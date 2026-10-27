package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelFileDescriptor
import android.os.ProxyFileDescriptorCallback
import android.os.storage.StorageManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.function.UnaryOperator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Packed native VFS compatibility and the retained failed ProxyFD architecture probe. */
@RunWith(AndroidJUnit4::class)
class PackedProxyDatabaseInstrumentedTest {
    @Test fun completeBaseAndKnownWayRevisionSeparateSameVersionOverlappingRegions() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val root=File(instrumentation.targetContext.cacheDir,"overlap-bindings-${System.nanoTime()}").apply{check(mkdirs())}
        val databases=mutableListOf<RuntimeMapDatabase>()
        try {
            val contexts=listOf("overlap-a","overlap-b","overlap-nodes").map { name ->
                val directory=File(root,name).apply{check(mkdirs())}
                for(file in requireNotNull(instrumentation.context.assets.list(name))) {
                    instrumentation.context.assets.open("$name/$file").use {input->File(directory,file).outputStream().use{input.copyTo(it)}}
                }
                RuntimeMapDatabase.open(File(directory,"context.yspc").path).also{databases+=it}
            }
            val identities=contexts.map{requireNotNull(it.database.amendmentBaseIdentity)}
            assertEquals(3,identities.toSet().size)
            val store=MapDataAmendmentStore(File(root,"edits"))
            fun text(index:Int,sql:String)=contexts[index].database.rawQuery(sql,null).use{check(it.moveToFirst());it.getString(0)}
            val sourceA=text(0,"SELECT rules_json FROM road_speed_rule_set WHERE way_id=10")
            val sourceB=text(1,"SELECT rules_json FROM road_speed_rule_set WHERE way_id=10")
            val rules=org.json.JSONObject(sourceA).apply {
                getJSONArray("tags").getJSONObject(0).getJSONArray("clauses").getJSONObject(0)
                    .put("limit",org.json.JSONObject().put("kind","numeric").put("kmh",30))
            }.toString()
            var row=MapDataAmendment("way:10","osm","way","10",identities[0],"overlap-shared-v1",
                MapDataAmendmentStore.waySourceRevision(sourceA),rules,mapOf("maxspeed" to "50"),"reviewer","source-review")
            store.put(row,0)
            fun speed(index:Int)=ConditionalSpeedRules.resolve(contexts[index].database,"10",1,50,false,
                countryCode="DEU",amendmentStore=store)?.kmh
            assertEquals(30,speed(0));assertEquals(60,speed(1));assertEquals(50,speed(2))
            row=row.copy(basisBundle=identities[1]);store.put(row,1)
            assertEquals(60,speed(1))
            row=row.copy(sourceRevision=MapDataAmendmentStore.waySourceRevision(sourceB));store.put(row,2)
            assertEquals(30,speed(1));assertEquals(50,speed(0))
            store.put(row.copy(basisBundle="overlap-shared-v1"),3)
            assertEquals(50,speed(0));assertEquals(60,speed(1));assertEquals(4,store.history(row.id).size)
        } finally {databases.forEach{it.close()};root.deleteRecursively()}
    }
    @Test fun nativeCursorPreservesBindingsTypesUnicodeMovementAndOwnerLifetime() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val file=File.createTempFile("packed-cursor-", ".sqlite",context.cacheDir)
        try {
            SQLiteDatabase.openOrCreateDatabase(file,null).use { db ->
                db.execSQL("CREATE TABLE sample(id INTEGER PRIMARY KEY,name TEXT,value REAL,bytes BLOB,empty TEXT)")
                db.execSQL("INSERT INTO sample VALUES(9007199254740993,?,1.25,X'00FF',NULL)",arrayOf("Straße α 🚗"))
                db.execSQL("INSERT INTO sample VALUES(9007199254740994,'second',2.5,X'',NULL)")
            }
            val owner=NativeRuntimeSqlDatabase(file.path,false)
            val rows=owner.rawQuery("SELECT id,name,value,bytes,empty FROM sample WHERE id>=? ORDER BY id",arrayOf("9007199254740993"))
            assertTrue(rows.moveToNext());assertEquals(9007199254740993L,rows.getLong(0))
            assertEquals("Straße α 🚗",rows.getString(1));assertEquals(1.25,rows.getDouble(2),0.0)
            assertTrue(rows.getBlob(3).contentEquals(byteArrayOf(0,-1)));assertTrue(rows.isNull(4))
            assertEquals(2,rows.count);assertEquals(0,rows.position)
            assertTrue(rows.moveToNext());assertEquals("second",rows.getString(1))
            assertEquals(0,rows.getBlob(3).size);assertFalse(rows.moveToNext());assertTrue(rows.isAfterLast)
            assertTrue(rows.moveToFirst());assertEquals(9007199254740993L,rows.getLong(0))
            owner.rawQuery("SELECT NULL,?",arrayOf("Unicode 🚗")).use { other ->
                assertTrue(other.moveToFirst());assertTrue(other.isNull(0));assertEquals("Unicode 🚗",other.getString(1))
                assertEquals(9007199254740993L,rows.getLong(0))
            }
            org.junit.Assert.assertThrows(android.database.sqlite.SQLiteException::class.java) {
                owner.rawQuery("DELETE FROM sample",null)
            }
            owner.close();assertTrue(rows.isClosed);assertFalse(owner.isOpen)
        } finally {file.delete()}
    }
    @org.junit.Ignore("API36 rejects SQLite reopening /proc/self/fd; native VFS is production path")
    @Test
    fun readonlyProxySupportsSQLiteViewsJoinsAndPackedGeometryCallback() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = File.createTempFile("packed-proxy-fixture-", ".sqlite", context.cacheDir)
        val geometry = "[[49.0000001,8.0000001],[49.0000002,8.0000002]]"
        try {
            SQLiteDatabase.openOrCreateDatabase(fixture, null).use { source ->
                source.execSQL("CREATE TABLE ways(way_id INTEGER PRIMARY KEY, street_name TEXT, maxspeed TEXT)")
                source.execSQL("CREATE TABLE road_speed_rule_set(way_id INTEGER PRIMARY KEY, rules_json TEXT)")
                source.execSQL("INSERT INTO ways VALUES(2532969814,'Straße α','50')")
                source.execSQL("INSERT INTO road_speed_rule_set VALUES(2532969814,'{\"conditional\":\"30 @ (22:00-06:00)\"}')")
                source.execSQL("CREATE VIEW way_geom AS SELECT way_id,ysp_way_points_json(way_id) AS points_json FROM ways")
            }
            val image = fixture.readBytes()
            val released = CountDownLatch(1)
            val reads = AtomicInteger()
            val thread = HandlerThread("packed-proxy-proof").apply { start() }
            var proxy: ParcelFileDescriptor? = null
            try {
                proxy = context.getSystemService(StorageManager::class.java).openProxyFileDescriptor(
                    ParcelFileDescriptor.MODE_READ_ONLY,
                    object : ProxyFileDescriptorCallback() {
                        override fun onGetSize(): Long = image.size.toLong()
                        override fun onRead(offset: Long, size: Int, data: ByteArray): Int {
                            require(offset >= 0 && size >= 0)
                            if (offset >= image.size) return 0
                            val count = minOf(size, data.size, image.size - offset.toInt())
                            image.copyInto(data, 0, offset.toInt(), offset.toInt() + count)
                            reads.incrementAndGet()
                            return count
                        }
                        override fun onRelease() {
                            released.countDown()
                            thread.quitSafely()
                        }
                    },
                    Handler(thread.looper),
                )
                SQLiteDatabase.openDatabase("/proc/self/fd/${proxy.fd}", null,
                    SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS).use { db ->
                    db.rawQuery("PRAGMA mmap_size=0", null).use { rows -> while (rows.moveToNext()) Unit }
                    db.execSQL("PRAGMA cache_size=-8192")
                    db.setCustomScalarFunction("ysp_way_points_json", UnaryOperator<String> { key ->
                        if (key == "2532969814") geometry else null
                    })
                    db.rawQuery("SELECT w.way_id,w.street_name,g.points_json,r.rules_json " +
                        "FROM ways w JOIN way_geom g USING(way_id) JOIN road_speed_rule_set r USING(way_id) " +
                        "WHERE w.way_id=? ORDER BY w.way_id LIMIT 1", arrayOf("2532969814")).use { rows ->
                        assertTrue(rows.moveToFirst())
                        assertEquals(2532969814L, rows.getLong(0))
                        assertEquals("Straße α", rows.getString(1))
                        assertEquals(geometry, rows.getString(2))
                        assertEquals("{\"conditional\":\"30 @ (22:00-06:00)\"}", rows.getString(3))
                        assertFalse(rows.moveToNext())
                    }
                    db.rawQuery("PRAGMA mmap_size", null).use { rows ->
                        assertTrue(rows.moveToFirst())
                        assertEquals(0L, rows.getLong(0))
                    }
                    assertTrue(db.isReadOnly)
                    assertTrue(reads.get() > 0)
                }
            } finally {
                if (proxy != null) {
                    proxy.close()
                    assertTrue("Proxy reader released", released.await(5, TimeUnit.SECONDS))
                } else thread.quitSafely()
                thread.join(5000)
                assertFalse("Proxy thread stopped", thread.isAlive)
            }
        } finally {
            fixture.delete()
            File(fixture.path + "-journal").delete()
            File(fixture.path + "-wal").delete()
            File(fixture.path + "-shm").delete()
        }
    }

    @Test
    fun compressedContextAndGeometryPreserveSQLAndLargeSourceIdentities() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val directory = File(instrumentation.targetContext.cacheDir, "packed-native-proof-${System.nanoTime()}")
        assertTrue(directory.mkdirs())
        try {
            for (name in listOf("source.sqlite", "fixture.context.yspc", "fixture.ways.yspg", "fixture.nodes.yspn")) {
                instrumentation.context.assets.open("packed-runtime/$name").use { input ->
                    File(directory, name).outputStream().use { output -> input.copyTo(output) }
                }
            }
            val sql = "SELECT w.way_id,w.speed,g.points_json FROM ways w JOIN way_geom g USING(way_id) ORDER BY w.way_id"
            val expected = SQLiteDatabase.openDatabase(File(directory,"source.sqlite").path,null,SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery(sql,null).use { rows -> buildList {
                    while (rows.moveToNext()) add(Triple(rows.getLong(0), rows.getInt(1), rows.getString(2)))
                } }
            }
            RuntimeMapDatabase.open(File(directory,"fixture.context.yspc").path).use { runtime ->
                val actual = runtime.database.rawQuery(sql,null).use { rows -> buildList {
                    while (rows.moveToNext()) add(Triple(rows.getLong(0),rows.getInt(1),rows.getString(2)))
                } }
                assertEquals(expected, actual)
                assertEquals(9007199254740993L, actual.last().first)
                val contextStats = org.json.JSONObject(requireNotNull(runtime.contextDiagnostics()))
                val geometryStats = org.json.JSONObject(requireNotNull(runtime.geometryDiagnostics()))
                assertEquals(0L,contextStats.getJSONObject("file").getLong("mapped_bytes"))
                assertEquals(0L,geometryStats.getJSONObject("file").getLong("mapped_bytes"))
                assertTrue(contextStats.getLong("block_cache_capacity_bytes") <= 2L*1024*1024)
                assertTrue(geometryStats.getLong("block_cache_capacity_bytes") <= 512L*1024)
                assertTrue(contextStats.getLong("block_cache_peak_bytes") <= 2L*1024*1024)
                assertTrue(geometryStats.getLong("block_cache_peak_bytes") <= 512L*1024)
                runtime.database.rawQuery("PRAGMA cache_size",null).use { cache ->
                    assertTrue(cache.moveToFirst());assertEquals(-1536,cache.getInt(0))
                }
                runtime.database.rawQuery("SELECT raw FROM restrictions WHERE way_id=20",null).use { rows ->
                    assertTrue(rows.moveToFirst())
                    assertEquals("30 @ (weight>7.5)",rows.getString(0))
                }
            }
            val native = RuntimePackedNative.nodesOpen(File(directory,"fixture.nodes.yspn").path)
            try {
                val raw = requireNotNull(RuntimePackedNative.nodeJson(native,"9007199254740993")).toString(Charsets.UTF_8)
                val node = org.json.JSONObject(raw)
                assertEquals(9007199254740993L,node.getLong("osm_node_id"))
                assertEquals("unresolved_direction",node.getString("binding_status"))
                assertEquals("30 @ (weight>7.5)",node.getJSONObject("tags").getString("maxspeed:hgv:conditional"))
                val nearby = org.json.JSONArray(requireNotNull(RuntimePackedNative.nodesQueryJson(native,49.0,8.0,10.0)).toString(Charsets.UTF_8))
                assertEquals(2,nearby.length())
                assertEquals("maxspeed",nearby.getJSONObject(0).getJSONObject("tags").getString("traffic_sign"))
            } finally { RuntimePackedNative.nodesClose(native) }
        } finally { directory.deleteRecursively() }
    }
}

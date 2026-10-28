package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class BundleDeltaInstrumentedTest {
    @Test fun nativeDeltaAppliesTransactionWithQuotedSemicolonsAndValidatesMaterializedDatabase() {
        val file = File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "delta-${UUID.randomUUID()}.sqlite")
        try {
            copyRtreeFixture(file)
            val backend = AndroidBundleDeltaDatabase()
            backend.applyPatch(file, "PRAGMA foreign_keys=OFF; BEGIN IMMEDIATE; UPDATE ways SET street_name='Rue de l''Église; south', maxspeed='30' WHERE way_id=1; DELETE FROM ways_rtree WHERE way_id=1; INSERT INTO ways_rtree VALUES(1,8,8.1,48,48.1); COMMIT;")
            backend.validate(file)
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT street_name,maxspeed FROM ways WHERE way_id=1", null).use { cursor ->
                    assertTrue(cursor.moveToFirst())
                    assertEquals("Rue de l'Église; south", cursor.getString(0))
                    assertEquals("30", cursor.getString(1))
                }
            }
            NativeRuntimeSqlDatabase(file.path, false).use { db ->
                db.rawQuery("SELECT count(*) FROM ways_rtree", null).use { cursor ->
                    assertTrue(cursor.moveToFirst()); assertEquals(1, cursor.getInt(0))
                }
            }
            assertFalse(File(file.path + "-wal").exists() && File(file.path + "-wal").length() > 0)
        } finally { SQLiteDatabase.deleteDatabase(file) }
    }

    @Test fun downloadedDeltaCannotModifySiblingJournalOrReplaceActiveBundle() {
        val root = File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "delta-boundary-${UUID.randomUUID()}")
        root.mkdirs()
        try {
            val source = File(root, "source.sqlite")
            copyRtreeFixture(source)
            val journal = File(root, "trip-journal/journal.sqlite")
            journal.parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(journal, null).use { db ->
                db.execSQL("CREATE TABLE events(value TEXT)"); db.execSQL("INSERT INTO events VALUES('private sentinel')")
            }
            val privateBytes = journal.readBytes()
            val data = source.readBytes()
            fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
            fun artifact(name: String, bytes: ByteArray) = """{"file":"$name","bytes":${bytes.size},"sha256":"${sha(bytes)}"}"""
            val manifestUrl = "https://fixture/manifest.json"
            val responses = mutableMapOf("https://fixture/speeds.sqlite" to data)
            fun manifest(version: String, delta: String = "null") = """{"format":"youspeed.v3.bundle.manifest","schema_version":1,"variant":"v3","region":"region","bundle_version":"$version","created_at_utc":"2026-09-02T00:00:00Z","min_app_version":"1.0","db":${artifact("speeds.sqlite", data)},"delta_index":$delta}""".toByteArray()
            responses[manifestUrl] = manifest("2026-09-01")
            val bootstrapper = BundleBootstrapper(root, object : HttpFetcher {
                override fun fetch(url: String) = requireNotNull(responses[url])
                override fun fetchToFile(url: String, destination: File, onProgress: ((Long, Long?) -> Unit)?) {
                    destination.writeBytes(fetch(url))
                }
            })
            val initial = bootstrapper.syncFromManifestUrl(manifestUrl)
            val state = File(root, "active_bundle.json").readBytes()
            val attack = "ATTACH DATABASE '${journal.path.replace("'", "''")}' AS private; DELETE FROM private.events; DETACH DATABASE private;".toByteArray()
            val index = """{"format":"youspeed.v3.delta.index","schema_version":1,"entries":[{"from_bundle_version":"2026-09-01","to_bundle_version":"2026-09-02","region":"region","delta_manifest_file":"deltas/attack.json"}]}""".toByteArray()
            responses["https://fixture/index.json"] = index
            responses["https://fixture/deltas/attack.json"] = """{"format":"youspeed.v3.delta.manifest","schema_version":1,"region":"region","from_bundle_version":"2026-09-01","to_bundle_version":"2026-09-02","patch":${artifact("attack.sql", attack)}}""".toByteArray()
            responses["https://fixture/deltas/attack.sql"] = attack
            responses[manifestUrl] = manifest("2026-09-02", artifact("index.json", index))
            assertThrows(android.database.sqlite.SQLiteException::class.java) { bootstrapper.syncFromManifestUrl(manifestUrl) }
            assertArrayEquals(privateBytes, journal.readBytes())
            assertArrayEquals(state, File(root, "active_bundle.json").readBytes())
            assertArrayEquals(data, File(initial.dbPath).readBytes())
            assertTrue(File(root, "staging").listFiles().orEmpty().isEmpty())
        } finally { root.deleteRecursively() }
    }

    private fun copyRtreeFixture(destination: File) {
        // API 36's framework SQLite may omit RTREE. The shipped private engine
        // consumes this real synthetic database without a test-only DDL API.
        InstrumentationRegistry.getInstrumentation().context.assets.open("bundle-delta-security/source.sqlite").use { input ->
            destination.outputStream().use { output -> input.copyTo(output) }
        }
    }
}

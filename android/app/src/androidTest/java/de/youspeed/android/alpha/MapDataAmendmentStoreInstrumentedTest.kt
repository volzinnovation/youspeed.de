package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MapDataAmendmentStoreInstrumentedTest {
    private val night="""{"version":1,"grammar":"youspeed-osm-speed-1","tags":[{"key":"maxspeed:conditional","raw":"30 @ (22:00-06:00)","role":"speed","vehicle":"all","direction":0,"conditional":true,"priority":0,"status":"supported","clauses":[{"limit":{"kind":"numeric","kmh":30},"condition":{"kind":"schedule","windows":[[1320,360]],"weekdays":[],"holidays":[]}}]}]}"""
    private val baseIdentity="ysp-base-v1:"+"a".repeat(64)+":"+"b".repeat(64)+":"+"c".repeat(64)
    private val atNight=Instant.parse("2026-10-27T22:30:00Z").toEpochMilli()
    private fun record(id:String="way:10",entity:String="way",source:String="10")=MapDataAmendment(
        id,"osm",entity,source,baseIdentity,baseIdentity,"source-fingerprint-1",night,
        mapOf("maxspeed" to "50","maxspeed:conditional" to "30 @ (22:00-06:00)"),"instrumented-test","source-evidence")
    private fun directory()=File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir,
        "amendment-test-${System.nanoTime()}").apply{check(mkdirs())}

    @Test fun revisionsPersistAndNumericAmendmentKeepsItsNightRestriction() {
        val directory=directory()
        try {
            val store=MapDataAmendmentStore(directory)
            assertEquals(1L,store.put(record(),0).revision)
            assertEquals(2L,store.amendNumericLimit("way:10",1,"maxspeed:conditional",0,25).revision)
            val reopened=MapDataAmendmentStore(directory)
            val saved=requireNotNull(reopened.latest("way:10"))
            val oldCondition=JSONObject(night).getJSONArray("tags").getJSONObject(0).getJSONArray("clauses").getJSONObject(0).getJSONObject("condition")
            val newCondition=JSONObject(saved.rulesJSON).getJSONArray("tags").getJSONObject(0).getJSONArray("clauses").getJSONObject(0).getJSONObject("condition")
            assertEquals(oldCondition.toString(),newCondition.toString())
            assertEquals(record().rawSourceTags,saved.rawSourceTags)
            val nightContext=ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1)
            assertEquals(25,reopened.resolve("10",baseIdentity,1,nightContext,50,false)?.kmh)
            val day=nightContext.copy(atMs=Instant.parse("2026-10-27T12:00:00Z").toEpochMilli())
            assertEquals(50,reopened.resolve("10",baseIdentity,1,day,50,false)?.kmh)
            assertNull(reopened.resolve("10","new-generation",1,nightContext,50,false))
            val conflict=assertThrows(MapDataAmendmentStore.Conflict::class.java){reopened.put(saved,1)}
            assertEquals(2L,conflict.actualRevision)
            reopened.tombstone("way:10",2)
            assertNull(MapDataAmendmentStore(directory).resolve("10",baseIdentity,1,nightContext,50,false))
            assertEquals(listOf(1L,2L,3L),reopened.history("way:10").map{it.revision})
        } finally {directory.deleteRecursively()}
    }
    @Test fun persistedNodePassageCannotAuthorizeASeparateDrive() {
        val directory=directory()
        try {
            val store=MapDataAmendmentStore(directory);val source="9007199254740993"
            store.put(record("node:$source","node",source).copy(direction=1,boundWayId="10",bindingVerified=true,
                passageEvidenceId="historical-passage",nodeJSON="{\"osm_node_id\":9007199254740993}"),0)
            val context=ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1)
            assertNull(store.resolve("10",baseIdentity,1,context,50,false))
            assertNull(store.resolve("20",baseIdentity,1,context,50,false,setOf(source)))
            assertEquals(30,store.resolve("10",baseIdentity,1,context,50,false,setOf(source))?.kmh)
            assertTrue(store.resolve("10",baseIdentity,null,context,50,false,setOf(source))?.unresolved==true)
            assertEquals(source,MapDataAmendmentStore(directory).latest("node:$source")?.sourceId)
        } finally {directory.deleteRecursively()}
    }
    @Test fun nodePassageUsesDirectedCrossingAndKeepsProofUntilItsReviewedScopeEnds() {
        val directory=directory()
        try {
            val source="9007199254740993";val store=MapDataAmendmentStore(directory)
            val node="""{"osm_node_id":9007199254740993,"latitude":0,"longitude":0.001,"memberships":[{"way_id":10,"coordinate_verified":true,"chainage_m":111.19492664455875}]}"""
            store.put(record("node:$source","node",source).copy(direction=1,boundWayId="10",bindingVerified=true,
                passageEvidenceId="reviewed-anchor",nodeJSON=node,scopeEndM=250.0),0)
            val file=File(directory,"source.sqlite")
            SQLiteDatabase.openOrCreateDatabase(file,null).use {db->
                db.execSQL("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
                db.execSQL("INSERT INTO metadata VALUES('packed_generation','fixture-1')")
                db.execSQL("CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT)")
                db.execSQL("INSERT INTO way_geom VALUES(10,'[[0,0],[0,0.003]]')")
            }
            InventorySignDatabase(file.path,store,baseIdentity).use {database->
                val runtime=InventorySignRuntime{}
                fun fix(lon:Double,seconds:Long,direction:Int=1,heading:Double=90.0)=InventorySignFix(0.0,lon,
                    Instant.ofEpochMilli(atNight+seconds*1000),5.0,"10",direction,true,baseIdentity,heading,5.0)
                fun evaluate(fix:InventorySignFix)=runtime.evaluate(database.read(fix.latitude,fix.longitude,fix.wayId,fix.direction),
                    fix,fix.at,false,false)
                val before=fix(.0008,0);assertTrue(evaluate(before).passedAmendedNodeIds.isEmpty())
                val crossed=fix(.0011,1);val decision=evaluate(crossed)
                assertEquals(setOf(source),decision.passedAmendedNodeIds)
                val base=SpeedLookupResult("10","primary","road","road",null,50,false,null,null,null,
                    false,"settlement:maxspeed_type:high",0.0,1,1,emptyList(),0.0,0.0,false,null,emptyList(),emptySet(),emptySet(),
                    emptySet(),emptySet(),null,null,false,false,0,emptyList(),emptyList(),DerivedSpeedSource.EXPLICIT_TAG)
                val amended=database.applyNodeAmendments(base,crossed,decision,"DEU",atNight)
                assertEquals(30,amended.speedLimitKmh);assertNotNull(amended.conditionalRuleContext)
                val inventory=base.copy(speedLimitKmh=70,bundleSpeedProvenance=BundleSpeedProvenance("inventory_sign","mobidata-bw-vzk"))
                assertEquals(inventory,database.applyNodeAmendments(inventory,crossed,decision,"DEU",atNight))
                assertEquals(30,store.resolve("10",baseIdentity,1,ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1),
                    50,false,decision.passedAmendedNodeIds)?.kmh)
                assertEquals(setOf(source),evaluate(fix(.00099,2)).passedAmendedNodeIds)
                assertEquals(setOf(source),evaluate(fix(.002,2)).passedAmendedNodeIds)
                val uncertain=fix(.002,3,direction=0,heading=Double.NaN)
                val held=evaluate(uncertain).passedAmendedNodeIds
                assertEquals(setOf(source),held)
                assertTrue(store.resolve("10",baseIdentity,null,ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU"),
                    50,false,held)?.unresolved==true)
                assertTrue(evaluate(fix(.0023,4)).passedAmendedNodeIds.isEmpty())
                runtime.finish(Instant.ofEpochMilli(atNight+5000))
                assertTrue(evaluate(fix(.002,6)).passedAmendedNodeIds.isEmpty())
                runtime.finish(Instant.ofEpochMilli(atNight+6500))
                val initialize=fix(.0011,7);assertEquals(setOf(source),evaluate(initialize).passedAmendedNodeIds)
                assertTrue(evaluate(fix(.0011,8,direction=-1,heading=270.0)).passedAmendedNodeIds.isEmpty())
                runtime.finish(Instant.ofEpochMilli(atNight+8500))
                assertEquals(setOf(source),evaluate(fix(.0011,9)).passedAmendedNodeIds)
                val edited=requireNotNull(store.latest("node:$source"))
                store.amendNumericLimit(edited.id,edited.revision,"maxspeed:conditional",0,25)
                assertEquals(setOf(source),evaluate(fix(.0011,10,direction=0,heading=Double.NaN)).passedAmendedNodeIds)
                val rulesOnly=requireNotNull(store.latest(edited.id))
                store.put(rulesOnly.copy(passageEvidenceId="new-reviewed-binding"),rulesOnly.revision)
                assertTrue(evaluate(fix(.0011,11,direction=0,heading=Double.NaN)).passedAmendedNodeIds.isEmpty())
            }
        } finally {directory.deleteRecursively()}
    }
    @Test fun validityExpiryReevaluatesOriginalBundleInsteadOfRetainingTheAmendment() {
        val directory=directory()
        try {
            val store=MapDataAmendmentStore(directory);val until=atNight/1000.0+60
            store.put(record().copy(validUntilUTC=until),0)
            SQLiteDatabase.create(null).use { db ->
                db.execSQL("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
                db.execSQL("INSERT INTO metadata VALUES('packed_generation','fixture-1')")
                db.execSQL("CREATE TABLE road_speed_capability(version INTEGER,grammar TEXT)")
                db.execSQL("INSERT INTO road_speed_capability VALUES(1,'youspeed-osm-speed-1')")
                db.execSQL("CREATE TABLE road_speed_rule_set(way_id INTEGER PRIMARY KEY,rules_json TEXT)")
                val baseline=JSONObject(night).apply {
                    getJSONArray("tags").getJSONObject(0).apply {
                        put("conditional",false);getJSONArray("clauses").getJSONObject(0)
                            .put("limit",JSONObject().put("kind","numeric").put("kmh",50)).put("condition",JSONObject().put("kind","true"))
                    }
                }.toString()
                db.execSQL("INSERT INTO road_speed_rule_set VALUES(10,?)",arrayOf(baseline))
                val result=ConditionalSpeedRules.resolve(db,"10",1,50,false,atNight,"Europe/Berlin","DEU",store,baseIdentity)
                assertEquals(30,result?.kmh)
                assertEquals(50,result?.reevaluation?.evaluate(atNight+61000)?.kmh)
            }
            val untrusted=ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1,clockTrusted=false)
            assertTrue(store.resolve("10",baseIdentity,1,untrusted,50,false)?.unresolved==true)
        } finally {directory.deleteRecursively()}
    }
    @Test fun inactiveNodeClauseReevaluatesTheUnderlyingConditionalAtEveryClockTick() {
        val directory=directory()
        try {
            val store=MapDataAmendmentStore(directory);val source="9007199254740993"
            store.put(record("node:$source","node",source).copy(direction=1,boundWayId="10",bindingVerified=true,
                passageEvidenceId="reviewed-passage"),0)
            val original=JSONObject(night).apply {
                getJSONArray("tags").getJSONObject(0).getJSONArray("clauses").getJSONObject(0).apply {
                    put("limit",JSONObject().put("kind","numeric").put("kmh",40))
                    put("condition",JSONObject().put("kind","schedule").put("windows",org.json.JSONArray("[[600,660]]")))
                }
            }.toString()
            val ten=Instant.parse("2026-10-27T09:30:00Z").toEpochMilli() // 10:30 Berlin
            val baseline=ConditionalSpeedRules.Reevaluation(original,50,false,1,"DEU","Europe/Berlin")
            val initial=baseline.evaluate(ten).copy(reevaluation=baseline)
            assertEquals(40,initial.kmh)
            val amended=store.resolve("10",baseIdentity,1,ConditionalSpeedRules.Context(ten,"Europe/Berlin","DEU",1),
                initial.kmh,false,setOf(source),baselineResult=initial)
            assertEquals(40,amended?.kmh)
            assertEquals(50,amended?.reevaluation?.evaluate(ten+3600000)?.kmh)
            assertEquals(30,amended?.reevaluation?.evaluate(atNight)?.kmh)
            var malformed=baseline
            repeat(9){malformed=baseline.copy(baselineReevaluations=listOf(malformed))}
            assertTrue(malformed.evaluate(ten).unresolved)
            assertEquals("map_amendment_reevaluation_depth",malformed.evaluate(ten).reason)
            val unknownBase=ConditionalSpeedRules.Result(null,false,true,"electronic_sign_state_unknown")
            val unknown=store.resolve("10",baseIdentity,1,ConditionalSpeedRules.Context(ten,"Europe/Berlin","DEU",1),
                50,false,setOf(source),baselineResult=unknownBase)
            assertTrue(unknown?.unresolved==true)
            assertTrue(unknown?.reevaluation?.evaluate(ten+3600000)?.unresolved==true)
            val expiry=unknown?.reevaluation?.copy(validUntilUTC=ten/1000.0+60)?.evaluate(ten+61000)
            assertTrue(expiry?.unresolved==true);assertEquals("electronic_sign_state_unknown",expiry?.reason)
            store.put(record(),0)
            assertTrue(store.resolve("10",baseIdentity,1,ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1),
                50,false,setOf(source),baselineResult=initial)?.unresolved==true)
        } finally {directory.deleteRecursively()}
    }
    @Test fun newLocalNodePersistsAmendsRestrictionsAndNeedsCurrentDirectedPassage() {
        val directory=directory()
        try {
            val source=MapDataAmendmentStore.newLocalNodeSourceId()
            assertTrue(MapDataAmendmentStore.isLocalNodeSourceId(source))
            val node=JSONObject().put("source_id",source).put("latitude",0).put("longitude",.001)
                .put("tags",JSONObject().put("traffic_sign","maxspeed").put("maxspeed:conditional","30 @ (22:00-06:00)"))
                .put("memberships",org.json.JSONArray()).put("binding_status","local_reviewed").toString()
            val initial=record(source,"node",source).copy(sourceNamespace="local",nodeJSON=node,
                rawSourceTags=mapOf("traffic_sign" to "maxspeed","maxspeed:conditional" to "30 @ (22:00-06:00)"))
            val store=MapDataAmendmentStore(directory);store.put(initial,0)
            val reopened=MapDataAmendmentStore(directory)
            assertEquals(source,reopened.latest(source)?.sourceId)
            assertFalse(JSONObject(requireNotNull(reopened.latest(source)?.nodeJSON)).has("osm_node_id"))
            val context=ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1)
            assertNull(reopened.resolve("10",baseIdentity,1,context,50,false,setOf(source)))
            val bound=reopened.put(requireNotNull(reopened.latest(source)).copy(direction=1,boundWayId="10",bindingVerified=true,
                passageEvidenceId="reviewed-local-binding",stationChainageM=100.0,scopeStartM=100.0,scopeEndM=200.0),1)
            val amended=reopened.amendNumericLimit(source,bound.revision,"maxspeed:conditional",0,25)
            assertEquals(initial.rawSourceTags,amended.rawSourceTags)
            val station=requireNotNull(AmendedNodePassageRuntime.station(amended,null,300.0))
            val passages=AmendedNodePassageRuntime()
            fun fix(chainage:Double,seconds:Long)=InventorySignFix(0.0,.001,Instant.ofEpochMilli(atNight+seconds*1000),
                5.0,"10",1,true,baseIdentity,90.0,5.0) to chainage
            val before=fix(90.0,0);assertTrue(passages.evaluate(listOf(station),before.first,before.first.at,before.second,90.0).isEmpty())
            val crossed=fix(110.0,1);val proof=passages.evaluate(listOf(station),crossed.first,crossed.first.at,crossed.second,90.0)
            assertEquals(setOf(source),proof)
            assertEquals(25,reopened.resolve("10",baseIdentity,1,context,50,false,proof)?.kmh)
            val day=context.copy(atMs=Instant.parse("2026-10-27T12:00:00Z").toEpochMilli())
            assertEquals(50,reopened.resolve("10",baseIdentity,1,day,50,false,proof)?.kmh)
            val end=fix(200.0,2);assertTrue(passages.evaluate(listOf(station),end.first,end.first.at,end.second,90.0).isEmpty())
            reopened.tombstone(source,amended.revision)
            assertNull(MapDataAmendmentStore(directory).resolve("10",baseIdentity,1,context,50,false,proof))
            val created=reopened.createLocalNode(0.0,.002,initial.rawSourceTags,night,baseIdentity,"test","survey")
            assertTrue(MapDataAmendmentStore.isLocalNodeSourceId(created.sourceId));assertEquals(1L,created.revision)
            assertFalse(created.bindingVerified)
        } finally {directory.deleteRecursively()}
    }
    @Test fun sameVersionOverlappingRegionAndChangedNodesCannotReuseReviewedAmendments() {
        val directory=directory()
        try {
            val store=MapDataAmendmentStore(directory)
            store.put(record(),0)
            val context=ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1)
            val otherContext="ysp-base-v1:"+"d".repeat(64)+":"+"b".repeat(64)+":"+"c".repeat(64)
            val otherNodes="ysp-base-v1:"+"a".repeat(64)+":"+"b".repeat(64)+":"+"e".repeat(64)
            assertEquals(30,store.resolve("10",baseIdentity,1,context,50,false)?.kmh)
            assertNull(store.resolve("10",otherContext,1,context,50,false))
            assertNull(store.resolve("10",otherNodes,1,context,50,false))
            val legacy=record("legacy:10").copy(basisBundle="2026-10-27-packed-v1",originalBundle="2026-10-27-packed-v1")
            store.put(legacy,0)
            assertNull(store.resolve("10","2026-10-27-packed-v1",1,context,50,false))
            assertEquals("2026-10-27-packed-v1",store.latest(legacy.id)?.basisBundle)
            store.tombstone("way:10",1)
            assertNull(store.resolve("10",baseIdentity,1,context,50,false))
            store.put(requireNotNull(store.latest(legacy.id)).copy(basisBundle=baseIdentity),1)
            assertEquals(30,store.resolve("10",baseIdentity,1,context,50,false)?.kmh)
        } finally {directory.deleteRecursively()}
    }
    @Test fun knownSourceRevisionSchemesRejectMismatchedSourceSnapshots() {
        val directory=directory()
        try {
            val store=MapDataAmendmentStore(directory)
            store.put(record().copy(sourceRevision="way-rule-set-sha256:"+MapDataAmendmentStore.sourceSHA256(night)),0)
            val context=ConditionalSpeedRules.Context(atNight,"Europe/Berlin","DEU",1)
            assertNull(store.resolve("10",baseIdentity,1,context,50,false))
            assertNull(store.resolve("10",baseIdentity,1,context,50,false,sourceWayRulesJSON="{}"))
            assertEquals(30,store.resolve("10",baseIdentity,1,context,50,false,sourceWayRulesJSON=night)?.kmh)
            val node="{\"osm_node_id\":9007199254740993}"
            val row=record("node:9007199254740993","node","9007199254740993").copy(nodeJSON=node,
                sourceRevision="node-json-sha256:"+MapDataAmendmentStore.sourceSHA256(node))
            store.put(row,0)
            assertThrows(IllegalArgumentException::class.java){store.put(row.copy(nodeJSON="{}"),1)}
        } finally {directory.deleteRecursively()}
    }
}

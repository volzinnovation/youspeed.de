package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Runs the same shared SQL, contexts and decisions as MatcherSequenceParityTests on iPhone. */
class MatcherSequenceParityInstrumentedTest {
    @Test fun sharedHistoryAndTunnelCorpusColdAndWarm() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val corpus = Json.parseToJsonElement(context.assets.open("matcher/sequence-v1.json").bufferedReader().use { it.readText() }).jsonObject
        assertEquals(1, corpus.getValue("schemaVersion").jsonPrimitive.int)
        for (raw in corpus.getValue("scenarios").jsonArray) {
            val scenario = raw.jsonObject
            val file = File(context.cacheDir, "sequence-parity-${UUID.randomUUID()}.sqlite")
            try {
                val sql = context.assets.open("matcher/fixtures/${scenario.string("fixture")}").bufferedReader().use { it.readText() }
                SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
                    SqliteFixtureSupport.execSql(db, sql)
                }
                val profile = MatcherDebugProfile.entries.first { it.storageValue == scenario.string("profile") }
                V3SpeedLimitLookup(file.path, matchingModel = profile.lookupModel).use { service ->
                    repeat(3) { iteration ->
                        val result = service.lookup(scenario.double("lat")!!, scenario.double("lon")!!,
                            scenario.double("radiusM")!!, 32, scenario.double("headingDeg"), scenario.double("speedKmh"),
                            scenario.double("horizontalAccuracyM"), scenario.int("gpsSignalBars"),
                            scenario["context"]?.takeUnless { it is JsonNull }?.jsonObject?.nativeContext())
                        assertEquals("${scenario.string("id")}/$iteration: ${result.selectionTrace}", scenario.string("wayID"), result.wayId)
                        assertEquals("${scenario.string("id")}/$iteration", scenario.getValue("isTunnelSegment").jsonPrimitive.boolean, result.isTunnelSegment)
                    }
                }
            } finally { SQLiteDatabase.deleteDatabase(file) }
        }
    }

    private fun JsonObject.nativeContext() = WayMatchContext(
        preferredWayId = string("preferredWayID"), preferredHighway = string("preferredHighway"),
        preferredEndpointProximityM = double("preferredEndpointProximityM"), recentWayIds = strings("recentWayIDs"),
        recentFixes = this["recentFixes"]?.jsonArray?.map { raw -> raw.jsonObject.let {
            WayMatchRecentFix(it.double("lat")!!, it.double("lon")!!, it.double("headingDeg"), it.double("headingAccuracyDeg"),
                it.double("speedKmh"), it.double("horizontalAccuracyM"), it.int("gpsSignalBars"))
        } } ?: emptyList(), preferredStreetRef = string("preferredStreetRef"), activeStreetRef = string("activeStreetRef"),
        preferredStreetName = string("preferredStreetName"), recentStreetRefs = strings("recentStreetRefs"),
        recentTunnelCandidateWayIds = strings("recentTunnelCandidateWayIDs").toSet(), recentTunnelCandidateRefs = strings("recentTunnelCandidateRefs").toSet(),
        recentTunnelApproachWayIds = strings("recentTunnelApproachWayIDs").toSet(), recentTunnelApproachRefs = strings("recentTunnelApproachRefs").toSet(),
        tunnelApproachFixCount = int("tunnelApproachFixCount") ?: 0, tunnelApproachBaselineAccuracyM = double("tunnelApproachBaselineAccuracyM"),
        tunnelApproachBaselineSignalBars = int("tunnelApproachBaselineSignalBars"), isInTunnelMode = this["isInTunnelMode"]?.jsonPrimitive?.boolean ?: false)
    private fun JsonObject.string(key: String) = this[key]?.jsonPrimitive?.contentOrNull
    private fun JsonObject.double(key: String) = this[key]?.jsonPrimitive?.doubleOrNull
    private fun JsonObject.int(key: String) = this[key]?.jsonPrimitive?.intOrNull
    private fun JsonObject.strings(key: String) = this[key]?.jsonArray?.map { it.jsonPrimitive.content } ?: emptyList()
}

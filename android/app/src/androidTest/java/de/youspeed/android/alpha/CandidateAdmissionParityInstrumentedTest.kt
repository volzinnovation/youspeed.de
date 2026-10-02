package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CandidateAdmissionParityInstrumentedTest {
    @Test fun sharedDenseCandidateAndProfileCorpus() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val corpus = Json.parseToJsonElement(context.assets.open("matcher/candidate-admission-v1.json").bufferedReader().use { it.readText() }).jsonObject
        val sql = context.assets.open("matcher/candidate-admission-v1.sql").bufferedReader().use { it.readText() }
        assertEquals(1, corpus.getValue("schemaVersion").jsonPrimitive.int)
        for (variant in corpus.getValue("variants").jsonArray.map { it.jsonPrimitive.content }) {
            val file = File(context.cacheDir, "candidate-parity-${UUID.randomUUID()}.sqlite")
            try {
                SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
                    sql.split(';').map(String::trim).filter(String::isNotEmpty).forEach(db::execSQL)
                    val table = when (variant) { "general_rtree" -> "ways_rtree"; "network_rtree" -> "surface_way_network_rtree"; else -> null }
                    if (table != null) {
                        SqliteFixtureSupport.createRtree(db, table)
                        db.execSQL("INSERT INTO $table SELECT way_id,min_lon,max_lon,min_lat,max_lat FROM ways ORDER BY way_id DESC")
                    }
                }
                V3SpeedLimitLookup(file.path, countryCode = "DEU").use { service ->
                    for (raw in corpus.getValue("scenarios").jsonArray) {
                        val scenario = raw.jsonObject
                        val admitted = service.admittedWayIdsForTesting(scenario.getValue("latitude").jsonPrimitive.double,
                            scenario.getValue("longitude").jsonPrimitive.double, scenario.getValue("radiusM").jsonPrimitive.double,
                            scenario.getValue("maxCandidates").jsonPrimitive.int)
                        assertEquals("$variant/${scenario.getValue("id")}", scenario.getValue("wayIDs").jsonArray.map { it.jsonPrimitive.content }, admitted)
                    }
                }
                val expected = corpus.getValue("lookup").jsonObject
                for (profile in listOf(MatcherDebugProfile.M7, MatcherDebugProfile.M8, MatcherDebugProfile.M9,
                                       MatcherDebugProfile.M10, MatcherDebugProfile.M11, MatcherDebugProfile.M12)) {
                    V3SpeedLimitLookup(file.path, countryCode = "DEU", matchingModel = profile.lookupModel).use { service ->
                        repeat(10) {
                            val result = service.lookup(expected.getValue("latitude").jsonPrimitive.double,
                                expected.getValue("longitude").jsonPrimitive.double, 200.0, 2, 90.0,
                                speedKmh = 40.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4)
                            assertEquals("$variant/$profile", expected.getValue("wayID").jsonPrimitive.content, result.wayId)
                            assertEquals("$variant/$profile", expected.getValue("speedLimitKmh").jsonPrimitive.int, result.speedLimitKmh)
                        }
                    }
                }
            } finally { file.delete() }
        }
    }
}

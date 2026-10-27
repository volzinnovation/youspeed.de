package de.youspeed.android.alpha
import java.io.File
import kotlinx.serialization.json.*

fun main(args: Array<String>) {
    val vectors = Json.parseToJsonElement(File(args[0]).readText()).jsonObject.getValue("scenarios").jsonArray
    val results = vectors.map { raw ->
        val scenario = raw.jsonObject; val session = TSRApplicabilitySession()
        buildJsonObject {
            put("id", scenario.getValue("id"))
            put("frames", JsonArray(scenario.getValue("batches").jsonArray.map {
                TSRApplicabilityJson.encodeDiagnostic(session.evaluate(TSRApplicabilityJson.decodeBatch(it.jsonObject)))
            }))
            put("liveMapFixSnapshots", JsonArray(scenario.getValue("batches").jsonArray.mapNotNull {
                val batch = TSRApplicabilityJson.decodeBatch(it.jsonObject)
                val road = batch.road ?: return@mapNotNull null
                val geometry = TSRMapGeometry(road.wayId, road.localTangentDeg, road.roadClass,
                    road.hypotheses, road.branches, road.capabilities, road.postedSpeedKmh)
                TSRApplicabilityJson.encodeRoad(TSRMapFix(geometry, road.capturedAtMs, road.horizontalAccuracyM,
                    road.courseDeg, road.courseAccuracyDeg, road.matchedStable).snapshot(batch.scope))
            }))
        }
    }
    print(JsonArray(results))
}

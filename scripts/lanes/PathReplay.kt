package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*

/** Host-only fixture adapter. Algorithms are compiled directly from the production sources. */
private fun JsonObject.s(key: String) = getValue(key).jsonPrimitive.content
private fun JsonObject.d(key: String) = getValue(key).jsonPrimitive.double
private fun JsonObject.b(key: String) = getValue(key).jsonPrimitive.boolean
private fun pose(o: JsonObject) = RoadPathPose(o.s("scope"),o.d("timeSeconds"),o.d("eastMeters"),o.d("northMeters"),
    o.d("courseDegrees"),o.d("speedMetersPerSecond"),o.d("horizontalAccuracyMeters"),o.d("courseAccuracyDegrees"))
private fun camera(o: JsonObject) = RoadPathCalibration(o.s("revision"),o.b("verified"),o.d("fx"),o.d("fy"),o.d("cx"),o.d("cy"),
    o.d("yawDegrees"),o.d("pitchDegrees"),o.d("rollDegrees"),o.d("heightMeters"),o["lateralOffsetMeters"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.double)
private fun corridor(o: JsonObject) = RoadPathCorridor(o.s("id"),o.s("role"),o.getValue("polygon").jsonArray.map {
    val p=it.jsonObject; RoadPathPoint(p.d("x"),p.d("y")) },o.d("confidence"),o.b("independentlySupported"),o.d("roadsideMarginMeters"))
private fun result(r: RoadPathResult) = buildJsonObject {
    put("classification",r.classification); put("reason",r.reason); put("trackId",r.trackId)
    put("eastMeters",r.eastMeters); put("northMeters",r.northMeters); put("heightMeters",r.heightMeters)
    put("rangeMeters",r.rangeMeters); put("residualMeters",r.residualMeters); put("baselineMeters",r.baselineMeters)
    put("parallaxDegrees",r.parallaxDegrees); put("supportingObservations",r.supportingObservations)
    put("uncertaintyEastMeters",r.uncertaintyEastMeters); put("uncertaintyNorthMeters",r.uncertaintyNorthMeters)
    put("shadowOnly",r.shadowOnly); put("oldestPoseTimeSeconds",r.oldestPoseTimeSeconds)
    put("newestPoseTimeSeconds",r.newestPoseTimeSeconds); put("maximumPoseAgeSeconds",r.maximumPoseAgeSeconds)
}
fun main(args: Array<String>) {
    require(args.size==1)
    val input=Json.parseToJsonElement(File(args[0]).readText()).jsonObject
    val output=buildJsonObject {
        putJsonArray("boundaryCases") {
            for (value in input.getValue("boundaryCases").jsonArray) {
                val c=value.jsonObject
                val r=RoadBoundaryDetector().detect(File(c.s("pixelsPath")).readBytes(),c.getValue("width").jsonPrimitive.int,
                    c.getValue("height").jsonPrimitive.int,0.8,c["maximumOperations"]?.jsonPrimitive?.int ?: 250_000)
                add(buildJsonObject {
                    put("id",c.s("id")); put("timestampSeconds",r.timestampSeconds); put("budgetExceeded",r.budgetExceeded); put("operationCount",r.operationCount)
                    putJsonArray("boundaries") { r.boundaries.forEach { b -> add(buildJsonObject {
                        put("confidence",b.confidence); put("cue",b.cue.name.lowercase()); put("supportRows",b.supportRows)
                        putJsonArray("points") { b.points.forEach { p -> add(buildJsonArray { add(p.x); add(p.y) }) } }
                    }) } }
                    putJsonArray("corridors") { r.corridors.forEach { c -> add(buildJsonObject {
                        put("leftBoundaryIndex",c.leftBoundaryIndex); put("rightBoundaryIndex",c.rightBoundaryIndex); put("confidence",c.confidence)
                    }) } }
                })
            }
        }
        putJsonArray("pathCases") {
            for (value in input.getValue("pathCases").jsonArray) {
                val c=value.jsonObject; val scope=c.s("scope"); val now=c.d("nowSeconds")
                val camera=c["calibration"]?.takeUnless { it is JsonNull }?.jsonObject?.let(::camera)
                val poses=c.getValue("poses").jsonArray.map { pose(it.jsonObject) }
                val observations=c.getValue("observations").jsonArray.map { e -> val o=e.jsonObject
                    RoadPathObservation(o.s("trackId"),o.s("scope"),o.s("calibrationRevision"),o.d("timeSeconds"),o.d("imageX"),o.d("imageY")) }
                val corridors=c.getValue("corridors").jsonArray.map { corridor(it.jsonObject) }
                val r=RoadPathEvidence.evaluate(scope,now,observations,poses,camera,corridors)
                val aligned=RoadPathEvidence.causalPoseAt(scope,now,poses)
                val projected=if (aligned!=null && camera!=null) RoadPathEvidence.projectGround(0.5,0.7,aligned,camera) else null
                add(buildJsonObject {
                    put("id",c.s("id")); put("result",result(r))
                    putJsonArray("roles") { RoadPathEvidence.inferCorridorRoles(scope,now,poses,corridors).forEach { add(it.role) } }
                    if (aligned!=null) putJsonObject("alignedPose") {
                        put("timeSeconds",aligned.timeSeconds); put("eastMeters",aligned.eastMeters); put("northMeters",aligned.northMeters)
                        put("horizontalAccuracyMeters",aligned.horizontalAccuracyMeters)
                    }
                    if (projected!=null) putJsonObject("projectedGround") { put("x",projected.x); put("y",projected.y) }
                })
            }
        }
    }
    print(output.toString())
}

package de.youspeed.android.alpha

import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.json.*

// Host-only value adapters for camera-independent production lane code. No Android
// camera/bitmap functionality is stubbed or exercised by this semantic comparison.
internal data class LaneImageGeometry(val width:Int,val height:Int,val rotationDegrees:Int,val sensorToBuffer:List<Double>)
data class NormalizedTrafficSignBoundingBox(val x:Double,val y:Double,val width:Double,val height:Double)

private fun JsonObject.s(key:String)=getValue(key).jsonPrimitive.content
private fun JsonObject.i(key:String)=getValue(key).jsonPrimitive.int
private fun JsonObject.d(key:String)=getValue(key).jsonPrimitive.double
private fun JsonObject.flag(key:String)=get(key)?.jsonPrimitive?.boolean ?: false
private fun points(values:List<LanePoint>)=buildJsonArray { values.forEach { p -> add(buildJsonArray { add(p.x);add(p.y) }) } }
private fun boundaries(values:List<RoadBoundaryEvidence>)=buildJsonArray { values.forEach { b -> add(buildJsonObject {
    put("points",points(b.points));put("observedSegments",buildJsonArray { b.observedSegments.forEach { add(points(it)) } })
    put("confidence",b.confidence);put("cue",b.cue.name.lowercase());put("supportRows",b.supportRows)
    put("provenance",b.provenance.name.lowercase());put("lastFreshTimestampSeconds",b.lastFreshTimestampSeconds)
    put("evidenceAgeSeconds",b.evidenceAgeSeconds);put("trackedAnchorCount",b.trackedAnchorCount)
    put("geometryConfidence",b.geometryConfidence);put("paintOccupancy",b.paintOccupancy)
}) } }

/** Image-only recorded semantic parity; refuses metadata it cannot reproduce faithfully. */
fun main(args:Array<String>) {
    require(args.size==2) { "normalized-manifest.json output.ndjson" }
    val manifest=Json.parseToJsonElement(File(args[0]).readText()).jsonObject
    require(manifest.i("schemaVersion")==1 && manifest.flag("previewMode"))
    val rows=manifest.getValue("frames").jsonArray
    require(rows.size in 1..100)
    val destination=File(args[1]);check(!destination.exists())
    fun session()=RoadPathSession(previewMode=true,
        detectionOptions=RoadBoundaryDetectionOptions(manifest.flag("useSearchBands"),manifest.flag("groupFragments")),
        fragmentTracking=manifest.flag("fragmentTracking"),retainTentativeIdentity=manifest.flag("retainTentativeIdentity"),
        jointSelection=manifest.flag("jointSelection"),nowNanos={ 0L })
    var current=session();var sequence:String?=null;var previousTime=Double.NEGATIVE_INFINITY
    val seen=mutableSetOf<String>()
    destination.bufferedWriter().use { writer -> for (value in rows) {
        val row=value.jsonObject;val id=row.s("id");val seq=row.s("sequenceId");val time=row.d("time")
        require(seen.add(id) && id.isNotBlank() && seq.isNotBlank())
        require(row.i("width") in 64..384 && row.i("height") in 64..216 && time.isFinite())
        require(listOf("calibration","visualCalibration").all { row[it]==null || row[it] is JsonNull }) {
            "Image-only adapter refuses calibration metadata"
        }
        require(row["locationFixes"]==null || row["locationFixes"] is JsonNull || row["locationFixes"]!!.jsonArray.isEmpty()) {
            "Image-only adapter refuses motion metadata"
        }
        if (sequence!=seq) { current=session();sequence=seq;previousTime=Double.NEGATIVE_INFINITY }
        require(time>previousTime);previousTime=time
        val bytes=File(row.s("grayPath")).readBytes()
        require(bytes.size==row.i("width")*row.i("height"))
        val hash=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        require(hash==row.s("graySha256"))
        val geometry="encoded:$seq:${row.i("decodedWidth")}x${row.i("decodedHeight")}"
        val frame=RoadPathCameraFrame(bytes,row.i("width"),row.i("height"),time,geometry,null,true,0.0,0L,
            rawWidth=row.i("decodedWidth"),rawHeight=row.i("decodedHeight"),sourceTimestampSeconds=time,
            orientationKey=row["orientationKey"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content ?: "")
        val scope=TSRApplicabilityScope(seq,"offline-video",geometry,1,1,1)
        val prepared=current.prepare(frame,id,scope)
        val diagnostic=TSRApplicabilityDiagnostic(1,TSRFrameCandidateBatch(1,id,time*1000,scope,"analyzed",emptyList(),false,0,"none","none",null),emptyList(),emptyList())
        val evaluated=Json.parseToJsonElement(current.evaluate(prepared,diagnostic)).jsonObject
        val published=evaluated.getValue("overlayPublished").jsonPrimitive.boolean
        val indices=if(published) prepared.presentation.visibleBoundaryIndices else emptyList()
        val output=buildJsonObject {
            put("id",id);put("sequenceId",seq);put("time",time);put("inputSha256",hash)
            put("rawBoundaries",boundaries(prepared.geometry.boundaries))
            put("confirmedBoundaries",boundaries(current.overlay()?.boundaries ?: emptyList()))
            put("visibleBoundaryIndices",buildJsonArray { indices.forEach { add(it) } })
            put("visibleIDs",buildJsonArray { indices.forEach { index ->
                add(requireNotNull(prepared.presentation.items.first { it.boundaryIndex==index }.trackId))
            } })
            put("lanePresentation",evaluated.getValue("lanePresentation"))
            put("calibrationDiagnostics",JsonObject(prepared.diagnostics.diagnosticJson.filterKeys { it!="stageMs" }))
            put("geometryBudgetExceeded",prepared.geometry.budgetExceeded)
            put("operationCount",prepared.geometry.operationCount);put("temporalOperationCount",prepared.geometry.temporalOperationCount)
            put("temporalResetReason",prepared.geometry.temporalResetReason)
            put("rejectionCounts",buildJsonObject { prepared.geometry.rejectionCounts.forEach { (k,v) -> put(k,v) } })
        }
        writer.appendLine(output.toString())
    } }
}

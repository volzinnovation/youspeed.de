package de.youspeed.android.alpha

import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.json.*

// Host-only value adapters; Android camera/bitmap capture is not exercised.
internal data class LaneImageGeometry(val width:Int,val height:Int,val rotationDegrees:Int,val sensorToBuffer:List<Double>)
data class NormalizedTrafficSignBoundingBox(val x:Double,val y:Double,val width:Double,val height:Double)
private fun JsonObject.s(key:String)=getValue(key).jsonPrimitive.content
private fun JsonObject.i(key:String)=getValue(key).jsonPrimitive.int
private fun points(values:List<LanePoint>)=buildJsonArray { values.forEach { p -> add(buildJsonArray { add(p.x);add(p.y) }) } }
private fun boundaries(values:List<RoadBoundaryEvidence>)=buildJsonArray { values.forEach { b -> add(buildJsonObject {
    put("points",points(b.points));put("observedSegments",buildJsonArray { b.observedSegments.forEach { add(points(it)) } })
    put("confidence",b.confidence);put("cue",b.cue.name.lowercase());put("supportRows",b.supportRows)
    put("provenance",b.provenance.name.lowercase());put("lastFreshTimestampSeconds",b.lastFreshTimestampSeconds)
    put("evidenceAgeSeconds",b.evidenceAgeSeconds);put("trackedAnchorCount",b.trackedAnchorCount)
    put("geometryConfidence",b.geometryConfidence);put("paintOccupancy",b.paintOccupancy)
}) } }
private fun jsonValue(value:Any?):JsonElement=when(value) {
    null -> JsonNull
    is JsonElement -> value
    is String -> JsonPrimitive(value)
    is Boolean -> JsonPrimitive(value)
    is Number -> JsonPrimitive(value)
    is Map<*,*> -> JsonObject(value.entries.associate { it.key.toString() to jsonValue(it.value) })
    is Iterable<*> -> JsonArray(value.map { jsonValue(it) })
    else -> error("Unsupported diagnostic type: ${value::class}")
}

fun main(args:Array<String>) {
    require(args.size==2) { "manifest.json output.ndjson" }
    val manifest=Json.parseToJsonElement(File(args[0]).readText()).jsonObject
    val mode=manifest.s("sessionMode");val traceEnabled=manifest.getValue("detectorTrace").jsonPrimitive.boolean
    require(manifest.i("schemaVersion")==1 && mode in listOf("preview","tsr"))
    val rows=manifest.getValue("frames").jsonArray;require(rows.size in 1..2048)
    val destination=File(args[1]);check(!destination.exists());val seen=mutableSetOf<String>()
    destination.bufferedWriter().use { writer -> for(value in rows) {
        val row=value.jsonObject;val id=row.s("id");val time=row.getValue("time").jsonPrimitive.double
        require(id.isNotEmpty() && id.all { it.code<128 } && seen.add(id) && row.s("sequenceId")==id && time==0.0)
        require(row.i("width") in 64..384 && row.i("height") in 64..216 && row.i("decodedWidth")>0 && row.i("decodedHeight")>0)
        val bytes=File(row.s("grayPath")).readBytes();require(bytes.size==row.i("width")*row.i("height"))
        val hash=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) };require(hash==row.s("graySha256"))
        val adjustments=row["semanticScoreAdjustments"]?.takeUnless { it is JsonNull }?.jsonArray?.map { it.jsonPrimitive.double }
        if(adjustments!=null) require(mode=="preview" && row.s("semanticSourceInputSha256")==hash && adjustments.size<=6 && adjustments.all { it.isFinite() && it in 0.0..0.1 })
        // Exactly the options used by ConsumerSessionController app callsites.
        val session=RoadPathSession(previewMode=mode=="preview",nowNanos={ 0L })
        val geometry="still:$id:${row.i("decodedWidth")}x${row.i("decodedHeight")}"
        val frame=RoadPathCameraFrame(bytes,row.i("width"),row.i("height"),0.0,geometry,null,true,0.0,0L,
            rawWidth=row.i("decodedWidth"),rawHeight=row.i("decodedHeight"),sourceTimestampSeconds=0.0)
        val scope=TSRApplicabilityScope(id,"offline-still",geometry,1,1,1)
        val trace=mutableListOf<JsonElement>()
        val observer:RoadBoundaryTraceObserver?=if(traceEnabled) { event -> trace.add(jsonValue(event));Unit } else null
        val prepared=session.prepare(frame,id,scope,detectorTrace=observer,semanticScoreAdjustments=adjustments)
        check(prepared.presentation.items.all { it.observationCount<=1 }) { "Still gained artificial temporal confirmation" }
        val diagnostic=TSRApplicabilityDiagnostic(1,TSRFrameCandidateBatch(1,id,0.0,scope,"analyzed",emptyList(),false,0,"none","none",null),emptyList(),emptyList())
        val evaluated=Json.parseToJsonElement(session.evaluate(prepared,diagnostic)).jsonObject
        val published=evaluated.getValue("overlayPublished").jsonPrimitive.boolean
        val indices=if(published) prepared.presentation.visibleBoundaryIndices else emptyList()
        val output=buildJsonObject {
            put("schemaVersion",1);put("id",id);put("sequenceId",id);put("time",0);put("inputSha256",hash)
            put("width",row.i("width"));put("height",row.i("height"));put("decodedWidth",row.i("decodedWidth"));put("decodedHeight",row.i("decodedHeight"))
            put("sessionMode",mode);put("freshInputObservations",1)
            put("rawBoundaries",boundaries(prepared.geometry.boundaries));put("confirmedBoundaries",boundaries(session.overlay()?.boundaries ?: emptyList()))
            put("visibleBoundaryIndices",buildJsonArray { indices.forEach { add(it) } })
            put("visibleIDs",buildJsonArray { indices.forEach { index -> add(requireNotNull(prepared.presentation.items.first { it.boundaryIndex==index }.trackId)) } })
            put("corridors",buildJsonArray { prepared.geometry.corridors.forEach { c -> add(buildJsonObject { put("leftBoundaryIndex",c.leftBoundaryIndex);put("rightBoundaryIndex",c.rightBoundaryIndex);put("confidence",c.confidence) }) } })
            put("lanePresentation",evaluated.getValue("lanePresentation"))
            put("calibrationDiagnostics",JsonObject(prepared.diagnostics.diagnosticJson.filterKeys { it!="stageMs" }))
            put("geometryBudgetExceeded",prepared.geometry.budgetExceeded);put("operationCount",prepared.geometry.operationCount)
            put("temporalOperationCount",prepared.geometry.temporalOperationCount);put("temporalResetReason",prepared.geometry.temporalResetReason)
            put("rejectionCounts",buildJsonObject { prepared.geometry.rejectionCounts.forEach { (k,v) -> put(k,v) } })
            put("overlayPublished",published);put("overlaySuppressionReason",evaluated["overlayPublicationSuppressionReason"] ?: JsonNull)
            put("deadlineExceeded",evaluated["deadlineExceeded"] ?: JsonPrimitive(false))
            if(traceEnabled) put("detectorTrace",JsonArray(trace))
        }
        writer.appendLine(output.toString())
    } }
}

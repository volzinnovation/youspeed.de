package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import java.time.Instant

/** Independent of numeric speed policy; matches the iPhone qualification rule. */
internal class SignCollectionObserver {
    data class Detection(val key: String, val box: List<Double>, val payload: JsonObject, val presentationTrack: String?,
        val supplementaryOCR: SupplementaryOCRAnnotation? = null, val commitReady: Boolean = true)
    data class CropCandidate(val observationId: String, val frameAt: Instant, val box: List<Double>, val selection: SignCollectionInterestSelection? = null,
        val supplementaryOCR: SupplementaryOCRAnnotation? = null)
    enum class CropCaptureResult { STORED, FAILED, SKIPPED }
    private companion object {
        const val REGULAR_CROP_LIMIT = 6
        const val MAXIMUM_CROP_LIMIT = 8
        const val MINIMUM_CROP_INTERVAL_MILLIS = 500L
        const val IMPROVEMENT_AREA_RATIO = 1.5
    }
    // Selection retains geometry only, never camera buffers.
    private data class Track(val id: String, val key: String, val first: Instant, var last: Instant, var box: List<Double>, var frames: Int = 0,
        var committed: Boolean = false, var cropCount: Int = 0, var lastCropAttempt: Instant? = null, var largestCropArea: Double = 0.0, var selection: SignCollectionInterestSelection? = null,
        var supplementaryOCR: SupplementaryOCRAnnotation? = null)
    private val tracks = mutableListOf<Track>()
    private val presentations = mutableMapOf<String, String>()
    private val attempts = mutableMapOf<String, String>()
    private data class SourceAssociation(val trackId: String, val modelLabel: String, val frameAt: Instant, val speedKmh: Int?, val box: List<Double>)
    private val sourceFrames = linkedMapOf<String, MutableList<SourceAssociation>>()
    private val committedIds = mutableSetOf<String>()
    private val recordedOCR = linkedSetOf<String>()
    private var frameTime: Instant? = null
    fun reset() {
        tracks.clear(); presentations.clear(); attempts.clear(); frameTime = null
        sourceFrames.clear(); committedIds.clear(); recordedOCR.clear()
    }
    fun observe(at: Instant, detections: List<Detection>, frameId: String? = null, captureCrop: ((CropCandidate) -> CropCaptureResult)? = null, selectCrop: ((JsonObject, String) -> SignCollectionInterestSelection)? = null, commit: (JsonObject) -> Unit) {
        if (frameTime?.let { at <= it } == true) return
        frameTime = at; tracks.removeAll { at.toEpochMilli() - it.last.toEpochMilli() > 2000 }
        val used = mutableSetOf<String>()
        detections.take(64).forEach { detection ->
            if (detection.box.size != 4 || detection.box.any { !it.isFinite() } || detection.box[2] <= 0 || detection.box[3] <= 0) return@forEach
            val track = tracks.filter { it.key == detection.key && it.id !in used }.maxByOrNull { iou(it.box, detection.box) }
                ?.takeIf { iou(it.box, detection.box) >= 0.2 } ?: run {
                    if (tracks.size >= 64) return@forEach
                    Track(SignCollectionJson.uuid(), detection.key, at, at, detection.box).also { tracks += it }
                }
            track.last = at; track.box = detection.box; track.frames++; used += track.id
            detection.supplementaryOCR?.let { track.supplementaryOCR = it }
            if (detection.commitReady && !track.committed && track.frames >= 2 && at.toEpochMilli() - track.first.toEpochMilli() >= 100) {
                var event = JsonObject(detection.payload + mapOf(
                    "event_id" to JsonPrimitive(track.id), "first_seen_at" to JsonPrimitive(track.first.toString()),
                    "last_seen_at" to JsonPrimitive(at.toString()), "representative_frame_at" to JsonPrimitive(at.toString()),
                    "duration_ms" to JsonPrimitive(at.toEpochMilli() - track.first.toEpochMilli()),
                    "scores" to JsonObject(detection.payload.getValue("scores").jsonObject + ("track_support" to JsonPrimitive(track.frames))),
                    "evidence" to JsonObject(detection.payload.getValue("evidence").jsonObject + mapOf("track_id" to JsonPrimitive(track.id), "analyzed_frames" to JsonPrimitive(track.frames), "finalization_reason" to JsonPrimitive("qualified_track"))),
                ))
                track.supplementaryOCR?.let { event = JsonObject(event + ("supplementary_ocr" to it.wire)) }
                if (selectCrop != null) {
                    if (track.selection == null) track.selection = selectCrop(detection.payload, track.id)
                    event = JsonObject(event + ("collection_selection" to track.selection!!.wire))
                }
                commit(event); track.committed = true; committedIds += track.id
            }
            if (track.committed && captureCrop != null && track.selection?.permits(at) != false) {
                val area = detection.box[2] * detection.box[3]
                val intervalReady = track.lastCropAttempt?.let { at.toEpochMilli() - it.toEpochMilli() >= MINIMUM_CROP_INTERVAL_MILLIS } ?: true
                if (intervalReady && track.cropCount < MAXIMUM_CROP_LIMIT &&
                    (track.cropCount < REGULAR_CROP_LIMIT || area >= track.largestCropArea * IMPROVEMENT_AREA_RATIO)) {
                    val result = captureCrop(CropCandidate(track.id, at, detection.box, track.selection, track.supplementaryOCR))
                    // Unavailable frames/capacity do not consume a slot; failures
                    // retry without hammering storage on every analyzed frame.
                    if (result != CropCaptureResult.SKIPPED) track.lastCropAttempt = at
                    if (result == CropCaptureResult.STORED) {
                        track.cropCount++
                        track.largestCropArea = maxOf(track.largestCropArea, area)
                    }
                }
            }
            if (frameId != null) {
                val classification = detection.payload["classification"]?.jsonObject
                val label = classification?.get("model_label")?.jsonPrimitive?.contentOrNull
                if (label != null) {
                    if (frameId !in sourceFrames && sourceFrames.size >= 64) sourceFrames.remove(sourceFrames.keys.first())
                    sourceFrames.getOrPut(frameId) { mutableListOf() } += SourceAssociation(track.id, label, at,
                        classification["value"]?.jsonPrimitive?.intOrNull, detection.box)
                }
            }
            if (track.committed) detection.presentationTrack?.let {
                if (presentations.size >= 512 && it !in presentations) presentations.clear()
                presentations[it] = track.id
            }
        }
        committedIds.retainAll(sourceFrames.values.flatten().map { it.trackId }.toSet() + tracks.map { it.id })
        // Feedback/listening may outlast the sign's visibility; retain bounded
        // display associations until the camera session or privacy reset.
    }
    /** A completion on an already ingested frame is metadata, never another sighting. */
    fun recordSupplementaryOCR(annotation: SupplementaryOCRAnnotation, at: Instant, commit: (JsonObject) -> Unit) {
        val attemptId = SignCollectionJson.sha256(SignCollectionJson.canonical(JsonArray(listOf(
            annotation.physicalSignId, annotation.frameId, annotation.engine, annotation.modelVersion).map(::JsonPrimitive))).toByteArray(Charsets.UTF_8))
        if (attemptId in recordedOCR) return
        val association = sourceFrames[annotation.frameId].orEmpty().filter {
            annotation.observedAt == it.frameAt && annotation.matches(it.modelLabel, it.speedKmh, it.box)
        }.singleOrNull()
        association?.let { source -> tracks.firstOrNull { it.id == source.trackId }?.supplementaryOCR = annotation }
        val target = association?.trackId?.takeIf { it in committedIds }
        val event = buildJsonObject {
            put("schema_version", 1); put("event_id", SignCollectionJson.uuid())
            put("created_at", maxOf(at, annotation.observedAt).toString()); put("crop_id", JsonNull)
            put("status", "supplementary_ocr_observed"); put("observation_id", target?.let(::JsonPrimitive) ?: JsonNull)
            put("association_status", if (target == null) "unresolved" else "exact"); put("ocr_attempt_id", attemptId)
            put("supplementary_ocr", annotation.wire)
        }
        commit(event)
        if (recordedOCR.size >= 1024) recordedOCR.remove(recordedOCR.first())
        recordedOCR += attemptId
        committedIds.retainAll(sourceFrames.values.flatten().map { it.trackId }.toSet() + tracks.map { it.id })
    }
    fun freeze(attempt: String, presentation: String?) {
        if (attempts.size >= 32) attempts.clear()
        presentations[presentation]?.let { attempts[attempt] = it }
    }
    fun correction(attempt: String, modality: String, at: Instant): JsonObject? {
        val target = attempts.remove(attempt) ?: return null
        return buildJsonObject {
            put("schema_version", 1); put("event_id", SignCollectionJson.uuid()); put("created_at", at.toString())
            put("intent", "unspecified_wrong"); put("input_modality", modality); put("target_kind", "observation"); put("target_id", target)
            put("target_version", JsonNull); put("association_status", "exact"); put("presentation_id", JsonNull)
            put("speech_attempt_id", if (modality == "voice") JsonPrimitive(attempt) else JsonNull); put("media_refs", JsonArray(emptyList()))
        }
    }
    private fun iou(a: List<Double>, b: List<Double>): Double {
        val intersection = maxOf(0.0, minOf(a[0]+a[2],b[0]+b[2])-maxOf(a[0],b[0])) * maxOf(0.0,minOf(a[1]+a[3],b[1]+b[3])-maxOf(a[1],b[1]))
        return intersection / maxOf(1e-12, a[2]*a[3]+b[2]*b[3]-intersection)
    }
}

/** All classes qualify independently from speed applicability. */
data class SignCaptureEvidence(val trackId: String, val modelLabel: String, val frameAt: Instant, val normalizedBox: List<Double>, val rawScore: Double, val sourceFrameId: String? = null)
internal class SignCaptureFilter {
    data class Detection(val key: String, val label: String, val box: List<Double>, val score: Double, val frameId: String? = null)
    private data class Track(val id: String, val key: String, val first: Instant, var last: Instant, var box: List<Double>, var frames: Int = 0, var captured: Boolean = false)
    private val tracks = mutableListOf<Track>()
    private var frameAt: Instant? = null
    private var captureAt: Instant? = null
    fun reset() { tracks.clear(); frameAt = null; captureAt = null }
    fun observe(at: Instant, detections: List<Detection>): List<SignCaptureEvidence> {
        if (frameAt?.let { at <= it } == true) return emptyList(); frameAt = at
        tracks.removeAll { at.toEpochMilli() - it.last.toEpochMilli() > 2000 }
        val used = mutableSetOf<String>(); val result = mutableListOf<SignCaptureEvidence>()
        detections.take(64).forEach { d ->
            if (d.box.size != 4 || d.box.any { !it.isFinite() } || d.box[2] <= 0 || d.box[3] <= 0) return@forEach
            val track = tracks.filter { it.key == d.key && it.id !in used }.maxByOrNull { iou(it.box,d.box) }?.takeIf { iou(it.box,d.box) >= 0.2 }
                ?: run { if (tracks.size >= 64) return@forEach; Track(SignCollectionJson.uuid(),d.key,at,at,d.box).also { tracks += it } }
            track.last = at; track.box = d.box; track.frames++; used += track.id
            if (!track.captured && track.frames >= 2 && at.toEpochMilli() - track.first.toEpochMilli() >= 100) result += SignCaptureEvidence(track.id,d.label,at,d.box,d.score,d.frameId)
        }
        if (captureAt?.let { at.toEpochMilli() - it.toEpochMilli() < 2000 } == true) return emptyList()
        return result.sortedByDescending { it.rawScore }
    }
    fun captured(evidence: List<SignCaptureEvidence>, at: Instant) { val ids = evidence.map { it.trackId }.toSet(); tracks.filter { it.id in ids }.forEach { it.captured = true }; captureAt = at }
    private fun iou(a: List<Double>, b: List<Double>): Double {
        val intersection = maxOf(0.0,minOf(a[0]+a[2],b[0]+b[2])-maxOf(a[0],b[0])) * maxOf(0.0,minOf(a[1]+a[3],b[1]+b[3])-maxOf(a[1],b[1]))
        return intersection / maxOf(1e-12,a[2]*a[3]+b[2]*b[3]-intersection)
    }
}

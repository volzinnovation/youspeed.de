package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import java.time.Instant

/** Independent of numeric speed policy; matches the iPhone qualification rule. */
internal class SignCollectionObserver {
    data class Detection(val key: String, val box: List<Double>, val payload: JsonObject, val presentationTrack: String?)
    private data class Track(val id: String, val key: String, val first: Instant, var last: Instant, var box: List<Double>, var frames: Int = 0, var committed: Boolean = false)
    private val tracks = mutableListOf<Track>()
    private val presentations = mutableMapOf<String, String>()
    private val attempts = mutableMapOf<String, String>()
    private var frameTime: Instant? = null
    fun reset() { tracks.clear(); presentations.clear(); attempts.clear(); frameTime = null }
    fun observe(at: Instant, detections: List<Detection>, commit: (JsonObject) -> Unit) {
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
            if (!track.committed && track.frames >= 2 && at.toEpochMilli() - track.first.toEpochMilli() >= 100) {
                val event = JsonObject(detection.payload + mapOf(
                    "event_id" to JsonPrimitive(track.id), "first_seen_at" to JsonPrimitive(track.first.toString()),
                    "last_seen_at" to JsonPrimitive(at.toString()), "representative_frame_at" to JsonPrimitive(at.toString()),
                    "duration_ms" to JsonPrimitive(at.toEpochMilli() - track.first.toEpochMilli()),
                    "scores" to JsonObject(detection.payload.getValue("scores").jsonObject + ("track_support" to JsonPrimitive(track.frames))),
                    "evidence" to JsonObject(detection.payload.getValue("evidence").jsonObject + mapOf("track_id" to JsonPrimitive(track.id), "analyzed_frames" to JsonPrimitive(track.frames), "finalization_reason" to JsonPrimitive("qualified_track"))),
                ))
                commit(event); track.committed = true
            }
            if (track.committed) detection.presentationTrack?.let {
                if (presentations.size >= 512 && it !in presentations) presentations.clear()
                presentations[it] = track.id
            }
        }
        // Feedback/listening may outlast the sign's visibility; retain bounded
        // display associations until the camera session or privacy reset.
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

package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant

enum class TrafficSignFeedbackMode { SPOKEN_SPEED, SOUND, SILENT }

/** Mirrors the iPhone recorder's distinction between a session and its consumers. */
object DriveRecorderPolicy {
    fun isActive(state: DriveRecorderState): Boolean = state in setOf(
        DriveRecorderState.REQUESTING_PERMISSION, DriveRecorderState.PREPARING,
        DriveRecorderState.RECORDING, DriveRecorderState.STOPPING,
    )

    fun canProcessPanoramaxUploads(state: DriveRecorderState): Boolean = !isActive(state)

    fun shouldRunRecognition(enabled: Boolean, independent: Boolean, recording: Boolean,
                             driving: Boolean, applicationActive: Boolean): Boolean =
        enabled && (independent || recording) && driving && applicationActive

    fun canShowPreview(state: DriveRecorderState, dashcamActive: Boolean, captureActive: Boolean): Boolean =
        state == DriveRecorderState.RECORDING && dashcamActive && !captureActive

    const val MOVIE_FILE_LIMIT_BYTES = 5_000_000_000L
    const val MOVIE_LIBRARY_LIMIT_BYTES = 10_000_000_000L
}

/** A physical sign produces feedback once, even if it is visible in many frames. */
internal class TrafficSignFeedbackGate(private val cooldown: Duration = Duration.ofSeconds(8)) {
    private val emitted = mutableSetOf<String>()
    private data class Recent(val speed: Int, val way: String, val direction: TrafficSignTravelDirection, val at: Instant)
    private var recent: Recent? = null

    @Synchronized fun shouldEmit(trackId: String?, speed: Int, context: TrafficSignDetectionContext, at: Instant): Boolean {
        if (speed <= 0) return false
        val way = context.wayId ?: return false
        val next = Recent(speed, way, context.travelDirection, at)
        val track = trackId?.trim()?.takeIf { it.isNotEmpty() }
        if (track != null) {
            if (!emitted.add("${context.wayId}:${context.travelDirection}:$track:$speed")) return false
        } else {
            recent?.let {
                if (it.speed == speed && it.way == next.way && it.direction == next.direction &&
                    Duration.between(it.at, at).abs() < cooldown) return false
            }
        }
        recent = next
        return true
    }

    @Synchronized fun reset() { emitted.clear(); recent = null }
}

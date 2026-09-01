package de.youspeed.android.alpha

import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

enum class TrafficSignThermalPressure {
    NOMINAL,
    FAIR,
    SERIOUS,
    CRITICAL,
}

data class TrafficSignAnalysisConditions(
    val speedMetersPerSecond: Double? = null,
    val hasActiveTrack: Boolean = false,
    val powerSaveMode: Boolean = false,
    val thermalPressure: TrafficSignThermalPressure = TrafficSignThermalPressure.NOMINAL,
)

data class TrafficSignFrameRateDecision(
    val targetFramesPerSecond: Int,
    val paused: Boolean,
    val reason: String,
) {
    val minimumIntervalNanos: Long?
        get() = targetFramesPerSecond.takeIf { it > 0 }?.let { NANOS_PER_SECOND / it }

    private companion object {
        const val NANOS_PER_SECOND = 1_000_000_000L
    }
}

/**
 * Keeps traffic-sign analysis between 2 and 10 FPS while reacting to travel
 * speed, candidate tracks, power saver, and thermal pressure. Critical thermal
 * pressure is the sole paused state and therefore intentionally uses 0 FPS.
 */
object TrafficSignAdaptiveFramePolicy {
    fun decide(conditions: TrafficSignAnalysisConditions): TrafficSignFrameRateDecision {
        if (conditions.thermalPressure == TrafficSignThermalPressure.CRITICAL) {
            return TrafficSignFrameRateDecision(
                targetFramesPerSecond = 0,
                paused = true,
                reason = "critical_thermal_pressure",
            )
        }

        var target = speedTarget(conditions.speedMetersPerSecond)
        var reason = "speed_adaptive"
        if (conditions.hasActiveTrack) {
            target = max(target, MAX_FRAMES_PER_SECOND)
            reason = "active_track"
        }
        if (conditions.powerSaveMode) {
            target = min(target, MIN_FRAMES_PER_SECOND)
            reason = "power_save"
        }
        when (conditions.thermalPressure) {
            TrafficSignThermalPressure.NOMINAL -> Unit
            TrafficSignThermalPressure.FAIR -> {
                target = min(target, FAIR_THERMAL_CAP)
                reason = "fair_thermal_pressure"
            }
            TrafficSignThermalPressure.SERIOUS -> {
                target = MIN_FRAMES_PER_SECOND
                reason = "serious_thermal_pressure"
            }
            TrafficSignThermalPressure.CRITICAL -> error("Handled above")
        }
        return TrafficSignFrameRateDecision(
            targetFramesPerSecond = target.coerceIn(MIN_FRAMES_PER_SECOND, MAX_FRAMES_PER_SECOND),
            paused = false,
            reason = reason,
        )
    }

    private fun speedTarget(speedMetersPerSecond: Double?): Int {
        val usableSpeed = speedMetersPerSecond?.takeIf { it.isFinite() && it > 0.0 } ?: return MIN_FRAMES_PER_SECOND
        // Roughly one analyzed frame per five metres, clamped to the product contract.
        return ceil(usableSpeed / METRES_PER_ANALYZED_FRAME).toInt()
            .coerceIn(MIN_FRAMES_PER_SECOND, SPEED_BASELINE_CAP)
    }

    const val MIN_FRAMES_PER_SECOND = 2
    const val MAX_FRAMES_PER_SECOND = 10
    private const val SPEED_BASELINE_CAP = 8
    private const val FAIR_THERMAL_CAP = 4
    private const val METRES_PER_ANALYZED_FRAME = 5.0
}

data class PendingTrafficSignFrame<T>(
    val value: T,
    val capturedAtNanos: Long,
)

/**
 * Single-flight mailbox used in addition to CameraX KEEP_ONLY_LATEST. At most
 * one frame waits while inference is running; replacing or clearing it invokes
 * [onDiscard] so a future ImageProxy adapter can always close dropped frames.
 */
class TrafficSignLatestFrameSlot<T>(
    private val onDiscard: (T) -> Unit = {},
) {
    private var pending: PendingTrafficSignFrame<T>? = null
    private var analysisInFlight = false
    private var lastDispatchAtNanos: Long? = null

    @Synchronized
    fun offer(value: T, capturedAtNanos: Long) {
        require(capturedAtNanos >= 0L) { "Frame timestamp must not be negative" }
        val incoming = PendingTrafficSignFrame(value, capturedAtNanos)
        val current = pending
        if (current != null && current.capturedAtNanos > capturedAtNanos) {
            onDiscard(value)
            return
        }
        pending = incoming
        current?.let { onDiscard(it.value) }
    }

    @Synchronized
    fun takeIfDue(
        nowNanos: Long,
        conditions: TrafficSignAnalysisConditions,
    ): PendingTrafficSignFrame<T>? {
        require(nowNanos >= 0L) { "Current timestamp must not be negative" }
        if (analysisInFlight) return null
        val decision = TrafficSignAdaptiveFramePolicy.decide(conditions)
        if (decision.paused) return null
        val interval = requireNotNull(decision.minimumIntervalNanos)
        val previousDispatch = lastDispatchAtNanos
        if (previousDispatch != null && nowNanos - previousDispatch < interval) return null
        val next = pending ?: return null
        pending = null
        analysisInFlight = true
        lastDispatchAtNanos = nowNanos
        return next
    }

    @Synchronized
    fun markAnalysisComplete() {
        check(analysisInFlight) { "No traffic-sign analysis is in flight" }
        analysisInFlight = false
    }

    @Synchronized
    fun clear() {
        pending?.let { onDiscard(it.value) }
        pending = null
    }

    @Synchronized
    fun hasPendingFrame(): Boolean = pending != null

    @Synchronized
    fun isAnalysisInFlight(): Boolean = analysisInFlight
}


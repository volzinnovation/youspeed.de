package de.youspeed.android.alpha

/** Platform-independent fields needed before a precise fix may replace live driving context. */
internal data class PreciseLocationSample(
    val timestampMs: Long,
    val elapsedRealtimeNanos: Long,
    val latitude: Double,
    val longitude: Double,
    val horizontalAccuracyMeters: Double?,
)

internal enum class PreciseLocationRejection(val diagnosticValue: String) {
    INVALID_COORDINATES("invalid_coordinates"),
    INVALID_HORIZONTAL_ACCURACY("invalid_horizontal_accuracy"),
    INVALID_TIMESTAMP("invalid_timestamp"),
    INVALID_ELAPSED_REALTIME("invalid_elapsed_realtime"),
    FUTURE_MONOTONIC_FIX("future_monotonic_fix"),
    FUTURE_WALL_CLOCK_FIX("future_wall_clock_fix"),
    STALE_MONOTONIC_FIX("stale_monotonic_fix"),
    STALE_WALL_CLOCK_FIX("stale_wall_clock_fix"),
    DUPLICATE_FIX("duplicate_fix"),
    OUT_OF_ORDER_FIX("out_of_order_fix"),
    NON_INCREASING_WALL_CLOCK("non_increasing_wall_clock"),
}

internal sealed interface PreciseLocationIntakeResult {
    data class Accepted(
        val timestampMs: Long,
        val wallClockAdjusted: Boolean,
    ) : PreciseLocationIntakeResult

    data class Rejected(val reason: PreciseLocationRejection) : PreciseLocationIntakeResult
}

/**
 * GPS and fused can deliver the same Android fix with different UTC timestamps.
 * Its elapsed-realtime timestamp identifies that physical sample across providers.
 * Only a small future UTC skew is repaired, using the sample's real monotonic age;
 * neither cached fixes nor untrusted future timestamps may replace accepted context.
 */
internal class PreciseLocationIntake {
    private var lastAcceptedTimestampMs: Long? = null
    private var lastAcceptedElapsedRealtimeNanos: Long? = null

    fun reset() {
        lastAcceptedTimestampMs = null
        lastAcceptedElapsedRealtimeNanos = null
    }

    fun evaluate(
        sample: PreciseLocationSample,
        nowMs: Long,
        nowElapsedRealtimeNanos: Long,
    ): PreciseLocationIntakeResult {
        fun reject(reason: PreciseLocationRejection) = PreciseLocationIntakeResult.Rejected(reason)

        if (!sample.latitude.isFinite() || sample.latitude !in -90.0..90.0 ||
            !sample.longitude.isFinite() || sample.longitude !in -180.0..180.0
        ) return reject(PreciseLocationRejection.INVALID_COORDINATES)
        if (sample.horizontalAccuracyMeters?.let { !it.isFinite() || it < 0.0 } == true) {
            return reject(PreciseLocationRejection.INVALID_HORIZONTAL_ACCURACY)
        }
        if (sample.timestampMs <= 0 || nowMs <= 0) return reject(PreciseLocationRejection.INVALID_TIMESTAMP)
        if (sample.elapsedRealtimeNanos < 0 || nowElapsedRealtimeNanos < 0 ||
            sample.elapsedRealtimeNanos > 0 && nowElapsedRealtimeNanos == 0L
        ) return reject(PreciseLocationRejection.INVALID_ELAPSED_REALTIME)

        val monotonicTimestamp = sample.elapsedRealtimeNanos.takeIf { it > 0 }
        val monotonicAgeNanos = monotonicTimestamp?.let { nowElapsedRealtimeNanos - it }
        if (monotonicAgeNanos != null) {
            if (monotonicAgeNanos < 0) return reject(PreciseLocationRejection.FUTURE_MONOTONIC_FIX)
            if (monotonicAgeNanos > TrafficSignRoadContextFreshness.MAXIMUM_AGE_MS * NANOS_PER_MILLISECOND) {
                return reject(PreciseLocationRejection.STALE_MONOTONIC_FIX)
            }
        }

        val wallClockAgeMs = nowMs - sample.timestampMs
        if (wallClockAgeMs > TrafficSignRoadContextFreshness.MAXIMUM_AGE_MS) {
            return reject(PreciseLocationRejection.STALE_WALL_CLOCK_FIX)
        }
        val adjusted = wallClockAgeMs < 0
        val timestampMs = if (adjusted) {
            if (wallClockAgeMs < -MAXIMUM_FUTURE_WALL_CLOCK_SKEW_MS || monotonicAgeNanos == null) {
                return reject(PreciseLocationRejection.FUTURE_WALL_CLOCK_FIX)
            }
            nowMs - monotonicAgeNanos / NANOS_PER_MILLISECOND
        } else {
            sample.timestampMs
        }
        if (timestampMs <= 0) return reject(PreciseLocationRejection.INVALID_TIMESTAMP)

        val previousMonotonicTimestamp = lastAcceptedElapsedRealtimeNanos
        if (monotonicTimestamp != null && previousMonotonicTimestamp != null) {
            if (monotonicTimestamp == previousMonotonicTimestamp) return reject(PreciseLocationRejection.DUPLICATE_FIX)
            if (monotonicTimestamp < previousMonotonicTimestamp) return reject(PreciseLocationRejection.OUT_OF_ORDER_FIX)
        }
        lastAcceptedTimestampMs?.let { previous ->
            if (timestampMs <= previous) {
                return reject(if (monotonicTimestamp != null && previousMonotonicTimestamp != null) {
                    PreciseLocationRejection.NON_INCREASING_WALL_CLOCK
                } else if (timestampMs == previous) {
                    PreciseLocationRejection.DUPLICATE_FIX
                } else {
                    PreciseLocationRejection.OUT_OF_ORDER_FIX
                })
            }
        }

        lastAcceptedTimestampMs = timestampMs
        // A fallback UTC-only fix must not erase known monotonic chronology.
        monotonicTimestamp?.let { lastAcceptedElapsedRealtimeNanos = it }
        return PreciseLocationIntakeResult.Accepted(timestampMs, adjusted)
    }

    private companion object {
        // The incident's fused timestamps were about 450 ms ahead of receipt.
        // This is input repair, not an extension of the road-context freshness limit.
        const val MAXIMUM_FUTURE_WALL_CLOCK_SKEW_MS = 1_000L
        const val NANOS_PER_MILLISECOND = 1_000_000L
    }
}

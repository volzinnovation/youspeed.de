package de.youspeed.android.alpha

import kotlin.math.ceil

/** A startup measurement from the verified reference-image recognition check. */
internal data class TrafficSignInferenceTimingProfile(
    val measuredWarmMaxMs: Double,
    val confirmationWindowMs: Long,
)

/** Adapts only elapsed-time allowance; model scores and evidence counts remain unchanged. */
internal object TrafficSignInferenceTimingPolicy {
    const val MAXIMUM_CONFIRMATION_WINDOW_MS = 6_000L

    fun profile(
        manifestConfirmationWindowMs: Long,
        referenceVerified: Boolean,
        warmInferenceTimesMs: List<Double>,
    ): TrafficSignInferenceTimingProfile? {
        require(manifestConfirmationWindowMs > 0L)
        if (!referenceVerified || warmInferenceTimesMs.isEmpty() ||
            warmInferenceTimesMs.any { !it.isFinite() || it <= 0.0 }
        ) return null

        val warmMaxMs = warmInferenceTimesMs.max()
        // A pair of serial camera inferences needs one inference interval
        // between captures. Budget two measured intervals to allow scheduling
        // jitter, while keeping confidence evidence bounded to six seconds.
        val measuredWindowMs = ceil(warmMaxMs * 2.0)
            .coerceAtMost(MAXIMUM_CONFIRMATION_WINDOW_MS.toDouble())
            .toLong()
        return TrafficSignInferenceTimingProfile(
            measuredWarmMaxMs = warmMaxMs,
            confirmationWindowMs = maxOf(manifestConfirmationWindowMs, measuredWindowMs),
        )
    }
}

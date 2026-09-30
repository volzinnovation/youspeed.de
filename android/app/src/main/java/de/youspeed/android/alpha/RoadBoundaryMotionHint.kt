package de.youspeed.android.alpha

import kotlin.math.abs

/** Causal GNSS search hint only. It neither projects pixels nor supplies observed lane points. */
data class RoadBoundaryMotionSample(val timeSeconds: Double, val speedMetersPerSecond: Double,
    val courseDegrees: Double, val horizontalAccuracyMeters: Double, val courseAccuracyDegrees: Double)
data class RoadBoundaryMotionHint(val used: Boolean, val reason: String, val sourceAgeSeconds: Double? = null,
    val speedMetersPerSecond: Double? = null, val courseAccuracyDegrees: Double? = null,
    val pairIntervalSeconds: Double? = null, val headingDeltaDegrees: Double? = null,
    val headingRateDegreesPerSecond: Double? = null,
    val horizontalSearchRadiusFloor: Int = 0) {
    companion object {
        fun from(samples: List<RoadBoundaryMotionSample>, capturedAtSeconds: Double, clockKnown: Boolean): RoadBoundaryMotionHint {
            if (!clockKnown || !capturedAtSeconds.isFinite()) return RoadBoundaryMotionHint(false,"capture_clock_unknown")
            val causal = samples.takeLast(32).filter { it.timeSeconds.isFinite() && it.timeSeconds <= capturedAtSeconds }
            val latest = causal.lastOrNull() ?: return RoadBoundaryMotionHint(false,"no_causal_fix")
            val age = capturedAtSeconds-latest.timeSeconds
            fun reject(reason: String) = RoadBoundaryMotionHint(false,reason,age,latest.speedMetersPerSecond,latest.courseAccuracyDegrees)
            // Session ingestion already owns GPS validity. Do not introduce a second health policy.
            fun valid(s: RoadBoundaryMotionSample) = listOf(s.speedMetersPerSecond,s.courseDegrees,s.horizontalAccuracyMeters,s.courseAccuracyDegrees).all { it.isFinite() } &&
                s.speedMetersPerSecond >= 0 && s.courseDegrees in 0.0..<360.0
            if (!valid(latest)) return reject("invalid_fix")
            val before = causal.dropLast(1).lastOrNull { it.timeSeconds < latest.timeSeconds } ?: return reject("insufficient_history")
            if (!valid(before)) return reject("invalid_fix")
            val interval = latest.timeSeconds-before.timeSeconds
            val delta = ((latest.courseDegrees-before.courseDegrees+540)%360)-180
            val rate = delta/interval
            if (!rate.isFinite()) return reject("invalid_fix_interval")
            val turning = latest.speedMetersPerSecond>0 && abs(rate)>6
            return RoadBoundaryMotionHint(turning,if(turning) "turn_search_hint" else "no_moving_turn",age,
                latest.speedMetersPerSecond,latest.courseAccuracyDegrees,interval,delta,rate,if(turning)12 else 0)
        }
    }
}

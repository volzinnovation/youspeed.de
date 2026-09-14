package de.youspeed.android.alpha

import kotlin.math.abs

internal data class TrafficSignPositionSample(
    val timestampMs: Long,
    val latitude: Double,
    val longitude: Double,
    val headingDegrees: Double?,
    val speedMetersPerSecond: Double,
)

/** Bounded reuse of a matched road identity while a newer GPS fix is being matched. */
internal object TrafficSignRoadContextFreshness {
    // Allows ordinary 1–3 second Android lookups, including motorway travel,
    // but never the tens-of-seconds context reuse observed in driving logs.
    const val MAXIMUM_AGE_MS = 6_000L
    const val MAXIMUM_DISPLACEMENT_M = 250.0
    private const val MAXIMUM_HEADING_CHANGE_DEGREES = 45.0

    fun accepts(matched: TrafficSignPositionSample, latest: TrafficSignPositionSample?, nowMs: Long): Boolean {
        latest ?: return false
        if (!valid(matched) || !valid(latest)) return false
        if (nowMs - matched.timestampMs !in 0..MAXIMUM_AGE_MS ||
            nowMs - latest.timestampMs !in 0..MAXIMUM_AGE_MS || latest.timestampMs < matched.timestampMs
        ) return false
        if (distanceMeters(matched.latitude, matched.longitude, latest.latitude, latest.longitude) > MAXIMUM_DISPLACEMENT_M) return false
        if (matched.speedMetersPerSecond >= 1.0 && latest.speedMetersPerSecond >= 1.0 &&
            matched.headingDegrees != null && latest.headingDegrees != null
        ) {
            val change = abs(matched.headingDegrees - latest.headingDegrees)
            if (minOf(change, 360.0 - change) > MAXIMUM_HEADING_CHANGE_DEGREES) return false
        }
        return true
    }

    fun refreshedContext(
        context: TrafficSignDetectionContext,
        matched: TrafficSignPositionSample?,
        latest: TrafficSignPositionSample?,
        nowMs: Long,
    ): TrafficSignDetectionContext? {
        if (matched == null || !accepts(matched, latest, nowMs)) return null
        latest ?: return null
        return context.copy(
            latitude = latest.latitude,
            longitude = latest.longitude,
            headingDegrees = latest.headingDegrees ?: context.headingDegrees,
            speedMetersPerSecond = latest.speedMetersPerSecond,
            routeRelationGroupIds = context.routeRelationGroupIds.toSet(),
            sourceRelationIds = context.sourceRelationIds.toSet(),
        )
    }

    private fun valid(value: TrafficSignPositionSample): Boolean =
        value.latitude.isFinite() && value.latitude in -90.0..90.0 &&
            value.longitude.isFinite() && value.longitude in -180.0..180.0 &&
            value.speedMetersPerSecond.isFinite() && value.speedMetersPerSecond >= 0.0 &&
            (value.headingDegrees == null || value.headingDegrees.isFinite() && value.headingDegrees in 0.0..<360.0)
}

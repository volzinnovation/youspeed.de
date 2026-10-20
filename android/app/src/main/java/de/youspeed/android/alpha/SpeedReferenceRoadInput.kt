package de.youspeed.android.alpha

/** Validate road-direction evidence before it reaches the shared reference policy. */
internal object SpeedReferenceRoadInput {
    fun direction(
        matchedDirection: TrafficSignTravelDirection,
        rawSpeedMetersPerSecond: Double?,
        bearingDegrees: Double?,
        bearingAccuracyDegrees: Double?,
        horizontalAccuracyMeters: Double?,
        observedAtMillis: Long,
        nowMillis: Long,
    ): TrafficSignTravelDirection {
        val ageMillis = nowMillis - observedAtMillis
        val reliable = rawSpeedMetersPerSecond?.let { it.isFinite() && it >= 1.0 } == true &&
            bearingDegrees?.let { it.isFinite() && it >= 0.0 && it < 360.0 } == true &&
            bearingAccuracyDegrees?.let { it.isFinite() && it in 0.0..TSRApplicabilityConfiguration.maxCourseAccuracyDeg } == true &&
            horizontalAccuracyMeters?.let { it.isFinite() && it in 0.0..TSRApplicabilityConfiguration.maxGpsAccuracyM } == true &&
            ageMillis >= 0 && ageMillis <= TSRApplicabilityConfiguration.maxContextAgeMs
        return matchedDirection.takeIf { reliable } ?: TrafficSignTravelDirection.UNKNOWN
    }

    fun lookupStatus(wayId: String?, effective: EffectiveSpeedLimit): String = when {
        effective.source.isStale -> "matched_last_known"
        effective.resolution?.kind == TrafficSignResolvedLimitKind.UNLIMITED -> "matched_unlimited"
        effective.source == EffectiveSpeedLimitSource.LOCAL_CORRECTION -> "matched_local_override"
        effective.source == EffectiveSpeedLimitSource.CAMERA -> "matched_camera_override"
        effective.resolution != null -> "matched"
        wayId != null -> "matched_no_speed"
        else -> "no_match"
    }
}

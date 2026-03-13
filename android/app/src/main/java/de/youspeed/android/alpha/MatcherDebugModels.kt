package de.youspeed.android.alpha

internal data class WayMatchHypothesis(
    val wayId: String,
    val streetRef: String?,
    val highway: String?,
    val corridorState: String? = null,
    val corridorKind: String? = null,
    val corridorId: Int? = null,
    val corridorSideNodeKey: String? = null,
    val cumulativeCost: Double,
    val emissionScore: Double,
    val endpointProximityM: Double,
    val startLat: Double?,
    val startLon: Double?,
    val endLat: Double?,
    val endLon: Double?,
    val isTunnel: Boolean,
)

internal data class MatchSelectionTrace(
    val step: String,
    val detail: String,
)

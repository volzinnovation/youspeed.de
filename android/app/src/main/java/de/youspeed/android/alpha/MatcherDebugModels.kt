package de.youspeed.android.alpha

internal enum class LookupMatchingModel {
    CONNECTED_BASELINE,
    SIMPLE_SPEED_REF_HEURISTIC,
    SIMPLE_SPEED_REF_URBAN_RELEASE_HEURISTIC,
    SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC,
    SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC,
    SIMPLE_SPEED_REF_CONNECTED_HEURISTIC,
    CORRIDOR_HMM_RAW_MINI_HMM,
    CORRIDOR_HMM,
    CORRIDOR_HMM_NO_THREE_WAY_GATE,
    CORRIDOR_HMM_NO_SAME_REF_BOUNCE_GATE,
    CORRIDOR_HMM_ANTI_ABA_HYSTERESIS,
}

enum class MatcherDebugProfile(
    val storageValue: String,
    val shortLabel: String,
    val displayName: String,
    internal val lookupModel: LookupMatchingModel,
) {
    M1("m1", "M1", "Connected baseline", LookupMatchingModel.CONNECTED_BASELINE),
    M2("m2", "M2", "Nearest + street-ref continuity", LookupMatchingModel.SIMPLE_SPEED_REF_HEURISTIC),
    M3("m3", "M3", "M2 + connected-candidate gate", LookupMatchingModel.SIMPLE_SPEED_REF_CONNECTED_HEURISTIC),
    M4("m4", "M4", "Corridor raw mini-HMM", LookupMatchingModel.CORRIDOR_HMM_RAW_MINI_HMM),
    M5("m5", "M5", "Corridor-aware final", LookupMatchingModel.CORRIDOR_HMM),
    M6("m6", "M6", "M2 + urban consecutive distance-gap release", LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_HEURISTIC),
    M7("m7", "M7", "M6 + 10m search window", LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC),
    M9("m9", "M9", "Guarded stale-ref suppression", LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC),
    ;

    val debugLabel: String
        get() = "$shortLabel $displayName"

    companion object {
        const val forcedProfileVersion: Int = 8
        val default: MatcherDebugProfile = M7

        fun fromStored(raw: String?): MatcherDebugProfile {
            val normalized = raw?.trim()?.lowercase().orEmpty()
            return entries.firstOrNull { it.storageValue == normalized } ?: default
        }

        fun resolveInitialProfile(raw: String?, forcedVersion: Int): MatcherDebugProfile {
            if (forcedVersion < forcedProfileVersion) {
                return default
            }
            return fromStored(raw)
        }
    }
}

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

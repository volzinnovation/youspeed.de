package de.youspeed.android.alpha

internal data class WayMatchRecentFix(
    val lat: Double,
    val lon: Double,
)

internal data class CorridorMatchState(
    val kind: String,
    val corridorId: Int,
    val sideNodeKey: String,
    val depthM: Double,
    val spanM: Double,
    val depthNodes: Int,
    val spanNodes: Int,
)

internal data class WayMatchContext(
    val preferredWayId: String? = null,
    val preferredHighway: String? = null,
    val preferredEndpointProximityM: Double? = null,
    val recentWayIds: List<String> = emptyList(),
    val recentWayHistory: List<String> = emptyList(),
    val recentFixes: List<WayMatchRecentFix> = emptyList(),
    val sameRefUrbanReleaseStreak: Int = 0,
    val preferredStreetRef: String? = null,
    val activeStreetRef: String? = null,
    val preferredStreetName: String? = null,
    val recentStreetRefs: List<String> = emptyList(),
    val consecutiveNoRefMatchCount: Int = 0,
    val recentTunnelCandidateWayIds: Set<String> = emptySet(),
    val recentTunnelCandidateRefs: Set<String> = emptySet(),
    val recentTunnelApproachWayIds: Set<String> = emptySet(),
    val recentTunnelApproachRefs: Set<String> = emptySet(),
    val tunnelApproachFixCount: Int = 0,
    val tunnelApproachBaselineAccuracyM: Double? = null,
    val tunnelApproachBaselineSignalBars: Int? = null,
    val recentHypotheses: List<WayMatchHypothesis> = emptyList(),
    val matchedFixCount: Int = 0,
    val hadRecentGpsSignalLoss: Boolean = false,
    val isInTunnelMode: Boolean = false,
    val isInMotorwayMode: Boolean = false,
    val activeCorridorState: CorridorMatchState? = null,
    val approachCorridorState: CorridorMatchState? = null,
    val approachCorridorFixCount: Int = 0,
    val approachCorridorStartDepthM: Double? = null,
    val approachCorridorStartDepthNodes: Int? = null,
)

internal class WayMatchSessionTracker {
    private var preferredWayId: String? = null
    private var preferredHighway: String? = null
    private var preferredEndpointProximityM: Double? = null
    private val recentWayIds = ArrayDeque<String>()
    private val recentWayHistory = ArrayDeque<String>()
    private val recentFixes = ArrayDeque<WayMatchRecentFix>()
    private var sameRefUrbanReleaseStreak = 0
    private var activeStreetRef: String? = null
    private var preferredStreetName: String? = null
    private val recentStreetRefs = ArrayDeque<String>()
    private var consecutiveNoRefMatchCount = 0
    private val recentTunnelCandidateWayIds = linkedSetOf<String>()
    private val recentTunnelCandidateRefs = linkedSetOf<String>()
    private val recentTunnelApproachWayIds = linkedSetOf<String>()
    private val recentTunnelApproachRefs = linkedSetOf<String>()
    private var tunnelApproachFixCount = 0
    private var tunnelApproachBaselineAccuracyM: Double? = null
    private var tunnelApproachBaselineSignalBars: Int? = null
    private var recentHypotheses: List<WayMatchHypothesis> = emptyList()
    private var matchedFixCount = 0
    private var hadRecentGpsSignalLoss = false
    private var isInTunnelMode = false
    private var isInMotorwayMode = false
    private var activeCorridorState: CorridorMatchState? = null
    private var approachCorridorState: CorridorMatchState? = null
    private var approachCorridorFixCount = 0
    private var approachCorridorStartDepthM: Double? = null
    private var approachCorridorStartDepthNodes: Int? = null

    fun snapshotOrNull(): WayMatchContext? {
        if (
            preferredWayId == null &&
            recentWayIds.isEmpty() &&
            sameRefUrbanReleaseStreak <= 0 &&
            activeStreetRef == null &&
            preferredStreetName == null &&
            recentStreetRefs.isEmpty() &&
            consecutiveNoRefMatchCount <= 0 &&
            recentTunnelCandidateWayIds.isEmpty() &&
            recentTunnelCandidateRefs.isEmpty() &&
            recentTunnelApproachWayIds.isEmpty() &&
            recentTunnelApproachRefs.isEmpty() &&
            tunnelApproachFixCount <= 0 &&
            recentHypotheses.isEmpty() &&
            !hadRecentGpsSignalLoss &&
            !isInTunnelMode &&
            !isInMotorwayMode &&
            activeCorridorState == null &&
            approachCorridorState == null
        ) {
            return null
        }
        return WayMatchContext(
            preferredWayId = preferredWayId,
            preferredHighway = preferredHighway,
            preferredEndpointProximityM = preferredEndpointProximityM,
            recentWayIds = recentWayIds.toList(),
            recentWayHistory = recentWayHistory.toList(),
            recentFixes = recentFixes.toList(),
            sameRefUrbanReleaseStreak = sameRefUrbanReleaseStreak,
            preferredStreetRef = recentStreetRefs.firstOrNull(),
            activeStreetRef = activeStreetRef,
            preferredStreetName = preferredStreetName,
            recentStreetRefs = recentStreetRefs.toList(),
            consecutiveNoRefMatchCount = consecutiveNoRefMatchCount,
            recentTunnelCandidateWayIds = recentTunnelCandidateWayIds.toSet(),
            recentTunnelCandidateRefs = recentTunnelCandidateRefs.toSet(),
            recentTunnelApproachWayIds = recentTunnelApproachWayIds.toSet(),
            recentTunnelApproachRefs = recentTunnelApproachRefs.toSet(),
            tunnelApproachFixCount = tunnelApproachFixCount,
            tunnelApproachBaselineAccuracyM = tunnelApproachBaselineAccuracyM,
            tunnelApproachBaselineSignalBars = tunnelApproachBaselineSignalBars,
            recentHypotheses = recentHypotheses,
            matchedFixCount = matchedFixCount,
            hadRecentGpsSignalLoss = hadRecentGpsSignalLoss,
            isInTunnelMode = isInTunnelMode,
            isInMotorwayMode = isInMotorwayMode,
            activeCorridorState = activeCorridorState,
            approachCorridorState = approachCorridorState,
            approachCorridorFixCount = approachCorridorFixCount,
            approachCorridorStartDepthM = approachCorridorStartDepthM,
            approachCorridorStartDepthNodes = approachCorridorStartDepthNodes,
        )
    }

    fun record(
        result: SpeedLookupResult,
        lat: Double,
        lon: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int,
    ) {
        val matchedWayId = result.wayId?.trim().orEmpty()
        if (matchedWayId.isNotEmpty()) {
            matchedFixCount += 1
            preferredWayId = matchedWayId
            pushFrontUnique(recentWayIds, matchedWayId, RECENT_WAY_LIMIT)
            pushFrontUnique(recentWayHistory, matchedWayId, RECENT_WAY_LIMIT)
        }
        preferredHighway = result.highway
        preferredEndpointProximityM = result.matchedEndpointProximityM
        activeStreetRef = result.streetRef
        preferredStreetName = result.streetBaseName ?: result.streetName
        sameRefUrbanReleaseStreak = updatedSameRefUrbanReleaseStreak(result)
        if (result.streetRefTokens.isEmpty()) {
            consecutiveNoRefMatchCount = minOf(consecutiveNoRefMatchCount + 1, 8)
        } else {
            consecutiveNoRefMatchCount = 0
        }
        result.streetRefTokens.forEach { pushFrontUnique(recentStreetRefs, it, RECENT_STREET_REF_LIMIT) }
        replaceLinkedSet(recentTunnelCandidateWayIds, result.nearbyTunnelCandidateWayIds, RECENT_WAY_LIMIT)
        replaceLinkedSet(recentTunnelCandidateRefs, result.nearbyTunnelCandidateRefs, RECENT_STREET_REF_LIMIT)
        recentHypotheses = result.matchHypotheses
        recentFixes.addFirst(WayMatchRecentFix(lat = lat, lon = lon))
        while (recentFixes.size > 3) {
            recentFixes.removeLast()
        }
        updateTunnelApproachState(result, horizontalAccuracyM, gpsSignalBars)
        updateApproachCorridorState(result)
        activeCorridorState = result.activeCorridorState
        isInTunnelMode = result.isTunnelSegment
        val resultHighway = result.highway?.trim()?.lowercase()
        isInMotorwayMode = when (resultHighway) {
            "motorway" -> true
            "motorway_link" -> isInMotorwayMode || result.activeCorridorState?.kind == "motorway"
            else -> false
        }
        hadRecentGpsSignalLoss = false
    }

    fun noteGpsSignalLoss(horizontalAccuracyM: Double?, gpsSignalBars: Int) {
        hadRecentGpsSignalLoss = gpsSignalBars <= 1 || (horizontalAccuracyM ?: 0.0) >= 30.0
    }

    fun reset() {
        preferredWayId = null
        preferredHighway = null
        preferredEndpointProximityM = null
        recentWayIds.clear()
        recentWayHistory.clear()
        recentFixes.clear()
        sameRefUrbanReleaseStreak = 0
        activeStreetRef = null
        preferredStreetName = null
        recentStreetRefs.clear()
        consecutiveNoRefMatchCount = 0
        recentTunnelCandidateWayIds.clear()
        recentTunnelCandidateRefs.clear()
        resetTunnelApproachState()
        resetApproachCorridorState()
        recentHypotheses = emptyList()
        matchedFixCount = 0
        hadRecentGpsSignalLoss = false
        isInTunnelMode = false
        isInMotorwayMode = false
        activeCorridorState = null
    }

    private fun updatedSameRefUrbanReleaseStreak(result: SpeedLookupResult): Int {
        val streak = result.selectionTrace
            .lastOrNull { it.step == "simple_same_ref_urban_release_streak" }
            ?.detail
            ?.toIntOrNull()
        return maxOf(streak ?: 0, 0)
    }

    private fun updateTunnelApproachState(
        result: SpeedLookupResult,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int,
    ) {
        if (result.isTunnelSegment || result.portalEligibleTunnelWayIds.isEmpty()) {
            resetTunnelApproachState()
            return
        }
        tunnelApproachFixCount += 1
        if (horizontalAccuracyM != null && horizontalAccuracyM.isFinite() && horizontalAccuracyM >= 0.0) {
            tunnelApproachBaselineAccuracyM = minOf(tunnelApproachBaselineAccuracyM ?: horizontalAccuracyM, horizontalAccuracyM)
        }
        tunnelApproachBaselineSignalBars = maxOf(tunnelApproachBaselineSignalBars ?: gpsSignalBars, gpsSignalBars)
        replaceLinkedSet(recentTunnelApproachWayIds, result.portalEligibleTunnelWayIds, RECENT_WAY_LIMIT)
        replaceLinkedSet(recentTunnelApproachRefs, result.portalEligibleTunnelRefs, RECENT_STREET_REF_LIMIT)
    }

    private fun resetTunnelApproachState() {
        recentTunnelApproachWayIds.clear()
        recentTunnelApproachRefs.clear()
        tunnelApproachFixCount = 0
        tunnelApproachBaselineAccuracyM = null
        tunnelApproachBaselineSignalBars = null
    }

    private fun updateApproachCorridorState(result: SpeedLookupResult) {
        if (result.activeCorridorState != null) {
            resetApproachCorridorState()
            return
        }
        val nextState = result.approachCorridorStateCandidate ?: run {
            resetApproachCorridorState()
            return
        }
        val currentState = approachCorridorState
        if (
            currentState != null &&
            currentState.kind == nextState.kind &&
            currentState.corridorId == nextState.corridorId &&
            currentState.sideNodeKey == nextState.sideNodeKey &&
            nextState.depthM + 6.0 >= currentState.depthM
        ) {
            approachCorridorFixCount += 1
            approachCorridorStartDepthM = minOf(approachCorridorStartDepthM ?: currentState.depthM, nextState.depthM)
            approachCorridorStartDepthNodes = minOf(approachCorridorStartDepthNodes ?: currentState.depthNodes, nextState.depthNodes)
        } else {
            approachCorridorFixCount = 1
            approachCorridorStartDepthM = nextState.depthM
            approachCorridorStartDepthNodes = nextState.depthNodes
        }
        approachCorridorState = nextState
    }

    private fun resetApproachCorridorState() {
        approachCorridorState = null
        approachCorridorFixCount = 0
        approachCorridorStartDepthM = null
        approachCorridorStartDepthNodes = null
    }

    private fun pushFrontUnique(target: ArrayDeque<String>, value: String, limit: Int) {
        target.remove(value)
        target.addFirst(value)
        while (target.size > limit) {
            target.removeLast()
        }
    }

    private fun replaceLinkedSet(
        target: LinkedHashSet<String>,
        values: Set<String>,
        limit: Int,
    ) {
        target.clear()
        values.take(limit).forEach { target += it }
    }

    companion object {
        private const val RECENT_WAY_LIMIT = 5
        private const val RECENT_STREET_REF_LIMIT = 6
    }
}

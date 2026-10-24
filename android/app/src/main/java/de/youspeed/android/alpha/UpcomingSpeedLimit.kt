package de.youspeed.android.alpha

import kotlin.math.ceil
import kotlin.math.max

/** Thirty seconds of observed travel, with the original 300 m minimum at low speed. */
internal object UpcomingSpeedLimitHorizon {
    const val minimumDistanceM = 300.0
    const val leadTimeSeconds = 30.0
    const val maxPathSegments = 32

    fun distanceM(speedKmh: Double?): Double {
        if (speedKmh == null || !speedKmh.isFinite() || speedKmh < 0) return minimumDistanceM
        val distance = speedKmh / 3.6 * leadTimeSeconds
        return if (distance.isFinite()) max(minimumDistanceM, distance) else minimumDistanceM
    }
}

/** Qualified offline physical sign evidence, independent of the active reference policy. */
data class UpcomingSpeedLimitCandidate(
    val signID: String, val sourceID: String, val snapshotSHA256: String, val ruleID: String,
    val originWayID: String, val direction: Int, val stationM: Double, val speedKmh: Int, val distanceM: Double,
) {
    internal val identity: String get() = "$sourceID|$snapshotSHA256|$signID|$direction"
    val displayDistanceM: Int get() = (ceil(distanceM / 10.0) * 10).toInt()
}

internal data class UpcomingSpeedLimitPath(
    val segmentID: String?, val wayID: String, val direction: Int, val startM: Double, val endM: Double,
    val entryDistanceM: Double, val relationGroupIDs: Set<Long>,
)

internal data class UpcomingSpeedLimitSnapshot(
    val wayID: String, val direction: Int, val chainageM: Double, val relationGroupIDs: Set<Long>,
    val path: List<UpcomingSpeedLimitPath>, val candidates: List<UpcomingSpeedLimitCandidate>,
    val reason: String, val queryTimeMs: Double = 0.0, val topologyAvailable: Boolean = false,
    val lookaheadDistanceM: Double = UpcomingSpeedLimitHorizon.minimumDistanceM,
)

/** Passage memory outlives visibility, lookup cancellation, GPS gaps and backgrounding. */
internal class UpcomingSpeedLimitTracker {
    private data class Encounter(val candidate: UpcomingSpeedLimitCandidate, val path: List<UpcomingSpeedLimitPath>)
    private var bundle: String? = null
    private var latest: UpcomingSpeedLimitSnapshot? = null
    private var lastPath: List<UpcomingSpeedLimitPath>? = null
    private var acceptedAtMs = Long.MIN_VALUE
    private var frozenGroups = emptySet<Long>()
    private val encountered = linkedMapOf<String, Encounter>()
    private val consumed = mutableSetOf<String>()
    private var departed = false
    private var exhausted = false
    private var scopeLost = false

    fun reset() { bundle = null; latest = null; lastPath = null; acceptedAtMs = Long.MIN_VALUE; frozenGroups = emptySet(); encountered.clear(); consumed.clear(); departed = false; exhausted = false; scopeLost = false }
    fun hide() { latest = null }
    fun certifiesContinuation(snapshot: UpcomingSpeedLimitSnapshot, bundleIdentity: String): Boolean = bundle == bundleIdentity && snapshot.topologyAvailable &&
        frozenGroups.intersect(snapshot.relationGroupIDs).isNotEmpty() && lastPath?.any {
            it.wayID == snapshot.wayID && it.direction == snapshot.direction &&
                snapshot.chainageM >= it.startM-1e-6 && snapshot.chainageM <= it.endM+1e-6
        } == true

    fun consume(snapshot: UpcomingSpeedLimitSnapshot?, bundleIdentity: String, fixAtMs: Long, nowMs: Long) {
        if (nowMs - fixAtMs !in 0 until 3000 || fixAtMs < acceptedAtMs || snapshot == null || !snapshot.chainageM.isFinite() || snapshot.direction !in setOf(-1,1) || snapshot.path.size > UpcomingSpeedLimitHorizon.maxPathSegments || !snapshot.lookaheadDistanceM.isFinite() || snapshot.lookaheadDistanceM < UpcomingSpeedLimitHorizon.minimumDistanceM) { hide(); return }
        if (bundle != bundleIdentity) {
            // A bundle replacement cannot resurrect a consumed station from that bundle.
            latest = null; lastPath = null; encountered.clear(); frozenGroups = emptySet(); scopeLost = false; bundle = bundleIdentity
        }
        val previous = latest
        val scopePath = previous?.path?.takeIf { it.isNotEmpty() } ?: lastPath
        val matchingPath = scopePath?.any { it.wayID == snapshot.wayID && it.direction == snapshot.direction } == true
        val sameWay = scopePath?.firstOrNull()?.let { it.wayID == snapshot.wayID && it.direction == snapshot.direction } == true
        val reversed = scopePath?.any { it.wayID == snapshot.wayID && it.direction != snapshot.direction } == true
        val groups = if (frozenGroups.isEmpty()) emptySet() else frozenGroups.intersect(snapshot.relationGroupIDs)
        val continuation = sameWay || (matchingPath && groups.isNotEmpty())
        if (scopePath != null && !matchingPath && !sameWay && groups.isNotEmpty() && !reversed) {
            // A jump beyond the retained bounded proof cannot re-advertise an old approach.
            // This suppresses presentation only; it never manufactures a camera/primary passage.
            consumed.addAll(encountered.keys)
            encountered.clear()
        }
        if (scopePath != null && (reversed || (!continuation && groups.isEmpty() && !sameWay))) {
            // A reliable departure/reversal establishes a new approach; a missing fix never does.
            encountered.clear(); consumed.removeAll { it.startsWith("$bundleIdentity|") }; frozenGroups = snapshot.relationGroupIDs; departed = true; exhausted = false; scopeLost = false
        }
        if (scopePath != null && sameWay && frozenGroups.isNotEmpty() && groups.isEmpty()) scopeLost = true
        if (scopePath == null || departed) { frozenGroups = snapshot.relationGroupIDs; departed = false }
        else if (frozenGroups.isNotEmpty()) frozenGroups = groups

        for ((key, encounter) in encountered) {
            val target = encounter.candidate
            val targetIndex = encounter.path.indexOfFirst { it.wayID == target.originWayID && it.direction == target.direction && target.stationM >= it.startM - 1e-6 && target.stationM <= it.endM + 1e-6 }
            val currentIndex = encounter.path.indexOfFirst { it.wayID == snapshot.wayID && it.direction == snapshot.direction && snapshot.chainageM >= it.startM - 1e-6 && snapshot.chainageM <= it.endM + 1e-6 }
            if ((snapshot.wayID == target.originWayID && snapshot.direction == target.direction && target.direction * (snapshot.chainageM - target.stationM) >= -1e-6) ||
                (targetIndex >= 0 && currentIndex > targetIndex)) consumed += key
        }
        encountered.keys.removeAll(consumed)
        val allowedPath = if(scopeLost) emptyList() else snapshot.path.takeWhile { path ->
            (path.wayID == snapshot.wayID && path.direction == snapshot.direction) || (snapshot.topologyAvailable && frozenGroups.isNotEmpty() && path.relationGroupIDs.intersect(frozenGroups).isNotEmpty())
        }
        val accepted = snapshot.candidates.filter { candidate ->
            candidate.distanceM.isFinite() && candidate.distanceM > 0 && candidate.distanceM <= snapshot.lookaheadDistanceM &&
                candidate.speedKmh in 1..300 && allowedPath.any {
            it.wayID == candidate.originWayID && it.direction == candidate.direction && candidate.stationM >= it.startM - 1e-6 && candidate.stationM <= it.endM + 1e-6
        } }
        accepted.forEach {
            if (encountered.size >= 64 || consumed.size >= 1024) { exhausted = true; return@forEach }
            encountered[key(it)] = Encounter(it, allowedPath)
            if (it.distanceM <= 0 || (snapshot.wayID == it.originWayID && snapshot.direction == it.direction && it.direction * (snapshot.chainageM - it.stationM) >= -1e-6)) consumed += key(it)
        }
        latest = snapshot.copy(path = allowedPath, candidates = accepted)
        if(allowedPath.isNotEmpty()) lastPath = allowedPath
        acceptedAtMs = fixAtMs
    }

    private fun key(candidate: UpcomingSpeedLimitCandidate) = "${bundle.orEmpty()}|${candidate.identity}"
    fun presentation(currentKmh: Int?, unlimited: Boolean, currentReliable: Boolean, nowMs: Long): UpcomingSpeedLimitCandidate? {
        if (exhausted || !currentReliable || nowMs - acceptedAtMs !in 0 until 3000) return null
        val current = if (unlimited) Double.POSITIVE_INFINITY else currentKmh?.toDouble() ?: return null
        val snapshot = latest ?: return null
        return snapshot.candidates.filter { it.distanceM.isFinite() && it.distanceM > 0 && it.distanceM <= snapshot.lookaheadDistanceM && it.speedKmh in 1..300 && it.speedKmh < current && key(it) !in consumed }
            .minWithOrNull(compareBy<UpcomingSpeedLimitCandidate> { it.distanceM }.thenBy { it.signID })
    }
}

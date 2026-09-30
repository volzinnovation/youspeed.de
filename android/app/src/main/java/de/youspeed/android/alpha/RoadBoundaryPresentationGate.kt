package de.youspeed.android.alpha

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** Display maturity only. This selection never changes detector, corridor or sign evidence. */
data class RoadBoundaryPresentationItem(val trackId: Long, val boundaryIndex: Int?, val state: String,
    val observationCount: Int, val firstObservedSeconds: Double?, val lastObservedSeconds: Double, val missedExposures: Int)
data class RoadBoundaryPresentationSnapshot(val accepted: Boolean, val reason: String?,
    val visibleBoundaryIndices: List<Int>, val items: List<RoadBoundaryPresentationItem>, val rawCount: Int,
    val operationCount: Int = 0) {
    val confirmedCount get() = items.count { it.state == "confirmed" }
    val tentativeCount get() = items.count { it.state == "tentative" }
    val missingCount get() = items.count { it.state == "missing" }
    companion object { fun rejected(reason: String, rawCount: Int = 0) =
        RoadBoundaryPresentationSnapshot(false, reason, emptyList(), emptyList(), rawCount) }
}

/** At most six current curves and six short-lived identities. Missing points are never rendered. */
class RoadBoundaryPresentationGate {
    private data class Track(val id: Long, val boundary: RoadBoundaryEvidence, val firstObserved: Double?,
        val lastObserved: Double, val observations: Int, val confirmed: Boolean, val misses: Int)
    private var tracks = emptyList<Track>()
    private var scope: String? = null
    private var lastTime = Double.NEGATIVE_INFINITY
    private var nextId = 1L
    fun reset() { tracks = emptyList(); scope = null; lastTime = Double.NEGATIVE_INFINITY }

    fun update(boundaries: List<RoadBoundaryEvidence>, exposureSeconds: Double, key: String,
        shouldContinue: () -> Boolean = { true }): RoadBoundaryPresentationSnapshot {
        val rawCount = boundaries.size
        if (!exposureSeconds.isFinite()) return RoadBoundaryPresentationSnapshot.rejected("invalid_timestamp", rawCount)
        if (scope == key && exposureSeconds <= lastTime) return RoadBoundaryPresentationSnapshot.rejected(
            if (exposureSeconds == lastTime) "duplicate_exposure" else "out_of_order_exposure", rawCount)
        var operations = 0
        fun check(cost: Int = 1): Boolean { operations += cost; return operations <= 20_000 && shouldContinue() }
        fun aborted(): RoadBoundaryPresentationSnapshot { reset(); return RoadBoundaryPresentationSnapshot.rejected("presentation_budget",rawCount) }
        if (!check()) return aborted()
        val resetReason = when { scope != null && scope != key -> "scope_or_geometry"; exposureSeconds-lastTime > .75 && tracks.isNotEmpty() -> "exposure_gap"; else -> null }
        val prior = if (scope == key && exposureSeconds-lastTime <= .75) tracks.filter { exposureSeconds-it.lastObserved <= .75 } else emptyList()
        val current = boundaries.take(6).mapIndexedNotNull { index,b ->
            if (!check(b.points.size.coerceAtMost(33))) return aborted()
            if (b.points.size !in 2..32 || !b.confidence.isFinite() || b.confidence !in 0.0..1.0 ||
                b.points.any { !it.x.isFinite() || !it.y.isFinite() || it.x !in 0.0..1.0 || it.y !in 0.0..1.0 } ||
                b.points.zipWithNext().any { (a,c) -> c.y <= a.y }) null else index to b
        }
        data class Pairing(val distance: Double, val prior: Int, val current: Int)
        val pairs = arrayListOf<Pairing>()
        for ((i,a) in prior.withIndex()) for ((j,b) in current.withIndex()) {
            if (!check((a.boundary.points.size+b.second.points.size)*5)) return aborted()
            if (a.boundary.cue != b.second.cue) continue
            val distance = distance(a.boundary.points,b.second.points)
            if (distance != null) pairs += Pairing(distance,i,j)
        }
        val priorUsed = mutableSetOf<Int>(); val assignments = mutableMapOf<Int,Int>()
        for (pair in pairs.sortedWith(compareBy<Pairing> { it.distance }.thenBy { prior[it.prior].id }.thenBy { it.current })) {
            if (pair.prior !in priorUsed && pair.current !in assignments) { priorUsed += pair.prior; assignments[pair.current] = pair.prior }
        }
        var serial = nextId
        val updated = arrayListOf<Track>(); val items = arrayListOf<RoadBoundaryPresentationItem>(); val visible = arrayListOf<Int>()
        for ((index,entry) in current.withIndex()) {
            if (!check()) return aborted()
            val old = assignments[index]?.let { prior[it] }
            val observed = entry.second.provenance != RoadBoundaryProvenance.TRACKED
            val first = old?.firstObserved ?: exposureSeconds.takeIf { observed }
            val count = (old?.observations ?: 0) + if (observed) 1 else 0
            val confirmed = old?.confirmed == true || (observed && count >= 2 && first != null && exposureSeconds-first >= .30)
            val track = Track(old?.id ?: serial++, entry.second, first, exposureSeconds, count, confirmed, 0)
            updated += track
            if (confirmed) visible += entry.first
            items += RoadBoundaryPresentationItem(track.id,entry.first,if(confirmed) "confirmed" else "tentative",count,first,exposureSeconds,0)
        }
        for ((index,old) in prior.withIndex()) {
            if (!check()) return aborted()
            if (index !in priorUsed && old.confirmed && old.misses == 0 && exposureSeconds-old.lastObserved <= .75) {
                val missing = old.copy(misses=1); updated += missing
                items += RoadBoundaryPresentationItem(old.id,null,"missing",old.observations,old.firstObserved,old.lastObserved,1)
            }
        }
        if (!check()) return aborted()
        tracks = updated.take(12); scope = key; lastTime = exposureSeconds; nextId = serial
        return RoadBoundaryPresentationSnapshot(true,resetReason,visible,items,rawCount,operations)
    }

    private fun distance(a: List<LanePoint>, b: List<LanePoint>): Double? {
        val top = max(a.first().y,b.first().y); val bottom = min(a.last().y,b.last().y)
        if (bottom-top < .12) return null
        val deltas = (0..4).map { i -> val y = top+(bottom-top)*i/4.0; roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y) }
        val mean = deltas.sumOf { abs(it) }/5
        val signedMean = deltas.sum()/5
        return mean.takeIf { it <= .045 && deltas.all { d -> abs(d) <= .07 && abs(d-signedMean) <= .025 } }
    }
}

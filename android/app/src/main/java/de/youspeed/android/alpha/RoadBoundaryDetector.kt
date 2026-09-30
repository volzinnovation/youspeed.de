package de.youspeed.android.alpha

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Image evidence only: even a PAINT cue is not a semantic road/lane classification. */
enum class RoadBoundaryCue { PAINT, EDGE }
enum class RoadBoundaryProvenance { FRESH, TRACKED, FUSED }
data class RoadBoundaryEvidence(
    val points: List<LanePoint>,
    val confidence: Double,
    val cue: RoadBoundaryCue,
    val supportRows: Int,
    val provenance: RoadBoundaryProvenance = RoadBoundaryProvenance.FRESH,
    val lastFreshTimestampSeconds: Double? = null,
    val evidenceAgeSeconds: Double = 0.0,
    val trackedAnchorCount: Int = 0,
)
/** These pairs are unassigned hypotheses. A calibrated trajectory must identify the ego path. */
data class RoadCorridorHypothesis(val leftBoundaryIndex: Int, val rightBoundaryIndex: Int, val confidence: Double)
data class RoadBoundaryFrame(
    val boundaries: List<RoadBoundaryEvidence>,
    val corridors: List<RoadCorridorHypothesis>,
    val timestampSeconds: Double,
    val budgetExceeded: Boolean = false,
    val operationCount: Int = 0,
    val temporalOperationCount: Int = 0,
    val temporalResetReason: String? = null,
)
data class RoadBoundarySearchGuidance(val horizonY: Double? = null, val polylines: List<List<LanePoint>> = emptyList())

/** Exact rows shared by detection and sparse horizontal preprocessing. */
internal object RoadBoundarySamplingRows {
    fun top(horizonY: Double?) = horizonY?.takeIf(Double::isFinite)?.let { (it+0.03).coerceIn(0.08,0.83) } ?: 0.50
    fun centers(height: Int, horizonY: Double?): IntArray {
        val topY = top(horizonY)
        val count = min(24,((0.94-topY)*(height-1)).roundToInt()+1).coerceAtLeast(8)
        return IntArray(count) { row -> ((0.94-row*(0.94-topY)/(count-1))*(height-1)).roundToInt() }
    }
    fun support(height: Int, horizonY: Double?): IntArray = centers(height,horizonY)
        .flatMap { listOf(it-1,it,it+1) }.distinct().sorted().toIntArray()
}

internal fun roadBoundaryXAt(points: List<LanePoint>, y: Double): Double {
    if (y <= points.first().y) return points.first().x
    if (y >= points.last().y) return points.last().x
    val index = points.indexOfFirst { it.y >= y }.coerceAtLeast(1)
    val a = points[index-1]; val b = points[index]
    return a.x + (b.x-a.x)*(y-a.y)/(b.y-a.y)
}

/**
 * Portable bounded CPU image front end, shared arithmetically with iPhone. The caller provides
 * upright luma reduced with a single aspect-preserving scale to at most 384 x 216. Twenty-four
 * sampled rows use prefix sums for ridge/edge contrast; capped greedy piecewise tracks preserve
 * observed curves and multiple boundaries without an unbounded line-hypothesis search.
 *
 * Edge-only structures never create corridor hypotheses. Shadows, barriers and buildings can
 * still resemble markings: this output cannot establish drivable space or sign applicability.
 * A cancelled/deadline-exceeded call returns no partial geometry and retains no frame state.
 */
class RoadBoundaryDetector {
    private data class Sample(val point: LanePoint, val strength: Double, val cue: RoadBoundaryCue, val row: Int)
    private class Track(val samples: MutableList<Sample>, val guide: List<LanePoint>? = null, val guideCorrectionLimit: Double) {
        fun predictedX(y: Double): Double {
            val last = samples.last()
            val guided = guide?.let { last.point.x + roadBoundaryXAt(it,y)-roadBoundaryXAt(it,last.point.y) }
            if (samples.size == 1) return guided ?: last.point.x
            val before = samples[max(0, samples.size - 3)]
            val slope = ((last.point.x - before.point.x) / (last.point.y - before.point.y)).coerceIn(-2.0, 2.0)
            val local = last.point.x + slope * (y - last.point.y)
            // Two current observations outrank an older curve. A prior may only nudge the
            // next association by one analysis pixel, never bend it onto adjacent paint.
            return guided?.let { local + (0.4 * (it - local)).coerceIn(-guideCorrectionLimit, guideCorrectionLimit) } ?: local
        }
    }
    private class Budget(val maximum: Int, val shouldContinue: () -> Boolean) {
        var used = 0
        fun check(cost: Int = 1): Boolean {
            if (cost > maximum - used) return false
            used += cost
            return shouldContinue()
        }
    }

    fun detect(
        grayscale: ByteArray,
        width: Int,
        height: Int,
        timestampSeconds: Double,
        maximumOperations: Int = 250_000,
        guidance: RoadBoundarySearchGuidance? = null,
        shouldContinue: () -> Boolean = { true },
    ): RoadBoundaryFrame {
        val budget = Budget(maximumOperations.coerceAtLeast(0), shouldContinue)
        fun empty(exceeded: Boolean = false) = RoadBoundaryFrame(emptyList(), emptyList(), timestampSeconds, exceeded, budget.used)
        if (width !in 64..384 || height !in 64..216 || grayscale.size != width * height || !timestampSeconds.isFinite()) return empty()
        if (!budget.check()) return empty(true)
        val active = ArrayList<Track>()
        val completed = ArrayList<Track>()
        val prefix = IntArray(width + 1)
        val strengths = DoubleArray(width)
        val paints = BooleanArray(width)
        val radii = (1..3).map { max(1, (it * width / 384.0).roundToInt()) }.distinct()
        val margin = 4 * radii.last() + 2
        val suppression = max(3, (width * 0.012).roundToInt())
        val guides = guidance?.polylines.orEmpty().take(8).filter { p -> p.size in 2..12 &&
            p.all { it.x.isFinite() && it.y.isFinite() && it.x in 0.0..1.0 && it.y in 0.0..1.0 } &&
            p.zipWithNext().all { (a,b) -> b.y > a.y } }
        val topY = RoadBoundarySamplingRows.top(guidance?.horizonY)
        val rows = RoadBoundarySamplingRows.centers(height,guidance?.horizonY)
        for (row in rows.indices) {
            if (!budget.check()) return empty(true)
            val y = rows[row]
            val normalizedY = y.toDouble() / (height - 1)
            prefix[0] = 0
            strengths.fill(0.0)
            paints.fill(false)
            for (x in 0 until width) {
                if (x % 32 == 0 && !budget.check(32)) return empty(true)
                prefix[x + 1] = prefix[x] + (grayscale[(y - 1) * width + x].toInt() and 255) +
                    (grayscale[y * width + x].toInt() and 255) + (grayscale[(y + 1) * width + x].toInt() and 255)
            }
            fun mean(center: Int, radius: Int): Double =
                (prefix[center + radius + 1] - prefix[center - radius]).toDouble() / (3 * (2 * radius + 1))
            for (x in margin until width - margin) {
                if (x % 32 == 0 && !budget.check(32 * radii.size)) return empty(true)
                var ridge = 0.0
                for (radius in radii) {
                    val middle = mean(x, radius)
                    if (middle >= 95) {
                        val offset = 3 * radius + 1
                        ridge = max(ridge, min(middle - mean(x - offset, radius), middle - mean(x + offset, radius)))
                    }
                }
                val edge = abs(mean(x - 3, 1) - mean(x + 3, 1))
                if (ridge >= 26) { strengths[x] = ridge; paints[x] = true }
                else if (edge >= 45) strengths[x] = edge * 0.45
            }
            val candidates = ArrayList<Sample>()
            for (x in margin until width - margin) {
                if (x % 32 == 0 && !budget.check(32 * (2 * suppression + 1))) return empty(true)
                if (strengths[x] == 0.0) continue
                var winner = true
                for (other in max(margin, x - suppression)..min(width - margin - 1, x + suppression)) {
                    if (strengths[other] > strengths[x] || (strengths[other] == strengths[x] && other < x)) { winner = false; break }
                }
                if (winner) candidates.add(Sample(LanePoint(x.toDouble() / (width - 1), normalizedY), strengths[x],
                    if (paints[x]) RoadBoundaryCue.PAINT else RoadBoundaryCue.EDGE, row))
            }
            fun guideDistance(sample: Sample) = guides.minOfOrNull { abs(sample.point.x-roadBoundaryXAt(it,sample.point.y)) } ?: 1.0
            // Priors only rank already observed pixels; they cannot create a candidate or raise its confidence.
            val rowCandidates = candidates.sortedWith(compareByDescending<Sample> {
                it.strength*(1+0.15*(1-guideDistance(it)/0.08).coerceIn(0.0,1.0))
            }.thenBy { it.point.x }).take(12)
            val expired = active.filter { row - it.samples.last().row > 4 }
            completed.addAll(expired)
            active.removeAll(expired.toSet())
            val usedTracks = BooleanArray(active.size)
            val usedCandidates = BooleanArray(rowCandidates.size)
            // At most 12 x 12 comparisons per assignment, at most 12 assignments per row.
            repeat(min(active.size, rowCandidates.size)) {
                var bestTrack = -1; var bestCandidate = -1; var bestDistance = Double.POSITIVE_INFINITY
                for (trackIndex in active.indices) {
                    if (!budget.check(rowCandidates.size + 1)) return empty(true)
                    if (usedTracks[trackIndex]) continue
                    val track = active[trackIndex]
                    val gap = row - track.samples.last().row
                    val tolerance = if (track.samples.size == 1) 0.065 else 0.028 + 0.012 * (gap - 1)
                    for (candidateIndex in rowCandidates.indices) {
                        if (usedCandidates[candidateIndex]) continue
                        val sample = rowCandidates[candidateIndex]
                        val distance = abs(sample.point.x - track.predictedX(normalizedY))
                        if (distance <= tolerance && distance < bestDistance) {
                            bestDistance = distance; bestTrack = trackIndex; bestCandidate = candidateIndex
                        }
                    }
                }
                if (bestTrack >= 0) {
                    active[bestTrack].samples.add(rowCandidates[bestCandidate])
                    usedTracks[bestTrack] = true; usedCandidates[bestCandidate] = true
                }
            }
            for (index in rowCandidates.indices) {
                if (!usedCandidates[index] && active.size < 12) {
                    val sample = rowCandidates[index]
                    val guide = guides.minByOrNull { abs(sample.point.x-roadBoundaryXAt(it,sample.point.y)) }
                        ?.takeIf { abs(sample.point.x-roadBoundaryXAt(it,sample.point.y)) <= 0.05 }
                    active.add(Track(arrayListOf(sample),guide,1.0 / (width - 1)))
                }
            }
        }
        completed.addAll(active)
        val evidence = ArrayList<RoadBoundaryEvidence>()
        for (track in completed) {
            if (!budget.check(track.samples.size + 1)) return empty(true)
            val samples = track.samples
            val span = samples.first().point.y - samples.last().point.y
            if (samples.size < 8 || span < min(0.16,(0.94-topY)*0.6)) continue
            val paintCount = samples.count { it.cue == RoadBoundaryCue.PAINT }
            val cue = if (paintCount >= 6 && paintCount * 5 >= samples.size * 3) RoadBoundaryCue.PAINT else RoadBoundaryCue.EDGE
            val density = samples.size.toDouble() / (samples.last().row - samples.first().row + 1)
            var confidence = min(1.0, span / 0.32) * density * min(1.0, samples.sumOf { it.strength } / samples.size / 90.0)
            if (cue == RoadBoundaryCue.EDGE) confidence = min(0.40, confidence)
            if (confidence < 0.22) continue
            evidence.add(RoadBoundaryEvidence(samples.asReversed().map { it.point }, confidence, cue, samples.size))
        }
        val boundaries = evidence.sortedWith(compareByDescending<RoadBoundaryEvidence> { it.confidence }
            .thenByDescending { it.supportRows }.thenBy { it.points.last().x }).take(6).sortedBy { it.points.last().x }
        val corridors = ArrayList<RoadCorridorHypothesis>()
        for (leftIndex in boundaries.indices) {
            if (!budget.check(32)) return empty(true)
            // Adjacent observed boundaries only; never skip an intervening marking to invent a lane.
            val rightIndex = leftIndex + 1
            if (rightIndex >= boundaries.size) continue
            val left = boundaries[leftIndex]; val right = boundaries[rightIndex]
            if (left.cue != RoadBoundaryCue.PAINT || right.cue != RoadBoundaryCue.PAINT || min(left.supportRows, right.supportRows) < 10) continue
            val top = max(left.points.first().y, right.points.first().y)
            val bottom = min(left.points.last().y, right.points.last().y)
            if (bottom - top < 0.24) continue
            val topWidth = xAt(right.points, top) - xAt(left.points, top)
            val bottomWidth = xAt(right.points, bottom) - xAt(left.points, bottom)
            if (topWidth !in 0.015..0.60 || bottomWidth !in 0.09..0.85 || bottomWidth < topWidth + 0.04) continue
            val overlapRows = (left.points + right.points).filter { it.y >= top && it.y <= bottom }
            if (overlapRows.any { xAt(right.points, it.y) - xAt(left.points, it.y) < 0.012 }) continue
            corridors.add(RoadCorridorHypothesis(leftIndex, rightIndex, min(left.confidence, right.confidence)))
        }
        if (!budget.check()) return empty(true)
        return RoadBoundaryFrame(boundaries, corridors.sortedWith(compareByDescending<RoadCorridorHypothesis> { it.confidence }
            .thenBy { it.leftBoundaryIndex }).take(2), timestampSeconds, false, budget.used)
    }

    private fun xAt(points: List<LanePoint>, y: Double): Double {
        val index = points.indexOfFirst { it.y >= y }.coerceAtLeast(1)
        val a = points[index - 1]; val b = points[index]
        return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
    }
}

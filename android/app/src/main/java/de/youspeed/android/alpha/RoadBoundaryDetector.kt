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
    /** Current exposure's contiguous paint support. Empty retains the legacy full-points contract. */
    val observedSegments: List<List<LanePoint>> = emptyList(),
    val geometryConfidence: Double? = null,
    val paintOccupancy: Double? = null,
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
    val rejectionCounts: Map<String, Int> = emptyMap(),
    val detectionVariant: String = "baseline",
)
data class RoadBoundaryDetectionOptions(val useSearchBands: Boolean = false, val groupFragments: Boolean = false) {
    val identifier: String get() = if (useSearchBands) { if (groupFragments) "bands_fragments" else "bands" } else if (groupFragments) "fragments" else "baseline"
}
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
/** Optional offline diagnostic sink. Payloads are allocated only when supplied;
 * observers must not mutate state read by shouldContinue. */
typealias RoadBoundaryTraceObserver = (Map<String, Any?>) -> Unit

class RoadBoundaryDetector {
    private data class Sample(val point: LanePoint, val strength: Double, val cue: RoadBoundaryCue, val row: Int, val stripeWidth: Int)
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
        options: RoadBoundaryDetectionOptions = RoadBoundaryDetectionOptions(),
        trace: RoadBoundaryTraceObserver? = null,
        shouldContinue: () -> Boolean = { true },
    ): RoadBoundaryFrame {
        fun sampleID(sample: Sample) = sample.row * width + (sample.point.x * (width-1)).roundToInt()
        fun sampleFields(sample: Sample): Map<String, Any?> = mapOf(
            "sampleID" to sampleID(sample), "point" to listOf(sample.point.x,sample.point.y), "strength" to sample.strength,
            "cue" to sample.cue.name.lowercase(), "row" to sample.row, "stripeWidth" to sample.stripeWidth)
        fun trackFields(track: Track, outcome: String): Map<String, Any?> = mapOf(
            "stage" to "track", "trackID" to sampleID(track.samples.first()),
            "samples" to track.samples.map(::sampleFields), "outcome" to outcome)
        val budget = Budget(maximumOperations.coerceAtLeast(0), shouldContinue)
        val rejections = linkedMapOf<String,Int>()
        fun reject(reason: String, count: Int = 1) { if (count > 0) rejections[reason] = (rejections[reason] ?: 0)+count }
        fun empty(exceeded: Boolean = false): RoadBoundaryFrame {
            trace?.invoke(mapOf("stage" to "completion", "status" to if(exceeded) "budget_or_cancelled" else "invalid_input", "operationCount" to budget.used))
            return RoadBoundaryFrame(emptyList(), emptyList(), timestampSeconds, exceeded, budget.used,
                rejectionCounts = rejections.toMap(), detectionVariant = options.identifier)
        }
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
        trace?.invoke(mapOf("stage" to "configuration", "schemaVersion" to 1, "width" to width, "height" to height,
            "samplingRows" to rows.toList(), "variant" to options.identifier, "guides" to guides.map { it.map { p -> listOf(p.x,p.y) } }))
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
                if (winner) {
                    var stripeWidth = 1
                    if (options.groupFragments && paints[x]) {
                        if (!budget.check(26)) return empty(true)
                        var left = x; var right = x
                        while (left > margin && paints[left-1] && x-left < 12) left--
                        while (right < width-margin-1 && paints[right+1] && right-x < 12) right++
                        stripeWidth = right-left+1
                    }
                    candidates.add(Sample(LanePoint(x.toDouble() / (width - 1), normalizedY), strengths[x],
                        if (paints[x]) RoadBoundaryCue.PAINT else RoadBoundaryCue.EDGE, row, stripeWidth))
                }
            }
            fun guideDistance(sample: Sample) = guides.minOfOrNull { abs(sample.point.x-roadBoundaryXAt(it,sample.point.y)) } ?: 1.0
            // Priors only rank already observed pixels; they cannot create a candidate or raise its confidence.
            val ranked = candidates.sortedWith(compareByDescending<Sample> {
                it.strength*(1+0.15*(1-guideDistance(it)/0.08).coerceIn(0.0,1.0))
            }.thenBy { it.point.x })
            var rowCandidates = ranked.take(12)
            if (options.useSearchBands) {
                if (!budget.check(candidates.size*3+24)) return empty(true)
                // Reserve equal capacity around two curved hypotheses; fill from the whole
                // image. Calibration never crops away a stripe or manufactures paint.
                val t = ((normalizedY-topY)/max(0.01,0.94-topY)).coerceIn(0.0,1.0)
                val ordered = guides.sortedBy { roadBoundaryXAt(it,0.94) }
                val centers = if (ordered.size >= 2) listOf(roadBoundaryXAt(ordered.first(),normalizedY),roadBoundaryXAt(ordered.last(),normalizedY))
                    else listOf(0.5-0.07-0.29*t,0.5+0.07+0.29*t)
                val halfWidth = 0.045+0.105*t
                val selected = linkedSetOf<Int>()
                for (center in centers) {
                    var reserved = 0
                    for (index in ranked.indices) {
                        if (reserved < 4 && abs(ranked[index].point.x-center)<=halfWidth && selected.add(index)) reserved++
                    }
                }
                for (index in ranked.indices) { if (selected.size < 12) selected.add(index) }
                rowCandidates = selected.sorted().map { ranked[it] }
                reject("outside_bands_retained",rowCandidates.count { sample -> centers.all { abs(sample.point.x-it)>halfWidth } })
            }
            trace?.invoke(mapOf("stage" to "row", "row" to row, "y" to normalizedY,
                "preCap" to ranked.map(::sampleFields), "postCap" to rowCandidates.map(::sampleFields)))
            reject("candidate_capacity",candidates.size-rowCandidates.size)
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
                    trace?.invoke(mapOf("stage" to "association", "outcome" to "assigned", "row" to row,
                        "sampleID" to sampleID(rowCandidates[bestCandidate]), "trackID" to sampleID(active[bestTrack].samples.first()),
                        "distance" to bestDistance, "predictedX" to active[bestTrack].predictedX(normalizedY)))
                    active[bestTrack].samples.add(rowCandidates[bestCandidate])
                    usedTracks[bestTrack] = true; usedCandidates[bestCandidate] = true
                }
            }
            for (index in rowCandidates.indices) {
                if (!usedCandidates[index] && active.size < 12) {
                    val sample = rowCandidates[index]
                    val guide = guides.minByOrNull { abs(sample.point.x-roadBoundaryXAt(it,sample.point.y)) }
                        ?.takeIf { abs(sample.point.x-roadBoundaryXAt(it,sample.point.y)) <= 0.05 }
                    trace?.invoke(mapOf("stage" to "association", "outcome" to "created", "row" to row,
                        "sampleID" to sampleID(sample), "trackID" to sampleID(sample)))
                    active.add(Track(arrayListOf(sample),guide,1.0 / (width - 1)))
                } else if (!usedCandidates[index]) {
                    trace?.invoke(mapOf("stage" to "association", "outcome" to "active_track_capacity", "row" to row,
                        "sampleID" to sampleID(rowCandidates[index])))
                }
            }
        }
        completed.addAll(active)
        // Accept original measured tracks first; gap fitting can recover additional
        // hypotheses but never erase supported paint when a global model fails.
        val evidence = ArrayList<RoadBoundaryEvidence>()
        val fragments = ArrayList<List<Sample>>()
        for (track in completed) {
            if (!budget.check(track.samples.size + 1)) return empty(true)
            val samples = track.samples
            val span = samples.first().point.y - samples.last().point.y
            if (samples.size < 8) {
                trace?.invoke(trackFields(track,"track_support"))
                reject("track_support")
                if (options.groupFragments) fragments.add(samples.toList())
                continue
            }
            if (span < min(0.16,(0.94-topY)*0.6)) {
                trace?.invoke(trackFields(track,"track_span"))
                reject("track_span")
                if (options.groupFragments) fragments.add(samples.toList())
                continue
            }
            val paintCount = samples.count { it.cue == RoadBoundaryCue.PAINT }
            val cue = if (paintCount >= 6 && paintCount * 5 >= samples.size * 3) RoadBoundaryCue.PAINT else RoadBoundaryCue.EDGE
            val density = samples.size.toDouble() / (samples.last().row - samples.first().row + 1)
            var confidence = min(1.0, span / 0.32) * density * min(1.0, samples.sumOf { it.strength } / samples.size / 90.0)
            if (cue == RoadBoundaryCue.EDGE) confidence = min(0.40, confidence)
            if (confidence < 0.22) {
                trace?.invoke(trackFields(track,"confidence"))
                reject("confidence")
                if (options.groupFragments) fragments.add(samples.toList())
                continue
            }
            trace?.invoke(trackFields(track,"accepted"))
            evidence.add(RoadBoundaryEvidence(samples.asReversed().map { it.point },confidence,cue,samples.size,
                observedSegments=if (options.groupFragments && cue==RoadBoundaryCue.PAINT) paintedSegments(samples) else emptyList(),
                paintOccupancy=if (options.groupFragments && cue==RoadBoundaryCue.PAINT) density else null))
            if (options.groupFragments) reject("supported_track_preserved")
        }
        fun ranked(values:List<RoadBoundaryEvidence>) = values.sortedWith(compareByDescending<RoadBoundaryEvidence> { it.confidence }
            .thenByDescending { it.supportRows }.thenBy { it.points.last().x })
        val protected = ranked(evidence).take(6)
        val additions = ArrayList<RoadBoundaryEvidence>()
        if (options.groupFragments) {
            // Only rejected short/sparse fragments can be consumed by a speculative join;
            // accepted raw tracks keep their geometry and priority at the output cap.
            fragments.sortWith(compareByDescending<List<Sample>> { it.size }.thenBy { it.first().point.x })
            reject("fragment_capacity",max(0,fragments.size-32))
            while (fragments.size>32) fragments.removeAt(fragments.lastIndex)
            val consumed = mutableSetOf<Int>()
            for (i in fragments.indices) {
                if (i in consumed) continue
                var changed = true
                while (changed) {
                    changed = false
                    for (j in fragments.indices) {
                        if (j==i || j in consumed) continue
                        val first=fragments[i]; val second=fragments[j]
                        if (!budget.check((first.size+second.size)*8+30)) return empty(true)
                        val joined=joinFragments(first,second,width) { reject(it) }
                        if (joined!=null) {
                            fragments[i]=joined; consumed.add(j); changed=true; reject("fragments_joined")
                        }
                    }
                }
            }
            for ((index,samples) in fragments.withIndex()) {
                if (index in consumed) continue
                if (!budget.check(samples.size*8+30)) return empty(true)
                val span=samples.first().point.y-samples.last().point.y
                if (samples.size<6) { reject("fragment_track_support"); continue }
                if (span<min(0.16,(0.94-topY)*0.6)) { reject("fragment_track_span"); continue }
                val paintCount=samples.count { it.cue==RoadBoundaryCue.PAINT }
                if (paintCount<6 || paintCount*5<samples.size*3) { reject("fragment_paint_support"); continue }
                val segments=paintedSegments(samples)
                // Fit only real gaps between observed paint intervals, never continuous shape.
                if (segments.count { it.size>=2 }<2) { reject("fragment_no_supported_gap"); continue }
                val model=validatedModel(samples,max(0.014,2.0/(width-1))) { reject(it) } ?: continue
                val density=samples.size.toDouble()/(samples.last().row-samples.first().row+1)
                val geometric=max(0.0,1-model.maximumResidual/max(0.028,4.0/(width-1)))
                val confidence=min(1.0,span/0.32)*min(1.0,paintCount/10.0)*geometric*
                    min(1.0,samples.sumOf { it.strength }/samples.size/90.0)
                if (confidence<0.22) { reject("fragment_confidence"); continue }
                additions.add(RoadBoundaryEvidence(model.points,confidence,RoadBoundaryCue.PAINT,samples.size,
                    observedSegments=segments,geometryConfidence=geometric,paintOccupancy=density))
            }
        }
        reject("fragment_output_capacity",max(0,additions.size-(6-protected.size)))
        val boundaries=(protected+ranked(additions).take(6-protected.size)).sortedBy { it.points.last().x }
        if (trace != null) {
            for ((origin,values) in listOf("measured" to evidence,"fragment" to additions)) for (boundary in values) {
                trace(mapOf("stage" to "fresh_hypothesis", "origin" to origin, "points" to boundary.points.map { listOf(it.x,it.y) },
                    "confidence" to boundary.confidence, "cue" to boundary.cue.name.lowercase(), "supportRows" to boundary.supportRows,
                    "observedSegments" to boundary.observedSegments.map { it.map { p -> listOf(p.x,p.y) } },
                    "outputIndex" to boundaries.indexOf(boundary).takeIf { it>=0 }))
            }
        }
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
        trace?.invoke(mapOf("stage" to "completion", "status" to "complete", "operationCount" to budget.used))
        return RoadBoundaryFrame(boundaries, corridors.sortedWith(compareByDescending<RoadCorridorHypothesis> { it.confidence }
            .thenBy { it.leftBoundaryIndex }).take(2), timestampSeconds, false, budget.used,
            rejectionCounts=rejections.toMap(), detectionVariant=options.identifier)
    }

    private data class Model(val points: List<LanePoint>, val maximumResidual: Double, val maximumSlope: Double, val curvature: Double)
    /** Centered/scaled quadratic fit; every observed sample must agree (no silent outlier removal). */
    private fun fitModel(samples: List<Sample>): Model? {
        if (samples.size < 3) return null
        val low=samples.minOf { it.point.y }; val high=samples.maxOf { it.point.y }
        val scale=high-low; val center=(high+low)/2
        if (scale < 0.035) return null
        val matrix=Array(3) { DoubleArray(4) }
        for (sample in samples) {
            val t=(sample.point.y-center)/scale; val v=doubleArrayOf(1.0,t,t*t)
            for (r in 0..2) { for (c in 0..2) matrix[r][c]+=v[r]*v[c]; matrix[r][3]+=v[r]*sample.point.x }
        }
        for (column in 0..2) {
            var pivot=column
            for (r in column+1..2) if (abs(matrix[r][column])>abs(matrix[pivot][column])) pivot=r
            if (abs(matrix[pivot][column])<1e-9) return null
            if (pivot!=column) { val swap=matrix[column]; matrix[column]=matrix[pivot]; matrix[pivot]=swap }
            val divisor=matrix[column][column]
            for (c in column..3) matrix[column][c]/=divisor
            for (r in 0..2) if (r!=column) {
                val factor=matrix[r][column]
                for (c in column..3) matrix[r][c]-=factor*matrix[column][c]
            }
        }
        val a=matrix[0][3]; val b=matrix[1][3]; val c=matrix[2][3]
        fun value(y:Double):Double { val t=(y-center)/scale; return a+b*t+c*t*t }
        val residual=samples.maxOf { abs(value(it.point.y)-it.point.x) }
        val points=(0..11).map { index -> val y=low+scale*index/11; LanePoint(value(y),y) }
        if (points.any { !it.x.isFinite() || it.x !in 0.0..1.0 }) return null
        return Model(points,residual,max(abs(b-c),abs(b+c))/scale,abs(2*c)/(scale*scale))
    }
    private fun paintedSegments(samples: List<Sample>): List<List<LanePoint>> {
        val segments=mutableListOf<List<LanePoint>>(); val current=mutableListOf<LanePoint>()
        var previousRow:Int?=null
        for (sample in samples) {
            if (sample.cue!=RoadBoundaryCue.PAINT || previousRow?.let { sample.row-it>1 }==true) {
                if (current.isNotEmpty()) { segments.add(current.reversed()); current.clear() }
            }
            if (sample.cue==RoadBoundaryCue.PAINT) current.add(sample.point)
            previousRow=sample.row
        }
        if (current.isNotEmpty()) segments.add(current.reversed())
        return segments.reversed()
    }
    private fun joinFragments(lhs:List<Sample>, rhs:List<Sample>, width:Int, reject:(String)->Unit):List<Sample>? {
        if (lhs.size<3 || rhs.size<3 || lhs.count { it.cue==RoadBoundaryCue.PAINT }*5<lhs.size*4 ||
            rhs.count { it.cue==RoadBoundaryCue.PAINT }*5<rhs.size*4) return null
        val near:List<Sample>; val far:List<Sample>
        if (lhs.last().row<rhs.first().row) { near=lhs; far=rhs }
        else if (rhs.last().row<lhs.first().row) { near=rhs; far=lhs }
        else return null
        val gap=far.first().row-near.last().row
        if (gap<=1 || gap>9) return null
        val a=near[max(0,near.size-3)]; val b=near.last(); val c=far.first(); val d=far[min(2,far.size-1)]
        val slopeNear=(b.point.x-a.point.x)/(b.point.y-a.point.y)
        val slopeFar=(d.point.x-c.point.x)/(d.point.y-c.point.y)
        val expected=b.point.x+slopeNear*(c.point.y-b.point.y)
        val widthNear=near.sumOf { it.stripeWidth }.toDouble()/near.size
        val widthFar=far.sumOf { it.stripeWidth }.toDouble()/far.size
        if (abs(slopeNear-slopeFar)>0.65) { reject("fragment_tangent"); return null }
        if (abs(expected-c.point.x)>0.035) { reject("fragment_endpoint"); return null }
        if (max(widthNear,widthFar)>min(widthNear,widthFar)*2.5) { reject("fragment_width"); return null }
        val joined=near+far
        if (validatedModel(joined,max(0.012,2.0/(width-1)),reject)==null) return null
        return joined
    }

    private fun validatedModel(samples:List<Sample>,residualLimit:Double,reject:(String)->Unit):Model? {
        val model=fitModel(samples) ?: run { reject("fragment_fit_invalid"); return null }
        var accepted=true
        if (model.maximumResidual>residualLimit) { reject("fragment_fit_residual"); accepted=false }
        if (model.maximumSlope>1.8) { reject("fragment_fit_slope"); accepted=false }
        if (model.curvature>7) { reject("fragment_fit_curvature"); accepted=false }
        return if (accepted) model else null
    }

    private fun xAt(points: List<LanePoint>, y: Double): Double {
        val index = points.indexOfFirst { it.y >= y }.coerceAtLeast(1)
        val a = points[index - 1]; val b = points[index]
        return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
    }
}

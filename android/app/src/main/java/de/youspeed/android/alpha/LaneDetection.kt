package de.youspeed.android.alpha

import kotlin.math.ceil
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Coordinates in the complete, upright analysis image (origin at top left). */
data class LanePoint(val x: Double, val y: Double)
data class LaneBoundary(val points: List<LanePoint>, val confidence: Double)
enum class LaneDetectionState { RELIABLE, UNCERTAIN, UNAVAILABLE }

/** Capture time in monotonic seconds. Runtime geometry/generation and timings travel separately. */
data class LaneDetectionEstimate(
    val left: LaneBoundary?,
    val right: LaneBoundary?,
    val timestampSeconds: Double,
    val state: LaneDetectionState,
) {
    val hasReliablePair: Boolean
        get() = state == LaneDetectionState.RELIABLE && left != null && right != null

    /** Fill only the common observed interval; longer single-side evidence remains a stroke. */
    val corridorPoints: List<LanePoint>
        get() {
            val l = left ?: return emptyList()
            val r = right ?: return emptyList()
            if (!hasReliablePair || l.points.size < 2 || r.points.size < 2) return emptyList()
            val top = max(l.points.first().y, r.points.first().y)
            val bottom = min(l.points.last().y, r.points.last().y)
            if (bottom <= top) return emptyList()
            fun clip(points: List<LanePoint>): List<LanePoint> {
                fun at(y: Double): LanePoint {
                    val index = points.indexOfFirst { it.y >= y }.coerceAtLeast(1)
                    val a = points[index - 1]; val b = points[index]
                    val t = if (b.y > a.y) (y - a.y) / (b.y - a.y) else 0.0
                    return LanePoint(a.x + (b.x - a.x) * t, y)
                }
                return listOf(at(top)) + points.filter { it.y > top && it.y < bottom } + listOf(at(bottom))
            }
            return clip(l.points) + clip(r.points).asReversed()
        }
}

/**
 * Bounded classical baseline shared with iPhone. It detects narrow bright ridges, then fits
 * converging boundaries by row-wise consensus. It deliberately does not invent missing sides
 * or claim curved-road coverage. This is visual evidence, not a driving/speed-limit decision.
 */
class LaneDetector {
    private data class Stripe(val x: Double, val y: Double, val contrast: Double)
    private data class Fit(val slope: Double, val intercept: Double, val samples: List<Stripe>) {
        fun x(y: Double) = slope * y + intercept
    }

    fun detect(grayscale: ByteArray, width: Int, height: Int, timestampSeconds: Double): LaneDetectionEstimate {
        fun unavailable() = LaneDetectionEstimate(null, null, timestampSeconds, LaneDetectionState.UNAVAILABLE)
        // Overflow-safe bounds also prevent accidental full-resolution work on the camera thread.
        if (width !in 64..640 || height !in 64..960 || grayscale.size.toLong() != width.toLong() * height ||
            !timestampSeconds.isFinite()) return unavailable()

        val aspectScale = min(1.0, width * 9.0 / (height * 16.0))
        val minimumSpan = max(0.07, 0.18 * aspectScale)
        val rowCount = min(48, (24 / aspectScale).roundToInt())
        val rowStep = 0.46 / (rowCount - 1)
        val rows = List(rowCount) { index ->
            val y = ((0.48 + index * rowStep) * (height - 1)).roundToInt()
            val radii = listOf(1, 2, 3, 4).map { max(1, (it * width / 384.0).roundToInt()) }.distinct()
            val margin = 4 * (radii.maxOrNull() ?: 1) + 2
            val candidates = ArrayList<Stripe>()
            val strengths = DoubleArray(width)
            fun mean(center: Int, radius: Int): Double {
                var sum = 0
                for (dy in -1..1) for (dx in -radius..radius) {
                    sum += grayscale[(y + dy) * width + center + dx].toInt() and 255
                }
                return sum.toDouble() / (3 * (2 * radius + 1))
            }
            for (x in max(margin, (width * 0.04).roundToInt()) until min(width - margin, (width * 0.96).roundToInt())) {
                var contrast = 0.0
                for (radius in radii) {
                    val center = mean(x, radius)
                    if (center < 80) continue
                    val offset = 3 * radius + 1
                    val ridge = min(center - mean(x - offset, radius), center - mean(x + offset, radius))
                    contrast = max(contrast, ridge)
                }
                if (contrast >= 24) strengths[x] = contrast
            }
            // Collapse a stripe to one local maximum before limiting candidates per image side.
            val suppression = max(3, (width * 0.015).roundToInt())
            for (x in margin until width - margin) {
                val strength = strengths[x]
                if (strength == 0.0) continue
                var winner = true
                for (other in max(margin, x - suppression)..min(width - margin - 1, x + suppression)) {
                    if (strengths[other] > strength || (strengths[other] == strength && other < x)) {
                        winner = false
                        break
                    }
                }
                if (winner) candidates.add(Stripe(x.toDouble() / (width - 1), y.toDouble() / (height - 1), strength))
            }
            candidates
        }
        val leftRows = rows.map { row -> row.filter { it.x <= 0.56 }.sortedByDescending { it.contrast }.take(4) }
        val rightRows = rows.map { row -> row.filter { it.x >= 0.44 }.sortedByDescending { it.contrast }.take(4) }
        var left = boundary(leftRows, isLeft = true, minimumSpan = minimumSpan, rowStep = rowStep)
        var right = boundary(rightRows, isLeft = false, minimumSpan = minimumSpan, rowStep = rowStep)
        if (left != null && right != null && !plausiblePair(left, right, minimumSpan)) {
            // Conflicting fits do not identify an ego lane. Preserve only the substantially better side.
            when {
                left.confidence > right.confidence + 0.20 -> right = null
                right.confidence > left.confidence + 0.20 -> left = null
                else -> { left = null; right = null }
            }
        }
        val state = when {
            left == null && right == null -> LaneDetectionState.UNAVAILABLE
            left != null && right != null && min(left.confidence, right.confidence) >= 0.62 -> LaneDetectionState.RELIABLE
            else -> LaneDetectionState.UNCERTAIN
        }
        return LaneDetectionEstimate(left, right, timestampSeconds, state)
    }

    private fun boundary(rows: List<List<Stripe>>, isLeft: Boolean, minimumSpan: Double, rowStep: Double): LaneBoundary? {
        var best: Fit? = null
        var bestScore = 0.0
        var alternative: Fit? = null
        var alternativeScore = 0.0
        fun valid(slope: Double, intercept: Double, topY: Double, bottomY: Double): Boolean {
            if (if (isLeft) slope !in -3.0..-0.15 else slope !in 0.15..3.0) return false
            val top = slope * topY + intercept
            val bottom = slope * bottomY + intercept
            return top in 0.22..0.78 && if (isLeft) bottom in 0.02..0.49 else bottom in 0.51..0.98
        }
        fun distinct(a: Fit, b: Fit) = abs(a.x(min(a.samples.last().y, b.samples.last().y)) - b.x(min(a.samples.last().y, b.samples.last().y))) > 0.075
        val separation = ceil(minimumSpan / rowStep).toInt()
        for (topRow in 0 until rows.size - separation) for (bottomRow in topRow + separation until rows.size) {
            for (top in rows[topRow]) for (bottom in rows[bottomRow]) {
                val slope = (bottom.x - top.x) / (bottom.y - top.y)
                val intercept = top.x - slope * top.y
                if (!valid(slope, intercept, top.y, bottom.y)) continue
                val samples = rows.mapNotNull { row ->
                    row.minByOrNull { abs(it.x - (slope * it.y + intercept)) }
                        ?.takeIf { abs(it.x - (slope * it.y + intercept)) <= 0.018 }
                }
                if (samples.size < 8 || samples.last().y - samples.first().y < minimumSpan) continue
                val score = samples.sumOf { min(1.0, it.contrast / 70.0) }
                val fit = Fit(slope, intercept, samples)
                val oldBest = best
                if (score > bestScore) {
                    if (oldBest != null && distinct(fit, oldBest)) {
                        alternative = oldBest; alternativeScore = bestScore
                    }
                    best = fit; bestScore = score
                } else if (oldBest != null && distinct(fit, oldBest) && score > alternativeScore) {
                    alternative = fit; alternativeScore = score
                }
            }
        }
        val seed = best ?: return null
        val samples = seed.samples
        val meanY = samples.sumOf { it.y } / samples.size
        val meanX = samples.sumOf { it.x } / samples.size
        val variance = samples.sumOf { (it.y - meanY) * (it.y - meanY) }
        if (variance <= 0) return null
        val slope = samples.sumOf { (it.y - meanY) * (it.x - meanX) } / variance
        val intercept = meanX - slope * meanY
        if (!valid(slope, intercept, samples.first().y, samples.last().y)) return null
        val residual = samples.sumOf { abs(it.x - (slope * it.y + intercept)) } / samples.size
        val span = samples.last().y - samples.first().y
        val expectedRows = 1.0 + span / rowStep
        var confidence = min(1.0, samples.size / expectedRows) * min(1.0, span / (minimumSpan * (0.28 / 0.18))) *
            min(1.0, samples.sumOf { it.contrast } / samples.size / 55.0) * max(0.0, 1.0 - residual / 0.04)
        if (alternative != null && alternativeScore >= bestScore * 0.88 && distinct(seed, alternative)) confidence = min(confidence, 0.49)
        if (confidence < 0.38) return null
        // Restrict rendering to the observed vertical extent; no extrapolated/inferred geometry.
        val points = List(5) { index ->
            val y = samples.first().y + span * index / 4
            LanePoint((slope * y + intercept).coerceIn(0.0, 1.0), y)
        }
        return LaneBoundary(points, confidence.coerceIn(0.0, 1.0))
    }

    private fun plausiblePair(left: LaneBoundary, right: LaneBoundary, minimumSpan: Double): Boolean {
        fun x(boundary: LaneBoundary, y: Double): Double {
            val a = boundary.points.first(); val b = boundary.points.last()
            return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
        }
        val topY = max(left.points.first().y, right.points.first().y)
        val bottomY = min(left.points.last().y, right.points.last().y)
        if (bottomY - topY < minimumSpan) return false
        val topWidth = x(right, topY) - x(left, topY)
        val bottomWidth = x(right, bottomY) - x(left, bottomY)
        val center = (x(right, bottomY) + x(left, bottomY)) / 2
        return topWidth in 0.015..0.55 && bottomWidth in 0.24..0.94 && bottomWidth > topWidth + 0.10 && center in 0.32..0.68
    }
}

/** Single-worker state. Missing sides disappear immediately; geometry is never predicted forward. */
class LaneTracker {
    private var previous: LaneDetectionEstimate? = null
    private var consecutivePairs = 0

    fun reset() { previous = null; consecutivePairs = 0 }

    fun update(estimate: LaneDetectionEstimate): LaneDetectionEstimate {
        var prior = previous
        if (!estimate.timestampSeconds.isFinite()) {
            reset()
            return estimate.copy(left = null, right = null, state = LaneDetectionState.UNAVAILABLE)
        }
        if (prior != null && (estimate.timestampSeconds <= prior.timestampSeconds || estimate.timestampSeconds - prior.timestampSeconds > 0.6)) {
            reset(); prior = null
        }
        fun compatible(old: LaneBoundary?, current: LaneBoundary?): Boolean =
            old != null && current != null && old.points.size == current.points.size &&
                old.points.zip(current.points).all { (a, b) -> abs(a.x - b.x) <= 0.065 && abs(a.y - b.y) <= 0.06 }
        fun smooth(old: LaneBoundary?, current: LaneBoundary?): LaneBoundary? {
            if (current == null || !compatible(old, current)) return current
            // Strong weight on the current frame limits lag while removing small fit jitter.
            return current.copy(points = old!!.points.zip(current.points).map { (a, b) -> LanePoint(a.x * 0.30 + b.x * 0.70, b.y) })
        }
        val pairMatches = prior != null && compatible(prior.left, estimate.left) && compatible(prior.right, estimate.right)
        consecutivePairs = if (estimate.hasReliablePair) { if (pairMatches) consecutivePairs + 1 else 1 } else 0
        val result = estimate.copy(
            left = smooth(prior?.left, estimate.left), right = smooth(prior?.right, estimate.right),
            state = if (estimate.hasReliablePair && consecutivePairs < 2) LaneDetectionState.UNCERTAIN else estimate.state,
        )
        previous = result
        return result
    }
}

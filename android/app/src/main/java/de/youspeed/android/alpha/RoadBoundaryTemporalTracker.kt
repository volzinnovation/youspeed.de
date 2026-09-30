package de.youspeed.android.alpha

import kotlin.math.*

/** Motion-supported image evidence; neither calibration nor an old curve creates fresh paint. */
data class RoadBoundaryPrediction internal constructor(
    val boundaries: List<RoadBoundaryEvidence>, val timestampSeconds: Double,
    val capturedAtSeconds: Double, val width: Int, val height: Int, val key: String,
    val operationCount: Int, val budgetExceeded: Boolean, val resetReason: String?,
    internal val acceptFrame: Boolean,
)

/** One raw-luma history frame; deterministic bounded patch search before the fresh scan. */
class RoadBoundaryTemporalTracker {
    private data class Previous(val gray: ByteArray, val width: Int, val height: Int, val time: Double,
        val key: String, val boundaries: List<RoadBoundaryEvidence>)
    private data class Match(val x: Int, val y: Int, val cost: Int)
    private data class Flow(val x: Int, val y: Int, val dx: Int, val dy: Int)
    private class Budget(val maximum: Int, val proceed: () -> Boolean) {
        var used = 0
        private var failed = false
        fun check(cost: Int = 1): Boolean {
            if (failed || cost > maximum-used || !proceed()) { failed=true; return false }
            used += cost
            return true
        }
    }
    private var previous: Previous? = null
    fun reset() { previous = null }

    fun predict(grayscale: ByteArray, width: Int, height: Int, timestampSeconds: Double, key: String,
        capturedAtSeconds: Double = timestampSeconds, maximumOperations: Int = 300_000,
        shouldContinue: () -> Boolean = { true }): RoadBoundaryPrediction {
        val budget = Budget(maximumOperations.coerceAtLeast(0),shouldContinue)
        fun empty(reason: String?, exceeded: Boolean = false, accept: Boolean = true, preserve: Boolean = false): RoadBoundaryPrediction {
            if (!preserve && (reason != null || exceeded)) reset()
            return RoadBoundaryPrediction(emptyList(),timestampSeconds,capturedAtSeconds,width,height,key,
                budget.used,exceeded,reason,accept)
        }
        if (width !in 64..384 || height !in 64..216 || grayscale.size != width*height ||
            !timestampSeconds.isFinite() || !capturedAtSeconds.isFinite()) return empty("invalid_input",accept=false)
        val old = previous
        if(old != null && old.key==key && old.width==width && old.height==height && timestampSeconds<=old.time)
            return empty(if(timestampSeconds==old.time) "duplicate_exposure" else "out_of_order_exposure",accept=false,preserve=true)
        if (!budget.check()) return empty("deadline",true)
        if (old == null) return empty(null)
        if (old.key != key || old.width != width || old.height != height) return empty("scope_or_geometry")
        val dt = timestampSeconds-old.time
        if (dt > 0.8) return empty("exposure_gap")
        val radius = ceil(dt*20).toInt().coerceIn(4,12)
        val tracked = ArrayList<RoadBoundaryEvidence>()
        for (boundary in old.boundaries.take(6)) {
            if (!budget.check()) return empty("deadline",true)
            val age = boundary.evidenceAgeSeconds+dt
            if (age > 0.8 || boundary.points.size < 4) continue
            val anchors = sample(boundary.points,8)
            val flows = ArrayList<Flow>()
            for (point in anchors) {
                val x = (point.x*(width-1)).roundToInt(); val y = (point.y*(height-1)).roundToInt()
                val forward = search(old.gray,grayscale,width,height,x,y,radius,budget) ?: continue
                val reverse = search(grayscale,old.gray,width,height,forward.x,forward.y,radius,budget) ?: continue
                if (abs(reverse.x-x)<=1 && abs(reverse.y-y)<=2) flows += Flow(x,y,forward.x-x,forward.y-y)
            }
            if (!budget.check()) return empty("deadline",true)
            if (flows.size < 4 || flows.size*5 < anchors.size*3) continue
            val medianX = flows.map { it.dx }.sorted()[flows.size/2]
            val medianY = flows.map { it.dy }.sorted()[flows.size/2]
            val coherent = flows.filter { abs(it.dx-medianX)<=4 && abs(it.dy-medianY)<=2 }.sortedBy { it.y }
            if (coherent.size < 4 || coherent.last().y-coherent.first().y < 0.12*(height-1)) continue
            val points = sample(boundary.points,12).filter {
                it.y*(height-1) >= coherent.first().y-1 && it.y*(height-1) <= coherent.last().y+1
            }.map { point ->
                val py = point.y*(height-1)
                val upper = coherent.indexOfFirst { it.y >= py }.let { if (it < 0) coherent.lastIndex else it }.coerceAtLeast(1)
                val a = coherent[upper-1]; val b = coherent[upper]
                val fraction = ((py-a.y)/max(1,b.y-a.y)).coerceIn(0.0,1.0)
                LanePoint((point.x+(a.dx+(b.dx-a.dx)*fraction)/(width-1)).coerceIn(0.0,1.0),
                    (point.y+(a.dy+(b.dy-a.dy)*fraction)/(height-1)).coerceIn(0.0,1.0))
            }
            if (points.size < 4 || !points.zipWithNext().all { (a,b)-> b.y>a.y }) continue
            val confidence = boundary.confidence*(1-dt/0.8)*coherent.size/anchors.size
            if (confidence < 0.12) continue
            tracked += boundary.copy(points=smooth(points,width),confidence=confidence,
                provenance=RoadBoundaryProvenance.TRACKED,evidenceAgeSeconds=age,trackedAnchorCount=coherent.size)
        }
        if (!budget.check()) return empty("deadline",true)
        return RoadBoundaryPrediction(tracked,timestampSeconds,capturedAtSeconds,width,height,key,budget.used,false,null,true)
    }

    /** Merge only after the same frame's fresh scan; carried curves never manufacture corridor pairs. */
    fun complete(prediction: RoadBoundaryPrediction, fresh: RoadBoundaryFrame, grayscale: ByteArray,
        shouldContinue: () -> Boolean = { true }): RoadBoundaryFrame {
        fun aborted(): RoadBoundaryFrame {
            reset()
            return RoadBoundaryFrame(emptyList(),emptyList(),prediction.capturedAtSeconds,true,fresh.operationCount,
                prediction.operationCount,"deadline")
        }
        if (!prediction.acceptFrame) return RoadBoundaryFrame(emptyList(),emptyList(),prediction.capturedAtSeconds,
            temporalOperationCount=prediction.operationCount,temporalResetReason=prediction.resetReason)
        if (prediction.budgetExceeded || fresh.budgetExceeded || !shouldContinue()) return aborted()
        if (grayscale.size != prediction.width*prediction.height || fresh.timestampSeconds != prediction.capturedAtSeconds) {
            reset(); return RoadBoundaryFrame(emptyList(),emptyList(),prediction.capturedAtSeconds,
                temporalOperationCount=prediction.operationCount,temporalResetReason=prediction.resetReason)
        }
        data class Entry(val original: Int?, val boundary: RoadBoundaryEvidence)
        val used = mutableSetOf<Int>(); val entries = ArrayList<Entry>()
        for ((index,observed) in fresh.boundaries.take(6).withIndex()) {
            if (!shouldContinue()) return aborted()
            val match = prediction.boundaries.indices.filter { it !in used && prediction.boundaries[it].cue==observed.cue }
                .minByOrNull { distance(observed.points,prediction.boundaries[it].points) }
                ?.takeIf { distance(observed.points,prediction.boundaries[it].points)<=0.035 }
            val current = sample(observed.points,12)
            val points = if (match != null) {
                used += match
                val prior = prediction.boundaries[match].points
                current.map { p -> LanePoint(p.x+((roadBoundaryXAt(prior,p.y)-p.x)*0.25)
                    .coerceIn(-2.0/(prediction.width-1),2.0/(prediction.width-1)),p.y) }
            } else current
            entries += Entry(index,observed.copy(points=smooth(points,prediction.width),
                provenance=if(match==null) RoadBoundaryProvenance.FRESH else RoadBoundaryProvenance.FUSED,
                lastFreshTimestampSeconds=prediction.capturedAtSeconds,evidenceAgeSeconds=0.0,
                trackedAnchorCount=match?.let { prediction.boundaries[it].trackedAnchorCount } ?: 0))
        }
        for ((index,carried) in prediction.boundaries.withIndex()) {
            if (!shouldContinue()) return aborted()
            if (index !in used && entries.none { distance(it.boundary.points,carried.points)<=0.035 }) entries += Entry(null,carried)
        }
        val selected = entries.sortedWith(compareByDescending<Entry> { it.boundary.confidence }
            .thenBy { it.boundary.points.last().x }).take(6).sortedBy { it.boundary.points.last().x }
        val corridors = fresh.corridors.mapNotNull { corridor ->
            val left = selected.indexOfFirst { it.original==corridor.leftBoundaryIndex }
            val right = selected.indexOfFirst { it.original==corridor.rightBoundaryIndex }
            if (left<0 || right!=left+1) null else RoadCorridorHypothesis(left,right,corridor.confidence)
        }.take(2)
        if (!shouldContinue()) return aborted()
        val boundaries = selected.map { it.boundary }
        previous = Previous(grayscale.copyOf(),prediction.width,prediction.height,prediction.timestampSeconds,prediction.key,boundaries)
        return RoadBoundaryFrame(boundaries,corridors,prediction.capturedAtSeconds,false,fresh.operationCount,
            prediction.operationCount,prediction.resetReason)
    }

    private fun search(source: ByteArray, target: ByteArray, width: Int, height: Int,
        x: Int, y: Int, radius: Int, budget: Budget): Match? {
        fun inside(px: Int, py: Int) = px in 2 until width-2 && py in 2 until height-2
        if (!inside(x,y)) return null
        var lo=255; var hi=0
        for (dy in -2..2) for (dx in -2..2) { val v=source[(y+dy)*width+x+dx].toInt() and 255; lo=min(lo,v);hi=max(hi,v) }
        if (hi-lo<24) return null
        fun cost(px: Int, py: Int): Int? {
            if (!inside(px,py) || !budget.check(25)) return null
            var sad=0
            for (dy in -2..2) for (dx in -2..2) sad += abs((source[(y+dy)*width+x+dx].toInt() and 255)-(target[(py+dy)*width+px+dx].toInt() and 255))
            return sad
        }
        var best: Match? = null
        fun consider(px: Int,py: Int) {
            val value=cost(px,py) ?: return
            val old=best
            if (old==null || value<old.cost || (value==old.cost && abs(px-x)+abs(py-y)<abs(old.x-x)+abs(old.y-y))) best=Match(px,py,value)
        }
        val offsets = ((-radius..radius step 2).toList()+0).distinct().sorted()
        for (dy in -2..2 step 2) for (dx in offsets) consider(x+dx,y+dy)
        val coarse=best ?: return null
        for (dy in -1..1) for (dx in -1..1) if(abs(coarse.x+dx-x)<=radius && abs(coarse.y+dy-y)<=2) consider(coarse.x+dx,coarse.y+dy)
        val result=best ?: return null
        if (result.cost>18*25) return null
        val alternate=listOfNotNull(cost(result.x-3,result.y),cost(result.x+3,result.y)).minOrNull()
        if (alternate!=null && alternate-result.cost<30) return null
        return result
    }
    private fun sample(points: List<LanePoint>, maximum: Int): List<LanePoint> =
        if(points.size<=maximum) points else (0 until maximum).map { points[it*(points.size-1)/(maximum-1)] }
    private fun smooth(points: List<LanePoint>,width: Int): List<LanePoint> = points.mapIndexed { i,p ->
        if(i==0 || i==points.lastIndex) p else LanePoint(p.x+((points[i-1].x+2*p.x+points[i+1].x)/4-p.x)
            .coerceIn(-1.5/(width-1),1.5/(width-1)),p.y)
    }
    private fun distance(a: List<LanePoint>,b: List<LanePoint>): Double {
        if(a.size<2 || b.size<2) return Double.POSITIVE_INFINITY
        val top=max(a.first().y,b.first().y);val bottom=min(a.last().y,b.last().y)
        if(bottom-top<0.10) return Double.POSITIVE_INFINITY
        return (0..4).sumOf { val y=top+(bottom-top)*it/4; abs(roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y)) }/5
    }
}

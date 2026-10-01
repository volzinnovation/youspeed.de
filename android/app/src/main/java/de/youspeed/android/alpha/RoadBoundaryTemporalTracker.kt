package de.youspeed.android.alpha

import kotlin.math.*

/** Motion-supported image evidence; neither calibration nor an old curve creates fresh paint. */
data class RoadBoundaryPrediction internal constructor(
    val boundaries: List<RoadBoundaryEvidence>, val timestampSeconds: Double,
    val capturedAtSeconds: Double, val width: Int, val height: Int, val key: String,
    val operationCount: Int, val budgetExceeded: Boolean, val resetReason: String?,
    internal val acceptFrame: Boolean,
    val fragmentAware: Boolean = false,
)

/** One raw-luma history frame; deterministic bounded patch search before the fresh scan. */
class RoadBoundaryTemporalTracker {
    private data class Previous(val gray: ByteArray, val width: Int, val height: Int, val time: Double,
        val key: String, val boundaries: List<RoadBoundaryEvidence>)
    private data class Match(val x: Int, val y: Int, val cost: Int)
    private data class Flow(val x: Int, val y: Int, val dx: Int, val dy: Int, val residualX: Int, val residualY: Int)
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
        motionHint: RoadBoundaryMotionHint? = null, motionProjection: RoadBoundaryMotionProjection? = null, fragmentAware: Boolean = false,
        shouldContinue: () -> Boolean = { true }): RoadBoundaryPrediction {
        val budget = Budget(maximumOperations.coerceAtLeast(0),shouldContinue)
        fun empty(reason: String?, exceeded: Boolean = false, accept: Boolean = true, preserve: Boolean = false): RoadBoundaryPrediction {
            if (!preserve && (reason != null || exceeded)) reset()
            return RoadBoundaryPrediction(emptyList(),timestampSeconds,capturedAtSeconds,width,height,key,
                budget.used,exceeded,reason,accept,fragmentAware)
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
        val radius = max(ceil(dt*20).toInt().coerceIn(4,12),
            if (motionHint?.used == true) motionHint.horizontalSearchRadiusFloor.coerceIn(0,12) else 0)
        val tracked = ArrayList<RoadBoundaryEvidence>()
        for (boundary in old.boundaries.take(6)) {
            if (!budget.check()) return empty("deadline",true)
            val age = boundary.evidenceAgeSeconds+dt
            if (age > 0.8 || boundary.points.size < (if(fragmentAware) 2 else 4)) continue
            val segments=boundary.observedSegments.ifEmpty { listOf(boundary.points) }
            val anchors=if(fragmentAware) paintAnchors(segments) else sample(boundary.points,8)
            val flows = ArrayList<Flow>()
            for (point in anchors) {
                val x = (point.x*(width-1)).roundToInt(); val y = (point.y*(height-1)).roundToInt()
                val predicted = if(motionProjection != null) motionProjection.project(point,dt) ?: continue else point
                val px=(predicted.x*(width-1)).roundToInt(); val py=(predicted.y*(height-1)).roundToInt()
                val uncertainty=if(fragmentAware) motionProjection?.searchUncertaintyPixels(point,dt,width,height) else null
                val searchRadius=max(radius,uncertainty?.first ?: 0)
                val vertical=max(if(motionProjection!=null) 4 else 2,uncertainty?.second ?: 0)
                val forward = search(old.gray,grayscale,width,height,x,y,searchRadius,budget,px,py,vertical,if(fragmentAware) 3 else 1) ?: continue
                val reverse = search(grayscale,old.gray,width,height,forward.x,forward.y,searchRadius,budget,
                    if(motionProjection!=null || fragmentAware) x else forward.x,if(motionProjection!=null || fragmentAware) y else forward.y,vertical,if(fragmentAware) 3 else 1) ?: continue
                if (abs(reverse.x-x)<=1 && abs(reverse.y-y)<=2)
                    flows += Flow(x,y,forward.x-x,forward.y-y,forward.x-px,forward.y-py)
            }
            if (!budget.check()) return empty("deadline",true)
            if (flows.size < 4 || flows.size*5 < anchors.size*3) continue
            val medianX = flows.map { it.residualX }.sorted()[flows.size/2]
            val medianY = flows.map { it.residualY }.sorted()[flows.size/2]
            val coherent = flows.filter { abs(it.residualX-medianX)<=4 && abs(it.residualY-medianY)<=2 }.sortedBy { it.y }
            if (coherent.size < 4 || coherent.last().y-coherent.first().y < (if(fragmentAware) .06 else .12)*(height-1)) continue
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
            if (points.size < (if(fragmentAware) 2 else 4) || !points.zipWithNext().all { (a,b)-> b.y>a.y }) continue
            val confidence = boundary.confidence*(1-dt/0.8)*coherent.size/anchors.size
            if (confidence < 0.12) continue
            // Keep confirmed patch support separate from the interpolated model across gaps.
            val carriedSegments=if(fragmentAware) segments.mapNotNull { segment ->
                if(segment.isEmpty()) return@mapNotNull null
                val matched=coherent.filter { it.y >= segment.first().y*(height-1)-1 && it.y <= segment.last().y*(height-1)+1 }
                    .map { LanePoint((it.x+it.dx).toDouble()/(width-1),(it.y+it.dy).toDouble()/(height-1)) }
                matched.takeIf { it.size>=2 && it.zipWithNext().all { (a,b) -> b.y>a.y } }
            } else emptyList()
            if(fragmentAware && carriedSegments.isEmpty()) continue
            tracked += boundary.copy(points=smooth(points,width),confidence=confidence,
                provenance=RoadBoundaryProvenance.TRACKED,evidenceAgeSeconds=age,trackedAnchorCount=coherent.size,observedSegments=carriedSegments)
        }
        if (!budget.check()) return empty("deadline",true)
        return RoadBoundaryPrediction(tracked,timestampSeconds,capturedAtSeconds,width,height,key,budget.used,false,null,true,fragmentAware)
    }

    /** Merge only after the same frame's fresh scan; carried curves never manufacture corridor pairs. */
    fun complete(prediction: RoadBoundaryPrediction, fresh: RoadBoundaryFrame, grayscale: ByteArray,
        shouldContinue: () -> Boolean = { true }): RoadBoundaryFrame {
        fun aborted(): RoadBoundaryFrame {
            reset()
            return RoadBoundaryFrame(emptyList(),emptyList(),prediction.capturedAtSeconds,true,fresh.operationCount,
                prediction.operationCount,"deadline",rejectionCounts=fresh.rejectionCounts,detectionVariant=fresh.detectionVariant)
        }
        if (!prediction.acceptFrame) return RoadBoundaryFrame(emptyList(),emptyList(),prediction.capturedAtSeconds,
            temporalOperationCount=prediction.operationCount,temporalResetReason=prediction.resetReason,rejectionCounts=fresh.rejectionCounts,detectionVariant=fresh.detectionVariant)
        if (prediction.budgetExceeded || fresh.budgetExceeded || !shouldContinue()) return aborted()
        if (grayscale.size != prediction.width*prediction.height || fresh.timestampSeconds != prediction.capturedAtSeconds) {
            reset(); return RoadBoundaryFrame(emptyList(),emptyList(),prediction.capturedAtSeconds,
                temporalOperationCount=prediction.operationCount,temporalResetReason=prediction.resetReason,rejectionCounts=fresh.rejectionCounts,detectionVariant=fresh.detectionVariant)
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
                current.map { p -> LanePoint(p.x+((roadBoundaryXAt(prior,p.y)-p.x)*.25)
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
            prediction.operationCount,prediction.resetReason,rejectionCounts=fresh.rejectionCounts,detectionVariant=fresh.detectionVariant)
    }

    private fun search(source: ByteArray, target: ByteArray, width: Int, height: Int,
        x: Int, y: Int, radius: Int, budget: Budget, centerX: Int = x, centerY: Int = y, vertical: Int = 2, refineCandidates: Int = 1): Match? {
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
        val coarseMatches=mutableListOf<Match>()
        fun consider(px: Int,py: Int,recordCoarse:Boolean=false) {
            val value=cost(px,py) ?: return
            if(recordCoarse) coarseMatches.add(Match(px,py,value))
            val old=best
            if (old==null || value<old.cost || (value==old.cost && abs(px-x)+abs(py-y)<abs(old.x-x)+abs(old.y-y))) best=Match(px,py,value)
        }
        val offsets = ((-radius..radius step 2).toList()+0).distinct().sorted()
        for (dy in -vertical..vertical step 2) for (dx in offsets) consider(centerX+dx,centerY+dy,refineCandidates>1)
        val coarse=best ?: return null
        // Three bounded refinements avoid endpoint aliasing without weakening image checks.
        val candidates=if(refineCandidates>1) coarseMatches.sortedWith(compareBy<Match> { it.cost }
            .thenBy { abs(it.x-x)+abs(it.y-y) }.thenBy { it.y }.thenBy { it.x }).take(3) else listOf(coarse)
        for(candidate in candidates) for(dy in -1..1) for(dx in -1..1)
            if(abs(candidate.x+dx-centerX)<=radius && abs(candidate.y+dy-centerY)<=vertical) consider(candidate.x+dx,candidate.y+dy)
        val result=best ?: return null
        if (result.cost>18*25) return null
        val alternate=listOfNotNull(cost(result.x-3,result.y),cost(result.x+3,result.y)).minOrNull()
        if (alternate!=null && alternate-result.cost<30) return null
        return result
    }
    /** Eight real paint anchors at most: endpoints first, then interiors, never fitted gaps. */
    private fun paintAnchors(segments: List<List<LanePoint>>): List<LanePoint> {
        val valid=segments.filter { it.size>=2 && it.last().y>it.first().y }
        val chosen=if(valid.size<=4) valid else (0..<4).map { valid[it*(valid.size-1)/3] }
        val points=mutableListOf<LanePoint>()
        fun add(p:LanePoint) { if(points.size<8 && points.none { abs(it.x-p.x)<1e-9 && abs(it.y-p.y)<1e-9 }) points.add(p) }
        for(segment in chosen) { add(segment.first()); add(segment.last()) }
        for(fraction in listOf(.5,.25,.75,.125,.875,.375)) for(segment in chosen) {
            val y=segment.first().y+(segment.last().y-segment.first().y)*fraction
            add(LanePoint(roadBoundaryXAt(segment,y),y))
        }
        return points.sortedBy { it.y }
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

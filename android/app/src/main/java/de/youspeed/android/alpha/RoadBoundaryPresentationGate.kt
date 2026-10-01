package de.youspeed.android.alpha

import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.pow
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** Display maturity only. This selection never changes detector, corridor or sign evidence. */
data class RoadBoundaryPresentationItem(val trackId: Long, val boundaryIndex: Int?, val state: String,
    val observationCount: Int, val firstObservedSeconds: Double?, val lastObservedSeconds: Double, val missedExposures: Int)
data class RoadBoundarySelectionDecision(val boundaryIndex: Int, var side: String = "none", var reason: String = "not_mature",
    var score: Double? = null, var anchorY: Double? = null, var centerX: Double? = null,
    var corridorReason: String? = null, var metricWidthMeters: Double? = null) {
    val diagnosticFields get() = mapOf("boundaryIndex" to boundaryIndex,"side" to side,"reason" to reason,
        "score" to score,"anchorY" to anchorY,"centerX" to centerX,"corridorReason" to corridorReason,"metricWidthMeters" to metricWidthMeters)
}
data class RoadBoundaryPresentationSnapshot(val accepted: Boolean, val reason: String?,
    val visibleBoundaryIndices: List<Int>, val items: List<RoadBoundaryPresentationItem>, val rawCount: Int,
    val operationCount: Int = 0, val selectionDecisions: List<RoadBoundarySelectionDecision> = emptyList(),
    val expiredTrackIds: List<Long> = emptyList()) {
    /** Reject inconsistent selections as a whole; diagnostics must never crash the app. */
    fun selectedBoundaries(boundaries: List<RoadBoundaryEvidence>): List<RoadBoundaryEvidence> =
        if (accepted && visibleBoundaryIndices.all { it in boundaries.indices }) visibleBoundaryIndices.map { boundaries[it] }
        else emptyList()
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

    fun update(boundaries: List<RoadBoundaryEvidence>, exposureSeconds: Double, key: String, retainMissingByTime: Boolean = false, fragmentAware: Boolean = false, retainTentativeIdentity: Boolean = false,
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
        val expired = if (retainTentativeIdentity && scope==key) tracks.filter { exposureSeconds-it.lastObserved>.75 }.map { it.id } else emptyList()
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
            val distance = distance(a.boundary.points,b.second.points,fragmentAware)
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
            if (retainTentativeIdentity && !observed) {
                // A prediction can relocate an identity, but cannot observe paint or extend its life.
                if (old != null) {
                    updated += old.copy(boundary=entry.second,misses=old.misses+1)
                    items += RoadBoundaryPresentationItem(old.id,null,"missing",old.observations,old.firstObserved,old.lastObserved,old.misses+1)
                }
                continue
            }
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
            if (index !in priorUsed && (old.confirmed || retainTentativeIdentity) && (retainMissingByTime || retainTentativeIdentity || old.misses == 0) && exposureSeconds-old.lastObserved <= .75) {
                val missing = old.copy(misses=old.misses+1); updated += missing
                items += RoadBoundaryPresentationItem(old.id,null,"missing",old.observations,old.firstObserved,old.lastObserved,old.misses+1)
            }
        }
        if (!check()) return aborted()
        tracks = updated.take(12); scope = key; lastTime = exposureSeconds; nextId = serial
        return RoadBoundaryPresentationSnapshot(true,resetReason,visible,items,rawCount,operations,expiredTrackIds=expired)
    }

    private fun distance(a: List<LanePoint>, b: List<LanePoint>, fragmentAware: Boolean): Double? {
        val top = max(a.first().y,b.first().y); val bottom = min(a.last().y,b.last().y)
        if (bottom-top < (if(fragmentAware) .04 else .12)) return null
        val deltas = (0..4).map { i -> val y = top+(bottom-top)*i/4.0; roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y) }
        val mean = deltas.sumOf { abs(it) }/5
        val signedMean = deltas.sum()/5
        return mean.takeIf { it <= .045 && deltas.all { d -> abs(d) <= .07 && abs(d-signedMean) <= .025 } }
    }
}

/** Preview geometry only. Lane count never supplies a lane index or metric width. */
data class RoadBoundaryEgoContext(
    val calibration: RoadPathCalibration? = null,
    val speedMetersPerSecond: Double? = null,
    val headingRateDegreesPerSecond: Double? = null,
    val directionalLaneCount: Int? = null,
    val roadContextConfidence: Double = 0.0
) {
    private val validCalibration: RoadPathCalibration? get() {
        val c=calibration ?: return null
        val offset=c.lateralOffsetMeters ?: return null
        return c.takeIf { c.verified && listOf(c.fx,c.fy,c.cx,c.cy,c.pitchDegrees,c.rollDegrees,c.yawDegrees,c.heightMeters).all { it.isFinite() } &&
            c.fx in .1..10.0 && c.fy in .1..10.0 && c.cx in 0.0..1.0 && c.cy in 0.0..1.0 &&
            abs(c.pitchDegrees)<=15 && abs(c.rollDegrees)<=15 && abs(c.yawDegrees)<=15 && c.heightMeters in .3..4.0 && offset.isFinite() && abs(offset)<=2 }
    }
    fun ground(point: LanePoint, visual: VisualRoadCalibration?): LanePoint? {
        val c=validCalibration ?: return null
        val pitch=visual?.takeIf { it.isValid }?.let { atan((c.cy-it.horizonY)/c.fy) } ?: (c.pitchDegrees*Math.PI/180)
        val roll=c.rollDegrees*Math.PI/180; val yaw=c.yawDegrees*Math.PI/180
        val u=(point.x-c.cx)/c.fx; val v=(point.y-c.cy)/c.fy
        val rx=cos(roll)*u-sin(roll)*v; val ry=sin(roll)*u+cos(roll)*v
        val down=cos(pitch)*ry+sin(pitch); val forward= -sin(pitch)*ry+cos(pitch)
        if(down<=.02) return null
        val z=(-sin(yaw)*rx+cos(yaw)*forward)*c.heightMeters/down
        val x=(cos(yaw)*rx+sin(yaw)*forward)*c.heightMeters/down+c.lateralOffsetMeters!!
        return LanePoint(x,z).takeIf { x.isFinite() && z in 2.0..80.0 }
    }
    private fun pathX(z: Double): Double {
        val speed=speedMetersPerSecond ?: return 0.0; val rate=headingRateDegreesPerSecond ?: return 0.0
        if(!speed.isFinite() || !rate.isFinite() || speed !in 3.0..60.0 || abs(rate)>15) return 0.0
        // Constant-curvature is a weak short-range trajectory prior, never observed paint.
        val curvature=rate*Math.PI/180/speed
        return max(-2.0,min(2.0,.5*curvature*min(z,25.0).pow(2)))
    }
    fun centerX(row: Double, visual: VisualRoadCalibration?): Double? {
        if(validCalibration==null) return null
        var low=0.0; var high=1.0
        val a=ground(LanePoint(low,row),visual) ?: return null; val b=ground(LanePoint(high,row),visual) ?: return null
        if(a.x-pathX(a.y)>=0 || b.x-pathX(b.y)<=0) return null
        repeat(12) {
            val middle=(low+high)/2
            val p=ground(LanePoint(middle,row),visual) ?: return null
            if(p.x<pathX(p.y)) low=middle else high=middle
        }
        return (low+high)/2
    }
    val multiLaneEdgePenalty: Double get() {
        val count=directionalLaneCount ?: return 0.0
        if(count !in 2..8 || !roadContextConfidence.isFinite() || roadContextConfidence !in .6..1.0) return 0.0
        return .06*roadContextConfidence
    }
}

/** Preview-only ego corridor selection; current image coordinates only, never a held curve. */
class RoadBoundaryEgoSelector {
    private data class Side(var points: List<LanePoint> = emptyList(), var id: Long? = null, var lastSeen: Double = Double.NEGATIVE_INFINITY,
        var challenger: Long? = null, var challengedAt: Double = 0.0)
    private data class Candidate(val index: Int, val id: Long, val score: Double, val points: List<LanePoint>)
    private var left=Side(); private var right=Side()
    private var scope: String?=null; private var lastTime=Double.NEGATIVE_INFINITY
    private var jointChallenger: String?=null; private var jointChallengedAt=0.0
    fun reset() { left=Side(); right=Side(); scope=null; lastTime=Double.NEGATIVE_INFINITY; jointChallenger=null }
    fun select(snapshot: RoadBoundaryPresentationSnapshot, boundaries: List<RoadBoundaryEvidence>, visual: VisualRoadCalibration?,
        time: Double, key: String, fragmentAware: Boolean = false, jointSelection: Boolean = false, egoContext: RoadBoundaryEgoContext? = null): RoadBoundaryPresentationSnapshot {
        if(!snapshot.accepted || !time.isFinite()) { reset(); return snapshot }
        if(scope!=key || time<=lastTime || time-lastTime>.75) reset()
        scope=key; lastTime=time
        val y=min(.83,max(.78,(visual?.horizonY ?: .50)+.20))
        fun center(row: Double): Double {
            val v=visual ?: return if(jointSelection) egoContext?.centerX(row,null) ?: .5 else .5
            return (roadBoundaryXAt(listOf(LanePoint(v.leftTopX,v.horizonY),v.leftBottom),row)+
                roadBoundaryXAt(listOf(LanePoint(v.rightTopX,v.horizonY),v.rightBottom),row))/2
        }
        val decisions=boundaries.indices.map { RoadBoundarySelectionDecision(it) }
        val l=arrayListOf<Candidate>(); val r=arrayListOf<Candidate>()
        for (index in snapshot.visibleBoundaryIndices.take(6)) {
            val b=boundaries.getOrNull(index) ?: continue
            val id=snapshot.items.firstOrNull { it.boundaryIndex==index }?.trackId ?: continue
            val top=b.points.firstOrNull(); val bottom=b.points.lastOrNull()
            if(top==null || bottom==null) { decisions[index].reason="empty_geometry"; continue }
            if((fragmentAware || jointSelection) && b.provenance==RoadBoundaryProvenance.TRACKED) { decisions[index].reason="tracked_only"; continue }
            if(b.confidence<.25) { decisions[index].reason="confidence"; continue }
            if(b.supportRows<4) { decisions[index].reason="support_rows"; continue }
            if(bottom.y-top.y < (if(fragmentAware) .06 else .12)) { decisions[index].reason="vertical_span"; continue }
            val anchor=if(fragmentAware) min(bottom.y,max(top.y,y)) else y
            if(!fragmentAware && (top.y>y || bottom.y<y)) { decisions[index].reason="lower_anchor_missing"; continue }
            val cx=center(anchor); val delta=roadBoundaryXAt(b.points,anchor)-cx
            decisions[index].anchorY=anchor; decisions[index].centerX=cx
            decisions[index].side=if(delta<0) "left" else "right"
            if(abs(delta)<(if(fragmentAware) .015 else .025)) { decisions[index].reason="center_exclusion"; continue }
            if(abs(delta)>.45) { decisions[index].reason="lateral_distance"; continue }
            val score=b.confidence+min(.2,(bottom.y-top.y)*.4)+(if(b.cue==RoadBoundaryCue.PAINT) .12 else 0.0)-abs(delta)*.6-
                (if(jointSelection && b.cue==RoadBoundaryCue.EDGE) .20+(egoContext?.multiLaneEdgePenalty ?: 0.0) else 0.0)
            decisions[index].score=score; decisions[index].reason="candidate"
            val candidate=Candidate(index,id,score,b.points)
            if(delta<0) l+=candidate else r+=candidate
        }
        val initial=if(jointSelection) chooseJoint(l,r,boundaries,visual,egoContext,fragmentAware,time,::center,decisions) else choose(l,left,time) to choose(r,right,time)
        var a=initial.first; var b=initial.second
        val x=a; val z=b
        if(x!=null && z!=null) {
            val top=max(if(fragmentAware) 0.0 else y,max(x.points.first().y,z.points.first().y)); val bottom=min(x.points.last().y,z.points.last().y)
            val jointQuality=if(jointSelection) pairQuality(x,z,boundaries,visual,egoContext,fragmentAware,::center) else null
            val valid=jointQuality?.valid ?: (bottom-top >= (if(fragmentAware) .04 else .06) && (0..4).all { i ->
                val row=top+(bottom-top)*i/4
                val lx=roadBoundaryXAt(x.points,row); val rx=roadBoundaryXAt(z.points,row)
                rx-lx>=.035 && rx-lx<=.90 && lx<center(row)+.02 && rx>center(row)-.02
            })
            if(!valid) {
                if(x.score>=z.score) { decisions[z.index].reason="pair_geometry"; decisions[z.index].corridorReason=jointQuality?.reason; b=null }
                else { decisions[x.index].reason="pair_geometry"; decisions[x.index].corridorReason=jointQuality?.reason; a=null }
            }
        }
        for((candidates,chosen) in listOf(l to a,r to b)) for(c in candidates) if(decisions[c.index].reason!="pair_geometry") {
            decisions[c.index].reason=when {
                chosen?.index==c.index -> "selected"
                chosen==null -> "incumbent_reacquisition_hold"
                c.score>chosen.score -> "challenger_margin_or_dwell"
                else -> "lower_side_score"
            }
        }
        return snapshot.copy(visibleBoundaryIndices=listOfNotNull(a?.index,b?.index),selectionDecisions=decisions)
    }
    private data class PairQuality(val reason: String,val adjustment: Double,val metricWidth: Double? = null) { val valid get() = reason=="consistent_corridor" }
    private data class JointPair(val left: Candidate,val right: Candidate,val score: Double)
    private fun pairQuality(a: Candidate,b: Candidate,boundaries: List<RoadBoundaryEvidence>,visual: VisualRoadCalibration?,
        context: RoadBoundaryEgoContext?,fragmentAware: Boolean,center: (Double)->Double): PairQuality {
        val top=max(a.points.first().y,b.points.first().y); val bottom=min(a.points.last().y,b.points.last().y)
        if(bottom-top < (if(fragmentAware) .04 else .06)) return PairQuality("no_common_support",0.0)
        val rows=(0..4).map { top+(bottom-top)*it/4.0 }
        val widths=rows.map { roadBoundaryXAt(b.points,it)-roadBoundaryXAt(a.points,it) }
        if(widths.any { it !in .035.. .90 }) return PairQuality("crossing_or_image_width",0.0)
        // Far paint may bend away from the vehicle axis. Containment is checked in the near half.
        if(rows.takeLast(3).any { roadBoundaryXAt(a.points,it)>=center(it)+.02 || roadBoundaryXAt(b.points,it)<=center(it)-.02 })
            return PairQuality("vehicle_outside_corridor",0.0)
        val mean=widths.sum()/5
        if((1..3).any { abs(widths[it+1]-2*widths[it]+widths[it-1])>max(.025,mean*.25) }) return PairQuality("inconsistent_curvature",0.0)
        var penalty=0.0; var metricWidth: Double?=null
        if(visual!=null) {
            val ratios=rows.mapNotNull { row ->
                val expected=roadBoundaryXAt(listOf(LanePoint(visual.rightTopX,visual.horizonY),visual.rightBottom),row)-roadBoundaryXAt(listOf(LanePoint(visual.leftTopX,visual.horizonY),visual.leftBottom),row)
                if(expected>=.06) (roadBoundaryXAt(b.points,row)-roadBoundaryXAt(a.points,row))/expected else null
            }
            if(ratios.isNotEmpty()) penalty+=min(.25,ratios.sumOf { abs(it-1) }/ratios.size*.20)
        }
        if(context!=null) {
            val ag=a.points.mapNotNull { context.ground(it,visual) }.sortedBy { it.y }
            val bg=b.points.mapNotNull { context.ground(it,visual) }.sortedBy { it.y }
            if(ag.isNotEmpty() && bg.isNotEmpty()) {
                val near=max(2.0,max(ag.first().y,bg.first().y)); val far=min(35.0,min(ag.last().y,bg.last().y))
                if(far-near>=2) {
                    val metric=(0..4).map { i ->
                        val z=near+(far-near)*i/4.0
                        roadBoundaryXAt(bg,z)-roadBoundaryXAt(ag,z)
                    }
                    val width=metric.sum()/5; metricWidth=width
                    // A failed metric pair may still leave one supported painted border visible.
                    if(metric.any { it !in 2.0..6.0 }) return PairQuality("metric_width",0.0,width)
                    if(metric.max()-metric.min()>max(1.5,width*.4)) return PairQuality("metric_width_change",0.0,width)
                    penalty+=min(.25,abs(width-3.5)*.10)
                }
            }
        }
        val paintCount=listOf(a,b).count { boundaries[it.index].cue==RoadBoundaryCue.PAINT }
        return PairQuality("consistent_corridor",.20+paintCount*.08-penalty,metricWidth)
    }
    private fun chooseJoint(l: List<Candidate>,r: List<Candidate>,boundaries: List<RoadBoundaryEvidence>,visual: VisualRoadCalibration?,
        context: RoadBoundaryEgoContext?,fragmentAware: Boolean,time: Double,center: (Double)->Double,
        decisions: List<RoadBoundarySelectionDecision>): Pair<Candidate?,Candidate?> {
        val pairs=arrayListOf<JointPair>()
        for(a in l) for(b in r) {
            val quality=pairQuality(a,b,boundaries,visual,context,fragmentAware,center)
            for(c in listOf(a,b)) if(decisions[c.index].corridorReason!="consistent_corridor") {
                decisions[c.index].corridorReason=quality.reason; decisions[c.index].metricWidthMeters=quality.metricWidth
            }
            if(quality.valid) pairs+=JointPair(a,b,a.score+b.score+quality.adjustment)
        }
        pairs.sortWith(compareByDescending<JointPair> { it.score }.thenBy { it.left.id }.thenBy { it.right.id })
        var best=pairs.firstOrNull()
        if(best==null) { jointChallenger=null; return choose(l,left,time) to choose(r,right,time) }
        val current=pairs.firstOrNull { it.left.id==left.id && it.right.id==right.id }
        if(current!=null) {
            if(best.left.id==current.left.id && best.right.id==current.right.id || best.score<current.score+.25) { best=current; jointChallenger=null }
            else {
                val challenger="${best.left.id}:${best.right.id}"
                if(jointChallenger!=challenger) { jointChallenger=challenger; jointChallengedAt=time }
                if(time-jointChallengedAt<.35) best=current else jointChallenger=null
            }
            left=Side(best.left.points,best.left.id,time); right=Side(best.right.points,best.right.id,time)
            return best.left to best.right
        }
        // An absent incumbent may delay replacement, but its old points are never output.
        jointChallenger=null
        return choose(listOf(best.left),left,time) to choose(listOf(best.right),right,time)
    }
    private fun choose(candidates: List<Candidate>, side: Side, time: Double): Candidate? {
        val sorted=candidates.sortedWith(compareByDescending<Candidate>{it.score}.thenBy{it.id})
        val best=sorted.firstOrNull()
        if(best==null) {
            side.challenger=null
            if(time-side.lastSeen>.75) { side.id=null; side.lastSeen=Double.NEGATIVE_INFINITY }
            return null
        }
        val current=sorted.firstOrNull{it.id==side.id}
        if(current!=null) {
            side.lastSeen=time; side.points=current.points
            if(best.id==current.id || best.score<current.score+.15) { side.challenger=null; return current }
            if(side.challenger!=best.id) { side.challenger=best.id; side.challengedAt=time }
            if(time-side.challengedAt<.35) return current
        } else if(side.id!=null && time-side.lastSeen<=.35 && !near(best.points,side.points)) return null
        side.id=best.id; side.points=best.points; side.lastSeen=time; side.challenger=null
        return best
    }
    private fun near(a: List<LanePoint>, b: List<LanePoint>): Boolean {
        if(a.isEmpty() || b.isEmpty()) return false
        val top=max(a.first().y,b.first().y); val bottom=min(a.last().y,b.last().y)
        return bottom-top>=.12 && (0..4).all { i ->
            val y=top+(bottom-top)*i/4
            abs(roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y))<=.055
        }
    }
}

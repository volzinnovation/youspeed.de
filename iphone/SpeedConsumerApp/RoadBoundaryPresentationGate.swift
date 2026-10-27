import Foundation

/// Display maturity only. This selection never changes detector, corridor or sign evidence.
struct RoadBoundaryPresentationItem {
    let trackId: Int64
    let boundaryIndex: Int?
    let state: String
    let observationCount: Int
    let firstObservedSeconds: Double?
    let lastObservedSeconds: Double
    let missedExposures: Int
}
struct RoadBoundarySelectionDecision {
    let boundaryIndex: Int
    var side: String = "none"
    var reason: String = "not_mature"
    var score: Double? = nil
    var anchorY: Double? = nil
    var centerX: Double? = nil
    var corridorReason: String? = nil
    var metricWidthMeters: Double? = nil
    var diagnosticFields: [String:Any] { ["boundaryIndex":boundaryIndex,"side":side,"reason":reason,
        "score":score as Any? ?? NSNull(),"anchorY":anchorY as Any? ?? NSNull(),"centerX":centerX as Any? ?? NSNull(),
        "corridorReason":corridorReason as Any? ?? NSNull(),"metricWidthMeters":metricWidthMeters as Any? ?? NSNull()] }
}
struct RoadBoundaryPresentationSnapshot {
    let accepted: Bool
    let reason: String?
    let visibleBoundaryIndices: [Int]
    let items: [RoadBoundaryPresentationItem]
    let rawCount: Int
    var operationCount = 0
    var selectionDecisions: [RoadBoundarySelectionDecision] = []
    var expiredTrackIds: [Int64] = []
    /// A rejected or inconsistent selection must never index a different geometry snapshot.
    func selectedBoundaries(from boundaries: [RoadBoundaryEvidence]) -> [RoadBoundaryEvidence] {
        guard accepted, visibleBoundaryIndices.allSatisfy({ boundaries.indices.contains($0) }) else { return [] }
        return visibleBoundaryIndices.map { boundaries[$0] }
    }
    var confirmedCount: Int { items.filter { $0.state == "confirmed" }.count }
    var tentativeCount: Int { items.filter { $0.state == "tentative" }.count }
    var missingCount: Int { items.filter { $0.state == "missing" }.count }
    static func rejected(_ reason: String, rawCount: Int = 0) -> Self {
        Self(accepted:false,reason:reason,visibleBoundaryIndices:[],items:[],rawCount:rawCount)
    }
    var diagnosticFields: [String:Any] {
        ["accepted":accepted,"reason":reason as Any? ?? NSNull(),"rawCount":rawCount,
         "visibleCount":visibleBoundaryIndices.count,"confirmedCount":confirmedCount,"tentativeCount":tentativeCount,
         "missingCount":missingCount,"operationCount":operationCount,"visibleBoundaryIndices":visibleBoundaryIndices,
         "selectionDecisions":selectionDecisions.map(\.diagnosticFields),"expiredTrackIds":expiredTrackIds,
         "items":items.map { ["trackId":$0.trackId,"boundaryIndex":$0.boundaryIndex as Any? ?? NSNull(),"state":$0.state,
             "observationCount":$0.observationCount,"firstObservedSeconds":$0.firstObservedSeconds as Any? ?? NSNull(),
             "lastObservedSeconds":$0.lastObservedSeconds,"missedExposures":$0.missedExposures] }]
    }
}

/// At most six current curves and six short-lived identities. Missing points are never rendered.
final class RoadBoundaryPresentationGate {
    private struct Track {
        let id: Int64
        let boundary: RoadBoundaryEvidence
        let firstObserved: Double?
        let lastObserved: Double
        let observations: Int
        let confirmed: Bool
        var misses: Int
    }
    private var tracks: [Track] = []
    private var scope: String?
    private var lastTime = -Double.infinity
    private var nextId: Int64 = 1
    func reset() { tracks=[]; scope=nil; lastTime = -Double.infinity }

    func update(boundaries: [RoadBoundaryEvidence], exposureSeconds: Double, key: String, retainMissingByTime: Bool = false, fragmentAware: Bool = false, retainTentativeIdentity: Bool = false,
                shouldContinue: () -> Bool = { true }) -> RoadBoundaryPresentationSnapshot {
        let rawCount=boundaries.count
        guard exposureSeconds.isFinite else { return .rejected("invalid_timestamp",rawCount:rawCount) }
        if scope==key && exposureSeconds<=lastTime {
            return .rejected(exposureSeconds==lastTime ? "duplicate_exposure" : "out_of_order_exposure",rawCount:rawCount)
        }
        var operations=0
        func check(_ cost: Int = 1) -> Bool { operations += cost; return operations<=20_000 && shouldContinue() }
        func aborted() -> RoadBoundaryPresentationSnapshot { reset(); return .rejected("presentation_budget",rawCount:rawCount) }
        guard check() else { return aborted() }
        let resetReason: String? = scope != nil && scope != key ? "scope_or_geometry" :
            exposureSeconds-lastTime > 0.75 && !tracks.isEmpty ? "exposure_gap" : nil
        let expired = retainTentativeIdentity && scope==key ? tracks.filter { exposureSeconds-$0.lastObserved>0.75 }.map(\.id) : []
        let prior = scope==key && exposureSeconds-lastTime<=0.75 ? tracks.filter { exposureSeconds-$0.lastObserved<=0.75 } : []
        var current: [(Int,RoadBoundaryEvidence)] = []
        for (index,b) in boundaries.prefix(6).enumerated() {
            guard check(min(33,b.points.count)) else { return aborted() }
            if !(2...32).contains(b.points.count) || !b.confidence.isFinite || !(0...1).contains(b.confidence) ||
                b.points.contains(where:{ !$0.x.isFinite || !$0.y.isFinite || !(0...1).contains($0.x) || !(0...1).contains($0.y) }) ||
                !zip(b.points,b.points.dropFirst()).allSatisfy({ $1.y>$0.y }) { continue }
            current.append((index,b))
        }
        struct Pairing { let distance: Double; let prior, current: Int }
        var pairs: [Pairing] = []
        for (i,a) in prior.enumerated() { for (j,b) in current.enumerated() {
            guard check((a.boundary.points.count+b.1.points.count)*5) else { return aborted() }
            if a.boundary.cue != b.1.cue { continue }
            if let d=distance(a.boundary.points,b.1.points,fragmentAware:fragmentAware) { pairs.append(Pairing(distance:d,prior:i,current:j)) }
        } }
        pairs.sort { a,b in
            if a.distance != b.distance { return a.distance<b.distance }
            if prior[a.prior].id != prior[b.prior].id { return prior[a.prior].id<prior[b.prior].id }
            return a.current<b.current
        }
        var priorUsed=Set<Int>(), assignments: [Int:Int] = [:]
        for pair in pairs where !priorUsed.contains(pair.prior) && assignments[pair.current]==nil {
            priorUsed.insert(pair.prior); assignments[pair.current]=pair.prior
        }
        var serial=nextId, updated: [Track] = [], items: [RoadBoundaryPresentationItem] = [], visible: [Int] = []
        for (index,entry) in current.enumerated() {
            guard check() else { return aborted() }
            let old=assignments[index].map { prior[$0] }
            let observed=entry.1.provenance != .tracked
            if retainTentativeIdentity && !observed {
                // A prediction can relocate an identity, but cannot observe paint or extend its life.
                if let old {
                    updated.append(Track(id:old.id,boundary:entry.1,firstObserved:old.firstObserved,lastObserved:old.lastObserved,
                        observations:old.observations,confirmed:old.confirmed,misses:old.misses+1))
                    items.append(RoadBoundaryPresentationItem(trackId:old.id,boundaryIndex:nil,state:"missing",observationCount:old.observations,
                        firstObservedSeconds:old.firstObserved,lastObservedSeconds:old.lastObserved,missedExposures:old.misses+1))
                }
                continue
            }
            let first=old?.firstObserved ?? (observed ? exposureSeconds : nil)
            let count=(old?.observations ?? 0)+(observed ? 1 : 0)
            let confirmed=old?.confirmed == true || (observed && count>=2 && first != nil && exposureSeconds-first!>=0.30)
            let id=old?.id ?? serial
            if old==nil { serial += 1 }
            let track=Track(id:id,boundary:entry.1,firstObserved:first,lastObserved:exposureSeconds,observations:count,confirmed:confirmed,misses:0)
            updated.append(track)
            if confirmed { visible.append(entry.0) }
            items.append(RoadBoundaryPresentationItem(trackId:id,boundaryIndex:entry.0,state:confirmed ? "confirmed" : "tentative",
                observationCount:count,firstObservedSeconds:first,lastObservedSeconds:exposureSeconds,missedExposures:0))
        }
        for (index,old) in prior.enumerated() {
            guard check() else { return aborted() }
            if !priorUsed.contains(index) && (old.confirmed || retainTentativeIdentity) && (retainMissingByTime || retainTentativeIdentity || old.misses==0) && exposureSeconds-old.lastObserved<=0.75 {
                var missing=old; missing.misses=old.misses+1; updated.append(missing)
                items.append(RoadBoundaryPresentationItem(trackId:old.id,boundaryIndex:nil,state:"missing",observationCount:old.observations,
                    firstObservedSeconds:old.firstObserved,lastObservedSeconds:old.lastObserved,missedExposures:old.misses+1))
            }
        }
        guard check() else { return aborted() }
        tracks=Array(updated.prefix(12)); scope=key; lastTime=exposureSeconds; nextId=serial
        return RoadBoundaryPresentationSnapshot(accepted:true,reason:resetReason,visibleBoundaryIndices:visible,items:items,rawCount:rawCount,operationCount:operations,expiredTrackIds:expired)
    }
    private func distance(_ a: [LanePoint], _ b: [LanePoint], fragmentAware: Bool) -> Double? {
        let top=max(a.first!.y,b.first!.y), bottom=min(a.last!.y,b.last!.y)
        if bottom-top < (fragmentAware ? 0.04 : 0.12) { return nil }
        let deltas=(0...4).map { i -> Double in let y=top+(bottom-top)*Double(i)/4; return roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y) }
        let mean=deltas.reduce(0) { $0+abs($1) }/5, signedMean=deltas.reduce(0,+)/5
        return mean<=0.045 && deltas.allSatisfy { abs($0)<=0.07 && abs($0-signedMean)<=0.025 } ? mean : nil
    }
}

/// Preview geometry only. Lane count never supplies a lane index or metric width.
/// The session supplies current verified intrinsics/mount and eligible causal motion.
struct RoadBoundaryEgoContext {
    var calibration: RoadPathCalibration? = nil
    var speedMetersPerSecond: Double? = nil
    var headingRateDegreesPerSecond: Double? = nil
    var directionalLaneCount: Int? = nil
    var roadContextConfidence: Double = 0

    private var validCalibration: RoadPathCalibration? {
        guard let c=calibration,c.verified,
              [c.fx,c.fy,c.cx,c.cy,c.pitchDegrees,c.rollDegrees,c.yawDegrees,c.heightMeters].allSatisfy(\.isFinite),
              (0.1...10).contains(c.fx),(0.1...10).contains(c.fy),(0...1).contains(c.cx),(0...1).contains(c.cy),
              abs(c.pitchDegrees)<=15,abs(c.rollDegrees)<=15,abs(c.yawDegrees)<=15,(0.3...4).contains(c.heightMeters),
              let offset=c.lateralOffsetMeters,offset.isFinite,abs(offset)<=2 else { return nil }
        return c
    }
    func ground(_ point: LanePoint, visual: VisualRoadCalibration?) -> LanePoint? {
        guard let c=validCalibration else { return nil }
        let pitch=visual.flatMap { $0.isValid ? atan((c.cy-$0.horizonY)/c.fy) : nil } ?? c.pitchDegrees * .pi/180
        let roll=c.rollDegrees * .pi/180,yaw=c.yawDegrees * .pi/180
        let u=(point.x-c.cx)/c.fx,v=(point.y-c.cy)/c.fy
        let rx=cos(roll)*u-sin(roll)*v,ry=sin(roll)*u+cos(roll)*v
        let down=cos(pitch)*ry+sin(pitch),forward = -sin(pitch)*ry+cos(pitch)
        guard down>0.02 else { return nil }
        let z=(-sin(yaw)*rx+cos(yaw)*forward)*c.heightMeters/down
        let x=(cos(yaw)*rx+sin(yaw)*forward)*c.heightMeters/down+c.lateralOffsetMeters!
        return x.isFinite && (2...80).contains(z) ? LanePoint(x:x,y:z) : nil
    }
    private func pathX(_ z: Double) -> Double {
        guard let speed=speedMetersPerSecond,let rate=headingRateDegreesPerSecond,
              speed.isFinite,rate.isFinite,(3...60).contains(speed),abs(rate)<=15 else { return 0 }
        // Constant-curvature is a weak short-range trajectory prior, never observed paint.
        let curvature=rate * .pi/180/speed
        return max(-2,min(2,0.5*curvature*pow(min(z,25),2)))
    }
    func centerX(row: Double, visual: VisualRoadCalibration?) -> Double? {
        guard validCalibration != nil else { return nil }
        var low=0.0,high=1.0
        guard let a=ground(LanePoint(x:low,y:row),visual:visual),let b=ground(LanePoint(x:high,y:row),visual:visual),
              a.x-pathX(a.y)<0,b.x-pathX(b.y)>0 else { return nil }
        for _ in 0..<12 {
            let middle=(low+high)/2
            guard let p=ground(LanePoint(x:middle,y:row),visual:visual) else { return nil }
            if p.x<pathX(p.y) { low=middle } else { high=middle }
        }
        return (low+high)/2
    }
    var multiLaneEdgePenalty: Double {
        guard let count=directionalLaneCount,(2...8).contains(count),roadContextConfidence.isFinite,
              (0.6...1).contains(roadContextConfidence) else { return 0 }
        return 0.06*roadContextConfidence
    }
}

/// Preview-only ego corridor selection. Confidence is evidence strength, not accuracy.
/// Identities may persist through gaps; coordinates are always from the current frame.
final class RoadBoundaryEgoSelector {
    private struct Side {
        var id: Int64? = nil
        var points: [LanePoint] = []
        var lastSeen = -Double.infinity
        var challenger: Int64? = nil
        var challengedAt = 0.0
    }
    private struct Candidate { let index: Int; let id: Int64; let score: Double; let points: [LanePoint] }
    private var left = Side(), right = Side()
    private var scope: String? = nil
    private var lastTime = -Double.infinity
    private var jointChallenger: String? = nil
    private var jointChallengedAt=0.0
    func reset() { left=Side(); right=Side(); scope=nil; lastTime = -Double.infinity; jointChallenger=nil }
    func select(_ snapshot: RoadBoundaryPresentationSnapshot, boundaries: [RoadBoundaryEvidence],
                visual: VisualRoadCalibration?, time: Double, key: String, fragmentAware: Bool = false, jointSelection: Bool = false, egoContext: RoadBoundaryEgoContext? = nil,
                semanticScoreAdjustments: [Double]? = nil) -> RoadBoundaryPresentationSnapshot {
        guard snapshot.accepted, time.isFinite else { reset(); return snapshot }
        if scope != key || time <= lastTime || time-lastTime > 0.75 { reset() }
        scope=key; lastTime=time
        // Explicit offline experiment input. Callers must qualify the exposure and
        // map raw hypothesis indices first. Missing/malformed arrays are a no-op.
        // Same-image semantics never add support, maturity or temporal observations.
        let semantic = semanticScoreAdjustments.flatMap { values -> [Double]? in
            values.count == boundaries.count && values.allSatisfy { $0.isFinite && (0...0.10).contains($0) } ? values : nil
        }
        let y=min(0.83,max(0.78,(visual?.horizonY ?? 0.50)+0.20))
        func center(_ row: Double) -> Double {
            guard let v=visual else { return jointSelection ? egoContext?.centerX(row:row,visual:nil) ?? 0.5 : 0.5 }
            return (roadBoundaryXAt([LanePoint(x:v.leftTopX,y:v.horizonY),v.leftBottom],row) +
                    roadBoundaryXAt([LanePoint(x:v.rightTopX,y:v.horizonY),v.rightBottom],row))/2
        }
        var decisions=boundaries.indices.map { RoadBoundarySelectionDecision(boundaryIndex:$0) }
        var l: [Candidate]=[], r: [Candidate]=[]
        for index in snapshot.visibleBoundaryIndices.prefix(6) {
            guard boundaries.indices.contains(index), let id=snapshot.items.first(where:{$0.boundaryIndex==index})?.trackId else { continue }
            let b=boundaries[index]
            guard let top=b.points.first, let bottom=b.points.last else { decisions[index].reason="empty_geometry"; continue }
            if (fragmentAware || jointSelection) && b.provenance == .tracked { decisions[index].reason="tracked_only"; continue }
            guard b.confidence >= 0.25 else { decisions[index].reason="confidence"; continue }
            guard b.supportRows >= 4 else { decisions[index].reason="support_rows"; continue }
            guard bottom.y-top.y >= (fragmentAware ? 0.06 : 0.12) else { decisions[index].reason="vertical_span"; continue }
            let anchor=fragmentAware ? min(bottom.y,max(top.y,y)) : y
            if !fragmentAware && (top.y>y || bottom.y<y) { decisions[index].reason="lower_anchor_missing"; continue }
            let cx=center(anchor), delta=roadBoundaryXAt(b.points,anchor)-cx
            decisions[index].anchorY=anchor; decisions[index].centerX=cx
            decisions[index].side=delta<0 ? "left" : "right"
            guard abs(delta) >= (fragmentAware ? 0.015 : 0.025) else { decisions[index].reason="center_exclusion"; continue }
            guard abs(delta)<=0.45 else { decisions[index].reason="lateral_distance"; continue }
            let score=b.confidence + min(0.2,(bottom.y-top.y)*0.4) + (b.cue == .paint ? 0.12 : 0) - abs(delta)*0.6 -
                (jointSelection && b.cue == .edge ? 0.20+(egoContext?.multiLaneEdgePenalty ?? 0) : 0) + (semantic?[index] ?? 0)
            decisions[index].score=score; decisions[index].reason="candidate"
            let candidate=Candidate(index:index,id:id,score:score,points:b.points)
            if delta<0 { l.append(candidate) } else { r.append(candidate) }
        }
        var a: Candidate?, b: Candidate?
        if jointSelection { (a,b)=chooseJoint(l,r,boundaries:boundaries,visual:visual,context:egoContext,fragmentAware:fragmentAware,time:time,center:center,decisions:&decisions) }
        else { a=choose(l,side:&left,time:time); b=choose(r,side:&right,time:time) }
        if let x=a, let z=b {
            let top=max(fragmentAware ? 0 : y,max(x.points.first!.y,z.points.first!.y)), bottom=min(x.points.last!.y,z.points.last!.y)
            let jointQuality=jointSelection ? pairQuality(x,z,boundaries:boundaries,visual:visual,context:egoContext,fragmentAware:fragmentAware,center:center) : nil
            let valid=jointQuality?.valid ?? (bottom-top >= (fragmentAware ? 0.04 : 0.06) && (0...4).allSatisfy { i in
                let row=top+(bottom-top)*Double(i)/4
                let lx=roadBoundaryXAt(x.points,row), rx=roadBoundaryXAt(z.points,row)
                return rx-lx>=0.035 && rx-lx<=0.90 && lx<center(row)+0.02 && rx>center(row)-0.02
            })
            if !valid {
                if x.score>=z.score { decisions[z.index].reason="pair_geometry"; decisions[z.index].corridorReason=jointQuality?.reason; b=nil }
                else { decisions[x.index].reason="pair_geometry"; decisions[x.index].corridorReason=jointQuality?.reason; a=nil }
            }
        }
        for (candidates,chosen) in [(l,a),(r,b)] {
            for c in candidates where decisions[c.index].reason != "pair_geometry" {
                decisions[c.index].reason = chosen?.index == c.index ? "selected" : chosen == nil ? "incumbent_reacquisition_hold" :
                    c.score > chosen!.score ? "challenger_margin_or_dwell" : "lower_side_score"
            }
        }
        return RoadBoundaryPresentationSnapshot(accepted:snapshot.accepted,reason:snapshot.reason,
            visibleBoundaryIndices:[a?.index,b?.index].compactMap{$0},items:snapshot.items,rawCount:snapshot.rawCount,
            operationCount:snapshot.operationCount,selectionDecisions:decisions,expiredTrackIds:snapshot.expiredTrackIds)
    }
    private struct PairQuality { let reason: String; let adjustment: Double; var metricWidth: Double? = nil; var valid: Bool { reason == "consistent_corridor" } }
    private struct JointPair { let left, right: Candidate; let score: Double }
    private func pairQuality(_ a: Candidate, _ b: Candidate, boundaries: [RoadBoundaryEvidence], visual: VisualRoadCalibration?,
                             context: RoadBoundaryEgoContext?, fragmentAware: Bool, center: (Double)->Double) -> PairQuality {
        let top=max(a.points.first!.y,b.points.first!.y),bottom=min(a.points.last!.y,b.points.last!.y)
        guard bottom-top >= (fragmentAware ? 0.04 : 0.06) else { return PairQuality(reason:"no_common_support",adjustment:0) }
        let rows=(0...4).map { top+(bottom-top)*Double($0)/4 }
        let widths=rows.map { roadBoundaryXAt(b.points,$0)-roadBoundaryXAt(a.points,$0) }
        guard widths.allSatisfy({ (0.035...0.90).contains($0) }) else { return PairQuality(reason:"crossing_or_image_width",adjustment:0) }
        // Far paint may bend away from the vehicle axis. Containment is checked in the near half.
        guard rows.suffix(3).allSatisfy({ roadBoundaryXAt(a.points,$0)<center($0)+0.02 && roadBoundaryXAt(b.points,$0)>center($0)-0.02 })
        else { return PairQuality(reason:"vehicle_outside_corridor",adjustment:0) }
        let mean=widths.reduce(0,+)/5
        guard (1...3).allSatisfy({ abs(widths[$0+1]-2*widths[$0]+widths[$0-1])<=max(0.025,mean*0.25) })
        else { return PairQuality(reason:"inconsistent_curvature",adjustment:0) }
        var penalty=0.0,metricWidth: Double? = nil
        if let v=visual {
            let ratios=rows.compactMap { row -> Double? in
                let expected=roadBoundaryXAt([LanePoint(x:v.rightTopX,y:v.horizonY),v.rightBottom],row)-roadBoundaryXAt([LanePoint(x:v.leftTopX,y:v.horizonY),v.leftBottom],row)
                return expected>=0.06 ? (roadBoundaryXAt(b.points,row)-roadBoundaryXAt(a.points,row))/expected : nil
            }
            if !ratios.isEmpty { penalty += min(0.25,ratios.map { abs($0-1) }.reduce(0,+)/Double(ratios.count)*0.20) }
        }
        if let context {
            let ag=a.points.compactMap { context.ground($0,visual:visual) }.sorted { $0.y<$1.y }
            let bg=b.points.compactMap { context.ground($0,visual:visual) }.sorted { $0.y<$1.y }
            if let af=ag.first,let al=ag.last,let bf=bg.first,let bl=bg.last {
                let near=max(2,max(af.y,bf.y)),far=min(35,min(al.y,bl.y))
                if far-near>=2 {
                    let metric=(0...4).map { i -> Double in
                        let z=near+(far-near)*Double(i)/4
                        return roadBoundaryXAt(bg,z)-roadBoundaryXAt(ag,z)
                    }
                    let width=metric.reduce(0,+)/5; metricWidth=width
                    // A failed metric pair may still leave one supported painted border visible.
                    guard metric.allSatisfy({ (2...6).contains($0) }) else { return PairQuality(reason:"metric_width",adjustment:0,metricWidth:width) }
                    guard metric.max()!-metric.min()!<=max(1.5,width*0.4) else { return PairQuality(reason:"metric_width_change",adjustment:0,metricWidth:width) }
                    penalty += min(0.25,abs(width-3.5)*0.10)
                }
            }
        }
        let paintCount=[a,b].filter { boundaries[$0.index].cue == .paint }.count
        return PairQuality(reason:"consistent_corridor",adjustment:0.20+Double(paintCount)*0.08-penalty,metricWidth:metricWidth)
    }
    private func chooseJoint(_ l: [Candidate],_ r: [Candidate],boundaries:[RoadBoundaryEvidence],visual:VisualRoadCalibration?,
                             context:RoadBoundaryEgoContext?,fragmentAware:Bool,time:Double,center:(Double)->Double,
                             decisions: inout [RoadBoundarySelectionDecision]) -> (Candidate?,Candidate?) {
        var pairs: [JointPair] = []
        for a in l { for b in r {
            let quality=pairQuality(a,b,boundaries:boundaries,visual:visual,context:context,fragmentAware:fragmentAware,center:center)
            for c in [a,b] {
                if decisions[c.index].corridorReason != "consistent_corridor" {
                    decisions[c.index].corridorReason=quality.reason; decisions[c.index].metricWidthMeters=quality.metricWidth
                }
            }
            if quality.valid { pairs.append(JointPair(left:a,right:b,score:a.score+b.score+quality.adjustment)) }
        } }
        pairs.sort { a,b in a.score != b.score ? a.score>b.score : a.left.id != b.left.id ? a.left.id<b.left.id : a.right.id<b.right.id }
        guard var best=pairs.first else {
            jointChallenger=nil
            return (choose(l,side:&left,time:time),choose(r,side:&right,time:time))
        }
        if let current=pairs.first(where: { $0.left.id==left.id && $0.right.id==right.id }) {
            if best.left.id==current.left.id && best.right.id==current.right.id || best.score<current.score+0.25 { best=current; jointChallenger=nil }
            else {
                let challenger="\(best.left.id):\(best.right.id)"
                if jointChallenger != challenger { jointChallenger=challenger; jointChallengedAt=time }
                if time-jointChallengedAt<0.35 { best=current } else { jointChallenger=nil }
            }
            left=Side(id:best.left.id,points:best.left.points,lastSeen:time)
            right=Side(id:best.right.id,points:best.right.points,lastSeen:time)
            return (best.left,best.right)
        }
        // An absent incumbent may delay replacement, but its old points are never output.
        jointChallenger=nil
        return (choose([best.left],side:&left,time:time),choose([best.right],side:&right,time:time))
    }
    private func choose(_ candidates: [Candidate], side: inout Side, time: Double) -> Candidate? {
        let sorted=candidates.sorted { $0.score == $1.score ? $0.id<$1.id : $0.score>$1.score }
        guard let best=sorted.first else {
            side.challenger=nil
            if time-side.lastSeen>0.75 { side=Side() }
            return nil
        }
        let incumbent=sorted.first { $0.id==side.id }
        if let current=incumbent {
            side.lastSeen=time; side.points=current.points
            if best.id==current.id || best.score<current.score+0.15 { side.challenger=nil; return current }
            if side.challenger != best.id { side.challenger=best.id; side.challengedAt=time }
            if time-side.challengedAt<0.35 { return current }
        } else if side.id != nil && time-side.lastSeen<=0.35 && !near(best.points,side.points) {
            // Brief occlusion: wait for the incumbent without displaying old coordinates.
            return nil
        }
        side.id=best.id; side.points=best.points; side.lastSeen=time; side.challenger=nil
        return best
    }
    private func near(_ a: [LanePoint], _ b: [LanePoint]) -> Bool {
        guard let af=a.first, let al=a.last, let bf=b.first, let bl=b.last else { return false }
        let top=max(af.y,bf.y), bottom=min(al.y,bl.y)
        return bottom-top>=0.12 && (0...4).allSatisfy { i in
            let y=top+(bottom-top)*Double(i)/4
            return abs(roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y))<=0.055
        }
    }
}

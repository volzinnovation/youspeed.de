import Foundation

/// Motion-supported image evidence; neither calibration nor an old curve creates fresh paint.
struct RoadBoundaryPrediction {
    let boundaries: [RoadBoundaryEvidence]
    let timestampSeconds, capturedAtSeconds: Double
    let width, height: Int
    let key: String
    let operationCount: Int
    let budgetExceeded: Bool
    let resetReason: String?
    fileprivate let acceptFrame: Bool
    var fragmentAware = false
}

/// One raw-luma history frame; arithmetic and search bounds match the Android core.
final class RoadBoundaryTemporalTracker {
    private struct Previous {
        let gray: [UInt8]
        let width, height: Int
        let time: Double
        let key: String
        let boundaries: [RoadBoundaryEvidence]
    }
    private struct Match { let x, y, cost: Int }
    private struct Flow { let x, y, dx, dy, residualX, residualY: Int }
    private final class Budget {
        let maximum: Int
        let proceed: () -> Bool
        var used = 0
        private var failed = false
        init(_ maximum: Int, _ proceed: @escaping () -> Bool) { self.maximum=maximum; self.proceed=proceed }
        func check(_ cost: Int = 1) -> Bool {
            if failed || cost > maximum-used || !proceed() { failed=true; return false }
            used += cost; return true
        }
    }
    private var previous: Previous?
    func reset() { previous=nil }

    func predict(grayscale: [UInt8], width: Int, height: Int, timestampSeconds: Double, key: String,
                 capturedAtSeconds: Double? = nil, maximumOperations: Int = 300_000,
                 motionHint: RoadBoundaryMotionHint? = nil, motionProjection: RoadBoundaryMotionProjection? = nil, fragmentAware: Bool = false,
                 shouldContinue: @escaping () -> Bool = { true }) -> RoadBoundaryPrediction {
        let captured = capturedAtSeconds ?? timestampSeconds
        let budget = Budget(max(0,maximumOperations),shouldContinue)
        func empty(_ reason: String?, exceeded: Bool = false, accept: Bool = true, preserve: Bool = false) -> RoadBoundaryPrediction {
            if !preserve && (reason != nil || exceeded) { reset() }
            return RoadBoundaryPrediction(boundaries:[],timestampSeconds:timestampSeconds,capturedAtSeconds:captured,
                width:width,height:height,key:key,operationCount:budget.used,budgetExceeded:exceeded,resetReason:reason,acceptFrame:accept,fragmentAware:fragmentAware)
        }
        guard (64...384).contains(width), (64...216).contains(height), grayscale.count==width*height,
              timestampSeconds.isFinite, captured.isFinite else { return empty("invalid_input",accept:false) }
        if let old=previous, old.key==key,old.width==width,old.height==height,timestampSeconds<=old.time {
            return empty(timestampSeconds==old.time ? "duplicate_exposure" : "out_of_order_exposure",accept:false,preserve:true)
        }
        guard budget.check() else { return empty("deadline",exceeded:true) }
        guard let old = previous else { return empty(nil) }
        guard old.key==key, old.width==width, old.height==height else { return empty("scope_or_geometry") }
        let dt=timestampSeconds-old.time
        if dt>0.8 { return empty("exposure_gap") }
        let radius=max(min(12,max(4,Int(ceil(dt*20)))),motionHint?.used == true ? min(12,max(0,motionHint!.horizontalSearchRadiusFloor)) : 0)
        var tracked: [RoadBoundaryEvidence] = []
        for boundary in old.boundaries.prefix(6) {
            guard budget.check() else { return empty("deadline",exceeded:true) }
            let age=boundary.evidenceAgeSeconds+dt
            if age>0.8 || boundary.points.count<(fragmentAware ? 2 : 4) { continue }
            let segments=boundary.observedSegments.isEmpty ? [boundary.points] : boundary.observedSegments
            let anchors=fragmentAware ? paintAnchors(segments) : sample(boundary.points,8)
            var flows: [Flow] = []
            for point in anchors {
                let x=Int((point.x*Double(width-1)).rounded()), y=Int((point.y*Double(height-1)).rounded())
                let predicted: LanePoint
                if let motionProjection { guard let p=motionProjection.project(point,dt:dt) else { continue }; predicted=p }
                else { predicted=point }
                let px=Int((predicted.x*Double(width-1)).rounded()), py=Int((predicted.y*Double(height-1)).rounded())
                let uncertainty=fragmentAware ? motionProjection?.searchUncertaintyPixels(point,dt:dt,width:width,height:height) : nil
                let searchRadius=max(radius,uncertainty?.horizontal ?? 0)
                let vertical=max(motionProjection != nil ? 4 : 2,uncertainty?.vertical ?? 0)
                guard let forward=search(old.gray,grayscale,width,height,x,y,searchRadius,budget,centerX:px,centerY:py,vertical:vertical,refineCandidates:fragmentAware ? 3 : 1),
                      let reverse=search(grayscale,old.gray,width,height,forward.x,forward.y,searchRadius,budget,
                        centerX:motionProjection != nil || fragmentAware ? x : forward.x,centerY:motionProjection != nil || fragmentAware ? y : forward.y,vertical:vertical,refineCandidates:fragmentAware ? 3 : 1) else { continue }
                if abs(reverse.x-x)<=1 && abs(reverse.y-y)<=2 {
                    flows.append(Flow(x:x,y:y,dx:forward.x-x,dy:forward.y-y,residualX:forward.x-px,residualY:forward.y-py))
                }
            }
            guard budget.check() else { return empty("deadline",exceeded:true) }
            if flows.count<4 || flows.count*5<anchors.count*3 { continue }
            let medianX=flows.map(\.residualX).sorted()[flows.count/2], medianY=flows.map(\.residualY).sorted()[flows.count/2]
            let coherent=flows.filter { abs($0.residualX-medianX)<=4 && abs($0.residualY-medianY)<=2 }.sorted { $0.y<$1.y }
            if coherent.count<4 || Double(coherent.last!.y-coherent.first!.y)<(fragmentAware ? 0.06 : 0.12)*Double(height-1) { continue }
            let points=sample(boundary.points,12).filter {
                $0.y*Double(height-1)>=Double(coherent.first!.y-1) && $0.y*Double(height-1)<=Double(coherent.last!.y+1)
            }.map { point -> LanePoint in
                let py=point.y*Double(height-1)
                let upper=max(1,coherent.firstIndex { Double($0.y)>=py } ?? coherent.count-1)
                let a=coherent[upper-1], b=coherent[upper]
                let fraction=max(0,min(1,(py-Double(a.y))/Double(max(1,b.y-a.y))))
                return LanePoint(x:max(0,min(1,point.x+(Double(a.dx)+Double(b.dx-a.dx)*fraction)/Double(width-1))),
                    y:max(0,min(1,point.y+(Double(a.dy)+Double(b.dy-a.dy)*fraction)/Double(height-1))))
            }
            if points.count<(fragmentAware ? 2 : 4) || !zip(points,points.dropFirst()).allSatisfy({ $1.y>$0.y }) { continue }
            let confidence=boundary.confidence*(1-dt/0.8)*Double(coherent.count)/Double(anchors.count)
            if confidence<0.12 { continue }
            // Only actual confirmed patch locations are carried as paint support.
            // Interpolated model points across gaps remain a separate search prior.
            let carriedSegments: [[LanePoint]] = fragmentAware ? segments.compactMap { segment in
                guard let first=segment.first, let last=segment.last else { return nil }
                let matched=coherent.filter { Double($0.y) >= first.y*Double(height-1)-1 && Double($0.y) <= last.y*Double(height-1)+1 }
                    .map { LanePoint(x:Double($0.x+$0.dx)/Double(width-1),y:Double($0.y+$0.dy)/Double(height-1)) }
                return matched.count>=2 && zip(matched,matched.dropFirst()).allSatisfy({$1.y>$0.y}) ? matched : nil
            } : []
            if fragmentAware && carriedSegments.isEmpty { continue }
            tracked.append(RoadBoundaryEvidence(points:smooth(points,width),confidence:confidence,cue:boundary.cue,supportRows:boundary.supportRows,
                provenance:.tracked,lastFreshTimestampSeconds:boundary.lastFreshTimestampSeconds,evidenceAgeSeconds:age,trackedAnchorCount:coherent.count,
                observedSegments:carriedSegments,geometryConfidence:boundary.geometryConfidence,paintOccupancy:boundary.paintOccupancy))
        }
        guard budget.check() else { return empty("deadline",exceeded:true) }
        return RoadBoundaryPrediction(boundaries:tracked,timestampSeconds:timestampSeconds,capturedAtSeconds:captured,
            width:width,height:height,key:key,operationCount:budget.used,budgetExceeded:false,resetReason:nil,acceptFrame:true,fragmentAware:fragmentAware)
    }

    /// Carried curves never manufacture corridor pairs; only this exposure's fresh pairs survive.
    func complete(prediction: RoadBoundaryPrediction, fresh: RoadBoundaryFrame, grayscale: [UInt8],
                  shouldContinue: () -> Bool = { true }) -> RoadBoundaryFrame {
        func aborted() -> RoadBoundaryFrame {
            reset()
            return RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:prediction.capturedAtSeconds,budgetExceeded:true,
                operationCount:fresh.operationCount,temporalOperationCount:prediction.operationCount,temporalResetReason:"deadline",rejectionCounts:fresh.rejectionCounts,detectionVariant:fresh.detectionVariant)
        }
        if !prediction.acceptFrame {
            return RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:prediction.capturedAtSeconds,
                temporalOperationCount:prediction.operationCount,temporalResetReason:prediction.resetReason,rejectionCounts:fresh.rejectionCounts,detectionVariant:fresh.detectionVariant)
        }
        if prediction.budgetExceeded || fresh.budgetExceeded || !shouldContinue() { return aborted() }
        if grayscale.count != prediction.width*prediction.height || fresh.timestampSeconds != prediction.capturedAtSeconds {
            reset()
            return RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:prediction.capturedAtSeconds,
                temporalOperationCount:prediction.operationCount,temporalResetReason:prediction.resetReason,rejectionCounts:fresh.rejectionCounts,detectionVariant:fresh.detectionVariant)
        }
        struct Entry { let original: Int?; let boundary: RoadBoundaryEvidence }
        var used=Set<Int>(), entries: [Entry] = []
        for (index,observed) in fresh.boundaries.prefix(6).enumerated() {
            guard shouldContinue() else { return aborted() }
            let candidate=prediction.boundaries.indices.filter { !used.contains($0) && prediction.boundaries[$0].cue==observed.cue }
                .min { distance(observed.points,prediction.boundaries[$0].points)<distance(observed.points,prediction.boundaries[$1].points) }
            let match=candidate.flatMap { distance(observed.points,prediction.boundaries[$0].points)<=0.035 ? $0 : nil }
            let current=sample(observed.points,12)
            let points: [LanePoint]
            if let match {
                used.insert(match)
                let prior=prediction.boundaries[match].points
                points=current.map { p in
                    let offset=(roadBoundaryXAt(prior,p.y)-p.x)*0.25, limit=2/Double(prediction.width-1)
                    return LanePoint(x:p.x+max(-limit,min(limit,offset)),y:p.y)
                }
            } else { points=current }
            entries.append(Entry(original:index,boundary:RoadBoundaryEvidence(points:smooth(points,prediction.width),
                confidence:observed.confidence,cue:observed.cue,supportRows:observed.supportRows,
                provenance:match==nil ? .fresh : .fused,lastFreshTimestampSeconds:prediction.capturedAtSeconds,evidenceAgeSeconds:0,
                trackedAnchorCount:match.map { prediction.boundaries[$0].trackedAnchorCount } ?? 0,
                observedSegments:observed.observedSegments,geometryConfidence:observed.geometryConfidence,paintOccupancy:observed.paintOccupancy)))
        }
        for (index,carried) in prediction.boundaries.enumerated() {
            guard shouldContinue() else { return aborted() }
            if !used.contains(index) && !entries.contains(where:{distance($0.boundary.points,carried.points)<=0.035}) {
                entries.append(Entry(original:nil,boundary:carried))
            }
        }
        let selected=Array(entries.sorted {
            $0.boundary.confidence==$1.boundary.confidence ? $0.boundary.points.last!.x<$1.boundary.points.last!.x : $0.boundary.confidence>$1.boundary.confidence
        }.prefix(6)).sorted { $0.boundary.points.last!.x<$1.boundary.points.last!.x }
        let corridors=Array(fresh.corridors.compactMap { corridor -> RoadCorridorHypothesis? in
            guard let left=selected.firstIndex(where:{$0.original==corridor.leftBoundaryIndex}),
                  let right=selected.firstIndex(where:{$0.original==corridor.rightBoundaryIndex}),right==left+1 else { return nil }
            return RoadCorridorHypothesis(leftBoundaryIndex:left,rightBoundaryIndex:right,confidence:corridor.confidence)
        }.prefix(2))
        guard shouldContinue() else { return aborted() }
        let boundaries=selected.map(\.boundary)
        previous=Previous(gray:grayscale,width:prediction.width,height:prediction.height,time:prediction.timestampSeconds,key:prediction.key,boundaries:boundaries)
        return RoadBoundaryFrame(boundaries:boundaries,corridors:corridors,timestampSeconds:prediction.capturedAtSeconds,
            operationCount:fresh.operationCount,temporalOperationCount:prediction.operationCount,temporalResetReason:prediction.resetReason,rejectionCounts:fresh.rejectionCounts,detectionVariant:fresh.detectionVariant)
    }

    private func search(_ source: [UInt8], _ target: [UInt8], _ width: Int, _ height: Int,
                        _ x: Int, _ y: Int, _ radius: Int, _ budget: Budget, centerX: Int? = nil, centerY: Int? = nil, vertical: Int = 2, refineCandidates: Int = 1) -> Match? {
        let cx=centerX ?? x, cy=centerY ?? y
        func inside(_ px: Int,_ py: Int) -> Bool { px>=2 && px<width-2 && py>=2 && py<height-2 }
        guard inside(x,y) else { return nil }
        var lo=255, hi=0
        for dy in -2...2 { for dx in -2...2 { let value=Int(source[(y+dy)*width+x+dx]);lo=min(lo,value);hi=max(hi,value) } }
        if hi-lo<24 { return nil }
        func cost(_ px: Int,_ py: Int) -> Int? {
            guard inside(px,py),budget.check(25) else { return nil }
            var sad=0
            for dy in -2...2 { for dx in -2...2 { sad += abs(Int(source[(y+dy)*width+x+dx])-Int(target[(py+dy)*width+px+dx])) } }
            return sad
        }
        var best: Match?
        var coarseMatches: [Match] = []
        func consider(_ px: Int,_ py: Int,recordCoarse: Bool = false) {
            guard let value=cost(px,py) else { return }
            if recordCoarse { coarseMatches.append(Match(x:px,y:py,cost:value)) }
            if best==nil || value<best!.cost || (value==best!.cost && abs(px-x)+abs(py-y)<abs(best!.x-x)+abs(best!.y-y)) {
                best=Match(x:px,y:py,cost:value)
            }
        }
        let offsets=Set(Array(stride(from:-radius,through:radius,by:2))+[0]).sorted()
        for dy in stride(from:-vertical,through:vertical,by:2) { for dx in offsets { consider(cx+dx,cy+dy,recordCoarse:refineCandidates>1) } }
        guard let coarse=best else { return nil }
        // Fragment endpoints can alias a two-pixel coarse grid. Refine three
        // bounded candidates, without weakening SAD or forward/backward checks.
        let candidates=refineCandidates>1 ? Array(coarseMatches.sorted {
            if $0.cost != $1.cost { return $0.cost<$1.cost }
            let a=abs($0.x-x)+abs($0.y-y), b=abs($1.x-x)+abs($1.y-y)
            return a != b ? a<b : $0.y != $1.y ? $0.y<$1.y : $0.x<$1.x
        }.prefix(3)) : [coarse]
        for candidate in candidates { for dy in -1...1 { for dx in -1...1 {
            if abs(candidate.x+dx-cx)<=radius && abs(candidate.y+dy-cy)<=vertical { consider(candidate.x+dx,candidate.y+dy) }
        } } }
        guard let result=best, result.cost<=18*25 else { return nil }
        let alternate=[cost(result.x-3,result.y),cost(result.x+3,result.y)].compactMap{$0}.min()
        if let alternate, alternate-result.cost<30 { return nil }
        return result
    }
    /// At most eight points, drawn only from painted intervals, with fragment
    /// endpoints prioritized before interiors. Never anchor inside a fitted gap.
    private func paintAnchors(_ segments: [[LanePoint]]) -> [LanePoint] {
        let valid=segments.filter { $0.count>=2 && $0.last!.y>$0.first!.y }
        let chosen=valid.count<=4 ? valid : (0..<4).map { valid[$0*(valid.count-1)/3] }
        var points: [LanePoint] = []
        func add(_ p: LanePoint) { if points.count<8 && !points.contains(where:{abs($0.x-p.x)<1e-9 && abs($0.y-p.y)<1e-9}) { points.append(p) } }
        for segment in chosen { add(segment.first!); add(segment.last!) }
        for fraction in [0.5,0.25,0.75,0.125,0.875,0.375] {
            for segment in chosen {
                let y=segment.first!.y+(segment.last!.y-segment.first!.y)*fraction
                add(LanePoint(x:roadBoundaryXAt(segment,y),y:y))
            }
        }
        return points.sorted {$0.y<$1.y}
    }
    private func sample(_ points: [LanePoint],_ maximum: Int) -> [LanePoint] {
        points.count<=maximum ? points : (0..<maximum).map { points[$0*(points.count-1)/(maximum-1)] }
    }
    private func smooth(_ points: [LanePoint],_ width: Int) -> [LanePoint] {
        points.enumerated().map { index,p in
            if index==0 || index==points.count-1 { return p }
            let offset=(points[index-1].x+2*p.x+points[index+1].x)/4-p.x, limit=1.5/Double(width-1)
            return LanePoint(x:p.x+max(-limit,min(limit,offset)),y:p.y)
        }
    }
    private func distance(_ a: [LanePoint],_ b: [LanePoint]) -> Double {
        if a.count<2 || b.count<2 { return .infinity }
        let top=max(a.first!.y,b.first!.y), bottom=min(a.last!.y,b.last!.y)
        if bottom-top<0.10 { return .infinity }
        return (0...4).reduce(0) { value,index in
            let y=top+(bottom-top)*Double(index)/4
            return value+abs(roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y))
        }/5
    }
}

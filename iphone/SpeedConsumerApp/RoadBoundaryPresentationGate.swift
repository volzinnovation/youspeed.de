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
struct RoadBoundaryPresentationSnapshot {
    let accepted: Bool
    let reason: String?
    let visibleBoundaryIndices: [Int]
    let items: [RoadBoundaryPresentationItem]
    let rawCount: Int
    var operationCount = 0
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

    func update(boundaries: [RoadBoundaryEvidence], exposureSeconds: Double, key: String,
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
            if let d=distance(a.boundary.points,b.1.points) { pairs.append(Pairing(distance:d,prior:i,current:j)) }
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
            if !priorUsed.contains(index) && old.confirmed && old.misses==0 && exposureSeconds-old.lastObserved<=0.75 {
                var missing=old; missing.misses=1; updated.append(missing)
                items.append(RoadBoundaryPresentationItem(trackId:old.id,boundaryIndex:nil,state:"missing",observationCount:old.observations,
                    firstObservedSeconds:old.firstObserved,lastObservedSeconds:old.lastObserved,missedExposures:1))
            }
        }
        guard check() else { return aborted() }
        tracks=Array(updated.prefix(12)); scope=key; lastTime=exposureSeconds; nextId=serial
        return RoadBoundaryPresentationSnapshot(accepted:true,reason:resetReason,visibleBoundaryIndices:visible,items:items,rawCount:rawCount,operationCount:operations)
    }
    private func distance(_ a: [LanePoint], _ b: [LanePoint]) -> Double? {
        let top=max(a.first!.y,b.first!.y), bottom=min(a.last!.y,b.last!.y)
        if bottom-top<0.12 { return nil }
        let deltas=(0...4).map { i -> Double in let y=top+(bottom-top)*Double(i)/4; return roadBoundaryXAt(a,y)-roadBoundaryXAt(b,y) }
        let mean=deltas.reduce(0) { $0+abs($1) }/5, signedMean=deltas.reduce(0,+)/5
        return mean<=0.045 && deltas.allSatisfy { abs($0)<=0.07 && abs($0-signedMean)<=0.025 } ? mean : nil
    }
}

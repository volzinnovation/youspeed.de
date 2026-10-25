import Foundation

/// Evidence from the selected map way, never from the nearest competing candidate.
struct SpeedReferenceBundleFix {
    let sourceTime: Double
    let ageSeconds: Double
    let accuracyMetres: Double
    let matchDistanceMetres: Double
    let applicable: Bool
}

/// Observation of one offer; never grants authority or retries withheld evidence.
struct SpeedReferenceCameraReceipt {
    let offeredID: String
    let offeredValue: SpeedReferenceValue
    let offeredKind: String
    let before: SpeedReferenceOutput
    let after: SpeedReferenceOutput
    let pendingContextBefore: Bool
    let pendingContextAfter: Bool

    var diagnosticFields: [String: Any] {
        ["offeredId": offeredID, "offeredValue": offeredValue.json, "offeredKind": offeredKind,
         "before": fields(before), "after": fields(after),
         "pendingContextBefore": pendingContextBefore, "pendingContextAfter": pendingContextAfter,
         "gapBefore": NSNull(), "seenBefore": NSNull(), "gateDiagnosticAvailability": "pending_context_only"]
    }
    private func fields(_ output: SpeedReferenceOutput) -> [String: Any] {
        ["state": output.state, "value": output.value?.json as Any? ?? NSNull(),
         "source": output.source as Any? ?? NSNull(), "evidenceId": output.evidenceID as Any? ?? NSNull(),
         "current": output.current, "generation": output.generation, "applicabilityRevision": output.applicabilityRevision,
         "transition": output.transition, "expiryReasons": output.expiryReasons,
         "rejection": output.rejection as Any? ?? NSNull()]
    }
}

/// Adapter for already interpreted inputs; contains no image/lane classification.
/// Owned by the drive controller's main actor. Clock is monotonic system uptime.
final class SpeedReferenceRuntime {
    private(set) var machine: SpeedReferenceMachine?
    private var session = UUID().uuidString
    private var sequence = 0
    private let now: () -> Double
    private var origin = 0.0
    private var meters = 0.0
    private var withdrawnCameraEvidence = Set<String>()
    private var cameraOrigins: [String: (Double, Double)] = [:]
    private var cachedBundleApplicability: [String:Any]?
    private var way: String?
    private var road: String?
    private var relations = Set<String>()
    private var direction = "unknown"
    private var acceptedDirections: [String: String] = [:]
    private var directionOrder: [String] = []
    private struct Departure {
        var way: String
        var road: String?
        var relations: Set<String>
        var direction: String
        let startedAt: Double
        let reason: String
        var verifiedFixCount = 0
        var lastVerifiedFixTime: Double?

        func continues(way nextWay: String, road nextRoad: String?, relations nextRelations: Set<String>, direction nextDirection: String) -> Bool {
            // Forward/reverse describe an OSM way's digitization, not the road's
            // travel direction. Adjacent ways can have opposite digitization.
            let reversed = way == nextWay && direction != "unknown" && nextDirection != "unknown" && direction != nextDirection
            return !reversed && (way == nextWay || (road != nil && road == nextRoad) || !relations.intersection(nextRelations).isEmpty)
        }

        mutating func observe(way nextWay: String, road nextRoad: String?, relations nextRelations: Set<String>, direction nextDirection: String) {
            if way != nextWay || nextDirection != "unknown" { direction = nextDirection }
            way = nextWay; road = nextRoad; relations = nextRelations
        }
    }
    private var departure: Departure?
    private(set) var lastEventReason = ""
    var elapsedSeconds: Double { machine?.time ?? 0 }
    var traveledMeters: Double { machine?.distance ?? 0 }
    var onTransition: ((SpeedReferenceOutput) -> Void)?
    init(model: SpeedLimitReferenceModel? = try? SpeedLimitReferenceModel.bundled(), now: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) { self.now = now; machine = model.map(SpeedReferenceMachine.init); reset() }
    func reset() {
        session = UUID().uuidString; sequence = 0; origin = now(); meters = 0
        withdrawnCameraEvidence = []
        cameraOrigins = [:]; cachedBundleApplicability = nil; way = nil; road = nil; relations = []; departure = nil; direction = "unknown"; acceptedDirections = [:]; directionOrder = []
        _ = send("reset")
    }
    var output: SpeedReferenceOutput? { machine?.project() }
    var cameraEvidenceIDs: [String] { ["camera", "camera_context"].compactMap { machine?.claims[$0]?.id } }
    var voice: SpeedReferenceValue? { machine?.claims["voice"]?.value }
    var policyIdentity: String { machine.map { "\($0.model.version):\($0.model.sha256)" } ?? "invalid_policy" }
    @discardableResult private func send(_ kind: String, _ fields: [String: Any] = [:]) -> SpeedReferenceOutput? {
        guard let machine else { return nil }
        sequence += 1
        var event: [String: Any] = ["kind": kind, "session_id": session, "sequence": sequence,
            "elapsed_s": kind == "reset" ? 0 : max(machine.time, now() - origin),
            "distance_m": meters, "generation": machine.generation]
        fields.forEach { event[$0.key] = $0.value }
        lastEventReason = fields["reason"] as? String ?? kind
        let before = machine.project()
        let result = machine.step(event)
        if before.state != result.state || before.value != result.value || before.evidenceID != result.evidenceID || !result.expiryReasons.isEmpty || result.transition == "T08" { onTransition?(result) }
        return result
    }
    func tick(distance: Double = 0) { if distance.isFinite && distance >= 0 { meters += distance }; _ = send("tick") }
    private var applicability: [String: Any] { ["status": "applicable", "context_revision": machine?.applicabilityRevision ?? 0, "conditions": [Any]()] }
    func voice(id: String, value: SpeedReferenceValue) { tick(); _ = send("voice", ["id": id, "value": value.json, "verified": true]) }
    func bundle(id: String, value: SpeedReferenceValue?, applicability evaluated: [String: Any]? = nil) {
        if let value {
            cachedBundleApplicability = evaluated
            _ = send("bundle",["id":id,"value":value.json,"verified":true,"applicability":evaluated ?? applicability])
        } else { cachedBundleApplicability = nil; _ = send("bundle_missing") }
    }
    @discardableResult
    func camera(id: String, value: SpeedReferenceValue, enclosing: Bool = false, applicability evaluated: [String: Any]? = nil) -> SpeedReferenceCameraReceipt? {
        tick()
        let first = cameraOrigins[id] ?? (machine?.time ?? 0, meters)
        cameraOrigins[id] = first
        // Capture after the existing tick, immediately before the unchanged offer.
        let before = machine?.project()
        let pendingBefore = machine?.pendingContext
        let kind = enclosing ? "camera_context" : "camera"
        let after = send(kind, ["id": id, "value": value.json,
            "verified": true, "applicability": evaluated ?? applicability, "observed_elapsed_s": first.0,
            "observed_distance_m": first.1, "area_verified": enclosing, "scope_kind": "zone"])
        guard let before, let after, let pendingBefore, let machine else { return nil }
        return SpeedReferenceCameraReceipt(offeredID: id, offeredValue: value, offeredKind: kind,
            before: before, after: after, pendingContextBefore: pendingBefore, pendingContextAfter: machine.pendingContext)
    }
    /// Source-specific opt-in; existing producer calls keep their old semantics.
    func preserveObservedCameraOrigin(id: String, elapsed: Double, distance: Double) {
        tick()
        guard elapsed.isFinite, distance.isFinite, elapsed >= 0, distance >= 0,
              elapsed <= elapsedSeconds, distance <= traveledMeters, cameraOrigins[id] == nil else { return }
        cameraOrigins[id] = (elapsed,distance)
    }
    /// Re-evaluate through existing T14, retaining independent current producer
    /// claims under their original IDs/ordinary evidence origins. No policy edit.
    @discardableResult
    func reevaluateObservedCamera(parentID: String, value: SpeedReferenceValue?,
                                  observedElapsedSeconds: Double, observedDistanceMeters: Double,
                                  evaluatedConditions: [String: Any] = [:]) -> SpeedReferenceCameraReceipt? {
        tick()
        // Voice explicitly clears camera authority under the existing policy;
        // never cache it for resurrection after that correction expires.
        guard voice == nil else { return nil }
        let owned = cameraEvidenceIDs.contains(parentID)
        guard value != nil || owned else { return nil }
        let other = machine?.claims.filter { key, claim in
            ["camera", "camera_context", "bundle"].contains(key) && claim.id != parentID
        } ?? [:]
        applicabilityContextChanged(revision: (machine?.applicabilityRevision ?? 0)+1)
        if let bundle = other["bundle"] {
            var evaluated = cachedBundleApplicability
            evaluated?["context_revision"] = machine?.applicabilityRevision ?? 0
            self.bundle(id:bundle.id,value:bundle.value,applicability:evaluated)
        }
        if let enclosing = other["camera_context"] { _ = camera(id: enclosing.id, value: enclosing.value, enclosing: true) }
        if let ordinary = other["camera"] {
            preserveObservedCameraOrigin(id: ordinary.id, elapsed: ordinary.time, distance: ordinary.distance)
            _ = camera(id: ordinary.id, value: ordinary.value)
        }
        guard let value else { return nil }
        preserveObservedCameraOrigin(id: parentID, elapsed: observedElapsedSeconds, distance: observedDistanceMeters)
        return camera(id: parentID, value: value, applicability:["status":"applicable",
            "context_revision":machine?.applicabilityRevision ?? 0,"conditions":evaluatedConditions])
    }
#if DEBUG
    var testBundleApplicability: [String:Any]? { cachedBundleApplicability }
#endif
    func applicabilityContextChanged(revision: Int) { _ = send("applicability_context_changed", ["next_revision": revision]) }
    func pipelineAuthorityWithdrawn(evidenceID: String) {
        guard withdrawnCameraEvidence.insert(evidenceID).inserted else { return }
        _ = send("camera_scope_invalidated")
    }
    func dismissCamera() { _ = send("camera_dismissed") }
    func boundary(_ reason: String) {
        tick(); _ = send("context_confirmed", ["id": UUID().uuidString, "confirmed": true, "reason": reason]); departure = nil
        acceptedDirections = [:]; directionOrder = []
    }
    func context(way nextWay: String?, road nextRoad: String?, relations nextRelations: Set<String>, direction nextDirection: String, stable: Bool, bundleFix: SpeedReferenceBundleFix? = nil) {
        tick()
        guard let nextWay, !nextWay.isEmpty else {
            departure?.verifiedFixCount=0; departure?.lastVerifiedFixTime=nil
            _ = send("context_missing"); return
        }
        var acceptedDirection = nextDirection
        let comparisonDirection = nextDirection == "unknown" && departure?.way == nextWay
            ? departure?.direction ?? nextDirection : nextDirection
        // Compare revisited ways in their own digitization, across intervening
        // segments and brief side-road excursions. Never compare raw forward/
        // reverse values belonging to different OSM ways.
        let originalDirection = acceptedDirections[nextWay] ?? (way == nextWay ? direction : "unknown")
        let reversed = originalDirection != "unknown" && comparisonDirection != "unknown" && originalDirection != comparisonDirection
        let returningOriginalDirection = originalDirection != "unknown" && nextDirection == originalDirection
        let pendingReversal = departure?.reason == "direction_reversal" && !returningOriginalDirection
        let continues = !reversed && !pendingReversal && (way == nil || way == nextWay || (road != nil && road == nextRoad) || !relations.intersection(nextRelations).isEmpty)
        if continues {
            _ = send("context_restored", ["verified": true]); departure = nil
        } else {
            if departure?.continues(way: nextWay, road: nextRoad, relations: nextRelations, direction: nextDirection) != true {
                departure = Departure(way: nextWay, road: nextRoad, relations: nextRelations, direction: nextDirection,
                    startedAt: machine?.time ?? 0, reason: reversed ? "direction_reversal" : "road_relation_exit")
            } else {
                departure?.observe(way: nextWay, road: nextRoad, relations: nextRelations, direction: nextDirection)
            }
            _ = send("context_pending")
            guard let machine else { return }
            if stable, let fix=bundleFix, fix.applicable,
               fix.sourceTime.isFinite, fix.sourceTime >= 0,
               fix.ageSeconds.isFinite, (0...machine.limit("verified_bundle_max_fix_age_s")).contains(fix.ageSeconds),
               fix.accuracyMetres.isFinite, (0...machine.limit("verified_bundle_max_accuracy_m")).contains(fix.accuracyMetres),
               fix.matchDistanceMetres.isFinite, (0...machine.limit("verified_bundle_max_match_distance_m")).contains(fix.matchDistanceMetres) {
                let last=departure?.lastVerifiedFixTime
                if last == nil || fix.sourceTime > last! {
                    let nextCount = last.map { fix.sourceTime-$0 <= machine.limit("verified_bundle_max_fix_gap_s") } == true ? (departure?.verifiedFixCount ?? 0)+1 : 1
                    departure?.verifiedFixCount = nextCount
                    departure?.lastVerifiedFixTime=fix.sourceTime
                }
            } else { departure?.verifiedFixCount=0; departure?.lastVerifiedFixTime=nil }
            guard stable, let departure else { return }
            let verifiedBundle = departure.reason == "road_relation_exit"
                && Double(departure.verifiedFixCount) >= machine.limit("verified_bundle_confirmation_fixes")
            guard verifiedBundle || machine.time-departure.startedAt >= machine.limit("road_departure_confirmation_s") else { return }
            guard departure.reason != "direction_reversal" || nextDirection != "unknown" else { return }
            acceptedDirection = departure.direction
            boundary(departure.reason)
        }
        if way != nextWay || acceptedDirection != "unknown" { direction = acceptedDirection }
        way = nextWay; road = nextRoad; relations = nextRelations
        if stable && acceptedDirection != "unknown" {
            if acceptedDirections[nextWay] == nil { directionOrder.append(nextWay) }
            acceptedDirections[nextWay] = acceptedDirection
            if directionOrder.count > 128 { acceptedDirections.removeValue(forKey: directionOrder.removeFirst()) }
        }
    }
}

extension SpeedReferenceValue {
    init?(_ value: EffectiveSpeedLimitValue) {
        switch value {
        case .numeric(let kmh): self.init(kind: "numeric", kmh: kmh)
        case .walk: self.init(kind: "walk")
        case .unlimited: self.init(kind: "unlimited")
        case .unknown: return nil
        }
    }
    var effectiveValue: EffectiveSpeedLimitValue {
        switch kind { case "numeric": return .numeric(kmh!); case "walk": return .walk; case "unlimited": return .unlimited; default: return .unknown }
    }
}
extension SpeedReferenceOutput {
    var effectiveState: EffectiveSpeedLimitState {
        let selectedSource: EffectiveSpeedLimitSource
        switch state { case "VOICE": selectedSource = .localCorrection; case "CAMERA": selectedSource = .camera; case "BUNDLE": selectedSource = .bundle; case "LAST_KNOWN": selectedSource = .lastKnown; default: selectedSource = .none }
        return EffectiveSpeedLimitState(value: value?.effectiveValue ?? .unknown, source: selectedSource,
            presentationReason: "reference_\(state.lowercased())_\(transition)", hasCameraEvidenceMarker: state == "CAMERA", isUserCorrection: state == "VOICE")
    }
}

/// Reject delayed frames and passages belonging to evidence the driver dismissed.
/// Track IDs stay suppressed for the session; a new sign can still be recognized.
struct VisionDismissalGate {
    private var cutoff: Date?
    private var tracks = Set<String>()
    mutating func dismiss(at time: Date, tracks ids: [String]) {
        cutoff = time
        tracks.formUnion(ids)
    }
    mutating func permits(track: String?, observedAt: Date) -> Bool {
        if let cutoff, observedAt <= cutoff {
            if let track { tracks.insert(track) }
            return false
        }
        return track.map { !tracks.contains($0) } ?? true
    }
}

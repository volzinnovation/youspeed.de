import Foundation

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
    private var way: String?
    private var road: String?
    private var relations = Set<String>()
    private var direction = "unknown"
    private var departure: (String, Double)?
    private(set) var lastEventReason = ""
    var elapsedSeconds: Double { machine?.time ?? 0 }
    var traveledMeters: Double { machine?.distance ?? 0 }
    var onTransition: ((SpeedReferenceOutput) -> Void)?
    init(model: SpeedLimitReferenceModel? = try? SpeedLimitReferenceModel.bundled(), now: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) { self.now = now; machine = model.map(SpeedReferenceMachine.init); reset() }
    func reset() {
        session = UUID().uuidString; sequence = 0; origin = now(); meters = 0
        withdrawnCameraEvidence = []
        cameraOrigins = [:]; way = nil; road = nil; relations = []; departure = nil; direction = "unknown"
        _ = send("reset")
    }
    var output: SpeedReferenceOutput? { machine?.project() }
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
        if let value { _ = send("bundle", ["id": id, "value": value.json, "verified": true, "applicability": evaluated ?? applicability]) }
        else { _ = send("bundle_missing") }
    }
    func camera(id: String, value: SpeedReferenceValue, enclosing: Bool = false, applicability evaluated: [String: Any]? = nil) {
        tick()
        let first = cameraOrigins[id] ?? (machine?.time ?? 0, meters)
        cameraOrigins[id] = first
        _ = send(enclosing ? "camera_context" : "camera", ["id": id, "value": value.json,
            "verified": true, "applicability": evaluated ?? applicability, "observed_elapsed_s": first.0,
            "observed_distance_m": first.1, "area_verified": enclosing, "scope_kind": "zone"])
    }
    func applicabilityContextChanged(revision: Int) { _ = send("applicability_context_changed", ["next_revision": revision]) }
    func pipelineAuthorityWithdrawn(evidenceID: String) {
        guard withdrawnCameraEvidence.insert(evidenceID).inserted else { return }
        _ = send("camera_scope_invalidated")
    }
    func dismissCamera() { _ = send("camera_dismissed") }
    func boundary(_ reason: String) {
        tick(); _ = send("context_confirmed", ["id": UUID().uuidString, "confirmed": true, "reason": reason]); departure = nil
    }
    func context(way nextWay: String?, road nextRoad: String?, relations nextRelations: Set<String>, direction nextDirection: String, stable: Bool) {
        tick()
        guard let nextWay, !nextWay.isEmpty else { _ = send("context_missing"); return }
        let reversed = way == nextWay && direction != "unknown" && nextDirection != "unknown" && direction != nextDirection
        let continues = !reversed && (way == nil || way == nextWay || (road != nil && road == nextRoad) || !relations.intersection(nextRelations).isEmpty)
        if continues {
            _ = send("context_restored", ["verified": true]); departure = nil
        } else {
            let candidate = "\(nextRoad ?? nextWay)|\(nextDirection)"
            if departure?.0 != candidate { departure = (candidate, machine?.time ?? 0) }
            _ = send("context_pending")
            guard stable, let departure, let machine, machine.time - departure.1 >= machine.limit("road_departure_confirmation_s") else { return }
            boundary(reversed ? "direction_reversal" : "road_relation_exit")
        }
        way = nextWay; road = nextRoad; relations = nextRelations; direction = nextDirection
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

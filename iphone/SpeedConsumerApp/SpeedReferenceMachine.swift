import Foundation
import CoreFoundation

struct SpeedReferenceValue: Equatable {
    let kind: String
    let kmh: Int?
    init(kind: String, kmh: Int? = nil) { self.kind = kind; self.kmh = kmh }
    var json: [String: Any] { kind == "numeric" ? ["kind": kind, "kmh": kmh!] : ["kind": kind] }
}
struct SpeedReferenceOutput {
    let state: String
    let value: SpeedReferenceValue?
    let source: String?
    let evidenceID: String?
    let current: Bool
    let generation: Int
    let applicabilityRevision: Int
    let transition: String
    let expiryReasons: [String]
    let rejection: String?
    var baselineKmh: Int? { current && value?.kind == "numeric" ? value?.kmh : nil }
}

/// Deterministic EFSM interpreter. Guard/action names are versioned vocabulary;
/// transition order, source selection and lifetime limits come from the artifact.
final class SpeedReferenceMachine {
    struct Claim {
        let id: String
        let value: SpeedReferenceValue
        let source: String
        let time: Double
        let distance: Double
    }
    let model: SpeedLimitReferenceModel
    private(set) var claims: [String: Claim] = [:]
    private var lastKnown: Claim?
    private(set) var generation = 0
    private(set) var applicabilityRevision = 0
    private var pending = false
    private var gap: (Double, Double)?
    private var seen = Set<String>()
    private var origins: [String: [Double]] = [:]
    private var session: String?
    private var sequence = -1
    private(set) var time = 0.0
    private(set) var distance = 0.0
    var pendingContext: Bool { pending }
    init(model: SpeedLimitReferenceModel) { self.model = model }
    func limit(_ name: String) -> Double { (model.policy["limits"] as! [String: NSNumber])[name]!.doubleValue }
    private func number(_ x: Any?) -> Double? {
        guard let n = x as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite, n.doubleValue >= 0 else { return nil }; return n.doubleValue
    }
    private func integer(_ x: Any?) -> Int? { guard let n = number(x), n.rounded() == n, n < Double(Int.max) else { return nil }; return Int(n) }
    private func yes(_ x: Any?) -> Bool { guard let n = x as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return false }; return n.boolValue }
    private func value(_ e: [String: Any]) -> SpeedReferenceValue? {
        guard let v = e["value"] as? [String: Any], let kind = v["kind"] as? String else { return nil }
        if ["walk", "unlimited"].contains(kind), v.count == 1 { return SpeedReferenceValue(kind: kind) }
        let domain = model.policy["value_domain"] as! [String: Any]
        if kind == "numeric", v.count == 2, let kmh = integer(v["kmh"]), kmh >= domain["numeric_min_kmh"] as! Int, kmh <= domain["numeric_max_kmh"] as! Int { return SpeedReferenceValue(kind: kind, kmh: kmh) }
        return nil
    }
    private func key(_ e: [String: Any]) -> String {
        let kind = e["kind"] as! String
        let revision = ["camera", "camera_context"].contains(kind) ? ((e["applicability"] as? [String: Any])?["context_revision"] as? Int).map(String.init) ?? "nil" : "nil"
        return "\(kind)|\(e["id"] as? String ?? "")|\(revision)"
    }
    private func applicable(_ e: [String: Any]) -> Bool {
        let a = e["applicability"] as? [String: Any] ?? [:]
        return a["status"] as? String == "applicable" && integer(a["context_revision"]) == applicabilityRevision
    }
    private func validate(_ e: [String: Any]) -> String? {
        guard let kind = e["kind"] as? String, (model.policy["events"] as! [String: Any])[kind] != nil else { return "unknown_event" }
        guard let s = e["session_id"] as? String, !s.isEmpty else { return "invalid_session" }
        guard let seq = integer(e["sequence"]) else { return "invalid_sequence" }
        guard let t = number(e["elapsed_s"]), let d = number(e["distance_m"]) else { return "invalid_progress" }
        if kind == "reset" { return s == session ? "duplicate_session" : (t != 0 || d != 0 ? "invalid_session_origin" : nil) }
        guard s == session else { return "wrong_session" }
        guard seq > sequence else { return "out_of_order" }
        guard t >= time, d >= distance else { return "non_monotonic_progress" }
        if kind != "tick", integer(e["generation"]) == nil { return "invalid_generation" }
        if ["voice", "camera", "camera_context", "bundle", "context_confirmed"].contains(kind), (e["id"] as? String)?.isEmpty != false { return "missing_evidence_id" }
        if ["voice", "camera", "camera_context", "bundle"].contains(kind), value(e) == nil { return "invalid_value" }
        if ["camera", "camera_context", "bundle"].contains(kind) {
            guard let a = e["applicability"] as? [String: Any], ["applicable", "inapplicable", "unresolved"].contains(a["status"] as? String ?? ""), integer(a["context_revision"]) != nil, a["conditions"] is [Any] || a["conditions"] is [String: Any] else { return "invalid_applicability_envelope" }
        }
        if kind == "camera" {
            guard let t0 = number(e["observed_elapsed_s"]), let d0 = number(e["observed_distance_m"]), t0 <= t, d0 <= d else { return "invalid_evidence_origin" }
            if let previous = origins[e["id"] as! String], previous != [t0, d0] { return "changed_evidence_origin" }
        }
        return nil
    }
    private func guardPasses(_ name: String, _ e: [String: Any]) -> Bool {
        let scoped = integer(e["generation"]) == generation
        let fresh = scoped && !seen.contains(key(e))
        switch name {
        case "always", "new_session": return true
        case "current_generation": return scoped
        case "verified_current_generation": return scoped && yes(e["verified"])
        case "fresh_scoped_evidence": return fresh && yes(e["verified"])
        case "fresh_applicable_pipeline_output":
            let ordinary = e["kind"] as? String == "camera"
            let alive = !ordinary || (time - (number(e["observed_elapsed_s"]) ?? 0) < limit("ordinary_max_age_s") && distance - (number(e["observed_distance_m"]) ?? 0) < limit("ordinary_max_distance_m"))
            return fresh && yes(e["verified"]) && claims["voice"] == nil && !pending && gap == nil && applicable(e) && alive
        case "verified_enclosing_camera": return guardPasses("fresh_applicable_pipeline_output", e) && yes(e["area_verified"]) && ["zone", "city"].contains(e["scope_kind"] as? String ?? "")
        case "current_verified_bundle": return scoped && yes(e["verified"]) && !pending && gap == nil && applicable(e)
        case "fresh_confirmed_boundary": return fresh && yes(e["confirmed"]) && (model.policy["boundary_reasons"] as! [String]).contains(e["reason"] as? String ?? "")
        case "new_applicability_revision": return scoped && (integer(e["next_revision"]) ?? -1) > applicabilityRevision
        default: preconditionFailure("Unsupported policy guard \(name)")
        }
    }
    private func action(_ name: String, _ e: [String: Any]) {
        if name.hasPrefix("accept_") {
            let source = String(name.dropFirst(7))
            claims[source] = Claim(id: e["id"] as! String, value: value(e)!, source: source == "camera_context" ? "camera" : source,
                time: source == "camera" ? number(e["observed_elapsed_s"])! : time, distance: source == "camera" ? number(e["observed_distance_m"])! : distance)
            return
        }
        if ["clear_voice", "clear_camera", "clear_camera_context", "clear_bundle"].contains(name) { claims.removeValue(forKey: String(name.dropFirst(6))); return }
        switch name {
        case "reset_session": claims = [:]; lastKnown = nil; generation = 0; applicabilityRevision = 0; pending = false; gap = nil; seen = []; origins = [:]; time = 0; distance = 0; session = e["session_id"] as? String; sequence = integer(e["sequence"])!
        case "advance_generation": generation += 1
        case "advance_applicability_revision": applicabilityRevision = integer(e["next_revision"])!
        case "mark_pending": pending = true
        case "clear_pending": pending = false
        case "start_gap_once": if gap == nil { gap = (time, distance) }
        case "clear_gap": gap = nil
        default: preconditionFailure("Unsupported policy action \(name)")
        }
    }
    func project(transition: String = "T10", expiry: [String] = [], rejection: String? = nil) -> SpeedReferenceOutput {
        for row in model.policy["selection"] as! [[String: Any]] {
            let name = row["register"] as? String
            let claim = name == "last_known" ? lastKnown : name.flatMap { claims[$0] }
            if name != nil && claim == nil { continue }
            let current = row["current"] as! Bool
            if current { lastKnown = claim }
            return SpeedReferenceOutput(state: row["state"] as! String, value: claim?.value, source: claim?.source, evidenceID: claim?.id, current: current, generation: generation, applicabilityRevision: applicabilityRevision, transition: transition, expiryReasons: expiry, rejection: rejection)
        }
        preconditionFailure("Missing policy selection fallback")
    }
    @discardableResult func step(_ e: [String: Any]) -> SpeedReferenceOutput {
        if let error = validate(e) { return project(transition: "REJECT", rejection: error) }
        let kind = e["kind"] as! String
        var reasons: [String] = []
        if kind != "reset" {
            time = number(e["elapsed_s"])!; distance = number(e["distance_m"])!; sequence = integer(e["sequence"])!
            for rule in model.policy["expiry"] as! [[String: Any]] {
                for source in rule["sources"] as! [String] {
                    guard let claim = claims[source] else { continue }
                    let delta = rule["metric"] as? String == "elapsed_s" ? time - claim.time : distance - claim.distance
                    if delta >= limit(rule["limit"] as! String) { claims.removeValue(forKey: source); reasons.append("\(source):\(rule["id"] as! String)") }
                }
            }
            if let gap, time - gap.0 >= limit("context_gap_max_age_s") || distance - gap.1 >= limit("context_gap_max_distance_m") {
                for source in ["voice", "camera", "bundle", "camera_context"] where claims[source] != nil { claims.removeValue(forKey: source); reasons.append("\(source):context_gap") }
            }
        }
        for row in model.policy["transitions"] as! [[String: Any]] {
            guard [kind, "*"].contains(row["on"] as! String), guardPasses(row["guard"] as! String, e) else { continue }
            for name in row["actions"] as! [String] { action(name, e) }
            if ["voice", "camera", "camera_context", "context_confirmed"].contains(kind) { seen.insert(key(e)) }
            if kind == "camera" { origins[e["id"] as! String] = [number(e["observed_elapsed_s"])!, number(e["observed_distance_m"])!] }
            return project(transition: row["id"] as! String, expiry: reasons)
        }
        preconditionFailure("Incomplete policy transition table")
    }
}

import Foundation
import CoreFoundation

/// The JSON Schema subset emitted by the pinned Pydantic wire models. Unknown
/// keywords affecting validation are rejected by the repository contract check.
struct SignCollectionSchema {
    static func validate(_ value: Any, schema: [String: Any], root: [String: Any]) throws {
        func invalid() throws -> Never { throw SignCollectionError.invalidContract }
        if let ref = schema["$ref"] as? String {
            guard ref.hasPrefix("#/$defs/"), let defs = root["$defs"] as? [String: Any], let target = defs[String(ref.dropFirst(8))] as? [String: Any] else { try invalid() }
            try validate(value, schema: target, root: root); return
        }
        if let branches = schema["anyOf"] as? [[String: Any]] {
            guard branches.contains(where: { (try? validate(value, schema: $0, root: root)) != nil }) else { try invalid() }; return
        }
        if let expected = schema["const"], try SignCollectionJSON.canonical(value) != SignCollectionJSON.canonical(expected) { try invalid() }
        if let choices = schema["enum"] as? [Any], !choices.contains(where: { (try? SignCollectionJSON.canonical($0)) == (try? SignCollectionJSON.canonical(value)) }) { try invalid() }
        switch schema["type"] as? String {
        case "null": guard value is NSNull else { try invalid() }
        case "boolean": guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { try invalid() }
        case "integer", "number":
            guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite else { try invalid() }
            let d = n.doubleValue
            if schema["type"] as? String == "integer", ["f", "d"].contains(String(cString: n.objCType)) { try invalid() }
            if let min = schema["minimum"] as? Double, d < min { try invalid() }
            if let max = schema["maximum"] as? Double, d > max { try invalid() }
            if let min = schema["exclusiveMinimum"] as? Double, d <= min { try invalid() }
            if let max = schema["exclusiveMaximum"] as? Double, d >= max { try invalid() }
        case "string":
            guard let s = value as? String else { try invalid() }
            if let min = schema["minLength"] as? Int, s.unicodeScalars.count < min { try invalid() }
            if let max = schema["maxLength"] as? Int, s.unicodeScalars.count > max { try invalid() }
            if let pattern = schema["pattern"] as? String, try NSRegularExpression(pattern: pattern).firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) == nil { try invalid() }
            if schema["format"] as? String == "date-time" {
                let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                let parsed = f.date(from: s); f.formatOptions = [.withInternetDateTime]
                guard parsed != nil || f.date(from: s) != nil, s.hasSuffix("Z") || s.hasSuffix("+00:00") else { try invalid() }
            }
        case "array":
            guard let a = value as? [Any] else { try invalid() }
            if let min = schema["minItems"] as? Int, a.count < min { try invalid() }
            if let max = schema["maxItems"] as? Int, a.count > max { try invalid() }
            if let items = schema["items"] as? [String: Any] { for child in a { try validate(child, schema: items, root: root) } }
        case "object":
            guard let o = value as? [String: Any] else { try invalid() }
            let properties = schema["properties"] as? [String: [String: Any]] ?? [:]
            guard (schema["required"] as? [String] ?? []).allSatisfy({ o[$0] != nil }) else { try invalid() }
            for (key, child) in o {
                if let property = properties[key] { try validate(child, schema: property, root: root) }
                else if schema["additionalProperties"] as? Bool == false { try invalid() }
            }
        case nil: break // Arbitrary event objects are checked against the event model.
        default: try invalid()
        }
    }
}

extension SignCollectionSchema {
    static func semantics(_ value: Any, model: String) throws {
        guard let o = value as? [String: Any] else { throw SignCollectionError.invalidContract }
        for key in ["event_id", "installation_id", "batch_id", "collection_session_id", "crop_id", "observation_id", "deletion_request_id", "target_id", "superseded_by"] {
            if let id = o[key], !(id is NSNull) { guard let s = id as? String, SignCollectionJSON.isUUID(s) else { throw SignCollectionError.invalidContract } }
        }
        for id in o["media_refs"] as? [String] ?? [] { guard SignCollectionJSON.isUUID(id) else { throw SignCollectionError.invalidContract } }
        if model == "sighting" {
            func date(_ key: String) throws -> Date {
                let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                let text = o[key] as! String; let fractional = f.date(from: text); f.formatOptions = [.withInternetDateTime]
                guard let date = fractional ?? f.date(from: text) else { throw SignCollectionError.invalidContract }; return date
            }
            guard try date("first_seen_at") <= date("representative_frame_at"), try date("representative_frame_at") <= date("last_seen_at") else { throw SignCollectionError.invalidContract }
            let scores = o["scores"] as! [String: Any]
            if o["source_kind"] as? String == "manual_capture" {
                guard o["model"] is NSNull, ["detector_raw", "classifier_raw", "calibrated_confidence"].allSatisfy({ scores[$0] is NSNull }) else { throw SignCollectionError.invalidContract }
            } else { guard !(o["model"] is NSNull) else { throw SignCollectionError.invalidContract } }
            if !(scores["calibrated_confidence"] is NSNull), scores["calibration_id"] as? String == nil || scores["calibration_sha256"] as? String == nil { throw SignCollectionError.invalidContract }
        }
        if model == "correction", o["intent"] as? String == "retract_correction", o["target_kind"] as? String != "correction" { throw SignCollectionError.invalidContract }
        if model == "crop" {
            let geometry = try SignCollectionCropGeometry(width: o["source_width"] as! Int, height: o["source_height"] as! Int, box: o["supplied_box"] as! [String: Double])
            for (key, expected) in geometry.wire { guard let actual = o[key], try SignCollectionJSON.canonical(expected) == SignCollectionJSON.canonical(actual) else { throw SignCollectionError.invalidContract } }
            guard o["decoded_width"] as? Int == geometry.actual[2]-geometry.actual[0], o["decoded_height"] as? Int == geometry.actual[3]-geometry.actual[1],
                   !(o["source_upright_sha256"] is NSNull) || !(o["local_frame_token"] as? String ?? "").isEmpty else { throw SignCollectionError.invalidContract }
        }
        if model == "batch" {
            let events = o["events"] as! [[String: Any]]; let ids = events.compactMap { $0["event_id"] as? String }
            guard ids.count == events.count, Set(ids).count == ids.count, ids.allSatisfy(SignCollectionJSON.isUUID) else { throw SignCollectionError.invalidContract }
        }
    }
}

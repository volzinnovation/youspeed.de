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
        for key in ["device_id", "event_id", "installation_id", "batch_id", "collection_session_id", "crop_id", "observation_id", "deletion_request_id", "target_id", "superseded_by"] {
            if let id = o[key], !(id is NSNull) { guard let s = id as? String, SignCollectionJSON.isUUID(s) else { throw SignCollectionError.invalidContract } }
        }
        for id in o["media_refs"] as? [String] ?? [] { guard SignCollectionJSON.isUUID(id) else { throw SignCollectionError.invalidContract } }
        try captureMetadata(o, model: model)
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
        func ocrDate(_ value: Any?) -> Date? {
            guard let text = value as? String else { return nil }
            let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let value = f.date(from: text) { return value }
            f.formatOptions = [.withInternetDateTime]; return f.date(from: text)
        }
        if let annotation = o["supplementary_ocr"] as? [String: Any] {
            guard let observed = ocrDate(annotation["observed_at"]),
                  let first = ocrDate(annotation["first_seen_at"]), first <= observed,
                  annotation["status"] as? String != "read" || annotation["raw_text"] is String else { throw SignCollectionError.invalidContract }
        }
        if model == "media-status" {
            let ocr = o["status"] as? String == "supplementary_ocr_observed"
            if ocr {
                guard o["crop_id"] is NSNull, o["superseded_by"] == nil || o["superseded_by"] is NSNull,
                      let annotation = o["supplementary_ocr"] as? [String: Any], o["ocr_attempt_id"] is String,
                      let status = o["association_status"] as? String, ["exact", "unresolved"].contains(status),
                      (o["observation_id"] is String) == (status == "exact"),
                      let created = ocrDate(o["created_at"]),
                      let observed = ocrDate(annotation["observed_at"]), created >= observed else { throw SignCollectionError.invalidContract }
            } else {
                guard o["crop_id"] is String,
                      ["supplementary_ocr", "ocr_attempt_id", "association_status"].allSatisfy({ o[$0] == nil || o[$0] is NSNull }) else { throw SignCollectionError.invalidContract }
            }
        }
        if model == "correction", o["intent"] as? String == "retract_correction", o["target_kind"] as? String != "correction" { throw SignCollectionError.invalidContract }
        if model == "crop" {
            let geometry = try SignCollectionCropGeometry(width: o["source_width"] as! Int, height: o["source_height"] as! Int, box: o["supplied_box"] as! [String: Double])
            for (key, expected) in geometry.wire { guard let actual = o[key], try SignCollectionJSON.canonical(expected) == SignCollectionJSON.canonical(actual) else { throw SignCollectionError.invalidContract } }
            guard o["decoded_width"] as? Int == geometry.actual[2]-geometry.actual[0], o["decoded_height"] as? Int == geometry.actual[3]-geometry.actual[1],
                   !(o["source_upright_sha256"] is NSNull) || !(o["local_frame_token"] as? String ?? "").isEmpty else { throw SignCollectionError.invalidContract }
        }
        if model == "batch" {
            let events = o["events"] as! [[String: Any]]
            guard events.allSatisfy({ $0["device_id"] == nil || $0["device_id"] is NSNull || $0["device_id"] as? String == o["installation_id"] as? String }) else { throw SignCollectionError.invalidContract }
            let ids = events.compactMap { $0["event_id"] as? String }
            guard ids.count == events.count, Set(ids).count == ids.count, ids.allSatisfy(SignCollectionJSON.isUUID) else { throw SignCollectionError.invalidContract }
        }
    }
}


extension SignCollectionSchema {
    static func captureMetadata(_ o: [String: Any], model: String) throws {
        guard ["sighting", "crop"].contains(model) else { return }
        let keys = ["capture_metadata_version", "device_id", "camera_viewing_direction"]
        guard o["observer_version"] as? String == "sighting-observer-2" ||
                keys.contains(where: { o[$0] != nil && !(o[$0] is NSNull) }) else { return }
        func date(_ v: Any?) -> Date? {
            guard let text = v as? String else { return nil }
            let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let d = f.date(from: text) { return d }
            f.formatOptions = [.withInternetDateTime]; return f.date(from: text)
        }
        guard o["capture_metadata_version"] as? Int == 1,
              let device = o["device_id"] as? String, SignCollectionJSON.isUUID(device),
              model != "crop" || device == o["installation_id"] as? String,
              let frame = date(o[model == "crop" ? "source_frame_at" : "representative_frame_at"]),
              let position = o["vehicle_position"] as? [String: Any],
              let direction = o["camera_viewing_direction"] as? [String: Any] else { throw SignCollectionError.invalidContract }
        for (measurement, timeKey, deltaKey, maximum) in [(position, "fix_at", "frame_fix_delta_ms", 5000.0),
                (direction, "measured_at", "frame_measurement_delta_ms", 500.0)] {
            guard let at = date(measurement[timeKey]), let delta = (measurement[deltaKey] as? NSNumber)?.doubleValue,
                  abs(frame.timeIntervalSince(at)*1000) <= maximum,
                  abs(frame.timeIntervalSince(at)*1000 - delta) <= 2 else { throw SignCollectionError.invalidContract }
        }
    }
}

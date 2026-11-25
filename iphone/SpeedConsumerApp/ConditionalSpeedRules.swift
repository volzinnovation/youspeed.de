import Foundation
import SQLite3

struct ConditionalSpeedPreview: Equatable, Sendable {
    let speedKmh: Int
    let restrictionText: String
    var localizedRestrictionText: String {
        ConditionalSpeedRules.localizedRestrictionText(restrictionText)
    }
}

/// A bundle producer adapter. It does not alter reference-policy priority/expiry.
enum ConditionalSpeedRules {
    static func localizedRestrictionText(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "wet"
            ? NSLocalizedString("limit.condition.wet", comment: "Wet-road conditional limit") : text
    }
    struct Result: Equatable {
        let kmh: Int?
        let unlimited: Bool
        let unresolved: Bool
        let reason: String
        var reevaluation: Reevaluation? = nil
        var inactivePreview: ConditionalSpeedPreview? = nil
        var activeRestrictionText: String? = nil
    }

    struct Reevaluation: Codable, Equatable, Sendable {
        let rulesJSON: String
        let baseKmh: Int?
        let baseUnlimited: Bool
        let direction: Int?
        let countryCode: String?
        var timeZoneID: String? = nil
        var validFromUTC: Double? = nil
        var validUntilUTC: Double? = nil
        var fallbackRulesJSON: String? = nil
        var fallbackUnresolved: Bool? = nil
        var fallbackReason: String? = nil
        // A node amendment can fall through to a time-dependent way rule.
        // Keep that producer context rather than freezing its current scalar.
        var baselineReevaluations: [Reevaluation]? = nil
        var fallbackReevaluations: [Reevaluation]? = nil
        /// Associate the recognized number with this way's rule, without inventing OCR evidence.
        func containsConditionalLimit(_ speedKmh: Int, at: Date, depth: Int = 0) -> Bool {
            guard depth < 8 else { return false }
            let outside = validFromUTC.map { at.timeIntervalSince1970 < $0 } == true
                || validUntilUTC.map { at.timeIntervalSince1970 >= $0 } == true
            if outside, let children = fallbackReevaluations {
                return children.count == 1 && children[0].containsConditionalLimit(speedKmh, at: at, depth: depth + 1)
            }
            guard let json = outside ? fallbackRulesJSON : rulesJSON,
                  let data = json.data(using: .utf8),
                  let rules = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  rules["version"] as? Int == 1, rules["grammar"] as? String == "youspeed-osm-speed-1",
                  let tags = rules["tags"] as? [[String: Any]], tags.count <= 128 else { return false }
            return tags.contains { tag in
                let scoped = tag["direction"] as? Int ?? 0
                guard tag["role"] as? String == "speed", tag["conditional"] as? Bool == true,
                      tag["status"] as? String == "supported",
                      ["all", "vehicle", "motor_vehicle", "motorcar"].contains(tag["vehicle"] as? String ?? ""),
                      scoped == 0 || scoped == direction else { return false }
                return (tag["clauses"] as? [[String: Any]] ?? []).contains { clause in
                    if let condition = clause["condition"] as? [String: Any],
                       excludedByVehicle(condition, facts: drivingFacts) { return false }
                    guard let limit = clause["limit"] as? [String: Any], limit["kind"] as? String == "numeric",
                          let value = limit["kmh"] as? Double, value.isFinite, value > 0, value <= 400 else { return false }
                    return Int(value.rounded()) == speedKmh
                }
            }
        }
        func evaluate(at: Date) -> Result {
            evaluate(at: at, depth: 0)
        }
        private func evaluate(at: Date, depth: Int) -> Result {
            guard depth < 8 else { return unknown("map_amendment_reevaluation_depth") }
            let instant = at.timeIntervalSince1970
            if validFromUTC.map({ instant < $0 }) == true || validUntilUTC.map({ instant >= $0 }) == true {
                if let children = fallbackReevaluations {
                    guard children.count == 1 else { return unknown("corrupt_map_amendment_fallback") }
                    return children[0].evaluate(at: at, depth: depth + 1)
                }
                if let fallbackRulesJSON {
                    guard let data = fallbackRulesJSON.data(using: .utf8),
                          let rules = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                        return unknown("corrupt_fallback_rule_set")
                    }
                    return ConditionalSpeedRules.evaluate(rules, context: Context(at: at, timeZoneID: timeZoneID,
                        countryCode: countryCode, direction: direction, facts: drivingFacts), baseKmh: baseKmh, baseUnlimited: baseUnlimited)
                }
                if fallbackUnresolved == true { return unknown(fallbackReason ?? "map_amendment_baseline_unresolved") }
                return Result(kmh: baseKmh, unlimited: baseUnlimited, unresolved: false, reason: "map_amendment_outside_validity")
            }
            guard let data = rulesJSON.data(using: .utf8), let rules = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return unknown("corrupt_rule_set") }
            var effectiveBase = baseKmh
            var effectiveUnlimited = baseUnlimited
            if let children = baselineReevaluations {
                guard children.count == 1 else { return unknown("corrupt_map_amendment_baseline") }
                let baseline = children[0].evaluate(at: at, depth: depth + 1)
                if ["map_amendment_reevaluation_depth", "corrupt_map_amendment_baseline", "corrupt_map_amendment_fallback"].contains(baseline.reason) { return baseline }
                effectiveBase = baseline.unresolved ? nil : baseline.kmh
                effectiveUnlimited = !baseline.unresolved && baseline.unlimited
            }
            return ConditionalSpeedRules.evaluate(rules, context: Context(at: at, timeZoneID: timeZoneID, countryCode: countryCode, direction: direction, facts: drivingFacts), baseKmh: effectiveBase, baseUnlimited: effectiveUnlimited)
        }
    }

    struct Context {
        var at = Date()
        var timeZoneID: String?
        var countryCode: String?
        var direction: Int?
        var vehicle = "motorcar"
        var facts: [String: Bool] = [:]
        var clockTrusted = true
    }

    // Product choice while wetness detection is unavailable: retain the independent
    // normal-road reference and expose the wet alternative as a conditional preview.
    static let drivingFacts = ["road_surface_wet": false, "vehicle_hazmat": false,
                               "vehicle_hazmat_water": false, "vehicle_agricultural": false]

    static func isOtherVehicleSpeedKey(_ key: String) -> Bool {
        let parts = key.split(separator: ":")
        guard parts.count > 1, parts[0] == "maxspeed" else { return false }
        return ["hgv", "bus", "motorcycle", "hazmat", "bicycle", "agricultural", "emergency", "taxi", "psv", "foot", "train", "tilting"].contains(parts[1])
    }

    private static func excludedByVehicle(_ condition: [String: Any], facts: [String: Bool], depth: Int = 0) -> Bool {
        guard depth < 20 else { return false }
        switch condition["kind"] as? String {
        case "context":
            guard let field = condition["field"] as? String, field.hasPrefix("vehicle_") else { return false }
            return facts[field] == false
        case "all", "any":
            guard let items = condition["items"] as? [[String: Any]], !items.isEmpty else { return false }
            let excluded = items.map { excludedByVehicle($0, facts: facts, depth: depth + 1) }
            return condition["kind"] as? String == "all" ? excluded.contains(true) : excluded.allSatisfy { $0 }
        default: return false
        }
    }

    static func resolve(db: OpaquePointer, wayID: String, direction: Int?, baseKmh: Int?, baseUnlimited: Bool,
                        at: Date = Date(), timeZoneID: String? = nil, countryCode: String? = nil,
                        amendmentStore: MapDataAmendmentStore? = nil, passedNodeIDs: Set<String> = [],
                        amendmentBaseIdentity: String? = nil) -> Result? {
        let baseline = resolveBundle(db: db, wayID: wayID, direction: direction, baseKmh: baseKmh,
            baseUnlimited: baseUnlimited, at: at, timeZoneID: timeZoneID, countryCode: countryCode)
        guard let generation = amendmentBaseIdentity ?? PackedBundleRuntime.amendmentBaseIdentity(database: db),
              MapDataAmendmentStore.isCanonicalBaseIdentity(generation),
              let store = amendmentStore ?? MapDataAmendmentStore.applicationStore() else { return baseline }
        do {
            guard var result = try store.resolve(wayID: wayID, bundle: generation, direction: direction,
                context: Context(at: at, timeZoneID: timeZoneID, countryCode: countryCode, direction: direction, facts: drivingFacts),
                baseKmh: baseKmh, baseUnlimited: baseUnlimited, passedNodeIDs: passedNodeIDs,
                baselineResult: baseline, sourceWayRulesJSON: baseline?.reevaluation?.rulesJSON) else { return baseline }
            result.reevaluation?.fallbackReevaluations = baseline?.reevaluation.map { [$0] }
            result.reevaluation?.fallbackRulesJSON = baseline?.reevaluation?.rulesJSON
            result.reevaluation?.fallbackUnresolved = baseline?.unresolved
            result.reevaluation?.fallbackReason = baseline?.reason
            return result
        } catch {
            return unknown("map_amendment_store_unavailable")
        }
    }

    private static func resolveBundle(db: OpaquePointer, wayID: String, direction: Int?, baseKmh: Int?, baseUnlimited: Bool,
                        at: Date, timeZoneID: String?, countryCode: String?) -> Result? {
        var capability: OpaquePointer?
        let hasCapability = sqlite3_prepare_v2(db, "SELECT version,grammar FROM road_speed_capability", -1, &capability, nil) == SQLITE_OK
        defer { sqlite3_finalize(capability) }
        if hasCapability {
            guard sqlite3_step(capability) == SQLITE_ROW, sqlite3_column_int(capability, 0) == 1,
                  sqlite3_column_text(capability, 1).map({ String(cString: $0) }) == "youspeed-osm-speed-1",
                  sqlite3_step(capability) == SQLITE_DONE else { return unknown("unsupported_conditional_capability") }
        } else if tableExists(db: db, name: "road_speed_capability") || tableExists(db: db, name: "road_speed_rule_set") {
            return unknown("incomplete_conditional_capability")
        }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT rules_json FROM road_speed_rule_set WHERE way_id=?", -1, &statement, nil) == SQLITE_OK else {
            return hasCapability ? unknown("incomplete_conditional_capability") : legacyUnresolved(db: db, wayID: wayID, direction: direction)
        }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_int64(statement, 1, Int64(wayID) ?? 0)
        guard sqlite3_step(statement) == SQLITE_ROW, let raw = sqlite3_column_text(statement, 0) else { return nil }
        guard let data = String(cString: raw).data(using: .utf8), data.count <= 262_144,
              let rules = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return unknown("corrupt_rule_set") }
        var result = evaluate(rules, context: Context(at: at, timeZoneID: timeZoneID, countryCode: countryCode, direction: direction, facts: drivingFacts), baseKmh: baseKmh, baseUnlimited: baseUnlimited)
        result.reevaluation = Reevaluation(rulesJSON: String(data: data, encoding: .utf8)!, baseKmh: baseKmh, baseUnlimited: baseUnlimited, direction: direction, countryCode: countryCode, timeZoneID: timeZoneID)
        return result
    }

    private static func tableExists(db: OpaquePointer, name: String) -> Bool {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", -1, &statement, nil) == SQLITE_OK else { return false }
        defer { sqlite3_finalize(statement) }
        _ = name.withCString { sqlite3_bind_text(statement, 1, $0, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) }
        return sqlite3_step(statement) == SQLITE_ROW
    }

    private static func legacyUnresolved(db: OpaquePointer, wayID: String, direction: Int?) -> Result? {
        var scalar: OpaquePointer?
        var scalarReady = sqlite3_prepare_v2(db, "SELECT maxspeed,maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=?", -1, &scalar, nil) == SQLITE_OK
        if !scalarReady { sqlite3_finalize(scalar); scalar = nil; scalarReady = sqlite3_prepare_v2(db, "SELECT maxspeed FROM ways WHERE way_id=?", -1, &scalar, nil) == SQLITE_OK }
        if scalarReady {
            sqlite3_bind_int64(scalar, 1, Int64(wayID) ?? 0)
            if sqlite3_step(scalar) == SQLITE_ROW {
                var index: Int32 = 0
                if sqlite3_column_count(scalar) == 3, let direction {
                    let scoped: Int32 = direction == 1 ? 1 : 2
                    if let bytes = sqlite3_column_text(scalar, scoped), !String(cString: bytes).trimmingCharacters(in: .whitespaces).isEmpty { index = scoped }
                }
                if let bytes = sqlite3_column_text(scalar, index), ["signals", "variable", "dynamic"].contains(String(cString: bytes).trimmingCharacters(in: .whitespaces).lowercased()) {
                    sqlite3_finalize(scalar)
                    return unknown("electronic_sign_state_unknown")
                }
            }
        }
        sqlite3_finalize(scalar)
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT lane_tags_json FROM traffic_sign_way_direction WHERE way_id=? LIMIT 1", -1, &statement, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_int64(statement, 1, Int64(wayID) ?? 0)
        guard sqlite3_step(statement) == SQLITE_ROW, let bytes = sqlite3_column_text(statement, 0),
              let data = String(cString: bytes).data(using: .utf8),
              let tags = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return nil }
        for (key, value) in tags where key.hasPrefix("maxspeed") {
            let parts = key.split(separator: ":").map(String.init)
            if isOtherVehicleSpeedKey(key) { continue }
            if parts.contains("forward"), direction == -1 { continue }
            if parts.contains("backward"), direction == 1 { continue }
            if parts.contains("reason") || parts.contains("type") { continue }
            if parts.contains("conditional") || (parts.contains("variable") && value != "no") { return unknown("legacy_conditional_rules_not_compiled") }
        }
        return nil
    }

    private static func unknown(_ reason: String) -> Result { Result(kmh: nil, unlimited: false, unresolved: true, reason: reason) }

    static func evaluate(_ rules: [String: Any], context: Context, baseKmh: Int?, baseUnlimited: Bool) -> Result {
        guard rules["version"] as? Int == 1, rules["grammar"] as? String == "youspeed-osm-speed-1",
              let allTags = rules["tags"] as? [[String: Any]], allTags.count <= 128 else { return unknown("unsupported_rule_set") }
        let tags = allTags.filter { tag in
            guard tag["role"] as? String == "speed" else { return false }
            let vehicle = tag["vehicle"] as? String ?? "unknown"
            return ["all", "vehicle", "motor_vehicle", context.vehicle].contains(vehicle) || vehicle == "hazmat"
        }.sorted {
            let lhs = ($0["priority"] as? Int ?? 0) * 2 + (($0["conditional"] as? Bool ?? false) ? 1 : 0)
            let rhs = ($1["priority"] as? Int ?? 0) * 2 + (($1["conditional"] as? Bool ?? false) ? 1 : 0)
            return lhs < rhs
        }
        if allTags.contains(where: { $0["role"] as? String == "variable" && ($0["raw"] as? String ?? "").lowercased() != "no" }) { return unknown("variable_sign_state_unknown") }
        var keys = Set<String>()
        func fact(_ key: String, _ assignments: [String: Bool]) -> Bool {
            if let known = context.facts[key] ?? assignments[key] { return known }
            keys.insert(key)
            return false
        }
        func truth(_ node: [String: Any], _ assignments: [String: Bool], _ depth: Int = 0) -> Bool {
            guard depth < 20 else { return fact("unsupported_depth", assignments) }
            switch node["kind"] as? String {
            case "true": return true
            case "context": return fact(node["field"] as? String ?? "unknown", assignments)
            case "not": return !truth(node["item"] as? [String: Any] ?? [:], assignments, depth + 1)
            case "all":
                let values = (node["items"] as? [[String: Any]] ?? [[:]]).map { truth($0, assignments, depth + 1) }
                return values.allSatisfy { $0 }
            case "any":
                let values = (node["items"] as? [[String: Any]] ?? [[:]]).map { truth($0, assignments, depth + 1) }
                return values.contains(true)
            case "schedule":
                let zoneID = context.timeZoneID ?? (["DE", "DEU"].contains(context.countryCode?.uppercased() ?? "") ? "Europe/Berlin" : "")
                guard context.clockTrusted, let zone = TimeZone(identifier: zoneID) else {
                    let identity = (try? JSONSerialization.data(withJSONObject: node, options: .sortedKeys)).flatMap { String(data: $0, encoding: .utf8) } ?? "unknown"
                    return fact("schedule:" + identity, assignments)
                }
                var calendar = Calendar(identifier: .gregorian); calendar.timeZone = zone
                let minute = calendar.component(.hour, from: context.at) * 60 + calendar.component(.minute, from: context.at)
                let windows = node["windows"] as? [[Int]] ?? []
                var anchors: [Date] = []
                if windows.isEmpty { anchors = [context.at] }
                for window in windows where window.count == 2 {
                    if window[0] < window[1], minute >= window[0], minute < window[1] { anchors.append(context.at) }
                    if window[0] > window[1] {
                        if minute >= window[0] { anchors.append(context.at) }
                        else if minute < window[1], let previous = calendar.date(byAdding: .day, value: -1, to: context.at) { anchors.append(previous) }
                    }
                }
                var matches: [Bool] = []
                for anchor in anchors {
                    let day = (calendar.component(.weekday, from: anchor) + 5) % 7 + 1
                    let annual = calendar.component(.month, from: anchor) * 100 + calendar.component(.day, from: anchor)
                    let start = node["annual_start"] as? Int, end = node["annual_end"] as? Int
                    let dateMatches = start == nil || end == nil || (start! <= end! ? annual >= start! && annual <= end! : annual >= start! || annual <= end!)
                    let weekdays = node["weekdays"] as? [Int] ?? []
                    let holidays = node["holidays"] as? [String] ?? []
                    let dateID = "\(calendar.component(.year, from: anchor))-\(annual)"
                    let holidayMatches = holidays.map { fact($0 + ":" + dateID, assignments) }.contains(true)
                    matches.append(dateMatches && (weekdays.isEmpty && holidays.isEmpty || weekdays.contains(day) || holidayMatches))
                }
                return matches.contains(true)
            default: return fact("unsupported_condition", assignments)
            }
        }
        func outcome(_ assignments: [String: Bool]) -> (value: String, restriction: String?) {
            var selected = baseUnlimited ? "unlimited" : baseKmh.map { "numeric:\($0)" } ?? "unknown"
            var restriction: String?
            for tag in tags {
                let direction = tag["direction"] as? Int ?? 0
                if direction != 0 {
                    if let known = context.direction { if known != direction { continue } }
                    else if fact("direction_forward", assignments) != (direction == 1) { continue }
                }
                if tag["vehicle"] as? String == "hazmat", !fact("vehicle_hazmat", assignments) { continue }
                if tag["status"] as? String != "supported" { selected = "unsupported"; restriction = nil; continue }
                for clause in tag["clauses"] as? [[String: Any]] ?? [] {
                    if truth(clause["condition"] as? [String: Any] ?? [:], assignments) {
                        let limit = clause["limit"] as? [String: Any] ?? [:]
                        if limit["kind"] as? String == "unlimited" { selected = "unlimited" }
                        else if let number = limit["kmh"] as? NSNumber, number.doubleValue.isFinite, number.doubleValue > 0, number.doubleValue <= 400 { selected = "numeric:\(Int(number.doubleValue.rounded()))" }
                        else { selected = "unsupported" }
                        // Follow the winning clause, including later unconditional
                        // overrides. Never attach a condition from a losing rule.
                        restriction = tag["conditional"] as? Bool == true ? restrictionText(tag: tag, clause: clause) : nil
                    }
                }
            }
            return (selected, restriction)
        }
        _ = outcome([:])
        // Enumerate correlated unknowns: one wetness/calendar fact has one value
        // throughout the ordered decision list, including repeated predicates.
        for tag in tags {
            if tag["direction"] as? Int != 0, context.direction == nil { _ = fact("direction_forward", [:]) }
            if tag["vehicle"] as? String == "hazmat" { _ = fact("vehicle_hazmat", [:]) }
            for clause in tag["clauses"] as? [[String: Any]] ?? [] { _ = truth(clause["condition"] as? [String: Any] ?? [:], [:]) }
        }
        guard keys.count <= 12 else { return unknown("too_many_unknown_contexts") }
        let orderedKeys = keys.sorted()
        var outcomes = Set<String>()
        var assignments: [[String: Bool]] = []
        var restrictions: [String?] = []
        for mask in 0..<(1 << orderedKeys.count) {
            var assignment: [String: Bool] = [:]
            for (index, key) in orderedKeys.enumerated() { assignment[key] = (mask & (1 << index)) != 0 }
            let selection = outcome(assignment)
            outcomes.insert(selection.value)
            restrictions.append(selection.restriction)
            assignments.append(assignment)
        }
        let preview = inactivePreview(tags: tags.reversed(), direction: context.direction,
                                      selected: outcomes.count == 1 ? outcomes.first : nil, facts: context.facts) { condition in
            assignments.allSatisfy { truth(condition, $0) }
        }
        guard outcomes.count == 1, let selected = outcomes.first, selected != "unsupported", selected != "unknown" else {
            var result = unknown("conditional_applicability_unresolved")
            result.inactivePreview = preview
            return result
        }
        let activeRestriction = restrictions.first ?? nil
        return Result(kmh: selected == "unlimited" ? nil : Int(selected.dropFirst(8)),
            unlimited: selected == "unlimited", unresolved: false, reason: "conditional_rules_evaluated", inactivePreview: preview,
            activeRestrictionText: restrictions.allSatisfy { $0 == activeRestriction } ? activeRestriction : nil)
    }

    private static func restrictionText(tag: [String: Any], clause: [String: Any]) -> String? {
        guard let raw = tag["raw"] as? String, let span = clause["source_span"] as? [Int], span.count == 2 else { return nil }
        let source = raw.unicodeScalars
        guard span[0] >= 0, span[0] < span[1], span[1] <= source.count else { return nil }
        let text = String(source[source.index(source.startIndex, offsetBy: span[0])..<source.index(source.startIndex, offsetBy: span[1])])
        guard let separator = text.firstIndex(of: "@") else { return nil }
        var condition = text[text.index(after: separator)...].trimmingCharacters(in: .whitespacesAndNewlines)
        if condition.hasPrefix("("), condition.hasSuffix(")") {
            condition = condition.dropFirst().dropLast().trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return condition.isEmpty ? nil : condition
    }

    private static func inactivePreview(tags: ReversedCollection<[[String: Any]]>, direction: Int?,
                                        selected: String?, facts: [String: Bool], alwaysApplies: ([String: Any]) -> Bool) -> ConditionalSpeedPreview? {
        for tag in tags {
            let scopedDirection = tag["direction"] as? Int ?? 0
            guard tag["conditional"] as? Bool == true, tag["status"] as? String == "supported",
                  tag["vehicle"] as? String != "hazmat", scopedDirection == 0 || scopedDirection == direction,
                  let raw = tag["raw"] as? String, let clauses = tag["clauses"] as? [[String: Any]] else { continue }
            let source = raw.unicodeScalars
            for clause in clauses.reversed() {
                guard let number = (clause["limit"] as? [String: Any])?["kmh"] as? NSNumber,
                      number.doubleValue.isFinite, (1...400).contains(number.doubleValue),
                      let condition = clause["condition"] as? [String: Any], !alwaysApplies(condition),
                      !excludedByVehicle(condition, facts: facts),
                      let span = clause["source_span"] as? [Int], span.count == 2,
                      span[0] >= 0, span[0] < span[1], span[1] <= source.count else { continue }
                let speed = Int(number.doubleValue.rounded())
                guard selected != "numeric:\(speed)" else { continue }
                let clauseText = String(source[source.index(source.startIndex, offsetBy: span[0])..<source.index(source.startIndex, offsetBy: span[1])])
                guard let separator = clauseText.firstIndex(of: "@") else { continue }
                var text = clauseText[clauseText.index(after: separator)...].trimmingCharacters(in: .whitespacesAndNewlines)
                if text.hasPrefix("("), text.hasSuffix(")") {
                    text = text.dropFirst().dropLast().trimmingCharacters(in: .whitespacesAndNewlines)
                }
                if !text.isEmpty { return ConditionalSpeedPreview(speedKmh: speed, restrictionText: text) }
            }
        }
        return nil
    }
}

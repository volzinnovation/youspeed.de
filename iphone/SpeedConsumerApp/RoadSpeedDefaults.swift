import Foundation

enum DrivingRoadIdentity {
    static let maximumAssertionAge: TimeInterval = 300
    static func key(ref: String?, name: String?, highway: String?) -> String? {
        let refs = (ref ?? "").uppercased().split(separator: ";").map {
            $0.filter { !$0.isWhitespace }
        }.filter { !$0.isEmpty }.sorted()
        let ramp = highway?.hasSuffix("_link") == true ? ":ramp" : ""
        if !refs.isEmpty { return "ref:" + refs.joined(separator: ";") + ramp }
        let name = name?.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ") ?? ""
        return name.isEmpty ? nil : "name:" + name + ramp
    }
}

/// Passenger-car statutory defaults. Missing country/road evidence stays unknown.
/// Geographic settlement estimates may be used by map lookup, but must not be
/// promoted to confirmed town-boundary events by callers.
enum RoadSpeedDefaults {
    static func country(_ raw: String?) -> String {
        let code = raw?.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() ?? ""
        return ["DEU": "DE", "FRA": "FR", "BEL": "BE", "NLD": "NL", "CHE": "CH"][code] ?? code
    }

    static func explicitSpeed(_ raw: String?) -> Int? {
        guard let value = raw?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
              value.range(of: #"^[0-9]{1,3}(\s*(km/h|kmh|kph|mph))?$"#, options: .regularExpression) != nil,
              let number = Double(value.prefix(while: { $0.isNumber })), number > 0 else { return nil }
        let kmh = Int((number * (value.hasSuffix("mph") ? 1.609344 : 1)).rounded())
        return (1...300).contains(kmh) ? kmh : nil
    }

    static func symbolicSpeed(_ raw: String?, country fallbackCountry: String?) -> Int? {
        guard let raw else { return nil }
        let parts = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased().split(separator: ":")
        guard let regime = parts.last, parts.count <= 2 else { return nil }
        let code = country(parts.count == 2 ? String(parts[0]) : fallbackCountry)
        switch regime {
        case "urban": return speedKmh(country: code, region: nil, highway: nil, insideCity: true)
        case "rural": return speedKmh(country: code, region: nil, highway: "road", insideCity: false)
        case "motorway": return speedKmh(country: code, region: nil, highway: "motorway", insideCity: false)
        case "trunk": return code == "FR" ? 110 : speedKmh(country: code, region: nil, highway: "trunk", insideCity: false)
        default: return nil
        }
    }

    static func speedKmh(country raw: String?, region: String?, highway: String?, insideCity: Bool?) -> Int? {
        let code = country(raw)
        let road = highway?.lowercased()
        if road == "motorway" { return ["BE", "CH"].contains(code) ? 120 : code == "FR" ? 130 : nil }
        if road == "living_street", code == "FR" { return 20 }
        guard let insideCity else { return nil }
        if insideCity {
            if code == "BE" { return region == "BE-BRU" ? 30 : ["BE-VLG", "BE-WAL"].contains(region) ? 50 : nil }
            return ["DE", "FR", "NL", "CH"].contains(code) ? 50 : nil
        }
        if road == "trunk", ["NL", "CH"].contains(code) { return 100 }
        // A motorway ramp or a trunk's carriageway regime cannot be inferred
        // from road class alone. Explicit/symbolic speed tags remain usable.
        guard ["primary", "secondary", "tertiary", "unclassified", "residential", "service", "road"].contains(road) else { return nil }
        switch code {
        case "DE": return 100
        case "FR", "NL", "CH": return 80
        case "BE": return region == "BE-VLG" ? 70 : region == "BE-WAL" ? 90 : nil
        default: return nil
        }
    }
}

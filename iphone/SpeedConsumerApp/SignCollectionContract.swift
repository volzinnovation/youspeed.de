import Foundation
import CoreFoundation
import CryptoKit

enum SignCollectionError: Error { case invalidJSON, invalidContract, consentRequired, deletionPending, capacity, invalidReceipt, storage }

/// Backend semantic-json-v1, deliberately distinct from RFC 8785. No Foundation
/// dictionary serialization is used for identity digests or saved request bytes.
enum SignCollectionJSON {
    static func parse(_ text: String) throws -> Any {
        var parser = Parser(bytes: Array(text.utf8))
        let value = try parser.value(0)
        parser.space()
        guard parser.index == parser.bytes.count else { throw SignCollectionError.invalidJSON }
        return value
    }

    static func canonical(_ value: Any, depth: Int = 0) throws -> String {
        guard depth <= 16 else { throw SignCollectionError.invalidJSON }
        if value is NSNull { return "null" }
        if let value = value as? String {
            guard value.unicodeScalars.count <= 4096 else { throw SignCollectionError.invalidJSON }
            var result = "\""
            for scalar in value.unicodeScalars {
                switch scalar.value {
                case 34: result += "\\\""
                case 92: result += "\\\\"
                case 8: result += "\\b"
                case 9: result += "\\t"
                case 10: result += "\\n"
                case 12: result += "\\f"
                case 13: result += "\\r"
                case 0..<32: result += String(format: "\\u%04x", scalar.value)
                default: result.unicodeScalars.append(scalar)
                }
            }
            return result + "\""
        }
        if let n = value as? NSNumber {
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "true" : "false" }
            let type = String(cString: n.objCType)
            if !["f", "d"].contains(type), abs(n.doubleValue) > 9_007_199_254_740_991 { throw SignCollectionError.invalidJSON }
            return try number(n.doubleValue)
        }
        if let array = value as? [Any] {
            guard array.count <= 128 else { throw SignCollectionError.invalidJSON }
            return "[" + (try array.map { try canonical($0, depth: depth + 1) }).joined(separator: ",") + "]"
        }
        if let object = value as? [String: Any] {
            guard object.count <= 128 else { throw SignCollectionError.invalidJSON }
            let keys = object.keys.sorted { $0.unicodeScalars.map(\.value).lexicographicallyPrecedes($1.unicodeScalars.map(\.value)) }
            return "{" + (try keys.map { try canonical($0) + ":" + canonical(object[$0]!, depth: depth + 1) }).joined(separator: ",") + "}"
        }
        throw SignCollectionError.invalidJSON
    }

    private static func number(_ value: Double) throws -> String {
        guard value.isFinite else { throw SignCollectionError.invalidJSON }
        if value == 0 { return "0" }
        // Find the nearest shortest decimal that round-trips the binary64.
        // This also avoids platform-specific exponent padding and integral .0.
        var shortest = String(value)
        for precision in 1...17 {
            let candidate = String(format: "%.*g", locale: Locale(identifier: "en_US_POSIX"), precision, value)
            if Double(candidate) == value { shortest = candidate; break }
        }
        let negative = shortest.first == "-"
        let parts = shortest.lowercased().replacingOccurrences(of: "-", with: "", range: shortest.startIndex..<(negative ? shortest.index(after: shortest.startIndex) : shortest.startIndex)).split(separator: "e")
        let decimal = parts[0].split(separator: ".", omittingEmptySubsequences: false)
        var digits = decimal.joined()
        var point = decimal[0].count + (parts.count == 2 ? Int(parts[1])! : 0)
        while digits.first == "0" { digits.removeFirst(); point -= 1 }
        while digits.last == "0" { digits.removeLast() }
        let sign = negative ? "-" : ""
        if abs(value) >= 1e-6 && abs(value) < 1e21 {
            if point <= 0 { return sign + "0." + String(repeating: "0", count: -point) + digits }
            if point >= digits.count { return sign + digits + String(repeating: "0", count: point - digits.count) }
            let split = digits.index(digits.startIndex, offsetBy: point)
            return sign + digits[..<split] + "." + digits[split...]
        }
        let exponent = point - 1
        let mantissa = String(digits.prefix(1)) + (digits.count > 1 ? "." + digits.dropFirst() : "")
        return sign + mantissa + "e" + (exponent >= 0 ? "+" : "-") + String(abs(exponent))
    }

    static func sha256(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func digest(_ value: Any) throws -> String { sha256(Data(try canonical(value).utf8)) }
    static func integer(_ value: Any?) -> Int? {
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), !["f", "d"].contains(String(cString: n.objCType)), abs(n.doubleValue) <= 9_007_199_254_740_991 else { return nil }
        return n.intValue
    }
    static func boolean(_ value: Any?) -> Bool? {
        guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }; return n.boolValue
    }
    static func uuid() -> String { UUID().uuidString.lowercased() }
    static func isUUID(_ value: String) -> Bool {
        guard let parsed = UUID(uuidString: value), parsed.uuidString.lowercased() == value else { return false }
        return value[value.index(value.startIndex, offsetBy: 14)] == "4"
            && "89ab".contains(value[value.index(value.startIndex, offsetBy: 19)])
    }
    static func utc(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    private struct Parser {
        let bytes: [UInt8]
        var index = 0
        mutating func space() { while index < bytes.count && [9, 10, 13, 32].contains(bytes[index]) { index += 1 } }
        mutating func take(_ byte: UInt8) -> Bool { space(); if index < bytes.count && bytes[index] == byte { index += 1; return true }; return false }
        mutating func value(_ depth: Int) throws -> Any {
            space()
            guard depth <= 16, index < bytes.count else { throw SignCollectionError.invalidJSON }
            if take(123) {
                var result: [String: Any] = [:]
                if take(125) { return result }
                repeat {
                    guard let key = try value(depth + 1) as? String, result[key] == nil, take(58) else { throw SignCollectionError.invalidJSON }
                    result[key] = try value(depth + 1)
                    guard result.count <= 128 else { throw SignCollectionError.invalidJSON }
                } while take(44)
                guard take(125) else { throw SignCollectionError.invalidJSON }; return result
            }
            if take(91) {
                var result: [Any] = []
                if take(93) { return result }
                repeat { result.append(try value(depth + 1)); guard result.count <= 128 else { throw SignCollectionError.invalidJSON } } while take(44)
                guard take(93) else { throw SignCollectionError.invalidJSON }; return result
            }
            let start = index
            if bytes[index] == 34 {
                index += 1
                var escaped = false
                while index < bytes.count {
                    let byte = bytes[index]; index += 1
                    if byte == 34 && !escaped { break }
                    if byte == 92 && !escaped { escaped = true } else { escaped = false }
                }
            } else {
                while index < bytes.count && ![9, 10, 13, 32, 44, 93, 125].contains(bytes[index]) { index += 1 }
            }
            let token = Data(bytes[start..<index])
            let result = try JSONSerialization.jsonObject(with: token, options: [.fragmentsAllowed])
            if let number = result as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() {
                // Foundation can produce NSDecimalNumber whose doubleValue
                // differs by several ULPs from a correctly rounded binary64.
                // Parse the original numeric token directly, preserving its kind.
                let literal = String(decoding: token, as: UTF8.self)
                if token.contains(46) || token.contains(101) || token.contains(69) {
                    guard let d = Double(literal), d.isFinite else { throw SignCollectionError.invalidJSON }
                    return NSNumber(value: d)
                }
                guard let n = Int64(literal), n >= -9_007_199_254_740_991, n <= 9_007_199_254_740_991 else { throw SignCollectionError.invalidJSON }
                return NSNumber(value: n)
            }
            _ = try canonical(result, depth: depth)
            return result
        }
    }
}

struct SignCollectionClaim {
    let scope: String
    let disclosureVersion: String
    let decidedAt: String
    let generation: Int
    let state: String
    var wire: [String: Any] { ["scope": scope, "disclosure_version": disclosureVersion, "decided_at": decidedAt,
                             "consent_generation": generation, "state": state, "origin": "client_claim"] }
}

struct SignCollectionContractGate {
    let verified: Bool
    private var schemas: [String: [String: Any]] = [:]
    static let manifestSHA256 = "820aa65f8999a4af54a40435363161279ee56ebf880c6e83dfa5d4c0103e2c96"
    static var blocked: SignCollectionContractGate { SignCollectionContractGate(verified: false) }
    private init(verified: Bool) { self.verified = verified }
    // Delivery additionally verifies deployed capabilities and explicit claims.
    var liveTransportAllowed: Bool { verified }
    func validate(_ value: Any, model: String) throws {
        guard verified, let schema = schemas[model] else { throw SignCollectionError.invalidContract }
        try SignCollectionSchema.validate(value, schema: schema, root: schema)
        try SignCollectionSchema.semantics(value, model: model)
        _ = try SignCollectionJSON.canonical(value)
    }
    init(read: (String) throws -> Data) throws {
        let bytes = try read("manifest.json")
        guard SignCollectionJSON.sha256(bytes) == Self.manifestSHA256 else { throw SignCollectionError.invalidContract }
        let manifest = try SignCollectionJSON.parse(String(decoding: bytes, as: UTF8.self)) as? [String: Any]
        guard let entries = manifest?["files"] as? [[String: String]], manifest?["canonicalization"] as? String == "semantic-json-v1" else { throw SignCollectionError.invalidContract }
        for entry in entries {
            guard let path = entry["path"], !path.contains(".."), let hash = entry["sha256"],
                  SignCollectionJSON.sha256(try read(path)) == hash else { throw SignCollectionError.invalidContract }
        }
        guard let cases = try SignCollectionJSON.parse(String(decoding: read("fixtures/semantic-json-v1.json"), as: UTF8.self)) as? [[String: Any]] else { throw SignCollectionError.invalidContract }
        for item in cases {
            guard let input = item["input"], try SignCollectionJSON.canonical(input) == item["canonical"] as? String,
                  try SignCollectionJSON.digest(input) == item["sha256"] as? String else { throw SignCollectionError.invalidContract }
        }
        for name in ["batch", "sighting", "correction", "media-status", "consent", "deletion", "crop"] {
            guard let schema = try SignCollectionJSON.parse(String(decoding: read(name + "-v1.schema.json"), as: UTF8.self)) as? [String: Any] else { throw SignCollectionError.invalidContract }
            schemas[name] = schema
        }
        verified = true
    }
}

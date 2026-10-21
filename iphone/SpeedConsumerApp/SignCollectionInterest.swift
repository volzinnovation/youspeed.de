import Foundation

/// The lifetime is one app process. Resume and camera/model restarts are not activations.
struct SignCollectionInterestActivation {
    private(set) var enabled = false
    mutating func update(_ value: Bool) -> Bool {
        let request = value && !enabled
        enabled = value
        return request
    }
}

/// The daily HTTPS policy only selects image evidence. Sightings never depend on it.
struct SignCollectionInterestPlan {
    static let maximumBytes = 2 * 1024 * 1024
    struct Identity: Hashable {
        let country: String
        let pack: String
        let classifier: String
        let label: String
    }
    struct Rule {
        let key: String
        let numerator: UInt64
        let denominator: UInt64
    }
    let revision: Int
        let generated: Date
    let validFrom: Date
    let expires: Date
    let rules: [Identity: Rule]
    let packs: Set<String>
    let document: [String: Any]

    static func isAlways(_ label: String) -> Bool { label == "bad" || label.hasPrefix("bad:") }
    static func sample(revision: Int, key: String, observation: String, numerator: UInt64, denominator: UInt64) -> Bool {
        guard revision > 0, revision <= 9_007_199_254_740_991, !key.contains("\n"), !key.contains("\r"),
              SignCollectionJSON.isUUID(observation), denominator > 0, denominator <= 1_000_000, numerator <= denominator else { return false }
        guard let draw = UInt64(observation.suffix(8), radix: 16) else { return false }
        return draw * denominator < numerator * 4_294_967_296
    }
    static func date(_ text: String) throws -> Date {
        guard text.hasSuffix("Z") || text.hasSuffix("+00:00") else { throw SignCollectionError.invalidContract }
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let value = f.date(from: text); f.formatOptions = [.withInternetDateTime]
        guard let date = value ?? f.date(from: text) else { throw SignCollectionError.invalidContract }; return date
    }
    init(data: Data, schema: [String: Any]) throws {
        guard data.count <= Self.maximumBytes, let text = String(data: data, encoding: .utf8),
              let d = try SignCollectionJSON.parse(text, maximumCollectionCount: 10_000) as? [String: Any] else { throw SignCollectionError.invalidContract }
        try SignCollectionSchema.validate(d, schema: schema, root: schema)
        revision = SignCollectionJSON.integer(d["revision"])!
        generated = try Self.date(d["generated_at"] as! String)
        validFrom = try Self.date(d["valid_from"] as! String)
        expires = try Self.date(d["valid_until"] as! String)
        guard generated <= validFrom, validFrom < expires, expires.timeIntervalSince(generated) <= 172_800 else { throw SignCollectionError.invalidContract }
        let compatible = d["compatible_packs"] as! [String]; packs = Set(compatible)
        guard packs.count == compatible.count else { throw SignCollectionError.invalidContract }
        let limits = d["limits"] as! [String: Any]
        let algorithm = d["algorithm_version"] as! String
        if algorithm == "daily-maximum-v1" {
            guard let maximum = SignCollectionJSON.integer(d["daily_maximum"]),
                  SignCollectionJSON.boolean(d["bootstrap"]) == (maximum == 0),
                  (limits["normal_images"] == nil || limits["normal_images"] is NSNull),
                  (limits["normal_bytes"] == nil || limits["normal_bytes"] is NSNull) else { throw SignCollectionError.invalidContract }
        }
        var found: [Identity: Rule] = [:], keys = Set<String>(), selectors = Set<[String]>(), allocation = 0
        for item in d["interests"] as! [[String: Any]] {
            let key = item["collection_key"] as! String, country = item["country"] as! String, classID = item["class_id"] as! String
            let fraction = item["selection"] as! [String: Any]
            let n = SignCollectionJSON.integer(fraction["numerator"])!, den = SignCollectionJSON.integer(fraction["denominator"])!
            guard n > 0, n <= den, !Self.isAlways(classID), keys.insert(key).inserted,
                  SignCollectionJSON.integer(item["target_deficit"])! > 0 else { throw SignCollectionError.invalidContract }
            if algorithm == "waterfill-v1" {
                guard let allocated = SignCollectionJSON.integer(item["allocated_images"]), allocated <= SignCollectionJSON.integer(item["target_deficit"])! else { throw SignCollectionError.invalidContract }
                allocation += allocated
            } else {
                guard n == den, SignCollectionJSON.integer(item["target_deficit"])! <= max(1, SignCollectionJSON.integer(d["daily_maximum"])!),
                      item["allocated_images"] == nil || item["allocated_images"] is NSNull else { throw SignCollectionError.invalidContract }
            }
            for selector in item["selectors"] as! [[String: Any]] {
                let identity = Identity(country: selector["country"] as! String, pack: selector["pack_sha256"] as! String,
                    classifier: selector["classifier_sha256"] as! String, label: selector["raw_label"] as! String)
                guard identity.country == country, packs.contains(identity.pack), !Self.isAlways(identity.label),
                      selectors.insert([identity.country, identity.pack, identity.label]).inserted else { throw SignCollectionError.invalidContract }
                found[identity] = Rule(key: key, numerator: UInt64(n), denominator: UInt64(den))
            }
        }
        if algorithm == "waterfill-v1" {
            guard let images = SignCollectionJSON.integer(limits["normal_images"]), let bytes = SignCollectionJSON.integer(limits["normal_bytes"]),
                  allocation <= images, allocation * SignCollectionJSON.integer(limits["max_image_bytes"])! <= bytes else { throw SignCollectionError.invalidContract }
        }
        rules = found; document = d
    }
    func current(_ now: Date) -> Bool { generated <= now && validFrom <= now && now < expires }
}

struct SignCollectionInterestSelection {
    let revision: Int?
    let key: String?
    let decision: String
    let fraction: [String: Int]?
    let expires: Date?
    var collects: Bool { decision == "always" || decision == "selected" }
    var wire: [String: Any] { ["plan_revision": revision as Any? ?? NSNull(), "collection_key": key as Any? ?? NSNull(),
        "decision": decision, "sampling_fraction": fraction as Any? ?? NSNull()] }
    func permits(at: Date) -> Bool { decision == "always" || (collects && expires.map { at < $0 } == true) }
}

/// One immutable HTTPS response file is also the durable anti-rollback ledger. Expiry never removes it.
final class SignCollectionInterestStore: @unchecked Sendable {
    private let lock = NSLock()
    private let path: URL
    private let schema: [String: Any]
    private var plan: SignCollectionInterestPlan?
    private var loadedUptime: TimeInterval = 0
    private var loadedWall = Date.distantPast
    private let now: () -> Date
    private let uptime: () -> TimeInterval
    init(path: URL, schema: [String: Any], now: @escaping () -> Date = Date.init,
         uptime: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.path = path; self.schema = schema; self.now = now; self.uptime = uptime
        if let size = try? path.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= SignCollectionInterestPlan.maximumBytes,
           let data = try? Data(contentsOf: path), let saved = try? SignCollectionInterestPlan(data: data, schema: schema) {
            plan = saved; loadedWall = now(); loadedUptime = uptime()
        }
    }
    private func usable() -> SignCollectionInterestPlan? {
        guard let plan, plan.current(now()), abs(now().timeIntervalSince(loadedWall) - (uptime() - loadedUptime)) < 300 else { return nil }
        return plan
    }
    var etag: String? { lock.lock(); defer { lock.unlock() }; return usable().map { "\"crop-interest-\($0.revision)\"" } }
    @discardableResult func install(_ data: Data) throws -> Bool {
        let candidate = try SignCollectionInterestPlan(data: data, schema: schema)
        lock.lock(); defer { lock.unlock() }
        guard candidate.current(now()) else { throw SignCollectionError.invalidContract }
        if let previous = plan {
            guard candidate.revision >= previous.revision, try candidate.revision != previous.revision || SignCollectionJSON.canonical(candidate.document, maximumCollectionCount: 10_000) == SignCollectionJSON.canonical(previous.document, maximumCollectionCount: 10_000) else { throw SignCollectionError.invalidContract }
        }
        try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: path, options: [.atomic, .completeFileProtectionUnlessOpen])
        plan = candidate; loadedWall = now(); loadedUptime = uptime(); return true
    }
    func interested(_ identity: SignCollectionInterestPlan.Identity) -> Bool {
        if SignCollectionInterestPlan.isAlways(identity.label) { return true }
        lock.lock(); defer { lock.unlock() }; return usable()?.rules[identity] != nil
    }
    func select(_ identity: SignCollectionInterestPlan.Identity, observation: String) -> SignCollectionInterestSelection {
        lock.lock(); defer { lock.unlock() }
        let current = usable()
        if SignCollectionInterestPlan.isAlways(identity.label) {
            return .init(revision: current?.revision, key: nil, decision: "always", fraction: ["numerator": 1, "denominator": 1], expires: nil)
        }
        guard let current, current.packs.contains(identity.pack) else { return .init(revision: nil, key: nil, decision: "no_valid_plan", fraction: nil, expires: nil) }
        guard let rule = current.rules[identity] else { return .init(revision: current.revision, key: nil, decision: "not_interested", fraction: nil, expires: current.expires) }
        let selected = SignCollectionInterestPlan.sample(revision: current.revision, key: rule.key, observation: observation, numerator: rule.numerator, denominator: rule.denominator)
        return .init(revision: current.revision, key: rule.key, decision: selected ? "selected" : "sampled_out",
                     fraction: ["numerator": Int(rule.numerator), "denominator": Int(rule.denominator)], expires: current.expires)
    }
}

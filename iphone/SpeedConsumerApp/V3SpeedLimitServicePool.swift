import Foundation

/// Bounded reuse for overlapping installed bundles. Evicted services close after
/// their final in-flight lookup releases them; no active session is interrupted.
final class V3SpeedLimitServicePool: @unchecked Sendable {
    private struct Key: Hashable {
        let path: String
        let identity: String?
        let country: String?
        let model: V3SpeedLimitService.MatchingModel
    }
    private struct Entry {
        let service: V3SpeedLimitService
        let used: UInt64
    }
    private let lock = NSLock()
    private let limit: Int
    private var clock: UInt64 = 0
    private var entries: [Key: Entry] = [:]

    init(limit: Int = 4) { self.limit = max(1, limit) }

    func service(dbPath: String, bundleIdentity: String? = nil, countryCode: String?,
                 matchingModel: V3SpeedLimitService.MatchingModel,
                 regulationRegion: ((Double, Double) -> String?)? = nil) -> V3SpeedLimitService {
        lock.lock()
        defer { lock.unlock() }
        let key = Key(path: dbPath, identity: bundleIdentity, country: countryCode, model: matchingModel)
        clock &+= 1
        if let entry = entries[key] {
            entries[key] = Entry(service: entry.service, used: clock)
            return entry.service
        }
        // A replaced generation at one path must not retain a second old cache.
        entries = entries.filter { $0.key.path != dbPath || $0.key.identity == bundleIdentity }
        if entries.count >= limit, let oldest = entries.min(by: { $0.value.used < $1.value.used }) {
            entries.removeValue(forKey: oldest.key)
        }
        let service = V3SpeedLimitService(dbPath: dbPath, countryCode: countryCode,
                                          matchingModel: matchingModel, regulationRegion: regulationRegion)
        entries[key] = Entry(service: service, used: clock)
        return service
    }

    var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return entries.count
    }

    func removeAll() {
        lock.lock()
        defer { lock.unlock() }
        entries.removeAll()
    }
}

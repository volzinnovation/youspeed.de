import Foundation

/// Serializes background diagnostic writes with changes to the saved preference.
final class DebugLogPersistence: @unchecked Sendable {
    static let defaultsKey = "youspeed.debug.logging_enabled"
    static let shared = DebugLogPersistence(defaults: .standard)
    private let defaults: UserDefaults
    private let lock = NSRecursiveLock()

    init(defaults: UserDefaults) { self.defaults = defaults }

    var isEnabled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return defaults.object(forKey: Self.defaultsKey) as? Bool ?? true
    }

    func setEnabled(_ enabled: Bool) {
        lock.lock()
        defer { lock.unlock() }
        defaults.set(enabled, forKey: Self.defaultsKey)
    }

    @discardableResult
    func write<T>(_ action: () throws -> T) rethrows -> T? {
        lock.lock()
        defer { lock.unlock() }
        guard isEnabled else { return nil }
        return try action()
    }
}

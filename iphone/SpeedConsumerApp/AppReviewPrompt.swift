import Foundation

/// Native review requests are attempts, never evidence of a submitted rating.
final class AppReviewPrompt {
    static let shared = AppReviewPrompt(enabled: ProcessInfo.processInfo.environment["YOUSPEED_SCREENSHOT_STATE"] == nil)
    static let launchCountKey = "youspeed.review.launch_count"
    static let ratedKey = "youspeed.review.user_confirmed_rated"
    static let lastVersionKey = "youspeed.review.last_requested_version"
    static let lastRequestKey = "youspeed.review.last_requested_at"
    static let cooldown: TimeInterval = 180 * 24 * 60 * 60
    private let defaults: UserDefaults
    private let enabled: Bool
    private let startedAt: Date
    private(set) var attemptedThisLaunch = false

    init(defaults: UserDefaults = .standard, enabled: Bool = true, now: Date = Date()) {
        self.defaults = defaults
        self.enabled = enabled
        startedAt = now
        if enabled {
            defaults.set(min(10, max(0, min(10, defaults.integer(forKey: Self.launchCountKey))) + 1), forKey: Self.launchCountKey)
        }
    }

    static func isSafeToRequest(speedKmh: Double?, stationaryObservedAt: Date?, now: Date,
                                inTunnel: Bool, buttonsVisible: Bool, dashboardReady: Bool,
                                active: Bool, interrupted: Bool) -> Bool {
        active && dashboardReady && buttonsVisible && !interrupted &&
            GravityAlignmentVisibility.isFreshStationary(speedKmh: speedKmh,
                stationaryObservedAt: stationaryObservedAt, now: now, inTunnel: inTunnel)
    }

    func isEligible(version: String, now: Date) -> Bool {
        guard enabled, !attemptedThisLaunch, !version.isEmpty,
              defaults.integer(forKey: Self.launchCountKey) >= 10,
              !defaults.bool(forKey: Self.ratedKey),
              now.timeIntervalSince(startedAt) >= 60,
              defaults.string(forKey: Self.lastVersionKey) != version else { return false }
        if let last = defaults.object(forKey: Self.lastRequestKey) as? Date {
            return now.timeIntervalSince(last) >= Self.cooldown
        }
        return true
    }

    @discardableResult
    func recordRequest(version: String, now: Date) -> Bool {
        guard isEligible(version: version, now: now) else { return false }
        attemptedThisLaunch = true
        defaults.set(version, forKey: Self.lastVersionKey)
        defaults.set(now, forKey: Self.lastRequestKey)
        return true
    }
}

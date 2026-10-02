import XCTest
@testable import SpeedConsumer

final class AppReviewPromptTests: XCTestCase {
    private func withDefaults(_ body: (UserDefaults) -> Void) throws {
        let name = "AppReviewPromptTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        body(defaults)
    }

    func testThresholdSessionDelayVersionAndCooldown() throws {
        try withDefaults { defaults in
            let start = Date(timeIntervalSince1970: 1_000_000)
            for _ in 1...9 { XCTAssertFalse(AppReviewPrompt(defaults: defaults, now: start).isEligible(version: "1", now: start.addingTimeInterval(61))) }
            let tenth = AppReviewPrompt(defaults: defaults, now: start)
            XCTAssertFalse(tenth.isEligible(version: "1", now: start.addingTimeInterval(59)))
            let requestTime = start.addingTimeInterval(60)
            XCTAssertTrue(tenth.recordRequest(version: "1", now: requestTime))
            XCTAssertFalse(tenth.recordRequest(version: "2", now: requestTime.addingTimeInterval(AppReviewPrompt.cooldown)))
            let next = AppReviewPrompt(defaults: defaults, now: start)
            XCTAssertFalse(next.isEligible(version: "1", now: requestTime.addingTimeInterval(AppReviewPrompt.cooldown)))
            XCTAssertFalse(next.isEligible(version: "2", now: requestTime.addingTimeInterval(AppReviewPrompt.cooldown - 1)))
            XCTAssertTrue(next.isEligible(version: "2", now: requestTime.addingTimeInterval(AppReviewPrompt.cooldown)))
            XCTAssertFalse(defaults.bool(forKey: AppReviewPrompt.ratedKey))
        }
    }

    func testDisabledLaunchAndExistingOptOut() throws {
        try withDefaults { defaults in
            let now = Date()
            defaults.set(9, forKey: AppReviewPrompt.launchCountKey)
            XCTAssertFalse(AppReviewPrompt(defaults: defaults, enabled: false, now: now).isEligible(version: "1", now: now.addingTimeInterval(61)))
            XCTAssertEqual(defaults.integer(forKey: AppReviewPrompt.launchCountKey), 9)
            defaults.set(Int.max, forKey: AppReviewPrompt.launchCountKey)
            defaults.set(true, forKey: AppReviewPrompt.ratedKey)
            XCTAssertFalse(AppReviewPrompt(defaults: defaults, now: now).isEligible(version: "1", now: now.addingTimeInterval(61)))
            XCTAssertEqual(defaults.integer(forKey: AppReviewPrompt.launchCountKey), 10)
        }
    }

    func testRequiresFreshStandstillVisibleButtonsReadyDashboardAndNoInterruptions() {
        let now = Date()
        func safe(speed: Double? = 0, fix: Date? = now, tunnel: Bool = false,
                  buttons: Bool = true, ready: Bool = true, active: Bool = true, interrupted: Bool = false) -> Bool {
            AppReviewPrompt.isSafeToRequest(speedKmh: speed, stationaryObservedAt: fix, now: now,
                inTunnel: tunnel, buttonsVisible: buttons, dashboardReady: ready, active: active, interrupted: interrupted)
        }
        XCTAssertTrue(safe())
        XCTAssertFalse(safe(speed: 1))
        XCTAssertFalse(safe(speed: nil))
        XCTAssertFalse(safe(fix: nil))
        XCTAssertFalse(safe(fix: now.addingTimeInterval(-4)))
        XCTAssertFalse(safe(fix: now.addingTimeInterval(1)))
        XCTAssertFalse(safe(tunnel: true))
        XCTAssertFalse(safe(buttons: false))
        XCTAssertFalse(safe(ready: false))
        XCTAssertFalse(safe(active: false))
        XCTAssertFalse(safe(interrupted: true))
    }
}

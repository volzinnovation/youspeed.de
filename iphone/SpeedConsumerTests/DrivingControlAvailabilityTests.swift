import XCTest
@testable import SpeedConsumer

final class DrivingControlAvailabilityTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 10_000)

    private func evaluate(allowed: Bool = false, raw: Double = 0, displayed: Double = 0,
                          accuracy: Double = 5, age: TimeInterval = 0) -> DrivingControlAvailability {
        DrivingControlAvailability.updated(previouslyAllowed: allowed,
            rawSpeedMetersPerSecond: raw, displayedSpeedKmh: displayed,
            horizontalAccuracyMeters: accuracy, observedAt: now.addingTimeInterval(-age), now: now)
    }

    func testFreshMeasuredZeroUnlocksAndProvidesGravityTimestamp() {
        let result = evaluate(age: 1)
        XCTAssertTrue(result.controlsAllowed)
        XCTAssertEqual(result.stationaryObservedAt, now.addingTimeInterval(-1))
    }

    func testPositiveRawSpeedLocksEvenWhenDisplayRoundsToZero() {
        XCTAssertFalse(evaluate(allowed: true, raw: 0.01, displayed: 0).controlsAllowed)
        XCTAssertNil(evaluate(allowed: true, raw: 0.01).stationaryObservedAt)
    }

    func testPositiveFilteredSpeedLocksEvenWithInvalidGPS() {
        XCTAssertFalse(evaluate(allowed: true, raw: -1, displayed: 3).controlsAllowed)
    }

    func testStaleZeroOrMissingSpeedCannotClearMovingLock() {
        for result in [evaluate(age: 4), evaluate(age: -4), evaluate(raw: -1), evaluate(raw: .nan), evaluate(accuracy: -1)] {
            XCTAssertFalse(result.controlsAllowed)
            XCTAssertNil(result.stationaryObservedAt)
        }
    }

    func testMissingFirstFixAllowsSetupWithoutClaimingStandstill() {
        let result = evaluate(allowed: true, raw: -1)
        XCTAssertTrue(result.controlsAllowed)
        XCTAssertNil(result.stationaryObservedAt)
    }
}

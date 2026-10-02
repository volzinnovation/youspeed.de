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

    func testFreshSpeedsBelowFourUnlockControlsWithoutClaimingStandstill() {
        for speed in [0.001, 0.5, 1, 3, 3.99] {
            let result = evaluate(raw: speed / 3.6, displayed: speed)
            XCTAssertTrue(result.controlsAllowed, "Speed: \(speed)")
            XCTAssertNil(result.stationaryObservedAt)
        }
        XCTAssertTrue(evaluate(raw: 0.01, displayed: 0).controlsAllowed)
        XCTAssertTrue(evaluate(raw: 0, displayed: 3.99).controlsAllowed)
        XCTAssertNil(evaluate(raw: 0, displayed: 3.99).stationaryObservedAt)
    }

    func testFourOrFasterLocksForRawAndDisplayedSpeed() {
        for speed in [4.0, 4.01, 30] {
            XCTAssertFalse(evaluate(allowed: true, raw: speed / 3.6).controlsAllowed)
            XCTAssertFalse(evaluate(allowed: true, displayed: speed).controlsAllowed)
            XCTAssertFalse(evaluate(allowed: true, raw: -1, displayed: speed).controlsAllowed)
        }
    }

    func testDeceleratingBelowFourRestoresControlsAndAcceleratingLocksAgain() {
        let moving = evaluate(allowed: true, raw: 10, displayed: 36)
        let slow = evaluate(allowed: moving.controlsAllowed, raw: 3 / 3.6, displayed: 3)
        let movingAgain = evaluate(allowed: slow.controlsAllowed, raw: 4 / 3.6, displayed: 4)
        XCTAssertFalse(moving.controlsAllowed)
        XCTAssertTrue(slow.controlsAllowed)
        XCTAssertFalse(movingAgain.controlsAllowed)
    }

    func testStaleLowSpeedCannotUnlockControls() {
        XCTAssertTrue(evaluate(raw: 1 / 3.6, displayed: 1, age: 3).controlsAllowed)
        XCTAssertFalse(evaluate(raw: 1 / 3.6, displayed: 1, age: 3.001).controlsAllowed)
        XCTAssertFalse(evaluate(raw: 1 / 3.6, displayed: 1, age: -0.001).controlsAllowed)
        XCTAssertFalse(evaluate(raw: -1, displayed: 1).controlsAllowed)
        XCTAssertTrue(evaluate(allowed: true, raw: -1, displayed: 1).controlsAllowed)
    }

    func testStaleZeroOrMissingSpeedCannotClearMovingLock() {
        for result in [evaluate(age: 4), evaluate(age: -4), evaluate(raw: -1), evaluate(raw: .nan), evaluate(accuracy: -1), evaluate(displayed: .nan), evaluate(displayed: -1)] {
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

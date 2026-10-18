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

    func testFreshSpeedsAtOrBelowTwentyUnlockControlsWithoutClaimingStandstill() {
        for speed in [0.001, 0.5, 1, 3, 19.99, 20] {
            let result = evaluate(raw: speed / 3.6, displayed: speed)
            XCTAssertTrue(result.controlsAllowed, "Speed: \(speed)")
            XCTAssertNil(result.stationaryObservedAt)
        }
        XCTAssertTrue(evaluate(raw: 0.01, displayed: 0).controlsAllowed)
        XCTAssertTrue(evaluate(raw: 0, displayed: 3.99).controlsAllowed)
        XCTAssertNil(evaluate(raw: 0, displayed: 3.99).stationaryObservedAt)
    }

    func testAboveTwentyLocksForRawAndDisplayedSpeed() {
        for speed in [20.001, 20.01, 30] {
            XCTAssertFalse(evaluate(allowed: true, raw: speed / 3.6).controlsAllowed)
            XCTAssertFalse(evaluate(allowed: true, displayed: speed).controlsAllowed)
            XCTAssertFalse(evaluate(allowed: true, raw: -1, displayed: speed).controlsAllowed)
        }
    }

    func testDeceleratingAtOrBelowTwentyRestoresControlsAndAcceleratingLocksAgain() {
        let moving = evaluate(allowed: true, raw: 10, displayed: 36)
        let slow = evaluate(allowed: moving.controlsAllowed, raw: 3 / 3.6, displayed: 3)
        let movingAgain = evaluate(allowed: slow.controlsAllowed, raw: 20.01 / 3.6, displayed: 20.01)
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

    func testControlsRequireFlatPostureAndSpeedPermission() {
        for angle in [0.0, 5, 10] {
            XCTAssertTrue(DrivingControlPosturePolicy.isFlat(angleDegrees: angle))
            XCTAssertTrue(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: true, angleDegrees: angle))
            XCTAssertFalse(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: false, angleDegrees: angle))
        }
        for angle in [nil, -1, 10.001, 30, 79, 90, 101, 135, 180, .nan, .infinity] as [Double?] {
            XCTAssertFalse(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: true, angleDegrees: angle))
            XCTAssertFalse(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: false, angleDegrees: angle))
        }
    }

    func testPostureUsesScreenPlaneInPortraitAndBothLandscapeMounts() throws {
        for angle in [0.0, 5, 10, 10.001, 45, 80, 90, 100, 135, 180] {
            let radians = angle * .pi / 180
            for (x, y) in [(0.0, -sin(radians)), (sin(radians), 0.0), (-sin(radians), 0.0)] {
                let measured = try XCTUnwrap(DrivingControlPosturePolicy.angleDegrees(x: x, y: y, z: -cos(radians)))
                XCTAssertEqual(measured, angle, accuracy: 1e-9)
                XCTAssertEqual(DrivingControlPosturePolicy.isFlat(angleDegrees: measured), (0...10).contains(angle))
            }
        }
    }

    func testInvalidGravityLeavesPostureUnknown() {
        for (x, y, z) in [(0.0, 0.0, 0.0), (0, -3, 0), (.nan, -1, 0), (0, -.infinity, 0), (0, 0, .nan)] {
            XCTAssertNil(DrivingControlPosturePolicy.angleDegrees(x: x, y: y, z: z))
        }
    }

    func testAccelerationInclinesAndStaleGPSCannotUnlockControls() {
        let moving = evaluate(allowed: true, raw: 10, displayed: 36)
        let stale = evaluate(allowed: moving.controlsAllowed, age: 4)
        for angle in [0.0, 5, 10, 45, 79, 101, 180] {
            for speed in [moving, stale] {
                XCTAssertFalse(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: speed.controlsAllowed, angleDegrees: angle))
                XCTAssertNil(speed.stationaryObservedAt)
            }
        }
    }

    #if canImport(UIKit)
    @MainActor
    func testPostureImmediatelyReappliesBothGates() {
        let model = DriveSessionViewModel()
        model.testSetDrivingControlAngle(0)
        model.testObserveDrivingControlSpeed(rawMetersPerSecond: 0, displayedKmh: 0)
        XCTAssertTrue(model.drivingControlsAllowed)
        model.testSetDrivingControlAngle(11)
        XCTAssertFalse(model.drivingControlsAllowed)
        model.testSetDrivingControlAngle(0)
        XCTAssertTrue(model.drivingControlsAllowed)
        model.testObserveDrivingControlSpeed(rawMetersPerSecond: 21 / 3.6, displayedKmh: 21)
        XCTAssertFalse(model.drivingControlsAllowed)
        model.testSetDrivingControlAngle(5)
        XCTAssertFalse(model.drivingControlsAllowed)
        model.testSetDrivingControlAngle(nil)
        XCTAssertFalse(model.drivingControlsAllowed)
    }
    #endif
}

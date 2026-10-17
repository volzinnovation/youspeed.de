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

    func testSpeedRestrictionOnlyAppliesWithinInclusiveUprightRange() {
        for angle in [80.0, 90, 100] {
            XCTAssertTrue(DrivingControlPosturePolicy.isUpright(angleDegrees: angle))
            XCTAssertFalse(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: false, angleDegrees: angle))
            XCTAssertTrue(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: true, angleDegrees: angle))
        }
        for angle in [0.0, 45, 79.999, 100.001, 135, 180] {
            XCTAssertFalse(DrivingControlPosturePolicy.isUpright(angleDegrees: angle))
            XCTAssertTrue(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: false, angleDegrees: angle))
        }
        for angle in [nil, .nan, .infinity, -.infinity] as [Double?] {
            XCTAssertTrue(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: false, angleDegrees: angle))
        }
    }

    func testPostureUsesScreenPlaneInPortraitAndBothLandscapeMounts() throws {
        for angle in [0.0, 45, 79.999, 80, 90, 100, 100.001, 135, 180] {
            let radians = angle * .pi / 180
            for (x, y) in [(0.0, -sin(radians)), (sin(radians), 0.0), (-sin(radians), 0.0)] {
                let measured = try XCTUnwrap(DrivingControlPosturePolicy.angleDegrees(x: x, y: y, z: -cos(radians)))
                XCTAssertEqual(measured, angle, accuracy: 1e-9)
                XCTAssertEqual(DrivingControlPosturePolicy.isUpright(angleDegrees: measured), (80...100).contains(angle))
            }
        }
    }

    func testInvalidGravityLeavesPostureUnknown() {
        for (x, y, z) in [(0.0, 0.0, 0.0), (0, -3, 0), (.nan, -1, 0), (0, -.infinity, 0), (0, 0, .nan)] {
            XCTAssertNil(DrivingControlPosturePolicy.angleDegrees(x: x, y: y, z: z))
        }
    }

    func testFlatOrHandheldPostureOverridesMovingAndStaleGPSWithoutClaimingStandstill() {
        let moving = evaluate(allowed: true, raw: 10, displayed: 36)
        let stale = evaluate(allowed: moving.controlsAllowed, age: 4)
        for angle in [0.0, 45, 79.999, 100.001, 180] {
            for speed in [moving, stale] {
                XCTAssertTrue(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: speed.controlsAllowed, angleDegrees: angle))
                XCTAssertNil(speed.stationaryObservedAt)
            }
        }
        // Returning upright still has the retained speed lock.
        XCTAssertFalse(DrivingControlPosturePolicy.controlsAllowed(speedControlsAllowed: stale.controlsAllowed, angleDegrees: 90))
    }

    #if canImport(UIKit)
    @MainActor
    func testPostureImmediatelyRestoresControlsAndGPSDoesNotRelockOutsideUpright() {
        let model = DriveSessionViewModel()
        model.testSetDrivingControlAngle(90)
        model.testObserveDrivingControlSpeed(rawMetersPerSecond: 10, displayedKmh: 36)
        XCTAssertFalse(model.drivingControlsAllowed)

        model.testSetDrivingControlAngle(0)
        XCTAssertTrue(model.drivingControlsAllowed)
        model.testObserveDrivingControlSpeed(rawMetersPerSecond: 20, displayedKmh: 72)
        XCTAssertTrue(model.drivingControlsAllowed)
        XCTAssertNil(model.stationarySpeedObservedAt)

        // Missing GPS while flat must not clear the speed lock retained for upright use.
        model.testObserveDrivingControlSpeed(rawMetersPerSecond: -1, displayedKmh: 0)
        XCTAssertTrue(model.drivingControlsAllowed)
        model.testSetDrivingControlAngle(90)
        XCTAssertFalse(model.drivingControlsAllowed)

        model.testSetDrivingControlAngle(110)
        XCTAssertTrue(model.drivingControlsAllowed)
        model.testSetDrivingControlAngle(nil)
        XCTAssertTrue(model.drivingControlsAllowed)
        XCTAssertNil(model.stationarySpeedObservedAt)
        model.testSetDrivingControlAngle(90)
        model.testObserveDrivingControlSpeed(rawMetersPerSecond: 0, displayedKmh: 0)
        XCTAssertTrue(model.drivingControlsAllowed)
        XCTAssertNotNil(model.stationarySpeedObservedAt)
    }
    #endif
}

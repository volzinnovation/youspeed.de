import XCTest
@testable import SpeedConsumer

final class GravityAlignmentTests: XCTestCase {
    func testSearchingForSignalShowsTheMountingAidWithoutASpeedFix() {
        for speed in [nil, .nan, 0, 80] as [Double?] {
            XCTAssertTrue(GravityAlignmentVisibility.isVisible(landscape: true, speedKmh: speed,
                inTunnel: false, searchingForSignal: true))
        }
        XCTAssertFalse(GravityAlignmentVisibility.isVisible(landscape: false, speedKmh: nil,
            inTunnel: false, searchingForSignal: true))
    }

    func testBothManualLandscapeMountsRemapGravityToUprightScreen() throws {
        let lower = try XCTUnwrap(GravityAlignmentGeometry.reading(
            x: 1, y: 0, z: 0, orientation: .landscapeCameraLowerRight))
        let upper = try XCTUnwrap(GravityAlignmentGeometry.reading(
            x: -1, y: 0, z: 0, orientation: .landscapeCameraUpperLeft))
        XCTAssertEqual(lower.rollDegrees, 0, accuracy: 0.0001)
        XCTAssertEqual(upper.rollDegrees, 0, accuracy: 0.0001)
        XCTAssertTrue(lower.isLevel)
        XCTAssertEqual(lower, upper)
    }

    func testRollAndTiltRemainEquivalentAcrossChosenMounts() throws {
        let roll = 12.0 * Double.pi / 180
        let tilt = -8.0 * Double.pi / 180
        let sx = sin(roll) * cos(tilt)
        let sy = -cos(roll) * cos(tilt)
        let z = sin(tilt)
        for (orientation, x, y) in [
            (ScreenOrientation.portrait, sx, sy),
            (.landscapeCameraLowerRight, -sy, sx),
            (.landscapeCameraUpperLeft, sy, -sx)
        ] {
            let reading = try XCTUnwrap(GravityAlignmentGeometry.reading(x: x, y: y, z: z, orientation: orientation))
            XCTAssertEqual(reading.rollDegrees, 12, accuracy: 0.0001)
            XCTAssertEqual(reading.tiltDegrees, -8, accuracy: 0.0001)
            XCTAssertFalse(reading.isLevel)
        }
    }

    func testUnavailableOrFlatGravityNeverAppearsLevel() {
        for vector in [(0.0, 0.0, 0.0), (0, 0, 1), (Double.nan, -1, 0), (0, -3, 0)] {
            XCTAssertNil(GravityAlignmentGeometry.reading(
                x: vector.0, y: vector.1, z: vector.2, orientation: .portrait))
        }
        let upsideDown = GravityAlignmentGeometry.reading(x: 0, y: 1, z: 0, orientation: .portrait)
        XCTAssertEqual(abs(upsideDown!.rollDegrees), 180, accuracy: 0.0001)
        XCTAssertFalse(upsideDown!.isLevel)
    }

    func testLevelRequiresBothAnglesWithinThreeDegrees() {
        XCTAssertTrue(GravityAlignmentReading(rollDegrees: 3, tiltDegrees: -3).isLevel)
        XCTAssertFalse(GravityAlignmentReading(rollDegrees: 3.01, tiltDegrees: 0).isLevel)
        XCTAssertFalse(GravityAlignmentReading(rollDegrees: 0, tiltDegrees: -3.01).isLevel)
    }

    func testOverlayShowsStartupZeroWithoutGPSAndMatchesDisplayedZero() {
        // Startup uses zero until GPS arrives; no observation timestamp is required.
        for speed in [0.0, 0.001, 0.49, 0.499999] {
            XCTAssertTrue(GravityAlignmentVisibility.isVisible(landscape: true, speedKmh: speed, inTunnel: false))
        }
    }

    func testOverlayHidesForMovingSpeedPortraitTunnelAndInvalidSpeed() {
        XCTAssertFalse(GravityAlignmentVisibility.isVisible(landscape: false, speedKmh: 0, inTunnel: false))
        XCTAssertFalse(GravityAlignmentVisibility.isVisible(landscape: true, speedKmh: 0, inTunnel: true))
        for speed in [nil, .nan, .infinity, -1, 0.5, 1, 130] as [Double?] {
            XCTAssertFalse(GravityAlignmentVisibility.isVisible(landscape: true, speedKmh: speed, inTunnel: false))
        }
    }

    func testPermissionGateStillRequiresFreshVerifiedExactZeroSpeed() {
        let now = Date(timeIntervalSince1970: 1_790_683_200)
        XCTAssertTrue(GravityAlignmentVisibility.isFreshStationary(speedKmh: 0,
            stationaryObservedAt: now, now: now, inTunnel: false))
        XCTAssertTrue(GravityAlignmentVisibility.isFreshStationary(speedKmh: 0,
            stationaryObservedAt: now.addingTimeInterval(-3), now: now, inTunnel: false))
        XCTAssertFalse(GravityAlignmentVisibility.isFreshStationary(speedKmh: 0,
            stationaryObservedAt: now, now: now, inTunnel: true))
        for observed in [nil, now.addingTimeInterval(-3.001), now.addingTimeInterval(0.001)] {
            XCTAssertFalse(GravityAlignmentVisibility.isFreshStationary(speedKmh: 0,
                stationaryObservedAt: observed, now: now, inTunnel: false))
        }
        for speed in [nil, .nan, .infinity, -1, 0.001] as [Double?] {
            XCTAssertFalse(GravityAlignmentVisibility.isFreshStationary(speedKmh: speed,
                stationaryObservedAt: now, now: now, inTunnel: false))
        }
    }
}

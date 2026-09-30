import XCTest
@testable import SpeedConsumer

final class LanePreviewPresentationTests: XCTestCase {
    private let source = LanePreviewSourceGeometry(captureSessionID: "capture", rawWidth: 1600, rawHeight: 1200,
        rotationDegrees: 180, orientationKey: "rear:exif:3", observedAtUptimeSeconds: 10)
    private var calibration: VisualRoadCalibration {
        VisualRoadCalibration(horizonY: 0.525, leftBottom: LanePoint(x: 0, y: 0.915), leftTopX: 0.43,
            rightBottom: LanePoint(x: 0.8, y: 0.965), rightTopX: 0.47, revision: "saved",
            imageWidth: 1920, imageHeight: 1440, orientationKey: "rear:exif:3")
    }
    private func decision(enabled: Bool = true, visible: Bool = true, active: Bool = true,
                          thermal: Bool = false, rotation: Int = 180, source: LanePreviewSourceGeometry? = nil,
                          profile: VisualRoadCalibration? = nil, mature: Int = 0,
                          context: Bool = false, stale: Bool = false, now: Double = 10.1) -> LanePreviewPresentationDecision {
        LanePreviewPresentationPolicy.decide(enabled: enabled, visible: visible, active: active, thermalPaused: thermal,
            previewRotation: rotation, source: source ?? self.source, calibration: profile ?? calibration,
            matureBoundaryCount: mature, contextAvailable: context, staleObservedBoundary: stale, nowUptime: now)
    }
    func testFallbackIsExactlyTwoFaintStraightGuidesWithoutHorizonOrPointHandles() {
        let result = decision()
        XCTAssertEqual(result.mode, .calibrationReference)
        XCTAssertEqual(result.reason, "stale_context")
        XCTAssertEqual(result.referenceOpacity, 0.28)
        XCTAssertEqual(result.referenceLines, [[calibration.leftBottom, LanePoint(x: 0.43, y: 0.525)],
                                             [calibration.rightBottom, LanePoint(x: 0.47, y: 0.525)]])
        XCTAssertTrue(result.referenceLines.allSatisfy { $0.count == 2 })
    }
    func testMatureCurrentBoundariesWinWithoutNeedingMapContextOrCalibration() {
        let result = LanePreviewPresentationPolicy.decide(enabled: true, visible: true, active: true, thermalPaused: false,
            previewRotation: 180, source: source, calibration: nil, matureBoundaryCount: 2,
            contextAvailable: false, staleObservedBoundary: false, nowUptime: 10.1)
        XCTAssertEqual(result.mode, .observed); XCTAssertTrue(result.referenceLines.isEmpty)
        XCTAssertEqual(result.referenceOpacity, 0)
    }
    func testHiddenDisabledBackgroundOrThermalNeverShowReferenceOrObserved() {
        for result in [decision(enabled: false, mature: 2), decision(visible: false, mature: 2), decision(active: false, mature: 2), decision(thermal: true, mature: 2)] {
            XCTAssertEqual(result.mode, .hidden); XCTAssertTrue(result.referenceLines.isEmpty)
        }
    }
    func testStaleFutureOrWrongPreviewRotationCannotBorrowCameraGeometry() {
        for result in [decision(now: 10.751), decision(now: 9.9), decision(rotation: 90)] {
            XCTAssertEqual(result.mode, .hidden); XCTAssertTrue(result.referenceLines.isEmpty)
        }
    }
    func testDifferentResolutionWithSameAspectWorksButCropOrOrientationChangeDoesNot() {
        XCTAssertEqual(decision().mode, .calibrationReference) // 1920x1440 saved; 1600x1200 live.
        let cropped = LanePreviewSourceGeometry(captureSessionID: "new-capture", rawWidth: 1280, rawHeight: 720,
            rotationDegrees: 180, orientationKey: "rear:exif:3", observedAtUptimeSeconds: 10)
        XCTAssertEqual(decision(source: cropped).reason, "calibration_geometry_incompatible")
        var turnedProfile = calibration; turnedProfile.orientationKey = "rear:exif:1"
        XCTAssertEqual(decision(profile: turnedProfile).mode, .hidden)
    }
    func testExpiredPausedOrTSREnabledLegacyCannotMaskReference() {
        func current(_ now: Double, _ state: String = "detected", _ allowed: Bool = true) -> Bool {
            LanePreviewPresentationPolicy.legacyFrameIsCurrent(capturedAtSeconds: 10, nowSeconds: now,
                state: state, legacyAllowed: allowed)
        }
        XCTAssertTrue(current(10.749))
        XCTAssertFalse(current(10.75)); XCTAssertFalse(current(50)); XCTAssertFalse(current(9.9))
        XCTAssertFalse(current(.nan)); XCTAssertFalse(current(10.1, "paused")); XCTAssertFalse(current(10.1, "detected", false))
        XCTAssertEqual(decision(mature: current(50) ? 2 : 0).mode, .calibrationReference)
    }
    func testReasonSeparatesWarmupFromExpiredObservedEvidence() {
        XCTAssertEqual(decision(context: true).reason, "no_confirmed_boundaries")
        XCTAssertEqual(decision(context: true, stale: true).reason, "stale_context")
        let unavailable = LanePreviewPresentationPolicy.decide(enabled: true, visible: true, active: true,
            thermalPaused: false, previewRotation: 180, source: nil, calibration: calibration,
            matureBoundaryCount: 0, contextAvailable: false, staleObservedBoundary: true, nowUptime: 10.1)
        XCTAssertEqual(unavailable.mode, .hidden)
    }
}

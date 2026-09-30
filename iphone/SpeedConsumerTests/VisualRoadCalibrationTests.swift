import XCTest
@testable import SpeedConsumer

final class VisualRoadCalibrationTests: XCTestCase {
    private func defaults() -> VisualRoadCalibration { .defaults(width: 1600, height: 1200, orientationKey: "rear:exif:3") }

    func testSchemaRoundTripAndSourceCompatibility() throws {
        let value = defaults()
        XCTAssertTrue(value.isValid)
        let data = try JSONEncoder().encode(value)
        XCTAssertEqual(try JSONDecoder().decode(VisualRoadCalibration.self, from: data), value)
        XCTAssertTrue(value.compatible(width: 800, height: 600, orientationKey: "rear:exif:3"))
        XCTAssertFalse(value.compatible(width: 1280, height: 720, orientationKey: "rear:exif:3"))
        XCTAssertFalse(value.compatible(width: 1600, height: 1200, orientationKey: "rear:exif:1"))
        XCTAssertEqual(value.leftBottom, LanePoint(x: 0, y: 1))
        XCTAssertEqual(value.rightBottom, LanePoint(x: 1, y: 1))
    }

    func testFiveStepsRestrictAxesAndUpperPointsAlwaysFollowHorizon() {
        var value = defaults()
        value.move(step: 0, dx: 0.5, dy: 0.005)
        XCTAssertEqual(value.horizonY, 0.425, accuracy: 1e-12)
        XCTAssertEqual(value.leftTopX, 0.46)
        value.move(step: 1, dx: 0.005, dy: -0.005)
        XCTAssertEqual(value.leftBottom, LanePoint(x: 0.005, y: 0.995))
        value.move(step: 2, dx: -0.005, dy: 0.5)
        XCTAssertEqual(value.leftTopX, 0.455, accuracy: 1e-12)
        XCTAssertEqual(value.horizonY, 0.425, accuracy: 1e-12)
        value.move(step: 3, dx: -0.005, dy: -0.005)
        XCTAssertEqual(value.rightBottom, LanePoint(x: 0.995, y: 0.995))
        value.move(step: 4, dx: 0.005, dy: 0.5)
        XCTAssertEqual(value.rightTopX, 0.545, accuracy: 1e-12)
        XCTAssertTrue(value.isValid)
    }

    func testInvalidAndCrossedGuidesCannotBeSaved() {
        var value = defaults()
        value.leftTopX = 0.9
        XCTAssertFalse(value.isValid)
        value = defaults(); value.horizonY = .nan
        XCTAssertFalse(value.isValid)
        value = defaults(); value.leftBottom = LanePoint(x: 0.99, y: 0.3)
        XCTAssertFalse(value.isValid)
    }

    func testDraftCancellationDoesNotChangePersistedSnapshotAndSaveReopens() throws {
        let suite = "VisualCalibrationTests.\(UUID().uuidString)"
        let preferences = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { preferences.removePersistentDomain(forName: suite) }
        let store = VisualRoadCalibrationStore(defaults: preferences)
        XCTAssertNil(store.snapshot())
        var original = defaults(); original.revision = "saved-one"
        XCTAssertTrue(store.save(original))
        var draft = try XCTUnwrap(store.snapshot()); draft.move(step: 2, dx: -0.05, dy: 0)
        XCTAssertEqual(store.snapshot(), original) // Discarding the local edit is Cancel.
        draft.revision = "saved-two"
        XCTAssertTrue(store.save(draft))
        XCTAssertEqual(VisualRoadCalibrationStore(defaults: preferences).snapshot(), draft)
        var invalid = draft; invalid.leftTopX = 1
        XCTAssertFalse(store.save(invalid))
        XCTAssertEqual(store.snapshot(), draft)
    }

    func testOnlyLeftCropEdgeChangesAndBoxesMapBackToExactPixelBoundary() {
        var calibration = defaults(); calibration.leftTopX = 0.461
        let left = calibration.cropLeftPixels(width: 1280)
        XCTAssertEqual(left, 590)
        let mapping = TrafficSignCalibrationCropMapping(sourceWidth: 1280, leftPixels: left)
        let box = TrafficSignNormalizedRect(x: 0.2, y: 0.1, width: 0.3, height: 0.4)
        let full = mapping.remap(box)
        XCTAssertEqual(full.x, (590 + 0.2 * 690) / 1280, accuracy: 1e-12)
        XCTAssertEqual(full.width, 0.3 * 690 / 1280, accuracy: 1e-12)
        XCTAssertEqual(full.y, box.y); XCTAssertEqual(full.height, box.height)
        let whole = mapping.remap(TrafficSignNormalizedRect(x: 0, y: 0, width: 1, height: 1))
        XCTAssertEqual(whole.x + whole.width, 1, accuracy: 1e-12)
        XCTAssertEqual(whole.y + whole.height, 1, accuracy: 1e-12)
        XCTAssertEqual(TrafficSignCalibrationCropMapping(sourceWidth: 1280, leftPixels: 0).remap(box), box)
    }

    func testRemappingDoesNotChangeModelScoresSemanticOrThresholds() {
        let original = TrafficSignDetection(rawClassId: "maxspeed-80", rawLabel: "80",
            semantic: TrafficSignSemantic(kind: .maximumSpeed, value: 80, unit: "km/h"),
            rawScore: 0.91, calibratedConfidence: 0.92, detectorRawScore: 0.93,
            detectorCalibratedConfidence: 0.94, classifierRawScore: 0.95, classifierCalibratedConfidence: 0.96,
            boundingBox: TrafficSignNormalizedRect(x: 0.2, y: 0.3, width: 0.1, height: 0.2),
            classThreshold: 0.7, assemblyId: "assembly")
        let mapped = TrafficSignCalibrationCropMapping(sourceWidth: 1600, leftPixels: 736).remap(original)
        XCTAssertEqual(mapped.semantic, original.semantic); XCTAssertEqual(mapped.rawScore, original.rawScore)
        XCTAssertEqual(mapped.calibratedConfidence, original.calibratedConfidence)
        XCTAssertEqual(mapped.detectorRawScore, original.detectorRawScore)
        XCTAssertEqual(mapped.detectorCalibratedConfidence, original.detectorCalibratedConfidence)
        XCTAssertEqual(mapped.classifierRawScore, original.classifierRawScore)
        XCTAssertEqual(mapped.classifierCalibratedConfidence, original.classifierCalibratedConfidence)
        XCTAssertEqual(mapped.classThreshold, original.classThreshold); XCTAssertEqual(mapped.assemblyId, original.assemblyId)
        XCTAssertNotEqual(mapped.boundingBox, original.boundingBox)
    }

    func testCalibrationCameraIsHiddenFromRecordingControls() {
        XCTAssertEqual(DriveRecorderPolicy.presentedRecorderState(captureState: .recording, purpose: .calibration,
            driveStartPending: false), .disabled)
        XCTAssertFalse(DriveRecorderPolicy.canProcessPanoramaxUploads(for: .recording, purpose: .calibration))
    }
}

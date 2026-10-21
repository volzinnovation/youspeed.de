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

    func testCalibrationCameraIsHiddenFromRecordingControls() {
        XCTAssertEqual(DriveRecorderPolicy.presentedRecorderState(captureState: .recording, purpose: .calibration,
            driveStartPending: false), .disabled)
        XCTAssertFalse(DriveRecorderPolicy.canProcessPanoramaxUploads(for: .recording, purpose: .calibration))
    }
}

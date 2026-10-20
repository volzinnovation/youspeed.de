import AVFoundation
import XCTest
@testable import SpeedConsumer

final class DriveRecorderStartupTests: XCTestCase {
    func testCodecSelectionHonorsTheConfiguredOutputsCapabilities() {
        XCTAssertEqual(DriveMovieCodecConfiguration.preferredCodec(
            available: [.h264, .hevc], supportedKeys: [AVVideoCodecKey]), .hevc)
        XCTAssertEqual(DriveMovieCodecConfiguration.preferredCodec(
            available: [.h264], supportedKeys: [AVVideoCodecKey]), .h264)
        XCTAssertNil(DriveMovieCodecConfiguration.preferredCodec(
            available: [], supportedKeys: [AVVideoCodecKey]))
        XCTAssertNil(DriveMovieCodecConfiguration.preferredCodec(
            available: [.jpeg], supportedKeys: [AVVideoCodecKey]))
        XCTAssertNil(DriveMovieCodecConfiguration.preferredCodec(
            available: [.hevc, .h264], supportedKeys: []))
    }

    @MainActor
    func testCameraConfigurationDoesNotBlockMainActorAndSerializesPendingOperations() async throws {
        let coordinator = DriveCaptureCoordinator(queueStore: nil)
        let began = expectation(description: "configuration began off main")
        let second = expectation(description: "next camera operation ran")
        let release = DispatchSemaphore(value: 0)
        let first = Task {
            try await coordinator.testRunSessionOperation {
                XCTAssertFalse(Thread.isMainThread)
                began.fulfill()
                XCTAssertEqual(release.wait(timeout: .now() + 5), .success)
            }
        }
        await fulfillment(of: [began], timeout: 3)
        let submitted = expectation(description: "second operation submitted")
        let next = Task {
            submitted.fulfill()
            try await coordinator.testRunSessionOperation {
                XCTAssertFalse(Thread.isMainThread)
                second.fulfill()
            }
        }
        await fulfillment(of: [submitted], timeout: 3)
        // If configuration occupied MainActor, this point could not be reached
        // while the worker is blocked. The second operation must remain queued.
        XCTAssertEqual(XCTWaiter.wait(for: [second], timeout: 0.05), .timedOut)
        release.signal()
        try await first.value
        try await next.value
    }

    @MainActor
    func testFailedConfigurationDoesNotStrandTheSessionQueue() async throws {
        enum Failure: Error { case expected }
        let coordinator = DriveCaptureCoordinator(queueStore: nil)
        do {
            try await coordinator.testRunSessionOperation { throw Failure.expected }
            XCTFail("The configuration error must reach its caller")
        } catch Failure.expected {}
        try await coordinator.testRunSessionOperation { XCTAssertFalse(Thread.isMainThread) }
    }

    @MainActor
    func testRecordingStartNotificationDoesNotRecursivelyReconcileUnchangedRecognition() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try PanoramaxQueueStore(root: root)
        let model = DriveSessionViewModel()
        model.trafficSignRecognitionEnabled = false
        model.panoramaxCaptureEnabled = false
        let coordinator = DriveCaptureCoordinator(queueStore: store)
        model.testAttachPanoramaxCaptureCoordinator(coordinator, store: store)
        let synchronize = try XCTUnwrap(coordinator.onChange)
        var notifications = 0
        coordinator.onChange = {
            notifications += 1
            // Bound a broken implementation so the regression fails with an
            // assertion instead of exhausting the test host's main stack.
            if notifications < 8 { synchronize() }
        }
        try coordinator.testPrepareManualPhotoSession(dashcamActive: true, purpose: .driveRecording) { _, _ in }
        XCTAssertLessThan(notifications, 3, "Recording must not cycle sync -> reconcile -> unchanged TSR -> notify")
        XCTAssertEqual(coordinator.state, .recording)
        XCTAssertTrue(coordinator.isDashcamModuleActive)
        XCTAssertFalse(coordinator.isTrafficSignRecognitionModuleActive)
        coordinator.onChange = nil
    }

    @MainActor
    func testRepeatedRecognitionDisableDoesNotPublishOrOverwriteRecordingDetail() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let coordinator = DriveCaptureCoordinator(queueStore: try PanoramaxQueueStore(root: root))
        try coordinator.testPrepareManualPhotoSession(dashcamActive: true, purpose: .driveRecording) { _, _ in }
        let detail = coordinator.lastCaptureDetail
        var notifications = 0
        coordinator.onChange = { notifications += 1 }
        for _ in 0..<10 { XCTAssertTrue(coordinator.setTrafficSignRecognitionEnabledDuringRecording(false)) }
        XCTAssertEqual(notifications, 0)
        XCTAssertEqual(coordinator.lastCaptureDetail, detail)
        XCTAssertTrue(coordinator.isDashcamModuleActive)
        coordinator.onChange = nil
    }

}

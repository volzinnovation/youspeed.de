import XCTest
import AVFoundation
import ImageIO
@testable import SpeedConsumer

final class LaneDetectionRuntimeTests: XCTestCase {
    private final class CountingConsumer: DriveVideoFrameConsumer {
        var frames = 0
        func consumeVideoFrame(_ sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation) { frames += 1 }
    }

    func testSharedDispatcherKeepsLaneAndTSRConsumersIndependent() throws {
        let dispatcher = DriveVideoFrameDispatcher()
        let lanes = CountingConsumer(), signs = CountingConsumer()
        dispatcher.setConsumer(signs)
        dispatcher.setLaneConsumer(lanes)
        dispatcher.setLanesEnabled(true)
        let frame = try makeFrame(timestamp: LaneDetectionRuntime.now())
        dispatcher.dispatchFrame(frame)
        XCTAssertEqual(lanes.frames, 1)
        XCTAssertEqual(signs.frames, 0)
        dispatcher.setEnabled(true)
        dispatcher.dispatchFrame(frame)
        XCTAssertEqual(lanes.frames, 2)
        XCTAssertEqual(signs.frames, 1)
        dispatcher.setConsumer(nil)
        dispatcher.setEnabled(false)
        dispatcher.dispatchFrame(frame)
        XCTAssertEqual(lanes.frames, 3)
        XCTAssertEqual(signs.frames, 1)
        dispatcher.setConsumer(signs)
        dispatcher.setEnabled(true)
        dispatcher.setLanesEnabled(false)
        dispatcher.dispatchFrame(frame)
        XCTAssertEqual(lanes.frames, 3)
        XCTAssertEqual(signs.frames, 2)
    }

    private func makeFrame(timestamp: Double) throws -> CMSampleBuffer {
        let width = 384, height = 216
        var pixelBuffer: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, width, height,
            kCVPixelFormatType_420YpCbCr8BiPlanarFullRange, nil, &pixelBuffer), kCVReturnSuccess)
        let buffer = try XCTUnwrap(pixelBuffer)
        CVPixelBufferLockBaseAddress(buffer, [])
        let base = try XCTUnwrap(CVPixelBufferGetBaseAddressOfPlane(buffer, 0)).assumingMemoryBound(to: UInt8.self)
        let stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        for y in 0..<height {
            let normalizedY = Double(y) / Double(height - 1)
            let left = Int((0.5 - (normalizedY - 0.45) * 0.75) * Double(width - 1))
            let right = Int((0.5 + (normalizedY - 0.45) * 0.75) * Double(width - 1))
            for x in 0..<width {
                base[y * stride + x] = normalizedY > 0.50 && (abs(x - left) <= 3 || abs(x - right) <= 3) ? 230 : 35
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        var format: CMVideoFormatDescription?
        XCTAssertEqual(CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: buffer, formatDescriptionOut: &format), noErr)
        var timing = CMSampleTimingInfo(duration: .invalid,
            presentationTimeStamp: CMTime(seconds: timestamp, preferredTimescale: 1_000_000_000), decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        XCTAssertEqual(CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: buffer,
            formatDescription: try XCTUnwrap(format), sampleTiming: &timing, sampleBufferOut: &sample), noErr)
        return try XCTUnwrap(sample)
    }

    @MainActor private func waitForProcessed(_ count: Int, runtime: LaneDetectionRuntime) async throws {
        let deadline = LaneDetectionRuntime.now() + 3
        while runtime.snapshot().metrics.processedFrames < count && LaneDetectionRuntime.now() < deadline {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertGreaterThanOrEqual(runtime.snapshot().metrics.processedFrames, count)
    }

    @MainActor func testRealFramePipelineRetainsTrackerBetweenJobsAndClearsGeometry() async throws {
        let runtime = LaneDetectionRuntime()
        runtime.configure(enabled: true, recording: true, appActive: true, sessionID: "drive", sourceClock: CMClockGetHostTimeClock())
        runtime.setPreview(visible: true, rotation: 0)
        let firstTime = LaneDetectionRuntime.now()
        runtime.consumeVideoFrame(try makeFrame(timestamp: firstTime), orientation: .up)
        try await waitForProcessed(1, runtime: runtime)
        XCTAssertEqual(runtime.snapshot().frame?.estimate.state, .uncertain)
        // Let the worker fully drain before the next admission. Confirmation
        // must survive this idle period instead of restarting every frame.
        let remaining = max(0, 0.23 - (LaneDetectionRuntime.now() - firstTime))
        try await Task.sleep(nanoseconds: UInt64(remaining * 1_000_000_000))
        runtime.consumeVideoFrame(try makeFrame(timestamp: LaneDetectionRuntime.now()), orientation: .up)
        try await waitForProcessed(2, runtime: runtime)
        XCTAssertEqual(runtime.snapshot().frame?.estimate.state, .reliable)
        runtime.setPreview(visible: true, rotation: 90)
        XCTAssertNil(runtime.snapshot().frame)
        XCTAssertEqual(runtime.snapshot().state, "unavailable")
        runtime.configure(enabled: true, recording: false, appActive: true, sessionID: nil, sourceClock: nil)
        XCTAssertNil(runtime.snapshot().frame)
        XCTAssertEqual(runtime.snapshot().state, "paused")
    }

    @MainActor func testUnmappedAndStaleTimestampsNeverEnterAnalysis() throws {
        let runtime = LaneDetectionRuntime()
        runtime.configure(enabled: true, recording: true, appActive: true, sessionID: "drive", sourceClock: nil)
        runtime.setPreview(visible: true, rotation: 0)
        runtime.consumeVideoFrame(try makeFrame(timestamp: LaneDetectionRuntime.now()), orientation: .up)
        XCTAssertEqual(runtime.snapshot().metrics.admittedFrames, 0)
        runtime.configure(enabled: true, recording: true, appActive: true, sessionID: "drive", sourceClock: CMClockGetHostTimeClock())
        runtime.consumeVideoFrame(try makeFrame(timestamp: LaneDetectionRuntime.now() - 2), orientation: .up)
        XCTAssertEqual(runtime.snapshot().metrics.admittedFrames, 0)
        XCTAssertEqual(runtime.snapshot().metrics.timestampRejectedFrames, 1)
    }

    func testTimingWindowIsBoundedAndIncludesTailSpikes() {
        var window = LaneTimingWindow()
        for value in 0..<200 { window.append(Double(value)) }
        XCTAssertEqual(window.summary.maximum, 199)
        XCTAssertEqual(window.summary.p50, 135)
        XCTAssertEqual(window.summary.p95, 193)
    }

    func testLaneActivityIsIndependentOfTSRAndRequiresVisibleActiveDashcam() {
        XCTAssertTrue(LaneOverlayPolicy.shouldRun(enabled: true, previewVisible: true, recording: true, appActive: true, thermal: .nominal))
        XCTAssertFalse(LaneOverlayPolicy.shouldRun(enabled: false, previewVisible: true, recording: true, appActive: true, thermal: .nominal))
        XCTAssertFalse(LaneOverlayPolicy.shouldRun(enabled: true, previewVisible: false, recording: true, appActive: true, thermal: .nominal))
        XCTAssertFalse(LaneOverlayPolicy.shouldRun(enabled: true, previewVisible: true, recording: false, appActive: true, thermal: .nominal))
        XCTAssertFalse(LaneOverlayPolicy.shouldRun(enabled: true, previewVisible: true, recording: true, appActive: false, thermal: .nominal))
        XCTAssertTrue(LaneOverlayPolicy.shouldRun(enabled: true, previewVisible: true, recording: true, appActive: true, thermal: .fair))
        for thermal in [ProcessInfo.ThermalState.serious, .critical] {
            XCTAssertFalse(LaneOverlayPolicy.shouldRun(enabled: true, previewVisible: true, recording: true, appActive: true, thermal: thermal))
        }
    }

    func testOverlayFadesFromCaptureTimeAndRejectsFutureAndExpiredFrames() {
        XCTAssertEqual(LaneOverlayPolicy.opacity(capturedAt: 10, now: 10.3), 1, accuracy: 0.00001)
        XCTAssertEqual(LaneOverlayPolicy.opacity(capturedAt: 10, now: 10.525), 0.5, accuracy: 0.00001)
        XCTAssertEqual(LaneOverlayPolicy.opacity(capturedAt: 10, now: 10.75), 0)
        XCTAssertEqual(LaneOverlayPolicy.opacity(capturedAt: 10, now: 9.99), 0)
    }

    func testPaddedLumaRowsRotateAndCropWithoutReadingPadding() {
        // 3x2 valid image with sentinel padding in each 5-byte row.
        let source: [UInt8] = [1, 2, 3, 99, 99, 4, 5, 6, 99, 99]
        for (rotation, width, height, expected) in [
            (0, 3, 2, [UInt8](arrayLiteral: 1, 2, 3, 4, 5, 6)),
            (90, 2, 3, [UInt8](arrayLiteral: 4, 1, 5, 2, 6, 3)),
            (180, 3, 2, [UInt8](arrayLiteral: 6, 5, 4, 3, 2, 1)),
            (270, 2, 3, [UInt8](arrayLiteral: 3, 6, 2, 5, 1, 4))
        ] {
            var output = [UInt8](repeating: 0, count: width * height)
            source.withUnsafeBufferPointer { pointer in
                LaneDetectionRuntime.copyLuma(base: pointer.baseAddress!, rowStride: 5,
                    aperture: CGRect(x: 0, y: 0, width: 3, height: 2), rotation: rotation,
                    width: width, height: height, destination: &output)
            }
            XCTAssertEqual(output, expected, "rotation \(rotation)")
        }
        var crop = [UInt8](repeating: 0, count: 4)
        source.withUnsafeBufferPointer { pointer in
            LaneDetectionRuntime.copyLuma(base: pointer.baseAddress!, rowStride: 5,
                aperture: CGRect(x: 1, y: 0, width: 2, height: 2), rotation: 0,
                width: 2, height: 2, destination: &crop)
        }
        XCTAssertEqual(crop, [2, 3, 5, 6])
    }

    func testInverseRotationPreservesSensorCoordinatesForPreviewConversion() {
        let expected = CGPoint(x: 0.2, y: 0.3)
        for (rotation, point) in [
            (0, LanePoint(x: 0.2, y: 0.3)),
            (90, LanePoint(x: 0.7, y: 0.2)),
            (180, LanePoint(x: 0.8, y: 0.7)),
            (270, LanePoint(x: 0.3, y: 0.8))
        ] {
            let actual = LaneOverlayPolicy.capturePoint(point, rotation: rotation)
            XCTAssertEqual(actual.x, expected.x, accuracy: 0.00001)
            XCTAssertEqual(actual.y, expected.y, accuracy: 0.00001)
        }
    }

    func testCleanApertureConvertsCoreVideoBottomLeftOriginToPixelRows() {
        let aperture = LaneOverlayPolicy.topLeftCleanAperture(
            CGRect(x: 8, y: 10, width: 100, height: 80), sourceWidth: 192, sourceHeight: 128)
        XCTAssertEqual(aperture, CGRect(x: 8, y: 38, width: 100, height: 80))
        let estimate = LaneDetectionEstimate(left: nil, right: nil, timestampSeconds: 1, state: .unavailable)
        let frame = LaneOverlayFrame(estimate: estimate, sessionID: "test", generation: 1, frameID: 1,
            rotation: 90, sourceWidth: 192, sourceHeight: 128, cleanAperture: aperture)
        // Upright top-right maps to native top-left, including asymmetric crop.
        let point = frame.capturePoint(LanePoint(x: 1, y: 0))
        XCTAssertEqual(point.x, 8.0 / 192, accuracy: 0.00001)
        XCTAssertEqual(point.y, 38.0 / 128, accuracy: 0.00001)
    }

    @MainActor func testLifecycleInvalidatesResultsAndNotifiesOnlyActivityTransitions() {
        let runtime = LaneDetectionRuntime()
        var activity: [Bool] = []
        runtime.onActivityChange = { activity.append($0) }
        runtime.configure(enabled: true, recording: true, appActive: true, sessionID: "first", sourceClock: nil)
        XCTAssertEqual(runtime.snapshot().state, "paused")
        runtime.setPreview(visible: true, rotation: 90)
        XCTAssertEqual(runtime.snapshot().state, "unavailable")
        runtime.setPreview(visible: true, rotation: 90)
        runtime.configure(enabled: true, recording: true, appActive: false, sessionID: "first", sourceClock: nil)
        XCTAssertEqual(runtime.snapshot().state, "paused")
        XCTAssertNil(runtime.snapshot().frame)
        runtime.configure(enabled: true, recording: true, appActive: true, sessionID: "second", sourceClock: nil)
        runtime.setPreview(visible: false, rotation: 90)
        XCTAssertEqual(activity, [true, false, true, false])
    }
}

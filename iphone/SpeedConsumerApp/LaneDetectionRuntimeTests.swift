import XCTest
import AVFoundation
import ImageIO
@testable import SpeedConsumer

final class LaneDetectionRuntimeTests: XCTestCase {
    func testCadenceSeparatesDeliveryAdmissionAndPublicationWithBoundedHistory() {
        var cadence=LaneCadenceWindow()
        for index in 0...200 {
            cadence.record("delivery",now:Double(index)*0.030)
            if index%4==0 {
                cadence.record("admitted",now:Double(index)*0.030)
                cadence.record("published",now:Double(index)*0.030+0.015)
            }
        }
        let fields=cadence.diagnosticFields
        let delivery=fields["delivery"] as! [String:Any], admitted=fields["admitted"] as! [String:Any]
        XCTAssertEqual(delivery["count"] as? Int,201)
        XCTAssertEqual(delivery["intervalSamples"] as? Int,128)
        XCTAssertEqual(delivery["intervalP95Ms"] as! Double,30,accuracy:1e-8)
        XCTAssertEqual(admitted["count"] as? Int,51)
        XCTAssertEqual(admitted["intervalP95Ms"] as! Double,120,accuracy:1e-8)
        cadence.resetIntervals()
        cadence.record("delivery",now:100)
        let resumed=cadence.diagnosticFields["delivery"] as! [String:Any]
        XCTAssertEqual(resumed["count"] as? Int,202)
        XCTAssertEqual(resumed["intervalSamples"] as? Int,0)
    }

    private final class CountingConsumer: DriveVideoFrameConsumer {
        var frames = 0
        var lastOrientation: CGImagePropertyOrientation?
        func consumeVideoFrame(_ sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation) {
            frames += 1
            lastOrientation = orientation
        }
    }

    func testSharedDispatcherKeepsLaneAndTSRConsumersIndependent() throws {
        let dispatcher = DriveVideoFrameDispatcher()
        let lanes = CountingConsumer(), signs = CountingConsumer()
        dispatcher.setConsumer(signs)
        dispatcher.setLaneConsumer(lanes)
        dispatcher.setLanesEnabled(true)
        let frame = try makeFrame(timestamp: LaneDetectionRuntime.now())
        dispatcher.dispatch(frame)
        XCTAssertEqual(lanes.frames, 1)
        XCTAssertEqual(signs.frames, 0)
        dispatcher.setEnabled(true)
        dispatcher.dispatch(frame)
        XCTAssertEqual(lanes.frames, 2)
        XCTAssertEqual(signs.frames, 1)
        dispatcher.setConsumer(nil)
        dispatcher.setEnabled(false)
        dispatcher.dispatch(frame)
        XCTAssertEqual(lanes.frames, 3)
        XCTAssertEqual(signs.frames, 1)
        dispatcher.setConsumer(signs)
        dispatcher.setEnabled(true)
        dispatcher.setLanesEnabled(false)
        dispatcher.dispatch(frame)
        XCTAssertEqual(lanes.frames, 3)
        XCTAssertEqual(signs.frames, 2)
        dispatcher.setLanesEnabled(true)
        for orientation in [CGImagePropertyOrientation.right, .down, .up] {
            dispatcher.setOrientation(orientation)
            dispatcher.dispatch(frame)
            XCTAssertEqual(lanes.lastOrientation, orientation)
            XCTAssertEqual(signs.lastOrientation, orientation)
        }
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

#if DEBUG && os(iOS)
import UIKit
import Darwin
import CoreLocation
import CryptoKit

/// Opt-in integration soak on the real app owner and visible dashboard. No replay,
/// second model, synthetic GPS/speed, threshold override or alternate capture graph.
final class LaneFullWorkloadDeviceTests: XCTestCase {
    private struct Config: Decodable { let runId: String; let seconds: Double; let includePhotos: Bool?; let includeLanes: Bool? }
    @MainActor private final class Sink {
        let handle: FileHandle
        var error: String?
        var preparationMs: [Double] = [], publicationIntervalsMs: [Double] = []
        var lastPublication: Double?, peakRSS: UInt64 = 0, peakPhysicalFootprint: UInt64 = 0, diagnosticFrames=0
        init(_ url: URL) throws {
            guard !FileManager.default.fileExists(atPath:url.path),FileManager.default.createFile(atPath:url.path,contents:nil) else {
                throw NSError(domain:"LaneFullWorkloadOutputExists",code:1)
            }
            handle=try FileHandle(forWritingTo:url)
        }
        func append(_ object: [String:Any]) {
            do { var line=try JSONSerialization.data(withJSONObject:object,options:[.sortedKeys]); line.append(10); try handle.write(contentsOf:line) }
            catch { self.error=error.localizedDescription }
        }
        func preview(_ text: String) {
            guard let data=text.data(using:.utf8),let fields=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any] else { return }
            let now=ProcessInfo.processInfo.systemUptime
            diagnosticFrames+=1
            if let value=fields["preparationMs"] as? Double,preparationMs.count<20_000 { preparationMs.append(value) }
            if let lastPublication,publicationIntervalsMs.count<20_000 { publicationIntervalsMs.append((now-lastPublication)*1000) }
            lastPublication=now
            append(["kind":"lane_frame","uptime":now,"diagnostic":fields])
        }
        func finish() { try? handle.synchronize(); try? handle.close() }
    }
    private func rss() -> UInt64? {
        var info=mach_task_basic_info(),count=mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size/MemoryLayout<natural_t>.size)
        let result=withUnsafeMutablePointer(to:&info) { pointer in pointer.withMemoryRebound(to:integer_t.self,capacity:Int(count)) {
            task_info(mach_task_self_,task_flavor_t(MACH_TASK_BASIC_INFO),$0,&count)
        } }
        return result == KERN_SUCCESS ? info.resident_size : nil
    }
    private func physicalFootprint() -> UInt64? {
        var info=task_vm_info_data_t(),count=mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size/MemoryLayout<natural_t>.size)
        let result=withUnsafeMutablePointer(to:&info) { pointer in pointer.withMemoryRebound(to:integer_t.self,capacity:Int(count)) {
            task_info(mach_task_self_,task_flavor_t(TASK_VM_INFO),$0,&count)
        } }
        return result == KERN_SUCCESS ? info.phys_footprint : nil
    }
    private func hardwareIdentifier() -> String {
        var info=utsname(); uname(&info)
        let capacity=MemoryLayout.size(ofValue:info.machine)
        return withUnsafePointer(to:&info.machine) { pointer in
            pointer.withMemoryRebound(to:CChar.self,capacity:capacity) { String(cString:$0) }
        }
    }
    private func distribution(_ values: [Double]) -> [String:Any] {
        let ordered=values.sorted(); guard !ordered.isEmpty else { return ["count":0] }
        func q(_ p: Double) -> Double { ordered[min(ordered.count-1,max(0,Int(ceil(Double(ordered.count)*p))-1))] }
        return ["count":ordered.count,"p50":q(0.5),"p95":q(0.95),"p99":q(0.99),"max":ordered.last!]
    }
    @MainActor private func waitUntil(_ seconds: Double,_ condition: ()->Bool) async throws -> Bool {
        let deadline=ProcessInfo.processInfo.systemUptime+seconds
        while !condition(),ProcessInfo.processInfo.systemUptime<deadline { try await Task.sleep(nanoseconds:100_000_000) }
        return condition()
    }
    @MainActor private func previewViews(_ view: UIView) -> [DriveCameraPreview.PreviewView] {
        (view as? DriveCameraPreview.PreviewView).map { [$0] } ?? view.subviews.flatMap { previewViews($0) }
    }
    @MainActor func testRealCameraTSRLanesRecordingAndDisplay() async throws {
#if targetEnvironment(simulator)
        throw XCTSkip("Physical iPhone camera required")
#else
        executionTimeAllowance=1200
        let environment=ProcessInfo.processInfo.environment
        guard let runID=environment["LANE_FULL_WORKLOAD_RUN_ID"] else { throw XCTSkip("Explicit LANE_FULL_WORKLOAD_RUN_ID required") }
        try XCTSkipUnless(environment["YOUSPEED_SCREENSHOT_STATE"]==nil,"The real app owner must not use screenshot fixtures")
        guard runID.range(of:"^[A-Za-z0-9_-]+$",options:.regularExpression) != nil else { throw NSError(domain:"LaneFullWorkloadRunID",code:1) }
        let root=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("LaneFullWorkload",isDirectory:true)
        let config=try JSONDecoder().decode(Config.self,from:Data(contentsOf:root.appendingPathComponent("config.json")))
        guard config.runId==runID,(30...900).contains(config.seconds) else { throw NSError(domain:"LaneFullWorkloadConfig",code:1) }
        let output=root.appendingPathComponent(runID,isDirectory:true)
        guard !FileManager.default.fileExists(atPath:output.path) else { throw NSError(domain:"LaneFullWorkloadOutputExists",code:1) }
        try XCTSkipUnless(AVCaptureDevice.authorizationStatus(for:.video) == .authorized,"Camera permission must already be granted")
        let locationAuthorization=CLLocationManager().authorizationStatus
        try XCTSkipUnless(locationAuthorization == .authorizedAlways || locationAuthorization == .authorizedWhenInUse,"Actual GPS permission required; no synthetic fix is injected")
        try XCTSkipUnless(UIApplication.shared.applicationState == .active,"Unlocked foreground iPhone required")
        guard try await waitUntil(30,{ DriveSessionViewModel.testActiveInstance != nil }),let model=DriveSessionViewModel.testActiveInstance else {
            throw NSError(domain:"LaneFullWorkloadNoAppOwner",code:1)
        }
        // Keeping startup logs is reversible and preserves the prior drive's evidence.
        if model.startupLogReviewState == .choice { model.keepStartupLogs() }
        try await model.testWaitForStartupDataLoad(timeout:60)
        try XCTSkipUnless(model.startupLogReviewState == .complete && model.startupDataState == .ready && model.onboardingStateLoaded && !model.shouldPresentOnboarding,
                          "Complete normal onboarding/map startup before the device soak")
        let includePhotos=config.includePhotos ?? true
        let includeLanes=config.includeLanes ?? true
        try XCTSkipUnless(model.activePanoramaxUploadBatchIDs.isEmpty,"Finish existing uploads before the device soak")
        guard try await waitUntil(60,{ !model.panoramaxQueueMaintenanceInProgress }) else { throw NSError(domain:"LaneFullWorkloadPhotoMaintenanceBusy",code:1) }
        let photoStore=model.testPanoramaxQueueStore
        if includePhotos { try XCTSkipUnless(photoStore != nil,"The normal photo queue must be ready") }
        let originalBatches=try photoStore?.listBatches() ?? []
        let originalBatchIDs=Set(originalBatches.map(\.batchID))
        let originalPhotoFiles=originalBatches.flatMap(\.items).compactMap { item -> (URL,Int)? in
            guard let url=photoStore?.originalURL(for:item),let bytes=(try? url.resourceValues(forKeys:[.fileSizeKey]))?.fileSize else { return nil }
            return (url,bytes)
        }
        let coordinator=try XCTUnwrap(model.testDriveCaptureCoordinator)
        try XCTSkipUnless(!coordinator.isDashcamModuleActive && !coordinator.needsDashcamFinalization,"An existing user dashcam recording must finish before the soak")
        let originals=DriveCaptureCoordinator.listDashcamRecordings()
        let originalBytes=originals.reduce(Int64(0)) { $0+$1.byteSize }
        // The explicitly selected DEBUG destination is isolated from normal movie
        // retention; existing owner videos never need moving or deleting.
        let capacity=try root.resourceValues(forKeys:[.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage ?? 0
        try XCTSkipUnless(capacity>=6_000_000_000,"At least 6 GB free device storage required for bounded 4K recording plus logs")
        try FileManager.default.createDirectory(at:output,withIntermediateDirectories:false)
        let sink=try Sink(output.appendingPathComponent("events.ndjson"))
        defer { sink.finish() }
        let ownerInventory:[String:Any]=["movies":originals.map { ["name":$0.url.lastPathComponent,"bytes":$0.byteSize,"createdAtSeconds":$0.createdAt.timeIntervalSince1970] as [String:Any] },
            "movieBytes":originalBytes,"photoBatchIDs":originalBatchIDs.sorted(),"photoFileCount":originalPhotoFiles.count,
            "photoBytes":originalPhotoFiles.reduce(Int64(0)) { $0+Int64($1.1) }]
        try JSONSerialization.data(withJSONObject:ownerInventory,options:[.prettyPrinted,.sortedKeys])
            .write(to:output.appendingPathComponent("owner-media-before.json"),options:.atomic)
        let defaults=UserDefaults.standard
        let keys=["youspeed.drive_recorder.dashcam_enabled","youspeed.drive_recorder.tsr_enabled",
                  "youspeed.drive_recorder.tsr_independent_enabled","youspeed.drive_recorder.panoramax_enabled",
                  "youspeed.drive_recorder.show_detected_lanes","youspeed.panoramax_unlimited_storage","youspeed.panoramax_delete_uploaded_images"]
        let stored=Dictionary(uniqueKeysWithValues:keys.compactMap { key in defaults.object(forKey:key).map { (key,$0) } })
        let originalDashcam=model.dashcamRecordingEnabled,originalTSR=model.trafficSignRecognitionEnabled,
            originalIndependent=model.trafficSignRecognitionIndependentEnabled,originalPhotos=model.panoramaxCaptureEnabled,
            originalLanes=model.showDetectedLanes,wasDriving=model.testIsDriving,
            originalUnlimited=model.panoramaxUnlimitedStorage,originalDeleteUploaded=model.panoramaxDeleteUploadedImages
        let oldDiagnostic=model.laneDetectionRuntime.onPreviewDiagnostic
        let idleTimer=UIApplication.shared.isIdleTimerDisabled
        let device=UIDevice.current,originalBatteryMonitoring=UIDevice.current.isBatteryMonitoringEnabled
        device.isBatteryMonitoringEnabled=true
        let initialDevice:[String:Any]=["hardwareIdentifier":hardwareIdentifier(),"model":device.model,
            "systemName":device.systemName,"systemVersion":device.systemVersion,"operatingSystemVersion":ProcessInfo.processInfo.operatingSystemVersionString,
            "buildNumber":Bundle.main.object(forInfoDictionaryKey:"CFBundleVersion") ?? "unknown",
            "appVersion":Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") ?? "unknown",
            "brightness":UIScreen.main.brightness,"batteryState":device.batteryState.rawValue,"batteryLevel":device.batteryLevel,
            "charging":device.batteryState == .charging || device.batteryState == .full,
            "thermalState":ProcessInfo.processInfo.thermalState.rawValue,"availableStorageBytes":capacity]
        defer { device.isBatteryMonitoringEnabled=originalBatteryMonitoring }
        var newMovie: URL?,stopped=false,completed=false,failure: Error?
        var thermalPausedSeconds=0.0,pausedSamples=0,samples=0,maxSpeedKmh:Double?,actualDuration=0.0
        var initialTSR:TrafficSignRuntimeMetrics?,finalTSR:TrafficSignRuntimeMetrics?
        var workloadRuntime:TrafficSignRuntime?
        var failureContext:[String:Any]=[:],movieValidationFailure:String?
        var movieMetadata:[String:Any]=[:],testSessionIDs=Set<String>()
        var capturedPhotos=0,newPhotoItemCount=0,previewVisibleSamples=0,photosArchived=true,archivedPhotoIDs:[String]=[]
        var attachedPreview:DriveCameraPreview.PreviewView?
        var runStarted=ProcessInfo.processInfo.systemUptime
        model.laneDetectionRuntime.onPreviewDiagnostic = { text in oldDiagnostic?(text); sink.preview(text) }
        do {
            model.panoramaxUnlimitedStorage=true
            model.panoramaxDeleteUploadedImages=false
            model.panoramaxCaptureEnabled=false
            model.trafficSignRecognitionIndependentEnabled=false
            // The published dashboard state can lag an automatic capture transition.
            // Stop and await the actual coordinator before changing its destination.
            coordinator.stop()
            guard try await waitUntil(20,{
                !model.isDriveRecorderActive && !coordinator.needsDashcamFinalization &&
                coordinator.state != .preparing && coordinator.state != .recording && coordinator.state != .stopping
            }) else { throw NSError(domain:"LaneFullWorkloadPriorSessionDidNotStop",code:1) }
            try coordinator.setTestDashcamOutputDirectory(output)
            model.dashcamRecordingEnabled=true
            model.trafficSignRecognitionEnabled=true
            model.showDetectedLanes=includeLanes
            if !model.testIsDriving { model.startDriving() }
            model.setTrafficSignApplicationActive(true)
            try await model.testWaitForTrafficSignModelLoad(timeout:60)
            let runtime=try XCTUnwrap(model.testTrafficSignRuntime)
            workloadRuntime=runtime
            initialTSR=runtime.metrics
            UIApplication.shared.isIdleTimerDisabled=true
            model.panoramaxCaptureEnabled=includePhotos
            if let sessionID=coordinator.activeCaptureSessionID { testSessionIDs.insert(sessionID) }
            model.toggleDriveRecorder()
            guard try await waitUntil(30,{ coordinator.state == .recording && coordinator.isDashcamModuleActive && coordinator.isTrafficSignRecognitionModuleActive }) else { throw NSError(domain:"LaneFullWorkloadCaptureDidNotStart",code:1,userInfo:[NSLocalizedDescriptionKey:coordinator.lastCaptureDetail]) }
            newMovie=coordinator.dashcamFileURL
            if let sessionID=coordinator.activeCaptureSessionID { testSessionIDs.insert(sessionID) }
            guard coordinator.isDashcamModuleActive,coordinator.isTrafficSignRecognitionModuleActive,
                  coordinator.isLaneAnalysisOutputAvailable,(!includePhotos || coordinator.isPanoramaxModuleActive) else { throw NSError(domain:"LaneFullWorkloadMissingConsumer",code:1) }
            // A selected TSR checkbox is insufficient: require real completed model
            // inference, lane preparation and visible dashboard before timing the soak.
            guard try await waitUntil(60,{
                let windows=UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
                attachedPreview=windows.flatMap { previewViews($0) }.first { $0.videoPreviewLayer.session === coordinator.session && $0.testIsCameraPreviewVisible }
                return runtime.metrics.completedInferences>(initialTSR?.completedInferences ?? 0) && (!includeLanes || sink.diagnosticFrames>=3) && attachedPreview != nil
            }) else {
                throw NSError(domain:"LaneFullWorkloadNoRealInferenceOrLaneFrames",code:1,
                    userInfo:[NSLocalizedDescriptionKey:"Camera started but real GPS/map eligibility, TSR or visible lane processing is unavailable"])
            }
            sink.preparationMs=[]; sink.publicationIntervalsMs=[]; sink.lastPublication=nil; sink.diagnosticFrames=0
            initialTSR=runtime.metrics
            runStarted=ProcessInfo.processInfo.systemUptime
            sink.append(["kind":"start","runId":runID,"seconds":config.seconds,"build":Bundle.main.object(forInfoDictionaryKey:"CFBundleVersion") ?? "unknown",
                         "device":initialDevice,"photoMinimumDistanceMeters":model.panoramaxMinimumDistanceMeters,"photoMinimumIntervalSeconds":model.panoramaxMinimumIntervalSeconds,
                         "modelPackId":runtime.verifiedPack.manifest.packId,"sessionPreset":coordinator.session.sessionPreset.rawValue,
                         "screenOrientation":model.screenOrientation.rawValue,"debugLoggingEnabled":model.debugLoggingEnabled,
                         "speedSource":"real_location_manager","syntheticSpeedOrGPS":false,"panoramaxEnabled":includePhotos,
                         "scope":"Actual app owner, map/GPS state, one loaded app TSR runtime, independent lanes, existing dashboard preview and dashcam encoder" ])
            var previous=runStarted,previousPaused=false
            var lastInferenceProgress=runStarted,lastLaneProgress=runStarted
            var previousInferenceCount=runtime.metrics.completedInferences,previousLaneCount=model.laneDetectionRuntime.snapshot().metrics.processedFrames
            while ProcessInfo.processInfo.systemUptime-runStarted<config.seconds {
                let now=ProcessInfo.processInfo.systemUptime
                if previousPaused { thermalPausedSeconds+=now-previous }
                previous=now
                guard UIApplication.shared.applicationState == .active,coordinator.state == .recording,
                      coordinator.isDashcamModuleActive,attachedPreview?.testIsCameraPreviewVisible==true else { throw NSError(domain:"LaneFullWorkloadInterrupted",code:1) }
                previewVisibleSamples+=1
                let thermal=ProcessInfo.processInfo.thermalState
                previousPaused=thermal == .serious || thermal == .critical
                if previousPaused { pausedSamples+=1 }
                let lane=model.laneDetectionRuntime.snapshot(),tsr=runtime.metrics
                finalTSR=tsr
                if tsr.completedInferences != previousInferenceCount || thermal == .critical { lastInferenceProgress=now }
                if lane.metrics.processedFrames != previousLaneCount || previousPaused { lastLaneProgress=now }
                previousInferenceCount=tsr.completedInferences; previousLaneCount=lane.metrics.processedFrames
                guard now-lastInferenceProgress<30,(!includeLanes || now-lastLaneProgress<15) else { throw NSError(domain:"LaneFullWorkloadProcessingStalled",code:1) }
                let resident=rss()
                if let resident { sink.peakRSS=max(sink.peakRSS,resident) }
                let footprint=physicalFootprint()
                if let footprint { sink.peakPhysicalFootprint=max(sink.peakPhysicalFootprint,footprint) }
                if model.currentSpeedKmh.isFinite { maxSpeedKmh=max(maxSpeedKmh ?? 0,model.currentSpeedKmh) }
                let movieBytes=newMovie.flatMap { try? $0.resourceValues(forKeys:[.fileSizeKey]).fileSize }
                sink.append(["kind":"sample","elapsedSeconds":now-runStarted,"thermalState":thermal.rawValue,"thermalStatus":thermal.rawValue,
                             "previewVisible":attachedPreview?.testIsCameraPreviewVisible==true,"movieActive":coordinator.isDashcamModuleActive,"cameraState":String(describing:coordinator.state),
                             "recognitionEnabled":coordinator.isTrafficSignRecognitionModuleActive,"lanesEnabled":model.showDetectedLanes,"photoCount":coordinator.capturedImageCount,
                             "laneThermalPaused":previousPaused,"laneState":lane.state,"residentBytes":resident as Any? ?? NSNull(),"rssBytes":resident as Any? ?? NSNull(),
                             "physicalFootprintBytes":footprint as Any? ?? NSNull(),"brightness":attachedPreview?.window?.screen.brightness as Any? ?? NSNull(),
                             "batteryState":device.batteryState.rawValue,"batteryLevel":device.batteryLevel,
                             "laneProcessed":lane.metrics.processedFrames,"laneRejected":lane.metrics.rejectedResults,
                             "laneThrottled":lane.metrics.cadenceSkippedFrames,"laneReplaced":lane.metrics.replacedFrames,
                             "lanePreprocessRollingP95Ms":lane.metrics.preprocessing.p95,"laneDetectionRollingP95Ms":lane.metrics.detection.p95,
                             "laneCaptureToResultRollingP95Ms":lane.metrics.captureToResult.p95,
                             "tsrAccepted":tsr.acceptedLiveFrames,"tsrCompleted":tsr.completedInferences,"tsrReplaced":tsr.replacedPendingLiveFrames,
                             "tsrThrottled":tsr.cadenceDroppedLiveFrames,"movieBytes":movieBytes as Any? ?? NSNull(),
                             "speedKmh":model.currentSpeedKmh as Any? ?? NSNull(),"gpsFixCount":model.gpsFixCount,
                             "sourceGeometry":model.lanePreviewSourceGeometry.map { "\($0.rawWidth)x\($0.rawHeight)" } ?? "unknown"])
                samples+=1
                if runtime.unavailability != nil { throw NSError(domain:"LaneFullWorkloadTSRTerminated",code:1) }
                if let error=sink.error { throw NSError(domain:"LaneFullWorkloadLogFailure",code:1,userInfo:[NSLocalizedDescriptionKey:error]) }
                let free=try output.resourceValues(forKeys:[.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage ?? 0
                guard free>=750_000_000 else { throw NSError(domain:"LaneFullWorkloadStorageGuard",code:1) }
                try await Task.sleep(nanoseconds:1_000_000_000)
            }
            actualDuration=ProcessInfo.processInfo.systemUptime-runStarted
            if previousPaused { thermalPausedSeconds+=ProcessInfo.processInfo.systemUptime-previous }
            finalTSR=runtime.metrics
            completed=true
        } catch {
            failure=error; actualDuration=ProcessInfo.processInfo.systemUptime-runStarted
            finalTSR=workloadRuntime?.metrics
            let problem=error as NSError
            failureContext=["domain":problem.domain,"code":problem.code,"elapsedSeconds":actualDuration,
                "applicationState":UIApplication.shared.applicationState.rawValue,
                "cameraState":String(describing:coordinator.state),"captureDetail":coordinator.lastCaptureDetail,
                "movieActive":coordinator.isDashcamModuleActive,"movieNeedsFinalization":coordinator.needsDashcamFinalization,
                "previewVisible":attachedPreview?.testIsCameraPreviewVisible==true,
                "lanesSelected":model.showDetectedLanes,"dashcamSelected":model.dashcamRecordingEnabled,
                "tsrActive":coordinator.isTrafficSignRecognitionModuleActive,
                "thermalState":ProcessInfo.processInfo.thermalState.rawValue,
                "tsrUnavailable":workloadRuntime?.unavailability.map { String(describing:$0) } as Any? ?? NSNull()]
            sink.append(["kind":"failure","context":failureContext,"description":error.localizedDescription])
        }
        // Cleanup is awaited even after failed startup/soak. Restore exact persisted
        // values, including absent keys; stop only the test's new recording.
        if let url=coordinator.dashcamFileURL,!originals.contains(where:{ $0.url==url }) { newMovie=url }
        capturedPhotos=coordinator.capturedImageCount
        model.panoramaxCaptureEnabled=false
        coordinator.stop()
        stopped=(try? await waitUntil(30,{
            !model.isDriveRecorderActive && !coordinator.needsDashcamFinalization &&
            coordinator.state != .preparing && coordinator.state != .recording && coordinator.state != .stopping
        })) ?? false
        // Exact test URLs retain their individual retention exemption for any late
        // delegate callback; clearing the override only affects future captures.
        try coordinator.setTestDashcamOutputDirectory(nil)
        if !wasDriving { model.stopDriving() }
        model.laneDetectionRuntime.onPreviewDiagnostic=oldDiagnostic
        // Archive only batches created by the test-owned capture sessions. Copy and
        // hash every original/thumbnail plus metadata before removing any test item.
        // Restoring quota with new items still in the queue could evict older images.
        if stopped,let store=photoStore {
            do {
                let created=try store.listBatches().filter { !originalBatchIDs.contains($0.batchID) && testSessionIDs.contains($0.captureSessionID) }
                newPhotoItemCount=created.reduce(0) { $0+$1.items.count }
                var deleteByBatch:[String:Set<String>]=[:]
                for batch in created where !batch.items.isEmpty {
                    let folder=output.appendingPathComponent("photos",isDirectory:true).appendingPathComponent(batch.batchID,isDirectory:true)
                    try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
                    try JSONEncoder().encode(batch).write(to:folder.appendingPathComponent("batch.json"),options:.atomic)
                    for item in batch.items {
                        guard item.itemID==URL(fileURLWithPath:item.itemID).lastPathComponent,let original=store.originalURL(for:item) else { throw NSError(domain:"LaneFullWorkloadPhotoPath",code:1) }
                        let sources=[("original",original),("thumbnail",store.thumbnailURL(for:item))].compactMap { label,url -> (String,URL)? in url.map { (label,$0) } }
                        for (label,source) in sources {
                            let target=folder.appendingPathComponent(item.itemID+"-"+label+"."+source.pathExtension)
                            try FileManager.default.copyItem(at:source,to:target)
                            guard SHA256.hash(data:try Data(contentsOf:source)) == SHA256.hash(data:try Data(contentsOf:target)) else { throw NSError(domain:"LaneFullWorkloadPhotoArchiveIntegrity",code:1) }
                        }
                        deleteByBatch[batch.batchID,default:[]].insert(item.itemID)
                    }
                }
                for (batchID,ids) in deleteByBatch {
                    let deletion=try store.deleteItems(batchID:batchID,itemIDs:ids)
                    guard !deletion.hasFailures,Set(deletion.deletedItemIDs)==ids else { throw NSError(domain:"LaneFullWorkloadPhotoQueueCleanup",code:1) }
                    archivedPhotoIDs.append(contentsOf:ids.sorted())
                }
                model.refreshPanoramaxBatches()
            } catch { photosArchived=false;completed=false;if failure==nil { failure=error } }
        } else if includePhotos { photosArchived=false }
        model.showDetectedLanes=originalLanes
        model.trafficSignRecognitionEnabled=originalTSR
        model.dashcamRecordingEnabled=originalDashcam
        if photosArchived {
            model.panoramaxUnlimitedStorage=originalUnlimited
            model.panoramaxDeleteUploadedImages=originalDeleteUploaded
        }
        model.trafficSignRecognitionIndependentEnabled=originalIndependent
        model.panoramaxCaptureEnabled=originalPhotos
        for key in keys where photosArchived || !["youspeed.panoramax_unlimited_storage","youspeed.panoramax_delete_uploaded_images"].contains(key) { if let value=stored[key] { defaults.set(value,forKey:key) } else { defaults.removeObject(forKey:key) } }
        UIApplication.shared.isIdleTimerDisabled=idleTimer
        if stopped,let movie=newMovie,FileManager.default.fileExists(atPath:movie.path),!originals.contains(where:{ $0.url==movie }) {
            do {
                let retained=output.appendingPathComponent("recording.mov")
                try FileManager.default.moveItem(at:movie,to:retained)
                model.refreshDashcamRecordings()
                let asset=AVURLAsset(url:retained)
                let duration=try await asset.load(.duration)
                let tracks=try await asset.loadTracks(withMediaType:.video)
                let dimensions=try await tracks.first?.load(.naturalSize)
                movieMetadata=["file":"recording.mov","durationSeconds":duration.seconds,
                               "width":dimensions.map { Double($0.width) } as Any? ?? NSNull(),"height":dimensions.map { Double($0.height) } as Any? ?? NSNull()]
                if !duration.seconds.isFinite || duration.seconds<config.seconds*0.9 || tracks.isEmpty {
                    completed=false;movieValidationFailure="LaneFullWorkloadMovieInvalid"
                    if failure==nil { failure=NSError(domain:"LaneFullWorkloadMovieInvalid",code:1) }
                }
            } catch { completed=false;movieValidationFailure=error.localizedDescription;if failure==nil { failure=error } }
        }
        if movieMetadata.isEmpty { completed=false;if failure==nil { failure=NSError(domain:"LaneFullWorkloadMovieMissing",code:1) } }
        let photosPreserved=originalPhotoFiles.allSatisfy { url,bytes in (try? url.resourceValues(forKeys:[.fileSizeKey]))?.fileSize==bytes }
        let preserved=originals.allSatisfy { before in
            guard let after=try? before.url.resourceValues(forKeys:[.fileSizeKey]) else { return false }
            return Int64(after.fileSize ?? -1)==before.byteSize
        }
        let preferencesRestored=keys.allSatisfy { key in
            let actual=defaults.object(forKey:key)
            if let expected=stored[key] as? NSObject { return (actual as? NSObject)==expected }
            return actual==nil
        }
        let startInferences=initialTSR?.completedInferences ?? 0,endInferences=finalTSR?.completedInferences ?? initialTSR?.completedInferences ?? 0
        let inferenceFrames=endInferences>=startInferences ? endInferences-startInferences : 0
        let summary:[String:Any]=["schemaVersion":1,"runId":runID,"platform":"iOS","completed":completed && stopped && preserved && photosPreserved && preferencesRestored,
            "complete":completed && stopped && preserved && photosPreserved && preferencesRestored,"device":initialDevice,
            "buildNumber":Bundle.main.object(forInfoDictionaryKey:"CFBundleVersion") ?? "unknown",
            "initialOwnerMovieBytes":originalBytes,"initialOwnerMovieCount":originals.count,"movieOutputIsolatedFromOwnerRetention":true,
            "requestedSeconds":config.seconds,"measuredSeconds":actualDuration,"sustained":actualDuration>=600,
            "testRecordingFinalized":stopped,"ownerMoviesPreserved":preserved,"ownerPhotoFilesPreserved":photosPreserved,"targetPreferencesRestoredExactly":preferencesRestored,
            "normalAutomaticCaptureRestored":originalPhotos || originalIndependent,"movie":movieMetadata,
            "preparationMs":distribution(sink.preparationMs),"mainActorDiagnosticDeliveryIntervalMs":distribution(sink.publicationIntervalsMs),
            "diagnosticFrames":sink.diagnosticFrames,"peakSampledResidentBytes":sink.peakRSS,"memorySamples":samples,
            "laneThermalPausedSeconds":thermalPausedSeconds,"thermalPausedSamples":pausedSamples,"maximumActualSpeedKmh":maxSpeedKmh as Any? ?? NSNull(),
            "tsrCompletedDuringSoak":inferenceFrames,"inferenceFrames":inferenceFrames,"laneFrames":sink.diagnosticFrames,
            "scene":"real_physical_camera_uncontrolled","syntheticLocation":false,"samples":samples,
            "includeLanes":includeLanes,"includePhotos":includePhotos,"photoCount":newPhotoItemCount,"cameraReportedPhotoCount":capturedPhotos,"photoCaptureWorkloadExercised":newPhotoItemCount>0,
            "archivedPhotoItemIDs":archivedPhotoIDs,"photoArchiveComplete":photosArchived,"previewVisibleSamples":previewVisibleSamples,
            "peakSampledRssBytes":sink.peakRSS,
            "peakSampledPhysicalFootprintBytes":sink.peakPhysicalFootprint,
            "failure":failure?.localizedDescription as Any? ?? NSNull(),
            "failureContext":failureContext,"movieValidationFailure":movieValidationFailure as Any? ?? NSNull(),
            "scope":"Real normal-app capture, TSR, lanes, dashboard and dashcam; GPS/map are actual device state. Panoramax selection is explicit (default on); captures use actual GPS and original user cadence, so a stationary run can yield zero photos. Only test-created photos are copied and hash-verified with metadata into this artifact before removing their queue items; no upload is started. If archiving fails, storage protection stays enabled and restoration reports failure. Stationary run does not establish driving cadence/recognition accuracy. RSS is sampled process memory, not exact peak. Thermal time is sampled serious/critical interval; delivery intervals include MainActor scheduling. Existing automatic camera behavior resumes only if originally selected."]
        let summaryURL=output.appendingPathComponent("summary.json")
        try JSONSerialization.data(withJSONObject:summary,options:[.prettyPrinted,.sortedKeys]).write(to:summaryURL,options:.atomic)
        let attachment=XCTAttachment(contentsOfFile:summaryURL);attachment.lifetime = .keepAlways;add(attachment)
        XCTAssertTrue(stopped,"Test movie did not finalize");XCTAssertTrue(preserved,"An owner's existing recording changed");XCTAssertTrue(photosPreserved,"An owner's existing photo changed");XCTAssertTrue(preferencesRestored,"Preference restoration failed")
        if let failure { throw failure }
        XCTAssertTrue(completed)
        if includeLanes { XCTAssertGreaterThan(sink.diagnosticFrames,0) }
        else { XCTAssertEqual(sink.diagnosticFrames,0,"Lane display stays off while dashcam records") }
#endif
    }
}
#endif

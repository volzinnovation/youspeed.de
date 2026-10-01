@preconcurrency import AVFoundation
import Foundation
import ImageIO
import OSLog
import UIKit

/// Preview-only analysis. This runtime never emits traffic-sign or speed-limit events.
enum LaneOverlayPolicy {
    static let sampleInterval = 0.2
    static let fadeAfter = 0.30
    static let expireAfter = 0.75

    static func opacity(capturedAt: Double, now: Double) -> Double {
        let age = now - capturedAt
        guard age >= 0, age < expireAfter else { return 0 }
        return age <= fadeAfter ? 1 : (expireAfter - age) / (expireAfter - fadeAfter)
    }

    static func shouldRun(enabled: Bool, previewVisible: Bool, recording: Bool, appActive: Bool, thermal: ProcessInfo.ThermalState) -> Bool {
        enabled && previewVisible && recording && appActive && thermal != .serious && thermal != .critical
    }

    /// Inverse of the rotation applied to native rear-camera pixels. The
    /// preview layer then applies its own rotation, mirroring and aspect fill.
    static func capturePoint(_ point: LanePoint, rotation: Int) -> CGPoint {
        switch rotation {
        case 90: return CGPoint(x: point.y, y: 1 - point.x)
        case 180: return CGPoint(x: 1 - point.x, y: 1 - point.y)
        case 270: return CGPoint(x: 1 - point.y, y: point.x)
        default: return CGPoint(x: point.x, y: point.y)
        }
    }

    static func topLeftCleanAperture(_ bottomLeft: CGRect, sourceWidth: Int, sourceHeight: Int) -> CGRect {
        // CoreVideo returns clean apertures in CoreImage's bottom-left space;
        // CVPixelBuffer Y rows and detector coordinates have a top-left origin.
        CGRect(x: bottomLeft.minX, y: Double(sourceHeight) - bottomLeft.maxY,
               width: bottomLeft.width, height: bottomLeft.height)
            .intersection(CGRect(x: 0, y: 0, width: sourceWidth, height: sourceHeight)).integral
    }
}

struct LaneRuntimeMetrics: Sendable {
    var admittedFrames = 0
    var replacedFrames = 0
    var processedFrames = 0
    var rejectedResults = 0
    var cadenceSkippedFrames = 0
    var timestampRejectedFrames = 0
    var preprocessingMilliseconds = 0.0
    var detectionMilliseconds = 0.0
    var captureToResultMilliseconds = 0.0
    var overlayAgeMilliseconds = 0.0
    var preprocessing = LaneTimingSummary()
    var detection = LaneTimingSummary()
    var captureToResult = LaneTimingSummary()
}

struct LaneTimingSummary: Sendable {
    var p50 = 0.0
    var p95 = 0.0
    var maximum = 0.0
}

/// Bounded measurements retain spikes without retaining camera images.
struct LaneTimingWindow {
    private var values = [Double]()
    private var next = 0
    mutating func append(_ value: Double) {
        if values.count < 128 { values.append(value) }
        else { values[next] = value }
        next = (next + 1) % 128
    }
    var summary: LaneTimingSummary {
        let sorted = values.sorted()
        guard !sorted.isEmpty else { return LaneTimingSummary() }
        return LaneTimingSummary(p50: sorted[Int(Double(sorted.count - 1) * 0.50)],
            p95: sorted[Int(ceil(Double(sorted.count - 1) * 0.95))], maximum: sorted.last ?? 0)
    }
}

/// Same stage meanings/window cap as Android; stores scalar timings only.
struct LaneCadenceWindow {
    private struct Stage { var count=0; var last:Double?; var intervals=[Double]() }
    private var stages:[String:Stage]=["delivery":Stage(),"admitted":Stage(),"published":Stage()]
    mutating func record(_ name:String, now:Double) {
        var stage=stages[name]!
        if let last=stage.last,now>=last {
            if stage.intervals.count==128 { stage.intervals.removeFirst() }
            stage.intervals.append((now-last)*1000)
        }
        stage.count+=1; stage.last=now; stages[name]=stage
    }
    mutating func resetIntervals() {
        for name in ["delivery","admitted","published"] { stages[name]?.last=nil; stages[name]?.intervals=[] }
    }
    var diagnosticFields:[String:Any] {
        stages.mapValues { stage in
            let sorted=stage.intervals.sorted()
            var fields:[String:Any]=["count":stage.count,"intervalSamples":sorted.count]
            if !sorted.isEmpty {
                fields["intervalP50Ms"]=sorted[Int(ceil(Double(sorted.count-1)*0.5))]
                fields["intervalP95Ms"]=sorted[Int(ceil(Double(sorted.count-1)*0.95))]
                fields["intervalMaxMs"]=sorted.last!
            }
            return fields
        }
    }
}

struct LaneOverlayFrame: Sendable {
    let estimate: LaneDetectionEstimate
    let sessionID: String
    let generation: UInt64
    let frameID: UInt64
    let rotation: Int
    let sourceWidth: Int
    let sourceHeight: Int
    // Full source-buffer coordinates, including a nontrivial clean aperture.
    let cleanAperture: CGRect

    func capturePoint(_ point: LanePoint) -> CGPoint {
        let p = LaneOverlayPolicy.capturePoint(point, rotation: rotation)
        return CGPoint(x: (cleanAperture.minX + p.x * cleanAperture.width) / Double(sourceWidth),
                       y: (cleanAperture.minY + p.y * cleanAperture.height) / Double(sourceHeight))
    }
}

struct LaneOverlaySnapshot {
    let frame: LaneOverlayFrame?
    let state: String
    let metrics: LaneRuntimeMetrics
}

final class LaneDetectionRuntime: DriveVideoFrameConsumer, @unchecked Sendable {
    private static let logger = Logger(subsystem: "de.youspeed.SpeedConsumer", category: "lanes")
    private final class Buffer { var bytes = [UInt8]() }
    private struct Frame {
        let buffer: Buffer
        let width: Int
        let height: Int
        let timestamp: Double
        let sessionID: String
        let generation: UInt64
        let id: UInt64
        let rotation: Int
        let sourceWidth: Int
        let sourceHeight: Int
        let cleanAperture: CGRect
        var roadFrame: RoadPathCameraFrame? = nil
    }

    private let lock = NSLock()
    private let queue = DispatchQueue(label: "de.youspeed.lanes", qos: .utility)
    // Only the serial worker touches these; retain confirmation across idle
    // periods between 5 Hz frame admissions.
    private var tracker = LaneTracker()
    private var trackerGeneration: UInt64?
    private var freeBuffers = [Buffer(), Buffer()]
    private var pending: Frame?
    private var workerScheduled = false
    private var enabled = false
    private var previewVisible = false
    private var recording = false
    private var appActive = true
    private var accepting = false
    private var sessionID: String?
    private var sourceClock: CMClock?
    private var rotation = 90
    private var geometry: String?
    private var generation: UInt64 = 0
    private var nextFrameID: UInt64 = 0
    private var lastAdmission = -Double.infinity
    private var result: LaneOverlayFrame?
    private var metrics = LaneRuntimeMetrics()
    private var cadence = LaneCadenceWindow()
    private var lastCadenceReport = -Double.infinity
    private var preprocessingTimes = LaneTimingWindow()
    private var detectionTimes = LaneTimingWindow()
    private var captureToResultTimes = LaneTimingWindow()
    private var thermalObserver: NSObjectProtocol?
    @MainActor var onPreviewDiagnostic: ((String) -> Void)?
    @MainActor var onActivityChange: ((Bool) -> Void)?

    private let previewSession: RoadPathSession?
    private let calibrationStore: VisualRoadCalibrationStore?
    init(previewSession: RoadPathSession? = nil, calibrationStore: VisualRoadCalibrationStore? = nil) {
        self.previewSession = previewSession
        self.calibrationStore = calibrationStore
        thermalObserver = NotificationCenter.default.addObserver(forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.refreshActivity() }
        }
    }

    deinit {
        if let thermalObserver { NotificationCenter.default.removeObserver(thermalObserver) }
    }

    static func now() -> Double { CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock())) }

    @MainActor func configure(enabled: Bool, recording: Bool, appActive: Bool, sessionID: String?, sourceClock: CMClock?) {
        lock.lock()
        let changed = self.enabled != enabled || self.recording != recording || self.appActive != appActive || self.sessionID != sessionID
        self.enabled = enabled
        self.recording = recording
        self.appActive = appActive
        self.sessionID = sessionID
        self.sourceClock = sourceClock
        if changed { invalidateLocked() }
        lock.unlock()
        refreshActivity()
    }

    @MainActor func setPreview(visible: Bool, rotation: Int) {
        lock.lock()
        if previewVisible != visible || self.rotation != rotation {
            previewVisible = visible
            self.rotation = rotation
            invalidateLocked()
        }
        lock.unlock()
        refreshActivity()
    }

    @MainActor private func refreshActivity() {
        lock.lock()
        let value = LaneOverlayPolicy.shouldRun(enabled: enabled, previewVisible: previewVisible,
            recording: recording, appActive: appActive, thermal: ProcessInfo.processInfo.thermalState) && sessionID != nil
        let changed = accepting != value
        if changed { invalidateLocked() }
        accepting = value
        lock.unlock()
        if changed { onActivityChange?(value) }
    }

    private func invalidateLocked() {
        previewSession?.invalidateOverlay()
        generation &+= 1
        result = nil
        geometry = nil
        lastAdmission = -Double.infinity
        cadence.resetIntervals()
        if let pending { freeBuffers.append(pending.buffer); self.pending = nil }
    }

    func snapshot(now: Double = LaneDetectionRuntime.now()) -> LaneOverlaySnapshot {
        lock.lock()
        defer { lock.unlock() }
        let fresh = result.flatMap { LaneOverlayPolicy.opacity(capturedAt: $0.estimate.timestampSeconds, now: now) > 0 ? $0 : nil }
        if let fresh { metrics.overlayAgeMilliseconds = (now - fresh.estimate.timestampSeconds) * 1_000 }
        return LaneOverlaySnapshot(frame: fresh, state: accepting ? (fresh?.estimate.state.rawValue ?? "unavailable") : "paused", metrics: metrics)
    }

    func consumeVideoFrame(_ sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation) {
        // The frame dispatcher owns the CVPixelBuffer. Copy only an admitted,
        // downsampled Y plane synchronously; no camera buffer escapes this call.
        let started = Self.now()
        lock.lock()
        defer { lock.unlock() }
        cadence.record("delivery",now:started)
        guard accepting, let sessionID, let sourceClock, let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer),
              CVPixelBufferGetPlaneCount(pixelBuffer) >= 1 else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let hostPTS = CMSyncConvertTime(pts, from: sourceClock, to: CMClockGetHostTimeClock())
        let timestamp = CMTimeGetSeconds(hostPTS)
        guard timestamp.isFinite, timestamp <= started + 0.05, started - timestamp < LaneOverlayPolicy.expireAfter else {
            metrics.timestampRejectedFrames += 1
            return
        }
        if timestamp < lastAdmission { invalidateLocked() }
        guard timestamp - lastAdmission >= (previewSession == nil ? LaneOverlayPolicy.sampleInterval : 0.1) else {
            metrics.cadenceSkippedFrames += 1
            return
        }
        if previewSession != nil {
            guard let capture = RoadPathCameraCapture.capture(sampleBuffer, orientation: orientation, sourceClock: sourceClock),
                  let road = capture.frame(pixel: pixelBuffer, orientation: orientation, visualCalibration: calibrationStore?.snapshot()) else { return }
            let key = "\(road.geometryId):\(road.visualCalibration?.revision ?? "none")"
            if geometry != key { invalidateLocked(); geometry = key }
            let buffer: Buffer
            if let pending { buffer = pending.buffer; self.pending = nil; metrics.replacedFrames += 1 }
            else if let available = freeBuffers.popLast() { buffer = available }
            else { return }
            buffer.bytes = road.grayscale
            metrics.admittedFrames += 1
            cadence.record("admitted",now:started)
            metrics.preprocessingMilliseconds = road.preprocessingMs
            preprocessingTimes.append(road.preprocessingMs)
            lastAdmission = timestamp; nextFrameID &+= 1
            pending = Frame(buffer: buffer, width: road.width, height: road.height, timestamp: timestamp,
                sessionID: sessionID, generation: generation, id: nextFrameID, rotation: road.rotationDegrees,
                sourceWidth: road.rawWidth, sourceHeight: road.rawHeight,
                cleanAperture: CGRect(x:0,y:0,width:road.rawWidth,height:road.rawHeight), roadFrame: road)
            if !workerScheduled { workerScheduled = true; queue.async { [weak self] in self?.processFrames() } }
            return
        }
        let sourceWidth = CVPixelBufferGetWidthOfPlane(pixelBuffer, 0)
        let sourceHeight = CVPixelBufferGetHeightOfPlane(pixelBuffer, 0)
        let aperture = LaneOverlayPolicy.topLeftCleanAperture(CVImageBufferGetCleanRect(pixelBuffer),
            sourceWidth: sourceWidth, sourceHeight: sourceHeight)
        guard aperture.width > 1, aperture.height > 1 else { return }
        let geometryKey = "\(sourceWidth):\(sourceHeight):\(aperture):\(rotation)"
        if geometry != geometryKey { invalidateLocked(); geometry = geometryKey }
        let rotated = rotation == 90 || rotation == 270
        let uprightWidth = rotated ? aperture.height : aperture.width
        let uprightHeight = rotated ? aperture.width : aperture.height
        let scale = min(384 / uprightWidth, 768 / uprightHeight, 1)
        let width = max(2, Int(uprightWidth * scale))
        let height = max(2, Int(uprightHeight * scale))
        let buffer: Buffer
        if let pending {
            buffer = pending.buffer
            self.pending = nil
            metrics.replacedFrames += 1
        } else if let available = freeBuffers.popLast() {
            buffer = available
        } else { return }
        if buffer.bytes.count != width * height { buffer.bytes = [UInt8](repeating: 0, count: width * height) }
        guard CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly) == kCVReturnSuccess else { freeBuffers.append(buffer); return }
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0) else { freeBuffers.append(buffer); return }
        Self.copyLuma(base: base.assumingMemoryBound(to: UInt8.self), rowStride: CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0),
            aperture: aperture, rotation: rotation, width: width, height: height, destination: &buffer.bytes)
        metrics.admittedFrames += 1
        cadence.record("admitted",now:started)
        metrics.preprocessingMilliseconds = (Self.now() - started) * 1_000
        preprocessingTimes.append(metrics.preprocessingMilliseconds)
        lastAdmission = timestamp
        nextFrameID &+= 1
        pending = Frame(buffer: buffer, width: width, height: height, timestamp: timestamp, sessionID: sessionID,
            generation: generation, id: nextFrameID, rotation: rotation, sourceWidth: sourceWidth,
            sourceHeight: sourceHeight, cleanAperture: aperture)
        if !workerScheduled {
            workerScheduled = true
            queue.async { [weak self] in self?.processFrames() }
        }
    }

    /// Kept separate so padded camera rows and all rotations can be tested.
    static func copyLuma(base: UnsafePointer<UInt8>, rowStride: Int, aperture: CGRect, rotation: Int,
                         width: Int, height: Int, destination: inout [UInt8]) {
        for y in 0..<height {
            for x in 0..<width {
                let point = LaneOverlayPolicy.capturePoint(LanePoint(x: (Double(x) + 0.5) / Double(width), y: (Double(y) + 0.5) / Double(height)), rotation: rotation)
                let sx = Int(aperture.minX) + min(Int(aperture.width) - 1, max(0, Int(point.x * aperture.width)))
                let sy = Int(aperture.minY) + min(Int(aperture.height) - 1, max(0, Int(point.y * aperture.height)))
                destination[y * width + x] = base[sy * rowStride + sx]
            }
        }
    }

    private func processFrames() {
        let detector = LaneDetector()
        while true {
            lock.lock()
            guard let frame = pending else { workerScheduled = false; lock.unlock(); return }
            pending = nil
            lock.unlock()
            if trackerGeneration != frame.generation { tracker.reset(); trackerGeneration = frame.generation }
            let started = Self.now()
            if let previewSession, let road = frame.roadFrame {
                let scope = TSRApplicabilityScope(sessionId:frame.sessionID,bundleId:"camera",cameraGeometryId:road.geometryId,
                    generation:frame.generation,contextGeneration:frame.generation,traversalEpoch:frame.generation)
                let prepared = previewSession.prepare(frame:road,frameId:"lane-\(frame.id)",scope:scope, shouldPublish: { [self] in
                    lock.lock(); defer { lock.unlock() }
                    return accepting && generation == frame.generation && sessionID == frame.sessionID
                })
                let finished = Self.now()
                lock.lock()
                metrics.processedFrames += 1
                metrics.detectionMilliseconds = (finished-started)*1000
                metrics.captureToResultMilliseconds = (finished-frame.timestamp)*1000
                detectionTimes.append(metrics.detectionMilliseconds)
                captureToResultTimes.append(metrics.captureToResultMilliseconds)
                metrics.preprocessing = preprocessingTimes.summary
                metrics.detection = detectionTimes.summary
                metrics.captureToResult = captureToResultTimes.summary
                if accepting && generation == frame.generation && sessionID == frame.sessionID {
                    cadence.record("published",now:finished)
                }
                let cadenceFields:[String:Any]?
                if finished-lastCadenceReport>=5 {
                    lastCadenceReport=finished
                    cadenceFields=cadence.diagnosticFields.merging([
                        "throttled":metrics.cadenceSkippedFrames,"replaced":metrics.replacedFrames,
                        "timestampRejected":metrics.timestampRejectedFrames,"processed":metrics.processedFrames,
                        "admissionIntervalMs":100],uniquingKeysWith:{ _,new in new })
                } else { cadenceFields=nil }
                freeBuffers.append(frame.buffer)
                lock.unlock()
                Self.logger.info("lane_preview_frame id=\(frame.id) source=\(road.sourceTimestampSeconds ?? 0) preparation_ms=\(prepared.preparationMs) budget=\(prepared.geometry.budgetExceeded) visible=\(prepared.presentation.visibleBoundaryIndices.count)")
                let selected = prepared.presentation.selectedBoundaries(from:prepared.geometry.boundaries)
                let invalidIndices = prepared.presentation.visibleBoundaryIndices.filter { !prepared.geometry.boundaries.indices.contains($0) }.count
                let diagnosticPresentation = invalidIndices == 0 ? prepared.presentation :
                    RoadBoundaryPresentationSnapshot.rejected("geometry_selection_mismatch",rawCount:prepared.geometry.boundaries.count)
                var fields: [String:Any] = ["frameId":"lane-\(frame.id)","sourceTimestampSeconds":road.sourceTimestampSeconds as Any? ?? NSNull(),
                    "capturedAtSeconds":road.capturedAtSeconds,"preparationMs":prepared.preparationMs,
                    "preparationTargetMs":50,"preparationTargetExceeded":prepared.performanceTargetExceeded,
                    "invalidVisibleBoundaryIndexCount":invalidIndices,
                    "lumaSamplingMs":road.preprocessingMs,"filterMs":prepared.filterMs,"geometryMs":prepared.geometryMs,
                    "queueWaitMs":max(0,(started-road.startedAt)*1000-road.preprocessingMs),
                    "thermalState":ProcessInfo.processInfo.thermalState.rawValue,
                    "buildNumber":Bundle.main.object(forInfoDictionaryKey:"CFBundleVersion") as? String ?? "unknown",
                    "geometryBudgetExceeded":prepared.geometry.budgetExceeded,"sourceWidth":road.rawWidth,"sourceHeight":road.rawHeight,
                    "rotationDegrees":road.rotationDegrees,"visualCalibrationRevision":road.visualCalibration?.revision as Any? ?? NSNull(),
                    "motionProjectionEligible":prepared.diagnostics.motionProjectionEligible,
                    "motionHint":prepared.motionHint.diagnosticFields,"presentation":diagnosticPresentation.diagnosticFields,
                    "lanePreparationDiagnostics":prepared.diagnostics.diagnosticFields,
                    "paintedSegments":selected.map { boundary in
                        (boundary.observedSegments.isEmpty ? [boundary.points] : boundary.observedSegments).map { $0.map { [$0.x,$0.y] } }
                    },
                    "visibleIds":selected.isEmpty ? [] : prepared.presentation.visibleBoundaryIndices.map { index in
                        prepared.presentation.items.first { $0.boundaryIndex == index }?.trackId as Any? ?? NSNull()
                    },
                    "boundaryProvenance":selected.map { $0.provenance.rawValue },
                    "boundaryEvidenceAgeSeconds":selected.map { $0.evidenceAgeSeconds },
                    "boundaries":selected.map { $0.points.map { [$0.x,$0.y] } }]
                if let cadenceFields { fields["laneCadence"]=cadenceFields }
                if let data=try? JSONSerialization.data(withJSONObject:fields,options:[.sortedKeys]),let text=String(data:data,encoding:.utf8) {
                    Task { @MainActor [weak self] in self?.onPreviewDiagnostic?(text) }
                }
                continue
            }
            let estimate = tracker.update(detector.detect(grayscale: frame.buffer.bytes, width: frame.width, height: frame.height, timestampSeconds: frame.timestamp))
            let finished = Self.now()
            lock.lock()
            metrics.processedFrames += 1
            metrics.detectionMilliseconds = (finished - started) * 1_000
            metrics.captureToResultMilliseconds = (finished - frame.timestamp) * 1_000
            detectionTimes.append(metrics.detectionMilliseconds)
            captureToResultTimes.append(metrics.captureToResultMilliseconds)
            if accepting && generation == frame.generation && sessionID == frame.sessionID
                && LaneOverlayPolicy.opacity(capturedAt: frame.timestamp, now: finished) > 0 {
                cadence.record("published",now:finished)
                result = LaneOverlayFrame(estimate: estimate, sessionID: frame.sessionID, generation: frame.generation,
                    frameID: frame.id, rotation: frame.rotation, sourceWidth: frame.sourceWidth,
                    sourceHeight: frame.sourceHeight, cleanAperture: frame.cleanAperture)
            } else { metrics.rejectedResults += 1 }
            freeBuffers.append(frame.buffer)
            if metrics.processedFrames % 25 == 0 {
                metrics.preprocessing = preprocessingTimes.summary
                metrics.detection = detectionTimes.summary
                metrics.captureToResult = captureToResultTimes.summary
            }
            let report = metrics
            lock.unlock()
            if report.processedFrames % 25 == 0 {
                Self.logger.info("frames=\(report.processedFrames) replaced=\(report.replacedFrames) rejected=\(report.rejectedResults) cadence_skipped=\(report.cadenceSkippedFrames) timestamp_rejected=\(report.timestampRejectedFrames) preprocess_p50_ms=\(report.preprocessing.p50) preprocess_p95_ms=\(report.preprocessing.p95) preprocess_max_ms=\(report.preprocessing.maximum) detection_p50_ms=\(report.detection.p50) detection_p95_ms=\(report.detection.p95) detection_max_ms=\(report.detection.maximum) capture_to_result_p50_ms=\(report.captureToResult.p50) capture_to_result_p95_ms=\(report.captureToResult.p95) capture_to_result_max_ms=\(report.captureToResult.maximum) overlay_age_ms=\(report.overlayAgeMilliseconds)")
            }
        }
    }
}

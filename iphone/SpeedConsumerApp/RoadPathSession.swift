import Foundation
import AVFoundation
import ImageIO

struct RoadPathCameraFrame {
    let grayscale: [UInt8]
    let width: Int
    let height: Int
    let capturedAtSeconds: Double
    let geometryId: String
    let calibration: RoadPathCalibration?
    let clockKnown: Bool
    let preprocessingMs: Double
    let startedAt: Double
    var rawWidth: Int = 0
    var rawHeight: Int = 0
    var rotationDegrees: Int = 0
    var sourceTimestampSeconds: Double? = nil
    var visualCalibration: VisualRoadCalibration? = nil
    var orientationKey: String = ""
}
struct RoadPathLiveOverlay {
    let boundaries: [RoadBoundaryEvidence]
    let capturedAtSeconds: Double
    let rotationDegrees: Int
    var presentation: RoadBoundaryPresentationSnapshot? = nil
    var captureSessionID: String? = nil
    var rawWidth = 0
    var rawHeight = 0
    var orientationKey = ""
    var visualCalibrationRevision: String? = nil
}

/// One exposure's immutable geometry, prepared before sign inference and never redetected later.
fileprivate struct RoadPathLocationFix { let time, latitude, longitude, course, speed, accuracy, courseAccuracy: Double }
fileprivate struct RoadPathLocationSnapshot {
    let fixes: [RoadPathLocationFix]
    let origin: RoadPathLocationFix?
    let duplicateFixesDropped: UInt64
    let outOfOrderFixesDropped: UInt64
}
struct RoadPathPreparedFrame {
    let frameId: String
    let scope: TSRApplicabilityScope
    let frame: RoadPathCameraFrame
    let geometry: RoadBoundaryFrame
    let presentation: RoadBoundaryPresentationSnapshot
    let motionHint: RoadBoundaryMotionHint
    let filterMs: Double
    let geometryMs: Double
    let preparationMs: Double
    let readyUptime: Double
    /// Engineering target only; slow but current results remain valid.
    var performanceTargetExceeded: Bool { preparationMs > 50 }
    fileprivate let locationEpoch: UInt64
    fileprivate let overlayEpoch: UInt64
    fileprivate let locations: RoadPathLocationSnapshot
    let publicationDetails: [String:Any]
    let diagnostics: RoadPathPreparationDiagnostics
}

/// Owner-supplied bus mounting dimensions; experimental diagnostics, never speed authority.
struct RoadPathCameraCapture: Sendable {
    let capturedAtSeconds: Double
    let clockKnown: Bool
    let calibration: RoadPathCalibration?
    let geometryId: String
    let sourceTimestampSeconds: Double?

    static func capture(_ sample: CMSampleBuffer, orientation: CGImagePropertyOrientation, sourceClock: CMClock?) -> Self? {
        guard let pixel = CMSampleBufferGetImageBuffer(sample) else { return nil }
        let hostNow = CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock()))
        let sourceTimestamp = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample))
        let pts = sourceClock.map { CMTimeGetSeconds(CMSyncConvertTime(CMSampleBufferGetPresentationTimeStamp(sample), from: $0, to: CMClockGetHostTimeClock())) }
        let known = pts.map { $0.isFinite && $0 <= hostNow && hostNow - $0 < 1.5 } ?? false
        let timestamp = Date().timeIntervalSince1970 - (known ? hostNow - pts! : 0)
        let w = Double(CVPixelBufferGetWidth(pixel)), h = Double(CVPixelBufferGetHeight(pixel))
        var calibration: RoadPathCalibration?
        if let data = CMGetAttachment(sample, key: kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix, attachmentModeOut: nil) as? Data,
           data.count == MemoryLayout<simd_float3x3>.size {
            let matrix = data.withUnsafeBytes { $0.loadUnaligned(as: simd_float3x3.self) }
            let rawFX = Double(matrix.columns.0.x), rawFY = Double(matrix.columns.1.y)
            let rawCX = Double(matrix.columns.2.x), rawCY = Double(matrix.columns.2.y)
            let fx: Double, fy: Double, cx: Double, cy: Double
            switch orientation {
            case .up: fx = rawFX/w; fy = rawFY/h; cx = rawCX/w; cy = rawCY/h
            case .right: fx = rawFY/h; fy = rawFX/w; cx = (h-rawCY)/h; cy = rawCX/w
            case .down: fx = rawFX/w; fy = rawFY/h; cx = (w-rawCX)/w; cy = (h-rawCY)/h
            case .left: fx = rawFY/h; fy = rawFX/w; cx = rawCY/h; cy = (w-rawCX)/w
            default: return nil
            }
            if [fx,fy,cx,cy].allSatisfy(\.isFinite), fx > 0, fy > 0 {
                calibration = RoadPathCalibration(revision: "test-bus-2026-09-29:avfoundation:\(orientation.rawValue):\(w)x\(h)", verified: true,
                    fx: fx, fy: fy, cx: cx, cy: cy, yawDegrees: 0, pitchDegrees: 0, rollDegrees: 0,
                    heightMeters: 1.60, lateralOffsetMeters: -0.08)
            }
        }
        return Self(capturedAtSeconds: timestamp, clockKnown: known, calibration: calibration,
            geometryId: "\(orientation.rawValue):\(w)x\(h):\(CVImageBufferGetCleanRect(pixel))",
            sourceTimestampSeconds: sourceTimestamp.isFinite ? sourceTimestamp : nil)
    }

    func frame(pixel: CVPixelBuffer, orientation: CGImagePropertyOrientation, visualCalibration: VisualRoadCalibration? = nil) -> RoadPathCameraFrame? {
        let start = ProcessInfo.processInfo.systemUptime
        guard CVPixelBufferGetPlaneCount(pixel) > 0, CVPixelBufferLockBaseAddress(pixel, .readOnly) == kCVReturnSuccess else { return nil }
        defer { CVPixelBufferUnlockBaseAddress(pixel, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddressOfPlane(pixel, 0)?.assumingMemoryBound(to: UInt8.self) else { return nil }
        let rawW = CVPixelBufferGetWidthOfPlane(pixel, 0), rawH = CVPixelBufferGetHeightOfPlane(pixel, 0)
        let stride = CVPixelBufferGetBytesPerRowOfPlane(pixel, 0)
        let rotated = orientation == .right || orientation == .left
        let uprightW = rotated ? rawH : rawW, uprightH = rotated ? rawW : rawH
        let orientationKey = "rear:exif:\(orientation.rawValue)"
        let visual = visualCalibration.flatMap { $0.compatible(width:uprightW,height:uprightH,orientationKey:orientationKey) ? $0 : nil }
        let scale = min(384.0/Double(uprightW), 216.0/Double(uprightH), 1.0)
        let width = max(1, Int(Double(uprightW)*scale)), height = max(1, Int(Double(uprightH)*scale))
        let rotation: Int
        switch orientation {
        case .up: rotation = 0
        case .right: rotation = 90
        case .down: rotation = 180
        case .left: rotation = 270
        default: return nil
        }
        guard let bytes = RoadPathLumaSampler.shared.copy(base:base,rawWidth:rawW,rawHeight:rawH,
            rotation:rotation,rowStride:stride,width:width,height:height) else { return nil }
        return RoadPathCameraFrame(grayscale: bytes, width: width, height: height, capturedAtSeconds: capturedAtSeconds,
            geometryId: geometryId+":visual:\(visual?.revision ?? "none")", calibration: calibration, clockKnown: clockKnown,
            preprocessingMs: (ProcessInfo.processInfo.systemUptime-start)*1000, startedAt: start,
            rawWidth: rawW, rawHeight: rawH, rotationDegrees: orientation == .right ? 90 : orientation == .down ? 180 : orientation == .left ? 270 : 0,
            sourceTimestampSeconds: sourceTimestampSeconds,visualCalibration:visual,orientationKey:orientationKey)
    }
}

/// Cached separable source offsets. Pixel-center rounding matches the original camera sampler.
/// The plan never retains a pixel buffer, and stride/rotation/size changes invalidate it.
final class RoadPathLumaSampler: @unchecked Sendable {
    static let shared = RoadPathLumaSampler()
    private struct Key: Equatable {
        let rawWidth, rawHeight, rotation, rowStride, pixelStride, width, height: Int
    }
    private struct Plan { let key: Key; let columns, rows: [Int] }
    private let lock = NSLock()
    private var cached: Plan?

    func copy(base: UnsafePointer<UInt8>, rawWidth: Int, rawHeight: Int, rotation: Int,
              rowStride: Int, pixelStride: Int = 1, width: Int, height: Int,
              shouldContinue: () -> Bool = { true }) -> [UInt8]? {
        guard rawWidth > 0, rawHeight > 0, rowStride > 0, pixelStride > 0,
              (1...384).contains(width), (1...216).contains(height), [0,90,180,270].contains(rotation),
              shouldContinue() else { return nil }
        let key = Key(rawWidth:rawWidth,rawHeight:rawHeight,rotation:rotation,rowStride:rowStride,
            pixelStride:pixelStride,width:width,height:height)
        lock.lock()
        let existing = cached
        lock.unlock()
        let plan: Plan
        if let existing, existing.key == key { plan = existing }
        else {
            let columns = (0..<width).map { x -> Int in
                let u = (Double(x)+0.5)/Double(width)
                switch rotation {
                case 0: return min(rawWidth-1,Int(u*Double(rawWidth)))*pixelStride
                case 90: return min(rawHeight-1,Int((1-u)*Double(rawHeight)))*rowStride
                case 180: return min(rawWidth-1,Int((1-u)*Double(rawWidth)))*pixelStride
                default: return min(rawHeight-1,Int(u*Double(rawHeight)))*rowStride
                }
            }
            let rows = (0..<height).map { y -> Int in
                let v = (Double(y)+0.5)/Double(height)
                switch rotation {
                case 0: return min(rawHeight-1,Int(v*Double(rawHeight)))*rowStride
                case 90: return min(rawWidth-1,Int(v*Double(rawWidth)))*pixelStride
                case 180: return min(rawHeight-1,Int((1-v)*Double(rawHeight)))*rowStride
                default: return min(rawWidth-1,Int((1-v)*Double(rawWidth)))*pixelStride
                }
            }
            plan = Plan(key:key,columns:columns,rows:rows)
            lock.lock(); cached = plan; lock.unlock()
        }
        var bytes = [UInt8](repeating:0,count:width*height)
        for y in 0..<height {
            guard shouldContinue() else { return nil }
            let sourceRow = plan.rows[y], destinationRow = y*width
            for x in 0..<width { bytes[destinationRow+x] = base[sourceRow+plan.columns[x]] }
        }
        return shouldContinue() ? bytes : nil
    }
}

/// Preview identity tolerates subpixel intrinsics noise against a fixed anchor, not the
/// previous frame. Cumulative zoom/crop drift therefore still starts a new generation.
final class RoadPreviewCalibrationIdentity {
    private var anchor: RoadPathCalibration?
    private(set) var generation: UInt64 = 0
    func key(_ current: RoadPathCalibration?) -> String {
        let compatible: Bool
        if let a = anchor, let c = current {
            compatible = a.revision == c.revision && a.verified == c.verified &&
                a.yawDegrees == c.yawDegrees && a.pitchDegrees == c.pitchDegrees && a.rollDegrees == c.rollDegrees &&
                a.heightMeters == c.heightMeters && a.lateralOffsetMeters == c.lateralOffsetMeters &&
                [a.fx,a.fy,a.cx,a.cy,c.fx,c.fy,c.cx,c.cy].allSatisfy(\.isFinite) &&
                a.fx > 0 && a.fy > 0 && c.fx > 0 && c.fy > 0 &&
                abs(c.fx-a.fx) <= a.fx*0.005 && abs(c.fy-a.fy) <= a.fy*0.005 &&
                abs(c.cx-a.cx) <= 0.001 && abs(c.cy-a.cy) <= 0.001
        } else { compatible = anchor == nil && current == nil }
        if !compatible { anchor = current; generation &+= 1 }
        return "preview-calibration:\(generation)"
    }
}

/// Immutable per-exposure values; generations describe identity, intrinsics describe this exposure.
struct RoadPathPreparationDiagnostics {
    let calibrationGeneration: UInt64
    let calibration: RoadPathCalibration?
    let resetComponents: [String]
    let stageMs: [String:Double]
    let guideTrust: RoadVisualGuideTrustSnapshot
    let guidePriorUsed: String
    let detectorRejections: [String:Int]
    let detectionVariant: String
    let motionProjectionEligible: Bool
    let fragmentTrackingEnabled: Bool
    var tentativeIdentityEnabled: Bool = false
    var jointSelectionEnabled: Bool = false
    var diagnosticFields: [String:Any] {
        var value: [String:Any] = ["calibrationGeneration":calibrationGeneration,"resetComponents":resetComponents,
            "stageMs":stageMs,"guideTrust":guideTrust.diagnosticFields,"guidePriorUsed":guidePriorUsed,
            "detectorRejections":detectorRejections,"detectionVariant":detectionVariant,
            "motionProjectionEligible":motionProjectionEligible,"fragmentTrackingEnabled":fragmentTrackingEnabled,
            "tentativeIdentityEnabled":tentativeIdentityEnabled,"jointSelectionEnabled":jointSelectionEnabled,
            "roadContextStatus":"directional_lane_count_unavailable"]
        if let c=calibration {
            value["currentIntrinsics"]=["fx":c.fx,"fy":c.fy,"cx":c.cx,"cy":c.cy].filter {$0.value.isFinite}
            value["calibrationRevision"]=c.revision
        }
        return value
    }
}
/// Component comparisons explain a reset without relying on an opaque concatenated key.
final class RoadPathResetDiagnostics {
    private var previous: [String:String]?
    func changed(_ components: [String:String], advance: Bool) -> [String] {
        let changed=previous.map { old in components.keys.filter { old[$0] != components[$0] }.sorted() } ?? ["initial"]
        if advance { previous=components }
        return changed
    }
}

final class RoadPathSession: @unchecked Sendable {
    private typealias Fix = RoadPathLocationFix
    private let lock = NSLock()
    private let evaluationLock = NSLock()
    private var fixes: [Fix] = []
    private var origin: Fix?
    private var locationEpoch: UInt64 = 0
    private var duplicateFixesDropped: UInt64 = 0
    private var outOfOrderFixesDropped: UInt64 = 0
    private let nowUptime: () -> Double
    // Association history belongs only to the serial evaluator, never the GNSS callback.
    private var evaluatedLocationEpoch: UInt64?
    private var scope: String?
    private var lastCapture = -Double.infinity
    private var lastSourceTimestampSeconds: Double?
    private var histories: [String:[RoadPathObservation]] = [:]
    private var clock: CMClock?
    private let detector = RoadBoundaryDetector()
    private let temporal = RoadBoundaryTemporalTracker()
    private let presentationGate = RoadBoundaryPresentationGate()
    private let egoSelector = RoadBoundaryEgoSelector()
    private var liveOverlay: RoadPathLiveOverlay?
    private var overlayEpoch: UInt64 = 0
    private var publishedScope: String?
    private var publishedFrameId: String?
    private var publishedCaptureTime = -Double.infinity
    private var publishedSourceTimestamp: Double?
    private let previewCalibrationIdentity = RoadPreviewCalibrationIdentity()
    private let previewMode: Bool
    private let detectionOptions: RoadBoundaryDetectionOptions
    private let fragmentTracking: Bool
    private let retainTentativeIdentity: Bool
    private let jointSelection: Bool
    private let guideValidator = RoadVisualGuideValidator()
    private let resetDiagnostics = RoadPathResetDiagnostics()
    private let maximumGeometryOperations: Int
    init(previewMode: Bool = false, maximumGeometryOperations: Int = 250_000, detectionOptions: RoadBoundaryDetectionOptions = RoadBoundaryDetectionOptions(), fragmentTracking: Bool = false, retainTentativeIdentity: Bool = false, jointSelection: Bool = false, nowUptime: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.retainTentativeIdentity = previewMode && retainTentativeIdentity; self.jointSelection = previewMode && jointSelection
        self.detectionOptions = previewMode ? detectionOptions : RoadBoundaryDetectionOptions(); self.fragmentTracking = previewMode && fragmentTracking
        self.previewMode = previewMode; self.maximumGeometryOperations = max(0,min(250_000,maximumGeometryOperations)); self.nowUptime = nowUptime
    }
    func overlay() -> RoadPathLiveOverlay? { lock.lock(); defer { lock.unlock() }; return liveOverlay }
    func invalidateOverlay() { lock.lock(); liveOverlay = nil; overlayEpoch &+= 1; publishedScope = nil; publishedFrameId = nil; lock.unlock() }
    func invalidatePreparedOverlay(frameId: String) {
        lock.lock(); defer { lock.unlock() }
        if publishedFrameId == frameId { liveOverlay = nil }
    }
    /// Explicit drive/clock lifecycle boundary. Re-delivered GNSS fixes are not a reset signal.
    func resetTrajectory() {
        lock.lock(); defer { lock.unlock() }
        fixes.removeAll(); origin = nil; locationEpoch &+= 1; liveOverlay = nil; overlayEpoch &+= 1
        publishedScope = nil; publishedFrameId = nil
    }
    func configureCamera(clock: CMClock?) { lock.lock(); self.clock = clock; lock.unlock() }
    func sourceClock() -> CMClock? { lock.lock(); defer { lock.unlock() }; return clock }
    func recordLocation(time: Double, latitude: Double, longitude: Double, course: Double, speed: Double, accuracy: Double, courseAccuracy: Double) {
        lock.lock(); defer { lock.unlock() }
        guard [time,latitude,longitude,course,speed,accuracy,courseAccuracy].allSatisfy(\.isFinite),
              (-90...90).contains(latitude), (-180...180).contains(longitude), (0..<360).contains(course), speed >= 0, accuracy >= 0, courseAccuracy >= 0 else { return }
        if let last = fixes.last, time <= last.time {
            // Keep already accepted poses immutable across duplicate/out-of-order callbacks.
            if time == last.time { duplicateFixesDropped &+= 1 } else { outOfOrderFixesDropped &+= 1 }
            return
        }
        let fix = Fix(time: time, latitude: latitude, longitude: longitude, course: course, speed: speed, accuracy: accuracy, courseAccuracy: courseAccuracy)
        if origin == nil { origin = fix }
        fixes.append(fix)
        fixes = Array(fixes.filter { time-$0.time <= 8 }.suffix(32))
    }
    private func calibrationKey(_ frame: RoadPathCameraFrame) -> String {
        let stable = previewCalibrationIdentity.key(frame.calibration)
        return previewMode ? stable : String(describing: frame.calibration)
    }
    private func scopeKey(_ scope: TSRApplicabilityScope, _ frame: RoadPathCameraFrame) -> String {
        "\(scope.sessionId):\(scope.generation):\(scope.contextGeneration):\(scope.traversalEpoch):\(scope.bundleId):\(frame.geometryId):\(calibrationKey(frame))"
    }

    func prepare(frame: RoadPathCameraFrame, frameId: String, scope: TSRApplicabilityScope,
                 detectorTrace: RoadBoundaryTraceObserver? = nil,
                 semanticScoreAdjustments: [Double]? = nil,
                 shouldPublish: () -> Bool = { true }) -> RoadPathPreparedFrame {
        evaluationLock.lock(); defer { evaluationLock.unlock() }
        lock.lock()
        let capturedLocationEpoch = locationEpoch, capturedOverlayEpoch = overlayEpoch
        let previousPreparedScope=publishedScope, previousPreparedCapture=publishedCaptureTime, previousPreparedSource=publishedSourceTimestamp
        let locations = RoadPathLocationSnapshot(fixes: fixes, origin: origin,
            duplicateFixesDropped: duplicateFixesDropped, outOfOrderFixesDropped: outOfOrderFixesDropped)
        lock.unlock()
        let key=scopeKey(scope,frame)
        let rawSourceTimestamp=frame.sourceTimestampSeconds.flatMap { $0.isFinite ? $0 : nil }
        let compareRaw=rawSourceTimestamp != nil && previousPreparedSource != nil
        let duplicateOrOlder=previousPreparedScope==key &&
            (compareRaw ? rawSourceTimestamp!<=previousPreparedSource! : frame.capturedAtSeconds<=previousPreparedCapture)
        let uprightWidth = frame.rotationDegrees%180==0 ? frame.rawWidth : frame.rawHeight
        let uprightHeight = frame.rotationDegrees%180==0 ? frame.rawHeight : frame.rawWidth
        let visual = frame.visualCalibration.flatMap { $0.compatible(width:uprightWidth,height:uprightHeight,orientationKey:frame.orientationKey) ? $0 : nil }
        let calibrationIdentity = calibrationKey(frame)
        let temporalKey = "\(scope.sessionId):\(scope.generation):\(frame.geometryId):\(calibrationIdentity):\(capturedLocationEpoch):\(capturedOverlayEpoch):visual:\(visual?.revision ?? "none"):orientation:\(frame.orientationKey):rawClock:\(rawSourceTimestamp != nil):known:\(frame.clockKnown)" + (previewMode ? ":camera:\(scope.cameraGeometryId)" : "")
        let exposureTime = rawSourceTimestamp ?? frame.capturedAtSeconds
        let components = ["scope":"\(scope.sessionId):\(scope.generation)",
            "camera":"\(scope.cameraGeometryId):\(frame.orientationKey)",
            "geometry":"\(frame.geometryId.components(separatedBy:":visual:").first ?? frame.geometryId):\(frame.width)x\(frame.height):\(frame.rawWidth)x\(frame.rawHeight):\(frame.rotationDegrees)",
            "calibration":calibrationIdentity,"visual":visual?.revision ?? "none",
            "clock":"\(rawSourceTimestamp != nil):\(frame.clockKnown)","lifecycle":"\(capturedLocationEpoch):\(capturedOverlayEpoch)"]
        var resetComponents = resetDiagnostics.changed(components,advance:!duplicateOrOlder)
        if duplicateOrOlder { resetComponents.append("clock_order_rejected") }
        let guidePlan = previewMode ? guideValidator.begin(saved:frame.visualCalibration,compatible:visual,time:exposureTime,key:temporalKey) :
            RoadVisualGuidePlan(independentAudit:false,trusted:visual != nil,reason:"legacy_tsr_guides")
        let trustedVisual = (!previewMode || guidePlan.trusted) ? visual : nil
        let samplingVisual = guidePlan.independentAudit ? nil : trustedVisual
        let filterStart = nowUptime()
        let queueMs = max(0,(filterStart-frame.startedAt)*1000-frame.preprocessingMs)
        // Work stays bounded by dimensions and operation caps; 50 ms is telemetry, not cancellation.
        let enhanced = duplicateOrOlder ? nil : RoadBoundaryPreprocessor.topHat5ForDetector(grayscale: frame.grayscale, width: frame.width, height: frame.height, horizonY: samplingVisual?.horizonY)
        let filterMs = max(0,(nowUptime()-filterStart)*1000)
        let detectorStart = nowUptime()
        let motionHint = RoadBoundaryMotionHint.from(samples:locations.fixes.map { RoadBoundaryMotionSample(
            timeSeconds:$0.time,speedMetersPerSecond:$0.speed,courseDegrees:$0.course,horizontalAccuracyMeters:$0.accuracy,
            courseAccuracyDegrees:$0.courseAccuracy) },capturedAtSeconds:frame.capturedAtSeconds,clockKnown:frame.clockKnown)
        let motionProjection = previewMode ? RoadBoundaryMotionProjection.from(frame.calibration,visual:trustedVisual,hint:motionHint) : nil
        let geometry: RoadBoundaryFrame
        var predictionMs=0.0, detectionMs=0.0, fusionMs=0.0
        var freshRejections: [String:Int] = [:]
        var variant = "baseline"
        var freshBoundaries: [RoadBoundaryEvidence] = []
        if let enhanced {
            let prediction = temporal.predict(grayscale:frame.grayscale,width:frame.width,height:frame.height,
                timestampSeconds:exposureTime,key:temporalKey,capturedAtSeconds:frame.capturedAtSeconds,
                motionHint:motionHint,motionProjection:motionProjection,fragmentAware:fragmentTracking)
            let predictedAt=nowUptime(); predictionMs=max(0,(predictedAt-detectorStart)*1000)
            var guides = guidePlan.independentAudit ? [] : prediction.boundaries.map(\.points)
            if !guidePlan.independentAudit, let visual {
                // Saved guides are supplemental only while weak; no horizon/centre restriction.
                guides.append([LanePoint(x:visual.leftTopX,y:visual.horizonY),visual.leftBottom])
                guides.append([LanePoint(x:visual.rightTopX,y:visual.horizonY),visual.rightBottom])
            }
            let fresh = prediction.budgetExceeded ? RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:frame.capturedAtSeconds,budgetExceeded:true) :
                detector.detect(grayscale:enhanced,width:frame.width,height:frame.height,timestampSeconds:frame.capturedAtSeconds,
                    maximumOperations:maximumGeometryOperations,guidance:RoadBoundarySearchGuidance(horizonY:samplingVisual?.horizonY,polylines:guides),options:detectionOptions,trace:detectorTrace)
            let detectedAt=nowUptime(); detectionMs=max(0,(detectedAt-predictedAt)*1000)
            freshBoundaries=fresh.boundaries; freshRejections=fresh.rejectionCounts; variant=fresh.detectionVariant
            geometry = temporal.complete(prediction:prediction,fresh:fresh,grayscale:frame.grayscale)
            fusionMs=max(0,(nowUptime()-detectedAt)*1000)
        } else {
            if !duplicateOrOlder { temporal.reset() }
            geometry = RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:frame.capturedAtSeconds,budgetExceeded:!duplicateOrOlder)
        }
        let guideTrust = previewMode && !duplicateOrOlder ? guideValidator.observe(freshBoundaries,visual:visual,time:exposureTime,plan:guidePlan) :
            (previewMode ? guideValidator.snapshot : RoadVisualGuideTrustSnapshot(state:visual == nil ? "unavailable" : "legacy",
                reason:"legacy_tsr_guides",independentAudit:false,matchedSides:0,agreementCount:0,leftResidual:nil,rightResidual:nil))
        let presentationStart=nowUptime()
        var presentation: RoadBoundaryPresentationSnapshot
        if duplicateOrOlder { presentation = .rejected("duplicate_or_older_frame",rawCount:geometry.boundaries.count) }
        else if geometry.budgetExceeded || !frame.clockKnown {
            presentationGate.reset()
            presentation = .rejected(geometry.budgetExceeded ? "geometry_budget" : "capture_clock_unknown",rawCount:geometry.boundaries.count)
        } else {
            presentation = presentationGate.update(boundaries:geometry.boundaries,exposureSeconds:rawSourceTimestamp ?? frame.capturedAtSeconds,
                key:"\(temporalKey):\(frame.width)x\(frame.height)",retainMissingByTime:previewMode,fragmentAware:detectionOptions.groupFragments,retainTentativeIdentity:retainTentativeIdentity)
        }
        if previewMode && !duplicateOrOlder {
            presentation = egoSelector.select(presentation,boundaries:geometry.boundaries,visual:guideTrust.state == "trusted" ? visual : nil,
                time:rawSourceTimestamp ?? frame.capturedAtSeconds,key:temporalKey,fragmentAware:detectionOptions.groupFragments,
                jointSelection:jointSelection,egoContext:RoadBoundaryEgoContext(
                    calibration:motionProjection == nil ? nil : frame.calibration,
                    speedMetersPerSecond:motionProjection == nil ? nil : motionHint.speedMetersPerSecond,
                    headingRateDegreesPerSecond:motionProjection == nil ? nil : motionHint.headingRateDegreesPerSecond),
                semanticScoreAdjustments:semanticScoreAdjustments)
        }
        let ready = nowUptime(), geometryMs = max(0,(ready-detectorStart)*1000)
        let preparationMs = max(0,(ready-frame.startedAt)*1000)
        if let reset=geometry.temporalResetReason, !["initial","scope_or_geometry"].contains(reset) { resetComponents.append("temporal:"+reset) }
        let diagnostics=RoadPathPreparationDiagnostics(calibrationGeneration:previewCalibrationIdentity.generation,
            calibration:frame.calibration,resetComponents:resetComponents,
            stageMs:["luma":frame.preprocessingMs,"queueAndAdmission":queueMs,"filter":filterMs,
                "prediction":predictionMs,"detector":detectionMs,"fusion":fusionMs,
                "presentation":max(0,(ready-presentationStart)*1000),"total":preparationMs],guideTrust:guideTrust,
            guidePriorUsed:guidePlan.independentAudit ? "none_independent_audit" : trustedVisual != nil ? "trusted" : visual != nil ? "weak_polylines_only" : "none",
            detectorRejections:freshRejections,detectionVariant:variant,motionProjectionEligible:motionProjection != nil,fragmentTrackingEnabled:fragmentTracking,
            tentativeIdentityEnabled:retainTentativeIdentity,jointSelectionEnabled:jointSelection)
        let sourceTimestamp = frame.sourceTimestampSeconds.flatMap { $0.isFinite ? $0 : nil }
        let publicationTime = Date().timeIntervalSince1970
        let admissionCurrent = shouldPublish()
        lock.lock()
        let rawClockOrdering = sourceTimestamp != nil && publishedSourceTimestamp != nil
        let orderingTime = rawClockOrdering ? sourceTimestamp! : frame.capturedAtSeconds
        let previousOrderingTime = rawClockOrdering ? publishedSourceTimestamp! : publishedCaptureTime
        let previous = publishedScope == key && orderingTime <= previousOrderingTime
        let suppression: String? = !admissionCurrent ? "admission_changed" : locationEpoch != capturedLocationEpoch ? "trajectory_reset" :
            overlayEpoch != capturedOverlayEpoch ? "overlay_invalidated" : previous ? "duplicate_or_older_frame" :
            geometry.budgetExceeded ? "geometry_budget" : !presentation.accepted ? presentation.reason ?? "presentation_rejected" :
            !frame.clockKnown ? "capture_clock_unknown" : nil
        if admissionCurrent && locationEpoch == capturedLocationEpoch && overlayEpoch == capturedOverlayEpoch && !previous {
            publishedScope = key; publishedCaptureTime = frame.capturedAtSeconds
            publishedSourceTimestamp = sourceTimestamp; publishedFrameId = frameId
            liveOverlay = suppression == nil ? RoadPathLiveOverlay(boundaries: presentation.selectedBoundaries(from:geometry.boundaries),
                capturedAtSeconds: frame.capturedAtSeconds, rotationDegrees: frame.rotationDegrees,presentation:presentation,
                captureSessionID:scope.sessionId,rawWidth:frame.rawWidth,rawHeight:frame.rawHeight,orientationKey:frame.orientationKey,
                visualCalibrationRevision:visual?.revision) : nil
        }
        lock.unlock()
        if suppression != nil && !previous && !duplicateOrOlder { presentationGate.reset() }
        var publication: [String:Any] = ["overlayPublicationDecisionAtSeconds":publicationTime,
            "overlayPublished":suppression == nil,"overlayPublicationPhase":"before_tsr"]
        if let suppression { publication["overlayPublicationSuppressionReason"] = suppression }
        else { publication["overlayPublishedAtSeconds"] = publicationTime
            publication["captureToOverlayPublicationMs"] = (publicationTime-frame.capturedAtSeconds)*1000 }
        return RoadPathPreparedFrame(frameId: frameId, scope: scope, frame: frame, geometry: geometry,
            presentation:presentation,motionHint:motionHint,filterMs: filterMs, geometryMs: geometryMs, preparationMs: preparationMs, readyUptime: ready,
            locationEpoch: capturedLocationEpoch, overlayEpoch: capturedOverlayEpoch, locations: locations, publicationDetails: publication, diagnostics: diagnostics)
    }

    /// Compatibility entry point for diagnostics/replay; live inference calls prepare before TSR.
    func evaluate(frame: RoadPathCameraFrame, diagnostic: TSRApplicabilityDiagnostic) -> String? {
        evaluate(prepared: prepare(frame: frame, frameId: diagnostic.batch.frameId, scope: diagnostic.batch.scope), diagnostic: diagnostic)
    }

    func evaluate(prepared: RoadPathPreparedFrame, diagnostic: TSRApplicabilityDiagnostic, tsrStartedAtUptime: Double? = nil) -> String? {
        evaluationLock.lock(); defer { evaluationLock.unlock() }
        let frame = prepared.frame, associationStarted = nowUptime()
        guard prepared.frameId == diagnostic.batch.frameId, prepared.scope == diagnostic.batch.scope else {
            let rejected: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":diagnostic.batch.frameId,
                "reason":"prepared_frame_mismatch","associations":[],"boundaries":[]]
            return (try? JSONSerialization.data(withJSONObject: rejected)).flatMap { String(data:$0,encoding:.utf8) }
        }
        // Snapshot data briefly: frame analysis must not block main-thread overlay or GNSS work.
        lock.lock()
        let currentLocationEpoch = locationEpoch, currentOverlayEpoch = overlayEpoch
        let capturedFixes = prepared.locations.fixes, capturedOrigin = prepared.locations.origin, capturedLocationEpoch = prepared.locationEpoch
        let capturedOverlayEpoch = prepared.overlayEpoch
        let capturedDuplicateFixesDropped = prepared.locations.duplicateFixesDropped, capturedOutOfOrderFixesDropped = prepared.locations.outOfOrderFixesDropped
        lock.unlock()
        guard currentLocationEpoch == prepared.locationEpoch else {
            histories.removeAll()
            let rejected: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":diagnostic.batch.frameId,
                "reason":"trajectory_reset","associations":[],"boundaries":[]]
            return (try? JSONSerialization.data(withJSONObject: rejected)).flatMap { String(data:$0,encoding:.utf8) }
        }
        guard currentOverlayEpoch == prepared.overlayEpoch else {
            let rejected: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":diagnostic.batch.frameId,
                "reason":"overlay_invalidated","associations":[],"boundaries":[]]
            return (try? JSONSerialization.data(withJSONObject: rejected)).flatMap { String(data:$0,encoding:.utf8) }
        }
        if evaluatedLocationEpoch != capturedLocationEpoch {
            histories.removeAll(); evaluatedLocationEpoch = capturedLocationEpoch; lastCapture = -.infinity
            lastSourceTimestampSeconds = nil
        }
        let batch = diagnostic.batch, s = batch.scope
        let key = scopeKey(s,frame)
        let sourceTimestamp = frame.sourceTimestampSeconds.flatMap { $0.isFinite ? $0 : nil }
        let sourceOrdering = sourceTimestamp != nil && lastSourceTimestampSeconds != nil
        let orderingTime = sourceOrdering ? sourceTimestamp! : frame.capturedAtSeconds
        let previousOrderingTime = sourceOrdering ? lastSourceTimestampSeconds! : lastCapture
        if scope != key { histories.removeAll(); scope = key }
        else if orderingTime <= previousOrderingTime {
            // A repeated exposure neither reinforces evidence nor invalidates prior observations.
            var skipped: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":batch.frameId,
                "capturedAtSeconds":frame.capturedAtSeconds,"geometryId":frame.geometryId,"deadlineExceeded":false,
                "frameOrderingClock":sourceOrdering ? "source_exposure" : "capture_utc_fallback",
                "reason":orderingTime == previousOrderingTime ? "duplicate_frame" : "out_of_order_frame","associations":[]]
            if let sourceTimestamp { skipped["sourceTimestampSeconds"] = sourceTimestamp }
            return (try? JSONSerialization.data(withJSONObject: skipped)).flatMap { String(data:$0,encoding:.utf8) }
        }
        lastCapture = frame.capturedAtSeconds
        lastSourceTimestampSeconds = sourceTimestamp
        // The waiting/inference interval is excluded; all work in both added phases is charged.
        func elapsedMs() -> Double { prepared.preparationMs + max(0,(nowUptime()-associationStarted)*1000) }
        let geometry = prepared.geometry
        let geometryMs = prepared.geometryMs
        let poses: [RoadPathPose] = capturedOrigin.map { reference in capturedFixes.filter {
            $0.time <= frame.capturedAtSeconds && frame.capturedAtSeconds-$0.time <= 5
        }.map { fix in
            let deltaLongitude = (fix.longitude-reference.longitude+540).truncatingRemainder(dividingBy:360)-180
            return RoadPathPose(scope: key, timeSeconds: fix.time,
                eastMeters: deltaLongitude * .pi/180 * 6_371_000 * cos(reference.latitude * .pi/180),
                northMeters: (fix.latitude-reference.latitude) * .pi/180 * 6_371_000,
                courseDegrees: fix.course, speedMetersPerSecond: fix.speed,
                horizontalAccuracyMeters: fix.accuracy, courseAccuracyDegrees: fix.courseAccuracy)
        } } ?? []
        var projected: [RoadPathCorridor] = []
        if let calibration = frame.calibration, let pose = RoadPathEvidence.causalPoseAt(scope: key, timeSeconds: frame.capturedAtSeconds, poses: poses), frame.clockKnown, !geometry.budgetExceeded {
            func reduced(_ points: [LanePoint]) -> [LanePoint] {
                if points.count <= 16 { return points }
                return (0..<16).map { points[$0*(points.count-1)/15] }
            }
            for (index,corridor) in geometry.corridors.enumerated() {
                let left = reduced(geometry.boundaries[corridor.leftBoundaryIndex].points)
                let right = reduced(geometry.boundaries[corridor.rightBoundaryIndex].points)
                let pixels = left + right.reversed()
                let polygon = pixels.compactMap { RoadPathEvidence.projectGround(imageX: $0.x, imageY: $0.y, pose: pose, calibration: calibration) }
                if polygon.count == pixels.count {
                    projected.append(RoadPathCorridor(id: "visual-\(index)", role: "unknown", polygon: polygon,
                        confidence: corridor.confidence, independentlySupported: true, roadsideMarginMeters: 2.5))
                }
            }
        }
        let corridors = RoadPathEvidence.inferCorridorRoles(scope: key, nowSeconds: frame.capturedAtSeconds, poses: poses, corridors: projected)
        let currentTracks = diagnostic.tracks.filter { $0.visibility == "observed" && !$0.associationAmbiguous }.prefix(24)
        let ids = Set(diagnostic.tracks.map(\.trackId)); histories = histories.filter { ids.contains($0.key) }
        var associations: [[String:Any]] = []
        for track in currentTracks {
            if elapsedMs() >= 200 { break }
            guard let sample = track.samples.last, sample.frameId == batch.frameId else { continue }
            let box = sample.candidate.box
            let observation = RoadPathObservation(trackId: track.trackId, scope: key, calibrationRevision: frame.calibration?.revision ?? "unavailable",
                timeSeconds: frame.capturedAtSeconds, imageX: box.centerX, imageY: box.centerY)
            let history = Array(((histories[track.trackId] ?? []).filter { frame.capturedAtSeconds-$0.timeSeconds <= 2.5 } + [observation]).suffix(12))
            histories[track.trackId] = history
            let result = RoadPathEvidence.evaluate(scope: key, nowSeconds: frame.capturedAtSeconds, observations: history, poses: poses,
                calibration: frame.clockKnown && !geometry.budgetExceeded ? frame.calibration : nil, corridors: corridors)
            var row: [String:Any] = ["trackId":track.trackId,"classification":result.classification,"reason":result.reason,"supportingObservations":result.supportingObservations]
            row["shadowOnly"] = true
            row["observations"] = history.map { ["timeSeconds":$0.timeSeconds,"imageX":$0.imageX,"imageY":$0.imageY,"calibrationRevision":$0.calibrationRevision] as [String:Any] }
            if let value = result.eastMeters { row["eastMeters"] = value }
            if let value = result.northMeters { row["northMeters"] = value }
            if let value = result.heightMeters { row["heightMeters"] = value }
            if let value = result.baselineMeters { row["baselineMeters"] = value }
            if let value = result.parallaxDegrees { row["parallaxDegrees"] = value }
            if let value = result.uncertaintyEastMeters { row["uncertaintyEastMeters"] = value }
            if let value = result.uncertaintyNorthMeters { row["uncertaintyNorthMeters"] = value }
            if let value = result.oldestPoseTimeSeconds { row["oldestPoseTimeSeconds"] = value }
            if let value = result.newestPoseTimeSeconds { row["newestPoseTimeSeconds"] = value }
            if let value = result.maximumPoseAgeSeconds { row["maximumPoseAgeSeconds"] = value }
            if let value = result.rangeMeters { row["rangeMeters"] = value }
            if let value = result.residualMeters { row["residualMeters"] = value }
            associations.append(row)
        }
        let exceeded = elapsedMs() > 200
        if exceeded { for i in associations.indices { associations[i]["classification"]="unknown"; associations[i]["reason"]="added_processing_deadline" } }
        var json: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":batch.frameId,"capturedAtSeconds":frame.capturedAtSeconds,
            "geometryId":frame.geometryId,"captureClockKnown":frame.clockKnown,"mountProfile":"test-bus-2026-09-29",
            "cameraHeightMeters":1.60,"cameraLateralOffsetMeters": -0.08,"calibrationAvailable":frame.calibration != nil,
            "trajectorySamples":poses.count,"preprocessingMs":frame.preprocessingMs+prepared.filterMs,"geometryMs":geometryMs,
            "addedProcessingMs":elapsedMs(),"deadlineExceeded":exceeded,"geometryDeadlineExceeded":geometry.budgetExceeded,
            "boundaries":geometry.boundaries.map { ["confidence":$0.confidence,"cue":$0.cue.rawValue,"supportRows":$0.supportRows,
                "provenance":$0.provenance.rawValue,"lastFreshTimestampSeconds":$0.lastFreshTimestampSeconds.map { $0 as Any } ?? NSNull(),
                "evidenceAgeSeconds":$0.evidenceAgeSeconds,"trackedAnchorCount":$0.trackedAnchorCount,
                "observedSegments":$0.observedSegments.map { $0.map { [$0.x,$0.y] } },
                "geometryConfidence":$0.geometryConfidence.map { $0 as Any } ?? NSNull(),
                "paintOccupancy":$0.paintOccupancy.map { $0 as Any } ?? NSNull(),
                "points":$0.points.map { [$0.x,$0.y] }] as [String:Any] },
            "corridors":corridors.map { ["id":$0.id,"role":$0.role,"confidence":$0.confidence] as [String:Any] }, "associations":associations]
        json["lanePreprocessingId"] = RoadBoundaryPreprocessor.identifier
        json["lanePresentation"] = prepared.presentation.diagnosticFields
        json["laneMotionHint"] = prepared.motionHint.diagnosticFields
        json["lanePreparationDiagnostics"] = prepared.diagnostics.diagnosticFields
        json["lumaSamplingMs"] = frame.preprocessingMs; json["laneFilterMs"] = prepared.filterMs
        json["preparationAddedMs"] = prepared.preparationMs
        json["preparationPerformanceTargetExceeded"] = prepared.performanceTargetExceeded
        json["lanePreparationReadyUptimeSeconds"] = prepared.readyUptime
        if let tsrStartedAtUptime {
            json["tsrInferenceStartedUptimeSeconds"] = tsrStartedAtUptime
            json["lanePreparedBeforeTsr"] = prepared.readyUptime <= tsrStartedAtUptime
        }
        json["geometryReusedAfterTsr"] = true
        json["visualCalibrationRevision"] = frame.visualCalibration?.revision
        if let visual = frame.visualCalibration,
           let encoded = try? JSONEncoder().encode(visual),
           let object = try? JSONSerialization.jsonObject(with: encoded) {
            let width = frame.rotationDegrees % 180 == 0 ? frame.rawWidth : frame.rawHeight
            let height = frame.rotationDegrees % 180 == 0 ? frame.rawHeight : frame.rawWidth
            json["visualCalibration"] = object
            json["tsrInputRegion"] = ["leftPixels": visual.cropLeftPixels(width: width),
                "topPixels": 0, "rightPixels": width, "bottomPixels": height]
        }
        json["temporalOperationCount"] = geometry.temporalOperationCount
        json["temporalResetReason"] = geometry.temporalResetReason
        json["imageWidth"] = frame.rotationDegrees % 180 == 0 ? frame.rawWidth : frame.rawHeight
        json["imageHeight"] = frame.rotationDegrees % 180 == 0 ? frame.rawHeight : frame.rawWidth
        json["imageMapping"] = ["rawWidth":frame.rawWidth,"rawHeight":frame.rawHeight,"rotationDegrees":frame.rotationDegrees]
        json["analysisWidth"] = frame.width; json["analysisHeight"] = frame.height
        if let sourceTimestamp { json["sourceTimestampSeconds"] = sourceTimestamp }
        json["frameOrderingClock"] = sourceTimestamp != nil ? "source_exposure" : "capture_utc_fallback"
        json["locationIngestion"] = ["duplicateFixesDropped":capturedDuplicateFixesDropped,
            "outOfOrderFixesDropped":capturedOutOfOrderFixesDropped,"resetCount":capturedLocationEpoch]
        json["captureAgeAtEvaluationMs"] = (Date().timeIntervalSince1970-frame.capturedAtSeconds)*1000
        json["trajectoryReference"] = "local GNSS phone position used as approximate vehicle centre; mounting and road-plane uncertainty remain"
        json["associationTimeBasis"] = "exposure_relative_research_result"
        json["sourceCallbackAtSeconds"] = batch.capturedAtMs/1000
        json["scope"] = key; json["rawCandidateCount"] = batch.rawCandidateCount; json["candidatesTruncated"] = batch.truncated
        json["trajectory"] = poses.map { ["timeSeconds":$0.timeSeconds,"eastMeters":$0.eastMeters,"northMeters":$0.northMeters,
            "courseDegrees":$0.courseDegrees,"speedMetersPerSecond":$0.speedMetersPerSecond,
            "horizontalAccuracyMeters":$0.horizontalAccuracyMeters,"courseAccuracyDegrees":$0.courseAccuracyDegrees] }
        if let reference = capturedOrigin { json["localOrigin"] = ["latitude":reference.latitude,"longitude":reference.longitude] }
        if let c = frame.calibration {
            json["calibration"] = ["revision":c.revision,"verified":c.verified,"fx":c.fx,"fy":c.fy,"cx":c.cx,"cy":c.cy,
                "yawDegrees":c.yawDegrees,"pitchDegrees":c.pitchDegrees,"rollDegrees":c.rollDegrees,"heightMeters":c.heightMeters,
                "lateralOffsetMeters":c.lateralOffsetMeters.map { $0 as Any } ?? NSNull(),
                "provenance":"owner-supplied approximate bus mount; level camera assumption; camera metadata intrinsics"] as [String:Any]
        }
        json["signBoxes"] = currentTracks.compactMap { t -> [String:Any]? in
            guard let sample = t.samples.last else { return nil }; let b = sample.candidate.box
            return ["trackId":t.trackId,"candidateId":sample.candidate.candidateId,"semanticKey":sample.candidate.semanticKey,
                "x":b.x,"y":b.y,"width":b.width,"height":b.height]
        }
        json["corridors"] = corridors.map { c -> [String:Any] in
            var row: [String:Any] = ["id":c.id,"role":c.role,"confidence":c.confidence,"polygon":c.polygon.map { [$0.x,$0.y] }]
            if let index = Int(c.id.replacingOccurrences(of:"visual-",with:"")), index < geometry.corridors.count {
                let h = geometry.corridors[index]
                row["imagePolygon"] = (geometry.boundaries[h.leftBoundaryIndex].points + geometry.boundaries[h.rightBoundaryIndex].points.reversed()).map { [$0.x,$0.y] }
            }
            return row
        }
        guard let data = try? JSONSerialization.data(withJSONObject: json, options: [.sortedKeys]), let encoded = String(data:data,encoding:.utf8) else { return nil }
        let totalMs = elapsedMs()
        lock.lock()
        let locationCurrent = locationEpoch == capturedLocationEpoch
        let publicationSuppressionReason: String? = !locationCurrent ? "trajectory_reset" :
            overlayEpoch != capturedOverlayEpoch ? "overlay_invalidated" :
            totalMs >= 200 ? "added_processing_deadline" :
            geometry.budgetExceeded ? "geometry_budget" :
            !frame.clockKnown ? "capture_clock_unknown" : nil
        if publicationSuppressionReason != nil && publishedFrameId == prepared.frameId {
            liveOverlay = nil
        }
        lock.unlock()
        // Never refresh or republish pre-TSR geometry after inference; its exposure age is unchanged.
        var publicationDetails = prepared.publicationDetails
        if let publicationSuppressionReason {
            publicationDetails["overlayPublished"] = false
            publicationDetails["overlayPublicationSuppressionReason"] = publicationSuppressionReason
        }
        if totalMs >= 200 || !locationCurrent {
            histories.removeAll()
            temporal.reset(); presentationGate.reset(); egoSelector.reset()
            var rejected: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":batch.frameId,"capturedAtSeconds":frame.capturedAtSeconds,
                "geometryId":frame.geometryId,"deadlineExceeded":totalMs >= 200,"totalAddedProcessingMs":totalMs,
                "reason":locationCurrent ? "added_processing_deadline" : "trajectory_reset","associations":[]]
            rejected.merge(publicationDetails) { _, new in new }
            return (try? JSONSerialization.data(withJSONObject:rejected)).flatMap { String(data:$0,encoding:.utf8) }
        }
        guard let publicationData = try? JSONSerialization.data(withJSONObject: publicationDetails, options: [.sortedKeys]),
              let publicationJSON = String(data: publicationData, encoding: .utf8) else { return nil }
        return String(encoded.dropLast()) + ",\"totalAddedProcessingMs\":\(totalMs)," + String(publicationJSON.dropFirst())
    }
}

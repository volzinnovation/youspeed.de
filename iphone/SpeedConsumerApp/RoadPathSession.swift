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
}
struct RoadPathLiveOverlay {
    let boundaries: [RoadBoundaryEvidence]
    let capturedAtSeconds: Double
    let rotationDegrees: Int
}

/// Owner-supplied bus mounting dimensions; experimental diagnostics, never speed authority.
struct RoadPathCameraCapture: Sendable {
    let capturedAtSeconds: Double
    let clockKnown: Bool
    let calibration: RoadPathCalibration?
    let geometryId: String

    static func capture(_ sample: CMSampleBuffer, orientation: CGImagePropertyOrientation, sourceClock: CMClock?) -> Self? {
        guard let pixel = CMSampleBufferGetImageBuffer(sample) else { return nil }
        let hostNow = CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock()))
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
            geometryId: "\(orientation.rawValue):\(w)x\(h):\(CVImageBufferGetCleanRect(pixel))")
    }

    func frame(pixel: CVPixelBuffer, orientation: CGImagePropertyOrientation) -> RoadPathCameraFrame? {
        let start = ProcessInfo.processInfo.systemUptime
        guard CVPixelBufferGetPlaneCount(pixel) > 0, CVPixelBufferLockBaseAddress(pixel, .readOnly) == kCVReturnSuccess else { return nil }
        defer { CVPixelBufferUnlockBaseAddress(pixel, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddressOfPlane(pixel, 0)?.assumingMemoryBound(to: UInt8.self) else { return nil }
        let rawW = CVPixelBufferGetWidthOfPlane(pixel, 0), rawH = CVPixelBufferGetHeightOfPlane(pixel, 0)
        let stride = CVPixelBufferGetBytesPerRowOfPlane(pixel, 0)
        let rotated = orientation == .right || orientation == .left
        let uprightW = rotated ? rawH : rawW, uprightH = rotated ? rawW : rawH
        let scale = min(384.0/Double(uprightW), 216.0/Double(uprightH), 1.0)
        let width = max(1, Int(Double(uprightW)*scale)), height = max(1, Int(Double(uprightH)*scale))
        var bytes = [UInt8](repeating: 0, count: width*height)
        for y in 0..<height { for x in 0..<width {
            let u = (Double(x)+0.5)/Double(width), v = (Double(y)+0.5)/Double(height)
            let rx: Double, ry: Double
            switch orientation {
            case .up: rx=u; ry=v
            case .right: rx=v; ry=1-u
            case .down: rx=1-u; ry=1-v
            case .left: rx=1-v; ry=u
            default: return nil
            }
            bytes[y*width+x] = base[min(rawH-1,Int(ry*Double(rawH)))*stride+min(rawW-1,Int(rx*Double(rawW)))]
        } }
        return RoadPathCameraFrame(grayscale: bytes, width: width, height: height, capturedAtSeconds: capturedAtSeconds,
            geometryId: geometryId, calibration: calibration, clockKnown: clockKnown,
            preprocessingMs: (ProcessInfo.processInfo.systemUptime-start)*1000, startedAt: start,
            rawWidth: rawW, rawHeight: rawH, rotationDegrees: orientation == .right ? 90 : orientation == .down ? 180 : orientation == .left ? 270 : 0)
    }
}

final class RoadPathSession: @unchecked Sendable {
    private struct Fix { let time, latitude, longitude, course, speed, accuracy, courseAccuracy: Double }
    private let lock = NSLock()
    private let evaluationLock = NSLock()
    private var fixes: [Fix] = []
    private var origin: Fix?
    private var locationEpoch: UInt64 = 0
    // Association history belongs only to the serial evaluator, never the GNSS callback.
    private var evaluatedLocationEpoch: UInt64?
    private var scope: String?
    private var lastCapture = -Double.infinity
    private var histories: [String:[RoadPathObservation]] = [:]
    private var clock: CMClock?
    private let detector = RoadBoundaryDetector()
    private var liveOverlay: RoadPathLiveOverlay?
    private var overlayEpoch: UInt64 = 0
    func overlay() -> RoadPathLiveOverlay? { lock.lock(); defer { lock.unlock() }; return liveOverlay }
    func invalidateOverlay() { lock.lock(); liveOverlay = nil; overlayEpoch &+= 1; lock.unlock() }
    func configureCamera(clock: CMClock?) { lock.lock(); self.clock = clock; lock.unlock() }
    func sourceClock() -> CMClock? { lock.lock(); defer { lock.unlock() }; return clock }
    func recordLocation(time: Double, latitude: Double, longitude: Double, course: Double, speed: Double, accuracy: Double, courseAccuracy: Double) {
        lock.lock(); defer { lock.unlock() }
        guard [time,latitude,longitude,course,speed,accuracy,courseAccuracy].allSatisfy(\.isFinite),
              (-90...90).contains(latitude), (-180...180).contains(longitude), (0..<360).contains(course), speed >= 0, accuracy >= 0, courseAccuracy >= 0 else { return }
        if let last = fixes.last, time <= last.time {
            fixes.removeAll(); origin = nil; locationEpoch &+= 1; liveOverlay = nil
        }
        let fix = Fix(time: time, latitude: latitude, longitude: longitude, course: course, speed: speed, accuracy: accuracy, courseAccuracy: courseAccuracy)
        if origin == nil { origin = fix }
        fixes.append(fix)
        fixes = Array(fixes.filter { time-$0.time <= 8 }.suffix(32))
    }
    func evaluate(frame: RoadPathCameraFrame, diagnostic: TSRApplicabilityDiagnostic) -> String? {
        evaluationLock.lock(); defer { evaluationLock.unlock() }
        // Snapshot data briefly: frame analysis must not block main-thread overlay or GNSS work.
        lock.lock()
        let capturedFixes = fixes, capturedOrigin = origin, capturedLocationEpoch = locationEpoch
        let capturedOverlayEpoch = overlayEpoch
        lock.unlock()
        if evaluatedLocationEpoch != capturedLocationEpoch { histories.removeAll(); evaluatedLocationEpoch = capturedLocationEpoch }
        let batch = diagnostic.batch, s = batch.scope
        let key = "\(s.sessionId):\(s.generation):\(s.contextGeneration):\(s.traversalEpoch):\(s.bundleId):\(frame.geometryId):\(String(describing: frame.calibration))"
        if scope != key || frame.capturedAtSeconds <= lastCapture { histories.removeAll(); scope = key }
        lastCapture = frame.capturedAtSeconds
        func elapsedMs() -> Double { (ProcessInfo.processInfo.systemUptime-frame.startedAt)*1000 }
        let geometry = detector.detect(grayscale: frame.grayscale, width: frame.width, height: frame.height,
            timestampSeconds: frame.capturedAtSeconds, shouldContinue: { elapsedMs() < 50 })
        let geometryMs = elapsedMs()-frame.preprocessingMs
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
            "trajectorySamples":poses.count,"preprocessingMs":frame.preprocessingMs,"geometryMs":geometryMs,
            "addedProcessingMs":elapsedMs(),"deadlineExceeded":exceeded,"geometryDeadlineExceeded":geometry.budgetExceeded,
            "boundaries":geometry.boundaries.map { ["confidence":$0.confidence,"cue":$0.cue.rawValue,"supportRows":$0.supportRows,"points":$0.points.map { [$0.x,$0.y] }] as [String:Any] },
            "corridors":corridors.map { ["id":$0.id,"role":$0.role,"confidence":$0.confidence] as [String:Any] }, "associations":associations]
        json["imageWidth"] = frame.rotationDegrees % 180 == 0 ? frame.rawWidth : frame.rawHeight
        json["imageHeight"] = frame.rotationDegrees % 180 == 0 ? frame.rawHeight : frame.rawWidth
        json["imageMapping"] = ["rawWidth":frame.rawWidth,"rawHeight":frame.rawHeight,"rotationDegrees":frame.rotationDegrees]
        json["analysisWidth"] = frame.width; json["analysisHeight"] = frame.height
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
        if locationCurrent && overlayEpoch == capturedOverlayEpoch {
            liveOverlay = totalMs < 200 && !geometry.budgetExceeded && frame.clockKnown ?
                RoadPathLiveOverlay(boundaries:geometry.boundaries,capturedAtSeconds:frame.capturedAtSeconds,rotationDegrees:frame.rotationDegrees) : nil
        }
        lock.unlock()
        if totalMs >= 200 || !locationCurrent {
            histories.removeAll()
            let rejected: [String:Any] = ["schemaVersion":1,"mode":"shadow","frameId":batch.frameId,"capturedAtSeconds":frame.capturedAtSeconds,
                "geometryId":frame.geometryId,"deadlineExceeded":totalMs >= 200,"totalAddedProcessingMs":totalMs,
                "reason":locationCurrent ? "added_processing_deadline" : "trajectory_clock_discontinuity","associations":[]]
            return (try? JSONSerialization.data(withJSONObject:rejected)).flatMap { String(data:$0,encoding:.utf8) }
        }
        return String(encoded.dropLast()) + ",\"totalAddedProcessingMs\":\(totalMs)}"
    }
}

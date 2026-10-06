import Foundation

/// Collection identity is independent of speed-limit applicability and its tracks.
/// Two distinct frames spanning 100 ms qualify a sighting, which is committed
/// immediately. Continuing frames share that sighting's identity but can supply
/// a bounded crop sequence until 2 s without support.
final class SignCollectionObserver {
    struct Detection {
        let key: String
        let box: [Double]
        let payload: [String: Any]
        let presentationTrack: String?
    }
    struct CropCandidate {
        let observationID: String
        let frameAt: Date
        let box: [Double]
    }
    enum CropCaptureResult { case stored, failed, skipped }
    // Six regular samples plus two reserved for a substantially larger view.
    // No image buffers are retained here; selection uses existing box geometry.
    private static let regularCropLimit = 6
    private static let maximumCropLimit = 8
    private static let minimumCropIntervalMilliseconds = 500.0
    private static let improvementAreaRatio = 1.5
    private struct Track {
        let id: String
        let key: String
        let first: Date
        var last: Date
        var box: [Double]
        var frames: Int
        var committed: Bool
        var cropCount = 0
        var lastCropAttempt: Date?
        var largestCropArea = 0.0
    }
    private var tracks: [Track] = []
    private var presentations: [String: String] = [:]
    private var attempts: [String: String] = [:]
    private var frameTime: Date?
    func reset() { tracks.removeAll(); presentations.removeAll(); attempts.removeAll(); frameTime = nil }
    func observe(at: Date, detections: [Detection],
                 captureCrop: ((CropCandidate) -> CropCaptureResult)? = nil,
                 commit: ([String: Any]) throws -> Void) throws {
        if let previous = frameTime, at <= previous { return }
        frameTime = at
        tracks.removeAll { at.timeIntervalSince($0.last) > 2 }
        var used = Set<String>()
        for detection in detections.prefix(64) {
            guard detection.box.count == 4, detection.box.allSatisfy({ $0.isFinite }), detection.box[2] > 0, detection.box[3] > 0 else { continue }
            let index = tracks.indices.filter { tracks[$0].key == detection.key && !used.contains(tracks[$0].id) }
                .max { Self.iou(tracks[$0].box, detection.box) < Self.iou(tracks[$1].box, detection.box) }
                .flatMap { Self.iou(tracks[$0].box, detection.box) >= 0.2 ? $0 : nil }
            let selected: Int
            if let index { selected = index }
            else {
                if tracks.count >= 64 { continue }
                tracks.append(Track(id: SignCollectionJSON.uuid(), key: detection.key, first: at, last: at, box: detection.box, frames: 0, committed: false))
                selected = tracks.count - 1
            }
            tracks[selected].last = at; tracks[selected].box = detection.box; tracks[selected].frames += 1
            let track = tracks[selected]; used.insert(track.id)
            if !track.committed, track.frames >= 2, (at.timeIntervalSince(track.first) * 1000).rounded() >= 100 {
                var event = detection.payload
                event["event_id"] = track.id; event["first_seen_at"] = SignCollectionJSON.utc(track.first)
                event["last_seen_at"] = SignCollectionJSON.utc(at); event["representative_frame_at"] = SignCollectionJSON.utc(at)
                event["duration_ms"] = Int((at.timeIntervalSince(track.first) * 1000).rounded())
                var scores = event["scores"] as! [String: Any]; scores["track_support"] = track.frames; event["scores"] = scores
                var evidence = event["evidence"] as! [String: Any]
                evidence["track_id"] = track.id; evidence["analyzed_frames"] = track.frames
                evidence["finalization_reason"] = "qualified_track"; event["evidence"] = evidence
                try commit(event) // Mark only after the durable transaction succeeds.
                tracks[selected].committed = true
            }
            if tracks[selected].committed, let captureCrop {
                let saved = tracks[selected]
                let area = detection.box[2] * detection.box[3]
                let intervalReady = saved.lastCropAttempt.map {
                    (at.timeIntervalSince($0) * 1000).rounded() >= Self.minimumCropIntervalMilliseconds
                } ?? true
                if intervalReady, saved.cropCount < Self.maximumCropLimit,
                   saved.cropCount < Self.regularCropLimit || area >= saved.largestCropArea * Self.improvementAreaRatio {
                    let result = captureCrop(CropCandidate(observationID: saved.id, frameAt: at, box: detection.box))
                    // Missing frames/per-frame capacity consume neither a slot nor
                    // the interval. Actual failures retry at the bounded cadence.
                    if result != .skipped { tracks[selected].lastCropAttempt = at }
                    if result == .stored {
                        tracks[selected].cropCount += 1
                        tracks[selected].largestCropArea = max(saved.largestCropArea, area)
                    }
                }
            }
            if tracks[selected].committed, let presentation = detection.presentationTrack {
                if presentations.count >= 512, presentations[presentation] == nil { presentations.removeAll() }
                presentations[presentation] = track.id
            }
        }
        // A sign may leave the frame before its feedback finishes. Retain the
        // bounded association for the displayed sign until session/privacy reset.
    }
    func freeze(attempt: String, presentation: String?) {
        if attempts.count >= 32 { attempts.removeAll() }
        if let presentation, let target = presentations[presentation] { attempts[attempt] = target }
    }
    func correction(attempt: String, modality: String, at: Date) -> [String: Any]? {
        guard let target = attempts.removeValue(forKey: attempt) else { return nil }
        return ["schema_version": 1, "event_id": SignCollectionJSON.uuid(), "created_at": SignCollectionJSON.utc(at),
                "intent": "unspecified_wrong", "input_modality": modality, "target_kind": "observation", "target_id": target,
                "target_version": NSNull(), "association_status": "exact", "presentation_id": NSNull(),
                "speech_attempt_id": modality == "voice" ? attempt as Any : NSNull(), "media_refs": []]
    }
    private static func iou(_ a: [Double], _ b: [Double]) -> Double {
        let intersection = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0],b[0])) * max(0, min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
        return intersection / max(1e-12, a[2]*a[3]+b[2]*b[3]-intersection)
    }
}

/// Independent capture eligibility: all admitted classes, no speed override dependency.
final class SignCaptureFilter {
    struct Evidence: Codable, Equatable, Sendable {
        let trackID: String
        let modelLabel: String
        let frameAt: Date
        let normalizedBox: [Double]
        let rawScore: Double
        var sourceFrameID: String? = nil
    }
    struct Detection { let key: String; let label: String; let box: [Double]; let score: Double; var frameID: String? = nil }
    private struct Track { let id: String; let key: String; let first: Date; var last: Date; var box: [Double]; var frames: Int; var captured: Bool }
    private var tracks: [Track] = []
    private var frameAt: Date?
    private var captureAt: Date?
    func reset() { tracks = []; frameAt = nil; captureAt = nil }
    func observe(at: Date, detections: [Detection]) -> [Evidence] {
        if let previous = frameAt, at <= previous { return [] }; frameAt = at
        tracks.removeAll { at.timeIntervalSince($0.last) > 2 }
        var used = Set<String>(), result: [Evidence] = []
        for d in detections.prefix(64) {
            guard d.box.count == 4, d.box.allSatisfy({ $0.isFinite }), d.box[2] > 0, d.box[3] > 0 else { continue }
            let match = tracks.indices.filter { tracks[$0].key == d.key && !used.contains(tracks[$0].id) }
                .max { Self.iou(tracks[$0].box,d.box) < Self.iou(tracks[$1].box,d.box) }
                .flatMap { Self.iou(tracks[$0].box,d.box) >= 0.2 ? $0 : nil }
            let index: Int
            if let match { index = match } else {
                guard tracks.count < 64 else { continue }
                tracks.append(Track(id: SignCollectionJSON.uuid(), key: d.key, first: at, last: at, box: d.box, frames: 0, captured: false)); index = tracks.count - 1
            }
            tracks[index].last = at; tracks[index].box = d.box; tracks[index].frames += 1
            let track = tracks[index]; used.insert(track.id)
            if !track.captured, track.frames >= 2, (at.timeIntervalSince(track.first)*1000).rounded() >= 100 {
                result.append(Evidence(trackID: track.id, modelLabel: d.label, frameAt: at, normalizedBox: d.box, rawScore: d.score, sourceFrameID: d.frameID))
            }
        }
        if let captureAt, at.timeIntervalSince(captureAt) < 2 { return [] }
        return result.sorted { $0.rawScore > $1.rawScore }
    }
    func captured(_ evidence: [Evidence], at: Date) {
        let ids = Set(evidence.map(\.trackID)); for i in tracks.indices where ids.contains(tracks[i].id) { tracks[i].captured = true }; captureAt = at
    }
    private static func iou(_ a: [Double], _ b: [Double]) -> Double {
        let intersection = max(0,min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])) * max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
        return intersection / max(1e-12,a[2]*a[3]+b[2]*b[3]-intersection)
    }
}

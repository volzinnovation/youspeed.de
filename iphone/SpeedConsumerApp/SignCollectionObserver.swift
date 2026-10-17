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
        var supplementaryOCR: SupplementaryOCRAnnotation? = nil
        var commitReady = true
    }
    struct CropCandidate {
        let observationID: String
        let frameAt: Date
        let box: [Double]
        var selection: SignCollectionInterestSelection? = nil
        var supplementaryOCR: SupplementaryOCRAnnotation? = nil
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
        var selection: SignCollectionInterestSelection? = nil
        var supplementaryOCR: SupplementaryOCRAnnotation? = nil
    }
    private var tracks: [Track] = []
    private var presentations: [String: String] = [:]
    private var attempts: [String: String] = [:]
    private struct SourceAssociation {
        let trackID: String
        let modelLabel: String
        let frameAt: Date
        let speedKmh: Int?
        let box: [Double]
    }
    // Geometry/provenance only. Never retain camera buffers for late OCR.
    private var sourceFrames: [String: [SourceAssociation]] = [:]
    private var sourceOrder: [String] = []
    private var committedIDs = Set<String>()
    private var recordedOCR = Set<String>()
    private var recordedOrder: [String] = []
    private var frameTime: Date?
    func reset() {
        tracks.removeAll(); presentations.removeAll(); attempts.removeAll(); frameTime = nil
        sourceFrames.removeAll(); sourceOrder.removeAll(); committedIDs.removeAll()
        recordedOCR.removeAll(); recordedOrder.removeAll()
    }
    func observe(at: Date, detections: [Detection], frameID: String? = nil,
                 captureCrop: ((CropCandidate) -> CropCaptureResult)? = nil,
                 selectCrop: (([String: Any], String) -> SignCollectionInterestSelection)? = nil,
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
            if let annotation = detection.supplementaryOCR { tracks[selected].supplementaryOCR = annotation }
            let track = tracks[selected]; used.insert(track.id)
            if detection.commitReady, !track.committed, track.frames >= 2, (at.timeIntervalSince(track.first) * 1000).rounded() >= 100 {
                var event = detection.payload
                if let annotation = track.supplementaryOCR { event["supplementary_ocr"] = annotation.wire }
                event["event_id"] = track.id; event["first_seen_at"] = SignCollectionJSON.utc(track.first)
                event["last_seen_at"] = SignCollectionJSON.utc(at); event["representative_frame_at"] = SignCollectionJSON.utc(at)
                event["duration_ms"] = Int((at.timeIntervalSince(track.first) * 1000).rounded())
                var scores = event["scores"] as! [String: Any]; scores["track_support"] = track.frames; event["scores"] = scores
                var evidence = event["evidence"] as! [String: Any]
                evidence["track_id"] = track.id; evidence["analyzed_frames"] = track.frames
                evidence["finalization_reason"] = "qualified_track"; event["evidence"] = evidence
                if let selectCrop {
                    if tracks[selected].selection == nil { tracks[selected].selection = selectCrop(detection.payload, track.id) }
                    event["collection_selection"] = tracks[selected].selection!.wire
                }
                try commit(event) // Mark only after the durable transaction succeeds.
                tracks[selected].committed = true
                committedIDs.insert(track.id)
            }
            if tracks[selected].committed, let captureCrop, tracks[selected].selection?.permits(at: at) != false {
                let saved = tracks[selected]
                let area = detection.box[2] * detection.box[3]
                let intervalReady = saved.lastCropAttempt.map {
                    (at.timeIntervalSince($0) * 1000).rounded() >= Self.minimumCropIntervalMilliseconds
                } ?? true
                if intervalReady, saved.cropCount < Self.maximumCropLimit,
                   saved.cropCount < Self.regularCropLimit || area >= saved.largestCropArea * Self.improvementAreaRatio {
                    let result = captureCrop(CropCandidate(observationID: saved.id, frameAt: at, box: detection.box,
                        selection: saved.selection, supplementaryOCR: saved.supplementaryOCR))
                    // Missing frames/per-frame capacity consume neither a slot nor
                    // the interval. Actual failures retry at the bounded cadence.
                    if result != .skipped { tracks[selected].lastCropAttempt = at }
                    if result == .stored {
                        tracks[selected].cropCount += 1
                        tracks[selected].largestCropArea = max(saved.largestCropArea, area)
                    }
                }
            }
            if let frameID, let classification = detection.payload["classification"] as? [String: Any],
               let label = classification["model_label"] as? String {
                if sourceFrames[frameID] == nil {
                    if sourceOrder.count >= 64 {
                        sourceFrames.removeValue(forKey: sourceOrder.removeFirst())
                    }
                    sourceOrder.append(frameID); sourceFrames[frameID] = []
                }
                sourceFrames[frameID, default: []].append(.init(trackID: track.id, modelLabel: label, frameAt: at,
                    speedKmh: classification["value"] as? Int, box: detection.box))
            }
            if tracks[selected].committed, let presentation = detection.presentationTrack {
                if presentations.count >= 512, presentations[presentation] == nil { presentations.removeAll() }
                presentations[presentation] = track.id
            }
        }
        committedIDs.formIntersection(Set(sourceFrames.values.flatMap { $0.map(\.trackID) } + tracks.map(\.id)))
        // A sign may leave the frame before its feedback finishes. Retain the
        // bounded association for the displayed sign until session/privacy reset.
    }
    /// A late completion must not count as another detection or rewrite an
    /// immutable sighting. Keep every actual source-frame attempt separately.
    func recordSupplementaryOCR(_ annotation: SupplementaryOCRAnnotation, at: Date,
                                commit: ([String: Any]) throws -> Void) throws {
        let identity = try SignCollectionJSON.canonical([annotation.physicalSignID, annotation.frameID,
                                                        annotation.engine, annotation.modelVersion])
        let attemptID = SignCollectionJSON.sha256(Data(identity.utf8))
        guard !recordedOCR.contains(attemptID) else { return }
        let matches = (sourceFrames[annotation.frameID] ?? []).filter {
            annotation.observedAt == $0.frameAt && annotation.matches(modelLabel: $0.modelLabel, speedKmh: $0.speedKmh, box: $0.box)
        }
        let association = matches.count == 1 ? matches.first : nil
        if let association, let index = tracks.firstIndex(where: { $0.id == association.trackID }) {
            tracks[index].supplementaryOCR = annotation
        }
        let target = association.flatMap { committedIDs.contains($0.trackID) ? $0.trackID : nil }
        let event: [String: Any] = ["schema_version": 1, "event_id": SignCollectionJSON.uuid(),
            "created_at": SignCollectionJSON.utc(max(at, annotation.observedAt)), "crop_id": NSNull(),
            "status": "supplementary_ocr_observed", "observation_id": target as Any? ?? NSNull(),
            "association_status": target == nil ? "unresolved" : "exact", "ocr_attempt_id": attemptID,
            "supplementary_ocr": annotation.wire]
        try commit(event)
        if recordedOrder.count >= 1024 { recordedOCR.remove(recordedOrder.removeFirst()) }
        recordedOrder.append(attemptID); recordedOCR.insert(attemptID)
        // Bound IDs together with retained source frames and active tracks.
        committedIDs.formIntersection(Set(sourceFrames.values.flatMap { $0.map(\.trackID) } + tracks.map(\.id)))
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

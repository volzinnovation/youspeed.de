import Foundation
import CoreGraphics

/// Shared sequence vectors are also exercised by Android's desktop tests.
func runCollectionRepeatCropChecks(gate: SignCollectionContractGate, root: URL, fixture: [String: Any], vectors: URL) throws {
    let input = try JSONSerialization.jsonObject(with: Data(contentsOf: vectors)) as! [String: Any]
    let start = Date(timeIntervalSince1970: 1_770_000_000)
    for scenario in input["scenarios"] as! [[String: Any]] {
        let name = scenario["name"] as! String
        let observer = SignCollectionObserver()
        var sightings = [[String: Any]](), attempts = [SignCollectionObserver.CropCandidate](), stored = 0
        for step in scenario["frames"] as! [[String: Any]] {
            let ms = step["milliseconds"] as! Int, size = step["size"] as! Double
            let at = start.addingTimeInterval(Double(ms) / 1000)
            let detection = SignCollectionObserver.Detection(key: "sign", box: [0.1, 0.1, size, size], payload: fixture, presentationTrack: "display")
            try observer.observe(at: at, detections: [detection], captureCrop: { candidate in
                attempts.append(candidate)
                switch step["result"] as! String {
                case "stored": stored += 1; return .stored
                case "failed": return .failed
                default: return .skipped
                }
            }) { sightings.append($0) }
            try check(attempts.count == step["attempts"] as! Int && stored == step["stored"] as! Int, "\(name) at \(ms) ms: crop cadence/budget")
            try check(sightings.count == (ms >= 100 ? 1 : 0), "\(name): one sighting per encounter")
            if let candidate = attempts.last {
                try check(candidate.observationID == sightings[0]["event_id"] as! String, "repeat crops keep sighting identity")
            }
        }
        try gate.validate(sightings[0], model: "sighting")
        try check(sightings[0]["representative_frame_at"] as! String == SignCollectionJSON.utc(start.addingTimeInterval(0.1)), "original sighting remains immutable")
        observer.freeze(attempt: "feedback", presentation: "display")
        try check(observer.correction(attempt: "feedback", modality: "voice", at: start.addingTimeInterval(5))?["target_id"] as? String == sightings[0]["event_id"] as? String, "repeat crops preserve correction identity")
    }

    let observer = SignCollectionObserver()
    var sightings = [[String: Any]](), captured = [SignCollectionObserver.CropCandidate]()
    let detections = (0..<5).map { index in
        SignCollectionObserver.Detection(key: "same-class", box: [Double(index) * 0.18, 0.1, 0.1, 0.1], payload: fixture, presentationTrack: nil)
    }
    func sample(_ milliseconds: Int) throws {
        var used = 0
        try observer.observe(at: start.addingTimeInterval(Double(milliseconds) / 1000), detections: detections, captureCrop: { candidate in
            guard used < 4 else { return .skipped }
            used += 1; captured.append(candidate); return .stored
        }) { sightings.append($0) }
    }
    try sample(0); try sample(100); try sample(200)
    try check(sightings.count == 5 && captured.count == 5 && Set(captured.map(\.observationID)).count == 5, "per-frame cap retries the fifth sign without merging same-class tracks")
    try observer.observe(at: start.addingTimeInterval(2.201), detections: [], commit: { sightings.append($0) })
    try sample(2300); try sample(2400)
    try check(sightings.count == 10 && captured.count == 9, "expired encounter resets crop budget and identity")
    observer.reset(); try sample(2500); try sample(2600)
    try check(sightings.count == 15 && captured.count == 13, "session/privacy reset releases crop state")

    let retry = SignCollectionObserver()
    var committed = false, prematureCrop = false
    try retry.observe(at: start, detections: [detections[0]], commit: { _ in })
    do {
        try retry.observe(at: start.addingTimeInterval(0.1), detections: [detections[0]], captureCrop: { _ in prematureCrop = true; return .stored }) { _ in
            throw SignCollectionError.storage
        }
        throw SignCollectionError.invalidContract
    } catch SignCollectionError.storage { }
    try check(!prematureCrop, "crop never precedes durable sighting commit")
    try retry.observe(at: start.addingTimeInterval(0.2), detections: [detections[0]], captureCrop: { _ in prematureCrop = committed; return .stored }) { _ in committed = true }
    try check(prematureCrop, "failed sighting commit retries before its crop")

    // Exercise repeated-frame PNGs, metadata and durable queue linkage together.
    let store = try SignCollectionStore(root: root.appendingPathComponent("repeat-crops-" + SignCollectionJSON.uuid()), gate: gate, now: { start })
    try store.beginSession(SignCollectionJSON.uuid())
    _ = try store.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: true, dontAskAgain: false)
    try store.authorizeAutomaticCrops()
    let color = CGColorSpace(name: CGColorSpace.sRGB)!
    let context = CGContext(data: nil, width: 100, height: 100, bitsPerComponent: 8, bytesPerRow: 400, space: color, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.setFillColor(CGColor(gray: 0.5, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 100, height: 100))
    let image = context.makeImage()!
    let sequence = SignCollectionObserver()
    var manifests = [[String: Any]](), storageFailure: Error?
    for (ms, size) in [(0, 0.2), (100, 0.2), (600, 0.3)] {
        let detection = SignCollectionObserver.Detection(key: "sign", box: [0.1, 0.1, size, size], payload: fixture, presentationTrack: nil)
        try sequence.observe(at: start.addingTimeInterval(Double(ms) / 1000), detections: [detection], captureCrop: { candidate in
            do {
                let box = Dictionary(uniqueKeysWithValues: zip(["x", "y", "width", "height"], candidate.box))
                let crop = try SignCollectionCrop.generate(upright: image, box: box, hashSource: false)
                var position = fixture["vehicle_position"] as! [String: Any]
                position["latitude"] = 47.0 + Double(ms) / 1_000_000
                position["course_degrees"] = Double(ms) / 10
                position["fix_at"] = SignCollectionJSON.utc(candidate.frameAt)
                position["frame_fix_delta_ms"] = 0
                let manifest = crop.metadata(cropID: SignCollectionJSON.uuid(), observationID: candidate.observationID, installationID: try store.installationID,
                    epoch: try store.collectionEpoch, sourceKind: "detector", frameAt: candidate.frameAt, localFrameToken: "frame-\(ms)",
                    privacyPreflight: "passed", redactionVersion: "metadata-strip-1", collectionClaim: try store.claim(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure),
                    vehiclePosition: position)
                try gate.validate(manifest, model: "crop")
                try store.enqueueAutomaticCrop(metadata: manifest, bytes: crop.bytes)
                manifests.append(manifest); return .stored
            } catch { storageFailure = error; return .failed }
        }) { try store.enqueue(kind: "sighting", event: $0, disclosure: SignCollectionCapabilities.metadataDisclosure) }
    }
    if let storageFailure { throw storageFailure }
    try check(store.pendingCount() == 1 && manifests.count == 2, "two crops enter durable queue for one sighting")
    try check(manifests[0]["observation_id"] as! String == manifests[1]["observation_id"] as! String && manifests[0]["crop_id"] as! String != manifests[1]["crop_id"] as! String, "repeat crop identities remain distinct")
    try check(manifests[1]["source_frame_at"] as! String == SignCollectionJSON.utc(start.addingTimeInterval(0.6)) && manifests[1]["local_frame_token"] as! String == "frame-600", "later crop describes its own exact frame")
    try check(manifests[1]["original_box"] as! [Int] == [10, 10, 40, 40], "later crop uses current geometry")
    try check((manifests[0]["vehicle_position"] as! [String: Any])["course_degrees"] as! Double == 10 &&
              (manifests[1]["vehicle_position"] as! [String: Any])["course_degrees"] as! Double == 60,
              "each crop retains its own course")
    try check((manifests[1]["vehicle_position"] as! [String: Any])["fix_at"] as! String == manifests[1]["source_frame_at"] as! String,
              "crop position fix is associated with its own frame")
    for _ in 0..<2 {
        let next = try store.nextCrop()!
        let queued = try SignCollectionJSON.parse(next.metadata) as! [String: Any]
        let original = manifests.first { $0["crop_id"] as? String == next.id }!
        try check(try SignCollectionJSON.canonical(queued["vehicle_position"]!) == SignCollectionJSON.canonical(original["vehicle_position"]!),
                  "durable queue preserves crop coordinates and course")
        try store.finishBestEffortCrop(id: next.id)
    }
    try check(store.nextCrop() == nil, "both repeated crops can drain independently")
    print("Swift repeat crops: shared cadence/growth/retry vectors, multiple signs, resets, commit ordering and durable PNG provenance passed")
}

import Foundation
import CoreGraphics

private final class CollectionFakeHTTP: SignCollectionRequesting {
    let handle: (String, String?) throws -> SignCollectionHTTPResponse
    var binary: ((String, Data) throws -> SignCollectionHTTPResponse)?
    func upload(handle: String, bytes: Data) async throws -> SignCollectionHTTPResponse { try binary!(handle, bytes) }
    init(_ handle: @escaping (String, String?) throws -> SignCollectionHTTPResponse) { self.handle = handle }
    func request(path: String, body: String?) async throws -> SignCollectionHTTPResponse { try handle(path, body) }
}

func runCollectionTransportChecks(gate: SignCollectionContractGate, root: URL, fixture: [String: Any], live: Bool) async throws {
    let disclosure = SignCollectionCapabilities.metadataDisclosure
    let caps: [String: Any] = ["contract_manifest_sha256": SignCollectionContractGate.manifestSHA256, "schema_versions": [1],
        "one_way_uploads": true, "durability": "live_eu_committed", "limits": ["metadata_bytes": 524288, "event_bytes": 16384],
        "disclosure_versions": ["sign_metadata": [disclosure], "crop_storage": [SignCollectionCapabilities.cropDisclosure]],
        "enforcement_enabled": true, "external_processor_enabled": true]
    _ = try SignCollectionCapabilities(caps) // These flags never govern metadata delivery.
    var metadataOnly = caps; metadataOnly["disclosure_versions"] = ["sign_metadata": [disclosure]]
    _ = try SignCollectionCapabilities(metadataOnly) // Optional crops cannot gate metadata.
    var invalid = caps; invalid["contract_manifest_sha256"] = String(repeating: "0", count: 64)
    rejects { _ = try SignCollectionCapabilities(invalid) }
    var time = Date()
    let store = try SignCollectionStore(root: root.appendingPathComponent("transport-" + SignCollectionJSON.uuid()), gate: gate, now: { time })
    try store.beginSession(SignCollectionJSON.uuid())
    _ = try store.decide(scope: "sign_metadata", disclosure: disclosure, granted: true, dontAskAgain: false)
    func observation() -> [String: Any] {
        var event = fixture; event["event_id"] = SignCollectionJSON.uuid(); event["collection_session_id"] = SignCollectionJSON.uuid()
        for key in ["first_seen_at", "last_seen_at", "representative_frame_at"] { event[key] = SignCollectionJSON.utc(time) }
        event["duration_ms"] = 0; event["vehicle_position"] = NSNull()
        return event
    }
    try store.enqueue(kind: "sighting", event: observation(), disclosure: disclosure)
    try store.enqueue(kind: "sighting", event: observation(), disclosure: disclosure)
    var requests: [(String, String?)] = [], lostBody: String?, lose = true, split = true
    let http = CollectionFakeHTTP { path, body in
        requests.append((path, body))
        if path == "capabilities" { return .init(status: 200, body: caps, retryAfter: nil) }
        let value = try SignCollectionJSON.parse(body!) as! [String: Any]
        if path == "consent-events" { return .init(status: 200, body: ["operation_receipt": "consent-" + (value["event_id"] as! String), "state": "recorded"], retryAfter: nil) }
        if lose { lose = false; lostBody = body; throw URLError(.networkConnectionLost) }
        if split { try check(body == lostBody, "lost ACK retries identical HTTP body"); split = false; return .init(status: 413, body: ["error": "request_too_large"], retryAfter: nil) }
        return .init(status: 200, body: ["schema_version": 1, "batch_id": value["batch_id"]!, "collection_epoch": value["collection_epoch"]!,
            "durability": "live_eu_committed", "operation_receipt": "batch-" + (value["batch_id"] as! String),
            "results": (value["events"] as! [[String: Any]]).map { ["event_id": $0["event_id"]!, "status": "accepted", "retryable": false] }], retryAfter: nil)
    }
    let worker = SignCollectionUploadWorker(store: store, client: http, now: { time }, jitter: { 0 })
    let offline = try await worker.runOnce(networkAvailable: false, ordinaryDeliveryAllowed: true)
    try check(offline == "offline" && requests.isEmpty && store.pendingCount() == 2, "offline delivery retains observations without making requests")
    // Privacy controls run even while ordinary contributions are paused.
    let paused = try await worker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: false)
    try check(paused == "contribution_paused" && requests.contains { $0.0 == "consent-events" }, "controls precede ordinary delivery gating")
    do { _ = try await worker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true); fatalError("lost ACK expected") } catch is URLError {}
    try check(store.pendingCount() == 2, "lost response preserves all events")
    time = time.addingTimeInterval(10)
    let splitResult = try await worker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    try check(splitResult == "batch_split", "413 splits immutable batch")
    for _ in 0..<2 { _ = try await worker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true) }
    try check(store.pendingCount() == 0, "child batches commit independently")
    let bodies = try requests.filter { $0.0 == "sighting-batches" }.map { try SignCollectionJSON.parse($0.1!) as! [String: Any] }
    try check(bodies.count == 4 && bodies[0]["batch_id"] as! String == bodies[1]["batch_id"] as! String && bodies[2]["batch_id"] as! String != bodies[0]["batch_id"] as! String, "413 replaces only batch identity")
    let originalIDs = Set((bodies[0]["events"] as! [[String: Any]]).map { $0["event_id"] as! String })
    try check(Set(bodies.suffix(2).flatMap { ($0["events"] as! [[String: Any]]).map { $0["event_id"] as! String } }) == originalIDs, "413 preserves event identities")
    print("Swift host transport: capabilities, privacy priority, lost ACK replay and 413 split passed")

    // A separate host-only observer replay verifies all-class sightings and frozen corrections.
    let observer = SignCollectionObserver(); var sightings: [[String: Any]] = []
    let detection = SignCollectionObserver.Detection(key: "non-speed", box: [0.1,0.1,0.2,0.2], payload: fixture, presentationTrack: "presentation-1")
    try observer.observe(at: time, detections: [detection]) { sightings.append($0) }
    try observer.observe(at: time.addingTimeInterval(0.1), detections: [detection]) { sightings.append($0) }
    try observer.observe(at: time.addingTimeInterval(0.2), detections: [detection]) { sightings.append($0) }
    try check(sightings.count == 1, "continuing frames create one sighting")
    observer.freeze(attempt: "speech-1", presentation: "presentation-1")
    try observer.observe(at: time.addingTimeInterval(3), detections: []) { sightings.append($0) }
    let correction = observer.correction(attempt: "speech-1", modality: "voice", at: time.addingTimeInterval(3))!
    try check(correction["target_id"] as! String == sightings[0]["event_id"] as! String, "speech-start target survives later frames")
    try gate.validate(correction, model: "correction")
    observer.freeze(attempt: "speech-after-feedback", presentation: "presentation-1")
    try check(observer.correction(attempt: "speech-after-feedback", modality: "voice", at: time.addingTimeInterval(3))?["target_id"] as? String == sightings[0]["event_id"] as? String, "display association remains after sign leaves the frame")
    print("Swift host observer: qualification, duplicate suppression and speech-start target passed")
    let privacyStore = try SignCollectionStore(root: root.appendingPathComponent("privacy-transport-" + SignCollectionJSON.uuid()), gate: gate)
    try privacyStore.beginSession(SignCollectionJSON.uuid())
    _ = try privacyStore.decide(scope: "sign_metadata", disclosure: disclosure, granted: true, dontAskAgain: false)
    let deletionID = try privacyStore.requestDeletion()
    var privacyPaths: [String] = [], activeRemoved = false
    let privacyHTTP = CollectionFakeHTTP { path, _ in
        privacyPaths.append(path)
        if path == "capabilities" { return .init(status: 200, body: caps, retryAfter: nil) }
        try check(path != "consent-events", "old unsent consent must not starve the deletion barrier")
        return .init(status: 200, body: ["operation_receipt": "delete-receipt", "state": activeRemoved ? "active_data_removed" : "deletion_pending", "next_collection_epoch": 1,
            "active_data_removed": activeRemoved, "archives_purged": false, "backup_expiry_complete": false], retryAfter: nil)
    }
    let privacyWorker = SignCollectionUploadWorker(store: privacyStore, client: privacyHTTP)
    _ = try await privacyWorker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: false)
    try check(privacyPaths.contains("operation-status") && privacyStore.collectionEpoch == 0, "poll barrier while ordinary contributions are paused")
    activeRemoved = true
    _ = try await privacyWorker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: false)
    try check(privacyStore.collectionEpoch == 1 && !privacyStore.deletionIsPending && privacyStore.controlStatus(id: deletionID)?.isComplete == false, "active removal releases epoch before backup completion")
    print("Swift host transport: deletion priority, old consent barrier and separate backup phases passed")
    // Recovery acceptance is a host suite, never an app developer mode.
    let recoveryRoot = root.appendingPathComponent("recovery-" + SignCollectionJSON.uuid())
    var recovery: SignCollectionStore? = try SignCollectionStore(root: recoveryRoot, gate: gate)
    let recoveryIdentity = try recovery!.installationID
    try recovery!.beginSession(SignCollectionJSON.uuid())
    _ = try recovery!.decide(scope: "sign_metadata", disclosure: disclosure, granted: true, dontAskAgain: false)
    try recovery!.enqueue(kind: "sighting", event: observation(), disclosure: disclosure)
    let recoveringBatch = try recovery!.prepareBatch()!
    for control in try recovery!.pendingControls() { try recovery!.applyControlReceipt(id: control.id, response: ["operation_receipt": "recorded-recovery-consent", "state": "recorded"]) }
    recovery = nil // Close/checkpoint before copying the recovery image.
    let restoredRoot = root.appendingPathComponent("restored-" + SignCollectionJSON.uuid())
    try FileManager.default.copyItem(at: recoveryRoot, to: restoredRoot)
    let restored = try SignCollectionStore(root: restoredRoot, gate: gate)
    try check(restored.installationID == recoveryIdentity && restored.collectionEpoch == 0 && restored.prepareBatch()!.body == recoveringBatch.body, "recovery retains identity, epoch and immutable request")
    let goneHTTP = CollectionFakeHTTP { path, _ in .init(status: path == "capabilities" ? 200 : 410, body: path == "capabilities" ? caps : ["error": "epoch_deleted"], retryAfter: nil) }
    let recoveryWorker = SignCollectionUploadWorker(store: restored, client: goneHTTP)
    let gone = try await recoveryWorker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    try check(gone == "quarantined" && restored.collectionEpoch == 0 && restored.prepareBatch() == nil, "deleted-epoch backup is quarantined without relabelling")
    print("Swift host recovery: identity, epoch, request bytes and 410 quarantine passed")
    try await runCropChecks(gate: gate, root: root, caps: caps)
    guard live else { return }

    // Explicit computer-suite opt-in. No synthetic generator is linked into either app.
    let liveStore = try SignCollectionStore(root: root.appendingPathComponent("live-host-" + SignCollectionJSON.uuid()), gate: gate)
    let client = try SignCollectionHTTPClient(); defer { client.close() }
    let transport = SignCollectionUploadWorker(store: liveStore, client: client)
    _ = try await transport.capabilities()
    try liveStore.beginSession(SignCollectionJSON.uuid())
    _ = try liveStore.decide(scope: "sign_metadata", disclosure: disclosure, granted: true, dontAskAgain: false)
    let liveCropClaim = try liveStore.decide(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure, granted: true, dontAskAgain: false)
    var synthetic = observation(); synthetic["source_kind"] = "manual_capture"; synthetic["model"] = NSNull()
    synthetic["app"] = ["platform": "ios", "version": "1.4", "build": "computer-contract-suite"]
    synthetic["scores"] = ["detector_raw": NSNull(), "classifier_raw": NSNull(), "raw_domain": NSNull(), "calibrated_confidence": NSNull(), "track_support": NSNull()]
    synthetic["classification"] = ["country": "unknown", "model_label": NSNull(), "canonical_code": NSNull(), "family": "unknown", "value": NSNull(), "unit": NSNull(), "role": "unknown", "mapping_revision": NSNull(), "mapping_sha256": NSNull(), "alternatives": []]
    try liveStore.enqueue(kind: "sighting", event: synthetic, disclosure: disclosure)
    let saved = try liveStore.prepareBatch()!
    // One computer-generated solid-color pixel, with no people, plates or private text.
    var livePixel: [UInt8] = [0,170,187,255]
    let liveContext = CGContext(data: &livePixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
    let liveCrop = try SignCollectionCrop.generate(upright: liveContext.makeImage()!, box: ["x":0,"y":0,"width":1,"height":1])
    let liveCropID = SignCollectionJSON.uuid()
    let liveCropMetadata = liveCrop.metadata(cropID: liveCropID, observationID: synthetic["event_id"] as! String,
        installationID: try liveStore.installationID, epoch: 0, sourceKind: "manual_capture", frameAt: Date(), localFrameToken: "computer-generated-pixel",
        privacyPreflight: "user_reviewed", redactionVersion: "host-solid-pixel-1", collectionClaim: liveCropClaim)
    try liveStore.enqueueAutomaticCrop(metadata: liveCropMetadata, bytes: liveCrop.bytes)
    do {
        let committed = try await transport.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
        try check(committed == "crop_committed" && liveStore.nextCrop() == nil && liveStore.pendingCount() == 1, "live durable metadata and bounded crop intake")
        _ = try await transport.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
        try check(liveStore.pendingCount() == 0, "live linked media status committed")
        let cropReplay = try await client.request(path: "media-uploads", body: SignCollectionJSON.canonical(liveCropMetadata))
        try check(cropReplay.status == 200 && cropReplay.body["state"] as? String == "media_durable" && cropReplay.body["sha256"] as? String == liveCrop.encodedHash, "live crop reservation replay identifies durable exact bytes")
        let replay = try await client.request(path: "sighting-batches", body: saved.body)
        try check(replay.status == 200, "live immutable replay HTTP 200")
        try liveStore.applyBatchReceipt(replay.body)
        print("Live host suite: native HTTPS capabilities, synthetic metadata/crop, linked status and exact replays passed")
    } catch {
        _ = try liveStore.requestDeletion()
        _ = try? await transport.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
        throw error
    }
    let deletion = try liveStore.requestDeletion()
    _ = try await transport.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    try check(liveStore.controlStatus(id: deletion)?.receipt != nil, "live deletion receipt persisted")
    print("Live host suite: synthetic-data deletion submitted; completion phases remain receipt-driven")
    for _ in 0..<6 {
        if try !liveStore.deletionIsPending { break }
        try await Task.sleep(nanoseconds: 20_000_000_000)
        _ = try await transport.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    }
    let phases = try liveStore.controlStatus(id: deletion)!.response ?? [:]
    print("Live deletion phases: active=\(SignCollectionJSON.boolean(phases["active_data_removed"]) == true), archives=\(SignCollectionJSON.boolean(phases["archives_purged"]) == true), backups=\(SignCollectionJSON.boolean(phases["backup_expiry_complete"]) == true)")
}

/// Resume host-suite deletion receipts without generating another observation.
func resumeCollectionHostCleanup(gate: SignCollectionContractGate, root: URL) async throws {
    let client = try SignCollectionHTTPClient(); defer { client.close() }
    let directories = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil).filter { $0.lastPathComponent.hasPrefix("live-host-") }
    for directory in directories {
        let store = try SignCollectionStore(root: directory, gate: gate)
        guard try store.pendingControls().contains(where: { $0.kind == "deletion" }) else { continue }
        let worker = SignCollectionUploadWorker(store: store, client: client)
        _ = try await worker.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
        for deletion in try store.controlHistory().filter({ $0.kind == "deletion" }) {
            let phases = deletion.response ?? [:]
            print("Resumed host cleanup: active=\(SignCollectionJSON.boolean(phases["active_data_removed"]) == true), archives=\(SignCollectionJSON.boolean(phases["archives_purged"]) == true), backups=\(SignCollectionJSON.boolean(phases["backup_expiry_complete"]) == true)")
        }
    }
}

private func runCropChecks(gate: SignCollectionContractGate, root: URL, caps originalCaps: [String: Any]) async throws {
    var caps = originalCaps; caps["limits"] = ["metadata_bytes": 524288, "event_bytes": 16384, "media_bytes": 5242880]
    var time = Date()
    let directory = root.appendingPathComponent("crop-recovery-" + SignCollectionJSON.uuid())
    var store: SignCollectionStore? = try SignCollectionStore(root: directory, gate: gate, now: { time })
    try store!.beginSession(SignCollectionJSON.uuid())
    _ = try store!.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: true, dontAskAgain: false)
    try store!.authorizeAutomaticCrops()
    let claim = try store!.claim(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure)
    var pixel: [UInt8] = [0,170,187,255]
    let context = CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
    let crop = try SignCollectionCrop.generate(upright: context.makeImage()!, box: ["x":0,"y":0,"width":1,"height":1])
    let id = SignCollectionJSON.uuid(), observation = SignCollectionJSON.uuid()
    let metadata = crop.metadata(cropID: id, observationID: observation, installationID: try store!.installationID, epoch: 0, sourceKind: "detector", frameAt: time,
        localFrameToken: "host-crop-frame", privacyPreflight: "user_reviewed", redactionVersion: "user-review-1", collectionClaim: claim)
    try store!.stageCrop(metadata: metadata, bytes: crop.bytes)
    try check(store!.nextCrop() == nil && store!.cropReviewCount() == 1, "legacy staged bytes wait for migration")
    store!.endSession(); store = nil
    store = try SignCollectionStore(root: directory, gate: gate, now: { time })
    try check(store!.cropReviewCount() == 1, "crop reviews survive restart without granting new consent")
    try store!.migrateAutomaticCrops()
    try check(store!.cropReviewCount() == 0 && store!.nextCrop()!.bytes == crop.bytes, "automatic migration commits original bytes after session end")
    var reservedBody: String?, durable = false, puts = 0, linked = false
    let http = CollectionFakeHTTP { path, body in
        if path == "capabilities" { return .init(status: 200, body: caps, retryAfter: nil) }
        let value = try SignCollectionJSON.parse(body!) as! [String: Any]
        if path == "consent-events" { return .init(status: 200, body: ["state":"recorded", "operation_receipt":"grant-" + (value["event_id"] as! String)], retryAfter: nil) }
        if path == "media-uploads" {
            if let previous = reservedBody { try check(previous == body, "reservation replay retains exact metadata") }; reservedBody = body
            try check(value["privacy_preflight"] as? String == "passed", "automatic upload must not claim user review")
            return .init(status: 200, body: durable ? ["state":"media_durable", "durability":"live_eu_committed", "operation_receipt":"crop-receipt", "sha256":crop.encodedHash] : ["state":"reserved", "operation_receipt":"crop-receipt", "sha256":crop.encodedHash, "handle":"safe_handle"], retryAfter: nil)
        }
        try check(path == "media-status-batches", "only append-only media status remains")
        let events = value["events"] as! [[String: Any]]
        try check(events.count == 1 && events[0]["status"] as? String == "linked" && events[0]["observation_id"] as? String == observation, "durable media appends exact linked status")
        linked = true
        return .init(status: 200, body: ["schema_version":1,"batch_id":value["batch_id"]!,"collection_epoch":0,"durability":"live_eu_committed","operation_receipt":"media-status-receipt", "results":events.map { ["event_id":$0["event_id"]!,"status":"accepted","retryable":false] }], retryAfter: nil)
    }
    http.binary = { handle, bytes in
        try check(handle == "safe_handle" && bytes == crop.bytes, "scoped PUT preserves encoded bytes")
        puts += 1; durable = true; throw URLError(.networkConnectionLost)
    }
    var worker: SignCollectionUploadWorker? = SignCollectionUploadWorker(store: store!, client: http, now: { time }, jitter: {0})
    _ = try await worker!.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: false)
    try check(puts == 0, "paused contributions cannot transfer crop bytes")
    let lostCrop = try await worker!.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    try check(lostCrop == "crop_delivery_unavailable" && store!.transportRetryDate() <= time, "crop outage cannot back off metadata or privacy controls")
    try check(store!.nextCrop()!.bytes == crop.bytes && store!.nextCrop()!.receipt == "crop-receipt", "lost ACK retains content and reservation receipt")
    worker = nil; store = nil; time = time.addingTimeInterval(10)
    let restored = root.appendingPathComponent("crop-restored-" + SignCollectionJSON.uuid())
    try FileManager.default.copyItem(at: directory, to: restored)
    store = try SignCollectionStore(root: restored, gate: gate, now: { time })
    worker = SignCollectionUploadWorker(store: store!, client: http, now: { time }, jitter: {0})
    _ = try await worker!.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    try check(store!.nextCrop() == nil && puts == 1 && store!.pendingCount() == 1, "reservation recovery resolves lost ACK without resending durable bytes")
    _ = try await worker!.runOnce(networkAvailable: true, ordinaryDeliveryAllowed: true)
    try check(linked && store!.pendingCount() == 0, "media status acknowledged independently")
    try store!.beginSession(SignCollectionJSON.uuid())
    _ = try store!.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: true, dontAskAgain: false)
    let renewed = try store!.decide(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure, granted: true, dontAskAgain: false)
    func stage() throws -> String {
        let id = SignCollectionJSON.uuid()
        let value = crop.metadata(cropID: id, observationID: observation, installationID: try store!.installationID, epoch: 0, sourceKind: "detector", frameAt: time,
            localFrameToken: nil, privacyPreflight: "user_reviewed", redactionVersion: "user-review-1", collectionClaim: renewed)
        try store!.stageCrop(metadata: value, bytes: crop.bytes); return id
    }
    _ = try stage(); try store!.migrateAutomaticCrops(); _ = try stage()
    time = time.addingTimeInterval(8*86400); try store!.expireCrops()
    try check(store!.cropReviewCount() == 0 && store!.nextCrop() == nil && store!.expiredCropCount() == 2, "review and transfer bytes expire after seven days")
    let expiration = try store!.prepareBatch()!
    let expirationEnvelope = try SignCollectionJSON.parse(expiration.body) as! [String: Any]
    try check((expirationEnvelope["events"] as! [[String: Any]])[0]["status"] as? String == "expired", "expired upload adds captured-authorized status")
    let automatic = try SignCollectionCrop.generate(upright: context.makeImage()!, box: ["x":0,"y":0,"width":1,"height":1], hashSource: false)
    try check(automatic.sourceHash == nil && automatic.bytes == crop.bytes, "runtime crop skips full-frame hashing without changing pixels")
    let automaticMetadata = automatic.metadata(cropID: SignCollectionJSON.uuid(), observationID: observation, installationID: try store!.installationID, epoch: 0, sourceKind: "detector", frameAt: time,
        localFrameToken: "automatic-host-frame", privacyPreflight: "passed", redactionVersion: "metadata-strip-1", collectionClaim: renewed)
    try store!.enqueueAutomaticCrop(metadata: automaticMetadata, bytes: automatic.bytes)
    store!.endSession()
    try check(store!.nextCrop()!.bytes == automatic.bytes && store!.cropReviewCount() == 0, "new capture enters automatic upload directly and survives session end")
    try store!.withdraw(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure)
    try check(store!.cropReviewCount() == 0 && store!.nextCrop() == nil, "withdrawal purges optional evidence")
    print("Swift host crops: automatic migration, recovery copy, lost PUT ACK, linked/expired status and withdrawal passed")

    let filter = SignCaptureFilter(), start = Date()
    let signs = [SignCaptureFilter.Detection(key:"white",label:"white",box:[0.1,0.1,0.2,0.2],score:0.8), SignCaptureFilter.Detection(key:"white",label:"white",box:[0.7,0.1,0.2,0.2],score:0.9)]
    try check(filter.observe(at:start,detections:signs).isEmpty, "one frame cannot capture")
    let qualified = filter.observe(at:start.addingTimeInterval(0.1),detections:signs)
    try check(qualified.count == 2 && Set(qualified.map(\.trackID)).count == 2, "same-class signs retain separate encounters")
    filter.captured(qualified,at:start.addingTimeInterval(0.1))
    try check(filter.observe(at:start.addingTimeInterval(0.2),detections:signs).isEmpty, "continuing encounter deduplicates")
    _ = filter.observe(at:start.addingTimeInterval(3),detections:[])
    _ = filter.observe(at:start.addingTimeInterval(3.1),detections:signs)
    try check(filter.observe(at:start.addingTimeInterval(3.2),detections:signs).count == 2, "new encounter qualifies after absence")
    print("Swift host Panoramax filter: all-class stability, encounter identity and duplicate suppression passed")
}

import Foundation
import CoreGraphics
import ImageIO

func check(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
    if try !condition() { fatalError(message) }
}
func rejects(_ body: () throws -> Void) { do { try body(); fatalError("expected rejection") } catch {} }
let contractRoot = URL(fileURLWithPath: CommandLine.arguments[1])
let outputRoot = URL(fileURLWithPath: CommandLine.arguments[2])
try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)
let gate = try SignCollectionContractGate { try Data(contentsOf: contractRoot.appendingPathComponent($0)) }
try check(gate.verified && gate.liveTransportAllowed, "verified transport contract")
for text in ["{\"a\":1,\"a\":2}", "9007199254740992", "NaN", "[1,]", "1 garbage"] { rejects { _ = try SignCollectionJSON.parse(text) } }
for name in ["sighting", "manual"] {
    let value = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/" + name + "-batch-v1.json"), encoding: .utf8)) as! [String: Any]
    try gate.validate(value, model: "batch")
    for event in value["events"] as! [[String: Any]] { try gate.validate(event, model: "sighting") }
}
for name in ["correction", "consent", "deletion", "crop", "media-status"] {
    try gate.validate(SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/" + name + "-v1.json"), encoding: .utf8)), model: name)
}
let clientVectors = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("tests/tsr/collection/canonical-edge-cases.json")
for vector in try SignCollectionJSON.parse(String(contentsOf: clientVectors, encoding: .utf8)) as! [[String: Any]] {
    try check(SignCollectionJSON.canonical(vector["input"]!) == vector["canonical"] as! String, "extended binary64 canonicalization: expected \(vector["canonical"]!), got \(try SignCollectionJSON.canonical(vector["input"]!))")
    try check(SignCollectionJSON.digest(vector["input"]!) == vector["sha256"] as! String, "extended binary64 digest")
}
let extraNumbers = [1e23, 1e-6, -0.0, 0.30000000000000004, Double.leastNonzeroMagnitude, 1.2345678901234567]
try Data(SignCollectionJSON.canonical(extraNumbers).utf8).write(to: outputRoot.appendingPathComponent("swift-numbers.json"))
let fixture = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/sighting-batch-v1.json"), encoding: .utf8)) as! [String: Any]
let event = (fixture["events"] as! [[String: Any]])[0]
var instant = ISO8601DateFormatter().date(from: "2026-10-02T09:55:00Z")!
let root = outputRoot.appendingPathComponent("swift-db-" + SignCollectionJSON.uuid())
var store: SignCollectionStore? = try SignCollectionStore(root: root, gate: gate, now: { instant })
let installation = try store!.installationID
let session = SignCollectionJSON.uuid()
try store!.beginSession(session)
try check(store!.shouldPrompt(scope: "sign_metadata", disclosure: "example-camera-use-1"), "first prompt")
try store!.beginSession(session)
try check(!store!.shouldPrompt(scope: "sign_metadata", disclosure: "example-camera-use-1"), "resume must not repeat prompt")
_ = try store!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: true, dontAskAgain: false)
try store!.enqueue(kind: "sighting", event: event, disclosure: "example-camera-use-1")
let batch = try store!.prepareBatch()!
try Data(batch.body.utf8).write(to: outputRoot.appendingPathComponent("swift-batch.json"))
store = nil
store = try SignCollectionStore(root: root, gate: gate, now: { instant })
try check(store!.installationID == installation && store!.collectionEpoch == 0, "restart identity/epoch")
try check(store!.prepareBatch()!.body == batch.body, "lost ACK exact bytes")
rejects { try store!.enqueue(kind: "sighting", event: event, disclosure: "example-camera-use-1") }
func receipt(_ status: String, eventID: String? = nil) -> [String: Any] {
    ["schema_version": 1, "batch_id": batch.id, "collection_epoch": batch.epoch, "durability": "live_eu_committed", "operation_receipt": "test-private-receipt", "results": [["event_id": eventID ?? event["event_id"]!, "status": status, "retryable": status == "retry_later"]]]
}
rejects { try store!.applyBatchReceipt(receipt("accepted", eventID: SignCollectionJSON.uuid())) }
try check(store!.pendingCount() == 1, "unknown receipt preserves pending")
try store!.applyBatchReceipt(receipt("retry_later"))
try check(store!.prepareBatch() == nil, "retry backoff")
instant = instant.addingTimeInterval(61)
let second = try store!.prepareBatch()!
try check(second.id != batch.id, "retry_later needs new immutable batch")
var accepted = receipt("duplicate"); accepted["batch_id"] = second.id
try store!.applyBatchReceipt(accepted)
try check(store!.pendingCount() == 0, "duplicate receipt releases event")
try store!.beginSession(SignCollectionJSON.uuid())
try check(store!.shouldPrompt(scope: "sign_metadata", disclosure: "example-camera-use-1"), "unchecked acceptance session only")
_ = try store!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: false, dontAskAgain: true)
store!.endSession(); try store!.beginSession(SignCollectionJSON.uuid())
try check(!store!.shouldPrompt(scope: "sign_metadata", disclosure: "materially-changed"), "remembered refusal survives scope change")
_ = try store!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: true, dontAskAgain: true)
try store!.enqueue(kind: "sighting", event: event, disclosure: "example-camera-use-1")
let deletion = try store!.requestDeletion()
try check(store!.requestDeletion() == deletion && store!.pendingCount() == 0, "durable deletion/idempotence")
rejects { _ = try store!.prepareBatch() }
try Data(store!.nextControl()!.body.utf8).write(to: outputRoot.appendingPathComponent("swift-deletion.json"))
let pending: [String: Any] = ["operation_receipt": "deletion-private-receipt", "state": "deletion_pending", "next_collection_epoch": 1, "active_data_removed": false]
try store!.applyControlReceipt(id: deletion, response: pending)
store = nil; store = try SignCollectionStore(root: root, gate: gate, now: { instant })
try check(store!.nextControl()!.receipt == "deletion-private-receipt" && store!.collectionEpoch == 0, "deletion receipt persisted without premature epoch advance")
var removed = pending; removed["active_data_removed"] = true; removed["state"] = "active_data_removed"
try store!.applyControlReceipt(id: deletion, response: removed)
try check(store!.installationID == installation && store!.collectionEpoch == 1, "delete retains UUID advances epoch")
rejects { try store!.enqueue(kind: "sighting", event: event, disclosure: "example-camera-use-1") }
let crop = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/crop-v1.json"), encoding: .utf8)) as! [String: Any]
let geometry = try SignCollectionCropGeometry(width: crop["source_width"] as! Int, height: crop["source_height"] as! Int, box: crop["supplied_box"] as! [String: Double])
try check(geometry.original == crop["original_box"] as! [Int] && geometry.actual == crop["actual_box"] as! [Int], "golden bottom clip")
var pixel: [UInt8] = [0, 0xaa, 0xbb, 255]
let context = CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
let encoded = try SignCollectionCrop.generate(upright: context.makeImage()!, box: ["x": 0, "y": 0, "width": 1, "height": 1])
try check(encoded.sourceHash == "12cc7f777c6213cec843bd1056ed1e2e1677c8f728e0b1d28d84000f53882d7e", "RGB8 no padding source hash")
try check(CGImageSourceCreateWithData(encoded.bytes as CFData, nil) != nil, "decodable crop")
try check(encoded.geometry.requested == [0,0,1,2] && encoded.geometry.actual == [0,0,1,1], "no bottom padding")
try store!.beginSession(SignCollectionJSON.uuid())
let cropClaim = try store!.decide(scope: "crop_storage", disclosure: "crop-1", granted: true, dontAskAgain: false)
let cropID = SignCollectionJSON.uuid()
let cropMetadata = encoded.metadata(cropID: cropID, observationID: SignCollectionJSON.uuid(), installationID: installation, epoch: 1, sourceKind: "manual_capture", frameAt: instant, localFrameToken: "synthetic-frame", privacyPreflight: "user_reviewed", redactionVersion: "review-1", collectionClaim: cropClaim)
try store!.enqueueCrop(metadata: cropMetadata, bytes: encoded.bytes, disclosure: "crop-1")
try Data(SignCollectionJSON.canonical(cropMetadata).utf8).write(to: outputRoot.appendingPathComponent("swift-crop.json"))
try encoded.bytes.write(to: outputRoot.appendingPathComponent("swift-crop.png"))
try Data(store!.nextControl()!.body.utf8).write(to: outputRoot.appendingPathComponent("swift-consent.json"))
store = nil; store = try SignCollectionStore(root: root, gate: gate, now: { instant })
try check(store!.nextCrop()!.bytes == encoded.bytes, "durable crop bytes after restart")
try store!.applyCropReceipt(id: cropID, response: ["state": "reserved", "handle": "upload-handle", "operation_receipt": "crop-receipt", "sha256": encoded.encodedHash])
try check(store!.nextCrop()!.handle == "upload-handle", "crop handle durable")
try store!.applyCropReceipt(id: cropID, response: ["state": "media_durable", "durability": "live_eu_committed", "operation_receipt": "crop-receipt", "sha256": encoded.encodedHash])
try check(store!.nextCrop() == nil, "release crop only after durable receipt")
print("Swift: pinned contracts, JSON identity, consent memory, SQLite restart, immutable receipts, deletion barrier and pixel crop passed")

// A second owner cannot use a stale session grant after an explicit withdrawal.
let peer = try SignCollectionStore(root: root, gate: gate, now: { instant })
try store!.beginSession(SignCollectionJSON.uuid())
try store!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: true, dontAskAgain: false)
try peer.withdraw(scope: "sign_metadata", disclosure: "example-camera-use-1")
var fresh = event; fresh["event_id"] = SignCollectionJSON.uuid()
rejects { try store!.enqueue(kind: "sighting", event: fresh, disclosure: "example-camera-use-1") }
try store!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: true, dontAskAgain: false)
try store!.enqueue(kind: "sighting", event: fresh, disclosure: "example-camera-use-1")
_ = try store!.prepareBatch()
instant = instant.addingTimeInterval(31 * 86400)
try check(store!.prepareBatch() == nil && store!.pendingCount() == 0 && store!.expiredEventCount() == 1, "in-flight expiration bounded and visible")
print("Swift: stale consent blocked; unacknowledged batch expiration recorded")

var rows: [UInt8] = []
let colors: [[UInt8]] = [[255,0,0], [0,255,0], [0,0,255], [255,255,0]]
var rowRGB = Data()
for color in colors { for _ in 0..<2 { rows.append(contentsOf: color + [255]); rowRGB.append(contentsOf: color) } }
let rowContext = CGContext(data: &rows, width: 2, height: 4, bitsPerComponent: 8, bytesPerRow: 8, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
let rowCrop = try SignCollectionCrop.generate(upright: rowContext.makeImage()!, box: ["x": 0, "y": 0.25, "width": 1, "height": 0.25])
try check(rowCrop.sourceHash == SignCollectionJSON.sha256(rowRGB), "upright source scanline order")
try check(rowCrop.geometry.actual == [0,1,2,3], "top-left crop row geometry")
try rowCrop.bytes.write(to: outputRoot.appendingPathComponent("swift-rows.png"))
print("Swift: upright RGB scanline order passed")

// Privacy receipts survive acknowledgements, restarts and later epoch barriers.
func checkPrivacyOperationRecovery() throws {
    let privacyRoot = outputRoot.appendingPathComponent("swift-privacy-" + SignCollectionJSON.uuid())
    var owner: SignCollectionStore? = try SignCollectionStore(root: privacyRoot, gate: gate)
    defer { owner = nil; try? FileManager.default.removeItem(at: privacyRoot) }
    try owner!.beginSession(SignCollectionJSON.uuid())
    try owner!.decide(scope: "processor:test", disclosure: "processor-1", granted: true, dontAskAgain: false)
    let grant = try owner!.nextControl()!.id
    try owner!.applyControlReceipt(id: grant, response: ["operation_receipt": "grant-receipt", "state": "recorded"])
    try owner!.withdraw(scope: "processor:test", disclosure: "processor-1")
    let withdrawal = try owner!.nextControl()!.id
    let stopping: [String: Any] = ["operation_receipt": "withdrawal-receipt", "state": "processing_stop_pending"]
    try owner!.applyControlReceipt(id: withdrawal, response: stopping)
    owner = nil; owner = try SignCollectionStore(root: privacyRoot, gate: gate)
    try check(owner!.nextControl()!.receipt == "withdrawal-receipt", "pending withdrawal polls after restart")
    rejects { try owner!.applyControlReceipt(id: withdrawal, response: ["operation_receipt": "withdrawal-receipt", "state": "processing_stopped"]) }
    rejects { try owner!.applyControlReceipt(id: withdrawal, response: ["operation_receipt": "changed-receipt", "state": "processing_stop_applied"]) }
    func deletionReceipt(_ epoch: Int, _ token: String, removed: Bool, archives: Bool = false, backups: Bool = false) -> [String: Any] {
        ["operation_receipt": token, "state": removed ? "active_data_removed" : "deletion_pending", "next_collection_epoch": epoch + 1,
         "active_data_removed": removed, "archives_purged": archives, "backup_expiry_complete": backups]
    }
    let first = try owner!.requestDeletion()
    try owner!.applyControlReceipt(id: first, response: deletionReceipt(0, "first-delete", removed: false))
    try check(owner!.pendingControls().map(\.id) == [first, withdrawal], "barrier first; pending withdrawal retained")
    let active = deletionReceipt(0, "first-delete", removed: true)
    try owner!.applyControlReceipt(id: first, response: active)
    owner = nil; owner = try SignCollectionStore(root: privacyRoot, gate: gate)
    try check(owner!.collectionEpoch == 1 && !owner!.controlStatus(id: first)!.isComplete, "active removal is not backup completion")
    try check(owner!.pendingControls().contains { $0.id == first && $0.receipt == "first-delete" }, "deletion remains pollable after restart")
    try check(owner!.controlStatus(id: grant)!.isComplete, "earlier acknowledged controls survive deletion")
    try owner!.beginSession(SignCollectionJSON.uuid())
    try owner!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: true, dontAskAgain: false)
    let currentGrant = try owner!.nextControl()!.id
    try check(currentGrant != first && currentGrant != withdrawal, "new control is not starved by background polls")
    try owner!.applyControlReceipt(id: currentGrant, response: ["operation_receipt": "current-grant", "state": "recorded"])
    try owner!.applyControlReceipt(id: first, response: active) // Idempotent; must not clear the new session.
    try check(owner!.collectionEpoch == 1, "same completion cannot advance epoch twice")
    var observation = event; observation["event_id"] = SignCollectionJSON.uuid()
    try owner!.enqueue(kind: "sighting", event: observation, disclosure: "example-camera-use-1")
    let second = try owner!.requestDeletion()
    try owner!.applyControlReceipt(id: first, response: deletionReceipt(0, "first-delete", removed: true, archives: true))
    try check(owner!.controlStatus(id: first)!.response?["archives_purged"] as? Bool == true, "archive phase stored separately")
    try check(!owner!.controlStatus(id: first)!.isComplete && owner!.nextControl()!.id == second, "archive purge does not release another barrier or complete backups")
    try owner!.applyControlReceipt(id: first, response: deletionReceipt(0, "first-delete", removed: true, archives: true, backups: true))
    try check(owner!.collectionEpoch == 1, "historical receipt does not alter current barrier epoch")
    rejects { _ = try owner!.prepareBatch() }
    rejects { try owner!.applyControlReceipt(id: first, response: active) }
    try owner!.applyControlReceipt(id: second, response: deletionReceipt(1, "second-delete", removed: true))
    try check(owner!.collectionEpoch == 2, "next deletion advances once")
    let applied: [String: Any] = ["operation_receipt": "withdrawal-receipt", "state": "processing_stop_applied"]
    try owner!.applyControlReceipt(id: withdrawal, response: applied)
    rejects { try owner!.applyControlReceipt(id: withdrawal, response: stopping) }
    try owner!.clearPendingForDeveloper()
    owner = nil; owner = try SignCollectionStore(root: privacyRoot, gate: gate)
    try check(owner!.controlStatus(id: first)!.isComplete && owner!.controlStatus(id: withdrawal)!.isComplete, "completed privacy history survives restart and later deletion")
    try check(owner!.pendingControls().map(\.id) == [second], "only unfinished phases remain pollable")
    try owner!.applyControlReceipt(id: second, response: deletionReceipt(1, "second-delete", removed: true, archives: true, backups: true))
    try check(owner!.nextControl() == nil && owner!.collectionEpoch == 2, "completed operations stop polling")
}
try checkPrivacyOperationRecovery()
print("Swift: privacy receipt recovery, separate deletion phases, repeat completion and historical epoch safety passed")

func checkEventSizeBoundary() throws {
    let sizeRoot = outputRoot.appendingPathComponent("swift-size-" + SignCollectionJSON.uuid())
    var owner: SignCollectionStore? = try SignCollectionStore(root: sizeRoot, gate: gate)
    defer { owner = nil; try? FileManager.default.removeItem(at: sizeRoot) }
    try owner!.beginSession(SignCollectionJSON.uuid())
    try owner!.decide(scope: "sign_metadata", disclosure: "example-camera-use-1", granted: true, dontAskAgain: false)
    try check(SignCollectionStore.maximumEventBytes == 16_384, "backend 16 KiB event limit")
    let marker = String(repeating: "\u{0001}", count: 160)
    var sized = event
    var evidence = sized["evidence"] as! [String: Any]
    var flags = Array(repeating: marker, count: 32); evidence["quality_flags"] = flags; sized["evidence"] = evidence
    let limit = SignCollectionStore.maximumEventBytes
    var trim = (try SignCollectionJSON.canonical(sized).utf8.count - limit + 5) / 6
    for index in flags.indices {
        let count = min(trim, 159); flags[index] = String(repeating: "\u{0001}", count: 160 - count); trim -= count
    }
    evidence["quality_flags"] = flags; sized["evidence"] = evidence
    let padding = limit - (try SignCollectionJSON.canonical(sized).utf8.count)
    var app = sized["app"] as! [String: Any]
    app["build"] = (app["build"] as! String) + String(repeating: "x", count: padding); sized["app"] = app
    try check(SignCollectionJSON.canonical(sized).utf8.count == limit, "schema-valid event exactly at byte limit")
    try gate.validate(sized, model: "sighting")
    try owner!.enqueue(kind: "sighting", event: sized, disclosure: "example-camera-use-1")
    try Data(SignCollectionJSON.canonical(sized).utf8).write(to: outputRoot.appendingPathComponent("swift-event-at-limit.json"))
    app["build"] = (app["build"] as! String) + "x"; sized["app"] = app; sized["event_id"] = SignCollectionJSON.uuid()
    try gate.validate(sized, model: "sighting")
    try Data(SignCollectionJSON.canonical(sized).utf8).write(to: outputRoot.appendingPathComponent("swift-event-over-limit.json"))
    do {
        try owner!.enqueue(kind: "sighting", event: sized, disclosure: "example-camera-use-1")
        fatalError("event above backend 16 KiB limit accepted")
    } catch SignCollectionError.capacity {} // Prove rejection is the byte limit, not a schema/identity error.
    try check(owner!.pendingCount() == 1, "oversized event does not enter durable queue")
}
try checkEventSizeBoundary()
print("Swift: exact 16 KiB canonical event accepted; 16 KiB + 1 byte rejected atomically")

let transportChecksDone = DispatchSemaphore(value: 0)
var transportChecksResult: Result<Void, Error>?
Task.detached {
    do {
        try await runCollectionTransportChecks(gate: gate, root: outputRoot, fixture: event, live: CommandLine.arguments.contains("--live"))
        if CommandLine.arguments.contains("--resume-live") { try await resumeCollectionHostCleanup(gate: gate, root: outputRoot) }
        transportChecksResult = .success(())
    }
    catch { transportChecksResult = .failure(error) }
    transportChecksDone.signal()
}
transportChecksDone.wait()
try transportChecksResult!.get()

import XCTest
import CoreGraphics
@testable import SpeedConsumer

final class SignCollectionFoundationTests: XCTestCase {
    private func gate() throws -> SignCollectionContractGate {
        try SignCollectionContractGate { path in
            let root = try XCTUnwrap(Bundle.main.url(forResource: "collection-contract-v1", withExtension: nil))
            return try Data(contentsOf: root.appendingPathComponent(path))
        }
    }
    func testPackagedGoldenContractAndIdentityAcrossRestart() throws {
        let gate = try gate(); XCTAssertTrue(gate.verified); XCTAssertTrue(gate.liveTransportAllowed)
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("collection-" + SignCollectionJSON.uuid())
        defer { try? FileManager.default.removeItem(at: root) }
        var store: SignCollectionStore? = try SignCollectionStore(root: root, gate: gate)
        let id = try store!.installationID
        XCTAssertTrue(SignCollectionJSON.isUUID(id)); XCTAssertEqual(try store!.collectionEpoch, 0)
        store = nil; store = try SignCollectionStore(root: root, gate: gate)
        XCTAssertEqual(try store!.installationID, id)
        let session = SignCollectionJSON.uuid()
        try store!.beginSession(session)
        XCTAssertTrue(try store!.shouldPrompt(scope: "sign_metadata", disclosure: "camera-1"))
        try store!.beginSession(session)
        XCTAssertFalse(try store!.shouldPrompt(scope: "sign_metadata", disclosure: "camera-1"))
        try store!.decide(scope: "sign_metadata", disclosure: "camera-1", granted: false, dontAskAgain: true)
        store = nil; store = try SignCollectionStore(root: root, gate: gate)
        try store!.beginSession(SignCollectionJSON.uuid())
        XCTAssertFalse(try store!.shouldPrompt(scope: "sign_metadata", disclosure: "camera-2"))
        let deletion = try store!.requestDeletion()
        XCTAssertEqual(try store!.requestDeletion(), deletion)
        XCTAssertThrowsError(try store!.prepareBatch())
        try store!.applyControlReceipt(id: deletion, response: ["operation_receipt": "receipt", "state": "deletion_pending", "next_collection_epoch": 1, "active_data_removed": false])
        store = nil; store = try SignCollectionStore(root: root, gate: gate)
        XCTAssertEqual(try store!.nextControl()?.receipt, "receipt"); XCTAssertEqual(try store!.collectionEpoch, 0)
        try store!.applyControlReceipt(id: deletion, response: ["operation_receipt": "receipt", "state": "active_data_removed", "next_collection_epoch": 1, "active_data_removed": true])
        XCTAssertEqual(try store!.installationID, id); XCTAssertEqual(try store!.collectionEpoch, 1)
    }
    func testNativeRGBHashAndBottomCrop() throws {
        var pixel: [UInt8] = [0, 0xaa, 0xbb, 255]
        let context = try XCTUnwrap(CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue))
        let crop = try SignCollectionCrop.generate(upright: XCTUnwrap(context.makeImage()), box: ["x": 0, "y": 0, "width": 1, "height": 1])
        XCTAssertEqual(crop.sourceHash, "12cc7f777c6213cec843bd1056ed1e2e1677c8f728e0b1d28d84000f53882d7e")
        XCTAssertEqual(crop.geometry.requested, [0,0,1,2]); XCTAssertEqual(crop.geometry.actual, [0,0,1,1])
    }

    func testCropReviewSurvivesSessionEndAndWithdrawalPurgesEvidence() throws {
        let gate = try gate(), root = FileManager.default.temporaryDirectory.appendingPathComponent("crop-review-" + SignCollectionJSON.uuid())
        var store: SignCollectionStore? = try SignCollectionStore(root: root, gate: gate)
        defer { store = nil; try? FileManager.default.removeItem(at: root) }
        var pixel: [UInt8] = [0,170,187,255]
        let context = try XCTUnwrap(CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue))
        let crop = try SignCollectionCrop.generate(upright: XCTUnwrap(context.makeImage()), box: ["x":0,"y":0,"width":1,"height":1])
        try store!.beginSession(SignCollectionJSON.uuid())
        try store!.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: true, dontAskAgain: false)
        let claim = try store!.decide(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure, granted: true, dontAskAgain: false)
        let id = SignCollectionJSON.uuid(), observation = SignCollectionJSON.uuid()
        let metadata = crop.metadata(cropID: id, observationID: observation, installationID: try store!.installationID, epoch: 0, sourceKind: "detector", frameAt: Date(), localFrameToken: nil, privacyPreflight: "user_reviewed", redactionVersion: "user-review-1", collectionClaim: claim)
        try store!.stageCrop(metadata: metadata, bytes: crop.bytes)
        XCTAssertNil(try store!.nextCrop()); XCTAssertEqual(try store!.cropReviewCount(),1)
        store!.endSession(); store = nil; store = try SignCollectionStore(root: root, gate: gate)
        try store!.reviewCrop(id: id, approved: true)
        XCTAssertEqual(try store!.nextCrop()?.bytes,crop.bytes)
        try store!.applyCropReceipt(id: id, response: ["state":"reserved","handle":"scoped_handle","operation_receipt":"crop-receipt","sha256":crop.encodedHash])
        try store!.applyCropReceipt(id: id, response: ["state":"media_durable","durability":"live_eu_committed","operation_receipt":"crop-receipt","sha256":crop.encodedHash])
        XCTAssertNil(try store!.nextCrop())
        let batch = try XCTUnwrap(store!.prepareBatch()); XCTAssertEqual(batch.kind,"media_status")
        let envelope = try SignCollectionJSON.parse(batch.body) as! [String:Any]
        XCTAssertEqual((envelope["events"] as! [[String:Any]])[0]["status"] as? String,"linked")
        XCTAssertEqual((envelope["events"] as! [[String:Any]])[0]["observation_id"] as? String,observation)
        try store!.withdraw(scope:"crop_storage",disclosure:SignCollectionCapabilities.cropDisclosure)
        XCTAssertEqual(try store!.cropReviewCount(),0)
    }
    func testPanoramaxAllClassEncounterFilterAndMetadataRoundtrip() throws {
        let filter = SignCaptureFilter(), at = Date()
        let detections = [SignCaptureFilter.Detection(key:"white",label:"white",box:[0.1,0.1,0.2,0.2],score:0.8), SignCaptureFilter.Detection(key:"white",label:"white",box:[0.7,0.1,0.2,0.2],score:0.9)]
        XCTAssertTrue(filter.observe(at:at,detections:detections).isEmpty)
        let evidence = filter.observe(at:at.addingTimeInterval(0.1),detections:detections)
        XCTAssertEqual(evidence.count,2); XCTAssertEqual(Set(evidence.map(\.trackID)).count,2)
        filter.captured(evidence,at:at.addingTimeInterval(0.1))
        XCTAssertTrue(filter.observe(at:at.addingTimeInterval(0.2),detections:detections).isEmpty)
        let sample = PanoramaxLocationSample(latitude:49,longitude:8,capturedAt:at,accuracyMeters:5,altitudeMeters:nil,headingDegrees:nil)
        let metadata = PanoramaxCaptureMetadata(captureID:"capture",captureSessionID:"session",capturedAt:at,location:sample,sha256:String(repeating:"a",count:64),byteSize:1,software:"test",captureReason:"recognized_sign",signEvidence:evidence)
        let encoded = try JSONEncoder().encode(metadata), decoded = try JSONDecoder().decode(PanoramaxCaptureMetadata.self,from:encoded)
        XCTAssertEqual(decoded.signEvidence,evidence); XCTAssertEqual(decoded.captureReason,"recognized_sign")
        var legacy = try JSONSerialization.jsonObject(with:encoded) as! [String:Any]; legacy.removeValue(forKey:"captureReason"); legacy.removeValue(forKey:"signEvidence")
        XCTAssertNil(try JSONDecoder().decode(PanoramaxCaptureMetadata.self,from:JSONSerialization.data(withJSONObject:legacy)).captureReason)
    }

    func testPrivacyReceiptsResumeThroughAllPhasesAndLaterEpochs() throws {
        let gate = try gate()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("collection-privacy-" + SignCollectionJSON.uuid())
        var store: SignCollectionStore? = try SignCollectionStore(root: root, gate: gate)
        defer { store = nil; try? FileManager.default.removeItem(at: root) }
        try store!.withdraw(scope: "processor:test", disclosure: "processor-1")
        let withdrawal = try XCTUnwrap(store!.nextControl()).id
        let stopping: [String: Any] = ["operation_receipt": "withdrawal", "state": "processing_stop_pending"]
        try store!.applyControlReceipt(id: withdrawal, response: stopping)
        store = nil; store = try SignCollectionStore(root: root, gate: gate)
        XCTAssertEqual(try store!.nextControl()?.receipt, "withdrawal")
        XCTAssertThrowsError(try store!.applyControlReceipt(id: withdrawal, response: ["operation_receipt": "withdrawal", "state": "processing_stopped"]))
        func deletionReceipt(_ next: Int, _ token: String, archives: Bool = false, backups: Bool = false) -> [String: Any] {
            ["operation_receipt": token, "state": "active_data_removed", "next_collection_epoch": next,
             "active_data_removed": true, "archives_purged": archives, "backup_expiry_complete": backups]
        }
        let first = try store!.requestDeletion()
        try store!.applyControlReceipt(id: first, response: deletionReceipt(1, "first"))
        store = nil; store = try SignCollectionStore(root: root, gate: gate)
        XCTAssertEqual(try store!.collectionEpoch, 1)
        XCTAssertFalse(try XCTUnwrap(store!.controlStatus(id: first)).isComplete)
        XCTAssertTrue(try store!.pendingControls().contains { $0.id == first })
        try store!.applyControlReceipt(id: first, response: deletionReceipt(1, "first", archives: true))
        XCTAssertFalse(try XCTUnwrap(store!.controlStatus(id: first)).isComplete)
        let second = try store!.requestDeletion()
        try store!.applyControlReceipt(id: first, response: deletionReceipt(1, "first", archives: true, backups: true))
        XCTAssertEqual(try store!.nextControl()?.id, second)
        XCTAssertEqual(try store!.collectionEpoch, 1)
        XCTAssertThrowsError(try store!.prepareBatch())
        try store!.applyControlReceipt(id: second, response: deletionReceipt(2, "second", archives: true, backups: true))
        try store!.applyControlReceipt(id: second, response: deletionReceipt(2, "second", archives: true, backups: true))
        XCTAssertEqual(try store!.collectionEpoch, 2)
        try store!.applyControlReceipt(id: withdrawal, response: ["operation_receipt": "withdrawal", "state": "processing_stop_applied"])
        XCTAssertThrowsError(try store!.applyControlReceipt(id: withdrawal, response: stopping))
        store = nil; store = try SignCollectionStore(root: root, gate: gate)
        XCTAssertTrue(try XCTUnwrap(store!.controlStatus(id: first)).isComplete)
        XCTAssertTrue(try XCTUnwrap(store!.controlStatus(id: withdrawal)).isComplete)
        XCTAssertNil(try store!.nextControl())
    }
}

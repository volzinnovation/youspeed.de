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
    func testRepeatCropsKeepExactFramesAndOneDurableSighting() throws {
        let gate = try gate()
        let contractRoot = try XCTUnwrap(Bundle.main.url(forResource: "collection-contract-v1", withExtension: nil))
        let batch = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/sighting-batch-v1.json"), encoding: .utf8)) as! [String: Any]
        let fixture = (batch["events"] as! [[String: Any]])[0]
        let start = Date()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("repeat-crops-" + SignCollectionJSON.uuid())
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try SignCollectionStore(root: root, gate: gate, now: { start })
        try store.beginSession(SignCollectionJSON.uuid())
        _ = try store.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: true, dontAskAgain: false)
        try store.authorizeAutomaticCrops()
        let context = try XCTUnwrap(CGContext(data: nil, width: 100, height: 100, bitsPerComponent: 8, bytesPerRow: 400,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue))
        context.setFillColor(CGColor(gray: 0.5, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 100, height: 100))
        let image = try XCTUnwrap(context.makeImage()), observer = SignCollectionObserver()
        var manifests = [[String: Any]](), failure: Error?
        for (ms, size) in [(0, 0.2), (100, 0.2), (599, 0.2), (600, 0.3)] {
            let detection = SignCollectionObserver.Detection(key: "sign", box: [0.1, 0.1, size, size], payload: fixture, presentationTrack: nil)
            try observer.observe(at: start.addingTimeInterval(Double(ms) / 1000), detections: [detection], captureCrop: { candidate in
                do {
                    let crop = try SignCollectionCrop.generate(upright: image,
                        box: Dictionary(uniqueKeysWithValues: zip(["x", "y", "width", "height"], candidate.box)), hashSource: false)
                    var position = fixture["vehicle_position"] as! [String: Any]
                    position["latitude"] = 47.0 + Double(ms) / 1_000_000
                    position["course_degrees"] = Double(ms) / 10
                    position["fix_at"] = SignCollectionJSON.utc(candidate.frameAt)
                    position["frame_fix_delta_ms"] = 0
                    let manifest = crop.metadata(cropID: SignCollectionJSON.uuid(), observationID: candidate.observationID, installationID: try store.installationID,
                        epoch: try store.collectionEpoch, sourceKind: "detector", frameAt: candidate.frameAt, localFrameToken: "frame-\(ms)",
                        privacyPreflight: "passed", redactionVersion: "metadata-strip-1", collectionClaim: try store.claim(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure),
                        vehiclePosition: position, phoneRoadMatch: SignCollectionPhoneRoadMatch(
                            osmWayID: String(4700 + ms), bundleVersion: "bundle-\(ms)", bundleDBSHA256: String(repeating: ms == 100 ? "a" : "b", count: 64),
                            matchedFixAt: candidate.frameAt.addingTimeInterval(-0.1), travelDirection: "forward", matchedWayStable: true))
                    try gate.validate(manifest, model: "crop")
                    try store.enqueueAutomaticCrop(metadata: manifest, bytes: crop.bytes)
                    manifests.append(manifest); return .stored
                } catch { failure = error; return .failed }
            }) { try store.enqueue(kind: "sighting", event: $0, disclosure: SignCollectionCapabilities.metadataDisclosure) }
        }
        if let failure { throw failure }
        let fraction = Date(timeIntervalSince1970: 1_791_532_800.0015)
        let fractionalCrop = try SignCollectionCrop.generate(upright: image, box: ["x":0,"y":0,"width":1,"height":1])
        let fractionalMetadata = fractionalCrop.metadata(cropID: SignCollectionJSON.uuid(), observationID: SignCollectionJSON.uuid(),
            installationID: try store.installationID, epoch: try store.collectionEpoch, sourceKind: "detector", frameAt: fraction,
            localFrameToken: "fractional", privacyPreflight: "passed", redactionVersion: "metadata-strip-1",
            collectionClaim: try store.claim(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure),
            phoneRoadMatch: SignCollectionPhoneRoadMatch(osmWayID: "123", bundleVersion: "fixture", bundleDBSHA256: String(repeating: "a", count: 64),
                matchedFixAt: Date(timeIntervalSince1970: 1_791_532_799.5), travelDirection: "forward", matchedWayStable: true))
        try gate.validate(fractionalMetadata, model: "crop")
        XCTAssertEqual(try store.pendingCount(), 1); XCTAssertEqual(manifests.count, 2)
        XCTAssertEqual(manifests[0]["observation_id"] as? String, manifests[1]["observation_id"] as? String)
        XCTAssertNotEqual(manifests[0]["crop_id"] as? String, manifests[1]["crop_id"] as? String)
        XCTAssertEqual(manifests[1]["source_frame_at"] as? String, SignCollectionJSON.utc(start.addingTimeInterval(0.6)))
        XCTAssertEqual(manifests[1]["local_frame_token"] as? String, "frame-600")
        XCTAssertEqual(manifests[1]["original_box"] as? [Int], [10, 10, 40, 40])
        XCTAssertEqual((manifests[0]["vehicle_position"] as? [String: Any])?["course_degrees"] as? Double, 10)
        XCTAssertEqual((manifests[1]["vehicle_position"] as? [String: Any])?["course_degrees"] as? Double, 60)
        XCTAssertEqual((manifests[1]["vehicle_position"] as? [String: Any])?["fix_at"] as? String, manifests[1]["source_frame_at"] as? String)
        XCTAssertEqual((manifests[0]["phone_road_match"] as? [String: Any])?["osm_way_id"] as? String, "4800")
        XCTAssertEqual((manifests[1]["phone_road_match"] as? [String: Any])?["osm_way_id"] as? String, "5300")
        var queued = [[String: Any]]()
        for _ in 0..<2 {
            let crop = try XCTUnwrap(store.nextCrop())
            queued.append(try SignCollectionJSON.parse(crop.metadata) as! [String: Any])
            try store.finishBestEffortCrop(id: crop.id)
        }
        XCTAssertEqual(Set(queued.map { $0["crop_id"] as! String }), Set(manifests.map { $0["crop_id"] as! String }))
        for saved in queued {
            let original = try XCTUnwrap(manifests.first { $0["crop_id"] as? String == saved["crop_id"] as? String })
            XCTAssertEqual(try SignCollectionJSON.canonical(saved["vehicle_position"]!), try SignCollectionJSON.canonical(original["vehicle_position"]!))
        }
        XCTAssertNil(try store.nextCrop())
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
        try store!.migrateAutomaticCrops()
        XCTAssertEqual(try store!.nextCrop()?.bytes,crop.bytes)
        try store!.finishBestEffortCrop(id: id)
        XCTAssertNil(try store!.nextCrop())
        XCTAssertNil(try store!.prepareBatch()) // The backend creates the media link internally.
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

import XCTest
import UIKit
import ImageIO
@testable import SpeedConsumer

private actor MapillaryTestTransport: MapillaryHTTPTransport {
    private var replies: [(Int, String)]
    private(set) var requests: [URLRequest] = []
    init(_ replies: [(Int, String)]) { self.replies = replies }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        requests.append(request)
        guard !replies.isEmpty else { throw MapillaryUploadError.response }
        let (code, body) = replies.removeFirst()
        return (Data(body.utf8), HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!)
    }
}

final class MapillaryUploadTests: XCTestCase {
    func testResumableOffsetAndOAuthHeaders() async throws {
        let transport = MapillaryTestTransport([(200, "{\"offset\":3}"), (200, "{\"h\":\"image-handle\"}")])
        let result = try await MapillaryUploadClient(transport: transport).upload(Data("abcdef".utf8),
            sessionKey: "photo.jpg", token: "user-token")
        XCTAssertEqual(result, "image-handle")
        let requests = await transport.requests
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests[1].httpBody, Data("def".utf8))
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "Offset"), "3")
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "Authorization"), "OAuth user-token")
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "X-Entity-Name"), "photo.jpg")
    }

    func testInvalidOffsetsCannotSendPhotoBytes() async throws {
        for offset in ["-1", "4", "true", "1.5", "\"0\""] {
            let transport = MapillaryTestTransport([(200, "{\"offset\":\(offset)}")])
            do {
                _ = try await MapillaryUploadClient(transport: transport).upload(Data([1, 2, 3]), sessionKey: "photo.jpg", token: "user-token")
                XCTFail("Accepted invalid offset \(offset)")
            } catch { }
            let requests = await transport.requests
            XCTAssertEqual(requests.count, 1)
        }
    }

    func testAuthenticationFailureAndCaptureGateStopBeforeTransfer() async throws {
        let unauthorized = MapillaryTestTransport([(401, "{}")])
        do {
            _ = try await MapillaryUploadClient(transport: unauthorized).upload(Data([1]), sessionKey: "photo.jpg", token: "user-token")
            XCTFail("Unauthorized upload succeeded")
        } catch MapillaryUploadError.http(401) { }
        let calls = await unauthorized.requests
        XCTAssertEqual(calls.count, 1)
        let blocked = MapillaryTestTransport([])
        do {
            _ = try await MapillaryUploadClient(transport: blocked).upload(Data([1]), sessionKey: "photo.jpg", token: "user-token", allowed: { false })
            XCTFail("Upload bypassed capture gate")
        } catch MapillaryUploadError.paused { }
        let blockedCalls = await blocked.requests
        XCTAssertTrue(blockedCalls.isEmpty)
    }

    func testFinishUsesImageBundleManifestAndReturnsProcessingCluster() async throws {
        let transport = MapillaryTestTransport([(200, "{\"cluster_id\":123}")])
        let cluster = try await MapillaryUploadClient(transport: transport).finish(handle: "manifest-handle", token: "user-token")
        XCTAssertEqual(cluster, "123")
        let requests = await transport.requests
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: requests[0].httpBody!) as? [String: String])
        XCTAssertEqual(body, ["file_handle": "manifest-handle", "file_type": "mly_bundle_manifest"])
        XCTAssertEqual(requests[0].url?.absoluteString, "https://graph.mapillary.com/finish_upload")
    }

    func testProfileUsesEachUsersToken() async throws {
        let transport = MapillaryTestTransport([(200, "{\"id\":\"alice\",\"username\":\"Alice\"}")])
        let profile = try await MapillaryUploadClient(transport: transport).profile(token: "alice-token")
        XCTAssertEqual(profile.id, "alice")
        let requests = await transport.requests
        XCTAssertEqual(requests[0].value(forHTTPHeaderField: "Authorization"), "OAuth alice-token")
    }

    func testPreparedJPEGHasMapillaryMetadataAndPreservesOriginal() async throws {
        let root = temporaryDirectory(); defer { try? FileManager.default.removeItem(at: root) }
        let photo = try photo(in: root)
        let original = try Data(contentsOf: photo.url)
        let data = try MapillaryImageMetadata.prepared(photo)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any])
        let tiff = try XCTUnwrap(properties[kCGImagePropertyTIFFDictionary as String] as? [String: Any])
        let raw = try XCTUnwrap(tiff[kCGImagePropertyTIFFImageDescription as String] as? String)
        let metadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any])
        XCTAssertEqual(metadata["MAPCaptureTime"] as? String, "2026_11_17_06_30_00_123")
        XCTAssertEqual(metadata["MAPLatitude"] as? Double, 48.8)
        XCTAssertEqual(metadata["MAPLongitude"] as? Double, 8.4)
        XCTAssertEqual(metadata["MAPSequenceUUID"] as? String, MapillaryUploadStore.hash(Data("drive-a".utf8)))
        XCTAssertEqual(try Data(contentsOf: photo.url), original)
    }

    func testResumeAfterFinishFailureKeepsHandlesAndNeverResendsImages() async throws {
        let root = temporaryDirectory(); defer { try? FileManager.default.removeItem(at: root) }
        let store = MapillaryUploadStore(root: root.appendingPathComponent("queue"))
        let photo = try photo(in: root)
        let job = try await store.prepare(photos: [photo], userID: "alice")
        let transport = MapillaryTestTransport([(200, "{\"offset\":0}"), (200, "{\"h\":\"photo-handle\"}"),
            (200, "{\"offset\":0}"), (200, "{\"h\":\"manifest-handle\"}"), (503, "{}")])
        do {
            try await MapillaryUploadWorker(client: .init(transport: transport), store: store).submit(job, userID: "alice", token: "alice-token")
            XCTFail("Expected interrupted finish")
        } catch MapillaryUploadError.http(503) { }
        let reopened = MapillaryUploadStore(root: root.appendingPathComponent("queue"))
        let pending = await reopened.pending(userID: "alice")
        XCTAssertEqual(pending.count, 1)
        XCTAssertEqual(pending[0].images[0].handle, "photo-handle")
        XCTAssertEqual(pending[0].manifestHandle, "manifest-handle")
        let otherAccount = await reopened.pending(userID: "bob")
        XCTAssertTrue(otherAccount.isEmpty)
        let retry = MapillaryTestTransport([(200, "{\"cluster_id\":\"cluster\"}")])
        try await MapillaryUploadWorker(client: .init(transport: retry), store: reopened).submit(pending[0], userID: "alice", token: "alice-token")
        let retryCalls = await retry.requests
        XCTAssertEqual(retryCalls.count, 1)
        XCTAssertEqual(retryCalls[0].url?.path, "/finish_upload")
        let after = await reopened.pending(userID: "alice")
        XCTAssertTrue(after.isEmpty)
        XCTAssertTrue(FileManager.default.fileExists(atPath: photo.url.path))
    }

    func testWrongAccountCannotResumeAnotherUsersJob() async throws {
        let root = temporaryDirectory(); defer { try? FileManager.default.removeItem(at: root) }
        let store = MapillaryUploadStore(root: root.appendingPathComponent("queue"))
        let job = try await store.prepare(photos: [try photo(in: root)], userID: "alice")
        let transport = MapillaryTestTransport([])
        do {
            try await MapillaryUploadWorker(client: .init(transport: transport), store: store).submit(job, userID: "bob", token: "bob-token")
            XCTFail("Account mismatch accepted")
        } catch MapillaryUploadError.account { }
        let requests = await transport.requests
        XCTAssertTrue(requests.isEmpty)
    }

    func testOverlappingSelectionSkipsPreviouslySubmittedPhotos() async throws {
        let root = temporaryDirectory(); defer { try? FileManager.default.removeItem(at: root) }
        let store = MapillaryUploadStore(root: root.appendingPathComponent("queue"))
        let first = try photo(in: root)
        var completed = try await store.prepare(photos: [first], userID: "alice")
        completed.clusterID = "cluster-a"; try await store.save(completed)
        let second = MapillaryPhoto(itemID: "item-b", url: first.url, metadata: first.metadata)
        let next = try await store.prepare(photos: [first, second], userID: "alice")
        XCTAssertEqual(next.images.map(\.itemID), ["item-b"])
        let uploaded = await store.uploadedItemIDs(userID: "alice")
        XCTAssertEqual(uploaded, ["item-a"])
        let otherUser = await store.uploadedItemIDs(userID: "bob")
        XCTAssertTrue(otherUser.isEmpty)
    }

    func testChangedOriginalCannotBePreparedForUpload() throws {
        let root = temporaryDirectory(); defer { try? FileManager.default.removeItem(at: root) }
        let photo = try photo(in: root)
        try Data([1, 2, 3]).write(to: photo.url)
        XCTAssertThrowsError(try MapillaryImageMetadata.prepared(photo))
    }

    func testMalformedSubmissionCannotBeRecordedAsSuccess() async throws {
        for value in ["true", "{}", "[]", "null", "1.5", "\"\""] {
            let transport = MapillaryTestTransport([(200, "{\"cluster_id\":\(value)}")])
            do {
                _ = try await MapillaryUploadClient(transport: transport).finish(handle: "manifest", token: "user-token")
                XCTFail("Accepted invalid submission receipt")
            } catch MapillaryUploadError.response { }
        }
    }

    func testChangedStagingCopyStopsBeforeAnyTransfer() async throws {
        let root = temporaryDirectory(); defer { try? FileManager.default.removeItem(at: root) }
        let queue = root.appendingPathComponent("queue")
        let store = MapillaryUploadStore(root: queue)
        let photo = try photo(in: root)
        let original = try Data(contentsOf: photo.url)
        let job = try await store.prepare(photos: [photo], userID: "alice")
        try Data([1, 2, 3]).write(to: queue.appendingPathComponent(job.id).appendingPathComponent(job.images[0].name))
        let transport = MapillaryTestTransport([])
        do {
            try await MapillaryUploadWorker(client: .init(transport: transport), store: store).submit(job, userID: "alice", token: "user-token")
            XCTFail("Corrupt staging copy was transferred")
        } catch MapillaryUploadError.image { }
        let requests = await transport.requests
        XCTAssertTrue(requests.isEmpty)
        XCTAssertEqual(try Data(contentsOf: photo.url), original)
    }

    private func temporaryDirectory() -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }
    private func photo(in root: URL) throws -> MapillaryPhoto {
        let bytes = try XCTUnwrap(UIGraphicsImageRenderer(size: CGSize(width: 16, height: 12)).image { context in
            UIColor.red.setFill();context.fill(CGRect(x: 0, y: 0, width: 16, height: 12))
        }.jpegData(compressionQuality: 0.9))
        let url = root.appendingPathComponent("original.jpg"); try bytes.write(to: url)
        let time = Date(timeIntervalSince1970: 1794897000.123)
        let location = PanoramaxLocationSample(latitude: 48.8, longitude: 8.4, capturedAt: time,
            accuracyMeters: 3, altitudeMeters: 250, headingDegrees: 15)
        return MapillaryPhoto(itemID: "item-a", url: url, metadata: .init(captureID: "capture-a", captureSessionID: "drive-a",
            capturedAt: time, location: location, sha256: MapillaryUploadStore.hash(bytes), byteSize: Int64(bytes.count), software: "YouSpeed test"))
    }
}

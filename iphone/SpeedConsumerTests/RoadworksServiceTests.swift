import XCTest
import CryptoKit
import CoreLocation
@testable import SpeedConsumer

@MainActor final class RoadworksServiceTests: XCTestCase {
    private func cachedPair(at root: URL) throws {
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let bytes = try Data(contentsOf: repository.appendingPathComponent("shared/roadworks/snapshot-v1.json"))
        let id = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let now = ISO8601DateFormatter().string(from: Date())
        let manifest: [String: Any] = ["schema_version": 1, "region": "DE-BW", "feature_enabled": true, "snapshot_id": id, "snapshot_bytes": bytes.count, "snapshot_path": "/youspeed/live/v1/regions/DE-BW/snapshots/" + id, "freshness": ["status": "fresh", "server_time": now, "source_publication_at": now, "source_modified_at": now, "last_checked_at": now], "coverage": ["region": "DE-BW", "complete_road_coverage": false, "autobahn_included": false], "attributions": [["provider": "fixture"]]]
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try bytes.write(to: root.appendingPathComponent(id + ".json"))
        try JSONSerialization.data(withJSONObject: manifest).write(to: root.appendingPathComponent("previous-manifest.json"))
        try Data("broken-current".utf8).write(to: root.appendingPathComponent("manifest.json"))
    }
    func testProductionCacheRestoresPreviousAndCompatibilityErrorSurvivesEvaluation() async throws {
        let name = "roadworks-previous-\(UUID())", root = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name)); defaults.set(true, forKey: "youspeed.roadworks.enabled")
        defer { defaults.removePersistentDomain(forName: name); try? FileManager.default.removeItem(at: root) }
        try cachedPair(at: root)
        let service = RoadworksService(directory: root, defaults: defaults) { url, _, _ in
            (Data("{\"schema_version\":2}".utf8), HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        }
        service.update(location: CLLocation(coordinate: .init(latitude: 48, longitude: 8), altitude: 0, horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: Date()))
        XCTAssertFalse(service.nearby.isEmpty)
        XCTAssertEqual(service.status, "unknown")
        service.refresh(explicit: true)
        for _ in 0..<100 { if service.status != "loading" { break }; await Task.yield() }
        XCTAssertEqual(service.status, "update_required")
        service.session(driving: false, foreground: true)
        XCTAssertEqual(service.status, "update_required")
        service.setEnabled(false)
    }
    func testClearEpochRejectsEarlierDiskPromotion() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("roadworks-disk-\(UUID())")
        defer { try? FileManager.default.removeItem(at: root) }
        let disk = RoadworksDiskStore(directory: root)
        let manifest = RoadworksAdvisory.Manifest(enabled: false, snapshotID: nil, snapshotBytes: nil, snapshotPath: nil, serverTime: Date(), sourcePublication: nil, sourceModified: nil, lastChecked: nil, advertisedStatus: .unavailable)
        await disk.clear(epoch: 1)
        let stale = try await disk.promote(epoch: 0, bytes: nil, candidate: manifest, manifestBytes: Data("{}".utf8), previousID: nil)
        XCTAssertFalse(stale)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
        let fresh = try await disk.promote(epoch: 2, bytes: nil, candidate: manifest, manifestBytes: Data("{}".utf8), previousID: nil)
        XCTAssertTrue(fresh)
        await disk.clear(epoch: 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("manifest.json").path))
        await disk.clear(epoch: 3)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }
    actor Calls {
        var count = 0
        func increment() { count += 1 }
    }
    func testOffByDefaultSingleRequestAndDisableCancelsWithoutLatePublication() async throws {
        let name = "roadworks-test-\(UUID())", calls = Calls()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let service = RoadworksService(directory: FileManager.default.temporaryDirectory.appendingPathComponent(name), defaults: defaults) { _, _, _ in
            await calls.increment()
            try await Task.sleep(nanoseconds: 10_000_000_000)
            throw URLError(.timedOut)
        }
        XCTAssertFalse(service.enabled)
        service.session(driving: true, foreground: true)
        service.refresh(explicit: true)
        await Task.yield()
        let before = await calls.count
        XCTAssertEqual(before, 0)
        service.setEnabled(true)
        service.refresh(explicit: true)
        for _ in 0..<20 { if await calls.count == 1 { break }; await Task.yield() }
        let during = await calls.count
        XCTAssertEqual(during, 1)
        service.setEnabled(false)
        for _ in 0..<5 { await Task.yield() }
        XCTAssertEqual(service.status, "off")
        XCTAssertNil(service.card)
        XCTAssertTrue(service.nearby.isEmpty)
    }
}

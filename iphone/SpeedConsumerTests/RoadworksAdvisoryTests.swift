import XCTest
import CryptoKit
@testable import SpeedConsumer

final class RoadworksAdvisoryTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_792_749_600) // 2026-10-23 10:00 UTC
    private func bytes() throws -> Data {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent("shared/roadworks/snapshot-v1.json"))
    }
    private func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private func snapshot() throws -> RoadworksAdvisory.Snapshot { let data=try bytes(); return try RoadworksAdvisory.parseSnapshot(data, expectedID:hash(data)) }
    private func manifest() throws -> RoadworksAdvisory.Manifest {
        let data=try bytes()
        return .init(enabled:true,snapshotID:hash(data),snapshotBytes:data.count,snapshotPath:nil,serverTime:now,
            sourcePublication:now.addingTimeInterval(-1200),sourceModified:now.addingTimeInterval(-600),lastChecked:now.addingTimeInterval(-30),advertisedStatus:.fresh)
    }
    private func fix(_ seconds: Double = 0, latitude: Double = 48) -> RoadworksRelevance.Fix {
        .init(point:.init(latitude:latitude,longitude:8),at:now.addingTimeInterval(seconds),accuracyM:5)
    }
    func testSharedSnapshotRetainsAttributionAndFindsMiddleOfLongLine() throws {
        let value=try snapshot()
        XCTAssertEqual(value.features.count,3)
        XCTAssertEqual(value.attributions.first?["license_id"],"dl-de/by-2-0")
        XCTAssertEqual(RoadworksAdvisory.distance(from:.init(latitude:48,longitude:8),to:try XCTUnwrap(value.features.first{$0.kind=="roadworks"})),0,accuracy:0.000001)
        XCTAssertEqual(value.features.first{$0.points.count==1}?.direction,"unknown")
    }
    func testFreshnessAgesOfflineAndSuccessfulCheckCannotFreshenPublisher() throws {
        let value=try manifest()
        XCTAssertEqual(value.freshness(receivedUptime:100,nowUptime:100),.fresh)
        XCTAssertEqual(value.freshness(receivedUptime:100,nowUptime:701),.delayed)
        XCTAssertEqual(value.freshness(receivedUptime:100,nowUptime:86501),.unavailable)
        XCTAssertEqual(value.freshness(receivedUptime:100,nowUptime:99),.unknown)
        XCTAssertEqual(try value.validatedHTTPClock(date:now,age:7200).freshness(receivedUptime:0,nowUptime:0),.delayed)
        XCTAssertThrowsError(try value.validatedHTTPClock(date:now.addingTimeInterval(-301),age:0))
    }
    func testCacheRejectsChecksumUnknownVersionAndSwappedPointWithoutReplacingGeneration() throws {
        let cache=RoadworksSnapshotCache(), data=try bytes(), manifest=try manifest()
        try cache.install(data,manifest:manifest)
        let original=cache.snapshot?.id
        XCTAssertThrowsError(try cache.install(data+Data([10]),manifest:manifest))
        let source=try XCTUnwrap(String(data:data,encoding:.utf8))
        for changed in [source.replacingOccurrences(of:"\"schema_version\": 1",with:"\"schema_version\": 2"),
                        source.replacingOccurrences(of:"8.0,\n          48.001",with:"48.001,\n          8.0")] {
            XCTAssertNotEqual(source,changed)
            let bad=Data(changed.utf8)
            XCTAssertThrowsError(try RoadworksAdvisory.parseSnapshot(bad,expectedID:hash(bad)))
            XCTAssertEqual(cache.snapshot?.id,original)
        }
    }
    func testCardRequiresTwoDistinctFixesAndExpiresWithoutAnotherLocation() throws {
        var runtime=RoadworksRelevance(); let value=try snapshot()
        func update(_ fix:RoadworksRelevance.Fix,now:Date?=nil,enabled:Bool=true) -> RoadworksRelevance.Card? {
            runtime.update(snapshot:value,freshness:.fresh,fix:fix,now:now ?? fix.at,enabled:enabled,driving:true,foreground:true)
        }
        XCTAssertNil(update(fix()))
        XCTAssertNil(update(fix()))
        XCTAssertEqual(update(fix(1))?.feature.kind,"closure")
        XCTAssertNil(update(fix(1),now:now.addingTimeInterval(5)))
        XCTAssertNil(update(fix(6)))
        XCTAssertNotNil(update(fix(7)))
        XCTAssertNil(update(fix(8),enabled:false))
        XCTAssertNil(update(fix(9)))
    }
    func testScheduleUsesHalfOpenCompiledIntervals() throws {
        let value=try XCTUnwrap(snapshot().features.first)
        XCTAssertFalse(value.eligible(at:now.addingTimeInterval(-0.001)))
        XCTAssertTrue(value.eligible(at:now))
        XCTAssertFalse(value.eligible(at:now.addingTimeInterval(7200)))
    }
    func testDiskCacheRestoresCurrentAndRecoversPreviousAfterCorruption() throws {
        let directory=FileManager.default.temporaryDirectory.appendingPathComponent("roadworks-cache-"+UUID().uuidString)
        defer { try? FileManager.default.removeItem(at:directory) }
        let cache=RoadworksSnapshotCache(directory:directory),data=try bytes(),original=try manifest()
        try cache.install(data,manifest:original)
        let next=Data(try XCTUnwrap(String(data:data,encoding:.utf8)).replacingOccurrences(of:"Synthetic reported worksite",with:"Next synthetic reported worksite").utf8)
        let nextID=hash(next)
        let nextManifest=RoadworksAdvisory.Manifest(enabled:true,snapshotID:nextID,snapshotBytes:next.count,snapshotPath:nil,
            serverTime:now,sourcePublication:now,sourceModified:now,lastChecked:now,advertisedStatus:.fresh)
        try cache.install(next,manifest:nextManifest)
        XCTAssertEqual(RoadworksSnapshotCache(directory:directory).snapshot?.id,nextID)
        XCTAssertEqual(RoadworksSnapshotCache(directory:directory).previousSnapshot?.id,original.snapshotID)
        try Data("truncated".utf8).write(to:directory.appendingPathComponent("snapshot-"+nextID+".json"))
        let recovered=RoadworksSnapshotCache(directory:directory)
        XCTAssertEqual(recovered.snapshot?.id,original.snapshotID)
        XCTAssertEqual(recovered.restoreError,"current_snapshot_invalid_using_previous")
    }
}

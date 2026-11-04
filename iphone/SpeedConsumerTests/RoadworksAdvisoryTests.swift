import XCTest
import CryptoKit
@testable import SpeedConsumer

final class RoadworksAdvisoryTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_792_749_600) // 2026-10-23 10:00 UTC
    private func bytes() throws -> Data {
        try RoadworksTestFixtures.data("snapshot-v1.json")
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
        for changed in [source.replacingOccurrences(of:"\"schema_version\": 1",with:"\"schema_version\": 3"),
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

    private func fixture(_ name: String) throws -> Data {
        try RoadworksTestFixtures.data(name)
    }
    private func v2Manifest() throws -> RoadworksAdvisory.Manifest {
        try RoadworksAdvisory.parseManifest(fixture("manifest-v2.json"))
    }
    private func v2Snapshot() throws -> RoadworksAdvisory.Snapshot {
        let data = try fixture("snapshot-v2.json")
        return try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data))
    }
    private func changed(_ data: Data, _ mutation: (inout [String: Any]) -> Void) throws -> Data {
        var root = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        mutation(&root)
        return try JSONSerialization.data(withJSONObject: root, options: .sortedKeys)
    }
    func testV1SourceMeaningAndV2ProvenanceRemainDistinct() throws {
        let old = try snapshot(), value = try v2Snapshot(), manifest = try v2Manifest()
        XCTAssertEqual(old.schemaVersion, 1)
        XCTAssertEqual(old.sourceIDs, ["bemas"])
        XCTAssertTrue(old.features.allSatisfy { $0.advisorySource == "bemas" })
        XCTAssertEqual(value.schemaVersion, 2)
        XCTAssertEqual(value.features.count, 6)
        XCTAssertEqual(value.sourceIDs, manifest.sourceIDs)
        XCTAssertTrue(value.features.allSatisfy { $0.sourceID != nil && $0.sourceVersionTime != nil })
        XCTAssertEqual(Set(value.features.map(\.kind)), ["roadworks", "closure", "incident", "hazard", "congestion"])
        let cache = RoadworksSnapshotCache()
        try cache.install(fixture("snapshot-v2.json"), manifest: manifest)
        var mismatched = manifest
        mismatched.sources.removeAll { $0.id == "autobahn-long-term" }
        XCTAssertThrowsError(try cache.install(fixture("snapshot-v2.json"), manifest: mismatched))
        XCTAssertEqual(cache.snapshot?.id, value.id)
    }
    func testV2RejectsSourceListCoverageAttributionAndFeatureIdentityConflicts() throws {
        let data = try fixture("manifest-v2.json")
        let invalid = [
            try changed(data) { root in var rows = root["sources"] as! [[String: Any]]; rows.append(rows[0]); root["sources"] = rows },
            try changed(data) { root in var coverage = root["coverage"] as! [String: Any]; coverage["source_ids"] = ["bemas"]; root["coverage"] = coverage },
            try changed(data) { root in var coverage = root["coverage"] as! [String: Any]; coverage["autobahn_included"] = false; root["coverage"] = coverage },
            try changed(data) { root in var rows = root["sources"] as! [[String: Any]]; var credit = rows[0]["attribution"] as! [String: String]; credit["license_id"] = " "; rows[0]["attribution"] = credit; root["sources"] = rows },
            try changed(data) { root in var clocks = root["freshness"] as! [String: Any]; clocks["status"] = "unavailable"; root["freshness"] = clocks }
        ]
        for bytes in invalid { XCTAssertThrowsError(try RoadworksAdvisory.parseManifest(bytes)) }
        let snapshotData = try fixture("snapshot-v2.json")
        for bytes in [
            try changed(snapshotData) { $0["source_ids"] = ["bemas", "unknown-provider"] },
            try changed(snapshotData) { root in var rows = root["features"] as! [[String: Any]]; rows[0]["id"] = "mobidata-bw:incidents-bw:wrong-source"; root["features"] = rows },
            try changed(snapshotData) { root in var rows = root["features"] as! [[String: Any]]; var properties = rows[0]["properties"] as! [String: Any]; properties["source_version_time"] = "2026-10-28T10:00:00"; rows[0]["properties"] = properties; root["features"] = rows }
        ] { XCTAssertThrowsError(try RoadworksAdvisory.parseSnapshot(bytes, expectedID: hash(bytes))) }
    }
    func testV2KeepsNullableRecordVersionAndUnknownScheduleWithoutGrantingEligibility() throws {
        let data = try changed(fixture("snapshot-v2.json")) { root in
            var rows = root["features"] as! [[String: Any]]
            var properties = rows[0]["properties"] as! [String: Any]
            properties["source_version_time"] = NSNull()
            properties["schedule_status"] = "unknown"
            properties["active_intervals"] = []
            rows[0]["properties"] = properties
            root["features"] = rows
        }
        let snapshot = try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data))
        let feature = try XCTUnwrap(snapshot.features.first)
        XCTAssertNil(feature.sourceVersionTime)
        XCTAssertNotNil(feature.sourceID)
        XCTAssertFalse(feature.eligible(at: try v2Manifest().serverTime))
    }
    func testV2AggregateFreshnessAloneNeverActivatesAFeature() throws {
        let snapshot = try v2Snapshot(), now = try v2Manifest().serverTime
        for statuses: [String: RoadworksAdvisory.Freshness]? in [nil, [:]] {
            var runtime = RoadworksRelevance()
            for seconds in [0.0, 1.0] {
                let at = now.addingTimeInterval(seconds)
                XCTAssertNil(runtime.update(snapshot: snapshot, freshness: .fresh,
                    fix: .init(point: .init(latitude: 48, longitude: 8), at: at, accuracyM: 5), now: at,
                    enabled: true, driving: true, foreground: true, sourceFreshness: statuses, eligibilityNow: at))
            }
        }
    }
    private func activeIncidentBytes(start: Any = NSNull(), end: Any = NSNull(),
                                     change: (inout [String: Any]) -> Void = { _ in }) throws -> Data {
        let publication = try XCTUnwrap(v2Manifest().sources.first { $0.id == "incidents-bw" }?.publication)
        let formatter = ISO8601DateFormatter()
        return try changed(fixture("snapshot-v2.json")) { root in
            let row = (root["features"] as! [[String: Any]]).first { ($0["properties"] as? [String: Any])?["kind"] as? String == "incident" }!
            var properties = row["properties"] as! [String: Any]
            properties["validity_basis"] = "reported_active"; properties["source_validity_status"] = "active"
            properties["source_validity_start"] = start; properties["source_validity_end"] = end
            properties["outer_start"] = formatter.string(from: publication)
            properties["outer_end"] = formatter.string(from: publication.addingTimeInterval(900))
            properties["active_intervals"] = [["start": properties["outer_start"]!, "end": properties["outer_end"]!]]
            properties["schedule_status"] = "resolved"
            change(&properties)
            var active = row; active["properties"] = properties
            root["features"] = [active]
        }
    }
    private func installingManifest(_ bytes: Data, sourceChange: (RoadworksAdvisory.Source) -> RoadworksAdvisory.Source = { $0 }) throws -> RoadworksAdvisory.Manifest {
        let value = try v2Manifest()
        return .init(enabled: value.enabled, snapshotID: hash(bytes), snapshotBytes: bytes.count,
            snapshotPath: "/youspeed/live/v2/regions/DE-BW/snapshots/" + hash(bytes), serverTime: value.serverTime,
            sourcePublication: value.sourcePublication, sourceModified: value.sourceModified, lastChecked: value.lastChecked,
            advertisedStatus: value.advertisedStatus, schemaVersion: 2, sources: value.sources.map(sourceChange))
    }
    func testIncidentValidityBasisPreservesScheduledAndOriginalActiveSpecifications() throws {
        let scheduled = try XCTUnwrap(v2Snapshot().features.first { $0.advisorySource == "incidents-bw" })
        XCTAssertEqual(scheduled.validityBasis, "scheduled")
        XCTAssertEqual(scheduled.sourceValidityStatus, "definedByValidityTimeSpec")
        XCTAssertNotNil(scheduled.sourceValidityStart)
        XCTAssertNotNil(scheduled.sourceValidityEnd)
        XCTAssertTrue(try snapshot().features.allSatisfy { $0.validityBasis == "scheduled" && $0.sourceValidityStatus == nil })
        let publication = try XCTUnwrap(v2Manifest().sources.first { $0.id == "incidents-bw" }?.publication)
        for specification in [("2026-10-20T10:00:00Z", "2026-10-21T10:00:00Z"), ("2026-11-01T10:00:00Z", "2026-11-02T10:00:00Z")] {
            let bytes = try activeIncidentBytes(start: specification.0, end: specification.1)
            let feature = try XCTUnwrap(RoadworksAdvisory.parseSnapshot(bytes, expectedID: hash(bytes)).features.first)
            XCTAssertEqual(feature.sourceValidityStart, ISO8601DateFormatter().date(from: specification.0))
            XCTAssertEqual(feature.sourceValidityEnd, ISO8601DateFormatter().date(from: specification.1))
            XCTAssertFalse(feature.eligible(at: publication.addingTimeInterval(-0.001)))
            XCTAssertTrue(feature.eligible(at: publication))
            XCTAssertTrue(feature.eligible(at: publication.addingTimeInterval(899.999)))
            XCTAssertFalse(feature.eligible(at: publication.addingTimeInterval(900)))
        }
    }
    func testIncidentValidityMetadataMissingMismatchedOrOversizedLeaseFailsClosed() throws {
        for key in ["validity_basis", "source_validity_status", "source_validity_start", "source_validity_end"] {
            let data = try activeIncidentBytes { $0.removeValue(forKey: key) }
            XCTAssertThrowsError(try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data)))
        }
        let invalid = [
            try activeIncidentBytes { $0["validity_basis"] = "unknown" },
            try activeIncidentBytes { $0["source_validity_status"] = "definedByValidityTimeSpec" },
            try activeIncidentBytes { $0["validity_basis"] = "scheduled" },
            try activeIncidentBytes { $0["schedule_status"] = "unknown"; $0["active_intervals"] = [] },
            try activeIncidentBytes { properties in
                let formatter = ISO8601DateFormatter()
                let end = formatter.string(from: formatter.date(from: properties["outer_end"] as! String)!.addingTimeInterval(1)); properties["outer_end"] = end
                properties["active_intervals"] = [["start": properties["outer_start"]!, "end": end]]
            },
            try activeIncidentBytes { $0["source_validity_start"] = "2026-10-28T10:00:00" }
        ]
        for data in invalid { XCTAssertThrowsError(try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data))) }
    }
    func testReportedActiveCacheLeaseBindsOnlyItsOwnSourcePublication() throws {
        let data = try activeIncidentBytes(), cache = RoadworksSnapshotCache()
        try cache.install(data, manifest: installingManifest(data))
        XCTAssertNil(cache.snapshot?.features.first?.sourceValidityStart)
        let id = cache.snapshot?.id
        let originalPublication = try XCTUnwrap(v2Manifest().sources.first { $0.id == "incidents-bw" }?.publication)
        for publication in [nil, originalPublication.addingTimeInterval(1)] as [Date?] {
            let manifest = try installingManifest(data) { source in
                guard source.id == "incidents-bw" else { return source }
                return .init(id: source.id, enabled: source.enabled, publication: publication, modified: source.modified,
                    checked: source.checked, status: source.status, attribution: source.attribution)
            }
            XCTAssertThrowsError(try cache.install(data, manifest: manifest))
            XCTAssertEqual(cache.snapshot?.id, id)
        }
        try cache.install(data, manifest: installingManifest(data) { source in
            guard source.id == "bemas" else { return source }
            return .init(id: source.id, enabled: source.enabled, publication: nil, modified: source.modified,
                checked: source.checked, status: source.status, attribution: source.attribution)
        })
    }
    func testReportedActiveLeaseExpiresHalfOpenEvenWhileSourceIsOnlyDelayed() throws {
        let data = try activeIncidentBytes(), snapshot = try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data))
        let manifest = try installingManifest(data)
        var runtime = RoadworksRelevance()
        func update(_ elapsed: Double) -> RoadworksRelevance.Card? {
            let at = manifest.serverTime.addingTimeInterval(elapsed)
            let statuses = ["incidents-bw": manifest.freshness(sourceID: "incidents-bw", receivedUptime: 0, nowUptime: elapsed)]
            return runtime.update(snapshot: snapshot, freshness: .fresh,
                fix: .init(point: .init(latitude: 48.001, longitude: 8), at: at, accuracyM: 5), now: at,
                enabled: true, driving: true, foreground: true, sourceFreshness: statuses,
                eligibilityNow: manifest.trustedNow(receivedUptime: 0, nowUptime: elapsed))
        }
        XCTAssertNil(update(541))
        XCTAssertEqual(update(542)?.freshness, .delayed)
        XCTAssertNotNil(update(839))
        XCTAssertEqual(manifest.freshness(sourceID: "incidents-bw", receivedUptime: 0, nowUptime: 840), .delayed)
        XCTAssertNil(update(840))
        XCTAssertEqual(manifest.freshness(sourceID: "incidents-bw", receivedUptime: 0, nowUptime: 841), .unavailable)
    }
    func testTrustedValidityClockIgnoresHandsetWallOffsetButKeepsGPSAgeSeparate() throws {
        let data = try activeIncidentBytes(), snapshot = try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data))
        let manifest = try installingManifest(data)
        for offset in [-7200.0, 7200.0] {
            var runtime = RoadworksRelevance()
            func update(_ elapsed: Double, fixAge: Double = 0) -> RoadworksRelevance.Card? {
                let wall = manifest.serverTime.addingTimeInterval(offset + elapsed)
                return runtime.update(snapshot: snapshot, freshness: .fresh,
                    fix: .init(point: .init(latitude: 48.001, longitude: 8), at: wall.addingTimeInterval(-fixAge), accuracyM: 5), now: wall,
                    enabled: true, driving: true, foreground: true,
                    sourceFreshness: ["incidents-bw": manifest.freshness(sourceID: "incidents-bw", receivedUptime: 100, nowUptime: 100 + elapsed)],
                    eligibilityNow: manifest.trustedNow(receivedUptime: 100, nowUptime: 100 + elapsed))
            }
            XCTAssertNil(update(0)); XCTAssertNotNil(update(1))
            XCTAssertNil(update(2, fixAge: 4), "GPS age must use the handset clock on both sides")
            XCTAssertNil(update(3)); XCTAssertNotNil(update(4))
            XCTAssertEqual(update(600)?.freshness, .delayed)
            XCTAssertNotNil(update(839)); XCTAssertNil(update(840), "The 900-second lease expires even with a slow handset clock")
        }
    }
    func testV2MissingOrInvalidMonotonicAnchorCannotUseWallClockAsValidity() throws {
        let data = try activeIncidentBytes(), snapshot = try RoadworksAdvisory.parseSnapshot(data, expectedID: hash(data))
        let manifest = try installingManifest(data)
        for uptime in [99, Double.nan, Double.infinity] {
            let trusted = manifest.trustedNow(receivedUptime: 100, nowUptime: uptime)
            XCTAssertNil(trusted)
            var runtime = RoadworksRelevance()
            for seconds in [0.0, 1.0] {
                let wall = manifest.serverTime.addingTimeInterval(seconds)
                XCTAssertNil(runtime.update(snapshot: snapshot, freshness: .fresh,
                    fix: .init(point: .init(latitude: 48.001, longitude: 8), at: wall, accuracyM: 5), now: wall,
                    enabled: true, driving: true, foreground: true, sourceFreshness: ["incidents-bw": .fresh], eligibilityNow: trusted))
            }
        }
    }
    func testCapturedIncidentQualificationArtifactWhenPresent() throws {
        let directory = try RoadworksTestFixtures.qualificationDirectory()
        let receiptURL = directory.appendingPathComponent("receipt.json")
        let receipt = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: receiptURL)) as? [String: Any])
        let data = try Data(contentsOf: directory.appendingPathComponent("snapshot.json"))
        let manifest = try RoadworksAdvisory.parseManifest(Data(contentsOf: directory.appendingPathComponent("manifest.json")))
        let cache = RoadworksSnapshotCache(); try cache.install(data, manifest: manifest)
        let snapshot = try XCTUnwrap(cache.snapshot)
        let checkedText = try XCTUnwrap(receipt["checked_at_utc"] as? String)
        let parser = ISO8601DateFormatter(); parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let checked = try XCTUnwrap(parser.date(from: checkedText) ?? ISO8601DateFormatter().date(from: checkedText))
        let elapsed = checked.timeIntervalSince(manifest.serverTime)
        let trusted = try XCTUnwrap(manifest.trustedNow(receivedUptime: 0, nowUptime: elapsed))
        XCTAssertEqual(trusted.timeIntervalSince1970, checked.timeIntervalSince1970, accuracy: 0.001)
        XCTAssertEqual(manifest.sourceIDs, RoadworksAdvisory.supportedSourceIDs)
        XCTAssertEqual(Set(manifest.sources.filter(\.enabled).map(\.id)), ["incidents-bw"])
        XCTAssertTrue(snapshot.features.allSatisfy { $0.advisorySource == "incidents-bw" })
        XCTAssertEqual(snapshot.features.count, try XCTUnwrap(receipt["exported_features"] as? Int))
        XCTAssertEqual(snapshot.features.filter { $0.validityBasis == "reported_active" }.count, try XCTUnwrap(receipt["reported_active_features"] as? Int))
        let status = manifest.freshness(sourceID: "incidents-bw", receivedUptime: 0, nowUptime: elapsed)
        let eligible = snapshot.features.filter { $0.eligible(at: trusted) && [.fresh, .delayed].contains(status) }
        XCTAssertEqual(eligible.count, try XCTUnwrap(receipt["eligible_features"] as? Int))
        XCTAssertTrue(snapshot.features.filter { !["roadworks", "closure", "incident", "hazard", "congestion"].contains($0.kind) }.allSatisfy { !$0.eligible(at: trusted) })
    }
    func testIncidentAgesOfflineWithoutSuppressingHealthyWorksAndUsesOwnCardStatus() throws {
        let manifest = try v2Manifest(), full = try v2Snapshot()
        let value = RoadworksAdvisory.Snapshot(id: full.id, window: full.window,
            features: full.features.filter { $0.advisorySource == "bemas" || $0.kind == "incident" },
            attributions: full.attributions, schemaVersion: 2, sourceIDs: full.sourceIDs)
        func statuses(_ elapsed: Double) -> [String: RoadworksAdvisory.Freshness] {
            Dictionary(uniqueKeysWithValues: manifest.sourceIDs.map { ($0, manifest.freshness(sourceID: $0, receivedUptime: 0, nowUptime: elapsed)) })
        }
        XCTAssertEqual(statuses(540)["incidents-bw"], .fresh)
        XCTAssertEqual(statuses(541)["incidents-bw"], .delayed)
        XCTAssertEqual(statuses(840)["incidents-bw"], .delayed)
        XCTAssertEqual(statuses(841)["incidents-bw"], .unavailable)
        XCTAssertEqual(statuses(841)["bemas"], .fresh)
        XCTAssertEqual(manifest.freshness(receivedUptime: 0, nowUptime: 841), .fresh)
        var runtime = RoadworksRelevance()
        func update(_ elapsed: Double) -> RoadworksRelevance.Card? {
            let at = manifest.serverTime.addingTimeInterval(elapsed)
            return runtime.update(snapshot: value, freshness: .unavailable,
                fix: .init(point: .init(latitude: 48.001, longitude: 8), at: at, accuracyM: 5), now: at,
                enabled: true, driving: true, foreground: true, sourceFreshness: statuses(elapsed),
                eligibilityNow: manifest.trustedNow(receivedUptime: 0, nowUptime: elapsed))
        }
        XCTAssertNil(update(600))
        XCTAssertEqual(update(601)?.feature.advisorySource, "incidents-bw")
        XCTAssertEqual(update(602)?.freshness, .delayed)
        XCTAssertNil(update(841))
        XCTAssertEqual(update(842)?.feature.advisorySource, "bemas")
    }
    func testDisabledRemovedAndFutureClockSourcesNeverGainEligibilityFromAggregate() throws {
        var manifest = try v2Manifest()
        let original = try XCTUnwrap(manifest.sources.first { $0.id == "incidents-bw" })
        manifest.sources = manifest.sources.map { $0.id == original.id ? .init(id: $0.id, enabled: false, publication: $0.publication, modified: $0.modified, checked: $0.checked, status: .fresh, attribution: $0.attribution) : $0 }
        XCTAssertEqual(manifest.freshness(sourceID: original.id, receivedUptime: 0, nowUptime: 0), .unavailable)
        XCTAssertEqual(manifest.freshness(receivedUptime: 0, nowUptime: 0), .fresh)
        manifest.sources.removeAll { $0.id == original.id }
        XCTAssertEqual(manifest.freshness(sourceID: original.id, receivedUptime: 0, nowUptime: 0), .unavailable)
        manifest.sources.append(.init(id: original.id, enabled: true, publication: original.publication,
            modified: manifest.serverTime.addingTimeInterval(1), checked: original.checked, status: .fresh, attribution: original.attribution))
        XCTAssertEqual(manifest.freshness(sourceID: original.id, receivedUptime: 0, nowUptime: 0), .unknown)
        manifest.sources = [.init(id: original.id, enabled: true, publication: manifest.serverTime,
            modified: manifest.serverTime, checked: manifest.serverTime.addingTimeInterval(-901), status: .fresh, attribution: original.attribution)]
        XCTAssertEqual(manifest.freshness(sourceID: original.id, receivedUptime: 0, nowUptime: 0), .unavailable)
    }
}


/// The physical test runner bundles these only in its signed unit-test product.
/// Captured source bytes never enter the driver's application or repository.
enum RoadworksTestFixtures {
    static func data(_ name: String) throws -> Data {
        let bundled = Bundle(for: RoadworksAdvisoryTests.self).resourceURL!
            .appendingPathComponent("roadworks", isDirectory: true).appendingPathComponent(name)
        if FileManager.default.fileExists(atPath: bundled.path) { return try Data(contentsOf: bundled) }
        #if targetEnvironment(simulator)
        let repository = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: repository.appendingPathComponent("shared/roadworks/" + name))
        #else
        throw ConsumerAppError.io("Missing bundled road advisory fixture: " + name)
        #endif
    }

    static func qualificationDirectory() throws -> URL {
        let bundled = Bundle(for: RoadworksAdvisoryTests.self).resourceURL!
            .appendingPathComponent("IncidentQualification", isDirectory: true)
        if FileManager.default.fileExists(atPath: bundled.appendingPathComponent("required.json").path) { return bundled }
        #if targetEnvironment(simulator)
        let host = URL(fileURLWithPath: "/private/tmp/youspeed-qualification-20261028/acceptance", isDirectory: true)
        guard FileManager.default.fileExists(atPath: host.appendingPathComponent("receipt.json").path) else {
            throw XCTSkip("Optional captured backend qualification artifact is not present")
        }
        return host
        #else
        // Physical acceptance must never pass by skipping unavailable host files.
        throw ConsumerAppError.io("Captured incident fixture is required on device; pass --incident-qualification-dir to the isolated test runner")
        #endif
    }
}

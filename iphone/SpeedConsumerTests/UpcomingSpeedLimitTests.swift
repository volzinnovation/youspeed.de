import XCTest
import CoreLocation
import SQLite3
import CryptoKit
import UIKit
@testable import SpeedConsumer

final class UpcomingSpeedLimitTests: XCTestCase {
    @MainActor
    func testCameraTownPassageControlsLocalityDefaultsAndKeepsExactNumericLimit() throws {
        let model = DriveSessionViewModel()
        Self.controllerLifetimes.append(model)
        defer { model.stopDriving() }
        let at = Date()
        func road(_ inside: Bool, speed: Int, source: String, highway: String) throws -> SpeedLimitResult {
            let payload: [String:Any] = ["wayID":"10","highway":highway,"speedSource":source,"speedLimitKmh":speed,
                "insideCity":inside,"citySource":"settlement:maxspeed_type:high","isTunnelSegment":false,
                "cityResolveMs":0,"cityCandidateBoundaries":0,"cityContainingBoundaries":0,"cityPlaceCandidates":0,
                "queryTimeMs":0,"candidateCount":1,"speedCandidateCount":1,"nearbyTunnelCandidateWayIDs":[],"nearbyTunnelCandidateRefs":[],
                "usedMiniHMM":false,"miniHMMCandidateCount":0,"matchHypotheses":[],"candidateTraces":[],"selectionTrace":[]]
            return try JSONDecoder().decode(SpeedLimitResult.self,from:JSONSerialization.data(withJSONObject:payload))
        }
        let location = CLLocation(coordinate:.init(latitude:48,longitude:8),altitude:0,horizontalAccuracy:5,verticalAccuracy:5,timestamp:at)
        model.testObserveCameraTownBoundary(insideCity:true,at:at)
        let entered = model.testInventoryContextualResult(try road(false,speed:100,source:"HIGHWAY_CLASS",highway:"primary"),location:location)
        XCTAssertEqual(entered.insideCity,true)
        XCTAssertEqual(entered.speedLimitKmh,50)
        XCTAssertEqual(entered.citySource,CameraTownLocalityLatch.source)
        _ = model.testApplySettlementContext(insideCity:false,source:"settlement:maxspeed_type:high",timestamp:at,coordinate:nil)
        XCTAssertEqual(model.lastLookupInsideCity,true)
        XCTAssertEqual(model.lastLookupCitySource,CameraTownLocalityLatch.source)
        model.testObserveCameraTownBoundary(insideCity:false,at:at.addingTimeInterval(1))
        let exited = model.testInventoryContextualResult(try road(true,speed:50,source:"HIGHWAY_CLASS",highway:"residential"),location:location)
        XCTAssertEqual(exited.insideCity,false)
        XCTAssertEqual(exited.speedLimitKmh,100)
        let exact = model.testInventoryContextualResult(try road(true,speed:70,source:"EXPLICIT_TAG",highway:"residential"),location:location)
        XCTAssertEqual(exact.insideCity,false)
        XCTAssertEqual(exact.speedLimitKmh,70)
    }
    func testCameraTownLocalityHasBoundaryCountryAndDriveLifetime() {
        var latch = CameraTownLocalityLatch()
        let at = Date(timeIntervalSince1970:1000)
        latch.observe(insideCity:true,at:at,countryCode:"DE")
        latch.observe(insideCity:false,at:at.addingTimeInterval(-1),countryCode:"DE")
        XCTAssertEqual(latch.insideCity,true)
        XCTAssertFalse(latch.supersedeByPhysicalBoundary(at:at))
        latch.selectCountry("DEU")
        XCTAssertEqual(latch.insideCity,true)
        XCTAssertTrue(latch.supersedeByPhysicalBoundary(at:at.addingTimeInterval(1)))
        XCTAssertNil(latch.insideCity)
        latch.observe(insideCity:false,at:at.addingTimeInterval(2),countryCode:"DE")
        latch.selectCountry("FR")
        XCTAssertNil(latch.insideCity)
        latch.observe(insideCity:true,at:at.addingTimeInterval(3),countryCode:"DE")
        latch.reset()
        XCTAssertNil(latch.insideCity)
    }
    func testGovernmentInventoryIsScopedToBadenWuerttemberg() {
        XCTAssertTrue(InventorySignSourceScope.allowsMobiData(countryCode: "DEU", dbPath: "/data/baden-wuerttemberg/speeds.sqlite"))
        XCTAssertTrue(InventorySignSourceScope.allowsMobiData(countryCode: "DE", dbPath: "/data/speeds.sqlite", sourceInputPBF: "roads/baden-wuerttemberg-260913.osm.pbf"))
        XCTAssertFalse(InventorySignSourceScope.allowsMobiData(countryCode: "FR", dbPath: "/data/baden-wuerttemberg/speeds.sqlite"))
        XCTAssertFalse(InventorySignSourceScope.allowsMobiData(countryCode: "DE", dbPath: "/data/germany/speeds.sqlite"))
        XCTAssertFalse(InventorySignSourceScope.allowsMobiData(countryCode: nil, dbPath: "/data/unknown.sqlite"))
        XCTAssertFalse(InventorySignSourceScope.allowsMobiData(countryCode: "DE", dbPath: "/data/baden-wuerttemberg/speeds.sqlite", sourceInputPBF: "roads/bavaria.osm.pbf"))
    }
    func testResidentialRoadLocalityHonorsExplicitTagsAndTownBoundaries() {
        let fallback = V3SpeedLimitService.residentialSettlementContext(.missing, highway: " ReSiDeNtIaL ")
        XCTAssertEqual(fallback.insideCity, true)
        XCTAssertEqual(fallback.citySource, "settlement:highway_residential:high")
        for source in ["zone_traffic", "maxspeed_type", "source_maxspeed", "traffic_sign"] {
            let explicit = V3SpeedLimitService.SettlementDecision(insideCity: false, source: source, confidence: "high")
            XCTAssertEqual(V3SpeedLimitService.residentialSettlementContext(explicit, highway: "residential"), explicit)
        }
        XCTAssertEqual(V3SpeedLimitService.residentialSettlementContext(.conflict, highway: "residential"), .conflict)
        XCTAssertEqual(V3SpeedLimitService.residentialSettlementContext(.missing, highway: "service"), .missing)
    }
    // Async delivery may still own a client after a controller fixture has stopped.
    // Keep these fixtures alive for the test process, as the existing controller suite does.
    @MainActor private static var controllerLifetimes: [DriveSessionViewModel] = []
    private struct Corpus: Decodable {
        struct Case: Decodable {
            struct Step: Decodable {
                struct Expected: Decodable { let signID: String?; let speedKmh: Int?; let distanceM: Double? }
                let event: String; let nowS: Double; let fixS: Double; let bundleID: String
                let currentLimitKmh: Int?; let currentUnlimited: Bool; let currentUsable: Bool
                let speedKmh: Double?
                let snapshot: UpcomingSpeedLimitSnapshot?; let expected: Expected
            }
            let id: String; let steps: [Step]
        }
        let schemaVersion: Int; let cases: [Case]
    }

    func testSharedSelectionAndLifetimeCorpus() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "scenarios-v1", withExtension: "json", subdirectory: "upcoming-speed-limit"))
        let data = try Data(contentsOf: url)
        let corpus = try JSONDecoder().decode(Corpus.self, from: data)
        XCTAssertEqual(corpus.schemaVersion, 1)
        var steps = 0
        for scenario in corpus.cases {
            var tracker = UpcomingSpeedLimitTracker()
            for step in scenario.steps {
                steps += 1
                let now = Date(timeIntervalSince1970: step.nowS)
                if let speedKmh = step.speedKmh, let snapshot = step.snapshot {
                    XCTAssertEqual(snapshot.lookaheadDistanceM, UpcomingSpeedLimitHorizon.distanceM(speedKmh: speedKmh), accuracy: 0.000001, scenario.id)
                }
                if step.event == "fix" {
                    tracker.consume(step.snapshot, bundle: step.bundleID, at: Date(timeIntervalSince1970: step.fixS), now: now)
                }
                let actual = tracker.selection(currentKmh: step.currentLimitKmh, unlimited: step.currentUnlimited,
                    currentIsStale: !step.currentUsable, now: now)
                XCTAssertEqual(actual?.signID, step.expected.signID, scenario.id)
                XCTAssertEqual(actual?.speedKmh, step.expected.speedKmh, scenario.id)
                XCTAssertEqual(actual?.distanceM, step.expected.distanceM, scenario.id)
            }
        }
        XCTAssertGreaterThanOrEqual(steps, 31)
    }

    func testGapJumpPastBoundedProofCannotResurrectOldTarget() {
        let candidate = UpcomingSpeedLimitCandidate(signID: "speed", sourceID: "fixture", snapshotSHA256: "snapshot",
            ruleID: "rule", originWayID: "101", direction: 1, stationM: 250, speedKmh: 70, distanceM: 150)
        let before = UpcomingSpeedLimitSnapshot(wayID: "101", direction: 1, chainageM: 100, relationGroupIDs: [10],
            path: [.init(segmentID: "1", wayID: "101", direction: 1, startM: 100, endM: 400, entryDistanceM: 0, relationGroupIDs: [10])],
            candidates: [candidate], reason: "candidate", queryTimeMs: 0, topologyAvailable: true)
        let afterGap = UpcomingSpeedLimitSnapshot(wayID: "102", direction: 1, chainageM: 500, relationGroupIDs: [10],
            path: [.init(segmentID: "2", wayID: "102", direction: 1, startM: 500, endM: 800, entryDistanceM: 0, relationGroupIDs: [10])],
            candidates: [], reason: "no_target", queryTimeMs: 0, topologyAvailable: true)
        var tracker = UpcomingSpeedLimitTracker()
        let at = Date(timeIntervalSince1970: 1000)
        tracker.consume(before, bundle: "fixture", at: at, now: at)
        tracker.invalidate(reason: "stale_fix")
        tracker.consume(afterGap, bundle: "fixture", at: at.addingTimeInterval(10), now: at.addingTimeInterval(10))
        tracker.consume(before, bundle: "fixture", at: at.addingTimeInterval(11), now: at.addingTimeInterval(11))
        XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at.addingTimeInterval(11)))
    }

    func testOptionalRealBWCertifiedApproaches() throws {
        struct Probe: Decodable {
            struct Case: Decodable {
                let id: String; let wayID: String; let direction: Int; let chainageM: Double
                let points: [[Double]]; let lat: Double; let lon: Double; let headingDeg: Double
                let relationGroupIDs: [Int]; let expectedSignID: String; let expectedSpeedKmh: Int
                let expectedDistanceM: Double; let expectedOriginWayID: String
            }
            let format: String; let cases: [Case]
        }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let directory = ProcessInfo.processInfo.environment["YOUSPEED_UPCOMING_BW_PROBE_DIR"].map { URL(fileURLWithPath: $0) }
            ?? root.appendingPathComponent("output/upcoming-speed-limit-bw-probe")
        guard FileManager.default.fileExists(atPath: directory.appendingPathComponent("cases.json").path) else {
            throw XCTSkip("Optional BW source-derived probe is not present")
        }
        let probe = try JSONDecoder().decode(Probe.self, from: Data(contentsOf: directory.appendingPathComponent("cases.json")))
        XCTAssertEqual(probe.format, "youspeed.upcoming.bw-probe.v1")
        let resources = V3LookupResources(path: directory.appendingPathComponent("probe.sqlite").path)
        let session = try resources.acquire()
        defer { resources.releaseSession() }
        var warm: [Double] = []
        for item in probe.cases {
            let points = try item.points.map { row -> (Double, Double) in
                guard row.count == 2 else { throw NSError(domain: "invalid_probe_coordinate", code: 1) }
                return (row[0], row[1])
            }
            let projection = try XCTUnwrap(InventorySignBundle.projection(lat: item.lat, lon: item.lon, points: points))
            XCTAssertEqual(projection.chainage, item.chainageM, accuracy: 0.25, item.id)
            for iteration in 0..<30 {
                let result = try XCTUnwrap(UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources,
                    inventory: .init(signs: [], activeRule: nil, wayID: item.wayID, direction: item.direction, chainageM: item.chainageM),
                    points: points, relationGroupIDs: item.relationGroupIDs))
                let candidate = try XCTUnwrap(result.candidates.first, item.id + ": " + result.reason)
                XCTAssertTrue(result.topologyAvailable, item.id)
                XCTAssertEqual(candidate.signID, item.expectedSignID, item.id)
                XCTAssertEqual(candidate.speedKmh, item.expectedSpeedKmh, item.id)
                XCTAssertEqual(candidate.originWayID, item.expectedOriginWayID, item.id)
                XCTAssertEqual(candidate.distanceM, item.expectedDistanceM, accuracy: 0.25, item.id)
                if iteration > 0 { warm.append(result.queryTimeMs) }
            }
        }
        let sorted = warm.sorted()
        if !sorted.isEmpty { print("UPCOMING_BW_NATIVE cases=\(probe.cases.count) warm_samples=\(sorted.count) p95_ms=\(sorted[Int(Double(sorted.count - 1) * 0.95)]) p99_ms=\(sorted[Int(Double(sorted.count - 1) * 0.99)]) max_ms=\(sorted.last!)") }
    }

    @MainActor
    func testControllerComparesFinalAuthorityAndRejectsBackgroundCompletion() async throws {
        let model = DriveSessionViewModel()
        Self.controllerLifetimes.append(model)
        defer { model.stopDriving() }
        try await model.testWaitForStartupDataLoad()
        let at = Date()
        let candidate = UpcomingSpeedLimitCandidate(signID: "speed", sourceID: "fixture", snapshotSHA256: "snapshot",
            ruleID: "rule", originWayID: "101", direction: 1, stationM: 250, speedKmh: 70, distanceM: 150)
        let snapshot = UpcomingSpeedLimitSnapshot(wayID: "101", direction: 1, chainageM: 100,
            relationGroupIDs: [10], path: [.init(segmentID: nil, wayID: "101", direction: 1,
                startM: 100, endM: 400, entryDistanceM: 0, relationGroupIDs: [10])],
            candidates: [candidate], reason: "candidate", queryTimeMs: 0, topologyAvailable: false)
        model.testPrepareUpcomingReference(bundleLimit: 100, cameraLimit: 50)
        model.testCommitUpcomingSnapshot(snapshot, timestamp: at, generation: model.testUpcomingGeneration)
        XCTAssertEqual(model.speedLimitKmh, 50)
        XCTAssertNil(model.upcomingSpeedLimit)
        // A reference change re-evaluates the retained snapshot without another lookup.
        model.testPrepareUpcomingReference(bundleLimit: 100)
        XCTAssertEqual(model.upcomingSpeedLimit?.speedKmh, 70)
        model.testSetUpcomingPendingRoadContext()
        XCTAssertNil(model.upcomingSpeedLimit)
        model.testPrepareUpcomingReference(bundleLimit: 100)
        XCTAssertEqual(model.upcomingSpeedLimit?.speedKmh, 70)
        let obsolete = model.testUpcomingGeneration
        model.setTrafficSignApplicationActive(false)
        XCTAssertNil(model.upcomingSpeedLimit)
        model.testCommitUpcomingSnapshot(snapshot, timestamp: Date(), generation: obsolete)
        XCTAssertNil(model.upcomingSpeedLimit)
        model.setTrafficSignApplicationActive(true)
        XCTAssertNil(model.upcomingSpeedLimit)
    }

    @MainActor
    func testControllerProvisionalSplitNeedsPreviousCertifiedPath() async throws {
        let model = DriveSessionViewModel()
        Self.controllerLifetimes.append(model)
        defer { model.stopDriving() }
        try await model.testWaitForStartupDataLoad()
        model.testPrepareUpcomingReference(bundleLimit: 100)
        let candidate = UpcomingSpeedLimitCandidate(signID: "speed", sourceID: "fixture", snapshotSHA256: "snapshot",
            ruleID: "rule", originWayID: "102", direction: -1, stationM: 50, speedKmh: 70, distanceM: 150)
        let childPath = UpcomingSpeedLimitPath(segmentID: "2", wayID: "102", direction: -1,
            startM: 0, endM: 200, entryDistanceM: 0, relationGroupIDs: [10])
        let provisional = UpcomingSpeedLimitSnapshot(wayID: "102", direction: -1, chainageM: 200,
            relationGroupIDs: [10], path: [childPath], candidates: [candidate], reason: "candidate", queryTimeMs: 0, topologyAvailable: true)
        model.testCommitUpcomingSnapshot(provisional, timestamp: Date(), generation: model.testUpcomingGeneration,
            requiresCertifiedContinuation: true)
        XCTAssertNil(model.upcomingSpeedLimit, "Global topology and shared relation alone are not prior path proof")
        let prior = UpcomingSpeedLimitSnapshot(wayID: "101", direction: 1, chainageM: 100,
            relationGroupIDs: [10], path: [.init(segmentID: "1", wayID: "101", direction: 1,
                startM: 100, endM: 150, entryDistanceM: 0, relationGroupIDs: [10]), childPath],
            candidates: [], reason: "candidate", queryTimeMs: 0, topologyAvailable: true)
        model.testCommitUpcomingSnapshot(prior, timestamp: Date(), generation: model.testUpcomingGeneration)
        model.testCommitUpcomingSnapshot(provisional, timestamp: Date(), generation: model.testUpcomingGeneration,
            requiresCertifiedContinuation: true)
        XCTAssertEqual(model.upcomingSpeedLimit?.signID, "speed")
        model.activeBundleVersion = "other-bundle-with-coincident-group-ids"
        model.activeDBPath = "other.sqlite"
        model.testSetUpcomingBundleIdentity("other-sha-with-coincident-group-ids")
        model.testCommitUpcomingSnapshot(provisional, timestamp: Date(), generation: model.testUpcomingGeneration,
            requiresCertifiedContinuation: true)
        XCTAssertNil(model.upcomingSpeedLimit, "A certificate is local to its bundle identity")
    }

    @MainActor
    func testControllerTimerExpiresWithoutAnotherFix() async throws {
        let model = DriveSessionViewModel()
        Self.controllerLifetimes.append(model)
        defer { model.stopDriving() }
        try await model.testWaitForStartupDataLoad()
        model.testPrepareUpcomingReference(bundleLimit: 100)
        let candidate = UpcomingSpeedLimitCandidate(signID: "speed", sourceID: "fixture", snapshotSHA256: "snapshot",
            ruleID: "rule", originWayID: "101", direction: 1, stationM: 250, speedKmh: 70, distanceM: 150)
        let snapshot = UpcomingSpeedLimitSnapshot(wayID: "101", direction: 1, chainageM: 100,
            relationGroupIDs: [10], path: [.init(segmentID: nil, wayID: "101", direction: 1,
                startM: 100, endM: 400, entryDistanceM: 0, relationGroupIDs: [10])],
            candidates: [candidate], reason: "candidate", queryTimeMs: 0, topologyAvailable: false)
        model.testCommitUpcomingSnapshot(snapshot, timestamp: Date().addingTimeInterval(-2.8), generation: model.testUpcomingGeneration)
        XCTAssertNotNil(model.upcomingSpeedLimit)
        try await Task.sleep(nanoseconds: 350_000_000)
        XCTAssertNil(model.upcomingSpeedLimit)
    }

    private let schema = """
        CREATE TABLE traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO traffic_sign_capability VALUES('version','1'),('road_snapshot_sha256','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
        CREATE TABLE traffic_sign_runtime(sign_id TEXT PRIMARY KEY,kind TEXT,sign_code TEXT,numeric_value REAL,unit TEXT,parameter_status TEXT,source_id TEXT,snapshot_sha256 TEXT);
        CREATE TABLE traffic_sign_association(sign_id TEXT,status TEXT,way_id INTEGER,direction INTEGER,station_chainage_m REAL);
        CREATE INDEX association_way ON traffic_sign_association(way_id,direction,status);
        CREATE TABLE traffic_sign_way_rule(rule_id TEXT,sign_id TEXT,way_id INTEGER,direction INTEGER,station_chainage_m REAL,start_chainage_m REAL,end_chainage_m REAL,speed_kmh REAL,association_status TEXT,lane_scope TEXT);
        CREATE INDEX rule_way ON traffic_sign_way_rule(way_id,direction);
        CREATE TABLE way_continuity_group(continuity_group_id INTEGER PRIMARY KEY,continuity_kind TEXT);
        CREATE TABLE way_continuity_membership(way_id INTEGER,continuity_group_id INTEGER);
        INSERT INTO way_continuity_group VALUES(10,'route_relation_connected');
        INSERT INTO way_continuity_membership VALUES(101,10),(102,10);
        """
    private let target = """
        INSERT INTO traffic_sign_runtime VALUES('speed','speed_limit','DE:274-70',70,'km/h','parsed_source_value','fixture','snapshot');
        INSERT INTO traffic_sign_association VALUES('speed','accepted',101,1,250);
        INSERT INTO traffic_sign_way_rule VALUES('rule','speed',101,1,250,250,1100,70,'accepted','all');
        """
    private let topology = """
        CREATE TABLE upcoming_path_capability(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO upcoming_path_capability VALUES
          ('version','1'),('completeness','complete'),('road_snapshot_sha256','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
          ('geometry_convention','source_vertices_spherical_6371000m_v1'),('source_node_incidence','complete_pbf_highway_v1'),
          ('restrictions','all_involved_ways_stop_v1'),('motorcar_profile','existing_runtime_direction_v1');
        CREATE TABLE upcoming_path_segment(segment_id INTEGER PRIMARY KEY,way_id INTEGER,direction INTEGER,start_chainage_m REAL,end_chainage_m REAL,start_node_id INTEGER,end_node_id INTEGER,length_m REAL,permission_status TEXT);
        CREATE TABLE upcoming_path_successor(from_segment_id INTEGER PRIMARY KEY,status TEXT,to_segment_id INTEGER,via_node_id INTEGER,proof TEXT);
        INSERT INTO upcoming_path_segment VALUES(1,101,1,0,150,1,2,150,'allowed'),(2,102,-1,0,200,2,3,200,'allowed');
        INSERT INTO upcoming_path_successor VALUES(1,'certified',2,2,'source_node_unbranched_unmerged_v1');
        """
    private func fixture(_ additions: String, body: (V3LookupResources, OpaquePointer) throws -> Void) throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("upcoming-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("fixture.sqlite")
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(file.path, &db), SQLITE_OK)
        let connection = try XCTUnwrap(db)
        let status = sqlite3_exec(connection, schema + additions, nil, nil, nil)
        let message = String(cString: sqlite3_errmsg(connection))
        sqlite3_close(connection)
        XCTAssertEqual(status, SQLITE_OK, message)
        let resources = V3LookupResources(path: file.path)
        let session = try resources.acquire()
        defer { resources.releaseSession() }
        try body(resources, session.db)
    }
    private func lookup(_ resources: V3LookupResources, _ db: OpaquePointer, way: String = "101", direction: Int = 1, chainage: Double = 100,
                        speedKmh: Double? = nil, points: [(Double, Double)] = [(0, 0), (0, 0.01)]) -> UpcomingSpeedLimitSnapshot? {
        UpcomingSpeedLimitBundle.lookup(db: db, resources: resources,
            inventory: .init(signs: [], activeRule: nil, wayID: way, direction: direction, chainageM: chainage),
            points: points, relationGroupIDs: [10], speedKmh: speedKmh)
    }
    func testThirtySecondHorizonAndInvalidMeasuredSpeeds() {
        for speed: Double? in [nil, -1, .nan, .infinity, -.infinity, .greatestFiniteMagnitude, 0, 10, 30, 36] {
            XCTAssertEqual(UpcomingSpeedLimitHorizon.distanceM(speedKmh: speed), 300)
        }
        XCTAssertEqual(UpcomingSpeedLimitHorizon.distanceM(speedKmh: 50), 416.6666666666667, accuracy: 0.000001)
        XCTAssertEqual(UpcomingSpeedLimitHorizon.distanceM(speedKmh: 100), 833.3333333333334, accuracy: 0.000001)
        XCTAssertEqual(UpcomingSpeedLimitHorizon.distanceM(speedKmh: 130), 1083.3333333333333, accuracy: 0.000001)
        XCTAssertEqual(UpcomingSpeedLimitHorizon.distanceM(speedKmh: 500), 500 / 3.6 * 30,
                       "Traversal is bounded by work and time rather than an arbitrary distance ceiling")
    }

    func testSnapshotLegacyJSONDefaultsHorizonAndRoundTripsDynamicHorizon() throws {
        let legacy = Data("""
            {"wayID":"101","direction":1,"chainageM":100,"relationGroupIDs":[10],"path":[],"candidates":[],"reason":"no_target","queryTimeMs":0,"topologyAvailable":false}
            """.utf8)
        XCTAssertEqual(try JSONDecoder().decode(UpcomingSpeedLimitSnapshot.self, from: legacy).lookaheadDistanceM, 300)
        let dynamic = UpcomingSpeedLimitSnapshot(wayID: "101", direction: 1, chainageM: 100, relationGroupIDs: [10],
            path: [], candidates: [], reason: "no_target", queryTimeMs: 0, topologyAvailable: false,
            lookaheadDistanceM: UpcomingSpeedLimitHorizon.distanceM(speedKmh: 130))
        XCTAssertEqual(try JSONDecoder().decode(UpcomingSpeedLimitSnapshot.self, from: JSONEncoder().encode(dynamic)), dynamic)
    }

    func testNativeReaderAdmitsExactDynamicBoundaryAndRejectsBeyondInBothDirections() throws {
        for speed in [50.0, 100.0, 130.0] {
            let horizon = UpcomingSpeedLimitHorizon.distanceM(speedKmh: speed)
            for direction in [-1, 1] {
                let chainage = direction == 1 ? 100.0 : 2000.0
                let station = chainage + Double(direction) * horizon
                let start = direction == 1 ? station : 0.0
                let end = direction == 1 ? 2200.0 : station
                for offset in [0.0, 0.001] {
                    let shiftedStation = station + Double(direction) * offset
                    try fixture(target + """
                        UPDATE traffic_sign_association SET direction=\(direction),station_chainage_m=\(shiftedStation);
                        UPDATE traffic_sign_way_rule SET direction=\(direction),station_chainage_m=\(shiftedStation),start_chainage_m=\(direction == 1 ? shiftedStation : start),end_chainage_m=\(direction == 1 ? end : shiftedStation);
                        """) { resources, db in
                            let result = try XCTUnwrap(lookup(resources, db, direction: direction, chainage: chainage,
                                speedKmh: speed, points: [(0, 0), (0, 0.02)]))
                            XCTAssertEqual(result.lookaheadDistanceM, horizon)
                            if offset == 0 {
                                XCTAssertEqual(try XCTUnwrap(result.candidates.first).distanceM, horizon, accuracy: 0.000001)
                                var tracker = UpcomingSpeedLimitTracker()
                                let at = Date(timeIntervalSince1970: 1000)
                                tracker.consume(result, bundle: "fixture", at: at, now: at)
                                XCTAssertEqual(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at)?.signID, "speed")
                                XCTAssertEqual(tracker.snapshot?.lookaheadDistanceM, horizon)
                            } else { XCTAssertTrue(result.candidates.isEmpty) }
                        }
                }
            }
        }
    }

    func testDynamicHorizonCrossesCertifiedReverseWayAndHonorsPassageAndExpiry() throws {
        try fixture(topology + target + """
            UPDATE upcoming_path_segment SET end_chainage_m=450,length_m=450 WHERE segment_id=1;
            UPDATE traffic_sign_association SET way_id=102,direction=-1,station_chainage_m=150;
            UPDATE traffic_sign_way_rule SET way_id=102,direction=-1,station_chainage_m=150,start_chainage_m=0,end_chainage_m=150;
            """) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty, "The default 300 m window does not reach the target")
                let result = try XCTUnwrap(lookup(resources, db, speedKmh: 50))
                XCTAssertEqual(result.candidates.first?.distanceM, 400)
                XCTAssertEqual(result.path.count, 2)
                var tracker = UpcomingSpeedLimitTracker()
                let at = Date(timeIntervalSince1970: 1000)
                tracker.consume(result, bundle: "fixture", at: at, now: at)
                XCTAssertEqual(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at)?.signID, "speed")
                XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at.addingTimeInterval(3)))
                tracker.consume(result, bundle: "fixture", at: at.addingTimeInterval(4), now: at.addingTimeInterval(4))
                let after = try XCTUnwrap(lookup(resources, db, way: "102", direction: -1, chainage: 149, speedKmh: 50))
                tracker.consume(after, bundle: "fixture", at: at.addingTimeInterval(5), now: at.addingTimeInterval(5))
                tracker.consume(result, bundle: "fixture", at: at.addingTimeInterval(6), now: at.addingTimeInterval(6))
                XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at.addingTimeInterval(6)), "Jitter cannot resurrect the passed station")
            }
    }

    func testTrackerRejectsInvalidOrNarrowerSnapshotHorizon() {
        let candidate = UpcomingSpeedLimitCandidate(signID: "speed", sourceID: "fixture", snapshotSHA256: "snapshot",
            ruleID: "rule", originWayID: "101", direction: 1, stationM: 500, speedKmh: 70, distanceM: 400)
        let path = UpcomingSpeedLimitPath(segmentID: nil, wayID: "101", direction: 1, startM: 100, endM: 1000,
            entryDistanceM: 0, relationGroupIDs: [10])
        let at = Date(timeIntervalSince1970: 1000)
        for horizon in [Double.nan, .infinity, -.infinity, -1, 299, 300] {
            var tracker = UpcomingSpeedLimitTracker()
            let snapshot = UpcomingSpeedLimitSnapshot(wayID: "101", direction: 1, chainageM: 100, relationGroupIDs: [10],
                path: [path], candidates: [candidate], reason: "candidate", queryTimeMs: 0, topologyAvailable: false,
                lookaheadDistanceM: horizon)
            tracker.consume(snapshot, bundle: "fixture", at: at, now: at)
            XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at))
        }
    }

    func testPhysicalOriginAndIndexedWarmQueries() throws {
        try fixture(target) { resources, db in
            let first = try XCTUnwrap(lookup(resources, db))
            XCTAssertEqual(first.candidates.first?.distanceM, 150)
            XCTAssertEqual(first.candidates.first?.originWayID, "101")
            XCTAssertFalse(first.topologyAvailable)
            let prepares = resources.statistics.prepares
            XCTAssertEqual(lookup(resources, db)?.candidates.first?.signID, "speed")
            XCTAssertEqual(resources.statistics.prepares, prepares)
        }
    }
    func testNonacceptedLocatedConflictBlocksLaterTarget() throws {
        try fixture(target + """
            INSERT INTO traffic_sign_runtime VALUES('conflict','speed_limit','DE:274-30',30,'km/h','parsed_source_value','fixture','snapshot');
            INSERT INTO traffic_sign_association VALUES('conflict','conflicting_source_values',101,1,200);
            """) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
        }
    }
    func testBoundaryAndUnresolvedLaneRuleBlockLaterTarget() throws {
        for additional in ["""
            INSERT INTO traffic_sign_runtime VALUES('town','settlement_boundary','DE:310',NULL,NULL,'not_applicable','fixture','snapshot');
            INSERT INTO traffic_sign_association VALUES('town','accepted',101,1,200);
            """, "UPDATE traffic_sign_way_rule SET lane_scope='conditional';"] {
            try fixture(target + additional) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
            }
        }
    }
    private let townEntry = """
        ALTER TABLE traffic_sign_way_rule ADD COLUMN inside_city INTEGER;
        INSERT INTO traffic_sign_runtime VALUES('town','settlement_boundary','DE:310',NULL,NULL,'not_applicable','osm-settlement','snapshot');
        INSERT INTO traffic_sign_association VALUES('town','accepted',101,1,200);
        INSERT INTO traffic_sign_way_rule VALUES('town-rule','town',101,1,200,200,1100,NULL,'accepted','all',1);
        """
    func testDirectedTownEntryPreviewsFiftyAndExitOrUnresolvedLocalityDoesNot() throws {
        for direction in [1, -1] {
            try fixture(townEntry + """
                UPDATE traffic_sign_association SET direction=\(direction);
                UPDATE traffic_sign_way_rule SET direction=\(direction),start_chainage_m=\(direction == 1 ? 200 : 0),end_chainage_m=\(direction == 1 ? 1100 : 200);
                """) { resources, db in
                    let result = try XCTUnwrap(lookup(resources, db, direction: direction, chainage: direction == 1 ? 100 : 300))
                    XCTAssertEqual(result.candidates.map(\.speedKmh), [50])
                    XCTAssertEqual(result.candidates.first?.sourceID, "osm-settlement")
                    XCTAssertEqual(result.candidates.first?.distanceM, 100)
                    XCTAssertTrue(try XCTUnwrap(lookup(resources, db, direction: -direction, chainage: direction == 1 ? 100 : 300)).candidates.isEmpty)
            }
        }
        for invalid in ["UPDATE traffic_sign_runtime SET sign_code='DE:311';", "UPDATE traffic_sign_way_rule SET inside_city=NULL;", "UPDATE traffic_sign_way_rule SET lane_scope='unresolved';", "UPDATE traffic_sign_association SET status='ambiguous';"] {
            try fixture(townEntry + invalid) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty, invalid)
            }
        }
    }
    func testTownEntryKeepsFreshExplicitLimitAndCannotHideItsConditionalScope() throws {
        let posted = """
            UPDATE traffic_sign_way_rule SET end_chainage_m=200 WHERE sign_id='town';
            INSERT INTO traffic_sign_runtime VALUES('posted','speed_limit','DE:274-30',30,'km/h','parsed_source_value','fixture','snapshot');
            INSERT INTO traffic_sign_association VALUES('posted','accepted',101,1,200);
            INSERT INTO traffic_sign_way_rule VALUES('posted-rule','posted',101,1,200,200,1100,30,'accepted','all',1);
            """
        try fixture(townEntry + posted) { resources, db in
            let candidates = try XCTUnwrap(lookup(resources, db)).candidates
            XCTAssertEqual(candidates.count, 1)
            let candidate = candidates.first
            XCTAssertEqual(candidate?.signID, "posted")
            XCTAssertEqual(candidate?.speedKmh, 30)
        }
        for scope in ["conditional", "unresolved"] {
            try fixture(townEntry + posted + "UPDATE traffic_sign_way_rule SET lane_scope='\(scope)' WHERE sign_id='posted';") { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
            }
        }
    }
    func testConditionalOSMContextBlocksImpliedTownFiftyWithoutSuppressingGovernmentBoundary() throws {
        let conditional = """
            CREATE TABLE road_speed_rule_set(way_id INTEGER PRIMARY KEY,rules_json TEXT);
            INSERT INTO road_speed_rule_set VALUES(101,'{}');
            """
        try fixture(townEntry + conditional) { resources, db in
            XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
        }
        try fixture(townEntry + conditional + "UPDATE traffic_sign_runtime SET source_id='mobidata-bw-vzk';") { resources, db in
            XCTAssertEqual(try XCTUnwrap(lookup(resources, db)).candidates.map(\.speedKmh), [50])
            let hidden = UpcomingSpeedLimitBundle.lookup(db: db, resources: resources,
                inventory: .init(signs: [], activeRule: nil, wayID: "101", direction: 1, chainageM: 100),
                points: [(0, 0), (0, 0.01)], relationGroupIDs: [10], allowMobiData: false)
            XCTAssertTrue(try XCTUnwrap(hidden).candidates.isEmpty)
        }
    }
    func testTownEntryAtCertifiedSplitUsesPhysicalOriginAndReverseChildLocality() throws {
        try fixture(topology + townEntry + """
            UPDATE traffic_sign_association SET station_chainage_m=150;
            UPDATE traffic_sign_way_rule SET station_chainage_m=150,start_chainage_m=150,end_chainage_m=150;
            INSERT INTO traffic_sign_way_rule VALUES('town-child','town',102,-1,200,0,200,NULL,'accepted','all',1);
            """) { resources, db in
                let result = try XCTUnwrap(lookup(resources, db))
                XCTAssertEqual(result.candidates.first?.signID, "town")
                XCTAssertEqual(result.candidates.first?.speedKmh, 50)
                XCTAssertEqual(result.candidates.first?.distanceM, 50)
                XCTAssertEqual(result.candidates.first?.originWayID, "101")
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db, way: "102", direction: -1, chainage: 190)).candidates.isEmpty)
        }
    }
    func testPropagatedChildEntryIsNotAnotherPhysicalSign() throws {
        try fixture(target + """
            INSERT INTO traffic_sign_way_rule VALUES('child','speed',102,1,0,0,200,70,'accepted','all');
            """) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db, way: "102", chainage: 0)).candidates.isEmpty)
        }
    }
    func testCertifiedSplitWithOppositeGeometryOrientation() throws {
        try fixture(topology + target + """
            UPDATE traffic_sign_association SET way_id=102,direction=-1,station_chainage_m=50;
            UPDATE traffic_sign_way_rule SET way_id=102,direction=-1,station_chainage_m=50,start_chainage_m=0,end_chainage_m=50;
            """) { resources, db in
                let result = try XCTUnwrap(lookup(resources, db))
                XCTAssertTrue(result.topologyAvailable)
                XCTAssertEqual(result.path.count, 2)
                XCTAssertEqual(result.candidates.first?.distanceM, 200)
                XCTAssertEqual(result.candidates.first?.direction, -1)
        }
    }
    func testPreviewOnlyContextAdmitsCertifiedSplitWithoutChangingPrimaryInventory() throws {
        try fixture(topology + target) { resources, db in
            let primary = InventorySignLookup(signs: [], activeRule: nil, wayID: "102", direction: nil, chainageM: 100)
            let context = UpcomingSpeedLimitBundle.previewContext(db: db, resources: resources, inventory: primary,
                points: [(0, 0), (0, 0.01)], latitude: 0, longitude: 100 / 111195.08,
                heading: 270, headingAccuracy: 5, accuracy: 5, fixUsable: true,
                preferredWayID: "101", matchedFixCount: 2, relationGroupIDs: [10])
            XCTAssertNil(primary.direction)
            XCTAssertEqual(context?.direction, -1)
            XCTAssertNotNil(lookup(resources, db))
        }
    }
    func testUncertifiedProofAndSourceMismatchCannotCrossWay() throws {
        for sql in ["UPDATE upcoming_path_successor SET proof='rounded_endpoint';", "UPDATE upcoming_path_capability SET value='other-source' WHERE key='road_snapshot_sha256';"] {
            try fixture(topology + target + """
                UPDATE traffic_sign_association SET way_id=102,direction=-1,station_chainage_m=50;
                UPDATE traffic_sign_way_rule SET way_id=102,direction=-1,station_chainage_m=50,start_chainage_m=0,end_chainage_m=50;
                """ + sql) { resources, db in
                    XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
                }
        }
    }
    func testAllStatusEventWorkCapDoesNotChooseFromTruncatedSegment() throws {
        var events = target
        for index in 0..<257 {
            events += "INSERT INTO traffic_sign_runtime VALUES('secondary\(index)','secondary','DE:205',NULL,NULL,'not_applicable','fixture','snapshot'); INSERT INTO traffic_sign_association VALUES('secondary\(index)','accepted',101,1,200);"
        }
        try fixture(events) { resources, db in
            let result = try XCTUnwrap(lookup(resources, db))
            XCTAssertTrue(result.candidates.isEmpty)
            XCTAssertEqual(result.reason, "budget_exceeded")
        }
    }

    func testInteriorJunctionStopAndDeniedCurrentSegmentNeverFallBackPastStop() throws {
        for additional in ["DELETE FROM upcoming_path_successor;", "UPDATE upcoming_path_segment SET permission_status='blocked' WHERE segment_id=1;"] {
            try fixture(topology + target + additional) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
            }
        }
    }
    func testEndpointOriginUsesCertifiedUniqueContinuingOffer() throws {
        try fixture(topology + target + """
            UPDATE traffic_sign_association SET station_chainage_m=150;
            UPDATE traffic_sign_way_rule SET station_chainage_m=150,start_chainage_m=150,end_chainage_m=150;
            INSERT INTO traffic_sign_way_rule VALUES('child','speed',102,-1,200,0,200,70,'accepted','all');
            """) { resources, db in
                let result = try XCTUnwrap(lookup(resources, db))
                XCTAssertEqual(result.candidates.first?.stationM, 150)
                XCTAssertEqual(result.candidates.first?.originWayID, "101")
                XCTAssertEqual(result.candidates.first?.distanceM, 50)
                var tracker = UpcomingSpeedLimitTracker()
                let at = Date(timeIntervalSince1970: 1000)
                tracker.consume(result, bundle: "fixture", at: at, now: at)
                XCTAssertEqual(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at)?.signID, "speed")
                let next = try XCTUnwrap(lookup(resources, db, way: "102", direction: -1, chainage: 199))
                tracker.consume(next, bundle: "fixture", at: at.addingTimeInterval(1), now: at.addingTimeInterval(1))
                XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at.addingTimeInterval(1)))
            }
    }

    func testEndpointExactlyAtDynamicHorizonConsumesOnCertifiedChildBeforeJitter() throws {
        let horizon = UpcomingSpeedLimitHorizon.distanceM(speedKmh: 50)
        let station = 100 + horizon
        try fixture(topology + target + """
            UPDATE upcoming_path_segment SET end_chainage_m=\(station),length_m=\(station) WHERE segment_id=1;
            UPDATE traffic_sign_association SET station_chainage_m=\(station);
            UPDATE traffic_sign_way_rule SET station_chainage_m=\(station),start_chainage_m=\(station),end_chainage_m=\(station);
            INSERT INTO traffic_sign_way_rule VALUES('child','speed',102,-1,200,0,200,70,'accepted','all');
            """) { resources, db in
                let result = try XCTUnwrap(lookup(resources, db, speedKmh: 50))
                XCTAssertEqual(result.candidates.first?.distanceM ?? -1, horizon, accuracy: 0.000001)
                XCTAssertEqual(result.path.last?.wayID, "102")
                XCTAssertLessThanOrEqual(result.path.count, 32)
                var tracker = UpcomingSpeedLimitTracker()
                let at = Date(timeIntervalSince1970: 1000)
                tracker.consume(result, bundle: "fixture", at: at, now: at)
                let after = try XCTUnwrap(lookup(resources, db, way: "102", direction: -1, chainage: 199, speedKmh: 50))
                tracker.consume(after, bundle: "fixture", at: at.addingTimeInterval(1), now: at.addingTimeInterval(1))
                tracker.consume(result, bundle: "fixture", at: at.addingTimeInterval(2), now: at.addingTimeInterval(2))
                XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at.addingTimeInterval(2)))
            }
    }

    func testEndpointExactlyAt300mConsumesOnCertifiedChildBeforeJitter() throws {
        try fixture(topology + target + """
            UPDATE upcoming_path_segment SET end_chainage_m=400,length_m=400 WHERE segment_id=1;
            UPDATE traffic_sign_association SET station_chainage_m=400;
            UPDATE traffic_sign_way_rule SET station_chainage_m=400,start_chainage_m=400,end_chainage_m=400;
            INSERT INTO traffic_sign_way_rule VALUES('child','speed',102,-1,200,0,200,70,'accepted','all');
            """) { resources, db in
                let result = try XCTUnwrap(lookup(resources, db))
                XCTAssertEqual(result.candidates.first?.distanceM, 300)
                XCTAssertEqual(result.path.last?.wayID, "102")
                var tracker = UpcomingSpeedLimitTracker()
                let at = Date(timeIntervalSince1970: 1000)
                tracker.consume(result, bundle: "fixture", at: at, now: at)
                let after = try XCTUnwrap(lookup(resources, db, way: "102", direction: -1, chainage: 199))
                tracker.consume(after, bundle: "fixture", at: at.addingTimeInterval(1), now: at.addingTimeInterval(1))
                tracker.consume(result, bundle: "fixture", at: at.addingTimeInterval(2), now: at.addingTimeInterval(2))
                XCTAssertNil(tracker.selection(currentKmh: 100, unlimited: false, currentIsStale: false, now: at.addingTimeInterval(2)))
            }
    }

    func testExistingPrimaryInventoryResolverOwnsContinuedEndpointOffer() throws {
        let columns = """
            ALTER TABLE traffic_sign_runtime ADD COLUMN record_key TEXT DEFAULT 'fixture';
            ALTER TABLE traffic_sign_runtime ADD COLUMN normalized_code TEXT;
            ALTER TABLE traffic_sign_runtime ADD COLUMN lon REAL DEFAULT 0;
            ALTER TABLE traffic_sign_runtime ADD COLUMN lat REAL DEFAULT 0;
            ALTER TABLE traffic_sign_runtime ADD COLUMN orientation_deg REAL;
            ALTER TABLE traffic_sign_runtime ADD COLUMN display_radius_m REAL DEFAULT 10;
            ALTER TABLE traffic_sign_runtime ADD COLUMN pictogram_code TEXT;
            ALTER TABLE traffic_sign_runtime ADD COLUMN pictogram_path TEXT;
            ALTER TABLE traffic_sign_runtime ADD COLUMN model_classes_json TEXT DEFAULT '[]';
            ALTER TABLE traffic_sign_way_rule ADD COLUMN local_heading_deg REAL;
            ALTER TABLE traffic_sign_way_rule ADD COLUMN inside_city INTEGER;
            ALTER TABLE traffic_sign_association ADD COLUMN local_heading_deg REAL;
            ALTER TABLE traffic_sign_association ADD COLUMN confidence REAL;
            ALTER TABLE traffic_sign_association ADD COLUMN evidence_json TEXT;
            """
        try fixture(target + """
            UPDATE traffic_sign_association SET station_chainage_m=150;
            UPDATE traffic_sign_way_rule SET station_chainage_m=150,start_chainage_m=150,end_chainage_m=150;
            INSERT INTO traffic_sign_way_rule VALUES('child','speed',102,-1,200,0,200,70,'accepted','all');
            """ + columns) { _, db in
                let before = try XCTUnwrap(InventorySignBundle.lookup(db: db, lat: 0, lon: 100 / 111195.08,
                    wayID: "101", points: [(0, 0), (0, 0.01)], heading: 90, headingAccuracy: 5, accuracy: 5))
                XCTAssertNil(before.activeRule)
                let after = try XCTUnwrap(InventorySignBundle.lookup(db: db, lat: 0, lon: 100 / 111195.08,
                    wayID: "102", points: [(0, 0), (0, 0.01)], heading: 270, headingAccuracy: 5, accuracy: 5))
                XCTAssertEqual(after.activeRule?.speedKmh, 70)
                XCTAssertEqual(after.activeRule?.signID, "speed")
            }
    }

    func testZeroLengthAndShadowedOriginCannotPromiseHandoff() throws {
        for additional in ["UPDATE traffic_sign_way_rule SET end_chainage_m=start_chainage_m;", "INSERT INTO traffic_sign_way_rule SELECT 'overlap',sign_id,way_id,direction,station_chainage_m,start_chainage_m,end_chainage_m,30,association_status,lane_scope FROM traffic_sign_way_rule;"] {
            try fixture(target + additional) { resources, db in
                XCTAssertTrue(try XCTUnwrap(lookup(resources, db)).candidates.isEmpty)
            }
        }
    }
}

extension UpcomingSpeedLimitTests {
    /// Explicit physical acceptance only. Reads the installed full bundle without
    /// changing driver settings, injecting GPS, starting capture or offering policy input.
    @MainActor
    func testPhysicalInstalledFullBWLookaheadPerformance() async throws {
#if targetEnvironment(simulator)
        throw XCTSkip("Physical installed full-bundle acceptance only")
#else
        struct Cases: Decodable {
            struct Item: Decodable {
                let id: String; let wayID: String; let direction: Int; let chainageM: Double
                let points: [[Double]]; let lat: Double; let lon: Double; let headingDeg: Double
                let relationGroupIDs: [Int]; let expectedSignID: String; let expectedSpeedKmh: Int
                let expectedDistanceM: Double; let expectedOriginWayID: String
            }
            let cases: [Item]
        }
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let casesURL = documents.appendingPathComponent("upcoming-physical-cases.json")
        guard FileManager.default.fileExists(atPath: casesURL.path) else {
            throw XCTSkip("Explicit physical source-backed case staging is absent")
        }
        let manager = V3BundleManager()
        let active = try await manager.activeState()
        XCTAssertEqual(active?.bundleVersion, "2026-10-23-v1.5-lookahead")
        let databaseValue = try await manager.activeDatabaseURL()
        let database = try XCTUnwrap(databaseValue)
        let bytes = try database.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        XCTAssertEqual(bytes, 3_099_021_312)
        let cases = try JSONDecoder().decode(Cases.self, from: Data(contentsOf: casesURL)).cases
        XCTAssertGreaterThanOrEqual(cases.count, 5)
        UIDevice.current.isBatteryMonitoringEnabled = true
        let startBattery = UIDevice.current.batteryLevel
        let startThermal = ProcessInfo.processInfo.thermalState.rawValue
        func milliseconds(_ start: UInt64) -> Double { Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000 }
        func stats(_ values: [Double]) -> [String: Any] {
            let sorted = values.sorted()
            guard !sorted.isEmpty else { return ["count": 0] }
            func at(_ p: Double) -> Double { sorted[min(sorted.count - 1, max(0, Int(ceil(p * Double(sorted.count))) - 1))] }
            return ["count": sorted.count, "p50_ms": at(0.50), "p95_ms": at(0.95), "p99_ms": at(0.99),
                    "max_ms": sorted.last!, "over_25ms": sorted.filter { $0 > 25 }.count]
        }
        var rows: [[String: Any]] = [], handoffs: [[String: Any]] = []
        var coldWall: [Double] = [], coldInternal: [Double] = [], warmWall: [Double] = [], warmInternal: [Double] = []
        var serviceWall: [Double] = [], serviceColdWall: [Double] = []
        var failures = 0, nilResults = 0, budgetStops = 0, serviceFailures = 0
        var serviceSelectedRoadFailures = 0, serviceNoRoadVisible = 0, serviceKnownRoad = 0
        func check(_ snapshot: UpcomingSpeedLimitSnapshot?, item: Cases.Item) -> Bool {
            guard let snapshot, snapshot.topologyAvailable,
                  let candidate = snapshot.candidates.first(where: { $0.signID == item.expectedSignID }) else { return false }
            return candidate.speedKmh == item.expectedSpeedKmh && candidate.originWayID == item.expectedOriginWayID
                && abs(candidate.distanceM - item.expectedDistanceM) <= 0.25
        }
        for item in cases {
            let points = item.points.map { ($0[0], $0[1]) }
            let inventory = InventorySignLookup(signs: [], activeRule: nil, wayID: item.wayID,
                                               direction: item.direction, chainageM: item.chainageM)
            // Every first/fresh connection is retained, including suppressed results.
            for iteration in 0..<10 {
                let resources = V3LookupResources(path: database.path)
                let opening = DispatchTime.now().uptimeNanoseconds
                let session = try resources.acquire()
                let openMs = milliseconds(opening)
                let wall = DispatchTime.now().uptimeNanoseconds
                let snapshot = UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources,
                    inventory: inventory, points: points, relationGroupIDs: item.relationGroupIDs)
                let wallMs = milliseconds(wall)
                resources.releaseSession()
                let correct = check(snapshot, item: item)
                if !correct { failures += 1 }
                if snapshot == nil { nilResults += 1 }
                if snapshot?.reason == "budget_exceeded" { budgetStops += 1 }
                coldWall.append(wallMs); if let internalMs = snapshot?.queryTimeMs { coldInternal.append(internalMs) }
                rows.append(["case": item.id, "phase": "fresh_connection", "iteration": iteration,
                    "open_ms": openMs, "wall_ms": wallMs, "query_ms": snapshot?.queryTimeMs as Any? ?? NSNull(),
                    "reason": snapshot?.reason ?? "nil", "correct": correct,
                    "sign_id": snapshot?.candidates.first?.signID as Any? ?? NSNull()])
                resources.invalidate()
            }
            let resources = V3LookupResources(path: database.path)
            let session = try resources.acquire()
            let warmupStart = DispatchTime.now().uptimeNanoseconds
            let warmup = UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources,
                inventory: inventory, points: points, relationGroupIDs: item.relationGroupIDs)
            let warmupCorrect = check(warmup, item: item)
            if !warmupCorrect { failures += 1 }
            if warmup == nil { nilResults += 1 }
            if warmup?.reason == "budget_exceeded" { budgetStops += 1 }
            rows.append(["case": item.id, "phase": "warmup", "iteration": 0,
                "wall_ms": milliseconds(warmupStart), "query_ms": warmup?.queryTimeMs as Any? ?? NSNull(),
                "reason": warmup?.reason ?? "nil", "correct": warmupCorrect])
            for iteration in 0..<30 {
                let wall = DispatchTime.now().uptimeNanoseconds
                let snapshot = UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources,
                    inventory: inventory, points: points, relationGroupIDs: item.relationGroupIDs)
                let wallMs = milliseconds(wall), correct = check(snapshot, item: item)
                if !correct { failures += 1 }
                if snapshot == nil { nilResults += 1 }
                if snapshot?.reason == "budget_exceeded" { budgetStops += 1 }
                warmWall.append(wallMs); if let internalMs = snapshot?.queryTimeMs { warmInternal.append(internalMs) }
                rows.append(["case": item.id, "phase": "warm", "iteration": iteration,
                    "wall_ms": wallMs, "query_ms": snapshot?.queryTimeMs as Any? ?? NSNull(),
                    "reason": snapshot?.reason ?? "nil", "correct": correct,
                    "sign_id": snapshot?.candidates.first?.signID as Any? ?? NSNull()])
            }
            if cases.prefix(5).contains(where: { $0.id == item.id }) {
            let initial = try XCTUnwrap(UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources,
                inventory: inventory, points: points, relationGroupIDs: item.relationGroupIDs))
            let target = try XCTUnwrap(initial.candidates.first { $0.signID == item.expectedSignID })
            // Locate the actual source geometry after the physical station; prove the
            // main production resolver now offers exactly the previewed speed/sign.
            var statement: OpaquePointer?
            XCTAssertEqual(sqlite3_prepare_v2(session.db, "SELECT points_json FROM way_geom WHERE way_id=?", -1, &statement, nil), SQLITE_OK)
            let q = try XCTUnwrap(statement)
            XCTAssertEqual(sqlite3_bind_int64(q, 1, Int64(item.expectedOriginWayID)!), SQLITE_OK)
            XCTAssertEqual(sqlite3_step(q), SQLITE_ROW)
            let raw = String(cString: sqlite3_column_text(q, 0)); sqlite3_finalize(q)
            let targetPoints = try JSONDecoder().decode([[Double]].self, from: Data(raw.utf8)).map { ($0[0], $0[1]) }
            let targetLength = zip(targetPoints, targetPoints.dropFirst()).reduce(0.0) {
                $0 + InventorySignBundle.distance($1.0.0, $1.0.1, $1.1.0, $1.1.1) * (6_371_000 / 6_371_008.8)
            }
            let postStation = min(targetLength - 0.01, max(0.01, target.stationM + Double(target.direction) * 1))
            var remaining = postStation, fix: (Double, Double, Double)?
            for (a, b) in zip(targetPoints, targetPoints.dropFirst()) {
                let length = InventorySignBundle.distance(a.0, a.1, b.0, b.1) * (6_371_000 / 6_371_008.8)
                if remaining <= length && length > 0 {
                    let fraction = remaining / length, lat = a.0 + (b.0 - a.0) * fraction, lon = a.1 + (b.1 - a.1) * fraction
                    let heading = (atan2((b.1 - a.1) * cos(lat * .pi / 180), b.0 - a.0) * 180 / .pi + 360
                        + (target.direction == 1 ? 0 : 180)).truncatingRemainder(dividingBy: 360)
                    fix = (lat, lon, heading); break
                }
                remaining -= length
            }
            let post = try XCTUnwrap(fix)
            let offer = try XCTUnwrap(InventorySignBundle.lookup(db: session.db, lat: post.0, lon: post.1,
                wayID: target.originWayID, points: targetPoints, heading: post.2, headingAccuracy: 5, accuracy: 5))
            XCTAssertEqual(offer.activeRule?.signID, item.expectedSignID)
            XCTAssertEqual(offer.activeRule?.speedKmh, item.expectedSpeedKmh)
            let after = UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources, inventory: offer,
                points: targetPoints, relationGroupIDs: item.relationGroupIDs)
            XCTAssertFalse(after?.candidates.contains(where: { $0.signID == item.expectedSignID }) ?? true)
            var tracker = UpcomingSpeedLimitTracker()
            let now = Date()
            tracker.consume(initial, bundle: active!.bundleVersion, at: now, now: now)
            XCTAssertEqual(tracker.selection(currentKmh: 300, unlimited: false, currentIsStale: false, now: now)?.signID, item.expectedSignID)
            tracker.consume(after, bundle: active!.bundleVersion, at: now.addingTimeInterval(1), now: now.addingTimeInterval(1))
            XCTAssertNotEqual(tracker.selection(currentKmh: item.expectedSpeedKmh, unlimited: false, currentIsStale: false, now: now.addingTimeInterval(1))?.signID, item.expectedSignID)
            handoffs.append(["case": item.id, "sign_id": item.expectedSignID, "speed_kmh": item.expectedSpeedKmh,
                "post_station_m": postStation, "main_offer_sign": offer.activeRule?.signID as Any? ?? NSNull(),
                "main_offer_speed": offer.activeRule?.speedKmh as Any? ?? NSNull(), "preview_dropped": true])
            }
            resources.releaseSession(); resources.invalidate()
            let service = V3SpeedLimitService(dbPath: database.path, countryCode: "DEU")
            let context = WayMatchContext(preferredWayID: item.wayID, recentWayIDs: [item.wayID],
                preferredStreetRef: nil, recentStreetRefs: [], matchedFixCount: 3)
            for iteration in 0..<31 {
                let start = DispatchTime.now().uptimeNanoseconds
                let result = try service.lookupSpeedLimit(lat: item.lat, lon: item.lon, matchContext: context,
                    headingDeg: item.headingDeg, headingAccuracyDeg: 5, speedKmh: 35, horizontalAccuracyM: 5)
                let elapsed = milliseconds(start), correct = result.wayID == item.wayID && check(result.upcomingSpeedLimits, item: item)
                if !correct { serviceFailures += 1 }
                if result.wayID == item.wayID {
                    serviceKnownRoad += 1
                    if !check(result.upcomingSpeedLimits, item: item) { serviceSelectedRoadFailures += 1 }
                }
                if result.wayID == nil && !(result.upcomingSpeedLimits?.candidates.isEmpty ?? true) { serviceNoRoadVisible += 1 }
                if iteration == 0 { serviceColdWall.append(elapsed) } else { serviceWall.append(elapsed) }
                rows.append(["case": item.id, "phase": iteration == 0 ? "full_service_fresh_connection" : "full_service_warm",
                    "iteration": iteration, "wall_ms": elapsed, "query_ms": result.upcomingSpeedLimits?.queryTimeMs as Any? ?? NSNull(),
                    "correct": correct, "matched_way": result.wayID as Any? ?? NSNull(),
                    "reason": result.upcomingSpeedLimits?.reason ?? "nil",
                    "preview_sign": result.upcomingSpeedLimits?.candidates.first?.signID as Any? ?? NSNull(),
                    "classification": result.wayID == item.wayID ? (correct ? "expected_road_and_preview" : "expected_road_preview_mismatch")
                        : (result.wayID == nil ? "matcher_no_selected_road" : "matcher_selected_different_road")])
            }
        }
        // Hash after latency samples: the verification scan must not precede first-connection samples.
        var digest = SHA256(), hashBytes = 0
        let handle = try FileHandle(forReadingFrom: database)
        while let chunk = try handle.read(upToCount: 4 * 1024 * 1024), !chunk.isEmpty { digest.update(data: chunk); hashBytes += chunk.count }
        try handle.close()
        let hash = digest.finalize().map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(hash, "34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c")
        XCTAssertEqual(hashBytes, bytes)
        let report: [String: Any] = ["format": "youspeed.upcoming.physical.iphone.v1", "device_model": UIDevice.current.model,
            "os_version": UIDevice.current.systemVersion, "app_version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "",
            "app_build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") ?? "", "bundle_version": active!.bundleVersion,
            "database_bytes": bytes, "database_sha256": hash, "database_path": database.path,
            "case_count": cases.count, "direct_attempts": coldWall.count + warmWall.count + cases.count,
            "warmup_attempts": cases.count,
            "direct_failures": failures, "direct_nil_results": nilResults, "direct_budget_stops": budgetStops,
            "service_attempts": serviceWall.count + serviceColdWall.count, "service_expected_case_mismatches": serviceFailures,
            "service_expected_road_attempts": serviceKnownRoad, "service_preview_failures_on_expected_road": serviceSelectedRoadFailures,
            "service_preview_visible_without_selected_road": serviceNoRoadVisible,
            "service_scope": "Controlled coordinates with preferredWayID and matchedFixCount=3; production corridor matcher still chooses/admit roads. All mismatches retained and classified, not counted as preview success.",
            "fresh_connection_wall": stats(coldWall), "fresh_connection_query": stats(coldInternal),
            "warm_wall": stats(warmWall), "warm_query": stats(warmInternal),
            "full_service_fresh_connection_wall": stats(serviceColdWall), "full_service_warm_wall": stats(serviceWall),
            "thermal_start": startThermal, "thermal_end": ProcessInfo.processInfo.thermalState.rawValue,
            "battery_start": startBattery, "battery_end": UIDevice.current.batteryLevel,
            "battery_state": UIDevice.current.batteryState.rawValue,
            "sqlite_version": String(cString: sqlite3_libversion()), "connection": "mode=ro&immutable=1; V3LookupResources production defaults",
            "storage_cache": "Uncontrolled OS cache; fresh connection does not mean storage cold. No global caches dropped. Hash scan performed after samples.",
            "controlled_replay": true, "real_driving": false, "handoffs": handoffs, "samples": rows]
        let output = documents.appendingPathComponent("upcoming-physical-performance.json")
        try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted]).write(to: output, options: .atomic)
        print("UPCOMING_PHYSICAL_IPHONE " + String(data: try JSONSerialization.data(withJSONObject: [
            "direct_failures": failures, "service_failures": serviceFailures, "warm": stats(warmWall),
            "fresh_connection": stats(coldWall), "full_service": stats(serviceWall)], options: [.sortedKeys]), encoding: .utf8)!)
        XCTAssertEqual(failures, 0)
        XCTAssertEqual(serviceSelectedRoadFailures, 0)
        XCTAssertEqual(serviceNoRoadVisible, 0)
        XCTAssertGreaterThanOrEqual(serviceKnownRoad, (cases.count - 5) * 31)
#endif
    }
}

extension UpcomingSpeedLimitTests {
    /// Offline integration replay through normal startup, bundle routing, worker,
    /// matcher, inventory, effective reference and preview publication. No main
    /// limit or upcoming snapshot is manually seeded.
    @MainActor
    func testFullBWRealControllerPublishesLowerUpcomingLimit() async throws {
#if !targetEnvironment(simulator)
        throw XCTSkip("Isolated simulator investigation while physical phones are away")
#else
        struct Cases: Decodable {
            struct Item: Decodable { let id: String; let wayID: String; let lat: Double; let lon: Double; let headingDeg: Double; let expectedSignID: String; let expectedSpeedKmh: Int; let points: [[Double]]; let chainageM: Double; let direction: Int }
            let cases: [Item]
        }
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let fullDB = repo.appendingPathComponent("mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite")
        guard FileManager.default.fileExists(atPath: fullDB.path) else { throw XCTSkip("Local full BW lookahead bundle unavailable") }
        let cases = try JSONDecoder().decode(Cases.self, from: Data(contentsOf: repo.appendingPathComponent("output/upcoming-speed-limit-physical-10059/iphone/physical-cases.json"))).cases
        let item = try XCTUnwrap(cases.first { $0.id == "bw-cross-way-3" })
        let fm = FileManager.default, support = try V3BundleManager.applicationSupportDirectory()
        let activeURL = support.appendingPathComponent("active_bundle.json")
        let originalActive = try? Data(contentsOf: activeURL)
        let bundleRoot = support.appendingPathComponent("bundles")
        let existing = (try? fm.contentsOfDirectory(at: bundleRoot, includingPropertiesForKeys: nil)) ?? []
        let manifests: [(URL, Data)] = existing.compactMap { directory in
            let url = directory.appendingPathComponent("bundle-manifest.v3.json")
            return (try? Data(contentsOf: url)).map { (url, $0) }
        }
        let fixture = bundleRoot.appendingPathComponent("baden-wuerttemberg-offline-controller-\(UUID().uuidString)")
        let manifestURL = fixture.appendingPathComponent("bundle-manifest.v3.json")
        defer {
            try? fm.removeItem(at: manifestURL)
            for (url, data) in manifests { try? data.write(to: url, options: .atomic) }
            if let originalActive { try? originalActive.write(to: activeURL, options: .atomic) }
            else { try? fm.removeItem(at: activeURL) }
            try? fm.removeItem(at: fixture)
        }
        for (url, _) in manifests { try fm.removeItem(at: url) }
        try fm.createDirectory(at: fixture, withIntermediateDirectories: true)
        let dbURL = fixture.appendingPathComponent("baden-wuerttemberg_speeds.sqlite")
        try fm.copyItem(at: fullDB, to: dbURL)
        try Data(contentsOf: repo.appendingPathComponent("mapdata/bundles/v3/baden-wuerttemberg/2026-10-23-v1.5-lookahead/baden-wuerttemberg_manifest.json")).write(to: manifestURL)
        let active = ActiveBundleState(region: "baden-wuerttemberg", bundleVersion: "2026-10-23-v1.5-lookahead",
            dbFileName: dbURL.lastPathComponent, activatedAtUTC: "2026-10-23T08:00:00Z", dbPath: dbURL.path,
            dbSHA256: "34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c")
        try JSONEncoder().encode(active).write(to: activeURL, options: .atomic)
        let model = DriveSessionViewModel()
        Self.controllerLifetimes.append(model)
        defer { model.stopDriving() }
        model.setDebugLoggingEnabled(true)
        model.matcherDebugProfile = .m7
        for _ in 0..<200 where model.startupLogReviewState == .checking {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        if model.startupLogReviewState == .choice || model.startupLogReviewState == .failed { model.keepStartupLogs() }
        try await model.testWaitForStartupDataLoad(timeout: 60)
        await model.testRefreshBundleInventory()
        XCTAssertEqual(model.activeBundleVersion, active.bundleVersion)
        var samples: [[String: Any]] = []
        for index in 0..<15 {
            await model.testRunGPSLookup(latitude: item.lat, longitude: item.lon,
                headingDegrees: item.headingDeg, speedKmh: 35)
            let sample: [String: Any] = ["fix": index, "way": model.limitWayID as Any? ?? NSNull(),
                "main_kmh": model.speedLimitKmh as Any? ?? NSNull(), "source": model.effectiveSpeedLimitState.source.rawValue,
                "preview_sign": model.upcomingSpeedLimit?.signID as Any? ?? NSNull(),
                "preview_kmh": model.upcomingSpeedLimit?.speedKmh as Any? ?? NSNull(),
                "distance_m": model.upcomingSpeedLimit?.distanceM as Any? ?? NSNull(),
                "status": model.lastLookupStatus, "error": model.lastError,
                "bundle": model.activeBundleVersion, "generation": model.testUpcomingGeneration,
                "diagnostics": model.testUpcomingDiagnosticState]
            samples.append(sample)
            print("UPCOMING_FULL_CONTROLLER " + String(data: try JSONSerialization.data(withJSONObject: sample, options: [.sortedKeys]), encoding: .utf8)!)
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        let target = try XCTUnwrap(model.upcomingSpeedLimit)
        func projectedFix(_ chainage: Double, _ rows: [[Double]], _ direction: Int) throws -> (Double, Double, Double) {
            var remaining = chainage
            for (a, b) in zip(rows, rows.dropFirst()) {
                let length = InventorySignBundle.distance(a[0], a[1], b[0], b[1]) * (6_371_000 / 6_371_008.8)
                if remaining <= length && length > 0 {
                    let f = remaining / length, lat = a[0] + (b[0] - a[0]) * f, lon = a[1] + (b[1] - a[1]) * f
                    let heading = (atan2((b[1] - a[1]) * cos(lat * .pi / 180), b[0] - a[0]) * 180 / .pi + 360
                        + (direction == 1 ? 0 : 180)).truncatingRemainder(dividingBy: 360)
                    return (lat, lon, heading)
                }
                remaining -= length
            }
            throw ConsumerAppError.io("Controller replay station outside source geometry")
        }
        var approach: [[String: Any]] = []
        for advance in [10.0, 20.0] {
            let fix = try projectedFix(item.chainageM + Double(item.direction) * advance, item.points, item.direction)
            await model.testRunGPSLookup(latitude: fix.0, longitude: fix.1, headingDegrees: fix.2, speedKmh: 35)
            approach.append(["phase": "approach", "advance_m": advance, "main_kmh": model.speedLimitKmh as Any? ?? NSNull(),
                "preview_sign": model.upcomingSpeedLimit?.signID as Any? ?? NSNull(),
                "distance_m": model.upcomingSpeedLimit?.distanceM as Any? ?? NSNull(), "way": model.limitWayID as Any? ?? NSNull(),
                "diagnostics": model.testUpcomingDiagnosticState])
            XCTAssertEqual(model.upcomingSpeedLimit?.signID, item.expectedSignID)
            XCTAssertEqual(model.upcomingSpeedLimit?.distanceM ?? -1, target.distanceM - advance, accuracy: 0.25)
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        var pointer: OpaquePointer?
        XCTAssertEqual(sqlite3_open_v2(dbURL.path, &pointer, SQLITE_OPEN_READONLY, nil), SQLITE_OK)
        let db = try XCTUnwrap(pointer); defer { sqlite3_close(db) }
        var statement: OpaquePointer?
        XCTAssertEqual(sqlite3_prepare_v2(db, "SELECT points_json FROM way_geom WHERE way_id=?", -1, &statement, nil), SQLITE_OK)
        let q = try XCTUnwrap(statement)
        XCTAssertEqual(sqlite3_bind_int64(q, 1, Int64(target.originWayID)!), SQLITE_OK)
        XCTAssertEqual(sqlite3_step(q), SQLITE_ROW)
        let raw = String(cString: sqlite3_column_text(q, 0)); sqlite3_finalize(q)
        let targetRows = try JSONDecoder().decode([[Double]].self, from: Data(raw.utf8))
        for (index, advance) in [-5.0, 1.0, 5.0, 5.0, 5.0].enumerated() {
            let fix = try projectedFix(target.stationM + Double(target.direction) * advance, targetRows, target.direction)
            await model.testRunGPSLookup(latitude: fix.0, longitude: fix.1, headingDegrees: fix.2, speedKmh: 35)
            approach.append(["phase": "origin_way", "fix": index, "past_station_m": advance,
                "main_kmh": model.speedLimitKmh as Any? ?? NSNull(), "source": model.effectiveSpeedLimitState.source.rawValue,
                "preview_sign": model.upcomingSpeedLimit?.signID as Any? ?? NSNull(),
                "distance_m": model.upcomingSpeedLimit?.distanceM as Any? ?? NSNull(), "way": model.limitWayID as Any? ?? NSNull(),
                "diagnostics": model.testUpcomingDiagnosticState])
            if advance > 0 { XCTAssertNotEqual(model.upcomingSpeedLimit?.signID, item.expectedSignID) }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        let tsr = (try? String(contentsOfFile: model.tsrLogPath, encoding: .utf8)) ?? ""
        let report: [String: Any] = ["format": "youspeed.upcoming.offline.controller.v1", "case": item.id,
            "full_db_bytes": try fullDB.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0,
            "matcher": model.matcherDebugProfile.rawValue, "samples": samples, "approach": approach,
            "upcoming_diagnostics": tsr.components(separatedBy: "\n").filter { $0.contains("upcoming_speed_limit") },
            "controlled_gps_replay": true, "main_or_upcoming_manually_injected": false]
        let destination = fm.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("upcoming-full-controller.json")
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: destination)
        XCTAssertEqual(model.limitWayID, target.originWayID)
        XCTAssertEqual(model.speedLimitKmh, item.expectedSpeedKmh)
        XCTAssertNotEqual(model.upcomingSpeedLimit?.signID, item.expectedSignID)
#endif
    }
}


extension UpcomingSpeedLimitTests {
    /// Public source-derived long approaches through the existing full BW bundle.
    /// This reads the DB in place; it does not install a bundle or inject controller state.
    func testOptionalRealBWLongHorizonReaderAndBothServiceBranches() throws {
        struct Cases: Decodable {
            struct Item: Decodable {
                let id: String; let wayID: String; let direction: Int; let chainageM: Double
                let points: [[Double]]; let lat: Double; let lon: Double; let headingDeg: Double
                let relationGroupIDs: [Int]; let expectedSignID: String; let expectedSpeedKmh: Int
                let expectedDistanceM: Double; let expectedOriginWayID: String; let drivingSpeedKmh: Double
            }
            let cases: [Item]
        }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let directory = root.appendingPathComponent("output/upcoming-speed-limit-adaptive-horizon-2026-10-23")
        let database = root.appendingPathComponent("mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite")
        let caseFile = directory.appendingPathComponent("long-horizon-cases.json")
        guard FileManager.default.fileExists(atPath: database.path), FileManager.default.fileExists(atPath: caseFile.path) else {
            throw XCTSkip("Optional public BW long-approach evidence is not present")
        }
        let cases = try JSONDecoder().decode(Cases.self, from: Data(contentsOf: caseFile)).cases
        XCTAssertGreaterThanOrEqual(cases.count, 20)
        let resources = V3LookupResources(path: database.path)
        let session = try resources.acquire()
        defer { resources.releaseSession() }
        var samples: [Double] = []
        var budgetMisses = 0
        for item in cases {
            for iteration in 0..<3 {
                func read() throws -> UpcomingSpeedLimitSnapshot {
                    try XCTUnwrap(UpcomingSpeedLimitBundle.lookup(db: session.db, resources: resources,
                        inventory: .init(signs: [], activeRule: nil, wayID: item.wayID, direction: item.direction, chainageM: item.chainageM),
                        points: item.points.map { ($0[0], $0[1]) }, relationGroupIDs: item.relationGroupIDs,
                        speedKmh: item.drivingSpeedKmh))
                }
                var snapshot = try read()
                // A cold read or host scheduling pause may consume the production
                // 25 ms budget. It must return no partial promise; the next fix
                // retries normally. Keep misses in the measured warm samples.
                if snapshot.reason == "budget_exceeded" {
                    budgetMisses += 1
                    XCTAssertTrue(snapshot.candidates.isEmpty, item.id)
                    if iteration > 0 { samples.append(snapshot.queryTimeMs) }
                    snapshot = try read()
                }
                let target = try XCTUnwrap(snapshot.candidates.first { $0.signID == item.expectedSignID }, item.id + ": " + snapshot.reason)
                XCTAssertGreaterThan(target.distanceM, 300, item.id)
                XCTAssertEqual(target.distanceM, item.expectedDistanceM, accuracy: 0.25, item.id)
                XCTAssertEqual(target.speedKmh, item.expectedSpeedKmh, item.id)
                XCTAssertEqual(target.originWayID, item.expectedOriginWayID, item.id)
                XCTAssertEqual(snapshot.lookaheadDistanceM, UpcomingSpeedLimitHorizon.distanceM(speedKmh: item.drivingSpeedKmh))
                if iteration > 0 { samples.append(snapshot.queryTimeMs) }
            }
        }
        let item = try XCTUnwrap(cases.first { $0.id == "bw-long-horizon-3" })
        for model: V3SpeedLimitService.MatchingModel in [.corridorHMM, .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic] {
            let service = V3SpeedLimitService(dbPath: database.path, countryCode: "DEU", matchingModel: model)
            defer { service.invalidateDatabase() }
            let context = WayMatchContext(preferredWayID: item.wayID, recentWayIDs: [item.wayID],
                preferredStreetRef: nil, recentStreetRefs: [], matchedFixCount: 3)
            let result = try service.lookupSpeedLimit(lat: item.lat, lon: item.lon, matchContext: context,
                headingDeg: item.headingDeg, headingAccuracyDeg: 5, speedKmh: item.drivingSpeedKmh, horizontalAccuracyM: 5)
            let snapshot = try XCTUnwrap(result.upcomingSpeedLimits, "\(model): expected observed-speed preview context")
            XCTAssertEqual(snapshot.lookaheadDistanceM, UpcomingSpeedLimitHorizon.distanceM(speedKmh: item.drivingSpeedKmh), "\(model)")
            XCTAssertEqual(result.wayID, item.wayID, "\(model)")
            XCTAssertTrue(snapshot.candidates.contains { $0.signID == item.expectedSignID }, "\(model): \(snapshot.reason)")
        }
        let sorted = samples.sorted()
        print("UPCOMING_BW_LONG_NATIVE cases=\(cases.count) warm_samples=\(sorted.count) budget_misses=\(budgetMisses) p95_ms=\(sorted[Int(Double(sorted.count - 1) * 0.95)]) max_ms=\(sorted.last!) full_db_bytes=3099021312")
    }
}

import XCTest
import SQLite3
@testable import SpeedConsumer

final class MapDataAmendmentStoreTests: XCTestCase {
    private let baseIdentity = "ysp-base-v1:" + String(repeating: "a", count: 64) + ":" + String(repeating: "b", count: 64) + ":" + String(repeating: "c", count: 64)
    private let rules = #"{"version":1,"grammar":"youspeed-osm-speed-1","tags":[{"key":"maxspeed","raw":"50","role":"speed","vehicle":"all","direction":0,"priority":0,"conditional":false,"status":"supported","clauses":[{"limit":{"kind":"numeric","kmh":50},"condition":{"kind":"true"}}]},{"key":"maxspeed:conditional","raw":"30 @ (wet)","role":"speed","vehicle":"all","direction":0,"priority":0,"conditional":true,"status":"supported","clauses":[{"limit":{"kind":"numeric","kmh":30},"condition":{"kind":"context","field":"wet"}}]}]}"#

    private func record(id: String = "source:10") -> MapDataAmendment {
        MapDataAmendment(id: id, sourceNamespace: "osm", entity: "way", sourceID: "10",
            basisBundle: baseIdentity, originalBundle: baseIdentity, sourceRevision: "source:10:revision:7",
            rulesJSON: rules, rawSourceTags: ["maxspeed": "50", "maxspeed:conditional": "30 @ (wet)"],
            author: "unit-test", evidenceID: "review:1")
    }

    private func run(_ body: (MapDataAmendmentStore, URL) throws -> Void) throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        try body(MapDataAmendmentStore(directory: directory), directory)
    }

    private func resolve(_ store: MapDataAmendmentStore, wet: Bool? = true, direction: Int? = 1,
                         at: Double = 150, passed: Set<String> = []) throws -> ConditionalSpeedRules.Result? {
        var context = ConditionalSpeedRules.Context(at: Date(timeIntervalSince1970: at), direction: direction)
        if let wet { context.facts["wet"] = wet }
        return try store.resolve(wayID: "10", bundle: baseIdentity, direction: direction,
            context: context, baseKmh: 50, baseUnlimited: false, passedNodeIDs: passed)
    }

    func testPersistentRestrictedAmendmentCASAndTombstone() throws {
        try run { store, directory in
            let original = try store.put(record(), expectedRevision: 0)
            XCTAssertEqual(original.revision, 1)
            XCTAssertThrowsError(try store.put(record(), expectedRevision: 0))
            let changed = try store.amendNumericLimit(original.id, expectedRevision: 1,
                tagKey: "maxspeed:conditional", clauseIndex: 0, kmh: 25)
            XCTAssertEqual(changed.rawSourceTags, original.rawSourceTags)
            let reopened = MapDataAmendmentStore(directory: directory)
            XCTAssertEqual(try resolve(reopened)?.kmh, 25)
            XCTAssertEqual(try resolve(reopened, wet: false)?.kmh, 50)
            XCTAssertEqual(try resolve(reopened, wet: nil)?.unresolved, true)
            XCTAssertEqual(try reopened.history(original.id).count, 2)
            _ = try reopened.tombstone(original.id, expectedRevision: 2)
            XCTAssertNil(try resolve(MapDataAmendmentStore(directory: directory)))
            XCTAssertEqual(try reopened.history(original.id).map(\.operation), ["upsert", "upsert", "tombstone"])
        }
    }

    func testValiditySurvivesReevaluationAndUnknownDirectionCannotApply() throws {
        try run { store, _ in
            var value = record(); value.validFromUTC = 100; value.validUntilUTC = 200
            _ = try store.put(value, expectedRevision: 0)
            let inside = try XCTUnwrap(resolve(store))
            XCTAssertEqual(inside.kmh, 30)
            XCTAssertEqual(inside.reevaluation?.evaluate(at: Date(timeIntervalSince1970: 200)).kmh, 50)
            var unknownFallback = try XCTUnwrap(inside.reevaluation)
            unknownFallback.fallbackUnresolved = true; unknownFallback.fallbackReason = "electronic_sign_state_unknown"
            XCTAssertTrue(unknownFallback.evaluate(at: Date(timeIntervalSince1970: 200)).unresolved)
            unknownFallback.fallbackRulesJSON = "invalid"
            XCTAssertEqual(unknownFallback.evaluate(at: Date(timeIntervalSince1970: 200)).reason, "corrupt_fallback_rule_set")
            XCTAssertNil(try resolve(store, at: 200))
            value.direction = 1; _ = try store.put(value, expectedRevision: 1)
            XCTAssertEqual(try resolve(store, direction: nil)?.unresolved, true)
            XCTAssertNil(try resolve(store, direction: -1))
        }
    }

    func testNodeNeedsCurrentDrivePassageInAdditionToHistoricalEvidence() throws {
        try run { store, _ in
            var value = MapDataAmendment(id: "node:9007199254740993", sourceNamespace: "osm", entity: "node",
                sourceID: "9007199254740993", direction: 1, basisBundle: baseIdentity, originalBundle: baseIdentity,
                sourceRevision: "node:original", rulesJSON: rules, rawSourceTags: ["traffic_sign": "maxspeed"],
                author: "test", evidenceID: "review", boundWayID: "10", bindingVerified: true, passageEvidenceID: "previous-drive")
            _ = try store.put(value, expectedRevision: 0)
            XCTAssertNil(try resolve(store))
            XCTAssertEqual(try resolve(store, passed: [value.sourceID])?.kmh, 30)
            value.bindingVerified = false; _ = try store.put(value, expectedRevision: 1)
            XCTAssertNil(try resolve(store, passed: [value.sourceID]))
        }
    }

    func testNodeConditionalReevaluatesItsChangingBaselineAndExpiry() throws {
        try run { store, _ in
            func scheduledRules(_ kmh: Int, until minute: Int, includeBase: Bool) throws -> String {
                var tags: [[String: Any]] = []
                if includeBase {
                    tags.append(["role": "speed", "vehicle": "all", "direction": 0, "priority": 0,
                        "conditional": false, "status": "supported", "clauses": [["condition": ["kind": "true"],
                        "limit": ["kind": "numeric", "kmh": 50]]]])
                }
                tags.append(["role": "speed", "vehicle": "all", "direction": 0, "priority": 0,
                    "conditional": true, "status": "supported", "clauses": [["condition": ["kind": "schedule", "windows": [[0, minute]]],
                    "limit": ["kind": "numeric", "kmh": kmh]]]])
                return String(data: try JSONSerialization.data(withJSONObject: ["version": 1, "grammar": "youspeed-osm-speed-1", "tags": tags]), encoding: .utf8)!
            }
            let day = Date(timeIntervalSince1970: 1_767_225_600) // 2026-01-01 UTC
            let sourceRules = try scheduledRules(30, until: 720, includeBase: true)
            let sourceContext = ConditionalSpeedRules.Reevaluation(rulesJSON: sourceRules, baseKmh: 50,
                baseUnlimited: false, direction: 1, countryCode: "DEU", timeZoneID: "UTC")
            var baseline = sourceContext.evaluate(at: day.addingTimeInterval(7*3600)); baseline.reevaluation = sourceContext
            var value = record(id: "node:123"); value = MapDataAmendment(id: value.id, sourceNamespace: "osm", entity: "node", sourceID: "123",
                direction: 1, basisBundle: value.basisBundle, originalBundle: value.originalBundle,
                sourceRevision: "node:123:7", rulesJSON: try scheduledRules(25, until: 600, includeBase: false),
                rawSourceTags: ["maxspeed:conditional": "25 @ (00:00-10:00)"],
                validUntilUTC: day.addingTimeInterval(12*3600).timeIntervalSince1970,
                author: "test", evidenceID: "review", boundWayID: "10", bindingVerified: true, passageEvidenceID: "drive")
            _ = try store.put(value, expectedRevision: 0)
            let context = ConditionalSpeedRules.Context(at: day.addingTimeInterval(7*3600), timeZoneID: "UTC", direction: 1)
            let result = try XCTUnwrap(store.resolve(wayID: "10", bundle: baseIdentity, direction: 1,
                context: context, baseKmh: 50, baseUnlimited: false, passedNodeIDs: ["123"], baselineResult: baseline))
            XCTAssertEqual(result.kmh, 25)
            let reevaluation = try XCTUnwrap(result.reevaluation)
            XCTAssertEqual(reevaluation.evaluate(at: day.addingTimeInterval(11*3600)).kmh, 30)
            XCTAssertEqual(reevaluation.evaluate(at: day.addingTimeInterval(13*3600)).kmh, 50)
            let decoded = try JSONDecoder().decode(ConditionalSpeedRules.Reevaluation.self, from: JSONEncoder().encode(reevaluation))
            XCTAssertEqual(decoded.evaluate(at: day.addingTimeInterval(11*3600)).kmh, 30)
            let unresolvedBaseline = ConditionalSpeedRules.Result(kmh: nil, unlimited: false, unresolved: true, reason: "electronic_sign_state_unknown")
            let laterContext = ConditionalSpeedRules.Context(at: day.addingTimeInterval(11*3600), timeZoneID: "UTC", direction: 1)
            let unresolved = try XCTUnwrap(store.resolve(wayID: "10", bundle: baseIdentity, direction: 1,
                context: laterContext, baseKmh: 50, baseUnlimited: false, passedNodeIDs: ["123"], baselineResult: unresolvedBaseline))
            XCTAssertTrue(unresolved.unresolved)
            XCTAssertTrue(try XCTUnwrap(unresolved.reevaluation).evaluate(at: day.addingTimeInterval(11*3600)).unresolved)
            XCTAssertEqual(try XCTUnwrap(unresolved.reevaluation).evaluate(at: day.addingTimeInterval(13*3600)).reason, "electronic_sign_state_unknown")
            var excessive = sourceContext
            for _ in 0..<9 { var parent = sourceContext; parent.baselineReevaluations = [excessive]; excessive = parent }
            XCTAssertTrue(excessive.evaluate(at: day).unresolved)
        }
    }

    func testChangedGenerationPendingReviewAndOverlapsDoNotInventPrecedence() throws {
        try run { store, _ in
            var value = record(); value.basisBundle = "different-generation"
            _ = try store.put(value, expectedRevision: 0)
            XCTAssertNil(try resolve(store))
            value.basisBundle = baseIdentity; value.reviewState = "needs_review"
            _ = try store.put(value, expectedRevision: 1)
            XCTAssertNil(try resolve(store))
            value.reviewState = "confirmed"; _ = try store.put(value, expectedRevision: 2)
            _ = try store.put(record(id: "second-source-record"), expectedRevision: 0)
            XCTAssertEqual(try resolve(store)?.reason, "map_amendment_conflict")
        }
    }

    func testMalformedIndexedTargetCannotApplyToAnotherWay() throws {
        try run { store, directory in
            _ = try store.put(record(), expectedRevision: 0)
            var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(try XCTUnwrap(store.latest("source:10")))) as! [String: Any]
            object["source_id"] = "11"
            let json = String(data: try JSONSerialization.data(withJSONObject: object), encoding: .utf8)!
            var db: OpaquePointer?
            XCTAssertEqual(sqlite3_open(directory.appendingPathComponent("map_data_amendments.sqlite").path, &db), SQLITE_OK)
            let database = try XCTUnwrap(db)
            defer { sqlite3_close(database) }
            var statement: OpaquePointer?
            XCTAssertEqual(sqlite3_prepare_v2(database, "UPDATE revisions SET body_json=?1 WHERE id='source:10'", -1, &statement, nil), SQLITE_OK)
            defer { sqlite3_finalize(statement) }
            _ = json.withCString { sqlite3_bind_text(statement, 1, $0, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) }
            XCTAssertEqual(sqlite3_step(statement), SQLITE_DONE)
            XCTAssertThrowsError(try resolve(store))
        }
    }

    func testReviewedNodeUsesExistingPassageAndHoldsUntilScopeEndOrReset() throws {
        try run { store, _ in
            let node: [String: Any] = ["osm_node_id": 123456, "source_id": "osm-node:123456", "latitude": 48.001,
                "longitude": 9.0, "tags": ["traffic_sign": "maxspeed", "maxspeed": "30"],
                "binding_status": "unresolved_direction", "memberships": [["way_id": 10, "source_vertex_ordinal": 1,
                    "chainage_m": 111.195, "direction": "unknown", "proof": "explicit_source_way_node_membership"]]]
            let nodeJSON = String(data: try JSONSerialization.data(withJSONObject: node, options: [.sortedKeys]), encoding: .utf8)!
            let record = MapDataAmendment(id: "node:123456", sourceNamespace: "osm", entity: "node", sourceID: "123456",
                direction: 1, basisBundle: baseIdentity, originalBundle: baseIdentity, sourceRevision: "source-node:1",
                rulesJSON: rules, rawSourceTags: ["maxspeed:conditional": "30 @ (wet)"], author: "reviewer", evidenceID: "review:1",
                nodeJSON: nodeJSON, boundWayID: "10", bindingVerified: true, passageEvidenceID: "reviewed-directed-association")
            _ = try store.put(record, expectedRevision: 0)
            let now = Date()
            let records = try store.nodePassageCandidates(wayID: "10", bundle: baseIdentity, at: now)
            var runtime = MapDataNodePassageRuntime()
            let points = [(48.0,9.0),(48.002,9.0)]
            let length = InventorySignBundle.distance(48,9,48.002,9) * (6_371_000.0/6_371_008.8)
            func consume(_ latitude: Double, offset: Double, accuracy: Double = 5, heading: Double = 0) -> Set<String> {
                runtime.consume(records: records, bundle: baseIdentity, wayID: "10", points: points,
                    wayLengthM: length, lat: latitude, lon: 9, heading: heading, headingAccuracy: 5,
                    accuracy: accuracy, matchStable: true, at: now.addingTimeInterval(offset), now: now.addingTimeInterval(offset))
            }
            XCTAssertTrue(consume(48.0008, offset: 0).isEmpty)
            XCTAssertEqual(consume(48.0011, offset: 1), ["123456"])
            XCTAssertEqual(consume(48.00099, offset: 1.5), ["123456"], "A passed scope survives small chainage jitter")
            XCTAssertEqual(consume(48.0015, offset: 2), ["123456"], "Leaving the geofence does not revoke the passed scope")
            let heldDuringGap = consume(48.0016, offset: 3, accuracy: 100)
            XCTAssertEqual(heldDuringGap, ["123456"])
            var context = ConditionalSpeedRules.Context(direction: 1); context.facts["wet"] = true
            XCTAssertEqual(try store.resolve(wayID: "10", bundle: baseIdentity, direction: 1,
                context: context, baseKmh: 50, baseUnlimited: false, passedNodeIDs: heldDuringGap)?.kmh, 30)
            var numericEdit = records[0]
            numericEdit.rulesJSON = numericEdit.rulesJSON.replacingOccurrences(of: #""kmh":30"#, with: #""kmh":25"#)
            numericEdit.revision += 1
            func invalidFix(_ candidate: MapDataAmendment, offset: Double) -> Set<String> {
                runtime.consume(records: [candidate], bundle: baseIdentity, wayID: "10", points: points,
                    wayLengthM: length, lat: 48.0016, lon: 9, heading: nil, headingAccuracy: nil,
                    accuracy: 100, matchStable: true, at: now.addingTimeInterval(offset), now: now.addingTimeInterval(offset))
            }
            XCTAssertEqual(invalidFix(numericEdit, offset: 3.2), ["123456"], "Changing a numeric clause retains the same passage proof")
            var rebound = numericEdit; rebound.passageEvidenceID = "different-reviewed-binding"
            XCTAssertTrue(invalidFix(rebound, offset: 3.4).isEmpty, "A new binding cannot borrow proof during a GPS/heading gap")
            XCTAssertTrue(consume(48.0021, offset: 4).isEmpty)
            runtime.reset()
            XCTAssertTrue(consume(48.0017, offset: 5).isEmpty, "A new drive cannot borrow the previous passage")
            XCTAssertTrue(consume(48.0011, offset: 6, heading: 180).isEmpty)
        }
    }

    func testLocalMissingSignPersistsAmendsPassesExpiresAndTombstones() throws {
        try run { store, directory in
            let created = try store.createLocalNode(latitude: 48.001, longitude: 9,
                tags: ["traffic_sign": "maxspeed", "maxspeed": "50", "maxspeed:conditional": "30 @ (wet)"],
                rulesJSON: rules, bundle: baseIdentity, author: "surveyor", evidenceID: "survey:1")
            XCTAssertTrue(created.sourceID.hasPrefix("local-node:"))
            let reopened = MapDataAmendmentStore(directory: directory)
            var saved = try XCTUnwrap(reopened.latest(created.id))
            let raw = try XCTUnwrap(saved.nodeJSON?.data(using: .utf8))
            let object = try XCTUnwrap(JSONSerialization.jsonObject(with: raw) as? [String: Any])
            XCTAssertNil(object["osm_node_id"])
            XCTAssertEqual(object["source_id"] as? String, saved.sourceID)
            XCTAssertNil(try resolve(reopened, passed: [saved.sourceID]), "An unbound local record cannot become a road limit")
            saved = try reopened.amendNumericLimit(saved.id, expectedRevision: 1, tagKey: "maxspeed:conditional", clauseIndex: 0, kmh: 25)
            XCTAssertEqual(saved.rawSourceTags["maxspeed:conditional"], "30 @ (wet)")
            saved.boundWayID = "10"; saved.direction = 1; saved.bindingVerified = true
            saved.passageEvidenceID = "reviewed-survey-binding"; saved.stationChainageM = 111.195
            saved.scopeStartM = 111.195; saved.scopeEndM = 180
            saved = try reopened.put(saved, expectedRevision: 2)
            let now = Date()
            let records = try reopened.nodePassageCandidates(wayID: "10", bundle: baseIdentity, at: now)
            var runtime = MapDataNodePassageRuntime()
            func consume(_ latitude: Double, offset: Double, records: [MapDataAmendment]) -> Set<String> {
                runtime.consume(records: records, bundle: baseIdentity, wayID: "10", points: [(48,9),(48.002,9)],
                    wayLengthM: 222.3898532891175, lat: latitude, lon: 9, heading: 0, headingAccuracy: 5,
                    accuracy: 5, matchStable: true, at: now.addingTimeInterval(offset), now: now.addingTimeInterval(offset))
            }
            XCTAssertTrue(consume(48.0008, offset: 0, records: records).isEmpty)
            let passed = consume(48.0011, offset: 1, records: records)
            XCTAssertEqual(passed, [saved.sourceID])
            XCTAssertEqual(try resolve(reopened, passed: passed)?.kmh, 25)
            XCTAssertEqual(try resolve(reopened, wet: false, passed: passed)?.kmh, 50)
            XCTAssertTrue(consume(48.0017, offset: 2, records: records).isEmpty)
            var outsideGeometry = saved; outsideGeometry.stationChainageM = 300; outsideGeometry.scopeEndM = 350
            runtime.reset()
            XCTAssertTrue(consume(48.0011, offset: 3, records: [outsideGeometry]).isEmpty)
            _ = try reopened.tombstone(saved.id, expectedRevision: 3)
            let final = MapDataAmendmentStore(directory: directory)
            XCTAssertNil(try resolve(final, passed: passed))
            XCTAssertEqual(try final.history(saved.id).map(\.operation), ["upsert", "upsert", "upsert", "tombstone"])
        }
    }

    func testKnownNodeRevisionIsByteBoundAndLegacyIncomingVersionIsInert() throws {
        let original = #"{"osm_node_id":123,"source_id":"osm-node:123","latitude":48,"longitude":9,"tags":{"maxspeed":"50"},"memberships":[],"binding_status":"unresolved_direction"}"#
        let changed = original.replacingOccurrences(of: #""maxspeed":"50""#, with: #""maxspeed":"60""#)
        let revision = MapDataAmendmentStore.nodeSourceRevision(json: original)
        XCTAssertTrue(MapDataAmendmentStore.matchesNodeSourceRevision(revision, json: original))
        XCTAssertFalse(MapDataAmendmentStore.matchesNodeSourceRevision(revision, json: changed))
        XCTAssertFalse(MapDataAmendmentStore.matchesNodeSourceRevision(revision, json: nil))
        try run { store, _ in
            var value = record(); value.basisBundle = "shared-version"
            _ = try store.put(value, expectedRevision: 0)
            XCTAssertNil(try store.resolve(wayID: "10", bundle: "shared-version", direction: 1,
                context: .init(direction: 1), baseKmh: 50, baseUnlimited: false))
        }
    }
}

import XCTest
import SQLite3
@testable import SpeedConsumer

final class ConditionalSpeedRulesTests: XCTestCase {
    private func nightRules() -> [String: Any] {
        ["version":1,"grammar":"youspeed-osm-speed-1","tags":[[
            "role":"speed","vehicle":"all","direction":0,"conditional":true,"priority":0,"status":"supported",
            "clauses":[["limit":["kind":"numeric","kmh":30],
                "condition":["kind":"schedule","windows":[[1320,360]],"weekdays":[],"holidays":[]]]]]]]
    }
    func testOutsideWindowUsesIndependentBaseAndNeverInventsOne() throws {
        let at = try XCTUnwrap(ISO8601DateFormatter().date(from:"2026-10-23T10:00:00Z"))
        let context = ConditionalSpeedRules.Context(at:at,countryCode:"DE",direction:1)
        XCTAssertEqual(ConditionalSpeedRules.evaluate(nightRules(),context:context,baseKmh:90,baseUnlimited:false).kmh,90)
        XCTAssertTrue(ConditionalSpeedRules.evaluate(nightRules(),context:context,baseKmh:nil,baseUnlimited:true).unlimited)
        XCTAssertTrue(ConditionalSpeedRules.evaluate(nightRules(),context:context,baseKmh:nil,baseUnlimited:false).unresolved)
    }
    func testCachedReevaluationKeepsExplicitTimezoneAndHalfOpenBoundary() throws {
        var database: OpaquePointer?
        XCTAssertEqual(sqlite3_open(":memory:",&database),SQLITE_OK)
        let db = try XCTUnwrap(database);defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db,"CREATE TABLE road_speed_capability(version INTEGER,grammar TEXT); INSERT INTO road_speed_capability VALUES(1,'youspeed-osm-speed-1'); CREATE TABLE road_speed_rule_set(way_id INTEGER PRIMARY KEY,rules_json TEXT);",nil,nil,nil),SQLITE_OK)
        let raw = String(decoding:try JSONSerialization.data(withJSONObject:nightRules()),as:UTF8.self).replacingOccurrences(of:"'",with:"''")
        XCTAssertEqual(sqlite3_exec(db,"INSERT INTO road_speed_rule_set VALUES(12,'\(raw)');",nil,nil,nil),SQLITE_OK)
        func instant(_ value: String) throws -> Date { try XCTUnwrap(ISO8601DateFormatter().date(from:value)) }
        let initial = try XCTUnwrap(ConditionalSpeedRules.resolve(db:db,wayID:"12",direction:1,baseKmh:90,baseUnlimited:false,
            at:instant("2026-10-23T19:59:00Z"),timeZoneID:"Europe/Paris",countryCode:"FR"))
        XCTAssertEqual(initial.kmh,90)
        let cached = try JSONDecoder().decode(ConditionalSpeedRules.Reevaluation.self,from:JSONEncoder().encode(XCTUnwrap(initial.reevaluation)))
        XCTAssertEqual(cached.evaluate(at:try instant("2026-10-23T20:00:00Z")).kmh,30)
        XCTAssertEqual(cached.evaluate(at:try instant("2026-10-24T04:00:00Z")).kmh,90)
    }
    func testPartialCapabilityCannotExecuteRulesOrRestoreScalarFallback() throws {
        for schema in ["CREATE TABLE road_speed_capability(other TEXT);", "CREATE TABLE road_speed_rule_set(way_id INTEGER,rules_json TEXT);"] {
            var database: OpaquePointer?
            XCTAssertEqual(sqlite3_open(":memory:",&database),SQLITE_OK)
            let db = try XCTUnwrap(database);defer { sqlite3_close(db) }
            XCTAssertEqual(sqlite3_exec(db,schema,nil,nil,nil),SQLITE_OK)
            let result=ConditionalSpeedRules.resolve(db:db,wayID:"12",direction:1,baseKmh:120,baseUnlimited:false)
            XCTAssertTrue(try XCTUnwrap(result).unresolved)
            XCTAssertNil(result?.kmh)
        }
    }
    func testLegacyElectronicMarkerCannotInventRoadClassDefault() throws {
        var database: OpaquePointer?
        XCTAssertEqual(sqlite3_open(":memory:", &database), SQLITE_OK)
        let db = try XCTUnwrap(database); defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, "CREATE TABLE ways(way_id INTEGER,maxspeed TEXT); INSERT INTO ways VALUES(716,'signals');", nil, nil, nil), SQLITE_OK)
        XCTAssertEqual(ConditionalSpeedRules.resolve(db: db, wayID: "716", direction: 1, baseKmh: 100, baseUnlimited: false)?.unresolved, true)
    }
    func testKnownBrokenCapabilityCannotFallBackToScalarSpeed() throws {
        var database: OpaquePointer?
        XCTAssertEqual(sqlite3_open(":memory:", &database), SQLITE_OK)
        let db = try XCTUnwrap(database); defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, "CREATE TABLE road_speed_capability(version INTEGER,grammar TEXT); INSERT INTO road_speed_capability VALUES(1,'youspeed-osm-speed-1');", nil, nil, nil), SQLITE_OK)
        let result = ConditionalSpeedRules.resolve(db: db, wayID: "12", direction: 1, baseKmh: 120, baseUnlimited: false)
        XCTAssertEqual(result?.unresolved, true)
        XCTAssertNil(result?.kmh)
    }
    func testSharedConditionalConformance() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("shared/conditional-speed-rules/conformance-v1.json"))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let rows = try XCTUnwrap(fixture["cases"] as? [[String: Any]])
        for row in rows {
            let ctx = try XCTUnwrap(row["context"] as? [String: Any])
            var context = ConditionalSpeedRules.Context(at: try XCTUnwrap(ISO8601DateFormatter().date(from: ctx["at"] as? String ?? "")), timeZoneID: ctx["time_zone_id"] as? String, countryCode: ctx["country_code"] as? String, direction: ctx["direction"] as? Int)
            context.clockTrusted = ctx["clock_trusted"] as? Bool ?? true
            context.facts = ctx["facts"] as? [String: Bool] ?? [:]
            let result = ConditionalSpeedRules.evaluate(try XCTUnwrap(row["rules"] as? [String: Any]), context: context, baseKmh: row["base_kmh"] as? Int, baseUnlimited: row["base_unlimited"] as? Bool ?? false)
            let expected = try XCTUnwrap(row["expected"] as? [String: Any])
            let name = row["id"] as? String ?? ""
            XCTAssertEqual(result.kmh, expected["kmh"] as? Int, name)
            XCTAssertEqual(result.unlimited, expected["unlimited"] as? Bool, name)
            XCTAssertEqual(result.unresolved, expected["unresolved"] as? Bool, name)
        }
    }
}

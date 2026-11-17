import XCTest
import SQLite3
import SwiftUI
import CoreLocation
@testable import SpeedConsumer

final class ConditionalSpeedRulesTests: XCTestCase {
    private func nightRules() -> [String: Any] {
        ["version":1,"grammar":"youspeed-osm-speed-1","tags":[[
            "role":"speed","vehicle":"all","direction":0,"conditional":true,"priority":0,"status":"supported",
            "raw":"30 @ (22:00-06:00)",
            "clauses":[["limit":["kind":"numeric","kmh":30],"source_span":[0,18],
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
        XCTAssertEqual(initial.inactivePreview, .init(speedKmh: 30, restrictionText: "22:00-06:00"))
        let cached = try JSONDecoder().decode(ConditionalSpeedRules.Reevaluation.self,from:JSONEncoder().encode(XCTUnwrap(initial.reevaluation)))
        let active = cached.evaluate(at:try instant("2026-10-23T20:00:00Z"))
        XCTAssertEqual(active.kmh,30)
        XCTAssertNil(active.inactivePreview)
        let expired = cached.evaluate(at:try instant("2026-10-24T04:00:00Z"))
        XCTAssertEqual(expired.kmh,90)
        XCTAssertEqual(expired.inactivePreview, initial.inactivePreview)
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


// Uses the full packed BW generation and the normal startup, routing and matcher.
extension ConditionalSpeedRulesTests {
    @MainActor
    func testBernbachFullBundleRouteAndWeekdayClockPresentation() async throws {
#if !targetEnvironment(simulator)
        throw XCTSkip("The clock replay runs in the isolated simulator.")
#else
        let fm = FileManager.default
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let source = repo.appendingPathComponent("mapdata/build/packed-v4-2026-11-17-conditional-bw/baden-wuerttemberg/bundle")
        let sourceManifest = source.appendingPathComponent("baden-wuerttemberg_manifest.json")
        guard fm.fileExists(atPath: sourceManifest.path) else {
            throw XCTSkip("Generate the local 2026-11-17 BW conditional bundle to run the Bernbach replay.")
        }
        let manifestData = try Data(contentsOf: sourceManifest)
        let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: manifestData)
        let packed = try XCTUnwrap(manifest.packedBase)
        let support = try V3BundleManager.applicationSupportDirectory()
        let bundles = support.appendingPathComponent("bundles")
        try fm.createDirectory(at: bundles, withIntermediateDirectories: true)
        let activeURL = support.appendingPathComponent("active_bundle.json")
        let originalActive = try? Data(contentsOf: activeURL)
        let existing = try fm.contentsOfDirectory(at: bundles, includingPropertiesForKeys: nil)
        let savedManifests: [(URL, Data)] = existing.compactMap {
            let url = $0.appendingPathComponent("bundle-manifest.v3.json")
            return (try? Data(contentsOf: url)).map { (url, $0) }
        }
        let fixture = bundles.appendingPathComponent("bernbach-replay-\(UUID().uuidString)")
        try fm.createDirectory(at: fixture, withIntermediateDirectories: true)
        defer {
            for (url, data) in savedManifests { try? data.write(to: url, options: .atomic) }
            if let originalActive { try? originalActive.write(to: activeURL, options: .atomic) }
            else { try? fm.removeItem(at: activeURL) }
            try? fm.removeItem(at: fixture)
        }
        for (url, _) in savedManifests { try fm.removeItem(at: url) }
        for artifact in [manifest.db] + packed.artifacts {
            try fm.copyItem(at: source.appendingPathComponent(artifact.file), to: fixture.appendingPathComponent(artifact.file))
        }
        try manifestData.write(to: fixture.appendingPathComponent("bundle-manifest.v3.json"))
        let databaseURL = fixture.appendingPathComponent(manifest.db.file)
        let active = ActiveBundleState(region: manifest.region, bundleVersion: manifest.bundleVersion,
            dbFileName: manifest.db.file, activatedAtUTC: manifest.createdAtUTC, dbPath: databaseURL.path,
            dbSHA256: manifest.db.sha256)
        try JSONEncoder().encode(active).write(to: activeURL, options: .atomic)
        let db = try PackedBundleRuntime.openReadOnly(path: databaseURL.path)
        defer { sqlite3_close(db) }
        let output = repo.appendingPathComponent("output/bernbach-conditional-2026-11-17/iphone")
        try fm.createDirectory(at: output, withIntermediateDirectories: true)
        var rows: [[String: Any]] = []
        for direction in [1, -1] {
            for day in 16...22 {
                for (time, activeTime) in [("06:29:59", false), ("06:30:00", true),
                                           ("17:29:59", true), ("17:30:00", false)] {
                    let at = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-11-\(day)T\(time)+01:00"))
                    let expected = day <= 20 && activeTime ? 30 : 50
                    let result = try XCTUnwrap(ConditionalSpeedRules.resolve(db: db, wayID: "966531279",
                        direction: direction, baseKmh: 50, baseUnlimited: false, at: at, countryCode: "DEU"))
                    XCTAssertEqual(result.kmh, expected)
                    XCTAssertFalse(result.unresolved)
                    XCTAssertEqual(result.inactivePreview?.speedKmh, expected == 50 ? 30 : nil)
                    if expected == 50 {
                        XCTAssertEqual(result.inactivePreview?.restrictionText, "Mo-Fr 06:30-17:30")
                    }
                    rows.append(["day": day, "time": time, "direction": direction, "kmh": result.kmh!,
                        "preview": result.inactivePreview?.speedKmh as Any? ?? NSNull()])
                }
            }
        }
        let model = DriveSessionViewModel()
        model.panoramaxCaptureEnabled = false
        model.trafficSignRecognitionEnabled = false
        defer { model.stopDriving() }
        for _ in 0..<200 where model.startupLogReviewState == .checking {
            try await Task.sleep(for: .milliseconds(10))
        }
        if model.startupLogReviewState == .choice || model.startupLogReviewState == .failed { model.keepStartupLogs() }
        try await model.testWaitForStartupDataLoad(timeout: 60)
        XCTAssertEqual(model.activeBundleVersion, manifest.bundleVersion)
        for bearing in [160.0, 340.0] {
            for _ in 0..<11 {
                await model.testRunGPSLookup(latitude: 48.8237069, longitude: 8.4159062,
                    headingDegrees: bearing, speedKmh: 30)
                try await Task.sleep(for: .seconds(1))
            }
            XCTAssertEqual(model.limitWayID, "966531279")
            for (time, expected) in [("06:29:59", 50), ("06:30:00", 30), ("17:29:59", 30), ("17:30:00", 50)] {
                let at = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-11-17T\(time)+01:00"))
                model.testReevaluateConditionalBundle(at: at)
                XCTAssertEqual(model.speedLimitKmh, expected, "\(bearing) \(time) \(model.testUpcomingDiagnosticState)")
                XCTAssertEqual(model.inactiveSpeedLimitPreview?.speedKmh, expected == 50 ? 30 : nil)
                if expected == 50 {
                    XCTAssertEqual(model.inactiveSpeedLimitPreview?.restrictionText, "Mo-Fr 06:30-17:30")
                }
                rows.append(["controller": true, "bearing": bearing, "time": time,
                    "kmh": model.speedLimitKmh as Any? ?? NSNull(),
                    "preview": model.inactiveSpeedLimitPreview?.speedKmh as Any? ?? NSNull()])
                if bearing == 160 && (time == "06:30:00" || time == "17:30:00") {
                    let renderer = ImageRenderer(content: MainView(viewModel: model)
                        .environment(\.locale, Locale(identifier: "de_DE"))
                        .frame(width: 393, height: 852))
                    renderer.scale = 2
                    let image = try XCTUnwrap(renderer.uiImage)
                    try XCTUnwrap(image.pngData()).write(to: output.appendingPathComponent("bernbach-\(expected).png"))
                }
            }
        }
        let direct = V3SpeedLimitService(dbPath: databaseURL.path, countryCode: "DEU")
        let pin = try direct.lookupSpeedLimit(lat: 48.823257, lon: 8.416530, headingDeg: 110,
            headingAccuracyDeg: 2, speedKmh: 30, horizontalAccuracyM: 2)
        XCTAssertEqual(pin.wayID, "966531278")
        XCTAssertEqual(pin.speedLimitKmh, 50)
        XCTAssertNil(pin.conditionalRuleContext)
        try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
            .write(to: output.appendingPathComponent("results.json"))
        print("BERNBACH_IPHONE \(rows.count) checks, pin way \(pin.wayID ?? "none")")
#endif
    }
}

import XCTest
import SQLite3
@testable import SpeedDBBench

final class SpeedDBBenchTests: XCTestCase {
    private struct MatrixLogPayload: Codable {
        let datasetKind: String
        let report: BenchmarkReport
    }

    func testBenchmarkRunnerOnSyntheticDB() throws {
        let (dbURL, datasetKind, cleanup) = try prepareBenchmarkDB()
        defer { cleanup() }

        let runner = SQLiteBenchmarkRunner(dbPath: dbURL.path)
        let input = ProbeInput(
            lat: 52.5200,
            lon: 13.4050,
            heading: 90.0,
            repeats: 5,
            searchRadiusM: 1200.0,
            tileRadius: 1,
            maxCandidates: 5000,
            topK: 5,
            headingWeight: 2.0,
            polylineTopN: 250
        )
        let report = try runner.run(input: input)
        let payload = MatrixLogPayload(datasetKind: datasetKind, report: report)
        if let data = try? JSONEncoder().encode(payload),
           let json = String(data: data, encoding: .utf8) {
            print("BENCHMARK_MATRIX_JSON=\(json)")
        }

        if datasetKind == "country_germany_v4" {
            XCTAssertGreaterThan(report.dbSizeBytes, 1_000_000_000)
        }

        XCTAssertEqual(report.benchmarkMs.keys.count, 4)
        for variant in BenchmarkVariant.allCases {
            guard let perMode = report.benchmarkMs[variant.rawValue] else {
                XCTFail("Missing variant \(variant.rawValue)")
                continue
            }
            for mode in DistanceMode.allCases {
                guard let timing = perMode[mode.rawValue] else {
                    XCTFail("Missing mode \(mode.rawValue) for variant \(variant.rawValue)")
                    continue
                }
                XCTAssertGreaterThan(timing.avgMs, 0)
                XCTAssertGreaterThan(timing.maxMs, 0)
            }
        }
        XCTAssertTrue(report.hasWayTileTable)
    }

    private func prepareBenchmarkDB() throws -> (URL, String, () -> Void) {
        let fm = FileManager.default
        let tempCountryDB = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("speeds_v4_germany.sqlite")
        if fm.fileExists(atPath: tempCountryDB.path) {
            return (tempCountryDB, "country_germany_v4", {})
        }
        let appSupport = try AssetStore.applicationSupportDirectory()
        let countryDB = appSupport.appendingPathComponent("speeds_v4_germany.sqlite")
        if fm.fileExists(atPath: countryDB.path) {
            return (countryDB, "country_germany_v4", {})
        }

        let dbURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("speeddbbench-unit-\(UUID().uuidString).sqlite")
        try createSyntheticDB(at: dbURL)
        return (dbURL, "synthetic_fixture", { try? fm.removeItem(at: dbURL) })
    }

    private func createSyntheticDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            XCTFail("Failed to open synthetic db")
            return
        }
        defer { sqlite3_close(db) }

        let schema = """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata(key, value) VALUES('tile_size_m', '4096');
        CREATE TABLE ways (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          highway TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
          approx_heading_deg REAL,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_tile (
          row_id INTEGER NOT NULL,
          tile_x INTEGER NOT NULL,
          tile_y INTEGER NOT NULL
        );
        INSERT INTO ways(
          row_id, way_id, highway, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign,
          approx_heading_deg, min_lon, min_lat, max_lon, max_lat
        )
          VALUES(1, 'w1', 'residential', '50', NULL, 'DE:urban', NULL, NULL, 90.0, 13.395, 52.510, 13.415, 52.530);
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
          VALUES(1, 13.395, 13.415, 52.510, 52.530);
        INSERT INTO way_geom(row_id, way_id, points_json)
          VALUES(1, 'w1', '[[52.510,13.395],[52.530,13.415]]');
        INSERT INTO way_tile(row_id, tile_x, tile_y)
          VALUES(1, 364, 1683);
        """
        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            XCTFail("Failed to create synthetic schema: \(err)")
            return
        }
    }
}

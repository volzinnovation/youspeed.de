import XCTest
import SQLite3
@testable import SpeedDBBench

final class SpeedDBBenchTests: XCTestCase {
    private struct MatrixLogPayload: Codable {
        let datasetKind: String
        let report: BenchmarkReport
    }

    private struct RouteLogPayload: Codable {
        let datasetKind: String
        let report: KarlsruheVariantReport
    }

    private struct StratifiedProbe: Codable {
        let probeID: String
        let stratum: String
        let region: String
        let lat: Double
        let lon: Double
        let heading: Double?
    }

    private struct StratifiedProbeReport: Codable {
        let probe: StratifiedProbe
        let report: BenchmarkReport
    }

    private struct StratifiedLogPayload: Codable {
        let datasetKind: String
        let probeCount: Int
        let reports: [StratifiedProbeReport]
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
                XCTAssertGreaterThanOrEqual(timing.avgMs, 0)
                XCTAssertGreaterThanOrEqual(timing.maxMs, 0)
            }
        }
        XCTAssertTrue(report.hasWayTileTable)
    }

    func testStratifiedLatencyBenchmarkFromEnvironment() throws {
        let env = ProcessInfo.processInfo.environment
        guard let dbPath = env["SPEEDDBBENCH_DB_PATH"], !dbPath.isEmpty else {
            throw XCTSkip("SPEEDDBBENCH_DB_PATH not set")
        }
        guard FileManager.default.fileExists(atPath: dbPath) else {
            throw XCTSkip("Benchmark DB does not exist at \(dbPath)")
        }
        guard let probeCSVPath = env["SPEEDDBBENCH_PROBE_CSV"], !probeCSVPath.isEmpty else {
            throw XCTSkip("SPEEDDBBENCH_PROBE_CSV not set")
        }

        let allProbes = try loadStratifiedProbes(path: probeCSVPath)
        let regionFilter = env["SPEEDDBBENCH_REGION_FILTER"].map {
            Set($0.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty })
        } ?? []
        let probes = regionFilter.isEmpty ? allProbes : allProbes.filter { regionFilter.contains($0.region) }
        if probes.isEmpty {
            throw XCTSkip("No probes remain after SPEEDDBBENCH_REGION_FILTER")
        }

        let repeats = max(1, Int(env["SPEEDDBBENCH_REPEATS"] ?? "5") ?? 5)
        let searchRadiusM = Double(env["SPEEDDBBENCH_SEARCH_RADIUS_M"] ?? "1200") ?? 1200.0
        let maxCandidates = max(1, Int(env["SPEEDDBBENCH_MAX_CANDIDATES"] ?? "5000") ?? 5000)
        let tileRadius = max(0, Int(env["SPEEDDBBENCH_TILE_RADIUS"] ?? "1") ?? 1)
        let polylineTopN = max(1, Int(env["SPEEDDBBENCH_POLYLINE_TOP_N"] ?? "250") ?? 250)

        let runner = SQLiteBenchmarkRunner(dbPath: dbPath)
        var reports: [StratifiedProbeReport] = []
        for probe in probes {
            let hasHeading = probe.heading != nil && (0.0...360.0).contains(probe.heading ?? -1.0)
            let input = ProbeInput(
                lat: probe.lat,
                lon: probe.lon,
                heading: hasHeading ? (probe.heading ?? 0.0) : 0.0,
                repeats: repeats,
                searchRadiusM: searchRadiusM,
                tileRadius: tileRadius,
                maxCandidates: maxCandidates,
                topK: 5,
                headingWeight: hasHeading ? 2.0 : 0.0,
                polylineTopN: polylineTopN
            )
            let report = try runner.run(input: input)
            reports.append(StratifiedProbeReport(probe: probe, report: report))
        }

        let payload = StratifiedLogPayload(
            datasetKind: env["SPEEDDBBENCH_DATASET_KIND"] ?? "external_sqlite",
            probeCount: reports.count,
            reports: reports
        )
        let data = try JSONEncoder().encode(payload)
        if let json = String(data: data, encoding: .utf8) {
            print("STRATIFIED_BENCHMARK_JSON=\(json)")
        }

        XCTAssertFalse(reports.isEmpty)
        if env["SPEEDDBBENCH_REQUIRE_WAY_TILE"] == "1" {
            XCTAssertTrue(reports.contains { $0.report.hasWayTileTable })
        }
    }

    func testKarlsruheVariantRouteBenchmarksIfPrepared() throws {
        let prepared = try preparedKarlsruheVariantDatabases()
        if prepared.isEmpty {
            throw XCTSkip("Prepared Karlsruhe benchmark variants not bundled in SpeedDBBench target")
        }

        let scenarios = [
            RouteScenario.karlsruheL564,
            RouteScenario.gernsbachTunnelSurface,
        ]

        for preparedDB in prepared {
            let runner = RouteScenarioBenchmarkRunner(dbPath: preparedDB.url.path)
            let report = try runner.run(
                scenarios: scenarios,
                repeats: 20,
                mode: preparedDB.mode
            )
            let payload = RouteLogPayload(datasetKind: preparedDB.datasetKind, report: report)
            if let data = try? JSONEncoder().encode(payload),
               let json = String(data: data, encoding: .utf8) {
                print("ROUTE_BENCHMARK_JSON=\(json)")
            }

            for scenario in report.scenarios {
                XCTAssertEqual(
                    scenario.mismatchedWayCount,
                    0,
                    "Unexpected way mismatches for \(preparedDB.datasetKind) / \(scenario.scenarioID)"
                )
                XCTAssertEqual(
                    scenario.tunnelMismatchCount,
                    0,
                    "Unexpected tunnel mismatches for \(preparedDB.datasetKind) / \(scenario.scenarioID)"
                )
                XCTAssertGreaterThan(scenario.timing.avgFixMs, 0)
            }
        }
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

    private func preparedKarlsruheVariantDatabases() throws -> [(url: URL, datasetKind: String, mode: RouteBenchmarkMode)] {
        let variants: [(resource: String, fileName: String, datasetKind: String, mode: RouteBenchmarkMode)] = [
            ("karlsruhe_v3_A_geom16", "karlsruhe_v3_A_geom16.sqlite", "karlsruhe_v3_A_geom16", .baseline),
            ("karlsruhe_v3_B_waylinks", "karlsruhe_v3_B_waylinks.sqlite", "karlsruhe_v3_B_waylinks", .wayLinks),
        ]

        var out: [(url: URL, datasetKind: String, mode: RouteBenchmarkMode)] = []
        let fm = FileManager.default
        let appSupport = try AssetStore.applicationSupportDirectory()
        if !fm.fileExists(atPath: appSupport.path) {
            try fm.createDirectory(at: appSupport, withIntermediateDirectories: true)
        }
        let candidateBundles = [Bundle.main, Bundle(for: type(of: self))] + Bundle.allBundles
        for variant in variants {
            let src = candidateBundles.lazy.compactMap { bundle in
                bundle.url(forResource: variant.resource, withExtension: "sqlite") ??
                bundle.url(forResource: variant.resource, withExtension: "sqlite", subdirectory: "BenchmarkAssets")
            }.first
            guard let src else {
                continue
            }
            let dst = appSupport.appendingPathComponent(variant.fileName)
            if fm.fileExists(atPath: dst.path) {
                try fm.removeItem(at: dst)
            }
            try fm.copyItem(at: src, to: dst)
            out.append((dst, variant.datasetKind, variant.mode))
        }
        return out
    }

    private func loadStratifiedProbes(path: String) throws -> [StratifiedProbe] {
        let raw = try String(contentsOfFile: path, encoding: .utf8)
        let lines = raw.split(whereSeparator: { $0.isNewline }).map(String.init)
        guard let headerLine = lines.first else {
            return []
        }
        let headers = parseCSVLine(headerLine)
        var probes: [StratifiedProbe] = []
        for line in lines.dropFirst() where !line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let values = parseCSVLine(line)
            var row: [String: String] = [:]
            for (idx, header) in headers.enumerated() where idx < values.count {
                row[header] = values[idx]
            }
            guard let probeID = row["probe_id"],
                  let stratum = row["stratum"],
                  let region = row["region"],
                  let lat = Double(row["lat"] ?? ""),
                  let lon = Double(row["lon"] ?? "") else {
                continue
            }
            let heading = Double(row["heading"] ?? "")
            probes.append(
                StratifiedProbe(
                    probeID: probeID,
                    stratum: stratum,
                    region: region,
                    lat: lat,
                    lon: lon,
                    heading: heading
                )
            )
        }
        return probes
    }

    private func parseCSVLine(_ line: String) -> [String] {
        var out: [String] = []
        var current = ""
        var inQuotes = false
        var iterator = line.makeIterator()
        while let ch = iterator.next() {
            if ch == "\"" {
                if inQuotes, let next = iterator.next() {
                    if next == "\"" {
                        current.append("\"")
                    } else {
                        inQuotes = false
                        if next == "," {
                            out.append(current)
                            current = ""
                        } else {
                            current.append(next)
                        }
                    }
                } else {
                    inQuotes.toggle()
                }
            } else if ch == "," && !inQuotes {
                out.append(current)
                current = ""
            } else {
                current.append(ch)
            }
        }
        out.append(current)
        return out
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

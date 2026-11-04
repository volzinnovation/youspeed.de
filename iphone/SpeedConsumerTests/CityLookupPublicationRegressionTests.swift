import XCTest
import SQLite3
@testable import SpeedConsumer

final class CityLookupPublicationRegressionTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("city-lookup-regression-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: directory)
    }

    func testIndependentCityKeepsAdminSixNameWithoutDuplicateDistrict() throws {
        let url = try fixture("pforzheim.sqlite")
        try addBoundary(at: url, row: 1, level: 6, name: "Pforzheim", polygon: true)
        try addArea(at: url, row: 101, name: "Pforzheim", level: 6)
        for model in models {
            let result = try lookup(url, model: model)
            XCTAssertEqual(result.cityName, "Pforzheim")
            XCTAssertEqual(result.cityPlaceName, "Pforzheim")
            XCTAssertNil(result.cityDistrictName)
            XCTAssertEqual(result.wayID, "6001")
            XCTAssertEqual(result.speedLimitKmh, 50)
        }
    }

    func testIncompleteNeuenbuergPolygonStillCompletesDistrictFromAreaPolygons() throws {
        let url = try fixture("neuenbuerg.sqlite")
        try addBoundary(at: url, row: 2, level: 8, name: "Neuenbürg", polygon: true)
        try addArea(at: url, row: 101, name: "Enzkreis", level: 6)
        try addArea(at: url, row: 102, name: "Neuenbürg", level: 8)
        for model in models {
            let result = try lookup(url, model: model)
            XCTAssertEqual(result.cityName, "Neuenbürg (Enzkreis)")
            XCTAssertEqual(result.cityPlaceName, "Neuenbürg")
            XCTAssertEqual(result.cityDistrictName, "Enzkreis")
            XCTAssertEqual(result.speedLimitKmh, 50)
        }
    }

    func testIndependentAndIncompleteCityFallbacksDoNotDecodeUnrelatedAreaGeometry() throws {
        for independent in [true, false] {
            let baseline = try fixture("baseline-\(independent).sqlite")
            try addBoundary(at: baseline, row: 1, level: independent ? 6 : 8,
                            name: independent ? "Pforzheim" : "Neuenbürg", polygon: true)
            try addArea(at: baseline, row: 101, name: independent ? "Pforzheim" : "Enzkreis", level: 6)
            if !independent { try addArea(at: baseline, row: 102, name: "Neuenbürg", level: 8) }
            let extra = directory.appendingPathComponent("extra-\(independent).sqlite")
            try FileManager.default.copyItem(at: baseline, to: extra)
            // This named park contains the fix but supplies neither an administrative
            // name nor a place classification. Its geometry cannot affect city selection.
            try execute(extra, """
            INSERT INTO areas(row_id,area_id,name,points_json,min_lon,min_lat,max_lon,max_lat)
            VALUES(200,'park','Unrelated park','[[12.999,51.999],[13.001,51.999],[13.001,52.001],[12.999,52.001],[12.999,51.999]]',12.999,51.999,13.001,52.001);
            INSERT INTO areas_rtree VALUES(200,12.999,13.001,51.999,52.001);
            """)
            for model in models {
                let first = V3SpeedLimitService(dbPath: baseline.path, matchingModel: model)
                let second = V3SpeedLimitService(dbPath: extra.path, matchingModel: model)
                let expected = try first.lookupSpeedLimit(lat: 52, lon: 13)
                let actual = try second.lookupSpeedLimit(lat: 52, lon: 13)
                XCTAssertEqual(actual.cityName, expected.cityName)
                XCTAssertEqual(actual.cityDistrictName, expected.cityDistrictName)
                XCTAssertEqual(actual.speedLimitKmh, expected.speedLimitKmh)
                XCTAssertEqual(second.resourceStatistics.geometryDecodes, first.resourceStatistics.geometryDecodes,
                    "A score-52 fallback must not decode geometry that cannot contribute a city name")
            }
        }
    }

    func testAreaFallbackKeepsPlacePriorityAndDeduplicatesOverlappingCandidateSets() throws {
        let url = try fixture("places.sqlite")
        try execute(url, """
        INSERT INTO areas(row_id,area_id,name,place,min_lon,min_lat,max_lon,max_lat) VALUES
          (1,'city','Pforzheim','city',13.005,52.005,13.005,52.005),
          (2,'town','Neuenbürg','town',13.01,52.01,13.01,52.01),
          (3,'village','Nearby village','village',13.0001,52.0001,13.0001,52.0001);
        INSERT INTO areas_rtree SELECT row_id,min_lon,max_lon,min_lat,max_lat FROM areas;
        """)
        XCTAssertEqual(try lookup(url).cityName, "Pforzheim", "City/town precedence is retained over a nearer village")
        try execute(url, "DELETE FROM areas_rtree WHERE row_id=1; DELETE FROM areas WHERE row_id=1")
        XCTAssertEqual(try lookup(url).cityName, "Neuenbürg")
        // A containing place belongs to both candidate sets. It must remain one
        // candidate, and exact containment must win over a merely nearby town.
        try execute(url, """
        UPDATE areas SET min_lon=12.999,max_lon=13.001,min_lat=51.999,max_lat=52.001 WHERE row_id=3;
        UPDATE areas_rtree SET min_lon=12.999,max_lon=13.001,min_lat=51.999,max_lat=52.001 WHERE row_id=3;
        """)
        let containing = try lookup(url)
        XCTAssertEqual(containing.cityName, "Nearby village")
        XCTAssertEqual(containing.cityPlaceCandidates, 2, "The exact and nearby ID sets must not duplicate a place")
    }

    func testLegacyNumericAdminLevelsKeepPolygonContainmentInsteadOfBoundingBoxFallback() throws {
        for rawLevel in ["06", "+6"] {
            let url = try fixture("legacy-admin-\(rawLevel).sqlite")
            // The fix is inside this bounding box but above the triangle's sloped
            // edge. Int("06") and Int("+6") are supported legacy admin levels;
            // omitting their geometry must not manufacture bbox containment.
            try execute(url, """
            INSERT INTO areas(row_id,area_id,geometry_type,name,boundary,admin_level,points_json,min_lon,min_lat,max_lon,max_lat)
            VALUES(1,'legacy-district','Polygon','Boundary district','administrative','\(rawLevel)',
              '[[12.99,51.99],[13.01,51.99],[12.99,52.005],[12.99,51.99]]',12.99,51.99,13.01,52.005);
            INSERT INTO areas_rtree VALUES(1,12.99,13.01,51.99,52.005);
            """)
            XCTAssertNil(try lookup(url).cityName, "\(rawLevel): a closed non-containing polygon must not become a bbox match")
            try execute(url, """
            UPDATE areas SET points_json='\(ring)',min_lon=12.98,min_lat=51.98,max_lon=13.02,max_lat=52.02 WHERE row_id=1;
            UPDATE areas_rtree SET min_lon=12.98,max_lon=13.02,min_lat=51.98,max_lat=52.02 WHERE row_id=1;
            """)
            XCTAssertEqual(try lookup(url).cityName, "Boundary district",
                "\(rawLevel): a containing legacy polygon must still supply its administrative name")
        }
    }

    func testAreaFallbackCapsDistinctOrderedCandidatesBeforePlaceSelection() throws {
        let url = try fixture("candidate-cap.sqlite")
        try execute(url, """
        WITH RECURSIVE ids(value) AS (SELECT 1 UNION ALL SELECT value+1 FROM ids WHERE value<510)
        INSERT INTO areas(row_id,area_id,name,min_lon,min_lat,max_lon,max_lat)
        SELECT value,'unrelated:'||value,'Unrelated area '||value,12.999,51.999,13.001,52.001 FROM ids;
        INSERT INTO areas(row_id,area_id,name,place,min_lon,min_lat,max_lon,max_lat) VALUES
          (511,'village','Nearby village','village',13.0001,52.0001,13.0001,52.0001),
          (512,'town','Neuenbürg','town',13.01,52.01,13.01,52.01),
          (513,'city','Pforzheim','city',13.005,52.005,13.005,52.005);
        INSERT INTO areas_rtree SELECT row_id,min_lon,max_lon,min_lat,max_lat FROM areas;
        """)
        for _ in 0..<3 {
            let capped = try lookup(url)
            XCTAssertEqual(capped.cityName, "Neuenbürg", "The city at row 513 lies beyond the deterministic 512-row cap")
            XCTAssertEqual(capped.cityPlaceCandidates, 2)
        }
        // Removing one unrelated row admits the city. A nearby candidate must
        // appear once even when its bbox also contains the exact fix.
        try execute(url, """
        DELETE FROM areas_rtree WHERE row_id=1; DELETE FROM areas WHERE row_id=1;
        UPDATE areas SET min_lon=12.999,min_lat=51.999,max_lon=13.001,max_lat=52.001 WHERE row_id=511;
        UPDATE areas_rtree SET min_lon=12.999,max_lon=13.001,min_lat=51.999,max_lat=52.001 WHERE row_id=511;
        """)
        let overlapping = try lookup(url)
        XCTAssertEqual(overlapping.cityName, "Nearby village", "Containment retains priority once both candidate sets include the village")
        XCTAssertEqual(overlapping.cityPlaceCandidates, 3, "The containing village must not consume a second candidate slot")
        try execute(url, """
        UPDATE areas SET min_lon=13.0001,min_lat=52.0001,max_lon=13.0001,max_lat=52.0001 WHERE row_id=511;
        UPDATE areas_rtree SET min_lon=13.0001,max_lon=13.0001,min_lat=52.0001,max_lat=52.0001 WHERE row_id=511;
        """)
        XCTAssertEqual(try lookup(url).cityName, "Pforzheim", "After one row is removed the city/town/village priority must remain stable")
    }

    func testContainingAdministrativeAreasSurviveMoreThan512NearbyPlacesWithLowerRowIDs() throws {
        let url = try fixture("point-priority.sqlite")
        try execute(url, """
        WITH RECURSIVE ids(value) AS (SELECT 1 UNION ALL SELECT value+1 FROM ids WHERE value<600)
        INSERT INTO areas(row_id,area_id,name,place,min_lon,min_lat,max_lon,max_lat)
        SELECT value,'hamlet:'||value,'Nearby hamlet '||value,'hamlet',13.01,52.01,13.01,52.01 FROM ids;
        INSERT INTO areas_rtree SELECT row_id,min_lon,max_lon,min_lat,max_lat FROM areas;
        """)
        // Containing administrative polygons are exact spatial evidence and must
        // be admitted before the nearby-name fallback exhausts its bounded rows.
        try addArea(at: url, row: 2001, name: "Enzkreis", level: 6)
        try addArea(at: url, row: 2002, name: "Neuenbürg", level: 8)
        for model in models {
            let result = try lookup(url, model: model)
            XCTAssertEqual(result.cityName, "Neuenbürg (Enzkreis)")
            XCTAssertEqual(result.cityPlaceName, "Neuenbürg")
            XCTAssertEqual(result.cityDistrictName, "Enzkreis")
            XCTAssertEqual(result.cityContainingBoundaries, 2)
            XCTAssertEqual(result.cityPlaceCandidates, 510,
                "Two exact admin candidates must leave 510 distinct nearby rows under the 512-row cap")
        }
    }

    /// Opt-in, source-backed acceptance. Stage context.yspc and its companion
    /// files beside cases.json in Documents/CityLookupFixture of .CityLookupTests.
    /// On Simulator, YOUSPEED_CITY_LOOKUP_CASES may point to the same cases file.
    func testStagedFullRegionalColdAndWarmCityLookupsStayBelowOneSecond() throws {
        let fixture = try stagedFixture()
        var totalSamples = 0
        for item in fixture.cases {
            let service = V3SpeedLimitService(dbPath: fixture.database.path, countryCode: "DEU")
            for iteration in 0..<4 {
                let start = DispatchTime.now().uptimeNanoseconds
                let result = try service.lookupSpeedLimit(lat: item.lat, lon: item.lon,
                    radiusM: 40, maxCandidates: 64, headingDeg: item.headingDeg,
                    headingAccuracyDeg: 10, speedKmh: 35, horizontalAccuracyM: 10)
                let elapsed = Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000
                XCTAssertNotNil(result.wayID, item.id)
                XCTAssertEqual(result.cityPlaceName, item.expectedCityPlaceName, item.id)
                XCTAssertLessThan(elapsed, 1_000,
                    "\(item.id), iteration \(iteration): lookup must finish before the next 1 Hz fix")
                print("CITY_LOOKUP_BUDGET id=\(item.id) iteration=\(iteration) wall_ms=\(elapsed) query_ms=\(result.queryTimeMs) city_ms=\(result.cityResolveMs)")
                totalSamples += 1
            }
        }
        XCTAssertGreaterThanOrEqual(totalSamples, 12)
    }

    @MainActor
    func testStagedFullRegionalCitySequencePublishesWhileOneHertzFixesContinue() async throws {
        let fixture = try stagedFixture()
        let worker = LatestPendingLookupWorker()
        let service = V3SpeedLimitService(dbPath: fixture.database.path, countryCode: "DEU")
        var published: [Int] = []
        var failures: [String] = []
        let count = max(6, fixture.cases.count * 2)
        for index in 0..<count {
            let item = fixture.cases[index % fixture.cases.count]
            worker.submit { token in
                do {
                    let result = try await Task.detached(priority: .utility) {
                        try service.lookupSpeedLimit(lat: item.lat, lon: item.lon,
                            radiusM: 40, maxCandidates: 64, headingDeg: item.headingDeg,
                            headingAccuracyDeg: 10, speedKmh: 35, horizontalAccuracyM: 10)
                    }.value
                    if token.isCurrent {
                        if result.cityPlaceName != item.expectedCityPlaceName || result.wayID == nil {
                            failures.append("\(item.id): missing road or unexpected place")
                        }
                        published.append(index)
                    }
                } catch { failures.append("\(item.id): \(error)") }
            }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        await worker.waitUntilIdle()
        XCTAssertEqual(failures, [])
        XCTAssertEqual(published, Array(0..<count), "Continuous GPS input must not starve city-result publication")
    }

    private let models: [V3SpeedLimitService.MatchingModel] = [.connectedBaseline, .corridorHMM]

    private func lookup(_ url: URL, model: V3SpeedLimitService.MatchingModel = .connectedBaseline) throws -> SpeedLimitResult {
        try V3SpeedLimitService(dbPath: url.path, matchingModel: model).lookupSpeedLimit(lat: 52, lon: 13)
    }

    private struct StagedCases: Decodable {
        struct Item: Decodable, Sendable {
            let id: String
            let lat: Double
            let lon: Double
            let headingDeg: Double?
            let expectedCityPlaceName: String
        }
        let databaseFile: String
        let cases: [Item]
    }

    private func stagedFixture() throws -> (database: URL, cases: [StagedCases.Item]) {
        let fm = FileManager.default
        let documents = try fm.url(for: .documentDirectory, in: .userDomainMask, appropriateFor: nil, create: false)
        let configured = ProcessInfo.processInfo.environment["YOUSPEED_CITY_LOOKUP_CASES"]
        let casesURL = configured.map { URL(fileURLWithPath: $0) }
            ?? documents.appendingPathComponent("CityLookupFixture/cases.json")
        guard fm.fileExists(atPath: casesURL.path) else {
            throw XCTSkip("Explicit full-region city lookup fixture is absent")
        }
        #if !targetEnvironment(simulator)
        // The driver's installed app currently carries the historical TestHost
        // suffix. An acceptance run must use a different, explicit container.
        guard Bundle.main.bundleIdentifier == "de.youspeed.SpeedConsumer.CityLookupTests" else {
            throw XCTSkip("Physical city acceptance requires the separate .CityLookupTests host")
        }
        #endif
        let staged = try JSONDecoder().decode(StagedCases.self, from: Data(contentsOf: casesURL))
        XCTAssertGreaterThanOrEqual(staged.cases.count, 3)
        guard !staged.cases.isEmpty else { throw XCTSkip("City acceptance cases are empty") }
        let database = casesURL.deletingLastPathComponent().appendingPathComponent(staged.databaseFile)
        XCTAssertTrue(fm.fileExists(atPath: database.path))
        XCTAssertEqual(database.pathExtension, "yspc", "Acceptance must exercise the packed regional map")
        return (database, staged.cases)
    }

    private func fixture(_ name: String) throws -> URL {
        let url = directory.appendingPathComponent(name)
        try execute(url, """
        CREATE TABLE ways(row_id INTEGER PRIMARY KEY,way_id TEXT UNIQUE,highway TEXT,street_name TEXT,ref TEXT,maxspeed TEXT,maxspeed_type TEXT,source_maxspeed TEXT,zone_maxspeed TEXT,traffic_sign TEXT,approx_heading_deg REAL,service TEXT,tunnel TEXT,bridge TEXT,covered TEXT,location TEXT,layer TEXT,level TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
        CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
        CREATE TABLE way_geom(row_id INTEGER PRIMARY KEY,way_id TEXT UNIQUE,points_json TEXT);
        INSERT INTO ways(row_id,way_id,highway,street_name,maxspeed,maxspeed_type,approx_heading_deg,min_lon,min_lat,max_lon,max_lat) VALUES(1,'6001','secondary','City test road','50','DE:rural',90,12.999,51.9998,13.001,52.0002);
        INSERT INTO ways_rtree VALUES(6001,12.999,13.001,51.9998,52.0002);
        INSERT INTO way_geom VALUES(1,'6001','[[52,12.999],[52,13.001]]');
        CREATE TABLE city_boundary(row_id INTEGER PRIMARY KEY,osm_type TEXT,osm_id INTEGER,admin_level INTEGER,name TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
        CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
        CREATE TABLE city_ring(boundary_row_id INTEGER,ring_index INTEGER,outer_index INTEGER,is_hole INTEGER,points_json TEXT);
        CREATE TABLE areas(row_id INTEGER PRIMARY KEY,area_id TEXT UNIQUE,geometry_type TEXT,name TEXT,place TEXT,boundary TEXT,admin_level TEXT,residential TEXT,parking TEXT,points_json TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
        CREATE INDEX idx_areas_place_admin ON areas(place,boundary,admin_level);
        CREATE VIRTUAL TABLE areas_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
        """)
        return url
    }

    private func addBoundary(at url: URL, row: Int, level: Int, name: String, polygon: Bool) throws {
        try execute(url, """
        INSERT INTO city_boundary VALUES(\(row),'relation',\(row),\(level),'\(name)',12.98,51.98,13.02,52.02);
        INSERT INTO city_boundary_rtree VALUES(\(row),12.98,13.02,51.98,52.02);
        \(polygon ? "INSERT INTO city_ring VALUES(\(row),0,0,0,'\(ring)');" : "")
        """)
    }

    private func addArea(at url: URL, row: Int, name: String, level: Int) throws {
        try execute(url, """
        INSERT INTO areas(row_id,area_id,geometry_type,name,boundary,admin_level,points_json,min_lon,min_lat,max_lon,max_lat)
        VALUES(\(row),'area:\(row)','Polygon','\(name)','administrative','\(level)','\(ring)',12.98,51.98,13.02,52.02);
        INSERT INTO areas_rtree VALUES(\(row),12.98,13.02,51.98,52.02);
        """)
    }

    private let ring = "[[12.98,51.98],[13.02,51.98],[13.02,52.02],[12.98,52.02],[12.98,51.98]]"

    private func execute(_ url: URL, _ sql: String) throws {
        var database: OpaquePointer?
        guard sqlite3_open(url.path, &database) == SQLITE_OK, let database else {
            throw NSError(domain: "CityLookupFixture", code: 1)
        }
        defer { sqlite3_close(database) }
        guard sqlite3_exec(database, sql, nil, nil, nil) == SQLITE_OK else {
            throw NSError(domain: "CityLookupFixture", code: 2,
                userInfo: [NSLocalizedDescriptionKey: String(cString: sqlite3_errmsg(database))])
        }
    }
}

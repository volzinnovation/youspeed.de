import XCTest
import SQLite3
import Darwin
@testable import SpeedConsumer

final class LookupResourceTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("lookup-resources-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: directory)
    }

    func testLazyConnectionReusesStatementsAndClearsBindings() throws {
        let url = try database("active.sqlite")
        let resources = V3LookupResources(path: url.path)
        XCTAssertEqual(resources.statistics.opens, 0)
        for value in 1...20 {
            XCTAssertEqual(try scalar(resources, sql: "SELECT ?1", value: Int32(value)), Int32(value))
        }
        XCTAssertEqual(try scalar(resources, sql: "SELECT ?1"), 0, "Bindings must not survive checkout")
        XCTAssertEqual(resources.statistics.opens, 1)
        XCTAssertEqual(resources.statistics.prepares, 1)
        XCTAssertEqual(resources.statistics.cachedStatements, 1)
        resources.invalidate()
        XCTAssertEqual(resources.statistics.closes, 1)
        XCTAssertEqual(resources.statistics.finalizes, 1)
        XCTAssertEqual(resources.statistics.cachedStatements, 0)
        XCTAssertEqual(try scalar(resources, sql: "SELECT value FROM fixture"), 1)
        XCTAssertEqual(resources.statistics.opens, 2)
    }

    func testSamePathAtomicReplacementInvalidatesAllCachesIncludingAbsentCapabilities() throws {
        // URI punctuation must remain part of the filename, never SQLite query parameters.
        let url = try database("bundle ? #.sqlite")
        let resources = V3LookupResources(path: url.path)
        XCTAssertEqual(try scalar(resources, sql: "SELECT value FROM fixture"), 1)
        try cacheFixture(resources, capability: false)
        let originalDate = try XCTUnwrap(FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as? Date)
        let replacement = try database("replacement.sqlite", value: 2)
        try FileManager.default.setAttributes([.modificationDate: originalDate], ofItemAtPath: replacement.path)
        XCTAssertEqual(rename(replacement.path, url.path), 0)
        XCTAssertEqual(try scalar(resources, sql: "SELECT value FROM fixture"), 2)
        try cacheFixture(resources, capability: true)
        XCTAssertEqual(resources.statistics.opens, 2)
        XCTAssertEqual(resources.statistics.closes, 1)
        XCTAssertEqual(resources.statistics.generation, 2)
        XCTAssertEqual(resources.statistics.geometryDecodes, 2)
        XCTAssertEqual(resources.statistics.capabilityLoads, 2)
        XCTAssertEqual(resources.statistics.cachedGeometries, 1)
    }

    func testConcurrentCallersSerializeOneConnectionAndStatement() throws {
        let url = try database("concurrent.sqlite")
        let resources = V3LookupResources(path: url.path)
        let failures = Failures()
        DispatchQueue.concurrentPerform(iterations: 100) { index in
            do {
                let actual = try self.scalar(resources, sql: "SELECT ?1", value: Int32(index))
                if actual != Int32(index) { failures.append("Binding crossed sessions: \(actual) != \(index)") }
            } catch { failures.append(String(describing: error)) }
        }
        XCTAssertEqual(failures.messages, [])
        XCTAssertEqual(resources.statistics.opens, 1)
        XCTAssertEqual(resources.statistics.prepares, 1)
        resources.invalidate()
        XCTAssertEqual(resources.statistics.opens, resources.statistics.closes)
        XCTAssertEqual(resources.statistics.prepares, resources.statistics.finalizes)
    }

    func testCachesHaveCountAndPayloadBoundsAndDoNotCacheCapabilityErrors() throws {
        let url = try database("bounded.sqlite")
        let resources = V3LookupResources(path: url.path, statementLimit: 2,
                                          geometryLimit: 2, geometryByteLimit: 40, capabilityLimit: 1)
        for index in 0..<10 { _ = try scalar(resources, sql: "SELECT \(index)") }
        XCTAssertEqual(resources.statistics.cachedStatements, 2)
        XCTAssertEqual(resources.statistics.finalizes, 8)
        _ = try resources.acquire()
        for raw in ["a", "b", "a", "c", "b"] {
            _ = resources.geometry(raw) { _ in [(1, 2)] }
        }
        XCTAssertEqual(resources.statistics.geometryDecodes, 4)
        XCTAssertEqual(resources.statistics.cachedGeometries, 2)
        XCTAssertLessThanOrEqual(resources.statistics.geometryBytes, 40)
        _ = resources.geometry(String(repeating: "x", count: 50)) { _ in [(1, 2)] }
        XCTAssertEqual(resources.statistics.cachedGeometries, 2)
        XCTAssertFalse(resources.capability("absent") { nil })
        XCTAssertTrue(resources.capability("absent") { true })
        XCTAssertTrue(resources.capability("absent") { XCTFail("Cached capability reloaded"); return false })
        XCTAssertFalse(resources.capability("uncached") { false })
        XCTAssertTrue(resources.capability("uncached") { true })
        XCTAssertEqual(resources.statistics.capabilityLoads, 4)
        resources.releaseSession()
        resources.invalidate()
        XCTAssertEqual(resources.statistics.geometryBytes, 0)
        XCTAssertEqual(resources.statistics.cachedGeometries, 0)
    }

    func testMissingFailedAndMalformedBundlesCanRecoverWithoutRetainedHandles() throws {
        let url = directory.appendingPathComponent("recover.sqlite")
        let resources = V3LookupResources(path: url.path)
        XCTAssertThrowsError(try resources.acquire())
        XCTAssertEqual(resources.statistics.opens, 0)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
        for _ in 0..<3 { XCTAssertThrowsError(try resources.acquire()) }
        XCTAssertEqual(resources.statistics.opens, 0)
        try FileManager.default.removeItem(at: url)
        try Data("not a sqlite database".utf8).write(to: url)
        XCTAssertThrowsError(try scalar(resources, sql: "SELECT value FROM fixture"))
        resources.invalidate()
        XCTAssertEqual(resources.statistics.opens, resources.statistics.closes)
        let replacement = try database("valid.sqlite", value: 3)
        XCTAssertEqual(rename(replacement.path, url.path), 0)
        XCTAssertEqual(try scalar(resources, sql: "SELECT value FROM fixture"), 3)
        try FileManager.default.removeItem(at: url)
        XCTAssertThrowsError(try resources.acquire())
        XCTAssertEqual(resources.statistics.opens, resources.statistics.closes)
    }

    func testGeometryCacheKeepsStrictSettlementDecodingSeparateFromCoordinatePairs() throws {
        let url = try database("formats.sqlite")
        let resources = V3LookupResources(path: url.path)
        _ = try resources.acquire()
        defer { resources.releaseSession() }
        let raw = "[[200,300]]"
        XCTAssertEqual(resources.geometry(raw) { _ in [(200, 300)] }.count, 1)
        XCTAssertTrue(resources.geometry(raw, format: .settlement) { _ in [] }.isEmpty)
        XCTAssertEqual(resources.geometry(raw) { _ in XCTFail("Decoded cached geometry"); return [] }.count, 1)
        XCTAssertEqual(resources.statistics.geometryDecodes, 2)
    }

    func testServiceReusesResourcesAcrossSpeedAndStreetNameLookupsForM7ThroughM12() throws {
        let url = try roadDatabase("roads.sqlite")
        let models: [V3SpeedLimitService.MatchingModel] = [
            .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic, .simpleSpeedRefStreetNameFallbackHeuristic,
            .simpleSpeedRefStreetNameGuardHeuristic, .simpleSpeedRefStreetNameGuardNodeAwareHeuristic,
            .simpleSequenceParticleHeuristic, .simpleSequenceViterbiHeuristic
        ]
        for model in models {
            let service = V3SpeedLimitService(dbPath: url.path, countryCode: "DE", matchingModel: model)
            let first = try service.lookupSpeedLimit(lat: 52.5205, lon: 13.4055)
            XCTAssertEqual(first.wayID, "100")
            XCTAssertEqual(first.speedLimitKmh, 30)
            XCTAssertEqual(try service.lookupStreetNames(forWayIDs: ["100"]), ["100": "Fixture Main Street"])
            let warm = service.resourceStatistics
            for _ in 0..<5 {
                let result = try service.lookupSpeedLimit(lat: 52.5205, lon: 13.4055)
                XCTAssertEqual(result.wayID, first.wayID)
                XCTAssertEqual(result.speedLimitKmh, first.speedLimitKmh)
                XCTAssertEqual(try service.lookupStreetNames(forWayIDs: ["100"]), ["100": "Fixture Main Street"])
            }
            XCTAssertEqual(service.resourceStatistics.opens, 1)
            XCTAssertEqual(service.resourceStatistics.prepares, warm.prepares)
            XCTAssertEqual(service.resourceStatistics.geometryDecodes, warm.geometryDecodes)
            XCTAssertGreaterThan(warm.geometryDecodes, 0)
            XCTAssertEqual(service.resourceStatistics.capabilityLoads, warm.capabilityLoads)
        }
    }

    func testServiceRefreshesSpeedNamesGeometryAndCapabilitiesAfterBundleReplacement() throws {
        let url = try roadDatabase("roads.sqlite")
        let service = V3SpeedLimitService(dbPath: url.path, matchingModel: .simpleSequenceViterbiHeuristic)
        XCTAssertEqual(try service.lookupSpeedLimit(lat: 52.5205, lon: 13.4055).speedLimitKmh, 30)
        XCTAssertEqual(try service.lookupStreetNames(forWayIDs: ["100"])["100"], "Fixture Main Street")
        let replacement = try roadDatabase("new.sqlite", speed: 50, name: "Replacement Street")
        XCTAssertEqual(rename(replacement.path, url.path), 0)
        XCTAssertEqual(try service.lookupSpeedLimit(lat: 52.5205, lon: 13.4055).speedLimitKmh, 50)
        XCTAssertEqual(try service.lookupStreetNames(forWayIDs: ["100"])["100"], "Replacement Street")
        XCTAssertEqual(service.resourceStatistics.opens, 2)
        XCTAssertEqual(service.resourceStatistics.closes, 1)
        XCTAssertEqual(service.resourceStatistics.geometryDecodes, 2)
    }

    func testRouteProbePoolIsBoundedReusesServicesAndReleasesEvictedGenerations() throws {
        let url = try roadDatabase("pool.sqlite")
        let pool = V3SpeedLimitServicePool(limit: 2)
        var first: V3SpeedLimitService? = pool.service(dbPath: url.path, bundleIdentity: "v1", countryCode: "DE", matchingModel: .simpleSpeedRefHeuristic)
        weak var released = first
        XCTAssertTrue(first === pool.service(dbPath: url.path, bundleIdentity: "v1", countryCode: "DE", matchingModel: .simpleSpeedRefHeuristic))
        _ = try first?.lookupStreetNames(forWayIDs: ["100"])
        first = nil
        let replacement = pool.service(dbPath: url.path, bundleIdentity: "v2", countryCode: "DE", matchingModel: .simpleSpeedRefHeuristic)
        XCTAssertNil(released)
        XCTAssertEqual(pool.count, 1)
        XCTAssertEqual(replacement.resourceStatistics.opens, 0)
        weak var evicted = pool.service(dbPath: "other", countryCode: "DE", matchingModel: .simpleSpeedRefHeuristic)
        _ = pool.service(dbPath: url.path, bundleIdentity: "v2", countryCode: "DE", matchingModel: .simpleSpeedRefHeuristic)
        _ = pool.service(dbPath: "third", countryCode: "DE", matchingModel: .simpleSpeedRefHeuristic)
        XCTAssertNil(evicted)
        XCTAssertEqual(pool.count, 2)
        pool.removeAll()
        XCTAssertEqual(pool.count, 0)
        // A retained in-flight service remains usable after pool eviction.
        XCTAssertEqual(try replacement.lookupStreetNames(forWayIDs: ["100"])["100"], "Fixture Main Street")
    }

    private func cacheFixture(_ resources: V3LookupResources, capability: Bool) throws {
        _ = try resources.acquire()
        defer { resources.releaseSession() }
        XCTAssertEqual(resources.capability("optional_table") { capability }, capability)
        _ = resources.geometry("points") { _ in [(1, 2)] }
    }

    private func scalar(_ resources: V3LookupResources, sql: String, value: Int32? = nil) throws -> Int32 {
        let session = try resources.acquire()
        defer { resources.releaseSession() }
        var statement: OpaquePointer?
        guard resources.prepare(session.db, sql, -1, &statement, nil) == SQLITE_OK, let statement else {
            throw ConsumerAppError.sqlite("Test prepare failed")
        }
        defer { resources.release(statement) }
        if let value { sqlite3_bind_int(statement, 1, value) }
        guard sqlite3_step(statement) == SQLITE_ROW else { throw ConsumerAppError.sqlite("Test step failed") }
        return sqlite3_column_int(statement, 0)
    }

    private func database(_ name: String, value: Int = 1) throws -> URL {
        let url = directory.appendingPathComponent(name)
        try execute(url, "CREATE TABLE fixture(value INTEGER); INSERT INTO fixture VALUES (\(value));")
        return url
    }

    private func roadDatabase(_ filename: String, speed: Int = 30, name: String = "Fixture Main Street") throws -> URL {
        let url = directory.appendingPathComponent(filename)
        try execute(url, """
            CREATE TABLE ways(row_id INTEGER PRIMARY KEY, way_id TEXT UNIQUE, highway TEXT, street_name TEXT,
              ref TEXT, maxspeed TEXT, maxspeed_type TEXT, source_maxspeed TEXT, approx_heading_deg REAL,
              service TEXT, tunnel TEXT, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL);
            CREATE TABLE way_geom(row_id INTEGER PRIMARY KEY, way_id TEXT UNIQUE, points_json TEXT);
            CREATE TABLE areas(row_id INTEGER PRIMARY KEY, name TEXT, place TEXT, boundary TEXT, admin_level TEXT,
              min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL, points_json TEXT);
            CREATE VIRTUAL TABLE areas_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
            INSERT INTO ways VALUES(1,'100','residential','\(name)',NULL,'\(speed)',NULL,NULL,45,NULL,NULL,13.405,52.520,13.406,52.521);
            INSERT INTO way_geom VALUES(1,'100','[[52.520,13.405],[52.521,13.406]]');
            """)
        return url
    }

    private func execute(_ url: URL, _ sql: String) throws {
        var connection: OpaquePointer?
        let code = sqlite3_open(url.path, &connection)
        guard let connection else { throw ConsumerAppError.sqlite("Test open failed") }
        defer { sqlite3_close(connection) }
        guard code == SQLITE_OK, sqlite3_exec(connection, sql, nil, nil, nil) == SQLITE_OK else {
            throw ConsumerAppError.sqlite(String(cString: sqlite3_errmsg(connection)))
        }
    }

    private final class Failures: @unchecked Sendable {
        private let lock = NSLock()
        private var values: [String] = []
        func append(_ value: String) { lock.lock(); defer { lock.unlock() }; values.append(value) }
        var messages: [String] { lock.lock(); defer { lock.unlock() }; return values }
    }
}

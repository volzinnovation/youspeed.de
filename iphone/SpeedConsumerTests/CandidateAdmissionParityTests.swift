import Foundation
import SQLite3
import XCTest
@testable import SpeedConsumer

final class CandidateAdmissionParityTests: XCTestCase {
    private struct Corpus: Decodable {
        let schemaVersion: Int
        let variants: [String]
        let scenarios: [Scenario]
        let lookup: Lookup
    }
    private struct Scenario: Decodable {
        let id: String
        let latitude: Double
        let longitude: Double
        let radiusM: Double
        let maxCandidates: Int
        let wayIDs: [String]
    }
    private struct Lookup: Decodable {
        let latitude: Double
        let longitude: Double
        let wayID: String
        let speedLimitKmh: Int
    }

    func testSharedDenseCandidateAndProfileCorpus() throws {
        let bundle = Bundle(for: Self.self)
        let corpus = try JSONDecoder().decode(Corpus.self, from: Data(contentsOf: XCTUnwrap(bundle.url(forResource: "candidate-admission-v1", withExtension: "json"))))
        let sql = try String(contentsOf: XCTUnwrap(bundle.url(forResource: "candidate-admission-v1", withExtension: "sql")), encoding: .utf8)
        XCTAssertEqual(corpus.schemaVersion, 1)
        for variant in corpus.variants {
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("candidate-parity-\(UUID().uuidString).sqlite")
            defer { try? FileManager.default.removeItem(at: file) }
            var db: OpaquePointer?
            XCTAssertEqual(sqlite3_open(file.path, &db), SQLITE_OK)
            let handle = try XCTUnwrap(db)
            do {
                defer { sqlite3_close(handle) }
                XCTAssertEqual(sqlite3_exec(handle, sql, nil, nil, nil), SQLITE_OK, String(cString: sqlite3_errmsg(handle)))
                let table = variant == "general_rtree" ? "ways_rtree" : (variant == "network_rtree" ? "surface_way_network_rtree" : nil)
                if let table {
                    XCTAssertEqual(sqlite3_exec(handle, "CREATE VIRTUAL TABLE \(table) USING rtree(way_id,min_lon,max_lon,min_lat,max_lat); INSERT INTO \(table) SELECT way_id,min_lon,max_lon,min_lat,max_lat FROM ways ORDER BY way_id DESC", nil, nil, nil), SQLITE_OK)
                }
            }
            let service = V3SpeedLimitService(dbPath: file.path, countryCode: "DEU")
            for scenario in corpus.scenarios {
                let actual = try service.admittedWayIDsForTesting(lat: scenario.latitude, lon: scenario.longitude,
                    radiusM: scenario.radiusM, maxCandidates: scenario.maxCandidates)
                XCTAssertEqual(actual, scenario.wayIDs, "\(variant)/\(scenario.id)")
            }
            let models: [V3SpeedLimitService.MatchingModel] = [.simpleSpeedRefUrbanReleaseNarrowWindowHeuristic,
                .simpleSpeedRefStreetNameFallbackHeuristic, .simpleSpeedRefStreetNameGuardHeuristic,
                .simpleSpeedRefStreetNameGuardNodeAwareHeuristic, .simpleSequenceParticleHeuristic, .simpleSequenceViterbiHeuristic]
            for model in models {
                let lookup = V3SpeedLimitService(dbPath: file.path, countryCode: "DEU", matchingModel: model)
                for _ in 0..<10 {
                    let result = try lookup.lookupSpeedLimit(lat: corpus.lookup.latitude, lon: corpus.lookup.longitude,
                        radiusM: 200, maxCandidates: 2, headingDeg: 90, speedKmh: 40, horizontalAccuracyM: 5, gpsSignalBars: 4)
                    XCTAssertEqual(result.wayID, corpus.lookup.wayID, "\(variant)/\(model)")
                    XCTAssertEqual(result.speedLimitKmh, corpus.lookup.speedLimitKmh, "\(variant)/\(model)")
                }
            }
        }
    }
}

import Foundation
import SQLite3
import XCTest
@testable import SpeedConsumer

/// Both native matchers consume these exact geometries, contexts and expected decisions.
final class MatcherSequenceParityTests: XCTestCase {
    private struct Corpus: Decodable { let schemaVersion: Int; let scenarios: [Scenario] }
    private struct Scenario: Decodable {
        let id: String, fixture: String, profile: String, wayID: String
        let lat: Double, lon: Double, radiusM: Double, speedKmh: Double, horizontalAccuracyM: Double
        let headingDeg: Double?
        let gpsSignalBars: Int
        let context: Context?
        let isTunnelSegment: Bool
    }
    private struct Fix: Decodable {
        let lat: Double, lon: Double
        let headingDeg: Double?, headingAccuracyDeg: Double?, speedKmh: Double?, horizontalAccuracyM: Double?
        let gpsSignalBars: Int?
        var native: WayMatchRecentFix {
            WayMatchRecentFix(lat: lat, lon: lon, headingDeg: headingDeg, headingAccuracyDeg: headingAccuracyDeg,
                speedKmh: speedKmh, horizontalAccuracyM: horizontalAccuracyM, gpsSignalBars: gpsSignalBars)
        }
    }
    private struct Context: Decodable {
        let preferredWayID: String?, preferredHighway: String?, preferredStreetRef: String?, activeStreetRef: String?, preferredStreetName: String?
        let preferredEndpointProximityM: Double?, tunnelApproachBaselineAccuracyM: Double?
        let recentWayIDs: [String]?, recentStreetRefs: [String]?, recentTunnelCandidateWayIDs: [String]?, recentTunnelCandidateRefs: [String]?
        let recentTunnelApproachWayIDs: [String]?, recentTunnelApproachRefs: [String]?
        let recentFixes: [Fix]?
        let tunnelApproachFixCount: Int?, tunnelApproachBaselineSignalBars: Int?
        let isInTunnelMode: Bool?
        var native: WayMatchContext {
            WayMatchContext(preferredWayID: preferredWayID, preferredHighway: preferredHighway,
                preferredEndpointProximityM: preferredEndpointProximityM, recentWayIDs: recentWayIDs ?? [],
                recentFixes: recentFixes?.map(\.native) ?? [], preferredStreetRef: preferredStreetRef,
                activeStreetRef: activeStreetRef, preferredStreetName: preferredStreetName, recentStreetRefs: recentStreetRefs ?? [],
                recentTunnelCandidateWayIDs: recentTunnelCandidateWayIDs ?? [], recentTunnelCandidateRefs: recentTunnelCandidateRefs ?? [],
                recentTunnelApproachWayIDs: recentTunnelApproachWayIDs ?? [], recentTunnelApproachRefs: recentTunnelApproachRefs ?? [],
                tunnelApproachFixCount: tunnelApproachFixCount ?? 0, tunnelApproachBaselineAccuracyM: tunnelApproachBaselineAccuracyM,
                tunnelApproachBaselineSignalBars: tunnelApproachBaselineSignalBars, isInTunnelMode: isInTunnelMode ?? false)
        }
    }
    func testSharedHistoryAndTunnelCorpusColdAndWarm() throws {
        let bundle = Bundle(for: Self.self)
        let corpus = try JSONDecoder().decode(Corpus.self, from: Data(contentsOf: XCTUnwrap(bundle.url(forResource: "sequence-v1", withExtension: "json"))))
        XCTAssertEqual(corpus.schemaVersion, 1)
        let models: [String: V3SpeedLimitService.MatchingModel] = ["m7": .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic,
            "m8": .simpleSpeedRefStreetNameFallbackHeuristic, "m9": .simpleSpeedRefStreetNameGuardHeuristic,
            "m10": .simpleSpeedRefStreetNameGuardNodeAwareHeuristic, "m11": .simpleSequenceParticleHeuristic, "m12": .simpleSequenceViterbiHeuristic]
        for scenario in corpus.scenarios {
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("sequence-parity-\(UUID().uuidString).sqlite")
            defer { try? FileManager.default.removeItem(at: file) }
            let fixture = try XCTUnwrap(bundle.url(forResource: scenario.fixture, withExtension: nil, subdirectory: "fixtures"))
            let sql = try String(contentsOf: fixture, encoding: .utf8)
            var db: OpaquePointer?
            XCTAssertEqual(sqlite3_open(file.path, &db), SQLITE_OK)
            let handle = try XCTUnwrap(db)
            do {
                defer { sqlite3_close(handle) }
                XCTAssertEqual(sqlite3_exec(handle, sql, nil, nil, nil), SQLITE_OK, String(cString: sqlite3_errmsg(handle)))
            }
            let service = V3SpeedLimitService(dbPath: file.path, matchingModel: try XCTUnwrap(models[scenario.profile]))
            for iteration in 0..<3 {
                let result = try service.lookupSpeedLimit(lat: scenario.lat, lon: scenario.lon, radiusM: scenario.radiusM,
                    maxCandidates: 32, matchContext: scenario.context?.native, headingDeg: scenario.headingDeg,
                    speedKmh: scenario.speedKmh, horizontalAccuracyM: scenario.horizontalAccuracyM, gpsSignalBars: scenario.gpsSignalBars)
                XCTAssertEqual(result.wayID, scenario.wayID, "\(scenario.id)/\(iteration): \(result.selectionTrace)")
                XCTAssertEqual(result.isTunnelSegment, scenario.isTunnelSegment, "\(scenario.id)/\(iteration)")
            }
        }
    }
}

import Foundation

final class RouteScenarioBenchmarkRunner {
    private let dbPath: String
    private let service: V3SpeedLimitService

    init(dbPath: String) {
        self.dbPath = dbPath
        self.service = V3SpeedLimitService(dbPath: dbPath)
    }

    func run(
        scenarios: [RouteScenario],
        repeats: Int,
        mode: RouteBenchmarkMode
    ) throws -> KarlsruheVariantReport {
        guard repeats > 0 else {
            throw BenchmarkError.invalidDB("Route benchmark repeats must be > 0")
        }

        let attrs = try FileManager.default.attributesOfItem(atPath: dbPath)
        let dbSize = (attrs[.size] as? NSNumber)?.int64Value ?? 0
        let reports = try scenarios.map { try runScenario($0, repeats: repeats, mode: mode) }

        let formatter = ISO8601DateFormatter()
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return KarlsruheVariantReport(
            generatedAtUTC: formatter.string(from: Date()),
            dbPath: dbPath,
            dbSizeBytes: dbSize,
            mode: mode,
            scenarios: reports
        )
    }

    private func runScenario(
        _ scenario: RouteScenario,
        repeats: Int,
        mode: RouteBenchmarkMode
    ) throws -> RouteScenarioReport {
        var scenarioDurationsMs: [Double] = []
        scenarioDurationsMs.reserveCapacity(repeats)
        var totalFixCount = 0
        var totalFixDurationMs = 0.0
        var mismatchedWayCount = 0
        var tunnelMismatchCount = 0

        for _ in 0..<repeats {
            let t0 = DispatchTime.now().uptimeNanoseconds
            var recentWayIDs: [String] = []
            var recentStreetRefs: [String] = []
            var recentHypotheses: [WayMatchHypothesis] = []
            var recentTunnelCandidateWayIDs: [String] = []
            var recentTunnelCandidateRefs: [String] = []
            var preferredWayID: String?
            var matchedFixCount = 0
            var isInTunnelMode = false

            for sample in scenario.samples {
                let queryStart = DispatchTime.now().uptimeNanoseconds
                let result = try service.lookupSpeedLimit(
                    lat: sample.lat,
                    lon: sample.lon,
                    radiusM: sample.radiusM,
                    maxCandidates: 64,
                    matchContext: WayMatchContext(
                        preferredWayID: preferredWayID,
                        recentWayIDs: recentWayIDs,
                        preferredStreetRef: recentStreetRefs.first,
                        recentStreetRefs: recentStreetRefs,
                        recentTunnelCandidateWayIDs: recentTunnelCandidateWayIDs,
                        recentTunnelCandidateRefs: recentTunnelCandidateRefs,
                        recentHypotheses: recentHypotheses,
                        matchedFixCount: matchedFixCount,
                        isInTunnelMode: isInTunnelMode
                    ),
                    headingDeg: sample.headingDeg,
                    headingAccuracyDeg: 10.0,
                    speedKmh: scenario.speedKmh,
                    horizontalAccuracyM: scenario.horizontalAccuracyM
                )

                let queryEnd = DispatchTime.now().uptimeNanoseconds
                totalFixDurationMs += Double(queryEnd - queryStart) / 1_000_000.0
                totalFixCount += 1

                if result.wayID != sample.expectedWayID {
                    mismatchedWayCount += 1
                }
                if scenario.id == RouteScenario.gernsbachTunnelSurface.id, result.isTunnelSegment {
                    tunnelMismatchCount += 1
                }

                if let wayID = result.wayID {
                    matchedFixCount += 1
                    recentWayIDs.removeAll(where: { $0 == wayID })
                    recentWayIDs.insert(wayID, at: 0)
                    if recentWayIDs.count > 5 {
                        recentWayIDs.removeLast(recentWayIDs.count - 5)
                    }
                    preferredWayID = wayID
                }
                for ref in V3SpeedLimitService.normalizedRefTokens(result.streetRef) {
                    recentStreetRefs.removeAll(where: { $0 == ref })
                    recentStreetRefs.insert(ref, at: 0)
                    if recentStreetRefs.count > 6 {
                        recentStreetRefs.removeLast(recentStreetRefs.count - 6)
                    }
                }
                recentHypotheses = result.matchHypotheses
                recentTunnelCandidateWayIDs = result.nearbyTunnelCandidateWayIDs
                recentTunnelCandidateRefs = result.nearbyTunnelCandidateRefs
                isInTunnelMode = result.isTunnelSegment
            }
            let t1 = DispatchTime.now().uptimeNanoseconds
            scenarioDurationsMs.append(Double(t1 - t0) / 1_000_000.0)
        }

        let sorted = scenarioDurationsMs.sorted()
        let avgScenarioMs = scenarioDurationsMs.reduce(0.0, +) / Double(scenarioDurationsMs.count)
        return RouteScenarioReport(
            scenarioID: scenario.id,
            mode: mode,
            repeats: repeats,
            timing: RouteScenarioTiming(
                avgScenarioMs: rounded(avgScenarioMs),
                p50ScenarioMs: rounded(sorted[sorted.count / 2]),
                minScenarioMs: rounded(sorted.first ?? 0.0),
                maxScenarioMs: rounded(sorted.last ?? 0.0),
                avgFixMs: rounded(totalFixDurationMs / Double(max(totalFixCount, 1)))
            ),
            mismatchedWayCount: mismatchedWayCount,
            tunnelMismatchCount: tunnelMismatchCount
        )
    }

    private func rounded(_ value: Double) -> Double {
        (value * 100.0).rounded() / 100.0
    }
}

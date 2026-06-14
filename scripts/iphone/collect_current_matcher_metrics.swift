import Foundation

struct TrackPoint {
    let lat: Double
    let lon: Double
}

struct DriveLogReplayMetrics {
    var replayedFixCount = 0
    var pseudoLabelExampleCount = 0
    var correctPseudoLabelCount = 0
    var changedExampleCount = 0
    var changedCorrectCount = 0
    var unchangedExampleCount = 0
    var unchangedCorrectCount = 0
    var usedThreeWayGateCount = 0
    var usedSameRefBounceGateCount = 0
    var usedAntiABAHysteresisCount = 0

    var accuracy: Double {
        guard pseudoLabelExampleCount > 0 else {
            return 0.0
        }
        return Double(correctPseudoLabelCount) / Double(pseudoLabelExampleCount)
    }

    var changedRecall: Double {
        guard changedExampleCount > 0 else {
            return 0.0
        }
        return Double(changedCorrectCount) / Double(changedExampleCount)
    }

    var unchangedAccuracy: Double {
        guard unchangedExampleCount > 0 else {
            return 0.0
        }
        return Double(unchangedCorrectCount) / Double(unchangedExampleCount)
    }

    mutating func formUnion(_ other: DriveLogReplayMetrics) {
        replayedFixCount += other.replayedFixCount
        pseudoLabelExampleCount += other.pseudoLabelExampleCount
        correctPseudoLabelCount += other.correctPseudoLabelCount
        changedExampleCount += other.changedExampleCount
        changedCorrectCount += other.changedCorrectCount
        unchangedExampleCount += other.unchangedExampleCount
        unchangedCorrectCount += other.unchangedCorrectCount
        usedThreeWayGateCount += other.usedThreeWayGateCount
        usedSameRefBounceGateCount += other.usedSameRefBounceGateCount
        usedAntiABAHysteresisCount += other.usedAntiABAHysteresisCount
    }
}

struct BundledMatchContextState {
    var recentWayIDs: [String] = []
    var recentFixes: [WayMatchRecentFix] = []
    var recentStreetRefs: [String] = []
    var recentHypotheses: [WayMatchHypothesis] = []
    var recentTunnelCandidateWayIDs: [String] = []
    var recentTunnelCandidateRefs: [String] = []
    var recentTunnelApproachWayIDs: [String] = []
    var recentTunnelApproachRefs: [String] = []
    var preferredWayID: String?
    var preferredHighway: String?
    var preferredEndpointProximityM: Double?
    var matchedFixCount = 0
    var tunnelApproachFixCount = 0
    var tunnelApproachBaselineAccuracyM: Double?
    var tunnelApproachBaselineSignalBars: Int?
    var isInTunnelMode = false
    var isInMotorwayMode = false
    var activeCorridorState: CorridorMatchState?
    var approachCorridorState: CorridorMatchState?
    var approachCorridorFixCount = 0
    var approachCorridorStartDepthM: Double?
    var approachCorridorStartDepthNodes: Int?

    var context: WayMatchContext? {
        guard preferredWayID != nil ||
                !recentWayIDs.isEmpty ||
                !recentStreetRefs.isEmpty ||
                !recentFixes.isEmpty ||
                !recentHypotheses.isEmpty ||
                !recentTunnelCandidateWayIDs.isEmpty ||
                !recentTunnelCandidateRefs.isEmpty ||
                !recentTunnelApproachWayIDs.isEmpty ||
                !recentTunnelApproachRefs.isEmpty ||
                tunnelApproachFixCount > 0 ||
                isInMotorwayMode ||
                activeCorridorState != nil ||
                approachCorridorState != nil ||
                approachCorridorStartDepthM != nil ||
                approachCorridorStartDepthNodes != nil ||
                isInTunnelMode else {
            return nil
        }
        return WayMatchContext(
            preferredWayID: preferredWayID,
            preferredHighway: preferredHighway,
            preferredEndpointProximityM: preferredEndpointProximityM,
            recentWayIDs: recentWayIDs,
            recentFixes: recentFixes,
            preferredStreetRef: recentStreetRefs.first,
            recentStreetRefs: recentStreetRefs,
            recentTunnelCandidateWayIDs: recentTunnelCandidateWayIDs,
            recentTunnelCandidateRefs: recentTunnelCandidateRefs,
            recentTunnelApproachWayIDs: recentTunnelApproachWayIDs,
            recentTunnelApproachRefs: recentTunnelApproachRefs,
            tunnelApproachFixCount: tunnelApproachFixCount,
            tunnelApproachBaselineAccuracyM: tunnelApproachBaselineAccuracyM,
            tunnelApproachBaselineSignalBars: tunnelApproachBaselineSignalBars,
            recentHypotheses: recentHypotheses,
            matchedFixCount: matchedFixCount,
            isInTunnelMode: isInTunnelMode,
            isInMotorwayMode: isInMotorwayMode,
            activeCorridorState: activeCorridorState,
            approachCorridorState: approachCorridorState,
            approachCorridorFixCount: approachCorridorFixCount,
            approachCorridorStartDepthM: approachCorridorStartDepthM,
            approachCorridorStartDepthNodes: approachCorridorStartDepthNodes
        )
    }

    mutating func record(
        _ result: SpeedLimitResult,
        lat: Double? = nil,
        lon: Double? = nil,
        headingDeg: Double? = nil,
        headingAccuracyDeg: Double? = nil,
        speedKmh: Double? = nil,
        horizontalAccuracyM: Double,
        gpsSignalBars: Int
    ) {
        if let wayID = result.wayID {
            matchedFixCount += 1
            recentWayIDs.removeAll(where: { $0 == wayID })
            recentWayIDs.insert(wayID, at: 0)
            if recentWayIDs.count > 5 {
                recentWayIDs.removeLast(recentWayIDs.count - 5)
            }
            preferredWayID = wayID
        }
        if let lat, let lon {
            recentFixes.insert(
                WayMatchRecentFix(
                    lat: lat,
                    lon: lon,
                    headingDeg: headingDeg,
                    headingAccuracyDeg: headingAccuracyDeg,
                    speedKmh: speedKmh,
                    horizontalAccuracyM: horizontalAccuracyM,
                    gpsSignalBars: gpsSignalBars
                ),
                at: 0
            )
            if recentFixes.count > 10 {
                recentFixes.removeLast(recentFixes.count - 10)
            }
        }
        preferredHighway = result.highway
        preferredEndpointProximityM = result.matchedEndpointProximityM
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
        updateTunnelApproachState(
            result: result,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        )
        updateApproachCorridorState(result: result)
        activeCorridorState = result.activeCorridorState
        isInTunnelMode = result.isTunnelSegment
        let resultHighway = result.highway?.lowercased()
        if resultHighway == "motorway" {
            isInMotorwayMode = true
        } else if resultHighway == "motorway_link" {
            isInMotorwayMode = isInMotorwayMode || result.activeCorridorState?.kind == "motorway"
        } else {
            isInMotorwayMode = false
        }
    }

    private mutating func updateTunnelApproachState(
        result: SpeedLimitResult,
        horizontalAccuracyM: Double,
        gpsSignalBars: Int
    ) {
        let approachTraces = result.candidateTraces.filter(Self.isTunnelApproachCandidateTrace)
        guard !result.isTunnelSegment, !approachTraces.isEmpty else {
            recentTunnelApproachWayIDs.removeAll(keepingCapacity: false)
            recentTunnelApproachRefs.removeAll(keepingCapacity: false)
            tunnelApproachFixCount = 0
            tunnelApproachBaselineAccuracyM = nil
            tunnelApproachBaselineSignalBars = nil
            return
        }

        tunnelApproachFixCount += 1
        if horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0 {
            if let baseline = tunnelApproachBaselineAccuracyM {
                tunnelApproachBaselineAccuracyM = min(baseline, horizontalAccuracyM)
            } else {
                tunnelApproachBaselineAccuracyM = horizontalAccuracyM
            }
        }
        tunnelApproachBaselineSignalBars = max(tunnelApproachBaselineSignalBars ?? gpsSignalBars, gpsSignalBars)

        recentTunnelApproachWayIDs.removeAll(keepingCapacity: false)
        recentTunnelApproachRefs.removeAll(keepingCapacity: false)
        for trace in approachTraces {
            if let wayID = trace.wayID {
                recentTunnelApproachWayIDs.removeAll(where: { $0 == wayID })
                recentTunnelApproachWayIDs.insert(wayID, at: 0)
                if recentTunnelApproachWayIDs.count > 5 {
                    recentTunnelApproachWayIDs.removeLast(recentTunnelApproachWayIDs.count - 5)
                }
            }
            for refToken in V3SpeedLimitService.normalizedRefTokens(trace.streetRef) {
                recentTunnelApproachRefs.removeAll(where: { $0 == refToken })
                recentTunnelApproachRefs.insert(refToken, at: 0)
                if recentTunnelApproachRefs.count > 6 {
                    recentTunnelApproachRefs.removeLast(recentTunnelApproachRefs.count - 6)
                }
            }
        }
    }

    private mutating func updateApproachCorridorState(result: SpeedLimitResult) {
        guard result.activeCorridorState == nil else {
            approachCorridorState = nil
            approachCorridorFixCount = 0
            approachCorridorStartDepthM = nil
            approachCorridorStartDepthNodes = nil
            return
        }
        let corridorTrace = result.candidateTraces.first(where: { trace in
            guard trace.corridorKind != nil,
                  trace.corridorID != nil,
                  trace.corridorSideNodeKey != nil,
                  trace.corridorDepthM != nil,
                  trace.corridorRemainingM != nil,
                  trace.corridorDepthNodes != nil,
                  trace.corridorRemainingNodes != nil else {
                return false
            }
            guard trace.corridorKind == "tunnel" || trace.corridorKind == "motorway" else {
                return false
            }
            return trace.corridorEntryZone == true
        }) ?? approachCorridorState.flatMap { currentState in
            result.candidateTraces.first(where: { trace in
                guard trace.corridorKind == currentState.kind,
                      trace.corridorID == currentState.corridorID,
                      trace.corridorSideNodeKey == currentState.sideNodeKey,
                      let depthM = trace.corridorDepthM,
                      trace.corridorRemainingM != nil,
                      trace.corridorDepthNodes != nil,
                      trace.corridorRemainingNodes != nil else {
                    return false
                }
                return depthM + 6.0 >= currentState.depthM
            })
        }
        guard let trace = corridorTrace,
              let corridorKind = trace.corridorKind,
              let corridorID = trace.corridorID,
              let sideNodeKey = trace.corridorSideNodeKey,
              let depthM = trace.corridorDepthM,
              let remainingM = trace.corridorRemainingM,
              let depthNodes = trace.corridorDepthNodes,
              let remainingNodes = trace.corridorRemainingNodes else {
            approachCorridorState = nil
            approachCorridorFixCount = 0
            approachCorridorStartDepthM = nil
            approachCorridorStartDepthNodes = nil
            return
        }

        let nextState = CorridorMatchState(
            kind: corridorKind,
            corridorID: corridorID,
            sideNodeKey: sideNodeKey,
            depthM: depthM,
            spanM: depthM + remainingM,
            depthNodes: depthNodes,
            spanNodes: depthNodes + remainingNodes
        )
        if let currentState = approachCorridorState,
           currentState.kind == nextState.kind,
           currentState.corridorID == nextState.corridorID,
           currentState.sideNodeKey == nextState.sideNodeKey,
           nextState.depthM + 6.0 >= currentState.depthM {
            approachCorridorFixCount += 1
            let startDepthM = approachCorridorStartDepthM ?? currentState.depthM
            approachCorridorStartDepthM = min(startDepthM, nextState.depthM)
            let startDepthNodes = approachCorridorStartDepthNodes ?? currentState.depthNodes
            approachCorridorStartDepthNodes = min(startDepthNodes, nextState.depthNodes)
        } else {
            approachCorridorFixCount = 1
            approachCorridorStartDepthM = nextState.depthM
            approachCorridorStartDepthNodes = nextState.depthNodes
        }
        approachCorridorState = nextState
    }

    private static func isTunnelApproachCandidateTrace(_ trace: MatchCandidateTrace) -> Bool {
        let isTunnel = (trace.tunnel ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "yes"
        return isTunnel && trace.portalEligible == true
    }
}

struct FieldReplayLogSummary: Codable {
    let logName: String
    let annotatedLogPath: String
    let replayed: Int
    let portalTunnel: Int
    let selectedTunnel: Int
    let motorway: Int
    let motorwayLink: Int
    let focusReplayCandidate: Int
    let focusReplaySelected: Int
    let focusLoggedCandidate: Int
    let focusLoggedSelected: Int
}

struct FieldReplaySummary: Codable {
    let logCount: Int
    let replayedFixCount: Int
    let portalEligibleTunnelFixCount: Int
    let selectedTunnelFixCount: Int
    let motorwayFixCount: Int
    let motorwayLinkFixCount: Int
    let focusWayID: String
    let focusReplayCandidateFixCount: Int
    let focusReplaySelectedFixCount: Int
    let focusLoggedCandidateFixCount: Int
    let focusLoggedSelectedFixCount: Int
    let perLog: [FieldReplayLogSummary]
}

struct GeomReplayLogSummary: Codable {
    let logName: String
    let annotatedLogPath: String
    let replayedFixCount: Int
    let pseudoLabelExampleCount: Int
    let accuracy: Double
    let changedRecall: Double
    let unchangedAccuracy: Double
    let loggedComparable: Int
    let loggedAgreement: Double
    let replayPortalEligibleTunnelFixCount: Int
    let loggedPortalEligibleTunnelFixCount: Int
    let replayTunnelFixCount: Int
    let loggedTunnelFixCount: Int
    let replayWayABAOscillations: Int
    let loggedWayABAOscillations: Int
    let replaySameRefABAOscillations: Int
    let loggedSameRefABAOscillations: Int
}

struct GeomReplaySummary: Codable {
    let logCount: Int
    let replayedFixCount: Int
    let pseudoLabelExampleCount: Int
    let accuracy: Double
    let changedRecall: Double
    let unchangedAccuracy: Double
    let usedThreeWayGateCount: Int
    let loggedComparable: Int
    let loggedAgreement: Double
    let replayPortalEligibleTunnelFixCount: Int
    let loggedPortalEligibleTunnelFixCount: Int
    let replayTunnelFixCount: Int
    let loggedTunnelFixCount: Int
    let replayWayABAOscillations: Int
    let loggedWayABAOscillations: Int
    let replaySameRefABAOscillations: Int
    let loggedSameRefABAOscillations: Int
    let perLog: [GeomReplayLogSummary]
}

struct ProfileSummary: Codable {
    let label: String
    let bytes: UInt64
    let replayedFixCount: Int
    let pseudoLabelExampleCount: Int
    let changedExampleCount: Int
    let accuracy: Double
    let changedRecall: Double
    let unchangedAccuracy: Double
    let usedThreeWayGateCount: Int
    let usedSameRefBounceGateCount: Int
    let usedAntiABAHysteresisCount: Int
    let geomLogAgreement: Double
    let geomReplayTunnel: Int
    let geomWayABA: Int
    let geomSameRefABA: Int
    let latencyE2EMedian: Double
    let latencyServiceP95: Double
    let focusReplayCandidate: Int
    let focusReplaySelected: Int
    let focusReplayCandidateOutsideLog3: Int
    let focusReplaySelectedOutsideLog3: Int
    let selectedTunnel: Int
    let accuracyComposite: Double
    let commonScore: Double
}

struct ProfileDeltaSummary: Codable {
    let label: String
    let correctedExamples: Int
    let regressedExamples: Int
    let netCorrections: Int
    let correctedChangedExamples: Int
    let regressedChangedExamples: Int
    let netChangedCorrections: Int
    let correctedUnchangedExamples: Int
    let regressedUnchangedExamples: Int
    let netUnchangedCorrections: Int
    let geomWayABADelta: Int
    let geomSameRefABADelta: Int
    let accuracyDelta: Double
    let changedRecallDelta: Double
    let unchangedAccuracyDelta: Double
    let commonScoreDelta: Double
}

struct RuntimeReplayMacros: Codable {
    let replayAllLogs: Int
    let replayAllLogFixes: Int
    let replayPseudoExamples: Int
    let replayChangedExamples: Int
    let replayAccuracyPct: Double
    let replayChangedRecallPct: Double
    let replayUnchangedAccuracyPct: Double
    let replayThreeWayGateActivations: Int
}

struct MetricsOutput: Codable {
    let generatedAtUTC: String
    let repoRoot: String
    let annotatedLogDirectory: String
    let inspectorLogs: [String]
    let geomLogs: [String]
    let fieldReplay: FieldReplaySummary
    let geomReplay: GeomReplaySummary
    let profiles: [ProfileSummary]
    let profileDeltas: [ProfileDeltaSummary]
    let runtimeReplayMacros: RuntimeReplayMacros
}

struct Args {
    let repoRoot: URL
    let bundledDB: URL
    let baselineDB: URL
    let corridorDB: URL
    let annotatedLogDir: URL
    let outputJSON: URL?
}

enum ArgumentError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case .message(let message):
            return message
        }
    }
}

func parseArgs() throws -> Args {
    let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
    var repoRoot = cwd
    var bundledDB = cwd
        .appendingPathComponent("mapdata", isDirectory: true)
        .appendingPathComponent("bundles", isDirectory: true)
        .appendingPathComponent("v3", isDirectory: true)
        .appendingPathComponent("karlsruhe-regbez", isDirectory: true)
        .appendingPathComponent("latest", isDirectory: true)
        .appendingPathComponent("karlsruhe-regbez_speeds.sqlite")
    var baselineDB = URL(fileURLWithPath: "/tmp/karlsruhe-regbez-baseline.sqlite")
    var corridorDB = URL(fileURLWithPath: "/tmp/karlsruhe-regbez-corridor.sqlite")
    var annotatedLogDir: URL?
    var outputJSON: URL?

    var iterator = CommandLine.arguments.dropFirst().makeIterator()
    while let arg = iterator.next() {
        guard let value = iterator.next() else {
            throw ArgumentError.message("Missing value for \(arg)")
        }
        switch arg {
        case "--repo-root":
            repoRoot = URL(fileURLWithPath: value, isDirectory: true)
        case "--bundled-db":
            bundledDB = URL(fileURLWithPath: value)
        case "--baseline-db":
            baselineDB = URL(fileURLWithPath: value)
        case "--corridor-db":
            corridorDB = URL(fileURLWithPath: value)
        case "--annotated-log-dir":
            annotatedLogDir = URL(fileURLWithPath: value, isDirectory: true)
        case "--output-json":
            outputJSON = URL(fileURLWithPath: value)
        default:
            throw ArgumentError.message("Unknown argument: \(arg)")
        }
    }

    return Args(
        repoRoot: repoRoot.standardizedFileURL,
        bundledDB: bundledDB.standardizedFileURL,
        baselineDB: baselineDB.standardizedFileURL,
        corridorDB: corridorDB.standardizedFileURL,
        annotatedLogDir: (
            annotatedLogDir
            ?? repoRoot
                .appendingPathComponent("inspector", isDirectory: true)
                .appendingPathComponent("logs", isDirectory: true)
                .appendingPathComponent("replay_debug", isDirectory: true)
        ).standardizedFileURL,
        outputJSON: outputJSON?.standardizedFileURL
    )
}

func percentile(_ values: [Double], _ p: Double) -> Double {
    guard !values.isEmpty else {
        return 0.0
    }
    let sorted = values.sorted()
    let idx = Int((Double(sorted.count - 1) * p).rounded(.toNearestOrEven))
    return sorted[min(max(idx, 0), sorted.count - 1)]
}

func parseGPXTrack(url: URL) throws -> [TrackPoint] {
    let content = try String(contentsOf: url, encoding: .utf8)
    let pattern = #"<trkpt[^>]*lat="([^"]+)"[^>]*lon="([^"]+)""#
    let regex = try NSRegularExpression(pattern: pattern)
    let fullRange = NSRange(content.startIndex..., in: content)
    return regex.matches(in: content, range: fullRange).compactMap { match in
        guard let latRange = Range(match.range(at: 1), in: content),
              let lonRange = Range(match.range(at: 2), in: content),
              let lat = Double(content[latRange]),
              let lon = Double(content[lonRange]) else {
            return nil
        }
        return TrackPoint(lat: lat, lon: lon)
    }
}

func inspectorLogURLs(repoRoot: URL) throws -> [URL] {
    let logsDirectory = repoRoot
        .appendingPathComponent("inspector", isDirectory: true)
        .appendingPathComponent("logs", isDirectory: true)
    let urls = try FileManager.default.contentsOfDirectory(at: logsDirectory, includingPropertiesForKeys: nil)
        .filter { $0.lastPathComponent.contains("drive_match_log") && $0.pathExtension == "ndjson" }
        .sorted { $0.lastPathComponent < $1.lastPathComponent }
    if urls.isEmpty {
        throw ArgumentError.message("No drive match logs found in \(logsDirectory.path)")
    }
    let filtered = try urls.filter(logContainsFixID(_:))
    if filtered.isEmpty {
        throw ArgumentError.message("No drive match logs with fixID found in \(logsDirectory.path)")
    }
    return filtered
}

func geomLogURLs(repoRoot: URL) throws -> [URL] {
    let logsRoot = repoRoot
        .appendingPathComponent("inspector", isDirectory: true)
        .appendingPathComponent("logs", isDirectory: true)
    let candidateDirectories = [
        logsRoot.appendingPathComponent("geom", isDirectory: true),
        logsRoot.appendingPathComponent("replay_debug", isDirectory: true)
            .appendingPathComponent("geom", isDirectory: true),
    ]
    for logsDirectory in candidateDirectories where FileManager.default.fileExists(atPath: logsDirectory.path) {
        let urls = try FileManager.default.contentsOfDirectory(at: logsDirectory, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.contains("drive_match_log") && $0.pathExtension == "ndjson" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        if !urls.isEmpty {
            let filtered = try urls.filter(logContainsFixID(_:))
            if !filtered.isEmpty {
                return filtered
            }
        }
    }
    throw ArgumentError.message(
        "No geom drive match logs found in \(candidateDirectories.map(\.path).joined(separator: ", "))"
    )
}

func logContainsFixID(_ url: URL) throws -> Bool {
    let content = try String(contentsOf: url, encoding: .utf8)
    for line in content.split(whereSeparator: \.isNewline) {
        let payload = try JSONSerialization.jsonObject(with: Data(line.utf8))
        if let dictionary = payload as? [String: Any] {
            return dictionary["fixID"] != nil
        }
    }
    return false
}

func inspectorLogsRoot(repoRoot: URL) -> URL {
    repoRoot
        .appendingPathComponent("inspector", isDirectory: true)
        .appendingPathComponent("logs", isDirectory: true)
}

func loadDriveMatchLogEntries(url: URL) throws -> [DriveMatchLogEntry] {
    let decoder = JSONDecoder()
    let content = try String(contentsOf: url, encoding: .utf8)
    return try content
        .split(whereSeparator: \.isNewline)
        .map { line in
            try decoder.decode(DriveMatchLogEntry.self, from: Data(line.utf8))
        }
}

func hindsightPseudoLabelWayID(
    in entries: [DriveMatchLogEntry],
    at index: Int,
    futureWindow: Int = 5,
    minFutureRunLength: Int = 5,
    minAgreementRatio: Double = 0.8
) -> String? {
    guard index >= 0, index < entries.count else {
        return nil
    }
    guard let rowResult = entries[index].result else {
        return nil
    }
    let candidateWayIDs = rowResult.candidateTraces.compactMap(\.wayID)
    guard !candidateWayIDs.isEmpty else {
        return nil
    }

    let upperBound = index + 1 + futureWindow
    guard upperBound <= entries.count else {
        return nil
    }
    let futureWayIDs = entries[(index + 1) ..< upperBound].compactMap { $0.result?.wayID }
    guard futureWayIDs.count == futureWindow else {
        return nil
    }

    let agreementThreshold = Int(ceil(Double(futureWindow) * minAgreementRatio))
    let majority = Dictionary(futureWayIDs.map { ($0, 1) }, uniquingKeysWith: +)
        .max { lhs, rhs in
            if lhs.value != rhs.value {
                return lhs.value < rhs.value
            }
            return lhs.key > rhs.key
        }
    guard let majorityWayID = majority?.key,
          let agreementCount = majority?.value,
          agreementCount >= agreementThreshold,
          candidateWayIDs.contains(majorityWayID) else {
        return nil
    }

    var futureRunLength = 0
    for futureWayID in futureWayIDs {
        guard futureWayID == majorityWayID else {
            break
        }
        futureRunLength += 1
    }
    return futureRunLength >= minFutureRunLength ? majorityWayID : nil
}

func candidateRank(for wayID: String?, in result: SpeedLimitResult?) -> Int? {
    guard let wayID, let result else {
        return nil
    }
    return result.candidateTraces.first(where: { $0.wayID == wayID })?.rank
}

func replayOutcome(
    loggedWayID: String?,
    replayWayID: String?,
    pseudoLabelWayID: String?
) -> (name: String, isError: Bool) {
    guard let pseudoLabelWayID else {
        return (loggedWayID == replayWayID ? "stable" : "diverged", false)
    }
    let loggedCorrect = loggedWayID == pseudoLabelWayID
    let replayCorrect = replayWayID == pseudoLabelWayID
    switch (loggedCorrect, replayCorrect) {
    case (true, true):
        return ("stable_correct", false)
    case (false, true):
        return ("recovered", false)
    case (true, false):
        return ("regressed", true)
    case (false, false):
        return ("still_wrong", true)
    }
}

func makeReplayDebug(
    entry: DriveMatchLogEntry,
    replayKind: String,
    sourceLogName: String,
    replayResult: SpeedLimitResult,
    pseudoLabelWayID: String?
) -> DriveMatchReplayDebug {
    let loggedWayID = entry.result?.wayID
    let replayWayID = replayResult.wayID
    let outcome = replayOutcome(
        loggedWayID: loggedWayID,
        replayWayID: replayWayID,
        pseudoLabelWayID: pseudoLabelWayID
    )
    let replayUsedThreeWayGate = replayResult.selectionTrace.contains(where: { $0.step == "three_way_gate" })
    var issueKinds: [String] = []
    if loggedWayID != replayWayID {
        issueKinds.append("logged_replay_delta")
    }
    if let pseudoLabelWayID {
        if loggedWayID != pseudoLabelWayID {
            issueKinds.append("logged_hindsight_mismatch")
        }
        if replayWayID != pseudoLabelWayID {
            issueKinds.append("replay_hindsight_mismatch")
        }
        if candidateRank(for: pseudoLabelWayID, in: replayResult) == nil {
            issueKinds.append("replay_missing_hindsight_candidate")
        }
    }

    let hindsight = pseudoLabelWayID.map { labelWayID in
        DriveMatchReplayHindsightDebug(
            wayID: labelWayID,
            futureWindow: 5,
            minFutureRunLength: 5,
            minAgreementRatio: 0.8,
            loggedMatches: loggedWayID == labelWayID,
            replayMatches: replayWayID == labelWayID,
            loggedCandidateRank: candidateRank(for: labelWayID, in: entry.result),
            replayCandidateRank: candidateRank(for: labelWayID, in: replayResult)
        )
    }

    return DriveMatchReplayDebug(
        annotationVersion: 1,
        replayKind: replayKind,
        sourceLogName: sourceLogName,
        outcome: outcome.name,
        isError: outcome.isError,
        issueKinds: issueKinds,
        loggedMatchesReplay: loggedWayID == replayWayID,
        loggedSelectedRank: candidateRank(for: loggedWayID, in: entry.result),
        replaySelectedRank: candidateRank(for: replayWayID, in: replayResult),
        replayUsedThreeWayGate: replayUsedThreeWayGate,
        hindsight: hindsight,
        replayResult: replayResult
    )
}

func annotatedEntry(
    from entry: DriveMatchLogEntry,
    replayKind: String,
    sourceLogName: String,
    replayResult: SpeedLimitResult,
    pseudoLabelWayID: String?
) -> DriveMatchLogEntry {
    DriveMatchLogEntry(
        fixID: entry.fixID,
        timestampUTC: entry.timestampUTC,
        lat: entry.lat,
        lon: entry.lon,
        speedKmh: entry.speedKmh,
        horizontalAccM: entry.horizontalAccM,
        verticalAccM: entry.verticalAccM,
        courseDeg: entry.courseDeg,
        gpsSignalBars: entry.gpsSignalBars,
        status: entry.status,
        speedLimitOverrideKmh: entry.speedLimitOverrideKmh,
        tunnelModeState: entry.tunnelModeState,
        result: entry.result,
        error: entry.error,
        replayDebug: makeReplayDebug(
            entry: entry,
            replayKind: replayKind,
            sourceLogName: sourceLogName,
            replayResult: replayResult,
            pseudoLabelWayID: pseudoLabelWayID
        )
    )
}

func annotatedLogOutputURL(
    sourceLogURL: URL,
    logsRoot: URL,
    annotatedLogRoot: URL
) -> URL {
    let sourcePath = sourceLogURL.standardizedFileURL.path
    let rootPrefix = logsRoot.standardizedFileURL.path + "/"
    let relativePath: String
    if sourcePath.hasPrefix(rootPrefix) {
        relativePath = String(sourcePath.dropFirst(rootPrefix.count))
    } else {
        relativePath = sourceLogURL.lastPathComponent
    }
    return annotatedLogRoot.appendingPathComponent(relativePath, isDirectory: false)
}

func writeAnnotatedDriveLog(entries: [DriveMatchLogEntry], to url: URL) throws {
    try FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true,
        attributes: nil
    )
    let encoder = JSONEncoder()
    let payload = try entries.map { try String(decoding: encoder.encode($0), as: UTF8.self) }
        .joined(separator: "\n")
    try (payload + "\n").write(to: url, atomically: true, encoding: .utf8)
}

func countABAOscillations(_ ids: [String?]) -> Int {
    guard ids.count >= 3 else {
        return 0
    }
    var count = 0
    for index in 2 ..< ids.count {
        guard let lhs = ids[index - 2],
              let middle = ids[index - 1],
              let rhs = ids[index] else {
            continue
        }
        if lhs == rhs, lhs != middle {
            count += 1
        }
    }
    return count
}

func countSameRefABAOscillations(wayIDs: [String?], refs: [String?]) -> Int {
    guard wayIDs.count == refs.count, wayIDs.count >= 3 else {
        return 0
    }
    var count = 0
    for index in 2 ..< wayIDs.count {
        guard let lhsWayID = wayIDs[index - 2],
              let middleWayID = wayIDs[index - 1],
              let rhsWayID = wayIDs[index],
              let lhsRef = refs[index - 2]?.trimmingCharacters(in: .whitespacesAndNewlines),
              let middleRef = refs[index - 1]?.trimmingCharacters(in: .whitespacesAndNewlines),
              let rhsRef = refs[index]?.trimmingCharacters(in: .whitespacesAndNewlines),
              !lhsRef.isEmpty,
              lhsRef == middleRef,
              lhsRef == rhsRef else {
            continue
        }
        if lhsWayID == rhsWayID, lhsWayID != middleWayID {
            count += 1
        }
    }
    return count
}

func isPortalEligibleTunnelTrace(_ trace: MatchCandidateTrace) -> Bool {
    let isTunnel = (trace.tunnel ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "yes"
    guard isTunnel else {
        return false
    }
    if let portalEligible = trace.portalEligible {
        return portalEligible
    }
    return (trace.corridorSelectable ?? false) && trace.tunnelSelectable
}

func hasPortalEligibleTunnelCandidate(_ result: SpeedLimitResult?) -> Bool {
    guard let result else {
        return false
    }
    return result.candidateTraces.contains(where: isPortalEligibleTunnelTrace)
}

func fileSize(_ url: URL) throws -> UInt64 {
    let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
    return (attrs[.size] as? NSNumber)?.uint64Value ?? 0
}

func collectFieldReplay(
    service: V3SpeedLimitService,
    logURLs: [URL],
    logsRoot: URL,
    annotatedLogRoot: URL
) throws -> FieldReplaySummary {
    let focusWayID = "313127285"
    var replayedFixCount = 0
    var portalEligibleTunnelFixCount = 0
    var selectedTunnelFixCount = 0
    var motorwayFixCount = 0
    var motorwayLinkFixCount = 0
    var focusReplayCandidateFixCount = 0
    var focusReplaySelectedFixCount = 0
    var focusLoggedCandidateFixCount = 0
    var focusLoggedSelectedFixCount = 0
    var perLog: [FieldReplayLogSummary] = []

    for logURL in logURLs {
        let entries = try loadDriveMatchLogEntries(url: logURL)
        var state = BundledMatchContextState()
        var annotatedEntries: [DriveMatchLogEntry] = []
        annotatedEntries.reserveCapacity(entries.count)
        var logReplayedFixCount = 0
        var logPortalEligibleTunnelFixCount = 0
        var logSelectedTunnelFixCount = 0
        var logMotorwayFixCount = 0
        var logMotorwayLinkFixCount = 0
        var logFocusReplayCandidateFixCount = 0
        var logFocusReplaySelectedFixCount = 0
        var logFocusLoggedCandidateFixCount = 0
        var logFocusLoggedSelectedFixCount = 0

        for (index, entry) in entries.enumerated() {
            if entry.result?.candidateTraces.contains(where: { $0.wayID == focusWayID }) == true {
                focusLoggedCandidateFixCount += 1
                logFocusLoggedCandidateFixCount += 1
            }
            if entry.result?.wayID == focusWayID {
                focusLoggedSelectedFixCount += 1
                logFocusLoggedSelectedFixCount += 1
            }
            let result = try service.lookupSpeedLimit(
                lat: entry.lat,
                lon: entry.lon,
                radiusM: 50.0,
                maxCandidates: 64,
                matchContext: state.context,
                headingDeg: entry.courseDeg,
                headingAccuracyDeg: 10.0,
                speedKmh: entry.speedKmh,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
            let pseudoLabelWayID = hindsightPseudoLabelWayID(in: entries, at: index)
            annotatedEntries.append(
                annotatedEntry(
                    from: entry,
                    replayKind: "field_replay",
                    sourceLogName: logURL.lastPathComponent,
                    replayResult: result,
                    pseudoLabelWayID: pseudoLabelWayID
                )
            )

            replayedFixCount += 1
            logReplayedFixCount += 1
            if result.candidateTraces.contains(where: { $0.wayID == focusWayID }) {
                focusReplayCandidateFixCount += 1
                logFocusReplayCandidateFixCount += 1
            }
            if result.wayID == focusWayID {
                focusReplaySelectedFixCount += 1
                logFocusReplaySelectedFixCount += 1
            }
            if hasPortalEligibleTunnelCandidate(result) {
                portalEligibleTunnelFixCount += 1
                logPortalEligibleTunnelFixCount += 1
            }
            if result.isTunnelSegment {
                selectedTunnelFixCount += 1
                logSelectedTunnelFixCount += 1
            }
            switch result.highway {
            case "motorway":
                motorwayFixCount += 1
                logMotorwayFixCount += 1
            case "motorway_link":
                motorwayLinkFixCount += 1
                logMotorwayLinkFixCount += 1
            default:
                break
            }

            state.record(
                result,
                lat: entry.lat,
                lon: entry.lon,
                headingDeg: entry.courseDeg,
                speedKmh: entry.speedKmh,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
        }

        let annotatedLogURL = annotatedLogOutputURL(
            sourceLogURL: logURL,
            logsRoot: logsRoot,
            annotatedLogRoot: annotatedLogRoot
        )
        try writeAnnotatedDriveLog(entries: annotatedEntries, to: annotatedLogURL)

        perLog.append(
            FieldReplayLogSummary(
                logName: logURL.lastPathComponent,
                annotatedLogPath: annotatedLogURL.path,
                replayed: logReplayedFixCount,
                portalTunnel: logPortalEligibleTunnelFixCount,
                selectedTunnel: logSelectedTunnelFixCount,
                motorway: logMotorwayFixCount,
                motorwayLink: logMotorwayLinkFixCount,
                focusReplayCandidate: logFocusReplayCandidateFixCount,
                focusReplaySelected: logFocusReplaySelectedFixCount,
                focusLoggedCandidate: logFocusLoggedCandidateFixCount,
                focusLoggedSelected: logFocusLoggedSelectedFixCount
            )
        )
    }

    return FieldReplaySummary(
        logCount: logURLs.count,
        replayedFixCount: replayedFixCount,
        portalEligibleTunnelFixCount: portalEligibleTunnelFixCount,
        selectedTunnelFixCount: selectedTunnelFixCount,
        motorwayFixCount: motorwayFixCount,
        motorwayLinkFixCount: motorwayLinkFixCount,
        focusWayID: focusWayID,
        focusReplayCandidateFixCount: focusReplayCandidateFixCount,
        focusReplaySelectedFixCount: focusReplaySelectedFixCount,
        focusLoggedCandidateFixCount: focusLoggedCandidateFixCount,
        focusLoggedSelectedFixCount: focusLoggedSelectedFixCount,
        perLog: perLog
    )
}

func collectGeomReplay(
    service: V3SpeedLimitService,
    logURLs: [URL],
    logsRoot: URL,
    annotatedLogRoot: URL
) throws -> GeomReplaySummary {
    var aggregate = DriveLogReplayMetrics()
    var aggregateLoggedComparable = 0
    var aggregateLoggedAgreement = 0
    var aggregateReplayTunnelFixCount = 0
    var aggregateLoggedTunnelFixCount = 0
    var aggregateReplayPortalEligibleTunnelFixCount = 0
    var aggregateLoggedPortalEligibleTunnelFixCount = 0
    var aggregateReplayWayOscillationCount = 0
    var aggregateLoggedWayOscillationCount = 0
    var aggregateReplaySameRefOscillationCount = 0
    var aggregateLoggedSameRefOscillationCount = 0
    var perLog: [GeomReplayLogSummary] = []

    for logURL in logURLs {
        let entries = try loadDriveMatchLogEntries(url: logURL)
            .sorted {
                if $0.fixID != $1.fixID {
                    return $0.fixID < $1.fixID
                }
                return $0.timestampUTC < $1.timestampUTC
            }
        var state = BundledMatchContextState()
        var annotatedEntries: [DriveMatchLogEntry] = []
        annotatedEntries.reserveCapacity(entries.count)
        var logMetrics = DriveLogReplayMetrics()
        var loggedWayIDs: [String?] = []
        var replayWayIDs: [String?] = []
        var loggedRefs: [String?] = []
        var replayRefs: [String?] = []
        var logLoggedComparable = 0
        var logLoggedAgreement = 0
        var logReplayTunnelFixCount = 0
        var logLoggedTunnelFixCount = 0
        var logReplayPortalEligibleTunnelFixCount = 0
        var logLoggedPortalEligibleTunnelFixCount = 0

        for (index, entry) in entries.enumerated() {
            let result = try service.lookupSpeedLimit(
                lat: entry.lat,
                lon: entry.lon,
                radiusM: 50.0,
                maxCandidates: 64,
                matchContext: state.context,
                headingDeg: entry.courseDeg,
                headingAccuracyDeg: 10.0,
                speedKmh: entry.speedKmh,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
            let pseudoLabelWayID = hindsightPseudoLabelWayID(in: entries, at: index)
            annotatedEntries.append(
                annotatedEntry(
                    from: entry,
                    replayKind: "geom_replay",
                    sourceLogName: logURL.lastPathComponent,
                    replayResult: result,
                    pseudoLabelWayID: pseudoLabelWayID
                )
            )

            logMetrics.replayedFixCount += 1
            if result.selectionTrace.contains(where: { $0.step == "three_way_gate" }) {
                logMetrics.usedThreeWayGateCount += 1
            }
            if let pseudoLabelWayID {
                let predictedMatches = result.wayID == pseudoLabelWayID
                let isChangedExample = entry.result?.wayID != pseudoLabelWayID
                logMetrics.pseudoLabelExampleCount += 1
                logMetrics.correctPseudoLabelCount += predictedMatches ? 1 : 0
                if isChangedExample {
                    logMetrics.changedExampleCount += 1
                    logMetrics.changedCorrectCount += predictedMatches ? 1 : 0
                } else {
                    logMetrics.unchangedExampleCount += 1
                    logMetrics.unchangedCorrectCount += predictedMatches ? 1 : 0
                }
            }

            if let loggedWayID = entry.result?.wayID {
                logLoggedComparable += 1
                if loggedWayID == result.wayID {
                    logLoggedAgreement += 1
                }
            }
            loggedWayIDs.append(entry.result?.wayID)
            replayWayIDs.append(result.wayID)
            loggedRefs.append(entry.result?.streetRef)
            replayRefs.append(result.streetRef)

            if entry.result?.isTunnelSegment == true {
                logLoggedTunnelFixCount += 1
            }
            if hasPortalEligibleTunnelCandidate(entry.result) {
                logLoggedPortalEligibleTunnelFixCount += 1
            }
            if hasPortalEligibleTunnelCandidate(result) {
                logReplayPortalEligibleTunnelFixCount += 1
            }
            if result.isTunnelSegment {
                logReplayTunnelFixCount += 1
            }

            state.record(
                result,
                lat: entry.lat,
                lon: entry.lon,
                headingDeg: entry.courseDeg,
                speedKmh: entry.speedKmh,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
        }

        let annotatedLogURL = annotatedLogOutputURL(
            sourceLogURL: logURL,
            logsRoot: logsRoot,
            annotatedLogRoot: annotatedLogRoot
        )
        try writeAnnotatedDriveLog(entries: annotatedEntries, to: annotatedLogURL)

        let replayWayOscillationCount = countABAOscillations(replayWayIDs)
        let loggedWayOscillationCount = countABAOscillations(loggedWayIDs)
        let replaySameRefOscillationCount = countSameRefABAOscillations(wayIDs: replayWayIDs, refs: replayRefs)
        let loggedSameRefOscillationCount = countSameRefABAOscillations(wayIDs: loggedWayIDs, refs: loggedRefs)
        let loggedAgreementRatio = logLoggedComparable > 0
            ? Double(logLoggedAgreement) / Double(logLoggedComparable)
            : 0.0

        aggregate.formUnion(logMetrics)
        aggregateLoggedComparable += logLoggedComparable
        aggregateLoggedAgreement += logLoggedAgreement
        aggregateReplayTunnelFixCount += logReplayTunnelFixCount
        aggregateLoggedTunnelFixCount += logLoggedTunnelFixCount
        aggregateReplayPortalEligibleTunnelFixCount += logReplayPortalEligibleTunnelFixCount
        aggregateLoggedPortalEligibleTunnelFixCount += logLoggedPortalEligibleTunnelFixCount
        aggregateReplayWayOscillationCount += replayWayOscillationCount
        aggregateLoggedWayOscillationCount += loggedWayOscillationCount
        aggregateReplaySameRefOscillationCount += replaySameRefOscillationCount
        aggregateLoggedSameRefOscillationCount += loggedSameRefOscillationCount

        perLog.append(
            GeomReplayLogSummary(
                logName: logURL.lastPathComponent,
                annotatedLogPath: annotatedLogURL.path,
                replayedFixCount: logMetrics.replayedFixCount,
                pseudoLabelExampleCount: logMetrics.pseudoLabelExampleCount,
                accuracy: logMetrics.accuracy,
                changedRecall: logMetrics.changedRecall,
                unchangedAccuracy: logMetrics.unchangedAccuracy,
                loggedComparable: logLoggedComparable,
                loggedAgreement: loggedAgreementRatio,
                replayPortalEligibleTunnelFixCount: logReplayPortalEligibleTunnelFixCount,
                loggedPortalEligibleTunnelFixCount: logLoggedPortalEligibleTunnelFixCount,
                replayTunnelFixCount: logReplayTunnelFixCount,
                loggedTunnelFixCount: logLoggedTunnelFixCount,
                replayWayABAOscillations: replayWayOscillationCount,
                loggedWayABAOscillations: loggedWayOscillationCount,
                replaySameRefABAOscillations: replaySameRefOscillationCount,
                loggedSameRefABAOscillations: loggedSameRefOscillationCount
            )
        )
    }

    let loggedAgreementRatio = aggregateLoggedComparable > 0
        ? Double(aggregateLoggedAgreement) / Double(aggregateLoggedComparable)
        : 0.0

    return GeomReplaySummary(
        logCount: logURLs.count,
        replayedFixCount: aggregate.replayedFixCount,
        pseudoLabelExampleCount: aggregate.pseudoLabelExampleCount,
        accuracy: aggregate.accuracy,
        changedRecall: aggregate.changedRecall,
        unchangedAccuracy: aggregate.unchangedAccuracy,
        usedThreeWayGateCount: aggregate.usedThreeWayGateCount,
        loggedComparable: aggregateLoggedComparable,
        loggedAgreement: loggedAgreementRatio,
        replayPortalEligibleTunnelFixCount: aggregateReplayPortalEligibleTunnelFixCount,
        loggedPortalEligibleTunnelFixCount: aggregateLoggedPortalEligibleTunnelFixCount,
        replayTunnelFixCount: aggregateReplayTunnelFixCount,
        loggedTunnelFixCount: aggregateLoggedTunnelFixCount,
        replayWayABAOscillations: aggregateReplayWayOscillationCount,
        loggedWayABAOscillations: aggregateLoggedWayOscillationCount,
        replaySameRefABAOscillations: aggregateReplaySameRefOscillationCount,
        loggedSameRefABAOscillations: aggregateLoggedSameRefOscillationCount,
        perLog: perLog
    )
}

func profileSummaries(
    baselineDB: URL,
    corridorDB: URL,
    logURLs: [URL],
    geomLogURLs: [URL],
    track: [TrackPoint]
) throws -> (profiles: [ProfileSummary], deltas: [ProfileDeltaSummary]) {
    let focusWayID = "313127285"

    struct ReplayExampleOutcome {
        let isChangedExample: Bool
        let predictedMatches: Bool
    }

    struct AggregateReplaySummary {
        let metrics: DriveLogReplayMetrics
        let focusReplayCandidate: Int
        let focusReplaySelected: Int
        let focusReplayCandidateOutsideLog3: Int
        let focusReplaySelectedOutsideLog3: Int
        let selectedTunnel: Int
        let outcomes: [String: ReplayExampleOutcome]
    }

    func runAggregateReplay(service: V3SpeedLimitService) throws -> AggregateReplaySummary {
        var aggregate = DriveLogReplayMetrics()
        var focusReplayCandidate = 0
        var focusReplaySelected = 0
        var focusReplayCandidateOutsideLog3 = 0
        var focusReplaySelectedOutsideLog3 = 0
        var selectedTunnel = 0
        var outcomes: [String: ReplayExampleOutcome] = [:]

        for logURL in logURLs {
            let entries = try loadDriveMatchLogEntries(url: logURL)
            var state = BundledMatchContextState()
            let isOtherLog = !logURL.lastPathComponent.contains("drive_match_log-3")
            for (index, entry) in entries.enumerated() {
                let result = try service.lookupSpeedLimit(
                    lat: entry.lat,
                    lon: entry.lon,
                    radiusM: 50.0,
                    maxCandidates: 64,
                    matchContext: state.context,
                    headingDeg: entry.courseDeg,
                    headingAccuracyDeg: 10.0,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )

                aggregate.replayedFixCount += 1
                if result.selectionTrace.contains(where: { $0.step == "three_way_gate" }) {
                    aggregate.usedThreeWayGateCount += 1
                }
                if result.selectionTrace.contains(where: { $0.step == "same_ref_bounce_gate" }) {
                    aggregate.usedSameRefBounceGateCount += 1
                }
                if result.selectionTrace.contains(where: { $0.step == "anti_aba_hysteresis" }) {
                    aggregate.usedAntiABAHysteresisCount += 1
                }
                if let pseudoLabelWayID = hindsightPseudoLabelWayID(in: entries, at: index) {
                    let selectedWayID = entry.result?.wayID
                    let predictedMatches = result.wayID == pseudoLabelWayID
                    let isChangedExample = selectedWayID != pseudoLabelWayID
                    aggregate.pseudoLabelExampleCount += 1
                    aggregate.correctPseudoLabelCount += predictedMatches ? 1 : 0
                    if isChangedExample {
                        aggregate.changedExampleCount += 1
                        aggregate.changedCorrectCount += predictedMatches ? 1 : 0
                    } else {
                        aggregate.unchangedExampleCount += 1
                        aggregate.unchangedCorrectCount += predictedMatches ? 1 : 0
                    }
                    outcomes["\(logURL.lastPathComponent)#\(entry.fixID)"] = ReplayExampleOutcome(
                        isChangedExample: isChangedExample,
                        predictedMatches: predictedMatches
                    )
                }

                if result.candidateTraces.contains(where: { $0.wayID == focusWayID }) {
                    focusReplayCandidate += 1
                    if isOtherLog {
                        focusReplayCandidateOutsideLog3 += 1
                    }
                }
                if result.wayID == focusWayID {
                    focusReplaySelected += 1
                    if isOtherLog {
                        focusReplaySelectedOutsideLog3 += 1
                    }
                }
                if result.isTunnelSegment {
                    selectedTunnel += 1
                }

                state.record(
                    result,
                    lat: entry.lat,
                    lon: entry.lon,
                    headingDeg: entry.courseDeg,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )
            }
        }

        return AggregateReplaySummary(
            metrics: aggregate,
            focusReplayCandidate: focusReplayCandidate,
            focusReplaySelected: focusReplaySelected,
            focusReplayCandidateOutsideLog3: focusReplayCandidateOutsideLog3,
            focusReplaySelectedOutsideLog3: focusReplaySelectedOutsideLog3,
            selectedTunnel: selectedTunnel,
            outcomes: outcomes
        )
    }

    func runGeomReplay(service: V3SpeedLimitService) throws -> (logAgreement: Double, replayTunnel: Int, replayWayABA: Int, replaySameRefABA: Int) {
        var comparable = 0
        var agreement = 0
        var replayTunnel = 0
        var replayWayIDs: [String?] = []
        var replayRefs: [String?] = []

        for logURL in geomLogURLs {
            let entries = try loadDriveMatchLogEntries(url: logURL)
                .sorted {
                    if $0.fixID != $1.fixID {
                        return $0.fixID < $1.fixID
                    }
                    return $0.timestampUTC < $1.timestampUTC
                }
            var state = BundledMatchContextState()
            var logWayIDs: [String?] = []
            var logRefs: [String?] = []
            var replayLogWayIDs: [String?] = []
            var replayLogRefs: [String?] = []
            for entry in entries {
                let result = try service.lookupSpeedLimit(
                    lat: entry.lat,
                    lon: entry.lon,
                    radiusM: 50.0,
                    maxCandidates: 64,
                    matchContext: state.context,
                    headingDeg: entry.courseDeg,
                    headingAccuracyDeg: 10.0,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )
                if let loggedWayID = entry.result?.wayID {
                    comparable += 1
                    agreement += loggedWayID == result.wayID ? 1 : 0
                }
                if result.isTunnelSegment {
                    replayTunnel += 1
                }
                logWayIDs.append(entry.result?.wayID)
                logRefs.append(entry.result?.streetRef)
                replayLogWayIDs.append(result.wayID)
                replayLogRefs.append(result.streetRef)
                state.record(
                    result,
                    lat: entry.lat,
                    lon: entry.lon,
                    headingDeg: entry.courseDeg,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )
            }
            replayWayIDs.append(contentsOf: replayLogWayIDs)
            replayRefs.append(contentsOf: replayLogRefs)
            _ = countABAOscillations(logWayIDs)
            _ = countSameRefABAOscillations(wayIDs: logWayIDs, refs: logRefs)
        }

        return (
            logAgreement: comparable > 0 ? Double(agreement) / Double(comparable) : 0.0,
            replayTunnel: replayTunnel,
            replayWayABA: countABAOscillations(replayWayIDs),
            replaySameRefABA: countSameRefABAOscillations(wayIDs: replayWayIDs, refs: replayRefs)
        )
    }

    func runLatency(service: V3SpeedLimitService) throws -> (e2eMedian: Double, serviceP95: Double) {
        var e2eMs: [Double] = []
        var serviceMs: [Double] = []
        for point in track {
            _ = try service.lookupSpeedLimit(lat: point.lat, lon: point.lon, radiusM: 120.0, maxCandidates: 64)
        }
        for _ in 0..<10 {
            for point in track {
                let started = DispatchTime.now().uptimeNanoseconds
                let result = try service.lookupSpeedLimit(lat: point.lat, lon: point.lon, radiusM: 120.0, maxCandidates: 64)
                _ = "\(result.speedLimitKmh.map(String.init) ?? "nil")|\(result.wayID ?? "nil")"
                e2eMs.append(Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000.0)
                serviceMs.append(result.queryTimeMs)
            }
        }
        return (
            e2eMedian: percentile(e2eMs, 0.50),
            serviceP95: percentile(serviceMs, 0.95)
        )
    }

    struct IntermediateProfile {
        let label: String
        let bytes: UInt64
        let replay: DriveLogReplayMetrics
        let geomLogAgreement: Double
        let geomReplayTunnel: Int
        let geomWayABA: Int
        let geomSameRefABA: Int
        let latencyE2EMedian: Double
        let latencyServiceP95: Double
        let focusReplayCandidate: Int
        let focusReplaySelected: Int
        let focusReplayCandidateOutsideLog3: Int
        let focusReplaySelectedOutsideLog3: Int
        let selectedTunnel: Int
        let replayOutcomes: [String: ReplayExampleOutcome]

        var accuracyComposite: Double {
            (0.50 * replay.accuracy) + (0.25 * replay.changedRecall) + (0.25 * replay.unchangedAccuracy)
        }
    }

    func summarize(label: String, dbURL: URL, model: V3SpeedLimitService.MatchingModel) throws -> IntermediateProfile {
        let service = V3SpeedLimitService(dbPath: dbURL.path, matchingModel: model)
        let replay = try runAggregateReplay(service: service)
        let geom = try runGeomReplay(service: service)
        let latency = try runLatency(service: service)
        return IntermediateProfile(
            label: label,
            bytes: try fileSize(dbURL),
            replay: replay.metrics,
            geomLogAgreement: geom.logAgreement,
            geomReplayTunnel: geom.replayTunnel,
            geomWayABA: geom.replayWayABA,
            geomSameRefABA: geom.replaySameRefABA,
            latencyE2EMedian: latency.e2eMedian,
            latencyServiceP95: latency.serviceP95,
            focusReplayCandidate: replay.focusReplayCandidate,
            focusReplaySelected: replay.focusReplaySelected,
            focusReplayCandidateOutsideLog3: replay.focusReplayCandidateOutsideLog3,
            focusReplaySelectedOutsideLog3: replay.focusReplaySelectedOutsideLog3,
            selectedTunnel: replay.selectedTunnel,
            replayOutcomes: replay.outcomes
        )
    }

    func commonScore(for profile: IntermediateProfile, bestLatencyP95: Double, minBytes: UInt64) -> Double {
        let latencyScore = bestLatencyP95 > 0 ? bestLatencyP95 / profile.latencyServiceP95 : 0.0
        let sizeScore = profile.bytes > 0 ? Double(minBytes) / Double(profile.bytes) : 0.0
        return 100.0 * (
            (0.70 * profile.accuracyComposite) +
            (0.20 * latencyScore) +
            (0.10 * sizeScore)
        )
    }

    func deltaSummary(
        from base: IntermediateProfile,
        to candidate: IntermediateProfile,
        bestLatencyP95: Double,
        minBytes: UInt64
    ) -> ProfileDeltaSummary {
        var correctedExamples = 0
        var regressedExamples = 0
        var correctedChangedExamples = 0
        var regressedChangedExamples = 0
        var correctedUnchangedExamples = 0
        var regressedUnchangedExamples = 0

        for key in base.replayOutcomes.keys.sorted() {
            guard let baseOutcome = base.replayOutcomes[key],
                  let candidateOutcome = candidate.replayOutcomes[key] else {
                continue
            }
            if !baseOutcome.predictedMatches && candidateOutcome.predictedMatches {
                correctedExamples += 1
                if baseOutcome.isChangedExample {
                    correctedChangedExamples += 1
                } else {
                    correctedUnchangedExamples += 1
                }
            } else if baseOutcome.predictedMatches && !candidateOutcome.predictedMatches {
                regressedExamples += 1
                if baseOutcome.isChangedExample {
                    regressedChangedExamples += 1
                } else {
                    regressedUnchangedExamples += 1
                }
            }
        }

        return ProfileDeltaSummary(
            label: candidate.label,
            correctedExamples: correctedExamples,
            regressedExamples: regressedExamples,
            netCorrections: correctedExamples - regressedExamples,
            correctedChangedExamples: correctedChangedExamples,
            regressedChangedExamples: regressedChangedExamples,
            netChangedCorrections: correctedChangedExamples - regressedChangedExamples,
            correctedUnchangedExamples: correctedUnchangedExamples,
            regressedUnchangedExamples: regressedUnchangedExamples,
            netUnchangedCorrections: correctedUnchangedExamples - regressedUnchangedExamples,
            geomWayABADelta: candidate.geomWayABA - base.geomWayABA,
            geomSameRefABADelta: candidate.geomSameRefABA - base.geomSameRefABA,
            accuracyDelta: candidate.replay.accuracy - base.replay.accuracy,
            changedRecallDelta: candidate.replay.changedRecall - base.replay.changedRecall,
            unchangedAccuracyDelta: candidate.replay.unchangedAccuracy - base.replay.unchangedAccuracy,
            commonScoreDelta: commonScore(for: candidate, bestLatencyP95: bestLatencyP95, minBytes: minBytes) -
                commonScore(for: base, bestLatencyP95: bestLatencyP95, minBytes: minBytes)
        )
    }

    let intermediates = [
        try summarize(label: "baseline", dbURL: baselineDB, model: .connectedBaseline),
        try summarize(label: "simple_speed_ref", dbURL: baselineDB, model: .simpleSpeedRefHeuristic),
        try summarize(
            label: "simple_speed_ref_connected",
            dbURL: baselineDB,
            model: .simpleSpeedRefConnectedHeuristic
        ),
        try summarize(label: "corridor_raw_mini_hmm", dbURL: corridorDB, model: .corridorHMMRawMiniHMM),
        try summarize(label: "corridor_no_three_way", dbURL: corridorDB, model: .corridorHMMNoThreeWayGate),
        try summarize(label: "corridor_no_same_ref_bounce", dbURL: corridorDB, model: .corridorHMMNoSameRefBounceGate),
        try summarize(label: "corridor_anti_aba", dbURL: corridorDB, model: .corridorHMMAntiABAHysteresis),
        try summarize(label: "corridor", dbURL: corridorDB, model: .corridorHMM),
    ]
    let bestLatencyP95 = intermediates.map(\.latencyServiceP95).min() ?? 1.0
    let minBytes = intermediates.map(\.bytes).min() ?? 1
    guard let corridor = intermediates.first(where: { $0.label == "corridor" }) else {
        throw ArgumentError.message("Missing corridor profile in replay summary")
    }
    let corridorReplayKeys = Set(corridor.replayOutcomes.keys)

    let profiles = intermediates.map { profile in
        precondition(Set(profile.replayOutcomes.keys) == corridorReplayKeys)
        return ProfileSummary(
            label: profile.label,
            bytes: profile.bytes,
            replayedFixCount: profile.replay.replayedFixCount,
            pseudoLabelExampleCount: profile.replay.pseudoLabelExampleCount,
            changedExampleCount: profile.replay.changedExampleCount,
            accuracy: profile.replay.accuracy,
            changedRecall: profile.replay.changedRecall,
            unchangedAccuracy: profile.replay.unchangedAccuracy,
            usedThreeWayGateCount: profile.replay.usedThreeWayGateCount,
            usedSameRefBounceGateCount: profile.replay.usedSameRefBounceGateCount,
            usedAntiABAHysteresisCount: profile.replay.usedAntiABAHysteresisCount,
            geomLogAgreement: profile.geomLogAgreement,
            geomReplayTunnel: profile.geomReplayTunnel,
            geomWayABA: profile.geomWayABA,
            geomSameRefABA: profile.geomSameRefABA,
            latencyE2EMedian: profile.latencyE2EMedian,
            latencyServiceP95: profile.latencyServiceP95,
            focusReplayCandidate: profile.focusReplayCandidate,
            focusReplaySelected: profile.focusReplaySelected,
            focusReplayCandidateOutsideLog3: profile.focusReplayCandidateOutsideLog3,
            focusReplaySelectedOutsideLog3: profile.focusReplaySelectedOutsideLog3,
            selectedTunnel: profile.selectedTunnel,
            accuracyComposite: profile.accuracyComposite,
            commonScore: commonScore(for: profile, bestLatencyP95: bestLatencyP95, minBytes: minBytes)
        )
    }

    let deltas = [
        "simple_speed_ref",
        "simple_speed_ref_connected",
        "corridor_no_three_way",
        "corridor_no_same_ref_bounce",
        "corridor_anti_aba",
    ]
        .compactMap { label in
            intermediates.first(where: { $0.label == label }).map {
                deltaSummary(from: corridor, to: $0, bestLatencyP95: bestLatencyP95, minBytes: minBytes)
            }
        }

    return (profiles: profiles, deltas: deltas)
}

@main
enum Main {
    static func main() throws {
        let args = try parseArgs()
        let logsRoot = inspectorLogsRoot(repoRoot: args.repoRoot)
        let logs = try inspectorLogURLs(repoRoot: args.repoRoot)
        let geomLogs = try geomLogURLs(repoRoot: args.repoRoot)
        let replayTrack = try parseGPXTrack(
            url: args.repoRoot
                .appendingPathComponent("iphone", isDirectory: true)
                .appendingPathComponent("SpeedConsumerApp", isDirectory: true)
                .appendingPathComponent("TestFixtures", isDirectory: true)
                .appendingPathComponent("replay_track.gpx")
        )

        let bundledService = V3SpeedLimitService(dbPath: args.bundledDB.path)
        let fieldReplay = try collectFieldReplay(
            service: bundledService,
            logURLs: logs,
            logsRoot: logsRoot,
            annotatedLogRoot: args.annotatedLogDir
        )
        let geomReplay = try collectGeomReplay(
            service: bundledService,
            logURLs: geomLogs,
            logsRoot: logsRoot,
            annotatedLogRoot: args.annotatedLogDir
        )
        let profileBenchmark = try profileSummaries(
            baselineDB: args.baselineDB,
            corridorDB: args.corridorDB,
            logURLs: logs,
            geomLogURLs: geomLogs,
            track: replayTrack
        )
        let profiles = profileBenchmark.profiles
        let profileDeltas = profileBenchmark.deltas

        guard let corridor = profiles.first(where: { $0.label == "corridor" }) else {
            throw ArgumentError.message("Missing corridor profile in replay summary")
        }

        let output = MetricsOutput(
            generatedAtUTC: ISO8601DateFormatter().string(from: Date()),
            repoRoot: args.repoRoot.path,
            annotatedLogDirectory: args.annotatedLogDir.path,
            inspectorLogs: logs.map(\.lastPathComponent),
            geomLogs: geomLogs.map(\.lastPathComponent),
            fieldReplay: fieldReplay,
            geomReplay: geomReplay,
            profiles: profiles,
            profileDeltas: profileDeltas,
            runtimeReplayMacros: RuntimeReplayMacros(
                replayAllLogs: logs.count,
                replayAllLogFixes: corridor.replayedFixCount,
                replayPseudoExamples: corridor.pseudoLabelExampleCount,
                replayChangedExamples: corridor.changedExampleCount,
                replayAccuracyPct: corridor.accuracy * 100.0,
                replayChangedRecallPct: corridor.changedRecall * 100.0,
                replayUnchangedAccuracyPct: corridor.unchangedAccuracy * 100.0,
                replayThreeWayGateActivations: corridor.usedThreeWayGateCount
            )
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(output)
        if let outputJSON = args.outputJSON {
            try data.write(to: outputJSON)
        }
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
}

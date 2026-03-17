import Foundation

struct DriveLogReplayMetrics {
    var replayedFixCount = 0
    var pseudoLabelExampleCount = 0
    var correctPseudoLabelCount = 0
    var changedExampleCount = 0
    var changedCorrectCount = 0
    var unchangedExampleCount = 0
    var unchangedCorrectCount = 0
    var usedThreeWayGateCount = 0
    var usedMiniHMMCount = 0
    var selectedTunnelFixCount = 0
    var loggedAgreementCount = 0
    var loggedComparableCount = 0
    var recoveredExamples = 0
    var regressedExamples = 0

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

    var loggedAgreement: Double {
        guard loggedComparableCount > 0 else {
            return 0.0
        }
        return Double(loggedAgreementCount) / Double(loggedComparableCount)
    }

    var netCorrections: Int {
        recoveredExamples - regressedExamples
    }
}

struct BundledMatchContextState {
    var recentWayIDs: [String] = []
    var recentFixes: [WayMatchRecentFix] = []
    var sameRefUrbanReleaseStreak = 0
    var recentStreetRefs: [String] = []
    var activeStreetRef: String?
    var activeStreetName: String?
    var consecutiveNoRefMatchCount = 0
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
                activeStreetName != nil ||
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
            sameRefUrbanReleaseStreak: sameRefUrbanReleaseStreak,
            preferredStreetRef: recentStreetRefs.first,
            activeStreetRef: activeStreetRef,
            preferredStreetName: activeStreetName,
            recentStreetRefs: recentStreetRefs,
            consecutiveNoRefMatchCount: consecutiveNoRefMatchCount,
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
            recentFixes.insert(WayMatchRecentFix(lat: lat, lon: lon), at: 0)
            if recentFixes.count > 3 {
                recentFixes.removeLast(recentFixes.count - 3)
            }
        }
        sameRefUrbanReleaseStreak = updatedSameRefUrbanReleaseStreak(after: result)
        preferredHighway = result.highway
        preferredEndpointProximityM = result.matchedEndpointProximityM
        let normalizedStreetRefs = V3SpeedLimitService.normalizedRefTokens(result.streetRef)
        activeStreetRef = result.streetRef
        activeStreetName = result.streetBaseName ?? result.streetName
        if normalizedStreetRefs.isEmpty {
            consecutiveNoRefMatchCount = min(consecutiveNoRefMatchCount + 1, 8)
        } else {
            consecutiveNoRefMatchCount = 0
        }
        for ref in normalizedStreetRefs {
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

    private mutating func updatedSameRefUrbanReleaseStreak(after result: SpeedLimitResult) -> Int {
        if let streakCount = result.selectionTrace.last(where: { $0.step == "simple_same_ref_urban_release_streak" }).flatMap({ Int($0.detail) }) {
            return max(streakCount, 0)
        }
        return 0
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

struct Args {
    let repoRoot: URL
    let baselineDB: URL
    let corridorDB: URL
    let outputJSON: URL
    let outputCSV: URL
    let outputDiffCSV: URL
    let logURLs: [URL]
}

struct ModelConfig {
    let label: String
    let dbURL: URL
    let matchingModel: V3SpeedLimitService.MatchingModel

    init(
        label: String,
        dbURL: URL,
        matchingModel: V3SpeedLimitService.MatchingModel
    ) {
        self.label = label
        self.dbURL = dbURL
        self.matchingModel = matchingModel
    }
}

struct ModelPrediction: Codable {
    let label: String
    let wayID: String?
    let streetName: String?
    let streetRef: String?
    let speedLimitKmh: Int?
    let isTunnelSegment: Bool
    let usedMiniHMM: Bool
    let usedThreeWayGate: Bool
    let selectedRank: Int?
    let pseudoLabelCandidateRank: Int?
    let agreesWithLogged: Bool
    let matchesPseudoLabel: Bool?
    let queryTimeMs: Double
}

struct FixComparisonRow: Codable {
    let logName: String
    let logIndex: Int
    let fixID: Int
    let timestampUTC: String
    let lat: Double
    let lon: Double
    let speedKmh: Double
    let horizontalAccM: Double
    let courseDeg: Double
    let gpsSignalBars: Int
    let status: String
    let loggedWayID: String?
    let loggedStreetName: String?
    let loggedStreetRef: String?
    let loggedMatchesPseudoLabel: Bool?
    let loggedPseudoLabelCandidateRank: Int?
    let loggedSimpleReason: String?
    let pseudoLabelWayID: String?
    let pseudoLabelStreetName: String?
    let pseudoLabelStreetRef: String?
    let isChangedExample: Bool?
    let predictions: [ModelPrediction]
    let distinctPredictedWayCount: Int
    let allModelsAgree: Bool
    let anyModelDiffersFromLogged: Bool
    let anyModelMatchesPseudoLabel: Bool
    let bestMatchingModels: [String]
}

struct ModelLogSummary: Codable {
    let logName: String
    let replayedFixCount: Int
    let pseudoLabelExampleCount: Int
    let changedExampleCount: Int
    let accuracy: Double
    let changedRecall: Double
    let unchangedAccuracy: Double
    let loggedAgreement: Double
    let usedThreeWayGateCount: Int
    let usedMiniHMMCount: Int
    let selectedTunnelFixCount: Int
    let recoveredExamples: Int
    let regressedExamples: Int
    let netCorrections: Int
}

struct ModelSummary: Codable {
    let label: String
    let dbPath: String
    let replayedFixCount: Int
    let pseudoLabelExampleCount: Int
    let changedExampleCount: Int
    let accuracy: Double
    let changedRecall: Double
    let unchangedAccuracy: Double
    let loggedAgreement: Double
    let usedThreeWayGateCount: Int
    let usedMiniHMMCount: Int
    let selectedTunnelFixCount: Int
    let recoveredExamples: Int
    let regressedExamples: Int
    let netCorrections: Int
    let perLog: [ModelLogSummary]
}

struct OutputPayload: Codable {
    let generatedAtUTC: String
    let repoRoot: String
    let logPaths: [String]
    let modelSummaries: [ModelSummary]
    let fixRows: [FixComparisonRow]
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
    var baselineDB = URL(fileURLWithPath: "/tmp/karlsruhe-regbez-baseline.sqlite")
    var corridorDB = URL(fileURLWithPath: "/tmp/karlsruhe-regbez-corridor.sqlite")
    var outputJSON = cwd.appendingPathComponent("tmp", isDirectory: true).appendingPathComponent("selected_matcher_replay.json")
    var outputCSV = cwd.appendingPathComponent("tmp", isDirectory: true).appendingPathComponent("selected_matcher_replay.csv")
    var outputDiffCSV = cwd.appendingPathComponent("tmp", isDirectory: true).appendingPathComponent("selected_matcher_replay.diff.csv")
    var logURLs: [URL] = []

    var iterator = CommandLine.arguments.dropFirst().makeIterator()
    while let arg = iterator.next() {
        switch arg {
        case "--repo-root":
            guard let value = iterator.next() else {
                throw ArgumentError.message("Missing value for --repo-root")
            }
            repoRoot = URL(fileURLWithPath: value, isDirectory: true)
        case "--baseline-db":
            guard let value = iterator.next() else {
                throw ArgumentError.message("Missing value for --baseline-db")
            }
            baselineDB = URL(fileURLWithPath: value)
        case "--corridor-db":
            guard let value = iterator.next() else {
                throw ArgumentError.message("Missing value for --corridor-db")
            }
            corridorDB = URL(fileURLWithPath: value)
        case "--output-json":
            guard let value = iterator.next() else {
                throw ArgumentError.message("Missing value for --output-json")
            }
            outputJSON = URL(fileURLWithPath: value)
        case "--output-csv":
            guard let value = iterator.next() else {
                throw ArgumentError.message("Missing value for --output-csv")
            }
            outputCSV = URL(fileURLWithPath: value)
        case "--output-diff-csv":
            guard let value = iterator.next() else {
                throw ArgumentError.message("Missing value for --output-diff-csv")
            }
            outputDiffCSV = URL(fileURLWithPath: value)
        default:
            if arg.hasPrefix("--") {
                throw ArgumentError.message("Unknown argument: \(arg)")
            }
            logURLs.append(URL(fileURLWithPath: arg))
        }
    }

    if logURLs.isEmpty {
        logURLs = [
            repoRoot
                .appendingPathComponent("inspector", isDirectory: true)
                .appendingPathComponent("logs", isDirectory: true)
                .appendingPathComponent("20260314_171804_881_drive_match_log.ndjson"),
            repoRoot
                .appendingPathComponent("inspector", isDirectory: true)
                .appendingPathComponent("logs", isDirectory: true)
                .appendingPathComponent("20260314_211105_381_drive_match_log.ndjson")
        ]
    }

    return Args(
        repoRoot: repoRoot.standardizedFileURL,
        baselineDB: baselineDB.standardizedFileURL,
        corridorDB: corridorDB.standardizedFileURL,
        outputJSON: outputJSON.standardizedFileURL,
        outputCSV: outputCSV.standardizedFileURL,
        outputDiffCSV: outputDiffCSV.standardizedFileURL,
        logURLs: logURLs.map(\.standardizedFileURL)
    )
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

func candidateTrace(for wayID: String?, in result: SpeedLimitResult?) -> MatchCandidateTrace? {
    guard let wayID, let result else {
        return nil
    }
    return result.candidateTraces.first(where: { $0.wayID == wayID })
}

func loggedSimpleReason(for entry: DriveMatchLogEntry) -> String? {
    for step in entry.result?.selectionTrace ?? [] where step.step == "simple_speed_ref_heuristic" {
        let detail = step.detail
        guard let range = detail.range(of: "reason=") else {
            return nil
        }
        let remainder = detail[range.upperBound...]
        if let end = remainder.firstIndex(of: " ") {
            return String(remainder[..<end])
        }
        return String(remainder)
    }
    return nil
}

func outputDirectory(for url: URL) -> URL {
    url.deletingLastPathComponent()
}

func ensureParentDirectory(for url: URL) throws {
    try FileManager.default.createDirectory(
        at: outputDirectory(for: url),
        withIntermediateDirectories: true,
        attributes: nil
    )
}

func csvEscape(_ value: String) -> String {
    if value.contains(",") || value.contains("\"") || value.contains("\n") {
        return "\"\(value.replacingOccurrences(of: "\"", with: "\"\""))\""
    }
    return value
}

func csvValue(_ value: String?) -> String {
    csvEscape(value ?? "")
}

func csvValue(_ value: Int?) -> String {
    value.map(String.init) ?? ""
}

func csvValue(_ value: Double?) -> String {
    value.map { String($0) } ?? ""
}

func csvValue(_ value: Bool?) -> String {
    value.map { $0 ? "true" : "false" } ?? ""
}

func parseStringListEnv(_ name: String) -> Set<String> {
    guard let raw = ProcessInfo.processInfo.environment[name], !raw.isEmpty else {
        return []
    }
    return Set(
        raw
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    )
}

@main
enum Main {
    static func main() throws {
        let args = try parseArgs()
        let sweepOnly = ProcessInfo.processInfo.environment["YOUSPEED_SWEEP_ONLY"] == "1"
        let modelLabelFilter = parseStringListEnv("YOUSPEED_MODEL_LABELS")
        var modelConfigs = [
            ModelConfig(
                label: "connectedBaseline",
                dbURL: args.baselineDB,
                matchingModel: .connectedBaseline
            ),
            ModelConfig(
                label: "simpleSpeedRef",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefHeuristic
            ),
            ModelConfig(
                label: "simpleSpeedRefUrbanRelease",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefUrbanReleaseHeuristic
            ),
            ModelConfig(
                label: "simpleSpeedRefUrbanRelease10m",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic
            ),
            ModelConfig(
                label: "simpleSpeedRefStreetNameFallback",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefStreetNameFallbackHeuristic
            ),
            ModelConfig(
                label: "simpleSpeedRefStreetNameGuard",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefStreetNameGuardHeuristic
            ),
            ModelConfig(
                label: "simpleSpeedRefStreetNameGuardNodeAware",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefStreetNameGuardNodeAwareHeuristic
            ),
            ModelConfig(
                label: "simpleSpeedRefConnected",
                dbURL: args.baselineDB,
                matchingModel: .simpleSpeedRefConnectedHeuristic
            ),
            ModelConfig(
                label: "corridorRawMiniHMM",
                dbURL: args.corridorDB,
                matchingModel: .corridorHMMRawMiniHMM
            ),
            ModelConfig(
                label: "corridor",
                dbURL: args.corridorDB,
                matchingModel: .corridorHMM
            )
        ]
        if sweepOnly {
            modelConfigs = modelConfigs.filter { $0.label == "simpleSpeedRef" }
        }
        if !modelLabelFilter.isEmpty {
            modelConfigs = modelConfigs.filter { modelLabelFilter.contains($0.label) }
        }

        var entriesByLogName: [String: [DriveMatchLogEntry]] = [:]
        var logNames: [String] = []
        for logURL in args.logURLs {
            let entries = try loadDriveMatchLogEntries(url: logURL)
            entriesByLogName[logURL.lastPathComponent] = entries
            logNames.append(logURL.lastPathComponent)
        }

        typealias FixKey = String

        var modelPredictionsByKey: [String: [FixKey: ModelPrediction]] = [:]
        var modelSummaries: [ModelSummary] = []

        for config in modelConfigs {
            var aggregate = DriveLogReplayMetrics()
            var perLog: [ModelLogSummary] = []
            var predictions: [FixKey: ModelPrediction] = [:]

            for logURL in args.logURLs {
                let logName = logURL.lastPathComponent
                guard let entries = entriesByLogName[logName] else {
                    continue
                }
                let service = V3SpeedLimitService(
                    dbPath: config.dbURL.path,
                    matchingModel: config.matchingModel
                )
                var state = BundledMatchContextState()
                var logMetrics = DriveLogReplayMetrics()

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

                    logMetrics.replayedFixCount += 1
                    if result.selectionTrace.contains(where: { $0.step == "three_way_gate" }) {
                        logMetrics.usedThreeWayGateCount += 1
                    }
                    if result.usedMiniHMM {
                        logMetrics.usedMiniHMMCount += 1
                    }
                    if result.isTunnelSegment {
                        logMetrics.selectedTunnelFixCount += 1
                    }
                    if let loggedWayID = entry.result?.wayID {
                        logMetrics.loggedComparableCount += 1
                        if loggedWayID == result.wayID {
                            logMetrics.loggedAgreementCount += 1
                        }
                    }

                    let pseudoLabelWayID = hindsightPseudoLabelWayID(in: entries, at: index)
                    let loggedWayID = entry.result?.wayID
                    if let pseudoLabelWayID {
                        let predictedMatches = result.wayID == pseudoLabelWayID
                        let loggedCorrect = loggedWayID == pseudoLabelWayID
                        let isChangedExample = loggedWayID != pseudoLabelWayID
                        logMetrics.pseudoLabelExampleCount += 1
                        logMetrics.correctPseudoLabelCount += predictedMatches ? 1 : 0
                        if isChangedExample {
                            logMetrics.changedExampleCount += 1
                            logMetrics.changedCorrectCount += predictedMatches ? 1 : 0
                        } else {
                            logMetrics.unchangedExampleCount += 1
                            logMetrics.unchangedCorrectCount += predictedMatches ? 1 : 0
                        }
                        if !loggedCorrect && predictedMatches {
                            logMetrics.recoveredExamples += 1
                        } else if loggedCorrect && !predictedMatches {
                            logMetrics.regressedExamples += 1
                        }
                    }

                    let key = "\(logName)#\(entry.fixID)"
                    predictions[key] = ModelPrediction(
                        label: config.label,
                        wayID: result.wayID,
                        streetName: result.streetName,
                        streetRef: result.streetRef,
                        speedLimitKmh: result.speedLimitKmh,
                        isTunnelSegment: result.isTunnelSegment,
                        usedMiniHMM: result.usedMiniHMM,
                        usedThreeWayGate: result.selectionTrace.contains(where: { $0.step == "three_way_gate" }),
                        selectedRank: candidateRank(for: result.wayID, in: result),
                        pseudoLabelCandidateRank: candidateRank(for: pseudoLabelWayID, in: result),
                        agreesWithLogged: result.wayID == loggedWayID,
                        matchesPseudoLabel: pseudoLabelWayID.map { result.wayID == $0 },
                        queryTimeMs: result.queryTimeMs
                    )

                    state.record(
                        result,
                        lat: entry.lat,
                        lon: entry.lon,
                        headingDeg: entry.courseDeg,
                        horizontalAccuracyM: entry.horizontalAccM,
                        gpsSignalBars: entry.gpsSignalBars
                    )
                }

                aggregate.replayedFixCount += logMetrics.replayedFixCount
                aggregate.pseudoLabelExampleCount += logMetrics.pseudoLabelExampleCount
                aggregate.correctPseudoLabelCount += logMetrics.correctPseudoLabelCount
                aggregate.changedExampleCount += logMetrics.changedExampleCount
                aggregate.changedCorrectCount += logMetrics.changedCorrectCount
                aggregate.unchangedExampleCount += logMetrics.unchangedExampleCount
                aggregate.unchangedCorrectCount += logMetrics.unchangedCorrectCount
                aggregate.usedThreeWayGateCount += logMetrics.usedThreeWayGateCount
                aggregate.usedMiniHMMCount += logMetrics.usedMiniHMMCount
                aggregate.selectedTunnelFixCount += logMetrics.selectedTunnelFixCount
                aggregate.loggedAgreementCount += logMetrics.loggedAgreementCount
                aggregate.loggedComparableCount += logMetrics.loggedComparableCount
                aggregate.recoveredExamples += logMetrics.recoveredExamples
                aggregate.regressedExamples += logMetrics.regressedExamples

                perLog.append(
                    ModelLogSummary(
                        logName: logName,
                        replayedFixCount: logMetrics.replayedFixCount,
                        pseudoLabelExampleCount: logMetrics.pseudoLabelExampleCount,
                        changedExampleCount: logMetrics.changedExampleCount,
                        accuracy: logMetrics.accuracy,
                        changedRecall: logMetrics.changedRecall,
                        unchangedAccuracy: logMetrics.unchangedAccuracy,
                        loggedAgreement: logMetrics.loggedAgreement,
                        usedThreeWayGateCount: logMetrics.usedThreeWayGateCount,
                        usedMiniHMMCount: logMetrics.usedMiniHMMCount,
                        selectedTunnelFixCount: logMetrics.selectedTunnelFixCount,
                        recoveredExamples: logMetrics.recoveredExamples,
                        regressedExamples: logMetrics.regressedExamples,
                        netCorrections: logMetrics.netCorrections
                    )
                )
            }

            modelPredictionsByKey[config.label] = predictions
            modelSummaries.append(
                ModelSummary(
                    label: config.label,
                    dbPath: config.dbURL.path,
                    replayedFixCount: aggregate.replayedFixCount,
                    pseudoLabelExampleCount: aggregate.pseudoLabelExampleCount,
                    changedExampleCount: aggregate.changedExampleCount,
                    accuracy: aggregate.accuracy,
                    changedRecall: aggregate.changedRecall,
                    unchangedAccuracy: aggregate.unchangedAccuracy,
                    loggedAgreement: aggregate.loggedAgreement,
                    usedThreeWayGateCount: aggregate.usedThreeWayGateCount,
                    usedMiniHMMCount: aggregate.usedMiniHMMCount,
                    selectedTunnelFixCount: aggregate.selectedTunnelFixCount,
                    recoveredExamples: aggregate.recoveredExamples,
                    regressedExamples: aggregate.regressedExamples,
                    netCorrections: aggregate.netCorrections,
                    perLog: perLog
                )
            )
        }

        var fixRows: [FixComparisonRow] = []
        fixRows.reserveCapacity(entriesByLogName.values.reduce(0) { $0 + $1.count })

        for logName in logNames {
            guard let entries = entriesByLogName[logName] else {
                continue
            }
            for (index, entry) in entries.enumerated() {
                let key = "\(logName)#\(entry.fixID)"
                let pseudoLabelWayID = hindsightPseudoLabelWayID(in: entries, at: index)
                let pseudoTrace = candidateTrace(for: pseudoLabelWayID, in: entry.result)
                let predictions = modelConfigs.compactMap { config in
                    modelPredictionsByKey[config.label]?[key]
                }
                let distinctPredictedWayCount = Set(predictions.compactMap(\.wayID)).count
                let allModelsAgree = distinctPredictedWayCount <= 1
                let loggedWayID = entry.result?.wayID
                let anyModelDiffersFromLogged = predictions.contains { $0.wayID != loggedWayID }
                let anyModelMatchesPseudoLabel = predictions.contains { $0.matchesPseudoLabel == true }
                let bestMatchingModels = predictions.compactMap { prediction in
                    prediction.matchesPseudoLabel == true ? prediction.label : nil
                }

                fixRows.append(
                    FixComparisonRow(
                        logName: logName,
                        logIndex: index,
                        fixID: entry.fixID,
                        timestampUTC: entry.timestampUTC,
                        lat: entry.lat,
                        lon: entry.lon,
                        speedKmh: entry.speedKmh,
                        horizontalAccM: entry.horizontalAccM,
                        courseDeg: entry.courseDeg,
                        gpsSignalBars: entry.gpsSignalBars,
                        status: entry.status,
                        loggedWayID: loggedWayID,
                        loggedStreetName: entry.result?.streetName,
                        loggedStreetRef: entry.result?.streetRef,
                        loggedMatchesPseudoLabel: pseudoLabelWayID.map { loggedWayID == $0 },
                        loggedPseudoLabelCandidateRank: candidateRank(for: pseudoLabelWayID, in: entry.result),
                        loggedSimpleReason: loggedSimpleReason(for: entry),
                        pseudoLabelWayID: pseudoLabelWayID,
                        pseudoLabelStreetName: pseudoTrace?.streetName,
                        pseudoLabelStreetRef: pseudoTrace?.streetRef,
                        isChangedExample: pseudoLabelWayID.map { loggedWayID != $0 },
                        predictions: predictions,
                        distinctPredictedWayCount: distinctPredictedWayCount,
                        allModelsAgree: allModelsAgree,
                        anyModelDiffersFromLogged: anyModelDiffersFromLogged,
                        anyModelMatchesPseudoLabel: anyModelMatchesPseudoLabel,
                        bestMatchingModels: bestMatchingModels
                    )
                )
            }
        }

        let payload = OutputPayload(
            generatedAtUTC: ISO8601DateFormatter().string(from: Date()),
            repoRoot: args.repoRoot.path,
            logPaths: args.logURLs.map(\.path),
            modelSummaries: modelSummaries,
            fixRows: fixRows
        )

        try ensureParentDirectory(for: args.outputJSON)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(payload).write(to: args.outputJSON)

        try ensureParentDirectory(for: args.outputCSV)
        let modelPrefixes = modelConfigs.map(\.label)
        var header = [
            "log_name",
            "log_index",
            "fix_id",
            "timestamp_utc",
            "lat",
            "lon",
            "speed_kmh",
            "horizontal_acc_m",
            "course_deg",
            "gps_signal_bars",
            "status",
            "logged_way_id",
            "logged_street_name",
            "logged_street_ref",
            "logged_simple_reason",
            "pseudo_label_way_id",
            "pseudo_label_street_name",
            "pseudo_label_street_ref",
            "logged_matches_pseudo_label",
            "logged_pseudo_label_candidate_rank",
            "is_changed_example",
            "distinct_predicted_way_count",
            "all_models_agree",
            "any_model_differs_from_logged",
            "any_model_matches_pseudo_label",
            "best_matching_models"
        ]
        for prefix in modelPrefixes {
            header.append(contentsOf: [
                "\(prefix)_way_id",
                "\(prefix)_street_name",
                "\(prefix)_street_ref",
                "\(prefix)_speed_limit_kmh",
                "\(prefix)_is_tunnel_segment",
                "\(prefix)_used_mini_hmm",
                "\(prefix)_used_three_way_gate",
                "\(prefix)_selected_rank",
                "\(prefix)_pseudo_label_candidate_rank",
                "\(prefix)_agrees_with_logged",
                "\(prefix)_matches_pseudo_label",
                "\(prefix)_query_time_ms"
            ])
        }

        var csvLines: [String] = [header.joined(separator: ",")]
        csvLines.reserveCapacity(fixRows.count + 1)
        var diffLines: [String] = [header.joined(separator: ",")]
        diffLines.reserveCapacity(fixRows.count + 1)

        for row in fixRows {
            var columns: [String] = [
                csvEscape(row.logName),
                String(row.logIndex),
                String(row.fixID),
                csvEscape(row.timestampUTC),
                String(row.lat),
                String(row.lon),
                String(row.speedKmh),
                String(row.horizontalAccM),
                String(row.courseDeg),
                String(row.gpsSignalBars),
                csvEscape(row.status),
                csvValue(row.loggedWayID),
                csvValue(row.loggedStreetName),
                csvValue(row.loggedStreetRef),
                csvValue(row.loggedSimpleReason),
                csvValue(row.pseudoLabelWayID),
                csvValue(row.pseudoLabelStreetName),
                csvValue(row.pseudoLabelStreetRef),
                csvValue(row.loggedMatchesPseudoLabel),
                csvValue(row.loggedPseudoLabelCandidateRank),
                csvValue(row.isChangedExample),
                String(row.distinctPredictedWayCount),
                csvValue(row.allModelsAgree),
                csvValue(row.anyModelDiffersFromLogged),
                csvValue(row.anyModelMatchesPseudoLabel),
                csvEscape(row.bestMatchingModels.joined(separator: "|"))
            ]
            let byLabel = Dictionary(uniqueKeysWithValues: row.predictions.map { ($0.label, $0) })
            for prefix in modelPrefixes {
                let prediction = byLabel[prefix]
                columns.append(contentsOf: [
                    csvValue(prediction?.wayID),
                    csvValue(prediction?.streetName),
                    csvValue(prediction?.streetRef),
                    csvValue(prediction?.speedLimitKmh),
                    csvValue(prediction?.isTunnelSegment),
                    csvValue(prediction?.usedMiniHMM),
                    csvValue(prediction?.usedThreeWayGate),
                    csvValue(prediction?.selectedRank),
                    csvValue(prediction?.pseudoLabelCandidateRank),
                    csvValue(prediction?.agreesWithLogged),
                    csvValue(prediction?.matchesPseudoLabel),
                    csvValue(prediction?.queryTimeMs)
                ])
            }
            let line = columns.joined(separator: ",")
            csvLines.append(line)
            if row.anyModelDiffersFromLogged || !row.allModelsAgree {
                diffLines.append(line)
            }
        }

        try csvLines.joined(separator: "\n").appending("\n").write(to: args.outputCSV, atomically: true, encoding: .utf8)

        try ensureParentDirectory(for: args.outputDiffCSV)
        try diffLines.joined(separator: "\n").appending("\n").write(
            to: args.outputDiffCSV,
            atomically: true,
            encoding: .utf8
        )

        FileHandle.standardOutput.write(Data("Wrote JSON: \(args.outputJSON.path)\n".utf8))
        FileHandle.standardOutput.write(Data("Wrote CSV: \(args.outputCSV.path)\n".utf8))
        FileHandle.standardOutput.write(Data("Wrote diff CSV: \(args.outputDiffCSV.path)\n".utf8))
    }
}

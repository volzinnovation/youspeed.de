import Foundation

// Shared by the consumer and benchmark targets; matcher contract changes belong here.
struct TrafficSignRouteRelationMembership: Codable, Equatable, Hashable, Sendable {
    let groupID: Int
    let sourceRelationID: Int64?

    var isValid: Bool { groupID > 0 }
}

struct WayMatchRecentFix: Sendable {
    let lat: Double
    let lon: Double
    let headingDeg: Double?
    let headingAccuracyDeg: Double?
    let speedKmh: Double?
    let horizontalAccuracyM: Double?
    let gpsSignalBars: Int?

    init(
        lat: Double,
        lon: Double,
        headingDeg: Double? = nil,
        headingAccuracyDeg: Double? = nil,
        speedKmh: Double? = nil,
        horizontalAccuracyM: Double? = nil,
        gpsSignalBars: Int? = nil
    ) {
        self.lat = lat
        self.lon = lon
        self.headingDeg = headingDeg
        self.headingAccuracyDeg = headingAccuracyDeg
        self.speedKmh = speedKmh
        self.horizontalAccuracyM = horizontalAccuracyM
        self.gpsSignalBars = gpsSignalBars
    }
}

struct CorridorMatchState: Codable, Sendable {
    let kind: String
    let corridorID: Int
    let sideNodeKey: String
    let depthM: Double
    let spanM: Double
    let depthNodes: Int
    let spanNodes: Int
}

struct WayMatchContext: Sendable {
    let preferredWayID: String?
    let preferredHighway: String?
    let preferredEndpointProximityM: Double?
    let recentWayIDs: [String]
    let recentFixes: [WayMatchRecentFix]
    let sameRefUrbanReleaseStreak: Int
    let preferredStreetRef: String?
    let activeStreetRef: String?
    let preferredStreetName: String?
    let recentStreetRefs: [String]
    let consecutiveNoRefMatchCount: Int
    let recentTunnelCandidateWayIDs: [String]
    let recentTunnelCandidateRefs: [String]
    let recentTunnelApproachWayIDs: [String]
    let recentTunnelApproachRefs: [String]
    let tunnelApproachFixCount: Int
    let tunnelApproachBaselineAccuracyM: Double?
    let tunnelApproachBaselineSignalBars: Int?
    let recentHypotheses: [WayMatchHypothesis]
    let matchedFixCount: Int
    let hadRecentGPSSignalLoss: Bool
    let isInTunnelMode: Bool
    let isInMotorwayMode: Bool
    let activeCorridorState: CorridorMatchState?
    let approachCorridorState: CorridorMatchState?
    let approachCorridorFixCount: Int
    let approachCorridorStartDepthM: Double?
    let approachCorridorStartDepthNodes: Int?

    init(
        preferredWayID: String?,
        preferredHighway: String? = nil,
        preferredEndpointProximityM: Double? = nil,
        recentWayIDs: [String],
        recentFixes: [WayMatchRecentFix] = [],
        sameRefUrbanReleaseStreak: Int = 0,
        preferredStreetRef: String?,
        activeStreetRef: String? = nil,
        preferredStreetName: String? = nil,
        recentStreetRefs: [String],
        consecutiveNoRefMatchCount: Int = 0,
        recentTunnelCandidateWayIDs: [String] = [],
        recentTunnelCandidateRefs: [String] = [],
        recentTunnelApproachWayIDs: [String] = [],
        recentTunnelApproachRefs: [String] = [],
        tunnelApproachFixCount: Int = 0,
        tunnelApproachBaselineAccuracyM: Double? = nil,
        tunnelApproachBaselineSignalBars: Int? = nil,
        recentHypotheses: [WayMatchHypothesis] = [],
        matchedFixCount: Int = 0,
        hadRecentGPSSignalLoss: Bool = false,
        isInTunnelMode: Bool = false,
        isInMotorwayMode: Bool = false,
        activeCorridorState: CorridorMatchState? = nil,
        approachCorridorState: CorridorMatchState? = nil,
        approachCorridorFixCount: Int = 0,
        approachCorridorStartDepthM: Double? = nil,
        approachCorridorStartDepthNodes: Int? = nil
    ) {
        self.preferredWayID = preferredWayID
        self.preferredHighway = preferredHighway
        self.preferredEndpointProximityM = preferredEndpointProximityM
        self.recentWayIDs = recentWayIDs
        self.recentFixes = recentFixes
        self.sameRefUrbanReleaseStreak = max(sameRefUrbanReleaseStreak, 0)
        self.preferredStreetRef = preferredStreetRef
        self.activeStreetRef = activeStreetRef
        self.preferredStreetName = preferredStreetName
        self.recentStreetRefs = recentStreetRefs
        self.consecutiveNoRefMatchCount = max(consecutiveNoRefMatchCount, 0)
        self.recentTunnelCandidateWayIDs = recentTunnelCandidateWayIDs
        self.recentTunnelCandidateRefs = recentTunnelCandidateRefs
        self.recentTunnelApproachWayIDs = recentTunnelApproachWayIDs
        self.recentTunnelApproachRefs = recentTunnelApproachRefs
        self.tunnelApproachFixCount = tunnelApproachFixCount
        self.tunnelApproachBaselineAccuracyM = tunnelApproachBaselineAccuracyM
        self.tunnelApproachBaselineSignalBars = tunnelApproachBaselineSignalBars
        self.recentHypotheses = recentHypotheses
        self.matchedFixCount = matchedFixCount
        self.hadRecentGPSSignalLoss = hadRecentGPSSignalLoss
        self.isInTunnelMode = isInTunnelMode
        self.isInMotorwayMode = isInMotorwayMode
        self.activeCorridorState = activeCorridorState
        self.approachCorridorState = approachCorridorState
        self.approachCorridorFixCount = approachCorridorFixCount
        self.approachCorridorStartDepthM = approachCorridorStartDepthM
        self.approachCorridorStartDepthNodes = approachCorridorStartDepthNodes
    }
}

struct WayMatchHypothesis: Codable, Sendable {
    let wayID: String
    let streetRef: String?
    let highway: String?
    let corridorState: String?
    let corridorKind: String?
    let corridorID: Int?
    let corridorSideNodeKey: String?
    let cumulativeCost: Double
    let emissionScore: Double
    let endpointProximityM: Double
    let startLat: Double?
    let startLon: Double?
    let endLat: Double?
    let endLon: Double?
    let isTunnel: Bool

    init(
        wayID: String,
        streetRef: String?,
        highway: String?,
        corridorState: String? = nil,
        corridorKind: String? = nil,
        corridorID: Int? = nil,
        corridorSideNodeKey: String? = nil,
        cumulativeCost: Double,
        emissionScore: Double,
        endpointProximityM: Double,
        startLat: Double?,
        startLon: Double?,
        endLat: Double?,
        endLon: Double?,
        isTunnel: Bool
    ) {
        self.wayID = wayID
        self.streetRef = streetRef
        self.highway = highway
        self.corridorState = corridorState
        self.corridorKind = corridorKind
        self.corridorID = corridorID
        self.corridorSideNodeKey = corridorSideNodeKey
        self.cumulativeCost = cumulativeCost
        self.emissionScore = emissionScore
        self.endpointProximityM = endpointProximityM
        self.startLat = startLat
        self.startLon = startLon
        self.endLat = endLat
        self.endLon = endLon
        self.isTunnel = isTunnel
    }

    var endpoints: [(Double, Double)] {
        var values: [(Double, Double)] = []
        if let startLat, let startLon {
            values.append((startLat, startLon))
        }
        if let endLat, let endLon {
            values.append((endLat, endLon))
        }
        return values
    }
}

struct MatchCandidateTrace: Codable, Sendable {
    let rank: Int
    let wayID: String?
    let streetName: String?
    let streetRef: String?
    let highway: String?
    let service: String?
    let tunnel: String?
    let distanceM: Double
    let endpointProximityM: Double?
    let score: Double
    let geometryScore: Double?
    let portalEligible: Bool?
    let corridorKind: String?
    let corridorID: Int?
    let corridorSideNodeKey: String?
    let corridorDepthM: Double?
    let corridorRemainingM: Double?
    let corridorDepthNodes: Int?
    let corridorRemainingNodes: Int?
    let corridorEntryZone: Bool?
    let corridorExitZone: Bool?
    let continuityClass: String
    let tunnelSelectable: Bool
    let corridorSelectable: Bool?
    let isSelected: Bool
}

struct MatchSelectionTrace: Codable, Sendable {
    let step: String
    let detail: String
}

struct DriveMatchReplayHindsightDebug: Codable, Sendable {
    let wayID: String
    let futureWindow: Int
    let minFutureRunLength: Int
    let minAgreementRatio: Double
    let loggedMatches: Bool
    let replayMatches: Bool
    let loggedCandidateRank: Int?
    let replayCandidateRank: Int?
}

struct DriveMatchReplayDebug: Codable, Sendable {
    let annotationVersion: Int
    let replayKind: String
    let sourceLogName: String
    let outcome: String
    let isError: Bool
    let issueKinds: [String]
    let loggedMatchesReplay: Bool
    let loggedSelectedRank: Int?
    let replaySelectedRank: Int?
    let replayUsedThreeWayGate: Bool
    let hindsight: DriveMatchReplayHindsightDebug?
    let replayResult: SpeedLimitResult
}

struct SpeedLimitResult: Codable, Sendable {
    var applicabilityGeometry: TSRMapGeometry? = nil
    let speedLimitKmh: Int?
    let isUnlimitedSpeedLimit: Bool?
    let wayID: String?
    let highway: String?
    let service: String?
    let tunnel: String?
    let bridge: String?
    let covered: String?
    let location: String?
    let layer: Int?
    let level: Int?
    let isTunnelSegment: Bool
    let streetName: String?
    let streetBaseName: String?
    let streetRef: String?
    let matchedEndpointProximityM: Double?
    let cityName: String?
    let cityPlaceName: String?
    let cityDistrictName: String?
    let insideCity: Bool?
    let citySource: String?
    let cityResolveMs: Double
    let cityCandidateBoundaries: Int
    let cityContainingBoundaries: Int
    let cityPlaceCandidates: Int
    let queryTimeMs: Double
    let candidateCount: Int
    let speedCandidateCount: Int
    let nearestCandidateDistanceM: Double?
    let nearestSpeedCandidateDistanceM: Double?
    let nearbyTunnelCandidateWayIDs: [String]
    let nearbyTunnelCandidateRefs: [String]
    let usedMiniHMM: Bool
    let miniHMMCandidateCount: Int
    let matchHypotheses: [WayMatchHypothesis]
    let candidateTraces: [MatchCandidateTrace]
    let selectionTrace: [MatchSelectionTrace]
    let activeCorridorState: CorridorMatchState?
    /// `nil` means the result came from an older serialized log. `false`
    /// means the opened bundle was inspected and lacks the capability.
    let routeContinuityAvailable: Bool?
    let routeRelationMemberships: [TrafficSignRouteRelationMembership]?
}

struct DriveMatchLogEntry: Codable, Sendable {
    let fixID: Int
    let timestampUTC: String
    let lat: Double
    let lon: Double
    let speedKmh: Double
    let horizontalAccM: Double
    let verticalAccM: Double
    let courseDeg: Double
    let gpsSignalBars: Int
    let status: String
    let speedLimitOverrideKmh: Int?
    let tunnelModeState: String
    let result: SpeedLimitResult?
    let error: String?
    let replayDebug: DriveMatchReplayDebug?

    init(
        fixID: Int,
        timestampUTC: String,
        lat: Double,
        lon: Double,
        speedKmh: Double,
        horizontalAccM: Double,
        verticalAccM: Double,
        courseDeg: Double,
        gpsSignalBars: Int,
        status: String,
        speedLimitOverrideKmh: Int?,
        tunnelModeState: String,
        result: SpeedLimitResult?,
        error: String?,
        replayDebug: DriveMatchReplayDebug? = nil
    ) {
        self.fixID = fixID
        self.timestampUTC = timestampUTC
        self.lat = lat
        self.lon = lon
        self.speedKmh = speedKmh
        self.horizontalAccM = horizontalAccM
        self.verticalAccM = verticalAccM
        self.courseDeg = courseDeg
        self.gpsSignalBars = gpsSignalBars
        self.status = status
        self.speedLimitOverrideKmh = speedLimitOverrideKmh
        self.tunnelModeState = tunnelModeState
        self.result = result
        self.error = error
        self.replayDebug = replayDebug
    }
}

enum ConsumerAppError: Error, LocalizedError {
    case invalidManifest(String)
    case io(String)
    case network(String)
    case checksum(String)
    case sqlite(String)

    var errorDescription: String? {
        switch self {
        case .invalidManifest(let message): return message
        case .io(let message): return message
        case .network(let message): return message
        case .checksum(let message): return message
        case .sqlite(let message): return message
        }
    }
}

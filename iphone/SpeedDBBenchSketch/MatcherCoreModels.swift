import Foundation

struct WayMatchContext: Sendable {
    let preferredWayID: String?
    let recentWayIDs: [String]
    let preferredStreetRef: String?
    let recentStreetRefs: [String]
    let recentTunnelCandidateWayIDs: [String]
    let recentTunnelCandidateRefs: [String]
    let recentHypotheses: [WayMatchHypothesis]
    let matchedFixCount: Int
    let hadRecentGPSSignalLoss: Bool
    let isInTunnelMode: Bool

    init(
        preferredWayID: String?,
        recentWayIDs: [String],
        preferredStreetRef: String?,
        recentStreetRefs: [String],
        recentTunnelCandidateWayIDs: [String] = [],
        recentTunnelCandidateRefs: [String] = [],
        recentHypotheses: [WayMatchHypothesis] = [],
        matchedFixCount: Int = 0,
        hadRecentGPSSignalLoss: Bool = false,
        isInTunnelMode: Bool = false
    ) {
        self.preferredWayID = preferredWayID
        self.recentWayIDs = recentWayIDs
        self.preferredStreetRef = preferredStreetRef
        self.recentStreetRefs = recentStreetRefs
        self.recentTunnelCandidateWayIDs = recentTunnelCandidateWayIDs
        self.recentTunnelCandidateRefs = recentTunnelCandidateRefs
        self.recentHypotheses = recentHypotheses
        self.matchedFixCount = matchedFixCount
        self.hadRecentGPSSignalLoss = hadRecentGPSSignalLoss
        self.isInTunnelMode = isInTunnelMode
    }
}

struct WayMatchHypothesis: Sendable {
    let wayID: String
    let streetRef: String?
    let highway: String?
    let cumulativeCost: Double
    let emissionScore: Double
    let endpointProximityM: Double
    let startLat: Double?
    let startLon: Double?
    let endLat: Double?
    let endLon: Double?
    let isTunnel: Bool

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

struct SpeedLimitResult {
    let speedLimitKmh: Int?
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
    let cityName: String?
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

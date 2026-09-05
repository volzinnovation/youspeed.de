import Foundation
import SQLite3

final class V3SpeedLimitService {
    enum MatchingModel {
        case corridorHMM
        case corridorHMMRawMiniHMM
        case corridorHMMNoThreeWayGate
        case corridorHMMNoSameRefBounceGate
        case corridorHMMAntiABAHysteresis
        case simpleSpeedRefHeuristic
        case simpleSpeedRefUrbanReleaseHeuristic
        case simpleSpeedRefUrbanReleaseNarrowWindowHeuristic
        case simpleSpeedRefStreetNameFallbackHeuristic
        case simpleSpeedRefStreetNameGuardHeuristic
        case simpleSpeedRefStreetNameGuardNodeAwareHeuristic
        case simpleSequenceParticleHeuristic
        case simpleSequenceViterbiHeuristic
        case simpleSpeedRefConnectedHeuristic
        case connectedBaseline
    }

    private let dbPath: String
    private let countryCode: String?
    private let matchingModel: MatchingModel
    private let corridorPairCacheLock = NSLock()
    private var cachedCorridorPairContext: CorridorPairContext?

    private var usesCorridorMatcher: Bool {
        switch matchingModel {
        case .corridorHMM,
             .corridorHMMRawMiniHMM,
             .corridorHMMNoThreeWayGate,
             .corridorHMMNoSameRefBounceGate,
             .corridorHMMAntiABAHysteresis:
            return true
        case .simpleSpeedRefHeuristic,
             .simpleSpeedRefUrbanReleaseHeuristic,
             .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic,
             .simpleSpeedRefStreetNameFallbackHeuristic,
             .simpleSpeedRefStreetNameGuardHeuristic,
             .simpleSpeedRefStreetNameGuardNodeAwareHeuristic,
             .simpleSequenceParticleHeuristic,
             .simpleSequenceViterbiHeuristic,
             .simpleSpeedRefConnectedHeuristic,
             .connectedBaseline:
            return false
        }
    }

    private var usesThreeWayGate: Bool {
        matchingModel != .corridorHMMNoThreeWayGate
    }

    private var usesSameRefBounceGate: Bool {
        matchingModel != .corridorHMMNoSameRefBounceGate
    }

    private var usesAntiABAHysteresis: Bool {
        matchingModel == .corridorHMMAntiABAHysteresis
    }

    private struct WayCandidate {
        let wayID: String?
        let highway: String?
        let service: String?
        let tunnel: String?
        let streetName: String?
        let streetBaseName: String?
        let streetRef: String?
        let speedKmh: Int?
        let speedSource: DerivedSpeedSource
        let isUnlimitedSpeedLimit: Bool
        let distanceM: Double
        let endpointProximityM: Double
        let distanceToStartM: Double?
        let distanceToEndM: Double?
        let score: Double
        let queryPoint: (Double, Double)
        let points: [(Double, Double)]
        let localHeadingDeg: Double?
        let wayLengthM: Double?
        let startNodeKey: String?
        let endNodeKey: String?
        let startPoint: (Double, Double)?
        let endPoint: (Double, Double)?
        let startHeadingDeg: Double?
        let endHeadingDeg: Double?
    }

    private struct PolylineMetrics {
        let distanceM: Double
        let endpointProximityM: Double
        let distanceToStartM: Double
        let distanceToEndM: Double
        let localHeadingDeg: Double?
    }

    private enum DerivedSpeedSource {
        case explicitTag
        case explicitUnlimitedTag
        case inheritedTag
        case highwayClass
        case none
    }

    private struct CityBoundaryCandidate {
        let rowID: Int64
        let adminLevel: Int
        let name: String?
        let minLon: Double
        let minLat: Double
        let maxLon: Double
        let maxLat: Double
    }

    private struct AreaCandidate {
        let name: String?
        let place: String?
        let boundary: String?
        let adminLevel: Int?
        let minLon: Double
        let minLat: Double
        let maxLon: Double
        let maxLat: Double
        let points: [(Double, Double)]
    }

    private typealias ResolvedCityContext = (
        insideCity: Bool?,
        cityName: String?,
        cityPlaceName: String?,
        cityDistrictName: String?,
        citySource: String,
        candidateBoundaries: Int,
        containingBoundaries: Int,
        placeCandidates: Int
    )

    private struct CityContext {
        let insideCity: Bool?
        let cityName: String?
        let cityPlaceName: String?
        let cityDistrictName: String?
        let citySource: String?
        let candidateBoundaries: Int
        let containingBoundaries: Int
        let placeCandidates: Int
        let resolveMs: Double
    }

    private struct ResidentialContext {
        let insideCity: Bool?
        let candidatePolygons: Int
        let containingPolygons: Int
        let resolveMs: Double
    }

    private struct NormalizedMatchContext {
        let preferredWayID: String?
        let preferredHighway: String?
        let preferredEndpointProximityM: Double?
        let recentWayIDs: Set<String>
        let recentWayHistory: [String]
        let recentFixes: [WayMatchRecentFix]
        let sameRefUrbanReleaseStreak: Int
        let preferredStreetRefs: Set<String>
        let activeStreetRefTokens: Set<String>
        let activeStreetNameTokens: Set<String>
        let recentStreetRefs: Set<String>
        let consecutiveNoRefMatchCount: Int
        let recentTunnelCandidateWayIDs: Set<String>
        let recentTunnelCandidateRefs: Set<String>
        let recentTunnelApproachWayIDs: Set<String>
        let recentTunnelApproachRefs: Set<String>
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
    }

    private struct WayLinkInfo {
        var linkedWayIDs: Set<String> = []
        var sharedRefWayIDs: Set<String> = []
        var sharedNodeKeysByLinkedWayID: [String: Set<String>] = [:]
    }

    private struct WayLinksContext {
        let available: Bool
        let byWayID: [String: WayLinkInfo]

        func isLinked(from sourceWayID: String?, to targetWayID: String?) -> Bool {
            guard let sourceWayID, let targetWayID else {
                return false
            }
            guard let info = byWayID[sourceWayID] else {
                return false
            }
            return info.linkedWayIDs.contains(targetWayID)
        }

        func isSharedRefLinked(from sourceWayID: String?, to targetWayID: String?) -> Bool {
            guard let sourceWayID, let targetWayID else {
                return false
            }
            guard let info = byWayID[sourceWayID] else {
                return false
            }
            return info.sharedRefWayIDs.contains(targetWayID)
        }

        func sharedNodeKeys(from sourceWayID: String?, to targetWayID: String?) -> Set<String> {
            guard let sourceWayID, let targetWayID else {
                return []
            }
            guard let info = byWayID[sourceWayID] else {
                return []
            }
            return info.sharedNodeKeysByLinkedWayID[targetWayID] ?? []
        }
    }

    private enum WayContinuityKind: String {
        case routeRelationConnected = "route_relation_connected"
        case sameStreetNameConnected = "same_street_name_connected"
    }

    private enum WayContinuityStrength: Equatable {
        case none
        case sameStreetNameConnected
        case routeRelationConnected

        var transitionBonus: Double {
            switch self {
            case .none:
                return 0.0
            case .sameStreetNameConnected:
                return V3SpeedLimitService.simpleSequenceViterbiSameStreetContinuityBonus
            case .routeRelationConnected:
                return V3SpeedLimitService.simpleSequenceViterbiRouteRelationContinuityBonus
            }
        }
    }

    private struct WayContinuityMembershipInfo {
        var routeRelationGroupIDs: Set<Int> = []
        var sameStreetNameGroupIDs: Set<Int> = []

        func sharedStrength(with other: WayContinuityMembershipInfo?) -> WayContinuityStrength {
            guard let other else {
                return .none
            }
            if !routeRelationGroupIDs.isDisjoint(with: other.routeRelationGroupIDs) {
                return .routeRelationConnected
            }
            if !sameStreetNameGroupIDs.isDisjoint(with: other.sameStreetNameGroupIDs) {
                return .sameStreetNameConnected
            }
            return .none
        }
    }

    private struct WayContinuityContext {
        let available: Bool
        let byWayID: [String: WayContinuityMembershipInfo]

        var trackedWayCount: Int {
            byWayID.count
        }

        func sharedStrength(from sourceWayID: String?, to targetWayID: String?) -> WayContinuityStrength {
            guard let sourceWayID, let targetWayID else {
                return .none
            }
            guard let source = byWayID[sourceWayID] else {
                return .none
            }
            return source.sharedStrength(with: byWayID[targetWayID])
        }
    }

    private struct WayEndpointInfo {
        let wayID: String
        let refNorm: String
        let highway: String?
        let tunnelFlag: Bool
        let startNodeKey: String
        let startLon: Double
        let startLat: Double
        let endNodeKey: String
        let endLon: Double
        let endLat: Double
        let wayLengthM: Double
    }

    private struct LocalWayGraphEdge {
        let wayID: String
        let toNodeKey: String
        let lengthM: Double
    }

    private struct LocalWayGraphContext {
        let available: Bool
        let byWayID: [String: WayEndpointInfo]
        let adjacencyByNodeKey: [String: [LocalWayGraphEdge]]
        let expandedWayCount: Int
    }

    private struct CorridorProgressInfo {
        let kind: String
        let corridorID: Int
        let sideNodeKey: String
        let startDepthM: Double
        let endDepthM: Double
        let spanM: Double
        let startDepthNodes: Int
        let endDepthNodes: Int
        let spanNodes: Int
    }

    private struct CorridorProgressContext {
        let available: Bool
        let byWayID: [String: [CorridorProgressInfo]]
    }

    private struct CorridorPairRelation {
        let corridorKind: String
        let corridorID: Int
        let sideNodeKey: String
        let pairedKind: String
        let pairedCorridorID: Int
    }

    private struct CorridorPairContext {
        let available: Bool
        let byMainKey: [String: [CorridorPairRelation]]
        let byPairedKey: [String: [CorridorPairRelation]]
    }

    private struct CandidateCorridorState {
        let snapshot: CorridorMatchState
        let entryZone: Bool
        let exitZone: Bool
        let progressDeltaM: Double?
        let progressDeltaNodes: Int?
    }

    private struct MiniHMMSelection {
        let selectedCandidate: WayCandidate?
        let selectedCorridorState: CorridorSequenceState?
        let hypotheses: [WayMatchHypothesis]
        let used: Bool
        let candidateCount: Int
    }

    private struct TransitionHeadingEvidence {
        let currentMismatchDeg: Double
        let candidateMismatchDeg: Double
        let turnAngleDeg: Double
        let speedKmh: Double
        let nearEndpoint: Bool
        let serviceLike: Bool

        var currentAligned: Bool {
            currentMismatchDeg <= V3SpeedLimitService.transitionHeadingCurrentAlignmentThresholdDeg
        }

        var candidateClearlyBetterAligned: Bool {
            candidateMismatchDeg + V3SpeedLimitService.transitionHeadingImprovementMarginDeg <= currentMismatchDeg
        }

        var meaningfulTurn: Bool {
            turnAngleDeg >= V3SpeedLimitService.transitionHeadingMeaningfulTurnDeg
        }

        var sharpTurn: Bool {
            turnAngleDeg >= V3SpeedLimitService.transitionHeadingSharpTurnDeg
        }

        var verySharpTurn: Bool {
            turnAngleDeg >= V3SpeedLimitService.transitionHeadingVerySharpTurnDeg
        }
    }

    private enum JunctionNodeTraversalDirection {
        case towardNode
        case awayFromNode
    }

    private enum CorridorState: String {
        case surface
        case tunnel
        case motorway
        case motorwayLink
    }

    private enum CorridorSequenceState: String {
        case surface
        case tunnelPortal
        case tunnelInside
        case tunnelExit
        case motorwayPortal
        case motorwayInside
        case motorwayExit
    }

    private struct SignalQualityEvidence {
        let tunnelApproachFixCount: Int
        let horizontalAccuracyDeltaM: Double
        let gpsSignalBarsDrop: Int
        let hadRecentGPSSignalLoss: Bool

        var tunnelScore: Double {
            if hadRecentGPSSignalLoss {
                return 1.0
            }
            guard tunnelApproachFixCount >= V3SpeedLimitService.tunnelApproachMinFixCount else {
                return 0.0
            }
            let accuracyComponent = min(max(horizontalAccuracyDeltaM / V3SpeedLimitService.tunnelApproachAccuracyDeltaM, 0.0), 1.0)
            let barsComponent = min(max(Double(gpsSignalBarsDrop) / Double(V3SpeedLimitService.tunnelApproachSignalDropBars), 0.0), 1.0)
            return min(1.0, max(accuracyComponent, barsComponent))
        }
    }

    private struct PortalMotionMetrics {
        let enteringFromStart: Bool
        let currentPortalDistanceM: Double
        let bestApproachDeltaM: Double
        let bestInteriorProgressDeltaM: Double
        let alignmentScore: Double
        let proximityScore: Double
    }

    private struct CorridorAnchor {
        let wayID: String?
        let highway: String?
        let endpointProximityM: Double?
        let isInTunnelMode: Bool

        var state: CorridorState {
            if isInTunnelMode {
                return .tunnel
            }
            switch (highway ?? "").lowercased() {
            case "motorway":
                return .motorway
            case "motorway_link":
                return .motorwayLink
            default:
                return .surface
            }
        }
    }

    private enum CandidateNetwork: String {
        case surface
        case tunnel
        case motorway

        var rtreeTableName: String {
            "\(rawValue)_way_network_rtree"
        }
    }

    private struct CandidateQueryResult {
        let candidates: [WayCandidate]
        let candidateCount: Int
        let speedCandidateCount: Int
        let nearestCandidateDistance: Double
        let nearestSpeedCandidateDistance: Double
        let nearbyTunnelCandidateWayIDs: [String]
        let nearbyTunnelCandidateRefs: Set<String>
        let queryRadiusM: Double
    }

    private struct TraceRankedCandidate {
        let candidate: WayCandidate
        let continuity: ContinuityClass
        let portalEligible: Bool
        let corridorState: CandidateCorridorState?
        let tunnelSelectable: Bool
        let corridorSelectable: Bool
        let traceScore: Double
        let traceRank: Int
    }

    private struct ThreeWayGateSelection {
        let candidate: WayCandidate
        let className: String
        let probabilitySummary: String
        let distanceWayID: String?
        let endpointWayID: String?
    }

    private struct SimpleSequenceParticleState {
        let candidate: WayCandidate
        let continuity: ContinuityClass
        let cumulativeCost: Double
        let emissionCost: Double
        let transitionCost: Double
        let seedWayID: String?
        let seedSource: String
    }

    private struct SimpleSequenceParticleSelection {
        let selected: WayCandidate?
        let traceRankedCandidates: [TraceRankedCandidate]
        let hypotheses: [WayMatchHypothesis]
        let selectionTrace: [MatchSelectionTrace]
    }

    private struct SimpleSequenceViterbiObservation {
        let lat: Double
        let lon: Double
        let headingDeg: Double?
        let speedKmh: Double?
        let horizontalAccuracyM: Double?
        let gpsSignalBars: Int?
        let headingForScoring: Double?
    }

    private struct SimpleSequenceViterbiLayer {
        let observation: SimpleSequenceViterbiObservation
        let candidates: [WayCandidate]
    }

    private struct SimpleSequenceViterbiState {
        let layerIndex: Int
        let stateIndex: Int
        let candidate: WayCandidate
        let continuity: ContinuityClass
        let cumulativeCost: Double
        let emissionCost: Double
        let transitionCost: Double
        let routeDistanceM: Double?
        let observedDistanceM: Double?
        let previousStateIndex: Int?
    }

    private struct SimpleSequenceViterbiSelection {
        let selected: WayCandidate?
        let traceRankedCandidates: [TraceRankedCandidate]
        let hypotheses: [WayMatchHypothesis]
        let selectionTrace: [MatchSelectionTrace]
    }

    private enum DriveMatchThreeWayGateModel {
        static let classNames: [String] = ["current", "lowest_distance", "lowest_endpoint"]

        static func probabilities(featureValues: [String: Double]) -> [Double] {
            if featureValues["cd_distance_advantage_m", default: 0.0] <= 0.031331026678 {
                if featureValues["current_low_endpoint", default: 0.0] <= 0.500000000000 {
                    if featureValues["endpoint_score", default: 0.0] <= 83.636764487926 {
                        if featureValues["current_distance_m", default: 0.0] <= 10.729136905329 {
                            return [0.786314873876, 0.000000000000, 0.213685126124]
                        } else {
                            return [0.115246098439, 0.000000000000, 0.884753901561]
                        }
                    } else {
                        return [1.000000000000, 0.000000000000, 0.000000000000]
                    }
                } else {
                    if featureValues["ce_distance_advantage_m", default: 0.0] <= -5.659849937512 {
                        return [1.000000000000, 0.000000000000, 0.000000000000]
                    } else {
                        if featureValues["speed_kmh", default: 0.0] <= 79.173000000000 {
                            return [0.003416126966, 0.000000000000, 0.996583873034]
                        } else {
                            return [0.000000000000, 0.218181818182, 0.781818181818]
                        }
                    }
                }
            } else {
                if featureValues["speed_kmh", default: 0.0] <= 90.562800000000 {
                    if featureValues["cd_endpoint_advantage_m", default: 0.0] <= 5.937269380776 {
                        if featureValues["current_endpoint_m", default: 0.0] <= 43.319029628448 {
                            return [0.001474900959, 0.998525099041, 0.000000000000]
                        } else {
                            return [0.148960739030, 0.851039260970, 0.000000000000]
                        }
                    } else {
                        if featureValues["current_distance_m", default: 0.0] <= 12.144174583370 {
                            return [1.000000000000, 0.000000000000, 0.000000000000]
                        } else {
                            return [0.225840336134, 0.774159663866, 0.000000000000]
                        }
                    }
                } else {
                    if featureValues["speed_kmh", default: 0.0] <= 98.526400000000 {
                        return [1.000000000000, 0.000000000000, 0.000000000000]
                    } else {
                        return [0.031537450723, 0.000000000000, 0.968462549277]
                    }
                }
            }
        }
    }


    private static let placeRank: [String: Int] = [
        "city": 0,
        "town": 1,
        "village": 2,
        "hamlet": 3,
    ]
    private static let cityBoundaryLevelPriority: [Int: Int] = [
        9: 0,
        8: 1,
        6: 2,
    ]
    private static let primaryPlaceMaxRank = 1
    private static let nearestPlaceFallbackMaxDistanceM: Double = 5_000
    private static let headingWeightMPerDeg: Double = 1.8
    private static let headingMinSpeedKmh: Double = 8.0
    private static let headingMaxAccuracyDeg: Double = 45.0
    private static let simpleSameRefHoldSpeedThresholdKmh: Double = 30.0
    private static let simpleSameRefUrbanReleaseMaxSpeedKmh: Double = 34.0
    private static let simpleSameRefUrbanReleaseMaxAccuracyM: Double = 10.0
    private static let simpleSameRefUrbanReleaseMaxBestDistanceM: Double = 2.5
    private static let simpleSameRefUrbanReleaseMinDistanceGapM: Double = 25.0
    private static let simpleSameRefUrbanReleaseRequiredStreak = 2
    private static let simpleSpeedRefNarrowWindowRadiusM: Double = 10.0
    private static let simpleStreetNameFallbackMinNoRefMatches = 2
    private static let simpleLowSpeedJunctionBestDistanceSlackM: Double = 3.0
    private static let simpleLowSpeedJunctionCurrentDistanceSlackM: Double = 4.0
    private static let simpleLowSpeedJunctionMaxCandidateMismatchDeg: Double = 35.0
    private static let simpleLowSpeedNodeAwareJunctionMaxCandidateMismatchDeg: Double = 40.0
    private static let simpleLowSpeedJunctionMinCurrentMismatchDeg: Double = 40.0
    private static let simpleLowSpeedJunctionSharedNodeToleranceM: Double = 16.0
    private static let simpleSequenceParticleMotionHeadingWeightMPerDeg: Double = 1.4
    private static let simpleSequenceParticleHistoryDecay: Double = 0.65
    private static let simpleSequenceParticleAdoptionSlackM: Double = 4.0
    private static let simpleSequenceParticleSharedNodeTurnPenaltyM: Double = 1.0
    private static let simpleSequenceViterbiWindowFixCount = 10
    private static let simpleSequenceViterbiBeamWidth = 6
    private static let simpleSequenceViterbiCandidateCount = 6
    private static let simpleSequenceViterbiLocalGraphMarginM: Double = 120.0
    private static let simpleSequenceViterbiObservationSigmaFloorM: Double = 4.0
    private static let simpleSequenceViterbiObservationSigmaCapM: Double = 25.0
    private static let simpleSequenceViterbiHeadingSigmaDeg: Double = 35.0
    private static let simpleSequenceViterbiTransitionBetaFloorM: Double = 12.0
    private static let simpleSequenceViterbiTransitionBetaScale: Double = 0.5
    private static let simpleSequenceViterbiTransitionBetaBiasM: Double = 10.0
    private static let simpleSequenceViterbiUnreachableTransitionPenalty: Double = 14.0
    private static let simpleSequenceViterbiLayerGapPenalty: Double = 2.0
    private static let simpleSequenceViterbiRouteRelationContinuityBonus: Double = 1.1
    private static let simpleSequenceViterbiSameStreetContinuityBonus: Double = 0.55
    private static let walkingTurnSwitchMaxSpeedKmh: Double = 7.0
    private static let walkingTurnSwitchPreferredDistanceM: Double = 10.0
    private static let walkingTurnSwitchBestDistanceM: Double = 5.0
    private static let walkingTurnSwitchMinGapM: Double = 8.0
    private static let walkingTurnSwitchEndpointM: Double = 4.0
    private static let preferredWayScoreSlackM: Double = 18.0
    private static let preferredWayDistanceMultiplier: Double = 1.9
    private static let preferredWayDistanceFloorM: Double = 85.0
    private static let sameRefScoreSlackM: Double = 11.0
    private static let sameRefDistanceMultiplier: Double = 1.55
    private static let sameRefDistanceFloorM: Double = 72.0
    private static let sameRefBouncePenaltyM: Double = 9.0
    private static let sameRefBounceMinScoreImprovementM: Double = 14.0
    private static let sameRefBounceMinDistanceImprovementM: Double = 8.0
    private static let recentWayScoreSlackM: Double = 6.0
    private static let recentWayDistanceMultiplier: Double = 1.35
    private static let recentWayDistanceFloorM: Double = 55.0
    private static let linkedWayScoreSlackM: Double = 8.0
    private static let linkedWayDistanceMultiplier: Double = 1.45
    private static let linkedWayDistanceFloorM: Double = 64.0
    private static let segmentTransitionEndpointThresholdM: Double = 12.0
    private static let segmentTransitionDistanceSlackM: Double = 12.0
    private static let transitionHeadingCurrentAlignmentThresholdDeg: Double = 18.0
    private static let transitionHeadingImprovementMarginDeg: Double = 12.0
    private static let transitionHeadingMeaningfulTurnDeg: Double = 18.0
    private static let transitionHeadingSharpTurnDeg: Double = 35.0
    private static let transitionHeadingVerySharpTurnDeg: Double = 55.0
    private static let transitionModerateSpeedKmh: Double = 32.0
    private static let transitionHighSpeedKmh: Double = 48.0
    private static let transitionServiceRoadSpeedKmh: Double = 24.0
    private static let transitionHeadingBonusM: Double = 4.0
    private static let transitionSharpTurnPenaltyM: Double = 10.0
    private static let transitionVerySharpTurnPenaltyM: Double = 16.0

    private static func primaryPlaceCandidates(
        from candidates: [(rank: Int, distanceM: Double, name: String)]
    ) -> [(rank: Int, distanceM: Double, name: String)] {
        candidates.filter { $0.rank <= primaryPlaceMaxRank }
    }

    private static func selectContainingPlace(
        from candidates: [(rank: Int, distanceM: Double, name: String)]
    ) -> (rank: Int, distanceM: Double, name: String)? {
        let primary = primaryPlaceCandidates(from: candidates)
        let effective = primary.isEmpty ? candidates : primary
        return effective.sorted(by: {
            if $0.rank != $1.rank { return $0.rank < $1.rank }
            if $0.distanceM != $1.distanceM { return $0.distanceM < $1.distanceM }
            return $0.name < $1.name
        }).first
    }

    private static func selectNearestPlaceFallback(
        from candidates: [(rank: Int, distanceM: Double, name: String)]
    ) -> (rank: Int, distanceM: Double, name: String)? {
        let withinThreshold = candidates.filter { $0.distanceM <= nearestPlaceFallbackMaxDistanceM }
        guard !withinThreshold.isEmpty else {
            return nil
        }
        let primary = primaryPlaceCandidates(from: withinThreshold)
        if !primary.isEmpty {
            return primary.sorted(by: {
                if $0.distanceM != $1.distanceM { return $0.distanceM < $1.distanceM }
                if $0.rank != $1.rank { return $0.rank < $1.rank }
                return $0.name < $1.name
            }).first
        }
        return withinThreshold.sorted(by: {
            if $0.rank != $1.rank { return $0.rank < $1.rank }
            if $0.distanceM != $1.distanceM { return $0.distanceM < $1.distanceM }
            return $0.name < $1.name
        }).first
    }

    private static func selectAdminBoundaryName(
        from boundaries: [(adminLevel: Int, bboxArea: Double, name: String)],
        adminLevel: Int
    ) -> String? {
        boundaries
            .filter { $0.adminLevel == adminLevel }
            .sorted(by: {
                if $0.bboxArea != $1.bboxArea { return $0.bboxArea < $1.bboxArea }
                return $0.name < $1.name
            })
            .first?.name
    }

    private static func buildAdminCityDisplay(
        from boundaries: [(adminLevel: Int, bboxArea: Double, name: String)]
    ) -> (cityName: String?, cityPlaceName: String?, cityDistrictName: String?) {
        let districtName = selectAdminBoundaryName(from: boundaries, adminLevel: 6)
        let adminLevel8Name = selectAdminBoundaryName(from: boundaries, adminLevel: 8)
        let adminLevel9Name = selectAdminBoundaryName(from: boundaries, adminLevel: 9)
        let placeName: String?
        if let adminLevel9Name {
            if let adminLevel8Name, !sameAdminName(adminLevel8Name, adminLevel9Name) {
                placeName = "\(adminLevel8Name) - \(adminLevel9Name)"
            } else {
                placeName = adminLevel9Name
            }
        } else if let adminLevel8Name {
            placeName = adminLevel8Name
        } else {
            placeName = districtName
        }
        guard let placeName else {
            return (cityName: nil, cityPlaceName: nil, cityDistrictName: nil)
        }
        let districtLine = districtName.flatMap { sameAdminName(placeName, $0) ? nil : $0 }
        let cityName = districtLine.map { "\(placeName) (\($0))" } ?? placeName
        return (cityName: cityName, cityPlaceName: placeName, cityDistrictName: districtLine)
    }

    private static func formatAdminCityName(
        from boundaries: [(adminLevel: Int, bboxArea: Double, name: String)]
    ) -> String? {
        buildAdminCityDisplay(from: boundaries).cityName
    }

    private static func sameAdminName(_ lhs: String, _ rhs: String) -> Bool {
        lhs.trimmingCharacters(in: .whitespacesAndNewlines)
            .caseInsensitiveCompare(rhs.trimmingCharacters(in: .whitespacesAndNewlines)) == .orderedSame
    }

    private static func isClosedAreaRing(_ points: [(Double, Double)]) -> Bool {
        guard points.count >= 4,
              let first = points.first,
              let last = points.last else {
            return false
        }
        return abs(first.0 - last.0) <= 1e-9 && abs(first.1 - last.1) <= 1e-9
    }
    private static let tunnelPortalEntryEndpointThresholdM: Double = 24.0
    private static let tunnelPortalExitEndpointThresholdM: Double = 28.0
    private static let tunnelPortalScoreSlackM: Double = 12.0
    private static let tunnelPortalDirectSnapMotionMinScore: Double = 0.2
    private static let tunnelPortalCommitSlackBonusM: Double = 18.0
    private static let tunnelApproachMinFixCount = 2
    private static let tunnelApproachAccuracyDeltaM: Double = 8.0
    private static let tunnelApproachSignalDropBars = 1
    private static let tunnelCorridorEntryDepthM: Double = 42.0
    private static let tunnelCorridorExitRemainingM: Double = 42.0
    private static let tunnelCorridorEntryMinDepthM: Double = 12.0
    private static let tunnelCorridorEntryFixCount = 2
    private static let tunnelCorridorEntryProgressNodes = 1
    private static let tunnelCorridorExitRemainingNodes = 1
    private static let corridorStateIllegalPenaltyM: Double = 80.0
    private static let corridorStateExpectedTransitionPenaltyM: Double = 2.0
    private static let corridorStatePersistencePenaltyM: Double = 0.5
    private static let corridorStateReentryPenaltyM: Double = 8.0
    private static let corridorStateTunnelSignalRewardM: Double = 8.0
    private static let corridorStateTunnelPersistenceRewardM: Double = 6.0
    private static let corridorStateTunnelChainRewardM: Double = 10.0
    private static let corridorStateMotorwayRewardM: Double = 4.0
    private static let corridorStateTunnelDirectCommitMinScore: Double = 0.75
    private static let corridorStateTunnelOutputMinScore: Double = 0.5
    private static let corridorStateTunnelChainCommitMinScore: Double = 0.7
    private static let corridorStateTunnelChainSlackBonusM: Double = 6.0
    private static let corridorStateTunnelOutputScoreSlackM: Double = 8.0
    private static let corridorStateMotorwayOutputScoreSlackM: Double = 6.0
    private static let motorwayTransitionEndpointThresholdM: Double = 36.0
    private static let motorwayCorridorEntryDepthM: Double = 150.0
    private static let motorwayCorridorExitRemainingM: Double = 160.0
    private static let motorwayCorridorEntryMinDepthM: Double = 30.0
    private static let motorwayCorridorEntryFixCount = 2
    private static let motorwayCorridorEntryProgressNodes = 1
    private static let motorwayCorridorExitRemainingNodes = 1
    private static let tunnelCorridorEntryProgressM: Double = 16.0
    private static let motorwayCorridorEntryProgressM: Double = 42.0
    private static let corridorProgressNoiseToleranceM: Double = 12.0
    private static let corridorProgressMinAdvanceM: Double = 4.0
    private static let connectedTransitionWarmupFixCount = 3
    private static let baselinePreferredDistanceSlackM: Double = 7.0
    private static let baselineSameRefDistanceSlackM: Double = 5.0
    private static let baselineTurnTransitionMaxSpeedKmh: Double = 36.0
    private static let baselineTurnDistanceSlackM: Double = 10.0
    private static let baselineTunnelExitEndpointThresholdM: Double = 28.0
    private static let baselineMotorwayGateEndpointThresholdM: Double = 42.0
    private static let maxTraceCandidateCount = 16
    private static let miniHMMBeamWidth = 4
    private static let miniHMMAmbiguousScoreGapM: Double = 14.0
    private static let miniHMMHistoryDecay: Double = 0.55
    private static let miniHMMUnrelatedTransitionPenaltyM: Double = 18.0
    private static let miniHMMLinkedWayTransitionPenaltyM: Double = 2.5
    private static let miniHMMSharedRefLinkedTransitionPenaltyM: Double = 0.75
    private static let miniHMMSameRefTransitionPenaltyM: Double = 4.0
    private static let miniHMMRecentWayTransitionPenaltyM: Double = 8.0
    private static let miniHMMHighwayClassTransitionPenaltyM: Double = 12.0
    private static let miniHMMEndpointConnectionPenaltyM: Double = 2.0
    private static let miniHMMEndpointConnectionThresholdM: Double = 20.0
    private static let miniHMMEndpointCandidateThresholdM: Double = 24.0
    private static let inCityHighwayClasses: Set<String> = [
        "residential",
        "service",
        "crossing",
        "living_street",
    ]

    init(
        dbPath: String,
        countryCode: String? = nil,
        matchingModel: MatchingModel = .corridorHMM
    ) {
        self.dbPath = dbPath
        self.countryCode = Self.normalizedCountryCode(countryCode) ?? Self.inferCountryCode(fromDBPath: dbPath)
        self.matchingModel = matchingModel
    }

    func lookupSpeedLimit(
        lat: Double,
        lon: Double,
        radiusM: Double = 50.0,
        maxCandidates: Int = 256,
        matchContext: WayMatchContext? = nil,
        preferredWayID: String? = nil,
        headingDeg: Double? = nil,
        headingAccuracyDeg: Double? = nil,
        speedKmh: Double? = nil,
        horizontalAccuracyM: Double? = nil,
        gpsSignalBars: Int? = nil
    ) throws -> SpeedLimitResult {
        let t0 = DispatchTime.now().uptimeNanoseconds

        var db: OpaquePointer?
        let encodedPath = dbPath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbPath
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for \(dbPath)")
        }
        defer { sqlite3_close(db) }

        let resolvedHeading = normalizedHeadingDegrees(headingDeg)
        let headingForScoring = shouldUseHeading(
            headingDeg: resolvedHeading,
            headingAccuracyDeg: headingAccuracyDeg,
            speedKmh: speedKmh
        ) ? resolvedHeading : nil
        let normalizedMatchContext = normalizedMatchContext(
            from: matchContext,
            fallbackPreferredWayID: preferredWayID,
            ageOutStaleRefContinuity: matchingModel == .simpleSpeedRefStreetNameGuardHeuristic
                || matchingModel == .simpleSpeedRefStreetNameGuardNodeAwareHeuristic
                || matchingModel == .simpleSequenceParticleHeuristic
                || matchingModel == .simpleSequenceViterbiHeuristic
        )
        let normalizedRadiusM = effectiveCandidateSearchRadiusM(radiusM: radiusM)
        let cappedCandidateRadiusM = candidateLookupRadiusM(radiusM: normalizedRadiusM, horizontalAccuracyM: horizontalAccuracyM)
        let cappedCandidateQuery = try loadCandidates(
            db: db,
            lat: lat,
            lon: lon,
            radiusM: cappedCandidateRadiusM,
            maxCandidates: maxCandidates,
            headingForScoring: headingForScoring,
            matchContext: normalizedMatchContext
        )
        let fullCandidateQuery: CandidateQueryResult?
        if cappedCandidateRadiusM < normalizedRadiusM {
            fullCandidateQuery = try loadCandidates(
                db: db,
                lat: lat,
                lon: lon,
                radiusM: normalizedRadiusM,
                maxCandidates: maxCandidates,
                headingForScoring: headingForScoring,
                matchContext: normalizedMatchContext
            )
        } else {
            fullCandidateQuery = nil
        }
        let candidateQuery = mergeCandidateQueries(
            capped: cappedCandidateQuery,
            full: fullCandidateQuery,
            matchContext: normalizedMatchContext,
            db: db
        )
        let candidateQueryMode: String
        if fullCandidateQuery == nil {
            candidateQueryMode = "full"
        } else if cappedCandidateQuery.candidates.isEmpty {
            candidateQueryMode = "full_fallback"
        } else if candidateQuery.candidateCount > cappedCandidateQuery.candidateCount {
            candidateQueryMode = "capped_plus_continuity"
        } else {
            candidateQueryMode = "capped"
        }

        var bestCandidate: WayCandidate?
        var preferredCandidate: WayCandidate?
        var sameRefCandidate: WayCandidate?
        var sameRefTransitionCandidate: WayCandidate?
        var linkedWayCandidate: WayCandidate?
        var recentWayCandidate: WayCandidate?
        let rankedCandidates = candidateQuery.candidates
        let candidateCount = candidateQuery.candidateCount
        let speedCandidateCount = candidateQuery.speedCandidateCount
        let nearestCandidateDistance = candidateQuery.nearestCandidateDistance
        let nearestSpeedCandidateDistance = candidateQuery.nearestSpeedCandidateDistance
        let nearbyTunnelCandidateWayIDs = candidateQuery.nearbyTunnelCandidateWayIDs
        let nearbyTunnelCandidateRefs = candidateQuery.nearbyTunnelCandidateRefs
        let wayLinksContext = loadWayLinksContext(
            db: db,
            candidates: rankedCandidates,
            matchContext: normalizedMatchContext
        )
        let corridorProgressContext: CorridorProgressContext
        let corridorPairContext: CorridorPairContext
        if usesCorridorMatcher {
            corridorProgressContext = loadCorridorProgressContext(
                db: db,
                candidates: rankedCandidates
            )
            corridorPairContext = loadCorridorPairContext(db: db)
        } else {
            corridorProgressContext = CorridorProgressContext(available: false, byWayID: [:])
            corridorPairContext = CorridorPairContext(available: false, byMainKey: [:], byPairedKey: [:])
        }
        let accuracyBuffer = scaledAccuracyBufferM(horizontalAccuracyM)
        let activeCorridorAnchorState = corridorAnchor(from: normalizedMatchContext)?.state ?? .surface
        let activeCorridorLabel = normalizedMatchContext.activeCorridorState.map {
            "\($0.kind)#\($0.corridorID)"
        } ?? activeCorridorAnchorState.rawValue
        var selectionTrace: [MatchSelectionTrace] = [
            MatchSelectionTrace(
                step: "context",
                detail: "preferred=\(normalizedMatchContext.preferredWayID ?? "nil") corridor=\(activeCorridorLabel) tunnel_mode=\(normalizedMatchContext.isInTunnelMode) gps_loss=\(normalizedMatchContext.hadRecentGPSSignalLoss) tunnel_approach=\(normalizedMatchContext.tunnelApproachFixCount) corridor_approach=\(normalizedMatchContext.approachCorridorFixCount) match_streak=\(normalizedMatchContext.matchedFixCount) candidate_radius_m=\(String(format: "%.1f", candidateQuery.queryRadiusM)) hacc_cap_m=\(String(format: "%.1f", cappedCandidateRadiusM)) candidate_query_mode=\(candidateQueryMode) accuracy_m=\(String(format: "%.1f", accuracyBuffer))"
            )
        ]
        let selectableCandidates: [WayCandidate]
        if usesCorridorMatcher {
            let corridorBaseCandidates = rankedCandidates.filter {
                isCorridorCandidateSelectable(
                    $0,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext,
                    progressContext: corridorProgressContext,
                    pairContext: corridorPairContext,
                    accuracyBufferM: accuracyBuffer,
                    horizontalAccuracyM: horizontalAccuracyM,
                    gpsSignalBars: gpsSignalBars
                )
            }
            let corridorSelectableCandidates = suppressAmbiguousSurfaceToTunnelEntries(
                in: corridorBaseCandidates,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext,
                accuracyBufferM: accuracyBuffer,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
            )
            if !corridorSelectableCandidates.isEmpty {
                selectableCandidates = corridorSelectableCandidates
                if corridorSelectableCandidates.count != rankedCandidates.count {
                    let filteredCount = rankedCandidates.count - corridorSelectableCandidates.count
                    selectionTrace.append(
                        MatchSelectionTrace(
                            step: "corridor_gate",
                            detail: "filtered \(filteredCount) candidates incompatible with corridor state \(activeCorridorLabel)"
                        )
                    )
                }
            } else if shouldFallbackWhenCorridorGateEmptiesCandidates(matchContext: normalizedMatchContext) {
                selectableCandidates = rankedCandidates
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "corridor_gate",
                        detail: "kept full candidate set after empty corridor gate during recent gps loss"
                    )
                )
            } else {
                selectableCandidates = corridorSelectableCandidates
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "corridor_gate",
                        detail: "rejected all candidates for corridor state \(activeCorridorLabel)"
                    )
                )
            }
        } else {
            selectableCandidates = rankedCandidates
        }
        let nearestAlternativeDistanceCandidate = selectableCandidates
            .filter { normalizedWayID($0.wayID) != normalizedWayID(normalizedMatchContext.preferredWayID) }
            .min { lhs, rhs in
                isBetterDistanceCandidate(lhs, than: rhs)
            }
        let graphSelectableCandidates: [WayCandidate]
        if shouldApplyConnectedTransitionGate(
            matchContext: normalizedMatchContext,
            wayLinks: wayLinksContext
        ) {
            let connectedCandidates = selectableCandidates.filter {
                isConnectedTransitionCandidate(
                    $0,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext
                )
            }
            if !connectedCandidates.isEmpty {
                graphSelectableCandidates = connectedCandidates
                if connectedCandidates.count != selectableCandidates.count {
                    selectionTrace.append(
                        MatchSelectionTrace(
                            step: "road_graph_gate",
                            detail: "filtered \(selectableCandidates.count - connectedCandidates.count) disconnected candidates after warmup"
                        )
                    )
                }
            } else {
                graphSelectableCandidates = selectableCandidates
            }
        } else {
            graphSelectableCandidates = selectableCandidates
        }
        bestCandidate = graphSelectableCandidates.first

        func buildNonCorridorMatcherResult(
            finalSelected: WayCandidate?,
            traceRankedCandidates: [TraceRankedCandidate],
            selectionTrace: [MatchSelectionTrace],
            matchHypotheses: [WayMatchHypothesis] = []
        ) -> SpeedLimitResult {
            var directionalHypotheses = matchHypotheses
            if directionalHypotheses.isEmpty {
                directionalHypotheses = traceRankedCandidates
                    .prefix(Self.miniHMMBeamWidth)
                    .compactMap { entry in
                        wayMatchHypothesis(
                            from: entry.candidate,
                            cumulativeCost: entry.traceScore,
                            emissionScore: entry.candidate.score
                        )
                    }
            }
            if let finalSelected,
               let selectedWayID = normalizedWayID(finalSelected.wayID),
               !directionalHypotheses.contains(where: { $0.wayID == selectedWayID }),
               let selectedHypothesis = wayMatchHypothesis(
                   from: finalSelected,
                   cumulativeCost: finalSelected.score,
                   emissionScore: finalSelected.score
               ) {
                directionalHypotheses.insert(selectedHypothesis, at: 0)
                if directionalHypotheses.count > Self.miniHMMBeamWidth {
                    directionalHypotheses.removeLast(
                        directionalHypotheses.count - Self.miniHMMBeamWidth
                    )
                }
            }
            let cityContext = resolveCityContext(db: db, lat: lat, lon: lon)
            let insideCityDecision: (insideCity: Bool?, source: String?)
            let residentialContext: ResidentialContext
            if highwayImpliesInsideCity(finalSelected?.highway) {
                insideCityDecision = (true, "highway_class_in_city")
                residentialContext = ResidentialContext(
                    insideCity: nil,
                    candidatePolygons: 0,
                    containingPolygons: 0,
                    resolveMs: 0.0
                )
            } else {
                residentialContext = resolveResidentialContext(db: db, lat: lat, lon: lon)
                if let insideCity = residentialContext.insideCity {
                    insideCityDecision = (insideCity, "residential_polygon")
                } else {
                    insideCityDecision = (cityContext.insideCity, cityContext.citySource)
                }
            }

            let t1 = DispatchTime.now().uptimeNanoseconds
            let elapsedMs = Double(t1 - t0) / 1_000_000.0
            let effectiveSpeed: Int?
            if finalSelected?.isUnlimitedSpeedLimit == true {
                effectiveSpeed = nil
            } else if let finalSelected, let matchedSpeed = finalSelected.speedKmh {
                if finalSelected.speedSource == .highwayClass,
                   Self.allowsResidentialAreaFallback(highway: finalSelected.highway),
                   let insideCity = insideCityDecision.insideCity {
                    effectiveSpeed = insideCity ? 50 : 100
                } else {
                    effectiveSpeed = matchedSpeed
                }
            } else if let finalSelected,
                      Self.allowsResidentialAreaFallback(highway: finalSelected.highway),
                      let insideCity = insideCityDecision.insideCity {
                effectiveSpeed = insideCity ? 50 : 100
            } else if insideCityDecision.insideCity == true {
                effectiveSpeed = 50
            } else {
                effectiveSpeed = nil
            }
            let resolvedInsideCityDecision = applyGermanLowSpeedInCityHeuristic(
                insideCityDecision: insideCityDecision,
                speedKmh: effectiveSpeed
            )
            let selectedRouteContinuity = loadSelectedRouteContinuity(
                db: db,
                wayID: finalSelected?.wayID
            )

            let candidateTraces = Array(traceRankedCandidates.prefix(Self.maxTraceCandidateCount)).map { entry in
                MatchCandidateTrace(
                    rank: entry.traceRank,
                    wayID: entry.candidate.wayID,
                    streetName: entry.candidate.streetName,
                    streetRef: entry.candidate.streetRef,
                    highway: entry.candidate.highway,
                    service: entry.candidate.service,
                    tunnel: entry.candidate.tunnel,
                    distanceM: entry.candidate.distanceM,
                    endpointProximityM: entry.candidate.endpointProximityM.isFinite ? entry.candidate.endpointProximityM : nil,
                    score: entry.traceScore,
                    geometryScore: entry.candidate.distanceM,
                    portalEligible: nil,
                    corridorKind: nil,
                    corridorID: nil,
                    corridorSideNodeKey: nil,
                    corridorDepthM: nil,
                    corridorRemainingM: nil,
                    corridorDepthNodes: nil,
                    corridorRemainingNodes: nil,
                    corridorEntryZone: nil,
                    corridorExitZone: nil,
                    continuityClass: String(describing: entry.continuity),
                    tunnelSelectable: true,
                    corridorSelectable: true,
                    isSelected: normalizedWayID(entry.candidate.wayID) == normalizedWayID(finalSelected?.wayID)
                )
            }

            return SpeedLimitResult(
                speedLimitKmh: effectiveSpeed,
                isUnlimitedSpeedLimit: finalSelected?.isUnlimitedSpeedLimit == true ? true : nil,
                wayID: finalSelected?.wayID,
                highway: finalSelected?.highway,
                service: finalSelected?.service,
                tunnel: finalSelected?.tunnel,
                bridge: nil,
                covered: nil,
                location: nil,
                layer: nil,
                level: nil,
                isTunnelSegment: isTruthyOSMTag(finalSelected?.tunnel),
                streetName: finalSelected?.streetName,
                streetBaseName: finalSelected?.streetBaseName,
                streetRef: finalSelected?.streetRef,
                matchedEndpointProximityM: finalSelected?.endpointProximityM.isFinite == true ? finalSelected?.endpointProximityM : nil,
                cityName: cityContext.cityName,
                cityPlaceName: cityContext.cityPlaceName,
                cityDistrictName: cityContext.cityDistrictName,
                insideCity: resolvedInsideCityDecision.insideCity,
                citySource: resolvedInsideCityDecision.source ?? cityContext.citySource,
                cityResolveMs: cityContext.resolveMs + residentialContext.resolveMs,
                cityCandidateBoundaries: cityContext.candidateBoundaries,
                cityContainingBoundaries: cityContext.containingBoundaries,
                cityPlaceCandidates: cityContext.placeCandidates,
                queryTimeMs: elapsedMs,
                candidateCount: candidateCount,
                speedCandidateCount: speedCandidateCount,
                nearestCandidateDistanceM: nearestCandidateDistance.isFinite ? nearestCandidateDistance : nil,
                nearestSpeedCandidateDistanceM: nearestSpeedCandidateDistance.isFinite ? nearestSpeedCandidateDistance : nil,
                nearbyTunnelCandidateWayIDs: nearbyTunnelCandidateWayIDs,
                nearbyTunnelCandidateRefs: Array(nearbyTunnelCandidateRefs).sorted(),
                usedMiniHMM: false,
                miniHMMCandidateCount: 0,
                matchHypotheses: directionalHypotheses,
                candidateTraces: candidateTraces,
                selectionTrace: selectionTrace,
                activeCorridorState: nil,
                routeContinuityAvailable: selectedRouteContinuity.available,
                routeRelationMemberships: selectedRouteContinuity.memberships
            )
        }

        if matchingModel == .connectedBaseline {
            let baselineSelection = selectConnectedBaselineCandidate(
                from: graphSelectableCandidates,
                matchContext: normalizedMatchContext,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh,
                wayLinks: wayLinksContext,
                accuracyBufferM: accuracyBuffer
            )
            selectionTrace.append(contentsOf: baselineSelection.selectionTrace)
            let finalSelected = baselineSelection.selected
            if let finalSelected {
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "final",
                        detail: "selected \(finalSelected.wayID ?? "nil") tunnel=\(isTruthyOSMTag(finalSelected.tunnel)) corridor=none"
                    )
                )
            }
            return buildNonCorridorMatcherResult(
                finalSelected: finalSelected,
                traceRankedCandidates: baselineSelection.traceRankedCandidates,
                selectionTrace: selectionTrace
            )
        }

        if matchingModel == .simpleSequenceParticleHeuristic {
            let heuristicSelection = selectSimpleSpeedRefHeuristicCandidate(
                from: rankedCandidates,
                matchContext: normalizedMatchContext,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh,
                accuracyBufferM: accuracyBuffer,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars,
                urbanSameRefReleaseEnabled: true,
                useStreetNameFallbackContinuity: false,
                useGuardedStreetNameFallbackContinuity: true,
                nodeDirectionAwareLowSpeedJunctionRelease: true,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext,
                pairContext: corridorPairContext
            )
            selectionTrace.append(contentsOf: heuristicSelection.selectionTrace)
            let particleSelection = selectSimpleSequenceParticleCandidate(
                from: rankedCandidates,
                heuristicSelected: heuristicSelection.selected,
                matchContext: normalizedMatchContext,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh
            )
            selectionTrace.append(contentsOf: particleSelection.selectionTrace)
            let finalSelected = particleSelection.selected ?? heuristicSelection.selected
            if let finalSelected {
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "final",
                        detail: "selected \(finalSelected.wayID ?? "nil") tunnel=\(isTruthyOSMTag(finalSelected.tunnel)) corridor=none model=simple_sequence_particle"
                    )
                )
            }
            return buildNonCorridorMatcherResult(
                finalSelected: finalSelected,
                traceRankedCandidates: particleSelection.traceRankedCandidates.isEmpty
                    ? heuristicSelection.traceRankedCandidates
                    : particleSelection.traceRankedCandidates,
                selectionTrace: selectionTrace,
                matchHypotheses: particleSelection.hypotheses
            )
        }

        if matchingModel == .simpleSequenceViterbiHeuristic {
            let viterbiSelection = selectSimpleSequenceViterbiCandidate(
                db: db,
                currentCandidates: rankedCandidates,
                matchContext: normalizedMatchContext,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars,
                searchRadiusM: normalizedRadiusM,
                maxCandidates: maxCandidates,
                wayLinks: wayLinksContext
            )
            selectionTrace.append(contentsOf: viterbiSelection.selectionTrace)
            let finalSelected = viterbiSelection.selected
            if let finalSelected {
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "final",
                        detail: "selected \(finalSelected.wayID ?? "nil") tunnel=\(isTruthyOSMTag(finalSelected.tunnel)) corridor=none model=simple_sequence_viterbi"
                    )
                )
            }
            return buildNonCorridorMatcherResult(
                finalSelected: finalSelected,
                traceRankedCandidates: viterbiSelection.traceRankedCandidates,
                selectionTrace: selectionTrace,
                matchHypotheses: viterbiSelection.hypotheses
            )
        }

        if matchingModel == .simpleSpeedRefHeuristic ||
            matchingModel == .simpleSpeedRefUrbanReleaseHeuristic ||
            matchingModel == .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic ||
            matchingModel == .simpleSpeedRefStreetNameFallbackHeuristic ||
            matchingModel == .simpleSpeedRefStreetNameGuardHeuristic ||
            matchingModel == .simpleSpeedRefStreetNameGuardNodeAwareHeuristic ||
            matchingModel == .simpleSpeedRefConnectedHeuristic {
            let simpleCandidates =
                matchingModel == .simpleSpeedRefConnectedHeuristic ? graphSelectableCandidates : rankedCandidates
            let simpleSelection = selectSimpleSpeedRefHeuristicCandidate(
                from: simpleCandidates,
                matchContext: normalizedMatchContext,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh,
                accuracyBufferM: accuracyBuffer,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars,
                urbanSameRefReleaseEnabled: matchingModel == .simpleSpeedRefUrbanReleaseHeuristic ||
                    matchingModel == .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic ||
                    matchingModel == .simpleSpeedRefStreetNameFallbackHeuristic ||
                    matchingModel == .simpleSpeedRefStreetNameGuardHeuristic ||
                    matchingModel == .simpleSpeedRefStreetNameGuardNodeAwareHeuristic,
                useStreetNameFallbackContinuity: matchingModel == .simpleSpeedRefStreetNameFallbackHeuristic,
                useGuardedStreetNameFallbackContinuity: matchingModel == .simpleSpeedRefStreetNameGuardHeuristic ||
                    matchingModel == .simpleSpeedRefStreetNameGuardNodeAwareHeuristic,
                nodeDirectionAwareLowSpeedJunctionRelease: matchingModel == .simpleSpeedRefStreetNameGuardNodeAwareHeuristic,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext,
                pairContext: corridorPairContext
            )
            selectionTrace.append(contentsOf: simpleSelection.selectionTrace)
            let finalSelected = simpleSelection.selected
            if let finalSelected {
                let modelName: String
                switch matchingModel {
                case .simpleSpeedRefConnectedHeuristic:
                    modelName = "simple_speed_ref_connected"
                case .simpleSpeedRefStreetNameGuardHeuristic:
                    modelName = "simple_speed_ref_street_name_guard"
                case .simpleSpeedRefStreetNameGuardNodeAwareHeuristic:
                    modelName = "simple_speed_ref_street_name_guard_node_aware"
                case .simpleSpeedRefStreetNameFallbackHeuristic:
                    modelName = "simple_speed_ref_street_name_fallback"
                case .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic:
                    modelName = "simple_speed_ref_urban_release_10m"
                case .simpleSpeedRefUrbanReleaseHeuristic:
                    modelName = "simple_speed_ref_urban_release"
                default:
                    modelName = "simple_speed_ref"
                }
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "final",
                        detail: "selected \(finalSelected.wayID ?? "nil") tunnel=\(isTruthyOSMTag(finalSelected.tunnel)) corridor=none model=\(modelName)"
                    )
                )
            }
            return buildNonCorridorMatcherResult(
                finalSelected: finalSelected,
                traceRankedCandidates: simpleSelection.traceRankedCandidates,
                selectionTrace: selectionTrace
            )
        }

        for candidate in graphSelectableCandidates {
            switch continuityClass(
                for: candidate,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext
            ) {
            case .preferredWay:
                if let existingPreferred = preferredCandidate {
                    if isBetterCandidate(candidate, than: existingPreferred) {
                        preferredCandidate = candidate
                    }
                } else {
                    preferredCandidate = candidate
                }
            case .sameRef:
                if let existingSameRef = sameRefCandidate {
                    if isBetterCandidate(candidate, than: existingSameRef) {
                        sameRefCandidate = candidate
                    }
                } else {
                    sameRefCandidate = candidate
                }
                if normalizedWayID(candidate.wayID) != normalizedMatchContext.preferredWayID {
                    if let existingTransition = sameRefTransitionCandidate {
                        if isBetterCandidate(candidate, than: existingTransition) {
                            sameRefTransitionCandidate = candidate
                        }
                    } else {
                        sameRefTransitionCandidate = candidate
                    }
                }
            case .linkedWay:
                if let existingLinkedWay = linkedWayCandidate {
                    if isBetterCandidate(candidate, than: existingLinkedWay) {
                        linkedWayCandidate = candidate
                    }
                } else {
                    linkedWayCandidate = candidate
                }
            case .recentWay:
                if let existingRecentWay = recentWayCandidate {
                    if isBetterCandidate(candidate, than: existingRecentWay) {
                        recentWayCandidate = candidate
                    }
                } else {
                    recentWayCandidate = candidate
                }
            case .none:
                break
            }
        }
        let miniHMMSelection = selectMiniHMMCandidate(
            from: graphSelectableCandidates,
            matchContext: normalizedMatchContext,
            preferredCandidate: preferredCandidate,
            sameRefTransitionCandidate: sameRefTransitionCandidate,
            observedHeadingDeg: headingForScoring,
            speedKmh: speedKmh,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars,
            wayLinks: wayLinksContext,
            progressContext: corridorProgressContext,
            pairContext: corridorPairContext
        )
        let traceRankedCandidates = buildTraceRankedCandidates(
            from: rankedCandidates,
            matchContext: normalizedMatchContext,
            wayLinks: wayLinksContext,
            progressContext: corridorProgressContext,
            pairContext: corridorPairContext,
            accuracyBufferM: accuracyBuffer,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        )
        let traceTop2Margin = top2TraceMargin(traceRankedCandidates)
        let signalEvidence = signalQualityEvidence(
            matchContext: normalizedMatchContext,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        )

        let heuristicSelected: WayCandidate?
        var lockHeuristicSelection = false
        if let bestCandidate {
            if let preferredCandidate,
               shouldSuppressImmediateSameRefBounce(
                candidate: bestCandidate,
                over: preferredCandidate,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                accuracyBufferM: accuracyBuffer
               ) {
                heuristicSelected = preferredCandidate
            } else if let preferredCandidate,
               shouldPreferSameRefAlternative(
                overPreferred: preferredCandidate,
                alternativeCandidate: bestCandidate,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh,
                accuracyBufferM: accuracyBuffer,
                wayLinks: wayLinksContext,
                matchContext: normalizedMatchContext
               ) {
                heuristicSelected = bestCandidate
                lockHeuristicSelection = true
            } else if let preferredCandidate,
               let sameRefTransitionCandidate,
               shouldPromoteSameRefTransition(
                from: preferredCandidate,
                to: sameRefTransitionCandidate,
                observedHeadingDeg: headingForScoring,
                speedKmh: speedKmh,
                accuracyBufferM: accuracyBuffer,
                wayLinks: wayLinksContext,
                matchContext: normalizedMatchContext
               ) {
                heuristicSelected = sameRefTransitionCandidate
                lockHeuristicSelection = true
            } else if let preferredCandidate,
                      let linkedWayCandidate,
                      shouldPromoteLinkedTransition(
                        from: preferredCandidate,
                        to: linkedWayCandidate,
                        observedHeadingDeg: headingForScoring,
                        speedKmh: speedKmh,
                        accuracyBufferM: accuracyBuffer,
                        wayLinks: wayLinksContext
                      ) {
                heuristicSelected = linkedWayCandidate
                lockHeuristicSelection = true
            } else if let preferredCandidate,
                      let nearestAlternativeDistanceCandidate,
                      shouldForceGeometricCandidateAtWalkingSpeed(
                        preferredCandidate: preferredCandidate,
                        geometricCandidate: nearestAlternativeDistanceCandidate,
                        observedHeadingDeg: headingForScoring,
                        speedKmh: speedKmh,
                        accuracyBufferM: accuracyBuffer,
                        matchContext: normalizedMatchContext,
                        wayLinks: wayLinksContext
                      ) {
                heuristicSelected = nearestAlternativeDistanceCandidate
                lockHeuristicSelection = true
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "low_speed_rule",
                        detail: "selected geometric turn \(nearestAlternativeDistanceCandidate.wayID ?? "nil") over preferred \(preferredCandidate.wayID ?? "nil") at walking speed"
                    )
                )
            } else if let preferredCandidate,
               shouldKeepContinuityCandidate(
                preferredCandidate,
                over: bestCandidate,
                radiusM: radiusM,
                accuracyBufferM: accuracyBuffer,
                scoreSlackM: Self.preferredWayScoreSlackM,
                distanceMultiplier: Self.preferredWayDistanceMultiplier,
                distanceFloorM: Self.preferredWayDistanceFloorM
               ) {
                heuristicSelected = preferredCandidate
            } else if let sameRefCandidate,
                      shouldKeepContinuityCandidate(
                        sameRefCandidate,
                        over: bestCandidate,
                        radiusM: radiusM,
                        accuracyBufferM: accuracyBuffer,
                        scoreSlackM: Self.sameRefScoreSlackM,
                        distanceMultiplier: Self.sameRefDistanceMultiplier,
                        distanceFloorM: Self.sameRefDistanceFloorM
                      ) {
                heuristicSelected = sameRefCandidate
            } else if let linkedWayCandidate,
                      shouldKeepContinuityCandidate(
                        linkedWayCandidate,
                        over: bestCandidate,
                        radiusM: radiusM,
                        accuracyBufferM: accuracyBuffer,
                        scoreSlackM: Self.linkedWayScoreSlackM,
                        distanceMultiplier: Self.linkedWayDistanceMultiplier,
                        distanceFloorM: Self.linkedWayDistanceFloorM
                      ) {
                heuristicSelected = linkedWayCandidate
            } else if let recentWayCandidate,
                      shouldKeepContinuityCandidate(
                        recentWayCandidate,
                        over: bestCandidate,
                        radiusM: radiusM,
                        accuracyBufferM: accuracyBuffer,
                        scoreSlackM: Self.recentWayScoreSlackM,
                        distanceMultiplier: Self.recentWayDistanceMultiplier,
                        distanceFloorM: Self.recentWayDistanceFloorM
                      ) {
                heuristicSelected = recentWayCandidate
            } else {
                heuristicSelected = bestCandidate
            }
        } else {
            heuristicSelected = preferredCandidate ?? sameRefCandidate ?? recentWayCandidate
        }
        if let heuristicSelected {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "heuristic",
                    detail: "selected \(heuristicSelected.wayID ?? "nil") continuity=\(continuityClass(for: heuristicSelected, matchContext: normalizedMatchContext, wayLinks: wayLinksContext))"
                )
            )
        }
        let usedMiniHMM = !lockHeuristicSelection && miniHMMSelection.selectedCandidate != nil
        let baselineSelected: WayCandidate?
        if lockHeuristicSelection {
            baselineSelected = heuristicSelected
        } else if let selectedCorridorState = miniHMMSelection.selectedCorridorState,
                  let miniHMMSelected = miniHMMSelection.selectedCandidate,
                  let miniHMMCandidateCorridorState = candidateCorridorState(
                    for: miniHMMSelected,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext,
                    progressContext: corridorProgressContext
                  ),
                  shouldPromoteMiniHMMCorridorSelection(
                    state: selectedCorridorState,
                    candidate: miniHMMSelected,
                    candidateCorridorState: miniHMMCandidateCorridorState,
                    over: heuristicSelected,
                    matchContext: normalizedMatchContext,
                    signalEvidence: signalEvidence
                  ) {
            baselineSelected = miniHMMSelected
        } else if let selectedCorridorState = miniHMMSelection.selectedCorridorState,
                  let miniHMMSelected = miniHMMSelection.selectedCandidate,
                  let heuristicSelected,
                  shouldKeepSurfaceHeuristicOverUncommittedTunnelCandidate(
                    state: selectedCorridorState,
                    tunnelCandidate: miniHMMSelected,
                    heuristicCandidate: heuristicSelected
                  ) {
            baselineSelected = heuristicSelected
        } else if let heuristicSelected, let miniHMMSelected = miniHMMSelection.selectedCandidate {
            let heuristicContinuity = continuityClass(
                for: heuristicSelected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext
            )
            let miniHMMContinuity = continuityClass(
                for: miniHMMSelected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext
            )
            if continuityPriority(heuristicContinuity) > continuityPriority(miniHMMContinuity) {
                baselineSelected = heuristicSelected
            } else {
                baselineSelected = miniHMMSelected
            }
        } else if let miniHMMSelected = miniHMMSelection.selectedCandidate {
            baselineSelected = miniHMMSelected
        } else {
            baselineSelected = heuristicSelected
        }
        let shouldApplyThreeWayGate = usesThreeWayGate &&
            !lockHeuristicSelection &&
            (miniHMMSelection.selectedCorridorState == nil || miniHMMSelection.selectedCorridorState == .surface) &&
            shouldUseThreeWayGate(
            currentSelected: baselineSelected,
            matchContext: normalizedMatchContext
        )
        let threeWayGateSelection = shouldApplyThreeWayGate ? selectThreeWayGateCandidate(
            from: traceRankedCandidates,
            currentSelected: baselineSelected,
            miniHMMSelected: miniHMMSelection.selectedCandidate,
            usedMiniHMM: usedMiniHMM,
            speedKmh: speedKmh,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars,
            top2Margin: traceTop2Margin
        ) : nil
        let selected: WayCandidate?
        if let threeWayGateSelection {
            if usesSameRefBounceGate,
               let baselineSelected,
               shouldSuppressImmediateSameRefBounce(
                candidate: threeWayGateSelection.candidate,
                over: baselineSelected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                accuracyBufferM: accuracyBuffer
               ) {
                selected = baselineSelected
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "same_ref_bounce_gate",
                        detail: "kept \(baselineSelected.wayID ?? "nil") over \(threeWayGateSelection.candidate.wayID ?? "nil") to avoid immediate same-ref bounce"
                    )
                )
            } else if let baselineSelected,
               normalizedWayID(threeWayGateSelection.candidate.wayID) != normalizedWayID(baselineSelected.wayID),
               shouldRejectTurnTransition(
                    from: baselineSelected,
                    to: threeWayGateSelection.candidate,
                    observedHeadingDeg: headingForScoring,
                    speedKmh: speedKmh,
                    fromEndpointProximityM: baselineSelected.endpointProximityM
               ) {
                selected = baselineSelected
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "turn_feasibility_gate",
                        detail: "kept \(baselineSelected.wayID ?? "nil") over \(threeWayGateSelection.candidate.wayID ?? "nil") due to speed/heading feasibility"
                    )
                )
            } else {
                selected = threeWayGateSelection.candidate
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "three_way_gate",
                        detail: "selected \(threeWayGateSelection.candidate.wayID ?? "nil") class=\(threeWayGateSelection.className) probs=\(threeWayGateSelection.probabilitySummary) current=\(baselineSelected?.wayID ?? "nil") distance=\(threeWayGateSelection.distanceWayID ?? "nil") endpoint=\(threeWayGateSelection.endpointWayID ?? "nil") heuristic=\(heuristicSelected?.wayID ?? "nil") mini=\(miniHMMSelection.selectedCandidate?.wayID ?? "nil")"
                    )
                )
            }
        } else {
            selected = baselineSelected
        }
        if let miniHMMSelected = miniHMMSelection.selectedCandidate {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "mini_hmm",
                    detail: "selected \(miniHMMSelected.wayID ?? "nil") state=\(miniHMMSelection.selectedCorridorState?.rawValue ?? "surface") beam=\(miniHMMSelection.candidateCount)"
                )
            )
        }

        func buildCorridorMatcherResult(
            finalSelected: WayCandidate?,
            finalActiveCorridorState: CorridorMatchState?,
            selectionTrace: [MatchSelectionTrace]
        ) -> SpeedLimitResult {
            let cityContext = resolveCityContext(db: db, lat: lat, lon: lon)
            let insideCityDecision: (insideCity: Bool?, source: String?)
            let residentialContext: ResidentialContext
            if highwayImpliesInsideCity(finalSelected?.highway) {
                insideCityDecision = (true, "highway_class_in_city")
                residentialContext = ResidentialContext(
                    insideCity: nil,
                    candidatePolygons: 0,
                    containingPolygons: 0,
                    resolveMs: 0.0
                )
            } else {
                residentialContext = resolveResidentialContext(db: db, lat: lat, lon: lon)
                if let insideCity = residentialContext.insideCity {
                    insideCityDecision = (insideCity, "residential_polygon")
                } else {
                    insideCityDecision = (cityContext.insideCity, cityContext.citySource)
                }
            }

            let t1 = DispatchTime.now().uptimeNanoseconds
            let elapsedMs = Double(t1 - t0) / 1_000_000.0

            let effectiveSpeed: Int?
            if finalSelected?.isUnlimitedSpeedLimit == true {
                effectiveSpeed = nil
            } else if let finalSelected, let matchedSpeed = finalSelected.speedKmh {
                if finalSelected.speedSource == .highwayClass,
                   Self.allowsResidentialAreaFallback(highway: finalSelected.highway),
                   let insideCity = insideCityDecision.insideCity {
                    // Highway class alone is weaker than explicit city/rural context.
                    effectiveSpeed = insideCity ? 50 : 100
                } else {
                    effectiveSpeed = matchedSpeed
                }
            } else if let finalSelected,
                      Self.allowsResidentialAreaFallback(highway: finalSelected.highway),
                      let insideCity = insideCityDecision.insideCity {
                // Keep inherited defaults only when a way match exists.
                effectiveSpeed = insideCity ? 50 : 100
            } else if insideCityDecision.insideCity == true {
                // Residential polygon containment can still provide a safe inner-city fallback.
                effectiveSpeed = 50
            } else {
                effectiveSpeed = nil
            }
            let resolvedInsideCityDecision = applyGermanLowSpeedInCityHeuristic(
                insideCityDecision: insideCityDecision,
                speedKmh: effectiveSpeed
            )
            let selectedRouteContinuity = loadSelectedRouteContinuity(
                db: db,
                wayID: finalSelected?.wayID
            )

            let selectedTunnelLike = isTruthyOSMTag(finalSelected?.tunnel)
            let candidateTraces = Array(traceRankedCandidates.prefix(Self.maxTraceCandidateCount)).map { entry in
                MatchCandidateTrace(
                    rank: entry.traceRank,
                    wayID: entry.candidate.wayID,
                    streetName: entry.candidate.streetName,
                    streetRef: entry.candidate.streetRef,
                    highway: entry.candidate.highway,
                    service: entry.candidate.service,
                    tunnel: entry.candidate.tunnel,
                    distanceM: entry.candidate.distanceM,
                    endpointProximityM: entry.candidate.endpointProximityM.isFinite ? entry.candidate.endpointProximityM : nil,
                    score: entry.traceScore,
                    geometryScore: entry.candidate.score,
                    portalEligible: entry.portalEligible,
                    corridorKind: entry.corridorState?.snapshot.kind,
                    corridorID: entry.corridorState?.snapshot.corridorID,
                    corridorSideNodeKey: entry.corridorState?.snapshot.sideNodeKey,
                    corridorDepthM: entry.corridorState?.snapshot.depthM,
                    corridorRemainingM: entry.corridorState.map { max(0.0, $0.snapshot.spanM - $0.snapshot.depthM) },
                    corridorDepthNodes: entry.corridorState?.snapshot.depthNodes,
                    corridorRemainingNodes: entry.corridorState.map { max(0, $0.snapshot.spanNodes - $0.snapshot.depthNodes) },
                    corridorEntryZone: entry.corridorState?.entryZone,
                    corridorExitZone: entry.corridorState?.exitZone,
                    continuityClass: String(describing: entry.continuity),
                    tunnelSelectable: entry.tunnelSelectable,
                    corridorSelectable: entry.corridorSelectable,
                    isSelected: normalizedWayID(entry.candidate.wayID) == normalizedWayID(finalSelected?.wayID)
                )
            }

            return SpeedLimitResult(
                speedLimitKmh: effectiveSpeed,
                isUnlimitedSpeedLimit: finalSelected?.isUnlimitedSpeedLimit == true ? true : nil,
                wayID: finalSelected?.wayID,
                highway: finalSelected?.highway,
                service: finalSelected?.service,
                tunnel: finalSelected?.tunnel,
                bridge: nil,
                covered: nil,
                location: nil,
                layer: nil,
                level: nil,
                isTunnelSegment: selectedTunnelLike,
                streetName: finalSelected?.streetName,
                streetBaseName: finalSelected?.streetBaseName,
                streetRef: finalSelected?.streetRef,
                matchedEndpointProximityM: finalSelected?.endpointProximityM.isFinite == true ? finalSelected?.endpointProximityM : nil,
                cityName: cityContext.cityName,
                cityPlaceName: cityContext.cityPlaceName,
                cityDistrictName: cityContext.cityDistrictName,
                insideCity: resolvedInsideCityDecision.insideCity,
                citySource: resolvedInsideCityDecision.source ?? cityContext.citySource,
                cityResolveMs: cityContext.resolveMs + residentialContext.resolveMs,
                cityCandidateBoundaries: cityContext.candidateBoundaries,
                cityContainingBoundaries: cityContext.containingBoundaries,
                cityPlaceCandidates: cityContext.placeCandidates,
                queryTimeMs: elapsedMs,
                candidateCount: candidateCount,
                speedCandidateCount: speedCandidateCount,
                nearestCandidateDistanceM: nearestCandidateDistance.isFinite ? nearestCandidateDistance : nil,
                nearestSpeedCandidateDistanceM: nearestSpeedCandidateDistance.isFinite ? nearestSpeedCandidateDistance : nil,
                nearbyTunnelCandidateWayIDs: nearbyTunnelCandidateWayIDs,
                nearbyTunnelCandidateRefs: Array(nearbyTunnelCandidateRefs).sorted(),
                usedMiniHMM: usedMiniHMM,
                miniHMMCandidateCount: miniHMMSelection.candidateCount,
                matchHypotheses: miniHMMSelection.hypotheses,
                candidateTraces: candidateTraces,
                selectionTrace: selectionTrace,
                activeCorridorState: finalActiveCorridorState,
                routeContinuityAvailable: selectedRouteContinuity.available,
                routeRelationMemberships: selectedRouteContinuity.memberships
            )
        }

        if matchingModel == .corridorHMMRawMiniHMM {
            let finalSelected = miniHMMSelection.selectedCandidate ?? heuristicSelected
            let finalActiveCorridorState: CorridorMatchState? = finalSelected.flatMap { candidate in
                guard let corridorState = candidateCorridorState(
                    for: candidate,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext,
                    progressContext: corridorProgressContext
                ) else {
                    return nil
                }
                if sameCorridorState(normalizedMatchContext.activeCorridorState, corridorState.snapshot) ||
                    shouldTriggerActiveCorridorMode(corridorState, matchContext: normalizedMatchContext) {
                    return corridorState.snapshot
                }
                return nil
            }
            var rawMiniHMMTrace = selectionTrace
            if let finalSelected {
                rawMiniHMMTrace.append(
                    MatchSelectionTrace(
                        step: "final",
                        detail: "selected \(finalSelected.wayID ?? "nil") via raw_mini_hmm tunnel=\(isTruthyOSMTag(finalSelected.tunnel)) corridor=\(finalActiveCorridorState.map { "\($0.kind)#\($0.corridorID)" } ?? "none")"
                    )
                )
            }
            return buildCorridorMatcherResult(
                finalSelected: finalSelected,
                finalActiveCorridorState: finalActiveCorridorState,
                selectionTrace: rawMiniHMMTrace
            )
        }

        let tunnelContinuityCandidate = preferredCandidate.flatMap { isTruthyOSMTag($0.tunnel) ? $0 : nil }
            ?? sameRefCandidate.flatMap { isTruthyOSMTag($0.tunnel) ? $0 : nil }
            ?? graphSelectableCandidates.first(where: { isTruthyOSMTag($0.tunnel) })
        let activeCorridorLockedCandidate = graphSelectableCandidates.first { candidate in
            guard let activeCorridorState = normalizedMatchContext.activeCorridorState,
                  let corridorState = candidateCorridorState(
                    for: candidate,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext,
                    progressContext: corridorProgressContext
                  ) else {
                return false
            }
            return sameCorridorState(activeCorridorState, corridorState.snapshot)
        }
        let triggeredCorridorEntryCandidate = graphSelectableCandidates.first { candidate in
            guard let corridorState = candidateCorridorState(
                for: candidate,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext
            ) else {
                return false
            }
            return shouldTriggerActiveCorridorMode(corridorState, matchContext: normalizedMatchContext)
        }
        let preferredHoldCandidate = preferredCandidate
            ?? baselineSelected.flatMap { candidate in
                normalizedWayID(candidate.wayID) == normalizedMatchContext.preferredWayID ? candidate : nil
            }
            ?? selected.flatMap { candidate in
                normalizedWayID(candidate.wayID) == normalizedMatchContext.preferredWayID ? candidate : nil
            }
            ?? graphSelectableCandidates.first(where: { candidate in
                normalizedWayID(candidate.wayID) == normalizedMatchContext.preferredWayID
            })
        var finalSelected: WayCandidate?
        var deferredActiveCorridorState: CorridorMatchState?
        if let selected,
           let activeCorridorState = normalizedMatchContext.activeCorridorState,
           !sameCorridorState(
                activeCorridorState,
                candidateCorridorState(
                    for: selected,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext,
                    progressContext: corridorProgressContext
                )?.snapshot
           ),
           let activeCorridorLockedCandidate,
           !isActiveCorridorEntryConnectorCandidate(
                selected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext
           ),
           !isActiveCorridorExitCandidate(
                selected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext
           ) {
            finalSelected = activeCorridorLockedCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "corridor_mode_lock",
                    detail: "kept corridor \(activeCorridorState.kind)#\(activeCorridorState.corridorID) candidate \(activeCorridorLockedCandidate.wayID ?? "nil") over \(selected.wayID ?? "nil") until exit zone"
                )
            )
        } else if normalizedMatchContext.activeCorridorState == nil,
                  let selected,
                  (selected.highway ?? "").lowercased() == "motorway_link",
                  let triggeredCorridorEntryCandidate,
                  let corridorState = candidateCorridorState(
                    for: triggeredCorridorEntryCandidate,
                    matchContext: normalizedMatchContext,
                    wayLinks: wayLinksContext,
                    progressContext: corridorProgressContext
                  ),
                  corridorState.snapshot.kind == "motorway" {
            let entryProgressM = corridorApproachProgressM(
                for: corridorState,
                matchContext: normalizedMatchContext
            )
            let entryProgressNodes = corridorApproachProgressNodes(
                for: corridorState,
                matchContext: normalizedMatchContext
            )
            finalSelected = selected
            deferredActiveCorridorState = corridorState.snapshot
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "corridor_entry_arm",
                    detail: "armed motorway mode via \(triggeredCorridorEntryCandidate.wayID ?? "nil") after \(normalizedMatchContext.approachCorridorFixCount) entry-zone fixes, \(String(format: "%.1f", entryProgressM)) m and \(entryProgressNodes) corridor nodes while keeping entry connector \(selected.wayID ?? "nil")"
                )
            )
        } else if normalizedMatchContext.activeCorridorState == nil,
                  let selected,
                  let triggeredCorridorEntryCandidate,
                  normalizedWayID(selected.wayID) != normalizedWayID(triggeredCorridorEntryCandidate.wayID) {
            let corridorState = candidateCorridorState(
                for: triggeredCorridorEntryCandidate,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext
            )
            let entryProgressM = corridorState.map {
                corridorApproachProgressM(for: $0, matchContext: normalizedMatchContext)
            } ?? 0.0
            let entryProgressNodes = corridorState.map {
                corridorApproachProgressNodes(for: $0, matchContext: normalizedMatchContext)
            } ?? 0
            finalSelected = triggeredCorridorEntryCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "corridor_entry_gate",
                    detail: "activated \(corridorState?.snapshot.kind ?? "corridor") mode via \(triggeredCorridorEntryCandidate.wayID ?? "nil") after \(normalizedMatchContext.approachCorridorFixCount) entry-zone fixes, \(String(format: "%.1f", entryProgressM)) m and \(entryProgressNodes) corridor nodes"
                )
            )
        } else if !normalizedMatchContext.isInTunnelMode,
           let selected,
           !isTruthyOSMTag(selected.tunnel),
           let tunnelContinuityCandidate,
           shouldPromoteTunnelEntry(
                tunnelCandidate: tunnelContinuityCandidate,
                over: selected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars,
                accuracyBufferM: accuracyBuffer
           ) {
            finalSelected = tunnelContinuityCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "tunnel_entry_gate",
                    detail: "promoted tunnel \(tunnelContinuityCandidate.wayID ?? "nil") over surface \(selected.wayID ?? "nil") after repeated portal exposure and degraded signal quality"
                )
            )
        } else if normalizedMatchContext.isInTunnelMode,
                  let selected,
                  !isTruthyOSMTag(selected.tunnel),
                  let tunnelContinuityCandidate,
           shouldKeepTunnelContinuity(
                tunnelCandidate: tunnelContinuityCandidate,
                over: selected,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext,
                pairContext: corridorPairContext,
                accuracyBufferM: accuracyBuffer,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
           ) {
            finalSelected = tunnelContinuityCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "tunnel_exit_gate",
                    detail: "kept tunnel \(tunnelContinuityCandidate.wayID ?? "nil") and rejected mid-segment surface exit \(selected.wayID ?? "nil")"
                )
            )
        } else {
            finalSelected = selected
        }
        if usesAntiABAHysteresis,
           let currentFinalSelected = finalSelected,
           let preferredHoldCandidate,
           shouldApplyAntiABAHysteresis(
                candidate: currentFinalSelected,
                holdCandidate: preferredHoldCandidate,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext,
                accuracyBufferM: accuracyBuffer
           ) {
            finalSelected = preferredHoldCandidate
            deferredActiveCorridorState = nil
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "anti_aba_hysteresis",
                    detail: "kept \(preferredHoldCandidate.wayID ?? "nil") over \(currentFinalSelected.wayID ?? "nil") to avoid immediate A-B-A bounce"
                )
            )
        }
        let finalActiveCorridorState: CorridorMatchState? = finalSelected.flatMap { candidate in
            guard let corridorState = candidateCorridorState(
                for: candidate,
                matchContext: normalizedMatchContext,
                wayLinks: wayLinksContext,
                progressContext: corridorProgressContext
            ) else {
                return nil
            }
            if sameCorridorState(normalizedMatchContext.activeCorridorState, corridorState.snapshot) ||
                shouldTriggerActiveCorridorMode(corridorState, matchContext: normalizedMatchContext) {
                return corridorState.snapshot
            }
            return nil
        } ?? deferredActiveCorridorState
        if let finalSelected {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "final",
                    detail: "selected \(finalSelected.wayID ?? "nil") tunnel=\(isTruthyOSMTag(finalSelected.tunnel)) corridor=\(finalActiveCorridorState.map { "\($0.kind)#\($0.corridorID)" } ?? "none")"
                )
            )
        }
        return buildCorridorMatcherResult(
            finalSelected: finalSelected,
            finalActiveCorridorState: finalActiveCorridorState,
            selectionTrace: selectionTrace
        )
    }

    func lookupStreetNames(forWayIDs wayIDs: [String]) throws -> [String: String] {
        let uniqueWayIDs = Array(
            Set(
                wayIDs
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }
            )
        ).sorted()
        guard !uniqueWayIDs.isEmpty else {
            return [:]
        }

        var db: OpaquePointer?
        let encodedPath = dbPath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbPath
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for \(dbPath)")
        }
        defer { sqlite3_close(db) }

        guard tableExists(db: db, name: "ways"), columnExists(db: db, table: "ways", column: "way_id") else {
            return [:]
        }

        let hasStreetName = columnExists(db: db, table: "ways", column: "street_name")
        let hasStreetRef = columnExists(db: db, table: "ways", column: "ref")
        guard hasStreetName || hasStreetRef else {
            return [:]
        }

        let streetSelect = hasStreetName ? "street_name" : "NULL"
        let refSelect = hasStreetRef ? "ref" : "NULL"
        var resolved: [String: String] = [:]

        let chunkSize = 200
        var cursor = 0
        while cursor < uniqueWayIDs.count {
            let end = min(cursor + chunkSize, uniqueWayIDs.count)
            let chunk = Array(uniqueWayIDs[cursor..<end])
            let placeholders = chunk.enumerated().map { "?\($0.offset + 1)" }.joined(separator: ",")
            let sql = """
            SELECT way_id, \(streetSelect) AS street_name, \(refSelect) AS ref
            FROM ways
            WHERE way_id IN (\(placeholders))
            """

            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw ConsumerAppError.sqlite("prepare failed in street lookup query")
            }
            defer { sqlite3_finalize(stmt) }

            for (index, wayID) in chunk.enumerated() {
                sqlite3_bind_text(stmt, Int32(index + 1), wayID, -1, SQLITE_TRANSIENT)
            }

            while true {
                let rc = sqlite3_step(stmt)
                if rc == SQLITE_DONE {
                    break
                }
                if rc != SQLITE_ROW {
                    throw ConsumerAppError.sqlite("step failed in street lookup query")
                }
                guard let wayID = cStringOptional(sqlite3_column_text(stmt, 0)) else {
                    continue
                }
                let streetName = cStringOptional(sqlite3_column_text(stmt, 1))
                let ref = cStringOptional(sqlite3_column_text(stmt, 2))
                if let display = Self.formattedStreetDisplay(streetName: streetName, ref: ref) {
                    resolved[wayID] = display
                }
            }

            cursor = end
        }

        return resolved
    }

    static func deriveSpeedLimitKmh(maxspeed: String?, maxspeedType: String?, sourceMaxspeed: String?, highway: String?) -> Int? {
        deriveSpeedLimitWithSource(
            maxspeed: maxspeed,
            maxspeedType: maxspeedType,
            sourceMaxspeed: sourceMaxspeed,
            highway: highway
        ).speed
    }

    static func germanLowSpeedLimitImpliesInsideCity(countryCode: String?, speedKmh: Int?) -> Bool {
        guard normalizedCountryCode(countryCode) == "DEU",
              let speedKmh,
              speedKmh > 0,
              speedKmh < 50 else {
            return false
        }
        return true
    }

    private static func allowsResidentialAreaFallback(highway: String?) -> Bool {
        switch highway?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "motorway", "motorway_link":
            return false
        default:
            return true
        }
    }

    private static func deriveSpeedLimitWithSource(
        maxspeed: String?,
        maxspeedType: String?,
        sourceMaxspeed: String?,
        highway: String?
    ) -> (speed: Int?, source: DerivedSpeedSource, isUnlimited: Bool) {
        if isUnlimitedSpeedTag(maxspeed) {
            return (nil, .explicitUnlimitedTag, true)
        }
        if let maxspeed, let explicit = parseExplicitSpeed(maxspeed) {
            return (explicit, .explicitTag, false)
        }

        let inherited = [maxspeedType, sourceMaxspeed].compactMap { $0 }.joined(separator: " ").lowercased()
        if inherited.contains("urban") {
            return (50, .inheritedTag, false)
        }
        if inherited.contains("rural") {
            return (100, .inheritedTag, false)
        }
        if inherited.contains("motorway") {
            return (nil, .inheritedTag, false)
        }

        switch highway?.lowercased() {
        case "motorway", "motorway_link":
            return (nil, .highwayClass, false)
        case "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link":
            return (100, .highwayClass, false)
        case "living_street":
            return (10, .highwayClass, false)
        case "residential", "service", "unclassified", "road":
            return (50, .highwayClass, false)
        default:
            return (nil, .none, false)
        }
    }

    static func isUnlimitedSpeedTag(_ raw: String?) -> Bool {
        guard let raw else {
            return false
        }
        return raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() == "none"
    }

    private static func normalizedCountryCode(_ raw: String?) -> String? {
        guard let raw else {
            return nil
        }
        let code = raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard code.count == 3 else {
            return nil
        }
        return code
    }

    private static func inferCountryCode(fromDBPath dbPath: String) -> String? {
        let fileName = URL(fileURLWithPath: dbPath).lastPathComponent.uppercased()
        guard fileName.count >= 3 else {
            return nil
        }
        let prefix = String(fileName.prefix(3))
        return prefix.allSatisfy(\.isLetter) ? prefix : nil
    }

    static func parseExplicitSpeed(_ raw: String) -> Int? {
        let digits = raw.filter(\.isNumber)
        guard !digits.isEmpty, let value = Int(digits), value > 0 else {
            return nil
        }
        return value
    }

    static func formattedStreetDisplay(streetName: String?, ref: String?) -> String? {
        let normalizedStreet = streetName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedRef = ref?.trimmingCharacters(in: .whitespacesAndNewlines)
        let hasStreet = (normalizedStreet?.isEmpty == false)
        let hasRef = (normalizedRef?.isEmpty == false)

        if hasStreet, hasRef {
            return "\(normalizedStreet!) (\(normalizedRef!))"
        }
        if hasStreet {
            return normalizedStreet
        }
        if hasRef {
            return normalizedRef
        }
        return nil
    }

    private func queryBounds(lat: Double, lon: Double, radiusM: Double) -> (minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) {
        let degLat = radiusM / 111_132.0
        let cosLat = max(0.173648, abs(cos(lat * .pi / 180.0)))
        let degLon = radiusM / (111_320.0 * cosLat)
        return (lon - degLon, lat - degLat, lon + degLon, lat + degLat)
    }

    private func candidateNetworks(for matchContext: NormalizedMatchContext) -> [CandidateNetwork] {
        let hasAnchorContext =
            matchContext.preferredWayID != nil ||
            matchContext.preferredHighway != nil ||
            !matchContext.recentWayIDs.isEmpty ||
            !matchContext.recentFixes.isEmpty
        let preferredHighwayFamily = highwayFamily(matchContext.preferredHighway)
        let activeCorridorKind = matchContext.activeCorridorState?.kind
        let approachCorridorKind = matchContext.approachCorridorState?.kind
        let portalPrefetchThresholdM =
            max(Self.tunnelPortalEntryEndpointThresholdM, Self.motorwayTransitionEndpointThresholdM) +
            Self.corridorProgressNoiseToleranceM
        let nearPortalAnchor = matchContext.preferredEndpointProximityM.map {
            $0.isFinite && $0 <= portalPrefetchThresholdM
        } ?? false

        var networks: [CandidateNetwork] = [.surface]
        if !hasAnchorContext ||
            matchContext.isInTunnelMode ||
            activeCorridorKind == "tunnel" ||
            approachCorridorKind == "tunnel" ||
            matchContext.tunnelApproachFixCount > 0 ||
            !matchContext.recentTunnelCandidateWayIDs.isEmpty ||
            !matchContext.recentTunnelCandidateRefs.isEmpty ||
            nearPortalAnchor {
            networks.append(.tunnel)
        }
        if !hasAnchorContext ||
            matchContext.isInMotorwayMode ||
            activeCorridorKind == "motorway" ||
            approachCorridorKind == "motorway" ||
            preferredHighwayFamily == "motorway" ||
            nearPortalAnchor {
            networks.append(.motorway)
        }
        return networks
    }

    private func candidateNetworkFilterSQL(for network: CandidateNetwork) -> String {
        let tunnelCondition = "LOWER(TRIM(COALESCE(w.tunnel, ''))) NOT IN ('', '0', 'false', 'no', 'off', 'none')"
        let highwayExpr = "LOWER(TRIM(COALESCE(w.highway, '')))"
        switch network {
        case .surface:
            return "NOT (\(tunnelCondition)) AND \(highwayExpr) != 'motorway'"
        case .tunnel:
            return tunnelCondition
        case .motorway:
            return "NOT (\(tunnelCondition)) AND \(highwayExpr) = 'motorway'"
        }
    }

    private func loadCandidates(
        db: OpaquePointer,
        lat: Double,
        lon: Double,
        radiusM: Double,
        maxCandidates: Int,
        headingForScoring: Double?,
        matchContext: NormalizedMatchContext
    ) throws -> CandidateQueryResult {
        var mergedCandidatesByWayID: [String: WayCandidate] = [:]
        var anonymousCandidates: [WayCandidate] = []
        for network in candidateNetworks(for: matchContext) {
            let candidates = try loadCandidates(
                db: db,
                lat: lat,
                lon: lon,
                radiusM: radiusM,
                maxCandidates: maxCandidates,
                headingForScoring: headingForScoring,
                network: network
            )
            for candidate in candidates {
                if let wayID = normalizedWayID(candidate.wayID) {
                    if let existing = mergedCandidatesByWayID[wayID] {
                        if isBetterCandidate(candidate, than: existing) {
                            mergedCandidatesByWayID[wayID] = candidate
                        }
                    } else {
                        mergedCandidatesByWayID[wayID] = candidate
                    }
                } else {
                    anonymousCandidates.append(candidate)
                }
            }
        }

        var rankedCandidates = Array(mergedCandidatesByWayID.values)
        rankedCandidates.append(contentsOf: anonymousCandidates)
        rankedCandidates.sort { lhs, rhs in
            isBetterCandidate(lhs, than: rhs)
        }
        let speedCandidateCount = rankedCandidates.reduce(into: 0) { partialResult, candidate in
            if candidate.speedKmh != nil || candidate.isUnlimitedSpeedLimit {
                partialResult += 1
            }
        }
        let nearestCandidateDistance = rankedCandidates.map(\.distanceM).min() ?? .infinity
        let nearestSpeedCandidateDistance = rankedCandidates
            .compactMap { ($0.speedKmh != nil || $0.isUnlimitedSpeedLimit) ? $0.distanceM : nil }
            .min() ?? .infinity
        let nearbyTunnelCandidateWayIDs = rankedCandidates.compactMap { candidate -> String? in
            guard isTruthyOSMTag(candidate.tunnel) else {
                return nil
            }
            return normalizedWayID(candidate.wayID)
        }
        let nearbyTunnelCandidateRefs = Set(
            rankedCandidates.flatMap { candidate in
                isTruthyOSMTag(candidate.tunnel) ? Self.normalizedRefTokens(candidate.streetRef) : []
            }
        )
        return CandidateQueryResult(
            candidates: rankedCandidates,
            candidateCount: rankedCandidates.count,
            speedCandidateCount: speedCandidateCount,
            nearestCandidateDistance: nearestCandidateDistance,
            nearestSpeedCandidateDistance: nearestSpeedCandidateDistance,
            nearbyTunnelCandidateWayIDs: nearbyTunnelCandidateWayIDs,
            nearbyTunnelCandidateRefs: nearbyTunnelCandidateRefs,
            queryRadiusM: radiusM
        )
    }

    private func loadCandidates(
        db: OpaquePointer,
        lat: Double,
        lon: Double,
        radiusM: Double,
        maxCandidates: Int,
        headingForScoring: Double?,
        network: CandidateNetwork
    ) throws -> [WayCandidate] {
        let wayGeomJoin = "LEFT JOIN way_geom g ON g.way_id = w.way_id"
        let hasWayEndpoints = tableExists(db: db, name: "way_endpoints")
        let wayEndpointJoin = hasWayEndpoints ? "LEFT JOIN way_endpoints e ON e.way_id = w.way_id" : ""
        let wayEndpointSelect = hasWayEndpoints
            ? ", e.start_node_key, e.end_node_key, e.way_length_m"
            : ", NULL AS start_node_key, NULL AS end_node_key, NULL AS way_length_m"
        let bounds = queryBounds(lat: lat, lon: lon, radiusM: radiusM)
        let hasNetworkRTree = tableExists(db: db, name: network.rtreeTableName)
        let hasWaysRtree = tableExists(db: db, name: "ways_rtree")
        let fromClause: String
        let boundsSource: String
        let extraWhereClause: String
        if hasNetworkRTree {
            fromClause = "FROM \(network.rtreeTableName) r JOIN ways w ON w.way_id = r.way_id"
            boundsSource = "r"
            extraWhereClause = ""
        } else if hasWaysRtree {
            fromClause = "FROM ways_rtree r JOIN ways w ON w.way_id = r.way_id"
            boundsSource = "r"
            extraWhereClause = "AND \(candidateNetworkFilterSQL(for: network))"
        } else {
            fromClause = "FROM ways w"
            boundsSource = "w"
            extraWhereClause = "AND \(candidateNetworkFilterSQL(for: network))"
        }
        let sql = """
        SELECT w.way_id, w.highway, w.street_name, w.ref, w.maxspeed, w.maxspeed_type, w.source_maxspeed,
               w.approx_heading_deg, w.service, w.tunnel,
               w.min_lon, w.min_lat, w.max_lon, w.max_lat, g.points_json\(wayEndpointSelect)
        \(fromClause)
        \(wayGeomJoin)
        \(wayEndpointJoin)
        WHERE \(boundsSource).min_lon <= ?1 AND \(boundsSource).max_lon >= ?2
          AND \(boundsSource).min_lat <= ?3 AND \(boundsSource).max_lat >= ?4
          \(extraWhereClause)
        LIMIT ?5
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw ConsumerAppError.sqlite("prepare failed in lookup query")
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, bounds.maxLon)
        sqlite3_bind_double(stmt, 2, bounds.minLon)
        sqlite3_bind_double(stmt, 3, bounds.maxLat)
        sqlite3_bind_double(stmt, 4, bounds.minLat)
        sqlite3_bind_int64(stmt, 5, Int64(maxCandidates))

        var rankedCandidates: [WayCandidate] = []
        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_DONE {
                break
            }
            if rc != SQLITE_ROW {
                throw ConsumerAppError.sqlite("step failed in lookup query")
            }

            let wayID = cStringOptional(sqlite3_column_text(stmt, 0))
            let highway = cStringOptional(sqlite3_column_text(stmt, 1))
            let rawStreetName = cStringOptional(sqlite3_column_text(stmt, 2))
            let streetRef = cStringOptional(sqlite3_column_text(stmt, 3))
            let streetName = Self.formattedStreetDisplay(streetName: rawStreetName, ref: streetRef)
            let maxspeedRaw = cStringOptional(sqlite3_column_text(stmt, 4))
            let maxspeedType = cStringOptional(sqlite3_column_text(stmt, 5))
            let sourceMaxspeed = cStringOptional(sqlite3_column_text(stmt, 6))
            let approxHeadingDeg = sqlite3_column_type(stmt, 7) == SQLITE_NULL ? nil : sqlite3_column_double(stmt, 7)
            let service = cStringOptional(sqlite3_column_text(stmt, 8))
            let tunnel = cStringOptional(sqlite3_column_text(stmt, 9))
            let minLon = sqlite3_column_double(stmt, 10)
            let minLat = sqlite3_column_double(stmt, 11)
            let maxLon = sqlite3_column_double(stmt, 12)
            let maxLat = sqlite3_column_double(stmt, 13)
            let points = parseWayPoints(cStringOptional(sqlite3_column_text(stmt, 14)))
            let startNodeKey = cStringOptional(sqlite3_column_text(stmt, 15))
            let endNodeKey = cStringOptional(sqlite3_column_text(stmt, 16))
            let wayLengthM = sqlite3_column_type(stmt, 17) == SQLITE_NULL ? nil : sqlite3_column_double(stmt, 17)

            let bboxDistance = distanceToBBoxM(
                lat: lat,
                lon: lon,
                minLon: minLon,
                minLat: minLat,
                maxLon: maxLon,
                maxLat: maxLat
            )
            let polylineMetrics = polylineMetrics(lat: lat, lon: lon, points: points)
            let distance = polylineMetrics?.distanceM ?? bboxDistance
            let parsedResult = Self.deriveSpeedLimitWithSource(
                maxspeed: maxspeedRaw,
                maxspeedType: maxspeedType,
                sourceMaxspeed: sourceMaxspeed,
                highway: highway
            )
            let localHeadingDeg = polylineMetrics?.localHeadingDeg
            let headingPenalty: Double
            if let headingForScoring,
               let candidateHeadingDeg = localHeadingDeg ?? approxHeadingDeg {
                headingPenalty = headingMismatchDeg(headingDeg: headingForScoring, approxHeadingDeg: candidateHeadingDeg) * Self.headingWeightMPerDeg
            } else {
                headingPenalty = 0.0
            }
            let score = distance + headingPenalty

            rankedCandidates.append(
                WayCandidate(
                    wayID: wayID,
                    highway: highway,
                    service: service,
                    tunnel: tunnel,
                    streetName: streetName,
                    streetBaseName: rawStreetName,
                    streetRef: streetRef,
                    speedKmh: parsedResult.speed,
                    speedSource: parsedResult.source,
                    isUnlimitedSpeedLimit: parsedResult.isUnlimited,
                    distanceM: distance,
                    endpointProximityM: polylineMetrics?.endpointProximityM ?? .infinity,
                    distanceToStartM: polylineMetrics?.distanceToStartM,
                    distanceToEndM: polylineMetrics?.distanceToEndM,
                    score: score,
                    queryPoint: (lat, lon),
                    points: points,
                    localHeadingDeg: localHeadingDeg,
                    wayLengthM: wayLengthM ?? polylineMetrics.map { $0.distanceToStartM + $0.distanceToEndM },
                    startNodeKey: startNodeKey,
                    endNodeKey: endNodeKey,
                    startPoint: points.first,
                    endPoint: points.last,
                    startHeadingDeg: endpointHeadingDeg(points: points, atStart: true),
                    endHeadingDeg: endpointHeadingDeg(points: points, atStart: false)
                )
            )
        }
        return rankedCandidates
    }

    private func effectiveCandidateSearchRadiusM(radiusM: Double) -> Double {
        let normalizedRadiusM = max(radiusM, 0.0)
        if matchingModel == .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic {
            return min(normalizedRadiusM, Self.simpleSpeedRefNarrowWindowRadiusM)
        }
        return normalizedRadiusM
    }

    private func candidateLookupRadiusM(radiusM: Double, horizontalAccuracyM: Double?) -> Double {
        let normalizedRadiusM = max(radiusM, 0.0)
        guard let horizontalAccuracyM, horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0.0 else {
            return normalizedRadiusM
        }
        return min(normalizedRadiusM, horizontalAccuracyM)
    }

    private func mergeCandidateQueries(
        capped: CandidateQueryResult,
        full: CandidateQueryResult?,
        matchContext: NormalizedMatchContext,
        db: OpaquePointer
    ) -> CandidateQueryResult {
        guard let full else {
            return capped
        }
        if capped.candidates.isEmpty {
            return full
        }

        var mergedCandidates = capped.candidates
        let linkedWayIDs = linkedWayIDsForAccuracyCapMerge(db: db, matchContext: matchContext)
        let sequenceExpansionWayIDs = !matchContext.recentHypotheses.isEmpty
            ? Set(full.candidates.prefix(Self.miniHMMBeamWidth).compactMap { normalizedWayID($0.wayID) })
            : []
        var includedWayIDs = Set(
            capped.candidates.compactMap { normalizedWayID($0.wayID) }
        )
        for candidate in full.candidates {
            guard let candidateWayID = normalizedWayID(candidate.wayID) else {
                continue
            }
            guard shouldIncludeContinuityCandidateBeyondAccuracyCap(
                candidate,
                matchContext: matchContext,
                linkedWayIDs: linkedWayIDs
            ) || sequenceExpansionWayIDs.contains(candidateWayID) else {
                continue
            }
            if includedWayIDs.insert(candidateWayID).inserted {
                mergedCandidates.append(candidate)
            }
        }
        guard mergedCandidates.count != capped.candidates.count else {
            return capped
        }

        mergedCandidates.sort { lhs, rhs in
            isBetterCandidate(lhs, than: rhs)
        }
        let speedCandidateCount = mergedCandidates.reduce(into: 0) { partialResult, candidate in
            if candidate.speedKmh != nil {
                partialResult += 1
            }
        }
        let nearestCandidateDistance = mergedCandidates.map(\.distanceM).min() ?? .infinity
        let nearestSpeedCandidateDistance = mergedCandidates
            .compactMap { $0.speedKmh != nil ? $0.distanceM : nil }
            .min() ?? .infinity
        let nearbyTunnelCandidateWayIDs = mergedCandidates.compactMap { candidate -> String? in
            guard isTruthyOSMTag(candidate.tunnel) else {
                return nil
            }
            return normalizedWayID(candidate.wayID)
        }
        let nearbyTunnelCandidateRefs = Set(
            mergedCandidates.flatMap { candidate in
                isTruthyOSMTag(candidate.tunnel) ? Self.normalizedRefTokens(candidate.streetRef) : []
            }
        )
        return CandidateQueryResult(
            candidates: mergedCandidates,
            candidateCount: mergedCandidates.count,
            speedCandidateCount: speedCandidateCount,
            nearestCandidateDistance: nearestCandidateDistance,
            nearestSpeedCandidateDistance: nearestSpeedCandidateDistance,
            nearbyTunnelCandidateWayIDs: nearbyTunnelCandidateWayIDs,
            nearbyTunnelCandidateRefs: nearbyTunnelCandidateRefs,
            queryRadiusM: capped.queryRadiusM
        )
    }

    private func shouldIncludeContinuityCandidateBeyondAccuracyCap(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        linkedWayIDs: Set<String>
    ) -> Bool {
        let candidateWayID = normalizedWayID(candidate.wayID)
        if candidateWayID == matchContext.preferredWayID {
            return true
        }
        if let candidateWayID, matchContext.recentWayIDs.contains(candidateWayID) {
            return true
        }

        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        if !candidateRefTokens.isEmpty &&
            (!candidateRefTokens.isDisjoint(with: matchContext.preferredStreetRefs) ||
             !candidateRefTokens.isDisjoint(with: matchContext.recentStreetRefs) ||
             !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelCandidateRefs)) {
            return true
        }

        if let candidateWayID, matchContext.recentTunnelCandidateWayIDs.contains(candidateWayID) {
            return true
        }
        if let candidateWayID, linkedWayIDs.contains(candidateWayID) {
            return true
        }
        return false
    }

    private func linkedWayIDsForAccuracyCapMerge(
        db: OpaquePointer,
        matchContext: NormalizedMatchContext
    ) -> Set<String> {
        guard tableExists(db: db, name: "way_links") else {
            return []
        }
        var anchorWayIDs = matchContext.recentWayIDs
        anchorWayIDs.formUnion(matchContext.recentHypotheses.map(\.wayID))
        if let preferredWayID = matchContext.preferredWayID {
            anchorWayIDs.insert(preferredWayID)
        }
        let orderedWayIDs = anchorWayIDs.compactMap { Int64($0) }.sorted()
        guard !orderedWayIDs.isEmpty else {
            return []
        }

        let placeholders = Array(repeating: "?", count: orderedWayIDs.count).joined(separator: ",")
        let sql = """
        SELECT way_id, linked_way_id
        FROM way_links
        WHERE way_id IN (\(placeholders))
        """

        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return []
        }
        for (index, wayID) in orderedWayIDs.enumerated() {
            sqlite3_bind_int64(stmt, Int32(index + 1), wayID)
        }

        let anchorWayIDStrings = Set(orderedWayIDs.map(String.init))
        var linkedWayIDs: Set<String> = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let sourceWayID = String(sqlite3_column_int64(stmt, 0))
            let targetWayID = String(sqlite3_column_int64(stmt, 1))
            if anchorWayIDStrings.contains(sourceWayID) {
                linkedWayIDs.insert(targetWayID)
            }
            if anchorWayIDStrings.contains(targetWayID) {
                linkedWayIDs.insert(sourceWayID)
            }
        }
        return linkedWayIDs.subtracting(anchorWayIDStrings)
    }

    private func distanceToBBoxM(lat: Double, lon: Double, minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) -> Double {
        let clampedLon = min(max(lon, minLon), maxLon)
        let clampedLat = min(max(lat, minLat), maxLat)
        return haversineM(lat1: lat, lon1: lon, lat2: clampedLat, lon2: clampedLon)
    }

    private func normalizedHeadingDegrees(_ headingDeg: Double?) -> Double? {
        guard var headingDeg, headingDeg.isFinite else {
            return nil
        }
        headingDeg.formTruncatingRemainder(dividingBy: 360.0)
        if headingDeg < 0.0 {
            headingDeg += 360.0
        }
        return headingDeg
    }

    private func shouldUseHeading(
        headingDeg: Double?,
        headingAccuracyDeg: Double?,
        speedKmh: Double?
    ) -> Bool {
        guard headingDeg != nil else {
            return false
        }
        if let speedKmh, speedKmh.isFinite, speedKmh < Self.headingMinSpeedKmh {
            return false
        }
        if let headingAccuracyDeg, headingAccuracyDeg.isFinite,
           headingAccuracyDeg >= 0.0, headingAccuracyDeg > Self.headingMaxAccuracyDeg {
            return false
        }
        return true
    }

    private func headingMismatchDeg(headingDeg: Double, approxHeadingDeg: Double) -> Double {
        var raw = abs((headingDeg - approxHeadingDeg).truncatingRemainder(dividingBy: 360.0))
        raw = min(raw, 360.0 - raw)
        return min(raw, abs(180.0 - raw))
    }

    private func directedHeadingMismatchDeg(headingDeg: Double, approxHeadingDeg: Double) -> Double {
        var raw = abs((headingDeg - approxHeadingDeg).truncatingRemainder(dividingBy: 360.0))
        raw = min(raw, 360.0 - raw)
        return raw
    }

    private func axisHeadingDeg(
        from lat1: Double?,
        lon1: Double?,
        to lat2: Double?,
        lon2: Double?
    ) -> Double? {
        guard let lat1, let lon1, let lat2, let lon2 else {
            return nil
        }
        let phi1 = lat1 * .pi / 180.0
        let phi2 = lat2 * .pi / 180.0
        let lambdaDelta = (lon2 - lon1) * .pi / 180.0
        let y = sin(lambdaDelta) * cos(phi2)
        let x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(lambdaDelta)
        guard x.isFinite, y.isFinite, abs(x) > 1e-12 || abs(y) > 1e-12 else {
            return nil
        }
        return normalizedHeadingDegrees((atan2(y, x) * 180.0 / .pi) + 360.0)
    }

    private func axisHeadingDeg(for candidate: WayCandidate) -> Double? {
        axisHeadingDeg(
            from: candidate.startPoint?.0,
            lon1: candidate.startPoint?.1,
            to: candidate.endPoint?.0,
            lon2: candidate.endPoint?.1
        )
    }

    private func transitionHeadingEvidence(
        fromHeadingDeg: Double?,
        toHeadingDeg: Double?,
        fromEndpointProximityM: Double,
        toEndpointProximityM: Double,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        serviceLike: Bool
    ) -> TransitionHeadingEvidence? {
        guard let observedHeadingDeg,
              let speedKmh,
              speedKmh.isFinite,
              speedKmh >= Self.headingMinSpeedKmh,
              let fromHeadingDeg,
              let toHeadingDeg else {
            return nil
        }
        let currentMismatchDeg = headingMismatchDeg(
            headingDeg: observedHeadingDeg,
            approxHeadingDeg: fromHeadingDeg
        )
        let candidateMismatchDeg = headingMismatchDeg(
            headingDeg: observedHeadingDeg,
            approxHeadingDeg: toHeadingDeg
        )
        let turnAngleDeg = headingMismatchDeg(
            headingDeg: fromHeadingDeg,
            approxHeadingDeg: toHeadingDeg
        )
        let nearEndpoint = fromEndpointProximityM <= Self.segmentTransitionEndpointThresholdM &&
            toEndpointProximityM <= (Self.segmentTransitionEndpointThresholdM * 2.0)
        return TransitionHeadingEvidence(
            currentMismatchDeg: currentMismatchDeg,
            candidateMismatchDeg: candidateMismatchDeg,
            turnAngleDeg: turnAngleDeg,
            speedKmh: speedKmh,
            nearEndpoint: nearEndpoint,
            serviceLike: serviceLike
        )
    }

    private func transitionHeadingEvidence(
        fromAxisHeadingDeg: Double?,
        fromEndpointProximityM: Double,
        to candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?
    ) -> TransitionHeadingEvidence? {
        transitionHeadingEvidence(
            fromHeadingDeg: fromAxisHeadingDeg,
            toHeadingDeg: axisHeadingDeg(for: candidate),
            fromEndpointProximityM: fromEndpointProximityM,
            toEndpointProximityM: candidate.endpointProximityM,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            serviceLike: (candidate.service?.isEmpty == false) ||
                candidate.highway?.lowercased() == "service"
        )
    }

    private func shouldRejectTurnTransition(
        from currentCandidate: WayCandidate,
        to candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        fromEndpointProximityM: Double
    ) -> Bool {
        guard let evidence = transitionHeadingEvidence(
            fromAxisHeadingDeg: axisHeadingDeg(for: currentCandidate),
            fromEndpointProximityM: fromEndpointProximityM,
            to: candidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh
        ) else {
            return false
        }
        guard evidence.currentAligned, evidence.meaningfulTurn, !evidence.candidateClearlyBetterAligned else {
            return false
        }
        if evidence.serviceLike && evidence.speedKmh >= Self.transitionServiceRoadSpeedKmh {
            return true
        }
        if evidence.verySharpTurn && evidence.speedKmh >= Self.transitionModerateSpeedKmh {
            return true
        }
        if evidence.sharpTurn && evidence.speedKmh >= Self.transitionHighSpeedKmh {
            return true
        }
        return false
    }

    private func transitionHeadingPenaltyAdjustment(
        fromAxisHeadingDeg: Double?,
        fromEndpointProximityM: Double,
        to candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?
    ) -> Double {
        guard let evidence = transitionHeadingEvidence(
            fromAxisHeadingDeg: fromAxisHeadingDeg,
            fromEndpointProximityM: fromEndpointProximityM,
            to: candidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh
        ) else {
            return 0.0
        }
        if evidence.currentAligned && evidence.meaningfulTurn && !evidence.candidateClearlyBetterAligned {
            if evidence.serviceLike && evidence.speedKmh >= Self.transitionServiceRoadSpeedKmh {
                return Self.transitionVerySharpTurnPenaltyM
            }
            if evidence.verySharpTurn && evidence.speedKmh >= Self.transitionModerateSpeedKmh {
                return Self.transitionVerySharpTurnPenaltyM
            }
            if evidence.sharpTurn && evidence.speedKmh >= Self.transitionHighSpeedKmh {
                return Self.transitionSharpTurnPenaltyM
            }
        }
        if evidence.nearEndpoint && evidence.candidateClearlyBetterAligned && evidence.meaningfulTurn {
            return evidence.speedKmh <= Self.transitionHighSpeedKmh
                ? -Self.transitionHeadingBonusM
                : -(Self.transitionHeadingBonusM * 0.5)
        }
        return 0.0
    }

    private func parseWayPoints(_ raw: String?) -> [(Double, Double)] {
        guard let raw, let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let arr = json as? [Any] else {
            return []
        }

        var out: [(Double, Double)] = []
        out.reserveCapacity(arr.count)
        for element in arr {
            guard let pair = element as? [Any], pair.count >= 2 else {
                continue
            }
            guard let lat = pair[0] as? Double,
                  let lon = pair[1] as? Double else {
                continue
            }
            out.append((lat, lon))
        }
        return out
    }

    private func polylineMetrics(lat: Double, lon: Double, points: [(Double, Double)]) -> PolylineMetrics? {
        if points.isEmpty {
            return nil
        }
        if points.count == 1 {
            let point = points[0]
            return PolylineMetrics(
                distanceM: haversineM(lat1: lat, lon1: lon, lat2: point.0, lon2: point.1),
                endpointProximityM: 0.0,
                distanceToStartM: 0.0,
                distanceToEndM: 0.0,
                localHeadingDeg: nil
            )
        }
        var best = Double.infinity
        var bestEndpointProximity = Double.infinity
        var bestLocalHeading: Double?
        let segmentLengths = zip(points, points.dropFirst()).map {
            haversineM(lat1: $0.0.0, lon1: $0.0.1, lat2: $0.1.0, lon2: $0.1.1)
        }
        let totalLength = segmentLengths.reduce(0.0, +)
        var cumulativeLength = 0.0
        var bestAlongPolylineM = 0.0
        for i in 0..<(points.count - 1) {
            let p1 = points[i]
            let p2 = points[i + 1]
            let projection = pointToSegmentProjection(
                lat: lat,
                lon: lon,
                lat1: p1.0,
                lon1: p1.1,
                lat2: p2.0,
                lon2: p2.1
            )
            if projection.distanceM < best {
                best = projection.distanceM
                let alongPolylineM = cumulativeLength + (projection.fraction * segmentLengths[i])
                bestAlongPolylineM = alongPolylineM
                bestEndpointProximity = min(alongPolylineM, max(totalLength - alongPolylineM, 0.0))
                bestLocalHeading = axisHeadingDeg(from: p1.0, lon1: p1.1, to: p2.0, lon2: p2.1)
            }
            cumulativeLength += segmentLengths[i]
        }
        guard best.isFinite else {
            return nil
        }
        return PolylineMetrics(
            distanceM: best,
            endpointProximityM: bestEndpointProximity,
            distanceToStartM: bestAlongPolylineM,
            distanceToEndM: max(totalLength - bestAlongPolylineM, 0.0),
            localHeadingDeg: bestLocalHeading
        )
    }

    private func endpointHeadingDeg(points: [(Double, Double)], atStart: Bool) -> Double? {
        guard points.count >= 2 else {
            return nil
        }
        if atStart {
            for index in 0..<(points.count - 1) {
                let current = points[index]
                let next = points[index + 1]
                if let heading = axisHeadingDeg(from: current.0, lon1: current.1, to: next.0, lon2: next.1) {
                    return heading
                }
            }
            return nil
        }
        for index in stride(from: points.count - 1, through: 1, by: -1) {
            let previous = points[index - 1]
            let current = points[index]
            if let heading = axisHeadingDeg(from: previous.0, lon1: previous.1, to: current.0, lon2: current.1) {
                return heading
            }
        }
        return nil
    }

    private func pointToSegmentProjection(
        lat: Double,
        lon: Double,
        lat1: Double,
        lon1: Double,
        lat2: Double,
        lon2: Double
    ) -> (distanceM: Double, fraction: Double) {
        let origin = toXYMeters(lat: lat, lon: lon, originLat: lat, originLon: lon)
        let start = toXYMeters(lat: lat1, lon: lon1, originLat: lat, originLon: lon)
        let end = toXYMeters(lat: lat2, lon: lon2, originLat: lat, originLon: lon)
        let dx = end.x - start.x
        let dy = end.y - start.y

        if dx == 0.0 && dy == 0.0 {
            return (hypot(origin.x - start.x, origin.y - start.y), 0.0)
        }
        let tNumerator = (origin.x - start.x) * dx + (origin.y - start.y) * dy
        let tDenominator = (dx * dx) + (dy * dy)
        let t = min(max(tNumerator / tDenominator, 0.0), 1.0)
        let projectionX = start.x + (t * dx)
        let projectionY = start.y + (t * dy)
        return (hypot(origin.x - projectionX, origin.y - projectionY), t)
    }

    private func toXYMeters(lat: Double, lon: Double, originLat: Double, originLon: Double) -> (x: Double, y: Double) {
        let metersPerDegLat = 111_132.0
        let metersPerDegLon = 111_320.0 * cos(originLat * .pi / 180.0)
        let x = (lon - originLon) * metersPerDegLon
        let y = (lat - originLat) * metersPerDegLat
        return (x, y)
    }

    private func isBetterCandidate(_ lhs: WayCandidate, than rhs: WayCandidate) -> Bool {
        if lhs.score != rhs.score {
            return lhs.score < rhs.score
        }
        if lhs.distanceM != rhs.distanceM {
            return lhs.distanceM < rhs.distanceM
        }
        return (lhs.wayID ?? "~") < (rhs.wayID ?? "~")
    }

    private func isBetterDistanceCandidate(_ lhs: WayCandidate, than rhs: WayCandidate) -> Bool {
        if lhs.distanceM != rhs.distanceM {
            return lhs.distanceM < rhs.distanceM
        }
        if lhs.score != rhs.score {
            return lhs.score < rhs.score
        }
        if lhs.endpointProximityM != rhs.endpointProximityM {
            return lhs.endpointProximityM < rhs.endpointProximityM
        }
        return (lhs.wayID ?? "~") < (rhs.wayID ?? "~")
    }

    private enum ContinuityClass {
        case preferredWay
        case sameRef
        case linkedWay
        case recentWay
        case none
    }

    private func continuityPriority(_ continuityClass: ContinuityClass) -> Int {
        switch continuityClass {
        case .preferredWay:
            return 4
        case .sameRef:
            return 3
        case .linkedWay:
            return 2
        case .recentWay:
            return 1
        case .none:
            return 0
        }
    }

    static func candidateTraceContinuityBand(continuityClass: String) -> Int {
        switch continuityClass {
        case "preferredWay":
            return 0
        case "sameRef":
            return 1
        case "linkedWay":
            return 2
        case "recentWay":
            return 3
        default:
            return 4
        }
    }

    static func candidateTraceScore(
        geometryScore: Double,
        continuityClass: String,
        maxGeometryScore: Double
    ) -> Double {
        let bandWidth = max(maxGeometryScore, geometryScore) + 1.0
        return (Double(candidateTraceContinuityBand(continuityClass: continuityClass)) * bandWidth) + geometryScore
    }

    private func traceRankingScore(
        for candidate: WayCandidate,
        continuityClass: ContinuityClass,
        maxGeometryScore: Double
    ) -> Double {
        Self.candidateTraceScore(
            geometryScore: candidate.score,
            continuityClass: String(describing: continuityClass),
            maxGeometryScore: maxGeometryScore
        )
    }

    private func buildTraceRankedCandidates(
        from candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?
    ) -> [TraceRankedCandidate] {
        let maxGeometryScore = candidates.map(\.score).max() ?? 0.0
        let sorted = candidates
            .map { candidate -> (candidate: WayCandidate, continuity: ContinuityClass, portalEligible: Bool, corridorState: CandidateCorridorState?, tunnelSelectable: Bool, corridorSelectable: Bool, traceScore: Double) in
                let continuity = continuityClass(
                    for: candidate,
                    matchContext: matchContext,
                    wayLinks: wayLinks
                )
                let corridorState = candidateCorridorState(
                    for: candidate,
                    matchContext: matchContext,
                    wayLinks: wayLinks,
                    progressContext: progressContext
                )
                let portalEligible = isPortalEligibleTunnelCandidate(
                    candidate,
                    matchContext: matchContext,
                    wayLinks: wayLinks,
                    progressContext: progressContext,
                    accuracyBufferM: accuracyBufferM
                )
                let tunnelSelectable = isTunnelCandidateSelectable(
                    candidate,
                    matchContext: matchContext,
                    wayLinks: wayLinks,
                    progressContext: progressContext,
                    pairContext: pairContext,
                    accuracyBufferM: accuracyBufferM
                )
                let corridorSelectable = isCorridorCandidateSelectable(
                    candidate,
                    matchContext: matchContext,
                    wayLinks: wayLinks,
                    progressContext: progressContext,
                    pairContext: pairContext,
                    accuracyBufferM: accuracyBufferM,
                    horizontalAccuracyM: horizontalAccuracyM,
                    gpsSignalBars: gpsSignalBars
                )
                return (
                    candidate: candidate,
                    continuity: continuity,
                    portalEligible: portalEligible,
                    corridorState: corridorState,
                    tunnelSelectable: tunnelSelectable,
                    corridorSelectable: corridorSelectable,
                    traceScore: traceRankingScore(
                        for: candidate,
                        continuityClass: continuity,
                        maxGeometryScore: maxGeometryScore
                    )
                )
            }
            .sorted { lhs, rhs in
                if lhs.traceScore != rhs.traceScore {
                    return lhs.traceScore < rhs.traceScore
                }
                if lhs.candidate.distanceM != rhs.candidate.distanceM {
                    return lhs.candidate.distanceM < rhs.candidate.distanceM
                }
                return (lhs.candidate.wayID ?? "~") < (rhs.candidate.wayID ?? "~")
            }

        return sorted.enumerated().map { index, entry in
            TraceRankedCandidate(
                candidate: entry.candidate,
                continuity: entry.continuity,
                portalEligible: entry.portalEligible,
                corridorState: entry.corridorState,
                tunnelSelectable: entry.tunnelSelectable,
                corridorSelectable: entry.corridorSelectable,
                traceScore: entry.traceScore,
                traceRank: index + 1
            )
        }
    }

    private func buildBaselineTraceRankedCandidates(
        from candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> [TraceRankedCandidate] {
        let maxDistance = candidates.map(\.distanceM).max() ?? 0.0
        let sorted = candidates
            .map { candidate -> (candidate: WayCandidate, continuity: ContinuityClass, traceScore: Double) in
                let continuity = continuityClass(
                    for: candidate,
                    matchContext: matchContext,
                    wayLinks: wayLinks
                )
                return (
                    candidate: candidate,
                    continuity: continuity,
                    traceScore: Self.candidateTraceScore(
                        geometryScore: candidate.distanceM,
                        continuityClass: String(describing: continuity),
                        maxGeometryScore: maxDistance
                    )
                )
            }
            .sorted { lhs, rhs in
                if lhs.traceScore != rhs.traceScore {
                    return lhs.traceScore < rhs.traceScore
                }
                if lhs.candidate.score != rhs.candidate.score {
                    return lhs.candidate.score < rhs.candidate.score
                }
                return (lhs.candidate.wayID ?? "~") < (rhs.candidate.wayID ?? "~")
            }

        return sorted.enumerated().map { index, entry in
            TraceRankedCandidate(
                candidate: entry.candidate,
                continuity: entry.continuity,
                portalEligible: false,
                corridorState: nil,
                tunnelSelectable: true,
                corridorSelectable: true,
                traceScore: entry.traceScore,
                traceRank: index + 1
            )
        }
    }

    private func top2TraceMargin(_ candidates: [TraceRankedCandidate]) -> Double {
        guard candidates.count >= 2 else {
            return 0.0
        }
        return candidates[1].traceScore - candidates[0].traceScore
    }

    private func selectThreeWayGateCandidate(
        from candidates: [TraceRankedCandidate],
        currentSelected: WayCandidate?,
        miniHMMSelected: WayCandidate?,
        usedMiniHMM: Bool,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        top2Margin: Double
    ) -> ThreeWayGateSelection? {
        let eligibleCandidates = candidates.filter(\.corridorSelectable)
        guard let currentTrace = traceCandidate(matching: normalizedWayID(currentSelected?.wayID), in: eligibleCandidates),
              let distanceTrace = lowestDistanceTraceCandidate(from: eligibleCandidates),
              let endpointTrace = lowestEndpointTraceCandidate(from: eligibleCandidates) else {
            return nil
        }

        let uniqueExpertWayIDs = Set(
            [
                normalizedWayID(currentTrace.candidate.wayID),
                normalizedWayID(distanceTrace.candidate.wayID),
                normalizedWayID(endpointTrace.candidate.wayID),
            ].compactMap { $0 }
        )
        guard uniqueExpertWayIDs.count > 1 else {
            return nil
        }

        let featureValues = threeWayGateFeatureValues(
            current: currentTrace,
            distance: distanceTrace,
            endpoint: endpointTrace,
            miniHMMSelected: miniHMMSelected,
            usedMiniHMM: usedMiniHMM,
            speedKmh: speedKmh,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars,
            top2Margin: top2Margin
        )
        let probabilities = DriveMatchThreeWayGateModel.probabilities(featureValues: featureValues)
        guard let predicted = probabilities.enumerated().max(by: { $0.element < $1.element }) else {
            return nil
        }

        let chosenTraceCandidate: TraceRankedCandidate
        switch predicted.offset {
        case 1:
            chosenTraceCandidate = distanceTrace
        case 2:
            chosenTraceCandidate = endpointTrace
        default:
            chosenTraceCandidate = currentTrace
        }
        let probabilitySummary = zip(DriveMatchThreeWayGateModel.classNames, probabilities)
            .map { name, value in
                "\(name)=\(String(format: "%.3f", value))"
            }
            .joined(separator: ",")
        return ThreeWayGateSelection(
            candidate: chosenTraceCandidate.candidate,
            className: DriveMatchThreeWayGateModel.classNames[predicted.offset],
            probabilitySummary: probabilitySummary,
            distanceWayID: distanceTrace.candidate.wayID,
            endpointWayID: endpointTrace.candidate.wayID
        )
    }

    private func shouldUseThreeWayGate(
        currentSelected: WayCandidate?,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        guard let currentSelected else {
            return false
        }
        guard matchContext.recentHypotheses.count >= 2 else {
            return false
        }
        if matchContext.isInTunnelMode {
            return false
        }
        return !isTruthyOSMTag(currentSelected.tunnel)
    }

    private func traceCandidate(
        matching wayID: String?,
        in candidates: [TraceRankedCandidate]
    ) -> TraceRankedCandidate? {
        guard let wayID else {
            return nil
        }
        return candidates.first { normalizedWayID($0.candidate.wayID) == wayID }
    }

    private func lowestDistanceTraceCandidate(
        from candidates: [TraceRankedCandidate]
    ) -> TraceRankedCandidate? {
        candidates.min { lhs, rhs in
            if lhs.candidate.distanceM != rhs.candidate.distanceM {
                return lhs.candidate.distanceM < rhs.candidate.distanceM
            }
            if lhs.traceRank != rhs.traceRank {
                return lhs.traceRank < rhs.traceRank
            }
            return lhs.traceScore < rhs.traceScore
        }
    }

    private func lowestEndpointTraceCandidate(
        from candidates: [TraceRankedCandidate]
    ) -> TraceRankedCandidate? {
        candidates.min { lhs, rhs in
            let lhsEndpoint = lhs.candidate.endpointProximityM.isFinite ? lhs.candidate.endpointProximityM : .infinity
            let rhsEndpoint = rhs.candidate.endpointProximityM.isFinite ? rhs.candidate.endpointProximityM : .infinity
            if lhsEndpoint != rhsEndpoint {
                return lhsEndpoint < rhsEndpoint
            }
            if lhs.candidate.distanceM != rhs.candidate.distanceM {
                return lhs.candidate.distanceM < rhs.candidate.distanceM
            }
            if lhs.traceRank != rhs.traceRank {
                return lhs.traceRank < rhs.traceRank
            }
            return lhs.traceScore < rhs.traceScore
        }
    }

    private func threeWayGateFeatureValues(
        current: TraceRankedCandidate,
        distance: TraceRankedCandidate,
        endpoint: TraceRankedCandidate,
        miniHMMSelected: WayCandidate?,
        usedMiniHMM: Bool,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        top2Margin: Double
    ) -> [String: Double] {
        let miniWayID = normalizedWayID(miniHMMSelected?.wayID)
        let speedValue = speedKmh ?? 0.0
        let horizontalAccuracyValue = horizontalAccuracyM ?? 0.0
        let gpsSignalBarsValue = Double(gpsSignalBars ?? 0)
        let currentEndpoint = current.candidate.endpointProximityM.isFinite ? current.candidate.endpointProximityM : .infinity
        let distanceEndpoint = distance.candidate.endpointProximityM.isFinite ? distance.candidate.endpointProximityM : .infinity
        let endpointEndpoint = endpoint.candidate.endpointProximityM.isFinite ? endpoint.candidate.endpointProximityM : .infinity

        var values: [String: Double] = [
            "bias": 1.0,
            "speed_kmh": speedValue,
            "horizontal_acc_m": horizontalAccuracyValue,
            "gps_signal_bars": gpsSignalBarsValue,
            "top2_margin": top2Margin,
            "used_mini_hmm": usedMiniHMM ? 1.0 : 0.0,
            "current_distance_m": current.candidate.distanceM,
            "distance_distance_m": distance.candidate.distanceM,
            "endpoint_distance_m": endpoint.candidate.distanceM,
            "current_endpoint_m": currentEndpoint,
            "distance_endpoint_m": distanceEndpoint,
            "endpoint_endpoint_m": endpointEndpoint,
            "current_score": current.traceScore,
            "distance_score": distance.traceScore,
            "endpoint_score": endpoint.traceScore,
            "current_rank": Double(current.traceRank),
            "distance_rank": Double(distance.traceRank),
            "endpoint_rank": Double(endpoint.traceRank),
            "current_low_endpoint": currentEndpoint <= 12.0 ? 1.0 : 0.0,
            "distance_low_endpoint": distanceEndpoint <= 12.0 ? 1.0 : 0.0,
            "endpoint_low_endpoint": endpointEndpoint <= 12.0 ? 1.0 : 0.0,
            "current_rank1": current.traceRank <= 1 ? 1.0 : 0.0,
            "distance_rank1": distance.traceRank <= 1 ? 1.0 : 0.0,
            "endpoint_rank1": endpoint.traceRank <= 1 ? 1.0 : 0.0,
            "current_mini_match": normalizedWayID(current.candidate.wayID) == miniWayID ? 1.0 : 0.0,
            "distance_mini_match": normalizedWayID(distance.candidate.wayID) == miniWayID ? 1.0 : 0.0,
            "endpoint_mini_match": normalizedWayID(endpoint.candidate.wayID) == miniWayID ? 1.0 : 0.0,
            "current_has_ref": (current.candidate.streetRef?.isEmpty == false) ? 1.0 : 0.0,
            "distance_has_ref": (distance.candidate.streetRef?.isEmpty == false) ? 1.0 : 0.0,
            "endpoint_has_ref": (endpoint.candidate.streetRef?.isEmpty == false) ? 1.0 : 0.0,
            "current_is_service": (current.candidate.service?.isEmpty == false) ? 1.0 : 0.0,
            "distance_is_service": (distance.candidate.service?.isEmpty == false) ? 1.0 : 0.0,
            "endpoint_is_service": (endpoint.candidate.service?.isEmpty == false) ? 1.0 : 0.0,
        ]

        threeWayGatePairFeatures(left: current, right: distance, prefix: "cd", into: &values)
        threeWayGatePairFeatures(left: current, right: endpoint, prefix: "ce", into: &values)
        threeWayGatePairFeatures(left: distance, right: endpoint, prefix: "de", into: &values)

        for (prefix, traceCandidate) in [("current", current), ("distance", distance), ("endpoint", endpoint)] {
            let continuityName = threeWayGateContinuityName(traceCandidate.continuity)
            for name in ["preferredWay", "sameRef", "linkedWay", "recentWay", "none"] {
                values["\(prefix)_cont_\(name)"] = continuityName == name ? 1.0 : 0.0
            }
        }
        return values
    }

    private func threeWayGatePairFeatures(
        left: TraceRankedCandidate,
        right: TraceRankedCandidate,
        prefix: String,
        into values: inout [String: Double]
    ) {
        let leftEndpoint = left.candidate.endpointProximityM.isFinite ? left.candidate.endpointProximityM : .infinity
        let rightEndpoint = right.candidate.endpointProximityM.isFinite ? right.candidate.endpointProximityM : .infinity
        let leftContinuity = threeWayGateContinuityName(left.continuity)
        let rightContinuity = threeWayGateContinuityName(right.continuity)
        let leftRef = left.candidate.streetRef ?? ""
        let rightRef = right.candidate.streetRef ?? ""
        values["\(prefix)_distance_advantage_m"] = left.candidate.distanceM - right.candidate.distanceM
        values["\(prefix)_score_advantage"] = left.traceScore - right.traceScore
        values["\(prefix)_endpoint_advantage_m"] = leftEndpoint - rightEndpoint
        values["\(prefix)_rank_advantage"] = Double(left.traceRank - right.traceRank)
        values["\(prefix)_band_advantage"] = threeWayGateContinuityBand(left.continuity) - threeWayGateContinuityBand(right.continuity)
        values["\(prefix)_same_ref"] = (!leftRef.isEmpty && leftRef == rightRef) ? 1.0 : 0.0
        values["\(prefix)_same_highway"] = threeWayGateHighwayBucket(left.candidate.highway) == threeWayGateHighwayBucket(right.candidate.highway) ? 1.0 : 0.0
        values["\(prefix)_same_continuity"] = leftContinuity == rightContinuity ? 1.0 : 0.0
    }

    private func threeWayGateContinuityName(_ continuity: ContinuityClass) -> String {
        switch continuity {
        case .preferredWay:
            return "preferredWay"
        case .sameRef:
            return "sameRef"
        case .linkedWay:
            return "linkedWay"
        case .recentWay:
            return "recentWay"
        case .none:
            return "none"
        }
    }

    private func threeWayGateContinuityBand(_ continuity: ContinuityClass) -> Double {
        switch continuity {
        case .preferredWay:
            return 0.0
        case .sameRef:
            return 1.0
        case .linkedWay:
            return 2.0
        case .recentWay:
            return 3.0
        case .none:
            return 4.0
        }
    }

    private func threeWayGateHighwayBucket(_ highway: String?) -> String {
        switch (highway ?? "").lowercased() {
        case "primary", "secondary", "residential", "tertiary", "unclassified", "service":
            return (highway ?? "").lowercased()
        default:
            return "other"
        }
    }

    private func normalizedMatchContext(
        from matchContext: WayMatchContext?,
        fallbackPreferredWayID: String?,
        ageOutStaleRefContinuity: Bool
    ) -> NormalizedMatchContext {
        let preferredWayID = normalizedWayID(matchContext?.preferredWayID) ?? normalizedWayID(fallbackPreferredWayID)
        var recentWayHistory: [String] = []
        for rawWayID in matchContext?.recentWayIDs ?? [] {
            guard let wayID = normalizedWayID(rawWayID) else {
                continue
            }
            recentWayHistory.removeAll(where: { $0 == wayID })
            recentWayHistory.append(wayID)
        }
        var recentWayIDs = Set(recentWayHistory)
        if let preferredWayID {
            recentWayHistory.removeAll(where: { $0 == preferredWayID })
            recentWayHistory.insert(preferredWayID, at: 0)
            recentWayIDs.insert(preferredWayID)
        }

        let activeStreetRefTokens = Set(Self.normalizedRefTokens(matchContext?.activeStreetRef))
        let consecutiveNoRefMatchCount = matchContext?.consecutiveNoRefMatchCount ?? 0
        let staleRefContinuityExpired =
            ageOutStaleRefContinuity &&
            activeStreetRefTokens.isEmpty &&
            consecutiveNoRefMatchCount >= Self.simpleStreetNameFallbackMinNoRefMatches

        var preferredStreetRefs = Set(Self.normalizedRefTokens(matchContext?.preferredStreetRef))
        if preferredStreetRefs.isEmpty {
            preferredStreetRefs = Set(
                (matchContext?.recentStreetRefs ?? []).flatMap { Self.normalizedRefTokens($0) }
            )
        }
        if staleRefContinuityExpired {
            preferredStreetRefs.removeAll()
        }
        let activeStreetNameTokens = Set(Self.normalizedStreetNameTokens(matchContext?.preferredStreetName))
        var recentStreetRefs = Set(
            (matchContext?.recentStreetRefs ?? []).flatMap { Self.normalizedRefTokens($0) }
        )
        if staleRefContinuityExpired {
            recentStreetRefs.removeAll()
        }
        recentStreetRefs.formUnion(preferredStreetRefs)
        let recentTunnelCandidateWayIDs = Set(
            (matchContext?.recentTunnelCandidateWayIDs ?? []).compactMap { normalizedWayID($0) }
        )
        let recentTunnelCandidateRefs = Set(
            (matchContext?.recentTunnelCandidateRefs ?? []).flatMap { Self.normalizedRefTokens($0) }
        )
        let recentTunnelApproachWayIDs = Set(
            (matchContext?.recentTunnelApproachWayIDs ?? []).compactMap { normalizedWayID($0) }
        )
        let recentTunnelApproachRefs = Set(
            (matchContext?.recentTunnelApproachRefs ?? []).flatMap { Self.normalizedRefTokens($0) }
        )
        let recentHypothesisLimit = max(Self.miniHMMBeamWidth, Self.simpleSequenceViterbiBeamWidth)
        let recentHypotheses = Array((matchContext?.recentHypotheses ?? []).prefix(recentHypothesisLimit))

        return NormalizedMatchContext(
            preferredWayID: preferredWayID,
            preferredHighway: matchContext?.preferredHighway,
            preferredEndpointProximityM: matchContext?.preferredEndpointProximityM,
            recentWayIDs: recentWayIDs,
            recentWayHistory: recentWayHistory,
            recentFixes: Array((matchContext?.recentFixes ?? []).prefix(Self.simpleSequenceViterbiWindowFixCount)),
            sameRefUrbanReleaseStreak: matchContext?.sameRefUrbanReleaseStreak ?? 0,
            preferredStreetRefs: preferredStreetRefs,
            activeStreetRefTokens: activeStreetRefTokens,
            activeStreetNameTokens: activeStreetNameTokens,
            recentStreetRefs: recentStreetRefs,
            consecutiveNoRefMatchCount: consecutiveNoRefMatchCount,
            recentTunnelCandidateWayIDs: recentTunnelCandidateWayIDs,
            recentTunnelCandidateRefs: recentTunnelCandidateRefs,
            recentTunnelApproachWayIDs: recentTunnelApproachWayIDs,
            recentTunnelApproachRefs: recentTunnelApproachRefs,
            tunnelApproachFixCount: matchContext?.tunnelApproachFixCount ?? 0,
            tunnelApproachBaselineAccuracyM: matchContext?.tunnelApproachBaselineAccuracyM,
            tunnelApproachBaselineSignalBars: matchContext?.tunnelApproachBaselineSignalBars,
            recentHypotheses: recentHypotheses,
            matchedFixCount: matchContext?.matchedFixCount ?? 0,
            hadRecentGPSSignalLoss: matchContext?.hadRecentGPSSignalLoss ?? false,
            isInTunnelMode: matchContext?.isInTunnelMode ?? false,
            isInMotorwayMode: matchContext?.isInMotorwayMode ?? false,
            activeCorridorState: matchContext?.activeCorridorState,
            approachCorridorState: matchContext?.approachCorridorState,
            approachCorridorFixCount: matchContext?.approachCorridorFixCount ?? 0,
            approachCorridorStartDepthM: matchContext?.approachCorridorStartDepthM,
            approachCorridorStartDepthNodes: matchContext?.approachCorridorStartDepthNodes
        )
    }

    private func baselineModeFilteredCandidates(
        from candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> [WayCandidate] {
        guard let preferredWayID = matchContext.preferredWayID else {
            return candidates
        }

        if matchContext.isInTunnelMode {
            let filtered = candidates.filter { candidate in
                if isTruthyOSMTag(candidate.tunnel) {
                    return true
                }
                return areLinkedWays(
                    preferredWayID,
                    normalizedWayID(candidate.wayID),
                    wayLinks: wayLinks
                ) && candidate.endpointProximityM <= Self.baselineTunnelExitEndpointThresholdM
            }
            return filtered.isEmpty ? candidates : filtered
        }

        if matchContext.isInMotorwayMode {
            let preferredHighway = (matchContext.preferredHighway ?? "").lowercased()
            let filtered = candidates.filter { candidate in
                let candidateHighway = (candidate.highway ?? "").lowercased()
                let candidateWayID = normalizedWayID(candidate.wayID)
                switch preferredHighway {
                case "motorway_link":
                    if candidateHighway == "motorway" || candidateHighway == "motorway_link" {
                        return true
                    }
                    return areLinkedWays(preferredWayID, candidateWayID, wayLinks: wayLinks) &&
                        candidate.endpointProximityM <= Self.baselineMotorwayGateEndpointThresholdM
                default:
                    if candidateHighway == "motorway" {
                        return true
                    }
                    if candidateHighway == "motorway_link" {
                        return areLinkedWays(preferredWayID, candidateWayID, wayLinks: wayLinks)
                    }
                    return false
                }
            }
            return filtered.isEmpty ? candidates : filtered
        }

        return candidates
    }

    private func bestBaselineContinuityCandidate(
        in candidates: [WayCandidate],
        continuity: ContinuityClass,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> WayCandidate? {
        candidates
            .filter {
                continuityClass(
                    for: $0,
                    matchContext: matchContext,
                    wayLinks: wayLinks
                ) == continuity
            }
            .sorted { isBetterDistanceCandidate($0, than: $1) }
            .first
    }

    private func shouldKeepBaselineContinuityCandidate(
        _ continuityCandidate: WayCandidate,
        over bestCandidate: WayCandidate,
        accuracyBufferM: Double,
        distanceSlackM: Double
    ) -> Bool {
        let allowedDistanceSlack = max(distanceSlackM, accuracyBufferM * 0.35)
        let allowedGeometrySlack = max(distanceSlackM * 2.0, accuracyBufferM)
        return continuityCandidate.distanceM <= bestCandidate.distanceM + allowedDistanceSlack &&
            continuityCandidate.score <= bestCandidate.score + allowedGeometrySlack
    }

    private func baselineTurnTransitionCandidate(
        in candidates: [WayCandidate],
        currentWayID: String?,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double
    ) -> WayCandidate? {
        guard let currentWayID,
              let currentCandidate = candidates.first(where: { normalizedWayID($0.wayID) == currentWayID }),
              let bestCandidate = candidates.sorted(by: { isBetterDistanceCandidate($0, than: $1) }).first else {
            return nil
        }
        let fromAxisHeading = axisHeadingDeg(for: currentCandidate)
        return candidates
            .filter { normalizedWayID($0.wayID) != currentWayID }
            .sorted { isBetterDistanceCandidate($0, than: $1) }
            .first { candidate in
                guard candidate.distanceM <= bestCandidate.distanceM + max(Self.baselineTurnDistanceSlackM, accuracyBufferM * 0.5),
                      let evidence = transitionHeadingEvidence(
                        fromAxisHeadingDeg: fromAxisHeading,
                        fromEndpointProximityM: currentCandidate.endpointProximityM,
                        to: candidate,
                        observedHeadingDeg: observedHeadingDeg,
                        speedKmh: speedKmh
                      ) else {
                    return false
                }
                return evidence.nearEndpoint &&
                    evidence.meaningfulTurn &&
                    evidence.candidateClearlyBetterAligned &&
                    evidence.speedKmh <= Self.baselineTurnTransitionMaxSpeedKmh
            }
    }

    private func selectConnectedBaselineCandidate(
        from candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double
    ) -> (selected: WayCandidate?, traceRankedCandidates: [TraceRankedCandidate], selectionTrace: [MatchSelectionTrace]) {
        let filteredCandidates = baselineModeFilteredCandidates(
            from: candidates,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        let rankedCandidates = filteredCandidates.sorted { isBetterDistanceCandidate($0, than: $1) }
        let traceRankedCandidates = buildBaselineTraceRankedCandidates(
            from: rankedCandidates,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        guard let bestCandidate = rankedCandidates.first else {
            return (
                selected: nil,
                traceRankedCandidates: traceRankedCandidates,
                selectionTrace: [MatchSelectionTrace(step: "baseline", detail: "no selectable candidates")]
            )
        }

        var selectionTrace: [MatchSelectionTrace] = []
        if filteredCandidates.count != candidates.count {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "baseline_mode_gate",
                    detail: "filtered \(candidates.count - filteredCandidates.count) candidates due to tunnel/motorway mode"
                )
            )
        }

        let preferredCandidate = bestBaselineContinuityCandidate(
            in: rankedCandidates,
            continuity: .preferredWay,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        let sameRefCandidate = bestBaselineContinuityCandidate(
            in: rankedCandidates,
            continuity: .sameRef,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        let turnCandidate = baselineTurnTransitionCandidate(
            in: rankedCandidates,
            currentWayID: matchContext.preferredWayID,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            accuracyBufferM: accuracyBufferM
        )

        let selected: WayCandidate
        if let turnCandidate {
            selected = turnCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "baseline_turn_gate",
                    detail: "selected connected turn \(turnCandidate.wayID ?? "nil") over \(bestCandidate.wayID ?? "nil") after low-speed heading change"
                )
            )
        } else if let preferredCandidate,
                  normalizedWayID(preferredCandidate.wayID) != normalizedWayID(bestCandidate.wayID),
                  shouldKeepBaselineContinuityCandidate(
                    preferredCandidate,
                    over: bestCandidate,
                    accuracyBufferM: accuracyBufferM,
                    distanceSlackM: Self.baselinePreferredDistanceSlackM
                  ) {
            selected = preferredCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "baseline_preferred_hold",
                    detail: "kept preferred \(preferredCandidate.wayID ?? "nil") over nearest \(bestCandidate.wayID ?? "nil")"
                )
            )
        } else if let sameRefCandidate,
                  normalizedWayID(sameRefCandidate.wayID) != normalizedWayID(bestCandidate.wayID),
                  shouldKeepBaselineContinuityCandidate(
                    sameRefCandidate,
                    over: bestCandidate,
                    accuracyBufferM: accuracyBufferM,
                    distanceSlackM: Self.baselineSameRefDistanceSlackM
                  ) {
            selected = sameRefCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "baseline_same_ref_hold",
                    detail: "kept same-ref \(sameRefCandidate.wayID ?? "nil") over nearest \(bestCandidate.wayID ?? "nil")"
                )
            )
        } else {
            selected = bestCandidate
        }

        selectionTrace.append(
            MatchSelectionTrace(
                step: "baseline",
                detail: "selected \(selected.wayID ?? "nil") nearest=\(bestCandidate.wayID ?? "nil") model=connected_baseline"
            )
        )
        return (
            selected: selected,
            traceRankedCandidates: traceRankedCandidates,
            selectionTrace: selectionTrace
        )
    }

    private func selectSimpleSpeedRefHeuristicCandidate(
        from candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        urbanSameRefReleaseEnabled: Bool,
        useStreetNameFallbackContinuity: Bool,
        useGuardedStreetNameFallbackContinuity: Bool,
        nodeDirectionAwareLowSpeedJunctionRelease: Bool,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext
    ) -> (selected: WayCandidate?, traceRankedCandidates: [TraceRankedCandidate], selectionTrace: [MatchSelectionTrace]) {
        let poorSignalThresholdM = 10.0
        let lowSpeedThresholdKmh = Self.simpleSameRefHoldSpeedThresholdKmh
        let poorSignal = (horizontalAccuracyM ?? Double.infinity) > poorSignalThresholdM
        let lowSpeedAccurateGPS = (speedKmh ?? 0.0) < lowSpeedThresholdKmh &&
            (horizontalAccuracyM ?? Double.infinity) < poorSignalThresholdM

        var selectionTrace: [MatchSelectionTrace] = []
        let legacyTunnelCandidates = candidates.filter {
            isLegacyTunnelCandidateSelectable(
                $0,
                matchContext: matchContext,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
            )
        }
        let tunnelSelectableCandidates: [WayCandidate]
        if legacyTunnelCandidates.isEmpty,
           shouldFallbackToTunnelOnlyCandidateSet(
                candidates,
                matchContext: matchContext
           ) {
            tunnelSelectableCandidates = candidates
        } else {
            tunnelSelectableCandidates = legacyTunnelCandidates
        }
        if tunnelSelectableCandidates.count != candidates.count {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_tunnel_selectability_gate",
                    detail: "filtered \(candidates.count - tunnelSelectableCandidates.count) tunnel candidates without portal or continuity support"
                )
            )
        }

        let ambiguityFilteredCandidates = suppressAmbiguousSurfaceToTunnelEntries(
            in: tunnelSelectableCandidates,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext,
            accuracyBufferM: accuracyBufferM,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        )
        let corridorAwareCandidates = ambiguityFilteredCandidates.isEmpty ? tunnelSelectableCandidates : ambiguityFilteredCandidates
        if corridorAwareCandidates.count != tunnelSelectableCandidates.count {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_tunnel_ambiguity_gate",
                    detail: "filtered \(tunnelSelectableCandidates.count - corridorAwareCandidates.count) ambiguous surface-to-tunnel portal candidates"
                )
            )
        }

        let filteredCandidates: [WayCandidate]
        if matchContext.isInTunnelMode && poorSignal {
            let tunnelCandidates = corridorAwareCandidates.filter { isTruthyOSMTag($0.tunnel) }
            filteredCandidates = tunnelCandidates.isEmpty ? corridorAwareCandidates : tunnelCandidates
        } else {
            filteredCandidates = corridorAwareCandidates
        }

        let rankedCandidates = filteredCandidates.sorted { isBetterDistanceCandidate($0, than: $1) }
        let traceRankedCandidates = buildBaselineTraceRankedCandidates(
            from: rankedCandidates,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        let geometryRanksByWayID = Dictionary(
            uniqueKeysWithValues: rankedCandidates.enumerated().compactMap { index, candidate in
                normalizedWayID(candidate.wayID).map { ($0, index + 1) }
            }
        )
        let traceRanksByWayID = Dictionary(
            uniqueKeysWithValues: traceRankedCandidates.compactMap { entry in
                normalizedWayID(entry.candidate.wayID).map { ($0, entry.traceRank) }
            }
        )
        guard let bestCandidate = rankedCandidates.first else {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_speed_ref_heuristic",
                    detail: "no selectable candidates"
                )
            )
            return (
                selected: nil,
                traceRankedCandidates: traceRankedCandidates,
                selectionTrace: selectionTrace
            )
        }

        if filteredCandidates.count != candidates.count {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_tunnel_hold_gate",
                    detail: "kept \(filteredCandidates.count) tunnel candidates while horizontal_accuracy_m=\(String(format: "%.1f", horizontalAccuracyM ?? Double.infinity)) remained above \(String(format: "%.1f", poorSignalThresholdM))"
                )
            )
        }

        let continuityIdentity: (tokens: Set<String>, source: SimpleContinuityIdentitySource)
        let previousContinuityCandidate: WayCandidate?
        if useGuardedStreetNameFallbackContinuity,
           let guardedContinuity = preferredGuardedStreetNameContinuityCandidate(
               rankedCandidates: rankedCandidates,
               bestCandidate: bestCandidate,
               matchContext: matchContext,
               horizontalAccuracyM: horizontalAccuracyM
           ) {
            continuityIdentity = (guardedContinuity.tokens, .streetName)
            previousContinuityCandidate = guardedContinuity.candidate
            selectionTrace.append(guardedContinuity.trace)
        } else {
            continuityIdentity = preferredSimpleContinuityIdentity(
                for: matchContext,
                useStreetNameFallbackContinuity: useStreetNameFallbackContinuity
            )
            let preferredContinuity = preferredSimpleContinuityCandidate(
                rankedCandidates: rankedCandidates,
                continuityIdentity: continuityIdentity,
                matchContext: matchContext,
                useStreetNameFallbackContinuity: useStreetNameFallbackContinuity || useGuardedStreetNameFallbackContinuity
            )
            previousContinuityCandidate = preferredContinuity?.candidate
            if let trace = preferredContinuity?.trace {
                selectionTrace.append(trace)
            }
        }

        let urbanReleasePressureActive: Bool
        if urbanSameRefReleaseEnabled,
           let speedKmh,
           speedKmh.isFinite,
           speedKmh >= lowSpeedThresholdKmh,
           speedKmh <= Self.simpleSameRefUrbanReleaseMaxSpeedKmh,
           let horizontalAccuracyM,
           horizontalAccuracyM.isFinite,
           horizontalAccuracyM <= Self.simpleSameRefUrbanReleaseMaxAccuracyM,
           let previousContinuityCandidate,
           normalizedWayID(previousContinuityCandidate.wayID) != normalizedWayID(bestCandidate.wayID),
           shouldEnableUrbanSameRefRelease(
               sameRefCandidate: previousContinuityCandidate,
               bestCandidate: bestCandidate
           ) {
            urbanReleasePressureActive = true
        } else {
            urbanReleasePressureActive = false
        }
        let nextUrbanReleaseStreak = urbanReleasePressureActive ? min(matchContext.sameRefUrbanReleaseStreak + 1, 8) : 0
        let lowSpeedJunctionRelease: LowSpeedSameRefJunctionRelease?
        let lowSpeedJunctionProbeTrace: MatchSelectionTrace?
        if let speedKmh,
           speedKmh.isFinite,
           speedKmh < lowSpeedThresholdKmh,
           continuityIdentity.source == .ref,
           let previousContinuityCandidate {
            if nodeDirectionAwareLowSpeedJunctionRelease {
                let nodeDirectionAnalysis = lowSpeedSameRefNodeDirectionJunctionAnalysis(
                    in: rankedCandidates,
                    currentCandidate: previousContinuityCandidate,
                    bestCandidate: bestCandidate,
                    observedHeadingDeg: observedHeadingDeg,
                    speedKmh: speedKmh,
                    accuracyBufferM: accuracyBufferM,
                    matchContext: matchContext,
                    wayLinks: wayLinks
                )
                lowSpeedJunctionRelease = nodeDirectionAnalysis.release
                lowSpeedJunctionProbeTrace = nodeDirectionAnalysis.probe.map { probe in
                    MatchSelectionTrace(
                        step: "simple_low_speed_same_ref_probe",
                        detail: lowSpeedSameRefJunctionProbeDetail(
                            probe: probe,
                            currentCandidate: previousContinuityCandidate,
                            bestCandidate: bestCandidate,
                            geometryRanksByWayID: geometryRanksByWayID,
                            traceRanksByWayID: traceRanksByWayID
                        )
                    )
                }
            } else {
                lowSpeedJunctionRelease = lowSpeedSameRefJunctionTransitionCandidate(
                    in: rankedCandidates,
                    currentCandidate: previousContinuityCandidate,
                    bestCandidate: bestCandidate,
                    observedHeadingDeg: observedHeadingDeg,
                    speedKmh: speedKmh,
                    accuracyBufferM: accuracyBufferM,
                    matchContext: matchContext,
                    wayLinks: wayLinks
                )
                lowSpeedJunctionProbeTrace = nil
            }
        } else {
            lowSpeedJunctionRelease = nil
            lowSpeedJunctionProbeTrace = nil
        }

        let selected: WayCandidate
        if let lowSpeedJunctionRelease {
            selected = lowSpeedJunctionRelease.candidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_low_speed_same_ref_junction_release",
                    detail: "released same-ref \(previousContinuityCandidate?.wayID ?? "nil") for linked turn \(lowSpeedJunctionRelease.candidate.wayID ?? "nil") via anchor \(lowSpeedJunctionRelease.anchorCandidate.wayID ?? "nil") at speed_kmh=\(String(format: "%.1f", speedKmh ?? 0.0)) candidate_m=\(String(format: "%.1f", lowSpeedJunctionRelease.candidate.distanceM))"
                )
            )
        } else if let speedKmh, speedKmh >= lowSpeedThresholdKmh, let previousContinuityCandidate {
            if urbanSameRefReleaseEnabled,
               urbanReleasePressureActive,
               nextUrbanReleaseStreak >= Self.simpleSameRefUrbanReleaseRequiredStreak {
                selected = bestCandidate
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "simple_same_ref_urban_release",
                        detail: "released \(continuityIdentity.source.traceLabel) \(previousContinuityCandidate.wayID ?? "nil") for nearest \(bestCandidate.wayID ?? "nil") speed_kmh=\(String(format: "%.1f", speedKmh)) nearest_m=\(String(format: "%.1f", bestCandidate.distanceM)) continuity_m=\(String(format: "%.1f", previousContinuityCandidate.distanceM)) streak=\(nextUrbanReleaseStreak)"
                    )
                )
            } else {
                selected = previousContinuityCandidate
                if normalizedWayID(previousContinuityCandidate.wayID) != normalizedWayID(bestCandidate.wayID) {
                    let step: String
                    if urbanSameRefReleaseEnabled && urbanReleasePressureActive {
                        step = continuityIdentity.source == .streetName ? "simple_same_name_urban_hold" : "simple_same_ref_urban_hold"
                    } else {
                        step = continuityIdentity.source == .streetName ? "simple_same_name_hold" : "simple_same_ref_hold"
                    }
                    let detail: String
                    if urbanSameRefReleaseEnabled && urbanReleasePressureActive {
                        detail = "kept \(continuityIdentity.source.traceLabel) \(previousContinuityCandidate.wayID ?? "nil") over nearest \(bestCandidate.wayID ?? "nil") at speed_kmh=\(String(format: "%.1f", speedKmh)) nearest_m=\(String(format: "%.1f", bestCandidate.distanceM)) continuity_m=\(String(format: "%.1f", previousContinuityCandidate.distanceM)) streak=\(nextUrbanReleaseStreak)"
                    } else {
                        detail = "kept \(continuityIdentity.source.traceLabel) \(previousContinuityCandidate.wayID ?? "nil") over nearest \(bestCandidate.wayID ?? "nil") at speed_kmh=\(String(format: "%.1f", speedKmh))"
                    }
                    selectionTrace.append(
                        MatchSelectionTrace(
                            step: step,
                            detail: detail
                        )
                    )
                }
            }
        } else {
            selected = bestCandidate
        }

        if let lowSpeedJunctionProbeTrace {
            selectionTrace.append(lowSpeedJunctionProbeTrace)
        }

        if urbanSameRefReleaseEnabled {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_same_ref_urban_release_streak",
                    detail: "\(nextUrbanReleaseStreak)"
                )
            )
        }

        let tunnelContinuityCandidate: WayCandidate? = {
            if let previousContinuityCandidate,
               isTruthyOSMTag(previousContinuityCandidate.tunnel) {
                return previousContinuityCandidate
            }
            if !continuityIdentity.tokens.isEmpty,
               let continuityMatchedTunnel = rankedCandidates.first(where: { candidate in
                   guard isTruthyOSMTag(candidate.tunnel) else {
                       return false
                   }
                   let candidateTokens = continuityTokens(
                       for: candidate,
                       source: continuityIdentity.source,
                       useStreetNameFallbackContinuity: useStreetNameFallbackContinuity || useGuardedStreetNameFallbackContinuity
                   )
                   return !candidateTokens.isEmpty &&
                       !candidateTokens.isDisjoint(with: continuityIdentity.tokens)
               }) {
                return continuityMatchedTunnel
            }
            return rankedCandidates.first(where: { isTruthyOSMTag($0.tunnel) })
        }()

        var finalSelected = selected
        if !matchContext.isInTunnelMode,
           !isTruthyOSMTag(finalSelected.tunnel),
           let tunnelContinuityCandidate,
           shouldPromoteTunnelEntry(
                tunnelCandidate: tunnelContinuityCandidate,
                over: finalSelected,
                matchContext: matchContext,
                wayLinks: wayLinks,
                progressContext: progressContext,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars,
                accuracyBufferM: accuracyBufferM
           ) {
            finalSelected = tunnelContinuityCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "tunnel_entry_gate",
                    detail: "promoted tunnel \(tunnelContinuityCandidate.wayID ?? "nil") over surface \(selected.wayID ?? "nil") on simple continuity path"
                )
            )
        } else if matchContext.isInTunnelMode,
                  !isTruthyOSMTag(finalSelected.tunnel),
                  let tunnelContinuityCandidate,
                  shouldKeepTunnelContinuity(
                    tunnelCandidate: tunnelContinuityCandidate,
                    over: finalSelected,
                    matchContext: matchContext,
                    wayLinks: wayLinks,
                    progressContext: progressContext,
                    pairContext: pairContext,
                    accuracyBufferM: accuracyBufferM,
                    horizontalAccuracyM: horizontalAccuracyM,
                    gpsSignalBars: gpsSignalBars
                  ) {
            finalSelected = tunnelContinuityCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "tunnel_exit_gate",
                    detail: "kept tunnel \(tunnelContinuityCandidate.wayID ?? "nil") and rejected surface exit \(selected.wayID ?? "nil") on simple continuity path"
                )
            )
        }
        if continuityIdentity.source == .ref,
           let previousContinuityCandidate,
           normalizedWayID(finalSelected.wayID) != normalizedWayID(previousContinuityCandidate.wayID),
           shouldSuppressImmediateSameRefBounce(
                candidate: finalSelected,
                over: previousContinuityCandidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
           ) {
            finalSelected = previousContinuityCandidate
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_same_ref_bounce_hold",
                    detail: "kept \(previousContinuityCandidate.wayID ?? "nil") over \(selected.wayID ?? "nil") to avoid immediate same-ref bounce"
                )
            )
        }

        let reason: String
        if lowSpeedJunctionRelease != nil {
            reason = "low_speed_same_ref_junction_release"
        } else if urbanSameRefReleaseEnabled,
           urbanReleasePressureActive,
           nextUrbanReleaseStreak >= Self.simpleSameRefUrbanReleaseRequiredStreak,
           normalizedWayID(finalSelected.wayID) == normalizedWayID(bestCandidate.wayID) {
            reason = continuityIdentity.source == .streetName
                ? "urban_same_name_distance_gap_release"
                : "urban_same_ref_distance_gap_release"
        } else if let speedKmh, speedKmh >= lowSpeedThresholdKmh, previousContinuityCandidate != nil {
            reason = continuityIdentity.source == .streetName ? "high_speed_same_name" : "high_speed_same_ref"
        } else if previousContinuityCandidate != nil {
            reason = continuityIdentity.source == .streetName ? "low_speed_same_name_release_distance" : "low_speed_same_ref_release_distance"
        } else if lowSpeedAccurateGPS {
            reason = "low_speed_good_gps_distance"
        } else if matchContext.isInTunnelMode && poorSignal {
            reason = "tunnel_hold_distance"
        } else {
            reason = "distance_fallback"
        }
        selectionTrace.append(
            MatchSelectionTrace(
                step: "simple_speed_ref_heuristic",
                detail: "selected \(finalSelected.wayID ?? "nil") nearest=\(bestCandidate.wayID ?? "nil") reason=\(reason) speed_kmh=\(String(format: "%.1f", speedKmh ?? 0.0)) hacc_m=\(String(format: "%.1f", horizontalAccuracyM ?? Double.infinity))"
            )
        )
        return (
            selected: finalSelected,
            traceRankedCandidates: traceRankedCandidates,
            selectionTrace: selectionTrace
        )
    }

    private func shouldFallbackToTunnelOnlyCandidateSet(
        _ candidates: [WayCandidate],
        matchContext: NormalizedMatchContext
    ) -> Bool {
        guard !candidates.isEmpty,
              !matchContext.isInTunnelMode,
              matchContext.preferredWayID == nil,
              !matchContext.hadRecentGPSSignalLoss,
              matchContext.recentTunnelCandidateWayIDs.isEmpty,
              matchContext.recentTunnelCandidateRefs.isEmpty,
              candidates.allSatisfy({ isTruthyOSMTag($0.tunnel) }) else {
            return false
        }
        return candidates.contains { !isServiceLikeTransitionCandidate($0) }
    }

    private func selectSimpleSequenceParticleCandidate(
        from candidates: [WayCandidate],
        heuristicSelected: WayCandidate?,
        matchContext: NormalizedMatchContext,
        observedHeadingDeg: Double?,
        speedKmh: Double?
    ) -> SimpleSequenceParticleSelection {
        guard let queryPoint = candidates.first?.queryPoint else {
            return SimpleSequenceParticleSelection(selected: heuristicSelected, traceRankedCandidates: [], hypotheses: [], selectionTrace: [])
        }
        let topologyFreeWayLinks = WayLinksContext(available: false, byWayID: [:])
        let fallbackMotionHeadingDeg = observedHeadingDeg ?? recentApproachHeadingDeg(
            matchContext: matchContext,
            queryPoint: queryPoint
        )
        let seedContext = simpleSequenceParticleSeedContext(
            candidates: candidates,
            matchContext: matchContext,
            limit: Self.miniHMMBeamWidth
        )
        var selectionTrace: [MatchSelectionTrace] = [
            MatchSelectionTrace(
                step: "simple_sequence_particle_seed",
                detail: "source=\(seedContext.source) count=\(seedContext.hypotheses.count) motion_heading_deg=\(fallbackMotionHeadingDeg.map { String(format: "%.1f", $0) } ?? "nil")"
            )
        ]

        var states: [SimpleSequenceParticleState] = []
        states.reserveCapacity(min(candidates.count, Self.maxTraceCandidateCount))
        for candidate in candidates.prefix(Self.maxTraceCandidateCount) {
            guard normalizedWayID(candidate.wayID) != nil else {
                continue
            }
            let emissionCost = simpleSequenceParticleEmissionCost(
                for: candidate,
                observedHeadingDeg: observedHeadingDeg,
                fallbackMotionHeadingDeg: fallbackMotionHeadingDeg
            )
            let transition = simpleSequenceParticleTransition(
                for: candidate,
                seedHypotheses: seedContext.hypotheses,
                observedHeadingDeg: fallbackMotionHeadingDeg,
                speedKmh: speedKmh,
                matchContext: matchContext,
                wayLinks: topologyFreeWayLinks
            )
            let continuity = continuityClass(
                for: candidate,
                matchContext: matchContext,
                wayLinks: topologyFreeWayLinks
            )
            states.append(
                SimpleSequenceParticleState(
                    candidate: candidate,
                    continuity: continuity,
                    cumulativeCost: emissionCost + transition.cost,
                    emissionCost: emissionCost,
                    transitionCost: transition.cost,
                    seedWayID: transition.seedWayID,
                    seedSource: transition.reason
                )
            )
        }

        states.sort { lhs, rhs in
            if lhs.cumulativeCost != rhs.cumulativeCost {
                return lhs.cumulativeCost < rhs.cumulativeCost
            }
            if lhs.emissionCost != rhs.emissionCost {
                return lhs.emissionCost < rhs.emissionCost
            }
            return (lhs.candidate.wayID ?? "~") < (rhs.candidate.wayID ?? "~")
        }

        let hypotheses = states.prefix(Self.miniHMMBeamWidth).compactMap { state in
            wayMatchHypothesis(
                from: state.candidate,
                cumulativeCost: state.cumulativeCost,
                emissionScore: state.emissionCost
            )
        }
        let traceRankedCandidates = states.enumerated().map { index, state in
            TraceRankedCandidate(
                candidate: state.candidate,
                continuity: state.continuity,
                portalEligible: false,
                corridorState: nil,
                tunnelSelectable: true,
                corridorSelectable: true,
                traceScore: state.cumulativeCost,
                traceRank: index + 1
            )
        }

        let particleSelected = states.first
        let heuristicWayID = normalizedWayID(heuristicSelected?.wayID)
        let heuristicCost = states.first(where: {
            normalizedWayID($0.candidate.wayID) == heuristicWayID
        })?.cumulativeCost ?? heuristicSelected?.score ?? Double.infinity

        let finalSelected: WayCandidate?
        if let particleSelected {
            if heuristicWayID == normalizedWayID(particleSelected.candidate.wayID) {
                finalSelected = heuristicSelected ?? particleSelected.candidate
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "simple_sequence_particle_agree",
                        detail: "particle and heuristic agreed on \(particleSelected.candidate.wayID ?? "nil") cost=\(String(format: "%.1f", particleSelected.cumulativeCost)) seed=\(particleSelected.seedWayID ?? "nil") reason=\(particleSelected.seedSource)"
                    )
                )
            } else if seedContext.hypotheses.isEmpty && observedHeadingDeg == nil && fallbackMotionHeadingDeg == nil {
                finalSelected = heuristicSelected ?? particleSelected.candidate
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "simple_sequence_particle_hold",
                        detail: "kept heuristic \(heuristicSelected?.wayID ?? "nil") over particle \(particleSelected.candidate.wayID ?? "nil") on cold start"
                    )
                )
            } else if particleSelected.cumulativeCost + Self.simpleSequenceParticleAdoptionSlackM < heuristicCost {
                finalSelected = particleSelected.candidate
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "simple_sequence_particle_switch",
                        detail: "switched heuristic \(heuristicSelected?.wayID ?? "nil") -> particle \(particleSelected.candidate.wayID ?? "nil") particle_cost=\(String(format: "%.1f", particleSelected.cumulativeCost)) heuristic_cost=\(String(format: "%.1f", heuristicCost)) seed=\(particleSelected.seedWayID ?? "nil") reason=\(particleSelected.seedSource)"
                    )
                )
            } else {
                finalSelected = heuristicSelected ?? particleSelected.candidate
                selectionTrace.append(
                    MatchSelectionTrace(
                        step: "simple_sequence_particle_hold",
                        detail: "kept heuristic \(heuristicSelected?.wayID ?? "nil") over particle \(particleSelected.candidate.wayID ?? "nil") particle_cost=\(String(format: "%.1f", particleSelected.cumulativeCost)) heuristic_cost=\(String(format: "%.1f", heuristicCost))"
                    )
                )
            }
        } else {
            finalSelected = heuristicSelected
        }

        if let particleSelected {
            selectionTrace.append(
                MatchSelectionTrace(
                    step: "simple_sequence_particle",
                    detail: "best_particle=\(particleSelected.candidate.wayID ?? "nil") cost=\(String(format: "%.1f", particleSelected.cumulativeCost)) emission=\(String(format: "%.1f", particleSelected.emissionCost)) transition=\(String(format: "%.1f", particleSelected.transitionCost))"
                )
            )
        }

        return SimpleSequenceParticleSelection(
            selected: finalSelected,
            traceRankedCandidates: traceRankedCandidates,
            hypotheses: hypotheses,
            selectionTrace: selectionTrace
        )
    }

    private func selectSimpleSequenceViterbiCandidate(
        db: OpaquePointer,
        currentCandidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        searchRadiusM: Double,
        maxCandidates: Int,
        wayLinks: WayLinksContext
    ) -> SimpleSequenceViterbiSelection {
        let fallbackTraceRankedCandidates = buildBaselineTraceRankedCandidates(
            from: currentCandidates,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        let currentObservation = SimpleSequenceViterbiObservation(
            lat: currentCandidates.first?.queryPoint.0 ?? matchContext.recentFixes.first?.lat ?? 0.0,
            lon: currentCandidates.first?.queryPoint.1 ?? matchContext.recentFixes.first?.lon ?? 0.0,
            headingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars,
            headingForScoring: observedHeadingDeg
        )
        let observations = simpleSequenceViterbiObservations(
            matchContext: matchContext,
            currentObservation: currentObservation
        )
        let layerBuild = simpleSequenceViterbiCandidateLayers(
            db: db,
            observations: observations,
            currentCandidates: currentCandidates,
            searchRadiusM: searchRadiusM,
            maxCandidates: maxCandidates,
            matchContext: matchContext
        )
        let layers = layerBuild.layers
        let continuityContext = loadWayContinuityContext(
            db: db,
            layers: layers,
            matchContext: matchContext
        )
        let graphContext = loadLocalWayGraphContext(
            db: db,
            observations: layers.map(\.observation),
            layers: layers
        )
        var selectionTrace: [MatchSelectionTrace] = [
            MatchSelectionTrace(
                step: "simple_sequence_viterbi_seed",
                detail: "source=rolling_hmm history_fixes=\(max(observations.count - 1, 0)) layers=\(layers.count) skipped_observations=\(layerBuild.skippedObservationCount) graph_available=\(graphContext.available) graph_way_count=\(graphContext.expandedWayCount) continuity_available=\(continuityContext.available) continuity_way_count=\(continuityContext.trackedWayCount)"
            )
        ]

        guard let finalLayer = layers.last, !finalLayer.candidates.isEmpty else {
            selectionTrace.append(
                MatchSelectionTrace(step: "simple_sequence_viterbi_hold", detail: "no viable candidate layers")
            )
            return SimpleSequenceViterbiSelection(
                selected: currentCandidates.first,
                traceRankedCandidates: fallbackTraceRankedCandidates,
                hypotheses: [],
                selectionTrace: selectionTrace
            )
        }

        var allLayerStates: [[SimpleSequenceViterbiState]] = []
        var shortestPathCache: [String: [String: Double]] = [:]

        for (layerIndex, layer) in layers.enumerated() {
            let previousLayer = layerIndex > 0 ? layers[layerIndex - 1] : nil
            let previousStates = layerIndex > 0 ? allLayerStates[layerIndex - 1] : []
            var layerStates: [SimpleSequenceViterbiState] = []
            layerStates.reserveCapacity(layer.candidates.count)

            for (stateIndex, candidate) in layer.candidates.enumerated() {
                let emissionCost = simpleSequenceViterbiEmissionCost(for: candidate, observation: layer.observation)
                if let previousLayer, !previousStates.isEmpty {
                    var bestCost = Double.infinity
                    var bestTransitionCost = Self.simpleSequenceViterbiUnreachableTransitionPenalty
                    var bestRouteDistance: Double?
                    var bestObservedDistance: Double?
                    var bestPreviousStateIndex: Int?

                    for previousState in previousStates {
                        let transition = simpleSequenceViterbiTransitionCost(
                            from: previousState.candidate,
                            previousObservation: previousLayer.observation,
                            to: candidate,
                            observation: layer.observation,
                            graph: graphContext,
                            continuity: continuityContext,
                            shortestPathCache: &shortestPathCache,
                            matchContext: matchContext,
                            wayLinks: wayLinks
                        )
                        let cumulativeCost = previousState.cumulativeCost + emissionCost + transition.cost
                        if cumulativeCost < bestCost {
                            bestCost = cumulativeCost
                            bestTransitionCost = transition.cost
                            bestRouteDistance = transition.routeDistanceM
                            bestObservedDistance = transition.observedDistanceM
                            bestPreviousStateIndex = previousState.stateIndex
                        }
                    }

                    layerStates.append(
                        SimpleSequenceViterbiState(
                            layerIndex: layerIndex,
                            stateIndex: stateIndex,
                            candidate: candidate,
                            continuity: continuityClass(for: candidate, matchContext: matchContext, wayLinks: wayLinks),
                            cumulativeCost: bestCost,
                            emissionCost: emissionCost,
                            transitionCost: bestTransitionCost,
                            routeDistanceM: bestRouteDistance,
                            observedDistanceM: bestObservedDistance,
                            previousStateIndex: bestPreviousStateIndex
                        )
                    )
                } else {
                    layerStates.append(
                        SimpleSequenceViterbiState(
                            layerIndex: layerIndex,
                            stateIndex: stateIndex,
                            candidate: candidate,
                            continuity: continuityClass(for: candidate, matchContext: matchContext, wayLinks: wayLinks),
                            cumulativeCost: emissionCost,
                            emissionCost: emissionCost,
                            transitionCost: 0.0,
                            routeDistanceM: nil,
                            observedDistanceM: nil,
                            previousStateIndex: nil
                        )
                    )
                }
            }

            allLayerStates.append(layerStates)
        }

        guard let lastStates = allLayerStates.last, !lastStates.isEmpty else {
            selectionTrace.append(
                MatchSelectionTrace(step: "simple_sequence_viterbi_hold", detail: "final layer empty after DP")
            )
            return SimpleSequenceViterbiSelection(
                selected: currentCandidates.first,
                traceRankedCandidates: fallbackTraceRankedCandidates,
                hypotheses: [],
                selectionTrace: selectionTrace
            )
        }

        let sortedLastStates = lastStates.enumerated().sorted { lhs, rhs in
            let left = lhs.element
            let right = rhs.element
            if left.cumulativeCost != right.cumulativeCost {
                return left.cumulativeCost < right.cumulativeCost
            }
            if left.transitionCost != right.transitionCost {
                return left.transitionCost < right.transitionCost
            }
            if left.emissionCost != right.emissionCost {
                return left.emissionCost < right.emissionCost
            }
            return (left.candidate.wayID ?? "~") < (right.candidate.wayID ?? "~")
        }

        let traceRankedCandidates = sortedLastStates.enumerated().map { rank, entry in
            TraceRankedCandidate(
                candidate: entry.element.candidate,
                continuity: entry.element.continuity,
                portalEligible: false,
                corridorState: nil,
                tunnelSelectable: true,
                corridorSelectable: true,
                traceScore: entry.element.cumulativeCost,
                traceRank: rank + 1
            )
        }
        let hypotheses = sortedLastStates.prefix(Self.simpleSequenceViterbiBeamWidth).compactMap { entry in
            wayMatchHypothesis(
                from: entry.element.candidate,
                cumulativeCost: entry.element.cumulativeCost,
                emissionScore: entry.element.emissionCost
            )
        }

        guard let bestFinal = sortedLastStates.first?.element else {
            return SimpleSequenceViterbiSelection(
                selected: currentCandidates.first,
                traceRankedCandidates: traceRankedCandidates.isEmpty ? fallbackTraceRankedCandidates : traceRankedCandidates,
                hypotheses: hypotheses,
                selectionTrace: selectionTrace
            )
        }

        var bestPathWayIDs: [String] = []
        var layerIndex = allLayerStates.count - 1
        var stateIndex = bestFinal.stateIndex
        while layerIndex >= 0, stateIndex < allLayerStates[layerIndex].count {
            let state = allLayerStates[layerIndex][stateIndex]
            if let wayID = normalizedWayID(state.candidate.wayID) {
                bestPathWayIDs.insert(wayID, at: 0)
            }
            guard let previousStateIndex = state.previousStateIndex else {
                break
            }
            layerIndex -= 1
            stateIndex = previousStateIndex
        }

        selectionTrace.append(
            MatchSelectionTrace(
                step: "simple_sequence_viterbi",
                detail: "best_viterbi=\(bestFinal.candidate.wayID ?? "nil") cost=\(String(format: "%.3f", bestFinal.cumulativeCost)) emission=\(String(format: "%.3f", bestFinal.emissionCost)) transition=\(String(format: "%.3f", bestFinal.transitionCost)) observed_route_delta_m=\(bestFinal.routeDistanceM.flatMap { route in bestFinal.observedDistanceM.map { observed in String(format: "%.1f", abs(route - observed)) } } ?? "nil") path=\(bestPathWayIDs.joined(separator: ">"))"
            )
        )

        return SimpleSequenceViterbiSelection(
            selected: bestFinal.candidate,
            traceRankedCandidates: traceRankedCandidates,
            hypotheses: hypotheses,
            selectionTrace: selectionTrace
        )
    }

    private func simpleSequenceViterbiObservations(
        matchContext: NormalizedMatchContext,
        currentObservation: SimpleSequenceViterbiObservation
    ) -> [SimpleSequenceViterbiObservation] {
        let priorObservations = matchContext.recentFixes
            .prefix(Self.simpleSequenceViterbiWindowFixCount - 1)
            .reversed()
            .map { fix in
                let normalizedHeading = normalizedHeadingDegrees(fix.headingDeg)
                return SimpleSequenceViterbiObservation(
                    lat: fix.lat,
                    lon: fix.lon,
                    headingDeg: normalizedHeading,
                    speedKmh: fix.speedKmh,
                    horizontalAccuracyM: fix.horizontalAccuracyM,
                    gpsSignalBars: fix.gpsSignalBars,
                    headingForScoring: shouldUseHeading(
                        headingDeg: normalizedHeading,
                        headingAccuracyDeg: fix.headingAccuracyDeg,
                        speedKmh: fix.speedKmh
                    ) ? normalizedHeading : nil
                )
            }
        return Array(priorObservations) + [currentObservation]
    }

    private func simpleSequenceViterbiCandidateLayers(
        db: OpaquePointer,
        observations: [SimpleSequenceViterbiObservation],
        currentCandidates: [WayCandidate],
        searchRadiusM: Double,
        maxCandidates: Int,
        matchContext: NormalizedMatchContext
    ) -> (layers: [SimpleSequenceViterbiLayer], skippedObservationCount: Int) {
        let cappedMaxCandidates = max(Self.simpleSequenceViterbiCandidateCount, min(maxCandidates, Self.maxTraceCandidateCount))
        var layers: [SimpleSequenceViterbiLayer] = []
        var skippedObservationCount = 0

        for (index, observation) in observations.enumerated() {
            let candidates: [WayCandidate]
            if index == observations.count - 1 {
                candidates = Array(currentCandidates.prefix(Self.simpleSequenceViterbiCandidateCount))
            } else {
                let preferredRadiusM = candidateLookupRadiusM(
                    radiusM: searchRadiusM,
                    horizontalAccuracyM: observation.horizontalAccuracyM
                )
                func queryCandidates(radiusM: Double) -> [WayCandidate]? {
                    guard let query = try? loadCandidates(
                        db: db,
                        lat: observation.lat,
                        lon: observation.lon,
                        radiusM: radiusM,
                        maxCandidates: cappedMaxCandidates,
                        headingForScoring: observation.headingForScoring,
                        matchContext: matchContext
                    ) else {
                        return nil
                    }
                    return Array(query.candidates.prefix(Self.simpleSequenceViterbiCandidateCount))
                }

                if let preferredCandidates = queryCandidates(radiusM: preferredRadiusM),
                   !preferredCandidates.isEmpty {
                    candidates = preferredCandidates
                } else if preferredRadiusM + 0.5 < searchRadiusM,
                          let widenedCandidates = queryCandidates(radiusM: searchRadiusM),
                          !widenedCandidates.isEmpty {
                    candidates = widenedCandidates
                } else {
                    skippedObservationCount += 1
                    continue
                }
            }

            let normalizedCandidates = candidates.filter { normalizedWayID($0.wayID) != nil }
            if normalizedCandidates.isEmpty {
                skippedObservationCount += 1
                continue
            }
            layers.append(SimpleSequenceViterbiLayer(observation: observation, candidates: normalizedCandidates))
        }

        return (layers, skippedObservationCount)
    }

    private func loadLocalWayGraphContext(
        db: OpaquePointer,
        observations: [SimpleSequenceViterbiObservation],
        layers: [SimpleSequenceViterbiLayer]
    ) -> LocalWayGraphContext {
        guard tableExists(db: db, name: "way_endpoints"), !observations.isEmpty else {
            return LocalWayGraphContext(available: false, byWayID: [:], adjacencyByNodeKey: [:], expandedWayCount: 0)
        }

        let lats = observations.map(\.lat)
        let lons = observations.map(\.lon)
        guard let minLat = lats.min(),
              let maxLat = lats.max(),
              let minLon = lons.min(),
              let maxLon = lons.max() else {
            return LocalWayGraphContext(available: false, byWayID: [:], adjacencyByNodeKey: [:], expandedWayCount: 0)
        }

        let totalObservedDistanceM = zip(observations, observations.dropFirst()).reduce(0.0) { partial, pair in
            partial + haversineM(lat1: pair.0.lat, lon1: pair.0.lon, lat2: pair.1.lat, lon2: pair.1.lon)
        }
        let marginM = max(Self.simpleSequenceViterbiLocalGraphMarginM, totalObservedDistanceM * 0.5 + 30.0)
        let degLat = marginM / 111_132.0
        let cosLat = max(0.173648, abs(cos(((minLat + maxLat) * 0.5) * .pi / 180.0)))
        let degLon = marginM / (111_320.0 * cosLat)

        var byWayID: [String: WayEndpointInfo] = [:]
        var adjacencyByNodeKey: [String: [LocalWayGraphEdge]] = [:]

        let sql = """
        SELECT CAST(e.way_id AS TEXT), e.ref_norm, e.highway, e.tunnel_flag,
               e.start_node_key, e.start_lon, e.start_lat,
               e.end_node_key, e.end_lon, e.end_lat, e.way_length_m
        FROM way_endpoints e
        JOIN ways_rtree r ON r.way_id = e.way_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
        """
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return LocalWayGraphContext(available: false, byWayID: [:], adjacencyByNodeKey: [:], expandedWayCount: 0)
        }
        sqlite3_bind_double(stmt, 1, maxLon + degLon)
        sqlite3_bind_double(stmt, 2, minLon - degLon)
        sqlite3_bind_double(stmt, 3, maxLat + degLat)
        sqlite3_bind_double(stmt, 4, minLat - degLat)

        while sqlite3_step(stmt) == SQLITE_ROW {
            guard let wayID = cStringOptional(sqlite3_column_text(stmt, 0)),
                  let startNodeKey = cStringOptional(sqlite3_column_text(stmt, 4)),
                  let endNodeKey = cStringOptional(sqlite3_column_text(stmt, 7)),
                  !wayID.isEmpty,
                  !startNodeKey.isEmpty,
                  !endNodeKey.isEmpty else {
                continue
            }
            let info = WayEndpointInfo(
                wayID: wayID,
                refNorm: cStringOptional(sqlite3_column_text(stmt, 1)) ?? "",
                highway: cStringOptional(sqlite3_column_text(stmt, 2)),
                tunnelFlag: sqlite3_column_int(stmt, 3) != 0,
                startNodeKey: startNodeKey,
                startLon: sqlite3_column_double(stmt, 5),
                startLat: sqlite3_column_double(stmt, 6),
                endNodeKey: endNodeKey,
                endLon: sqlite3_column_double(stmt, 8),
                endLat: sqlite3_column_double(stmt, 9),
                wayLengthM: sqlite3_column_double(stmt, 10)
            )
            appendWayEndpointInfo(info, byWayID: &byWayID, adjacencyByNodeKey: &adjacencyByNodeKey)
        }

        let requiredWayIDs = Set(layers.flatMap { layer in
            layer.candidates.compactMap { normalizedWayID($0.wayID) }
        })
        let missingWayIDs = requiredWayIDs.subtracting(byWayID.keys)
        if !missingWayIDs.isEmpty {
            let placeholders = Array(repeating: "?", count: missingWayIDs.count).joined(separator: ",")
            let sql = """
            SELECT CAST(way_id AS TEXT), ref_norm, highway, tunnel_flag,
                   start_node_key, start_lon, start_lat,
                   end_node_key, end_lon, end_lat, way_length_m
            FROM way_endpoints
            WHERE CAST(way_id AS TEXT) IN (\(placeholders))
            """
            var missingStmt: OpaquePointer?
            defer { sqlite3_finalize(missingStmt) }
            if sqlite3_prepare_v2(db, sql, -1, &missingStmt, nil) == SQLITE_OK, let missingStmt {
                for (index, wayID) in missingWayIDs.sorted().enumerated() {
                    sqlite3_bind_text(
                        missingStmt,
                        Int32(index + 1),
                        wayID,
                        -1,
                        unsafeBitCast(-1, to: sqlite3_destructor_type.self)
                    )
                }
                while sqlite3_step(missingStmt) == SQLITE_ROW {
                    guard let wayID = cStringOptional(sqlite3_column_text(missingStmt, 0)),
                          let startNodeKey = cStringOptional(sqlite3_column_text(missingStmt, 4)),
                          let endNodeKey = cStringOptional(sqlite3_column_text(missingStmt, 7)),
                          !wayID.isEmpty,
                          !startNodeKey.isEmpty,
                          !endNodeKey.isEmpty else {
                        continue
                    }
                    let info = WayEndpointInfo(
                        wayID: wayID,
                        refNorm: cStringOptional(sqlite3_column_text(missingStmt, 1)) ?? "",
                        highway: cStringOptional(sqlite3_column_text(missingStmt, 2)),
                        tunnelFlag: sqlite3_column_int(missingStmt, 3) != 0,
                        startNodeKey: startNodeKey,
                        startLon: sqlite3_column_double(missingStmt, 5),
                        startLat: sqlite3_column_double(missingStmt, 6),
                        endNodeKey: endNodeKey,
                        endLon: sqlite3_column_double(missingStmt, 8),
                        endLat: sqlite3_column_double(missingStmt, 9),
                        wayLengthM: sqlite3_column_double(missingStmt, 10)
                    )
                    appendWayEndpointInfo(info, byWayID: &byWayID, adjacencyByNodeKey: &adjacencyByNodeKey)
                }
            }
        }

        return LocalWayGraphContext(
            available: !byWayID.isEmpty,
            byWayID: byWayID,
            adjacencyByNodeKey: adjacencyByNodeKey,
            expandedWayCount: byWayID.count
        )
    }

    private func appendWayEndpointInfo(
        _ info: WayEndpointInfo,
        byWayID: inout [String: WayEndpointInfo],
        adjacencyByNodeKey: inout [String: [LocalWayGraphEdge]]
    ) {
        guard byWayID[info.wayID] == nil else {
            return
        }
        byWayID[info.wayID] = info
        adjacencyByNodeKey[info.startNodeKey, default: []].append(
            LocalWayGraphEdge(wayID: info.wayID, toNodeKey: info.endNodeKey, lengthM: info.wayLengthM)
        )
        adjacencyByNodeKey[info.endNodeKey, default: []].append(
            LocalWayGraphEdge(wayID: info.wayID, toNodeKey: info.startNodeKey, lengthM: info.wayLengthM)
        )
    }

    private func simpleSequenceViterbiEmissionCost(
        for candidate: WayCandidate,
        observation: SimpleSequenceViterbiObservation
    ) -> Double {
        let sigmaM = min(
            max(observation.horizontalAccuracyM ?? 8.0, Self.simpleSequenceViterbiObservationSigmaFloorM),
            Self.simpleSequenceViterbiObservationSigmaCapM
        )
        var cost = 0.5 * pow(candidate.distanceM / sigmaM, 2.0)
        if let headingDeg = observation.headingForScoring,
           let candidateHeadingDeg = candidate.localHeadingDeg ?? axisHeadingDeg(for: candidate) {
            let mismatchDeg = headingMismatchDeg(headingDeg: headingDeg, approxHeadingDeg: candidateHeadingDeg)
            cost += 0.5 * pow(mismatchDeg / Self.simpleSequenceViterbiHeadingSigmaDeg, 2.0)
        }
        return cost
    }

    private func simpleSequenceViterbiTransitionCost(
        from previousCandidate: WayCandidate,
        previousObservation: SimpleSequenceViterbiObservation,
        to candidate: WayCandidate,
        observation: SimpleSequenceViterbiObservation,
        graph: LocalWayGraphContext,
        continuity: WayContinuityContext,
        shortestPathCache: inout [String: [String: Double]],
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> (cost: Double, routeDistanceM: Double?, observedDistanceM: Double?) {
        let observedDistanceM = haversineM(
            lat1: previousObservation.lat,
            lon1: previousObservation.lon,
            lat2: observation.lat,
            lon2: observation.lon
        )
        let continuityStrength = simpleSequenceViterbiContinuityStrength(
            from: previousCandidate,
            to: candidate,
            continuity: continuity
        )
        let continuityBonus = continuityStrength.transitionBonus
        if graph.available,
           let routeDistanceM = simpleSequenceViterbiRouteDistanceM(
                from: previousCandidate,
                to: candidate,
                graph: graph,
                shortestPathCache: &shortestPathCache
           ) {
            let beta = max(
                Self.simpleSequenceViterbiTransitionBetaFloorM,
                observedDistanceM * Self.simpleSequenceViterbiTransitionBetaScale + Self.simpleSequenceViterbiTransitionBetaBiasM
            )
            let baseCost = abs(routeDistanceM - observedDistanceM) / beta
            return (max(0.0, baseCost - continuityBonus), routeDistanceM, observedDistanceM)
        }

        if let previousHypothesis = wayMatchHypothesis(
                from: previousCandidate,
                cumulativeCost: 0.0,
                emissionScore: previousCandidate.score
           ),
           (!graph.available || continuityStrength != .none) {
            let baseCost =
                genericTransitionPenalty(
                    from: previousHypothesis,
                    to: candidate,
                    observedHeadingDeg: observation.headingForScoring,
                    speedKmh: observation.speedKmh,
                    matchContext: matchContext,
                    wayLinks: wayLinks
                ) + Self.simpleSequenceViterbiLayerGapPenalty
            return (
                max(0.0, baseCost - continuityBonus),
                nil,
                observedDistanceM
            )
        }

        return (Self.simpleSequenceViterbiUnreachableTransitionPenalty, nil, observedDistanceM)
    }

    private func simpleSequenceViterbiContinuityStrength(
        from previousCandidate: WayCandidate,
        to candidate: WayCandidate,
        continuity: WayContinuityContext
    ) -> WayContinuityStrength {
        guard normalizedWayID(previousCandidate.wayID) != normalizedWayID(candidate.wayID) else {
            return .none
        }
        return continuity.sharedStrength(
            from: normalizedWayID(previousCandidate.wayID),
            to: normalizedWayID(candidate.wayID)
        )
    }

    private func simpleSequenceViterbiRouteDistanceM(
        from previousCandidate: WayCandidate,
        to candidate: WayCandidate,
        graph: LocalWayGraphContext,
        shortestPathCache: inout [String: [String: Double]]
    ) -> Double? {
        if normalizedWayID(previousCandidate.wayID) == normalizedWayID(candidate.wayID),
           let previousDistanceToStartM = previousCandidate.distanceToStartM,
           let currentDistanceToStartM = candidate.distanceToStartM {
            return abs(currentDistanceToStartM - previousDistanceToStartM)
        }

        let previousOptions = simpleSequenceViterbiNodeOptions(for: previousCandidate, graph: graph)
        let currentOptions = simpleSequenceViterbiNodeOptions(for: candidate, graph: graph)
        guard !previousOptions.isEmpty, !currentOptions.isEmpty else {
            return nil
        }

        var bestDistanceM = Double.infinity
        for previousOption in previousOptions {
            let distances = simpleSequenceViterbiShortestPathDistances(
                from: previousOption.nodeKey,
                graph: graph,
                cache: &shortestPathCache
            )
            for currentOption in currentOptions {
                guard let graphDistanceM = distances[currentOption.nodeKey] else {
                    continue
                }
                bestDistanceM = min(
                    bestDistanceM,
                    previousOption.distanceM + graphDistanceM + currentOption.distanceM
                )
            }
        }
        return bestDistanceM.isFinite ? bestDistanceM : nil
    }

    private func simpleSequenceViterbiNodeOptions(
        for candidate: WayCandidate,
        graph: LocalWayGraphContext
    ) -> [(nodeKey: String, distanceM: Double)] {
        let wayID = normalizedWayID(candidate.wayID)
        let endpointInfo = wayID.flatMap { graph.byWayID[$0] }
        let startNodeKey = candidate.startNodeKey ?? endpointInfo?.startNodeKey
        let endNodeKey = candidate.endNodeKey ?? endpointInfo?.endNodeKey

        var options: [(nodeKey: String, distanceM: Double)] = []
        if let startNodeKey, let distanceToStartM = candidate.distanceToStartM {
            options.append((startNodeKey, distanceToStartM))
        }
        if let endNodeKey, let distanceToEndM = candidate.distanceToEndM {
            options.append((endNodeKey, distanceToEndM))
        }
        if options.count == 2, options[0].nodeKey == options[1].nodeKey {
            return [options.min(by: { $0.distanceM < $1.distanceM })!]
        }
        return options
    }

    private func simpleSequenceViterbiShortestPathDistances(
        from startNodeKey: String,
        graph: LocalWayGraphContext,
        cache: inout [String: [String: Double]]
    ) -> [String: Double] {
        if let cached = cache[startNodeKey] {
            return cached
        }
        var distances: [String: Double] = [startNodeKey: 0.0]
        var frontier: [(nodeKey: String, distanceM: Double)] = [(startNodeKey, 0.0)]

        while !frontier.isEmpty {
            var bestIndex = 0
            for index in 1..<frontier.count where frontier[index].distanceM < frontier[bestIndex].distanceM {
                bestIndex = index
            }
            let current = frontier.remove(at: bestIndex)
            if current.distanceM > distances[current.nodeKey, default: .infinity] {
                continue
            }
            for edge in graph.adjacencyByNodeKey[current.nodeKey] ?? [] {
                let nextDistanceM = current.distanceM + edge.lengthM
                if nextDistanceM < distances[edge.toNodeKey, default: .infinity] {
                    distances[edge.toNodeKey] = nextDistanceM
                    frontier.append((edge.toNodeKey, nextDistanceM))
                }
            }
        }

        cache[startNodeKey] = distances
        return distances
    }

    private func simpleSequenceParticleSeedContext(
        candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        limit: Int
    ) -> (hypotheses: [WayMatchHypothesis], source: String) {
        if !matchContext.recentHypotheses.isEmpty {
            return (Array(matchContext.recentHypotheses.prefix(limit)), "recent_hypotheses")
        }
        if let preferredWayID = matchContext.preferredWayID,
           let preferredCandidate = candidates.first(where: {
               normalizedWayID($0.wayID) == preferredWayID
           }),
           let hypothesis = wayMatchHypothesis(
               from: preferredCandidate,
               cumulativeCost: 0.0,
               emissionScore: preferredCandidate.score
           ) {
            return ([hypothesis], "preferred_way")
        }
        return ([], "cold_start")
    }

    private func simpleSequenceParticleEmissionCost(
        for candidate: WayCandidate,
        observedHeadingDeg: Double?,
        fallbackMotionHeadingDeg: Double?
    ) -> Double {
        var emissionCost = candidate.score
        guard observedHeadingDeg == nil,
              let fallbackMotionHeadingDeg,
              let candidateHeadingDeg = axisHeadingDeg(for: candidate) else {
            return emissionCost
        }
        emissionCost += headingMismatchDeg(
            headingDeg: fallbackMotionHeadingDeg,
            approxHeadingDeg: candidateHeadingDeg
        ) * Self.simpleSequenceParticleMotionHeadingWeightMPerDeg
        return emissionCost
    }

    private func simpleSequenceParticleTransition(
        for candidate: WayCandidate,
        seedHypotheses: [WayMatchHypothesis],
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> (cost: Double, seedWayID: String?, reason: String) {
        guard !seedHypotheses.isEmpty else {
            return (0.0, nil, "emission_only")
        }

        var bestCost = Double.infinity
        var bestSeedWayID: String?
        var bestReason = "history"
        for hypothesis in seedHypotheses {
            let historyCost = hypothesis.cumulativeCost * Self.simpleSequenceParticleHistoryDecay
            let genericCost = genericTransitionPenalty(
                from: hypothesis,
                to: candidate,
                observedHeadingDeg: observedHeadingDeg,
                speedKmh: speedKmh,
                matchContext: matchContext,
                wayLinks: wayLinks
            )
            let geometryTurnCost = simpleSequenceParticleSharedNodeTurnCost(
                from: hypothesis,
                to: candidate,
                observedHeadingDeg: observedHeadingDeg,
                speedKmh: speedKmh
            )
            let transitionCost: Double
            let transitionReason: String
            if let geometryTurnCost, geometryTurnCost < genericCost {
                transitionCost = geometryTurnCost
                transitionReason = "shared_node_turn"
            } else {
                transitionCost = genericCost
                transitionReason = "history"
            }
            let totalCost = historyCost + transitionCost
            if totalCost < bestCost {
                bestCost = totalCost
                bestSeedWayID = hypothesis.wayID
                bestReason = transitionReason
            }
        }
        return (bestCost.isFinite ? bestCost : 0.0, bestSeedWayID, bestReason)
    }

    private func simpleSequenceParticleSharedNodeTurnCost(
        from hypothesis: WayMatchHypothesis,
        to candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?
    ) -> Double? {
        let anchorCandidate = wayCandidate(from: hypothesis)
        guard let sharedPoint = sharedJunctionPoint(between: anchorCandidate, and: candidate),
              let evidence = nodeDirectionTransitionHeadingEvidence(
                from: anchorCandidate,
                to: candidate,
                sharedPoint: sharedPoint,
                observedHeadingDeg: observedHeadingDeg,
                speedKmh: speedKmh
              ),
              evidence.nearEndpoint,
              evidence.meaningfulTurn,
              evidence.candidateClearlyBetterAligned,
              evidence.candidateMismatchDeg <= Self.simpleLowSpeedNodeAwareJunctionMaxCandidateMismatchDeg,
              evidence.currentMismatchDeg >= Self.simpleLowSpeedJunctionMinCurrentMismatchDeg,
              !evidence.serviceLike else {
            return nil
        }
        return Self.simpleSequenceParticleSharedNodeTurnPenaltyM
    }

    private func wayMatchHypothesis(
        from candidate: WayCandidate,
        cumulativeCost: Double,
        emissionScore: Double
    ) -> WayMatchHypothesis? {
        guard let wayID = normalizedWayID(candidate.wayID) else {
            return nil
        }
        return WayMatchHypothesis(
            wayID: wayID,
            streetRef: candidate.streetRef,
            highway: candidate.highway,
            cumulativeCost: cumulativeCost,
            emissionScore: emissionScore,
            endpointProximityM: candidate.endpointProximityM,
            startLat: candidate.startPoint?.0,
            startLon: candidate.startPoint?.1,
            endLat: candidate.endPoint?.0,
            endLon: candidate.endPoint?.1,
            isTunnel: isTruthyOSMTag(candidate.tunnel)
        )
    }

    private func wayCandidate(from hypothesis: WayMatchHypothesis) -> WayCandidate {
        let axisHeading = axisHeadingDeg(
            from: hypothesis.startLat,
            lon1: hypothesis.startLon,
            to: hypothesis.endLat,
            lon2: hypothesis.endLon
        )
        return WayCandidate(
            wayID: hypothesis.wayID,
            highway: hypothesis.highway,
            service: nil,
            tunnel: hypothesis.isTunnel ? "yes" : nil,
            streetName: nil,
            streetBaseName: nil,
            streetRef: hypothesis.streetRef,
            speedKmh: nil,
            speedSource: .none,
            isUnlimitedSpeedLimit: false,
            distanceM: 0.0,
            endpointProximityM: hypothesis.endpointProximityM,
            distanceToStartM: 0.0,
            distanceToEndM: 0.0,
            score: hypothesis.emissionScore,
            queryPoint: (
                hypothesis.startLat ?? 0.0,
                hypothesis.startLon ?? 0.0
            ),
            points: [],
            localHeadingDeg: axisHeading,
            wayLengthM: nil,
            startNodeKey: nil,
            endNodeKey: nil,
            startPoint: hypothesis.startLat.flatMap { startLat in
                hypothesis.startLon.map { (startLat, $0) }
            },
            endPoint: hypothesis.endLat.flatMap { endLat in
                hypothesis.endLon.map { (endLat, $0) }
            },
            startHeadingDeg: axisHeading,
            endHeadingDeg: axisHeading
        )
    }

    private struct LowSpeedSameRefJunctionRelease {
        let candidate: WayCandidate
        let anchorCandidate: WayCandidate
    }

    private struct LowSpeedSameRefJunctionProbe {
        let candidate: WayCandidate
        let anchorCandidate: WayCandidate
        let blockFlags: [String]
        let evidence: TransitionHeadingEvidence?
    }

    private struct LowSpeedSameRefNodeDirectionAnalysis {
        let release: LowSpeedSameRefJunctionRelease?
        let probe: LowSpeedSameRefJunctionProbe?
    }

    private func lowSpeedSameRefJunctionTransitionCandidate(
        in candidates: [WayCandidate],
        currentCandidate: WayCandidate,
        bestCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double,
        accuracyBufferM: Double,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> LowSpeedSameRefJunctionRelease? {
        guard wayLinks.available,
              speedKmh >= Self.headingMinSpeedKmh,
              let currentWayID = normalizedWayID(currentCandidate.wayID) else {
            return nil
        }
        let effectiveHeadingDeg = observedHeadingDeg ?? recentApproachHeadingDeg(
            matchContext: matchContext,
            queryPoint: currentCandidate.queryPoint
        )
        guard let effectiveHeadingDeg else {
            return nil
        }

        let maxDistanceSlack = max(Self.simpleLowSpeedJunctionBestDistanceSlackM, accuracyBufferM * 0.35)
        let maxCurrentGap = max(Self.simpleLowSpeedJunctionCurrentDistanceSlackM, accuracyBufferM * 0.4)
        let continuityRefTokens = preferredSimpleRefContinuityTokens(for: matchContext)
        let anchorCandidates = lowSpeedSameRefJunctionAnchorCandidates(
            in: candidates,
            currentCandidate: currentCandidate,
            continuityRefTokens: continuityRefTokens,
            matchContext: matchContext
        )
        guard !anchorCandidates.isEmpty else {
            return nil
        }

        let releases = candidates.compactMap { candidate -> LowSpeedSameRefJunctionRelease? in
            guard let candidateWayID = normalizedWayID(candidate.wayID),
                  candidateWayID != currentWayID else {
                return nil
            }
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            if !candidateRefTokens.isEmpty,
               candidateRefTokens == continuityRefTokens {
                return nil
            }
            guard candidate.distanceM <= bestCandidate.distanceM + maxDistanceSlack,
                  candidate.distanceM <= currentCandidate.distanceM + maxCurrentGap else {
                return nil
            }

            for anchorCandidate in anchorCandidates {
                guard let anchorWayID = normalizedWayID(anchorCandidate.wayID),
                      wayLinks.isLinked(from: anchorWayID, to: candidateWayID) ||
                        wayLinks.isLinked(from: candidateWayID, to: anchorWayID),
                      let evidence = transitionHeadingEvidence(
                        fromAxisHeadingDeg: axisHeadingDeg(for: anchorCandidate),
                        fromEndpointProximityM: anchorCandidate.endpointProximityM,
                        to: candidate,
                        observedHeadingDeg: effectiveHeadingDeg,
                        speedKmh: speedKmh
                      ),
                      evidence.nearEndpoint,
                      evidence.meaningfulTurn,
                      evidence.candidateClearlyBetterAligned,
                      evidence.candidateMismatchDeg <= Self.simpleLowSpeedJunctionMaxCandidateMismatchDeg,
                      evidence.currentMismatchDeg >= Self.simpleLowSpeedJunctionMinCurrentMismatchDeg,
                      !isServiceLikeTransitionCandidate(candidate) else {
                    continue
                }
                return LowSpeedSameRefJunctionRelease(
                    candidate: candidate,
                    anchorCandidate: anchorCandidate
                )
            }
            return nil
        }

        return releases.sorted { lhs, rhs in
            if lhs.candidate.score != rhs.candidate.score {
                return lhs.candidate.score < rhs.candidate.score
            }
            return isBetterDistanceCandidate(lhs.candidate, than: rhs.candidate)
        }.first
    }

    private func lowSpeedSameRefNodeDirectionJunctionAnalysis(
        in candidates: [WayCandidate],
        currentCandidate: WayCandidate,
        bestCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double,
        accuracyBufferM: Double,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> LowSpeedSameRefNodeDirectionAnalysis {
        guard wayLinks.available,
              speedKmh >= Self.headingMinSpeedKmh,
              let currentWayID = normalizedWayID(currentCandidate.wayID) else {
            return LowSpeedSameRefNodeDirectionAnalysis(release: nil, probe: nil)
        }
        let effectiveHeadingDeg = observedHeadingDeg ?? recentApproachHeadingDeg(
            matchContext: matchContext,
            queryPoint: currentCandidate.queryPoint
        )
        guard let effectiveHeadingDeg else {
            return LowSpeedSameRefNodeDirectionAnalysis(release: nil, probe: nil)
        }

        let maxDistanceSlack = max(Self.simpleLowSpeedJunctionBestDistanceSlackM, accuracyBufferM * 0.35)
        let maxCurrentGap = max(Self.simpleLowSpeedJunctionCurrentDistanceSlackM, accuracyBufferM * 0.4)
        let continuityRefTokens = preferredSimpleRefContinuityTokens(for: matchContext)
        let anchorCandidates = lowSpeedSameRefJunctionAnchorCandidates(
            in: candidates,
            currentCandidate: currentCandidate,
            continuityRefTokens: continuityRefTokens,
            matchContext: matchContext
        )
        guard !anchorCandidates.isEmpty else {
            return LowSpeedSameRefNodeDirectionAnalysis(release: nil, probe: nil)
        }

        let releases = candidates.compactMap { candidate -> LowSpeedSameRefJunctionRelease? in
            guard let candidateWayID = normalizedWayID(candidate.wayID),
                  candidateWayID != currentWayID else {
                return nil
            }
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            if !candidateRefTokens.isEmpty,
               candidateRefTokens == continuityRefTokens {
                return nil
            }
            guard candidate.distanceM <= bestCandidate.distanceM + maxDistanceSlack,
                  candidate.distanceM <= currentCandidate.distanceM + maxCurrentGap,
                  !isServiceLikeTransitionCandidate(candidate) else {
                return nil
            }

            for anchorCandidate in anchorCandidates {
                guard let sharedPoint = sharedJunctionPoint(between: anchorCandidate, and: candidate),
                      let evidence = nodeDirectionTransitionHeadingEvidence(
                        from: anchorCandidate,
                        to: candidate,
                        sharedPoint: sharedPoint,
                        observedHeadingDeg: effectiveHeadingDeg,
                        speedKmh: speedKmh
                      ),
                      evidence.nearEndpoint,
                      evidence.meaningfulTurn,
                      evidence.candidateClearlyBetterAligned,
                      evidence.candidateMismatchDeg <= Self.simpleLowSpeedNodeAwareJunctionMaxCandidateMismatchDeg,
                      evidence.currentMismatchDeg >= Self.simpleLowSpeedJunctionMinCurrentMismatchDeg else {
                    continue
                }
                return LowSpeedSameRefJunctionRelease(
                    candidate: candidate,
                    anchorCandidate: anchorCandidate
                )
            }
            return nil
        }

        let release = releases.sorted { lhs, rhs in
            if lhs.candidate.score != rhs.candidate.score {
                return lhs.candidate.score < rhs.candidate.score
            }
            return isBetterDistanceCandidate(lhs.candidate, than: rhs.candidate)
        }.first
        guard release == nil else {
            return LowSpeedSameRefNodeDirectionAnalysis(release: release, probe: nil)
        }

        var bestProbe: LowSpeedSameRefJunctionProbe?
        for candidate in candidates {
            guard let candidateWayID = normalizedWayID(candidate.wayID),
                  candidateWayID != currentWayID else {
                continue
            }
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            if !candidateRefTokens.isEmpty,
               candidateRefTokens == continuityRefTokens {
                continue
            }

            for anchorCandidate in anchorCandidates {
                guard let anchorWayID = normalizedWayID(anchorCandidate.wayID),
                      wayLinks.isLinked(from: anchorWayID, to: candidateWayID) ||
                        wayLinks.isLinked(from: candidateWayID, to: anchorWayID) else {
                    continue
                }

                let sharedPoint = sharedJunctionPoint(between: anchorCandidate, and: candidate)
                let evidence = sharedPoint.flatMap {
                    nodeDirectionTransitionHeadingEvidence(
                        from: anchorCandidate,
                        to: candidate,
                        sharedPoint: $0,
                        observedHeadingDeg: effectiveHeadingDeg,
                        speedKmh: speedKmh
                    )
                }
                var blockFlags: [String] = []
                if candidate.distanceM > bestCandidate.distanceM + maxDistanceSlack {
                    blockFlags.append("best_gap")
                }
                if candidate.distanceM > currentCandidate.distanceM + maxCurrentGap {
                    blockFlags.append("current_gap")
                }
                if sharedPoint == nil {
                    blockFlags.append("shared_node_missing")
                }
                if let evidence {
                    if !evidence.nearEndpoint {
                        blockFlags.append("not_near_endpoint")
                    }
                    if !evidence.meaningfulTurn {
                        blockFlags.append("turn_not_meaningful")
                    }
                    if !evidence.candidateClearlyBetterAligned {
                        blockFlags.append("candidate_not_better_aligned")
                    }
                    if evidence.candidateMismatchDeg > Self.simpleLowSpeedNodeAwareJunctionMaxCandidateMismatchDeg {
                        blockFlags.append("candidate_heading_mismatch")
                    }
                    if evidence.currentMismatchDeg < Self.simpleLowSpeedJunctionMinCurrentMismatchDeg {
                        blockFlags.append("current_heading_still_aligned")
                    }
                    if evidence.serviceLike {
                        blockFlags.append("service_like")
                    }
                } else if sharedPoint != nil {
                    blockFlags.append("heading_unavailable")
                }

                guard !blockFlags.isEmpty else {
                    continue
                }
                let probe = LowSpeedSameRefJunctionProbe(
                    candidate: candidate,
                    anchorCandidate: anchorCandidate,
                    blockFlags: blockFlags,
                    evidence: evidence
                )
                if let currentBestProbe = bestProbe {
                    if isBetterDistanceCandidate(candidate, than: currentBestProbe.candidate) {
                        bestProbe = probe
                    }
                } else {
                    bestProbe = probe
                }
                break
            }
        }

        return LowSpeedSameRefNodeDirectionAnalysis(release: nil, probe: bestProbe)
    }

    private func lowSpeedSameRefJunctionProbeDetail(
        probe: LowSpeedSameRefJunctionProbe,
        currentCandidate: WayCandidate,
        bestCandidate: WayCandidate,
        geometryRanksByWayID: [String: Int],
        traceRanksByWayID: [String: Int]
    ) -> String {
        let candidateWayID = normalizedWayID(probe.candidate.wayID)
        let currentWayID = normalizedWayID(currentCandidate.wayID)
        let bestWayID = normalizedWayID(bestCandidate.wayID)
        let blocked = probe.blockFlags.reduce(into: [String]()) { partialResult, flag in
            if !partialResult.contains(flag) {
                partialResult.append(flag)
            }
        }

        var parts = [
            "candidate=\(probe.candidate.wayID ?? "nil")",
            "anchor=\(probe.anchorCandidate.wayID ?? "nil")",
            "blocked=\(blocked.joined(separator: ","))",
            "candidate_geometry_rank=\(candidateWayID.flatMap { geometryRanksByWayID[$0] }.map(String.init) ?? "nil")",
            "candidate_trace_rank=\(candidateWayID.flatMap { traceRanksByWayID[$0] }.map(String.init) ?? "nil")",
            "current_geometry_rank=\(currentWayID.flatMap { geometryRanksByWayID[$0] }.map(String.init) ?? "nil")",
            "best_geometry_rank=\(bestWayID.flatMap { geometryRanksByWayID[$0] }.map(String.init) ?? "nil")",
            "candidate_m=\(String(format: "%.1f", probe.candidate.distanceM))",
            "current_m=\(String(format: "%.1f", currentCandidate.distanceM))",
            "best_m=\(String(format: "%.1f", bestCandidate.distanceM))",
            "candidate_endpoint_m=\(String(format: "%.1f", probe.candidate.endpointProximityM))",
            "current_endpoint_m=\(String(format: "%.1f", currentCandidate.endpointProximityM))"
        ]
        if let evidence = probe.evidence {
            parts.append("turn_deg=\(String(format: "%.1f", evidence.turnAngleDeg))")
            parts.append("candidate_mismatch_deg=\(String(format: "%.1f", evidence.candidateMismatchDeg))")
            parts.append("current_mismatch_deg=\(String(format: "%.1f", evidence.currentMismatchDeg))")
        }
        return parts.joined(separator: " ")
    }

    private func nodeDirectionTransitionHeadingEvidence(
        from anchorCandidate: WayCandidate,
        to candidate: WayCandidate,
        sharedPoint: (Double, Double),
        observedHeadingDeg: Double?,
        speedKmh: Double?
    ) -> TransitionHeadingEvidence? {
        transitionHeadingEvidence(
            fromHeadingDeg: junctionNodeHeadingDeg(
                for: anchorCandidate,
                sharedPoint: sharedPoint,
                traversal: .towardNode
            ),
            toHeadingDeg: junctionNodeHeadingDeg(
                for: candidate,
                sharedPoint: sharedPoint,
                traversal: .awayFromNode
            ),
            fromEndpointProximityM: anchorCandidate.endpointProximityM,
            toEndpointProximityM: candidate.endpointProximityM,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            serviceLike: isServiceLikeTransitionCandidate(candidate)
        )
    }

    private func sharedJunctionPoint(
        between firstCandidate: WayCandidate,
        and secondCandidate: WayCandidate
    ) -> (Double, Double)? {
        let firstEndpoints = [firstCandidate.startPoint, firstCandidate.endPoint].compactMap { $0 }
        let secondEndpoints = [secondCandidate.startPoint, secondCandidate.endPoint].compactMap { $0 }
        guard !firstEndpoints.isEmpty, !secondEndpoints.isEmpty else {
            return nil
        }

        var bestDistanceM = Double.infinity
        var bestPair: ((Double, Double), (Double, Double))?
        for firstPoint in firstEndpoints {
            for secondPoint in secondEndpoints {
                let distanceM = haversineM(
                    lat1: firstPoint.0,
                    lon1: firstPoint.1,
                    lat2: secondPoint.0,
                    lon2: secondPoint.1
                )
                if distanceM < bestDistanceM {
                    bestDistanceM = distanceM
                    bestPair = (firstPoint, secondPoint)
                }
            }
        }
        guard let bestPair,
              bestDistanceM <= Self.simpleLowSpeedJunctionSharedNodeToleranceM else {
            return nil
        }
        return (
            (bestPair.0.0 + bestPair.1.0) * 0.5,
            (bestPair.0.1 + bestPair.1.1) * 0.5
        )
    }

    private func junctionNodeHeadingDeg(
        for candidate: WayCandidate,
        sharedPoint: (Double, Double),
        traversal: JunctionNodeTraversalDirection
    ) -> Double? {
        let startDistanceM = candidate.startPoint.map {
            haversineM(
                lat1: $0.0,
                lon1: $0.1,
                lat2: sharedPoint.0,
                lon2: sharedPoint.1
            )
        } ?? Double.infinity
        let endDistanceM = candidate.endPoint.map {
            haversineM(
                lat1: $0.0,
                lon1: $0.1,
                lat2: sharedPoint.0,
                lon2: sharedPoint.1
            )
        } ?? Double.infinity
        let fallbackHeadingDeg = axisHeadingDeg(for: candidate)

        if startDistanceM <= endDistanceM,
           startDistanceM <= Self.simpleLowSpeedJunctionSharedNodeToleranceM {
            switch traversal {
            case .towardNode:
                return oppositeHeadingDeg(candidate.startHeadingDeg ?? fallbackHeadingDeg)
            case .awayFromNode:
                return candidate.startHeadingDeg ?? fallbackHeadingDeg
            }
        }
        guard endDistanceM <= Self.simpleLowSpeedJunctionSharedNodeToleranceM else {
            return nil
        }
        switch traversal {
        case .towardNode:
            return candidate.endHeadingDeg ?? fallbackHeadingDeg
        case .awayFromNode:
            return oppositeHeadingDeg(candidate.endHeadingDeg ?? fallbackHeadingDeg)
        }
    }

    private func oppositeHeadingDeg(_ headingDeg: Double?) -> Double? {
        guard let headingDeg else {
            return nil
        }
        return normalizedHeadingDegrees(headingDeg + 180.0)
    }

    private func recentApproachHeadingDeg(
        matchContext: NormalizedMatchContext,
        queryPoint: (Double, Double)
    ) -> Double? {
        for fix in matchContext.recentFixes {
            let distanceM = haversineM(
                lat1: fix.lat,
                lon1: fix.lon,
                lat2: queryPoint.0,
                lon2: queryPoint.1
            )
            if distanceM >= 2.0 {
                return axisHeadingDeg(
                    from: fix.lat,
                    lon1: fix.lon,
                    to: queryPoint.0,
                    lon2: queryPoint.1
                )
            }
        }
        guard let fix = matchContext.recentFixes.first else {
            return nil
        }
        return axisHeadingDeg(
            from: fix.lat,
            lon1: fix.lon,
            to: queryPoint.0,
            lon2: queryPoint.1
        )
    }

    private enum SimpleContinuityIdentitySource {
        case none
        case ref
        case streetName

        var traceLabel: String {
            switch self {
            case .none:
                return "continuity"
            case .ref:
                return "same-ref"
            case .streetName:
                return "same-name"
            }
        }
    }

    private func preferredSimpleContinuityIdentity(
        for matchContext: NormalizedMatchContext,
        useStreetNameFallbackContinuity: Bool
    ) -> (tokens: Set<String>, source: SimpleContinuityIdentitySource) {
        if !matchContext.activeStreetRefTokens.isEmpty {
            return (matchContext.activeStreetRefTokens, .ref)
        }
        if useStreetNameFallbackContinuity,
           matchContext.consecutiveNoRefMatchCount >= Self.simpleStreetNameFallbackMinNoRefMatches,
           !matchContext.activeStreetNameTokens.isEmpty {
            return (matchContext.activeStreetNameTokens, .streetName)
        }
        if !matchContext.preferredStreetRefs.isEmpty {
            return (matchContext.preferredStreetRefs, .ref)
        }
        return ([], .none)
    }

    private func preferredGuardedStreetNameContinuityCandidate(
        rankedCandidates: [WayCandidate],
        bestCandidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        horizontalAccuracyM: Double?
    ) -> (candidate: WayCandidate, tokens: Set<String>, trace: MatchSelectionTrace)? {
        guard matchContext.activeStreetRefTokens.isEmpty,
              matchContext.consecutiveNoRefMatchCount >= Self.simpleStreetNameFallbackMinNoRefMatches,
              !matchContext.activeStreetNameTokens.isEmpty,
              isUrbanSameRefReleaseTargetHighway(matchContext.preferredHighway),
              let horizontalAccuracyM,
              horizontalAccuracyM.isFinite,
              horizontalAccuracyM > 0 else {
            return nil
        }

        let nameCandidate = rankedCandidates.first { candidate in
            guard Set(Self.normalizedRefTokens(candidate.streetRef)).isEmpty else {
                return false
            }
            let candidateTokens = Set(Self.normalizedStreetNameTokens(candidate.streetBaseName ?? candidate.streetName))
            guard !candidateTokens.isEmpty else {
                return false
            }
            return !candidateTokens.isDisjoint(with: matchContext.activeStreetNameTokens)
        }
        guard let nameCandidate,
              normalizedWayID(nameCandidate.wayID) == normalizedWayID(bestCandidate.wayID),
              isUrbanSameRefReleaseTargetHighway(nameCandidate.highway),
              nameCandidate.distanceM <= horizontalAccuracyM else {
            return nil
        }

        let refTokens = preferredSimpleRefContinuityTokens(for: matchContext)
        let staleRefCandidate = rankedCandidates.first { candidate in
            let candidateTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            guard !candidateTokens.isEmpty else {
                return false
            }
            return !candidateTokens.isDisjoint(with: refTokens)
        }

        if let staleRefCandidate {
            guard isUrbanSameRefReleaseSourceHighway(staleRefCandidate.highway) else {
                return nil
            }
            let staleRefOutsideAccuracyCap = staleRefCandidate.distanceM > horizontalAccuracyM
            let staleRefDistanceGapM = staleRefCandidate.distanceM - nameCandidate.distanceM
            guard staleRefOutsideAccuracyCap ||
                    staleRefDistanceGapM >= Self.simpleSameRefUrbanReleaseMinDistanceGapM else {
                return nil
            }
        }

        let trace = MatchSelectionTrace(
            step: "simple_same_name_guard",
            detail: "kept same-name \(nameCandidate.wayID ?? "nil") after \(matchContext.consecutiveNoRefMatchCount) no-ref matches best_m=\(String(format: "%.1f", nameCandidate.distanceM)) stale_ref_m=\(String(format: "%.1f", staleRefCandidate?.distanceM ?? Double.infinity)) hacc_m=\(String(format: "%.1f", horizontalAccuracyM))"
        )
        return (
            candidate: nameCandidate,
            tokens: matchContext.activeStreetNameTokens,
            trace: trace
        )
    }

    private func preferredSimpleRefContinuityTokens(
        for matchContext: NormalizedMatchContext
    ) -> Set<String> {
        if !matchContext.activeStreetRefTokens.isEmpty {
            return matchContext.activeStreetRefTokens
        }
        return matchContext.preferredStreetRefs
    }

    private func preferredSimpleContinuityCandidate(
        rankedCandidates: [WayCandidate],
        continuityIdentity: (tokens: Set<String>, source: SimpleContinuityIdentitySource),
        matchContext: NormalizedMatchContext,
        useStreetNameFallbackContinuity: Bool
    ) -> (candidate: WayCandidate, trace: MatchSelectionTrace?)? {
        guard !continuityIdentity.tokens.isEmpty else {
            return nil
        }
        let continuityCandidates = rankedCandidates.filter { candidate in
            let candidateTokens = continuityTokens(
                for: candidate,
                source: continuityIdentity.source,
                useStreetNameFallbackContinuity: useStreetNameFallbackContinuity
            )
            guard !candidateTokens.isEmpty else {
                return false
            }
            return !candidateTokens.isDisjoint(with: continuityIdentity.tokens)
        }
        guard let geometricContinuityCandidate = continuityCandidates.first else {
            return nil
        }
        let preferredContinuityCandidate = continuityCandidates.min { lhs, rhs in
            let lhsRank = simpleContinuityGuardRank(for: lhs, matchContext: matchContext)
            let rhsRank = simpleContinuityGuardRank(for: rhs, matchContext: matchContext)
            if lhsRank != rhsRank {
                return lhsRank < rhsRank
            }
            return isBetterDistanceCandidate(lhs, than: rhs)
        } ?? geometricContinuityCandidate

        let trace: MatchSelectionTrace?
        if normalizedWayID(preferredContinuityCandidate.wayID) != normalizedWayID(geometricContinuityCandidate.wayID),
           simpleContinuityGuardRank(for: preferredContinuityCandidate, matchContext: matchContext) <
            simpleContinuityGuardRank(for: geometricContinuityCandidate, matchContext: matchContext) {
            trace = MatchSelectionTrace(
                step: continuityIdentity.source == .streetName
                    ? "simple_same_name_route_class_guard"
                    : "simple_same_ref_route_class_guard",
                detail: "kept \(continuityIdentity.source.traceLabel) \(preferredContinuityCandidate.wayID ?? "nil") over closer \(geometricContinuityCandidate.wayID ?? "nil") preferred_highway=\(matchContext.preferredHighway ?? "nil")"
            )
        } else {
            trace = nil
        }
        return (preferredContinuityCandidate, trace)
    }

    private func simpleContinuityGuardRank(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> Int {
        var rank = 0
        if let preferredFamily = highwayFamily(matchContext.preferredHighway) {
            if highwayFamily(candidate.highway) != preferredFamily {
                rank += 4
            }
        }
        if isServiceLikeTransitionCandidate(candidate) {
            rank += 2
        }
        if matchContext.isInTunnelMode != isTruthyOSMTag(candidate.tunnel) {
            rank += 1
        }
        return rank
    }

    private func lowSpeedSameRefJunctionAnchorCandidates(
        in candidates: [WayCandidate],
        currentCandidate: WayCandidate,
        continuityRefTokens: Set<String>,
        matchContext: NormalizedMatchContext
    ) -> [WayCandidate] {
        var anchorWayIDs: [String] = []
        if let preferredWayID = matchContext.preferredWayID {
            anchorWayIDs.append(preferredWayID)
        }
        anchorWayIDs.append(contentsOf: matchContext.recentWayHistory)
        anchorWayIDs.append(contentsOf: matchContext.recentWayIDs)
        if let currentWayID = normalizedWayID(currentCandidate.wayID) {
            anchorWayIDs.append(currentWayID)
        }

        var seenWayIDs = Set<String>()
        var anchors: [WayCandidate] = []
        for wayID in anchorWayIDs {
            guard seenWayIDs.insert(wayID).inserted,
                  let candidate = candidates.first(where: {
                    normalizedWayID($0.wayID) == wayID
                  }) else {
                continue
            }
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            if !continuityRefTokens.isEmpty &&
                (candidateRefTokens.isEmpty || candidateRefTokens.isDisjoint(with: continuityRefTokens)) {
                continue
            }
            anchors.append(candidate)
        }
        if anchors.isEmpty {
            anchors.append(currentCandidate)
        }
        return anchors
    }

    private func continuityTokens(
        for candidate: WayCandidate,
        source: SimpleContinuityIdentitySource,
        useStreetNameFallbackContinuity: Bool
    ) -> Set<String> {
        let refTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        if !refTokens.isEmpty {
            return refTokens
        }
        if useStreetNameFallbackContinuity, source == .streetName {
            return Set(Self.normalizedStreetNameTokens(candidate.streetBaseName ?? candidate.streetName))
        }
        return []
    }

    private func isUrbanSameRefReleaseSourceHighway(_ highway: String?) -> Bool {
        switch (highway ?? "").lowercased() {
        case "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street":
            return true
        default:
            return false
        }
    }

    private func isUrbanSameRefReleaseTargetHighway(_ highway: String?) -> Bool {
        switch (highway ?? "").lowercased() {
        case "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street":
            return true
        default:
            return false
        }
    }

    private func shouldEnableUrbanSameRefRelease(
        sameRefCandidate: WayCandidate,
        bestCandidate: WayCandidate
    ) -> Bool {
        guard isUrbanSameRefReleaseSourceHighway(sameRefCandidate.highway),
              isUrbanSameRefReleaseTargetHighway(bestCandidate.highway),
              bestCandidate.distanceM <= Self.simpleSameRefUrbanReleaseMaxBestDistanceM else {
            return false
        }
        let distanceGapM = sameRefCandidate.distanceM - bestCandidate.distanceM
        return distanceGapM >= Self.simpleSameRefUrbanReleaseMinDistanceGapM
    }

    private func isServiceLikeTransitionCandidate(_ candidate: WayCandidate) -> Bool {
        if (candidate.highway ?? "").lowercased() == "service" {
            return true
        }
        switch (candidate.service ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "driveway", "parking_aisle", "alley", "emergency_access", "drive-through",
             "yard", "bus", "delivery", "parking", "busbay", "siding", "spur",
             "slipway", "weigh_station", "training":
            return true
        default:
            return false
        }
    }

    private func selectMiniHMMCandidate(
        from candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        preferredCandidate: WayCandidate?,
        sameRefTransitionCandidate: WayCandidate?,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext
    ) -> MiniHMMSelection {
        guard shouldUseMiniHMM(
            candidates: candidates,
            matchContext: matchContext,
            preferredCandidate: preferredCandidate,
            sameRefTransitionCandidate: sameRefTransitionCandidate
        ) else {
            return MiniHMMSelection(selectedCandidate: nil, selectedCorridorState: nil, hypotheses: [], used: false, candidateCount: 0)
        }

        let beamCandidates = Array(candidates.prefix(Self.miniHMMBeamWidth))
        guard !beamCandidates.isEmpty else {
            return MiniHMMSelection(selectedCandidate: nil, selectedCorridorState: nil, hypotheses: [], used: false, candidateCount: 0)
        }

        let signalEvidence = signalQualityEvidence(
            matchContext: matchContext,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        )
        let accuracyBufferM = scaledAccuracyBufferM(horizontalAccuracyM)
        var hypotheses: [WayMatchHypothesis] = []
        hypotheses.reserveCapacity(beamCandidates.count * 3)

        for candidate in beamCandidates {
            guard let wayID = normalizedWayID(candidate.wayID) else {
                continue
            }
            let candidateCorridorState = candidateCorridorState(
                for: candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                progressContext: progressContext
            )
            for corridorSequenceState in corridorSequenceStates(for: candidate) {
                let emission = candidate.score
                    + miniHMMPriorAdjustment(for: candidate, matchContext: matchContext)
                    + corridorEmissionPenalty(
                        for: candidate,
                        candidateCorridorState: candidateCorridorState,
                        corridorState: corridorSequenceState,
                        matchContext: matchContext,
                        signalEvidence: signalEvidence,
                        wayLinks: wayLinks
                    )
                let cumulativeCost: Double
                if matchContext.recentHypotheses.isEmpty {
                    cumulativeCost = emission
                } else {
                    var bestPathCost = Double.infinity
                    for hypothesis in matchContext.recentHypotheses {
                        let pathCost = (hypothesis.cumulativeCost * Self.miniHMMHistoryDecay)
                            + transitionPenalty(
                                from: hypothesis,
                                to: candidate,
                                corridorState: corridorSequenceState,
                                observedHeadingDeg: observedHeadingDeg,
                                speedKmh: speedKmh,
                                matchContext: matchContext,
                                signalEvidence: signalEvidence,
                                wayLinks: wayLinks,
                                accuracyBufferM: accuracyBufferM,
                                candidateCorridorState: candidateCorridorState,
                                pairContext: pairContext
                            )
                            + emission
                        if pathCost < bestPathCost {
                            bestPathCost = pathCost
                        }
                    }
                    cumulativeCost = bestPathCost.isFinite ? bestPathCost : emission
                }

                hypotheses.append(
                    WayMatchHypothesis(
                        wayID: wayID,
                        streetRef: candidate.streetRef,
                        highway: candidate.highway,
                        corridorState: corridorSequenceState.rawValue,
                        corridorKind: candidateCorridorState?.snapshot.kind,
                        corridorID: candidateCorridorState?.snapshot.corridorID,
                        corridorSideNodeKey: candidateCorridorState?.snapshot.sideNodeKey,
                        cumulativeCost: cumulativeCost,
                        emissionScore: candidate.score,
                        endpointProximityM: candidate.endpointProximityM,
                        startLat: candidate.startPoint?.0,
                        startLon: candidate.startPoint?.1,
                        endLat: candidate.endPoint?.0,
                        endLon: candidate.endPoint?.1,
                        isTunnel: isTruthyOSMTag(candidate.tunnel)
                    )
                )
            }
        }

        hypotheses.sort { lhs, rhs in
            if lhs.cumulativeCost != rhs.cumulativeCost {
                return lhs.cumulativeCost < rhs.cumulativeCost
            }
            if lhs.emissionScore != rhs.emissionScore {
                return lhs.emissionScore < rhs.emissionScore
            }
            if lhs.wayID != rhs.wayID {
                return lhs.wayID < rhs.wayID
            }
            return (lhs.corridorState ?? "~") < (rhs.corridorState ?? "~")
        }
        if hypotheses.count > Self.miniHMMBeamWidth {
            hypotheses.removeLast(hypotheses.count - Self.miniHMMBeamWidth)
        }

        let selectedWayID = hypotheses.first?.wayID
        let selectedCorridorState = hypotheses.first.flatMap { corridorSequenceState(from: $0) }
        let selectedCandidate = beamCandidates.first { normalizedWayID($0.wayID) == selectedWayID }
        return MiniHMMSelection(
            selectedCandidate: selectedCandidate,
            selectedCorridorState: selectedCorridorState,
            hypotheses: hypotheses,
            used: true,
            candidateCount: beamCandidates.count
        )
    }

    private func shouldUseMiniHMM(
        candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        preferredCandidate: WayCandidate?,
        sameRefTransitionCandidate: WayCandidate?
    ) -> Bool {
        if !matchContext.recentHypotheses.isEmpty {
            return candidates.count > 1
        }
        guard candidates.count > 1 else {
            return false
        }
        let best = candidates[0]
        let second = candidates[1]
        if second.score - best.score <= Self.miniHMMAmbiguousScoreGapM {
            return true
        }
        if let preferredCandidate,
           normalizedWayID(preferredCandidate.wayID) != normalizedWayID(best.wayID) {
            return true
        }
        if sameRefTransitionCandidate != nil {
            return true
        }
        if candidates.prefix(Self.miniHMMBeamWidth).contains(where: { isTruthyOSMTag($0.tunnel) }) {
            return true
        }
        return false
    }

    private func corridorSequenceState(from hypothesis: WayMatchHypothesis) -> CorridorSequenceState? {
        if let corridorState = hypothesis.corridorState,
           let parsed = CorridorSequenceState(rawValue: corridorState) {
            return parsed
        }
        if hypothesis.isTunnel {
            return .tunnelInside
        }
        switch (hypothesis.highway ?? "").lowercased() {
        case "motorway":
            return .motorwayInside
        case "motorway_link":
            return .motorwayPortal
        default:
            return .surface
        }
    }

    private func corridorSequenceStates(for candidate: WayCandidate) -> [CorridorSequenceState] {
        switch corridorState(for: candidate) {
        case .surface:
            return [.surface, .tunnelExit]
        case .tunnel:
            return [.tunnelPortal, .tunnelInside]
        case .motorway:
            return [.motorwayInside]
        case .motorwayLink:
            return [.motorwayPortal, .motorwayExit]
        }
    }

    private func isCommittedCorridorSelectionState(_ corridorState: CorridorSequenceState) -> Bool {
        switch corridorState {
        case .tunnelInside, .motorwayInside:
            return true
        default:
            return false
        }
    }

    private func shouldPromoteMiniHMMCorridorSelection(
        state: CorridorSequenceState,
        candidate: WayCandidate,
        candidateCorridorState: CandidateCorridorState,
        over heuristicCandidate: WayCandidate?,
        matchContext: NormalizedMatchContext,
        signalEvidence: SignalQualityEvidence
    ) -> Bool {
        guard isCommittedCorridorSelectionState(state) else {
            return false
        }

        let scoreSlackM: Double
        switch state {
        case .tunnelInside:
            let chainCommitScore = corridorChainCommitScore(
                for: candidateCorridorState,
                matchContext: matchContext
            )
            let tunnelEvidenceScore = max(
                signalEvidence.tunnelScore,
                max(
                    portalCommitProgressScore(for: candidate, matchContext: matchContext),
                    chainCommitScore
                )
            )
            guard signalEvidence.hadRecentGPSSignalLoss ||
                    chainCommitScore >= Self.corridorStateTunnelChainCommitMinScore ||
                    (tunnelEvidenceScore >= Self.corridorStateTunnelOutputMinScore &&
                     matchesTunnelApproachCandidate(candidate, matchContext: matchContext)) else {
                return false
            }
            scoreSlackM = Self.corridorStateTunnelOutputScoreSlackM +
                (chainCommitScore * Self.corridorStateTunnelChainSlackBonusM)
        case .motorwayInside:
            scoreSlackM = Self.corridorStateMotorwayOutputScoreSlackM
        default:
            return false
        }

        guard let heuristicCandidate else {
            return true
        }
        return candidate.score <= heuristicCandidate.score + scoreSlackM
    }

    private func shouldKeepSurfaceHeuristicOverUncommittedTunnelCandidate(
        state: CorridorSequenceState,
        tunnelCandidate: WayCandidate,
        heuristicCandidate: WayCandidate
    ) -> Bool {
        guard isTruthyOSMTag(tunnelCandidate.tunnel),
              !isTruthyOSMTag(heuristicCandidate.tunnel) else {
            return false
        }
        switch state {
        case .tunnelPortal, .tunnelInside:
            return true
        default:
            return false
        }
    }

    private func corridorEmissionPenalty(
        for candidate: WayCandidate,
        candidateCorridorState: CandidateCorridorState?,
        corridorState: CorridorSequenceState,
        matchContext: NormalizedMatchContext,
        signalEvidence: SignalQualityEvidence,
        wayLinks: WayLinksContext
    ) -> Double {
        let candidateClass = self.corridorState(for: candidate)
        let chainCommitScore = corridorChainCommitScore(
            for: candidateCorridorState,
            matchContext: matchContext
        )
        switch corridorState {
        case .surface:
            guard candidateClass == .surface else {
                return Self.corridorStateIllegalPenaltyM
            }
            return 0.0
        case .tunnelPortal:
            guard candidateClass == .tunnel else {
                return Self.corridorStateIllegalPenaltyM
            }
            var penalty = 6.0
            if matchesTunnelApproachCandidate(candidate, matchContext: matchContext) {
                penalty -= 1.5
            }
            let portalEvidenceScore = max(
                signalEvidence.tunnelScore,
                portalMotionProgressScore(for: candidate, matchContext: matchContext)
            )
            penalty -= portalEvidenceScore * Self.corridorStateTunnelSignalRewardM
            penalty -= chainCommitScore * (Self.corridorStateTunnelChainRewardM * 0.35)
            return penalty
        case .tunnelInside:
            guard candidateClass == .tunnel else {
                return Self.corridorStateIllegalPenaltyM
            }
            var penalty = 4.0
            let candidateWayID = normalizedWayID(candidate.wayID)
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            if let candidateWayID, matchContext.recentTunnelCandidateWayIDs.contains(candidateWayID) {
                penalty -= Self.corridorStateTunnelPersistenceRewardM
            } else if !candidateRefTokens.isEmpty,
                      !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelCandidateRefs) {
                penalty -= Self.corridorStateTunnelPersistenceRewardM * 0.5
            }
            let tunnelEvidenceScore = max(
                signalEvidence.tunnelScore,
                max(
                    portalCommitProgressScore(for: candidate, matchContext: matchContext),
                    chainCommitScore
                )
            )
            penalty -= tunnelEvidenceScore * (Self.corridorStateTunnelSignalRewardM * 0.5)
            penalty -= chainCommitScore * Self.corridorStateTunnelChainRewardM
            return penalty
        case .tunnelExit:
            guard candidateClass == .surface else {
                return Self.corridorStateIllegalPenaltyM
            }
            return 4.0
        case .motorwayPortal:
            guard candidateClass == .motorwayLink else {
                return Self.corridorStateIllegalPenaltyM
            }
            return -Self.corridorStateMotorwayRewardM
        case .motorwayInside:
            guard candidateClass == .motorway else {
                return Self.corridorStateIllegalPenaltyM
            }
            return -(Self.corridorStateMotorwayRewardM + 1.0)
        case .motorwayExit:
            guard candidateClass == .motorwayLink else {
                return Self.corridorStateIllegalPenaltyM
            }
            return -Self.corridorStateMotorwayRewardM
        }
    }

    private func miniHMMPriorAdjustment(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> Double {
        var adjustment = 0.0
        let candidateWayID = normalizedWayID(candidate.wayID)
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))

        if candidateWayID == matchContext.preferredWayID {
            adjustment -= 8.0
        } else if let candidateWayID, matchContext.recentWayIDs.contains(candidateWayID) {
            adjustment -= 2.5
        }

        if !candidateRefTokens.isEmpty,
           (!candidateRefTokens.isDisjoint(with: matchContext.preferredStreetRefs) ||
            !candidateRefTokens.isDisjoint(with: matchContext.recentStreetRefs)) {
            adjustment -= 3.5
        }

        let recentTunnelWayMatch = candidateWayID.map { matchContext.recentTunnelCandidateWayIDs.contains($0) } ?? false
        if matchContext.isInTunnelMode {
            adjustment += isTruthyOSMTag(candidate.tunnel) ? -6.0 : 10.0
        }
        if isTruthyOSMTag(candidate.tunnel),
           matchContext.hadRecentGPSSignalLoss,
           (recentTunnelWayMatch || !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelCandidateRefs)) {
            adjustment -= 2.0
        }
        return adjustment
    }

    private func transitionPenalty(
        from hypothesis: WayMatchHypothesis,
        to candidate: WayCandidate,
        corridorState: CorridorSequenceState,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        matchContext: NormalizedMatchContext,
        signalEvidence: SignalQualityEvidence,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        candidateCorridorState: CandidateCorridorState?,
        pairContext: CorridorPairContext
    ) -> Double {
        let wayPenalty = genericTransitionPenalty(
            from: hypothesis,
            to: candidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
        let statePenalty = corridorStateTransitionPenalty(
            from: hypothesis,
            to: candidate,
            corridorState: corridorState,
            matchContext: matchContext,
            signalEvidence: signalEvidence,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM,
            candidateCorridorState: candidateCorridorState,
            pairContext: pairContext
        )
        return wayPenalty + statePenalty
    }

    private func genericTransitionPenalty(
        from hypothesis: WayMatchHypothesis,
        to candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Double {
        guard let candidateWayID = normalizedWayID(candidate.wayID) else {
            return Self.miniHMMUnrelatedTransitionPenaltyM
        }
        if candidateWayID == hypothesis.wayID {
            return 0.0
        }

        let basePenalty: Double
        if wayLinks.isSharedRefLinked(from: hypothesis.wayID, to: candidateWayID) {
            basePenalty = Self.miniHMMSharedRefLinkedTransitionPenaltyM
        } else if wayLinks.isLinked(from: hypothesis.wayID, to: candidateWayID) {
            basePenalty = Self.miniHMMLinkedWayTransitionPenaltyM
        } else {
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            let previousRefTokens = Set(Self.normalizedRefTokens(hypothesis.streetRef))
            if !candidateRefTokens.isEmpty,
               !candidateRefTokens.isDisjoint(with: previousRefTokens) {
                if wayLinks.available {
                    basePenalty = Self.miniHMMUnrelatedTransitionPenaltyM
                } else {
                    let endpointThreshold = Self.segmentTransitionEndpointThresholdM
                    if hypothesis.endpointProximityM <= endpointThreshold ||
                        candidate.endpointProximityM <= endpointThreshold * 2.0 {
                        basePenalty = 1.5
                    } else {
                        basePenalty = Self.miniHMMSameRefTransitionPenaltyM
                    }
                }
            } else if matchContext.recentWayIDs.contains(candidateWayID) {
                basePenalty = Self.miniHMMRecentWayTransitionPenaltyM
            } else if !wayLinks.available,
                        hasEndpointContinuation(from: hypothesis, to: candidate) {
                basePenalty = Self.miniHMMEndpointConnectionPenaltyM
            } else if let previousHighway = hypothesis.highway?.lowercased(),
                      let currentHighway = candidate.highway?.lowercased(),
                      previousHighway == currentHighway {
                basePenalty = Self.miniHMMHighwayClassTransitionPenaltyM
            } else {
                basePenalty = Self.miniHMMUnrelatedTransitionPenaltyM
            }
        }

        let bouncePenalty = isImmediateSameRefBounceTransition(
            from: hypothesis,
            to: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks
        ) ? Self.sameRefBouncePenaltyM : 0.0

        let headingAdjustment = transitionHeadingPenaltyAdjustment(
            fromAxisHeadingDeg: axisHeadingDeg(from: hypothesis.startLat, lon1: hypothesis.startLon, to: hypothesis.endLat, lon2: hypothesis.endLon),
            fromEndpointProximityM: hypothesis.endpointProximityM,
            to: candidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh
        )
        return max(0.0, basePenalty + bouncePenalty + headingAdjustment)
    }

    private func corridorStateTransitionPenalty(
        from hypothesis: WayMatchHypothesis,
        to candidate: WayCandidate,
        corridorState nextState: CorridorSequenceState,
        matchContext: NormalizedMatchContext,
        signalEvidence: SignalQualityEvidence,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        candidateCorridorState: CandidateCorridorState?,
        pairContext: CorridorPairContext
    ) -> Double {
        let previousState = corridorSequenceState(from: hypothesis) ?? .surface
        let previousCorridorSnapshot = hypothesisCorridorSnapshot(hypothesis)
        let candidateSnapshot = candidateCorridorState?.snapshot
        let previousAnchor = CorridorAnchor(
            wayID: hypothesis.wayID,
            highway: hypothesis.highway,
            endpointProximityM: hypothesis.endpointProximityM,
            isInTunnelMode: previousState == .tunnelPortal || previousState == .tunnelInside
        )
        let candidateWayID = normalizedWayID(candidate.wayID)
        let linkedToPrevious = areLinkedWays(hypothesis.wayID, candidateWayID, wayLinks: wayLinks)
        let sharedRefLinkedToPrevious = areSharedRefLinkedWays(hypothesis.wayID, candidateWayID, wayLinks: wayLinks)
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        let previousRefTokens = Set(Self.normalizedRefTokens(hypothesis.streetRef))
        let sharesRefWithPrevious = !candidateRefTokens.isEmpty && !candidateRefTokens.isDisjoint(with: previousRefTokens)
        let portalMotionScore = portalMotionProgressScore(for: candidate, matchContext: matchContext)
        let portalCommitScore = portalCommitProgressScore(for: candidate, matchContext: matchContext)
        let tunnelPortalTransition = isTunnelPortalTransition(
            from: previousAnchor,
            to: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM,
            entry: previousState == .surface || previousState == .tunnelPortal
        )
        let motorwayTransition = isMotorwayTransitionCandidate(
            from: previousAnchor,
            to: candidate,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM
        )

        if pairContext.available,
           let previousCorridorSnapshot,
           let candidateSnapshot {
            if previousCorridorSnapshot.kind == candidateSnapshot.kind,
               previousCorridorSnapshot.corridorID == candidateSnapshot.corridorID,
               previousCorridorSnapshot.sideNodeKey == candidateSnapshot.sideNodeKey {
                switch (previousState, nextState, candidateSnapshot.kind) {
                case (.surface, .surface, "surface"):
                    return Self.corridorStatePersistencePenaltyM
                case (.motorwayPortal, .motorwayPortal, "motorway_link"),
                     (.motorwayExit, .motorwayExit, "motorway_link"):
                    return Self.corridorStatePersistencePenaltyM
                case (.tunnelPortal, .tunnelPortal, "tunnel"),
                     (.tunnelInside, .tunnelInside, "tunnel"):
                    return Self.corridorStatePersistencePenaltyM - Self.corridorStateTunnelPersistenceRewardM
                case (.motorwayInside, .motorwayInside, "motorway"):
                    return Self.corridorStatePersistencePenaltyM - Self.corridorStateMotorwayRewardM
                default:
                    break
                }
            }

            if previousCorridorSnapshot.kind == "surface",
               candidateSnapshot.kind == "tunnel",
               isPairedWithMainCorridor(
                    pairedSnapshot: previousCorridorSnapshot,
                    mainSnapshot: candidateSnapshot,
                    pairContext: pairContext
               ) {
                switch nextState {
                case .tunnelPortal:
                    let tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalMotionScore)
                    return Self.corridorStateExpectedTransitionPenaltyM - (tunnelEvidenceScore * Self.corridorStateTunnelSignalRewardM)
                case .tunnelInside:
                    let tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalCommitScore)
                    return Self.corridorStateReentryPenaltyM - (tunnelEvidenceScore * Self.corridorStateTunnelSignalRewardM)
                default:
                    break
                }
            }

            if previousCorridorSnapshot.kind == "tunnel",
               candidateSnapshot.kind == "surface",
               isMainCorridorPairedToCandidate(
                    mainSnapshot: previousCorridorSnapshot,
                    candidateSnapshot: candidateSnapshot,
                    pairContext: pairContext,
                    requireOppositeSide: true
               ) {
                switch nextState {
                case .tunnelExit, .surface:
                    return Self.corridorStateExpectedTransitionPenaltyM
                default:
                    break
                }
            }

            if previousCorridorSnapshot.kind == "motorway_link",
               candidateSnapshot.kind == "motorway",
               isPairedWithMainCorridor(
                    pairedSnapshot: previousCorridorSnapshot,
                    mainSnapshot: candidateSnapshot,
                    pairContext: pairContext
               ) {
                if nextState == .motorwayInside {
                    return Self.corridorStateExpectedTransitionPenaltyM - Self.corridorStateMotorwayRewardM
                }
            }

            if previousCorridorSnapshot.kind == "motorway",
               candidateSnapshot.kind == "motorway_link",
               isMainCorridorPairedToCandidate(
                    mainSnapshot: previousCorridorSnapshot,
                    candidateSnapshot: candidateSnapshot,
                    pairContext: pairContext,
                    requireOppositeSide: true
               ) {
                if nextState == .motorwayExit {
                    return Self.corridorStateExpectedTransitionPenaltyM
                }
            }
        }

        switch (previousState, nextState) {
        case (.surface, .surface):
            return Self.corridorStatePersistencePenaltyM
        case (.surface, .tunnelPortal):
            if tunnelPortalTransition {
                let tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalMotionScore)
                return Self.corridorStateExpectedTransitionPenaltyM - (tunnelEvidenceScore * Self.corridorStateTunnelSignalRewardM)
            }
            return Self.corridorStateIllegalPenaltyM
        case (.surface, .tunnelInside):
            if matchesTunnelApproachCandidate(candidate, matchContext: matchContext),
               (signalEvidence.hadRecentGPSSignalLoss ||
                signalEvidence.tunnelScore >= Self.corridorStateTunnelDirectCommitMinScore ||
                portalCommitScore >= Self.corridorStateTunnelDirectCommitMinScore) {
                let tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalCommitScore)
                return Self.corridorStateReentryPenaltyM - (tunnelEvidenceScore * Self.corridorStateTunnelSignalRewardM)
            }
            return Self.corridorStateIllegalPenaltyM
        case (.surface, .motorwayPortal):
            return motorwayTransition ? Self.corridorStateExpectedTransitionPenaltyM : Self.corridorStateIllegalPenaltyM
        case (.surface, .motorwayInside), (.surface, .motorwayExit), (.surface, .tunnelExit):
            return Self.corridorStateIllegalPenaltyM
        case (.tunnelPortal, .surface):
            return Self.corridorStateReentryPenaltyM
        case (.tunnelPortal, .tunnelPortal):
            return (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) ? Self.corridorStatePersistencePenaltyM : Self.corridorStateIllegalPenaltyM
        case (.tunnelPortal, .tunnelInside):
            return (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) ? Self.corridorStateExpectedTransitionPenaltyM - Self.corridorStateTunnelPersistenceRewardM : Self.corridorStateIllegalPenaltyM
        case (.tunnelPortal, .tunnelExit), (.tunnelPortal, .motorwayPortal), (.tunnelPortal, .motorwayInside), (.tunnelPortal, .motorwayExit):
            return Self.corridorStateIllegalPenaltyM
        case (.tunnelInside, .tunnelPortal):
            return (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) ? Self.corridorStatePersistencePenaltyM : Self.corridorStateIllegalPenaltyM
        case (.tunnelInside, .tunnelInside):
            return (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) ? Self.corridorStatePersistencePenaltyM - Self.corridorStateTunnelPersistenceRewardM : Self.corridorStateIllegalPenaltyM
        case (.tunnelInside, .tunnelExit):
            return tunnelPortalTransition ? Self.corridorStateExpectedTransitionPenaltyM : Self.corridorStateIllegalPenaltyM
        case (.tunnelInside, .surface):
            return Self.corridorStateIllegalPenaltyM
        case (.tunnelInside, .motorwayPortal), (.tunnelInside, .motorwayInside), (.tunnelInside, .motorwayExit):
            return Self.corridorStateIllegalPenaltyM
        case (.tunnelExit, .surface):
            return (linkedToPrevious || sharesRefWithPrevious || candidateWayID == hypothesis.wayID) ? Self.corridorStateExpectedTransitionPenaltyM : Self.corridorStateIllegalPenaltyM
        case (.tunnelExit, .tunnelInside):
            return Self.corridorStateReentryPenaltyM
        case (.tunnelExit, .tunnelPortal), (.tunnelExit, .tunnelExit), (.tunnelExit, .motorwayPortal), (.tunnelExit, .motorwayInside), (.tunnelExit, .motorwayExit):
            return Self.corridorStateIllegalPenaltyM
        case (.motorwayPortal, .surface):
            return Self.corridorStateReentryPenaltyM
        case (.motorwayPortal, .motorwayPortal):
            return motorwayTransition ? Self.corridorStatePersistencePenaltyM : Self.corridorStateIllegalPenaltyM
        case (.motorwayPortal, .motorwayInside):
            return motorwayTransition ? Self.corridorStateExpectedTransitionPenaltyM - Self.corridorStateMotorwayRewardM : Self.corridorStateIllegalPenaltyM
        case (.motorwayPortal, .motorwayExit):
            return motorwayTransition ? Self.corridorStateExpectedTransitionPenaltyM : Self.corridorStateIllegalPenaltyM
        case (.motorwayPortal, .tunnelPortal), (.motorwayPortal, .tunnelInside), (.motorwayPortal, .tunnelExit):
            return Self.corridorStateIllegalPenaltyM
        case (.motorwayInside, .motorwayInside):
            return (linkedToPrevious || sharesRefWithPrevious) ? Self.corridorStatePersistencePenaltyM - Self.corridorStateMotorwayRewardM : Self.corridorStateIllegalPenaltyM
        case (.motorwayInside, .motorwayExit):
            return motorwayTransition ? Self.corridorStateExpectedTransitionPenaltyM : Self.corridorStateIllegalPenaltyM
        case (.motorwayInside, .surface), (.motorwayInside, .motorwayPortal), (.motorwayInside, .tunnelPortal), (.motorwayInside, .tunnelInside), (.motorwayInside, .tunnelExit):
            return Self.corridorStateIllegalPenaltyM
        case (.motorwayExit, .surface):
            return (linkedToPrevious || sharesRefWithPrevious || hasEndpointContinuation(from: hypothesis, to: candidate)) ? Self.corridorStateExpectedTransitionPenaltyM : Self.corridorStateIllegalPenaltyM
        case (.motorwayExit, .motorwayExit):
            return motorwayTransition ? Self.corridorStatePersistencePenaltyM : Self.corridorStateIllegalPenaltyM
        case (.motorwayExit, .motorwayPortal), (.motorwayExit, .motorwayInside), (.motorwayExit, .tunnelPortal), (.motorwayExit, .tunnelInside), (.motorwayExit, .tunnelExit):
            return Self.corridorStateIllegalPenaltyM
        }
    }

    private func hasEndpointContinuation(
        from hypothesis: WayMatchHypothesis,
        to candidate: WayCandidate
    ) -> Bool {
        guard let previousFamily = highwayFamily(hypothesis.highway),
              let currentFamily = highwayFamily(candidate.highway),
              previousFamily == currentFamily else {
            return false
        }
        guard hypothesis.endpointProximityM <= Self.miniHMMEndpointCandidateThresholdM,
              candidate.endpointProximityM <= Self.miniHMMEndpointCandidateThresholdM else {
            return false
        }

        let previousEndpoints = hypothesis.endpoints
        let currentEndpoints = [candidate.startPoint, candidate.endPoint].compactMap { $0 }
        guard !previousEndpoints.isEmpty, !currentEndpoints.isEmpty else {
            return false
        }

        let bestConnection = previousEndpoints.reduce(Double.infinity) { partialBest, previous in
            let currentBest = currentEndpoints.reduce(Double.infinity) { candidateBest, current in
                min(
                    candidateBest,
                    haversineM(lat1: previous.0, lon1: previous.1, lat2: current.0, lon2: current.1)
                )
            }
            return min(partialBest, currentBest)
        }
        return bestConnection <= Self.miniHMMEndpointConnectionThresholdM
    }

    private func loadWayContinuityContext(
        db: OpaquePointer,
        layers: [SimpleSequenceViterbiLayer],
        matchContext: NormalizedMatchContext
    ) -> WayContinuityContext {
        guard tableExists(db: db, name: "way_continuity_membership") else {
            return WayContinuityContext(available: false, byWayID: [:])
        }

        var relevantWayIDs = Set(layers.flatMap { layer in
            layer.candidates.compactMap { normalizedWayID($0.wayID) }
        })
        relevantWayIDs.formUnion(matchContext.recentWayIDs)
        relevantWayIDs.formUnion(matchContext.recentHypotheses.map(\.wayID))
        if let preferredWayID = matchContext.preferredWayID {
            relevantWayIDs.insert(preferredWayID)
        }
        let orderedWayIDs = relevantWayIDs.compactMap { Int64($0) }.sorted()
        guard !orderedWayIDs.isEmpty else {
            return WayContinuityContext(available: true, byWayID: [:])
        }

        let placeholders = Array(repeating: "?", count: orderedWayIDs.count).joined(separator: ",")
        let hasMembershipKind = columnExists(db: db, table: "way_continuity_membership", column: "continuity_kind")
        let hasGroupTable = tableExists(db: db, name: "way_continuity_group")
        guard hasMembershipKind || hasGroupTable else {
            return WayContinuityContext(available: true, byWayID: [:])
        }
        let kindSelect = hasMembershipKind ? "m.continuity_kind" : "g.continuity_kind"
        let joinClause = hasMembershipKind ? "" : "JOIN way_continuity_group g ON g.continuity_group_id = m.continuity_group_id"
        let sql = """
        SELECT m.way_id, m.continuity_group_id, \(kindSelect)
        FROM way_continuity_membership m
        \(joinClause)
        WHERE m.way_id IN (\(placeholders))
        """

        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return WayContinuityContext(available: true, byWayID: [:])
        }

        for (index, wayID) in orderedWayIDs.enumerated() {
            sqlite3_bind_int64(stmt, Int32(index + 1), wayID)
        }

        var byWayID: [String: WayContinuityMembershipInfo] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            let wayID = String(sqlite3_column_int64(stmt, 0))
            let continuityGroupID = Int(sqlite3_column_int(stmt, 1))
            guard !wayID.isEmpty, continuityGroupID != 0,
                  let rawKind = cStringOptional(sqlite3_column_text(stmt, 2)),
                  let kind = WayContinuityKind(rawValue: rawKind) else {
                continue
            }
            var info = byWayID[wayID] ?? WayContinuityMembershipInfo()
            switch kind {
            case .routeRelationConnected:
                info.routeRelationGroupIDs.insert(continuityGroupID)
            case .sameStreetNameConnected:
                info.sameStreetNameGroupIDs.insert(continuityGroupID)
            }
            byWayID[wayID] = info
        }

        return WayContinuityContext(available: true, byWayID: byWayID)
    }

    /// Returns only the route-relation memberships that are safe for a live
    /// camera assertion. Broad same-name continuity is intentionally excluded.
    /// Schema/statement failures fail closed as capability unavailable.
    private func loadSelectedRouteContinuity(
        db: OpaquePointer,
        wayID: String?
    ) -> (available: Bool, memberships: [TrafficSignRouteRelationMembership]) {
        guard tableExists(db: db, name: "way_continuity_membership"),
              tableExists(db: db, name: "way_continuity_group"),
              routeRelationContinuityDeclared(db: db) else {
            return (false, [])
        }
        let hasMembershipKind = columnExists(
            db: db,
            table: "way_continuity_membership",
            column: "continuity_kind"
        )
        let hasGroupTable = tableExists(db: db, name: "way_continuity_group")
        guard hasMembershipKind || hasGroupTable else { return (false, []) }
        guard let wayID = normalizedWayID(wayID), let numericWayID = Int64(wayID) else {
            return (true, [])
        }

        let sql: String
        if hasGroupTable {
            let kindExpression = hasMembershipKind ? "m.continuity_kind" : "g.continuity_kind"
            let sourceExpression = columnExists(
                db: db,
                table: "way_continuity_group",
                column: "source_relation_id"
            ) ? "g.source_relation_id" : "NULL"
            sql = """
            SELECT m.continuity_group_id, \(sourceExpression)
            FROM way_continuity_membership m
            JOIN way_continuity_group g
              ON g.continuity_group_id = m.continuity_group_id
            WHERE m.way_id = ? AND \(kindExpression) = ?
            ORDER BY m.continuity_group_id
            """
        } else {
            sql = """
            SELECT m.continuity_group_id, NULL
            FROM way_continuity_membership m
            WHERE m.way_id = ? AND m.continuity_kind = ?
            ORDER BY m.continuity_group_id
            """
        }

        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return (false, [])
        }
        sqlite3_bind_int64(stmt, 1, numericWayID)
        sqlite3_bind_text(
            stmt,
            2,
            WayContinuityKind.routeRelationConnected.rawValue,
            -1,
            SQLITE_TRANSIENT
        )

        var memberships: [TrafficSignRouteRelationMembership] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let groupID = Int(sqlite3_column_int64(stmt, 0))
            let sourceRelationID = sqlite3_column_type(stmt, 1) == SQLITE_NULL
                ? nil
                : sqlite3_column_int64(stmt, 1)
            let membership = TrafficSignRouteRelationMembership(
                groupID: groupID,
                sourceRelationID: sourceRelationID
            )
            if membership.isValid { memberships.append(membership) }
        }
        return (true, memberships)
    }

    /// Table presence alone is not a capability signal: fallback bundles may
    /// contain only same-street-name groups. Require the build metadata to opt
    /// in to route-relation continuity before it can extend a camera assertion.
    private func routeRelationContinuityDeclared(db: OpaquePointer) -> Bool {
        guard tableExists(db: db, name: "metadata") else { return false }
        let sql = "SELECT value FROM metadata WHERE key = 'way_continuity_mode' LIMIT 1"
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK,
              let stmt,
              sqlite3_step(stmt) == SQLITE_ROW,
              let value = cStringOptional(sqlite3_column_text(stmt, 0)) else { return false }
        return value.split(separator: "+").contains {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
                == WayContinuityKind.routeRelationConnected.rawValue
        }
    }

    private func loadWayLinksContext(
        db: OpaquePointer,
        candidates: [WayCandidate],
        matchContext: NormalizedMatchContext
    ) -> WayLinksContext {
        guard tableExists(db: db, name: "way_links") else {
            return WayLinksContext(available: false, byWayID: [:])
        }

        var relevantWayIDs = Set(candidates.compactMap { normalizedWayID($0.wayID) })
        relevantWayIDs.formUnion(matchContext.recentWayIDs)
        relevantWayIDs.formUnion(matchContext.recentHypotheses.map(\.wayID))
        if let preferredWayID = matchContext.preferredWayID {
            relevantWayIDs.insert(preferredWayID)
        }
        let orderedWayIDs = relevantWayIDs.compactMap { Int64($0) }.sorted()
        guard !orderedWayIDs.isEmpty else {
            return WayLinksContext(available: true, byWayID: [:])
        }

        let placeholders = Array(repeating: "?", count: orderedWayIDs.count).joined(separator: ",")
        let hasSharedRef = columnExists(db: db, table: "way_links", column: "shared_ref")
        let hasSharedNodeKey = columnExists(db: db, table: "way_links", column: "shared_node_key")
        let sharedRefSelect = hasSharedRef ? "shared_ref" : "0 AS shared_ref"
        let sharedNodeKeySelect = hasSharedNodeKey ? "shared_node_key" : "NULL AS shared_node_key"
        let sql = """
        SELECT way_id, linked_way_id, \(sharedRefSelect), \(sharedNodeKeySelect)
        FROM way_links
        WHERE way_id IN (\(placeholders))
        """

        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return WayLinksContext(available: true, byWayID: [:])
        }

        for (index, wayID) in orderedWayIDs.enumerated() {
            sqlite3_bind_int64(stmt, Int32(index + 1), wayID)
        }

        var byWayID: [String: WayLinkInfo] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            let sourceWayID = String(sqlite3_column_int64(stmt, 0))
            let linkedWayID = String(sqlite3_column_int64(stmt, 1))
            guard !sourceWayID.isEmpty, !linkedWayID.isEmpty else {
                continue
            }
            if sourceWayID == linkedWayID {
                continue
            }
            var info = byWayID[sourceWayID] ?? WayLinkInfo()
            info.linkedWayIDs.insert(linkedWayID)
            if sqlite3_column_int(stmt, 2) != 0 {
                info.sharedRefWayIDs.insert(linkedWayID)
            }
            if let sharedNodeKey = cStringOptional(sqlite3_column_text(stmt, 3)), !sharedNodeKey.isEmpty {
                var nodeKeys = info.sharedNodeKeysByLinkedWayID[linkedWayID] ?? []
                nodeKeys.insert(sharedNodeKey)
                info.sharedNodeKeysByLinkedWayID[linkedWayID] = nodeKeys
            }
            byWayID[sourceWayID] = info
        }
        return WayLinksContext(available: true, byWayID: byWayID)
    }

    private func loadCorridorProgressContext(
        db: OpaquePointer,
        candidates: [WayCandidate]
    ) -> CorridorProgressContext {
        guard tableExists(db: db, name: "corridor_progress") else {
            return CorridorProgressContext(available: false, byWayID: [:])
        }
        let orderedWayIDs = Set(candidates.compactMap { normalizedWayID($0.wayID) })
            .compactMap { Int64($0) }
            .sorted()
        guard !orderedWayIDs.isEmpty else {
            return CorridorProgressContext(available: true, byWayID: [:])
        }

        let hasNodeDepthColumns =
            columnExists(db: db, table: "corridor_progress", column: "start_depth_nodes") &&
            columnExists(db: db, table: "corridor_progress", column: "end_depth_nodes") &&
            columnExists(db: db, table: "corridor_progress", column: "corridor_span_nodes")
        let placeholders = Array(repeating: "?", count: orderedWayIDs.count).joined(separator: ",")
        let sql = """
        SELECT corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m, corridor_span_m\(hasNodeDepthColumns ? ", start_depth_nodes, end_depth_nodes, corridor_span_nodes" : "")
        FROM corridor_progress
        WHERE way_id IN (\(placeholders))
        """

        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return CorridorProgressContext(available: true, byWayID: [:])
        }
        for (index, wayID) in orderedWayIDs.enumerated() {
            sqlite3_bind_int64(stmt, Int32(index + 1), wayID)
        }

        var byWayID: [String: [CorridorProgressInfo]] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            let corridorKind = cStringOptional(sqlite3_column_text(stmt, 0)) ?? ""
            let corridorID = Int(sqlite3_column_int(stmt, 1))
            let sideNodeKey = cStringOptional(sqlite3_column_text(stmt, 2)) ?? ""
            let wayID = String(sqlite3_column_int64(stmt, 3))
            guard !corridorKind.isEmpty, !sideNodeKey.isEmpty, !wayID.isEmpty else {
                continue
            }
            let info = CorridorProgressInfo(
                kind: corridorKind,
                corridorID: corridorID,
                sideNodeKey: sideNodeKey,
                startDepthM: sqlite3_column_double(stmt, 4),
                endDepthM: sqlite3_column_double(stmt, 5),
                spanM: sqlite3_column_double(stmt, 6),
                startDepthNodes: hasNodeDepthColumns ? Int(sqlite3_column_int(stmt, 7)) : 0,
                endDepthNodes: hasNodeDepthColumns ? Int(sqlite3_column_int(stmt, 8)) : 0,
                spanNodes: hasNodeDepthColumns ? Int(sqlite3_column_int(stmt, 9)) : 0
            )
            byWayID[wayID, default: []].append(info)
        }
        return CorridorProgressContext(available: true, byWayID: byWayID)
    }

    private func corridorPairKey(
        kind: String,
        corridorID: Int,
        sideNodeKey: String
    ) -> String {
        "\(kind)#\(corridorID)#\(sideNodeKey)"
    }

    private func loadCorridorPairContext(
        db: OpaquePointer
    ) -> CorridorPairContext {
        corridorPairCacheLock.lock()
        defer { corridorPairCacheLock.unlock() }
        if let cachedCorridorPairContext {
            return cachedCorridorPairContext
        }
        guard tableExists(db: db, name: "corridor_pairs") else {
            let emptyContext = CorridorPairContext(available: false, byMainKey: [:], byPairedKey: [:])
            cachedCorridorPairContext = emptyContext
            return emptyContext
        }
        let sql = """
        SELECT corridor_kind, corridor_id, side_node_key, paired_kind, paired_corridor_id
        FROM corridor_pairs
        """
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            let emptyContext = CorridorPairContext(available: true, byMainKey: [:], byPairedKey: [:])
            cachedCorridorPairContext = emptyContext
            return emptyContext
        }

        var byMainKey: [String: [CorridorPairRelation]] = [:]
        var byPairedKey: [String: [CorridorPairRelation]] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            guard let corridorKind = cStringOptional(sqlite3_column_text(stmt, 0)),
                  let sideNodeKey = cStringOptional(sqlite3_column_text(stmt, 2)),
                  let pairedKind = cStringOptional(sqlite3_column_text(stmt, 3)),
                  !corridorKind.isEmpty,
                  !sideNodeKey.isEmpty,
                  !pairedKind.isEmpty else {
                continue
            }
            let relation = CorridorPairRelation(
                corridorKind: corridorKind,
                corridorID: Int(sqlite3_column_int(stmt, 1)),
                sideNodeKey: sideNodeKey,
                pairedKind: pairedKind,
                pairedCorridorID: Int(sqlite3_column_int(stmt, 4))
            )
            let mainKey = corridorPairKey(
                kind: relation.corridorKind,
                corridorID: relation.corridorID,
                sideNodeKey: relation.sideNodeKey
            )
            let pairedKey = corridorPairKey(
                kind: relation.pairedKind,
                corridorID: relation.pairedCorridorID,
                sideNodeKey: relation.sideNodeKey
            )
            byMainKey[mainKey, default: []].append(relation)
            byPairedKey[pairedKey, default: []].append(relation)
        }
        let context = CorridorPairContext(
            available: true,
            byMainKey: byMainKey,
            byPairedKey: byPairedKey
        )
        cachedCorridorPairContext = context
        return context
    }

    private func corridorProgressInfos(
        for candidate: WayCandidate,
        progressContext: CorridorProgressContext
    ) -> [CorridorProgressInfo] {
        guard progressContext.available,
              let wayID = normalizedWayID(candidate.wayID) else {
            return []
        }
        return progressContext.byWayID[wayID] ?? []
    }

    private func corridorEntryDepthThresholdM(kind: String) -> Double {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorEntryDepthM
        default:
            return Self.tunnelCorridorEntryDepthM
        }
    }

    private func corridorExitRemainingThresholdM(kind: String) -> Double {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorExitRemainingM
        default:
            return Self.tunnelCorridorExitRemainingM
        }
    }

    private func corridorEntryMinDepthM(kind: String) -> Double {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorEntryMinDepthM
        default:
            return Self.tunnelCorridorEntryMinDepthM
        }
    }

    private func corridorEntryFixCount(kind: String) -> Int {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorEntryFixCount
        default:
            return Self.tunnelCorridorEntryFixCount
        }
    }

    private func corridorEntryProgressThresholdM(kind: String) -> Double {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorEntryProgressM
        default:
            return Self.tunnelCorridorEntryProgressM
        }
    }

    private func corridorEntryProgressThresholdNodes(kind: String) -> Int {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorEntryProgressNodes
        default:
            return Self.tunnelCorridorEntryProgressNodes
        }
    }

    private func corridorExitRemainingThresholdNodes(kind: String) -> Int {
        switch kind {
        case "motorway":
            return Self.motorwayCorridorExitRemainingNodes
        default:
            return Self.tunnelCorridorExitRemainingNodes
        }
    }

    private func corridorUsesNodeProgress(
        spanNodes: Int,
        thresholdNodes: Int
    ) -> Bool {
        spanNodes >= thresholdNodes + 1
    }

    private func corridorApproachProgressM(
        for candidateCorridorState: CandidateCorridorState,
        matchContext: NormalizedMatchContext
    ) -> Double {
        let startDepthM = matchContext.approachCorridorStartDepthM ?? matchContext.approachCorridorState?.depthM
        guard let startDepthM else {
            return 0.0
        }
        return max(0.0, candidateCorridorState.snapshot.depthM - startDepthM)
    }

    private func corridorApproachProgressNodes(
        for candidateCorridorState: CandidateCorridorState,
        matchContext: NormalizedMatchContext
    ) -> Int {
        let startDepthNodes = matchContext.approachCorridorStartDepthNodes ?? matchContext.approachCorridorState?.depthNodes
        guard let startDepthNodes else {
            return 0
        }
        return max(0, candidateCorridorState.snapshot.depthNodes - startDepthNodes)
    }

    private func corridorChainCommitScore(
        for candidateCorridorState: CandidateCorridorState?,
        matchContext: NormalizedMatchContext
    ) -> Double {
        guard let candidateCorridorState else {
            return 0.0
        }
        if sameCorridorState(matchContext.activeCorridorState, candidateCorridorState.snapshot) {
            return 1.0
        }
        guard let approachState = matchContext.approachCorridorState,
              sameCorridorState(approachState, candidateCorridorState.snapshot),
              matchContext.approachCorridorFixCount >= corridorEntryFixCount(kind: candidateCorridorState.snapshot.kind),
              candidateCorridorState.snapshot.depthM + Self.corridorProgressNoiseToleranceM >= approachState.depthM,
              candidateCorridorState.snapshot.depthM >= corridorEntryMinDepthM(kind: candidateCorridorState.snapshot.kind) else {
            return 0.0
        }

        let progressThresholdM = max(corridorEntryProgressThresholdM(kind: candidateCorridorState.snapshot.kind), 1.0)
        let progressScore = min(
            1.0,
            max(0.0, corridorApproachProgressM(for: candidateCorridorState, matchContext: matchContext) / progressThresholdM)
        )
        let entryDepthWindowM = max(
            corridorEntryDepthThresholdM(kind: candidateCorridorState.snapshot.kind) -
                corridorEntryMinDepthM(kind: candidateCorridorState.snapshot.kind),
            1.0
        )
        let depthScore = min(
            1.0,
            max(
                0.0,
                (candidateCorridorState.snapshot.depthM -
                    corridorEntryMinDepthM(kind: candidateCorridorState.snapshot.kind)) / entryDepthWindowM
            )
        )
        let fixScore = min(
            1.0,
            Double(matchContext.approachCorridorFixCount) /
                Double(max(corridorEntryFixCount(kind: candidateCorridorState.snapshot.kind) + 1, 1))
        )

        let nodeThreshold = corridorEntryProgressThresholdNodes(kind: candidateCorridorState.snapshot.kind)
        let nodeScore: Double
        if corridorUsesNodeProgress(spanNodes: candidateCorridorState.snapshot.spanNodes, thresholdNodes: nodeThreshold) {
            let progressNodes = corridorApproachProgressNodes(for: candidateCorridorState, matchContext: matchContext)
            nodeScore = min(1.0, Double(progressNodes) / Double(max(nodeThreshold, 1)))
        } else {
            nodeScore = progressScore
        }

        return max(
            progressScore,
            min(1.0, (0.45 * progressScore) + (0.25 * depthScore) + (0.20 * nodeScore) + (0.10 * fixScore))
        )
    }

    private func hasCommittedApproachCorridorEvidence(
        for candidateCorridorState: CandidateCorridorState?,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        corridorChainCommitScore(
            for: candidateCorridorState,
            matchContext: matchContext
        ) >= Self.corridorStateTunnelChainCommitMinScore
    }

    private func hasPairedSurfaceApproachEvidence(
        for candidateCorridorState: CandidateCorridorState?,
        matchContext: NormalizedMatchContext,
        pairContext: CorridorPairContext
    ) -> Bool {
        guard pairContext.available,
              let candidateSnapshot = candidateCorridorState?.snapshot else {
            return !pairContext.available
        }
        for hypothesis in matchContext.recentHypotheses {
            guard let previousSnapshot = hypothesisCorridorSnapshot(hypothesis),
                  previousSnapshot.kind == "surface" || previousSnapshot.kind == "motorway_link" else {
                continue
            }
            if isPairedWithMainCorridor(
                pairedSnapshot: previousSnapshot,
                mainSnapshot: candidateSnapshot,
                pairContext: pairContext
            ) {
                return true
            }
        }
        return false
    }

    private func isTunnelCandidateSelectable(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double
    ) -> Bool {
        guard isTruthyOSMTag(candidate.tunnel) else {
            return true
        }
        if isLegacyTunnelCandidateSelectable(
            candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM
        ) {
            return true
        }
        guard let corridorCandidateState = candidateCorridorState(
            for: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext
        ) else {
            return false
        }
        if sameCorridorState(matchContext.activeCorridorState, corridorCandidateState.snapshot) {
            return true
        }
        guard hasPairedSurfaceApproachEvidence(
            for: corridorCandidateState,
            matchContext: matchContext,
            pairContext: pairContext
        ) else {
            return false
        }
        if isContinuingApproachCorridorCandidate(
            corridorCandidateState,
            matchContext: matchContext
        ) {
            return true
        }
        return hasCommittedApproachCorridorEvidence(
            for: corridorCandidateState,
            matchContext: matchContext
        )
    }

    private func isContinuingApproachCorridorCandidate(
        _ candidateCorridorState: CandidateCorridorState?,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        guard let candidateCorridorState,
              let approachState = matchContext.approachCorridorState,
              sameCorridorState(approachState, candidateCorridorState.snapshot),
              candidateCorridorState.snapshot.depthM + Self.corridorProgressNoiseToleranceM >= approachState.depthM else {
            return false
        }
        if let progressDeltaNodes = candidateCorridorState.progressDeltaNodes,
           progressDeltaNodes < -1,
           !candidateCorridorState.exitZone {
            return false
        }
        return true
    }

    private func corridorDepthM(
        for candidate: WayCandidate,
        progressInfo: CorridorProgressInfo
    ) -> Double? {
        guard let distanceToStartM = candidate.distanceToStartM,
              let distanceToEndM = candidate.distanceToEndM else {
            return nil
        }
        let viaStart = progressInfo.startDepthM + distanceToStartM
        let viaEnd = progressInfo.endDepthM + distanceToEndM
        return min(viaStart, viaEnd)
    }

    private func corridorDepthNodes(
        for candidate: WayCandidate,
        progressInfo: CorridorProgressInfo
    ) -> Int? {
        guard let distanceToStartM = candidate.distanceToStartM,
              let distanceToEndM = candidate.distanceToEndM else {
            return min(progressInfo.startDepthNodes, progressInfo.endDepthNodes)
        }
        if distanceToStartM <= distanceToEndM {
            return progressInfo.startDepthNodes
        }
        return progressInfo.endDepthNodes
    }

    private func corridorStateSnapshot(
        for candidate: WayCandidate,
        progressInfo: CorridorProgressInfo
    ) -> CorridorMatchState? {
        guard let depthM = corridorDepthM(for: candidate, progressInfo: progressInfo),
              let depthNodes = corridorDepthNodes(for: candidate, progressInfo: progressInfo) else {
            return nil
        }
        return CorridorMatchState(
            kind: progressInfo.kind,
            corridorID: progressInfo.corridorID,
            sideNodeKey: progressInfo.sideNodeKey,
            depthM: depthM,
            spanM: progressInfo.spanM,
            depthNodes: depthNodes,
            spanNodes: progressInfo.spanNodes
        )
    }

    private func sameCorridorState(
        _ lhs: CorridorMatchState?,
        _ rhs: CorridorMatchState?
    ) -> Bool {
        guard let lhs, let rhs else {
            return false
        }
        return lhs.kind == rhs.kind &&
            lhs.corridorID == rhs.corridorID &&
            lhs.sideNodeKey == rhs.sideNodeKey
    }

    private func isCorridorExitZone(_ snapshot: CorridorMatchState) -> Bool {
        let remainingM = max(0.0, snapshot.spanM - snapshot.depthM)
        guard remainingM <= corridorExitRemainingThresholdM(kind: snapshot.kind) else {
            return false
        }
        let thresholdNodes = corridorExitRemainingThresholdNodes(kind: snapshot.kind)
        guard corridorUsesNodeProgress(spanNodes: snapshot.spanNodes, thresholdNodes: thresholdNodes) else {
            return true
        }
        let remainingNodes = max(0, snapshot.spanNodes - snapshot.depthNodes)
        return remainingNodes <= thresholdNodes
    }

    private func corridorPairRelations(
        forMain snapshot: CorridorMatchState?,
        pairContext: CorridorPairContext
    ) -> [CorridorPairRelation] {
        guard pairContext.available, let snapshot else {
            return []
        }
        let key = corridorPairKey(
            kind: snapshot.kind,
            corridorID: snapshot.corridorID,
            sideNodeKey: snapshot.sideNodeKey
        )
        return pairContext.byMainKey[key] ?? []
    }

    private func corridorPairRelations(
        forPaired snapshot: CorridorMatchState?,
        pairContext: CorridorPairContext
    ) -> [CorridorPairRelation] {
        guard pairContext.available, let snapshot else {
            return []
        }
        let key = corridorPairKey(
            kind: snapshot.kind,
            corridorID: snapshot.corridorID,
            sideNodeKey: snapshot.sideNodeKey
        )
        return pairContext.byPairedKey[key] ?? []
    }

    private func hypothesisCorridorSnapshot(
        _ hypothesis: WayMatchHypothesis
    ) -> CorridorMatchState? {
        guard let corridorKind = hypothesis.corridorKind,
              let corridorID = hypothesis.corridorID,
              let sideNodeKey = hypothesis.corridorSideNodeKey else {
            return nil
        }
        return CorridorMatchState(
            kind: corridorKind,
            corridorID: corridorID,
            sideNodeKey: sideNodeKey,
            depthM: 0.0,
            spanM: 0.0,
            depthNodes: 0,
            spanNodes: 0
        )
    }

    private func isPairedWithMainCorridor(
        pairedSnapshot: CorridorMatchState?,
        mainSnapshot: CorridorMatchState?,
        pairContext: CorridorPairContext,
        requireOppositeSide: Bool = false
    ) -> Bool {
        guard let pairedSnapshot,
              let mainSnapshot else {
            return false
        }
        return corridorPairRelations(forPaired: pairedSnapshot, pairContext: pairContext).contains { relation in
            guard relation.corridorKind == mainSnapshot.kind,
                  relation.corridorID == mainSnapshot.corridorID else {
                return false
            }
            if requireOppositeSide {
                return relation.sideNodeKey != mainSnapshot.sideNodeKey
            }
            return relation.sideNodeKey == mainSnapshot.sideNodeKey
        }
    }

    private func isMainCorridorPairedToCandidate(
        mainSnapshot: CorridorMatchState?,
        candidateSnapshot: CorridorMatchState?,
        pairContext: CorridorPairContext,
        requireOppositeSide: Bool = false
    ) -> Bool {
        guard let candidateSnapshot,
              let mainSnapshot else {
            return false
        }
        return corridorPairRelations(forMain: mainSnapshot, pairContext: pairContext).contains { relation in
            guard relation.pairedKind == candidateSnapshot.kind,
                  relation.pairedCorridorID == candidateSnapshot.corridorID else {
                return false
            }
            if requireOppositeSide {
                return relation.sideNodeKey != mainSnapshot.sideNodeKey &&
                    relation.sideNodeKey == candidateSnapshot.sideNodeKey
            }
            return relation.sideNodeKey == candidateSnapshot.sideNodeKey
        }
    }

    private func candidateCorridorState(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext
    ) -> CandidateCorridorState? {
        let infos = corridorProgressInfos(for: candidate, progressContext: progressContext)
        guard !infos.isEmpty else {
            return nil
        }

        if let activeState = matchContext.activeCorridorState {
            let activeCandidates = infos
                .filter {
                    $0.kind == activeState.kind &&
                    $0.corridorID == activeState.corridorID &&
                    $0.sideNodeKey == activeState.sideNodeKey
                }
                .compactMap { info -> CandidateCorridorState? in
                    guard let snapshot = corridorStateSnapshot(for: candidate, progressInfo: info) else {
                        return nil
                    }
                    return CandidateCorridorState(
                        snapshot: snapshot,
                        entryZone: snapshot.depthM <= corridorEntryDepthThresholdM(kind: snapshot.kind),
                        exitZone: isCorridorExitZone(snapshot),
                        progressDeltaM: snapshot.depthM - activeState.depthM,
                        progressDeltaNodes: snapshot.depthNodes - activeState.depthNodes
                    )
                }
                .sorted { lhs, rhs in
                    if lhs.snapshot.depthM != rhs.snapshot.depthM {
                        return lhs.snapshot.depthM < rhs.snapshot.depthM
                    }
                    return lhs.snapshot.corridorID < rhs.snapshot.corridorID
                }
            if let activeCandidate = activeCandidates.first {
                return activeCandidate
            }
        }

        if let approachState = matchContext.approachCorridorState {
            let approachCandidates = infos
                .filter {
                    $0.kind == approachState.kind &&
                    $0.corridorID == approachState.corridorID &&
                    $0.sideNodeKey == approachState.sideNodeKey
                }
                .compactMap { info -> CandidateCorridorState? in
                    guard let snapshot = corridorStateSnapshot(for: candidate, progressInfo: info) else {
                        return nil
                    }
                    return CandidateCorridorState(
                        snapshot: snapshot,
                        entryZone: snapshot.depthM <= corridorEntryDepthThresholdM(kind: snapshot.kind),
                        exitZone: isCorridorExitZone(snapshot),
                        progressDeltaM: snapshot.depthM - approachState.depthM,
                        progressDeltaNodes: snapshot.depthNodes - approachState.depthNodes
                    )
                }
                .sorted { lhs, rhs in
                    if lhs.snapshot.depthM != rhs.snapshot.depthM {
                        return lhs.snapshot.depthM < rhs.snapshot.depthM
                    }
                    return lhs.snapshot.corridorID < rhs.snapshot.corridorID
                }
            if let approachCandidate = approachCandidates.first {
                return approachCandidate
            }
        }

        if let candidateWayID = normalizedWayID(candidate.wayID),
           candidateWayID == matchContext.preferredWayID || matchContext.recentWayIDs.contains(candidateWayID) {
            let preferredCandidates = infos
                .compactMap { info -> CandidateCorridorState? in
                    guard let snapshot = corridorStateSnapshot(for: candidate, progressInfo: info) else {
                        return nil
                    }
                    return CandidateCorridorState(
                        snapshot: snapshot,
                        entryZone: snapshot.depthM <= corridorEntryDepthThresholdM(kind: snapshot.kind),
                        exitZone: isCorridorExitZone(snapshot),
                        progressDeltaM: nil,
                        progressDeltaNodes: nil
                    )
                }
                .sorted { lhs, rhs in
                    if lhs.snapshot.depthM != rhs.snapshot.depthM {
                        return lhs.snapshot.depthM < rhs.snapshot.depthM
                    }
                    if lhs.snapshot.depthNodes != rhs.snapshot.depthNodes {
                        return lhs.snapshot.depthNodes < rhs.snapshot.depthNodes
                    }
                    return lhs.snapshot.corridorID < rhs.snapshot.corridorID
                }
            if let preferredCandidate = preferredCandidates.first {
                return preferredCandidate
            }
        }

        guard let anchor = corridorAnchor(from: matchContext),
              let candidateWayID = normalizedWayID(candidate.wayID) else {
            return nil
        }
        let sharedNodeKeys = wayLinks.sharedNodeKeys(from: anchor.wayID, to: candidateWayID)
        guard !sharedNodeKeys.isEmpty else {
            return nil
        }
        return infos
            .filter { sharedNodeKeys.contains($0.sideNodeKey) }
            .compactMap { info -> CandidateCorridorState? in
                guard let snapshot = corridorStateSnapshot(for: candidate, progressInfo: info) else {
                    return nil
                }
                return CandidateCorridorState(
                    snapshot: snapshot,
                    entryZone: snapshot.depthM <= corridorEntryDepthThresholdM(kind: snapshot.kind),
                    exitZone: isCorridorExitZone(snapshot),
                    progressDeltaM: nil,
                    progressDeltaNodes: nil
                )
            }
            .sorted { lhs, rhs in
                if lhs.snapshot.depthM != rhs.snapshot.depthM {
                    return lhs.snapshot.depthM < rhs.snapshot.depthM
                }
                return lhs.snapshot.corridorID < rhs.snapshot.corridorID
            }
            .first
    }

    private func shouldTriggerActiveCorridorMode(
        _ candidateCorridorState: CandidateCorridorState,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        if sameCorridorState(matchContext.activeCorridorState, candidateCorridorState.snapshot) {
            return true
        }
        guard let approachState = matchContext.approachCorridorState,
              sameCorridorState(approachState, candidateCorridorState.snapshot),
              matchContext.approachCorridorFixCount >= corridorEntryFixCount(kind: candidateCorridorState.snapshot.kind),
              candidateCorridorState.snapshot.depthM >= corridorEntryMinDepthM(kind: candidateCorridorState.snapshot.kind) else {
            return false
        }
        guard corridorChainCommitScore(
            for: candidateCorridorState,
            matchContext: matchContext
        ) >= Self.corridorStateTunnelChainCommitMinScore else {
            return false
        }
        return candidateCorridorState.snapshot.depthM + Self.corridorProgressNoiseToleranceM >= approachState.depthM
    }

    private func isActiveCorridorExitCandidate(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        guard let activeState = matchContext.activeCorridorState,
              let preferredWayID = matchContext.preferredWayID,
              let candidateWayID = normalizedWayID(candidate.wayID) else {
            return false
        }
        let remainingM = max(0.0, activeState.spanM - activeState.depthM)
        guard remainingM <= corridorExitRemainingThresholdM(kind: activeState.kind) + Self.corridorProgressNoiseToleranceM else {
            return false
        }
        let remainingThresholdNodes = corridorExitRemainingThresholdNodes(kind: activeState.kind)
        if corridorUsesNodeProgress(spanNodes: activeState.spanNodes, thresholdNodes: remainingThresholdNodes) {
            let remainingNodes = max(0, activeState.spanNodes - activeState.depthNodes)
            guard remainingNodes <= remainingThresholdNodes else {
                return false
            }
        }
        let sharedNodeKeys = wayLinks.sharedNodeKeys(from: preferredWayID, to: candidateWayID)
        guard sharedNodeKeys.contains(where: { $0 != activeState.sideNodeKey }) else {
            return false
        }
        switch activeState.kind {
        case "motorway":
            return (candidate.highway ?? "").lowercased() == "motorway_link"
        default:
            return !isTruthyOSMTag(candidate.tunnel)
        }
    }

    private func isActiveCorridorEntryConnectorCandidate(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        guard let activeState = matchContext.activeCorridorState,
              activeState.kind == "motorway",
              activeState.depthM <= corridorEntryDepthThresholdM(kind: activeState.kind) + Self.corridorProgressNoiseToleranceM,
              let preferredWayID = matchContext.preferredWayID,
              let candidateWayID = normalizedWayID(candidate.wayID),
              (candidate.highway ?? "").lowercased() == "motorway_link" else {
            return false
        }
        let entryThresholdNodes = corridorEntryProgressThresholdNodes(kind: activeState.kind)
        if corridorUsesNodeProgress(spanNodes: activeState.spanNodes, thresholdNodes: entryThresholdNodes),
           activeState.depthNodes > entryThresholdNodes {
            return false
        }
        let sharedNodeKeys = wayLinks.sharedNodeKeys(from: preferredWayID, to: candidateWayID)
        return sharedNodeKeys.contains(activeState.sideNodeKey)
    }

    private func isLinkedCandidate(
        _ candidateWayID: String?,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        requireSharedRef: Bool = false
    ) -> Bool {
        guard wayLinks.available, let candidateWayID else {
            return false
        }
        var anchorWayIDs = matchContext.recentWayIDs
        anchorWayIDs.formUnion(matchContext.recentHypotheses.map(\.wayID))
        if let preferredWayID = matchContext.preferredWayID {
            anchorWayIDs.insert(preferredWayID)
        }
        for anchorWayID in anchorWayIDs where anchorWayID != candidateWayID {
            if requireSharedRef {
                if wayLinks.isSharedRefLinked(from: anchorWayID, to: candidateWayID) {
                    return true
                }
            } else if wayLinks.isLinked(from: anchorWayID, to: candidateWayID) {
                return true
            }
        }
        return false
    }

    private func corridorAnchor(from matchContext: NormalizedMatchContext) -> CorridorAnchor? {
        guard matchContext.preferredWayID != nil ||
                matchContext.preferredHighway != nil ||
                matchContext.isInTunnelMode else {
            return nil
        }
        return CorridorAnchor(
            wayID: matchContext.preferredWayID,
            highway: matchContext.preferredHighway,
            endpointProximityM: matchContext.preferredEndpointProximityM,
            isInTunnelMode: matchContext.isInTunnelMode
        )
    }

    private func corridorState(for candidate: WayCandidate) -> CorridorState {
        if isTruthyOSMTag(candidate.tunnel) {
            return .tunnel
        }
        switch (candidate.highway ?? "").lowercased() {
        case "motorway":
            return .motorway
        case "motorway_link":
            return .motorwayLink
        default:
            return .surface
        }
    }

    private func isEndpointNear(_ proximityM: Double?, thresholdM: Double) -> Bool {
        guard let proximityM, proximityM.isFinite else {
            return false
        }
        return proximityM <= thresholdM
    }

    private func areLinkedWays(
        _ sourceWayID: String?,
        _ targetWayID: String?,
        wayLinks: WayLinksContext
    ) -> Bool {
        wayLinks.isLinked(from: sourceWayID, to: targetWayID) ||
            wayLinks.isLinked(from: targetWayID, to: sourceWayID)
    }

    private func areSharedRefLinkedWays(
        _ sourceWayID: String?,
        _ targetWayID: String?,
        wayLinks: WayLinksContext
    ) -> Bool {
        wayLinks.isSharedRefLinked(from: sourceWayID, to: targetWayID) ||
            wayLinks.isSharedRefLinked(from: targetWayID, to: sourceWayID)
    }

    private func hasSharedRefWithPreferred(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        guard !candidateRefTokens.isEmpty else {
            return false
        }
        return !matchContext.preferredStreetRefs.isDisjoint(with: candidateRefTokens)
    }

    private func isPortalEligibleTunnelCandidate(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        accuracyBufferM: Double
    ) -> Bool {
        guard isTruthyOSMTag(candidate.tunnel),
              wayLinks.available,
              let anchor = corridorAnchor(from: matchContext),
              anchor.state == .surface else {
            return false
        }
        guard isTunnelPortalTransition(
            from: anchor,
            to: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM,
            entry: true
        ) else {
            return false
        }
        let corridorState = candidateCorridorState(
            for: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext
        )
        if let corridorState {
            guard corridorState.snapshot.kind == "tunnel",
                  corridorState.entryZone else {
                return false
            }
        }
        let motionScore = portalMotionProgressScore(for: candidate, matchContext: matchContext)
        let endpointDistance = corridorState?.snapshot.depthM ?? candidate.endpointProximityM
        let portalDistanceThreshold = Self.tunnelPortalEntryEndpointThresholdM + accuracyBufferM
        guard endpointDistance.isFinite, endpointDistance <= portalDistanceThreshold else {
            return false
        }
        let directSnapThreshold = max(4.0, min(accuracyBufferM * 0.35, 10.0))
        if endpointDistance <= directSnapThreshold {
            if matchContext.recentFixes.isEmpty {
                return true
            }
            return motionScore >= Self.tunnelPortalDirectSnapMotionMinScore
        }
        if matchContext.recentFixes.isEmpty {
            return true
        }
        return motionScore >= 0.25
    }

    private func portalMotionMetrics(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> PortalMotionMetrics? {
        guard !matchContext.recentFixes.isEmpty,
              !candidate.points.isEmpty,
              let currentDistanceToStartM = candidate.distanceToStartM,
              let currentDistanceToEndM = candidate.distanceToEndM else {
            return nil
        }

        let enteringFromStart = currentDistanceToStartM <= currentDistanceToEndM
        let currentPortalDistance = enteringFromStart ? currentDistanceToStartM : currentDistanceToEndM

        var bestApproachDeltaM = 0.0
        var bestInteriorProgressDeltaM = 0.0
        for fix in matchContext.recentFixes.prefix(2) {
            guard let priorMetrics = polylineMetrics(lat: fix.lat, lon: fix.lon, points: candidate.points) else {
                continue
            }
            let priorPortalDistance = enteringFromStart ? priorMetrics.distanceToStartM : priorMetrics.distanceToEndM
            bestApproachDeltaM = max(bestApproachDeltaM, priorPortalDistance - currentPortalDistance)
            bestInteriorProgressDeltaM = max(bestInteriorProgressDeltaM, currentPortalDistance - priorPortalDistance)
        }

        let proximityScore = max(0.0, min((18.0 - currentPortalDistance) / 18.0, 1.0))
        let alignmentScore: Double
        if let priorFix = matchContext.recentFixes.first,
           let motionHeading = axisHeadingDeg(
                from: priorFix.lat,
                lon1: priorFix.lon,
                to: candidate.queryPoint.0,
                lon2: candidate.queryPoint.1
           ),
           let portalHeading = portalInteriorHeadingDeg(
                for: candidate,
                enteringFromStart: enteringFromStart
           ) {
            alignmentScore = max(
                0.0,
                1.0 - (directedHeadingMismatchDeg(headingDeg: motionHeading, approxHeadingDeg: portalHeading) / 55.0)
            )
        } else {
            alignmentScore = 0.0
        }

        return PortalMotionMetrics(
            enteringFromStart: enteringFromStart,
            currentPortalDistanceM: currentPortalDistance,
            bestApproachDeltaM: bestApproachDeltaM,
            bestInteriorProgressDeltaM: bestInteriorProgressDeltaM,
            alignmentScore: alignmentScore,
            proximityScore: proximityScore
        )
    }

    private func portalMotionProgressScore(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> Double {
        guard let metrics = portalMotionMetrics(for: candidate, matchContext: matchContext) else {
            return 0.0
        }
        let rawApproachComponent = max(0.0, min(metrics.bestApproachDeltaM / 12.0, 1.0))
        let approachComponent = metrics.alignmentScore >= 0.35 ? rawApproachComponent : 0.0
        return max(
            approachComponent,
            (approachComponent * 0.6) + (metrics.alignmentScore * 0.25) + (metrics.proximityScore * 0.15)
        )
    }

    private func portalCommitProgressScore(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> Double {
        guard let metrics = portalMotionMetrics(for: candidate, matchContext: matchContext),
              matchContext.tunnelApproachFixCount >= max(Self.tunnelApproachMinFixCount + 1, 3),
              metrics.alignmentScore >= 0.35,
              metrics.currentPortalDistanceM >= 4.0 else {
            return 0.0
        }
        let interiorComponent = max(0.0, min(metrics.bestInteriorProgressDeltaM / 12.0, 1.0))
        guard interiorComponent > 0.0 else {
            return 0.0
        }
        return (interiorComponent * 0.6) + (metrics.alignmentScore * 0.25) + (metrics.proximityScore * 0.15)
    }

    private func portalInteriorHeadingDeg(
        for candidate: WayCandidate,
        enteringFromStart: Bool
    ) -> Double? {
        if enteringFromStart {
            return candidate.startHeadingDeg
        }
        guard let endHeadingDeg = candidate.endHeadingDeg else {
            return nil
        }
        return normalizedHeadingDegrees(endHeadingDeg + 180.0)
    }

    private func isEndpointLinkedTransition(
        from anchor: CorridorAnchor,
        to candidate: WayCandidate,
        wayLinks: WayLinksContext,
        endpointThresholdM: Double,
        accuracyBufferM: Double
    ) -> Bool {
        let candidateWayID = normalizedWayID(candidate.wayID)
        guard areLinkedWays(anchor.wayID, candidateWayID, wayLinks: wayLinks) else {
            return false
        }
        let threshold = endpointThresholdM + accuracyBufferM
        let sourceNearEndpoint = anchor.endpointProximityM.map { isEndpointNear($0, thresholdM: threshold) } ?? true
        let candidateNearEndpoint = candidate.endpointProximityM <= (threshold * 2.0)
        return sourceNearEndpoint && candidateNearEndpoint
    }

    private func isTunnelPortalTransition(
        from anchor: CorridorAnchor,
        to candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        entry: Bool
    ) -> Bool {
        let endpointThresholdM = entry
            ? Self.tunnelPortalEntryEndpointThresholdM
            : Self.tunnelPortalExitEndpointThresholdM
        guard isEndpointLinkedTransition(
            from: anchor,
            to: candidate,
            wayLinks: wayLinks,
            endpointThresholdM: endpointThresholdM,
            accuracyBufferM: accuracyBufferM
        ) else {
            return false
        }
        if entry {
            return areSharedRefLinkedWays(anchor.wayID, normalizedWayID(candidate.wayID), wayLinks: wayLinks) ||
                hasSharedRefWithPreferred(candidate, matchContext: matchContext)
        }
        return true
    }

    private func isMotorwayTransitionCandidate(
        from anchor: CorridorAnchor,
        to candidate: WayCandidate,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double
    ) -> Bool {
        isEndpointLinkedTransition(
            from: anchor,
            to: candidate,
            wayLinks: wayLinks,
            endpointThresholdM: Self.motorwayTransitionEndpointThresholdM,
            accuracyBufferM: accuracyBufferM
        )
    }

    private func matchesTunnelApproachCandidate(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        let candidateWayID = normalizedWayID(candidate.wayID)
        if let candidateWayID, matchContext.recentTunnelApproachWayIDs.contains(candidateWayID) {
            return true
        }
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        guard !candidateRefTokens.isEmpty else {
            return false
        }
        return !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelApproachRefs)
    }

    private func hasCommittedTunnelApproachEvidence(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?
    ) -> Bool {
        guard isTruthyOSMTag(candidate.tunnel),
              matchContext.tunnelApproachFixCount >= Self.tunnelApproachMinFixCount,
              matchesTunnelApproachCandidate(candidate, matchContext: matchContext) else {
            return false
        }
        if matchContext.hadRecentGPSSignalLoss {
            return true
        }
        if let baselineAccuracyM = matchContext.tunnelApproachBaselineAccuracyM,
           let horizontalAccuracyM,
           horizontalAccuracyM.isFinite,
           horizontalAccuracyM >= baselineAccuracyM + Self.tunnelApproachAccuracyDeltaM {
            return true
        }
        if let baselineSignalBars = matchContext.tunnelApproachBaselineSignalBars,
           let gpsSignalBars,
           gpsSignalBars <= baselineSignalBars - Self.tunnelApproachSignalDropBars {
            return true
        }
        return portalCommitProgressScore(for: candidate, matchContext: matchContext) >= Self.corridorStateTunnelDirectCommitMinScore
    }

    private func signalQualityEvidence(
        matchContext: NormalizedMatchContext,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?
    ) -> SignalQualityEvidence {
        let horizontalAccuracyDeltaM: Double
        if let baselineAccuracyM = matchContext.tunnelApproachBaselineAccuracyM,
           let horizontalAccuracyM,
           horizontalAccuracyM.isFinite {
            horizontalAccuracyDeltaM = max(0.0, horizontalAccuracyM - baselineAccuracyM)
        } else {
            horizontalAccuracyDeltaM = 0.0
        }
        let gpsSignalBarsDrop: Int
        if let baselineSignalBars = matchContext.tunnelApproachBaselineSignalBars,
           let gpsSignalBars {
            gpsSignalBarsDrop = max(0, baselineSignalBars - gpsSignalBars)
        } else {
            gpsSignalBarsDrop = 0
        }
        return SignalQualityEvidence(
            tunnelApproachFixCount: matchContext.tunnelApproachFixCount,
            horizontalAccuracyDeltaM: horizontalAccuracyDeltaM,
            gpsSignalBarsDrop: gpsSignalBarsDrop,
            hadRecentGPSSignalLoss: matchContext.hadRecentGPSSignalLoss
        )
    }

    private func shouldFallbackWhenCorridorGateEmptiesCandidates(
        matchContext: NormalizedMatchContext
    ) -> Bool {
        matchContext.hadRecentGPSSignalLoss
    }

    private func isCorridorCandidateSelectable(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?
    ) -> Bool {
        let tunnelSelectable = isTunnelCandidateSelectable(
            candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext,
            pairContext: pairContext,
            accuracyBufferM: accuracyBufferM
        )
        guard tunnelSelectable else {
            return false
        }
        if let activeCorridorState = matchContext.activeCorridorState {
            if let corridorState = candidateCorridorState(
                for: candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                progressContext: progressContext
            ),
            sameCorridorState(activeCorridorState, corridorState.snapshot) {
                if let progressDeltaM = corridorState.progressDeltaM {
                    guard progressDeltaM >= -Self.corridorProgressNoiseToleranceM ||
                            corridorState.exitZone else {
                        return false
                    }
                }
                if let progressDeltaNodes = corridorState.progressDeltaNodes,
                   corridorUsesNodeProgress(
                        spanNodes: activeCorridorState.spanNodes,
                        thresholdNodes: corridorEntryProgressThresholdNodes(kind: activeCorridorState.kind)
                   ),
                   progressDeltaNodes < -1,
                   !corridorState.exitZone {
                    return false
                }
                return true
            }
            if isActiveCorridorEntryConnectorCandidate(
                candidate,
                matchContext: matchContext,
                wayLinks: wayLinks
            ) {
                return true
            }
            return isActiveCorridorExitCandidate(
                candidate,
                matchContext: matchContext,
                wayLinks: wayLinks
            )
        }
        guard wayLinks.available,
              let anchor = corridorAnchor(from: matchContext) else {
            return tunnelSelectable
        }

        let candidateWayID = normalizedWayID(candidate.wayID)
        if candidateWayID == anchor.wayID {
            return true
        }

        let candidateState = corridorState(for: candidate)
        let corridorCandidateState = candidateCorridorState(
            for: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext
        )
        switch (anchor.state, candidateState) {
        case (.surface, .surface):
            return true
        case (.surface, .tunnel):
            if isContinuingApproachCorridorCandidate(
                corridorCandidateState,
                matchContext: matchContext
            ) {
                return true
            }
            if hasCommittedApproachCorridorEvidence(
                for: corridorCandidateState,
                matchContext: matchContext
            ) {
                return true
            }
            if isPortalEligibleTunnelCandidate(
                candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                progressContext: progressContext,
                accuracyBufferM: accuracyBufferM
            ) {
                return true
            }
            return hasCommittedTunnelApproachEvidence(
                for: candidate,
                matchContext: matchContext,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
            )
        case (.surface, .motorway):
            if let corridorState = corridorCandidateState {
                return shouldTriggerActiveCorridorMode(corridorState, matchContext: matchContext)
            }
            return false
        case (.surface, .motorwayLink):
            return isMotorwayTransitionCandidate(
                from: anchor,
                to: candidate,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
            )
        case (.tunnel, .surface):
            return isTunnelPortalTransition(
                from: anchor,
                to: candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM,
                entry: false
            )
        case (.tunnel, .tunnel):
            if let candidateWayID, matchContext.recentTunnelCandidateWayIDs.contains(candidateWayID) {
                return true
            }
            let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
            if !candidateRefTokens.isEmpty,
               !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelCandidateRefs) {
                return true
            }
            return isEndpointLinkedTransition(
                from: anchor,
                to: candidate,
                wayLinks: wayLinks,
                endpointThresholdM: Self.tunnelPortalEntryEndpointThresholdM,
                accuracyBufferM: accuracyBufferM
            )
        case (.tunnel, .motorway), (.tunnel, .motorwayLink):
            return false
        case (.motorway, .surface), (.motorway, .tunnel):
            return false
        case (.motorway, .motorway), (.motorway, .motorwayLink):
            return isMotorwayTransitionCandidate(
                from: anchor,
                to: candidate,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
            )
        case (.motorwayLink, .tunnel):
            return false
        case (.motorwayLink, .motorway):
            if let corridorState = corridorCandidateState,
            shouldTriggerActiveCorridorMode(corridorState, matchContext: matchContext) {
                return true
            }
            return isMotorwayTransitionCandidate(
                from: anchor,
                to: candidate,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
            )
        case (.motorwayLink, .surface), (.motorwayLink, .motorwayLink):
            return isMotorwayTransitionCandidate(
                from: anchor,
                to: candidate,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
            )
        }
    }

    private func isSurfacePortalContinuationCandidate(
        _ candidate: WayCandidate,
        anchor: CorridorAnchor,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double
    ) -> Bool {
        guard corridorState(for: candidate) == .surface else {
            return false
        }
        guard hasSharedRefWithPreferred(candidate, matchContext: matchContext) else {
            return false
        }
        return isEndpointLinkedTransition(
            from: anchor,
            to: candidate,
            wayLinks: wayLinks,
            endpointThresholdM: Self.tunnelPortalEntryEndpointThresholdM,
            accuracyBufferM: accuracyBufferM
        )
    }

    private func suppressAmbiguousSurfaceToTunnelEntries(
        in candidates: [WayCandidate],
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?
    ) -> [WayCandidate] {
        guard wayLinks.available,
              !matchContext.hadRecentGPSSignalLoss,
              let anchor = corridorAnchor(from: matchContext),
              anchor.state == .surface else {
            return candidates
        }
        guard candidates.contains(where: {
            isSurfacePortalContinuationCandidate(
                $0,
                anchor: anchor,
                matchContext: matchContext,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM
            )
        }) else {
            return candidates
        }
        return candidates.filter { candidate in
            guard corridorState(for: candidate) == .tunnel,
                  hasSharedRefWithPreferred(candidate, matchContext: matchContext) else {
                return true
            }
            if matchesTunnelApproachCandidate(candidate, matchContext: matchContext) {
                return true
            }
            if let corridorState = candidateCorridorState(
                for: candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                progressContext: progressContext
            ) {
                if isContinuingApproachCorridorCandidate(
                    corridorState,
                    matchContext: matchContext
                ) {
                    return true
                }
                if hasCommittedApproachCorridorEvidence(
                    for: corridorState,
                    matchContext: matchContext
                ) {
                    return true
                }
                if shouldTriggerActiveCorridorMode(corridorState, matchContext: matchContext) {
                    return true
                }
            }
            if hasCommittedTunnelApproachEvidence(
                for: candidate,
                matchContext: matchContext,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
            ) {
                return true
            }
            return !isTunnelPortalTransition(
                from: anchor,
                to: candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM,
                entry: true
            )
        }
    }

    private func shouldApplyConnectedTransitionGate(
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        guard wayLinks.available else {
            return false
        }
        guard !matchContext.hadRecentGPSSignalLoss else {
            return false
        }
        guard matchContext.matchedFixCount >= Self.connectedTransitionWarmupFixCount else {
            return false
        }
        return matchContext.preferredWayID != nil || !matchContext.recentWayIDs.isEmpty
    }

    private func isConnectedTransitionCandidate(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        let candidateWayID = normalizedWayID(candidate.wayID)
        if candidateWayID == matchContext.preferredWayID {
            return true
        }
        if let candidateWayID, matchContext.recentWayIDs.contains(candidateWayID) {
            return true
        }
        return isLinkedCandidate(candidateWayID, matchContext: matchContext, wayLinks: wayLinks)
    }

    private func highwayFamily(_ raw: String?) -> String? {
        guard let raw else {
            return nil
        }
        let normalized = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else {
            return nil
        }
        if normalized.hasSuffix("_link") {
            return String(normalized.dropLast(5))
        }
        return normalized
    }

    private func continuityClass(
        for candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> ContinuityClass {
        if let candidateWayID = normalizedWayID(candidate.wayID),
           let preferredWayID = matchContext.preferredWayID,
           candidateWayID == preferredWayID {
            return .preferredWay
        }

        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        if !candidateRefTokens.isEmpty,
           (!matchContext.preferredStreetRefs.isDisjoint(with: candidateRefTokens) ||
            !matchContext.recentStreetRefs.isDisjoint(with: candidateRefTokens)) {
            if wayLinks.available,
               !isLinkedCandidate(normalizedWayID(candidate.wayID), matchContext: matchContext, wayLinks: wayLinks) {
                return .none
            }
            return .sameRef
        }

        if isLinkedCandidate(normalizedWayID(candidate.wayID), matchContext: matchContext, wayLinks: wayLinks) {
            return .linkedWay
        }

        if let candidateWayID = normalizedWayID(candidate.wayID),
           matchContext.recentWayIDs.contains(candidateWayID) {
            return .recentWay
        }

        return .none
    }

    private func shouldKeepContinuityCandidate(
        _ continuityCandidate: WayCandidate,
        over bestCandidate: WayCandidate,
        radiusM: Double,
        accuracyBufferM: Double,
        scoreSlackM: Double,
        distanceMultiplier: Double,
        distanceFloorM: Double
    ) -> Bool {
        let maxDistance = max(radiusM * distanceMultiplier, distanceFloorM) + accuracyBufferM
        return continuityCandidate.distanceM <= maxDistance &&
            continuityCandidate.score <= bestCandidate.score + scoreSlackM
    }

    private func shouldForceGeometricCandidateAtWalkingSpeed(
        preferredCandidate: WayCandidate,
        geometricCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        _ = observedHeadingDeg
        guard let speedKmh,
              speedKmh.isFinite,
              speedKmh <= Self.walkingTurnSwitchMaxSpeedKmh,
              matchContext.matchedFixCount >= 3 else {
            return false
        }
        guard normalizedWayID(preferredCandidate.wayID) != normalizedWayID(geometricCandidate.wayID) else {
            return false
        }
        guard geometricCandidate.service != "driveway" else {
            return false
        }
        let requiredEndpointProximity = max(
            Self.walkingTurnSwitchEndpointM,
            min(accuracyBufferM, 6.0)
        )
        guard preferredCandidate.endpointProximityM <= requiredEndpointProximity else {
            return false
        }
        let requiredPreferredDistance = max(
            Self.walkingTurnSwitchPreferredDistanceM,
            accuracyBufferM + 4.0
        )
        guard preferredCandidate.distanceM >= requiredPreferredDistance else {
            return false
        }
        let allowedBestDistance = max(
            Self.walkingTurnSwitchBestDistanceM,
            min(accuracyBufferM + 1.0, 6.0)
        )
        guard geometricCandidate.distanceM <= allowedBestDistance else {
            return false
        }
        let requiredGap = max(
            Self.walkingTurnSwitchMinGapM,
            accuracyBufferM + 1.5
        )
        guard preferredCandidate.distanceM >= geometricCandidate.distanceM + requiredGap else {
            return false
        }
        return preferredCandidate.distanceM >= geometricCandidate.distanceM * 2.5
    }

    private func scaledAccuracyBufferM(_ horizontalAccuracyM: Double?) -> Double {
        guard let horizontalAccuracyM, horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0 else {
            return 0.0
        }
        return min(max(horizontalAccuracyM * 1.35, 0.0), 60.0)
    }

    private func isLegacyPortalTransitionCandidate(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        requireSharedRef: Bool
    ) -> Bool {
        let endpointThreshold = (requireSharedRef ? Self.tunnelPortalEntryEndpointThresholdM : Self.tunnelPortalExitEndpointThresholdM) + accuracyBufferM
        guard candidate.endpointProximityM <= endpointThreshold else {
            return false
        }
        let candidateWayID = normalizedWayID(candidate.wayID)
        if requireSharedRef {
            if wayLinks.available {
                return isLinkedCandidate(
                    candidateWayID,
                    matchContext: matchContext,
                    wayLinks: wayLinks,
                    requireSharedRef: true
                )
            }
            return false
        }
        if wayLinks.available,
           isLinkedCandidate(candidateWayID, matchContext: matchContext, wayLinks: wayLinks) {
            return true
        }
        if let candidateWayID, matchContext.recentWayIDs.contains(candidateWayID) {
            return true
        }
        return false
    }

    private func shouldPromoteSameRefTransition(
        from preferredCandidate: WayCandidate,
        to transitionCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        wayLinks: WayLinksContext,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        guard normalizedWayID(preferredCandidate.wayID) != normalizedWayID(transitionCandidate.wayID) else {
            return false
        }
        if shouldSuppressImmediateSameRefBounce(
            candidate: transitionCandidate,
            over: preferredCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM
        ) {
            return false
        }
        let preferredRefTokens = Set(Self.normalizedRefTokens(preferredCandidate.streetRef))
        let transitionRefTokens = Set(Self.normalizedRefTokens(transitionCandidate.streetRef))
        guard !preferredRefTokens.isEmpty,
              !preferredRefTokens.isDisjoint(with: transitionRefTokens) else {
            return false
        }

        let endpointThreshold = Self.segmentTransitionEndpointThresholdM + accuracyBufferM
        let preferredAtEndpoint = preferredCandidate.endpointProximityM <= endpointThreshold
        let transitionNearEndpoint = transitionCandidate.endpointProximityM <= (endpointThreshold * 2.0)
        let transitionNotFarther = transitionCandidate.distanceM <= preferredCandidate.distanceM + Self.segmentTransitionDistanceSlackM + accuracyBufferM
        if wayLinks.available,
           !isLinkedCandidate(
                normalizedWayID(transitionCandidate.wayID),
                matchContext: matchContext,
                wayLinks: wayLinks
           ) {
            return false
        }
        if shouldRejectTurnTransition(
            from: preferredCandidate,
            to: transitionCandidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            fromEndpointProximityM: preferredCandidate.endpointProximityM
        ) {
            return false
        }
        return preferredAtEndpoint && transitionNearEndpoint && transitionNotFarther
    }

    private func shouldPromoteLinkedTransition(
        from preferredCandidate: WayCandidate,
        to transitionCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        wayLinks: WayLinksContext
    ) -> Bool {
        guard wayLinks.available,
              let preferredWayID = normalizedWayID(preferredCandidate.wayID),
              let transitionWayID = normalizedWayID(transitionCandidate.wayID),
              preferredWayID != transitionWayID,
              wayLinks.isLinked(from: preferredWayID, to: transitionWayID) ||
                wayLinks.isLinked(from: transitionWayID, to: preferredWayID) else {
            return false
        }
        guard highwayFamily(preferredCandidate.highway) == highwayFamily(transitionCandidate.highway) else {
            return false
        }
        let endpointThreshold = Self.segmentTransitionEndpointThresholdM + accuracyBufferM
        let preferredAtEndpoint = preferredCandidate.endpointProximityM <= endpointThreshold
        let transitionNearEndpoint = transitionCandidate.endpointProximityM <= (endpointThreshold * 2.0)
        let transitionNotFarther = transitionCandidate.distanceM <= preferredCandidate.distanceM + Self.segmentTransitionDistanceSlackM + accuracyBufferM
        let transitionScoreCompetitive = transitionCandidate.score <= preferredCandidate.score + Self.linkedWayScoreSlackM + accuracyBufferM
        if shouldRejectTurnTransition(
            from: preferredCandidate,
            to: transitionCandidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            fromEndpointProximityM: preferredCandidate.endpointProximityM
        ) {
            return false
        }
        return preferredAtEndpoint && transitionNearEndpoint && transitionNotFarther && transitionScoreCompetitive
    }

    private func shouldPreferSameRefAlternative(
        overPreferred preferredCandidate: WayCandidate,
        alternativeCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        wayLinks: WayLinksContext,
        matchContext: NormalizedMatchContext
    ) -> Bool {
        guard normalizedWayID(preferredCandidate.wayID) != normalizedWayID(alternativeCandidate.wayID) else {
            return false
        }
        if shouldSuppressImmediateSameRefBounce(
            candidate: alternativeCandidate,
            over: preferredCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM
        ) {
            return false
        }
        let preferredRefTokens = Set(Self.normalizedRefTokens(preferredCandidate.streetRef))
        let alternativeRefTokens = Set(Self.normalizedRefTokens(alternativeCandidate.streetRef))
        guard !preferredRefTokens.isEmpty,
              !preferredRefTokens.isDisjoint(with: alternativeRefTokens) else {
            return false
        }
        if wayLinks.available,
           !isLinkedCandidate(
                normalizedWayID(alternativeCandidate.wayID),
                matchContext: matchContext,
                wayLinks: wayLinks
           ) {
            return false
        }
        if alternativeCandidate.distanceM + accuracyBufferM + 10.0 < preferredCandidate.distanceM {
            return true
        }
        return shouldPromoteSameRefTransition(
            from: preferredCandidate,
            to: alternativeCandidate,
            observedHeadingDeg: observedHeadingDeg,
            speedKmh: speedKmh,
            accuracyBufferM: accuracyBufferM,
            wayLinks: wayLinks,
            matchContext: matchContext
        )
    }

    private func shouldPromoteTunnelEntry(
        tunnelCandidate: WayCandidate,
        over surfaceCandidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        accuracyBufferM: Double
    ) -> Bool {
        let portalEligible = isPortalEligibleTunnelCandidate(
            tunnelCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext,
            accuracyBufferM: accuracyBufferM
        )
        guard isTruthyOSMTag(tunnelCandidate.tunnel),
              !isTruthyOSMTag(surfaceCandidate.tunnel),
              portalEligible || hasCommittedTunnelApproachEvidence(
                for: tunnelCandidate,
                matchContext: matchContext,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
              ) else {
            return false
        }
        let portalCommitScore = portalCommitProgressScore(for: tunnelCandidate, matchContext: matchContext)
        let allowedSlack =
            max(Self.tunnelPortalScoreSlackM, min(accuracyBufferM, 20.0)) +
            (portalCommitScore * Self.tunnelPortalCommitSlackBonusM)
        return tunnelCandidate.score <= surfaceCandidate.score + allowedSlack
    }

    private func shouldKeepTunnelContinuity(
        tunnelCandidate: WayCandidate,
        over surfaceCandidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?
    ) -> Bool {
        guard isTruthyOSMTag(tunnelCandidate.tunnel),
              !isTruthyOSMTag(surfaceCandidate.tunnel),
              matchContext.isInTunnelMode else {
            return false
        }
        if isCorridorCandidateSelectable(
            surfaceCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext,
            pairContext: pairContext,
            accuracyBufferM: accuracyBufferM,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        ),
           surfaceCandidate.score <= tunnelCandidate.score + Self.tunnelPortalScoreSlackM {
            return false
        }
        return tunnelCandidate.score <= surfaceCandidate.score + max(Self.tunnelPortalScoreSlackM, accuracyBufferM)
    }

    private func shouldSuppressImmediateSameRefBounce(
        candidate: WayCandidate,
        over preferredCandidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double
    ) -> Bool {
        guard isImmediateSameRefBounceCandidate(
            candidate,
            preferredCandidate: preferredCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks
        ) else {
            return false
        }
        let requiredScoreImprovement = max(Self.sameRefBounceMinScoreImprovementM, accuracyBufferM)
        if preferredCandidate.score - candidate.score >= requiredScoreImprovement {
            return false
        }
        let requiredDistanceImprovement = Self.sameRefBounceMinDistanceImprovementM + min(accuracyBufferM * 0.25, 4.0)
        if preferredCandidate.distanceM - candidate.distanceM >= requiredDistanceImprovement {
            return false
        }
        return true
    }

    private func shouldApplyAntiABAHysteresis(
        candidate: WayCandidate,
        holdCandidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        accuracyBufferM: Double
    ) -> Bool {
        guard let candidateWayID = normalizedWayID(candidate.wayID),
              let holdWayID = normalizedWayID(holdCandidate.wayID),
              let preferredWayID = matchContext.preferredWayID,
              let priorWayID = matchContext.recentWayHistory.dropFirst().first,
              holdWayID == preferredWayID,
              candidateWayID == priorWayID,
              candidateWayID != holdWayID else {
            return false
        }
        guard isTruthyOSMTag(candidate.tunnel) == isTruthyOSMTag(holdCandidate.tunnel) else {
            return false
        }

        let candidateCorridorSnapshot = candidateCorridorState(
            for: candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext
        )?.snapshot
        let holdCorridorSnapshot = candidateCorridorState(
            for: holdCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            progressContext: progressContext
        )?.snapshot
        let sameCorridor =
            sameCorridorState(candidateCorridorSnapshot, holdCorridorSnapshot) ||
            (candidateCorridorSnapshot == nil && holdCorridorSnapshot == nil)
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        let holdRefTokens = Set(Self.normalizedRefTokens(holdCandidate.streetRef))
        let sharesRef = !candidateRefTokens.isEmpty && !candidateRefTokens.isDisjoint(with: holdRefTokens)
        let linked = wayLinks.available && (
            areLinkedWays(candidateWayID, holdWayID, wayLinks: wayLinks) ||
            areSharedRefLinkedWays(candidateWayID, holdWayID, wayLinks: wayLinks)
        )
        guard sameCorridor || sharesRef || linked else {
            return false
        }

        let requiredScoreImprovement = max(Self.sameRefBounceMinScoreImprovementM, accuracyBufferM)
        if holdCandidate.score - candidate.score >= requiredScoreImprovement {
            return false
        }
        let requiredDistanceImprovement = Self.sameRefBounceMinDistanceImprovementM + min(accuracyBufferM * 0.25, 4.0)
        if holdCandidate.distanceM - candidate.distanceM >= requiredDistanceImprovement {
            return false
        }
        return true
    }

    private func isImmediateSameRefBounceCandidate(
        _ candidate: WayCandidate,
        preferredCandidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        guard let candidateWayID = normalizedWayID(candidate.wayID),
              let preferredWayID = normalizedWayID(preferredCandidate.wayID),
              candidateWayID != preferredWayID,
              let priorWayID = matchContext.recentWayHistory.dropFirst().first,
              candidateWayID == priorWayID else {
            return false
        }
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        let preferredRefTokens = Set(Self.normalizedRefTokens(preferredCandidate.streetRef))
        guard !candidateRefTokens.isEmpty,
              !candidateRefTokens.isDisjoint(with: preferredRefTokens),
              wayLinks.available else {
            return false
        }
        return areLinkedWays(candidateWayID, preferredWayID, wayLinks: wayLinks) ||
            areSharedRefLinkedWays(candidateWayID, preferredWayID, wayLinks: wayLinks)
    }

    private func isImmediateSameRefBounceTransition(
        from hypothesis: WayMatchHypothesis,
        to candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext
    ) -> Bool {
        guard hypothesis.wayID == matchContext.preferredWayID,
              let preferredWaypoint = normalizedWayID(candidate.wayID) else {
            return false
        }
        let preferredCandidate = WayCandidate(
            wayID: hypothesis.wayID,
            highway: hypothesis.highway,
            service: nil,
            tunnel: hypothesis.isTunnel ? "yes" : nil,
            streetName: nil,
            streetBaseName: nil,
            streetRef: hypothesis.streetRef,
            speedKmh: nil,
            speedSource: .none,
            isUnlimitedSpeedLimit: false,
            distanceM: 0.0,
            endpointProximityM: hypothesis.endpointProximityM,
            distanceToStartM: 0.0,
            distanceToEndM: 0.0,
            score: hypothesis.emissionScore,
            queryPoint: (
                hypothesis.startLat ?? 0.0,
                hypothesis.startLon ?? 0.0
            ),
            points: [],
            localHeadingDeg: axisHeadingDeg(
                from: hypothesis.startLat,
                lon1: hypothesis.startLon,
                to: hypothesis.endLat,
                lon2: hypothesis.endLon
            ),
            wayLengthM: nil,
            startNodeKey: nil,
            endNodeKey: nil,
            startPoint: hypothesis.startLat.flatMap { startLat in
                hypothesis.startLon.map { (startLat, $0) }
            },
            endPoint: hypothesis.endLat.flatMap { endLat in
                hypothesis.endLon.map { (endLat, $0) }
            },
            startHeadingDeg: axisHeadingDeg(
                from: hypothesis.startLat,
                lon1: hypothesis.startLon,
                to: hypothesis.endLat,
                lon2: hypothesis.endLon
            ),
            endHeadingDeg: axisHeadingDeg(
                from: hypothesis.startLat,
                lon1: hypothesis.startLon,
                to: hypothesis.endLat,
                lon2: hypothesis.endLon
            )
        )
        guard preferredWaypoint != hypothesis.wayID else {
            return false
        }
        return isImmediateSameRefBounceCandidate(
            candidate,
            preferredCandidate: preferredCandidate,
            matchContext: matchContext,
            wayLinks: wayLinks
        )
    }

    private func normalizedWayID(_ raw: String?) -> String? {
        let normalized = raw?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let normalized, !normalized.isEmpty else {
            return nil
        }
        return normalized
    }

    private func isLegacyTunnelCandidateSelectable(
        _ candidate: WayCandidate,
        matchContext: NormalizedMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double
    ) -> Bool {
        guard isTruthyOSMTag(candidate.tunnel) else {
            return true
        }
        let candidateWayID = normalizedWayID(candidate.wayID)
        let candidateRefTokens = Set(Self.normalizedRefTokens(candidate.streetRef))
        if matchContext.isInTunnelMode {
            if let candidateWayID,
               candidateWayID == matchContext.preferredWayID {
                return true
            }
            if let candidateWayID, matchContext.recentTunnelCandidateWayIDs.contains(candidateWayID) {
                return true
            }
            if !candidateRefTokens.isEmpty,
               !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelCandidateRefs) {
                return true
            }
            return isLegacyPortalTransitionCandidate(
                candidate,
                matchContext: matchContext,
                wayLinks: wayLinks,
                accuracyBufferM: accuracyBufferM,
                requireSharedRef: true
            )
        }

        if let candidateWayID,
           candidateWayID == matchContext.preferredWayID {
            return true
        }

        if isLegacyPortalTransitionCandidate(
            candidate,
            matchContext: matchContext,
            wayLinks: wayLinks,
            accuracyBufferM: accuracyBufferM,
            requireSharedRef: true
        ) {
            return true
        }
        if matchContext.hadRecentGPSSignalLoss {
            if let candidateWayID, matchContext.recentTunnelCandidateWayIDs.contains(candidateWayID) {
                return true
            }
            if !candidateRefTokens.isEmpty,
               !candidateRefTokens.isDisjoint(with: matchContext.recentTunnelCandidateRefs) {
                return candidate.endpointProximityM <= Self.tunnelPortalEntryEndpointThresholdM + accuracyBufferM
            }
        }
        return false
    }

    static func normalizedRefTokens(_ raw: String?) -> [String] {
        guard let raw else {
            return []
        }
        return raw
            .split(separator: ";")
            .map { token in
                String(token)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                    .uppercased()
                    .replacingOccurrences(of: " ", with: "")
            }
            .filter { !$0.isEmpty }
    }

    static func normalizedStreetNameTokens(_ raw: String?) -> [String] {
        guard let raw else {
            return []
        }
        let token = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased()
            .unicodeScalars
            .filter { CharacterSet.alphanumerics.contains($0) }
        let normalized = String(String.UnicodeScalarView(token))
        return normalized.isEmpty ? [] : [normalized]
    }

    private func haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double) -> Double {
        let r = 6_371_008.8
        let p1 = lat1 * .pi / 180.0
        let p2 = lat2 * .pi / 180.0
        let dLat = (lat2 - lat1) * .pi / 180.0
        let dLon = (lon2 - lon1) * .pi / 180.0
        let a = sin(dLat / 2) * sin(dLat / 2) + cos(p1) * cos(p2) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * asin(sqrt(a))
    }

    private func cStringOptional(_ cString: UnsafePointer<UInt8>?) -> String? {
        guard let cString else {
            return nil
        }
        return String(cString: cString)
    }

    private func isTruthyOSMTag(_ raw: String?) -> Bool {
        guard let raw else {
            return false
        }
        let normalized = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.isEmpty {
            return false
        }
        return !["0", "false", "no", "off", "none"].contains(normalized)
    }

    private func tableExists(db: OpaquePointer, name: String) -> Bool {
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1 LIMIT 1"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return false
        }
        sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT)
        return sqlite3_step(stmt) == SQLITE_ROW
    }

    private func columnExists(db: OpaquePointer, table: String, column: String) -> Bool {
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "PRAGMA table_info(\(table));"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return false
        }
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let name = cStringOptional(sqlite3_column_text(stmt, 1)), name == column {
                return true
            }
        }
        return false
    }

    private func resolveCityContext(db: OpaquePointer, lat: Double, lon: Double) -> CityContext {
        let startNs = DispatchTime.now().uptimeNanoseconds

        let hasBoundaryTables = tableExists(db: db, name: "city_boundary") &&
            tableExists(db: db, name: "city_boundary_rtree") &&
            tableExists(db: db, name: "city_ring")
        let polygonResult: ResolvedCityContext?
        if hasBoundaryTables {
            let hasPlaceTables = tableExists(db: db, name: "city_place") &&
                tableExists(db: db, name: "city_place_rtree")
            polygonResult = resolveCityContextWithPolygons(
                db: db,
                lat: lat,
                lon: lon,
                hasPlaceTables: hasPlaceTables
            )
        } else {
            polygonResult = nil
        }

        let hasAreasTables = tableExists(db: db, name: "areas") && tableExists(db: db, name: "areas_rtree")
        let areaResult: ResolvedCityContext? = hasAreasTables
            ? resolveCityContextFromAreas(db: db, lat: lat, lon: lon)
            : nil

        let resolved = {
            if let polygonResult, let areaResult {
                return preferredCityContext(primary: polygonResult, fallback: areaResult)
            }
            if let polygonResult {
                return polygonResult
            }
            if let areaResult {
                return areaResult
            }
            return (
                insideCity: nil,
                cityName: nil,
                cityPlaceName: nil,
                cityDistrictName: nil,
                citySource: "unavailable",
                candidateBoundaries: 0,
                containingBoundaries: 0,
                placeCandidates: 0
            )
        }()

        let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
        return CityContext(
            insideCity: resolved.insideCity,
            cityName: resolved.cityName,
            cityPlaceName: resolved.cityPlaceName,
            cityDistrictName: resolved.cityDistrictName,
            citySource: resolved.citySource,
            candidateBoundaries: resolved.candidateBoundaries,
            containingBoundaries: resolved.containingBoundaries,
            placeCandidates: resolved.placeCandidates,
            resolveMs: elapsed
        )
    }

    private func preferredCityContext(primary: ResolvedCityContext, fallback: ResolvedCityContext) -> ResolvedCityContext {
        let primaryScore = cityContextResolutionScore(primary)
        let fallbackScore = cityContextResolutionScore(fallback)
        return fallbackScore > primaryScore ? fallback : primary
    }

    private func cityContextResolutionScore(_ context: ResolvedCityContext) -> Int {
        let baseScore: Int
        switch context.citySource {
        case "admin_polygon":
            baseScore = 50
        case "admin_bbox":
            baseScore = 40
        case "place_bbox":
            baseScore = 30
        case "place_fallback", "place_nearest":
            baseScore = 20
        default:
            baseScore = 0
        }
        let cityNameBonus = (context.cityName?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false) ? 2 : 0
        let districtBonus = (context.cityDistrictName?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false) ? 1 : 0
        return baseScore + cityNameBonus + districtBonus
    }

    private func resolveResidentialContext(db: OpaquePointer, lat: Double, lon: Double, limitRows: Int = 1024) -> ResidentialContext {
        let startNs = DispatchTime.now().uptimeNanoseconds

        let hasAreasTables = tableExists(db: db, name: "areas") && tableExists(db: db, name: "areas_rtree")
        let hasResidentialColumn = columnExists(db: db, table: "areas", column: "residential")
        let hasPointsColumn = columnExists(db: db, table: "areas", column: "points_json")
        guard hasAreasTables, hasResidentialColumn, hasPointsColumn else {
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
            return ResidentialContext(insideCity: nil, candidatePolygons: 0, containingPolygons: 0, resolveMs: elapsed)
        }

        let sql = """
        SELECT a.residential, a.points_json
        FROM areas_rtree r
        JOIN areas a ON a.row_id = r.row_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
          AND a.residential IS NOT NULL
          AND trim(a.residential) <> ''
        LIMIT ?5
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
            return ResidentialContext(insideCity: nil, candidatePolygons: 0, containingPolygons: 0, resolveMs: elapsed)
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, lon)
        sqlite3_bind_double(stmt, 2, lon)
        sqlite3_bind_double(stmt, 3, lat)
        sqlite3_bind_double(stmt, 4, lat)
        sqlite3_bind_int64(stmt, 5, Int64(limitRows))

        var candidates = 0
        var containing = 0
        while sqlite3_step(stmt) == SQLITE_ROW {
            guard let pointsRaw = cStringOptional(sqlite3_column_text(stmt, 1)),
                  let ring = parseRingPoints(pointsRaw) else {
                continue
            }
            candidates += 1
            if pointInRing(lon: lon, lat: lat, ring: ring) {
                containing += 1
            }
        }

        let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
        let insideCity: Bool? = candidates > 0 ? (containing > 0) : nil
        return ResidentialContext(
            insideCity: insideCity,
            candidatePolygons: candidates,
            containingPolygons: containing,
            resolveMs: elapsed
        )
    }

    private func highwayImpliesInsideCity(_ highway: String?) -> Bool {
        guard let highway else {
            return false
        }
        return Self.inCityHighwayClasses.contains(
            highway.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        )
    }

    private func applyGermanLowSpeedInCityHeuristic(
        insideCityDecision: (insideCity: Bool?, source: String?),
        speedKmh: Int?
    ) -> (insideCity: Bool?, source: String?) {
        guard insideCityDecision.insideCity != true,
              Self.germanLowSpeedLimitImpliesInsideCity(countryCode: countryCode, speedKmh: speedKmh) else {
            return insideCityDecision
        }
        return (true, "de_speed_limit_lt_50")
    }

    private func resolveCityContextWithPolygons(
        db: OpaquePointer,
        lat: Double,
        lon: Double,
        hasPlaceTables: Bool,
        limitRows: Int = 2048
    ) -> ResolvedCityContext? {
        let boundarySQL = """
        SELECT b.row_id, b.admin_level, b.name, b.min_lon, b.min_lat, b.max_lon, b.max_lat
        FROM city_boundary_rtree r
        JOIN city_boundary b ON b.row_id = r.row_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
          AND b.admin_level IN (6, 8, 9)
        LIMIT ?5
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, boundarySQL, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return nil
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, lon)
        sqlite3_bind_double(stmt, 2, lon)
        sqlite3_bind_double(stmt, 3, lat)
        sqlite3_bind_double(stmt, 4, lat)
        sqlite3_bind_int64(stmt, 5, Int64(limitRows))

        var boundaries: [CityBoundaryCandidate] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            boundaries.append(
                CityBoundaryCandidate(
                    rowID: sqlite3_column_int64(stmt, 0),
                    adminLevel: Int(sqlite3_column_int64(stmt, 1)),
                    name: cStringOptional(sqlite3_column_text(stmt, 2)),
                    minLon: sqlite3_column_double(stmt, 3),
                    minLat: sqlite3_column_double(stmt, 4),
                    maxLon: sqlite3_column_double(stmt, 5),
                    maxLat: sqlite3_column_double(stmt, 6)
                )
            )
        }

        var containing: [(adminLevel: Int, bboxArea: Double, name: String)] = []
        for boundary in boundaries {
            let name = boundary.name?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !name.isEmpty else {
                continue
            }
            if boundaryContainsPoint(db: db, boundaryRowID: boundary.rowID, lon: lon, lat: lat) {
                let bboxArea = max(boundary.maxLon - boundary.minLon, 0) * max(boundary.maxLat - boundary.minLat, 0)
                containing.append((adminLevel: boundary.adminLevel, bboxArea: bboxArea, name: name))
            }
        }

        let adminDisplay = Self.buildAdminCityDisplay(from: containing)
        if let cityName = adminDisplay.cityName {
            return (
                insideCity: true,
                cityName: cityName,
                cityPlaceName: adminDisplay.cityPlaceName,
                cityDistrictName: adminDisplay.cityDistrictName,
                citySource: "admin_polygon",
                candidateBoundaries: boundaries.count,
                containingBoundaries: containing.count,
                placeCandidates: 0
            )
        }

        if hasPlaceTables {
            let placeSQL = """
            SELECT p.place, p.name, p.lon, p.lat
            FROM city_place_rtree r
            JOIN city_place p ON p.row_id = r.row_id
            WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
              AND r.min_lat <= ?3 AND r.max_lat >= ?4
            ORDER BY ((p.lon - ?5) * (p.lon - ?6) + (p.lat - ?7) * (p.lat - ?8)) ASC
            LIMIT 16
            """
            var placeStmt: OpaquePointer?
            if sqlite3_prepare_v2(db, placeSQL, -1, &placeStmt, nil) == SQLITE_OK, let placeStmt {
                defer { sqlite3_finalize(placeStmt) }
                sqlite3_bind_double(placeStmt, 1, lon + 0.3)
                sqlite3_bind_double(placeStmt, 2, lon - 0.3)
                sqlite3_bind_double(placeStmt, 3, lat + 0.3)
                sqlite3_bind_double(placeStmt, 4, lat - 0.3)
                sqlite3_bind_double(placeStmt, 5, lon)
                sqlite3_bind_double(placeStmt, 6, lon)
                sqlite3_bind_double(placeStmt, 7, lat)
                sqlite3_bind_double(placeStmt, 8, lat)

                var candidates: [(rank: Int, distanceM: Double, name: String)] = []
                while sqlite3_step(placeStmt) == SQLITE_ROW {
                    guard let place = cStringOptional(sqlite3_column_text(placeStmt, 0)),
                          let rank = Self.placeRank[place],
                          let name = cStringOptional(sqlite3_column_text(placeStmt, 1)),
                          !name.isEmpty else {
                        continue
                    }
                    let placeLon = sqlite3_column_double(placeStmt, 2)
                    let placeLat = sqlite3_column_double(placeStmt, 3)
                    let distance = haversineM(lat1: lat, lon1: lon, lat2: placeLat, lon2: placeLon)
                    candidates.append((rank: rank, distanceM: distance, name: name))
                }
                if let best = Self.selectNearestPlaceFallback(from: candidates) {
                    return (
                        insideCity: false,
                        cityName: best.name,
                        cityPlaceName: best.name,
                        cityDistrictName: nil,
                        citySource: "place_fallback",
                        candidateBoundaries: boundaries.count,
                        containingBoundaries: 0,
                        placeCandidates: candidates.count
                    )
                }
            }
        }

        return (
            insideCity: false,
            cityName: nil,
            cityPlaceName: nil,
            cityDistrictName: nil,
            citySource: hasPlaceTables ? "admin_polygons_plus_places" : "admin_polygons",
            candidateBoundaries: boundaries.count,
            containingBoundaries: 0,
            placeCandidates: 0
        )
    }

    private func resolveCityContextFromAreas(
        db: OpaquePointer,
        lat: Double,
        lon: Double,
        limitRows: Int = 512
    ) -> ResolvedCityContext {
        let hasPointsColumn = columnExists(db: db, table: "areas", column: "points_json")
        let sql = """
        SELECT a.name, a.place, a.boundary, a.admin_level, a.min_lon, a.min_lat, a.max_lon, a.max_lat, \(hasPointsColumn ? "a.points_json" : "NULL")
        FROM areas_rtree r
        JOIN areas a ON a.row_id = r.row_id
        WHERE (
            r.min_lon <= ?1 AND r.max_lon >= ?2
            AND r.min_lat <= ?3 AND r.max_lat >= ?4
        ) OR (
            a.place IN ('city','town','village','hamlet')
            AND r.min_lon <= ?5 AND r.max_lon >= ?6
            AND r.min_lat <= ?7 AND r.max_lat >= ?8
        )
        LIMIT ?9
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return (
                insideCity: nil,
                cityName: nil,
                cityPlaceName: nil,
                cityDistrictName: nil,
                citySource: "bbox_unavailable",
                candidateBoundaries: 0,
                containingBoundaries: 0,
                placeCandidates: 0
            )
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, lon)
        sqlite3_bind_double(stmt, 2, lon)
        sqlite3_bind_double(stmt, 3, lat)
        sqlite3_bind_double(stmt, 4, lat)
        sqlite3_bind_double(stmt, 5, lon + 0.3)
        sqlite3_bind_double(stmt, 6, lon - 0.3)
        sqlite3_bind_double(stmt, 7, lat + 0.3)
        sqlite3_bind_double(stmt, 8, lat - 0.3)
        sqlite3_bind_int64(stmt, 9, Int64(limitRows))

        var areas: [AreaCandidate] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let adminLevelRaw = cStringOptional(sqlite3_column_text(stmt, 3))
            let adminLevel = adminLevelRaw.flatMap(Int.init)
            areas.append(
                AreaCandidate(
                    name: cStringOptional(sqlite3_column_text(stmt, 0)),
                    place: cStringOptional(sqlite3_column_text(stmt, 1)),
                    boundary: cStringOptional(sqlite3_column_text(stmt, 2)),
                    adminLevel: adminLevel,
                    minLon: sqlite3_column_double(stmt, 4),
                    minLat: sqlite3_column_double(stmt, 5),
                    maxLon: sqlite3_column_double(stmt, 6),
                    maxLat: sqlite3_column_double(stmt, 7),
                    points: cStringOptional(sqlite3_column_text(stmt, 8)).flatMap(parseRingPoints) ?? []
                )
            )
        }

        var containingAdminExact: [(adminLevel: Int, bboxArea: Double, name: String)] = []
        var containingAdminBBox: [(adminLevel: Int, bboxArea: Double, name: String)] = []
        var containingPlaces: [(rank: Int, distanceM: Double, name: String)] = []
        var nearbyPlaces: [(rank: Int, distanceM: Double, name: String)] = []

        for area in areas {
            guard let name = area.name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty else {
                continue
            }
            let inside = pointInBBox(lat: lat, lon: lon, minLon: area.minLon, minLat: area.minLat, maxLon: area.maxLon, maxLat: area.maxLat)
            let areaSize = max(area.maxLon - area.minLon, 0) * max(area.maxLat - area.minLat, 0)

            if area.boundary == "administrative",
               let level = area.adminLevel,
               Self.cityBoundaryLevelPriority[level] != nil,
               inside {
                if Self.isClosedAreaRing(area.points), pointInRing(lon: lon, lat: lat, ring: area.points) {
                    containingAdminExact.append((adminLevel: level, bboxArea: areaSize, name: name))
                } else {
                    containingAdminBBox.append((adminLevel: level, bboxArea: areaSize, name: name))
                }
            }

            if let place = area.place,
               let rank = Self.placeRank[place] {
                let centerLat = (area.minLat + area.maxLat) / 2
                let centerLon = (area.minLon + area.maxLon) / 2
                let distance = haversineM(lat1: lat, lon1: lon, lat2: centerLat, lon2: centerLon)
                nearbyPlaces.append((rank: rank, distanceM: distance, name: name))
                if inside {
                    containingPlaces.append((rank: rank, distanceM: distance, name: name))
                }
            }
        }

        let exactAdminDisplay = Self.buildAdminCityDisplay(from: containingAdminExact)
        if let cityName = exactAdminDisplay.cityName {
            return (
                insideCity: true,
                cityName: cityName,
                cityPlaceName: exactAdminDisplay.cityPlaceName,
                cityDistrictName: exactAdminDisplay.cityDistrictName,
                citySource: "admin_polygon",
                candidateBoundaries: containingAdminExact.count,
                containingBoundaries: containingAdminExact.count,
                placeCandidates: nearbyPlaces.count
            )
        }

        let bboxAdminDisplay = Self.buildAdminCityDisplay(from: containingAdminBBox)
        if let cityName = bboxAdminDisplay.cityName {
            return (
                insideCity: true,
                cityName: cityName,
                cityPlaceName: bboxAdminDisplay.cityPlaceName,
                cityDistrictName: bboxAdminDisplay.cityDistrictName,
                citySource: "admin_bbox",
                candidateBoundaries: containingAdminBBox.count,
                containingBoundaries: containingAdminBBox.count,
                placeCandidates: nearbyPlaces.count
            )
        }

        if let best = Self.selectContainingPlace(from: containingPlaces) {
            return (
                true,
                best.name,
                best.name,
                nil,
                "place_bbox",
                0,
                0,
                nearbyPlaces.count
            )
        }

        if let best = Self.selectNearestPlaceFallback(from: nearbyPlaces) {
            return (
                false,
                best.name,
                best.name,
                nil,
                "place_nearest",
                0,
                0,
                nearbyPlaces.count
            )
        }

        if containingAdminExact.isEmpty,
           containingAdminBBox.isEmpty,
           containingPlaces.isEmpty,
           nearbyPlaces.isEmpty {
            return (
                insideCity: nil,
                cityName: nil,
                cityPlaceName: nil,
                cityDistrictName: nil,
                citySource: "bbox_unclassified",
                candidateBoundaries: 0,
                containingBoundaries: 0,
                placeCandidates: 0
            )
        }

        return (
            false,
            nil,
            nil,
            nil,
            "bbox_no_match",
            0,
            0,
            0
        )
    }

    private func boundaryContainsPoint(db: OpaquePointer, boundaryRowID: Int64, lon: Double, lat: Double) -> Bool {
        let sql = """
        SELECT outer_index, is_hole, points_json
        FROM city_ring
        WHERE boundary_row_id = ?1
        ORDER BY outer_index, is_hole, ring_index
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return false
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_int64(stmt, 1, boundaryRowID)

        struct RingGroup {
            var outer: [(Double, Double)]?
            var holes: [[(Double, Double)]]
        }

        var groups: [Int: RingGroup] = [:]

        while sqlite3_step(stmt) == SQLITE_ROW {
            let outerIndex = Int(sqlite3_column_int64(stmt, 0))
            let isHole = Int(sqlite3_column_int64(stmt, 1))
            guard let pointsRaw = cStringOptional(sqlite3_column_text(stmt, 2)),
                  let ring = parseRingPoints(pointsRaw) else {
                continue
            }

            var group = groups[outerIndex] ?? RingGroup(outer: nil, holes: [])
            if isHole == 0 {
                group.outer = ring
            } else {
                group.holes.append(ring)
            }
            groups[outerIndex] = group
        }

        for group in groups.values {
            guard let outer = group.outer else {
                continue
            }
            if !pointInRing(lon: lon, lat: lat, ring: outer) {
                continue
            }
            let inHole = group.holes.contains { hole in
                pointInRing(lon: lon, lat: lat, ring: hole)
            }
            if !inHole {
                return true
            }
        }

        return false
    }

    private func parseRingPoints(_ raw: String) -> [(Double, Double)]? {
        guard let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let arr = json as? [Any] else {
            return nil
        }
        var out: [(Double, Double)] = []
        out.reserveCapacity(arr.count)
        for element in arr {
            guard let pair = element as? [Any], pair.count >= 2 else {
                continue
            }
            guard let lon = pair[0] as? Double,
                  let lat = pair[1] as? Double else {
                continue
            }
            out.append((lon, lat))
        }
        return out.count >= 4 ? out : nil
    }

    private func pointInRing(lon: Double, lat: Double, ring: [(Double, Double)]) -> Bool {
        if ring.count < 4 {
            return false
        }
        var inside = false
        for i in 0..<(ring.count - 1) {
            let (x1, y1) = ring[i]
            let (x2, y2) = ring[i + 1]
            if pointOnSegment(px: lon, py: lat, x1: x1, y1: y1, x2: x2, y2: y2) {
                return true
            }
            let crossesLatitude = ((y1 > lat) != (y2 > lat))
            let denom = (y2 - y1) == 0 ? 1e-30 : (y2 - y1)
            let xAtLat = (x2 - x1) * (lat - y1) / denom + x1
            if crossesLatitude && lon < xAtLat {
                inside.toggle()
            }
        }
        return inside
    }

    private func pointOnSegment(px: Double, py: Double, x1: Double, y1: Double, x2: Double, y2: Double) -> Bool {
        let eps = 1e-12
        let cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
        if abs(cross) > eps {
            return false
        }
        let dot = (px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)
        if dot < -eps {
            return false
        }
        let sqLen = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1)
        if dot - sqLen > eps {
            return false
        }
        return true
    }

    private func pointInBBox(lat: Double, lon: Double, minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) -> Bool {
        return minLat <= lat && lat <= maxLat && minLon <= lon && lon <= maxLon
    }
}

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

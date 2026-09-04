import Foundation
import CryptoKit
import OSLog
import SQLite3

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

struct BundleArtifact: Codable, Sendable {
    let file: String
    let bytes: Int64
    let sha256: String
    let url: String?
    let compression: String?
    let uncompressedBytes: Int64?
    let uncompressedSHA256: String?

    enum CodingKeys: String, CodingKey {
        case file
        case bytes
        case sha256
        case url
        case compression
        case uncompressedBytes = "uncompressed_bytes"
        case uncompressedSHA256 = "uncompressed_sha256"
    }

    init(
        file: String,
        bytes: Int64,
        sha256: String,
        url: String?,
        compression: String? = nil,
        uncompressedBytes: Int64? = nil,
        uncompressedSHA256: String? = nil
    ) {
        self.file = file
        self.bytes = bytes
        self.sha256 = sha256
        self.url = url
        self.compression = compression
        self.uncompressedBytes = uncompressedBytes
        self.uncompressedSHA256 = uncompressedSHA256
    }
}

struct BundleCoverageBBox: Codable, Sendable {
    let minLon: Double
    let minLat: Double
    let maxLon: Double
    let maxLat: Double

    enum CodingKeys: String, CodingKey {
        case minLon = "min_lon"
        case minLat = "min_lat"
        case maxLon = "max_lon"
        case maxLat = "max_lat"
    }
}

struct BundleCoverage: Codable, Sendable {
    let bbox: BundleCoverageBBox
    let poly: BundleArtifact?
}

struct V3BundleManifest: Codable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let region: String
    let countryCode: String?
    let bundleVersion: String
    let createdAtUTC: String
    let minAppVersion: String
    let db: BundleArtifact
    let dbParts: [BundleArtifact]?
    let deltaIndex: BundleArtifact?
    let penaltyRules: BundleArtifact?
    let coverage: BundleCoverage?

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case region
        case countryCode = "country_code"
        case bundleVersion = "bundle_version"
        case createdAtUTC = "created_at_utc"
        case minAppVersion = "min_app_version"
        case db
        case dbParts = "db_parts"
        case deltaIndex = "delta_index"
        case penaltyRules = "penalty_rules"
        case coverage
    }

    init(
        format: String,
        schemaVersion: Int,
        variant: String,
        region: String,
        countryCode: String? = nil,
        bundleVersion: String,
        createdAtUTC: String,
        minAppVersion: String,
        db: BundleArtifact,
        dbParts: [BundleArtifact]?,
        deltaIndex: BundleArtifact?,
        penaltyRules: BundleArtifact? = nil,
        coverage: BundleCoverage? = nil
    ) {
        self.format = format
        self.schemaVersion = schemaVersion
        self.variant = variant
        self.region = region
        self.countryCode = countryCode
        self.bundleVersion = bundleVersion
        self.createdAtUTC = createdAtUTC
        self.minAppVersion = minAppVersion
        self.db = db
        self.dbParts = dbParts
        self.deltaIndex = deltaIndex
        self.penaltyRules = penaltyRules
        self.coverage = coverage
    }
}

struct V3CountryBundleCatalogRegion: Codable, Sendable {
    let region: String
    let name: String
    let bundleVersion: String
    let manifest: BundleArtifact
    let coverage: BundleCoverage?

    enum CodingKeys: String, CodingKey {
        case region
        case name
        case bundleVersion = "bundle_version"
        case manifest
        case coverage
    }
}

struct V3CountryBundleCatalog: Codable, Sendable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let country: String
    let bundleVersion: String
    let createdAtUTC: String
    let maxCountryPBFBytes: Int64
    let regions: [V3CountryBundleCatalogRegion]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case country
        case bundleVersion = "bundle_version"
        case createdAtUTC = "created_at_utc"
        case maxCountryPBFBytes = "max_country_pbf_bytes"
        case regions
    }
}

struct V3BundleTargetRegionConfig: Codable, Sendable {
    let regionID: String
    let regionName: String?

    enum CodingKeys: String, CodingKey {
        case regionID = "region_id"
        case regionName = "name"
    }
}

struct V3BundleTargetCountryConfig: Codable, Sendable {
    let rank: Int
    let countryID: String
    let countryCode: String
    let iso2: String?
    let mode: String
    let regions: [V3BundleTargetRegionConfig]

    enum CodingKeys: String, CodingKey {
        case rank
        case countryID = "country_id"
        case countryCode = "country_code"
        case iso2
        case mode
        case regions
    }
}

struct V3BundleTargetsConfig: Codable, Sendable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let maxCountryPBFBytes: Int64
    let githubOwner: String?
    let githubRepo: String?
    let countries: [V3BundleTargetCountryConfig]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case maxCountryPBFBytes = "max_country_pbf_bytes"
        case githubOwner = "github_owner"
        case githubRepo = "github_repo"
        case countries
    }

    func country(countryID: String) -> V3BundleTargetCountryConfig? {
        let key = countryID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !key.isEmpty else {
            return nil
        }
        return countries.first { $0.countryID.lowercased() == key }
    }

    func country(countryCode: String) -> V3BundleTargetCountryConfig? {
        let key = countryCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !key.isEmpty else {
            return nil
        }
        return countries.first { $0.countryCode.uppercased() == key }
    }

    static func loadBundled(
        named resourceName: String = "BundleTargets.top10",
        bundle: Bundle = .main
    ) throws -> V3BundleTargetsConfig {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            throw ConsumerAppError.io("Missing bundled \(resourceName).json")
        }
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(V3BundleTargetsConfig.self, from: data)
    }

    func manifestEndpoints(
        githubOwner: String? = nil,
        githubRepo: String? = nil,
        preferredCountryCode: String? = nil
    ) -> [V3ManifestEndpoint] {
        let owner = (githubOwner ?? self.githubOwner)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let repo = (githubRepo ?? self.githubRepo)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let owner, !owner.isEmpty, let repo, !repo.isEmpty else {
            return []
        }
        let preferredCode = preferredCountryCode?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .uppercased()
        let orderedCountries: [V3BundleTargetCountryConfig] = {
            if let preferredCode,
               let preferredIndex = countries.firstIndex(where: { $0.countryCode.uppercased() == preferredCode }) {
                var reordered = countries
                let preferred = reordered.remove(at: preferredIndex)
                return [preferred] + reordered
            }
            return countries
        }()

        var out: [V3ManifestEndpoint] = []
        var seen = Set<URL>()
        for country in orderedCountries {
            let countryToken = idToken(country.countryID)
            guard !countryToken.isEmpty else {
                continue
            }
            let usesRegionalShards = (country.mode == "regional_shards")
            if !usesRegionalShards {
                let manifestFile = "\(countryToken)_manifest.json"
                guard let url = URL(
                    string: "https://github.com/\(owner)/\(repo)/releases/download/\(countryToken)/\(manifestFile)"
                ) else {
                    continue
                }
                guard seen.insert(url).inserted else {
                    continue
                }
                out.append(
                    V3ManifestEndpoint(
                        countryID: country.countryID,
                        countryCode: country.countryCode,
                        regionID: country.countryID,
                        manifestRegion: countryToken,
                        regionName: nil,
                        manifestURL: url
                    )
                )
                continue
            }
            for region in country.regions {
                let regionFullID = expandedRegionID(country: country, regionID: region.regionID)
                let regionTail = regionFullID.split(separator: "/").last.map(String.init) ?? regionFullID
                let regionToken = idToken(regionTail)
                guard !regionToken.isEmpty else {
                    continue
                }
                let releaseTag = regionToken
                let manifestFile = "\(regionToken)_manifest.json"
                guard let url = URL(
                    string: "https://github.com/\(owner)/\(repo)/releases/download/\(releaseTag)/\(manifestFile)"
                ) else {
                    continue
                }
                guard seen.insert(url).inserted else {
                    continue
                }
                out.append(
                    V3ManifestEndpoint(
                        countryID: country.countryID,
                        countryCode: country.countryCode,
                        regionID: regionFullID,
                        manifestRegion: regionToken,
                        regionName: region.regionName,
                        manifestURL: url
                    )
                )
            }
        }
        return out
    }

    private func expandedRegionID(country: V3BundleTargetCountryConfig, regionID: String) -> String {
        let trimmedRegionID = regionID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let trimmedCountryID = country.countryID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !trimmedRegionID.isEmpty else {
            return trimmedCountryID
        }
        if trimmedRegionID.contains("/") {
            return trimmedRegionID
        }
        if country.mode == "regional_shards" && trimmedRegionID != trimmedCountryID {
            return "\(trimmedCountryID)/\(trimmedRegionID)"
        }
        return trimmedRegionID
    }

    private func idToken(_ raw: String) -> String {
        raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .replacingOccurrences(of: "_", with: "-")
            .replacingOccurrences(of: "/", with: "-")
    }
}

struct V3ManifestEndpoint: Sendable, Hashable {
    let countryID: String
    let countryCode: String
    let regionID: String
    let manifestRegion: String
    let regionName: String?
    let manifestURL: URL

    init(
        countryID: String,
        countryCode: String,
        regionID: String,
        manifestRegion: String,
        regionName: String? = nil,
        manifestURL: URL
    ) {
        self.countryID = countryID
        self.countryCode = countryCode
        self.regionID = regionID
        self.manifestRegion = manifestRegion
        self.regionName = regionName
        self.manifestURL = manifestURL
    }
}

struct DownloadedBundleInfo: Sendable, Hashable, Identifiable {
    var id: String { "\(region)|\(bundleVersion)|\(dbFileName)" }
    let region: String
    let bundleVersion: String
    let countryCode: String?
    let dbFileName: String
    let dbPath: String
}

struct LocalBundleRoute: Sendable {
    let region: String
    let bundleVersion: String
    let countryCode: String?
    let dbPath: String
    let dbSHA256: String?

    init(
        region: String,
        bundleVersion: String,
        countryCode: String?,
        dbPath: String,
        dbSHA256: String? = nil
    ) {
        self.region = region
        self.bundleVersion = bundleVersion
        self.countryCode = countryCode
        self.dbPath = dbPath
        self.dbSHA256 = dbSHA256
    }
}

struct PenaltyRuleContext: Sendable {
    let countryCode: String?
    let rulesPath: String?
    let rulesFileName: String?
}

struct V3DeltaIndex: Codable {
    struct Entry: Codable {
        let fromBundleVersion: String
        let toBundleVersion: String
        let region: String?
        let deltaManifestFile: String

        enum CodingKeys: String, CodingKey {
            case fromBundleVersion = "from_bundle_version"
            case toBundleVersion = "to_bundle_version"
            case region
            case deltaManifestFile = "delta_manifest_file"
        }
    }

    let format: String
    let schemaVersion: Int
    let count: Int
    let entries: [Entry]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case count
        case entries
    }
}

struct V3DeltaManifest: Codable {
    let format: String
    let schemaVersion: Int
    let region: String
    let fromBundleVersion: String
    let toBundleVersion: String
    let patch: BundleArtifact

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case region
        case fromBundleVersion = "from_bundle_version"
        case toBundleVersion = "to_bundle_version"
        case patch
    }
}

struct ActiveBundleState: Codable {
    let region: String
    let bundleVersion: String
    let dbFileName: String
    let dbPath: String?
    let activatedAtUTC: String
    let dbSHA256: String?

    init(
        region: String,
        bundleVersion: String,
        dbFileName: String,
        activatedAtUTC: String,
        dbPath: String? = nil,
        dbSHA256: String? = nil
    ) {
        self.region = region
        self.bundleVersion = bundleVersion
        self.dbFileName = dbFileName
        self.dbPath = dbPath
        self.activatedAtUTC = activatedAtUTC
        self.dbSHA256 = dbSHA256
    }

    enum CodingKeys: String, CodingKey {
        case region
        case bundleVersion = "bundle_version"
        case dbFileName = "db_file_name"
        case dbPath = "db_path"
        case activatedAtUTC = "activated_at_utc"
        case dbSHA256 = "db_sha256"
    }
}

struct BundleSyncResult: Codable {
    enum Mode: String, Codable {
        case bootstrap
        case upToDate
        case fullDownload
        case deltaPatch
    }

    let mode: Mode
    let bundleVersion: String
    let dbPath: String
    let details: String
    let dbSHA256: String?

    init(
        mode: Mode,
        bundleVersion: String,
        dbPath: String,
        details: String,
        dbSHA256: String? = nil
    ) {
        self.mode = mode
        self.bundleVersion = bundleVersion
        self.dbPath = dbPath
        self.details = details
        self.dbSHA256 = dbSHA256
    }
}

struct BundleSyncProgress: Sendable {
    enum Stage: String, Sendable {
        case preparing
        case downloading
        case assembling
        case validating
        case applyingDelta
        case completed
    }

    let stage: Stage
    let detail: String
    let completedBytes: Int64
    let totalBytes: Int64
    let partDownloads: [PartDownloadProgress]
}

struct PartDownloadProgress: Sendable, Identifiable {
    let id: String
    let detail: String
    let completedBytes: Int64
    let totalBytes: Int64
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

enum LocalObservationModality: String, Codable, Sendable {
    case voice_command
    case lock_current_speed
    case computer_vision
}

enum LocalObservationIntentType: String, Codable, Sendable {
    case set_maxspeed
    case temporary_restriction
    case map_inconsistency
    case lock_speed_snapshot
}

enum LocalObservationState: String, Codable, Sendable, CaseIterable {
    case localOnly = "local_only"
    case needsReview = "needs_review"
    case approvedForExport = "approved_for_export"
    case exportedOsc = "exported_osc"
    case editorImported = "editor_imported"
    case uploadedToOsm = "uploaded_to_osm"
    case discarded = "discarded"
}

enum LocalObservationOperation: String, Codable, Sendable {
    case setMaxspeed = "set_maxspeed"
}

enum LocalObservationDirectionScope: String, Codable, Sendable {
    case wayWide = "way_wide"
    case forward
    case backward
    case unknown
}

enum LocalObservationApplicability: String, Codable, Sendable {
    case permanent
    case temporary
    case conditional
    case unresolved
}

enum LocalObservationExportDisposition: String, Codable, Sendable {
    case eligible
    case superseded
    case exported
}

struct LocalObservation: Codable, Sendable, Identifiable {
    let id: String
    let modality: LocalObservationModality
    let intentType: LocalObservationIntentType
    let value: String?
    let lat: Double?
    let lon: Double?
    let headingDeg: Double?
    let roadCandidateIDs: [String]
    let cityContext: String?
    let streetContext: String?
    let capturedAtUTC: String
    let confidenceCalibrated: Double?
    let sourceVersion: String
    let state: LocalObservationState
    let devicePseudoID: String
    let updatedAtUTC: String
    let exportID: String?
    let oldSpeedKmh: Int?
    let newSpeedKmh: Int?
    let evidenceJSON: String?
    let primaryWayID: String?
    let effectiveAtUTC: String?
    let operation: LocalObservationOperation?
    let directionScope: LocalObservationDirectionScope?
    let applicability: LocalObservationApplicability?
    let runtimeApplicable: Bool?
    let finalizedEventID: String?
    let approvalRevision: String?
    let exportDisposition: LocalObservationExportDisposition?
    let exportTagKey: String?

    init(
        id: String,
        modality: LocalObservationModality,
        intentType: LocalObservationIntentType,
        value: String?,
        lat: Double?,
        lon: Double?,
        headingDeg: Double?,
        roadCandidateIDs: [String],
        cityContext: String?,
        streetContext: String?,
        capturedAtUTC: String,
        confidenceCalibrated: Double?,
        sourceVersion: String,
        state: LocalObservationState,
        devicePseudoID: String,
        updatedAtUTC: String,
        exportID: String?,
        oldSpeedKmh: Int?,
        newSpeedKmh: Int?,
        evidenceJSON: String? = nil,
        primaryWayID: String? = nil,
        effectiveAtUTC: String? = nil,
        operation: LocalObservationOperation? = nil,
        directionScope: LocalObservationDirectionScope? = nil,
        applicability: LocalObservationApplicability? = nil,
        runtimeApplicable: Bool? = nil,
        finalizedEventID: String? = nil,
        approvalRevision: String? = nil,
        exportDisposition: LocalObservationExportDisposition? = nil,
        exportTagKey: String? = nil
    ) {
        self.id = id
        self.modality = modality
        self.intentType = intentType
        self.value = value
        self.lat = lat
        self.lon = lon
        self.headingDeg = headingDeg
        self.roadCandidateIDs = roadCandidateIDs
        self.cityContext = cityContext
        self.streetContext = streetContext
        self.capturedAtUTC = capturedAtUTC
        self.confidenceCalibrated = confidenceCalibrated
        self.sourceVersion = sourceVersion
        self.state = state
        self.devicePseudoID = devicePseudoID
        self.updatedAtUTC = updatedAtUTC
        self.exportID = exportID
        self.oldSpeedKmh = oldSpeedKmh
        self.newSpeedKmh = newSpeedKmh
        self.evidenceJSON = evidenceJSON
        self.primaryWayID = primaryWayID
        self.effectiveAtUTC = effectiveAtUTC
        self.operation = operation
        self.directionScope = directionScope
        self.applicability = applicability
        self.runtimeApplicable = runtimeApplicable
        self.finalizedEventID = finalizedEventID
        self.approvalRevision = approvalRevision
        self.exportDisposition = exportDisposition
        self.exportTagKey = exportTagKey
    }
}

struct LocalObservationCaptureContext: Sendable {
    let lat: Double?
    let lon: Double?
    let headingDeg: Double?
    let roadCandidateIDs: [String]
    let cityContext: String?
    let streetContext: String?
    let confidenceCalibrated: Double?
    let sourceVersion: String
}

struct LocalObservationProposal: Sendable {
    struct TargetObject: Sendable {
        let type: String
        let id: String
    }

    let observationID: String
    let targetObjects: [TargetObject]
    let oscXML: String
    let confidenceSummary: String
}

struct LocalObservationExportResult: Sendable {
    let exportID: String
    let packageDirectory: URL
    let changesFile: URL
    let reviewFile: URL
    let readmeFile: URL
}

struct LocalObservationBulkExportResult: Sendable {
    let exportID: String
    let packageDirectory: URL
    let changesFile: URL
    let includedCount: Int
}

enum LocalObservationComputerVisionReceiptDecision: String, Codable, Sendable {
    case inserted
    case equivalent
    case staleGeneration = "stale_generation"
}

struct LocalObservationComputerVisionRecordResult: Sendable {
    let decision: LocalObservationComputerVisionReceiptDecision
    let observation: LocalObservation?
}

actor LocalObservationStore {
    private struct FrozenExportMember: Codable, Sendable {
        let observationID: String
        let wayID: String
        let tagKey: String
        let value: String
        let directionScope: LocalObservationDirectionScope
        let approvalRevision: String
        let effectiveAtUTC: String
        let capturedAtUTC: String
        let sourceVersion: String
        let streetContext: String?
        let cityContext: String?
        let confidenceCalibrated: Double?

        var targetKey: String { "way:\(wayID)|tag:\(tagKey)" }
    }

    private struct ExportReservation: Sendable {
        let batchID: String
        let createdAtUTC: String
        let packageDirectory: URL
        let status: String
        let packageSHA256: String?
        let members: [FrozenExportMember]
    }

    private nonisolated static let logger = Logger(subsystem: "de.youspeed.SpeedConsumer", category: "local-observations")
    private let fileManager: FileManager
    private let userDefaults: UserDefaults
    private let bundle: Bundle
    private let rootDirectoryOverride: URL?
    private let nowProvider: @Sendable () -> Date
    private static let devicePseudoIDDefaultsKey = "youspeed.local_observation.device_pseudo_id"
    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    init(
        fileManager: FileManager = .default,
        userDefaults: UserDefaults = .standard,
        bundle: Bundle = .main,
        rootDirectoryOverride: URL? = nil,
        nowProvider: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.fileManager = fileManager
        self.userDefaults = userDefaults
        self.bundle = bundle
        self.rootDirectoryOverride = rootDirectoryOverride
        self.nowProvider = nowProvider
    }

    func captureVoiceCommand(command: String, context: LocalObservationCaptureContext) throws -> LocalObservation {
        let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw ConsumerAppError.io("Voice command must not be empty")
        }
        let parsedSpeed = Self.extractFirstSpeedKmh(from: trimmed)
        let intent: LocalObservationIntentType = parsedSpeed == nil ? .map_inconsistency : .set_maxspeed
        let value = parsedSpeed.map(String.init) ?? trimmed
        return try insertObservation(
            modality: .voice_command,
            intent: intent,
            value: value,
            context: context,
            initialState: .needsReview
        )
    }

    func lockCurrentSpeed(speedKmh: Int, context: LocalObservationCaptureContext) throws -> LocalObservation {
        guard speedKmh > 0 else {
            throw ConsumerAppError.io("Current speed must be > 0 to create lock observation")
        }
        return try insertObservation(
            modality: .lock_current_speed,
            intent: .lock_speed_snapshot,
            value: String(speedKmh),
            context: context,
            initialState: .needsReview,
            oldSpeedKmh: nil,
            newSpeedKmh: speedKmh
        )
    }

    func recordSpeedLimitChange(
        oldSpeedKmh: Int?,
        newMaxspeedValue: String,
        context: LocalObservationCaptureContext
    ) throws -> LocalObservation {
        let normalizedValue = newMaxspeedValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedValue.isEmpty else {
            throw ConsumerAppError.io("Recorded maxspeed value must not be empty")
        }
        let numericSpeed = Int(normalizedValue)
        if let numericSpeed, numericSpeed <= 0 {
            throw ConsumerAppError.io("Recorded speed must be > 0 km/h")
        }
        let wayID = context.roadCandidateIDs.first?.trimmingCharacters(in: .whitespacesAndNewlines)
        Self.logger.notice(
            "local_obs record_speed_change begin value=\(normalizedValue, privacy: .public) old=\(oldSpeedKmh?.description ?? "n/a", privacy: .public) way=\(wayID ?? "n/a", privacy: .public) source=\(context.sourceVersion, privacy: .public)"
        )
        let observation = try insertObservation(
            modality: .voice_command,
            intent: .set_maxspeed,
            value: normalizedValue,
            context: context,
            initialState: .localOnly,
            oldSpeedKmh: oldSpeedKmh,
            newSpeedKmh: numericSpeed
        )
        Self.logger.notice(
            "local_obs record_speed_change saved id=\(observation.id, privacy: .public) state=\(observation.state.rawValue, privacy: .public) way=\(observation.roadCandidateIDs.first ?? "n/a", privacy: .public) new=\(observation.value ?? "n/a", privacy: .public)"
        )
        return observation
    }

    /// Consumes one finalized passage under the controller's generation gate.
    /// The receipt and optional observation are committed in the same SQLite
    /// transaction, making retries exactly-once even when the value already
    /// exists as the newest correction for the typed target.
    func recordComputerVisionPassageIfNeeded(
        event: TrafficSignPassageEvent,
        decision: TrafficSignPassagePersistenceDecision,
        writePermit: TrafficSignWritePermit
    ) throws -> LocalObservationComputerVisionRecordResult {
        var staleExportBatchIDs: [String] = []
        let consumed = try writePermit.consume {
            try withDatabase { db in
                guard sqlite3_exec(db, "BEGIN IMMEDIATE", nil, nil, nil) == SQLITE_OK else {
                    throw sqliteError(db: db, context: "begin computer-vision observation")
                }
                do {
                    if let existing = try computerVisionReceipt(
                        db: db,
                        finalizedEventID: event.finalizedEventID
                    ) {
                        guard sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK else {
                            throw sqliteError(db: db, context: "commit existing computer-vision receipt")
                        }
                        return existing
                    }

                    let activation = event.activationContext
                    // A boundary match may be absent or explicitly unstable.
                    // The finalizer's stabilized activation/rematch is the only
                    // authoritative target; the boundary remains evidence.
                    let primaryWayID = activation.wayId
                    guard Self.isPositiveWayID(primaryWayID) else {
                        throw ConsumerAppError.io("Computer-vision passage has no valid OSM way id")
                    }
                    let canonicalValue = Self.canonicalMaxspeedValue(decision.value)
                    let evidenceData = try TrafficSignPassageWireEncoder.encode(
                        event: event,
                        decision: decision
                    )
                    guard let evidenceJSON = String(data: evidenceData, encoding: .utf8) else {
                        throw ConsumerAppError.io("Could not encode computer-vision passage evidence")
                    }
                    let canCompareTypedTarget = decision.operation == .setMaxspeed
                        && decision.runtimeApplicable
                        && decision.directionScope != .unknown
                        && canonicalValue != nil
                    let equivalentCorrection: (value: String, observationID: String)?
                    if canCompareTypedTarget {
                        equivalentCorrection = try newestRuntimeCorrection(
                            db: db,
                            wayID: primaryWayID,
                            direction: decision.directionScope
                        )
                    } else {
                        equivalentCorrection = nil
                    }
                    let equivalent = equivalentCorrection?.value == canonicalValue

                    let consumedAtUTC = Self.isoFormatter.string(from: nowProvider())
                    if equivalent {
                        try insertComputerVisionPassageEvidence(
                            db: db,
                            finalizedEventID: event.finalizedEventID,
                            evidenceJSON: evidenceJSON,
                            equivalentObservationID: equivalentCorrection?.observationID,
                            consumedAtUTC: consumedAtUTC
                        )
                        try insertComputerVisionReceipt(
                            db: db,
                            finalizedEventID: event.finalizedEventID,
                            decision: .equivalent,
                            observationID: equivalentCorrection?.observationID,
                            consumedAtUTC: consumedAtUTC
                        )
                        guard sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK else {
                            throw sqliteError(db: db, context: "commit equivalent computer-vision receipt")
                        }
                        return LocalObservationComputerVisionRecordResult(
                            decision: .equivalent,
                            observation: nil
                        )
                    }

                    let observationID = UUID().uuidString.lowercased()
                    let effectiveAtUTC = Self.isoFormatter.string(from: event.passageBoundaryTimestampUTC)
                    let coordinate = event.passageBoundaryCoordinate ?? TrafficSignCoordinate(
                        latitude: activation.latitude,
                        longitude: activation.longitude
                    )
                    let roadIDsData = try JSONEncoder().encode([primaryWayID])
                    let roadIDsJSON = String(data: roadIDsData, encoding: .utf8) ?? "[]"
                    let intent: LocalObservationIntentType
                    if decision.applicability == .temporary {
                        intent = .temporary_restriction
                    } else if decision.operation == .setMaxspeed {
                        intent = .set_maxspeed
                    } else {
                        intent = .map_inconsistency
                    }
                    let exportDisposition: LocalObservationExportDisposition? = decision.operation == .setMaxspeed
                        && decision.applicability == .permanent
                        && decision.directionScope != .unknown
                        ? .eligible
                        : nil
                    let bundleSHA = activation.sourceSignature.bundleSHA256 ?? "unverified"
                    let sourceVersion = "tsr:\(event.packID)|artifact:\(event.artifactSHA256)|bundle_sha256:\(bundleSHA)"
                    let insertSQL = """
                    INSERT INTO observations (
                      observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                      city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                      device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                      evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
                      runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
                    ) VALUES (
                      ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, NULL, NULL, ?9, ?10, ?11, ?12, ?13, ?14,
                      NULL, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, NULL, ?25, ?26
                    )
                    """
                    var insertStmt: OpaquePointer?
                    guard sqlite3_prepare_v2(db, insertSQL, -1, &insertStmt, nil) == SQLITE_OK,
                          let insertStmt else {
                        throw sqliteError(db: db, context: "prepare computer-vision observation insert")
                    }
                    sqlite3_bind_text(insertStmt, 1, observationID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 2, LocalObservationModality.computer_vision.rawValue, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 3, intent.rawValue, -1, SQLITE_TRANSIENT)
                    bindOptionalText(canonicalValue, stmt: insertStmt, index: 4)
                    sqlite3_bind_double(insertStmt, 5, coordinate.latitude)
                    sqlite3_bind_double(insertStmt, 6, coordinate.longitude)
                    sqlite3_bind_double(insertStmt, 7, activation.headingDegrees)
                    sqlite3_bind_text(insertStmt, 8, roadIDsJSON, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 9, effectiveAtUTC, -1, SQLITE_TRANSIENT)
                    bindOptionalDouble(event.finalCalibratedConfidence, stmt: insertStmt, index: 10)
                    sqlite3_bind_text(insertStmt, 11, sourceVersion, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 12, decision.initialState.rawValue, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 13, ensureDevicePseudoID(), -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 14, consumedAtUTC, -1, SQLITE_TRANSIENT)
                    bindOptionalInt(decision.oldSpeedKmh, stmt: insertStmt, index: 15)
                    bindOptionalInt(canonicalValue.flatMap(Int.init), stmt: insertStmt, index: 16)
                    sqlite3_bind_text(insertStmt, 17, evidenceJSON, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 18, primaryWayID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 19, effectiveAtUTC, -1, SQLITE_TRANSIENT)
                    bindOptionalText(decision.operation?.rawValue, stmt: insertStmt, index: 20)
                    sqlite3_bind_text(insertStmt, 21, decision.directionScope.rawValue, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(insertStmt, 22, decision.applicability.rawValue, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_int(insertStmt, 23, decision.runtimeApplicable ? 1 : 0)
                    sqlite3_bind_text(insertStmt, 24, event.finalizedEventID, -1, SQLITE_TRANSIENT)
                    bindOptionalText(exportDisposition?.rawValue, stmt: insertStmt, index: 25)
                    bindOptionalText(decision.exportTagKey, stmt: insertStmt, index: 26)
                    guard sqlite3_step(insertStmt) == SQLITE_DONE else {
                        sqlite3_finalize(insertStmt)
                        throw sqliteError(db: db, context: "execute computer-vision observation insert")
                    }
                    sqlite3_finalize(insertStmt)

                    staleExportBatchIDs += try staleOverlappingPendingExportBatches(
                        db: db,
                        wayID: primaryWayID,
                        direction: decision.directionScope,
                        incomingObservationID: observationID
                    )

                    if decision.runtimeApplicable,
                       decision.operation == .setMaxspeed,
                       decision.applicability == .permanent,
                       canonicalValue != nil {
                        staleExportBatchIDs += try supersedeOlderTypedCorrections(
                            db: db,
                            wayID: primaryWayID,
                            direction: decision.directionScope,
                            effectiveAtUTC: effectiveAtUTC,
                            keepingObservationID: observationID
                        )
                    }

                    try insertComputerVisionPassageEvidence(
                        db: db,
                        finalizedEventID: event.finalizedEventID,
                        evidenceJSON: evidenceJSON,
                        equivalentObservationID: nil,
                        consumedAtUTC: consumedAtUTC
                    )

                    try insertComputerVisionReceipt(
                        db: db,
                        finalizedEventID: event.finalizedEventID,
                        decision: .inserted,
                        observationID: observationID,
                        consumedAtUTC: consumedAtUTC
                    )
                    guard let observation = try fetchObservation(
                        db: db,
                        observationID: observationID
                    ) else {
                        throw ConsumerAppError.sqlite("Inserted computer-vision observation could not be decoded")
                    }
                    guard sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK else {
                        throw sqliteError(db: db, context: "commit computer-vision observation")
                    }
                    return LocalObservationComputerVisionRecordResult(
                        decision: .inserted,
                        observation: observation
                    )
                } catch {
                    sqlite3_exec(db, "ROLLBACK", nil, nil, nil)
                    throw error
                }
            }
        }
        quarantineStaleExportBatches(staleExportBatchIDs)
        return consumed ?? LocalObservationComputerVisionRecordResult(
            decision: .staleGeneration,
            observation: nil
        )
    }

    func fetchLatestRuntimeApplicableCorrection(
        wayID: String,
        direction: LocalObservationDirectionScope
    ) throws -> LocalObservation? {
        guard Self.isPositiveWayID(wayID) else { return nil }
        return try withDatabase { db in
            try latestValidatedRuntimeCorrection(
                db: db,
                wayID: wayID,
                direction: direction
            )?.observation
        }
    }

    private func computerVisionReceipt(
        db: OpaquePointer,
        finalizedEventID: String
    ) throws -> LocalObservationComputerVisionRecordResult? {
        let sql = """
        SELECT decision, observation_id
        FROM computer_vision_event_receipts
        WHERE finalized_event_id = ?1
        LIMIT 1
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare computer-vision receipt lookup")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, finalizedEventID, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_ROW,
              let raw = cStringOptional(sqlite3_column_text(stmt, 0)),
              let decision = LocalObservationComputerVisionReceiptDecision(rawValue: raw) else {
            return nil
        }
        let observationID = cStringOptional(sqlite3_column_text(stmt, 1))
        let observation = try observationID.flatMap {
            try fetchObservation(db: db, observationID: $0)
        }
        return LocalObservationComputerVisionRecordResult(
            decision: decision,
            observation: observation
        )
    }

    private func insertComputerVisionReceipt(
        db: OpaquePointer,
        finalizedEventID: String,
        decision: LocalObservationComputerVisionReceiptDecision,
        observationID: String?,
        consumedAtUTC: String
    ) throws {
        let sql = """
        INSERT INTO computer_vision_event_receipts (
          finalized_event_id, decision, observation_id, consumed_at_utc
        ) VALUES (?1, ?2, ?3, ?4)
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare computer-vision receipt insert")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, finalizedEventID, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, decision.rawValue, -1, SQLITE_TRANSIENT)
        bindOptionalText(observationID, stmt: stmt, index: 3)
        sqlite3_bind_text(stmt, 4, consumedAtUTC, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_DONE else {
            throw sqliteError(db: db, context: "execute computer-vision receipt insert")
        }
    }

    private func insertComputerVisionPassageEvidence(
        db: OpaquePointer,
        finalizedEventID: String,
        evidenceJSON: String,
        equivalentObservationID: String?,
        consumedAtUTC: String
    ) throws {
        let sql = """
        INSERT INTO computer_vision_passage_events (
          finalized_event_id, evidence_json, equivalent_observation_id, consumed_at_utc
        ) VALUES (?1, ?2, ?3, ?4)
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare computer-vision passage evidence")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, finalizedEventID, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, evidenceJSON, -1, SQLITE_TRANSIENT)
        bindOptionalText(equivalentObservationID, stmt: stmt, index: 3)
        sqlite3_bind_text(stmt, 4, consumedAtUTC, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_DONE else {
            throw sqliteError(db: db, context: "insert computer-vision passage evidence")
        }
    }

    private func newestRuntimeCorrection(
        db: OpaquePointer,
        wayID: String,
        direction: LocalObservationDirectionScope
    ) throws -> (value: String, observationID: String)? {
        guard let correction = try latestValidatedRuntimeCorrection(
            db: db,
            wayID: wayID,
            direction: direction
        ) else {
            return nil
        }
        return (correction.canonicalValue, correction.observation.id)
    }

    /// Reads candidates newest-first and deliberately validates each decoded
    /// row. A future enum or a malformed newer row must not hide an older safe
    /// correction, and SQL predicates alone are not an authorization boundary.
    private func latestValidatedRuntimeCorrection(
        db: OpaquePointer,
        wayID: String,
        direction: LocalObservationDirectionScope
    ) throws -> (observation: LocalObservation, canonicalValue: String)? {
        let acceptedDirections: [LocalObservationDirectionScope]
        switch direction {
        case .forward, .backward:
            acceptedDirections = [direction, .wayWide]
        case .wayWide, .unknown:
            acceptedDirections = [.wayWide]
        }
        let placeholders = acceptedDirections.indices
            .map { "?\($0 + 3)" }
            .joined(separator: ",")
        let sql = """
        SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
               city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
               device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
               evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
               runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
        FROM observations
        WHERE primary_way_id = ?1
          AND direction_scope IN (\(placeholders))
          AND runtime_applicable = 1
        ORDER BY effective_at_utc DESC,
                 CASE WHEN direction_scope = ?2 THEN 0 ELSE 1 END,
                 observation_id DESC
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare validated runtime correction lookup")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, wayID, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, direction.rawValue, -1, SQLITE_TRANSIENT)
        for (offset, accepted) in acceptedDirections.enumerated() {
            sqlite3_bind_text(stmt, Int32(3 + offset), accepted.rawValue, -1, SQLITE_TRANSIENT)
        }

        while true {
            switch sqlite3_step(stmt) {
            case SQLITE_ROW:
                guard let observation = decodeObservationRow(stmt),
                      let canonicalValue = Self.validatedRuntimeCorrectionValue(
                        observation,
                        expectedWayID: wayID,
                        acceptedDirections: acceptedDirections
                      ) else {
                    continue
                }
                return (observation, canonicalValue)
            case SQLITE_DONE:
                return nil
            default:
                throw sqliteError(db: db, context: "execute validated runtime correction lookup")
            }
        }
    }

    /// A newer correction wins for the same typed target. Older approved rows
    /// remain in the audit trail but cannot be exported or selected at runtime.
    private func supersedeOlderTypedCorrections(
        db: OpaquePointer,
        wayID: String,
        direction: LocalObservationDirectionScope,
        effectiveAtUTC: String,
        keepingObservationID: String
    ) throws -> [String] {
        let staleBatchIDs = try staleOverlappingPendingExportBatches(
            db: db,
            wayID: wayID,
            direction: direction,
            incomingObservationID: keepingObservationID
        )
        // A way-wide correction overlaps both directional tags, while a
        // directional correction overlaps the way-wide fallback for that
        // direction. Unknown-direction evidence is never runtime-applicable,
        // but an older unknown typed row must not remain export-eligible once
        // a newer applicable correction resolves its scope.
        let overlappingDirections: [LocalObservationDirectionScope]
        switch direction {
        case .wayWide, .unknown:
            overlappingDirections = [.wayWide, .forward, .backward, .unknown]
        case .forward:
            overlappingDirections = [.wayWide, .forward, .unknown]
        case .backward:
            overlappingDirections = [.wayWide, .backward, .unknown]
        }
        let directionPlaceholders = overlappingDirections.indices
            .map { "?\($0 + 2)" }
            .joined(separator: ",")
        let keepingIndex = Int32(overlappingDirections.count + 2)
        let effectiveAtIndex = keepingIndex + 1
        let sql = """
        UPDATE observations
           SET export_disposition = 'superseded'
         WHERE primary_way_id = ?1
           AND direction_scope IN (\(directionPlaceholders))
           AND operation = 'set_maxspeed'
           AND applicability = 'permanent'
           AND observation_id != ?\(keepingIndex)
           AND COALESCE(effective_at_utc, captured_at_utc) <= ?\(effectiveAtIndex)
           AND COALESCE(export_disposition, 'eligible') != 'exported'
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare typed correction supersession")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, wayID, -1, SQLITE_TRANSIENT)
        for (offset, overlappingDirection) in overlappingDirections.enumerated() {
            sqlite3_bind_text(
                stmt,
                Int32(offset + 2),
                overlappingDirection.rawValue,
                -1,
                SQLITE_TRANSIENT
            )
        }
        sqlite3_bind_text(stmt, keepingIndex, keepingObservationID, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, effectiveAtIndex, effectiveAtUTC, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_DONE else {
            throw sqliteError(db: db, context: "execute typed correction supersession")
        }
        return staleBatchIDs
    }

    private func staleOverlappingPendingExportBatches(
        db: OpaquePointer,
        wayID: String,
        direction: LocalObservationDirectionScope,
        incomingObservationID: String
    ) throws -> [String] {
        let overlappingTagKeys: [String]
        switch direction {
        case .wayWide:
            overlappingTagKeys = ["maxspeed", "maxspeed:forward", "maxspeed:backward"]
        case .forward:
            overlappingTagKeys = ["maxspeed", "maxspeed:forward"]
        case .backward:
            overlappingTagKeys = ["maxspeed", "maxspeed:backward"]
        case .unknown:
            overlappingTagKeys = ["maxspeed", "maxspeed:forward", "maxspeed:backward"]
        }
        var staleBatchIDs: [String] = []
        if !overlappingTagKeys.isEmpty {
            let targetKeys = overlappingTagKeys.map { "way:\(wayID)|tag:\($0)" }
            let placeholders = targetKeys.indices.map { "?\($0 + 1)" }.joined(separator: ",")
            let incomingIndex = Int32(targetKeys.count + 1)
            var selectStmt: OpaquePointer?
            let selectSQL = """
            SELECT DISTINCT m.batch_id
              FROM local_observation_export_members m
              JOIN observations frozen ON frozen.observation_id = m.observation_id
              JOIN observations incoming ON incoming.observation_id = ?\(incomingIndex)
             WHERE m.status = 'pending'
               AND m.target_key IN (\(placeholders))
               AND (
                    COALESCE(frozen.effective_at_utc, frozen.captured_at_utc)
                        < COALESCE(incoming.effective_at_utc, incoming.captured_at_utc)
                    OR (
                        COALESCE(frozen.effective_at_utc, frozen.captured_at_utc)
                            = COALESCE(incoming.effective_at_utc, incoming.captured_at_utc)
                        AND frozen.rowid < incoming.rowid
                    )
               )
             ORDER BY m.batch_id
            """
            guard sqlite3_prepare_v2(db, selectSQL, -1, &selectStmt, nil) == SQLITE_OK,
                  let selectStmt else {
                throw sqliteError(db: db, context: "prepare overlapping OSC batch lookup")
            }
            for (index, targetKey) in targetKeys.enumerated() {
                sqlite3_bind_text(selectStmt, Int32(index + 1), targetKey, -1, SQLITE_TRANSIENT)
            }
            sqlite3_bind_text(
                selectStmt,
                incomingIndex,
                incomingObservationID,
                -1,
                SQLITE_TRANSIENT
            )
            while sqlite3_step(selectStmt) == SQLITE_ROW {
                if let batchID = cStringOptional(sqlite3_column_text(selectStmt, 0)) {
                    staleBatchIDs.append(batchID)
                }
            }
            sqlite3_finalize(selectStmt)
            for batchID in staleBatchIDs {
                try markExportBatchStaleInDatabase(db: db, batchID: batchID)
            }
        }

        return staleBatchIDs
    }

    private func fetchObservation(
        db: OpaquePointer,
        observationID: String
    ) throws -> LocalObservation? {
        let sql = """
        SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
               city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
               device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
               evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
               runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
        FROM observations
        WHERE observation_id = ?1
        LIMIT 1
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare observation transaction fetch")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_ROW else { return nil }
        return decodeObservationRow(stmt)
    }

    func fetchObservations(states: [LocalObservationState]? = nil, limit: Int = 50) throws -> [LocalObservation] {
        try withDatabase { db in
            var sql = """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                   evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
                   runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
            FROM observations
            """
            if let states, !states.isEmpty {
                let placeholders = Array(repeating: "?", count: states.count).joined(separator: ",")
                sql += " WHERE state IN (\(placeholders))"
            }
            sql += " ORDER BY captured_at_utc DESC LIMIT ?"

            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation fetch")
            }
            defer { sqlite3_finalize(stmt) }

            var bindIndex: Int32 = 1
            if let states, !states.isEmpty {
                for state in states {
                    sqlite3_bind_text(stmt, bindIndex, state.rawValue, -1, SQLITE_TRANSIENT)
                    bindIndex += 1
                }
            }
            sqlite3_bind_int64(stmt, bindIndex, Int64(max(1, limit)))

            var out: [LocalObservation] = []
            while sqlite3_step(stmt) == SQLITE_ROW {
                if let observation = decodeObservationRow(stmt) {
                    out.append(observation)
                }
            }
            return out
        }
    }

    func deleteObservation(observationID: String) throws {
        try withDatabase { db in
            guard try !hasPendingExportMember(db: db, observationID: observationID) else {
                throw ConsumerAppError.io("Observation is frozen in a pending OSC export")
            }
            let sql = "DELETE FROM observations WHERE observation_id = ?1"
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation delete")
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(stmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "execute observation delete")
            }
        }
    }

    func deleteAllObservations() throws -> Int {
        try withDatabase { db in
            var pendingStmt: OpaquePointer?
            guard sqlite3_prepare_v2(
                db,
                "SELECT 1 FROM local_observation_export_members WHERE status = 'pending' LIMIT 1",
                -1,
                &pendingStmt,
                nil
            ) == SQLITE_OK, let pendingStmt else {
                throw sqliteError(db: db, context: "prepare pending OSC deletion guard")
            }
            let hasPending = sqlite3_step(pendingStmt) == SQLITE_ROW
            sqlite3_finalize(pendingStmt)
            guard !hasPending else {
                throw ConsumerAppError.io("Cannot delete observations while an OSC export is pending")
            }
            var countStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM observations", -1, &countStmt, nil) == SQLITE_OK,
                  let countStmt else {
                throw sqliteError(db: db, context: "prepare observation count")
            }
            defer { sqlite3_finalize(countStmt) }
            let existingCount: Int
            if sqlite3_step(countStmt) == SQLITE_ROW {
                existingCount = Int(sqlite3_column_int64(countStmt, 0))
            } else {
                existingCount = 0
            }

            guard sqlite3_exec(db, "DELETE FROM observations", nil, nil, nil) == SQLITE_OK else {
                throw sqliteError(db: db, context: "delete all observations")
            }
            return existingCount
        }
    }

    func reviewAndApproveProposal(observationID: String) throws -> LocalObservation {
        try updateObservationState(observationID: observationID, newState: .approvedForExport)
    }

    func discardObservation(observationID: String) throws -> LocalObservation {
        try updateObservationState(observationID: observationID, newState: .discarded)
    }

    func buildOsmProposal(observationID: String) throws -> LocalObservationProposal {
        let observation = try fetchObservation(observationID: observationID)
        let target = try validatedExportTarget(observation)

        let xml = Self.makeOsmChangeXML(
            wayID: target.wayID,
            tagKey: target.tagKey,
            maxspeedValue: target.value
        )
        let summary = observation.confidenceCalibrated.map { String(format: "confidence=%.2f", $0) } ?? "confidence=n/a"
        return LocalObservationProposal(
            observationID: observationID,
            targetObjects: [.init(type: "way", id: target.wayID)],
            oscXML: xml,
            confidenceSummary: summary
        )
    }

    func exportProposalAsOscPackage(observationID: String) throws -> LocalObservationExportResult {
        let reservation = try reserveExportBatch(observationID: observationID)
        guard reservation.members.count == 1,
              reservation.members[0].observationID == observationID else {
            throw ConsumerAppError.io("Reserved export does not match the requested observation")
        }
        try materializeAndFinalizeExport(reservation)

        return LocalObservationExportResult(
            exportID: reservation.batchID,
            packageDirectory: reservation.packageDirectory,
            changesFile: reservation.packageDirectory.appendingPathComponent("changes.osc"),
            reviewFile: reservation.packageDirectory.appendingPathComponent("review.json"),
            readmeFile: reservation.packageDirectory.appendingPathComponent("README.txt")
        )
    }

    func exportAllLocalObservationsAsOsc() throws -> LocalObservationBulkExportResult {
        let reservation = try reserveExportBatch(observationID: nil)
        try materializeAndFinalizeExport(reservation)

        return LocalObservationBulkExportResult(
            exportID: reservation.batchID,
            packageDirectory: reservation.packageDirectory,
            changesFile: reservation.packageDirectory.appendingPathComponent("changes.osc"),
            includedCount: reservation.members.count
        )
    }

#if DEBUG
    /// Narrow test seam around the durable reservation boundary. Production
    /// callers continue to use the atomic public export methods above.
    struct ExportReservationTestSnapshot: Sendable {
        let batchID: String
        let packageDirectory: URL
        let memberObservationIDs: [String]
    }

    func testReserveExportBatch(observationID: String?) throws -> ExportReservationTestSnapshot {
        let reservation = try reserveExportBatch(observationID: observationID)
        return ExportReservationTestSnapshot(
            batchID: reservation.batchID,
            packageDirectory: reservation.packageDirectory,
            memberObservationIDs: reservation.members.map(\.observationID)
        )
    }

    func testFinalizeReservedExportBatch(batchID: String) throws {
        let reservation = try withDatabase { db in
            try loadExportReservation(db: db, batchID: batchID)
        }
        guard let reservation else {
            throw ConsumerAppError.io("OSC test reservation not found")
        }
        try materializeAndFinalizeExport(reservation)
    }

    func testExportBatchStatus(batchID: String) throws -> String? {
        try withDatabase { db in
            try exportBatchStatus(db: db, batchID: batchID)
        }
    }
#endif

    /// Freezes the complete, reviewed typed target set before any package file
    /// is written. A pending reservation is durable and deterministic, so a
    /// launch after a crash resumes the same batch/path instead of creating a
    /// second OSC package.
    private func reserveExportBatch(observationID: String?) throws -> ExportReservation {
        try withDatabase { db in
            try beginImmediate(db, context: "begin OSC export reservation")
            do {
                try staleInvalidPendingExportBatches(db: db)
                if let existing = try resumableExportReservation(
                    db: db,
                    observationID: observationID
                ) {
                    try commit(db, context: "commit resumed OSC export reservation")
                    return existing
                }

                let observations = try approvedExportObservations(
                    db: db,
                    observationID: observationID
                )
                let allowsManualLocalOnly = observationID == nil
                var newestByTarget: [String: FrozenExportMember] = [:]
                for observation in observations {
                    let target = try validatedExportTarget(
                        observation,
                        allowManualLocalOnly: allowsManualLocalOnly
                    )
                    guard try isNewestTypedTarget(db: db, observation: observation) else {
                        continue
                    }
                    guard let direction = observation.directionScope else { continue }
                    let approvalRevision = observation.approvalRevision
                        ?? Self.approvalRevision(
                            wayID: target.wayID,
                            tagKey: target.tagKey,
                            value: target.value,
                            direction: direction
                        )
                    let member = FrozenExportMember(
                        observationID: observation.id,
                        wayID: target.wayID,
                        tagKey: target.tagKey,
                        value: target.value,
                        directionScope: direction,
                        approvalRevision: approvalRevision,
                        effectiveAtUTC: observation.effectiveAtUTC ?? observation.capturedAtUTC,
                        capturedAtUTC: observation.capturedAtUTC,
                        sourceVersion: observation.sourceVersion,
                        streetContext: observation.streetContext,
                        cityContext: observation.cityContext,
                        confidenceCalibrated: observation.confidenceCalibrated
                    )
                    let key = member.targetKey
                    if let previous = newestByTarget[key] {
                        if (member.effectiveAtUTC, member.observationID)
                            > (previous.effectiveAtUTC, previous.observationID) {
                            newestByTarget[key] = member
                        }
                    } else {
                        newestByTarget[key] = member
                    }
                }
                let members = newestByTarget.values.sorted {
                    ($0.targetKey, $0.observationID) < ($1.targetKey, $1.observationID)
                }
                guard !members.isEmpty else {
                    throw ConsumerAppError.io(
                        observationID == nil
                            ? "Keine freigegebenen, aktuellen maxspeed-Korrekturen vorhanden."
                            : "Observation is not the newest approved export target"
                    )
                }
                if let observationID,
                   members.count != 1 || members[0].observationID != observationID {
                    throw ConsumerAppError.io("Observation is not eligible for OSC export")
                }

                let identity = members.map {
                    [
                        $0.observationID,
                        $0.targetKey,
                        $0.value,
                        $0.directionScope.rawValue,
                        $0.approvalRevision,
                        $0.effectiveAtUTC,
                    ].joined(separator: "|")
                }.joined(separator: "\n")
                let batchID = SHA256.hash(data: Data(identity.utf8))
                    .map { String(format: "%02x", $0) }
                    .joined()
                if let existing = try loadExportReservation(db: db, batchID: batchID) {
                    try commit(db, context: "commit deterministic OSC export reservation reuse")
                    return existing
                }
                let createdAtUTC = Self.isoFormatter.string(from: nowProvider())
                let packageDirectory = try exportsDirectory().appendingPathComponent(
                    "osm-export-\(String(batchID.prefix(20)))",
                    isDirectory: true
                )
                let encoder = JSONEncoder()
                encoder.outputFormatting = [.sortedKeys]
                let payloadJSON = String(
                    data: try encoder.encode(members),
                    encoding: .utf8
                ) ?? "[]"

                let insertBatchSQL = """
                INSERT INTO local_observation_export_batches (
                  batch_id, created_at_utc, status, package_path, package_sha256,
                  payload_json, finalized_at_utc
                ) VALUES (?1, ?2, 'pending', ?3, NULL, ?4, NULL)
                """
                var batchStmt: OpaquePointer?
                guard sqlite3_prepare_v2(db, insertBatchSQL, -1, &batchStmt, nil) == SQLITE_OK,
                      let batchStmt else {
                    throw sqliteError(db: db, context: "prepare OSC export batch reservation")
                }
                sqlite3_bind_text(batchStmt, 1, batchID, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(batchStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(batchStmt, 3, packageDirectory.path, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(batchStmt, 4, payloadJSON, -1, SQLITE_TRANSIENT)
                let batchStep = sqlite3_step(batchStmt)
                sqlite3_finalize(batchStmt)
                guard batchStep == SQLITE_DONE else {
                    throw sqliteError(db: db, context: "reserve OSC export batch")
                }

                let insertMemberSQL = """
                INSERT INTO local_observation_export_members (
                  batch_id, observation_id, target_key, approval_revision, status
                ) VALUES (?1, ?2, ?3, ?4, 'pending')
                """
                for member in members {
                    var memberStmt: OpaquePointer?
                    guard sqlite3_prepare_v2(db, insertMemberSQL, -1, &memberStmt, nil) == SQLITE_OK,
                          let memberStmt else {
                        throw sqliteError(db: db, context: "prepare OSC export member reservation")
                    }
                    sqlite3_bind_text(memberStmt, 1, batchID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(memberStmt, 2, member.observationID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(memberStmt, 3, member.targetKey, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(memberStmt, 4, member.approvalRevision, -1, SQLITE_TRANSIENT)
                    let memberStep = sqlite3_step(memberStmt)
                    sqlite3_finalize(memberStmt)
                    guard memberStep == SQLITE_DONE else {
                        throw sqliteError(db: db, context: "reserve OSC export member")
                    }
                }
                let reservation = ExportReservation(
                    batchID: batchID,
                    createdAtUTC: createdAtUTC,
                    packageDirectory: packageDirectory,
                    status: "pending",
                    packageSHA256: nil,
                    members: members
                )
                try commit(db, context: "commit OSC export reservation")
                return reservation
            } catch {
                sqlite3_exec(db, "ROLLBACK", nil, nil, nil)
                throw error
            }
        }
    }

    private func materializeAndFinalizeExport(_ reservation: ExportReservation) throws {
        let oscData = Data(Self.makeFrozenOsmChangeXML(members: reservation.members).utf8)
        let oscSHA = SHA256.hash(data: oscData).map { String(format: "%02x", $0) }.joined()
        let finalDirectory = reservation.packageDirectory
        let changesFile = finalDirectory.appendingPathComponent("changes.osc")
        let reviewFile = finalDirectory.appendingPathComponent("review.json")
        let readmeFile = finalDirectory.appendingPathComponent("README.txt")

        if reservation.status == "finalized",
           fileManager.fileExists(atPath: changesFile.path),
           try SHA256.hash(data: Data(contentsOf: changesFile))
            .map({ String(format: "%02x", $0) }).joined() == oscSHA {
            return
        }

        try revalidatePendingReservation(reservation, packageSHA256: oscSHA)

        let temporaryDirectory = try exportsDirectory().appendingPathComponent(
            ".\(reservation.batchID).tmp",
            isDirectory: true
        )
        if fileManager.fileExists(atPath: temporaryDirectory.path) {
            try fileManager.removeItem(at: temporaryDirectory)
        }
        try fileManager.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
        do {
            try oscData.write(
                to: temporaryDirectory.appendingPathComponent("changes.osc"),
                options: .atomic
            )
            try makeFrozenReviewJSON(reservation).write(
                to: temporaryDirectory.appendingPathComponent("review.json"),
                options: .atomic
            )
            try Data(Self.readmeTemplate.utf8).write(
                to: temporaryDirectory.appendingPathComponent("README.txt"),
                options: .atomic
            )

            // Revalidate after all bytes are frozen but before publishing the
            // directory. If a newer target won, this batch becomes stale and
            // no final OSC path is exposed.
            try revalidatePendingReservation(reservation, packageSHA256: oscSHA)
            if fileManager.fileExists(atPath: finalDirectory.path) {
                let existing = finalDirectory.appendingPathComponent("changes.osc")
                guard fileManager.fileExists(atPath: existing.path),
                      SHA256.hash(data: try Data(contentsOf: existing))
                        .map({ String(format: "%02x", $0) }).joined() == oscSHA else {
                    throw ConsumerAppError.io("Existing deterministic OSC package does not match its reservation")
                }
                try fileManager.removeItem(at: temporaryDirectory)
            } else {
                try fileManager.moveItem(at: temporaryDirectory, to: finalDirectory)
            }
            try finalizeExportReservation(reservation, packageSHA256: oscSHA)
        } catch {
            try? fileManager.removeItem(at: temporaryDirectory)
            throw error
        }

        guard fileManager.fileExists(atPath: changesFile.path),
              fileManager.fileExists(atPath: reviewFile.path),
              fileManager.fileExists(atPath: readmeFile.path) else {
            throw ConsumerAppError.io("Finalized OSC package is incomplete")
        }
    }

    private func revalidatePendingReservation(
        _ reservation: ExportReservation,
        packageSHA256: String
    ) throws {
        try withDatabase { db in
            try beginImmediate(db, context: "begin OSC reservation validation")
            do {
                guard try exportReservationIsCurrent(db: db, reservation: reservation) else {
                    try markExportBatchStale(db: db, batchID: reservation.batchID)
                    try commit(db, context: "commit stale OSC reservation")
                    throw ConsumerAppError.io("OSC export reservation became stale and must be reviewed again")
                }
                let sql = """
                UPDATE local_observation_export_batches
                   SET package_sha256 = ?1
                 WHERE batch_id = ?2 AND status = 'pending'
                """
                var stmt: OpaquePointer?
                guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                    throw sqliteError(db: db, context: "prepare OSC reservation hash")
                }
                sqlite3_bind_text(stmt, 1, packageSHA256, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 2, reservation.batchID, -1, SQLITE_TRANSIENT)
                let step = sqlite3_step(stmt)
                sqlite3_finalize(stmt)
                guard step == SQLITE_DONE else {
                    throw sqliteError(db: db, context: "store OSC reservation hash")
                }
                try commit(db, context: "commit OSC reservation validation")
            } catch {
                sqlite3_exec(db, "ROLLBACK", nil, nil, nil)
                throw error
            }
        }
    }

    private func finalizeExportReservation(
        _ reservation: ExportReservation,
        packageSHA256: String
    ) throws {
        try withDatabase { db in
            try beginImmediate(db, context: "begin OSC export finalization")
            do {
                if try exportBatchStatus(db: db, batchID: reservation.batchID) == "finalized" {
                    try commit(db, context: "commit already finalized OSC export")
                    return
                }
                guard try exportReservationIsCurrent(db: db, reservation: reservation) else {
                    try markExportBatchStale(db: db, batchID: reservation.batchID)
                    try commit(db, context: "commit stale OSC export finalization")
                    throw ConsumerAppError.io("OSC export changed before finalization")
                }

                let observationIDs = reservation.members.map(\.observationID)
                let observationIDsJSON = String(
                    data: try JSONEncoder().encode(observationIDs),
                    encoding: .utf8
                ) ?? "[]"
                let insertExportSQL = """
                INSERT OR IGNORE INTO exports (
                  export_id, created_at_utc, package_path, package_sha256,
                  observation_ids, returned_changeset_id
                ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)
                """
                var exportStmt: OpaquePointer?
                guard sqlite3_prepare_v2(db, insertExportSQL, -1, &exportStmt, nil) == SQLITE_OK,
                      let exportStmt else {
                    throw sqliteError(db: db, context: "prepare frozen OSC export insert")
                }
                sqlite3_bind_text(exportStmt, 1, reservation.batchID, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(exportStmt, 2, reservation.createdAtUTC, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(exportStmt, 3, reservation.packageDirectory.path, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(exportStmt, 4, packageSHA256, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(exportStmt, 5, observationIDsJSON, -1, SQLITE_TRANSIENT)
                let exportStep = sqlite3_step(exportStmt)
                sqlite3_finalize(exportStmt)
                guard exportStep == SQLITE_DONE else {
                    throw sqliteError(db: db, context: "insert frozen OSC export")
                }

                let finalizedAtUTC = Self.isoFormatter.string(from: nowProvider())
                let updateObservationSQL = """
                UPDATE observations
                   SET state = 'exported_osc', updated_at_utc = ?1,
                       export_id = ?2, export_disposition = 'exported'
                 WHERE observation_id = ?3
                   AND ((state = 'approved_for_export' AND approval_revision = ?4)
                        OR (state IN ('local_only', 'needs_review')
                            AND modality != 'computer_vision'
                            AND approval_revision IS NULL))
                   AND export_disposition = 'eligible'
                   AND primary_way_id = ?5
                   AND export_tag_key = ?6
                   AND LOWER(TRIM(value)) = ?7
                """
                for member in reservation.members {
                    var updateStmt: OpaquePointer?
                    guard sqlite3_prepare_v2(db, updateObservationSQL, -1, &updateStmt, nil) == SQLITE_OK,
                          let updateStmt else {
                        throw sqliteError(db: db, context: "prepare guarded OSC member finalization")
                    }
                    sqlite3_bind_text(updateStmt, 1, finalizedAtUTC, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(updateStmt, 2, reservation.batchID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(updateStmt, 3, member.observationID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(updateStmt, 4, member.approvalRevision, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(updateStmt, 5, member.wayID, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(updateStmt, 6, member.tagKey, -1, SQLITE_TRANSIENT)
                    sqlite3_bind_text(updateStmt, 7, member.value, -1, SQLITE_TRANSIENT)
                    let updateStep = sqlite3_step(updateStmt)
                    let changed = sqlite3_changes(db)
                    sqlite3_finalize(updateStmt)
                    guard updateStep == SQLITE_DONE, changed == 1 else {
                        throw ConsumerAppError.io("OSC member changed during guarded finalization")
                    }
                }

                let finalizeSQL = """
                UPDATE local_observation_export_batches
                   SET status = 'finalized', package_sha256 = ?1, finalized_at_utc = ?2
                 WHERE batch_id = ?3 AND status = 'pending';
                UPDATE local_observation_export_members
                   SET status = 'finalized'
                 WHERE batch_id = ?3 AND status = 'pending';
                """
                var finalizeError: UnsafeMutablePointer<Int8>?
                let quotedSHA = packageSHA256.replacingOccurrences(of: "'", with: "''")
                let quotedTime = finalizedAtUTC.replacingOccurrences(of: "'", with: "''")
                let quotedBatch = reservation.batchID.replacingOccurrences(of: "'", with: "''")
                let boundFinalizeSQL = finalizeSQL
                    .replacingOccurrences(of: "?1", with: "'\(quotedSHA)'")
                    .replacingOccurrences(of: "?2", with: "'\(quotedTime)'")
                    .replacingOccurrences(of: "?3", with: "'\(quotedBatch)'")
                guard sqlite3_exec(db, boundFinalizeSQL, nil, nil, &finalizeError) == SQLITE_OK else {
                    let detail = finalizeError.map { String(cString: $0) } ?? "unknown"
                    sqlite3_free(finalizeError)
                    throw ConsumerAppError.sqlite("finalize OSC reservation: \(detail)")
                }
                try commit(db, context: "commit OSC export finalization")
            } catch {
                sqlite3_exec(db, "ROLLBACK", nil, nil, nil)
                throw error
            }
        }
    }

    private func approvedExportObservations(
        db: OpaquePointer,
        observationID: String?
    ) throws -> [LocalObservation] {
        var sql = """
        SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
               city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
               device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
               evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
               runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
        FROM observations
        WHERE (state = 'approved_for_export'
               OR (?1 IS NULL
                   AND state IN ('local_only', 'needs_review')
                   AND modality != 'computer_vision'))
        """
        if observationID != nil { sql += " AND observation_id = ?2" }
        sql += " ORDER BY COALESCE(effective_at_utc, captured_at_utc), observation_id"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare approved OSC members")
        }
        defer { sqlite3_finalize(stmt) }
        bindOptionalText(observationID, stmt: stmt, index: 1)
        if let observationID { sqlite3_bind_text(stmt, 2, observationID, -1, SQLITE_TRANSIENT) }
        var result: [LocalObservation] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let observation = decodeObservationRow(stmt) { result.append(observation) }
        }
        return result
    }

    private func resumableExportReservation(
        db: OpaquePointer,
        observationID: String?
    ) throws -> ExportReservation? {
        let sql: String
        if observationID != nil {
            sql = """
            SELECT b.batch_id
              FROM local_observation_export_batches b
              JOIN local_observation_export_members m ON m.batch_id = b.batch_id
             WHERE m.observation_id = ?1 AND b.status IN ('pending', 'finalized')
             ORDER BY CASE b.status WHEN 'pending' THEN 0 ELSE 1 END, b.created_at_utc DESC
             LIMIT 1
            """
        } else {
            sql = """
            SELECT batch_id
              FROM local_observation_export_batches
             WHERE status = 'pending'
             ORDER BY created_at_utc, batch_id
             LIMIT 1
            """
        }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare resumable OSC reservation")
        }
        defer { sqlite3_finalize(stmt) }
        if let observationID {
            sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
        }
        guard sqlite3_step(stmt) == SQLITE_ROW,
              let batchID = cStringOptional(sqlite3_column_text(stmt, 0)) else { return nil }
        return try loadExportReservation(db: db, batchID: batchID)
    }

    private func loadExportReservation(
        db: OpaquePointer,
        batchID: String
    ) throws -> ExportReservation? {
        let sql = """
        SELECT created_at_utc, status, package_path, package_sha256, payload_json
          FROM local_observation_export_batches
         WHERE batch_id = ?1
         LIMIT 1
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare OSC reservation load")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, batchID, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_ROW,
              let createdAtUTC = cStringOptional(sqlite3_column_text(stmt, 0)),
              let status = cStringOptional(sqlite3_column_text(stmt, 1)),
              ["pending", "finalized", "stale"].contains(status),
              let packagePath = cStringOptional(sqlite3_column_text(stmt, 2)),
              let payload = cStringOptional(sqlite3_column_text(stmt, 4))?.data(using: .utf8) else {
            return nil
        }
        let members = try JSONDecoder().decode([FrozenExportMember].self, from: payload)
        guard !members.isEmpty else { return nil }
        let expectedDirectory = try exportsDirectory().appendingPathComponent(
            "osm-export-\(String(batchID.prefix(20)))",
            isDirectory: true
        ).standardizedFileURL
        guard URL(fileURLWithPath: packagePath, isDirectory: true).standardizedFileURL.path
                == expectedDirectory.path else {
            throw ConsumerAppError.io("OSC reservation package path is invalid")
        }
        return ExportReservation(
            batchID: batchID,
            createdAtUTC: createdAtUTC,
            packageDirectory: expectedDirectory,
            status: status,
            packageSHA256: cStringOptional(sqlite3_column_text(stmt, 3)),
            members: members
        )
    }

    private func staleInvalidPendingExportBatches(db: OpaquePointer) throws {
        let sql = """
        SELECT batch_id
          FROM local_observation_export_batches
         WHERE status = 'pending'
         ORDER BY created_at_utc, batch_id
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare pending OSC reservation audit")
        }
        var batchIDs: [String] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let id = cStringOptional(sqlite3_column_text(stmt, 0)) { batchIDs.append(id) }
        }
        sqlite3_finalize(stmt)
        for batchID in batchIDs {
            guard let reservation = try loadExportReservation(db: db, batchID: batchID),
                  try exportReservationIsCurrent(db: db, reservation: reservation) else {
                try markExportBatchStale(db: db, batchID: batchID)
                continue
            }
        }
    }

    private func exportReservationIsCurrent(
        db: OpaquePointer,
        reservation: ExportReservation
    ) throws -> Bool {
        guard try exportBatchStatus(db: db, batchID: reservation.batchID) == "pending" else {
            return false
        }
        for member in reservation.members {
            guard let observation = try fetchObservation(
                db: db,
                observationID: member.observationID
            ),
                  observation.exportDisposition == .eligible,
                  observation.primaryWayID == member.wayID,
                  observation.exportTagKey == member.tagKey,
                  Self.canonicalMaxspeedValue(observation.value) == member.value,
                  observation.directionScope == member.directionScope,
                  let target = try? validatedExportTarget(
                    observation,
                    allowManualLocalOnly: true
                  ),
                  target.wayID == member.wayID,
                  target.tagKey == member.tagKey,
                  target.value == member.value,
                  member.approvalRevision == Self.approvalRevision(
                    wayID: member.wayID,
                    tagKey: member.tagKey,
                    value: member.value,
                    direction: member.directionScope
                  ),
                  try isNewestTypedTarget(db: db, observation: observation) else {
                return false
            }
        }
        return true
    }

    private func exportBatchStatus(db: OpaquePointer, batchID: String) throws -> String? {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(
            db,
            "SELECT status FROM local_observation_export_batches WHERE batch_id = ?1 LIMIT 1",
            -1,
            &stmt,
            nil
        ) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare OSC batch status")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, batchID, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_ROW else { return nil }
        return cStringOptional(sqlite3_column_text(stmt, 0))
    }

    private func markExportBatchStaleInDatabase(db: OpaquePointer, batchID: String) throws {
        let sql = """
        UPDATE local_observation_export_batches
           SET status = 'stale'
         WHERE batch_id = ?1 AND status = 'pending';
        UPDATE local_observation_export_members
           SET status = 'stale'
         WHERE batch_id = ?1 AND status = 'pending';
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare stale OSC batch")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, batchID, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_DONE else {
            throw sqliteError(db: db, context: "mark OSC batch stale")
        }
        // sqlite3_prepare_v2 compiles only the first statement; update members
        // separately so partial-index uniqueness is released deterministically.
        var memberStmt: OpaquePointer?
        guard sqlite3_prepare_v2(
            db,
            "UPDATE local_observation_export_members SET status = 'stale' WHERE batch_id = ?1 AND status = 'pending'",
            -1,
            &memberStmt,
            nil
        ) == SQLITE_OK, let memberStmt else {
            throw sqliteError(db: db, context: "prepare stale OSC members")
        }
        defer { sqlite3_finalize(memberStmt) }
        sqlite3_bind_text(memberStmt, 1, batchID, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(memberStmt) == SQLITE_DONE else {
            throw sqliteError(db: db, context: "mark OSC members stale")
        }
    }

    private func markExportBatchStale(db: OpaquePointer, batchID: String) throws {
        try markExportBatchStaleInDatabase(db: db, batchID: batchID)
        if let reservation = try loadExportReservation(db: db, batchID: batchID) {
            try quarantineStaleExportPackage(reservation)
        }
    }

    private func isNewestTypedTarget(
        db: OpaquePointer,
        observation: LocalObservation
    ) throws -> Bool {
        guard let wayID = observation.primaryWayID,
              let direction = observation.directionScope else { return false }
        let applicableDirections: [LocalObservationDirectionScope]
        switch direction {
        case .wayWide:
            applicableDirections = [.wayWide, .forward, .backward, .unknown]
        case .forward:
            applicableDirections = [.forward, .wayWide, .unknown]
        case .backward:
            applicableDirections = [.backward, .wayWide, .unknown]
        case .unknown:
            return false
        }
        let placeholders = applicableDirections.indices.map { "?\($0 + 2)" }.joined(separator: ",")
        let sql = """
        SELECT observation_id
          FROM observations
         WHERE primary_way_id = ?1
           AND direction_scope IN (\(placeholders))
           AND state != 'discarded'
           AND (operation = 'set_maxspeed'
                OR intent_type IN ('map_inconsistency', 'temporary_restriction'))
         ORDER BY COALESCE(effective_at_utc, captured_at_utc) DESC, rowid DESC
         LIMIT 1
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare newest OSC target validation")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, wayID, -1, SQLITE_TRANSIENT)
        for (offset, applicable) in applicableDirections.enumerated() {
            sqlite3_bind_text(stmt, Int32(offset + 2), applicable.rawValue, -1, SQLITE_TRANSIENT)
        }
        guard sqlite3_step(stmt) == SQLITE_ROW else { return false }
        return cStringOptional(sqlite3_column_text(stmt, 0)) == observation.id
    }

    private func quarantineStaleExportPackage(_ reservation: ExportReservation) throws {
        let source = reservation.packageDirectory
        guard fileManager.fileExists(atPath: source.path) else { return }
        let quarantineRoot = try rootDir().appendingPathComponent(
            "stale-osm-editor-packages",
            isDirectory: true
        )
        try createDirectoryIfNeeded(at: quarantineRoot)
        let destination = quarantineRoot.appendingPathComponent(
            reservation.batchID,
            isDirectory: true
        )
        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: source)
        } else {
            try fileManager.moveItem(at: source, to: destination)
        }
    }

    private func quarantineStaleExportBatches(_ batchIDs: [String]) {
        for batchID in Set(batchIDs) {
            do {
                try withDatabase { db in
                    if let reservation = try loadExportReservation(db: db, batchID: batchID),
                       reservation.status == "stale" {
                        try quarantineStaleExportPackage(reservation)
                    }
                }
            } catch {
                Self.logger.error(
                    "OSC stale package quarantine failed batch=\(batchID, privacy: .public) error=\(error.localizedDescription, privacy: .public)"
                )
            }
        }
    }

    private func makeFrozenReviewJSON(_ reservation: ExportReservation) throws -> Data {
        let payload: [String: Any] = [
            "export_id": reservation.batchID,
            "created_at_utc": reservation.createdAtUTC,
            "app_version": appVersion(),
            "observation_ids": reservation.members.map(\.observationID),
            "target_objects": reservation.members.map { ["type": "way", "id": $0.wayID] },
            "suggested_changeset_comment": "Update maxspeed based on YouSpeed local observations",
            "suggested_changeset_source": "YouSpeed local observation",
            "frozen_targets": reservation.members.map {
                [
                    "way_id": $0.wayID,
                    "tag_key": $0.tagKey,
                    "value": $0.value,
                    "approval_revision": $0.approvalRevision,
                ]
            },
        ]
        guard JSONSerialization.isValidJSONObject(payload) else {
            throw ConsumerAppError.io("Invalid frozen review.json payload")
        }
        return try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
    }

    private static func makeFrozenOsmChangeXML(members: [FrozenExportMember]) -> String {
        let body = members.sorted {
            ($0.targetKey, $0.observationID) < ($1.targetKey, $1.observationID)
        }.map { member in
            """
                <way id="\(xmlEscape(member.wayID))">
                  <tag k="\(xmlEscape(member.tagKey))" v="\(xmlEscape(member.value))"/>
                </way>
            """
        }.joined(separator: "\n")
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
        \(body)
          </modify>
        </osmChange>
        """
    }

    private func beginImmediate(_ db: OpaquePointer, context: String) throws {
        guard sqlite3_exec(db, "BEGIN IMMEDIATE", nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: context)
        }
    }

    private func hasPendingExportMember(
        db: OpaquePointer,
        observationID: String
    ) throws -> Bool {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(
            db,
            "SELECT 1 FROM local_observation_export_members WHERE observation_id = ?1 AND status = 'pending' LIMIT 1",
            -1,
            &stmt,
            nil
        ) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare pending OSC member guard")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
        return sqlite3_step(stmt) == SQLITE_ROW
    }

    private func commit(_ db: OpaquePointer, context: String) throws {
        guard sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: context)
        }
    }

    private func updateObservationState(observationID: String, newState: LocalObservationState) throws -> LocalObservation {
        let nowUTC = Self.isoFormatter.string(from: nowProvider())
        return try withDatabase { db in
            try beginImmediate(db, context: "begin observation review transition")
            do {
                guard let existing = try fetchObservation(db: db, observationID: observationID) else {
                    throw ConsumerAppError.io("Observation not found: \(observationID)")
                }
                guard try !hasPendingExportMember(db: db, observationID: observationID) else {
                    throw ConsumerAppError.io("Observation is frozen in a pending OSC export")
                }
                let approvalRevision: String?
                switch newState {
                case .approvedForExport:
                    guard existing.state == .localOnly || existing.state == .needsReview else {
                        throw ConsumerAppError.io("Only local or review observations can be approved")
                    }
                    guard existing.exportDisposition != .superseded,
                          let wayID = existing.primaryWayID,
                          Self.isPositiveWayID(wayID),
                          existing.operation == .setMaxspeed,
                          let direction = existing.directionScope,
                          direction != .unknown,
                          existing.applicability == .permanent,
                          let tagKey = existing.exportTagKey,
                          ["maxspeed", "maxspeed:forward", "maxspeed:backward"].contains(tagKey),
                          let value = Self.canonicalMaxspeedValue(existing.value),
                          existing.modality != .computer_vision
                            || Self.hasSafeComputerVisionRuntimeEvidence(
                                existing,
                                wayID: wayID,
                                direction: direction,
                                tagKey: tagKey,
                                canonicalValue: value
                            ),
                          try isNewestTypedTarget(db: db, observation: existing) else {
                        throw ConsumerAppError.io("Observation is not the newest safe typed maxspeed target")
                    }
                    approvalRevision = Self.approvalRevision(
                        wayID: wayID,
                        tagKey: tagKey,
                        value: value,
                        direction: direction
                    )
                case .discarded:
                    guard existing.state == .localOnly
                            || existing.state == .needsReview
                            || existing.state == .approvedForExport else {
                        throw ConsumerAppError.io("Exported or terminal observations cannot be discarded")
                    }
                    approvalRevision = nil
                default:
                    throw ConsumerAppError.io("Unsupported local observation state transition")
                }
                let sql = """
                UPDATE observations
                   SET state = ?1, updated_at_utc = ?2, approval_revision = ?3
                 WHERE observation_id = ?4 AND state = ?5
                """
                var stmt: OpaquePointer?
                guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                    throw sqliteError(db: db, context: "prepare guarded observation state update")
                }
                sqlite3_bind_text(stmt, 1, newState.rawValue, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 2, nowUTC, -1, SQLITE_TRANSIENT)
                bindOptionalText(approvalRevision, stmt: stmt, index: 3)
                sqlite3_bind_text(stmt, 4, observationID, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 5, existing.state.rawValue, -1, SQLITE_TRANSIENT)
                let step = sqlite3_step(stmt)
                let changed = sqlite3_changes(db)
                sqlite3_finalize(stmt)
                guard step == SQLITE_DONE, changed == 1,
                      let updated = try fetchObservation(db: db, observationID: observationID) else {
                    throw ConsumerAppError.io("Observation changed during review transition")
                }
                try commit(db, context: "commit observation review transition")
                return updated
            } catch {
                sqlite3_exec(db, "ROLLBACK", nil, nil, nil)
                throw error
            }
        }
    }

    private func insertObservation(
        modality: LocalObservationModality,
        intent: LocalObservationIntentType,
        value: String?,
        context: LocalObservationCaptureContext,
        initialState: LocalObservationState,
        oldSpeedKmh: Int? = nil,
        newSpeedKmh: Int? = nil
    ) throws -> LocalObservation {
        var staleExportBatchIDs: [String] = []
        let id = UUID().uuidString.lowercased()
        let nowUTC = Self.isoFormatter.string(from: nowProvider())
        let devicePseudoID = ensureDevicePseudoID()
        let roadIDsData = try JSONEncoder().encode(context.roadCandidateIDs)
        let roadIDsJSON = String(data: roadIDsData, encoding: .utf8) ?? "[]"
        let primaryWayID = context.roadCandidateIDs.first(where: Self.isPositiveWayID)
        let normalizedValue = Self.canonicalMaxspeedValue(value)
        let isCanonicalCorrection = intent == .set_maxspeed
            && primaryWayID != nil
            && normalizedValue != nil
        let operation: LocalObservationOperation? = isCanonicalCorrection ? .setMaxspeed : nil
        let directionScope: LocalObservationDirectionScope? = isCanonicalCorrection ? .wayWide : nil
        let applicability: LocalObservationApplicability? = isCanonicalCorrection ? .permanent : nil
        let exportDisposition: LocalObservationExportDisposition? = isCanonicalCorrection ? .eligible : nil

        do {
            try withDatabase { db in
                let sql = """
                INSERT INTO observations (
                  observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                  city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                  device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                  evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
                  runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
                ) VALUES (
                  ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16,
                  NULL, ?17, ?18, NULL, ?19, ?20, ?21, ?22, ?23, ?24, NULL, NULL, ?25, ?26
                )
                """
                var stmt: OpaquePointer?
                guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                    throw sqliteError(db: db, context: "prepare observation insert")
                }
                defer { sqlite3_finalize(stmt) }

                sqlite3_bind_text(stmt, 1, id, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 2, modality.rawValue, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 3, intent.rawValue, -1, SQLITE_TRANSIENT)
                if let value {
                    sqlite3_bind_text(stmt, 4, value, -1, SQLITE_TRANSIENT)
                } else {
                    sqlite3_bind_null(stmt, 4)
                }
                bindOptionalDouble(context.lat, stmt: stmt, index: 5)
                bindOptionalDouble(context.lon, stmt: stmt, index: 6)
                bindOptionalDouble(context.headingDeg, stmt: stmt, index: 7)
                sqlite3_bind_text(stmt, 8, roadIDsJSON, -1, SQLITE_TRANSIENT)
                bindOptionalText(context.cityContext, stmt: stmt, index: 9)
                bindOptionalText(context.streetContext, stmt: stmt, index: 10)
                sqlite3_bind_text(stmt, 11, nowUTC, -1, SQLITE_TRANSIENT)
                bindOptionalDouble(context.confidenceCalibrated, stmt: stmt, index: 12)
                sqlite3_bind_text(stmt, 13, context.sourceVersion, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 14, initialState.rawValue, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 15, devicePseudoID, -1, SQLITE_TRANSIENT)
                sqlite3_bind_text(stmt, 16, nowUTC, -1, SQLITE_TRANSIENT)
                bindOptionalInt(oldSpeedKmh, stmt: stmt, index: 17)
                bindOptionalInt(newSpeedKmh, stmt: stmt, index: 18)
                bindOptionalText(primaryWayID, stmt: stmt, index: 19)
                sqlite3_bind_text(stmt, 20, nowUTC, -1, SQLITE_TRANSIENT)
                bindOptionalText(operation?.rawValue, stmt: stmt, index: 21)
                bindOptionalText(directionScope?.rawValue, stmt: stmt, index: 22)
                bindOptionalText(applicability?.rawValue, stmt: stmt, index: 23)
                sqlite3_bind_int(stmt, 24, isCanonicalCorrection ? 1 : 0)
                bindOptionalText(exportDisposition?.rawValue, stmt: stmt, index: 25)
                bindOptionalText(isCanonicalCorrection ? "maxspeed" : nil, stmt: stmt, index: 26)

                guard sqlite3_step(stmt) == SQLITE_DONE else {
                    throw sqliteError(db: db, context: "execute observation insert")
                }
                if isCanonicalCorrection, let primaryWayID, let directionScope {
                    staleExportBatchIDs += try supersedeOlderTypedCorrections(
                        db: db,
                        wayID: primaryWayID,
                        direction: directionScope,
                        effectiveAtUTC: nowUTC,
                        keepingObservationID: id
                    )
                }
            }
            quarantineStaleExportBatches(staleExportBatchIDs)
            let observation = try fetchObservation(observationID: id)
            Self.logger.notice(
                "local_obs insert saved id=\(observation.id, privacy: .public) modality=\(observation.modality.rawValue, privacy: .public) state=\(observation.state.rawValue, privacy: .public) way=\(observation.roadCandidateIDs.first ?? "n/a", privacy: .public)"
            )
            return observation
        } catch {
            Self.logger.error(
                "local_obs insert failed modality=\(modality.rawValue, privacy: .public) intent=\(intent.rawValue, privacy: .public) value=\(value ?? "n/a", privacy: .public) error=\(error.localizedDescription, privacy: .public)"
            )
            throw error
        }
    }

    private func fetchObservation(observationID: String) throws -> LocalObservation {
        try withDatabase { db in
            let sql = """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                   evidence_json, primary_way_id, effective_at_utc, operation, direction_scope, applicability,
                   runtime_applicable, finalized_event_id, approval_revision, export_disposition, export_tag_key
            FROM observations
            WHERE observation_id = ?1
            LIMIT 1
            """
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare single observation fetch")
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(stmt) == SQLITE_ROW else {
                throw ConsumerAppError.io("Observation not found: \(observationID)")
            }
            guard let observation = decodeObservationRow(stmt) else {
                throw ConsumerAppError.io("Observation is from an unsupported future schema: \(observationID)")
            }
            return observation
        }
    }

    private func decodeObservationRow(_ stmt: OpaquePointer) -> LocalObservation? {
        guard let id = cString(sqlite3_column_text(stmt, 0)),
              let modalityRaw = cString(sqlite3_column_text(stmt, 1)),
              let modality = LocalObservationModality(rawValue: modalityRaw),
              let intentRaw = cString(sqlite3_column_text(stmt, 2)),
              let intent = LocalObservationIntentType(rawValue: intentRaw),
              let capturedAt = cString(sqlite3_column_text(stmt, 10)),
              let sourceVersion = cString(sqlite3_column_text(stmt, 12)),
              let stateRaw = cString(sqlite3_column_text(stmt, 13)),
              let state = LocalObservationState(rawValue: stateRaw),
              let devicePseudoID = cString(sqlite3_column_text(stmt, 14)),
              let updatedAt = cString(sqlite3_column_text(stmt, 15)) else {
            return nil
        }

        let roadJSON = cString(sqlite3_column_text(stmt, 7)) ?? "[]"
        let roadIDs: [String]
        if let jsonData = roadJSON.data(using: .utf8),
           let decoded = try? JSONDecoder().decode([String].self, from: jsonData) {
            roadIDs = decoded
        } else {
            roadIDs = []
        }

        let operationRaw = cStringOptional(sqlite3_column_text(stmt, 22))
        let directionRaw = cStringOptional(sqlite3_column_text(stmt, 23))
        let applicabilityRaw = cStringOptional(sqlite3_column_text(stmt, 24))
        let dispositionRaw = cStringOptional(sqlite3_column_text(stmt, 28))
        guard operationRaw == nil || LocalObservationOperation(rawValue: operationRaw!) != nil,
              directionRaw == nil || LocalObservationDirectionScope(rawValue: directionRaw!) != nil,
              applicabilityRaw == nil || LocalObservationApplicability(rawValue: applicabilityRaw!) != nil,
              dispositionRaw == nil || LocalObservationExportDisposition(rawValue: dispositionRaw!) != nil else {
            return nil
        }

        return LocalObservation(
            id: id,
            modality: modality,
            intentType: intent,
            value: cStringOptional(sqlite3_column_text(stmt, 3)),
            lat: sqliteOptionalDouble(stmt, index: 4),
            lon: sqliteOptionalDouble(stmt, index: 5),
            headingDeg: sqliteOptionalDouble(stmt, index: 6),
            roadCandidateIDs: roadIDs,
            cityContext: cStringOptional(sqlite3_column_text(stmt, 8)),
            streetContext: cStringOptional(sqlite3_column_text(stmt, 9)),
            capturedAtUTC: capturedAt,
            confidenceCalibrated: sqliteOptionalDouble(stmt, index: 11),
            sourceVersion: sourceVersion,
            state: state,
            devicePseudoID: devicePseudoID,
            updatedAtUTC: updatedAt,
            exportID: cStringOptional(sqlite3_column_text(stmt, 16)),
            oldSpeedKmh: sqliteOptionalInt(stmt, index: 17),
            newSpeedKmh: sqliteOptionalInt(stmt, index: 18),
            evidenceJSON: cStringOptional(sqlite3_column_text(stmt, 19)),
            primaryWayID: cStringOptional(sqlite3_column_text(stmt, 20)),
            effectiveAtUTC: cStringOptional(sqlite3_column_text(stmt, 21)),
            operation: operationRaw.flatMap(LocalObservationOperation.init(rawValue:)),
            directionScope: directionRaw.flatMap(LocalObservationDirectionScope.init(rawValue:)),
            applicability: applicabilityRaw.flatMap(LocalObservationApplicability.init(rawValue:)),
            runtimeApplicable: sqliteOptionalInt(stmt, index: 25).map { $0 != 0 },
            finalizedEventID: cStringOptional(sqlite3_column_text(stmt, 26)),
            approvalRevision: cStringOptional(sqlite3_column_text(stmt, 27)),
            exportDisposition: dispositionRaw.flatMap(LocalObservationExportDisposition.init(rawValue:)),
            exportTagKey: cStringOptional(sqlite3_column_text(stmt, 29))
        )
    }

    /// Fail-closed structural gate shared by direct runtime lookup and
    /// computer-vision equivalence detection. Export approval/disposition is
    /// intentionally absent: those fields govern OSC publication, not runtime
    /// correction history.
    private static func validatedRuntimeCorrectionValue(
        _ observation: LocalObservation,
        expectedWayID: String,
        acceptedDirections: [LocalObservationDirectionScope]
    ) -> String? {
        guard observation.runtimeApplicable == true,
              observation.state != .discarded,
              observation.intentType == .set_maxspeed,
              observation.operation == .setMaxspeed,
              observation.applicability == .permanent,
              let wayID = observation.primaryWayID?
                .trimmingCharacters(in: .whitespacesAndNewlines),
              wayID == expectedWayID,
              isPositiveWayID(wayID),
              let direction = observation.directionScope,
              acceptedDirections.contains(direction),
              direction != .unknown,
              let canonicalValue = canonicalMaxspeedValue(observation.value),
              let expectedTagKey = runtimeTagKey(for: direction),
              observation.exportTagKey == expectedTagKey else {
            return nil
        }

        switch observation.modality {
        case .voice_command:
            // Preserve the documented legacy voice/manual behavior: safely
            // typed historical rows can remain runtime-active while awaiting
            // review. Review-only camera evidence has no such compatibility
            // exception.
            break
        case .computer_vision:
            guard observation.state != .needsReview,
                  hasSafeComputerVisionRuntimeEvidence(
                observation,
                wayID: wayID,
                direction: direction,
                tagKey: expectedTagKey,
                canonicalValue: canonicalValue
            ) else {
                return nil
            }
        case .lock_current_speed:
            return nil
        }
        return canonicalValue
    }

    /// Camera corrections are authoritative only while their immutable shared
    /// passage envelope proves the same resolved, unconditional typed target as
    /// the indexed columns. Corrupt or partial evidence is review data only.
    private static func hasSafeComputerVisionRuntimeEvidence(
        _ observation: LocalObservation,
        wayID: String,
        direction: LocalObservationDirectionScope,
        tagKey: String,
        canonicalValue: String
    ) -> Bool {
        guard let finalizedEventID = nonemptyRuntimeString(observation.finalizedEventID),
              let evidenceJSON = observation.evidenceJSON,
              let evidenceData = evidenceJSON.data(using: .utf8),
              let root = (try? JSONSerialization.jsonObject(with: evidenceData)) as? [String: Any],
              (root["schema_version"] as? NSNumber)?.intValue == 1,
              root["event_kind"] as? String == "traffic_sign_passage",
              root["finalized_event_id"] as? String == finalizedEventID,
              nonemptyRuntimeString(root["drive_session_id"] as? String) != nil,
              let pack = root["pack"] as? [String: Any],
              pack["override_eligible"] as? Bool == true,
              pack["calibration_status"] as? String == "passed",
              let components = pack["components"] as? [[String: Any]],
              !components.isEmpty,
              components.allSatisfy({ component in
                  nonemptyRuntimeString(component["role"] as? String) != nil
                      && isRuntimeSHA256(component["artifact_sha256"] as? String)
                      && nonemptyRuntimeString(component["preprocessing_version"] as? String) != nil
                      && nonemptyRuntimeString(component["calibration_id"] as? String) != nil
              }),
              let action = root["action"] as? [String: Any],
              nonemptyRuntimeString(action["kind"] as? String) != nil,
              action["permanence"] as? String == "permanent",
              action["condition_state"] as? String == "none",
              let restrictions = action["restrictions"] as? [Any],
              restrictions.isEmpty,
              let activation = root["activation"] as? [String: Any],
              activation["way_id"] as? String == wayID,
              let scope = root["applicability_scope"] as? [String: Any],
              scope["continuity_capable_bundle"] as? Bool == true,
              isRuntimeSHA256(scope["bundle_sha256"] as? String),
              let resolution = root["resolution"] as? [String: Any],
              resolution["runtime_status"] as? String == "resolved",
              let operation = resolution["normalized_operation"] as? [String: Any],
              operation["operation"] as? String == "set_maxspeed",
              operation["tag_key"] as? String == tagKey,
              canonicalMaxspeedValue(operation["tag_value"] as? String) == canonicalValue,
              operation["direction_scope"] as? String == runtimeWireDirection(for: direction),
              let persistence = root["persistence"] as? [String: Any],
              persistence["observation_intent"] as? String == "set_maxspeed",
              persistence["runtime_applicable"] as? Bool == true else {
            return false
        }
        return true
    }

    private static func runtimeTagKey(
        for direction: LocalObservationDirectionScope
    ) -> String? {
        switch direction {
        case .wayWide: return "maxspeed"
        case .forward: return "maxspeed:forward"
        case .backward: return "maxspeed:backward"
        case .unknown: return nil
        }
    }

    private static func runtimeWireDirection(
        for direction: LocalObservationDirectionScope
    ) -> String? {
        switch direction {
        case .wayWide: return "way"
        case .forward: return "forward"
        case .backward: return "backward"
        case .unknown: return nil
        }
    }

    private static func nonemptyRuntimeString(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !trimmed.isEmpty else {
            return nil
        }
        return trimmed
    }

    private static func isRuntimeSHA256(_ value: String?) -> Bool {
        guard let value, value.count == 64 else { return false }
        return value.unicodeScalars.allSatisfy { scalar in
            switch scalar.value {
            case 48...57, 65...70, 97...102: return true
            default: return false
            }
        }
    }

    private func validatedExportTarget(
        _ observation: LocalObservation,
        allowManualLocalOnly: Bool = false
    ) throws -> (wayID: String, tagKey: String, value: String) {
        let explicitlyApproved = observation.state == .approvedForExport
        let implicitManualBulkApproval = allowManualLocalOnly
            && (observation.state == .localOnly || observation.state == .needsReview)
            && observation.modality != .computer_vision
            && observation.approvalRevision == nil
        guard explicitlyApproved || implicitManualBulkApproval else {
            throw ConsumerAppError.io(
                observation.modality == .computer_vision
                    ? "Computer-vision observations must be approved_for_export before OSC generation"
                    : "Observation must be approved_for_export before OSC generation"
            )
        }
        guard observation.exportDisposition == .eligible,
              observation.operation == .setMaxspeed,
              observation.applicability == .permanent,
              let direction = observation.directionScope,
              direction != .unknown,
              let wayID = observation.primaryWayID,
              Self.isPositiveWayID(wayID),
              let tagKey = observation.exportTagKey,
              ["maxspeed", "maxspeed:forward", "maxspeed:backward"].contains(tagKey),
              let value = Self.canonicalMaxspeedValue(observation.value) else {
            throw ConsumerAppError.io("Observation has no eligible typed permanent maxspeed operation")
        }
        let expectedTagKey: String
        switch direction {
        case .wayWide: expectedTagKey = "maxspeed"
        case .forward: expectedTagKey = "maxspeed:forward"
        case .backward: expectedTagKey = "maxspeed:backward"
        case .unknown:
            throw ConsumerAppError.io("Unknown direction cannot be exported")
        }
        guard tagKey == expectedTagKey else {
            throw ConsumerAppError.io("Observation tag key does not match its reviewed direction")
        }
        guard observation.modality != .computer_vision
                || Self.hasSafeComputerVisionRuntimeEvidence(
                    observation,
                    wayID: wayID,
                    direction: direction,
                    tagKey: tagKey,
                    canonicalValue: value
                ) else {
            throw ConsumerAppError.io(
                "Computer-vision observation has incomplete or inconsistent passage evidence"
            )
        }
        let expectedRevision = Self.approvalRevision(
            wayID: wayID,
            tagKey: tagKey,
            value: value,
            direction: direction
        )
        guard implicitManualBulkApproval || observation.approvalRevision == expectedRevision else {
            throw ConsumerAppError.io("Observation changed after approval and must be reviewed again")
        }
        return (wayID, tagKey, value)
    }

    private func makeReviewJSON(
        exportID: String,
        createdAtUTC: String,
        observation: LocalObservation,
        proposal: LocalObservationProposal
    ) throws -> Data {
        let targetObjects = proposal.targetObjects.map { ["type": $0.type, "id": $0.id] }
        let payload: [String: Any] = [
            "export_id": exportID,
            "created_at_utc": createdAtUTC,
            "app_version": appVersion(),
            "data_bundle_version": observation.sourceVersion,
            "observation_ids": [observation.id],
            "target_objects": targetObjects,
            "street_context": observation.streetContext ?? "",
            "city_context": observation.cityContext ?? "",
            "suggested_changeset_comment": "Update maxspeed based on YouSpeed local observation",
            "suggested_changeset_source": "YouSpeed local observation",
            "confidence_summary": proposal.confidenceSummary,
        ]
        guard JSONSerialization.isValidJSONObject(payload) else {
            throw ConsumerAppError.io("Invalid review.json payload")
        }
        return try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
    }

    private static let readmeTemplate = """
    YouSpeed editor export package

    Files:
    - changes.osc
    - review.json
    - README.txt

    JOSM import:
    1. Open JOSM.
    2. File -> Open... and select changes.osc.
    3. Review all tag changes carefully.
    4. Upload using your own OSM account.

    Merkaartor import:
    1. Open Merkaartor.
    2. Import changes.osc.
    3. Review all edited objects and tags.
    4. Upload using your own OSM account.

    Important:
    - Final upload is always user-controlled in the editor.
    - You are responsible for reviewing correctness before upload.
    """

    private static func makeOsmChangeXML(
        wayID: String,
        tagKey: String,
        maxspeedValue: String
    ) -> String {
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
            <way id="\(xmlEscape(wayID))">
              <tag k="\(xmlEscape(tagKey))" v="\(xmlEscape(maxspeedValue))"/>
            </way>
          </modify>
        </osmChange>
        """
    }

    private static func makeBulkOsmChangeXML(observations: [LocalObservation]) -> String {
        let body = observations.compactMap { observation -> String? in
            guard let wayID = observation.primaryWayID,
                  let tagKey = observation.exportTagKey,
                  let maxspeedValue = observation.value?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !maxspeedValue.isEmpty else {
                return nil
            }
            return """
                <way id="\(xmlEscape(wayID))">
                  <tag k="\(xmlEscape(tagKey))" v="\(xmlEscape(maxspeedValue))"/>
                </way>
            """
        }.joined(separator: "\n")
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
        \(body)
          </modify>
        </osmChange>
        """
    }

    private static func xmlEscape(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func safeTimestamp(_ iso: String) -> String {
        iso.replacingOccurrences(of: ":", with: "").replacingOccurrences(of: "-", with: "")
    }

    private func appVersion() -> String {
        let short = (bundle.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.0.0"
        let build = (bundle.infoDictionary?["CFBundleVersion"] as? String) ?? "0"
        return "\(short) (\(build))"
    }

    private func ensureDevicePseudoID() -> String {
        if let existing = userDefaults.string(forKey: Self.devicePseudoIDDefaultsKey),
           !existing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return existing
        }
        let generated = UUID().uuidString.lowercased()
        userDefaults.set(generated, forKey: Self.devicePseudoIDDefaultsKey)
        return generated
    }

    private static func extractFirstSpeedKmh(from text: String) -> Int? {
        let pattern = #"\b([1-9][0-9]{0,2})\b"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..<text.endIndex, in: text)),
              let range = Range(match.range(at: 1), in: text),
              let value = Int(text[range]),
              (5...160).contains(value) else {
            return nil
        }
        return value
    }

    private static func canonicalMaxspeedValue(_ value: String?) -> String? {
        guard let normalized = value?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(), !normalized.isEmpty else { return nil }
        if normalized == "walk" || normalized == "none" { return normalized }
        guard let numeric = Int(normalized), (5...200).contains(numeric) else { return nil }
        return String(numeric)
    }

    private static func isPositiveWayID(_ value: String) -> Bool {
        guard let numeric = Int64(value.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return false
        }
        return numeric > 0
    }

    private static func approvalRevision(
        wayID: String,
        tagKey: String,
        value: String,
        direction: LocalObservationDirectionScope
    ) -> String {
        "way:\(wayID)|tag:\(tagKey)|value:\(value)|direction:\(direction.rawValue)"
    }

    private func rootDir() throws -> URL {
        if let rootDirectoryOverride {
            try createDirectoryIfNeeded(at: rootDirectoryOverride)
            return rootDirectoryOverride
        }
        return try V3BundleManager.applicationSupportDirectory(fileManager: fileManager)
    }

    private func databaseURL() throws -> URL {
        try rootDir().appendingPathComponent("local_observation_store.sqlite")
    }

    private func exportsDirectory() throws -> URL {
        let url = try rootDir().appendingPathComponent("osm-editor-packages", isDirectory: true)
        try createDirectoryIfNeeded(at: url)
        return url
    }

    private func withDatabase<T>(_ block: (OpaquePointer) throws -> T) throws -> T {
        let dbURL = try databaseURL()
        let root = dbURL.deletingLastPathComponent()
        try createDirectoryIfNeeded(at: root)

        var db: OpaquePointer?
        let flags = SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(dbURL.path, &db, flags, nil) == SQLITE_OK, let db else {
            let msg = db.flatMap { sqlite3_errmsg($0).flatMap { String(cString: $0) } } ?? "unknown sqlite error"
            if let db {
                sqlite3_close(db)
            }
            throw ConsumerAppError.sqlite("open local observation store failed: \(msg)")
        }
        defer { sqlite3_close(db) }

        try ensureSchema(db: db)
        return try block(db)
    }

    private func ensureSchema(db: OpaquePointer) throws {
        let sql = """
        CREATE TABLE IF NOT EXISTS observations (
          observation_id TEXT PRIMARY KEY,
          modality TEXT NOT NULL,
          intent_type TEXT NOT NULL,
          value TEXT,
          lat REAL,
          lon REAL,
          heading_deg REAL,
          road_candidate_ids TEXT NOT NULL,
          city_context TEXT,
          street_context TEXT,
          captured_at_utc TEXT NOT NULL,
          confidence_calibrated REAL,
          source_version TEXT NOT NULL,
          state TEXT NOT NULL,
          device_pseudo_id TEXT NOT NULL,
          updated_at_utc TEXT NOT NULL,
          export_id TEXT,
          old_speed_kmh INTEGER,
          new_speed_kmh INTEGER,
          evidence_json TEXT,
          primary_way_id TEXT,
          effective_at_utc TEXT,
          operation TEXT,
          direction_scope TEXT,
          applicability TEXT,
          runtime_applicable INTEGER NOT NULL DEFAULT 0,
          finalized_event_id TEXT,
          approval_revision TEXT,
          export_disposition TEXT,
          export_tag_key TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_observations_state ON observations(state);
        CREATE INDEX IF NOT EXISTS idx_observations_captured ON observations(captured_at_utc DESC);
        CREATE TABLE IF NOT EXISTS exports (
          export_id TEXT PRIMARY KEY,
          created_at_utc TEXT NOT NULL,
          package_path TEXT NOT NULL,
          package_sha256 TEXT NOT NULL,
          observation_ids TEXT NOT NULL,
          returned_changeset_id TEXT
        );
        CREATE TABLE IF NOT EXISTS computer_vision_event_receipts (
          finalized_event_id TEXT PRIMARY KEY,
          decision TEXT NOT NULL,
          observation_id TEXT,
          consumed_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS computer_vision_passage_events (
          finalized_event_id TEXT PRIMARY KEY,
          evidence_json TEXT NOT NULL,
          equivalent_observation_id TEXT,
          consumed_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_observation_export_batches (
          batch_id TEXT PRIMARY KEY,
          created_at_utc TEXT NOT NULL,
          status TEXT NOT NULL,
          package_path TEXT NOT NULL,
          package_sha256 TEXT,
          payload_json TEXT NOT NULL,
          finalized_at_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS local_observation_export_members (
          batch_id TEXT NOT NULL,
          observation_id TEXT NOT NULL,
          target_key TEXT NOT NULL,
          approval_revision TEXT NOT NULL,
          status TEXT NOT NULL,
          PRIMARY KEY (batch_id, observation_id),
          FOREIGN KEY (batch_id) REFERENCES local_observation_export_batches(batch_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_export_members_pending_observation
          ON local_observation_export_members(observation_id)
          WHERE status = 'pending';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_export_members_pending_target
          ON local_observation_export_members(target_key)
          WHERE status = 'pending';
        """
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: "ensure local observation schema")
        }
        try ensureObservationColumn(db: db, columnName: "old_speed_kmh", typeDeclaration: "INTEGER")
        try ensureObservationColumn(db: db, columnName: "new_speed_kmh", typeDeclaration: "INTEGER")
        try ensureObservationColumn(db: db, columnName: "evidence_json", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "primary_way_id", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "effective_at_utc", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "operation", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "direction_scope", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "applicability", typeDeclaration: "TEXT")
        try ensureObservationColumn(
            db: db,
            columnName: "runtime_applicable",
            typeDeclaration: "INTEGER NOT NULL DEFAULT 0"
        )
        try ensureObservationColumn(db: db, columnName: "finalized_event_id", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "approval_revision", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "export_disposition", typeDeclaration: "TEXT")
        try ensureObservationColumn(db: db, columnName: "export_tag_key", typeDeclaration: "TEXT")
        try backfillLegacyObservationSemantics(db: db)
        let indexSQL = """
        CREATE INDEX IF NOT EXISTS idx_observations_runtime_way
          ON observations(primary_way_id, direction_scope, effective_at_utc DESC, observation_id DESC)
          WHERE runtime_applicable = 1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_cv_event
          ON observations(finalized_event_id)
          WHERE finalized_event_id IS NOT NULL;
        """
        guard sqlite3_exec(db, indexSQL, nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: "ensure observation runtime indexes")
        }
    }

    private func backfillLegacyObservationSemantics(db: OpaquePointer) throws {
        let selectSQL = """
        SELECT observation_id, intent_type, value, road_candidate_ids, captured_at_utc, state
        FROM observations
        WHERE effective_at_utc IS NULL OR operation IS NULL
        """
        var selectStmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, selectSQL, -1, &selectStmt, nil) == SQLITE_OK,
              let selectStmt else {
            throw sqliteError(db: db, context: "prepare legacy observation backfill")
        }
        defer { sqlite3_finalize(selectStmt) }

        let updateSQL = """
        UPDATE observations
           SET primary_way_id = COALESCE(primary_way_id, ?1),
               effective_at_utc = COALESCE(effective_at_utc, ?2),
               operation = COALESCE(operation, ?3),
               direction_scope = COALESCE(direction_scope, ?4),
               applicability = COALESCE(applicability, ?5),
               runtime_applicable = ?6,
               export_disposition = COALESCE(export_disposition, ?7),
               export_tag_key = COALESCE(export_tag_key, ?8),
               approval_revision = COALESCE(approval_revision, ?9)
         WHERE observation_id = ?10
        """
        while sqlite3_step(selectStmt) == SQLITE_ROW {
            guard let id = cStringOptional(sqlite3_column_text(selectStmt, 0)),
                  let capturedAt = cStringOptional(sqlite3_column_text(selectStmt, 4)) else { continue }
            let intent = cStringOptional(sqlite3_column_text(selectStmt, 1))
            let value = cStringOptional(sqlite3_column_text(selectStmt, 2))
            let state = cStringOptional(sqlite3_column_text(selectStmt, 5))
            let roadJSON = cStringOptional(sqlite3_column_text(selectStmt, 3)) ?? "[]"
            let roads = roadJSON.data(using: .utf8).flatMap {
                try? JSONDecoder().decode([String].self, from: $0)
            } ?? []
            let primaryWayID = roads.first(where: Self.isPositiveWayID)
            let normalized = Self.canonicalMaxspeedValue(value)
            let canonical = intent == LocalObservationIntentType.set_maxspeed.rawValue
                && primaryWayID != nil
                && normalized != nil
            let approvalRevision = canonical
                && state == LocalObservationState.approvedForExport.rawValue
                ? Self.approvalRevision(
                    wayID: primaryWayID!,
                    tagKey: "maxspeed",
                    value: normalized!,
                    direction: .wayWide
                )
                : nil

            var updateStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, updateSQL, -1, &updateStmt, nil) == SQLITE_OK,
                  let updateStmt else {
                throw sqliteError(db: db, context: "prepare legacy observation update")
            }
            bindOptionalText(primaryWayID, stmt: updateStmt, index: 1)
            sqlite3_bind_text(updateStmt, 2, capturedAt, -1, SQLITE_TRANSIENT)
            bindOptionalText(canonical ? LocalObservationOperation.setMaxspeed.rawValue : nil, stmt: updateStmt, index: 3)
            bindOptionalText(canonical ? LocalObservationDirectionScope.wayWide.rawValue : nil, stmt: updateStmt, index: 4)
            bindOptionalText(canonical ? LocalObservationApplicability.permanent.rawValue : nil, stmt: updateStmt, index: 5)
            sqlite3_bind_int(updateStmt, 6, canonical ? 1 : 0)
            bindOptionalText(canonical ? LocalObservationExportDisposition.eligible.rawValue : nil, stmt: updateStmt, index: 7)
            bindOptionalText(canonical ? "maxspeed" : nil, stmt: updateStmt, index: 8)
            bindOptionalText(approvalRevision, stmt: updateStmt, index: 9)
            sqlite3_bind_text(updateStmt, 10, id, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(updateStmt) == SQLITE_DONE else {
                sqlite3_finalize(updateStmt)
                throw sqliteError(db: db, context: "execute legacy observation update")
            }
            sqlite3_finalize(updateStmt)
        }
    }

    private func ensureObservationColumn(
        db: OpaquePointer,
        columnName: String,
        typeDeclaration: String
    ) throws {
        let pragma = "PRAGMA table_info(observations)"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, pragma, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare schema table_info")
        }
        defer { sqlite3_finalize(stmt) }

        var exists = false
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let namePtr = sqlite3_column_text(stmt, 1),
               String(cString: namePtr) == columnName {
                exists = true
                break
            }
        }
        guard !exists else {
            return
        }
        let alterSQL = "ALTER TABLE observations ADD COLUMN \(columnName) \(typeDeclaration)"
        guard sqlite3_exec(db, alterSQL, nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: "alter observations add \(columnName)")
        }
    }

    private func createDirectoryIfNeeded(at url: URL) throws {
        if !fileManager.fileExists(atPath: url.path) {
            try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
        }
    }

    private func sqliteError(db: OpaquePointer, context: String) -> ConsumerAppError {
        let message = sqlite3_errmsg(db).flatMap { String(cString: $0) } ?? "unknown sqlite error"
        return .sqlite("\(context): \(message)")
    }

    private func bindOptionalDouble(_ value: Double?, stmt: OpaquePointer, index: Int32) {
        if let value {
            sqlite3_bind_double(stmt, index, value)
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func bindOptionalText(_ value: String?, stmt: OpaquePointer, index: Int32) {
        if let value {
            sqlite3_bind_text(stmt, index, value, -1, SQLITE_TRANSIENT)
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func bindOptionalInt(_ value: Int?, stmt: OpaquePointer, index: Int32) {
        if let value {
            sqlite3_bind_int64(stmt, index, Int64(value))
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func sqliteOptionalDouble(_ stmt: OpaquePointer, index: Int32) -> Double? {
        if sqlite3_column_type(stmt, index) == SQLITE_NULL {
            return nil
        }
        return sqlite3_column_double(stmt, index)
    }

    private func sqliteOptionalInt(_ stmt: OpaquePointer, index: Int32) -> Int? {
        if sqlite3_column_type(stmt, index) == SQLITE_NULL {
            return nil
        }
        return Int(sqlite3_column_int64(stmt, index))
    }

    private func cString(_ ptr: UnsafePointer<UInt8>?) -> String? {
        guard let ptr else {
            return nil
        }
        return String(cString: ptr)
    }

    private func cStringOptional(_ ptr: UnsafePointer<UInt8>?) -> String? {
        guard let value = cString(ptr)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }
}

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

    init(
        region: String,
        bundleVersion: String,
        dbFileName: String,
        activatedAtUTC: String,
        dbPath: String? = nil
    ) {
        self.region = region
        self.bundleVersion = bundleVersion
        self.dbFileName = dbFileName
        self.dbPath = dbPath
        self.activatedAtUTC = activatedAtUTC
    }

    enum CodingKeys: String, CodingKey {
        case region
        case bundleVersion = "bundle_version"
        case dbFileName = "db_file_name"
        case dbPath = "db_path"
        case activatedAtUTC = "activated_at_utc"
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

actor LocalObservationStore {
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

    func fetchObservations(states: [LocalObservationState]? = nil, limit: Int = 50) throws -> [LocalObservation] {
        try withDatabase { db in
            var sql = """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
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
                out.append(try decodeObservationRow(stmt))
            }
            return out
        }
    }

    func deleteObservation(observationID: String) throws {
        try withDatabase { db in
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
        guard observation.state == .approvedForExport || observation.state == .needsReview else {
            throw ConsumerAppError.io("Observation \(observationID) is not exportable in current state \(observation.state.rawValue)")
        }
        guard let wayID = observation.roadCandidateIDs.first, !wayID.isEmpty else {
            throw ConsumerAppError.io("Observation \(observationID) has no road candidate id")
        }
        guard let rawValue = observation.value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.isEmpty else {
            throw ConsumerAppError.io("Observation \(observationID) does not contain a maxspeed value")
        }

        let xml = Self.makeOsmChangeXML(wayID: wayID, maxspeedValue: rawValue)
        let summary = observation.confidenceCalibrated.map { String(format: "confidence=%.2f", $0) } ?? "confidence=n/a"
        return LocalObservationProposal(
            observationID: observationID,
            targetObjects: [.init(type: "way", id: wayID)],
            oscXML: xml,
            confidenceSummary: summary
        )
    }

    func exportProposalAsOscPackage(observationID: String) throws -> LocalObservationExportResult {
        let proposal = try buildOsmProposal(observationID: observationID)
        let observation = try fetchObservation(observationID: observationID)
        guard observation.state == .approvedForExport else {
            throw ConsumerAppError.io("Observation must be approved_for_export before export")
        }

        let createdAt = nowProvider()
        let createdAtUTC = Self.isoFormatter.string(from: createdAt)
        let exportID = UUID().uuidString.lowercased()
        let packageDirectory = try exportsDirectory()
            .appendingPathComponent("osm-export-\(Self.safeTimestamp(createdAtUTC))-\(String(exportID.prefix(8)))", isDirectory: true)
        try createDirectoryIfNeeded(at: packageDirectory)

        let changesFile = packageDirectory.appendingPathComponent("changes.osc")
        let reviewFile = packageDirectory.appendingPathComponent("review.json")
        let readmeFile = packageDirectory.appendingPathComponent("README.txt")

        let oscData = Data(proposal.oscXML.utf8)
        try oscData.write(to: changesFile, options: .atomic)
        let reviewJSON = try makeReviewJSON(
            exportID: exportID,
            createdAtUTC: createdAtUTC,
            observation: observation,
            proposal: proposal
        )
        try reviewJSON.write(to: reviewFile, options: .atomic)
        try Data(Self.readmeTemplate.utf8).write(to: readmeFile, options: .atomic)

        let oscSHA = SHA256.hash(data: oscData).compactMap { String(format: "%02x", $0) }.joined()
        try withDatabase { db in
            let insertExportSQL = """
            INSERT OR REPLACE INTO exports (
              export_id, created_at_utc, package_path, package_sha256, observation_ids, returned_changeset_id
            ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)
            """
            var exportStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, insertExportSQL, -1, &exportStmt, nil) == SQLITE_OK, let exportStmt else {
                throw sqliteError(db: db, context: "prepare export insert")
            }
            defer { sqlite3_finalize(exportStmt) }
            sqlite3_bind_text(exportStmt, 1, exportID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 3, packageDirectory.path, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 4, oscSHA, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 5, "[\"\(observation.id)\"]", -1, SQLITE_TRANSIENT)
            guard sqlite3_step(exportStmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "insert export row")
            }

            let updateObsSQL = """
            UPDATE observations
               SET state = ?1, updated_at_utc = ?2, export_id = ?3
             WHERE observation_id = ?4
            """
            var updateStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, updateObsSQL, -1, &updateStmt, nil) == SQLITE_OK, let updateStmt else {
                throw sqliteError(db: db, context: "prepare observation update after export")
            }
            defer { sqlite3_finalize(updateStmt) }
            sqlite3_bind_text(updateStmt, 1, LocalObservationState.exportedOsc.rawValue, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(updateStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(updateStmt, 3, exportID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(updateStmt, 4, observation.id, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(updateStmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "update exported observation state")
            }
        }

        return LocalObservationExportResult(
            exportID: exportID,
            packageDirectory: packageDirectory,
            changesFile: changesFile,
            reviewFile: reviewFile,
            readmeFile: readmeFile
        )
    }

    func exportAllLocalObservationsAsOsc() throws -> LocalObservationBulkExportResult {
        let observations = try fetchObservations(limit: 1_000)
            .filter { $0.state != .discarded }
            .sorted { $0.capturedAtUTC < $1.capturedAtUTC }
        let reduced = observations.reduce(into: [String: LocalObservation]()) { partial, observation in
            guard let wayID = observation.roadCandidateIDs.first,
                  !wayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  let maxspeedValue = observation.value?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !maxspeedValue.isEmpty else {
                return
            }
            if let newSpeed = observation.newSpeedKmh, newSpeed <= 0 {
                return
            }
            partial[wayID] = observation
        }
        let payload = reduced.values.sorted { lhs, rhs in
            lhs.capturedAtUTC < rhs.capturedAtUTC
        }
        guard !payload.isEmpty else {
            throw ConsumerAppError.io("Keine lokalen Erfassungen mit Way-ID und maxspeed-Wert vorhanden.")
        }

        let createdAt = nowProvider()
        let createdAtUTC = Self.isoFormatter.string(from: createdAt)
        let exportID = UUID().uuidString.lowercased()
        let packageDirectory = try exportsDirectory()
            .appendingPathComponent("osm-export-all-\(Self.safeTimestamp(createdAtUTC))-\(String(exportID.prefix(8)))", isDirectory: true)
        try createDirectoryIfNeeded(at: packageDirectory)

        let changesFile = packageDirectory.appendingPathComponent("changes.osc")
        let xml = Self.makeBulkOsmChangeXML(observations: payload)
        let oscData = Data(xml.utf8)
        try oscData.write(to: changesFile, options: .atomic)
        let oscSHA = SHA256.hash(data: oscData).compactMap { String(format: "%02x", $0) }.joined()

        let observationIDsJSONData = try JSONEncoder().encode(payload.map(\.id))
        let observationIDsJSON = String(data: observationIDsJSONData, encoding: .utf8) ?? "[]"

        try withDatabase { db in
            let insertExportSQL = """
            INSERT OR REPLACE INTO exports (
              export_id, created_at_utc, package_path, package_sha256, observation_ids, returned_changeset_id
            ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)
            """
            var exportStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, insertExportSQL, -1, &exportStmt, nil) == SQLITE_OK, let exportStmt else {
                throw sqliteError(db: db, context: "prepare bulk export insert")
            }
            defer { sqlite3_finalize(exportStmt) }
            sqlite3_bind_text(exportStmt, 1, exportID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 3, packageDirectory.path, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 4, oscSHA, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 5, observationIDsJSON, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(exportStmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "insert bulk export row")
            }
        }

        return LocalObservationBulkExportResult(
            exportID: exportID,
            packageDirectory: packageDirectory,
            changesFile: changesFile,
            includedCount: payload.count
        )
    }

    private func updateObservationState(observationID: String, newState: LocalObservationState) throws -> LocalObservation {
        let nowUTC = Self.isoFormatter.string(from: nowProvider())
        try withDatabase { db in
            let sql = """
            UPDATE observations
               SET state = ?1, updated_at_utc = ?2
             WHERE observation_id = ?3
            """
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation state update")
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, newState.rawValue, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 2, nowUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 3, observationID, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(stmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "execute observation state update")
            }
        }
        return try fetchObservation(observationID: observationID)
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
        let id = UUID().uuidString.lowercased()
        let nowUTC = Self.isoFormatter.string(from: nowProvider())
        let devicePseudoID = ensureDevicePseudoID()
        let roadIDsData = try JSONEncoder().encode(context.roadCandidateIDs)
        let roadIDsJSON = String(data: roadIDsData, encoding: .utf8) ?? "[]"

        do {
            try withDatabase { db in
                let sql = """
                INSERT INTO observations (
                  observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                  city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                  device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, NULL, ?17, ?18)
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

                guard sqlite3_step(stmt) == SQLITE_DONE else {
                    throw sqliteError(db: db, context: "execute observation insert")
                }
            }
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
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
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
            return try decodeObservationRow(stmt)
        }
    }

    private func decodeObservationRow(_ stmt: OpaquePointer) throws -> LocalObservation {
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
            throw ConsumerAppError.sqlite("Invalid observation row")
        }

        let roadJSON = cString(sqlite3_column_text(stmt, 7)) ?? "[]"
        let roadIDs: [String]
        if let jsonData = roadJSON.data(using: .utf8),
           let decoded = try? JSONDecoder().decode([String].self, from: jsonData) {
            roadIDs = decoded
        } else {
            roadIDs = []
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
            newSpeedKmh: sqliteOptionalInt(stmt, index: 18)
        )
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

    private static func makeOsmChangeXML(wayID: String, maxspeedValue: String) -> String {
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
            <way id="\(xmlEscape(wayID))">
              <tag k="maxspeed" v="\(xmlEscape(maxspeedValue))"/>
            </way>
          </modify>
        </osmChange>
        """
    }

    private static func makeBulkOsmChangeXML(observations: [LocalObservation]) -> String {
        let body = observations.compactMap { observation -> String? in
            guard let wayID = observation.roadCandidateIDs.first,
                  let maxspeedValue = observation.value?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !maxspeedValue.isEmpty else {
                return nil
            }
            return """
                <way id="\(xmlEscape(wayID))">
                  <tag k="maxspeed" v="\(xmlEscape(maxspeedValue))"/>
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
          new_speed_kmh INTEGER
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
        """
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: "ensure local observation schema")
        }
        try ensureObservationColumn(db: db, columnName: "old_speed_kmh", typeDeclaration: "INTEGER")
        try ensureObservationColumn(db: db, columnName: "new_speed_kmh", typeDeclaration: "INTEGER")
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

import Foundation

struct BundleArtifact: Codable, Sendable {
    let file: String
    let bytes: Int64
    let sha256: String
    let url: String?
}

struct V3BundleManifest: Codable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let region: String
    let bundleVersion: String
    let createdAtUTC: String
    let minAppVersion: String
    let db: BundleArtifact
    let dbParts: [BundleArtifact]?
    let deltaIndex: BundleArtifact?

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case region
        case bundleVersion = "bundle_version"
        case createdAtUTC = "created_at_utc"
        case minAppVersion = "min_app_version"
        case db
        case dbParts = "db_parts"
        case deltaIndex = "delta_index"
    }
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

struct SpeedLimitResult {
    let speedLimitKmh: Int?
    let wayID: String?
    let streetName: String?
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

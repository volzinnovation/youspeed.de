import Foundation

enum BenchmarkVariant: String, Codable, CaseIterable {
    case v1
    case v2
    case v3
    case v4
}

enum DistanceMode: String, Codable, CaseIterable {
    case bbox
    case hybrid
    case polyline
}

struct ProbeInput: Codable {
    let lat: Double
    let lon: Double
    let heading: Double
    let repeats: Int
    let searchRadiusM: Double
    let tileRadius: Int
    let maxCandidates: Int
    let topK: Int
    let headingWeight: Double
    let polylineTopN: Int
}

struct ProbeTiming: Codable {
    let avgMs: Double
    let p50Ms: Double
    let minMs: Double
    let maxMs: Double
}

struct BenchmarkReport: Codable {
    let generatedAtUTC: String
    let dbPath: String
    let dbSizeBytes: Int64
    let hasRTreeSupport: Bool
    let hasWayTileTable: Bool
    let input: ProbeInput
    let benchmarkMs: [String: [String: ProbeTiming]]
}

enum BenchmarkError: Error, LocalizedError {
    case missingBundleAsset(String)
    case invalidDB(String)
    case sqliteError(String)
    case ioError(String)

    var errorDescription: String? {
        switch self {
        case .missingBundleAsset(let message): return message
        case .invalidDB(let message): return message
        case .sqliteError(let message): return message
        case .ioError(let message): return message
        }
    }
}

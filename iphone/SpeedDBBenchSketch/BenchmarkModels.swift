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
    case polycontainment
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

enum RouteBenchmarkMode: String, Codable {
    case baseline
    case wayLinks
}

struct RouteSample: Codable {
    let lat: Double
    let lon: Double
    let headingDeg: Double
    let expectedWayID: String
    let radiusM: Double
}

struct RouteScenario: Codable {
    let id: String
    let description: String
    let samples: [RouteSample]
    let speedKmh: Double
    let horizontalAccuracyM: Double

    static let karlsruheL564 = RouteScenario(
        id: "karlsruhe_l564",
        description: "L564 continuity across the Risswasenweg side-road ambiguity",
        samples: [
            RouteSample(lat: 48.77670, lon: 8.40306, headingDeg: 180.0, expectedWayID: "52869774", radiusM: 40.0),
            RouteSample(lat: 48.77632, lon: 8.40311, headingDeg: 180.0, expectedWayID: "1316349759", radiusM: 40.0),
            RouteSample(lat: 48.77600, lon: 8.40300, headingDeg: 180.0, expectedWayID: "206811644", radiusM: 40.0),
            RouteSample(lat: 48.77440, lon: 8.40360, headingDeg: 210.0, expectedWayID: "1220097540", radiusM: 50.0),
        ],
        speedKmh: 45.0,
        horizontalAccuracyM: 5.0
    )

    static let gernsbachTunnelSurface = RouteScenario(
        id: "gernsbach_surface_vs_tunnel",
        description: "Surface sequence near Tunnel Gernsbach must not flip into tunnel mode",
        samples: [
            RouteSample(lat: 48.7656588, lon: 8.3370405, headingDeg: 337.0, expectedWayID: "209270482", radiusM: 80.0),
            RouteSample(lat: 48.7670444, lon: 8.3362234, headingDeg: 336.0, expectedWayID: "1251752493", radiusM: 80.0),
            RouteSample(lat: 48.7671638, lon: 8.3360973, headingDeg: 330.0, expectedWayID: "1252070523", radiusM: 80.0),
            RouteSample(lat: 48.7677662, lon: 8.3357282, headingDeg: 0.0, expectedWayID: "1036502006", radiusM: 80.0),
            RouteSample(lat: 48.7678893, lon: 8.3357290, headingDeg: 336.0, expectedWayID: "1251752490", radiusM: 80.0),
            RouteSample(lat: 48.7681050, lon: 8.3357090, headingDeg: 0.0, expectedWayID: "209270485", radiusM: 80.0),
            RouteSample(lat: 48.7683400, lon: 8.3357540, headingDeg: 0.0, expectedWayID: "1037006038", radiusM: 80.0),
        ],
        speedKmh: 35.0,
        horizontalAccuracyM: 5.0
    )
}

struct RouteScenarioTiming: Codable {
    let avgScenarioMs: Double
    let p50ScenarioMs: Double
    let minScenarioMs: Double
    let maxScenarioMs: Double
    let avgFixMs: Double
}

struct RouteScenarioReport: Codable {
    let scenarioID: String
    let mode: RouteBenchmarkMode
    let repeats: Int
    let timing: RouteScenarioTiming
    let mismatchedWayCount: Int
    let tunnelMismatchCount: Int
}

struct KarlsruheVariantReport: Codable {
    let generatedAtUTC: String
    let dbPath: String
    let dbSizeBytes: Int64
    let mode: RouteBenchmarkMode
    let scenarios: [RouteScenarioReport]
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

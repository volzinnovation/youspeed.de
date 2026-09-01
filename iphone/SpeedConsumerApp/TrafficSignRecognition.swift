import Foundation

// MARK: - Portable model-pack contract

struct TrafficSignModelPackManifest: Codable, Equatable, Sendable {
    enum Pipeline: String, Codable, Sendable {
        case directDetection = "direct_detection"
        case proposalClassification = "proposal_classification"
    }

    enum Platform: String, Codable, Sendable {
        case ios
        case android
        case reference
    }

    enum ArtifactFormat: String, Codable, Sendable {
        case coreml
        case tflite
        case onnx
    }

    enum Precision: String, Codable, Sendable {
        case float32
        case float16
        case int8
        case uint8
    }

    struct Preprocessing: Codable, Equatable, Sendable {
        let version: String
        let inputWidth: Int
        let inputHeight: Int
        let colorSpace: String
        let resize: String
        let orientation: String
    }

    struct Thresholds: Codable, Equatable, Sendable {
        let provisional: Double
        let confirmed: Double
        let unknown: Double
        let confirmationFrames: Int
        let confirmationWindowMs: Int
        let minimumTrackIou: Double
    }

    struct Calibration: Codable, Equatable, Sendable {
        enum Kind: String, Codable, Sendable {
            case none
            case temperatureScaling = "temperature_scaling"
            case isotonic
            case platt
        }

        enum RuntimeOutput: String, Codable, Sendable {
            case rawScore = "raw_score"
            case calibratedConfidence = "calibrated_confidence"
        }

        let kind: Kind
        let revision: String
        let datasetSha256: String
        let calibrated: Bool
        let runtimeOutput: RuntimeOutput
    }

    struct ClassMapping: Codable, Equatable, Sendable {
        let classId: String
        let label: String
        let semantic: TrafficSignSemantic
        let threshold: Double
    }

    struct SourceCheckpoint: Codable, Equatable, Sendable {
        let uri: String
        let revision: String
        let sha256: String
    }

    struct Exporter: Codable, Equatable, Sendable {
        let name: String
        let version: String
        let configuration: String
    }

    struct Parity: Codable, Equatable, Sendable {
        let tolerance: Double
        let measuredMaxAbsDifference: Double
        let passed: Bool
    }

    struct Artifact: Codable, Equatable, Sendable {
        let platform: Platform
        let minimumRuntime: String
        let format: ArtifactFormat
        let precision: Precision
        let inputShape: [Int]
        let outputSchema: String
        let path: String
        let sha256: String
        let sourceCheckpointSha256: String
        let exporter: Exporter
        let calibrationDatasetSha256: String
        let parity: Parity
    }

    struct Component: Codable, Equatable, Sendable {
        let componentId: String
        let sourceCheckpoint: SourceCheckpoint
        let artifacts: [Artifact]
    }

    struct License: Codable, Equatable, Sendable {
        let name: String
        let spdx: String
        let source: String
    }

    struct Signature: Codable, Equatable, Sendable {
        let algorithm: String
        let keyId: String
        let value: String
    }

    let schemaVersion: Int
    let packId: String
    let countries: [String]
    let pipeline: Pipeline
    let taxonomyVersion: String
    let preprocessing: Preprocessing
    let thresholds: Thresholds
    let calibration: Calibration
    let classMapping: [ClassMapping]
    let detector: Component
    let classifier: Component?
    let licenses: [License]
    let minimumAppVersion: String
    let signature: Signature?
}

enum TrafficSignSemanticKind: String, Codable, CaseIterable, Sendable {
    case maximumSpeed = "maximum_speed"
    case zoneStart = "zone_start"
    case zoneEnd = "zone_end"
    case restrictionEnd = "restriction_end"
    case cityEntry = "city_entry"
    case cityExit = "city_exit"
    case pedestrianZoneStart = "pedestrian_zone_start"
    case pedestrianZoneEnd = "pedestrian_zone_end"
    case temporary
    case unknown
}

struct TrafficSignSemantic: Codable, Equatable, Hashable, Sendable {
    let kind: TrafficSignSemanticKind
    let value: Int?
    let unit: String?

    var stableKey: String {
        [kind.rawValue, value.map(String.init) ?? "", unit ?? ""].joined(separator: ":")
    }
}

enum TrafficSignPackValidationError: Error, Equatable, LocalizedError {
    case invalid(String)
    case noCompatibleArtifact(String)

    var errorDescription: String? {
        switch self {
        case .invalid(let detail), .noCompatibleArtifact(let detail):
            return detail
        }
    }
}

enum TrafficSignPackJSON {
    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return encoder
    }
}

enum TrafficSignModelPackValidator {
    static let supportedSchemaVersion = 1
    static let supportedTaxonomyVersion = "tsr-semantic-v1"
    static let supportedPreprocessingVersions: Set<String> = [
        "vision-scale-fit-rgb-v1",
        "litert-letterbox-rgb-v1",
    ]

    static func validate(
        _ manifest: TrafficSignModelPackManifest,
        platform: TrafficSignModelPackManifest.Platform,
        runtimeVersion: String,
        appVersion: String,
        countryCode: String
    ) throws -> TrafficSignModelPackManifest.Artifact {
        guard manifest.schemaVersion == supportedSchemaVersion else {
            throw TrafficSignPackValidationError.invalid("Unsupported TSR pack schema")
        }
        guard !manifest.packId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw TrafficSignPackValidationError.invalid("TSR pack id is empty")
        }
        guard manifest.taxonomyVersion == supportedTaxonomyVersion else {
            throw TrafficSignPackValidationError.invalid("Unsupported TSR taxonomy")
        }
        guard supportedPreprocessingVersions.contains(manifest.preprocessing.version) else {
            throw TrafficSignPackValidationError.invalid("Unsupported TSR preprocessing contract")
        }
        guard manifest.preprocessing.inputWidth > 0,
              manifest.preprocessing.inputHeight > 0,
              ["rgb", "bgr"].contains(manifest.preprocessing.colorSpace),
              ["scale_fit_letterbox", "scale_fill"].contains(manifest.preprocessing.resize),
              manifest.preprocessing.orientation == "normalize_exif_and_mirroring" else {
            throw TrafficSignPackValidationError.invalid("Invalid TSR preprocessing configuration")
        }

        let normalizedCountries = manifest.countries.map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        }
        guard !normalizedCountries.isEmpty,
              normalizedCountries.allSatisfy({ Self.isISOAlpha2($0) }),
              Set(normalizedCountries).count == normalizedCountries.count else {
            throw TrafficSignPackValidationError.invalid("Invalid or duplicate TSR country codes")
        }
        let requestedCountry = countryCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard normalizedCountries.contains(requestedCountry) else {
            throw TrafficSignPackValidationError.invalid("TSR pack does not support the active country")
        }

        guard version(appVersion, isAtLeast: manifest.minimumAppVersion) else {
            throw TrafficSignPackValidationError.invalid("TSR pack requires a newer app version")
        }
        try validate(thresholds: manifest.thresholds)
        try validate(calibration: manifest.calibration)
        try validate(classMapping: manifest.classMapping)
        guard !manifest.licenses.isEmpty,
              manifest.licenses.allSatisfy({
                  !$0.name.isEmpty && !$0.spdx.isEmpty && !$0.source.isEmpty
              }) else {
            throw TrafficSignPackValidationError.invalid("TSR pack license metadata is missing")
        }

        switch manifest.pipeline {
        case .directDetection:
            guard manifest.classifier == nil else {
                throw TrafficSignPackValidationError.invalid("Direct TSR packs cannot declare a classifier")
            }
        case .proposalClassification:
            guard manifest.classifier != nil else {
                throw TrafficSignPackValidationError.invalid("Two-stage TSR packs require a classifier")
            }
        }

        let components = [manifest.detector] + [manifest.classifier].compactMap { $0 }
        for component in components {
            try validate(component: component, calibration: manifest.calibration)
        }

        let expectedFormat: TrafficSignModelPackManifest.ArtifactFormat
        let supportedOutputSchemas: Set<String>
        switch platform {
        case .ios:
            expectedFormat = .coreml
            supportedOutputSchemas = ["vision_recognized_objects_v1"]
        case .android:
            expectedFormat = .tflite
            supportedOutputSchemas = ["yolo_nms_xyxy_scores_classes_v1"]
        case .reference:
            expectedFormat = .onnx
            supportedOutputSchemas = [
                "yolo_nms_xyxy_scores_classes_v1",
                "vision_recognized_objects_v1",
            ]
        }

        let compatible = manifest.detector.artifacts
            .filter {
                $0.platform == platform
                    && $0.format == expectedFormat
                    && supportedOutputSchemas.contains($0.outputSchema)
                    && version(runtimeVersion, isAtLeast: $0.minimumRuntime)
            }
            .sorted { $0.path < $1.path }
        guard let artifact = compatible.first else {
            throw TrafficSignPackValidationError.noCompatibleArtifact(
                "No compatible TSR detector artifact for this runtime"
            )
        }
        return artifact
    }

    private static func validate(
        thresholds: TrafficSignModelPackManifest.Thresholds
    ) throws {
        guard (0...1).contains(thresholds.unknown),
              (0...1).contains(thresholds.provisional),
              (0...1).contains(thresholds.confirmed),
              thresholds.unknown <= thresholds.provisional,
              thresholds.provisional <= thresholds.confirmed,
              thresholds.confirmationFrames >= 2,
              thresholds.confirmationWindowMs > 0,
              (0...1).contains(thresholds.minimumTrackIou) else {
            throw TrafficSignPackValidationError.invalid("Invalid TSR fusion thresholds")
        }
    }

    private static func validate(
        calibration: TrafficSignModelPackManifest.Calibration
    ) throws {
        guard isSHA256(calibration.datasetSha256), !calibration.revision.isEmpty else {
            throw TrafficSignPackValidationError.invalid("Invalid TSR calibration metadata")
        }
        if calibration.calibrated {
            guard calibration.kind != .none,
                  calibration.runtimeOutput == .calibratedConfidence else {
                throw TrafficSignPackValidationError.invalid(
                    "Calibrated TSR confidence must be declared explicitly"
                )
            }
        } else {
            guard calibration.runtimeOutput == .rawScore else {
                throw TrafficSignPackValidationError.invalid(
                    "Uncalibrated TSR output cannot be presented as confidence"
                )
            }
        }
    }

    private static func validate(
        classMapping: [TrafficSignModelPackManifest.ClassMapping]
    ) throws {
        guard !classMapping.isEmpty else {
            throw TrafficSignPackValidationError.invalid("TSR class mapping is empty")
        }
        let ids = classMapping.map(\.classId)
        guard ids.allSatisfy({ !$0.isEmpty }), Set(ids).count == ids.count else {
            throw TrafficSignPackValidationError.invalid("Duplicate or empty TSR class id")
        }
        for mapping in classMapping {
            guard !mapping.label.isEmpty, (0...1).contains(mapping.threshold) else {
                throw TrafficSignPackValidationError.invalid("Invalid TSR class mapping")
            }
            let semantic = mapping.semantic
            switch semantic.kind {
            case .maximumSpeed, .zoneStart, .temporary:
                guard let value = semantic.value,
                      value > 0,
                      ["km/h", "mph"].contains(semantic.unit ?? "") else {
                    throw TrafficSignPackValidationError.invalid(
                        "Speed TSR semantic requires a positive value and unit"
                    )
                }
            case .zoneEnd, .restrictionEnd, .cityEntry, .cityExit,
                    .pedestrianZoneStart, .pedestrianZoneEnd, .unknown:
                guard semantic.value == nil, semantic.unit == nil else {
                    throw TrafficSignPackValidationError.invalid(
                        "Non-speed TSR semantic cannot carry a numeric value"
                    )
                }
            }
        }
    }

    private static func validate(
        component: TrafficSignModelPackManifest.Component,
        calibration: TrafficSignModelPackManifest.Calibration
    ) throws {
        guard !component.componentId.isEmpty,
              !component.sourceCheckpoint.uri.isEmpty,
              !component.sourceCheckpoint.revision.isEmpty,
              isSHA256(component.sourceCheckpoint.sha256),
              !component.artifacts.isEmpty else {
            throw TrafficSignPackValidationError.invalid("Invalid TSR component metadata")
        }
        for artifact in component.artifacts {
            let unsafeParts = artifact.path.split(separator: "/").contains("..")
            guard !artifact.path.isEmpty,
                  !artifact.path.hasPrefix("/"),
                  !unsafeParts,
                  isSHA256(artifact.sha256),
                  isSHA256(artifact.sourceCheckpointSha256),
                  artifact.sourceCheckpointSha256 == component.sourceCheckpoint.sha256,
                  isSHA256(artifact.calibrationDatasetSha256),
                  artifact.calibrationDatasetSha256 == calibration.datasetSha256,
                  artifact.inputShape.count == 3 || artifact.inputShape.count == 4,
                  artifact.inputShape.allSatisfy({ $0 > 0 }),
                  !artifact.outputSchema.isEmpty,
                  !artifact.exporter.name.isEmpty,
                  !artifact.exporter.version.isEmpty,
                  !artifact.exporter.configuration.isEmpty,
                  artifact.parity.passed,
                  artifact.parity.tolerance >= 0,
                  artifact.parity.measuredMaxAbsDifference >= 0,
                  artifact.parity.measuredMaxAbsDifference <= artifact.parity.tolerance else {
                throw TrafficSignPackValidationError.invalid("Invalid TSR runtime artifact metadata")
            }
        }
    }

    static func isSHA256(_ value: String) -> Bool {
        value.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil
    }

    private static func isISOAlpha2(_ value: String) -> Bool {
        value.count == 2 && value.allSatisfy { $0 >= "A" && $0 <= "Z" }
    }

    private static func version(_ actual: String, isAtLeast required: String) -> Bool {
        let actualParts = actual.split(separator: ".").map { Int($0) ?? 0 }
        let requiredParts = required.split(separator: ".").map { Int($0) ?? 0 }
        let count = max(actualParts.count, requiredParts.count)
        for index in 0..<count {
            let lhs = index < actualParts.count ? actualParts[index] : 0
            let rhs = index < requiredParts.count ? requiredParts[index] : 0
            if lhs != rhs { return lhs > rhs }
        }
        return true
    }
}

// MARK: - Normalized inference contract

struct TrafficSignNormalizedRect: Codable, Equatable, Hashable, Sendable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double

    var isValid: Bool {
        x.isFinite && y.isFinite && width.isFinite && height.isFinite
            && x >= 0 && y >= 0 && width > 0 && height > 0
            && x + width <= 1 && y + height <= 1
    }

    var area: Double { width * height }

    func intersectionOverUnion(with other: Self) -> Double {
        guard isValid, other.isValid else { return 0 }
        let left = max(x, other.x)
        let top = max(y, other.y)
        let right = min(x + width, other.x + other.width)
        let bottom = min(y + height, other.y + other.height)
        let intersection = max(0, right - left) * max(0, bottom - top)
        let union = area + other.area - intersection
        return union > 0 ? intersection / union : 0
    }
}

enum TrafficSignRecognitionSource: String, Codable, Sendable {
    case liveFrame = "live_frame"
    case cameraStill = "camera_still"
    case diagnosticImport = "diagnostic_import"
}

enum TrafficSignRecognitionResultState: String, Codable, Sendable {
    case noRecognition = "no_recognition"
    case provisional
    case confirmed
    case unknown
    case unavailable
}

enum TrafficSignConditionState: String, Codable, Sendable {
    case none
    case resolving
    case resolved
    case unresolved
}

enum TrafficSignRestrictionKind: String, Codable, Sendable {
    case weather
    case timeWindow = "time_window"
    case daysOfWeek = "days_of_week"
    case vehicle
    case maxWeight = "max_weight"
    case school
    case resident
    case exception
    case distance
    case direction
    case extent
    case text
    case other
    case unknown
}

struct TrafficSignRestriction: Codable, Equatable, Hashable, Sendable {
    let kind: TrafficSignRestrictionKind
    let normalizedValue: String
    let rawText: String?
    let countrySignCode: String?

    var isValid: Bool {
        !normalizedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

struct TrafficSignDetection: Equatable, Sendable {
    let rawClassId: String
    let rawLabel: String
    let semantic: TrafficSignSemantic
    let rawScore: Double
    let calibratedConfidence: Double?
    let boundingBox: TrafficSignNormalizedRect
    let classThreshold: Double
    let assemblyId: String?
    let conditionState: TrafficSignConditionState
    let restrictions: [TrafficSignRestriction]

    init(
        rawClassId: String,
        rawLabel: String,
        semantic: TrafficSignSemantic,
        rawScore: Double,
        calibratedConfidence: Double?,
        boundingBox: TrafficSignNormalizedRect,
        classThreshold: Double,
        assemblyId: String? = nil,
        conditionState: TrafficSignConditionState = .none,
        restrictions: [TrafficSignRestriction] = []
    ) {
        self.rawClassId = rawClassId
        self.rawLabel = rawLabel
        self.semantic = semantic
        self.rawScore = rawScore
        self.calibratedConfidence = calibratedConfidence
        self.boundingBox = boundingBox
        self.classThreshold = classThreshold
        self.assemblyId = assemblyId
        self.conditionState = conditionState
        self.restrictions = restrictions
    }
}

struct TrafficSignRecognitionCandidate: Codable, Equatable, Sendable {
    let rawClassId: String
    let rawLabel: String
    let semanticKind: String
    let value: Int?
    let unit: String?
    let rawScore: Double
    let calibratedConfidence: Double?
    let boundingBox: TrafficSignNormalizedRect
    let trackId: String?
    let evidenceFrames: Int
    let assemblyId: String?
    let conditionState: TrafficSignConditionState
    let restrictions: [TrafficSignRestriction]

    init(
        rawClassId: String,
        rawLabel: String,
        semanticKind: String,
        value: Int?,
        unit: String?,
        rawScore: Double,
        calibratedConfidence: Double?,
        boundingBox: TrafficSignNormalizedRect,
        trackId: String?,
        evidenceFrames: Int,
        assemblyId: String? = nil,
        conditionState: TrafficSignConditionState = .none,
        restrictions: [TrafficSignRestriction] = []
    ) {
        self.rawClassId = rawClassId
        self.rawLabel = rawLabel
        self.semanticKind = semanticKind
        self.value = value
        self.unit = unit
        self.rawScore = rawScore
        self.calibratedConfidence = calibratedConfidence
        self.boundingBox = boundingBox
        self.trackId = trackId
        self.evidenceFrames = evidenceFrames
        self.assemblyId = assemblyId
        self.conditionState = conditionState
        self.restrictions = restrictions
    }
}

struct TrafficSignRecognitionEvent: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let packId: String
    let artifactSha256: String
    let preprocessingVersion: String
    let source: TrafficSignRecognitionSource
    let frameTimestampUtc: Date
    let state: TrafficSignRecognitionResultState
    let candidate: TrafficSignRecognitionCandidate?
    let roadContext: TrafficSignDetectionContext?
    let latencyMs: Double
    let thermalState: String?

    init(
        schemaVersion: Int,
        packId: String,
        artifactSha256: String,
        preprocessingVersion: String,
        source: TrafficSignRecognitionSource,
        frameTimestampUtc: Date,
        state: TrafficSignRecognitionResultState,
        candidate: TrafficSignRecognitionCandidate?,
        roadContext: TrafficSignDetectionContext? = nil,
        latencyMs: Double,
        thermalState: String?
    ) {
        self.schemaVersion = schemaVersion
        self.packId = packId
        self.artifactSha256 = artifactSha256
        self.preprocessingVersion = preprocessingVersion
        self.source = source
        self.frameTimestampUtc = frameTimestampUtc
        self.state = state
        self.candidate = candidate
        self.roadContext = roadContext
        self.latencyMs = latencyMs
        self.thermalState = thermalState
    }
}

// MARK: - Transient runtime override

struct TrafficSignRuntimeSourceSignature: Codable, Equatable, Hashable, Sendable {
    let osmRevision: String
    let localCorrectionRevision: String?

    var isValid: Bool {
        !osmRevision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (localCorrectionRevision.map {
                !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            } ?? true)
    }
}

enum TrafficSignTravelDirection: String, Codable, Sendable {
    case forward
    case reverse
    case unknown
}

struct TrafficSignDetectionContext: Codable, Equatable, Sendable {
    let wayId: String
    let latitude: Double
    let longitude: Double
    let headingDegrees: Double
    let travelDirection: TrafficSignTravelDirection
    let sourceSignature: TrafficSignRuntimeSourceSignature

    var isValid: Bool {
        !wayId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && latitude.isFinite
            && (-90...90).contains(latitude)
            && longitude.isFinite
            && (-180...180).contains(longitude)
            && headingDegrees.isFinite
            && headingDegrees >= 0
            && headingDegrees < 360
            && sourceSignature.isValid
    }
}

struct TrafficSignTransientSpeedOverride: Codable, Equatable, Sendable {
    let speedKmh: Int
    let detectedAt: Date
    let packId: String
    let trackId: String?
    let context: TrafficSignDetectionContext
}

/// Keeps a confirmed camera value above the local-correction and OSM display
/// layers without mutating either durable source. The caller supplies a stable
/// signature for the map/local inputs used when the sign was detected. A new
/// source revision invalidates the camera value immediately.
struct TrafficSignTransientOverridePolicy: Sendable {
    private(set) var activeOverride: TrafficSignTransientSpeedOverride?

    @discardableResult
    mutating func ingestConfirmedDetection(
        _ event: TrafficSignRecognitionEvent,
        currentSourceSignature: TrafficSignRuntimeSourceSignature
    ) -> Bool {
        guard event.state == .confirmed,
              event.source != .diagnosticImport,
              let context = event.roadContext,
              context.isValid,
              context.sourceSignature == currentSourceSignature else {
            return false
        }
        if let activeOverride,
           event.frameTimestampUtc <= activeOverride.detectedAt {
            return false
        }
        // Any newer confirmed sign supersedes the old camera assertion. Only
        // a numeric maximum-speed candidate creates a replacement override.
        activeOverride = nil
        guard let candidate = event.candidate,
              candidate.semanticKind == TrafficSignSemanticKind.maximumSpeed.rawValue,
              let speedKmh = candidate.value,
              speedKmh > 0,
              candidate.unit == "km/h",
              candidate.boundingBox.isValid,
              candidate.conditionState == .none,
              candidate.restrictions.isEmpty else {
            return true
        }
        activeOverride = TrafficSignTransientSpeedOverride(
            speedKmh: speedKmh,
            detectedAt: event.frameTimestampUtc,
            packId: event.packId,
            trackId: candidate.trackId,
            context: context
        )
        return true
    }

    mutating func resolvedSpeedKmh(
        osmSpeedKmh: Int?,
        localCorrectionSpeedKmh: Int?,
        currentSourceSignature: TrafficSignRuntimeSourceSignature
    ) -> Int? {
        if activeOverride?.context.sourceSignature != currentSourceSignature {
            activeOverride = nil
        }
        return activeOverride?.speedKmh ?? localCorrectionSpeedKmh ?? osmSpeedKmh
    }

    mutating func clear() {
        activeOverride = nil
    }
}

// MARK: - Adaptive latest-frame policy

enum TrafficSignThermalState: String, Codable, Sendable {
    case nominal
    case fair
    case serious
    case critical
}

struct TrafficSignAnalysisConditions: Equatable, Sendable {
    let speedKmh: Double?
    let candidateRecentlySeen: Bool
    let lowPowerMode: Bool
    let thermalState: TrafficSignThermalState
    let appIsActive: Bool
}

enum TrafficSignAnalysisPolicy {
    static func framesPerSecond(for conditions: TrafficSignAnalysisConditions) -> Double? {
        guard conditions.appIsActive, conditions.thermalState != .critical else { return nil }
        if conditions.thermalState == .serious { return 2 }
        if conditions.lowPowerMode { return 2 }

        let base: Double
        switch conditions.speedKmh ?? 0 {
        case 100...:
            base = 8
        case 60...:
            base = 6
        case 30...:
            base = 4
        default:
            base = 2
        }
        let adaptive = conditions.candidateRecentlySeen ? 10 : base
        return conditions.thermalState == .fair ? min(5, adaptive) : min(10, max(2, adaptive))
    }

    static func minimumInterval(for conditions: TrafficSignAnalysisConditions) -> TimeInterval? {
        guard let fps = framesPerSecond(for: conditions), fps > 0 else { return nil }
        return 1 / fps
    }
}

struct TrafficSignLatestFrameThrottle: Sendable {
    private(set) var lastAnalysisAt: TimeInterval?

    mutating func shouldAnalyze(
        timestamp: TimeInterval,
        conditions: TrafficSignAnalysisConditions
    ) -> Bool {
        guard let minimumInterval = TrafficSignAnalysisPolicy.minimumInterval(for: conditions) else {
            return false
        }
        guard let lastAnalysisAt else {
            self.lastAnalysisAt = timestamp
            return true
        }
        guard timestamp >= lastAnalysisAt + minimumInterval else { return false }
        self.lastAnalysisAt = timestamp
        return true
    }
}

// MARK: - Temporal fusion

struct TrafficSignFusionEngine: Sendable {
    private struct StampedDetection: Sendable {
        let timestamp: Date
        let detection: TrafficSignDetection
    }

    private struct Track: Sendable {
        let id: String
        let semanticKey: String
        var evidence: [StampedDetection]
    }

    let packId: String
    let artifactSha256: String
    let preprocessingVersion: String
    let thresholds: TrafficSignModelPackManifest.Thresholds
    let runtimeOutput: TrafficSignModelPackManifest.Calibration.RuntimeOutput
    private var tracks: [Track] = []

    init(
        packId: String,
        artifactSha256: String,
        preprocessingVersion: String,
        thresholds: TrafficSignModelPackManifest.Thresholds,
        runtimeOutput: TrafficSignModelPackManifest.Calibration.RuntimeOutput = .rawScore
    ) {
        self.packId = packId
        self.artifactSha256 = artifactSha256
        self.preprocessingVersion = preprocessingVersion
        self.thresholds = thresholds
        self.runtimeOutput = runtimeOutput
    }

    mutating func ingest(
        detections: [TrafficSignDetection],
        source: TrafficSignRecognitionSource,
        timestamp: Date,
        roadContext: TrafficSignDetectionContext?,
        latencyMs: Double,
        thermalState: TrafficSignThermalState?
    ) -> TrafficSignRecognitionEvent {
        let window = TimeInterval(thresholds.confirmationWindowMs) / 1_000
        let oldestAllowed = timestamp.addingTimeInterval(-window)
        tracks = tracks.compactMap { track in
            var updated = track
            updated.evidence.removeAll { $0.timestamp < oldestAllowed }
            return updated.evidence.isEmpty ? nil : updated
        }

        let eligible = detections
            .filter { detection in
                detection.boundingBox.isValid
                    && effectiveScore(for: detection).map {
                        $0 >= max(thresholds.unknown, detection.classThreshold)
                    } == true
            }
            .sorted { lhs, rhs in
                let lhsScore = effectiveScore(for: lhs) ?? -.infinity
                let rhsScore = effectiveScore(for: rhs) ?? -.infinity
                if lhsScore != rhsScore { return lhsScore > rhsScore }
                return lhs.boundingBox.area > rhs.boundingBox.area
            }

        guard let detection = eligible.first else {
            return event(
                source: source,
                timestamp: timestamp,
                state: .noRecognition,
                candidate: nil,
                roadContext: roadContext,
                latencyMs: latencyMs,
                thermalState: thermalState
            )
        }

        // A delayed live callback is actionable only with the road snapshot
        // taken alongside that frame. Never attach a recognition to whatever
        // way/location happens to be current after inference completes.
        if source == .liveFrame, roadContext?.isValid != true {
            return event(
                source: source,
                timestamp: timestamp,
                state: .noRecognition,
                candidate: nil,
                roadContext: nil,
                latencyMs: latencyMs,
                thermalState: thermalState
            )
        }

        if detection.semantic.kind == .unknown {
            return event(
                source: source,
                timestamp: timestamp,
                state: .unknown,
                candidate: candidate(from: detection, trackID: nil, evidenceFrames: 1),
                roadContext: roadContext,
                latencyMs: latencyMs,
                thermalState: thermalState
            )
        }

        let matchingIndex = tracks.indices.first { index in
            guard tracks[index].semanticKey == detection.semantic.stableKey,
                  let previous = tracks[index].evidence.last?.detection else { return false }
            return previous.boundingBox.intersectionOverUnion(with: detection.boundingBox)
                >= thresholds.minimumTrackIou
        }
        let index: Int
        if let matchingIndex {
            index = matchingIndex
            tracks[index].evidence.append(StampedDetection(timestamp: timestamp, detection: detection))
        } else {
            tracks.append(
                Track(
                    id: UUID().uuidString.lowercased(),
                    semanticKey: detection.semantic.stableKey,
                    evidence: [StampedDetection(timestamp: timestamp, detection: detection)]
                )
            )
            index = tracks.index(before: tracks.endIndex)
        }

        let track = tracks[index]
        let evidenceFrames = track.evidence.count
        let score = effectiveScore(for: detection) ?? -.infinity
        let hasConfirmedEvidence = track.evidence.contains {
            (effectiveScore(for: $0.detection) ?? -.infinity) >= thresholds.confirmed
        }
        let state: TrafficSignRecognitionResultState = evidenceFrames >= thresholds.confirmationFrames
            && hasConfirmedEvidence
            && score >= thresholds.provisional
            ? .confirmed
            : .provisional
        return event(
            source: source,
            timestamp: timestamp,
            state: state,
            candidate: candidate(
                from: detection,
                trackID: track.id,
                evidenceFrames: evidenceFrames
            ),
            roadContext: roadContext,
            latencyMs: latencyMs,
            thermalState: thermalState
        )
    }

    private func candidate(
        from detection: TrafficSignDetection,
        trackID: String?,
        evidenceFrames: Int
    ) -> TrafficSignRecognitionCandidate {
        TrafficSignRecognitionCandidate(
            rawClassId: detection.rawClassId,
            rawLabel: detection.rawLabel,
            semanticKind: detection.semantic.kind.rawValue,
            value: detection.semantic.value,
            unit: detection.semantic.unit,
            rawScore: detection.rawScore,
            calibratedConfidence: detection.calibratedConfidence,
            boundingBox: detection.boundingBox,
            trackId: trackID,
            evidenceFrames: evidenceFrames,
            assemblyId: detection.assemblyId,
            conditionState: detection.conditionState,
            restrictions: detection.restrictions
        )
    }

    private func effectiveScore(for detection: TrafficSignDetection) -> Double? {
        switch runtimeOutput {
        case .rawScore:
            return detection.rawScore
        case .calibratedConfidence:
            return detection.calibratedConfidence
        }
    }

    private func event(
        source: TrafficSignRecognitionSource,
        timestamp: Date,
        state: TrafficSignRecognitionResultState,
        candidate: TrafficSignRecognitionCandidate?,
        roadContext: TrafficSignDetectionContext?,
        latencyMs: Double,
        thermalState: TrafficSignThermalState?
    ) -> TrafficSignRecognitionEvent {
        TrafficSignRecognitionEvent(
            schemaVersion: 1,
            packId: packId,
            artifactSha256: artifactSha256,
            preprocessingVersion: preprocessingVersion,
            source: source,
            frameTimestampUtc: timestamp,
            state: state,
            candidate: candidate,
            roadContext: roadContext,
            latencyMs: max(0, latencyMs),
            thermalState: thermalState?.rawValue
        )
    }
}

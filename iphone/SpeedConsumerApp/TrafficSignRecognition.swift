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

    enum SignRole: String, Codable, Sendable {
        case primarySign = "primary_sign"
        case supplementaryPlate = "supplementary_plate"
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
        let signRole: SignRole
        let restriction: TrafficSignRestriction?

        init(
            classId: String,
            label: String,
            semantic: TrafficSignSemantic,
            threshold: Double,
            signRole: SignRole = .primarySign,
            restriction: TrafficSignRestriction? = nil
        ) {
            self.classId = classId
            self.label = label
            self.semantic = semantic
            self.threshold = threshold
            self.signRole = signRole
            self.restriction = restriction
        }

        private enum CodingKeys: String, CodingKey {
            case classId
            case label
            case semantic
            case threshold
            case signRole
            case restriction
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            classId = try container.decode(String.self, forKey: .classId)
            label = try container.decode(String.self, forKey: .label)
            semantic = try container.decode(TrafficSignSemantic.self, forKey: .semantic)
            threshold = try container.decode(Double.self, forKey: .threshold)
            signRole = try container.decodeIfPresent(SignRole.self, forKey: .signRole)
                ?? .primarySign
            restriction = try container.decodeIfPresent(
                TrafficSignRestriction.self,
                forKey: .restriction
            )
        }

        func encode(to encoder: Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(classId, forKey: .classId)
            try container.encode(label, forKey: .label)
            try container.encode(semantic, forKey: .semantic)
            try container.encode(threshold, forKey: .threshold)
            if signRole != .primarySign {
                try container.encode(signRole, forKey: .signRole)
            }
            try container.encodeIfPresent(restriction, forKey: .restriction)
        }
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

    struct Lineage: Codable, Equatable, Sendable {
        let sourceManifestSha256: String
        let datasetInventorySha256s: [String]
        let trainingRunId: String
        let trainingRunSha256: String
        let evaluationReportSha256: String
        let parityReportSha256: String

        // Foundation's generic snake-case decoder turns the plural wire key
        // `dataset_inventory_sha256s` into `datasetInventorySha256S` (capital
        // trailing S), which does not match the idiomatic Swift property name.
        // Keep the portable wire contract stable while handling that acronym
        // edge case explicitly. Encoding uses the normal camel-case spelling
        // so `.convertToSnakeCase` still emits `dataset_inventory_sha256s`.
        private enum DecodingKeys: String, CodingKey {
            case sourceManifestSha256
            case datasetInventorySha256s = "datasetInventorySha256S"
            case trainingRunId
            case trainingRunSha256
            case evaluationReportSha256
            case parityReportSha256
        }

        private enum EncodingKeys: String, CodingKey {
            case sourceManifestSha256
            case datasetInventorySha256s
            case trainingRunId
            case trainingRunSha256
            case evaluationReportSha256
            case parityReportSha256
        }

        init(
            sourceManifestSha256: String,
            datasetInventorySha256s: [String],
            trainingRunId: String,
            trainingRunSha256: String,
            evaluationReportSha256: String,
            parityReportSha256: String
        ) {
            self.sourceManifestSha256 = sourceManifestSha256
            self.datasetInventorySha256s = datasetInventorySha256s
            self.trainingRunId = trainingRunId
            self.trainingRunSha256 = trainingRunSha256
            self.evaluationReportSha256 = evaluationReportSha256
            self.parityReportSha256 = parityReportSha256
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: DecodingKeys.self)
            sourceManifestSha256 = try container.decode(
                String.self,
                forKey: .sourceManifestSha256
            )
            datasetInventorySha256s = try container.decode(
                [String].self,
                forKey: .datasetInventorySha256s
            )
            trainingRunId = try container.decode(String.self, forKey: .trainingRunId)
            trainingRunSha256 = try container.decode(String.self, forKey: .trainingRunSha256)
            evaluationReportSha256 = try container.decode(
                String.self,
                forKey: .evaluationReportSha256
            )
            parityReportSha256 = try container.decode(
                String.self,
                forKey: .parityReportSha256
            )
        }

        func encode(to encoder: Encoder) throws {
            var container = encoder.container(keyedBy: EncodingKeys.self)
            try container.encode(sourceManifestSha256, forKey: .sourceManifestSha256)
            try container.encode(datasetInventorySha256s, forKey: .datasetInventorySha256s)
            try container.encode(trainingRunId, forKey: .trainingRunId)
            try container.encode(trainingRunSha256, forKey: .trainingRunSha256)
            try container.encode(evaluationReportSha256, forKey: .evaluationReportSha256)
            try container.encode(parityReportSha256, forKey: .parityReportSha256)
        }
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
    let lineage: Lineage
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
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            if let date = iso8601Formatter(fractionalSeconds: true).date(from: value)
                ?? iso8601Formatter(fractionalSeconds: false).date(from: value) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: try decoder.singleValueContainer(),
                debugDescription: "Invalid ISO-8601 date: \(value)"
            )
        }
        return decoder
    }

    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(
                iso8601Formatter(fractionalSeconds: true).string(from: date)
            )
        }
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return encoder
    }

    private static func iso8601Formatter(
        fractionalSeconds: Bool
    ) -> ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = fractionalSeconds
            ? [.withInternetDateTime, .withFractionalSeconds]
            : [.withInternetDateTime]
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return formatter
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
        try validate(lineage: manifest.lineage)

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

        return try compatibleArtifact(
            in: manifest.detector,
            platform: platform,
            expectedFormat: expectedFormat,
            supportedOutputSchemas: supportedOutputSchemas,
            runtimeVersion: runtimeVersion,
            componentName: "detector"
        )
    }

    static func compatibleClassifierArtifact(
        in manifest: TrafficSignModelPackManifest,
        platform: TrafficSignModelPackManifest.Platform,
        runtimeVersion: String
    ) throws -> TrafficSignModelPackManifest.Artifact {
        guard manifest.pipeline == .proposalClassification,
              let classifier = manifest.classifier else {
            throw TrafficSignPackValidationError.noCompatibleArtifact(
                "This TSR pack does not contain a classifier"
            )
        }
        let expectedFormat: TrafficSignModelPackManifest.ArtifactFormat
        let supportedOutputSchemas: Set<String>
        switch platform {
        case .ios:
            expectedFormat = .coreml
            supportedOutputSchemas = ["vision_classifications_v1"]
        case .android:
            expectedFormat = .tflite
            supportedOutputSchemas = ["classification_scores_v1"]
        case .reference:
            expectedFormat = .onnx
            supportedOutputSchemas = [
                "classification_scores_v1",
                "vision_classifications_v1",
            ]
        }
        return try compatibleArtifact(
            in: classifier,
            platform: platform,
            expectedFormat: expectedFormat,
            supportedOutputSchemas: supportedOutputSchemas,
            runtimeVersion: runtimeVersion,
            componentName: "classifier"
        )
    }

    private static func compatibleArtifact(
        in component: TrafficSignModelPackManifest.Component,
        platform: TrafficSignModelPackManifest.Platform,
        expectedFormat: TrafficSignModelPackManifest.ArtifactFormat,
        supportedOutputSchemas: Set<String>,
        runtimeVersion: String,
        componentName: String
    ) throws -> TrafficSignModelPackManifest.Artifact {
        let compatible = component.artifacts
            .filter {
                $0.platform == platform
                    && $0.format == expectedFormat
                    && supportedOutputSchemas.contains($0.outputSchema)
                    && version(runtimeVersion, isAtLeast: $0.minimumRuntime)
            }
            .sorted { $0.path < $1.path }
        guard let artifact = compatible.first else {
            throw TrafficSignPackValidationError.noCompatibleArtifact(
                "No compatible TSR \(componentName) artifact for this runtime"
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
            switch mapping.signRole {
            case .primarySign:
                guard mapping.restriction == nil else {
                    throw TrafficSignPackValidationError.invalid(
                        "Primary TSR classes cannot declare a supplementary restriction"
                    )
                }
            case .supplementaryPlate:
                guard mapping.semantic.kind == .unknown,
                      mapping.semantic.value == nil,
                      mapping.semantic.unit == nil,
                      mapping.restriction?.isValid == true else {
                    throw TrafficSignPackValidationError.invalid(
                        "Supplementary TSR classes require an unknown primary semantic and typed restriction"
                    )
                }
            }
            let semantic = mapping.semantic
            switch semantic.kind {
            case .maximumSpeed, .zoneStart, .temporary:
                guard let value = semantic.value,
                      (5...200).contains(value),
                      ["km/h", "mph"].contains(semantic.unit ?? "") else {
                    throw TrafficSignPackValidationError.invalid(
                        "Speed TSR semantic requires a 5...200 value and unit"
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

    private static func validate(
        lineage: TrafficSignModelPackManifest.Lineage
    ) throws {
        guard isSHA256(lineage.sourceManifestSha256),
              !lineage.datasetInventorySha256s.isEmpty,
              Set(lineage.datasetInventorySha256s).count
                == lineage.datasetInventorySha256s.count,
              lineage.datasetInventorySha256s.allSatisfy(isSHA256),
              !lineage.trainingRunId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              isSHA256(lineage.trainingRunSha256),
              isSHA256(lineage.evaluationReportSha256),
              isSHA256(lineage.parityReportSha256) else {
            throw TrafficSignPackValidationError.invalid("Invalid TSR training lineage")
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
    let detectorRawScore: Double?
    let detectorCalibratedConfidence: Double?
    let classifierRawScore: Double?
    let classifierCalibratedConfidence: Double?
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
        detectorRawScore: Double? = nil,
        detectorCalibratedConfidence: Double? = nil,
        classifierRawScore: Double? = nil,
        classifierCalibratedConfidence: Double? = nil,
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
        self.detectorRawScore = detectorRawScore
        self.detectorCalibratedConfidence = detectorCalibratedConfidence
        self.classifierRawScore = classifierRawScore
        self.classifierCalibratedConfidence = classifierCalibratedConfidence
        self.boundingBox = boundingBox
        self.classThreshold = classThreshold
        self.assemblyId = assemblyId
        self.conditionState = conditionState
        self.restrictions = restrictions
    }
}

enum TrafficSignSpatialAssembly {
    struct ClassifiedDetection: Equatable, Sendable {
        let detection: TrafficSignDetection
        let signRole: TrafficSignModelPackManifest.SignRole
        let restriction: TrafficSignRestriction?
        let detectorRawScore: Double?
        let detectorCalibratedConfidence: Double?
        let classifierRawScore: Double?
        let classifierCalibratedConfidence: Double?
        let auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2]

        init(
            detection: TrafficSignDetection,
            signRole: TrafficSignModelPackManifest.SignRole,
            restriction: TrafficSignRestriction?,
            detectorRawScore: Double? = nil,
            detectorCalibratedConfidence: Double? = nil,
            classifierRawScore: Double? = nil,
            classifierCalibratedConfidence: Double? = nil,
            auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2] = []
        ) {
            self.detection = detection
            self.signRole = signRole
            self.restriction = restriction
            self.detectorRawScore = detectorRawScore
            self.detectorCalibratedConfidence = detectorCalibratedConfidence
            self.classifierRawScore = classifierRawScore
            self.classifierCalibratedConfidence = classifierCalibratedConfidence
            self.auxiliaryEvidence = auxiliaryEvidence
        }
    }

    struct GroupedAssembly: Equatable, Sendable {
        let detection: TrafficSignDetection
        let primary: ClassifiedDetection
        let supplementaryPlates: [ClassifiedDetection]
    }

    struct Geometry: Equatable, Sendable {
        let maximumVerticalGap: Double
        let permittedBoxOverlap: Double
        let minimumHorizontalOverlapFraction: Double

        init(
            maximumVerticalGap: Double = 0.18,
            permittedBoxOverlap: Double = 0.03,
            minimumHorizontalOverlapFraction: Double = 0.25
        ) {
            self.maximumVerticalGap = maximumVerticalGap
            self.permittedBoxOverlap = permittedBoxOverlap
            self.minimumHorizontalOverlapFraction = minimumHorizontalOverlapFraction
        }
    }

    static func assemble(
        _ classified: [ClassifiedDetection],
        assemblyIDPrefix: String = UUID().uuidString.lowercased(),
        geometry: Geometry = Geometry()
    ) -> [TrafficSignDetection] {
        assembleWithMembers(
            classified,
            assemblyIDPrefix: assemblyIDPrefix,
            geometry: geometry
        ).map(\.detection)
    }

    /// Preserves the exact primary/plate members used by the existing spatial
    /// assembly so a second consumer can emit per-stage QA without repeating or
    /// approximating the association algorithm.
    static func assembleWithMembers(
        _ classified: [ClassifiedDetection],
        assemblyIDPrefix: String = UUID().uuidString.lowercased(),
        geometry: Geometry = Geometry()
    ) -> [GroupedAssembly] {
        let primaries = classified.filter { $0.signRole == .primarySign }
        let plates = classified.filter { $0.signRole == .supplementaryPlate }
        var assignments: [Int: [ClassifiedDetection]] = [:]
        var assignedPlateCount = 0

        for plate in plates {
            let best = primaries.indices.compactMap { index -> (Int, Double)? in
                associationCost(
                    primary: primaries[index].detection.boundingBox,
                    plate: plate.detection.boundingBox,
                    geometry: geometry
                ).map { (index, $0) }
            }.min { lhs, rhs in
                lhs.1 == rhs.1 ? lhs.0 < rhs.0 : lhs.1 < rhs.1
            }
            if let best {
                assignments[best.0, default: []].append(plate)
                assignedPlateCount += 1
            }
        }
        let hasUnassignedPlate = assignedPlateCount < plates.count

        return primaries.enumerated().map { index, primary in
            let assigned = assignments[index, default: []]
                .sorted { $0.detection.boundingBox.y < $1.detection.boundingBox.y }
            let restrictions = assigned.compactMap(\.restriction)
            let conditionState: TrafficSignConditionState
            if assigned.isEmpty {
                // A detected white plate that narrowly misses the association
                // geometry is still evidence that an apparently numeric sign
                // may be conditional. Suppress an unconditional override until
                // a later frame resolves the assembly.
                conditionState = hasUnassignedPlate ? .unresolved : .none
            } else if restrictions.count != assigned.count
                        || restrictions.contains(where: { $0.kind == .unknown }) {
                conditionState = .unresolved
            } else {
                conditionState = .resolved
            }
            let source = primary.detection
            let detection = TrafficSignDetection(
                rawClassId: source.rawClassId,
                rawLabel: source.rawLabel,
                semantic: source.semantic,
                rawScore: source.rawScore,
                calibratedConfidence: source.calibratedConfidence,
                detectorRawScore: primary.detectorRawScore,
                detectorCalibratedConfidence: primary.detectorCalibratedConfidence,
                classifierRawScore: primary.classifierRawScore,
                classifierCalibratedConfidence: primary.classifierCalibratedConfidence,
                boundingBox: source.boundingBox,
                classThreshold: source.classThreshold,
                assemblyId: "\(assemblyIDPrefix)-assembly-\(index + 1)",
                conditionState: conditionState,
                restrictions: restrictions
            )
            return GroupedAssembly(
                detection: detection,
                primary: primary,
                supplementaryPlates: assigned
            )
        }
    }

    private static func associationCost(
        primary: TrafficSignNormalizedRect,
        plate: TrafficSignNormalizedRect,
        geometry: Geometry
    ) -> Double? {
        guard primary.isValid, plate.isValid else { return nil }
        let verticalGap = plate.y - (primary.y + primary.height)
        guard verticalGap >= -geometry.permittedBoxOverlap,
              verticalGap <= geometry.maximumVerticalGap else { return nil }
        let overlap = max(
            0,
            min(primary.x + primary.width, plate.x + plate.width)
                - max(primary.x, plate.x)
        )
        let denominator = min(primary.width, plate.width)
        guard denominator > 0,
              overlap / denominator >= geometry.minimumHorizontalOverlapFraction else {
            return nil
        }
        let centerDistance = abs(
            (primary.x + primary.width / 2) - (plate.x + plate.width / 2)
        )
        return max(0, verticalGap) + centerDistance
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
    let detectorRawScore: Double?
    let detectorCalibratedConfidence: Double?
    let classifierRawScore: Double?
    let classifierCalibratedConfidence: Double?
    let assemblyConfidence: Double?
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
        detectorRawScore: Double? = nil,
        detectorCalibratedConfidence: Double? = nil,
        classifierRawScore: Double? = nil,
        classifierCalibratedConfidence: Double? = nil,
        assemblyConfidence: Double? = nil,
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
        self.detectorRawScore = detectorRawScore
        self.detectorCalibratedConfidence = detectorCalibratedConfidence
        self.classifierRawScore = classifierRawScore
        self.classifierCalibratedConfidence = classifierCalibratedConfidence
        self.assemblyConfidence = assemblyConfidence
        self.boundingBox = boundingBox
        self.trackId = trackId
        self.evidenceFrames = evidenceFrames
        self.assemblyId = assemblyId
        self.conditionState = conditionState
        self.restrictions = restrictions
    }
}

struct TrafficSignModelComponentLineage: Codable, Equatable, Sendable {
    let role: String
    let artifactSHA256: String
    let preprocessingVersion: String
    let calibrationID: String

    var isValid: Bool {
        ["proposal_detector", "semantic_classifier", "direct_detector"].contains(role)
            && artifactSHA256.range(
                of: "^[0-9a-fA-F]{64}$",
                options: .regularExpression
            ) != nil
            && !preprocessingVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !calibrationID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

struct TrafficSignRecognitionEvent: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let packId: String
    let artifactSha256: String
    let preprocessingVersion: String
    let modelComponents: [TrafficSignModelComponentLineage]
    let frameId: String?
    let driveSessionId: String?
    let analysisEligible: Bool?
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
        modelComponents: [TrafficSignModelComponentLineage] = [],
        frameId: String? = nil,
        driveSessionId: String? = nil,
        analysisEligible: Bool? = true,
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
        self.modelComponents = modelComponents
        self.frameId = frameId
        self.driveSessionId = driveSessionId
        self.analysisEligible = analysisEligible
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
    let bundleSHA256: String?

    init(
        osmRevision: String,
        localCorrectionRevision: String?,
        bundleSHA256: String? = nil
    ) {
        self.osmRevision = osmRevision
        self.localCorrectionRevision = localCorrectionRevision
        self.bundleSHA256 = bundleSHA256
    }

    var isValid: Bool {
        !osmRevision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (localCorrectionRevision.map {
                !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            } ?? true)
    }

    var hasVerifiedBundleLineage: Bool {
        guard let bundleSHA256 else { return false }
        return bundleSHA256.range(
            of: "^[0-9a-fA-F]{64}$",
            options: .regularExpression
        ) != nil
    }

    private enum CodingKeys: String, CodingKey {
        case osmRevision
        case localCorrectionRevision
        case bundleSHA256
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        osmRevision = try container.decode(String.self, forKey: .osmRevision)
        localCorrectionRevision = try container.decodeIfPresent(
            String.self,
            forKey: .localCorrectionRevision
        )
        bundleSHA256 = try container.decodeIfPresent(String.self, forKey: .bundleSHA256)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(osmRevision, forKey: .osmRevision)
        if let localCorrectionRevision {
            try container.encode(localCorrectionRevision, forKey: .localCorrectionRevision)
        } else {
            try container.encodeNil(forKey: .localCorrectionRevision)
        }
        try container.encodeIfPresent(bundleSHA256, forKey: .bundleSHA256)
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
    let routeContinuityAvailable: Bool
    let routeRelationMemberships: [TrafficSignRouteRelationMembership]
    let traversalEpoch: UInt64
    let matchedWayStable: Bool

    init(
        wayId: String,
        latitude: Double,
        longitude: Double,
        headingDegrees: Double,
        travelDirection: TrafficSignTravelDirection,
        sourceSignature: TrafficSignRuntimeSourceSignature,
        routeContinuityAvailable: Bool = false,
        routeRelationMemberships: [TrafficSignRouteRelationMembership] = [],
        traversalEpoch: UInt64 = 0,
        matchedWayStable: Bool = false
    ) {
        self.wayId = wayId
        self.latitude = latitude
        self.longitude = longitude
        self.headingDegrees = headingDegrees
        self.travelDirection = travelDirection
        self.sourceSignature = sourceSignature
        self.routeContinuityAvailable = routeContinuityAvailable
        self.routeRelationMemberships = routeRelationMemberships
        self.traversalEpoch = traversalEpoch
        self.matchedWayStable = matchedWayStable
    }

    private enum CodingKeys: String, CodingKey {
        case wayId
        case latitude
        case longitude
        case headingDegrees
        case travelDirection
        case sourceSignature
        case routeContinuityAvailable
        case routeRelationMemberships
        case traversalEpoch
        case matchedWayStable
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        wayId = try container.decode(String.self, forKey: .wayId)
        latitude = try container.decode(Double.self, forKey: .latitude)
        longitude = try container.decode(Double.self, forKey: .longitude)
        headingDegrees = try container.decode(Double.self, forKey: .headingDegrees)
        travelDirection = try container.decode(TrafficSignTravelDirection.self, forKey: .travelDirection)
        sourceSignature = try container.decode(TrafficSignRuntimeSourceSignature.self, forKey: .sourceSignature)
        routeContinuityAvailable = try container.decodeIfPresent(Bool.self, forKey: .routeContinuityAvailable) ?? false
        routeRelationMemberships = try container.decodeIfPresent(
            [TrafficSignRouteRelationMembership].self,
            forKey: .routeRelationMemberships
        ) ?? []
        traversalEpoch = try container.decodeIfPresent(UInt64.self, forKey: .traversalEpoch) ?? 0
        matchedWayStable = try container.decodeIfPresent(Bool.self, forKey: .matchedWayStable) ?? false
    }

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

enum TrafficSignRuntimeDeploymentPolicy {
    static let bundledBootstrapShadowPackId = "de-panoramax-bootstrap-shadow-v1"
    /// Live override activation is an explicit code-owned allowlist. Shipping
    /// or renaming a model pack can never enable speed overrides by accident.
    private static let speedOverrideEnabledPackIDs: Set<String> = []

    static func isShadowOnly(packId: String) -> Bool {
        !speedOverrideEnabledPackIDs.contains(packId)
    }
}

/// Keeps a confirmed camera value above the local-correction and OSM display
/// layers without mutating either durable source. The exact frame context is
/// retained as provenance; a new way, travel direction, or map/local source
/// revision invalidates the camera value immediately.
struct TrafficSignTransientOverridePolicy: Sendable {
    private(set) var activeOverride: TrafficSignTransientSpeedOverride?

    /// Pack/event v2 is shadow-only in M0. Even a confirmed numeric event is
    /// QA evidence and cannot create, replace, or clear the effective speed.
    /// Gate metadata in a pack is never interpreted as runtime authorization.
    @discardableResult
    mutating func ingestConfirmedDetection(
        _ event: TrafficSignRecognitionEventV2,
        currentSourceSignature: TrafficSignRuntimeSourceSignature
    ) -> Bool {
        _ = event
        _ = currentSourceSignature
        return false
    }

    @discardableResult
    mutating func ingestConfirmedDetection(
        _ event: TrafficSignRecognitionEvent,
        currentSourceSignature: TrafficSignRuntimeSourceSignature
    ) -> Bool {
        guard event.state == .confirmed,
              event.source != .diagnosticImport,
              let context = event.roadContext,
              context.isValid,
              context.travelDirection != .unknown,
              context.sourceSignature == currentSourceSignature else {
            return false
        }
        if let activeOverride,
           event.frameTimestampUtc <= activeOverride.detectedAt {
            return false
        }
        // Any newer confirmed sign supersedes the old camera assertion. Only
        // an unconditional numeric speed semantic creates a replacement.
        activeOverride = nil
        guard let candidate = event.candidate,
              [
                  TrafficSignSemanticKind.maximumSpeed.rawValue,
                  TrafficSignSemanticKind.zoneStart.rawValue,
                  TrafficSignSemanticKind.temporary.rawValue,
              ].contains(candidate.semanticKind),
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
        currentContext: TrafficSignDetectionContext?
    ) -> Int? {
        if let activeOverride {
            guard let currentContext,
                  currentContext.isValid,
                  activeOverride.context.wayId == currentContext.wayId,
                  activeOverride.context.travelDirection == currentContext.travelDirection,
                  activeOverride.context.sourceSignature == currentContext.sourceSignature else {
                self.activeOverride = nil
                return localCorrectionSpeedKmh ?? osmSpeedKmh
            }
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
        var roadKey: RoadKey?
        var evidence: [StampedDetection]
    }

    private struct RoadKey: Equatable, Sendable {
        let traversalEpoch: UInt64
        let bundleRevision: String

        init?(_ context: TrafficSignDetectionContext?) {
            guard let context, context.isValid else { return nil }
            traversalEpoch = context.traversalEpoch
            bundleRevision = context.sourceSignature.bundleRevision
        }
    }

    let packId: String
    let artifactSha256: String
    let preprocessingVersion: String
    let modelComponents: [TrafficSignModelComponentLineage]
    let thresholds: TrafficSignModelPackManifest.Thresholds
    let runtimeOutput: TrafficSignModelPackManifest.Calibration.RuntimeOutput
    private var tracks: [Track] = []

    init(
        packId: String,
        artifactSha256: String,
        preprocessingVersion: String,
        thresholds: TrafficSignModelPackManifest.Thresholds,
        runtimeOutput: TrafficSignModelPackManifest.Calibration.RuntimeOutput = .rawScore,
        modelComponents: [TrafficSignModelComponentLineage] = []
    ) {
        self.packId = packId
        self.artifactSha256 = artifactSha256
        self.preprocessingVersion = preprocessingVersion
        self.modelComponents = modelComponents
        self.thresholds = thresholds
        self.runtimeOutput = runtimeOutput
    }

    mutating func reset() {
        tracks.removeAll(keepingCapacity: true)
    }

    mutating func ingest(
        detections: [TrafficSignDetection],
        source: TrafficSignRecognitionSource,
        timestamp: Date,
        roadContext: TrafficSignDetectionContext?,
        latencyMs: Double,
        thermalState: TrafficSignThermalState?,
        frameID: String? = nil,
        driveSessionID: String? = nil
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

        // Supplementary plates and unsupported classifier labels are retained
        // as QA evidence, but must not hide a supported speed sign from the
        // same frame merely because their raw score is higher.
        guard let detection = eligible.first(where: { $0.semantic.kind != .unknown })
                ?? eligible.first else {
            return event(
                source: source,
                timestamp: timestamp,
                state: .noRecognition,
                candidate: nil,
                roadContext: roadContext,
                latencyMs: latencyMs,
                thermalState: thermalState,
                frameID: frameID,
                driveSessionID: driveSessionID
            )
        }

        // Visual tracking may continue through a temporary matcher gap, but
        // the absent road context remains attached as nil. The passage
        // finalizer will never activate or persist from that frame alone.

        if detection.semantic.kind == .unknown {
            return event(
                source: source,
                timestamp: timestamp,
                state: .unknown,
                candidate: candidate(from: detection, trackID: nil, evidenceFrames: 1),
                roadContext: roadContext,
                latencyMs: latencyMs,
                thermalState: thermalState,
                frameID: frameID,
                driveSessionID: driveSessionID
            )
        }

        let roadKey = RoadKey(roadContext)
        let matchingIndex = tracks.indices.first { index in
            guard tracks[index].semanticKey == detection.semantic.stableKey,
                  (tracks[index].roadKey == nil || roadKey == nil || tracks[index].roadKey == roadKey),
                  let previous = tracks[index].evidence.last?.detection else { return false }
            return previous.boundingBox.intersectionOverUnion(with: detection.boundingBox)
                >= thresholds.minimumTrackIou
        }
        let index: Int
        if let matchingIndex {
            index = matchingIndex
            tracks[index].evidence.append(StampedDetection(timestamp: timestamp, detection: detection))
            if tracks[index].roadKey == nil, let roadKey {
                tracks[index].roadKey = roadKey
            }
        } else {
            tracks.append(
                Track(
                    id: UUID().uuidString.lowercased(),
                    semanticKey: detection.semantic.stableKey,
                    roadKey: roadKey,
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
        var seenRestrictions = Set<TrafficSignRestriction>()
        let fusedRestrictions = track.evidence
            .flatMap(\.detection.restrictions)
            .filter { seenRestrictions.insert($0).inserted }
        let fusedConditionState: TrafficSignConditionState
        let observedConditionStates = track.evidence.map(\.detection.conditionState)
        if observedConditionStates.contains(.unresolved) {
            fusedConditionState = .unresolved
        } else if observedConditionStates.contains(.resolving) {
            fusedConditionState = .resolving
        } else if observedConditionStates.contains(.resolved) || !fusedRestrictions.isEmpty {
            fusedConditionState = .resolved
        } else {
            fusedConditionState = .none
        }
        let fusedAssemblyID = track.evidence.reversed().compactMap {
            $0.detection.assemblyId
        }.first
        return event(
            source: source,
            timestamp: timestamp,
            state: state,
            candidate: candidate(
                from: detection,
                trackID: track.id,
                evidenceFrames: evidenceFrames,
                assemblyId: fusedAssemblyID,
                conditionState: fusedConditionState,
                restrictions: fusedRestrictions
            ),
            roadContext: roadContext,
            latencyMs: latencyMs,
            thermalState: thermalState,
            frameID: frameID,
            driveSessionID: driveSessionID
        )
    }

    private func candidate(
        from detection: TrafficSignDetection,
        trackID: String?,
        evidenceFrames: Int,
        assemblyId: String? = nil,
        conditionState: TrafficSignConditionState? = nil,
        restrictions: [TrafficSignRestriction]? = nil
    ) -> TrafficSignRecognitionCandidate {
        TrafficSignRecognitionCandidate(
            rawClassId: detection.rawClassId,
            rawLabel: detection.rawLabel,
            semanticKind: detection.semantic.kind.rawValue,
            value: detection.semantic.value,
            unit: detection.semantic.unit,
            rawScore: detection.rawScore,
            calibratedConfidence: detection.calibratedConfidence,
            detectorRawScore: detection.detectorRawScore,
            detectorCalibratedConfidence: detection.detectorCalibratedConfidence,
            classifierRawScore: detection.classifierRawScore,
            classifierCalibratedConfidence: detection.classifierCalibratedConfidence,
            assemblyConfidence: [
                detection.detectorCalibratedConfidence,
                detection.classifierCalibratedConfidence,
            ].compactMap { $0 }.min() ?? detection.calibratedConfidence,
            boundingBox: detection.boundingBox,
            trackId: trackID,
            evidenceFrames: evidenceFrames,
            assemblyId: assemblyId ?? detection.assemblyId,
            conditionState: conditionState ?? detection.conditionState,
            restrictions: restrictions ?? detection.restrictions
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
        thermalState: TrafficSignThermalState?,
        frameID: String?,
        driveSessionID: String?
    ) -> TrafficSignRecognitionEvent {
        TrafficSignRecognitionEvent(
            schemaVersion: 1,
            packId: packId,
            artifactSha256: artifactSha256,
            preprocessingVersion: preprocessingVersion,
            modelComponents: modelComponents,
            frameId: frameID,
            driveSessionId: driveSessionID,
            analysisEligible: true,
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

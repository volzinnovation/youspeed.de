import Foundation

// MARK: - Pack/event v2 shadow boundary

enum TrafficSignExecutionModeV2: String, Codable, Sendable {
    case shadow
}

enum TrafficSignEvidenceOriginV2: String, Codable, Sendable {
    case runtimeInference = "runtime_inference"
    case reviewedExpectation = "reviewed_expectation"
}

enum TrafficSignOverrideDispositionV2: String, Codable, Sendable {
    case shadowEvidenceOnly = "shadow_evidence_only"
}

enum TrafficSignQADispositionV2: String, Codable, Sendable {
    case emit
}

enum TrafficSignInputSourceV2: String, Codable, Sendable {
    case liveFrame = "live_frame"
    case cameraStill = "camera_still"
    case diagnosticImport = "diagnostic_import"
    case panoramaxReplay = "panoramax_replay"
}

enum TrafficSignRuntimeArtifactFormatV2: String, Codable, Sendable {
    case onnx
    case coreml
    case litert
}

enum TrafficSignAssociationPolicyV2: String, Codable, Sendable {
    case stableObservationHintThenUniqueSemanticRoadDirection =
        "stable_observation_hint_then_unique_semantic_road_direction"
}

enum TrafficSignPlateReadabilityV2: String, Codable, Sendable {
    case readable
    case unreadable
}

enum TrafficSignRestrictionTransitionV2: String, Codable, Sendable {
    case none
    case preservedUnreadable = "preserved_unreadable"
    case upgradedFromLaterReadableEvidence = "upgraded_from_later_readable_evidence"
}

enum TrafficSignDiagnosticCaptureStatusV2: String, Codable, Sendable {
    case notRequested = "not_requested"
    case requested
    case persisted
    case failed
}

enum TrafficSignDiagnosticReasonV2: String, Codable, Sendable {
    case shadowCandidate = "shadow_candidate"
    case uncertainPrimary = "uncertain_primary"
    case unreadableSupplementaryPlate = "unreadable_supplementary_plate"
    case temporalUpgrade = "temporal_upgrade"
    case manualQA = "manual_qa"
}

enum TrafficSignPrimarySemanticKindV2: String, Codable, Sendable {
    case maximumSpeed = "maximum_speed"
    case maximumSpeedEnd = "maximum_speed_end"
    case zoneStart = "zone_start"
    case zoneEnd = "zone_end"
    case restrictionEnd = "restriction_end"
    case unknown
}

struct TrafficSignPrimarySemanticV2: Codable, Equatable, Hashable, Sendable {
    let kind: TrafficSignPrimarySemanticKindV2
    let value: Int?
    let unit: String?

    var isValid: Bool {
        switch kind {
        case .maximumSpeed, .zoneStart:
            return value.map({ $0 > 0 }) == true
                && (unit == "km/h" || unit == "mph")
        case .maximumSpeedEnd, .zoneEnd, .restrictionEnd:
            return value == nil && unit == nil
        case .unknown:
            return value == nil && unit == nil
        }
    }

    private enum CodingKeys: String, CodingKey {
        case kind
        case value
        case unit
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(kind, forKey: .kind)
        if let value { try container.encode(value, forKey: .value) }
        else { try container.encodeNil(forKey: .value) }
        if let unit { try container.encode(unit, forKey: .unit) }
        else { try container.encodeNil(forKey: .unit) }
    }
}

struct TrafficSignRestrictionV2: Codable, Equatable, Hashable, Sendable {
    let kind: TrafficSignRestrictionKind
    let normalizedValue: String
    let distanceM: Int?
    let extentM: Int?
    let rawText: String?
    let countrySignCode: String?

    init(
        kind: TrafficSignRestrictionKind,
        normalizedValue: String,
        distanceM: Int? = nil,
        extentM: Int? = nil,
        rawText: String? = nil,
        countrySignCode: String? = nil
    ) {
        self.kind = kind
        self.normalizedValue = normalizedValue
        self.distanceM = distanceM
        self.extentM = extentM
        self.rawText = rawText
        self.countrySignCode = countrySignCode
    }

    var isValid: Bool {
        guard !normalizedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              rawText.map({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) ?? true,
              countrySignCode.map({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) ?? true else {
            return false
        }
        switch kind {
        case .distance:
            return distanceM.map({ $0 > 0 }) == true && extentM == nil
        case .extent:
            return extentM.map({ $0 > 0 }) == true && distanceM == nil
        default:
            return distanceM == nil && extentM == nil
        }
    }
}

struct TrafficSignShadowStageIdentityV2: Codable, Equatable, Sendable {
    let componentId: String
    let artifactId: String
    let artifactSha256: String
    let artifactFormat: TrafficSignRuntimeArtifactFormatV2
    let preprocessingVersion: String
    let calibrationId: String
    let calibrationPassed: Bool

    var isValid: Bool {
        !componentId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !artifactId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && artifactSha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil
            && !preprocessingVersion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !calibrationId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

/// A deliberately small, runtime-only v2 projection for a verified v1 model
/// pack. It does not pretend that an off-the-shelf bootstrap pack satisfies the
/// full training/release pack-v2 schema. Instead it binds the exact mobile
/// artifacts and the two preprocessing/calibration contracts needed to emit
/// honest event-v2 shadow evidence.
struct TrafficSignShadowPackProjectionV2: Codable, Equatable, Sendable {
    struct ExecutionPolicy: Codable, Equatable, Sendable {
        let mode: TrafficSignExecutionModeV2
        let overrideEligible: Bool
    }

    struct Preprocessing: Codable, Equatable, Sendable {
        let version: String
        let inputWidth: Int
        let inputHeight: Int
        let colorSpace: String
        let resize: String
        let orientation: String
    }

    struct Calibration: Codable, Equatable, Sendable {
        let id: String
        let datasetSha256: String
        let passed: Bool
        let runtimeOutput: String
        let expectedCalibrationError: Double?
        let maximumExpectedCalibrationError: Double?
        let evidencePath: String?
        let evidenceSha256: String?

        var isValid: Bool {
            guard !id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  datasetSha256.range(
                    of: "^[a-f0-9]{64}$",
                    options: .regularExpression
                  ) != nil,
                  ["raw_score", "calibrated_confidence"].contains(runtimeOutput) else {
                return false
            }
            return true
        }
    }

    struct Stage: Codable, Equatable, Sendable {
        let componentId: String
        let artifactId: String
        let artifactPath: String
        let artifactSha256: String
        let artifactFormat: TrafficSignRuntimeArtifactFormatV2
        let preprocessing: Preprocessing
        let calibration: Calibration
    }

    struct Thresholds: Codable, Equatable, Sendable {
        let classifierConfirmed: Double
        let confirmationFrames: Int
        let temporalWindowMs: Int
        let minimumTrackIou: Double
    }

    struct Association: Codable, Equatable, Sendable {
        let policy: TrafficSignAssociationPolicyV2
        let stableObservationHintCanOverrideIou: Bool
        let fallbackRequiresUniqueCandidate: Bool
    }

    let schemaVersion: Int
    let sourcePackId: String
    let packId: String
    let taxonomyVersion: String
    let executionPolicy: ExecutionPolicy
    let detector: Stage
    let classifier: Stage
    let thresholds: Thresholds
    let association: Association

    func configuration(
        sourceManifest: TrafficSignModelPackManifest,
        detectorArtifact: TrafficSignModelPackManifest.Artifact,
        classifierArtifact: TrafficSignModelPackManifest.Artifact
    ) throws -> TrafficSignShadowRuntimeConfigurationV2 {
        guard schemaVersion == 2,
              sourcePackId == sourceManifest.packId,
              sourceManifest.pipeline == .proposalClassification,
              taxonomyVersion == "tsr-semantic-v2",
              executionPolicy.mode == .shadow,
              !executionPolicy.overrideEligible,
              stage(
                  detector,
                  binds: sourceManifest.detector,
                  artifact: detectorArtifact,
                  expectedResize: "scale_fit_letterbox"
              ),
              let sourceClassifier = sourceManifest.classifier,
              stage(
                  classifier,
                  binds: sourceClassifier,
                  artifact: classifierArtifact,
                  expectedResize: "scale_fill"
              ),
              detector.artifactId != classifier.artifactId,
              detector.artifactSha256 != classifier.artifactSha256,
              detector.preprocessing.version != classifier.preprocessing.version,
              detector.calibration.id != classifier.calibration.id else {
            throw TrafficSignShadowRuntimeError.invalidConfiguration(
                "The TSR v2 shadow projection does not bind the verified two-stage pack."
            )
        }

        let configuration = TrafficSignShadowRuntimeConfigurationV2(
            packId: packId,
            taxonomyVersion: taxonomyVersion,
            initialMode: executionPolicy.mode,
            overrideEligible: executionPolicy.overrideEligible,
            detector: identity(for: detector),
            classifier: identity(for: classifier),
            classifierConfirmedThreshold: thresholds.classifierConfirmed,
            confirmationFrames: thresholds.confirmationFrames,
            minimumTrackIou: thresholds.minimumTrackIou,
            temporalWindowMs: thresholds.temporalWindowMs,
            associationPolicy: association.policy,
            stableObservationHintCanOverrideIou:
                association.stableObservationHintCanOverrideIou,
            fallbackRequiresUniqueCandidate: association.fallbackRequiresUniqueCandidate
        )
        guard configuration.isValid else {
            throw TrafficSignShadowRuntimeError.invalidConfiguration(
                "The TSR v2 shadow projection contains an invalid runtime contract."
            )
        }
        return configuration
    }

    private func stage(
        _ stage: Stage,
        binds component: TrafficSignModelPackManifest.Component,
        artifact: TrafficSignModelPackManifest.Artifact,
        expectedResize: String
    ) -> Bool {
        let shape = artifact.inputShape
        guard shape.count >= 3 else { return false }
        let expectedHeight = shape[shape.count - 2]
        let expectedWidth = shape[shape.count - 1]
        return stage.componentId == component.componentId
            && stage.artifactPath == artifact.path
            && stage.artifactSha256 == artifact.sha256
            && stage.artifactFormat == .coreml
            && artifact.format == .coreml
            && stage.preprocessing.inputWidth == expectedWidth
            && stage.preprocessing.inputHeight == expectedHeight
            && stage.preprocessing.colorSpace == "rgb"
            && stage.preprocessing.resize == expectedResize
            && stage.preprocessing.orientation == "normalize_exif_and_mirroring"
            && !stage.preprocessing.version.isEmpty
            && stage.calibration.datasetSha256 == artifact.calibrationDatasetSha256
            && stage.calibration.isValid
    }

    private func identity(for stage: Stage) -> TrafficSignShadowStageIdentityV2 {
        TrafficSignShadowStageIdentityV2(
            componentId: stage.componentId,
            artifactId: stage.artifactId,
            artifactSha256: stage.artifactSha256,
            artifactFormat: stage.artifactFormat,
            preprocessingVersion: stage.preprocessing.version,
            calibrationId: stage.calibration.id,
            calibrationPassed: stage.calibration.passed
        )
    }
}

struct TrafficSignShadowRuntimeConfigurationV2: Equatable, Sendable {
    let packId: String
    let taxonomyVersion: String
    let initialMode: TrafficSignExecutionModeV2
    let overrideEligible: Bool
    let detector: TrafficSignShadowStageIdentityV2
    let classifier: TrafficSignShadowStageIdentityV2
    let classifierConfirmedThreshold: Double
    let confirmationFrames: Int
    let minimumTrackIou: Double
    let temporalWindowMs: Int
    let associationPolicy: TrafficSignAssociationPolicyV2
    let stableObservationHintCanOverrideIou: Bool
    let fallbackRequiresUniqueCandidate: Bool

    var isValid: Bool {
        !packId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && taxonomyVersion == "tsr-semantic-v2"
            && initialMode == .shadow
            && !overrideEligible
            && detector.isValid
            && classifier.isValid
            && detector.componentId != classifier.componentId
            && detector.artifactId != classifier.artifactId
            && detector.artifactSha256 != classifier.artifactSha256
            && detector.artifactFormat == classifier.artifactFormat
            && detector.artifactFormat != .onnx
            && detector.preprocessingVersion != classifier.preprocessingVersion
            && detector.calibrationId != classifier.calibrationId
            && classifierConfirmedThreshold.isFinite
            && (0...1).contains(classifierConfirmedThreshold)
            && confirmationFrames >= 2
            && minimumTrackIou.isFinite
            && (0...1).contains(minimumTrackIou)
            && temporalWindowMs > 0
            && associationPolicy == .stableObservationHintThenUniqueSemanticRoadDirection
            && stableObservationHintCanOverrideIou
            && fallbackRequiresUniqueCandidate
    }
}

struct TrafficSignFrameV2: Codable, Equatable, Sendable {
    let frameId: String
    let timestampUtc: Date
    let width: Int
    let height: Int

    var isValid: Bool {
        !frameId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && width > 0
            && height > 0
    }
}

struct TrafficSignStageScoreV2: Codable, Equatable, Sendable {
    let rawScore: Double
    let calibratedConfidence: Double?

    var isValid: Bool {
        rawScore.isFinite
            && (calibratedConfidence.map { $0.isFinite && (0...1).contains($0) } ?? true)
    }

    private enum CodingKeys: String, CodingKey {
        case rawScore
        case calibratedConfidence
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(rawScore, forKey: .rawScore)
        if let calibratedConfidence {
            try container.encode(calibratedConfidence, forKey: .calibratedConfidence)
        } else {
            try container.encodeNil(forKey: .calibratedConfidence)
        }
    }
}

/// Evidence from an on-device Vision helper that is not one of the two model
/// stages declared in `stage_runs`.
enum TrafficSignAuxiliaryEvidenceSourceV2: String, Codable, Sendable {
    case appleVisionTextRecognition = "apple_vision_text_recognition"
    case appleVisionRectangleDetection = "apple_vision_rectangle_detection"
}

struct TrafficSignAuxiliaryEvidenceV2: Codable, Equatable, Sendable {
    let source: TrafficSignAuxiliaryEvidenceSourceV2
    let rawScore: Double
    let rawText: String?
    let candidateRestriction: TrafficSignRestrictionV2?

    init(
        source: TrafficSignAuxiliaryEvidenceSourceV2,
        rawScore: Double,
        rawText: String? = nil,
        candidateRestriction: TrafficSignRestrictionV2? = nil
    ) {
        self.source = source
        self.rawScore = rawScore
        self.rawText = rawText
        self.candidateRestriction = candidateRestriction
    }

    var isValid: Bool {
        guard rawScore.isFinite, (0...1).contains(rawScore) else { return false }
        switch source {
        case .appleVisionTextRecognition:
            return rawText.map {
                !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            } == true && candidateRestriction?.isValid == true
        case .appleVisionRectangleDetection:
            return rawText == nil && candidateRestriction == nil
        }
    }
}

struct TrafficSignStageRunV2: Codable, Equatable, Sendable {
    let componentId: String
    let artifactId: String
    let artifactSha256: String
    let artifactFormat: TrafficSignRuntimeArtifactFormatV2
    let preprocessingVersion: String
    let calibrationId: String
    let invoked: Bool
    let latencyMs: Double
}

struct TrafficSignStageRunsV2: Codable, Equatable, Sendable {
    let detector: TrafficSignStageRunV2
    let classifier: TrafficSignStageRunV2
}

struct TrafficSignPrimaryEvidenceV2: Codable, Equatable, Sendable {
    let objectId: String
    let boundingBox: TrafficSignNormalizedRect
    let detectorScore: TrafficSignStageScoreV2?
    let classifierScore: TrafficSignStageScoreV2?
    let classId: String
    let semantic: TrafficSignPrimarySemanticV2

    private enum CodingKeys: String, CodingKey {
        case objectId
        case boundingBox
        case detectorScore
        case classifierScore
        case classId
        case semantic
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(objectId, forKey: .objectId)
        try container.encode(boundingBox, forKey: .boundingBox)
        if let detectorScore { try container.encode(detectorScore, forKey: .detectorScore) }
        else { try container.encodeNil(forKey: .detectorScore) }
        if let classifierScore { try container.encode(classifierScore, forKey: .classifierScore) }
        else { try container.encodeNil(forKey: .classifierScore) }
        try container.encode(classId, forKey: .classId)
        try container.encode(semantic, forKey: .semantic)
    }
}

struct TrafficSignSupplementaryPlateEvidenceV2: Codable, Equatable, Sendable {
    let objectId: String
    let boundingBox: TrafficSignNormalizedRect
    let detectorScore: TrafficSignStageScoreV2?
    let classifierScore: TrafficSignStageScoreV2?
    let auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2]?
    let classId: String?
    let readability: TrafficSignPlateReadabilityV2
    let restriction: TrafficSignRestrictionV2?

    var isValid: Bool {
        guard !objectId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              boundingBox.isValid,
              detectorScore?.isValid ?? true,
              auxiliaryEvidence?.allSatisfy(\.isValid) ?? true else {
            return false
        }
        switch readability {
        case .unreadable:
            return (classifierScore?.isValid ?? true) && classId == nil && restriction == nil
        case .readable:
            return (classifierScore?.isValid ?? true)
                && classId.map { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } == true
                && restriction?.isValid == true
        }
    }

    private enum CodingKeys: String, CodingKey {
        case objectId
        case boundingBox
        case detectorScore
        case classifierScore
        case auxiliaryEvidence
        case classId
        case readability
        case restriction
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(objectId, forKey: .objectId)
        try container.encode(boundingBox, forKey: .boundingBox)
        if let detectorScore { try container.encode(detectorScore, forKey: .detectorScore) }
        else { try container.encodeNil(forKey: .detectorScore) }
        if let classifierScore { try container.encode(classifierScore, forKey: .classifierScore) }
        else { try container.encodeNil(forKey: .classifierScore) }
        if let auxiliaryEvidence {
            try container.encode(auxiliaryEvidence, forKey: .auxiliaryEvidence)
        } else {
            try container.encodeNil(forKey: .auxiliaryEvidence)
        }
        if let classId { try container.encode(classId, forKey: .classId) }
        else { try container.encodeNil(forKey: .classId) }
        try container.encode(readability, forKey: .readability)
        if let restriction { try container.encode(restriction, forKey: .restriction) }
        else { try container.encodeNil(forKey: .restriction) }
    }
}

struct TrafficSignTemporalEvidenceV2: Codable, Equatable, Sendable {
    let evidenceFrameCount: Int
    let priorEventId: String?
    let restrictionTransition: TrafficSignRestrictionTransitionV2

    private enum CodingKeys: String, CodingKey {
        case evidenceFrameCount
        case priorEventId
        case restrictionTransition
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(evidenceFrameCount, forKey: .evidenceFrameCount)
        if let priorEventId { try container.encode(priorEventId, forKey: .priorEventId) }
        else { try container.encodeNil(forKey: .priorEventId) }
        try container.encode(restrictionTransition, forKey: .restrictionTransition)
    }
}

struct TrafficSignAssemblyV2: Codable, Equatable, Sendable {
    let assemblyId: String
    let physicalSignTrackId: String
    let primary: TrafficSignPrimaryEvidenceV2
    let supplementaryPlates: [TrafficSignSupplementaryPlateEvidenceV2]
    let conditionState: TrafficSignConditionState
    let temporalEvidence: TrafficSignTemporalEvidenceV2
}

struct TrafficSignDiagnosticCaptureV2: Codable, Equatable, Sendable {
    let status: TrafficSignDiagnosticCaptureStatusV2
    let reasons: [TrafficSignDiagnosticReasonV2]
    let captureId: String?

    private enum CodingKeys: String, CodingKey {
        case status
        case reasons
        case captureId
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(status, forKey: .status)
        try container.encode(reasons, forKey: .reasons)
        if let captureId { try container.encode(captureId, forKey: .captureId) }
        else { try container.encodeNil(forKey: .captureId) }
    }
}

struct TrafficSignRecognitionEventV2: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let eventId: String
    let packId: String
    let taxonomyVersion: String
    let evidenceOrigin: TrafficSignEvidenceOriginV2
    let executionMode: TrafficSignExecutionModeV2
    let overrideEligible: Bool
    let overrideDisposition: TrafficSignOverrideDispositionV2
    let qaDisposition: TrafficSignQADispositionV2
    let source: TrafficSignInputSourceV2
    let frame: TrafficSignFrameV2
    let stageRuns: TrafficSignStageRunsV2
    let state: TrafficSignRecognitionResultState
    let assemblies: [TrafficSignAssemblyV2]
    let roadContext: TrafficSignDetectionContext?
    let diagnosticCapture: TrafficSignDiagnosticCaptureV2
    let thermalState: String?
}

// MARK: - Backend-neutral input and capture hooks

struct TrafficSignTwoStagePrimaryObservationV2: Equatable, Sendable {
    let objectId: String
    let classId: String
    let semantic: TrafficSignPrimarySemanticV2
    let boundingBox: TrafficSignNormalizedRect
    let detectorScore: Double
    let detectorCalibratedConfidence: Double?
    let classifierRawScore: Double
    let classifierCalibratedConfidence: Double?
    let classifierThreshold: Double
}

struct TrafficSignTwoStagePlateObservationV2: Equatable, Sendable {
    let objectId: String
    let classId: String?
    let boundingBox: TrafficSignNormalizedRect
    let detectorScore: Double?
    let detectorCalibratedConfidence: Double?
    let classifierRawScore: Double?
    let classifierCalibratedConfidence: Double?
    let auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2]
    let classifierThreshold: Double
    let readability: TrafficSignPlateReadabilityV2
    let restriction: TrafficSignRestrictionV2?

    init(
        objectId: String,
        classId: String?,
        boundingBox: TrafficSignNormalizedRect,
        detectorScore: Double?,
        detectorCalibratedConfidence: Double?,
        classifierRawScore: Double?,
        classifierCalibratedConfidence: Double?,
        auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2] = [],
        classifierThreshold: Double,
        readability: TrafficSignPlateReadabilityV2,
        restriction: TrafficSignRestrictionV2?
    ) {
        self.objectId = objectId
        self.classId = classId
        self.boundingBox = boundingBox
        self.detectorScore = detectorScore
        self.detectorCalibratedConfidence = detectorCalibratedConfidence
        self.classifierRawScore = classifierRawScore
        self.classifierCalibratedConfidence = classifierCalibratedConfidence
        self.auxiliaryEvidence = auxiliaryEvidence
        self.classifierThreshold = classifierThreshold
        self.readability = readability
        self.restriction = restriction
    }
}

struct TrafficSignTwoStageAssemblyObservationV2: Equatable, Sendable {
    let assemblyId: String
    let stableObservationHint: String?
    let primary: TrafficSignTwoStagePrimaryObservationV2
    let supplementaryPlates: [TrafficSignTwoStagePlateObservationV2]

    init(
        assemblyId: String,
        stableObservationHint: String? = nil,
        primary: TrafficSignTwoStagePrimaryObservationV2,
        supplementaryPlates: [TrafficSignTwoStagePlateObservationV2]
    ) {
        self.assemblyId = assemblyId
        self.stableObservationHint = stableObservationHint
        self.primary = primary
        self.supplementaryPlates = supplementaryPlates
    }
}

struct TrafficSignShadowFrameInputV2: Equatable, Sendable {
    let eventId: String
    let evidenceOrigin: TrafficSignEvidenceOriginV2
    let source: TrafficSignInputSourceV2
    let frame: TrafficSignFrameV2
    let roadContext: TrafficSignDetectionContext
    let requestedState: TrafficSignRecognitionResultState
    let detectorLatencyMs: Double
    let classifierInvoked: Bool
    let classifierLatencyMs: Double
    let assemblies: [TrafficSignTwoStageAssemblyObservationV2]
    let diagnosticReasons: [TrafficSignDiagnosticReasonV2]
    let thermalState: String?

    init(
        eventId: String,
        evidenceOrigin: TrafficSignEvidenceOriginV2 = .runtimeInference,
        source: TrafficSignInputSourceV2,
        frame: TrafficSignFrameV2,
        roadContext: TrafficSignDetectionContext,
        requestedState: TrafficSignRecognitionResultState,
        detectorLatencyMs: Double,
        classifierInvoked: Bool,
        classifierLatencyMs: Double,
        assemblies: [TrafficSignTwoStageAssemblyObservationV2],
        diagnosticReasons: [TrafficSignDiagnosticReasonV2] = [],
        thermalState: String? = nil
    ) {
        self.eventId = eventId
        self.evidenceOrigin = evidenceOrigin
        self.source = source
        self.frame = frame
        self.roadContext = roadContext
        self.requestedState = requestedState
        self.detectorLatencyMs = detectorLatencyMs
        self.classifierInvoked = classifierInvoked
        self.classifierLatencyMs = classifierLatencyMs
        self.assemblies = assemblies
        self.diagnosticReasons = diagnosticReasons
        self.thermalState = thermalState
    }
}

struct TrafficSignDiagnosticCaptureRequestV2: Equatable, Sendable {
    let eventId: String
    let frame: TrafficSignFrameV2
    let roadContext: TrafficSignDetectionContext
    let reasons: [TrafficSignDiagnosticReasonV2]
}

struct TrafficSignDiagnosticCaptureOutcomeV2: Equatable, Sendable {
    let status: TrafficSignDiagnosticCaptureStatusV2
    let captureId: String?

    init(status: TrafficSignDiagnosticCaptureStatusV2, captureId: String? = nil) {
        self.status = status
        self.captureId = captureId
    }
}

protocol TrafficSignDiagnosticCaptureSinkV2: AnyObject, Sendable {
    func requestCapture(
        _ request: TrafficSignDiagnosticCaptureRequestV2
    ) throws -> TrafficSignDiagnosticCaptureOutcomeV2
}

protocol TrafficSignQAEventSinkV2: AnyObject, Sendable {
    func emit(_ event: TrafficSignRecognitionEventV2)
}

/// App-private persistence for shadow QA. Events and optional diagnostic JPEGs
/// are grouped by the recorder's immutable capture-session UUID. This store is
/// intentionally unrelated to Panoramax upload state: nothing written here is
/// remotely uploadable without a separate, future review/export flow.
final class TrafficSignShadowEvidenceStoreV2: TrafficSignDiagnosticCaptureSinkV2,
        TrafficSignQAEventSinkV2, @unchecked Sendable {
    typealias JPEGProvider = @Sendable () throws -> Data

    private struct PendingFrame {
        let captureGroupId: String
        let diagnosticCaptureEnabled: Bool
        let jpegProvider: JPEGProvider
    }

    private struct SessionMetadata: Codable {
        let schemaVersion: Int
        let captureGroupId: String
        let createdAtUtc: Date
        let storageScope: String
        let diagnosticImagesEnabled: Bool
        let exportApproved: Bool
        let redactionStatus: String
    }

    private let rootURL: URL
    private let fileManager: FileManager
    private let minimumCaptureInterval: TimeInterval
    private let maximumCapturesPerSession: Int
    private let lock = NSLock()
    private var pendingByEventId: [String: PendingFrame] = [:]
    private var captureCountByGroup: [String: Int] = [:]
    private var lastCaptureAtByGroup: [String: Date] = [:]
    private var deletedGroups = Set<String>()
    private(set) var lastPersistenceError: String?

    init(
        rootURL: URL? = nil,
        fileManager: FileManager = .default,
        minimumCaptureInterval: TimeInterval = 2,
        maximumCapturesPerSession: Int = 120
    ) throws {
        self.fileManager = fileManager
        self.minimumCaptureInterval = max(0, minimumCaptureInterval)
        self.maximumCapturesPerSession = max(1, maximumCapturesPerSession)
        if let rootURL {
            self.rootURL = rootURL.standardizedFileURL
        } else {
            let applicationSupport = try fileManager.url(
                for: .applicationSupportDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            self.rootURL = applicationSupport
                .appendingPathComponent("YouSpeed", isDirectory: true)
                .appendingPathComponent("TrafficSignQA", isDirectory: true)
                .appendingPathComponent("v2", isDirectory: true)
        }
        try prepareDirectory(self.rootURL)
    }

    func stageFrame(
        eventId: String,
        captureGroupId: String,
        diagnosticCaptureEnabled: Bool,
        jpegProvider: @escaping JPEGProvider
    ) {
        guard Self.isSafeIdentifier(eventId), Self.isSafeIdentifier(captureGroupId) else { return }
        lock.lock()
        defer { lock.unlock() }
        guard !deletedGroups.contains(captureGroupId) else { return }
        pendingByEventId[eventId] = PendingFrame(
            captureGroupId: captureGroupId,
            diagnosticCaptureEnabled: diagnosticCaptureEnabled,
            jpegProvider: jpegProvider
        )
        do {
            try prepareSessionIfNeeded(
                captureGroupId: captureGroupId,
                diagnosticCaptureEnabled: diagnosticCaptureEnabled
            )
        } catch {
            lastPersistenceError = error.localizedDescription
        }
    }

    func unstageFrame(eventId: String) {
        lock.lock()
        pendingByEventId.removeValue(forKey: eventId)
        lock.unlock()
    }

    func requestCapture(
        _ request: TrafficSignDiagnosticCaptureRequestV2
    ) throws -> TrafficSignDiagnosticCaptureOutcomeV2 {
        lock.lock()
        guard let pending = pendingByEventId[request.eventId],
              !deletedGroups.contains(pending.captureGroupId) else {
            lock.unlock()
            return TrafficSignDiagnosticCaptureOutcomeV2(status: .notRequested)
        }
        guard pending.diagnosticCaptureEnabled else {
            lock.unlock()
            return TrafficSignDiagnosticCaptureOutcomeV2(status: .notRequested)
        }
        let count = captureCount(for: pending.captureGroupId)
        let tooSoon = lastCaptureAtByGroup[pending.captureGroupId].map {
            request.frame.timestampUtc.timeIntervalSince($0) < minimumCaptureInterval
        } ?? false
        guard count < maximumCapturesPerSession, !tooSoon else {
            lock.unlock()
            return TrafficSignDiagnosticCaptureOutcomeV2(status: .requested)
        }
        lock.unlock()

        let jpeg = try pending.jpegProvider()
        guard !jpeg.isEmpty else {
            return TrafficSignDiagnosticCaptureOutcomeV2(status: .failed)
        }

        lock.lock()
        defer { lock.unlock() }
        guard !deletedGroups.contains(pending.captureGroupId),
              pendingByEventId[request.eventId] != nil else {
            return TrafficSignDiagnosticCaptureOutcomeV2(status: .notRequested)
        }
        let captureId = UUID().uuidString.lowercased()
        do {
            let capturesURL = sessionURL(pending.captureGroupId)
                .appendingPathComponent("captures", isDirectory: true)
            try prepareDirectory(capturesURL)
            let destination = capturesURL.appendingPathComponent(
                "\(captureId).jpg",
                isDirectory: false
            )
            try jpeg.write(to: destination, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            var mutableDestination = destination
            try? mutableDestination.setResourceValues(values)
            captureCountByGroup[pending.captureGroupId] = count + 1
            lastCaptureAtByGroup[pending.captureGroupId] = request.frame.timestampUtc
            return TrafficSignDiagnosticCaptureOutcomeV2(
                status: .persisted,
                captureId: captureId
            )
        } catch {
            lastPersistenceError = error.localizedDescription
            return TrafficSignDiagnosticCaptureOutcomeV2(status: .failed)
        }
    }

    func emit(_ event: TrafficSignRecognitionEventV2) {
        lock.lock()
        defer { lock.unlock() }
        guard let pending = pendingByEventId[event.eventId],
              !deletedGroups.contains(pending.captureGroupId) else { return }
        do {
            let session = sessionURL(pending.captureGroupId)
            try prepareSessionIfNeeded(
                captureGroupId: pending.captureGroupId,
                diagnosticCaptureEnabled: pending.diagnosticCaptureEnabled
            )
            let eventURL = session.appendingPathComponent("events.ndjson", isDirectory: false)
            var data = try Self.eventEncoder().encode(event)
            data.append(0x0A)
            if !fileManager.fileExists(atPath: eventURL.path) {
                try Data().write(
                    to: eventURL,
                    options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
                )
            }
            let handle = try FileHandle(forWritingTo: eventURL)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try handle.synchronize()
            lastPersistenceError = nil
        } catch {
            if let captureId = event.diagnosticCapture.captureId,
               Self.isSafeIdentifier(captureId) {
                let captureURL = sessionURL(pending.captureGroupId)
                    .appendingPathComponent("captures", isDirectory: true)
                    .appendingPathComponent("\(captureId).jpg", isDirectory: false)
                try? fileManager.removeItem(at: captureURL)
            }
            lastPersistenceError = error.localizedDescription
        }
    }

    /// Deleting a local QA group also creates a process-local tombstone so a
    /// late inference from the just-deleted recorder session cannot recreate it.
    @discardableResult
    func deleteCaptureGroup(_ captureGroupId: String) -> Bool {
        guard Self.isSafeIdentifier(captureGroupId) else { return false }
        lock.lock()
        defer { lock.unlock() }
        deletedGroups.insert(captureGroupId)
        pendingByEventId = pendingByEventId.filter { $0.value.captureGroupId != captureGroupId }
        captureCountByGroup.removeValue(forKey: captureGroupId)
        lastCaptureAtByGroup.removeValue(forKey: captureGroupId)
        let url = sessionURL(captureGroupId)
        guard fileManager.fileExists(atPath: url.path) else { return true }
        do {
            try fileManager.removeItem(at: url)
            return true
        } catch {
            lastPersistenceError = error.localizedDescription
            return false
        }
    }

    func eventsURL(captureGroupId: String) -> URL? {
        guard Self.isSafeIdentifier(captureGroupId) else { return nil }
        return sessionURL(captureGroupId).appendingPathComponent("events.ndjson")
    }

    func captureURL(captureGroupId: String, captureId: String) -> URL? {
        guard Self.isSafeIdentifier(captureGroupId), Self.isSafeIdentifier(captureId) else {
            return nil
        }
        return sessionURL(captureGroupId)
            .appendingPathComponent("captures", isDirectory: true)
            .appendingPathComponent("\(captureId).jpg", isDirectory: false)
    }

    private func prepareSessionIfNeeded(
        captureGroupId: String,
        diagnosticCaptureEnabled: Bool
    ) throws {
        let session = sessionURL(captureGroupId)
        try prepareDirectory(session)
        let metadataURL = session.appendingPathComponent("session.json", isDirectory: false)
        if fileManager.fileExists(atPath: metadataURL.path) {
            // A recorder session can start before the user enables both the
            // Dashcam and TSR chips. Record that image capture became enabled
            // later instead of leaving stale `false` metadata behind.
            guard diagnosticCaptureEnabled else { return }
            let existing = try Self.eventDecoder().decode(
                SessionMetadata.self,
                from: Data(contentsOf: metadataURL)
            )
            guard !existing.diagnosticImagesEnabled else { return }
            let updated = SessionMetadata(
                schemaVersion: existing.schemaVersion,
                captureGroupId: existing.captureGroupId,
                createdAtUtc: existing.createdAtUtc,
                storageScope: existing.storageScope,
                diagnosticImagesEnabled: true,
                exportApproved: existing.exportApproved,
                redactionStatus: existing.redactionStatus
            )
            try Self.eventEncoder().encode(updated).write(
                to: metadataURL,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            return
        }
        let metadata = SessionMetadata(
            schemaVersion: 1,
            captureGroupId: captureGroupId,
            createdAtUtc: Date(),
            storageScope: "local_tsr_qa_only",
            diagnosticImagesEnabled: diagnosticCaptureEnabled,
            exportApproved: false,
            redactionStatus: "pending_review"
        )
        let data = try Self.eventEncoder().encode(metadata)
        try data.write(
            to: metadataURL,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private func captureCount(for captureGroupId: String) -> Int {
        if let cached = captureCountByGroup[captureGroupId] { return cached }
        let captures = sessionURL(captureGroupId)
            .appendingPathComponent("captures", isDirectory: true)
        let count = (try? fileManager.contentsOfDirectory(
            at: captures,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ).filter { $0.pathExtension.lowercased() == "jpg" }.count) ?? 0
        captureCountByGroup[captureGroupId] = count
        return count
    }

    private func sessionURL(_ captureGroupId: String) -> URL {
        rootURL.appendingPathComponent(captureGroupId, isDirectory: true)
    }

    private func prepareDirectory(_ url: URL) throws {
        try fileManager.createDirectory(
            at: url,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutableURL = url
        try? mutableURL.setResourceValues(values)
    }

    private static func eventEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }

    private static func eventDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        value.range(
            of: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
            options: .regularExpression
        ) != nil
    }
}

enum TrafficSignShadowRuntimeError: Error, Equatable, LocalizedError {
    case invalidConfiguration(String)
    case invalidInput(String)
    case nonChronologicalFrame

    var errorDescription: String? {
        switch self {
        case .invalidConfiguration(let detail), .invalidInput(let detail):
            return detail
        case .nonChronologicalFrame:
            return "TSR shadow frames must be chronological."
        }
    }
}

// MARK: - M0 shadow round trip

/// Binds the two mobile stage identities, performs fail-closed plate
/// normalization and temporal association, emits a v2 QA event, and delegates
/// consent-aware diagnostic persistence to a separate sink. It intentionally
/// exposes no API that can alter the effective speed source.
final class TrafficSignShadowRuntimeV2: @unchecked Sendable {
    private struct RoadKey: Equatable, Sendable {
        let wayId: String
        let direction: TrafficSignTravelDirection
        let sourceSignature: TrafficSignRuntimeSourceSignature

        init(_ context: TrafficSignDetectionContext) {
            wayId = context.wayId
            direction = context.travelDirection
            sourceSignature = context.sourceSignature
        }
    }

    private struct Track: Sendable {
        let id: String
        let roadKey: RoadKey
        let semantic: TrafficSignPrimarySemanticV2
        var boundingBox: TrafficSignNormalizedRect
        var lastObservedAt: Date
        var evidenceFrameCount: Int
        var lastEventId: String?
        var lastConditionState: TrafficSignConditionState?
        var stableObservationHint: String?
    }

    private struct CoreResult: Sendable {
        let assemblies: [TrafficSignAssemblyV2]
        let state: TrafficSignRecognitionResultState
        let reasons: [TrafficSignDiagnosticReasonV2]
    }

    let configuration: TrafficSignShadowRuntimeConfigurationV2

    private let diagnosticCaptureSink: (any TrafficSignDiagnosticCaptureSinkV2)?
    private let qaEventSink: (any TrafficSignQAEventSinkV2)?
    private let lock = NSLock()
    private var tracks: [Track] = []
    private var nextTrackNumber: UInt64 = 1
    private var lastFrameTimestamp: Date?

    init(
        configuration: TrafficSignShadowRuntimeConfigurationV2,
        diagnosticCaptureSink: (any TrafficSignDiagnosticCaptureSinkV2)? = nil,
        qaEventSink: (any TrafficSignQAEventSinkV2)? = nil
    ) throws {
        guard configuration.isValid else {
            throw TrafficSignShadowRuntimeError.invalidConfiguration(
                "The TSR v2 runtime configuration is not a valid shadow pack projection."
            )
        }
        self.configuration = configuration
        self.diagnosticCaptureSink = diagnosticCaptureSink
        self.qaEventSink = qaEventSink
    }

    func process(_ input: TrafficSignShadowFrameInputV2) throws -> TrafficSignRecognitionEventV2 {
        try validate(input)
        let core: CoreResult
        lock.lock()
        do {
            if let lastFrameTimestamp, input.frame.timestampUtc < lastFrameTimestamp {
                throw TrafficSignShadowRuntimeError.nonChronologicalFrame
            }
            self.lastFrameTimestamp = input.frame.timestampUtc
            expireTracks(now: input.frame.timestampUtc)
            var usedTrackIDs = Set<String>()
            let assemblies = input.assemblies.map { observation in
                normalizeAssembly(
                    observation,
                    evidenceOrigin: input.evidenceOrigin,
                    eventID: input.eventId,
                    observedAt: input.frame.timestampUtc,
                    roadContext: input.roadContext,
                    usedTrackIDs: &usedTrackIDs
                )
            }
            let state = recognitionState(input: input, assemblies: assemblies)
            let reasons = diagnosticReasons(input: input, assemblies: assemblies, state: state)
            core = CoreResult(assemblies: assemblies, state: state, reasons: reasons)
            lock.unlock()
        } catch {
            lock.unlock()
            throw error
        }

        let capture = requestDiagnosticCapture(input: input, reasons: core.reasons)
        let event = TrafficSignRecognitionEventV2(
            schemaVersion: 2,
            eventId: input.eventId,
            packId: configuration.packId,
            taxonomyVersion: configuration.taxonomyVersion,
            evidenceOrigin: input.evidenceOrigin,
            executionMode: .shadow,
            overrideEligible: false,
            overrideDisposition: .shadowEvidenceOnly,
            qaDisposition: .emit,
            source: input.source,
            frame: input.frame,
            stageRuns: TrafficSignStageRunsV2(
                detector: stageRun(
                    configuration.detector,
                    invoked: input.evidenceOrigin == .runtimeInference,
                    latencyMs: input.evidenceOrigin == .runtimeInference
                        ? input.detectorLatencyMs
                        : 0
                ),
                classifier: stageRun(
                    configuration.classifier,
                    invoked: input.evidenceOrigin == .runtimeInference
                        && input.classifierInvoked,
                    latencyMs: input.evidenceOrigin == .runtimeInference
                        ? input.classifierLatencyMs
                        : 0
                )
            ),
            state: core.state,
            assemblies: core.assemblies,
            roadContext: input.roadContext,
            diagnosticCapture: capture,
            thermalState: input.thermalState
        )
        qaEventSink?.emit(event)
        return event
    }

    func reset() {
        lock.lock()
        tracks.removeAll(keepingCapacity: true)
        nextTrackNumber = 1
        lastFrameTimestamp = nil
        lock.unlock()
    }

    private func validate(_ input: TrafficSignShadowFrameInputV2) throws {
        let provenanceIsValid: Bool
        switch input.evidenceOrigin {
        case .runtimeInference:
            provenanceIsValid = input.assemblies.isEmpty || input.classifierInvoked
        case .reviewedExpectation:
            // Reviewed labels exercise the device-side event/temporal contract,
            // never the detector or classifier. Reject mixed provenance instead
            // of emitting an event that could be mistaken for model evidence.
            provenanceIsValid = (input.source == .panoramaxReplay
                || input.source == .diagnosticImport)
                && input.detectorLatencyMs == 0
                && !input.classifierInvoked
                && input.classifierLatencyMs == 0
        }
        guard !input.eventId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              input.frame.isValid,
              input.roadContext.isValid,
              input.detectorLatencyMs.isFinite,
              input.detectorLatencyMs >= 0,
              input.classifierLatencyMs.isFinite,
              input.classifierLatencyMs >= 0,
              input.classifierInvoked || input.classifierLatencyMs == 0,
              provenanceIsValid,
              Set(input.diagnosticReasons).count == input.diagnosticReasons.count else {
            throw TrafficSignShadowRuntimeError.invalidInput("The TSR v2 frame input is invalid.")
        }
        for assembly in input.assemblies {
            let primary = assembly.primary
            guard !assembly.assemblyId.isEmpty,
                  assembly.stableObservationHint.map({ !$0.isEmpty }) ?? true,
                  !primary.objectId.isEmpty,
                  !primary.classId.isEmpty,
                  primary.semantic.isValid,
                  primary.boundingBox.isValid,
                  scoreIsValid(primary.detectorScore),
                  primary.classifierRawScore.isFinite,
                  scoreIsValid(primary.classifierCalibratedConfidence),
                  (0...1).contains(primary.classifierThreshold) else {
                throw TrafficSignShadowRuntimeError.invalidInput("The TSR v2 primary observation is invalid.")
            }
            for plate in assembly.supplementaryPlates {
                guard !plate.objectId.isEmpty,
                      plate.boundingBox.isValid,
                      scoreIsValid(plate.detectorScore),
                      scoreIsValid(plate.detectorCalibratedConfidence),
                      plate.classifierRawScore.map(\.isFinite) ?? true,
                      scoreIsValid(plate.classifierCalibratedConfidence),
                      plate.auxiliaryEvidence.allSatisfy(\.isValid),
                      (0...1).contains(plate.classifierThreshold) else {
                    throw TrafficSignShadowRuntimeError.invalidInput("The TSR v2 plate observation is invalid.")
                }
            }
        }
    }

    private func scoreIsValid(_ score: Double?) -> Bool {
        score.map { $0.isFinite && (0...1).contains($0) } ?? true
    }

    private func normalizeAssembly(
        _ observation: TrafficSignTwoStageAssemblyObservationV2,
        evidenceOrigin: TrafficSignEvidenceOriginV2,
        eventID: String,
        observedAt: Date,
        roadContext: TrafficSignDetectionContext,
        usedTrackIDs: inout Set<String>
    ) -> TrafficSignAssemblyV2 {
        let includeScores = evidenceOrigin == .runtimeInference
        let primary = TrafficSignPrimaryEvidenceV2(
            objectId: observation.primary.objectId,
            boundingBox: observation.primary.boundingBox,
            detectorScore: includeScores
                ? TrafficSignStageScoreV2(
                    rawScore: observation.primary.detectorScore,
                    calibratedConfidence: observation.primary.detectorCalibratedConfidence
                )
                : nil,
            classifierScore: includeScores
                ? TrafficSignStageScoreV2(
                    rawScore: observation.primary.classifierRawScore,
                    calibratedConfidence: observation.primary.classifierCalibratedConfidence
                )
                : nil,
            classId: observation.primary.classId,
            semantic: observation.primary.semantic
        )
        let plates = observation.supplementaryPlates.map {
            normalizePlate($0, evidenceOrigin: evidenceOrigin)
        }
        let conditionState: TrafficSignConditionState
        if plates.isEmpty {
            conditionState = .none
        } else if plates.allSatisfy({ $0.readability == .readable }) {
            conditionState = .resolved
        } else {
            conditionState = .unresolved
        }

        let roadKey = RoadKey(roadContext)
        let candidates = tracks.indices.filter {
            !usedTrackIDs.contains(tracks[$0].id)
                && tracks[$0].roadKey == roadKey
                && tracks[$0].semantic == primary.semantic
                && hintsAreCompatible(
                    tracks[$0].stableObservationHint,
                    observation.stableObservationHint
                )
        }
        let hintedIndex = observation.stableObservationHint.flatMap { hint in
            candidates.first { tracks[$0].stableObservationHint == hint }
        }
        let overlappingIndex = candidates
            .map { ($0, tracks[$0].boundingBox.intersectionOverUnion(with: primary.boundingBox)) }
            .filter { $0.1 >= configuration.minimumTrackIou }
            .max { $0.1 < $1.1 }?
            .0
        let uniqueFallback = candidates.count == 1 ? candidates[0] : nil
        let matchingIndex = hintedIndex ?? overlappingIndex ?? uniqueFallback
        let trackIndex: Int
        if let matchingIndex {
            trackIndex = matchingIndex
        } else {
            tracks.append(Track(
                id: "tsr-v2-track-\(nextTrackNumber)",
                roadKey: roadKey,
                semantic: primary.semantic,
                boundingBox: primary.boundingBox,
                lastObservedAt: observedAt,
                evidenceFrameCount: 0,
                lastEventId: nil,
                lastConditionState: nil,
                stableObservationHint: observation.stableObservationHint
            ))
            nextTrackNumber &+= 1
            trackIndex = tracks.index(before: tracks.endIndex)
        }
        usedTrackIDs.insert(tracks[trackIndex].id)
        let transition: TrafficSignRestrictionTransitionV2
        if tracks[trackIndex].lastConditionState == .unresolved, conditionState == .resolved {
            transition = .upgradedFromLaterReadableEvidence
        } else if tracks[trackIndex].lastEventId != nil, conditionState == .unresolved {
            transition = .preservedUnreadable
        } else {
            transition = .none
        }
        let temporal = TrafficSignTemporalEvidenceV2(
            evidenceFrameCount: tracks[trackIndex].evidenceFrameCount + 1,
            priorEventId: tracks[trackIndex].lastEventId,
            restrictionTransition: transition
        )
        tracks[trackIndex].boundingBox = primary.boundingBox
        tracks[trackIndex].lastObservedAt = observedAt
        tracks[trackIndex].evidenceFrameCount = temporal.evidenceFrameCount
        tracks[trackIndex].lastEventId = eventID
        tracks[trackIndex].lastConditionState = conditionState
        if tracks[trackIndex].stableObservationHint == nil {
            tracks[trackIndex].stableObservationHint = observation.stableObservationHint
        }

        return TrafficSignAssemblyV2(
            assemblyId: observation.assemblyId,
            physicalSignTrackId: tracks[trackIndex].id,
            primary: primary,
            supplementaryPlates: plates,
            conditionState: conditionState,
            temporalEvidence: temporal
        )
    }

    private func recognitionState(
        input: TrafficSignShadowFrameInputV2,
        assemblies: [TrafficSignAssemblyV2]
    ) -> TrafficSignRecognitionResultState {
        guard !assemblies.isEmpty else {
            return input.requestedState == .unavailable ? .unavailable : .noRecognition
        }
        guard input.requestedState != .unknown else {
            return .unknown
        }
        if input.evidenceOrigin == .reviewedExpectation {
            let evidenceCount = assemblies.map(\.temporalEvidence.evidenceFrameCount).max() ?? 0
            return evidenceCount >= configuration.confirmationFrames ? .confirmed : .provisional
        }
        let hasQualifiedPrimary = input.assemblies.contains {
            let score = $0.primary.classifierCalibratedConfidence
                ?? $0.primary.classifierRawScore
            return score.isFinite
                && score >= configuration.classifierConfirmedThreshold
        }
        guard hasQualifiedPrimary else { return .unknown }
        let evidenceCount = assemblies.map(\.temporalEvidence.evidenceFrameCount).max() ?? 0
        return evidenceCount >= configuration.confirmationFrames ? .confirmed : .provisional
    }

    private func normalizePlate(
        _ observation: TrafficSignTwoStagePlateObservationV2,
        evidenceOrigin: TrafficSignEvidenceOriginV2
    ) -> TrafficSignSupplementaryPlateEvidenceV2 {
        let confidence = observation.classifierCalibratedConfidence
            ?? observation.classifierRawScore
        let reviewedExpectation = evidenceOrigin == .reviewedExpectation
        let readableEvidenceIsComplete = observation.readability == .readable
            && observation.classId.map {
                !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            } == true
            && observation.restriction?.isValid == true
        let readable = reviewedExpectation
            ? readableEvidenceIsComplete
            : readableEvidenceIsComplete
            && observation.classifierRawScore?.isFinite == true
            && confidence.map { $0.isFinite && $0 >= observation.classifierThreshold } == true
        let includeScores = evidenceOrigin == .runtimeInference
        return TrafficSignSupplementaryPlateEvidenceV2(
            objectId: observation.objectId,
            boundingBox: observation.boundingBox,
            detectorScore: includeScores
                ? observation.detectorScore.map {
                    TrafficSignStageScoreV2(
                        rawScore: $0,
                        calibratedConfidence: observation.detectorCalibratedConfidence
                    )
                }
                : nil,
            classifierScore: includeScores
                ? observation.classifierRawScore.map {
                    TrafficSignStageScoreV2(
                        rawScore: $0,
                        calibratedConfidence: confidence
                    )
                }
                : nil,
            auxiliaryEvidence: includeScores && !observation.auxiliaryEvidence.isEmpty
                ? observation.auxiliaryEvidence
                : nil,
            classId: readable ? observation.classId : nil,
            readability: readable ? .readable : .unreadable,
            restriction: readable ? observation.restriction : nil
        )
    }

    private func diagnosticReasons(
        input: TrafficSignShadowFrameInputV2,
        assemblies: [TrafficSignAssemblyV2],
        state: TrafficSignRecognitionResultState
    ) -> [TrafficSignDiagnosticReasonV2] {
        var reasons = input.diagnosticReasons
        if assemblies.contains(where: {
            $0.supplementaryPlates.contains(where: { $0.readability == .unreadable })
        }) {
            reasons.append(.unreadableSupplementaryPlate)
        }
        if assemblies.contains(where: {
            $0.temporalEvidence.restrictionTransition == .upgradedFromLaterReadableEvidence
        }) {
            reasons.append(.temporalUpgrade)
        }
        if state == .confirmed { reasons.append(.shadowCandidate) }
        var seen = Set<TrafficSignDiagnosticReasonV2>()
        return reasons.filter { seen.insert($0).inserted }
    }

    private func requestDiagnosticCapture(
        input: TrafficSignShadowFrameInputV2,
        reasons: [TrafficSignDiagnosticReasonV2]
    ) -> TrafficSignDiagnosticCaptureV2 {
        guard !reasons.isEmpty, let diagnosticCaptureSink else {
            return TrafficSignDiagnosticCaptureV2(
                status: .notRequested,
                reasons: reasons,
                captureId: nil
            )
        }
        let outcome: TrafficSignDiagnosticCaptureOutcomeV2
        do {
            outcome = try diagnosticCaptureSink.requestCapture(
                TrafficSignDiagnosticCaptureRequestV2(
                    eventId: input.eventId,
                    frame: input.frame,
                    roadContext: input.roadContext,
                    reasons: reasons
                )
            )
        } catch {
            outcome = TrafficSignDiagnosticCaptureOutcomeV2(status: .failed)
        }
        let captureID = outcome.status == .persisted
            && outcome.captureId?.isEmpty == false
            ? outcome.captureId
            : nil
        let status = outcome.status == .persisted && captureID == nil ? .failed : outcome.status
        return TrafficSignDiagnosticCaptureV2(status: status, reasons: reasons, captureId: captureID)
    }

    private func expireTracks(now: Date) {
        let window = TimeInterval(configuration.temporalWindowMs) / 1_000
        tracks.removeAll { now.timeIntervalSince($0.lastObservedAt) > window }
    }

    private func hintsAreCompatible(_ lhs: String?, _ rhs: String?) -> Bool {
        guard let lhs, let rhs else { return true }
        return lhs == rhs
    }

    private func stageRun(
        _ identity: TrafficSignShadowStageIdentityV2,
        invoked: Bool,
        latencyMs: Double
    ) -> TrafficSignStageRunV2 {
        TrafficSignStageRunV2(
            componentId: identity.componentId,
            artifactId: identity.artifactId,
            artifactSha256: identity.artifactSha256,
            artifactFormat: identity.artifactFormat,
            preprocessingVersion: identity.preprocessingVersion,
            calibrationId: identity.calibrationId,
            invoked: invoked,
            latencyMs: latencyMs
        )
    }
}

@preconcurrency import AVFoundation
@preconcurrency import CoreML
import CoreGraphics
import CoreImage
import Foundation
import ImageIO
import OSLog
import UniformTypeIdentifiers
@preconcurrency import Vision

#if TRAFFIC_SIGN_RUNTIME_STANDALONE_TYPECHECK
protocol DriveVideoFrameConsumer: AnyObject {
    func consumeVideoFrame(
        _ sampleBuffer: CMSampleBuffer,
        orientation: CGImagePropertyOrientation
    )
}
#endif

private enum TrafficSignRuntimeLog {
    private static let logger = Logger(
        subsystem: "de.youspeed.SpeedConsumer",
        category: "tsr"
    )

    private static func timestamp(_ date: Date = Date()) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    static func recoveredAuxiliaryFailure(stage: String, error: Error) {
        let nsError = error as NSError
        logger.warning(
            "timestamp=\(timestamp(), privacy: .public) event=auxiliary_inference_failed stage=\(stage, privacy: .public) error_domain=\(nsError.domain, privacy: .public) error_code=\(nsError.code) detail=\(String(describing: error), privacy: .public)"
        )
    }

    static func frameFailure(
        frameId: String,
        eventId: String,
        source: TrafficSignRecognitionSource,
        frameTimestampUTC: Date,
        context: TrafficSignDetectionContext?,
        captureSessionId: String?,
        consecutiveFailures: Int,
        terminal: Bool,
        error: Error
    ) {
        let nsError = error as NSError
        let captureSessionId = captureSessionId ?? "none"
        let wayID = context?.wayId ?? "unmatched"
        let latitude = context?.latitude ?? .nan
        let longitude = context?.longitude ?? .nan
        let heading = context?.headingDegrees ?? .nan
        let direction = context?.travelDirection.rawValue ?? "unknown"
        logger.error(
            "timestamp=\(timestamp(), privacy: .public) frame_timestamp_utc=\(timestamp(frameTimestampUTC), privacy: .public) event=frame_inference_failed frame_id=\(frameId, privacy: .public) event_id=\(eventId, privacy: .public) source=\(source.rawValue, privacy: .public) way_id=\(wayID, privacy: .public) latitude=\(latitude, privacy: .public) longitude=\(longitude, privacy: .public) heading_degrees=\(heading, privacy: .public) travel_direction=\(direction, privacy: .public) capture_session_id=\(captureSessionId, privacy: .public) consecutive_failures=\(consecutiveFailures) terminal=\(terminal) error_domain=\(nsError.domain, privacy: .public) error_code=\(nsError.code) detail=\(String(describing: error), privacy: .public)"
        )
    }

    static func terminalUnavailability(
        _ reason: TrafficSignRuntimeUnavailability,
        consecutiveFailures: Int
    ) {
        logger.fault(
            "timestamp=\(timestamp(), privacy: .public) event=runtime_unavailable code=\(reason.code.rawValue, privacy: .public) consecutive_failures=\(consecutiveFailures) detail=\(reason.detail, privacy: .public)"
        )
    }
}

// MARK: - Verified local model packs

enum TrafficSignRuntimeUnavailableCode: String, Codable, Sendable {
    case modelPackDirectoryMissing = "model_pack_directory_missing"
    case modelPackAuthenticationRequired = "model_pack_authentication_required"
    case manifestMissing = "manifest_missing"
    case manifestInvalid = "manifest_invalid"
    case noCompatibleArtifact = "no_compatible_artifact"
    case unsafeArtifactPath = "unsafe_artifact_path"
    case artifactMissing = "artifact_missing"
    case modelLoadFailed = "model_load_failed"
    case inferenceFailed = "inference_failed"
}

struct TrafficSignRuntimeUnavailability: Error, Equatable, LocalizedError, Sendable {
    let code: TrafficSignRuntimeUnavailableCode
    let detail: String

    var errorDescription: String? { detail }
}

struct TrafficSignVerifiedModelPack: Sendable {
    let directoryURL: URL
    let manifest: TrafficSignModelPackManifest
    let detectorArtifact: TrafficSignModelPackManifest.Artifact
    let detectorArtifactURL: URL
    let classifierArtifact: TrafficSignModelPackManifest.Artifact?
    let classifierArtifactURL: URL?
    let shadowRuntimeConfigurationV2: TrafficSignShadowRuntimeConfigurationV2?

    init(
        directoryURL: URL,
        manifest: TrafficSignModelPackManifest,
        detectorArtifact: TrafficSignModelPackManifest.Artifact,
        detectorArtifactURL: URL,
        classifierArtifact: TrafficSignModelPackManifest.Artifact? = nil,
        classifierArtifactURL: URL? = nil,
        shadowRuntimeConfigurationV2: TrafficSignShadowRuntimeConfigurationV2? = nil
    ) {
        self.directoryURL = directoryURL
        self.manifest = manifest
        self.detectorArtifact = detectorArtifact
        self.detectorArtifactURL = detectorArtifactURL
        self.classifierArtifact = classifierArtifact
        self.classifierArtifactURL = classifierArtifactURL
        self.shadowRuntimeConfigurationV2 = shadowRuntimeConfigurationV2
    }
}

enum TrafficSignModelPackDirectoryLoader {
    static let manifestFileName = "manifest.json"
    static let shadowRuntimeProjectionFileName = "shadow-runtime-v2.json"

    static func load(
        from directoryURL: URL,
        runtimeVersion: String,
        appVersion: String,
        countryCode: String,
        fileManager: FileManager = .default
    ) throws -> TrafficSignVerifiedModelPack {
        let rootURL = directoryURL.standardizedFileURL
        guard rootURL.isFileURL,
              let rootValues = try? rootURL.resourceValues(forKeys: [
                  .isDirectoryKey,
                  .isSymbolicLinkKey,
              ]),
              rootValues.isDirectory == true,
              rootValues.isSymbolicLink != true else {
            throw TrafficSignRuntimeUnavailability(
                code: .modelPackDirectoryMissing,
                detail: "The local TSR model-pack directory is missing or unsafe."
            )
        }

        let manifestURL = rootURL.appendingPathComponent(manifestFileName, isDirectory: false)
        guard let manifestValues = try? manifestURL.resourceValues(forKeys: [
            .isRegularFileKey,
            .isSymbolicLinkKey,
            .fileSizeKey,
        ]),
              manifestValues.isRegularFile == true,
              manifestValues.isSymbolicLink != true,
              (manifestValues.fileSize ?? 0) > 0,
              (manifestValues.fileSize ?? 0) <= 1_048_576 else {
            throw TrafficSignRuntimeUnavailability(
                code: .manifestMissing,
                detail: "The local TSR model-pack manifest is missing or unsafe."
            )
        }

        let manifest: TrafficSignModelPackManifest
        do {
            let data = try Data(contentsOf: manifestURL, options: [.mappedIfSafe])
            manifest = try TrafficSignPackJSON.decoder().decode(
                TrafficSignModelPackManifest.self,
                from: data
            )
        } catch {
            throw TrafficSignRuntimeUnavailability(
                code: .manifestInvalid,
                detail: "The local TSR model-pack manifest cannot be decoded."
            )
        }

        let artifact: TrafficSignModelPackManifest.Artifact
        do {
            artifact = try TrafficSignModelPackValidator.validate(
                manifest,
                platform: .ios,
                runtimeVersion: runtimeVersion,
                appVersion: appVersion,
                countryCode: countryCode
            )
        } catch let error as TrafficSignPackValidationError {
            let code: TrafficSignRuntimeUnavailableCode
            switch error {
            case .noCompatibleArtifact:
                code = .noCompatibleArtifact
            case .invalid:
                code = .manifestInvalid
            }
            throw TrafficSignRuntimeUnavailability(
                code: code,
                detail: error.localizedDescription
            )
        } catch {
            throw TrafficSignRuntimeUnavailability(
                code: .manifestInvalid,
                detail: "The local TSR model-pack manifest is invalid."
            )
        }

        let artifactURL = try verifiedArtifactURL(
            for: artifact,
            below: rootURL,
            fileManager: fileManager
        )

        var classifierArtifact: TrafficSignModelPackManifest.Artifact?
        var classifierArtifactURL: URL?
        if manifest.pipeline == .proposalClassification {
            do {
                let selectedClassifier = try TrafficSignModelPackValidator
                    .compatibleClassifierArtifact(
                        in: manifest,
                        platform: .ios,
                        runtimeVersion: runtimeVersion
                    )
                classifierArtifact = selectedClassifier
                classifierArtifactURL = try verifiedArtifactURL(
                    for: selectedClassifier,
                    below: rootURL,
                    fileManager: fileManager
                )
            } catch let error as TrafficSignPackValidationError {
                throw TrafficSignRuntimeUnavailability(
                    code: .noCompatibleArtifact,
                    detail: error.localizedDescription
                )
            }
        }

        let shadowRuntimeConfigurationV2: TrafficSignShadowRuntimeConfigurationV2?
        if let classifierArtifact {
            shadowRuntimeConfigurationV2 = try loadShadowRuntimeConfigurationV2(
                below: rootURL,
                sourceManifest: manifest,
                detectorArtifact: artifact,
                classifierArtifact: classifierArtifact,
                fileManager: fileManager
            )
        } else {
            shadowRuntimeConfigurationV2 = nil
        }
        return TrafficSignVerifiedModelPack(
            directoryURL: rootURL,
            manifest: manifest,
            detectorArtifact: artifact,
            detectorArtifactURL: artifactURL,
            classifierArtifact: classifierArtifact,
            classifierArtifactURL: classifierArtifactURL,
            shadowRuntimeConfigurationV2: shadowRuntimeConfigurationV2
        )
    }

    private static func loadShadowRuntimeConfigurationV2(
        below rootURL: URL,
        sourceManifest: TrafficSignModelPackManifest,
        detectorArtifact: TrafficSignModelPackManifest.Artifact,
        classifierArtifact: TrafficSignModelPackManifest.Artifact,
        fileManager: FileManager
    ) throws -> TrafficSignShadowRuntimeConfigurationV2? {
        let url = rootURL.appendingPathComponent(
            shadowRuntimeProjectionFileName,
            isDirectory: false
        )
        guard fileManager.fileExists(atPath: url.path) else { return nil }
        guard let values = try? url.resourceValues(forKeys: [
            .isRegularFileKey,
            .isSymbolicLinkKey,
            .fileSizeKey,
        ]),
              values.isRegularFile == true,
              values.isSymbolicLink != true,
              (values.fileSize ?? 0) > 0,
              (values.fileSize ?? 0) <= 262_144 else {
            throw TrafficSignRuntimeUnavailability(
                code: .manifestInvalid,
                detail: "The TSR v2 shadow runtime projection is missing or unsafe."
            )
        }
        do {
            let projection = try TrafficSignPackJSON.decoder().decode(
                TrafficSignShadowPackProjectionV2.self,
                from: Data(contentsOf: url, options: [.mappedIfSafe])
            )
            return try projection.configuration(
                sourceManifest: sourceManifest,
                detectorArtifact: detectorArtifact,
                classifierArtifact: classifierArtifact
            )
        } catch let error as TrafficSignRuntimeUnavailability {
            throw error
        } catch {
            throw TrafficSignRuntimeUnavailability(
                code: .manifestInvalid,
                detail: "The TSR v2 shadow runtime projection is invalid or does not match its models."
            )
        }
    }

    private static func verifiedArtifactURL(
        for artifact: TrafficSignModelPackManifest.Artifact,
        below rootURL: URL,
        fileManager: FileManager
    ) throws -> URL {
        let artifactURL = try safeArtifactURL(
            relativePath: artifact.path,
            below: rootURL,
            fileManager: fileManager
        )
        guard ["mlmodel", "mlpackage", "mlmodelc"].contains(
            artifactURL.pathExtension.lowercased()
        ) else {
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "The selected Core ML artifact has an unsupported file type."
            )
        }
        return artifactURL
    }

    private static func safeArtifactURL(
        relativePath: String,
        below rootURL: URL,
        fileManager: FileManager
    ) throws -> URL {
        let path = relativePath.trimmingCharacters(in: .whitespacesAndNewlines)
        let components = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard path == relativePath,
              !path.isEmpty,
              !path.hasPrefix("/"),
              !path.contains("\\"),
              !path.unicodeScalars.contains(where: { $0.value == 0 }),
              components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw TrafficSignRuntimeUnavailability(
                code: .unsafeArtifactPath,
                detail: "The TSR artifact path is not a safe relative path."
            )
        }

        var candidateURL = rootURL
        for (index, component) in components.enumerated() {
            candidateURL.appendPathComponent(component, isDirectory: false)
            let values: URLResourceValues
            do {
                values = try candidateURL.resourceValues(forKeys: [
                    .isSymbolicLinkKey,
                    .isRegularFileKey,
                    .isDirectoryKey,
                ])
            } catch {
                throw TrafficSignRuntimeUnavailability(
                    code: .artifactMissing,
                    detail: "The selected TSR model artifact is missing."
                )
            }
            guard values.isSymbolicLink != true else {
                throw TrafficSignRuntimeUnavailability(
                    code: .unsafeArtifactPath,
                    detail: "The TSR artifact path contains a symbolic link."
                )
            }
            if index < components.index(before: components.endIndex) {
                guard values.isDirectory == true else {
                    throw TrafficSignRuntimeUnavailability(
                        code: .artifactMissing,
                        detail: "The selected TSR model artifact is missing."
                    )
                }
            }
        }

        let rootComponents = rootURL.resolvingSymlinksInPath().standardizedFileURL.pathComponents
        let artifactURL = candidateURL.resolvingSymlinksInPath().standardizedFileURL
        let artifactComponents = artifactURL.pathComponents
        guard artifactComponents.count > rootComponents.count,
              Array(artifactComponents.prefix(rootComponents.count)) == rootComponents else {
            throw TrafficSignRuntimeUnavailability(
                code: .unsafeArtifactPath,
                detail: "The TSR artifact resolves outside its model-pack directory."
            )
        }

        guard fileManager.fileExists(atPath: artifactURL.path),
              let values = try? artifactURL.resourceValues(forKeys: [
                  .isRegularFileKey,
                  .isDirectoryKey,
                  .isSymbolicLinkKey,
              ]),
              values.isSymbolicLink != true,
              values.isRegularFile == true || values.isDirectory == true else {
            throw TrafficSignRuntimeUnavailability(
                code: .artifactMissing,
                detail: "The selected TSR model artifact is missing."
            )
        }
        return artifactURL
    }
}

// MARK: - Inference backend

protocol TrafficSignInferenceBackend: AnyObject, Sendable {
    func detections(
        in pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) throws -> [TrafficSignDetection]

    func detections(
        in cgImage: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> [TrafficSignDetection]
}

struct TrafficSignTwoStageInferenceResultV2: Sendable {
    let legacyDetections: [TrafficSignDetection]
    let assemblies: [TrafficSignTwoStageAssemblyObservationV2]
    let detectorLatencyMs: Double
    let classifierInvoked: Bool
    let classifierLatencyMs: Double
}

/// Additive richer output implemented by the real two-stage backend. The main
/// runtime calls this once and fans the result into the existing v1 UI fusion
/// and the v2 shadow evidence runtime; it never runs either model twice.
protocol TrafficSignShadowInferenceBackendV2: TrafficSignInferenceBackend {
    func shadowInference(
        in pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) throws -> TrafficSignTwoStageInferenceResultV2

    func shadowInference(
        in cgImage: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> TrafficSignTwoStageInferenceResultV2
}

enum TrafficSignInferenceBackendError: Error, LocalizedError, Sendable {
    case incompatibleOutput

    var errorDescription: String? {
        switch self {
        case .incompatibleOutput:
            return "The Core ML model did not return Vision recognized-object observations."
        }
    }
}

final class TrafficSignVisionCoreMLBackend: TrafficSignInferenceBackend, @unchecked Sendable {
    private let inferenceLock = NSLock()
    private let visionModel: VNCoreMLModel
    private let cropAndScaleOption: VNImageCropAndScaleOption
    private let mappingsByClassID: [String: TrafficSignModelPackManifest.ClassMapping]
    private let unknownThreshold: Double
    private let runtimeOutput: TrafficSignModelPackManifest.Calibration.RuntimeOutput

    init(
        verifiedPack: TrafficSignVerifiedModelPack,
        computeUnits: MLComputeUnits = .all
    ) throws {
        guard verifiedPack.manifest.pipeline == .directDetection else {
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "Two-stage TSR packs require a classifier runtime that is not installed."
            )
        }
        guard verifiedPack.detectorArtifact.outputSchema == "vision_recognized_objects_v1" else {
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "The selected Core ML artifact has an unsupported output schema."
            )
        }

        let modelURL: URL
        switch verifiedPack.detectorArtifactURL.pathExtension.lowercased() {
        case "mlmodel", "mlpackage":
            do {
                modelURL = try MLModel.compileModel(at: verifiedPack.detectorArtifactURL)
            } catch {
                throw TrafficSignRuntimeUnavailability(
                    code: .modelLoadFailed,
                    detail: "The verified TSR model could not be compiled."
                )
            }
        case "mlmodelc":
            modelURL = verifiedPack.detectorArtifactURL
        default:
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "The selected Core ML artifact has an unsupported file type."
            )
        }

        do {
            let configuration = MLModelConfiguration()
            configuration.computeUnits = computeUnits
            let model = try MLModel(contentsOf: modelURL, configuration: configuration)
            visionModel = try VNCoreMLModel(for: model)
        } catch {
            throw TrafficSignRuntimeUnavailability(
                code: .modelLoadFailed,
                detail: "The verified TSR Core ML model could not be loaded."
            )
        }

        switch verifiedPack.manifest.preprocessing.resize {
        case "scale_fit_letterbox":
            cropAndScaleOption = .scaleFit
        case "scale_fill":
            cropAndScaleOption = .scaleFill
        default:
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "The selected TSR preprocessing mode is unsupported by Vision."
            )
        }
        mappingsByClassID = Dictionary(
            uniqueKeysWithValues: verifiedPack.manifest.classMapping.map { ($0.classId, $0) }
        )
        unknownThreshold = verifiedPack.manifest.thresholds.unknown
        runtimeOutput = verifiedPack.manifest.calibration.runtimeOutput
    }

    func detections(
        in pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) throws -> [TrafficSignDetection] {
        try perform(
            VNImageRequestHandler(
                cvPixelBuffer: pixelBuffer,
                orientation: orientation,
                options: [:]
            )
        )
    }

    func detections(
        in cgImage: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> [TrafficSignDetection] {
        try perform(
            VNImageRequestHandler(
                cgImage: cgImage,
                orientation: orientation,
                options: [:]
            )
        )
    }

    private func perform(_ handler: VNImageRequestHandler) throws -> [TrafficSignDetection] {
        inferenceLock.lock()
        defer { inferenceLock.unlock() }
        let request = VNCoreMLRequest(model: visionModel)
        request.imageCropAndScaleOption = cropAndScaleOption
        try handler.perform([request])

        let results = request.results ?? []
        guard results.allSatisfy({ $0 is VNRecognizedObjectObservation }) else {
            throw TrafficSignInferenceBackendError.incompatibleOutput
        }
        let classified: [TrafficSignSpatialAssembly.ClassifiedDetection] = results.compactMap {
            observation -> TrafficSignSpatialAssembly.ClassifiedDetection? in
            guard let recognizedObject = observation as? VNRecognizedObjectObservation,
                  let rawLabel = recognizedObject.labels.first else {
                return nil
            }
            return classifiedDetection(from: recognizedObject, label: rawLabel)
        }
        return TrafficSignSpatialAssembly.assemble(classified)
    }

    private func classifiedDetection(
        from observation: VNRecognizedObjectObservation,
        label: VNClassificationObservation
    ) -> TrafficSignSpatialAssembly.ClassifiedDetection? {
        let visionBox = observation.boundingBox
        let contractBox = TrafficSignNormalizedRect(
            x: min(1, max(0, Double(visionBox.minX))),
            y: min(1, max(0, Double(1 - visionBox.maxY))),
            width: min(1, max(0, Double(visionBox.width))),
            height: min(1, max(0, Double(visionBox.height)))
        )
        guard contractBox.isValid else { return nil }

        let mapping = mappingsByClassID[label.identifier]
        let score = Double(label.confidence)
        return TrafficSignSpatialAssembly.ClassifiedDetection(
            detection: TrafficSignDetection(
                rawClassId: label.identifier,
                rawLabel: mapping?.label ?? label.identifier,
                semantic: mapping?.semantic ?? TrafficSignSemantic(
                    kind: .unknown,
                    value: nil,
                    unit: nil
                ),
                rawScore: score,
                calibratedConfidence: runtimeOutput == .calibratedConfidence ? score : nil,
                boundingBox: contractBox,
                classThreshold: mapping?.threshold ?? unknownThreshold
            ),
            signRole: mapping?.signRole ?? .primarySign,
            restriction: mapping?.restriction
        )
    }
}

/// Two-stage Core ML runtime for proposal detectors whose object labels only
/// identify a generic traffic sign. Each sign proposal is classified from the
/// same source frame, preserving the detector box for temporal fusion and QA.
final class TrafficSignVisionTwoStageCoreMLBackend: TrafficSignShadowInferenceBackendV2,
        @unchecked Sendable {
    private static let minimumExtentOCRSignHeight: CGFloat = 0.02
    private static let minimumExtentOCRConfidence: Float = 0.25
    /// Bounds per-frame Vision work on noisy detector output while retaining far
    /// more proposals than a normal road scene contains.
    private static let maximumProposalsPerRole = 12
    private static let kilometerExtentRegex = try! NSRegularExpression(
        pattern: #"([0-9]{1,2}(?:[.,][0-9]{1,2})?)\s*k\s*m"#,
        options: [.caseInsensitive]
    )

    private let inferenceLock = NSLock()
    private let detectorModel: VNCoreMLModel
    private let classifierModel: VNCoreMLModel
    private let mappingsByClassID: [String: TrafficSignModelPackManifest.ClassMapping]
    private let unknownThreshold: Double
    private let runtimeOutput: TrafficSignModelPackManifest.Calibration.RuntimeOutput
    private let detectorOutputIsCalibrated: Bool
    private let classifierOutputIsCalibrated: Bool

    init(
        verifiedPack: TrafficSignVerifiedModelPack,
        computeUnits: MLComputeUnits = .all
    ) throws {
        guard verifiedPack.manifest.pipeline == .proposalClassification,
              verifiedPack.detectorArtifact.outputSchema == "vision_recognized_objects_v1",
              verifiedPack.classifierArtifact?.outputSchema == "vision_classifications_v1",
              let classifierArtifactURL = verifiedPack.classifierArtifactURL else {
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "The bundled traffic-sign detector and classifier are incomplete."
            )
        }
        if let shadow = verifiedPack.shadowRuntimeConfigurationV2 {
            guard shadow.detector.preprocessingVersion
                    == "vision-scale-fit-letterbox-rgb-1280-v2",
                  shadow.classifier.preprocessingVersion
                    == "vision-roi-xpad10-lower35-upper5-scale-fill-rgb-224-v2" else {
                throw TrafficSignRuntimeUnavailability(
                    code: .manifestInvalid,
                    detail: "The TSR v2 stage preprocessing does not match the installed Vision pipeline."
                )
            }
        }

        detectorModel = try Self.loadVisionModel(
            at: verifiedPack.detectorArtifactURL,
            computeUnits: computeUnits,
            componentName: "detector"
        )
        classifierModel = try Self.loadVisionModel(
            at: classifierArtifactURL,
            computeUnits: computeUnits,
            componentName: "classifier"
        )
        mappingsByClassID = Dictionary(
            uniqueKeysWithValues: verifiedPack.manifest.classMapping.map { ($0.classId, $0) }
        )
        unknownThreshold = verifiedPack.manifest.thresholds.unknown
        runtimeOutput = verifiedPack.manifest.calibration.runtimeOutput
        detectorOutputIsCalibrated = verifiedPack.shadowRuntimeConfigurationV2?
            .detector.calibrationPassed == true
        classifierOutputIsCalibrated = verifiedPack.shadowRuntimeConfigurationV2?
            .classifier.calibrationPassed == true
    }

    func detections(
        in pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) throws -> [TrafficSignDetection] {
        try shadowInference(in: pixelBuffer, orientation: orientation).legacyDetections
    }

    func shadowInference(
        in pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) throws -> TrafficSignTwoStageInferenceResultV2 {
        try perform(
            VNImageRequestHandler(
                cvPixelBuffer: pixelBuffer,
                orientation: orientation,
                options: [:]
            )
        )
    }

    func detections(
        in cgImage: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> [TrafficSignDetection] {
        try shadowInference(in: cgImage, orientation: orientation).legacyDetections
    }

    func shadowInference(
        in cgImage: CGImage,
        orientation: CGImagePropertyOrientation
    ) throws -> TrafficSignTwoStageInferenceResultV2 {
        try perform(
            VNImageRequestHandler(
                cgImage: cgImage,
                orientation: orientation,
                options: [:]
            )
        )
    }

    private func perform(
        _ handler: VNImageRequestHandler
    ) throws -> TrafficSignTwoStageInferenceResultV2 {
        inferenceLock.lock()
        defer { inferenceLock.unlock() }

        let detectorRequest = VNCoreMLRequest(model: detectorModel)
        detectorRequest.imageCropAndScaleOption = .scaleFit
        let detectorStartedAt = ProcessInfo.processInfo.systemUptime
        try handler.perform([detectorRequest])
        let detectorLatencyMs = max(
            0,
            (ProcessInfo.processInfo.systemUptime - detectorStartedAt) * 1_000
        )
        let results = detectorRequest.results ?? []
        guard results.allSatisfy({ $0 is VNRecognizedObjectObservation }) else {
            throw TrafficSignInferenceBackendError.incompatibleOutput
        }

        let objects = results.compactMap { $0 as? VNRecognizedObjectObservation }
        let signObjects = Array(objects.filter { object in
            guard let label = object.labels.first,
                  object.confidence.isFinite,
                  Self.isValidNormalizedRegion(object.boundingBox) else { return false }
            return Self.isSignProposal(label.identifier)
                && Double(object.confidence) >= unknownThreshold
        }
        .sorted { $0.confidence > $1.confidence }
        .prefix(Self.maximumProposalsPerRole))
        let plateObjects = Array(objects.filter { object in
            guard let label = object.labels.first,
                  object.confidence.isFinite,
                  Self.isValidNormalizedRegion(object.boundingBox) else { return false }
            return Self.isPlateProposal(label.identifier)
                && Double(object.confidence) >= unknownThreshold
        }
        .sorted { $0.confidence > $1.confidence }
        .prefix(Self.maximumProposalsPerRole))

        var classified: [TrafficSignSpatialAssembly.ClassifiedDetection] = []
        classified.reserveCapacity((signObjects.count * 2) + plateObjects.count)
        var synthesizedPlateBoxes: [TrafficSignNormalizedRect] = []
        var classifierLatencyMs: Double = 0
        for object in signObjects {
            let classifierStartedAt = ProcessInfo.processInfo.systemUptime
            let result = try classify(
                object,
                detectorConfidence: Double(object.confidence),
                using: handler
            )
            classifierLatencyMs += max(
                0,
                (ProcessInfo.processInfo.systemUptime - classifierStartedAt) * 1_000
            )
            guard let result else { continue }
            classified.append(result)
            var restriction: TrafficSignSpatialAssembly.ClassifiedDetection?
            if result.detection.semantic.kind == .maximumSpeed {
                do {
                    restriction = try recognizeExtentBelow(object, using: handler)
                } catch {
                    TrafficSignRuntimeLog.recoveredAuxiliaryFailure(
                        stage: "supplementary_plate_ocr",
                        error: error
                    )
                }
                if restriction == nil {
                    do {
                        restriction = try detectUnreadablePlateBelow(object, using: handler)
                    } catch {
                        TrafficSignRuntimeLog.recoveredAuxiliaryFailure(
                            stage: "supplementary_plate_rectangle",
                            error: error
                        )
                    }
                }
            }
            if let restriction {
                classified.append(restriction)
                synthesizedPlateBoxes.append(restriction.detection.boundingBox)
            }
        }

        // Keep a detected white supplementary plate in the QA assembly even
        // though this bootstrap classifier cannot read its text yet. Marking
        // it unresolved makes that limitation explicit and prevents future
        // non-shadow use from treating the primary sign as unconditional.
        let detectorPlates = plateObjects.compactMap(supplementaryPlateDetection)
        let legacyClassified = classified + detectorPlates.filter { unresolved in
                !synthesizedPlateBoxes.contains {
                    Self.boxesOverlap($0, unresolved.detection.boundingBox)
                }
            }
        // Preserve every actual detector proposal in raw v2 QA, even when a
        // synthesized Vision observation overlaps it. The legacy consumer
        // keeps its existing duplicate-box suppression.
        let shadowClassified = classified + detectorPlates
        let grouped = TrafficSignSpatialAssembly.assembleWithMembers(legacyClassified)
        let shadowGrouped = TrafficSignSpatialAssembly.assembleWithMembers(shadowClassified)
        return TrafficSignTwoStageInferenceResultV2(
            legacyDetections: grouped.map(\.detection),
            assemblies: shadowGrouped.compactMap(Self.shadowAssembly),
            detectorLatencyMs: detectorLatencyMs,
            classifierInvoked: !signObjects.isEmpty,
            classifierLatencyMs: classifierLatencyMs
        )
    }

    private func classify(
        _ object: VNRecognizedObjectObservation,
        detectorConfidence: Double,
        using handler: VNImageRequestHandler
    ) throws -> TrafficSignSpatialAssembly.ClassifiedDetection? {
        guard Self.isValidNormalizedRegion(object.boundingBox) else { return nil }
        let classifierRegion = Self.classifierRegion(for: object.boundingBox)
        guard Self.isValidNormalizedRegion(classifierRegion) else { return nil }
        let request = VNCoreMLRequest(model: classifierModel)
        request.imageCropAndScaleOption = .scaleFill
        request.regionOfInterest = classifierRegion
        try handler.perform([request])
        guard let classification = request.results?
            .compactMap({ $0 as? VNClassificationObservation })
            .first else {
            throw TrafficSignInferenceBackendError.incompatibleOutput
        }

        let visionBox = object.boundingBox
        guard let contractBox = Self.contractBox(from: visionBox) else { return nil }
        let mapping = mappingsByClassID[classification.identifier]
        let score = min(detectorConfidence, Double(classification.confidence))
        return TrafficSignSpatialAssembly.ClassifiedDetection(
            detection: TrafficSignDetection(
                rawClassId: classification.identifier,
                rawLabel: mapping?.label ?? classification.identifier,
                semantic: mapping?.semantic ?? TrafficSignSemantic(
                    kind: .unknown,
                    value: nil,
                    unit: nil
                ),
                rawScore: score,
                calibratedConfidence: runtimeOutput == .calibratedConfidence ? score : nil,
                boundingBox: contractBox,
                classThreshold: mapping?.threshold ?? unknownThreshold
            ),
            signRole: mapping?.signRole ?? .primarySign,
            restriction: mapping?.restriction,
            detectorRawScore: detectorConfidence,
            detectorCalibratedConfidence: detectorOutputIsCalibrated
                ? detectorConfidence
                : nil,
            classifierRawScore: Double(classification.confidence),
            classifierCalibratedConfidence: classifierOutputIsCalibrated
                ? Double(classification.confidence)
                : nil
        )
    }

    private func supplementaryPlateDetection(
        _ object: VNRecognizedObjectObservation
    ) -> TrafficSignSpatialAssembly.ClassifiedDetection? {
        guard object.labels.first != nil,
              let contractBox = Self.contractBox(from: object.boundingBox) else { return nil }
        let restriction = TrafficSignRestriction(
            kind: .unknown,
            normalizedValue: "detected-unread",
            rawText: nil,
            countrySignCode: nil
        )
        return TrafficSignSpatialAssembly.ClassifiedDetection(
            detection: TrafficSignDetection(
                rawClassId: "supplementary_plate_unread",
                rawLabel: "Supplementary plate (unread)",
                semantic: TrafficSignSemantic(kind: .unknown, value: nil, unit: nil),
                rawScore: Double(object.confidence),
                calibratedConfidence: nil,
                boundingBox: contractBox,
                classThreshold: unknownThreshold
            ),
            signRole: .supplementaryPlate,
            restriction: restriction,
            detectorRawScore: Double(object.confidence),
            detectorCalibratedConfidence: nil
        )
    }

    /// The bootstrap detector does not reliably propose the small white plate
    /// in the field-test frames. For a readable, nearby speed sign, inspect one
    /// sign-height directly below it with Apple's on-device OCR. This remains
    /// auxiliary evidence and does not broaden inference to the scene.
    private func recognizeExtentBelow(
        _ object: VNRecognizedObjectObservation,
        using handler: VNImageRequestHandler
    ) throws -> TrafficSignSpatialAssembly.ClassifiedDetection? {
        guard object.boundingBox.height >= Self.minimumExtentOCRSignHeight else { return nil }
        let region = Self.supplementaryTextRegion(for: object.boundingBox)
        guard region.width > 0, region.height > 0 else { return nil }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["de-DE", "en-US"]
        request.regionOfInterest = region
        try handler.perform([request])

        var best: (
            restriction: TrafficSignRestriction,
            confidence: Float,
            box: CGRect
        )?
        for observation in request.results ?? [] {
            for candidate in observation.topCandidates(3) {
                guard candidate.confidence >= Self.minimumExtentOCRConfidence,
                      let restriction = Self.extentRestriction(from: candidate.string) else {
                    continue
                }
                if best == nil || candidate.confidence > best!.confidence {
                    best = (
                        restriction,
                        candidate.confidence,
                        Self.fullImageRegion(observation.boundingBox, within: region)
                    )
                }
            }
        }

        guard let best,
              let contractBox = Self.contractBox(from: best.box) else { return nil }
        return TrafficSignSpatialAssembly.ClassifiedDetection(
            detection: TrafficSignDetection(
                rawClassId: "supplementary_extent_ocr",
                rawLabel: "Supplementary plate extent: \(best.restriction.normalizedValue)",
                semantic: TrafficSignSemantic(kind: .unknown, value: nil, unit: nil),
                rawScore: Double(best.confidence),
                calibratedConfidence: nil,
                boundingBox: contractBox,
                classThreshold: Double(Self.minimumExtentOCRConfidence)
            ),
            signRole: .supplementaryPlate,
            restriction: best.restriction,
            auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2(
                source: .appleVisionTextRecognition,
                rawScore: Double(best.confidence),
                rawText: best.restriction.rawText,
                candidateRestriction: Self.shadowRestriction(best.restriction)
            )]
        )
    }

    /// A small plate can be visually present even when its glyphs are below
    /// OCR resolution. Rectangle detection records that presence as unresolved
    /// instead of inventing text from a neighboring frame.
    private func detectUnreadablePlateBelow(
        _ object: VNRecognizedObjectObservation,
        using handler: VNImageRequestHandler
    ) throws -> TrafficSignSpatialAssembly.ClassifiedDetection? {
        let region = Self.supplementaryPlateSearchRegion(for: object.boundingBox)
        guard region.width > 0, region.height > 0 else { return nil }

        let request = VNDetectRectanglesRequest()
        request.regionOfInterest = region
        request.maximumObservations = 5
        request.minimumAspectRatio = 0.3
        request.maximumAspectRatio = 1
        request.minimumSize = 0.05
        request.minimumConfidence = 0.1
        request.quadratureTolerance = 30
        try handler.perform([request])

        guard let plate = (request.results ?? [])
            .filter({ Self.isLikelySupplementaryPlate($0.boundingBox, below: object.boundingBox) })
            .max(by: { lhs, rhs in
                lhs.boundingBox.width * lhs.boundingBox.height
                    < rhs.boundingBox.width * rhs.boundingBox.height
            }),
              let contractBox = Self.contractBox(from: plate.boundingBox) else { return nil }
        let restriction = TrafficSignRestriction(
            kind: .unknown,
            normalizedValue: "detected-unread",
            rawText: nil,
            countrySignCode: nil
        )
        return TrafficSignSpatialAssembly.ClassifiedDetection(
            detection: TrafficSignDetection(
                rawClassId: "supplementary_plate_vision_rectangle_unread",
                rawLabel: "Supplementary plate (unread)",
                semantic: TrafficSignSemantic(kind: .unknown, value: nil, unit: nil),
                rawScore: Double(plate.confidence),
                calibratedConfidence: nil,
                boundingBox: contractBox,
                classThreshold: unknownThreshold
            ),
            signRole: .supplementaryPlate,
            restriction: restriction,
            auxiliaryEvidence: [TrafficSignAuxiliaryEvidenceV2(
                source: .appleVisionRectangleDetection,
                rawScore: Double(plate.confidence)
            )]
        )
    }

    static func shadowAssembly(
        _ grouped: TrafficSignSpatialAssembly.GroupedAssembly
    ) -> TrafficSignTwoStageAssemblyObservationV2? {
        let source = grouped.primary
        guard let detectorScore = source.detectorRawScore,
              let classifierScore = source.classifierRawScore else { return nil }
        let semantic = shadowSemantic(
            rawClassId: source.detection.rawClassId,
            semantic: source.detection.semantic
        )
        let assemblyId = grouped.detection.assemblyId
            ?? UUID().uuidString.lowercased()
        let plates = grouped.supplementaryPlates.enumerated().compactMap { index, plate
            -> TrafficSignTwoStagePlateObservationV2? in
            guard plate.detectorRawScore != nil || !plate.auxiliaryEvidence.isEmpty else {
                return nil
            }
            let restriction = plate.restriction.flatMap(shadowRestriction)
            let isOCR = plate.detection.rawClassId == "supplementary_extent_ocr"
            return TrafficSignTwoStagePlateObservationV2(
                objectId: "\(assemblyId)-plate-\(index + 1)-\(plate.detection.rawClassId)",
                classId: isOCR && restriction != nil ? "supplementary_extent" : nil,
                boundingBox: plate.detection.boundingBox,
                detectorScore: plate.detectorRawScore,
                detectorCalibratedConfidence: plate.detectorCalibratedConfidence,
                classifierRawScore: nil,
                classifierCalibratedConfidence: nil,
                auxiliaryEvidence: plate.auxiliaryEvidence,
                classifierThreshold: plate.detection.classThreshold,
                readability: isOCR && restriction != nil ? .readable : .unreadable,
                restriction: isOCR ? restriction : nil
            )
        }
        return TrafficSignTwoStageAssemblyObservationV2(
            assemblyId: assemblyId,
            stableObservationHint: nil,
            primary: TrafficSignTwoStagePrimaryObservationV2(
                objectId: "\(assemblyId)-primary",
                classId: shadowClassId(
                    rawClassId: source.detection.rawClassId,
                    semantic: semantic
                ),
                semantic: semantic,
                boundingBox: source.detection.boundingBox,
                detectorScore: detectorScore,
                detectorCalibratedConfidence: source.detectorCalibratedConfidence,
                classifierRawScore: classifierScore,
                classifierCalibratedConfidence: source.classifierCalibratedConfidence,
                classifierThreshold: source.detection.classThreshold
            ),
            supplementaryPlates: plates
        )
    }

    private static let shadowNumericSpeedValues: Set<Int> = [
        5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130,
    ]

    static func shadowSemantic(
        rawClassId: String,
        semantic: TrafficSignSemantic
    ) -> TrafficSignPrimarySemanticV2 {
        switch semantic.kind {
        case .maximumSpeed:
            guard let value = semantic.value,
                  shadowNumericSpeedValues.contains(value) else {
                return TrafficSignPrimarySemanticV2(kind: .unknown, value: nil, unit: nil)
            }
            return TrafficSignPrimarySemanticV2(
                kind: .maximumSpeed,
                value: value,
                unit: semantic.unit
            )
        case .zoneStart:
            return TrafficSignPrimarySemanticV2(
                kind: .zoneStart,
                value: semantic.value,
                unit: semantic.unit
            )
        case .zoneEnd:
            return TrafficSignPrimarySemanticV2(kind: .zoneEnd, value: nil, unit: nil)
        case .restrictionEnd:
            if rawClassId == "maxspeed:end" {
                return TrafficSignPrimarySemanticV2(
                    kind: .maximumSpeedEnd,
                    value: nil,
                    unit: nil
                )
            }
            return TrafficSignPrimarySemanticV2(
                kind: .restrictionEnd,
                value: nil,
                unit: nil
            )
        case .cityEntry, .cityExit, .pedestrianZoneStart, .pedestrianZoneEnd,
                .temporary, .unknown:
            return TrafficSignPrimarySemanticV2(kind: .unknown, value: nil, unit: nil)
        }
    }

    static func shadowClassId(
        rawClassId: String,
        semantic: TrafficSignPrimarySemanticV2
    ) -> String {
        switch semantic.kind {
        case .maximumSpeed:
            return semantic.value.map { "speed_limit_\($0)" }
                ?? "other_or_unknown_primary"
        case .maximumSpeedEnd:
            return "maximum_speed_end"
        case .zoneStart:
            return "maximum_speed_zone_start"
        case .zoneEnd:
            return "maximum_speed_zone_end"
        case .restrictionEnd:
            return rawClassId == "maxspeed:end"
                ? "maximum_speed_end"
                : "restriction_end"
        case .unknown:
            return "other_or_unknown_primary"
        }
    }

    private static func shadowRestriction(
        _ restriction: TrafficSignRestriction
    ) -> TrafficSignRestrictionV2? {
        let meters: Int?
        switch restriction.kind {
        case .distance, .extent:
            meters = metricDistanceMeters(from: restriction.normalizedValue)
        default:
            meters = nil
        }
        return TrafficSignRestrictionV2(
            kind: restriction.kind,
            normalizedValue: restriction.normalizedValue,
            distanceM: restriction.kind == .distance ? meters : nil,
            extentM: restriction.kind == .extent ? meters : nil,
            rawText: restriction.rawText,
            countrySignCode: restriction.countrySignCode
        )
    }

    private static func metricDistanceMeters(from value: String) -> Int? {
        let normalized = value
            .lowercased()
            .replacingOccurrences(of: ",", with: ".")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = normalized.split(whereSeparator: { $0.isWhitespace })
        guard let first = parts.first, let amount = Double(first), amount > 0 else { return nil }
        if normalized.contains("km") { return Int((amount * 1_000).rounded()) }
        if normalized.contains("m") { return Int(amount.rounded()) }
        return nil
    }

    static func classifierRegion(for signBox: CGRect) -> CGRect {
        let horizontalPadding = signBox.width * 0.10
        let lowerExtension = signBox.height * 0.35
        let upperPadding = signBox.height * 0.05
        let minX = max(0, signBox.minX - horizontalPadding)
        let minY = max(0, signBox.minY - lowerExtension)
        let maxX = min(1, signBox.maxX + horizontalPadding)
        let maxY = min(1, signBox.maxY + upperPadding)
        return CGRect(
            x: minX,
            y: minY,
            width: max(0, maxX - minX),
            height: max(0, maxY - minY)
        )
    }

    static func isValidNormalizedRegion(_ region: CGRect) -> Bool {
        guard region.origin.x.isFinite,
              region.origin.y.isFinite,
              region.width.isFinite,
              region.height.isFinite,
              region.width > 0,
              region.height > 0 else { return false }
        return region.minX >= 0
            && region.minY >= 0
            && region.maxX <= 1
            && region.maxY <= 1
    }

    static func supplementaryTextRegion(for signBox: CGRect) -> CGRect {
        let horizontalPadding = signBox.width * 0.18
        let minX = max(0, signBox.minX - horizontalPadding)
        let minY = max(0, signBox.minY - signBox.height)
        let maxX = min(1, signBox.maxX + horizontalPadding)
        let maxY = min(1, signBox.minY)
        return CGRect(
            x: minX,
            y: minY,
            width: max(0, maxX - minX),
            height: max(0, maxY - minY)
        )
    }

    static func supplementaryPlateSearchRegion(for signBox: CGRect) -> CGRect {
        let horizontalPadding = signBox.width * 0.30
        let minX = max(0, signBox.minX - horizontalPadding)
        let minY = max(0, signBox.minY - signBox.height)
        let maxX = min(1, signBox.maxX + horizontalPadding)
        let maxY = min(1, signBox.minY)
        return CGRect(
            x: minX,
            y: minY,
            width: max(0, maxX - minX),
            height: max(0, maxY - minY)
        )
    }

    static func extentRestriction(from recognizedText: String) -> TrafficSignRestriction? {
        let trimmed = recognizedText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let fullRange = NSRange(trimmed.startIndex..<trimmed.endIndex, in: trimmed)
        guard let match = kilometerExtentRegex.firstMatch(
            in: trimmed,
            options: [],
            range: fullRange
        ),
              match.numberOfRanges > 1,
              let valueRange = Range(match.range(at: 1), in: trimmed),
              let kilometers = Double(
                  trimmed[valueRange].replacingOccurrences(of: ",", with: ".")
              ),
              kilometers > 0,
              kilometers <= 99 else { return nil }

        var valueText = String(
            format: "%.2f",
            locale: Locale(identifier: "en_US_POSIX"),
            kilometers
        )
        while valueText.last == "0" { valueText.removeLast() }
        if valueText.last == "." { valueText.removeLast() }
        return TrafficSignRestriction(
            kind: .extent,
            normalizedValue: "\(valueText) km",
            rawText: trimmed,
            countrySignCode: nil
        )
    }

    static func fullImageRegion(_ roiRelativeBox: CGRect, within region: CGRect) -> CGRect {
        CGRect(
            x: region.minX + (roiRelativeBox.minX * region.width),
            y: region.minY + (roiRelativeBox.minY * region.height),
            width: roiRelativeBox.width * region.width,
            height: roiRelativeBox.height * region.height
        )
    }

    static func isLikelySupplementaryPlate(_ plate: CGRect, below sign: CGRect) -> Bool {
        guard sign.width > 0, sign.height > 0, plate.width > 0, plate.height > 0 else {
            return false
        }
        let widthRatio = plate.width / sign.width
        let heightRatio = plate.height / sign.height
        let verticalGap = sign.minY - plate.maxY
        let horizontalOverlap = max(
            0,
            min(sign.maxX, plate.maxX) - max(sign.minX, plate.minX)
        )
        let overlapDenominator = min(sign.width, plate.width)
        return (0.35...1.10).contains(widthRatio)
            && (0.08...0.50).contains(heightRatio)
            && verticalGap >= -(sign.height * 0.08)
            && verticalGap <= sign.height * 0.35
            && overlapDenominator > 0
            && horizontalOverlap / overlapDenominator >= 0.60
    }

    private static func boxesOverlap(
        _ lhs: TrafficSignNormalizedRect,
        _ rhs: TrafficSignNormalizedRect
    ) -> Bool {
        let overlapWidth = min(lhs.x + lhs.width, rhs.x + rhs.width) - max(lhs.x, rhs.x)
        let overlapHeight = min(lhs.y + lhs.height, rhs.y + rhs.height) - max(lhs.y, rhs.y)
        return overlapWidth > 0 && overlapHeight > 0
    }

    private static func contractBox(from visionBox: CGRect) -> TrafficSignNormalizedRect? {
        let box = TrafficSignNormalizedRect(
            x: min(1, max(0, Double(visionBox.minX))),
            y: min(1, max(0, Double(1 - visionBox.maxY))),
            width: min(1, max(0, Double(visionBox.width))),
            height: min(1, max(0, Double(visionBox.height)))
        )
        return box.isValid ? box : nil
    }

    private static func isSignProposal(_ identifier: String) -> Bool {
        identifier == "sign" || identifier == "class0" || identifier == "0"
    }

    private static func isPlateProposal(_ identifier: String) -> Bool {
        identifier == "plate" || identifier == "class1" || identifier == "1"
    }

    private static func loadVisionModel(
        at artifactURL: URL,
        computeUnits: MLComputeUnits,
        componentName: String
    ) throws -> VNCoreMLModel {
        let modelURL: URL
        switch artifactURL.pathExtension.lowercased() {
        case "mlmodel", "mlpackage":
            do {
                modelURL = try MLModel.compileModel(at: artifactURL)
            } catch {
                throw TrafficSignRuntimeUnavailability(
                    code: .modelLoadFailed,
                    detail: "The bundled traffic-sign \(componentName) could not be prepared."
                )
            }
        case "mlmodelc":
            modelURL = artifactURL
        default:
            throw TrafficSignRuntimeUnavailability(
                code: .noCompatibleArtifact,
                detail: "The bundled traffic-sign \(componentName) has an unsupported format."
            )
        }

        do {
            let configuration = MLModelConfiguration()
            configuration.computeUnits = computeUnits
            return try VNCoreMLModel(
                for: MLModel(contentsOf: modelURL, configuration: configuration)
            )
        } catch {
            throw TrafficSignRuntimeUnavailability(
                code: .modelLoadFailed,
                detail: "The bundled traffic-sign \(componentName) could not be loaded."
            )
        }
    }
}

// MARK: - Atomic frame state

struct TrafficSignFrameSnapshot: Equatable, Sendable {
    let context: TrafficSignDetectionContext?
    let coordinate: TrafficSignCoordinate?
    let conditions: TrafficSignAnalysisConditions
    let sessionGeneration: UInt64
    let contextGeneration: UInt64
    let captureSessionId: String?
    let diagnosticCaptureEnabled: Bool

    init(
        context: TrafficSignDetectionContext?,
        coordinate: TrafficSignCoordinate? = nil,
        conditions: TrafficSignAnalysisConditions,
        sessionGeneration: UInt64 = 0,
        contextGeneration: UInt64 = 0,
        captureSessionId: String? = nil,
        diagnosticCaptureEnabled: Bool = false
    ) {
        self.context = context
        self.coordinate = coordinate ?? context.map {
            TrafficSignCoordinate(latitude: $0.latitude, longitude: $0.longitude)
        }
        self.conditions = conditions
        self.sessionGeneration = sessionGeneration
        self.contextGeneration = contextGeneration
        self.captureSessionId = captureSessionId
        self.diagnosticCaptureEnabled = diagnosticCaptureEnabled
    }
}

/// The camera callback reads context and analysis conditions in one locked
/// operation. A caller may update both together whenever map matching, heading,
/// or the active source signature changes.
final class TrafficSignAtomicFrameState: @unchecked Sendable {
    private let lock = NSLock()
    private var value: TrafficSignFrameSnapshot?

    init(value: TrafficSignFrameSnapshot? = nil) {
        self.value = value
    }

    func update(_ value: TrafficSignFrameSnapshot?) {
        lock.lock()
        self.value = value
        lock.unlock()
    }

    func snapshot() -> TrafficSignFrameSnapshot? {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

struct TrafficSignRuntimeEmission: Equatable, Sendable {
    let event: TrafficSignRecognitionEvent
    let frameContext: TrafficSignDetectionContext?
    let frameSpeedKmh: Double?
    let sessionGeneration: UInt64
    let contextGeneration: UInt64
    let captureSessionId: String?
    let shadowEventV2: TrafficSignRecognitionEventV2?
    let passageUpdate: TrafficSignPassageFinalizerUpdate

    init(
        event: TrafficSignRecognitionEvent,
        frameContext: TrafficSignDetectionContext?,
        frameSpeedKmh: Double? = nil,
        sessionGeneration: UInt64 = 0,
        contextGeneration: UInt64 = 0,
        captureSessionId: String? = nil,
        shadowEventV2: TrafficSignRecognitionEventV2? = nil,
        passageUpdate: TrafficSignPassageFinalizerUpdate = .idle
    ) {
        precondition(
            event.roadContext == frameContext,
            "A TSR event must retain the context captured with its source frame."
        )
        self.event = event
        self.frameContext = frameContext
        self.frameSpeedKmh = frameSpeedKmh
        self.sessionGeneration = sessionGeneration
        self.contextGeneration = contextGeneration
        self.captureSessionId = captureSessionId
        self.shadowEventV2 = shadowEventV2
        self.passageUpdate = passageUpdate
    }
}

/// Terminal failures are asynchronous frame results too. Carry the immutable
/// frame generations and runtime identity so a callback queued before a
/// disable/re-enable cycle cannot tear down the replacement generation.
struct TrafficSignRuntimeUnavailabilityEmission: Equatable, Sendable {
    let reason: TrafficSignRuntimeUnavailability
    let sessionGeneration: UInt64
    let contextGeneration: UInt64
    let captureSessionId: String?
    let runtimeIdentity: String
}

struct TrafficSignRuntimeMetrics: Equatable, Sendable {
    let acceptedLiveFrames: UInt64
    let cadenceDroppedLiveFrames: UInt64
    let replacedPendingLiveFrames: UInt64
    let completedInferences: UInt64
}

// MARK: - One-in-flight runtime

final class TrafficSignRuntime: DriveVideoFrameConsumer, @unchecked Sendable {
    typealias SnapshotProvider = @Sendable () -> TrafficSignFrameSnapshot?
    typealias EventHandler = @Sendable (TrafficSignRuntimeEmission) -> Void
    typealias UnavailabilityHandler = @Sendable (TrafficSignRuntimeUnavailabilityEmission) -> Void

    /// A single Vision/Core ML failure can be caused by transient device load.
    /// Three failures without an intervening success indicate a persistent
    /// runtime problem and are reported as terminal unavailability.
    private static let maximumConsecutiveInferenceFailures = 3

    private enum Image: @unchecked Sendable {
        case pixelBuffer(CVPixelBuffer)
        case cgImage(CGImage)
    }

    private struct WorkItem: @unchecked Sendable {
        let eventId: String
        let frameId: String
        let image: Image
        let orientation: CGImagePropertyOrientation
        let source: TrafficSignRecognitionSource
        let timestampUTC: Date
        let snapshot: TrafficSignFrameSnapshot
    }

    private struct SuccessfulProcessingResult {
        let event: TrafficSignRecognitionEvent
        let shadowEventV2: TrafficSignRecognitionEventV2?
        let passageUpdate: TrafficSignPassageFinalizerUpdate
    }

    private struct SchedulingState {
        var stopped = false
        var unavailable: TrafficSignRuntimeUnavailability?
        var unavailableSessionGeneration: UInt64?
        var unavailableContextGeneration: UInt64?
        var unavailableCaptureSessionID: String?
        var inferenceInFlight = false
        var latestPendingLive: WorkItem?
        var latestPendingStill: WorkItem?
        var throttle = TrafficSignLatestFrameThrottle()
        var candidateBurstUntilUptime: TimeInterval?
        var acceptedLiveFrames: UInt64 = 0
        var cadenceDroppedLiveFrames: UInt64 = 0
        var replacedPendingLiveFrames: UInt64 = 0
        var completedInferences: UInt64 = 0
        var consecutiveInferenceFailures = 0
    }

    let verifiedPack: TrafficSignVerifiedModelPack
    let runtimeIdentity = UUID().uuidString.lowercased()

    private let backend: any TrafficSignInferenceBackend
    private let snapshotProvider: SnapshotProvider
    private let eventHandler: EventHandler
    private let unavailabilityHandler: UnavailabilityHandler?
    private let processingGate: TrafficSignWriteGate?
    private let shadowRuntimeV2: TrafficSignShadowRuntimeV2?
    private let shadowEvidenceStoreV2: TrafficSignShadowEvidenceStoreV2?
    private let callbackQueue: DispatchQueue
    private let inferenceQueue: DispatchQueue
    private let lock = NSLock()
    private var schedulingState = SchedulingState()
    private var fusion: TrafficSignFusionEngine
    private var passageFinalizer = TrafficSignPassageFinalizer()
    private var fusionSessionGeneration: UInt64?
    private var fusionContextGeneration: UInt64?

    init(
        verifiedPack: TrafficSignVerifiedModelPack,
        backend: any TrafficSignInferenceBackend,
        snapshotProvider: @escaping SnapshotProvider,
        callbackQueue: DispatchQueue = .main,
        eventHandler: @escaping EventHandler,
        unavailabilityHandler: UnavailabilityHandler? = nil,
        processingGate: TrafficSignWriteGate? = nil,
        shadowRuntimeV2: TrafficSignShadowRuntimeV2? = nil,
        shadowEvidenceStoreV2: TrafficSignShadowEvidenceStoreV2? = nil
    ) {
        self.verifiedPack = verifiedPack
        self.backend = backend
        self.snapshotProvider = snapshotProvider
        self.callbackQueue = callbackQueue
        self.eventHandler = eventHandler
        self.unavailabilityHandler = unavailabilityHandler
        self.processingGate = processingGate
        self.shadowRuntimeV2 = shadowRuntimeV2
        self.shadowEvidenceStoreV2 = shadowEvidenceStoreV2
        inferenceQueue = DispatchQueue(
            label: "de.youspeed.traffic-sign-recognition.inference",
            qos: .userInitiated,
            autoreleaseFrequency: .workItem
        )
        fusion = TrafficSignFusionEngine(
            packId: verifiedPack.manifest.packId,
            artifactSha256: verifiedPack.detectorArtifact.sha256,
            preprocessingVersion: verifiedPack.manifest.preprocessing.version,
            thresholds: verifiedPack.manifest.thresholds,
            runtimeOutput: verifiedPack.manifest.calibration.runtimeOutput,
            modelComponents: Self.modelComponentLineage(for: verifiedPack)
        )
    }

    private static func modelComponentLineage(
        for pack: TrafficSignVerifiedModelPack
    ) -> [TrafficSignModelComponentLineage] {
        let preprocessing = pack.manifest.preprocessing.version
        let calibration = pack.manifest.calibration.revision
        let detectorRole = pack.classifierArtifact == nil
            ? "direct_detector"
            : "proposal_detector"
        var components = [TrafficSignModelComponentLineage(
            role: detectorRole,
            artifactSHA256: pack.detectorArtifact.sha256,
            preprocessingVersion: preprocessing,
            calibrationID: calibration
        )]
        if let classifier = pack.classifierArtifact {
            components.append(TrafficSignModelComponentLineage(
                role: "semantic_classifier",
                artifactSHA256: classifier.sha256,
                preprocessingVersion: preprocessing,
                calibrationID: calibration
            ))
        }
        return components
    }

    func consumeVideoFrame(
        _ sampleBuffer: CMSampleBuffer,
        orientation: CGImagePropertyOrientation
    ) {
        let timestampUTC = Date()
        guard CMSampleBufferDataIsReady(sampleBuffer),
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer),
              let snapshot = snapshotProvider() else {
            return
        }
        submitLive(
            WorkItem(
                eventId: UUID().uuidString.lowercased(),
                frameId: UUID().uuidString.lowercased(),
                image: .pixelBuffer(pixelBuffer),
                orientation: orientation,
                source: .liveFrame,
                timestampUTC: timestampUTC,
                snapshot: snapshot
            )
        )
    }

    /// Still inference uses the same backend and fusion contract as live video,
    /// but bypasses the live-frame cadence. At most one newest live frame and
    /// one newest still wait behind an in-flight inference, so neither source
    /// can build an unbounded image queue.
    func analyzeStill(
        pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation,
        timestampUTC: Date = Date(),
        snapshot: TrafficSignFrameSnapshot
    ) {
        guard snapshot.context?.isValid == true else { return }
        submitWithoutCadence(
            WorkItem(
                eventId: UUID().uuidString.lowercased(),
                frameId: UUID().uuidString.lowercased(),
                image: .pixelBuffer(pixelBuffer),
                orientation: orientation,
                source: .cameraStill,
                timestampUTC: timestampUTC,
                snapshot: snapshot
            )
        )
    }

    func analyzeStill(
        cgImage: CGImage,
        orientation: CGImagePropertyOrientation,
        timestampUTC: Date = Date(),
        snapshot: TrafficSignFrameSnapshot
    ) {
        guard snapshot.context?.isValid == true else { return }
        submitWithoutCadence(
            WorkItem(
                eventId: UUID().uuidString.lowercased(),
                frameId: UUID().uuidString.lowercased(),
                image: .cgImage(cgImage),
                orientation: orientation,
                source: .cameraStill,
                timestampUTC: timestampUTC,
                snapshot: snapshot
            )
        )
    }

    func stop() {
        lock.lock()
        schedulingState.stopped = true
        schedulingState.latestPendingLive = nil
        schedulingState.latestPendingStill = nil
        lock.unlock()
    }

    var metrics: TrafficSignRuntimeMetrics {
        lock.lock()
        defer { lock.unlock() }
        return TrafficSignRuntimeMetrics(
            acceptedLiveFrames: schedulingState.acceptedLiveFrames,
            cadenceDroppedLiveFrames: schedulingState.cadenceDroppedLiveFrames,
            replacedPendingLiveFrames: schedulingState.replacedPendingLiveFrames,
            completedInferences: schedulingState.completedInferences
        )
    }

    var unavailability: TrafficSignRuntimeUnavailability? {
        lock.lock()
        defer { lock.unlock() }
        return schedulingState.unavailable
    }

    private func submitLive(_ item: WorkItem) {
        let now = ProcessInfo.processInfo.systemUptime
        var shouldStart = false
        lock.lock()
        reactivateTerminalFailureForNewGenerationIfNeeded(item.snapshot)
        guard !schedulingState.stopped, schedulingState.unavailable == nil else {
            lock.unlock()
            return
        }
        let burstActive = schedulingState.candidateBurstUntilUptime.map { now < $0 } ?? false
        let supplied = item.snapshot.conditions
        let conditions = TrafficSignAnalysisConditions(
            speedKmh: supplied.speedKmh,
            candidateRecentlySeen: supplied.candidateRecentlySeen || burstActive,
            lowPowerMode: supplied.lowPowerMode,
            thermalState: supplied.thermalState,
            appIsActive: supplied.appIsActive
        )
        guard schedulingState.throttle.shouldAnalyze(timestamp: now, conditions: conditions) else {
            schedulingState.cadenceDroppedLiveFrames &+= 1
            lock.unlock()
            return
        }

        schedulingState.acceptedLiveFrames &+= 1
        if schedulingState.inferenceInFlight {
            if schedulingState.latestPendingLive != nil {
                schedulingState.replacedPendingLiveFrames &+= 1
            }
            schedulingState.latestPendingLive = item
        } else {
            schedulingState.inferenceInFlight = true
            shouldStart = true
        }
        lock.unlock()

        if shouldStart { perform(item) }
    }

    private func submitWithoutCadence(_ item: WorkItem) {
        var shouldStart = false
        lock.lock()
        reactivateTerminalFailureForNewGenerationIfNeeded(item.snapshot)
        guard !schedulingState.stopped, schedulingState.unavailable == nil else {
            lock.unlock()
            return
        }
        if schedulingState.inferenceInFlight {
            schedulingState.latestPendingStill = item
        } else {
            schedulingState.inferenceInFlight = true
            shouldStart = true
        }
        lock.unlock()

        if shouldStart { perform(item) }
    }

    /// Called only while `lock` is held. Terminal inference health belongs to
    /// the generation that produced it; a later explicitly enabled generation
    /// gets a fresh failure budget even when it reuses the loaded model object.
    private func reactivateTerminalFailureForNewGenerationIfNeeded(
        _ snapshot: TrafficSignFrameSnapshot
    ) {
        guard schedulingState.unavailable != nil else { return }
        let sameGeneration = schedulingState.unavailableSessionGeneration
                == snapshot.sessionGeneration
            && schedulingState.unavailableContextGeneration == snapshot.contextGeneration
            && schedulingState.unavailableCaptureSessionID == snapshot.captureSessionId
        guard !sameGeneration else { return }
        schedulingState.unavailable = nil
        schedulingState.unavailableSessionGeneration = nil
        schedulingState.unavailableContextGeneration = nil
        schedulingState.unavailableCaptureSessionID = nil
        schedulingState.consecutiveInferenceFailures = 0
    }

    private func perform(_ item: WorkItem) {
        inferenceQueue.async { [weak self] in
            guard let self else { return }
            let startedAt = ProcessInfo.processInfo.systemUptime
            do {
                let detections: [TrafficSignDetection]
                let twoStageResult: TrafficSignTwoStageInferenceResultV2?
                if let twoStageBackend = self.backend
                    as? any TrafficSignShadowInferenceBackendV2 {
                    let result: TrafficSignTwoStageInferenceResultV2
                    switch item.image {
                    case .pixelBuffer(let pixelBuffer):
                        result = try twoStageBackend.shadowInference(
                            in: pixelBuffer,
                            orientation: item.orientation
                        )
                    case .cgImage(let cgImage):
                        result = try twoStageBackend.shadowInference(
                            in: cgImage,
                            orientation: item.orientation
                        )
                    }
                    detections = result.legacyDetections
                    twoStageResult = result
                } else {
                    switch item.image {
                    case .pixelBuffer(let pixelBuffer):
                        detections = try self.backend.detections(
                            in: pixelBuffer,
                            orientation: item.orientation
                        )
                    case .cgImage(let cgImage):
                        detections = try self.backend.detections(
                            in: cgImage,
                            orientation: item.orientation
                        )
                    }
                    twoStageResult = nil
                }
                let latencyMs = max(
                    0,
                    (ProcessInfo.processInfo.systemUptime - startedAt) * 1_000
                )
                let process = { () -> SuccessfulProcessingResult in
                    if self.fusionSessionGeneration != item.snapshot.sessionGeneration
                        || self.fusionContextGeneration != item.snapshot.contextGeneration {
                        self.fusion.reset()
                        self.passageFinalizer.reset()
                        self.shadowRuntimeV2?.reset()
                        self.fusionSessionGeneration = item.snapshot.sessionGeneration
                        self.fusionContextGeneration = item.snapshot.contextGeneration
                    }
                    let event = self.fusion.ingest(
                        detections: detections,
                        source: item.source,
                        timestamp: item.timestampUTC,
                        roadContext: item.snapshot.context,
                        latencyMs: latencyMs,
                        thermalState: item.snapshot.conditions.thermalState,
                        frameID: item.frameId,
                        driveSessionID: item.snapshot.captureSessionId
                    )
                    let passageUpdate = self.passageFinalizer.ingest(
                        event,
                        sessionGeneration: item.snapshot.sessionGeneration,
                        contextGeneration: item.snapshot.contextGeneration,
                        frameCoordinate: item.snapshot.coordinate,
                        frameSpeedKmh: item.snapshot.conditions.speedKmh,
                        calibratedActivationEligible: item.snapshot.conditions.speedKmh.map {
                            $0.isFinite && $0 >= 1
                        } == true
                    )
                    // Shadow QA must never disable the existing recognition
                    // UI. The admission gate covers staging/JPEG/event sinks,
                    // so invalidating a generation is a barrier after which an
                    // old frame cannot write any diagnostic artifact.
                    let shadowEventV2: TrafficSignRecognitionEventV2?
                    do {
                        shadowEventV2 = try self.processShadowV2(
                            result: twoStageResult,
                            item: item
                        )
                    } catch {
                        shadowEventV2 = nil
                    }
                    return SuccessfulProcessingResult(
                        event: event,
                        shadowEventV2: shadowEventV2,
                        passageUpdate: passageUpdate
                    )
                }

                let processed: SuccessfulProcessingResult?
                let expectedToken = TrafficSignGenerationToken(
                    session: item.snapshot.sessionGeneration,
                    context: item.snapshot.contextGeneration
                )
                if let processingGate = self.processingGate {
                    processed = processingGate.permit(for: expectedToken)?.consume(process)
                } else if self.isWorkItemStillCurrent(item) {
                    processed = process()
                } else {
                    processed = nil
                }
                guard let processed else {
                    self.discardStaleWorkItem()
                    return
                }
                self.complete(
                    item: item,
                    event: processed.event,
                    shadowEventV2: processed.shadowEventV2,
                    passageUpdate: processed.passageUpdate
                )
            } catch {
                self.handleInferenceFailure(item: item, error: error)
            }
        }
    }

    private func processShadowV2(
        result: TrafficSignTwoStageInferenceResultV2?,
        item: WorkItem
    ) throws -> TrafficSignRecognitionEventV2? {
        guard let result,
              let shadowRuntimeV2,
              let roadContext = item.snapshot.context else { return nil }
        let dimensions = Self.orientedDimensions(for: item.image, orientation: item.orientation)
        var diagnosticReasons: [TrafficSignDiagnosticReasonV2] = []
        if !result.assemblies.isEmpty {
            diagnosticReasons.append(.shadowCandidate)
            let hasQualifiedConfidence = result.assemblies.contains { assembly in
                let score = assembly.primary.classifierCalibratedConfidence
                    ?? assembly.primary.classifierRawScore
                return score.isFinite
                    && score >= shadowRuntimeV2.configuration.classifierConfirmedThreshold
            }
            if !hasQualifiedConfidence {
                diagnosticReasons.append(.uncertainPrimary)
            }
        }

        let evidenceStore = shadowEvidenceStoreV2
        if let captureSessionId = item.snapshot.captureSessionId, let evidenceStore {
            evidenceStore.stageFrame(
                eventId: item.eventId,
                captureGroupId: captureSessionId,
                diagnosticCaptureEnabled: item.snapshot.diagnosticCaptureEnabled,
                jpegProvider: {
                    try Self.diagnosticJPEG(
                        for: item.image,
                        orientation: item.orientation
                    )
                }
            )
        }
        defer { evidenceStore?.unstageFrame(eventId: item.eventId) }

        let source: TrafficSignInputSourceV2
        switch item.source {
        case .liveFrame:
            source = .liveFrame
        case .cameraStill:
            source = .cameraStill
        case .diagnosticImport:
            source = .diagnosticImport
        }

        return try shadowRuntimeV2.process(TrafficSignShadowFrameInputV2(
            eventId: item.eventId,
            source: source,
            frame: TrafficSignFrameV2(
                frameId: item.frameId,
                timestampUtc: item.timestampUTC,
                width: dimensions.width,
                height: dimensions.height
            ),
            roadContext: roadContext,
            requestedState: result.assemblies.isEmpty ? .noRecognition : .confirmed,
            detectorLatencyMs: result.detectorLatencyMs,
            classifierInvoked: result.classifierInvoked,
            classifierLatencyMs: result.classifierLatencyMs,
            assemblies: result.assemblies,
            diagnosticReasons: diagnosticReasons,
            thermalState: item.snapshot.conditions.thermalState.rawValue
        ))
    }

    private static func orientedDimensions(
        for image: Image,
        orientation: CGImagePropertyOrientation
    ) -> (width: Int, height: Int) {
        let source: (width: Int, height: Int)
        switch image {
        case .pixelBuffer(let pixelBuffer):
            source = (CVPixelBufferGetWidth(pixelBuffer), CVPixelBufferGetHeight(pixelBuffer))
        case .cgImage(let cgImage):
            source = (cgImage.width, cgImage.height)
        }
        switch orientation {
        case .left, .leftMirrored, .right, .rightMirrored:
            return (source.height, source.width)
        case .up, .upMirrored, .down, .downMirrored:
            return source
        }
    }

    private static func diagnosticJPEG(
        for image: Image,
        orientation: CGImagePropertyOrientation
    ) throws -> Data {
        let source: CIImage
        switch image {
        case .pixelBuffer(let pixelBuffer):
            source = CIImage(cvPixelBuffer: pixelBuffer)
        case .cgImage(let cgImage):
            source = CIImage(cgImage: cgImage)
        }
        let oriented = source.oriented(forExifOrientation: Int32(orientation.rawValue))
        let context = CIContext(options: [.cacheIntermediates: false])
        guard let cgImage = context.createCGImage(oriented, from: oriented.extent),
              let destinationData = CFDataCreateMutable(nil, 0),
              let destination = CGImageDestinationCreateWithData(
                  destinationData,
                  UTType.jpeg.identifier as CFString,
                  1,
                  nil
              ) else {
            throw TrafficSignRuntimeUnavailability(
                code: .inferenceFailed,
                detail: "The analyzed TSR frame could not be encoded for local diagnostics."
            )
        }
        CGImageDestinationAddImage(
            destination,
            cgImage,
            [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary
        )
        guard CGImageDestinationFinalize(destination) else {
            throw TrafficSignRuntimeUnavailability(
                code: .inferenceFailed,
                detail: "The analyzed TSR frame could not be encoded for local diagnostics."
            )
        }
        return destinationData as Data
    }

    private func isWorkItemStillCurrent(_ item: WorkItem) -> Bool {
        guard let current = snapshotProvider() else { return false }
        return current.sessionGeneration == item.snapshot.sessionGeneration
            && current.contextGeneration == item.snapshot.contextGeneration
            && current.captureSessionId == item.snapshot.captureSessionId
    }

    private func discardStaleWorkItem() {
        var next: WorkItem?
        lock.lock()
        if schedulingState.stopped || schedulingState.unavailable != nil {
            schedulingState.inferenceInFlight = false
            schedulingState.latestPendingLive = nil
            schedulingState.latestPendingStill = nil
        } else if let live = schedulingState.latestPendingLive,
                  let still = schedulingState.latestPendingStill {
            if live.timestampUTC <= still.timestampUTC {
                schedulingState.latestPendingLive = nil
                next = live
            } else {
                schedulingState.latestPendingStill = nil
                next = still
            }
        } else if let still = schedulingState.latestPendingStill {
            schedulingState.latestPendingStill = nil
            next = still
        } else if let live = schedulingState.latestPendingLive {
            schedulingState.latestPendingLive = nil
            next = live
        } else {
            schedulingState.inferenceInFlight = false
        }
        lock.unlock()
        if let next { perform(next) }
    }

    private func complete(
        item: WorkItem,
        event: TrafficSignRecognitionEvent,
        shadowEventV2: TrafficSignRecognitionEventV2?,
        passageUpdate: TrafficSignPassageFinalizerUpdate
    ) {
        let now = ProcessInfo.processInfo.systemUptime
        var next: WorkItem?
        var shouldDeliver = false
        lock.lock()
        schedulingState.completedInferences &+= 1
        schedulingState.consecutiveInferenceFailures = 0
        if event.state == .provisional || event.state == .confirmed || event.state == .unknown {
            schedulingState.candidateBurstUntilUptime = now + 1.5
        }
        if schedulingState.stopped || schedulingState.unavailable != nil {
            schedulingState.inferenceInFlight = false
            schedulingState.latestPendingLive = nil
            schedulingState.latestPendingStill = nil
        } else if let live = schedulingState.latestPendingLive,
                  let still = schedulingState.latestPendingStill {
            if live.timestampUTC <= still.timestampUTC {
                schedulingState.latestPendingLive = nil
                next = live
            } else {
                schedulingState.latestPendingStill = nil
                next = still
            }
        } else if let still = schedulingState.latestPendingStill {
            schedulingState.latestPendingStill = nil
            next = still
        } else if let live = schedulingState.latestPendingLive {
            schedulingState.latestPendingLive = nil
            next = live
        } else {
            schedulingState.inferenceInFlight = false
        }
        shouldDeliver = !schedulingState.stopped && schedulingState.unavailable == nil
        lock.unlock()

        if shouldDeliver {
            let emission = TrafficSignRuntimeEmission(
                event: event,
                frameContext: item.snapshot.context,
                frameSpeedKmh: item.snapshot.conditions.speedKmh,
                sessionGeneration: item.snapshot.sessionGeneration,
                contextGeneration: item.snapshot.contextGeneration,
                captureSessionId: item.snapshot.captureSessionId,
                shadowEventV2: shadowEventV2,
                passageUpdate: passageUpdate
            )
            callbackQueue.async { [weak self, eventHandler] in
                guard self?.canDeliverCallback == true else { return }
                eventHandler(emission)
            }
        }
        if let next { perform(next) }
    }

    private func handleInferenceFailure(item: WorkItem, error: Error) {
        let expectedToken = TrafficSignGenerationToken(
            session: item.snapshot.sessionGeneration,
            context: item.snapshot.contextGeneration
        )
        if let processingGate {
            guard let permit = processingGate.permit(for: expectedToken),
                  permit.consume({
                      self.handleAdmittedInferenceFailure(item: item, error: error)
                      return true
                  }) == true else {
                discardStaleWorkItem()
                return
            }
            return
        }
        guard isWorkItemStillCurrent(item) else {
            discardStaleWorkItem()
            return
        }
        handleAdmittedInferenceFailure(item: item, error: error)
    }

    private func handleAdmittedInferenceFailure(item: WorkItem, error: Error) {
        let reason = TrafficSignRuntimeUnavailability(
            code: .inferenceFailed,
            detail: "Speed-sign recognition stopped after three camera-processing errors in a row. Stop and restart recording to try again."
        )
        var next: WorkItem?
        var shouldNotify = false
        var consecutiveFailures = 0
        var terminal = false
        lock.lock()
        guard !schedulingState.stopped, schedulingState.unavailable == nil else {
            schedulingState.inferenceInFlight = false
            schedulingState.latestPendingLive = nil
            schedulingState.latestPendingStill = nil
            lock.unlock()
            return
        }

        schedulingState.consecutiveInferenceFailures += 1
        consecutiveFailures = schedulingState.consecutiveInferenceFailures
        if consecutiveFailures >= Self.maximumConsecutiveInferenceFailures {
            schedulingState.unavailable = reason
            schedulingState.unavailableSessionGeneration = item.snapshot.sessionGeneration
            schedulingState.unavailableContextGeneration = item.snapshot.contextGeneration
            schedulingState.unavailableCaptureSessionID = item.snapshot.captureSessionId
            schedulingState.inferenceInFlight = false
            schedulingState.latestPendingLive = nil
            schedulingState.latestPendingStill = nil
            shouldNotify = true
            terminal = true
        } else if let live = schedulingState.latestPendingLive,
                  let still = schedulingState.latestPendingStill {
            if live.timestampUTC <= still.timestampUTC {
                schedulingState.latestPendingLive = nil
                next = live
            } else {
                schedulingState.latestPendingStill = nil
                next = still
            }
        } else if let still = schedulingState.latestPendingStill {
            schedulingState.latestPendingStill = nil
            next = still
        } else if let live = schedulingState.latestPendingLive {
            schedulingState.latestPendingLive = nil
            next = live
        } else {
            schedulingState.inferenceInFlight = false
        }
        lock.unlock()

        TrafficSignRuntimeLog.frameFailure(
            frameId: item.frameId,
            eventId: item.eventId,
            source: item.source,
            frameTimestampUTC: item.timestampUTC,
            context: item.snapshot.context,
            captureSessionId: item.snapshot.captureSessionId,
            consecutiveFailures: consecutiveFailures,
            terminal: terminal,
            error: error
        )
        if terminal {
            TrafficSignRuntimeLog.terminalUnavailability(
                reason,
                consecutiveFailures: consecutiveFailures
            )
        }
        if shouldNotify, let unavailabilityHandler {
            let emission = TrafficSignRuntimeUnavailabilityEmission(
                reason: reason,
                sessionGeneration: item.snapshot.sessionGeneration,
                contextGeneration: item.snapshot.contextGeneration,
                captureSessionId: item.snapshot.captureSessionId,
                runtimeIdentity: runtimeIdentity
            )
            callbackQueue.async { unavailabilityHandler(emission) }
        }
        if let next { perform(next) }
    }

    private var canDeliverCallback: Bool {
        lock.lock()
        defer { lock.unlock() }
        return !schedulingState.stopped && schedulingState.unavailable == nil
    }
}

enum TrafficSignRuntimeBootstrapResult: Sendable {
    case ready(TrafficSignRuntime)
    case unavailable(TrafficSignRuntimeUnavailability)
}

enum TrafficSignRuntimeBootstrap {
    typealias BackendFactory = @Sendable (
        TrafficSignVerifiedModelPack
    ) throws -> any TrafficSignInferenceBackend

    static func make(
        modelPackDirectoryURL: URL,
        runtimeVersion: String,
        appVersion: String,
        countryCode: String,
        snapshotProvider: @escaping TrafficSignRuntime.SnapshotProvider,
        callbackQueue: DispatchQueue = .main,
        backendFactory: BackendFactory? = nil,
        eventHandler: @escaping TrafficSignRuntime.EventHandler,
        unavailabilityHandler: TrafficSignRuntime.UnavailabilityHandler? = nil,
        processingGate: TrafficSignWriteGate? = nil
    ) -> TrafficSignRuntimeBootstrapResult {
        do {
            let pack = try TrafficSignModelPackDirectoryLoader.load(
                from: modelPackDirectoryURL,
                runtimeVersion: runtimeVersion,
                appVersion: appVersion,
                countryCode: countryCode
            )
            let backend: any TrafficSignInferenceBackend
            if let backendFactory {
                backend = try backendFactory(pack)
            } else {
                switch pack.manifest.pipeline {
                case .directDetection:
                    backend = try TrafficSignVisionCoreMLBackend(verifiedPack: pack)
                case .proposalClassification:
                    backend = try TrafficSignVisionTwoStageCoreMLBackend(verifiedPack: pack)
                }
            }
            let shadowEvidenceStoreV2: TrafficSignShadowEvidenceStoreV2?
            let shadowRuntimeV2: TrafficSignShadowRuntimeV2?
            if let configuration = pack.shadowRuntimeConfigurationV2 {
                let store = try TrafficSignShadowEvidenceStoreV2()
                shadowEvidenceStoreV2 = store
                shadowRuntimeV2 = try TrafficSignShadowRuntimeV2(
                    configuration: configuration,
                    diagnosticCaptureSink: store,
                    qaEventSink: store
                )
            } else {
                shadowEvidenceStoreV2 = nil
                shadowRuntimeV2 = nil
            }
            return .ready(TrafficSignRuntime(
                verifiedPack: pack,
                backend: backend,
                snapshotProvider: snapshotProvider,
                callbackQueue: callbackQueue,
                eventHandler: eventHandler,
                unavailabilityHandler: unavailabilityHandler,
                processingGate: processingGate,
                shadowRuntimeV2: shadowRuntimeV2,
                shadowEvidenceStoreV2: shadowEvidenceStoreV2
            ))
        } catch let reason as TrafficSignRuntimeUnavailability {
            return .unavailable(reason)
        } catch {
            return .unavailable(TrafficSignRuntimeUnavailability(
                code: .modelLoadFailed,
                detail: "No compatible verified TSR model is available on this device."
            ))
        }
    }
}

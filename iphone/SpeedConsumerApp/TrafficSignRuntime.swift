@preconcurrency import AVFoundation
@preconcurrency import CoreML
import CoreGraphics
import CoreImage
import Foundation
import CryptoKit
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

    static func lanePreparation(_ prepared: RoadPathPreparedFrame, tsrStartedAt: Double) {
        var fields = prepared.publicationDetails
        fields["frameId"] = prepared.frameId
        fields["capturedAtSeconds"] = prepared.frame.capturedAtSeconds
        fields["geometryId"] = prepared.frame.geometryId
        fields["lanePreprocessingId"] = RoadBoundaryPreprocessor.identifier
        fields["lanePreparationReadyUptimeSeconds"] = prepared.readyUptime
        fields["tsrInferenceStartedUptimeSeconds"] = tsrStartedAt
        fields["lanePreparedBeforeTsr"] = prepared.readyUptime <= tsrStartedAt
        fields["preparationAddedMs"] = prepared.preparationMs
        fields["geometryDeadlineExceeded"] = prepared.geometry.budgetExceeded
        guard let data = try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return }
        logger.notice("timestamp=\(timestamp(), privacy: .public) tsr_path_preparation_v1=\(json, privacy: .public)")
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
    let manifestSHA256: String?

    init(
        directoryURL: URL,
        manifest: TrafficSignModelPackManifest,
        detectorArtifact: TrafficSignModelPackManifest.Artifact,
        detectorArtifactURL: URL,
        classifierArtifact: TrafficSignModelPackManifest.Artifact? = nil,
        classifierArtifactURL: URL? = nil,
        shadowRuntimeConfigurationV2: TrafficSignShadowRuntimeConfigurationV2? = nil,
        manifestSHA256: String? = nil
    ) {
        self.directoryURL = directoryURL
        self.manifest = manifest
        self.detectorArtifact = detectorArtifact
        self.detectorArtifactURL = detectorArtifactURL
        self.classifierArtifact = classifierArtifact
        self.classifierArtifactURL = classifierArtifactURL
        self.shadowRuntimeConfigurationV2 = shadowRuntimeConfigurationV2
        self.manifestSHA256 = manifestSHA256
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
        let manifestSHA256: String
        do {
            let data = try Data(contentsOf: manifestURL, options: [.mappedIfSafe])
            manifestSHA256 = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
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
            shadowRuntimeConfigurationV2: shadowRuntimeConfigurationV2,
            manifestSHA256: manifestSHA256
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
    var proposalsTruncated: Bool = false
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
        return TrafficSignVisionTwoStageCoreMLBackend
            .primarySignOnlyAssemblies(classified)
            .map(\.detection)
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
                calibratedConfidence: nil,
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
    /// Bounds per-frame Vision work on noisy detector output while retaining far
    /// more proposals than a normal road scene contains.
    private static let maximumProposalsPerRole = 12

    private let inferenceLock = NSLock()
    private let detectorModel: VNCoreMLModel
    private let classifierModel: VNCoreMLModel
    private let mappingsByClassID: [String: TrafficSignModelPackManifest.ClassMapping]
    private let unknownThreshold: Double

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
                    == "vision-scale-fit-letterbox-rgb-1024-v2",
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
        let admittedProposals = objects.filter { object in
            guard let label = object.labels.first,
                  object.confidence.isFinite,
                  Self.isValidNormalizedRegion(object.boundingBox) else { return false }
            return Self.isSignProposal(label.identifier)
                && Double(object.confidence) >= unknownThreshold
        }
        .sorted { $0.confidence > $1.confidence }
        let signObjects = Array(admittedProposals.prefix(Self.maximumProposalsPerRole))
        var classified: [TrafficSignSpatialAssembly.ClassifiedDetection] = []
        classified.reserveCapacity(signObjects.count)
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
        }

        let grouped = TrafficSignSpatialAssembly.assembleWithMembers(classified)
        return TrafficSignTwoStageInferenceResultV2(
            legacyDetections: grouped.map(\.detection),
            assemblies: grouped.compactMap(Self.shadowAssembly),
            detectorLatencyMs: detectorLatencyMs,
            classifierInvoked: !signObjects.isEmpty,
            classifierLatencyMs: classifierLatencyMs,
            proposalsTruncated: admittedProposals.count > Self.maximumProposalsPerRole
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
                calibratedConfidence: nil,
                boundingBox: contractBox,
                classThreshold: mapping?.threshold ?? unknownThreshold
            ),
            signRole: mapping?.signRole ?? .primarySign,
            restriction: mapping?.restriction,
            detectorRawScore: detectorConfidence,
            detectorCalibratedConfidence: nil,
            classifierRawScore: Double(classification.confidence),
            classifierCalibratedConfidence: nil
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
            supplementaryPlates: grouped.supplementaryPlates.enumerated().map { index, plate in
                .init(objectId: "\(assemblyId)-plate-\(index)", classId: plate.detection.rawClassId,
                    boundingBox: plate.detection.boundingBox, detectorScore: plate.detectorRawScore,
                    detectorCalibratedConfidence: plate.detectorCalibratedConfidence,
                    classifierRawScore: plate.classifierRawScore,
                    classifierCalibratedConfidence: plate.classifierCalibratedConfidence,
                    auxiliaryEvidence: plate.auxiliaryEvidence, classifierThreshold: plate.detection.classThreshold,
                    readability: .unreadable, restriction: nil)
            }
        )
    }

    /// Compatibility entry point; preserve every actual associated plate and uncertainty.
    static func primarySignOnlyAssemblies(
        _ classified: [TrafficSignSpatialAssembly.ClassifiedDetection],
        assemblyIDPrefix: String = UUID().uuidString.lowercased()
    ) -> [TrafficSignSpatialAssembly.GroupedAssembly] {
        TrafficSignSpatialAssembly.assembleWithMembers(classified, assemblyIDPrefix: assemblyIDPrefix)
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
    let applicabilityMapFix: TSRMapFix?
    let context: TrafficSignDetectionContext?
    let coordinate: TrafficSignCoordinate?
    let conditions: TrafficSignAnalysisConditions
    let sessionGeneration: UInt64
    let contextGeneration: UInt64
    let captureSessionId: String?
    let diagnosticCaptureEnabled: Bool

    init(
        context: TrafficSignDetectionContext?,
        applicabilityMapFix: TSRMapFix? = nil,
        coordinate: TrafficSignCoordinate? = nil,
        conditions: TrafficSignAnalysisConditions,
        sessionGeneration: UInt64 = 0,
        contextGeneration: UInt64 = 0,
        captureSessionId: String? = nil,
        diagnosticCaptureEnabled: Bool = false
    ) {
        self.context = context
        self.applicabilityMapFix = applicabilityMapFix
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
    let displayObservation: TrafficSignDisplayObservation?
    /// Independent OCR presentation evidence; never serialized into primary recognition/rules.
    let supplementaryText: TrafficSignSupplementaryTextObservation?
    let ocrPhase: TrafficSignSupplementaryOCRPhase
    let ocrAnnotation: TrafficSignSupplementaryOCRAnnotation?
    /// Latest actual read, including empty/failure, for immutable collection provenance.
    let ocrAttemptAnnotation: TrafficSignSupplementaryOCRAnnotation?
    /// A retry result updates supplementary evidence, never processes primary authority twice.
    let supplementaryOCROnly: Bool
    let ocrDiagnostic: String?
    let applicabilityDiagnostic: TSRApplicabilityDiagnostic?
    let roadPathDiagnostic: String?
    /// Raw recognition for the independently consented, non-authoritative annotation sink only.
    let annotationEvent: TrafficSignRecognitionEvent?
    let collectionDetections: [TrafficSignDetection]
    let collectionFrame: SignCollectionFrame?
    let collectionCaptureAt: Date?
    /// Boxes describe the mobile recognition window, not a full-size captured photo.
    let usesDetectorWindow: Bool

    init(
        event: TrafficSignRecognitionEvent,
        frameContext: TrafficSignDetectionContext?,
        frameSpeedKmh: Double? = nil,
        sessionGeneration: UInt64 = 0,
        contextGeneration: UInt64 = 0,
        captureSessionId: String? = nil,
        shadowEventV2: TrafficSignRecognitionEventV2? = nil,
        passageUpdate: TrafficSignPassageFinalizerUpdate = .idle,
        displayObservation: TrafficSignDisplayObservation? = nil,
        supplementaryText: TrafficSignSupplementaryTextObservation? = nil,
        ocrPhase: TrafficSignSupplementaryOCRPhase = .notRequired,
        ocrAnnotation: TrafficSignSupplementaryOCRAnnotation? = nil,
        ocrAttemptAnnotation: TrafficSignSupplementaryOCRAnnotation? = nil,
        supplementaryOCROnly: Bool = false,
        ocrDiagnostic: String? = nil,
        applicabilityDiagnostic: TSRApplicabilityDiagnostic? = nil,
        roadPathDiagnostic: String? = nil,
        annotationEvent: TrafficSignRecognitionEvent? = nil,
        collectionDetections: [TrafficSignDetection] = [],
        collectionFrame: SignCollectionFrame? = nil,
        collectionCaptureAt: Date? = nil,
        usesDetectorWindow: Bool = false
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
        self.displayObservation = displayObservation
        self.supplementaryText = supplementaryText
        self.ocrPhase = ocrPhase
        self.ocrAnnotation = ocrAnnotation
        self.ocrAttemptAnnotation = ocrAttemptAnnotation
        self.supplementaryOCROnly = supplementaryOCROnly
        self.ocrDiagnostic = ocrDiagnostic
        self.applicabilityDiagnostic = applicabilityDiagnostic
        self.roadPathDiagnostic = roadPathDiagnostic
        self.annotationEvent = annotationEvent
        self.collectionDetections = collectionDetections
        self.collectionFrame = collectionFrame
        self.collectionCaptureAt = collectionCaptureAt
        self.usesDetectorWindow = usesDetectorWindow
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
    typealias AdmissionMismatchHandler = @Sendable (String) -> Void

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
        var image: Image
        var orientation: CGImagePropertyOrientation
        var collectionSource: (image: Image, orientation: CGImagePropertyOrientation)? = nil
        let source: TrafficSignRecognitionSource
        let timestampUTC: Date
        let snapshot: TrafficSignFrameSnapshot
        var roadPathCapture: RoadPathCameraCapture? = nil
        var visualCalibration: VisualRoadCalibration? = nil
    }

    private struct SuccessfulProcessingResult {
        let event: TrafficSignRecognitionEvent
        let shadowEventV2: TrafficSignRecognitionEventV2?
        let passageUpdate: TrafficSignPassageFinalizerUpdate
        let applicabilityDiagnostic: TSRApplicabilityDiagnostic
        let roadPathDiagnostic: String?
        let displayDetections: [TrafficSignDetection]
        let annotationEvent: TrafficSignRecognitionEvent?
        let collectionDetections: [TrafficSignDetection]
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
    private let admissionMismatchHandler: AdmissionMismatchHandler?
    private let processingGate: TrafficSignWriteGate?
    private let shadowRuntimeV2: TrafficSignShadowRuntimeV2?
    private let shadowEvidenceStoreV2: TrafficSignShadowEvidenceStoreV2?
    private let callbackQueue: DispatchQueue
    private let inferenceQueue: DispatchQueue
    private let lock = NSLock()
    private var schedulingState = SchedulingState()
    private var fusion: TrafficSignFusionEngine
    private var annotationFusion: TrafficSignFusionEngine
    private var passageFinalizer = TrafficSignPassageFinalizer()
    private var applicabilitySession = TSRApplicabilitySession()
    private let roadPathSession: RoadPathSession?
    private let visualCalibrationProvider: @Sendable () -> VisualRoadCalibration?
    private let inferenceCropContext = CIContext(options: [.cacheIntermediates: false])
    private var applicabilityScope: TSRApplicabilityScope?
    private var liveAdmissionTrackID: String?
    private var supplementaryTextTracker = TrafficSignSupplementaryTextTracker()
    private var supplementaryOCRDiagnostic: String?
    private var supplementaryOCRDeferralCounts: [String: Int] = [:]
    private lazy var supplementaryPictogramCatalog = TrafficSignPresentationCatalog.bundled(
        countryCode: verifiedPack.manifest.countries.first ?? "DE")
    private var fusionSessionGeneration: UInt64?
    private var fusionContextGeneration: UInt64?

    init(
        verifiedPack: TrafficSignVerifiedModelPack,
        backend: any TrafficSignInferenceBackend,
        snapshotProvider: @escaping SnapshotProvider,
        callbackQueue: DispatchQueue = .main,
        eventHandler: @escaping EventHandler,
        unavailabilityHandler: UnavailabilityHandler? = nil,
        admissionMismatchHandler: AdmissionMismatchHandler? = nil,
        processingGate: TrafficSignWriteGate? = nil,
        shadowRuntimeV2: TrafficSignShadowRuntimeV2? = nil,
        shadowEvidenceStoreV2: TrafficSignShadowEvidenceStoreV2? = nil,
        roadPathSession: RoadPathSession? = nil,
        visualCalibrationProvider: @escaping @Sendable () -> VisualRoadCalibration? = { nil }
    ) {
        self.verifiedPack = verifiedPack
        self.roadPathSession = roadPathSession
        self.visualCalibrationProvider = visualCalibrationProvider
        self.passageFinalizer = TrafficSignPassageFinalizer(countryCode: verifiedPack.manifest.countries.first ?? "DE")
        self.backend = backend
        self.snapshotProvider = snapshotProvider
        self.callbackQueue = callbackQueue
        self.eventHandler = eventHandler
        self.unavailabilityHandler = unavailabilityHandler
        self.admissionMismatchHandler = admissionMismatchHandler
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
        annotationFusion = fusion
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
                snapshot: snapshot,
                roadPathCapture: RoadPathCameraCapture.capture(sampleBuffer, orientation: orientation, sourceClock: roadPathSession?.sourceClock()),
                visualCalibration: compatibleVisualCalibration(for: .pixelBuffer(pixelBuffer), orientation: orientation)
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
                snapshot: snapshot,
                visualCalibration: compatibleVisualCalibration(for: .pixelBuffer(pixelBuffer), orientation: orientation)
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
                snapshot: snapshot,
                visualCalibration: compatibleVisualCalibration(for: .cgImage(cgImage), orientation: orientation)
            )
        )
    }

    func stop() {
        lock.lock()
        schedulingState.stopped = true
        schedulingState.latestPendingLive = nil
        schedulingState.latestPendingStill = nil
        lock.unlock()
        roadPathSession?.invalidateOverlay()
        inferenceQueue.async { [weak self] in self?.supplementaryTextTracker.reset() }
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
            var item = item
            let dimensions = Self.orientedDimensions(for: item.image, orientation: item.orientation)
            let frameScope = TSRApplicabilityScope(sessionId: item.snapshot.captureSessionId ?? "no-session",
                bundleId: item.snapshot.context?.sourceSignature.bundleSHA256 ?? "unverified",
                cameraGeometryId: "mobile-right-1024-v1:\(item.orientation.rawValue):\(dimensions.width)x\(dimensions.height):visual=\(item.visualCalibration?.revision ?? "none")",
                generation: item.snapshot.sessionGeneration, contextGeneration: item.snapshot.contextGeneration,
                traversalEpoch: item.snapshot.context?.traversalEpoch ?? 0)
            var preparedRoadPath: RoadPathPreparedFrame?
            var preparationUnavailableReason = "frame_input_unavailable"
            let prepare = { () -> Bool in
                guard self.canDeliverCallback, self.isWorkItemStillCurrent(item) else { return false }
                if let session = self.roadPathSession {
                    let thermal = ProcessInfo.processInfo.thermalState
                    if thermal == .serious || thermal == .critical {
                        preparationUnavailableReason = "thermal_paused"; session.invalidateOverlay()
                    } else if let capture = item.roadPathCapture, case .pixelBuffer(let pixel) = item.image,
                              let frame = capture.frame(pixel: pixel, orientation: item.orientation, visualCalibration: item.visualCalibration) {
                        preparedRoadPath = session.prepare(frame: frame, frameId: item.frameId, scope: frameScope,
                            shouldPublish: { self.canDeliverCallback && self.isWorkItemStillCurrent(item) })
                    } else { session.invalidateOverlay() }
                }
                return true
            }
            let token = TrafficSignGenerationToken(session: item.snapshot.sessionGeneration, context: item.snapshot.contextGeneration)
            let admitted: Bool
            if let gate = self.processingGate { admitted = gate.permit(for: token)?.consume(prepare) ?? false }
            else { admitted = prepare() }
            guard admitted else { self.discardStaleWorkItem(); return }
            // The exact same admitted pixel buffer reaches TSR only after geometry is ready.
            let startedAt = ProcessInfo.processInfo.systemUptime
            if let preparedRoadPath { TrafficSignRuntimeLog.lanePreparation(preparedRoadPath, tsrStartedAt: startedAt) }
            do {
                // One mobile window feeds detection, classification and auxiliary reads.
                // Results remain in window coordinates; no full-frame remapping.
                let source: CIImage
                switch item.image {
                case .pixelBuffer(let pixel): source = CIImage(cvPixelBuffer: pixel)
                case .cgImage(let image): source = CIImage(cgImage: image)
                }
                let input = try TrafficSignDetectorInput(source: source, orientation: item.orientation,
                    context: self.inferenceCropContext)
                item.collectionSource = (item.image, item.orientation)
                item.image = .cgImage(input.image)
                item.orientation = .up
                let rawDetections: [TrafficSignDetection]
                let rawTwoStage: TrafficSignTwoStageInferenceResultV2?
                if let twoStageBackend = self.backend as? any TrafficSignShadowInferenceBackendV2 {
                    let result: TrafficSignTwoStageInferenceResultV2
                    switch item.image {
                    case .pixelBuffer(let pixel): result = try twoStageBackend.shadowInference(in: pixel, orientation: item.orientation)
                    case .cgImage(let image): result = try twoStageBackend.shadowInference(in: image, orientation: item.orientation)
                    }
                    rawDetections = result.legacyDetections; rawTwoStage = result
                } else {
                    switch item.image {
                    case .pixelBuffer(let pixel): rawDetections = try self.backend.detections(in: pixel, orientation: item.orientation)
                    case .cgImage(let image): rawDetections = try self.backend.detections(in: image, orientation: item.orientation)
                    }
                    rawTwoStage = nil
                }
                let detections = rawDetections
                let verifiedZoneIndices = Set(detections.enumerated().filter {
                    $0.element.semantic.kind == .zoneStart
                }.sorted { $0.element.rawScore > $1.element.rawScore }.prefix(2).compactMap { index, detection -> Int? in
                    guard let speed = detection.semantic.value,
                          let crop = self.primaryPanelCrop(source:self.nativeAuxiliarySource(item),box:detection.boundingBox),
                          TrafficSignSupplementaryOCR.verifiesZone(in: crop, speed: speed) else { return nil }
                    return index
                })
                let twoStageResult = rawTwoStage
                let latencyMs = max(
                    0,
                    (ProcessInfo.processInfo.systemUptime - startedAt) * 1_000
                )
                let process = { () -> SuccessfulProcessingResult in
                    if self.fusionSessionGeneration != item.snapshot.sessionGeneration
                        || self.fusionContextGeneration != item.snapshot.contextGeneration {
                        self.fusion.reset(); self.annotationFusion.reset()
                        self.passageFinalizer.reset()
                        self.applicabilitySession.reset()
                        self.shadowRuntimeV2?.reset()
                        self.supplementaryTextTracker.reset()
                        self.fusionSessionGeneration = item.snapshot.sessionGeneration
                        self.fusionContextGeneration = item.snapshot.contextGeneration
                    }
                    let scope = frameScope
                    let candidates = detections.prefix(TSRApplicabilityConfiguration.maxCandidates).enumerated().map { index, detection in
                        let score = self.verifiedPack.manifest.calibration.runtimeOutput == .rawScore
                            ? detection.rawScore : detection.calibratedConfidence ?? -.infinity
                        return TSRApplicabilityCandidate(candidateId: "\(item.frameId):\(index)", semanticKey: detection.semantic.stableKey,
                            box: TSRApplicabilityBox(x: detection.boundingBox.x, y: detection.boundingBox.y,
                                width: detection.boundingBox.width, height: detection.boundingBox.height),
                            rawScore: detection.rawScore, recognitionEligible: detection.isQualifiedObservation(runtimeOutput: self.verifiedPack.manifest.calibration.runtimeOutput, unknownThreshold: self.verifiedPack.manifest.thresholds.unknown),
                            assemblyId: detection.assemblyId, recognitionScore: score.isFinite ? score : nil,
                            calibratedConfidence: detection.calibratedConfidence, rawClassId: detection.rawClassId,
                            detectorRawScore: detection.detectorRawScore, classifierRawScore: detection.classifierRawScore)
                    }
                    let batch = TSRFrameCandidateBatch(schemaVersion: 1, frameId: item.frameId,
                        capturedAtMs: item.timestampUTC.timeIntervalSince1970 * 1000, scope: scope, status: "analyzed",
                        candidates: candidates, truncated: detections.count > TSRApplicabilityConfiguration.maxCandidates
                            || twoStageResult?.proposalsTruncated == true,
                        rawCandidateCount: detections.count, modelId: self.verifiedPack.detectorArtifact.sha256,
                        preprocessingId: self.verifiedPack.manifest.preprocessing.version,
                        road: item.snapshot.applicabilityMapFix?.snapshot(scope: scope),
                        country: self.verifiedPack.manifest.countries.count == 1 ? self.verifiedPack.manifest.countries.first : nil)
                    if TSRApplicabilityConfiguration.defaultMode != "shadow", self.applicabilityScope != scope {
                        self.fusion.reset(); self.annotationFusion.reset(); self.passageFinalizer.reset()
                        self.supplementaryTextTracker.reset()
                    }
                    if self.applicabilityScope != scope { self.liveAdmissionTrackID = nil }
                    self.applicabilityScope = scope
                    let applicability = self.applicabilitySession.evaluate(batch,
                        verifiedZones: Set(verifiedZoneIndices.map { "\(item.frameId):\($0)" }))
                    let roadPathDiagnostic: String?
                    if let session = self.roadPathSession {
                        func skipped(_ reason: String) -> String? {
                            session.invalidateOverlay()
                            let value: [String: Any] = ["schemaVersion": 1, "mode": "shadow", "frameId": item.frameId,
                                "reason": reason, "capturedAtSeconds": item.timestampUTC.timeIntervalSince1970,
                                "captureClockKnown": false, "geometryId": "unavailable:\(dimensions.width)x\(dimensions.height)",
                                "boundaries": [], "associations": []]
                            return (try? JSONSerialization.data(withJSONObject: value)).flatMap { String(data: $0, encoding: .utf8) }
                        }
                        if let preparedRoadPath {
                            roadPathDiagnostic = session.evaluate(prepared: preparedRoadPath, diagnostic: applicability,
                                tsrStartedAtUptime: startedAt, associateSigns: false)
                                ?? skipped("path_processing_failed")
                        } else { roadPathDiagnostic = skipped(preparationUnavailableReason) }
                    } else { roadPathDiagnostic = nil }
                    let exitWithheld = TSRMotorwayExitPolicy.withheldCandidates(batch)
                    let accessWithheld = self.applicabilitySession.accessRoadWithheldCandidateIDs
                    let liveWithheld = self.applicabilitySession.liveWithheldCandidateIDs
                    let exitEligibleDetections = detections.enumerated().filter {
                        !exitWithheld.contains("\(item.frameId):\($0.offset)") && !accessWithheld.contains("\(item.frameId):\($0.offset)")
                            && !liveWithheld.contains("\(item.frameId):\($0.offset)")
                    }.map(\.element)
                    if let previous = self.liveAdmissionTrackID,
                       applicability.decisions.contains(where: { $0.trackId == previous && TSRLiveSignAdmission.blocks($0) }) {
                        // Withheld evidence is cancellation, never an analyzed disappearance.
                        self.fusion.reset(); self.passageFinalizer.reset(); self.liveAdmissionTrackID = nil
                    }
                    if !exitWithheld.isEmpty {
                        // Withholding is not an analyzed disappearance and must
                        // never finalize an earlier view of the same exit sign.
                        self.fusion.reset(); self.passageFinalizer.reset()
                    }
                    let enforcing = TSRApplicabilityConfiguration.defaultMode != "shadow"
                    if enforcing, let activeID = self.passageFinalizer.activePhysicalTrackID,
                       !applicability.tracks.contains(where: { $0.trackId == activeID }) {
                        self.passageFinalizer.reset() // Expiry cancels without synthesizing passage.
                    }
                    let activeTrackID = self.passageFinalizer.activePhysicalTrackID
                    let eligibleTracks = applicability.tracks.filter { track in
                        applicability.decisions.contains { $0.trackId == track.trackId && $0.immediateEligible }
                    }.sorted {
                        if $0.trackId == activeTrackID { return true }; if $1.trackId == activeTrackID { return false }
                        let a = $0.samples.last?.candidate.rawScore ?? 0, b = $1.samples.last?.candidate.rawScore ?? 0
                        return a == b ? $0.trackId < $1.trackId : a > b
                    }
                    let selectedTrack = eligibleTracks.first
                    let selectedIndex = selectedTrack?.samples.last?.candidate.candidateId.split(separator: ":").last.flatMap { Int($0) }
                    let selectedDetections = enforcing ? selectedIndex.map { [detections[$0]] } ?? [] : exitEligibleDetections
                    let physicalSamples = selectedTrack?.samples.filter {
                        $0.candidate.recognitionEligible && batch.capturedAtMs - $0.capturedAtMs <= Double(self.verifiedPack.manifest.thresholds.confirmationWindowMs)
                    } ?? []
                    var event = self.fusion.ingest(
                        detections: selectedDetections,
                        source: item.source,
                        timestamp: item.timestampUTC,
                        roadContext: item.snapshot.context,
                        latencyMs: latencyMs,
                        thermalState: item.snapshot.conditions.thermalState,
                        frameID: item.frameId,
                        driveSessionID: item.snapshot.captureSessionId,
                        physicalTrackID: enforcing ? selectedTrack?.trackId : nil,
                        physicalEvidenceFrames: enforcing ? physicalSamples.count : nil,
                        physicalHasConfirmedEvidence: enforcing ? physicalSamples.contains {
                            ($0.candidate.recognitionScore ?? -.infinity) >= self.verifiedPack.manifest.thresholds.confirmed
                        } : nil
                    )
                    let eventTrackID: String?
                    if enforcing { eventTrackID = selectedTrack?.trackId }
                    else if let candidate = event.candidate, let index = detections.firstIndex(where: { $0.rawClassId == candidate.rawClassId && $0.boundingBox == candidate.boundingBox }) {
                        eventTrackID = applicability.tracks.first { $0.samples.last?.candidate.candidateId == "\(item.frameId):\(index)" }?.trackId
                    } else { eventTrackID = nil }
                    event.applicabilityDecision = applicability.decisions.first { $0.trackId == eventTrackID }
                    if event.candidate != nil { self.liveAdmissionTrackID = eventTrackID }
                    // Raw confirmation remains available only to the annotation sink. It is
                    // never sent to preview, display, finalizer, resolver or correction storage.
                    var annotationEvent: TrafficSignRecognitionEvent? = nil
                    if enforcing || !exitWithheld.isEmpty || !accessWithheld.isEmpty || !liveWithheld.isEmpty {
                        var raw = self.annotationFusion.ingest(detections: detections, source: item.source,
                            timestamp: item.timestampUTC, roadContext: item.snapshot.context, latencyMs: latencyMs,
                            thermalState: item.snapshot.conditions.thermalState, frameID: item.frameId,
                            driveSessionID: item.snapshot.captureSessionId)
                        if let candidate = raw.candidate, let index = detections.firstIndex(where: {
                            $0.rawClassId == candidate.rawClassId && $0.boundingBox == candidate.boundingBox
                        }), let track = applicability.tracks.first(where: {
                            $0.samples.last?.candidate.candidateId == "\(item.frameId):\(index)"
                        }) {
                            raw.applicabilityDecision = applicability.decisions.first { $0.trackId == track.trackId }
                        }
                        annotationEvent = raw
                    }
                    let canConsumePassage = self.applicabilitySession.canConsumePassage(activeTrackId: activeTrackID,
                        selectedTrackId: selectedTrack?.trackId, mode: TSRApplicabilityConfiguration.defaultMode)
                    var passageUpdate = self.passageFinalizer.ingest(
                        event,
                        sessionGeneration: item.snapshot.sessionGeneration,
                        contextGeneration: item.snapshot.contextGeneration,
                        frameCoordinate: item.snapshot.coordinate,
                        frameSpeedKmh: item.snapshot.conditions.speedKmh,
                        // Speed-limit activation is based on an admitted live
                        // frame, not on the vehicle's current speed.
                        calibratedActivationEligible: item.source == .liveFrame && canConsumePassage && exitWithheld.isEmpty
                    )
                    if case .committed(var passage) = passageUpdate {
                        passage.applicabilityDecision = self.applicabilitySession.passageDecision(trackId: passage.physicalTrackID)
                        passageUpdate = passage.permitsApplicability() ? .committed(passage) : .idle
                    }
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
                        passageUpdate: passageUpdate,
                        applicabilityDiagnostic: applicability,
                        roadPathDiagnostic: roadPathDiagnostic,
                        displayDetections: selectedDetections,
                        annotationEvent: annotationEvent,
                        collectionDetections: detections
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
                    self.roadPathSession?.invalidatePreparedOverlay(frameId: item.frameId)
                    notifyAdmissionMismatch(item, reason: "processing_gate_rejected")
                    self.discardStaleWorkItem()
                    return
                }
                let displayObservation = TrafficSignDisplayObservation.accepted(
                    from: processed.displayDetections, timestamp: item.timestampUTC,
                    classifierCheckpointSHA256: self.verifiedPack.manifest.classifier?.sourceCheckpoint.sha256
                )
                let finishPrimary = { (phase: TrafficSignSupplementaryOCRPhase, annotation: TrafficSignSupplementaryOCRAnnotation?) in
                    self.complete(item: item, event: processed.event, shadowEventV2: processed.shadowEventV2,
                        passageUpdate: processed.passageUpdate, displayObservation: displayObservation,
                        supplementaryText: annotation?.supplementaryText, ocrPhase: phase, ocrAnnotation: annotation,
                        ocrDiagnostic: self.supplementaryOCRDiagnostic, applicabilityDiagnostic: processed.applicabilityDiagnostic,
                        roadPathDiagnostic: processed.roadPathDiagnostic, annotationEvent: processed.annotationEvent,
                        collectionDetections: processed.collectionDetections)
                }
                switch self.prepareSupplementaryOCR(item: item, processed: processed) {
                case .notRequired:
                    finishPrimary(.notRequired, nil)
                case .cached(let annotation):
                    finishPrimary(.completed, annotation)
                case .perform(let attempt):
                    // Preserve the initial numeric read's publication boundary.
                    // Later, clearer reads update only supplementary evidence.
                    let waitsForInitialRead = attempt.number == 1 && attempt.primary.speedKmh != nil
                    finishPrimary(waitsForInitialRead ? .pending : (attempt.cachedAnnotation == nil ? .notRequired : .completed),
                        attempt.cachedAnnotation)
                    let actualRead = self.performSupplementaryOCR(item: item, attempt: attempt,
                        primaryBoxes: processed.collectionDetections.map(\.boundingBox))
                    self.deliverOCRCompletion(item: item, processed: processed,
                        displayObservation: displayObservation,
                        annotation: self.supplementaryTextTracker.presentationAnnotation(at: item.timestampUTC),
                        attemptAnnotation: actualRead, supplementaryOnly: !waitsForInitialRead)
                }
            } catch {
                self.roadPathSession?.invalidatePreparedOverlay(frameId: item.frameId)
                self.handleInferenceFailure(item: item, error: error)
            }
        }
    }

    private func nativeAuxiliarySource(_ item: WorkItem) -> CIImage {
        let original = item.collectionSource ?? (item.image,item.orientation)
        let source: CIImage
        switch original.0 {
        case .pixelBuffer(let pixel): source = CIImage(cvPixelBuffer:pixel)
        case .cgImage(let image): source = CIImage(cgImage:image)
        }
        return TrafficSignDetectorInput.nativeWindow(source:source,orientation:original.1)
    }
    private func nativeAuxiliaryBounds(_ item: WorkItem) -> (size:Int,content:TrafficSignPlateRect) {
        let original = item.collectionSource ?? (item.image,item.orientation)
        let dimensions = Self.orientedDimensions(for:original.0,orientation:original.1)
        let size = dimensions.height
        return (size,.init(x:max(0,size-dimensions.width),y:0,width:min(size,dimensions.width),height:size))
    }
    /// Read only a native primary-plus-lower rectangle, after primary admission.
    /// OCR publishes a separate restriction-text annotation. It cannot modify
    /// fusion, passages, resolver assertions, or primary traffic-sign semantics.
    private func prepareSupplementaryOCR(
        item: WorkItem,
        processed: SuccessfulProcessingResult
    ) -> TrafficSignSupplementaryTextTracker.Admission {
        supplementaryOCRDiagnostic = nil
        guard item.source == .liveFrame, item.snapshot.conditions.appIsActive,
              canDeliverCallback, isWorkItemStillCurrent(item) else {
            supplementaryTextTracker.reset()
            return .notRequired
        }
        let candidate = processed.event.candidate
        let numeric = candidate.map {
            [TrafficSignSemanticKind.maximumSpeed.rawValue, TrafficSignSemanticKind.zoneStart.rawValue].contains($0.semanticKind)
                && $0.unit == "km/h" && ($0.value ?? 0) > 0
        } ?? false
        let numericDetection = numeric ? processed.displayDetections.first { detection in
            detection.rawClassId == candidate?.rawClassId && detection.boundingBox == candidate?.boundingBox
                && detection.semantic.value == candidate?.value && detection.semantic.kind.rawValue == candidate?.semanticKind
        } : nil
        let acceptedDisplay = TrafficSignDisplayObservation.acceptedDetection(from: processed.displayDetections)
        let pictogram = acceptedDisplay.flatMap { detection -> TrafficSignDetection? in
            guard let catalog = supplementaryPictogramCatalog,
                  catalog.classifierCheckpointSHA256 == verifiedPack.manifest.classifier?.sourceCheckpoint.sha256,
                  let sign = catalog.sign(for: detection.rawClassId), sign.displayEligible,
                  sign.imagePath != nil else { return nil }
            return detection
        }
        let primary = (numericDetection ?? pictogram).map {
            TrafficSignSupplementaryTextTracker.Primary(classID: $0.rawClassId,
                speedKmh: numericDetection == nil ? nil : $0.semantic.value, box: $0.boundingBox,
                physicalSignID: numericDetection == nil ? nil : (processed.event.applicabilityDecision?.trackId ?? candidate?.trackId))
        }
        let native = nativeAuxiliaryBounds(item)
        let dimensions = (width:native.size,height:native.size)
        let crop = primary.flatMap { TrafficSignSupplementaryOCRGeometry.cropRect(primaryBox: $0.box,
            imageWidth: dimensions.width, imageHeight: dimensions.height) }
        let thermal = ProcessInfo.processInfo.thermalState
        let canRead = item.snapshot.conditions.thermalState != .critical && thermal != .critical
        if let primary, !canRead || crop == nil {
            let reason = canRead ? "native_roi_too_small_or_clipped" : "thermal_deferred"
            let count = (supplementaryOCRDeferralCounts[reason] ?? 0) + 1
            supplementaryOCRDeferralCounts[reason] = count
            if count == 1 || count % 20 == 0 {
                supplementaryOCRDiagnostic = "ocr_deferred reason=\(reason) count=\(count) class=\(primary.classID)"
            }
        }
        return supplementaryTextTracker.begin(primary: primary, frameID: item.frameId, at: item.timestampUTC,
            confirmed: processed.event.state == .confirmed, evidenceFrames: candidate?.evidenceFrames ?? 0,
            nativeROISize: crop.map { CGSize(width: $0.width, height: $0.height / 2) }, canRead: canRead)
    }

    private func performSupplementaryOCR(item: WorkItem, attempt: TrafficSignSupplementaryTextTracker.Attempt,
                                         primaryBoxes: [TrafficSignNormalizedRect])
        -> TrafficSignSupplementaryOCRAnnotation? {
        guard canDeliverCallback, isWorkItemStillCurrent(item) else { return nil }
        let started = ProcessInfo.processInfo.systemUptime
        let thermal = ProcessInfo.processInfo.thermalState
        guard thermal != .critical,
              let crop = supplementaryOCRCrop(source:nativeAuxiliarySource(item),primaryBox:attempt.primary.box) else {
            supplementaryTextTracker.deferAttempt(attempt)
            supplementaryOCRDiagnostic = "ocr_deferred reason=thermal_or_crop_changed attempt=\(attempt.number)"
            return nil
        }
        var read = TrafficSignSupplementaryOCRRead(rawText: nil,
            modelVersion: TrafficSignSupplementaryOCR.shared.modelVersion, readStatus: .failed)
        do { read = try TrafficSignSupplementaryOCR.shared.read(in: crop) }
        catch {
            read = TrafficSignSupplementaryOCRRead(rawText: nil,
                modelVersion: TrafficSignSupplementaryOCR.shared.modelVersion, readStatus: .failed)
            TrafficSignRuntimeLog.recoveredAuxiliaryFailure(stage: "supplementary_text", error: error)
        }
        guard canDeliverCallback, isWorkItemStillCurrent(item) else { return nil }
        let native = nativeAuxiliaryBounds(item)
        let dimensions = (width:native.size,height:native.size)
        let roi = TrafficSignSupplementaryOCRGeometry.cropRect(primaryBox: attempt.primary.box,
            imageWidth: dimensions.width, imageHeight: dimensions.height).flatMap { rect -> TrafficSignNormalizedRect? in
                guard let plate = read.plateRect else { return nil }
                return TrafficSignNormalizedRect(x: (rect.minX + Double(plate.x)) / Double(dimensions.width),
                    y: (rect.minY + Double(plate.y)) / Double(dimensions.height),
                    width: Double(plate.width) / Double(dimensions.width), height: Double(plate.height) / Double(dimensions.height))
            }
        supplementaryOCRDiagnostic = TrafficSignSupplementaryOCRDiagnostics.attempt(read: read,
            classID: attempt.primary.classID, frameID: item.frameId, width: crop.width, height: crop.height / 2,
            number: attempt.number, durationMilliseconds: (ProcessInfo.processInfo.systemUptime - started) * 1000)
        let evidence = TrafficSignSupplementaryOCRGeometry.cropRect(primaryBox: attempt.primary.box,
            imageWidth: dimensions.width, imageHeight: dimensions.height).flatMap { context -> TrafficSignConditionalAssemblyEvidence? in
                guard let scan = read.scan else { return nil }
                return .init(sourceWidth: dimensions.width, sourceHeight: dimensions.height,
                    sourceFrameID: item.frameId, capturedAt: item.timestampUTC, physicalSignID: attempt.physicalSignID,
                    primaryBox: attempt.primary.box,
                    contextRect: .init(x: Int(context.minX), y: Int(context.minY), width: Int(context.width), height: Int(context.height)),
                    otherPrimaryBoxes: primaryBoxes.filter { $0 != attempt.primary.box }, scan: scan,
                    qualityDecision: read.decision, passes: read.passes,nativeContentRect:native.content)
            }
        return supplementaryTextTracker.finish(attempt, read: read, ocrBoundingBox: roi, assemblyEvidence: evidence)
    }

    private func supplementaryOCRCrop(source: CIImage, primaryBox: TrafficSignNormalizedRect) -> CGImage? {
        let upright = source
        let extent = upright.extent
        guard let rect = TrafficSignSupplementaryOCRGeometry.cropRect(primaryBox: primaryBox,
            imageWidth: Int(extent.width), imageHeight: Int(extent.height)) else { return nil }
        let native = CGRect(x: extent.minX + rect.minX, y: extent.maxY - rect.maxY,
                            width: rect.width, height: rect.height)
        return inferenceCropContext.createCGImage(upright, from: native)
    }

    private func primaryPanelCrop(source:CIImage,box:TrafficSignNormalizedRect) -> CGImage? {
        guard box.isValid else { return nil }
        let upright = source
        let extent = upright.extent
        let rect = CGRect(x: extent.minX + floor(box.x * extent.width),
            y: extent.maxY - ceil((box.y + box.height) * extent.height),
            width: ceil(box.width * extent.width), height: ceil(box.height * extent.height))
        guard rect.width >= 48, rect.height >= 48, rect.width * rect.height <= 1_000_000,
              extent.contains(rect) else { return nil }
        return inferenceCropContext.createCGImage(upright, from: rect)
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

    private func compatibleVisualCalibration(for image: Image, orientation: CGImagePropertyOrientation) -> VisualRoadCalibration? {
        let dimensions = Self.orientedDimensions(for: image, orientation: orientation)
        guard let calibration = visualCalibrationProvider(),
              calibration.compatible(width: dimensions.width, height: dimensions.height,
                  orientationKey: "rear:exif:\(orientation.rawValue)") else { return nil }
        return calibration
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
        passageUpdate: TrafficSignPassageFinalizerUpdate,
        displayObservation: TrafficSignDisplayObservation?,
        supplementaryText: TrafficSignSupplementaryTextObservation? = nil,
        ocrPhase: TrafficSignSupplementaryOCRPhase = .notRequired,
        ocrAnnotation: TrafficSignSupplementaryOCRAnnotation? = nil,
        ocrDiagnostic: String? = nil,
        applicabilityDiagnostic: TSRApplicabilityDiagnostic? = nil,
        roadPathDiagnostic: String? = nil,
        annotationEvent: TrafficSignRecognitionEvent? = nil,
        collectionDetections: [TrafficSignDetection] = []
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
                passageUpdate: passageUpdate,
                displayObservation: displayObservation,
                supplementaryText: supplementaryText,
                ocrPhase: ocrPhase,
                ocrAnnotation: ocrAnnotation,
                ocrDiagnostic: ocrDiagnostic,
                applicabilityDiagnostic: applicabilityDiagnostic,
                roadPathDiagnostic: roadPathDiagnostic,
                annotationEvent: annotationEvent,
                collectionDetections: collectionDetections,
                collectionFrame: makeCollectionFrame(item),
                collectionCaptureAt: item.roadPathCapture.flatMap { $0.clockKnown ? Date(timeIntervalSince1970: $0.capturedAtSeconds) : nil },
                usesDetectorWindow: true
            )
            callbackQueue.async { [weak self, eventHandler] in
                guard self?.canDeliverCallback == true else { return }
                eventHandler(emission)
            }
        }
        if let next { perform(next) }
    }

    private func deliverOCRCompletion(item: WorkItem, processed: SuccessfulProcessingResult,
                                      displayObservation: TrafficSignDisplayObservation?,
                                      annotation: TrafficSignSupplementaryOCRAnnotation?,
                                      attemptAnnotation: TrafficSignSupplementaryOCRAnnotation?,
                                      supplementaryOnly: Bool) {
        guard canDeliverCallback, isWorkItemStillCurrent(item) else { return }
        let emission = TrafficSignRuntimeEmission(event: processed.event, frameContext: item.snapshot.context,
            frameSpeedKmh: item.snapshot.conditions.speedKmh, sessionGeneration: item.snapshot.sessionGeneration,
            contextGeneration: item.snapshot.contextGeneration, captureSessionId: item.snapshot.captureSessionId,
            shadowEventV2: processed.shadowEventV2, passageUpdate: processed.passageUpdate,
            displayObservation: displayObservation, supplementaryText: annotation?.supplementaryText,
            ocrPhase: .completed, ocrAnnotation: annotation, ocrAttemptAnnotation: attemptAnnotation,
            supplementaryOCROnly: supplementaryOnly, ocrDiagnostic: supplementaryOCRDiagnostic,
            applicabilityDiagnostic: processed.applicabilityDiagnostic,
            roadPathDiagnostic: processed.roadPathDiagnostic, annotationEvent: processed.annotationEvent,
            collectionDetections: processed.collectionDetections, collectionFrame: makeCollectionFrame(item),
                collectionCaptureAt: item.roadPathCapture.flatMap { $0.clockKnown ? Date(timeIntervalSince1970: $0.capturedAtSeconds) : nil },
            usesDetectorWindow: true)
        callbackQueue.async { [weak self, eventHandler] in
            guard let self, self.canDeliverCallback, self.isWorkItemStillCurrent(item) else { return }
            eventHandler(emission)
        }
    }

    private func makeCollectionFrame(_ item: WorkItem) -> SignCollectionFrame? {
        guard item.source == .liveFrame else { return nil }
        return SignCollectionFrame(token: item.frameId, crop: { box in
            let native = item.collectionSource ?? (item.image, item.orientation)
            let source: CIImage
            switch native.0 { case .pixelBuffer(let buffer): source = CIImage(cvPixelBuffer: buffer); case .cgImage(let image): source = CIImage(cgImage: image) }
            let upright = TrafficSignDetectorInput.nativeWindow(source: source, orientation: native.1)
            let size = Int(upright.extent.height)
            let geometry = try SignCollectionCropGeometry(width: size, height: size, box: box)
            let bounds = geometry.actual
            let rect = CGRect(x: bounds[0], y: size - bounds[3],
                width: bounds[2] - bounds[0], height: bounds[3] - bounds[1])
            let color = CGColorSpace(name: CGColorSpace.sRGB)!
            let ci = CIContext(options: [.cacheIntermediates: false])
            guard let image = ci.createCGImage(upright, from: rect, format: .RGBA8, colorSpace: color),
                  let rgb = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8, bytesPerRow: image.width * 4,
                      space: color, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { throw SignCollectionError.storage }
            rgb.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            guard let result = rgb.makeImage() else { throw SignCollectionError.storage }
            return try SignCollectionCrop.encode(cropped: result, geometry: geometry, sourceWidth: size, sourceHeight: size)
        })
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
                notifyAdmissionMismatch(item, reason: "inference_failure_processing_gate_rejected")
                discardStaleWorkItem()
                return
            }
            return
        }
        guard isWorkItemStillCurrent(item) else {
            notifyAdmissionMismatch(item, reason: "inference_failure_stale_frame")
            discardStaleWorkItem()
            return
        }
        handleAdmittedInferenceFailure(item: item, error: error)
    }

    private func notifyAdmissionMismatch(_ item: WorkItem, reason: String) {
        guard let admissionMismatchHandler else { return }
        let current = snapshotProvider()
        let currentSession = current.map { String($0.sessionGeneration) } ?? "none"
        let currentContext = current.map { String($0.contextGeneration) } ?? "none"
        let currentCapture = current?.captureSessionId ?? "none"
        let detail = "reason=\(reason) frame=\(item.snapshot.sessionGeneration):\(item.snapshot.contextGeneration):\(item.snapshot.captureSessionId ?? "none") current=\(currentSession):\(currentContext):\(currentCapture)"
        callbackQueue.async {
            admissionMismatchHandler(detail)
        }
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
        admissionMismatchHandler: TrafficSignRuntime.AdmissionMismatchHandler? = nil,
        processingGate: TrafficSignWriteGate? = nil,
        roadPathSession: RoadPathSession? = nil,
        visualCalibrationProvider: @escaping @Sendable () -> VisualRoadCalibration? = { nil }
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
                admissionMismatchHandler: admissionMismatchHandler,
                processingGate: processingGate,
                shadowRuntimeV2: shadowRuntimeV2,
                shadowEvidenceStoreV2: shadowEvidenceStoreV2,
                roadPathSession: roadPathSession,
                visualCalibrationProvider: visualCalibrationProvider
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

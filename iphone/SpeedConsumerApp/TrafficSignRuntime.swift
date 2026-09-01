@preconcurrency import AVFoundation
@preconcurrency import CoreML
import CoreGraphics
import CryptoKit
import Foundation
import ImageIO
@preconcurrency import Vision

#if TRAFFIC_SIGN_RUNTIME_STANDALONE_TYPECHECK
protocol DriveVideoFrameConsumer: AnyObject {
    func consumeVideoFrame(
        _ sampleBuffer: CMSampleBuffer,
        orientation: CGImagePropertyOrientation
    )
}
#endif

// MARK: - Verified local model packs

enum TrafficSignRuntimeUnavailableCode: String, Codable, Sendable {
    case modelPackDirectoryMissing = "model_pack_directory_missing"
    case modelPackAuthenticationRequired = "model_pack_authentication_required"
    case manifestMissing = "manifest_missing"
    case manifestInvalid = "manifest_invalid"
    case noCompatibleArtifact = "no_compatible_artifact"
    case unsafeArtifactPath = "unsafe_artifact_path"
    case artifactMissing = "artifact_missing"
    case artifactHashMismatch = "artifact_hash_mismatch"
    case artifactUnreadable = "artifact_unreadable"
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
}

enum TrafficSignModelPackDirectoryLoader {
    static let manifestFileName = "manifest.json"

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
        let actualDigest: String
        do {
            actualDigest = try TrafficSignArtifactSHA256.hexDigest(
                of: artifactURL,
                fileManager: fileManager
            )
        } catch let error as TrafficSignRuntimeUnavailability {
            throw error
        } catch {
            throw TrafficSignRuntimeUnavailability(
                code: .artifactUnreadable,
                detail: "The selected TSR model artifact cannot be read."
            )
        }
        guard actualDigest == artifact.sha256 else {
            throw TrafficSignRuntimeUnavailability(
                code: .artifactHashMismatch,
                detail: "The selected TSR model artifact failed its SHA-256 integrity check."
            )
        }

        return TrafficSignVerifiedModelPack(
            directoryURL: rootURL,
            manifest: manifest,
            detectorArtifact: artifact,
            detectorArtifactURL: artifactURL
        )
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

/// Raw files are hashed byte-for-byte. Directory artifacts use a deterministic
/// `tsr-directory-sha256-v1` digest over sorted relative paths, sizes, and file
/// contents. Symlinks and special files are never followed.
enum TrafficSignArtifactSHA256 {
    private static let chunkSize = 1_048_576

    static func hexDigest(
        of artifactURL: URL,
        fileManager: FileManager = .default
    ) throws -> String {
        let values = try artifactURL.resourceValues(forKeys: [
            .isRegularFileKey,
            .isDirectoryKey,
            .isSymbolicLinkKey,
        ])
        guard values.isSymbolicLink != true else {
            throw TrafficSignRuntimeUnavailability(
                code: .unsafeArtifactPath,
                detail: "The TSR model artifact cannot be a symbolic link."
            )
        }
        if values.isRegularFile == true {
            var hasher = SHA256()
            try update(&hasher, withContentsOf: artifactURL)
            return hex(hasher.finalize())
        }
        guard values.isDirectory == true else {
            throw TrafficSignRuntimeUnavailability(
                code: .artifactUnreadable,
                detail: "The TSR model artifact is not a file or directory."
            )
        }

        let rootURL = artifactURL.standardizedFileURL
        var enumerationError: Error?
        guard let enumerator = fileManager.enumerator(
            at: rootURL,
            includingPropertiesForKeys: [
                .isRegularFileKey,
                .isDirectoryKey,
                .isSymbolicLinkKey,
                .fileSizeKey,
            ],
            options: [],
            errorHandler: { _, error in
                enumerationError = error
                return false
            }
        ) else {
            throw TrafficSignRuntimeUnavailability(
                code: .artifactUnreadable,
                detail: "The TSR model artifact directory cannot be enumerated."
            )
        }

        var files: [(relativePath: String, url: URL, byteSize: UInt64)] = []
        while let childURL = enumerator.nextObject() as? URL {
            let childValues = try childURL.resourceValues(forKeys: [
                .isRegularFileKey,
                .isDirectoryKey,
                .isSymbolicLinkKey,
                .fileSizeKey,
            ])
            guard childValues.isSymbolicLink != true else {
                throw TrafficSignRuntimeUnavailability(
                    code: .unsafeArtifactPath,
                    detail: "The TSR model artifact directory contains a symbolic link."
                )
            }
            if childValues.isDirectory == true { continue }
            guard childValues.isRegularFile == true else {
                throw TrafficSignRuntimeUnavailability(
                    code: .artifactUnreadable,
                    detail: "The TSR model artifact directory contains a special file."
                )
            }
            let relativePath = String(childURL.path.dropFirst(rootURL.path.count + 1))
            guard !relativePath.isEmpty else { continue }
            files.append((
                relativePath: relativePath,
                url: childURL,
                byteSize: UInt64(max(0, childValues.fileSize ?? 0))
            ))
        }
        if enumerationError != nil {
            throw TrafficSignRuntimeUnavailability(
                code: .artifactUnreadable,
                detail: "The TSR model artifact directory cannot be read completely."
            )
        }
        files.sort { $0.relativePath.utf8.lexicographicallyPrecedes($1.relativePath.utf8) }

        var hasher = SHA256()
        hasher.update(data: Data("tsr-directory-sha256-v1\u{0}".utf8))
        for file in files {
            let pathData = Data(file.relativePath.utf8)
            update(&hasher, withBigEndian: UInt64(pathData.count))
            hasher.update(data: pathData)
            update(&hasher, withBigEndian: file.byteSize)
            try update(&hasher, withContentsOf: file.url)
        }
        return hex(hasher.finalize())
    }

    private static func update(_ hasher: inout SHA256, withContentsOf url: URL) throws {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        while let chunk = try handle.read(upToCount: chunkSize), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
    }

    private static func update(_ hasher: inout SHA256, withBigEndian value: UInt64) {
        var encoded = value.bigEndian
        withUnsafeBytes(of: &encoded) { bytes in
            hasher.update(data: Data(bytes))
        }
    }

    private static func hex<D: Sequence>(_ digest: D) -> String where D.Element == UInt8 {
        digest.map { String(format: "%02x", $0) }.joined()
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

// MARK: - Atomic frame state

struct TrafficSignFrameSnapshot: Equatable, Sendable {
    let context: TrafficSignDetectionContext
    let conditions: TrafficSignAnalysisConditions
    let sessionGeneration: UInt64
    let contextGeneration: UInt64

    init(
        context: TrafficSignDetectionContext,
        conditions: TrafficSignAnalysisConditions,
        sessionGeneration: UInt64 = 0,
        contextGeneration: UInt64 = 0
    ) {
        self.context = context
        self.conditions = conditions
        self.sessionGeneration = sessionGeneration
        self.contextGeneration = contextGeneration
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
    let frameContext: TrafficSignDetectionContext
    let sessionGeneration: UInt64
    let contextGeneration: UInt64

    init(
        event: TrafficSignRecognitionEvent,
        frameContext: TrafficSignDetectionContext,
        sessionGeneration: UInt64 = 0,
        contextGeneration: UInt64 = 0
    ) {
        precondition(
            event.roadContext == frameContext,
            "A TSR event must retain the context captured with its source frame."
        )
        self.event = event
        self.frameContext = frameContext
        self.sessionGeneration = sessionGeneration
        self.contextGeneration = contextGeneration
    }
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
    typealias UnavailabilityHandler = @Sendable (TrafficSignRuntimeUnavailability) -> Void

    private enum Image: @unchecked Sendable {
        case pixelBuffer(CVPixelBuffer)
        case cgImage(CGImage)
    }

    private struct WorkItem: @unchecked Sendable {
        let image: Image
        let orientation: CGImagePropertyOrientation
        let source: TrafficSignRecognitionSource
        let timestampUTC: Date
        let snapshot: TrafficSignFrameSnapshot
    }

    private struct SchedulingState {
        var stopped = false
        var unavailable: TrafficSignRuntimeUnavailability?
        var inferenceInFlight = false
        var latestPendingLive: WorkItem?
        var latestPendingStill: WorkItem?
        var throttle = TrafficSignLatestFrameThrottle()
        var candidateBurstUntilUptime: TimeInterval?
        var acceptedLiveFrames: UInt64 = 0
        var cadenceDroppedLiveFrames: UInt64 = 0
        var replacedPendingLiveFrames: UInt64 = 0
        var completedInferences: UInt64 = 0
    }

    let verifiedPack: TrafficSignVerifiedModelPack

    private let backend: any TrafficSignInferenceBackend
    private let snapshotProvider: SnapshotProvider
    private let eventHandler: EventHandler
    private let unavailabilityHandler: UnavailabilityHandler?
    private let callbackQueue: DispatchQueue
    private let inferenceQueue: DispatchQueue
    private let lock = NSLock()
    private var schedulingState = SchedulingState()
    private var fusion: TrafficSignFusionEngine
    private var fusionSessionGeneration: UInt64?
    private var fusionContextGeneration: UInt64?

    init(
        verifiedPack: TrafficSignVerifiedModelPack,
        backend: any TrafficSignInferenceBackend,
        snapshotProvider: @escaping SnapshotProvider,
        callbackQueue: DispatchQueue = .main,
        eventHandler: @escaping EventHandler,
        unavailabilityHandler: UnavailabilityHandler? = nil
    ) {
        self.verifiedPack = verifiedPack
        self.backend = backend
        self.snapshotProvider = snapshotProvider
        self.callbackQueue = callbackQueue
        self.eventHandler = eventHandler
        self.unavailabilityHandler = unavailabilityHandler
        inferenceQueue = DispatchQueue(
            label: "de.youspeed.traffic-sign-recognition.inference",
            qos: .userInitiated
        )
        fusion = TrafficSignFusionEngine(
            packId: verifiedPack.manifest.packId,
            artifactSha256: verifiedPack.detectorArtifact.sha256,
            preprocessingVersion: verifiedPack.manifest.preprocessing.version,
            thresholds: verifiedPack.manifest.thresholds,
            runtimeOutput: verifiedPack.manifest.calibration.runtimeOutput
        )
    }

    func consumeVideoFrame(
        _ sampleBuffer: CMSampleBuffer,
        orientation: CGImagePropertyOrientation
    ) {
        let timestampUTC = Date()
        guard CMSampleBufferDataIsReady(sampleBuffer),
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer),
              let snapshot = snapshotProvider(),
              snapshot.context.isValid else {
            return
        }
        submitLive(
            WorkItem(
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
        guard snapshot.context.isValid else { return }
        submitWithoutCadence(
            WorkItem(
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
        guard snapshot.context.isValid else { return }
        submitWithoutCadence(
            WorkItem(
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

    private func perform(_ item: WorkItem) {
        inferenceQueue.async { [weak self] in
            guard let self else { return }
            let startedAt = ProcessInfo.processInfo.systemUptime
            do {
                let detections: [TrafficSignDetection]
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
                let latencyMs = max(
                    0,
                    (ProcessInfo.processInfo.systemUptime - startedAt) * 1_000
                )
                if self.fusionSessionGeneration != item.snapshot.sessionGeneration
                    || self.fusionContextGeneration != item.snapshot.contextGeneration {
                    self.fusion.reset()
                    self.fusionSessionGeneration = item.snapshot.sessionGeneration
                    self.fusionContextGeneration = item.snapshot.contextGeneration
                }
                let event = self.fusion.ingest(
                    detections: detections,
                    source: item.source,
                    timestamp: item.timestampUTC,
                    roadContext: item.snapshot.context,
                    latencyMs: latencyMs,
                    thermalState: item.snapshot.conditions.thermalState
                )
                self.complete(item: item, event: event)
            } catch {
                self.fail(
                    TrafficSignRuntimeUnavailability(
                        code: .inferenceFailed,
                        detail: "The verified TSR model failed during on-device inference."
                    )
                )
            }
        }
    }

    private func complete(item: WorkItem, event: TrafficSignRecognitionEvent) {
        let now = ProcessInfo.processInfo.systemUptime
        var next: WorkItem?
        var shouldDeliver = false
        lock.lock()
        schedulingState.completedInferences &+= 1
        if event.state == .provisional || event.state == .confirmed || event.state == .unknown {
            schedulingState.candidateBurstUntilUptime = now + 1.5
        }
        if schedulingState.stopped || schedulingState.unavailable != nil {
            schedulingState.inferenceInFlight = false
            schedulingState.latestPendingLive = nil
            schedulingState.latestPendingStill = nil
        } else if let pending = schedulingState.latestPendingStill {
            schedulingState.latestPendingStill = nil
            next = pending
        } else if let pending = schedulingState.latestPendingLive {
            schedulingState.latestPendingLive = nil
            next = pending
        } else {
            schedulingState.inferenceInFlight = false
        }
        shouldDeliver = !schedulingState.stopped && schedulingState.unavailable == nil
        lock.unlock()

        if shouldDeliver {
            let emission = TrafficSignRuntimeEmission(
                event: event,
                frameContext: item.snapshot.context,
                sessionGeneration: item.snapshot.sessionGeneration,
                contextGeneration: item.snapshot.contextGeneration
            )
            callbackQueue.async { [weak self, eventHandler] in
                guard self?.canDeliverCallback == true else { return }
                eventHandler(emission)
            }
        }
        if let next { perform(next) }
    }

    private func fail(_ reason: TrafficSignRuntimeUnavailability) {
        var shouldNotify = false
        lock.lock()
        if !schedulingState.stopped, schedulingState.unavailable == nil {
            schedulingState.unavailable = reason
            schedulingState.inferenceInFlight = false
            schedulingState.latestPendingLive = nil
            schedulingState.latestPendingStill = nil
            shouldNotify = true
        }
        lock.unlock()
        guard shouldNotify, let unavailabilityHandler else { return }
        callbackQueue.async { unavailabilityHandler(reason) }
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
        unavailabilityHandler: TrafficSignRuntime.UnavailabilityHandler? = nil
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
                backend = try TrafficSignVisionCoreMLBackend(verifiedPack: pack)
            }
            return .ready(TrafficSignRuntime(
                verifiedPack: pack,
                backend: backend,
                snapshotProvider: snapshotProvider,
                callbackQueue: callbackQueue,
                eventHandler: eventHandler,
                unavailabilityHandler: unavailabilityHandler
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

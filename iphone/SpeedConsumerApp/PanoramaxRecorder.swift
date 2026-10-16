@preconcurrency import AVFoundation
import CoreLocation
import Foundation
import ImageIO
import OSLog
import SwiftUI
import UIKit

/// The device boundary lets regression tests exercise capability fallbacks and
/// AVFoundation's required configuration order without a physical camera.
protocol DriveCameraFocusDevice: AnyObject {
    func isFocusModeSupported(_ focusMode: AVCaptureDevice.FocusMode) -> Bool
    func lockForConfiguration() throws
    func unlockForConfiguration()
    var focusMode: AVCaptureDevice.FocusMode { get set }
    var isFocusPointOfInterestSupported: Bool { get }
    var focusPointOfInterest: CGPoint { get set }
    var isAutoFocusRangeRestrictionSupported: Bool { get }
    var autoFocusRangeRestriction: AVCaptureDevice.AutoFocusRangeRestriction { get set }
    var automaticallyAdjustsFaceDrivenAutoFocusEnabled: Bool { get set }
    var isFaceDrivenAutoFocusEnabled: Bool { get set }
}

extension AVCaptureDevice: DriveCameraFocusDevice {}

enum DriveCameraFocusConfiguration {
    static func apply(to camera: any DriveCameraFocusDevice) throws {
        let mode: AVCaptureDevice.FocusMode
        if camera.isFocusModeSupported(.continuousAutoFocus) {
            mode = .continuousAutoFocus
        } else if camera.isFocusModeSupported(.autoFocus) {
            mode = .autoFocus
        } else {
            // Fixed-focus hardware has no autofocus controls to configure.
            return
        }

        try camera.lockForConfiguration()
        defer { camera.unlockForConfiguration() }
        if camera.isFocusPointOfInterestSupported {
            camera.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5)
        }
        if camera.isAutoFocusRangeRestrictionSupported {
            camera.autoFocusRangeRestriction = .far
        }
        // Prefer the road ahead over faces or their windscreen reflections.
        camera.automaticallyAdjustsFaceDrivenAutoFocusEnabled = false
        camera.isFaceDrivenAutoFocusEnabled = false
        // Apply the mode last: setting range/point/face preferences alone does
        // not initiate focusing. Never lock an uncalibrated lens position:
        // AVFoundation explicitly does not define lensPosition == 1 as infinity.
        camera.focusMode = mode
    }
}

enum DriveRecorderState: Equatable {
    case disabled
    case preparing
    case recording
    case stopping
    case denied
    case unavailable
    case failed
}

enum DriveCaptureSessionPurpose: Equatable {
    case driveRecording
    case automaticCapture
    case calibration
}

enum TrafficSignRecognitionState: Equatable {
    case disabled
    case unavailable
    case noRecognition
    case provisional(Int)
    case confirmed(Int)
    case unknown
}

struct DriveRecorderStartConfiguration: Equatable {
    let dashcamEnabled: Bool
    let trafficSignRecognitionEnabled: Bool
    let panoramaxEnabled: Bool
}

enum DriveRecorderPolicy {
    static func shouldRunAutomaticPhotos(enabled: Bool, driving: Bool, applicationActive: Bool, storageReady: Bool) -> Bool {
        enabled && driving && applicationActive && storageReady
    }

    static func shouldKeepCameraAfterMovieFinalization(
        panoramaxActive: Bool,
        trafficSignRecognitionActive: Bool,
        successful: Bool,
        actionPending: Bool
    ) -> Bool {
        panoramaxActive || trafficSignRecognitionActive || (successful && actionPending)
    }
    /// The main recorder control always starts a Dashcam movie. The other
    /// consumers retain their independent selections and share the same fixed
    /// capture graph, so enabling video must never switch TSR or Panoramax off.
    static func mainControlStartConfiguration(
        trafficSignRecognitionEnabled: Bool,
        panoramaxEnabled: Bool
    ) -> DriveRecorderStartConfiguration {
        DriveRecorderStartConfiguration(
            dashcamEnabled: true,
            trafficSignRecognitionEnabled: trafficSignRecognitionEnabled,
            panoramaxEnabled: panoramaxEnabled
        )
    }

    static func shouldRunStandaloneTrafficSignRecognition(
        recognitionEnabled: Bool,
        independentRecognitionEnabled: Bool,
        runtimeReady: Bool,
        isDriving: Bool,
        applicationIsActive: Bool
    ) -> Bool {
        recognitionEnabled
            && independentRecognitionEnabled
            && runtimeReady
            && isDriving
            && applicationIsActive
    }

    static func presentedRecorderState(
        captureState: DriveRecorderState,
        purpose: DriveCaptureSessionPurpose?,
        driveStartPending: Bool
    ) -> DriveRecorderState {
        if driveStartPending {
            return .preparing
        }
        if purpose == .automaticCapture || purpose == .calibration {
            return .disabled
        }
        return captureState
    }

    static func shouldEnablePanoramaxFallback(
        dashcamEnabled: Bool,
        trafficSignRecognitionReady: Bool,
        panoramaxEnabled: Bool
    ) -> Bool {
        !dashcamEnabled && !trafficSignRecognitionReady && !panoramaxEnabled
    }

    static func canToggleModules(for state: DriveRecorderState) -> Bool {
        state == .recording
    }

    static func canShowDashcamPreview(
        for state: DriveRecorderState,
        dashcamActive: Bool,
        speedCaptureActive: Bool
    ) -> Bool {
        state == .recording && dashcamActive && !speedCaptureActive
    }

    static func shouldStopAfterTrafficSignRuntimeLoss(
        for state: DriveRecorderState,
        dashcamActive: Bool,
        panoramaxActive: Bool
    ) -> Bool {
        (state == .preparing || state == .recording)
            && !dashcamActive
            && !panoramaxActive
    }

    static func canProcessPanoramaxUploads(
        for state: DriveRecorderState,
        purpose: DriveCaptureSessionPurpose? = nil
    ) -> Bool {
        // Automatic photos/TSR do not own the movie controls. Completed batches
        // remain reviewable; the queue separately protects the capturing batch.
        if purpose == .automaticCapture {
            return true
        }
        switch state {
        case .preparing, .recording, .stopping:
            return false
        case .disabled, .denied, .unavailable, .failed:
            return true
        }
    }

    static func canEditPanoramaxSelection(in state: PanoramaxBatchState) -> Bool {
        switch state {
        case .awaitingReview, .approved, .partial, .blocked:
            return true
        case .capturing, .creatingUploadSet, .uploading, .processing, .complete:
            return false
        }
    }

    static func canStartPanoramaxUpload(for state: PanoramaxBatchState) -> Bool {
        state == .approved || state == .partial || state == .processing
    }

    static func canResumePanoramaxRemoteSet(
        batchState: PanoramaxBatchState,
        remoteUploadSetID: String?,
        itemStates: [PanoramaxItemState]
    ) -> Bool {
        guard let remoteUploadSetID,
              !remoteUploadSetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return false
        }
        if batchState == .processing {
            return true
        }
        guard batchState == .partial else { return false }
        // A legacy/manual cleanup may have removed every local item after the
        // remote set was created. The remote set still needs an explicit
        // completion/poll round trip even though there is no thumbnail to tap.
        if itemStates.isEmpty {
            return true
        }
        return itemStates.contains { state in
            state == .uploaded || state == .accepted || state == .duplicate
        }
    }

    /// Explicit gallery deletion is authoritative for local data regardless of
    /// upload state. It never implies a remote Panoramax delete or sync.
    static func canDeletePanoramaxItem(
        batchState: PanoramaxBatchState,
        itemState: PanoramaxItemState
    ) -> Bool {
        true
    }

    /// Automatic quota enforcement must never race a live capture or upload
    /// lifecycle. Unlike an explicit user deletion, automatic quota eviction
    /// still preserves accepted items in an unfinished remote upload set.
    static func canEvictPanoramaxItem(
        batchState: PanoramaxBatchState,
        itemState: PanoramaxItemState
    ) -> Bool {
        switch batchState {
        case .capturing, .creatingUploadSet, .uploading, .processing:
            return false
        case .awaitingReview, .approved, .complete, .blocked:
            return true
        case .partial:
            return itemState != .uploaded && itemState != .accepted && itemState != .duplicate
        }
    }

    static func canSelectPanoramaxItem(in state: PanoramaxItemState) -> Bool {
        switch state {
        case .captured, .included, .excluded, .queued, .retryableError:
            return true
        case .uploading, .uploaded, .accepted, .duplicate, .rejected, .permanentError, .abandoned:
            return false
        }
    }
}

struct DashcamRecording: Identifiable, Equatable {
    let id: String
    let url: URL
    let createdAt: Date
    let byteSize: Int64
}

private struct PanoramaxPhotoProcessingResult {
    let sample: PanoramaxLocationSample
    let saved: Bool
    let detail: String
    var annotationLogLine: String? = nil
}

/// An image analyzer attaches here without owning or reconfiguring the
/// platform camera session. Work must finish quickly because the dispatcher
/// drops stale frames instead of building an inference backlog.
protocol DriveVideoFrameConsumer: AnyObject {
    func consumeVideoFrame(_ sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation)
}

final class DriveVideoFrameDispatcher: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private let lock = NSLock()
    private weak var consumer: (any DriveVideoFrameConsumer)?
    private var enabled = false
    private var orientation: CGImagePropertyOrientation = .right
    private weak var laneConsumer: (any DriveVideoFrameConsumer)?
    private var lanesEnabled = false
        private var legacyLanesAllowed = false
    private weak var calibrationConsumer: (any DriveVideoFrameConsumer)?
    private var calibrationEnabled = false
    private var captureSessionID: String?
    private var sourceGeometry: LanePreviewSourceGeometry?

    func setCaptureSessionID(_ value: String?) {
        lock.lock(); captureSessionID = value; sourceGeometry = nil; lock.unlock()
    }

    func currentSourceGeometry() -> LanePreviewSourceGeometry? {
        lock.lock(); defer { lock.unlock() }; return sourceGeometry
    }

    func setCalibrationConsumer(_ consumer: (any DriveVideoFrameConsumer)?, enabled: Bool) {
        lock.lock(); calibrationConsumer = consumer; calibrationEnabled = enabled; lock.unlock()
    }

    func setLaneConsumer(_ consumer: (any DriveVideoFrameConsumer)?) {
        lock.lock()
        laneConsumer = consumer
        lock.unlock()
    }

    func setLanesEnabled(_ enabled: Bool) {
        lock.lock()
        lanesEnabled = enabled
        lock.unlock()
    }

    var hasConsumer: Bool {
        lock.lock()
        defer { lock.unlock() }
        return consumer != nil
    }

    func setConsumer(_ consumer: (any DriveVideoFrameConsumer)?) {
        lock.lock()
        self.consumer = consumer
        lock.unlock()
    }

    func setEnabled(_ enabled: Bool) {
        lock.lock()
        self.enabled = enabled
        lock.unlock()
    }

    func setOrientation(_ orientation: CGImagePropertyOrientation) {
        lock.lock()
        if self.orientation != orientation { sourceGeometry = nil }
        self.orientation = orientation
        lock.unlock()
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        dispatch(sampleBuffer)
    }

    func dispatch(_ sampleBuffer: CMSampleBuffer) {
        lock.lock()
        defer { lock.unlock() }
        // Admission is bounded: the consumer captures its context and schedules
        // inference asynchronously. Keep it atomic with setOrientation so an
        // old orientation cannot acquire a new context after a mount change.
        let now = ProcessInfo.processInfo.systemUptime
        if sourceGeometry == nil || now - (sourceGeometry?.observedAtUptimeSeconds ?? -.infinity) >= 0.2,
           let captureSessionID, CMSampleBufferDataIsReady(sampleBuffer),
           let pixel = CMSampleBufferGetImageBuffer(sampleBuffer) {
            let rotation: Int? = switch orientation {
            case .up: 0
            case .right: 90
            case .down: 180
            case .left: 270
            default: nil
            }
            if let rotation {
                sourceGeometry = LanePreviewSourceGeometry(captureSessionID: captureSessionID,
                    rawWidth: CVPixelBufferGetWidth(pixel), rawHeight: CVPixelBufferGetHeight(pixel),
                    rotationDegrees: rotation, orientationKey: "rear:exif:\(orientation.rawValue)",
                    observedAtUptimeSeconds: now)
            } else { sourceGeometry = nil }
        }
        let activeConsumer = enabled ? consumer : nil
        let activeLaneConsumer = lanesEnabled ? laneConsumer : nil
        if calibrationEnabled { calibrationConsumer?.consumeVideoFrame(sampleBuffer, orientation: orientation) }
        activeLaneConsumer?.consumeVideoFrame(sampleBuffer, orientation: orientation)
        activeConsumer?.consumeVideoFrame(sampleBuffer, orientation: orientation)
    }
}

/// The single rear-camera owner for a recorded drive.
///
/// One configured session fans out to independent consumers: encoded Dashcam
/// video, latest-frame TSR and lane analysis, cadence-driven full-resolution
/// Panoramax stills, and a display-only preview layer. Panoramax review and
/// upload deliberately live outside this type and can only run after this
/// session is inactive.
@MainActor
final class DriveCaptureCoordinator: NSObject, ObservableObject {
    private nonisolated static let logger = Logger(
        subsystem: "de.youspeed.SpeedConsumer",
        category: "drive-recorder"
    )
    private static let maximumDashcamFileBytes: Int64 = 5_000_000_000
    private static let dashcamRetentionBytes: Int64 = 10_000_000_000
    // AVFoundation objects are configured before use and then touched only on
    // sessionQueue for start/stop/capture operations.
    nonisolated(unsafe) let session = AVCaptureSession()

    @Published private(set) var state: DriveRecorderState = .disabled
    @Published private(set) var sessionPurpose: DriveCaptureSessionPurpose? = nil
    @Published private(set) var startedAt: Date?
    @Published private(set) var dashcamFileURL: URL?
    @Published private(set) var dashcamTransitionInFlight = false
    @Published private(set) var capturedImageCount = 0
    private(set) var manualPhotoCaptureFailed = false
    @Published private(set) var lastCaptureAt: Date?
    @Published private(set) var lastCaptureDetail = "Noch keine Aufnahme"
    @Published private(set) var lastAccuracyMeters: Double?

    var onChange: (() -> Void)?
    var onDiagnostic: ((String) -> Void)?
    private var lastDiagnosticSnapshot: String?
    var onTrafficSignAnnotation: ((String) -> Void)?
    var onPanoramaxQueueChange: (() -> Void)?

    private var queueStore: PanoramaxQueueStore?
    private let sessionQueue = DispatchQueue(label: "de.youspeed.drive-recorder.camera")
    private let videoQueue = DispatchQueue(label: "de.youspeed.drive-recorder.tsr", qos: .userInitiated)
    private let photoProcessingQueue = DispatchQueue(label: "de.youspeed.drive-recorder.panoramax", qos: .utility)
    nonisolated(unsafe) private let frameDispatcher = DriveVideoFrameDispatcher()
    nonisolated(unsafe) private let photoOutput = AVCapturePhotoOutput()
    nonisolated(unsafe) private let movieOutput = AVCaptureMovieFileOutput()
    nonisolated(unsafe) private let videoOutput = AVCaptureVideoDataOutput()

    private var cadenceConfiguration = PanoramaxCadenceConfiguration()
    private var storageLimitBytes: Int64?
    private var batch: PanoramaxBatchRecord?
    private var lastCaptureSample: PanoramaxLocationSample?
    private var pendingSignEvidence: [SignCaptureFilter.Evidence] = []
    private var pendingCaptureReason = "cadence"
    private var lastManualPhotoRequestAt: Date?
    private var pendingSample: PanoramaxLocationSample?
    private var pendingPhotoUniqueID: Int64?
    private var photoInFlight = false
    private var movieOutputAvailable = false
    private var photoOutputAvailable = false
    private var videoOutputAvailable = false
    private var generation = 0
    private var activeDashcamEnabled = false
    private var activePanoramaxEnabled = false
    private var activeManualPhotosEnabled = false
    private var requestedManualPhotosEnabled = false
    private var manualBatchPreparationInFlight = false
    private var manualBatchPreparationFailed = false
    private var manualPhotoMoving = true
    private var activeTSREnabled = false
    private var calibrationPreviewEnabled = false
    private var activeLanesEnabled = false
    private var startTimeoutTask: Task<Void, Never>?
    private var stopTimeoutTask: Task<Void, Never>?
    private var dashcamTransitionTimeoutTask: Task<Void, Never>?
    private var stopResultState: DriveRecorderState = .disabled
    private var stopResultDetail: String?
    private var notificationTokens: [NSObjectProtocol] = []
    private var captureSessionID: String?
    private var activeDashcamRecordingURL: URL?
    private var dashcamTransition: DashcamTransition?
    private var latestTrafficSignAnnotationDraft: PanoramaxTrafficSignAnnotationDraft?
    private var screenOrientation = ScreenOrientation.load()
    private var orientationChangedAt = Date.distantPast
    private var orientationEpoch: UInt64 = 0
    private var pendingPhotoOrientationEpoch: UInt64?
    private var interactionFinalization: ((Result<Void, Error>) -> Void)?
    private var interactionFinalizationTimeout: Task<Void, Never>?

#if DEBUG
    private var testDashcamOutputDirectory: URL?
    private var testPhotoCapture: ((Int64, CGFloat) -> Void)?

    /// Camera-independent seam for simulator/unit coverage. The request and
    /// completion still go through the production admission/JPEG/queue path.
    func testPrepareManualPhotoSession(automaticPhotos: Bool = false,
                                      dashcamActive: Bool = false,
                                      outputAvailable: Bool = true,
                                      capture: @escaping (Int64, CGFloat) -> Void) throws {
        guard let queueStore else { throw RecorderError.sessionUnavailable }
        testPhotoCapture = capture
        generation += 1
        pendingPhotoUniqueID = nil
        pendingSample = nil
        photoInFlight = false
        lastManualPhotoRequestAt = nil
        capturedImageCount = 0
        lastCaptureAt = nil
        manualPhotoMoving = true
        let sessionID = UUID().uuidString
        captureSessionID = sessionID
        sessionPurpose = .automaticCapture
        requestedManualPhotosEnabled = true
        activeManualPhotosEnabled = true
        activePanoramaxEnabled = automaticPhotos
        activeDashcamEnabled = dashcamActive
        requestedPanoramaxEnabled = automaticPhotos
        photoOutputAvailable = outputAvailable
        batch = try queueStore.createBatch(captureSessionID: sessionID)
        state = .recording
        notifyChange()
    }

    func testCompletePhoto(data: Data?, uniqueID: Int64) {
        finishPhoto(data: data, error: nil, uniqueID: uniqueID)
    }

    // Keep the exemption on the exact created URL, including late callbacks after
    // the test clears its destination. Normal recordings never enter this set.
    private var isolatedTestDashcamURLs = Set<URL>()

    func setTestDashcamOutputDirectory(_ directory: URL?) throws {
        guard let directory else { testDashcamOutputDirectory = nil; return }
        guard !needsDashcamFinalization, state != .preparing, state != .recording, state != .stopping,
              let runID = ProcessInfo.processInfo.environment["LANE_FULL_WORKLOAD_RUN_ID"],
              runID.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil else {
            throw NSError(domain: "LaneFullWorkloadMovieDestinationBusyOrUnauthorized", code: 1)
        }
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LaneFullWorkload", isDirectory: true).resolvingSymlinksInPath().standardizedFileURL
        let target = directory.resolvingSymlinksInPath().standardizedFileURL
        guard target.deletingLastPathComponent() == root, target.lastPathComponent == runID,
              (try? target.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true else {
            throw NSError(domain: "LaneFullWorkloadMovieDestinationInvalid", code: 1)
        }
        testDashcamOutputDirectory = target
    }
#endif

    var needsDashcamFinalization: Bool {
        activeDashcamEnabled || dashcamTransitionInFlight || activeDashcamRecordingURL != nil
    }

    func setScreenOrientation(_ orientation: ScreenOrientation) {
        guard !needsDashcamFinalization else { return }
        screenOrientation = orientation
        orientationEpoch &+= 1
        orientationChangedAt = Date()
        latestTrafficSignAnnotationDraft = nil
        // No graph mutation: every camera consumer remains attached.
        frameDispatcher.setOrientation(orientation.frameOrientation)
    }

    func finalizeDashcamForInteraction(completion: @escaping (Result<Void, Error>) -> Void) {
        guard interactionFinalization == nil else {
            completion(.failure(DriveInteractionError.finalizationFailed))
            return
        }
        guard needsDashcamFinalization else { completion(.success(())); return }
        interactionFinalization = completion
        interactionFinalizationTimeout = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(18))
            guard !Task.isCancelled, let self else { return }
            completeInteractionFinalization(.failure(DriveInteractionError.finalizationFailed))
        }
        stopDashcamForPendingInteraction()
    }

    private func stopDashcamForPendingInteraction() {
        guard interactionFinalization != nil else { return }
        // Startup's movie delegate resumes this request once its URL is live.
        guard state != .preparing, !dashcamTransitionInFlight else { return }
        guard state == .recording,
              setDashcamEnabledDuringRecording(false) else {
            if state != .stopping {
                completeInteractionFinalization(.failure(DriveInteractionError.finalizationFailed))
            }
            return
        }
    }

    private func completeInteractionFinalization(_ result: Result<Void, Error>) {
        let completion = interactionFinalization
        interactionFinalization = nil
        interactionFinalizationTimeout?.cancel()
        interactionFinalizationTimeout = nil
        completion?(result)
    }

    var isDashcamModuleActive: Bool { activeDashcamEnabled }
    var isPanoramaxModuleActive: Bool { activePanoramaxEnabled }
    var isManualPhotoInFlight: Bool { photoInFlight }
    var isTrafficSignRecognitionModuleActive: Bool { activeTSREnabled }
    var isAutomaticCaptureSession: Bool {
        sessionPurpose == .automaticCapture
    }
    private(set) var requestedPanoramaxEnabled = false
    var activeCaptureSessionID: String? { captureSessionID }
    var lanePreviewSourceGeometry: LanePreviewSourceGeometry? { frameDispatcher.currentSourceGeometry() }
    var hasTrafficSignRecognitionConsumer: Bool { frameDispatcher.hasConsumer }
    var isDashcamOutputAvailable: Bool { movieOutputAvailable }
    var isLaneAnalysisOutputAvailable: Bool { videoOutputAvailable }
    var isTrafficSignRecognitionOutputAvailable: Bool {
        videoOutputAvailable && frameDispatcher.hasConsumer
    }

    init(queueStore: PanoramaxQueueStore?) {
        self.queueStore = queueStore
        super.init()
        observeSessionFailures()
    }

    deinit {
        startTimeoutTask?.cancel()
        stopTimeoutTask?.cancel()
        dashcamTransitionTimeoutTask?.cancel()
        interactionFinalizationTimeout?.cancel()
        notificationTokens.forEach(NotificationCenter.default.removeObserver)
    }

    func setQueueStore(_ store: PanoramaxQueueStore) {
        queueStore = store
        manualBatchPreparationFailed = false
        prepareManualPhotoBatchIfNeeded()
    }

    /// A manually created batch becomes reviewable at standstill. Keep an
    /// accepted exposure alive through deceleration and seal after persistence.
    func setManualPhotoMoving(_ moving: Bool) {
        if moving != manualPhotoMoving { manualBatchPreparationFailed = false }
        manualPhotoMoving = moving
        guard state == .recording else { return }
        if !moving, !photoInFlight {
            activeManualPhotosEnabled = false
            if !activePanoramaxEnabled, batch != nil {
                closePanoramaxBatchForReview()
                notifyChange()
            }
        } else if moving {
            activeManualPhotosEnabled = requestedManualPhotosEnabled && photoOutputAvailable && batch != nil
            prepareManualPhotoBatchIfNeeded()
        }
    }

    private func prepareManualPhotoBatchIfNeeded() {
        guard state == .recording, manualPhotoMoving, queueStore != nil,
              requestedManualPhotosEnabled, photoOutputAvailable,
              batch == nil, !manualBatchPreparationInFlight, !manualBatchPreparationFailed,
              let captureSessionID else { return }
        manualBatchPreparationInFlight = true
        let requestedGeneration = generation
        Task { @MainActor [weak self] in
            guard let self else { return }
            await preparePanoramaxBatch(captureSessionID: captureSessionID, requestedGeneration: requestedGeneration)
            manualBatchPreparationInFlight = false
            if generation == requestedGeneration, state == .recording {
                activeManualPhotosEnabled = batch != nil && manualPhotoMoving
                manualBatchPreparationFailed = batch == nil
                if !manualPhotoMoving, !activePanoramaxEnabled { closePanoramaxBatchForReview() }
                notifyChange()
            }
        }
    }

    func setVideoFrameConsumer(_ consumer: (any DriveVideoFrameConsumer)?) {
        frameDispatcher.setConsumer(consumer)
        guard consumer == nil, activeTSREnabled else {
            notifyChange()
            return
        }
        frameDispatcher.setEnabled(false)
        activeTSREnabled = false
        updateVideoAnalysisConnection()
        lastCaptureDetail = "Verkehrszeichenmodell nicht mehr verfuegbar"
        if DriveRecorderPolicy.shouldStopAfterTrafficSignRuntimeLoss(
            for: state,
            dashcamActive: activeDashcamEnabled || dashcamTransitionInFlight,
            panoramaxActive: activePanoramaxEnabled || activeManualPhotosEnabled || calibrationPreviewEnabled
        ) {
            beginStopping(resultState: .unavailable, detail: lastCaptureDetail)
            return
        }
        notifyChange()
    }

    func setCalibrationPreviewConsumer(_ consumer: (any DriveVideoFrameConsumer)?) {
        calibrationPreviewEnabled = consumer != nil
        frameDispatcher.setCalibrationConsumer(consumer, enabled: calibrationPreviewEnabled)
        updateVideoAnalysisConnection()
    }

    func setLaneFrameConsumer(_ consumer: (any DriveVideoFrameConsumer)?) {
        frameDispatcher.setLaneConsumer(consumer)
    }

    func setLaneAnalysisEnabled(_ enabled: Bool) {
        let enabled = enabled && state == .recording && activeDashcamEnabled && videoOutputAvailable
        guard activeLanesEnabled != enabled else { return }
        activeLanesEnabled = enabled
        frameDispatcher.setLanesEnabled(enabled)
        updateVideoAnalysisConnection()
    }

    private func updateVideoAnalysisConnection() {
        let enabled = activeTSREnabled || activeLanesEnabled || calibrationPreviewEnabled
        sessionQueue.async { [weak self] in
            self?.videoOutput.connection(with: .video)?.isEnabled = enabled
        }
    }

    /// Retains the newest confirmed result for the next still and, when there
    /// is no still in flight, also tries the most recent picture from this drive.
    func recordTrafficSignRecognition(_ emission: TrafficSignRuntimeEmission) {
        guard var draft = PanoramaxTrafficSignAnnotationDraft(emission: emission),
              draft.frameTimestampUTC >= orientationChangedAt,
              let captureSessionID,
              emission.captureSessionId == captureSessionID else { return }
        draft.minimumImageTimestamp = orientationChangedAt
        latestTrafficSignAnnotationDraft = draft
        guard !photoInFlight, let batch, let queueStore else { return }
        let batchID = batch.batchID
        photoProcessingQueue.async { [weak self] in
            let itemID = try? queueStore.attachTrafficSignAnnotation(
                batchID: batchID,
                draft: draft
            )
            Task { @MainActor [weak self] in
                guard let self, let itemID else { return }
                if self.latestTrafficSignAnnotationDraft?.sourceEventID == draft.sourceEventID {
                    self.latestTrafficSignAnnotationDraft = nil
                }
                self.onTrafficSignAnnotation?("event_id=\(draft.sourceEventID) image_id=\(itemID) speed_kmh=\(draft.speedLimitKmh)")
                self.notifyChange()
            }
        }
    }

    func updatePanoramaxConfiguration(
        _ configuration: PanoramaxCadenceConfiguration,
        storageLimitBytes: Int64?
    ) {
        cadenceConfiguration = configuration
        self.storageLimitBytes = storageLimitBytes
    }

    func start(
        dashcamEnabled: Bool,
        trafficSignRecognitionEnabled: Bool,
        panoramaxEnabled: Bool,
        purpose: DriveCaptureSessionPurpose = .driveRecording,
        manualPhotosEnabled: Bool = false,
        allowCameraPermissionRequest: Bool = true
    ) {
        guard state != .preparing, state != .recording, state != .stopping else {
            return
        }

        let tsrEnabled = trafficSignRecognitionEnabled && frameDispatcher.hasConsumer
        let manualPhotos = manualPhotosEnabled && purpose != .calibration
        guard dashcamEnabled || panoramaxEnabled || trafficSignRecognitionEnabled || calibrationPreviewEnabled || manualPhotos else {
            state = .unavailable
            lastCaptureDetail = trafficSignRecognitionEnabled
                ? "Noch kein Verkehrszeichenmodell installiert"
                : "Kein Kameramodul aktiviert"
            notifyChange()
            return
        }

        generation += 1
        let requestedGeneration = generation
        let captureSessionID = UUID().uuidString
        self.captureSessionID = captureSessionID
        frameDispatcher.setCaptureSessionID(captureSessionID)
        sessionPurpose = purpose
        state = .preparing
        startedAt = nil
        dashcamFileURL = nil
        dashcamTransitionInFlight = false
        dashcamTransition = nil
        dashcamTransitionTimeoutTask?.cancel()
        dashcamTransitionTimeoutTask = nil
        activeDashcamRecordingURL = nil
        latestTrafficSignAnnotationDraft = nil
        capturedImageCount = 0
        lastCaptureAt = nil
        lastAccuracyMeters = nil
        lastCaptureDetail = "Kamera wird vorbereitet"
        activeDashcamEnabled = dashcamEnabled
        requestedPanoramaxEnabled = panoramaxEnabled
        activePanoramaxEnabled = panoramaxEnabled
        requestedManualPhotosEnabled = manualPhotos
        manualBatchPreparationFailed = false
        manualPhotoCaptureFailed = false
        manualPhotoMoving = true
        activeManualPhotosEnabled = manualPhotos
        lastManualPhotoRequestAt = nil
        activeTSREnabled = tsrEnabled
        notifyChange()

        Task { @MainActor [weak self] in
            guard let self else { return }
            let authorization = AVCaptureDevice.authorizationStatus(for: .video)
            var authorized = authorization == .authorized
            if authorization == .notDetermined && allowCameraPermissionRequest {
                authorized = await AVCaptureDevice.requestAccess(for: .video)
            }
            guard authorized else {
                guard generation == requestedGeneration else { return }
                resetActiveModulesAfterFailure()
                state = .denied
                lastCaptureDetail = "Kamerazugriff verweigert"
                notifyChange()
                return
            }
            guard generation == requestedGeneration, state == .preparing else { return }

            do {
                try configureSession(
                    dashcamEnabled: activeDashcamEnabled,
                    // Preserve the user's selection while an asynchronously
                    // verified model pack is still loading. The selected video
                    // output must get graph priority even though it cannot
                    // consume frames until the runtime attaches.
                    trafficSignRecognitionEnabled: trafficSignRecognitionEnabled || calibrationPreviewEnabled,
                    panoramaxEnabled: activePanoramaxEnabled
                )
                activeDashcamEnabled = activeDashcamEnabled && movieOutputAvailable
                activeTSREnabled = trafficSignRecognitionEnabled
                    && frameDispatcher.hasConsumer
                    && videoOutputAvailable
                activePanoramaxEnabled = activePanoramaxEnabled && photoOutputAvailable
                activeManualPhotosEnabled = activeManualPhotosEnabled && photoOutputAvailable
                if activePanoramaxEnabled || activeManualPhotosEnabled {
                    await preparePanoramaxBatch(captureSessionID: captureSessionID, requestedGeneration: requestedGeneration)
                    guard generation == requestedGeneration, state == .preparing else { return }
                }
                if activeDashcamEnabled {
                    dashcamFileURL = try makeDashcamFileURL(captureSessionID: captureSessionID)
                }
                guard activeDashcamEnabled || activeTSREnabled || activePanoramaxEnabled || activeManualPhotosEnabled || (calibrationPreviewEnabled && videoOutputAvailable) else {
                    throw RecorderError.noEnabledModuleAvailable
                }
            } catch let error as RecorderError {
                closePanoramaxBatchForReview()
                resetActiveModulesAfterFailure()
                state = error.isAvailabilityFailure ? .unavailable : .failed
                switch error {
                case .noEnabledModuleAvailable:
                    lastCaptureDetail = "Kein aktiviertes Kameramodul ist verfuegbar"
                case .panoramaxUnavailable:
                    lastCaptureDetail = "Panoramax-Fotokamera ist fuer diese Kamerakonfiguration nicht verfuegbar"
                default:
                    lastCaptureDetail = "Kamera konnte nicht gestartet werden"
                }
                notifyChange()
                return
            } catch {
                closePanoramaxBatchForReview()
                resetActiveModulesAfterFailure()
                state = .failed
                lastCaptureDetail = "Kamera konnte nicht gestartet werden"
                notifyChange()
                return
            }

            guard generation == requestedGeneration, state == .preparing else {
                closePanoramaxBatchForReview()
                return
            }

            let movieURL = dashcamFileURL
            let movieAngle = screenOrientation.captureRotationAngle
            let trafficSignFramesEnabled = activeTSREnabled || calibrationPreviewEnabled
            frameDispatcher.setOrientation(screenOrientation.frameOrientation)
            frameDispatcher.setEnabled(activeTSREnabled)
            scheduleStartTimeout(generation: requestedGeneration)
            sessionQueue.async { [weak self] in
                guard let self else { return }
                self.videoOutput.connection(with: .video)?.isEnabled = trafficSignFramesEnabled
                self.session.startRunning()
                if let movieURL {
                    self.configureMovieCodecIfPossible(rotationAngle: movieAngle)
                    self.movieOutput.startRecording(to: movieURL, recordingDelegate: self)
                } else {
                    Task { @MainActor [weak self] in
                        self?.finishStarting(generation: requestedGeneration)
                    }
                }
            }
        }
    }

    func stop() {
        beginStopping(resultState: .disabled, detail: nil)
    }

    /// Starts or stops only the Dashcam encoder while the shared camera and
    /// the other consumers keep running. The movie output is attached before
    /// the session starts, so this never reconfigures a live capture graph.
    @discardableResult
    func setDashcamEnabledDuringRecording(_ enabled: Bool) -> Bool {
        guard state == .recording, !dashcamTransitionInFlight else { return false }

        if enabled {
            guard !activeDashcamEnabled else { return false }
            guard movieOutputAvailable, let captureSessionID else {
                lastCaptureDetail = "Dashcam ist fuer diese Kamerakonfiguration nicht verfuegbar"
                notifyChange()
                return false
            }
            do {
                let fileURL = try makeDashcamFileURL(captureSessionID: captureSessionID)
                let token = UUID()
                dashcamFileURL = fileURL
                let movieAngle = screenOrientation.captureRotationAngle
                beginDashcamTransition(.starting(url: fileURL, token: token))
                lastCaptureDetail = "Dashcam wird gestartet"
                notifyChange()
                sessionQueue.async { [weak self] in
                    guard let self else { return }
                    guard self.session.isRunning, !self.movieOutput.isRecording else {
                        Task { @MainActor [weak self] in
                            self?.finishDashcamToggleFailure(
                                "Dashcam konnte nicht gestartet werden",
                                token: token
                            )
                        }
                        return
                    }
                    self.configureMovieCodecIfPossible(rotationAngle: movieAngle)
                    self.movieOutput.startRecording(to: fileURL, recordingDelegate: self)
                }
            } catch {
                finishDashcamToggleFailure("Dashcam-Datei konnte nicht erstellt werden", token: nil)
                return false
            }
            return true
        }

        guard activeDashcamEnabled, let activeDashcamRecordingURL else { return false }
        let token = UUID()
        beginDashcamTransition(.stopping(url: activeDashcamRecordingURL, token: token))
        lastCaptureDetail = "Dashcam wird gespeichert"
        notifyChange()
        sessionQueue.async { [weak self] in
            guard let self else { return }
            if self.movieOutput.isRecording {
                self.movieOutput.stopRecording()
            } else {
                Task { @MainActor [weak self] in
                    self?.finishDashcamDisableWithoutCallback(token: token)
                }
            }
        }
        return true
    }

    /// TSR can be switched without changing the session graph. If no validated
    /// model consumer is attached, the request stays visibly unavailable and
    /// no fake recognition state is published.
    @discardableResult
    func setTrafficSignRecognitionEnabledDuringRecording(_ enabled: Bool) -> Bool {
        guard state == .recording else { return false }
        guard enabled else {
            frameDispatcher.setEnabled(false)
            activeTSREnabled = false
            updateVideoAnalysisConnection()
            lastCaptureDetail = "Verkehrszeichenerkennung pausiert"
            notifyChange()
            return true
        }
        guard videoOutputAvailable, frameDispatcher.hasConsumer else {
            frameDispatcher.setEnabled(false)
            activeTSREnabled = false
            lastCaptureDetail = "Noch kein Verkehrszeichenmodell installiert"
            notifyChange()
            return false
        }
        frameDispatcher.setEnabled(true)
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.videoOutput.connection(with: .video)?.isEnabled = true
        }
        activeTSREnabled = true
        lastCaptureDetail = "Verkehrszeichenerkennung aktiv"
        notifyChange()
        return true
    }

    private func beginStopping(resultState: DriveRecorderState, detail: String?) {
        guard state == .recording || state == .preparing else {
            return
        }
        generation += 1
        let stopGeneration = generation
        stopResultState = resultState
        stopResultDetail = detail
        startTimeoutTask?.cancel()
        startTimeoutTask = nil
        dashcamTransitionTimeoutTask?.cancel()
        dashcamTransitionTimeoutTask = nil
        dashcamTransition = nil
        dashcamTransitionInFlight = false
        state = .stopping
        frameDispatcher.setCaptureSessionID(nil)
        frameDispatcher.setEnabled(false)
        activeLanesEnabled = false
        frameDispatcher.setLanesEnabled(false)
        closePanoramaxBatchForReview()
        pendingSample = nil
        pendingPhotoUniqueID = nil
        photoInFlight = false
        latestTrafficSignAnnotationDraft = nil
        notifyChange()
        scheduleStopTimeout(generation: stopGeneration)

        sessionQueue.async { [weak self] in
            guard let self else { return }
            let awaitsMovieFinalization = self.movieOutput.isRecording
            if awaitsMovieFinalization {
                self.movieOutput.stopRecording()
            }
            if self.session.isRunning {
                self.session.stopRunning()
            }
            guard !awaitsMovieFinalization else { return }
            Task { @MainActor [weak self] in
                self?.finishStopping(generation: stopGeneration)
            }
        }
    }

    @discardableResult
    func ingestRecognizedSigns(_ evidence: [SignCaptureFilter.Evidence], location: CLLocation, speedMetersPerSecond: Double?) -> Bool {
        guard cadenceConfiguration.recognizedSignsOnly, !evidence.isEmpty, evidence.allSatisfy({ abs(Date().timeIntervalSince($0.frameAt)) <= 2 }) else { return false }
        return capture(location: location, speedMetersPerSecond: speedMetersPerSecond, signEvidence: evidence)
    }
    func ingest(location: CLLocation, speedMetersPerSecond: Double? = nil) {
        guard !cadenceConfiguration.recognizedSignsOnly else { return }
        _ = capture(location: location, speedMetersPerSecond: speedMetersPerSecond, signEvidence: [])
    }

    func canCaptureManualPhoto(location: CLLocation, now: Date = Date()) -> Bool {
        DrivingPhotoPolicy.canCapture(
            recording: state == .recording && activeManualPhotosEnabled,
            cameraAuthorized: cameraAuthorizedForPhoto,
            photoOutputAvailable: photoOutputAvailable,
            storageReady: batch != nil && queueStore?.hasSpaceForManualPhoto() == true,
            photoInFlight: photoInFlight,
            locationUsable: DrivingPhotoPolicy.locationIsUsable(
                latitude: location.coordinate.latitude, longitude: location.coordinate.longitude,
                accuracy: location.horizontalAccuracy, timestamp: location.timestamp, now: now,
                maxAge: cadenceConfiguration.maxLocationAge, maxAccuracy: cadenceConfiguration.maxAccuracyMeters),
            lastRequestAt: lastManualPhotoRequestAt, now: now
        )
    }

    private var cameraAuthorizedForPhoto: Bool {
#if DEBUG
        if testPhotoCapture != nil { return true }
#endif
        return AVCaptureDevice.authorizationStatus(for: .video) == .authorized
    }

    /// A tap shares the JPEG/queue pipeline without enabling automatic photos,
    /// consuming a sign-filter candidate, uploading, or finalizing the movie.
    @discardableResult
    func captureManualPhoto(location: CLLocation, speedKmh: Double) -> Bool {
        guard DrivingPhotoPolicy.showsButton(speedKmh: speedKmh),
              canCaptureManualPhoto(location: location) else { return false }
        return capture(location: location, speedMetersPerSecond: speedKmh / 3.6, signEvidence: [], manual: true)
    }

    private func capture(location: CLLocation, speedMetersPerSecond: Double?, signEvidence: [SignCaptureFilter.Evidence], manual: Bool = false) -> Bool {
        guard state == .recording,
              (manual ? activeManualPhotosEnabled : activePanoramaxEnabled),
              photoOutputAvailable,
              !photoInFlight,
              batch != nil else {
            return false
        }
        let accuracy = location.horizontalAccuracy
        let requestedAt = Date()
        if !signEvidence.isEmpty, let last = lastCaptureAt, requestedAt.timeIntervalSince(last) < 2 { return false }
        guard manual || PanoramaxCapturePolicy.isMoving(speedMetersPerSecond: speedMetersPerSecond ?? location.speed) else { return false }
        guard accuracy >= 0,
              accuracy.isFinite,
              requestedAt.timeIntervalSince(location.timestamp) <= cadenceConfiguration.maxLocationAge,
              location.timestamp <= requestedAt.addingTimeInterval(60), accuracy <= cadenceConfiguration.maxAccuracyMeters else {
            return false
        }
        let heading: Double?
        if location.course >= 0, location.course <= 360, location.courseAccuracy >= 0 {
            heading = location.course
        } else {
            heading = nil
        }
        let sample = PanoramaxLocationSample(
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            capturedAt: requestedAt,
            accuracyMeters: accuracy,
            altitudeMeters: location.altitude.isFinite ? location.altitude : nil,
            headingDegrees: heading
        )
        lastAccuracyMeters = accuracy
        guard manual || !signEvidence.isEmpty || PanoramaxCapturePolicy.shouldCapture(
            lastCapture: lastCaptureSample,
            current: sample,
            now: requestedAt,
            configuration: cadenceConfiguration
        ) else {
            notifyChange()
            return false
        }

        pendingSignEvidence = signEvidence
        pendingCaptureReason = manual ? "manual" : (signEvidence.isEmpty ? "cadence" : "recognized_sign")
        if manual {
            lastManualPhotoRequestAt = requestedAt
            manualPhotoCaptureFailed = false
        }
        pendingSample = sample
        pendingPhotoOrientationEpoch = orientationEpoch
        let photoAngle = screenOrientation.captureRotationAngle
        photoInFlight = true
        let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
        let maximumDimensions = photoOutput.maxPhotoDimensions
        if maximumDimensions.width > 0, maximumDimensions.height > 0 {
            settings.maxPhotoDimensions = maximumDimensions
        }
        pendingPhotoUniqueID = settings.uniqueID
        notifyChange()
#if DEBUG
        if let testPhotoCapture {
            testPhotoCapture(settings.uniqueID, photoAngle)
            return true
        }
#endif
        sessionQueue.async { [weak self] in
            guard let self else { return }
            guard self.session.isRunning, !self.session.isInterrupted,
                  let connection = self.photoOutput.connection(with: .video), connection.isActive else {
                Task { @MainActor [weak self] in
                    self?.finishPhoto(data: nil, error: nil, uniqueID: settings.uniqueID)
                }
                return
            }
            if connection.isVideoRotationAngleSupported(photoAngle) {
                connection.videoRotationAngle = photoAngle
            }
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
        return true
    }

    private func preparePanoramaxBatch(captureSessionID: String, requestedGeneration: Int) async {
        guard let queueStore else {
            activePanoramaxEnabled = false
            activeManualPhotosEnabled = false
            lastCaptureDetail = "Panoramax-Speicher nicht verfuegbar"
            return
        }
        do {
            let created = try await PanoramaxQueueMaintenanceExecutor.shared.perform(store: queueStore) {
                try $0.createBatch(captureSessionID: captureSessionID)
            }
            guard generation == requestedGeneration, (state == .preparing || state == .recording) else {
                // Stop/new start may run while JPEG work owns the queue lock.
                // Seal only this obsolete batch; never overwrite the new drive.
                _ = try? await PanoramaxQueueMaintenanceExecutor.shared.perform(store: queueStore) {
                    try $0.transitionBatch(created.batchID, to: .awaitingReview)
                }
                return
            }
            batch = created
        } catch {
            guard generation == requestedGeneration, (state == .preparing || state == .recording) else { return }
            activePanoramaxEnabled = false
            activeManualPhotosEnabled = false
            batch = nil
            lastCaptureDetail = "Panoramax-Batch konnte nicht erstellt werden: \(error.localizedDescription)"
        }
    }

    private func closePanoramaxBatchForReview() {
        if let batch, let queueStore {
            // FIFO with photo persistence: a finished still already queued for
            // storage must commit before the batch becomes reviewable.
            photoProcessingQueue.async { [weak self] in
                _ = try? queueStore.transitionBatch(batch.batchID, to: .awaitingReview)
                Task { @MainActor [weak self] in self?.onPanoramaxQueueChange?() }
            }
        }
        batch = nil
        lastCaptureSample = nil
    }

    private func configureSession(
        dashcamEnabled: Bool,
        trafficSignRecognitionEnabled: Bool,
        panoramaxEnabled: Bool
    ) throws {
        let supports4K = session.canSetSessionPreset(.hd4K3840x2160)
        try configureSessionGraph(
            preset: supports4K ? .hd4K3840x2160 : .high,
            dashcamEnabled: dashcamEnabled,
            trafficSignRecognitionEnabled: trafficSignRecognitionEnabled,
            panoramaxEnabled: panoramaxEnabled
        )

        // Dashcam is a live-selectable consumer even when it was off at drive
        // start. If the 4K multi-output graph cannot retain its dormant movie
        // output, rebuild once at the broadly supported high preset before the
        // session starts. No live graph is ever reconfigured.
        let requestedOutputMissing = !movieOutputAvailable
            || (panoramaxEnabled && !photoOutputAvailable)
            || !videoOutputAvailable
        if requestedOutputMissing, supports4K {
            try configureSessionGraph(
                preset: .high,
                dashcamEnabled: dashcamEnabled,
                trafficSignRecognitionEnabled: trafficSignRecognitionEnabled,
                panoramaxEnabled: panoramaxEnabled
            )
        }

        // A selected Panoramax session must never be reported as recording
        // without a still output. The Dashcam can continue on a reduced graph,
        // but silently dropping the photo consumer makes the user's setting
        // appear enabled while every GPS-triggered capture is discarded.
        if panoramaxEnabled, !photoOutputAvailable {
            throw RecorderError.panoramaxUnavailable
        }

        if dashcamEnabled, !movieOutputAvailable,
           !videoOutputAvailable, !photoOutputAvailable {
            throw RecorderError.sessionUnavailable
        }
    }

    private func configureSessionGraph(
        preset: AVCaptureSession.Preset,
        dashcamEnabled: Bool,
        trafficSignRecognitionEnabled: Bool,
        panoramaxEnabled: Bool
    ) throws {
        session.beginConfiguration()
        defer { session.commitConfiguration() }

        session.inputs.forEach(session.removeInput)
        session.outputs.forEach(session.removeOutput)
        movieOutputAvailable = false
        videoOutputAvailable = false
        photoOutputAvailable = false

        if session.canSetSessionPreset(preset) {
            session.sessionPreset = preset
        } else if session.canSetSessionPreset(.high) {
            session.sessionPreset = .high
        }

        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw RecorderError.cameraUnavailable
        }
        let input = try AVCaptureDeviceInput(device: camera)
        guard session.canAddInput(input) else {
            throw RecorderError.sessionUnavailable
        }

        session.addInput(input)
        configureRoadFocus(for: camera)

        func addMovieOutputIfPossible() {
            guard !movieOutputAvailable, session.canAddOutput(movieOutput) else { return }
            session.addOutput(movieOutput)
            movieOutput.movieFragmentInterval = CMTime(seconds: 10, preferredTimescale: 600)
            movieOutput.maxRecordedFileSize = Self.maximumDashcamFileBytes
            movieOutputAvailable = true
        }

        func addVideoOutputIfPossible() {
            guard !videoOutputAvailable, session.canAddOutput(videoOutput) else { return }
            session.addOutput(videoOutput)
            videoOutput.alwaysDiscardsLateVideoFrames = true
            videoOutput.videoSettings = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
            ]
            // Both analyzers consume native sensor coordinates. Set this only
            // while building the graph: VDO rotation physically rotates buffers
            // and changing it during recording rebuilds the capture pipeline.
            if let connection = videoOutput.connection(with: .video) {
                if connection.isVideoRotationAngleSupported(0) { connection.videoRotationAngle = 0 }
                if connection.isCameraIntrinsicMatrixDeliverySupported { connection.isCameraIntrinsicMatrixDeliveryEnabled = true }
                if connection.isVideoMirroringSupported {
                    connection.automaticallyAdjustsVideoMirroring = false
                    connection.isVideoMirrored = false
                }
            }
            videoOutput.setSampleBufferDelegate(frameDispatcher, queue: videoQueue)
            videoOutputAvailable = true
        }

        func addPhotoOutputIfPossible() {
            guard !photoOutputAvailable, session.canAddOutput(photoOutput) else { return }
            session.addOutput(photoOutput)
            if let dimensions = camera.activeFormat.supportedMaxPhotoDimensions.max(by: {
                Int64($0.width) * Int64($0.height) < Int64($1.width) * Int64($1.height)
            }) {
                photoOutput.maxPhotoDimensions = dimensions
            }
            photoOutputAvailable = true
        }

        // Keep the graph fixed while the session is running. Panoramax is a
        // selected still consumer, so attach it before the video outputs; on
        // devices with a constrained multi-output budget this prevents the
        // Dashcam/TSR streams from silently displacing photo capture.
        if panoramaxEnabled || (requestedManualPhotosEnabled && !dashcamEnabled && !trafficSignRecognitionEnabled) {
            addPhotoOutputIfPossible()
        }
        if dashcamEnabled { addMovieOutputIfPossible() }
        if trafficSignRecognitionEnabled { addVideoOutputIfPossible() }
        addMovieOutputIfPossible()
        addVideoOutputIfPossible()
        // Optional manual stills are attached last. A constrained device must
        // retain its selected movie/recognition outputs and disable the shutter
        // rather than reconfigure or fail the live session.
        if requestedManualPhotosEnabled { addPhotoOutputIfPossible() }
        videoOutput.connection(with: .video)?.isEnabled = trafficSignRecognitionEnabled
            && frameDispatcher.hasConsumer
        guard movieOutputAvailable || videoOutputAvailable || photoOutputAvailable else {
            throw RecorderError.sessionUnavailable
        }
    }

    /// Photos, Dashcam and TSR share road-focused autofocus. Restrict scans to
    /// distant subjects where supported to avoid focusing on the windscreen.
    private func configureRoadFocus(for camera: AVCaptureDevice) {
        do {
            try DriveCameraFocusConfiguration.apply(to: camera)
        } catch {
            Self.logger.error("Could not configure rear camera autofocus: \(error.localizedDescription, privacy: .public)")
        }
    }

    nonisolated private func configureMovieCodecIfPossible(rotationAngle: CGFloat) {
        guard let connection = movieOutput.connection(with: .video) else { return }
        if connection.isVideoRotationAngleSupported(rotationAngle) {
            connection.videoRotationAngle = rotationAngle
        }
        let codec: AVVideoCodecType = movieOutput.availableVideoCodecTypes.contains(.hevc) ? .hevc : .h264
        movieOutput.setOutputSettings([AVVideoCodecKey: codec], for: connection)
    }

    private func finishPhoto(data: Data?, error: Error?, uniqueID: Int64) {
        // A callback from a drive that has already stopped must never consume
        // the location sample or batch belonging to a newly started drive.
        guard pendingPhotoUniqueID == uniqueID else { return }
        guard state == .recording,
              let data,
              let sample = pendingSample,
              let batch,
              let queueStore else {
            photoInFlight = false
            pendingSample = nil
            pendingPhotoUniqueID = nil
            if !manualPhotoMoving {
                activeManualPhotosEnabled = false
                if !activePanoramaxEnabled { closePanoramaxBatchForReview() }
            }
            if state == .recording {
                if pendingCaptureReason == "manual" { manualPhotoCaptureFailed = true }
                lastCaptureDetail = error.map { "Aufnahme fehlgeschlagen: \($0.localizedDescription)" } ?? "Aufnahme verworfen"
            }
            notifyChange()
            return
        }
        let storageLimit = storageLimitBytes
        let signEvidence = pendingSignEvidence
        let captureReason = pendingCaptureReason
        let annotationDraft = pendingPhotoOrientationEpoch == orientationEpoch
            ? latestTrafficSignAnnotationDraft : nil
        latestTrafficSignAnnotationDraft = nil
        photoProcessingQueue.async { [weak self] in
            let result = Self.persistPanoramaxPhoto(
                data: data,
                sample: sample,
                batch: batch,
                queueStore: queueStore,
                storageLimitBytes: storageLimit,
                annotationDraft: annotationDraft, signEvidence: signEvidence, captureReason: captureReason
            )
            Task { @MainActor [weak self] in
                self?.finishPhotoProcessing(uniqueID: uniqueID, result: result)
            }
        }
    }

    private func finishPhotoProcessing(uniqueID: Int64, result: PanoramaxPhotoProcessingResult) {
        guard pendingPhotoUniqueID == uniqueID else { return }
        defer {
            photoInFlight = false
            pendingSample = nil
            pendingPhotoUniqueID = nil
            if !manualPhotoMoving {
                activeManualPhotosEnabled = false
                if !activePanoramaxEnabled { closePanoramaxBatchForReview() }
            }
            notifyChange()
        }
        guard state == .recording else { return }
        lastCaptureDetail = result.detail
        if pendingCaptureReason == "manual" { manualPhotoCaptureFailed = !result.saved }
        guard result.saved else { return }
        lastCaptureSample = result.sample
        capturedImageCount += 1
        lastCaptureAt = result.sample.capturedAt
        lastCaptureDetail = "Panoramax-Bild \(capturedImageCount) lokal gespeichert"
        if let annotationLogLine = result.annotationLogLine {
            onTrafficSignAnnotation?(annotationLogLine)
        }
    }

    private func finishDashcamToggleFailure(_ detail: String, token: UUID?) {
        if let token {
            guard dashcamTransition?.token == token else { return }
        }
        completeInteractionFinalization(.failure(DriveInteractionError.finalizationFailed))
        activeDashcamEnabled = false
        activeDashcamRecordingURL = nil
        dashcamFileURL = nil
        clearDashcamTransition()
        lastCaptureDetail = detail
        if state == .recording, !activePanoramaxEnabled, !activeManualPhotosEnabled, !activeTSREnabled {
            beginStopping(resultState: .failed, detail: detail)
        } else {
            notifyChange()
        }
    }

    private func finishDashcamDisableWithoutCallback(token: UUID) {
        guard dashcamTransition?.token == token else { return }
        completeInteractionFinalization(.failure(DriveInteractionError.finalizationFailed))
        activeDashcamEnabled = false
        activeDashcamRecordingURL = nil
        clearDashcamTransition()
        lastCaptureDetail = "Dashcam-Aufnahme beendet"
        if state == .recording, !activePanoramaxEnabled, !activeManualPhotosEnabled, !activeTSREnabled {
            beginStopping(resultState: .disabled, detail: lastCaptureDetail)
        } else {
            notifyChange()
        }
    }

    private func beginDashcamTransition(_ transition: DashcamTransition) {
        dashcamTransitionTimeoutTask?.cancel()
        dashcamTransition = transition
        dashcamTransitionInFlight = true
        let token = transition.token
        dashcamTransitionTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(6))
            guard !Task.isCancelled,
                  let self,
                  state == .recording,
                  dashcamTransition?.token == token else { return }
            switch transition {
            case .starting:
                finishDashcamToggleFailure("Dashcam-Start hat zu lange gedauert", token: token)
                sessionQueue.async { [weak self] in
                    guard let self, self.movieOutput.isRecording else { return }
                    self.movieOutput.stopRecording()
                }
            case .stopping:
                clearDashcamTransition()
                lastCaptureDetail = "Dashcam konnte nicht sicher beendet werden"
                completeInteractionFinalization(.failure(DriveInteractionError.finalizationFailed))
                notifyChange()
            }
        }
    }

    private func clearDashcamTransition() {
        dashcamTransitionTimeoutTask?.cancel()
        dashcamTransitionTimeoutTask = nil
        dashcamTransition = nil
        dashcamTransitionInFlight = false
    }

    private func resetActiveModulesAfterFailure() {
        frameDispatcher.setCaptureSessionID(nil)
        completeInteractionFinalization(.failure(DriveInteractionError.finalizationFailed))
        activeDashcamEnabled = false
        activePanoramaxEnabled = false
        activeManualPhotosEnabled = false
        activeTSREnabled = false
        activeDashcamRecordingURL = nil
        clearDashcamTransition()
        captureSessionID = nil
        frameDispatcher.setEnabled(false)
        activeLanesEnabled = false
        frameDispatcher.setLanesEnabled(false)
    }

    nonisolated private static func persistPanoramaxPhoto(
        data: Data,
        sample: PanoramaxLocationSample,
        batch: PanoramaxBatchRecord,
        queueStore: PanoramaxQueueStore,
        storageLimitBytes: Int64?,
        annotationDraft: PanoramaxTrafficSignAnnotationDraft?, signEvidence: [SignCaptureFilter.Evidence], captureReason: String
    ) -> PanoramaxPhotoProcessingResult {
        let dimensions = PanoramaxJPEGMetadata.pixelDimensions(from: data)
        let annotations: [PanoramaxTrafficSignAnnotation]
        if let dimensions,
           let annotation = annotationDraft?.projected(
               imageWidth: dimensions.width,
               imageHeight: dimensions.height,
               imageTimestamp: sample.capturedAt
           ) {
            annotations = [annotation]
        } else {
            annotations = []
        }
        let panoramaxJPEG = PanoramaxJPEGMetadata.adding(
            to: data,
            location: sample,
            annotations: annotations
        ) ?? data
        guard let thumbnail = makeThumbnail(from: panoramaxJPEG) else {
            return PanoramaxPhotoProcessingResult(sample: sample, saved: false, detail: "Vorschaubild konnte nicht erstellt werden")
        }
        let metadata = PanoramaxCaptureMetadata(
            captureID: UUID().uuidString,
            captureSessionID: batch.captureSessionID,
            capturedAt: sample.capturedAt,
            location: sample,
            sha256: PanoramaxQueueStore.sha256(panoramaxJPEG),
            byteSize: Int64(panoramaxJPEG.count),
            software: "YouSpeed/1.0.1",
            imageWidthPixels: dimensions?.width,
            imageHeightPixels: dimensions?.height,
            trafficSignAnnotations: annotations.isEmpty ? nil : annotations,
            captureReason: captureReason, signEvidence: signEvidence.isEmpty ? nil : signEvidence
        )
        do {
            _ = try queueStore.addJPEG(
                batchID: batch.batchID,
                jpeg: panoramaxJPEG,
                thumbnail: thumbnail,
                metadata: metadata
            )
            let annotationLogLine = annotations.first.map {
                "event_id=\($0.sourceEventID) image_id=\(metadata.captureID) speed_kmh=\($0.speedLimitKmh)"
            }
            if let storageLimitBytes {
                _ = try? queueStore.enforceStorageLimit(maxBytes: storageLimitBytes)
            }
            return PanoramaxPhotoProcessingResult(
                sample: sample,
                saved: true,
                detail: "Panoramax-Bild lokal gespeichert",
                annotationLogLine: annotationLogLine
            )
        } catch {
            return PanoramaxPhotoProcessingResult(sample: sample, saved: false, detail: "Aufnahme konnte nicht gespeichert werden")
        }
    }

    private func finishStopping(generation stopGeneration: Int) {
        guard generation == stopGeneration, state == .stopping else { return }
        stopTimeoutTask?.cancel()
        stopTimeoutTask = nil
        state = stopResultState
        startedAt = nil
        activeDashcamEnabled = false
        activePanoramaxEnabled = false
        activeManualPhotosEnabled = false
        activeTSREnabled = false
        activeDashcamRecordingURL = nil
        clearDashcamTransition()
        captureSessionID = nil
        sessionPurpose = nil
        latestTrafficSignAnnotationDraft = nil
        lastCaptureDetail = stopResultDetail ?? (capturedImageCount > 0
            ? "\(capturedImageCount) Panoramax-Bilder fuer spaeter gespeichert"
            : "Aufnahme beendet")
        stopResultState = .disabled
        stopResultDetail = nil
        notifyChange()
    }

    private func finishStarting(generation requestedGeneration: Int) {
        guard generation == requestedGeneration, state == .preparing else { return }
        defer {
            if interactionFinalization != nil {
                if needsDashcamFinalization {
                    stopDashcamForPendingInteraction()
                } else if state == .recording {
                    // The camera may have fallen back to stills/TSR before an
                    // encoder was created. There is then no movie to finalize.
                    completeInteractionFinalization(.success(()))
                }
            }
        }
        guard activeDashcamEnabled || activePanoramaxEnabled || activeManualPhotosEnabled || activeTSREnabled || (calibrationPreviewEnabled && videoOutputAvailable) else {
            beginStopping(
                resultState: .unavailable,
                detail: "Kein aktiviertes Kameramodul ist mehr verfuegbar"
            )
            return
        }
        startTimeoutTask?.cancel()
        startTimeoutTask = nil
        startedAt = Date()
        state = .recording
        if activePanoramaxEnabled {
            lastCaptureDetail = "Panoramax-Bilder werden lokal gesammelt"
        } else if activeDashcamEnabled {
            lastCaptureDetail = "Dashcam-Aufnahme aktiv"
        } else if activeTSREnabled {
            lastCaptureDetail = "Verkehrszeichenerkennung aktiv"
        } else if activeManualPhotosEnabled {
            lastCaptureDetail = NSLocalizedString("drive_photo.ready", comment: "")
        } else if calibrationPreviewEnabled {
            lastCaptureDetail = NSLocalizedString("calibration.live", comment: "")
        }
        notifyChange()
    }

    private func scheduleStartTimeout(generation requestedGeneration: Int) {
        startTimeoutTask?.cancel()
        startTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(8))
            guard !Task.isCancelled,
                  let self,
                  generation == requestedGeneration,
                  state == .preparing else { return }
            beginStopping(resultState: .failed, detail: "Kamera-Start hat zu lange gedauert")
        }
    }

    private func scheduleStopTimeout(generation stopGeneration: Int) {
        stopTimeoutTask?.cancel()
        stopTimeoutTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled,
                  let self,
                  generation == stopGeneration,
                  state == .stopping else { return }
            lastCaptureDetail = "Kamera wird noch beendet"
            notifyChange()
            finishStoppingAfterSessionQueue(generation: stopGeneration)
        }
    }

    /// A stop timeout may recover from a missing movie-finalization callback,
    /// but it must never make the coordinator restartable while stopRunning()
    /// is still blocked. Queueing this barrier after the stop operation keeps
    /// all AVCaptureSession mutations serialized.
    private func finishStoppingAfterSessionQueue(generation stopGeneration: Int) {
        guard generation == stopGeneration, state == .stopping else { return }
        sessionQueue.async { [weak self] in
            Task { @MainActor [weak self] in
                self?.finishStopping(generation: stopGeneration)
            }
        }
    }

    private func observeSessionFailures() {
        let center = NotificationCenter.default
        notificationTokens.append(center.addObserver(
            forName: .AVCaptureSessionWasInterrupted,
            object: session,
            queue: nil
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.beginStopping(resultState: .failed, detail: "Kamera wurde unterbrochen; lokale Daten wurden abgeschlossen")
            }
        })
        notificationTokens.append(center.addObserver(
            forName: .AVCaptureSessionRuntimeError,
            object: session,
            queue: nil
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.beginStopping(resultState: .failed, detail: "Kamera-Fehler; lokale Daten wurden abgeschlossen")
            }
        })
    }

    private func logPathRecording(event: String, url: URL) {
        let duration = CMTimeGetSeconds(movieOutput.recordedDuration)
        var value: [String:Any] = ["event":event,"videoFile":url.lastPathComponent,
            "observedAtSeconds":Date().timeIntervalSince1970,"timingQuality":"callback_anchor_estimated"]
        if duration.isFinite && duration >= 0 { value["recordedDurationSeconds"] = duration }
        if let data = try? JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]), let json = String(data:data,encoding:.utf8) {
            onDiagnostic?("tsr_path_recording_v1=\(json)")
        }
    }

    private func handleMovieFinished(
        url: URL,
        successful: Bool,
        errorSummary: String?
    ) {
        logPathRecording(event:"stop",url:url)
        if let errorSummary {
            Self.logger.error(
                "movie output finished file=\(url.lastPathComponent, privacy: .public) successful=\(successful, privacy: .public) error=\(errorSummary, privacy: .public)"
            )
        }
        guard dashcamFileURL?.standardizedFileURL == url.standardizedFileURL else {
            if successful {
                Self.protectRecordedFile(at: url)
                enforceDashcamStorageLimitUnlessIsolatedTest(retaining: url)
            } else {
                try? FileManager.default.removeItem(at: url)
            }
            return
        }
        defer {
            completeInteractionFinalization(successful
                ? .success(()) : .failure(DriveInteractionError.finalizationFailed))
        }
        if successful {
            dashcamFileURL = url
            Self.protectRecordedFile(at: url)
            enforceDashcamStorageLimitUnlessIsolatedTest(retaining: url)
        } else {
            try? FileManager.default.removeItem(at: url)
            dashcamFileURL = nil
        }
        let transition = dashcamTransition?.matches(url: url) == true ? dashcamTransition : nil
        let wasLiveToggle = transition != nil
        if transition != nil {
            clearDashcamTransition()
        }
        if activeDashcamRecordingURL?.standardizedFileURL == url.standardizedFileURL {
            activeDashcamRecordingURL = nil
        }
        activeDashcamEnabled = false
        if state == .stopping {
            finishStoppingAfterSessionQueue(generation: generation)
        } else if state == .preparing {
            activeDashcamEnabled = false
            beginStopping(resultState: .failed, detail: "Dashcam-Aufnahme konnte nicht gestartet werden")
        } else if state == .recording {
            activeDashcamEnabled = false
            if DriveRecorderPolicy.shouldKeepCameraAfterMovieFinalization(
                panoramaxActive: activePanoramaxEnabled || activeManualPhotosEnabled,
                trafficSignRecognitionActive: activeTSREnabled,
                successful: successful,
                actionPending: interactionFinalization != nil
            ) {
                if wasLiveToggle, successful {
                    lastCaptureDetail = activePanoramaxEnabled || activeManualPhotosEnabled || activeTSREnabled
                        ? "Dashcam-Aufnahme gespeichert; andere Kameramodule laufen weiter"
                        : "Dashcam-Aufnahme gespeichert"
                } else {
                    lastCaptureDetail = successful
                        ? "Dashcam-Dateigrenze erreicht; andere Kameramodule laufen weiter"
                        : "Dashcam-Aufnahme beendet; andere Kameramodule laufen weiter"
                }
                notifyChange()
            } else {
                beginStopping(
                    resultState: successful ? .disabled : .failed,
                    detail: successful ? "Dashcam-Dateigrenze erreicht" : "Dashcam-Aufnahme fehlgeschlagen"
                )
            }
        } else {
            notifyChange()
        }
    }

    private func handleMovieStarted(url: URL) {
        logPathRecording(event:"start",url:url)
        defer { stopDashcamForPendingInteraction() }
        guard dashcamFileURL?.standardizedFileURL == url.standardizedFileURL else {
            sessionQueue.async { [weak self] in
                guard let self,
                      self.movieOutput.isRecording,
                      self.movieOutput.outputFileURL?.standardizedFileURL == url.standardizedFileURL else { return }
                self.movieOutput.stopRecording()
            }
            return
        }
        if state == .preparing {
            activeDashcamRecordingURL = url
            activeDashcamEnabled = true
            finishStarting(generation: generation)
        } else if state == .recording,
                  case .starting(let expectedURL, _) = dashcamTransition,
                  expectedURL.standardizedFileURL == url.standardizedFileURL {
            activeDashcamRecordingURL = url
            activeDashcamEnabled = true
            clearDashcamTransition()
            lastCaptureDetail = "Dashcam-Aufnahme aktiv"
            notifyChange()
        } else if state == .recording,
                  activeDashcamEnabled,
                  activeDashcamRecordingURL?.standardizedFileURL == url.standardizedFileURL {
            return
        } else {
            // A callback can arrive after a global stop or a live-start timeout.
            // Never let it revive UI state; stop the orphan encoder instead.
            sessionQueue.async { [weak self] in
                guard let self, self.movieOutput.isRecording else { return }
                self.movieOutput.stopRecording()
            }
        }
    }

    private nonisolated static func recordingErrorSummary(_ error: NSError?) -> String? {
        guard let error else { return nil }
        var parts = [
            "\(error.domain)(\(error.code))",
            error.localizedDescription,
        ]
        if let underlying = error.userInfo[NSUnderlyingErrorKey] as? NSError {
            parts.append(
                "underlying=\(underlying.domain)(\(underlying.code)): \(underlying.localizedDescription)"
            )
        }
        if let finished = error.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool {
            parts.append("recordingSuccessfullyFinished=\(finished)")
        }
        return parts.joined(separator: "; ")
    }

    private enum DashcamTransition {
        case starting(url: URL, token: UUID)
        case stopping(url: URL, token: UUID)

        var token: UUID {
            switch self {
            case .starting(_, let token), .stopping(_, let token):
                return token
            }
        }

        func matches(url: URL) -> Bool {
            let expectedURL: URL
            switch self {
            case .starting(let url, _), .stopping(let url, _):
                expectedURL = url
            }
            return expectedURL.standardizedFileURL == url.standardizedFileURL
        }
    }

    private func makeDashcamFileURL(captureSessionID: String) throws -> URL {
        let filename = "drive-\(captureSessionID)-\(UUID().uuidString).mov"
#if DEBUG
        if let directory = testDashcamOutputDirectory {
            let url = directory.appendingPathComponent(filename).standardizedFileURL
            isolatedTestDashcamURLs.insert(url)
            return url
        }
#endif
        return try Self.dashcamDirectory().appendingPathComponent(filename)
    }

    private func enforceDashcamStorageLimitUnlessIsolatedTest(retaining url: URL) {
#if DEBUG
        if isolatedTestDashcamURLs.contains(url.standardizedFileURL) { return }
#endif
        Self.enforceDashcamStorageLimit(retaining: url)
    }

    static func listDashcamRecordings() -> [DashcamRecording] {
        guard let root = try? dashcamDirectory(),
              let urls = try? FileManager.default.contentsOfDirectory(
                at: root,
                includingPropertiesForKeys: [.creationDateKey, .contentModificationDateKey, .fileSizeKey],
                options: [.skipsHiddenFiles]
              ) else { return [] }
        return urls.compactMap { url in
            guard url.pathExtension.lowercased() == "mov",
                  let values = try? url.resourceValues(forKeys: [.creationDateKey, .contentModificationDateKey, .fileSizeKey]) else {
                return nil
            }
            return DashcamRecording(
                id: url.lastPathComponent,
                url: url,
                createdAt: values.creationDate ?? values.contentModificationDate ?? .distantPast,
                byteSize: Int64(values.fileSize ?? 0)
            )
        }
        .sorted { $0.createdAt > $1.createdAt }
    }

    @discardableResult
    static func deleteDashcamRecording(id: String) -> Bool {
        guard id == URL(fileURLWithPath: id).lastPathComponent,
              id.hasSuffix(".mov"),
              let root = try? dashcamDirectory() else { return false }
        let target = root.appendingPathComponent(id)
        guard FileManager.default.fileExists(atPath: target.path) else { return false }
        do {
            try FileManager.default.removeItem(at: target)
            return true
        } catch {
            return false
        }
    }

    private static func dashcamDirectory() throws -> URL {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        var root = base
            .appendingPathComponent("YouSpeed", isDirectory: true)
            .appendingPathComponent("DriveRecorder", isDirectory: true)
            .appendingPathComponent("Videos", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try root.setResourceValues(values)
        try FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: root.path
        )
        return root
    }

    private static func enforceDashcamStorageLimit(retaining retainedURL: URL) {
        var recordings = listDashcamRecordings()
        var total = recordings.reduce(Int64(0)) { $0 + $1.byteSize }
        guard total > dashcamRetentionBytes else { return }
        recordings.sort { $0.createdAt < $1.createdAt }
        for recording in recordings where total > dashcamRetentionBytes {
            guard recording.url.standardizedFileURL != retainedURL.standardizedFileURL else { continue }
            if deleteDashcamRecording(id: recording.id) {
                total -= recording.byteSize
            }
        }
    }

    private static func protectRecordedFile(at url: URL) {
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
        var protectedURL = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? protectedURL.setResourceValues(values)
    }

    nonisolated private static func makeThumbnail(from data: Data) -> Data? {
        guard let image = UIImage(data: data),
              let thumbnail = image.preparingThumbnail(of: CGSize(width: 640, height: 360)) else {
            return nil
        }
        return thumbnail.jpegData(compressionQuality: 0.72)
    }

    private func notifyChange() {
        let snapshot = "state=\(state) purpose=\(String(describing: sessionPurpose)) photos_requested=\(requestedPanoramaxEnabled) photos_active=\(activePanoramaxEnabled) photo_output=\(photoOutputAvailable) dashcam_active=\(activeDashcamEnabled) tsr_active=\(activeTSREnabled) photos=\(capturedImageCount) detail=\(lastCaptureDetail)"
        if snapshot != lastDiagnosticSnapshot {
            lastDiagnosticSnapshot = snapshot
            Self.logger.notice("capture_state \(snapshot, privacy: .public)")
            onDiagnostic?(snapshot)
        }
        onChange?()
    }

    private enum RecorderError: Error, Equatable {
        case cameraUnavailable
        case sessionUnavailable
        case panoramaxUnavailable
        case noEnabledModuleAvailable

        var isAvailabilityFailure: Bool {
            self == .cameraUnavailable || self == .sessionUnavailable
                || self == .panoramaxUnavailable || self == .noEnabledModuleAvailable
        }
    }
}

extension DriveCaptureCoordinator: AVCapturePhotoCaptureDelegate {
    nonisolated func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        let data = photo.fileDataRepresentation()
        let uniqueID = photo.resolvedSettings.uniqueID
        Task { @MainActor [weak self] in
            self?.finishPhoto(data: data, error: error, uniqueID: uniqueID)
        }
    }
}

extension DriveCaptureCoordinator: AVCaptureFileOutputRecordingDelegate {
    nonisolated func fileOutput(
        _ output: AVCaptureFileOutput,
        didStartRecordingTo fileURL: URL,
        from connections: [AVCaptureConnection]
    ) {
        Task { @MainActor [weak self] in
            self?.handleMovieStarted(url: fileURL)
        }
    }

    nonisolated func fileOutput(
        _ output: AVCaptureFileOutput,
        didFinishRecordingTo outputFileURL: URL,
        from connections: [AVCaptureConnection],
        error: Error?
    ) {
        let nsError = error as NSError?
        let successful = error == nil
            || (nsError?.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool == true)
        let errorSummary = Self.recordingErrorSummary(nsError)
        Task { @MainActor [weak self] in
            self?.handleMovieFinished(
                url: outputFileURL,
                successful: successful,
                errorSummary: errorSummary
            )
        }
    }
}

// Compatibility aliases keep existing call sites and tests source-compatible
// while camera ownership moves from the Panoramax feature to the shared drive.
typealias PanoramaxRecorderState = DriveRecorderState
typealias PanoramaxRecorder = DriveCaptureCoordinator

@MainActor
private enum LanePreviewStyle {
    static let color = UIColor(red: 57 / 255.0, green: 1, blue: 20 / 255.0, alpha: 1)
    // The camera eye and outer sign ring are about 4–6 points on the dashboard.
    static let strokeWidth: CGFloat = 5
    static let outlineWidth: CGFloat = 1
}

struct DriveCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    var orientation: ScreenOrientation = .portrait
    var laneRuntime: LaneDetectionRuntime? = nil
    var roadPathSession: RoadPathSession? = nil
    var calibrationStore: VisualRoadCalibrationStore? = nil
    var sourceGeometryProvider: (() -> LanePreviewSourceGeometry?)? = nil
    var activityAllowedProvider: (() -> Bool)? = nil
    var contextAvailableProvider: (() -> Bool)? = nil
    var onLanePresentation: ((LanePreviewPresentationDiagnostic) -> Void)? = nil
    var showDetectedLanes = false
    var legacyLanesAllowed = false
    var previewVisible = false

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.orientation = orientation
        view.videoPreviewLayer.session = session
        view.videoPreviewLayer.videoGravity = .resizeAspectFill
        view.setLanePresentation(calibrationStore: calibrationStore, source: sourceGeometryProvider,
            active: activityAllowedProvider, context: contextAvailableProvider, diagnostic: onLanePresentation)
        view.setLanePreview(runtime: laneRuntime, pathSession: roadPathSession, enabled: showDetectedLanes, visible: previewVisible, legacyAllowed: legacyLanesAllowed)
        view.updateVideoRotation()
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.orientation = orientation
        if uiView.videoPreviewLayer.session !== session {
            uiView.videoPreviewLayer.session = session
        }
        uiView.setLanePresentation(calibrationStore: calibrationStore, source: sourceGeometryProvider,
            active: activityAllowedProvider, context: contextAvailableProvider, diagnostic: onLanePresentation)
        uiView.setLanePreview(runtime: laneRuntime, pathSession: roadPathSession, enabled: showDetectedLanes, visible: previewVisible, legacyAllowed: legacyLanesAllowed)
        uiView.updateVideoRotation()
    }

    static func dismantleUIView(_ uiView: PreviewView, coordinator: Void) {
        uiView.setLanePreview(runtime: nil, pathSession: nil, enabled: false, visible: false)
        uiView.setLanePresentation(calibrationStore: nil, source: nil, active: nil, context: nil, diagnostic: nil)
        uiView.videoPreviewLayer.session = nil
    }

    final class PreviewView: UIView {
        var orientation: ScreenOrientation = .portrait
        private var laneRuntime: LaneDetectionRuntime?
        private var roadPathSession: RoadPathSession?
        private var calibrationStore: VisualRoadCalibrationStore?
        private var sourceGeometryProvider: (() -> LanePreviewSourceGeometry?)?
        private var activityAllowedProvider: (() -> Bool)?
        private var contextAvailableProvider: (() -> Bool)?
        private var onLanePresentation: ((LanePreviewPresentationDiagnostic) -> Void)?
        private var lanesEnabled = false
        private var legacyLanesAllowed = false
        private var previewVisible = false
        #if DEBUG
        var testIsLanePreviewVisible: Bool { lanesEnabled && testIsCameraPreviewVisible }
        var testIsCameraPreviewVisible: Bool {
            guard previewVisible,let window,!bounds.isEmpty else { return false }
            var ancestor: UIView? = self
            while let view=ancestor {
                if view.isHidden || view.alpha<=0.01 || view.layer.opacity<=0.01 { return false }
                ancestor=view.superview
            }
            return window.bounds.intersects(convert(bounds,to:window))
        }
        #endif
        private let laneOutline = CAShapeLayer()
        private let laneLines = CAShapeLayer()
        private let laneFill = CAShapeLayer()
        private let calibrationReferenceLines = CAShapeLayer()
        private let referenceHysteresis = LaneReferenceHysteresis()
        private let laneStatus = UILabel()
        private var laneTimer: Timer?
        private let legacyPresentationGate = RoadBoundaryPresentationGate()
        private var legacyPresentationKey: String?
        private var legacyPresentedFrameID: UInt64?
        private var legacyVisibleIndices: [Int] = []

        override init(frame: CGRect) {
            super.init(frame: frame)
            laneLines.fillColor = UIColor.clear.cgColor
            laneLines.strokeColor = LanePreviewStyle.color.cgColor
            laneLines.lineWidth = LanePreviewStyle.strokeWidth
            laneLines.lineJoin = .round
            laneLines.lineCap = .round
            laneOutline.fillColor = UIColor.clear.cgColor
            laneOutline.strokeColor = UIColor.black.withAlphaComponent(0.8).cgColor
            laneOutline.lineWidth = LanePreviewStyle.strokeWidth + LanePreviewStyle.outlineWidth * 2
            laneOutline.lineJoin = .round
            laneOutline.lineCap = .round
            calibrationReferenceLines.fillColor = UIColor.clear.cgColor
            calibrationReferenceLines.strokeColor = LanePreviewStyle.color.cgColor
            calibrationReferenceLines.lineWidth = LanePreviewStyle.strokeWidth
            calibrationReferenceLines.lineDashPattern = [14,10]
            calibrationReferenceLines.lineDashPattern = [14, 10]
            calibrationReferenceLines.lineCap = .round
            calibrationReferenceLines.opacity = 0.28
            layer.addSublayer(calibrationReferenceLines)
            layer.addSublayer(laneFill)
            layer.addSublayer(laneOutline)
            layer.addSublayer(laneLines)
            laneStatus.font = .preferredFont(forTextStyle: .caption2)
            laneStatus.textColor = .white
            laneStatus.backgroundColor = UIColor.black.withAlphaComponent(0.65)
            laneStatus.layer.cornerRadius = 5
            laneStatus.clipsToBounds = true
            addSubview(laneStatus)
            isAccessibilityElement = true
            clipsToBounds = true
        }

        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

        func setLanePresentation(calibrationStore: VisualRoadCalibrationStore?, source: (() -> LanePreviewSourceGeometry?)?,
                                 active: (() -> Bool)?, context: (() -> Bool)?,
                                 diagnostic: ((LanePreviewPresentationDiagnostic) -> Void)?) {
            self.calibrationStore = calibrationStore; sourceGeometryProvider = source
            activityAllowedProvider = active; contextAvailableProvider = context; onLanePresentation = diagnostic
        }

        func setLanePreview(runtime: LaneDetectionRuntime?, pathSession: RoadPathSession?, enabled: Bool, visible: Bool, legacyAllowed: Bool = false) {
            if laneRuntime !== runtime { laneRuntime?.setPreview(visible: false, rotation: 90) }
            laneRuntime = runtime
            roadPathSession = pathSession
            lanesEnabled = enabled
            if legacyLanesAllowed != legacyAllowed { resetLegacyPresentation() }
            legacyLanesAllowed = legacyAllowed
            previewVisible = visible
            updateLaneActivity()
        }

        private func updateLaneActivity() {
            let visible = lanesEnabled && previewVisible && window != nil
            let previewConnection = videoPreviewLayer.connection
            let rotation = Int(previewConnection?.videoRotationAngle ?? 90)
            laneRuntime?.setPreview(visible: visible, rotation: rotation)
            if visible && laneTimer == nil {
                let timer = Timer(timeInterval: 1.0 / 15, repeats: true) { [weak self] _ in self?.drawLanes() }
                RunLoop.main.add(timer, forMode: .common)
                laneTimer = timer
            } else if !visible {
                resetLegacyPresentation()
                laneTimer?.invalidate()
                laneTimer = nil
            }
            drawLanes()
        }

        private func showLaneCurves(lines: UIBezierPath, opacity: Float) {
            laneLines.path = lines.cgPath
            laneOutline.path = lines.cgPath
            for marker in [laneLines, laneOutline] { marker.opacity = opacity }
        }

        private func appendSmoothBoundary(_ points: [LanePoint], to path: UIBezierPath,
                                          project: (LanePoint) -> CGPoint) {
            var last: LanePoint?
            for curve in LaneBoundaryBezier.fit(points) {
                if last != curve.start { path.move(to: project(curve.start)) }
                path.addCurve(to: project(curve.end), controlPoint1: project(curve.control1), controlPoint2: project(curve.control2))
                last = curve.end
            }
        }

        private func resetLegacyPresentation() {
            legacyPresentationGate.reset(); legacyPresentationKey = nil
            legacyPresentedFrameID = nil; legacyVisibleIndices = []
        }

        private func matureLegacyBoundaries(_ frame: LaneOverlayFrame, source: LanePreviewSourceGeometry,
                                            calibrationRevision: String?) -> [LaneBoundary] {
            let key = "\(source.geometryKey):\(frame.generation):\(calibrationRevision ?? "none")"
            if legacyPresentationKey != key {
                resetLegacyPresentation(); legacyPresentationKey = key
            }
            let boundaries = [frame.estimate.left, frame.estimate.right].compactMap { $0 }
            if legacyPresentedFrameID != frame.frameID {
                let evidence = boundaries.map { RoadBoundaryEvidence(points: $0.points,
                    confidence: $0.confidence, cue: .paint, supportRows: $0.points.count) }
                let snapshot = legacyPresentationGate.update(boundaries: evidence,
                    exposureSeconds: frame.estimate.timestampSeconds, key: key)
                legacyVisibleIndices = snapshot.visibleBoundaryIndices
                legacyPresentedFrameID = frame.frameID
            }
            return legacyVisibleIndices.compactMap { boundaries.indices.contains($0) ? boundaries[$0] : nil }
        }

        private func drawLanes() {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            defer { CATransaction.commit() }
            for shape in [laneLines, laneOutline, laneFill, calibrationReferenceLines] { shape.path = nil }
            laneStatus.isHidden = true
            accessibilityValue = nil
            let source = sourceGeometryProvider?(), profile = calibrationStore?.snapshot()
            let now = ProcessInfo.processInfo.systemUptime, utc = Date().timeIntervalSince1970
            let rotation = Int(videoPreviewLayer.connection?.videoRotationAngle ?? 90)
            let thermal = ProcessInfo.processInfo.thermalState
            let thermalPaused = thermal == .serious || thermal == .critical
            let active = activityAllowedProvider?() == true && UIApplication.shared.applicationState == .active
                && videoPreviewLayer.session?.isRunning == true && videoPreviewLayer.connection?.isEnabled == true
            let visible = previewVisible && window != nil
            let compatibleProfile = source.flatMap { source in profile.flatMap {
                $0.compatible(width: source.imageWidth, height: source.imageHeight, orientationKey: source.orientationKey) ? $0 : nil
            } }
            let path = roadPathSession?.overlay()
            let pathAge = path.map { utc - $0.capturedAtSeconds }
            let validPath = path.flatMap { path -> RoadPathLiveOverlay? in
                guard let source, path.captureSessionID == source.captureSessionID,
                      path.rawWidth == source.rawWidth, path.rawHeight == source.rawHeight,
                      path.rotationDegrees == source.rotationDegrees, path.orientationKey == source.orientationKey,
                      path.visualCalibrationRevision == compatibleProfile?.revision,
                      let pathAge, pathAge >= 0, pathAge < 0.75 else { return nil }
                return path
            }
            let legacy = laneRuntime?.snapshot()
            let legacyFrame = legacy?.frame.flatMap { frame -> LaneOverlayFrame? in
                guard LanePreviewPresentationPolicy.legacyFrameIsCurrent(capturedAtSeconds: frame.estimate.timestampSeconds,
                    nowSeconds: LaneDetectionRuntime.now(), state: legacy?.state ?? "paused", legacyAllowed: legacyLanesAllowed),
                      let source, frame.sessionID == source.captureSessionID, frame.rotation == source.rotationDegrees,
                      frame.sourceWidth == source.rawWidth, frame.sourceHeight == source.rawHeight else { return nil }
                return frame
            }
            let runnable = lanesEnabled && visible && active && !thermalPaused
            if !runnable { resetLegacyPresentation() }
            let legacyBoundaries: [LaneBoundary]
            if runnable, validPath?.boundaries.isEmpty != false, let source, let legacyFrame {
                legacyBoundaries = matureLegacyBoundaries(legacyFrame, source: source, calibrationRevision: compatibleProfile?.revision)
            } else { legacyBoundaries = [] }
            let count = validPath?.boundaries.isEmpty == false ? validPath!.boundaries.count : legacyBoundaries.count
            let rawDecision = LanePreviewPresentationPolicy.decide(enabled: lanesEnabled, visible: visible,
                active: active, thermalPaused: thermalPaused, previewRotation: rotation, source: source,
                calibration: profile, matureBoundaryCount: count, contextAvailable: contextAvailableProvider?() ?? false,
                staleObservedBoundary: pathAge.map { $0 >= 0.75 || $0 < 0 } ?? false, nowUptime: now)
            let decision = referenceHysteresis.apply(rawDecision,
                scope:"\(source?.geometryKey ?? "none"):\(profile?.revision ?? "none")", now:ProcessInfo.processInfo.systemUptime)
            onLanePresentation?(LanePreviewPresentationDiagnostic(decision: decision, source: source,
                calibration: profile, matureBoundaryCount: count))
            switch decision.mode {
            case .hidden:
                guard lanesEnabled && visible else { return }
                let paused = decision.reason == "thermal_paused" || decision.reason == "activity_paused"
                laneStatus.text = "  " + NSLocalizedString(paused ? "drive_recorder.lanes.paused" : "drive_recorder.lanes.unavailable", comment: "") + "  "
            case .calibrationReference:
                guard let source else { return }
                let lines = UIBezierPath()
                for guide in decision.referenceLines {
                    guard guide.count == 2 else { continue }
                    let first = LaneOverlayPolicy.capturePoint(guide[0], rotation: source.rotationDegrees)
                    let second = LaneOverlayPolicy.capturePoint(guide[1], rotation: source.rotationDegrees)
                    lines.move(to: videoPreviewLayer.layerPointConverted(fromCaptureDevicePoint: first))
                    lines.addLine(to: videoPreviewLayer.layerPointConverted(fromCaptureDevicePoint: second))
                }
                // A distinct layer guarantees no observed-point dots, fill or horizon can leak into the reference.
                calibrationReferenceLines.path = lines.cgPath
                calibrationReferenceLines.opacity = Float(decision.referenceOpacity)
                laneStatus.text = "  " + NSLocalizedString("drive_recorder.lanes.reference", comment: "") + "  "
            case .observed:
                let lines = UIBezierPath()
                if let path = validPath, !path.boundaries.isEmpty {
                    for boundary in path.boundaries {
                        // Paint support is separate from the fitted model: never bridge a dashed gap.
                        let segments = boundary.observedSegments.isEmpty ? [boundary.points] : boundary.observedSegments
                        for segment in segments where segment.count >= 2 {
                            appendSmoothBoundary(segment, to: lines) { p in
                                videoPreviewLayer.layerPointConverted(fromCaptureDevicePoint: LaneOverlayPolicy.capturePoint(p, rotation: path.rotationDegrees))
                            }
                        }
                    }
                    let age = max(0, utc - path.capturedAtSeconds)
                    showLaneCurves(lines: lines, opacity: Float(age <= 0.6 ? 1 : (0.75-age)/0.15))
                } else if let frame = legacyFrame {
                    for boundary in legacyBoundaries {
                        appendSmoothBoundary(boundary.points, to: lines) {
                            videoPreviewLayer.layerPointConverted(fromCaptureDevicePoint: frame.capturePoint($0))
                        }
                    }
                    showLaneCurves(lines: lines,
                        opacity: Float(LaneOverlayPolicy.opacity(capturedAt: frame.estimate.timestampSeconds, now: LaneDetectionRuntime.now())))
                    // The legacy corridor fill is eligible only when both current edges matured.
                    if legacyBoundaries.count == 2, let first = frame.estimate.corridorPoints.first {
                        let fill = UIBezierPath()
                        func converted(_ p: LanePoint) -> CGPoint {
                            videoPreviewLayer.layerPointConverted(fromCaptureDevicePoint: frame.capturePoint(p))
                        }
                        fill.move(to: converted(first))
                        frame.estimate.corridorPoints.dropFirst().forEach { fill.addLine(to: converted($0)) }
                        fill.close()
                        laneFill.fillColor = LanePreviewStyle.color.withAlphaComponent(0.10).cgColor
                        laneFill.opacity = Float(LaneOverlayPolicy.opacity(capturedAt: frame.estimate.timestampSeconds,
                            now: LaneDetectionRuntime.now()) * (legacyBoundaries.map(\.confidence).min() ?? 0))
                        laneFill.path = fill.cgPath
                    }
                }
                laneStatus.text = "  " + String(format: NSLocalizedString("drive_recorder.lanes.status", comment: ""),
                    NSLocalizedString("drive_recorder.lanes.experimental", comment: "")) + " (\(count))  "
            }
            laneStatus.isHidden = false
            laneStatus.sizeToFit(); laneStatus.frame.origin = CGPoint(x: 12, y: max(42, bounds.height - 65))
            accessibilityValue = laneStatus.text
        }

        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var videoPreviewLayer: AVCaptureVideoPreviewLayer {
            guard let layer = layer as? AVCaptureVideoPreviewLayer else {
                fatalError("Expected AVCaptureVideoPreviewLayer")
            }
            return layer
        }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            updateVideoRotation()
            updateLaneActivity()
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            updateVideoRotation()
            drawLanes()
        }

        func updateVideoRotation() {
            guard let connection = videoPreviewLayer.connection else { return }
            let angle = orientation.captureRotationAngle
            guard connection.isVideoRotationAngleSupported(angle) else { return }
            if connection.videoRotationAngle != angle {
                connection.videoRotationAngle = angle
            }
            updateLaneActivity()
        }
    }
}

typealias PanoramaxCameraPreview = DriveCameraPreview

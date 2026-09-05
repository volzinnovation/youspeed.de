@preconcurrency import AVFoundation
import CoreLocation
import Foundation
import ImageIO
import OSLog
import SwiftUI
import UIKit

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
    case standaloneTrafficSignRecognition
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
        if purpose == .standaloneTrafficSignRecognition {
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

    static func canProcessPanoramaxUploads(for state: DriveRecorderState) -> Bool {
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

/// A traffic-sign recognizer attaches here without owning or reconfiguring the
/// platform camera session. Work must finish quickly because the dispatcher
/// drops stale frames instead of building an inference backlog.
protocol DriveVideoFrameConsumer: AnyObject {
    func consumeVideoFrame(_ sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation)
}

private final class DriveVideoFrameDispatcher: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private let lock = NSLock()
    private weak var consumer: (any DriveVideoFrameConsumer)?
    private var enabled = false

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

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        lock.lock()
        let activeConsumer = enabled ? consumer : nil
        lock.unlock()
        activeConsumer?.consumeVideoFrame(sampleBuffer, orientation: .right)
    }
}

/// The single rear-camera owner for a recorded drive.
///
/// One configured session fans out to four independent consumers: encoded
/// Dashcam video, latest-frame TSR analysis, cadence-driven full-resolution
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
    @Published private(set) var lastCaptureAt: Date?
    @Published private(set) var lastCaptureDetail = "Noch keine Aufnahme"
    @Published private(set) var lastAccuracyMeters: Double?

    var onChange: (() -> Void)?
    var onTrafficSignAnnotation: ((String) -> Void)?

    private let queueStore: PanoramaxQueueStore?
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
    private var pendingSample: PanoramaxLocationSample?
    private var pendingPhotoUniqueID: Int64?
    private var photoInFlight = false
    private var movieOutputAvailable = false
    private var photoOutputAvailable = false
    private var videoOutputAvailable = false
    private var generation = 0
    private var activeDashcamEnabled = false
    private var activePanoramaxEnabled = false
    private var activeTSREnabled = false
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

    var isDashcamModuleActive: Bool { activeDashcamEnabled }
    var isPanoramaxModuleActive: Bool { activePanoramaxEnabled }
    var isTrafficSignRecognitionModuleActive: Bool { activeTSREnabled }
    var isStandaloneTrafficSignRecognitionSession: Bool {
        sessionPurpose == .standaloneTrafficSignRecognition
    }
    var activeCaptureSessionID: String? { captureSessionID }
    var hasTrafficSignRecognitionConsumer: Bool { frameDispatcher.hasConsumer }
    var isDashcamOutputAvailable: Bool { movieOutputAvailable }
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
        notificationTokens.forEach(NotificationCenter.default.removeObserver)
    }

    func setVideoFrameConsumer(_ consumer: (any DriveVideoFrameConsumer)?) {
        frameDispatcher.setConsumer(consumer)
        guard consumer == nil, activeTSREnabled else {
            notifyChange()
            return
        }
        frameDispatcher.setEnabled(false)
        activeTSREnabled = false
        sessionQueue.async { [weak self] in
            self?.videoOutput.connection(with: .video)?.isEnabled = false
        }
        lastCaptureDetail = "Verkehrszeichenmodell nicht mehr verfuegbar"
        if DriveRecorderPolicy.shouldStopAfterTrafficSignRuntimeLoss(
            for: state,
            dashcamActive: activeDashcamEnabled || dashcamTransitionInFlight,
            panoramaxActive: activePanoramaxEnabled
        ) {
            beginStopping(resultState: .unavailable, detail: lastCaptureDetail)
            return
        }
        notifyChange()
    }

    /// Retains the newest confirmed result for the next still and, when there
    /// is no still in flight, also tries the most recent picture from this drive.
    func recordTrafficSignRecognition(_ emission: TrafficSignRuntimeEmission) {
        guard let draft = PanoramaxTrafficSignAnnotationDraft(emission: emission),
              let captureSessionID,
              emission.captureSessionId == captureSessionID else { return }
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
        purpose: DriveCaptureSessionPurpose = .driveRecording
    ) {
        guard state != .preparing, state != .recording, state != .stopping else {
            return
        }

        let tsrEnabled = trafficSignRecognitionEnabled && frameDispatcher.hasConsumer
        guard dashcamEnabled || panoramaxEnabled || trafficSignRecognitionEnabled else {
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
        activePanoramaxEnabled = panoramaxEnabled
        activeTSREnabled = tsrEnabled
        notifyChange()

        Task { @MainActor [weak self] in
            guard let self else { return }
            guard await AVCaptureDevice.requestAccess(for: .video) else {
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
                    trafficSignRecognitionEnabled: trafficSignRecognitionEnabled,
                    panoramaxEnabled: activePanoramaxEnabled
                )
                activeDashcamEnabled = activeDashcamEnabled && movieOutputAvailable
                activeTSREnabled = trafficSignRecognitionEnabled
                    && frameDispatcher.hasConsumer
                    && videoOutputAvailable
                activePanoramaxEnabled = activePanoramaxEnabled && photoOutputAvailable
                if activePanoramaxEnabled {
                    preparePanoramaxBatch(captureSessionID: captureSessionID)
                }
                if activeDashcamEnabled {
                    dashcamFileURL = try Self.makeDashcamFileURL(captureSessionID: captureSessionID)
                }
                guard activeDashcamEnabled || activeTSREnabled || activePanoramaxEnabled else {
                    throw RecorderError.noEnabledModuleAvailable
                }
            } catch let error as RecorderError {
                closePanoramaxBatchForReview()
                resetActiveModulesAfterFailure()
                state = error.isAvailabilityFailure ? .unavailable : .failed
                lastCaptureDetail = error == .noEnabledModuleAvailable
                    ? "Kein aktiviertes Kameramodul ist verfuegbar"
                    : "Kamera konnte nicht gestartet werden"
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
            let trafficSignFramesEnabled = activeTSREnabled
            frameDispatcher.setEnabled(activeTSREnabled)
            scheduleStartTimeout(generation: requestedGeneration)
            sessionQueue.async { [weak self] in
                guard let self else { return }
                self.videoOutput.connection(with: .video)?.isEnabled = trafficSignFramesEnabled
                self.session.startRunning()
                if let movieURL {
                    self.configureMovieCodecIfPossible()
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
                let fileURL = try Self.makeDashcamFileURL(captureSessionID: captureSessionID)
                let token = UUID()
                dashcamFileURL = fileURL
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
                    self.configureMovieCodecIfPossible()
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
            sessionQueue.async { [weak self] in
                self?.videoOutput.connection(with: .video)?.isEnabled = false
            }
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
        frameDispatcher.setEnabled(false)
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

    func ingest(location: CLLocation) {
        guard state == .recording,
              activePanoramaxEnabled,
              !photoInFlight,
              batch != nil else {
            return
        }
        let accuracy = location.horizontalAccuracy
        let requestedAt = Date()
        guard accuracy >= 0,
              accuracy.isFinite,
              requestedAt.timeIntervalSince(location.timestamp) <= cadenceConfiguration.maxLocationAge else {
            return
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
        guard PanoramaxCapturePolicy.shouldCapture(
            lastCapture: lastCaptureSample,
            current: sample,
            now: requestedAt,
            configuration: cadenceConfiguration
        ) else {
            notifyChange()
            return
        }

        pendingSample = sample
        photoInFlight = true
        let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
        let maximumDimensions = photoOutput.maxPhotoDimensions
        if maximumDimensions.width > 0, maximumDimensions.height > 0 {
            settings.maxPhotoDimensions = maximumDimensions
        }
        pendingPhotoUniqueID = settings.uniqueID
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
    }

    private func preparePanoramaxBatch(captureSessionID: String) {
        guard let queueStore else {
            activePanoramaxEnabled = false
            lastCaptureDetail = "Panoramax-Speicher nicht verfuegbar"
            return
        }
        do {
            batch = try queueStore.createBatch(captureSessionID: captureSessionID)
        } catch {
            activePanoramaxEnabled = false
            batch = nil
            lastCaptureDetail = "Panoramax-Batch konnte nicht erstellt werden"
        }
    }

    private func closePanoramaxBatchForReview() {
        if let batch {
            _ = try? queueStore?.transitionBatch(batch.batchID, to: .awaitingReview)
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

        // Keep the graph fixed while the session is running. Attach selected
        // consumers before dormant switchable outputs so a dormant Dashcam or
        // TSR reservation can never displace a module the user actually chose.
        if dashcamEnabled { addMovieOutputIfPossible() }
        if trafficSignRecognitionEnabled { addVideoOutputIfPossible() }
        if panoramaxEnabled { addPhotoOutputIfPossible() }
        addMovieOutputIfPossible()
        addVideoOutputIfPossible()
        videoOutput.connection(with: .video)?.isEnabled = trafficSignRecognitionEnabled
            && frameDispatcher.hasConsumer
        guard movieOutputAvailable || videoOutputAvailable || photoOutputAvailable else {
            throw RecorderError.sessionUnavailable
        }
    }

    nonisolated private func configureMovieCodecIfPossible() {
        guard let connection = movieOutput.connection(with: .video) else { return }
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
            if state == .recording {
                lastCaptureDetail = error == nil ? "Aufnahme verworfen" : "Aufnahme fehlgeschlagen"
            }
            notifyChange()
            return
        }
        let storageLimit = storageLimitBytes
        let annotationDraft = latestTrafficSignAnnotationDraft
        latestTrafficSignAnnotationDraft = nil
        photoProcessingQueue.async { [weak self] in
            let result = Self.persistPanoramaxPhoto(
                data: data,
                sample: sample,
                batch: batch,
                queueStore: queueStore,
                storageLimitBytes: storageLimit,
                annotationDraft: annotationDraft
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
            notifyChange()
        }
        guard state == .recording else { return }
        lastCaptureDetail = result.detail
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
        activeDashcamEnabled = false
        activeDashcamRecordingURL = nil
        dashcamFileURL = nil
        clearDashcamTransition()
        lastCaptureDetail = detail
        if state == .recording, !activePanoramaxEnabled, !activeTSREnabled {
            beginStopping(resultState: .failed, detail: detail)
        } else {
            notifyChange()
        }
    }

    private func finishDashcamDisableWithoutCallback(token: UUID) {
        guard dashcamTransition?.token == token else { return }
        activeDashcamEnabled = false
        activeDashcamRecordingURL = nil
        clearDashcamTransition()
        lastCaptureDetail = "Dashcam-Aufnahme beendet"
        if state == .recording, !activePanoramaxEnabled, !activeTSREnabled {
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
                beginStopping(
                    resultState: .failed,
                    detail: "Dashcam konnte nicht sicher beendet werden"
                )
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
        activeDashcamEnabled = false
        activePanoramaxEnabled = false
        activeTSREnabled = false
        activeDashcamRecordingURL = nil
        clearDashcamTransition()
        captureSessionID = nil
        frameDispatcher.setEnabled(false)
    }

    nonisolated private static func persistPanoramaxPhoto(
        data: Data,
        sample: PanoramaxLocationSample,
        batch: PanoramaxBatchRecord,
        queueStore: PanoramaxQueueStore,
        storageLimitBytes: Int64?,
        annotationDraft: PanoramaxTrafficSignAnnotationDraft?
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
            trafficSignAnnotations: annotations.isEmpty ? nil : annotations
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
        guard activeDashcamEnabled || activePanoramaxEnabled || activeTSREnabled else {
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

    private func handleMovieFinished(
        url: URL,
        successful: Bool,
        errorSummary: String?
    ) {
        if let errorSummary {
            Self.logger.error(
                "movie output finished file=\(url.lastPathComponent, privacy: .public) successful=\(successful, privacy: .public) error=\(errorSummary, privacy: .public)"
            )
        }
        guard dashcamFileURL?.standardizedFileURL == url.standardizedFileURL else {
            if successful {
                Self.protectRecordedFile(at: url)
                Self.enforceDashcamStorageLimit(retaining: url)
            } else {
                try? FileManager.default.removeItem(at: url)
            }
            return
        }
        if successful {
            dashcamFileURL = url
            Self.protectRecordedFile(at: url)
            Self.enforceDashcamStorageLimit(retaining: url)
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
        if state == .stopping {
            finishStoppingAfterSessionQueue(generation: generation)
        } else if state == .preparing {
            activeDashcamEnabled = false
            beginStopping(resultState: .failed, detail: "Dashcam-Aufnahme konnte nicht gestartet werden")
        } else if state == .recording {
            activeDashcamEnabled = false
            if activePanoramaxEnabled || activeTSREnabled {
                if wasLiveToggle, successful {
                    lastCaptureDetail = "Dashcam-Aufnahme gespeichert; andere Kameramodule laufen weiter"
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

    private static func makeDashcamFileURL(captureSessionID: String) throws -> URL {
        try dashcamDirectory().appendingPathComponent(
            "drive-\(captureSessionID)-\(UUID().uuidString).mov"
        )
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
        onChange?()
    }

    private enum RecorderError: Error, Equatable {
        case cameraUnavailable
        case sessionUnavailable
        case noEnabledModuleAvailable

        var isAvailabilityFailure: Bool {
            self == .cameraUnavailable || self == .sessionUnavailable || self == .noEnabledModuleAvailable
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

struct DriveCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.videoPreviewLayer.session = session
        view.videoPreviewLayer.videoGravity = .resizeAspectFill
        view.updateVideoRotation()
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        if uiView.videoPreviewLayer.session !== session {
            uiView.videoPreviewLayer.session = session
        }
        uiView.updateVideoRotation()
    }

    static func dismantleUIView(_ uiView: PreviewView, coordinator: Void) {
        uiView.videoPreviewLayer.session = nil
    }

    final class PreviewView: UIView {
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
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            updateVideoRotation()
        }

        func updateVideoRotation() {
            guard let orientation = window?.windowScene?.interfaceOrientation,
                  let connection = videoPreviewLayer.connection else { return }
            let angle: CGFloat
            switch orientation {
            case .portrait:
                angle = 90
            case .portraitUpsideDown:
                angle = 270
            case .landscapeLeft:
                angle = 180
            case .landscapeRight:
                angle = 0
            default:
                return
            }
            guard connection.isVideoRotationAngleSupported(angle) else { return }
            guard connection.videoRotationAngle != angle else { return }
            connection.videoRotationAngle = angle
        }
    }
}

typealias PanoramaxCameraPreview = DriveCameraPreview

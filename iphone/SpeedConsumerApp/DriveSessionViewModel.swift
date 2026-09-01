import CoreLocation
import AVFoundation
import Foundation
import OSLog
import Speech
import UIKit

struct TunnelModeTracker {
    enum State: String, Equatable {
        case inactive
        case active
    }

    private(set) var state: State = .inactive

    mutating func reset() {
        state = .inactive
    }

    mutating func consumeFix(isTunnelSegment: Bool) {
        state = isTunnelSegment ? .active : .inactive
    }

    var isTunnelModeActive: Bool {
        state != .inactive
    }
}

private final class ConfirmationTonePlayer {
    private static let sampleRate: Double = 44_100
    private static let frequencyHz: Double = 432
    private static let durationSeconds: Double = 0.18
    private static let amplitude: Float = 0.30

    private let toneBuffer: AVAudioPCMBuffer?
    private var engine: AVAudioEngine?
    private var playerNode: AVAudioPlayerNode?

    init() {
        toneBuffer = Self.makeToneBuffer()
    }

    func play() {
        guard let toneBuffer else {
            return
        }
        stop()

        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.ambient, mode: .default, options: [.duckOthers])
        try? session.setActive(true)

        let engine = AVAudioEngine()
        let playerNode = AVAudioPlayerNode()
        engine.attach(playerNode)
        engine.connect(playerNode, to: engine.mainMixerNode, format: toneBuffer.format)
        playerNode.scheduleBuffer(toneBuffer, at: nil, options: [.interrupts]) { [weak self] in
            DispatchQueue.main.async {
                self?.stopAndDeactivate()
            }
        }

        do {
            try engine.start()
        } catch {
            stopAndDeactivate()
            return
        }

        self.engine = engine
        self.playerNode = playerNode
        playerNode.play()
    }

    private func stopAndDeactivate() {
        stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func stop() {
        playerNode?.stop()
        engine?.stop()
        playerNode = nil
        engine = nil
    }

    private static func makeToneBuffer() -> AVAudioPCMBuffer? {
        let frameCount = Int(sampleRate * durationSeconds)
        guard frameCount > 0,
              let format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frameCount)),
              let channel = buffer.floatChannelData?.pointee else {
            return nil
        }

        let attackFrames = max(1, Int(sampleRate * 0.012))
        let releaseFrames = max(1, Int(sampleRate * 0.04))
        for frame in 0..<frameCount {
            let t = Double(frame) / sampleRate
            let wave = sin(2.0 * Double.pi * frequencyHz * t)
            let attack = min(1.0, Double(frame) / Double(attackFrames))
            let release = min(1.0, Double(frameCount - frame) / Double(releaseFrames))
            let envelope = Float(min(attack, release))
            channel[frame] = Float(wave) * amplitude * envelope
        }
        buffer.frameLength = AVAudioFrameCount(frameCount)
        return buffer
    }
}

enum AppScreenshotState: String {
    case warnLevel0 = "warn-level-0"
    case warnLevel1 = "warn-level-1"
    case warnLevel2 = "warn-level-2"
    case warnLevel3 = "warn-level-3"
    case pedestrianZone = "pedestrian-zone"
    case autobahnUnlimitedAbove130 = "autobahn-unlimited-above-130"

    struct Fixture {
        let currentSpeedKmh: Double
        let speedLimitKmh: Int?
        let speedLimitDisplayText: String?
        let isUnlimitedSpeedLimitActive: Bool
        let streetName: String
        let cityName: String
        let wayID: String
        let insideCity: Bool
        let latitude: Double
        let longitude: Double
        let gpsHorizontalAccuracyM: Double
        let gpsSignalBars: Int
    }

    static func current(processInfo: ProcessInfo = .processInfo) -> AppScreenshotState? {
        let raw = processInfo.environment["YOUSPEED_SCREENSHOT_STATE"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard let raw, !raw.isEmpty else {
            return nil
        }
        return AppScreenshotState(rawValue: raw)
    }

    var fixture: Fixture {
        switch self {
        case .warnLevel0:
            return Fixture(
                currentSpeedKmh: 47,
                speedLimitKmh: 50,
                speedLimitDisplayText: nil,
                isUnlimitedSpeedLimitActive: false,
                streetName: "Durlacher Allee",
                cityName: "Karlsruhe",
                wayID: "karlsruhe-warn-0",
                insideCity: true,
                latitude: 49.0102,
                longitude: 8.4266,
                gpsHorizontalAccuracyM: 6,
                gpsSignalBars: 4
            )
        case .warnLevel1:
            return Fixture(
                currentSpeedKmh: 67,
                speedLimitKmh: 50,
                speedLimitDisplayText: nil,
                isUnlimitedSpeedLimitActive: false,
                streetName: "Durlacher Allee",
                cityName: "Karlsruhe",
                wayID: "karlsruhe-warn-1",
                insideCity: true,
                latitude: 49.0102,
                longitude: 8.4266,
                gpsHorizontalAccuracyM: 6,
                gpsSignalBars: 4
            )
        case .warnLevel2:
            return Fixture(
                currentSpeedKmh: 73,
                speedLimitKmh: 50,
                speedLimitDisplayText: nil,
                isUnlimitedSpeedLimitActive: false,
                streetName: "Durlacher Allee",
                cityName: "Karlsruhe",
                wayID: "karlsruhe-warn-2",
                insideCity: true,
                latitude: 49.0102,
                longitude: 8.4266,
                gpsHorizontalAccuracyM: 6,
                gpsSignalBars: 4
            )
        case .warnLevel3:
            return Fixture(
                currentSpeedKmh: 86,
                speedLimitKmh: 50,
                speedLimitDisplayText: nil,
                isUnlimitedSpeedLimitActive: false,
                streetName: "Durlacher Allee",
                cityName: "Karlsruhe",
                wayID: "karlsruhe-warn-3",
                insideCity: true,
                latitude: 49.0102,
                longitude: 8.4266,
                gpsHorizontalAccuracyM: 6,
                gpsSignalBars: 4
            )
        case .pedestrianZone:
            return Fixture(
                currentSpeedKmh: 5,
                speedLimitKmh: nil,
                speedLimitDisplayText: "Schritt",
                isUnlimitedSpeedLimitActive: false,
                streetName: "Im Kloster",
                cityName: "Bad Herrenalb",
                wayID: "bad-herrenalb-pedestrian-zone",
                insideCity: true,
                latitude: 48.7966,
                longitude: 8.4361,
                gpsHorizontalAccuracyM: 5,
                gpsSignalBars: 4
            )
        case .autobahnUnlimitedAbove130:
            return Fixture(
                currentSpeedKmh: 142,
                speedLimitKmh: nil,
                speedLimitDisplayText: nil,
                isUnlimitedSpeedLimitActive: true,
                streetName: "A 5",
                cityName: "Karlsruhe",
                wayID: "autobahn-unlimited-130-plus",
                insideCity: false,
                latitude: 49.0180,
                longitude: 8.3501,
                gpsHorizontalAccuracyM: 5,
                gpsSignalBars: 4
            )
        }
    }
}

enum MatcherDebugProfile: String, CaseIterable, Identifiable {
    case m1
    case m2
    case m3
    case m4
    case m5
    case m6
    case m7
    case m8
    case m9
    case m10
    case m11
    case m12

    var id: String { rawValue }

    var shortLabel: String {
        switch self {
        case .m1: return "M1"
        case .m2: return "M2"
        case .m3: return "M3"
        case .m4: return "M4"
        case .m5: return "M5"
        case .m6: return "M6"
        case .m7: return "M7"
        case .m8: return "M8"
        case .m9: return "M9"
        case .m10: return "M10"
        case .m11: return "M11"
        case .m12: return "M12"
        }
    }

    var displayName: String {
        switch self {
        case .m1: return "Connected baseline"
        case .m2: return "Nearest + street-ref continuity"
        case .m3: return "M2 + connected-candidate gate"
        case .m4: return "Corridor raw mini-HMM"
        case .m5: return "Corridor-aware final"
        case .m6: return "M2 + urban consecutive distance-gap release"
        case .m7: return "M6 + 10m search window"
        case .m8: return "M6 + no-ref street-name continuity"
        case .m9: return "M8 + guarded stale-ref suppression"
        case .m10: return "M9 + node-direction-aware junction release"
        case .m11: return "M10 + topology-only particle sequence"
        case .m12: return "M11 + 10-fix HMM/Viterbi"
        }
    }

    var debugLabel: String { "\(shortLabel) \(displayName)" }

    var matchingModel: V3SpeedLimitService.MatchingModel {
        switch self {
        case .m1: return .connectedBaseline
        case .m2: return .simpleSpeedRefHeuristic
        case .m3: return .simpleSpeedRefConnectedHeuristic
        case .m4: return .corridorHMMRawMiniHMM
        case .m5: return .corridorHMM
        case .m6: return .simpleSpeedRefUrbanReleaseHeuristic
        case .m7: return .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic
        case .m8: return .simpleSpeedRefStreetNameFallbackHeuristic
        case .m9: return .simpleSpeedRefStreetNameGuardHeuristic
        case .m10: return .simpleSpeedRefStreetNameGuardNodeAwareHeuristic
        case .m11: return .simpleSequenceParticleHeuristic
        case .m12: return .simpleSequenceViterbiHeuristic
        }
    }

    static let defaultProfile: MatcherDebugProfile = .m2
    static let forcedProfileVersion: Int = 7

    static func resolveInitialProfile(storedRawValue: String?, forcedVersion: Int) -> MatcherDebugProfile {
        if forcedVersion < forcedProfileVersion {
            return defaultProfile
        }
        guard let storedRawValue else {
            return defaultProfile
        }
        return MatcherDebugProfile(rawValue: storedRawValue) ?? defaultProfile
    }
}

@MainActor
final class DriveSessionViewModel: NSObject, ObservableObject {
    private nonisolated static let logger = Logger(subsystem: "de.youspeed.SpeedConsumer", category: "session")
    enum SpeedCaptureMode: Equatable {
        case idle
        case speakingPrompt
        case listening
        case evaluating
        case saving
    }

    enum StartupDataState: String {
        case loading
        case ready
        case failed
    }

    struct BundleDownloadOption: Identifiable, Hashable {
        let id: String
        let countryCode: String
        let countryName: String
        let displayName: String
        let endpoint: V3ManifestEndpoint
    }

    struct BundleDownloadCountrySection: Identifiable, Hashable {
        let id: String
        let countryCode: String
        let countryName: String
        let options: [BundleDownloadOption]
    }

    @Published var syncStatus: String = "not_synced"
    @Published var syncProgressStage: String = "idle"
    @Published var syncProgressDetail: String = ""
    @Published var syncProgressCompletedBytes: Int64 = 0
    @Published var syncProgressTotalBytes: Int64 = 0
    @Published var syncProgressBytesPerSecond: Double = 0
    @Published var syncProgressETASeconds: Double?
    @Published var syncPartDownloads: [PartDownloadProgress] = []
    @Published var maintenanceMessage: String = ""
    @Published var driveStatus: String = "stopped"
    @Published var activeBundleVersion: String = "none"
    @Published var activeDBPath: String = ""
    @Published var currentSpeedKmh: Double = 0
    @Published var speedLimitKmh: Int?
    @Published var speedLimitDisplayText: String?
    @Published var limitWayID: String?
    @Published var limitStreetName: String?
    @Published var limitCityName: String?
    @Published var limitCityPlaceName: String?
    @Published var limitCityDistrictName: String?
    @Published var lastError: String = ""
    @Published var currentLatitude: Double?
    @Published var currentLongitude: Double?
    @Published var gpsHorizontalAccuracyM: Double?
    @Published var gpsSignalBars: Int = 0
    @Published var lookupMaxCandidates: Int = 512
    @Published var lastLookupStatus: String = "idle"
    @Published var lastLookupQueryMs: Double = 0
    @Published var lastLookupCandidateCount: Int = 0
    @Published var lastLookupSpeedCandidateCount: Int = 0
    @Published var lastLookupNearestCandidateM: Double?
    @Published var lastLookupNearestSpeedCandidateM: Double?
    @Published var lastLookupInsideCity: Bool?
    @Published var lastLookupCitySource: String = "n/a"
    @Published var lastLookupCityResolveMs: Double = 0
    @Published var lastLookupCityCandidateBoundaries: Int = 0
    @Published var lastLookupCityContainingBoundaries: Int = 0
    @Published var lastLookupCityPlaceCandidates: Int = 0
    @Published var lookupEventLog: [String] = []
    @Published var gpsFixCount: Int = 0
    @Published var gpsLogPath: String = ""
    @Published var matchLogPath: String = ""
    @Published var lastCandidateTraces: [MatchCandidateTrace] = []
    @Published var lastSelectionTrace: [MatchSelectionTrace] = []
    @Published var startupDataState: StartupDataState = .loading
    @Published var startupProgress: Double = 0
    @Published var startupDetail: String = "Lokale Daten werden vorbereitet"
    @Published var observationDraftVoiceCommand: String = ""
    @Published var localObservations: [LocalObservation] = []
    @Published var localObservationStreetNames: [String: String] = [:]
    @Published var localObservationStatus: String = ""
    @Published var lastExportDirectoryPath: String = ""
    @Published var localObservationShareURL: URL?
    @Published private(set) var bundleDownloadSections: [BundleDownloadCountrySection] = []
    @Published private(set) var downloadedBundleCountByRegion: [String: Int] = [:]
    @Published private(set) var downloadedBundleLatestVersionByRegion: [String: String] = [:]
    @Published private(set) var expectedBundleBytesByRegion: [String: Int64] = [:]
    @Published private(set) var activeDownloadOptionID: String?
    @Published var dashcamRecordingEnabled: Bool {
        didSet {
            guard dashcamRecordingEnabled != oldValue else { return }
            UserDefaults.standard.set(dashcamRecordingEnabled, forKey: Self.dashcamRecordingEnabledDefaultsKey)
        }
    }
    @Published var trafficSignRecognitionEnabled: Bool {
        didSet {
            guard trafficSignRecognitionEnabled != oldValue else { return }
            UserDefaults.standard.set(trafficSignRecognitionEnabled, forKey: Self.trafficSignRecognitionEnabledDefaultsKey)
            trafficSignRecognitionState = trafficSignRecognitionEnabled ? .unavailable : .disabled
        }
    }
    @Published var panoramaxCaptureEnabled: Bool {
        didSet {
            guard panoramaxCaptureEnabled != oldValue else { return }
            UserDefaults.standard.set(panoramaxCaptureEnabled, forKey: Self.panoramaxCaptureEnabledDefaultsKey)
        }
    }
    @Published private(set) var driveRecorderState: DriveRecorderState = .disabled
    @Published private(set) var driveRecorderStartedAt: Date?
    @Published private(set) var dashcamFileURL: URL?
    @Published private(set) var dashcamRecordings: [DashcamRecording] = []
    @Published private(set) var driveRecorderDashcamActive = false
    @Published private(set) var driveRecorderDashcamTransitioning = false
    @Published private(set) var driveRecorderDashcamAvailable = false
    @Published private(set) var driveRecorderTrafficSignRecognitionActive = false
    @Published private(set) var driveRecorderTrafficSignRecognitionAvailable = false
    @Published private(set) var driveRecorderPanoramaxActive = false
    @Published private(set) var trafficSignRecognitionState: TrafficSignRecognitionState = .unavailable
    @Published private(set) var trafficSignRecognitionLastEvent: TrafficSignRecognitionEvent?
    @Published private(set) var trafficSignRecognitionActiveOverride: TrafficSignTransientSpeedOverride?
    @Published private(set) var trafficSignRecognitionModelPackID: String?
    @Published private(set) var trafficSignRecognitionUnavailableDetail = "No verified traffic-sign model pack is installed."
    @Published private(set) var panoramaxCaptureState: PanoramaxRecorderState = .disabled
    @Published private(set) var panoramaxCaptureCount = 0
    @Published private(set) var panoramaxLastCaptureAt: Date?
    @Published private(set) var panoramaxLastCaptureDetail = "Noch keine Aufnahme"
    @Published private(set) var panoramaxLastAccuracyMeters: Double?
    @Published private(set) var panoramaxBatches: [PanoramaxBatchRecord] = []
    @Published private(set) var panoramaxUploadStatusByBatch: [String: String] = [:]
    @Published private(set) var panoramaxUploadProgressByBatch: [String: PanoramaxUploadProgress] = [:]
    @Published private(set) var activePanoramaxUploadBatchIDs: Set<String> = []
    @Published private(set) var panoramaxMaintenanceIssue: String?
    @Published private(set) var panoramaxQueueMaintenanceInProgress = false
    @Published var panoramaxTriggerMode: PanoramaxCaptureTriggerMode {
        didSet {
            UserDefaults.standard.set(panoramaxTriggerMode.rawValue, forKey: Self.panoramaxTriggerModeDefaultsKey)
            applyPanoramaxConfiguration()
        }
    }
    @Published var panoramaxMinimumDistanceMeters: Double {
        didSet {
            let clamped = min(max(panoramaxMinimumDistanceMeters, 3), 100)
            if clamped != panoramaxMinimumDistanceMeters { panoramaxMinimumDistanceMeters = clamped; return }
            UserDefaults.standard.set(panoramaxMinimumDistanceMeters, forKey: Self.panoramaxMinimumDistanceDefaultsKey)
            applyPanoramaxConfiguration()
        }
    }
    @Published var panoramaxMinimumIntervalSeconds: Double {
        didSet {
            let clamped = min(max(panoramaxMinimumIntervalSeconds, 1), 60)
            if clamped != panoramaxMinimumIntervalSeconds { panoramaxMinimumIntervalSeconds = clamped; return }
            UserDefaults.standard.set(panoramaxMinimumIntervalSeconds, forKey: Self.panoramaxMinimumIntervalDefaultsKey)
            applyPanoramaxConfiguration()
        }
    }
    @Published var panoramaxUnlimitedStorage: Bool {
        didSet {
            UserDefaults.standard.set(panoramaxUnlimitedStorage, forKey: Self.panoramaxUnlimitedStorageDefaultsKey)
            applyPanoramaxConfiguration()
            enforcePanoramaxStorageLimit()
        }
    }
    @Published var panoramaxStorageLimitMB: Double {
        didSet {
            let clamped = min(max(panoramaxStorageLimitMB, 100), 10_000)
            if clamped != panoramaxStorageLimitMB { panoramaxStorageLimitMB = clamped; return }
            UserDefaults.standard.set(panoramaxStorageLimitMB, forKey: Self.panoramaxStorageLimitDefaultsKey)
            applyPanoramaxConfiguration()
            enforcePanoramaxStorageLimit()
        }
    }
    @Published var panoramaxDeleteUploadedImages: Bool {
        didSet {
            UserDefaults.standard.set(
                panoramaxDeleteUploadedImages,
                forKey: Self.panoramaxDeleteUploadedImagesDefaultsKey
            )
            if panoramaxDeleteUploadedImages {
                retryCompletedPanoramaxRetention()
            }
        }
    }
    @Published private(set) var speedCaptureMode: SpeedCaptureMode = .idle
    @Published private(set) var tunnelModeState: TunnelModeTracker.State = .inactive
    @Published private(set) var isUnlimitedSpeedLimitActive: Bool = false
    @Published private(set) var appScreenshotState: AppScreenshotState?
    @Published private(set) var activePenaltyRules: SpeedPenaltyRuleSet
    @Published private(set) var activePenaltyRulesFile: String
    @Published var audioAlertThresholdKmh: Int {
        didSet {
            let clamped = min(max(audioAlertThresholdKmh, 0), 80)
            if clamped != audioAlertThresholdKmh {
                audioAlertThresholdKmh = clamped
                return
            }
            guard audioAlertThresholdKmh != oldValue else {
                return
            }
            UserDefaults.standard.set(audioAlertThresholdKmh, forKey: Self.audioAlertThresholdDefaultsKey)
        }
    }
    @Published var audioAlertsEnabled: Bool {
        didSet {
            guard audioAlertsEnabled != oldValue else {
                return
            }
            UserDefaults.standard.set(audioAlertsEnabled, forKey: Self.audioAlertsEnabledDefaultsKey)
            if !audioAlertsEnabled, speechSynthesizer.isSpeaking {
                speechSynthesizer.stopSpeaking(at: .immediate)
            }
        }
    }
    @Published var hideWelcomeScreen: Bool {
        didSet {
            guard hideWelcomeScreen != oldValue else {
                return
            }
            UserDefaults.standard.set(hideWelcomeScreen, forKey: Self.hideWelcomeScreenDefaultsKey)
        }
    }
    @Published var matcherDebugProfile: MatcherDebugProfile {
        didSet {
            guard matcherDebugProfile != oldValue else {
                return
            }
            UserDefaults.standard.set(matcherDebugProfile.rawValue, forKey: Self.matcherDebugProfileDefaultsKey)
            resetWayMatchContinuity()
            resetTunnelModeTracking()
            invalidateTrafficSignOverrideForBaseSourceMutation()
            if appScreenshotState == nil, !activeDBPath.isEmpty {
                speedLimitService = makeSpeedLimitService(dbPath: activeDBPath)
            }
        }
    }

    private let bundleManager = V3BundleManager()
    private let localObservationStore = LocalObservationStore()
    private let locationManager = CLLocationManager()
    private let speechSynthesizer = AVSpeechSynthesizer()
    private let captureConfirmationTonePlayer = ConfirmationTonePlayer()
    private let bundledTargetsConfig: V3BundleTargetsConfig?
    private let manifestEndpoints: [V3ManifestEndpoint]
    let panoramaxAccount: PanoramaxAccountModel
    private var panoramaxQueueStore: PanoramaxQueueStore?
    private var speedLimitService: V3SpeedLimitService?
    private var driveCaptureCoordinator: DriveCaptureCoordinator?
    private let trafficSignFrameState = TrafficSignAtomicFrameState()
    private var trafficSignRuntime: TrafficSignRuntime?
    private var trafficSignRuntimeLoadTask: Task<Void, Never>?
    private var trafficSignApplicationIsActive = true
    private var trafficSignRecorderGeneration: UInt64 = 0
    private var trafficSignContextGeneration: UInt64 = 0
    private var trafficSignFrameContextIsCurrent = false
    private var latestTrafficSignLookupFixID = 0
    private var panoramaxUploadTasks: [String: Task<Void, Never>] = [:]
    private var panoramaxQueueMaintenanceTask: Task<Void, Never>?
    private var panoramaxQueueMaintenanceGeneration: UInt64 = 0
    private var panoramaxBatchPublicationGeneration: UInt64 = 0
    private var panoramaxStorageLimitTask: Task<Void, Never>?
    private var panoramaxStorageLimitGeneration: UInt64 = 0
    private var isDriving = false
    private var hasPreparedGPSLogFile = false
    private var preparedMatchLogURL: URL?
    private var lastProgressUIUpdate = Date.distantPast
    private var lastLoggedSyncProgressSignature: String = ""
    private var lastDownloadProgressAt: Date?
    private var lastDownloadProgressBytes: Int64?
    private var syncBackgroundTaskID: UIBackgroundTaskIdentifier = .invalid
    private var syncTask: Task<Void, Never>?
    private var startupTask: Task<Void, Never>?
    private var lastAudioFeedbackAt = Date.distantPast
    private var lastAnnouncedSpeechText: String?
    private var wasDrivingBanWarningActive = false
    private var lastDrivingBanWarningAt = Date.distantPast
    private var recentSpeedSampleLocations: [CLLocation] = []
    private var previousMatchedWayID: String?
    private var previousMatchedHighway: String?
    private var previousMatchedEndpointProximityM: Double?
    private var previousMatchedStreetRef: String?
    private var previousMatchedStreetName: String?
    private var recentMatchedWayIDs: [String] = []
    private var recentObservedFixes: [WayMatchRecentFix] = []
    private var sameRefUrbanReleaseStreak = 0
    private var recentMatchedStreetRefs: [String] = []
    private var consecutiveNoRefMatchCount = 0
    private var recentNearbyTunnelWayIDs: [String] = []
    private var recentNearbyTunnelRefs: [String] = []
    private var recentTunnelApproachWayIDs: [String] = []
    private var recentTunnelApproachRefs: [String] = []
    private var tunnelApproachFixCount = 0
    private var tunnelApproachBaselineAccuracyM: Double?
    private var tunnelApproachBaselineSignalBars: Int?
    private var motorwayModeActive = false
    private var activeCorridorState: CorridorMatchState?
    private var approachCorridorState: CorridorMatchState?
    private var approachCorridorFixCount = 0
    private var approachCorridorStartDepthM: Double?
    private var approachCorridorStartDepthNodes: Int?
    private var recentMatchHypotheses: [WayMatchHypothesis] = []
    private var matchedFixCount = 0
    private var hadRecentGPSSignalLoss = false
    private var speedCapturePromptFallbackTask: Task<Void, Never>?
    private var speedCaptureListeningTimeoutTask: Task<Void, Never>?
    private var awaitingSpeedCapturePromptCompletion = false
    private var speedCaptureRecognizer: SFSpeechRecognizer?
    private var speedCaptureRecognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var speedCaptureRecognitionTask: SFSpeechRecognitionTask?
    private var speedCaptureAudioEngine: AVAudioEngine?
    private var speedCaptureStartListeningTask: Task<Void, Never>?
    private var speedCaptureLatestTranscript: String = ""
    private var speedCaptureDidResolve = false
    private var lastKnownSpeedLimitKmh: Int?
    private var localSpeedOverridesByWayID: [String: Int] = [:]
    private var localSpeedOverrideValuesByWayID: [String: String] = [:]
    private var localSpeedOverrideRevisionsByWayID: [String: String] = [:]
    private var activeLocalSpeedCorrection: ActiveLocalSpeedCorrection?
    private var trafficSignOverridePolicy = TrafficSignTransientOverridePolicy()
    private var currentTrafficSignSourceSignature: TrafficSignRuntimeSourceSignature?
    private var currentBundledSpeedLimitKmh: Int?
    private var currentLocalCorrectionSpeedKmh: Int?
    private var currentBaseSpeedLimitDisplayText: String?
    private var currentBundledUnlimitedSpeedLimitActive = false
    private var currentBaseUnlimitedSpeedLimitActive = false
    private var currentTrafficSignTravelDirection: TrafficSignTravelDirection = .unknown
    private var latestTrafficSignDetectionContext: TrafficSignDetectionContext?
    private var limitStreetBaseName: String?
    private var limitStreetRef: String?
    private var tunnelModeTracker = TunnelModeTracker()
    private static let audioAlertThresholdDefaultsKey = "youspeed.audio_alert_threshold_kmh"
    private static let audioAlertsEnabledDefaultsKey = "youspeed.audio_alerts_enabled"
    private static let hideWelcomeScreenDefaultsKey = "youspeed.hide_welcome_screen"
    private static let dashcamRecordingEnabledDefaultsKey = "youspeed.drive_recorder.dashcam_enabled"
    private static let trafficSignRecognitionEnabledDefaultsKey = "youspeed.drive_recorder.tsr_enabled"
    // The legacy key represented whether the old Panoramax-only recorder was
    // running and was written back to false whenever recording stopped. It is
    // not a valid module preference. A new key prevents that stopped state from
    // disabling every consumer after migration to the shared Drive Recorder.
    private static let panoramaxCaptureEnabledDefaultsKey = "youspeed.drive_recorder.panoramax_enabled"
    private static let panoramaxTriggerModeDefaultsKey = "youspeed.panoramax_trigger_mode"
    private static let panoramaxMinimumDistanceDefaultsKey = "youspeed.panoramax_minimum_distance_m"
    private static let panoramaxMinimumIntervalDefaultsKey = "youspeed.panoramax_minimum_interval_s"
    private static let panoramaxUnlimitedStorageDefaultsKey = "youspeed.panoramax_unlimited_storage"
    private static let panoramaxStorageLimitDefaultsKey = "youspeed.panoramax_storage_limit_mb"
    private static let panoramaxDeleteUploadedImagesDefaultsKey = "youspeed.panoramax_delete_uploaded_images"
    private static let matcherDebugProfileDefaultsKey = "youspeed.matcher_debug_profile"
    private static let matcherDebugProfileForcedVersionDefaultsKey = "youspeed.matcher_debug_profile_forced_version"
    private static let defaultAudioAlertThresholdKmh = 8
    private static let defaultAudioAlertsEnabled = true
    private static let defaultHideWelcomeScreen = false
    private static let defaultTrafficSignCountryCode = "DE"
    private static let drivingBanWarningReminderInterval: TimeInterval = 24
    private static let fallbackLookupRadiusM: Double = 50.0
    private static let minLookupRadiusM: Double = 50.0
    private static let maxLookupRadiusM: Double = 160.0
    private static let lookupRadiusAccuracyMultiplier: Double = 2.2
    private static let startupSeedActivationFloorProgress: Double = 0.92
    private static let recentMatchedWayHistoryLimit = 5
    private static let recentMatchedFixHistoryLimit = 10
    private static let recentMatchedStreetRefHistoryLimit = 6
    private static let derivedSpeedComputationMinWindowSeconds: TimeInterval = 2.0
    private static let derivedSpeedComputationMaxWindowSeconds: TimeInterval = 4.5
    nonisolated private static let lowSpeedDerivedFallbackThresholdKmh: Double = 7.0
    private static let speedCaptureSpeechLocaleIdentifier = "de-DE"
    private static let speedCaptureListeningWindowSeconds: UInt64 = 4
    private static let speedCaptureTimeoutPaddingNanos: UInt64 = 350_000_000
    private static let speedCaptureStartDelayNanos: UInt64 = 300_000_000
    private static let gpsLogCSVHeader = "fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m,vacc_m,course_deg,status,way_id,street_name,city_name,inside_city,city_source,city_resolve_ms,city_candidate_boundaries,city_containing_boundaries,city_place_candidates,speed_limit_kmh,query_ms,candidate_count,speed_candidate_count,nearest_candidate_m,nearest_speed_candidate_m,error\n"
    private struct SpeedCaptureWhitelistEntry {
        let value: String
        let count: Int
        let contextualPhrases: [String]
        let displayLabel: String
    }
    private struct ActiveLocalSpeedCorrection {
        let wayID: String
        let maxspeedValue: String
        let numericSpeedKmh: Int?
    }
    // Source: https://taginfo.openstreetmap.org/api/4/key/values?key=maxspeed&filter=all&lang=de&sortname=count&sortorder=desc&rp=26
    // Snapshot date: 2026-03-03
    private static let speedCaptureWhitelistByPriority: [SpeedCaptureWhitelistEntry] = [
        .init(value: "50", count: 4_638_156, contextualPhrases: ["50", "fuenfzig"], displayLabel: "50 km/h"),
        .init(value: "30", count: 4_230_894, contextualPhrases: ["30", "dreissig"], displayLabel: "30 km/h"),
        .init(value: "40", count: 1_489_813, contextualPhrases: ["40", "vierzig"], displayLabel: "40 km/h"),
        .init(value: "60", count: 1_296_509, contextualPhrases: ["60", "sechzig"], displayLabel: "60 km/h"),
        .init(value: "80", count: 990_073, contextualPhrases: ["80", "achtzig"], displayLabel: "80 km/h"),
        .init(value: "70", count: 716_723, contextualPhrases: ["70", "siebzig"], displayLabel: "70 km/h"),
        .init(value: "100", count: 657_012, contextualPhrases: ["100", "hundert"], displayLabel: "100 km/h"),
        .init(value: "20", count: 634_365, contextualPhrases: ["20", "zwanzig"], displayLabel: "20 km/h"),
        .init(value: "90", count: 480_306, contextualPhrases: ["90", "neunzig"], displayLabel: "90 km/h"),
        .init(value: "120", count: 266_492, contextualPhrases: ["120", "hundertzwanzig"], displayLabel: "120 km/h"),
        .init(value: "10", count: 157_726, contextualPhrases: ["10", "zehn"], displayLabel: "10 km/h"),
        .init(value: "110", count: 152_915, contextualPhrases: ["110", "hundertzehn"], displayLabel: "110 km/h"),
        .init(value: "130", count: 111_960, contextualPhrases: ["130", "hundertdreissig"], displayLabel: "130 km/h"),
        .init(value: "walk", count: 5_788, contextualPhrases: ["fussgaengerzone", "fussgaenger zone", "walk"], displayLabel: "Fussgaengerzone"),
    ]
    private static let speedCaptureValueSet: Set<String> = Set(speedCaptureWhitelistByPriority.map(\.value))
    private static let speedCapturePhraseToValue: [String: String] = [
        "zehn": "10",
        "zwanzig": "20",
        "dreissig": "30",
        "vierzig": "40",
        "fuenfzig": "50",
        "sechzig": "60",
        "siebzig": "70",
        "achtzig": "80",
        "neunzig": "90",
        "hundert": "100",
        "hundert zehn": "110",
        "hundertzehn": "110",
        "einhundert zehn": "110",
        "einhundertzehn": "110",
        "hundert zwanzig": "120",
        "hundertzwanzig": "120",
        "einhundert zwanzig": "120",
        "einhundertzwanzig": "120",
        "hundert dreissig": "130",
        "hundertdreissig": "130",
        "einhundert dreissig": "130",
        "einhundertdreissig": "130",
        "fussgaengerzone": "walk",
        "fussgaenger zone": "walk",
        "fussgaengerbereich": "walk",
        "walk": "walk",
    ]
    private static let speedCaptureContextualStrings: [String] = {
        var out: [String] = []
        var seen = Set<String>()
        for entry in speedCaptureWhitelistByPriority {
            let tokens = [entry.value] + entry.contextualPhrases
            for token in tokens {
                guard seen.insert(token).inserted else {
                    continue
                }
                out.append(token)
            }
        }
        return out
    }()
    private static let lookupTimestampFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter
    }()
    private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private static let exportTimestampFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMdd_HHmmss_SSS"
        return formatter
    }()

    static func defaultManifestURL(bundle: Bundle = .main) -> URL? {
        defaultManifestURL(infoDictionary: bundle.infoDictionary)
    }

    static func defaultManifestURL(infoDictionary: [String: Any]?) -> URL? {
        let candidates = [
            "YouSpeedV3ManifestURL",
            "YouSpeedBundleManifestURL",
        ]
        for key in candidates {
            guard let raw = infoDictionary?[key] as? String else {
                continue
            }
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty || trimmed.contains("$(") {
                continue
            }
            guard let url = URL(string: trimmed),
                  let scheme = url.scheme?.lowercased(),
                  scheme == "http" || scheme == "https" else {
                continue
            }
            return url
        }
        return nil
    }

    static func defaultManifestEndpoints(
        bundle: Bundle = .main,
        preferredCountryCode: String? = "DEU"
    ) -> [V3ManifestEndpoint] {
        var endpoints: [V3ManifestEndpoint] = []
        if let config = try? V3BundleTargetsConfig.loadBundled(bundle: bundle) {
            endpoints.append(contentsOf: config.manifestEndpoints(preferredCountryCode: preferredCountryCode))
        }
        if let explicitURL = defaultManifestURL(bundle: bundle) {
            endpoints.append(
                V3ManifestEndpoint(
                    countryID: "custom",
                    countryCode: "UNK",
                    regionID: "custom",
                    manifestRegion: "custom",
                    manifestURL: explicitURL
                )
            )
        }
        var seen = Set<URL>()
        var deduped: [V3ManifestEndpoint] = []
        for endpoint in endpoints {
            guard seen.insert(endpoint.manifestURL).inserted else {
                continue
            }
            deduped.append(endpoint)
        }
        return deduped
    }

    private func refreshDownloadedBundleInventory() async {
        do {
            let downloaded = try await bundleManager.listDownloadedBundles()
            var countByRegion: [String: Int] = [:]
            var latestByRegion: [String: String] = [:]
            for bundle in downloaded {
                let key = bundle.region.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                countByRegion[key, default: 0] += 1
                if let existing = latestByRegion[key] {
                    if bundle.bundleVersion > existing {
                        latestByRegion[key] = bundle.bundleVersion
                    }
                } else {
                    latestByRegion[key] = bundle.bundleVersion
                }
            }
            downloadedBundleCountByRegion = countByRegion
            downloadedBundleLatestVersionByRegion = latestByRegion
        } catch {
            Self.logger.warning("bundle inventory refresh failed: \(error.localizedDescription, privacy: .public)")
            downloadedBundleCountByRegion = [:]
            downloadedBundleLatestVersionByRegion = [:]
        }
    }

    private func buildBundleDownloadSections() -> [BundleDownloadCountrySection] {
        guard let config = bundledTargetsConfig else {
            return []
        }
        var sections: [BundleDownloadCountrySection] = []
        let locale = Locale.current
        for country in config.countries {
            let countryCode = country.countryCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
            let countryName = localizedCountryName(for: country, locale: locale)
            let endpointsForCountry = manifestEndpoints.filter {
                $0.countryID.lowercased() == country.countryID.lowercased()
            }
            guard !endpointsForCountry.isEmpty else {
                continue
            }
            let options = endpointsForCountry.map { endpoint in
                BundleDownloadOption(
                    id: "\(endpoint.countryID)|\(endpoint.manifestRegion)",
                    countryCode: countryCode,
                    countryName: countryName,
                    displayName: localizedRegionName(for: endpoint, countryName: countryName, locale: locale),
                    endpoint: endpoint
                )
            }.sorted {
                $0.displayName.localizedCaseInsensitiveCompare($1.displayName) == .orderedAscending
            }
            sections.append(
                BundleDownloadCountrySection(
                    id: countryCode,
                    countryCode: countryCode,
                    countryName: countryName,
                    options: options
                )
            )
        }
        return sections.sorted {
            $0.countryName.localizedCaseInsensitiveCompare($1.countryName) == .orderedAscending
        }
    }

    private func refreshExpectedBundleSizes() async {
        var sizes: [String: Int64] = [:]
        for section in bundleDownloadSections {
            for option in section.options {
                let primaryRegion = normalizedManifestRegion(option.endpoint.manifestRegion)
                if sizes[primaryRegion] == nil,
                   let bytes = await fetchExpectedBundleBytes(from: option.endpoint.manifestURL) {
                    sizes[primaryRegion] = bytes
                }
            }
        }
        expectedBundleBytesByRegion = sizes
    }

    private func fetchExpectedBundleBytes(from manifestURL: URL) async -> Int64? {
        do {
            var request = URLRequest(url: manifestURL)
            request.timeoutInterval = 15
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                return nil
            }
            let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: data)
            return manifest.db.bytes > 0 ? manifest.db.bytes : nil
        } catch {
            return nil
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        guard bytes > 0 else {
            return "0 MB"
        }
        let gb = Double(bytes) / 1_000_000_000.0
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "de_DE")
        formatter.numberStyle = .decimal
        if gb >= 1.0 {
            formatter.minimumFractionDigits = 0
            formatter.maximumFractionDigits = gb < 10 ? 1 : 0
            let value = formatter.string(from: NSNumber(value: gb)) ?? String(format: "%.1f", gb)
            return "\(value) GB"
        }
        let mb = Double(bytes) / 1_000_000.0
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = 0
        let value = formatter.string(from: NSNumber(value: mb.rounded())) ?? String(Int(mb.rounded()))
        return "\(value) MB"
    }

    private func localizedCountryName(for country: V3BundleTargetCountryConfig, locale: Locale) -> String {
        let iso2 = country.iso2?.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() ?? ""
        if let localized = locale.localizedString(forRegionCode: iso2), !localized.isEmpty {
            return localized
        }
        let raw = country.countryID.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
        return String(raw.prefix(1)).uppercased(with: locale) + String(raw.dropFirst())
    }

    private func localizedRegionName(for endpoint: V3ManifestEndpoint, countryName: String, locale: Locale) -> String {
        let normalizedCountryID = endpoint.countryID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedRegionID = endpoint.regionID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalizedCountryID == normalizedRegionID {
            return countryName
        }
        let localizationKey = "map.region.\(normalizedRegionID)"
        let localizedRegion = NSLocalizedString(localizationKey, comment: "")
        if localizedRegion != localizationKey {
            return localizedRegion
        }
        if let configured = endpoint.regionName?.trimmingCharacters(in: .whitespacesAndNewlines),
           !configured.isEmpty {
            return configured
        }
        let tail = normalizedRegionID.split(separator: "/").last.map(String.init) ?? normalizedRegionID

        let words = tail
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
        let title = words
            .map { token in
                String(token.prefix(1)).uppercased(with: locale) + String(token.dropFirst())
            }
            .joined(separator: " ")
        return title.isEmpty ? countryName : title
    }

    private func normalizedManifestRegion(_ raw: String) -> String {
        raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private func idToken(_ raw: String) -> String {
        raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .replacingOccurrences(of: "_", with: "-")
            .replacingOccurrences(of: "/", with: "-")
    }

    private func countryManifestRegionToken(for option: BundleDownloadOption) -> String {
        idToken(option.endpoint.countryID)
    }

    private func normalizedCountryCode(_ raw: String?) -> String? {
        guard let raw else {
            return nil
        }
        let code = raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard code.count == 3 else {
            return nil
        }
        return code
    }

    private func isGermanAutobahnUnlimitedMatch(result: SpeedLimitResult, localOverrideValue: String?) -> Bool {
        guard localOverrideValue == nil,
              result.isUnlimitedSpeedLimit == true,
              normalizedCountryCode(activePenaltyRules.countryCode) == "DEU" else {
            return false
        }
        return result.highway?.lowercased() == "motorway"
    }

    private func inferCountryCodeFromDBPath(_ dbPath: String) -> String? {
        let fileName = URL(fileURLWithPath: dbPath).lastPathComponent.uppercased()
        if fileName.count >= 3 {
            let prefix = String(fileName.prefix(3))
            if prefix.allSatisfy(\.isLetter) {
                return prefix
            }
        }
        return nil
    }

    private func makeSpeedLimitService(dbPath: String, preferredCountryCode: String? = nil) -> V3SpeedLimitService {
        V3SpeedLimitService(
            dbPath: dbPath,
            countryCode: normalizedCountryCode(preferredCountryCode)
                ?? normalizedCountryCode(activePenaltyRules.countryCode)
                ?? inferCountryCodeFromDBPath(dbPath),
            matchingModel: matcherDebugProfile.matchingModel
        )
    }

    private func applyPenaltyRulesForActiveBundle(preferredCountryCode: String? = nil) async {
        var context: PenaltyRuleContext?
        if !activeDBPath.isEmpty {
            context = try? await bundleManager.resolvePenaltyRuleContext(forDBPath: activeDBPath)
        }

        if let rulesPath = context?.rulesPath {
            do {
                let fileURL = URL(fileURLWithPath: rulesPath)
                let rules = try SpeedPenaltyRuleSet.loadFile(at: fileURL)
                activePenaltyRules = rules
                activePenaltyRulesFile = fileURL.lastPathComponent
                return
            } catch {
                Self.logger.warning("rules load from local bundle failed: \(error.localizedDescription, privacy: .public)")
            }
        }

        let countryCode = normalizedCountryCode(preferredCountryCode)
            ?? normalizedCountryCode(context?.countryCode)
            ?? inferCountryCodeFromDBPath(activeDBPath)
            ?? "DEU"
        let bundledStem = "\(countryCode)-rules"
        if let rules = try? SpeedPenaltyRuleSet.loadBundled(named: bundledStem) {
            activePenaltyRules = rules
            activePenaltyRulesFile = "\(bundledStem).json"
            return
        }
        if let fallbackBundled = try? SpeedPenaltyRuleSet.loadBundled(named: "DEU-rules") {
            activePenaltyRules = fallbackBundled
            activePenaltyRulesFile = "DEU-rules.json"
            return
        }
        activePenaltyRules = SpeedPenaltyRuleSet.fallbackDEU()
        activePenaltyRulesFile = "DEU-rules.json"
    }

    override init() {
        let storedThreshold = UserDefaults.standard.object(forKey: Self.audioAlertThresholdDefaultsKey) as? Int
        let storedAudioEnabled = UserDefaults.standard.object(forKey: Self.audioAlertsEnabledDefaultsKey) as? Bool
        let storedHideWelcome = UserDefaults.standard.object(forKey: Self.hideWelcomeScreenDefaultsKey) as? Bool
        let storedDashcamEnabled = UserDefaults.standard.object(forKey: Self.dashcamRecordingEnabledDefaultsKey) as? Bool
        let storedTSREnabled = UserDefaults.standard.object(forKey: Self.trafficSignRecognitionEnabledDefaultsKey) as? Bool
        let storedPanoramaxEnabled = UserDefaults.standard.object(forKey: Self.panoramaxCaptureEnabledDefaultsKey) as? Bool
        let storedTriggerMode = UserDefaults.standard.string(forKey: Self.panoramaxTriggerModeDefaultsKey).flatMap(PanoramaxCaptureTriggerMode.init(rawValue:)) ?? .distance
        let storedMinimumDistance = UserDefaults.standard.object(forKey: Self.panoramaxMinimumDistanceDefaultsKey) as? Double
        let storedMinimumInterval = UserDefaults.standard.object(forKey: Self.panoramaxMinimumIntervalDefaultsKey) as? Double
        let storedUnlimitedStorage = UserDefaults.standard.object(forKey: Self.panoramaxUnlimitedStorageDefaultsKey) as? Bool
        let storedStorageLimit = UserDefaults.standard.object(forKey: Self.panoramaxStorageLimitDefaultsKey) as? Double
        let storedDeleteUploadedImages = UserDefaults.standard.object(
            forKey: Self.panoramaxDeleteUploadedImagesDefaultsKey
        ) as? Bool
        let storedMatcherProfile = UserDefaults.standard.string(forKey: Self.matcherDebugProfileDefaultsKey)
        let storedMatcherForcedVersion = UserDefaults.standard.integer(forKey: Self.matcherDebugProfileForcedVersionDefaultsKey)
        let bundledRules = (try? SpeedPenaltyRuleSet.loadBundled(named: "DEU-rules")) ?? SpeedPenaltyRuleSet.fallbackDEU()
        let initialMatcherProfile = MatcherDebugProfile.resolveInitialProfile(
            storedRawValue: storedMatcherProfile,
            forcedVersion: storedMatcherForcedVersion
        )
        activePenaltyRules = bundledRules
        activePenaltyRulesFile = "DEU-rules.json"
        audioAlertThresholdKmh = min(max(storedThreshold ?? Self.defaultAudioAlertThresholdKmh, 0), 80)
        audioAlertsEnabled = storedAudioEnabled ?? Self.defaultAudioAlertsEnabled
        hideWelcomeScreen = storedHideWelcome ?? Self.defaultHideWelcomeScreen
        dashcamRecordingEnabled = storedDashcamEnabled ?? false
        // Keep the model-backed consumer opt-in until a validated country
        // model is installed; the shared camera hook is already available.
        trafficSignRecognitionEnabled = storedTSREnabled ?? false
        panoramaxCaptureEnabled = storedPanoramaxEnabled ?? true
        panoramaxTriggerMode = storedTriggerMode
        panoramaxMinimumDistanceMeters = min(max(storedMinimumDistance ?? 25, 3), 100)
        panoramaxMinimumIntervalSeconds = min(max(storedMinimumInterval ?? 5, 1), 60)
        panoramaxUnlimitedStorage = storedUnlimitedStorage ?? false
        panoramaxStorageLimitMB = min(max(storedStorageLimit ?? 1000, 100), 10_000)
        panoramaxDeleteUploadedImages = storedDeleteUploadedImages ?? false
        matcherDebugProfile = initialMatcherProfile
        bundledTargetsConfig = try? V3BundleTargetsConfig.loadBundled()
        manifestEndpoints = Self.defaultManifestEndpoints()
        panoramaxAccount = PanoramaxAccountModel()
        let endpointCount = manifestEndpoints.count
        Self.logger.notice("sync endpoints configured count=\(endpointCount, privacy: .public)")
        super.init()
        trafficSignRecognitionState = trafficSignRecognitionEnabled ? .unavailable : .disabled
        panoramaxQueueStore = try? PanoramaxQueueStore(performStartupMaintenance: false)
        startPanoramaxQueueMaintenance()
        driveCaptureCoordinator = DriveCaptureCoordinator(queueStore: panoramaxQueueStore)
        applyPanoramaxConfiguration()
        driveCaptureCoordinator?.onChange = { [weak self] in
            self?.syncDriveRecorderState()
        }
        syncDriveRecorderState()
        prepareTrafficSignRecognitionRuntime()
        refreshDashcamRecordings()
        refreshPanoramaxBatches()
        if storedMatcherForcedVersion < MatcherDebugProfile.forcedProfileVersion
            || storedMatcherProfile != initialMatcherProfile.rawValue
        {
            UserDefaults.standard.set(initialMatcherProfile.rawValue, forKey: Self.matcherDebugProfileDefaultsKey)
            UserDefaults.standard.set(
                MatcherDebugProfile.forcedProfileVersion,
                forKey: Self.matcherDebugProfileForcedVersionDefaultsKey
            )
        }
        if let screenshotState = AppScreenshotState.current() {
            clearDrivingLogsOnAppLaunch()
            configureForScreenshotMode(screenshotState)
            return
        }
        clearDrivingLogsOnAppLaunch()
        bundleDownloadSections = buildBundleDownloadSections()
        locationManager.delegate = self
        speechSynthesizer.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.activityType = .automotiveNavigation
        locationManager.distanceFilter = kCLDistanceFilterNone
        beginStartupDataLoadIfNeeded()
        Task { @MainActor [weak self] in
            await self?.refreshLocalObservations()
            await self?.refreshDownloadedBundleInventory()
            await self?.refreshExpectedBundleSizes()
        }
    }

    var isDatabaseReadyForQueries: Bool {
        startupDataState == .ready && speedLimitService != nil && !activeDBPath.isEmpty
    }

    var driveRecorderPreviewSession: AVCaptureSession? {
        driveCaptureCoordinator?.session
    }

    var panoramaxPreviewSession: AVCaptureSession? {
        driveRecorderPreviewSession
    }

    var isDriveRecorderActive: Bool {
        switch driveRecorderState {
        case .preparing, .recording, .stopping:
            return true
        case .disabled, .denied, .unavailable, .failed:
            return false
        }
    }

    var isPanoramaxRecordingActive: Bool {
        isDriveRecorderActive && panoramaxCaptureEnabled
    }

    var canProcessPanoramaxUploads: Bool {
        DriveRecorderPolicy.canProcessPanoramaxUploads(for: driveRecorderState)
    }

    var canToggleDriveRecorderModules: Bool {
        DriveRecorderPolicy.canToggleModules(for: driveRecorderState)
    }

    func toggleDriveRecorder() {
        if isDriveRecorderActive {
            guard driveRecorderState != .stopping else { return }
            driveCaptureCoordinator?.stop()
            return
        }
        guard !(panoramaxCaptureEnabled && panoramaxQueueMaintenanceInProgress) else {
            panoramaxLastCaptureDetail = "Panoramax-Speicher wird vorbereitet"
            return
        }
        if trafficSignRecognitionEnabled, trafficSignRuntime == nil {
            prepareTrafficSignRecognitionRuntime()
        }
        let configuration = DriveRecorderPolicy.mainControlStartConfiguration(
            trafficSignRecognitionEnabled: trafficSignRecognitionEnabled,
            panoramaxEnabled: panoramaxCaptureEnabled
        )
        // The main recorder control owns the Dashcam start. Persist that
        // selection before the coordinator publishes `.preparing`, while
        // retaining the independently selected TSR and Panoramax consumers.
        dashcamRecordingEnabled = configuration.dashcamEnabled
        cancelPanoramaxUploadsForRecorderStart()
        driveCaptureCoordinator?.start(
            dashcamEnabled: configuration.dashcamEnabled,
            trafficSignRecognitionEnabled: configuration.trafficSignRecognitionEnabled,
            panoramaxEnabled: configuration.panoramaxEnabled
        )
    }

    func togglePanoramaxRecording() {
        toggleDriveRecorder()
    }

    static func trafficSignModelPackDirectoryURL(
        countryCode: String = "DE"
    ) throws -> URL {
        #if DEBUG
        if let configuredPath = ProcessInfo.processInfo.environment["YOUSPEED_TSR_MODEL_PACK_DIR"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !configuredPath.isEmpty {
            return URL(fileURLWithPath: configuredPath, isDirectory: true)
        }
        #endif
        throw TrafficSignRuntimeUnavailability(
            code: .modelPackAuthenticationRequired,
            detail: "Downloaded TSR model packs remain disabled until signature verification and approved-pack activation are implemented. In DEBUG builds, set YOUSPEED_TSR_MODEL_PACK_DIR explicitly for an integrity-checked developer pack (country \(countryCode.uppercased()))."
        )
    }

    /// Keeps lifecycle state in the same atomic snapshot as the map context.
    /// The camera queue never reaches into this MainActor-owned view model.
    func setTrafficSignApplicationActive(_ isActive: Bool) {
        trafficSignApplicationIsActive = isActive
        refreshTrafficSignFrameSnapshot()
    }

    private func prepareTrafficSignRecognitionRuntime() {
        guard trafficSignRuntime == nil, trafficSignRuntimeLoadTask == nil else { return }

        let directoryURL: URL
        do {
            directoryURL = try Self.trafficSignModelPackDirectoryURL()
        } catch let reason as TrafficSignRuntimeUnavailability {
            handleTrafficSignRuntimeUnavailability(reason)
            return
        } catch {
            handleTrafficSignRuntimeUnavailability(TrafficSignRuntimeUnavailability(
                code: .modelPackDirectoryMissing,
                detail: "The local TSR model-pack directory is unavailable."
            ))
            return
        }

        let frameState = trafficSignFrameState
        let snapshotProvider: TrafficSignRuntime.SnapshotProvider = {
            frameState.snapshot()
        }
        let runtimeVersion = UIDevice.current.systemVersion
        let countryCode = Self.defaultTrafficSignCountryCode
        let appVersion = (Bundle.main.object(
            forInfoDictionaryKey: "CFBundleShortVersionString"
        ) as? String) ?? "0.0.0"
        let eventHandler: TrafficSignRuntime.EventHandler = { [weak self] emission in
            Task { @MainActor [weak self] in
                self?.acceptTrafficSignRuntimeEmission(emission)
            }
        }
        let unavailableHandler: TrafficSignRuntime.UnavailabilityHandler = { [weak self] reason in
            Task { @MainActor [weak self] in
                self?.handleTrafficSignRuntimeUnavailability(reason)
            }
        }

        trafficSignRecognitionUnavailableDetail = "Loading and verifying the local traffic-sign model pack."
        trafficSignRuntimeLoadTask = Task { @MainActor [weak self] in
            let result = await Task.detached(priority: .utility) {
                TrafficSignRuntimeBootstrap.make(
                    modelPackDirectoryURL: directoryURL,
                    runtimeVersion: runtimeVersion,
                    appVersion: appVersion,
                    countryCode: countryCode,
                    snapshotProvider: snapshotProvider,
                    callbackQueue: .main,
                    eventHandler: eventHandler,
                    unavailabilityHandler: unavailableHandler
                )
            }.value

            guard let self else {
                if case .ready(let runtime) = result { runtime.stop() }
                return
            }
            self.trafficSignRuntimeLoadTask = nil
            guard !Task.isCancelled else {
                if case .ready(let runtime) = result { runtime.stop() }
                return
            }

            switch result {
            case .ready(let runtime):
                self.trafficSignRuntime = runtime
                self.trafficSignRecognitionModelPackID = runtime.verifiedPack.manifest.packId
                self.trafficSignRecognitionUnavailableDetail = ""
                if let driveCaptureCoordinator = self.driveCaptureCoordinator {
                    driveCaptureCoordinator.setVideoFrameConsumer(runtime)
                    if self.trafficSignRecognitionEnabled,
                       driveCaptureCoordinator.state == .recording {
                        _ = driveCaptureCoordinator
                            .setTrafficSignRecognitionEnabledDuringRecording(true)
                    }
                }
                if self.trafficSignRecognitionEnabled,
                   self.driveRecorderState != .recording {
                    self.trafficSignRecognitionState = .noRecognition
                }
                self.syncDriveRecorderState()
            case .unavailable(let reason):
                self.handleTrafficSignRuntimeUnavailability(reason)
            }
        }
    }

    private func handleTrafficSignRuntimeUnavailability(
        _ reason: TrafficSignRuntimeUnavailability
    ) {
        trafficSignRuntime?.stop()
        trafficSignRuntime = nil
        trafficSignRecognitionModelPackID = nil
        trafficSignRecognitionUnavailableDetail = reason.detail
        driveCaptureCoordinator?.setVideoFrameConsumer(nil)
        if trafficSignRecognitionEnabled {
            trafficSignRecognitionState = .unavailable
        }
        syncDriveRecorderState()
    }

    private func refreshTrafficSignFrameSnapshot() {
        guard trafficSignFrameContextIsCurrent,
              let context = latestTrafficSignDetectionContext,
              context.isValid else {
            trafficSignFrameState.update(nil)
            return
        }
        let candidateRecentlySeen: Bool
        if let event = trafficSignRecognitionLastEvent {
            switch event.state {
            case .provisional, .confirmed, .unknown:
                candidateRecentlySeen = abs(event.frameTimestampUtc.timeIntervalSinceNow) <= 1.5
            case .noRecognition, .unavailable:
                candidateRecentlySeen = false
            }
        } else {
            candidateRecentlySeen = false
        }
        trafficSignFrameState.update(TrafficSignFrameSnapshot(
            context: context,
            conditions: TrafficSignAnalysisConditions(
                speedKmh: currentSpeedKmh,
                candidateRecentlySeen: candidateRecentlySeen,
                lowPowerMode: ProcessInfo.processInfo.isLowPowerModeEnabled,
                thermalState: Self.trafficSignThermalState(ProcessInfo.processInfo.thermalState),
                appIsActive: trafficSignApplicationIsActive
            ),
            sessionGeneration: trafficSignRecorderGeneration,
            contextGeneration: trafficSignContextGeneration
        ))
    }

    private func beginTrafficSignContextLookup(fixID: Int) {
        latestTrafficSignLookupFixID = fixID
        // Pause new frame admission while the fix is being matched, but keep
        // the previous identity long enough to distinguish a coordinate-only
        // update from a real way/direction/source change. This prevents slow
        // inference from being starved by routine same-road GPS fixes.
        trafficSignFrameContextIsCurrent = false
        trafficSignFrameState.update(nil)
    }

    /// Any newly committed base-source information invalidates frames captured
    /// under the previous OSM/local snapshot immediately. The next completed
    /// map match publishes a fresh coherent context.
    private func invalidateTrafficSignInferenceContext() {
        trafficSignContextGeneration &+= 1
        trafficSignFrameContextIsCurrent = false
        latestTrafficSignDetectionContext = nil
        trafficSignFrameState.update(nil)
    }

    /// Clears only the transient camera layer when a durable map/local input
    /// changes outside the normal GPS lookup. This prevents a stationary drive
    /// from retaining a detection after a bundle activation or a correction
    /// edit while leaving both durable sources untouched.
    private func invalidateTrafficSignOverrideForBaseSourceMutation() {
        let hadPublishedTrafficSignState = currentTrafficSignSourceSignature != nil
            || latestTrafficSignDetectionContext != nil
            || trafficSignOverridePolicy.activeOverride != nil
            || trafficSignRecognitionLastEvent != nil
        // Always advance the epoch: a first lookup may already be running even
        // though no context has been published yet.
        currentTrafficSignSourceSignature = nil
        invalidateTrafficSignInferenceContext()
        guard hadPublishedTrafficSignState else { return }
        trafficSignOverridePolicy.clear()
        trafficSignRecognitionActiveOverride = nil
        trafficSignRecognitionLastEvent = nil
        restoreBaseSpeedLimitPresentation()
        if !trafficSignRecognitionEnabled {
            trafficSignRecognitionState = .disabled
        } else if trafficSignRuntime == nil {
            trafficSignRecognitionState = .unavailable
        } else {
            trafficSignRecognitionState = .noRecognition
        }
    }

    private func invalidateTrafficSignOverrideIfBundleWillChange(
        bundleVersion: String,
        dbPath: String
    ) {
        guard bundleVersion != activeBundleVersion || dbPath != activeDBPath else { return }
        invalidateTrafficSignOverrideForBaseSourceMutation()
    }

    private static func trafficSignThermalState(
        _ state: ProcessInfo.ThermalState
    ) -> TrafficSignThermalState {
        switch state {
        case .nominal: return .nominal
        case .fair: return .fair
        case .serious: return .serious
        case .critical: return .critical
        @unknown default: return .serious
        }
    }

    /// Frame consumers request this snapshot before dispatching asynchronous
    /// inference. The returned value is later embedded in the recognition
    /// event, so a callback can never borrow a newer way/location by accident.
    func trafficSignDetectionContextSnapshot() -> TrafficSignDetectionContext? {
        latestTrafficSignDetectionContext
    }

    /// Accepts one normalized result from either the live camera or the
    /// still-image path. A camera result affects only the transient runtime
    /// source; OSM and local corrections remain unchanged and reviewable.
    private func acceptTrafficSignRuntimeEmission(_ emission: TrafficSignRuntimeEmission) {
        guard emission.sessionGeneration == trafficSignRecorderGeneration,
              emission.contextGeneration == trafficSignContextGeneration else { return }
        acceptTrafficSignRecognitionEvent(emission.event)
    }

    func acceptTrafficSignRecognitionEvent(_ event: TrafficSignRecognitionEvent) {
        guard driveRecorderState == .recording,
              driveRecorderTrafficSignRecognitionActive,
              trafficSignFrameContextIsCurrent,
              let currentContext = latestTrafficSignDetectionContext,
              let eventContext = event.roadContext,
              currentContext.wayId == eventContext.wayId,
              currentContext.travelDirection == eventContext.travelDirection,
              currentContext.sourceSignature == eventContext.sourceSignature,
              let currentTrafficSignSourceSignature else { return }

        let previousOverride = trafficSignOverridePolicy.activeOverride
        let acceptedConfirmedDetection = trafficSignOverridePolicy.ingestConfirmedDetection(
            event,
            currentSourceSignature: currentTrafficSignSourceSignature
        )
        trafficSignRecognitionActiveOverride = trafficSignOverridePolicy.activeOverride

        // Once a confirmed camera limit is actively driving the display, an
        // empty or provisional later frame must not make the badge claim that
        // no camera result is in force. Only a newer confirmed detection (which
        // may replace or explicitly end it) changes the effective presentation.
        if previousOverride == nil || acceptedConfirmedDetection {
            publishTrafficSignRecognitionState(for: event)
        }
        refreshTrafficSignFrameSnapshot()

        guard acceptedConfirmedDetection else { return }
        let resolved = trafficSignOverridePolicy.resolvedSpeedKmh(
            osmSpeedKmh: currentBundledSpeedLimitKmh,
            localCorrectionSpeedKmh: currentLocalCorrectionSpeedKmh,
            currentContext: currentContext
        )
        trafficSignRecognitionActiveOverride = trafficSignOverridePolicy.activeOverride
        speedLimitKmh = resolved
        if trafficSignOverridePolicy.activeOverride != nil {
            speedLimitDisplayText = nil
            isUnlimitedSpeedLimitActive = false
        } else {
            speedLimitDisplayText = currentBaseSpeedLimitDisplayText
            isUnlimitedSpeedLimitActive = currentBaseUnlimitedSpeedLimitActive
        }
        if let resolved {
            lastKnownSpeedLimitKmh = resolved
        }
        if let context = event.roadContext {
            let latitudeText = String(format: "%.5f", context.latitude)
            let longitudeText = String(format: "%.5f", context.longitude)
            let headingText = String(format: "%.1f", context.headingDegrees)
            let effectiveText = resolved.map(String.init) ?? "nil"
            appendLookupEvent(
                "tsr state=\(event.state.rawValue) way=\(context.wayId) lat=\(latitudeText) lon=\(longitudeText) heading=\(headingText) direction=\(context.travelDirection.rawValue) effective=\(effectiveText)"
            )
        }
        maybeNotifyDrivingBanWarning()
        maybeSpeakOverspeedWarning()
    }

    private func publishTrafficSignRecognitionState(
        for event: TrafficSignRecognitionEvent
    ) {
        trafficSignRecognitionLastEvent = event
        switch event.state {
        case .noRecognition:
            trafficSignRecognitionState = .noRecognition
        case .provisional:
            if let value = event.candidate?.value {
                trafficSignRecognitionState = .provisional(value)
            } else {
                trafficSignRecognitionState = .unknown
            }
        case .confirmed:
            if let value = event.candidate?.value {
                trafficSignRecognitionState = .confirmed(value)
            } else {
                trafficSignRecognitionState = .unknown
            }
        case .unknown:
            trafficSignRecognitionState = .unknown
        case .unavailable:
            trafficSignRecognitionState = .unavailable
        }
    }

    /// Changes only the Dashcam consumer. The shared camera session, elapsed
    /// drive time, TSR, and Panoramax capture stay untouched.
    @discardableResult
    func toggleDriveRecorderDashcam() -> Bool {
        guard canToggleDriveRecorderModules,
              !driveRecorderDashcamTransitioning,
              let driveCaptureCoordinator else { return false }

        if driveRecorderDashcamActive {
            dashcamRecordingEnabled = false
            if !driveRecorderPanoramaxActive && !driveRecorderTrafficSignRecognitionActive {
                driveCaptureCoordinator.stop()
                return true
            }
            guard driveCaptureCoordinator.setDashcamEnabledDuringRecording(false) else {
                dashcamRecordingEnabled = true
                return false
            }
            return true
        }

        guard driveCaptureCoordinator.setDashcamEnabledDuringRecording(true) else {
            return false
        }
        dashcamRecordingEnabled = true
        syncDriveRecorderState()
        return true
    }

    /// Changes only the model-backed TSR consumer. Until a real recognizer is
    /// attached this returns false, allowing the UI to explain availability
    /// instead of presenting a fake active state.
    @discardableResult
    func toggleDriveRecorderTrafficSignRecognition() -> Bool {
        guard canToggleDriveRecorderModules,
              let driveCaptureCoordinator else { return false }

        if driveRecorderTrafficSignRecognitionActive {
            trafficSignRecognitionEnabled = false
            if !driveRecorderPanoramaxActive
                && !driveRecorderDashcamActive
                && !driveRecorderDashcamTransitioning {
                driveCaptureCoordinator.stop()
                return true
            }
            guard driveCaptureCoordinator.setTrafficSignRecognitionEnabledDuringRecording(false) else {
                trafficSignRecognitionEnabled = true
                return false
            }
            return true
        }

        if !driveRecorderTrafficSignRecognitionAvailable {
            prepareTrafficSignRecognitionRuntime()
            if trafficSignRecognitionEnabled {
                trafficSignRecognitionEnabled = false
                syncDriveRecorderState()
                return true
            }
            // Preserve an explicit selection while remaining honest about the
            // missing model. The chip shows selected + unavailable, and the
            // recorder continues with its other consumers.
            trafficSignRecognitionEnabled = true
            _ = driveCaptureCoordinator.setTrafficSignRecognitionEnabledDuringRecording(true)
            syncDriveRecorderState()
            return false
        }

        guard driveCaptureCoordinator.setTrafficSignRecognitionEnabledDuringRecording(true) else {
            return false
        }
        trafficSignRecognitionEnabled = true
        syncDriveRecorderState()
        return true
    }

    private func applyPanoramaxConfiguration() {
        let cadence = PanoramaxCadenceConfiguration(
            distanceMeters: panoramaxMinimumDistanceMeters,
            fallbackInterval: panoramaxMinimumIntervalSeconds,
            maxLocationAge: 10,
            maxAccuracyMeters: 50,
            triggerMode: panoramaxTriggerMode
        )
        driveCaptureCoordinator?.updatePanoramaxConfiguration(
            cadence,
            storageLimitBytes: panoramaxUnlimitedStorage ? nil : Int64(panoramaxStorageLimitMB * 1_000_000)
        )
    }

    private func syncDriveRecorderState() {
        let previousState = driveRecorderState
        let previousDashcamURL = dashcamFileURL
        let previousDashcamActive = driveRecorderDashcamActive
        let previousTrafficSignActive = driveRecorderTrafficSignRecognitionActive
        driveRecorderState = driveCaptureCoordinator?.state ?? .failed
        driveRecorderStartedAt = driveCaptureCoordinator?.startedAt
        dashcamFileURL = driveCaptureCoordinator?.dashcamFileURL
        driveRecorderDashcamActive = driveCaptureCoordinator?.isDashcamModuleActive ?? false
        driveRecorderDashcamTransitioning = driveCaptureCoordinator?.dashcamTransitionInFlight ?? false
        driveRecorderDashcamAvailable = driveCaptureCoordinator?.isDashcamOutputAvailable ?? false
        driveRecorderTrafficSignRecognitionActive = driveCaptureCoordinator?.isTrafficSignRecognitionModuleActive ?? false
        driveRecorderTrafficSignRecognitionAvailable = driveCaptureCoordinator?.isTrafficSignRecognitionOutputAvailable ?? false
        driveRecorderPanoramaxActive = driveCaptureCoordinator?.isPanoramaxModuleActive ?? false
        // The model may finish loading while camera permission/session setup is
        // still in progress. Honor the persisted chip selection as soon as the
        // coordinator reaches recording instead of requiring a second tap.
        if driveRecorderState == .recording,
           trafficSignRecognitionEnabled,
           trafficSignRuntime != nil,
           !driveRecorderTrafficSignRecognitionActive,
           driveRecorderTrafficSignRecognitionAvailable,
           driveCaptureCoordinator?.setTrafficSignRecognitionEnabledDuringRecording(true) == true {
            // The coordinator notification re-enters this method with its
            // active state already committed; let that pass publish the rest.
            return
        }
        if previousTrafficSignActive != driveRecorderTrafficSignRecognitionActive
            || (previousState == .recording) != (driveRecorderState == .recording) {
            trafficSignRecorderGeneration &+= 1
            refreshTrafficSignFrameSnapshot()
        }
        if !trafficSignRecognitionEnabled {
            trafficSignRecognitionState = .disabled
        } else if driveRecorderTrafficSignRecognitionActive,
                  trafficSignRecognitionState == .unavailable {
            trafficSignRecognitionUnavailableDetail = ""
            trafficSignRecognitionState = .noRecognition
        } else if trafficSignRuntime == nil {
            trafficSignRecognitionState = .unavailable
        } else if driveRecorderState == .recording,
                  !driveRecorderTrafficSignRecognitionActive {
            trafficSignRecognitionState = .unavailable
            if trafficSignRecognitionUnavailableDetail.isEmpty {
                trafficSignRecognitionUnavailableDetail =
                    "The TSR camera output is unavailable for this recording configuration."
            }
        } else if trafficSignRecognitionState == .unavailable {
            trafficSignRecognitionState = .noRecognition
        }
        panoramaxCaptureState = driveRecorderState
        panoramaxCaptureCount = driveCaptureCoordinator?.capturedImageCount ?? 0
        panoramaxLastCaptureAt = driveCaptureCoordinator?.lastCaptureAt
        panoramaxLastCaptureDetail = driveCaptureCoordinator?.lastCaptureDetail ?? "Panoramax-Speicher nicht verfuegbar"
        panoramaxLastAccuracyMeters = driveCaptureCoordinator?.lastAccuracyMeters
        if previousState != driveRecorderState, canProcessPanoramaxUploads {
            refreshPanoramaxBatches()
        }
        let trafficSignSessionEnded = previousState == .recording
            && driveRecorderState != .recording
        let trafficSignModuleBecameInactive = previousTrafficSignActive
            && !driveRecorderTrafficSignRecognitionActive
        if trafficSignSessionEnded
            || trafficSignModuleBecameInactive
            || !trafficSignRecognitionEnabled {
            trafficSignOverridePolicy.clear()
            trafficSignRecognitionActiveOverride = nil
            trafficSignRecognitionLastEvent = nil
            restoreBaseSpeedLimitPresentation()
            if !trafficSignRecognitionEnabled {
                trafficSignRecognitionState = .disabled
            } else if trafficSignRuntime == nil {
                trafficSignRecognitionState = .unavailable
            } else if driveRecorderState == .recording,
                      !driveRecorderTrafficSignRecognitionActive {
                // A selected runtime can still be rejected by the concrete
                // multi-output capture graph. Do not present that as an active
                // recognizer which merely found no sign.
                trafficSignRecognitionState = .unavailable
            } else {
                trafficSignRecognitionState = .noRecognition
            }
        }
        if previousState != driveRecorderState
            || previousDashcamURL != dashcamFileURL
            || previousDashcamActive != driveRecorderDashcamActive {
            refreshDashcamRecordings()
        }
    }

    private func restoreBaseSpeedLimitPresentation() {
        speedLimitKmh = currentLocalCorrectionSpeedKmh ?? currentBundledSpeedLimitKmh
        speedLimitDisplayText = currentBaseSpeedLimitDisplayText
        isUnlimitedSpeedLimitActive = currentBaseUnlimitedSpeedLimitActive
        if let speedLimitKmh {
            lastKnownSpeedLimitKmh = speedLimitKmh
        }
    }

    func refreshDashcamRecordings() {
        dashcamRecordings = DriveCaptureCoordinator.listDashcamRecordings()
    }

    func deleteDashcamRecording(_ recording: DashcamRecording) {
        guard !isDriveRecorderActive else { return }
        _ = DriveCaptureCoordinator.deleteDashcamRecording(id: recording.id)
        refreshDashcamRecordings()
    }

    func refreshPanoramaxBatches() {
        guard let store = panoramaxQueueStore else {
            panoramaxBatches = []
            return
        }
        Task { @MainActor [weak self] in
            guard let self else { return }
            let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
            let result = await PanoramaxQueueMaintenanceExecutor.shared.loadBatches(store: store)
            applyPanoramaxMaintenanceResult(
                result,
                publicationGeneration: publicationGeneration
            )
        }
    }

    var panoramaxGalleryItems: [(batch: PanoramaxBatchRecord, item: PanoramaxItemRecord)] {
        panoramaxBatches.flatMap { batch in batch.items.map { (batch: batch, item: $0) } }
            .sorted { $0.item.metadata.capturedAt > $1.item.metadata.capturedAt }
    }

    func panoramaxThumbnailURL(for item: PanoramaxItemRecord) -> URL? {
        panoramaxQueueStore?.thumbnailURL(for: item)
    }

    func panoramaxOriginalURL(for item: PanoramaxItemRecord) -> URL? {
        panoramaxQueueStore?.originalURL(for: item)
    }

    func setPanoramaxItemIncluded(batchID: String, itemID: String, included: Bool) {
        guard canProcessPanoramaxUploads,
              !activePanoramaxUploadBatchIDs.contains(batchID),
              let batch = try? panoramaxQueueStore?.getBatch(batchID),
              DriveRecorderPolicy.canEditPanoramaxSelection(in: batch.state),
              let item = batch.items.first(where: { $0.itemID == itemID }),
              DriveRecorderPolicy.canSelectPanoramaxItem(in: item.state) else { return }
        do {
            _ = try panoramaxQueueStore?.updateItem(
                batchID: batchID,
                itemID: itemID,
                state: included ? .included : .excluded
            )
            refreshPanoramaxBatches()
        } catch {
            panoramaxLastCaptureDetail = "Bildstatus konnte nicht gespeichert werden"
        }
    }

    func togglePanoramaxFavorite(batchID: String, itemID: String) {
        guard canProcessPanoramaxUploads,
              !activePanoramaxUploadBatchIDs.contains(batchID) else { return }
        guard let batch = panoramaxBatches.first(where: { $0.batchID == batchID }),
              let item = batch.items.first(where: { $0.itemID == itemID }) else { return }
        do {
            _ = try panoramaxQueueStore?.updateItemFavorite(batchID: batchID, itemID: itemID, isFavorite: !item.isFavorite)
            refreshPanoramaxBatches()
        } catch {
            panoramaxLastCaptureDetail = "Favorit konnte nicht gespeichert werden"
        }
    }

    private func enforcePanoramaxStorageLimit() {
        panoramaxStorageLimitGeneration &+= 1
        let storageGeneration = panoramaxStorageLimitGeneration
        panoramaxStorageLimitTask?.cancel()
        guard !panoramaxUnlimitedStorage, let store = panoramaxQueueStore else {
            panoramaxStorageLimitTask = nil
            return
        }
        let maxBytes = Int64(panoramaxStorageLimitMB * 1_000_000)
        panoramaxStorageLimitTask = Task { @MainActor [weak self] in
            // Slider updates arrive in bursts. Debounce them so a transient
            // lower value cannot evict images after the user chose a larger
            // limit or switched to unlimited storage.
            do {
                try await Task.sleep(nanoseconds: 250_000_000)
            } catch {
                return
            }
            guard let self,
                  storageGeneration == panoramaxStorageLimitGeneration,
                  !panoramaxUnlimitedStorage else { return }
            let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
            let result = await PanoramaxQueueMaintenanceExecutor.shared.enforceStorageLimit(
                store: store,
                maxBytes: maxBytes
            )
            guard !Task.isCancelled,
                  storageGeneration == panoramaxStorageLimitGeneration else { return }
            applyPanoramaxMaintenanceResult(
                result,
                publicationGeneration: publicationGeneration
            )
            panoramaxStorageLimitTask = nil
        }
    }

    func deletePanoramaxItem(batchID: String, itemID: String) {
        guard canProcessPanoramaxUploads,
              !activePanoramaxUploadBatchIDs.contains(batchID),
              let store = panoramaxQueueStore else { return }
        Task { @MainActor [weak self] in
            guard let self else { return }
            let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
            let result = await PanoramaxQueueMaintenanceExecutor.shared.deleteItems(
                store: store,
                itemIDsByBatch: [batchID: [itemID]]
            )
            applyPanoramaxMaintenanceResult(
                result,
                publicationGeneration: publicationGeneration
            )
        }
    }

    func deletePanoramaxSelections(_ selections: [(batchID: String, itemID: String)]) {
        guard canProcessPanoramaxUploads, let store = panoramaxQueueStore else { return }
        let selectionsByBatch = Dictionary(grouping: selections, by: { $0.batchID })
        let deletable = selectionsByBatch.reduce(into: [String: Set<String>]()) { result, entry in
            guard !activePanoramaxUploadBatchIDs.contains(entry.key) else { return }
            result[entry.key] = Set(entry.value.map(\.itemID))
        }
        guard !deletable.isEmpty else { return }
        Task { @MainActor [weak self] in
            guard let self else { return }
            let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
            let result = await PanoramaxQueueMaintenanceExecutor.shared.deleteItems(
                store: store,
                itemIDsByBatch: deletable
            )
            applyPanoramaxMaintenanceResult(
                result,
                publicationGeneration: publicationGeneration
            )
        }
    }

    private func notePanoramaxCleanupFailures(_ failedPaths: [String]) {
        guard !failedPaths.isEmpty else { return }
        panoramaxMaintenanceIssue = String(
            format: NSLocalizedString("panoramax.gallery.cleanup_failed", comment: ""),
            failedPaths.count
        )
    }

    private func startPanoramaxQueueMaintenance() {
        guard let store = panoramaxQueueStore else { return }
        panoramaxQueueMaintenanceInProgress = true
        panoramaxQueueMaintenanceGeneration &+= 1
        let generation = panoramaxQueueMaintenanceGeneration
        let deleteCompletedUploads = panoramaxDeleteUploadedImages
        panoramaxQueueMaintenanceTask = Task { @MainActor [weak self] in
            guard let self else { return }
            let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
            let result = await PanoramaxQueueMaintenanceExecutor.shared.runStartup(
                store: store,
                deleteCompletedUploads: deleteCompletedUploads
            )
            applyPanoramaxMaintenanceResult(
                result,
                publicationGeneration: publicationGeneration
            )
            if generation == panoramaxQueueMaintenanceGeneration {
                panoramaxQueueMaintenanceInProgress = false
                panoramaxQueueMaintenanceTask = nil
            }
        }
    }

    /// Applies or retries the opt-in retention policy to batches whose remote
    /// processing already completed. Disk scanning/deletion runs on the shared
    /// serial maintenance actor, never on SwiftUI's main actor.
    private func retryCompletedPanoramaxRetention() {
        guard panoramaxDeleteUploadedImages, let store = panoramaxQueueStore else { return }
        panoramaxQueueMaintenanceInProgress = true
        panoramaxQueueMaintenanceGeneration &+= 1
        let generation = panoramaxQueueMaintenanceGeneration
        panoramaxQueueMaintenanceTask = Task { @MainActor [weak self] in
            guard let self else { return }
            let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
            let result = await PanoramaxQueueMaintenanceExecutor.shared.retryCompletedRetention(store: store)
            applyPanoramaxMaintenanceResult(
                result,
                publicationGeneration: publicationGeneration
            )
            if generation == panoramaxQueueMaintenanceGeneration {
                panoramaxQueueMaintenanceInProgress = false
                panoramaxQueueMaintenanceTask = nil
            }
        }
    }

    private func nextPanoramaxBatchPublicationGeneration() -> UInt64 {
        panoramaxBatchPublicationGeneration &+= 1
        return panoramaxBatchPublicationGeneration
    }

    private func applyPanoramaxMaintenanceResult(
        _ result: PanoramaxQueueMaintenanceResult,
        publicationGeneration: UInt64
    ) {
        if let startup = result.startupCleanup, startup.hasFailures {
            notePanoramaxCleanupFailures(startup.failedRelativePaths)
        }
        notePanoramaxCleanupFailures(result.deletion.failedRelativePaths)
        guard publicationGeneration == panoramaxBatchPublicationGeneration,
              result.batchLoadSucceeded else { return }
        panoramaxBatches = result.batches
    }

    func approvePanoramaxBatch(batchID: String) {
        guard canProcessPanoramaxUploads else {
            panoramaxUploadStatusByBatch[batchID] = "Upload erst nach Ende der Aufnahme bearbeiten"
            return
        }
        do {
            guard var batch = try panoramaxQueueStore?.getBatch(batchID) else { return }
            guard batch.state == .awaitingReview else { return }
            batch.items = batch.items.map { item in
                guard item.state == .captured else { return item }
                var included = item
                included.state = .included
                return included
            }
            guard batch.items.contains(where: { $0.state == .included || $0.state == .retryableError }) else {
                panoramaxUploadStatusByBatch[batchID] = "Keine Bilder ausgewaehlt"
                return
            }
            batch.state = .approved
            try panoramaxQueueStore?.updateBatch(batch)
            refreshPanoramaxBatches()
        } catch {
            panoramaxLastCaptureDetail = "Batch konnte nicht freigegeben werden"
        }
    }

    func panoramaxUploadStatus(for batchID: String) -> String? {
        panoramaxUploadStatusByBatch[batchID]
    }

    var panoramaxAggregateUploadProgress: PanoramaxUploadProgress? {
        let active = activePanoramaxUploadBatchIDs.compactMap { panoramaxUploadProgressByBatch[$0] }
        guard !active.isEmpty else { return nil }
        let completed = active.reduce(0) { $0 + $1.completedItems }
        let total = active.reduce(0) { $0 + $1.totalItems }
        let phase: PanoramaxUploadProgress.Phase
        if active.contains(where: { $0.phase == .stopping }) {
            phase = .stopping
        } else if active.contains(where: { $0.phase == .uploading }) {
            phase = .uploading
        } else if active.contains(where: { $0.phase == .processing }) {
            phase = .processing
        } else {
            phase = .preparing
        }
        return PanoramaxUploadProgress(completedItems: completed, totalItems: total, phase: phase)
    }

    var panoramaxUploadIsReady: Bool {
        panoramaxAccount.isConnected && panoramaxAccount.normalizedOrigin != nil && panoramaxAccount.tokenForUpload() != nil
    }

    /// Applies the gallery selection to each affected batch, then starts the existing
    /// upload-set workflow. Unselected, non-terminal items are explicitly excluded.
    func uploadPanoramaxSelections(_ selections: [(batchID: String, itemID: String)]) {
        guard canProcessPanoramaxUploads else {
            for batchID in Set(selections.map(\.batchID)) {
                panoramaxUploadStatusByBatch[batchID] = "Upload erst nach Ende der Aufnahme starten"
            }
            return
        }
        guard panoramaxUploadIsReady, let store = panoramaxQueueStore else { return }
        let selectedByBatch = Dictionary(grouping: selections, by: { $0.batchID })
        for (batchID, selected) in selectedByBatch {
            guard !activePanoramaxUploadBatchIDs.contains(batchID) else { continue }
            let loadedBatch: PanoramaxBatchRecord?
            do {
                loadedBatch = try store.getBatch(batchID)
            } catch {
                panoramaxUploadStatusByBatch[batchID] = "Auswahl konnte nicht gelesen werden"
                continue
            }
            guard let loadedBatch,
                  DriveRecorderPolicy.canEditPanoramaxSelection(in: loadedBatch.state) else { continue }
            var batch = loadedBatch
            let editableIDs = Set(batch.items.filter { DriveRecorderPolicy.canSelectPanoramaxItem(in: $0.state) }.map(\.itemID))
            let selectedIDs = Set(selected.map(\.itemID)).intersection(editableIDs)
            guard !selectedIDs.isEmpty else { continue }
            batch.items = batch.items.map { item in
                guard editableIDs.contains(item.itemID) else { return item }
                var updated = item
                updated.state = selectedIDs.contains(item.itemID) ? .queued : .excluded
                return updated
            }
            batch.state = .approved
            do {
                try store.updateBatch(batch)
            } catch {
                panoramaxUploadStatusByBatch[batchID] = "Auswahl konnte nicht gespeichert werden"
                continue
            }
            uploadPanoramaxBatch(batchID: batchID)
        }
        refreshPanoramaxBatches()
    }

    func uploadPanoramaxBatch(batchID: String) {
        guard canProcessPanoramaxUploads else {
            panoramaxUploadStatusByBatch[batchID] = "Upload erst nach Ende der Aufnahme starten"
            return
        }
        guard let origin = panoramaxAccount.normalizedOrigin,
              let token = panoramaxAccount.tokenForUpload() else {
            panoramaxUploadStatusByBatch[batchID] = "Panoramax-Konto verbinden und bestaetigen"
            return
        }
        guard let store = panoramaxQueueStore else {
            panoramaxUploadStatusByBatch[batchID] = "Batch zuerst fuer Upload freigeben"
            return
        }
        guard panoramaxUploadTasks[batchID] == nil else {
            panoramaxUploadStatusByBatch[batchID] = "Upload fuer diesen Batch laeuft bereits"
            return
        }
        let loadedBatch: PanoramaxBatchRecord?
        do {
            loadedBatch = try store.getBatch(batchID)
        } catch {
            panoramaxUploadStatusByBatch[batchID] = "Batch konnte nicht gelesen werden"
            return
        }
        guard var batch = loadedBatch,
              DriveRecorderPolicy.canStartPanoramaxUpload(for: batch.state) else {
            panoramaxUploadStatusByBatch[batchID] = "Batch zuerst fuer Upload freigeben"
            return
        }
        let selected = batch.items.filter {
            $0.state == .queued || $0.state == .included || $0.state == .retryableError
        }
        let previouslyUploadedCount = batch.items.filter {
            $0.state == .uploaded || $0.state == .accepted || $0.state == .duplicate
        }.count
        let canResumeRemoteSet = DriveRecorderPolicy.canResumePanoramaxRemoteSet(
            batchState: batch.state,
            remoteUploadSetID: batch.remoteUploadSetID,
            itemStates: batch.items.map(\.state)
        )
        guard !selected.isEmpty || canResumeRemoteSet || batch.state == .processing else {
            panoramaxUploadStatusByBatch[batchID] = "Keine Bilder ausgewaehlt"
            return
        }
        if batch.state != .processing {
            batch.state = batch.remoteUploadSetID == nil ? .creatingUploadSet : .uploading
        }
        batch.instanceOrigin = origin.absoluteString
        do {
            try store.updateBatch(batch)
        } catch {
            panoramaxUploadStatusByBatch[batchID] = "Upload-Status konnte nicht gespeichert werden"
            return
        }
        refreshPanoramaxBatches()
        panoramaxUploadStatusByBatch[batchID] = "Upload wird vorbereitet"
        panoramaxUploadProgressByBatch[batchID] = PanoramaxUploadProgress(
            completedItems: previouslyUploadedCount,
            totalItems: previouslyUploadedCount + selected.count,
            phase: .preparing
        )

        activePanoramaxUploadBatchIDs.insert(batchID)
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                panoramaxUploadTasks[batchID] = nil
                activePanoramaxUploadBatchIDs.remove(batchID)
                panoramaxUploadProgressByBatch[batchID] = nil
            }
            do {
                try await performPanoramaxUpload(
                    batchID: batchID,
                    initialBatch: batch,
                    selected: selected,
                    previouslyUploadedCount: previouslyUploadedCount,
                    origin: origin,
                    token: token,
                    store: store
                )
            } catch {
                handlePanoramaxUploadFailure(batchID: batchID, error: error, store: store)
            }
        }
        panoramaxUploadTasks[batchID] = task
    }

    func isPanoramaxUploadActive(batchID: String) -> Bool {
        activePanoramaxUploadBatchIDs.contains(batchID)
    }

    private func performPanoramaxUpload(
        batchID: String,
        initialBatch: PanoramaxBatchRecord,
        selected: [PanoramaxItemRecord],
        previouslyUploadedCount: Int,
        origin: URL,
        token: String,
        store: PanoramaxQueueStore
    ) async throws {
        let client = PanoramaxUploadClient(origin: origin, token: token)
        var uploadSetID = initialBatch.remoteUploadSetID

        if initialBatch.state == .processing {
            guard let uploadSetID else { throw PanoramaxProcessingError.missingRemoteUploadSet }
            panoramaxUploadProgressByBatch[batchID] = PanoramaxUploadProgress(
                completedItems: previouslyUploadedCount,
                totalItems: previouslyUploadedCount,
                phase: .processing
            )
            try requirePanoramaxProcessingAllowed()
            do {
                _ = try await client.pollUntilReady(uploadSetID: uploadSetID)
                try await finishPanoramaxUpload(batchID: batchID, store: store)
            } catch PanoramaxUploadClient.UploadError.timedOut {
                panoramaxUploadStatusByBatch[batchID] = "Upload uebertragen – Verarbeitung laeuft weiter"
            }
            return
        }

        if uploadSetID == nil {
            try requirePanoramaxProcessingAllowed()
            let title = "YouSpeed \(initialBatch.createdAt.formatted(date: .abbreviated, time: .shortened))"
            let uploadSet = try await client.createUploadSet(
                title: title,
                estimatedFileCount: max(selected.count, 1)
            )
            uploadSetID = uploadSet.id
            guard var current = try store.getBatch(batchID) else { return }
            current.remoteUploadSetID = uploadSet.id
            current.state = .uploading
            try store.updateBatch(current)
            refreshPanoramaxBatches()
            // Persist a server ID that was already created even if a drive-start
            // cancellation arrived while the response was in flight. The next
            // network boundary remains blocked, and retry will reuse this set.
            try requirePanoramaxProcessingAllowed()
        }

        guard let uploadSetID else { throw PanoramaxProcessingError.missingRemoteUploadSet }
        let total = previouslyUploadedCount + selected.count
        panoramaxUploadStatusByBatch[batchID] = "\(previouslyUploadedCount)/\(total) Bilder werden uebertragen"
        var uploaded = previouslyUploadedCount
        panoramaxUploadProgressByBatch[batchID] = PanoramaxUploadProgress(
            completedItems: uploaded,
            totalItems: total,
            phase: .uploading
        )
        for item in selected {
            try requirePanoramaxProcessingAllowed()
            guard let fileURL = panoramaxOriginalURL(for: item) else { continue }
            do {
                try await client.upload(
                    file: fileURL,
                    uploadSetID: uploadSetID,
                    fileName: "\(item.itemID).jpg",
                    beforeRequest: {
                        try Task.checkCancellation()
                        // Persist the in-flight marker only after multipart
                        // preparation and limiter waiting, immediately before
                        // the transport can put bytes on the wire.
                        try store.updateItem(
                            batchID: batchID,
                            itemID: item.itemID,
                            state: .uploading
                        )
                    }
                )
            } catch {
                let durableState: PanoramaxItemState? = {
                    do {
                        return try store.getBatch(batchID)?
                            .items.first(where: { $0.itemID == item.itemID })?
                            .state
                    } catch {
                        return nil
                    }
                }()
                // A preparation/permit cancellation never reached the
                // before-request hook, so its queued item must stay retryable.
                // Only an item durably marked in flight has an outcome to
                // classify or quarantine.
                if durableState == .uploading {
                    _ = try? store.updateItem(
                        batchID: batchID,
                        itemID: item.itemID,
                        state: PanoramaxUploadClient.durableItemStateAfterUploadFailure(
                            error,
                            taskIsCancelled: Task.isCancelled
                        )
                    )
                }
                refreshPanoramaxBatches()
                throw error
            }
            // A successful response is durable evidence that this original was
            // accepted. Record it before observing cancellation so a later retry
            // cannot duplicate a file that Panoramax already received.
            // A failed commit deliberately leaves `.uploading`; startup repair
            // quarantines that unknown remote outcome as `.abandoned`.
            try store.updateItem(batchID: batchID, itemID: item.itemID, state: .uploaded)
            uploaded += 1
            panoramaxUploadStatusByBatch[batchID] = "\(uploaded)/\(total) Bilder uebertragen"
            panoramaxUploadProgressByBatch[batchID] = PanoramaxUploadProgress(
                completedItems: uploaded,
                totalItems: total,
                phase: .uploading
            )
            refreshPanoramaxBatches()
            try requirePanoramaxProcessingAllowed()
        }

        guard var current = try store.getBatch(batchID) else { return }
        let remaining = current.items.filter {
            $0.state == .queued || $0.state == .included || $0.state == .retryableError
        }
        if !remaining.isEmpty {
            current.state = .partial
            try store.updateBatch(current)
            refreshPanoramaxBatches()
            panoramaxUploadStatusByBatch[batchID] = "\(uploaded)/\(total) uebertragen – erneut versuchen"
            return
        }

        try requirePanoramaxProcessingAllowed()
        _ = try await client.complete(uploadSetID: uploadSetID)
        current = try store.getBatch(batchID) ?? current
        current.state = .processing
        try store.updateBatch(current)
        refreshPanoramaxBatches()
        panoramaxUploadStatusByBatch[batchID] = "Panoramax verarbeitet den Batch"
        panoramaxUploadProgressByBatch[batchID] = PanoramaxUploadProgress(
            completedItems: uploaded,
            totalItems: total,
            phase: .processing
        )
        // Completion has already reached the server. Persist that transition
        // before cancellation, then prohibit the next polling request.
        try requirePanoramaxProcessingAllowed()
        do {
            _ = try await client.pollUntilReady(uploadSetID: uploadSetID)
            try await finishPanoramaxUpload(batchID: batchID, store: store)
        } catch PanoramaxUploadClient.UploadError.timedOut {
            panoramaxUploadStatusByBatch[batchID] = "Upload uebertragen – Verarbeitung laeuft weiter"
        }
    }

    /// Finalizes the remote set before applying local retention. This ordering
    /// preserves the accepted-item ledger for resume until Panoramax confirms
    /// that server-side processing is complete.
    private func finishPanoramaxUpload(batchID: String, store: PanoramaxQueueStore) async throws {
        let publicationGeneration = nextPanoramaxBatchPublicationGeneration()
        let result = try await PanoramaxQueueMaintenanceExecutor.shared.finalizeRemoteCompletion(
            store: store,
            batchID: batchID,
            deleteUploadedImages: panoramaxDeleteUploadedImages
        )
        let cleanupFailures = result.deletion.failedRelativePaths
        applyPanoramaxMaintenanceResult(
            result,
            publicationGeneration: publicationGeneration
        )
        panoramaxUploadStatusByBatch[batchID] = cleanupFailures.isEmpty
            ? "Upload abgeschlossen"
            : "Upload abgeschlossen – lokale Dateien konnten nicht vollstaendig entfernt werden"
    }

    private func requirePanoramaxProcessingAllowed() throws {
        guard !Task.isCancelled, canProcessPanoramaxUploads else {
            throw CancellationError()
        }
    }

    private func handlePanoramaxUploadFailure(
        batchID: String,
        error: Error,
        store: PanoramaxQueueStore
    ) {
        let wasCancelled = Task.isCancelled
            || error is CancellationError
            || (error as? URLError)?.code == .cancelled
        do {
            // This also handles a persistence failure after a successful
            // server response: any item still durably `.uploading` has an
            // unknown remote outcome and must be quarantined immediately,
            // regardless of the error that brought us here.
            _ = try store.abandonInFlightItems(batchID: batchID)
            refreshPanoramaxBatches()
        } catch {
            panoramaxUploadStatusByBatch[batchID] =
                "Upload beendet; sicherer Status konnte nicht gespeichert werden"
            refreshPanoramaxBatches()
            return
        }
        panoramaxUploadStatusByBatch[batchID] = wasCancelled
            ? "Upload gestoppt; wartende Bilder bleiben vorgemerkt"
            : "Upload fehlgeschlagen: \(error.localizedDescription)"
        refreshPanoramaxBatches()
    }

    func stopPanoramaxUploads() {
        stopPanoramaxUploads(status: "Upload wird gestoppt")
    }

    private func cancelPanoramaxUploadsForRecorderStart() {
        stopPanoramaxUploads(status: "Upload fuer die Fahrtaufnahme pausiert")
    }

    private func stopPanoramaxUploads(status: String) {
        for (batchID, task) in panoramaxUploadTasks {
            _ = try? panoramaxQueueStore?.abandonInFlightItems(batchID: batchID)
            if let progress = panoramaxUploadProgressByBatch[batchID] {
                panoramaxUploadProgressByBatch[batchID] = PanoramaxUploadProgress(
                    completedItems: progress.completedItems,
                    totalItems: progress.totalItems,
                    phase: .stopping
                )
            }
            task.cancel()
            panoramaxUploadStatusByBatch[batchID] = status
        }
        refreshPanoramaxBatches()
    }

    private enum PanoramaxProcessingError: LocalizedError {
        case missingRemoteUploadSet

        var errorDescription: String? {
            "Panoramax-Upload-ID fehlt"
        }
    }

    var isScreenshotMode: Bool {
        appScreenshotState != nil
    }

    var isSyncingNow: Bool {
        startupTask != nil || syncTask != nil || syncStatus == "syncing" || syncStatus == "bootstrapping"
    }

    var configuredManifestEndpointCount: Int {
        manifestEndpoints.count
    }

    var configuredManifestCountryCodes: String {
        let codes = Set(
            manifestEndpoints
                .map { $0.countryCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() }
                .filter { !$0.isEmpty && $0 != "UNK" }
        )
        if codes.isEmpty {
            return "n/a"
        }
        return codes.sorted().joined(separator: ", ")
    }

    var activeDatabaseFileName: String {
        guard !activeDBPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return "n/a"
        }
        return URL(fileURLWithPath: activeDBPath).lastPathComponent
    }

    var activeDatabaseOriginLabel: String {
        guard !activeDBPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return "none"
        }
        if activeBundleVersion.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "seed" {
            return "seed"
        }
        if activeDBPath.contains("/bundles/") {
            return "downloaded"
        }
        return "embedded"
    }

    func isBundleDownloaded(_ option: BundleDownloadOption) -> Bool {
        let primaryRegion = normalizedManifestRegion(option.endpoint.manifestRegion)
        if downloadedBundleCountByRegion[primaryRegion, default: 0] > 0 {
            return true
        }
        let countryRegion = countryManifestRegionToken(for: option)
        if countryRegion != primaryRegion,
           downloadedBundleCountByRegion[countryRegion, default: 0] > 0 {
            return true
        }
        return false
    }

    func downloadedBundleStatusText(_ option: BundleDownloadOption) -> String {
        let primaryRegion = normalizedManifestRegion(option.endpoint.manifestRegion)
        let countryRegion = countryManifestRegionToken(for: option)

        let count: Int
        let latest: String
        if downloadedBundleCountByRegion[primaryRegion, default: 0] > 0 {
            count = downloadedBundleCountByRegion[primaryRegion, default: 0]
            latest = downloadedBundleLatestVersionByRegion[primaryRegion] ?? "n/a"
        } else if countryRegion != primaryRegion, downloadedBundleCountByRegion[countryRegion, default: 0] > 0 {
            count = downloadedBundleCountByRegion[countryRegion, default: 0]
            latest = downloadedBundleLatestVersionByRegion[countryRegion] ?? "n/a"
        } else {
            let size = bundleSizeText(for: option)
            return size.isEmpty ? "" : "Dateigroesse: \(size)"
        }

        if count == 1 {
            return "Installiert (\(latest))"
        }
        return "Installiert (\(count)x, neueste \(latest))"
    }

    func bundleSizeText(for option: BundleDownloadOption) -> String {
        let primaryRegion = normalizedManifestRegion(option.endpoint.manifestRegion)
        let countryRegion = countryManifestRegionToken(for: option)
        if let bytes = expectedBundleBytesByRegion[primaryRegion], bytes > 0 {
            return formatBytes(bytes)
        }
        if countryRegion != primaryRegion, let bytes = expectedBundleBytesByRegion[countryRegion], bytes > 0 {
            return formatBytes(bytes)
        }
        return ""
    }

    var hasActiveBundleDownload: Bool {
        guard let activeDownloadOptionID,
              !activeDownloadOptionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return false
        }
        return syncStatus == "syncing" || syncTask != nil
    }

    func isActiveBundleDownload(_ option: BundleDownloadOption) -> Bool {
        hasActiveBundleDownload && activeDownloadOptionID == option.id
    }

    func activeBundleDownloadProgress(_ option: BundleDownloadOption) -> Double? {
        guard isActiveBundleDownload(option) else {
            return nil
        }
        let total = max(syncProgressTotalBytes, 0)
        guard total > 0 else {
            return nil
        }
        let completed = min(max(syncProgressCompletedBytes, 0), total)
        return Double(completed) / Double(total)
    }

    func activeBundleDownloadBytesText(_ option: BundleDownloadOption) -> String {
        guard isActiveBundleDownload(option) else {
            return ""
        }
        let completed = max(syncProgressCompletedBytes, 0)
        let total = max(syncProgressTotalBytes, 0)
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        if total > 0 {
            return "\(formatter.string(fromByteCount: completed)) / \(formatter.string(fromByteCount: total))"
        }
        if completed > 0 {
            return formatter.string(fromByteCount: completed)
        }
        return ""
    }

    func downloadSelectedBundle(_ option: BundleDownloadOption) {
        guard startupTask == nil else {
            let message = "Download blockiert: Startup-Datenvorbereitung laeuft noch."
            syncProgressDetail = message
            maintenanceMessage = message
            Self.logger.notice("download_selected blocked reason=startup_task_running bundle=\(option.displayName, privacy: .public)")
            return
        }
        guard syncTask == nil else {
            let message = "Download blockiert: Es laeuft bereits eine Synchronisierung."
            syncProgressDetail = message
            maintenanceMessage = message
            Self.logger.notice("download_selected blocked reason=sync_already_running bundle=\(option.displayName, privacy: .public)")
            return
        }
        activeDownloadOptionID = option.id
        syncTask = Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            beginSyncBackgroundTask()
            defer {
                endSyncBackgroundTask()
                activeDownloadOptionID = nil
                syncTask = nil
            }
            do {
                lastError = ""
                syncProgressStage = "preparing"
                syncProgressDetail = "Preparing sync"
                syncProgressCompletedBytes = 0
                syncProgressTotalBytes = 0
                syncProgressBytesPerSecond = 0
                syncProgressETASeconds = nil
                syncPartDownloads = []
                maintenanceMessage = "Download gestartet: \(option.displayName)"
                Self.logger.notice(
                    "download_selected start bundle=\(option.displayName, privacy: .public) region=\(option.endpoint.manifestRegion, privacy: .public) url=\(option.endpoint.manifestURL.absoluteString, privacy: .public)"
                )

                syncStatus = "syncing"

                let sync: BundleSyncResult
                sync = try await bundleManager.syncFromManifestURL(option.endpoint.manifestURL) { progress in
                    Task { @MainActor [weak self] in
                        self?.applySyncProgress(progress)
                    }
                }
                invalidateTrafficSignOverrideIfBundleWillChange(
                    bundleVersion: sync.bundleVersion,
                    dbPath: sync.dbPath
                )
                activeBundleVersion = sync.bundleVersion
                activeDBPath = sync.dbPath
                speedLimitService = makeSpeedLimitService(
                    dbPath: sync.dbPath,
                    preferredCountryCode: option.countryCode
                )
                await applyPenaltyRulesForActiveBundle(preferredCountryCode: option.countryCode)
                syncStatus = "ready_\(sync.mode.rawValue)"
                syncProgressStage = "completed"
                syncProgressDetail = "Sync completed"
                syncProgressBytesPerSecond = 0
                syncProgressETASeconds = 0
                syncPartDownloads = []
                maintenanceMessage = "Bundle geladen: \(option.displayName) (\(sync.bundleVersion))"
                await refreshDownloadedBundleInventory()
            } catch {
                syncStatus = "sync_failed"
                syncProgressStage = "failed"
                syncProgressETASeconds = nil
                syncPartDownloads = []
                lastError = error.localizedDescription
                maintenanceMessage = "Download fehlgeschlagen: \(option.displayName) (\(error.localizedDescription))"
                Self.logger.error(
                    "download_selected failed bundle=\(option.displayName, privacy: .public) region=\(option.endpoint.manifestRegion, privacy: .public) error=\(error.localizedDescription, privacy: .public)"
                )
                if !activeDBPath.isEmpty {
                    speedLimitService = makeSpeedLimitService(dbPath: activeDBPath)
                    await applyPenaltyRulesForActiveBundle()
                }
            }
        }
    }

    func deleteSelectedBundle(_ option: BundleDownloadOption) {
        guard startupTask == nil else {
            maintenanceMessage = "Startup-Datenvorbereitung laeuft noch."
            return
        }
        guard syncTask == nil else {
            maintenanceMessage = "Synchronisierung laeuft bereits."
            return
        }
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let primaryRegion = normalizedManifestRegion(option.endpoint.manifestRegion)
                let countryRegion = countryManifestRegionToken(for: option)
                var removed = try await bundleManager.removeDownloadedBundles(forManifestRegion: primaryRegion)
                if removed == 0, countryRegion != primaryRegion {
                    removed = try await bundleManager.removeDownloadedBundles(forManifestRegion: countryRegion)
                }
                if removed > 0 {
                    let activeURL = try await bundleManager.activeDatabaseURL()
                    let activeExists = activeURL.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
                    if !activeExists {
                        let bootstrap = try await bundleManager.bootstrapSeedIfNeeded()
                        invalidateTrafficSignOverrideIfBundleWillChange(
                            bundleVersion: bootstrap.bundleVersion,
                            dbPath: bootstrap.dbPath
                        )
                        activeBundleVersion = bootstrap.bundleVersion
                        activeDBPath = bootstrap.dbPath
                        await applyPenaltyRulesForActiveBundle()
                        speedLimitService = bootstrap.dbPath.isEmpty ? nil : makeSpeedLimitService(dbPath: bootstrap.dbPath)
                        syncStatus = "ready_\(bootstrap.mode.rawValue)"
                    }
                    maintenanceMessage = "Bundle geloescht: \(option.displayName)"
                } else {
                    maintenanceMessage = "Kein heruntergeladenes Bundle gefunden: \(option.displayName)"
                }
                await refreshDownloadedBundleInventory()
            } catch {
                let text = "Bundle konnte nicht geloescht werden: \(error.localizedDescription)"
                maintenanceMessage = text
                lastError = text
            }
        }
    }

    var isInSpeedCaptureMode: Bool {
        if case .idle = speedCaptureMode {
            return false
        }
        return true
    }

    var isTunnelModeActive: Bool {
        tunnelModeTracker.isTunnelModeActive
    }

    var isLowSpeedMatchingRuleActive: Bool {
        lastSelectionTrace.contains { $0.step == "low_speed_rule" }
    }

    var speedCaptureSignText: String? {
        switch speedCaptureMode {
        case .idle:
            return nil
        case .speakingPrompt, .listening, .evaluating, .saving:
            return "?"
        }
    }

    var speedCapturePrimaryMetricText: String? {
        switch speedCaptureMode {
        case .idle:
            return nil
        case .speakingPrompt, .listening:
            return NSLocalizedString("speed_capture.prompt.primary", comment: "")
        case .evaluating:
            return NSLocalizedString("speed_capture.evaluating.primary", comment: "")
        case .saving:
            return NSLocalizedString("speed_capture.saving.primary", comment: "")
        }
    }

    var speedCaptureSecondaryMetricText: String? {
        switch speedCaptureMode {
        case .idle:
            return nil
        case .speakingPrompt, .listening:
            return NSLocalizedString("speed_capture.prompt.secondary", comment: "")
        case .evaluating:
            return NSLocalizedString("speed_capture.evaluating.secondary", comment: "")
        case .saving:
            return NSLocalizedString("speed_capture.saving.secondary", comment: "")
        }
    }

    func bootstrapAndSync() {
        activeDownloadOptionID = nil
        guard startupTask == nil else {
            let message = "Synchronisierung blockiert: Startup-Datenvorbereitung laeuft noch."
            syncProgressDetail = message
            maintenanceMessage = message
            Self.logger.notice("sync_request rejected reason=startup_task_running")
            return
        }
        guard syncTask == nil else {
            let message = "Synchronisierung laeuft bereits."
            syncProgressDetail = message
            maintenanceMessage = message
            Self.logger.notice("sync_request ignored reason=sync_already_running")
            return
        }
        Self.logger.notice("sync begin")
        syncTask = Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            beginSyncBackgroundTask()
            defer {
                endSyncBackgroundTask()
                syncTask = nil
            }
            do {
                lastError = ""
                syncProgressStage = "preparing"
                syncProgressDetail = "Preparing sync"
                syncProgressCompletedBytes = 0
                syncProgressTotalBytes = 0
                syncProgressBytesPerSecond = 0
                syncProgressETASeconds = nil
                syncPartDownloads = []
                lastDownloadProgressAt = nil
                lastDownloadProgressBytes = nil
                syncStatus = "bootstrapping"
                let bootstrap = try await bundleManager.bootstrapSeedIfNeeded()
                invalidateTrafficSignOverrideIfBundleWillChange(
                    bundleVersion: bootstrap.bundleVersion,
                    dbPath: bootstrap.dbPath
                )
                activeBundleVersion = bootstrap.bundleVersion
                activeDBPath = bootstrap.dbPath
                Self.logger.notice(
                    "sync bootstrap_ready version=\(bootstrap.bundleVersion, privacy: .public) db=\(bootstrap.dbPath, privacy: .public)"
                )

                guard !manifestEndpoints.isEmpty else {
                    syncStatus = "seed_only"
                    if !activeDBPath.isEmpty {
                        await applyPenaltyRulesForActiveBundle()
                        speedLimitService = makeSpeedLimitService(dbPath: activeDBPath)
                    }
                    Self.logger.notice("sync seed_only no_manifest_endpoint")
                    return
                }

                syncStatus = "syncing"
                let preferredCountryCode = normalizedCountryCode(activePenaltyRules.countryCode)
                    ?? inferCountryCodeFromDBPath(activeDBPath)
                    ?? "DEU"
                Self.logger.notice(
                    "sync endpoints run preferred_country=\(preferredCountryCode, privacy: .public) endpoint_count=\(manifestEndpoints.count, privacy: .public)"
                )
                let sync = try await bundleManager.syncFromManifestEndpoints(
                    manifestEndpoints,
                    preferredCountryCode: preferredCountryCode
                ) { progress in
                    Task { @MainActor [weak self] in
                        self?.applySyncProgress(progress)
                    }
                }
                invalidateTrafficSignOverrideIfBundleWillChange(
                    bundleVersion: sync.bundleVersion,
                    dbPath: sync.dbPath
                )
                activeBundleVersion = sync.bundleVersion
                activeDBPath = sync.dbPath
                await applyPenaltyRulesForActiveBundle()
                speedLimitService = makeSpeedLimitService(dbPath: sync.dbPath)
                syncStatus = "ready_\(sync.mode.rawValue)"
                syncProgressStage = "completed"
                syncProgressDetail = "Sync completed"
                syncProgressBytesPerSecond = 0
                syncProgressETASeconds = 0
                syncPartDownloads = []
                lastError = ""
                await refreshDownloadedBundleInventory()
                Self.logger.notice(
                    "sync success mode=\(sync.mode.rawValue, privacy: .public) version=\(sync.bundleVersion, privacy: .public) db=\(sync.dbPath, privacy: .public)"
                )
            } catch {
                syncStatus = "sync_failed"
                syncProgressStage = "failed"
                syncProgressETASeconds = nil
                syncPartDownloads = []
                lastError = error.localizedDescription
                if !activeDBPath.isEmpty {
                    await applyPenaltyRulesForActiveBundle()
                    speedLimitService = makeSpeedLimitService(dbPath: activeDBPath)
                }
                Self.logger.error("sync failed error=\(error.localizedDescription, privacy: .public)")
            }
        }
    }

    func flushLocalContributionsAndResync() {
        guard startupTask == nil else {
            syncProgressDetail = "Startup data preparation is still running"
            Self.logger.notice("maintenance_flush rejected reason=startup_task_running")
            return
        }
        guard syncTask == nil else {
            syncProgressDetail = "Sync already in progress"
            Self.logger.notice("maintenance_flush rejected reason=sync_already_running")
            return
        }

        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let removed = try await bundleManager.flushLocalContributionState()
                resetWayMatchContinuity()
                let currentWayID = latestTrafficSignDetectionContext?.wayId
                    ?? limitWayID?.trimmingCharacters(in: .whitespacesAndNewlines)
                let removedCurrentRoadCorrection = currentWayID.map {
                    self.localSpeedOverridesByWayID[$0] != nil
                        || self.localSpeedOverrideValuesByWayID[$0] != nil
                        || self.localSpeedOverrideRevisionsByWayID[$0] != nil
                } ?? false
                localSpeedOverridesByWayID.removeAll(keepingCapacity: false)
                localSpeedOverrideValuesByWayID.removeAll(keepingCapacity: false)
                localSpeedOverrideRevisionsByWayID.removeAll(keepingCapacity: false)
                activeLocalSpeedCorrection = nil
                if removedCurrentRoadCorrection {
                    currentLocalCorrectionSpeedKmh = nil
                    currentBaseSpeedLimitDisplayText = nil
                    currentBaseUnlimitedSpeedLimitActive =
                        currentBundledUnlimitedSpeedLimitActive
                    invalidateTrafficSignOverrideForBaseSourceMutation()
                }
                maintenanceMessage = removed > 0
                    ? "Lokale Korrekturen geloescht (\(removed) Eintraege). Starte Synchronisierung."
                    : "Keine lokalen Korrekturen gefunden. Starte Synchronisierung."
                Self.logger.notice("maintenance_flush success removed=\(removed, privacy: .public)")
                bootstrapAndSync()
            } catch {
                let text = "Lokale Korrekturen konnten nicht geloescht werden: \(error.localizedDescription)"
                maintenanceMessage = text
                lastError = text
                Self.logger.error("maintenance_flush failed error=\(error.localizedDescription, privacy: .public)")
            }
        }
    }

    func deleteDownloadedBundlesKeepingSeed() {
        guard startupTask == nil else {
            maintenanceMessage = "Startup-Datenvorbereitung laeuft noch."
            return
        }
        guard syncTask == nil else {
            maintenanceMessage = "Synchronisierung laeuft bereits."
            return
        }

        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let removed = try await bundleManager.removeDownloadedBundlesKeepingSeed()
                let bootstrap = try await bundleManager.bootstrapSeedIfNeeded()
                invalidateTrafficSignOverrideIfBundleWillChange(
                    bundleVersion: bootstrap.bundleVersion,
                    dbPath: bootstrap.dbPath
                )
                activeBundleVersion = bootstrap.bundleVersion
                activeDBPath = bootstrap.dbPath
                await applyPenaltyRulesForActiveBundle()
                speedLimitService = bootstrap.dbPath.isEmpty ? nil : makeSpeedLimitService(dbPath: bootstrap.dbPath)
                syncStatus = "ready_\(bootstrap.mode.rawValue)"
                lastError = ""
                await refreshDownloadedBundleInventory()
                maintenanceMessage = removed > 0
                    ? "Heruntergeladene Datenbanken geloescht (\(removed)). Seed ist aktiv."
                    : "Keine heruntergeladene Datenbank gefunden. Seed ist aktiv."
                Self.logger.notice("maintenance delete_downloaded_bundles removed=\(removed, privacy: .public)")
            } catch {
                let text = "Heruntergeladene Datenbanken konnten nicht geloescht werden: \(error.localizedDescription)"
                maintenanceMessage = text
                lastError = text
                Self.logger.error("maintenance delete_downloaded_bundles failed error=\(error.localizedDescription, privacy: .public)")
            }
        }
    }

    private func ensureSeedBootstrapIfNeeded() {
        beginStartupDataLoadIfNeeded()
    }

    func retryStartupDataPreparation() {
        Self.logger.notice("startup retry requested")
        beginStartupDataLoadIfNeeded(force: true)
    }

    private func beginStartupDataLoadIfNeeded(force: Bool = false) {
        guard force || startupTask == nil else {
            Self.logger.notice("startup begin skipped reason=task_already_running")
            return
        }
        guard force || (speedLimitService == nil && activeDBPath.isEmpty) else {
            startupDataState = .ready
            startupProgress = 1
            startupDetail = "Lokale Daten sind bereit"
            Self.logger.notice("startup begin skipped reason=already_ready")
            return
        }

        startupTask?.cancel()
        Self.logger.notice("startup begin force=\(force, privacy: .public)")
        startupTask = Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            defer { startupTask = nil }

            startupDataState = .loading
            startupProgress = 0.02
            startupDetail = "Lokale Daten werden vorbereitet"
            if force {
                syncProgressDetail = ""
            }

            do {
                lastError = ""
                let recovered = try await bundleManager.recoverLocalDataAtStartup { detail, fraction in
                    Task { @MainActor [weak self] in
                        guard let self else {
                            return
                        }
                        startupDetail = detail
                        startupProgress = max(startupProgress, min(max(fraction, 0), 0.9))
                        if fraction >= 0.99 {
                            Self.logger.notice("startup progress detail=\(detail, privacy: .public) fraction=\(fraction, privacy: .public)")
                        }
                    }
                }

                let startupResult: BundleSyncResult
                if let recovered {
                    startupResult = recovered
                    Self.logger.notice(
                        "startup recovered_local mode=\(recovered.mode.rawValue, privacy: .public) version=\(recovered.bundleVersion, privacy: .public)"
                    )
                } else {
                    startupDetail = "Pruefe lokale Kartendaten"
                    startupProgress = max(startupProgress, Self.startupSeedActivationFloorProgress)
                    Self.logger.notice("startup no_local_data_fallback=none")
                    startupResult = try await bundleManager.bootstrapSeedIfNeeded()
                }

                invalidateTrafficSignOverrideIfBundleWillChange(
                    bundleVersion: startupResult.bundleVersion,
                    dbPath: startupResult.dbPath
                )
                activeBundleVersion = startupResult.bundleVersion
                activeDBPath = startupResult.dbPath
                if startupResult.dbPath.isEmpty {
                    speedLimitService = nil
                    syncStatus = "not_synced"
                    await refreshDownloadedBundleInventory()
                    startupProgress = 1
                    startupDetail = "Daten-Download erforderlich"
                    startupDataState = .ready
                    Self.logger.notice("startup ready no_local_database download_required=true")
                    return
                }
                await applyPenaltyRulesForActiveBundle()
                speedLimitService = makeSpeedLimitService(dbPath: startupResult.dbPath)
                syncStatus = "ready_\(startupResult.mode.rawValue)"
                await refreshDownloadedBundleInventory()
                startupProgress = 1
                startupDetail = "Datenbank ist bereit"
                startupDataState = .ready
                Self.logger.notice(
                    "startup ready mode=\(startupResult.mode.rawValue, privacy: .public) version=\(startupResult.bundleVersion, privacy: .public) db=\(startupResult.dbPath, privacy: .public)"
                )
            } catch {
                startupDataState = .failed
                startupProgress = min(startupProgress, 0.98)
                startupDetail = "Lokale Daten konnten nicht geladen werden"
                lastError = error.localizedDescription
                syncStatus = "sync_failed"
                Self.logger.error("startup failed error=\(error.localizedDescription, privacy: .public)")
            }
        }
    }

    private func configureForScreenshotMode(_ screenshotState: AppScreenshotState) {
        let fixture = screenshotState.fixture
        appScreenshotState = screenshotState
        driveStatus = "running"
        invalidateTrafficSignOverrideIfBundleWillChange(
            bundleVersion: "screenshot",
            dbPath: screenshotState.rawValue
        )
        activeBundleVersion = "screenshot"
        activeDBPath = screenshotState.rawValue
        currentSpeedKmh = fixture.currentSpeedKmh
        speedLimitKmh = fixture.speedLimitKmh
        speedLimitDisplayText = fixture.speedLimitDisplayText
        limitWayID = fixture.wayID
        limitStreetName = fixture.streetName
        limitCityName = fixture.cityName
        limitCityPlaceName = fixture.cityName
        limitCityDistrictName = nil
        lastError = ""
        currentLatitude = fixture.latitude
        currentLongitude = fixture.longitude
        gpsHorizontalAccuracyM = fixture.gpsHorizontalAccuracyM
        gpsSignalBars = fixture.gpsSignalBars
        lastLookupInsideCity = fixture.insideCity
        lastLookupCitySource = fixture.insideCity ? "residential_polygon" : "road_class"
        gpsFixCount = 24
        startupDataState = .ready
        startupProgress = 1
        startupDetail = "Screenshot mode"
        syncStatus = "ready_screenshot"
        syncProgressStage = "completed"
        syncProgressDetail = "Screenshot mode"
        isUnlimitedSpeedLimitActive = fixture.isUnlimitedSpeedLimitActive
        audioAlertsEnabled = false
        hideWelcomeScreen = true
        speedLimitService = nil
        bundleDownloadSections = buildBundleDownloadSections()
        downloadedBundleCountByRegion = [:]
        downloadedBundleLatestVersionByRegion = [:]
        expectedBundleBytesByRegion = [:]
    }

    private func beginSyncBackgroundTask() {
        guard syncBackgroundTaskID == .invalid else {
            return
        }
        syncBackgroundTaskID = UIApplication.shared.beginBackgroundTask(withName: "SpeedConsumerSync") { [weak self] in
            Task { @MainActor in
                guard let self else {
                    return
                }
                self.syncProgressDetail = "Background sync time expired"
                self.endSyncBackgroundTask()
            }
        }
    }

    private func endSyncBackgroundTask() {
        guard syncBackgroundTaskID != .invalid else {
            return
        }
        UIApplication.shared.endBackgroundTask(syncBackgroundTaskID)
        syncBackgroundTaskID = .invalid
    }

    private func applySyncProgress(_ progress: BundleSyncProgress) {
        let now = Date()
        let isTerminal = progress.stage == .completed
        if !isTerminal, now.timeIntervalSince(lastProgressUIUpdate) < 0.1 {
            return
        }
        lastProgressUIUpdate = now
        syncProgressStage = progress.stage.rawValue
        syncProgressDetail = progress.detail
        syncProgressCompletedBytes = max(0, progress.completedBytes)
        syncProgressTotalBytes = max(0, progress.totalBytes)
        syncPartDownloads = progress.partDownloads
        if progress.stage != .downloading && progress.stage != .assembling {
            syncPartDownloads = []
        }
        let signature = "\(progress.stage.rawValue)|\(progress.detail)"
        if signature != lastLoggedSyncProgressSignature {
            lastLoggedSyncProgressSignature = signature
            Self.logger.notice(
                "sync progress stage=\(progress.stage.rawValue, privacy: .public) detail=\(progress.detail, privacy: .public) completed=\(progress.completedBytes, privacy: .public) total=\(progress.totalBytes, privacy: .public)"
            )
        }
        updateDownloadRateAndETA(progress: progress, now: now)
    }

    private func updateDownloadRateAndETA(progress: BundleSyncProgress, now: Date) {
        guard progress.stage == .downloading else {
            lastDownloadProgressAt = nil
            lastDownloadProgressBytes = nil
            if progress.stage == .completed {
                syncProgressBytesPerSecond = 0
                syncProgressETASeconds = 0
            } else {
                syncProgressETASeconds = nil
            }
            return
        }

        let completed = max(0, progress.completedBytes)
        let total = max(0, progress.totalBytes)
        defer {
            lastDownloadProgressAt = now
            lastDownloadProgressBytes = completed
        }

        guard let previousAt = lastDownloadProgressAt,
              let previousBytes = lastDownloadProgressBytes else {
            syncProgressETASeconds = nil
            return
        }

        let deltaTime = now.timeIntervalSince(previousAt)
        let deltaBytes = completed - previousBytes
        guard deltaTime > 0.05 else {
            return
        }
        guard deltaBytes >= 0 else {
            syncProgressBytesPerSecond = 0
            syncProgressETASeconds = nil
            return
        }

        if deltaBytes > 0 {
            let instantaneousRate = Double(deltaBytes) / deltaTime
            if syncProgressBytesPerSecond <= 0 {
                syncProgressBytesPerSecond = instantaneousRate
            } else {
                syncProgressBytesPerSecond = (syncProgressBytesPerSecond * 0.75) + (instantaneousRate * 0.25)
            }
        }

        guard total > 0,
              syncProgressBytesPerSecond > 1,
              completed <= total else {
            syncProgressETASeconds = nil
            return
        }
        let remainingBytes = total - completed
        syncProgressETASeconds = Double(remainingBytes) / syncProgressBytesPerSecond
    }

    func startDriving() {
        if speedLimitService == nil && startupDataState != .ready {
            ensureSeedBootstrapIfNeeded()
        }
        isDriving = true
        isUnlimitedSpeedLimitActive = false
        resetDerivedSpeedTracking()
        resetTunnelModeTracking()
        driveStatus = "requesting_location"
        let auth = locationManager.authorizationStatus
        if auth == .notDetermined {
            locationManager.requestWhenInUseAuthorization()
        } else if auth == .authorizedWhenInUse || auth == .authorizedAlways {
            locationManager.startUpdatingLocation()
            driveStatus = "running"
        } else {
            driveStatus = "location_denied"
            lastError = "Location permission denied"
        }
    }

    func stopDriving() {
        isDriving = false
        driveCaptureCoordinator?.stop()
        locationManager.stopUpdatingLocation()
        latestTrafficSignDetectionContext = nil
        currentTrafficSignSourceSignature = nil
        trafficSignFrameContextIsCurrent = false
        latestTrafficSignLookupFixID = 0
        trafficSignContextGeneration &+= 1
        trafficSignFrameState.update(nil)
        trafficSignOverridePolicy.clear()
        trafficSignRecognitionActiveOverride = nil
        trafficSignRecognitionLastEvent = nil
        if trafficSignRecognitionEnabled {
            trafficSignRecognitionState = trafficSignRuntime == nil
                ? .unavailable
                : .noRecognition
        }
        resetDerivedSpeedTracking()
        driveStatus = "stopped"
        cancelSpeedCapture(reason: nil)
        isUnlimitedSpeedLimitActive = false
        resetTunnelModeTracking()
        lastAudioFeedbackAt = .distantPast
        lastAnnouncedSpeechText = nil
        wasDrivingBanWarningActive = false
        lastDrivingBanWarningAt = .distantPast
        resetWayMatchContinuity()
        activeLocalSpeedCorrection = nil
        limitStreetBaseName = nil
        limitStreetRef = nil
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
    }

    private func syncTunnelModePublishedState() {
        if tunnelModeState != tunnelModeTracker.state {
            tunnelModeState = tunnelModeTracker.state
        }
    }

    private func resetTunnelModeTracking() {
        tunnelModeTracker.reset()
        syncTunnelModePublishedState()
    }

    func resetDiagnostics() {
        lookupEventLog.removeAll(keepingCapacity: false)
        gpsFixCount = 0
        gpsHorizontalAccuracyM = nil
        gpsSignalBars = 0
        lastCandidateTraces.removeAll(keepingCapacity: false)
        lastSelectionTrace.removeAll(keepingCapacity: false)
        resetWayMatchContinuity()
        activeLocalSpeedCorrection = nil
        limitStreetBaseName = nil
        limitStreetRef = nil
        lastLookupStatus = "idle"
        lastLookupQueryMs = 0
        lastLookupCandidateCount = 0
        lastLookupSpeedCandidateCount = 0
        lastLookupNearestCandidateM = nil
        lastLookupNearestSpeedCandidateM = nil
        lastLookupInsideCity = nil
        lastLookupCitySource = "n/a"
        lastLookupCityResolveMs = 0
        lastLookupCityCandidateBoundaries = 0
        lastLookupCityContainingBoundaries = 0
        lastLookupCityPlaceCandidates = 0
        isUnlimitedSpeedLimitActive = false
        resetTunnelModeTracking()

        guard let logURL = prepareGPSLogFileIfNeeded() else {
            return
        }
        do {
            try Data(Self.gpsLogCSVHeader.utf8).write(to: logURL, options: .atomic)
            resetPreparedMatchLogFile()
            if let matchLogURL = prepareMatchLogFileIfNeeded() {
                try Data().write(to: matchLogURL, options: .atomic)
            }
        } catch {
            lastError = "gps log reset failed: \(error.localizedDescription)"
        }
    }

    func clearDrivingLogs() {
        do {
            if let gpsLogURL = prepareGPSLogFileIfNeeded() {
                try Data(Self.gpsLogCSVHeader.utf8).write(to: gpsLogURL, options: .atomic)
            }
            resetPreparedMatchLogFile()
            if let matchLogURL = prepareMatchLogFileIfNeeded() {
                try Data().write(to: matchLogURL, options: .atomic)
            }
            lastError = ""
        } catch {
            lastError = "driving log clear failed: \(error.localizedDescription)"
        }
    }

    private func clearDrivingLogsOnAppLaunch(fileManager: FileManager = .default) {
        do {
            let base = try V3BundleManager.applicationSupportDirectory(fileManager: fileManager)
            if !fileManager.fileExists(atPath: base.path) {
                try fileManager.createDirectory(at: base, withIntermediateDirectories: true)
            }

            let existingURLs = try fileManager.contentsOfDirectory(
                at: base,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            )
            for url in existingURLs where
                url.pathExtension == "ndjson" &&
                url.lastPathComponent.contains("drive_match_log") {
                try fileManager.removeItem(at: url)
            }

            hasPreparedGPSLogFile = false
            if let gpsLogURL = prepareGPSLogFileIfNeeded() {
                try Data(Self.gpsLogCSVHeader.utf8).write(to: gpsLogURL, options: .atomic)
            }
            resetPreparedMatchLogFile()
            if let matchLogURL = prepareMatchLogFileIfNeeded() {
                try Data().write(to: matchLogURL, options: .atomic)
            }
            lastError = ""
        } catch {
            lastError = "startup log clear failed: \(error.localizedDescription)"
        }
    }

    private func currentWayMatchContext() -> WayMatchContext? {
        guard previousMatchedWayID != nil ||
                !recentMatchedWayIDs.isEmpty ||
                !recentMatchedStreetRefs.isEmpty ||
                previousMatchedStreetName != nil ||
                !recentNearbyTunnelWayIDs.isEmpty ||
                !recentNearbyTunnelRefs.isEmpty ||
                !recentTunnelApproachWayIDs.isEmpty ||
                !recentTunnelApproachRefs.isEmpty ||
                tunnelApproachFixCount > 0 ||
                motorwayModeActive ||
                activeCorridorState != nil ||
                approachCorridorState != nil ||
                approachCorridorStartDepthM != nil ||
                approachCorridorStartDepthNodes != nil ||
                !recentMatchHypotheses.isEmpty ||
                !recentObservedFixes.isEmpty ||
                hadRecentGPSSignalLoss else {
            return nil
        }
        return WayMatchContext(
            preferredWayID: previousMatchedWayID,
            preferredHighway: previousMatchedHighway,
            preferredEndpointProximityM: previousMatchedEndpointProximityM,
            recentWayIDs: recentMatchedWayIDs,
            recentFixes: recentObservedFixes,
            sameRefUrbanReleaseStreak: sameRefUrbanReleaseStreak,
            preferredStreetRef: recentMatchedStreetRefs.first,
            activeStreetRef: previousMatchedStreetRef,
            preferredStreetName: previousMatchedStreetName,
            recentStreetRefs: recentMatchedStreetRefs,
            consecutiveNoRefMatchCount: consecutiveNoRefMatchCount,
            recentTunnelCandidateWayIDs: recentNearbyTunnelWayIDs,
            recentTunnelCandidateRefs: recentNearbyTunnelRefs,
            recentTunnelApproachWayIDs: recentTunnelApproachWayIDs,
            recentTunnelApproachRefs: recentTunnelApproachRefs,
            tunnelApproachFixCount: tunnelApproachFixCount,
            tunnelApproachBaselineAccuracyM: tunnelApproachBaselineAccuracyM,
            tunnelApproachBaselineSignalBars: tunnelApproachBaselineSignalBars,
            recentHypotheses: recentMatchHypotheses,
            matchedFixCount: matchedFixCount,
            hadRecentGPSSignalLoss: hadRecentGPSSignalLoss,
            isInTunnelMode: tunnelModeTracker.isTunnelModeActive,
            isInMotorwayMode: motorwayModeActive,
            activeCorridorState: activeCorridorState,
            approachCorridorState: approachCorridorState,
            approachCorridorFixCount: approachCorridorFixCount,
            approachCorridorStartDepthM: approachCorridorStartDepthM,
            approachCorridorStartDepthNodes: approachCorridorStartDepthNodes
        )
    }

    private func recordWayMatch(
        result: SpeedLimitResult,
        lat: Double,
        lon: Double,
        headingDeg: Double?,
        headingAccuracyDeg: Double?,
        speedKmh: Double?,
        horizontalAccuracyM: Double,
        gpsSignalBars: Int
    ) {
        recentObservedFixes.insert(
            WayMatchRecentFix(
                lat: lat,
                lon: lon,
                headingDeg: headingDeg,
                headingAccuracyDeg: headingAccuracyDeg,
                speedKmh: speedKmh,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
            ),
            at: 0
        )
        if recentObservedFixes.count > Self.recentMatchedFixHistoryLimit {
            recentObservedFixes.removeLast(recentObservedFixes.count - Self.recentMatchedFixHistoryLimit)
        }

        guard let wayID = normalizedWayID(result.wayID) else {
            return
        }
        matchedFixCount += 1
        previousMatchedWayID = wayID
        previousMatchedHighway = result.highway
        previousMatchedEndpointProximityM = result.matchedEndpointProximityM
        previousMatchedStreetRef = result.streetRef
        previousMatchedStreetName = result.streetBaseName ?? result.streetName
        pushUniqueFront(
            wayID,
            into: &recentMatchedWayIDs,
            limit: Self.recentMatchedWayHistoryLimit
        )
        sameRefUrbanReleaseStreak = updatedSameRefUrbanReleaseStreak(after: result)
        let normalizedStreetRefs = V3SpeedLimitService.normalizedRefTokens(result.streetRef)
        if normalizedStreetRefs.isEmpty {
            consecutiveNoRefMatchCount = min(consecutiveNoRefMatchCount + 1, 8)
        } else {
            consecutiveNoRefMatchCount = 0
        }
        for refToken in normalizedStreetRefs {
            pushUniqueFront(
                refToken,
                into: &recentMatchedStreetRefs,
                limit: Self.recentMatchedStreetRefHistoryLimit
            )
        }
        for tunnelWayID in result.nearbyTunnelCandidateWayIDs {
            pushUniqueFront(
                tunnelWayID,
                into: &recentNearbyTunnelWayIDs,
                limit: Self.recentMatchedWayHistoryLimit
            )
        }
        for refToken in result.nearbyTunnelCandidateRefs {
            pushUniqueFront(
                refToken,
                into: &recentNearbyTunnelRefs,
                limit: Self.recentMatchedStreetRefHistoryLimit
            )
        }
        updateTunnelApproachState(
            result: result,
            horizontalAccuracyM: horizontalAccuracyM,
            gpsSignalBars: gpsSignalBars
        )
        updateApproachCorridorState(result: result)
        activeCorridorState = result.activeCorridorState
        let resultHighway = result.highway?.lowercased()
        if resultHighway == "motorway" {
            motorwayModeActive = true
        } else if resultHighway == "motorway_link" {
            motorwayModeActive = motorwayModeActive || result.activeCorridorState?.kind == "motorway"
        } else {
            motorwayModeActive = false
        }
        recentMatchHypotheses = result.matchHypotheses
        hadRecentGPSSignalLoss = false
    }

    private func resetWayMatchContinuity() {
        previousMatchedWayID = nil
        previousMatchedHighway = nil
        previousMatchedEndpointProximityM = nil
        previousMatchedStreetRef = nil
        previousMatchedStreetName = nil
        recentMatchedWayIDs.removeAll(keepingCapacity: false)
        recentObservedFixes.removeAll(keepingCapacity: false)
        sameRefUrbanReleaseStreak = 0
        recentMatchedStreetRefs.removeAll(keepingCapacity: false)
        consecutiveNoRefMatchCount = 0
        recentNearbyTunnelWayIDs.removeAll(keepingCapacity: false)
        recentNearbyTunnelRefs.removeAll(keepingCapacity: false)
        resetTunnelApproachState()
        resetApproachCorridorState()
        motorwayModeActive = false
        activeCorridorState = nil
        recentMatchHypotheses.removeAll(keepingCapacity: false)
        matchedFixCount = 0
        hadRecentGPSSignalLoss = false
    }

    private func resetTunnelApproachState() {
        recentTunnelApproachWayIDs.removeAll(keepingCapacity: false)
        recentTunnelApproachRefs.removeAll(keepingCapacity: false)
        tunnelApproachFixCount = 0
        tunnelApproachBaselineAccuracyM = nil
        tunnelApproachBaselineSignalBars = nil
    }

    private func updatedSameRefUrbanReleaseStreak(after result: SpeedLimitResult) -> Int {
        if let streakCount = result.selectionTrace.last(where: { $0.step == "simple_same_ref_urban_release_streak" }).flatMap({ Int($0.detail) }) {
            return max(streakCount, 0)
        }
        return 0
    }

    private func resetApproachCorridorState() {
        approachCorridorState = nil
        approachCorridorFixCount = 0
        approachCorridorStartDepthM = nil
        approachCorridorStartDepthNodes = nil
    }

    private func updateTunnelApproachState(
        result: SpeedLimitResult,
        horizontalAccuracyM: Double,
        gpsSignalBars: Int
    ) {
        let approachTraces = result.candidateTraces.filter(Self.isTunnelApproachCandidateTrace)
        guard !result.isTunnelSegment, !approachTraces.isEmpty else {
            resetTunnelApproachState()
            return
        }

        tunnelApproachFixCount += 1
        if horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0 {
            if let baseline = tunnelApproachBaselineAccuracyM {
                tunnelApproachBaselineAccuracyM = min(baseline, horizontalAccuracyM)
            } else {
                tunnelApproachBaselineAccuracyM = horizontalAccuracyM
            }
        }
        tunnelApproachBaselineSignalBars = max(tunnelApproachBaselineSignalBars ?? gpsSignalBars, gpsSignalBars)

        recentTunnelApproachWayIDs.removeAll(keepingCapacity: false)
        recentTunnelApproachRefs.removeAll(keepingCapacity: false)
        for trace in approachTraces {
            if let wayID = normalizedWayID(trace.wayID) {
                pushUniqueFront(
                    wayID,
                    into: &recentTunnelApproachWayIDs,
                    limit: Self.recentMatchedWayHistoryLimit
                )
            }
            for refToken in V3SpeedLimitService.normalizedRefTokens(trace.streetRef) {
                pushUniqueFront(
                    refToken,
                    into: &recentTunnelApproachRefs,
                    limit: Self.recentMatchedStreetRefHistoryLimit
                )
            }
        }
    }

    private func updateApproachCorridorState(result: SpeedLimitResult) {
        guard result.activeCorridorState == nil else {
            resetApproachCorridorState()
            return
        }
        let corridorTrace = result.candidateTraces.first(where: { trace in
            guard trace.corridorKind != nil,
                  trace.corridorID != nil,
                  trace.corridorSideNodeKey != nil,
                  trace.corridorDepthM != nil,
                  trace.corridorRemainingM != nil,
                  trace.corridorDepthNodes != nil,
                  trace.corridorRemainingNodes != nil else {
                return false
            }
            guard trace.corridorKind == "tunnel" || trace.corridorKind == "motorway" else {
                return false
            }
            return trace.corridorEntryZone == true
        }) ?? approachCorridorState.flatMap { currentState in
            result.candidateTraces.first(where: { trace in
                guard trace.corridorKind == currentState.kind,
                      trace.corridorID == currentState.corridorID,
                      trace.corridorSideNodeKey == currentState.sideNodeKey,
                      let depthM = trace.corridorDepthM,
                      trace.corridorRemainingM != nil,
                      trace.corridorDepthNodes != nil,
                      trace.corridorRemainingNodes != nil else {
                    return false
                }
                return depthM + 6.0 >= currentState.depthM
            })
        }
        guard let trace = corridorTrace,
              let corridorKind = trace.corridorKind,
              let corridorID = trace.corridorID,
              let sideNodeKey = trace.corridorSideNodeKey,
              let depthM = trace.corridorDepthM,
              let remainingM = trace.corridorRemainingM,
        let depthNodes = trace.corridorDepthNodes,
        let remainingNodes = trace.corridorRemainingNodes else {
            resetApproachCorridorState()
            return
        }

        let nextState = CorridorMatchState(
            kind: corridorKind,
            corridorID: corridorID,
            sideNodeKey: sideNodeKey,
            depthM: depthM,
            spanM: depthM + remainingM,
            depthNodes: depthNodes,
            spanNodes: depthNodes + remainingNodes
        )
        if let currentState = approachCorridorState,
           currentState.kind == nextState.kind,
           currentState.corridorID == nextState.corridorID,
           currentState.sideNodeKey == nextState.sideNodeKey,
           nextState.depthM + 6.0 >= currentState.depthM {
            approachCorridorFixCount += 1
            let startDepthM = approachCorridorStartDepthM ?? currentState.depthM
            approachCorridorStartDepthM = min(startDepthM, nextState.depthM)
            let startDepthNodes = approachCorridorStartDepthNodes ?? currentState.depthNodes
            approachCorridorStartDepthNodes = min(startDepthNodes, nextState.depthNodes)
        } else {
            approachCorridorFixCount = 1
            approachCorridorStartDepthM = nextState.depthM
            approachCorridorStartDepthNodes = nextState.depthNodes
        }
        approachCorridorState = nextState
    }

    private static func isTunnelApproachCandidateTrace(_ trace: MatchCandidateTrace) -> Bool {
        let isTunnel = (trace.tunnel ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "yes"
        return isTunnel && trace.portalEligible == true
    }

    private func normalizedWayID(_ raw: String?) -> String? {
        let normalized = raw?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let normalized, !normalized.isEmpty else {
            return nil
        }
        return normalized
    }

    private func pushUniqueFront(_ value: String, into values: inout [String], limit: Int) {
        values.removeAll(where: { $0 == value })
        values.insert(value, at: 0)
        if values.count > limit {
            values.removeLast(values.count - limit)
        }
    }

    func beginSpeedLimitCapture() {
        guard !isInSpeedCaptureMode else {
            return
        }
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        activeLocalSpeedCorrection = nil
        awaitingSpeedCapturePromptCompletion = false
        speedCapturePromptFallbackTask?.cancel()
        speedCapturePromptFallbackTask = nil
        speedCaptureStartListeningTask?.cancel()
        speedCaptureStartListeningTask = nil
        speedCaptureMode = .speakingPrompt
        localObservationStatus = "Jetzt sprechen."
        speedCaptureLatestTranscript = ""
        speedCaptureDidResolve = false
#if DEBUG
        if ProcessInfo.processInfo.environment["YOUSPEED_GUIDE_ASSUME_SPEECH"] == "1" {
            speedCaptureMode = .listening
            return
        }
#endif
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                try await self.prepareSpeedCaptureRecognizer()
                self.startSpeedCaptureListening()
            } catch {
                self.cancelSpeedCapture(reason: "Spracherfassung nicht verfuegbar: \(error.localizedDescription)")
            }
        }
    }

    func deleteLocalObservation(_ observationID: String) {
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                try await localObservationStore.deleteObservation(observationID: observationID)
                localObservationStatus = "Eintrag geloescht."
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Loeschen fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func deleteAllLocalObservations() {
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let removed = try await localObservationStore.deleteAllObservations()
                localObservationStatus = removed > 0
                    ? "\(removed) lokale Erfassungen geloescht."
                    : "Keine lokalen Erfassungen vorhanden."
                localObservationShareURL = nil
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Alle Eintraege loeschen fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func exportAllLocalObservations() {
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let result = try await localObservationStore.exportAllLocalObservationsAsOsc()
                localObservationShareURL = result.changesFile
                lastExportDirectoryPath = result.packageDirectory.path
                localObservationStatus = "Export erstellt (\(result.includedCount) Wege): changes.osc"
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Export fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func clearLocalObservationShareURL() {
        localObservationShareURL = nil
    }

    func captureVoiceObservationDraft() {
        let command = observationDraftVoiceCommand.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !command.isEmpty else {
            localObservationStatus = "Bitte Sprachbefehl eingeben."
            return
        }
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let observation = try await localObservationStore.captureVoiceCommand(
                    command: command,
                    context: currentObservationCaptureContext()
                )
                observationDraftVoiceCommand = ""
                localObservationStatus = "Beobachtung erfasst: \(observation.intentType.rawValue) (\(observation.state.rawValue))."
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Erfassung fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func lockCurrentSpeedAsObservation() {
        let speed = Int(round(currentSpeedKmh))
        guard speed > 0 else {
            localObservationStatus = "Lock current speed nur mit Geschwindigkeit > 0 km/h."
            return
        }
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let observation = try await localObservationStore.lockCurrentSpeed(
                    speedKmh: speed,
                    context: currentObservationCaptureContext()
                )
                localObservationStatus = "Speed-Lock erfasst: \(observation.value ?? "?") km/h."
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Speed-Lock fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func approveObservation(_ observationID: String) {
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                _ = try await localObservationStore.reviewAndApproveProposal(observationID: observationID)
                localObservationStatus = "Beobachtung freigegeben fuer Export."
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Freigabe fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func discardObservation(_ observationID: String) {
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                _ = try await localObservationStore.discardObservation(observationID: observationID)
                localObservationStatus = "Beobachtung verworfen."
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Verwerfen fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func exportFirstApprovedObservation() {
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let approved = try await localObservationStore.fetchObservations(states: [.approvedForExport], limit: 1)
                guard let first = approved.first else {
                    localObservationStatus = "Keine freigegebene Beobachtung fuer Export vorhanden."
                    return
                }
                let export = try await localObservationStore.exportProposalAsOscPackage(observationID: first.id)
                lastExportDirectoryPath = export.packageDirectory.path
                localObservationStatus = "Export erstellt: \(export.packageDirectory.lastPathComponent)"
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Export fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    func refreshLocalObservations() async {
        do {
            let observations = try await localObservationStore.fetchObservations(limit: 500)
            let resolvedNumeric = Self.resolveLocalSpeedOverrides(from: observations)
            let resolvedValues = Self.resolveLocalSpeedOverrideValues(from: observations)
            let resolvedRevisions = Self.resolveLocalSpeedOverrideRevisions(from: observations)
            let currentWayID = latestTrafficSignDetectionContext?.wayId
                ?? limitWayID?.trimmingCharacters(in: .whitespacesAndNewlines)
            let currentRoadCorrectionChanged = currentWayID.map {
                localSpeedOverridesByWayID[$0] != resolvedNumeric[$0]
                    || localSpeedOverrideValuesByWayID[$0] != resolvedValues[$0]
                    || localSpeedOverrideRevisionsByWayID[$0] != resolvedRevisions[$0]
            } ?? false
            localObservations = observations
            localSpeedOverridesByWayID = resolvedNumeric
            localSpeedOverrideValuesByWayID = resolvedValues
            localSpeedOverrideRevisionsByWayID = resolvedRevisions
            localObservationStreetNames = resolveStreetNames(for: observations)
            if currentRoadCorrectionChanged, let currentWayID {
                if activeLocalSpeedCorrection?.wayID == currentWayID,
                   activeLocalSpeedCorrection?.maxspeedValue != resolvedValues[currentWayID] {
                    activeLocalSpeedCorrection = nil
                }
                currentLocalCorrectionSpeedKmh = resolvedNumeric[currentWayID]
                currentBaseSpeedLimitDisplayText = Self.speedLimitDisplayText(
                    for: resolvedValues[currentWayID]
                )
                currentBaseUnlimitedSpeedLimitActive = resolvedValues[currentWayID] == nil
                    && currentBundledUnlimitedSpeedLimitActive
                invalidateTrafficSignOverrideForBaseSourceMutation()
            }
        } catch {
            localObservationStatus = "Lokale Beobachtungen konnten nicht geladen werden: \(error.localizedDescription)"
            lastError = localObservationStatus
        }
    }

    static func resolveLocalSpeedOverrides(from observations: [LocalObservation]) -> [String: Int] {
        var resolved: [String: Int] = [:]
        for observation in observations {
            guard observation.state != .discarded else {
                continue
            }
            guard let wayID = observation.roadCandidateIDs.first?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !wayID.isEmpty else {
                continue
            }
            let speedCandidate = observation.newSpeedKmh ?? observation.value.flatMap(Int.init)
            guard let speedCandidate, speedCandidate > 0 else {
                continue
            }
            if resolved[wayID] == nil {
                resolved[wayID] = speedCandidate
            }
        }
        return resolved
    }

    static func resolveLocalSpeedOverrideValues(from observations: [LocalObservation]) -> [String: String] {
        var resolved: [String: String] = [:]
        for observation in observations {
            guard observation.state != .discarded else {
                continue
            }
            guard let wayID = observation.roadCandidateIDs.first?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !wayID.isEmpty else {
                continue
            }
            guard let maxspeedValue = observation.value?.trimmingCharacters(in: CharacterSet.whitespacesAndNewlines),
                  !maxspeedValue.isEmpty else {
                continue
            }
            if resolved[wayID] == nil {
                resolved[wayID] = maxspeedValue
            }
        }
        return resolved
    }

    static func resolveLocalSpeedOverrideRevisions(
        from observations: [LocalObservation]
    ) -> [String: String] {
        var resolved: [String: String] = [:]
        for observation in observations {
            guard observation.state != .discarded,
                  let wayID = observation.roadCandidateIDs.first?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                  !wayID.isEmpty,
                  let value = observation.value?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                  !value.isEmpty,
                  resolved[wayID] == nil else { continue }
            resolved[wayID] = localSpeedCorrectionRevisionToken(for: observation)
        }
        return resolved
    }

    private static func localSpeedCorrectionRevisionToken(
        for observation: LocalObservation
    ) -> String {
        "id:\(observation.id)|updated:\(observation.updatedAtUTC)|state:\(observation.state.rawValue)|source:\(observation.sourceVersion)"
    }

    static func speedLimitDisplayText(for maxspeedValue: String?) -> String? {
        switch maxspeedValue?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "walk":
            return "Schritt"
        default:
            return nil
        }
    }

    private func resolveStreetNames(for observations: [LocalObservation]) -> [String: String] {
        let wayIDs = observations
            .compactMap { $0.roadCandidateIDs.first?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !wayIDs.isEmpty else {
            return [:]
        }

        let resolver: V3SpeedLimitService?
        if let speedLimitService {
            resolver = speedLimitService
        } else if !activeDBPath.isEmpty {
            resolver = makeSpeedLimitService(dbPath: activeDBPath)
        } else {
            resolver = nil
        }

        guard let resolver else {
            return [:]
        }
        do {
            return try resolver.lookupStreetNames(forWayIDs: wayIDs)
        } catch {
            Self.logger.warning("streetname lookup for local observations failed: \(error.localizedDescription, privacy: .public)")
            return [:]
        }
    }

    private func currentObservationCaptureContext() -> LocalObservationCaptureContext {
        let source = activeBundleVersion.isEmpty ? "none" : activeBundleVersion
        let roadCandidates = limitWayID.map { [$0] } ?? []
        let confidence: Double?
        if speedLimitKmh != nil || speedLimitDisplayText != nil {
            confidence = 0.85
        } else if lastLookupNearestCandidateM != nil {
            confidence = 0.55
        } else {
            confidence = nil
        }
        return LocalObservationCaptureContext(
            lat: currentLatitude,
            lon: currentLongitude,
            headingDeg: nil,
            roadCandidateIDs: roadCandidates,
            cityContext: limitCityName,
            streetContext: limitStreetName,
            confidenceCalibrated: confidence,
            sourceVersion: source
        )
    }

    private func startSpeedCapturePromptSpeech() {
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        awaitingSpeedCapturePromptCompletion = true
        speedCaptureMode = .speakingPrompt
        let utterance = AVSpeechUtterance(string: "Geschwindigkeit erfassen. Jetzt sprechen.")
        utterance.voice = AVSpeechSynthesisVoice(language: Self.speedCaptureSpeechLocaleIdentifier)
            ?? AVSpeechSynthesisVoice(language: Locale.preferredLanguages.first ?? Self.speedCaptureSpeechLocaleIdentifier)
        utterance.rate = 0.46
        speechSynthesizer.speak(utterance)

        speedCapturePromptFallbackTask?.cancel()
        speedCapturePromptFallbackTask = Task { [weak self] in
            let fallbackDelayNanos = 3_800_000_000 as UInt64
            try? await Task.sleep(nanoseconds: fallbackDelayNanos)
            guard !Task.isCancelled else {
                return
            }
            await MainActor.run {
                guard let self, self.awaitingSpeedCapturePromptCompletion else {
                    return
                }
                self.awaitingSpeedCapturePromptCompletion = false
                self.scheduleSpeedCaptureListeningStart()
            }
        }
    }

    private func scheduleSpeedCaptureListeningStart() {
        speedCaptureStartListeningTask?.cancel()
        speedCaptureStartListeningTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.speedCaptureStartDelayNanos)
            guard !Task.isCancelled else {
                return
            }
            await MainActor.run {
                guard let self else {
                    return
                }
                guard self.speedCaptureMode == .speakingPrompt else {
                    return
                }
                self.startSpeedCaptureListening()
            }
        }
    }

    private func startSpeedCaptureListening() {
        guard !speedCaptureDidResolve else {
            return
        }
        guard speedCaptureMode == .speakingPrompt || speedCaptureMode == .listening else {
            return
        }
        guard let recognizer = speedCaptureRecognizer else {
            cancelSpeedCapture(reason: "Spracherkennung nicht initialisiert.")
            return
        }
        stopActiveSpeedCaptureRecognition(keepStatus: true)
        speedCaptureLatestTranscript = ""
        speedCaptureDidResolve = false
        speedCaptureMode = .listening
        localObservationStatus = "Jetzt sprechen: 10 bis 130 oder Fussgaengerzone."

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.taskHint = .confirmation
        request.addsPunctuation = false
        request.contextualStrings = Self.speedCaptureContextualStrings
        speedCaptureRecognitionRequest = request

        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.record, mode: .measurement, options: [.duckOthers])
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
            let engine = AVAudioEngine()
            speedCaptureAudioEngine = engine
            let inputNode = engine.inputNode
            inputNode.removeTap(onBus: 0)
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
                self?.speedCaptureRecognitionRequest?.append(buffer)
            }
            engine.prepare()
            try engine.start()
        } catch {
            cancelSpeedCapture(reason: "Mikrofonstart fehlgeschlagen: \(error.localizedDescription)")
            return
        }

        speedCaptureRecognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                if let transcript = result?.bestTranscription.formattedString,
                   !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    self.speedCaptureLatestTranscript = transcript
                }
                if let error {
                    if !self.speedCaptureLatestTranscript.isEmpty {
                        self.finishSpeedCaptureListening(source: "recognition_error_with_transcript")
                    } else {
                        self.cancelSpeedCapture(reason: "Spracherkennung fehlgeschlagen: \(error.localizedDescription)")
                    }
                    return
                }
                if result?.isFinal == true {
                    self.finishSpeedCaptureListening(source: "final_result")
                }
            }
        }

        speedCaptureListeningTimeoutTask?.cancel()
        speedCaptureListeningTimeoutTask = Task { [weak self] in
            let timeout = (Self.speedCaptureListeningWindowSeconds * 1_000_000_000) + Self.speedCaptureTimeoutPaddingNanos
            try? await Task.sleep(nanoseconds: timeout)
            guard !Task.isCancelled else {
                return
            }
            await MainActor.run {
                self?.finishSpeedCaptureListening(source: "timeout")
            }
        }
    }

    private func finishSpeedCaptureListening(source: String) {
        guard !speedCaptureDidResolve else {
            return
        }
        speedCaptureDidResolve = true
        speedCaptureMode = .evaluating
        speedCaptureListeningTimeoutTask?.cancel()
        speedCaptureListeningTimeoutTask = nil
        stopActiveSpeedCaptureRecognition(keepStatus: true)

        let transcript = speedCaptureLatestTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else {
            cancelSpeedCapture(reason: "Keine Sprache erkannt. Bitte erneut starten.")
            return
        }
        guard let selection = Self.resolveSpeedCaptureSelection(from: transcript) else {
            Self.logger.notice("capture_speech unmatched transcript=\(transcript, privacy: .private(mask: .hash)) source=\(source, privacy: .public)")
            cancelSpeedCapture(reason: "Nicht verstanden. Erlaubt sind 10 bis 130 oder Fussgaengerzone.")
            return
        }
        Self.logger.notice(
            "capture_speech matched transcript=\(transcript, privacy: .private(mask: .hash)) maxspeed=\(selection.value, privacy: .public) source=\(source, privacy: .public)"
        )
        commitSpeedCaptureObservation(selection: selection)
    }

    private func commitSpeedCaptureObservation(selection: SpeedCaptureWhitelistEntry) {
        speedCaptureMode = .saving
        let oldSpeed = speedLimitKmh
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            do {
                let captureContext = currentObservationCaptureContext()
                let wayID = captureContext.roadCandidateIDs.first ?? "n/a"
                Self.logger.notice(
                    "capture_speech persist begin maxspeed=\(selection.value, privacy: .public) old=\(oldSpeed?.description ?? "n/a", privacy: .public) way=\(wayID, privacy: .public) source=\(captureContext.sourceVersion, privacy: .public)"
                )
                let observation = try await localObservationStore.recordSpeedLimitChange(
                    oldSpeedKmh: oldSpeed,
                    newMaxspeedValue: selection.value,
                    context: captureContext
                )
                if let wayID = observation.roadCandidateIDs.first,
                   !wayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    localSpeedOverrideValuesByWayID[wayID] = selection.value
                    localSpeedOverrideRevisionsByWayID[wayID] =
                        Self.localSpeedCorrectionRevisionToken(for: observation)
                }
                // A newly committed local correction is genuinely new source
                // information and therefore ends any older camera assertion.
                trafficSignOverridePolicy.clear()
                trafficSignRecognitionActiveOverride = nil
                trafficSignRecognitionLastEvent = nil
                currentTrafficSignSourceSignature = nil
                invalidateTrafficSignInferenceContext()
                if trafficSignRecognitionEnabled {
                    trafficSignRecognitionState = trafficSignRuntime == nil
                        ? .unavailable
                        : .noRecognition
                }
                if let numericSpeed = observation.newSpeedKmh,
                   let wayID = observation.roadCandidateIDs.first,
                   !wayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    localSpeedOverridesByWayID[wayID] = numericSpeed
                    if limitWayID == wayID {
                        currentLocalCorrectionSpeedKmh = numericSpeed
                        currentBaseSpeedLimitDisplayText = nil
                        currentBaseUnlimitedSpeedLimitActive = false
                        speedLimitKmh = numericSpeed
                        lastKnownSpeedLimitKmh = numericSpeed
                        isUnlimitedSpeedLimitActive = false
                    }
                }
                if let wayID = observation.roadCandidateIDs.first,
                   limitWayID == wayID {
                    if observation.newSpeedKmh == nil {
                        currentLocalCorrectionSpeedKmh = nil
                        speedLimitKmh = nil
                    }
                    let displayText = Self.speedLimitDisplayText(for: selection.value)
                    currentBaseSpeedLimitDisplayText = displayText
                    currentBaseUnlimitedSpeedLimitActive = false
                    speedLimitDisplayText = displayText
                    if speedLimitDisplayText != nil {
                        isUnlimitedSpeedLimitActive = false
                    }
                }
                let way = observation.roadCandidateIDs.first ?? "n/a"
                localObservationStatus = "Erfasst: way \(way), alt \(oldSpeed?.description ?? "n/a"), neu \(selection.displayLabel)."
                Self.logger.notice(
                    "capture_speech persist saved id=\(observation.id, privacy: .public) way=\(way, privacy: .public) value=\(observation.value ?? "n/a", privacy: .public) state=\(observation.state.rawValue, privacy: .public)"
                )
                activateLocalSpeedCorrectionIfPossible(selection: selection, observation: observation)
                await refreshLocalObservations()
                cancelSpeedCapture(reason: nil)
                playSpeedCaptureConfirmationTone()
            } catch {
                let message = "Erfassung fehlgeschlagen: \(error.localizedDescription)"
                localObservationStatus = message
                lastError = message
                Self.logger.error("capture_speech persist failed error=\(error.localizedDescription, privacy: .public)")
                cancelSpeedCapture(reason: message)
            }
        }
    }

    private func playSpeedCaptureConfirmationTone() {
        captureConfirmationTonePlayer.play()
        Self.logger.notice("capture_speech confirmation_tone played freq_hz=432")
    }

    private func activateLocalSpeedCorrectionIfPossible(selection: SpeedCaptureWhitelistEntry, observation: LocalObservation) {
        let wayID = observation.roadCandidateIDs.first?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !wayID.isEmpty else {
            activeLocalSpeedCorrection = nil
            return
        }

        activeLocalSpeedCorrection = ActiveLocalSpeedCorrection(
            wayID: wayID,
            maxspeedValue: selection.value,
            numericSpeedKmh: observation.newSpeedKmh ?? Int(selection.value)
        )
        Self.logger.notice(
            "capture_corr session_started way=\(wayID, privacy: .public) value=\(selection.value, privacy: .public)"
        )
    }

    private func applyActiveLocalSpeedCorrectionIfNeeded(for result: SpeedLimitResult, lat _: Double, lon _: Double) -> String? {
        guard let correction = activeLocalSpeedCorrection else {
            return nil
        }
        guard let wayID = result.wayID?.trimmingCharacters(in: .whitespacesAndNewlines), !wayID.isEmpty else {
            return nil
        }
        guard wayID == correction.wayID else {
            Self.logger.notice(
                "capture_corr session_stopped reason=way_changed from=\(correction.wayID, privacy: .public) to=\(wayID, privacy: .public)"
            )
            activeLocalSpeedCorrection = nil
            return nil
        }

        localSpeedOverrideValuesByWayID[wayID] = correction.maxspeedValue
        if let numeric = correction.numericSpeedKmh {
            localSpeedOverridesByWayID[wayID] = numeric
        }
        return correction.maxspeedValue
    }

    private func makeTrafficSignSourceSignature(
        result: SpeedLimitResult,
        localOverrideValue: String?,
        travelDirection: TrafficSignTravelDirection
    ) -> TrafficSignRuntimeSourceSignature {
        let bundle = activeBundleVersion.trimmingCharacters(in: .whitespacesAndNewlines)
        let way = result.wayID?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "none"
        let osmValue: String
        if result.isUnlimitedSpeedLimit == true {
            osmValue = "unlimited"
        } else {
            osmValue = result.speedLimitKmh.map(String.init) ?? "none"
        }
        let osmRevision = "bundle:\(bundle.isEmpty ? "none" : bundle)|way:\(way.isEmpty ? "none" : way)|direction:\(travelDirection.rawValue)|maxspeed:\(osmValue)"
        let localRevision = localOverrideValue.map { value in
            let correctionRevision = localSpeedOverrideRevisionsByWayID[way]
                ?? "unversioned"
            return "way:\(way.isEmpty ? "none" : way)|maxspeed:\(value)|revision:\(correctionRevision)"
        }
        return TrafficSignRuntimeSourceSignature(
            osmRevision: osmRevision,
            localCorrectionRevision: localRevision
        )
    }

    private func makeTrafficSignDetectionContext(
        result: SpeedLimitResult,
        latitude: Double,
        longitude: Double,
        headingDegrees: Double?,
        travelDirection: TrafficSignTravelDirection,
        sourceSignature: TrafficSignRuntimeSourceSignature
    ) -> TrafficSignDetectionContext? {
        guard let wayId = result.wayID?.trimmingCharacters(in: .whitespacesAndNewlines),
              !wayId.isEmpty,
              let headingDegrees,
              headingDegrees.isFinite,
              headingDegrees >= 0,
              headingDegrees < 360 else {
            return nil
        }
        let context = TrafficSignDetectionContext(
            wayId: wayId,
            latitude: latitude,
            longitude: longitude,
            headingDegrees: headingDegrees,
            travelDirection: travelDirection,
            sourceSignature: sourceSignature
        )
        return context.isValid ? context : nil
    }

    private static func hasSameTrafficSignRoadIdentity(
        _ lhs: TrafficSignDetectionContext?,
        _ rhs: TrafficSignDetectionContext?
    ) -> Bool {
        switch (lhs, rhs) {
        case (nil, nil):
            return true
        case let (lhs?, rhs?):
            return lhs.wayId == rhs.wayId
                && lhs.travelDirection == rhs.travelDirection
                && lhs.sourceSignature == rhs.sourceSignature
        case (.some, nil), (nil, .some):
            return false
        }
    }

    private static func trafficSignTravelDirection(
        for result: SpeedLimitResult,
        headingDegrees: Double?
    ) -> TrafficSignTravelDirection {
        guard let headingDegrees,
              headingDegrees.isFinite,
              headingDegrees >= 0,
              headingDegrees < 360,
              let wayID = result.wayID,
              let hypothesis = result.matchHypotheses.first(where: { $0.wayID == wayID }),
              let startLat = hypothesis.startLat,
              let startLon = hypothesis.startLon,
              let endLat = hypothesis.endLat,
              let endLon = hypothesis.endLon,
              let wayHeading = initialBearingDegrees(
                  startLatitude: startLat,
                  startLongitude: startLon,
                  endLatitude: endLat,
                  endLongitude: endLon
              ) else {
            return .unknown
        }
        let clockwise = (headingDegrees - wayHeading + 360).truncatingRemainder(dividingBy: 360)
        let difference = min(clockwise, 360 - clockwise)
        return difference <= 90 ? .forward : .reverse
    }

    private static func initialBearingDegrees(
        startLatitude: Double,
        startLongitude: Double,
        endLatitude: Double,
        endLongitude: Double
    ) -> Double? {
        let latitude1 = startLatitude * .pi / 180
        let latitude2 = endLatitude * .pi / 180
        let longitudeDelta = (endLongitude - startLongitude) * .pi / 180
        let y = sin(longitudeDelta) * cos(latitude2)
        let x = cos(latitude1) * sin(latitude2)
            - sin(latitude1) * cos(latitude2) * cos(longitudeDelta)
        guard x.isFinite, y.isFinite, abs(x) + abs(y) > 1e-12 else { return nil }
        return (atan2(y, x) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }

    private func cancelSpeedCapture(reason: String?) {
        stopActiveSpeedCaptureRecognition(keepStatus: true)
        speedCaptureStartListeningTask?.cancel()
        speedCaptureStartListeningTask = nil
        speedCapturePromptFallbackTask?.cancel()
        speedCapturePromptFallbackTask = nil
        speedCaptureListeningTimeoutTask?.cancel()
        speedCaptureListeningTimeoutTask = nil
        awaitingSpeedCapturePromptCompletion = false
        speedCaptureLatestTranscript = ""
        speedCaptureDidResolve = false
        speedCaptureMode = .idle
        if let reason, !reason.isEmpty {
            localObservationStatus = reason
        }
    }

    private func stopActiveSpeedCaptureRecognition(keepStatus: Bool) {
        speedCaptureRecognitionTask?.cancel()
        speedCaptureRecognitionTask = nil
        speedCaptureRecognitionRequest?.endAudio()
        speedCaptureRecognitionRequest = nil
        if let engine = speedCaptureAudioEngine {
            if engine.isRunning {
                engine.stop()
            }
            engine.inputNode.removeTap(onBus: 0)
        }
        speedCaptureAudioEngine = nil
        let session = AVAudioSession.sharedInstance()
        try? session.setActive(false, options: .notifyOthersOnDeactivation)
        if !keepStatus {
            localObservationStatus = ""
        }
    }

    private func prepareSpeedCaptureRecognizer() async throws {
        let speechAuth = await requestSpeechRecognitionAuthorization()
        guard speechAuth == .authorized else {
            throw ConsumerAppError.io(Self.speechAuthorizationDescription(speechAuth))
        }
        let hasMicPermission = await requestMicrophonePermission()
        guard hasMicPermission else {
            throw ConsumerAppError.io("Mikrofonberechtigung wurde nicht erteilt.")
        }
        guard let locale = Self.resolvePreferredSpeechLocale() else {
            throw ConsumerAppError.io("Keine deutsche On-Device-Spracherkennung verfuegbar.")
        }
        guard let recognizer = SFSpeechRecognizer(locale: locale) else {
            throw ConsumerAppError.io("SFSpeechRecognizer konnte nicht erstellt werden.")
        }
        guard recognizer.supportsOnDeviceRecognition else {
            throw ConsumerAppError.io("On-Device-Spracherkennung fuer \(locale.identifier) nicht verfuegbar.")
        }
        speedCaptureRecognizer = recognizer
    }

    private func requestSpeechRecognitionAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }

    private func requestMicrophonePermission() async -> Bool {
        return await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission(completionHandler: { granted in
                continuation.resume(returning: granted)
            })
        }
    }

    private static func resolvePreferredSpeechLocale() -> Locale? {
        let supported = SFSpeechRecognizer.supportedLocales()
        let preferred = Locale(identifier: speedCaptureSpeechLocaleIdentifier)
        if supported.contains(preferred) {
            return preferred
        }
        return supported.first { $0.identifier.lowercased().hasPrefix("de") }
    }

    private static func speechAuthorizationDescription(_ status: SFSpeechRecognizerAuthorizationStatus) -> String {
        switch status {
        case .notDetermined:
            return "Spracherkennung ist noch nicht freigegeben."
        case .denied:
            return "Spracherkennung in iOS-Einstellungen aktivieren."
        case .restricted:
            return "Spracherkennung ist auf diesem Geraet eingeschraenkt."
        case .authorized:
            return "Spracherkennung autorisiert."
        @unknown default:
            return "Unbekannter Spracherkennungsstatus."
        }
    }

    private static func resolveSpeedCaptureSelection(from transcript: String) -> SpeedCaptureWhitelistEntry? {
        let normalized = normalizeSpeedCaptureTranscript(transcript)
        guard !normalized.isEmpty else {
            return nil
        }

        var candidates = Set<String>()
        let nsRange = NSRange(normalized.startIndex..<normalized.endIndex, in: normalized)
        if let regex = try? NSRegularExpression(pattern: #"\b([0-9]{2,3})\b"#) {
            for match in regex.matches(in: normalized, range: nsRange) {
                guard let range = Range(match.range(at: 1), in: normalized) else {
                    continue
                }
                let token = String(normalized[range])
                if speedCaptureValueSet.contains(token) {
                    candidates.insert(token)
                }
            }
        }

        for (phrase, value) in speedCapturePhraseToValue {
            if normalized.contains(phrase) {
                candidates.insert(value)
            }
        }

        guard !candidates.isEmpty else {
            return nil
        }

        for entry in speedCaptureWhitelistByPriority where candidates.contains(entry.value) {
            return entry
        }
        return nil
    }

    private static func normalizeSpeedCaptureTranscript(_ raw: String) -> String {
        raw
            .lowercased()
            .replacingOccurrences(of: "ä", with: "ae")
            .replacingOccurrences(of: "ö", with: "oe")
            .replacingOccurrences(of: "ü", with: "ue")
            .replacingOccurrences(of: "ß", with: "ss")
            .replacingOccurrences(of: "[^a-z0-9]+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func routeDatabaseForCoordinate(lat: Double, lon: Double, fixTimestamp: String, fixID: Int) async {
        let routingContextGeneration = trafficSignContextGeneration
        do {
            guard let route = try await bundleManager.resolveLocalBundleRoute(
                lat: lat,
                lon: lon,
                fallbackDBPath: activeDBPath.isEmpty ? nil : activeDBPath
            ) else {
                return
            }
            guard fixID == latestTrafficSignLookupFixID,
                  routingContextGeneration == trafficSignContextGeneration else { return }
            guard route.dbPath != activeDBPath
                    || route.bundleVersion != activeBundleVersion else {
                return
            }
            invalidateTrafficSignOverrideIfBundleWillChange(
                bundleVersion: route.bundleVersion,
                dbPath: route.dbPath
            )
            activeDBPath = route.dbPath
            activeBundleVersion = route.bundleVersion
            speedLimitService = makeSpeedLimitService(
                dbPath: route.dbPath,
                preferredCountryCode: route.countryCode
            )
            await applyPenaltyRulesForActiveBundle(preferredCountryCode: route.countryCode)
            resetWayMatchContinuity()
            appendLookupEvent(
                "\(fixTimestamp) fix=\(fixID) db_switch region=\(route.region) version=\(route.bundleVersion) db=\(URL(fileURLWithPath: route.dbPath).lastPathComponent)"
            )
        } catch {
            Self.logger.warning("regional db route failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func updateSpeedLimit(for location: CLLocation, fixID: Int, speedKmh: Double) async {
        let fixTimestamp = Self.lookupTimestampFormatter.string(from: location.timestamp)
        let fixTimestampISO = Self.isoFormatter.string(from: location.timestamp)
        let lat = location.coordinate.latitude
        let lon = location.coordinate.longitude
        let hAcc = location.horizontalAccuracy
        let vAcc = location.verticalAccuracy
        gpsHorizontalAccuracyM = hAcc >= 0 ? hAcc : nil
        gpsSignalBars = Self.gpsSignalBars(horizontalAccuracyM: hAcc)
        let rawCourse = location.course
        let course = (0.0 ... 360.0).contains(rawCourse) ? rawCourse : nil
        let rawCourseAccuracy = location.courseAccuracy
        let courseAccuracy = rawCourseAccuracy >= 0.0 ? rawCourseAccuracy : nil

        await routeDatabaseForCoordinate(lat: lat, lon: lon, fixTimestamp: fixTimestamp, fixID: fixID)

        guard fixID == latestTrafficSignLookupFixID else { return }

        guard let service = speedLimitService else {
            wasDrivingBanWarningActive = false
            isUnlimitedSpeedLimitActive = false
            resetTunnelModeTracking()
            matchedFixCount = 0
            hadRecentGPSSignalLoss = true
            appendLookupEvent(
                "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) speed_kmh=\(String(format: "%.1f", speedKmh)) hacc_m=\(String(format: "%.1f", hAcc)) status=no_service"
            )
            appendGPSFixCSV(
                fixID: fixID,
                timestampISO: fixTimestampISO,
                lat: lat,
                lon: lon,
                speedKmh: speedKmh,
                horizontalAccM: hAcc,
                verticalAccM: vAcc,
                courseDeg: rawCourse,
                status: "no_service",
                result: nil,
                errorText: nil
            )
            return
        }
        let radiusM = Self.lookupRadius(forHorizontalAccuracy: hAcc)
        let maxCandidates = lookupMaxCandidates
        let matchContext = currentWayMatchContext()
        let gpsBars = gpsSignalBars
        let lookupContextGeneration = trafficSignContextGeneration

        Task.detached(priority: .utility) {
            do {
                let result = try service.lookupSpeedLimit(
                    lat: lat,
                    lon: lon,
                    radiusM: radiusM,
                    maxCandidates: maxCandidates,
                    matchContext: matchContext,
                    headingDeg: course,
                    headingAccuracyDeg: courseAccuracy,
                    speedKmh: speedKmh,
                    horizontalAccuracyM: hAcc,
                    gpsSignalBars: gpsBars
                )
                await MainActor.run {
                    guard fixID == self.latestTrafficSignLookupFixID,
                          lookupContextGeneration == self.trafficSignContextGeneration else {
                        self.appendLookupEvent(
                            "\(fixTimestamp) fix=\(fixID) status=stale_lookup_or_source_discarded"
                        )
                        return
                    }
                    let propagatedOverrideValue = self.applyActiveLocalSpeedCorrectionIfNeeded(for: result, lat: lat, lon: lon)
                    let localOverrideValue = propagatedOverrideValue ?? result.wayID.flatMap { self.localSpeedOverrideValuesByWayID[$0] }
                    let localOverride = localOverrideValue.flatMap(Int.init)
                    let travelDirection = Self.trafficSignTravelDirection(
                        for: result,
                        headingDegrees: course
                    )
                    let sourceSignature = self.makeTrafficSignSourceSignature(
                        result: result,
                        localOverrideValue: localOverrideValue,
                        travelDirection: travelDirection
                    )
                    self.currentTrafficSignSourceSignature = sourceSignature
                    self.currentBundledSpeedLimitKmh = result.speedLimitKmh
                    self.currentLocalCorrectionSpeedKmh = localOverride
                    let baseSpeedLimitDisplayText = Self.speedLimitDisplayText(
                        for: localOverrideValue
                    )
                    let bundledUnlimitedMatch = self.isGermanAutobahnUnlimitedMatch(
                        result: result,
                        localOverrideValue: nil
                    )
                    let baseUnlimitedMatch = localOverrideValue == nil
                        && bundledUnlimitedMatch
                    self.currentBaseSpeedLimitDisplayText = baseSpeedLimitDisplayText
                    self.currentBundledUnlimitedSpeedLimitActive = bundledUnlimitedMatch
                    self.currentBaseUnlimitedSpeedLimitActive = baseUnlimitedMatch
                    let nextTrafficSignContext = self.makeTrafficSignDetectionContext(
                        result: result,
                        latitude: lat,
                        longitude: lon,
                        headingDegrees: course,
                        travelDirection: travelDirection,
                        sourceSignature: sourceSignature
                    )
                    let effectiveSpeedLimit = self.trafficSignOverridePolicy.resolvedSpeedKmh(
                        osmSpeedKmh: result.speedLimitKmh,
                        localCorrectionSpeedKmh: localOverride,
                        currentContext: nextTrafficSignContext
                    )
                    self.trafficSignRecognitionActiveOverride = self.trafficSignOverridePolicy.activeOverride
                    let hasTrafficSignOverride = self.trafficSignOverridePolicy.activeOverride != nil
                    let unlimitedMatch = hasTrafficSignOverride
                        ? false
                        : baseUnlimitedMatch
                    self.speedLimitKmh = effectiveSpeedLimit
                    self.speedLimitDisplayText = hasTrafficSignOverride
                        ? nil
                        : baseSpeedLimitDisplayText
                    self.isUnlimitedSpeedLimitActive = unlimitedMatch
                    if let resolved = effectiveSpeedLimit {
                        self.lastKnownSpeedLimitKmh = resolved
                    }
                    self.limitWayID = result.wayID
                    self.limitStreetName = result.streetName
                    self.limitStreetBaseName = result.streetBaseName
                    self.limitStreetRef = result.streetRef
                    self.limitCityName = result.cityName
                    self.limitCityPlaceName = result.cityPlaceName
                    self.limitCityDistrictName = result.cityDistrictName
                    let roadIdentityChanged = !Self.hasSameTrafficSignRoadIdentity(
                        self.latestTrafficSignDetectionContext,
                        nextTrafficSignContext
                    )
                    if roadIdentityChanged {
                        self.trafficSignContextGeneration &+= 1
                        self.trafficSignRecognitionLastEvent = nil
                        if !self.trafficSignRecognitionEnabled {
                            self.trafficSignRecognitionState = .disabled
                        } else if self.trafficSignRuntime == nil {
                            self.trafficSignRecognitionState = .unavailable
                        } else {
                            self.trafficSignRecognitionState = .noRecognition
                        }
                    }
                    self.currentTrafficSignTravelDirection = travelDirection
                    self.latestTrafficSignDetectionContext = nextTrafficSignContext
                    self.trafficSignFrameContextIsCurrent = self.latestTrafficSignDetectionContext != nil
                    self.refreshTrafficSignFrameSnapshot()
                    self.tunnelModeTracker.consumeFix(isTunnelSegment: result.isTunnelSegment)
                    self.syncTunnelModePublishedState()
                    self.recordWayMatch(
                        result: result,
                        lat: lat,
                        lon: lon,
                        headingDeg: course,
                        headingAccuracyDeg: courseAccuracy,
                        speedKmh: speedKmh,
                        horizontalAccuracyM: hAcc,
                        gpsSignalBars: gpsBars
                    )
                    self.maybeNotifyDrivingBanWarning()
                    self.maybeSpeakOverspeedWarning()
                    let lookupStatus: String
                    if unlimitedMatch {
                        lookupStatus = "matched_unlimited"
                    } else if effectiveSpeedLimit == nil {
                        lookupStatus = "no_match"
                    } else if hasTrafficSignOverride {
                        lookupStatus = "matched_camera_override"
                    } else if localOverride != nil {
                        lookupStatus = "matched_local_override"
                    } else {
                        lookupStatus = "matched"
                    }
                    self.lastLookupStatus = lookupStatus
                    self.lastLookupQueryMs = result.queryTimeMs
                    self.lastLookupCandidateCount = result.candidateCount
                    self.lastLookupSpeedCandidateCount = result.speedCandidateCount
                    self.lastLookupNearestCandidateM = result.nearestCandidateDistanceM
                    self.lastLookupNearestSpeedCandidateM = result.nearestSpeedCandidateDistanceM
                    self.lastLookupInsideCity = result.insideCity
                    self.lastLookupCitySource = result.citySource ?? "n/a"
                    self.lastLookupCityResolveMs = result.cityResolveMs
                    self.lastLookupCityCandidateBoundaries = result.cityCandidateBoundaries
                    self.lastLookupCityContainingBoundaries = result.cityContainingBoundaries
                    self.lastLookupCityPlaceCandidates = result.cityPlaceCandidates
                    self.lastCandidateTraces = result.candidateTraces
                    self.lastSelectionTrace = result.selectionTrace
                    let speedText = effectiveSpeedLimit.map(String.init) ?? "nil"
                    let wayText = result.wayID ?? "nil"
                    let streetText = result.streetName ?? "nil"
                    let cityText = result.cityName ?? "nil"
                    let insideCityText = result.insideCity.map { $0 ? "1" : "0" } ?? "nil"
                    let citySourceText = result.citySource ?? "nil"
                    let nearestText = result.nearestCandidateDistanceM.map { String(format: "%.1f", $0) } ?? "nil"
                    let nearestSpeedText = result.nearestSpeedCandidateDistanceM.map { String(format: "%.1f", $0) } ?? "nil"
                    let tunnelSegmentText = result.isTunnelSegment ? "1" : "0"
                    let tunnelModeText = self.tunnelModeState.rawValue
                    let localOverrideText = localOverrideValue ?? "nil"
                    self.appendLookupEvent(
                        "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) speed_kmh=\(String(format: "%.1f", speedKmh)) hacc_m=\(String(format: "%.1f", hAcc)) speed=\(speedText) local_override=\(localOverrideText) way=\(wayText) street=\(streetText) city=\(cityText) inside_city=\(insideCityText) city_src=\(citySourceText) city_ms=\(String(format: "%.3f", result.cityResolveMs)) q_ms=\(String(format: "%.3f", result.queryTimeMs)) rows=\(result.candidateCount) speed_rows=\(result.speedCandidateCount) nearest_m=\(nearestText) nearest_speed_m=\(nearestSpeedText) tunnel_seg=\(tunnelSegmentText) tunnel_mode=\(tunnelModeText)"
                    )
                    self.appendGPSFixCSV(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: speedKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: rawCourse,
                        status: lookupStatus,
                        result: result,
                        speedLimitOverrideKmh: effectiveSpeedLimit,
                        errorText: nil
                    )
                    self.appendMatchLog(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: speedKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: rawCourse,
                        status: lookupStatus,
                        gpsSignalBars: self.gpsSignalBars,
                        tunnelModeState: self.tunnelModeState.rawValue,
                        result: result,
                        speedLimitOverrideKmh: effectiveSpeedLimit,
                        errorText: nil
                    )
                }
            } catch {
                await MainActor.run {
                    guard fixID == self.latestTrafficSignLookupFixID else { return }
                    self.trafficSignFrameContextIsCurrent = false
                    self.trafficSignFrameState.update(nil)
                    self.isUnlimitedSpeedLimitActive = false
                    self.lastLookupStatus = "error"
                    self.lastError = error.localizedDescription
                    self.wasDrivingBanWarningActive = false
                    self.resetTunnelModeTracking()
                    self.lastCandidateTraces = []
                    self.lastSelectionTrace = []
                    self.appendLookupEvent(
                        "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) speed_kmh=\(String(format: "%.1f", speedKmh)) hacc_m=\(String(format: "%.1f", hAcc)) lookup_error=\(error.localizedDescription)"
                    )
                    self.appendGPSFixCSV(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: speedKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: rawCourse,
                        status: "lookup_error",
                        result: nil,
                        errorText: error.localizedDescription
                    )
                    self.appendMatchLog(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: speedKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: rawCourse,
                        status: "lookup_error",
                        gpsSignalBars: self.gpsSignalBars,
                        tunnelModeState: self.tunnelModeState.rawValue,
                        result: nil,
                        errorText: error.localizedDescription
                    )
                }
            }
        }
    }

    private static func lookupRadius(forHorizontalAccuracy horizontalAccuracyM: Double) -> Double {
        guard horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0 else {
            return fallbackLookupRadiusM
        }
        let radius = (horizontalAccuracyM * lookupRadiusAccuracyMultiplier) + 20.0
        return min(max(radius, minLookupRadiusM), maxLookupRadiusM)
    }

    private static func gpsSignalBars(horizontalAccuracyM: Double) -> Int {
        guard horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0 else {
            return 0
        }
        switch horizontalAccuracyM {
        case ..<8:
            return 4
        case ..<15:
            return 3
        case ..<30:
            return 2
        case ..<60:
            return 1
        default:
            return 0
        }
    }

    private func resetDerivedSpeedTracking() {
        recentSpeedSampleLocations.removeAll(keepingCapacity: true)
        currentSpeedKmh = 0
    }

    private func updateCurrentSpeed(from location: CLLocation) -> Double {
        if let last = recentSpeedSampleLocations.last,
           location.timestamp <= last.timestamp {
            recentSpeedSampleLocations.removeAll(keepingCapacity: true)
        }

        recentSpeedSampleLocations.append(location)
        // Keep a short history so low-speed fallback can use recent displacement.
        recentSpeedSampleLocations.removeAll {
            location.timestamp.timeIntervalSince($0.timestamp) > Self.derivedSpeedComputationMaxWindowSeconds
        }

        let gpsSpeedKmh = max(0, location.speed) * 3.6
        let speedAccuracyKmh = location.speedAccuracy >= 0 ? location.speedAccuracy * 3.6 : nil
        let fallbackDerivedSpeedKmh: Double
        if let referenceLocation = recentSpeedSampleLocations.first {
            let elapsedSeconds = location.timestamp.timeIntervalSince(referenceLocation.timestamp)
            let accuracyAllowanceM = max(0, max(referenceLocation.horizontalAccuracy, location.horizontalAccuracy))
            if elapsedSeconds >= Self.derivedSpeedComputationMinWindowSeconds {
                fallbackDerivedSpeedKmh = Self.derivedSpeedKmh(
                    distanceM: location.distance(from: referenceLocation),
                    elapsedSeconds: elapsedSeconds,
                    accuracyAllowanceM: accuracyAllowanceM
                )
            } else {
                fallbackDerivedSpeedKmh = 0
            }
        } else {
            fallbackDerivedSpeedKmh = 0
        }

        let previousDisplaySpeedKmh = currentSpeedKmh
        currentSpeedKmh = Self.filteredDisplaySpeedKmh(
            rawSpeedKmh: gpsSpeedKmh,
            fallbackDerivedSpeedKmh: fallbackDerivedSpeedKmh,
            speedAccuracyKmh: speedAccuracyKmh,
            previousDisplaySpeedKmh: previousDisplaySpeedKmh
        )
        return currentSpeedKmh
    }

    nonisolated static func derivedSpeedKmh(
        distanceM: Double,
        elapsedSeconds: TimeInterval,
        accuracyAllowanceM: Double = 0
    ) -> Double {
        guard distanceM.isFinite,
              distanceM > 0,
              elapsedSeconds.isFinite,
              elapsedSeconds > 0 else {
            return 0
        }
        let adjustedDistanceM = max(0, distanceM - max(0, accuracyAllowanceM))
        guard adjustedDistanceM > 0 else {
            return 0
        }
        return (adjustedDistanceM / elapsedSeconds) * 3.6
    }

    nonisolated static func filteredDisplaySpeedKmh(
        rawSpeedKmh: Double,
        fallbackDerivedSpeedKmh: Double = 0,
        speedAccuracyKmh: Double?,
        previousDisplaySpeedKmh: Double
    ) -> Double {
        let normalizedRawSpeedKmh = rawSpeedKmh.isFinite && rawSpeedKmh > 0 ? rawSpeedKmh : 0
        let normalizedFallbackDerivedSpeedKmh = fallbackDerivedSpeedKmh.isFinite && fallbackDerivedSpeedKmh > 0
            ? fallbackDerivedSpeedKmh
            : 0
        if normalizedRawSpeedKmh < Self.lowSpeedDerivedFallbackThresholdKmh {
            return normalizedFallbackDerivedSpeedKmh
        }
        return normalizedRawSpeedKmh
    }

    private func appendLookupEvent(_ line: String) {
        lookupEventLog.insert(line, at: 0)
        if lookupEventLog.count > 200 {
            lookupEventLog.removeLast(lookupEventLog.count - 200)
        }
    }

    private func appendGPSFixCSV(
        fixID: Int,
        timestampISO: String,
        lat: Double,
        lon: Double,
        speedKmh: Double,
        horizontalAccM: Double,
        verticalAccM: Double,
        courseDeg: Double,
        status: String,
        result: SpeedLimitResult?,
        speedLimitOverrideKmh: Int? = nil,
        errorText: String?
    ) {
        guard let logURL = prepareGPSLogFileIfNeeded() else {
            return
        }

        let wayID = result?.wayID ?? ""
        let streetName = result?.streetName ?? ""
        let cityName = result?.cityName ?? ""
        let insideCity = result?.insideCity.map { $0 ? "1" : "0" } ?? ""
        let citySource = result?.citySource ?? ""
        let cityResolveMs = result.map { String(format: "%.3f", $0.cityResolveMs) } ?? ""
        let cityCandidateBoundaries = result.map { String($0.cityCandidateBoundaries) } ?? ""
        let cityContainingBoundaries = result.map { String($0.cityContainingBoundaries) } ?? ""
        let cityPlaceCandidates = result.map { String($0.cityPlaceCandidates) } ?? ""
        let speedLimit = speedLimitOverrideKmh.map(String.init) ?? result?.speedLimitKmh.map(String.init) ?? ""
        let queryMs = result.map { String(format: "%.3f", $0.queryTimeMs) } ?? ""
        let candidateCount = result.map { String($0.candidateCount) } ?? ""
        let speedCandidateCount = result.map { String($0.speedCandidateCount) } ?? ""
        let nearestCandidate = result?.nearestCandidateDistanceM.map { String(format: "%.2f", $0) } ?? ""
        let nearestSpeedCandidate = result?.nearestSpeedCandidateDistanceM.map { String(format: "%.2f", $0) } ?? ""

        let row: [String] = [
            "\(fixID)",
            timestampISO,
            String(format: "%.7f", lat),
            String(format: "%.7f", lon),
            String(format: "%.2f", speedKmh),
            String(format: "%.2f", horizontalAccM),
            String(format: "%.2f", verticalAccM),
            String(format: "%.2f", courseDeg),
            status,
            wayID,
            streetName,
            cityName,
            insideCity,
            citySource,
            cityResolveMs,
            cityCandidateBoundaries,
            cityContainingBoundaries,
            cityPlaceCandidates,
            speedLimit,
            queryMs,
            candidateCount,
            speedCandidateCount,
            nearestCandidate,
            nearestSpeedCandidate,
            errorText ?? "",
        ]
        let escaped = row.map(csvEscape).joined(separator: ",") + "\n"
        let payload = Data(escaped.utf8)

        do {
            let handle = try FileHandle(forWritingTo: logURL)
            try handle.seekToEnd()
            try handle.write(contentsOf: payload)
            try handle.close()
        } catch {
            // Keep lookup flow unaffected if file logging fails.
        }
    }

    private func appendMatchLog(
        fixID: Int,
        timestampISO: String,
        lat: Double,
        lon: Double,
        speedKmh: Double,
        horizontalAccM: Double,
        verticalAccM: Double,
        courseDeg: Double,
        status: String,
        gpsSignalBars: Int,
        tunnelModeState: String,
        result: SpeedLimitResult?,
        speedLimitOverrideKmh: Int? = nil,
        errorText: String?
    ) {
        guard let logURL = prepareMatchLogFileIfNeeded() else {
            return
        }
        let entry = DriveMatchLogEntry(
            fixID: fixID,
            timestampUTC: timestampISO,
            lat: lat,
            lon: lon,
            speedKmh: speedKmh,
            horizontalAccM: horizontalAccM,
            verticalAccM: verticalAccM,
            courseDeg: courseDeg,
            gpsSignalBars: gpsSignalBars,
            status: status,
            speedLimitOverrideKmh: speedLimitOverrideKmh,
            tunnelModeState: tunnelModeState,
            result: result,
            error: errorText
        )
        do {
            let payload = try JSONEncoder().encode(entry) + Data("\n".utf8)
            let handle = try FileHandle(forWritingTo: logURL)
            try handle.seekToEnd()
            try handle.write(contentsOf: payload)
            try handle.close()
        } catch {
            // Keep lookup flow unaffected if file logging fails.
        }
    }

    private func csvEscape(_ field: String) -> String {
        if field.contains(",") || field.contains("\"") || field.contains("\n") || field.contains("\r") {
            return "\"\(field.replacingOccurrences(of: "\"", with: "\"\""))\""
        }
        return field
    }

    private func prepareGPSLogFileIfNeeded() -> URL? {
        do {
            let base = try V3BundleManager.applicationSupportDirectory(fileManager: .default)
            if !FileManager.default.fileExists(atPath: base.path) {
                try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
            }
            let logURL = base.appendingPathComponent("gps_fix_log.csv")
            gpsLogPath = logURL.path

            if !hasPreparedGPSLogFile {
                if !FileManager.default.fileExists(atPath: logURL.path) {
                    try Data(Self.gpsLogCSVHeader.utf8).write(to: logURL, options: .atomic)
                }
                hasPreparedGPSLogFile = true
            }

            return logURL
        } catch {
            lastError = "gps log init failed: \(error.localizedDescription)"
            return nil
        }
    }

    private func prepareMatchLogFileIfNeeded() -> URL? {
        do {
            let base = try V3BundleManager.applicationSupportDirectory(fileManager: .default)
            if !FileManager.default.fileExists(atPath: base.path) {
                try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
            }
            let logURL: URL
            if let preparedMatchLogURL {
                logURL = preparedMatchLogURL
            } else {
                logURL = makeTimestampedMatchLogURL(in: base)
                preparedMatchLogURL = logURL
            }
            matchLogPath = logURL.path
            if !FileManager.default.fileExists(atPath: logURL.path) {
                try Data().write(to: logURL, options: .atomic)
            }
            return logURL
        } catch {
            lastError = "match log init failed: \(error.localizedDescription)"
            return nil
        }
    }

    private func resetPreparedMatchLogFile() {
        preparedMatchLogURL = nil
        matchLogPath = ""
    }

    private func makeTimestampedMatchLogURL(in base: URL) -> URL {
        let prefix = Self.exportTimestampFormatter.string(from: Date())
        for suffix in 0...999 {
            let filename: String
            if suffix == 0 {
                filename = "\(prefix)_drive_match_log.ndjson"
            } else {
                filename = "\(prefix)_\(suffix)_drive_match_log.ndjson"
            }
            let url = base.appendingPathComponent(filename)
            if !FileManager.default.fileExists(atPath: url.path) {
                return url
            }
        }
        return base.appendingPathComponent("\(prefix)_\(UUID().uuidString.lowercased())_drive_match_log.ndjson")
    }

    var currentOverspeedKmh: Int {
        guard !isUnlimitedSpeedLimitActive, let speedLimitKmh else {
            return 0
        }
        return max(0, Int(round(currentSpeedKmh)) - speedLimitKmh)
    }

    var currentPenaltyNotice: SpeedPenaltyNotice? {
        guard !isTunnelModeActive, !isUnlimitedSpeedLimitActive else {
            return nil
        }
        return SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: currentOverspeedKmh,
            rules: activePenaltyRules,
            insideCity: lastLookupInsideCity
        )
    }

    private func maybeSpeakOverspeedWarning() {
        guard driveStatus == "running" else {
            return
        }
        guard !isInSpeedCaptureMode else {
            return
        }
        guard audioAlertsEnabled else {
            lastAnnouncedSpeechText = nil
            return
        }
        let overspeed = currentOverspeedKmh
        let threshold = audioAlertThresholdKmh
        guard threshold > 0, overspeed >= threshold, let notice = currentPenaltyNotice else {
            lastAnnouncedSpeechText = nil
            return
        }
        if let drivingBanMonths = notice.drivingBanMonths, drivingBanMonths > 0 {
            return
        }

        let speechText: String
        switch notice.severity {
        case .moneyOnly:
            let currency = activePenaltyRules.currencyCode
            if let fineEUR = notice.moneyFineEUR {
                speechText = "\(fineEUR) \(currency)"
            } else {
                speechText = currency
            }
        case .pointsAndFine:
            if let points = notice.penaltyPoints {
                speechText = points == 1 ? "ein Punkt" : "\(points) Punkte"
            } else {
                speechText = "Punkte"
            }
        }

        let now = Date()
        let changedSignificantly = speechText != lastAnnouncedSpeechText
        let minimumInterval: TimeInterval = 8
        guard changedSignificantly || now.timeIntervalSince(lastAudioFeedbackAt) >= minimumInterval else {
            return
        }

        let utterance = AVSpeechUtterance(string: speechText)
        if let preferredLanguage = Locale.preferredLanguages.first {
            utterance.voice = AVSpeechSynthesisVoice(language: preferredLanguage)
        }
        utterance.rate = 0.48
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        speechSynthesizer.speak(utterance)
        lastAudioFeedbackAt = now
        lastAnnouncedSpeechText = speechText
    }

    private func maybeNotifyDrivingBanWarning() {
        guard driveStatus == "running" else {
            wasDrivingBanWarningActive = false
            return
        }
        guard !isInSpeedCaptureMode else {
            return
        }
        guard let notice = currentPenaltyNotice,
              let drivingBanMonths = notice.drivingBanMonths,
              drivingBanMonths > 0 else {
            wasDrivingBanWarningActive = false
            return
        }

        let now = Date()
        let enteringWarning = !wasDrivingBanWarningActive
        let enoughTimeElapsed = now.timeIntervalSince(lastDrivingBanWarningAt) >= Self.drivingBanWarningReminderInterval
        guard enteringWarning || enoughTimeElapsed else {
            return
        }

        let generator = UINotificationFeedbackGenerator()
        generator.prepare()
        generator.notificationOccurred(.warning)

        let speechText = drivingBanMonths == 1
            ? "Achtung. Ein Monat Fahrverbot moeglich."
            : "Achtung. \(drivingBanMonths) Monate Fahrverbot moeglich."
        if audioAlertsEnabled {
            if enteringWarning && speechSynthesizer.isSpeaking {
                speechSynthesizer.stopSpeaking(at: .immediate)
            }
            if enteringWarning || !speechSynthesizer.isSpeaking {
                let utterance = AVSpeechUtterance(string: speechText)
                if let preferredLanguage = Locale.preferredLanguages.first {
                    utterance.voice = AVSpeechSynthesisVoice(language: preferredLanguage)
                }
                utterance.rate = 0.46
                speechSynthesizer.speak(utterance)
            }
        }

        wasDrivingBanWarningActive = true
        lastDrivingBanWarningAt = now
    }
}

#if DEBUG
extension DriveSessionViewModel {
    func testResetLocalObservationStore() async throws {
        _ = try await localObservationStore.deleteAllObservations()
        await refreshLocalObservations()
        localObservationStatus = ""
        lastError = ""
        localObservationShareURL = nil
        lastExportDirectoryPath = ""
    }

    func testStoredLocalObservations(limit: Int = 50) async throws -> [LocalObservation] {
        try await localObservationStore.fetchObservations(limit: limit)
    }

    func testSimulateRecognizedSpeedCapture(transcript: String, source: String = "unit_test") async throws {
        speedCaptureMode = .listening
        speedCaptureLatestTranscript = transcript
        speedCaptureDidResolve = false
        finishSpeedCaptureListening(source: source)
        try await waitForTestSpeedCaptureToBecomeIdle()
    }

    func testSetActiveLocalSpeedCorrection(wayID: String, value: String, numericSpeedKmh: Int?) {
        activeLocalSpeedCorrection = ActiveLocalSpeedCorrection(
            wayID: wayID,
            maxspeedValue: value,
            numericSpeedKmh: numericSpeedKmh
        )
    }

    func testApplyActiveLocalSpeedCorrection(wayID: String?) -> String? {
        let result = SpeedLimitResult(
            speedLimitKmh: 50,
            isUnlimitedSpeedLimit: false,
            wayID: wayID,
            highway: nil,
            service: nil,
            tunnel: nil,
            bridge: nil,
            covered: nil,
            location: nil,
            layer: nil,
            level: nil,
            isTunnelSegment: false,
            streetName: nil,
            streetBaseName: nil,
            streetRef: nil,
            matchedEndpointProximityM: nil,
            cityName: nil,
            cityPlaceName: nil,
            cityDistrictName: nil,
            insideCity: nil,
            citySource: nil,
            cityResolveMs: 0,
            cityCandidateBoundaries: 0,
            cityContainingBoundaries: 0,
            cityPlaceCandidates: 0,
            queryTimeMs: 0,
            candidateCount: 0,
            speedCandidateCount: 0,
            nearestCandidateDistanceM: nil,
            nearestSpeedCandidateDistanceM: nil,
            nearbyTunnelCandidateWayIDs: [],
            nearbyTunnelCandidateRefs: [],
            usedMiniHMM: false,
            miniHMMCandidateCount: 0,
            matchHypotheses: [],
            candidateTraces: [],
            selectionTrace: [],
            activeCorridorState: nil
        )
        return applyActiveLocalSpeedCorrectionIfNeeded(for: result, lat: 0, lon: 0)
    }

    var testSpeedCaptureDidResolve: Bool {
        speedCaptureDidResolve
    }

    var testSpeedCaptureLatestTranscript: String {
        speedCaptureLatestTranscript
    }

    var testActiveLocalSpeedCorrectionWayID: String? {
        activeLocalSpeedCorrection?.wayID
    }

    private func waitForTestSpeedCaptureToBecomeIdle(timeoutNanoseconds: UInt64 = 2_000_000_000) async throws {
        let startedAt = DispatchTime.now().uptimeNanoseconds
        while DispatchTime.now().uptimeNanoseconds - startedAt < timeoutNanoseconds {
            if speedCaptureMode == .idle {
                return
            }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        throw ConsumerAppError.io("Timed out waiting for speed capture to become idle")
    }
}
#endif

extension DriveSessionViewModel: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.awaitingSpeedCapturePromptCompletion else {
                return
            }
            self.awaitingSpeedCapturePromptCompletion = false
            self.scheduleSpeedCaptureListeningStart()
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.awaitingSpeedCapturePromptCompletion else {
                return
            }
            self.awaitingSpeedCapturePromptCompletion = false
            self.scheduleSpeedCaptureListeningStart()
        }
    }
}

extension DriveSessionViewModel: @preconcurrency CLLocationManagerDelegate {
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard isDriving else {
            return
        }
        let auth = manager.authorizationStatus
        if auth == .authorizedWhenInUse || auth == .authorizedAlways {
            resetDerivedSpeedTracking()
            manager.startUpdatingLocation()
            driveStatus = "running"
        } else if auth == .denied || auth == .restricted {
            driveStatus = "location_denied"
            lastError = "Location permission denied"
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard !locations.isEmpty else {
            return
        }
        for location in locations {
            let displaySpeedKmh = updateCurrentSpeed(from: location)
            currentLatitude = location.coordinate.latitude
            currentLongitude = location.coordinate.longitude
            driveCaptureCoordinator?.ingest(location: location)
            gpsFixCount += 1
            maybeSpeakOverspeedWarning()
            let fixID = gpsFixCount
            beginTrafficSignContextLookup(fixID: fixID)
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                await updateSpeedLimit(for: location, fixID: fixID, speedKmh: displaySpeedKmh)
            }
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        driveStatus = "location_error"
        lastError = error.localizedDescription
    }
}

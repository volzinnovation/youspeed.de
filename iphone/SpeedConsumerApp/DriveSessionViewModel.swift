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
    @Published var panoramaxCaptureEnabled: Bool {
        didSet {
            guard panoramaxCaptureEnabled != oldValue else { return }
            UserDefaults.standard.set(panoramaxCaptureEnabled, forKey: Self.panoramaxCaptureEnabledDefaultsKey)
            if panoramaxCaptureEnabled, isDriving {
                panoramaxRecorder?.startRecording()
            } else if !panoramaxCaptureEnabled {
                panoramaxRecorder?.stopRecording()
            }
        }
    }
    @Published private(set) var panoramaxCaptureState: PanoramaxRecorderState = .disabled
    @Published private(set) var panoramaxCaptureCount = 0
    @Published private(set) var panoramaxLastCaptureAt: Date?
    @Published private(set) var panoramaxLastCaptureDetail = "Noch keine Aufnahme"
    @Published private(set) var panoramaxLastAccuracyMeters: Double?
    @Published private(set) var panoramaxBatches: [PanoramaxBatchRecord] = []
    @Published private(set) var panoramaxUploadStatusByBatch: [String: String] = [:]
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
    private var panoramaxRecorder: PanoramaxRecorder?
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
    private var activeLocalSpeedCorrection: ActiveLocalSpeedCorrection?
    private var limitStreetBaseName: String?
    private var limitStreetRef: String?
    private var tunnelModeTracker = TunnelModeTracker()
    private static let audioAlertThresholdDefaultsKey = "youspeed.audio_alert_threshold_kmh"
    private static let audioAlertsEnabledDefaultsKey = "youspeed.audio_alerts_enabled"
    private static let hideWelcomeScreenDefaultsKey = "youspeed.hide_welcome_screen"
    private static let panoramaxCaptureEnabledDefaultsKey = "youspeed.panoramax_capture_enabled"
    private static let matcherDebugProfileDefaultsKey = "youspeed.matcher_debug_profile"
    private static let matcherDebugProfileForcedVersionDefaultsKey = "youspeed.matcher_debug_profile_forced_version"
    private static let defaultAudioAlertThresholdKmh = 8
    private static let defaultAudioAlertsEnabled = true
    private static let defaultHideWelcomeScreen = false
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
        let storedPanoramaxCaptureEnabled = UserDefaults.standard.object(forKey: Self.panoramaxCaptureEnabledDefaultsKey) as? Bool
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
        panoramaxCaptureEnabled = storedPanoramaxCaptureEnabled ?? false
        matcherDebugProfile = initialMatcherProfile
        bundledTargetsConfig = try? V3BundleTargetsConfig.loadBundled()
        manifestEndpoints = Self.defaultManifestEndpoints()
        panoramaxAccount = PanoramaxAccountModel()
        let endpointCount = manifestEndpoints.count
        Self.logger.notice("sync endpoints configured count=\(endpointCount, privacy: .public)")
        super.init()
        panoramaxQueueStore = try? PanoramaxQueueStore()
        panoramaxRecorder = PanoramaxRecorder(queueStore: panoramaxQueueStore)
        panoramaxRecorder?.onChange = { [weak self] in
            self?.syncPanoramaxRecorderState()
        }
        syncPanoramaxRecorderState()
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

    var panoramaxPreviewSession: AVCaptureSession? {
        panoramaxRecorder?.session
    }

    private func syncPanoramaxRecorderState() {
        panoramaxCaptureState = panoramaxRecorder?.state ?? .failed
        panoramaxCaptureCount = panoramaxRecorder?.capturedImageCount ?? 0
        panoramaxLastCaptureAt = panoramaxRecorder?.lastCaptureAt
        panoramaxLastCaptureDetail = panoramaxRecorder?.lastCaptureDetail ?? "Panoramax-Speicher nicht verfuegbar"
        panoramaxLastAccuracyMeters = panoramaxRecorder?.lastAccuracyMeters
    }

    func refreshPanoramaxBatches() {
        panoramaxBatches = (try? panoramaxQueueStore?.listBatches()) ?? []
    }

    func panoramaxThumbnailURL(for item: PanoramaxItemRecord) -> URL? {
        panoramaxQueueStore?.thumbnailURL(for: item)
    }

    func panoramaxOriginalURL(for item: PanoramaxItemRecord) -> URL? {
        panoramaxQueueStore?.originalURL(for: item)
    }

    func setPanoramaxItemIncluded(batchID: String, itemID: String, included: Bool) {
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

    func deletePanoramaxItem(batchID: String, itemID: String) {
        do {
            try panoramaxQueueStore?.deleteItem(batchID: batchID, itemID: itemID)
            refreshPanoramaxBatches()
        } catch {
            panoramaxLastCaptureDetail = "Bild konnte nicht geloescht werden"
        }
    }

    func approvePanoramaxBatch(batchID: String) {
        do {
            guard var batch = try panoramaxQueueStore?.getBatch(batchID) else { return }
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

    func uploadPanoramaxBatch(batchID: String) {
        guard let origin = panoramaxAccount.normalizedOrigin,
              let token = panoramaxAccount.tokenForUpload() else {
            panoramaxUploadStatusByBatch[batchID] = "Panoramax-Konto verbinden und bestaetigen"
            return
        }
        guard let store = panoramaxQueueStore else {
            panoramaxUploadStatusByBatch[batchID] = "Batch zuerst fuer Upload freigeben"
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
              batch.state == .approved || batch.state == .partial else {
            panoramaxUploadStatusByBatch[batchID] = "Batch zuerst fuer Upload freigeben"
            return
        }
        let selected = batch.items.filter { $0.state != .excluded && $0.state != .uploaded && $0.state != .accepted }
        guard !selected.isEmpty else {
            panoramaxUploadStatusByBatch[batchID] = "Keine Bilder ausgewaehlt"
            return
        }
        batch.state = .creatingUploadSet
        batch.instanceOrigin = origin.absoluteString
        try? store.updateBatch(batch)
        refreshPanoramaxBatches()
        panoramaxUploadStatusByBatch[batchID] = "Upload wird vorbereitet"

        Task { @MainActor [weak self] in
            guard let self else { return }
            let client = PanoramaxUploadClient(origin: origin, token: token)
            do {
                let title = "YouSpeed \(batch.createdAt.formatted(date: .abbreviated, time: .shortened))"
                let uploadSet = try await client.createUploadSet(title: title, estimatedFileCount: selected.count)
                guard var current = try store.getBatch(batchID) else { return }
                current.remoteUploadSetID = uploadSet.id
                current.state = .uploading
                try store.updateBatch(current)
                refreshPanoramaxBatches()
                panoramaxUploadStatusByBatch[batchID] = "0/\(selected.count) Bilder werden uebertragen"

                var uploaded = 0
                for item in selected {
                    guard let fileURL = panoramaxOriginalURL(for: item) else { continue }
                    _ = try? store.updateItem(batchID: batchID, itemID: item.itemID, state: .uploading)
                    do {
                        try await client.upload(file: fileURL, uploadSetID: uploadSet.id, fileName: "\(item.itemID).jpg")
                        _ = try? store.updateItem(batchID: batchID, itemID: item.itemID, state: .uploaded)
                        uploaded += 1
                        panoramaxUploadStatusByBatch[batchID] = "\(uploaded)/\(selected.count) Bilder uebertragen"
                    } catch {
                        _ = try? store.updateItem(batchID: batchID, itemID: item.itemID, state: .retryableError)
                    }
                }

                guard var completed = try store.getBatch(batchID) else { return }
                completed.state = uploaded == selected.count ? .processing : .partial
                try store.updateBatch(completed)
                refreshPanoramaxBatches()
                guard uploaded == selected.count else {
                    panoramaxUploadStatusByBatch[batchID] = "\(uploaded)/\(selected.count) uebertragen – erneut versuchen"
                    return
                }
                _ = try await client.complete(uploadSetID: uploadSet.id)
                panoramaxUploadStatusByBatch[batchID] = "Panoramax verarbeitet den Batch"
                do {
                    _ = try await client.pollUntilReady(uploadSetID: uploadSet.id)
                    guard var ready = try store.getBatch(batchID) else { return }
                    ready.state = .complete
                    try store.updateBatch(ready)
                    panoramaxUploadStatusByBatch[batchID] = "Upload abgeschlossen"
                    refreshPanoramaxBatches()
                } catch {
                    panoramaxUploadStatusByBatch[batchID] = "Upload uebertragen – Verarbeitung laeuft weiter"
                }
            } catch {
                if var failed = try? store.getBatch(batchID) {
                    failed.state = .approved
                    try? store.updateBatch(failed)
                    refreshPanoramaxBatches()
                }
                panoramaxUploadStatusByBatch[batchID] = "Upload fehlgeschlagen: \(error.localizedDescription)"
            }
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
                localSpeedOverridesByWayID.removeAll(keepingCapacity: false)
                localSpeedOverrideValuesByWayID.removeAll(keepingCapacity: false)
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
        if panoramaxCaptureEnabled {
            panoramaxRecorder?.startRecording()
        }
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
        panoramaxRecorder?.stopRecording()
        locationManager.stopUpdatingLocation()
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
            localObservations = observations
            localSpeedOverridesByWayID = Self.resolveLocalSpeedOverrides(from: observations)
            localSpeedOverrideValuesByWayID = Self.resolveLocalSpeedOverrideValues(from: observations)
            localObservationStreetNames = resolveStreetNames(for: observations)
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
                }
                if let numericSpeed = observation.newSpeedKmh,
                   let wayID = observation.roadCandidateIDs.first,
                   !wayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    localSpeedOverridesByWayID[wayID] = numericSpeed
                    if limitWayID == wayID {
                        speedLimitKmh = numericSpeed
                        lastKnownSpeedLimitKmh = numericSpeed
                        isUnlimitedSpeedLimitActive = false
                    }
                }
                if let wayID = observation.roadCandidateIDs.first,
                   limitWayID == wayID {
                    if observation.newSpeedKmh == nil {
                        speedLimitKmh = nil
                    }
                    speedLimitDisplayText = Self.speedLimitDisplayText(for: selection.value)
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
        do {
            guard let route = try await bundleManager.resolveLocalBundleRoute(
                lat: lat,
                lon: lon,
                fallbackDBPath: activeDBPath.isEmpty ? nil : activeDBPath
            ) else {
                return
            }
            guard route.dbPath != activeDBPath else {
                return
            }
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
                    let propagatedOverrideValue = self.applyActiveLocalSpeedCorrectionIfNeeded(for: result, lat: lat, lon: lon)
                    let localOverrideValue = propagatedOverrideValue ?? result.wayID.flatMap { self.localSpeedOverrideValuesByWayID[$0] }
                    let localOverride = localOverrideValue.flatMap(Int.init)
                    let effectiveSpeedLimit = localOverride ?? result.speedLimitKmh
                    let unlimitedMatch = self.isGermanAutobahnUnlimitedMatch(result: result, localOverrideValue: localOverrideValue)
                    self.speedLimitKmh = effectiveSpeedLimit
                    self.speedLimitDisplayText = Self.speedLimitDisplayText(for: localOverrideValue)
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
            if panoramaxCaptureEnabled {
                panoramaxRecorder?.ingest(location: location)
            }
            gpsFixCount += 1
            maybeSpeakOverspeedWarning()
            let fixID = gpsFixCount
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

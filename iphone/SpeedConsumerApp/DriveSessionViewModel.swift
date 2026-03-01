import CoreLocation
import AVFoundation
import Foundation
import OSLog
import UIKit

struct TunnelModeTracker {
    enum State: String, Equatable {
        case inactive
        case active
        case awaitingSignalReturn
    }

    private(set) var state: State = .inactive
    private var consecutiveTunnelFixes = 0
    private var consecutiveNonTunnelFixes = 0

    mutating func reset() {
        state = .inactive
        consecutiveTunnelFixes = 0
        consecutiveNonTunnelFixes = 0
    }

    mutating func markSignalLost() {
        guard state == .active else {
            return
        }
        state = .awaitingSignalReturn
        consecutiveTunnelFixes = 0
        consecutiveNonTunnelFixes = 0
    }

    mutating func consumeFix(
        isTunnelSegment: Bool,
        nearTunnelPortal: Bool,
        tunnelPortalMarkersAvailable: Bool
    ) {
        if state == .awaitingSignalReturn {
            // Expected behavior for tunnel GPS shadowing: leave tunnel mode once
            // signal is back and continue with fresh evidence.
            state = .inactive
            consecutiveTunnelFixes = 0
            consecutiveNonTunnelFixes = 0
        }

        let tunnelEntryEvidence: Bool
        if tunnelPortalMarkersAvailable {
            tunnelEntryEvidence = isTunnelSegment && nearTunnelPortal
        } else {
            // Backward compatibility for older bundles without portal markers.
            tunnelEntryEvidence = isTunnelSegment
        }

        switch state {
        case .inactive:
            if tunnelEntryEvidence {
                consecutiveTunnelFixes += 1
                consecutiveNonTunnelFixes = 0
                if consecutiveTunnelFixes >= 2 {
                    state = .active
                    consecutiveTunnelFixes = 0
                }
            } else {
                consecutiveTunnelFixes = 0
                consecutiveNonTunnelFixes = 0
            }
        case .active:
            if isTunnelSegment {
                consecutiveNonTunnelFixes = 0
            } else {
                consecutiveNonTunnelFixes += 1
                if consecutiveNonTunnelFixes >= 2 {
                    reset()
                }
            }
        case .awaitingSignalReturn:
            break
        }
    }

    var isTunnelModeActive: Bool {
        state != .inactive
    }
}

@MainActor
final class DriveSessionViewModel: NSObject, ObservableObject {
    private nonisolated static let logger = Logger(subsystem: "de.youspeed.SpeedConsumer", category: "session")
    enum SpeedCaptureMode: Equatable {
        case idle
        case speakingPrompt
        case countdown(Int)
        case saving
    }

    enum StartupDataState: String {
        case loading
        case ready
        case failed
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
    @Published var limitWayID: String?
    @Published var limitStreetName: String?
    @Published var limitCityName: String?
    @Published var lastError: String = ""
    @Published var currentLatitude: Double?
    @Published var currentLongitude: Double?
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
    @Published var startupDataState: StartupDataState = .loading
    @Published var startupProgress: Double = 0
    @Published var startupDetail: String = "Lokale Daten werden vorbereitet"
    @Published var observationDraftVoiceCommand: String = ""
    @Published var localObservations: [LocalObservation] = []
    @Published var localObservationStreetNames: [String: String] = [:]
    @Published var localObservationStatus: String = ""
    @Published var lastExportDirectoryPath: String = ""
    @Published var localObservationShareURL: URL?
    @Published private(set) var speedCaptureMode: SpeedCaptureMode = .idle
    @Published private(set) var tunnelModeState: TunnelModeTracker.State = .inactive
    @Published private(set) var activePenaltyRules: SpeedPenaltyRuleSet
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

    private let bundleManager = V3BundleManager()
    private let localObservationStore = LocalObservationStore()
    private let locationManager = CLLocationManager()
    private let speechSynthesizer = AVSpeechSynthesizer()
    private let githubReleaseToken: String
    private let manifestURL: URL?
    private var speedLimitService: V3SpeedLimitService?
    private var isDriving = false
    private var hasPreparedGPSLogFile = false
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
    private var previousMatchedWayID: String?
    private var speedCaptureCountdownTask: Task<Void, Never>?
    private var speedCapturePromptFallbackTask: Task<Void, Never>?
    private var awaitingSpeedCapturePromptCompletion = false
    private var speedCaptureBaselineKmh: Int?
    private var speedCaptureRequiresStableVehicleSpeed = false
    private var lastKnownSpeedLimitKmh: Int?
    private var localSpeedOverridesByWayID: [String: Int] = [:]
    private var tunnelModeTracker = TunnelModeTracker()
    private var locationSignalMonitorTask: Task<Void, Never>?
    private var lastLocationFixAt = Date.distantPast
    private static let audioAlertThresholdDefaultsKey = "youspeed.audio_alert_threshold_kmh"
    private static let audioAlertsEnabledDefaultsKey = "youspeed.audio_alerts_enabled"
    private static let defaultAudioAlertThresholdKmh = 8
    private static let defaultAudioAlertsEnabled = true
    private static let drivingBanWarningReminderInterval: TimeInterval = 24
    private static let fallbackLookupRadiusM: Double = 50.0
    private static let minLookupRadiusM: Double = 50.0
    private static let maxLookupRadiusM: Double = 160.0
    private static let lookupRadiusAccuracyMultiplier: Double = 2.2
    private static let startupSeedActivationFloorProgress: Double = 0.92
    private static let tunnelGpsLossTimeoutSeconds: TimeInterval = 6
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

    static func defaultGitHubReleaseToken(bundle: Bundle = .main) -> String {
        defaultGitHubReleaseToken(infoDictionary: bundle.infoDictionary)
    }

    static func defaultGitHubReleaseToken(infoDictionary: [String: Any]?) -> String {
        let candidates = [
            "YOUSPEED_RELEASE_READ_TOKEN",
            "YouSpeedGitHubReleaseToken",
            "GITHUB_RELEASE_TOKEN",
        ]
        for key in candidates {
            guard let raw = infoDictionary?[key] as? String else {
                continue
            }
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty || trimmed.contains("$(") {
                continue
            }
            return trimmed
        }
        return ""
    }

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

    override init() {
        let storedThreshold = UserDefaults.standard.object(forKey: Self.audioAlertThresholdDefaultsKey) as? Int
        let storedAudioEnabled = UserDefaults.standard.object(forKey: Self.audioAlertsEnabledDefaultsKey) as? Bool
        let bundledRules = (try? SpeedPenaltyRuleSet.loadBundled(named: "DEU-rules")) ?? SpeedPenaltyRuleSet.fallbackDEU()
        activePenaltyRules = bundledRules
        audioAlertThresholdKmh = min(max(storedThreshold ?? Self.defaultAudioAlertThresholdKmh, 0), 80)
        audioAlertsEnabled = storedAudioEnabled ?? Self.defaultAudioAlertsEnabled
        githubReleaseToken = Self.defaultGitHubReleaseToken()
        manifestURL = Self.defaultManifestURL()
        super.init()
        locationManager.delegate = self
        speechSynthesizer.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.activityType = .automotiveNavigation
        locationManager.distanceFilter = 10
        beginStartupDataLoadIfNeeded()
        Task { @MainActor [weak self] in
            await self?.refreshLocalObservations()
        }
    }

    var isDatabaseReadyForQueries: Bool {
        startupDataState == .ready && speedLimitService != nil && !activeDBPath.isEmpty
    }

    var isSyncingNow: Bool {
        startupTask != nil || syncTask != nil || syncStatus == "syncing" || syncStatus == "bootstrapping"
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

    var speedCaptureSignText: String? {
        switch speedCaptureMode {
        case .idle:
            return nil
        case .speakingPrompt, .saving:
            return "?"
        case .countdown(let seconds):
            return "\(seconds)"
        }
    }

    func bootstrapAndSync() {
        guard startupTask == nil else {
            syncProgressDetail = "Startup data preparation is still running"
            Self.logger.notice("sync_request rejected reason=startup_task_running")
            return
        }
        guard syncTask == nil else {
            syncProgressDetail = "Sync already in progress"
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
                await bundleManager.setGitHubToken(githubReleaseToken)
                syncStatus = "bootstrapping"
                let bootstrap = try await bundleManager.bootstrapSeedIfNeeded()
                activeBundleVersion = bootstrap.bundleVersion
                activeDBPath = bootstrap.dbPath
                Self.logger.notice(
                    "sync bootstrap_ready version=\(bootstrap.bundleVersion, privacy: .public) db=\(bootstrap.dbPath, privacy: .public)"
                )

                guard let manifestURL else {
                    syncStatus = "seed_only"
                    if !activeDBPath.isEmpty {
                        speedLimitService = V3SpeedLimitService(dbPath: activeDBPath)
                    }
                    Self.logger.notice("sync seed_only no_manifest_url")
                    return
                }

                let manifestHost = manifestURL.host?.lowercased() ?? ""
                if githubReleaseToken.isEmpty,
                   (manifestHost.contains("github.com") || manifestHost.contains("githubusercontent.com")) {
                    syncStatus = "sync_failed"
                    lastError = "GitHub release token is missing in app configuration (YOUSPEED_RELEASE_READ_TOKEN)."
                    if !activeDBPath.isEmpty {
                        speedLimitService = V3SpeedLimitService(dbPath: activeDBPath)
                    }
                    Self.logger.error("sync failed missing_github_token")
                    return
                }

                syncStatus = "syncing"
                let sync = try await bundleManager.syncFromManifestURL(manifestURL) { progress in
                    Task { @MainActor [weak self] in
                        self?.applySyncProgress(progress)
                    }
                }
                activeBundleVersion = sync.bundleVersion
                activeDBPath = sync.dbPath
                speedLimitService = V3SpeedLimitService(dbPath: sync.dbPath)
                syncStatus = "ready_\(sync.mode.rawValue)"
                syncProgressStage = "completed"
                syncProgressDetail = "Sync completed"
                syncProgressBytesPerSecond = 0
                syncProgressETASeconds = 0
                syncPartDownloads = []
                lastError = ""
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
                    speedLimitService = V3SpeedLimitService(dbPath: activeDBPath)
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
                previousMatchedWayID = nil
                localSpeedOverridesByWayID.removeAll(keepingCapacity: false)
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
                await bundleManager.setGitHubToken(githubReleaseToken)
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
                    startupDetail = "Aktiviere Seed-Datenbank"
                    startupProgress = max(startupProgress, Self.startupSeedActivationFloorProgress)
                    Self.logger.notice("startup no_local_data_fallback=seed")
                    startupResult = try await bundleManager.bootstrapSeedIfNeeded()
                }

                activeBundleVersion = startupResult.bundleVersion
                activeDBPath = startupResult.dbPath
                if startupResult.dbPath.isEmpty {
                    throw ConsumerAppError.io("No local database available after startup recovery")
                }
                speedLimitService = V3SpeedLimitService(dbPath: startupResult.dbPath)
                syncStatus = "ready_\(startupResult.mode.rawValue)"
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
        if speedLimitService == nil {
            ensureSeedBootstrapIfNeeded()
        }
        isDriving = true
        resetTunnelModeTracking()
        lastLocationFixAt = Date.distantPast
        startLocationSignalMonitor()
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
        locationManager.stopUpdatingLocation()
        stopLocationSignalMonitor()
        driveStatus = "stopped"
        cancelSpeedCapture(reason: nil)
        resetTunnelModeTracking()
        lastAudioFeedbackAt = .distantPast
        lastAnnouncedSpeechText = nil
        wasDrivingBanWarningActive = false
        lastDrivingBanWarningAt = .distantPast
        previousMatchedWayID = nil
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

    private func startLocationSignalMonitor() {
        locationSignalMonitorTask?.cancel()
        locationSignalMonitorTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard let self else {
                    return
                }
                guard self.driveStatus == "running" else {
                    continue
                }
                guard self.tunnelModeTracker.state == .active else {
                    continue
                }
                let silence = Date().timeIntervalSince(self.lastLocationFixAt)
                if silence >= Self.tunnelGpsLossTimeoutSeconds {
                    self.tunnelModeTracker.markSignalLost()
                    self.syncTunnelModePublishedState()
                    self.lastLookupStatus = "gps_shadow_tunnel"
                }
            }
        }
    }

    private func stopLocationSignalMonitor() {
        locationSignalMonitorTask?.cancel()
        locationSignalMonitorTask = nil
    }

    func resetDiagnostics() {
        lookupEventLog.removeAll(keepingCapacity: false)
        gpsFixCount = 0
        previousMatchedWayID = nil
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
        resetTunnelModeTracking()
        lastLocationFixAt = Date.distantPast

        guard let logURL = prepareGPSLogFileIfNeeded() else {
            return
        }
        do {
            let header = "fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m,vacc_m,course_deg,status,way_id,street_name,city_name,inside_city,city_source,city_resolve_ms,city_candidate_boundaries,city_containing_boundaries,city_place_candidates,speed_limit_kmh,query_ms,candidate_count,speed_candidate_count,nearest_candidate_m,nearest_speed_candidate_m,error\n"
            try Data(header.utf8).write(to: logURL, options: .atomic)
        } catch {
            lastError = "gps log reset failed: \(error.localizedDescription)"
        }
    }

    func beginSpeedLimitCapture() {
        guard !isInSpeedCaptureMode else {
            return
        }

        let roundedCurrentSpeed = max(0, Int(round(currentSpeedKmh)))
        let currentLimit = max(0, speedLimitKmh ?? 0)
        let rememberedLimit = max(0, lastKnownSpeedLimitKmh ?? 0)
        let baseline: Int?
        if roundedCurrentSpeed > 0 {
            baseline = roundedCurrentSpeed
            speedCaptureRequiresStableVehicleSpeed = true
        } else if currentLimit > 0 {
            baseline = currentLimit
            speedCaptureRequiresStableVehicleSpeed = false
        } else if rememberedLimit > 0 {
            baseline = rememberedLimit
            speedCaptureRequiresStableVehicleSpeed = false
        } else {
            baseline = nil
            speedCaptureRequiresStableVehicleSpeed = false
        }

        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        speedCaptureBaselineKmh = baseline
        speedCaptureMode = .speakingPrompt
        awaitingSpeedCapturePromptCompletion = true
        localObservationStatus = baseline != nil
            ? "Geschwindigkeitserfassung gestartet."
            : "Geschwindigkeitserfassung gestartet, aber keine Referenzgeschwindigkeit erkannt."
        let utterance = AVSpeechUtterance(string: "Geschwindigkeit erfassen, Regelgeschwindigkeit 5 Sekunden halten")
        utterance.voice = AVSpeechSynthesisVoice(language: "de-DE")
            ?? AVSpeechSynthesisVoice(language: Locale.preferredLanguages.first ?? "de-DE")
        utterance.rate = 0.46
        speechSynthesizer.speak(utterance)

        speedCapturePromptFallbackTask?.cancel()
        speedCapturePromptFallbackTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard !Task.isCancelled else {
                return
            }
            await MainActor.run {
                guard let self, self.awaitingSpeedCapturePromptCompletion else {
                    return
                }
                self.awaitingSpeedCapturePromptCompletion = false
                self.startSpeedCaptureCountdown()
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
            resolver = V3SpeedLimitService(dbPath: activeDBPath)
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
        if speedLimitKmh != nil {
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

    private func startSpeedCaptureCountdown() {
        speedCaptureCountdownTask?.cancel()
        speedCaptureMode = .countdown(5)
        speedCaptureCountdownTask = Task { [weak self] in
            guard let self else {
                return
            }
            for second in stride(from: 5, through: 1, by: -1) {
                let abort = await MainActor.run { () -> Bool in
                    if self.speedCaptureRequiresStableVehicleSpeed {
                        guard let baseline = self.speedCaptureBaselineKmh else {
                            self.cancelSpeedCapture(reason: "Keine Referenzgeschwindigkeit erkannt. Bitte erneut starten.")
                            return true
                        }
                        let current = Int(round(self.currentSpeedKmh))
                        if abs(current - baseline) > 3 {
                            self.cancelSpeedCapture(reason: "Geschwindigkeit nicht stabil gehalten. Bitte erneut starten.")
                            return true
                        }
                    }
                    self.speedCaptureMode = .countdown(second)
                    return false
                }
                if abort || Task.isCancelled {
                    return
                }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
            await MainActor.run {
                self.commitSpeedCaptureObservation()
            }
        }
    }

    private func commitSpeedCaptureObservation() {
        speedCaptureMode = .saving
        let newSpeed = speedCaptureBaselineKmh
            ?? speedLimitKmh
            ?? lastKnownSpeedLimitKmh
            ?? Int(round(currentSpeedKmh))
        let oldSpeed = speedLimitKmh
        Task { @MainActor [weak self] in
            guard let self else {
                return
            }
            defer { cancelSpeedCapture(reason: nil) }
            guard newSpeed > 0 else {
                localObservationStatus = "Erfassung abgebrochen: ungueltige Geschwindigkeit."
                return
            }
            do {
                let observation = try await localObservationStore.recordSpeedLimitChange(
                    oldSpeedKmh: oldSpeed,
                    newSpeedKmh: newSpeed,
                    context: currentObservationCaptureContext()
                )
                if let wayID = observation.roadCandidateIDs.first,
                   !wayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    localSpeedOverridesByWayID[wayID] = newSpeed
                    if limitWayID == wayID {
                        speedLimitKmh = newSpeed
                        lastKnownSpeedLimitKmh = newSpeed
                    }
                }
                let way = observation.roadCandidateIDs.first ?? "n/a"
                localObservationStatus = "Erfasst: way \(way), alt \(oldSpeed?.description ?? "n/a"), neu \(newSpeed) km/h."
                await refreshLocalObservations()
            } catch {
                localObservationStatus = "Erfassung fehlgeschlagen: \(error.localizedDescription)"
                lastError = localObservationStatus
            }
        }
    }

    private func cancelSpeedCapture(reason: String?) {
        speedCaptureCountdownTask?.cancel()
        speedCaptureCountdownTask = nil
        speedCapturePromptFallbackTask?.cancel()
        speedCapturePromptFallbackTask = nil
        awaitingSpeedCapturePromptCompletion = false
        speedCaptureBaselineKmh = nil
        speedCaptureRequiresStableVehicleSpeed = false
        speedCaptureMode = .idle
        if let reason, !reason.isEmpty {
            localObservationStatus = reason
        }
    }

    private func updateSpeedLimit(for location: CLLocation, fixID: Int) {
        let fixTimestamp = Self.lookupTimestampFormatter.string(from: location.timestamp)
        let fixTimestampISO = Self.isoFormatter.string(from: location.timestamp)
        let lat = location.coordinate.latitude
        let lon = location.coordinate.longitude
        let gpsKmh = max(0, location.speed) * 3.6
        let hAcc = location.horizontalAccuracy
        let vAcc = location.verticalAccuracy
        let rawCourse = location.course
        let course = (0.0 ... 360.0).contains(rawCourse) ? rawCourse : nil
        let rawCourseAccuracy = location.courseAccuracy
        let courseAccuracy = rawCourseAccuracy >= 0.0 ? rawCourseAccuracy : nil
        guard let service = speedLimitService else {
            wasDrivingBanWarningActive = false
            appendLookupEvent(
                "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) gps_kmh=\(String(format: "%.1f", gpsKmh)) hacc_m=\(String(format: "%.1f", hAcc)) status=no_service"
            )
            appendGPSFixCSV(
                fixID: fixID,
                timestampISO: fixTimestampISO,
                lat: lat,
                lon: lon,
                speedKmh: gpsKmh,
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
        let preferredWayID = previousMatchedWayID

        Task.detached(priority: .utility) {
            do {
                let result = try service.lookupSpeedLimit(
                    lat: lat,
                    lon: lon,
                    radiusM: radiusM,
                    maxCandidates: maxCandidates,
                    preferredWayID: preferredWayID,
                    headingDeg: course,
                    headingAccuracyDeg: courseAccuracy,
                    speedKmh: gpsKmh,
                    horizontalAccuracyM: hAcc
                )
                await MainActor.run {
                    self.lastLocationFixAt = Date()
                    let localOverride = result.wayID.flatMap { self.localSpeedOverridesByWayID[$0] }
                    let effectiveSpeedLimit = localOverride ?? result.speedLimitKmh
                    self.speedLimitKmh = effectiveSpeedLimit
                    if let resolved = effectiveSpeedLimit {
                        self.lastKnownSpeedLimitKmh = resolved
                    }
                    self.limitWayID = result.wayID
                    self.limitStreetName = result.streetName
                    self.limitCityName = result.cityName
                    self.tunnelModeTracker.consumeFix(
                        isTunnelSegment: result.isTunnelSegment,
                        nearTunnelPortal: result.nearTunnelPortal,
                        tunnelPortalMarkersAvailable: result.tunnelPortalMarkersAvailable
                    )
                    self.syncTunnelModePublishedState()
                    if let wayID = result.wayID {
                        self.previousMatchedWayID = wayID
                    }
                    self.maybeNotifyDrivingBanWarning()
                    self.maybeSpeakOverspeedWarning()
                    let lookupStatus: String
                    if effectiveSpeedLimit == nil {
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
                    let tunnelPortalText = result.nearTunnelPortal ? "1" : "0"
                    let tunnelPortalDistanceText = result.tunnelPortalDistanceM.map { String(format: "%.1f", $0) } ?? "nil"
                    let localOverrideText = localOverride.map(String.init) ?? "nil"
                    self.appendLookupEvent(
                        "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) gps_kmh=\(String(format: "%.1f", gpsKmh)) hacc_m=\(String(format: "%.1f", hAcc)) speed=\(speedText) local_override=\(localOverrideText) way=\(wayText) street=\(streetText) city=\(cityText) inside_city=\(insideCityText) city_src=\(citySourceText) city_ms=\(String(format: "%.3f", result.cityResolveMs)) q_ms=\(String(format: "%.3f", result.queryTimeMs)) rows=\(result.candidateCount) speed_rows=\(result.speedCandidateCount) nearest_m=\(nearestText) nearest_speed_m=\(nearestSpeedText) tunnel_seg=\(tunnelSegmentText) tunnel_mode=\(tunnelModeText) near_portal=\(tunnelPortalText) portal_m=\(tunnelPortalDistanceText)"
                    )
                    self.appendGPSFixCSV(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: gpsKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: rawCourse,
                        status: lookupStatus,
                        result: result,
                        speedLimitOverrideKmh: effectiveSpeedLimit,
                        errorText: nil
                    )
                }
            } catch {
                await MainActor.run {
                    self.lastLookupStatus = "error"
                    self.lastError = error.localizedDescription
                    self.wasDrivingBanWarningActive = false
                    self.appendLookupEvent(
                        "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) gps_kmh=\(String(format: "%.1f", gpsKmh)) hacc_m=\(String(format: "%.1f", hAcc)) lookup_error=\(error.localizedDescription)"
                    )
                    self.appendGPSFixCSV(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: gpsKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: rawCourse,
                        status: "lookup_error",
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
                    let header = "fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m,vacc_m,course_deg,status,way_id,street_name,city_name,inside_city,city_source,city_resolve_ms,city_candidate_boundaries,city_containing_boundaries,city_place_candidates,speed_limit_kmh,query_ms,candidate_count,speed_candidate_count,nearest_candidate_m,nearest_speed_candidate_m,error\n"
                    try Data(header.utf8).write(to: logURL, options: .atomic)
                }
                hasPreparedGPSLogFile = true
            }

            return logURL
        } catch {
            lastError = "gps log init failed: \(error.localizedDescription)"
            return nil
        }
    }

    var currentOverspeedKmh: Int {
        guard let speedLimitKmh else {
            return 0
        }
        return max(0, Int(round(currentSpeedKmh)) - speedLimitKmh)
    }

    var currentPenaltyNotice: SpeedPenaltyNotice? {
        guard !isTunnelModeActive else {
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
            if let fineEUR = notice.moneyFineEUR {
                speechText = "\(fineEUR) Euro"
            } else {
                speechText = "Euro"
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

extension DriveSessionViewModel: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.awaitingSpeedCapturePromptCompletion else {
                return
            }
            self.awaitingSpeedCapturePromptCompletion = false
            self.startSpeedCaptureCountdown()
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.awaitingSpeedCapturePromptCompletion else {
                return
            }
            self.awaitingSpeedCapturePromptCompletion = false
            self.startSpeedCaptureCountdown()
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
            currentSpeedKmh = max(0, location.speed) * 3.6
            currentLatitude = location.coordinate.latitude
            currentLongitude = location.coordinate.longitude
            lastLocationFixAt = Date()
            gpsFixCount += 1
            maybeSpeakOverspeedWarning()
            updateSpeedLimit(for: location, fixID: gpsFixCount)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        if tunnelModeTracker.state == .active {
            tunnelModeTracker.markSignalLost()
            syncTunnelModePublishedState()
            lastLookupStatus = "gps_shadow_tunnel"
            return
        }
        driveStatus = "location_error"
        lastError = error.localizedDescription
    }
}

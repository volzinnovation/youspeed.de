import CoreLocation
import AVFoundation
import Foundation
import OSLog
import UIKit

@MainActor
final class DriveSessionViewModel: NSObject, ObservableObject {
    private nonisolated static let logger = Logger(subsystem: "de.youspeed.SpeedConsumer", category: "session")
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

    private let bundleManager = V3BundleManager()
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
    private static let audioAlertThresholdDefaultsKey = "youspeed.audio_alert_threshold_kmh"
    private static let defaultAudioAlertThresholdKmh = 8
    private static let drivingBanWarningReminderInterval: TimeInterval = 24
    private static let defaultLookupRadiusM: Double = 50.0
    private static let startupSeedActivationFloorProgress: Double = 0.92
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
        let bundledRules = (try? SpeedPenaltyRuleSet.loadBundled(named: "DEU-rules")) ?? SpeedPenaltyRuleSet.fallbackDEU()
        activePenaltyRules = bundledRules
        audioAlertThresholdKmh = min(max(storedThreshold ?? Self.defaultAudioAlertThresholdKmh, 0), 80)
        githubReleaseToken = Self.defaultGitHubReleaseToken()
        manifestURL = Self.defaultManifestURL()
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.activityType = .automotiveNavigation
        locationManager.distanceFilter = 10
        beginStartupDataLoadIfNeeded()
    }

    var isDatabaseReadyForQueries: Bool {
        startupDataState == .ready && speedLimitService != nil && !activeDBPath.isEmpty
    }

    var isSyncingNow: Bool {
        startupTask != nil || syncTask != nil || syncStatus == "syncing" || syncStatus == "bootstrapping"
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
        driveStatus = "stopped"
        lastAudioFeedbackAt = .distantPast
        lastAnnouncedSpeechText = nil
        wasDrivingBanWarningActive = false
        lastDrivingBanWarningAt = .distantPast
        previousMatchedWayID = nil
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
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

    private func updateSpeedLimit(for location: CLLocation, fixID: Int) {
        let fixTimestamp = Self.lookupTimestampFormatter.string(from: location.timestamp)
        let fixTimestampISO = Self.isoFormatter.string(from: location.timestamp)
        let lat = location.coordinate.latitude
        let lon = location.coordinate.longitude
        let gpsKmh = max(0, location.speed) * 3.6
        let hAcc = location.horizontalAccuracy
        let vAcc = location.verticalAccuracy
        let course = location.course
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
                courseDeg: course,
                status: "no_service",
                result: nil,
                errorText: nil
            )
            return
        }
        let radiusM = Self.defaultLookupRadiusM
        let maxCandidates = lookupMaxCandidates
        let preferredWayID = previousMatchedWayID

        Task.detached(priority: .utility) {
            do {
                let result = try service.lookupSpeedLimit(
                    lat: lat,
                    lon: lon,
                    radiusM: radiusM,
                    maxCandidates: maxCandidates,
                    preferredWayID: preferredWayID
                )
                await MainActor.run {
                    self.speedLimitKmh = result.speedLimitKmh
                    self.limitWayID = result.wayID
                    self.limitStreetName = result.streetName
                    self.limitCityName = result.cityName
                    if let wayID = result.wayID {
                        self.previousMatchedWayID = wayID
                    }
                    self.maybeNotifyDrivingBanWarning()
                    self.maybeSpeakOverspeedWarning()
                    self.lastLookupStatus = result.speedLimitKmh == nil ? "no_match" : "matched"
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
                    let speedText = result.speedLimitKmh.map(String.init) ?? "nil"
                    let wayText = result.wayID ?? "nil"
                    let streetText = result.streetName ?? "nil"
                    let cityText = result.cityName ?? "nil"
                    let insideCityText = result.insideCity.map { $0 ? "1" : "0" } ?? "nil"
                    let citySourceText = result.citySource ?? "nil"
                    let nearestText = result.nearestCandidateDistanceM.map { String(format: "%.1f", $0) } ?? "nil"
                    let nearestSpeedText = result.nearestSpeedCandidateDistanceM.map { String(format: "%.1f", $0) } ?? "nil"
                    self.appendLookupEvent(
                        "\(fixTimestamp) fix=\(fixID) lat=\(String(format: "%.5f", lat)) lon=\(String(format: "%.5f", lon)) gps_kmh=\(String(format: "%.1f", gpsKmh)) hacc_m=\(String(format: "%.1f", hAcc)) speed=\(speedText) way=\(wayText) street=\(streetText) city=\(cityText) inside_city=\(insideCityText) city_src=\(citySourceText) city_ms=\(String(format: "%.3f", result.cityResolveMs)) q_ms=\(String(format: "%.3f", result.queryTimeMs)) rows=\(result.candidateCount) speed_rows=\(result.speedCandidateCount) nearest_m=\(nearestText) nearest_speed_m=\(nearestSpeedText)"
                    )
                    self.appendGPSFixCSV(
                        fixID: fixID,
                        timestampISO: fixTimestampISO,
                        lat: lat,
                        lon: lon,
                        speedKmh: gpsKmh,
                        horizontalAccM: hAcc,
                        verticalAccM: vAcc,
                        courseDeg: course,
                        status: result.speedLimitKmh == nil ? "no_match" : "matched",
                        result: result,
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
                        courseDeg: course,
                        status: "lookup_error",
                        result: nil,
                        errorText: error.localizedDescription
                    )
                }
            }
        }
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
        let speedLimit = result?.speedLimitKmh.map(String.init) ?? ""
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
        SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: currentOverspeedKmh,
            rules: activePenaltyRules,
            insideCity: lastLookupInsideCity
        )
    }

    private func maybeSpeakOverspeedWarning() {
        guard driveStatus == "running" else {
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
                speechText = points == 1 ? "1 Punkt" : "\(points) Punkte"
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

        wasDrivingBanWarningActive = true
        lastDrivingBanWarningAt = now
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
            gpsFixCount += 1
            maybeSpeakOverspeedWarning()
            updateSpeedLimit(for: location, fixID: gpsFixCount)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        driveStatus = "location_error"
        lastError = error.localizedDescription
    }
}

package de.youspeed.android.alpha

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.media.AudioManager
import android.media.ToneGenerator
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import java.util.zip.InflaterInputStream
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model

enum class StartupDataState {
    LOADING,
    READY,
    FAILED,
}

enum class TunnelModeState {
    INACTIVE,
    ACTIVE,
}

data class LocalObservation(
    val id: String,
    val modality: LocalObservationModality,
    val intentType: LocalObservationIntentType,
    val value: String?,
    val lat: Double?,
    val lon: Double?,
    val headingDeg: Double?,
    val roadCandidateIds: List<String>,
    val cityContext: String?,
    val streetContext: String?,
    val capturedAtUTC: String,
    val confidenceCalibrated: Double?,
    val sourceVersion: String,
    val state: LocalObservationState,
    val devicePseudoId: String,
    val updatedAtUTC: String,
    val exportId: String?,
    val oldSpeedKmh: Int?,
    val newSpeedKmh: Int?,
) {
    val streetName: String
        get() = streetContext?.trim().orEmpty().ifBlank { "Strassenname n/a" }

    val wayId: String?
        get() = roadCandidateIds.firstOrNull()?.trim()?.ifBlank { null }

    val newSpeedValue: String?
        get() = value?.trim()?.ifBlank { null } ?: newSpeedKmh?.toString()
}

private data class ActiveLocalSpeedCorrection(
    val maxspeedValue: String,
    val numericSpeedKmh: Int?,
    val anchorStreetName: String?,
    val anchorRef: String?,
    val wayIds: Set<String>,
)

private data class PendingStartupData(
    val startupDetail: String,
    val activeBundleVersion: String,
    val activeDBPath: String,
    val activePenaltyRules: ActivePenaltyRules,
    val syncStatus: String,
    val localObservations: List<LocalObservation>,
)

data class ConsumerUiState(
    val startupDataState: StartupDataState = StartupDataState.LOADING,
    val startupProgress: Double = 0.0,
    val startupDetail: String = "Lokale Daten werden vorbereitet",
    val syncStatus: String = "not_synced",
    val syncProgressDetail: String = "",
    val maintenanceMessage: String = "",
    val activeBundleVersion: String = "none",
    val activeDBPath: String = "",
    val currentSpeedKmh: Double = 0.0,
    val speedLimitKmh: Int? = null,
    val speedLimitDisplayText: String? = null,
    val isUnlimitedSpeedLimitActive: Boolean = false,
    val limitWayId: String? = null,
    val limitStreetName: String? = null,
    val limitStreetBaseName: String? = null,
    val limitStreetRef: String? = null,
    val limitCityName: String? = null,
    val currentLatitude: Double? = null,
    val currentLongitude: Double? = null,
    val gpsHorizontalAccuracyM: Double? = null,
    val gpsSignalBars: Int = 0,
    val gpsFixCount: Int = 0,
    val gpsLogPath: String = "",
    val matchLogPath: String = "",
    val lastLookupQueryMs: Double = 0.0,
    val lastLookupCandidateCount: Int = 0,
    val lastLookupSpeedCandidateCount: Int = 0,
    val lastLookupNearestCandidateM: Double? = null,
    val lastLookupNearestSpeedCandidateM: Double? = null,
    val lastLookupCitySource: String = "n/a",
    val driveStatus: String = "stopped",
    val lastError: String = "",
    val legalText: String = "",
    val audioAlertsEnabled: Boolean = true,
    val audioAlertThresholdKmh: Int = 8,
    val hideWelcomeScreen: Boolean = false,
    val bundleDownloadSections: List<BundleDownloadCountrySection> = emptyList(),
    val downloadedBundleCountByRegion: Map<String, Int> = emptyMap(),
    val downloadedBundleLatestVersionByRegion: Map<String, String> = emptyMap(),
    val configuredManifestEndpointCount: Int = 0,
    val configuredManifestCountryCodes: String = "n/a",
    val hasGitHubReleaseToken: Boolean = false,
    val activePenaltyRules: ActivePenaltyRules = ActivePenaltyRules.fallback(),
    val localObservations: List<LocalObservation> = emptyList(),
    val localObservationStatus: String = "",
    val speedCaptureMode: SpeedCaptureModeState = SpeedCaptureModeState.IDLE,
    val speedCaptureTranscript: String = "",
    val germanSpeechModelState: GermanSpeechModelState = GermanSpeechModelState.CHECKING,
    val germanSpeechModelStatus: String = "Gebuendeltes deutsches Offline-Sprachmodell wird vorbereitet.",
    val lastExportDirectoryPath: String = "",
    val appScreenshotState: AppScreenshotState? = null,
    val lastLookupInsideCity: Boolean? = null,
    val tunnelModeState: TunnelModeState = TunnelModeState.INACTIVE,
    val isLowSpeedMatchingRuleActive: Boolean = false,
    val matcherDebugProfile: MatcherDebugProfile = MatcherDebugProfile.default,
) {
    val isDatabaseReadyForQueries: Boolean
        get() = startupDataState == StartupDataState.READY && activeDBPath.isNotBlank()
}

data class BundleDownloadOption(
    val id: String,
    val countryCode: String,
    val countryName: String,
    val displayName: String,
    val endpoint: V3ManifestEndpoint,
)

data class BundleDownloadCountrySection(
    val id: String,
    val countryCode: String,
    val countryName: String,
    val options: List<BundleDownloadOption>,
)

data class AppScreenshotFixture(
    val currentSpeedKmh: Double,
    val speedLimitKmh: Int?,
    val speedLimitDisplayText: String?,
    val isUnlimitedSpeedLimitActive: Boolean,
    val streetName: String,
    val cityName: String,
    val wayId: String,
    val insideCity: Boolean,
    val latitude: Double,
    val longitude: Double,
    val gpsHorizontalAccuracyM: Double,
    val gpsSignalBars: Int,
)

enum class AppScreenshotState(val rawValue: String) {
    WARN_LEVEL_0("warn-level-0"),
    WARN_LEVEL_1("warn-level-1"),
    WARN_LEVEL_2("warn-level-2"),
    WARN_LEVEL_3("warn-level-3"),
    PEDESTRIAN_ZONE("pedestrian-zone"),
    AUTOBAHN_UNLIMITED_ABOVE_130("autobahn-unlimited-above-130");

    val fixture: AppScreenshotFixture
        get() = when (this) {
            WARN_LEVEL_0 -> AppScreenshotFixture(47.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-0", true, 49.0102, 8.4266, 6.0, 4)
            WARN_LEVEL_1 -> AppScreenshotFixture(67.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-1", true, 49.0102, 8.4266, 6.0, 4)
            WARN_LEVEL_2 -> AppScreenshotFixture(73.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-2", true, 49.0102, 8.4266, 6.0, 4)
            WARN_LEVEL_3 -> AppScreenshotFixture(86.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-3", true, 49.0102, 8.4266, 6.0, 4)
            PEDESTRIAN_ZONE -> AppScreenshotFixture(5.0, null, "Schritt", false, "Im Kloster", "Bad Herrenalb", "bad-herrenalb-pedestrian-zone", true, 48.7966, 8.4361, 5.0, 4)
            AUTOBAHN_UNLIMITED_ABOVE_130 -> AppScreenshotFixture(142.0, null, null, true, "A 5", "Karlsruhe", "autobahn-unlimited-130-plus", false, 49.0180, 8.3501, 5.0, 4)
        }

    companion object {
        fun fromRaw(raw: String?): AppScreenshotState? {
            val normalized = raw?.trim()?.lowercase(Locale.US).orEmpty()
            return entries.firstOrNull { it.rawValue == normalized }
        }
    }
}

object ConsumerAppLogic {
    private val ymdFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    private val compactFormatter = DateTimeFormatter.ofPattern("yyyyMMdd")

    fun requiresWelcome(bundleVersion: String, now: Instant): Boolean {
        val normalized = bundleVersion.trim().lowercase(Locale.US)
        if (normalized.isEmpty() || normalized == "none" || normalized == "seed") {
            return true
        }
        val bundleDate = parseBundleDate(normalized) ?: return true
        val bundleInstant = bundleDate.atStartOfDay().toInstant(ZoneOffset.UTC)
        val ageSeconds = now.epochSecond - bundleInstant.epochSecond
        return ageSeconds > 30L * 24L * 60L * 60L
    }

    fun parseBundleDate(version: String): LocalDate? {
        val longMatch = Regex("""\d{4}-\d{2}-\d{2}""").find(version)?.value
        if (longMatch != null) {
            return runCatching { LocalDate.parse(longMatch, ymdFormatter) }.getOrNull()
        }
        val compactMatch = Regex("""\d{8}""").find(version)?.value
        if (compactMatch != null) {
            return runCatching { LocalDate.parse(compactMatch, compactFormatter) }.getOrNull()
        }
        return null
    }
}

class ConsumerSessionController(
    context: Context,
    private val rootDir: File,
    private val preferences: SharedPreferences,
    private val clock: Clock,
    launchScreenshotState: AppScreenshotState?,
) {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val assetReader = AndroidAssetReader(appContext)
    private val githubReleaseToken = BuildConfig.YOUSPEED_RELEASE_READ_TOKEN.trim()
    private val bootstrapper = BundleBootstrapper(
        rootDir = rootDir,
        httpFetcher = HttpUrlFetcher(githubReleaseToken),
        clock = clock,
    )
    private val locationManager = appContext.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val targetsConfig = runCatching {
        ContractJson.decodeBundleTargets(assetReader.readText("BundleTargets.top10.json"))
    }.getOrNull()
    private val manifestEndpoints = targetsConfig?.manifestEndpoints(preferredCountryCode = "DEU").orEmpty()
    private val lookupToken = AtomicLong(0L)
    private val localObservationStore = LocalObservationStore(appContext, rootDir, preferences, clock)
    private val wayMatchTracker = WayMatchSessionTracker()
    private val bundledVoskModelStore = BundledVoskModelStore(appContext, rootDir)
    private val initialMatcherDebugProfile: MatcherDebugProfile =
        MatcherDebugProfile.resolveInitialProfile(
            raw = preferences.getString(KEY_MATCHER_DEBUG_PROFILE, null),
            forcedVersion = preferences.getInt(KEY_MATCHER_DEBUG_PROFILE_FORCED_VERSION, 0),
        ).also { profile ->
            val storedForcedVersion = preferences.getInt(KEY_MATCHER_DEBUG_PROFILE_FORCED_VERSION, 0)
            val storedProfile = preferences.getString(KEY_MATCHER_DEBUG_PROFILE, null)
            if (storedForcedVersion < MatcherDebugProfile.forcedProfileVersion || storedProfile != profile.storageValue) {
                preferences.edit()
                    .putString(KEY_MATCHER_DEBUG_PROFILE, profile.storageValue)
                    .putInt(KEY_MATCHER_DEBUG_PROFILE_FORCED_VERSION, MatcherDebugProfile.forcedProfileVersion)
                    .apply()
            }
        }

    private var host: ConsumerHost? = null
    private var isDriving = false
    private var lookupService: V3SpeedLimitLookup? = null
    private var lookupServicePath: String? = null
    private var lookupServiceCountryCode: String? = null
    private var lookupServiceMatcherProfile: MatcherDebugProfile? = null
    private var localSpeedOverridesByWayId: Map<String, Int> = emptyMap()
    private var localSpeedOverrideValuesByWayId: Map<String, String> = emptyMap()
    private var lastAudioFeedbackAtMs = 0L
    private var lastAnnouncedSpeechText: String? = null
    private var wasDrivingBanWarningActive = false
    private var lastDrivingBanWarningAtMs = 0L
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private var bundledVoskModel: Model? = null
    private var bundledVoskModelPath: String? = null
    private var activeVoskSpeedCaptureSession: VoskSpeedCaptureSession? = null
    private var speedCapturePromptUtteranceId: String? = null
    private var isAwaitingSpeedCapturePromptCompletion = false
    private var isSpeedCaptureResolved = false
    private var activeLocalSpeedCorrection: ActiveLocalSpeedCorrection? = null
    private var pendingStartupData: PendingStartupData? = null
    private var isStartupWaitingForSpeechModel = false
    private var isGermanSpeechModelCheckInFlight = false
    private var shouldResumeSpeedCaptureAfterSpeechModelReady = false
    private var confirmationToneGenerator: ToneGenerator? = null
    private val speedCapturePromptFallbackRunnable = Runnable {
        if (isAwaitingSpeedCapturePromptCompletion) {
            isAwaitingSpeedCapturePromptCompletion = false
            scheduleSpeedCaptureListeningStart()
        }
    }
    private val speedCaptureListeningStartRunnable = Runnable {
        if (uiState.speedCaptureMode == SpeedCaptureModeState.SPEAKING_PROMPT) {
            startSpeedCaptureListening()
        }
    }

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            if (!isDriving) {
                return
            }
            consumeLocation(location)
        }

        override fun onProviderEnabled(provider: String) = Unit

        override fun onProviderDisabled(provider: String) = Unit

        @Deprecated("Deprecated in Java")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
    }

    var uiState by mutableStateOf(
        ConsumerUiState(
            legalText = assetReader.readTextOrEmpty("legal.txt"),
            audioAlertsEnabled = preferences.getBoolean(KEY_AUDIO_ALERTS_ENABLED, true),
            audioAlertThresholdKmh = preferences.getInt(KEY_AUDIO_ALERT_THRESHOLD, 8).coerceIn(0, 80),
            hideWelcomeScreen = preferences.getBoolean(KEY_HIDE_WELCOME, false),
            bundleDownloadSections = buildBundleDownloadSections(),
            configuredManifestEndpointCount = manifestEndpoints.size,
            configuredManifestCountryCodes = manifestCountryCodes(),
            hasGitHubReleaseToken = githubReleaseToken.isNotBlank(),
            activePenaltyRules = loadPenaltyRules("DEU"),
            appScreenshotState = launchScreenshotState,
            matcherDebugProfile = initialMatcherDebugProfile,
        ),
    )
        private set

    init {
        rootDir.mkdirs()
        if (launchScreenshotState != null) {
            configureForScreenshotMode(launchScreenshotState)
        } else {
            beginStartupDataLoadIfNeeded()
        }
    }

    fun bindHost(host: ConsumerHost) {
        this.host = host
    }

    fun dispose() {
        stopDriving()
        closeLookupService()
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        closeBundledVoskModel()
        textToSpeech?.stop()
        textToSpeech?.shutdown()
        textToSpeech = null
        confirmationToneGenerator?.release()
        confirmationToneGenerator = null
        executor.shutdownNow()
    }

    fun beginStartupDataLoadIfNeeded(force: Boolean = false) {
        if (!force && uiState.startupDataState == StartupDataState.READY) {
            return
        }
        pendingStartupData = null
        isStartupWaitingForSpeechModel = false
        updateState {
            copy(
                startupDataState = StartupDataState.LOADING,
                startupProgress = 0.08,
                startupDetail = "Lokale Daten werden vorbereitet",
                lastError = "",
                speedCaptureMode = SpeedCaptureModeState.IDLE,
                speedCaptureTranscript = "",
                localObservationStatus = "",
            )
        }
        executor.execute {
            try {
                bootstrapBundledSeedIfNeeded()
                refreshDownloadedBundleInventory()
                val observations = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(observations)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(observations)
                val active = bootstrapper.activeState()
                replaceLookupService(active?.dbPath, preferredCountryCode = active?.countryCode)
                val nextRules = loadPenaltyRules(active?.countryCode ?: inferCountryCodeFromDBPath(active?.dbPath) ?: "DEU")
                pendingStartupData = PendingStartupData(
                    startupDetail = when {
                        active?.bundleVersion == "seed" -> "Karlsruhe-Seed und Offline-Spracherkennung sind bereit"
                        active?.dbPath?.isNotBlank() == true -> "Lokale Daten und Offline-Spracherkennung sind bereit"
                        else -> "Noch kein lokales Bundle aktiv"
                    },
                    activeBundleVersion = active?.bundleVersion ?: "none",
                    activeDBPath = active?.dbPath ?: "",
                    activePenaltyRules = nextRules,
                    syncStatus = when {
                        active?.bundleVersion == "seed" -> "seed_only"
                        active?.dbPath?.isNotBlank() == true -> "ready_fullDownload"
                        else -> "not_synced"
                    },
                    localObservations = observations,
                )
                isStartupWaitingForSpeechModel = true
                postState {
                    copy(
                        startupDataState = StartupDataState.LOADING,
                        startupProgress = 0.62,
                        startupDetail = "Gebuendeltes deutsches Offline-Sprachmodell wird vorbereitet",
                        activeBundleVersion = active?.bundleVersion ?: "none",
                        activeDBPath = active?.dbPath ?: "",
                        activePenaltyRules = nextRules,
                        syncStatus = when {
                            active?.bundleVersion == "seed" -> "seed_only"
                            active?.dbPath?.isNotBlank() == true -> "ready_fullDownload"
                            else -> "not_synced"
                        },
                        localObservations = observations,
                        driveStatus = "stopped",
                    )
                }
                mainHandler.post {
                    ensureGermanSpeechModelPrepared(force = true, userInitiated = false)
                }
            } catch (error: Exception) {
                pendingStartupData = null
                isStartupWaitingForSpeechModel = false
                postState {
                    copy(
                        startupDataState = StartupDataState.FAILED,
                        startupProgress = 1.0,
                        startupDetail = "Lokale Daten konnten nicht vorbereitet werden",
                        lastError = error.message ?: error.javaClass.simpleName,
                    )
                }
            }
        }
    }

    fun retryStartupDataPreparation() {
        beginStartupDataLoadIfNeeded(force = true)
    }

    fun shouldPresentWelcome(now: Instant = clock.instant()): Boolean {
        if (uiState.startupDataState != StartupDataState.READY || uiState.hideWelcomeScreen) {
            return false
        }
        return ConsumerAppLogic.requiresWelcome(uiState.activeBundleVersion, now)
    }

    fun startDriving() {
        if (uiState.appScreenshotState != null || uiState.startupDataState != StartupDataState.READY) {
            return
        }
        isDriving = true
        ensureTextToSpeech()
        if (!hasLocationPermission()) {
            updateState {
                copy(
                    driveStatus = "requesting_location",
                    lastError = "",
                )
            }
            host?.requestLocationPermission()
            return
        }
        startLocationUpdates()
    }

    fun stopDriving() {
        isDriving = false
        stopLocationUpdates()
        wayMatchTracker.reset()
        cancelSpeedCapture(reason = null)
        textToSpeech?.stop()
        lastAnnouncedSpeechText = null
        wasDrivingBanWarningActive = false
        lastAudioFeedbackAtMs = 0L
        lastDrivingBanWarningAtMs = 0L
        if (uiState.appScreenshotState == null) {
            updateState { copy(driveStatus = "stopped") }
        }
    }

    fun onLocationPermissionResult(granted: Boolean) {
        if (!granted) {
            updateState {
                copy(
                    driveStatus = "location_denied",
                    lastError = "Standortberechtigung wurde nicht erteilt.",
                )
            }
            return
        }
        if (isDriving) {
            startLocationUpdates()
        }
    }

    fun beginSpeedCapture() {
        if (uiState.startupDataState != StartupDataState.READY || uiState.speedCaptureMode != SpeedCaptureModeState.IDLE) {
            return
        }
        if (uiState.appScreenshotState != null) {
            host?.showTransientMessage("Spracherkennung ist im Screenshot-Modus deaktiviert.")
            return
        }
        if (uiState.germanSpeechModelState != GermanSpeechModelState.READY) {
            host?.showTransientMessage(
                uiState.germanSpeechModelStatus.ifBlank {
                    "Gebuendeltes deutsches Offline-Sprachmodell ist nicht bereit."
                },
            )
            return
        }
        if (!hasMicrophonePermission()) {
            updateState {
                copy(
                    speedCaptureMode = SpeedCaptureModeState.REQUESTING_MIC_PERMISSION,
                    speedCaptureTranscript = "",
                    localObservationStatus = "Mikrofonberechtigung wird angefragt.",
                )
            }
            host?.requestMicrophonePermission()
            return
        }
        prepareSpeedCaptureRecognizerAndMaybeStart()
    }

    fun onMicrophonePermissionResult(granted: Boolean) {
        if (!granted) {
            shouldResumeSpeedCaptureAfterSpeechModelReady = false
            host?.showTransientMessage("Mikrofonberechtigung wurde nicht erteilt.")
            cancelSpeedCapture(reason = null)
            return
        }
        if (uiState.speedCaptureMode == SpeedCaptureModeState.REQUESTING_MIC_PERMISSION) {
            prepareSpeedCaptureRecognizerAndMaybeStart()
        }
    }

    fun retrySpeedCapture() {
        if (uiState.speedCaptureMode == SpeedCaptureModeState.SAVING) {
            return
        }
        cancelSpeedCapture(reason = null)
        beginSpeedCapture()
    }

    fun prepareGermanSpeechModel() {
        ensureGermanSpeechModelPrepared(force = true, userInitiated = true)
    }

    fun cancelSpeedCapture(reason: String?) {
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        textToSpeech?.stop()
        resetSpeedCaptureTransientState()
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.IDLE,
                speedCaptureTranscript = "",
                localObservationStatus = reason ?: localObservationStatus,
            )
        }
    }

    fun setAudioAlertsEnabled(enabled: Boolean) {
        preferences.edit().putBoolean(KEY_AUDIO_ALERTS_ENABLED, enabled).apply()
        if (!enabled) {
            textToSpeech?.stop()
            lastAnnouncedSpeechText = null
        }
        updateState { copy(audioAlertsEnabled = enabled) }
    }

    fun setAudioAlertThresholdKmh(value: Int) {
        val clamped = value.coerceIn(0, 80)
        preferences.edit().putInt(KEY_AUDIO_ALERT_THRESHOLD, clamped).apply()
        updateState { copy(audioAlertThresholdKmh = clamped) }
    }

    fun setHideWelcomeScreen(hidden: Boolean) {
        preferences.edit().putBoolean(KEY_HIDE_WELCOME, hidden).apply()
        updateState { copy(hideWelcomeScreen = hidden) }
    }

    fun setMatcherDebugProfile(profile: MatcherDebugProfile) {
        val current = uiState.matcherDebugProfile
        if (current == profile) {
            return
        }
        preferences.edit().putString(KEY_MATCHER_DEBUG_PROFILE, profile.storageValue).apply()
        wayMatchTracker.reset()
        replaceLookupService(
            uiState.activeDBPath.takeIf { it.isNotBlank() },
            preferredCountryCode = uiState.activePenaltyRules.countryCode,
            matcherProfile = profile,
        )
        updateState { copy(matcherDebugProfile = profile) }
    }

    fun fetchFirstGermanyManifest() {
        val endpoint = manifestEndpoints.firstOrNull { it.countryCode.uppercase(Locale.US) == "DEU" }
            ?: return setError("Keine Deutschland-Endpunkte in BundleTargets.top10.json gefunden.")
        if (requiresGitHubToken(endpoint.manifestUrl) && githubReleaseToken.isBlank()) {
            return setError("GitHub Release Token fehlt (YOUSPEED_RELEASE_READ_TOKEN).")
        }
        runSyncTask(status = "syncing", detail = "Lade Manifest") {
            val manifest = bootstrapper.fetchManifest(endpoint.manifestUrl)
            copy(
                syncStatus = "ready_manifest",
                syncProgressDetail = "Manifest geladen: ${manifest.region} ${manifest.bundleVersion}",
                maintenanceMessage = "Manifest geladen: ${manifest.region}",
                lastError = "",
            )
        }
    }

    fun bootstrapAndSync() {
        if (manifestEndpoints.isEmpty()) {
            setError("Keine Manifest-Endpunkte konfiguriert.")
            return
        }
        if (manifestEndpoints.any { requiresGitHubToken(it.manifestUrl) } && githubReleaseToken.isBlank()) {
            setError("GitHub Release Token fehlt in der Android-Build-Konfiguration (YOUSPEED_RELEASE_READ_TOKEN).")
            return
        }
        runSyncTask(status = "syncing", detail = "Synchronisierung startet") {
            var lastFailure: Exception? = null
            var successState: ConsumerUiState? = null
            val endpoints = manifestEndpoints.filter { it.countryCode.uppercase(Locale.US) == "DEU" } +
                manifestEndpoints.filter { it.countryCode.uppercase(Locale.US) != "DEU" }
            for (endpoint in endpoints) {
                try {
                    val sync = bootstrapper.syncFromManifestUrl(endpoint.manifestUrl)
                    refreshDownloadedBundleInventory()
                    val active = bootstrapper.activeState()
                    replaceLookupService(sync.dbPath, preferredCountryCode = active?.countryCode ?: endpoint.countryCode)
                    successState = copy(
                        syncStatus = "ready_${sync.mode.name.lowercase(Locale.US)}",
                        syncProgressDetail = "Synchronisierung abgeschlossen",
                        maintenanceMessage = sync.details,
                        activeBundleVersion = sync.bundleVersion,
                        activeDBPath = sync.dbPath,
                        activePenaltyRules = loadPenaltyRules(active?.countryCode ?: inferCountryCodeFromDBPath(sync.dbPath) ?: "DEU"),
                        lastError = "",
                    )
                    break
                } catch (error: Exception) {
                    lastFailure = error
                }
            }
            successState?.let { return@runSyncTask it }
            throw lastFailure ?: IllegalStateException("Kein Manifest-Endpunkt konnte synchronisiert werden.")
        }
    }

    fun deleteDownloadedBundlesKeepingSeed() {
        executor.execute {
            try {
                val removed = bootstrapper.removeDownloadedBundlesKeepingSeed()
                refreshDownloadedBundleInventory()
                bootstrapBundledSeedIfNeeded()
                val active = bootstrapper.activeState()
                replaceLookupService(active?.dbPath, preferredCountryCode = active?.countryCode)
                postState {
                    copy(
                        activeBundleVersion = active?.bundleVersion ?: "none",
                        activeDBPath = active?.dbPath ?: "",
                        syncStatus = when {
                            active?.bundleVersion == "seed" -> "seed_only"
                            active?.dbPath?.isNotBlank() == true -> "ready_fullDownload"
                            else -> "not_synced"
                        },
                        maintenanceMessage = if (removed > 0) {
                            "Heruntergeladene Datenbanken geloescht ($removed)."
                        } else {
                            "Keine heruntergeladenen Datenbanken gefunden."
                        },
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Heruntergeladene Datenbanken konnten nicht geloescht werden: ${error.message}")
            }
        }
    }

    fun downloadSelectedBundle(option: BundleDownloadOption) {
        if (requiresGitHubToken(option.endpoint.manifestUrl) && githubReleaseToken.isBlank()) {
            setError("GitHub Release Token fehlt (YOUSPEED_RELEASE_READ_TOKEN).")
            return
        }
        runSyncTask(status = "syncing", detail = "Lade ${option.displayName}") {
            val sync = bootstrapper.syncFromManifestUrl(option.endpoint.manifestUrl)
            refreshDownloadedBundleInventory()
            val active = bootstrapper.activeState()
            replaceLookupService(sync.dbPath, preferredCountryCode = active?.countryCode ?: option.countryCode)
            copy(
                syncStatus = "ready_${sync.mode.name.lowercase(Locale.US)}",
                syncProgressDetail = "Bundle geladen: ${option.displayName}",
                maintenanceMessage = "Bundle geladen: ${option.displayName}",
                activeBundleVersion = sync.bundleVersion,
                activeDBPath = sync.dbPath,
                activePenaltyRules = loadPenaltyRules(active?.countryCode ?: option.countryCode),
                lastError = "",
            )
        }
    }

    fun deleteSelectedBundle(option: BundleDownloadOption) {
        executor.execute {
            try {
                val removed = bootstrapper.removeDownloadedBundles(option.endpoint.manifestRegion)
                refreshDownloadedBundleInventory()
                val active = bootstrapper.activeState()
                replaceLookupService(active?.dbPath, preferredCountryCode = active?.countryCode)
                postState {
                    copy(
                        activeBundleVersion = active?.bundleVersion ?: "none",
                        activeDBPath = active?.dbPath ?: "",
                        maintenanceMessage = if (removed > 0) "Bundle geloescht: ${option.displayName}" else "Kein Bundle geloescht: ${option.displayName}",
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Bundle konnte nicht geloescht werden: ${error.message}")
            }
        }
    }

    private fun persistSpeedCaptureSelection(selection: SpeedCaptureSelection) {
        val selectedValue = selection.value
        executor.execute {
            try {
                postState { copy(speedCaptureMode = SpeedCaptureModeState.SAVING) }
                val savedObservation = localObservationStore.recordSpeedLimitChange(
                    oldSpeedKmh = uiState.speedLimitKmh,
                    newMaxspeedValue = selectedValue,
                    captureContext = currentObservationCaptureContext(
                        wayId = uiState.limitWayId,
                        streetName = uiState.limitStreetName,
                        cityName = uiState.limitCityName,
                        confidence = currentObservationConfidence(),
                    ),
                    initialState = LocalObservationState.LOCAL_ONLY,
                )
                val updated = localObservationStore.fetchObservations(limit = 500)
                val numericSpeed = savedObservation.newSpeedKmh
                val wayId = savedObservation.wayId
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                activateLocalSpeedCorrectionIfPossible(selection, savedObservation)
                val displayText = speedLimitDisplayTextForValue(selection.value)
                resetSpeedCaptureTransientState()
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = "Erfasst: way ${wayId ?: "n/a"}, alt ${uiState.speedLimitKmh ?: "n/a"}, neu ${selection.displayLabel}.",
                        speedCaptureMode = SpeedCaptureModeState.IDLE,
                        speedCaptureTranscript = "",
                        maintenanceMessage = "",
                        lastError = "",
                        speedLimitKmh = when {
                            wayId != null && wayId == limitWayId && numericSpeed != null -> numericSpeed
                            wayId != null && wayId == limitWayId && displayText != null -> null
                            else -> speedLimitKmh
                        },
                        speedLimitDisplayText = if (wayId != null && wayId == limitWayId) displayText else speedLimitDisplayText,
                        isUnlimitedSpeedLimitActive = if (wayId != null && wayId == limitWayId && (numericSpeed != null || displayText != null)) false else isUnlimitedSpeedLimitActive,
                    )
                }
                playSpeedCaptureConfirmationTone()
            } catch (error: Exception) {
                showSpeedCaptureFailure(reason = "Lokale Erfassung konnte nicht gespeichert werden: ${error.message}")
            }
        }
    }

    fun deleteLocalObservation(observationId: String) {
        executor.execute {
            try {
                localObservationStore.deleteObservation(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                activeLocalSpeedCorrection = null
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = "Eintrag geloescht.",
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Loeschen fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun deleteAllLocalObservations() {
        executor.execute {
            try {
                val removed = localObservationStore.deleteAllObservations()
                localSpeedOverridesByWayId = emptyMap()
                localSpeedOverrideValuesByWayId = emptyMap()
                activeLocalSpeedCorrection = null
                postState {
                    copy(
                        localObservations = emptyList(),
                        localObservationStatus = if (removed > 0) "$removed lokale Erfassungen geloescht." else "Keine lokalen Erfassungen vorhanden.",
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Alle Eintraege loeschen fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun exportAllLocalObservations() {
        executor.execute {
            try {
                val result = localObservationStore.exportAllLocalObservationsAsOsc()
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservationStatus = "Export erstellt (${result.includedCount} Wege): changes.osc",
                        localObservations = updated,
                        lastExportDirectoryPath = result.packageDirectory.absolutePath,
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Export fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun approveLocalObservation(observationId: String) {
        executor.execute {
            try {
                localObservationStore.reviewAndApproveProposal(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = "Beobachtung freigegeben fuer Export.",
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Freigabe fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun discardLocalObservation(observationId: String) {
        executor.execute {
            try {
                localObservationStore.discardObservation(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = "Beobachtung verworfen.",
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Verwerfen fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun exportLocalObservation(observationId: String) {
        executor.execute {
            try {
                val result = localObservationStore.exportProposalAsOscPackage(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = "Export erstellt: ${result.packageDirectory.name}",
                        lastExportDirectoryPath = result.packageDirectory.absolutePath,
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Einzelexport fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun shareGpsLog() {
        val path = uiState.gpsLogPath.takeIf { it.isNotBlank() } ?: return setError("Noch keine GPS-Logdatei vorhanden.")
        host?.shareFile(path, "text/csv")
    }

    fun shareMatchLog() {
        val path = uiState.matchLogPath.takeIf { it.isNotBlank() } ?: return setError("Noch keine Matcher-Logdatei vorhanden.")
        host?.shareFile(path, "application/x-ndjson")
    }

    fun clearDrivingLogs() {
        executor.execute {
            try {
                gpsLogFile().parentFile?.mkdirs()
                gpsLogFile().writeText(GPS_LOG_HEADER)
                matchLogFile().parentFile?.mkdirs()
                matchLogFile().writeText("")
                postState {
                    copy(
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                        maintenanceMessage = "Fahrlog geleert.",
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError("Fahrlog leeren fehlgeschlagen: ${error.message}")
            }
        }
    }

    fun openCurrentOsmUrl() {
        val url = currentOsmUrl() ?: return setError("Keine OSM-Position verfuegbar.")
        host?.openExternalUrl(url)
    }

    fun debugRows(): List<Pair<String, String>> {
        val state = uiState
        fun text(value: String?): String = value?.trim().takeUnless { it.isNullOrEmpty() } ?: "n/a"
        return listOf(
            "Koordinate" to coordinateText(),
            "Geschwindigkeit" to String.format(Locale.US, "%.1f km/h", state.currentSpeedKmh),
            "Tempolimit" to (state.speedLimitDisplayText ?: state.speedLimitKmh?.toString()?.plus(" km/h") ?: if (state.isUnlimitedSpeedLimitActive) "unbegrenzt" else "n/a"),
            "Delta" to "${ConsumerMainScreenLogic.currentOverspeedKmh(state)} km/h",
            "Drive-Status" to state.driveStatus,
            "GPS-Fixes" to state.gpsFixCount.toString(),
            "Aktives Bundle" to state.activeBundleVersion,
            "Aktive DB" to if (state.activeDBPath.isBlank()) "n/a" else File(state.activeDBPath).name,
            "DB-Pfad" to if (state.activeDBPath.isBlank()) "n/a" else state.activeDBPath,
            "Way-ID" to text(state.limitWayId),
            "Strasse" to text(state.limitStreetName),
            "Stadt" to text(state.limitCityName),
            "GPS-Signal" to "${state.gpsSignalBars}/4",
            "Horizontal" to (state.gpsHorizontalAccuracyM?.run { String.format(Locale.US, "%.1f m", this) } ?: "n/a"),
            "Matcher" to state.matcherDebugProfile.debugLabel,
            "Tunnel-Modus" to when (state.tunnelModeState) {
                TunnelModeState.INACTIVE -> "inactive"
                TunnelModeState.ACTIVE -> "active"
            },
            "Innerorts" to when (state.lastLookupInsideCity) {
                true -> "ja"
                false -> "nein"
                null -> "n/a"
            },
            "Lookup Query" to String.format(Locale.US, "%.2f ms", state.lastLookupQueryMs),
            "Kandidaten" to state.lastLookupCandidateCount.toString(),
            "Mit Limit" to state.lastLookupSpeedCandidateCount.toString(),
            "Naechster Weg" to (state.lastLookupNearestCandidateM?.let { String.format(Locale.US, "%.1f m", it) } ?: "n/a"),
            "Naechstes Limit" to (state.lastLookupNearestSpeedCandidateM?.let { String.format(Locale.US, "%.1f m", it) } ?: "n/a"),
            "Stadtquelle" to state.lastLookupCitySource,
            "GPS-Log" to if (state.gpsLogPath.isBlank()) "n/a" else state.gpsLogPath,
            "Matcher-Log" to if (state.matchLogPath.isBlank()) "n/a" else state.matchLogPath,
            "Lookup" to state.syncStatus,
            "Manifest-Endpunkte" to state.configuredManifestEndpointCount.toString(),
            "Manifest-Laender" to state.configuredManifestCountryCodes,
            "GitHub Token" to if (state.hasGitHubReleaseToken) "vorhanden" else "fehlt",
        )
    }

    fun currentOsmUrl(): String? {
        val wayId = uiState.limitWayId ?: return null
        val latitude = uiState.currentLatitude ?: return null
        val longitude = uiState.currentLongitude ?: return null
        val latText = String.format(Locale.US, "%.6f", latitude)
        val lonText = String.format(Locale.US, "%.6f", longitude)
        return "https://www.openstreetmap.org/way/$wayId#map=18/$latText/$lonText"
    }

    fun formattedSyncStatus(): String = when (uiState.syncStatus) {
        "not_synced" -> "Nicht synchronisiert"
        "syncing" -> "Synchronisiert..."
        "sync_failed" -> "Synchronisierung fehlgeschlagen"
        "seed_only" -> "Seed aktiv"
        else -> uiState.syncStatus.replace("_", " ")
    }

    fun isBundleDownloaded(option: BundleDownloadOption): Boolean {
        return uiState.downloadedBundleCountByRegion[tokenize(option.endpoint.manifestRegion)] ?: 0 > 0
    }

    fun downloadedBundleStatusText(option: BundleDownloadOption): String {
        val key = tokenize(option.endpoint.manifestRegion)
        val count = uiState.downloadedBundleCountByRegion[key] ?: 0
        if (count <= 0) {
            return ""
        }
        val latest = uiState.downloadedBundleLatestVersionByRegion[key]
        return if (latest != null) "geladen ($latest)" else "geladen"
    }

    private fun coordinateText(): String {
        val lat = uiState.currentLatitude?.run { String.format(Locale.US, "%.6f", this) } ?: "n/a"
        val lon = uiState.currentLongitude?.run { String.format(Locale.US, "%.6f", this) } ?: "n/a"
        return "$lat, $lon"
    }

    private fun runSyncTask(
        status: String,
        detail: String,
        work: ConsumerUiState.() -> ConsumerUiState,
    ) {
        updateState {
            copy(
                syncStatus = status,
                syncProgressDetail = detail,
                maintenanceMessage = "",
                lastError = "",
            )
        }
        executor.execute {
            try {
                val updated = work(uiState)
                postState { updated }
            } catch (error: Exception) {
                setError(error.message ?: error.javaClass.simpleName)
            }
        }
    }

    private fun setError(message: String) {
        postState {
            copy(
                syncStatus = if (syncStatus == "syncing") "sync_failed" else syncStatus,
                syncProgressDetail = "",
                lastError = message,
            )
        }
    }

    private fun refreshDownloadedBundleInventory() {
        val bundles = bootstrapper.listDownloadedBundles()
        val countByRegion = linkedMapOf<String, Int>()
        val latestByRegion = linkedMapOf<String, String>()
        bundles.forEach { bundle ->
            val key = tokenize(bundle.region)
            countByRegion[key] = (countByRegion[key] ?: 0) + 1
            val currentLatest = latestByRegion[key]
            if (currentLatest == null || bundle.bundleVersion > currentLatest) {
                latestByRegion[key] = bundle.bundleVersion
            }
        }
        postState {
            copy(
                downloadedBundleCountByRegion = countByRegion,
                downloadedBundleLatestVersionByRegion = latestByRegion,
            )
        }
    }

    private fun buildBundleDownloadSections(): List<BundleDownloadCountrySection> {
        val config = targetsConfig ?: return emptyList()
        val locale = Locale.GERMANY
        return config.countries.map { country ->
            val countryName = locale.getDisplayCountryForCode(country.iso2 ?: country.countryCode.take(2)).ifBlank {
                country.countryId.replace('-', ' ').replaceFirstChar { if (it.isLowerCase()) it.titlecase(locale) else it.toString() }
            }
            val options = config.manifestEndpoints(preferredCountryCode = null)
                .filter { it.countryId.lowercase(Locale.US) == country.countryId.lowercase(Locale.US) }
                .map { endpoint ->
                    BundleDownloadOption(
                        id = "${endpoint.countryId}|${endpoint.manifestRegion}",
                        countryCode = country.countryCode,
                        countryName = countryName,
                        displayName = endpoint.regionName ?: endpoint.manifestRegion.replace('-', ' ').replaceFirstChar { if (it.isLowerCase()) it.titlecase(locale) else it.toString() },
                        endpoint = endpoint,
                    )
                }
            BundleDownloadCountrySection(
                id = country.countryId,
                countryCode = country.countryCode,
                countryName = countryName,
                options = options.sortedBy { it.displayName },
            )
        }.sortedBy { it.countryName }
    }

    private fun manifestCountryCodes(): String {
        val codes = manifestEndpoints.map { it.countryCode.trim().uppercase(Locale.US) }
            .filter { it.isNotEmpty() && it != "UNK" }
            .toSortedSet()
        return if (codes.isEmpty()) "n/a" else codes.joinToString(", ")
    }

    private fun configureForScreenshotMode(state: AppScreenshotState) {
        val fixture = state.fixture
        uiState = uiState.copy(
            startupDataState = StartupDataState.READY,
            startupProgress = 1.0,
            startupDetail = "Screenshot fixture loaded",
            syncStatus = "ready_fixture",
            activeBundleVersion = "screenshot-fixture",
            activeDBPath = "/tmp/screenshot-fixture.sqlite",
            currentSpeedKmh = fixture.currentSpeedKmh,
            speedLimitKmh = fixture.speedLimitKmh,
            speedLimitDisplayText = fixture.speedLimitDisplayText,
            isUnlimitedSpeedLimitActive = fixture.isUnlimitedSpeedLimitActive,
            limitWayId = fixture.wayId,
            limitStreetName = fixture.streetName,
            limitStreetBaseName = fixture.streetName,
            limitStreetRef = null,
            limitCityName = fixture.cityName,
            currentLatitude = fixture.latitude,
            currentLongitude = fixture.longitude,
            gpsHorizontalAccuracyM = fixture.gpsHorizontalAccuracyM,
            gpsSignalBars = fixture.gpsSignalBars,
            gpsFixCount = 1,
            driveStatus = "running",
            hideWelcomeScreen = true,
            appScreenshotState = state,
            lastLookupInsideCity = fixture.insideCity,
            localObservationStatus = "",
            germanSpeechModelState = GermanSpeechModelState.READY,
            germanSpeechModelStatus = "Screenshot-Modus verwendet kein Live-Audio.",
            gpsLogPath = gpsLogFile().absolutePath,
            matchLogPath = matchLogFile().absolutePath,
        )
    }

    private fun loadPenaltyRules(countryCode: String): ActivePenaltyRules {
        val assetName = "${countryCode.trim().uppercase(Locale.US)}-rules.json"
        val fileName: String
        val raw = when {
            assetReader.readTextOrNull("Rules/$assetName") != null -> {
                fileName = assetName
                assetReader.readText("Rules/$assetName")
            }
            assetReader.readTextOrNull(assetName) != null -> {
                fileName = assetName
                assetReader.readText(assetName)
            }
            else -> {
                fileName = "DEU-rules.json"
                assetReader.readTextOrNull("Rules/DEU-rules.json")
                    ?: assetReader.readTextOrNull("DEU-rules.json")
                    ?: return ActivePenaltyRules.fallback()
            }
        }
        val parsed = runCatching { PenaltyRulesParser.parse(raw) }.getOrElse { return ActivePenaltyRules.fallback() }
        return ActivePenaltyRules(fileName = fileName, ruleSet = parsed)
    }

    private fun requiresGitHubToken(url: String): Boolean {
        return HttpUrlFetcher.parseGitHubReleaseAssetUrl(url) != null
    }

    private fun tokenize(raw: String): String {
        return raw.trim().lowercase(Locale.US).replace(" ", "-").replace("_", "-").replace("/", "-")
    }

    private fun currentObservationCaptureContext(
        wayId: String?,
        streetName: String?,
        cityName: String?,
        confidence: Double?,
    ): LocalObservationCaptureContext {
        return LocalObservationCaptureContext(
            lat = uiState.currentLatitude,
            lon = uiState.currentLongitude,
            headingDeg = null,
            roadCandidateIds = listOfNotNull(wayId?.trim()?.ifBlank { null }),
            cityContext = cityName?.trim()?.ifBlank { null },
            streetContext = streetName?.trim()?.ifBlank { null },
            confidenceCalibrated = confidence,
            sourceVersion = uiState.activeBundleVersion.ifBlank { "none" },
        )
    }

    private fun currentObservationConfidence(): Double? {
        return when {
            uiState.speedLimitKmh != null || uiState.speedLimitDisplayText != null || uiState.isUnlimitedSpeedLimitActive -> 0.85
            uiState.lastLookupNearestCandidateM != null -> 0.55
            else -> null
        }
    }

    @SuppressLint("MissingPermission")
    private fun startLocationUpdates() {
        if (!hasLocationPermission()) {
            updateState {
                copy(
                    driveStatus = "location_denied",
                    lastError = "Standortberechtigung wurde nicht erteilt.",
                )
            }
            return
        }
        stopLocationUpdates()
        ensureDrivingLogsExist()
        val providers = locationManager.getProviders(true).filterNotNull()
        if (providers.isEmpty()) {
            updateState {
                copy(
                    driveStatus = "location_error",
                    lastError = "Keine aktiven Standortanbieter verfuegbar.",
                )
            }
            return
        }
        providers.forEach { provider ->
            runCatching {
                locationManager.requestLocationUpdates(provider, 3_000L, 5f, locationListener, Looper.getMainLooper())
            }.onFailure {
                updateState {
                    copy(
                        driveStatus = "location_error",
                        lastError = it.message ?: "Standortupdates konnten nicht gestartet werden.",
                    )
                }
            }
        }
        providers.mapNotNull { provider -> runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull() }
            .maxByOrNull { it.time }
            ?.let(::consumeLocation)
        updateState {
            copy(
                driveStatus = "running",
                lastError = "",
                gpsLogPath = gpsLogFile().absolutePath,
                matchLogPath = matchLogFile().absolutePath,
            )
        }
    }

    private fun stopLocationUpdates() {
        runCatching { locationManager.removeUpdates(locationListener) }
    }

    private fun consumeLocation(location: Location) {
        val previousDisplaySpeedKmh = uiState.currentSpeedKmh
        val rawSpeedKmh = max(0.0, location.speed.toDouble()) * 3.6
        val speedAccuracyKmh = if (location.hasSpeedAccuracy()) location.speedAccuracyMetersPerSecond.toDouble() * 3.6 else null
        val filteredSpeedKmh = filteredDisplaySpeedKmh(
            rawSpeedKmh = rawSpeedKmh,
            speedAccuracyKmh = speedAccuracyKmh,
            previousDisplaySpeedKmh = previousDisplaySpeedKmh,
        )
        val gpsFixCount = uiState.gpsFixCount + 1
        val gpsHorizontalAccuracyM = location.accuracy.toDouble().takeIf { it >= 0.0 }
        val gpsSignalBars = gpsSignalBars(gpsHorizontalAccuracyM)

        updateState {
            copy(
                currentSpeedKmh = filteredSpeedKmh,
                currentLatitude = location.latitude,
                currentLongitude = location.longitude,
                gpsHorizontalAccuracyM = gpsHorizontalAccuracyM,
                gpsSignalBars = gpsSignalBars,
                gpsFixCount = gpsFixCount,
                driveStatus = "running",
                lastError = if (driveStatus == "location_error") "" else lastError,
            )
        }
        maybeSpeakOverspeedWarning()

        val token = lookupToken.incrementAndGet()
        val dbPath = uiState.activeDBPath.takeIf { it.isNotBlank() && File(it).exists() }
        if (dbPath == null) {
            executor.execute {
                wayMatchTracker.reset()
                ensureDrivingLogsExist()
                appendGpsFixRow(
                    fixId = gpsFixCount,
                    location = location,
                    speedKmh = filteredSpeedKmh,
                    status = "no_database",
                    result = null,
                )
                appendMatchLogEntry(
                    fixId = gpsFixCount,
                    location = location,
                    speedKmh = filteredSpeedKmh,
                    status = "no_database",
                    result = null,
                    matchContext = null,
                    gpsSignalBars = gpsSignalBars,
                    errorText = null,
                )
                postState {
                    copy(
                        speedLimitKmh = null,
                        speedLimitDisplayText = null,
                        isUnlimitedSpeedLimitActive = false,
                        limitWayId = null,
                        limitStreetName = null,
                        limitStreetBaseName = null,
                        limitStreetRef = null,
                        limitCityName = null,
                        lastLookupInsideCity = null,
                        lastLookupCitySource = "n/a",
                        lastLookupQueryMs = 0.0,
                        lastLookupCandidateCount = 0,
                        lastLookupSpeedCandidateCount = 0,
                        lastLookupNearestCandidateM = null,
                        lastLookupNearestSpeedCandidateM = null,
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                    )
                }
            }
            return
        }

        executor.execute {
            try {
                val service = ensureLookupService(dbPath)
                val matchContext = wayMatchTracker.snapshotOrNull()
                val result = service.lookup(
                    lat = location.latitude,
                    lon = location.longitude,
                    radiusM = lookupRadiusForHorizontalAccuracy(location.accuracy.toDouble()),
                    maxCandidates = 1200,
                    headingDeg = location.bearing.toDouble().takeIf { location.hasBearing() },
                    speedKmh = filteredSpeedKmh,
                    horizontalAccuracyM = gpsHorizontalAccuracyM,
                    gpsSignalBars = gpsSignalBars,
                    matchContext = matchContext,
                )
                val activeCorrectionOverrideValue = applyActiveLocalSpeedCorrectionIfNeeded(result = result)
                val localOverrideValue = activeCorrectionOverrideValue ?: result.wayId?.let { localSpeedOverrideValuesByWayId[it] }
                val localOverride = localOverrideValue?.toIntOrNull()
                val effectiveSpeed = localOverride ?: result.speedLimitKmh
                val effectiveDisplayText = speedLimitDisplayTextForValue(localOverrideValue)
                val unlimitedActive = localOverrideValue == null &&
                    result.isUnlimitedSpeedLimit &&
                    normalizedCountryCode(uiState.activePenaltyRules.countryCode) == "DEU" &&
                    result.highway?.trim()?.lowercase(Locale.US) == "motorway"

                ensureDrivingLogsExist()
                appendGpsFixRow(
                    fixId = gpsFixCount,
                    location = location,
                    speedKmh = filteredSpeedKmh,
                    status = when {
                        unlimitedActive -> "matched_unlimited"
                        localOverrideValue != null -> "matched_local_override"
                        effectiveSpeed != null -> "matched"
                        else -> "no_match"
                    },
                    result = result,
                    overrideSpeedKmh = effectiveSpeed,
                )
                appendMatchLogEntry(
                    fixId = gpsFixCount,
                    location = location,
                    speedKmh = filteredSpeedKmh,
                    status = when {
                        unlimitedActive -> "matched_unlimited"
                        localOverrideValue != null -> "matched_local_override"
                        effectiveSpeed != null -> "matched"
                        else -> "no_match"
                    },
                    result = result,
                    matchContext = matchContext,
                    gpsSignalBars = gpsSignalBars,
                    overrideSpeedKmh = effectiveSpeed,
                    errorText = null,
                )

                if (lookupToken.get() != token) {
                    return@execute
                }
                wayMatchTracker.record(
                    result = result,
                    lat = location.latitude,
                    lon = location.longitude,
                    horizontalAccuracyM = gpsHorizontalAccuracyM,
                    gpsSignalBars = gpsSignalBars,
                )
                postState {
                    copy(
                        speedLimitKmh = effectiveSpeed,
                        speedLimitDisplayText = effectiveDisplayText,
                        isUnlimitedSpeedLimitActive = unlimitedActive,
                        limitWayId = result.wayId,
                        limitStreetName = result.streetName,
                        limitStreetBaseName = result.streetBaseName,
                        limitStreetRef = result.streetRef,
                        limitCityName = result.cityName,
                        lastLookupInsideCity = result.insideCity,
                        lastLookupCitySource = result.citySource ?: "n/a",
                        lastLookupQueryMs = result.queryTimeMs,
                        lastLookupCandidateCount = result.candidateCount,
                        lastLookupSpeedCandidateCount = result.speedCandidateCount,
                        lastLookupNearestCandidateM = result.nearestCandidateDistanceM,
                        lastLookupNearestSpeedCandidateM = result.nearestSpeedCandidateDistanceM,
                        tunnelModeState = if (result.isTunnelSegment) TunnelModeState.ACTIVE else TunnelModeState.INACTIVE,
                        isLowSpeedMatchingRuleActive = result.usedWalkingTurnSwitch,
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                    )
                }
                mainHandler.post {
                    maybeSpeakDrivingBanWarning()
                    maybeSpeakOverspeedWarning()
                }
            } catch (error: Exception) {
                wayMatchTracker.noteGpsSignalLoss(horizontalAccuracyM = gpsHorizontalAccuracyM, gpsSignalBars = gpsSignalBars)
                ensureDrivingLogsExist()
                appendGpsFixRow(
                    fixId = gpsFixCount,
                    location = location,
                    speedKmh = filteredSpeedKmh,
                    status = "lookup_error",
                    result = null,
                    errorText = error.message ?: error.javaClass.simpleName,
                )
                appendMatchLogEntry(
                    fixId = gpsFixCount,
                    location = location,
                    speedKmh = filteredSpeedKmh,
                    status = "lookup_error",
                    result = null,
                    matchContext = wayMatchTracker.snapshotOrNull(),
                    gpsSignalBars = gpsSignalBars,
                    errorText = error.message ?: error.javaClass.simpleName,
                )
                postState {
                    copy(
                        driveStatus = "location_error",
                        lastError = error.message ?: error.javaClass.simpleName,
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                    )
                }
            }
        }
    }

    private fun maybeSpeakOverspeedWarning() {
        if (uiState.driveStatus != "running" || !uiState.audioAlertsEnabled || uiState.speedCaptureMode != SpeedCaptureModeState.IDLE) {
            lastAnnouncedSpeechText = null
            return
        }
        val overspeedKmh = ConsumerMainScreenLogic.currentOverspeedKmh(uiState)
        val threshold = uiState.audioAlertThresholdKmh
        val notice = ConsumerMainScreenLogic.currentPenaltyNotice(uiState)
        if (threshold <= 0 || overspeedKmh < threshold || notice == null || (notice.drivingBanMonths ?: 0) > 0) {
            lastAnnouncedSpeechText = null
            return
        }
        val speechText = when (notice.severity) {
            PenaltySeverity.MONEY_ONLY -> notice.moneyFineEUR?.let { "$it ${uiState.activePenaltyRules.currencyCode}" } ?: uiState.activePenaltyRules.currencyCode
            PenaltySeverity.POINTS_AND_FINE -> notice.penaltyPoints?.let { if (it == 1) "ein Punkt" else "$it Punkte" } ?: "Punkte"
        }
        val now = System.currentTimeMillis()
        val changedSignificantly = speechText != lastAnnouncedSpeechText
        if (!changedSignificantly && now - lastAudioFeedbackAtMs < 8_000L) {
            return
        }
        speakText(speechText)
        lastAudioFeedbackAtMs = now
        lastAnnouncedSpeechText = speechText
    }

    private fun maybeSpeakDrivingBanWarning() {
        if (uiState.driveStatus != "running" || uiState.speedCaptureMode != SpeedCaptureModeState.IDLE) {
            wasDrivingBanWarningActive = false
            return
        }
        val notice = ConsumerMainScreenLogic.currentPenaltyNotice(uiState)
        val drivingBanMonths = notice?.drivingBanMonths ?: 0
        if (drivingBanMonths <= 0) {
            wasDrivingBanWarningActive = false
            return
        }
        val now = System.currentTimeMillis()
        val enteringWarning = !wasDrivingBanWarningActive
        if (!enteringWarning && now - lastDrivingBanWarningAtMs < DRIVING_BAN_WARNING_REMINDER_MS) {
            return
        }
        val speechText = if (drivingBanMonths == 1) {
            "Achtung. Ein Monat Fahrverbot moeglich."
        } else {
            "Achtung. $drivingBanMonths Monate Fahrverbot moeglich."
        }
        if (uiState.audioAlertsEnabled) {
            speakText(speechText)
        }
        wasDrivingBanWarningActive = true
        lastDrivingBanWarningAtMs = now
    }

    private fun ensureTextToSpeech() {
        if (textToSpeech != null) {
            return
        }
        textToSpeech = TextToSpeech(appContext) { status ->
            textToSpeechReady = status == TextToSpeech.SUCCESS
            if (textToSpeechReady) {
                textToSpeech?.language = Locale.GERMANY
                textToSpeech?.setSpeechRate(0.9f)
                textToSpeech?.setOnUtteranceProgressListener(
                    object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) = Unit

                        override fun onDone(utteranceId: String?) {
                            if (utteranceId != null && utteranceId == speedCapturePromptUtteranceId) {
                                mainHandler.post {
                                    if (isAwaitingSpeedCapturePromptCompletion) {
                                        isAwaitingSpeedCapturePromptCompletion = false
                                        scheduleSpeedCaptureListeningStart()
                                    }
                                }
                            }
                        }

                        @Deprecated("Deprecated in Java")
                        override fun onError(utteranceId: String?) {
                            if (utteranceId != null && utteranceId == speedCapturePromptUtteranceId) {
                                mainHandler.post {
                                    if (isAwaitingSpeedCapturePromptCompletion) {
                                        isAwaitingSpeedCapturePromptCompletion = false
                                        scheduleSpeedCaptureListeningStart()
                                    }
                                }
                            }
                        }
                    },
                )
            }
        }
    }

    private fun speakText(text: String) {
        ensureTextToSpeech()
        if (!textToSpeechReady) {
            return
        }
        textToSpeech?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "youspeed-${System.currentTimeMillis()}")
    }

    private fun prepareSpeedCaptureRecognizerAndMaybeStart() {
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.PREPARING,
                speedCaptureTranscript = "",
                localObservationStatus = "Offline-Spracherkennung wird vorbereitet.",
            )
        }
        if (uiState.germanSpeechModelState != GermanSpeechModelState.READY) {
            shouldResumeSpeedCaptureAfterSpeechModelReady = true
            ensureGermanSpeechModelPrepared(force = true, userInitiated = true)
            return
        }
        if (bundledVoskModel == null) {
            showSpeedCaptureFailure(reason = "Gebuendeltes Offline-Sprachmodell ist noch nicht bereit.")
            return
        }
        startSpeedCapturePromptSpeech()
    }

    private fun startSpeedCapturePromptSpeech() {
        ensureTextToSpeech()
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.SPEAKING_PROMPT,
                speedCaptureTranscript = "",
                localObservationStatus = "Geschwindigkeit erfassen. Jetzt sprechen.",
            )
        }
        if (!textToSpeechReady) {
            scheduleSpeedCaptureListeningStart()
            return
        }
        textToSpeech?.stop()
        isAwaitingSpeedCapturePromptCompletion = true
        speedCapturePromptUtteranceId = "speed-capture-prompt-${System.currentTimeMillis()}"
        mainHandler.removeCallbacks(speedCapturePromptFallbackRunnable)
        mainHandler.postDelayed(speedCapturePromptFallbackRunnable, SpeedCaptureSpeech.promptFallbackDelayMs)
        textToSpeech?.speak(
            SpeedCaptureSpeech.promptText,
            TextToSpeech.QUEUE_FLUSH,
            null,
            speedCapturePromptUtteranceId,
        )
    }

    private fun scheduleSpeedCaptureListeningStart() {
        mainHandler.removeCallbacks(speedCapturePromptFallbackRunnable)
        mainHandler.removeCallbacks(speedCaptureListeningStartRunnable)
        mainHandler.postDelayed(speedCaptureListeningStartRunnable, SpeedCaptureSpeech.startDelayMs)
    }

    private fun startSpeedCaptureListening() {
        if (isSpeedCaptureResolved) {
            return
        }
        val model = bundledVoskModel ?: return showSpeedCaptureFailure(reason = "Offline-Sprachmodell ist nicht geladen.")
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        isSpeedCaptureResolved = false
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.LISTENING,
                speedCaptureTranscript = "",
                localObservationStatus = "Jetzt sprechen: 10 bis 130 oder Fussgaengerzone.",
            )
        }
        val session = runCatching {
            VoskSpeedCaptureSession(model, SpeedCaptureSpeech.voskGrammarJson)
        }.getOrElse {
            showSpeedCaptureFailure(reason = "Offline-Spracherkennung konnte nicht initialisiert werden: ${it.message ?: it.javaClass.simpleName}")
            return
        }
        activeVoskSpeedCaptureSession = session
        val started = runCatching {
            session.start(
                timeoutMs = SpeedCaptureSpeech.listeningWindowMs + SpeedCaptureSpeech.timeoutPaddingMs,
                listener = object : VoskSpeedCaptureSession.Listener {
                    override fun onPartialTranscript(transcript: String) {
                        if (transcript.isNotBlank()) {
                            updateState { copy(speedCaptureTranscript = transcript) }
                            if (SpeedCaptureSpeech.resolveSelection(transcript) != null) {
                                finishSpeedCaptureListening(source = "partial_result", transcripts = listOf(transcript))
                            }
                        }
                    }

                    override fun onCompleted(transcripts: List<String>, source: String) {
                        finishSpeedCaptureListening(source = source, transcripts = transcripts)
                    }

                    override fun onError(message: String) {
                        showSpeedCaptureFailure(reason = "Offline-Spracherkennung fehlgeschlagen: $message")
                    }
                },
            )
        }.getOrElse {
            showSpeedCaptureFailure(reason = "Spracherkennung konnte nicht gestartet werden: ${it.message ?: it.javaClass.simpleName}")
            return
        }
        if (!started) {
            showSpeedCaptureFailure(reason = "Spracherkennung ist bereits aktiv.")
        }
    }

    private fun finishSpeedCaptureListening(@Suppress("UNUSED_PARAMETER") source: String, transcripts: List<String> = emptyList()) {
        if (isSpeedCaptureResolved) {
            return
        }
        isSpeedCaptureResolved = true
        updateState { copy(speedCaptureMode = SpeedCaptureModeState.EVALUATING) }
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        val candidates = (transcripts + uiState.speedCaptureTranscript)
            .map(String::trim)
            .filter(String::isNotEmpty)
            .distinct()
        if (candidates.isEmpty()) {
            cancelSpeedCapture(reason = null)
            return
        }
        val selection = candidates.firstNotNullOfOrNull(SpeedCaptureSpeech::resolveSelection)
        if (selection == null) {
            cancelSpeedCapture(reason = null)
            return
        }
        persistSpeedCaptureSelection(selection)
    }

    private fun stopActiveSpeedCaptureRecognition(clearStatus: Boolean) {
        mainHandler.removeCallbacks(speedCapturePromptFallbackRunnable)
        mainHandler.removeCallbacks(speedCaptureListeningStartRunnable)
        runCatching { activeVoskSpeedCaptureSession?.close() }
        activeVoskSpeedCaptureSession = null
        if (clearStatus) {
            updateState { copy(localObservationStatus = "") }
        }
    }

    private fun showSpeedCaptureFailure(reason: String?) {
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        textToSpeech?.stop()
        resetSpeedCaptureTransientState()
        if (!reason.isNullOrBlank()) {
            host?.showTransientMessage(reason)
        }
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.IDLE,
                speedCaptureTranscript = "",
            )
        }
    }

    private fun resetSpeedCaptureTransientState() {
        mainHandler.removeCallbacks(speedCapturePromptFallbackRunnable)
        mainHandler.removeCallbacks(speedCaptureListeningStartRunnable)
        isAwaitingSpeedCapturePromptCompletion = false
        isSpeedCaptureResolved = false
        shouldResumeSpeedCaptureAfterSpeechModelReady = false
        speedCapturePromptUtteranceId = null
    }

    private fun ensureGermanSpeechModelPrepared(
        force: Boolean,
        userInitiated: Boolean,
    ) {
        if (isGermanSpeechModelCheckInFlight) {
            return
        }
        if (!force && uiState.germanSpeechModelState == GermanSpeechModelState.READY) {
            return
        }
        isGermanSpeechModelCheckInFlight = true
        setGermanSpeechModelState(
            state = GermanSpeechModelState.DOWNLOADING,
            status = "Gebuendeltes deutsches Offline-Sprachmodell wird vorbereitet.",
            updateCaptureStatus = userInitiated || uiState.speedCaptureMode == SpeedCaptureModeState.PREPARING,
        )
        executor.execute {
            runCatching { bundledVoskModelStore.prepareModel() }
                .onSuccess { handle ->
                    replaceBundledVoskModel(handle)
                    markGermanSpeechModelReady("Gebuendeltes deutsches Offline-Sprachmodell ist bereit.")
                    if (shouldResumeSpeedCaptureAfterSpeechModelReady) {
                        mainHandler.post { continuePendingSpeedCaptureIfPossible() }
                    }
                }
                .onFailure { error ->
                    val message = "Gebuendeltes Offline-Sprachmodell konnte nicht vorbereitet werden: ${error.message ?: error.javaClass.simpleName}"
                    isGermanSpeechModelCheckInFlight = false
                    setGermanSpeechModelState(
                        state = GermanSpeechModelState.UNAVAILABLE,
                        status = message,
                        updateCaptureStatus = userInitiated || shouldResumeSpeedCaptureAfterSpeechModelReady,
                    )
                    if (isStartupWaitingForSpeechModel) {
                        failStartupForSpeechModel(message)
                    } else if (userInitiated || uiState.speedCaptureMode != SpeedCaptureModeState.IDLE) {
                        mainHandler.post {
                            showSpeedCaptureFailure(reason = message)
                        }
                    }
                }
        }
    }

    private fun markGermanSpeechModelReady(status: String) {
        isGermanSpeechModelCheckInFlight = false
        setGermanSpeechModelState(
            state = GermanSpeechModelState.READY,
            status = status,
            updateCaptureStatus = false,
        )
        if (isStartupWaitingForSpeechModel) {
            finishStartupAfterSpeechModelReady()
        }
    }

    private fun continuePendingSpeedCaptureIfPossible() {
        if (!shouldResumeSpeedCaptureAfterSpeechModelReady) {
            return
        }
        if (!hasMicrophonePermission()) {
            updateState {
                copy(
                    speedCaptureMode = SpeedCaptureModeState.REQUESTING_MIC_PERMISSION,
                    speedCaptureTranscript = "",
                    localObservationStatus = "Mikrofonberechtigung wird angefragt.",
                )
            }
            host?.requestMicrophonePermission()
            return
        }
        shouldResumeSpeedCaptureAfterSpeechModelReady = false
        prepareSpeedCaptureRecognizerAndMaybeStart()
    }

    private fun setGermanSpeechModelState(
        state: GermanSpeechModelState,
        status: String,
        updateCaptureStatus: Boolean = false,
    ) {
        postState {
            copy(
                germanSpeechModelState = state,
                germanSpeechModelStatus = status,
                startupProgress = if (startupDataState == StartupDataState.LOADING && isStartupWaitingForSpeechModel) {
                    startupProgressForSpeechModelState(state)
                } else {
                    startupProgress
                },
                startupDetail = if (startupDataState == StartupDataState.LOADING && isStartupWaitingForSpeechModel) {
                    status
                } else {
                    startupDetail
                },
                localObservationStatus = if (updateCaptureStatus && speedCaptureMode != SpeedCaptureModeState.IDLE) {
                    status
                } else {
                    localObservationStatus
                },
            )
        }
    }

    private fun finishStartupAfterSpeechModelReady() {
        val prepared = pendingStartupData ?: return
        pendingStartupData = null
        isStartupWaitingForSpeechModel = false
        postState {
            copy(
                startupDataState = StartupDataState.READY,
                startupProgress = 1.0,
                startupDetail = prepared.startupDetail,
                activeBundleVersion = prepared.activeBundleVersion,
                activeDBPath = prepared.activeDBPath,
                activePenaltyRules = prepared.activePenaltyRules,
                syncStatus = prepared.syncStatus,
                localObservations = prepared.localObservations,
                driveStatus = "stopped",
                speedCaptureMode = SpeedCaptureModeState.IDLE,
                speedCaptureTranscript = "",
                localObservationStatus = "",
                lastError = "",
            )
        }
    }

    private fun failStartupForSpeechModel(message: String) {
        pendingStartupData = null
        isStartupWaitingForSpeechModel = false
        isGermanSpeechModelCheckInFlight = false
        postState {
            copy(
                startupDataState = StartupDataState.FAILED,
                startupProgress = 1.0,
                startupDetail = "Deutsches Sprachmodell konnte nicht vorbereitet werden",
                speedCaptureMode = SpeedCaptureModeState.IDLE,
                speedCaptureTranscript = "",
                localObservationStatus = "",
                lastError = message,
            )
        }
    }

    private fun startupProgressForSpeechModelState(state: GermanSpeechModelState): Double {
        return when (state) {
            GermanSpeechModelState.CHECKING -> 0.70
            GermanSpeechModelState.DOWNLOADING -> 0.82
            GermanSpeechModelState.PENDING -> 0.78
            GermanSpeechModelState.READY -> 1.0
            GermanSpeechModelState.UNAVAILABLE -> 1.0
        }
    }

    private fun replaceBundledVoskModel(handle: BundledVoskModelHandle) {
        val previousModel = bundledVoskModel
        bundledVoskModel = handle.model
        bundledVoskModelPath = handle.modelPath
        if (previousModel != null && previousModel !== handle.model) {
            runCatching { previousModel.close() }
        }
    }

    private fun closeBundledVoskModel() {
        val model = bundledVoskModel
        bundledVoskModel = null
        bundledVoskModelPath = null
        if (model != null) {
            runCatching { model.close() }
        }
    }

    private fun playSpeedCaptureConfirmationTone() {
        val tone = confirmationToneGenerator ?: ToneGenerator(AudioManager.STREAM_NOTIFICATION, 75).also {
            confirmationToneGenerator = it
        }
        runCatching { tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 140) }
    }

    private fun activateLocalSpeedCorrectionIfPossible(selection: SpeedCaptureSelection, observation: LocalObservation) {
        val wayId = observation.wayId?.trim().orEmpty()
        if (wayId.isEmpty()) {
            activeLocalSpeedCorrection = null
            return
        }
        val anchorRef = normalizedRoadIdentity(uiState.limitStreetRef)
        val anchorStreet = normalizedRoadIdentity(uiState.limitStreetBaseName ?: uiState.limitStreetName)
        if (anchorRef == null && anchorStreet == null) {
            activeLocalSpeedCorrection = null
            return
        }
        activeLocalSpeedCorrection = ActiveLocalSpeedCorrection(
            maxspeedValue = selection.value,
            numericSpeedKmh = observation.newSpeedKmh,
            anchorStreetName = anchorStreet,
            anchorRef = anchorRef,
            wayIds = setOf(wayId),
        )
    }

    private fun applyActiveLocalSpeedCorrectionIfNeeded(result: SpeedLookupResult): String? {
        val correction = activeLocalSpeedCorrection ?: return null
        val wayId = result.wayId?.trim().orEmpty()
        if (wayId.isEmpty()) {
            return null
        }
        val currentRef = normalizedRoadIdentity(result.streetRef)
        val currentStreet = normalizedRoadIdentity(result.streetBaseName ?: result.streetName)
        val sharesRef = correction.anchorRef != null && correction.anchorRef == currentRef
        val sharesStreet = correction.anchorStreetName != null && correction.anchorStreetName == currentStreet
        if (!sharesRef && !sharesStreet) {
            activeLocalSpeedCorrection = null
            return null
        }
        if (wayId in correction.wayIds) {
            localSpeedOverrideValuesByWayId = localSpeedOverrideValuesByWayId + (wayId to correction.maxspeedValue)
            correction.numericSpeedKmh?.let { localSpeedOverridesByWayId = localSpeedOverridesByWayId + (wayId to it) }
            return correction.maxspeedValue
        }
        val expandedCorrection = correction.copy(wayIds = correction.wayIds + wayId)
        activeLocalSpeedCorrection = expandedCorrection
        localSpeedOverrideValuesByWayId = localSpeedOverrideValuesByWayId + (wayId to expandedCorrection.maxspeedValue)
        expandedCorrection.numericSpeedKmh?.let { localSpeedOverridesByWayId = localSpeedOverridesByWayId + (wayId to it) }
        persistChainedLocalObservation(
            wayId = wayId,
            streetName = result.streetName,
            cityName = result.cityName,
            oldSpeedKmh = result.speedLimitKmh,
            selectedValue = expandedCorrection.maxspeedValue,
            confidence = 0.72,
        )
        return expandedCorrection.maxspeedValue
    }

    private fun persistChainedLocalObservation(
        wayId: String,
        streetName: String?,
        cityName: String?,
        oldSpeedKmh: Int?,
        selectedValue: String,
        confidence: Double?,
    ) {
        executor.execute {
            try {
                localObservationStore.recordSpeedLimitChange(
                    oldSpeedKmh = oldSpeedKmh,
                    newMaxspeedValue = selectedValue,
                    captureContext = currentObservationCaptureContext(
                        wayId = wayId,
                        streetName = streetName,
                        cityName = cityName,
                        confidence = confidence,
                    ),
                    initialState = LocalObservationState.LOCAL_ONLY,
                )
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                postState { copy(localObservations = updated) }
            } catch (_: Exception) {
                return@execute
            }
        }
    }

    private fun normalizedRoadIdentity(raw: String?): String? {
        val normalized = raw
            ?.trim()
            ?.lowercase(Locale.US)
            ?.replace(Regex("\\s+"), " ")
            .orEmpty()
        return normalized.ifBlank { null }
    }

    private fun hasLocationPermission(): Boolean {
        val fine = appContext.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = appContext.checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    private fun hasMicrophonePermission(): Boolean {
        return appContext.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }

    private fun resolveLookupCountryCode(
        dbPath: String,
        preferredCountryCode: String? = null,
    ): String? {
        return normalizedCountryCode(preferredCountryCode)
            ?: normalizedCountryCode(uiState.activePenaltyRules.countryCode)
            ?: inferCountryCodeFromDBPath(dbPath)
    }

    private fun ensureLookupService(
        dbPath: String,
        preferredCountryCode: String? = null,
        matcherProfile: MatcherDebugProfile = uiState.matcherDebugProfile,
    ): V3SpeedLimitLookup {
        val resolvedCountryCode = resolveLookupCountryCode(
            dbPath = dbPath,
            preferredCountryCode = preferredCountryCode,
        )
        val current = lookupService
        if (
            current != null &&
            lookupServicePath == dbPath &&
            lookupServiceCountryCode == resolvedCountryCode &&
            lookupServiceMatcherProfile == matcherProfile
        ) {
            return current
        }
        closeLookupService()
        return V3SpeedLimitLookup(
            dbPath,
            countryCode = resolvedCountryCode,
            matchingModel = matcherProfile.lookupModel,
        ).also {
            lookupService = it
            lookupServicePath = dbPath
            lookupServiceCountryCode = resolvedCountryCode
            lookupServiceMatcherProfile = matcherProfile
        }
    }

    private fun replaceLookupService(
        dbPath: String?,
        preferredCountryCode: String? = null,
        matcherProfile: MatcherDebugProfile = uiState.matcherDebugProfile,
    ) {
        if (dbPath.isNullOrBlank()) {
            closeLookupService()
            return
        }
        val resolvedCountryCode = resolveLookupCountryCode(
            dbPath = dbPath,
            preferredCountryCode = preferredCountryCode,
        )
        if (
            lookupServicePath == dbPath &&
            lookupServiceCountryCode == resolvedCountryCode &&
            lookupServiceMatcherProfile == matcherProfile &&
            lookupService != null
        ) {
            return
        }
        closeLookupService()
        runCatching {
            lookupService = V3SpeedLimitLookup(
                dbPath,
                countryCode = resolvedCountryCode,
                matchingModel = matcherProfile.lookupModel,
            )
            lookupServicePath = dbPath
            lookupServiceCountryCode = resolvedCountryCode
            lookupServiceMatcherProfile = matcherProfile
        }.onFailure {
            lookupService = null
            lookupServicePath = null
            lookupServiceCountryCode = null
            lookupServiceMatcherProfile = null
        }
    }

    private fun closeLookupService() {
        lookupService?.close()
        lookupService = null
        lookupServicePath = null
        lookupServiceCountryCode = null
        lookupServiceMatcherProfile = null
    }

    private fun bootstrapBundledSeedIfNeeded() {
        val active = bootstrapper.activeState()
        if (active?.dbPath?.isNotBlank() == true && File(active.dbPath).exists()) {
            return
        }
        val assetName = BUNDLED_SEED_ASSET_NAME
        val assetInput = assetReader.openOrNull(assetName) ?: return
        assetInput.use { input ->
            val seedDir = File(rootDir, "bundles/seed")
            if (!seedDir.exists()) {
                seedDir.mkdirs()
            }
            val seedFile = File(seedDir, BUNDLED_SEED_DB_FILE_NAME)
            if (!seedFile.exists() || seedFile.length() == 0L) {
                InflaterInputStream(BufferedInputStream(input)).use { inflater ->
                    FileOutputStream(seedFile).use { output ->
                        inflater.copyTo(output)
                    }
                }
            }
            val seedState = ActiveBundleState(
                region = "karlsruhe-regbez",
                countryCode = "DEU",
                bundleVersion = "seed",
                dbFileName = seedFile.name,
                dbPath = seedFile.absolutePath,
                dbSha256 = sha256Hex(seedFile),
                dbBytes = seedFile.length(),
                manifestUrl = "asset://$assetName",
                activatedAtUTC = clock.instant().toString(),
            )
            File(rootDir, "active_bundle.json").writeText(ContractJson.encodeActiveBundleState(seedState))
        }
    }

    private fun resolveLocalSpeedOverrides(observations: List<LocalObservation>): Map<String, Int> {
        val resolved = linkedMapOf<String, Int>()
        observations.forEach { observation ->
            val wayId = observation.wayId?.trim().orEmpty()
            if (observation.state == LocalObservationState.DISCARDED) {
                return@forEach
            }
            val speed = observation.newSpeedKmh ?: observation.newSpeedValue?.toIntOrNull()
            if (wayId.isNotEmpty() && speed != null && speed > 0 && wayId !in resolved) {
                resolved[wayId] = speed
            }
        }
        return resolved
    }

    private fun resolveLocalSpeedOverrideValues(observations: List<LocalObservation>): Map<String, String> {
        val resolved = linkedMapOf<String, String>()
        observations.forEach { observation ->
            val wayId = observation.wayId?.trim().orEmpty()
            val maxspeedValue = observation.newSpeedValue?.trim().orEmpty()
            if (observation.state == LocalObservationState.DISCARDED) {
                return@forEach
            }
            if (wayId.isNotEmpty() && maxspeedValue.isNotEmpty() && wayId !in resolved) {
                resolved[wayId] = maxspeedValue
            }
        }
        return resolved
    }

    private fun speedLimitDisplayTextForValue(maxspeedValue: String?): String? {
        return when (maxspeedValue?.trim()?.lowercase(Locale.US)) {
            "walk" -> "Schritt"
            else -> null
        }
    }

    private fun ensureDrivingLogsExist() {
        gpsLogFile().parentFile?.mkdirs()
        if (!gpsLogFile().exists()) {
            gpsLogFile().writeText(GPS_LOG_HEADER)
        }
        matchLogFile().parentFile?.mkdirs()
        if (!matchLogFile().exists()) {
            matchLogFile().writeText("")
        }
    }

    private fun gpsLogFile(): File = File(rootDir, "logs/gps_fix_log.csv")

    private fun matchLogFile(): File = File(rootDir, "logs/drive_match_log.ndjson")

    private fun appendGpsFixRow(
        fixId: Int,
        location: Location,
        speedKmh: Double,
        status: String,
        result: SpeedLookupResult?,
        overrideSpeedKmh: Int? = null,
        errorText: String? = null,
    ) {
        val row = listOf(
            fixId.toString(),
            Instant.ofEpochMilli(location.time).toString(),
            String.format(Locale.US, "%.7f", location.latitude),
            String.format(Locale.US, "%.7f", location.longitude),
            String.format(Locale.US, "%.2f", speedKmh),
            String.format(Locale.US, "%.2f", location.accuracy.toDouble()),
            if (location.hasVerticalAccuracy()) String.format(Locale.US, "%.2f", location.verticalAccuracyMeters.toDouble()) else "",
            if (location.hasBearing()) String.format(Locale.US, "%.2f", location.bearing.toDouble()) else "",
            status,
            result?.wayId.orEmpty(),
            result?.streetName.orEmpty(),
            result?.cityName.orEmpty(),
            result?.insideCity?.let { if (it) "1" else "0" }.orEmpty(),
            result?.citySource.orEmpty(),
            overrideSpeedKmh?.toString().orEmpty(),
            String.format(Locale.US, "%.3f", result?.queryTimeMs ?: 0.0),
            (result?.candidateCount ?: 0).toString(),
            (result?.speedCandidateCount ?: 0).toString(),
            result?.nearestCandidateDistanceM?.let { String.format(Locale.US, "%.2f", it) }.orEmpty(),
            result?.nearestSpeedCandidateDistanceM?.let { String.format(Locale.US, "%.2f", it) }.orEmpty(),
            errorText.orEmpty(),
        )
        gpsLogFile().appendText(row.joinToString(",") { csvEscape(it) } + "\n")
    }

    private fun appendMatchLogEntry(
        fixId: Int,
        location: Location,
        speedKmh: Double,
        status: String,
        result: SpeedLookupResult?,
        matchContext: WayMatchContext?,
        gpsSignalBars: Int,
        overrideSpeedKmh: Int? = null,
        errorText: String? = null,
    ) {
        val timestampUtc = Instant.ofEpochMilli(location.time).toString()
        val horizontalAccM = location.accuracy.toDouble().takeIf { it >= 0.0 } ?: 0.0
        val verticalAccM = if (location.hasVerticalAccuracy()) location.verticalAccuracyMeters.toDouble() else 0.0
        val courseDeg = if (location.hasBearing()) location.bearing.toDouble() else -1.0
        val tunnelModeState = when {
            result?.isTunnelSegment == true || matchContext?.isInTunnelMode == true -> "active"
            else -> "inactive"
        }

        val entry = JSONObject().apply {
            put("fixID", fixId)
            put("timestampUTC", timestampUtc)
            put("lat", location.latitude)
            put("lon", location.longitude)
            put("speedKmh", speedKmh)
            put("horizontalAccM", horizontalAccM)
            put("verticalAccM", verticalAccM)
            put("courseDeg", courseDeg)
            put("gpsSignalBars", gpsSignalBars)
            put("status", status)
            overrideSpeedKmh?.let { put("speedLimitOverrideKmh", it) }
            put("tunnelModeState", tunnelModeState)
            result?.let { put("result", buildRichMatchResultJson(it, matchContext, horizontalAccM)) }
            errorText?.let { put("error", it) }

            // Preserve the old Android flat schema for existing tooling.
            put("timestamp_utc", timestampUtc)
            put("speed_kmh", speedKmh)
            put("gps_signal_bars", gpsSignalBars)
            result?.wayId?.let { put("way_id", it) }
            result?.streetName?.let { put("street_name", it) }
            result?.cityName?.let { put("city_name", it) }
            result?.insideCity?.let { put("inside_city", it) }
            result?.citySource?.let { put("city_source", it) }
            overrideSpeedKmh?.let { put("speed_limit_kmh", it) }
            result?.queryTimeMs?.let { put("query_ms", it) }
            result?.candidateCount?.let { put("candidate_count", it) }
            result?.speedCandidateCount?.let { put("speed_candidate_count", it) }
            result?.nearestCandidateDistanceM?.let { put("nearest_candidate_m", it) }
            result?.nearestSpeedCandidateDistanceM?.let { put("nearest_speed_candidate_m", it) }
        }

        matchLogFile().appendText(entry.toString() + "\n")
    }

    private fun buildRichMatchResultJson(
        result: SpeedLookupResult,
        matchContext: WayMatchContext?,
        horizontalAccM: Double,
    ): JSONObject {
        val selectedTrace = result.candidateTraces.firstOrNull { it.isSelected }
        return JSONObject().apply {
            result.speedLimitKmh?.let { put("speedLimitKmh", it) }
            put("isUnlimitedSpeedLimit", result.isUnlimitedSpeedLimit)
            result.wayId?.let { put("wayID", it) }
            result.highway?.let { put("highway", it) }
            selectedTrace?.service?.let { put("service", it) }
            selectedTrace?.tunnel?.let { put("tunnel", it) }
            put("isTunnelSegment", result.isTunnelSegment)
            result.streetName?.let { put("streetName", it) }
            result.streetBaseName?.let { put("streetBaseName", it) }
            result.streetRef?.let { put("streetRef", it) }
            result.matchedEndpointProximityM?.let { put("matchedEndpointProximityM", it) }
            result.cityName?.let { put("cityName", it) }
            result.insideCity?.let { put("insideCity", it) }
            result.citySource?.let { put("citySource", it) }
            put("cityResolveMs", 0.0)
            put("cityCandidateBoundaries", 0)
            put("cityContainingBoundaries", 0)
            put("cityPlaceCandidates", 0)
            put("queryTimeMs", result.queryTimeMs)
            put("candidateCount", result.candidateCount)
            put("speedCandidateCount", result.speedCandidateCount)
            result.nearestCandidateDistanceM?.let { put("nearestCandidateDistanceM", it) }
            result.nearestSpeedCandidateDistanceM?.let { put("nearestSpeedCandidateDistanceM", it) }
            put("nearbyTunnelCandidateWayIDs", jsonStringArray(result.nearbyTunnelCandidateWayIds.sorted()))
            put("nearbyTunnelCandidateRefs", jsonStringArray(result.nearbyTunnelCandidateRefs.sorted()))
            put("usedMiniHMM", result.usedMiniHMM)
            put("miniHMMCandidateCount", result.miniHMMCandidateCount)
            put("matchHypotheses", JSONArray().apply {
                result.matchHypotheses.forEach { put(buildHypothesisJson(it)) }
            })
            put("candidateTraces", JSONArray().apply {
                result.candidateTraces.forEach { put(buildCandidateTraceJson(it)) }
            })
            val selectionTrace = if (result.selectionTrace.isNotEmpty()) {
                buildSelectionTraceJson(result.selectionTrace)
            } else {
                buildFallbackSelectionTraceJson(matchContext, result, horizontalAccM)
            }
            put("selectionTrace", selectionTrace)
            result.activeCorridorState?.let { put("activeCorridorState", buildCorridorStateJson(it)) }
        }
    }

    private fun buildHypothesisJson(hypothesis: WayMatchHypothesis): JSONObject {
        return JSONObject().apply {
            put("wayID", hypothesis.wayId)
            hypothesis.streetRef?.let { put("streetRef", it) }
            hypothesis.highway?.let { put("highway", it) }
            hypothesis.corridorState?.let { put("corridorState", it) }
            hypothesis.corridorKind?.let { put("corridorKind", it) }
            hypothesis.corridorId?.let { put("corridorID", it) }
            hypothesis.corridorSideNodeKey?.let { put("corridorSideNodeKey", it) }
            put("cumulativeCost", hypothesis.cumulativeCost)
            put("emissionScore", hypothesis.emissionScore)
            put("endpointProximityM", hypothesis.endpointProximityM)
            hypothesis.startLat?.let { put("startLat", it) }
            hypothesis.startLon?.let { put("startLon", it) }
            hypothesis.endLat?.let { put("endLat", it) }
            hypothesis.endLon?.let { put("endLon", it) }
            put("isTunnel", hypothesis.isTunnel)
        }
    }

    private fun buildCandidateTraceJson(trace: MatcherCandidateTrace): JSONObject {
        return JSONObject().apply {
            put("rank", trace.rank)
            trace.wayId?.let { put("wayID", it) }
            trace.streetName?.let { put("streetName", it) }
            trace.streetRef?.let { put("streetRef", it) }
            trace.highway?.let { put("highway", it) }
            trace.service?.let { put("service", it) }
            trace.tunnel?.let { put("tunnel", it) }
            put("distanceM", trace.distanceM)
            put("endpointProximityM", trace.endpointProximityM)
            put("score", trace.score)
            trace.geometryScore?.let { put("geometryScore", it) }
            put("portalEligible", trace.portalEligible)
            put("continuityClass", trace.continuityClass)
            put("tunnelSelectable", trace.tunnelSelectable)
            put("corridorSelectable", trace.corridorSelectable)
            put("isSelected", trace.isSelected)
        }
    }

    private fun buildSelectionTraceJson(traces: List<MatchSelectionTrace>): JSONArray {
        return JSONArray().apply {
            traces.forEach { trace ->
                put(selectionTraceStep(step = trace.step, detail = trace.detail))
            }
        }
    }

    private fun buildFallbackSelectionTraceJson(
        matchContext: WayMatchContext?,
        result: SpeedLookupResult,
        horizontalAccM: Double,
    ): JSONArray {
        val selectedTrace = result.candidateTraces.firstOrNull { it.isSelected }
        val accuracyText = String.format(Locale.US, "%.1f", horizontalAccM)
        return JSONArray().apply {
            put(
                selectionTraceStep(
                    step = "context",
                    detail = buildString {
                        append("preferred=").append(matchContext?.preferredWayId ?: "nil")
                        append(" tunnel_mode=").append(matchContext?.isInTunnelMode == true)
                        append(" gps_loss=").append(matchContext?.hadRecentGpsSignalLoss == true)
                        append(" tunnel_approach=").append(matchContext?.tunnelApproachFixCount ?: 0)
                        append(" corridor_approach=").append(matchContext?.approachCorridorFixCount ?: 0)
                        append(" match_streak=").append(matchContext?.matchedFixCount ?: 0)
                        append(" accuracy_m=").append(accuracyText)
                    },
                ),
            )
            if (selectedTrace != null) {
                put(
                    selectionTraceStep(
                        step = "heuristic",
                        detail = "selected ${result.wayId ?: "nil"} continuity=${selectedTrace.continuityClass}",
                    ),
                )
            }
            if (result.usedWalkingTurnSwitch) {
                put(
                    selectionTraceStep(
                        step = "walking_turn_switch",
                        detail = "selected ${result.wayId ?: "nil"} due to low-speed geometric switch",
                    ),
                )
            }
            put(
                selectionTraceStep(
                    step = "final",
                    detail = "selected ${result.wayId ?: "nil"} tunnel=${result.isTunnelSegment} corridor=${result.activeCorridorState?.kind ?: "none"}",
                ),
            )
        }
    }

    private fun selectionTraceStep(step: String, detail: String): JSONObject {
        return JSONObject().apply {
            put("step", step)
            put("detail", detail)
        }
    }

    private fun buildCorridorStateJson(state: CorridorMatchState): JSONObject {
        return JSONObject().apply {
            put("kind", state.kind)
            put("corridorID", state.corridorId)
            put("sideNodeKey", state.sideNodeKey)
            put("depthM", state.depthM)
            put("spanM", state.spanM)
            put("depthNodes", state.depthNodes)
            put("spanNodes", state.spanNodes)
        }
    }

    private fun jsonStringArray(values: Iterable<String>): JSONArray {
        return JSONArray().apply {
            values.forEach { put(it) }
        }
    }

    private fun csvEscape(value: String): String {
        if (value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r")) {
            return "\"${value.replace("\"", "\"\"")}\""
        }
        return value
    }

    private fun inferCountryCodeFromDBPath(dbPath: String?): String? {
        val fileName = File(dbPath ?: return null).name.uppercase(Locale.US)
        if (fileName.length < 3) {
            return null
        }
        val prefix = fileName.take(3)
        return prefix.takeIf { it.all(Char::isLetter) }
    }

    private fun normalizedCountryCode(raw: String?): String? {
        val code = raw?.trim()?.uppercase(Locale.US) ?: return null
        return code.takeIf { it.length == 3 }
    }

    private fun sha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) {
                    break
                }
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun updateState(transform: ConsumerUiState.() -> ConsumerUiState) {
        uiState = uiState.transform()
    }

    private fun postState(transform: ConsumerUiState.() -> ConsumerUiState) {
        mainHandler.post {
            uiState = uiState.transform()
        }
    }

    companion object {
        private const val KEY_AUDIO_ALERT_THRESHOLD = "youspeed.audio_alert_threshold_kmh"
        private const val KEY_AUDIO_ALERTS_ENABLED = "youspeed.audio_alerts_enabled"
        private const val KEY_HIDE_WELCOME = "youspeed.hide_welcome_screen"
        private const val KEY_MATCHER_DEBUG_PROFILE = "youspeed.matcher_debug_profile"
        private const val KEY_MATCHER_DEBUG_PROFILE_FORCED_VERSION = "youspeed.matcher_debug_profile_forced_version"
        private const val DRIVING_BAN_WARNING_REMINDER_MS = 24_000L
        private const val BUNDLED_SEED_ASSET_NAME = "karlsruhe-regbez_speeds.sqlite.zlib"
        private const val BUNDLED_SEED_DB_FILE_NAME = "karlsruhe-regbez_speeds.sqlite"
        private const val GPS_LOG_HEADER = "fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m,vacc_m,bearing_deg,status,way_id,street_name,city_name,inside_city,city_source,speed_limit_kmh,query_ms,candidate_count,speed_candidate_count,nearest_candidate_m,nearest_speed_candidate_m,error\n"

        private fun gpsSignalBars(horizontalAccuracyM: Double?): Int {
            val accuracy = horizontalAccuracyM ?: return 0
            if (!accuracy.isFinite() || accuracy < 0.0) {
                return 0
            }
            return when {
                accuracy < 8.0 -> 4
                accuracy < 15.0 -> 3
                accuracy < 30.0 -> 2
                accuracy < 60.0 -> 1
                else -> 0
            }
        }

        private fun lookupRadiusForHorizontalAccuracy(horizontalAccuracyM: Double): Double {
            if (!horizontalAccuracyM.isFinite() || horizontalAccuracyM < 0.0) {
                return 180.0
            }
            val radius = (horizontalAccuracyM * 3.0) + 20.0
            return radius.coerceIn(60.0, 600.0)
        }

        private fun filteredDisplaySpeedKmh(
            rawSpeedKmh: Double,
            speedAccuracyKmh: Double?,
            previousDisplaySpeedKmh: Double,
        ): Double {
            val standstillEnterThresholdKmh = 4.0
            val standstillExitThresholdKmh = 6.0
            val standstillAccuracyMarginKmh = 1.0
            if (!rawSpeedKmh.isFinite() || rawSpeedKmh <= 0.0) {
                return 0.0
            }
            val normalizedAccuracyKmh = speedAccuracyKmh?.takeIf { it.isFinite() && it >= 0.0 }
            if (previousDisplaySpeedKmh <= 0.5 && rawSpeedKmh < standstillExitThresholdKmh) {
                return 0.0
            }
            val enterThreshold = min(
                standstillExitThresholdKmh,
                max(
                    standstillEnterThresholdKmh,
                    (normalizedAccuracyKmh ?: 0.0) + standstillAccuracyMarginKmh,
                ),
            )
            return if (rawSpeedKmh <= enterThreshold) 0.0 else rawSpeedKmh
        }
    }
}

private class AndroidAssetReader(
    private val context: Context,
) {
    fun readText(name: String): String {
        return context.assets.open(name).bufferedReader().use { it.readText() }
    }

    fun readTextOrNull(name: String): String? {
        return runCatching { readText(name) }.getOrNull()
    }

    fun readTextOrEmpty(name: String): String = readTextOrNull(name).orEmpty()

    fun openOrNull(name: String): InputStream? {
        return runCatching { context.assets.open(name) }.getOrNull()
    }
}

private fun Locale.getDisplayCountryForCode(code: String): String {
    return if (code.length == 2) {
        Locale("", code.uppercase(Locale.US)).getDisplayCountry(this)
    } else {
        ""
    }
}

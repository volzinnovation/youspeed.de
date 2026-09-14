package de.youspeed.android.alpha

import android.annotation.SuppressLint
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.media.AudioManager
import android.media.ToneGenerator
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.os.VibrationEffect
import android.os.VibratorManager
import androidx.camera.core.Preview
import java.time.Duration
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
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.zip.InflaterInputStream
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
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

enum class TrafficSignDebugIndicator {
    NORMAL,
    INVALID_ROAD_CONTEXT,
    GENERATION_SESSION_CONTEXT_MISMATCH,
    RUNTIME_UNHEALTHY,
}

enum class DriveRecorderState {
    DISABLED,
    REQUESTING_PERMISSION,
    PREPARING,
    RECORDING,
    STOPPING,
    DENIED,
    UNAVAILABLE,
    FAILED,
}

data class DashcamRecording(
    val path: String,
    val createdAt: Instant,
    val bytes: Long,
)

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
    val evidenceJson: String? = null,
    val evidenceSummary: String? = null,
    val primaryWayId: String? = null,
    val effectiveAtUTC: String = capturedAtUTC,
    val finalizedEventId: String? = null,
    val runtimeApplicable: Boolean = false,
    val actionKind: TrafficSignActionKind? = null,
    val resolvedLimitKind: TrafficSignResolvedLimitKind? = null,
    val directionScope: TrafficSignTravelDirection = TrafficSignTravelDirection.UNKNOWN,
    val permanent: Boolean = true,
    val unconditional: Boolean = true,
    val osmTagKey: String? = null,
    val canonicalValue: String? = null,
    val supersededForExport: Boolean = false,
) {
    val streetName: String
        get() = streetContext?.trim().orEmpty().ifBlank { ConsumerRuntimeText.STREET_UNKNOWN.text() }

    val wayId: String?
        get() = primaryWayId?.trim()?.ifBlank { null }
            ?: roadCandidateIds.firstOrNull()?.trim()?.ifBlank { null }

    val newSpeedValue: String?
        get() = canonicalValue?.trim()?.ifBlank { null }
            ?: value?.trim()?.ifBlank { null }
            ?: newSpeedKmh?.toString()
}

internal data class ActiveLocalSpeedCorrection(
    val wayId: String,
    val maxspeedValue: String,
    val numericSpeedKmh: Int?,
)

internal enum class LocalSpeedCorrectionDecision {
    KEEP_WAITING,
    APPLY,
    EXPIRE,
}

internal object LocalSpeedCorrectionPolicy {
    fun decide(activeWayId: String, matchedWayId: String?): LocalSpeedCorrectionDecision {
        val normalizedMatchedWayId = matchedWayId?.trim().orEmpty()
        if (normalizedMatchedWayId.isEmpty()) {
            return LocalSpeedCorrectionDecision.KEEP_WAITING
        }
        return if (normalizedMatchedWayId == activeWayId) {
            LocalSpeedCorrectionDecision.APPLY
        } else {
            LocalSpeedCorrectionDecision.EXPIRE
        }
    }
}

/** Serializes the "is this still the newest GPS lookup?" check with TSR mutation. */
internal class TrafficSignLookupMutationGate {
    private val lock = Any()
    private var token = 0L

    fun advance(): Long = synchronized(lock) {
        token += 1L
        token
    }

    fun isCurrent(expected: Long): Boolean = synchronized(lock) { token == expected }

    fun <T> mutateIfCurrent(expected: Long, block: () -> T): T? = synchronized(lock) {
        if (token != expected) null else block()
    }
}

/** Builds the local source beneath a camera assertion after its durable CV write. */
internal fun trafficSignBaseForPersistedCorrection(
    currentContext: TrafficSignDetectionContext?,
    correction: LocalRuntimeCorrection,
): TrafficSignBaseLimit? {
    val current = currentContext ?: return null
    if (current.wayId != correction.wayId) return null
    if (correction.directionScope != TrafficSignTravelDirection.UNKNOWN &&
        current.travelDirection != correction.directionScope
    ) {
        return null
    }
    val resolution = when (val value = correction.canonicalValue.trim().lowercase(Locale.US)) {
        "walk" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.WALK)
        "none" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNLIMITED)
        else -> value.toIntOrNull()?.takeIf(::isSharedTrafficSignSpeedKmh)?.let { speed ->
            TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, speed)
        }
    } ?: return null
    return TrafficSignBaseLimit(
        resolution = resolution,
        source = EffectiveSpeedLimitSource.LOCAL_CORRECTION,
        reason = "local_correction:${correction.observationId}",
    )
}

private data class TrafficSignEvaluationOutcome(
    val effective: EffectiveSpeedLimit,
    val activatedPassage: TrafficSignPassageEvent?,
    val persistablePassage: TrafficSignPassageEvent?,
    val generation: Long,
    val tsrWasEnabled: Boolean,
    val invalidatedByCityEntry: Boolean = false,
)

private data class PendingStartupData(
    val startupDetail: String,
    val activeBundleVersion: String,
    val activeDBPath: String,
    val syncStatus: String,
    val localObservations: List<LocalObservation>,
)

data class ConsumerUiState(
    val startupDataState: StartupDataState = StartupDataState.LOADING,
    val startupProgress: Double = 0.0,
    val startupDetail: String = ConsumerRuntimeText.STARTUP_PREPARING.text(),
    val syncStatus: String = "not_synced",
    val syncProgressDetail: String = "",
    val syncProgressCompletedBytes: Long = 0L,
    val syncProgressTotalBytes: Long = 0L,
    val maintenanceMessage: String = "",
    val activeDownloadOptionId: String? = null,
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
    val limitCityPlaceName: String? = null,
    val limitCityDistrictName: String? = null,
    val currentLatitude: Double? = null,
    val currentLongitude: Double? = null,
    val gpsHorizontalAccuracyM: Double? = null,
    val gpsSignalBars: Int = 0,
    val gpsFixCount: Int = 0,
    val coarseLatitude: Double? = null,
    val coarseLongitude: Double? = null,
    val coarseHorizontalAccuracyM: Double? = null,
    val coarseLocationSource: String? = null,
    val coarseCityName: String? = null,
    val coarseCityPlaceName: String? = null,
    val coarseCityDistrictName: String? = null,
    val coarseCitySource: String? = null,
    val gpsLogPath: String = "",
    val matchLogPath: String = "",
    val runtimeDiagnosticsLogPath: String = "",
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
    val onboardingCompleted: Boolean = false,
    val onboardingStep: Int = 0,
    val onboardingSelectedMapId: String? = null,
    val onboardingSuggestedMapId: String? = null,
    val onboardingLocationRequested: Boolean = false,
    val onboardingLocating: Boolean = false,
    val preciseLocationGranted: Boolean = false,
    val bundleDownloadSections: List<BundleDownloadCountrySection> = emptyList(),
    val firstLocationPackStatus: String = ConsumerRuntimeText.FIRST_LOCATION_WAITING.text(),
    val countryModelPackStatus: String = ConsumerRuntimeText.MODEL_COUNTRY_PENDING.text(),
    val downloadedBundleCountByRegion: Map<String, Int> = emptyMap(),
    val downloadedBundleLatestVersionByRegion: Map<String, String> = emptyMap(),
    val configuredManifestEndpointCount: Int = 0,
    val configuredManifestCountryCodes: String = "n/a",
    val activePenaltyRules: ActivePenaltyRules = ActivePenaltyRules.unavailable(),
    val localObservations: List<LocalObservation> = emptyList(),
    val localObservationStatus: String = "",
    val speedCaptureMode: SpeedCaptureModeState = SpeedCaptureModeState.IDLE,
    val speedCaptureTranscript: String = "",
    val germanSpeechModelState: GermanSpeechModelState = GermanSpeechModelState.CHECKING,
    val germanSpeechModelStatus: String = ConsumerRuntimeText.SPEECH_MODEL_PREPARING.text(),
    val lastExportDirectoryPath: String = "",
    val appScreenshotState: AppScreenshotState? = null,
    val lastLookupInsideCity: Boolean? = null,
    val tunnelModeState: TunnelModeState = TunnelModeState.INACTIVE,
    val isLowSpeedMatchingRuleActive: Boolean = false,
    val matcherDebugProfile: MatcherDebugProfile = MatcherDebugProfile.default,
    val trafficSignRecognitionEnabled: Boolean = false,
    val trafficSignRecognitionIndependentEnabled: Boolean = false,
    val trafficSignFeedbackMode: TrafficSignFeedbackMode = TrafficSignFeedbackMode.SOUND,
    val trafficSignLastEvent: TrafficSignRecognitionEvent? = null,
    val trafficSignRecognitionUnavailable: Boolean = false,
    val trafficSignDebugRoadContextInvalid: Boolean = false,
    val trafficSignDebugGenerationSessionContextMismatch: Boolean = false,
    val trafficSignDebugRuntimeUnhealthy: Boolean = false,
    val otherTrafficSignDisplayEnabled: Boolean = false,
    val lastTrafficSignPictogram: TrafficSignPictogram? = null,
    val isTrafficSignEndOverlayVisible: Boolean = false,
    val trafficSignCameraRuntimeState: TrafficSignCameraRuntimeState = TrafficSignCameraRuntimeState.DISABLED,
    val trafficSignCameraRuntimeDetail: String = ConsumerRuntimeText.CAMERA_DISABLED.text(),
    val panoramaxCaptureEnabled: Boolean = true,
    val panoramaxTriggerMode: PanoramaxCaptureTriggerMode = PanoramaxCaptureTriggerMode.DISTANCE,
    val panoramaxMinimumDistanceMeters: Double = 25.0,
    val panoramaxMinimumIntervalSeconds: Double = 5.0,
    val panoramaxUnlimitedStorage: Boolean = false,
    val panoramaxStorageLimitMB: Double = 1000.0,
    val panoramaxDeleteUploadedImages: Boolean = false,
    val panoramaxMaintenanceIssue: String? = null,
    val panoramaxMaintenanceInProgress: Boolean = true,
    val panoramaxAccountConnected: Boolean = false,
    val panoramaxAccountHasToken: Boolean = false,
    val panoramaxAccountBusy: Boolean = false,
    val panoramaxAccountStatus: String = "",
    val panoramaxActiveUploadBatchIds: Set<String> = emptySet(),
    val panoramaxUploadStatusByBatch: Map<String, String> = emptyMap(),
    val panoramaxUploadProgressByBatch: Map<String, PanoramaxUploadProgress> = emptyMap(),
    val panoramaxCaptureCount: Int = 0,
    val panoramaxLastCaptureDetail: String = "No photo captured",
    val panoramaxBatches: List<PanoramaxBatchRecord> = emptyList(),
    val driveRecorderState: DriveRecorderState = DriveRecorderState.DISABLED,
    val driveRecorderStartedAt: Instant? = null,
    val dashcamRecordingEnabled: Boolean = false,
    val driveRecorderDashcamActive: Boolean = false,
    val driveRecorderDashcamTransitioning: Boolean = false,
    val driveRecorderPanoramaxActive: Boolean = false,
    val dashcamRecordings: List<DashcamRecording> = emptyList(),
    val trafficSignGeneration: Long = 0L,
    val effectiveSpeedLimitSource: EffectiveSpeedLimitSource = EffectiveSpeedLimitSource.NONE,
    val effectiveSpeedLimitReason: String = "no_limit",
    val cameraSpeedLimitEvidence: Boolean = false,
    val trafficSignFinalConfidence: Double? = null,
    val trafficSignAccumulatedSupport: Double? = null,
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
    CAMERA_LIMIT_ACTIVE("camera-limit-active"),
    OTHER_SIGN_GIVE_WAY("other-sign-give-way"),
    OTHER_SIGN_STOP("other-sign-stop"),
    OTHER_SIGN_CLEARED("other-sign-cleared"),
    PEDESTRIAN_ZONE("pedestrian-zone"),
    AUTOBAHN_UNLIMITED_ABOVE_130("autobahn-unlimited-above-130");

    val fixture: AppScreenshotFixture
        get() = when (this) {
            WARN_LEVEL_0 -> AppScreenshotFixture(47.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-0", true, 49.0102, 8.4266, 6.0, 4)
            WARN_LEVEL_1 -> AppScreenshotFixture(67.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-1", true, 49.0102, 8.4266, 6.0, 4)
            WARN_LEVEL_2 -> AppScreenshotFixture(73.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-2", true, 49.0102, 8.4266, 6.0, 4)
            WARN_LEVEL_3 -> AppScreenshotFixture(86.0, 50, null, false, "Durlacher Allee", "Karlsruhe", "karlsruhe-warn-3", true, 49.0102, 8.4266, 6.0, 4)
            CAMERA_LIMIT_ACTIVE, OTHER_SIGN_GIVE_WAY, OTHER_SIGN_STOP, OTHER_SIGN_CLEARED -> AppScreenshotFixture(0.0, 30, null, false, "Lindenweg", "Bad Herrenalb", "bad-herrenalb-camera-limit-active", true, 48.7966, 8.4361, 5.0, 4)
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
    private val countryScreenshotScenario: CountryPenaltyScreenshotScenario? = null,
) {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val isDisposed = AtomicBoolean(false)
    private val assetReader = AndroidAssetReader(appContext)
    private val trafficSignDisplayCatalog by lazy {
        appContext.assets.open(TrafficSignDisplayCatalog.ASSET_PATH).bufferedReader().use {
            TrafficSignDisplayCatalog.decode(it.readText())
        }
    }
    private val bootstrapper = BundleBootstrapper(
        rootDir = rootDir,
        httpFetcher = HttpUrlFetcher(),
        clock = clock,
        assetReader = assetReader,
    )
    private val locationManager = appContext.getSystemService(Context.LOCATION_SERVICE) as LocationManager
    private val targetsConfig = runCatching {
        ContractJson.decodeBundleTargets(assetReader.readText("BundleTargets.top10.json"))
    }.getOrNull()
    private val manifestEndpoints = targetsConfig?.manifestEndpoints(preferredCountryCode = "DEU").orEmpty()
    private val regionalPackCatalog = runCatching {
        RegionalPackCatalog.decode(assetReader.readText("RegionalCoverage/catalog-v1.json").toByteArray())
    }.getOrNull()
    private val countryPackRegistry = runCatching {
        TrafficSignCountryPackRegistry.decodeBundled(assetReader.readText("tsr/country-pack-registry-v1.json").toByteArray())
    }.getOrNull()
    private val countryPackSelection = TrafficSignCountrySelection()
    private val penaltyCountrySelection = PenaltyCountrySelection()
    private val penaltyCountryExpiry = Runnable {
        val country = penaltyCountrySelection.expire(clock.millis() / 1000.0)
        updateState { copy(activePenaltyRules = country?.let(::loadPenaltyRules) ?: ActivePenaltyRules.unavailable()) }
    }
    private var firstLocationRegion: RegionalPackCatalog.Region? = null
    private var firstLocationRequested = false
    private var locationSuggestionGeneration = 0L
    private val firstLocationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) { discoverPacks(location) }
    }
    private val lookupToken = TrafficSignLookupMutationGate()
    private val trafficSignGeneration = TrafficSignWriteGate()
    private val localObservationStore = LocalObservationStore(appContext, rootDir, preferences, clock)
    private val panoramaxQueueStore = PanoramaxQueueStore(appContext)
    private val panoramaxAccount by lazy {
        PanoramaxAccount(appContext).also { account ->
            account.onChange = { postState { copy(panoramaxAccountConnected = account.state.isConnected,
                panoramaxAccountHasToken = account.state.hasToken, panoramaxAccountBusy = account.state.isBusy,
                panoramaxAccountStatus = account.state.status) } }
        }
    }
    private val panoramaxUploader by lazy {
        PanoramaxUploadCoordinator(panoramaxQueueStore, panoramaxAccount,
            canProcessUploads = ::canProcessPanoramaxUploads,
            deleteUploadedImages = { uiState.panoramaxDeleteUploadedImages },
            onChange = { refreshPanoramaxUploadState() })
    }
    private val dashcamDirectory = File(appContext.filesDir, "dashcam").apply { mkdirs() }
    private val wayMatchTracker = WayMatchSessionTracker()
    private val trafficSignResolver = TrafficSignRuntimeSourceResolver()
    private var trafficSignEndOverlayGeneration = 0L
    private var trafficSignEndOverlayHideRunnable: Runnable? = null
    private val trafficSignEndOverlayDurationMs = 2_000L
    private val trafficSignStateLock = Any()
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
    private var trafficSignDriveSessionId: String? = null
    private val lookupServiceLock = Any()
    private var lookupService: V3SpeedLimitLookup? = null
    private var lookupServicePath: String? = null
    private var lookupServiceCountryCode: String? = null
    private var lookupServiceMatcherProfile: MatcherDebugProfile? = null
    private var localSpeedOverridesByWayId: Map<String, Int> = emptyMap()
    private var localSpeedOverrideValuesByWayId: Map<String, String> = emptyMap()
    private var latestTrafficSignContext: TrafficSignDetectionContext? = null
    private var lastTrafficSignDebugLogSignature: String? = null
    private var lastTrafficSignDebugLogAtMs = 0L
    private var latestTrafficSignBase = TrafficSignBaseLimit(null, EffectiveSpeedLimitSource.NONE, "no_limit")
    private var latestResolverLocation: Location? = null
    @Volatile private var latestCaptureLocation: Location? = null
    private var coarseLocationSequence = 0L
    private var latestTrafficSignDirection = TrafficSignTravelDirection.UNKNOWN
    private var latestTrafficSignInsideCity: Boolean? = null
    private val trafficSignTraversalTracker = TrafficSignTraversalTracker()
    private var trafficSignTraversalEpoch = 1L
    private var lastTrafficSignInferenceLogAtMs = 0L
    private var lastAudioFeedbackAtMs = 0L
    private var lastAnnouncedSpeechText: String? = null
    private var wasDrivingBanWarningActive = false
    private var lastDrivingBanWarningAtMs = 0L
    private val recentSpeedSampleLocations: MutableList<Location> = mutableListOf()
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private var bundledVoskModel: Model? = null
    private var bundledVoskModelPath: String? = null
    private var activeVoskSpeedCaptureSession: VoskSpeedCaptureSession? = null
    private var speedCapturePromptUtteranceId: String? = null
    private var isAwaitingSpeedCapturePromptCompletion = false
    private var isSpeedCaptureResolved = false
    private var activeLocalSpeedCorrection: ActiveLocalSpeedCorrection? = null
    private var panoramaxCaptureEnabled = preferences.getBoolean(KEY_PANORAMAX_CAPTURE_ENABLED, true)
    @Volatile private var driveRecorderEnabled = false
    @Volatile private var applicationActive = true
    private val captureLock = Any()
    private val feedbackGate = TrafficSignFeedbackGate()
    private var confirmationToneUntilMs = 0L
    private var activeDashcamPath: String? = null
    @Volatile private var latestDashcamEventPath: String? = null
    private data class PendingPhoto(val requestId: String, val sessionId: String,
        val sample: PanoramaxLocationSample, val drafts: List<PanoramaxTrafficSignAnnotationDraft>)
    private var pendingPhoto: PendingPhoto? = null
    private var latestAnnotationDrafts: List<PanoramaxTrafficSignAnnotationDraft> = emptyList()
    private var panoramaxCaptureSessionId: String? = null
    private var panoramaxLastCaptureSample: PanoramaxLocationSample? = null
    private var panoramaxCaptureInFlight = false
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
            if (!isDriving || !hasFineLocationPermission() || location.provider == LocationManager.NETWORK_PROVIDER) {
                return
            }
            consumeLocation(location)
        }

        override fun onProviderEnabled(provider: String) = Unit

        override fun onProviderDisabled(provider: String) = Unit

        @Deprecated("Deprecated in Java")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
    }

    /** Network provider uses Wi-Fi/cell positioning on Android. It is useful
     * for administrative context only; it must never drive speed matching or
     * Panoramax capture. */
    private val coarseLocationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            if (isDriving) {
                consumeCoarseLocation(location)
            }
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
            onboardingCompleted = preferences.getBoolean(OnboardingPolicy.COMPLETED_KEY, false),
            onboardingStep = preferences.getInt(OnboardingPolicy.STEP_KEY, 0).coerceIn(0, OnboardingPolicy.LAST_STEP),
            onboardingSelectedMapId = preferences.getString("youspeed.onboarding.selected_map", null),
            onboardingLocationRequested = preferences.getBoolean("youspeed.onboarding.location_requested", false),
            preciseLocationGranted = hasFineLocationPermission(),
            gpsLogPath = gpsLogFile().absolutePath,
            matchLogPath = matchLogFile().absolutePath,
            runtimeDiagnosticsLogPath = runtimeDiagnosticsLogFile().absolutePath,
            bundleDownloadSections = buildBundleDownloadSections(),
            configuredManifestEndpointCount = manifestEndpoints.size,
            configuredManifestCountryCodes = manifestCountryCodes(),
            activePenaltyRules = ActivePenaltyRules.unavailable(),
            appScreenshotState = launchScreenshotState,
            matcherDebugProfile = initialMatcherDebugProfile,
            trafficSignRecognitionEnabled = preferences.getBoolean(KEY_TRAFFIC_SIGN_RECOGNITION_ENABLED, false),
            otherTrafficSignDisplayEnabled = preferences.getBoolean(KEY_OTHER_TRAFFIC_SIGN_DISPLAY_ENABLED, false),
            trafficSignRecognitionIndependentEnabled = preferences.getBoolean("youspeed.drive_recorder.tsr_independent_enabled", false),
            trafficSignFeedbackMode = runCatching { TrafficSignFeedbackMode.valueOf(preferences.getString("youspeed.drive_recorder.tsr_feedback_mode", "SOUND")!!) }.getOrDefault(TrafficSignFeedbackMode.SOUND),
            panoramaxTriggerMode = runCatching { PanoramaxCaptureTriggerMode.valueOf(preferences.getString("youspeed.panoramax.trigger_mode", "DISTANCE")!!) }.getOrDefault(PanoramaxCaptureTriggerMode.DISTANCE),
            panoramaxMinimumDistanceMeters = preferences.getFloat("youspeed.panoramax.minimum_distance", 25f).toDouble().coerceIn(3.0, 100.0),
            panoramaxMinimumIntervalSeconds = preferences.getFloat("youspeed.panoramax.minimum_interval", 5f).toDouble().coerceIn(1.0, 60.0),
            panoramaxUnlimitedStorage = preferences.getBoolean("youspeed.panoramax.unlimited_storage", false),
            panoramaxStorageLimitMB = preferences.getFloat("youspeed.panoramax.storage_limit_mb", 1000f).toDouble().coerceIn(100.0, 10000.0),
            panoramaxDeleteUploadedImages = preferences.getBoolean("youspeed.panoramax.delete_uploaded", false),
            panoramaxCaptureEnabled = panoramaxCaptureEnabled,
            dashcamRecordings = listDashcamRecordings(),
            trafficSignGeneration = trafficSignGeneration.get(),
            panoramaxBatches = panoramaxQueueStore.listBatches(),
            panoramaxCaptureCount = panoramaxQueueStore.listBatches().sumOf { it.items.size },
        ),
    )
        private set

    init {
        rootDir.mkdirs()
        ensureRuntimeDiagnosticsLogExists()
        runCatching {
            resetDrivingLogFiles(gpsLogFile = gpsLogFile(), matchLogFile = matchLogFile())
        }.onFailure { error ->
            appendRuntimeDiagnosticEvent(
                event = "driving_logs_startup_reset_failed",
                details = mapOf(
                    "pid" to Process.myPid(),
                    "error" to (error.message ?: error.javaClass.simpleName),
                ),
            )
        }
        installCrashObserverIfNeeded()
        appendRuntimeDiagnosticEvent(
            event = "session_init",
            details = mapOf(
                "pid" to Process.myPid(),
                "screenshotState" to launchScreenshotState?.rawValue,
            ),
        )
        preparePanoramaxStorage()
        if (launchScreenshotState != null) {
            configureForScreenshotMode(launchScreenshotState)
        } else {
            beginStartupDataLoadIfNeeded()
        }
    }

    fun bindHost(host: ConsumerHost) {
        this.host = host
        reconcileTrafficSignCamera()
    }

    fun dispose() {
        mainHandler.removeCallbacks(penaltyCountryExpiry)
        if (!isDisposed.compareAndSet(false, true)) {
            return
        }
        panoramaxUploader.close()
        stopDriving()
        runCatching { locationManager.removeUpdates(firstLocationListener) }
        mainHandler.removeCallbacks(speedCapturePromptFallbackRunnable)
        mainHandler.removeCallbacks(speedCaptureListeningStartRunnable)
        appendRuntimeDiagnosticEvent(
            event = "session_dispose",
            details = mapOf(
                "pid" to Process.myPid(),
                "driveStatus" to uiState.driveStatus,
            ),
        )
        closeLookupService(reason = "controller_dispose")
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
        if (isDisposed.get()) {
            return
        }
        if (!force && uiState.startupDataState == StartupDataState.READY) {
            return
        }
        pendingStartupData = null
        isStartupWaitingForSpeechModel = false
        updateState {
            copy(
                startupDataState = StartupDataState.LOADING,
                startupProgress = 0.08,
                startupDetail = ConsumerRuntimeText.STARTUP_PREPARING.text(),
                lastError = "",
                speedCaptureMode = SpeedCaptureModeState.IDLE,
                speedCaptureTranscript = "",
                localObservationStatus = "",
            )
        }
        submitBackgroundTask {
            try {
                bootstrapBundledSeedIfNeeded()
                refreshDownloadedBundleInventory()
                val observations = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(observations)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(observations)
                val active = bootstrapper.activeState()
                // Resolve migration before READY makes a user-initiated download possible.
                // Persist false as well: the first new download must not skip the later steps.
                if (!preferences.contains(OnboardingPolicy.COMPLETED_KEY)) {
                    preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY,
                        OnboardingPolicy.migrateCompletion(null, OnboardingPolicy.hasUsableMap(
                            active?.bundleVersion ?: "none", active?.dbPath?.let { File(it).isFile } == true,
                        ))).apply()
                }
                replaceLookupService(
                    active?.dbPath,
                    preferredCountryCode = active?.countryCode,
                    reason = "startup_prepare",
                )
                pendingStartupData = PendingStartupData(
                    startupDetail = when {
                        active?.bundleVersion == "seed" -> ConsumerRuntimeText.STARTUP_SEED_READY.text()
                        active?.dbPath?.isNotBlank() == true -> ConsumerRuntimeText.STARTUP_READY.text()
                        else -> ConsumerRuntimeText.STARTUP_NO_MAP.text()
                    },
                    activeBundleVersion = active?.bundleVersion ?: "none",
                    activeDBPath = active?.dbPath ?: "",

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
                        startupDetail = ConsumerRuntimeText.SPEECH_MODEL_PREPARING_SHORT.text(),
                        activeBundleVersion = active?.bundleVersion ?: "none",
                        activeDBPath = active?.dbPath ?: "",

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
                        startupDetail = ConsumerRuntimeText.STARTUP_FAILED.text(),
                        lastError = error.message ?: error.javaClass.simpleName,
                    )
                }
            }
        }
    }

    fun retryStartupDataPreparation() {
        beginStartupDataLoadIfNeeded(force = true)
    }

    fun hasUsableOnboardingMap(): Boolean = hasUsableOnboardingMap(uiState)

    private fun hasUsableOnboardingMap(state: ConsumerUiState): Boolean = OnboardingPolicy.hasUsableMap(
        state.activeBundleVersion,
        state.activeDBPath.takeIf { it.isNotBlank() }?.let { File(it).let { db -> db.isFile && db.length() > 0 } } == true,
    )

    fun shouldPresentOnboarding(): Boolean = uiState.appScreenshotState == null &&
        uiState.startupDataState == StartupDataState.READY &&
        OnboardingPolicy.requiresSetup(uiState.onboardingCompleted, hasUsableOnboardingMap())

    fun advanceOnboarding() {
        refreshOnboardingPermissions()
        if (!OnboardingPolicy.canAdvance(uiState.onboardingStep, hasUsableOnboardingMap(), uiState.preciseLocationGranted)) return
        if (uiState.onboardingStep == OnboardingPolicy.LAST_STEP) {
            preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true).apply()
            updateState { copy(onboardingCompleted = true, onboardingLocating = false) }
            firstLocationRequested = false
            runCatching { locationManager.removeUpdates(firstLocationListener) }
        } else {
            setOnboardingStep(uiState.onboardingStep + 1)
        }
    }

    fun goBackInOnboarding() = setOnboardingStep(uiState.onboardingStep - 1)

    private fun setOnboardingStep(step: Int) {
        val next = OnboardingPolicy.resumedStep(step, hasUsableOnboardingMap())
        preferences.edit().putInt(OnboardingPolicy.STEP_KEY, next).apply()
        updateState { copy(onboardingStep = next) }
    }

    fun canReplayOnboarding(): Boolean = !driveRecorderEnabled && !DriveRecorderPolicy.isActive(uiState.driveRecorderState)

    fun replayOnboarding(): Boolean {
        if (!canReplayOnboarding()) return false
        stopDriving()
        preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, false).putInt(OnboardingPolicy.STEP_KEY, 0).apply()
        updateState { copy(onboardingCompleted = false, onboardingStep = 0) }
        return true
    }

    fun pauseDrivingForOnboarding() {
        if (shouldPresentOnboarding() && isDriving) stopDriving()
    }

    fun refreshOnboardingPermissions() {
        val precise = hasFineLocationPermission()
        updateState { copy(preciseLocationGranted = precise,
            driveStatus = if (!isDriving && shouldPresentOnboarding()) "stopped" else driveStatus,
            lastError = if (precise && lastError == ConsumerRuntimeText.LOCATION_DENIED.text()) "" else lastError) }
    }

    fun requestOnboardingLocationPermission() {
        preferences.edit().putBoolean("youspeed.onboarding.location_requested", true).apply()
        updateState { copy(onboardingLocationRequested = true, preciseLocationGranted = hasFineLocationPermission()) }
        if (!hasFineLocationPermission()) host?.requestLocationPermission()
    }

    fun openOnboardingLocationSettings() { host?.openApplicationSettings() }

    fun selectOnboardingMap(id: String) {
        if (isSyncingNow() || uiState.bundleDownloadSections.flatMap { it.options }.none { it.id == id }) return
        firstLocationRequested = false
        locationSuggestionGeneration++
        runCatching { locationManager.removeUpdates(firstLocationListener) }
        preferences.edit().putString("youspeed.onboarding.selected_map", id).apply()
        updateState { copy(onboardingSelectedMapId = id, onboardingLocating = false, lastError = "") }
    }

    fun downloadOnboardingMap() {
        val selected = uiState.bundleDownloadSections.flatMap { it.options }
            .firstOrNull { it.id == uiState.onboardingSelectedMapId } ?: return
        downloadSelectedBundle(selected, firstLocationSetup = true)
    }

    fun useLocationForOnboarding() {
        if (isSyncingNow()) return
        firstLocationRegion = null
        firstLocationRequested = true
        preferences.edit().putBoolean("youspeed.onboarding.location_requested", true).apply()
        updateState { copy(onboardingLocationRequested = true, onboardingLocating = true,
            onboardingSuggestedMapId = null, firstLocationPackStatus = appContext.getString(R.string.onboarding_locating)) }
        if (hasLocationPermission()) requestFirstLocation() else host?.requestLocationPermission()
    }

    @SuppressLint("MissingPermission")
    private fun requestFirstLocation() {
        if (!firstLocationRequested || !hasLocationPermission() || isDisposed.get() || uiState.appScreenshotState != null) return
        val generation = ++locationSuggestionGeneration
        runCatching { locationManager.removeUpdates(firstLocationListener) }
        for (provider in locationManager.getProviders(true).filter { it != LocationManager.PASSIVE_PROVIDER }) {
            if (!firstLocationRequested) break
            runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull()?.let(::discoverPacks)
            if (!firstLocationRequested) break
            runCatching { locationManager.requestLocationUpdates(provider, 1000L, 0f, firstLocationListener, Looper.getMainLooper()) }
        }
        mainHandler.postDelayed({
            if (generation == locationSuggestionGeneration && firstLocationRequested && uiState.onboardingLocating) {
                firstLocationRequested = false
                runCatching { locationManager.removeUpdates(firstLocationListener) }
                updateState { copy(onboardingLocating = false,
                    firstLocationPackStatus = appContext.getString(R.string.onboarding_location_unavailable)) }
            }
        }, 30_000)
    }

    fun retryFirstLocationSetup() = useLocationForOnboarding()

    private fun discoverPacks(location: Location) {
        if (!isDriving && !firstLocationRequested) return
        val countryCode = penaltyCountrySelection.update(regionalPackCatalog, location.latitude, location.longitude,
            if (location.hasAccuracy()) location.accuracy.toDouble() else Double.NaN,
            location.time / 1000.0, clock.millis() / 1000.0)
        updateState { copy(activePenaltyRules = countryCode?.let(::loadPenaltyRules) ?: ActivePenaltyRules.unavailable()) }
        val expirySeconds = penaltyCountrySelection.expiryTimestampSeconds
        if (penaltyCountrySelection.lastUpdateAcceptedNewFix || expirySeconds == null) mainHandler.removeCallbacks(penaltyCountryExpiry)
        if (penaltyCountrySelection.lastUpdateAcceptedNewFix && expirySeconds != null) {
            val remainingValidityMs = (expirySeconds * 1000.0 - clock.millis()).toLong().coerceAtLeast(1L)
            mainHandler.postDelayed(penaltyCountryExpiry, remainingValidityMs)
        }
        if (!location.hasAccuracy() || !FirstLocationPackPolicy.acceptsFix(location.latitude, location.longitude,
                location.accuracy.toDouble(), location.time / 1000.0, clock.millis() / 1000.0)) return
        val catalog = regionalPackCatalog ?: run {
            updateState { copy(firstLocationPackStatus = ConsumerRuntimeText.REGION_CATALOG_MISSING.text()) }
            return
        }
        val matches = catalog.matches(location.longitude, location.latitude)
        val country = countryPackSelection.update(matches.map { it.country }.toSet(), location.time / 1000.0)
        val state = countryPackRegistry?.decision(country, "android", BuildConfig.VERSION_NAME.removeSuffix("-debug"),
            android.os.Build.VERSION.SDK_INT.toString(), now = clock.millis() / 1000)?.state
        val prefix = country?.let { ConsumerRuntimeText.MODEL_COUNTRY_PREFIX.text(it) } ?: ConsumerRuntimeText.MODEL_PREFIX.text()
        updateState { copy(countryModelPackStatus = prefix + if (state == "country_unresolved")
            ConsumerRuntimeText.MODEL_COUNTRY_UNCLEAR.text() else ConsumerRuntimeText.MODEL_DOWNLOAD_UNAVAILABLE.text()) }
        if (!firstLocationRequested) return
        firstLocationRegion = matches.firstOrNull()
        val option = firstLocationRegion?.let { region ->
            uiState.bundleDownloadSections.flatMap { it.options }.firstOrNull { it.id == region.id }
        }
        firstLocationRequested = false
        runCatching { locationManager.removeUpdates(firstLocationListener) }
        if (option == null) {
            updateState { copy(onboardingLocating = false,
                firstLocationPackStatus = appContext.getString(R.string.onboarding_location_unavailable)) }
        } else {
            preferences.edit().putString("youspeed.onboarding.selected_map", option.id).apply()
            updateState { copy(onboardingLocating = false, onboardingSuggestedMapId = option.id,
                onboardingSelectedMapId = option.id,
                firstLocationPackStatus = appContext.getString(R.string.onboarding_suggested_map, option.displayName)) }
        }
    }

    internal fun isTrafficSignRecognitionRuntimeEnabled(): Boolean = !shouldPresentOnboarding() && DriveRecorderPolicy.shouldRunRecognition(
        uiState.trafficSignRecognitionEnabled, uiState.trafficSignRecognitionIndependentEnabled,
        driveRecorderEnabled, isDriving, applicationActive,
    )

    internal fun isDriveRecorderSessionActive(): Boolean = driveRecorderEnabled && isDriving && applicationActive
    internal fun isDashcamRecordingEnabled(): Boolean = isDriveRecorderSessionActive() && uiState.dashcamRecordingEnabled
    internal fun isPanoramaxCaptureEnabled(): Boolean = panoramaxCaptureEnabled && isDriveRecorderSessionActive()

    fun canProcessPanoramaxUploads(): Boolean = !driveRecorderEnabled && DriveRecorderPolicy.canProcessPanoramaxUploads(uiState.driveRecorderState) &&
        !uiState.panoramaxMaintenanceInProgress

    fun setDriveRecorderPreviewSurfaceProvider(provider: Preview.SurfaceProvider?) {
        host?.setDriveRecorderPreviewSurfaceProvider(provider)
    }

    fun setApplicationActive(active: Boolean) {
        if (active) {
            refreshOnboardingPermissions()
            if (uiState.onboardingLocating) requestFirstLocation()
        }
        if (applicationActive == active) return
        applicationActive = active
        invalidateTrafficSignGeneration(clearAssertion = true, reason = "application_lifecycle", permitWrites = active && isTrafficSignRecognitionRuntimeEnabled())
        if (!active) {
            if (driveRecorderEnabled) stopDriveRecorder()
            if (uiState.onboardingLocating) {
                locationSuggestionGeneration++
                runCatching { locationManager.removeUpdates(firstLocationListener) }
            }
        }
        reconcileTrafficSignCamera()
    }

    internal fun nextDashcamRecordingFile(): File {
        dashcamDirectory.mkdirs()
        return File(dashcamDirectory, "dashcam-${clock.millis()}-${UUID.randomUUID()}.mp4").also {
            activeDashcamPath = it.absolutePath
            latestDashcamEventPath = it.absolutePath
        }
    }

    private fun listDashcamRecordings(): List<DashcamRecording> =
        dashcamDirectory.listFiles { file -> file.isFile && file.extension.equals("mp4", ignoreCase = true) }
            .orEmpty()
            .sortedByDescending { it.lastModified() }
            .map { file -> DashcamRecording(file.absolutePath, Instant.ofEpochMilli(file.lastModified()), file.length()) }

    fun toggleDriveRecorder() {
        if (shouldPresentOnboarding()) return
        if (uiState.appScreenshotState != null || uiState.startupDataState != StartupDataState.READY ||
            uiState.driveRecorderState == DriveRecorderState.STOPPING) return
        if (driveRecorderEnabled) { stopDriveRecorder(); return }
        if (panoramaxCaptureEnabled && uiState.panoramaxMaintenanceInProgress) return
        stopPanoramaxUploads()
        latestDashcamEventPath = null
        driveRecorderEnabled = true
        feedbackGate.reset()
        updateState { copy(driveRecorderState = DriveRecorderState.PREPARING, dashcamRecordingEnabled = true,
            driveRecorderStartedAt = clock.instant(), trafficSignRecognitionUnavailable = false) }
        if (!isDriving) startDriving() else reconcileTrafficSignCamera()
        ensurePanoramaxCaptureSessionIfCameraActive()
    }

    private fun stopDriveRecorder() {
        driveRecorderEnabled = false
        updateState { copy(driveRecorderState = DriveRecorderState.STOPPING, dashcamRecordingEnabled = false,
            driveRecorderPanoramaxActive = false) }
        endPanoramaxCaptureSession()
        reconcileTrafficSignCamera()
        if (!uiState.driveRecorderDashcamActive && !uiState.driveRecorderDashcamTransitioning) {
            updateState { copy(driveRecorderState = DriveRecorderState.DISABLED, driveRecorderStartedAt = null) }
        }
    }

    fun toggleDriveRecorderDashcam() {
        if (uiState.driveRecorderState != DriveRecorderState.RECORDING || uiState.driveRecorderDashcamTransitioning) return
        updateState { copy(dashcamRecordingEnabled = !dashcamRecordingEnabled, driveRecorderDashcamTransitioning = true) }
        reconcileTrafficSignCamera()
    }

    fun toggleDriveRecorderTrafficSignRecognition() {
        if (uiState.driveRecorderState != DriveRecorderState.RECORDING) return
        setTrafficSignRecognitionEnabled(!uiState.trafficSignRecognitionEnabled)
    }

    fun setPanoramaxCaptureEnabled(enabled: Boolean) {
        if (panoramaxCaptureEnabled == enabled || DriveRecorderPolicy.isActive(uiState.driveRecorderState)) return
        panoramaxCaptureEnabled = enabled
        preferences.edit().putBoolean(KEY_PANORAMAX_CAPTURE_ENABLED, enabled).apply()
        updateState { copy(panoramaxCaptureEnabled = enabled) }
    }

    internal fun currentPanoramaxLocationSample(): PanoramaxLocationSample? {
        val location = latestCaptureLocation?.let(::Location) ?: return null
        if (!location.hasAccuracy() || location.provider == LocationManager.NETWORK_PROVIDER) return null
        return PanoramaxLocationSample(
            latitude = location.latitude, longitude = location.longitude,
            capturedAt = Instant.ofEpochMilli(location.time), accuracyMeters = location.accuracy.toDouble(),
            altitudeMeters = location.altitude.takeIf { location.hasAltitude() && it.isFinite() },
            headingDegrees = location.bearing.toDouble().takeIf { location.hasBearing() && it.isFinite() && it >= 0.0 },
        )
    }

    fun togglePanoramaxCapture() {
        setPanoramaxCaptureEnabled(!panoramaxCaptureEnabled)
    }

    private fun beginPanoramaxCaptureSession() {
        if (panoramaxCaptureSessionId != null || !panoramaxCaptureEnabled) return
        val sessionId = UUID.randomUUID().toString().lowercase(Locale.US)
        runCatching { panoramaxQueueStore.createBatch(sessionId) }
            .onSuccess {
                panoramaxCaptureSessionId = sessionId
                panoramaxLastCaptureSample = null
                panoramaxCaptureInFlight = false
            }
            .onFailure { error ->
                updateState { copy(lastError = error.message ?: error.javaClass.simpleName) }
            }
    }

    private fun endPanoramaxCaptureSession() {
        synchronized(captureLock) {
            panoramaxCaptureSessionId = null
            panoramaxLastCaptureSample = null
            panoramaxCaptureInFlight = false
            pendingPhoto = null
        }
        panoramaxQueueStore.listBatches().filter { it.state == PanoramaxBatchState.CAPTURING }.forEach { batch ->
            runCatching { panoramaxQueueStore.transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW) }
        }
        submitBackgroundTask { enforcePanoramaxStorageLimit(); refreshPanoramaxBatches() }
    }

    fun refreshPanoramaxBatches() {
        updateState {
            val batches = panoramaxQueueStore.listBatches()
            copy(panoramaxBatches = batches, panoramaxCaptureCount = batches.sumOf { it.items.size })
        }
    }

    /**
     * The camera runtime is shared with independent TSR. If it was already active when the
     * recorder was enabled, there is no new ACTIVE callback to create the Panoramax batch.
     */
    private fun ensurePanoramaxCaptureSessionIfCameraActive() {
        if (DriveRecorderPolicy.shouldEnsurePanoramaxCaptureSession(
                driveRecorderEnabled = driveRecorderEnabled,
                panoramaxEnabled = panoramaxCaptureEnabled,
                driving = isDriving,
                applicationActive = applicationActive,
                cameraState = uiState.trafficSignCameraRuntimeState,
            )) {
            beginPanoramaxCaptureSession()
        }
    }

    /** Re-applies the movie consumer after the shared camera reports ACTIVE. */
    private fun ensureDashcamRecordingIfCameraActive(cameraState: TrafficSignCameraRuntimeState = uiState.trafficSignCameraRuntimeState) {
        if (driveRecorderEnabled && uiState.dashcamRecordingEnabled && isDriving && applicationActive &&
            cameraState == TrafficSignCameraRuntimeState.ACTIVE
        ) {
            host?.startTrafficSignCamera()
        }
    }

    fun deletePanoramaxItem(batchId: String, itemId: String) = deletePanoramaxItems(mapOf(batchId to setOf(itemId)))

    fun setPanoramaxItemIncluded(batchId: String, itemId: String, included: Boolean) {
        if (!canProcessPanoramaxUploads()) return
        runCatching {
            val batch = panoramaxQueueStore.getBatch(batchId) ?: return
            if (!PanoramaxQueuePolicy.canEditSelection(batch.state)) return
            panoramaxQueueStore.updateItem(
                batchId,
                itemId,
                if (included) PanoramaxItemState.INCLUDED else PanoramaxItemState.EXCLUDED,
            )
        }.onSuccess {
            updateState {
                val batches = panoramaxQueueStore.listBatches()
                copy(panoramaxBatches = batches, panoramaxCaptureCount = batches.sumOf { it.items.size })
            }
        }
            .onFailure { error -> updateState { copy(lastError = error.message ?: error.javaClass.simpleName) } }
    }

    internal fun onPanoramaxPhotoCaptured(path: String, @Suppress("UNUSED_PARAMETER") sample: PanoramaxLocationSample, requestId: String) {
        if (!submitBackgroundTask {
            val request = synchronized(captureLock) { pendingPhoto?.takeIf { it.requestId == requestId && it.sessionId == panoramaxCaptureSessionId } }
            if (request == null) { File(path).delete(); return@submitBackgroundTask }
            var thumbnailFile: File? = null
            try {
                val original = File(path)
                val dimensions = PanoramaxJpegMetadata.pixelDimensions(original) ?: error("Could not decode Panoramax photo")
                val drafts = synchronized(captureLock) {
                    (request.drafts + latestAnnotationDrafts).distinctBy { it.sourceEventId }
                }
                val annotations = drafts.mapNotNull { it.projected(dimensions.first, dimensions.second, request.sample.capturedAt) }
                PanoramaxJpegMetadata.write(original, request.sample, annotations)
                thumbnailFile = File.createTempFile("panoramax-thumb-", ".jpg", appContext.cacheDir)
                PanoramaxJpegMetadata.createThumbnail(original, requireNotNull(thumbnailFile))
                val metadata = PanoramaxCaptureMetadata(
                    captureId = request.requestId, captureSessionId = request.sessionId,
                    capturedAt = request.sample.capturedAt, location = request.sample,
                    sha256 = PanoramaxQueueStore.sha256(original), byteSize = original.length(),
                    software = "YouSpeed Android ${BuildConfig.VERSION_NAME}",
                    imageWidthPixels = dimensions.first, imageHeightPixels = dimensions.second,
                    trafficSignAnnotations = annotations.takeIf { it.isNotEmpty() },
                )
                synchronized(captureLock) {
                    if (pendingPhoto?.requestId != requestId || panoramaxCaptureSessionId != request.sessionId) return@synchronized
                    val batch = panoramaxQueueStore.listBatches().firstOrNull {
                        it.state == PanoramaxBatchState.CAPTURING && it.captureSessionId == request.sessionId
                    } ?: return@synchronized
                    panoramaxQueueStore.addJpeg(batch.batchId, original, requireNotNull(thumbnailFile), metadata)
                    panoramaxLastCaptureSample = request.sample
                    val attachedIds = annotations.map { it.sourceEventId }.toSet()
                    latestAnnotationDrafts = latestAnnotationDrafts.filterNot { it.sourceEventId in attachedIds }
                    updateState { copy(panoramaxLastCaptureDetail = ConsumerUiStrings.text("Photo saved", "Foto gespeichert", "Photo enregistrée", "Foto opgeslagen")) }
                }
                enforcePanoramaxStorageLimit()
            } catch (error: Exception) {
                updateState { copy(panoramaxLastCaptureDetail = error.message ?: "Photo could not be saved") }
            } finally {
                File(path).delete()
                thumbnailFile?.delete()
                synchronized(captureLock) { if (pendingPhoto?.requestId == requestId) { pendingPhoto = null; panoramaxCaptureInFlight = false } }
                refreshPanoramaxBatches()
            }
        }) File(path).delete()
    }

    internal fun onPanoramaxPhotoCaptureFailed(detail: String, requestId: String) {
        val wasPending = synchronized(captureLock) {
            if (pendingPhoto?.requestId != requestId) false else {
                pendingPhoto = null; panoramaxCaptureInFlight = false; true
            }
        }
        if (wasPending) postState { copy(panoramaxLastCaptureDetail = detail) }
    }

    private fun maybeCapturePanoramaxPhoto() {
        if (!isPanoramaxCaptureEnabled() || uiState.driveRecorderState != DriveRecorderState.RECORDING) return
        val sample = currentPanoramaxLocationSample() ?: return
        val request = synchronized(captureLock) {
            val sessionId = panoramaxCaptureSessionId ?: return
            if (panoramaxCaptureInFlight || !PanoramaxCapturePolicy.shouldCapture(panoramaxLastCaptureSample, sample,
                    now = clock.instant(), config = PanoramaxCadenceConfig(distanceMeters = uiState.panoramaxMinimumDistanceMeters,
                        fallbackInterval = Duration.ofMillis((uiState.panoramaxMinimumIntervalSeconds * 1000).toLong()),
                        triggerMode = uiState.panoramaxTriggerMode))) return
            PendingPhoto(UUID.randomUUID().toString(), sessionId, sample.copy(capturedAt = clock.instant()), latestAnnotationDrafts.toList()).also {
                pendingPhoto = it; panoramaxCaptureInFlight = true
            }
        }
        val currentHost = host
        if (currentHost == null) onPanoramaxPhotoCaptureFailed("Camera unavailable", request.requestId)
        else mainHandler.post { currentHost.capturePanoramaxPhoto(request.requestId) }
    }

    private fun preparePanoramaxStorage() {
        submitBackgroundTask {
            runCatching {
                val failures = panoramaxQueueStore.performStartupMaintenanceNow().failedRelativePaths.toMutableList()
                panoramaxQueueStore.repairMissingThumbnails()
                if (uiState.panoramaxDeleteUploadedImages) failures += panoramaxQueueStore.deleteUploadedItemsInCompletedBatches().failedRelativePaths
                if (!uiState.panoramaxUnlimitedStorage) failures += panoramaxQueueStore.enforceStorageLimit((uiState.panoramaxStorageLimitMB * 1_000_000).toLong()).failedRelativePaths
                cleanupDashcamRecordings()
                postState { copy(panoramaxMaintenanceIssue = failures.takeIf { it.isNotEmpty() }?.joinToString(),
                    panoramaxAccountStatus = panoramaxAccount.state.status,
                    panoramaxAccountConnected = panoramaxAccount.state.isConnected,
                    panoramaxAccountHasToken = panoramaxAccount.state.hasToken,
                    panoramaxAccountBusy = panoramaxAccount.state.isBusy, panoramaxMaintenanceInProgress = false) }
            }.onFailure { error -> postState { copy(panoramaxMaintenanceIssue = error.message, panoramaxMaintenanceInProgress = false) } }
            refreshPanoramaxBatches()
        }
    }

    private fun enforcePanoramaxStorageLimit() {
        if (uiState.panoramaxUnlimitedStorage) return
        val report = panoramaxQueueStore.enforceStorageLimit((uiState.panoramaxStorageLimitMB * 1_000_000).toLong())
        if (report.hasFailures) postState { copy(panoramaxMaintenanceIssue = report.failedRelativePaths.joinToString()) }
    }

    fun panoramaxOriginalFile(item: PanoramaxItemRecord): File = panoramaxQueueStore.originalFile(item)
    fun panoramaxThumbnailFile(item: PanoramaxItemRecord): File = panoramaxQueueStore.thumbnailFile(item)

    fun setPanoramaxItemFavorite(batchId: String, itemId: String, favorite: Boolean) {
        submitBackgroundTask {
            runCatching { panoramaxQueueStore.updateItemFavorite(batchId, itemId, favorite) }
                .onFailure { error -> postState { copy(panoramaxMaintenanceIssue = error.message) } }
            refreshPanoramaxBatches()
        }
    }

    fun deletePanoramaxItems(selections: Map<String, Set<String>>) {
        if (!canProcessPanoramaxUploads()) return
        selections.keys.forEach(panoramaxUploader::stopBatch)
        submitBackgroundTask {
            selections.forEach { (batchId, itemIds) ->
                runCatching { panoramaxQueueStore.deleteItems(batchId, itemIds) }
                    .onSuccess { if (it.hasFailures) postState { copy(panoramaxMaintenanceIssue = it.failedRelativePaths.joinToString()) } }
                    .onFailure { error -> postState { copy(panoramaxMaintenanceIssue = error.message) } }
            }
            refreshPanoramaxBatches()
        }
    }

    fun connectPanoramaxAccount() { submitBackgroundTask { panoramaxAccount.connect()?.let { url -> mainHandler.post { host?.openExternalUrl(url) } } } }
    fun validatePanoramaxAccount() { submitBackgroundTask { panoramaxAccount.validateConnection() } }
    fun disconnectPanoramaxAccount() { stopPanoramaxUploads(); submitBackgroundTask { panoramaxAccount.disconnect() } }
    fun uploadPanoramaxSelections(selections: Map<String, Set<String>>) { if (canProcessPanoramaxUploads()) panoramaxUploader.uploadSelections(selections) }
    fun resumePanoramaxUpload(batchId: String) { if (canProcessPanoramaxUploads()) panoramaxUploader.uploadBatch(batchId) }
    fun stopPanoramaxUploads() { panoramaxUploader.stopAll() }

    private fun refreshPanoramaxUploadState() {
        val active = panoramaxUploader.activeBatchIds
        val status = panoramaxUploader.statusByBatch
        val progress = panoramaxUploader.progressByBatch
        postState { copy(panoramaxActiveUploadBatchIds = active, panoramaxUploadStatusByBatch = status,
            panoramaxUploadProgressByBatch = progress, panoramaxAccountConnected = panoramaxAccount.state.isConnected,
            panoramaxAccountHasToken = panoramaxAccount.state.hasToken, panoramaxAccountBusy = panoramaxAccount.state.isBusy,
            panoramaxAccountStatus = panoramaxAccount.state.status) }
        refreshPanoramaxBatches()
    }

    fun setPanoramaxTriggerMode(value: PanoramaxCaptureTriggerMode) {
        preferences.edit().putString("youspeed.panoramax.trigger_mode", value.name).apply()
        updateState { copy(panoramaxTriggerMode = value) }
    }
    fun setPanoramaxMinimumDistanceMeters(value: Double) {
        val clamped = value.coerceIn(3.0, 100.0)
        preferences.edit().putFloat("youspeed.panoramax.minimum_distance", clamped.toFloat()).apply()
        updateState { copy(panoramaxMinimumDistanceMeters = clamped) }
    }
    fun setPanoramaxMinimumIntervalSeconds(value: Double) {
        val clamped = value.coerceIn(1.0, 60.0)
        preferences.edit().putFloat("youspeed.panoramax.minimum_interval", clamped.toFloat()).apply()
        updateState { copy(panoramaxMinimumIntervalSeconds = clamped) }
    }
    fun setPanoramaxUnlimitedStorage(value: Boolean) {
        preferences.edit().putBoolean("youspeed.panoramax.unlimited_storage", value).apply()
        updateState { copy(panoramaxUnlimitedStorage = value) }
        submitBackgroundTask { enforcePanoramaxStorageLimit(); refreshPanoramaxBatches() }
    }
    fun setPanoramaxStorageLimitMB(value: Double) {
        val clamped = value.coerceIn(100.0, 10000.0)
        preferences.edit().putFloat("youspeed.panoramax.storage_limit_mb", clamped.toFloat()).apply()
        updateState { copy(panoramaxStorageLimitMB = clamped) }
        submitBackgroundTask { enforcePanoramaxStorageLimit(); refreshPanoramaxBatches() }
    }
    fun setPanoramaxDeleteUploadedImages(value: Boolean) {
        preferences.edit().putBoolean("youspeed.panoramax.delete_uploaded", value).apply()
        updateState { copy(panoramaxDeleteUploadedImages = value) }
        if (value) submitBackgroundTask {
            runCatching { panoramaxQueueStore.deleteUploadedItemsInCompletedBatches() }
                .onSuccess { if (it.hasFailures) postState { copy(panoramaxMaintenanceIssue = it.failedRelativePaths.joinToString()) } }
                .onFailure { error -> postState { copy(panoramaxMaintenanceIssue = error.message) } }
            refreshPanoramaxBatches()
        }
    }

    fun setTrafficSignRecognitionIndependentEnabled(value: Boolean) {
        preferences.edit().putBoolean("youspeed.drive_recorder.tsr_independent_enabled", value).apply()
        updateState { copy(trafficSignRecognitionIndependentEnabled = value, trafficSignRecognitionUnavailable = false) }
        invalidateTrafficSignGeneration(true, "independent_recognition_changed", isTrafficSignRecognitionRuntimeEnabled())
        reconcileTrafficSignCamera()
    }
    fun setTrafficSignFeedbackMode(value: TrafficSignFeedbackMode) {
        preferences.edit().putString("youspeed.drive_recorder.tsr_feedback_mode", value.name).apply()
        updateState { copy(trafficSignFeedbackMode = value) }
        feedbackGate.reset()
    }

    fun onTrafficSignRecognitionEvent(event: TrafficSignRecognitionEvent, generation: Long) {
        mainHandler.post {
            val currentGeneration = trafficSignGeneration.get()
            val generationMismatch = generation != currentGeneration
            val sessionMismatch = event.driveSessionId != trafficSignDriveSessionId
            if (generationMismatch || sessionMismatch) {
                noteTrafficSignDebugMismatch(
                    reason = "recognition_event_rejected",
                    details = mapOf(
                        "eventGeneration" to generation,
                        "currentGeneration" to currentGeneration,
                        "eventSessionId" to event.driveSessionId,
                        "currentSessionId" to trafficSignDriveSessionId,
                    ),
                )
                return@post
            }
            if (!isTrafficSignRecognitionRuntimeEnabled()) return@post
            PanoramaxTrafficSignAnnotationDraft.from(event)?.let { draft ->
                val captureSession = synchronized(captureLock) {
                    latestAnnotationDrafts = (latestAnnotationDrafts.filter { Duration.between(it.frameTimestampUtc, event.frameTimestampUtc).abs().toMillis() <= 5_000 &&
                        it.physicalSignTrackId != draft.physicalSignTrackId } + draft)
                    panoramaxCaptureSessionId
                }
                if (captureSession != null) submitBackgroundTask {
                    runCatching {
                        synchronized(captureLock) {
                            if (generation != trafficSignGeneration.get() || captureSession != panoramaxCaptureSessionId || panoramaxCaptureInFlight) return@synchronized
                            val batch = panoramaxQueueStore.listBatches().firstOrNull {
                                it.state == PanoramaxBatchState.CAPTURING && it.captureSessionId == captureSession
                            } ?: return@synchronized
                            if (panoramaxQueueStore.attachTrafficSignAnnotation(batch.batchId, draft) != null) {
                                latestAnnotationDrafts = latestAnnotationDrafts.filterNot { it.sourceEventId == draft.sourceEventId }
                            }
                        }
                    }.onFailure { error -> postState { copy(panoramaxMaintenanceIssue = error.message) } }
                }
            }
            updateState { copy(trafficSignLastEvent = event) }
        }
    }

    internal fun onTrafficSignStartupMeasured(result: AndroidTrafficSignStartupResult) {
        appendRuntimeDiagnosticEvent(
            event = "traffic_sign_startup_reference",
            details = mapOf(
                "referenceClassId" to AndroidTrafficSignStartupProbe.REFERENCE_CLASS_ID,
                "referenceSha256" to AndroidTrafficSignStartupProbe.REFERENCE_SHA256,
                "referenceVerified" to true,
                "warmInferenceTimesMs" to result.warmInferenceTimesMs,
                "measuredWarmMaxMs" to result.timingProfile.measuredWarmMaxMs,
                "confirmationWindowMs" to result.timingProfile.confirmationWindowMs,
                "executionBackend" to result.executionBackend,
                "accelerationFallbackReason" to result.accelerationFallbackReason,
            ),
        )
    }

    /** Writes bounded stage-level evidence for the Android camera lane. */
    fun onTrafficSignInferenceDiagnostics(output: TrafficSignOrchestrationOutput) {
        val diagnostics = output.inferenceDiagnostics ?: return
        if (output.contextIsCurrent && output.event.driveSessionId == trafficSignDriveSessionId) {
            updateState { copy(trafficSignDebugGenerationSessionContextMismatch = false) }
        }
        val now = clock.millis()
        synchronized(trafficSignStateLock) {
            if (now - lastTrafficSignInferenceLogAtMs < TRAFFIC_SIGN_INFERENCE_LOG_INTERVAL_MS) return
            lastTrafficSignInferenceLogAtMs = now
        }
        appendRuntimeDiagnosticEvent(
            event = "traffic_sign_inference",
            details = buildMap {
                put("frameId", output.event.frameId)
                put("source", output.event.source.wireValue)
                put("inferenceMs", diagnostics.inferenceMs)
                put("confirmationWindowMs", output.effectiveConfirmationWindowMs)
                put("executionBackend", diagnostics.executionBackend)
                put("accelerationFallbackReason", diagnostics.accelerationFallbackReason)
                put("detectorPreprocessingMs", diagnostics.detectorPreprocessingMs)
                put("detectorInferenceMs", diagnostics.detectorInferenceMs)
                put("classifierInferenceMs", diagnostics.classifierInferenceMs)
                put("detectorProposalCount", diagnostics.detectorProposalCount)
                put("detectorTopScore", diagnostics.detectorTopScore)
                put("classifierInvocationCount", diagnostics.classifierInvocationCount)
                put("classifiedDetectionCount", diagnostics.classifiedDetectionCount)
                put("classifierTopScore", diagnostics.classifierTopScore)
                put("primaryClassId", diagnostics.primaryClassId)
                put("primaryScore", diagnostics.primaryScore)
                put("detectorRawSignTopScore", diagnostics.detectorRawSignTopScore)
                put("detectorRawGlobalTopScore", diagnostics.detectorRawGlobalTopScore)
                put("detectorRawSignScoresAboveThreshold", diagnostics.detectorRawSignScoresAboveThreshold)
                put("sourceWidthPixels", diagnostics.sourceWidthPixels)
                put("sourceHeightPixels", diagnostics.sourceHeightPixels)
                put("sourceLumaMean", diagnostics.sourceLumaMean)
                put("recognitionState", output.event.state.wireValue)
                put("contextIsCurrent", output.contextIsCurrent)
                put("contextGeneration", output.contextGeneration)
                put("wayId", output.event.roadContext?.wayId)
                put("matchedWayStable", output.event.roadContext?.matchedWayStable)
                put("hasVerifiedBundle", output.event.roadContext?.hasVerifiedBundle)
                put("displayAccepted", output.displayObservation != null)
                put("passageFinalized", output.passageEvent != null)
                put("backendFailureReason", output.backendFailureReason)
                put("terminalBackendFailure", output.terminalBackendFailure)
            },
        )
    }

    fun onTrafficSignRecognitionUnavailable(detail: String, generation: Long) {
        mainHandler.post {
            val currentGeneration = trafficSignGeneration.get()
            if (generation != currentGeneration) {
                noteTrafficSignDebugMismatch(
                    reason = "runtime_unavailable_rejected",
                    details = mapOf(
                        "eventGeneration" to generation,
                        "currentGeneration" to currentGeneration,
                        "detail" to detail,
                    ),
                )
                return@post
            }
            if (!isTrafficSignRecognitionRuntimeEnabled()) return@post
            invalidateTrafficSignGeneration(true, "recognition_unavailable", false)
            updateState {
                copy(
                    trafficSignRecognitionUnavailable = true,
                    trafficSignCameraRuntimeDetail = detail,
                    trafficSignDebugRuntimeUnhealthy = true,
                )
            }
            if (!driveRecorderEnabled) host?.stopTrafficSignCamera()
        }
    }

    fun onTrafficSignRecognitionContextMismatch(generation: Long) {
        mainHandler.post {
            noteTrafficSignDebugMismatch(
                reason = "orchestrator_context_rejected",
                details = mapOf(
                    "eventGeneration" to generation,
                    "currentGeneration" to trafficSignGeneration.get(),
                    "currentWayId" to latestTrafficSignContext?.wayId,
                ),
            )
        }
    }

    fun onDashcamRecordingStateChanged(active: Boolean, transitioning: Boolean = false, path: String) {
        postState { if (path != latestDashcamEventPath) this else copy(driveRecorderDashcamActive = active, driveRecorderDashcamTransitioning = transitioning,
            dashcamRecordingEnabled = if (!active && !transitioning) false else dashcamRecordingEnabled,
            driveRecorderState = if (!driveRecorderEnabled && !active && !transitioning) DriveRecorderState.DISABLED else driveRecorderState,
            driveRecorderStartedAt = if (!driveRecorderEnabled && !active && !transitioning) null else driveRecorderStartedAt) }
    }

    fun onDashcamCameraReleased() {
        postState {
            if (driveRecorderEnabled) this else copy(driveRecorderState = DriveRecorderState.DISABLED,
                driveRecorderDashcamActive = false, driveRecorderDashcamTransitioning = false,
                dashcamRecordingEnabled = false, driveRecorderStartedAt = null)
        }
    }

    fun deleteDashcamRecordings(paths: Set<String>) {
        if (DriveRecorderPolicy.isActive(uiState.driveRecorderState)) return
        submitBackgroundTask {
            val allowed = listDashcamRecordings().map { it.path }.toSet()
            val failures = paths.intersect(allowed).filter { it != activeDashcamPath && !File(it).delete() }
            postState { copy(dashcamRecordings = listDashcamRecordings(), lastError = if (failures.isEmpty()) "" else "Some videos could not be deleted") }
        }
    }

    private fun cleanupDashcamRecordings() {
        var size = listDashcamRecordings().sumOf { it.bytes }
        listDashcamRecordings().asReversed().filter { it.path != activeDashcamPath }.forEach { recording ->
            if (size > DriveRecorderPolicy.MOVIE_LIBRARY_LIMIT_BYTES && File(recording.path).delete()) size -= recording.bytes
        }
        postState { copy(dashcamRecordings = listDashcamRecordings()) }
    }

    fun startDriving() {
        if (shouldPresentOnboarding()) return
        if (uiState.appScreenshotState != null || uiState.startupDataState != StartupDataState.READY) {
            return
        }
        isDriving = true
        trafficSignDriveSessionId = UUID.randomUUID().toString().lowercase(Locale.US)
        invalidateTrafficSignGeneration(
            clearAssertion = true,
            reason = "drive_started",
            permitWrites = uiState.trafficSignRecognitionEnabled,
        )
        reconcileTrafficSignCamera()
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
        latestCaptureLocation = null
        driveRecorderEnabled = false
        endPanoramaxCaptureSession()
        isDriving = false
        host?.stopTrafficSignCamera()
        lookupToken.advance()
        invalidateTrafficSignGeneration(clearAssertion = true, reason = "drive_stopped", permitWrites = false)
        trafficSignDriveSessionId = null
        stopLocationUpdates()
        resetDerivedSpeedTracking()
        wayMatchTracker.reset()
        cancelSpeedCapture(reason = null)
        textToSpeech?.stop()
        lastAnnouncedSpeechText = null
        wasDrivingBanWarningActive = false
        lastAudioFeedbackAtMs = 0L
        lastDrivingBanWarningAtMs = 0L
        if (uiState.appScreenshotState == null) {
            updateState {
                copy(
                    driveStatus = "stopped",
                    currentSpeedKmh = 0.0,
                    trafficSignCameraRuntimeState = TrafficSignCameraRuntimeState.DISABLED,
                    trafficSignCameraRuntimeDetail = ConsumerRuntimeText.CAMERA_DISABLED.text(),
                    driveRecorderState = DriveRecorderState.DISABLED,
                    panoramaxCaptureEnabled = panoramaxCaptureEnabled,
                    panoramaxBatches = panoramaxQueueStore.listBatches(),
                )
            }
        }
    }

    fun onLocationPermissionResult(granted: Boolean) {
        refreshOnboardingPermissions()
        if (!granted) {
            updateState {
                copy(
                    onboardingLocating = false,
                    firstLocationPackStatus = appContext.getString(R.string.onboarding_location_unavailable),
                    driveStatus = if (isDriving) "location_denied" else "stopped",
                    lastError = ConsumerRuntimeText.LOCATION_DENIED.text(),
                )
            }
            return
        }
        if (isDriving) {
            startLocationUpdates()
        } else {
            requestFirstLocation()
        }
    }

    fun beginSpeedCapture() {
        if (shouldPresentOnboarding()) return
        if (uiState.startupDataState != StartupDataState.READY || uiState.speedCaptureMode != SpeedCaptureModeState.IDLE) {
            return
        }
        if (uiState.appScreenshotState != null) {
            host?.showTransientMessage(ConsumerRuntimeText.SCREENSHOT_SPEECH_DISABLED.text())
            return
        }
        if (uiState.germanSpeechModelState != GermanSpeechModelState.READY) {
            host?.showTransientMessage(
                uiState.germanSpeechModelStatus.ifBlank {
                    ConsumerRuntimeText.SPEECH_MODEL_NOT_READY.text()
                },
            )
            return
        }
        if (!hasMicrophonePermission()) {
            updateState {
                copy(
                    speedCaptureMode = SpeedCaptureModeState.REQUESTING_MIC_PERMISSION,
                    speedCaptureTranscript = "",
                    localObservationStatus = ConsumerRuntimeText.MIC_PERMISSION_REQUESTED.text(),
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
            host?.showTransientMessage(ConsumerRuntimeText.MIC_PERMISSION_DENIED.text())
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

    fun setTrafficSignRecognitionEnabled(enabled: Boolean) {
        if (uiState.trafficSignRecognitionEnabled == enabled) return
        feedbackGate.reset()
        preferences.edit().putBoolean(KEY_TRAFFIC_SIGN_RECOGNITION_ENABLED, enabled).apply()
        invalidateTrafficSignGeneration(
            clearAssertion = true,
            reason = if (enabled) "tsr_enabled" else "tsr_disabled",
            permitWrites = enabled && isDriving,
        )
        updateState {
            copy(
                trafficSignRecognitionEnabled = enabled,
                trafficSignRecognitionUnavailable = false,
                trafficSignDebugRoadContextInvalid = false,
                trafficSignDebugGenerationSessionContextMismatch = false,
                trafficSignDebugRuntimeUnhealthy = false,
                trafficSignLastEvent = null,
                trafficSignCameraRuntimeState = if (enabled) {
                    trafficSignCameraRuntimeState
                } else {
                    TrafficSignCameraRuntimeState.DISABLED
                },
                trafficSignCameraRuntimeDetail = if (enabled) {
                    trafficSignCameraRuntimeDetail
                } else {
                    ConsumerRuntimeText.CAMERA_DISABLED.text()
                },
                trafficSignGeneration = this@ConsumerSessionController.trafficSignGeneration.get(),
            )
        }
        reconcileTrafficSignCamera()
    }

    fun setOtherTrafficSignDisplayEnabled(enabled: Boolean) {
        preferences.edit().putBoolean(KEY_OTHER_TRAFFIC_SIGN_DISPLAY_ENABLED, enabled).apply()
        updateState { copy(otherTrafficSignDisplayEnabled = enabled, lastTrafficSignPictogram = null) }
    }

    /** Presentation-only callback. This path never invokes the speed resolver or passage persistence. */
    fun submitTrafficSignDisplayObservation(observation: TrafficSignDisplayObservation) {
        if (TrafficSignDisplayPolicy.accepted(listOf(TrafficSignDetection(observation.candidate))) == null) return
        if (observation.isSpeedLimitEnd) showTrafficSignEndOverlay()
        val currentGeneration = trafficSignGeneration.get()
        val generationMismatch = observation.generation != currentGeneration
        val sessionMismatch = observation.driveSessionId != trafficSignDriveSessionId
        if (generationMismatch || sessionMismatch) {
            noteTrafficSignDebugMismatch(
                reason = "display_observation_rejected",
                details = mapOf(
                    "eventGeneration" to observation.generation,
                    "currentGeneration" to currentGeneration,
                    "eventSessionId" to observation.driveSessionId,
                    "currentSessionId" to trafficSignDriveSessionId,
                ),
            )
            return
        }
        postState {
            if (!otherTrafficSignDisplayEnabled || !trafficSignRecognitionEnabled || !isDriving) {
                this
            } else copy(lastTrafficSignPictogram = TrafficSignDisplayPolicy.next(
                lastTrafficSignPictogram, observation, trafficSignDisplayCatalog,
            ))
        }
    }

    private fun showTrafficSignEndOverlay() {
        mainHandler.post {
            if (isDisposed.get()) return@post
            trafficSignEndOverlayGeneration += 1L
            val generation = trafficSignEndOverlayGeneration
            trafficSignEndOverlayHideRunnable?.let(mainHandler::removeCallbacks)
            updateState { copy(isTrafficSignEndOverlayVisible = true) }
            val hide = Runnable {
                if (generation == trafficSignEndOverlayGeneration) {
                    updateState { copy(isTrafficSignEndOverlayVisible = false) }
                }
            }
            trafficSignEndOverlayHideRunnable = hide
            mainHandler.postDelayed(hide, trafficSignEndOverlayDurationMs)
        }
    }

    fun onCameraPermissionResult(granted: Boolean) {
        if (!granted) {
            if (driveRecorderEnabled) {
                driveRecorderEnabled = false
                updateState { copy(driveRecorderState = DriveRecorderState.DENIED) }
            }
            onTrafficSignCameraRuntimeStateChanged(
                TrafficSignCameraRuntimeState.DENIED,
                ConsumerRuntimeText.CAMERA_PERMISSION_DENIED.text(),
            )
            return
        }
        reconcileTrafficSignCamera()
    }

    fun onTrafficSignCameraRuntimeStateChanged(
        state: TrafficSignCameraRuntimeState,
        detail: String,
    ) {
        if (state in setOf(
                TrafficSignCameraRuntimeState.FAILED,
                TrafficSignCameraRuntimeState.UNAVAILABLE,
                TrafficSignCameraRuntimeState.DENIED,
            ) && isTrafficSignRecognitionRuntimeEnabled()
        ) {
            noteTrafficSignDebugIssue(
                issue = TrafficSignDebugIndicator.RUNTIME_UNHEALTHY,
                reason = "camera_runtime_state",
                details = mapOf("state" to state.name.lowercase(Locale.US), "detail" to detail),
            )
        }
        if (driveRecorderEnabled) {
            val recorderState = when (state) {
                TrafficSignCameraRuntimeState.ACTIVE -> DriveRecorderState.RECORDING
                TrafficSignCameraRuntimeState.REQUESTING_PERMISSION -> DriveRecorderState.REQUESTING_PERMISSION
                TrafficSignCameraRuntimeState.STARTING -> DriveRecorderState.PREPARING
                TrafficSignCameraRuntimeState.DENIED -> DriveRecorderState.DENIED
                TrafficSignCameraRuntimeState.UNAVAILABLE -> DriveRecorderState.UNAVAILABLE
                TrafficSignCameraRuntimeState.FAILED -> DriveRecorderState.FAILED
                TrafficSignCameraRuntimeState.DISABLED -> DriveRecorderState.DISABLED
            }
            updateState { copy(driveRecorderState = recorderState) }
            if (state == TrafficSignCameraRuntimeState.ACTIVE && isPanoramaxCaptureEnabled()) beginPanoramaxCaptureSession()
            if (state == TrafficSignCameraRuntimeState.ACTIVE) ensureDashcamRecordingIfCameraActive(state)
            if (state in setOf(TrafficSignCameraRuntimeState.FAILED, TrafficSignCameraRuntimeState.UNAVAILABLE, TrafficSignCameraRuntimeState.DENIED)) {
                driveRecorderEnabled = false
                endPanoramaxCaptureSession()
            }
        }
        postState {
            copy(
                trafficSignCameraRuntimeState = state,
                trafficSignCameraRuntimeDetail = if (trafficSignRecognitionUnavailable && state == TrafficSignCameraRuntimeState.ACTIVE) trafficSignCameraRuntimeDetail else detail,
                driveRecorderPanoramaxActive = isPanoramaxCaptureEnabled() && state == TrafficSignCameraRuntimeState.ACTIVE,
                trafficSignDebugRuntimeUnhealthy = trafficSignDebugRuntimeUnhealthy
                    || state in setOf(
                        TrafficSignCameraRuntimeState.FAILED,
                        TrafficSignCameraRuntimeState.UNAVAILABLE,
                        TrafficSignCameraRuntimeState.DENIED,
                    ),
            )
        }
        appendRuntimeDiagnosticEvent(
            event = "traffic_sign_camera_runtime",
            details = mapOf(
                "state" to state.name.lowercase(Locale.US),
                "detail" to detail,
            ),
        )
    }

    fun onDashcamRecordingFinalized(path: String, success: Boolean, detail: String?) {
        if (activeDashcamPath == path) activeDashcamPath = null
        submitBackgroundTask { cleanupDashcamRecordings() }
        postState {
            if (path != latestDashcamEventPath) copy(dashcamRecordings = listDashcamRecordings()) else
            copy(driveRecorderState = if (driveRecorderEnabled) driveRecorderState else DriveRecorderState.DISABLED,
                dashcamRecordings = listDashcamRecordings(),
                lastError = if (success) "" else detail.orEmpty())
        }
    }

    fun currentSpeedMetersPerSecondForTrafficSignAnalysis(): Double =
        (uiState.currentSpeedKmh / 3.6).takeIf { it.isFinite() && it >= 0.0 } ?: 0.0

    private fun reconcileTrafficSignCamera() {
        val shouldRun = !shouldPresentOnboarding() && (isTrafficSignRecognitionRuntimeEnabled() || isDriveRecorderSessionActive()) && uiState.appScreenshotState == null
        if (!shouldRun) {
            host?.stopTrafficSignCamera()
            updateState {
                copy(
                    trafficSignCameraRuntimeState = TrafficSignCameraRuntimeState.DISABLED,
                    trafficSignCameraRuntimeDetail = ConsumerRuntimeText.CAMERA_DISABLED.text(),
                )
            }
            return
        }
        if (hasCameraPermission()) {
            host?.startTrafficSignCamera()
            ensurePanoramaxCaptureSessionIfCameraActive()
            // Reusing an already-active shared camera does not emit another ACTIVE callback.
            // Bring the recorder state across the same boundary synchronously so the movie
            // consumer and Panoramax capture are not left in PREPARING forever.
            if (driveRecorderEnabled && uiState.trafficSignCameraRuntimeState == TrafficSignCameraRuntimeState.ACTIVE) {
                updateState {
                    copy(
                        driveRecorderState = DriveRecorderState.RECORDING,
                        driveRecorderPanoramaxActive = isPanoramaxCaptureEnabled(),
                    )
                }
            }
        } else if (uiState.trafficSignCameraRuntimeState != TrafficSignCameraRuntimeState.REQUESTING_PERMISSION) {
            updateState {
                copy(
                    trafficSignCameraRuntimeState = TrafficSignCameraRuntimeState.REQUESTING_PERMISSION,
                    trafficSignCameraRuntimeDetail = ConsumerRuntimeText.CAMERA_PERMISSION_REQUESTED.text(),
                )
            }
            host?.requestCameraPermission()
        }
    }

    /** Coherent road-context snapshot captured by the live CameraX/LiteRT lane for each accepted frame. */
    fun currentTrafficSignDetectionContext(): TrafficSignDetectionContextSnapshotValue? =
        synchronized(trafficSignStateLock) {
            val (generation, writePermitted) = trafficSignGeneration.snapshot()
            if (!writePermitted || !isTrafficSignRecognitionRuntimeEnabled() || uiState.trafficSignRecognitionUnavailable) {
                null
            } else latestTrafficSignContext?.let { context ->
                if (!context.isValidForTrafficSignDebugging()) {
                    noteTrafficSignDebugRoadContextInvalid(context)
                } else {
                    clearTrafficSignDebugRoadContextInvalid()
                }
                TrafficSignDetectionContextSnapshotValue(
                    context = context.copy(
                        routeRelationGroupIds = context.routeRelationGroupIds.toSet(),
                        sourceRelationIds = context.sourceRelationIds.toSet(),
                    ),
                    generation = generation,
                    // A recognized sign may establish the active limit even
                    // while the vehicle is stationary. Runtime admission is
                    // the safety gate; vehicle speed is not.
                    runtimeActivationEligible = isTrafficSignRecognitionRuntimeEnabled(),
                    driveSessionId = trafficSignDriveSessionId,
                )
            } ?: run {
                noteTrafficSignDebugRoadContextInvalid(null)
                null
            }
        }

    private fun TrafficSignDetectionContext.isValidForTrafficSignDebugging(): Boolean =
        !wayId.isNullOrBlank() && matchedWayStable && hasVerifiedBundle

    private fun noteTrafficSignDebugRoadContextInvalid(context: TrafficSignDetectionContext?) {
        val reason = when {
            context == null -> "missing"
            context.wayId.isNullOrBlank() -> "way_unmatched"
            !context.matchedWayStable -> "way_unstable"
            !context.hasVerifiedBundle -> "bundle_unverified"
            else -> "invalid"
        }
        noteTrafficSignDebugIssue(
            issue = TrafficSignDebugIndicator.INVALID_ROAD_CONTEXT,
            reason = "road_context_invalid",
            details = mapOf(
                "reason" to reason,
                "wayId" to context?.wayId,
                "matchedWayStable" to context?.matchedWayStable,
                "hasVerifiedBundle" to context?.hasVerifiedBundle,
            ),
        )
    }

    private fun clearTrafficSignDebugRoadContextInvalid() {
        updateState { copy(trafficSignDebugRoadContextInvalid = false) }
    }

    private fun noteTrafficSignDebugMismatch(
        reason: String,
        details: Map<String, Any?> = emptyMap(),
    ) {
        noteTrafficSignDebugIssue(
            issue = TrafficSignDebugIndicator.GENERATION_SESSION_CONTEXT_MISMATCH,
            reason = reason,
            details = details,
        )
    }

    private fun noteTrafficSignDebugIssue(
        issue: TrafficSignDebugIndicator,
        reason: String,
        details: Map<String, Any?> = emptyMap(),
    ) {
        val signature = buildString {
            append(issue.name)
            append('|')
            append(reason)
            details.toSortedMap().forEach { (key, value) ->
                append('|')
                append(key)
                append('=')
                append(value)
            }
        }
        val now = clock.millis()
        if (signature != lastTrafficSignDebugLogSignature || now - lastTrafficSignDebugLogAtMs >= 5_000L) {
            lastTrafficSignDebugLogSignature = signature
            lastTrafficSignDebugLogAtMs = now
            appendRuntimeDiagnosticEvent(
                event = "traffic_sign_debug_issue",
                details = details + mapOf(
                    "issue" to issue.name.lowercase(Locale.US),
                    "reason" to reason,
                    "trafficSignGeneration" to trafficSignGeneration.get(),
                    "driveSessionId" to trafficSignDriveSessionId,
                ),
            )
        }
        updateState {
            when (issue) {
                TrafficSignDebugIndicator.INVALID_ROAD_CONTEXT -> copy(trafficSignDebugRoadContextInvalid = true)
                TrafficSignDebugIndicator.GENERATION_SESSION_CONTEXT_MISMATCH -> copy(
                    trafficSignDebugGenerationSessionContextMismatch = true,
                )
                TrafficSignDebugIndicator.RUNTIME_UNHEALTHY -> copy(trafficSignDebugRuntimeUnhealthy = true)
                TrafficSignDebugIndicator.NORMAL -> this
            }
        }
    }

    /**
     * Accepts only an already-finalized live-frame passage. Visibility events
     * and the v2 shadow lane have no API path into the authoritative resolver.
     */
    fun submitFinalizedTrafficSignPassage(event: TrafficSignPassageEvent): Boolean {
        val currentGeneration = trafficSignGeneration.get()
        val generationMismatch = event.generation != currentGeneration
        val sessionMismatch = event.driveSessionId != trafficSignDriveSessionId
        if (generationMismatch || sessionMismatch) {
            noteTrafficSignDebugMismatch(
                reason = "passage_rejected",
                details = mapOf(
                    "eventGeneration" to event.generation,
                    "currentGeneration" to currentGeneration,
                    "eventSessionId" to event.driveSessionId,
                    "currentSessionId" to trafficSignDriveSessionId,
                ),
            )
            return false
        }
        if (!uiState.trafficSignRecognitionEnabled || !isDriving) {
            return false
        }
        return submitBackgroundTask {
            val backgroundGenerationMismatch = event.generation != trafficSignGeneration.get()
            val backgroundSessionMismatch = event.driveSessionId != trafficSignDriveSessionId
            if (backgroundGenerationMismatch || backgroundSessionMismatch) {
                noteTrafficSignDebugMismatch(
                    reason = "passage_background_rejected",
                    details = mapOf(
                        "eventGeneration" to event.generation,
                        "currentGeneration" to trafficSignGeneration.get(),
                        "eventSessionId" to event.driveSessionId,
                        "currentSessionId" to trafficSignDriveSessionId,
                    ),
                )
                return@submitBackgroundTask
            }
            if (!uiState.trafficSignRecognitionEnabled || !isDriving) {
                return@submitBackgroundTask
            }
            val outcome = synchronized(trafficSignStateLock) {
                // Invalidation advances the generation before taking this lock. Recheck all
                // admission state here so an old callback cannot mutate the resolver after a
                // disable, stop, or bundle replacement has logically taken effect.
                val contextCurrent = trafficSignPassageContextIsCurrent(event, latestTrafficSignContext)
                if (!uiState.trafficSignRecognitionEnabled || !isDriving ||
                    event.generation != trafficSignGeneration.get() ||
                    event.driveSessionId != trafficSignDriveSessionId ||
                    !contextCurrent
                ) {
                    if (!contextCurrent) {
                        noteTrafficSignDebugMismatch(
                            reason = "passage_context_rejected",
                            details = mapOf(
                                "eventGeneration" to event.generation,
                                "currentGeneration" to trafficSignGeneration.get(),
                                "eventSessionId" to event.driveSessionId,
                                "currentSessionId" to trafficSignDriveSessionId,
                                "currentWayId" to latestTrafficSignContext?.wayId,
                            ),
                        )
                    }
                    return@synchronized null
                }
                val base = latestTrafficSignBase
                var effective = trafficSignResolver.commit(
                    event,
                    base,
                    fallbackSpeedLimitAfterEnd = speedLimitFallbackAfterEnd(),
                )
                latestTrafficSignContext?.let { current ->
                    effective = trafficSignResolver.reconcile(
                        TrafficSignRoadMatch(
                            context = current,
                            matchedAtUtc = clock.instant(),
                            stabilized = current.matchedWayStable,
                        ),
                        base,
                    )
                }
                val activated = trafficSignResolver.takeNewlyActivatedEvent()
                    ?.takeIf { trafficSignResolver.activeAssertion()?.event?.finalizedEventId == it.finalizedEventId }
                Triple(effective, activated, trafficSignResolver.takeNewlyPersistableEvent())
            } ?: return@submitBackgroundTask
            if (event.generation != trafficSignGeneration.get() || !uiState.trafficSignRecognitionEnabled || !isDriving) {
                return@submitBackgroundTask
            }
            publishEffectiveTrafficSignLimit(outcome.first, outcome.second, event.generation)
            outcome.third?.let { persistable ->
                persistFinalizedTrafficSignPassage(
                    event = persistable,
                    resolvedLimit = outcome.first.resolution
                        ?.takeIf { outcome.second?.finalizedEventId == persistable.finalizedEventId }
                        ?: persistable.resolution,
                )
            }
        }
    }

    private fun invalidateTrafficSignGeneration(
        clearAssertion: Boolean,
        reason: String,
        permitWrites: Boolean,
    ) {
        val generation = trafficSignGeneration.incrementAndGet(permitWrites)
        feedbackGate.reset()
        synchronized(captureLock) { latestAnnotationDrafts = emptyList() }
        val base = synchronized(trafficSignStateLock) {
            if (clearAssertion) trafficSignResolver.clear()
            latestTrafficSignContext = null
            latestResolverLocation = null
            latestTrafficSignDirection = TrafficSignTravelDirection.UNKNOWN
            latestTrafficSignInsideCity = null
            resetTrafficSignTraversalLocked()
            latestTrafficSignBase.effective()
        }
        updateState {
            copy(
                trafficSignGeneration = generation,
                lastTrafficSignPictogram = null,
                isTrafficSignEndOverlayVisible = false,
                trafficSignDebugRoadContextInvalid = false,
                trafficSignDebugGenerationSessionContextMismatch = false,
                trafficSignDebugRuntimeUnhealthy = false,
                speedLimitKmh = base.resolution?.speedKmh,
                speedLimitDisplayText = if (base.resolution?.kind == TrafficSignResolvedLimitKind.WALK) "Schritt" else null,
                isUnlimitedSpeedLimitActive = base.resolution?.kind == TrafficSignResolvedLimitKind.UNLIMITED,
                effectiveSpeedLimitSource = base.source,
                effectiveSpeedLimitReason = reason,
                cameraSpeedLimitEvidence = false,
                trafficSignFinalConfidence = null,
                trafficSignAccumulatedSupport = null,
            )
        }
    }

    private fun persistFinalizedTrafficSignPassage(
        event: TrafficSignPassageEvent,
        resolvedLimit: TrafficSignResolvedLimit,
    ) {
        runCatching {
            synchronized(trafficSignStateLock) {
                trafficSignGeneration.withPermit(event.generation) {
                    if (!uiState.trafficSignRecognitionEnabled || !isDriving ||
                        event.driveSessionId != trafficSignDriveSessionId
                    ) {
                        return@withPermit null
                    }
                    val observation = localObservationStore.recordComputerVisionPassageIfNeeded(
                        event = event,
                        resolvedLimit = resolvedLimit,
                        captureContext = LocalObservationCaptureContext(
                            lat = event.activationContext?.latitude ?: event.lastSeenContext?.latitude,
                            lon = event.activationContext?.longitude ?: event.lastSeenContext?.longitude,
                            headingDeg = event.activationContext?.headingDegrees ?: event.lastSeenContext?.headingDegrees,
                            roadCandidateIds = listOfNotNull(
                                event.activationContext?.wayId,
                                event.lastSeenContext?.wayId,
                            ).distinct(),
                            cityContext = uiState.limitCityName,
                            streetContext = uiState.limitStreetName,
                            confidenceCalibrated = event.finalConfidence,
                            sourceVersion = uiState.activeBundleVersion,
                        ),
                        writeGate = null,
                        generationIsCurrent = { it == trafficSignGeneration.get() },
                        writePermitted = { uiState.trafficSignRecognitionEnabled && isDriving },
                    )
                    event.activationContext?.let { activation ->
                        localObservationStore.runtimeApplicableCorrectionForFinalizedEvent(
                            finalizedEventId = event.finalizedEventId,
                            currentDirection = activation.travelDirection,
                        )?.let { correction ->
                            trafficSignBaseForPersistedCorrection(latestTrafficSignContext, correction)?.let { localBase ->
                                // The active camera assertion still wins. This only refreshes
                                // the underlying source exposed by disable or later expiry.
                                latestTrafficSignBase = localBase
                            }
                        }
                    }
                    observation
                }
            }
        }.onSuccess { observation ->
            if (observation != null) {
                val updated = localObservationStore.fetchObservations()
                postState { copy(localObservations = updated) }
            }
        }.onFailure { error ->
            appendRuntimeDiagnosticEvent(
                event = "traffic_sign_observation_failed",
                details = mapOf("eventId" to event.finalizedEventId, "error" to (error.message ?: error.javaClass.simpleName)),
            )
        }
    }

    private fun publishEffectiveTrafficSignLimit(
        effective: EffectiveSpeedLimit,
        passage: TrafficSignPassageEvent? = null,
        expectedGeneration: Long = trafficSignGeneration.get(),
    ) {
        val resolution = effective.resolution
        if (passage != null && effective.source == EffectiveSpeedLimitSource.CAMERA && resolution?.kind == TrafficSignResolvedLimitKind.NUMERIC) {
            mainHandler.post {
                val context = passage.activationContext
                val speed = resolution.speedKmh
                if (trafficSignGeneration.get() == expectedGeneration && context != null && speed != null &&
                    uiState.speedCaptureMode == SpeedCaptureModeState.IDLE && isTrafficSignRecognitionRuntimeEnabled() &&
                    uiState.trafficSignFeedbackMode != TrafficSignFeedbackMode.SILENT &&
                    feedbackGate.shouldEmit(passage.physicalTrackId, speed, context, passage.passageBoundary.timestampUtc)) {
                    when (uiState.trafficSignFeedbackMode) {
                        TrafficSignFeedbackMode.SOUND -> playSpeedCaptureConfirmationTone()
                        TrafficSignFeedbackMode.SPOKEN_SPEED -> speakText(ConsumerUiStrings.text(
                            "$speed kilometres per hour", "$speed Kilometer pro Stunde", "$speed kilomètres par heure", "$speed kilometer per uur"))
                        TrafficSignFeedbackMode.SILENT -> Unit
                    }
                }
            }
        }
        postState {
            if (this@ConsumerSessionController.trafficSignGeneration.get() != expectedGeneration ||
                !trafficSignRecognitionEnabled || !this@ConsumerSessionController.isDriving
            ) this else copy(
                speedLimitKmh = resolution?.speedKmh,
                speedLimitDisplayText = if (resolution?.kind == TrafficSignResolvedLimitKind.WALK) "Schritt" else null,
                isUnlimitedSpeedLimitActive = resolution?.kind == TrafficSignResolvedLimitKind.UNLIMITED,
                effectiveSpeedLimitSource = effective.source,
                effectiveSpeedLimitReason = effective.presentationReason,
                cameraSpeedLimitEvidence = effective.cameraEvidence,
                trafficSignFinalConfidence = passage?.finalConfidence ?: trafficSignFinalConfidence,
                trafficSignAccumulatedSupport = passage?.finalAccumulatedSupport ?: trafficSignAccumulatedSupport,
            )
        }
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
            reason = "matcher_profile_changed",
        )
        updateState { copy(matcherDebugProfile = profile) }
    }

    fun fetchFirstGermanyManifest() {
        val endpoint = manifestEndpoints.firstOrNull { it.countryCode.uppercase(Locale.US) == "DEU" }
            ?: return setError(ConsumerRuntimeText.GERMANY_ENDPOINTS_MISSING.text())
        runSyncTask(status = "syncing", detail = ConsumerRuntimeText.LOADING_MANIFEST.text()) {
            val manifest = bootstrapper.fetchManifest(endpoint.manifestUrl)
            copy(
                syncStatus = "ready_manifest",
                syncProgressDetail = ConsumerRuntimeText.MANIFEST_LOADED.text("${manifest.region} ${manifest.bundleVersion}"),
                maintenanceMessage = ConsumerRuntimeText.MANIFEST_LOADED.text(manifest.region),
                lastError = "",
            )
        }
    }

    fun bootstrapAndSync() {
        if (manifestEndpoints.isEmpty()) {
            setError(ConsumerRuntimeText.ENDPOINTS_MISSING.text())
            return
        }
        if (isSyncingNow()) {
            setError(ConsumerRuntimeText.SYNC_ALREADY_RUNNING.text())
            return
        }
        updateState {
            copy(syncStatus = "syncing", syncProgressDetail = ConsumerRuntimeText.SYNC_STARTING.text(),
                syncProgressCompletedBytes = 0L, syncProgressTotalBytes = 0L,
                maintenanceMessage = "", activeDownloadOptionId = null, lastError = "")
        }
        submitBackgroundTask {
            try {
                val preferredCountry = bootstrapper.activeState()?.countryCode
                    ?: lookupServiceCountryCode ?: "DEU"
                val sync = bootstrapper.syncFromManifestEndpoints(manifestEndpoints, preferredCountry, ::applyBundleSyncProgress)
                refreshDownloadedBundleInventory()
                replaceLookupService(sync.dbPath, preferredCountryCode = bootstrapper.activeState()?.countryCode,
                    reason = "bootstrap_and_sync")
                postState {
                    copy(syncStatus = "ready_${sync.mode.name.lowercase(Locale.US)}",
                        syncProgressDetail = ConsumerRuntimeText.SYNC_COMPLETE.text(),
                        syncProgressCompletedBytes = 0L, syncProgressTotalBytes = 0L,
                        maintenanceMessage = sync.details, activeDownloadOptionId = null,
                        activeBundleVersion = sync.bundleVersion, activeDBPath = sync.dbPath, lastError = "")
                }
            } catch (error: Exception) {
                setError(error.message ?: ConsumerRuntimeText.NO_ENDPOINT_SYNCED.text())
            }
        }
    }

    fun deleteDownloadedBundlesKeepingSeed() {
        submitBackgroundTask {
            try {
                val removed = bootstrapper.removeDownloadedBundlesKeepingSeed()
                refreshDownloadedBundleInventory()
                bootstrapBundledSeedIfNeeded()
                val active = bootstrapper.activeState()
                replaceLookupService(
                    active?.dbPath,
                    preferredCountryCode = active?.countryCode,
                    reason = "delete_downloaded_bundles",
                )
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
                            ConsumerRuntimeText.MAPS_DELETED.text(removed)
                        } else {
                            ConsumerRuntimeText.NO_DOWNLOADED_MAPS.text()
                        },
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.MAPS_DELETE_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun downloadSelectedBundle(
        option: BundleDownloadOption,
        initialDownloader: BundleBootstrapper? = null,
        firstLocationSetup: Boolean = initialDownloader != null,
    ) {
        if (isSyncingNow()) {
            setError(ConsumerRuntimeText.DOWNLOAD_BUSY.text())
            return
        }
        updateState {
            copy(
                syncStatus = "syncing",
                syncProgressDetail = ConsumerRuntimeText.DOWNLOADING_NAME.text(option.displayName),
                syncProgressCompletedBytes = 0L,
                syncProgressTotalBytes = 0L,
                maintenanceMessage = ConsumerRuntimeText.DOWNLOAD_STARTED.text(option.displayName),
                activeDownloadOptionId = option.id,
                lastError = "",
            )
        }
        submitBackgroundTask {
            try {
                val sync = (initialDownloader ?: bootstrapper).syncFromManifestUrl(
                    manifestUrl = option.endpoint.manifestUrl,
                    onProgress = ::applyBundleSyncProgress,
                )
                refreshDownloadedBundleInventory()
                val active = bootstrapper.activeState()
                replaceLookupService(
                    sync.dbPath,
                    preferredCountryCode = active?.countryCode ?: option.countryCode,
                    reason = "download_selected_bundle",
                )
                if (firstLocationSetup) preferences.edit().putBoolean("youspeed.first_location_map_complete", true).apply()
                postState {
                    copy(
                        firstLocationPackStatus = if (firstLocationSetup) ConsumerRuntimeText.MATCHING_MAP_READY.text(option.displayName) else firstLocationPackStatus,
                        syncStatus = "ready_${sync.mode.name.lowercase(Locale.US)}",
                        syncProgressDetail = ConsumerRuntimeText.MAP_LOADED.text(option.displayName),
                        syncProgressCompletedBytes = 0L,
                        syncProgressTotalBytes = 0L,
                        maintenanceMessage = ConsumerRuntimeText.MAP_LOADED.text(option.displayName),
                        activeDownloadOptionId = null,
                        activeBundleVersion = sync.bundleVersion,
                        activeDBPath = sync.dbPath,

                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                if (firstLocationSetup) postState {
                    copy(firstLocationPackStatus = ConsumerRuntimeText.MAP_DOWNLOAD_FAILED.text())
                }
                setError(error.message ?: error.javaClass.simpleName)
            }
        }
    }

    fun deleteSelectedBundle(option: BundleDownloadOption) {
        submitBackgroundTask {
            try {
                val removed = bootstrapper.removeDownloadedBundles(option.endpoint.manifestRegion)
                refreshDownloadedBundleInventory()
                val active = bootstrapper.activeState()
                replaceLookupService(
                    active?.dbPath,
                    preferredCountryCode = active?.countryCode,
                    reason = "delete_selected_bundle",
                )
                postState {
                    copy(
                        activeBundleVersion = active?.bundleVersion ?: "none",
                        activeDBPath = active?.dbPath ?: "",
                        maintenanceMessage = if (removed > 0) ConsumerRuntimeText.MAP_DELETED.text(option.displayName) else ConsumerRuntimeText.MAP_NOT_DELETED.text(option.displayName),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.MAP_DELETE_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    private fun persistSpeedCaptureSelection(selection: SpeedCaptureSelection) {
        val selectedValue = selection.value
        submitBackgroundTask {
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
                        localObservationStatus = ConsumerRuntimeText.OBSERVATION_SAVED.text(wayId ?: "–", uiState.speedLimitKmh ?: "–", if (selection.value == "walk") ConsumerRuntimeText.PEDESTRIAN_ZONE.text() else selection.displayLabel),
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
                showSpeedCaptureFailure(reason = ConsumerRuntimeText.OBSERVATION_SAVE_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun deleteLocalObservation(observationId: String) {
        submitBackgroundTask {
            try {
                localObservationStore.deleteObservation(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                activeLocalSpeedCorrection = null
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = ConsumerRuntimeText.OBSERVATION_DELETED.text(),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.DELETE_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun deleteAllLocalObservations() {
        submitBackgroundTask {
            try {
                val removed = localObservationStore.deleteAllObservations()
                localSpeedOverridesByWayId = emptyMap()
                localSpeedOverrideValuesByWayId = emptyMap()
                activeLocalSpeedCorrection = null
                postState {
                    copy(
                        localObservations = emptyList(),
                        localObservationStatus = if (removed > 0) ConsumerRuntimeText.OBSERVATIONS_DELETED.text(removed) else ConsumerRuntimeText.NO_OBSERVATIONS.text(),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.DELETE_ALL_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun exportAllLocalObservations() {
        submitBackgroundTask {
            try {
                val result = localObservationStore.exportAllLocalObservationsAsOsc()
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservationStatus = ConsumerRuntimeText.EXPORT_CREATED_COUNT.text(result.includedCount),
                        localObservations = updated,
                        lastExportDirectoryPath = result.packageDirectory.absolutePath,
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.EXPORT_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun approveLocalObservation(observationId: String) {
        submitBackgroundTask {
            try {
                localObservationStore.reviewAndApproveProposal(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = ConsumerRuntimeText.OBSERVATION_APPROVED.text(),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.APPROVAL_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun discardLocalObservation(observationId: String) {
        submitBackgroundTask {
            try {
                localObservationStore.discardObservation(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = ConsumerRuntimeText.OBSERVATION_DISCARDED.text(),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.DISCARD_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun exportLocalObservation(observationId: String) {
        submitBackgroundTask {
            try {
                val result = localObservationStore.exportProposalAsOscPackage(observationId)
                val updated = localObservationStore.fetchObservations(limit = 500)
                localSpeedOverridesByWayId = resolveLocalSpeedOverrides(updated)
                localSpeedOverrideValuesByWayId = resolveLocalSpeedOverrideValues(updated)
                postState {
                    copy(
                        localObservations = updated,
                        localObservationStatus = ConsumerRuntimeText.EXPORT_CREATED.text(result.packageDirectory.name),
                        lastExportDirectoryPath = result.packageDirectory.absolutePath,
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.SINGLE_EXPORT_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun shareGpsLog() {
        val path = uiState.gpsLogPath.takeIf { it.isNotBlank() } ?: return setError(ConsumerRuntimeText.GPS_LOG_MISSING.text())
        host?.shareFile(path, "text/csv")
    }

    fun shareMatchLog() {
        val path = uiState.matchLogPath.takeIf { it.isNotBlank() } ?: return setError(ConsumerRuntimeText.MATCH_LOG_MISSING.text())
        host?.shareFile(path, "application/x-ndjson")
    }

    fun shareRuntimeDiagnosticsLog() {
        val path = uiState.runtimeDiagnosticsLogPath.takeIf { it.isNotBlank() }
            ?: return setError(ConsumerRuntimeText.DIAGNOSTIC_LOG_MISSING.text())
        host?.shareFile(path, "application/x-ndjson")
    }

    fun shareDashcamRecording(path: String) {
        host?.shareFile(path, "video/mp4")
    }

    fun clearDrivingLogs() {
        submitBackgroundTask {
            try {
                resetDrivingLogFiles(gpsLogFile = gpsLogFile(), matchLogFile = matchLogFile())
                postState {
                    copy(
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                        maintenanceMessage = ConsumerRuntimeText.DRIVING_LOG_CLEARED.text(),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.CLEAR_DRIVING_LOG_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun clearRuntimeDiagnosticsLog() {
        submitBackgroundTask {
            try {
                ensureRuntimeDiagnosticsLogExists()
                runtimeDiagnosticsLogFile().writeText("")
                appendRuntimeDiagnosticEvent(
                    event = "runtime_diagnostics_cleared",
                    details = mapOf("pid" to Process.myPid()),
                )
                postState {
                    copy(
                        runtimeDiagnosticsLogPath = runtimeDiagnosticsLogFile().absolutePath,
                        maintenanceMessage = ConsumerRuntimeText.DIAGNOSTIC_LOG_CLEARED.text(),
                        lastError = "",
                    )
                }
            } catch (error: Exception) {
                setError(ConsumerRuntimeText.CLEAR_DIAGNOSTIC_LOG_FAILED.text(error.message ?: error.javaClass.simpleName))
            }
        }
    }

    fun openCurrentOsmUrl() {
        val url = currentOsmUrl() ?: return setError(ConsumerRuntimeText.OSM_LOCATION_MISSING.text())
        host?.openExternalUrl(url)
    }

    fun debugRows(): List<Pair<String, String>> {
        val state = uiState
        fun text(value: String?): String = value?.trim().takeUnless { it.isNullOrEmpty() } ?: "n/a"
        return listOf(
            ConsumerRuntimeText.COORDINATES.text() to coordinateText(),
            ConsumerRuntimeText.SPEED.text() to String.format(Locale.US, "%.1f km/h", state.currentSpeedKmh),
            ConsumerRuntimeText.SPEED_LIMIT.text() to (state.speedLimitDisplayText?.let {
                if (it == "Schritt") ConsumerRuntimeText.PEDESTRIAN_ZONE.text() else it
            } ?: state.speedLimitKmh?.toString()?.plus(" km/h") ?: if (state.isUnlimitedSpeedLimitActive) ConsumerRuntimeText.UNLIMITED.text() else "n/a"),
            ConsumerRuntimeText.OVERSPEED.text() to "${ConsumerMainScreenLogic.currentOverspeedKmh(state)} km/h",
            ConsumerRuntimeText.DRIVE_STATUS.text() to when (state.driveStatus) {
                "running" -> ConsumerRuntimeText.DRIVING_RUNNING.text()
                "stopped" -> ConsumerRuntimeText.DRIVING_STOPPED.text()
                "requesting_location" -> ConsumerRuntimeText.LOCATION_REQUIRED_FOR_MAP.text()
                "location_denied" -> ConsumerRuntimeText.LOCATION_DENIED.text()
                else -> state.driveStatus
            },
            ConsumerRuntimeText.GPS_FIXES.text() to state.gpsFixCount.toString(),
            ConsumerRuntimeText.ACTIVE_BUNDLE.text() to state.activeBundleVersion,
            ConsumerRuntimeText.ACTIVE_DATABASE.text() to if (state.activeDBPath.isBlank()) "n/a" else File(state.activeDBPath).name,
            ConsumerRuntimeText.DATABASE_PATH.text() to if (state.activeDBPath.isBlank()) "n/a" else state.activeDBPath,
            ConsumerRuntimeText.WAY_ID.text() to text(state.limitWayId),
            ConsumerRuntimeText.STREET.text() to text(state.limitStreetName),
            ConsumerRuntimeText.CITY.text() to text(state.limitCityName),
            ConsumerRuntimeText.LOCALITY.text() to text(state.limitCityPlaceName),
            ConsumerRuntimeText.DISTRICT.text() to text(state.limitCityDistrictName),
            ConsumerRuntimeText.GPS_SIGNAL.text() to "${state.gpsSignalBars}/4",
            ConsumerRuntimeText.GPS_ACCURACY.text() to (state.gpsHorizontalAccuracyM?.run { String.format(Locale.US, "%.1f m", this) } ?: "n/a"),
            ConsumerRuntimeText.MATCHER.text() to state.matcherDebugProfile.debugLabel,
            ConsumerRuntimeText.TUNNEL_MODE.text() to when (state.tunnelModeState) {
                TunnelModeState.INACTIVE -> ConsumerRuntimeText.INACTIVE.text()
                TunnelModeState.ACTIVE -> ConsumerRuntimeText.ACTIVE.text()
            },
            ConsumerRuntimeText.BUILT_UP_AREA.text() to when (state.lastLookupInsideCity) {
                true -> ConsumerRuntimeText.YES.text()
                false -> ConsumerRuntimeText.NO.text()
                null -> "n/a"
            },
            ConsumerRuntimeText.QUERY_TIME.text() to String.format(Locale.US, "%.2f ms", state.lastLookupQueryMs),
            ConsumerRuntimeText.CANDIDATES.text() to state.lastLookupCandidateCount.toString(),
            ConsumerRuntimeText.WITH_LIMIT.text() to state.lastLookupSpeedCandidateCount.toString(),
            ConsumerRuntimeText.NEAREST_ROAD.text() to (state.lastLookupNearestCandidateM?.let { String.format(Locale.US, "%.1f m", it) } ?: "n/a"),
            ConsumerRuntimeText.NEAREST_LIMIT.text() to (state.lastLookupNearestSpeedCandidateM?.let { String.format(Locale.US, "%.1f m", it) } ?: "n/a"),
            ConsumerRuntimeText.CITY_SOURCE.text() to state.lastLookupCitySource,
            ConsumerRuntimeText.GPS_LOG.text() to if (state.gpsLogPath.isBlank()) "n/a" else state.gpsLogPath,
            ConsumerRuntimeText.MATCH_LOG.text() to if (state.matchLogPath.isBlank()) "n/a" else state.matchLogPath,
            ConsumerRuntimeText.DIAGNOSTIC_LOG.text() to if (state.runtimeDiagnosticsLogPath.isBlank()) "n/a" else state.runtimeDiagnosticsLogPath,
            ConsumerRuntimeText.LOOKUP.text() to formattedSyncStatus(),
            ConsumerRuntimeText.MANIFEST_SOURCES.text() to state.configuredManifestEndpointCount.toString(),
            ConsumerRuntimeText.MANIFEST_COUNTRIES.text() to state.configuredManifestCountryCodes,
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
        "not_synced" -> ConsumerRuntimeText.SYNC_NOT_STARTED.text()
        "syncing" -> ConsumerRuntimeText.SYNC_RUNNING.text()
        "bootstrapping" -> ConsumerRuntimeText.PREPARING.text()
        "sync_failed" -> ConsumerRuntimeText.SYNC_FAILED.text()
        "seed_only" -> ConsumerRuntimeText.STARTER_ACTIVE.text()
        "ready_upToDate", "ready_up_to_date" -> ConsumerRuntimeText.SYNC_CURRENT.text()
        "ready_fullDownload", "ready_full_download", "ready_deltaPatch" -> ConsumerRuntimeText.SYNC_COMPLETE.text()
        "ready_bootstrap" -> ConsumerRuntimeText.STARTER_ACTIVE.text()
        "ready_manifest" -> ConsumerRuntimeText.MANIFEST_READY.text()
        else -> uiState.syncStatus.replace("_", " ")
    }

    fun isSyncingNow(): Boolean {
        return uiState.syncStatus == "syncing" || uiState.syncStatus == "bootstrapping"
    }

    fun hasActiveBundleDownload(): Boolean {
        return !uiState.activeDownloadOptionId.isNullOrBlank()
    }

    fun isActiveBundleDownload(option: BundleDownloadOption): Boolean {
        return hasActiveBundleDownload() && uiState.activeDownloadOptionId == option.id
    }

    fun activeBundleDownloadProgress(option: BundleDownloadOption): Double? {
        if (!isActiveBundleDownload(option)) {
            return null
        }
        val total = uiState.syncProgressTotalBytes.coerceAtLeast(0L)
        if (total <= 0L) {
            return null
        }
        val completed = uiState.syncProgressCompletedBytes.coerceAtLeast(0L).coerceAtMost(total)
        return completed.toDouble() / total.toDouble()
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
        return if (latest != null) ConsumerRuntimeText.DOWNLOADED_VERSION.text(latest) else ConsumerRuntimeText.DOWNLOADED.text()
    }

    private fun coordinateText(): String {
        val lat = uiState.currentLatitude?.run { String.format(Locale.US, "%.6f", this) } ?: "n/a"
        val lon = uiState.currentLongitude?.run { String.format(Locale.US, "%.6f", this) } ?: "n/a"
        return "$lat, $lon"
    }

    private fun applyBundleSyncProgress(progress: BundleSyncProgress) {
        postState {
            copy(
                syncProgressDetail = when (progress.stage) {
                    BundleSyncStage.PREPARING -> ConsumerRuntimeText.DOWNLOAD_PREPARING.text()
                    BundleSyncStage.DOWNLOADING -> ConsumerRuntimeText.DOWNLOAD_RUNNING.text()
                    BundleSyncStage.ASSEMBLING -> ConsumerRuntimeText.DOWNLOAD_ASSEMBLING.text()
                    BundleSyncStage.APPLYING_DELTA -> ConsumerRuntimeText.DOWNLOAD_ASSEMBLING.text()
                    BundleSyncStage.COMPLETED -> ConsumerRuntimeText.SYNC_COMPLETE.text()
                },
                syncProgressCompletedBytes = progress.completedBytes.coerceAtLeast(0L),
                syncProgressTotalBytes = progress.totalBytes.coerceAtLeast(0L),
            )
        }
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
                syncProgressCompletedBytes = 0L,
                syncProgressTotalBytes = 0L,
                maintenanceMessage = "",
                activeDownloadOptionId = null,
                lastError = "",
            )
        }
        submitBackgroundTask {
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
                syncStatus = if (syncStatus == "syncing" || syncStatus == "bootstrapping") "sync_failed" else syncStatus,
                syncProgressDetail = "",
                syncProgressCompletedBytes = 0L,
                syncProgressTotalBytes = 0L,
                activeDownloadOptionId = null,
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
        val locale = Locale.getDefault()
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
        val scenario = countryScreenshotScenario
        val fixture = scenario?.let {
            state.fixture.copy(currentSpeedKmh = (it.limitKmh + it.deltaKmh).toDouble(), speedLimitKmh = it.limitKmh,
                streetName = it.street, cityName = it.city, latitude = it.latitude, longitude = it.longitude, insideCity = true)
        } ?: state.fixture
        val selectedCountry = penaltyCountrySelection.update(regionalPackCatalog, fixture.latitude, fixture.longitude,
            fixture.gpsHorizontalAccuracyM, clock.millis() / 1000.0, clock.millis() / 1000.0)
        check(scenario == null || selectedCountry == scenario.countryCode) { "Screenshot GPS country did not resolve" }
        val cameraFixture = state in setOf(AppScreenshotState.CAMERA_LIMIT_ACTIVE, AppScreenshotState.OTHER_SIGN_GIVE_WAY,
            AppScreenshotState.OTHER_SIGN_STOP, AppScreenshotState.OTHER_SIGN_CLEARED)
        uiState = uiState.copy(
            otherTrafficSignDisplayEnabled = cameraFixture,
            trafficSignRecognitionEnabled = cameraFixture,
            lastTrafficSignPictogram = when (state) {
                AppScreenshotState.OTHER_SIGN_GIVE_WAY -> trafficSignDisplayCatalog.pictogram("give_way")
                AppScreenshotState.OTHER_SIGN_STOP -> trafficSignDisplayCatalog.pictogram("stop")
                else -> null
            },
            activePenaltyRules = selectedCountry?.let(::loadPenaltyRules) ?: ActivePenaltyRules.unavailable(),
            startupDataState = StartupDataState.READY,
            startupProgress = 1.0,
            startupDetail = ConsumerRuntimeText.SCREENSHOT_READY.text(),
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
            limitCityPlaceName = fixture.cityName,
            limitCityDistrictName = null,
            currentLatitude = fixture.latitude,
            currentLongitude = fixture.longitude,
            gpsHorizontalAccuracyM = fixture.gpsHorizontalAccuracyM,
            gpsSignalBars = fixture.gpsSignalBars,
            gpsFixCount = 1,
            driveStatus = "running",
            hideWelcomeScreen = true,
            appScreenshotState = state,
            lastLookupInsideCity = fixture.insideCity,
            effectiveSpeedLimitSource = if (cameraFixture) {
                EffectiveSpeedLimitSource.CAMERA
            } else {
                EffectiveSpeedLimitSource.BUNDLE
            },
            effectiveSpeedLimitReason = if (cameraFixture) {
                "screenshot_camera_limit_active"
            } else {
                "screenshot_fixture"
            },
            cameraSpeedLimitEvidence = cameraFixture,
            localObservationStatus = "",
            germanSpeechModelState = GermanSpeechModelState.READY,
            germanSpeechModelStatus = ConsumerRuntimeText.SCREENSHOT_NO_AUDIO.text(),
            gpsLogPath = gpsLogFile().absolutePath,
            matchLogPath = matchLogFile().absolutePath,
        )
    }

    private fun loadPenaltyRules(countryCode: String): ActivePenaltyRules {
        val code = PenaltyCountryCodes.normalize(countryCode) ?: return ActivePenaltyRules.unavailable()
        val assetName = "$code-rules.json"
        val raw = assetReader.readTextOrNull("Rules/$assetName") ?: assetReader.readTextOrNull(assetName)
            ?: return ActivePenaltyRules.unavailable(code)
        val parsed = runCatching { PenaltyRulesParser.parse(raw) }.getOrNull()
            ?.takeIf { PenaltyCountryCodes.normalize(it.countryCode) == code && it.bands.isNotEmpty() }
            ?: return ActivePenaltyRules.unavailable(code)
        return ActivePenaltyRules(fileName = assetName, ruleSet = parsed)
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
                    lastError = ConsumerRuntimeText.LOCATION_DENIED.text(),
                )
            }
            return
        }
        stopLocationUpdates()
        resetDerivedSpeedTracking()
        updateState { copy(currentSpeedKmh = 0.0) }
        ensureDrivingLogsExist()
        val enabledProviders = locationManager.getProviders(true).filterNotNull()
        val preciseProviders = if (hasFineLocationPermission()) {
            enabledProviders.filter { provider ->
                provider == LocationManager.GPS_PROVIDER || provider == "fused"
            }
        } else {
            emptyList()
        }
        val hasNetworkProvider = LocationManager.NETWORK_PROVIDER in enabledProviders
        if (preciseProviders.isEmpty() && !hasNetworkProvider) {
            updateState {
                copy(
                    driveStatus = "location_error",
                    lastError = ConsumerRuntimeText.LOCATION_PROVIDERS_MISSING.text(),
                )
            }
            return
        }
        preciseProviders.forEach { provider ->
            runCatching {
                locationManager.requestLocationUpdates(provider, 3_000L, 0f, locationListener, Looper.getMainLooper())
            }.onFailure {
                updateState {
                    copy(
                        driveStatus = "location_error",
                        lastError = it.message ?: ConsumerRuntimeText.LOCATION_UPDATES_FAILED.text(),
                    )
                }
            }
        }
        if (hasNetworkProvider) {
            runCatching {
                locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER,
                    5_000L,
                    0f,
                    coarseLocationListener,
                    Looper.getMainLooper(),
                )
            }.onFailure {
                appendRuntimeDiagnosticEvent(
                    event = "coarse_location_updates_failed",
                    details = mapOf("error" to (it.message ?: it.javaClass.simpleName)),
                )
            }
        }
        preciseProviders.mapNotNull { provider -> runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull() }
            .maxByOrNull { it.time }
            ?.let(::consumeLocation)
        if (hasNetworkProvider) {
            runCatching { locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER) }
                .getOrNull()
                ?.let(::consumeCoarseLocation)
        }
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
        runCatching { locationManager.removeUpdates(coarseLocationListener) }
    }

    private fun resetDerivedSpeedTracking() {
        recentSpeedSampleLocations.clear()
    }

    private fun updateCurrentSpeed(location: Location): Double {
        if (recentSpeedSampleLocations.isNotEmpty() && location.time <= recentSpeedSampleLocations.last().time) {
            recentSpeedSampleLocations.clear()
        }

        recentSpeedSampleLocations += Location(location)
        // Keep a short history so low-speed fallback can use recent displacement.
        recentSpeedSampleLocations.removeAll { location.time - it.time > DERIVED_SPEED_COMPUTATION_MAX_WINDOW_MS }

        val gpsSpeedKmh = max(0.0, location.speed.toDouble()) * 3.6
        val speedAccuracyKmh = if (location.hasSpeedAccuracy()) location.speedAccuracyMetersPerSecond.toDouble() * 3.6 else null
        val referenceLocation = recentSpeedSampleLocations.firstOrNull()
        val fallbackDerivedSpeedKmh = if (referenceLocation != null) {
            val elapsedSeconds = (location.time - referenceLocation.time).toDouble() / 1_000.0
            val accuracyAllowanceM = max(
                0.0,
                max(
                    referenceLocation.accuracy.toDouble().takeIf { it.isFinite() && it >= 0.0 } ?: 0.0,
                    location.accuracy.toDouble().takeIf { it.isFinite() && it >= 0.0 } ?: 0.0,
                ),
            )
            if (elapsedSeconds >= DERIVED_SPEED_COMPUTATION_MIN_WINDOW_SECONDS) {
                derivedSpeedKmh(
                    distanceM = location.distanceTo(referenceLocation).toDouble(),
                    elapsedSeconds = elapsedSeconds,
                    accuracyAllowanceM = accuracyAllowanceM,
                )
            } else {
                0.0
            }
        } else {
            0.0
        }
        return filteredDisplaySpeedKmh(
            rawSpeedKmh = gpsSpeedKmh,
            fallbackDerivedSpeedKmh = fallbackDerivedSpeedKmh,
            speedAccuracyKmh = speedAccuracyKmh,
            previousDisplaySpeedKmh = uiState.currentSpeedKmh,
        )
    }

    private fun consumeLocation(location: Location) {
        if (!hasFineLocationPermission() || location.provider == LocationManager.NETWORK_PROVIDER) {
            return
        }
        discoverPacks(location)
        val previousLocation = recentSpeedSampleLocations
            .asReversed()
            .firstOrNull { prior ->
                location.time > prior.time && location.distanceTo(prior).toDouble() > 0.1
            }
        val trafficSignHeadingDegrees = trafficSignHeadingDegrees(
            reportedBearingDegrees = location.bearing.toDouble().takeIf { location.hasBearing() },
            previousLatitude = previousLocation?.latitude,
            previousLongitude = previousLocation?.longitude,
            currentLatitude = location.latitude,
            currentLongitude = location.longitude,
        )
        latestCaptureLocation = Location(location)
        val filteredSpeedKmh = updateCurrentSpeed(location)
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
        maybeCapturePanoramaxPhoto()

        val token = lookupToken.advance()
        val fallbackDBPath = uiState.activeDBPath.takeIf { it.isNotBlank() && File(it).exists() }
        val fallbackBundleVersion = uiState.activeBundleVersion

        submitBackgroundTask {
            // A newer fix may already be queued while an earlier map lookup is running.
            // Discard obsolete work before touching the database again.
            if (!lookupToken.isCurrent(token)) return@submitBackgroundTask
            val route = runCatching {
                bootstrapper.resolveLocalBundleRoute(
                    lat = location.latitude,
                    lon = location.longitude,
                    fallbackDBPath = fallbackDBPath,
                )
            }.onFailure { error ->
                appendRuntimeDiagnosticEvent(
                    event = "bundle_route_error",
                    details = mapOf(
                        "lat" to location.latitude,
                        "lon" to location.longitude,
                        "fallbackDbPath" to fallbackDBPath,
                        "errorClass" to error.javaClass.name,
                        "error" to (error.message ?: error.javaClass.simpleName),
                    ),
                )
            }.getOrNull()
            val routedDBPath = route?.dbPath?.takeIf { it.isNotBlank() && File(it).exists() }
            val effectiveDBPath = routedDBPath ?: fallbackDBPath
            val fallbackCountryCode = normalizedCountryCode(bootstrapper.activeState()?.countryCode)
                ?: inferCountryCodeFromDBPath(fallbackDBPath)
            val effectiveCountryCode = normalizedCountryCode(route?.countryCode)
                ?: fallbackCountryCode
                ?: inferCountryCodeFromDBPath(effectiveDBPath)
            val effectiveBundleVersion = route?.bundleVersion ?: fallbackBundleVersion
            val effectiveBundleSha256 = route?.dbSha256
                ?.trim()
                ?.lowercase(Locale.US)
                ?.takeIf { VERIFIED_SHA256.matches(it) }
            val previousTrafficSignBundleSha256 = synchronized(trafficSignStateLock) {
                latestTrafficSignContext?.bundleSha256
            }
            val routeChanged = route != null && (
                    routedDBPath != fallbackDBPath ||
                    effectiveBundleVersion != fallbackBundleVersion ||
                    effectiveCountryCode != fallbackCountryCode ||
                    (previousTrafficSignBundleSha256 != null && effectiveBundleSha256 != previousTrafficSignBundleSha256)
            )

            if (!lookupToken.isCurrent(token)) return@submitBackgroundTask

            if (routeChanged && effectiveDBPath != null) {
                lookupToken.mutateIfCurrent(token) {
                    val nextTrafficSignGeneration = trafficSignGeneration.incrementAndGet(
                        uiState.trafficSignRecognitionEnabled && isDriving,
                    )
                    synchronized(trafficSignStateLock) {
                        trafficSignResolver.clear()
                        latestTrafficSignContext = null
                        latestResolverLocation = null
                        resetTrafficSignTraversalLocked()
                    }
                    appendRuntimeDiagnosticEvent(
                        event = "bundle_route_switched",
                        details = mapOf(
                            "lat" to location.latitude,
                            "lon" to location.longitude,
                            "region" to route?.region,
                            "bundleVersion" to effectiveBundleVersion,
                            "dbPath" to effectiveDBPath,
                            "previousDbPath" to fallbackDBPath,
                            "countryCode" to effectiveCountryCode,
                        ),
                    )
                    postState {
                        if (!lookupToken.isCurrent(token)) this else copy(
                            activeBundleVersion = effectiveBundleVersion,
                            activeDBPath = effectiveDBPath,

                            trafficSignGeneration = nextTrafficSignGeneration,
                            cameraSpeedLimitEvidence = false,
                            trafficSignFinalConfidence = null,
                            trafficSignAccumulatedSupport = null,
                        )
                    }
                } ?: return@submitBackgroundTask
            }

            if (effectiveDBPath == null) {
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
                        limitCityPlaceName = null,
                        limitCityDistrictName = null,
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
                return@submitBackgroundTask
            }

            try {
                val matchContext = wayMatchTracker.snapshotOrNull()
                val result = synchronized(lookupServiceLock) {
                    ensureLookupServiceLocked(
                        dbPath = effectiveDBPath,
                        preferredCountryCode = effectiveCountryCode,
                        reason = "location_lookup",
                    ).lookup(
                        lat = location.latitude,
                        lon = location.longitude,
                        radiusM = lookupRadiusForHorizontalAccuracy(location.accuracy.toDouble()),
                        maxCandidates = 1200,
                        headingDeg = trafficSignHeadingDegrees,
                        speedKmh = filteredSpeedKmh,
                        horizontalAccuracyM = gpsHorizontalAccuracyM,
                        gpsSignalBars = gpsSignalBars,
                        matchContext = matchContext,
                        headingAccuracyDeg = location.bearingAccuracyDegrees.toDouble().takeIf { location.hasBearingAccuracy() },
                    )
                }
                if (!lookupToken.isCurrent(token)) return@submitBackgroundTask
                val activeCorrectionOverrideValue = applyActiveLocalSpeedCorrectionIfNeeded(result = result)
                val indexedCorrection = result.wayId?.let { wayId ->
                    localObservationStore.latestRuntimeApplicableCorrection(wayId, result.travelDirection)
                }
                val localOverrideValue = activeCorrectionOverrideValue ?: indexedCorrection?.canonicalValue
                val baseLimit = trafficSignBaseLimit(
                    localOverrideValue = localOverrideValue,
                    localCorrectionId = indexedCorrection?.observationId,
                    result = result,
                    countryCode = effectiveCountryCode ?: "ZZZ",
                )
                val evaluation = evaluateTrafficSignSources(
                    expectedLookupToken = token,
                    result = result,
                    location = location,
                    base = baseLimit,
                    bundleVersion = effectiveBundleVersion,
                    bundleSha256 = effectiveBundleSha256,
                    countryCode = effectiveCountryCode ?: "ZZZ",
                    localCorrectionRevision = indexedCorrection?.observationId,
                    headingDegrees = trafficSignHeadingDegrees,
                    matchedFixCount = matchContext?.matchedFixCount ?: 0,
                ) ?: return@submitBackgroundTask
                if (evaluation.invalidatedByCityEntry) {
                    appendRuntimeDiagnosticEvent(
                        event = "assertion_invalidated",
                        details = mapOf(
                            "reason" to "bundle_city_entry",
                            "baseSource" to baseLimit.source.wireValue,
                            "baseKmh" to baseLimit.resolution?.speedKmh,
                            "wayId" to result.wayId,
                        ),
                    )
                }
                val effectiveSpeed = evaluation.effective.resolution?.speedKmh
                val effectiveDisplayText = if (evaluation.effective.resolution?.kind == TrafficSignResolvedLimitKind.WALK) "Schritt" else null
                val unlimitedActive = evaluation.effective.resolution?.kind == TrafficSignResolvedLimitKind.UNLIMITED

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

                val committedEvaluation = lookupToken.mutateIfCurrent(token) {
                    wayMatchTracker.record(
                        result = result,
                        lat = location.latitude,
                        lon = location.longitude,
                        horizontalAccuracyM = gpsHorizontalAccuracyM,
                        gpsSignalBars = gpsSignalBars,
                        headingDeg = location.bearing.toDouble().takeIf { location.hasBearing() },
                        speedKmh = filteredSpeedKmh,
                        headingAccuracyDeg = location.bearingAccuracyDegrees.toDouble().takeIf { location.hasBearingAccuracy() },
                    )
                    evaluation
                } ?: return@submitBackgroundTask
                postState {
                    if (!lookupToken.isCurrent(token) ||
                        this@ConsumerSessionController.trafficSignGeneration.get() != committedEvaluation.generation ||
                        (committedEvaluation.tsrWasEnabled && (!trafficSignRecognitionEnabled || !this@ConsumerSessionController.isDriving))
                    ) {
                        this
                    } else copy(
                        speedLimitKmh = effectiveSpeed,
                        speedLimitDisplayText = effectiveDisplayText,
                        isUnlimitedSpeedLimitActive = unlimitedActive,
                        effectiveSpeedLimitSource = committedEvaluation.effective.source,
                        effectiveSpeedLimitReason = committedEvaluation.effective.presentationReason,
                        cameraSpeedLimitEvidence = committedEvaluation.effective.cameraEvidence,
                        trafficSignFinalConfidence = committedEvaluation.activatedPassage?.finalConfidence
                            ?: trafficSignFinalConfidence.takeIf { committedEvaluation.effective.cameraEvidence },
                        trafficSignAccumulatedSupport = committedEvaluation.activatedPassage?.finalAccumulatedSupport
                            ?: trafficSignAccumulatedSupport.takeIf { committedEvaluation.effective.cameraEvidence },
                        trafficSignGeneration = this@ConsumerSessionController.trafficSignGeneration.get(),
                        limitWayId = result.wayId,
                        limitStreetName = result.streetName,
                        limitStreetBaseName = result.streetBaseName,
                        limitStreetRef = result.streetRef,
                        limitCityName = result.cityName,
                        limitCityPlaceName = result.cityPlaceName,
                        limitCityDistrictName = result.cityDistrictName,
                        lastLookupInsideCity = result.insideCity,
                        lastLookupCitySource = result.citySource ?: "n/a",
                        lastLookupQueryMs = result.queryTimeMs,
                        lastLookupCandidateCount = result.candidateCount,
                        lastLookupSpeedCandidateCount = result.speedCandidateCount,
                        lastLookupNearestCandidateM = result.nearestCandidateDistanceM,
                        lastLookupNearestSpeedCandidateM = result.nearestSpeedCandidateDistanceM,
                        activeBundleVersion = effectiveBundleVersion,
                        activeDBPath = effectiveDBPath,

                        tunnelModeState = if (result.isTunnelSegment) TunnelModeState.ACTIVE else TunnelModeState.INACTIVE,
                        isLowSpeedMatchingRuleActive = result.usedWalkingTurnSwitch,
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                    )
                }
                mainHandler.post {
                    if (lookupToken.isCurrent(token)) {
                        maybeSpeakDrivingBanWarning()
                        maybeSpeakOverspeedWarning()
                    }
                }
            } catch (error: Exception) {
                appendRuntimeDiagnosticEvent(
                    event = "lookup_error",
                    details = mapOf(
                        "dbPath" to effectiveDBPath,
                        "fixId" to gpsFixCount,
                        "errorClass" to error.javaClass.name,
                        "error" to (error.message ?: error.javaClass.simpleName),
                    ),
                )
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
                        activeBundleVersion = effectiveBundleVersion,
                        activeDBPath = effectiveDBPath,

                        driveStatus = "location_error",
                        lastError = error.message ?: error.javaClass.simpleName,
                        gpsLogPath = gpsLogFile().absolutePath,
                        matchLogPath = matchLogFile().absolutePath,
                    )
                }
            }
        }
    }

    private fun consumeCoarseLocation(location: Location) {
        if (!location.latitude.isFinite() || !location.longitude.isFinite()) {
            return
        }
        val accuracy = location.accuracy.toDouble().takeIf { it.isFinite() && it >= 0.0 }
        val sequence = ++coarseLocationSequence
        updateState {
            copy(
                coarseLatitude = location.latitude,
                coarseLongitude = location.longitude,
                coarseHorizontalAccuracyM = accuracy,
                coarseLocationSource = "wifi_network",
            )
        }
        val dbPath = uiState.activeDBPath.takeIf { it.isNotBlank() && File(it).exists() } ?: return
        submitBackgroundTask {
            if (sequence != coarseLocationSequence) return@submitBackgroundTask
            val countryCode = normalizedCountryCode(bootstrapper.activeState()?.countryCode)
                ?: inferCountryCodeFromDBPath(dbPath)
            val context = runCatching {
                V3SpeedLimitLookup(
                    dbPath = dbPath,
                    countryCode = countryCode,
                    matchingModel = uiState.matcherDebugProfile.lookupModel,
                ).use { lookup -> lookup.lookupCityContext(location.latitude, location.longitude) }
            }.onFailure { error ->
                appendRuntimeDiagnosticEvent(
                    event = "coarse_city_lookup_error",
                    details = mapOf(
                        "lat" to location.latitude,
                        "lon" to location.longitude,
                        "dbPath" to dbPath,
                        "error" to (error.message ?: error.javaClass.simpleName),
                    ),
                )
            }.getOrNull() ?: return@submitBackgroundTask
            postState {
                if (sequence != coarseLocationSequence) this else copy(
                    coarseCityName = context.cityName,
                    coarseCityPlaceName = context.cityPlaceName,
                    coarseCityDistrictName = context.cityDistrictName,
                    coarseCitySource = context.citySource ?: "n/a",
                )
            }
        }
    }

    private fun maybeSpeakOverspeedWarning() {
        if (uiState.driveStatus != "running" || !uiState.audioAlertsEnabled || uiState.speedCaptureMode != SpeedCaptureModeState.IDLE || clock.millis() < confirmationToneUntilMs) {
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
            PenaltySeverity.MONEY_ONLY -> notice.moneyFineEUR?.let { "$it ${uiState.activePenaltyRules.currencyCode}" } ?: notice.title
            PenaltySeverity.POINTS_AND_FINE -> "${notice.penaltyPoints ?: ""} ${ConsumerMainScreenLogic.secondaryMetricText(uiState)}"
        }
        val now = System.currentTimeMillis()
        val changedSignificantly = speechText != lastAnnouncedSpeechText
        if (!changedSignificantly && now - lastAudioFeedbackAtMs < 8_000L) {
            return
        }
        if (textToSpeech?.isSpeaking == true) return
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
            ConsumerRuntimeText.DRIVING_BAN_ONE.text()
        } else {
            ConsumerRuntimeText.DRIVING_BAN_MONTHS.text(drivingBanMonths)
        }
        runCatching {
            appContext.getSystemService(VibratorManager::class.java)?.defaultVibrator?.vibrate(
                VibrationEffect.createWaveform(longArrayOf(0, 120, 80, 120), -1),
            )
        }
        if (uiState.audioAlertsEnabled && textToSpeech?.isSpeaking != true && clock.millis() >= confirmationToneUntilMs) {
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
                textToSpeech?.language = Locale.getDefault()
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
        textToSpeech?.language = Locale.getDefault()
        textToSpeech?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "youspeed-${System.currentTimeMillis()}")
    }

    private fun prepareSpeedCaptureRecognizerAndMaybeStart() {
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.PREPARING,
                speedCaptureTranscript = "",
                localObservationStatus = ConsumerRuntimeText.SPEECH_PREPARING.text(),
            )
        }
        if (uiState.germanSpeechModelState != GermanSpeechModelState.READY) {
            shouldResumeSpeedCaptureAfterSpeechModelReady = true
            ensureGermanSpeechModelPrepared(force = true, userInitiated = true)
            return
        }
        if (bundledVoskModel == null) {
            showSpeedCaptureFailure(reason = ConsumerRuntimeText.SPEECH_NOT_READY.text())
            return
        }
        startSpeedCaptureListening()
    }

    private fun startSpeedCapturePromptSpeech() {
        ensureTextToSpeech()
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.SPEAKING_PROMPT,
                speedCaptureTranscript = "",
                localObservationStatus = ConsumerRuntimeText.CORRECTION_PROMPT.text(),
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
        textToSpeech?.language = Locale.GERMANY
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
        val model = bundledVoskModel ?: return showSpeedCaptureFailure(reason = ConsumerRuntimeText.SPEECH_NOT_LOADED.text())
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        isSpeedCaptureResolved = false
        updateState {
            copy(
                speedCaptureMode = SpeedCaptureModeState.LISTENING,
                speedCaptureTranscript = "",
                localObservationStatus = ConsumerRuntimeText.SPEECH_LISTENING.text(),
            )
        }
        val session = runCatching {
            VoskSpeedCaptureSession(model, SpeedCaptureSpeech.voskGrammarJson)
        }.getOrElse {
            showSpeedCaptureFailure(reason = ConsumerRuntimeText.SPEECH_INIT_FAILED.text(it.message ?: it.javaClass.simpleName))
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
                        }
                    }

                    override fun onCompleted(transcripts: List<String>, source: String) {
                        finishSpeedCaptureListening(source = source, transcripts = transcripts)
                    }

                    override fun onError(message: String) {
                        showSpeedCaptureFailure(reason = ConsumerRuntimeText.SPEECH_FAILED.text(message))
                    }
                },
            )
        }.getOrElse {
            showSpeedCaptureFailure(reason = ConsumerRuntimeText.SPEECH_START_FAILED.text(it.message ?: it.javaClass.simpleName))
            return
        }
        if (!started) {
            showSpeedCaptureFailure(reason = ConsumerRuntimeText.SPEECH_ALREADY_ACTIVE.text())
        }
    }

    private fun finishSpeedCaptureListening(@Suppress("UNUSED_PARAMETER") source: String, transcripts: List<String> = emptyList()) {
        if (isSpeedCaptureResolved) {
            return
        }
        isSpeedCaptureResolved = true
        updateState { copy(speedCaptureMode = SpeedCaptureModeState.EVALUATING) }
        stopActiveSpeedCaptureRecognition(clearStatus = false)
        val candidates = transcripts
            .map(String::trim)
            .filter(String::isNotEmpty)
            .distinct()
        if (candidates.isEmpty()) {
            cancelSpeedCapture(reason = null)
            return
        }
        val selection = candidates.firstNotNullOfOrNull(SpeedCaptureSpeech::resolveSelection)
        if (selection != null) {
            persistSpeedCaptureSelection(selection)
            return
        }
        cancelSpeedCapture(reason = null)
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
        if (isDisposed.get()) {
            return
        }
        if (isGermanSpeechModelCheckInFlight) {
            return
        }
        if (!force && uiState.germanSpeechModelState == GermanSpeechModelState.READY) {
            return
        }
        isGermanSpeechModelCheckInFlight = true
        setGermanSpeechModelState(
            state = GermanSpeechModelState.DOWNLOADING,
            status = ConsumerRuntimeText.SPEECH_MODEL_PREPARING.text(),
            updateCaptureStatus = userInitiated || uiState.speedCaptureMode == SpeedCaptureModeState.PREPARING,
        )
        val submitted = submitBackgroundTask {
            runCatching { bundledVoskModelStore.prepareModel() }
                .onSuccess { handle ->
                    replaceBundledVoskModel(handle)
                    markGermanSpeechModelReady(ConsumerRuntimeText.SPEECH_MODEL_READY.text())
                    if (shouldResumeSpeedCaptureAfterSpeechModelReady) {
                        mainHandler.post { continuePendingSpeedCaptureIfPossible() }
                    }
                }
                .onFailure { error ->
                    val message = ConsumerRuntimeText.SPEECH_MODEL_PREPARATION_FAILED.text(error.message ?: error.javaClass.simpleName)
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
        if (!submitted) {
            isGermanSpeechModelCheckInFlight = false
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
                    localObservationStatus = ConsumerRuntimeText.MIC_PERMISSION_REQUESTED.text(),
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
                onboardingCompleted = preferences.getBoolean(OnboardingPolicy.COMPLETED_KEY, false),
                activeBundleVersion = prepared.activeBundleVersion,
                activeDBPath = prepared.activeDBPath,

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
                startupDetail = ConsumerRuntimeText.SPEECH_PREPARATION_FAILED.text(),
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
        confirmationToneUntilMs = clock.millis() + 1000
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
        activeLocalSpeedCorrection = ActiveLocalSpeedCorrection(
            wayId = wayId,
            maxspeedValue = selection.value,
            numericSpeedKmh = observation.newSpeedKmh,
        )
    }

    private fun applyActiveLocalSpeedCorrectionIfNeeded(result: SpeedLookupResult): String? {
        val correction = activeLocalSpeedCorrection ?: return null
        return when (LocalSpeedCorrectionPolicy.decide(correction.wayId, result.wayId)) {
            LocalSpeedCorrectionDecision.KEEP_WAITING -> null
            LocalSpeedCorrectionDecision.EXPIRE -> {
                activeLocalSpeedCorrection = null
                null
            }
            LocalSpeedCorrectionDecision.APPLY -> {
                localSpeedOverrideValuesByWayId = localSpeedOverrideValuesByWayId + (correction.wayId to correction.maxspeedValue)
                correction.numericSpeedKmh?.let { localSpeedOverridesByWayId = localSpeedOverridesByWayId + (correction.wayId to it) }
                correction.maxspeedValue
            }
        }
    }

    private fun trafficSignBaseLimit(
        localOverrideValue: String?,
        localCorrectionId: String?,
        result: SpeedLookupResult,
        countryCode: String,
    ): TrafficSignBaseLimit {
        val localResolution = resolvedLimitForCanonicalValue(localOverrideValue)
        if (localResolution != null) {
            return TrafficSignBaseLimit(
                resolution = localResolution,
                source = EffectiveSpeedLimitSource.LOCAL_CORRECTION,
                reason = "local_correction:${localCorrectionId ?: "session"}",
            )
        }
        val bundleResolution = when {
            result.isUnlimitedSpeedLimit &&
                normalizedCountryCode(countryCode) == "DEU" &&
                result.highway?.trim()?.lowercase(Locale.US) == "motorway" ->
                TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNLIMITED)
            result.speedLimitKmh != null ->
                TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, result.speedLimitKmh)
            else -> null
        }
        return TrafficSignBaseLimit(
            resolution = bundleResolution,
            source = if (bundleResolution == null) EffectiveSpeedLimitSource.NONE else EffectiveSpeedLimitSource.BUNDLE,
            reason = if (bundleResolution == null) "bundle_no_limit" else "bundle",
        )
    }

    private fun speedLimitFallbackAfterEnd(): TrafficSignResolvedLimit? =
        latestTrafficSignInsideCity?.let { insideCity ->
            TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, if (insideCity) 50 else 100)
        } ?: latestTrafficSignBase.resolution

    private fun resolvedLimitForCanonicalValue(value: String?): TrafficSignResolvedLimit? = when (
        val normalized = value?.trim()?.lowercase(Locale.US)
    ) {
        null, "" -> null
        "walk" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.WALK)
        "none" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNLIMITED)
        else -> normalized.toIntOrNull()?.takeIf { it > 0 }?.let {
            TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, it)
        }
    }

    private fun evaluateTrafficSignSources(
        expectedLookupToken: Long,
        result: SpeedLookupResult,
        location: Location,
        base: TrafficSignBaseLimit,
        bundleVersion: String,
        bundleSha256: String?,
        countryCode: String,
        localCorrectionRevision: String?,
        headingDegrees: Double?,
        matchedFixCount: Int,
    ): TrafficSignEvaluationOutcome? = lookupToken.mutateIfCurrent(expectedLookupToken) {
        synchronized(trafficSignStateLock) {
        var (evaluationGeneration, writePermitActive) = trafficSignGeneration.snapshot()
        val enteredCity = TrafficSignBundleContextPolicy.enteredCity(
            previousInsideCity = latestTrafficSignInsideCity,
            currentInsideCity = result.insideCity,
        )
        if (enteredCity) {
            evaluationGeneration = trafficSignGeneration.incrementAndGet(writePermitActive)
            trafficSignResolver.clear()
            latestTrafficSignContext = null
            latestResolverLocation = null
            latestTrafficSignDirection = TrafficSignTravelDirection.UNKNOWN
            resetTrafficSignTraversalLocked()
        }
        latestTrafficSignInsideCity = result.insideCity
        val tsrEnabledForEvaluation = writePermitActive && uiState.trafficSignRecognitionEnabled && isDriving
        val previousContext = latestTrafficSignContext
        val previousWayId = normalizeTrafficSignWayId(previousContext?.wayId)
        val reversed = previousWayId != null &&
            previousWayId == normalizeTrafficSignWayId(result.wayId) &&
            previousContext?.travelDirection != TrafficSignTravelDirection.UNKNOWN &&
            result.travelDirection != TrafficSignTravelDirection.UNKNOWN &&
            previousContext?.travelDirection != result.travelDirection
        val bundleRevision = "bundle:$bundleVersion"
        val bundleChanged = previousContext != null &&
            (previousContext.sourceSignature.bundleRevision != bundleRevision ||
                previousContext.bundleSha256 != bundleSha256)
        if (reversed || bundleChanged) {
            resetTrafficSignTraversalLocked()
            if (bundleChanged) trafficSignResolver.clear()
        }
        val traversal = trafficSignTraversalTracker.update(
            wayId = result.wayId,
            direction = result.travelDirection,
            continuityAvailable = result.routeRelationContinuityAvailable,
            continuityGroups = result.routeRelationGroupIds,
        )
        trafficSignTraversalEpoch = traversal.epoch
        val currentWayId = normalizeTrafficSignWayId(result.wayId)
        val matchedWayStable = matchedFixCount >= 1 && (
            (currentWayId != null && currentWayId == previousWayId) || traversal.continuouslyRelated
        )
        val context = TrafficSignDetectionContext(
            wayId = result.wayId,
            latitude = location.latitude,
            longitude = location.longitude,
            headingDegrees = headingDegrees ?: 0.0,
            travelDirection = result.travelDirection,
            sourceSignature = TrafficSignRuntimeSourceSignature(
                osmRevision = "$bundleRevision|way:${result.wayId ?: "none"}|maxspeed:${result.speedLimitKmh ?: "none"}",
                localCorrectionRevision = localCorrectionRevision,
            ),
            bundleSha256 = bundleSha256,
            countryCode = normalizedCountryCode(countryCode) ?: "DEU",
            routeRelationGroupIds = result.routeRelationGroupIds.toSet(),
            sourceRelationIds = result.sourceRelationIds.toSet(),
            continuityCapable = result.routeRelationContinuityAvailable,
            traversalEpoch = trafficSignTraversalEpoch,
            matchedWayStable = matchedWayStable,
            speedMetersPerSecond = location.speed.toDouble().takeIf { location.hasSpeed() && it.isFinite() && it >= 0.0 }
                ?: (uiState.currentSpeedKmh / 3.6).coerceAtLeast(0.0),
        )
        val distance = latestResolverLocation?.distanceTo(location)?.toDouble()?.takeIf { it.isFinite() && it >= 0.0 } ?: 0.0
        latestResolverLocation = Location(location)
        latestTrafficSignContext = context
        latestTrafficSignBase = base
        latestTrafficSignDirection = result.travelDirection
        updateTrafficSignRoadContextDebugStateLocked(context)
        val effective = if (tsrEnabledForEvaluation) {
            trafficSignResolver.reconcile(
                match = TrafficSignRoadMatch(
                    context = context.takeIf { !it.wayId.isNullOrBlank() },
                    matchedAtUtc = clock.instant(),
                    distanceFromPreviousM = distance,
                    stabilized = matchedWayStable,
                    traversalReversed = reversed,
                ),
                base = base,
            )
        } else {
            trafficSignResolver.clear()
            base.effective()
        }
            val outcome = TrafficSignEvaluationOutcome(
                effective = effective,
                // Capture one-shot outputs in the same lookup-token critical
                // section as resolver mutation. Persistence below also uses
                // this frozen outcome before the token can be superseded.
                activatedPassage = trafficSignResolver.takeNewlyActivatedEvent(),
                persistablePassage = trafficSignResolver.takeNewlyPersistableEvent(),
                generation = evaluationGeneration,
                tsrWasEnabled = tsrEnabledForEvaluation,
                invalidatedByCityEntry = enteredCity,
            )
            outcome.persistablePassage?.let { passage ->
                persistFinalizedTrafficSignPassage(
                    event = passage,
                    resolvedLimit = outcome.effective.resolution
                        ?.takeIf { outcome.activatedPassage?.finalizedEventId == passage.finalizedEventId }
                        ?: passage.resolution,
                )
            }
            outcome
        }
    }

    private fun resetTrafficSignTraversalLocked() {
        trafficSignTraversalTracker.reset()
        trafficSignTraversalEpoch = trafficSignTraversalTracker.epoch
    }

    private fun updateTrafficSignRoadContextDebugStateLocked(context: TrafficSignDetectionContext) {
        val invalid = !context.isValidForTrafficSignDebugging()
        if (uiState.trafficSignDebugRoadContextInvalid != invalid) {
            updateState { copy(trafficSignDebugRoadContextInvalid = invalid) }
        }
    }

    private fun normalizeTrafficSignWayId(raw: String?): String? = raw
        ?.trim()
        ?.takeIf { it.isNotEmpty() }
        ?.let { value ->
            value.toLongOrNull()?.toString()
                ?: value.toDoubleOrNull()
                    ?.takeIf { it.isFinite() && it % 1.0 == 0.0 }
                    ?.toLong()
                    ?.toString()
                ?: value
        }

    private fun hasLocationPermission(): Boolean {
        val fine = appContext.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = appContext.checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    private fun hasFineLocationPermission(): Boolean {
        return appContext.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasMicrophonePermission(): Boolean {
        return appContext.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasCameraPermission(): Boolean {
        return appContext.checkSelfPermission(android.Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
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
        reason: String = "unspecified",
    ): V3SpeedLimitLookup = synchronized(lookupServiceLock) {
        ensureLookupServiceLocked(
            dbPath = dbPath,
            preferredCountryCode = preferredCountryCode,
            matcherProfile = matcherProfile,
            reason = reason,
        )
    }

    private fun ensureLookupServiceLocked(
        dbPath: String,
        preferredCountryCode: String? = null,
        matcherProfile: MatcherDebugProfile = uiState.matcherDebugProfile,
        reason: String = "unspecified",
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
        closeLookupServiceLocked(reason = "ensure_lookup_service:$reason")
        return V3SpeedLimitLookup(
            dbPath,
            countryCode = resolvedCountryCode,
            matchingModel = matcherProfile.lookupModel,
        ).also {
            lookupService = it
            lookupServicePath = dbPath
            lookupServiceCountryCode = resolvedCountryCode
            lookupServiceMatcherProfile = matcherProfile
            appendRuntimeDiagnosticEvent(
                event = "lookup_service_opened",
                details = mapOf(
                    "reason" to reason,
                    "dbPath" to dbPath,
                    "countryCode" to resolvedCountryCode,
                    "matcherProfile" to matcherProfile.storageValue,
                ),
            )
        }
    }

    private fun replaceLookupService(
        dbPath: String?,
        preferredCountryCode: String? = null,
        matcherProfile: MatcherDebugProfile = uiState.matcherDebugProfile,
        reason: String = "unspecified",
    ) = synchronized(lookupServiceLock) {
        replaceLookupServiceLocked(
            dbPath = dbPath,
            preferredCountryCode = preferredCountryCode,
            matcherProfile = matcherProfile,
            reason = reason,
        )
    }

    private fun replaceLookupServiceLocked(
        dbPath: String?,
        preferredCountryCode: String? = null,
        matcherProfile: MatcherDebugProfile = uiState.matcherDebugProfile,
        reason: String = "unspecified",
    ) {
        if (dbPath.isNullOrBlank()) {
            closeLookupServiceLocked(reason = "replace_lookup_service_empty_path:$reason")
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
        closeLookupServiceLocked(reason = "replace_lookup_service:$reason")
        val opened = runCatching {
            lookupService = V3SpeedLimitLookup(
                dbPath,
                countryCode = resolvedCountryCode,
                matchingModel = matcherProfile.lookupModel,
            )
            lookupServicePath = dbPath
            lookupServiceCountryCode = resolvedCountryCode
            lookupServiceMatcherProfile = matcherProfile
        }
        opened.onSuccess {
            appendRuntimeDiagnosticEvent(
                event = "lookup_service_opened",
                details = mapOf(
                    "reason" to reason,
                    "dbPath" to dbPath,
                    "countryCode" to resolvedCountryCode,
                    "matcherProfile" to matcherProfile.storageValue,
                ),
            )
        }.onFailure {
            appendRuntimeDiagnosticEvent(
                event = "lookup_service_open_failed",
                details = mapOf(
                    "reason" to reason,
                    "dbPath" to dbPath,
                    "countryCode" to resolvedCountryCode,
                    "matcherProfile" to matcherProfile.storageValue,
                    "errorClass" to it.javaClass.name,
                    "error" to (it.message ?: it.javaClass.simpleName),
                ),
            )
            lookupService = null
            lookupServicePath = null
            lookupServiceCountryCode = null
            lookupServiceMatcherProfile = null
        }
    }

    private fun closeLookupService(reason: String = "unspecified") = synchronized(lookupServiceLock) {
        closeLookupServiceLocked(reason)
    }

    private fun closeLookupServiceLocked(reason: String = "unspecified") {
        if (lookupService != null) {
            appendRuntimeDiagnosticEvent(
                event = "lookup_service_closed",
                details = mapOf(
                    "reason" to reason,
                    "dbPath" to lookupServicePath,
                    "countryCode" to lookupServiceCountryCode,
                    "matcherProfile" to lookupServiceMatcherProfile?.storageValue,
                ),
            )
        }
        lookupService?.close()
        lookupService = null
        lookupServicePath = null
        lookupServiceCountryCode = null
        lookupServiceMatcherProfile = null
    }

    private fun bootstrapBundledSeedIfNeeded() {
        val active = bootstrapper.activeState()
        if (active?.dbPath?.isNotBlank() == true && File(active.dbPath).exists() && active.bundleVersion != "seed") {
            return
        }
        val assetName = BUNDLED_SEED_ASSET_NAME
        val bundledAssetSha = assetReader.openOrNull(assetName)?.use { input -> sha256Hex(input) } ?: return
        val seedDir = File(rootDir, "bundles/seed")
        if (!seedDir.exists()) {
            seedDir.mkdirs()
        }
        val seedFile = File(seedDir, BUNDLED_SEED_DB_FILE_NAME)
        val previousBundledAssetSha = preferences.getString(KEY_BUNDLED_SEED_ASSET_SHA256, null)
        val previousSeedBytes = seedFile.takeIf { it.exists() }?.length()
        val shouldRefreshSeed = !seedFile.exists() ||
            seedFile.length() == 0L ||
            previousBundledAssetSha != bundledAssetSha
        if (shouldRefreshSeed) {
            val tempSeedFile = File(seedDir, "$BUNDLED_SEED_DB_FILE_NAME.tmp")
            assetReader.openOrNull(assetName)?.use { input ->
                InflaterInputStream(BufferedInputStream(input)).use { inflater ->
                    FileOutputStream(tempSeedFile).use { output ->
                        inflater.copyTo(output)
                    }
                }
            } ?: return
            if (seedFile.exists()) {
                seedFile.delete()
            }
            if (!tempSeedFile.renameTo(seedFile)) {
                tempSeedFile.copyTo(seedFile, overwrite = true)
                tempSeedFile.delete()
            }
            preferences.edit().putString(KEY_BUNDLED_SEED_ASSET_SHA256, bundledAssetSha).apply()
            appendRuntimeDiagnosticEvent(
                event = "seed_refreshed",
                details = mapOf(
                    "assetName" to assetName,
                    "assetSha256" to bundledAssetSha,
                    "previousAssetSha256" to previousBundledAssetSha,
                    "previousDbBytes" to previousSeedBytes,
                    "dbPath" to seedFile.absolutePath,
                ),
            )
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
        if (shouldRefreshSeed || active?.dbSha256 != seedState.dbSha256 || active.dbPath != seedState.dbPath) {
            appendRuntimeDiagnosticEvent(
                event = "seed_activated",
                details = mapOf(
                    "dbPath" to seedState.dbPath,
                    "dbSha256" to seedState.dbSha256,
                    "dbBytes" to seedState.dbBytes,
                    "bundleVersion" to seedState.bundleVersion,
                    "assetSha256" to bundledAssetSha,
                ),
            )
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
        ensureRuntimeDiagnosticsLogExists()
    }

    private fun gpsLogFile(): File = File(rootDir, "logs/gps_fix_log.csv")

    private fun matchLogFile(): File = File(rootDir, "logs/drive_match_log.ndjson")

    private fun runtimeDiagnosticsLogFile(): File = File(rootDir, "logs/runtime_diagnostics.ndjson")

    private fun ensureRuntimeDiagnosticsLogExists() {
        runtimeDiagnosticsLogFile().parentFile?.mkdirs()
        if (!runtimeDiagnosticsLogFile().exists()) {
            runtimeDiagnosticsLogFile().writeText("")
        }
    }

    private fun installCrashObserverIfNeeded() {
        synchronized(ConsumerSessionController::class.java) {
            if (crashObserverInstalled) {
                return
            }
            val diagnosticsFile = runtimeDiagnosticsLogFile()
            val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
                appendRuntimeDiagnosticEvent(
                    file = diagnosticsFile,
                    timestamp = clock.instant(),
                    event = "uncaught_exception",
                    details = mapOf(
                        "pid" to Process.myPid(),
                        "thread" to thread.name,
                        "errorClass" to throwable.javaClass.name,
                        "error" to (throwable.message ?: throwable.javaClass.simpleName),
                        "stacktrace" to throwable.stackTraceToString().take(12000),
                    ),
                )
                previousHandler?.uncaughtException(thread, throwable)
            }
            crashObserverInstalled = true
        }
    }

    private fun appendRuntimeDiagnosticEvent(
        event: String,
        details: Map<String, Any?> = emptyMap(),
    ) {
        appendRuntimeDiagnosticEvent(
            file = runtimeDiagnosticsLogFile(),
            timestamp = clock.instant(),
            event = event,
            details = details,
        )
    }

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
            put("matchedWayStable", result.matchedWayStable)
            put("matchedFixCount", matchContext?.matchedFixCount ?: 0)
            matchContext?.preferredWayId?.let { put("preferredWayID", it) }
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
        return PenaltyCountryCodes.normalize(raw)
    }

    private fun sha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            updateDigest(digest, input)
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun sha256Hex(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        updateDigest(digest, input)
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun updateDigest(digest: MessageDigest, input: InputStream) {
        input.use {
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) {
                    break
                }
                digest.update(buffer, 0, read)
            }
        }
    }

    private fun normalizeOnboardingState(state: ConsumerUiState): ConsumerUiState {
        if (state.startupDataState != StartupDataState.READY || state.appScreenshotState != null) return state
        if (hasUsableOnboardingMap(state)) return state
        if (state.onboardingCompleted || state.onboardingStep != 0) {
            preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, false).putInt(OnboardingPolicy.STEP_KEY, 0).apply()
        }
        return state.copy(onboardingCompleted = false, onboardingStep = 0)
    }

    private fun updateState(transform: ConsumerUiState.() -> ConsumerUiState) {
        if (isDisposed.get()) {
            return
        }
        if (Looper.myLooper() != Looper.getMainLooper()) {
            postState(transform)
            return
        }
        uiState = normalizeOnboardingState(uiState.transform()).withCurrentTrafficSignDisplayGeneration(
            previousGeneration = uiState.trafficSignGeneration, currentGeneration = trafficSignGeneration.get(),
        )
    }

    private fun postState(transform: ConsumerUiState.() -> ConsumerUiState) {
        if (isDisposed.get()) {
            return
        }
        mainHandler.post {
            if (isDisposed.get()) {
                return@post
            }
            uiState = normalizeOnboardingState(uiState.transform()).withCurrentTrafficSignDisplayGeneration(
                previousGeneration = uiState.trafficSignGeneration, currentGeneration = trafficSignGeneration.get(),
            )
        }
    }

    private fun submitBackgroundTask(task: () -> Unit): Boolean {
        if (isDisposed.get() || executor.isShutdown || executor.isTerminated) {
            return false
        }
        return try {
            executor.execute {
                if (!isDisposed.get()) {
                    task()
                }
            }
            true
        } catch (_: RejectedExecutionException) {
            false
        }
    }

    companion object {
        @Volatile private var crashObserverInstalled = false
        private const val KEY_AUDIO_ALERT_THRESHOLD = "youspeed.audio_alert_threshold_kmh"
        private const val KEY_AUDIO_ALERTS_ENABLED = "youspeed.audio_alerts_enabled"
        private const val KEY_OTHER_TRAFFIC_SIGN_DISPLAY_ENABLED = "youspeed.other_traffic_sign_display_enabled"
        private const val KEY_TRAFFIC_SIGN_RECOGNITION_ENABLED = "youspeed.traffic_sign_recognition_enabled"
        private const val KEY_PANORAMAX_CAPTURE_ENABLED = "youspeed.panoramax_capture_enabled"
        private const val KEY_BUNDLED_SEED_ASSET_SHA256 = "youspeed.bundled_seed_asset_sha256"
        private val VERIFIED_SHA256 = Regex("^[a-f0-9]{64}$")
        private const val KEY_HIDE_WELCOME = "youspeed.hide_welcome_screen"
        private const val KEY_MATCHER_DEBUG_PROFILE = "youspeed.matcher_debug_profile"
        private const val KEY_MATCHER_DEBUG_PROFILE_FORCED_VERSION = "youspeed.matcher_debug_profile_forced_version"
        private const val DRIVING_BAN_WARNING_REMINDER_MS = 24_000L
        private const val BUNDLED_SEED_ASSET_NAME = "karlsruhe-regbez_speeds.sqlite.zlib"
        private const val BUNDLED_SEED_DB_FILE_NAME = "karlsruhe-regbez_speeds.sqlite"
        private const val DERIVED_SPEED_COMPUTATION_MAX_WINDOW_MS = 4_500L
        private const val DERIVED_SPEED_COMPUTATION_MIN_WINDOW_SECONDS = 2.0
        private const val LOW_SPEED_DERIVED_FALLBACK_THRESHOLD_KMH = 7.0
        private const val TRAFFIC_SIGN_INFERENCE_LOG_INTERVAL_MS = 1_000L
        private const val GPS_LOG_HEADER = "fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m,vacc_m,bearing_deg,status,way_id,street_name,city_name,inside_city,city_source,speed_limit_kmh,query_ms,candidate_count,speed_candidate_count,nearest_candidate_m,nearest_speed_candidate_m,error\n"

        internal fun resetDrivingLogFiles(gpsLogFile: File, matchLogFile: File) {
            gpsLogFile.parentFile?.mkdirs()
            gpsLogFile.writeText(GPS_LOG_HEADER)
            matchLogFile.parentFile?.mkdirs()
            matchLogFile.writeText("")
        }

        private fun appendRuntimeDiagnosticEvent(
            file: File,
            timestamp: Instant,
            event: String,
            details: Map<String, Any?> = emptyMap(),
        ) {
            runCatching {
                file.parentFile?.mkdirs()
                if (!file.exists()) {
                    file.writeText("")
                }
                val entry = JSONObject().apply {
                    put("timestampUTC", timestamp.toString())
                    put("event", event)
                    details.forEach { (key, value) ->
                        if (value != null) {
                            put(key, value)
                        }
                    }
                }
                file.appendText(entry.toString() + "\n")
            }
        }

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

        internal fun derivedSpeedKmh(
            distanceM: Double,
            elapsedSeconds: Double,
            accuracyAllowanceM: Double = 0.0,
        ): Double {
            if (!distanceM.isFinite() || distanceM <= 0.0 || !elapsedSeconds.isFinite() || elapsedSeconds <= 0.0) {
                return 0.0
            }
            val adjustedDistanceM = max(0.0, distanceM - max(0.0, accuracyAllowanceM))
            if (adjustedDistanceM <= 0.0) {
                return 0.0
            }
            return (adjustedDistanceM / elapsedSeconds) * 3.6
        }

        @Suppress("UNUSED_PARAMETER")
        internal fun filteredDisplaySpeedKmh(
            rawSpeedKmh: Double,
            fallbackDerivedSpeedKmh: Double = 0.0,
            speedAccuracyKmh: Double?,
            previousDisplaySpeedKmh: Double,
        ): Double {
            val normalizedRawSpeedKmh = if (rawSpeedKmh.isFinite() && rawSpeedKmh > 0.0) rawSpeedKmh else 0.0
            val normalizedFallbackDerivedSpeedKmh = if (fallbackDerivedSpeedKmh.isFinite() && fallbackDerivedSpeedKmh > 0.0) {
                fallbackDerivedSpeedKmh
            } else {
                0.0
            }
            if (normalizedRawSpeedKmh < LOW_SPEED_DERIVED_FALLBACK_THRESHOLD_KMH) {
                return normalizedFallbackDerivedSpeedKmh
            }
            return normalizedRawSpeedKmh
        }

        internal fun trafficSignHeadingDegrees(
            reportedBearingDegrees: Double?,
            previousLatitude: Double?,
            previousLongitude: Double?,
            currentLatitude: Double,
            currentLongitude: Double,
        ): Double? {
            if (reportedBearingDegrees != null && reportedBearingDegrees.isFinite() &&
                reportedBearingDegrees >= 0.0 && reportedBearingDegrees < 360.0
            ) {
                return reportedBearingDegrees
            }
            if (previousLatitude == null || previousLongitude == null ||
                !previousLatitude.isFinite() || !previousLongitude.isFinite() ||
                !currentLatitude.isFinite() || !currentLongitude.isFinite() ||
                (previousLatitude == currentLatitude && previousLongitude == currentLongitude)
            ) {
                return null
            }
            val startLatitudeRadians = Math.toRadians(previousLatitude)
            val endLatitudeRadians = Math.toRadians(currentLatitude)
            val longitudeDeltaRadians = Math.toRadians(currentLongitude - previousLongitude)
            val y = sin(longitudeDeltaRadians) * cos(endLatitudeRadians)
            val x = cos(startLatitudeRadians) * sin(endLatitudeRadians) -
                sin(startLatitudeRadians) * cos(endLatitudeRadians) * cos(longitudeDeltaRadians)
            return (Math.toDegrees(atan2(y, x)) + 360.0) % 360.0
        }
    }
}

private class AndroidAssetReader(
    private val context: Context,
) : AppAssetReader {
    override fun readText(name: String): String {
        return context.assets.open(name).bufferedReader().use { it.readText() }
    }

    override fun readTextOrNull(name: String): String? {
        return runCatching { readText(name) }.getOrNull()
    }

    fun readTextOrEmpty(name: String): String = readTextOrNull(name).orEmpty()

    override fun openOrNull(name: String): InputStream? {
        return runCatching { context.assets.open(name) }.getOrNull()
    }

    override fun listOrNull(path: String): List<String>? {
        return runCatching { context.assets.list(path)?.toList().orEmpty() }.getOrNull()
    }
}

private fun Locale.getDisplayCountryForCode(code: String): String {
    return if (code.length == 2) {
        Locale("", code.uppercase(Locale.US)).getDisplayCountry(this)
    } else {
        ""
    }
}

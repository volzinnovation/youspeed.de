package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.MediaMetadataRetriever
import android.os.Debug
import android.os.Build
import android.os.BatteryManager
import android.provider.Settings
import android.os.PowerManager
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import androidx.camera.view.PreviewView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
import java.io.RandomAccessFile
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in physical-camera soak. A stationary scene measures workload, not road accuracy. */
@RunWith(AndroidJUnit4::class)
class LaneFullWorkloadInstrumentedTest {
    @get:Rule val permissions: GrantPermissionRule = GrantPermissionRule.grant(
        Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION)

    @Test fun sustainedCameraRecognitionLanesMovieAndDisplay() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue("Opt in with -e laneFullWorkload true", arguments.getString("laneFullWorkload") == "true")
        val seconds = (arguments.getString("laneFullWorkloadSeconds")?.toLongOrNull() ?: 600L).coerceIn(30, 1800)
        val includePhotos = arguments.getString("laneFullWorkloadPhotos") != "false"
        val includeLanes = arguments.getString("laneFullWorkloadLanes") != "false"
        val requireStructuredCadence = arguments.getString("laneRequireStructuredCadence") == "true"
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val installedPackage = context.packageManager.getPackageInfo(context.packageName, 0)
        val initialBattery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        assumeTrue("At least 6 GB free device storage required", context.filesDir.usableSpace >= 6_000_000_000L)
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val previous = preferences.all
        val ownerMovies = File(context.filesDir, "dashcam")
        val existing = ownerMovies.listFiles().orEmpty().filter { it.isFile }.associate { it.name to it.length() }
        assumeTrue("Owner movie library must be within normal startup retention before testing",
            existing.values.sum() <= DriveRecorderPolicy.MOVIE_LIBRARY_LIMIT_BYTES)
        val originalMovieHashes = existing.keys.associateWith { PanoramaxQueueStore.sha256(File(ownerMovies, it)) }
        val queue = PanoramaxQueueStore(context)
        val existingBatches = queue.listBatches().map { it.batchId }.toSet()
        var photosArchived = false
        val originalPhotos = File(context.noBackupFilesDir, "panoramax").walkTopDown()
            .filter { it.isFile && it.extension == "jpg" }.associateWith { it.length() }
        val runId = "lane-full-workload-${System.currentTimeMillis()}"
        val output = File(context.filesDir, "lane-evaluation/$runId").apply { mkdirs() }
        val movies = File(output, "movies").apply { mkdirs() }
        File(output, "owner-movies-before.json").writeText(org.json.JSONArray(existing.map { (name, bytes) ->
            JSONObject().put("name", name).put("bytes", bytes).put("sha256", originalMovieHashes.getValue(name))
        }).toString(2))
        val samples = File(output, "samples.ndjson")
        val events = File(output, "runtime.ndjson")
        val summary = JSONObject().put("schemaVersion", 1).put("runId", runId)
            .put("scene", "stationary_physical_camera").put("syntheticLocation", false)
            .put("requestedSeconds", seconds).put("sampleIntervalSeconds", 1).put("panoramaxEnabled", includePhotos).put("lanesEnabled", includeLanes)
            .put("buildNumber", installedPackage.longVersionCode).put("versionName", installedPackage.versionName)
            .put("testCompileBuildNumber", BuildConfig.VERSION_CODE)
            .put("runLabel", arguments.getString("laneFullWorkloadLabel") ?: "current-installed-app")
            .put("harnessSourceSha256", arguments.getString("laneFullWorkloadHarnessSha256"))
            .put("harnessApkSha256", arguments.getString("laneFullWorkloadApkSha256"))
            .put("deviceManufacturer", Build.MANUFACTURER).put("deviceModel", Build.MODEL)
            .put("osRelease", Build.VERSION.RELEASE).put("sdkInt", Build.VERSION.SDK_INT)
            .put("buildFingerprint", Build.FINGERPRINT)
            .put("initialBatteryLevel", initialBattery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1))
            .put("initialBatteryScale", initialBattery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1))
            .put("initialBatteryPlugged", initialBattery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1))
            .put("initialBatteryStatus", initialBattery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1))
            .put("initialBatteryTemperatureTenthsC", initialBattery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1))
            .put("initialThermalStatus", context.getSystemService(PowerManager::class.java).currentThermalStatus)
            .put("initialScreenBrightness", Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS, -1))
            .put("screenBrightnessMode", Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS_MODE, -1))
            .put("complete", false)
        var logPosition = 0L
        var laneFrames = 0
        var inferenceFrames = 0
        var structuredCameraCadenceEvents = 0
        var structuredLaneCadenceEvents = 0
        var thermalPausedSamples = 0
        var peakRssBytes = 0L
        var previewSamples = 0
        var sampleCount = 0
        var phase = "warmup"
        var diagnosticFile: File? = null
        var thermalPausedSeconds = 0.0
        var maxLaneGapSeconds = 0.0
        var maxInferenceGapSeconds = 0.0
        var photosAtSoakStart = 0
        var photosAtSoakEnd = 0
        fun testPhotoCount() = queue.listBatches().filter { it.batchId !in existingBatches }.sumOf { it.items.size }
        fun drainEvents() {
            val log = diagnosticFile?.takeIf { it.isFile } ?: return
            RandomAccessFile(log, "r").use { reader ->
                if (reader.length() < logPosition) logPosition = 0
                reader.seek(logPosition)
                // Bound each sample's diagnostic I/O even on an unusually noisy drive.
                val end = minOf(reader.length(), logPosition + 1_048_576L)
                while (reader.filePointer < end) {
                    val start = reader.filePointer
                    val rawLine = reader.readLine() ?: break
                    val line = String(rawLine.toByteArray(Charsets.ISO_8859_1), Charsets.UTF_8)
                    if (reader.filePointer == reader.length() && !line.endsWith("}")) {
                        reader.seek(start); break // Writer has not finished this line.
                    }
                    events.appendText(line + "\n")
                    val parsed = runCatching { JSONObject(line) }.getOrNull()
                    val event = parsed?.optString("event")
                    if (requireStructuredCadence && parsed != null && event == "traffic_sign_camera_analysis" && parsed.optString("stage") == "cadence") {
                        listOf("counts", "deliveryInterval", "cameraHold", "copiedInputCameraHold", "lanes").forEach {
                            assertTrue("Camera cadence $it is a JSON object", parsed.opt(it) is JSONObject)
                        }
                        assertTrue("Nested lane delivery is a JSON object", parsed.getJSONObject("lanes").opt("delivery") is JSONObject)
                        structuredCameraCadenceEvents++
                    }
                    if (requireStructuredCadence && parsed != null && event == "lane_preview_performance") {
                        assertTrue("Lane cadence is a JSON object", parsed.opt("laneCadence") is JSONObject)
                        assertTrue("Nested lane admission is a JSON object", parsed.getJSONObject("laneCadence").opt("admitted") is JSONObject)
                        structuredLaneCadenceEvents++
                    }
                    if (phase != "finalization") {
                        if (event == "lane_preview_frame") laneFrames++
                        if (event == "traffic_sign_inference") inferenceFrames++
                    }
                }
                logPosition = reader.filePointer
            }
        }
        try {
            assertTrue(preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true)
                .putBoolean(DebugLogPersistence.PREFERENCE_KEY, true)
                .putBoolean("youspeed.panoramax.unlimited_storage", true)
                .putBoolean("youspeed.panoramax.delete_uploaded", false).commit())
            ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)).use { scenario ->
                fun act(block: (ConsumerSessionController) -> Unit) = scenario.onActivity { block(it.sessionController) }
                fun state(): ConsumerUiState {
                    lateinit var value: ConsumerUiState
                    act { value = it.uiState }; return value
                }
                fun awaitState(label: String, condition: (ConsumerUiState) -> Boolean) {
                    val deadline = SystemClock.elapsedRealtime() + 60_000
                    while (SystemClock.elapsedRealtime() < deadline) {
                        if (condition(state())) return
                        SystemClock.sleep(100)
                    }
                    fail("$label: ${state().trafficSignCameraRuntimeDetail}; ${state().driveRecorderState}")
                }
                try {
                    awaitState("Startup log review completes its scan") {
                        it.startupLogReviewState in setOf(StartupLogReviewState.CHOICE, StartupLogReviewState.COMPLETE, StartupLogReviewState.FAILED)
                    }
                    act { it.keepStartupLogs() }
                    awaitState("Preserve existing logs") { it.startupLogReviewState == StartupLogReviewState.COMPLETE }
                    awaitState("Usable installed map and storage maintenance") {
                        it.startupDataState == StartupDataState.READY && !it.panoramaxMaintenanceInProgress && it.panoramaxActiveUploadBatchIds.isEmpty()
                    }
                    act {
                        assertTrue("Full workload requires the existing installed map", it.hasUsableOnboardingMap())
                        it.setTestDashcamOutputDirectory(movies)
                        diagnosticFile = File(it.uiState.runtimeDiagnosticsLogPath)
                        logPosition = diagnosticFile?.length() ?: 0L
                        it.setDebugLoggingEnabled(true)
                        it.setShowDetectedLanes(includeLanes)
                        it.setTrafficSignRecognitionEnabled(true)
                        it.setTrafficSignRecognitionIndependentEnabled(true)
                        it.setPanoramaxCaptureEnabled(includePhotos)
                        it.startDriving()
                        it.toggleDriveRecorder()
                    }
                    awaitState("Movie has actual encoder output") {
                        it.driveRecorderDashcamActive && movies.listFiles().orEmpty()
                            .any { file -> file.name !in existing && file.length() > 1024 }
                    }
                    awaitState("Actual lane worker and TSR inference (requires a real location context)") {
                        drainEvents()
                        (!includeLanes || laneFrames > 0) && inferenceFrames > 0 && it.trafficSignCameraRuntimeState == TrafficSignCameraRuntimeState.ACTIVE
                    }
                    summary.put("warmupLaneFrames", laneFrames).put("warmupInferenceFrames", inferenceFrames)
                    photosAtSoakStart = testPhotoCount()
                    summary.put("warmupPhotoCount", photosAtSoakStart)
                    phase = "soak"
                    laneFrames = 0; inferenceFrames = 0
                    val start = SystemClock.elapsedRealtime()
                    var previousSample = start
                    var previousPaused = false
                    var lastLaneProgress = start
                    var lastInferenceProgress = start
                    var priorLaneCount = 0
                    var priorInferenceCount = 0
                    val thermal = context.getSystemService(PowerManager::class.java)
                    while (SystemClock.elapsedRealtime() - start < seconds * 1000) {
                        val now = SystemClock.elapsedRealtime()
                        if (previousPaused) thermalPausedSeconds += (now - previousSample) / 1000.0
                        previousSample = now
                        var preview = false
                        lateinit var current: ConsumerUiState
                        lateinit var lanes: LaneRuntimeSnapshot
                        scenario.onActivity { activity ->
                            current = activity.sessionController.uiState
                            lanes = activity.sessionController.laneRuntimeSnapshot
                            preview = hasVisiblePreview(activity.window.decorView)
                        }
                        val rss = File("/proc/self/status").useLines { lines ->
                            lines.firstOrNull { it.startsWith("VmRSS:") }?.trim()?.split(Regex("\\s+"))
                                ?.getOrNull(1)?.toLongOrNull()?.times(1024) ?: 0L
                        }
                        peakRssBytes = maxOf(peakRssBytes, rss)
                        if (preview) previewSamples++
                        previousPaused = thermal.currentThermalStatus >= PowerManager.THERMAL_STATUS_SEVERE
                        if (previousPaused) thermalPausedSamples++
                        sampleCount++
                        samples.appendText(JSONObject().put("elapsedSeconds", (SystemClock.elapsedRealtime() - start) / 1000.0)
                            .put("thermalStatus", thermal.currentThermalStatus).put("rssBytes", rss)
                            .put("screenBrightness", Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS, -1))
                            .put("nativeHeapBytes", Debug.getNativeHeapAllocatedSize())
                            .put("javaHeapBytes", Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory())
                            .put("previewVisible", preview).put("movieActive", current.driveRecorderDashcamActive)
                            .put("cameraState", current.trafficSignCameraRuntimeState.name)
                            .put("recognitionEnabled", current.trafficSignRecognitionEnabled)
                            .put("recognitionUnavailable", current.trafficSignRecognitionUnavailable)
                            .put("lanesEnabled", current.showDetectedLanes).put("laneState", lanes.state.name)
                            .put("laneProcessedFrames", lanes.processedFrames).put("lanePreparationMs", lanes.detectionMs)
                            .put("photoCount", current.panoramaxCaptureCount)
                            .put("movieBytes", movies.listFiles().orEmpty().filter { it.name !in existing }.sumOf { it.length() })
                            .toString() + "\n")
                        drainEvents()
                        if (laneFrames != priorLaneCount || previousPaused) lastLaneProgress = now
                        if (inferenceFrames != priorInferenceCount || thermal.currentThermalStatus >= PowerManager.THERMAL_STATUS_CRITICAL) lastInferenceProgress = now
                        priorLaneCount = laneFrames; priorInferenceCount = inferenceFrames
                        maxLaneGapSeconds = maxOf(maxLaneGapSeconds, (now - lastLaneProgress) / 1000.0)
                        maxInferenceGapSeconds = maxOf(maxInferenceGapSeconds, (now - lastInferenceProgress) / 1000.0)
                        if (includeLanes) assertTrue("Lane processing continues outside thermal pauses", now - lastLaneProgress < 15_000)
                        else assertFalse("Lane option remains off while dashcam records", current.showDetectedLanes)
                        assertTrue("TSR inference continues outside thermal pauses", now - lastInferenceProgress < 30_000)
                        assertTrue("Storage remains available", context.filesDir.usableSpace >= 750_000_000L)
                        assertTrue("Dashcam remains active during full workload", current.driveRecorderDashcamActive)
                        assertFalse("Recognition backend remains healthy", current.trafficSignRecognitionUnavailable)
                        SystemClock.sleep(1000)
                    }
                    if (previousPaused) thermalPausedSeconds += (SystemClock.elapsedRealtime() - previousSample) / 1000.0
                    photosAtSoakEnd = testPhotoCount()
                    summary.put("elapsedSeconds", (SystemClock.elapsedRealtime() - start) / 1000.0)
                        .put("photoCount", state().panoramaxCaptureCount)
                        .put("soakPhotoCaptureCount", (photosAtSoakEnd - photosAtSoakStart).coerceAtLeast(0))
                        .put("photoEncoderExercisedDuringSoak", photosAtSoakEnd > photosAtSoakStart)
                        .put("photoWorkloadQualification", if (photosAtSoakEnd > photosAtSoakStart)
                            "Actual eligible still captures observed; stationary cadence differs from driving"
                            else "No still captured during soak; photo-encoder thermal load not validated")
                } finally {
                    phase = "finalization"
                    act { it.stopDriving() }
                    awaitState("Movie finalized after drive stop") {
                        !it.driveRecorderDashcamActive && !it.driveRecorderDashcamTransitioning
                    }
                    awaitState("Photo session sealed") {
                        queue.listBatches().filter { it.batchId !in existingBatches }.none { it.state == PanoramaxBatchState.CAPTURING }
                    }
                    act { it.setTestDashcamOutputDirectory(null) }
                    drainEvents()
                }
            }
            val recordings = movies.listFiles().orEmpty().filter { it.name !in existing && it.extension == "mp4" }
            var durationMs = 0L
            recordings.forEach { file ->
                val metadata = MediaMetadataRetriever()
                try {
                    metadata.setDataSource(file.absolutePath)
                    durationMs += metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
                } finally { metadata.release() }
            }
            summary.put("movieDurationMs", durationMs).put("movies", org.json.JSONArray(recordings.map { it.name }))
            assertTrue("Recorded movie covers the sustained test", durationMs >= seconds * 900)
            if (includeLanes) assertTrue("Actual lane preparation ran", laneFrames > 0)
            else assertEquals("No preview lane frames while disabled", 0, laneFrames)
            assertTrue("Actual TSR inference ran", inferenceFrames > 0)
            assertTrue("Preview remained visible", previewSamples >= sampleCount * 0.95)
            if (requireStructuredCadence) {
                assertTrue("Camera cadence producer emitted structured diagnostics", structuredCameraCadenceEvents > 0)
                assertTrue("Lane cadence producer emitted structured diagnostics", structuredLaneCadenceEvents > 0)
            }
            summary.put("complete", true)
        } finally {
            summary.put("samples", sampleCount).put("peakSampledRssBytes", peakRssBytes)
                .put("structuredCameraCadenceEvents", structuredCameraCadenceEvents)
                .put("structuredLaneCadenceEvents", structuredLaneCadenceEvents)
                .put("thermalPausedSamples", thermalPausedSamples).put("laneThermalPausedSeconds", thermalPausedSeconds)
                .put("maxLaneEligibleGapSeconds", maxLaneGapSeconds).put("maxInferenceEligibleGapSeconds", maxInferenceGapSeconds)
                .put("laneFrames", laneFrames)
                .put("inferenceFrames", inferenceFrames).put("previewVisibleSamples", previewSamples)
            summary.put("newTestPhotoCount", testPhotoCount())
            // Archive only this test's photos outside the user's storage quota, then
            // remove their queue entries. This prevents later retention from evicting owner media.
            try {
                val newBatches = queue.listBatches().filter { it.batchId !in existingBatches }
                val encode = PanoramaxQueueStore::class.java.getDeclaredMethod("encode", PanoramaxBatchRecord::class.java)
                    .apply { isAccessible = true }
                for (batch in newBatches) {
                    check(batch.state != PanoramaxBatchState.CAPTURING) { "Test photo capture has not finalized" }
                    val archive = File(output, "photos/${batch.batchId}").apply { mkdirs() }
                    File(archive, "batch.json").writeText(checkNotNull(encode.invoke(queue, batch)).toString())
                    for (item in batch.items) {
                        val source = queue.originalFile(item)
                        val retained = File(archive, "${item.itemId}.jpg")
                        source.copyTo(retained)
                        check(PanoramaxQueueStore.sha256(source) == PanoramaxQueueStore.sha256(retained)) { "Photo archive verification failed" }
                    }
                    queue.deleteItems(batch.batchId, batch.items.map { it.itemId }.toSet())
                }
                photosArchived = queue.listBatches().filter { it.batchId !in existingBatches }.all { it.items.isEmpty() }
            } catch (failure: Throwable) {
                summary.put("photoArchiveFailure", failure.toString()).put("complete", false)
            }
            summary.put("testPhotosArchivedOutsideQueue", photosArchived)
            // Keep the test movie/evidence for review, and restore the owner's exact preferences.
            val editor = preferences.edit().clear()
            previous.forEach { (key, value) -> when (value) {
                is Boolean -> editor.putBoolean(key, value)
                is String -> editor.putString(key, value)
                is Int -> editor.putInt(key, value)
                is Long -> editor.putLong(key, value)
                is Float -> editor.putFloat(key, value)
                is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
            } }
            if (!photosArchived) {
                // Failed evidence archival must not enable deletion of the owner's media.
                editor.putBoolean("youspeed.panoramax.unlimited_storage", true)
                    .putBoolean("youspeed.panoramax.delete_uploaded", false)
            }
            val preferencesRestored = editor.commit() && photosArchived
            summary.put("preferencesRestored", preferencesRestored)
            if (!preferencesRestored) summary.put("complete", false)
            val ownerMovieAudit = existing.map { (name, bytes) ->
                val file = File(ownerMovies, name)
                val preserved = file.isFile && file.length() == bytes && PanoramaxQueueStore.sha256(file) == originalMovieHashes[name]
                JSONObject().put("name", name).put("expectedBytes", bytes).put("expectedSha256", originalMovieHashes[name])
                    .put("actualBytes", file.length()).put("preserved", preserved)
            }
            summary.put("ownerMovieAudit", org.json.JSONArray(ownerMovieAudit))
            val ownerMediaPreserved = ownerMovieAudit.all { it.getBoolean("preserved") } &&
                originalPhotos.all { (file, bytes) -> file.length() == bytes }
            summary.put("ownerMediaPreserved", ownerMediaPreserved)
            if (!ownerMediaPreserved) summary.put("complete", false)
            File(output, "summary.json").writeText(summary.toString(2))
            assertTrue("Archive test photos and restore original preferences", preferencesRestored)
            ownerMovieAudit.forEach { assertTrue("Preserve owner's movie ${it.getString("name")}", it.getBoolean("preserved")) }
            originalPhotos.forEach { (file, bytes) -> assertEquals("Preserve owner's photo ${file.name}", bytes, file.length()) }
        }
    }

    private fun hasVisiblePreview(view: View): Boolean =
        (view is PreviewView && view.isAttachedToWindow && view.isShown && view.alpha > 0 && view.width > 0 && view.height > 0 && view.previewStreamState.value == PreviewView.StreamState.STREAMING) ||
            (view is ViewGroup && (0 until view.childCount).any { hasVisiblePreview(view.getChildAt(it)) })
}

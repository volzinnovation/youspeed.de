package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.location.Location
import android.location.LocationManager
import android.media.MediaMetadataRetriever
import android.os.SystemClock
import android.util.Log
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import androidx.camera.view.PreviewView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises the actual CameraX graph; catches regressions that state-policy tests cannot. */
@RunWith(AndroidJUnit4::class)
class DriveRecorderInstrumentedTest {
    private val injectedLatitudes = mutableListOf<Double>()
    @get:Rule val permissions: GrantPermissionRule = GrantPermissionRule.grant(
        Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.RECORD_AUDIO,
    )

    @Test fun liveButtonsFinalizeMovieAndPreservePhotoSession() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val previous = preferences.all
        val existingMovies = File(context.filesDir, "dashcam").listFiles().orEmpty().map { it.name }.toSet()
        val queue = PanoramaxQueueStore(context)
        val existingBatches = queue.listBatches().map { it.batchId }.toSet()
        val existingMedia = listOf(File(context.filesDir, "dashcam"), File(context.noBackupFilesDir, "panoramax"))
            .flatMap { it.walkTopDown().filter { file -> file.isFile && (file.extension == "jpg" || file.extension == "mp4") }.toList() }
            .associateWith { it.length() }
        val bundleRoot = File(context.filesDir, "bundle")
        val activeStateFile = File(bundleRoot, "active_bundle.json")
        val previousActiveState = activeStateFile.takeIf { it.isFile }?.readBytes()
        var fixtureDatabase: File? = null
        var fixtureDirectory: File? = null
        var replacedActiveState = false
        try {
            val existingActive = BundleBootstrapper(bundleRoot, HttpUrlFetcher()).activeState()
            if (existingActive == null || !OnboardingPolicy.hasUsableMap(existingActive.bundleVersion,
                    File(existingActive.dbPath).isFile)) {
                // A real local road database satisfies setup exactly as a downloaded
                // map does. Do not weaken production onboarding for camera tests.
                val directory = File(bundleRoot, "bundles/recorder-map-${UUID.randomUUID()}").apply { mkdirs() }
                fixtureDirectory = directory
                val fixture = File(directory, "roads.sqlite")
                fixtureDatabase = fixture
                createRecorderMapFixture(fixture)
                val active = ActiveBundleState(
                    region = "recorder-test-region",
                    countryCode = "DEU",
                    bundleVersion = "2026-09-11-recorder-fixture",
                    dbFileName = fixture.name,
                    dbPath = fixture.absolutePath,
                    dbSha256 = sha256(fixture),
                    dbBytes = fixture.length(),
                    manifestUrl = "asset://shared/matcher/fixtures/straight-linked.sql",
                    activatedAtUTC = Instant.now().toString(),
                )
                assertTrue(bundleRoot.isDirectory || bundleRoot.mkdirs())
                // Keep the synthetic map usable across real GPS callbacks and injected capture fixes.
                writeCoverageFixtureManifest(fixture, active.region, active.bundleVersion, -180.0, -90.0, 180.0, 90.0)
                replacedActiveState = true
                activeStateFile.writeText(ContractJson.encodeActiveBundleState(active))
                assertEquals(active, BundleBootstrapper(bundleRoot, HttpUrlFetcher()).activeState())
            }
            assertTrue(preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true)
                .putBoolean("youspeed.drive_recorder.tsr_independent_enabled", false)
                // A test capture must never evict the owner's existing photos.
                .putBoolean("youspeed.panoramax.unlimited_storage", true)
                .putBoolean("youspeed.panoramax.delete_uploaded", false).commit())
            ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)).use { scenario ->
                val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
                device.findObject(By.res("com.android.systemui", "ok"))?.click()
                fun act(action: (ConsumerSessionController) -> Unit) = scenario.onActivity { action(it.sessionController) }
                fun state(): ConsumerUiState {
                    lateinit var value: ConsumerUiState
                    act { value = it.uiState }
                    return value
                }
                fun awaitState(label: String, condition: (ConsumerUiState) -> Boolean) {
                    val deadline = SystemClock.uptimeMillis() + 30_000
                    while (SystemClock.uptimeMillis() < deadline) {
                        if (condition(state())) return
                        SystemClock.sleep(100)
                    }
                    fail("$label: ${state().driveRecorderState}, ${state().trafficSignCameraRuntimeDetail}; photos=${state().panoramaxCaptureCount}, detail=${state().panoramaxLastCaptureDetail}")
                }
                fun startMovieWithFrames(label: String) {
                    val movies = File(context.filesDir, "dashcam")
                    val previousNames = movies.listFiles().orEmpty().map { it.name }.toSet()
                    act { it.toggleDriveRecorderDashcam() }
                    // CameraX Start precedes the first encoder frame. A stop at
                    // that instant correctly reports ERROR_NO_VALID_DATA; this
                    // success-path test must wait for actual movie output.
                    awaitState(label) { state -> state.driveRecorderDashcamActive &&
                        movies.listFiles().orEmpty().any { it.name !in previousNames && it.length() > 1_024 } }
                }
                act { if (it.uiState.startupLogReviewState == StartupLogReviewState.CHOICE) it.keepStartupLogs() }
                awaitState("Startup") { it.startupDataState == StartupDataState.READY && !it.panoramaxMaintenanceInProgress }
                act {
                    assertTrue("Recorder test requires a real road database", it.hasUsableOnboardingMap())
                    assertFalse("Recorder test has completed setup", it.shouldPresentOnboarding())
                    // Start independent TSR first, then enable the recorder. This is the
                    // lifecycle ordering that previously skipped Panoramax batch creation.
                    it.setTrafficSignRecognitionEnabled(true)
                    it.setTrafficSignRecognitionIndependentEnabled(true)
                    it.setPanoramaxCaptureEnabled(true)
                    it.startDriving()
                    // Real GPS must not race the labelled capture samples below.
                    val manager = ConsumerSessionController::class.java.getDeclaredField("locationManager")
                        .apply { isAccessible = true }.get(it) as LocationManager
                    for (name in listOf("locationListener", "coarseLocationListener")) {
                        manager.removeUpdates(ConsumerSessionController::class.java.getDeclaredField(name)
                            .apply { isAccessible = true }.get(it) as android.location.LocationListener)
                    }
                }
                awaitState("Standalone camera active") {
                    it.trafficSignCameraRuntimeState == TrafficSignCameraRuntimeState.ACTIVE &&
                        it.driveRecorderState == DriveRecorderState.DISABLED
                }
                act {
                    it.toggleDriveRecorder()
                }
                awaitState("Movie and photos active") { it.driveRecorderDashcamActive && it.driveRecorderPanoramaxActive }
                // The tethered phone is stationary. Feed only this controller a
                // labelled test fix; never install an OS mock-location provider.
                act { injectMovingTestFix(it, fast = true) }
                awaitState("First Panoramax photo saved") { it.panoramaxCaptureCount > 0 }
                awaitState("Initial movie has encoder frames before the stop action") {
                    File(context.filesDir, "dashcam").listFiles().orEmpty()
                        .any { file -> file.name !in existingMovies && file.length() > 1_024 }
                }
                act { injectMovingTestFix(it, stationary = true) }
                awaitState("Stationary sample permits dashboard controls") { it.drivingControlsAllowed }
                // Camera continuity is independent of the optional contribution
                // prompt. Dismiss it without granting or recording consent.
                act { it.signCollection.dismissConsent() }
                assertPreviewButtonFinalizesMovieAndPreservesSurface(scenario, context, ::state)
                val settings = device.wait(Until.findObject(By.res("settings-button")), 10_000)
                assertNotNull(settings)
                settings!!.click()
                assertTrue(device.wait(Until.hasObject(By.res("settings-sheet")), 10_000))
                lateinit var gate: TrafficSignLookupMutationGate
                act {
                    gate = ConsumerSessionController::class.java.getDeclaredField("lookupToken")
                        .apply { isAccessible = true }.get(it) as TrafficSignLookupMutationGate
                    assertTrue(gate.isPaused())
                    it.setPanoramaxTriggerMode(PanoramaxCaptureTriggerMode.TIME)
                    it.setPanoramaxMinimumIntervalSeconds(1.0)
                }
                val pausedCount = state().panoramaxCaptureCount
                val pausedFixes = state().gpsFixCount
                // Keep supplying fixes as a moving drive would. A previous
                // still may finish just before a single fix, inside the cadence
                // interval; the stationary tethered GPS supplies no later one.
                val captureDeadline = SystemClock.uptimeMillis() + 30_000
                while (state().panoramaxCaptureCount <= pausedCount && SystemClock.uptimeMillis() < captureDeadline) {
                    act { injectMovingTestFix(it) }
                    SystemClock.sleep(3_000)
                }
                awaitState("Camera saves a photo while Settings pauses matching") { it.panoramaxCaptureCount > pausedCount }
                assertTrue(state().gpsFixCount > pausedFixes)
                assertTrue(gate.isPaused())
                assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
                assertTrue(state().driveRecorderPanoramaxActive)
                val settingsPhoto = queue.listBatches().filter { it.batchId !in existingBatches }
                    .flatMap { it.items }.maxBy { it.metadata.capturedAt }
                assertTrue("The still retains one of this test's moving GPS samples",
                    injectedLatitudes.any { kotlin.math.abs(it - settingsPhoto.metadata.location.latitude) < 1e-9 })
                assertEquals(0.0, settingsPhoto.metadata.location.longitude, 0.0)
                assertEquals(123.0, requireNotNull(settingsPhoto.metadata.location.altitudeMeters), 0.0)
                Log.i("Phase1DeviceTest", "CameraX Settings capture: count=$pausedCount->${state().panoramaxCaptureCount}; rawFixes=$pausedFixes->${state().gpsFixCount}; GPS/altitude metadata retained; matching paused")
                assertTrue(device.takeScreenshot(File(context.cacheDir, "phase1-settings-live-capture.png")))
                device.pressBack()
                assertTrue(device.wait(Until.gone(By.res("settings-sheet")), 10_000))
                assertFalse(gate.isPaused())
                startMovieWithFrames("Explicit movie restart")
                act { it.toggleDriveRecorderTrafficSignRecognition() }
                awaitState("TSR button finalizes video before changing recognition") {
                    !it.driveRecorderDashcamActive && !it.driveRecorderDashcamTransitioning && !it.trafficSignRecognitionEnabled
                }
                assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
                assertTrue(state().driveRecorderPanoramaxActive)
                startMovieWithFrames("Explicit movie restart before stop intent")
                act { it.toggleDriveRecorderDashcam() }
                awaitState("Dashcam stop intent remains off") { !it.driveRecorderDashcamActive && !it.driveRecorderDashcamTransitioning }
                assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
                assertTrue(state().driveRecorderPanoramaxActive)
                startMovieWithFrames("Movie restarted")
                act { it.toggleDriveRecorder() }
                awaitState("Recorder stopped") { it.driveRecorderState == DriveRecorderState.DISABLED }
                // Automatic photos are independent of the movie recorder.
                // Ending the drive seals the capture session before cleanup.
                act { it.stopDriving() }
                awaitState("Photo session sealed after drive stop") {
                    queue.listBatches().filter { it.batchId !in existingBatches }
                        .none { it.state == PanoramaxBatchState.CAPTURING }
                }
                act { assertTrue(it.canProcessPanoramaxUploads()) }
            }
        } finally {
            try {
                // Restore the exact original selection (including malformed/seed
                // state) before deleting the temporary database and its sidecars.
                if (replacedActiveState) {
                    if (previousActiveState != null) {
                        activeStateFile.writeBytes(previousActiveState)
                        assertArrayEquals(previousActiveState, activeStateFile.readBytes())
                    } else {
                        assertTrue(!activeStateFile.exists() || activeStateFile.delete())
                    }
                }
                fixtureDatabase?.let(SQLiteDatabase::deleteDatabase)
                fixtureDirectory?.deleteRecursively()
                File(context.filesDir, "dashcam").listFiles().orEmpty().filter { it.name !in existingMovies }.forEach { it.delete() }
                queue.listBatches().filter { it.batchId !in existingBatches }.forEach { batch ->
                    queue.deleteItems(batch.batchId, batch.items.map { it.itemId }.toSet())
                }
                existingMedia.forEach { (file, length) ->
                    assertTrue("Existing media remains: ${file.name}", file.isFile)
                    assertEquals("Existing media size remains: ${file.name}", length, file.length())
                }
                Log.i("Phase1DeviceTest", "Preserved ${existingMedia.size} preexisting photo/movie files with unchanged sizes; removed test media only")
            } finally {
                // Restore user preferences even if media cleanup reports a failure.
                val editor = preferences.edit().clear()
                previous.forEach { (key, value) -> when (value) {
                    is Boolean -> editor.putBoolean(key, value)
                    is String -> editor.putString(key, value)
                    is Int -> editor.putInt(key, value)
                    is Long -> editor.putLong(key, value)
                    is Float -> editor.putFloat(key, value)
                    is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
                } }
                assertTrue("Restore recorder test preferences", editor.commit())
            }
        }
    }

    private fun injectMovingTestFix(controller: ConsumerSessionController, stationary: Boolean = false, fast: Boolean = false) {
        // TIME mode also rejects stationary fixes inside twice their accuracy.
        // About 2.2 m per three-second sample keeps Settings safely reachable.
        val nextLatitude = if (stationary) injectedLatitudes.last() else (injectedLatitudes.size + 1) * 0.00002
        if (!stationary) injectedLatitudes += nextLatitude
        // Begin the stationary phase with no preceding movement history.
        if (stationary) ConsumerSessionController::class.java.getDeclaredMethod("resetDerivedSpeedTracking")
            .apply { isAccessible = true }.invoke(controller)
        val location = Location(LocationManager.GPS_PROVIDER).apply {
            latitude = nextLatitude; longitude = 0.0
            accuracy = 0.1f; speed = if (stationary) 0f else if (fast) 2f else 0.5f; bearing = 90f; altitude = 123.0
            time = System.currentTimeMillis(); elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
        }
        ConsumerSessionController::class.java.getDeclaredMethod("consumeLocation", Location::class.java)
            .apply { isAccessible = true }.invoke(controller, location)
    }

    private fun assertPreviewButtonFinalizesMovieAndPreservesSurface(
        scenario: ActivityScenario<MainActivity>,
        context: Context,
        state: () -> ConsumerUiState,
    ) {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        fun click(tag: String) {
            device.findObject(By.res("com.android.systemui", "ok"))?.click()
            val button = device.wait(Until.findObject(By.res(tag)), 10_000)
            if (button == null) {
                device.dumpWindowHierarchy(File(context.cacheDir, "recorder-failed-hierarchy.xml"))
                device.takeScreenshot(File(context.cacheDir, "recorder-failed-screen.png"))
            }
            assertNotNull("Preview control $tag", button)
            button!!.click()
        }
        fun awaitPreview(visible: Boolean): PreviewSnapshot {
            val deadline = SystemClock.uptimeMillis() + 10_000
            while (SystemClock.uptimeMillis() < deadline) {
                var snapshot: PreviewSnapshot? = null
                scenario.onActivity { activity ->
                    val preview = findPreviewView(activity.window.decorView)
                    if (preview != null && preview.isAttachedToWindow &&
                        preview.alpha == (if (visible) 1f else 0f)) {
                        val output = findPreviewOutput(preview)
                        val surface = when (output) {
                            is SurfaceView -> output.holder.surface.takeIf { it.isValid }
                            is TextureView -> output.surfaceTexture.takeIf { output.isAvailable }
                            else -> null
                        }
                        if (output != null && surface != null) snapshot = PreviewSnapshot(preview, output, surface)
                    }
                }
                snapshot?.let { return it }
                SystemClock.sleep(50)
            }
            error("No attached preview surface with visible=$visible")
        }

        // Showing the movie preview on start is automatic, not a button action.
        val initial = awaitPreview(visible = true)
        val movieNames = File(context.filesDir, "dashcam").listFiles().orEmpty().map { it.name }.toSet()
        val recordingStartedAt = state().driveRecorderStartedAt
        val destroyed = AtomicInteger()
        val holder = (initial.output as? SurfaceView)?.holder
        val callback = object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) = Unit
            override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) = Unit
            override fun surfaceDestroyed(holder: SurfaceHolder) { destroyed.incrementAndGet() }
        }
        scenario.onActivity { holder?.addCallback(callback) }
        try {
            val cameraState = state().trafficSignCameraRuntimeState
            val recognitionEnabled = state().trafficSignRecognitionEnabled
            SystemClock.sleep(1_000)
            click("recorder-hide-preview")
            val deadline = SystemClock.uptimeMillis() + 30_000
            while ((state().driveRecorderDashcamActive || state().driveRecorderDashcamTransitioning ||
                    state().dashcamButtonActionPending) && SystemClock.uptimeMillis() < deadline) SystemClock.sleep(100)
            assertFalse(state().driveRecorderDashcamActive)
            assertFalse(state().driveRecorderDashcamTransitioning)
            assertFalse(state().dashcamButtonActionPending)
            assertNull(state().dashcamButtonActionError)
            val hidden = awaitPreview(visible = false)
            assertSame("Stopping video keeps preview mounted for the photo/TSR session", initial.preview, hidden.preview)
            assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
            assertTrue(state().driveRecorderPanoramaxActive)
            assertEquals(recognitionEnabled, state().trafficSignRecognitionEnabled)
            assertEquals(cameraState, state().trafficSignCameraRuntimeState)
            assertEquals(recordingStartedAt, state().driveRecorderStartedAt)
            assertEquals("The button must not create a replacement movie", movieNames,
                File(context.filesDir, "dashcam").listFiles().orEmpty().map { it.name }.toSet())
            val movie = state().dashcamRecordings.maxByOrNull { it.createdAt }
            assertNotNull("Finalized movie is listed before the button action completes", movie)
            MediaMetadataRetriever().use { retriever ->
                retriever.setDataSource(requireNotNull(movie).path)
                assertTrue("Finalized movie is playable", (retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0) > 0)
            }
            SystemClock.sleep(500)
            assertFalse("A user action never restarts video automatically", state().driveRecorderDashcamActive)
            assertEquals("Stopping only the video consumer keeps the preview surface", 0, destroyed.get())
        } finally {
            scenario.onActivity { holder?.removeCallback(callback) }
        }
    }

    private data class PreviewSnapshot(val preview: PreviewView, val output: View, val surface: Any)

    private fun findPreviewView(view: View): PreviewView? {
        if (view is PreviewView) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            findPreviewView(view.getChildAt(index))?.let { return it }
        }
        return null
    }

    private fun findPreviewOutput(view: View): View? {
        if (view is SurfaceView || view is TextureView) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            findPreviewOutput(view.getChildAt(index))?.let { return it }
        }
        return null
    }

    private fun createRecorderMapFixture(file: File) {
        val assets = InstrumentationRegistry.getInstrumentation().targetContext.assets
        val sql = assets.open("matcher/fixtures/straight-linked.sql").bufferedReader().use { it.readText() }
        SQLiteDatabase.openOrCreateDatabase(file, null).use { database ->
            DeltaUpdatePolicy.sqlStatements(sql).forEach(database::execSQL)
            database.rawQuery("PRAGMA integrity_check", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals("ok", cursor.getString(0))
            }
            database.rawQuery("SELECT COUNT(*) FROM ways WHERE maxspeed IS NOT NULL", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertTrue("Fixture must contain road speed limits", cursor.getInt(0) > 0)
            }
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

}

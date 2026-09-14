package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.media.MediaMetadataRetriever
import android.os.SystemClock
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
    @get:Rule val permissions: GrantPermissionRule = GrantPermissionRule.grant(
        Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION,
    )

    @Test fun liveButtonsFinalizeMovieAndPreservePhotoSession() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val previous = preferences.all
        val existingMovies = File(context.filesDir, "dashcam").listFiles().orEmpty().map { it.name }.toSet()
        val queue = PanoramaxQueueStore(context)
        val existingBatches = queue.listBatches().map { it.batchId }.toSet()
        val bundleRoot = File(context.filesDir, "bundle")
        val activeStateFile = File(bundleRoot, "active_bundle.json")
        val previousActiveState = activeStateFile.takeIf { it.isFile }?.readBytes()
        var fixtureDatabase: File? = null
        var replacedActiveState = false
        try {
            val existingActive = BundleBootstrapper(bundleRoot, HttpUrlFetcher()).activeState()
            if (existingActive == null || !OnboardingPolicy.hasUsableMap(existingActive.bundleVersion,
                    File(existingActive.dbPath).isFile)) {
                // A real local road database satisfies setup exactly as a downloaded
                // map does. Do not weaken production onboarding for camera tests.
                val fixture = File(context.cacheDir, "recorder-map-${UUID.randomUUID()}.sqlite")
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
                    manifestUrl = "asset://androidTest/matcher-parity/straight-linked.sql",
                    activatedAtUTC = Instant.now().toString(),
                )
                assertTrue(bundleRoot.isDirectory || bundleRoot.mkdirs())
                replacedActiveState = true
                activeStateFile.writeText(ContractJson.encodeActiveBundleState(active))
                assertEquals(active, BundleBootstrapper(bundleRoot, HttpUrlFetcher()).activeState())
            }
            assertTrue(preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true)
                .putBoolean("youspeed.drive_recorder.tsr_independent_enabled", false).commit())
            ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)).use { scenario ->
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
                    fail("$label: ${state().driveRecorderState}, ${state().trafficSignCameraRuntimeDetail}")
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
                }
                awaitState("Standalone camera active") {
                    it.trafficSignCameraRuntimeState == TrafficSignCameraRuntimeState.ACTIVE &&
                        it.driveRecorderState == DriveRecorderState.DISABLED
                }
                act {
                    it.toggleDriveRecorder()
                }
                awaitState("Movie and photos active") { it.driveRecorderDashcamActive && it.driveRecorderPanoramaxActive }
                awaitState("First Panoramax photo saved") { it.panoramaxCaptureCount > 0 }
                assertPreviewButtonFinalizesMovieAndPreservesSurface(scenario, context, ::state)
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
                assertFalse(queue.listBatches().any { it.state == PanoramaxBatchState.CAPTURING })
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
                File(context.filesDir, "dashcam").listFiles().orEmpty().filter { it.name !in existingMovies }.forEach { it.delete() }
                queue.listBatches().filter { it.batchId !in existingBatches }.forEach { batch ->
                    queue.deleteItems(batch.batchId, batch.items.map { it.itemId }.toSet())
                }
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

    private fun assertPreviewButtonFinalizesMovieAndPreservesSurface(
        scenario: ActivityScenario<MainActivity>,
        context: Context,
        state: () -> ConsumerUiState,
    ) {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        fun click(tag: String) {
            val button = device.wait(Until.findObject(By.res(tag)), 10_000)
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
        val assets = InstrumentationRegistry.getInstrumentation().context.assets
        val sql = assets.open("matcher-parity/straight-linked.sql").bufferedReader().use { it.readText() }
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

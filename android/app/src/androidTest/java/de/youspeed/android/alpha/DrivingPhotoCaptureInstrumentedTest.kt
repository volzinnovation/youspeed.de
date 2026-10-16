package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.RectF
import android.location.Location
import android.location.LocationManager
import android.view.WindowInsets
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.MutableState
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Isolated files and a request-counting host: never opens camera hardware or an OS location provider. */
@RunWith(AndroidJUnit4::class)
class DrivingPhotoCaptureInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    @Test fun thresholdAndBottomRightSafeAreaHoldInBothLandscapeMountsAndNarrowPortrait() {
        withFixture { fixture, scenario ->
            for (orientation in ManualOrientation.entries) {
                scenario.onActivity { activity ->
                    fixture.state { copy(manualOrientation = orientation, currentSpeedKmh = 0.0, drivingControlsAllowed = true) }
                    activity.requestedOrientation = orientation.requestedOrientation
                }
                val device = UiDevice.getInstance(instrumentation)
                compose.waitUntil(15_000) { device.displayRotation == orientation.targetRotation }
                for (speed in listOf(0.0, 1.0, 1.001, 1.5, 3.99, 4.0, 35.0)) {
                    scenario.onActivity {
                        fixture.state { copy(currentSpeedKmh = speed, drivingControlsAllowed = speed < 4.0) }
                    }
                    compose.waitForIdle()
                    if (speed <= 1.0) compose.onNodeWithTag("driving-photo-button").assertDoesNotExist()
                    else {
                        compose.onNodeWithTag("driving-photo-button").assertExists()
                        scenario.onActivity { assertBottomRight(it, device, speed < 4.0) }
                        verifyPendingBounds()
                    }
                }
            }
            scenario.onActivity { activity ->
                fixture.state { copy(manualOrientation = ManualOrientation.PORTRAIT,
                    currentSpeedKmh = 1.5, drivingControlsAllowed = true) }
                activity.requestedOrientation = ManualOrientation.PORTRAIT.requestedOrientation
                activity.setContent {
                    Box(Modifier.fillMaxSize()) {
                        Box(Modifier.width(320.dp).fillMaxHeight()) { ConsumerApp(fixture.controller) }
                    }
                }
            }
            compose.waitUntil(15_000) {
                UiDevice.getInstance(instrumentation).displayRotation == ManualOrientation.PORTRAIT.targetRotation
            }
            compose.waitForIdle()
            val footer = compose.onNodeWithTag("dashboard-bottom-controls").fetchSemanticsNode().boundsInWindow
            val shutter = compose.onNodeWithTag("driving-photo-button").fetchSemanticsNode().boundsInWindow
            assertTrue("A separate row avoids a seventh narrow touch target", footer.bottom < shutter.top)
            assertTrue(shutter.right <= compose.onNodeWithTag("main-root").fetchSemanticsNode().boundsInWindow.right)
        }
    }

    @Test fun tapUsesOneLocalJpegRequestWithoutStoppingMovieAndIgnoresAutomaticPreferenceAndSignFilter() {
        withFixture { fixture, scenario ->
            fixture.prepareCapture(scenario, speed = 1.5)
            compose.onNodeWithTag("driving-photo-button").assertIsEnabled()
            val starts = fixture.host.starts
            val stops = fixture.host.stops
            compose.onNodeWithTag("driving-photo-button").performClick()
            compose.waitUntil(5_000) { fixture.host.requests.size == 1 }
            compose.onNodeWithTag("driving-photo-button").assertIsNotEnabled()
            scenario.onActivity {
                repeat(5) { assertFalse(fixture.controller.captureDrivingPhoto()) }
                assertTrue(fixture.controller.uiState.driveRecorderDashcamActive)
                assertTrue(fixture.controller.uiState.dashcamRecordingEnabled)
                assertFalse(fixture.controller.uiState.dashcamButtonActionPending)
                assertFalse(fixture.controller.uiState.panoramaxCaptureEnabled)
                assertTrue(fixture.controller.uiState.panoramaxRecognizedSignsOnly)
            }
            assertEquals(starts, fixture.host.starts)
            assertEquals(stops, fixture.host.stops)
            assertEquals(0, fixture.host.permissionRequests)
            fixture.completePhoto(scenario, fixture.host.requests.single())
            compose.waitUntil(10_000) { fixture.queue.listBatches().sumOf { it.items.size } == 1 }
            val item = fixture.queue.listBatches().flatMap { it.items }.single()
            assertEquals("manual", item.metadata.captureReason)
            assertEquals(PanoramaxItemState.CAPTURED, item.state)
            assertTrue(fixture.queue.originalFile(item).isFile)
            assertTrue(fixture.queue.thumbnailFile(item).isFile)
            assertEquals(48.0, item.metadata.location.latitude, 0.0)
            assertNull(item.metadata.signEvidence)
            assertTrue(fixture.controller.uiState.panoramaxActiveUploadBatchIds.isEmpty())
            assertEquals("The still did not rebind the camera", starts, fixture.host.starts)
            assertEquals("The still did not stop the movie", stops, fixture.host.stops)
            scenario.onActivity {
                // The same position cannot meet automatic cadence, but is a valid next explicit photo.
                assertFalse(PanoramaxCapturePolicy.shouldCapture(item.metadata.location, item.metadata.location))
                fixture.fix(Instant.now())
            }
            // The controller's wall-clock cooldown can expire before the next
            // Compose readiness tick. A click while semantics are still disabled
            // is correctly ignored, so wait for the actual user-visible state.
            compose.waitUntil(5_000) {
                fixture.controller.canCaptureDrivingPhoto() &&
                    !compose.onNodeWithTag("driving-photo-button").fetchSemanticsNode()
                        .config.contains(SemanticsProperties.Disabled)
            }
            compose.onNodeWithTag("driving-photo-button").assertIsEnabled().performClick()
            compose.waitUntil(5_000) { fixture.host.requests.size == 2 }
            scenario.onActivity {
                fixture.controller.onPanoramaxPhotoCaptureFailed("Synthetic test failure", fixture.host.requests.last())
                assertFalse("A fast failure still debounces the same gesture", fixture.controller.captureDrivingPhoto())
            }
            compose.waitUntil(5_000) { fixture.controller.uiState.drivingPhotoCaptureFailed }
            assertEquals(1, fixture.queue.listBatches().sumOf { it.items.size })
        }
    }

    @Test fun unavailablePermissionStorageLocationOutputAndSessionDisableWithoutDialogs() {
        withFixture { fixture, scenario ->
            fixture.prepareCapture(scenario, speed = 30.0)
            scenario.onActivity {
                fixture.context.cameraGranted = false
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.controller.bindHost(fixture.host)
                assertEquals("No moving permission prompt", 0, fixture.host.permissionRequests)
                fixture.context.cameraGranted = true
                fixture.context.freeBytes = 19_999_999L
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.context.freeBytes = 100_000_000L
                fixture.fix(Instant.now().minusSeconds(11))
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.fix(Instant.now())
                fixture.controller.onPanoramaxPhotoOutputReadyChanged(false)
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.controller.onPanoramaxPhotoOutputReadyChanged(true)
                fixture.state { copy(panoramaxCaptureBatchReady = false) }
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.state { copy(panoramaxCaptureBatchReady = true, appScreenshotState = AppScreenshotState.OTHER_SIGN_GIVE_WAY) }
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.state { copy(appScreenshotState = null, onboardingCompleted = false) }
                assertFalse(fixture.controller.captureDrivingPhoto())
                fixture.state { copy(onboardingCompleted = true) }
                fixture.controller.setApplicationActive(false)
                assertFalse(fixture.controller.captureDrivingPhoto())
            }
            compose.waitForIdle()
            compose.onNodeWithTag("driving-photo-button").assertIsNotEnabled()
            assertTrue(fixture.host.requests.isEmpty())
            assertEquals(0, fixture.host.permissionRequests)
            scenario.onActivity {
                fixture.controller.dispose()
                assertFalse(fixture.controller.captureDrivingPhoto())
            }
        }
    }

    @Test fun manualOnlyCameraStartsOnMovementAndStopsWhenParkedWithoutChangingAutomaticPreference() {
        withFixture { fixture, scenario ->
            fixture.prepareCapture(scenario, speed = 30.0)
            scenario.onActivity {
                fixture.manualOnly()
                fixture.state { copy(currentSpeedKmh = 0.0, drivingControlsAllowed = true) }
                fixture.reconcileSession()
            }
            val stopped = fixture.host.stops
            val started = fixture.host.starts
            assertTrue(stopped > 0)
            assertEquals(TrafficSignCameraRuntimeState.DISABLED, fixture.controller.uiState.trafficSignCameraRuntimeState)
            scenario.onActivity {
                fixture.state { copy(currentSpeedKmh = 1.01, drivingControlsAllowed = true) }
                fixture.reconcileSession()
            }
            assertTrue(fixture.host.starts > started)
            assertEquals(stopped, fixture.host.stops)
            assertFalse(fixture.controller.uiState.panoramaxCaptureEnabled)
            assertEquals(0, fixture.host.permissionRequests)
        }
    }

    @Test fun stoppingMotionSealsManualBatchAfterInFlightSaveAndStaleCallbackCannotSaveIntoLaterSession() {
        withFixture { fixture, scenario ->
            fixture.prepareCapture(scenario, speed = 30.0)
            scenario.onActivity { assertTrue(fixture.controller.captureDrivingPhoto()) }
            compose.waitUntil(5_000) { fixture.host.requests.size == 1 }
            val first = fixture.host.requests.single()
            scenario.onActivity {
                fixture.state { copy(currentSpeedKmh = 0.0, drivingControlsAllowed = true) }
                fixture.reconcileSession()
            }
            assertEquals(PanoramaxBatchState.CAPTURING, fixture.queue.listBatches().single().state)
            fixture.completePhoto(scenario, first)
            compose.waitUntil(10_000) { fixture.queue.listBatches().single().state == PanoramaxBatchState.AWAITING_REVIEW }
            assertEquals(1, fixture.queue.listBatches().single().items.size)
            scenario.onActivity {
                fixture.state { copy(currentSpeedKmh = 30.0, drivingControlsAllowed = false) }
                fixture.fix(Instant.now())
                fixture.reconcileSession()
            }
            compose.waitUntil(5_000) { fixture.controller.canCaptureDrivingPhoto() }
            scenario.onActivity { assertTrue(fixture.controller.captureDrivingPhoto()) }
            compose.waitUntil(5_000) { fixture.host.requests.size == 2 }
            scenario.onActivity { fixture.controller.stopDriving() }
            val staleFile = fixture.completePhoto(scenario, fixture.host.requests.last())
            compose.waitUntil(10_000) { !staleFile.exists() && fixture.queue.listBatches().none { it.state == PanoramaxBatchState.CAPTURING } }
            assertEquals("Stopped-session callback is discarded", 1, fixture.queue.listBatches().sumOf { it.items.size })
        }
    }

    private fun assertBottomRight(activity: MainActivity, device: UiDevice, ordinaryControls: Boolean) {
        // Called on main only for window geometry; semantics are read outside the main callback below.
        val insets = requireNotNull(activity.window.decorView.rootWindowInsets).getInsets(
            WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
        val safe = RectF(insets.left.toFloat(), insets.top.toFloat(),
            device.displayWidth - insets.right.toFloat(), device.displayHeight - insets.bottom.toFloat())
        val density = activity.resources.displayMetrics.density
        pendingSafe = safe
        pendingDensity = density
        pendingOrdinaryControls = ordinaryControls
    }
    private var pendingSafe = RectF()
    private var pendingDensity = 1f
    private var pendingOrdinaryControls = false

    private fun verifyPendingBounds() {
        val shutter = compose.onNodeWithTag("driving-photo-button").fetchSemanticsNode().boundsInWindow
        assertTrue("Shutter remains inside safe area $pendingSafe: $shutter", shutter.left >= pendingSafe.left - 1 &&
            shutter.top >= pendingSafe.top - 1 && shutter.right <= pendingSafe.right + 1 && shutter.bottom <= pendingSafe.bottom + 1)
        assertTrue("Right inset stays small", pendingSafe.right - shutter.right <= 25 * pendingDensity)
        assertEquals("Bottom inset is eight dp", 8 * pendingDensity, pendingSafe.bottom - shutter.bottom, 2f)
        if (pendingOrdinaryControls) {
            val footer = compose.onNodeWithTag("dashboard-bottom-controls").fetchSemanticsNode().boundsInWindow
            assertTrue("Ordinary controls cannot overlap shutter", footer.bottom < shutter.top)
        } else compose.onNodeWithTag("dashboard-bottom-controls").assertDoesNotExist()
    }

    private fun withFixture(block: (Fixture, ActivityScenario<MainActivity>) -> Unit) {
        val base = instrumentation.targetContext
        val preferences = base.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val priorOrientation = preferences.getString("youspeed.manual_orientation", null)
        val fixture = Fixture(base)
        try {
            ActivityScenario.launch<MainActivity>(Intent(base, MainActivity::class.java)
                .putExtra("screenshot_state", "other-sign-give-way")).use { scenario ->
                scenario.onActivity { activity ->
                    fixture.controller = ConsumerSessionController(fixture.context, File(fixture.root, "bundle"),
                        fixture.context.getSharedPreferences("youspeed", Context.MODE_PRIVATE), Clock.systemUTC(),
                        AppScreenshotState.OTHER_SIGN_GIVE_WAY)
                    fixture.host.orientation = { activity.requestedOrientation = it.requestedOrientation }
                    fixture.controller.bindHost(fixture.host)
                    activity.setContent { ConsumerApp(fixture.controller) }
                }
                compose.waitUntil(10_000) { !fixture.controller.uiState.panoramaxMaintenanceInProgress }
                block(fixture, scenario)
                scenario.onActivity { fixture.controller.dispose() }
            }
        } finally {
            instrumentation.runOnMainSync { if (fixture.initialized) fixture.controller.dispose() }
            if (fixture.initialized) fixture.awaitStorageShutdown()
            fixture.context.deletePreferences()
            fixture.root.deleteRecursively()
            val edit = preferences.edit()
            if (priorOrientation == null) edit.remove("youspeed.manual_orientation") else edit.putString("youspeed.manual_orientation", priorOrientation)
            edit.commit()
        }
    }

    private inner class Fixture(base: Context) {
        val root = File(base.cacheDir, "manual-photo-${UUID.randomUUID()}").apply { mkdirs() }
        val context = IsolatedContext(base, root)
        val host = PhotoHost()
        lateinit var controller: ConsumerSessionController
        val initialized get() = ::controller.isInitialized
        val queue get() = PanoramaxQueueStore(context)

        fun state(transform: ConsumerUiState.() -> ConsumerUiState) {
            @Suppress("UNCHECKED_CAST")
            val state = field("uiState\$delegate").get(controller) as MutableState<ConsumerUiState>
            state.value = state.value.transform()
        }
        fun fix(at: Instant) {
            field("latestCaptureLocation").set(controller, Location(LocationManager.GPS_PROVIDER).apply {
                latitude = 48.0; longitude = 8.0; accuracy = 5f; time = at.toEpochMilli(); speed = 30f / 3.6f
            })
        }
        fun manualOnly() {
            field("driveRecorderEnabled").setBoolean(controller, false)
            field("activeDashcamPath").set(controller, null)
            state { copy(driveRecorderState = DriveRecorderState.DISABLED, dashcamRecordingEnabled = false,
                driveRecorderDashcamActive = false) }
        }
        fun awaitStorageShutdown() {
            val worker = field("panoramaxStorageWorker").get(controller)
            val executor = PanoramaxStorageWorker::class.java.getDeclaredField("executor")
                .apply { isAccessible = true }.get(worker) as java.util.concurrent.ExecutorService
            assertTrue(executor.awaitTermination(10, java.util.concurrent.TimeUnit.SECONDS))
        }
        fun reconcileSession() = ConsumerSessionController::class.java.getDeclaredMethod("reconcilePhotoCaptureSession")
            .apply { isAccessible = true }.invoke(controller)

        fun prepareCapture(scenario: ActivityScenario<MainActivity>, speed: Double) {
            scenario.onActivity {
                field("isDriving").setBoolean(controller, true)
                field("panoramaxCaptureEnabled").setBoolean(controller, false)
                field("driveRecorderEnabled").setBoolean(controller, true)
                field("activeDashcamPath").set(controller, "isolated-manual-photo-test.mp4")
                fix(Instant.now())
                state { copy(appScreenshotState = null, startupDataState = StartupDataState.READY,
                    startupLogReviewState = StartupLogReviewState.COMPLETE, onboardingCompleted = true,
                    downloadedBundleLatestVersionByRegion = mapOf("isolated-test" to "2026-10-10"),
                    driveStatus = "running", currentSpeedKmh = speed, drivingControlsAllowed = speed < 4.0,
                    panoramaxCaptureEnabled = false, panoramaxRecognizedSignsOnly = true,
                    panoramaxUnlimitedStorage = true, panoramaxDeleteUploadedImages = false,
                    trafficSignRecognitionEnabled = false, driveRecorderState = DriveRecorderState.RECORDING,
                    dashcamRecordingEnabled = true, driveRecorderDashcamActive = true) }
                controller.bindHost(host)
                controller.onPanoramaxPhotoOutputReadyChanged(true)
                controller.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Isolated test output")
            }
            compose.waitUntil(10_000) { controller.canCaptureDrivingPhoto() }
        }

        fun completePhoto(scenario: ActivityScenario<MainActivity>, requestId: String): File {
            val file = File(context.cacheDir, "$requestId.jpg")
            val bitmap = Bitmap.createBitmap(64, 48, Bitmap.Config.ARGB_8888)
            try { file.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it)) } }
            finally { bitmap.recycle() }
            scenario.onActivity {
                controller.onPanoramaxPhotoCaptured(file.absolutePath,
                    PanoramaxLocationSample(48.0, 8.0, Instant.now(), 5.0), requestId)
            }
            return file
        }
        private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }
    }

    private class IsolatedContext(val base: Context, val root: File) : ContextWrapper(base) {
        var cameraGranted = true
        var freeBytes = 100_000_000L
        private val preferenceNames = mutableSetOf<String>()
        override fun getApplicationContext(): Context = this
        override fun getFilesDir(): File = object : File(root, "files") {
            override fun getUsableSpace(): Long = freeBytes
        }.apply { mkdirs() }
        override fun getCacheDir(): File = File(root, "cache").apply { mkdirs() }
        override fun getNoBackupFilesDir(): File = File(root, "no-backup").apply { mkdirs() }
        override fun getSharedPreferences(name: String, mode: Int) =
            base.getSharedPreferences("${root.name}-$name".also(preferenceNames::add), mode)
        override fun checkSelfPermission(permission: String): Int =
            if (permission == Manifest.permission.CAMERA && cameraGranted) PackageManager.PERMISSION_GRANTED
            else PackageManager.PERMISSION_DENIED
        fun deletePreferences() { preferenceNames.forEach { base.deleteSharedPreferences(it) } }
    }

    private class PhotoHost : ConsumerHost {
        var starts = 0
        var stops = 0
        var permissionRequests = 0
        var orientation: (ManualOrientation) -> Unit = {}
        val requests = mutableListOf<String>()
        override fun requestLocationPermission() { permissionRequests++ }
        override fun requestMicrophonePermission() { permissionRequests++ }
        override fun requestCameraPermission() { permissionRequests++ }
        override fun startTrafficSignCamera() { starts++ }
        override fun stopTrafficSignCamera() { stops++ }
        override fun applyManualOrientation(orientation: ManualOrientation) { this.orientation(orientation) }
        override fun capturePanoramaxPhoto(requestId: String) { requests += requestId }
        override fun showTransientMessage(message: String) {}
        override fun openExternalUrl(url: String) { fail("A manual photo must not open another screen") }
        override fun shareFile(path: String, mimeType: String) { fail("A manual photo must remain local") }
    }
}

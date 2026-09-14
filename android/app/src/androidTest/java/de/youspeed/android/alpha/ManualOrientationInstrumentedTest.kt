package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Controller state transitions with explicit camera callbacks and no native camera. */
@RunWith(AndroidJUnit4::class)
class ManualOrientationInstrumentedTest {
    @get:Rule val permissions: GrantPermissionRule = GrantPermissionRule.grant(
        Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION,
    )

    @Test fun successfulFinalizationRunsOneActionAndPreservesPhotoAndRecognitionSession() = withController { test ->
        val path = test.beginMovie()
        val before = test.state()
        val batchesBefore = test.captureSessionIds()
        val cameraStopsBefore = test.host.cameraStops
        var actions = 0

        test.act {
            it.performButtonAction { actions++ }
            it.performButtonAction { actions += 100 }
        }
        assertTrue(test.state().dashcamButtonActionPending)
        assertFalse(test.state().dashcamRecordingEnabled)
        assertEquals(0, actions)
        test.assertOtherConsumersPreserved(before, batchesBefore, cameraStopsBefore)
        assertEquals(before.trafficSignGeneration, test.state().trafficSignGeneration)

        test.act { it.onDashcamRecordingFinalized("stale.mp4", success = true, detail = null) }
        test.idle()
        assertTrue(test.state().dashcamButtonActionPending)
        assertEquals(0, actions)

        test.finalize(path, success = true)
        test.act { it.onDashcamRecordingFinalized(path, success = true, detail = null) }
        test.idle()
        assertEquals(1, actions)
        assertFalse(test.state().dashcamButtonActionPending)
        assertFalse(test.state().driveRecorderDashcamActive)
        assertFalse(test.state().dashcamRecordingEnabled)
        assertNull(test.state().dashcamButtonActionError)
        test.assertOtherConsumersPreserved(before, batchesBefore, cameraStopsBefore)
        assertEquals(before.trafficSignGeneration, test.state().trafficSignGeneration)
    }

    @Test fun failedFinalizationDropsActionWithoutStoppingPhotoOrRecognition() = withController { test ->
        val path = test.beginMovie()
        val before = test.state()
        val batchesBefore = test.captureSessionIds()
        val cameraStopsBefore = test.host.cameraStops
        var actions = 0
        test.act { it.performButtonAction { actions++ } }

        test.finalize(path, success = false, detail = "Simulated save failure")
        test.act { it.onDashcamRecordingFinalized(path, success = true, detail = null) }
        test.idle()

        assertEquals(0, actions)
        assertFalse(test.state().dashcamButtonActionPending)
        assertEquals("Simulated save failure", test.state().dashcamButtonActionError)
        assertFalse(test.state().dashcamRecordingEnabled)
        test.assertOtherConsumersPreserved(before, batchesBefore, cameraStopsBefore)
        assertEquals(before.trafficSignGeneration, test.state().trafficSignGeneration)
        test.act { it.performButtonAction { actions++ } }
        assertEquals("A later tap is accepted after failure", 1, actions)
    }

    @Test fun bothLandscapeChoicesApplyOnlyAfterSavingAndSurviveControllerReload() = withController { test ->
        assertEquals(ManualOrientation.PORTRAIT, test.state().manualOrientation)
        for (orientation in ManualOrientation.entries.filter { it.isLandscape }) {
            val path = test.beginMovie()
            val before = test.state()
            val batchesBefore = test.captureSessionIds()
            val cameraStopsBefore = test.host.cameraStops
            val previousApplications = test.host.appliedOrientations.toList()

            test.act { it.setManualOrientation(orientation) }
            assertEquals(before.manualOrientation, test.state().manualOrientation)
            assertEquals(previousApplications, test.host.appliedOrientations)
            assertTrue(test.state().dashcamButtonActionPending)

            test.finalize(path, success = true)
            assertEquals(orientation, test.state().manualOrientation)
            assertEquals(previousApplications + orientation, test.host.appliedOrientations)
            assertEquals(orientation.storageValue, test.preferences.getString("youspeed.manual_orientation", null))
            assertFalse(test.state().dashcamRecordingEnabled)
            test.assertOtherConsumersPreserved(before, batchesBefore, cameraStopsBefore)

            test.reload()
            assertEquals(orientation, test.state().manualOrientation)
            assertEquals(orientation, test.host.appliedOrientations.last())
        }
    }

    @Test fun failedMovieSaveDoesNotApplyOrPersistRequestedOrientation() = withController { test ->
        val path = test.beginMovie()
        val previousApplications = test.host.appliedOrientations.toList()
        test.act { it.setManualOrientation(ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT) }
        test.finalize(path, success = false, detail = "Simulated save failure")

        assertEquals(ManualOrientation.PORTRAIT, test.state().manualOrientation)
        assertEquals(previousApplications, test.host.appliedOrientations)
        assertEquals(ManualOrientation.PORTRAIT,
            ManualOrientation.fromStorageValue(test.preferences.getString("youspeed.manual_orientation", null)))
        assertFalse(test.state().dashcamButtonActionPending)
    }

    @Test fun unexpectedCameraReleaseDropsWaitingActionWithoutClaimingSaved() = withController { test ->
        test.beginMovie()
        var actions = 0
        test.act {
            it.performButtonAction { actions++ }
            it.onDashcamCameraReleased()
        }
        test.idle()
        assertEquals(0, actions)
        assertFalse(test.state().dashcamButtonActionPending)
        assertNotNull(test.state().dashcamButtonActionError)
        assertFalse(test.state().dashcamRecordingEnabled)
    }

    private class RecordingHost : ConsumerHost {
        var cameraStarts = 0
        var cameraStops = 0
        val appliedOrientations = mutableListOf<ManualOrientation>()
        override fun requestLocationPermission() {}
        override fun requestMicrophonePermission() {}
        override fun requestCameraPermission() {}
        override fun startTrafficSignCamera() { cameraStarts++ }
        override fun stopTrafficSignCamera() { cameraStops++ }
        override fun applyManualOrientation(orientation: ManualOrientation) { appliedOrientations += orientation }
        override fun capturePanoramaxPhoto(requestId: String) {}
        override fun showTransientMessage(message: String) {}
        override fun openExternalUrl(url: String) {}
        override fun shareFile(path: String, mimeType: String) {}
    }

    private class ControllerHarness(
        val context: Context,
        val preferences: SharedPreferences,
        val bundleRoot: File,
    ) {
        private val instrumentation = InstrumentationRegistry.getInstrumentation()
        val host = RecordingHost()
        private var controller: ConsumerSessionController? = null

        fun initialize() {
            instrumentation.runOnMainSync {
                controller = ConsumerSessionController(context, bundleRoot, preferences, Clock.systemUTC(), null)
                requireNotNull(controller).bindHost(host)
            }
            val deadline = SystemClock.uptimeMillis() + 60_000
            while ((state().startupDataState == StartupDataState.LOADING || state().panoramaxMaintenanceInProgress) &&
                SystemClock.uptimeMillis() < deadline) SystemClock.sleep(50)
            assertEquals(state().lastError, StartupDataState.READY, state().startupDataState)
            assertFalse(state().panoramaxMaintenanceInProgress)
            act { assertFalse("Fixture satisfies setup", it.shouldPresentOnboarding()) }
        }

        fun act(action: (ConsumerSessionController) -> Unit) =
            instrumentation.runOnMainSync { action(requireNotNull(controller)) }

        fun idle() = instrumentation.waitForIdleSync()

        fun state(): ConsumerUiState {
            lateinit var state: ConsumerUiState
            act { state = it.uiState }
            return state
        }

        fun beginMovie(): String {
            act {
                if (!it.isDriveRecorderSessionActive()) {
                    it.setTrafficSignRecognitionEnabled(true)
                    it.setTrafficSignRecognitionIndependentEnabled(true)
                    it.setPanoramaxCaptureEnabled(true)
                    it.startDriving()
                    it.toggleDriveRecorder()
                    it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Test camera active")
                } else if (!it.uiState.dashcamRecordingEnabled) {
                    it.toggleDriveRecorderDashcam()
                }
            }
            idle()
            lateinit var path: String
            act {
                assertTrue(it.isDriveRecorderSessionActive())
                assertTrue(it.isPanoramaxCaptureEnabled())
                assertTrue(it.isTrafficSignRecognitionRuntimeEnabled())
                path = it.nextDashcamRecordingFile().absolutePath
                it.onDashcamRecordingStateChanged(active = true, path = path)
            }
            idle()
            assertTrue(state().driveRecorderDashcamActive)
            assertTrue(state().dashcamRecordingEnabled)
            assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
            assertEquals(1, captureSessionIds().size)
            return path
        }

        fun finalize(path: String, success: Boolean, detail: String? = null) {
            act {
                it.onDashcamRecordingStateChanged(active = false, path = path)
                it.onDashcamRecordingFinalized(path, success, detail)
            }
            idle()
        }

        fun captureSessionIds(): Set<String> = PanoramaxQueueStore(context).listBatches()
            .filter { it.state == PanoramaxBatchState.CAPTURING }.map { it.captureSessionId }.toSet()

        fun assertOtherConsumersPreserved(before: ConsumerUiState, batchIds: Set<String>, cameraStops: Int) {
            val after = state()
            assertEquals(DriveRecorderState.RECORDING, after.driveRecorderState)
            assertEquals(before.driveRecorderStartedAt, after.driveRecorderStartedAt)
            assertTrue(after.driveRecorderPanoramaxActive)
            assertTrue(after.trafficSignRecognitionEnabled)
            assertTrue(after.trafficSignRecognitionIndependentEnabled)
            assertEquals(TrafficSignCameraRuntimeState.ACTIVE, after.trafficSignCameraRuntimeState)
            assertEquals(batchIds, captureSessionIds())
            assertEquals(cameraStops, host.cameraStops)
            act {
                assertTrue(it.isDriveRecorderSessionActive())
                assertTrue(it.isPanoramaxCaptureEnabled())
                assertTrue(it.isTrafficSignRecognitionRuntimeEnabled())
            }
        }

        fun reload() {
            dispose()
            initialize()
        }

        fun dispose() {
            instrumentation.runOnMainSync {
                controller?.dispose()
                controller = null
            }
            idle()
        }
    }

    private fun withController(block: (ControllerHarness) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = instrumentation.targetContext
        val id = "orientation-test-${UUID.randomUUID()}"
        val directory = File(base.cacheDir, id).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = File(directory, "files").apply { mkdirs() }
            override fun getCacheDir(): File = File(directory, "cache").apply { mkdirs() }
            override fun getNoBackupFilesDir(): File = File(directory, "no-backup").apply { mkdirs() }
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences =
                base.getSharedPreferences("$id-$name", mode)
        }
        val preferences = isolated.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val bundleRoot = File(isolated.filesDir, "bundle").apply { mkdirs() }
        val harness = ControllerHarness(isolated, preferences, bundleRoot)
        try {
            val databaseFile = File(bundleRoot, "orientation-fixture.sqlite")
            val sql = instrumentation.context.assets.open("matcher-parity/straight-linked.sql").bufferedReader().use { it.readText() }
            SQLiteDatabase.openOrCreateDatabase(databaseFile, null).use { database ->
                DeltaUpdatePolicy.sqlStatements(sql).forEach(database::execSQL)
            }
            val active = ActiveBundleState(
                region = "orientation-test-region", countryCode = "DEU", bundleVersion = "2026-09-14-orientation-fixture",
                dbFileName = databaseFile.name, dbPath = databaseFile.absolutePath,
                dbSha256 = PanoramaxQueueStore.sha256(databaseFile), dbBytes = databaseFile.length(),
                manifestUrl = "asset://androidTest/matcher-parity/straight-linked.sql", activatedAtUTC = Instant.now().toString(),
            )
            File(bundleRoot, "active_bundle.json").writeText(ContractJson.encodeActiveBundleState(active))
            assertTrue(preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true).commit())
            harness.initialize()
            block(harness)
        } finally {
            harness.dispose()
            base.deleteSharedPreferences("$id-youspeed")
            directory.deleteRecursively()
        }
    }
}

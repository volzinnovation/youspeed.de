package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
import java.time.Clock
import java.time.Instant
import java.util.Locale
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
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

    @Test fun settingsPauseKeepsRawFixesAndWaitsForQueuedBundleRemovalAfterDismissal() = withController { test ->
        test.act { it.startDriving() }
        test.stopSystemLocationUpdates()
        test.injectFix()
        test.awaitLookupWork()
        val warm = test.lookupStats()
        assertTrue("An actual native SQLite reader was opened", warm.liveConnections > 0)
        repeat(3) { test.injectFix(); test.awaitLookupWork() }
        assertEquals("Repeated fixes retain the reader", warm.opens, test.lookupStats().opens)
        val used = test.lookupStats()
        assertTrue(test.state().limitWayId != null)
        val before = test.state().gpsFixCount
        test.act { it.setSettingsVisible(true) }
        val pausedToken = test.lookupGate().snapshot()
        repeat(3) { test.injectFix() }
        test.awaitLookupWork()
        assertEquals(before + 3, test.state().gpsFixCount)
        assertEquals("Paused fixes do not touch SQLite", used, test.lookupStats())
        assertFalse(test.lookupGate().isCurrent(pausedToken))
        val held = CountDownLatch(1)
        val release = CountDownLatch(1)
        test.backgroundExecutor().submit {
            held.countDown()
            check(release.await(15, TimeUnit.SECONDS))
        }
        try {
            assertTrue(held.await(3, TimeUnit.SECONDS))
            test.act {
                it.deleteDownloadedBundlesKeepingSeed()
                it.setSettingsVisible(false)
            }
            assertTrue("Closing Settings cannot resume a queued deletion", test.lookupGate().isPaused())
            test.injectFix()
            assertEquals(before + 4, test.state().gpsFixCount)
            assertEquals(used, test.lookupStats())
        } finally { release.countDown() }
        test.awaitBackgroundWork()
        assertFalse("Deletion completion resumes admission", test.lookupGate().isPaused())
        assertFalse(test.lookupGate().isCurrent(pausedToken))
        assertFalse("The isolated downloaded fixture was deleted", File(test.bundleRoot, "bundles/orientation-fixture/orientation-fixture.sqlite").exists())
        assertNull("Removed source cannot retain the previous matched road", test.state().limitWayId)
        val resumed = test.lookupStats()
        test.idle()
        assertEquals("Resume does not replay a fix captured in Settings", resumed, test.lookupStats())
        test.injectFix()
        test.awaitLookupWork()
        assertFalse(test.lookupGate().isPaused())
        Log.i("Phase1DeviceTest", "Settings lookup reuse: warm=$warm repeated=$used resumed=$resumed; rawFixesBefore=$before rawFixesAfter=${test.state().gpsFixCount}; queued deletion held pause; fresh fix resumed")
    }

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

    @Test fun disablingRecognitionKeepsSharedCameraAndPhotoSessionActive() = withController { test ->
        test.beginMovie()
        val batches = test.captureSessionIds()
        val cameraStops = test.host.cameraStops
        test.act { it.setTrafficSignRecognitionEnabled(false) }
        test.awaitBackgroundWork()
        assertFalse(test.state().trafficSignRecognitionEnabled)
        assertEquals(TrafficSignCameraRuntimeState.ACTIVE, test.state().trafficSignCameraRuntimeState)
        assertTrue(test.state().driveRecorderPanoramaxActive)
        assertEquals(DriveRecorderState.RECORDING, test.state().driveRecorderState)
        assertEquals(batches, test.captureSessionIds())
        assertEquals(cameraStops, test.host.cameraStops)
    }

    @Test fun disablingRecognitionStopsCameraWhenNoOtherConsumerNeedsIt() = withController { test ->
        test.act {
            it.setPanoramaxCaptureEnabled(false)
            it.setTrafficSignRecognitionEnabled(true)
            it.setTrafficSignRecognitionIndependentEnabled(true)
            it.startDriving()
            it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Standalone recognition")
        }
        test.idle()
        val cameraStops = test.host.cameraStops
        test.act { it.setTrafficSignRecognitionEnabled(false) }
        assertEquals(TrafficSignCameraRuntimeState.DISABLED, test.state().trafficSignCameraRuntimeState)
        assertFalse(test.state().driveRecorderPanoramaxActive)
        assertTrue(test.host.cameraStops > cameraStops)
    }

    @Test fun terminalRecognitionFailureRetainsAutomaticPhotosButReleasesUnusedCamera() {
        for (photosEnabled in listOf(true, false)) withController { test ->
            test.act {
                it.setPanoramaxCaptureEnabled(photosEnabled)
                it.setTrafficSignRecognitionEnabled(true)
                it.setTrafficSignRecognitionIndependentEnabled(true)
                it.startDriving()
                it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Standalone camera")
            }
            test.awaitBackgroundWork()
            val cameraStops = test.host.cameraStops
            val batches = test.captureSessionIds()
            test.act { it.onTrafficSignRecognitionUnavailable("Test model failure", it.uiState.trafficSignGeneration) }
            test.idle()
            assertTrue(test.state().trafficSignRecognitionUnavailable)
            assertEquals("Test model failure", test.state().trafficSignCameraRuntimeDetail)
            if (photosEnabled) {
                assertEquals(cameraStops, test.host.cameraStops)
                assertEquals(TrafficSignCameraRuntimeState.ACTIVE, test.state().trafficSignCameraRuntimeState)
                assertTrue(test.state().driveRecorderPanoramaxActive)
                assertEquals(batches, test.captureSessionIds())
            } else assertTrue(test.host.cameraStops > cameraStops)
        }
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

    @Test fun queueMaintenanceCannotBlockCameraCallbacksGalleryActionsOrDriveStop() = withController { test ->
        var galleryActions = 0
        test.withStorageWorkerBlocked {
            test.actResponsive {
                it.startDriving()
                it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Test camera active")
                it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Repeated active callback")
                repeat(1_000) { _ -> it.refreshPanoramaxBatches() }
                it.performButtonAction { galleryActions++ }
            }
            assertEquals("Gallery button responds while maintenance holds the queue lock", 1, galleryActions)
        }
        test.awaitBackgroundWork()
        assertEquals("Repeated ACTIVE callbacks reserve a single capture session", 1, test.captureSessionIds().size)
        test.withStorageWorkerBlocked {
            test.actResponsive {
                it.refreshPanoramaxBatches()
                it.stopDriving()
                it.performButtonAction { galleryActions++ }
            }
            assertEquals(2, galleryActions)
        }
        test.awaitBackgroundWork()
        assertTrue(test.captureSessionIds().isEmpty())
        assertEquals(PanoramaxBatchState.AWAITING_REVIEW, test.queueBatches().single().state)
    }

    @Test fun cancelledQueuedCaptureStartCannotFinalizeTheNextDriveSession() = withController { test ->
        test.withStorageWorkerBlocked {
            test.actResponsive {
                it.startDriving()
                it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "First drive")
                it.stopDriving()
                it.startDriving()
                it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Next drive")
                it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Repeated active callback")
            }
        }
        test.awaitBackgroundWork()
        val batches = test.queueBatches()
        assertEquals("Only the latest drive remains capturing", 1, batches.count { it.state == PanoramaxBatchState.CAPTURING })
        assertTrue("A cancelled start may either be skipped or finalized", batches.size in 1..2)
        assertTrue(batches.filter { it.state != PanoramaxBatchState.CAPTURING }.all {
            it.state == PanoramaxBatchState.AWAITING_REVIEW
        })
    }

    @Test fun disposalSealsCapturesAfterQueueContentionWithoutBlockingMain() = withController { test ->
        test.act {
            it.startDriving()
            it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Test camera active")
        }
        test.awaitBackgroundWork()
        assertEquals(1, test.captureSessionIds().size)
        val executor = test.storageExecutor()
        test.withStorageWorkerBlocked {
            test.actResponsive { it.dispose() }
            assertTrue(executor.isShutdown)
            assertFalse("Final sealing waits for maintenance on the worker", executor.isTerminated)
            // Another controller can create a session while this controller
            // waits for its accepted storage work to drain.
            PanoramaxQueueStore(test.context).createBatch("replacement-controller-session")
        }
        assertTrue(executor.awaitTermination(10, TimeUnit.SECONDS))
        val batches = test.queueBatches()
        assertEquals(PanoramaxBatchState.AWAITING_REVIEW,
            batches.single { it.captureSessionId != "replacement-controller-session" }.state)
        assertEquals("Disposal only finalizes sessions owned by this controller", PanoramaxBatchState.CAPTURING,
            batches.single { it.captureSessionId == "replacement-controller-session" }.state)
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

        fun actResponsive(action: (ConsumerSessionController) -> Unit) {
            val completed = CountDownLatch(1)
            val failure = AtomicReference<Throwable?>()
            Handler(Looper.getMainLooper()).post {
                try { action(requireNotNull(controller)) }
                catch (error: Throwable) { failure.set(error) }
                finally { completed.countDown() }
            }
            assertTrue("UI callbacks must not wait for the queue lock", completed.await(3, TimeUnit.SECONDS))
            failure.get()?.let { throw it }
        }

        fun withStorageWorkerBlocked(block: () -> Unit) {
            val held = CountDownLatch(1)
            val release = CountDownLatch(1)
            // Photo work now has a dedicated worker and shared-root locking.
            // Blocking the former per-store monitor no longer creates contention.
            val worker = storageExecutor().submit {
                held.countDown()
                check(release.await(15, TimeUnit.SECONDS))
            }
            try {
                assertTrue(held.await(3, TimeUnit.SECONDS))
                block()
            } finally {
                release.countDown()
                worker.get(5, TimeUnit.SECONDS)
                idle()
            }
        }

        fun awaitBackgroundWork() {
            // A mutation may enqueue a coalesced refresh at the tail.
            repeat(2) {
                backgroundExecutor().submit {}.get(10, TimeUnit.SECONDS)
                storageExecutor().submit {}.get(10, TimeUnit.SECONDS)
                idle()
            }
        }

        fun storageExecutor(): ExecutorService = PanoramaxStorageWorker::class.java.getDeclaredField("executor")
            .apply { isAccessible = true }.get(field("panoramaxStorageWorker")) as ExecutorService

        fun backgroundExecutor(): ExecutorService {
            val field = ConsumerSessionController::class.java.getDeclaredField("executor").apply { isAccessible = true }
            return field.get(requireNotNull(controller)) as ExecutorService
        }

        fun idle() = instrumentation.waitForIdleSync()

        fun lookupGate(): TrafficSignLookupMutationGate = field("lookupToken") as TrafficSignLookupMutationGate

        fun lookupStats(): LookupPoolStats = (field("lookupResources") as LookupSessionResources<*>).stats()

        private fun field(name: String): Any = requireNotNull(ConsumerSessionController::class.java.getDeclaredField(name)
            .apply { isAccessible = true }.get(requireNotNull(controller)))

        fun awaitLookupWork() {
            val worker = field("lookupWorker") as LatestPendingLookupWorker
            val executor = LatestPendingLookupWorker::class.java.getDeclaredField("executor")
                .apply { isAccessible = true }.get(worker) as ExecutorService
            executor.submit {}.get(10, TimeUnit.SECONDS)
            idle()
        }

        fun stopSystemLocationUpdates() {
            val manager = field("locationManager") as LocationManager
            manager.removeUpdates(field("locationListener") as LocationListener)
            manager.removeUpdates(field("coarseLocationListener") as LocationListener)
        }

        fun injectFix() {
            val location = Location(LocationManager.GPS_PROVIDER).apply {
                latitude = 52.06000; longitude = 13.00392
                accuracy = 5f; speed = 8f; bearing = 90f
                time = System.currentTimeMillis(); elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
            }
            act { controller ->
                ConsumerSessionController::class.java.getDeclaredMethod("consumeLocation", Location::class.java)
                    .apply { isAccessible = true }.invoke(controller, location)
            }
        }

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
                    stopSystemLocationUpdates()
                    it.toggleDriveRecorder()
                    it.onTrafficSignCameraRuntimeStateChanged(TrafficSignCameraRuntimeState.ACTIVE, "Test camera active")
                } else if (!it.uiState.dashcamRecordingEnabled) {
                    it.toggleDriveRecorderDashcam()
                }
            }
            awaitBackgroundWork()
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

        fun queueBatches(): List<PanoramaxBatchRecord> = PanoramaxQueueStore(context).listBatches()

        fun captureSessionIds(): Set<String> = queueBatches()
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
            val executors = controller?.let { listOf(backgroundExecutor(), storageExecutor()) }.orEmpty()
            instrumentation.runOnMainSync {
                controller?.dispose()
                controller = null
            }
            executors.forEach { assertTrue(it.awaitTermination(15, TimeUnit.SECONDS)) }
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
        val previousLocale = Locale.getDefault()
        try {
            // This fixture exercises the German setup used by the attached
            // phones, independent of the emulator's default speech language.
            Locale.setDefault(Locale.GERMANY)
            val databaseFile = File(bundleRoot, "bundles/orientation-fixture/orientation-fixture.sqlite")
            assertTrue(databaseFile.parentFile!!.mkdirs())
            val sql = instrumentation.targetContext.assets.open("matcher/fixtures/straight-linked.sql").bufferedReader().use { it.readText() }
            SQLiteDatabase.openOrCreateDatabase(databaseFile, null).use { database ->
                DeltaUpdatePolicy.sqlStatements(sql).forEach(database::execSQL)
            }
            val active = ActiveBundleState(
                region = "orientation-test-region", countryCode = "DEU", bundleVersion = "2026-09-14-orientation-fixture",
                dbFileName = databaseFile.name, dbPath = databaseFile.absolutePath,
                dbSha256 = PanoramaxQueueStore.sha256(databaseFile), dbBytes = databaseFile.length(),
                manifestUrl = "asset://shared/matcher/fixtures/straight-linked.sql", activatedAtUTC = Instant.now().toString(),
            )
            writeCoverageFixtureManifest(databaseFile, active.region, active.bundleVersion, 13.0, 52.0, 13.1, 52.1)
            File(bundleRoot, "active_bundle.json").writeText(ContractJson.encodeActiveBundleState(active))
            assertTrue(preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true).commit())
            harness.initialize()
            block(harness)
        } finally {
            harness.dispose()
            base.deleteSharedPreferences("$id-youspeed")
            directory.deleteRecursively()
            Locale.setDefault(previousLocale)
        }
    }
}

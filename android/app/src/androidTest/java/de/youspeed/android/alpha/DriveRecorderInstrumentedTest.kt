package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
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

    @Test fun liveModuleChangesPreserveMovieAndPhotoSession() {
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
                act { it.toggleDriveRecorderTrafficSignRecognition() }
                // Incremental CameraX graph changes previously stopped the movie here.
                SystemClock.sleep(2_000)
                assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
                assertTrue(state().driveRecorderDashcamActive)
                assertFalse(state().trafficSignRecognitionEnabled)
                act { it.toggleDriveRecorderDashcam() }
                awaitState("Movie off") { !it.driveRecorderDashcamActive && !it.driveRecorderDashcamTransitioning }
                assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
                assertTrue(state().driveRecorderPanoramaxActive)
                act { it.toggleDriveRecorderDashcam() }
                awaitState("Movie restarted") { it.driveRecorderDashcamActive }
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

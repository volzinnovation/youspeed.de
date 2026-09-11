package de.youspeed.android.alpha

import android.Manifest
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
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
        preferences.edit().putBoolean("youspeed.hide_welcome_screen", true)
            .putBoolean("youspeed.drive_recorder.tsr_independent_enabled", false).commit()
        try {
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
                act { it.setTrafficSignRecognitionEnabled(false); it.setPanoramaxCaptureEnabled(true); it.toggleDriveRecorder() }
                awaitState("Movie and photos active") { it.driveRecorderDashcamActive && it.driveRecorderPanoramaxActive }
                act { it.toggleDriveRecorderTrafficSignRecognition() }
                // Incremental CameraX graph changes previously stopped the movie here.
                SystemClock.sleep(2_000)
                assertEquals(DriveRecorderState.RECORDING, state().driveRecorderState)
                assertTrue(state().driveRecorderDashcamActive)
                assertTrue(state().trafficSignRecognitionEnabled)
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
            File(context.filesDir, "dashcam").listFiles().orEmpty().filter { it.name !in existingMovies }.forEach { it.delete() }
            queue.listBatches().filter { it.batchId !in existingBatches }.forEach { batch ->
                queue.deleteItems(batch.batchId, batch.items.map { it.itemId }.toSet())
            }
            val editor = preferences.edit().clear()
            previous.forEach { (key, value) -> when (value) {
                is Boolean -> editor.putBoolean(key, value)
                is String -> editor.putString(key, value)
                is Int -> editor.putInt(key, value)
                is Long -> editor.putLong(key, value)
                is Float -> editor.putFloat(key, value)
                is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
            } }
            editor.commit()
        }
    }
}

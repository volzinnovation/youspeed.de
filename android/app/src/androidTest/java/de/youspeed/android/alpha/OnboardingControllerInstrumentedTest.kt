package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class OnboardingControllerInstrumentedTest {
    @Test fun freshSetupDoesNotRequestPermissionsDownloadOrStartCamera() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = instrumentation.targetContext
        val id = "onboarding-test-${UUID.randomUUID()}"
        val root = File(base.cacheDir, id).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = File(root, "files").apply { mkdirs() }
            override fun getCacheDir(): File = File(root, "cache").apply { mkdirs() }
            override fun getNoBackupFilesDir(): File = File(root, "no-backup").apply { mkdirs() }
            override fun getSharedPreferences(name: String, mode: Int) = base.getSharedPreferences("$id-$name", mode)
        }
        val preferences = isolated.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val host = QuietHost()
        lateinit var controller: ConsumerSessionController
        var initialized = false
        fun act(action: (ConsumerSessionController) -> Unit) = instrumentation.runOnMainSync { action(controller) }
        fun state(): ConsumerUiState {
            lateinit var current: ConsumerUiState
            act { current = it.uiState }
            return current
        }
        try {
            instrumentation.runOnMainSync {
                controller = ConsumerSessionController(isolated, File(root, "bundle"), preferences, Clock.systemUTC(), null)
                initialized = true
                controller.bindHost(host)
            }
            val deadline = SystemClock.uptimeMillis() + 60_000
            while (state().startupDataState == StartupDataState.LOADING && SystemClock.uptimeMillis() < deadline) {
                SystemClock.sleep(100)
            }
            assertEquals(state().lastError, StartupDataState.READY, state().startupDataState)
            assertTrue(preferences.contains("youspeed.onboarding.completed"))
            assertFalse(preferences.getBoolean("youspeed.onboarding.completed", true))
            act {
                assertTrue(it.shouldPresentOnboarding())
                assertFalse(it.hasUsableOnboardingMap())
                it.advanceOnboarding()
                it.startDriving()
                it.setTrafficSignRecognitionEnabled(true)
                it.setTrafficSignRecognitionIndependentEnabled(true)
                it.toggleDriveRecorder()
                it.setApplicationActive(false)
                it.setApplicationActive(true)
                // Delayed OS results must not restart a session behind setup.
                it.onLocationPermissionResult(true)
                it.onCameraPermissionResult(true)
            }
            instrumentation.waitForIdleSync()
            assertEquals(0, state().onboardingStep)
            assertFalse(state().onboardingCompleted)
            assertEquals("stopped", state().driveStatus)
            assertFalse(state().syncStatus.startsWith("syncing"))
            assertEquals(0, host.locationRequests)
            assertEquals(0, host.cameraRequests)
            assertEquals(0, host.microphoneRequests)
            assertEquals(0, host.cameraStarts)
        } finally {
            if (initialized) act { it.dispose() }
            base.deleteSharedPreferences("$id-youspeed")
            root.deleteRecursively()
        }
    }

    private class QuietHost : ConsumerHost {
        var locationRequests = 0
        var cameraRequests = 0
        var microphoneRequests = 0
        var cameraStarts = 0
        override fun requestLocationPermission() { locationRequests++ }
        override fun requestMicrophonePermission() { microphoneRequests++ }
        override fun requestCameraPermission() { cameraRequests++ }
        override fun startTrafficSignCamera() { cameraStarts++ }
        override fun stopTrafficSignCamera() {}
        override fun capturePanoramaxPhoto(requestId: String) {}
        override fun showTransientMessage(message: String) {}
        override fun openExternalUrl(url: String) {}
        override fun shareFile(path: String, mimeType: String) {}
    }
}

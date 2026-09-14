package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import java.io.File
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Real Activity/configuration changes; the deterministic fixture requires no camera or GPS. */
@RunWith(AndroidJUnit4::class)
class ManualOrientationLayoutInstrumentedTest {
    @Test fun selectedMountRepositionsStablePanesWithoutLosingConfirmedSign() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val key = "youspeed.manual_orientation"
        val previous = preferences.getString(key, null)
        val device = UiDevice.getInstance(instrumentation)
        try {
            assertTrue(preferences.edit().putString(key, ManualOrientation.PORTRAIT.storageValue).commit())
            ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)
                .putExtra("screenshot_state", "other-sign-give-way")).use { scenario ->
                lateinit var activity: MainActivity
                lateinit var controller: ConsumerSessionController
                scenario.onActivity { activity = it; controller = it.sessionController }
                val confirmedPictogram = controller.uiState.lastTrafficSignPictogram
                assertNotNull(confirmedPictogram)
                for (orientation in ManualOrientation.entries + ManualOrientation.PORTRAIT) {
                    scenario.onActivity { it.sessionController.setManualOrientation(orientation) }
                    val deadline = SystemClock.uptimeMillis() + 15_000
                    var ready = false
                    while (SystemClock.uptimeMillis() < deadline) {
                        val sign = device.findObject(By.res("main-sign-pane"))?.visibleBounds
                        val workspace = device.findObject(By.res("main-workspace-pane"))?.visibleBounds
                        val arranged = sign != null && workspace != null &&
                            if (orientation.isLandscape) sign.right <= workspace.left && sign.centerX() < workspace.centerX()
                            else sign.bottom <= workspace.top && sign.centerY() < workspace.centerY()
                        if (device.displayRotation == orientation.targetRotation && arranged) { ready = true; break }
                        SystemClock.sleep(50)
                    }
                    assertTrue("Pane order and rotation for $orientation", ready)
                    scenario.onActivity {
                        assertSame("Rotation retains the Activity", activity, it)
                        assertSame("Rotation retains the driving controller", controller, it.sessionController)
                        assertEquals(orientation.requestedOrientation, it.requestedOrientation)
                        assertEquals(orientation, it.sessionController.uiState.manualOrientation)
                        assertEquals("Changing mount preserves a confirmed scalar limit", 30, it.sessionController.uiState.speedLimitKmh)
                        assertEquals(EffectiveSpeedLimitSource.CAMERA, it.sessionController.uiState.effectiveSpeedLimitSource)
                        assertEquals(confirmedPictogram, it.sessionController.uiState.lastTrafficSignPictogram)
                    }
                    val screen = device.findObject(By.res("main-root")).visibleBounds
                    for (tag in listOf("speed-sign", "settings-button", "drive-recorder-toggle-button", "city-badge")) {
                        val bounds = device.findObject(By.res(tag))?.visibleBounds
                        assertNotNull("$tag visible in $orientation", bounds)
                        assertTrue("$tag has usable bounds in $orientation", requireNotNull(bounds).width() > 0 && bounds.height() > 0)
                        assertTrue("$tag stays inside the screen in $orientation", screen.contains(bounds))
                    }
                    assertTrue(device.takeScreenshot(File(context.cacheDir, "manual-${orientation.storageValue}.png")))
                }
            }
        } finally {
            val restore = preferences.edit()
            if (previous == null) restore.remove(key) else restore.putString(key, previous)
            assertTrue(restore.commit())
        }
    }
}

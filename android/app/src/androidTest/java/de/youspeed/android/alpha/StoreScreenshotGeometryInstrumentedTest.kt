package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Measures the real moving recorder pane so marketing pixels stay inside its native bounds. */
@RunWith(AndroidJUnit4::class)
class StoreScreenshotGeometryInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()

    @Test fun movingRecorderRetainsItsPreviewInsideTheWindow() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val key = "youspeed.manual_orientation"
        val previous = preferences.getString(key, null)
        val device = UiDevice.getInstance(instrumentation)
        try {
            assertTrue(preferences.edit().putString(key, ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT.storageValue).commit())
            ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)
                .putExtra("screenshot_state", "camera-limit-active")
                .putExtra("screenshot_dashcam", true)
                .putExtra("screenshot_speed", 27)).use { scenario ->
                compose.waitUntil(15_000) { device.displayWidth > device.displayHeight }
                scenario.onActivity {
                    assertEquals(27.0, it.sessionController.uiState.currentSpeedKmh, 0.0)
                    assertFalse(it.sessionController.uiState.drivingControlsAllowed)
                }
                val pane = compose.onNodeWithTag("recorder-camera-preview").fetchSemanticsNode().boundsInWindow
                assertTrue(pane.left >= 0 && pane.top >= 0)
                assertTrue(pane.right <= device.displayWidth && pane.bottom <= device.displayHeight)
                assertTrue(pane.width > 0 && pane.height > 0)
                File(context.cacheDir, "store-moving-preview-bounds.txt").writeText(
                    "${pane.left},${pane.top},${pane.width},${pane.height}\n")
            }
        } finally {
            val edit = preferences.edit()
            if (previous == null) edit.remove(key) else edit.putString(key, previous)
            assertTrue(edit.commit())
        }
    }
}

package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class MobiDataSourceContourInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()

    @Test fun sourceChangesPreserveGeometryAndCameraBrackets() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        check(context.packageName.endsWith(".testhost")) { "Use the isolated app; never the driver's installation" }
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val key = "youspeed.manual_orientation"
        val previous = preferences.getString(key, null)
        val device = UiDevice.getInstance(instrumentation)
        try {
            for (orientation in listOf(ManualOrientation.PORTRAIT, ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT)) {
                assertTrue(preferences.edit().putString(key, orientation.storageValue).commit())
                var original: androidx.compose.ui.geometry.Rect? = null
                for (fixture in listOf("osm-inventory-signs", "mobidata-signs", "camera-limit-active")) {
                    ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)
                        .putExtra("screenshot_state", fixture)).use {
                        compose.waitUntil(20_000) { (device.displayWidth > device.displayHeight) == orientation.isLandscape }
                        compose.waitForIdle()
                        val sign = compose.onNodeWithTag("speed-sign")
                        sign.assertExists()
                        if (fixture == "mobidata-signs") {
                            sign.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "MobiData"))
                            compose.onNodeWithTag("mobidata-sign-source-contour", useUnmergedTree = true).assertExists()
                        } else {
                            sign.assert(SemanticsMatcher.keyNotDefined(SemanticsProperties.StateDescription))
                            compose.onNodeWithTag("mobidata-sign-source-contour", useUnmergedTree = true).assertDoesNotExist()
                        }
                        if (fixture == "camera-limit-active") compose.onNodeWithTag("camera-speed-source-marker").assertExists()
                        else compose.onNodeWithTag("camera-speed-source-marker").assertDoesNotExist()
                        val bounds = sign.fetchSemanticsNode().boundsInWindow
                        original?.let { expected ->
                            assertEquals(expected.left, bounds.left, 0.5f)
                            assertEquals(expected.top, bounds.top, 0.5f)
                            assertEquals(expected.width, bounds.width, 0.5f)
                            assertEquals(expected.height, bounds.height, 0.5f)
                        } ?: run { original = bounds }
                        compose.onNodeWithTag("speed-evidence-source").assertDoesNotExist()
                        compose.onNodeWithTag("dashboard-tsr-activity").assertDoesNotExist()
                        assertTrue(device.takeScreenshot(File(context.filesDir, "source-contour-$fixture-${orientation.storageValue}.png")))
                    }
                }
            }
        } finally {
            val edit = preferences.edit()
            if (previous == null) edit.remove(key) else edit.putString(key, previous)
            assertTrue(edit.commit())
        }
    }
}

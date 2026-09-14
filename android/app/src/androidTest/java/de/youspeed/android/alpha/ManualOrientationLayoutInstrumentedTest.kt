package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.graphics.RectF
import android.view.WindowInsets
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Real Activity/configuration changes; the deterministic fixture requires no camera or GPS. */
@RunWith(AndroidJUnit4::class)
class ManualOrientationLayoutInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()

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
                    compose.waitForIdle()
                    var ready = false
                    // Let the Compose test clock drive recomposition and
                    // measure passes while Android completes window rotation.
                    // UiAutomator polling alone leaves that clock suspended.
                    compose.waitUntil(15_000) {
                        val sign = compose.onAllNodesWithTag("main-sign-pane").fetchSemanticsNodes()
                            .singleOrNull()?.boundsInWindow
                        val workspace = compose.onAllNodesWithTag("main-workspace-pane").fetchSemanticsNodes()
                            .singleOrNull()?.boundsInWindow
                        val arranged = if (orientation.isLandscape) {
                            sign != null && workspace != null &&
                                sign.right <= workspace.left && sign.center.y >= workspace.top && sign.center.y <= workspace.bottom
                        } else {
                            sign != null && workspace != null &&
                                sign.bottom <= workspace.top &&
                                kotlin.math.abs(sign.center.x - workspace.center.x) <= 1f
                        }
                        ready = device.displayRotation == orientation.targetRotation && arranged
                        ready
                    }
                    assertTrue("Pane order and rotation for $orientation", ready)
                    compose.waitForIdle()
                    scenario.onActivity {
                        assertSame("Rotation retains the Activity", activity, it)
                        assertSame("Rotation retains the driving controller", controller, it.sessionController)
                        assertEquals(orientation.requestedOrientation, it.requestedOrientation)
                        assertEquals(orientation, it.sessionController.uiState.manualOrientation)
                        assertEquals("Changing mount preserves a confirmed scalar limit", 30, it.sessionController.uiState.speedLimitKmh)
                        assertEquals(EffectiveSpeedLimitSource.CAMERA, it.sessionController.uiState.effectiveSpeedLimitSource)
                        assertEquals(confirmedPictogram, it.sessionController.uiState.lastTrafficSignPictogram)
                        assertEquals("GPS remains available for diagnostics", 4, it.sessionController.uiState.gpsSignalBars)
                        assertEquals(5.0, requireNotNull(it.sessionController.uiState.gpsHorizontalAccuracyM), 0.0)
                    }
                    val screen = device.findObject(By.res("main-root")).visibleBounds
                    for (tag in listOf("speed-sign", "settings-button", "drive-recorder-toggle-button", "city-badge")) {
                        val bounds = device.findObject(By.res(tag))?.visibleBounds
                        assertNotNull("$tag visible in $orientation", bounds)
                        assertTrue("$tag has usable bounds in $orientation", requireNotNull(bounds).width() > 0 && bounds.height() > 0)
                        assertTrue("$tag stays inside the screen in $orientation", screen.contains(bounds))
                    }
                    assertDashboardControls(activity, device, orientation)
                    assertTrue(device.takeScreenshot(File(context.cacheDir, "manual-${orientation.storageValue}.png")))
                }
            }
        } finally {
            val restore = preferences.edit()
            if (previous == null) restore.remove(key) else restore.putString(key, previous)
            assertTrue(restore.commit())
        }
    }

    @Test fun portraitFooterFitsFiveEvenlySpacedButtonsAt320Dp() {
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
                scenario.onActivity {
                    activity = it
                    val controller = it.sessionController
                    it.setContent {
                        Box(Modifier.fillMaxSize()) {
                            Box(Modifier.width(320.dp).fillMaxHeight()) { ConsumerApp(controller) }
                        }
                    }
                }
                compose.waitUntil(15_000) { device.displayRotation == ManualOrientation.PORTRAIT.targetRotation }
                compose.waitForIdle()
                val density = context.resources.displayMetrics.density
                assertEquals("The narrow portrait width is actually rendered", 320 * density,
                    compose.onNodeWithTag("main-root").fetchSemanticsNode().size.width.toFloat(), 1f)
                assertDashboardControls(activity, device, ManualOrientation.PORTRAIT)
                assertTrue(device.takeScreenshot(File(context.cacheDir, "manual-portrait-320dp.png")))
            }
        } finally {
            val restore = preferences.edit()
            if (previous == null) restore.remove(key) else restore.putString(key, previous)
            assertTrue(restore.commit())
        }
    }

    private fun assertDashboardControls(activity: MainActivity, device: UiDevice, orientation: ManualOrientation) {
        compose.waitForIdle()
        assertTrue("The dashboard has no GPS icon/accuracy badge",
            compose.onAllNodesWithTag("gps-badge").fetchSemanticsNodes().isEmpty())
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val density = activity.resources.displayMetrics.density
        val origin = IntArray(2)
        lateinit var safe: RectF
        instrumentation.runOnMainSync {
            val root = activity.window.decorView
            root.getLocationOnScreen(origin)
            val insets = requireNotNull(root.rootWindowInsets).getInsets(
                WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            safe = RectF(insets.left.toFloat(), insets.top.toFloat(),
                device.displayWidth - insets.right.toFloat(), device.displayHeight - insets.bottom.toFloat())
        }
        fun bounds(tag: String): RectF {
            val nodes = compose.onAllNodesWithTag(tag).fetchSemanticsNodes()
            assertEquals("Exactly one $tag is present", 1, nodes.size)
            val node = nodes.single()
            val position = node.positionInWindow
            val raw = RectF(position.x + origin[0], position.y + origin[1],
                position.x + origin[0] + node.size.width, position.y + origin[1] + node.size.height)
            assertTrue("$tag stays inside safe screen $safe: $raw", raw.left >= safe.left - 1 &&
                raw.top >= safe.top - 1 && raw.right <= safe.right + 1 && raw.bottom <= safe.bottom + 1)
            assertEquals("$tag is not horizontally clipped", raw.width(), node.boundsInWindow.width, 1f)
            assertEquals("$tag is not vertically clipped", raw.height(), node.boundsInWindow.height, 1f)
            return raw
        }
        val footer = bounds("dashboard-bottom-controls")
        val footerTags = mutableListOf("drive-recorder-toggle-button")
        footerTags += "local-recordings-button"
        footerTags += listOf("panoramax-gallery-button", "legal-button", "settings-button")
        val buttons = footerTags.map { tag ->
            bounds(tag).also { button ->
                assertTrue("$tag has a 48dp target", button.width() >= 48 * density - 1 && button.height() >= 48 * density - 1)
                assertTrue("$tag belongs to the bottom row", footer.contains(button))
            }
        }
        assertTrue("The controls stay at the bottom", safe.bottom - footer.bottom <= 24 * density + 1)
        if (!orientation.isLandscape) {
            val gaps = buttons.zipWithNext { left, right -> right.left - left.right }
            assertTrue("All five controls have generous spacing", gaps.all { it >= 8 * density - 1 })
            assertTrue("The five controls are evenly spaced", requireNotNull(gaps.maxOrNull()) - requireNotNull(gaps.minOrNull()) <= 2)
            assertTrue("Every portrait control is on one row", buttons.all { kotlin.math.abs(it.top - buttons.first().top) <= 1 })
        }
        bounds("last-traffic-sign-pictogram")
        bounds("camera-speed-source-marker")
    }
}

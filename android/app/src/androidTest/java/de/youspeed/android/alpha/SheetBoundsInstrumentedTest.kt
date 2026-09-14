package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.graphics.RectF
import android.os.SystemClock
import android.view.View
import android.view.WindowInsets
import android.view.inspector.WindowInspector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasScrollAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.By
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Uses measured, unclipped Compose bounds: visibleBounds alone hides overflow. */
@RunWith(AndroidJUnit4::class)
class SheetBoundsInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val device = UiDevice.getInstance(instrumentation)

    @Test fun openSettingsResizesThroughBothLandscapeMountsAndPortraitKeyboard() = withDashboard { scenario ->
        clickDashboard("settings-button")
        waitFor("settings-sheet-close")
        val originalWindow = focusedWindow()
        for (mount in listOf(ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT,
            ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT)) {
            compose.onNodeWithTag("orientation-${mount.storageValue}").performClick()
            waitForRotation(mount)
            assertSheetBounds("settings-sheet")
            compose.onNodeWithTag("orientation-portrait").performClick()
            waitForRotation(ManualOrientation.PORTRAIT)
            assertSame("The open sheet and its input state survive rotation", originalWindow, focusedWindow())
            assertSheetBounds("settings-sheet")
        }
        capture("settings-portrait")
        scenario.onActivity { it.sessionController.setAudioAlertsEnabled(true) }
        compose.onNode(hasScrollAction() and hasAnyAncestor(hasTestTag("settings-sheet-content")))
            .performScrollToNode(hasTestTag("audio-alert-threshold"))
        compose.onNodeWithTag("audio-alert-threshold").performClick()
        compose.waitUntil(10_000) {
            focusedWindow().rootWindowInsets?.isVisible(WindowInsets.Type.ime()) == true
        }
        waitForSettledKeyboard()
        assertSheetBounds("settings-sheet")
        // Compose's own coordinates can remain unchanged while Android pans a
        // native dialog. Check the final accessibility bounds on screen as well.
        for (tag in listOf("settings-sheet-close", "settings-sheet-title")) {
            val native = device.findObject(By.res(tag))
            assertNotNull("$tag remains visible above the settled keyboard", native)
            val visible = requireNotNull(native).visibleBounds
            val measured = compose.onNodeWithTag(tag).fetchSemanticsNode().size
            assertEquals("$tag native width is not clipped", measured.width.toFloat(), visible.width().toFloat(), 1f)
            assertEquals("$tag native height is not clipped", measured.height.toFloat(), visible.height().toFloat(), 1f)
            assertTrue("$tag remains within the physical screen", visible.left >= 0 && visible.top >= 0 &&
                visible.right <= device.displayWidth && visible.bottom <= device.displayHeight)
        }
        capture("settings-portrait-keyboard")
        device.pressBack()
        compose.waitUntil(10_000) {
            focusedWindow().rootWindowInsets?.isVisible(WindowInsets.Type.ime()) != true
        }
        compose.onNodeWithTag("settings-sheet-close").performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("settings-sheet").fetchSemanticsNodes().isEmpty() }
    }

    @Test fun portraitLegalCreditsRecordingsAndGalleryStayInsideSafeWindow() = withDashboard {
        clickDashboard("legal-button")
        assertSheetBounds("legal-sheet")
        compose.onNodeWithTag("attribution-button").performClick()
        assertSheetBounds("attribution-sheet")
        compose.onNodeWithTag("attribution-sheet-close").performClick()
        compose.onNodeWithTag("legal-sheet-close").performClick()
        clickDashboard("local-recordings-button")
        assertSheetBounds("local-recordings-sheet")
        assertTagsInsideSafeWindow(listOf("local-export-button", "local-delete-all-button"))
        capture("recordings-portrait")
        compose.onNodeWithTag("local-recordings-sheet-close").performClick()
        clickDashboard("panoramax-gallery-button")
        assertSheetBounds("panoramax-gallery-sheet")
        val actions = compose.onAllNodes(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button) and
            hasAnyAncestor(hasTestTag("panoramax-gallery-sheet-content"))).fetchSemanticsNodes()
        assertTrue("Photo gallery exposes all four actions", actions.size >= 4)
        assertNodesInsideSafeWindow(actions.mapIndexed { index, node -> "gallery-action-$index" to node })
        val barActions = compose.onAllNodesWithTag("gallery-action").fetchSemanticsNodes()
        assertEquals("Photo gallery action bar keeps all four actions", 4, barActions.size)
        val minimum = 48 * context.resources.displayMetrics.density - 1
        barActions.forEach { assertTrue("Gallery action has at least 48dp height", it.size.height >= minimum) }
        capture("gallery-portrait")
        compose.onNodeWithTag("panoramax-gallery-sheet-close").performClick()
    }

    private fun withDashboard(block: (ActivityScenario<MainActivity>) -> Unit) {
        val preferences = context.getSharedPreferences("youspeed", Context.MODE_PRIVATE)
        val keys = listOf("youspeed.manual_orientation", "youspeed.audio_alerts_enabled")
        val previous = preferences.all.filterKeys { it in keys }
        try {
            assertTrue(preferences.edit().putString(keys.first(), ManualOrientation.PORTRAIT.storageValue).commit())
            ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)
                .putExtra("screenshot_state", "other-sign-give-way")).use { scenario ->
                waitForRotation(ManualOrientation.PORTRAIT)
                waitFor("settings-button")
                block(scenario)
            }
        } finally {
            val restore = preferences.edit()
            keys.forEach { restore.remove(it) }
            previous.forEach { (key, value) -> when (value) {
                is String -> restore.putString(key, value)
                is Boolean -> restore.putBoolean(key, value)
            } }
            assertTrue(restore.commit())
        }
    }

    private fun clickDashboard(tag: String) {
        waitFor(tag)
        compose.onNode(hasClickAction() and hasAnyAncestor(hasTestTag(tag)), useUnmergedTree = true).performClick()
    }

    private fun waitFor(tag: String) {
        compose.waitUntil(10_000) { compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun waitForRotation(orientation: ManualOrientation) {
        compose.waitUntil(15_000) { device.displayRotation == orientation.targetRotation }
        compose.waitForIdle()
    }

    private fun focusedWindow(): View {
        lateinit var result: View
        instrumentation.runOnMainSync {
            result = WindowInspector.getGlobalWindowViews().last { it.hasWindowFocus() }
        }
        return result
    }

    private fun waitForSettledKeyboard() {
        var previous = ""
        var unchangedSince = SystemClock.uptimeMillis()
        compose.waitUntil(10_000) {
            val window = focusedWindow()
            val origin = IntArray(2)
            var imeBottom = 0
            instrumentation.runOnMainSync {
                window.getLocationOnScreen(origin)
                imeBottom = window.rootWindowInsets?.getInsets(WindowInsets.Type.ime())?.bottom ?: 0
            }
            // Avoid UiAutomator's implicit idle wait inside Compose's polling
            // loop (the text cursor can keep the accessibility tree busy).
            val current = "${origin.toList()}:$imeBottom:${window.width}:${window.height}"
            val now = SystemClock.uptimeMillis()
            if (current != previous) {
                previous = current
                unchangedSince = now
            }
            now - unchangedSince >= 800
        }
    }

    private fun assertSheetBounds(tag: String) {
        waitFor("$tag-close")
        compose.waitForIdle()
        assertTagsInsideSafeWindow(listOf(tag, "$tag-header", "$tag-close", "$tag-title", "$tag-content"))
        val close = compose.onNodeWithTag("$tag-close").fetchSemanticsNode()
        val title = compose.onNodeWithTag("$tag-title").fetchSemanticsNode()
        assertTrue("Close is left of the title", close.positionInWindow.x + close.size.width <= title.positionInWindow.x)
        val minimum = 48 * context.resources.displayMetrics.density - 1
        assertTrue("Close has a 48dp touch target", close.size.width >= minimum && close.size.height >= minimum)
    }

    private fun assertTagsInsideSafeWindow(tags: List<String>) = assertNodesInsideSafeWindow(
        tags.map { it to compose.onNodeWithTag(it).fetchSemanticsNode() })

    private fun assertNodesInsideSafeWindow(nodes: List<Pair<String, SemanticsNode>>) {
        val window = focusedWindow()
        val origin = IntArray(2)
        lateinit var safe: RectF
        instrumentation.runOnMainSync {
            window.getLocationOnScreen(origin)
            val inset = requireNotNull(window.rootWindowInsets).getInsets(
                WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime())
            safe = RectF(inset.left.toFloat(), inset.top.toFloat(),
                device.displayWidth - inset.right.toFloat(), device.displayHeight - inset.bottom.toFloat())
        }
        for ((tag, node) in nodes) {
            val position = node.positionInWindow
            val raw = RectF(position.x + origin[0], position.y + origin[1],
                position.x + origin[0] + node.size.width, position.y + origin[1] + node.size.height)
            assertTrue("$tag has nonempty bounds: $raw", raw.width() > 0 && raw.height() > 0)
            assertTrue("$tag unclipped bounds $raw fit safe screen $safe", raw.left >= safe.left - 1 &&
                raw.top >= safe.top - 1 && raw.right <= safe.right + 1 && raw.bottom <= safe.bottom + 1)
            assertEquals("$tag is not horizontally clipped", node.size.width.toFloat(), node.boundsInWindow.width, 1f)
            assertEquals("$tag is not vertically clipped", node.size.height.toFloat(), node.boundsInWindow.height, 1f)
        }
    }

    private fun capture(name: String) {
        assertTrue(device.takeScreenshot(File(context.cacheDir, "sheet-bounds-$name.png")))
    }
}

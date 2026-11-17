package de.youspeed.android.alpha

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.graphics.BitmapFactory
import android.os.SystemClock
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File
import java.util.concurrent.atomic.AtomicReference
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Rule
import org.junit.After
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AttributionInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private var scenario: ActivityScenario<MainActivity>? = null

    @After fun closeApp() { scenario?.close(); scenario = null }

    @Test fun packagedCreditsAndFullNoticesAreAvailableOfflineFromInfo() {
        val catalog = context.assets.open(AttributionCatalog.ASSET_PATH).bufferedReader().use { AttributionCatalog.decode(it.readText()) }
        val artworkIds = context.assets.open("tsr/sign-pictograms/manifest.json").bufferedReader().use {
            Json.parseToJsonElement(it.readText()).jsonObject.getValue("artworks").jsonArray
                .map { artwork -> "sign-" + artwork.jsonObject.getValue("sign_code").jsonPrimitive.content }.toSet()
        }
        assertTrue(artworkIds.isNotEmpty())
        assertEquals(artworkIds, catalog.entries.filter { it.category == "sign" && it.id.startsWith("sign-DE:") }.map { it.id }.toSet())
        for (path in AttributionCatalog.NOTICE_PATHS) {
            assertTrue(context.assets.open(path).bufferedReader().use { it.readText() }.isNotBlank())
        }
        context.assets.open("attributions/brands/mapillary-logo.png").use {
            assertNotNull("The packaged Mapillary logo must decode", BitmapFactory.decodeStream(it))
        }
        val launch = Intent(Intent.ACTION_MAIN).apply {
            setClassName(context.packageName, "de.youspeed.android.alpha.MainActivity")
            addCategory(Intent.CATEGORY_LAUNCHER)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            putExtra("screenshot_state", "other-sign-stop")
        }
        scenario = ActivityScenario.launch(launch)
        compose.waitForIdle()
        waitFor("legal-button")
        compose.onNode(hasClickAction() and hasAnyAncestor(hasTestTag("legal-button")), useUnmergedTree = true).performClick()
        waitFor("legal-sheet")
        compose.onNodeWithTag("mapillary-attribution-link").performScrollTo().assertIsDisplayed().assertHasClickAction()
        capture("info-mapillary")
        val openedUrl = AtomicReference<String?>()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val monitor = object : Instrumentation.ActivityMonitor() {
            override fun onStartActivity(intent: Intent): Instrumentation.ActivityResult? {
                if (intent.action != Intent.ACTION_VIEW) return null
                openedUrl.set(intent.dataString)
                return Instrumentation.ActivityResult(Activity.RESULT_OK, null)
            }
        }
        instrumentation.addMonitor(monitor)
        try {
            compose.onNodeWithTag("mapillary-attribution-link").performClick()
            assertEquals("https://www.mapillary.com/", openedUrl.get())
        } finally {
            instrumentation.removeMonitor(monitor)
        }
        compose.onNodeWithTag("attribution-button").performScrollTo().performClick()
        waitFor("attribution-list")
        capture("info-sources")
        scrollTo("mapillary-attribution-link")
        compose.onNode(hasTestTag("mapillary-attribution-link") and hasAnyAncestor(hasTestTag("attribution-list")))
            .assertIsDisplayed().assertHasClickAction()
        capture("info-mapillary-credit")
        val first = catalog.entries.first { it.category == "data" }
        scrollTo("credit-${first.id}")
        compose.onNodeWithTag("credit-${first.id}").performClick()
        for (tag in listOf("source-${first.id}", "license-${first.id}")) {
            scrollTo(tag)
            compose.onNodeWithTag(tag).assertHasClickAction().assertIsDisplayed()
        }
        scrollTo("credit-${first.id}")
        capture("info-source-detail")
        for (path in AttributionCatalog.NOTICE_PATHS) {
            scrollTo("notice-${path.replace('/', '-')}")
            compose.onNodeWithTag("notice-${path.replace('/', '-')}").performClick()
            waitFor("attribution-notice-text")
            capture("info-notice-${path.replace('/', '-')}")
            device.pressBack()
            waitFor("attribution-list")
        }
        device.pressBack()
        waitFor("legal-sheet")
        device.pressBack()
        waitFor("main-root")
    }

    private fun waitFor(tag: String) {
        // Compose owns the test frame clock, including frames scheduled after asset IO.
        try {
            compose.waitUntil(timeoutMillis = 20_000) {
                compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty()
            }
        } catch (failure: androidx.compose.ui.test.ComposeTimeoutException) {
            device.dumpWindowHierarchy(File(context.cacheDir, "attribution-failed-hierarchy.xml"))
            device.takeScreenshot(File(context.cacheDir, "attribution-failed-screen.png"))
            throw AssertionError("Attribution screen did not expose $tag; evidence retained in app cache", failure)
        }
    }

    private fun scrollTo(tag: String) {
        compose.onNodeWithTag("attribution-list").performScrollToNode(hasTestTag(tag))
    }

    private fun capture(name: String) {
        device.waitForIdle()
        SystemClock.sleep(500)
        assertTrue(device.takeScreenshot(File(context.getExternalFilesDir(null), "$name.png")))
    }
}

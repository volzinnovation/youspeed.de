package de.youspeed.android.alpha

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Stateless UI fixtures: no app preferences, maps, onboarding data or display settings are changed. */
@RunWith(AndroidJUnit4::class)
class PortraitContentLayoutInstrumentedTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private data class Viewport(val widthDp: Int, val fontScale: Float)
    private val narrowViewports = listOf(Viewport(320, 1.5f), Viewport(360, 1.3f))
    private val viewport = mutableStateOf<Viewport?>(narrowViewports.first())
    private val ui = mutableStateOf(ConsumerUiState())

    @Test fun longStartupFailureKeepsRetryReachableWithLargePortraitText() {
        var retries = 0
        ui.value = ConsumerUiState(
            startupDataState = StartupDataState.FAILED,
            startupProgress = 0.45,
            startupDetail = "The downloaded map could not be opened. Please retry after checking the connection.",
            lastError = (1..14).joinToString("\n") {
                "Attempt $it: the map download was interrupted before its contents could be verified. The saved map remains available."
            },
        )
        render { StartupScreen(ui.value, onRetry = { retries++ }) }
        for (size in narrowViewports) {
            compose.runOnIdle { viewport.value = size }
            assertViewportSize(size.widthDp)
            assertInsideViewport(compose.onNodeWithTag("startup-content"))
            val retry = compose.onNodeWithTag("startup-retry-button")
            retry.assertIsNotDisplayed()
            retry.performScrollTo().assertIsDisplayed().assertIsEnabled()
            assertInsideViewport(retry, minimumTouchSizeDp = 48)
            retry.performClick()
        }
        compose.runOnIdle { assertEquals(narrowViewports.size, retries) }

        // Capture the unchanged device viewport as well as exercising narrow
        // compositional constraints above. No wm size/density override is used.
        compose.runOnIdle { viewport.value = null }
        capture("startup-failure")
        compose.onNodeWithTag("startup-retry-button").performScrollTo().assertIsDisplayed()
        capture("startup-retry")
    }

    @Test fun everyOnboardingStepFitsPortraitAndKeepsNavigationOutsideScrollingContent() {
        var nextCount = 0
        var backCount = 0
        ui.value = ConsumerUiState(
            preciseLocationGranted = true,
            trafficSignRecognitionEnabled = true,
            audioAlertsEnabled = true,
        )
        render {
            OnboardingScreen(
                ui = ui.value,
                hasUsableMap = true,
                isSyncing = false,
                onNext = { nextCount++ },
                onBack = { backCount++ },
                onUseLocation = {},
                onOpenLocationSettings = {},
                onSelectMap = {},
                onDownloadMap = {},
                onAudioEnabled = {},
                onAudioThreshold = {},
                onRecognitionEnabled = {},
                onIndependentRecognitionEnabled = {},
                onPanoramaxEnabled = {},
            )
        }
        for (size in narrowViewports) {
            compose.runOnIdle { viewport.value = size }
            assertViewportSize(size.widthDp)
            for (step in 0..4) {
                compose.runOnIdle { ui.value = ui.value.copy(onboardingStep = step) }
                assertOnboardingNavigation(step)
                val contentTarget = when (step) {
                    0 -> compose.onNodeWithTag("onboarding-choose-map-button")
                    1 -> compose.onNodeWithTag("onboarding-threshold-increase")
                    2 -> compose.onNodeWithContentDescription(context.getString(R.string.onboarding_video_screenshot))
                    3 -> compose.onNodeWithTag("onboarding-independent-toggle")
                    else -> compose.onNodeWithTag("onboarding-panoramax-toggle")
                }
                contentTarget.performScrollTo().assertIsDisplayed()
                assertInsideViewport(contentTarget)
                // Scrolling instructional content must not move either footer control.
                assertOnboardingNavigation(step)
                compose.onNodeWithTag("onboarding-next-button").performClick()
                if (step > 0) compose.onNodeWithTag("onboarding-back-button").performClick()
            }
        }
        compose.runOnIdle {
            assertEquals(10, nextCount)
            assertEquals(8, backCount)
            viewport.value = null
        }
        for (step in 0..4) {
            compose.runOnIdle { ui.value = ui.value.copy(onboardingStep = step) }
            assertOnboardingNavigation(step)
            capture("onboarding-step-$step")
        }
    }

    private fun render(content: @Composable () -> Unit) {
        compose.setContent {
            val baseDensity = LocalDensity.current
            val size = viewport.value
            MaterialTheme {
                Surface(Modifier.fillMaxSize(), color = Color.Black) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                        CompositionLocalProvider(LocalDensity provides Density(
                            baseDensity.density, size?.fontScale ?: baseDensity.fontScale,
                        )) {
                            key(size) {
                                val dimensions = size?.let { Modifier.size(it.widthDp.dp, 560.dp) }
                                    ?: Modifier.fillMaxSize()
                                Box(dimensions.clipToBounds().testTag("portrait-content-viewport")) {
                                    content()
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private fun assertViewportSize(widthDp: Int) {
        val node = compose.onNodeWithTag("portrait-content-viewport").fetchSemanticsNode()
        val density = context.resources.displayMetrics.density
        assertEquals("The requested narrow width is actually rendered", widthDp * density, node.size.width.toFloat(), 1f)
        assertEquals("The fixture has a bounded portrait height", 560 * density, node.size.height.toFloat(), 1f)
    }

    private fun assertOnboardingNavigation(step: Int) {
        assertInsideViewport(compose.onNodeWithTag("onboarding-content"))
        val next = compose.onNodeWithTag("onboarding-next-button")
        next.assertIsDisplayed().assertIsEnabled()
        assertInsideViewport(next, minimumTouchSizeDp = 48)
        if (step > 0) {
            val back = compose.onNodeWithTag("onboarding-back-button")
            back.assertIsDisplayed().assertIsEnabled()
            assertInsideViewport(back, minimumTouchSizeDp = 48)
        }
    }

    private fun assertInsideViewport(interaction: SemanticsNodeInteraction, minimumTouchSizeDp: Int = 0) {
        val viewportNode = compose.onNodeWithTag("portrait-content-viewport").fetchSemanticsNode()
        val node = interaction.fetchSemanticsNode()
        val parent = Rect(viewportNode.positionInRoot.x, viewportNode.positionInRoot.y,
            viewportNode.positionInRoot.x + viewportNode.size.width, viewportNode.positionInRoot.y + viewportNode.size.height)
        val raw = Rect(node.positionInRoot.x, node.positionInRoot.y,
            node.positionInRoot.x + node.size.width, node.positionInRoot.y + node.size.height)
        assertTrue("Nonempty layout bounds: $raw", raw.width > 0 && raw.height > 0)
        assertTrue("Unclipped node $raw stays inside viewport $parent", raw.left >= parent.left - 1 &&
            raw.top >= parent.top - 1 && raw.right <= parent.right + 1 && raw.bottom <= parent.bottom + 1)
        assertEquals("No horizontal clipping", raw.width, node.boundsInRoot.width, 1f)
        assertEquals("No vertical clipping", raw.height, node.boundsInRoot.height, 1f)
        if (minimumTouchSizeDp > 0) {
            val minimum = minimumTouchSizeDp * context.resources.displayMetrics.density - 1
            assertTrue("At least ${minimumTouchSizeDp}dp touch bounds: $raw", raw.width >= minimum && raw.height >= minimum)
        }
    }

    private fun capture(name: String) {
        val bitmap = compose.onNodeWithTag("portrait-content-viewport").captureToImage().asAndroidBitmap()
        File(context.cacheDir, "portrait-content-$name.png").outputStream().use {
            assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
        }
    }
}

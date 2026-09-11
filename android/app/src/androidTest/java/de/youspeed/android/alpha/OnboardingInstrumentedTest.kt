package de.youspeed.android.alpha

import android.graphics.Bitmap
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises the real walkthrough UI without accessing the user's maps or preferences. */
@RunWith(AndroidJUnit4::class)
class OnboardingInstrumentedTest {
    @get:Rule val compose = createComposeRule()
    private val ui = mutableStateOf(ConsumerUiState())
    private val mapReady = mutableStateOf(false)
    private val syncing = mutableStateOf(false)
    private var nextCount = 0
    private var downloadCount = 0
    private var settingsCount = 0
    private var selectedMap: String? = null

    @Test fun manualMapChoiceAndDownloadNeverBypassActivation() {
        val option = BundleDownloadOption(
            "test-region", "DE", "Germany", "Test region",
            V3ManifestEndpoint("de", "DE", "test-region", "test-region", "Test region", "https://example.invalid/manifest.json"),
        )
        ui.value = ConsumerUiState(
            bundleDownloadSections = listOf(BundleDownloadCountrySection("de", "DE", "Germany", listOf(option))),
        )
        render()
        compose.onNodeWithTag("onboarding-next-button").assertIsNotEnabled()
        compose.onNodeWithTag("onboarding-choose-map-button").performScrollTo().performClick()
        compose.onNodeWithTag("onboarding-map-choice-test-region").performScrollTo().performClick()
        compose.runOnIdle { assertEquals("test-region", selectedMap) }
        compose.onNodeWithTag("onboarding-map-download-button").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, downloadCount); syncing.value = true }
        compose.onNodeWithTag("onboarding-next-button").assertIsNotEnabled()
        compose.runOnIdle {
            syncing.value = false
            ui.value = ui.value.copy(syncStatus = "failed", lastError = "Download interrupted")
        }
        compose.onNodeWithTag("onboarding-next-button").assertIsNotEnabled()
        compose.onNodeWithTag("onboarding-map-download-button").performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals(2, downloadCount)
            mapReady.value = true
            ui.value = ui.value.copy(lastError = "", activeBundleVersion = "2026-09-11", activeDBPath = "/fixture/validated.sqlite")
        }
        compose.onNodeWithTag("onboarding-next-button").assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, nextCount) }
    }

    @Test fun deniedPreciseLocationHasRecoveryAndBlocksProgress() {
        ui.value = ConsumerUiState(onboardingStep = 1, onboardingLocationRequested = true, preciseLocationGranted = false)
        mapReady.value = true
        render()
        compose.onNodeWithTag("onboarding-next-button").assertIsNotEnabled()
        compose.onNodeWithTag("onboarding-location-settings-button").performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals(1, settingsCount)
            ui.value = ui.value.copy(preciseLocationGranted = true)
        }
        compose.onNodeWithTag("onboarding-next-button").assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, nextCount) }
    }

    @Test fun optionalCameraAndPhotoChoicesRemainExplicit() {
        ui.value = ConsumerUiState(onboardingStep = 3, preciseLocationGranted = true)
        mapReady.value = true
        render()
        compose.onNodeWithTag("onboarding-recognition-toggle").performScrollTo().assertIsOff().performClick()
        compose.onNodeWithTag("onboarding-recognition-toggle").assertIsOn()
        compose.onNodeWithTag("onboarding-independent-toggle").performScrollTo().assertIsOff().performClick()
        compose.onNodeWithTag("onboarding-independent-toggle").assertIsOn()
        compose.runOnIdle { ui.value = ui.value.copy(onboardingStep = 4, panoramaxCaptureEnabled = true) }
        compose.onNodeWithTag("onboarding-panoramax-toggle").performScrollTo().assertIsOn().performClick()
        compose.onNodeWithTag("onboarding-panoramax-toggle").assertIsOff()
        compose.onNodeWithTag("onboarding-next-button").assertIsEnabled()
    }

    @Test fun everyStepRendersWithReachableNavigation() {
        ui.value = ConsumerUiState(preciseLocationGranted = true)
        mapReady.value = true
        render()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        for (step in 0..4) {
            compose.runOnIdle { ui.value = ui.value.copy(onboardingStep = step) }
            compose.onNodeWithTag("onboarding-next-button").assertIsEnabled()
            compose.waitForIdle()
            val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
            val output = File(context.getExternalFilesDir(null), "onboarding-step-$step.png")
            output.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
        }
    }

    @Test fun cameraExampleOpensAndClosesWithoutChangingSettings() {
        ui.value = ConsumerUiState(onboardingStep = 3, preciseLocationGranted = true)
        mapReady.value = true
        render()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        compose.onNodeWithContentDescription(context.getString(R.string.onboarding_camera_limit_caption))
            .performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.onboarding_close_example)).performClick()
        compose.runOnIdle {
            assertEquals(0, nextCount)
            assertEquals(false, ui.value.trafficSignRecognitionEnabled)
            assertEquals(3, ui.value.onboardingStep)
        }
        compose.onNodeWithTag("onboarding-next-button").assertIsEnabled()
    }

    private fun render() {
        compose.setContent {
            MaterialTheme {
                Surface(color = Color.Black) {
                    OnboardingScreen(
                        ui = ui.value,
                        hasUsableMap = mapReady.value,
                        isSyncing = syncing.value,
                        onNext = { nextCount++ },
                        onBack = {},
                        onUseLocation = {},
                        onOpenLocationSettings = { settingsCount++ },
                        onSelectMap = { selectedMap = it; ui.value = ui.value.copy(onboardingSelectedMapId = it) },
                        onDownloadMap = { downloadCount++ },
                        onAudioEnabled = { ui.value = ui.value.copy(audioAlertsEnabled = it) },
                        onAudioThreshold = { ui.value = ui.value.copy(audioAlertThresholdKmh = it) },
                        onRecognitionEnabled = { ui.value = ui.value.copy(trafficSignRecognitionEnabled = it) },
                        onIndependentRecognitionEnabled = { ui.value = ui.value.copy(trafficSignRecognitionIndependentEnabled = it) },
                        onPanoramaxEnabled = { ui.value = ui.value.copy(panoramaxCaptureEnabled = it) },
                    )
                }
            }
        }
    }
}

package de.youspeed.android.alpha

import android.content.Intent
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class MapillaryAccountUiInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    @Test fun ownAccountSettingsRequireAnExplicitToken() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val launch=Intent(context,MainActivity::class.java).putExtra("screenshot_state","camera-limit-active")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        ActivityScenario.launch<MainActivity>(launch).use {
            compose.waitUntil(30000) {compose.onAllNodesWithTag("settings-button").fetchSemanticsNodes().isNotEmpty()}
            compose.onNode(hasClickAction() and hasAnyAncestor(hasTestTag("settings-button")),useUnmergedTree=true).performClick()
            compose.onNodeWithTag("settings-list").performScrollToNode(hasTestTag("mapillary-account-token"))
            compose.onNodeWithTag("mapillary-account-token").assertIsDisplayed()
            compose.onNodeWithTag("mapillary-account-connect").assertIsNotEnabled()
            assertTrue(UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
                .takeScreenshot(File(context.getExternalFilesDir(null),"mapillary-own-account-settings.png")))
        }
    }
}

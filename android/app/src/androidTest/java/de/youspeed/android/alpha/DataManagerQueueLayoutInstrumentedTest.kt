package de.youspeed.android.alpha

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DataManagerQueueLayoutInstrumentedTest {
    @get:Rule val compose = createComposeRule()

    @Test fun queuedRunningFailureAndCompletionKeepFollowingActionsStationary() {
        val ui = mutableStateOf(ConsumerUiState())
        compose.setContent {
            MaterialTheme {
                Column(Modifier.fillMaxWidth()) {
                    DataManagerBundleTransferStatus("belgium", ui.value, reserveSpace = true)
                    Button(onClick = {}, modifier = Modifier.testTag("following-region-action")) { Text("Netherlands") }
                }
            }
        }
        val original = compose.onNodeWithTag("following-region-action").fetchSemanticsNode().positionInRoot.y
        val snapshots = listOf(
            ConsumerUiState(queuedBundleDownloadIds = listOf("belgium")),
            ConsumerUiState(activeDownloadOptionId = "belgium", syncStatus = "syncing", syncProgressDetail = "Preparing"),
            ConsumerUiState(activeDownloadOptionId = "belgium", syncStatus = "syncing", syncProgressDetail = "Downloading",
                syncProgressCompletedBytes = 50, syncProgressTotalBytes = 100),
            ConsumerUiState(bundleDownloadErrors = mapOf("belgium" to "A long network error that wraps across several lines while another region runs"),
                activeDownloadOptionId = "netherlands"),
            ConsumerUiState(),
        )
        snapshots.forEach { snapshot ->
            compose.runOnIdle { ui.value = snapshot }
            val top = compose.onNodeWithTag("following-region-action").fetchSemanticsNode().positionInRoot.y
            assertEquals("Queue transitions cannot move another region's button", original, top, 1f)
        }
    }
}

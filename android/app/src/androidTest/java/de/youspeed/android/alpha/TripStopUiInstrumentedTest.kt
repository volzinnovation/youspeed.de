package de.youspeed.android.alpha
import androidx.compose.runtime.mutableStateOf
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
class TripStopUiInstrumentedTest {
 @get:Rule val compose=createComposeRule()
 @Test fun sixDigitsDragAndSaveOrContinue() {
  val visible=mutableStateOf(true);var saved:Int?=null;var continued=false
  compose.setContent {MaterialTheme {if(visible.value) TripStoppedOdometerPrompt(TripStopPromptSnapshot("fixture",123454,true),Color.Black,{saved=it;visible.value=false},{continued=true;visible.value=false})}}
  compose.onNodeWithTag("trip-stop-prompt").assertIsDisplayed()
  repeat(6){compose.onNodeWithTag("trip-stop-digit-$it").assertIsDisplayed()}
  compose.onNodeWithTag("trip-stop-digit-5").performTouchInput {swipeUp(durationMillis=600)}
  compose.onNodeWithTag("trip-stop-save").performClick()
  compose.runOnIdle {assertNotNull(saved);assertTrue(saved!! in 123450..123459);assertNotEquals(123454,saved);visible.value=true}
  compose.onNodeWithTag("trip-stop-continue").performClick()
  compose.runOnIdle {assertTrue(continued)}
  compose.onNodeWithTag("trip-stop-prompt").assertDoesNotExist()
 }
}

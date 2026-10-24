package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.hasTestTag
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TripJournalUiInstrumentedTest {
    @get:Rule val compose=createComposeRule()

    @Test fun offHistoryShortcutOpensNormalSettingsAtJournalAndReturnsFromNestedHistory() {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        check(base.packageName.endsWith(".testhost"))
        val root=File(base.cacheDir,"journal-navigation-${UUID.randomUUID()}").apply {mkdirs()}
        val name="journal-navigation-${UUID.randomUUID()}"
        val journal=TripJournal.get(base);val preferences=base.getSharedPreferences("trip-journal",Context.MODE_PRIVATE)
        val priorConfigured=preferences.contains("enabled");val priorEnabled=journal.enabled
        val visible=mutableStateOf(true);lateinit var controller:ConsumerSessionController;var initialized=false
        try {
            journal.setEnabled(false);journal.snapshot()
            compose.runOnIdle {
                controller=ConsumerSessionController(base,root,base.getSharedPreferences(name,Context.MODE_PRIVATE),java.time.Clock.systemUTC(),AppScreenshotState.OTHER_SIGN_GIVE_WAY);initialized=true
                ConsumerSessionController::class.java.getDeclaredField("drivingControlPostureMotion").apply {isAccessible=true}.let {(it.get(controller) as DrivingControlPostureMotion).stop()}
                @Suppress("UNCHECKED_CAST") val state=ConsumerSessionController::class.java.getDeclaredField("uiState\$delegate").apply {isAccessible=true}.get(controller) as androidx.compose.runtime.MutableState<ConsumerUiState>
                state.value=state.value.copy(phoneIsFlat=true,drivingControlsAllowed=true,currentSpeedKmh=0.0,startupLogReviewState=StartupLogReviewState.COMPLETE)
            }
            compose.setContent {if(visible.value) ConsumerApp(controller)}
            val offState=ConsumerUiStrings.text("Off","Aus","Désactivé","Uit")
            val onState=ConsumerUiStrings.text("On","Ein","Activé","Aan")
            fun assertRecordingState(value:String) {
                compose.onNodeWithTag("trip-journal-button").assert(androidx.compose.ui.test.SemanticsMatcher.expectValue(androidx.compose.ui.semantics.SemanticsProperties.StateDescription,value))
            }
            fun saveButtons(name:String) {
                File(base.cacheDir,name).outputStream().use {output ->
                    compose.onNodeWithTag("dashboard-bottom-controls").captureToImage().asAndroidBitmap().compress(android.graphics.Bitmap.CompressFormat.PNG,100,output)
                }
            }
            assertRecordingState(offState)
            saveButtons("journal-button-off.png")
            compose.runOnIdle {journal.setEnabled(true)}
            compose.waitForIdle();assertRecordingState(onState)
            saveButtons("journal-button-on.png")
            compose.runOnIdle {journal.setEnabled(false)}
            compose.waitForIdle();assertRecordingState(offState)
            compose.onNodeWithTag("trip-journal-button").performClick()
            compose.onNodeWithTag("trip-journal-recording-off").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-open-settings").performClick()
            compose.onNodeWithTag("settings-sheet").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-recording-toggle").assertIsDisplayed()
            org.junit.Assert.assertFalse(journal.enabled)
            compose.onNodeWithTag("settings-list").performScrollToNode(hasTestTag("settings-trip-history"))
            compose.onNodeWithTag("settings-trip-history").performClick()
            compose.onNodeWithTag("trip-journal-open-settings").performClick()
            compose.onNodeWithTag("settings-sheet").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-recording-toggle").assertIsDisplayed()
            org.junit.Assert.assertFalse(journal.enabled)
        } finally {
            compose.runOnIdle {visible.value=false;if(initialized) controller.dispose()};compose.waitForIdle()
            if(priorConfigured) journal.setEnabled(priorEnabled) else preferences.edit().remove("enabled").commit()
            base.deleteSharedPreferences(name);root.deleteRecursively()
        }
    }

    @Test fun readFailureShowsErrorWithoutCrashingSimpleHistory() {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(base.cacheDir,"trip-ui-regression-${UUID.randomUUID()}").apply { mkdirs() }
        val preferenceName="trip-ui-regression-${UUID.randomUUID()}"
        val context=object : ContextWrapper(base) {
            override fun getFilesDir()=root
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferenceName,mode)
        }
        val journal=TripJournal(context,heartbeat=false)
        val visible=mutableStateOf(true)
        try {
            journal.setEnabled(true); journal.start()
            val id=journal.snapshot().first.single().getString("id")
            compose.setContent { if (visible.value) TripJournalScreen(journal) {} }
            compose.waitUntil(10000) {runCatching {compose.onNodeWithTag("trip-journal-list").performScrollToNode(hasTestTag("trip-$id"));true}.getOrDefault(false)}
            SQLiteDatabase.openOrCreateDatabase(File(root,"trip-journal/trips.sqlite"),null).use { db ->
                db.execSQL("DROP TABLE events")
            }
            compose.waitUntil(10000) {runCatching {compose.onNodeWithTag("trip-journal-list").performScrollToNode(hasTestTag("trip-journal-error"));true}.getOrDefault(false)}
            compose.onNodeWithTag("trip-journal-list").performScrollToNode(hasTestTag("trip-journal-error"))
            compose.onNodeWithTag("trip-journal-error").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-sheet").assertIsDisplayed()
        } finally {
            compose.runOnIdle { visible.value=false }
            compose.waitForIdle()
            journal.close()
            base.deleteSharedPreferences(preferenceName)
            root.deleteRecursively()
        }
    }
    @Test fun emptyHistoryOpensDirectlyWithFiveColumnsAndClose() {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(base.cacheDir,"trip-ui-empty-${UUID.randomUUID()}").apply {mkdirs()}
        val preferenceName="trip-ui-empty-${UUID.randomUUID()}"
        val context=object:ContextWrapper(base) {
            override fun getFilesDir()=root
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferenceName,mode)
        }
        val journal=TripJournal(context,false);val visible=mutableStateOf(true)
        var requestedSettings=false
        try {
            compose.setContent {if(visible.value) TripJournalScreen(journal,onOpenSettings={requestedSettings=true}) {visible.value=false}}
            compose.onNodeWithTag("trip-journal-table-header").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-recording-off").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-empty").assertDoesNotExist()
            compose.onNodeWithTag("trip-journal-recording-off").assertTextContains(when(java.util.Locale.getDefault().language) {
                "de" -> "Fahrtenaufzeichnung ist aus."
                "fr" -> "L’enregistrement des trajets est désactivé."
                "nl" -> "Ritten opnemen staat uit."
                else -> "Trip recording is off."
            },substring=true)
            for(i in 0..4) compose.onNodeWithTag("trip-journal-column-$i").assertExists()
            for(tag in listOf("trip-journal-filters","trip-journal-backup","trip-journal-restore","trip-journal-clear","trip-journal-data-disclosure")) compose.onNodeWithTag(tag).assertDoesNotExist()
            val pictures=File(base.filesDir,"journal-simple-validation").apply {mkdirs()}
            compose.onNodeWithTag("trip-journal-sheet").captureToImage().asAndroidBitmap().let {image ->File(pictures,"empty-initial-full-screen.png").outputStream().use {image.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}}
            compose.onNodeWithTag("trip-journal-open-settings").assertIsDisplayed().performClick()
            compose.runOnIdle {org.junit.Assert.assertTrue(requestedSettings);org.junit.Assert.assertFalse(journal.enabled);org.junit.Assert.assertFalse(journal.configured)}
            compose.onNodeWithTag("trip-journal-sheet-close").performClick()
            compose.onNodeWithTag("trip-journal-sheet").assertDoesNotExist()
        } finally {compose.runOnIdle {visible.value=false};compose.waitForIdle();journal.close();base.deleteSharedPreferences(preferenceName);root.deleteRecursively()}
    }
}

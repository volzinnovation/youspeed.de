package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.SharedPreferences
import android.location.Location
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import java.util.zip.ZipFile

@RunWith(AndroidJUnit4::class)
class TripJournalTableUiInstrumentedTest {
    @get:Rule val compose=createComposeRule()

    @Test fun recordingPreferenceIsDirectAndDoesNotPresentHistory() {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(base.cacheDir,"journal-settings-${UUID.randomUUID()}").apply {mkdirs()}
        val preferenceName="journal-settings-${UUID.randomUUID()}"
        val context=object:ContextWrapper(base) {
            override fun getFilesDir()=root
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferenceName,mode)
        }
        val journal=TripJournal(context,false);val visible=mutableStateOf(true)
        try {
            compose.setContent {if(visible.value) Column {TripJournalRecordingPreferences(journal);TripJournalDataManagement(journal)}}
            compose.onNodeWithTag("trip-journal-recording-toggle").assertIsOff()
            compose.onNodeWithTag("trip-journal-recording-disclosure").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-recording-toggle").performClick();assertTrue(journal.enabled)
            compose.onNodeWithTag("trip-journal-recording-toggle").performClick();assertFalse(journal.enabled)
            compose.onNodeWithTag("trip-journal-sheet").assertDoesNotExist()
            compose.onNodeWithTag("trip-journal-backup").assertDoesNotExist()
            compose.onNodeWithTag("trip-journal-restore").assertDoesNotExist()
            compose.onNodeWithTag("trip-journal-clear").assertDoesNotExist()
            compose.onNodeWithTag("trip-journal-data-disclosure").performClick()
            compose.onNodeWithTag("trip-journal-backup").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-restore").assertIsDisplayed()
            compose.onNodeWithTag("trip-journal-clear").assertIsDisplayed()
        } finally {compose.runOnIdle {visible.value=false};compose.waitForIdle();journal.close();base.deleteSharedPreferences(preferenceName);root.deleteRecursively()}
    }

    @Test fun simpleInitialTableAndCompactOdometerShareDelete() {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(base.filesDir,"journal-table-${UUID.randomUUID()}").apply {mkdirs()}
        val preferenceName="journal-table-${UUID.randomUUID()}"
        val shared=AtomicReference<Intent?>(null)
        val context=object:ContextWrapper(base) {
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getCacheDir()=File(root,"cache").apply {mkdirs()}
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferenceName,mode)
            override fun startActivity(intent:Intent) {shared.set(intent)}
        }
        var wall=1_800_000_000.0;var elapsed=10000L
        val journal=TripJournal(context,false,{wall},{elapsed})
        val visible=mutableStateOf(true)
        val pictures=File(base.filesDir,"journal-simple-validation").apply {mkdirs()}
        fun picture(tag:String,name:String) {compose.onNodeWithTag(tag).captureToImage().asAndroidBitmap().let {bitmap->File(pictures,name).outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}}}
        try {
            journal.setEnabled(true)
            journal.start();val id=journal.snapshot().first.single().getString("id");journal.odometer(id,12000.0,null)
            val startName="Long unabridged street name with several words at the beginning"
            val endName="Another complete destination street name with several words"
            for(i in 0..2) {
                val lat=48.0+i*0.00015
                journal.location(Location("gps").apply {latitude=lat;longitude=8.0;accuracy=3f;speed=10f;time=(wall*1000).toLong();elapsedRealtimeNanos=elapsed*1_000_000})
                journal.matchedPlace(wall,if(i==0) startName else endName,"Town",lat,8.0,3.0)
                journal.snapshot();wall+=1;elapsed+=1000
            }
            journal.tsr("fixture_tsr",mapOf("state" to "read"));journal.stop();journal.snapshot();wall+=6;elapsed+=6000;journal.snapshot()
            compose.setContent {
                val host=LocalContext.current
                val shareContext=remember(host) {object:ContextWrapper(host) {override fun startActivity(intent:Intent) {shared.set(intent)}}}
                if(visible.value) CompositionLocalProvider(LocalContext provides shareContext) {TripJournalScreen(journal) {}}
            }
            compose.waitUntil(10000) {compose.onAllNodesWithTag("trip-$id").fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithTag("trip-journal-table-header").assertIsDisplayed()
            compose.onNodeWithTag("trip-$id-cell-0").assertIsDisplayed()
            for(tag in listOf("trip-journal-filters","trip-journal-backup","trip-journal-restore","trip-journal-clear","trip-journal-data-disclosure","trip-$id-details")) compose.onNodeWithTag(tag).assertDoesNotExist()
            for(label in listOf("Filters","Saved trips","New trip","Details","Encrypted backup","Clear all trips and counters")) compose.onAllNodesWithText(label).assertCountEquals(0)
            compose.onNodeWithTag("trip-journal-recording-toggle").assertDoesNotExist()
            for(i in 0..4) compose.onNodeWithTag("trip-journal-column-$i").assertExists()
            compose.onNodeWithTag("trip-journal-column-5").assertDoesNotExist()
            compose.onNodeWithTag("trip-$id-cell-1").assertTextEquals(startName+"\nTown")
            compose.onNodeWithTag("trip-$id-cell-2").assertTextEquals(endName+"\nTown")
            val white=compose.onNodeWithTag("trip-journal-sheet").captureToImage().toPixelMap()
            assertEquals(Color.White,white[white.width/2,5])
            picture("trip-journal-sheet","initial-full-screen.png")
            compose.onNodeWithTag("trip-$id-cell-0").performClick()
            compose.onNodeWithTag("trip-ending-odometer-sheet-close").assertIsDisplayed()
            compose.onNodeWithTag("trip-ending-odometer-details").assertDoesNotExist()
            compose.onAllNodesWithText("Optional:",substring=true).assertCountEquals(0)
            val odoWhite=compose.onNodeWithTag("trip-ending-odometer-sheet").captureToImage().toPixelMap()
            assertEquals(Color.White,odoWhite[odoWhite.width/2,5])
            compose.onNodeWithTag("trip-ending-odometer-input").performTextInput("11999")
            compose.onNodeWithTag("trip-ending-odometer-error").assertIsDisplayed()
            compose.onNodeWithTag("trip-ending-odometer-save").assertIsNotEnabled()
            compose.onNodeWithTag("trip-ending-odometer-input").performTextClearance()
            compose.onNodeWithTag("trip-ending-odometer-input").performTextInput("12000,5")
            picture("trip-ending-odometer-sheet","odometer.png")
            compose.onNodeWithTag("trip-ending-odometer-sheet-close").performClick()
            assertFalse(journal.snapshot().first.single().has("odo_end"))
            compose.onNodeWithTag("trip-$id-cell-0").performClick()
            compose.onNodeWithTag("trip-ending-odometer-input").performTextInput("12000,5")
            compose.onNodeWithTag("trip-ending-odometer-save").performClick()
            compose.waitUntil(10000) {compose.onAllNodesWithTag("trip-ending-odometer-sheet").fetchSemanticsNodes().isEmpty()}
            assertEquals(12000.5,journal.snapshot().first.single().getDouble("odo_end"),0.0)
            compose.onNodeWithTag("trip-$id-share").performScrollTo().performClick()
            compose.waitUntil(10000) {shared.get()!=null}
            assertEquals(Intent.ACTION_CHOOSER,shared.get()!!.action)
            val send=shared.get()!!.getParcelableExtra(Intent.EXTRA_INTENT,Intent::class.java)!!
            assertEquals(Intent.ACTION_SEND,send.action);assertEquals("application/zip",send.type)
            compose.onNodeWithTag("trip-ending-odometer-sheet").assertDoesNotExist()
            val archive=File(context.filesDir,"trip-exports/$id").listFiles()!!.single {it.extension=="zip"}
            ZipFile(archive).use {zip ->
                for(name in listOf("gps.json","tsr.json","track.gpx","track.geojson")) assertNotNull(name,zip.getEntry(name))
                assertTrue(zip.getInputStream(zip.getEntry("tsr.json")).reader().readText().contains("fixture_tsr"))
                val trip=JSONObject(zip.getInputStream(zip.getEntry("trip.json")).reader().readText()).getJSONObject("trip")
                assertFalse(trip.has("odo_end"));assertFalse(zip.entries().asSequence().any {it.name.startsWith("media/")})
            }
            picture("trip-journal-sheet","history-right.png")
            compose.onNodeWithTag("trip-$id-delete").performScrollTo().performClick()
            val deleteTitle=ConsumerUiStrings.text("Delete trip?","Fahrt löschen?","Supprimer ce trajet ?","Rit verwijderen?")
            compose.waitUntil(10000) {compose.onAllNodesWithText(deleteTitle).fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithTag("trip-ending-odometer-sheet").assertDoesNotExist()
            compose.onNodeWithText(ConsumerUiStrings.text("Cancel","Abbrechen","Annuler","Annuleren")).performClick();assertEquals(1,journal.snapshot().first.size)
            compose.onNodeWithTag("trip-$id-details").assertDoesNotExist()
            compose.onNodeWithTag("trip-$id-cell-0").performScrollTo().performClick()
            compose.onNodeWithTag("trip-ending-odometer-saved").assertIsDisplayed()
            compose.onNodeWithTag("trip-ending-odometer-input").assertDoesNotExist()
            compose.onNodeWithTag("trip-ending-odometer-details").assertDoesNotExist()


        } catch(error:Throwable) {
            runCatching {picture("trip-journal-sheet","failure.png")}
            val tree=runCatching {compose.onNodeWithTag("trip-journal-sheet").printToString()}.getOrElse {compose.onRoot(useUnmergedTree=true).printToString()}
            throw AssertionError(error.message+"\n"+tree+"\nSnapshot: "+journal.snapshot().first,error)
        } finally {compose.runOnIdle {visible.value=false};compose.waitForIdle();journal.close();base.deleteSharedPreferences(preferenceName);root.deleteRecursively()}
    }
}

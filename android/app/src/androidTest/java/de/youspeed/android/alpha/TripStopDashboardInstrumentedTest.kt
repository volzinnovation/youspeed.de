package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.graphics.Bitmap
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import java.util.Locale
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class TripStopDashboardInstrumentedTest {
    @get:Rule val compose=createEmptyComposeRule()
    @Test fun stopButtonOpensPersistentEditorInBothOrientations() {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        check(base.packageName.endsWith(".testhost"))
        val previousLocale=Locale.getDefault()
        Locale.setDefault(Locale.GERMANY)
        val fixture="trip-stop-dashboard-${java.util.UUID.randomUUID()}"
        val root=File(base.cacheDir,fixture).apply {mkdirs()}
        val isolated=object:ContextWrapper(base) {
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getSharedPreferences(name:String,mode:Int)=base.getSharedPreferences(fixture,mode)
        }
        var tick=0L;val wall=System.currentTimeMillis()/1000.0
        val journal=TripJournal(isolated,heartbeat=false,wallClock={wall+tick},elapsedClock={tick*1000})
        journal.setEnabled(true);journal.start();journal.snapshot()
        fun feed(speed:Float,t:Long) {tick=t;journal.location(android.location.Location("gps").apply {latitude=if(t==0L) 49.0 else 49.001;longitude=8.0;accuracy=3f;this.speed=speed;time=((wall+tick)*1000).toLong();elapsedRealtimeNanos=(tick+1)*1_000_000_000L});journal.snapshot()}
        feed(10f,0);for(t in 1L..16)feed(0f,t)
        val scenario=ActivityScenario.launch<MainActivity>(Intent(base,MainActivity::class.java).putExtra("screenshot_state","camera-limit-active"))
        lateinit var controller:ConsumerSessionController
        scenario.onActivity {controller=it.sessionController;ConsumerSessionController::class.java.getDeclaredField("tripJournal").apply {isAccessible=true}.set(controller,journal)}
        val ui=mutableStateOf(controller.uiState.copy(currentSpeedKmh=0.0,stationarySpeedObservedAt=Instant.now(),presentationForeground=true))
        try {
            scenario.onActivity {activity->activity.setContent {
                LaunchedEffect(Unit) {while(true) {if(ui.value.currentSpeedKmh==0.0)ui.value=ui.value.copy(stationarySpeedObservedAt=Instant.now());kotlinx.coroutines.delay(400)}}
                MaterialTheme {
                    val dashboard=ui.value
                    // Reset alongside state reads: orientation may recompose only this content lambda.
                    Locale.setDefault(Locale.GERMANY)
                    MainScreen(controller,dashboard,true,{},{},{},{},{},{},{},{},{})
                }
            }}
            for(orientation in listOf(ManualOrientation.PORTRAIT,ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT)) {
                scenario.onActivity {it.applyManualOrientation(orientation)}
                compose.runOnIdle {ui.value=ui.value.copy(manualOrientation=orientation)}
                compose.waitUntil(15_000){compose.onAllNodesWithTag("trip-stop-end").fetchSemanticsNodes().isNotEmpty()}
                compose.waitUntil(5_000){compose.onAllNodesWithText("Fahrt beenden").fetchSemanticsNodes().isNotEmpty()}
                compose.onNodeWithTag("trip-stop-end").assertIsDisplayed()
                compose.onNodeWithTag("primary-metric").assertDoesNotExist()
                val image=compose.onNodeWithTag("main-root").captureToImage().asAndroidBitmap()
                File(base.cacheDir,"trip-stop-${orientation.storageValue}.png").outputStream().use {image.compress(Bitmap.CompressFormat.PNG,100,it)}
            }
            compose.onNodeWithTag("trip-stop-end").performClick()
            compose.waitUntil(5_000){compose.onAllNodesWithTag("trip-stop-prompt").fetchSemanticsNodes().isNotEmpty()}
            repeat(6){compose.onNodeWithTag("trip-stop-digit-$it").assertIsDisplayed()}
            compose.onNodeWithTag("trip-stop-digit-5").performTouchInput {swipeUp(durationMillis=600)}
            val saved=journal.history().single()
            assertEquals("ended",saved.getString("state"))
            compose.runOnIdle {ui.value=ui.value.copy(currentSpeedKmh=20.0,stationarySpeedObservedAt=null)}
            compose.onNodeWithTag("trip-stop-prompt").assertIsDisplayed()
            compose.onNodeWithTag("trip-stop-save").performClick()
            compose.waitUntil(5_000){compose.onAllNodesWithTag("trip-stop-prompt").fetchSemanticsNodes().isEmpty()}
            journal.newTrip();journal.snapshot()
            compose.runOnIdle {ui.value=ui.value.copy(currentSpeedKmh=0.0,stationarySpeedObservedAt=Instant.now())}
            compose.onNodeWithTag("trip-stop-end").assertDoesNotExist()
            compose.onNodeWithTag("primary-metric").assertIsDisplayed().assertTextEquals("0")
            val initialImage=compose.onNodeWithTag("main-root").captureToImage().asAndroidBitmap()
            File(base.cacheDir,"trip-initial-zero.png").outputStream().use {initialImage.compress(Bitmap.CompressFormat.PNG,100,it)}
            assertTrue(journal.history().single().has("odo_end"))
            assertEquals(saved.getDouble("distance"),journal.history().single().getDouble("distance"),0.0)
        } finally {
            scenario.onActivity {it.applyManualOrientation(ManualOrientation.PORTRAIT)}
            scenario.close();journal.close();base.deleteSharedPreferences(fixture);root.deleteRecursively()
            Locale.setDefault(previousLocale)
        }
    }
}

package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import androidx.activity.compose.setContent
import androidx.test.core.app.ActivityScenario
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Full dashboard composition; physical-driver validation requires a separate explicit opt-in. */
@RunWith(AndroidJUnit4::class)
class UpcomingSpeedLimitLayoutInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    @Test fun upcomingSignFitsEveryMountWithRecorderAndLargerText() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val driverValidation=InstrumentationRegistry.getArguments().getString("driver_ui_validation")=="true"
        check(context.packageName.endsWith(".testhost") || driverValidation)
        val preferences=context.getSharedPreferences("youspeed",Context.MODE_PRIVATE)
        val previewCandidate=if(driverValidation) {
            val active=org.json.JSONObject(File(context.filesDir,"bundle/active_bundle.json").readText())
            val database=File(active.getString("db_path"))
            assertEquals(3099021312L,database.length())
            assertEquals("34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c",active.getString("db_sha256"))
            val c=org.json.JSONObject(File(context.cacheDir,"upcoming-physical-cases.json").readText()).getJSONArray("cases").getJSONObject(0)
            val groups=c.getJSONArray("relationGroupIDs").let { a -> (0 until a.length()).map { a.getLong(it) }.toSet() }
            android.database.sqlite.SQLiteDatabase.openDatabase(database.path,null,android.database.sqlite.SQLiteDatabase.OPEN_READONLY).use { db ->
                val reader=UpcomingSpeedLimitReader(db)
                fun read()=reader.read(c.getDouble("lat"),c.getDouble("lon"),c.getString("wayID"),c.getInt("direction"),true,1.0,c.getDouble("headingDeg"),1.0,groups)
                read()
                requireNotNull(read()).candidates.first { it.signID==c.getString("expectedSignID") }
            }
        } else UpcomingSpeedLimitCandidate("test","fixture","snapshot","rule","1",1,200.0,20,
            InstrumentationRegistry.getArguments().getString("upcoming_preview_distance_m")?.toDouble() ?: 120.0)
        val device = UiDevice.getInstance(instrumentation)
        val scenario=ActivityScenario.launch<MainActivity>(Intent(context,MainActivity::class.java).putExtra("screenshot_state","camera-limit-active"))
        lateinit var controller: ConsumerSessionController
        scenario.onActivity { controller=it.sessionController }
        // A fresh isolated installation may complete existing preference migrations on launch.
        val originalPreferences=preferences.all.toMap()
        val ui = mutableStateOf(controller.uiState.copy(
            upcomingSpeedLimit=previewCandidate,
            speedLimitKmh=if(driverValidation)100 else controller.uiState.speedLimitKmh,
            speedLimitDisplayText=if(driverValidation)"100" else controller.uiState.speedLimitDisplayText,
            otherTrafficSignDisplayEnabled=true,inventorySignCode="DE:205",inventorySignParameterText="Give way",
            retainedTrafficSignSupplementaryText=TrafficSignSupplementaryTextObservation(if(driverValidation)"maxspeed:100" else "maxspeed:30",if(driverValidation)100 else 30,"fixture","frame",
                java.time.Instant.now(),java.time.Instant.now(),"6–18 h",TrafficSignSupplementaryTimeWindow(360,1080),
                TrafficSignSupplementaryOCRStatus.READ,NormalizedTrafficSignBoundingBox(0.5,0.1,0.1,0.1)),
        ))
        val font = mutableStateOf(1f)
        val narrowPortrait = mutableStateOf(false)
        fun assertControlRowFits() {
            val root=compose.onNodeWithTag("main-root").fetchSemanticsNode().boundsInRoot
            val tags=listOf("drive-recorder-toggle-button","panoramax-capture-toggle-button","panoramax-gallery-button","visual-calibration-button","legal-button","trip-journal-button","settings-button")
            var previous:Rect?=null
            tags.forEach { tag ->
                val node=compose.onNodeWithTag(tag).assertIsDisplayed().fetchSemanticsNode()
                val raw=Rect(node.positionInRoot.x,node.positionInRoot.y,node.positionInRoot.x+node.size.width,node.positionInRoot.y+node.size.height)
                assertTrue("$tag remains inside dashboard $root: $raw",raw.left>=root.left-1 && raw.right<=root.right+1 && raw.top>=root.top-1 && raw.bottom<=root.bottom+1)
                assertEquals("$tag is not horizontally clipped",raw.width,node.boundsInRoot.width,1f)
                assertEquals("$tag retains existing 48 dp width",48f*context.resources.displayMetrics.density,raw.width,1f)
                previous?.let {prior ->assertTrue("$tag does not overlap its preceding button",prior.right<=raw.left+1f)}
                previous=raw
            }
        }
        try {
            scenario.onActivity { activity -> activity.setContent {
                val density = LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density,font.value)) {
                    MaterialTheme { Box((if(narrowPortrait.value) Modifier.width(360.dp).fillMaxHeight() else Modifier.fillMaxSize()).background(Color.Black)) {
                        MainScreen(controller,ui.value,true,{},{},{},{},{},{},{},{},{})
                    } }
                }
            } }
            for (orientation in ManualOrientation.entries) {
                scenario.onActivity { it.applyManualOrientation(orientation) }
                compose.runOnIdle { ui.value=ui.value.copy(manualOrientation=orientation) }
                compose.waitUntil(20_000) { (device.displayWidth>device.displayHeight)==orientation.isLandscape }
                for (recorder in listOf(false,true)) for (scale in listOf(1f,1.5f)) {
                    compose.runOnIdle { font.value=scale;ui.value=ui.value.copy(
                        driveRecorderState=if(recorder) DriveRecorderState.RECORDING else DriveRecorderState.DISABLED,
                        driveRecorderDashcamActive=recorder) }
                    compose.waitForIdle()
                    val previewNode=compose.onNodeWithTag("upcoming-speed-limit")
                    try { previewNode.assertIsDisplayed() } catch(error: AssertionError) { throw AssertionError("$orientation recorder=$recorder scale=$scale: ${previewNode.fetchSemanticsNode().boundsInRoot}",error) }
                    val preview=previewNode.fetchSemanticsNode()
                    assertTrue("Long distance remains available to accessibility",preview.config[androidx.compose.ui.semantics.SemanticsProperties.ContentDescription]
                        .single().contains(previewCandidate.displayDistanceM.toString()))
                    val pane=compose.onNodeWithTag("main-sign-pane").fetchSemanticsNode().boundsInRoot
                    val raw=Rect(preview.positionInRoot.x,preview.positionInRoot.y,preview.positionInRoot.x+preview.size.width,preview.positionInRoot.y+preview.size.height)
                    assertTrue("Preview $raw fits sign pane $pane ($orientation, $recorder, $scale)",raw.left>=pane.left-1 && raw.top>=pane.top-1 && raw.right<=pane.right+1 && raw.bottom<=pane.bottom+1)
                    assertEquals(raw.height,preview.boundsInRoot.height,1f)
                    assertEquals(raw.width,preview.boundsInRoot.width,1f)
                    val main=compose.onNodeWithTag("speed-sign").fetchSemanticsNode().boundsInRoot
                    assertTrue("Main sign remains dominant",main.width>raw.width)
                    val diameter=60f*context.resources.displayMetrics.density
                    val smallCenterX=if(orientation.isLandscape) raw.left+diameter/2 else raw.center.x
                    val smallCenterY=raw.top+diameter/2
                    val centerDistance=kotlin.math.hypot(smallCenterX-main.center.x,smallCenterY-main.center.y)
                    assertTrue("Current and upcoming circles remain separated ($orientation, $recorder, $scale): $centerDistance",
                        centerDistance>=main.width/2+diameter/2+6f*context.resources.displayMetrics.density)
                    assertTrue("Preview stays below retained secondary sign",raw.top>compose.onNodeWithTag("inventory-sign-code").fetchSemanticsNode().boundsInRoot.bottom)
                    val image=compose.onNodeWithTag("main-root").captureToImage().asAndroidBitmap()
                    File(context.cacheDir,"upcoming-layout-${orientation.storageValue}-$recorder-$scale.png").outputStream().use { image.compress(Bitmap.CompressFormat.PNG,100,it) }
                    val plate=compose.onNodeWithTag("traffic-sign-supplementary-time").assertIsDisplayed().fetchSemanticsNode().boundsInRoot
                    assertFalse("Preview does not cover the supplementary plate",raw.overlaps(plate))
                    val journal=compose.onNodeWithTag("trip-journal-button").assertIsDisplayed().fetchSemanticsNode().boundsInRoot
                    val settings=compose.onNodeWithTag("settings-button").assertIsDisplayed().fetchSemanticsNode().boundsInRoot
                    assertEquals("Journal uses the existing 48 dp pill button width",48f*context.resources.displayMetrics.density,journal.width,1f)
                    assertEquals("Journal uses the existing button height",settings.height,journal.height,1f)
                    assertTrue("Journal sits immediately left of settings",journal.center.x<settings.center.x && journal.right<=settings.left+1f)
                    assertTrue("Journal and settings share the control row",kotlin.math.abs(journal.center.y-settings.center.y)<1f)
                    assertControlRowFits()
                }
            }
            scenario.onActivity {it.applyManualOrientation(ManualOrientation.PORTRAIT)}
            compose.runOnIdle {ui.value=ui.value.copy(manualOrientation=ManualOrientation.PORTRAIT);font.value=1.5f;narrowPortrait.value=true}
            compose.waitUntil(20_000) {device.displayWidth<device.displayHeight}
            compose.waitForIdle()
            assertEquals("Narrow portrait fixture is 360 dp wide",360f*context.resources.displayMetrics.density,compose.onNodeWithTag("main-root").fetchSemanticsNode().boundsInRoot.width,1f)
            assertControlRowFits()
        } finally {
            device.unfreezeRotation()
            scenario.close()
            assertEquals("Layout validation must preserve driver preferences",originalPreferences,preferences.all)
        }
    }
}

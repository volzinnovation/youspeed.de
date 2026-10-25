package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.SharedPreferences
import androidx.activity.compose.setContent
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class TripJournalNativeShareInstrumentedTest {
    @get:Rule val compose=createEmptyComposeRule()

    @Test fun touchOpensNativeChooserForSyntheticTrip() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val base=instrumentation.targetContext
        check(base.packageName.endsWith(".testhost"))
        val name="native-trip-share-${UUID.randomUUID()}"
        val root=File(base.filesDir,name).apply {mkdirs()}
        val context=object:ContextWrapper(base) {
            override fun getFilesDir()=root
            override fun getSharedPreferences(key:String,mode:Int):SharedPreferences=base.getSharedPreferences(name,mode)
        }
        val journal=TripJournal(context,false)
        journal.setEnabled(true);journal.start()
        val id=journal.history().single().getString("id")
        journal.stop();journal.completeFinalizerForTesting()
        val scenario=ActivityScenario.launch<MainActivity>(Intent(base,MainActivity::class.java).putExtra("screenshot_state","camera-limit-active"))
        val device=UiDevice.getInstance(instrumentation)
        try {
            scenario.onActivity {activity->activity.setContent {TripJournalScreen(journal) {}}}
            compose.waitUntil(10000) {compose.onAllNodesWithTag("trip-$id-share").fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithTag("trip-$id-share").performTouchInput {click(center)}
            assertTrue("The actual Android share chooser must open",
                device.wait(Until.hasObject(By.pkg("com.android.intentresolver")),10000) || device.currentPackageName=="android")
            assertTrue(File(root,"trip-exports/$id").walkTopDown().any {it.extension=="zip"})
            device.pressBack()
        } finally {
            scenario.close();journal.close();base.deleteSharedPreferences(name);root.deleteRecursively()
        }
    }
}

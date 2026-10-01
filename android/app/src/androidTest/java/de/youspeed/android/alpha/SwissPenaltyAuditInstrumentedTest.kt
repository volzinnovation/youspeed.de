package de.youspeed.android.alpha

import android.content.Intent
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.By
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Audits the actual GPS country selector, packaged rules and dashboard resolver.
 * Expectations below describe current behavior, not legal approval of that behavior. */
@RunWith(AndroidJUnit4::class)
class SwissPenaltyAuditInstrumentedTest {
    @Test fun swissLocationLoadsSharedRulesAndRecordsCurrentPresentation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val output = File(context.filesDir, "swiss-penalty-audit").apply { mkdirs() }
        val reports = JSONArray()
        val cases = listOf(Triple(50, 5, true), Triple(80, 10, false),
            Triple(120, 10, false), Triple(120, 32, false), Triple(30, 40, true),
            Triple(80, 60, false), Triple(120, 80, false))
        cases.forEachIndexed { index, (limit, delta, urban) ->
            val intent = Intent(context, MainActivity::class.java).apply {
                putExtra("screenshot_state", "warn-level-1")
                putExtra("screenshot_country", "CH")
                putExtra("screenshot_limit", limit)
                putExtra("screenshot_delta", delta)
                putExtra("screenshot_inside_city", urban)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            }
            ActivityScenario.launch<MainActivity>(intent).use { scenario ->
                scenario.onActivity { activity ->
                    val state = activity.sessionController.uiState
                    assertEquals("CHE", state.activePenaltyRules.countryCode)
                    assertEquals("CHE-rules.json", state.activePenaltyRules.fileName)
                    assertEquals("CHF", state.activePenaltyRules.currencyCode)
                    assertEquals(47.3769, state.currentLatitude!!, 0.000001)
                    val notice = ConsumerMainScreenLogic.currentPenaltyNotice(state)!!
                    reports.put(JSONObject().apply {
                        put("country", state.activePenaltyRules.countryCode)
                        put("rules_file", state.activePenaltyRules.fileName)
                        put("currency", state.activePenaltyRules.currencyCode)
                        put("latitude", state.currentLatitude)
                        put("longitude", state.currentLongitude)
                        put("posted_limit_kmh", limit); put("delta_kmh", delta)
                        put("inside_city", urban)
                        put("money_fine_eur", notice.moneyFineEUR ?: JSONObject.NULL)
                        put("driving_ban_months", notice.drivingBanMonths ?: JSONObject.NULL)
                        put("conditional_driving_ban_months", notice.conditionalDrivingBanMonths ?: JSONObject.NULL)
                        put("title", notice.title); put("details", notice.details)
                    })
                }
                device.waitForIdle()
                device.findObject(By.text("Got it"))?.click()
                SystemClock.sleep(500)
                assertTrue(device.takeScreenshot(File(output, "case-$index.png")))
            }
        }
        File(output, "report.json").writeText(reports.toString(2) + "\n")
    }
}

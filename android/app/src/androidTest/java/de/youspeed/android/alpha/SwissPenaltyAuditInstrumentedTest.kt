package de.youspeed.android.alpha

import android.content.Intent
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.By
import java.io.File
import java.util.Locale
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
        val language = InstrumentationRegistry.getArguments().getString("language") ?: "en"
        assertEquals(language, Locale.getDefault().language)
        val singular = mapOf("de" to "Monat Fahrverbot", "fr" to "mois d'interdiction",
            "en" to "month driving ban", "nl" to "maand rijverbod").getValue(language)
        val plural = mapOf("de" to "Monate Fahrverbot", "fr" to "mois d'interdiction",
            "en" to "months driving ban", "nl" to "maanden rijverbod").getValue(language)
        val review = mapOf("de" to "Prüfen", "fr" to "À vérifier",
            "en" to "Review", "nl" to "Controleren").getValue(language)
        val output = File(context.filesDir, "swiss-penalty-audit/$language").apply { mkdirs() }
        val reports = JSONArray()
        val cases = listOf(Triple(50, 5, true), Triple(80, 10, false),
            Triple(120, 10, false), Triple(120, 32, false), Triple(30, 40, true),
            Triple(80, 60, false), Triple(120, 80, false), Triple(120, 32, false))
        cases.forEachIndexed { index, (limit, delta, urban) ->
            val intent = Intent(context, MainActivity::class.java).apply {
                putExtra("screenshot_state", "warn-level-1")
                putExtra("screenshot_country", "CH")
                putExtra("screenshot_limit", limit)
                putExtra("screenshot_delta", delta)
                putExtra("screenshot_inside_city", urban)
                putExtra("screenshot_highway", listOf("residential", "primary", "motorway", "motorway", "residential", "primary", "motorway", "trunk")[index])
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
                    val expectedFine = listOf(40, 100, 60, null, null, null, null, null)[index]
                    val expectedMonths = listOf(null, null, null, 1, 24, 24, 24, null)[index]
                    assertEquals(expectedFine, notice.moneyFineEUR)
                    assertEquals(expectedMonths, notice.drivingBanMonths)
                    reports.put(JSONObject().apply {
                        put("locale", language)
                        put("country", state.activePenaltyRules.countryCode)
                        put("rules_file", state.activePenaltyRules.fileName)
                        put("currency", state.activePenaltyRules.currencyCode)
                        put("latitude", state.currentLatitude)
                        put("longitude", state.currentLongitude)
                        put("posted_limit_kmh", limit); put("delta_kmh", delta)
                        put("inside_city", urban)
                        put("highway", state.lastLookupHighway)
                        put("advisory_caption", notice.advisoryCaption)
                        put("money_fine_eur", notice.moneyFineEUR ?: JSONObject.NULL)
                        put("driving_ban_months", notice.drivingBanMonths ?: JSONObject.NULL)
                        put("conditional_driving_ban_months", notice.conditionalDrivingBanMonths ?: JSONObject.NULL)
                        put("title", notice.title); put("details", notice.details)
                    })
                }
                device.waitForIdle()
                for (label in listOf("Got it", "Verstanden", "Compris", "Begrepen")) {
                    device.findObject(By.text(label))?.click()
                }
                SystemClock.sleep(500)
                val expectedPrimary = listOf("40", "100", "60", "≥1", "24", "24", "24", "!")[index]
                val expectedSecondary = listOf("CHF", "CHF", "CHF", singular, plural, plural, plural, review)[index]
                assertEquals(expectedPrimary, device.findObject(By.res("primary-metric"))?.text)
                assertEquals(expectedSecondary, device.findObject(By.res("secondary-metric"))?.text)
                assertFalse(device.hasObject(By.res("penalty-advisory-caption")))
                assertTrue(device.takeScreenshot(File(output, "case-$index.png")))
            }
        }
        File(output, "report.json").writeText(reports.toString(2) + "\n")
    }
}

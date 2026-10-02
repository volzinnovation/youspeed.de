package de.youspeed.android.alpha

import java.io.File
import java.util.Locale
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DutchPenaltyTests {
    private fun rules() = PenaltyRulesParser.parse(File("../../shared/Rules/NLD-rules.json").readText())

    @Test fun reviewedOfficialTariffsBoundariesAndUnknownContext() {
        val rules = rules()
        val cases = Json.parseToJsonElement(File("../../shared/penalty-rules-tests/NLD-cases.json").readText())
            .jsonObject.getValue("cases").jsonArray
        assertEquals(175, cases.size)
        for (element in cases) {
            val row = element.jsonObject
            fun int(key: String) = row[key]?.jsonPrimitive?.intOrNull
            val highway = row["highway"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content
            for (language in listOf("de", "en", "fr", "nl")) {
                val notice = SpeedPenaltyRuleEngine.resolveNotice(int("excess")!!, rules,
                    row["inside_city"]?.jsonPrimitive?.booleanOrNull, int("posted_limit"), Locale(language),
                    PenaltyRoadArea.matchedMotorway(highway))!!
                val label = "${row["id"]}/$language"
                assertEquals(label, int("fine"), notice.moneyFineEUR)
                assertEquals(label, row["enforcement"]!!.jsonPrimitive.content, notice.enforcementClass)
                assertNull(label, notice.penaltyPoints)
                assertNull(label, notice.drivingBanMonths)
                assertFalse(label, notice.details.contains("{"))
                if ((notice.moneyFineEUR ?: 0) > 0) {
                    assertTrue(label, notice.details.contains("${notice.moneyFineEUR} EUR"))
                    assertTrue(label, notice.details.contains("9 EUR"))
                }
            }
        }
        assertNull(SpeedPenaltyRuleEngine.resolveNotice(0, rules))
        assertFalse(SpeedPenaltyRuleSet.prefersDownloaded(rules.copy(contentRevision = 0), rules))
    }

    @Test fun dutchDashboardShowsFineAndCriminalContextInsteadOfGenericReview() {
        val state = ConsumerUiState(currentLatitude = 52.3676, currentLongitude = 4.9041,
            gpsSignalBars = 4, currentSpeedKmh = 62.0, speedLimitKmh = 50,
            effectiveSpeedLimitSource = EffectiveSpeedLimitSource.BUNDLE,
            activePenaltyRules = ActivePenaltyRules("NLD-rules.json", rules()), limitWayId = "dutch-road",
            lastLookupHighway = "residential", lastLookupInsideCity = true,
            lastLookupCitySource = "settlement:polygon:high")
        assertEquals("140", ConsumerMainScreenLogic.primaryMetricText(state))
        assertEquals("EUR", ConsumerMainScreenLogic.secondaryMetricText(state))
        assertEquals("194", ConsumerMainScreenLogic.primaryMetricText(state.copy(speedLimitKmh = 30, currentSpeedKmh = 42.0)))
        assertEquals("134", ConsumerMainScreenLogic.primaryMetricText(state.copy(lastLookupInsideCity = false)))
        assertEquals("126", ConsumerMainScreenLogic.primaryMetricText(state.copy(lastLookupHighway = "motorway")))
        val criminal = state.copy(currentSpeedKmh = 85.0)
        assertEquals("⚖", ConsumerMainScreenLogic.primaryMetricText(criminal))
        assertFalse(ConsumerMainScreenLogic.secondaryMetricText(criminal).contains("Review"))
        assertEquals("!", ConsumerMainScreenLogic.primaryMetricText(state.copy(lastLookupHighway = "trunk")))
        assertNull(ConsumerMainScreenLogic.currentPenaltyNotice(state.copy(effectiveSpeedLimitSource = EffectiveSpeedLimitSource.STALE_BUNDLE)))
    }
}

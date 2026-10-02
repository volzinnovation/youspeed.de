package de.youspeed.android.alpha

import java.io.File
import java.util.Locale
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SwissPenaltyCorrectionTests {
    private fun rules() = PenaltyRulesParser.parse(File("../../shared/Rules/CHE-rules.json").readText())
    @Test fun officialBoundariesRoadCategoriesAndExceptions() {
        val rules = rules()
        val cases = Json.parseToJsonElement(File("../../shared/penalty-rules-tests/CHE-cases.json").readText()).jsonObject.getValue("cases").jsonArray
        assertEquals(105, cases.size)
        for (element in cases) {
            val row = element.jsonObject
            fun int(key: String) = row[key]?.jsonPrimitive?.intOrNull
            val highway = row["highway"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content
            for (language in listOf("en", "de", "fr", "nl")) {
                val notice = SpeedPenaltyRuleEngine.resolveNotice(int("excess")!!, rules,
                    row["inside_city"]?.jsonPrimitive?.booleanOrNull, int("posted_limit"), Locale(language),
                    PenaltyRoadArea.matchedMotorway(highway))
                val label = "${row["id"]}/$language"
                assertEquals(label, row["notice"]!!.jsonPrimitive.boolean, notice != null)
                assertEquals(label, int("fine"), notice?.moneyFineEUR)
                assertEquals(label, int("months"), notice?.drivingBanMonths)
                assertEquals(label, int("exceptional_months"), notice?.conditionalDrivingBanMonths)
                assertNull(label, notice?.penaltyPoints)
                if (notice != null) {
                    assertNotNull(label, notice.advisoryCaption)
                    val band = rules.bands.single {
                        int("excess")!! >= it.minDeltaKmh && int("excess")!! <= (it.maxDeltaKmh ?: Int.MAX_VALUE)
                    }
                    // Raser is specified by the independent fixture, not the resolver.
                    val templates = if (int("exceptional_months") == 12)
                        rules.postedLimitEscalation!!.localizedTemplates.getValue(language)
                    else band.localizedTemplates.getValue(language)
                    assertEquals(label, templates.titleTemplate, notice.title)
                    assertEquals(label, templates.detailTemplate.replace("{currency}", rules.currencyCode), notice.details)
                    val caption = if (int("exceptional_months") == 12)
                        rules.postedLimitEscalation!!.localizedCaptions.getValue(language)
                    else rules.localizedAdvisoryCaptions.getValue(language)
                    assertEquals(label, caption, notice.advisoryCaption)
                    assertEquals(label, PenaltySeverity.MONEY_ONLY, notice.severity)
                }
            }
        }
    }

    @Test fun olderDownloadedContentCannotOverrideTheNewPackagedRevision() {
        val packaged = rules()
        val legacy = packaged.copy(contentRevision = 0)
        assertFalse(SpeedPenaltyRuleSet.prefersDownloaded(legacy, packaged))
        assertTrue(SpeedPenaltyRuleSet.prefersDownloaded(packaged, packaged))
        assertTrue(SpeedPenaltyRuleSet.prefersDownloaded(packaged.copy(contentRevision = 20261002), packaged))
        assertTrue(SpeedPenaltyRuleSet.prefersDownloaded(legacy, null))
    }

    @Test fun motorwayUsesMatchedClassAndUncertaintyClearsTheExactNumber() {
        val state = ConsumerUiState(currentLatitude = 47.3769, currentLongitude = 8.5417,
            gpsSignalBars = 4, currentSpeedKmh = 90.0, speedLimitKmh = 80,
            effectiveSpeedLimitSource = EffectiveSpeedLimitSource.BUNDLE,
            activePenaltyRules = ActivePenaltyRules("CHE-rules.json", rules()), limitWayId = "swiss-motorway",
            lastLookupHighway = "motorway", lastLookupInsideCity = true, lastLookupCitySource = "settlement:polygon:high")
        assertEquals("60", ConsumerMainScreenLogic.primaryMetricText(state))
        assertEquals("CHF", ConsumerMainScreenLogic.secondaryMetricText(state))
        assertEquals("≥1", ConsumerMainScreenLogic.primaryMetricText(state.copy(currentSpeedKmh = 112.0)))
        assertEquals("!", ConsumerMainScreenLogic.primaryMetricText(state.copy(lastLookupHighway = null)))
        assertEquals("!", ConsumerMainScreenLogic.primaryMetricText(state.copy(lastLookupHighway = "motorway_link")))
        assertNull(ConsumerMainScreenLogic.currentPenaltyNotice(state.copy(effectiveSpeedLimitSource = EffectiveSpeedLimitSource.STALE_BUNDLE)))
    }
}

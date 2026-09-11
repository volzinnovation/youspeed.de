package de.youspeed.android.alpha

import java.io.File
import java.util.Locale
import org.junit.Assert.*
import org.junit.Test

class CountryPenaltyTests {
    private fun rules(code: String) = PenaltyRulesParser.parse(File("src/main/assets/Rules/$code-rules.json").readText())
    private fun catalog() = RegionalPackCatalog.decode(File("../../shared/RegionalCoverage/catalog-v1.json").readBytes())

    @Test fun countryAliasesNeverDefaultUnknownToGermany() {
        listOf("DE" to "DEU", "fr" to "FRA", " NL " to "NLD", "BEL" to "BEL").forEach {
            assertEquals(it.second, PenaltyCountryCodes.normalize(it.first))
        }
        listOf(null, "", "US", "BAD", "DEU-rules.json").forEach { assertNull(PenaltyCountryCodes.normalize(it)) }
        assertFalse(ActivePenaltyRules.unavailable().isAvailable)
        assertNull(SpeedPenaltyRuleEngine.resolveNotice(50, ActivePenaltyRules.unavailable().ruleSet))
    }

    @Test fun simulatedDeFrBeNlTravelSwitchesWithoutAnyDownloadedMap() {
        val selector = PenaltyCountrySelection()
        val catalog = catalog()
        fun fix(lat: Double, lon: Double, time: Double, accuracy: Double = 5.0, now: Double = time) =
            selector.update(catalog, lat, lon, accuracy, time, now)
        assertEquals("DEU", fix(49.0102, 8.4266, 100.0))
        for ((index, country) in listOf("FRA", "BEL", "NLD").withIndex()) {
            val scenario = CountryPenaltyScreenshotScenario(country, 10)
            val start = 120.0 + 30 * index
            assertNull(fix(scenario.latitude, scenario.longitude, start))
            assertNull(fix(scenario.latitude, scenario.longitude, start + 8))
            assertEquals(country, fix(scenario.latitude, scenario.longitude, start + 16))
        }
        assertNull(fix(52.3676, 4.9041, 210.0, accuracy = 101.0))
        assertNull(fix(52.3676, 4.9041, 211.0, now = 250.0))
        assertNull(fix(0.0, 0.0, 260.0))
        assertNull(fix(52.3676, 4.9041, 999999.0, now = 270.0))
        assertEquals("NLD", fix(52.3676, 4.9041, 271.0))
    }

    @Test fun duplicateAfterOverlapKeepsThePreviousCountrySuspended() {
        val regions = listOf("DE", "FR").map { country ->
            RegionalPackCatalog.Region(country, country, country, listOf(0.0, 0.0, 5.0, 5.0),
                listOf(listOf(listOf(listOf(0.0, 0.0), listOf(5.0, 0.0), listOf(5.0, 5.0), listOf(0.0, 5.0), listOf(0.0, 0.0)))))
        }
        val selector = PenaltyCountrySelection()
        assertEquals("DEU", selector.update(RegionalPackCatalog(regions.take(1)), 2.0, 2.0, 5.0, 100.0, 100.0))
        assertNull(selector.update(RegionalPackCatalog(regions), 2.0, 2.0, 5.0, 101.0, 101.0))
        assertNull(selector.update(RegionalPackCatalog(regions.take(1)), 2.0, 2.0, 5.0, 101.0, 101.0))
        assertNull(selector.update(null, 2.0, 2.0, 5.0, 102.0, 102.0))
    }

    @Test fun duplicateAndOlderValidFixPreserveTheDisplayedCountryAndOriginalExpiry() {
        val selector = PenaltyCountrySelection()
        val catalog = catalog()
        assertEquals("DEU", selector.update(catalog, 49.0102, 8.4266, 5.0, 100.0, 100.0))
        assertTrue(selector.lastUpdateAcceptedNewFix)
        assertEquals(130.05, selector.expiryTimestampSeconds!!, 0.0001)
        // Different coordinates on a redelivered timestamp cannot imply a border crossing.
        assertEquals("DEU", selector.update(catalog, 48.8566, 2.3522, 5.0, 100.0, 110.0))
        assertFalse(selector.lastUpdateAcceptedNewFix)
        assertEquals("DEU", selector.update(catalog, 48.8566, 2.3522, 5.0, 99.0, 112.0))
        assertFalse(selector.lastUpdateAcceptedNewFix)
        assertEquals(130.05, selector.expiryTimestampSeconds!!, 0.0001)
        assertEquals("DEU", selector.expire(130.0))
        assertNull(selector.expire(130.05))
        assertNull(selector.expiryTimestampSeconds)
    }

    @Test fun duplicateAndOlderFixesNeitherCountNorResetPendingCountryEvidence() {
        val selector = PenaltyCountrySelection()
        val catalog = catalog()
        fun germany(time: Double, now: Double = time) = selector.update(catalog, 49.0102, 8.4266, 5.0, time, now)
        fun france(time: Double, now: Double = time) = selector.update(catalog, 48.8566, 2.3522, 5.0, time, now)
        assertEquals("DEU", germany(100.0))
        assertNull(france(110.0))
        val pendingExpiry = selector.expiryTimestampSeconds
        assertNull(germany(110.0, 112.0))
        assertNull(germany(105.0, 113.0))
        assertNull(france(110.0, 114.0))
        assertEquals(pendingExpiry, selector.expiryTimestampSeconds)
        assertNull(france(118.0))
        assertEquals("FRA", france(126.0))
    }

    @Test fun invalidDuplicateClearsFineAndValidRedeliveryCannotRestoreIt() {
        val selector = PenaltyCountrySelection()
        val catalog = catalog()
        fun fix(time: Double, now: Double, accuracy: Double = 5.0) =
            selector.update(catalog, 49.0102, 8.4266, accuracy, time, now)
        assertEquals("DEU", fix(100.0, 100.0))
        assertNull(fix(100.0, 101.0, accuracy = 101.0))
        assertNull(selector.expiryTimestampSeconds)
        assertNull(fix(100.0, 102.0))
        assertFalse(selector.lastUpdateAcceptedNewFix)
        assertNull(fix(99.0, 102.0))
        assertEquals("DEU", fix(103.0, 103.0))
        assertEquals(133.05, selector.expiryTimestampSeconds!!, 0.0001)
        assertNull(selector.update(null, 49.0102, 8.4266, 5.0, 103.0, 104.0))
        assertNull(fix(103.0, 105.0))
    }

    @Test fun invalidFixResetsPendingEvidenceAndOldFixCannotReestablishIt() {
        val selector = PenaltyCountrySelection()
        val catalog = catalog()
        fun france(time: Double, accuracy: Double = 5.0) = selector.update(catalog, 48.8566, 2.3522, accuracy, time, time)
        assertEquals("DEU", selector.update(catalog, 49.0102, 8.4266, 5.0, 100.0, 100.0))
        assertNull(france(110.0))
        assertNull(france(115.0, 101.0))
        assertNull(selector.update(catalog, 48.8566, 2.3522, 5.0, 110.0, 116.0))
        assertNull(selector.expiryTimestampSeconds)
        assertNull(france(118.0))
        assertNull(france(126.0))
        assertEquals("FRA", france(134.0))
    }

    @Test fun countryTransitionRequiresNewEvidenceAfterGpsSilence() {
        val selector = PenaltyCountrySelection()
        val catalog = catalog()
        fun fix(lat: Double, lon: Double, time: Double) = selector.update(catalog, lat, lon, 5.0, time, time)
        assertEquals("DEU", fix(49.0102, 8.4266, 100.0))
        assertNull(fix(48.8566, 2.3522, 110.0))
        assertNull(fix(48.8566, 2.3522, 118.0))
        assertNull(fix(48.8566, 2.3522, 160.0))
        assertNull(fix(48.8566, 2.3522, 168.0))
        assertEquals("FRA", fix(48.8566, 2.3522, 176.0))
    }

    @Test fun franceLowFineFollowsPostedLimitInsteadOfUrbanFlag() {
        val rules = rules("FRA")
        for (urban in listOf(true, false, null)) {
            assertEquals(135, SpeedPenaltyRuleEngine.resolveNotice(4, rules, urban, 50)?.moneyFineEUR)
            assertEquals(68, SpeedPenaltyRuleEngine.resolveNotice(4, rules, urban, 80)?.moneyFineEUR)
            assertNull(SpeedPenaltyRuleEngine.resolveNotice(4, rules, urban)?.moneyFineEUR)
        }
        assertEquals(0, SpeedPenaltyRuleEngine.resolveNotice(4, rules)?.penaltyPoints)
        assertEquals(1, SpeedPenaltyRuleEngine.resolveNotice(5, rules)?.penaltyPoints)
        assertNull(SpeedPenaltyRuleEngine.resolveNotice(50, rules)?.moneyFineEUR)
        assertEquals("criminal", SpeedPenaltyRuleEngine.resolveNotice(50, rules)?.enforcementClass)
    }

    @Test fun allBandsHaveCompleteLocalizedNoticesAndNoHoles() {
        for (country in listOf("FRA", "NLD", "BEL")) {
            val rules = rules(country)
            for (language in listOf("de", "en", "fr", "nl")) {
                for (delta in 1..100) {
                    val notice = SpeedPenaltyRuleEngine.resolveNotice(delta, rules, true, 50, Locale.forLanguageTag(language))
                    assertNotNull("$country $language +$delta", notice)
                    assertTrue(notice!!.title.isNotBlank() && notice.details.isNotBlank())
                    assertFalse(notice.title.contains("{"))
                    assertFalse(notice.details.contains("{"))
                    assertEquals(rules.bands.single { delta >= it.minDeltaKmh && delta <= (it.maxDeltaKmh ?: Int.MAX_VALUE) }
                        .localizedTemplates[language]!!.titleTemplate.replace("{delta}", "$delta"), notice.title)
                    if (country != "FRA") {
                        assertNull(notice.penaltyPoints)
                        assertNull(notice.drivingBanMonths)
                        assertNull(notice.conditionalDrivingBanMonths)
                    }
                }
            }
            assertNull(SpeedPenaltyRuleEngine.resolveNotice(0, rules))
        }
        assertEquals(58, SpeedPenaltyRuleEngine.resolveNotice(10, rules("BEL"))?.moneyFineEUR)
        assertNull(SpeedPenaltyRuleEngine.resolveNotice(11, rules("BEL"))?.moneyFineEUR)
        assertEquals("context_dependent", SpeedPenaltyRuleEngine.resolveNotice(39, rules("NLD"))?.enforcementClass)
        assertEquals("criminal", SpeedPenaltyRuleEngine.resolveNotice(40, rules("NLD"))?.enforcementClass)
    }

    @Test fun contextualFineDisplaysReviewWithoutFakePoints() {
        val state = ConsumerUiState(currentSpeedKmh = 85.0, speedLimitKmh = 50,
            currentLatitude = 50.8503, currentLongitude = 4.3517, gpsSignalBars = 4,
            activePenaltyRules = ActivePenaltyRules("BEL-rules.json", rules("BEL")))
        assertEquals("!", ConsumerMainScreenLogic.primaryMetricText(state))
        assertFalse(ConsumerMainScreenLogic.secondaryMetricText(state).contains("EUR"))
        assertEquals(1.0, ConsumerMainScreenLogic.overspeedBackgroundProgress(state)!!, 0.0)
    }
}

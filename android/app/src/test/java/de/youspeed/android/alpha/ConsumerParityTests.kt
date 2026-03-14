package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConsumerParityTests {
    @Test
    fun requiresWelcomeForSeedNoneAndStaleBundles() {
        assertTrue(ConsumerAppLogic.requiresWelcome("seed", Instant.parse("2026-03-12T00:00:00Z")))
        assertTrue(ConsumerAppLogic.requiresWelcome("none", Instant.parse("2026-03-12T00:00:00Z")))
        assertTrue(ConsumerAppLogic.requiresWelcome("2026-01-01", Instant.parse("2026-03-12T00:00:00Z")))
        assertFalse(ConsumerAppLogic.requiresWelcome("2026-03-03", Instant.parse("2026-03-12T00:00:00Z")))
    }

    @Test
    fun parsesBundleDatesLikeIphoneApp() {
        assertEquals("2026-03-03", ConsumerAppLogic.parseBundleDate("2026-03-03")?.toString())
        assertEquals("2026-03-03", ConsumerAppLogic.parseBundleDate("deu_20260303_latest")?.toString())
        assertNull(ConsumerAppLogic.parseBundleDate("latest"))
    }

    @Test
    fun parsesGitHubReleaseAssetPaths() {
        val parsed = HttpUrlFetcher.parseGitHubReleaseAssetUrl(
            "https://github.com/volzinnovation/youspeed.de/releases/download/baden-wuerttemberg/baden-wuerttemberg_manifest.json"
        )
        assertNotNull(parsed)
        assertEquals("volzinnovation", parsed?.owner)
        assertEquals("youspeed.de", parsed?.repo)
        assertEquals("baden-wuerttemberg", parsed?.tag)
        assertEquals("baden-wuerttemberg_manifest.json", parsed?.assetName)
    }

    @Test
    fun screenshotFixturesMirrorIphoneSurface() {
        val fixture = AppScreenshotState.WARN_LEVEL_3.fixture
        assertEquals(86.0, fixture.currentSpeedKmh, 0.0)
        assertEquals(50, fixture.speedLimitKmh)
        assertEquals("Durlacher Allee", fixture.streetName)
        assertEquals("Karlsruhe", fixture.cityName)
        assertEquals(4, fixture.gpsSignalBars)
    }

    @Test
    fun pedestrianScreenshotFixtureMatchesWalkingSignSurface() {
        val fixture = AppScreenshotState.PEDESTRIAN_ZONE.fixture
        assertEquals(5.0, fixture.currentSpeedKmh, 0.0)
        assertNull(fixture.speedLimitKmh)
        assertEquals("Schritt", fixture.speedLimitDisplayText)
        assertEquals("Im Kloster", fixture.streetName)
        assertEquals("Bad Herrenalb", fixture.cityName)
    }

    @Test
    fun matcherStartupProfileMigratesLegacyDefaultToM2() {
        assertEquals(MatcherDebugProfile.M2, MatcherDebugProfile.resolveInitialProfile("m1", forcedVersion = 0))
        assertEquals(MatcherDebugProfile.M2, MatcherDebugProfile.resolveInitialProfile(null, forcedVersion = 0))
    }

    @Test
    fun matcherStartupProfilePreservesExplicitSelectionAfterMigration() {
        assertEquals(
            MatcherDebugProfile.M4,
            MatcherDebugProfile.resolveInitialProfile("m4", forcedVersion = MatcherDebugProfile.forcedProfileVersion),
        )
    }

    @Test
    fun matcherProfilesFollowPaperLadder() {
        assertEquals("M1 Connected baseline", MatcherDebugProfile.M1.debugLabel)
        assertEquals("M2 Nearest + street-ref continuity", MatcherDebugProfile.M2.debugLabel)
        assertEquals("M3 M2 + connected-candidate gate", MatcherDebugProfile.M3.debugLabel)
        assertEquals(LookupMatchingModel.CORRIDOR_HMM_RAW_MINI_HMM, MatcherDebugProfile.M4.lookupModel)
        assertEquals(LookupMatchingModel.CORRIDOR_HMM, MatcherDebugProfile.M5.lookupModel)
    }

    @Test
    fun parsesGermanPenaltyRulesAndResolvesInnerortsBandLikeIphone() {
        val raw = """
            {
              "format": "youspeed.penalty.rules",
              "schema_version": 1,
              "land_code": "DEU",
              "land_name": "Deutschland",
              "waehrung_code": "EUR",
              "stufen": [
                {
                  "min_ueber_kmh": 31,
                  "max_ueber_kmh": 40,
                  "schweregrad": "punkte_und_geldbusse",
                  "titel_vorlage": "Hoher Verstoss",
                  "detail_vorlage": "Voraussichtlich innerorts 260 {waehrung}",
                  "geldbusse_eur": 200,
                  "punkte": 1,
                  "ortsvarianten": {
                    "innerorts": { "geldbusse_eur": 260, "punkte": 2, "fahrverbot_monate": 1 },
                    "ausserorts": { "geldbusse_eur": 200, "punkte": 1, "fahrverbot_monate": 0 }
                  }
                }
              ]
            }
        """.trimIndent()

        val rules = PenaltyRulesParser.parse(raw)
        val notice = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh = 36, rules = rules, insideCity = true)

        assertEquals("DEU", rules.countryCode)
        assertEquals(1, rules.bands.size)
        assertNotNull(notice)
        assertEquals(260, notice?.moneyFineEUR)
        assertEquals(2, notice?.penaltyPoints)
        assertEquals(1, notice?.drivingBanMonths)
    }

    @Test
    fun mainScreenLogicPrefersDrivingBanPresentationForHighGermanOverspeed() {
        val state = ConsumerUiState(
            startupDataState = StartupDataState.READY,
            activeDBPath = "/tmp/mock.sqlite",
            currentSpeedKmh = 86.0,
            speedLimitKmh = 50,
            currentLatitude = 49.0102,
            currentLongitude = 8.4266,
            gpsSignalBars = 4,
            activePenaltyRules = ActivePenaltyRules(
                fileName = "DEU-rules.json",
                ruleSet = PenaltyRulesParser.parse(
                    """
                        {
                          "format": "youspeed.penalty.rules",
                          "schema_version": 1,
                          "land_code": "DEU",
                          "land_name": "Deutschland",
                          "waehrung_code": "EUR",
                          "stufen": [
                            {
                              "min_ueber_kmh": 31,
                              "max_ueber_kmh": 40,
                              "schweregrad": "punkte_und_geldbusse",
                              "titel_vorlage": "Hoher Verstoss",
                              "detail_vorlage": "Voraussichtlich innerorts 260 {waehrung}",
                              "geldbusse_eur": 200,
                              "punkte": 1,
                              "ortsvarianten": {
                                "innerorts": { "geldbusse_eur": 260, "punkte": 2, "fahrverbot_monate": 1 },
                                "ausserorts": { "geldbusse_eur": 200, "punkte": 1, "fahrverbot_monate": 0 }
                              }
                            }
                          ]
                        }
                    """.trimIndent()
                ),
            ),
            lastLookupInsideCity = true,
        )

        assertEquals(36, ConsumerMainScreenLogic.currentOverspeedKmh(state))
        assertEquals("1", ConsumerMainScreenLogic.primaryMetricText(state))
        assertEquals("Monat Fahrverbot", ConsumerMainScreenLogic.secondaryMetricText(state))
        assertTrue(ConsumerMainScreenLogic.isDrivingBanWarningActive(state))
    }

    @Test
    fun mainScreenLogicShowsWalkingPaceLabelForPedestrianZoneOverride() {
        val state = ConsumerUiState(
            startupDataState = StartupDataState.READY,
            activeDBPath = "/tmp/mock.sqlite",
            currentLatitude = 48.7990,
            currentLongitude = 8.4383,
            gpsSignalBars = 4,
            speedLimitDisplayText = "Schritt",
        )

        assertEquals("Schritt", ConsumerMainScreenLogic.limitText(state))
        assertEquals(0, ConsumerMainScreenLogic.currentOverspeedKmh(state))
        assertTrue(ConsumerMainScreenLogic.showsPedestrianZoneSign(state))
    }
}

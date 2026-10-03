package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import java.util.Locale
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConsumerParityTests {
    private fun withLocale(locale: Locale, block: () -> Unit) {
        val previous = Locale.getDefault()
        try {
            Locale.setDefault(locale)
            block()
        } finally {
            Locale.setDefault(previous)
        }
    }

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
    fun derivedSpeedUsesDistanceAndElapsedTime() {
        assertEquals(36.0, ConsumerSessionController.derivedSpeedKmh(distanceM = 50.0, elapsedSeconds = 5.0), 0.0001)
    }

    @Test
    fun derivedSpeedSubtractsAccuracyAllowance() {
        assertEquals(
            8.4,
            ConsumerSessionController.derivedSpeedKmh(distanceM = 12.0, elapsedSeconds = 3.0, accuracyAllowanceM = 5.0),
            0.0001,
        )
        assertEquals(
            0.0,
            ConsumerSessionController.derivedSpeedKmh(distanceM = 4.0, elapsedSeconds = 3.0, accuracyAllowanceM = 5.0),
            0.0001,
        )
    }

    @Test
    fun derivedSpeedKeepsLowNonZeroValues() {
        assertEquals(3.6, ConsumerSessionController.derivedSpeedKmh(distanceM = 2.0, elapsedSeconds = 2.0), 0.0001)
    }

    @Test
    fun trafficSignDirectionUsesTheSecondGpsFixWithoutReportedBearing() {
        assertEquals(
            90.0,
            ConsumerSessionController.trafficSignHeadingDegrees(
                reportedBearingDegrees = null,
                previousLatitude = 49.0,
                previousLongitude = 8.0,
                currentLatitude = 49.0,
                currentLongitude = 8.001,
            ) ?: -1.0,
            0.01,
        )
        assertEquals(
            271.0,
            ConsumerSessionController.trafficSignHeadingDegrees(
                reportedBearingDegrees = 271.0,
                previousLatitude = 49.0,
                previousLongitude = 8.0,
                currentLatitude = 49.0,
                currentLongitude = 8.001,
            ) ?: -1.0,
            0.0,
        )
    }

    @Test
    fun onlyAnExplicitOutsideToInsideTransitionInvalidatesTsr() {
        assertTrue(TrafficSignBundleContextPolicy.enteredCity(false, true, "settlement:zone_traffic:high", "settlement:zone_traffic:high"))
        assertFalse(TrafficSignBundleContextPolicy.enteredCity(null, true))
        assertFalse(TrafficSignBundleContextPolicy.enteredCity(true, true))
        assertFalse(TrafficSignBundleContextPolicy.enteredCity(true, false))
    }

    @Test
    fun cameraEyeAppearsOnlyForAnAppliedCameraLimit() {
        assertTrue(
            CameraSpeedLimitUsePresentation.isVisible(
                isInSpeedCaptureMode = false,
                source = EffectiveSpeedLimitSource.CAMERA,
                hasResolvedValue = true,
            ),
        )
        assertFalse(
            CameraSpeedLimitUsePresentation.isVisible(
                isInSpeedCaptureMode = false,
                source = EffectiveSpeedLimitSource.BUNDLE,
                hasResolvedValue = true,
            ),
        )
        assertFalse(
            CameraSpeedLimitUsePresentation.isVisible(
                isInSpeedCaptureMode = true,
                source = EffectiveSpeedLimitSource.CAMERA,
                hasResolvedValue = true,
            ),
        )
    }

    @Test
    fun coveringBundleExcludesForeignActiveRouteBeforeRoadEvidence() {
        val covering = LocalBundleRoute("france/rhone-alpes", "v1", "FRA", "/ra.sqlite")
        val active = LocalBundleRoute("switzerland", "v2", "CHE", "/ch.sqlite")
        // The Lyon fix can have no road within the selected matcher's radius.
        // An outside incumbent must never compete, even if it reports a road.
        for (outsideHasRoad in listOf(false, true)) {
            val probes = listOf(
                BundleRouteProbe(covering, false, false, null, null),
                BundleRouteProbe(active, outsideHasRoad, outsideHasRoad, null, null),
            )
            assertEquals(covering, BundleRouteSelection.choose(probes, active.dbPath, listOf(covering)))
        }
    }

    @Test
    fun bundleRouteCoverageGapNeverUsesActiveDatabase() {
        val active = LocalBundleRoute("switzerland", "v2", "CHE", "/ch.sqlite", "a".repeat(64))
        val probe = BundleRouteProbe(active, true, true, 0.0, 0.0)
        assertNull(BundleRouteSelection.choose(listOf(probe), active.dbPath, emptyList()))
        assertNull(BundleRouteSelection.choose(emptyList(), null, emptyList()))
    }

    @Test
    fun overlappingBundleRouteKeepsCurrentOnTieAndSwitchesToOnlyRoadMatch() {
        val current = LocalBundleRoute("germany/rheinland-pfalz", "v1", "DEU", "/rp.sqlite")
        val alternate = LocalBundleRoute("germany/baden-wuerttemberg", "v1", "DEU", "/bw.sqlite")
        val currentProbe = BundleRouteProbe(current, true, true, 20.0, 20.0)
        val tiedAlternate = BundleRouteProbe(alternate, true, true, 20.0, 20.0)
        assertEquals(current, BundleRouteSelection.choose(listOf(currentProbe, tiedAlternate), current.dbPath, listOf(current, alternate)))

        val noWayCurrent = currentProbe.copy(hasWayMatch = false, hasSpeedMatch = false, nearestCandidateDistanceM = null, nearestSpeedCandidateDistanceM = null)
        assertEquals(alternate, BundleRouteSelection.choose(listOf(noWayCurrent, tiedAlternate), current.dbPath, listOf(current, alternate)))
    }

    @Test
    fun moreNearbyRoadFeaturesSwitchImmediatelyInBothBorderDirections() {
        val france = LocalBundleRoute("alsace", "v1", "FRA", "/alsace.sqlite")
        val germany = LocalBundleRoute("baden-wuerttemberg", "v1", "DEU", "/bw.sqlite")
        for ((current, destination) in listOf(france to germany, germany to france)) {
            // Both maps still match, and the incumbent has a much better old
            // proximity score. Local road completeness must still win.
            val incumbent = BundleRouteProbe(current, true, true, 0.0, 0.0, candidateCount = 2, speedCandidateCount = 2)
            val moreComplete = BundleRouteProbe(destination, true, true, 90.0, 90.0, candidateCount = 3, speedCandidateCount = 1)
            val probes = listOf(incumbent, moreComplete)
            val routes = listOf(current, destination)
            assertEquals(destination, BundleRouteSelection.choose(probes, current.dbPath, routes))
            assertEquals(destination, BundleRouteSelection.choose(probes.reversed(), null, routes))
            assertEquals(destination, BundleRouteSelection.choose(probes, destination.dbPath, routes))
        }
    }

    @Test
    fun equalRoadCountsPreferMoreSpeedFeaturesThenKeepExistingHysteresis() {
        val current = LocalBundleRoute("alsace", "v1", "FRA", "/alsace.sqlite")
        val alternate = LocalBundleRoute("baden-wuerttemberg", "v1", "DEU", "/bw.sqlite")
        val incumbent = BundleRouteProbe(current, true, true, 0.0, 0.0, candidateCount = 4, speedCandidateCount = 1)
        val moreSpeedFeatures = BundleRouteProbe(alternate, true, true, 90.0, 90.0, candidateCount = 4, speedCandidateCount = 2)
        val routes = listOf(current, alternate)
        assertEquals(alternate, BundleRouteSelection.choose(listOf(incumbent, moreSpeedFeatures), current.dbPath, routes))
        val tiedCounts = moreSpeedFeatures.copy(speedCandidateCount = 1, nearestCandidateDistanceM = 0.0, nearestSpeedCandidateDistanceM = 0.0)
        assertEquals(current, BundleRouteSelection.choose(listOf(incumbent, tiedCounts), current.dbPath, routes))
        val smallScoreLead = tiedCounts.copy(nearestCandidateDistanceM = 10.0, nearestSpeedCandidateDistanceM = 10.0)
        assertEquals(alternate, BundleRouteSelection.choose(listOf(incumbent, smallScoreLead), alternate.dbPath, routes))
    }

    @Test
    fun nearbyFeatureCountsNeverOverrideCoverageEligibility() {
        val covering = LocalBundleRoute("baden-wuerttemberg", "v1", "DEU", "/bw.sqlite")
        val outside = LocalBundleRoute("alsace", "v1", "FRA", "/alsace.sqlite")
        val probes = listOf(
            BundleRouteProbe(covering, false, false, null, null, candidateCount = 1),
            BundleRouteProbe(outside, true, true, 0.0, 0.0, candidateCount = 100, speedCandidateCount = 100),
        )
        assertEquals(covering, BundleRouteSelection.choose(probes, outside.dbPath, listOf(covering)))
        assertNull(BundleRouteSelection.choose(probes, outside.dbPath, emptyList()))
    }

    @Test
    fun trafficSignGenerationDoesNotSwitchForSameRouteWithUnknownDigest() {
        val route = BundleRouteIdentity(
            dbPath = "/bundles/belgium/belgium_speeds.sqlite",
            bundleVersion = "2026-09-15",
            countryCode = "BEL",
            dbSha256 = null,
        )
        val current = route.copy(dbSha256 = "known-current-digest")

        assertFalse(route.differsFrom(current))
        assertFalse(current.differsFrom(route))
    }

    @Test
    fun trafficSignGenerationSwitchesForRealRouteIdentityChanges() {
        val current = BundleRouteIdentity("/old.sqlite", "2026-09-14", "BEL", "a")

        assertTrue(current.copy(dbPath = "/new.sqlite").differsFrom(current))
        assertTrue(current.copy(bundleVersion = "2026-09-15").differsFrom(current))
        assertTrue(current.copy(countryCode = "NLD").differsFrom(current))
        assertTrue(current.copy(dbSha256 = "b").differsFrom(current))
    }

    @Test
    fun trafficSignModelSelectionOnlyRepeatsForARealRouteOrCountryChange() {
        assertTrue(BundleRouteSelection.shouldSelectTrafficSignModel(null, "BEL", routeChanged = false))
        assertFalse(BundleRouteSelection.shouldSelectTrafficSignModel("BEL", "BEL", routeChanged = false))
        assertTrue(BundleRouteSelection.shouldSelectTrafficSignModel("BEL", "NLD", routeChanged = false))
        assertTrue(BundleRouteSelection.shouldSelectTrafficSignModel("BEL", "BEL", routeChanged = true))
    }

    @Test
    fun staleBundleLimitIsNotUsedForOverspeedWarnings() {
        val state = ConsumerUiState(
            currentSpeedKmh = 91.0,
            speedLimitKmh = 50,
            effectiveSpeedLimitSource = EffectiveSpeedLimitSource.STALE_BUNDLE,
        )
        assertEquals(0, ConsumerMainScreenLogic.currentOverspeedKmh(state))
        assertEquals("50", ConsumerMainScreenLogic.limitText(state))
    }

    @Test
    fun startupPreparationPreservesPreviousDriveAndCreatesOnlyMissingFiles() {
        val root = java.nio.file.Files.createTempDirectory("drive-log-retention").toFile()
        try {
            val gps = File(root, "logs/gps.csv")
            val match = File(root, "logs/match.ndjson")
            ConsumerSessionController.prepareDrivingLogFiles(gps, match)
            assertTrue(gps.readText().startsWith("fix_id,timestamp_utc,"))
            gps.appendText("previous drive GPS\n")
            match.writeText("{\"previousDrive\":true}\n")
            val gpsBytes = gps.readBytes()
            val matchBytes = match.readBytes()
            repeat(2) { ConsumerSessionController.prepareDrivingLogFiles(gps, match) }
            assertTrue(gpsBytes.contentEquals(gps.readBytes()))
            assertTrue(matchBytes.contentEquals(match.readBytes()))
            match.delete()
            ConsumerSessionController.prepareDrivingLogFiles(gps, match)
            assertTrue(gpsBytes.contentEquals(gps.readBytes()))
            assertEquals("", match.readText())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun resetDrivingLogFilesRewritesCsvAndClearsMatcherLog() {
        val rootDir = createTempDirectory(prefix = "driving-logs-").toFile()
        try {
            val gpsLogFile = File(rootDir, "logs/gps_fix_log.csv")
            val matchLogFile = File(rootDir, "logs/drive_match_log.ndjson")
            gpsLogFile.parentFile?.mkdirs()
            gpsLogFile.writeText("stale")
            matchLogFile.parentFile?.mkdirs()
            matchLogFile.writeText("{\"stale\":true}\n")

            ConsumerSessionController.resetDrivingLogFiles(gpsLogFile = gpsLogFile, matchLogFile = matchLogFile)

            assertTrue(gpsLogFile.exists())
            assertTrue(matchLogFile.exists())
            assertTrue(gpsLogFile.readText().startsWith("fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m"))
            assertEquals("", matchLogFile.readText())
        } finally {
            rootDir.deleteRecursively()
        }
    }

    @Test
    fun filteredDisplaySpeedUsesDerivedBelowLowSpeedThreshold() {
        assertEquals(
            1.8,
            ConsumerSessionController.filteredDisplaySpeedKmh(
                rawSpeedKmh = 3.8,
                fallbackDerivedSpeedKmh = 1.8,
                speedAccuracyKmh = null,
                previousDisplaySpeedKmh = 7.2,
            ),
            0.0001,
        )
        assertEquals(
            0.0,
            ConsumerSessionController.filteredDisplaySpeedKmh(
                rawSpeedKmh = 5.4,
                fallbackDerivedSpeedKmh = 0.0,
                speedAccuracyKmh = 2.0,
                previousDisplaySpeedKmh = 0.0,
            ),
            0.0001,
        )
    }

    @Test
    fun filteredDisplaySpeedUsesRawGpsAtOrAboveThreshold() {
        assertEquals(
            7.0,
            ConsumerSessionController.filteredDisplaySpeedKmh(
                rawSpeedKmh = 7.0,
                fallbackDerivedSpeedKmh = 2.8,
                speedAccuracyKmh = null,
                previousDisplaySpeedKmh = 0.0,
            ),
            0.0001,
        )
        assertEquals(
            12.4,
            ConsumerSessionController.filteredDisplaySpeedKmh(
                rawSpeedKmh = 12.4,
                fallbackDerivedSpeedKmh = 4.2,
                speedAccuracyKmh = null,
                previousDisplaySpeedKmh = 0.0,
            ),
            0.0001,
        )
    }

    @Test
    fun filteredDisplaySpeedClampsNonPositiveInputs() {
        assertEquals(
            0.0,
            ConsumerSessionController.filteredDisplaySpeedKmh(
                rawSpeedKmh = 0.0,
                fallbackDerivedSpeedKmh = 0.0,
                speedAccuracyKmh = null,
                previousDisplaySpeedKmh = 0.0,
            ),
            0.0001,
        )
        assertEquals(
            0.0,
            ConsumerSessionController.filteredDisplaySpeedKmh(
                rawSpeedKmh = -1.0,
                fallbackDerivedSpeedKmh = -2.0,
                speedAccuracyKmh = null,
                previousDisplaySpeedKmh = 0.0,
            ),
            0.0001,
        )
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
    fun cameraScreenshotFixtureExercisesTheEyeIndicator() {
        val fixture = AppScreenshotState.CAMERA_LIMIT_ACTIVE.fixture
        assertEquals(30, fixture.speedLimitKmh)
        assertEquals("Lindenweg", fixture.streetName)
        assertTrue(fixture.insideCity)
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
    fun matcherStartupProfileMigratesLegacyDefaultToM7() {
        assertEquals(MatcherDebugProfile.M7, MatcherDebugProfile.default)
        assertEquals(MatcherDebugProfile.M7, MatcherDebugProfile.resolveInitialProfile("m1", forcedVersion = 0))
        assertEquals(MatcherDebugProfile.M7, MatcherDebugProfile.resolveInitialProfile(null, forcedVersion = 0))
    }

    @Test
    fun coarseLocationShowsAdministrativeContextWithoutGpsRoadMatch() {
        val state = ConsumerUiState(
            coarseLatitude = 48.80,
            coarseLongitude = 8.44,
            coarseHorizontalAccuracyM = 2_000.0,
            coarseLocationSource = "wifi_network",
            coarseCityPlaceName = "Bad Herrenalb",
            coarseCityDistrictName = "Landkreis Calw",
        )

        assertTrue(ConsumerMainScreenLogic.hasUsableCoarseLocation(state))
        assertFalse(ConsumerMainScreenLogic.hasUsableGpsFix(state))
        assertEquals("Bad Herrenalb", ConsumerMainScreenLogic.debugWayIdText(state))
        assertTrue(ConsumerMainScreenLogic.shouldShowCityBadge(state))
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
        assertEquals(LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_HEURISTIC, MatcherDebugProfile.M6.lookupModel)
        assertEquals(
            LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC,
            MatcherDebugProfile.M7.lookupModel,
        )
        assertEquals(
            LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_FALLBACK_HEURISTIC,
            MatcherDebugProfile.M8.lookupModel,
        )
        assertEquals("M9 M8 + guarded stale-ref suppression", MatcherDebugProfile.M9.debugLabel)
        assertEquals(LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC, MatcherDebugProfile.M9.lookupModel)
        assertEquals(
            LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_NODE_AWARE_HEURISTIC,
            MatcherDebugProfile.M10.lookupModel,
        )
        assertEquals(LookupMatchingModel.SIMPLE_SEQUENCE_PARTICLE_HEURISTIC, MatcherDebugProfile.M11.lookupModel)
        assertEquals(LookupMatchingModel.SIMPLE_SEQUENCE_VITERBI_HEURISTIC, MatcherDebugProfile.M12.lookupModel)
    }

    @Test
    fun localSpeedCorrectionExpiresOnNextWayId() {
        assertEquals(LocalSpeedCorrectionDecision.APPLY, LocalSpeedCorrectionPolicy.decide("17721265", "17721265"))
        assertEquals(LocalSpeedCorrectionDecision.KEEP_WAITING, LocalSpeedCorrectionPolicy.decide("17721265", null))
        assertEquals(LocalSpeedCorrectionDecision.EXPIRE, LocalSpeedCorrectionPolicy.decide("17721265", "17721266"))
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
                    "ausserorts": { "geldbusse_eur": 200, "punkte": 1, "fahrverbot_monate": 1 }
                  }
                }
              ]
            }
        """.trimIndent()

        val rules = PenaltyRulesParser.parse(raw)
        val innerNotice = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh = 36, rules = rules, insideCity = true)
        val outerNotice = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh = 36, rules = rules, insideCity = false)

        assertEquals("DEU", rules.countryCode)
        assertEquals(1, rules.bands.size)
        assertNotNull(innerNotice)
        assertNotNull(outerNotice)
        assertEquals(260, innerNotice?.moneyFineEUR)
        assertEquals(2, innerNotice?.penaltyPoints)
        assertEquals(1, innerNotice?.drivingBanMonths)
        assertEquals(200, outerNotice?.moneyFineEUR)
        assertEquals(1, outerNotice?.penaltyPoints)
        assertEquals(1, outerNotice?.drivingBanMonths)
        assertNull(outerNotice?.conditionalDrivingBanMonths)
    }

    @Test
    fun mainScreenLogicPrefersDrivingBanPresentationForHighGermanOverspeed() = withLocale(Locale.GERMANY) {
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
            lastLookupCitySource = "settlement:zone_traffic:high",
        )

        assertEquals(36, ConsumerMainScreenLogic.currentOverspeedKmh(state))
        assertEquals("1", ConsumerMainScreenLogic.primaryMetricText(state))
        assertEquals("Monat Fahrverbot", ConsumerMainScreenLogic.secondaryMetricText(state))
        assertTrue(ConsumerMainScreenLogic.isDrivingBanWarningActive(state))
    }

    @Test
    fun lowConfidenceSettlementDoesNotChooseAnUrbanOrRuralPenaltyVariant() {
        val rules = PenaltyRulesParser.parse("""
            {"format":"youspeed.penalty.rules","schema_version":1,"land_code":"DEU",
             "land_name":"Deutschland","waehrung_code":"EUR","stufen":[
             {"min_ueber_kmh":31,"max_ueber_kmh":40,"schweregrad":"punkte_und_geldbusse",
              "titel_vorlage":"Verstoss","detail_vorlage":"Unbekannter Ortskontext",
              "geldbusse_eur":200,"punkte":1,"ortsvarianten":{
                "innerorts":{"geldbusse_eur":260,"punkte":2},
                "ausserorts":{"geldbusse_eur":150,"punkte":1}}}]}
        """.trimIndent())
        val state = ConsumerUiState(currentSpeedKmh = 86.0, speedLimitKmh = 50,
            activePenaltyRules = ActivePenaltyRules("DEU-rules.json", rules),
            lastLookupInsideCity = false, lastLookupCitySource = "settlement:landuse:low")
        val unknown = ConsumerMainScreenLogic.currentPenaltyNotice(state.copy(lastLookupInsideCity = null))
        assertEquals(unknown, ConsumerMainScreenLogic.currentPenaltyNotice(state))
        assertEquals(200, unknown?.moneyFineEUR)
        assertEquals(150, ConsumerMainScreenLogic.currentPenaltyNotice(state.copy(lastLookupCitySource = "settlement:zone_traffic:high"))?.moneyFineEUR)
        assertEquals(260, ConsumerMainScreenLogic.currentPenaltyNotice(state.copy(lastLookupInsideCity = true,
            lastLookupCitySource = "settlement:zone_traffic:high"))?.moneyFineEUR)
        assertTrue(ConsumerMainScreenLogic.shouldHighlightCityBadge(state.copy(lastLookupInsideCity = true)))
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

    @Test
    fun mainScreenLogicMovesSearchSignalIntoSecondaryMetric() = withLocale(Locale.GERMANY) {
        val state = ConsumerUiState(
            startupDataState = StartupDataState.READY,
            activeDBPath = "/tmp/mock.sqlite",
            gpsSignalBars = 0,
        )

        assertEquals(" ", ConsumerMainScreenLogic.primaryMetricText(state))
        assertEquals("Suche Signal", ConsumerMainScreenLogic.secondaryMetricText(state))
    }

    @Test
    fun mainScreenLogicShowsCompactPlaceBadgeOutsideCityWhenStreetAndCityKnown() {
        val state = ConsumerUiState(
            startupDataState = StartupDataState.READY,
            activeDBPath = "/tmp/mock.sqlite",
            currentLatitude = 49.0180,
            currentLongitude = 8.3501,
            gpsSignalBars = 4,
            limitStreetName = "A 5",
            limitCityName = "Karlsruhe",
            limitWayId = "autobahn-unlimited-130-plus",
            lastLookupInsideCity = false,
        )

        assertTrue(ConsumerMainScreenLogic.shouldShowCityBadge(state))
        assertFalse(ConsumerMainScreenLogic.shouldHighlightCityBadge(state))
    }
}

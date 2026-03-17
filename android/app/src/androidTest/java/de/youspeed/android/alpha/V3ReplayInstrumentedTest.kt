package de.youspeed.android.alpha

import android.content.res.AssetManager
import android.database.sqlite.SQLiteDatabase
import android.util.Log
import android.util.Xml
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.BufferedInputStream
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.zip.InflaterInputStream
import kotlin.math.ceil
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.xmlpull.v1.XmlPullParser

@RunWith(AndroidJUnit4::class)
class V3ReplayInstrumentedTest {
    @Test
    fun replayTrackFromGpxFixture_matchesExpectedWayAndSpeed() {
        val track = parseGpxTrackAsset("replay_track.gpx")
        val expected = loadReplayExpectations("replay_expected.json")
        runReplayAssertion(track = track, expected = expected, radiusM = 120.0)
    }

    @Test
    fun replayTrackFromKmlFixture_matchesExpectedWayAndSpeed() {
        val track = parseKmlTrackAsset("replay_track.kml")
        val expected = loadReplayExpectations("replay_expected.json")
        runReplayAssertion(track = track, expected = expected, radiusM = 120.0)
    }

    @Test
    fun benchmarkEndToEndLookupLatency_usingBundledDBAndReplayTrack() {
        val dbFile = resolveBundledSeedDbFile()
        val track = parseGpxTrackAsset("replay_track.gpx")
        assertTrue("Replay track fixture must contain at least one point", track.isNotEmpty())

        val e2eMs = ArrayList<Double>(track.size * 20)
        val serviceMs = ArrayList<Double>(track.size * 20)
        var projectedPayloadBytes = 0

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            // Warmup pass to stabilize caches and first-open effects.
            track.forEach { point ->
                lookup.lookup(
                    lat = point.lat,
                    lon = point.lon,
                    radiusM = 120.0,
                    maxCandidates = 64,
                    headingDeg = null,
                )
            }

            repeat(20) {
                track.forEach { point ->
                    val startedAtNs = System.nanoTime()
                    val result = lookup.lookup(
                        lat = point.lat,
                        lon = point.lon,
                        radiusM = 120.0,
                        maxCandidates = 64,
                        headingDeg = null,
                    )

                    // Include app-facing projection so this approximates fix->UI payload cost.
                    val speedText = result.speedLimitKmh?.toString() ?: "nil"
                    val wayText = result.wayId ?: "nil"
                    val streetText = result.streetName ?: "nil"
                    val cityText = result.cityName ?: "nil"
                    val insideCityText = result.insideCity?.let { if (it) "1" else "0" } ?: "nil"
                    projectedPayloadBytes += "$speedText|$wayText|$streetText|$cityText|$insideCityText".length

                    val elapsedMs = (System.nanoTime() - startedAtNs) / 1_000_000.0
                    e2eMs += elapsedMs
                    serviceMs += result.queryTimeMs
                }
            }
        }

        val e2eMedian = percentile(e2eMs, 0.50)
        val e2eP95 = percentile(e2eMs, 0.95)
        val serviceMedian = percentile(serviceMs, 0.50)
        val serviceP95 = percentile(serviceMs, 0.95)

        val benchmarkLine = String.format(
            "ANDROID_APP_E2E_BENCH n=%d e2e_ms_median=%.3f e2e_ms_p95=%.3f service_ms_median=%.3f service_ms_p95=%.3f payload_bytes=%d",
            e2eMs.size,
            e2eMedian,
            e2eP95,
            serviceMedian,
            serviceP95,
            projectedPayloadBytes,
        )
        println(benchmarkLine)
        Log.i(LOG_TAG, benchmarkLine)

        assertTrue("Expected positive median end-to-end latency", e2eMedian > 0.0)
        assertTrue("Expected projected payload work to run", projectedPayloadBytes > 0)
    }

    @Test
    fun bundledReplayWindowSettlesOnFutureStableWay() {
        val dbFile = resolveReplayDbFile()
        val requiredWayIds = setOf("1037006038", "16634524", "209270485")
        val presentWayIds = readPresentWayIds(dbFile, requiredWayIds)
        assumeTrue("Bundled seed DB does not contain required three-way regression ways", presentWayIds.containsAll(requiredWayIds))

        val entries = loadReplayWindow("replay_three_way_gate_window.json")
        val target = entries.first { it.fixId == 38 }
        val tracker = warmMatchTracker(entries.filter { it.fixId < target.fixId })

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = target.lat,
                lon = target.lon,
                radiusM = 50.0,
                maxCandidates = 64,
                headingDeg = target.courseDeg.takeIf { it >= 0.0 },
                speedKmh = target.speedKmh,
                horizontalAccuracyM = target.horizontalAccM,
                gpsSignalBars = target.gpsSignalBars,
                matchContext = tracker.snapshotOrNull(),
            )

            assertEquals("16634524", result.wayId)
        }
    }

    @Test
    fun bundledReplayWindowRejectsDisconnectedLoffenauHop() {
        val dbFile = resolveReplayDbFile()
        val requiredWayIds = setOf("16654539", "206811642", "723188219")
        val presentWayIds = readPresentWayIds(dbFile, requiredWayIds)
        assumeTrue("Bundled seed DB does not contain required Loffenau regression ways", presentWayIds.containsAll(requiredWayIds))

        val entries = loadReplayWindow("replay_loffenau_window.json")
        val target = entries.first { it.fixId == 2497 }
        assertEquals("16654539", target.result?.wayId)

        val tracker = warmMatchTracker(entries.filter { it.fixId < target.fixId })
        val warmedContext = tracker.snapshotOrNull()
        assumeTrue("Replay warmup should build matcher continuity state", warmedContext?.matchedFixCount ?: 0 >= 3)

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = target.lat,
                lon = target.lon,
                radiusM = 50.0,
                maxCandidates = 64,
                headingDeg = target.courseDeg.takeIf { it >= 0.0 },
                speedKmh = target.speedKmh,
                horizontalAccuracyM = target.horizontalAccM,
                gpsSignalBars = target.gpsSignalBars,
                matchContext = warmedContext,
            )

            assertNotEquals("16654539", result.wayId)
            assertTrue(setOf("206811642", "723188219").contains(result.wayId))
        }
    }

    @Test
    fun bundledLookupUsesAdminPolygonAtLoffenauRegressionFix() {
        val dbFile = resolveReplayDbFile()
        val target = loadReplayWindow("replay_loffenau_window.json").first { it.fixId == 2497 }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = target.lat,
                lon = target.lon,
                radiusM = 50.0,
                maxCandidates = 64,
                headingDeg = null,
            )

            assertEquals("Gernsbach (Landkreis Rastatt)", result.cityName)
            assertEquals("Gernsbach", result.cityPlaceName)
            assertEquals("Landkreis Rastatt", result.cityDistrictName)
            assertEquals(true, result.insideCity)
            assertEquals("admin_polygon", result.citySource)
        }
    }

    @Test
    fun bundledLookupResolvesLoffenauViaAdminPolygon() {
        val dbFile = resolveReplayDbFile()

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.7739967,
                lon = 8.3807646,
                radiusM = 50.0,
                maxCandidates = 64,
                headingDeg = null,
            )

            assertEquals("Loffenau (Landkreis Rastatt)", result.cityName)
            assertEquals("Loffenau", result.cityPlaceName)
            assertEquals("Landkreis Rastatt", result.cityDistrictName)
            assertEquals(true, result.insideCity)
            assertEquals("admin_polygon", result.citySource)
        }
    }

    @Test
    fun replayFieldLogs_reportAggregateHindsightAndTunnelMetrics() {
        val dbFile = resolveReplayDbFile()
        val traceDir = resolveReplayTraceDir()
        val manifest = loadReplayTraceManifest(traceDir)
        assumeTrue("Replay trace bundle missing top-level field logs", manifest.fieldLogs.isNotEmpty())

        val focusWayId = "313127285"
        val aggregate = ReplayPseudoLabelMetrics()
        var replayedFixCount = 0
        var portalEligibleTunnelFixCount = 0
        var selectedTunnelFixCount = 0
        var motorwayFixCount = 0
        var motorwayLinkFixCount = 0
        var focusReplayCandidateFixCount = 0
        var focusReplaySelectedFixCount = 0
        var focusLoggedCandidateFixCount = 0
        var focusLoggedSelectedFixCount = 0
        val perLogSummaries = mutableListOf<String>()

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            manifest.fieldLogs.forEach { descriptor ->
                val entries = loadReplayTraceEntries(traceDir, descriptor.file).sortedWith(compareBy<ReplayDriveLogEntry> { it.fixId }.thenBy { it.timestampUtc })
                assumeTrue("Expected non-empty replay field log ${descriptor.name}", entries.isNotEmpty())

                val tracker = WayMatchSessionTracker()
                val logMetrics = ReplayPseudoLabelMetrics()
                var logReplayedFixCount = 0
                var logPortalEligibleTunnelFixCount = 0
                var logSelectedTunnelFixCount = 0
                var logMotorwayFixCount = 0
                var logMotorwayLinkFixCount = 0
                var logFocusReplayCandidateFixCount = 0
                var logFocusReplaySelectedFixCount = 0
                var logFocusLoggedCandidateFixCount = 0
                var logFocusLoggedSelectedFixCount = 0

                entries.forEachIndexed { index, entry ->
                    val loggedResult = entry.result
                    if (loggedResult?.candidateWayIds?.contains(focusWayId) == true) {
                        focusLoggedCandidateFixCount += 1
                        logFocusLoggedCandidateFixCount += 1
                    }
                    if (loggedResult?.wayId == focusWayId) {
                        focusLoggedSelectedFixCount += 1
                        logFocusLoggedSelectedFixCount += 1
                    }

                    val result = lookup.lookup(
                        lat = entry.lat,
                        lon = entry.lon,
                        radiusM = 50.0,
                        maxCandidates = 64,
                        headingDeg = entry.courseDeg.takeIf { it >= 0.0 },
                        speedKmh = entry.speedKmh,
                        horizontalAccuracyM = entry.horizontalAccM,
                        gpsSignalBars = entry.gpsSignalBars,
                        matchContext = tracker.snapshotOrNull(),
                    )

                    replayedFixCount += 1
                    logReplayedFixCount += 1
                    logMetrics.replayedFixCount += 1
                    if (result.candidateTraces.any { it.wayId == focusWayId }) {
                        focusReplayCandidateFixCount += 1
                        logFocusReplayCandidateFixCount += 1
                    }
                    if (result.wayId == focusWayId) {
                        focusReplaySelectedFixCount += 1
                        logFocusReplaySelectedFixCount += 1
                    }
                    if (hasPortalEligibleTunnelCandidate(result)) {
                        portalEligibleTunnelFixCount += 1
                        logPortalEligibleTunnelFixCount += 1
                    }
                    if (result.isTunnelSegment) {
                        selectedTunnelFixCount += 1
                        logSelectedTunnelFixCount += 1
                    }
                    when (result.highway) {
                        "motorway" -> {
                            motorwayFixCount += 1
                            logMotorwayFixCount += 1
                        }

                        "motorway_link" -> {
                            motorwayLinkFixCount += 1
                            logMotorwayLinkFixCount += 1
                        }
                    }

                    hindsightPseudoLabelWayId(
                        entries = entries,
                        index = index,
                        futureWindow = 5,
                        minFutureRunLength = 5,
                        minAgreementRatio = 0.8,
                    )?.let { pseudoLabelWayId ->
                        val isChangedExample = loggedResult?.wayId != pseudoLabelWayId
                        val predictedMatches = result.wayId == pseudoLabelWayId
                        logMetrics.recordPseudoLabelExample(predictedMatches = predictedMatches, isChangedExample = isChangedExample)
                    }

                    tracker.record(
                        result = result,
                        lat = entry.lat,
                        lon = entry.lon,
                        horizontalAccuracyM = entry.horizontalAccM,
                        gpsSignalBars = entry.gpsSignalBars,
                    )
                }

                aggregate.formUnion(logMetrics)
                perLogSummaries += buildString {
                    append(descriptor.name)
                    append(" replayed=").append(logReplayedFixCount)
                    append(" hindsight=").append(formatRatio(logMetrics.accuracy))
                    append(" changedRecall=").append(formatRatio(logMetrics.changedRecall))
                    append(" unchangedAcc=").append(formatRatio(logMetrics.unchangedAccuracy))
                    append(" portalTunnel=").append(logPortalEligibleTunnelFixCount)
                    append(" selectedTunnel=").append(logSelectedTunnelFixCount)
                    append(" motorway=").append(logMotorwayFixCount)
                    append(" motorwayLink=").append(logMotorwayLinkFixCount)
                    append(" focusReplayCand=").append(logFocusReplayCandidateFixCount)
                    append(" focusReplaySel=").append(logFocusReplaySelectedFixCount)
                    append(" focusLoggedCand=").append(logFocusLoggedCandidateFixCount)
                    append(" focusLoggedSel=").append(logFocusLoggedSelectedFixCount)
                }
            }
        }

        println(
            "FIELD_REPLAY_ANDROID"
                + " replayed=$replayedFixCount"
                + " pseudo=${aggregate.pseudoLabelExampleCount}"
                + " acc=${formatRatio(aggregate.accuracy)}"
                + " changedRecall=${formatRatio(aggregate.changedRecall)}"
                + " unchangedAcc=${formatRatio(aggregate.unchangedAccuracy)}"
                + " portalTunnel=$portalEligibleTunnelFixCount"
                + " selectedTunnel=$selectedTunnelFixCount"
                + " motorway=$motorwayFixCount"
                + " motorwayLink=$motorwayLinkFixCount"
        )
        println(
            "FIELD_REPLAY_ANDROID_WAY $focusWayId"
                + " replayCandidate=$focusReplayCandidateFixCount"
                + " replaySelected=$focusReplaySelectedFixCount"
                + " loggedCandidate=$focusLoggedCandidateFixCount"
                + " loggedSelected=$focusLoggedSelectedFixCount"
        )
        println("FIELD_REPLAY_ANDROID_LOGS ${perLogSummaries.joinToString(" | ")}")

        assertTrue("Expected non-empty replay bundle coverage", replayedFixCount > 0)
        assertTrue("Expected hindsight pseudo-label coverage across field logs", aggregate.pseudoLabelExampleCount > 0)
        assertTrue("Expected tunnel-portal or tunnel selection evidence in field logs", portalEligibleTunnelFixCount + selectedTunnelFixCount > 0)
    }

    @Test
    fun replayGeomLogs_reportAgreementAndOscillationDiagnostics() {
        val dbFile = resolveReplayDbFile()
        val traceDir = resolveReplayTraceDir()
        val manifest = loadReplayTraceManifest(traceDir)
        assumeTrue("Replay trace bundle missing geom logs", manifest.geomLogs.isNotEmpty())

        val aggregate = ReplayPseudoLabelMetrics()
        var aggregateLoggedComparable = 0
        var aggregateLoggedAgreement = 0
        var aggregateReplayTunnelFixCount = 0
        var aggregateLoggedTunnelFixCount = 0
        var aggregateReplayPortalEligibleTunnelFixCount = 0
        var aggregateLoggedPortalEligibleTunnelFixCount = 0
        var aggregateReplayWayOscillationCount = 0
        var aggregateLoggedWayOscillationCount = 0
        var aggregateReplaySameRefOscillationCount = 0
        var aggregateLoggedSameRefOscillationCount = 0
        val perLogSummaries = mutableListOf<String>()

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            manifest.geomLogs.forEach { descriptor ->
                val entries = loadReplayTraceEntries(traceDir, descriptor.file).sortedWith(compareBy<ReplayDriveLogEntry> { it.fixId }.thenBy { it.timestampUtc })
                assumeTrue("Expected non-empty geom replay log ${descriptor.name}", entries.isNotEmpty())

                val tracker = WayMatchSessionTracker()
                val logMetrics = ReplayPseudoLabelMetrics()
                val loggedWayIds = mutableListOf<String?>()
                val replayWayIds = mutableListOf<String?>()
                val loggedRefs = mutableListOf<String?>()
                val replayRefs = mutableListOf<String?>()
                var logLoggedComparable = 0
                var logLoggedAgreement = 0
                var logReplayTunnelFixCount = 0
                var logLoggedTunnelFixCount = 0
                var logReplayPortalEligibleTunnelFixCount = 0
                var logLoggedPortalEligibleTunnelFixCount = 0
                val mismatchSamples = mutableListOf<String>()
                val tunnelFailureRanges = mutableListOf<String>()
                val replayTunnelSamples = mutableListOf<String>()
                var currentTunnelFailureStartFixId: Int? = null
                var currentTunnelFailureLength = 0
                var currentTunnelFailureRecovered = false

                fun finishTunnelFailureRangeIfNeeded(endFixId: Int) {
                    val startFixId = currentTunnelFailureStartFixId
                    if (startFixId != null &&
                        currentTunnelFailureLength >= 3 &&
                        !currentTunnelFailureRecovered &&
                        tunnelFailureRanges.size < 4
                    ) {
                        tunnelFailureRanges += "$startFixId-$endFixId"
                    }
                    currentTunnelFailureStartFixId = null
                    currentTunnelFailureLength = 0
                    currentTunnelFailureRecovered = false
                }

                entries.forEachIndexed { index, entry ->
                    val result = lookup.lookup(
                        lat = entry.lat,
                        lon = entry.lon,
                        radiusM = 50.0,
                        maxCandidates = 64,
                        headingDeg = entry.courseDeg.takeIf { it >= 0.0 },
                        speedKmh = entry.speedKmh,
                        horizontalAccuracyM = entry.horizontalAccM,
                        gpsSignalBars = entry.gpsSignalBars,
                        matchContext = tracker.snapshotOrNull(),
                    )

                    logMetrics.replayedFixCount += 1
                    hindsightPseudoLabelWayId(
                        entries = entries,
                        index = index,
                        futureWindow = 5,
                        minFutureRunLength = 5,
                        minAgreementRatio = 0.8,
                    )?.let { pseudoLabelWayId ->
                        val predictedMatches = result.wayId == pseudoLabelWayId
                        val isChangedExample = entry.result?.wayId != pseudoLabelWayId
                        logMetrics.recordPseudoLabelExample(predictedMatches = predictedMatches, isChangedExample = isChangedExample)
                    }

                    val loggedWayId = entry.result?.wayId
                    loggedWayIds += loggedWayId
                    replayWayIds += result.wayId
                    loggedRefs += entry.result?.streetRef
                    replayRefs += result.streetRef

                    if (loggedWayId != null) {
                        logLoggedComparable += 1
                        if (loggedWayId == result.wayId) {
                            logLoggedAgreement += 1
                        } else if (mismatchSamples.size < 6) {
                            mismatchSamples += "fix ${entry.fixId} $loggedWayId->${result.wayId ?: "nil"} ref ${entry.result.streetRef ?: "-"}->${result.streetRef ?: "-"}"
                        }
                    }

                    if (entry.result?.isTunnelSegment == true) {
                        logLoggedTunnelFixCount += 1
                    }
                    if (hasPortalEligibleTunnelCandidate(entry.result)) {
                        logLoggedPortalEligibleTunnelFixCount += 1
                    }
                    if (hasPortalEligibleTunnelCandidate(result)) {
                        logReplayPortalEligibleTunnelFixCount += 1
                        if (currentTunnelFailureStartFixId == null) {
                            currentTunnelFailureStartFixId = entry.fixId
                        }
                        currentTunnelFailureLength += 1
                    } else {
                        finishTunnelFailureRangeIfNeeded(entries[maxOf(index - 1, 0)].fixId)
                    }
                    if (result.isTunnelSegment) {
                        logReplayTunnelFixCount += 1
                        currentTunnelFailureRecovered = true
                        if (replayTunnelSamples.size < 6) {
                            replayTunnelSamples += "fix ${entry.fixId} way ${result.wayId ?: "nil"} logged=${entry.result?.wayId ?: "nil"} portal=${hasPortalEligibleTunnelCandidate(result)}"
                        }
                    }

                    tracker.record(
                        result = result,
                        lat = entry.lat,
                        lon = entry.lon,
                        horizontalAccuracyM = entry.horizontalAccM,
                        gpsSignalBars = entry.gpsSignalBars,
                    )
                }
                entries.lastOrNull()?.let { finishTunnelFailureRangeIfNeeded(it.fixId) }

                val replayWayOscillationCount = countABAOscillations(replayWayIds)
                val loggedWayOscillationCount = countABAOscillations(loggedWayIds)
                val replaySameRefOscillationCount = countSameRefABAOscillations(replayWayIds, replayRefs)
                val loggedSameRefOscillationCount = countSameRefABAOscillations(loggedWayIds, loggedRefs)
                val loggedAgreementRatio = safeRatio(logLoggedAgreement, logLoggedComparable)

                aggregate.formUnion(logMetrics)
                aggregateLoggedComparable += logLoggedComparable
                aggregateLoggedAgreement += logLoggedAgreement
                aggregateReplayTunnelFixCount += logReplayTunnelFixCount
                aggregateLoggedTunnelFixCount += logLoggedTunnelFixCount
                aggregateReplayPortalEligibleTunnelFixCount += logReplayPortalEligibleTunnelFixCount
                aggregateLoggedPortalEligibleTunnelFixCount += logLoggedPortalEligibleTunnelFixCount
                aggregateReplayWayOscillationCount += replayWayOscillationCount
                aggregateLoggedWayOscillationCount += loggedWayOscillationCount
                aggregateReplaySameRefOscillationCount += replaySameRefOscillationCount
                aggregateLoggedSameRefOscillationCount += loggedSameRefOscillationCount

                perLogSummaries += buildString {
                    append(descriptor.name)
                    append(" fixes=").append(entries.size)
                    append(" logAgree=").append(formatRatio(loggedAgreementRatio))
                    append(" hindsight=").append(formatRatio(logMetrics.accuracy))
                    append(" changedRecall=").append(formatRatio(logMetrics.changedRecall))
                    append(" unchangedAcc=").append(formatRatio(logMetrics.unchangedAccuracy))
                    append(" replayPortalTunnel=").append(logReplayPortalEligibleTunnelFixCount)
                    append(" loggedPortalTunnel=").append(logLoggedPortalEligibleTunnelFixCount)
                    append(" replayTunnel=").append(logReplayTunnelFixCount)
                    append(" loggedTunnel=").append(logLoggedTunnelFixCount)
                    append(" wayABA=").append(replayWayOscillationCount).append("/").append(loggedWayOscillationCount)
                    append(" sameRefABA=").append(replaySameRefOscillationCount).append("/").append(loggedSameRefOscillationCount)
                    append(" tunnelMiss=").append(tunnelFailureRanges.ifEmpty { listOf("none") }.joinToString(","))
                    append(" replayTunnelFixes=").append(replayTunnelSamples.ifEmpty { listOf("none") }.joinToString("; "))
                    append(" mismatches=").append(mismatchSamples.ifEmpty { listOf("none") }.joinToString("; "))
                }
            }
        }

        val aggregateLoggedAgreementRatio = safeRatio(aggregateLoggedAgreement, aggregateLoggedComparable)
        println(
            "GEOM_REPLAY_ANDROID"
                + " fixes=${aggregate.replayedFixCount}"
                + " logAgree=${formatRatio(aggregateLoggedAgreementRatio)}"
                + " hindsight=${formatRatio(aggregate.accuracy)}"
                + " changedRecall=${formatRatio(aggregate.changedRecall)}"
                + " unchangedAcc=${formatRatio(aggregate.unchangedAccuracy)}"
                + " replayPortalTunnel=$aggregateReplayPortalEligibleTunnelFixCount"
                + " loggedPortalTunnel=$aggregateLoggedPortalEligibleTunnelFixCount"
                + " replayTunnel=$aggregateReplayTunnelFixCount"
                + " loggedTunnel=$aggregateLoggedTunnelFixCount"
                + " wayABA=$aggregateReplayWayOscillationCount/$aggregateLoggedWayOscillationCount"
                + " sameRefABA=$aggregateReplaySameRefOscillationCount/$aggregateLoggedSameRefOscillationCount"
        )
        println("GEOM_REPLAY_ANDROID_LOGS ${perLogSummaries.joinToString(" | ")}")

        assertTrue("Expected geom replay coverage", aggregate.replayedFixCount > 0)
        assertTrue("Expected logged geom comparison coverage", aggregateLoggedComparable > 0)
        assertTrue("Expected hindsight pseudo-label coverage on geom logs", aggregate.pseudoLabelExampleCount > 0)
    }

    @Test
    fun replayWalkingLog_reportsLowSpeedContinuityDiagnostics() {
        val dbFile = resolveReplayDbFile()
        val traceDir = resolveReplayTraceDir()
        val manifest = loadReplayTraceManifest(traceDir)
        val walkingLog = manifest.walkingLog
        assumeTrue("Replay trace bundle missing walking log", walkingLog != null)

        val entries = loadReplayTraceEntries(traceDir, walkingLog!!.file).sortedWith(compareBy<ReplayDriveLogEntry> { it.fixId }.thenBy { it.timestampUtc })
        assumeTrue("Walking replay log should not be empty", entries.isNotEmpty())

        val lowSpeedThresholdKmh = 8.0
        val tracker = WayMatchSessionTracker()
        var logComparable = 0
        var logAgreement = 0
        var lowSpeedFixCount = 0
        var loggedStickyCount = 0
        var replayStickyCount = 0
        var loggedStrongStickyCount = 0
        var replayStrongStickyCount = 0
        val loggedContinuityCounter = linkedMapOf<String, Int>()
        val replayContinuityCounter = linkedMapOf<String, Int>()
        val samples = mutableListOf<String>()

        fun recordStickyEvent(
            label: String,
            speedKmh: Double,
            entry: ReplayDriveLogEntry,
            selected: MatcherCandidateTrace?,
            best: MatcherCandidateTrace?,
            counter: MutableMap<String, Int>,
            stickyCountIncrement: () -> Unit,
            strongStickyCountIncrement: () -> Unit,
        ) {
            if (selected == null || best == null || selected.wayId == best.wayId) {
                return
            }
            if (selected.continuityClass == "none") {
                return
            }
            stickyCountIncrement()
            counter[selected.continuityClass] = (counter[selected.continuityClass] ?: 0) + 1
            if (selected.distanceM >= best.distanceM + 10.0) {
                strongStickyCountIncrement()
            }
            if (samples.size < 8) {
                samples += buildString {
                    append(label)
                    append(" fix ").append(entry.fixId)
                    append(" speed=").append(formatRatio(speedKmh))
                    append(" selected=").append(selected.wayId ?: "nil").append("/").append(selected.continuityClass)
                    append(" dist=").append(formatRatio(selected.distanceM))
                    append(" raw=").append(formatRatio(selected.geometryScore ?: selected.distanceM))
                    append(" best=").append(best.wayId ?: "nil").append("/").append(best.continuityClass)
                    append(" bestDist=").append(formatRatio(best.distanceM))
                    append(" bestRaw=").append(formatRatio(best.geometryScore ?: best.distanceM))
                    append(" logged=").append(entry.result?.wayId ?: "nil")
                }
            }
        }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            entries.forEach { entry ->
                val result = lookup.lookup(
                    lat = entry.lat,
                    lon = entry.lon,
                    radiusM = 50.0,
                    maxCandidates = 64,
                    headingDeg = entry.courseDeg.takeIf { it >= 0.0 },
                    speedKmh = entry.speedKmh,
                    horizontalAccuracyM = entry.horizontalAccM,
                    gpsSignalBars = entry.gpsSignalBars,
                    matchContext = tracker.snapshotOrNull(),
                )

                if (entry.result?.wayId != null) {
                    logComparable += 1
                    if (entry.result.wayId == result.wayId) {
                        logAgreement += 1
                    }
                }

                if (entry.speedKmh <= lowSpeedThresholdKmh) {
                    lowSpeedFixCount += 1
                    val loggedSelected = entry.result?.candidateTraces?.firstOrNull { it.isSelected }?.toMatcherCandidateTrace()
                    val loggedBest = nearestTrace(entry.result?.candidateTraces.orEmpty().map { it.toMatcherCandidateTrace() })
                    recordStickyEvent(
                        label = "logged",
                        speedKmh = entry.speedKmh,
                        entry = entry,
                        selected = loggedSelected,
                        best = loggedBest,
                        counter = loggedContinuityCounter,
                        stickyCountIncrement = { loggedStickyCount += 1 },
                        strongStickyCountIncrement = { loggedStrongStickyCount += 1 },
                    )

                    val replaySelected = result.candidateTraces.firstOrNull { it.isSelected }
                    val replayBest = nearestTrace(result.candidateTraces)
                    recordStickyEvent(
                        label = "replay",
                        speedKmh = entry.speedKmh,
                        entry = entry,
                        selected = replaySelected,
                        best = replayBest,
                        counter = replayContinuityCounter,
                        stickyCountIncrement = { replayStickyCount += 1 },
                        strongStickyCountIncrement = { replayStrongStickyCount += 1 },
                    )
                }

                tracker.record(
                    result = result,
                    lat = entry.lat,
                    lon = entry.lon,
                    horizontalAccuracyM = entry.horizontalAccM,
                    gpsSignalBars = entry.gpsSignalBars,
                )
            }
        }

        println(
            "WALKING_REPLAY_ANDROID"
                + " fixes=${entries.size}"
                + " lowSpeedFixes=$lowSpeedFixCount"
                + " logAgree=${formatRatio(safeRatio(logAgreement, logComparable))}"
                + " loggedSticky=$loggedStickyCount"
                + " replaySticky=$replayStickyCount"
                + " loggedStrongSticky=$loggedStrongStickyCount"
                + " replayStrongSticky=$replayStrongStickyCount"
                + " loggedContinuity=${formatCounter(loggedContinuityCounter)}"
                + " replayContinuity=${formatCounter(replayContinuityCounter)}"
        )
        println("WALKING_REPLAY_ANDROID_SAMPLES ${samples.ifEmpty { listOf("none") }.joinToString(" | ")}")

        assertTrue("Expected walking replay coverage", entries.isNotEmpty())
        assertTrue("Expected low-speed walking replay examples", lowSpeedFixCount > 0)
    }

    private fun runReplayAssertion(
        track: List<TrackPoint>,
        expected: List<ReplayExpectation>,
        radiusM: Double,
    ) {
        assertEquals("Track and expected output count mismatch", track.size, expected.size)
        val dbFile = createReplayFixtureDb()
        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            track.indices.forEach { index ->
                val point = track[index]
                val expectedPoint = expected[index]
                val result = lookup.lookup(
                    lat = point.lat,
                    lon = point.lon,
                    radiusM = radiusM,
                    maxCandidates = 64,
                    headingDeg = null,
                )
                assertEquals("Unexpected way ID at replay index=$index", expectedPoint.expectedWayId, result.wayId)
                assertEquals("Unexpected speed at replay index=$index", expectedPoint.expectedSpeedKmh, result.speedLimitKmh)
            }
        }
    }

    private fun createReplayFixtureDb(): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.cacheDir, "replay-fixture-${UUID.randomUUID()}.sqlite")
        val db = SQLiteDatabase.openOrCreateDatabase(file, null)
        try {
            execSql(
                db,
                """
                CREATE TABLE ways (
                  way_id TEXT PRIMARY KEY,
                  highway TEXT,
                  street_name TEXT,
                  ref TEXT,
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  approx_heading_deg REAL,
                  service TEXT,
                  tunnel TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );
                CREATE TABLE ways_rtree (
                  way_id TEXT NOT NULL,
                  min_lon REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lat REAL NOT NULL
                );
                CREATE TABLE way_geom (
                  way_id TEXT PRIMARY KEY,
                  points_json TEXT NOT NULL
                );

                INSERT INTO ways VALUES ('100', 'residential', 'Fixture Main Street', NULL, '30', NULL, NULL, 90.0, 'main', NULL, 13.4050, 52.5200, 13.4060, 52.5210);
                INSERT INTO ways_rtree VALUES ('100', 13.4050, 13.4060, 52.5200, 52.5210);
                INSERT INTO way_geom VALUES ('100', '[[52.5200,13.4050],[52.5210,13.4060]]');

                INSERT INTO ways VALUES ('200', 'residential', 'Fixture Side Street', NULL, '50', NULL, NULL, 45.0, 'main', NULL, 13.4072, 52.5218, 13.4080, 52.5222);
                INSERT INTO ways_rtree VALUES ('200', 13.4072, 13.4080, 52.5218, 52.5222);
                INSERT INTO way_geom VALUES ('200', '[[52.5218,13.4072],[52.5222,13.4080]]');
                """.trimIndent(),
            )
        } finally {
            db.close()
        }
        return file
    }

    private fun resolveReplayDbFile(): File {
        val targetContext = InstrumentationRegistry.getInstrumentation().targetContext
        val arguments = InstrumentationRegistry.getArguments()
        val explicitPath = arguments.getString("replay_db_path")?.trim().orEmpty()
        val candidate = if (explicitPath.isNotEmpty()) {
            File(explicitPath)
        } else {
            File(targetContext.filesDir, "replay/replay_regressions.sqlite")
        }
        assumeTrue(
            "Replay regression DB missing. Generate and push app-internal replay/replay_regressions.sqlite first.",
            candidate.exists() && candidate.isFile,
        )
        return candidate
    }

    private fun resolveBundledSeedDbFile(): File {
        val targetContext = InstrumentationRegistry.getInstrumentation().targetContext
        val seedDir = File(targetContext.filesDir, "benchmark")
        if (!seedDir.exists()) {
            seedDir.mkdirs()
        }
        val seedFile = File(seedDir, BUNDLED_SEED_DB_FILE_NAME)
        val tempFile = File(seedDir, "$BUNDLED_SEED_DB_FILE_NAME.tmp")
        tempFile.delete()
        targetContext.assets.open(BUNDLED_SEED_ASSET_NAME).use { input ->
            InflaterInputStream(BufferedInputStream(input)).use { inflater ->
                FileOutputStream(tempFile).use { output ->
                    inflater.copyTo(output)
                }
            }
        }
        seedFile.delete()
        check(tempFile.renameTo(seedFile)) { "Failed to atomically place bundled benchmark DB" }
        assumeTrue(
            "Bundled benchmark DB missing after asset inflate",
            seedFile.exists() && seedFile.isFile && seedFile.length() > 0L,
        )
        return seedFile
    }

    private fun resolveReplayTraceDir(): File {
        val targetContext = InstrumentationRegistry.getInstrumentation().targetContext
        val arguments = InstrumentationRegistry.getArguments()
        val explicitPath = arguments.getString("replay_trace_dir")?.trim().orEmpty()
        val candidate = if (explicitPath.isNotEmpty()) {
            File(explicitPath)
        } else {
            File(targetContext.filesDir, "replay/traces")
        }
        assumeTrue(
            "Replay trace bundle missing. Generate and push app-internal replay/traces first.",
            candidate.exists() && candidate.isDirectory,
        )
        return candidate
    }

    private fun readPresentWayIds(
        dbFile: File,
        wayIds: Set<String>,
    ): Set<String> {
        if (!dbFile.exists()) {
            return emptySet()
        }
        val db = SQLiteDatabase.openDatabase(dbFile.absolutePath, null, SQLiteDatabase.OPEN_READONLY)
        try {
            if (wayIds.isEmpty()) {
                return emptySet()
            }
            val placeholders = wayIds.joinToString(",") { "?" }
            val sql = "SELECT way_id FROM ways WHERE way_id IN ($placeholders)"
            return db.rawQuery(sql, wayIds.toTypedArray()).use { cursor ->
                buildSet {
                    while (cursor.moveToNext()) {
                        cursor.getString(0)?.trim()?.takeIf { it.isNotEmpty() }?.let(::add)
                    }
                }
            }
        } finally {
            db.close()
        }
    }

    private fun warmMatchTracker(entries: List<ReplayDriveLogEntry>): WayMatchSessionTracker {
        val tracker = WayMatchSessionTracker()
        entries.forEach { entry ->
            val snapshot = entry.result ?: return@forEach
            tracker.record(
                result = snapshot.toSpeedLookupResult(),
                lat = entry.lat,
                lon = entry.lon,
                horizontalAccuracyM = entry.horizontalAccM,
                gpsSignalBars = entry.gpsSignalBars,
            )
        }
        return tracker
    }

    private fun ReplayLogResult.toSpeedLookupResult(): SpeedLookupResult {
        val portalEligibleWayIds = candidateTraces.mapNotNullTo(linkedSetOf()) { trace ->
            trace.wayId?.takeIf { trace.portalEligible }
        }
        val portalEligibleRefs = candidateTraces.flatMapTo(linkedSetOf()) { trace ->
            if (trace.portalEligible) normalizedRefTokens(trace.streetRef) else emptyList()
        }
        return SpeedLookupResult(
            wayId = wayId,
            highway = highway,
            streetName = null,
            streetBaseName = null,
            streetRef = streetRef,
            speedLimitKmh = null,
            isUnlimitedSpeedLimit = false,
            cityName = null,
            cityPlaceName = null,
            cityDistrictName = null,
            insideCity = null,
            citySource = null,
            queryTimeMs = 0.0,
            candidateCount = candidateTraces.size,
            speedCandidateCount = 0,
            candidateTraces = candidateTraces.map { it.toMatcherCandidateTrace() },
            nearestCandidateDistanceM = candidateTraces.mapNotNull { it.distanceM }.minOrNull()?.takeIf { it.isFinite() },
            nearestSpeedCandidateDistanceM = null,
            isTunnelSegment = isTunnelSegment,
            matchedEndpointProximityM = matchedEndpointProximityM,
            streetRefTokens = normalizedRefTokens(streetRef),
            nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds.toSet(),
            nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs.toSet(),
            portalEligibleTunnelWayIds = portalEligibleWayIds,
            portalEligibleTunnelRefs = portalEligibleRefs,
            activeCorridorState = null,
            approachCorridorStateCandidate = null,
            usedWalkingTurnSwitch = false,
            usedMiniHMM = false,
            miniHMMCandidateCount = 0,
            matchHypotheses = emptyList(),
            selectionTrace = emptyList(),
        )
    }

    private fun ReplayLogCandidateTrace.toMatcherCandidateTrace(): MatcherCandidateTrace {
        return MatcherCandidateTrace(
            rank = rank,
            wayId = wayId,
            score = score ?: Double.POSITIVE_INFINITY,
            distanceM = distanceM ?: Double.POSITIVE_INFINITY,
            geometryScore = geometryScore,
            endpointProximityM = endpointProximityM ?: Double.POSITIVE_INFINITY,
            continuityClass = continuityClass ?: "none",
            highway = highway,
            service = service,
            streetName = streetName,
            streetRef = streetRef,
            tunnel = tunnel,
            tunnelSelectable = tunnelSelectable,
            corridorSelectable = corridorSelectable,
            portalEligible = portalEligible,
            isSelected = isSelected,
        )
    }

    private fun parseGpxTrackAsset(name: String): List<TrackPoint> {
        val parser = Xml.newPullParser()
        instrumentationAssets().open(name).use { input ->
            parser.setInput(input, "UTF-8")
            val out = mutableListOf<TrackPoint>()
            var eventType = parser.eventType
            while (eventType != XmlPullParser.END_DOCUMENT) {
                if (eventType == XmlPullParser.START_TAG && parser.name == "trkpt") {
                    val lat = parser.getAttributeValue(null, "lat")?.toDoubleOrNull()
                    val lon = parser.getAttributeValue(null, "lon")?.toDoubleOrNull()
                    if (lat != null && lon != null) {
                        out += TrackPoint(lat = lat, lon = lon)
                    }
                }
                eventType = parser.next()
            }
            return out
        }
    }

    private fun parseKmlTrackAsset(name: String): List<TrackPoint> {
        val parser = Xml.newPullParser()
        instrumentationAssets().open(name).use { input ->
            parser.setInput(input, "UTF-8")
            var eventType = parser.eventType
            while (eventType != XmlPullParser.END_DOCUMENT) {
                if (eventType == XmlPullParser.START_TAG && parser.name == "coordinates") {
                    val coordinates = parser.nextText()
                    return coordinates
                        .trim()
                        .split(Regex("\\s+"))
                        .mapNotNull { raw ->
                            val parts = raw.split(",")
                            val lon = parts.getOrNull(0)?.trim()?.toDoubleOrNull()
                            val lat = parts.getOrNull(1)?.trim()?.toDoubleOrNull()
                            if (lat != null && lon != null) TrackPoint(lat = lat, lon = lon) else null
                        }
                }
                eventType = parser.next()
            }
        }
        return emptyList()
    }

    private fun loadReplayExpectations(name: String): List<ReplayExpectation> {
        val content = instrumentationAssets().open(name).bufferedReader().use { it.readText() }
        val payload = JSONArray(content)
        return buildList(payload.length()) {
            for (index in 0 until payload.length()) {
                val obj = payload.getJSONObject(index)
                add(
                    ReplayExpectation(
                        expectedWayId = obj.takeUnless { it.isNull("expected_way_id") }?.optString("expected_way_id")?.ifBlank { null },
                        expectedSpeedKmh = if (obj.isNull("expected_speed_kmh")) null else obj.getInt("expected_speed_kmh"),
                    ),
                )
            }
        }
    }

    private fun loadReplayWindow(name: String): List<ReplayDriveLogEntry> {
        val content = instrumentationAssets().open(name).bufferedReader().use { it.readText() }
        val payload = JSONArray(content)
        return buildList(payload.length()) {
            for (index in 0 until payload.length()) {
                add(decodeReplayDriveLogEntry(payload.getJSONObject(index)))
            }
        }
    }

    private fun loadReplayTraceManifest(traceDir: File): ReplayTraceManifest {
        val payload = JSONObject(File(traceDir, "manifest.json").readText())
        return ReplayTraceManifest(
            fieldLogs = decodeReplayTraceDescriptors(payload.optJSONArray("field_logs")),
            geomLogs = decodeReplayTraceDescriptors(payload.optJSONArray("geom_logs")),
            walkingLog = payload.optJSONObject("walking_log")?.let(::decodeReplayTraceDescriptor),
        )
    }

    private fun decodeReplayTraceDescriptors(array: JSONArray?): List<ReplayTraceDescriptor> {
        if (array == null) {
            return emptyList()
        }
        return buildList(array.length()) {
            for (index in 0 until array.length()) {
                add(decodeReplayTraceDescriptor(array.getJSONObject(index)))
            }
        }
    }

    private fun decodeReplayTraceDescriptor(obj: JSONObject): ReplayTraceDescriptor {
        return ReplayTraceDescriptor(
            name = obj.getString("name"),
            file = obj.getString("file"),
            entryCount = obj.getInt("entry_count"),
        )
    }

    private fun loadReplayTraceEntries(
        traceDir: File,
        fileName: String,
    ): List<ReplayDriveLogEntry> {
        val file = File(traceDir, fileName)
        assumeTrue("Missing replay trace file $fileName under ${traceDir.absolutePath}", file.exists() && file.isFile)
        return buildList {
            file.bufferedReader().useLines { lines ->
                lines.filter { it.isNotBlank() }.forEach { raw ->
                    add(decodeReplayDriveLogEntry(JSONObject(raw)))
                }
            }
        }
    }

    private fun decodeReplayDriveLogEntry(obj: JSONObject): ReplayDriveLogEntry {
        return ReplayDriveLogEntry(
            fixId = obj.getInt("fix_id"),
            timestampUtc = obj.getString("timestamp_utc"),
            lat = obj.getDouble("lat"),
            lon = obj.getDouble("lon"),
            speedKmh = obj.getDouble("speed_kmh"),
            horizontalAccM = obj.getDouble("horizontal_acc_m"),
            courseDeg = obj.optDouble("course_deg", -1.0),
            gpsSignalBars = obj.optInt("gps_signal_bars", 0),
            status = obj.optString("status", "matched"),
            result = obj.optJSONObject("result")?.let(::decodeReplayLogResult),
        )
    }

    private fun decodeReplayLogResult(obj: JSONObject): ReplayLogResult {
        return ReplayLogResult(
            wayId = obj.takeUnless { it.isNull("way_id") }?.optString("way_id")?.ifBlank { null },
            highway = obj.takeUnless { it.isNull("highway") }?.optString("highway")?.ifBlank { null },
            streetRef = obj.takeUnless { it.isNull("street_ref") }?.optString("street_ref")?.ifBlank { null },
            isTunnelSegment = obj.optBoolean("is_tunnel_segment", false),
            nearbyTunnelCandidateWayIds = obj.optJSONArray("nearby_tunnel_candidate_way_ids").toStringList(),
            nearbyTunnelCandidateRefs = obj.optJSONArray("nearby_tunnel_candidate_refs").toStringList(),
            matchedEndpointProximityM = obj.takeUnless { it.isNull("matched_endpoint_proximity_m") }?.optDouble("matched_endpoint_proximity_m"),
            candidateTraces = decodeReplayLogCandidateTraces(obj.optJSONArray("candidate_traces")),
        )
    }

    private fun decodeReplayLogCandidateTraces(array: JSONArray?): List<ReplayLogCandidateTrace> {
        if (array == null) {
            return emptyList()
        }
        return buildList(array.length()) {
            for (index in 0 until array.length()) {
                val obj = array.getJSONObject(index)
                add(
                    ReplayLogCandidateTrace(
                        rank = obj.optInt("rank", index + 1),
                        wayId = obj.takeUnless { it.isNull("way_id") }?.optString("way_id")?.ifBlank { null },
                        score = obj.takeUnless { it.isNull("score") }?.optDouble("score"),
                        distanceM = obj.takeUnless { it.isNull("distance_m") }?.optDouble("distance_m"),
                        geometryScore = obj.takeUnless { it.isNull("geometry_score") }?.optDouble("geometry_score"),
                        endpointProximityM = obj.takeUnless { it.isNull("endpoint_proximity_m") }?.optDouble("endpoint_proximity_m"),
                        continuityClass = obj.takeUnless { it.isNull("continuity_class") }?.optString("continuity_class")?.ifBlank { null },
                        highway = obj.takeUnless { it.isNull("highway") }?.optString("highway")?.ifBlank { null },
                        service = obj.takeUnless { it.isNull("service") }?.optString("service")?.ifBlank { null },
                        streetName = obj.takeUnless { it.isNull("street_name") }?.optString("street_name")?.ifBlank { null },
                        streetRef = obj.takeUnless { it.isNull("street_ref") }?.optString("street_ref")?.ifBlank { null },
                        tunnel = obj.takeUnless { it.isNull("tunnel") }?.optString("tunnel")?.ifBlank { null },
                        tunnelSelectable = obj.optBoolean("tunnel_selectable", false),
                        corridorSelectable = obj.optBoolean("corridor_selectable", false),
                        portalEligible = obj.optBoolean("portal_eligible", false),
                        isSelected = obj.optBoolean("is_selected", false),
                    ),
                )
            }
        }
    }

    private fun instrumentationAssets(): AssetManager = InstrumentationRegistry.getInstrumentation().context.assets

    private fun execSql(
        db: SQLiteDatabase,
        sql: String,
    ) {
        sql.split(";")
            .map(String::trim)
            .filter(String::isNotEmpty)
            .forEach(db::execSQL)
    }

    private fun normalizedRefTokens(raw: String?): List<String> {
        return raw
            ?.trim()
            ?.uppercase()
            ?.split(Regex("[^A-Z0-9]+"))
            ?.map(String::trim)
            ?.filter(String::isNotEmpty)
            .orEmpty()
    }

    private fun hindsightPseudoLabelWayId(
        entries: List<ReplayDriveLogEntry>,
        index: Int,
        futureWindow: Int,
        minFutureRunLength: Int,
        minAgreementRatio: Double,
    ): String? {
        if (index < 0 || index >= entries.size) {
            return null
        }
        val rowResult = entries[index].result ?: return null
        val candidateWayIds = rowResult.candidateWayIds
        if (candidateWayIds.isEmpty()) {
            return null
        }
        val upperBound = index + 1 + futureWindow
        if (upperBound > entries.size) {
            return null
        }
        val futureWayIds = entries.subList(index + 1, upperBound).mapNotNull { it.result?.wayId }
        if (futureWayIds.size != futureWindow) {
            return null
        }
        val agreementThreshold = ceil(futureWindow * minAgreementRatio).toInt()
        val majority = futureWayIds.groupingBy { it }.eachCount().maxWithOrNull(
            compareBy<Map.Entry<String, Int>> { it.value }.thenByDescending { it.key },
        ) ?: return null
        if (majority.value < agreementThreshold || majority.key !in candidateWayIds) {
            return null
        }
        var futureRunLength = 0
        for (futureWayId in futureWayIds) {
            if (futureWayId != majority.key) {
                break
            }
            futureRunLength += 1
        }
        return majority.key.takeIf { futureRunLength >= minFutureRunLength }
    }

    private fun countABAOscillations(ids: List<String?>): Int {
        if (ids.size < 3) {
            return 0
        }
        var count = 0
        for (index in 2 until ids.size) {
            val lhs = ids[index - 2]
            val middle = ids[index - 1]
            val rhs = ids[index]
            if (lhs != null && middle != null && rhs != null && lhs == rhs && lhs != middle) {
                count += 1
            }
        }
        return count
    }

    private fun countSameRefABAOscillations(
        wayIds: List<String?>,
        refs: List<String?>,
    ): Int {
        if (wayIds.size != refs.size || wayIds.size < 3) {
            return 0
        }
        var count = 0
        for (index in 2 until wayIds.size) {
            val lhsWayId = wayIds[index - 2]
            val middleWayId = wayIds[index - 1]
            val rhsWayId = wayIds[index]
            val lhsRef = refs[index - 2]?.trim()
            val middleRef = refs[index - 1]?.trim()
            val rhsRef = refs[index]?.trim()
            if (
                lhsWayId != null &&
                middleWayId != null &&
                rhsWayId != null &&
                !lhsRef.isNullOrEmpty() &&
                lhsRef == middleRef &&
                lhsRef == rhsRef &&
                lhsWayId == rhsWayId &&
                lhsWayId != middleWayId
            ) {
                count += 1
            }
        }
        return count
    }

    private fun hasPortalEligibleTunnelCandidate(result: ReplayLogResult?): Boolean {
        return result?.candidateTraces?.any { it.portalEligible } == true
    }

    private fun hasPortalEligibleTunnelCandidate(result: SpeedLookupResult?): Boolean {
        return result?.candidateTraces?.any { it.portalEligible } == true
    }

    private fun nearestTrace(traces: List<MatcherCandidateTrace>): MatcherCandidateTrace? {
        return traces.minWithOrNull(
            compareBy<MatcherCandidateTrace> { it.distanceM }
                .thenBy { it.geometryScore ?: Double.POSITIVE_INFINITY }
                .thenBy { it.wayId ?: "" },
        )
    }

    private fun formatCounter(counter: Map<String, Int>): String {
        return if (counter.isEmpty()) {
            "none"
        } else {
            counter.keys.sorted().joinToString(",") { key -> "$key=${counter[key] ?: 0}" }
        }
    }

    private fun safeRatio(numerator: Int, denominator: Int): Double {
        return if (denominator > 0) numerator.toDouble() / denominator.toDouble() else 0.0
    }

    private fun formatRatio(value: Double): String = String.format("%.4f", value)

    private fun percentile(
        values: List<Double>,
        p: Double,
    ): Double {
        if (values.isEmpty()) {
            return 0.0
        }
        val sorted = values.sorted()
        val index = ((sorted.size - 1).toDouble() * p).toInt()
        return sorted[index.coerceIn(0, sorted.size - 1)]
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) {
            return emptyList()
        }
        return buildList(length()) {
            for (index in 0 until length()) {
                optString(index)?.trim()?.takeIf { it.isNotEmpty() }?.let(::add)
            }
        }
    }

    private data class TrackPoint(
        val lat: Double,
        val lon: Double,
    )

    private data class ReplayExpectation(
        val expectedWayId: String?,
        val expectedSpeedKmh: Int?,
    )

    private data class ReplayTraceManifest(
        val fieldLogs: List<ReplayTraceDescriptor>,
        val geomLogs: List<ReplayTraceDescriptor>,
        val walkingLog: ReplayTraceDescriptor?,
    )

    private data class ReplayTraceDescriptor(
        val name: String,
        val file: String,
        val entryCount: Int,
    )

    private data class ReplayDriveLogEntry(
        val fixId: Int,
        val timestampUtc: String,
        val lat: Double,
        val lon: Double,
        val speedKmh: Double,
        val horizontalAccM: Double,
        val courseDeg: Double,
        val gpsSignalBars: Int,
        val status: String,
        val result: ReplayLogResult?,
    )

    private data class ReplayLogResult(
        val wayId: String?,
        val highway: String?,
        val streetRef: String?,
        val isTunnelSegment: Boolean,
        val nearbyTunnelCandidateWayIds: List<String>,
        val nearbyTunnelCandidateRefs: List<String>,
        val matchedEndpointProximityM: Double?,
        val candidateTraces: List<ReplayLogCandidateTrace>,
    ) {
        val candidateWayIds: List<String>
            get() = candidateTraces.mapNotNull { it.wayId }
    }

    private data class ReplayLogCandidateTrace(
        val rank: Int,
        val wayId: String?,
        val score: Double?,
        val distanceM: Double?,
        val geometryScore: Double?,
        val endpointProximityM: Double?,
        val continuityClass: String?,
        val highway: String?,
        val service: String?,
        val streetName: String?,
        val streetRef: String?,
        val tunnel: String?,
        val tunnelSelectable: Boolean,
        val corridorSelectable: Boolean,
        val portalEligible: Boolean,
        val isSelected: Boolean,
    )

    private data class ReplayPseudoLabelMetrics(
        var replayedFixCount: Int = 0,
        var pseudoLabelExampleCount: Int = 0,
        var correctPseudoLabelCount: Int = 0,
        var changedExampleCount: Int = 0,
        var changedCorrectCount: Int = 0,
        var unchangedExampleCount: Int = 0,
        var unchangedCorrectCount: Int = 0,
    ) {
        val accuracy: Double
            get() = if (pseudoLabelExampleCount > 0) {
                correctPseudoLabelCount.toDouble() / pseudoLabelExampleCount.toDouble()
            } else {
                0.0
            }

        val changedRecall: Double
            get() = if (changedExampleCount > 0) {
                changedCorrectCount.toDouble() / changedExampleCount.toDouble()
            } else {
                0.0
            }

        val unchangedAccuracy: Double
            get() = if (unchangedExampleCount > 0) {
                unchangedCorrectCount.toDouble() / unchangedExampleCount.toDouble()
            } else {
                0.0
            }

        fun recordPseudoLabelExample(
            predictedMatches: Boolean,
            isChangedExample: Boolean,
        ) {
            pseudoLabelExampleCount += 1
            if (predictedMatches) {
                correctPseudoLabelCount += 1
            }
            if (isChangedExample) {
                changedExampleCount += 1
                if (predictedMatches) {
                    changedCorrectCount += 1
                }
            } else {
                unchangedExampleCount += 1
                if (predictedMatches) {
                    unchangedCorrectCount += 1
                }
            }
        }

        fun formUnion(other: ReplayPseudoLabelMetrics) {
            replayedFixCount += other.replayedFixCount
            pseudoLabelExampleCount += other.pseudoLabelExampleCount
            correctPseudoLabelCount += other.correctPseudoLabelCount
            changedExampleCount += other.changedExampleCount
            changedCorrectCount += other.changedCorrectCount
            unchangedExampleCount += other.unchangedExampleCount
            unchangedCorrectCount += other.unchangedCorrectCount
        }
    }

    private companion object {
        private const val BUNDLED_SEED_ASSET_NAME = "karlsruhe-regbez_speeds.sqlite.zlib"
        private const val BUNDLED_SEED_DB_FILE_NAME = "karlsruhe-regbez_speeds.sqlite"
        private const val LOG_TAG = "V3ReplayInstrumentedTest"
    }
}

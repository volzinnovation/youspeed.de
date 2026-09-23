package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignPassageTests {
    private val t0 = Instant.parse("2026-09-04T08:00:00Z")

    @Test fun framePreviewCannotReturnAfterFiveMinuteExpiry() {
        val context = context("1", emptySet())
        val preview = TrafficSignSpeedOverride(90, t0, "preview", context)
        assertEquals(preview, TrafficSignSpeedOverridePolicy.currentForPresentation(preview, context, t0.plusSeconds(299)))
        assertNull(TrafficSignSpeedOverridePolicy.currentForPresentation(preview, context, t0.plusSeconds(300)))
        assertNull(TrafficSignSpeedOverridePolicy.currentForPresentation(preview, context.copy(wayId = "2"), t0.plusSeconds(1)))
    }

    @Test fun frenchDefaultsAndStrictSpeedTags() {
        assertEquals(80, RoadSpeedDefaults.symbolicSpeed("FR:rural", "FRA"))
        assertEquals(50, RoadSpeedDefaults.symbolicSpeed("FR:urban", "FR"))
        assertEquals(80, RoadSpeedDefaults.speedKmh("FR", null, "secondary", false))
        assertEquals(50, RoadSpeedDefaults.speedKmh("FR", null, "secondary", true))
        assertNull(RoadSpeedDefaults.speedKmh("FR", null, "trunk", false))
        assertNull(RoadSpeedDefaults.speedKmh("FR", null, "motorway_link", false))
        for (value in listOf("50;70", "50 @ (wet)", "signals", "50/80", "none", "0", "999")) assertNull(value, RoadSpeedDefaults.explicitSpeed(value))
        assertEquals(50, RoadSpeedDefaults.explicitSpeed("50 km/h"))
        assertEquals(48, RoadSpeedDefaults.explicitSpeed("30 mph"))
        assertEquals("ref:A9", DrivingRoadIdentity.key(" A 9 ", null, "motorway"))
        assertFalse(DrivingRoadIdentity.key("A9", null, "motorway") == DrivingRoadIdentity.key("A9", null, "motorway_link"))
    }

    @Test fun cameraLimitSurvivesWaySplitsButExpiresAfterFiveMinutes() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(130, EffectiveSpeedLimitSource.BUNDLE)
        val first = context("1", emptySet()).copy(continuityCapable = false, roadIdentity = "ref:A9")
        val next = context("2", emptySet()).copy(continuityCapable = false, roadIdentity = "ref:A9")
        resolver.commit(passage(TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 90), first), bundle)
        assertEquals(90, resolver.reconcile(TrafficSignRoadMatch(next, t0.plusSeconds(299)), bundle).resolution?.speedKmh)
        assertEquals(130, resolver.reconcile(TrafficSignRoadMatch(next, t0.plusSeconds(300)), bundle).resolution?.speedKmh)
        assertNull(resolver.activeAssertion())
    }

    @Test fun roadReferenceChangeClearsCameraEvenWithinSameRouteRelation() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(80, EffectiveSpeedLimitSource.BUNDLE)
        resolver.commit(passage(context = context("100", setOf(1)).copy(roadIdentity = "ref:D19")), bundle)
        assertEquals(80, resolver.reconcile(TrafficSignRoadMatch(context("101", setOf(1)).copy(roadIdentity = "ref:D228"), t0.plusSeconds(1)), bundle).resolution?.speedKmh)
    }

    @Test fun postedTimeoutRetainsEnclosingZone() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(80, EffectiveSpeedLimitSource.BUNDLE)
        resolver.commit(passage(TrafficSignAction(TrafficSignActionKind.ZONE_START, 30)), bundle)
        resolver.commit(passage(TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 20), at = t0.plusSeconds(1)), bundle)
        assertEquals(30, resolver.reconcile(TrafficSignRoadMatch(context("100", setOf(1)), t0.plusSeconds(301)), bundle).resolution?.speedKmh)
    }

    @Test fun singleStructuralSignRequiresStableContextAndThreeNegativeFrames() {
        for (stable in listOf(true, false)) {
            val finalizer = TrafficSignPassageFinalizer()
            val context = context("100", setOf(1)).copy(matchedWayStable = stable)
            val seen = recognition(t0, confidence = 0.777).let { it.copy(roadContext = context, candidate = it.candidate?.copy(
                rawClassId = "maxspeed:end", semantic = TrafficSignSemantic(TrafficSignSemanticKind.RESTRICTION_END))) }
            finalizer.observe(seen, 0.777, 1, true, true)
            for (index in 1..2) assertNull(finalizer.observe(missing(t0.plusMillis(index * 200L)).copy(roadContext = context), null, 1, true, true))
            assertEquals(stable, finalizer.observe(missing(t0.plusMillis(600)).copy(roadContext = context), null, 1, true, true) != null)
        }
    }

    @Test fun userRecordingPrecedesCameraStartsEndsAndReconciliation() {
        val manual = base(90, EffectiveSpeedLimitSource.LOCAL_CORRECTION).copy(isUserCorrection = true)
        for (action in listOf(TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 50),
            TrafficSignAction(TrafficSignActionKind.ALL_RESTRICTIONS_END),
            TrafficSignAction(TrafficSignActionKind.CITY_ENTRY, countryCode = "FR"))) {
            val resolver = TrafficSignRuntimeSourceResolver()
            resolver.commit(passage(), base(130, EffectiveSpeedLimitSource.BUNDLE))
            val result = resolver.commit(passage(action = action), manual)
            assertEquals(90, result.resolution?.speedKmh)
            assertTrue(result.isUserCorrection)
            assertNull(resolver.activeAssertion())
            assertEquals(90, resolver.effective(manual).resolution?.speedKmh)
        }
    }

    @Test fun nationalEndAndCityTransitionsDiscardOldPostedLimits() {
        val bundle = base(70, EffectiveSpeedLimitSource.BUNDLE)
        for (action in listOf(TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, 70),
            TrafficSignAction(TrafficSignActionKind.ALL_RESTRICTIONS_END), TrafficSignAction(TrafficSignActionKind.CITY_EXIT))) {
            val resolver = TrafficSignRuntimeSourceResolver()
            resolver.commit(passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 70)), bundle)
            val ended = resolver.commit(passage(action = action, at = t0.plusSeconds(2)), bundle,
                TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 130))
            assertEquals(130, ended.resolution?.speedKmh)
            assertEquals(130, resolver.effective(bundle).resolution?.speedKmh)
        }
        for (country in listOf("FR", "BE")) {
            val resolver = TrafficSignRuntimeSourceResolver()
            resolver.commit(passage(), bundle)
            assertEquals(50, resolver.commit(passage(action = TrafficSignAction(TrafficSignActionKind.CITY_ENTRY, countryCode = country),
                at = t0.plusSeconds(2)), bundle, TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50)).resolution?.speedKmh)
        }
    }

    @Test fun roadDefaultsRequireCountryRegionAndRoadContext() {
        assertEquals(130, TrafficSignRoadDefaultPolicy.speedKmh("FR", null, "motorway", null))
        assertEquals(120, TrafficSignRoadDefaultPolicy.speedKmh("CH", null, "motorway", null))
        assertEquals(100, TrafficSignRoadDefaultPolicy.speedKmh("CH", null, "trunk", false))
        assertEquals(70, TrafficSignRoadDefaultPolicy.speedKmh("BE", "BE-VLG", "secondary", false))
        assertEquals(90, TrafficSignRoadDefaultPolicy.speedKmh("BE", "BE-WAL", "secondary", false))
        assertEquals(30, TrafficSignRoadDefaultPolicy.speedKmh("BE", "BE-BRU", "residential", true))
        assertNull(TrafficSignRoadDefaultPolicy.speedKmh("NL", null, "motorway", null))
        assertNull(TrafficSignRoadDefaultPolicy.speedKmh("BE", null, "secondary", false))
    }

    @Test
    fun visibleFramesNeverActivateAndOnlyQualifiedLiveLossFinalizes() {
        val finalizer = TrafficSignPassageFinalizer()
        val first = finalizer.observe(
            event = recognition(t0, trackId = "physical-1", confidence = 0.82),
            fusedScore = 0.82,
            contextGeneration = 4,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        )
        val second = finalizer.observe(
            event = recognition(t0.plusMillis(200), trackId = "physical-1", confidence = 0.88),
            fusedScore = 0.88,
            contextGeneration = 4,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        )

        assertNull(first)
        assertNull(second)
        assertNull(finalizer.observe(
            event = missing(t0.plusMillis(400)),
            fusedScore = null,
            contextGeneration = 4,
            qualifiedAnalyzedFrame = false,
            overrideEligible = true,
        ))

        assertNull(finalizer.observe(
            event = missing(t0.plusMillis(600)),
            fusedScore = null,
            contextGeneration = 4,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        ))
        val passage = finalizer.observe(
            event = missing(t0.plusMillis(800)),
            fusedScore = null,
            contextGeneration = 4,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        )

        requireNotNull(passage)
        assertEquals(t0.plusMillis(600), passage.passageBoundary.timestampUtc)
        assertEquals(0.88, passage.finalConfidence, 0.0)
        assertTrue(passage.finalAccumulatedSupport > passage.evidence.first().accumulatedSupport)
        assertTrue(passage.evidence.zipWithNext().all { (a, b) -> b.accumulatedSupport >= a.accumulatedSupport })
    }

    @Test
    fun passageRetainsAllAssemblyIdsAndMeasuresConsecutiveSeenStreaks() {
        val finalizer = TrafficSignPassageFinalizer()
        fun seen(at: Instant, assemblyId: String, confidence: Double) = recognition(at, confidence = confidence).let { event ->
            event.copy(candidate = event.candidate?.copy(assemblyId = assemblyId))
        }

        finalizer.observe(seen(t0, "assembly-a", 0.90), 0.90, 1, true, true)
        finalizer.observe(seen(t0.plusMillis(200), "assembly-b", 0.92), 0.92, 1, true, true)
        assertNull(finalizer.observe(missing(t0.plusMillis(400)), null, 1, true, true))
        finalizer.observe(seen(t0.plusMillis(600), "assembly-c", 0.94), 0.94, 1, true, true)
        assertNull(finalizer.observe(missing(t0.plusMillis(800)), null, 1, true, true))
        val passage = finalizer.observe(missing(t0.plusMillis(1_000)), null, 1, true, true)

        requireNotNull(passage)
        assertEquals(listOf("assembly-a", "assembly-b", "assembly-c"), passage.assemblyIds)
        assertEquals(3, passage.framesSeen)
        assertEquals(2, passage.peakConsecutiveFramesSeen)
    }

    @Test
    fun duplicateSuppressionUsesNormalizedActionRatherThanRawClassAlias() {
        val finalizer = TrafficSignPassageFinalizer()
        fun aliased(at: Instant, rawClassId: String) = recognition(at).let { event ->
            event.copy(candidate = event.candidate?.copy(rawClassId = rawClassId))
        }

        finalizer.observe(aliased(t0, "speed_limit_30"), 0.95, 1, true, true)
        finalizer.observe(aliased(t0.plusMillis(100), "de_274_30"), 0.96, 1, true, true)
        assertNull(finalizer.observe(missing(t0.plusMillis(200)), null, 1, true, true))
        assertEquals(
            "physical-1",
            finalizer.observe(missing(t0.plusMillis(300)), null, 1, true, true)?.physicalTrackId,
        )

        repeat(2) { index ->
            assertNull(
                finalizer.observe(
                    aliased(t0.plusMillis(500L + index * 100L), "maximum_speed_30_alias"),
                    0.99,
                    1,
                    true,
                    true,
                ),
            )
        }
        repeat(3) { index ->
            assertNull(finalizer.observe(missing(t0.plusMillis(800L + index * 100L)), null, 1, true, true))
        }
        assertFalse(finalizer.hasActiveTrack())
    }

    @Test
    fun trackerIdSplitIsSuppressedOnlyWhenTheSameActionIsSpatiallyNear() {
        val finalizer = TrafficSignPassageFinalizer()
        fun seen(at: Instant, trackId: String, longitude: Double) = recognition(
            at = at,
            trackId = trackId,
            confidence = 0.96,
            speedKmh = 50,
        ).copy(roadContext = context("100", setOf(1)).copy(longitude = longitude))

        finalizer.observe(seen(t0, "track-a", 8.4000), 0.96, 1, true, true)
        finalizer.observe(seen(t0.plusMillis(100), "track-a", 8.4000), 0.97, 1, true, true)
        assertNull(finalizer.observe(missing(t0.plusMillis(200)), null, 1, true, true))
        assertEquals(
            "track-a",
            finalizer.observe(missing(t0.plusMillis(300)), null, 1, true, true)?.physicalTrackId,
        )

        // The tracker split the same nearby physical sign into a fresh ID.
        repeat(2) { index ->
            assertNull(
                finalizer.observe(
                    seen(t0.plusMillis(400L + index * 100L), "track-b", 8.4001),
                    0.98,
                    1,
                    true,
                    true,
                ),
            )
        }
        repeat(3) { index ->
            assertNull(finalizer.observe(missing(t0.plusMillis(600L + index * 100L)), null, 1, true, true))
        }
        assertFalse(finalizer.hasActiveTrack())

        // Roughly 73 m east at this latitude: a separate, same-valued sign is
        // outside the 45 m split-suppression radius even inside the time bound.
        finalizer.observe(seen(t0.plusMillis(1_000), "track-c", 8.4010), 0.96, 1, true, true)
        finalizer.observe(seen(t0.plusMillis(1_100), "track-c", 8.4010), 0.97, 1, true, true)
        assertNull(finalizer.observe(missing(t0.plusMillis(1_200)), null, 1, true, true))
        assertEquals(
            "track-c",
            finalizer.observe(missing(t0.plusMillis(1_300)), null, 1, true, true)?.physicalTrackId,
        )
    }

    @Test
    fun interveningDistinctActionAllowsReturningToEarlierValueInsideSuppressionWindow() {
        val finalizer = TrafficSignPassageFinalizer()
        fun commit(trackId: String, speedKmh: Int, offsetMs: Long): TrafficSignPassageEvent {
            finalizer.observe(recognition(t0.plusMillis(offsetMs), trackId, 0.96, speedKmh), 0.96, 1, true, true)
            finalizer.observe(recognition(t0.plusMillis(offsetMs + 100), trackId, 0.97, speedKmh), 0.97, 1, true, true)
            assertNull(finalizer.observe(missing(t0.plusMillis(offsetMs + 200)), null, 1, true, true))
            return requireNotNull(
                finalizer.observe(missing(t0.plusMillis(offsetMs + 300)), null, 1, true, true),
            )
        }

        assertEquals(50, commit("track-50-a", 50, 0).action.valueKmh)
        assertEquals(70, commit("track-70", 70, 500).action.valueKmh)
        assertEquals(50, commit("track-50-b", 50, 1_000).action.valueKmh)
    }

    @Test
    fun confirmedSingleFrameStillRequiresStrictThresholdButRepeatedTrackArms() {
        val single = TrafficSignPassageFinalizer()
        single.observe(recognition(t0, confidence = 0.90), 0.90, 1, true, true)
        repeat(3) { index ->
            assertNull(single.observe(missing(t0.plusMillis(200L + index * 200L)), null, 1, true, true))
        }

        val repeated = TrafficSignPassageFinalizer()
        repeated.observe(recognition(t0, confidence = 0.90), 0.90, 1, true, true)
        repeated.observe(recognition(t0.plusMillis(200), confidence = 0.91), 0.91, 1, true, true)
        assertNull(repeated.observe(missing(t0.plusMillis(400)), null, 1, true, true))
        assertEquals(
            "physical-1",
            repeated.observe(missing(t0.plusMillis(600)), null, 1, true, true)?.physicalTrackId,
        )
    }

    @Test
    fun highConfidenceSingleSightingStillRequiresStrictLossDebounceWithStrongGeometry() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(recognition(t0, confidence = 0.97), 0.97, 1, true, true)

        assertNull(finalizer.observe(
            missing(t0.plusMillis(200)), null, 1, true, true, strongPassGeometry = true,
        ))
        assertNull(finalizer.observe(
            missing(t0.plusMillis(400)), null, 1, true, true, strongPassGeometry = true,
        ))
        val passage = finalizer.observe(
            missing(t0.plusMillis(600)), null, 1, true, true, strongPassGeometry = true,
        )

        assertEquals("physical-1", passage?.physicalTrackId)
        assertEquals(3, passage?.negativeFramesToCommit)
    }

    @Test
    fun stationaryMissingFramesDoNotAdvanceAnArmedPassage() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(recognition(t0, confidence = 0.90), 0.90, 1, true, true)
        finalizer.observe(recognition(t0.plusMillis(200), confidence = 0.91), 0.91, 1, true, true)

        repeat(3) { index ->
            assertNull(
                finalizer.observe(
                    missing(t0.plusMillis(400L + index * 200L)),
                    null,
                    1,
                    qualifiedAnalyzedFrame = true,
                    overrideEligible = false,
                ),
            )
        }
        assertTrue(finalizer.hasActiveTrack())
        assertNull(finalizer.observe(missing(t0.plusMillis(1_200)), null, 1, true, true))
        assertEquals(
            "physical-1",
            finalizer.observe(missing(t0.plusMillis(1_400)), null, 1, true, true)?.physicalTrackId,
        )
    }

    @Test
    fun stillCaptureCannotArmButRawScoreLiveFramesCan() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(
            event = recognition(t0, source = TrafficSignInputSource.CAMERA_STILL),
            fusedScore = 0.99,
            contextGeneration = 1,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        )
        finalizer.observe(
            event = recognition(t0.plusSeconds(1)).copy(
                candidate = recognition(t0.plusSeconds(1)).candidate?.copy(calibratedConfidence = null),
            ),
            fusedScore = 0.99,
            contextGeneration = 1,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        )
        finalizer.observe(
            event = recognition(t0.plusMillis(1_200)).copy(
                candidate = recognition(t0.plusMillis(1_200)).candidate?.copy(calibratedConfidence = null),
            ),
            fusedScore = 0.99,
            contextGeneration = 1,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
        )

        assertTrue(finalizer.hasActiveTrack())
        assertNull(finalizer.observe(missing(t0.plusSeconds(2)), null, 1, true, true))
        assertEquals(
            30,
            finalizer.observe(missing(t0.plusMillis(2_200)), null, 1, true, true)
                ?.action?.valueKmh,
        )
    }

    @Test
    fun unknownDirectionAndMissingContinuityDoNotBlockSameWayActivation() {
        val base = base(50, EffectiveSpeedLimitSource.BUNDLE)
        val contexts = listOf(
            context("100", emptySet()).copy(travelDirection = TrafficSignTravelDirection.UNKNOWN),
            context("100", emptySet()).copy(continuityCapable = false),
        )

        contexts.forEachIndexed { index, activationContext ->
            val resolver = TrafficSignRuntimeSourceResolver()
            val effective = resolver.commit(
                passage(
                    action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 30),
                    context = activationContext,
                    at = t0.plusSeconds(index.toLong()),
                ),
                base,
            )

            assertEquals(30, effective.resolution?.speedKmh)
            assertEquals(EffectiveSpeedLimitSource.CAMERA, effective.source)
            assertEquals(activationContext.travelDirection, resolver.activeAssertion()?.scope?.travelDirection)
        }
    }

    @Test
    fun unknownAndNonSpeedHardNegativesNeverCreatePassageEvents() {
        listOf(
            TrafficSignSemanticKind.UNKNOWN,
            TrafficSignSemanticKind.NON_SPEED_RESTRICTION_END,
        ).forEachIndexed { index, kind ->
            val finalizer = TrafficSignPassageFinalizer()
            val hardNegative = recognition(t0.plusSeconds(index.toLong())).let { event ->
                event.copy(candidate = event.candidate?.copy(semantic = TrafficSignSemantic(kind)))
            }
            repeat(4) {
                assertNull(finalizer.observe(hardNegative, 0.99, 1, true, true))
            }
            assertFalse(finalizer.hasActiveTrack())
        }
    }

    @Test
    fun hardNegativeRecognitionsAreNeutralToAnArmedSpeedTrack() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(recognition(t0), 0.90, 1, true, true)
        finalizer.observe(recognition(t0.plusMillis(200)), 0.94, 1, true, true)
        val hardNegative = recognition(t0.plusMillis(400)).let { event ->
            event.copy(candidate = event.candidate?.copy(semantic = TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)))
        }

        repeat(3) { index ->
            assertNull(finalizer.observe(hardNegative.copy(frameTimestampUtc = t0.plusMillis(400L + index)), 0.99, 1, true, true))
        }
        assertTrue(finalizer.hasActiveTrack())
        assertNull(finalizer.observe(missing(t0.plusMillis(800)), null, 1, true, true))
        assertEquals("physical-1", finalizer.observe(missing(t0.plusMillis(1_000)), null, 1, true, true)?.physicalTrackId)
    }

    @Test
    fun legacyRestrictionEndUsesRawClassToDistinguish278From282() {
        fun finalized(rawClassId: String): TrafficSignPassageEvent? {
            val finalizer = TrafficSignPassageFinalizer()
            val legacy = recognition(t0).let { event ->
                event.copy(
                    candidate = event.candidate?.copy(
                        rawClassId = rawClassId,
                        semantic = TrafficSignSemantic(TrafficSignSemanticKind.RESTRICTION_END, value = 30),
                    ),
                )
            }
            finalizer.observe(legacy, 0.90, 1, true, true)
            finalizer.observe(legacy.copy(frameTimestampUtc = t0.plusMillis(200)), 0.94, 1, true, true)
            finalizer.observe(missing(t0.plusMillis(400)), null, 1, true, true)
            return finalizer.observe(missing(t0.plusMillis(600)), null, 1, true, true)
        }

        assertEquals(TrafficSignActionKind.MAXIMUM_SPEED_END, finalized("maxspeed:end")?.action?.kind)
        assertEquals(TrafficSignActionKind.ALL_RESTRICTIONS_END, finalized("DE:282")?.action?.kind)
        assertNull(finalized("no_overtaking:end"))
    }

    @Test
    fun generationWriteGateLinearizesInvalidationAfterAnInFlightWrite() {
        val gate = TrafficSignWriteGate()
        val generation = gate.incrementAndGet(permitWrites = true)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val invalidated = CountDownLatch(1)
        val writer = Thread {
            gate.withPermit(generation) {
                entered.countDown()
                release.await(2, TimeUnit.SECONDS)
            }
        }
        val invalidator = Thread {
            gate.incrementAndGet(permitWrites = false)
            invalidated.countDown()
        }
        writer.start()
        assertTrue(entered.await(1, TimeUnit.SECONDS))
        invalidator.start()
        assertFalse(invalidated.await(100, TimeUnit.MILLISECONDS))
        release.countDown()
        assertTrue(invalidated.await(1, TimeUnit.SECONDS))
        writer.join()
        invalidator.join()
        assertNull(gate.withPermit(generation) { "stale" })
    }

    @Test
    fun cameraGenerationSnapshotDoesNotWaitForDurableWrite() {
        val gate = TrafficSignWriteGate()
        val generation = gate.incrementAndGet(permitWrites = true)
        val writing = CountDownLatch(1)
        val releaseWrite = CountDownLatch(1)
        val read = CountDownLatch(1)
        val snapshot = java.util.concurrent.atomic.AtomicReference<Pair<Long, Boolean>>()
        val writer = Thread {
            gate.withPermit(generation) {
                writing.countDown()
                releaseWrite.await(5, TimeUnit.SECONDS)
            }
        }
        val reader = Thread { snapshot.set(gate.snapshot()); read.countDown() }
        try {
            writer.start()
            assertTrue(writing.await(1, TimeUnit.SECONDS))
            reader.start()
            assertTrue("Camera admission waited for storage", read.await(1, TimeUnit.SECONDS))
            assertEquals(generation to true, snapshot.get())
        } finally {
            releaseWrite.countDown()
            writer.join(2_000)
            reader.join(2_000)
        }
    }

    @Test
    fun differentVisibleCandidateFinalizesArmedOldTrackAndRetainsNewTrack() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(recognition(t0, "old", 0.85), 0.85, 1, true, true)
        finalizer.observe(recognition(t0.plusMillis(200), "old", 0.88), 0.88, 1, true, true)

        assertNull(finalizer.observe(
            recognition(t0.plusMillis(400), "new", 0.96, speedKmh = 50),
            0.96,
            1,
            true,
            true,
        ))
        val oldPassage = finalizer.observe(
            recognition(t0.plusMillis(600), "new", 0.97, speedKmh = 50),
            0.97,
            1,
            true,
            true,
        )

        assertEquals("old", oldPassage?.physicalTrackId)
        assertTrue(finalizer.hasActiveTrack())
        assertNull(finalizer.observe(missing(t0.plusMillis(800)), null, 1, true, true))
        assertEquals("new", finalizer.observe(missing(t0.plusMillis(1_000)), null, 1, true, true)?.physicalTrackId)
    }

    @Test
    fun reusedTrackIdWithDifferentSupportedSemanticFinalizesOldBeforeNew() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(recognition(t0, speedKmh = 50), 0.90, 1, true, true)
        finalizer.observe(recognition(t0.plusMillis(200), speedKmh = 50), 0.92, 1, true, true)

        assertNull(finalizer.observe(recognition(t0.plusMillis(400), speedKmh = 70), 0.93, 1, true, true))
        val oldPassage = finalizer.observe(
            recognition(t0.plusMillis(600), speedKmh = 70),
            0.94,
            1,
            true,
            true,
        )
        assertEquals(50, oldPassage?.action?.valueKmh)
        assertTrue(finalizer.hasActiveTrack())

        assertNull(finalizer.observe(missing(t0.plusMillis(800)), null, 1, true, true))
        val newPassage = finalizer.observe(missing(t0.plusMillis(1_000)), null, 1, true, true)
        assertEquals(70, newPassage?.action?.valueKmh)
    }

    @Test
    fun strongPassGeometryMayFinalizeRepeatedTrackOnFirstAnalyzedMiss() {
        val finalizer = TrafficSignPassageFinalizer()
        finalizer.observe(recognition(t0, "strong", 0.84), 0.84, 1, true, true)
        finalizer.observe(recognition(t0.plusMillis(200), "strong", 0.90), 0.90, 1, true, true)

        val passage = finalizer.observe(
            event = missing(t0.plusMillis(400)),
            fusedScore = null,
            contextGeneration = 1,
            qualifiedAnalyzedFrame = true,
            overrideEligible = true,
            strongPassGeometry = true,
        )

        assertEquals("strong", passage?.physicalTrackId)
        assertEquals(true, passage?.passageBoundary?.strongPassGeometry)
        assertEquals(1, passage?.negativeFramesToCommit)
    }

    @Test
    fun relationScopeNarrowsAndCannotHopTransitively() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val local = base(50, EffectiveSpeedLimitSource.LOCAL_CORRECTION)
        val committed = resolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 70), context = context("100", setOf(1, 2))),
            local,
        )
        assertEquals(70, committed.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, committed.source)

        val continued = resolver.reconcile(
            TrafficSignRoadMatch(context("101", setOf(2, 3)), t0.plusSeconds(1)),
            local,
        )
        assertEquals(EffectiveSpeedLimitSource.CAMERA, continued.source)
        assertEquals(setOf(2L), resolver.activeAssertion()?.scope?.eligibleRouteRelationGroupIds)

        val hopped = resolver.reconcile(
            TrafficSignRoadMatch(context("102", setOf(3)), t0.plusSeconds(2)),
            local,
        )
        assertEquals(EffectiveSpeedLimitSource.LOCAL_CORRECTION, hopped.source)
        assertNull(resolver.activeAssertion())
    }

    @Test
    fun staleLookupGateDoesNotDrainPendingPersistablePassage() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val event = passage(context = context("100", setOf(1)))
        resolver.commit(event, base(50, EffectiveSpeedLimitSource.BUNDLE))
        val gate = TrafficSignLookupMutationGate()
        val staleToken = gate.advance()
        gate.advance()

        assertNull(gate.mutateIfCurrent(staleToken) { resolver.takeNewlyPersistableEvent() })
        assertEquals(event.finalizedEventId, resolver.takeNewlyPersistableEvent()?.finalizedEventId)
    }

    @Test
    fun tokenScopedEvaluationPersistsFrozenPassageBeforeSupersededUiCommit() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val gate = TrafficSignLookupMutationGate()
        val oldToken = gate.advance()
        val oldEvent = passage(
            action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 70),
            context = context("100", setOf(1)),
        )
        val persisted = mutableListOf<Pair<String, Int?>>()

        val frozenOldEvent = gate.mutateIfCurrent(oldToken) {
            val oldEffective = resolver.commit(oldEvent, base(50, EffectiveSpeedLimitSource.BUNDLE))
            resolver.takeNewlyPersistableEvent()?.also { event ->
                persisted += event.finalizedEventId to oldEffective.resolution?.speedKmh
            }
        }
        val newToken = gate.advance()

        assertNull(gate.mutateIfCurrent(oldToken) { frozenOldEvent })
        assertNull(
            gate.mutateIfCurrent(newToken) {
                // The new lookup must never inherit the old event and combine
                // it with its own base/effective resolution.
                resolver.takeNewlyPersistableEvent()
            },
        )
        assertEquals(oldEvent.finalizedEventId, frozenOldEvent?.finalizedEventId)
        assertEquals(listOf(oldEvent.finalizedEventId to 70), persisted)

        gate.mutateIfCurrent(newToken) {
            // A later 90 base cannot be paired with or re-persist the old event.
            resolver.reconcile(
                TrafficSignRoadMatch(context("200", setOf(2)), t0.plusSeconds(1)),
                base(90, EffectiveSpeedLimitSource.BUNDLE),
            )
            resolver.takeNewlyPersistableEvent()?.also { event ->
                persisted += event.finalizedEventId to 90
            }
        }
        assertEquals(listOf(oldEvent.finalizedEventId to 70), persisted)
    }

    @Test fun voiceCorrectionFollowsRoadReferenceAndExpiresWithoutRefreshingItsAge() {
        var correction = ActiveLocalSpeedCorrection("1", "130", 130, roadIdentity = "ref:A9", startedAt = t0)
        assertEquals(LocalSpeedCorrectionDecision.APPLY, LocalSpeedCorrectionPolicy.decide(correction, "2", "ref:A9", TrafficSignTravelDirection.FORWARD, t0.plusSeconds(30)))
        correction = correction.copy(lastMatchedAt = t0.plusSeconds(299))
        assertEquals(LocalSpeedCorrectionDecision.APPLY, LocalSpeedCorrectionPolicy.decide(correction, "3", "ref:A9", TrafficSignTravelDirection.FORWARD, t0.plusSeconds(299)))
        assertEquals(LocalSpeedCorrectionDecision.EXPIRE, LocalSpeedCorrectionPolicy.decide(correction, "3", "ref:A9", TrafficSignTravelDirection.FORWARD, t0.plusSeconds(300)))
        assertEquals(LocalSpeedCorrectionDecision.EXPIRE, LocalSpeedCorrectionPolicy.decide(correction, "2", "ref:D19", TrafficSignTravelDirection.FORWARD, t0.plusSeconds(1)))
        assertEquals(LocalSpeedCorrectionDecision.EXPIRE, LocalSpeedCorrectionPolicy.decide(correction.copy(direction = TrafficSignTravelDirection.FORWARD), "1", "ref:A9", TrafficSignTravelDirection.REVERSE, t0.plusSeconds(1)))
    }

    @Test
    fun acceptedCrossWayDigitizationFlipBecomesDirectionForRepeatedNewWayMatch() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
        resolver.commit(
            passage(context = context("100", setOf(7))),
            bundle,
        )
        val reverseOnRelatedWay = context("101", setOf(7)).copy(
            travelDirection = TrafficSignTravelDirection.REVERSE,
        )

        val transitioned = resolver.reconcile(
            TrafficSignRoadMatch(reverseOnRelatedWay, t0.plusSeconds(1)),
            bundle,
        )
        assertEquals(EffectiveSpeedLimitSource.CAMERA, transitioned.source)
        assertEquals(TrafficSignTravelDirection.REVERSE, resolver.activeAssertion()?.scope?.travelDirection)

        val repeated = resolver.reconcile(
            TrafficSignRoadMatch(reverseOnRelatedWay, t0.plusSeconds(2)),
            bundle,
        )
        assertEquals(EffectiveSpeedLimitSource.CAMERA, repeated.source)
        assertEquals(30, repeated.resolution?.speedKmh)
    }

    @Test
    fun passageScopeStartsAtFirstSightingAndCannotGainBoundaryRelations() {
        val finalizer = TrafficSignPassageFinalizer()
        val first = recognition(t0).copy(roadContext = context("100", setOf(1)))
        val second = recognition(t0.plusMillis(200)).copy(roadContext = context("101", setOf(1, 2)))
        finalizer.observe(first, 0.88, 1, true, true)
        finalizer.observe(second, 0.92, 1, true, true)
        finalizer.observe(missing(t0.plusMillis(400)).copy(roadContext = second.roadContext), null, 1, true, true)
        val passage = requireNotNull(
            finalizer.observe(missing(t0.plusMillis(600)).copy(roadContext = second.roadContext), null, 1, true, true),
        )
        assertEquals(setOf(1L), passage.eligibleRouteRelationGroupIds)

        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, resolver.commit(passage, bundle).source)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, resolver.reconcile(
            TrafficSignRoadMatch(context("102", setOf(2)), t0.plusSeconds(1)),
            bundle,
        ).source)
    }

    @Test
    fun trackAcquiredDuringNoMatchAdoptsFirstLaterValidVisibleContext() {
        val finalizer = TrafficSignPassageFinalizer()
        val noMatch = context("100", setOf(99)).copy(wayId = null, matchedWayStable = false)
        val matched = context("100", setOf(1))
        finalizer.observe(
            recognition(t0, confidence = 0.90).copy(roadContext = noMatch),
            0.90,
            1,
            true,
            true,
        )
        finalizer.observe(
            recognition(t0.plusMillis(200), confidence = 0.93).copy(roadContext = matched),
            0.93,
            1,
            true,
            true,
        )
        finalizer.observe(missing(t0.plusMillis(400)).copy(roadContext = matched), null, 1, true, true)
        val passage = requireNotNull(
            finalizer.observe(missing(t0.plusMillis(600)).copy(roadContext = matched), null, 1, true, true),
        )

        assertEquals("100", passage.firstSeenContext?.wayId)
        assertEquals(setOf(1L), passage.initialRouteRelationGroupIds)
        assertEquals(setOf(1L), passage.eligibleRouteRelationGroupIds)
        val effective = TrafficSignRuntimeSourceResolver().commit(
            passage,
            base(50, EffectiveSpeedLimitSource.BUNDLE),
        )
        assertEquals(EffectiveSpeedLimitSource.CAMERA, effective.source)
        assertEquals(30, effective.resolution?.speedKmh)
    }

    @Test
    fun transitiveRelationHopDuringVisibleTrackCannotActivateAtBoundary() {
        val finalizer = TrafficSignPassageFinalizer()
        val first = recognition(t0).copy(roadContext = context("100", setOf(1, 2)))
        val second = recognition(t0.plusMillis(200)).copy(roadContext = context("101", setOf(2, 3)))
        val boundaryContext = context("102", setOf(3))
        finalizer.observe(first, 0.88, 1, true, true)
        finalizer.observe(second, 0.92, 1, true, true)
        finalizer.observe(missing(t0.plusMillis(400)).copy(roadContext = boundaryContext), null, 1, true, true)
        val passage = requireNotNull(
            finalizer.observe(missing(t0.plusMillis(600)).copy(roadContext = boundaryContext), null, 1, true, true),
        )

        assertEquals(setOf(2L), passage.eligibleRouteRelationGroupIds)
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, resolver.commit(passage, bundle).source)
        assertNull(resolver.activeAssertion())
        assertEquals(passage.finalizedEventId, resolver.takeNewlyPersistableEvent()?.finalizedEventId)
    }

    @Test
    fun delayedPassageMustStillMatchCurrentRoadScope() {
        val event = passage(context = context("100", setOf(1)))
        assertFalse(trafficSignPassageContextIsCurrent(event, context("200", setOf(2))))
        assertTrue(trafficSignPassageContextIsCurrent(event, context("200", setOf(1, 2))))
        assertTrue(
            trafficSignPassageContextIsCurrent(
                event,
                context("100", setOf(1)).copy(wayId = null, matchedWayStable = false),
            ),
        )
    }

    @Test
    fun noMatchBoundaryMayEnterPendingOnlyWhileFrozenRecognitionScopeIsCurrent() {
        val noMatch = context("100", setOf(1)).copy(wayId = null, matchedWayStable = false)
        val event = passage(
            context = null,
            lastSeenContext = context("100", setOf(1)),
        )

        assertTrue(trafficSignPassageContextIsCurrent(event, noMatch))
        assertTrue(trafficSignPassageContextIsCurrent(event, context("101", setOf(1, 2))))
        assertFalse(trafficSignPassageContextIsCurrent(event, context("200", setOf(2))))
    }

    @Test
    fun productionForwarderIgnoresPerFrameOverrideAndForwardsOnlyPassage() {
        val forwarded = mutableListOf<TrafficSignPassageEvent>()
        val forwarder = TrafficSignFinalizedPassageForwarder { event ->
            forwarded += event
            true
        }
        val recognition = recognition(t0)
        forwarder.onRecognition(
            TrafficSignOrchestrationOutput(
                event = recognition,
                speedOverride = TrafficSignSpeedOverride(30, t0, "legacy", requireNotNull(recognition.roadContext)),
                passageEvent = null,
            ),
        )
        forwarder.onSpeedOverrideChanged(
            TrafficSignSpeedOverride(30, t0, "legacy", requireNotNull(recognition.roadContext)),
        )
        assertTrue(forwarded.isEmpty())

        val passage = passage()
        forwarder.onRecognition(TrafficSignOrchestrationOutput(recognition, null, passage))
        assertEquals(listOf(passage), forwarded)
    }

    @Test
    fun rawAnnotationCannotReachAuthorityCallbacks() {
        val raw = recognition(t0)
        val withheld = raw.copy(state = TrafficSignRecognitionState.NO_RECOGNITION, candidate = null)
        val authority = mutableListOf<TrafficSignRecognitionEvent>()
        val annotations = mutableListOf<TrafficSignRecognitionEvent>()
        val passages = mutableListOf<TrafficSignPassageEvent>()
        val forwarder = TrafficSignFinalizedPassageForwarder(
            submitRecognitionEvent = { event, _ -> authority += event },
            submitAnnotationEvent = { event, _ -> annotations += event },
            submitFinalizedPassage = { passages += it; true },
        )
        forwarder.onRecognition(TrafficSignOrchestrationOutput(withheld, null, annotationEvent = raw))
        assertEquals(listOf(withheld), authority)
        assertEquals(listOf(raw), annotations)
        assertTrue(passages.isEmpty())
        assertNotNull(PanoramaxTrafficSignAnnotationDraft.from(annotations.single()))
        assertNull(PanoramaxTrafficSignAnnotationDraft.from(authority.single()))
    }

    @Test
    fun productionForwarderPreservesGenerationAndSurfacesOnlyTerminalFailures() {
        val events = mutableListOf<Pair<TrafficSignRecognitionEvent, Long>>()
        val failures = mutableListOf<Pair<String, Long>>()
        val forwarder = TrafficSignFinalizedPassageForwarder(
            submitRecognitionEvent = { event, generation -> events += event to generation },
            onRuntimeUnavailable = { detail, generation -> failures += detail to generation },
            submitFinalizedPassage = { true },
        )
        val event = recognition(t0)
        forwarder.onRecognition(TrafficSignOrchestrationOutput(event, null, contextGeneration = 7))
        forwarder.onRecognition(TrafficSignOrchestrationOutput(event, null, backendFailureReason = "temporary", contextGeneration = 7))
        assertEquals(listOf(event to 7L), events)
        assertTrue(failures.isEmpty())
        forwarder.onRecognition(TrafficSignOrchestrationOutput(event, null, backendFailureReason = "stopped", terminalBackendFailure = true, contextGeneration = 8))
        assertEquals(listOf("stopped" to 8L), failures)
    }

    @Test
    fun slowDiagnosticsCannotHoldBackThePrimaryPassage() {
        val primaryDelivered = CountDownLatch(1)
        val logging = CountDownLatch(1)
        val releaseLog = CountDownLatch(1)
        val forwarder = TrafficSignFinalizedPassageForwarder(
            onInferenceDiagnostics = {
                logging.countDown()
                releaseLog.await(5, TimeUnit.SECONDS)
            },
            submitFinalizedPassage = { primaryDelivered.countDown(); true },
        )
        val output = TrafficSignOrchestrationOutput(recognition(t0), null, passage())
        val worker = Thread { forwarder.onRecognition(output) }
        try {
            worker.start()
            assertTrue(logging.await(1, TimeUnit.SECONDS))
            assertEquals("Primary delivery waited for the diagnostic sink", 0L, primaryDelivered.count)
        } finally {
            releaseLog.countDown()
            worker.join(2_000)
        }
    }

    @Test
    fun missingVerifiedBundleChecksumFailsClosed() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
        val unverified = context("100", setOf(1)).copy(bundleSha256 = null)

        val effective = resolver.commit(passage(context = unverified), bundle)

        assertEquals(EffectiveSpeedLimitSource.BUNDLE, effective.source)
        assertNull(resolver.activeAssertion())
        assertEquals(
            TrafficSignActionKind.POSTED_MAXIMUM,
            resolver.takeNewlyPersistableEvent()?.action?.kind,
        )
    }

    @Test
    fun ineligiblePassageIsDiscardedWithoutActivationOrPersistence() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val base = base(50, EffectiveSpeedLimitSource.BUNDLE)

        val effective = resolver.commit(passage().copy(overrideEligible = false), base)

        assertEquals(EffectiveSpeedLimitSource.BUNDLE, effective.source)
        assertNull(resolver.activeAssertion())
        assertNull(resolver.takeNewlyPersistableEvent())
    }

    @Test
    fun noMatchIsBoundedAndTraversalReversalClearsCamera() {
        val resolver = TrafficSignRuntimeSourceResolver(
            TrafficSignSourceResolverConfiguration(Duration.ofSeconds(3), maximumNoMatchDistanceM = 30.0),
        )
        val bundle = base(100, EffectiveSpeedLimitSource.BUNDLE)
        resolver.commit(passage(context = context("100", setOf(1))), bundle)

        assertEquals(EffectiveSpeedLimitSource.CAMERA, resolver.reconcile(
            TrafficSignRoadMatch(null, t0.plusSeconds(1), distanceFromPreviousM = 10.0),
            bundle,
        ).source)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, resolver.reconcile(
            TrafficSignRoadMatch(null, t0.plusSeconds(2), distanceFromPreviousM = 25.0),
            bundle,
        ).source)

        resolver.commit(passage(context = context("100", setOf(1))), bundle)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, resolver.reconcile(
            TrafficSignRoadMatch(context("100", setOf(1)), t0.plusSeconds(3), traversalReversed = true),
            bundle,
        ).source)
    }

    @Test
    fun noMatchBoundaryWaitsForFirstSameScopeStableRematch() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(100, EffectiveSpeedLimitSource.BUNDLE)
        val seen = context("100", setOf(7))
        val pending = passage(context = null, lastSeenContext = seen)

        assertEquals(EffectiveSpeedLimitSource.BUNDLE, resolver.commit(pending, bundle).source)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, resolver.reconcile(
            TrafficSignRoadMatch(context("101", setOf(7)), t0.plusSeconds(1), stabilized = false),
            bundle,
        ).source)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, resolver.reconcile(
            TrafficSignRoadMatch(context("101", setOf(7)), t0.plusSeconds(2)),
            bundle,
        ).source)
    }

    @Test
    fun incompatiblePendingRematchIsDiscardedWithoutPersistence() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(100, EffectiveSpeedLimitSource.BUNDLE)
        val pending = passage(context = null, lastSeenContext = context("100", setOf(7)))

        resolver.commit(pending, bundle)
        resolver.reconcile(
            TrafficSignRoadMatch(context("200", setOf(8)), t0.plusSeconds(1)),
            bundle,
        )

        assertNull(resolver.activeAssertion())
        assertNull(resolver.takeNewlyPersistableEvent())
    }

    @Test
    fun mismatchedEndPreservesOlderCameraLimitForReviewAndCityEntryResolvesToGermanFifty() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val bundle = base(70, EffectiveSpeedLimitSource.BUNDLE)
        resolver.commit(passage(context = context("100", setOf(1))), bundle)

        val ended = resolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, valueKmh = 50),
                context = context("100", setOf(1)),
                at = t0.plusSeconds(1),
            ),
            bundle,
        )
        assertEquals(EffectiveSpeedLimitSource.CAMERA, ended.source)
        assertTrue(ended.cameraEvidence)
        assertEquals(30, ended.resolution?.speedKmh)
        assertEquals(
            TrafficSignActionKind.MAXIMUM_SPEED_END,
            resolver.takeNewlyPersistableEvent()?.action?.kind,
        )

        assertEquals(
            TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
            resolveDirectAction(TrafficSignAction(TrafficSignActionKind.CITY_ENTRY, countryCode = "DEU")),
        )
    }

    @Test
    fun matchingMaximumSpeedEndUsesCityDefaultOrExplicitOsmFallback() {
        val innerCity = TrafficSignRuntimeSourceResolver()
        val base = base(70, EffectiveSpeedLimitSource.BUNDLE)
        innerCity.commit(passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 70)), base)
        val cityEnd = innerCity.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, 70), at = t0.plusSeconds(1)),
            base,
            fallbackSpeedLimitAfterEnd = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
        )
        assertEquals(50, cityEnd.resolution?.speedKmh)

        val osmFallback = TrafficSignRuntimeSourceResolver()
        osmFallback.commit(passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 70)), base)
        val wayEnd = osmFallback.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, 70), at = t0.plusSeconds(2)),
            base,
            fallbackSpeedLimitAfterEnd = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 100),
        )
        assertEquals(100, wayEnd.resolution?.speedKmh)
    }

    @Test
    fun matchingZoneEndUsesTheSamePostEndFallback() {
        val resolver = TrafficSignRuntimeSourceResolver()
        val base = base(70, EffectiveSpeedLimitSource.BUNDLE)
        resolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.ZONE_START, valueKmh = 30)),
            base,
        )
        val ended = resolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.ZONE_END), at = t0.plusSeconds(1)),
            base,
            fallbackSpeedLimitAfterEnd = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
        )
        assertEquals(50, ended.resolution?.speedKmh)
    }

    @Test
    fun typedEndsPreserveEnclosingLayersAndRejectZoneValueMismatch() {
        val bundle = base(70, EffectiveSpeedLimitSource.BUNDLE)
        val resolver = TrafficSignRuntimeSourceResolver()
        resolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.CITY_ENTRY, countryCode = "DEU"),
                at = t0,
            ),
            bundle,
        )
        resolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 30),
                at = t0.plusSeconds(1),
            ),
            bundle,
        )
        val restoredCity = resolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, valueKmh = 30),
                at = t0.plusSeconds(2),
            ),
            bundle,
        )
        assertEquals(50, restoredCity.resolution?.speedKmh)

        val zoneResolver = TrafficSignRuntimeSourceResolver()
        zoneResolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.ZONE_START, valueKmh = 30),
                at = t0.plusSeconds(3),
            ),
            bundle,
        )
        val mismatch = zoneResolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.ZONE_END, valueKmh = 50),
                at = t0.plusSeconds(4),
            ),
            bundle,
        )
        assertEquals(30, mismatch.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, mismatch.source)
        assertTrue(mismatch.cameraEvidence)
        assertEquals(TrafficSignActionKind.ZONE_START, zoneResolver.activeAssertion()?.layers?.last()?.kind)
        assertEquals(TrafficSignActionKind.ZONE_END, zoneResolver.takeNewlyPersistableEvent()?.action?.kind)
    }

    @Test
    fun pedestrianZoneEndClearsInnerPostedRuleAndRestoresOnlyVerifiedEnclosingBase() {
        fun resolverWithWalkAndInnerThirty(base: TrafficSignBaseLimit): TrafficSignRuntimeSourceResolver {
            return TrafficSignRuntimeSourceResolver().also { resolver ->
                resolver.commit(
                    passage(
                        action = TrafficSignAction(TrafficSignActionKind.PEDESTRIAN_ZONE_START),
                        at = t0,
                    ),
                    base,
                )
                resolver.commit(
                    passage(
                        action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 30),
                        at = t0.plusSeconds(1),
                    ),
                    base,
                )
            }
        }

        val verifiedBase = base(50, EffectiveSpeedLimitSource.BUNDLE).copy(structurallyVerifiedForEnd = true)
        val safe = resolverWithWalkAndInnerThirty(verifiedBase)
        val restored = safe.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.PEDESTRIAN_ZONE_END),
                at = t0.plusSeconds(2),
            ),
            verifiedBase,
        )
        assertEquals(50, restored.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, restored.source)
        assertTrue(safe.activeAssertion()?.layers.orEmpty().isEmpty())

        val unverifiedBase = base(50, EffectiveSpeedLimitSource.BUNDLE)
        val unsafe = resolverWithWalkAndInnerThirty(unverifiedBase)
        val masked = unsafe.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.PEDESTRIAN_ZONE_END),
                context = context("100", setOf(1)).copy(continuityCapable = false),
                at = t0.plusSeconds(3),
            ),
            unverifiedBase,
        )
        assertEquals(TrafficSignResolvedLimitKind.UNKNOWN, masked.resolution?.kind)
        assertEquals(EffectiveSpeedLimitSource.NONE, masked.source)
        assertTrue(masked.cameraEvidence)
        assertTrue(unsafe.activeAssertion()?.layers.orEmpty().isEmpty())
    }

    @Test
    fun roadClassExitsNeverCarryAnActivePostedCameraLimitOntoTheNewRoad() {
        listOf(
            TrafficSignActionKind.MOTORWAY_EXIT,
            TrafficSignActionKind.MOTORROAD_EXIT,
        ).forEachIndexed { index, exitKind ->
            val resolver = TrafficSignRuntimeSourceResolver()
            val unverifiedBundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
            resolver.commit(
                passage(
                    action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 70),
                    at = t0.plusSeconds(index.toLong()),
                ),
                unverifiedBundle,
            )

            val ended = resolver.commit(
                passage(
                    action = TrafficSignAction(exitKind),
                    at = t0.plusSeconds(index.toLong() + 10),
                ),
                unverifiedBundle,
            )

            assertEquals(TrafficSignResolvedLimitKind.UNKNOWN, ended.resolution?.kind)
            assertEquals(EffectiveSpeedLimitSource.NONE, ended.source)
            assertTrue(ended.cameraEvidence)
            assertTrue(resolver.activeAssertion()?.layers.orEmpty().isEmpty())
        }

        val verifiedResolver = TrafficSignRuntimeSourceResolver()
        val verifiedBundle = TrafficSignBaseLimit(
            resolution = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
            source = EffectiveSpeedLimitSource.BUNDLE,
            reason = "verified_bundle",
            structurallyVerifiedForEnd = true,
        )
        verifiedResolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 70)),
            verifiedBundle,
        )
        val restored = verifiedResolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.MOTORWAY_EXIT), at = t0.plusSeconds(20)),
            verifiedBundle,
        )
        assertEquals(50, restored.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, restored.source)
    }

    @Test
    fun conditionalEndMasksMatchingStaleCameraRuleButConditionalStartDoesNotMutate() {
        val bundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
        val resolver = TrafficSignRuntimeSourceResolver()
        resolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 70)),
            bundle,
        )

        val conditionalEnd = passage(
            action = TrafficSignAction(
                kind = TrafficSignActionKind.MAXIMUM_SPEED_END,
                valueKmh = 70,
                conditionState = TrafficSignConditionState.UNRESOLVED,
            ),
            at = t0.plusSeconds(1),
        )
        val masked = resolver.commit(conditionalEnd, bundle)
        assertEquals(TrafficSignResolvedLimitKind.UNKNOWN, masked.resolution?.kind)
        assertEquals(EffectiveSpeedLimitSource.NONE, masked.source)
        assertTrue(masked.cameraEvidence)
        assertTrue(resolver.activeAssertion()?.layers.orEmpty().isEmpty())
        assertEquals(conditionalEnd.finalizedEventId, resolver.takeNewlyPersistableEvent()?.finalizedEventId)

        val startResolver = TrafficSignRuntimeSourceResolver()
        startResolver.commit(
            passage(action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 70)),
            bundle,
        )
        val unchanged = startResolver.commit(
            passage(
                action = TrafficSignAction(
                    kind = TrafficSignActionKind.POSTED_MAXIMUM,
                    valueKmh = 30,
                    conditionState = TrafficSignConditionState.UNRESOLVED,
                ),
                at = t0.plusSeconds(2),
            ),
            bundle,
        )
        assertEquals(70, unchanged.resolution?.speedKmh)
    }

    @Test
    fun unsafeSpeedEndsMaskMatchingRulesWhileExplicitValueMismatchesPreserveThem() {
        val bundle = base(50, EffectiveSpeedLimitSource.BUNDLE)
        val safeContext = context("100", setOf(1))
        val unsafeContexts = listOf(
            safeContext.copy(travelDirection = TrafficSignTravelDirection.UNKNOWN),
            safeContext.copy(continuityCapable = false),
            safeContext.copy(matchedWayStable = false),
            safeContext.copy(bundleSha256 = null),
        )
        unsafeContexts.forEachIndexed { index, unsafeContext ->
            val resolver = TrafficSignRuntimeSourceResolver()
            resolver.commit(
                passage(
                    action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 70),
                    context = safeContext,
                    at = t0.plusSeconds(index.toLong()),
                ),
                bundle,
            )
            resolver.takeNewlyActivatedEvent()
            resolver.takeNewlyPersistableEvent()

            val masked = resolver.commit(
                passage(
                    action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END),
                    context = unsafeContext,
                    at = t0.plusSeconds(index.toLong() + 10),
                ),
                bundle,
            )
            assertEquals(TrafficSignResolvedLimitKind.UNKNOWN, masked.resolution?.kind)
            assertEquals(EffectiveSpeedLimitSource.NONE, masked.source)
            assertTrue(masked.cameraEvidence)
            assertTrue(resolver.activeAssertion()?.layers.orEmpty().isEmpty())
        }

        val maximumResolver = TrafficSignRuntimeSourceResolver()
        maximumResolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, valueKmh = 70),
                context = safeContext,
            ),
            bundle,
        )
        maximumResolver.takeNewlyActivatedEvent()
        maximumResolver.takeNewlyPersistableEvent()
        val maximumMismatchEvent = passage(
            action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, valueKmh = 50),
            context = safeContext.copy(travelDirection = TrafficSignTravelDirection.UNKNOWN),
            at = t0.plusSeconds(20),
        )
        val maximumMismatch = maximumResolver.commit(maximumMismatchEvent, bundle)
        assertEquals(70, maximumMismatch.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, maximumMismatch.source)
        assertNull(maximumResolver.takeNewlyActivatedEvent())
        assertEquals(maximumMismatchEvent.finalizedEventId, maximumResolver.takeNewlyPersistableEvent()?.finalizedEventId)

        val zoneResolver = TrafficSignRuntimeSourceResolver()
        zoneResolver.commit(
            passage(
                action = TrafficSignAction(TrafficSignActionKind.ZONE_START, valueKmh = 30),
                context = safeContext,
            ),
            bundle,
        )
        zoneResolver.takeNewlyActivatedEvent()
        zoneResolver.takeNewlyPersistableEvent()
        val zoneMismatchEvent = passage(
            action = TrafficSignAction(TrafficSignActionKind.ZONE_END, valueKmh = 50),
            context = safeContext.copy(continuityCapable = false),
            at = t0.plusSeconds(21),
        )
        val zoneMismatch = zoneResolver.commit(zoneMismatchEvent, bundle)
        assertEquals(30, zoneMismatch.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.CAMERA, zoneMismatch.source)
        assertNull(zoneResolver.takeNewlyActivatedEvent())
        assertEquals(zoneMismatchEvent.finalizedEventId, zoneResolver.takeNewlyPersistableEvent()?.finalizedEventId)
    }

    private fun recognition(
        at: Instant,
        trackId: String = "physical-1",
        confidence: Double = 0.95,
        speedKmh: Int = 30,
        source: TrafficSignInputSource = TrafficSignInputSource.LIVE_FRAME,
    ) = TrafficSignRecognitionEvent(
        schemaVersion = 1,
        packId = "pack-v1",
        artifactSha256 = "a".repeat(64),
        preprocessingVersion = "rgb-v1",
        source = source,
        frameTimestampUtc = at,
        state = TrafficSignRecognitionState.CONFIRMED,
        candidate = TrafficSignCandidate(
            rawClassId = "speed_limit_$speedKmh",
            rawLabel = "$speedKmh",
            semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, speedKmh, "km/h"),
            rawScore = confidence,
            calibratedConfidence = confidence,
            boundingBox = NormalizedTrafficSignBoundingBox(0.7, 0.1, 0.1, 0.2),
            trackId = trackId,
            evidenceFrames = 2,
        ),
        roadContext = context("100", setOf(1)),
        latencyMs = 12.0,
        thermalState = null,
        frameId = "frame-${at.toEpochMilli()}",
        driveSessionId = "drive-test",
        calibrationId = "calibration-test",
        componentRole = "direct_detector",
        modelComponents = listOf(
            TrafficSignModelComponentLineage(
                role = "direct_detector",
                artifactSha256 = "a".repeat(64),
                preprocessingVersion = "rgb-v1",
                calibrationId = "calibration-test",
            ),
        ),
    )

    private fun missing(at: Instant) = recognition(at).copy(
        state = TrafficSignRecognitionState.NO_RECOGNITION,
        candidate = null,
    )

    private fun passage(
        action: TrafficSignAction = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 30),
        context: TrafficSignDetectionContext? = context("100", setOf(1)),
        lastSeenContext: TrafficSignDetectionContext? = context ?: context("100", setOf(1)),
        at: Instant = t0,
    ) = TrafficSignPassageEvent(
        finalizedEventId = "event-${action.kind.wireValue}-${at.toEpochMilli()}",
        driveSessionId = "drive-test",
        generation = 1,
        packId = "pack-v1",
        artifactSha256 = "a".repeat(64),
        preprocessingVersion = "rgb-v1",
        calibrationId = "calibration-test",
        componentRole = "direct_detector",
        modelComponents = listOf(
            TrafficSignModelComponentLineage(
                role = "direct_detector",
                artifactSha256 = "a".repeat(64),
                preprocessingVersion = "rgb-v1",
                calibrationId = "calibration-test",
            ),
        ),
        physicalTrackId = "track-${at.toEpochMilli()}",
        assemblyId = null,
        assemblyIds = listOf("assembly-${at.toEpochMilli()}"),
        action = action,
        resolution = resolveDirectAction(action),
        firstSeenAtUtc = at.minusSeconds(1),
        lastSeenAtUtc = at.minusMillis(100),
        firstSeenContext = lastSeenContext,
        lastSeenContext = lastSeenContext,
        passageBoundary = TrafficSignPassageBoundary(at, context),
        activationContext = context,
        initialRouteRelationGroupIds = lastSeenContext?.routeRelationGroupIds.orEmpty(),
        eligibleRouteRelationGroupIds = lastSeenContext?.routeRelationGroupIds.orEmpty(),
        sourceRelationIds = lastSeenContext?.sourceRelationIds.orEmpty(),
        evidence = listOf(
            TrafficSignPassageFrameEvidence(
                frameId = "seen-${at.toEpochMilli()}",
                timestampUtc = at.minusSeconds(1),
                rawScore = 0.9,
                calibratedConfidence = 0.88,
                accumulatedSupport = 0.91,
                boundingBox = NormalizedTrafficSignBoundingBox(0.7, 0.1, 0.1, 0.2),
            ),
        ),
        lossEvidence = listOf(
            TrafficSignPassageLossEvidence(
                frameId = "missing-${at.toEpochMilli()}",
                timestampUtc = at,
                strongPassGeometry = false,
            ),
        ),
        framesSeen = 1,
        finalConfidence = 0.88,
        finalAccumulatedSupport = 0.91,
        peakConsecutiveFramesSeen = 1,
        lossReason = "consecutive_analyzed_misses",
        negativeFramesToCommit = 1,
        overrideEligible = true,
    )

    private fun context(wayId: String, groups: Set<Int>) = TrafficSignDetectionContext(
        wayId = wayId,
        latitude = 49.0,
        longitude = 8.4,
        headingDegrees = 90.0,
        travelDirection = TrafficSignTravelDirection.FORWARD,
        sourceSignature = TrafficSignRuntimeSourceSignature("bundle-v1|way:$wayId|maxspeed:50", "local-v1"),
        bundleSha256 = "a".repeat(64),
        routeRelationGroupIds = groups.map(Int::toLong).toSet(),
        sourceRelationIds = groups.map { it.toLong() + 9_000L }.toSet(),
        continuityCapable = true,
        traversalEpoch = 1,
    )

    private fun base(speed: Int, source: EffectiveSpeedLimitSource) = TrafficSignBaseLimit(
        resolution = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, speed),
        source = source,
        reason = source.wireValue,
    )
}

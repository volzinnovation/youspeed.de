package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import java.util.ArrayDeque
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignRecognitionOrchestratorTests {
    @Test
    fun frameTimeRoadContextSurvivesAsynchronousLiveAndStillInference() {
        val harness = Harness()
        val acceptedContext = context(
            wayId = "way-accepted",
            latitude = 49.0069,
            longitude = 8.4037,
            heading = 87.5,
            direction = TrafficSignTravelDirection.FORWARD,
            signature = signature("bundle-a", "local-a"),
        )
        harness.context = acceptedContext
        val live = harness.frame("live-1", TrafficSignInputSource.LIVE_FRAME, capturedAtNanos = 0L)

        assertTrue(harness.orchestrator.submit(live))
        assertEquals(listOf("live-1"), harness.backend.activeFrameIds())

        // Navigation moves while inference is still outstanding. The event
        // must retain the coherent snapshot taken when live-1 was accepted.
        harness.context = context(
            wayId = "way-later",
            latitude = 50.0,
            longitude = 9.0,
            heading = 240.0,
            direction = TrafficSignTravelDirection.REVERSE,
            signature = signature("bundle-a", "local-a"),
        )
        harness.clockNanos = 40_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))

        val liveEvent = harness.observer.outputs.single().event
        assertEquals(acceptedContext, liveEvent.roadContext)
        assertEquals("way-accepted", liveEvent.roadContext?.wayId)
        assertEquals(49.0069, liveEvent.roadContext?.latitude ?: 0.0, 0.0)
        assertEquals(8.4037, liveEvent.roadContext?.longitude ?: 0.0, 0.0)
        assertEquals(87.5, liveEvent.roadContext?.headingDegrees ?: 0.0, 0.0)
        assertEquals(TrafficSignTravelDirection.FORWARD, liveEvent.roadContext?.travelDirection)
        assertEquals(TrafficSignInputSource.LIVE_FRAME, liveEvent.source)
        assertEquals(1, live.releaseCount)

        harness.clockNanos = 500_000_000L
        val still = harness.frame("still-1", TrafficSignInputSource.CAMERA_STILL, capturedAtNanos = 500_000_000L)
        assertTrue(harness.orchestrator.submit(still))
        harness.clockNanos = 530_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))

        assertEquals(TrafficSignInputSource.CAMERA_STILL, harness.observer.outputs.last().event.source)
        assertEquals(harness.context, harness.observer.outputs.last().event.roadContext)
        assertEquals(1, still.releaseCount)
    }

    @Test
    fun oneInferenceRunsWhileOnlyTheLatestPendingFrameIsRetained() {
        val harness = Harness()
        val first = harness.frame("first", capturedAtNanos = 0L)
        val replaced = harness.frame("replaced", capturedAtNanos = 100_000_000L)
        val latest = harness.frame("latest", capturedAtNanos = 200_000_000L)

        assertTrue(harness.orchestrator.submit(first))
        harness.clockNanos = 100_000_000L
        assertTrue(harness.orchestrator.submit(replaced))
        harness.clockNanos = 200_000_000L
        assertTrue(harness.orchestrator.submit(latest))

        assertEquals(listOf("first"), harness.backend.activeFrameIds())
        assertEquals(1, replaced.releaseCount)
        assertEquals(0, latest.releaseCount)

        harness.clockNanos = 600_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        assertEquals(listOf("latest"), harness.backend.activeFrameIds())
        assertEquals(1, first.releaseCount)

        harness.clockNanos = 640_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        assertEquals(1, latest.releaseCount)
        assertEquals(2, harness.observer.outputs.size)
        assertEquals(
            listOf(
                Instant.parse("2026-09-01T10:00:00Z"),
                Instant.parse("2026-09-01T10:00:00.200Z"),
            ),
            harness.observer.outputs.map { it.event.frameTimestampUtc },
        )
    }

    @Test
    fun confirmedDetectionOverridesBothSourcesUntilSourceSignatureChanges() {
        val harness = Harness()
        val source = signature("bundle-current-way", "local-current-way")
        harness.context = context(
            wayId = "4711",
            latitude = 49.0123,
            longitude = 8.4567,
            heading = 92.0,
            direction = TrafficSignTravelDirection.FORWARD,
            signature = source,
        )

        repeat(3) { index ->
            harness.clockNanos = index * 500_000_000L
            assertTrue(
                harness.orchestrator.submit(
                    harness.frame("confirmation-$index", capturedAtNanos = harness.clockNanos),
                ),
            )
            harness.clockNanos += 35_000_000L
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        }

        val confirmed = harness.observer.outputs.last()
        assertEquals(TrafficSignRecognitionState.CONFIRMED, confirmed.event.state)
        assertEquals("4711", confirmed.event.roadContext?.wayId)
        assertNull(confirmed.speedOverride)
        harness.clockNanos = 1_500_000_000L
        harness.orchestrator.submit(harness.frame("passed", capturedAtNanos = harness.clockNanos))
        harness.clockNanos += 35_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        harness.clockNanos = 2_000_000_000L
        harness.orchestrator.submit(harness.frame("passed-confirmed", capturedAtNanos = harness.clockNanos))
        harness.clockNanos += 35_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        assertEquals(30, harness.observer.outputs.last().passageEvent?.resolution?.speedKmh)
        assertEquals(30, harness.observer.outputs.last().speedOverride?.speedKmh)
        assertEquals(30, harness.orchestrator.effectiveSpeedKmh(localCorrectionKmh = 50, bundledMapKmh = 70))

        val retained = harness.orchestrator.speedOverride()
        harness.orchestrator.reconcileSource(source.copy(), harness.contextGeneration)
        assertSame(retained, harness.orchestrator.speedOverride())
        assertEquals(30, harness.orchestrator.effectiveSpeedKmh(localCorrectionKmh = 50, bundledMapKmh = 70))

        harness.contextGeneration += 1
        harness.orchestrator.reconcileSource(
            signature("bundle-next-way", "local-next-way"),
            harness.contextGeneration,
        )
        assertNull(harness.orchestrator.speedOverride())
        assertEquals(50, harness.orchestrator.effectiveSpeedKmh(localCorrectionKmh = 50, bundledMapKmh = 70))
    }

    @Test
    fun calibratedPackNeverFallsBackToRawBackendScore() {
        val harness = Harness()
        val rawOnly = detection().copy(
            candidate = detection().candidate.copy(
                rawScore = 0.99,
                calibratedConfidence = null,
            ),
        )

        harness.orchestrator.submit(harness.frame("raw-only", capturedAtNanos = 0L))
        harness.clockNanos = 20_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(rawOnly))

        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, harness.observer.outputs.single().event.state)
        assertNull(harness.observer.outputs.single().event.candidate)
        assertNull(harness.orchestrator.speedOverride())
    }

    @Test
    fun stationaryContextCannotArmOrFinalizeAuthoritativePassage() {
        val harness = Harness()
        harness.runtimeActivationEligible = false
        repeat(3) { index ->
            harness.clockNanos = index * 500_000_000L
            harness.orchestrator.submit(harness.frame("stationary-$index", capturedAtNanos = harness.clockNanos))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        }
        repeat(3) { index ->
            harness.clockNanos += 500_000_000L
            harness.orchestrator.submit(harness.frame("stationary-miss-$index", capturedAtNanos = harness.clockNanos))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        }

        assertTrue(harness.observer.outputs.none { it.passageEvent != null })
        assertNull(harness.orchestrator.speedOverride())
    }

    @Test
    fun delayedResultFromAnOlderSourceCannotOverrideTheNewSource() {
        val harness = Harness()
        harness.context = context(signature = signature("bundle-old", null))
        val old = harness.frame("old", capturedAtNanos = 0L)
        harness.orchestrator.submit(old)

        harness.contextGeneration += 1
        harness.orchestrator.reconcileSource(
            signature("bundle-new", null),
            harness.contextGeneration,
        )
        harness.clockNanos = 25_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))

        val output = harness.observer.outputs.single()
        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, output.event.state)
        assertEquals("bundle-old", output.event.roadContext?.sourceSignature?.osmRevision)
        assertNull(output.speedOverride)
        assertEquals(1, old.releaseCount)
    }

    @Test
    fun inFlightResultCannotAdoptRelationsFromALaterUnrelatedSameGenerationContext() {
        val harness = Harness()
        harness.context = context(wayId = "way-x").copy(
            routeRelationGroupIds = setOf(1L),
            sourceRelationIds = setOf(9_001L),
        )
        val oldFrame = harness.frame("old-way-x", capturedAtNanos = 0L)
        assertTrue(harness.orchestrator.submit(oldFrame))

        // Map matching leaves relation 1 without advancing the TSR setting
        // generation. The accepted X frame must retain its own {1} scope and
        // reset epoch rather than validating against Z's replacement {2}.
        harness.context = context(wayId = "way-z").copy(
            routeRelationGroupIds = setOf(2L),
            sourceRelationIds = setOf(9_002L),
        )
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)
        harness.clockNanos = 25_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))

        val staleOutput = harness.observer.outputs.single()
        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, staleOutput.event.state)
        assertNull(staleOutput.event.candidate)
        assertNull(staleOutput.passageEvent)
        assertNull(harness.orchestrator.speedOverride())

        harness.clockNanos = 500_000_000L
        assertTrue(harness.orchestrator.submit(harness.frame("missing-way-z", capturedAtNanos = harness.clockNanos)))
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null, strongPassGeometry = true))
        assertNull(harness.observer.outputs.last().passageEvent)
        assertEquals(1, oldFrame.releaseCount)
    }

    @Test
    fun sameRoadFixRetainsOverrideButWayOrDirectionChangeClearsIt() {
        val harness = Harness()
        val source = signature("bundle-v1|way:4711|direction:forward", "local-v1")
        harness.context = context(
            wayId = "4711",
            direction = TrafficSignTravelDirection.FORWARD,
            signature = source,
        )
        repeat(3) { index ->
            harness.clockNanos = index * 500_000_000L
            harness.orchestrator.submit(
                harness.frame("confirm-$index", capturedAtNanos = harness.clockNanos),
            )
            harness.clockNanos += 20_000_000L
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        }
        harness.clockNanos = 1_500_000_000L
        harness.orchestrator.submit(harness.frame("confirm-passed", capturedAtNanos = harness.clockNanos))
        harness.clockNanos += 20_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        harness.clockNanos = 2_000_000_000L
        harness.orchestrator.submit(harness.frame("confirm-passed-confirmed", capturedAtNanos = harness.clockNanos))
        harness.clockNanos += 20_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        val confirmed = requireNotNull(harness.orchestrator.speedOverride())

        harness.orchestrator.reconcileContext(
            harness.context.copy(latitude = 49.01, longitude = 8.41, headingDegrees = 91.0),
            harness.contextGeneration,
        )
        assertSame(confirmed, harness.orchestrator.speedOverride())

        harness.contextGeneration += 1
        harness.orchestrator.reconcileContext(
            harness.context.copy(
                headingDegrees = 271.0,
                travelDirection = TrafficSignTravelDirection.REVERSE,
            ),
            harness.contextGeneration,
        )
        assertNull(harness.orchestrator.speedOverride())
        assertEquals(50, harness.orchestrator.effectiveSpeedKmh(50, 70))
    }

    @Test
    fun delayedResultFromPreviousDirectionIsRejectedEvenWithEqualSourceSignature() {
        val harness = Harness()
        val source = signature("bundle-v1", "local-v1")
        harness.context = context(
            wayId = "4711",
            heading = 90.0,
            direction = TrafficSignTravelDirection.FORWARD,
            signature = source,
        )
        harness.orchestrator.submit(harness.frame("forward", capturedAtNanos = 0L))

        harness.context = harness.context.copy(
            headingDegrees = 270.0,
            travelDirection = TrafficSignTravelDirection.REVERSE,
        )
        harness.contextGeneration += 1
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)
        harness.clockNanos = 25_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))

        val output = harness.observer.outputs.single()
        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, output.event.state)
        assertEquals(TrafficSignTravelDirection.FORWARD, output.event.roadContext?.travelDirection)
        assertNull(output.speedOverride)
    }

    @Test
    fun unknownToKnownDirectionOnSameWayDoesNotDiscardArmedPassage() {
        val harness = Harness()
        harness.context = context(direction = TrafficSignTravelDirection.UNKNOWN)
        repeat(3) { index ->
            harness.clockNanos = index * 500_000_000L
            harness.orchestrator.submit(harness.frame("unknown-$index", capturedAtNanos = harness.clockNanos))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        }

        harness.context = harness.context.copy(travelDirection = TrafficSignTravelDirection.FORWARD)
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)
        repeat(2) { index ->
            harness.clockNanos += 500_000_000L
            harness.orchestrator.submit(harness.frame("known-miss-$index", capturedAtNanos = harness.clockNanos))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        }

        assertEquals(30, harness.observer.outputs.last().passageEvent?.resolution?.speedKmh)
    }

    @Test
    fun unknownDirectionGapCannotHideSameWayReversalOfArmedTrack() {
        val harness = Harness()
        val highConfidence = detection().let { detection ->
            detection.copy(candidate = detection.candidate.copy(rawScore = 0.98, calibratedConfidence = 0.98))
        }
        harness.context = context(
            wayId = "4711",
            direction = TrafficSignTravelDirection.FORWARD,
        )
        repeat(2) { index ->
            harness.clockNanos = index * 500_000_000L
            assertTrue(harness.orchestrator.submit(harness.frame("forward-seen-$index", capturedAtNanos = harness.clockNanos)))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(highConfidence))
        }

        harness.context = harness.context.copy(
            headingDegrees = 100.0,
            travelDirection = TrafficSignTravelDirection.UNKNOWN,
        )
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)
        harness.context = harness.context.copy(
            headingDegrees = 270.0,
            travelDirection = TrafficSignTravelDirection.REVERSE,
        )
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)

        harness.clockNanos = 1_000_000_000L
        assertTrue(harness.orchestrator.submit(harness.frame("reverse-missing", capturedAtNanos = harness.clockNanos)))
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null, strongPassGeometry = true))

        assertTrue(harness.observer.outputs.none { it.passageEvent != null })
        assertNull(harness.orchestrator.speedOverride())
    }

    @Test
    fun noMatchAcquisitionAdoptsFirstMatchedScopeAndPassesOnRelatedWay() {
        val harness = Harness()
        val highConfidence = detection().let { detection ->
            detection.copy(
                candidate = detection.candidate.copy(
                    rawScore = 0.99,
                    calibratedConfidence = 0.99,
                ),
            )
        }
        harness.context = context(wayId = "unused").copy(
            wayId = null,
            routeRelationGroupIds = emptySet(),
            sourceRelationIds = emptySet(),
            matchedWayStable = false,
        )
        harness.orchestrator.submit(harness.frame("visible-no-match", capturedAtNanos = 0L))
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(highConfidence))

        harness.clockNanos = 500_000_000L
        harness.context = context(wayId = "way-b").copy(
            routeRelationGroupIds = setOf(7L),
            sourceRelationIds = setOf(70L),
        )
        harness.orchestrator.submit(harness.frame("visible-way-b", capturedAtNanos = harness.clockNanos))
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(highConfidence))

        harness.clockNanos = 1_000_000_000L
        harness.context = context(wayId = "way-c").copy(
            routeRelationGroupIds = setOf(7L),
            sourceRelationIds = setOf(70L),
        )
        harness.orchestrator.submit(harness.frame("missing-way-c", capturedAtNanos = harness.clockNanos))
        harness.backend.completeNext(
            TrafficSignBackendResult.Recognition(
                detection = null,
                strongPassGeometry = true,
            ),
        )

        val passage = requireNotNull(harness.observer.outputs.last().passageEvent)
        assertEquals("way-b", passage.firstSeenContext?.wayId)
        assertEquals(setOf(7L), passage.initialRouteRelationGroupIds)
        assertEquals(setOf(7L), passage.eligibleRouteRelationGroupIds)
        assertEquals("way-c", passage.activationContext?.wayId)
        assertEquals(30, passage.resolution.speedKmh)
    }

    @Test
    fun promotedAdjacentTrackUsesItsOwnRecognitionScopeInsteadOfPriorTracksIntersection() {
        val harness = Harness()
        fun scopedContext(wayId: String, groups: Set<Long>) = context(wayId = wayId).copy(
            routeRelationGroupIds = groups,
            sourceRelationIds = groups.map { it + 9_000L }.toSet(),
        )
        fun highConfidenceDetection(speedKmh: Int): TrafficSignDetection = detection().let { detection ->
            detection.copy(
                candidate = detection.candidate.copy(
                    rawClassId = "speed_limit_$speedKmh",
                    rawLabel = "Maximum speed $speedKmh",
                    semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, speedKmh, "km/h"),
                    rawScore = 0.98,
                    calibratedConfidence = 0.98,
                ),
            )
        }
        fun submitRecognition(frameId: String, atNanos: Long, speedKmh: Int) {
            harness.clockNanos = atNanos
            assertTrue(harness.orchestrator.submit(harness.frame(frameId, capturedAtNanos = atNanos)))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(highConfidenceDetection(speedKmh)))
        }

        harness.context = scopedContext("way-x", setOf(1L))
        submitRecognition("a-x", 0L, 30)
        harness.context = scopedContext("way-y", setOf(1L, 2L))
        submitRecognition("a-y", 500_000_000L, 30)

        // B is a different supported sign. Its first Y frame counts as loss
        // for A while B starts an independent queued track rooted in {1,2}.
        submitRecognition("b-y-1", 1_000_000_000L, 50)
        submitRecognition("b-y-2", 1_500_000_000L, 50)
        val firstPassage = requireNotNull(harness.observer.outputs.last().passageEvent)
        assertEquals(30, firstPassage.action.valueKmh)
        assertEquals(setOf(1L), firstPassage.eligibleRouteRelationGroupIds)

        // Losing B on Z/{2} must use B's {1,2} origin, not A's {1} scope.
        harness.context = scopedContext("way-z", setOf(2L))
        harness.clockNanos = 2_000_000_000L
        assertTrue(harness.orchestrator.submit(harness.frame("b-missing-z", capturedAtNanos = harness.clockNanos)))
        harness.backend.completeNext(
            TrafficSignBackendResult.Recognition(
                detection = null,
                strongPassGeometry = true,
            ),
        )

        val promotedPassage = requireNotNull(harness.observer.outputs.last().passageEvent)
        assertEquals(50, promotedPassage.action.valueKmh)
        assertEquals("way-y", promotedPassage.firstSeenContext?.wayId)
        assertEquals(setOf(1L, 2L), promotedPassage.initialRouteRelationGroupIds)
        assertEquals(setOf(2L), promotedPassage.eligibleRouteRelationGroupIds)
        assertEquals("way-z", promotedPassage.activationContext?.wayId)
    }

    @Test
    fun queuedAdjacentTrackSurvivesOwnRelationBeforeOldTrackFinishesDebounce() {
        val harness = Harness()
        fun scopedContext(wayId: String, groups: Set<Long>) = context(wayId = wayId).copy(
            routeRelationGroupIds = groups,
            sourceRelationIds = groups.map { it + 9_000L }.toSet(),
        )
        fun recognized(speedKmh: Int) = detection().let { detection ->
            detection.copy(
                candidate = detection.candidate.copy(
                    rawClassId = "speed_limit_$speedKmh",
                    rawLabel = "Maximum speed $speedKmh",
                    semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, speedKmh, "km/h"),
                    rawScore = 0.98,
                    calibratedConfidence = 0.98,
                ),
            )
        }
        fun submit(frameId: String, nanos: Long, speedKmh: Int) {
            harness.clockNanos = nanos
            assertTrue(harness.orchestrator.submit(harness.frame(frameId, capturedAtNanos = nanos)))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(recognized(speedKmh)))
        }

        harness.context = scopedContext("way-x", setOf(1L))
        submit("a-x-1", 0L, 30)
        submit("a-x-2", 500_000_000L, 30)
        harness.context = scopedContext("way-y", setOf(1L, 2L))
        submit("b-y-1", 1_000_000_000L, 50)
        assertTrue(harness.observer.outputs.none { it.passageEvent != null })

        // A is still one negative short of committing. Moving onto relation 2
        // drops A but promotes B using B's independent {1,2} origin.
        harness.context = scopedContext("way-z", setOf(2L))
        submit("b-z-2", 1_500_000_000L, 50)
        harness.clockNanos = 2_000_000_000L
        assertTrue(harness.orchestrator.submit(harness.frame("b-missing-z", capturedAtNanos = harness.clockNanos)))
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null, strongPassGeometry = true))

        val passages = harness.observer.outputs.mapNotNull { it.passageEvent }
        assertEquals(1, passages.size)
        assertEquals(50, passages.single().action.valueKmh)
        assertEquals("way-y", passages.single().firstSeenContext?.wayId)
        assertEquals(setOf(1L, 2L), passages.single().initialRouteRelationGroupIds)
        assertEquals(setOf(2L), passages.single().eligibleRouteRelationGroupIds)
        assertEquals("way-z", passages.single().activationContext?.wayId)
    }

    @Test
    fun firstStableRematchAfterNoMatchMustBelongToKnownTracksFrozenScope() {
        val harness = Harness()
        fun scopedContext(wayId: String, groups: Set<Long>) = context(wayId = wayId).copy(
            routeRelationGroupIds = groups,
            sourceRelationIds = groups.map { it + 9_000L }.toSet(),
        )
        val highConfidence = detection().let { detection ->
            detection.copy(candidate = detection.candidate.copy(rawScore = 0.98, calibratedConfidence = 0.98))
        }
        harness.context = scopedContext("way-x", setOf(1L))
        repeat(2) { index ->
            harness.clockNanos = index * 500_000_000L
            assertTrue(harness.orchestrator.submit(harness.frame("x-seen-$index", capturedAtNanos = harness.clockNanos)))
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(highConfidence))
        }

        harness.context = harness.context.copy(
            wayId = null,
            routeRelationGroupIds = emptySet(),
            sourceRelationIds = emptySet(),
            matchedWayStable = false,
        )
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)

        harness.context = scopedContext("way-z", setOf(2L))
        harness.orchestrator.reconcileContext(harness.context, harness.contextGeneration)
        harness.clockNanos = 1_000_000_000L
        assertTrue(harness.orchestrator.submit(harness.frame("z-missing", capturedAtNanos = harness.clockNanos)))
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null, strongPassGeometry = true))

        assertTrue(harness.observer.outputs.none { it.passageEvent != null })
        assertNull(harness.orchestrator.speedOverride())
    }

    @Test
    fun staleSnapshotCannotRollBackAnExplicitlyReconciledContextGeneration() {
        val harness = Harness()
        val nextSource = signature("bundle-v2", "local-v2")
        harness.orchestrator.reconcileSource(nextSource, contextGeneration = 1L)
        val staleFrame = harness.frame("stale-context", capturedAtNanos = 0L)

        assertEquals(false, harness.orchestrator.submit(staleFrame))
        assertEquals(1, staleFrame.releaseCount)
        assertTrue(harness.backend.activeFrameIds().isEmpty())
        assertNull(harness.orchestrator.speedOverride())
    }

    @Test
    fun closePublishesRemovalOfTheSessionScopedOverride() {
        val harness = Harness()
        repeat(3) { index ->
            harness.clockNanos = index * 500_000_000L
            harness.orchestrator.submit(
                harness.frame("close-$index", capturedAtNanos = harness.clockNanos),
            )
            harness.clockNanos += 20_000_000L
            harness.backend.completeNext(TrafficSignBackendResult.Recognition(detection()))
        }
        harness.clockNanos = 1_500_000_000L
        harness.orchestrator.submit(harness.frame("close-passed", capturedAtNanos = harness.clockNanos))
        harness.clockNanos += 20_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        harness.clockNanos = 2_000_000_000L
        harness.orchestrator.submit(harness.frame("close-passed-confirmed", capturedAtNanos = harness.clockNanos))
        harness.clockNanos += 20_000_000L
        harness.backend.completeNext(TrafficSignBackendResult.Recognition(null))
        assertEquals(30, harness.orchestrator.speedOverride()?.speedKmh)

        harness.orchestrator.close()

        assertNull(harness.orchestrator.speedOverride())
        assertNull(harness.observer.overrideChanges.last())
        assertEquals(50, harness.orchestrator.effectiveSpeedKmh(50, 70))
    }

    private class Harness {
        val pack: TrafficSignModelPack = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)
        val backend = FakeBackend()
        val observer = RecordingObserver()
        var clockNanos = 0L
        var context = context()
        var contextGeneration = 0L
        var runtimeActivationEligible = true
        val orchestrator = TrafficSignRecognitionOrchestrator(
            modelPack = pack,
            runtimeArtifact = requireNotNull(pack.androidArtifact()),
            backend = backend,
            contextSnapshot = TrafficSignDetectionContextSnapshot {
                TrafficSignDetectionContextSnapshotValue(
                    context,
                    contextGeneration,
                    runtimeActivationEligible,
                    driveSessionId = "drive-test",
                )
            },
            conditionsSnapshot = { TrafficSignAnalysisConditions() },
            monotonicClockNanos = { clockNanos },
            observer = observer,
        )

        fun frame(
            id: String,
            source: TrafficSignInputSource = TrafficSignInputSource.LIVE_FRAME,
            capturedAtNanos: Long,
        ) = FakeFrame(
            frameId = id,
            source = source,
            capturedAtUtc = Instant.parse("2026-09-01T10:00:00Z").plusNanos(capturedAtNanos),
            capturedAtMonotonicNanos = capturedAtNanos,
        )
    }

    private class FakeBackend : TrafficSignRecognitionBackend<FakeFrame> {
        private val pending = ArrayDeque<Pair<FakeFrame, (TrafficSignBackendResult) -> Unit>>()

        override fun recognize(frame: FakeFrame, completion: (TrafficSignBackendResult) -> Unit) {
            pending.addLast(frame to completion)
        }

        fun activeFrameIds(): List<String> = pending.map { it.first.frameId }

        fun completeNext(result: TrafficSignBackendResult) {
            val (_, completion) = pending.removeFirst()
            completion(result)
        }
    }

    private class FakeFrame(
        override val frameId: String,
        override val source: TrafficSignInputSource,
        override val capturedAtUtc: Instant,
        override val capturedAtMonotonicNanos: Long,
        override val widthPixels: Int = 960,
        override val heightPixels: Int = 540,
    ) : TrafficSignNormalizedFrameHandle {
        var releaseCount = 0
            private set

        override fun release() {
            releaseCount += 1
        }
    }

    private class RecordingObserver : TrafficSignRecognitionObserver {
        val outputs = mutableListOf<TrafficSignOrchestrationOutput>()
        val overrideChanges = mutableListOf<TrafficSignSpeedOverride?>()

        override fun onRecognition(output: TrafficSignOrchestrationOutput) {
            outputs += output
        }

        override fun onSpeedOverrideChanged(current: TrafficSignSpeedOverride?) {
            overrideChanges += current
        }
    }

    private companion object {
        fun detection() = TrafficSignDetection(
            candidate = TrafficSignCandidate(
                rawClassId = "speed_limit_30",
                rawLabel = "Maximum speed 30",
                semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h"),
                rawScore = 0.91,
                calibratedConfidence = 0.86,
                boundingBox = NormalizedTrafficSignBoundingBox(0.70, 0.15, 0.08, 0.12),
            ),
            cropQuality = 0.8,
        )

        fun context(
            wayId: String = "way-1",
            latitude: Double = 49.0,
            longitude: Double = 8.4,
            heading: Double = 82.0,
            direction: TrafficSignTravelDirection = TrafficSignTravelDirection.FORWARD,
            signature: TrafficSignRuntimeSourceSignature = signature("bundle-v1", "local-v1"),
        ) = TrafficSignDetectionContext(
            wayId = wayId,
            latitude = latitude,
            longitude = longitude,
            headingDegrees = heading,
            travelDirection = direction,
            sourceSignature = signature,
            bundleSha256 = "a".repeat(64),
            routeRelationGroupIds = setOf(1L),
            sourceRelationIds = setOf(9_001L),
            continuityCapable = true,
            traversalEpoch = 1L,
        )

        fun signature(osm: String, local: String?) = TrafficSignRuntimeSourceSignature(
            osmRevision = osm,
            localCorrectionRevision = local,
        )

        fun fixture(name: String): File {
            val candidates = listOf(
                File("shared/tsr/fixtures/$name"),
                File("../shared/tsr/fixtures/$name"),
                File("../../shared/tsr/fixtures/$name"),
            )
            return candidates.firstOrNull(File::exists)
                ?: error("Unable to locate shared TSR fixture $name from ${System.getProperty("user.dir")}")
        }
    }
}

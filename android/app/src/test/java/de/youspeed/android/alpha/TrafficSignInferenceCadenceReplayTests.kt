package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Replays synthetic timings representative of the slow Android camera lane, without location data. */
class TrafficSignInferenceCadenceReplayTests {
    @Test
    fun multiSecondInferencePreventsRepeatedSpeedSignsFromReachingPassageConfirmation() {
        val replay = Replay()

        replay.analyze(0, 2_800, detection(0.87))
        replay.analyze(2_900, 2_800, detection(0.90))
        replay.analyze(5_800, 2_800, null)
        replay.analyze(8_700, 2_800, null)
        replay.analyze(11_600, 2_800, null)

        val sightings = replay.outputs.take(2)
        assertTrue(sightings.all { it.event.state == TrafficSignRecognitionState.PROVISIONAL })
        assertTrue(sightings.all { it.event.candidate?.evidenceFrames == 1 })
        assertNotEquals(sightings[0].event.candidate?.trackId, sightings[1].event.candidate?.trackId)
        // Recognition and presentation are alive: confidence expires before the
        // next sighting, while the unchanged context and classifier remain valid.
        assertTrue(replay.outputs.all { it.contextIsCurrent && it.backendFailureReason == null })
        assertTrue(replay.outputs.all { it.event.latencyMs == 2_800.0 })
        assertEquals(2, replay.displayObservations.size)
        assertTrue(replay.passages.isEmpty())
        assertNull(replay.orchestrator.speedOverride())
        assertEquals(70, replay.orchestrator.effectiveSpeedKmh(null, 70))
        replay.close()
    }

    @Test
    fun sameScoresAtViableCadenceConfirmAndReachTheLivePassageForwarder() {
        val replay = Replay()

        replay.analyze(0, 100, detection(0.87))
        replay.analyze(500, 100, detection(0.90))

        val sightings = replay.outputs.toList()
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, sightings[0].event.state)
        assertEquals(TrafficSignRecognitionState.CONFIRMED, sightings[1].event.state)
        assertEquals(sightings[0].event.candidate?.trackId, sightings[1].event.candidate?.trackId)
        assertEquals(2, sightings[1].event.candidate?.evidenceFrames)
        assertTrue(replay.passages.isEmpty())
        assertNull(replay.orchestrator.speedOverride())

        replay.analyze(1_000, 100, null)
        assertTrue(replay.passages.isEmpty())
        replay.analyze(1_500, 100, null)

        val passage = replay.passages.single()
        assertEquals(50, passage.resolution.speedKmh)
        assertEquals(2, passage.framesSeen)
        assertEquals(2, passage.negativeFramesToCommit)
        assertTrue(replay.outputs.all { it.contextIsCurrent && it.backendFailureReason == null })
        assertEquals(2, replay.displayObservations.size)
        assertEquals(50, replay.orchestrator.effectiveSpeedKmh(null, 70))
        replay.close()
    }

    @Test
    fun verifiedDeviceTimingAllowsSlowInferenceToConfirmAndFinalizeWithoutCountingSkippedFrames() {
        val profile = requireNotNull(TrafficSignInferenceTimingPolicy.profile(1_500, true, listOf(2_800.0, 2_900.0)))
        assertEquals(5_800L, profile.confirmationWindowMs)
        val replay = Replay(profile)

        replay.analyze(0, 2_900, detection(0.87))
        replay.analyze(3_000, 2_900, detection(0.90))
        assertEquals(TrafficSignRecognitionState.CONFIRMED, replay.outputs.last().event.state)
        assertEquals(replay.outputs.first().event.candidate?.trackId, replay.outputs.last().event.candidate?.trackId)
        assertEquals(2, replay.outputs.last().event.candidate?.evidenceFrames)
        assertTrue(replay.passages.isEmpty())

        replay.analyze(6_000, 2_900, null)
        assertTrue(replay.passages.isEmpty())
        replay.skipFrameForThermalPressure(9_000)
        assertEquals(3, replay.outputs.size)
        assertTrue(replay.passages.isEmpty())
        replay.analyze(12_000, 2_900, null)

        val passage = replay.passages.single()
        assertEquals(50, passage.resolution.speedKmh)
        assertEquals(2, passage.negativeFramesToCommit)
        assertEquals(Instant.EPOCH.plusMillis(6_000), passage.passageBoundary.timestampUtc)
        assertEquals(listOf(6_000L, 12_000L), passage.lossEvidence.map { it.timestampUtc.toEpochMilli() })
        assertEquals(50, replay.orchestrator.effectiveSpeedKmh(null, 70))
        replay.close()
    }

    @Test
    fun deviceTimingStillExpiresEvidenceAfterTheSixSecondCap() {
        val profile = requireNotNull(TrafficSignInferenceTimingPolicy.profile(1_500, true, listOf(4_000.0)))
        val replay = Replay(profile)
        replay.analyze(0, 2_900, detection(0.87))
        replay.analyze(6_100, 2_900, detection(0.90))
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, replay.outputs.last().event.state)
        assertEquals(1, replay.outputs.last().event.candidate?.evidenceFrames)
        assertNotEquals(replay.outputs.first().event.candidate?.trackId, replay.outputs.last().event.candidate?.trackId)
        repeat(3) { index -> replay.analyze(9_100L + index * 3_000L, 2_900, null) }
        assertTrue(replay.passages.isEmpty())
        assertNull(replay.orchestrator.speedOverride())
        replay.close()
    }

    @Test
    fun successfulCpuFallbackAfterFastStartupUpdatesTimingAndFinalizesThePassage() {
        val fastProfile = requireNotNull(TrafficSignInferenceTimingPolicy.profile(1_500, true, listOf(100.0)))
        val replay = Replay(fastProfile)
        replay.analyze(0, 2_800, detection(0.87), diagnostics = fallbackDiagnostics(2_800.0))
        replay.analyze(2_900, 2_800, detection(0.90), diagnostics = fallbackDiagnostics(2_800.0))

        assertEquals(5_600L, replay.outputs.last().effectiveConfirmationWindowMs)
        assertEquals(TrafficSignRecognitionState.CONFIRMED, replay.outputs.last().event.state)
        assertEquals(2, replay.outputs.last().event.candidate?.evidenceFrames)
        assertEquals(replay.outputs.first().event.candidate?.trackId, replay.outputs.last().event.candidate?.trackId)
        assertTrue(replay.passages.isEmpty())
        replay.analyze(5_800, 2_800, null, diagnostics = fallbackDiagnostics(2_800.0))
        replay.analyze(8_700, 2_800, null, diagnostics = fallbackDiagnostics(2_800.0))
        assertEquals(50, replay.passages.single().resolution.speedKmh)
        assertEquals(2, replay.passages.single().framesSeen)
        assertEquals(2, replay.passages.single().negativeFramesToCommit)
        replay.close()
    }

    @Test
    fun fallbackTimingRemainsMonotonicAndStillExpiresEvidenceAtTheCap() {
        val replay = Replay(requireNotNull(TrafficSignInferenceTimingPolicy.profile(1_500, true, listOf(100.0))))
        replay.analyze(0, 3_200, detection(0.87), diagnostics = fallbackDiagnostics(3_200.0))
        assertEquals(6_000L, replay.outputs.last().effectiveConfirmationWindowMs)
        replay.analyze(6_100, 2_800, detection(0.90), diagnostics = fallbackDiagnostics(2_800.0))
        assertEquals(6_000L, replay.outputs.last().effectiveConfirmationWindowMs)
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, replay.outputs.last().event.state)
        assertEquals(1, replay.outputs.last().event.candidate?.evidenceFrames)
        assertTrue(replay.passages.isEmpty())
        replay.close()
    }

    @Test
    fun staleOrFailedInferenceCannotExtendTheVerifiedStartupWindow() {
        val replay = Replay(requireNotNull(TrafficSignInferenceTimingPolicy.profile(1_500, true, listOf(100.0))))
        replay.analyze(0, 2_800, detection(0.87),
            diagnostics = fallbackDiagnostics(2_800.0), contextChangesDuringInference = true)
        assertFalse(replay.outputs.last().contextIsCurrent)
        assertEquals(1_500L, replay.outputs.last().effectiveConfirmationWindowMs)
        replay.analyze(2_900, 9_000, null, failureReason = "CPU inference failed")
        assertEquals(TrafficSignRecognitionState.UNAVAILABLE, replay.outputs.last().event.state)
        assertEquals(1_500L, replay.outputs.last().effectiveConfirmationWindowMs)
        assertTrue(replay.passages.isEmpty())
        replay.close()
    }

    @Test
    fun timingExtensionRequiresBothVerifiedStartupAndAnExplicitCpuFallback() {
        val unverified = Replay()
        unverified.analyze(0, 2_800, detection(0.87), diagnostics = fallbackDiagnostics(2_800.0))
        assertEquals(1_500L, unverified.outputs.last().effectiveConfirmationWindowMs)
        unverified.close()

        val verified = Replay(requireNotNull(TrafficSignInferenceTimingPolicy.profile(1_500, true, listOf(100.0))))
        verified.analyze(0, 2_800, detection(0.87), diagnostics = fallbackDiagnostics(2_800.0).copy(
            accelerationFallbackReason = null,
        ))
        assertEquals(1_500L, verified.outputs.last().effectiveConfirmationWindowMs)
        verified.analyze(2_900, 2_800, detection(0.90), diagnostics = fallbackDiagnostics(2_800.0).copy(
            executionBackend = "gpu",
        ))
        assertEquals(1_500L, verified.outputs.last().effectiveConfirmationWindowMs)
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, verified.outputs.last().event.state)
        verified.close()
    }

    @Test(expected = IllegalArgumentException::class)
    fun arbitraryUnboundedWindowIsRejected() {
        Replay(TrafficSignInferenceTimingProfile(2_900.0, 60_000))
    }

    @Test(expected = IllegalArgumentException::class)
    fun deviceWindowCannotReduceManifestAllowance() {
        Replay(TrafficSignInferenceTimingProfile(100.0, 100))
    }

    private class Replay(timingProfile: TrafficSignInferenceTimingProfile? = null) {
        private var nowNanos = 0L
        private var contextGeneration = 1L
        private var thermalPressure = TrafficSignThermalPressure.NOMINAL
        private var pendingCompletion: ((TrafficSignBackendResult) -> Unit)? = null
        private val frames = mutableListOf<Frame>()
        val outputs = mutableListOf<TrafficSignOrchestrationOutput>()
        val displayObservations = mutableListOf<TrafficSignDisplayObservation>()
        val passages = mutableListOf<TrafficSignPassageEvent>()
        private val pack = productionManifest().readText().let(TrafficSignModelPackJson::decode)
        private val context = TrafficSignDetectionContext(
            wayId = "100",
            latitude = 0.0,
            longitude = 0.0,
            headingDegrees = 90.0,
            travelDirection = TrafficSignTravelDirection.FORWARD,
            sourceSignature = TrafficSignRuntimeSourceSignature("bundle:cadence-fixture", null),
            bundleSha256 = "a".repeat(64),
            countryCode = "DE",
            matchedWayStable = true,
            speedMetersPerSecond = 10.0,
        )
        val orchestrator = TrafficSignRecognitionOrchestrator(
            modelPack = pack,
            runtimeArtifact = requireNotNull(pack.androidArtifact(pack.detector)),
            backend = TrafficSignRecognitionBackend<Frame> { _, completion ->
                check(pendingCompletion == null)
                pendingCompletion = completion
            },
            contextSnapshot = TrafficSignDetectionContextSnapshot {
                TrafficSignDetectionContextSnapshotValue(context, contextGeneration, true, "cadence-fixture")
            },
            conditionsSnapshot = { TrafficSignAnalysisConditions(speedMetersPerSecond = 10.0, thermalPressure = thermalPressure) },
            monotonicClockNanos = { nowNanos },
            observer = TrafficSignFinalizedPassageForwarder(
                submitDisplayObservation = { displayObservations += it },
                onInferenceDiagnostics = { outputs += it },
                submitFinalizedPassage = { passages += it; true },
            ),
            confirmationWindowMsOverride = timingProfile?.confirmationWindowMs,
        )

        fun analyze(
            capturedAtMs: Long,
            inferenceMs: Long,
            detection: TrafficSignDetection?,
            diagnostics: TrafficSignInferenceDiagnostics? = null,
            contextChangesDuringInference: Boolean = false,
            failureReason: String? = null,
        ) {
            val capturedAtNanos = capturedAtMs * 1_000_000
            require(capturedAtNanos >= nowNanos)
            nowNanos = capturedAtNanos
            val frame = Frame("frame-${frames.size}", capturedAtNanos).also(frames::add)
            assertTrue(orchestrator.submit(frame))
            val completion = requireNotNull(pendingCompletion)
            pendingCompletion = null
            nowNanos += inferenceMs * 1_000_000
            if (contextChangesDuringInference) {
                contextGeneration += 1
                orchestrator.reconcileContext(context, contextGeneration)
            }
            completion(if (failureReason == null) {
                TrafficSignBackendResult.Recognition(detection, diagnostics = diagnostics)
            } else {
                TrafficSignBackendResult.Unavailable(failureReason)
            })
            assertEquals(1, frame.releases)
        }

        fun skipFrameForThermalPressure(capturedAtMs: Long) {
            val capturedAtNanos = capturedAtMs * 1_000_000
            require(capturedAtNanos >= nowNanos)
            nowNanos = capturedAtNanos
            thermalPressure = TrafficSignThermalPressure.CRITICAL
            val frame = Frame("frame-${frames.size}", capturedAtNanos).also(frames::add)
            assertTrue(orchestrator.submit(frame))
            assertNull(pendingCompletion)
            assertEquals(1, frame.releases)
            thermalPressure = TrafficSignThermalPressure.NOMINAL
        }

        fun close() {
            orchestrator.close()
            assertTrue(frames.all { it.releases == 1 })
            assertFalse(outputs.isEmpty())
        }
    }

    private class Frame(
        override val frameId: String,
        override val capturedAtMonotonicNanos: Long,
    ) : TrafficSignNormalizedFrameHandle {
        override val source = TrafficSignInputSource.LIVE_FRAME
        override val capturedAtUtc = Instant.EPOCH.plusNanos(capturedAtMonotonicNanos)
        override val widthPixels = 1_280
        override val heightPixels = 720
        var releases = 0
        override fun release() { releases += 1 }
    }

    private companion object {
        fun fallbackDiagnostics(inferenceMs: Double) = TrafficSignInferenceDiagnostics(
            inferenceMs = inferenceMs,
            detectorProposalCount = 1,
            detectorTopScore = 0.90,
            classifierInvocationCount = 1,
            classifiedDetectionCount = 1,
            classifierTopScore = 0.999,
            primaryClassId = "maxspeed:50",
            primaryScore = 0.90,
            executionBackend = "cpu",
            accelerationFallbackReason = "GPU inference failed: device lost",
        )

        fun detection(score: Double) = TrafficSignDetection(
            TrafficSignCandidate(
                rawClassId = "maxspeed:50",
                rawLabel = "Maximum speed 50 km/h",
                semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 50, "km/h"),
                rawScore = score,
                calibratedConfidence = null,
                boundingBox = NormalizedTrafficSignBoundingBox(0.7, 0.15, 0.08, 0.12),
                proposalRawScore = score,
                classifierRawScore = 0.999,
            ),
        )

        fun productionManifest(): File = listOf(
            File("app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json"),
            File("src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json"),
            File("android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json"),
        ).firstOrNull(File::isFile) ?: error("Unable to locate the bundled traffic-sign model manifest")
    }
}

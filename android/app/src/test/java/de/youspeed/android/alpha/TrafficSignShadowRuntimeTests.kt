package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignShadowRuntimeTests {
    @Test
    fun hardFrameKeepsVisiblePlateUnreadableAndEmitsCaptureEvidence() {
        val captures = mutableListOf<TrafficSignDiagnosticCaptureRequestV2>()
        val qaEvents = mutableListOf<TrafficSignRecognitionEventV2>()
        val runtime = runtime(
            captureSink = TrafficSignDiagnosticCaptureSinkV2 { request ->
                captures += request
                TrafficSignDiagnosticCaptureOutcomeV2(
                    status = TrafficSignDiagnosticCaptureStatusV2.PERSISTED,
                    captureId = "capture-hard-frame",
                )
            },
            qaSink = TrafficSignQAEventSinkV2(qaEvents::add),
        )

        val event = runtime.process(frameInput(eventId = "event-hard", readablePlate = false))

        assertEquals(2, event.schemaVersion)
        assertEquals(TrafficSignEvidenceOriginV2.RUNTIME_INFERENCE, event.evidenceOrigin)
        assertEquals(TrafficSignExecutionModeV2.SHADOW, event.executionMode)
        assertFalse(event.overrideEligible)
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, event.state)
        assertEquals(TrafficSignOverrideDispositionV2.SHADOW_EVIDENCE_ONLY, event.overrideDisposition)
        val context = requireNotNull(event.roadContext)
        assertEquals("52869774", context.wayId)
        assertEquals(48.780302778, context.latitude, 0.000000001)
        assertEquals(8.402511111, context.longitude, 0.000000001)
        assertEquals(184.0, context.headingDegrees, 0.001)
        assertEquals(TrafficSignTravelDirection.REVERSE, context.travelDirection)

        val assembly = event.assemblies.single()
        assertEquals(70, assembly.primary.semantic.value)
        assertEquals(TrafficSignConditionState.UNRESOLVED, assembly.conditionState)
        assertEquals(TrafficSignPlateReadabilityV2.UNREADABLE, assembly.supplementaryPlates.single().readability)
        assertEquals(0.18, assembly.supplementaryPlates.single().classifierScore?.rawScore ?: -1.0, 0.0001)
        assertNull(assembly.supplementaryPlates.single().restriction)
        assertEquals(
            TrafficSignRestrictionTransitionV2.NONE,
            assembly.temporalEvidence.restrictionTransition,
        )
        assertEquals(1, assembly.temporalEvidence.evidenceFrameCount)
        assertNull(assembly.temporalEvidence.priorEventId)

        assertEquals("yolox-nano-detector", event.stageRuns.detector.componentId)
        assertEquals("mobilenetv3-large-classifier", event.stageRuns.classifier.componentId)
        assertNotEquals(event.stageRuns.detector.artifactSha256, event.stageRuns.classifier.artifactSha256)
        assertEquals(TrafficSignDiagnosticCaptureStatusV2.PERSISTED, event.diagnosticCapture.status)
        assertEquals("capture-hard-frame", event.diagnosticCapture.captureId)
        assertTrue(
            TrafficSignDiagnosticReasonV2.UNREADABLE_SUPPLEMENTARY_PLATE in
                event.diagnosticCapture.reasons,
        )
        assertEquals(event.eventId, captures.single().eventId)
        assertEquals(event, qaEvents.single())
    }

    @Test
    fun laterCalibratedReadableFrameUpgradesOnlyTheSamePhysicalSignTrack() {
        val runtime = runtime()
        val hard = runtime.process(frameInput(eventId = "event-hard", readablePlate = false))
        val readable = runtime.process(
            frameInput(
                eventId = "event-readable",
                readablePlate = true,
                timestamp = Instant.parse("2026-09-01T16:14:35.468Z"),
                latitude = 48.779997222,
                longitude = 8.402469444,
                headingDegrees = 183.0,
                primaryBox = NormalizedTrafficSignBoundingBox(
                    0.702020202020,
                    0.391571969697,
                    0.062710437710,
                    0.034564393939,
                ),
                plateBox = NormalizedTrafficSignBoundingBox(
                    0.704545454545,
                    0.425426136364,
                    0.046717171717,
                    0.015861742424,
                ),
            ),
        )

        val firstAssembly = hard.assemblies.single()
        val upgraded = readable.assemblies.single()
        assertEquals(firstAssembly.physicalSignTrackId, upgraded.physicalSignTrackId)
        assertEquals(TrafficSignRecognitionState.CONFIRMED, readable.state)
        assertEquals(TrafficSignConditionState.RESOLVED, upgraded.conditionState)
        assertEquals(TrafficSignPlateReadabilityV2.READABLE, upgraded.supplementaryPlates.single().readability)
        assertEquals("2000 m", upgraded.supplementaryPlates.single().restriction?.normalizedValue)
        assertEquals(2000, upgraded.supplementaryPlates.single().restriction?.extentM)
        assertEquals("↕ 2 km", upgraded.supplementaryPlates.single().restriction?.rawText)
        assertEquals(2, upgraded.temporalEvidence.evidenceFrameCount)
        assertEquals("event-hard", upgraded.temporalEvidence.priorEventId)
        assertEquals(
            TrafficSignRestrictionTransitionV2.UPGRADED_FROM_LATER_READABLE_EVIDENCE,
            upgraded.temporalEvidence.restrictionTransition,
        )
    }

    @Test
    fun readableLabelBelowCalibratedThresholdCannotInventTwoKilometres() {
        val runtime = runtime()
        runtime.process(frameInput(eventId = "event-hard", readablePlate = false))

        val lowConfidence = runtime.process(
            frameInput(
                eventId = "event-low-confidence",
                readablePlate = true,
                plateCalibratedConfidence = 0.69,
                timestamp = Instant.parse("2026-09-01T16:14:35.468Z"),
            ),
        )

        val assembly = lowConfidence.assemblies.single()
        assertEquals(TrafficSignConditionState.UNRESOLVED, assembly.conditionState)
        assertEquals(TrafficSignPlateReadabilityV2.UNREADABLE, assembly.supplementaryPlates.single().readability)
        assertEquals(0.69, assembly.supplementaryPlates.single().classifierScore?.calibratedConfidence ?: -1.0, 0.0001)
        assertNull(assembly.supplementaryPlates.single().restriction)
        assertEquals(
            TrafficSignRestrictionTransitionV2.PRESERVED_UNREADABLE,
            assembly.temporalEvidence.restrictionTransition,
        )
    }

    @Test
    fun laterReadableFrameWithAnotherStableHintStartsANewPhysicalSignTrack() {
        val runtime = runtime()
        val hard = runtime.process(frameInput(eventId = "event-hard", readablePlate = false))
        val otherSign = runtime.process(
            frameInput(
                eventId = "event-other-sign",
                readablePlate = true,
                timestamp = Instant.parse("2026-09-01T16:14:35.468Z"),
                stableObservationHint = "different-runtime-sign-track",
            ),
        )

        val firstAssembly = hard.assemblies.single()
        val otherAssembly = otherSign.assemblies.single()
        assertNotEquals(firstAssembly.physicalSignTrackId, otherAssembly.physicalSignTrackId)
        assertEquals(1, otherAssembly.temporalEvidence.evidenceFrameCount)
        assertNull(otherAssembly.temporalEvidence.priorEventId)
        assertEquals(TrafficSignRestrictionTransitionV2.NONE, otherAssembly.temporalEvidence.restrictionTransition)
    }

    @Test
    fun v2ShadowEvidenceCanNeitherCreateNorReplaceAnOverride() {
        val runtime = runtime()
        runtime.process(frameInput(eventId = "event-hard", readablePlate = false))
        val event = runtime.process(
            frameInput(
                eventId = "event-readable",
                readablePlate = true,
                timestamp = Instant.parse("2026-09-01T16:14:35.468Z"),
            ),
        )
        assertEquals(TrafficSignRecognitionState.CONFIRMED, event.state)
        val context = requireNotNull(event.roadContext)
        val existing = TrafficSignSpeedOverride(
            speedKmh = 50,
            detectedAtUtc = Instant.parse("2026-09-01T09:59:00Z"),
            trackId = "active-v1-track",
            context = context,
        )

        assertNull(
            TrafficSignSpeedOverridePolicy.applyRecognition(
                current = null,
                event = event,
                currentSourceSignature = context.sourceSignature,
            ),
        )
        assertSame(
            existing,
            TrafficSignSpeedOverridePolicy.applyRecognition(
                current = existing,
                event = event,
                currentSourceSignature = context.sourceSignature,
            ),
        )
        assertEquals(
            50,
            TrafficSignSpeedOverridePolicy.effectiveSpeedKmh(
                current = existing,
                localCorrectionKmh = 60,
                bundledMapKmh = 70,
            ),
        )
    }

    private fun runtime(
        captureSink: TrafficSignDiagnosticCaptureSinkV2? = null,
        qaSink: TrafficSignQAEventSinkV2? = null,
    ) = TrafficSignShadowRuntimeV2(
        configuration = configuration(),
        diagnosticCaptureSink = captureSink,
        qaEventSink = qaSink,
    )

    private fun configuration() = TrafficSignShadowRuntimeConfigurationV2(
        packId = "de-yolox-nano-mobilenetv3-large-m0",
        taxonomyVersion = "tsr-semantic-v2",
        initialMode = TrafficSignExecutionModeV2.SHADOW,
        overrideEligible = false,
        detector = TrafficSignShadowStageIdentityV2(
            componentId = "yolox-nano-detector",
            artifactId = "detector-litert-fp16",
            artifactSha256 = "a".repeat(64),
            artifactFormat = TrafficSignRuntimeArtifactFormatV2.LITERT,
            preprocessingVersion = "detector-full-frame-letterbox-v2",
            calibrationId = "detector-calibration-v2",
            calibrationPassed = true,
        ),
        classifier = TrafficSignShadowStageIdentityV2(
            componentId = "mobilenetv3-large-classifier",
            artifactId = "classifier-litert-fp16",
            artifactSha256 = "b".repeat(64),
            artifactFormat = TrafficSignRuntimeArtifactFormatV2.LITERT,
            preprocessingVersion = "classifier-proposal-crop-v2",
            calibrationId = "classifier-calibration-v2",
            calibrationPassed = true,
        ),
        classifierConfirmedThreshold = 0.8,
        confirmationFrames = 2,
        minimumTrackIou = 0.2,
        temporalWindowMs = 2_500,
        associationPolicy =
            TrafficSignAssociationPolicyV2.STABLE_OBSERVATION_HINT_THEN_UNIQUE_SEMANTIC_ROAD_DIRECTION,
        stableObservationHintCanOverrideIou = true,
        fallbackRequiresUniqueCandidate = true,
    )

    private fun frameInput(
        eventId: String,
        readablePlate: Boolean,
        plateCalibratedConfidence: Double = 0.94,
        timestamp: Instant = Instant.parse("2026-09-01T16:14:33.731Z"),
        latitude: Double = 48.780302778,
        longitude: Double = 8.402511111,
        headingDegrees: Double = 184.0,
        wayId: String = "52869774",
        stableObservationHint: String = "panoramax-physical-sign-70-extent-2km-48.7800-8.4025",
        primaryBox: NormalizedTrafficSignBoundingBox = NormalizedTrafficSignBoundingBox(
            0.490740740741,
            0.427320075758,
            0.023148148148,
            0.013257575758,
        ),
        plateBox: NormalizedTrafficSignBoundingBox = NormalizedTrafficSignBoundingBox(
            0.492424242424,
            0.440104166667,
            0.018518518519,
            0.005918560606,
        ),
    ): TrafficSignShadowFrameInputV2 {
        val context = TrafficSignDetectionContext(
            wayId = wayId,
            latitude = latitude,
            longitude = longitude,
            headingDegrees = headingDegrees,
            travelDirection = TrafficSignTravelDirection.REVERSE,
            sourceSignature = TrafficSignRuntimeSourceSignature(
                osmRevision = "bundle:3efd3c6ff66f90006778bb23d6995483fbe483620b72e838f83bcf77538cac89|way:52869774|maxspeed:70",
                localCorrectionRevision = null,
            ),
        )
        val restriction = if (readablePlate) {
            TrafficSignRestrictionV2(
                kind = TrafficSignRestrictionKind.EXTENT,
                normalizedValue = "2000 m",
                extentM = 2000,
                rawText = "↕ 2 km",
                countrySignCode = null,
            )
        } else {
            null
        }
        return TrafficSignShadowFrameInputV2(
            eventId = eventId,
            source = TrafficSignInputSourceV2.PANORAMAX_REPLAY,
            frame = TrafficSignFrameV2(
                frameId = "frame-$eventId",
                timestampUtc = timestamp,
                width = 2376,
                height = 4224,
            ),
            roadContext = context,
            requestedState = TrafficSignRecognitionState.CONFIRMED,
            detectorLatencyMs = 18.0,
            classifierInvoked = true,
            classifierLatencyMs = 7.0,
            assemblies = listOf(
                TrafficSignTwoStageAssemblyObservationV2(
                    assemblyId = "assembly-$eventId",
                    stableObservationHint = stableObservationHint,
                    primary = TrafficSignTwoStagePrimaryObservationV2(
                        objectId = "primary-$eventId",
                        classId = "speed_limit_70",
                        semantic = TrafficSignPrimarySemanticV2(
                            kind = TrafficSignPrimarySemanticKindV2.MAXIMUM_SPEED,
                            value = 70,
                            unit = "km/h",
                        ),
                        boundingBox = primaryBox,
                        detectorScore = 0.92,
                        detectorCalibratedConfidence = 0.91,
                        classifierRawScore = 2.4,
                        classifierCalibratedConfidence = 0.96,
                        classifierThreshold = 0.80,
                    ),
                    supplementaryPlates = listOf(
                        TrafficSignTwoStagePlateObservationV2(
                            objectId = "plate-$eventId",
                            classId = if (readablePlate) "restriction_extent_2000m" else null,
                            boundingBox = plateBox,
                            detectorScore = 0.81,
                            detectorCalibratedConfidence = 0.79,
                            classifierRawScore = if (readablePlate) 1.9 else 0.18,
                            classifierCalibratedConfidence = if (readablePlate) {
                                plateCalibratedConfidence
                            } else {
                                0.16
                            },
                            classifierThreshold = 0.70,
                            readability = if (readablePlate) {
                                TrafficSignPlateReadabilityV2.READABLE
                            } else {
                                TrafficSignPlateReadabilityV2.UNREADABLE
                            },
                            restriction = restriction,
                        ),
                    ),
                ),
            ),
        )
    }
}

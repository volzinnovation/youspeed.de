package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

class TrafficSignSpeedOverridePolicyTests {
    private val t0 = Instant.parse("2026-09-01T10:00:00Z")

    @Test
    fun confirmedNumericDetectionOverridesLocalAndBundledSpeed() {
        val override = TrafficSignSpeedOverridePolicy.applyRecognition(
            current = null,
            event = event(speedKmh = 30, at = t0, context = context("map-v1/local-v3")),
            currentSourceSignature = signature("map-v1/local-v3"),
        )

        assertEquals(30, override?.speedKmh)
        assertEquals(30, TrafficSignSpeedOverridePolicy.effectiveSpeedKmh(override, localCorrectionKmh = 50, bundledMapKmh = 70))
    }

    @Test
    fun unknownTravelDirectionUsesWayWideOverride() {
        val source = signature("map-v1/local-v3")
        val knownContext = context("map-v1/local-v3")
        val existing = requireNotNull(
            TrafficSignSpeedOverridePolicy.applyRecognition(
                current = null,
                event = event(speedKmh = 30, at = t0, context = knownContext),
                currentSourceSignature = source,
            ),
        )
        val unknownContext = context(
            sourceID = "map-v1/local-v3",
            travelDirection = TrafficSignTravelDirection.UNKNOWN,
        )
        val unknownDirectionEvent = event(
            speedKmh = 50,
            at = t0.plusSeconds(1),
            context = unknownContext,
        )

        val created = TrafficSignSpeedOverridePolicy.applyRecognition(
            current = null,
            event = unknownDirectionEvent,
            currentSourceSignature = source,
        )
        val replaced = TrafficSignSpeedOverridePolicy.applyRecognition(
            current = existing,
            event = unknownDirectionEvent,
            currentSourceSignature = source,
        )

        assertEquals(50, created?.speedKmh)
        assertEquals(50, replaced?.speedKmh)
        assertEquals(TrafficSignTravelDirection.UNKNOWN, replaced?.context?.travelDirection)
    }

    @Test
    fun numericZoneStartAndTemporarySignsAreActionableLiveOverrides() {
        val source = signature("map-v1/local-v3")
        val detectionContext = context("map-v1/local-v3")
        val actionableSemantics = listOf(
            TrafficSignSemanticKind.ZONE_START to 30,
            TrafficSignSemanticKind.TEMPORARY to 50,
        )

        actionableSemantics.forEachIndexed { index, (kind, speedKmh) ->
            val override = TrafficSignSpeedOverridePolicy.applyRecognition(
                current = null,
                event = event(
                    speedKmh = speedKmh,
                    at = t0.plusSeconds(index.toLong()),
                    context = detectionContext,
                    semanticKind = kind,
                ),
                currentSourceSignature = source,
            )

            assertEquals(speedKmh, override?.speedKmh)
        }
    }

    @Test
    fun diagnosticImportCannotCreateOrReplaceALiveOverride() {
        val detectionContext = context("map-v1/local-v3")
        val existing = requireNotNull(
            TrafficSignSpeedOverridePolicy.applyRecognition(
                current = null,
                event = event(speedKmh = 30, at = t0, context = detectionContext),
                currentSourceSignature = detectionContext.sourceSignature,
            ),
        )
        val imported = event(
            speedKmh = 50,
            at = t0.plusSeconds(1),
            context = detectionContext,
        ).copy(source = TrafficSignInputSource.DIAGNOSTIC_IMPORT)

        assertNull(TrafficSignSpeedOverridePolicy.applyRecognition(
            current = null,
            event = imported,
            currentSourceSignature = detectionContext.sourceSignature,
        ))
        assertSame(existing, TrafficSignSpeedOverridePolicy.applyRecognition(
            current = existing,
            event = imported,
            currentSourceSignature = detectionContext.sourceSignature,
        ))
    }

    @Test
    fun repeatedGpsFixWithSameSourceSignatureDoesNotClearOverride() {
        val override = requireNotNull(
            TrafficSignSpeedOverridePolicy.applyRecognition(
                null,
                event(30, t0, context("map-v1/local-v3")),
                signature("map-v1/local-v3"),
            ),
        )

        val retained = TrafficSignSpeedOverridePolicy.reconcileSource(override, signature("map-v1/local-v3"))

        assertSame(override, retained)
    }

    @Test
    fun genuinelyChangedMapOrLocalRevisionClearsOverride() {
        val override = TrafficSignSpeedOverridePolicy.applyRecognition(
            null,
            event(30, t0, context("map-v1/local-v3")),
            signature("map-v1/local-v3"),
        )

        assertNull(TrafficSignSpeedOverridePolicy.reconcileSource(override, signature("map-v2/local-v3")))
        assertEquals(50, TrafficSignSpeedOverridePolicy.effectiveSpeedKmh(null, localCorrectionKmh = 50, bundledMapKmh = 70))
    }

    @Test
    fun newerConfirmedDetectionReplacesAndOlderDetectionCannotRollBack() {
        val firstContext = context("source-v1")
        val first = TrafficSignSpeedOverridePolicy.applyRecognition(
            null,
            event(30, t0, firstContext),
            firstContext.sourceSignature,
        )
        val newerContext = context("source-v1", wayId = "456")
        val newer = TrafficSignSpeedOverridePolicy.applyRecognition(
            first,
            event(50, t0.plusSeconds(2), newerContext),
            newerContext.sourceSignature,
        )
        val older = TrafficSignSpeedOverridePolicy.applyRecognition(
            newer,
            event(20, t0.plusSeconds(1), firstContext),
            firstContext.sourceSignature,
        )

        assertEquals(50, newer?.speedKmh)
        assertSame(newer, older)
    }

    @Test
    fun newerConfirmedNonNumericSignEndsPreviousNumericOverride() {
        val detectionContext = context("source-v1")
        val first = TrafficSignSpeedOverridePolicy.applyRecognition(
            null,
            event(30, t0, detectionContext),
            detectionContext.sourceSignature,
        )
        val restrictionEnd = event(30, t0.plusSeconds(1), detectionContext).copy(
            candidate = event(30, t0.plusSeconds(1), detectionContext).candidate?.copy(
                semantic = TrafficSignSemantic(TrafficSignSemanticKind.RESTRICTION_END),
            ),
        )

        assertNull(TrafficSignSpeedOverridePolicy.applyRecognition(first, restrictionEnd, detectionContext.sourceSignature))
    }

    @Test
    fun delayedDetectionFromPreviousWayCannotOverrideNewMapContext() {
        val oldContext = context("map-v1", wayId = "123")
        val currentSignature = signature("map-v2")

        val override = TrafficSignSpeedOverridePolicy.applyRecognition(
            current = null,
            event = event(30, t0, oldContext),
            currentSourceSignature = currentSignature,
        )

        assertNull(override)
    }

    private fun context(
        sourceID: String,
        wayId: String = "123",
        travelDirection: TrafficSignTravelDirection = TrafficSignTravelDirection.FORWARD,
    ) = TrafficSignDetectionContext(
        wayId = wayId,
        latitude = 49.0069,
        longitude = 8.4037,
        headingDegrees = 87.0,
        travelDirection = travelDirection,
        sourceSignature = signature(sourceID),
    )

    private fun signature(value: String) = TrafficSignRuntimeSourceSignature(
        osmRevision = value.substringBefore('/'),
        localCorrectionRevision = value.substringAfter('/', missingDelimiterValue = "").ifBlank { null },
    )

    private fun event(
        speedKmh: Int,
        at: Instant,
        context: TrafficSignDetectionContext,
        semanticKind: TrafficSignSemanticKind = TrafficSignSemanticKind.MAXIMUM_SPEED,
    ) = TrafficSignRecognitionEvent(
        schemaVersion = 1,
        packId = "de-fixture",
        artifactSha256 = "a".repeat(64),
        preprocessingVersion = "vision-scale-fit-rgb-v1",
        source = TrafficSignInputSource.LIVE_FRAME,
        frameTimestampUtc = at,
        state = TrafficSignRecognitionState.CONFIRMED,
        candidate = TrafficSignCandidate(
            rawClassId = "speed_limit_$speedKmh",
            rawLabel = "Maximum speed $speedKmh",
            semantic = TrafficSignSemantic(semanticKind, speedKmh, "km/h"),
            rawScore = 0.9,
            calibratedConfidence = 0.85,
            boundingBox = NormalizedTrafficSignBoundingBox(0.7, 0.15, 0.08, 0.12),
            trackId = "track-$speedKmh",
            evidenceFrames = 3,
        ),
        roadContext = context,
        latencyMs = 40.0,
        thermalState = "nominal",
    )
}

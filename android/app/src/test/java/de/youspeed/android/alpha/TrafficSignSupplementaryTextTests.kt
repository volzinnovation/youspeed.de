package de.youspeed.android.alpha

import java.time.Instant
import java.util.Locale
import org.junit.Assert.*
import org.junit.Test

class TrafficSignSupplementaryTextTests {
    private val start = Instant.parse("2026-10-16T08:00:00Z")
    private val box = NormalizedTrafficSignBoundingBox(.2, .2, .2, .2)
    private fun candidate() = TrafficSignCandidate("maxspeed:30", "30",
        TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h"), .98, null, box)
    private fun request() = TrafficSignSupplementaryOCRRequest(candidate(), "physical", "confirmed-second-frame",
        start.plusMillis(201), start, TrafficSignSupplementaryScope(7, "drive"))

    @Test fun timeParsingIsOptionalFormattingAndNeverDropsUnknownRawConditions() {
        for (text in listOf("22-6h", "22–6 h", "22 — 06 Uhr", "22−6", "22:00-06:00"))
            assertEquals("22–6 h", TrafficSignSupplementaryTimeWindow.parse(text)?.displayText)
        for (text in listOf("Mo-Fr\n22-6h", "22-6h außer Anlieger", "24-6h", "22:60-6h", "22-22h", "226h", "22-O6h", ""))
            assertNull(text, TrafficSignSupplementaryTimeWindow.parse(text))
        val annotation = request().annotation("Mo-Fr\n22-6h")
        assertEquals("Mo-Fr\n22-6h", annotation.rawText)
        assertNull(annotation.window)
        assertEquals("Mo-Fr 22-6h", annotation.text)
        assertEquals("Montag bis Freitag von 22 Uhr bis 6 Uhr", annotation.spokenText(Locale.GERMAN))
        assertTrue(annotation.hasText)
        assertTrue(candidate().restrictions.isEmpty())
        assertEquals(TrafficSignConditionState.NONE, candidate().conditionState)
    }

    @Test fun localizedReadoutAndRawDisplayRemainHumanReadableAndBounded() {
        val window = TrafficSignSupplementaryTimeWindow(1320, 360)
        assertEquals("von 22 Uhr bis 6 Uhr", window.spokenText(Locale.GERMAN))
        assertEquals("from 10 p.m. to 6 a.m.", window.spokenText(Locale.ENGLISH))
        assertEquals("de 1 heure à 6 heures", TrafficSignSupplementaryTimeWindow(60, 360).spokenText(Locale.FRENCH))
        assertEquals("bei Nässe", request().annotation("bei\tNässe").text)
        assertEquals(158, request().annotation("a".repeat(200)).text.length)
        assertTrue(request().annotation("a".repeat(200)).text.endsWith("…"))
        assertEquals(200, request().annotation("a".repeat(200)).rawText?.length)
    }

    @Test fun publicPanoramaxExampleRetainsWeekdaysAndNormalizesCompactSuperscriptMinutes() {
        for (raw in listOf("Mo-Fr\n630_1730 h", "Mo-Fr\n6³⁰–17³⁰ h")) {
            val value = request().annotation(raw)
            assertEquals(raw, value.rawText)
            assertNull(value.window)
            assertEquals("Mo-Fr 6:30–17:30 h", value.text)
            assertEquals("Montag bis Freitag von 6 Uhr 30 bis 17 Uhr 30", value.spokenText(Locale.GERMAN))
        }
        assertEquals("1234-5678 h", TrafficSignOCRTextFormatting.display("1234-5678 h"))
        assertEquals("630-1730 kg", TrafficSignOCRTextFormatting.display("630-1730 kg"))
    }

    @Test fun onlyPositiveNumericKmhSpeedSignsQualifyForOcr() {
        assertEquals(30, candidate().numericSupplementarySpeed())
        for (semantic in listOf(TrafficSignSemantic(TrafficSignSemanticKind.TEMPORARY, 30, "km/h"),
            TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "mph"),
            TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED_END, 30, "km/h"),
            TrafficSignSemantic(TrafficSignSemanticKind.CITY_ENTRY, 50, "km/h")))
            assertNull(candidate().copy(rawClassId = "other", semantic = semantic).numericSupplementarySpeed())
    }

    @Test fun nativeBottomHalfRequiresTheWholeLowerRectangleWithoutResizing() {
        assertEquals(TrafficSignSupplementaryPixelRect(0, 115, 136, 115),
            supplementaryTextPixelRect(NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, .5), 136, 230))
        assertNull(supplementaryTextPixelRect(NormalizedTrafficSignBoundingBox(.1, .5, .5, .4), 136, 230))
        assertNull(supplementaryTextPixelRect(NormalizedTrafficSignBoundingBox(.1, .1, .1, .1), 136, 230))
    }

    @Test fun annotationRecordsAllCompletionStatusesAndImmutableOriginalReadProvenance() {
        assertEquals(TrafficSignSupplementaryOCRStatus.NO_TEXT, request().annotation(" ").status)
        assertEquals(TrafficSignSupplementaryOCRStatus.FAILED, request().annotation(null, failed = true).status)
        val original = request().annotation("bei Nässe")
        val cached = original.copy(observedAt = start.plusSeconds(10))
        assertEquals(TrafficSignSupplementaryOCRStatus.READ, cached.status)
        assertEquals(original.frameId, cached.frameId)
        assertEquals(original.sourceObservedAt, cached.sourceObservedAt)
        assertEquals(start, cached.firstSeenAt)
        assertTrue(cached.isFresh(start.plusSeconds(12)))
        assertFalse(cached.isFresh(start.plusSeconds(14)))
    }

    @Test fun presentationRequiresMatchingNumericCameraEvidenceAndClearsOnGenerationReset() {
        val observation = request().annotation("bei Nässe")
        assertTrue(observation.matchesNumeric(30, true))
        assertFalse(observation.matchesNumeric(50, true))
        assertFalse(observation.matchesNumeric(30, false))
        assertFalse(request().annotation(null).matchesNumeric(30, true))
        assertEquals(observation.speechKey, observation.copy(physicalSignId = "fragment").speechKey)
        assertNotEquals(observation.presentationKey, observation.copy(physicalSignId = "fragment").presentationKey)
        val reset = ConsumerUiState(trafficSignSupplementaryText = observation, trafficSignPendingSpeedKmh = 30, trafficSignGeneration = 7)
            .withCurrentTrafficSignDisplayGeneration(7, 8)
        assertNull(reset.trafficSignSupplementaryText)
        assertNull(reset.trafficSignPendingSpeedKmh)
    }

    @Test fun pendingOcrNeverOwnsOrdinarySpeechAndStaleCallbacksCannotCancelNewSpeech() {
        val playback = TrafficSignSpeechPlaybackState()
        playback.begin("ordinary-sign", secondary = true)
        assertTrue(playback.hasSecondaryUtterance)
        assertFalse(playback.hasSupplementaryUtterance)
        playback.begin("ocr", secondary = true, supplementaryKey = "physical:raw")
        playback.finish("ordinary-sign")
        assertTrue(playback.hasSupplementaryUtterance)
        playback.begin("speed", secondary = false)
        playback.finish("ocr")
        assertFalse(playback.hasSupplementaryUtterance)
        assertFalse(playback.isIdle(false))
        playback.reset()
        assertTrue(playback.isIdle(false))
    }
}

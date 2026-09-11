package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeedCaptureSpeechTests {
    @Test
    fun timeoutOrEmptyFinalResultNeverPromotesAProvisionalHypothesis() {
        val buffer = SpeedCaptureTranscriptBuffer()
        buffer.updatePartial("hundert")
        assertEquals("100", SpeedCaptureSpeech.resolveSelection(buffer.partialTranscript)?.value)
        assertTrue(buffer.finalCandidates().isEmpty())
        assertTrue(buffer.acceptCompleted(emptyList()).isEmpty())
        buffer.updatePartial("hundert zwanzig")
        assertTrue(buffer.acceptCompleted(listOf(" ")).isEmpty())
    }

    @Test
    fun finalizedUtteranceReplacesThePartialAndPreservesOnlyCompletedAlternatives() {
        val buffer = SpeedCaptureTranscriptBuffer()
        buffer.updatePartial("hundert")
        val final = buffer.acceptCompleted(listOf("hundert zwanzig", " 120 ", "120"))
        assertEquals(listOf("hundert zwanzig", "120"), final)
        assertEquals("120", final.firstNotNullOfOrNull(SpeedCaptureSpeech::resolveSelection)?.value)
        buffer.updatePartial("dreissig")
        assertEquals(final, buffer.acceptCompleted(emptyList()))
        assertEquals(final, buffer.finalCandidates())
    }

    @Test
    fun resolvesGermanTranscriptToNumericWhitelistValue() {
        val selection = SpeedCaptureSpeech.resolveSelection("bitte hier hundert dreissig")

        requireNotNull(selection)
        assertEquals("130", selection.value)
        assertEquals(130, selection.numericSpeedKmh)
    }

    @Test
    fun resolvesPedestrianZoneTranscript() {
        val selection = SpeedCaptureSpeech.resolveSelection("das ist eine fussgaengerzone")

        requireNotNull(selection)
        assertEquals("walk", selection.value)
        assertNull(selection.numericSpeedKmh)
    }

    @Test
    fun resolvesUmlautTranscriptVariantsFromVosk() {
        val speedSelection = SpeedCaptureSpeech.resolveSelection("bitte hier hundert dreißig")
        val walkSelection = SpeedCaptureSpeech.resolveSelection("das ist eine fußgängerzone")

        requireNotNull(speedSelection)
        requireNotNull(walkSelection)
        assertEquals("130", speedSelection.value)
        assertEquals("walk", walkSelection.value)
    }

    @Test
    fun manualSelectionAcceptsWalkAlias() {
        val selection = SpeedCaptureSpeech.selectionForValue("Fussgaengerzone")

        requireNotNull(selection)
        assertEquals("walk", selection.value)
        assertEquals("Fussgaengerzone", selection.displayLabel)
    }

    @Test
    fun usesShortCorrectionPromptText() {
        assertEquals("Korrektur", SpeedCaptureSpeech.promptText)
    }

    @Test
    fun rejectsNonWhitelistTranscript() {
        val selection = SpeedCaptureSpeech.resolveSelection("zweihundert")

        assertNull(selection)
    }
}

package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SpeedCaptureSpeechTests {
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
    fun rejectsNonWhitelistTranscript() {
        val selection = SpeedCaptureSpeech.resolveSelection("zweihundert")

        assertNull(selection)
    }
}

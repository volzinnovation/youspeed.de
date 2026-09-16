package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

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

    @Test
    fun resolvesFrenchOnDeviceSpeechProfile() {
        val language = SpeedCaptureSpeech.languageFor(Locale.FRENCH)
        val speed = SpeedCaptureSpeech.resolveSelection("quatre-vingt-dix", language)
        val walk = SpeedCaptureSpeech.resolveSelection("zone piétonne", language)

        assertEquals(SpeedCaptureLanguage.FRENCH, language)
        assertEquals("fr-FR", language.localeTag)
        assertEquals("vosk-model-small-fr-0.22", language.modelAssetPath)
        assertEquals("Correction", language.promptText)
        assertEquals("90", speed?.value)
        assertEquals("walk", walk?.value)
    }

    @Test
    fun resolvesDutchOnDeviceSpeechProfile() {
        val language = SpeedCaptureSpeech.languageFor(Locale.forLanguageTag("nl-NL"))
        val speed = SpeedCaptureSpeech.resolveSelection("honderdtwintig", language)
        val walk = SpeedCaptureSpeech.resolveSelection("voetgangerszone", language)

        assertEquals(SpeedCaptureLanguage.DUTCH, language)
        assertEquals("nl-NL", language.localeTag)
        assertEquals("vosk-model-small-nl-0.22", language.modelAssetPath)
        assertEquals("Correctie", language.promptText)
        assertEquals("120", speed?.value)
        assertEquals("walk", walk?.value)
    }

    @Test
    fun usesEnglishForUnsupportedDeviceLanguageAndResolvesEnglishSpeech() {
        val language = SpeedCaptureSpeech.languageFor(Locale.ITALIAN)
        val speed = SpeedCaptureSpeech.resolveSelection("one hundred and twenty", language)
        val walk = SpeedCaptureSpeech.resolveSelection("pedestrian zone", language)

        assertEquals(SpeedCaptureLanguage.ENGLISH, language)
        assertEquals("en-US", language.localeTag)
        assertEquals("vosk-model-small-en-us-0.15", language.modelAssetPath)
        assertEquals("Correction", language.promptText)
        assertEquals("120", speed?.value)
        assertEquals("walk", walk?.value)
    }
}

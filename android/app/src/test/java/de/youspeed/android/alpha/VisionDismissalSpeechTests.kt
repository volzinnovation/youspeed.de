package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class VisionDismissalSpeechTests {
    @Test fun everyBundledLanguageHasAnExactDismissalCommandAndUnknownGrammarPath() {
        val expected = mapOf(SpeedCaptureLanguage.GERMAN to "Falsch", SpeedCaptureLanguage.ENGLISH to "Wrong",
            SpeedCaptureLanguage.FRENCH to "Faux", SpeedCaptureLanguage.DUTCH to "Fout")
        assertEquals(SpeedCaptureLanguage.values().toSet(), expected.keys)
        expected.forEach { (language, word) ->
            assertTrue(VisionDismissalSpeech.accepts("  $word! ", language))
            assertTrue(VisionDismissalSpeech.grammar(language).contains("[unk]"))
            assertFalse(VisionDismissalSpeech.accepts("not $word", language))
            assertFalse(VisionDismissalSpeech.accepts("$word [unk]", language))
            assertFalse(VisionDismissalSpeech.accepts("${word}ly", language))
            assertFalse(VisionDismissalSpeech.accepts("", language))
            assertFalse(VisionDismissalSpeech.accepts("50", language))
        }
    }

    @Test fun repeatedFramesAndFinalizationDoNotExtendOrReopenAWindow() {
        val window = VisionDismissalWindow()
        val evidence = VisionDismissalEvidence(1, "sign-30", 30)
        assertTrue(window.observe(evidence, 0, true))
        assertTrue(window.begin(evidence, 300))
        assertFalse(window.observe(evidence, 3_000, true))
        assertTrue(window.owns(evidence, 4_300))
        assertTrue(window.owns(evidence, 4_649)) // Completed result delivery only, after capture stops.
        assertTrue(window.expired(4_650))
        window.cancel()
        assertFalse(window.observe(evidence, 5_000, true))
        assertFalse(window.observe(evidence.copy(generation = 2), 5_100, true))
    }

    @Test fun replacementAndCancellationInvalidateQueuedCallbacks() {
        val window = VisionDismissalWindow()
        val first = VisionDismissalEvidence(1, "exit-30", 30)
        val second = VisionDismissalEvidence(1, "main-50", 50)
        assertTrue(window.observe(first, 0, true))
        assertTrue(window.begin(first, 300))
        assertTrue(window.observe(second, 800, true))
        assertFalse(window.owns(first, 900))
        assertTrue(window.begin(second, 1_100))
        assertFalse(window.observe(null, 1_200, true))
        assertFalse(window.owns(second, 1_201))
    }

    @Test fun unavailableMicrophoneAndExpiredTtsDelayNeverReplayAnOldSign() {
        val window = VisionDismissalWindow()
        val first = VisionDismissalEvidence(1, "one", 30)
        val second = VisionDismissalEvidence(1, "two", 50)
        assertFalse(window.observe(first, 0, false))
        assertFalse(window.observe(first, 500, true))
        assertTrue(window.observe(second, 1_000, true))
        assertFalse(window.observe(second, 3_999, true))
        assertFalse(window.begin(second, 4_000))
        assertTrue(window.expired(4_000))
    }

    @Test fun backgroundOrManualCaptureCancelsWithoutReopeningTheSameSign() {
        val window = VisionDismissalWindow()
        val sign = VisionDismissalEvidence(1, "one", 30)
        assertTrue(window.observe(sign, 0, true))
        assertTrue(window.begin(sign, 300))
        assertFalse(window.observe(sign, 1_000, false))
        assertFalse(window.owns(sign, 1_001))
        assertFalse(window.observe(sign, 1_500, true))
        window.resetForNewDrive()
        assertTrue(window.observe(sign.copy(generation = 2), 2_000, true))
    }
}

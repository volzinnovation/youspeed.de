package de.youspeed.android.alpha

import java.time.Instant
import java.util.Locale
import org.junit.Assert.*
import org.junit.Test

class SecondaryTrafficSignSpeechTests {
    @Test fun feedbackPreferencesKeepExistingNamesAndSoundDefault() {
        assertEquals(TrafficSignFeedbackMode.SOUND, ConsumerUiState().trafficSignFeedbackMode)
        assertEquals(TrafficSignFeedbackMode.SOUND, TrafficSignFeedbackMode.fromStorageValue(null))
        assertEquals(TrafficSignFeedbackMode.SOUND, TrafficSignFeedbackMode.fromStorageValue("unknown"))
        for (mode in TrafficSignFeedbackMode.entries) {
            assertEquals(mode, TrafficSignFeedbackMode.fromStorageValue(mode.name))
        }
        assertEquals(TrafficSignFeedbackMode.SPOKEN_SPEED, TrafficSignFeedbackMode.fromStorageValue("SPOKEN_SPEED"))
        assertEquals(TrafficSignFeedbackMode.SILENT, TrafficSignFeedbackMode.fromStorageValue("SILENT"))
    }

    @Test fun optionalSpeechNeverFallsBackToTechnicalLabelOrAnotherLanguage() {
        assertNull(catalog().pictogram("technical:class")?.spokenText(Locale.GERMAN))
        assertNull(catalog("null").pictogram("technical:class")?.spokenText(Locale.GERMAN))
        val sign = requireNotNull(catalog("""{"de":"  Vorfahrt gewähren  ","en":"Give way","fr":" ","nl":42}""")
            .pictogram("technical:class"))
        assertEquals("Vorfahrt gewähren", sign.spokenText(Locale.GERMANY))
        assertEquals("Give way", sign.spokenText(Locale.UK))
        assertNull(sign.spokenText(Locale.FRENCH))
        assertNull(sign.spokenText(Locale.forLanguageTag("nl-NL")))
        assertNull(sign.spokenText(Locale.forLanguageTag("it-IT")))
        assertEquals("technical:class", sign.label(Locale.FRENCH))
    }

    @Test fun sameClassStaysSilentWhileContinuouslySeenIncludingBusyAndStationaryFrames() {
        val gate = SecondaryTrafficSignSpeechGate()
        assertTrue(observe(gate, "stop", 0))
        for (second in 1L..30L) {
            assertFalse(observe(gate, "stop", second, canSpeak = second < 5 || second >= 25))
        }
        assertFalse(observe(gate, "stop", 37)) // Seven seconds since its last sighting.
        assertTrue(observe(gate, "stop", 45))  // Exactly eight seconds not seen.
    }

    @Test fun voiceDismissalWindowDoesNotQueueOrRearmAContinuouslyVisibleSign() {
        val gate = SecondaryTrafficSignSpeechGate()
        assertTrue(observe(gate, "stop", 0))
        for (second in 1L..12L) {
            assertFalse(observe(gate, "stop", second, canSpeak = allowed(visionDismissalIdle = false)))
        }
        assertFalse(observe(gate, "stop", 13, canSpeak = allowed()))
        assertTrue(observe(gate, "stop", 21, canSpeak = allowed()))
    }

    @Test fun differentClassesHaveIndependentAbsenceAndThreeSecondGlobalSpacing() {
        val gate = SecondaryTrafficSignSpeechGate()
        assertTrue(observe(gate, "stop", 0))
        assertFalse(observe(gate, "give_way", 1))
        assertFalse(observe(gate, "give_way", 2))
        assertTrue(observe(gate, "give_way", 3))
        assertFalse(observe(gate, "stop", 4))
        assertFalse(observe(gate, "stop", 11))
        assertTrue(observe(gate, "stop", 19))
    }

    @Test fun busyFramesAreNotQueuedAndOnlyAFreshNewFrameCanSpeak() {
        val gate = SecondaryTrafficSignSpeechGate()
        var emissions = 0
        assertFalse(gate.consume("stop", time(0), time(0), false) { emissions++; true })
        assertEquals(0, emissions)
        assertFalse(gate.consume("stop", time(0), time(1), true) { emissions++; true })
        assertFalse(gate.consume("stop", time(1), time(4), true) { emissions++; true })
        assertEquals(0, emissions)
        assertTrue(gate.consume("stop", time(5), time(5), true) { emissions++; true })
        assertEquals(1, emissions)
    }

    @Test fun failedSpeechDoesNotConsumeTheSignOrCooldown() {
        val gate = SecondaryTrafficSignSpeechGate()
        assertFalse(gate.consume("stop", time(0), time(0), true) { false })
        assertTrue(observe(gate, "stop", 1))
    }

    @Test fun staleFutureDuplicateAndOutOfOrderObservationsCannotSpeak() {
        val gate = SecondaryTrafficSignSpeechGate()
        assertFalse(gate.consume("stop", time(0), time(3), true) { fail("Stale"); true })
        assertFalse(gate.consume("stop", time(5), time(4), true) { fail("Future"); true })
        assertTrue(gate.consume("stop", time(5), time(7), true) { true }) // Inclusive two-second freshness.
        assertFalse(gate.consume("give_way", time(5), time(7), true) { fail("Duplicate"); true })
        assertFalse(gate.consume("give_way", time(4), time(5), true) { fail("Out of order"); true })
    }

    @Test fun lifecycleResetClearsDedupAndCooldownButContextDeliveryResetDoesNot() {
        val gate = SecondaryTrafficSignSpeechGate()
        val delivery = TrafficSignDisplayDeliveryGate()
        assertTrue(delivery.accept(observation(0), 1, "drive"))
        assertTrue(observe(gate, "stop", 0))
        delivery.reset() // A road/city generation only resets admission, retaining speech history.
        assertTrue(delivery.accept(observation(1).copy(generation = 2), 2, "drive"))
        assertFalse(observe(gate, "stop", 1))
        gate.reset() // Preference, display, drive, camera, country or background lifecycle.
        assertTrue(observe(gate, "stop", 2))
    }

    @Test fun displayDeliveryRechecksSessionGenerationAndTimestampAfterPosting() {
        val gate = TrafficSignDisplayDeliveryGate()
        assertFalse(gate.accept(observation(10), 2, "drive"))
        assertFalse(gate.accept(observation(10), 1, "new-drive"))
        assertFalse(gate.accept(observation(10).copy(capturedAtUtc = null), 1, "drive"))
        assertTrue(gate.accept(observation(10), 1, "drive"))
        assertFalse(gate.accept(observation(10), 1, "drive"))
        assertFalse(gate.accept(observation(9), 1, "drive"))
        assertTrue(gate.accept(observation(11), 1, "drive"))
        gate.reset()
        assertTrue(gate.accept(observation(1).copy(generation = 2, driveSessionId = "new-drive"), 2, "new-drive"))
    }

    @Test fun submittedSpeechBlocksSecondaryBeforeEngineStartsAndOldCallbacksCannotClearNewSpeech() {
        val playback = TrafficSignSpeechPlaybackState()
        assertTrue(playback.isIdle(engineSpeaking = false))
        playback.begin("secondary-1", secondary = true)
        assertFalse(playback.isIdle(engineSpeaking = false))
        assertTrue(playback.hasSecondaryUtterance)
        playback.begin("speed-2", secondary = false) // QUEUE_FLUSH replaces the secondary.
        playback.finish("secondary-1") // Android may report its stop after submitting speed-2.
        assertFalse(playback.isIdle(engineSpeaking = false))
        assertFalse(playback.hasSecondaryUtterance)
        playback.finish("speed-2")
        assertTrue(playback.isIdle(engineSpeaking = false))
        assertFalse(playback.isIdle(engineSpeaking = true))
    }

    @Test fun secondaryCancellationNeverOwnsACapturePromptAndResetClearsPendingSpeech() {
        val playback = TrafficSignSpeechPlaybackState()
        playback.begin("secondary", secondary = true)
        playback.reset() // User starts capture, including pending-but-not-speaking audio.
        assertTrue(playback.isIdle(engineSpeaking = false))
        playback.begin("capture-prompt", secondary = false)
        assertFalse(playback.hasSecondaryUtterance)
        playback.finish("secondary")
        assertFalse(playback.isIdle(engineSpeaking = false))
        playback.finish("capture-prompt")
        assertTrue(playback.isIdle(engineSpeaking = false))
    }

    @Test fun onlyCombinedModeDisplayedMovingLiveSignsMayUseAnIdleSpeechLane() {
        assertTrue(allowed())
        assertFalse(allowed(mode = TrafficSignFeedbackMode.SPOKEN_SPEED))
        assertFalse(allowed(mode = TrafficSignFeedbackMode.SOUND))
        assertFalse(allowed(mode = TrafficSignFeedbackMode.SILENT))
        assertFalse(allowed(display = false))
        assertFalse(allowed(runtime = false))
        assertFalse(allowed(live = false))
        assertFalse(allowed(speed = 0.0))
        assertFalse(allowed(speed = 0.99))
        assertFalse(allowed(speed = Double.NaN))
        assertFalse(allowed(speed = Double.POSITIVE_INFINITY))
        assertTrue(allowed(speed = 1.0))
        assertFalse(allowed(captureIdle = false))
        assertFalse(allowed(speechIdle = false))
        assertFalse(allowed(primaryPending = true))
        assertFalse(allowed(visionDismissalIdle = false))
    }

    private fun allowed(mode: TrafficSignFeedbackMode = TrafficSignFeedbackMode.SPOKEN_SPEED_AND_SIGNS,
                        display: Boolean = true, runtime: Boolean = true, live: Boolean = true,
                        speed: Double = 30.0, captureIdle: Boolean = true, speechIdle: Boolean = true,
                        primaryPending: Boolean = false, visionDismissalIdle: Boolean = true) = SecondaryTrafficSignSpeechPolicy.canSpeak(
        mode, display, runtime, live, speed, captureIdle, speechIdle, primaryPending, visionDismissalIdle,
    )

    private fun observe(gate: SecondaryTrafficSignSpeechGate, classId: String, seconds: Long,
                        canSpeak: Boolean = true) = gate.consume(classId, time(seconds), time(seconds), canSpeak) { true }

    private fun time(seconds: Long) = Instant.parse("2026-09-01T10:00:00Z").plusSeconds(seconds)

    private fun observation(seconds: Long) = TrafficSignDisplayObservation(
        candidate = TrafficSignCandidate(
            rawClassId = "stop", rawLabel = "stop", semantic = TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN),
            rawScore = 0.95, calibratedConfidence = null,
            boundingBox = NormalizedTrafficSignBoundingBox(0.5, 0.2, 0.1, 0.2),
            proposalRawScore = 0.95, classifierRawScore = 0.95,
        ),
        generation = 1, driveSessionId = "drive", capturedAtUtc = time(seconds), source = TrafficSignInputSource.LIVE_FRAME,
    )

    private fun catalog(speech: String? = null) = TrafficSignDisplayCatalog.decode("""
        {"schema_version":1,"country":"DE","classifier_checkpoint_sha256":"test",
         "class_labels":["technical:class"],"signs":[{
           "class_id":"technical:class","display_eligible":true,
           "image_path":"tsr/sign-pictograms/png/de-205.png",
           "label":{"de":"technical:class","en":"technical:class","fr":"technical:class","nl":"technical:class"}
           ${speech?.let { ",\"speech\":$it" } ?: ""}
         }]}
    """.trimIndent())
}

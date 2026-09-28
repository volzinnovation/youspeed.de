package de.youspeed.android.alpha

/** Commands share the four languages for which the app ships an offline Vosk model. */
internal object VisionDismissalSpeech {
    const val listeningWindowMs = 4_000L
    const val maximumStartDelayMs = 3_000L
    const val resultDeliveryGraceMs = 350L

    fun command(language: SpeedCaptureLanguage): String = when (language) {
        SpeedCaptureLanguage.GERMAN -> "falsch"
        SpeedCaptureLanguage.ENGLISH -> "wrong"
        SpeedCaptureLanguage.FRENCH -> "faux"
        SpeedCaptureLanguage.DUTCH -> "fout"
    }

    fun accepts(transcript: String, language: SpeedCaptureLanguage): Boolean =
        SpeedCaptureSpeech.normalizeTranscript(transcript) == command(language)

    // The unknown path prevents every noise/utterance from being forced into the command.
    fun grammar(language: SpeedCaptureLanguage): String = "[\"${command(language)}\",\"[unk]\"]"
}

internal data class VisionDismissalEvidence(val generation: Long, val trackId: String, val speedKmh: Int)

/** Monotonic, one-shot ownership. Preview and finalized frames of one sign cannot reopen it. */
internal class VisionDismissalWindow {
    private val seen = linkedSetOf<Pair<String, Int>>()
    var evidence: VisionDismissalEvidence? = null; private set
    private var startDeadlineMs = 0L
    private var endDeadlineMs: Long? = null

    fun observe(next: VisionDismissalEvidence?, nowMs: Long, eligible: Boolean): Boolean {
        if (next == evidence && eligible && next != null) return false
        cancel()
        if (next == null || !seen.add(next.trackId to next.speedKmh)) return false
        if (seen.size > 128) seen.remove(seen.first())
        if (!eligible) return false
        evidence = next
        startDeadlineMs = nowMs + VisionDismissalSpeech.maximumStartDelayMs
        return true
    }

    fun begin(expected: VisionDismissalEvidence, nowMs: Long): Boolean {
        if (evidence != expected || endDeadlineMs != null || nowMs >= startDeadlineMs) return false
        endDeadlineMs = nowMs + VisionDismissalSpeech.listeningWindowMs
        return true
    }

    fun owns(expected: VisionDismissalEvidence, nowMs: Long): Boolean = evidence == expected &&
        endDeadlineMs?.let { nowMs <= it + VisionDismissalSpeech.resultDeliveryGraceMs } == true

    fun expired(nowMs: Long): Boolean = evidence != null && nowMs >=
        (endDeadlineMs?.plus(VisionDismissalSpeech.resultDeliveryGraceMs) ?: startDeadlineMs)
    fun cancel() { evidence = null; endDeadlineMs = null }
    fun resetForNewDrive() { cancel(); seen.clear() }
}

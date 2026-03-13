package de.youspeed.android.alpha

import java.util.Locale

enum class SpeedCaptureModeState {
    IDLE,
    REQUESTING_MIC_PERMISSION,
    PREPARING,
    SPEAKING_PROMPT,
    LISTENING,
    EVALUATING,
    SAVING,
    FAILED,
}

enum class GermanSpeechModelState {
    CHECKING,
    DOWNLOADING,
    PENDING,
    READY,
    UNAVAILABLE,
}

data class SpeedCaptureSelection(
    val value: String,
    val count: Int,
    val contextualPhrases: List<String>,
    val displayLabel: String,
) {
    val numericSpeedKmh: Int?
        get() = value.toIntOrNull()
}

object SpeedCaptureSpeech {
    const val speechLocaleTag: String = "de-DE"
    const val promptText: String = "Geschwindigkeit erfassen. Jetzt sprechen."
    const val listeningWindowMs: Long = 30_000L
    const val timeoutPaddingMs: Long = 350L
    const val startDelayMs: Long = 300L
    const val promptFallbackDelayMs: Long = 3_800L

    // Source: https://taginfo.openstreetmap.org/api/4/key/values?key=maxspeed&filter=all&lang=de&sortname=count&sortorder=desc&rp=26
    // Snapshot date: 2026-03-03
    val whitelistByPriority: List<SpeedCaptureSelection> = listOf(
        SpeedCaptureSelection(value = "50", count = 4_638_156, contextualPhrases = listOf("50", "fuenfzig"), displayLabel = "50 km/h"),
        SpeedCaptureSelection(value = "30", count = 4_230_894, contextualPhrases = listOf("30", "dreissig"), displayLabel = "30 km/h"),
        SpeedCaptureSelection(value = "40", count = 1_489_813, contextualPhrases = listOf("40", "vierzig"), displayLabel = "40 km/h"),
        SpeedCaptureSelection(value = "60", count = 1_296_509, contextualPhrases = listOf("60", "sechzig"), displayLabel = "60 km/h"),
        SpeedCaptureSelection(value = "80", count = 990_073, contextualPhrases = listOf("80", "achtzig"), displayLabel = "80 km/h"),
        SpeedCaptureSelection(value = "70", count = 716_723, contextualPhrases = listOf("70", "siebzig"), displayLabel = "70 km/h"),
        SpeedCaptureSelection(value = "100", count = 657_012, contextualPhrases = listOf("100", "hundert"), displayLabel = "100 km/h"),
        SpeedCaptureSelection(value = "20", count = 634_365, contextualPhrases = listOf("20", "zwanzig"), displayLabel = "20 km/h"),
        SpeedCaptureSelection(value = "90", count = 480_306, contextualPhrases = listOf("90", "neunzig"), displayLabel = "90 km/h"),
        SpeedCaptureSelection(value = "120", count = 266_492, contextualPhrases = listOf("120", "hundertzwanzig"), displayLabel = "120 km/h"),
        SpeedCaptureSelection(value = "10", count = 157_726, contextualPhrases = listOf("10", "zehn"), displayLabel = "10 km/h"),
        SpeedCaptureSelection(value = "110", count = 152_915, contextualPhrases = listOf("110", "hundertzehn"), displayLabel = "110 km/h"),
        SpeedCaptureSelection(value = "130", count = 111_960, contextualPhrases = listOf("130", "hundertdreissig"), displayLabel = "130 km/h"),
        SpeedCaptureSelection(
            value = "walk",
            count = 5_788,
            contextualPhrases = listOf("fussgaengerzone", "fussgaenger zone", "walk"),
            displayLabel = "Fussgaengerzone",
        ),
    )

    val contextualStrings: ArrayList<String> = ArrayList<String>().apply {
        val seen = linkedSetOf<String>()
        whitelistByPriority.forEach { entry ->
            (listOf(entry.value) + entry.contextualPhrases).forEach { token ->
                if (seen.add(token)) {
                    add(token)
                }
            }
        }
    }

    val voskGrammarJson: String = listOf(
            "10",
            "20",
            "30",
            "40",
            "50",
            "60",
            "70",
            "80",
            "90",
            "100",
            "110",
            "120",
            "130",
            "zehn",
            "zwanzig",
            "dreissig",
            "dreißig",
            "vierzig",
            "fuenfzig",
            "fünfzig",
            "sechzig",
            "siebzig",
            "achtzig",
            "neunzig",
            "hundert",
            "hundert zehn",
            "hundertzehn",
            "einhundert zehn",
            "einhundertzehn",
            "hundert zwanzig",
            "hundertzwanzig",
            "einhundert zwanzig",
            "einhundertzwanzig",
            "hundert dreissig",
            "hundertdreißig",
            "hundertdreissig",
            "einhundert dreissig",
            "einhundertdreißig",
            "einhundertdreissig",
            "fussgaengerzone",
            "fußgängerzone",
            "fussgaenger zone",
            "fußgänger zone",
            "fussgaengerbereich",
            "fußgängerbereich",
            "walk",
            "[unk]",
        )
        .joinToString(
            separator = ",",
            prefix = "[",
            postfix = "]",
        ) { phrase ->
            "\"${phrase.replace("\\", "\\\\").replace("\"", "\\\"")}\""
        }

    private val valueSet: Set<String> = whitelistByPriority.mapTo(linkedSetOf(), SpeedCaptureSelection::value)

    private val phraseToValue: Map<String, String> = linkedMapOf(
        "zehn" to "10",
        "zwanzig" to "20",
        "dreissig" to "30",
        "vierzig" to "40",
        "fuenfzig" to "50",
        "sechzig" to "60",
        "siebzig" to "70",
        "achtzig" to "80",
        "neunzig" to "90",
        "hundert" to "100",
        "hundert zehn" to "110",
        "hundertzehn" to "110",
        "einhundert zehn" to "110",
        "einhundertzehn" to "110",
        "hundert zwanzig" to "120",
        "hundertzwanzig" to "120",
        "einhundert zwanzig" to "120",
        "einhundertzwanzig" to "120",
        "hundert dreissig" to "130",
        "hundertdreissig" to "130",
        "einhundert dreissig" to "130",
        "einhundertdreissig" to "130",
        "fussgaengerzone" to "walk",
        "fussgaenger zone" to "walk",
        "fussgaengerbereich" to "walk",
        "walk" to "walk",
    )

    fun resolveSelection(transcript: String): SpeedCaptureSelection? {
        val normalized = normalizeTranscript(transcript)
        if (normalized.isEmpty()) {
            return null
        }
        val candidateScores = linkedMapOf<String, Int>()
        Regex("""\b([0-9]{2,3})\b""")
            .findAll(normalized)
            .forEach { match ->
                val token = match.groupValues.getOrNull(1).orEmpty()
                if (token in valueSet) {
                    candidateScores[token] = maxOf(candidateScores[token] ?: 0, 1)
                }
            }
        phraseToValue.forEach { (phrase, value) ->
            val regex = Regex("""(?:^|\s)${Regex.escape(phrase)}(?:$|\s)""")
            if (regex.containsMatchIn(normalized)) {
                candidateScores[value] = maxOf(candidateScores[value] ?: 0, phrase.length)
            }
        }
        val bestScore = candidateScores.values.maxOrNull() ?: return null
        val bestValues = candidateScores.filterValues { it == bestScore }.keys
        return whitelistByPriority.firstOrNull { it.value in bestValues }
    }

    fun selectionForValue(rawValue: String): SpeedCaptureSelection? {
        val normalized = normalizeManualValue(rawValue) ?: return null
        return whitelistByPriority.firstOrNull { it.value == normalized }
    }

    fun normalizeTranscript(raw: String): String {
        return raw
            .lowercase(Locale.US)
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
            .replace(Regex("[^a-z0-9]+"), " ")
            .trim()
    }

    private fun normalizeManualValue(rawValue: String): String? {
        val trimmed = rawValue.trim()
        if (trimmed.isEmpty()) {
            return null
        }
        val digitsOnly = trimmed.filter(Char::isDigit)
        if (digitsOnly.isNotEmpty()) {
            return digitsOnly
        }
        return when (normalizeTranscript(trimmed)) {
            "walk", "fussgaengerzone", "fussgaenger zone", "fussgaengerbereich" -> "walk"
            else -> null
        }
    }
}

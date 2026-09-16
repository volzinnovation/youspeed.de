package de.youspeed.android.alpha

import java.util.Locale
import java.text.Normalizer

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

enum class SpeechModelState {
    CHECKING,
    DOWNLOADING,
    PENDING,
    READY,
    UNAVAILABLE,
}

/** Kept as a source-compatible alias for older controller/test names. */
typealias GermanSpeechModelState = SpeechModelState

enum class SpeedCaptureLanguage(
    val localeTag: String,
    val modelAssetPath: String,
    val promptText: String,
    val promptStatusText: String,
    val listeningStatus: String,
    val displayName: String,
) {
    GERMAN(
        "de-DE", "vosk-model-small-de-0.15", "Korrektur",
        "Korrektur. Bitte auf Deutsch sprechen.", "Jetzt sprechen: 10 bis 130 oder Fußgängerzone.", "Deutsch",
    ),
    FRENCH(
        "fr-FR", "vosk-model-small-fr-0.22", "Correction",
        "Correction. Parlez en français.", "Parlez maintenant : 10 à 130 ou zone piétonne.", "Français",
    ),
    DUTCH(
        "nl-NL", "vosk-model-small-nl-0.22", "Correctie",
        "Correctie. Spreek in het Nederlands.", "Spreek nu: 10 tot 130 of voetgangersgebied.", "Nederlands",
    ),
    ENGLISH(
        "en-US", "vosk-model-small-en-us-0.15", "Correction",
        "Correction. Speak in English.", "Speak now: 10 to 130 or pedestrian zone.", "English",
    );

    companion object {
        fun forLocale(locale: Locale): SpeedCaptureLanguage = when (locale.language.lowercase(Locale.ROOT)) {
            "fr" -> FRENCH
            "nl" -> DUTCH
            "de" -> GERMAN
            "en" -> ENGLISH
            else -> ENGLISH
        }
    }
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

/** Partial hypotheses may be displayed but never become a saved correction. */
internal class SpeedCaptureTranscriptBuffer {
    var partialTranscript: String = ""
        private set
    private var completedCandidates: List<String> = emptyList()

    fun updatePartial(transcript: String) { partialTranscript = transcript.trim() }

    fun acceptCompleted(transcripts: List<String>): List<String> {
        val candidates = transcripts.map(String::trim).filter(String::isNotEmpty).distinct()
        if (candidates.isNotEmpty()) completedCandidates = candidates
        return completedCandidates
    }

    fun finalCandidates(): List<String> = completedCandidates
}

object SpeedCaptureSpeech {
    const val listeningWindowMs: Long = 4_000L
    const val timeoutPaddingMs: Long = 350L
    const val startDelayMs: Long = 300L
    const val promptFallbackDelayMs: Long = 3_800L

    private val profiles: Map<SpeedCaptureLanguage, SpeedCaptureSpeechProfile> = mapOf(
        SpeedCaptureLanguage.GERMAN to SpeedCaptureSpeechProfile(
            language = SpeedCaptureLanguage.GERMAN,
            numberWords = linkedMapOf(
                "zehn" to "10", "zwanzig" to "20", "dreissig" to "30", "vierzig" to "40",
                "fuenfzig" to "50", "sechzig" to "60", "siebzig" to "70", "achtzig" to "80",
                "neunzig" to "90", "hundert" to "100", "hundert zehn" to "110", "hundertzehn" to "110",
                "einhundert zehn" to "110", "einhundertzehn" to "110", "hundert zwanzig" to "120",
                "hundertzwanzig" to "120", "einhundert zwanzig" to "120", "einhundertzwanzig" to "120",
                "hundert dreissig" to "130", "hundertdreissig" to "130", "einhundert dreissig" to "130",
                "einhundertdreissig" to "130", "fussgaengerzone" to "walk", "fussgaenger zone" to "walk",
                "fussgaengerbereich" to "walk", "walk" to "walk",
            ),
            grammarPhrases = listOf(
                "zehn", "zwanzig", "dreissig", "dreißig", "vierzig", "fuenfzig", "fünfzig", "sechzig",
                "siebzig", "achtzig", "neunzig", "hundert", "hundert zehn", "hundertzehn", "einhundert zehn",
                "einhundertzehn", "hundert zwanzig", "hundertzwanzig", "einhundert zwanzig", "einhundertzwanzig",
                "hundert dreissig", "hundertdreißig", "hundertdreissig", "einhundert dreissig", "einhundertdreißig",
                "einhundertdreissig", "fussgaengerzone", "fußgängerzone", "fussgaenger zone", "fußgänger zone",
                "fussgaengerbereich", "fußgängerbereich", "walk",
            ),
            pedestrianPhrases = listOf("fussgaengerzone", "fussgaenger zone", "fussgaengerbereich", "walk"),
        ),
        SpeedCaptureLanguage.FRENCH to SpeedCaptureSpeechProfile(
            language = SpeedCaptureLanguage.FRENCH,
            numberWords = linkedMapOf(
                "dix" to "10", "vingt" to "20", "trente" to "30", "quarante" to "40", "cinquante" to "50",
                "soixante" to "60", "soixante dix" to "70", "quatre vingt" to "80", "quatre vingts" to "80",
                "quatre vingt dix" to "90", "cent" to "100", "cent dix" to "110", "cent vingt" to "120",
                "cent trente" to "130", "zone pietonne" to "walk", "zone pieton" to "walk", "walk" to "walk",
            ),
            grammarPhrases = listOf(
                "dix", "vingt", "trente", "quarante", "cinquante", "soixante", "soixante dix", "soixante-dix",
                "quatre vingt", "quatre-vingt", "quatre vingts", "quatre-vingts", "quatre vingt dix",
                "quatre-vingt-dix", "cent", "cent dix", "cent-dix", "cent vingt", "cent-vingt", "cent trente",
                "cent-trente", "zone pietonne", "zone piétonne", "zone pieton", "zone piéton", "walk",
            ),
            pedestrianPhrases = listOf("zone pietonne", "zone pieton", "walk"),
        ),
        SpeedCaptureLanguage.DUTCH to SpeedCaptureSpeechProfile(
            language = SpeedCaptureLanguage.DUTCH,
            numberWords = linkedMapOf(
                "tien" to "10", "twintig" to "20", "dertig" to "30", "veertig" to "40", "vijftig" to "50",
                "zestig" to "60", "zeventig" to "70", "tachtig" to "80", "negentig" to "90", "honderd" to "100",
                "honderd tien" to "110", "honderdtien" to "110", "honderd twintig" to "120", "honderdtwintig" to "120",
                "honderd dertig" to "130", "honderddertig" to "130", "voetgangersgebied" to "walk",
                "voetgangers zone" to "walk", "voetgangerszone" to "walk", "walk" to "walk",
            ),
            grammarPhrases = listOf(
                "tien", "twintig", "dertig", "veertig", "vijftig", "zestig", "zeventig", "tachtig", "negentig",
                "honderd", "honderd tien", "honderdtien", "honderd twintig", "honderdtwintig", "honderd dertig",
                "honderddertig", "voetgangersgebied", "voetgangers zone", "voetgangerszone", "walk",
            ),
            pedestrianPhrases = listOf("voetgangersgebied", "voetgangers zone", "voetgangerszone", "walk"),
        ),
        SpeedCaptureLanguage.ENGLISH to SpeedCaptureSpeechProfile(
            language = SpeedCaptureLanguage.ENGLISH,
            numberWords = linkedMapOf(
                "ten" to "10", "twenty" to "20", "thirty" to "30", "forty" to "40", "fifty" to "50",
                "sixty" to "60", "seventy" to "70", "eighty" to "80", "ninety" to "90", "one hundred" to "100",
                "one hundred ten" to "110", "one hundred twenty" to "120", "one hundred thirty" to "130",
                "one hundred and ten" to "110", "one hundred and twenty" to "120", "one hundred and thirty" to "130",
                "pedestrian zone" to "walk", "pedestrians zone" to "walk", "walk" to "walk",
            ),
            grammarPhrases = listOf(
                "ten", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
                "one hundred", "one hundred ten", "one hundred and ten", "one hundred twenty",
                "one hundred and twenty", "one hundred thirty", "one hundred and thirty", "pedestrian zone",
                "pedestrians zone", "walk",
            ),
            pedestrianPhrases = listOf("pedestrian zone", "pedestrians zone", "walk"),
        ),
    )

    val speechLocaleTag: String get() = profileFor(SpeedCaptureLanguage.GERMAN).language.localeTag
    val promptText: String get() = profileFor(SpeedCaptureLanguage.GERMAN).language.promptText
    val whitelistByPriority: List<SpeedCaptureSelection> get() = profileFor(SpeedCaptureLanguage.GERMAN).whitelist
    val contextualStrings: ArrayList<String> get() = ArrayList(profileFor(SpeedCaptureLanguage.GERMAN).contextualStrings)
    val voskGrammarJson: String get() = profileFor(SpeedCaptureLanguage.GERMAN).voskGrammarJson

    fun profileFor(language: SpeedCaptureLanguage): SpeedCaptureSpeechProfile = profiles.getValue(language)

    fun languageFor(locale: Locale): SpeedCaptureLanguage = SpeedCaptureLanguage.forLocale(locale)

    fun resolveSelection(transcript: String, language: SpeedCaptureLanguage = SpeedCaptureLanguage.GERMAN): SpeedCaptureSelection? {
        val profile = profileFor(language)
        val normalized = normalizeTranscript(transcript)
        if (normalized.isEmpty()) return null
        val candidateScores = linkedMapOf<String, Int>()
        Regex("""\b([0-9]{2,3})\b""").findAll(normalized).forEach { match ->
            val token = match.groupValues.getOrNull(1).orEmpty()
            if (token in profile.valueSet) candidateScores[token] = maxOf(candidateScores[token] ?: 0, 1)
        }
        profile.phraseToValue.forEach { (phrase, value) ->
            val regex = Regex("""(?:^|\s)${Regex.escape(phrase)}(?:$|\s)""")
            if (regex.containsMatchIn(normalized)) candidateScores[value] = maxOf(candidateScores[value] ?: 0, phrase.length)
        }
        val bestScore = candidateScores.values.maxOrNull() ?: return null
        val bestValues = candidateScores.filterValues { it == bestScore }.keys
        return profile.whitelist.firstOrNull { it.value in bestValues }
    }

    fun selectionForValue(rawValue: String, language: SpeedCaptureLanguage = SpeedCaptureLanguage.GERMAN): SpeedCaptureSelection? {
        val normalized = normalizeManualValue(rawValue, language) ?: return null
        return profileFor(language).whitelist.firstOrNull { it.value == normalized }
    }

    fun normalizeTranscript(raw: String): String {
        val germanFolded = raw.lowercase(Locale.ROOT)
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        val folded = Normalizer.normalize(germanFolded, Normalizer.Form.NFD)
            .replace(Regex("\\p{M}+"), "")
        return folded
            .replace(Regex("[^a-z0-9]+"), " ").trim()
    }

    private fun normalizeManualValue(rawValue: String, language: SpeedCaptureLanguage): String? {
        val trimmed = rawValue.trim()
        if (trimmed.isEmpty()) return null
        val digitsOnly = trimmed.filter(Char::isDigit)
        if (digitsOnly.isNotEmpty()) return digitsOnly
        val normalized = normalizeTranscript(trimmed)
        return profileFor(language).phraseToValue[normalized]
    }
}

data class SpeedCaptureSpeechProfile(
    val language: SpeedCaptureLanguage,
    private val numberWords: Map<String, String>,
    private val grammarPhrases: List<String>,
    private val pedestrianPhrases: List<String>,
) {
    private val speedEntries = listOf("10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "110", "120", "130")
    val phraseToValue: Map<String, String> = numberWords
    val valueSet: Set<String> = (speedEntries + "walk").toSet()
    val whitelist: List<SpeedCaptureSelection> = speedEntries.map { value ->
        SpeedCaptureSelection(value, 0, numberWords.filterValues { it == value }.keys.toList(), "$value km/h")
    } + SpeedCaptureSelection("walk", 0, pedestrianPhrases, when (language) {
        SpeedCaptureLanguage.GERMAN -> "Fussgaengerzone"
        SpeedCaptureLanguage.FRENCH -> "Zone piétonne"
        SpeedCaptureLanguage.DUTCH -> "Voetgangersgebied"
        SpeedCaptureLanguage.ENGLISH -> "Pedestrian zone"
    })
    val contextualStrings: List<String> = (whitelist.flatMap { listOf(it.value) + it.contextualPhrases }).distinct()
    val voskGrammarJson: String = (speedEntries + grammarPhrases + pedestrianPhrases + "[unk]")
        .distinct().joinToString(separator = ",", prefix = "[", postfix = "]") { phrase ->
            "\"${phrase.replace("\\", "\\\\").replace("\"", "\\\"")}\""
        }
}

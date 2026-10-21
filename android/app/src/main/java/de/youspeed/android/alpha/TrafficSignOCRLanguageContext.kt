package de.youspeed.android.alpha

import com.google.android.gms.tasks.Tasks
import com.google.mlkit.nl.languageid.LanguageIdentification
import java.util.Locale
import java.util.concurrent.TimeUnit

/** Road language is independent of UI language. No country-wide language guess for CH/BE. */
internal object TrafficSignOCRLanguageContext {
    @Volatile private var country: String? = null
    private val prepared = LinkedHashMap<String, String>()
    private val identifier by lazy { LanguageIdentification.getClient() }

    fun warmUp() { runCatching { Tasks.await(identifier.identifyPossibleLanguages("Synthetic language warmup"), 1, TimeUnit.SECONDS) } }

    fun configure(countryCode: String?) { country = countryCode?.uppercase(Locale.ROOT) }

    fun languages(countryCode: String?): List<String> = when (countryCode?.uppercase(Locale.ROOT)) {
        "DE", "DEU", "LI", "LIE" -> listOf("de-DE")
        "FR", "FRA", "MC", "MCO" -> listOf("fr-FR")
        "NL", "NLD" -> listOf("nl-NL")
        "BE", "BEL" -> listOf("nl-BE", "fr-BE", "de-BE")
        "CH", "CHE" -> listOf("de-CH", "fr-CH", "it-CH", "rm-CH")
        "LU", "LUX" -> listOf("fr-LU", "de-LU", "lb-LU")
        "RO", "ROU" -> listOf("ro-RO")
        "SE", "SWE" -> listOf("sv-SE")
        "IS", "ISL" -> listOf("is-IS")
        else -> listOf("de-DE", "fr-FR", "nl-NL", "it-IT", "en-GB")
    }

    fun resolve(text: String, candidates: List<String>, hypotheses: Map<String, Double> = emptyMap()): String? {
        if (candidates.size == 1) return candidates.first()
        val words = text.lowercase(Locale.ROOT).split(Regex("[^\\p{L}]+" )).filter(String::isNotEmpty).toSet()
        val cues = mapOf(
            "de" to setOf("werktags", "nässe", "schulweg", "ausgenommen", "anlieger", "frei", "uhr"),
            "fr" to setOf("sauf", "école", "pluie", "riverains", "heures"),
            "nl" to setOf("uitgezonderd", "school", "nat", "wegdek", "uur"),
            "it" to setOf("lunedi", "lunedì", "martedì", "venerdì", "eccetto", "escluso", "scuola", "pioggia", "ore"),
            "rm" to setOf("scola", "exceptà", "lavurdis"), "lb" to setOf("ausser", "schoul"),
        )
        val evidenced = cues.filterValues { it.intersect(words).isNotEmpty() }.keys.toMutableSet()
        if (words.containsAll(listOf("mo", "fr"))) evidenced.add("de")
        if (words.containsAll(listOf("ma", "vr"))) evidenced.add("nl")
        if (evidenced.size > 1) return null
        val allowed = candidates.map { it.take(2) }.toSet()
        evidenced.singleOrNull()?.takeIf { it in allowed }?.let { language ->
            return candidates.firstOrNull { it.startsWith("$language-") }
        }
        if (words.joinToString("").length < 12) return null
        val ranked = hypotheses.entries.sortedByDescending { it.value }
        val best = ranked.firstOrNull() ?: return null
        if (best.key !in allowed || best.value < .75 || best.value - (ranked.getOrNull(1)?.value ?: 0.0) < .20) return null
        return candidates.firstOrNull { it.startsWith("${best.key}-") }
    }

    /** On the existing OCR worker only; the bundled identifier needs no network. */
    fun prepare(text: String) {
        val candidates = languages(country)
        var resolved = resolve(text, candidates)
        if (candidates.size > 1) {
            val blocks = listOf(text) + text.lines().take(6).filter { line -> line.count(Char::isLetter) >= 12 }
            val scores = runCatching {
                val tasks = blocks.map { identifier.identifyPossibleLanguages(it) }
                Tasks.await(Tasks.whenAllComplete(tasks), 250, TimeUnit.MILLISECONDS)
                tasks.map { task -> task.result.associate { it.languageTag to it.confidence.toDouble() } }
            }.getOrNull()
            if (scores != null) {
                resolved = resolve(text, candidates, scores.first())
                val lineLanguages = blocks.drop(1).mapIndexedNotNull { index, line -> resolve(line, candidates, scores[index + 1]) }.toSet()
                if (lineLanguages.size > 1) resolved = null
            }
        }
        synchronized(prepared) {
            if (prepared.size >= 128) prepared.clear()
            prepared[candidates.joinToString(",") + "|" + text] = resolved ?: ""
        }
    }

    fun speechLocale(text: String): Locale? {
        val candidates = languages(country)
        val tag = synchronized(prepared) { prepared[candidates.joinToString(",") + "|" + text] }
            ?: resolve(text, candidates)
        return tag?.takeIf(String::isNotEmpty)?.let(Locale::forLanguageTag)
    }
}

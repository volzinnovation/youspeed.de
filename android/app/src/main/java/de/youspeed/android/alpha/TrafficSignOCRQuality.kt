package de.youspeed.android.alpha

import java.text.Normalizer
import java.util.Locale

data class TrafficSignOCRPass(val text: String, val confidence: Double, val scale: Int, val uncoveredInk: Boolean = false)
internal object TrafficSignOCRQuality {
    fun comparison(text: String): String = Normalizer.normalize(text, Normalizer.Form.NFKC)
        .lowercase(Locale.ROOT).filter { it.isLetterOrDigit() }
    fun selected(passes: List<TrafficSignOCRPass>): TrafficSignOCRPass? {
        val last = passes.lastOrNull() ?: return null
        fun plain(value: String) = Normalizer.normalize(value, Normalizer.Form.NFD).replace(Regex("\\p{M}"), "")
        val normalized = comparison(last.text); val folded = plain(normalized)
        return passes.dropLast(1).firstOrNull {
            val value = comparison(it.text)
            !it.uncoveredInk && it.confidence >= .25 && value != normalized && plain(value) == folded && normalized == folded
        } ?: last
    }
    fun decision(passes: List<TrafficSignOCRPass>, nativeWidth: Int): String {
        val chosen = selected(passes) ?: return "empty"
        val others = passes.filter { it != chosen }
        if (chosen.uncoveredInk) return "incomplete_plate"
        val text = comparison(chosen.text)
        if (text.length < 2 || chosen.confidence < 0.25) return "symbol_or_uncertain"
        if (text in setOf("zone", "lone", "lune") || (text.all { it.isDigit() } && TrafficSignSupplementaryTimeWindow.parse(chosen.text) == null)) return "primary_or_symbol"
        if (others.any { it.text.count(Char::isDigit) > chosen.text.count(Char::isDigit) }) return "lost_numeric_clause"
        val digits = text.filter { it.isDigit() }
        if (digits.isNotEmpty()) {
            if (passes.size < 2 || others.none { it.text.isNotEmpty() && it.text.filter(Char::isDigit) == chosen.text.filter(Char::isDigit) }) return "numeric_disagreement"
            if (digits.length >= 6 && nativeWidth.toDouble()/text.length < 8) return "insufficient_native_detail"
        }
        if (Regex("(?:^[TIil|↑↕]+\\s*\\d|[TIil1]\\s*$)", RegexOption.IGNORE_CASE).containsMatchIn(chosen.text) &&
            Regex("\\d\\s*(?:m|km)", RegexOption.IGNORE_CASE).containsMatchIn(chosen.text)) return "ambiguous_arrow"
        return "accepted"
    }
}

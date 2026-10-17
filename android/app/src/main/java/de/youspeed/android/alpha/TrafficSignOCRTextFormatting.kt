package de.youspeed.android.alpha

import java.util.Locale

/** Formatting only. Keep all clauses and the original collected text; never evaluate conditions. */
internal object TrafficSignOCRTextFormatting {
    fun display(raw: String): String {
        val normal = raw.map { c -> "⁰¹²³⁴⁵⁶⁷⁸⁹".indexOf(c).let { if (it < 0) c else '0' + it } }.joinToString("")
        return Regex("(?<!\\d)(\\d{3,4})\\s*[-–—_−]\\s*(\\d{3,4})\\s*h(?!\\p{L})", RegexOption.IGNORE_CASE).replace(normal) { match ->
            fun time(value: String): String? {
                val hour = value.dropLast(2).toIntOrNull() ?: return null
                val minute = value.takeLast(2).toIntOrNull() ?: return null
                return if (hour < 24 && minute < 60) String.format(Locale.ROOT, "%d:%02d", hour, minute) else null
            }
            val start = time(match.groupValues[1]); val end = time(match.groupValues[2])
            if (start != null && end != null) "$start–$end h" else match.value
        }
    }
    fun speech(raw: String, locale: Locale): String {
        var text = Regex("(?<!\\d)\\d{1,2}(?::[0-5]\\d)?\\s*[-–—_−]\\s*\\d{1,2}(?::[0-5]\\d)?\\s*h(?!\\p{L})", RegexOption.IGNORE_CASE).replace(display(raw)) {
            TrafficSignSupplementaryTimeWindow.parse(it.value.replace('_', '–'))?.spokenText(locale) ?: it.value
        }
        val weekday = when (locale.language) {
            "de" -> "\\bMo\\s*[-–]\\s*Fr\\b" to "Montag bis Freitag"
            "fr" -> "\\bLu\\s*[-–]\\s*Ve\\b" to "lundi à vendredi"
            "nl" -> "\\bMa\\s*[-–]\\s*Vr\\b" to "maandag tot vrijdag"
            "it" -> "\\bLu\\s*[-–]\\s*Ve\\b" to "lunedì a venerdì"
            else -> null
        }
        if (weekday != null) text = Regex(weekday.first, RegexOption.IGNORE_CASE).replace(text, weekday.second)
        return text.trim().split(Regex("\\s+")).joinToString(" ")
    }
}

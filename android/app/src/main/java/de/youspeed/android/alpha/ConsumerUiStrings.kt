package de.youspeed.android.alpha

import java.util.Locale

/** Text used by presentation logic that also runs outside an Android context. */
internal object ConsumerUiStrings {
    fun text(en: String, de: String, fr: String, nl: String, locale: Locale = Locale.getDefault()): String =
        when (locale.language.lowercase(Locale.ROOT)) {
            "de" -> de
            "fr" -> fr
            "nl" -> nl
            else -> en
        }
}

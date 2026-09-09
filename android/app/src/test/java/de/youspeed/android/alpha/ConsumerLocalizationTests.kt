package de.youspeed.android.alpha

import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConsumerLocalizationTests {
    @Test
    fun belgianLocalesSelectTheirLanguageForRuntimeMessages() {
        assertEquals(
            "La reconnaissance par caméra est active.",
            ConsumerRuntimeText.CAMERA_ACTIVE.text(locale = Locale.forLanguageTag("fr-BE")),
        )
        assertEquals(
            "Cameraherkenning is actief.",
            ConsumerRuntimeText.CAMERA_ACTIVE.text(locale = Locale.forLanguageTag("nl-BE")),
        )
        assertEquals(
            "Kamera-Erkennung ist aktiv.",
            ConsumerRuntimeText.CAMERA_ACTIVE.text(locale = Locale.forLanguageTag("de-BE")),
        )
        assertEquals(
            "Carte adaptée prête hors ligne : Bruxelles.",
            ConsumerRuntimeText.MATCHING_MAP_READY.text("Bruxelles", locale = Locale.forLanguageTag("fr-BE")),
        )
    }

    @Test
    fun everyRuntimeTranslationFormatsWithoutLeakingPlaceholders() {
        for (tag in listOf("en", "de", "fr-FR", "fr-BE", "nl-NL", "nl-BE", "de-BE")) {
            for (message in ConsumerRuntimeText.entries) {
                val rendered = message.text("one", "two", "three", locale = Locale.forLanguageTag(tag))
                assertTrue("$tag ${message.name}", rendered.isNotBlank())
                assertFalse("$tag ${message.name}", Regex("%[1-3]\\\$s").containsMatchIn(rendered))
            }
        }
    }

    @Test
    fun initialControllerStateUsesTheCurrentLanguage() {
        val previous = Locale.getDefault()
        try {
            Locale.setDefault(Locale.forLanguageTag("nl-BE"))
            val state = ConsumerUiState()
            assertEquals("Kaartselectie wacht op de eerste GPS-locatie.", state.firstLocationPackStatus)
            assertEquals("Cameraherkenning is uitgeschakeld.", state.trafficSignCameraRuntimeDetail)
            assertEquals("Verkeersbordmodel: land nog niet bepaald.", state.countryModelPackStatus)
        } finally {
            Locale.setDefault(previous)
        }
    }
}

package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class TrafficSignOCRLanguageContextTests {
    @Test fun countryLanguagesIgnoreDeviceLanguage() {
        assertEquals(listOf("fr-FR"), TrafficSignOCRLanguageContext.languages("FRA"))
        assertEquals(listOf("de-CH", "fr-CH", "it-CH", "rm-CH"), TrafficSignOCRLanguageContext.languages("CH"))
        assertEquals(listOf("nl-BE", "fr-BE", "de-BE"), TrafficSignOCRLanguageContext.languages("BEL"))
    }
    @Test fun multilingualCountriesUseTextAndAbstainForAmbiguity() {
        val ch = TrafficSignOCRLanguageContext.languages("CH")
        val be = TrafficSignOCRLanguageContext.languages("BE")
        assertEquals("de-CH", TrafficSignOCRLanguageContext.resolve("Mo-Fr\n630-1730 h", ch))
        assertEquals("fr-CH", TrafficSignOCRLanguageContext.resolve("sauf riverains", ch))
        assertEquals("it-CH", TrafficSignOCRLanguageContext.resolve("eccetto scuola", ch))
        assertEquals("nl-BE", TrafficSignOCRLanguageContext.resolve("uitgezonderd fietsers", be))
        for (text in listOf("22-6 h", "Lu-Ve", "P")) assertNull(TrafficSignOCRLanguageContext.resolve(text, ch))
        assertNull(TrafficSignOCRLanguageContext.resolve("sauf riverains\nuitgezonderd fietsers", be))
    }
    @Test fun confidenceCannotForceForeignOrUncertainTextIntoLocalLanguage() {
        val ch = TrafficSignOCRLanguageContext.languages("CH")
        assertNull(TrafficSignOCRLanguageContext.resolve("abcdefghijklmnop", ch, mapOf("en" to .95, "de" to .04)))
        assertNull(TrafficSignOCRLanguageContext.resolve("abcdefghijklmnop", ch, mapOf("fr" to .60, "it" to .40)))
        assertEquals("it-CH", TrafficSignOCRLanguageContext.resolve("abcdefghijklmnop", ch, mapOf("it" to .90, "fr" to .05)))
        assertEquals("fr-FR", TrafficSignOCRLanguageContext.resolve("22-6 h", listOf("fr-FR")))
    }
}

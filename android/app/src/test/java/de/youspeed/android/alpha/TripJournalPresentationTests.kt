package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test
import java.util.Locale

class TripJournalPresentationTests {
    @Test fun historyDistanceUsesOneLocalizedDecimal() {
        assertEquals("1,2",TripJournalPresentation.distanceKilometres(1234.0,Locale.GERMANY))
        assertEquals("1.2",TripJournalPresentation.distanceKilometres(1234.0,Locale.US))
        assertEquals("0,0",TripJournalPresentation.distanceKilometres(0.0,Locale.GERMANY))
    }
    @Test fun optionalEndingReadingAcceptsDecimalCommaButRejectsInvalidFacts() {
        assertEquals(12000.5,TripJournalPresentation.endingKilometres("12000,5",12000.0)!!,0.0)
        for(value in listOf("","NaN","Infinity","-1","11999,9","1,2,3")) assertNull(value,TripJournalPresentation.endingKilometres(value,12000.0))
    }
}

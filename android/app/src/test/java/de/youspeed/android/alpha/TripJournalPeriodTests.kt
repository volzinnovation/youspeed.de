package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class TripJournalPeriodTests {
    private val zone=ZoneId.of("Europe/Berlin")
    @Test fun sevenLocalDatesIncludeTodayAcrossClockChange() {
        val (start,end)=TripJournalPeriod.bounds(LocalDate.of(2026,10,26),zone,7)
        assertEquals(LocalDate.of(2026,10,20).atStartOfDay(zone).toEpochSecond().toDouble(),start,0.0)
        assertEquals(LocalDate.of(2026,10,27).atStartOfDay(zone).toEpochSecond().toDouble(),end,0.0)
        assertEquals(169*3600.0,end-start,0.0)
    }
    @Test fun customInclusiveDatesOverridePresetAndSelectWholeStartDates() {
        val (start,end)=TripJournalPeriod.bounds(LocalDate.of(2026,10,23),zone,7,"2026-01-01","2026-01-31")
        assertEquals(LocalDate.of(2026,1,1).atStartOfDay(zone).toEpochSecond().toDouble(),start,0.0)
        assertEquals(LocalDate.of(2026,2,1).atStartOfDay(zone).toEpochSecond().toDouble(),end,0.0)
        assertTrue(TripJournalPeriod.validCustom("2026-01-01","2026-01-31"))
    }
    @Test fun incompleteInvalidAndInvertedCustomDatesNeverBroadenSelection() {
        listOf("" to "2026-01-31","2026-01-01" to "","invalid" to "2026-01-31","2026-02-30" to "2026-03-01","2026-02-01" to "2026-01-31").forEach {(from,to)->
            assertFalse(TripJournalPeriod.validCustom(from,to))
            val (lower,upper)=TripJournalPeriod.bounds(LocalDate.of(2026,10,23),zone,7,from,to)
            assertFalse(1_800_000_000.0>=lower && 1_800_000_000.0<upper)
        }
        assertTrue(TripJournalPeriod.validCustom("",""))
        assertEquals(TripJournalPeriod.bounds(LocalDate.of(2026,10,23),zone,7),TripJournalPeriod.bounds(LocalDate.of(2026,10,23),zone,7,"",""))
    }
}

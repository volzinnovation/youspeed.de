package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class TripMediaClockTests {
    @Test fun segmentBoundarySelectsOnlyOwningInterval() {
        assertEquals(9.5,TripMediaClock.offset(109.5,100.0,10.0)!!,0.0)
        assertNull(TripMediaClock.offset(110.0,100.0,10.0))
        assertEquals(0.0,TripMediaClock.offset(110.0,110.0,10.0)!!,0.0)
        assertEquals(4.0,TripMediaClock.offset(112.0,110.0,10.0,2.0)!!,0.0)
    }
    @Test fun unavailableOrInvalidClockNeverFabricatesRecording() {
        assertNull(TripMediaClock.offset(99.0,100.0,10.0))
        assertNull(TripMediaClock.offset(101.0,100.0,0.0))
        assertNull(TripMediaClock.offset(101.0,Double.NaN,10.0))
        assertNull(TripMediaClock.offset(101.0,100.0,10.0,-1.0))
    }
}

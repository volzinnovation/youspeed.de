package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Test

class TripMeasurementTests {
    @Test fun jitterAndStoppedVehicleDoNotAccumulateDistance() {
        assertEquals(0.0, TripMeasurement.acceptedDistance(1.0,4.0,8.0,8.0,1.0),0.0)
        assertEquals(0.0, TripMeasurement.acceptedDistance(2.0,9.0,3.0,3.0,0.0),0.0)
    }
    @Test fun lowSpeedUsesAccumulatedAnchorDistance() {
        assertEquals(8.0,TripMeasurement.acceptedDistance(8.0,8.0,5.0,5.0,1.0),0.0)
    }
    @Test fun gapsJumpsAndInvalidClocksCannotCreateKilometres() {
        assertEquals(0.0,TripMeasurement.acceptedDistance(16.0,30.0,3.0,3.0,3.0),0.0)
        assertEquals(0.0,TripMeasurement.acceptedDistance(1.0,1000.0,3.0,3.0,3.0),0.0)
        assertEquals(0.0,TripMeasurement.acceptedDistance(-1.0,5.0,3.0,3.0,3.0),0.0)
        assertEquals(0.0,TripMeasurement.acceptedDistance(1.0,Double.NaN,3.0,3.0,3.0),0.0)
    }
    @Test fun halfMillimetreRoundsAwayFromZeroLikeIPhone() {
        assertEquals(3.001,TripMeasurement.acceptedDistance(1.0,3.0005,1.0,1.0,1.0),0.0)
    }
}

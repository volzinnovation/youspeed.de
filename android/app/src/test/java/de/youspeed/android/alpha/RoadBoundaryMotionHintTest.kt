package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class RoadBoundaryMotionHintTest {
    private fun fix(t:Double,c:Double,s:Double=10.0) = RoadBoundaryMotionSample(t,s,c,25.0,30.0)
    @Test fun movingHeadingChangeUsesExistingSearchCapWithWrappedAngles() {
        val hint=RoadBoundaryMotionHint.from(listOf(fix(10.0,355.0),fix(10.5,5.0)),10.6,true)
        assertTrue(hint.used); assertEquals(12,hint.horizontalSearchRadiusFloor)
        assertEquals(10.0,hint.headingDeltaDegrees!!,1e-9); assertEquals(20.0,hint.headingRateDegreesPerSecond!!,1e-9)
        assertEquals(.1,hint.sourceAgeSeconds!!,1e-9)
        // Existing app GPS acceptance owns quality. Accuracy remains diagnostic, not a new policy.
        assertEquals(30.0,hint.courseAccuracyDegrees!!,1e-9)
    }
    @Test fun futureFixCannotLeakIntoAnEarlierExposure() {
        val fixes=listOf(fix(10.0,0.0),fix(10.5,0.0),fix(11.0,90.0))
        val hint=RoadBoundaryMotionHint.from(fixes,10.6,true)
        assertFalse(hint.used); assertEquals(0.0,hint.headingDeltaDegrees!!,0.0)
    }
    @Test fun absentUnknownClockStationaryAndInvalidInputsLeaveSearchUnchanged() {
        assertFalse(RoadBoundaryMotionHint.from(emptyList(),10.0,true).used)
        assertFalse(RoadBoundaryMotionHint.from(listOf(fix(9.0,0.0),fix(10.0,45.0)),10.0,false).used)
        assertFalse(RoadBoundaryMotionHint.from(listOf(fix(9.0,0.0),fix(10.0,45.0,0.0)),10.0,true).used)
        assertFalse(RoadBoundaryMotionHint.from(listOf(fix(9.0,0.0),fix(10.0,Double.NaN)),10.0,true).used)
    }
    @Test fun duplicateTimestampIsNotAHeadingVelocityPair() {
        val hint=RoadBoundaryMotionHint.from(listOf(fix(10.0,0.0),fix(10.0,90.0)),10.0,true)
        assertFalse(hint.used); assertEquals("insufficient_history",hint.reason)
    }
}

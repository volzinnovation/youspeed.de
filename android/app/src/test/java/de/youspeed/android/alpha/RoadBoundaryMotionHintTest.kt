package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class RoadBoundaryMotionHintTest {

    @Test fun projectionUncertaintyEnvelopeIsBoundedAndNeedsValidProjection() {
        val c=RoadPathCalibration("mount",true,.8,.8,.5,.5,0.0,0.0,0.0,1.6,0.0)
        val hint=RoadBoundaryMotionHint(false,"straight",sourceAgeSeconds=.8,speedMetersPerSecond=10.0,
            courseAccuracyDegrees=5.0,pairIntervalSeconds=.5,headingRateDegreesPerSecond=0.0)
        val projection=requireNotNull(RoadBoundaryMotionProjection.from(c,null,hint))
        val radius=requireNotNull(projection.searchUncertaintyPixels(LanePoint(.4,.65),.1,384,216))
        assertTrue(radius.first in 2..8); assertTrue(radius.second in 2..6)
        assertNull(projection.searchUncertaintyPixels(LanePoint(.4,.3),.1,384,216))
        assertNull(projection.searchUncertaintyPixels(LanePoint(.4,.65),.9,384,216))
    }

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
    private fun projection(speed:Double=10.0,rate:Double=0.0,age:Double=.1,accuracy:Double=5.0,verified:Boolean=true):RoadBoundaryMotionProjection? {
        val c=RoadPathCalibration("test",verified,1.0,1.0,.5,.5,0.0,0.0,0.0,1.6,0.0)
        return RoadBoundaryMotionProjection.from(c,null,RoadBoundaryMotionHint(false,"fixture",age,speed,accuracy,.5,headingRateDegreesPerSecond=rate))
    }
    @Test fun roadPlaneForwardMotionAndTurnDirection() {
        val p=projection()!!.project(LanePoint(.7,.66),.1)!!
        assertEquals(.5+2.0/9,p.x,1e-9); assertEquals(.5+1.6/9,p.y,1e-9)
        assertTrue(projection(10.0,10.0)!!.project(LanePoint(.7,.66),.1)!!.x<p.x)
        assertTrue(projection(10.0,-10.0)!!.project(LanePoint(.7,.66),.1)!!.x>p.x)
    }
    @Test fun roadPlaneRejectsUncertainStaleAndOutOfViewPredictions() {
        assertNull(projection(age=1.2)); assertNull(projection(accuracy=30.0)); assertNull(projection(verified=false))
        assertNull(projection(speed=0.0)); assertNull(projection(rate=36.0))
        assertNull(projection()!!.project(LanePoint(.7,.4),.1))
        assertNull(projection()!!.project(LanePoint(.7,.66),.8))
        assertNull(projection(60.0)!!.project(LanePoint(.7,.66),.2))
    }
}

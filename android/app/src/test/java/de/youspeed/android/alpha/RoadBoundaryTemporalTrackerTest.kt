package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.abs
import kotlin.math.roundToInt

class RoadBoundaryTemporalTrackerTest {
    private val width=192; private val height=108
    private fun center(y: Int)=45+0.11*y+0.0012*(y-50)*(y-50)
    private fun scene(dx: Int=0,dy: Int=0,occlusion: IntRange?=null): ByteArray {
        val image=ByteArray(width*height) { 50 }
        for(y in 3 until height-3) {
            val targetY=y+dy
            if(targetY !in 0 until height || occlusion?.contains(targetY)==true) continue
            val x=center(y).roundToInt()+dx
            for(offset in -1..1) if(x+offset in 0 until width) image[targetY*width+x+offset]=(190+y%7*5).toByte()
        }
        return image
    }
    private fun fresh(time: Double,dx: Int=0,dy: Int=0,confidence: Double=0.9): RoadBoundaryFrame {
        val points=(55..100 step 3).map { y -> LanePoint((center(y)+dx)/(width-1),(y+dy).toDouble()/(height-1)) }
        return RoadBoundaryFrame(listOf(RoadBoundaryEvidence(points,confidence,RoadBoundaryCue.PAINT,points.size)),emptyList(),time)
    }
    private fun seed(tracker: RoadBoundaryTemporalTracker): RoadBoundaryFrame {
        val image=scene();val prediction=tracker.predict(image,width,height,10.0,"scope",100.0)
        return tracker.complete(prediction,fresh(100.0),image)
    }
    @Test fun translatedCurveIsAdvectedBeforeFreshScanAndCarryKeepsEvidenceAge() {
        val tracker=RoadBoundaryTemporalTracker();seed(tracker)
        val image=scene(7,1)
        val prediction=tracker.predict(image,width,height,10.45,"scope",100.45)
        assertFalse(prediction.budgetExceeded);assertEquals(1,prediction.boundaries.size)
        val carried=prediction.boundaries.single()
        assertTrue(carried.trackedAnchorCount>=4);assertTrue(carried.points.size<=12)
        assertEquals(0.45,carried.evidenceAgeSeconds,1e-9);assertEquals(100.0,carried.lastFreshTimestampSeconds!!,1e-9)
        val maximumError=carried.points.maxOf { p -> abs(p.x*(width-1)-(center((p.y*(height-1)-1).roundToInt())+7)) }
        assertTrue("maximum motion error=$maximumError pixels",maximumError<=2.0)
        val output=tracker.complete(prediction,RoadBoundaryFrame(emptyList(),emptyList(),100.45),image)
        assertEquals(RoadBoundaryProvenance.TRACKED,output.boundaries.single().provenance)
        assertTrue(output.corridors.isEmpty());assertTrue(output.boundaries.single().confidence<0.9)
        val expired=tracker.predict(scene(8,1),width,height,10.81,"scope",100.81)
        assertTrue(expired.boundaries.isEmpty())
    }
    @Test fun partialOcclusionRequiresSeveralCurrentAnchorsAndFullOcclusionCannotCarry() {
        val tracker=RoadBoundaryTemporalTracker();seed(tracker)
        val partial=tracker.predict(scene(3,0,73..77),width,height,10.2,"scope",100.2)
        assertEquals(1,partial.boundaries.size)
        assertTrue(partial.boundaries.single().trackedAnchorCount in 4..7)
        tracker.complete(partial,RoadBoundaryFrame(emptyList(),emptyList(),100.2),scene(3,0,73..77))
        val blank=ByteArray(width*height){50}
        val occluded=tracker.predict(blank,width,height,10.4,"scope",100.4)
        assertTrue(occluded.boundaries.isEmpty())
        tracker.complete(occluded,RoadBoundaryFrame(emptyList(),emptyList(),100.4),blank)
        assertTrue(tracker.predict(scene(3),width,height,10.6,"scope",100.6).boundaries.isEmpty())
    }
    @Test fun freshObservationReacquiresWithoutDuplicateOrConfidenceInflation() {
        val tracker=RoadBoundaryTemporalTracker();seed(tracker)
        val image=scene(3);val predicted=tracker.predict(image,width,height,10.2,"scope",100.2)
        val result=tracker.complete(predicted,fresh(100.2,3,confidence=0.8),image)
        assertEquals(1,result.boundaries.size)
        val boundary=result.boundaries.single()
        assertEquals(RoadBoundaryProvenance.FUSED,boundary.provenance)
        assertEquals(0.8,boundary.confidence,0.0);assertEquals(0.0,boundary.evidenceAgeSeconds,0.0)
        assertEquals(100.2,boundary.lastFreshTimestampSeconds!!,0.0);assertTrue(boundary.points.size<=12)
    }
    @Test fun identityAndGapResetButDuplicateAndOlderExposurePreservePrior() {
        val tracker=RoadBoundaryTemporalTracker();seed(tracker)
        assertEquals("scope_or_geometry",tracker.predict(scene(),width,height,10.2,"new-calibration",100.2).resetReason)
        seed(tracker)
        assertEquals("exposure_gap",tracker.predict(scene(),width,height,11.0,"scope",101.0).resetReason)
        seed(tracker)
        val duplicate=tracker.predict(scene(),width,height,10.0,"scope",100.1)
        assertEquals("duplicate_exposure",duplicate.resetReason)
        assertTrue(tracker.complete(duplicate,fresh(100.1),scene()).boundaries.isEmpty())
        val older=tracker.predict(ByteArray(width*height){50},width,height,9.9,"scope",100.15,shouldContinue={false})
        assertEquals("out_of_order_exposure",older.resetReason)
        assertFalse(older.budgetExceeded)
        tracker.complete(older,fresh(100.15),ByteArray(width*height){50},shouldContinue={false})
        assertEquals(1,tracker.predict(scene(3),width,height,10.2,"scope",100.2).boundaries.size)
        seed(tracker);tracker.reset()
        assertTrue(tracker.predict(scene(),width,height,10.2,"scope",100.2).boundaries.isEmpty())
    }
    @Test fun budgetCancellationAndInvalidInputPublishNoPartialOrStaleTrack() {
        val tracker=RoadBoundaryTemporalTracker();seed(tracker)
        val over=tracker.predict(scene(3),width,height,10.2,"scope",100.2,maximumOperations=100)
        assertTrue(over.budgetExceeded);assertTrue(over.boundaries.isEmpty());assertTrue(over.operationCount<=100)
        assertTrue(tracker.complete(over,fresh(100.2),scene(3)).boundaries.isEmpty())
        seed(tracker)
        val cancelled=tracker.predict(scene(3),width,height,10.2,"scope",100.2,shouldContinue={false})
        assertTrue(cancelled.budgetExceeded);assertTrue(cancelled.boundaries.isEmpty())
        seed(tracker)
        val invalid=tracker.predict(ByteArray(3),width,height,10.2,"scope",100.2)
        assertEquals("invalid_input",invalid.resetReason);assertTrue(invalid.boundaries.isEmpty())
    }
    @Test fun calibrationAndPredictedGuidesNeverManufactureObservedPaint() {
        val guidance=RoadBoundarySearchGuidance(0.42,listOf(listOf(LanePoint(0.46,0.42),LanePoint(0.0,1.0)),
            listOf(LanePoint(0.54,0.42),LanePoint(1.0,1.0))))
        val result=RoadBoundaryDetector().detect(ByteArray(width*height){55},width,height,100.0,guidance=guidance)
        assertTrue(result.boundaries.isEmpty());assertTrue(result.corridors.isEmpty())
    }
    @Test fun absentGpsHintPreservesExactMotionEvidenceAndWork() {
        val a=RoadBoundaryTemporalTracker(); val b=RoadBoundaryTemporalTracker(); seed(a); seed(b)
        val image=scene(3)
        val baseline=a.predict(image,width,height,10.2,"scope",100.2)
        val hinted=b.predict(image,width,height,10.2,"scope",100.2,
            motionHint=RoadBoundaryMotionHint.from(emptyList(),100.2,true))
        assertEquals(baseline.boundaries,hinted.boundaries)
        assertEquals(baseline.operationCount,hinted.operationCount)
    }
}

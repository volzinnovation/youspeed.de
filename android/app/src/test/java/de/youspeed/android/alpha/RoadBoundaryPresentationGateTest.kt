package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class RoadBoundaryPresentationGateTest {
    private fun line(x: Double = .3, provenance: RoadBoundaryProvenance = RoadBoundaryProvenance.FRESH,
        cue: RoadBoundaryCue = RoadBoundaryCue.PAINT) = RoadBoundaryEvidence(
        (0..7).map { LanePoint(x+it*.003,.55+it*.05) },.8,cue,8,provenance=provenance)
    @Test fun confirmationNeedsTwoObservedExposuresAndElapsedTime() {
        val gate = RoadBoundaryPresentationGate(); val boundary=line()
        val first=gate.update(listOf(boundary),10.0,"a")
        assertTrue(first.visibleBoundaryIndices.isEmpty()); assertEquals(1,first.tentativeCount)
        assertTrue(gate.update(listOf(boundary),10.1,"a").visibleBoundaryIndices.isEmpty())
        // A tracked frame cannot turn two closely spaced observations into a mature line.
        assertTrue(gate.update(listOf(line(provenance=RoadBoundaryProvenance.TRACKED)),10.4,"a").visibleBoundaryIndices.isEmpty())
        val confirmed=gate.update(listOf(line(.305,RoadBoundaryProvenance.FUSED)),10.5,"a")
        assertEquals(listOf(0),confirmed.visibleBoundaryIndices)
        assertEquals(first.items.single().trackId,confirmed.items.single().trackId)
        assertEquals(3,confirmed.items.single().observationCount)
        assertEquals(boundary.points,line().points) // Selection never modifies input geometry.
    }
    @Test fun oneFrameArtifactsAndTrackedOnlyLinesNeverAppear() {
        val gate=RoadBoundaryPresentationGate()
        gate.update(listOf(line()),1.0,"a")
        assertTrue(gate.update(emptyList(),1.45,"a").items.isEmpty())
        assertTrue(gate.update(listOf(line()),1.6,"a").visibleBoundaryIndices.isEmpty())
        gate.reset()
        repeat(4) { assertTrue(gate.update(listOf(line(provenance=RoadBoundaryProvenance.TRACKED)),2+it*.2,"a").visibleBoundaryIndices.isEmpty()) }
    }
    @Test fun absenceHidesImmediatelyButBriefIdentitySurvives() {
        val gate=RoadBoundaryPresentationGate(); gate.update(listOf(line()),1.0,"a")
        val mature=gate.update(listOf(line()),1.45,"a"); val id=mature.items.single().trackId
        val absent=gate.update(emptyList(),1.6,"a")
        assertTrue(absent.visibleBoundaryIndices.isEmpty()); assertEquals(1,absent.missingCount)
        val back=gate.update(listOf(line(.31)),1.8,"a")
        assertEquals(listOf(0),back.visibleBoundaryIndices); assertEquals(id,back.items.single().trackId)
        gate.update(emptyList(),2.0,"a")
        assertTrue(gate.update(emptyList(),2.2,"a").items.isEmpty())
        val later=gate.update(listOf(line()),2.3,"a")
        assertTrue(later.visibleBoundaryIndices.isEmpty()); assertNotEquals(id,later.items.single().trackId)
    }
    @Test fun duplicateAndOlderFramesDoNotCountOrClearMaturity() {
        val gate=RoadBoundaryPresentationGate(); val initial=gate.update(listOf(line()),10.0,"a")
        val duplicate=gate.update(listOf(line()),10.0,"a") { error("Duplicate must not consume deadline callback") }
        assertFalse(duplicate.accepted)
        assertFalse(gate.update(emptyList(),9.0,"a").accepted)
        val next=gate.update(listOf(line()),10.45,"a")
        assertEquals(initial.items.single().trackId,next.items.single().trackId)
        assertEquals(2,next.items.single().observationCount); assertEquals(listOf(0),next.visibleBoundaryIndices)
    }
    @Test fun cueGeometryLifecycleAndExposureGapResetIdentity() {
        val gate=RoadBoundaryPresentationGate(); gate.update(listOf(line()),1.0,"a")
        assertTrue(gate.update(listOf(line(cue=RoadBoundaryCue.EDGE)),1.45,"a").visibleBoundaryIndices.isEmpty())
        assertTrue(gate.update(listOf(line(.7)),1.6,"a").visibleBoundaryIndices.isEmpty())
        assertTrue(gate.update(listOf(line(.7)),1.9,"new-calibration").visibleBoundaryIndices.isEmpty())
        gate.update(listOf(line(.7)),2.3,"new-calibration")
        val gap=gate.update(listOf(line(.7)),3.1,"new-calibration")
        assertEquals("exposure_gap",gap.reason); assertTrue(gap.visibleBoundaryIndices.isEmpty())
    }
    @Test fun matchingPreservesIdsWhenDetectionOrderChanges() {
        val gate=RoadBoundaryPresentationGate(); val first=gate.update(listOf(line(.3),line(.7)),1.0,"a")
        val next=gate.update(listOf(line(.69),line(.31)),1.45,"a")
        assertEquals(first.items[0].trackId,next.items[1].trackId); assertEquals(first.items[1].trackId,next.items[0].trackId)
        assertEquals(listOf(0,1),next.visibleBoundaryIndices)
    }
    @Test fun deadlineAndInvalidGeometryNeverPublishPartialSelection() {
        val gate=RoadBoundaryPresentationGate(); gate.update(listOf(line()),1.0,"a")
        val aborted=gate.update(listOf(line()),1.45,"a") { false }
        assertFalse(aborted.accepted); assertTrue(aborted.visibleBoundaryIndices.isEmpty())
        assertTrue(gate.update(listOf(line()),1.6,"a").visibleBoundaryIndices.isEmpty())
        val bad=line().copy(points=listOf(LanePoint(Double.NaN,.5),LanePoint(.3,.9)))
        assertTrue(gate.update(listOf(bad),1.8,"a").visibleBoundaryIndices.isEmpty())
    }
}

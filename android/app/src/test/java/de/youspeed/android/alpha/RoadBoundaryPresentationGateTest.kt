package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class RoadBoundaryPresentationGateTest {
    private fun line(x: Double = .3, provenance: RoadBoundaryProvenance = RoadBoundaryProvenance.FRESH,
        cue: RoadBoundaryCue = RoadBoundaryCue.PAINT) = RoadBoundaryEvidence(
        (0..7).map { LanePoint(x+it*.003,.55+it*.05) },.8,cue,8,provenance=provenance)
    @Test fun diagnosticSelectionRejectsMissingOrInvalidGeometryWithoutPartialOutput() {
        val valid = RoadBoundaryPresentationSnapshot(true,null,listOf(1),emptyList(),2)
        assertEquals(listOf(line(.7)),valid.selectedBoundaries(listOf(line(.3),line(.7))))
        assertTrue(valid.selectedBoundaries(emptyList()).isEmpty())
        val partial = valid.copy(visibleBoundaryIndices=listOf(0,2))
        assertTrue(partial.selectedBoundaries(listOf(line(.3),line(.7))).isEmpty())
        assertTrue(valid.copy(visibleBoundaryIndices=listOf(-1)).selectedBoundaries(listOf(line())).isEmpty())
        assertTrue(RoadBoundaryPresentationSnapshot.rejected("invalid").selectedBoundaries(listOf(line())).isEmpty())
    }
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
    private fun mature(b:List<RoadBoundaryEvidence>,ids:List<Long>)=RoadBoundaryPresentationSnapshot(true,null,b.indices.toList(),ids.mapIndexed { i,id ->
        RoadBoundaryPresentationItem(id,i,"confirmed",4,0.0,1.0,0)
    },b.size)
    @Test fun previewIdentitySurvivesMultipleMissesButExpiresByTime() {
        val gate=RoadBoundaryPresentationGate()
        gate.update(listOf(line()),1.0,"a",true)
        val id=gate.update(listOf(line()),1.4,"a",true).items[0].trackId
        for(t in listOf(1.5,1.6,1.7)) {
            val result=gate.update(emptyList(),t,"a",true)
            assertTrue(result.visibleBoundaryIndices.isEmpty()); assertEquals(id,result.items.first().trackId)
        }
        assertEquals(id,gate.update(listOf(line()),1.8,"a",true).items[0].trackId)
        gate.update(emptyList(),2.2,"a",true)
        assertTrue(gate.update(emptyList(),2.6,"a",true).items.isEmpty())
    }
    @Test fun egoSelectionKeepsOnePerSideAndWaitsBeforeReplacingMissingSide() {
        val selector=RoadBoundaryEgoSelector(); val b=listOf(line(.3),line(.7),line(.12))
        assertEquals(listOf(0,1),selector.select(mature(b,listOf(1,2,3)),b,null,1.0,"a").visibleBoundaryIndices)
        val reorder=listOf(b[2],b[1],b[0])
        assertEquals(listOf(2,1),selector.select(mature(reorder,listOf(3,2,1)),reorder,null,1.1,"a").visibleBoundaryIndices)
        val missing=listOf(b[2],b[1])
        assertEquals(listOf(1),selector.select(mature(missing,listOf(3,2)),missing,null,1.2,"a").visibleBoundaryIndices)
        assertEquals(listOf(0,1),selector.select(mature(missing,listOf(3,2)),missing,null,1.5,"a").visibleBoundaryIndices)
        assertTrue(selector.select(mature(emptyList(),emptyList()),emptyList(),null,1.6,"a").visibleBoundaryIndices.isEmpty())
    }
    @Test fun egoSelectionRequiresSustainedChallengerAndRejectsCrossingPair() {
        val selector=RoadBoundaryEgoSelector(); val weak=line(.3).copy(confidence=.4)
        selector.select(mature(listOf(weak),listOf(1)),listOf(weak),null,1.0,"a")
        val b=listOf(weak,line(.25))
        assertEquals(listOf(0),selector.select(mature(b,listOf(1,2)),b,null,1.1,"a").visibleBoundaryIndices)
        assertEquals(listOf(0),selector.select(mature(b,listOf(1,2)),b,null,1.3,"a").visibleBoundaryIndices)
        assertEquals(listOf(1),selector.select(mature(b,listOf(1,2)),b,null,1.5,"a").visibleBoundaryIndices)
        val crossed=line().copy(points=listOf(LanePoint(.1,.55),LanePoint(.7,.9)))
        val pair=listOf(crossed,line(.6))
        assertEquals(1,selector.select(mature(pair,listOf(4,5)),pair,null,2.0,"new").visibleBoundaryIndices.size)
    }
    @Test fun nearbyMatureReplacementAndShortNearFieldBoundaryAvoidArtificialGap() {
        val selector=RoadBoundaryEgoSelector(); val first=listOf(line(.3)); val nearby=listOf(line(.31))
        selector.select(mature(first,listOf(1)),first,null,1.0,"a")
        assertEquals(listOf(0),selector.select(mature(nearby,listOf(2)),nearby,null,1.1,"a").visibleBoundaryIndices)
        val short=listOf(line().copy(points=listOf(LanePoint(.88,.73),LanePoint(.86,.94))))
        assertEquals(listOf(0),selector.select(mature(short,listOf(3)),short,null,1.2,"turn").visibleBoundaryIndices)
    }
    @Test fun fragmentsDoNotRequirePaintAtFixedLowerAnchorAndExplainSelection() {
        val points=(0..7).map { LanePoint(.32+it*.003,.56+it*.022) }
        val border=RoadBoundaryEvidence(points,.85,RoadBoundaryCue.PAINT,8,observedSegments=listOf(points.take(3),points.takeLast(3)))
        val baseline=RoadBoundaryEgoSelector().select(mature(listOf(border),listOf(1)),listOf(border),null,1.0,"a")
        assertTrue(baseline.visibleBoundaryIndices.isEmpty())
        assertEquals("lower_anchor_missing",baseline.selectionDecisions[0].reason)
        val result=RoadBoundaryEgoSelector().select(mature(listOf(border),listOf(1)),listOf(border),null,1.0,"a",fragmentAware=true)
        assertEquals(listOf(0),result.visibleBoundaryIndices)
        assertEquals("left",result.selectionDecisions[0].side)
        assertEquals("selected",result.selectionDecisions[0].reason)
        assertEquals(points.last().y,result.selectionDecisions[0].anchorY)
        assertEquals(border.observedSegments,result.selectedBoundaries(listOf(border))[0].observedSegments)
    }
    @Test fun fragmentSelectionHidesMatureTrackedModelAndExplainsConfidenceRejection() {
        val predicted=line(.3,RoadBoundaryProvenance.TRACKED)
        val weak=line(.7).copy(confidence=.2)
        val result=RoadBoundaryEgoSelector().select(mature(listOf(predicted,weak),listOf(1,2)),listOf(predicted,weak),null,1.0,"a",fragmentAware=true)
        assertTrue(result.visibleBoundaryIndices.isEmpty())
        assertEquals(listOf("tracked_only","confidence"),result.selectionDecisions.map { it.reason })
    }
    @Test fun shortFragmentSupportCanKeepIdentityWithoutLowerRowPaint() {
        val gate=RoadBoundaryPresentationGate()
        val points=(0..4).map { LanePoint(.32,.60+it*.018) }
        val border=RoadBoundaryEvidence(points,.8,RoadBoundaryCue.PAINT,5,observedSegments=listOf(points))
        val first=gate.update(listOf(border),1.0,"a",fragmentAware=true)
        val next=gate.update(listOf(border),1.4,"a",fragmentAware=true)
        assertEquals(first.items.first().trackId,next.items.first().trackId)
        assertEquals(listOf(0),next.visibleBoundaryIndices)
        assertEquals(listOf(0),RoadBoundaryEgoSelector().select(next,listOf(border),null,1.4,"a",fragmentAware=true).visibleBoundaryIndices)
    }

    @Test fun tentativeIdentitySurvivesDashAbsenceWithoutReinforcement() {
        val gate=RoadBoundaryPresentationGate()
        val first=gate.update(listOf(line()),1.0,"a",retainTentativeIdentity=true)
        for(t in listOf(1.1,1.2,1.3)) {
            val missing=gate.update(emptyList(),t,"a",retainTentativeIdentity=true)
            assertTrue(missing.visibleBoundaryIndices.isEmpty())
            assertEquals(first.items.first().trackId,missing.items.first().trackId)
            assertEquals(1,missing.items.first().observationCount)
            assertEquals(1.0,missing.items.first().lastObservedSeconds,0.0)
        }
        val back=gate.update(listOf(line()),1.4,"a",retainTentativeIdentity=true)
        assertEquals(listOf(0),back.visibleBoundaryIndices)
        assertEquals(2,back.items.first().observationCount)
        assertEquals(first.items.first().trackId,back.items.first().trackId)
    }
    @Test fun predictionsCannotExtendTentativeOrConfirmedEvidenceAge() {
        for(confirm in listOf(false,true)) {
            val gate=RoadBoundaryPresentationGate()
            gate.update(listOf(line()),1.0,"a",retainTentativeIdentity=true)
            val last=if(confirm) 1.4 else 1.0
            if(confirm) gate.update(listOf(line()),last,"a",retainTentativeIdentity=true)
            for(dt in listOf(.1,.3,.5,.7)) {
                val predicted=gate.update(listOf(line(.3,RoadBoundaryProvenance.TRACKED)),last+dt,"a",retainTentativeIdentity=true)
                assertTrue(predicted.visibleBoundaryIndices.isEmpty())
                assertEquals("missing",predicted.items.first().state)
                assertEquals(if(confirm) 2 else 1,predicted.items.first().observationCount)
                assertEquals(last,predicted.items.first().lastObservedSeconds,0.0)
                assertNull(predicted.items.first().boundaryIndex)
            }
            val expired=gate.update(listOf(line(.3,RoadBoundaryProvenance.TRACKED)),last+.8,"a",retainTentativeIdentity=true)
            assertTrue(expired.items.isEmpty()); assertEquals(1,expired.expiredTrackIds.size)
            val fresh=gate.update(listOf(line()),last+.9,"a",retainTentativeIdentity=true)
            assertTrue(fresh.visibleBoundaryIndices.isEmpty()); assertEquals(1,fresh.items.first().observationCount)
            assertNotEquals(expired.expiredTrackIds.first(),fresh.items.first().trackId)
        }
        assertTrue(RoadBoundaryPresentationGate().update(listOf(line(.3,RoadBoundaryProvenance.TRACKED)),1.0,"a",retainTentativeIdentity=true).items.isEmpty())
    }
    private fun metricCalibration(height: Double=1.6,verified: Boolean=true)=RoadPathCalibration("test-current",verified,.45,1.2,.5,.5,0.0,0.0,0.0,height,0.0)
    private fun metricLine(lateral: Double,confidence: Double=.8,cue: RoadBoundaryCue=RoadBoundaryCue.PAINT)=RoadBoundaryEvidence(
        (0..7).map { val y=.55+it*.05; LanePoint(.5+.45*lateral*(y-.5)/1.92,y) },confidence,cue,8)
    @Test fun jointMetricCorridorPrefersEgoPaintOverHighConfidenceOppositeEdge() {
        val borders=listOf(metricLine(-5.0,1.0),metricLine(-1.75,.55),metricLine(1.75))
        val legacy=RoadBoundaryEgoSelector().select(mature(borders,listOf(1,2,3)),borders,null,1.0,"a")
        assertEquals(listOf(0,2),legacy.visibleBoundaryIndices)
        val result=RoadBoundaryEgoSelector().select(mature(borders,listOf(1,2,3)),borders,null,1.0,"a",jointSelection=true,
            egoContext=RoadBoundaryEgoContext(calibration=metricCalibration()))
        assertEquals(listOf(1,2),result.visibleBoundaryIndices)
        assertEquals("metric_width",result.selectionDecisions[0].corridorReason)
        assertEquals(3.5,result.selectionDecisions[1].metricWidthMeters!!,1e-10)
    }
    @Test fun jointStripeEvidenceDownranksGutterAndGraphRemainsWeak() {
        val borders=listOf(line(.3,RoadBoundaryProvenance.FRESH,RoadBoundaryCue.EDGE),line(.32).copy(confidence=.65),line(.7))
        val result=RoadBoundaryEgoSelector().select(mature(borders,listOf(1,2,3)),borders,null,1.0,"a",jointSelection=true,
            egoContext=RoadBoundaryEgoContext(directionalLaneCount=3,roadContextConfidence=.9))
        assertEquals(listOf(1,2),result.visibleBoundaryIndices)
        val paints=listOf(line(.3),line(.7))
        for(lanes in listOf(null,1,2,8,99)) {
            val selected=RoadBoundaryEgoSelector().select(mature(paints,listOf(1,2)),paints,null,1.0,"a",jointSelection=true,
                egoContext=RoadBoundaryEgoContext(directionalLaneCount=lanes,roadContextConfidence=1.0))
            assertEquals(listOf(0,1),selected.visibleBoundaryIndices)
        }
    }
    @Test fun jointSelectionAcceptsBendInOneImageHalfAndNoCalibrationFallback() {
        val visual=VisualRoadCalibration("trusted",384,216,"upright",.45,LanePoint(.10,1.0),.23,LanePoint(.46,1.0),.27)
        val borders=listOf(line(.12),line(.40))
        val result=RoadBoundaryEgoSelector().select(mature(borders,listOf(1,2)),borders,visual,1.0,"a",jointSelection=true)
        assertEquals(listOf(0,1),result.visibleBoundaryIndices)
        assertTrue(result.selectedBoundaries(borders).flatMap { it.points }.all { it.x<.5 })
        val normal=listOf(line(.3),line(.7))
        val fallback=RoadBoundaryEgoSelector().select(mature(normal,listOf(1,2)),normal,null,1.0,"a",jointSelection=true,
            egoContext=RoadBoundaryEgoContext(calibration=metricCalibration(verified=false)))
        assertEquals(listOf(0,1),fallback.visibleBoundaryIndices)
        assertTrue(fallback.selectionDecisions.all { it.metricWidthMeters==null })
    }
    @Test fun metricConflictCannotEraseBothObservedPaintBorders() {
        val borders=listOf(metricLine(-1.75),metricLine(1.75))
        val result=RoadBoundaryEgoSelector().select(mature(borders,listOf(1,2)),borders,null,1.0,"a",jointSelection=true,
            egoContext=RoadBoundaryEgoContext(calibration=metricCalibration(4.0)))
        assertEquals(1,result.visibleBoundaryIndices.size)
        assertEquals("metric_width",result.selectionDecisions.first { it.reason=="pair_geometry" }.corridorReason)
        assertEquals(RoadBoundaryProvenance.FRESH,result.selectedBoundaries(borders).first().provenance)
    }
    @Test fun jointPairRejectsInconsistentCurvatureAndHidesTrackedOutput() {
        val wobble=RoadBoundaryEvidence(listOf(LanePoint(.65,.55),LanePoint(.92,.6375),LanePoint(.62,.725),LanePoint(.94,.8125),LanePoint(.7,.9)),.8,RoadBoundaryCue.PAINT,8)
        val borders=listOf(line(.3),wobble)
        val result=RoadBoundaryEgoSelector().select(mature(borders,listOf(1,2)),borders,null,1.0,"a",jointSelection=true)
        assertEquals(1,result.visibleBoundaryIndices.size)
        assertTrue(result.selectionDecisions.any { it.corridorReason=="inconsistent_curvature" })
        val tracked=listOf(line(.3,RoadBoundaryProvenance.TRACKED))
        assertTrue(RoadBoundaryEgoSelector().select(mature(tracked,listOf(1)),tracked,null,1.0,"a",jointSelection=true).visibleBoundaryIndices.isEmpty())
    }

}

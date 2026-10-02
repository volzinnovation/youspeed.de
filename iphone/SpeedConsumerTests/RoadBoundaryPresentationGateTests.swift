import XCTest
@testable import SpeedConsumer

final class RoadBoundaryPresentationGateTests: XCTestCase {
    private func line(_ x:Double = 0.3,_ provenance:RoadBoundaryProvenance = .fresh,_ cue:RoadBoundaryCue = .paint) -> RoadBoundaryEvidence {
        RoadBoundaryEvidence(points:(0...7).map { LanePoint(x:x+Double($0)*0.003,y:0.55+Double($0)*0.05) },confidence:0.8,cue:cue,supportRows:8,provenance:provenance)
    }
    func testDiagnosticSelectionRejectsMissingOrInvalidGeometryWithoutPartialOutput() {
        let valid = RoadBoundaryPresentationSnapshot(accepted:true,reason:nil,visibleBoundaryIndices:[1],items:[],rawCount:2)
        XCTAssertEqual(valid.selectedBoundaries(from:[line(0.3),line(0.7)]),[line(0.7)])
        XCTAssertTrue(valid.selectedBoundaries(from:[]).isEmpty)
        let partial = RoadBoundaryPresentationSnapshot(accepted:true,reason:nil,visibleBoundaryIndices:[0,2],items:[],rawCount:2)
        XCTAssertTrue(partial.selectedBoundaries(from:[line(0.3),line(0.7)]).isEmpty)
        let negative = RoadBoundaryPresentationSnapshot(accepted:true,reason:nil,visibleBoundaryIndices:[-1],items:[],rawCount:2)
        XCTAssertTrue(negative.selectedBoundaries(from:[line()]).isEmpty)
        XCTAssertTrue(RoadBoundaryPresentationSnapshot.rejected("invalid").selectedBoundaries(from:[line()]).isEmpty)
    }
    func testConfirmationNeedsTwoObservedExposuresAndElapsedTime() {
        let gate=RoadBoundaryPresentationGate(), boundary=line()
        let first=gate.update(boundaries:[boundary],exposureSeconds:10,key:"a")
        XCTAssertTrue(first.visibleBoundaryIndices.isEmpty); XCTAssertEqual(first.tentativeCount,1)
        XCTAssertTrue(gate.update(boundaries:[boundary],exposureSeconds:10.1,key:"a").visibleBoundaryIndices.isEmpty)
        XCTAssertTrue(gate.update(boundaries:[line(0.3,.tracked)],exposureSeconds:10.4,key:"a").visibleBoundaryIndices.isEmpty)
        let confirmed=gate.update(boundaries:[line(0.305,.fused)],exposureSeconds:10.5,key:"a")
        XCTAssertEqual(confirmed.visibleBoundaryIndices,[0]); XCTAssertEqual(first.items.first?.trackId,confirmed.items.first?.trackId)
        XCTAssertEqual(confirmed.items.first?.observationCount,3); XCTAssertEqual(boundary.points,line().points)
    }
    func testOneFrameArtifactsAndTrackedOnlyLinesNeverAppear() {
        let gate=RoadBoundaryPresentationGate()
        _=gate.update(boundaries:[line()],exposureSeconds:1,key:"a")
        XCTAssertTrue(gate.update(boundaries:[],exposureSeconds:1.45,key:"a").items.isEmpty)
        XCTAssertTrue(gate.update(boundaries:[line()],exposureSeconds:1.6,key:"a").visibleBoundaryIndices.isEmpty)
        gate.reset()
        for i in 0..<4 { XCTAssertTrue(gate.update(boundaries:[line(0.3,.tracked)],exposureSeconds:2+Double(i)*0.2,key:"a").visibleBoundaryIndices.isEmpty) }
    }
    func testAbsenceHidesImmediatelyButBriefIdentitySurvives() {
        let gate=RoadBoundaryPresentationGate()
        _=gate.update(boundaries:[line()],exposureSeconds:1,key:"a")
        let mature=gate.update(boundaries:[line()],exposureSeconds:1.45,key:"a"), id=mature.items.first?.trackId
        let absent=gate.update(boundaries:[],exposureSeconds:1.6,key:"a")
        XCTAssertTrue(absent.visibleBoundaryIndices.isEmpty); XCTAssertEqual(absent.missingCount,1)
        let back=gate.update(boundaries:[line(0.31)],exposureSeconds:1.8,key:"a")
        XCTAssertEqual(back.visibleBoundaryIndices,[0]); XCTAssertEqual(id,back.items.first?.trackId)
        _=gate.update(boundaries:[],exposureSeconds:2,key:"a")
        XCTAssertTrue(gate.update(boundaries:[],exposureSeconds:2.2,key:"a").items.isEmpty)
        let later=gate.update(boundaries:[line()],exposureSeconds:2.3,key:"a")
        XCTAssertTrue(later.visibleBoundaryIndices.isEmpty); XCTAssertNotEqual(id,later.items.first?.trackId)
    }
    func testDuplicateAndOlderFramesDoNotCountOrClearMaturity() {
        let gate=RoadBoundaryPresentationGate(), initial=gate.update(boundaries:[line()],exposureSeconds:10,key:"a")
        let duplicate=gate.update(boundaries:[line()],exposureSeconds:10,key:"a",shouldContinue:{ XCTFail("Duplicate must not consume deadline callback"); return false })
        XCTAssertFalse(duplicate.accepted); XCTAssertFalse(gate.update(boundaries:[],exposureSeconds:9,key:"a").accepted)
        let next=gate.update(boundaries:[line()],exposureSeconds:10.45,key:"a")
        XCTAssertEqual(initial.items.first?.trackId,next.items.first?.trackId)
        XCTAssertEqual(next.items.first?.observationCount,2); XCTAssertEqual(next.visibleBoundaryIndices,[0])
    }
    func testCueGeometryLifecycleAndExposureGapResetIdentity() {
        let gate=RoadBoundaryPresentationGate()
        _=gate.update(boundaries:[line()],exposureSeconds:1,key:"a")
        XCTAssertTrue(gate.update(boundaries:[line(0.3,.fresh,.edge)],exposureSeconds:1.45,key:"a").visibleBoundaryIndices.isEmpty)
        XCTAssertTrue(gate.update(boundaries:[line(0.7)],exposureSeconds:1.6,key:"a").visibleBoundaryIndices.isEmpty)
        XCTAssertTrue(gate.update(boundaries:[line(0.7)],exposureSeconds:1.9,key:"new-calibration").visibleBoundaryIndices.isEmpty)
        _=gate.update(boundaries:[line(0.7)],exposureSeconds:2.3,key:"new-calibration")
        let gap=gate.update(boundaries:[line(0.7)],exposureSeconds:3.1,key:"new-calibration")
        XCTAssertEqual(gap.reason,"exposure_gap"); XCTAssertTrue(gap.visibleBoundaryIndices.isEmpty)
    }
    func testMatchingPreservesIdsWhenDetectionOrderChanges() {
        let gate=RoadBoundaryPresentationGate(), first=gate.update(boundaries:[line(0.3),line(0.7)],exposureSeconds:1,key:"a")
        let next=gate.update(boundaries:[line(0.69),line(0.31)],exposureSeconds:1.45,key:"a")
        XCTAssertEqual(first.items[0].trackId,next.items[1].trackId); XCTAssertEqual(first.items[1].trackId,next.items[0].trackId)
        XCTAssertEqual(next.visibleBoundaryIndices,[0,1])
    }
    func testDeadlineAndInvalidGeometryNeverPublishPartialSelection() {
        let gate=RoadBoundaryPresentationGate()
        _=gate.update(boundaries:[line()],exposureSeconds:1,key:"a")
        let aborted=gate.update(boundaries:[line()],exposureSeconds:1.45,key:"a",shouldContinue:{false})
        XCTAssertFalse(aborted.accepted); XCTAssertTrue(aborted.visibleBoundaryIndices.isEmpty)
        XCTAssertTrue(gate.update(boundaries:[line()],exposureSeconds:1.6,key:"a").visibleBoundaryIndices.isEmpty)
        let bad=RoadBoundaryEvidence(points:[LanePoint(x:.nan,y:0.5),LanePoint(x:0.3,y:0.9)],confidence:0.8,cue:.paint,supportRows:8)
        XCTAssertTrue(gate.update(boundaries:[bad],exposureSeconds:1.8,key:"a").visibleBoundaryIndices.isEmpty)
    }
    private func mature(_ b: [RoadBoundaryEvidence], _ ids: [Int64]) -> RoadBoundaryPresentationSnapshot {
        RoadBoundaryPresentationSnapshot(accepted:true,reason:nil,visibleBoundaryIndices:Array(b.indices),items:ids.enumerated().map {
            RoadBoundaryPresentationItem(trackId:$0.element,boundaryIndex:$0.offset,state:"confirmed",observationCount:4,firstObservedSeconds:0,lastObservedSeconds:1,missedExposures:0)
        },rawCount:b.count)
    }
    func testPreviewIdentitySurvivesMultipleMissesButExpiresByTime() {
        let gate=RoadBoundaryPresentationGate()
        _=gate.update(boundaries:[line()],exposureSeconds:1,key:"a",retainMissingByTime:true)
        let id=gate.update(boundaries:[line()],exposureSeconds:1.4,key:"a",retainMissingByTime:true).items[0].trackId
        for t in [1.5,1.6,1.7] {
            let result=gate.update(boundaries:[],exposureSeconds:t,key:"a",retainMissingByTime:true)
            XCTAssertTrue(result.visibleBoundaryIndices.isEmpty); XCTAssertEqual(result.items.first?.trackId,id)
        }
        XCTAssertEqual(gate.update(boundaries:[line()],exposureSeconds:1.8,key:"a",retainMissingByTime:true).items[0].trackId,id)
        _=gate.update(boundaries:[],exposureSeconds:2.2,key:"a",retainMissingByTime:true)
        XCTAssertTrue(gate.update(boundaries:[],exposureSeconds:2.6,key:"a",retainMissingByTime:true).items.isEmpty)
    }
    func testEgoSelectionKeepsOnePerSideAndWaitsBeforeReplacingMissingSide() {
        let selector=RoadBoundaryEgoSelector(), b=[line(0.3),line(0.7),line(0.12)]
        XCTAssertEqual(selector.select(mature(b,[1,2,3]),boundaries:b,visual:nil,time:1,key:"a").visibleBoundaryIndices,[0,1])
        let reorder=[b[2],b[1],b[0]]
        XCTAssertEqual(selector.select(mature(reorder,[3,2,1]),boundaries:reorder,visual:nil,time:1.1,key:"a").visibleBoundaryIndices,[2,1])
        let missing=[b[2],b[1]]
        XCTAssertEqual(selector.select(mature(missing,[3,2]),boundaries:missing,visual:nil,time:1.2,key:"a").visibleBoundaryIndices,[1])
        XCTAssertEqual(selector.select(mature(missing,[3,2]),boundaries:missing,visual:nil,time:1.5,key:"a").visibleBoundaryIndices,[0,1])
        XCTAssertTrue(selector.select(mature([],[]),boundaries:[],visual:nil,time:1.6,key:"a").visibleBoundaryIndices.isEmpty)
    }
    func testEgoSelectionRequiresSustainedChallengerAndRejectsCrossingPair() {
        let selector=RoadBoundaryEgoSelector()
        let weak=RoadBoundaryEvidence(points:line(0.3).points,confidence:0.4,cue:.paint,supportRows:8)
        _=selector.select(mature([weak],[1]),boundaries:[weak],visual:nil,time:1,key:"a")
        let b=[weak,line(0.25)]
        XCTAssertEqual(selector.select(mature(b,[1,2]),boundaries:b,visual:nil,time:1.1,key:"a").visibleBoundaryIndices,[0])
        XCTAssertEqual(selector.select(mature(b,[1,2]),boundaries:b,visual:nil,time:1.3,key:"a").visibleBoundaryIndices,[0])
        XCTAssertEqual(selector.select(mature(b,[1,2]),boundaries:b,visual:nil,time:1.5,key:"a").visibleBoundaryIndices,[1])
        let crossed=RoadBoundaryEvidence(points:[LanePoint(x:0.1,y:0.55),LanePoint(x:0.7,y:0.9)],confidence:0.8,cue:.paint,supportRows:8)
        let pair=[crossed,line(0.6)]
        XCTAssertEqual(selector.select(mature(pair,[4,5]),boundaries:pair,visual:nil,time:2,key:"new").visibleBoundaryIndices.count,1)
    }
    func testNearbyMatureReplacementAndShortNearFieldBoundaryAvoidArtificialGap() {
        let selector=RoadBoundaryEgoSelector(), first=[line(0.3)], nearby=[line(0.31)]
        _=selector.select(mature(first,[1]),boundaries:first,visual:nil,time:1,key:"a")
        XCTAssertEqual(selector.select(mature(nearby,[2]),boundaries:nearby,visual:nil,time:1.1,key:"a").visibleBoundaryIndices,[0])
        let short=[RoadBoundaryEvidence(points:[LanePoint(x:0.88,y:0.73),LanePoint(x:0.86,y:0.94)],confidence:0.8,cue:.paint,supportRows:8)]
        XCTAssertEqual(selector.select(mature(short,[3]),boundaries:short,visual:nil,time:1.2,key:"turn").visibleBoundaryIndices,[0])
    }
    func testFragmentsDoNotRequirePaintAtFixedLowerAnchorAndExplainSelection() {
        let points=(0...7).map { LanePoint(x:0.32+Double($0)*0.003,y:0.56+Double($0)*0.022) }
        let border=RoadBoundaryEvidence(points:points,confidence:0.85,cue:.paint,supportRows:8,
            observedSegments:[Array(points.prefix(3)),Array(points.suffix(3))])
        let baseline=RoadBoundaryEgoSelector().select(mature([border],[1]),boundaries:[border],visual:nil,time:1,key:"a")
        XCTAssertTrue(baseline.visibleBoundaryIndices.isEmpty)
        XCTAssertEqual(baseline.selectionDecisions[0].reason,"lower_anchor_missing")
        let result=RoadBoundaryEgoSelector().select(mature([border],[1]),boundaries:[border],visual:nil,time:1,key:"a",fragmentAware:true)
        XCTAssertEqual(result.visibleBoundaryIndices,[0])
        XCTAssertEqual(result.selectionDecisions[0].side,"left")
        XCTAssertEqual(result.selectionDecisions[0].reason,"selected")
        XCTAssertEqual(result.selectionDecisions[0].anchorY,points.last!.y)
        XCTAssertEqual(result.selectedBoundaries(from:[border])[0].observedSegments,border.observedSegments)
    }
    func testFragmentSelectionHidesMatureTrackedModelAndExplainsConfidenceRejection() {
        let predicted=line(0.3,.tracked)
        let weak=RoadBoundaryEvidence(points:line(0.7).points,confidence:0.2,cue:.paint,supportRows:8)
        let result=RoadBoundaryEgoSelector().select(mature([predicted,weak],[1,2]),boundaries:[predicted,weak],visual:nil,time:1,key:"a",fragmentAware:true)
        XCTAssertTrue(result.visibleBoundaryIndices.isEmpty)
        XCTAssertEqual(result.selectionDecisions.map(\.reason),["tracked_only","confidence"])
    }
    func testShortFragmentSupportCanKeepIdentityWithoutLowerRowPaint() {
        let gate=RoadBoundaryPresentationGate()
        let points=(0...4).map { LanePoint(x:0.32,y:0.60+Double($0)*0.018) }
        let border=RoadBoundaryEvidence(points:points,confidence:0.8,cue:.paint,supportRows:5,observedSegments:[points])
        let first=gate.update(boundaries:[border],exposureSeconds:1,key:"a",fragmentAware:true)
        let next=gate.update(boundaries:[border],exposureSeconds:1.4,key:"a",fragmentAware:true)
        XCTAssertEqual(first.items.first?.trackId,next.items.first?.trackId)
        XCTAssertEqual(next.visibleBoundaryIndices,[0])
        XCTAssertEqual(RoadBoundaryEgoSelector().select(next,boundaries:[border],visual:nil,time:1.4,key:"a",fragmentAware:true).visibleBoundaryIndices,[0])
    }

    func testTentativeIdentitySurvivesDashAbsenceWithoutReinforcement() {
        let gate=RoadBoundaryPresentationGate()
        let first=gate.update(boundaries:[line()],exposureSeconds:1,key:"a",retainTentativeIdentity:true)
        for t in [1.1,1.2,1.3] {
            let missing=gate.update(boundaries:[],exposureSeconds:t,key:"a",retainTentativeIdentity:true)
            XCTAssertTrue(missing.visibleBoundaryIndices.isEmpty)
            XCTAssertEqual(missing.items.first?.trackId,first.items.first?.trackId)
            XCTAssertEqual(missing.items.first?.observationCount,1)
            XCTAssertEqual(missing.items.first?.lastObservedSeconds,1)
        }
        let back=gate.update(boundaries:[line()],exposureSeconds:1.4,key:"a",retainTentativeIdentity:true)
        XCTAssertEqual(back.visibleBoundaryIndices,[0])
        XCTAssertEqual(back.items.first?.observationCount,2)
        XCTAssertEqual(back.items.first?.trackId,first.items.first?.trackId)
    }
    func testPredictionsCannotExtendTentativeOrConfirmedEvidenceAge() {
        for confirm in [false,true] {
            let gate=RoadBoundaryPresentationGate()
            _=gate.update(boundaries:[line()],exposureSeconds:1,key:"a",retainTentativeIdentity:true)
            let last=confirm ? 1.4 : 1.0
            if confirm { _=gate.update(boundaries:[line()],exposureSeconds:last,key:"a",retainTentativeIdentity:true) }
            for dt in [0.1,0.3,0.5,0.7] {
                let predicted=gate.update(boundaries:[line(0.3,.tracked)],exposureSeconds:last+dt,key:"a",retainTentativeIdentity:true)
                XCTAssertTrue(predicted.visibleBoundaryIndices.isEmpty)
                XCTAssertEqual(predicted.items.first?.state,"missing")
                XCTAssertEqual(predicted.items.first?.observationCount,confirm ? 2 : 1)
                XCTAssertEqual(predicted.items.first?.lastObservedSeconds,last)
                XCTAssertNil(predicted.items.first?.boundaryIndex)
            }
            let expired=gate.update(boundaries:[line(0.3,.tracked)],exposureSeconds:last+0.8,key:"a",retainTentativeIdentity:true)
            XCTAssertTrue(expired.items.isEmpty); XCTAssertEqual(expired.expiredTrackIds.count,1)
            let fresh=gate.update(boundaries:[line()],exposureSeconds:last+0.9,key:"a",retainTentativeIdentity:true)
            XCTAssertTrue(fresh.visibleBoundaryIndices.isEmpty); XCTAssertEqual(fresh.items.first?.observationCount,1)
            XCTAssertNotEqual(fresh.items.first?.trackId,expired.expiredTrackIds.first)
        }
        XCTAssertTrue(RoadBoundaryPresentationGate().update(boundaries:[line(0.3,.tracked)],exposureSeconds:1,key:"a",retainTentativeIdentity:true).items.isEmpty)
    }
    private func metricCalibration(_ height: Double = 1.6, verified: Bool = true) -> RoadPathCalibration {
        RoadPathCalibration(revision:"test-current",verified:verified,fx:0.45,fy:1.2,cx:0.5,cy:0.5,
            yawDegrees:0,pitchDegrees:0,rollDegrees:0,heightMeters:height,lateralOffsetMeters:0)
    }
    private func metricLine(_ lateral: Double, confidence: Double = 0.8, cue: RoadBoundaryCue = .paint) -> RoadBoundaryEvidence {
        let points=(0...7).map { i -> LanePoint in
            let y=0.55+Double(i)*0.05
            return LanePoint(x:0.5+0.45*lateral*(y-0.5)/1.92,y:y)
        }
        return RoadBoundaryEvidence(points:points,confidence:confidence,cue:cue,supportRows:8)
    }
    func testJointMetricCorridorPrefersEgoPaintOverHighConfidenceOppositeEdge() {
        let borders=[metricLine(-5,confidence:1),metricLine(-1.75,confidence:0.55),metricLine(1.75)]
        let legacy=RoadBoundaryEgoSelector().select(mature(borders,[1,2,3]),boundaries:borders,visual:nil,time:1,key:"a")
        XCTAssertEqual(legacy.visibleBoundaryIndices,[0,2])
        let result=RoadBoundaryEgoSelector().select(mature(borders,[1,2,3]),boundaries:borders,visual:nil,time:1,key:"a",
            jointSelection:true,egoContext:RoadBoundaryEgoContext(calibration:metricCalibration()))
        XCTAssertEqual(result.visibleBoundaryIndices,[1,2])
        XCTAssertEqual(result.selectionDecisions[0].corridorReason,"metric_width")
        XCTAssertEqual(result.selectionDecisions[1].metricWidthMeters!,3.5,accuracy:1e-10)
    }
    func testJointStripeEvidenceDownranksGutterAndGraphRemainsWeak() {
        let borders=[line(0.3,.fresh,.edge),RoadBoundaryEvidence(points:line(0.32).points,confidence:0.65,cue:.paint,supportRows:8),line(0.7)]
        let result=RoadBoundaryEgoSelector().select(mature(borders,[1,2,3]),boundaries:borders,visual:nil,time:1,key:"a",
            jointSelection:true,egoContext:RoadBoundaryEgoContext(directionalLaneCount:3,roadContextConfidence:0.9))
        XCTAssertEqual(result.visibleBoundaryIndices,[1,2])
        let paints=[line(0.3),line(0.7)]
        for lanes in [nil,1,2,8,99] as [Int?] {
            let selected=RoadBoundaryEgoSelector().select(mature(paints,[1,2]),boundaries:paints,visual:nil,time:1,key:"a",
                jointSelection:true,egoContext:RoadBoundaryEgoContext(directionalLaneCount:lanes,roadContextConfidence:1))
            XCTAssertEqual(selected.visibleBoundaryIndices,[0,1])
        }
    }
    func testJointSelectionAcceptsBendInOneImageHalfAndNoCalibrationFallback() {
        let visual=VisualRoadCalibration(horizonY:0.45,leftBottom:LanePoint(x:0.10,y:1),leftTopX:0.23,
            rightBottom:LanePoint(x:0.46,y:1),rightTopX:0.27,revision:"trusted",imageWidth:384,imageHeight:216,orientationKey:"upright")
        let borders=[line(0.12),line(0.40)]
        let result=RoadBoundaryEgoSelector().select(mature(borders,[1,2]),boundaries:borders,visual:visual,time:1,key:"a",jointSelection:true)
        XCTAssertEqual(result.visibleBoundaryIndices,[0,1])
        XCTAssertTrue(result.selectedBoundaries(from:borders).flatMap(\.points).allSatisfy { $0.x<0.5 })
        let normal=[line(0.3),line(0.7)]
        let fallback=RoadBoundaryEgoSelector().select(mature(normal,[1,2]),boundaries:normal,visual:nil,time:1,key:"a",
            jointSelection:true,egoContext:RoadBoundaryEgoContext(calibration:metricCalibration(verified:false)))
        XCTAssertEqual(fallback.visibleBoundaryIndices,[0,1])
        XCTAssertTrue(fallback.selectionDecisions.allSatisfy { $0.metricWidthMeters==nil })
    }
    func testMetricConflictCannotEraseBothObservedPaintBorders() {
        let borders=[metricLine(-1.75),metricLine(1.75)]
        let result=RoadBoundaryEgoSelector().select(mature(borders,[1,2]),boundaries:borders,visual:nil,time:1,key:"a",
            jointSelection:true,egoContext:RoadBoundaryEgoContext(calibration:metricCalibration(4)))
        XCTAssertEqual(result.visibleBoundaryIndices.count,1)
        XCTAssertEqual(result.selectionDecisions.first(where: { $0.reason=="pair_geometry" })?.corridorReason,"metric_width")
        XCTAssertEqual(result.selectedBoundaries(from:borders).first?.provenance,.fresh)
    }
    func testJointPairRejectsInconsistentCurvatureAndHidesTrackedOutput() {
        let wobble=RoadBoundaryEvidence(points:[LanePoint(x:0.65,y:0.55),LanePoint(x:0.92,y:0.6375),LanePoint(x:0.62,y:0.725),LanePoint(x:0.94,y:0.8125),LanePoint(x:0.7,y:0.9)],confidence:0.8,cue:.paint,supportRows:8)
        let borders=[line(0.3),wobble]
        let result=RoadBoundaryEgoSelector().select(mature(borders,[1,2]),boundaries:borders,visual:nil,time:1,key:"a",jointSelection:true)
        XCTAssertEqual(result.visibleBoundaryIndices.count,1)
        XCTAssertTrue(result.selectionDecisions.contains { $0.corridorReason=="inconsistent_curvature" })
        let tracked=[line(0.3,.tracked)]
        XCTAssertTrue(RoadBoundaryEgoSelector().select(mature(tracked,[1]),boundaries:tracked,visual:nil,time:1,key:"a",jointSelection:true).visibleBoundaryIndices.isEmpty)
    }

}

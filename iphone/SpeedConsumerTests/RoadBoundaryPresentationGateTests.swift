import XCTest
@testable import SpeedConsumer

final class RoadBoundaryPresentationGateTests: XCTestCase {
    private func line(_ x:Double = 0.3,_ provenance:RoadBoundaryProvenance = .fresh,_ cue:RoadBoundaryCue = .paint) -> RoadBoundaryEvidence {
        RoadBoundaryEvidence(points:(0...7).map { LanePoint(x:x+Double($0)*0.003,y:0.55+Double($0)*0.05) },confidence:0.8,cue:cue,supportRows:8,provenance:provenance)
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
}

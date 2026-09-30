import XCTest
@testable import SpeedConsumer

final class RoadBoundaryTemporalTrackerTests: XCTestCase {
    func testAbsentGpsHintPreservesExactMotionEvidenceAndWork() {
        let a=RoadBoundaryTemporalTracker(), b=RoadBoundaryTemporalTracker(); seed(a); seed(b)
        let image=scene(3)
        let baseline=a.predict(grayscale:image,width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2)
        let hinted=b.predict(grayscale:image,width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2,
            motionHint:RoadBoundaryMotionHint.from(samples:[],capturedAtSeconds:100.2,clockKnown:true))
        XCTAssertEqual(baseline.boundaries,hinted.boundaries); XCTAssertEqual(baseline.operationCount,hinted.operationCount)
    }
    private let width=192, height=108
    private func center(_ y: Int) -> Double { 45+0.11*Double(y)+0.0012*Double((y-50)*(y-50)) }
    private func scene(_ dx: Int=0,_ dy: Int=0,_ occlusion: ClosedRange<Int>?=nil) -> [UInt8] {
        var image=[UInt8](repeating:50,count:width*height)
        for y in 3..<height-3 {
            let targetY=y+dy
            if targetY<0 || targetY>=height || occlusion?.contains(targetY)==true { continue }
            let x=Int(center(y).rounded())+dx
            for offset in -1...1 where x+offset>=0 && x+offset<width { image[targetY*width+x+offset]=UInt8(190+y%7*5) }
        }
        return image
    }
    private func fresh(_ time: Double,_ dx: Int=0,_ dy: Int=0,confidence: Double=0.9) -> RoadBoundaryFrame {
        let points=stride(from:55,through:100,by:3).map { y in LanePoint(x:(center(y)+Double(dx))/Double(width-1),y:Double(y+dy)/Double(height-1)) }
        return RoadBoundaryFrame(boundaries:[RoadBoundaryEvidence(points:points,confidence:confidence,cue:.paint,supportRows:points.count)],corridors:[],timestampSeconds:time)
    }
    @discardableResult private func seed(_ tracker: RoadBoundaryTemporalTracker) -> RoadBoundaryFrame {
        let image=scene(), prediction=tracker.predict(grayscale:scene(),width:width,height:height,timestampSeconds:10,key:"scope",capturedAtSeconds:100)
        return tracker.complete(prediction:prediction,fresh:fresh(100),grayscale:image)
    }
    func testTranslatedCurveIsAdvectedBeforeFreshScanAndCarryKeepsEvidenceAge() throws {
        let tracker=RoadBoundaryTemporalTracker();seed(tracker)
        let image=scene(7,1)
        let prediction=tracker.predict(grayscale:image,width:width,height:height,timestampSeconds:10.45,key:"scope",capturedAtSeconds:100.45)
        XCTAssertFalse(prediction.budgetExceeded);XCTAssertEqual(prediction.boundaries.count,1)
        let carried=try XCTUnwrap(prediction.boundaries.first)
        XCTAssertGreaterThanOrEqual(carried.trackedAnchorCount,4);XCTAssertLessThanOrEqual(carried.points.count,12)
        XCTAssertEqual(carried.evidenceAgeSeconds,0.45,accuracy:1e-9);XCTAssertEqual(try XCTUnwrap(carried.lastFreshTimestampSeconds),100,accuracy:1e-9)
        let maximumError=carried.points.map { p in abs(p.x*Double(width-1)-(center(Int((p.y*Double(height-1)-1).rounded()))+7)) }.max() ?? .infinity
        XCTAssertLessThanOrEqual(maximumError,2,"Maximum motion error in analysis pixels")
        let output=tracker.complete(prediction:prediction,fresh:RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:100.45),grayscale:image)
        XCTAssertEqual(output.boundaries.first?.provenance,.tracked);XCTAssertTrue(output.corridors.isEmpty)
        XCTAssertLessThan(try XCTUnwrap(output.boundaries.first?.confidence),0.9)
        XCTAssertTrue(tracker.predict(grayscale:scene(8,1),width:width,height:height,timestampSeconds:10.81,key:"scope",capturedAtSeconds:100.81).boundaries.isEmpty)
    }
    func testPartialOcclusionRequiresCurrentAnchorsAndFullOcclusionCannotCarry() throws {
        let tracker=RoadBoundaryTemporalTracker();seed(tracker)
        let image=scene(3,0,73...77)
        let partial=tracker.predict(grayscale:image,width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2)
        XCTAssertEqual(partial.boundaries.count,1)
        XCTAssertTrue((4...7).contains(try XCTUnwrap(partial.boundaries.first?.trackedAnchorCount)))
        _=tracker.complete(prediction:partial,fresh:RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:100.2),grayscale:image)
        let blank=[UInt8](repeating:50,count:width*height)
        let occluded=tracker.predict(grayscale:blank,width:width,height:height,timestampSeconds:10.4,key:"scope",capturedAtSeconds:100.4)
        XCTAssertTrue(occluded.boundaries.isEmpty)
        _=tracker.complete(prediction:occluded,fresh:RoadBoundaryFrame(boundaries:[],corridors:[],timestampSeconds:100.4),grayscale:blank)
        XCTAssertTrue(tracker.predict(grayscale:scene(3),width:width,height:height,timestampSeconds:10.6,key:"scope",capturedAtSeconds:100.6).boundaries.isEmpty)
    }
    func testFreshObservationReacquiresWithoutDuplicateOrConfidenceInflation() throws {
        let tracker=RoadBoundaryTemporalTracker();seed(tracker)
        let image=scene(3), predicted=tracker.predict(grayscale:scene(3),width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2)
        let result=tracker.complete(prediction:predicted,fresh:fresh(100.2,3,confidence:0.8),grayscale:image)
        XCTAssertEqual(result.boundaries.count,1)
        let boundary=try XCTUnwrap(result.boundaries.first)
        XCTAssertEqual(boundary.provenance,.fused);XCTAssertEqual(boundary.confidence,0.8)
        XCTAssertEqual(boundary.evidenceAgeSeconds,0);XCTAssertEqual(boundary.lastFreshTimestampSeconds,100.2)
        XCTAssertLessThanOrEqual(boundary.points.count,12)
    }
    func testIdentityAndGapResetButDuplicateAndOlderExposurePreservePrior() {
        let tracker=RoadBoundaryTemporalTracker();seed(tracker)
        XCTAssertEqual(tracker.predict(grayscale:scene(),width:width,height:height,timestampSeconds:10.2,key:"new-calibration",capturedAtSeconds:100.2).resetReason,"scope_or_geometry")
        seed(tracker)
        XCTAssertEqual(tracker.predict(grayscale:scene(),width:width,height:height,timestampSeconds:11,key:"scope",capturedAtSeconds:101).resetReason,"exposure_gap")
        seed(tracker)
        let duplicate=tracker.predict(grayscale:scene(),width:width,height:height,timestampSeconds:10,key:"scope",capturedAtSeconds:100.1)
        XCTAssertEqual(duplicate.resetReason,"duplicate_exposure")
        XCTAssertTrue(tracker.complete(prediction:duplicate,fresh:fresh(100.1),grayscale:scene()).boundaries.isEmpty)
        let blank=[UInt8](repeating:50,count:width*height)
        let older=tracker.predict(grayscale:blank,width:width,height:height,timestampSeconds:9.9,key:"scope",capturedAtSeconds:100.15,shouldContinue:{false})
        XCTAssertEqual(older.resetReason,"out_of_order_exposure");XCTAssertFalse(older.budgetExceeded)
        _=tracker.complete(prediction:older,fresh:fresh(100.15),grayscale:blank,shouldContinue:{false})
        XCTAssertEqual(tracker.predict(grayscale:scene(3),width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2).boundaries.count,1)
        seed(tracker);tracker.reset()
        XCTAssertTrue(tracker.predict(grayscale:scene(),width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2).boundaries.isEmpty)
    }
    func testBudgetCancellationAndInvalidInputPublishNoPartialOrStaleTrack() {
        let tracker=RoadBoundaryTemporalTracker();seed(tracker)
        let over=tracker.predict(grayscale:scene(3),width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2,maximumOperations:100)
        XCTAssertTrue(over.budgetExceeded);XCTAssertTrue(over.boundaries.isEmpty);XCTAssertLessThanOrEqual(over.operationCount,100)
        XCTAssertTrue(tracker.complete(prediction:over,fresh:fresh(100.2),grayscale:scene(3)).boundaries.isEmpty)
        seed(tracker)
        let cancelled=tracker.predict(grayscale:scene(3),width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2,shouldContinue:{false})
        XCTAssertTrue(cancelled.budgetExceeded);XCTAssertTrue(cancelled.boundaries.isEmpty)
        seed(tracker)
        let invalid=tracker.predict(grayscale:[0,0,0],width:width,height:height,timestampSeconds:10.2,key:"scope",capturedAtSeconds:100.2)
        XCTAssertEqual(invalid.resetReason,"invalid_input");XCTAssertTrue(invalid.boundaries.isEmpty)
    }
    func testCalibrationAndPredictedGuidesNeverManufactureObservedPaint() {
        let guidance=RoadBoundarySearchGuidance(horizonY:0.42,polylines:[[LanePoint(x:0.46,y:0.42),LanePoint(x:0,y:1)],
            [LanePoint(x:0.54,y:0.42),LanePoint(x:1,y:1)]])
        let result=RoadBoundaryDetector().detect(grayscale:[UInt8](repeating:55,count:width*height),width:width,height:height,timestampSeconds:100,guidance:guidance)
        XCTAssertTrue(result.boundaries.isEmpty);XCTAssertTrue(result.corridors.isEmpty)
    }
}

import XCTest
@testable import SpeedConsumer

final class RoadBoundaryMotionHintTests: XCTestCase {

    func testProjectionUncertaintyEnvelopeIsBoundedAndNeedsValidProjection() throws {
        let c=RoadPathCalibration(revision:"mount",verified:true,fx:0.8,fy:0.8,cx:0.5,cy:0.5,
            yawDegrees:0,pitchDegrees:0,rollDegrees:0,heightMeters:1.6,lateralOffsetMeters:0)
        let hint=RoadBoundaryMotionHint(used:false,reason:"straight",sourceAgeSeconds:0.8,speedMetersPerSecond:10,
            courseAccuracyDegrees:5,pairIntervalSeconds:0.5,headingRateDegreesPerSecond:0)
        let projection=try XCTUnwrap(RoadBoundaryMotionProjection.from(c,visual:nil,hint:hint))
        let radius=try XCTUnwrap(projection.searchUncertaintyPixels(LanePoint(x:0.4,y:0.65),dt:0.1,width:384,height:216))
        XCTAssertTrue((2...8).contains(radius.horizontal)); XCTAssertTrue((2...6).contains(radius.vertical))
        XCTAssertNil(projection.searchUncertaintyPixels(LanePoint(x:0.4,y:0.3),dt:0.1,width:384,height:216))
        XCTAssertNil(projection.searchUncertaintyPixels(LanePoint(x:0.4,y:0.65),dt:0.9,width:384,height:216))
    }

    private func fix(_ t:Double,_ c:Double,_ s:Double = 10) -> RoadBoundaryMotionSample {
        RoadBoundaryMotionSample(timeSeconds:t,speedMetersPerSecond:s,courseDegrees:c,horizontalAccuracyMeters:25,courseAccuracyDegrees:30)
    }
    func testMovingHeadingChangeUsesExistingSearchCapWithWrappedAngles() {
        let hint=RoadBoundaryMotionHint.from(samples:[fix(10,355),fix(10.5,5)],capturedAtSeconds:10.6,clockKnown:true)
        XCTAssertTrue(hint.used); XCTAssertEqual(hint.horizontalSearchRadiusFloor,12)
        XCTAssertEqual(hint.headingDeltaDegrees!,10,accuracy:1e-9); XCTAssertEqual(hint.headingRateDegreesPerSecond!,20,accuracy:1e-9)
        XCTAssertEqual(hint.sourceAgeSeconds!,0.1,accuracy:1e-9); XCTAssertEqual(hint.courseAccuracyDegrees!,30,accuracy:1e-9)
    }
    func testFutureFixCannotLeakIntoAnEarlierExposure() {
        let hint=RoadBoundaryMotionHint.from(samples:[fix(10,0),fix(10.5,0),fix(11,90)],capturedAtSeconds:10.6,clockKnown:true)
        XCTAssertFalse(hint.used); XCTAssertEqual(hint.headingDeltaDegrees,0)
    }
    func testAbsentUnknownClockStationaryAndInvalidInputsLeaveSearchUnchanged() {
        XCTAssertFalse(RoadBoundaryMotionHint.from(samples:[],capturedAtSeconds:10,clockKnown:true).used)
        XCTAssertFalse(RoadBoundaryMotionHint.from(samples:[fix(9,0),fix(10,45)],capturedAtSeconds:10,clockKnown:false).used)
        XCTAssertFalse(RoadBoundaryMotionHint.from(samples:[fix(9,0),fix(10,45,0)],capturedAtSeconds:10,clockKnown:true).used)
        XCTAssertFalse(RoadBoundaryMotionHint.from(samples:[fix(9,0),fix(10,.nan)],capturedAtSeconds:10,clockKnown:true).used)
    }
    func testDuplicateTimestampIsNotAHeadingVelocityPair() {
        let hint=RoadBoundaryMotionHint.from(samples:[fix(10,0),fix(10,90)],capturedAtSeconds:10,clockKnown:true)
        XCTAssertFalse(hint.used); XCTAssertEqual(hint.reason,"insufficient_history")
    }
    private func projection(_ speed: Double = 10, _ rate: Double = 0, _ age: Double = 0.1, _ accuracy: Double = 5, _ verified: Bool = true) -> RoadBoundaryMotionProjection? {
        let c=RoadPathCalibration(revision:"test",verified:verified,fx:1,fy:1,cx:0.5,cy:0.5,yawDegrees:0,pitchDegrees:0,rollDegrees:0,heightMeters:1.6,lateralOffsetMeters:0)
        return RoadBoundaryMotionProjection.from(c,visual:nil,hint:RoadBoundaryMotionHint(used:false,reason:"fixture",sourceAgeSeconds:age,
            speedMetersPerSecond:speed,courseAccuracyDegrees:accuracy,pairIntervalSeconds:0.5,headingRateDegreesPerSecond:rate))
    }
    func testRoadPlaneForwardMotionAndTurnDirection() {
        // World point (x=2,z=10) projects to (.7,.66); moving forward 1m leaves z=9.
        let p=projection()!.project(LanePoint(x:0.7,y:0.66),dt:0.1)!
        XCTAssertEqual(p.x,0.5+2/9,accuracy:1e-9); XCTAssertEqual(p.y,0.5+1.6/9,accuracy:1e-9)
        let turn=projection(10,10)!.project(LanePoint(x:0.7,y:0.66),dt:0.1)!
        XCTAssertLessThan(turn.x,p.x)
        XCTAssertGreaterThan(projection(10,-10)!.project(LanePoint(x:0.7,y:0.66),dt:0.1)!.x,p.x)
    }
    func testRoadPlaneRejectsUncertainStaleAndOutOfViewPredictions() {
        XCTAssertNil(projection(10,0,1.2)); XCTAssertNil(projection(10,0,0.1,30)); XCTAssertNil(projection(10,0,0.1,5,false))
        XCTAssertNil(projection(0)); XCTAssertNil(projection(10,36))
        XCTAssertNil(projection()!.project(LanePoint(x:0.7,y:0.4),dt:0.1))
        XCTAssertNil(projection()!.project(LanePoint(x:0.7,y:0.66),dt:0.8))
        XCTAssertNil(projection(60)!.project(LanePoint(x:0.7,y:0.66),dt:0.2))
    }
}

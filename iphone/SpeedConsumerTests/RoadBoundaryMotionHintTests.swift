import XCTest
@testable import SpeedConsumer

final class RoadBoundaryMotionHintTests: XCTestCase {
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
}

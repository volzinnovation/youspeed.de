import XCTest
@testable import SpeedConsumer

final class TripMeasurementTests: XCTestCase {
    func testJitterAndStoppedVehicle() {
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:1,metres:3.0005,accuracy:1,previousAccuracy:1,speed:4),3.001)
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:1,metres:4,accuracy:8,previousAccuracy:8,speed:1),0)
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:2,metres:9,accuracy:3,previousAccuracy:3,speed:0),0)
    }
    func testLowSpeedAndGaps() {
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:8,metres:8,accuracy:5,previousAccuracy:5,speed:1),8)
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:16,metres:30,accuracy:3,previousAccuracy:3,speed:3),0)
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:1,metres:1000,accuracy:3,previousAccuracy:3,speed:3),0)
        XCTAssertEqual(TripMeasurement.acceptedDistance(seconds:-1,metres:5,accuracy:3,previousAccuracy:3,speed:3),0)
    }
}

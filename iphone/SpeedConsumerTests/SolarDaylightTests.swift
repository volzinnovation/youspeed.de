import XCTest
@testable import SpeedConsumer

final class SolarDaylightTests: XCTestCase {
    func testSeasonsPolarRegionsLeapYearAndDateline() {
        let f = ISO8601DateFormatter()
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-10-18T17:05:00Z")!), false, "2026-10-18T17:05:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-06-21T18:00:00Z")!), true, "2026-06-21T18:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-12-21T18:00:00Z")!), false, "2026-12-21T18:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 78.22, longitude: 15.65, at: f.date(from: "2026-06-21T00:00:00Z")!), true, "2026-06-21T00:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 78.22, longitude: 15.65, at: f.date(from: "2026-12-21T12:00:00Z")!), false, "2026-12-21T12:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: -33.87, longitude: 151.21, at: f.date(from: "2026-12-21T00:00:00Z")!), true, "2026-12-21T00:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: -33.87, longitude: 151.21, at: f.date(from: "2026-12-21T12:00:00Z")!), false, "2026-12-21T12:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 0.0, longitude: 0.0, at: f.date(from: "2024-02-29T12:00:00Z")!), true, "2024-02-29T12:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 0.0, longitude: 180.0, at: f.date(from: "2026-03-20T00:00:00Z")!), true, "2026-03-20T00:00:00Z")
        XCTAssertEqual(SolarDaylight.permitsCameraTSR(latitude: 0.0, longitude: -180.0, at: f.date(from: "2026-03-20T12:00:00Z")!), false, "2026-03-20T12:00:00Z")
    }
    func testDSTAndTimezoneOffsetsDescribeAbsoluteInstants() {
        let f = ISO8601DateFormatter()
        XCTAssertEqual(SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-10-25T02:30:00+02:00")!), SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-10-25T00:30:00Z")!))
        XCTAssertEqual(SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-10-25T02:30:00+01:00")!), SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-10-25T01:30:00Z")!))
        XCTAssertEqual(SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-03-29T03:30:00+02:00")!), SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-03-29T01:30:00Z")!))
        XCTAssertEqual(SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-07-01T12:00:00+05:30")!), SolarDaylight.elevationDegrees(latitude: 48.76, longitude: 8.34, at: f.date(from: "2026-07-01T06:30:00Z")!))
    }
    func testMissingAndInvalidLocationPausesCamera() {
        for (lat, lon) in [(nil, 8.0), (49.0, nil), (.nan, 8), (91, 8), (49, 181), (49, .infinity)] as [(Double?, Double?)] {
            XCTAssertFalse(SolarDaylight.permitsCameraTSR(latitude: lat, longitude: lon, at: Date()))
        }
    }
}

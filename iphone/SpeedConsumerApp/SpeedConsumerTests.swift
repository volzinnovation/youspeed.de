import XCTest
@testable import SpeedConsumer

final class SpeedConsumerTests: XCTestCase {
    func testParseExplicitSpeed() {
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed("30"), 30)
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed("80 km/h"), 80)
        XCTAssertNil(V3SpeedLimitService.parseExplicitSpeed("signals"))
    }

    func testDeriveSpeedLimitFallbacks() {
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: "DE:urban", sourceMaxspeed: nil, highway: nil), 50)
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: nil, sourceMaxspeed: "DE:rural", highway: nil), 100)
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: nil, sourceMaxspeed: nil, highway: "motorway"), 130)
    }

    func testDecodeBundleManifest() throws {
        let raw = """
        {
          "format": "youspeed.v3.bundle.manifest",
          "schema_version": 1,
          "variant": "v3",
          "region": "germany",
          "bundle_version": "2026-02-24",
          "created_at_utc": "2026-02-24T00:00:00Z",
          "min_app_version": "1.0.0",
          "db": {
            "file": "speeds_v3.sqlite",
            "bytes": 123,
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "url": "https://github.com/volzinnovation/youspeed.de/releases/download/v3-data-2026-02-24/germany/2026-02-24/speeds_v3.sqlite"
          },
          "delta_index": null
        }
        """
        let data = Data(raw.utf8)
        let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: data)
        XCTAssertEqual(manifest.variant, "v3")
        XCTAssertEqual(manifest.bundleVersion, "2026-02-24")
        XCTAssertEqual(manifest.db.file, "speeds_v3.sqlite")
    }
}

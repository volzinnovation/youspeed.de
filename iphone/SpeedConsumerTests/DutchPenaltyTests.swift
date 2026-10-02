import Foundation
import XCTest
@testable import SpeedConsumer

final class DutchPenaltyTests: XCTestCase {
    private struct Vector: Decodable {
        let id: String
        let excess: Int
        let posted_limit: Int?
        let inside_city: Bool?
        let highway: String?
        let fine: Int?
        let enforcement: String
    }
    private struct Fixture: Decodable { let cases: [Vector] }

    func testReviewedOfficialTariffsBoundariesAndUnknownContext() throws {
        let rules = try SpeedPenaltyRuleSet.loadBundled(named: "NLD-rules")
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "NLD-cases", withExtension: "json"))
        let vectors = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: url)).cases
        XCTAssertEqual(vectors.count, 175)
        for vector in vectors {
            for language in ["de", "en", "fr", "nl"] {
                let notice = try XCTUnwrap(SpeedPenaltyRuleEngine.resolveNotice(
                    overspeedKmh: vector.excess, rules: rules, insideCity: vector.inside_city,
                    postedLimitKmh: vector.posted_limit, languageCode: language,
                    isMotorway: PenaltyRoadArea.matchedMotorway(highway: vector.highway)))
                let label = "\(vector.id)/\(language)"
                XCTAssertEqual(notice.moneyFineEUR, vector.fine, label)
                XCTAssertEqual(notice.enforcementClass, vector.enforcement, label)
                XCTAssertNil(notice.penaltyPoints, label)
                XCTAssertNil(notice.drivingBanMonths, label)
                XCTAssertFalse(notice.details.contains("{"), label)
                if let fine = vector.fine, fine > 0 {
                    XCTAssertTrue(notice.details.contains("\(fine) EUR"), label)
                    XCTAssertTrue(notice.details.contains("9 EUR"), label)
                }
            }
        }
        XCTAssertNil(SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 0, rules: rules))
        let legacy = try JSONDecoder().decode(SpeedPenaltyRuleSet.self, from: JSONSerialization.data(withJSONObject: [
            "format": "youspeed.penalty.rules", "country_code": "NLD", "bands": []]))
        XCTAssertFalse(SpeedPenaltyRuleSet.prefersDownloaded(legacy, over: rules))
    }
}

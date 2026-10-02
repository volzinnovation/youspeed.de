import Foundation
import XCTest
@testable import SpeedConsumer

final class PenaltyDocumentationTests: XCTestCase {
    func testInfoDocumentReadsAllCountriesAndTheEffectiveRuleJSON() throws {
        var rules = try SpeedPenaltyRuleSet.loadBundled(named: "NLD-rules")
        let data = try XCTUnwrap(rules.documentationJSON)
        var original = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        var tariffs = original["speeding_tariffs"] as! [String: Any]
        var categories = tariffs["road_categories"] as! [String: Any]
        var urban = categories["urban"] as! [String: Any]
        var amounts = urban["fines_eur"] as! [String: Any]
        amounts["12"] = 777
        urban["fines_eur"] = amounts; categories["urban"] = urban
        tariffs["road_categories"] = categories; original["speeding_tariffs"] = tariffs
        original["country_name"] = "</script><script>untrusted()</script> __YOUSPEED_RENDERER__"
        rules.documentationJSON = try JSONSerialization.data(withJSONObject: original)
        let html = try PenaltyDocumentationHTML.make(activeRules: rules, locale: "nl")
        XCTAssertFalse(html.contains("<script>untrusted()"))
        let marker = "window.penaltyDocumentationInput="
        let after = try XCTUnwrap(html.range(of: marker)).upperBound
        let end = try XCTUnwrap(html.range(of: ";</script>", range: after..<html.endIndex)).lowerBound
        let input = try JSONSerialization.jsonObject(with: Data(html[after..<end].utf8)) as! [String: Any]
        let documents = input["documents"] as! [[String: Any]]
        XCTAssertEqual(documents.count, 12)
        XCTAssertEqual(input["locale"] as? String, "nl")
        let selected = try XCTUnwrap(documents.first { $0["country_code"] as? String == "NLD" })
        XCTAssertEqual(selected["country_name"] as? String, original["country_name"] as? String)
        let selectedTariffs = selected["speeding_tariffs"] as! [String: Any]
        let selectedCategories = selectedTariffs["road_categories"] as! [String: Any]
        let selectedUrban = selectedCategories["urban"] as! [String: Any]
        XCTAssertEqual((selectedUrban["fines_eur"] as! [String: Any])["12"] as? Int, 777)
    }
}

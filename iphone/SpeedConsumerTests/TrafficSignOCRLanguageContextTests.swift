import XCTest
@testable import SpeedConsumer

final class TrafficSignOCRLanguageContextTests: XCTestCase {
    func testCountryLanguagesDoNotFollowDeviceLanguage() {
        XCTAssertEqual(TrafficSignOCRLanguageContext.languages(for: "FRA"), ["fr-FR"])
        XCTAssertEqual(TrafficSignOCRLanguageContext.languages(for: "CH"), ["de-CH", "fr-CH", "it-CH", "rm-CH"])
        XCTAssertEqual(TrafficSignOCRLanguageContext.languages(for: "BEL"), ["nl-BE", "fr-BE", "de-BE"])
    }

    func testDutchRequiresAccurateVisionWhenFastDoesNotSupportIt() {
        let fast = ["de-DE", "fr-FR", "it-IT", "en-US"]
        let accurate = fast + ["nl-NL"]
        XCTAssertTrue(TrafficSignSupplementaryOCR.needsAccurate(languages: ["nl-BE", "fr-BE"], fast: fast, accurate: accurate))
        XCTAssertFalse(TrafficSignSupplementaryOCR.needsAccurate(languages: ["de-CH", "fr-CH", "it-CH", "rm-CH"], fast: fast, accurate: accurate))
    }

    func testMultilingualCountryUsesTextAndAbstainsForAmbiguousClocks() {
        let swiss = TrafficSignOCRLanguageContext.languages(for: "CH")
        let belgian = TrafficSignOCRLanguageContext.languages(for: "BE")
        XCTAssertEqual(TrafficSignOCRLanguageContext.resolve(text: "Mo-Fr\n630-1730 h", candidates: swiss), "de-CH")
        XCTAssertEqual(TrafficSignOCRLanguageContext.resolve(text: "sauf riverains", candidates: swiss), "fr-CH")
        XCTAssertEqual(TrafficSignOCRLanguageContext.resolve(text: "eccetto scuola", candidates: swiss), "it-CH")
        XCTAssertEqual(TrafficSignOCRLanguageContext.resolve(text: "uitgezonderd fietsers", candidates: belgian), "nl-BE")
        for text in ["22-6 h", "Lu-Ve", "P", "sauf riverains\nuitgezonderd fietsers"] {
            XCTAssertNil(TrafficSignOCRLanguageContext.resolve(text: text, candidates: text.contains("fietsers") ? belgian : swiss))
        }
    }

    func testUnconstrainedConfidenceCannotForceForeignOrUncertainTextIntoLocalLanguage() {
        let swiss = TrafficSignOCRLanguageContext.languages(for: "CH")
        XCTAssertNil(TrafficSignOCRLanguageContext.resolve(text: "abcdefghijklmnop", candidates: swiss, hypotheses: ["en": 0.95, "de": 0.04]))
        XCTAssertNil(TrafficSignOCRLanguageContext.resolve(text: "abcdefghijklmnop", candidates: swiss, hypotheses: ["fr": 0.60, "it": 0.40]))
        XCTAssertEqual(TrafficSignOCRLanguageContext.resolve(text: "abcdefghijklmnop", candidates: swiss, hypotheses: ["it": 0.90, "fr": 0.05]), "it-CH")
        XCTAssertEqual(TrafficSignOCRLanguageContext.resolve(text: "22-6 h", candidates: ["fr-FR"]), "fr-FR")
    }
}

import Foundation
import XCTest
@testable import SpeedConsumer

final class TrafficSignDocumentationTests: XCTestCase {
    func testReferenceReadsEveryNationalCatalogWithOriginalPictogramsAndSpeech() throws {
        let html = try TrafficSignDocumentationHTML.make(activeCountry: "NLD", locale: "fr")
        let marker = "window.trafficSignDocumentationInput="
        let start = try XCTUnwrap(html.range(of: marker)).upperBound
        let end = try XCTUnwrap(html.range(of: ";</script>", range: start..<html.endIndex)).lowerBound
        let input = try JSONSerialization.jsonObject(with: Data(html[start..<end].utf8)) as! [String: Any]
        XCTAssertEqual(input["activeCountry"] as? String, "NL")
        let catalogs = input["catalogs"] as! [[String: Any]]
        XCTAssertEqual(Set(catalogs.compactMap { $0["country"] as? String }), Set(["DE", "FR", "NL", "BE", "CH"]))
        let images = input["images"] as! [String: String]
        for catalog in catalogs {
            let code = catalog["country"] as! String
            let sourceURL = try XCTUnwrap(Bundle.main.url(forResource: "prolix-\(code.lowercased())-class-catalog-v1", withExtension: "json"))
            let original = try JSONSerialization.jsonObject(with: Data(contentsOf: sourceURL)) as! NSDictionary
            XCTAssertEqual(catalog as NSDictionary, original)
            for sign in catalog["signs"] as! [[String: Any]] where sign["display_eligible"] as? Bool == true {
                let path = sign["image_path"] as! String
                let encoded = try XCTUnwrap(images[path])
                let decoded = try XCTUnwrap(Data(base64Encoded: String(encoded.dropFirst("data:image/png;base64,".count))))
                let source = try Data(contentsOf: Bundle.main.resourceURL!.appendingPathComponent(String(path.dropFirst(4))))
                XCTAssertEqual(decoded, source)
            }
        }
    }
}

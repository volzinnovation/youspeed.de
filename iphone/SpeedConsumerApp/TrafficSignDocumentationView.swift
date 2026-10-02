import Foundation
import SwiftUI

/// Presents the bundled national catalogues without changing recognition or speech policy.
enum TrafficSignDocumentationHTML {
    static func make(activeCountry: String?, locale: String = Bundle.main.preferredLocalizations.first ?? "en", bundle: Bundle = .main) throws -> String {
        let root = bundle.resourceURL!
        let folder = root.appendingPathComponent("traffic-sign-documentation")
        var catalogs: [[String: Any]] = []
        var images: [String: String] = [:]
        for country in TrafficSignModelPackSelection.bundledCountryCodes.sorted() {
            guard let url = bundle.url(forResource: "prolix-\(country.lowercased())-class-catalog-v1", withExtension: "json") else { continue }
            let catalog = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
            catalogs.append(catalog)
            for sign in catalog["signs"] as? [[String: Any]] ?? [] where sign["display_eligible"] as? Bool == true {
                guard let path = sign["image_path"] as? String, path.hasPrefix("tsr/sign-pictograms/"), path.hasSuffix(".png"), !path.split(separator: "/").contains(".."), images[path] == nil else { continue }
                let bytes = try Data(contentsOf: root.appendingPathComponent(String(path.dropFirst(4))))
                images[path] = "data:image/png;base64," + bytes.base64EncodedString()
            }
        }
        func json(_ url: URL) throws -> Any { try JSONSerialization.jsonObject(with: Data(contentsOf: url)) }
        var documentationCountry = PenaltyCountryCode.alpha2(activeCountry) ?? "DE"
        #if DEBUG
        if let requested = PenaltyCountryCode.alpha2(ProcessInfo.processInfo.environment["YOUSPEED_SCREENSHOT_REFERENCE_COUNTRY"]), catalogs.contains(where: { $0["country"] as? String == requested }) {
            documentationCountry = requested
        }
        #endif
        let input: [String: Any] = ["catalogs": catalogs, "images": images, "locale": locale,
            "activeCountry": documentationCountry,
            "translations": try json(folder.appendingPathComponent("translations.json")),
            "commonTranslations": try json(root.appendingPathComponent("penalty-documentation/translations.json"))]
        let data = try JSONSerialization.data(withJSONObject: input, options: [.sortedKeys])
        let encoded = String(decoding: data, as: UTF8.self).replacingOccurrences(of: "<", with: "\\u003c")
        let template = try String(contentsOf: folder.appendingPathComponent("index.html"), encoding: .utf8)
        let renderer = try String(contentsOf: folder.appendingPathComponent("renderer.js"), encoding: .utf8)
        return template.replacingOccurrences(of: "__YOUSPEED_RENDERER__", with: renderer)
            .replacingOccurrences(of: "__YOUSPEED_INPUT__", with: encoded)
    }
}

struct TrafficSignDocumentationView: View {
    let activeCountry: String?
    var body: some View {
        OfflineDocumentationWebView(html: try? TrafficSignDocumentationHTML.make(activeCountry: activeCountry), identifier: "traffic-sign-documentation")
            .navigationTitle(NSLocalizedString("traffic.sign.documentation.title", comment: ""))
            .navigationBarTitleDisplayMode(.inline)
            .subscreenCloseButton()
    }
}

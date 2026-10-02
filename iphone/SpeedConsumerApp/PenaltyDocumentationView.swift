import Foundation
import SwiftUI
import WebKit

/// Uses the original JSON, not a second set of authored penalty values.
enum PenaltyDocumentationHTML {
    static func make(activeRules: SpeedPenaltyRuleSet, locale: String = Bundle.main.preferredLocalizations.first ?? "en",
                     bundle: Bundle = .main) throws -> String {
        let folder = bundle.resourceURL!.appendingPathComponent("penalty-documentation")
        var documents: [String: [String: Any]] = [:]
        let urls = (bundle.urls(forResourcesWithExtension: "json", subdirectory: "Rules") ?? [])
            + (bundle.urls(forResourcesWithExtension: "json", subdirectory: nil) ?? [])
        for url in urls where url.lastPathComponent.hasSuffix("-rules.json") {
            guard let data = try? Data(contentsOf: url),
                  let document = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let code = document["country_code"] as? String ?? document["land_code"] as? String else { continue }
            documents[code] = document
        }
        // A selected downloaded revision is the same effective source the dashboard uses.
        if let data = activeRules.documentationJSON,
           let document = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
            documents[activeRules.countryCode] = document
        }
        let translations = try JSONSerialization.jsonObject(with: Data(contentsOf: folder.appendingPathComponent("translations.json")))
        var documentationCountry = activeRules.countryCode
        #if DEBUG
        if let requested = ProcessInfo.processInfo.environment["YOUSPEED_SCREENSHOT_REFERENCE_COUNTRY"], documents[requested] != nil {
            documentationCountry = requested
        }
        #endif
        let input: [String: Any] = ["documents": documents.keys.sorted().compactMap { documents[$0] },
                                  "translations": translations, "locale": locale, "activeCountry": documentationCountry]
        let data = try JSONSerialization.data(withJSONObject: input, options: [.sortedKeys])
        // Country strings are data, including an embedded closing script tag.
        let json = String(decoding: data, as: UTF8.self).replacingOccurrences(of: "<", with: "\\u003c")
        let template = try String(contentsOf: folder.appendingPathComponent("index.html"), encoding: .utf8)
        let renderer = try String(contentsOf: folder.appendingPathComponent("renderer.js"), encoding: .utf8)
        return template.replacingOccurrences(of: "__YOUSPEED_RENDERER__", with: renderer)
            .replacingOccurrences(of: "__YOUSPEED_INPUT__", with: json)
    }
}

struct PenaltyDocumentationView: View {
    let activeRules: SpeedPenaltyRuleSet
    var body: some View {
        OfflineDocumentationWebView(html: try? PenaltyDocumentationHTML.make(activeRules: activeRules))
            .navigationTitle(NSLocalizedString("penalty.documentation.title", comment: ""))
            .navigationBarTitleDisplayMode(.inline)
            .subscreenCloseButton()
    }
}

struct OfflineDocumentationWebView: UIViewRepresentable {
    let html: String?
    var identifier: String = "penalty-documentation"
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero)
        webView.navigationDelegate = context.coordinator
        webView.accessibilityIdentifier = identifier
        if let html { webView.loadHTMLString(html, baseURL: nil) }
        return webView
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if let url = action.request.url, ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
                if action.navigationType == .linkActivated { UIApplication.shared.open(url) }
                decisionHandler(.cancel)
            } else {
                decisionHandler(action.request.url?.absoluteString == "about:blank" ? .allow : .cancel)
            }
        }
    }
}

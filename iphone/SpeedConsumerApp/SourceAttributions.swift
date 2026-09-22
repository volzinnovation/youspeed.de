import Foundation
import SwiftUI
import UIKit

struct SourceAttributionCatalog: Decodable {
    let schemaVersion: Int
    let reviewedAt: String
    let entries: [SourceAttribution]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case reviewedAt = "reviewed_at"
        case entries
    }

    static func load(bundle: Bundle = .main) -> SourceAttributionCatalog? {
        for candidateBundle in [bundle, Bundle(for: SpeedConsumerAppDelegate.self)] {
            guard let url = candidateBundle.url(
                forResource: "sources", withExtension: "json", subdirectory: "attributions"
            ), let data = try? Data(contentsOf: url),
                  let catalog = try? JSONDecoder().decode(Self.self, from: data),
                  catalog.schemaVersion == 1 else { continue }
            return catalog
        }
        return nil
    }
}

struct SourceAttribution: Decodable, Identifiable {
    let id: String
    let title: String
    let attribution: String
    let license: String
    let sourceURL: String
    let licenseURL: String
    let changes: String
    let category: String

    enum CodingKeys: String, CodingKey {
        case id, title, attribution, license, changes, category
        case sourceURL = "source_url"
        case licenseURL = "license_url"
    }

    static func webURL(_ string: String) -> URL? {
        guard let url = URL(string: string),
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil else { return nil }
        return url
    }
}

struct SourceAttributionsView: View {
    private let catalog = SourceAttributionCatalog.load()
    @State private var query = ""
    private let categories = ["data", "sign", "model", "software", "reference"]

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 16) {
                    Text(NSLocalizedString("about.sources.intro", comment: ""))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    NavigationLink {
                        TrafficSignThirdPartyNoticesView(text: TrafficSignThirdPartyNoticesLoader.load())
                    } label: {
                        Label(NSLocalizedString("about.tsr_attribution.licenses", comment: ""), systemImage: "doc.text")
                    }
                }
                .padding(16)
                .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
                if let catalog {
                    ForEach(categories, id: \.self) { category in
                        let entries = catalog.entries.filter {
                            $0.category == category && matchesSearch($0)
                        }
                        if !entries.isEmpty {
                            Text(NSLocalizedString("about.sources.category.\(category)", comment: ""))
                                .font(.headline)
                                .padding(.top, 8)
                            ForEach(entries) { entry in
                                SourceAttributionRow(entry: entry)
                                    .padding(16)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
                            }
                        }
                    }
                } else {
                    Text(NSLocalizedString("about.sources.unavailable", comment: ""))
                }
            }
            .padding(16)
        }
        .background(Color(.systemGroupedBackground))
        .searchable(text: $query, prompt: Text(NSLocalizedString("about.sources.search", comment: "")))
        .navigationTitle(NSLocalizedString("about.sources.title", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
        .subscreenCloseButton()
    }

    private func matchesSearch(_ entry: SourceAttribution) -> Bool {
        query.isEmpty || [entry.title, entry.attribution, entry.license, entry.changes]
            .contains { $0.localizedCaseInsensitiveContains(query) }
    }
}

private struct SourceAttributionRow: View {
    let entry: SourceAttribution

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(entry.title)
                .font(.headline)
                .lineLimit(nil)
                .fixedSize(horizontal: false, vertical: true)
            MultilineCreditText(text: entry.attribution)
            if !entry.changes.isEmpty {
                Text("\(NSLocalizedString("about.sources.changes", comment: "")): \(entry.changes)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let sourceURL = SourceAttribution.webURL(entry.sourceURL) {
                Link(NSLocalizedString("about.sources.source", comment: ""), destination: sourceURL)
                    .buttonStyle(.borderless)
            }
            if let licenseURL = SourceAttribution.webURL(entry.licenseURL) {
                Link(destination: licenseURL) {
                    Text(entry.license)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                    .buttonStyle(.borderless)
            } else {
                Text(entry.license)
            }
        }
        .font(.subheadline)
        .lineLimit(nil)
        .fixedSize(horizontal: false, vertical: true)
        .padding(.vertical, 6)
    }
}

private struct MultilineCreditText: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UILabel {
        let label = UILabel()
        label.numberOfLines = 0
        label.lineBreakMode = .byWordWrapping
        label.font = .preferredFont(forTextStyle: .subheadline)
        label.adjustsFontForContentSizeCategory = true
        label.textColor = .label
        return label
    }

    func updateUIView(_ uiView: UILabel, context: Context) {
        uiView.text = text
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UILabel, context: Context) -> CGSize? {
        guard let width = proposal.width else { return nil }
        uiView.preferredMaxLayoutWidth = width
        let size = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: width, height: ceil(size.height))
    }
}

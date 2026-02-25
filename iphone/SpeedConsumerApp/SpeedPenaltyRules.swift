import Foundation

enum PenaltySeverity: String, Codable, Sendable {
    case moneyOnly = "money_only"
    case pointsAndFine = "points_and_fine"
}

struct OverspeedPenaltyBand: Codable, Sendable {
    let minDeltaKmh: Int
    let maxDeltaKmh: Int?
    let severity: PenaltySeverity
    let titleTemplate: String
    let detailTemplate: String

    enum CodingKeys: String, CodingKey {
        case minDeltaKmh = "min_delta_kmh"
        case maxDeltaKmh = "max_delta_kmh"
        case severity
        case titleTemplate = "title_template"
        case detailTemplate = "detail_template"
    }
}

struct SpeedPenaltyRuleSet: Codable, Sendable {
    let format: String
    let schemaVersion: Int
    let countryCode: String
    let countryName: String
    let currencyCode: String
    let defaultLanguage: String?
    let bands: [OverspeedPenaltyBand]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case countryCode = "country_code"
        case countryName = "country_name"
        case currencyCode = "currency_code"
        case defaultLanguage = "default_language"
        case bands
    }

    static func loadBundled(named fileStem: String, bundle: Bundle = .main) throws -> SpeedPenaltyRuleSet {
        if let url = bundle.url(forResource: fileStem, withExtension: "json", subdirectory: "Rules") {
            let data = try Data(contentsOf: url)
            return try JSONDecoder().decode(SpeedPenaltyRuleSet.self, from: data)
        }
        if let url = bundle.url(forResource: fileStem, withExtension: "json") {
            let data = try Data(contentsOf: url)
            return try JSONDecoder().decode(SpeedPenaltyRuleSet.self, from: data)
        }
        throw ConsumerAppError.io("Missing bundled rules file \(fileStem).json")
    }

    static func fallbackDEU() -> SpeedPenaltyRuleSet {
        SpeedPenaltyRuleSet(
            format: "youspeed.penalty.rules",
            schemaVersion: 1,
            countryCode: "DEU",
            countryName: "Germany",
            currencyCode: "EUR",
            defaultLanguage: "en",
            bands: [
                OverspeedPenaltyBand(
                    minDeltaKmh: 1,
                    maxDeltaKmh: 10,
                    severity: .moneyOnly,
                    titleTemplate: "Too Fast by {delta} km/h",
                    detailTemplate: "Likely money fine: about 30 to 40 {currency}"
                ),
                OverspeedPenaltyBand(
                    minDeltaKmh: 11,
                    maxDeltaKmh: 20,
                    severity: .moneyOnly,
                    titleTemplate: "Too Fast by {delta} km/h",
                    detailTemplate: "Likely money fine: about 50 to 100 {currency}"
                ),
                OverspeedPenaltyBand(
                    minDeltaKmh: 21,
                    maxDeltaKmh: nil,
                    severity: .pointsAndFine,
                    titleTemplate: "Penalty Points Risk",
                    detailTemplate: "{delta} km/h above limit: likely fine plus points"
                ),
            ]
        )
    }
}

struct SpeedPenaltyNotice: Sendable {
    let severity: PenaltySeverity
    let title: String
    let details: String
    let deltaKmh: Int
}

enum SpeedPenaltyRuleEngine {
    static func resolveNotice(overspeedKmh: Int, rules: SpeedPenaltyRuleSet) -> SpeedPenaltyNotice? {
        guard overspeedKmh > 0 else {
            return nil
        }
        guard let band = rules.bands.first(where: { band in
            if overspeedKmh < band.minDeltaKmh {
                return false
            }
            if let max = band.maxDeltaKmh {
                return overspeedKmh <= max
            }
            return true
        }) else {
            return nil
        }

        return SpeedPenaltyNotice(
            severity: band.severity,
            title: applyTemplate(
                band.titleTemplate,
                deltaKmh: overspeedKmh,
                rules: rules
            ),
            details: applyTemplate(
                band.detailTemplate,
                deltaKmh: overspeedKmh,
                rules: rules
            ),
            deltaKmh: overspeedKmh
        )
    }

    private static func applyTemplate(_ raw: String, deltaKmh: Int, rules: SpeedPenaltyRuleSet) -> String {
        raw
            .replacingOccurrences(of: "{delta}", with: "\(deltaKmh)")
            .replacingOccurrences(of: "{country}", with: rules.countryName)
            .replacingOccurrences(of: "{country_code}", with: rules.countryCode)
            .replacingOccurrences(of: "{currency}", with: rules.currencyCode)
    }
}

import Foundation

enum PenaltySeverity: String, Codable, Sendable {
    case moneyOnly = "money_only"
    case pointsAndFine = "points_and_fine"

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        switch raw {
        case "money_only", "nur_geldbusse":
            self = .moneyOnly
        case "points_and_fine", "punkte_und_geldbusse":
            self = .pointsAndFine
        default:
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unsupported penalty severity: \(raw)"
            )
        }
    }
}

enum PenaltyRoadArea: Sendable {
    case innerorts
    case ausserorts

    init?(insideCity: Bool?) {
        guard let insideCity else {
            return nil
        }
        self = insideCity ? .innerorts : .ausserorts
    }

    var templateToken: String {
        switch self {
        case .innerorts:
            return "innerorts"
        case .ausserorts:
            return "ausserorts"
        }
    }
}

struct LocalityPenaltyVariant: Decodable, Sendable {
    let moneyFineEUR: Int?
    let penaltyPoints: Int?
    let drivingBanMonths: Int?
    let conditionalDrivingBanMonths: Int?
    let drivingBanCondition: String?

    enum CodingKeys: String, CodingKey {
        case moneyFineEUR = "money_fine_eur"
        case moneyFineEURDE = "geldbusse_eur"
        case penaltyPoints = "penalty_points"
        case penaltyPointsDE = "punkte"
        case drivingBanMonths = "driving_ban_months"
        case drivingBanMonthsDE = "fahrverbot_monate"
        case conditionalDrivingBanMonths = "conditional_driving_ban_months"
        case conditionalDrivingBanMonthsDE = "bedingtes_fahrverbot_monate"
        case drivingBanCondition = "driving_ban_condition"
        case drivingBanConditionDE = "fahrverbot_bedingung"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        moneyFineEUR = try container.decodeFirst(Int.self, for: [.moneyFineEUR, .moneyFineEURDE])
        penaltyPoints = try container.decodeFirst(Int.self, for: [.penaltyPoints, .penaltyPointsDE])
        drivingBanMonths = try container.decodeFirst(Int.self, for: [.drivingBanMonths, .drivingBanMonthsDE])
        conditionalDrivingBanMonths = try container.decodeFirst(
            Int.self,
            for: [.conditionalDrivingBanMonths, .conditionalDrivingBanMonthsDE]
        )
        drivingBanCondition = try container.decodeFirst(
            String.self,
            for: [.drivingBanCondition, .drivingBanConditionDE]
        )
    }
}

private struct LocalityPenaltyVariants: Decodable, Sendable {
    let innerorts: LocalityPenaltyVariant?
    let ausserorts: LocalityPenaltyVariant?

    enum CodingKeys: String, CodingKey {
        case innerorts
        case ausserorts
        case ausserortsUmlaut = "außerorts"
        case urban
        case rural
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        innerorts = try container.decodeFirst(
            LocalityPenaltyVariant.self,
            for: [.innerorts, .urban]
        )
        ausserorts = try container.decodeFirst(
            LocalityPenaltyVariant.self,
            for: [.ausserorts, .ausserortsUmlaut, .rural]
        )
    }

    func forArea(_ area: PenaltyRoadArea) -> LocalityPenaltyVariant? {
        switch area {
        case .innerorts:
            return innerorts
        case .ausserorts:
            return ausserorts
        }
    }
}

struct OverspeedPenaltyBand: Decodable, Sendable {
    let minDeltaKmh: Int
    let maxDeltaKmh: Int?
    let severity: PenaltySeverity
    let titleTemplate: String
    let detailTemplate: String
    let moneyFineEUR: Int?
    let penaltyPoints: Int?
    let drivingBanMonths: Int?
    let conditionalDrivingBanMonths: Int?
    let drivingBanCondition: String?
    private let localityVariants: LocalityPenaltyVariants?

    init(
        minDeltaKmh: Int,
        maxDeltaKmh: Int?,
        severity: PenaltySeverity,
        titleTemplate: String,
        detailTemplate: String,
        moneyFineEUR: Int? = nil,
        penaltyPoints: Int? = nil,
        drivingBanMonths: Int? = nil,
        conditionalDrivingBanMonths: Int? = nil,
        drivingBanCondition: String? = nil
    ) {
        self.minDeltaKmh = minDeltaKmh
        self.maxDeltaKmh = maxDeltaKmh
        self.severity = severity
        self.titleTemplate = titleTemplate
        self.detailTemplate = detailTemplate
        self.moneyFineEUR = moneyFineEUR
        self.penaltyPoints = penaltyPoints
        self.drivingBanMonths = drivingBanMonths
        self.conditionalDrivingBanMonths = conditionalDrivingBanMonths
        self.drivingBanCondition = drivingBanCondition
        self.localityVariants = nil
    }

    enum CodingKeys: String, CodingKey {
        case minDeltaKmh = "min_delta_kmh"
        case minDeltaKmhDE = "min_ueber_kmh"
        case maxDeltaKmh = "max_delta_kmh"
        case maxDeltaKmhDE = "max_ueber_kmh"
        case severity
        case severityDE = "schweregrad"
        case titleTemplate = "title_template"
        case titleTemplateDE = "titel_vorlage"
        case detailTemplate = "detail_template"
        case detailTemplateDE = "detail_vorlage"
        case moneyFineEUR = "money_fine_eur"
        case moneyFineEURDE = "geldbusse_eur"
        case penaltyPoints = "penalty_points"
        case penaltyPointsDE = "punkte"
        case drivingBanMonths = "driving_ban_months"
        case drivingBanMonthsDE = "fahrverbot_monate"
        case conditionalDrivingBanMonths = "conditional_driving_ban_months"
        case conditionalDrivingBanMonthsDE = "bedingtes_fahrverbot_monate"
        case drivingBanCondition = "driving_ban_condition"
        case drivingBanConditionDE = "fahrverbot_bedingung"
        case localityVariants = "locality_variants"
        case localityVariantsDE = "ortsvarianten"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        guard let minDelta = try container.decodeFirst(Int.self, for: [.minDeltaKmh, .minDeltaKmhDE]) else {
            throw DecodingError.keyNotFound(
                CodingKeys.minDeltaKmh,
                DecodingError.Context(codingPath: container.codingPath, debugDescription: "Missing min delta key")
            )
        }

        let maxDelta = try container.decodeFirst(Int.self, for: [.maxDeltaKmh, .maxDeltaKmhDE])
        let points = try container.decodeFirst(Int.self, for: [.penaltyPoints, .penaltyPointsDE])
        let severityValue = try container.decodeFirst(PenaltySeverity.self, for: [.severity, .severityDE])
        let severity = severityValue ?? ((points ?? 0) > 0 ? .pointsAndFine : .moneyOnly)

        self.minDeltaKmh = minDelta
        self.maxDeltaKmh = maxDelta
        self.severity = severity
        self.titleTemplate = try container.decodeFirst(String.self, for: [.titleTemplate, .titleTemplateDE])
            ?? "Zu schnell um {delta} km/h"
        self.detailTemplate = try container.decodeFirst(String.self, for: [.detailTemplate, .detailTemplateDE])
            ?? ""
        self.moneyFineEUR = try container.decodeFirst(Int.self, for: [.moneyFineEUR, .moneyFineEURDE])
        self.penaltyPoints = points
        self.drivingBanMonths = try container.decodeFirst(Int.self, for: [.drivingBanMonths, .drivingBanMonthsDE])
        self.conditionalDrivingBanMonths = try container.decodeFirst(
            Int.self,
            for: [.conditionalDrivingBanMonths, .conditionalDrivingBanMonthsDE]
        )
        self.drivingBanCondition = try container.decodeFirst(
            String.self,
            for: [.drivingBanCondition, .drivingBanConditionDE]
        )
        self.localityVariants = try container.decodeFirst(
            LocalityPenaltyVariants.self,
            for: [.localityVariants, .localityVariantsDE]
        )
    }

    func variant(for area: PenaltyRoadArea?) -> LocalityPenaltyVariant? {
        guard let area, let localityVariants else {
            return nil
        }
        return localityVariants.forArea(area)
    }
}

struct SpeedPenaltyRuleSet: Decodable, Sendable {
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
        case countryCodeDE = "land_code"
        case countryName = "country_name"
        case countryNameDE = "land_name"
        case currencyCode = "currency_code"
        case currencyCodeDE = "waehrung_code"
        case defaultLanguage = "default_language"
        case defaultLanguageDE = "standardsprache"
        case bands
        case bandsDE = "stufen"
    }

    init(
        format: String,
        schemaVersion: Int,
        countryCode: String,
        countryName: String,
        currencyCode: String,
        defaultLanguage: String?,
        bands: [OverspeedPenaltyBand]
    ) {
        self.format = format
        self.schemaVersion = schemaVersion
        self.countryCode = countryCode
        self.countryName = countryName
        self.currencyCode = currencyCode
        self.defaultLanguage = defaultLanguage
        self.bands = bands
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        format = try container.decode(String.self, forKey: .format)
        schemaVersion = try container.decodeFirst(Int.self, for: [.schemaVersion]) ?? 1
        countryCode = try container.decodeFirst(String.self, for: [.countryCode, .countryCodeDE]) ?? "DEU"
        countryName = try container.decodeFirst(String.self, for: [.countryName, .countryNameDE]) ?? "Deutschland"
        currencyCode = try container.decodeFirst(String.self, for: [.currencyCode, .currencyCodeDE]) ?? "EUR"
        defaultLanguage = try container.decodeFirst(String.self, for: [.defaultLanguage, .defaultLanguageDE])
        bands = try container.decodeFirst([OverspeedPenaltyBand].self, for: [.bands, .bandsDE]) ?? []
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
                    detailTemplate: "Likely money fine: about 30 to 40 {currency}",
                    moneyFineEUR: 30
                ),
                OverspeedPenaltyBand(
                    minDeltaKmh: 11,
                    maxDeltaKmh: 15,
                    severity: .moneyOnly,
                    titleTemplate: "Too Fast by {delta} km/h",
                    detailTemplate: "Likely money fine: about 50 to 70 {currency}",
                    moneyFineEUR: 50
                ),
                OverspeedPenaltyBand(
                    minDeltaKmh: 16,
                    maxDeltaKmh: 20,
                    severity: .moneyOnly,
                    titleTemplate: "Too Fast by {delta} km/h",
                    detailTemplate: "Likely money fine: about 70 to 100 {currency}",
                    moneyFineEUR: 70
                ),
                OverspeedPenaltyBand(
                    minDeltaKmh: 21,
                    maxDeltaKmh: 30,
                    severity: .pointsAndFine,
                    titleTemplate: "Penalty Points Risk",
                    detailTemplate: "{delta} km/h above limit: likely fine plus 1 point",
                    penaltyPoints: 1
                ),
                OverspeedPenaltyBand(
                    minDeltaKmh: 31,
                    maxDeltaKmh: nil,
                    severity: .pointsAndFine,
                    titleTemplate: "High Violation",
                    detailTemplate: "{delta} km/h above limit: likely high fine and points",
                    penaltyPoints: 2
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
    let moneyFineEUR: Int?
    let penaltyPoints: Int?
    let drivingBanMonths: Int?
    let conditionalDrivingBanMonths: Int?
    let drivingBanCondition: String?
}

enum SpeedPenaltyRuleEngine {
    static func resolveNotice(overspeedKmh: Int, rules: SpeedPenaltyRuleSet, insideCity: Bool? = nil) -> SpeedPenaltyNotice? {
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
        let area = PenaltyRoadArea(insideCity: insideCity)
        let variant = band.variant(for: area)
        let moneyFine = variant?.moneyFineEUR ?? band.moneyFineEUR
        let points = variant?.penaltyPoints ?? band.penaltyPoints
        let drivingBanMonths = variant?.drivingBanMonths ?? band.drivingBanMonths
        let conditionalDrivingBanMonths = variant?.conditionalDrivingBanMonths ?? band.conditionalDrivingBanMonths
        let drivingBanCondition = variant?.drivingBanCondition ?? band.drivingBanCondition
        let severity = ((points ?? 0) > 0) ? PenaltySeverity.pointsAndFine : .moneyOnly

        return SpeedPenaltyNotice(
            severity: severity,
            title: applyTemplate(
                band.titleTemplate,
                deltaKmh: overspeedKmh,
                rules: rules,
                area: area
            ),
            details: applyTemplate(
                band.detailTemplate,
                deltaKmh: overspeedKmh,
                rules: rules,
                area: area
            ),
            deltaKmh: overspeedKmh,
            moneyFineEUR: moneyFine,
            penaltyPoints: points,
            drivingBanMonths: drivingBanMonths,
            conditionalDrivingBanMonths: conditionalDrivingBanMonths,
            drivingBanCondition: drivingBanCondition
        )
    }

    private static func applyTemplate(
        _ raw: String,
        deltaKmh: Int,
        rules: SpeedPenaltyRuleSet,
        area: PenaltyRoadArea?
    ) -> String {
        let areaToken = area?.templateToken ?? "unbekannt"
        return raw
            .replacingOccurrences(of: "{delta}", with: "\(deltaKmh)")
            .replacingOccurrences(of: "{country}", with: rules.countryName)
            .replacingOccurrences(of: "{land}", with: rules.countryName)
            .replacingOccurrences(of: "{country_code}", with: rules.countryCode)
            .replacingOccurrences(of: "{land_code}", with: rules.countryCode)
            .replacingOccurrences(of: "{currency}", with: rules.currencyCode)
            .replacingOccurrences(of: "{waehrung}", with: rules.currencyCode)
            .replacingOccurrences(of: "{locality}", with: areaToken)
            .replacingOccurrences(of: "{bereich}", with: areaToken)
    }
}

private extension KeyedDecodingContainer {
    func decodeFirst<T: Decodable>(_ type: T.Type, for keys: [Key]) throws -> T? {
        for key in keys where contains(key) {
            return try decodeIfPresent(T.self, forKey: key)
        }
        return nil
    }
}

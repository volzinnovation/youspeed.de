package de.youspeed.android.alpha

import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

enum class PenaltySeverity {
    MONEY_ONLY,
    POINTS_AND_FINE;

    companion object {
        fun fromRaw(raw: String?): PenaltySeverity {
            return when (raw?.trim()?.lowercase(Locale.US)) {
                "money_only", "nur_geldbusse" -> MONEY_ONLY
                "points_and_fine", "punkte_und_geldbusse" -> POINTS_AND_FINE
                else -> MONEY_ONLY
            }
        }
    }
}

enum class PenaltyRoadArea(val templateToken: String) {
    INNERORTS("innerorts"),
    AUSSERORTS("ausserorts");

    companion object {
        fun fromInsideCity(insideCity: Boolean?): PenaltyRoadArea? {
            return when (insideCity) {
                true -> INNERORTS
                false -> AUSSERORTS
                null -> null
            }
        }
    }
}

data class LocalityPenaltyVariant(
    val moneyFineEUR: Int? = null,
    val penaltyPoints: Int? = null,
    val drivingBanMonths: Int? = null,
    val conditionalDrivingBanMonths: Int? = null,
    val drivingBanCondition: String? = null,
)

data class OverspeedPenaltyBand(
    val minDeltaKmh: Int,
    val maxDeltaKmh: Int?,
    val severity: PenaltySeverity,
    val titleTemplate: String,
    val detailTemplate: String,
    val moneyFineEUR: Int? = null,
    val penaltyPoints: Int? = null,
    val drivingBanMonths: Int? = null,
    val conditionalDrivingBanMonths: Int? = null,
    val drivingBanCondition: String? = null,
    val innerortsVariant: LocalityPenaltyVariant? = null,
    val ausserortsVariant: LocalityPenaltyVariant? = null,
) {
    fun variantFor(area: PenaltyRoadArea?): LocalityPenaltyVariant? {
        return when (area) {
            PenaltyRoadArea.INNERORTS -> innerortsVariant
            PenaltyRoadArea.AUSSERORTS -> ausserortsVariant
            null -> null
        }
    }
}

data class SpeedPenaltyRuleSet(
    val format: String,
    val schemaVersion: Int,
    val countryCode: String,
    val countryName: String,
    val currencyCode: String,
    val defaultLanguage: String?,
    val bands: List<OverspeedPenaltyBand>,
) {
    companion object {
        fun fallbackDEU(): SpeedPenaltyRuleSet {
            return SpeedPenaltyRuleSet(
                format = "youspeed.penalty.rules",
                schemaVersion = 1,
                countryCode = "DEU",
                countryName = "Germany",
                currencyCode = "EUR",
                defaultLanguage = "en",
                bands = listOf(
                    OverspeedPenaltyBand(
                        minDeltaKmh = 1,
                        maxDeltaKmh = 10,
                        severity = PenaltySeverity.MONEY_ONLY,
                        titleTemplate = "Too Fast by {delta} km/h",
                        detailTemplate = "Likely money fine: about 30 to 40 {currency}",
                        moneyFineEUR = 30,
                    ),
                    OverspeedPenaltyBand(
                        minDeltaKmh = 11,
                        maxDeltaKmh = 15,
                        severity = PenaltySeverity.MONEY_ONLY,
                        titleTemplate = "Too Fast by {delta} km/h",
                        detailTemplate = "Likely money fine: about 50 to 70 {currency}",
                        moneyFineEUR = 50,
                    ),
                    OverspeedPenaltyBand(
                        minDeltaKmh = 16,
                        maxDeltaKmh = 20,
                        severity = PenaltySeverity.MONEY_ONLY,
                        titleTemplate = "Too Fast by {delta} km/h",
                        detailTemplate = "Likely money fine: about 70 to 100 {currency}",
                        moneyFineEUR = 70,
                    ),
                    OverspeedPenaltyBand(
                        minDeltaKmh = 21,
                        maxDeltaKmh = 30,
                        severity = PenaltySeverity.POINTS_AND_FINE,
                        titleTemplate = "Penalty Points Risk",
                        detailTemplate = "{delta} km/h above limit: likely fine plus 1 point",
                        penaltyPoints = 1,
                    ),
                    OverspeedPenaltyBand(
                        minDeltaKmh = 31,
                        maxDeltaKmh = null,
                        severity = PenaltySeverity.POINTS_AND_FINE,
                        titleTemplate = "High Violation",
                        detailTemplate = "{delta} km/h above limit: likely high fine and points",
                        penaltyPoints = 2,
                    ),
                ),
            )
        }
    }
}

data class ActivePenaltyRules(
    val fileName: String,
    val ruleSet: SpeedPenaltyRuleSet,
) {
    val countryCode: String
        get() = ruleSet.countryCode

    val countryName: String
        get() = ruleSet.countryName

    val currencyCode: String
        get() = ruleSet.currencyCode

    val bandCount: Int
        get() = ruleSet.bands.size

    companion object {
        fun fallback(): ActivePenaltyRules {
            return ActivePenaltyRules(
                fileName = "DEU-rules.json",
                ruleSet = SpeedPenaltyRuleSet.fallbackDEU(),
            )
        }
    }
}

data class SpeedPenaltyNotice(
    val severity: PenaltySeverity,
    val title: String,
    val details: String,
    val deltaKmh: Int,
    val moneyFineEUR: Int?,
    val penaltyPoints: Int?,
    val drivingBanMonths: Int?,
    val conditionalDrivingBanMonths: Int?,
    val drivingBanCondition: String?,
)

object PenaltyRulesParser {
    private val json = Json { ignoreUnknownKeys = true }

    fun parse(raw: String): SpeedPenaltyRuleSet {
        val root = json.parseToJsonElement(raw).jsonObject
        val bands = root.valueForArray("bands", "stufen").orEmpty().map { parseBand(it.jsonObject) }
        return SpeedPenaltyRuleSet(
            format = root.valueForString("format") ?: "youspeed.penalty.rules",
            schemaVersion = root.valueForInt("schema_version") ?: 1,
            countryCode = root.valueForString("country_code", "land_code") ?: "DEU",
            countryName = root.valueForString("country_name", "land_name") ?: "Deutschland",
            currencyCode = root.valueForString("currency_code", "waehrung_code") ?: "EUR",
            defaultLanguage = root.valueForString("default_language", "standardsprache"),
            bands = bands,
        )
    }

    private fun parseBand(root: JsonObject): OverspeedPenaltyBand {
        val points = root.valueForInt("penalty_points", "punkte")
        val severity = root.valueForString("severity", "schweregrad")?.let(PenaltySeverity::fromRaw)
            ?: if ((points ?: 0) > 0) PenaltySeverity.POINTS_AND_FINE else PenaltySeverity.MONEY_ONLY
        val variantsRoot = root.valueForObject("locality_variants", "ortsvarianten")
        return OverspeedPenaltyBand(
            minDeltaKmh = root.valueForInt("min_delta_kmh", "min_ueber_kmh") ?: 0,
            maxDeltaKmh = root.valueForNullableInt("max_delta_kmh", "max_ueber_kmh"),
            severity = severity,
            titleTemplate = root.valueForString("title_template", "titel_vorlage") ?: "Zu schnell um {delta} km/h",
            detailTemplate = root.valueForString("detail_template", "detail_vorlage").orEmpty(),
            moneyFineEUR = root.valueForInt("money_fine_eur", "geldbusse_eur"),
            penaltyPoints = points,
            drivingBanMonths = root.valueForInt("driving_ban_months", "fahrverbot_monate"),
            conditionalDrivingBanMonths = root.valueForInt(
                "conditional_driving_ban_months",
                "bedingtes_fahrverbot_monate",
            ),
            drivingBanCondition = root.valueForString("driving_ban_condition", "fahrverbot_bedingung"),
            innerortsVariant = parseVariant(variantsRoot?.valueForObject("innerorts", "urban")),
            ausserortsVariant = parseVariant(variantsRoot?.valueForObject("ausserorts", "außerorts", "rural")),
        )
    }

    private fun parseVariant(root: JsonObject?): LocalityPenaltyVariant? {
        root ?: return null
        return LocalityPenaltyVariant(
            moneyFineEUR = root.valueForInt("money_fine_eur", "geldbusse_eur"),
            penaltyPoints = root.valueForInt("penalty_points", "punkte"),
            drivingBanMonths = root.valueForInt("driving_ban_months", "fahrverbot_monate"),
            conditionalDrivingBanMonths = root.valueForInt(
                "conditional_driving_ban_months",
                "bedingtes_fahrverbot_monate",
            ),
            drivingBanCondition = root.valueForString("driving_ban_condition", "fahrverbot_bedingung"),
        )
    }
}

object SpeedPenaltyRuleEngine {
    fun resolveNotice(
        overspeedKmh: Int,
        rules: SpeedPenaltyRuleSet,
        insideCity: Boolean? = null,
    ): SpeedPenaltyNotice? {
        if (overspeedKmh <= 0) {
            return null
        }
        val band = rules.bands.firstOrNull { candidate ->
            if (overspeedKmh < candidate.minDeltaKmh) {
                return@firstOrNull false
            }
            val max = candidate.maxDeltaKmh
            max == null || overspeedKmh <= max
        } ?: return null
        val area = PenaltyRoadArea.fromInsideCity(insideCity)
        val variant = band.variantFor(area)
        val points = variant?.penaltyPoints ?: band.penaltyPoints
        val moneyFine = variant?.moneyFineEUR ?: band.moneyFineEUR
        val drivingBanMonths = variant?.drivingBanMonths ?: band.drivingBanMonths
        val conditionalDrivingBanMonths = variant?.conditionalDrivingBanMonths ?: band.conditionalDrivingBanMonths
        val drivingBanCondition = variant?.drivingBanCondition ?: band.drivingBanCondition
        val severity = if ((points ?: 0) > 0) PenaltySeverity.POINTS_AND_FINE else band.severity
        return SpeedPenaltyNotice(
            severity = severity,
            title = applyTemplate(band.titleTemplate, overspeedKmh, rules, area),
            details = applyTemplate(band.detailTemplate, overspeedKmh, rules, area),
            deltaKmh = overspeedKmh,
            moneyFineEUR = moneyFine,
            penaltyPoints = points,
            drivingBanMonths = drivingBanMonths,
            conditionalDrivingBanMonths = conditionalDrivingBanMonths,
            drivingBanCondition = drivingBanCondition,
        )
    }

    private fun applyTemplate(
        raw: String,
        deltaKmh: Int,
        rules: SpeedPenaltyRuleSet,
        area: PenaltyRoadArea?,
    ): String {
        val areaToken = area?.templateToken ?: "unbekannt"
        return raw
            .replace("{delta}", deltaKmh.toString())
            .replace("{country}", rules.countryName)
            .replace("{land}", rules.countryName)
            .replace("{country_code}", rules.countryCode)
            .replace("{land_code}", rules.countryCode)
            .replace("{currency}", rules.currencyCode)
            .replace("{waehrung}", rules.currencyCode)
            .replace("{locality}", areaToken)
            .replace("{bereich}", areaToken)
    }
}

private fun JsonObject.valueForString(vararg keys: String): String? {
    for (key in keys) {
        val value = this[key] ?: continue
        if (value is JsonPrimitive) {
            return value.content.trim()
        }
    }
    return null
}

private fun JsonObject.valueForInt(vararg keys: String): Int? {
    for (key in keys) {
        val value = this[key] ?: continue
        val primitive = value as? JsonPrimitive ?: continue
        primitive.intOrNull?.let { return it }
    }
    return null
}

private fun JsonObject.valueForNullableInt(vararg keys: String): Int? {
    for (key in keys) {
        val value = this[key] ?: continue
        if (value is JsonPrimitive && value.content == "null") {
            return null
        }
        val primitive = value as? JsonPrimitive ?: continue
        primitive.intOrNull?.let { return it }
    }
    return null
}

private fun JsonObject.valueForArray(vararg keys: String): JsonArray? {
    for (key in keys) {
        val value = this[key] ?: continue
        return value.jsonArray
    }
    return null
}

private fun JsonObject.valueForObject(vararg keys: String): JsonObject? {
    for (key in keys) {
        val value = this[key] ?: continue
        return value.jsonObject
    }
    return null
}

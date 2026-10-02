package de.youspeed.android.alpha

import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
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
        fun fromRaw(raw: String): PenaltySeverity {
            return when (raw.trim().lowercase(Locale.US)) {
                "money_only", "nur_geldbusse" -> MONEY_ONLY
                "points_and_fine", "punkte_und_geldbusse" -> POINTS_AND_FINE
                else -> throw IllegalArgumentException("Unsupported penalty severity: $raw")
            }
        }
    }
}

enum class PenaltyRoadArea(val templateToken: String) {
    INNERORTS("innerorts"),
    AUSSERORTS("ausserorts"),
    MOTORWAY("autobahn");

    companion object {
        fun matchedMotorway(highway: String?): Boolean? = when (highway) {
            "motorway" -> true
            "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service", "primary_link", "secondary_link", "tertiary_link" -> false
            else -> null
        }
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

data class PenaltyTemplates(val titleTemplate: String, val detailTemplate: String)

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
    val atMost50Variant: LocalityPenaltyVariant? = null,
    val above50Variant: LocalityPenaltyVariant? = null,
    val localizedTemplates: Map<String, PenaltyTemplates> = emptyMap(),
    val enforcementClass: String? = null,
    val motorwayVariant: LocalityPenaltyVariant? = null,
) {
    fun variantFor(area: PenaltyRoadArea?): LocalityPenaltyVariant? {
        return when (area) {
            PenaltyRoadArea.INNERORTS -> innerortsVariant
            PenaltyRoadArea.AUSSERORTS -> ausserortsVariant
            PenaltyRoadArea.MOTORWAY -> motorwayVariant
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
    val contentRevision: Int = 0,
    val requiresRoadCategory: Boolean = false,
    val localizedAdvisoryCaptions: Map<String, String> = emptyMap(),
    val postedLimitEscalation: PostedLimitPenaltyEscalation? = null,
    val speedingTariffs: SpeedingTariffTable? = null,
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

        fun prefersDownloaded(downloaded: SpeedPenaltyRuleSet, packaged: SpeedPenaltyRuleSet?): Boolean =
            packaged == null || downloaded.contentRevision >= packaged.contentRevision
    }
}

data class ActivePenaltyRules(
    val fileName: String,
    val ruleSet: SpeedPenaltyRuleSet,
) {
    val countryCode: String
        get() = ruleSet.countryCode

    val countryName: String
        get() = PenaltyCountryCodes.alpha2(countryCode)?.let { Locale("", it).getDisplayCountry(Locale.getDefault()) } ?: ruleSet.countryName

    val isAvailable: Boolean
        get() = ruleSet.bands.isNotEmpty()

    val currencyCode: String
        get() = ruleSet.currencyCode

    val bandCount: Int
        get() = ruleSet.bands.size

    companion object {
        fun unavailable(countryCode: String? = null): ActivePenaltyRules = ActivePenaltyRules(
            fileName = "",
            ruleSet = SpeedPenaltyRuleSet("youspeed.penalty.rules", 1, countryCode ?: "", "", "EUR", "en", emptyList()),
        )

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
    val enforcementClass: String? = null,
    val advisoryCaption: String? = null,
)

data class SpeedingTariffCategory(val finesEUR: Map<String, Int>, val criminalFromDeltaKmh: Int)
data class SpeedingTariffTable(
    val administrativeFeeEUR: Int,
    val minimumDeltaKmh: Int,
    val motorway130MinimumDeltaKmh: Int,
    val roadCategories: Map<String, SpeedingTariffCategory>,
    val localizedTemplates: Map<String, PenaltyTemplates>,
    val localizedBelowThresholdTemplates: Map<String, PenaltyTemplates>,
    val localizedCriminalTemplates: Map<String, PenaltyTemplates>,
    val localizedCriminalCaptions: Map<String, String>,
    val localizedUnknownCategoryCaptions: Map<String, String>,
) {
    fun category(area: PenaltyRoadArea?, postedLimit: Int?): SpeedingTariffCategory? {
        if (area == null || postedLimit == null || postedLimit <= 0) return null
        val key = when (area) {
            PenaltyRoadArea.MOTORWAY -> "motorway"
            PenaltyRoadArea.AUSSERORTS -> "rural"
            PenaltyRoadArea.INNERORTS -> when (postedLimit) { 30 -> "urban_30"; 15 -> "urban_15"; else -> "urban" }
        }
        return roadCategories[key]
    }
    fun fine(excess: Int, area: PenaltyRoadArea?, postedLimit: Int?): Int? {
        val category = category(area, postedLimit) ?: return null
        postedLimit ?: return null
        // Do not deduct a police measurement margin from live GPS speed.
        val minimum = if (area == PenaltyRoadArea.MOTORWAY && postedLimit == 130) motorway130MinimumDeltaKmh else minimumDeltaKmh
        if (excess < minimum && postedLimit <= 120) return 0
        if (excess < minimum) return null
        return category.finesEUR[excess.toString()]
    }
}

data class PostedLimitPenaltyThreshold(val maxPostedLimitKmh: Int?, val minDeltaKmh: Int)
data class PostedLimitPenaltyEscalation(
    val thresholds: List<PostedLimitPenaltyThreshold>,
    val drivingBanMonths: Int,
    val conditionalDrivingBanMonths: Int,
    val drivingBanCondition: String,
    val localizedTemplates: Map<String, PenaltyTemplates>,
    val localizedCaptions: Map<String, String>,
) {
    fun applies(excess: Int, postedLimit: Int?): Boolean {
        if (postedLimit == null || postedLimit <= 0) return false
        val threshold = thresholds.firstOrNull { it.maxPostedLimitKmh == null || postedLimit <= it.maxPostedLimitKmh } ?: return false
        return excess >= threshold.minDeltaKmh
    }
}

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
            contentRevision = root.valueForInt("content_revision") ?: 0,
            speedingTariffs = root.valueForObject("speeding_tariffs")?.let { table ->
                fun templates(key: String) = table.valueForObject(key)!!.mapValues { (_, value) ->
                    val row = value.jsonObject
                    PenaltyTemplates(row.valueForString("title_template")!!, row.valueForString("detail_template")!!)
                }
                fun captions(key: String) = table.valueForObject(key)!!.mapValues { it.value.jsonPrimitive.content }
                SpeedingTariffTable(
                    administrativeFeeEUR = table.valueForInt("administrative_fee_eur")!!,
                    minimumDeltaKmh = table.valueForInt("minimum_delta_kmh")!!,
                    motorway130MinimumDeltaKmh = table.valueForInt("motorway_130_minimum_delta_kmh")!!,
                    roadCategories = table.valueForObject("road_categories")!!.mapValues { (_, value) ->
                        val row = value.jsonObject
                        SpeedingTariffCategory(row.valueForObject("fines_eur")!!.mapValues { it.value.jsonPrimitive.intOrNull!! },
                            row.valueForInt("criminal_from_delta_kmh")!!)
                    },
                    localizedTemplates = templates("localized_templates"),
                    localizedBelowThresholdTemplates = templates("localized_below_threshold_templates"),
                    localizedCriminalTemplates = templates("localized_criminal_templates"),
                    localizedCriminalCaptions = captions("localized_criminal_captions"),
                    localizedUnknownCategoryCaptions = captions("localized_unknown_category_captions"),
                )
            },
            requiresRoadCategory = root["requires_road_category"]?.jsonPrimitive?.booleanOrNull ?: false,
            localizedAdvisoryCaptions = root.valueForObject("localized_advisory_captions")?.mapValues { it.value.jsonPrimitive.content }.orEmpty(),
            postedLimitEscalation = root.valueForObject("posted_limit_escalation")?.let { risk ->
                PostedLimitPenaltyEscalation(
                    thresholds = risk.valueForArray("thresholds").orEmpty().map { it.jsonObject.let { threshold ->
                        PostedLimitPenaltyThreshold(threshold.valueForInt("max_posted_limit_kmh"), threshold.valueForInt("min_delta_kmh") ?: error("Missing excess threshold"))
                    } },
                    drivingBanMonths = risk.valueForInt("driving_ban_months") ?: error("Missing minimum withdrawal"),
                    conditionalDrivingBanMonths = risk.valueForInt("conditional_driving_ban_months") ?: error("Missing exceptional minimum"),
                    drivingBanCondition = risk.valueForString("driving_ban_condition") ?: error("Missing withdrawal scope"),
                    localizedTemplates = risk.valueForObject("localized_templates")?.mapValues { (_, it) ->
                        PenaltyTemplates(it.jsonObject.valueForString("title_template").orEmpty(), it.jsonObject.valueForString("detail_template").orEmpty())
                    }.orEmpty(),
                    localizedCaptions = risk.valueForObject("localized_captions")?.mapValues { it.value.jsonPrimitive.content }.orEmpty(),
                )
            },
        )
    }

    private fun parseBand(root: JsonObject): OverspeedPenaltyBand {
        val points = root.valueForInt("penalty_points", "punkte")
        // Like Swift's decodeFirst, the first present key wins, including null.
        // Missing/null severity is inferred from points; malformed values are not.
        val severityValue = listOf("severity", "schweregrad").firstOrNull(root::containsKey)?.let(root::get)
        val severity = severityValue?.takeUnless { it == JsonNull }?.let {
            require(it is JsonPrimitive && it.isString) { "Penalty severity must be a string" }
            PenaltySeverity.fromRaw(it.content)
        }
            ?: if ((points ?: 0) > 0) PenaltySeverity.POINTS_AND_FINE else PenaltySeverity.MONEY_ONLY
        val variantsRoot = root.valueForObject("locality_variants", "ortsvarianten")
        val postedVariants = root.valueForObject("posted_limit_variants")
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
            motorwayVariant = parseVariant(variantsRoot?.valueForObject("motorway")),
            atMost50Variant = parseVariant(postedVariants?.valueForObject("at_most_50")),
            above50Variant = parseVariant(postedVariants?.valueForObject("above_50")),
            localizedTemplates = root.valueForObject("localized_templates")?.mapValues { (_, element) ->
                val template = element.jsonObject
                PenaltyTemplates(template.valueForString("title_template").orEmpty(), template.valueForString("detail_template").orEmpty())
            }.orEmpty(),
            enforcementClass = root.valueForString("enforcement_class"),
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
        postedSpeedLimitKmh: Int? = null,
        locale: Locale = Locale.getDefault(),
        isMotorway: Boolean? = null,
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
        val area = if (rules.requiresRoadCategory) when (isMotorway) {
            true -> PenaltyRoadArea.MOTORWAY
            false -> PenaltyRoadArea.fromInsideCity(insideCity)
            null -> null
        } else PenaltyRoadArea.fromInsideCity(insideCity)
        val postedVariant = when {
            postedSpeedLimitKmh == null || postedSpeedLimitKmh <= 0 -> null
            postedSpeedLimitKmh <= 50 -> band.atMost50Variant
            else -> band.above50Variant
        }
        val variant = postedVariant ?: band.variantFor(area)
        val escalation = rules.postedLimitEscalation?.takeIf { it.applies(overspeedKmh, postedSpeedLimitKmh) }
        val tariff = rules.speedingTariffs
        val tariffFine = tariff?.fine(overspeedKmh, area, postedSpeedLimitKmh)
        val tariffCategory = tariff?.category(area, postedSpeedLimitKmh)
        val tariffCriminal = tariff != null && (tariffCategory?.let { overspeedKmh >= it.criminalFromDeltaKmh } ?: (overspeedKmh >= 40))
        val tariffTemplates = if (tariffFine != null) {
            if (tariffFine == 0) tariff!!.localizedBelowThresholdTemplates else tariff!!.localizedTemplates
        } else if (tariffCriminal && overspeedKmh < 50) tariff!!.localizedCriminalTemplates else null
        val templates = tariffTemplates?.get(locale.language) ?: tariffTemplates?.get("en") ?: escalation?.localizedTemplates?.get(locale.language) ?: escalation?.localizedTemplates?.get("en") ?: band.localizedTemplates[locale.language]
            ?: band.localizedTemplates[rules.defaultLanguage] ?: band.localizedTemplates["en"]
        val points = variant?.penaltyPoints ?: band.penaltyPoints
        val categoryKnown = !rules.requiresRoadCategory || (area != null && (postedSpeedLimitKmh ?: 0) > 0)
        val moneyFine = if (tariff != null) tariffFine else if (escalation == null && categoryKnown) variant?.moneyFineEUR ?: band.moneyFineEUR else null
        val drivingBanMonths = escalation?.drivingBanMonths ?: if (categoryKnown) variant?.drivingBanMonths ?: band.drivingBanMonths else null
        val conditionalDrivingBanMonths = escalation?.conditionalDrivingBanMonths ?: if (categoryKnown) variant?.conditionalDrivingBanMonths ?: band.conditionalDrivingBanMonths else null
        val drivingBanCondition = escalation?.drivingBanCondition ?: variant?.drivingBanCondition ?: band.drivingBanCondition
        val severity = if ((points ?: 0) > 0) PenaltySeverity.POINTS_AND_FINE else band.severity
        return SpeedPenaltyNotice(
            severity = severity,
            title = applyTemplate(templates?.titleTemplate ?: band.titleTemplate, overspeedKmh, rules, area),
            details = applyTemplate((templates?.detailTemplate ?: band.detailTemplate)
                .replace("{fine}", tariffFine?.toString().orEmpty())
                .replace("{fee}", tariff?.administrativeFeeEUR?.toString().orEmpty()), overspeedKmh, rules, area),
            deltaKmh = overspeedKmh,
            moneyFineEUR = moneyFine,
            penaltyPoints = points,
            drivingBanMonths = drivingBanMonths,
            conditionalDrivingBanMonths = conditionalDrivingBanMonths,
            drivingBanCondition = drivingBanCondition,
            enforcementClass = if (tariff != null) {
                if (tariffCriminal) "criminal" else if (tariffFine != null) "administrative" else "context_dependent"
            } else if (escalation == null) band.enforcementClass else "raser",
            advisoryCaption = (if (tariff != null && tariffFine == null) {
                val captions = if (tariffCriminal) tariff.localizedCriminalCaptions else tariff.localizedUnknownCategoryCaptions
                captions[locale.language] ?: captions["en"]
            } else null) ?: escalation?.localizedCaptions?.get(locale.language) ?: escalation?.localizedCaptions?.get("en")
                ?: rules.localizedAdvisoryCaptions[locale.language] ?: rules.localizedAdvisoryCaptions["en"],
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

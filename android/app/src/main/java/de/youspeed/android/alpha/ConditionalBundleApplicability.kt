package de.youspeed.android.alpha

/** Opaque producer evidence; the reference interpreter does not evaluate this AST. */
internal fun conditionalBundleApplicability(rule:ConditionalSpeedRules.Reevaluation,result:ConditionalSpeedRules.Result,atMs:Long):Map<String,Any?> = mapOf(
    "status" to if(result.unresolved) "unresolved" else "applicable",
    "context_revision" to 0,
    "conditions" to mapOf("source" to "osm_conditional_rule_set","grammar" to "youspeed-osm-speed-1",
        "rule_set_ast_json" to rule.rulesJSON,"evaluated_at_ms" to atMs,
        "result" to if(result.unresolved) "unresolved" else "effective_value_selected",
        "reason" to result.reason,"effective_value" to when {result.unlimited -> mapOf("kind" to "unlimited");result.kmh!=null -> mapOf("kind" to "numeric","kmh" to result.kmh);else -> null},
        "independent_base_kmh" to rule.baseKmh,"independent_base_unlimited" to rule.baseUnlimited,
        "direction" to rule.direction,"country" to rule.countryCode,"time_zone" to (rule.timeZoneId ?: if(rule.countryCode?.uppercase() in setOf("DE","DEU")) "Europe/Berlin" else null)))

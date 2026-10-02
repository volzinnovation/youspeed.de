package de.youspeed.android.alpha

import kotlin.math.roundToInt

object DrivingRoadIdentity {
    const val MAXIMUM_ASSERTION_AGE_SECONDS = 300L
    fun key(ref: String?, name: String?, highway: String?): String? {
        val refs = ref.orEmpty().uppercase().split(";").map { it.filterNot(Char::isWhitespace) }.filter { it.isNotEmpty() }.sorted()
        val ramp = if (highway?.endsWith("_link") == true) ":ramp" else ""
        if (refs.isNotEmpty()) return "ref:" + refs.joinToString(";") + ramp
        val normalizedName = name?.trim()?.lowercase()?.replace(Regex("\\s+"), " ").orEmpty()
        return normalizedName.takeIf { it.isNotEmpty() }?.let { "name:$it$ramp" }
    }
}

/** Same statutory defaults and strict tag parsing as iPhone RoadSpeedDefaults. */
object RoadSpeedDefaults {
    fun country(raw: String?): String {
        val code = raw?.trim()?.uppercase().orEmpty()
        return mapOf("DEU" to "DE", "FRA" to "FR", "BEL" to "BE", "NLD" to "NL", "CHE" to "CH")[code] ?: code
    }
    fun explicitSpeed(raw: String?): Int? {
        val value = raw?.trim()?.lowercase() ?: return null
        if (!Regex("^[0-9]{1,3}(\\s*(km/h|kmh|kph|mph))?$").matches(value)) return null
        val number = value.takeWhile { it.isDigit() }.toDoubleOrNull() ?: return null
        val kmh = (number * if (value.endsWith("mph")) 1.609344 else 1.0).roundToInt()
        return kmh.takeIf { it in 1..300 }
    }
    fun symbolicSpeed(raw: String?, fallbackCountry: String?): Int? {
        val parts = raw?.trim()?.lowercase()?.split(":") ?: return null
        if (parts.size !in 1..2) return null
        val code = country(if (parts.size == 2) parts[0] else fallbackCountry)
        return when (parts.last()) {
            "urban" -> speedKmh(code, null, null, true)
            "rural" -> speedKmh(code, null, "road", false)
            "motorway" -> speedKmh(code, null, "motorway", false)
            "trunk" -> if (code == "FR") 110 else speedKmh(code, null, "trunk", false)
            else -> null
        }
    }
    fun speedKmh(country: String?, region: String?, highway: String?, insideCity: Boolean?): Int? {
        val code = RoadSpeedDefaults.country(country)
        val road = highway?.lowercase()
        if (road == "motorway") return when (code) { "BE", "CH" -> 120; "FR" -> 130; else -> null }
        if (road == "living_street" && code == "FR") return 20
        if (insideCity == null) return null
        if (insideCity) {
            if (code == "BE") return when (region) { "BE-BRU" -> 30; "BE-VLG", "BE-WAL" -> 50; else -> null }
            return if (code in setOf("DE", "FR", "NL", "CH")) 50 else null
        }
        if (road == "trunk" && code in setOf("NL", "CH")) return 100
        if (road !in setOf("primary", "secondary", "tertiary", "unclassified", "residential", "service", "road")) return null
        return when (code) {
            "DE" -> 100
            "FR", "NL", "CH" -> 80
            "BE" -> when (region) { "BE-VLG" -> 70; "BE-WAL" -> 90; else -> null }
            else -> null
        }
    }
}

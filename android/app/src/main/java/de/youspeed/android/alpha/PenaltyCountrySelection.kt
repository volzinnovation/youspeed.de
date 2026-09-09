package de.youspeed.android.alpha

import java.util.Locale

object PenaltyCountryCodes {
    private val codes = mapOf("DE" to "DEU", "FR" to "FRA", "NL" to "NLD", "BE" to "BEL",
        "LU" to "LUX", "RO" to "ROU", "SE" to "SWE", "IS" to "ISL", "GB" to "GBR",
        "LI" to "LIE", "MC" to "MCO", "CH" to "CHE")

    fun normalize(raw: String?): String? {
        val code = raw?.trim()?.uppercase(Locale.ROOT) ?: return null
        return codes[code] ?: code.takeIf { it in codes.values }
    }

    fun alpha2(raw: String?): String? = normalize(raw)?.let { normalized -> codes.entries.first { it.value == normalized }.key }
}

/** Conservative country selection from offline extract coverage, not an administrative border claim.
 * Overlapping coverage, invalid fixes and pending transitions never display the previous country's fine.
 */
class PenaltyCountrySelection {
    private val selection = TrafficSignCountrySelection()
    private var lastAcceptedTimestamp: Double? = null

    fun update(catalog: RegionalPackCatalog?, latitude: Double, longitude: Double, accuracy: Double,
               timestamp: Double, now: Double): String? {
        val accepted = FirstLocationPackPolicy.acceptsFix(latitude, longitude, accuracy, timestamp, now)
        if (!accepted) {
            selection.suspendPendingTransition()
            return null
        }
        if (lastAcceptedTimestamp?.let { timestamp - it > 30.0 } == true) selection.suspendPendingTransition()
        if (lastAcceptedTimestamp == null || timestamp > lastAcceptedTimestamp!!) lastAcceptedTimestamp = timestamp
        val countries = catalog?.matches(longitude, latitude)?.map { it.country }?.toSet().orEmpty()
        return PenaltyCountryCodes.normalize(selection.update(countries, timestamp))
    }
}

/** Reproducible native UI scenario. Supplies GPS/road/speed inputs, never precomputed penalty output. */
data class CountryPenaltyScreenshotScenario(val countryCode: String, val deltaKmh: Int, val limitKmh: Int = 50) {
    init {
        require(countryCode in setOf("FRA", "NLD", "BEL"))
        require(deltaKmh in 0..100 && limitKmh in 10..130)
    }
    val latitude: Double get() = when (countryCode) { "FRA" -> 48.8566; "NLD" -> 52.3676; else -> 50.8503 }
    val longitude: Double get() = when (countryCode) { "FRA" -> 2.3522; "NLD" -> 4.9041; else -> 4.3517 }
    val city: String get() = when (countryCode) { "FRA" -> "Paris"; "NLD" -> "Amsterdam"; else -> "Bruxelles / Brussel" }
    val street: String get() = when (countryCode) { "FRA" -> "Rue de Rivoli"; "NLD" -> "Stadhouderskade"; else -> "Rue de la Loi / Wetstraat" }
}

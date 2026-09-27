package de.youspeed.android.alpha

/** Country metadata belongs to a database path, not the last downloaded country. */
internal data class LookupCountrySource(val dbPath: String, val countryCode: String?)

internal fun lookupCountryForDatabase(
    dbPath: String,
    selected: LookupCountrySource?,
    installed: LookupCountrySource?,
    inferredCountryCode: String?,
): String? = selected?.takeIf { it.dbPath == dbPath }?.countryCode?.let(PenaltyCountryCodes::normalize)
    ?: installed?.takeIf { it.dbPath == dbPath }?.countryCode?.let(PenaltyCountryCodes::normalize)
    ?: PenaltyCountryCodes.normalize(inferredCountryCode)

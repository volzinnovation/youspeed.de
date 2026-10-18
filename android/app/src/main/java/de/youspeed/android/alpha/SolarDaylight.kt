package de.youspeed.android.alpha

import java.time.Instant
import java.time.ZoneOffset
import kotlin.math.*

/** NOAA general solar-position equations, evaluated at an absolute UTC instant.
 * https://gml.noaa.gov/grad/solcalc/solareqns.PDF
 * No timezone lookup or DST/country rules are required. */
internal object SolarDaylight {
    fun elevationDegrees(latitude: Double, longitude: Double, at: Instant): Double? {
        if (!latitude.isFinite() || latitude !in -90.0..90.0 ||
            !longitude.isFinite() || longitude !in -180.0..180.0) return null
        val utc = at.atOffset(ZoneOffset.UTC)
        val hours = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
        val gamma = 2 * PI / utc.toLocalDate().lengthOfYear() * (utc.dayOfYear - 1 + (hours - 12) / 24)
        val equation = 229.18 * (0.000075 + 0.001868 * cos(gamma) - 0.032077 * sin(gamma)
            - 0.014615 * cos(2 * gamma) - 0.040849 * sin(2 * gamma))
        val declination = 0.006918 - 0.399912 * cos(gamma) + 0.070257 * sin(gamma)
            - 0.006758 * cos(2 * gamma) + 0.000907 * sin(2 * gamma)
            - 0.002697 * cos(3 * gamma) + 0.00148 * sin(3 * gamma)
        val hourAngle = (hours * 60 + equation + 4 * longitude) / 4 - 180
        val lat = Math.toRadians(latitude)
        val sine = sin(lat) * sin(declination) + cos(lat) * cos(declination) * cos(Math.toRadians(hourAngle))
        return Math.toDegrees(asin(sine.coerceIn(-1.0, 1.0)))
    }

    /** Standard sunrise/sunset horizon. Unknown location leaves camera TSR paused. */
    fun permitsCameraTSR(latitude: Double?, longitude: Double?, at: Instant): Boolean =
        latitude != null && longitude != null && (elevationDegrees(latitude, longitude, at)?.let { it >= -0.833 } == true)
}

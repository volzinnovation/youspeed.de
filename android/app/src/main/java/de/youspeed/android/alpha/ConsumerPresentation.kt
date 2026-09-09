package de.youspeed.android.alpha

import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt

object ConsumerMainScreenLogic {
    fun hasUsableGpsFix(state: ConsumerUiState): Boolean {
        return state.currentLatitude != null && state.currentLongitude != null && state.gpsSignalBars > 0
    }

    fun isInSpeedCaptureMode(state: ConsumerUiState): Boolean {
        return state.speedCaptureMode != SpeedCaptureModeState.IDLE
    }

    fun isSearchingSignal(state: ConsumerUiState): Boolean = !hasUsableGpsFix(state)

    fun currentOverspeedKmh(state: ConsumerUiState): Int {
        if (state.isUnlimitedSpeedLimitActive) {
            return 0
        }
        val speedLimit = state.speedLimitKmh ?: return 0
        return max(0, state.currentSpeedKmh.roundToInt() - speedLimit)
    }

    fun currentPenaltyNotice(state: ConsumerUiState): SpeedPenaltyNotice? {
        if (state.tunnelModeState == TunnelModeState.ACTIVE || state.isUnlimitedSpeedLimitActive || isInSpeedCaptureMode(state)) {
            return null
        }
        return SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh = currentOverspeedKmh(state),
            rules = state.activePenaltyRules.ruleSet,
            insideCity = state.lastLookupInsideCity,
            postedSpeedLimitKmh = state.speedLimitKmh,
        )
    }

    fun primaryMetricText(state: ConsumerUiState): String {
        if (isInSpeedCaptureMode(state)) {
            return when (state.speedCaptureMode) {
                SpeedCaptureModeState.REQUESTING_MIC_PERMISSION -> ConsumerUiStrings.text("Allow", "Mikrofon", "Autoriser", "Sta toe")
                SpeedCaptureModeState.PREPARING -> ConsumerUiStrings.text("Preparing", "Bereite", "Préparation", "Voorbereiden")
                SpeedCaptureModeState.SPEAKING_PROMPT, SpeedCaptureModeState.LISTENING -> ConsumerUiStrings.text("Speak", "Jetzt", "Parlez", "Spreek")
                SpeedCaptureModeState.EVALUATING -> ConsumerUiStrings.text("Checking", "Prüfe", "Vérification", "Controleren")
                SpeedCaptureModeState.SAVING -> ConsumerUiStrings.text("Saving", "Speichere", "Enregistrement", "Opslaan")
                SpeedCaptureModeState.FAILED -> ConsumerUiStrings.text("Try", "Erneut", "Réessayez", "Probeer")
                SpeedCaptureModeState.IDLE -> ""
            }
        }
        val notice = currentPenaltyNotice(state)
        val drivingBanMonths = notice?.drivingBanMonths ?: 0
        if (drivingBanMonths > 0) {
            return drivingBanMonths.toString()
        }
        return when (notice?.severity) {
            PenaltySeverity.MONEY_ONLY -> notice.moneyFineEUR?.toString() ?: "!"
            PenaltySeverity.POINTS_AND_FINE -> notice.penaltyPoints?.takeIf { it > 0 }?.toString() ?: "!"
            null -> if (isSearchingSignal(state)) " " else state.currentSpeedKmh.roundToInt().toString()
        }
    }

    fun secondaryMetricText(state: ConsumerUiState): String {
        if (isInSpeedCaptureMode(state)) {
            return when (state.speedCaptureMode) {
                SpeedCaptureModeState.REQUESTING_MIC_PERMISSION -> ConsumerUiStrings.text("microphone", "erlauben", "le microphone", "microfoon")
                SpeedCaptureModeState.PREPARING -> ConsumerUiStrings.text("offline", "offline", "hors ligne", "offline")
                SpeedCaptureModeState.SPEAKING_PROMPT, SpeedCaptureModeState.LISTENING -> ConsumerUiStrings.text("now", "sprechen", "maintenant", "nu")
                SpeedCaptureModeState.EVALUATING -> ConsumerUiStrings.text("input", "Eingabe", "de la saisie", "invoer")
                SpeedCaptureModeState.SAVING -> ConsumerUiStrings.text("value", "Wert", "de la valeur", "waarde")
                SpeedCaptureModeState.FAILED -> ConsumerUiStrings.text("again", "sprechen", "de parler", "opnieuw")
                SpeedCaptureModeState.IDLE -> ""
            }
        }
        val notice = currentPenaltyNotice(state)
        val drivingBanMonths = notice?.drivingBanMonths ?: 0
        if (drivingBanMonths > 0) {
            return localizedDrivingBanLabel(drivingBanMonths)
        }
        if (notice != null && notice.moneyFineEUR == null && (notice.penaltyPoints ?: 0) == 0) {
            return ConsumerUiStrings.text("Review", "Prüfen", "À vérifier", "Controleren")
        }
        return when (notice?.severity) {
            PenaltySeverity.MONEY_ONLY -> state.activePenaltyRules.currencyCode
            PenaltySeverity.POINTS_AND_FINE -> {
                val points = notice.penaltyPoints
                localizedPointsLabel(points ?: 0)
            }
            null -> if (isSearchingSignal(state)) localizedSearchingSignalLabel() else "km/h"
        }
    }

    fun limitText(state: ConsumerUiState): String {
        if (isInSpeedCaptureMode(state)) {
            return "?"
        }
        state.speedLimitDisplayText?.let { return it }
        val speedLimit = state.speedLimitKmh
        return when {
            speedLimit != null -> speedLimit.toString()
            hasUsableGpsFix(state) -> "–"
            else -> "?"
        }
    }

    fun showsPedestrianZoneSign(state: ConsumerUiState): Boolean {
        return !isInSpeedCaptureMode(state) && state.speedLimitDisplayText == "Schritt"
    }

    fun debugCoordinateText(state: ConsumerUiState): String {
        if (isInSpeedCaptureMode(state)) {
            return ""
        }
        val street = normalizedPlaceText(state.limitStreetName)
        if (street != null && state.limitWayId != null) {
            return street
        }
        val latitude = state.currentLatitude
        val longitude = state.currentLongitude
        if (latitude == null || longitude == null) {
            return ConsumerUiStrings.text("Searching…", "Suche…", "Recherche…", "Zoeken…")
        }
        return iso6709Coordinate(latitude = latitude, longitude = longitude, fractionalDigits = 3)
    }

    fun debugWayIdText(state: ConsumerUiState): String {
        if (isInSpeedCaptureMode(state)) {
            return ""
        }
        val city = normalizedPlaceText(state.limitCityName ?: state.limitCityPlaceName)
        if (city != null) {
            return city
        }
        return if (hasUsableGpsFix(state)) {
            ConsumerUiStrings.text("City unknown", "Stadt unbekannt", "Ville inconnue", "Plaats onbekend")
        } else {
            ConsumerUiStrings.text("Searching…", "Suche…", "Recherche…", "Zoeken…")
        }
    }

    fun shouldShowCityBadge(state: ConsumerUiState): Boolean {
        if (isInSpeedCaptureMode(state)) {
            return false
        }
        return cityBadgeStreetText(state) != null ||
            cityBadgePlaceText(state) != null ||
            cityBadgeDistrictText(state) != null
    }

    fun shouldHighlightCityBadge(state: ConsumerUiState): Boolean = state.lastLookupInsideCity == true

    fun cityBadgeStreetText(state: ConsumerUiState): String? = normalizedPlaceText(state.limitStreetName)

    fun cityBadgePlaceText(state: ConsumerUiState): String? {
        return normalizedPlaceText(state.limitCityPlaceName)
            ?: normalizedPlaceText(state.limitCityName)
    }

    fun cityBadgeDistrictText(state: ConsumerUiState): String? = normalizedPlaceText(state.limitCityDistrictName)

    fun isDrivingBanWarningActive(state: ConsumerUiState): Boolean {
        return (currentPenaltyNotice(state)?.drivingBanMonths ?: 0) > 0
    }

    fun overspeedBackgroundProgress(state: ConsumerUiState): Double? {
        if (!hasUsableGpsFix(state) || isInSpeedCaptureMode(state)) {
            return null
        }
        val overspeed = currentOverspeedKmh(state)
        if (overspeed <= 0) {
            return null
        }
        if (isDrivingBanWarningActive(state) || currentPenaltyNotice(state)?.enforcementClass != null) {
            return 1.0
        }
        val pointThreshold = minOverspeedForPoints(state).coerceAtLeast(1).toDouble()
        val drivingBanThreshold = max(minOverspeedForDrivingBan(state), minOverspeedForPoints(state) + 1).toDouble()
        val notice = currentPenaltyNotice(state)
        if (notice?.severity == PenaltySeverity.POINTS_AND_FINE) {
            val normalized = ((overspeed - pointThreshold) / max(1.0, drivingBanThreshold - pointThreshold)).coerceIn(0.0, 1.0)
            return 0.68 + (normalized * 0.27)
        }
        val normalized = (overspeed / pointThreshold).coerceIn(0.0, 1.0)
        return normalized * 0.62
    }

    fun usesDarkForeground(state: ConsumerUiState): Boolean {
        if (isInSpeedCaptureMode(state)) {
            return true
        }
        if (state.isUnlimitedSpeedLimitActive && !isInSpeedCaptureMode(state)) {
            return true
        }
        val progress = overspeedBackgroundProgress(state) ?: return false
        return progress < 0.45
    }

    private fun minOverspeedForPoints(state: ConsumerUiState): Int {
        return state.activePenaltyRules.ruleSet.bands
            .filter { band -> band.severity == PenaltySeverity.POINTS_AND_FINE || (band.penaltyPoints ?: 0) > 0 }
            .minOfOrNull { it.minDeltaKmh }
            ?: 21
    }

    private fun minOverspeedForDrivingBan(state: ConsumerUiState): Int {
        return state.activePenaltyRules.ruleSet.bands
            .filter { band ->
                (band.drivingBanMonths ?: 0) > 0 ||
                    (band.conditionalDrivingBanMonths ?: 0) > 0 ||
                    (band.innerortsVariant?.drivingBanMonths ?: 0) > 0 ||
                    (band.ausserortsVariant?.drivingBanMonths ?: 0) > 0 ||
                    (band.innerortsVariant?.conditionalDrivingBanMonths ?: 0) > 0 ||
                    (band.ausserortsVariant?.conditionalDrivingBanMonths ?: 0) > 0
            }
            .minOfOrNull { it.minDeltaKmh }
            ?: (minOverspeedForPoints(state) + 10)
    }

    private fun normalizedPlaceText(raw: String?): String? {
        val trimmed = raw?.trim().orEmpty()
        return trimmed.ifEmpty { null }
    }

    private fun localizedDrivingBanLabel(months: Int): String {
        val one = months == 1
        return when (Locale.getDefault().language.lowercase(Locale.US)) {
            "de" -> if (one) "Monat Fahrverbot" else "Monate Fahrverbot"
            "nl" -> if (one) "maand rijverbod" else "maanden rijverbod"
            "fr" -> "mois d'interdiction"
            else -> if (one) "month driving ban" else "months driving ban"
        }
    }

    private fun localizedPointsLabel(points: Int): String {
        val one = points == 1
        return when (Locale.getDefault().language.lowercase(Locale.US)) {
            "de" -> if (one) "Punkt" else "Punkte"
            "nl" -> if (one) "punt" else "punten"
            "fr" -> if (one) "point" else "points"
            else -> if (one) "point" else "points"
        }
    }

    private fun localizedSearchingSignalLabel(): String {
        return when (Locale.getDefault().language.lowercase(Locale.US)) {
            "de" -> "Suche Signal"
            "nl" -> "Signaal zoeken"
            "fr" -> "Recherche signal"
            else -> "Searching signal"
        }
    }

    private fun iso6709Coordinate(latitude: Double, longitude: Double, fractionalDigits: Int): String {
        val latSign = if (latitude >= 0) "N" else "S"
        val lonSign = if (longitude >= 0) "O" else "W"
        val latBody = String.format(
            Locale.US,
            "%0${3 + 1 + fractionalDigits}.${fractionalDigits}f",
            kotlin.math.abs(latitude),
        )
        val lonBody = String.format(
            Locale.US,
            "%0${3 + 1 + fractionalDigits}.${fractionalDigits}f",
            kotlin.math.abs(longitude),
        )
        return "$latSign$latBody $lonSign$lonBody"
    }
}

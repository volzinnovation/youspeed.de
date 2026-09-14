package de.youspeed.android.alpha

/**
 * Remembers only a camera-entry confirmation across short gaps in map evidence.
 * This memory never supplies the displayed city flag, statutory default, or penalty context.
 * Call under the controller's traffic-sign state lock.
 */
internal class TrafficSignCityEntryTracker {
    private data class Confirmation(
        val insideCity: Boolean,
        val source: String,
        val position: TrafficSignPositionSample,
    )

    private var confirmation: Confirmation? = null
    private var bundleRevision: String? = null
    private var lastObservedTimestampMs: Long? = null

    fun reset() {
        confirmation = null
        bundleRevision = null
        lastObservedTimestampMs = null
    }

    fun observe(
        insideCity: Boolean?,
        citySource: String?,
        position: TrafficSignPositionSample,
        revision: String,
    ): Boolean {
        if (revision != bundleRevision) reset()
        bundleRevision = revision
        if (!position.latitude.isFinite() || position.latitude !in -90.0..90.0 ||
            !position.longitude.isFinite() || position.longitude !in -180.0..180.0
        ) {
            reset()
            return false
        }
        if (lastObservedTimestampMs?.let { position.timestampMs < it } == true) {
            reset()
            return false
        }
        lastObservedTimestampMs = position.timestampMs
        confirmation?.let { previous ->
            val elapsedMs = position.timestampMs - previous.position.timestampMs
            if (elapsedMs < 0L) {
                reset()
                return false
            }
            if (elapsedMs > MAXIMUM_GAP_MS || distanceMeters(
                    previous.position.latitude, previous.position.longitude,
                    position.latitude, position.longitude,
                ) > MAXIMUM_GAP_METERS
            ) confirmation = null
        }
        if (insideCity == null || citySource?.startsWith("settlement:") != true || !citySource.endsWith(":high")) {
            return false
        }
        val entered = TrafficSignBundleContextPolicy.enteredCity(
            previousInsideCity = confirmation?.insideCity,
            currentInsideCity = insideCity,
            previousCitySource = confirmation?.source,
            currentCitySource = citySource,
        )
        confirmation = Confirmation(insideCity, citySource, position)
        return entered
    }

    companion object {
        const val MAXIMUM_GAP_MS = 8_000L
        const val MAXIMUM_GAP_METERS = 160.0
    }
}

package de.youspeed.android.alpha

/** Version 1; mirrored by Swift TripMeasurement and shared fixtures. */
internal object TripMeasurement {
    fun acceptedDistance(seconds: Double, metres: Double, accuracy: Double, previousAccuracy: Double, speed: Double): Double {
        if (!listOf(seconds,metres,accuracy,previousAccuracy,speed).all { it.isFinite() } ||
            seconds<=0 || seconds>15 || metres<maxOf(3.0,accuracy,previousAccuracy) || metres/seconds>70 || speed<=0.5) return 0.0
        return kotlin.math.floor(metres*1000+0.5)/1000
    }
}

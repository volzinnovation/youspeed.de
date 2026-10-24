package de.youspeed.android.alpha

import android.content.Context
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.os.SystemClock
import kotlinx.serialization.json.*
import java.time.Instant
import kotlin.math.*

/** Optical axis in north/east/up coordinates; screen rotation never changes it. */
internal data class SignCollectionCameraSample(val at: Instant, val azimuth: Double, val elevation: Double, val accuracy: String) {
    companion object {
        fun rotationMatrix(r: FloatArray, at: Instant, accuracy: String): SignCollectionCameraSample? {
            if (r.size != 9) return null
            return opticalAxis(-r[5].toDouble(),-r[2].toDouble(),-r[8].toDouble(),at,accuracy)
        }
        fun opticalAxis(north: Double, east: Double, up: Double, at: Instant, accuracy: String): SignCollectionCameraSample? {
            if (!listOf(north,east,up).all { it.isFinite() } || accuracy !in setOf("medium","high") || hypot(north,east) <= 0.1) return null
            return SignCollectionCameraSample(at, (Math.toDegrees(atan2(east,north))+360)%360,
                Math.toDegrees(atan2(up,hypot(north,east))), accuracy)
        }
    }
    fun wire(frameAt: Instant, declination: Double): JsonObject? {
        val delta = java.time.Duration.between(at, frameAt).toNanos()/1_000_000.0
        if (abs(delta) > 500 || !declination.isFinite()) return null
        return buildJsonObject {
            put("azimuth_degrees", ((azimuth+declination)%360+360)%360); put("elevation_degrees", elevation)
            put("reference", "true_north"); put("optical_axis", "rear_camera"); put("measured_at", at.toString())
            put("frame_measurement_delta_ms", delta); put("accuracy_status", accuracy); put("source", "android_rotation_vector")
        }
    }
}

internal class SignCollectionCameraHistory {
    private val samples = ArrayDeque<SignCollectionCameraSample>()
    @Synchronized fun append(sample: SignCollectionCameraSample) { samples.addLast(sample); while (samples.size > 240) samples.removeFirst() }
    @Synchronized fun clear() = samples.clear()
    @Synchronized fun direction(at: Instant, declination: Double): JsonObject? =
        samples.minByOrNull { abs(java.time.Duration.between(it.at, at).toNanos()) }?.wire(at,declination)
}

/** Absolute magnetic rotation vector, corrected to true north at the frame's GPS fix. */
internal class SignCollectionCameraDirection(context: Context) : SensorEventListener {
    private val sensors = context.getSystemService(SensorManager::class.java)
    private val sensor = sensors.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    private val history = SignCollectionCameraHistory()
    private var active = false
    private var bootUTC = Instant.EPOCH
    fun setActive(value: Boolean) {
        if (active == value) return
        active = value; sensors.unregisterListener(this); history.clear()
        if (value && sensor != null) {
            bootUTC = Instant.now().minusNanos(SystemClock.elapsedRealtimeNanos())
            sensors.registerListener(this, sensor, 50_000)
        }
    }
    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) { if (accuracy < SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM) history.clear() }
    override fun onSensorChanged(event: SensorEvent) {
        if (!active) return
        val accuracy = when (event.accuracy) {
            SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> "high"
            SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> "medium"
            else -> { history.clear(); return }
        }
        val r = FloatArray(9); SensorManager.getRotationMatrixFromVector(r,event.values)
        // Android's ENU rotation matrix maps device to world; rear camera is -Z.
        val sample = SignCollectionCameraSample.rotationMatrix(r,bootUTC.plusNanos(event.timestamp), accuracy)
        if (sample == null) history.clear() else history.append(sample)
    }
    fun direction(at: Instant, fix: Location): JsonObject? {
        val declination = GeomagneticField(fix.latitude.toFloat(),fix.longitude.toFloat(),
            (if (fix.hasAltitude()) fix.altitude else 0.0).toFloat(),at.toEpochMilli()).declination.toDouble()
        return history.direction(at,declination)
    }
}

package de.youspeed.android.alpha

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.Looper

/** Foreground posture intake also runs while a dialog is open or GPS reports movement. */
internal class DrivingControlPostureMotion(context: Context, private val onAngleChanged: (Double?) -> Unit) {
    private val manager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
    private val sensor = manager?.getDefaultSensor(Sensor.TYPE_GRAVITY)
        ?: manager?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private var registered = false
    private var filtered: DoubleArray? = null
    private val listener = object : SensorEventListener {
        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
            if (registered && accuracy == SensorManager.SENSOR_STATUS_UNRELIABLE) {
                filtered = null
                onAngleChanged(null)
            }
        }

        override fun onSensorChanged(event: SensorEvent) {
            if (!registered) return
            if (event.accuracy == SensorManager.SENSOR_STATUS_UNRELIABLE || event.values.size < 3) {
                filtered = null
                onAngleChanged(null)
                return
            }
            // TYPE_GRAVITY is already filtered by Android. Only the accelerometer fallback
            // needs a low-pass filter to separate gravity from brief hand movements.
            val previous = filtered
            val vector = DoubleArray(3) { index ->
                val value = event.values[index].toDouble() / 9.80665
                if (sensor?.type == Sensor.TYPE_ACCELEROMETER && previous != null) {
                    previous[index] + 0.25 * (value - previous[index])
                } else value
            }
            // Android's sensor vector has the opposite sign to downward gravity.
            val angle = DrivingControlPosturePolicy.screenAngleDegrees(-vector[0], -vector[1], -vector[2])
            filtered = vector.takeIf { angle != null }
            onAngleChanged(angle)
        }
    }

    fun start() {
        if (registered) return
        registered = sensor != null && runCatching {
            manager?.registerListener(listener, sensor, 100_000, Handler(Looper.getMainLooper())) == true
        }.getOrDefault(false)
        if (!registered) onAngleChanged(null)
    }

    fun stop() {
        registered = false
        manager?.unregisterListener(listener)
        filtered = null
        onAngleChanged(null)
    }
}

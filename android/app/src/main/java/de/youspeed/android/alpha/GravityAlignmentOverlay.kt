package de.youspeed.android.alpha

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlin.math.max
import kotlin.math.min

/** The dashboard supplies its stationary-only visibility and 10%-by-10% bounds. */
@Composable
fun GravityAlignmentOverlay(orientation: ManualOrientation, modifier: Modifier = Modifier,
                            foregroundColor: Color = Color.White) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var reading by remember(orientation) { mutableStateOf<GravityAlignmentReading?>(null) }
    DisposableEffect(context, lifecycleOwner, orientation) {
        val manager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
        val sensor = manager?.getDefaultSensor(Sensor.TYPE_GRAVITY)
            ?: manager?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        var registered = false
        var filtered: DoubleArray? = null
        val listener = object : SensorEventListener {
            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
            override fun onSensorChanged(event: SensorEvent) {
                if (!registered || event.values.size < 3) return
                val previous = filtered
                val alpha = 0.25
                val vector = DoubleArray(3) { index ->
                    val value = event.values[index].toDouble()
                    previous?.let { it[index] + alpha * (value - it[index]) } ?: value
                }
                filtered = vector
                reading = GravityAlignmentGeometry.fromAndroidGravity(vector[0], vector[1], vector[2], orientation)
            }
        }
        fun stop() {
            registered = false
            manager?.unregisterListener(listener)
            filtered = null
            reading = null
        }
        fun start() {
            if (!registered && sensor != null) {
                registered = manager?.registerListener(listener, sensor, 100_000, Handler(Looper.getMainLooper())) == true
            }
        }
        val observer = LifecycleEventObserver { _, _ ->
            if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) start() else stop()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) start()
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            stop()
        }
    }
    val title = stringResource(R.string.gravity_alignment_title)
    val value = reading?.let { stringResource(R.string.gravity_alignment_angles, it.rollDegrees, it.tiltDegrees) }
        ?: stringResource(R.string.gravity_alignment_unavailable)
    val primary = foregroundColor
    Canvas(modifier.clipToBounds().testTag("gravity-alignment").semantics {
        contentDescription = "$title. $value"
    }) {
        val center = Offset(size.width / 2, size.height / 2)
        val radius = min(size.width, size.height) * 0.12f
        val stroke = max(1f, min(size.width, size.height) * 0.045f)
        val neutral = primary.copy(alpha = 0.45f)
        drawLine(neutral, Offset(size.width * 0.12f, center.y), Offset(size.width * 0.35f, center.y), stroke)
        drawLine(neutral, Offset(size.width * 0.65f, center.y), Offset(size.width * 0.88f, center.y), stroke)
        drawCircle(neutral, radius, center, style = Stroke(stroke))
        reading?.let { reading ->
            val offset = (reading.tiltDegrees / 20).coerceIn(-1.0, 1.0).toFloat() * size.height * 0.32f
            val color = if (reading.isLevel) Color(0xFF34C759) else primary
            rotate(-reading.rollDegrees.toFloat(), center) {
                drawLine(color, Offset(size.width * 0.10f, center.y + offset),
                    Offset(size.width * 0.90f, center.y + offset), stroke)
                drawCircle(color, radius * 0.55f, Offset(center.x, center.y + offset))
            }
        }
    }
}

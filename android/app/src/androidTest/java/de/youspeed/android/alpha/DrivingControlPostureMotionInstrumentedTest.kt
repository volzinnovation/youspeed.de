package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Opt-in hardware check: contains no camera, real journal or location access. */
@RunWith(AndroidJUnit4::class)
class DrivingControlPostureMotionInstrumentedTest {
    @Test fun liveFaceUpDeskProvidesFlatPosture() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        assumeTrue(InstrumentationRegistry.getArguments().getString("live_desk_posture")=="true")
        val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        val manager=context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val sensor=manager.getDefaultSensor(Sensor.TYPE_GRAVITY) ?: manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        val raw=CopyOnWriteArrayList<String>()
        val angles=CopyOnWriteArrayList<Double?>()
        val ready=CountDownLatch(1)
        val listener=object:SensorEventListener {
            override fun onAccuracyChanged(sensor:Sensor?,accuracy:Int) {}
            override fun onSensorChanged(event:SensorEvent) {
                if(raw.size<10) raw.add("accuracy=${event.accuracy}, gravity=${event.values.take(3)}")
            }
        }
        val motion=DrivingControlPostureMotion(context) {angle->angles.add(angle);if(angle!=null) ready.countDown()}
        ActivityScenario.launch<MainActivity>(Intent(context,MainActivity::class.java).putExtra("screenshot_state","camera-limit-active")).use {
            try {
                instrumentation.runOnMainSync {manager.registerListener(listener,sensor,100_000);motion.start()}
                val received=ready.await(5,TimeUnit.SECONDS)
                assertTrue("No usable posture: sensor=$sensor raw=$raw angles=$angles",received)
                val angle=angles.last {it!=null}
                assertTrue("Place the phone face up and flat: angle=$angle raw=$raw",DrivingControlPosturePolicy.isFlat(angle))
            } finally {instrumentation.runOnMainSync {motion.stop();manager.unregisterListener(listener)}}
        }
    }
}

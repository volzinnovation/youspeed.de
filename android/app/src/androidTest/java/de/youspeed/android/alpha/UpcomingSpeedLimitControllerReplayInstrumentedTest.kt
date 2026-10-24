package de.youspeed.android.alpha

import android.content.Context
import android.location.Location
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in normal controller/router replay in the isolated app, without system GPS injection. */
@RunWith(AndroidJUnit4::class)
class UpcomingSpeedLimitControllerReplayInstrumentedTest {
    @Test fun realFullBundleFlowsThroughNormalControllerAndReference() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        assumeTrue(InstrumentationRegistry.getArguments().getString("offline_controller_replay")=="true")
        val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        val active=JSONObject(File(context.filesDir,"bundle/active_bundle.json").readText())
        assertEquals("2026-10-23-v1.5-lookahead",active.getString("bundle_version"))
        assertEquals(3099021312L,File(active.getString("db_path")).length())
        val cases=JSONObject(File(context.cacheDir,"upcoming-physical-cases.json").readText()).getJSONArray("cases")
        val preferences=context.getSharedPreferences("upcoming-offline-controller-replay",Context.MODE_PRIVATE)
        preferences.edit().clear().putBoolean(OnboardingPolicy.COMPLETED_KEY,true)
            .putBoolean("youspeed.audio_alerts_enabled",false).putBoolean("youspeed.traffic_sign_recognition_enabled",false)
            .putBoolean("youspeed.hide_welcome_screen",true).putBoolean("youspeed.panoramax.capture_enabled",false).commit()
        lateinit var controller: ConsumerSessionController
        instrumentation.runOnMainSync {
            controller=ConsumerSessionController(context,File(context.filesDir,"bundle"),preferences,Clock.systemUTC(),null)
            controller.setApplicationActive(true)
        }
        val rows=JSONArray()
        val outcomes=JSONArray()
        val started=SystemClock.elapsedRealtime()
        try {
            while(SystemClock.elapsedRealtime()-started<120_000) {
                var ready=false
                instrumentation.runOnMainSync {
                    controller.keepStartupLogs()
                    ready=controller.uiState.startupDataState==StartupDataState.READY
                }
                if(ready) break
                Thread.sleep(100)
            }
            assertEquals("Normal offline startup must finish",StartupDataState.READY,controller.uiState.startupDataState)
            assertEquals("Normal startup must open the new version",active.getString("db_path"),controller.uiState.activeDBPath)
            for(index in listOf(2,4,3)) {
                val c=cases.getJSONObject(index)
                var visible=0
                var rawTarget=0
                instrumentation.runOnMainSync {
                    controller.startDriving()
                    // Only this isolated replay uses direct listener dispatch. Never alter a system provider.
                    method("stopLocationUpdates").invoke(controller)
                }
                for(round in 0 until 18) {
                    instrumentation.runOnMainSync {
                        val location=Location("gps").apply {
                            latitude=c.getDouble("lat");longitude=c.getDouble("lon")
                            time=System.currentTimeMillis();elapsedRealtimeNanos=SystemClock.elapsedRealtimeNanos()
                            accuracy=1f;speed=(60.0/3.6).toFloat();bearing=c.getDouble("headingDeg").toFloat();bearingAccuracyDegrees=1f
                        }
                        method("consumeLocation",Location::class.java).invoke(controller,location)
                    }
                    Thread.sleep(850)
                    instrumentation.runOnMainSync {
                        val state=controller.uiState
                        val reference=field("speedReference").get(controller) as SpeedReferenceRuntime
                        val tracker=field("upcomingSpeedLimitTracker").get(controller) as UpcomingSpeedLimitTracker
                        val latest=UpcomingSpeedLimitTracker::class.java.getDeclaredField("latest").apply { isAccessible=true }.get(tracker) as? UpcomingSpeedLimitSnapshot
                        val target=latest?.candidates?.firstOrNull { it.signID==c.getString("expectedSignID") }
                        if(target!=null) rawTarget++
                        if(state.upcomingSpeedLimit?.signID==c.getString("expectedSignID")) visible++
                        rows.put(JSONObject().put("case",c.getString("id")).put("round",round)
                            .put("dbPath",state.activeDBPath).put("bundleVersion",state.activeBundleVersion)
                            .put("mainKmh",state.speedLimitKmh ?: JSONObject.NULL).put("mainDisplayText",state.speedLimitDisplayText ?: JSONObject.NULL)
                            .put("source",state.effectiveSpeedLimitSource.toString()).put("mainCurrent",reference.output()?.current ?: false)
                            .put("contextPending",reference.contextPending()).put("wayID",state.limitWayId ?: JSONObject.NULL)
                            .put("candidateCount",latest?.candidates?.size ?: 0).put("rawTarget",target!=null)
                            .put("previewVisible",state.upcomingSpeedLimit!=null).put("visibleTarget",state.upcomingSpeedLimit?.signID==c.getString("expectedSignID"))
                            .put("pendingCameraKmh",state.trafficSignPendingSpeedKmh ?: JSONObject.NULL).put("endOverlay",state.isTrafficSignEndOverlayVisible)
                            .put("snapshotReason",latest?.reason ?: JSONObject.NULL).put("lastError",state.lastError))
                    }
                    Thread.sleep(150)
                }
                instrumentation.runOnMainSync { controller.stopDriving() }
                outcomes.put(JSONObject().put("case",c.getString("id")).put("visibleTargetFrames",visible).put("rawTargetFrames",rawTarget))
            }
        } finally {
            File(context.cacheDir,"upcoming-controller-replay-results.json").writeText(JSONObject()
                .put("format","youspeed.upcoming.normal-controller-replay.android.v1")
                .put("scope","Isolated emulator; unchanged production startup, regional routing, matcher, inventory resolver, governed reference, worker and UI state. Public source coordinates dispatched to the normal listener method at1Hz; no main/reference/snapshot stubs, no system GPS injection or real drive.")
                .put("device",android.os.Build.MODEL).put("versionCode",BuildConfig.VERSION_CODE).put("versionName",BuildConfig.VERSION_NAME)
                .put("rows",rows).put("outcomes",outcomes).toString(2))
            instrumentation.runOnMainSync { controller.dispose() }
        }
        for(i in 0 until 2) assertTrue("Lower target must become visible through the real controller: ${outcomes.getJSONObject(i)}",outcomes.getJSONObject(i).getInt("visibleTargetFrames")>0)
        assertEquals("An equal target stays hidden",0,outcomes.getJSONObject(2).getInt("visibleTargetFrames"))
    }
    private fun field(name:String)=ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible=true }
    private fun method(name:String,vararg types:Class<*>)=ConsumerSessionController::class.java.getDeclaredMethod(name,*types).apply { isAccessible=true }
}

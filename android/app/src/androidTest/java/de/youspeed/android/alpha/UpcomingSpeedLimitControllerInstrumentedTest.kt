package de.youspeed.android.alpha

import android.content.Context
import android.location.Location
import androidx.compose.runtime.MutableState
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UpcomingSpeedLimitControllerInstrumentedTest {
    @Test fun verifiedBundleRoadChangePublishesOnSecondFixAndRetiresOldCamera() {
        val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        instrumentation.runOnMainSync {
            val controller=ConsumerSessionController(context,File(context.cacheDir,"verified-road-controller"),context.getSharedPreferences("verified-road-controller",Context.MODE_PRIVATE),Clock.systemUTC(),launchScreenshotState=AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            try {
                val runtime=field("speedReference").get(controller) as SpeedReferenceRuntime;runtime.reset()
                val apply=ConsumerSessionController::class.java.getDeclaredMethod("applyActiveLocalSpeedCorrectionIfNeeded",SpeedLookupResult::class.java,Location::class.java).apply {isAccessible=true}
                val bundle=ConsumerSessionController::class.java.getDeclaredMethod("updateBundledSpeedReference",String::class.java,SpeedReferenceValue::class.java).apply {isAccessible=true}
                val at=System.currentTimeMillis()-2000
                fun fix(way:String,ref:String,t:Long) {
                    val location=Location("gps").apply {time=t;accuracy=4.7f;speed=10f;bearing=90f;bearingAccuracyDegrees=1f}
                    val candidate=MatcherCandidateTrace(1,way,1.0,1.0,null,10.0,"none","secondary",null,"road",ref,null,true,true,false,true)
                    apply.invoke(controller,lookup().copy(wayId=way,streetRef=ref,travelDirection=TrafficSignTravelDirection.FORWARD,candidateTraces=listOf(candidate)),location)
                    bundle.invoke(controller,"verified-road-map",SpeedReferenceValue("numeric",60))
                }
                fix("old","L 340",at);runtime.camera("old-road-camera",SpeedReferenceValue("numeric",100))
                val gate=field("trafficSignGeneration").get(controller) as TrafficSignWriteGate;val generation=gate.get()
                fix("new","L 564",at+1000);assertEquals(100,runtime.output()?.value?.kmh)
                fix("new","L 564",at+2000);assertEquals(60,runtime.output()?.baselineKmh)
                assertEquals("BUNDLE",runtime.output()?.state);assertTrue(gate.get()>generation)
                runtime.camera("old-road-camera",SpeedReferenceValue("numeric",100));assertEquals(60,runtime.output()?.baselineKmh)
            } finally {controller.dispose()}
        }
    }
    @Test fun turnaroundAcrossWaysClearsOldCameraAndAdvancesProducerGeneration() {
        val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        lateinit var controller:ConsumerSessionController
        lateinit var runtime:SpeedReferenceRuntime
        lateinit var apply:java.lang.reflect.Method
        fun fix(way:String,direction:TrafficSignTravelDirection) {
            val location=Location("gps").apply {time=System.currentTimeMillis();accuracy=3f;speed=10f;bearing=90f;bearingAccuracyDegrees=1f}
            apply.invoke(controller,lookup().copy(wayId=way,travelDirection=direction,streetRef="L 340",streetBaseName="turnaround-test",sourceRelationIds=setOf(10)),location)
            ConsumerSessionController::class.java.getDeclaredMethod("updateBundledSpeedReference",String::class.java,SpeedReferenceValue::class.java).apply {isAccessible=true}
                .invoke(controller,"turnaround-map",SpeedReferenceValue("numeric",60))
        }
        instrumentation.runOnMainSync {
            controller=ConsumerSessionController(context,File(context.cacheDir,"turnaround-controller"),context.getSharedPreferences("turnaround-controller",Context.MODE_PRIVATE),Clock.systemUTC(),launchScreenshotState=AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            runtime=field("speedReference").get(controller) as SpeedReferenceRuntime
            runtime.reset()
            apply=ConsumerSessionController::class.java.getDeclaredMethod("applyActiveLocalSpeedCorrectionIfNeeded",SpeedLookupResult::class.java,Location::class.java).apply {isAccessible=true}
            fix("723493085",TrafficSignTravelDirection.FORWARD)
            ConsumerSessionController::class.java.getDeclaredMethod("updateBundledSpeedReference",String::class.java,SpeedReferenceValue::class.java).apply {isAccessible=true}
                .invoke(controller,"turnaround-map",SpeedReferenceValue("numeric",60))
            runtime.camera("turnaround-old-camera",SpeedReferenceValue("numeric",100))
            fix("178845215",TrafficSignTravelDirection.FORWARD)
            fix("723493085",TrafficSignTravelDirection.REVERSE)
            assertEquals(100,runtime.output()?.value?.kmh)
        }
        val gate=field("trafficSignGeneration").get(controller) as TrafficSignWriteGate;val generation=gate.get()
        try {
            Thread.sleep(8100)
            instrumentation.runOnMainSync {
                fix("935939126",TrafficSignTravelDirection.REVERSE)
                assertEquals("${runtime.output()} reason=${runtime.lastEventReason}",60,runtime.output()?.value?.kmh)
                assertNotEquals(generation,gate.get())
                runtime.camera("turnaround-old-camera",SpeedReferenceValue("numeric",100))
                assertEquals(60,runtime.output()?.value?.kmh)
            }
        } finally {instrumentation.runOnMainSync {controller.dispose()}}
    }
    @Test fun cameraTownPassageControlsLocalityDefaultsAndKeepsExplicitNumericLimit() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost") || InstrumentationRegistry.getArguments().getString("driver_ui_validation")=="true")
        instrumentation.runOnMainSync {
            val controller=ConsumerSessionController(context,File(context.cacheDir,"camera-town-locality"),
                context.getSharedPreferences("camera-town-locality",Context.MODE_PRIVATE),Clock.systemUTC(),
                launchScreenshotState=AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            try {
                val latch=field("cameraTownLocality").get(controller) as CameraTownLocalityLatch
                val at=java.time.Instant.now()
                val location=Location("gps").apply { time=at.toEpochMilli(); latitude=48.0; longitude=8.0 }
                val apply=ConsumerSessionController::class.java.getDeclaredMethod("applyCameraTownLocality",
                    SpeedLookupResult::class.java,Location::class.java,String::class.java).apply { isAccessible=true }
                fun contextual(result: SpeedLookupResult)=apply.invoke(controller,result,location,"DE") as SpeedLookupResult
                latch.observe(true,at,"DE")
                val rural=lookup().copy(speedSource=DerivedSpeedSource.HIGHWAY_CLASS)
                assertEquals(true,contextual(rural).insideCity)
                assertEquals(50,contextual(rural).speedLimitKmh)
                // Ordinary refreshed map context cannot revoke a physical crossing.
                assertEquals(true,contextual(rural.copy(wayId="2")).insideCity)
                latch.observe(false,at.plusSeconds(1),"DE")
                val residential=rural.copy(highway="residential",insideCity=true,speedLimitKmh=50,
                    citySource="settlement:highway_residential:high")
                assertEquals(false,contextual(residential).insideCity)
                assertEquals(100,contextual(residential).speedLimitKmh)
                assertEquals(70,contextual(residential.copy(speedSource=DerivedSpeedSource.EXPLICIT_TAG,speedLimitKmh=70)).speedLimitKmh)
                val motorway=contextual(rural.copy(highway="motorway"))
                assertTrue(motorway.isUnlimitedSpeedLimit)
                val base=ConsumerSessionController::class.java.getDeclaredMethod("trafficSignBaseLimit",String::class.java,
                    String::class.java,SpeedLookupResult::class.java,String::class.java,Integer::class.java,java.lang.Boolean.TYPE)
                    .apply { isAccessible=true }.invoke(controller,null,null,motorway,"DE",null,false) as TrafficSignBaseLimit
                assertEquals(TrafficSignResolvedLimitKind.UNLIMITED,base.resolution?.kind)
                // A newer accepted physical town boundary establishes the next context.
                location.time=at.plusSeconds(2).toEpochMilli()
                val crossed=contextual(residential.copy(inventoryBoundaryEvent="city_entry",inventoryBoundarySignId="town-entry"))
                assertNull(latch.insideCity)
                assertEquals(true,crossed.insideCity)
                assertEquals(50,crossed.speedLimitKmh)
            } finally { controller.dispose() }
        }
    }
    @Test fun scheduledExpiryClearsPreviewWithoutAnotherLocationOrPolicyTransition() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost") || InstrumentationRegistry.getArguments().getString("driver_ui_validation")=="true")
        val testClock=object: Clock() {
            var skewMs=0L
            override fun getZone(): java.time.ZoneId=java.time.ZoneOffset.UTC
            override fun withZone(zone: java.time.ZoneId): Clock=this
            override fun instant(): java.time.Instant=java.time.Instant.ofEpochMilli(millis())
            override fun millis(): Long=System.currentTimeMillis()+skewMs
        }
        lateinit var controller: ConsumerSessionController
        instrumentation.runOnMainSync {
            controller=ConsumerSessionController(context,File(context.cacheDir,"upcoming-timer"),
                context.getSharedPreferences("upcoming-timer",Context.MODE_PRIVATE),testClock,
                launchScreenshotState=AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            field("isDriving").setBoolean(controller,true)
            val reference=field("speedReference").get(controller) as SpeedReferenceRuntime
            reference.context("1","road",setOf("10"),"forward",true)
            reference.bundle("base",SpeedReferenceValue("numeric",100))
            val at=System.currentTimeMillis()
            val snapshot=UpcomingSpeedLimitSnapshot("1",1,100.0,setOf(10),
                listOf(UpcomingSpeedLimitPath(null,"1",1,0.0,500.0,-100.0,setOf(10))),
                listOf(UpcomingSpeedLimitCandidate("target","source","snapshot","rule","1",1,200.0,20,100.0)),"test")
            val result=lookup().copy(upcomingSpeedLimits=snapshot)
            ConsumerSessionController::class.java.getDeclaredMethod("consumeUpcomingSpeedLimit",SpeedLookupResult::class.java,
                String::class.java,Location::class.java,java.lang.Long.TYPE).apply { isAccessible=true }.invoke(controller,result,
                "/tmp/screenshot-fixture.sqlite|screenshot-fixture|snapshot",Location("gps").apply { time=at },field("upcomingSpeedLimitEpoch").getLong(controller))
            refresh(controller)
            assertEquals("target",controller.uiState.upcomingSpeedLimit?.signID)
            assertEquals(100,reference.output()?.value?.kmh)
        }
        try {
            Thread.sleep(3200)
            instrumentation.runOnMainSync {
                assertNull("The scheduled main-thread timer clears presentation",controller.uiState.upcomingSpeedLimit)
                testClock.skewMs=-2000
                refresh(controller)
                assertNull("A clock adjustment cannot resurrect the expired snapshot",controller.uiState.upcomingSpeedLimit)
                assertEquals("Preview expiry does not modify the main reference",100,(field("speedReference").get(controller) as SpeedReferenceRuntime).output()?.value?.kmh)
            }
        } finally { instrumentation.runOnMainSync { controller.dispose() } }
    }
    private fun field(name: String)=ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible=true }
    private fun refresh(controller: ConsumerSessionController) {
        ConsumerSessionController::class.java.getDeclaredMethod("updateState",kotlin.jvm.functions.Function1::class.java)
            .apply { isAccessible=true }.invoke(controller,{ state: ConsumerUiState -> state })
    }
    private fun lookup()=SpeedLookupResult(wayId="1",highway="primary",streetName="road",streetBaseName="road",streetRef=null,
        speedLimitKmh=100,isUnlimitedSpeedLimit=false,cityName=null,cityPlaceName=null,cityDistrictName=null,insideCity=false,citySource=null,
        queryTimeMs=0.0,candidateCount=1,speedCandidateCount=1,candidateTraces=emptyList(),nearestCandidateDistanceM=0.0,nearestSpeedCandidateDistanceM=0.0,
        isTunnelSegment=false,matchedEndpointProximityM=null,streetRefTokens=emptyList(),nearbyTunnelCandidateWayIds=emptySet(),nearbyTunnelCandidateRefs=emptySet(),
        portalEligibleTunnelWayIds=emptySet(),portalEligibleTunnelRefs=emptySet(),activeCorridorState=null,approachCorridorStateCandidate=null,usedWalkingTurnSwitch=false,
        usedMiniHMM=false,miniHMMCandidateCount=0,matchHypotheses=emptyList(),selectionTrace=emptyList())
}

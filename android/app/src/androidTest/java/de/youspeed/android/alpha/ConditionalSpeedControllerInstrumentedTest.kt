package de.youspeed.android.alpha

import android.content.Context
import androidx.compose.runtime.MutableState
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.UUID

/** Executes the actual controller admission and minute refresh, not just the rule parser. */
class ConditionalSpeedControllerInstrumentedTest {
    @Test fun numericOsmBaseCanBecomeUnlimitedAcrossClockBoundaryAndRepeatedFixes() {
        val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        val clock=object:Clock() {
            var at=Instant.parse("2026-10-23T16:59:00Z").toEpochMilli()
            override fun millis()=at
            override fun instant()=Instant.ofEpochMilli(at)
            override fun getZone():ZoneId=ZoneOffset.UTC
            override fun withZone(zone:ZoneId):Clock=this
        }
        val cases=JSONObject(context.assets.open("conditional-speed-rules/conformance-v1.json").bufferedReader().use {it.readText()}).getJSONArray("cases")
        val fixture=(0 until cases.length()).map {cases.getJSONObject(it)}.single {it.optString("id")=="night-unlimited"}
        val rules=fixture.getJSONObject("rules")
        val conditional=rules.getJSONArray("tags").getJSONObject(1)
        conditional.put("raw","none @ (19:00-06:00)")
        conditional.getJSONArray("clauses").getJSONObject(0).getJSONObject("condition").put("windows",JSONArray().put(JSONArray().put(1140).put(360)))
        val rule=ConditionalSpeedRules.Reevaluation(rules.toString(),120,false,1,"DEU")
        val root=File(context.cacheDir,"conditional-controller-${UUID.randomUUID()}").apply {mkdirs()}
        val preference="conditional-controller-${UUID.randomUUID()}"
        lateinit var controller:ConsumerSessionController
        instrumentation.runOnMainSync {
            controller=ConsumerSessionController(context,root,context.getSharedPreferences(preference,Context.MODE_PRIVATE),clock,launchScreenshotState=AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            field("isDriving").setBoolean(controller,true)
        }
        try {
            instrumentation.runOnMainSync {
                val result=lookup().copy(conditionalRuleContext=rule,speedSource=DerivedSpeedSource.EXPLICIT_TAG)
                assertEquals(120,base(controller,result,"DEU").resolution?.speedKmh)
                clock.at=Instant.parse("2026-10-23T17:00:00Z").toEpochMilli()
                val evaluated=rule.evaluate(clock.at);assertTrue(evaluated.unlimited)
                val night=result.copy(speedLimitKmh=evaluated.kmh,isUnlimitedSpeedLimit=evaluated.unlimited)
                repeat(3) {assertEquals(TrafficSignResolvedLimitKind.UNLIMITED,base(controller,night,"DEU").resolution?.kind)}
                assertNull("German conditional none must not authorize unlimited in another country",base(controller,night,"FRA").resolution)
                val reference=field("speedReference").get(controller) as SpeedReferenceRuntime
                reference.reset();reference.context("1","road",setOf("10"),"forward",true);reference.bundle("base",SpeedReferenceValue("numeric",120))
                @Suppress("UNCHECKED_CAST") val state=field("uiState\$delegate").get(controller) as MutableState<ConsumerUiState>
                state.value=state.value.copy(activeDBPath="/fixture/conditional.sqlite",limitWayId="1",activeBundleVersion="fixture")
                val nested=ConsumerSessionController::class.java.declaredClasses.single {it.simpleName=="ConditionalClockContext"}
                val constructor=nested.declaredConstructors.single().apply {isAccessible=true}
                val generation=(field("trafficSignGeneration").get(controller) as TrafficSignWriteGate).get()
                field("conditionalClockContext").set(controller,constructor.newInstance(rule,"1","/fixture/conditional.sqlite",generation))
                field("conditionalClockMinute").set(controller,null)
                val tick=ConsumerSessionController::class.java.getDeclaredMethod("reevaluateConditionalClock").apply {isAccessible=true}
                tick.invoke(controller)
                assertEquals("unlimited",reference.output()?.value?.kind)
                clock.at=Instant.parse("2026-10-24T04:00:00Z").toEpochMilli();tick.invoke(controller)
                assertEquals(120,reference.output()?.value?.kmh)
            }
        } finally {instrumentation.runOnMainSync {controller.dispose()};context.deleteSharedPreferences(preference);root.deleteRecursively()}
    }
    private fun field(name:String)=ConsumerSessionController::class.java.getDeclaredField(name).apply {isAccessible=true}
    private fun base(controller:ConsumerSessionController,result:SpeedLookupResult,country:String)=ConsumerSessionController::class.java.getDeclaredMethod("trafficSignBaseLimit",String::class.java,String::class.java,SpeedLookupResult::class.java,String::class.java,Int::class.javaObjectType,Boolean::class.javaPrimitiveType).apply {isAccessible=true}.invoke(controller,null,null,result,country,null,false) as TrafficSignBaseLimit
    private fun lookup()=SpeedLookupResult(wayId="1",highway="motorway",streetName="road",streetBaseName="road",streetRef=null,
        speedLimitKmh=120,isUnlimitedSpeedLimit=false,cityName=null,cityPlaceName=null,cityDistrictName=null,insideCity=false,citySource=null,
        queryTimeMs=0.0,candidateCount=1,speedCandidateCount=1,candidateTraces=emptyList(),nearestCandidateDistanceM=0.0,nearestSpeedCandidateDistanceM=0.0,
        isTunnelSegment=false,matchedEndpointProximityM=null,streetRefTokens=emptyList(),nearbyTunnelCandidateWayIds=emptySet(),nearbyTunnelCandidateRefs=emptySet(),
        portalEligibleTunnelWayIds=emptySet(),portalEligibleTunnelRefs=emptySet(),activeCorridorState=null,approachCorridorStateCandidate=null,usedWalkingTurnSwitch=false,
        usedMiniHMM=false,miniHMMCandidateCount=0,matchHypotheses=emptyList(),selectionTrace=emptyList())
}

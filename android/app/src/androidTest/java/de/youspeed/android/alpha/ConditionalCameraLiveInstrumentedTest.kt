package de.youspeed.android.alpha

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.RectF
import androidx.compose.runtime.MutableState
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

/** Real bundled detector/OCR pixels are separate from the synthetic road/clock replay below. */
class ConditionalCameraLiveInstrumentedTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private val positive="fbc95839-71fc-540c-ae6b-041df195e07d"
    private fun source(id:String)=instrumentation.context.assets.open("tsr-ocr-32/$id.png").use {requireNotNull(BitmapFactory.decodeStream(it))}
    private fun read(bitmap:Bitmap,candidate:TrafficSignCandidate,parent:String,frame:String,at:Instant,generation:Long,session:String,
        content:TrafficSignSupplementaryPixelRect=TrafficSignSupplementaryPixelRect(0,0,bitmap.width,bitmap.height),otherPrimaries:List<NormalizedTrafficSignBoundingBox> = emptyList()):TrafficSignSupplementaryTextAnnotation {
        val done=CountDownLatch(1);var annotation:TrafficSignSupplementaryTextAnnotation?=null
        val request=TrafficSignSupplementaryOCRRequest(candidate,parent,frame,at,at,TrafficSignSupplementaryScope(generation,session),otherPrimaryBoxes=otherPrimaries)
        AndroidTrafficSignSupplementaryOCR.fromBitmap(bitmap,content).recognize(request) {annotation=it;done.countDown()}
        assertTrue("Bundled OCR must finish",done.await(30,TimeUnit.SECONDS))
        return requireNotNull(annotation)
    }
    @Test fun nativeCroppedParentsKeepAbstainingWhenActualDetectorGeometryOverlapsTheirPanels() {
        check(context.packageName.endsWith(".testhost"))
        val warm=CountDownLatch(1);AndroidTrafficSignSupplementaryOCR.warmUp(context) {warm.countDown()}
        assertTrue(warm.await(30,TimeUnit.SECONDS));assertTrue(AndroidTrafficSignSupplementaryOCR.ready)
        val pack=AndroidTrafficSignModelPackLoader.load(context)
        AndroidLiteRtTrafficSignInferenceEngine(pack).use {engine ->
            for(id in listOf("7c735ee1-bbd7-5ab4-b969-f4fd9ac40b8b",positive)) {
                val photo=source(id)
                // Preserve each real source pixel exactly, adding scene margin for the detector
                // rather than asking it to interpret an already tightly cut parent as a full frame.
                val bitmap=Bitmap.createBitmap(512,768,Bitmap.Config.ARGB_8888).apply {
                    eraseColor(Color.rgb(114,114,114));Canvas(this).drawBitmap(photo,(512-photo.width)/2f,30f,null)
                }
                photo.recycle()
                try {
                    val detection=engine.recognizeAllWithDiagnostics(bitmap).detections.filter {it.candidate.rawClassId=="maxspeed:30"}.maxByOrNull {it.candidate.rawScore}
                    assertNotNull("Actual model must recognize the real 30 sign $id",detection)
                    val candidate=requireNotNull(detection).candidate
                    val at=Instant.parse("2026-10-23T03:59:58Z")
                    val native=AndroidTrafficSignDetectorInput.nativeWindow(bitmap)
                    val content=AndroidTrafficSignDetectorInput.nativeContentRect(bitmap)
                    val first:TrafficSignSupplementaryTextAnnotation
                    val second:TrafficSignSupplementaryTextAnnotation
                    try {
                        first=read(native,candidate,"native-$id","native-$id-1",at,1,"native",content)
                        second=read(native,candidate,"native-$id","native-$id-2",at.plusMillis(400),1,"native",content)
                    } finally {native.recycle()}
                    assertEquals("Native proof $id box=${candidate.boundingBox} status=${first.status} decision=${first.qualityDecision} raw=${first.rawText}",bitmap.height,first.assemblyEvidence?.sourceWidth)
                    assertEquals(content,first.assemblyEvidence?.sourceContentRect)
                    for(annotation in listOf(first,second)) {
                        assertEquals("$id ${annotation.rawText} ${annotation.qualityDecision}",TrafficSignSupplementaryOCRStatus.READ,annotation.status)
                        assertEquals(ConditionalOCRInterpretation.Condition.Schedule(emptyList(),1320,360),ConditionalOCRInterpretation.parse(annotation.rawText.orEmpty())?.condition)
                        assertEquals("Actual expanded parent/plate overlap remains unresolved",TrafficSignConditionalAssemblyEvidence.Kind.UNRESOLVED,
                            annotation.assemblyEvidence?.validate(annotation.primaryBoundingBox,annotation.rawText)?.kind)
                    }
                    val tracker=ConditionalOCRInterpretation.Tracker()
                    fun observation(a:TrafficSignSupplementaryTextAnnotation)=ConditionalOCRInterpretation.Observation(a.physicalSignId,a.physicalSignId,a.primaryClassId,30,
                        a.assemblyEvidence!!.plateRects.indices.map {"plate-$it"},a.frameId,a.rawText.orEmpty(),a.sourceObservedAt,at,0.0,"DE","native",1,
                        pack.modelPack.packId,pack.detectorArtifact.sha256,assemblyEvidence=a.assemblyEvidence)
                    assertEquals(ConditionalOCRInterpretation.Verification.CANDIDATE,tracker.consume(observation(first)).verification)
                    assertEquals(ConditionalOCRInterpretation.Verification.CANDIDATE,tracker.consume(observation(second)).verification)
                } finally {bitmap.recycle()}
            }
            val clipped=source("7444ffc9-d750-5b2b-bf8e-a39951ad9f6a")
            try {
                val detections=engine.recognizeAllWithDiagnostics(clipped).detections.filter {it.candidate.numericSupplementarySpeed()!=null}
                assertTrue("Negative source contains actual numeric parents",detections.isNotEmpty())
                for((i,detection) in detections.withIndex()) {
                    val native=AndroidTrafficSignDetectorInput.nativeWindow(clipped)
                    val annotation=try {read(native,detection.candidate,"clipped-$i","clipped-$i",Instant.now(),1,"negative",AndroidTrafficSignDetectorInput.nativeContentRect(clipped))} finally {native.recycle()}
                    assertNotEquals(TrafficSignConditionalAssemblyEvidence.Kind.CONDITIONAL,
                        annotation.assemblyEvidence?.validate(annotation.primaryBoundingBox,annotation.rawText)?.kind)
                }
            } finally {clipped.recycle()}
        }
    }

    @Test fun originalFullScenesUseActualDetectorAndOriginalPixelGeometry() {
        val rows=org.json.JSONArray();var complete=0
        AndroidLiteRtTrafficSignInferenceEngine(AndroidTrafficSignModelPackLoader.load(context)).use {engine ->
            for(id in listOf("baa81e7c-8bfc-49d0-bca5-f39c1dfe21cc","0c6575e7-36c3-4468-a6d0-e709485176df")) {
                val bitmap=instrumentation.context.assets.open("tsr-ocr-32/source-scenes/$id.jpg").use {requireNotNull(BitmapFactory.decodeStream(it))}
                try {
                    assertEquals(4224,bitmap.width);assertEquals(2376,bitmap.height)
                    val detections=engine.recognizeAllWithDiagnostics(bitmap).detections
                    val numeric=detections.filter {it.candidate.rawClassId=="maxspeed:30"}
                    assertTrue("Actual full scene must detect numeric parent $id",numeric.isNotEmpty())
                    val native=AndroidTrafficSignDetectorInput.nativeWindow(bitmap)
                    try {
                        for((index,detection) in numeric.withIndex()) {
                            val at=Instant.parse("2026-10-23T03:59:58Z")
                            val others=detections.map {it.candidate.boundingBox}.filter {it!=detection.candidate.boundingBox}
                            val first=read(native,detection.candidate,"natural-$id-$index","natural-$id-$index-1",at,1,"natural",AndroidTrafficSignDetectorInput.nativeContentRect(bitmap),others)
                            val second=read(native,detection.candidate,"natural-$id-$index","natural-$id-$index-2",at.plusMillis(400),1,"natural",AndroidTrafficSignDetectorInput.nativeContentRect(bitmap),others)
                            val verdict=second.assemblyEvidence?.validate(second.primaryBoundingBox,second.rawText)
                            rows.put(org.json.JSONObject().put("source",id).put("raw",second.rawText).put("decision",second.qualityDecision).put("box",second.primaryBoundingBox.toString())
                                .put("validation",verdict.toString()).put("native_width",second.assemblyEvidence?.sourceWidth).put("native_height",second.assemblyEvidence?.sourceHeight))
                            if(verdict?.kind==TrafficSignConditionalAssemblyEvidence.Kind.CONDITIONAL) {
                                complete++
                                val tracker=ConditionalOCRInterpretation.Tracker()
                                fun observation(a:TrafficSignSupplementaryTextAnnotation)=ConditionalOCRInterpretation.Observation(a.physicalSignId,a.physicalSignId,a.primaryClassId,30,
                                    a.assemblyEvidence!!.plateRects.indices.map {"panel-$it"},a.frameId,a.rawText.orEmpty(),a.sourceObservedAt,at,0.0,"DE","natural",1,
                                    "actual-native-detector","actual-bundled-ocr",assemblyEvidence=a.assemblyEvidence)
                                tracker.consume(observation(first))
                                assertEquals(ConditionalOCRInterpretation.Verification.VERIFIED,tracker.consume(observation(second)).verification)
                            }
                        }
                    } finally {native.recycle()}
                } finally {bitmap.recycle()}
            }
        }
        File(context.filesDir,"conditional-natural-results.json").writeText(rows.toString(2))
        assertTrue("At least one original full scene must produce complete native-pixel proof: $rows",complete>0)
    }

    @Test fun actualControllerEvaluatesClockWithOriginalOriginsPriorityAndNoBareReinstatement() {
        Fixture().use {fixture ->
            val pack=AndroidTrafficSignModelPackLoader.load(context)
            AndroidLiteRtTrafficSignInferenceEngine(pack).use {engine ->
                val original=source(positive)
                try {
                    feedApproach(fixture,pack,engine,original,"clock-parent")
                    assertEquals(fixture.dump(),30,fixture.runtime.output()?.value?.kmh)
                    val origin=fixture.runtime.ordinaryCameraOrigin();assertNotNull(origin)
                    fixture.main {
                        fixture.clock.set(Instant.parse("2026-10-23T04:00:00Z"));fixture.elapsed=2.0;fixture.reevaluate()
                        assertEquals("government:BW",fixture.runtime.output()?.evidenceId);assertEquals(50,fixture.runtime.output()?.value?.kmh)
                        // A bounded wall-clock correction exercises same-ID reactivation/withdrawal twice.
                        fixture.clock.set(Instant.parse("2026-10-23T03:59:59.800Z"));fixture.elapsed=3.0;fixture.reevaluate()
                        assertEquals(30,fixture.runtime.output()?.value?.kmh);assertEquals(origin,fixture.runtime.ordinaryCameraOrigin())
                        fixture.clock.set(Instant.parse("2026-10-23T04:00:01Z"));fixture.elapsed=4.0;fixture.reevaluate()
                        assertEquals(50,fixture.runtime.output()?.value?.kmh)
                        fixture.clock.set(Instant.parse("2026-10-23T03:59:59.800Z"));fixture.elapsed=5.0;fixture.reevaluate()
                        assertEquals(30,fixture.runtime.output()?.value?.kmh)
                        val changed=fixture.roadContext.copy(sourceSignature=TrafficSignRuntimeSourceSignature("bundle|way:101|maxspeed:70",null))
                        field("latestTrafficSignContext").set(fixture.controller,changed)
                        fixture.bundle("osm-clock",70);fixture.reevaluate()
                        assertEquals("Computed OSM scalar changes cannot invalidate a proven same-road camera condition",30,fixture.runtime.output()?.value?.kmh)
                        fixture.runtime.voice("own",SpeedReferenceValue("numeric",80));fixture.reevaluate()
                        assertEquals("voice",fixture.runtime.output()?.source);assertEquals(80,fixture.runtime.output()?.value?.kmh)
                        fixture.runtime.boundary("applicable_end");fixture.bundle("osm",50);fixture.reevaluate()
                        assertEquals("Clock alone cannot revive camera evidence suppressed by own correction",50,fixture.runtime.output()?.value?.kmh)
                    }
                } finally {original.recycle()}
            }
        }
    }

    @Test fun missingLaneAndOppositeFaceDecisionsCannotBorrowGoodOcrProof() {
        val pack=AndroidTrafficSignModelPackLoader.load(context)
        AndroidLiteRtTrafficSignInferenceEngine(pack).use {engine ->
            val original=source(positive)
            try {for(kind in listOf("missing","lane","opposite_face")) Fixture().use {fixture ->
                feedApproach(fixture,pack,engine,original,"veto-$kind") {decision ->
                    if(kind=="missing") null else decision.copy(classification="UNKNOWN",immediateEligible=false,passageEligible=false,
                        reasons=listOf(if(kind=="lane") TSRLiveSignAdmission.sideRoadReason else "opposite_face"))
                }
                assertEquals("Good pixels do not override missing/negative road admission: $kind",50,fixture.runtime.output()?.value?.kmh)
                assertFalse(fixture.runtime.cameraEvidenceIds().contains("veto-$kind"))
            }} finally {original.recycle()}
        }
    }

    @Test fun initiallyInactiveOldConditionNeverSupersedesNewCameraAndRetainsIndependentZone() {
        val pack=AndroidTrafficSignModelPackLoader.load(context)
        AndroidLiteRtTrafficSignInferenceEngine(pack).use {engine ->
            val original=source(positive)
            try {
                Fixture().use {fixture ->
                    fixture.clock.set(Instant.parse("2026-10-23T19:59:58Z"))
                    feedApproach(fixture,pack,engine,original,"old-inactive")
                    assertEquals(50,fixture.runtime.output()?.value?.kmh)
                    fixture.main {
                        fixture.elapsed=2.0;fixture.runtime.camera("newer-independent-camera",SpeedReferenceValue("numeric",80))
                        fixture.clock.set(Instant.parse("2026-10-23T20:00:00Z"));fixture.elapsed=3.0;fixture.reevaluate()
                        assertEquals("An old never-offered condition must not revive over a newer physical camera claim",80,fixture.runtime.output()?.value?.kmh)
                        assertEquals("newer-independent-camera",fixture.runtime.output()?.evidenceId)
                    }
                }
                Fixture().use {fixture ->
                    fixture.main {fixture.runtime.camera("independent-zone",SpeedReferenceValue("numeric",30),enclosing=true)}
                    feedApproach(fixture,pack,engine,original,"zone-conditional")
                    assertEquals(fixture.dump(),"zone-conditional",fixture.runtime.output()?.evidenceId)
                    fixture.main {
                        fixture.clock.set(Instant.parse("2026-10-23T04:00:00Z"));fixture.elapsed=2.0;fixture.reevaluate()
                        assertEquals("independent-zone",fixture.runtime.output()?.evidenceId)
                        fixture.clock.set(Instant.parse("2026-10-23T03:59:59.800Z"));fixture.elapsed=3.0;fixture.reevaluate()
                        assertEquals("zone-conditional",fixture.runtime.output()?.evidenceId)
                        fixture.clock.set(Instant.parse("2026-10-23T04:00:01Z"));fixture.elapsed=4.0;fixture.reevaluate()
                        assertEquals("independent-zone",fixture.runtime.output()?.evidenceId)
                    }
                }
            } finally {original.recycle()}
        }
    }

    private fun feedApproach(fixture:Fixture,pack:AndroidTrafficSignVerifiedPack,engine:AndroidLiteRtTrafficSignInferenceEngine,
        original:Bitmap,parent:String,decisionTransform:(TSRApplicabilityDecision)->TSRApplicabilityDecision?={it}) {
                    val fusion=TrafficSignFusionEngine(pack.modelPack.thresholds,pack.modelPack.calibration.runtimeOutput,
                        pack.modelPack.classMapping.associate {it.classId to it.threshold})
                    val samples=mutableListOf<TSRTrackSample>()
                    val start=fixture.clock.instant()
                    for(index in 0..3) {
                        val frame="actual-clock-$index";val at=start.plusMillis(index*400L)
                        // Independent replay inputs use real photograph pixels at successive approach scales.
                        val bitmap=Bitmap.createBitmap(512,768,Bitmap.Config.ARGB_8888).apply {eraseColor(Color.rgb(114,114,114))}
                        try {
                            val scale=1.6f+index*.2f;val w=original.width*scale;val h=original.height*scale
                            Canvas(bitmap).drawBitmap(original,null,RectF((512-w)/2,30f,(512+w)/2,30+h),null)
                            val detection=engine.recognizeAllWithDiagnostics(bitmap).detections.filter {it.candidate.rawClassId=="maxspeed:30"}.maxByOrNull {it.candidate.rawScore}
                            assertNotNull("Real model must recognize replay frame $index",detection)
                            val fused=fusion.observe(requireNotNull(detection),index*400L,parent)
                            val candidate=requireNotNull(fused.candidate)
                            val box=candidate.boundingBox;val scope=fixture.scope
                            val sample=TSRTrackSample(frame,at.toEpochMilli().toDouble(),TSRApplicabilityCandidate("$frame:0","maximum_speed:30:km/h",
                                TSRApplicabilityBox(box.x,box.y,box.width,box.height),candidate.rawScore,true,null))
                            samples+=sample
                            val road=fixture.road(frame,at)
                            val batch=TSRFrameCandidateBatch(1,frame,at.toEpochMilli().toDouble(),scope,"analyzed",listOf(sample.candidate),false,1,pack.modelPack.packId,pack.modelPack.preprocessing.version,road,"DE")
                            val decision=TSRApplicabilityPolicy.evaluate(TSRPhysicalTrackSnapshot(parent,scope,samples.toList(),"observed",false),batch)
                            fixture.clock.set(at);fixture.elapsed=index*.4
                            val event=TrafficSignRecognitionEvent(1,pack.modelPack.packId,pack.detectorArtifact.sha256,pack.modelPack.preprocessing.version,
                                TrafficSignInputSource.LIVE_FRAME,at,fused.state,candidate,fixture.roadContext,0.0,"nominal",frame,fixture.session,applicabilityDecision=decisionTransform(decision))
                            if(index>=2) {
                                assertEquals("Replay must pass real fusion confirmation",TrafficSignRecognitionState.CONFIRMED,event.state)
                                assertTrue("Replay must enable the actual runtime",fixture.controller.isTrafficSignRecognitionRuntimeEnabled())
                            }
                            fixture.main {fixture.controller.onTrafficSignUnverifiedAssembly(event,fixture.generation)}
                            if(index>0) {
                                assertEquals("Actual applicability engine must prove ego approach", "LIKELY_EGO_CORRIDOR",decision.classification)
                                val native=AndroidTrafficSignDetectorInput.nativeWindow(bitmap)
                                val annotation=try {read(native,candidate,parent,frame,at,fixture.generation,fixture.session,AndroidTrafficSignDetectorInput.nativeContentRect(bitmap))} finally {native.recycle()}
                                assertEquals("Actual live replay pixels must yield a complete read",TrafficSignConditionalAssemblyEvidence.Kind.CONDITIONAL,
                                    annotation.assemblyEvidence?.validate(box,annotation.rawText)?.kind)
                                fixture.main {fixture.controller.onTrafficSignSupplementaryAuthority(event,annotation)}
                            }
                        } finally {bitmap.recycle()}
                    }
    }

    private inner class Fixture:AutoCloseable {
        val session="live-condition-${UUID.randomUUID()}";val root=File(context.cacheDir,session).apply {mkdirs()}
        val clock=MutableClock(Instant.parse("2026-10-23T03:59:58Z"));var elapsed=0.0
        lateinit var controller:ConsumerSessionController;lateinit var runtime:SpeedReferenceRuntime
        val generation:Long get()=(field("trafficSignGeneration").get(controller) as TrafficSignWriteGate).get()
        val roadContext=TrafficSignDetectionContext("101",48.0,8.0,0.0,TrafficSignTravelDirection.FORWARD,
            TrafficSignRuntimeSourceSignature("bundle|way:101|maxspeed:50",null),"a".repeat(64),"DE",matchedWayStable=true,roadIdentity="road")
        val scope get()=TSRApplicabilityScope(session,"a".repeat(64),"camera",1,generation,0)
        init {main {
            controller=ConsumerSessionController(context,root,context.getSharedPreferences(session,Context.MODE_PRIVATE),clock,AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            field("isDriving").setBoolean(controller,true);field("trafficSignDriveSessionId").set(controller,session)
            field("cameraTSRDaylightAllowed").setBoolean(controller,true);field("latestTrafficSignContext").set(controller,roadContext)
            @Suppress("UNCHECKED_CAST") val state=field("uiState\$delegate").get(controller) as MutableState<ConsumerUiState>
            state.value=state.value.copy(appScreenshotState=null,onboardingCompleted=true,startupDataState=StartupDataState.READY,
                startupLogReviewState=StartupLogReviewState.COMPLETE,trafficSignRecognitionEnabled=true,trafficSignRecognitionIndependentEnabled=true,
                downloadedBundleLatestVersionByRegion=mapOf("replay-road-fixture" to "conditional-replay-v1"))
            val model=SpeedLimitReferenceModel.load {name->context.assets.open("${SpeedLimitReferenceModel.DIRECTORY}/$name").use {it.readBytes()}}
            runtime=SpeedReferenceRuntime(model) {elapsed};field("speedReference").set(controller,runtime)
            runtime.context("101","road",emptySet(),"forward",true);bundle("government:BW",50)
        }}
        fun road(frame:String,at:Instant)=TrafficSignMapContextSnapshot("road-$frame",at.toEpochMilli().toDouble(),scope,"101",3.0,3.0,0.0,0.0,true,
            "residential",emptyList(),emptyList(),listOf("endpoint_links","local_tangent"),60.0,0.0)
        fun main(body:()->Unit)=instrumentation.runOnMainSync(body)
        fun bundle(id:String,value:Int)=ConsumerSessionController::class.java.getDeclaredMethod("updateBundledSpeedReference",String::class.java,SpeedReferenceValue::class.java).apply {isAccessible=true}.invoke(controller,id,SpeedReferenceValue("numeric",value))
        fun dump():String = (field("conditionalCameraTracks").get(controller) as Map<*,*>).values.joinToString {track ->
            track!!::class.java.declaredFields.joinToString {f ->f.isAccessible=true;"${f.name}=${f.get(track)}"}
        }
        fun reevaluate() {runtime.tick();ConsumerSessionController::class.java.getDeclaredMethod("reevaluateConditionalCamera").apply {isAccessible=true}.invoke(controller)}
        override fun close() {main {controller.dispose()};context.deleteSharedPreferences(session);root.deleteRecursively()}
    }
    private class MutableClock(private var instant:Instant):Clock() {
        fun set(value:Instant) {instant=value}
        override fun instant()=instant
        override fun getZone():ZoneId=ZoneId.of("UTC")
        override fun withZone(zone:ZoneId)=this
    }
    private fun field(name:String)=ConsumerSessionController::class.java.getDeclaredField(name).apply {isAccessible=true}
}

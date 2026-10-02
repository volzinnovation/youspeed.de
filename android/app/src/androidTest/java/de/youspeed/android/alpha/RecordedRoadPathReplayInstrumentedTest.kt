package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.media.Image
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Build
import android.os.PowerManager
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.security.MessageDigest
import kotlin.math.ceil
import kotlin.math.roundToInt
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Headless, explicit-input replay. Never starts a controller, camera, recorder or uploader. */
@LargeTest
@RunWith(AndroidJUnit4::class)
class RecordedRoadPathReplayInstrumentedTest {
    private val identity = listOf(1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0)
    private fun elapsed(start: Long) = (System.nanoTime()-start)/1e6
    private fun sha(file: File) = MessageDigest.getInstance("SHA-256").let { digest ->
        file.inputStream().use { stream -> val bytes=ByteArray(1024*1024); while (true) {
            val n=stream.read(bytes); if (n<0) break; digest.update(bytes,0,n)
        } }; digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
    }

    @Test fun replayRecordedVideoWithActualModelsAndProductionPathSession() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        val args=InstrumentationRegistry.getArguments()
        val requestedRunId=args.getString("replay_run_id")
        assumeTrue("Recorded-video replay requires an explicit replay_run_id",!requestedRunId.isNullOrBlank())
        val runId=requireNotNull(requestedRunId)
        require(runId.matches(Regex("[A-Za-z0-9_-]+")))
        val input=File(context.cacheDir,"recorded-road-path-replay/input.json")
        assertTrue("Explicit local replay inputs are required",input.isFile)
        val manifest=JSONObject(input.readText())
        val video=File(context.filesDir,"dashcam/${manifest.getString("videoFile")}")
        assertTrue("The existing source recording must remain available",video.isFile)
        assertEquals(manifest.getString("videoSha256"),sha(video))
        assertTrue(Build.MODEL.lowercase().contains("g86"))
        val startUs=((args.getString("replay_start_seconds")?.toDoubleOrNull() ?: 0.0)*1e6).toLong()
        val endUs=((args.getString("replay_end_seconds")?.toDoubleOrNull() ?: 646.6)*1e6).toLong()
        val intervalUs=((args.getString("replay_interval_seconds")?.toDoubleOrNull() ?: .5)*1e6).toLong()
        require(startUs>=0 && endUs>startUs && intervalUs>=100_000)
        val output=File(context.cacheDir,"recorded-road-path-replay/$runId").apply { mkdirs() }
        val power=context.getSystemService(PowerManager::class.java)
        val report=JSONObject().put("schemaVersion",1).put("runId",runId).put("completed",false)
            .put("measurementKind","recorded_video_actual_model_replay")
            .put("videoSha256",manifest.getString("videoSha256")).put("inputManifestSha256",sha(input))
            .put("sourceManifestSha256",manifest.getString("sourceManifestSha256"))
            .put("modelCountry",manifest.getString("country")).put("startPtsUs",startUs).put("endPtsUs",endUs)
            .put("samplingIntervalUs",intervalUs).put("deviceModel",Build.MODEL).put("sdk",Build.VERSION.SDK_INT)
            .put("appVersion",BuildConfig.VERSION_NAME).put("appVersionCode",BuildConfig.VERSION_CODE)
            .put("thermalStart",power?.currentThermalStatus).put("limitations",manifest.getJSONArray("limitations"))
        fun save() = File(output,"summary.json").writeText(report.toString(2))
        save()
        val contexts=manifest.getJSONArray("frames").let { a -> List(a.length()) { a.getJSONObject(it) } }
            .sortedBy { it.getDouble("capturedAtSeconds") }
        val fixes=manifest.getJSONArray("fixes").let { a -> List(a.length()) { a.getJSONObject(it) } }
            .sortedBy { it.getDouble("arrivalSeconds") }
        val cal=manifest.getJSONObject("calibration")
        val calibration=RoadPathCalibration(cal.getString("revision"),true,cal.getDouble("fx"),cal.getDouble("fy"),
            cal.getDouble("cx"),cal.getDouble("cy"),cal.getDouble("yawDegrees"),cal.getDouble("pitchDegrees"),
            cal.getDouble("rollDegrees"),cal.getDouble("heightMeters"),cal.getDouble("lateralOffsetMeters"))
        val anchor=manifest.getDouble("estimatedVideoUtcAnchor")
        val pack=AndroidTrafficSignModelPackLoader.load(context,manifest.getString("country"))
        assertEquals(manifest.getString("packId"),pack.modelPack.packId)
        assertEquals(manifest.getString("detectorSha256"),pack.detectorArtifact.sha256)
        assertEquals(manifest.getString("classifierSha256"),pack.classifierArtifact.sha256)
        report.put("packId",pack.modelPack.packId).put("detectorSha256",pack.detectorArtifact.sha256)
            .put("classifierSha256",pack.classifierArtifact.sha256).put("gpuPrecisionLossAllowed",true)
        val timings=linkedMapOf<String,MutableList<Double>>()
        fun record(name:String,value:Double) { timings.getOrPut(name) { mutableListOf() }.add(value) }
        val classes=linkedMapOf<String,Int>()
        val associationReasons=linkedMapOf<String,Int>()
        val associations=linkedMapOf<String,Int>()
        val thermal=linkedMapOf<Int,Int>()
        var selected=0; var decoded=0; var withSigns=0; var withBoundaries=0; var geometryAborts=0; var deadlineMisses=0
        var fixIndex=0; var contextIndex=-1; var scopeChanges=0; var lastScope:TSRApplicabilityScope?=null
        var previousPts=Long.MIN_VALUE; var repeatedPts=0; var reversedPts=0; var lastSelectedPts=Long.MIN_VALUE
        var gpu=0; var otherBackend=0
        val path=RoadPathSession()
        val applicability=TSRApplicabilitySession()
        val extractor=MediaExtractor()
        var codec:MediaCodec?=null
        var codecStarted=false
        val started=System.nanoTime()
        try {
            extractor.setDataSource(video.path)
            val track=(0 until extractor.trackCount).first { extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/")==true }
            extractor.selectTrack(track)
            val format=extractor.getTrackFormat(track)
            val rotation=if (format.containsKey(MediaFormat.KEY_ROTATION)) format.getInteger(MediaFormat.KEY_ROTATION) else 0
            assertEquals("This replay fixture is encoded upright",0,rotation)
            report.put("containerFormat",format.toString()).put("videoRotationDegrees",rotation)
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
            codec=MediaCodec.createDecoderByType(requireNotNull(format.getString(MediaFormat.KEY_MIME)))
            report.put("decoderName",codec.name).put("decoderHardwareAccelerated",codec.codecInfo.isHardwareAccelerated)
            codec.configure(format,null,null,0); codec.start(); codecStarted=true
            extractor.seekTo(startUs,MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
            var inputEnded=false; var outputEnded=false; var nextPts=startUs
            var lastProgress=System.nanoTime()
            val info=MediaCodec.BufferInfo()
            var decoderFormat=format
            AndroidLiteRtTrafficSignInferenceEngine(pack,gpuPrecisionLossAllowed=true).use { engine ->
                val startup=AndroidTrafficSignStartupProbe.run(context,engine,pack.modelPack)
                report.put("startupBackend",startup.executionBackend)
                    .put("startupWarmInferenceMs",JSONArray(startup.warmInferenceTimesMs))
                    .put("startupConfirmationWindowMs",startup.timingProfile.confirmationWindowMs)
                save()
                File(output,"frames.ndjson").bufferedWriter().use { writer ->
                    while (!outputEnded) {
                        check(elapsed(lastProgress)<120_000) { "Decoder produced no output for120s" }
                        if (!inputEnded) {
                            val index=codec.dequeueInputBuffer(1_000)
                            if (index>=0) {
                                val buffer=requireNotNull(codec.getInputBuffer(index))
                                val size=extractor.readSampleData(buffer,0)
                                if (size<0) { codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputEnded=true }
                                else { codec.queueInputBuffer(index,0,size,extractor.sampleTime,0); extractor.advance() }
                            }
                        }
                        val index=codec.dequeueOutputBuffer(info,1_000)
                        if (index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                            decoderFormat=codec.outputFormat; report.put("decoderOutputFormat",decoderFormat.toString()); save()
                        } else if (index>=0) {
                            lastProgress=System.nanoTime()
                            try {
                                if (info.size>0) {
                                    val pts=info.presentationTimeUs; decoded++
                                    if (pts==previousPts) repeatedPts++ else if (pts<previousPts) reversedPts++
                                    previousPts=pts
                                    if (pts>endUs) { outputEnded=true }
                                    else if (pts>=nextPts && pts>lastSelectedPts) {
                                        val target=nextPts
                                        while (nextPts<=pts) nextPts+=intervalUs
                                        val frameStart=System.nanoTime()
                                        val capture=anchor+pts/1e6
                                        while (fixIndex<fixes.size && fixes[fixIndex].getDouble("arrivalSeconds")<=capture) {
                                            val f=fixes[fixIndex++]
                                            path.recordLocation(f.getDouble("time"),f.getDouble("latitude"),f.getDouble("longitude"),
                                                f.getDouble("course"),f.getDouble("speed"),f.getDouble("accuracy"),f.getDouble("courseAccuracy"))
                                        }
                                        while (contextIndex+1<contexts.size && contexts[contextIndex+1].getDouble("capturedAtSeconds")<=capture) contextIndex++
                                        val sourceContext=contexts.getOrNull(contextIndex)
                                        val scope=sourceContext?.let { TSRApplicabilityJson.decodeScope(Json.parseToJsonElement(it.getJSONObject("scope").toString()).jsonObject) }
                                            ?.copy(cameraGeometryId="recorded-1280x720")
                                            ?: TSRApplicabilityScope("recorded-replay-before-context","unavailable","recorded-1280x720",0,0,0)
                                        if (lastScope!=scope) { scopeChanges++; lastScope=scope }
                                        val road=sourceContext?.optJSONObject("road")?.let {
                                            TSRApplicabilityJson.decodeRoad(Json.parseToJsonElement(it.toString()).jsonObject).copy(scope=scope)
                                        }
                                        val image=requireNotNull(codec.getOutputImage(index)) { "Decoder cannot expose readable YUV" }
                                        try {
                                            assertEquals(1280,image.cropRect.width()); assertEquals(720,image.cropRect.height())
                                            // Match live ordering: exact-exposure luma/filter/geometry first,
                                            // then TSR, then sign association using the same immutable geometry.
                                            val frameId="replay-$pts"
                                            val pathStart=System.nanoTime()
                                            val crop=image.cropRect
                                            val plane=image.planes[0]
                                            val buffer=plane.buffer.duplicate().apply { position(position()+crop.top*plane.rowStride+crop.left*plane.pixelStride) }
                                            val small=ByteArray(384*216)
                                            LaneLumaSampler.copyUpright(buffer,plane.rowStride,plane.pixelStride,
                                                LaneImageGeometry(crop.width(),crop.height(),0,identity),small,384,216)
                                            val preprocessingMs=elapsed(pathStart)
                                            val prepared=path.prepare(RoadPathCameraFrame(small,384,216,capture,
                                                "recorded-centered-crop-1280x720",calibration,true,preprocessingMs,pathStart,
                                                1280,720,0,identity,pts/1e6),frameId,scope)
                                            val lanePreparedAtNanos=System.nanoTime()
                                            val pathPreparationMs=elapsed(pathStart)
                                            val convertStart=System.nanoTime()
                                            val bitmap=toBitmap(image,decoderFormat)
                                            val conversionMs=elapsed(convertStart)
                                            try {
                                                val tsrStartedAtNanos=System.nanoTime()
                                                assertTrue("Lane preparation must finish before TSR starts",lanePreparedAtNanos<=tsrStartedAtNanos)
                                                val inference=engine.recognizeAllWithDiagnostics(bitmap)
                                                val raw=inference.detections
                                                val candidates=raw.take(TSRApplicabilityConfiguration.maxCandidates).mapIndexed { i,d ->
                                                    val c=d.candidate; val b=c.boundingBox
                                                    val score=if(pack.modelPack.calibration.runtimeOutput==TrafficSignCalibrationOutput.RAW_SCORE)c.rawScore else c.calibratedConfidence
                                                    TSRApplicabilityCandidate("$frameId:$i","${c.semantic.kind.wireValue}:${c.semantic.value}:${c.semantic.unit}",
                                                        TSRApplicabilityBox(b.x,b.y,b.width,b.height),c.rawScore,
                                                        c.isQualifiedObservation(pack.modelPack.calibration.runtimeOutput,pack.modelPack.thresholds.unknown,
                                                            pack.modelPack.classMapping.firstOrNull { it.classId==c.rawClassId }?.threshold ?: 0.0),
                                                        c.assemblyId,score,c.calibratedConfidence,c.rawClassId,c.proposalRawScore,c.classifierRawScore)
                                                }
                                                val batch=TSRFrameCandidateBatch(1,frameId,capture*1000,scope,"analyzed",candidates,
                                                    raw.size>TSRApplicabilityConfiguration.maxCandidates || inference.detectorProposalCount>=12,
                                                    raw.size,pack.detectorArtifact.sha256,pack.modelPack.preprocessing.version,road,pack.modelPack.countries.singleOrNull())
                                                val trackingStart=System.nanoTime()
                                                val diagnostic=applicability.evaluate(batch)
                                                val trackingMs=elapsed(trackingStart)
                                                val associationStart=System.nanoTime()
                                                val result=JSONObject(path.evaluate(prepared,diagnostic))
                                                val pathMs=pathPreparationMs+elapsed(associationStart)
                                                // Historical UTC age is meaningless as a live-latency measurement.
                                                result.remove("captureAgeAtEvaluationMs"); result.remove("localOrigin")
                                                val totalMs=elapsed(frameStart)
                                                val thermalState=power?.currentThermalStatus ?: -1
                                                thermal[thermalState]=(thermal[thermalState] ?: 0)+1
                                                if(inference.executionBackend=="gpu")gpu++ else otherBackend++
                                                if(raw.isNotEmpty())withSigns++
                                                raw.forEach { d -> val name=d.candidate.rawClassId; classes[name]=(classes[name] ?: 0)+1 }
                                                if((result.optJSONArray("boundaries")?.length() ?: 0)>0)withBoundaries++
                                                if(result.optBoolean("geometryDeadlineExceeded",false))geometryAborts++
                                                if(pathMs>=200 || result.optBoolean("deadlineExceeded",false))deadlineMisses++
                                                result.optJSONArray("associations")?.let { a -> for(i in 0 until a.length()) {
                                                    val v=a.getJSONObject(i); val reason=v.getString("reason"); val classification=v.getString("classification")
                                                    associationReasons[reason]=(associationReasons[reason] ?: 0)+1
                                                    associations[classification]=(associations[classification] ?: 0)+1
                                                } }
                                                record("pixelConversionMs",conversionMs); record("inferenceMs",inference.inferenceMs)
                                                record("detectorPreprocessingMs",inference.detectorPreprocessingMs)
                                                record("detectorInferenceMs",inference.detectorInferenceMs); record("classifierInferenceMs",inference.classifierInferenceMs)
                                                record("trackingMs",trackingMs); record("pathPreprocessingMs",preprocessingMs)
                                                record("geometryMs",result.optDouble("geometryMs",0.0)); record("addedPathMs",pathMs)
                                                record("selectedFrameWallMs",totalMs); record("selectionOffsetMs",(pts-target)/1000.0)
                                                if(lastSelectedPts!=Long.MIN_VALUE)record("selectedPtsIntervalMs",(pts-lastSelectedPts)/1000.0)
                                                val row=JSONObject().put("frameId",frameId).put("actualPtsUs",pts).put("targetPtsUs",target)
                                                    .put("estimatedCaptureUtcSeconds",capture).put("captureUtcEstimated",true)
                                                    .put("inferenceMs",inference.inferenceMs).put("pixelConversionMs",conversionMs)
                                                    .put("lanePreparedAtNanos",lanePreparedAtNanos).put("tsrStartedAtNanos",tsrStartedAtNanos)
                                                    .put("lanePreparedBeforeTsr",lanePreparedAtNanos<=tsrStartedAtNanos)
                                                    .put("pathPreparationMs",pathPreparationMs)
                                                    .put("addedPathMs",pathMs).put("trackingMs",trackingMs).put("selectedFrameWallMs",totalMs)
                                                    .put("executionBackend",inference.executionBackend).put("fallbackReason",inference.accelerationFallbackReason)
                                                    .put("thermalStatus",thermalState).put("scope",JSONObject(TSRApplicabilityJson.encodeScope(scope).toString()))
                                                    .put("candidates",JSONArray(candidates.map { JSONObject(TSRApplicabilityJson.encodeCandidate(it).toString()) }))
                                                    .put("applicability",JSONArray(diagnostic.decisions.map { JSONObject(TSRApplicabilityJson.encodeDecision(it).toString()) }))
                                                    .put("path",result)
                                                writer.write(row.toString()); writer.newLine()
                                                // Review decoder color/orientation before a full run. File encoding is
                                                // outside all measured frame/model/path regions and happens once.
                                                if(selected==0)File(output,"first-frame-$pts.png").outputStream().use {
                                                    check(bitmap.compress(Bitmap.CompressFormat.PNG,100,it))
                                                }
                                                selected++; lastSelectedPts=pts
                                                if(selected%20==0) { writer.flush(); report.put("selectedFrames",selected).put("lastSelectedPtsUs",pts); save()
                                                    Log.i("RoadPathReplay","$runId frames=$selected ptsSeconds=${pts/1e6} wallSeconds=${elapsed(started)/1000}") }
                                            } finally { bitmap.recycle() }
                                        } finally { image.close() }
                                    }
                                }
                                if(info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0)outputEnded=true
                            } finally { codec.releaseOutputBuffer(index,false) }
                        }
                    }
                }
            }
            report.put("completed",true)
            assertTrue("Replay must run actual frames",selected>0)
            assertEquals("Decoded output PTS must remain ordered",0,reversedPts)
        } catch(t:Throwable) { report.put("completed",false).put("failure",t.javaClass.simpleName+": "+t.message); throw t }
        finally {
            if(codecStarted)runCatching { codec?.stop() }; codec?.release(); extractor.release()
            report.put("elapsedWallSeconds",elapsed(started)/1000).put("selectedFrames",selected).put("decodedFrames",decoded)
                .put("lastSelectedPtsUs",lastSelectedPts).put("decodedRepeatedPts",repeatedPts).put("decodedReversedPts",reversedPts)
                .put("framesWithSigns",withSigns).put("framesWithBoundaries",withBoundaries).put("geometryDeadlineAborts",geometryAborts)
                .put("addedPathDeadlineMisses",deadlineMisses).put("gpuFrames",gpu).put("otherBackendFrames",otherBackend)
                .put("locationFixesFed",fixIndex).put("observedScopeSegments",scopeChanges)
                .put("rawClassCounts",JSONObject(classes as Map<*,*>)).put("associationReasonCounts",JSONObject(associationReasons as Map<*,*>))
                .put("associationClassifications",JSONObject(associations as Map<*,*>))
                .put("thermalSampleCounts",JSONObject(thermal.mapKeys { it.key.toString() } as Map<*,*>)).put("thermalEnd",power?.currentThermalStatus)
                .put("timingMs",JSONObject().apply { timings.forEach { (name,values) -> put(name,stats(values)) } })
            save()
        }
    }

    private fun stats(values:List<Double>):JSONObject {
        val sorted=values.sorted()
        if(sorted.isEmpty())return JSONObject().put("samples",0)
        fun q(p:Double)=sorted[(ceil(sorted.size*p).toInt()-1).coerceIn(0,sorted.lastIndex)]
        return JSONObject().put("samples",sorted.size).put("p50",q(.5)).put("p95",q(.95)).put("p99",q(.99))
            .put("min",sorted.first()).put("max",sorted.last()).put("mean",sorted.average())
    }

    /** Decoder YUV → sRGB-like bytes using signalled standard/range; no JPEG intermediates. */
    private fun toBitmap(image:Image,format:MediaFormat):Bitmap {
        val rect=image.cropRect; val width=rect.width(); val height=rect.height()
        val planes=image.planes; require(planes.size==3)
        val y=planes[0]; val u=planes[1]; val v=planes[2]
        val yb=y.buffer; val ub=u.buffer; val vb=v.buffer
        val yp=yb.position(); val up=ub.position(); val vp=vb.position()
        val full=format.containsKey(MediaFormat.KEY_COLOR_RANGE) && format.getInteger(MediaFormat.KEY_COLOR_RANGE)==MediaFormat.COLOR_RANGE_FULL
        val bt709=format.containsKey(MediaFormat.KEY_COLOR_STANDARD) && format.getInteger(MediaFormat.KEY_COLOR_STANDARD)==MediaFormat.COLOR_STANDARD_BT709
        val kr=if(bt709).2126 else .299; val kb=if(bt709).0722 else .114; val kg=1-kr-kb
        val yy=if(full)1.0 else 255.0/219; val cc=if(full)1.0 else 255.0/224
        val pixels=IntArray(width*height)
        fun clamp(x:Double)=x.roundToInt().coerceIn(0,255)
        for(row in 0 until height)for(col in 0 until width) {
            val x=col+rect.left; val z=row+rect.top
            val l=((yb.get(yp+z*y.rowStride+x*y.pixelStride).toInt() and 255)-(if(full)0 else 16))*yy
            val cb=((ub.get(up+(z/2)*u.rowStride+(x/2)*u.pixelStride).toInt() and 255)-128)*cc
            val cr=((vb.get(vp+(z/2)*v.rowStride+(x/2)*v.pixelStride).toInt() and 255)-128)*cc
            val r=clamp(l+2*(1-kr)*cr); val b=clamp(l+2*(1-kb)*cb)
            val g=clamp(l-2*kb*(1-kb)/kg*cb-2*kr*(1-kr)/kg*cr)
            pixels[row*width+col]=(255 shl 24) or (r shl 16) or (g shl 8) or b
        }
        return Bitmap.createBitmap(pixels,width,height,Bitmap.Config.ARGB_8888)
    }
}

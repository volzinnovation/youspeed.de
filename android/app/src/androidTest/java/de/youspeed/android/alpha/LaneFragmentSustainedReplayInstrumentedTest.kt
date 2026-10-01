package de.youspeed.android.alpha

import android.os.Build
import android.os.Debug
import android.os.PowerManager
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.security.MessageDigest
import kotlin.math.ceil

/** Opt-in component-only sustained replay. No activity, camera, recorder, model, UI, GPS or network. */
class LaneFragmentSustainedReplayInstrumentedTest {
    private val variants = setOf("baseline", "bands", "fragments", "bands_fragments", "fragments_tracking", "bands_fragments_tracking")
    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun points(values: List<LanePoint>) = JSONArray().apply { values.forEach { put(JSONArray().put(it.x).put(it.y)) } }
    private fun boundaries(values: List<RoadBoundaryEvidence>) = JSONArray().apply { values.forEach { b ->
        put(JSONObject().put("points",points(b.points)).put("observedSegments",JSONArray().apply { b.observedSegments.forEach { put(points(it)) } })
            .put("confidence",b.confidence).put("cue",b.cue.name.lowercase()).put("supportRows",b.supportRows)
            .put("provenance",b.provenance.name.lowercase()).put("evidenceAgeSeconds",b.evidenceAgeSeconds)
            .put("geometryConfidence",b.geometryConfidence ?: JSONObject.NULL).put("paintOccupancy",b.paintOccupancy ?: JSONObject.NULL))
    } }
    private fun distribution(values: List<Double>): JSONObject {
        val sorted=values.sorted()
        if(sorted.isEmpty()) return JSONObject().put("count",0)
        fun q(p:Double)=sorted[(ceil(p*sorted.size).toInt()-1).coerceIn(0,sorted.lastIndex)]
        return JSONObject().put("count",sorted.size).put("p50",q(.5)).put("p95",q(.95)).put("p99",q(.99)).put("max",sorted.last())
    }
    private fun calibration(value: JSONObject?) = value?.let { c -> RoadPathCalibration(c.getString("revision"),c.getBoolean("verified"),
        c.getDouble("fx"),c.getDouble("fy"),c.getDouble("cx"),c.getDouble("cy"),c.getDouble("yawDegrees"),c.getDouble("pitchDegrees"),
        c.getDouble("rollDegrees"),c.getDouble("heightMeters"),if(c.isNull("lateralOffsetMeters")) null else c.getDouble("lateralOffsetMeters")) }
    private fun visual(value: JSONObject?) = value?.let { c ->
        fun p(name:String):LanePoint { val v=c.getJSONObject(name); return LanePoint(v.getDouble("x"),v.getDouble("y")) }
        VisualRoadCalibration(c.getString("revision"),c.getInt("imageWidth"),c.getInt("imageHeight"),c.getString("orientationKey"),
            c.getDouble("horizonY"),p("leftBottom"),c.getDouble("leftTopX"),p("rightBottom"),c.getDouble("rightTopX"))
    }
    private fun residentBytes():Long? = runCatching {
        File("/proc/self/status").useLines { lines -> lines.firstOrNull { it.startsWith("VmRSS:") }
            ?.trim()?.split(Regex("\\s+"))?.get(1)?.toLong()?.times(1024) }
    }.getOrNull()

    @Test fun pacedRecordedAblationsAndTracking() {
        val args=InstrumentationRegistry.getArguments()
        val runId=args.getString("lane_fragment_run_id")
        assumeTrue("Explicit lane_fragment_run_id required",runId!=null)
        require(runId!!.matches(Regex("[A-Za-z0-9_-]+")))
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(context.cacheDir,"lane-fragment-replay")
        val config=JSONObject(File(root,"config.json").readText())
        require(config.getString("runId")==runId) { "Explicit run ID must match config.json" }
        val seconds=(args.getString("lane_fragment_seconds")?.toDouble() ?: config.optDouble("secondsPerArm",180.0))
        require(seconds in 1.0..300.0)
        val arms=args.getString("lane_fragment_variants")?.split(',') ?: config.getJSONArray("variants").let { a -> (0 until a.length()).map { a.getString(it) } }
        require(arms.isNotEmpty() && arms.distinct()==arms && arms.all { it in variants })
        val manifestBytes=File(root,"input.json").readBytes()
        val rows=JSONObject(manifestBytes.toString(Charsets.UTF_8)).getJSONArray("frames")
        require(rows.length() in 1..5000)
        val output=File(root,"$runId.ndjson"); val report=File(root,"$runId.json")
        require(!output.exists() && !report.exists()) { "Use a new run ID" }
        val power=context.getSystemService(PowerManager::class.java)
        val summaries=JSONObject()
        output.bufferedWriter().use { writer ->
            for (arm in arms) {
                val options=RoadBoundaryDetectionOptions(useSearchBands=arm.contains("bands"),groupFragments=arm.contains("fragments"))
                fun newSession()=RoadPathSession(previewMode=true,detectionOptions=options,fragmentTracking=arm.endsWith("tracking"))
                var session=newSession()
                var previousSequence=""; var previousTime=Double.NEGATIVE_INFINITY
                val latencies=mutableListOf<Double>(); val filterTimes=mutableListOf<Double>(); val geometryTimes=mutableListOf<Double>()
                var maxRss=0L; var maxJava=0L; var maxNative=0L; var memorySamples=0; var operationRejects=0; var targetMisses=0; var invalidSelected=0
                var identityChanges=0; var previousIds:List<Long>?=null; var loops=0; var thermalPauseSeconds=0.0
                val thermalCounts=linkedMapOf<Int,Int>()
                val start=System.nanoTime(); var next=start; var index=0; var lastTick=start; var wasPaused=false
                while((System.nanoTime()-start)/1e9<seconds) {
                    val wait=next-System.nanoTime()
                    if(wait>0) Thread.sleep(wait/1_000_000,(wait%1_000_000).toInt())
                    val tick=System.nanoTime()
                    if((tick-start)/1e9>=seconds) break
                    if(wasPaused) thermalPauseSeconds+=(tick-lastTick)/1e9
                    lastTick=tick
                    val thermal=power?.currentThermalStatus ?: -1
                    thermalCounts[thermal]=(thermalCounts[thermal] ?: 0)+1
                    val paused=thermal>=PowerManager.THERMAL_STATUS_SEVERE
                    val row=rows.getJSONObject(index%rows.length()); if(index>0 && index%rows.length()==0) loops++
                    val record=JSONObject().put("schemaVersion",1).put("runId",runId).put("arm",arm).put("index",index)
                        .put("wallSeconds",(tick-start)/1e9).put("id",row.getString("id")).put("sequenceId",row.getString("sequenceId"))
                        .put("sourcePtsSeconds",row.getDouble("time")).put("thermalStatus",thermal).put("thermalPaused",paused)
                    if(index%10==0) {
                        val rss=residentBytes(); val runtime=Runtime.getRuntime(); val javaBytes=runtime.totalMemory()-runtime.freeMemory()
                        val native=Debug.getNativeHeapAllocatedSize(); memorySamples++
                        if(rss!=null) maxRss=maxOf(maxRss,rss)
                        maxJava=maxOf(maxJava,javaBytes); maxNative=maxOf(maxNative,native)
                        record.put("residentBytes",rss ?: JSONObject.NULL).put("javaHeapUsedBytes",javaBytes).put("nativeHeapAllocatedBytes",native)
                    }
                    if(!paused) {
                        val sequence=row.getString("sequenceId"); val pts=row.getDouble("time")
                        if(wasPaused || sequence!=previousSequence || pts<=previousTime) { session=newSession(); previousIds=null }
                        previousSequence=sequence; previousTime=pts
                        val filename=row.getString("file"); require(File(filename).name==filename)
                        val width=row.getInt("width"); val height=row.getInt("height")
                        require(width in 64..384 && height in 64..216)
                        val loadStart=System.nanoTime(); val bytes=File(root,filename).readBytes()
                        assertEquals(width*height,bytes.size); assertEquals(row.getString("rawSha256"),sha(bytes))
                        record.put("loadAndIntegrityMs",(System.nanoTime()-loadStart)/1e6)
                        val started=System.nanoTime(); val pixels=bytes.copyOf(); val copyMs=(System.nanoTime()-started)/1e6
                        val geometryId="encoded:$sequence:${row.getInt("decodedWidth")}x${row.getInt("decodedHeight")}"
                        val frame=RoadPathCameraFrame(pixels,width,height,pts,geometryId,calibration(row.optJSONObject("calibration")),true,copyMs,started,
                            rawWidth=row.getInt("decodedWidth"),rawHeight=row.getInt("decodedHeight"),sourceTimestampSeconds=pts,
                            visualCalibration=visual(row.optJSONObject("visualCalibration")),orientationKey=row.optString("orientationKey",""))
                        val scope=TSRApplicabilityScope(sequence,"component-replay",geometryId,1,1,1)
                        val prepared=session.prepare(frame,row.getString("id"),scope)
                        val elapsed=(System.nanoTime()-started)/1e6
                        val selected=prepared.presentation.visibleBoundaryIndices
                        invalidSelected+=selected.count { it !in prepared.geometry.boundaries.indices }
                        val ids=selected.map { selectedIndex -> prepared.presentation.items.firstOrNull { it.boundaryIndex==selectedIndex }?.trackId ?: -1L }
                        invalidSelected+=ids.count { it<0 }
                        val identitySet=ids.sorted()
                        if(previousIds!=null && previousIds!=identitySet) identityChanges++
                        previousIds=identitySet
                        latencies.add(elapsed); filterTimes.add(prepared.filterMs); geometryTimes.add(prepared.geometryMs)
                        if(prepared.geometry.budgetExceeded) operationRejects++
                        if(elapsed>50) targetMisses++
                        record.put("componentMs",elapsed).put("filterMs",prepared.filterMs).put("geometryMs",prepared.geometryMs)
                            .put("performanceTargetExceeded50Ms",elapsed>50).put("operationBudgetExceeded",prepared.geometry.budgetExceeded)
                            .put("operationCount",prepared.geometry.operationCount).put("temporalOperationCount",prepared.geometry.temporalOperationCount)
                            .put("selectedIndices",JSONArray(selected)).put("visibleIds",JSONArray(ids)).put("boundaries",boundaries(prepared.geometry.boundaries))
                            .put("selectedBoundaries",boundaries(selected.mapNotNull { prepared.geometry.boundaries.getOrNull(it) }))
                            .put("selectionDecisions",JSONArray(prepared.presentation.selectionDecisions.map { JSONObject(it.diagnosticFields) }))
                            .put("lanePreparationDiagnostics",JSONObject(prepared.diagnostics.diagnosticJson.toString()))
                    } else record.put("rejectionReason","thermal_paused")
                    writer.appendLine(record.toString()); if(index%10==0) writer.flush()
                    wasPaused=paused; index++
                    next+=100_000_000L
                    // Never burst through missed admissions to catch up after a stall.
                    if(next<System.nanoTime()) next=System.nanoTime()+100_000_000L
                }
                if(wasPaused) thermalPauseSeconds+=(System.nanoTime()-lastTick)/1e9
                summaries.put(arm,JSONObject().put("admissions",index).put("processedFrames",latencies.size).put("loops",loops)
                    .put("wallSeconds",(System.nanoTime()-start)/1e9).put("componentMs",distribution(latencies))
                    .put("filterMs",distribution(filterTimes)).put("geometryMs",distribution(geometryTimes))
                    .put("performanceTargetExceeded50Ms",targetMisses).put("operationBudgetExceeded",operationRejects)
                    .put("identitySetChangesWithinSequences",identityChanges).put("invalidSelectedIndices",invalidSelected)
                    .put("peakSampledResidentBytes",maxRss).put("peakSampledJavaHeapUsedBytes",maxJava).put("peakSampledNativeHeapAllocatedBytes",maxNative)
                    .put("memorySamples",memorySamples).put("thermalPausedSeconds",thermalPauseSeconds)
                    .put("thermalSamples",JSONObject(thermalCounts.mapKeys { it.key.toString() })))
                assertEquals("Selected boundary indices must be valid",0,invalidSelected)
            }
        }
        report.writeText(JSONObject().put("schemaVersion",1).put("runId",runId).put("completed",true)
            .put("deviceModel",Build.MODEL).put("sdk",Build.VERSION.SDK_INT).put("manifestSha256",sha(manifestBytes))
            .put("secondsPerArm",seconds).put("sustained",seconds>=180).put("fpsTarget",10).put("arms",summaries)
            .put("scope","Paced lane component replay; no camera, TSR, recorder, rendering or GNSS injection. Includes luma copy/filter/detection/tracking/presentation; excludes disk/integrity/JSON. Repeated encoded exposures reset at each sequence/loop. Thermal pause is this harness's severe-or-higher gate. RSS sampled once per second is process RSS, not an exact peak or Android memory limit. Identity counts are diagnostics, not manually labelled accuracy.")
            .toString(2))
        assertTrue(report.isFile)
    }
}

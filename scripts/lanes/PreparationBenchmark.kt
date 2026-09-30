package de.youspeed.android.alpha

import java.io.File
import java.nio.ByteBuffer
import kotlinx.serialization.json.*

/** Standalone ART benchmark: no app installation, camera, model, recorder or GNSS. */
object PreparationBenchmark {
    private val identity=listOf(1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0)
    private val scope=TSRApplicabilityScope("benchmark","offline","fixture",1,1,1)
    private data class Fixture(val id: String,val plane: ByteBuffer,val rawW: Int,val rawH: Int,val stride: Int,
        val width: Int,val height: Int,val rotation: Int)
    private data class Result(val pixels: ByteArray,val geometry: RoadBoundaryFrame,
        val presentation: RoadBoundaryPresentationSnapshot,val copyMs: Double,val filterMs: Double,
        val geometryMs: Double,val wallMs: Double,val cpuMs: Double)

    @JvmStatic fun main(args: Array<String>) {
        require(args.size==2) { "manifest.json duration-seconds" }
        val manifest=Json.parseToJsonElement(File(args[0]).readText()).jsonObject
        val fixtures=manifest.getValue("frames").jsonArray.map { value ->
            val f=value.jsonObject
            fun number(k: String)=f.getValue(k).jsonPrimitive.int
            Fixture(f.getValue("id").jsonPrimitive.content,
                ByteBuffer.wrap(File(f.getValue("path").jsonPrimitive.content).readBytes()),
                number("rawWidth"),number("rawHeight"),number("stride"),number("width"),number("height"),number("rotation"))
        }
        fun sample(f: Fixture, optimized: Boolean, index: Int,
            baseline: LegacyRoadPathSession, candidate: RoadPathSession, exact: Boolean=false): Result {
            val geometry=LaneImageGeometry(f.rawW,f.rawH,f.rotation,identity)
            val cpu=android.os.Debug.threadCpuTimeNanos()
            val start=System.nanoTime()
            val bytes=ByteArray(f.width*f.height)
            if(optimized) LaneLumaSampler.copyUpright(f.plane,f.stride,1,geometry,bytes,f.width,f.height)
            else LegacyLaneLumaSampler.copyUpright(f.plane,f.stride,1,geometry,bytes,f.width,f.height)
            val copied=System.nanoTime()
            val stamp=index*.5+10.0
            val inputStart=if(exact) 0L else start
            val result=if(optimized) {
                val frame=RoadPathCameraFrame(bytes,f.width,f.height,stamp,f.id,null,true,(copied-start)/1e6,inputStart,
                    f.rawW,f.rawH,f.rotation,identity,sourceTimestampSeconds=stamp)
                val p=candidate.prepare(frame,"frame-$index",scope)
                Result(bytes,p.geometry,p.presentation,(copied-start)/1e6,p.filterMs,p.geometryMs,
                    (System.nanoTime()-start)/1e6,(android.os.Debug.threadCpuTimeNanos()-cpu)/1e6)
            } else {
                val frame=LegacyRoadPathCameraFrame(bytes,f.width,f.height,stamp,f.id,null,true,(copied-start)/1e6,inputStart,
                    f.rawW,f.rawH,f.rotation,identity,sourceTimestampSeconds=stamp)
                val p=baseline.prepare(frame,"frame-$index",scope)
                Result(bytes,p.geometry,p.presentation,(copied-start)/1e6,p.filterMs,p.geometryMs,
                    (System.nanoTime()-start)/1e6,(android.os.Debug.threadCpuTimeNanos()-cpu)/1e6)
            }
            return result
        }
        // Correctness checks run with a fixed clock, separate from real-deadline timing.
        for(f in fixtures) {
            val baseline=LegacyRoadPathSession { 0L };val candidate=RoadPathSession { 0L }
            for(index in 0..3) {
                val old=sample(f,false,index,baseline,candidate,true)
                val new=sample(f,true,index,baseline,candidate,true)
                check(old.pixels.contentEquals(new.pixels)) { "luma mismatch ${f.id}" }
                check(old.geometry==new.geometry) { "geometry mismatch ${f.id}" }
                check(old.presentation==new.presentation) { "presentation mismatch ${f.id}" }
            }
        }
        // New sessions; correctness warmed the VM. First timing samples are session-cold,
        // not process-cold, and must not be reported as application cold starts.
        val baseline=fixtures.map { LegacyRoadPathSession() };val candidate=fixtures.map { RoadPathSession() }
        val start=System.nanoTime();var index=0
        val seconds=args[1].toDouble().coerceIn(1.0,180.0)
        while((System.nanoTime()-start)/1e9<seconds || index<20) {
            for((fi,f) in fixtures.withIndex()) {
                for(optimized in if(index%2==0) listOf(false,true) else listOf(true,false)) {
                    val r=sample(f,optimized,index,baseline[fi],candidate[fi])
                    println(buildJsonObject {
                        put("fixture",f.id);put("variant",if(optimized) "optimized" else "baseline")
                        put("index",index);put("warmup",index<10);put("copyMs",r.copyMs);put("filterMs",r.filterMs)
                        put("geometryMs",r.geometryMs);put("preparationMs",r.wallMs);put("threadCpuMs",r.cpuMs)
                        put("geometryBudgetExceeded",r.geometry.budgetExceeded);put("boundaries",r.geometry.boundaries.size)
                    }.toString())
                }
            }
            index++
        }
    }
}

package de.youspeed.android.alpha

import java.io.File
import java.security.MessageDigest

private fun encode(value:Any?):String=when(value) {
    null -> "null"
    is String -> "\""+value.replace("\\","\\\\").replace("\"","\\\"")+"\""
    is Boolean, is Number -> value.toString()
    is Map<*,*> -> value.entries.joinToString(",","{","}") { encode(it.key.toString())+":"+encode(it.value) }
    is Iterable<*> -> value.joinToString(",","[","]") { encode(it) }
    else -> error("Unsupported JSON value")
}
fun main(args:Array<String>) {
    File(args[0]).forEachLine { line ->
        val f=line.split('\t'); val width=f[2].toInt(); val height=f[3].toInt(); val time=f[4].toDouble()
        val bytes=File(f[1]).readBytes(); val filtered=requireNotNull(RoadPathLaneFilter.applyForDetector(bytes,width,height))
        val digest=MessageDigest.getInstance("SHA-256").digest(filtered).joinToString("") { "%02x".format(it.toInt() and 255) }
        for(options in listOf(RoadBoundaryDetectionOptions(),RoadBoundaryDetectionOptions(useSearchBands=true),RoadBoundaryDetectionOptions(groupFragments=true),RoadBoundaryDetectionOptions(useSearchBands=true,groupFragments=true))) {
            val frame=RoadBoundaryDetector().detect(filtered,width,height,time,options=options)
            println(encode(mapOf("id" to f[0],"variant" to options.identifier,"filteredSha256" to digest,
                "operationCount" to frame.operationCount,"budgetExceeded" to frame.budgetExceeded,"rejectionCounts" to frame.rejectionCounts,
                "boundaries" to frame.boundaries.map { b -> mapOf("points" to b.points.map { listOf(it.x,it.y) },"confidence" to b.confidence,
                    "cue" to b.cue.name.lowercase(),"supportRows" to b.supportRows,"observedSegments" to b.observedSegments.map { it.map { p -> listOf(p.x,p.y) } },
                    "geometryConfidence" to b.geometryConfidence,"paintOccupancy" to b.paintOccupancy) },
                "corridors" to frame.corridors.map { mapOf("leftBoundaryIndex" to it.leftBoundaryIndex,"rightBoundaryIndex" to it.rightBoundaryIndex,"confidence" to it.confidence) })))
        }
    }
}

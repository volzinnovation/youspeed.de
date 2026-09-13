package de.youspeed.android.alpha

import java.io.File

/** Host-only replay entry point; input names are restricted by replay.py. */
fun main(args: Array<String>) {
    require(args.size == 1) { "Expected fixture manifest TSV" }
    val detector = LaneDetector()
    val records = mutableListOf<String>()
    File(args[0]).readLines().filter { it.isNotBlank() }.forEach { row ->
        val fields = row.split('\t')
        require(fields.size == 4 && fields[0].matches(Regex("[A-Za-z0-9_-]+")))
        val width = fields[1].toInt()
        val height = fields[2].toInt()
        val pixels = File(fields[3]).readBytes()
        val tracker = LaneTracker()
        repeat(3) { frame ->
            val estimate = tracker.update(detector.detect(pixels, width, height, frame * 0.2))
            fun boundary(value: LaneBoundary?): String = if (value == null) "null" else {
                val points = value.points.joinToString(",") { "[${it.x},${it.y}]" }
                "{\"confidence\":${value.confidence},\"points\":[$points]}"
            }
            val corridor = estimate.corridorPoints.joinToString(",", "[", "]") { "[${it.x},${it.y}]" }
            records += "{\"case\":\"${fields[0]}\",\"frame\":$frame,\"state\":\"${estimate.state.name.lowercase()}\",\"timestamp_seconds\":${estimate.timestampSeconds},\"corridor_points\":$corridor,\"left\":${boundary(estimate.left)},\"right\":${boundary(estimate.right)}}"
        }
    }
    print(records.joinToString(",", "[", "]"))
}

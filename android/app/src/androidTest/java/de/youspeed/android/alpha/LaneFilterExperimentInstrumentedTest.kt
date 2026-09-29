package de.youspeed.android.alpha

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

/** Explicit offline experiment only: never starts a controller, camera, drive or recording. */
class LaneFilterExperimentInstrumentedTest {
    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it.toInt() and 255) }

    @Test fun recordedLumaPreprocessingComparison() {
        val args = InstrumentationRegistry.getArguments()
        val runId = args.getString("lane_filter_run_id")
        assumeTrue("Explicit private manifest required", runId != null)
        require(runId!!.matches(Regex("[A-Za-z0-9_-]+")))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val root = File(context.cacheDir, "lane-filter-experiment")
        val manifest = JSONObject(File(root, "input.json").readText())
        val rows = manifest.getJSONArray("frames")
        val detector = RoadBoundaryDetector()
        val output = File(root, "$runId.json")
        val results = JSONArray()
        val stats = linkedMapOf("raw" to mutableListOf<Double>(), "tophat5_enhanced" to mutableListOf())
        val filterStats = linkedMapOf("raw" to mutableListOf<Double>(), "tophat5_enhanced" to mutableListOf())
        var exactMatches = 0
        var deadlineMisses = 0
        var geometryAborts = 0
        val wallStart = System.nanoTime()
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val name = row.getString("file")
            require(File(name).name == name)
            val width = row.getInt("width")
            val height = row.getInt("height")
            require(width in 64..384 && height in 64..216)
            val bytes = File(root, name).readBytes()
            assertEquals(width * height, bytes.size)
            assertEquals(row.getString("rawSha256"), sha(bytes))
            val variants = if (i % 2 == 0) listOf("raw", "tophat5_enhanced") else listOf("tophat5_enhanced", "raw")
            for (variant in variants) {
                val start = System.nanoTime()
                val processed = if (variant == "raw") bytes else RoadPathLaneFilter.apply(bytes, width, height) {
                    System.nanoTime() - start < 50_000_000
                }
                val prepared = System.nanoTime()
                // A proposed prefilter must share the existing geometry deadline.
                var detection = if (processed == null) RoadBoundaryFrame(emptyList(), emptyList(), i.toDouble(), budgetExceeded = true)
                else detector.detect(processed, width, height, i.toDouble(),
                    shouldContinue = { (System.nanoTime() - start) < 50_000_000 })
                val end = System.nanoTime()
                val filterMs = (prepared - start) / 1e6
                val totalMs = (end - start) / 1e6
                if (totalMs >= 50) detection = RoadBoundaryFrame(emptyList(), emptyList(), i.toDouble(), budgetExceeded = true)
                stats.getValue(variant).add(totalMs)
                filterStats.getValue(variant).add(filterMs)
                if (totalMs >= 200) deadlineMisses++
                if (detection.budgetExceeded) geometryAborts++
                results.put(JSONObject().put("id", row.getString("id")).put("variant", variant)
                    .put("filterMs", filterMs).put("filterAndDetectorMs", totalMs)
                    .put("boundaryCount", detection.boundaries.size).put("paintCount", detection.boundaries.count { it.cue == RoadBoundaryCue.PAINT })
                    .put("geometryBudgetExceeded", detection.budgetExceeded).put("firstVariantSample", stats.getValue(variant).size == 1))
            }
            // Untimed exact parity is independent of a legitimate budget cancellation in the timed run.
            val exact = requireNotNull(RoadPathLaneFilter.apply(bytes, width, height))
            assertEquals("OpenCV reference parity: ${row.getString("id")}", row.getString("topHat5Sha256"), sha(exact))
            exactMatches++
        }
        fun distribution(values: List<Double>): JSONObject {
            val sorted = values.sorted()
            fun q(p: Double) = sorted[(ceil(p * sorted.size).toInt() - 1).coerceIn(0, sorted.lastIndex)]
            return JSONObject().put("samples", sorted.size).put("p50", q(.5)).put("p95", q(.95)).put("max", sorted.last())
        }
        val timing = JSONObject()
        stats.forEach { (name, values) -> timing.put(name, JSONObject().put("filterAndDetectorMs", distribution(values))
            .put("filterMs", distribution(filterStats.getValue(name)))) }
        val report = JSONObject().put("schemaVersion", 1).put("runId", runId).put("completed", true)
            .put("productionFilter", RoadPathLaneFilter.ID).put("frames", rows.length()).put("opencvExactMatches", exactMatches).put("timingMs", timing)
            .put("deadlineMisses200Ms", deadlineMisses).put("geometryAborts50Ms", geometryAborts)
            .put("wallSeconds", (System.nanoTime() - wallStart) / 1e9).put("results", results)
            .put("scope", "Offline Moto CPU preprocessing + unchanged production detector sharing a 50 ms deadline; includes first samples; excludes disk I/O, decode, luma resampling, TSR, path association, JSON and UI")
        output.writeText(report.toString(2))
        assertTrue("Actual recorded frames required", rows.length() > 0)
    }
}

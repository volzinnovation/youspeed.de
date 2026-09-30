package de.youspeed.android.alpha

import android.os.Build
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
import kotlin.math.abs
import kotlin.math.ceil

/** Opt-in, headless component replay. Never creates an activity, camera, drive, model or upload. */
class LaneContinuityReplayInstrumentedTest {
    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it.toInt() and 255) }

    private data class Sample(
        val id: String, val sequence: String, val time: Double, val geometry: RoadBoundaryFrame,
        val copyMs: Double, val filterMs: Double, val geometryAndTrackingMs: Double,
        val associationAndJsonMs: Double, val totalMs: Double, val reportedAddedMs: Double,
        val deadlineExceeded: Boolean,
    )

    @Test fun sixRecordedSequencesCompareStatelessAndTemporalProductionPaths() {
        val args = InstrumentationRegistry.getArguments()
        val runId = args.getString("lane_continuity_run_id")
        assumeTrue("Explicit private sequence replay required", runId != null)
        require(runId!!.matches(Regex("[A-Za-z0-9_-]+")))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val root = File(context.cacheDir, "lane-continuity-replay")
        val manifestBytes = File(root, "input.json").readBytes()
        val manifest = JSONObject(manifestBytes.toString(Charsets.UTF_8))
        val rows = manifest.getJSONArray("frames")
        require(rows.length() > 0)
        val power = context.getSystemService(PowerManager::class.java)
        val thermalStart = power?.currentThermalStatus
        val thermalBySequence = JSONObject()
        val samples = linkedMapOf("stateless" to mutableListOf<Sample>(), "temporal_session" to mutableListOf())
        val detector = RoadBoundaryDetector()
        var session = RoadPathSession()
        var lastSequence: String? = null
        var lastPts = Double.NEGATIVE_INFINITY
        val seenSequences = linkedSetOf<String>()
        var exactFilterMatches = 0
        var evidenceFreshnessViolations = 0
        val wallStart = System.nanoTime()
        val output = File(root, "$runId.ndjson")
        require(!output.exists()) { "Use a new run ID; existing reports are preserved" }
        output.bufferedWriter().use { writer ->
            for (index in 0 until rows.length()) {
                val row = rows.getJSONObject(index)
                val id = row.getString("id")
                val sequence = row.getString("sequenceId")
                val filename = row.getString("file")
                require(File(filename).name == filename)
                val width = row.getInt("width"); val height = row.getInt("height")
                require(width in 64..384 && height in 64..216)
                val ptsValue = row.getLong("actualPtsValue")
                val ptsTimescale = row.getLong("actualPtsTimescale")
                require(ptsTimescale > 0)
                val pts = ptsValue.toDouble() / ptsTimescale
                assertEquals(row.getDouble("actualVideoSeconds"), pts, 1e-9)
                if (sequence != lastSequence) {
                    require(seenSequences.add(sequence)) { "Sequence must be contiguous" }
                    session = RoadPathSession() // Reset all temporal/association state at each disconnected clip.
                    lastSequence = sequence; lastPts = Double.NEGATIVE_INFINITY
                    thermalBySequence.put(sequence, power?.currentThermalStatus ?: JSONObject.NULL)
                }
                require(pts > lastPts) { "Fixtures must preserve unique increasing encoded exposures" }
                lastPts = pts
                val bytes = File(root, filename).readBytes()
                assertEquals(width * height, bytes.size)
                assertEquals(row.getString("rawSha256"), sha(bytes))
                val scope = TSRApplicabilityScope(sequence, "offline-video", "encoded:${width}x$height", 1, 1, 1)
                val diagnostic = TSRApplicabilityDiagnostic(1,
                    TSRFrameCandidateBatch(1, id, pts * 1000, scope, "analyzed", emptyList(), false, 0,
                        "none-headless-lane-replay", "none", null), emptyList(), emptyList())
                // Alternate order to reduce systematic warming bias; retain every first/cold sample.
                val arms = if (index % 2 == 0) listOf("stateless", "temporal_session") else listOf("temporal_session", "stateless")
                for (arm in arms) {
                    val started = System.nanoTime()
                    val pixels = bytes.copyOf()
                    val copied = System.nanoTime()
                    val copyMs = (copied - started) / 1e6
                    val sample: Sample
                    var pathJson: JSONObject? = null
                    if (arm == "stateless") {
                        val filtered = RoadPathLaneFilter.apply(pixels, width, height) { System.nanoTime() - started < 50_000_000 }
                        val filteredAt = System.nanoTime()
                        var geometry = if (filtered == null) RoadBoundaryFrame(emptyList(), emptyList(), pts, budgetExceeded = true)
                        else detector.detect(filtered, width, height, pts) { System.nanoTime() - started < 50_000_000 }
                        val finished = System.nanoTime()
                        val totalMs = (finished - started) / 1e6
                        if (totalMs >= 50) geometry = RoadBoundaryFrame(emptyList(), emptyList(), pts,
                            budgetExceeded = true, operationCount = geometry.operationCount)
                        sample = Sample(id, sequence, pts, geometry, copyMs, (filteredAt - copied) / 1e6,
                            (finished - filteredAt) / 1e6, 0.0, totalMs, totalMs, totalMs >= 200)
                    } else {
                        // PTS is the replay evidence clock. No fake GNSS, intrinsics, visual calibration or UTC is supplied.
                        val frame = RoadPathCameraFrame(pixels, width, height, pts, "encoded:$sequence", null,
                            true, copyMs, started, rawWidth = row.getInt("decodedWidth"), rawHeight = row.getInt("decodedHeight"),
                            sourceTimestampSeconds = pts)
                        val prepared = session.prepare(frame, id, scope)
                        val preparationFinished = System.nanoTime()
                        val encoded = session.evaluate(prepared, diagnostic)
                        val finished = System.nanoTime()
                        pathJson = JSONObject(encoded) // Parsing/reporting is outside measured path work.
                        sample = Sample(id, sequence, pts, prepared.geometry, copyMs, prepared.filterMs,
                            prepared.geometryMs, (finished - preparationFinished) / 1e6, (finished - started) / 1e6,
                            pathJson.optDouble("totalAddedProcessingMs", (finished - started) / 1e6),
                            pathJson.optBoolean("deadlineExceeded") || finished - started >= 200_000_000)
                        for (boundary in prepared.geometry.boundaries) {
                            val fresh = boundary.lastFreshTimestampSeconds
                            val age = boundary.evidenceAgeSeconds
                            if (age < 0 || age > .8 + 1e-9 || fresh == null || fresh > pts + 1e-9 ||
                                abs((pts - fresh) - age) > 1e-7 ||
                                (boundary.provenance != RoadBoundaryProvenance.TRACKED && age > 1e-9)) evidenceFreshnessViolations++
                        }
                    }
                    samples.getValue(arm).add(sample)
                    val result = JSONObject().put("schemaVersion", 1).put("runId", runId).put("id", id)
                        .put("arm", arm).put("sequenceId", sequence).put("source", row.getString("source"))
                        .put("sourceVideoSha256", row.getString("sourceVideoSha256")).put("rawSha256", row.getString("rawSha256"))
                        .put("actualPtsValue", ptsValue).put("actualPtsTimescale", ptsTimescale).put("sourcePtsSeconds", pts)
                        .put("lumaCopyMs", sample.copyMs).put("filterMs", sample.filterMs)
                        .put("geometryAndTrackingMs", sample.geometryAndTrackingMs).put("associationAndJsonMs", sample.associationAndJsonMs)
                        .put("totalWallMs", sample.totalMs).put("reportedAddedProcessingMs", sample.reportedAddedMs)
                        .put("geometryBudgetExceeded", sample.geometry.budgetExceeded).put("deadlineExceeded200Ms", sample.deadlineExceeded)
                        .put("operationCount", sample.geometry.operationCount).put("temporalOperationCount", sample.geometry.temporalOperationCount)
                        .put("temporalResetReason", sample.geometry.temporalResetReason ?: JSONObject.NULL)
                        .put("boundaries", boundariesJson(sample.geometry.boundaries)).put("corridorCount", sample.geometry.corridors.size)
                        .put("thermalStatus", power?.currentThermalStatus ?: JSONObject.NULL)
                        .put("replayClock", "encoded_video_pts_relative_seconds")
                    if (pathJson != null) result.put("pathDiagnostic", pathJson)
                    writer.appendLine(result.toString())
                }
                // Exact OpenCV parity is checked separately so a valid deadline cancellation retains its timing sample.
                val exact = requireNotNull(RoadPathLaneFilter.apply(bytes, width, height))
                assertEquals(row.getString("topHat5Sha256"), sha(exact))
                exactFilterMatches++
            }
        }
        val aggregate = JSONObject()
        samples.forEach { (arm, values) ->
            val perSequence = JSONObject()
            seenSequences.forEach { seq -> perSequence.put(seq, summarize(values.filter { it.sequence == seq })) }
            aggregate.put(arm, summarize(values).put("bySequence", perSequence))
        }
        val report = JSONObject().put("schemaVersion", 1).put("runId", runId).put("completed", true)
            .put("deviceModel", Build.MODEL).put("androidSdk", Build.VERSION.SDK_INT)
            .put("manifestSha256", sha(manifestBytes)).put("frames", rows.length()).put("sequences", seenSequences.size)
            .put("filterId", RoadPathLaneFilter.ID).put("opencvExactMatches", exactFilterMatches)
            .put("evidenceFreshnessViolations", evidenceFreshnessViolations).put("thermalStart", thermalStart ?: JSONObject.NULL)
            .put("thermalEnd", power?.currentThermalStatus ?: JSONObject.NULL).put("thermalBySequence", thermalBySequence)
            .put("wallSeconds", (System.nanoTime() - wallStart) / 1e9).put("arms", aggregate)
            .put("scope", "Headless accelerated component replay, production code and exact encoded PTS; no model, camera, controller, GNSS or calibration. Timings include reduced-luma copying/filter/geometry and temporal-session association/JSON, exclude disk/decode/camera sampling/model/UI. GeometryAndTrackingMs is the combined production stage, not separate optical-flow attribution. Counts and displacement are continuity diagnostics, not accuracy or calibrated road truth. Relative PTS must not be interpreted as wall-clock overlay visibility.")
        File(root, "$runId.json").writeText(report.toString(2))
        assertEquals("No stale/future/mislabeled evidence may survive", 0, evidenceFreshnessViolations)
        assertEquals(rows.length(), exactFilterMatches)
        assertTrue("Both recordings and all six controls are required", seenSequences.size >= 6)
    }

    private fun boundariesJson(boundaries: List<RoadBoundaryEvidence>) = JSONArray().apply {
        boundaries.forEach { b -> put(JSONObject().put("cue", b.cue.name.lowercase()).put("confidence", b.confidence)
            .put("supportRows", b.supportRows).put("provenance", b.provenance.name.lowercase())
            .put("lastFreshTimestampSeconds", b.lastFreshTimestampSeconds ?: JSONObject.NULL).put("evidenceAgeSeconds", b.evidenceAgeSeconds)
            .put("trackedAnchorCount", b.trackedAnchorCount).put("points", JSONArray().apply {
                b.points.forEach { put(JSONArray().put(it.x).put(it.y)) }
            })) }
    }

    private fun distribution(values: List<Double>): JSONObject {
        val sorted = values.filter(Double::isFinite).sorted()
        if (sorted.isEmpty()) return JSONObject().put("samples", 0)
        fun q(p: Double) = sorted[(ceil(p * sorted.size).toInt() - 1).coerceIn(0, sorted.lastIndex)]
        return JSONObject().put("samples", sorted.size).put("p50", q(.5)).put("p95", q(.95)).put("p99", q(.99)).put("max", sorted.last())
    }

    private fun summarize(values: List<Sample>): JSONObject {
        var pairs = 0; var countChanges = 0; var presenceChanges = 0; var lost = 0; var born = 0
        val displacements = mutableListOf<Double>()
        for ((a, b) in values.zipWithNext()) {
            if (a.sequence != b.sequence || b.time - a.time !in 0.0.. .8) continue
            pairs++
            if (a.geometry.boundaries.size != b.geometry.boundaries.size) countChanges++
            if (a.geometry.boundaries.isEmpty() != b.geometry.boundaries.isEmpty()) presenceChanges++
            val matches = mutableListOf<Triple<Double, Int, Int>>()
            a.geometry.boundaries.forEachIndexed { i, left -> b.geometry.boundaries.forEachIndexed { j, right ->
                if (left.cue == right.cue) distance(left.points, right.points)?.takeIf { it <= .15 }?.let { matches += Triple(it, i, j) }
            } }
            val leftUsed = mutableSetOf<Int>(); val rightUsed = mutableSetOf<Int>()
            for ((distance, i, j) in matches.sortedBy { it.first }) {
                if (i !in leftUsed && j !in rightUsed) { leftUsed += i; rightUsed += j; displacements += distance }
            }
            lost += a.geometry.boundaries.size - leftUsed.size; born += b.geometry.boundaries.size - rightUsed.size
        }
        val boundaries = values.flatMap { it.geometry.boundaries }
        val provenance = JSONObject()
        RoadBoundaryProvenance.entries.forEach { p -> provenance.put(p.name.lowercase(), boundaries.count { it.provenance == p }) }
        val resets = JSONObject()
        values.groupingBy { it.geometry.temporalResetReason ?: "none" }.eachCount().forEach { (reason, count) -> resets.put(reason, count) }
        return JSONObject().put("frames", values.size).put("boundaryFrames", values.count { it.geometry.boundaries.isNotEmpty() })
            .put("paintFrames", values.count { s -> s.geometry.boundaries.any { it.cue == RoadBoundaryCue.PAINT } })
            .put("twoPaintFrames", values.count { s -> s.geometry.boundaries.count { it.cue == RoadBoundaryCue.PAINT } >= 2 })
            .put("corridorFrames", values.count { it.geometry.corridors.isNotEmpty() }).put("adjacentPairs", pairs)
            .put("countChanges", countChanges).put("presenceChanges", presenceChanges).put("unmatchedPriorBoundaries", lost).put("newBoundaries", born)
            .put("matchedDisplacementNormalized", distribution(displacements)).put("provenance", provenance)
            .put("evidenceAgeSeconds", distribution(boundaries.map { it.evidenceAgeSeconds }))
            .put("freshDetectorOperationCount", distribution(values.map { it.geometry.operationCount.toDouble() }))
            .put("temporalOperationCount", distribution(values.map { it.geometry.temporalOperationCount.toDouble() }))
            .put("temporalResetReasons", resets)
            .put("geometryBudgetAborts50Ms", values.count { it.geometry.budgetExceeded }).put("deadlineMisses200Ms", values.count { it.deadlineExceeded })
            .put("timingMs", JSONObject().put("lumaCopy", distribution(values.map { it.copyMs }))
                .put("filter", distribution(values.map { it.filterMs })).put("geometryAndTracking", distribution(values.map { it.geometryAndTrackingMs }))
                .put("associationAndJson", distribution(values.map { it.associationAndJsonMs })).put("totalWall", distribution(values.map { it.totalMs }))
                .put("reportedAddedProcessing", distribution(values.map { it.reportedAddedMs })))
    }

    private fun distance(left: List<LanePoint>, right: List<LanePoint>): Double? {
        fun xAt(points: List<LanePoint>, y: Double): Double? {
            if (points.size < 2 || y < points.first().y || y > points.last().y) return null
            val i = points.indexOfFirst { it.y >= y }.coerceAtLeast(1)
            val a = points[i - 1]; val b = points[i]
            return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
        }
        val deltas = listOf(.6, .7, .8, .9).mapNotNull { y ->
            val a = xAt(left, y); val b = xAt(right, y)
            if (a == null || b == null) null else abs(a - b)
        }
        return deltas.takeIf { it.size >= 2 }?.average()
    }
}

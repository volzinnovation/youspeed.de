package de.youspeed.android.alpha

import android.graphics.BitmapFactory
import android.os.Build
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.nio.ByteBuffer
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeFalse
import org.junit.Test
import org.junit.runner.RunWith

/** Offline component replay, not a substitute for CameraX + TSR + recorder endurance. */
@LargeTest
@RunWith(AndroidJUnit4::class)
class RoadPathPerformanceInstrumentedTest {
    private val identity = listOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    private val calibration = RoadPathCalibration("benchmark-only", true, .8, .8, .5, .5,
        0.0, 0.0, 0.0, 1.4, -.08)
    private val scope = TSRApplicabilityScope("benchmark", "synthetic", "upright", 1, 1, 1)
    @Volatile private var consumed = 0

    private data class Fixture(val name: String, val plane: ByteBuffer, val rowStride: Int,
        val pixelStride: Int, val width: Int, val height: Int, val rotation: Int = 0,
        val source: String = "generated", val clutter: Boolean = false)
    private data class Timing(val wall: Double, val queue: Double, val baseline: Double,
        val copy: Double = 0.0, val geometry: Double = 0.0, val association: Double = 0.0,
        val added: Double = 0.0, val boundaryCount: Int = 0, val budgetExceeded: Boolean = false,
        val geometryAborted: Boolean = false)

    @Test
    fun pairedReplayMeasuresAdditionalRoadPathComponentsAndDeadlineMisses() {
        assumeFalse("Wall-time budgets require a physical device", Build.FINGERPRINT.startsWith("generic") || Build.MODEL.contains("sdk_gphone"))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val args = InstrumentationRegistry.getArguments()
        val repeats = (args.getString("road_path_iterations")?.toIntOrNull() ?: 120).coerceIn(20, 2000)
        val warmup = (args.getString("road_path_warmup")?.toIntOrNull() ?: 8).coerceIn(1, 100)
        val runId = args.getString("road_path_run_id") ?: "direct-${System.currentTimeMillis()}"
        val power = context.getSystemService(PowerManager::class.java)
        val worker = Executors.newSingleThreadExecutor { task ->
            Thread({ Process.setThreadPriority(Process.THREAD_PRIORITY_BACKGROUND); task.run() }, "RoadPathBenchmark")
        }
        val report = JSONObject().put("schemaVersion", 1).put("runId", runId)
            .put("measurementKind", "offline_paired_component_replay")
            .put("budgetMs", 200.0).put("liveOverheadVerified", false)
            .put("sustainedThermalBehaviorVerified", false)
            .put("accuracyVerified", false)
            .put("limitations", JSONArray(listOf(
                "No live CameraX, video encoder, photo capture, map lookup, GPU inference or camera backlog is measured.",
                "Baseline replays already-detected synthetic candidates through production applicability; enabled mode invokes the production RoadPathSession. Model inference is excluded in both modes.",
                "Image decode and RGB-to-luma fixture preparation occur before timing; camera-plane copy and resizing are timed.",
                "Synthetic camera metadata does not measure Camera2 focal-characteristic retrieval; input geometry conversion and luma-buffer allocation are included.",
                "Synthetic camera calibration and GNSS poses exercise geometry; no real fixture is a calibrated accuracy label.",
                "Pose/observation replay times are synthetic. Measured durations use elapsedRealtimeNanos; capture age is not measured.",
                "Worker dispatch is measured, but the production camera worker contention and sustained thermal behavior require a separate drive.",
                "Paired on-minus-off wall times retain negative jitter; component costs are independently timed and checked.",
            )))
            .put("device", JSONObject().put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL)
                .put("sdk", Build.VERSION.SDK_INT).put("release", Build.VERSION.RELEASE)
                .put("fingerprint", Build.FINGERPRINT).put("abis", JSONArray(Build.SUPPORTED_ABIS.toList())))
            .put("app", JSONObject().put("applicationId", BuildConfig.APPLICATION_ID)
                .put("versionName", BuildConfig.VERSION_NAME).put("versionCode", BuildConfig.VERSION_CODE))
            .put("iterationsPerFixture", repeats).put("warmupPerFixture", warmup)
            .put("thermalBefore", power?.currentThermalStatus)
        val reports = JSONArray()
        var budgetPassed = true
        try {
            val fixtures = listOf(
                generated("landscape", 1280, 720),
                generated("portrait", 720, 1280),
                generated("landscape_clutter", 1280, 720, clutter = true),
                generated("portrait_clutter_pixel_stride_2", 720, 1280, clutter = true, pixelStride = 2),
                generated("rotated_landscape", 720, 1280, rotation = 90),
                imageFixture("tsr-panoramax-0906fc23.jpg"),
                imageFixture("tsr-panoramax-49e25e66.jpg"),
            )
            for (fixture in fixtures) {
                val geometry = LaneImageGeometry(fixture.width, fixture.height, fixture.rotation, identity)
                val scale = min(384.0 / geometry.uprightWidth, 216.0 / geometry.uprightHeight).coerceAtMost(1.0)
                val width = max(1, (geometry.uprightWidth * scale).toInt())
                val height = max(1, (geometry.uprightHeight * scale).toInt())
                val baseline = TSRApplicabilitySession()
                val enabled = TSRApplicabilitySession()
                val session = RoadPathSession(SystemClock::elapsedRealtimeNanos)
                var sequence = 0
                fun sample(on: Boolean, index: Int): Timing {
                    val submitted = SystemClock.elapsedRealtimeNanos()
                    val future = worker.submit<Timing> {
                        val entered = SystemClock.elapsedRealtimeNanos()
                        val batch = syntheticBatch(index)
                        val diagnostic = (if (on) enabled else baseline).evaluate(batch)
                        consumed = diagnostic.tracks.size
                        val baseFinished = SystemClock.elapsedRealtimeNanos()
                        if (!on) Timing((baseFinished - submitted) / 1e6, (entered - submitted) / 1e6,
                            (baseFinished - entered) / 1e6)
                        else {
                            val transform = FloatArray(9) { identity[it].toFloat() }
                            val inputGeometry = LaneImageGeometry(fixture.width, fixture.height, fixture.rotation,
                                transform.map(Float::toDouble))
                            val frameScale = minOf(384.0 / inputGeometry.uprightWidth, 216.0 / inputGeometry.uprightHeight, 1.0)
                            val frameWidth = (inputGeometry.uprightWidth * frameScale).toInt().coerceAtLeast(1)
                            val frameHeight = (inputGeometry.uprightHeight * frameScale).toInt().coerceAtLeast(1)
                            val destination = ByteArray(frameWidth * frameHeight)
                            LaneLumaSampler.copyUpright(fixture.plane, fixture.rowStride, fixture.pixelStride,
                                inputGeometry, destination, frameWidth, frameHeight)
                            val geometryId = "fixture:${fixture.width}x${fixture.height}:${fixture.rotation}:${transform.joinToString()}"
                            val copied = SystemClock.elapsedRealtimeNanos()
                            val captureTime = 10.0 + index * .2
                            // GNSS collection cost is included conservatively, although the live
                            // recorder stores fixes on location callbacks rather than each frame.
                            session.recordLocation(captureTime, index * 2.0 / 6_371_000 * 180 / Math.PI,
                                0.0, 0.0, 10.0, .1, .2)
                            val diagnostics = session.evaluate(RoadPathCameraFrame(destination, frameWidth, frameHeight,
                                captureTime, geometryId, calibration, true,
                                (copied - baseFinished) / 1e6, baseFinished), diagnostic)
                            val finished = SystemClock.elapsedRealtimeNanos()
                            val json = JSONObject(diagnostics)
                            consumed = diagnostics.length
                            // Deadline fallback diagnostics deliberately omit geometry detail;
                            // retain and fail the actual slow sample instead of crashing parsing.
                            val geometryMs = json.optDouble("geometryMs", 0.0)
                            val addedMs = (finished - baseFinished) / 1e6
                            Timing((finished - submitted) / 1e6, (entered - submitted) / 1e6,
                                (baseFinished - entered) / 1e6, (copied - baseFinished) / 1e6,
                                geometryMs, max(0.0, addedMs - geometryMs - (copied - baseFinished) / 1e6),
                                addedMs, json.optJSONArray("boundaries")?.length() ?: 0,
                                json.optBoolean("deadlineExceeded", false), json.optBoolean("geometryDeadlineExceeded", false))
                        }
                    }
                    return future.get(15, TimeUnit.SECONDS)
                }
                fun pair(): Pair<Timing, Timing> {
                    val index = sequence++
                    return if (index % 2 == 0) {
                        val off = sample(false, index); off to sample(true, index)
                    } else {
                        val on = sample(true, index); sample(false, index) to on
                    }
                }
                val cold = pair()
                val warming = List(warmup) { pair() }
                val pairs = List(repeats) { pair() }
                val added = pairs.map { it.second.added }
                val differences = pairs.map { it.second.wall - it.first.wall }
                val coldDifference = cold.second.wall - cold.first.wall
                val fixturePass = (pairs + warming + cold).all { (off, on) ->
                    on.added <= 200.0 && on.wall - off.wall <= 200.0 && !on.budgetExceeded }
                budgetPassed = budgetPassed && fixturePass
                reports.put(JSONObject().put("name", fixture.name).put("source", fixture.source)
                    .put("inputWidth", fixture.width).put("inputHeight", fixture.height)
                    .put("sampledWidth", width).put("sampledHeight", height).put("rotationDegrees", fixture.rotation)
                    .put("pixelStride", fixture.pixelStride).put("rowStride", fixture.rowStride)
                    .put("baselineOffWallMs", stats(pairs.map { it.first.wall }))
                    .put("enabledWallMs", stats(pairs.map { it.second.wall }))
                    .put("pairedAddedWallMs", stats(differences))
                    .put("addedComponentsMs", stats(added))
                    .put("copyMs", stats(pairs.map { it.second.copy }))
                    .put("geometryMs", stats(pairs.map { it.second.geometry }))
                    .put("trajectoryAndAssociationMs", stats(pairs.map { it.second.association }))
                    .put("enabledQueueMs", stats(pairs.map { it.second.queue }))
                    .put("baselineProcessingMs", stats(pairs.map { it.first.baseline }))
                    .put("coldAddedComponentsMs", cold.second.added).put("coldPairedAddedWallMs", coldDifference)
                    .put("warmupAddedComponentsMs", stats(warming.map { it.second.added }))
                    .put("warmupPairedAddedWallMs", stats(warming.map { it.second.wall - it.first.wall }))
                    .put("maxBoundaryCount", pairs.maxOf { it.second.boundaryCount })
                    .put("detectorDeadlineAborts", pairs.count { it.second.geometryAborted })
                    .put("componentBudgetPassed", fixturePass).put("thermalAfter", power?.currentThermalStatus)
                    .put("samples", JSONArray(pairs.map { (off, on) -> JSONObject()
                        .put("offWallMs", off.wall).put("onWallMs", on.wall).put("addedComponentsMs", on.added)
                        .put("queueMs", on.queue).put("copyMs", on.copy).put("geometryMs", on.geometry)
                        .put("associationMs", on.association).put("deadlineExceeded", on.budgetExceeded)
                        .put("geometryDeadlineAborted", on.geometryAborted) })))
                report.put("fixtures", reports).put("componentBudgetPassed", budgetPassed)
                File(context.cacheDir, "road-path-performance.json").writeText(report.toString(2))
            }
            val oracleTimes = worker.submit<List<Double>> {
                List(repeats) { index ->
                    val started = SystemClock.elapsedRealtimeNanos()
                    repeat(24) { exerciseOracleAssociation(index) }
                    (SystemClock.elapsedRealtimeNanos() - started) / 1e6
                }
            }.get(60, TimeUnit.SECONDS)
            // A separate synthetic control guarantees non-degenerate triangulation is
            // measured even when an unlabelled static image offers no usable corridor.
            report.put("synthetic24TrackTriangulationControlMs", stats(oracleTimes))
            val controlPassed = oracleTimes.all { it <= 200.0 }
            budgetPassed = budgetPassed && controlPassed
            report.put("syntheticControlBudgetPassed", controlPassed)
            report.put("thermalAfter", power?.currentThermalStatus)
                .put("componentBudgetPassed", budgetPassed).put("completed", true)
            File(context.cacheDir, "road-path-performance.json").writeText(report.toString(2))
            assertTrue("Measured road-path components or paired added wall time exceeded 200 ms; report retained in app cache", budgetPassed)
        } finally {
            worker.shutdownNow()
        }
    }

    @Test
    fun deadlineCancellationClearsGeometryAndStaleTriangulationCannotBecomeFresh() {
        val cancelled = RoadBoundaryDetector().detect(ByteArray(384 * 216) { 230.toByte() },
            384, 216, 10.0, shouldContinue = { false })
        assertTrue(cancelled.budgetExceeded)
        assertTrue(cancelled.boundaries.isEmpty())
        assertTrue(cancelled.corridors.isEmpty())
        val (poses, observations) = oracleInputs(10.0)
        val stale = RoadPathEvidence.evaluate("benchmark", 11.6, observations, poses, calibration, emptyList())
        assertEquals("unknown", stale.classification)
        assertEquals("stale_observations", stale.reason)
        assertTrue(stale.shadowOnly)
    }

    private fun oracleInputs(origin: Double): Pair<List<RoadPathPose>, List<RoadPathObservation>> {
        val poses = listOf(0.0, .4, .8).map { offset ->
            RoadPathPose("benchmark", origin + offset, 0.0, offset * 10, 0.0, 10.0, .1, .2)
        }
        val observations = poses.map { pose -> RoadPathObservation("sign", "benchmark", calibration.revision,
            pose.timeSeconds, .5 + .8 * 3.08 / (30 - pose.northMeters), .5 + .8 * (1.4 - 2) / (30 - pose.northMeters)) }
        return poses to observations
    }

    private fun exerciseOracleAssociation(index: Int) {
        val origin = 10.0 + index * .2
        val (poses, observations) = oracleInputs(origin)
        val oracle = RoadPathCorridor("synthetic-current", "current_path", listOf(
            RoadPathPoint(-2.0, 0.0), RoadPathPoint(2.0, 0.0), RoadPathPoint(2.0, 50.0), RoadPathPoint(-2.0, 50.0)),
            1.0, true, 2.0)
        val calibrated = RoadPathEvidence.evaluate("benchmark", origin + .8, observations, poses, calibration, listOf(oracle))
        check(calibrated.supportingObservations == 3 && calibrated.shadowOnly &&
            calibrated.eastMeters?.let { abs(it - 3.0) < 1e-7 } == true &&
            calibrated.northMeters?.let { abs(it - 30.0) < 1e-7 } == true &&
            calibrated.heightMeters?.let { abs(it - 2.0) < 1e-7 } == true) {
            "Synthetic triangulation control did not recover the known sign coordinates: $calibrated"
        }
        consumed = calibrated.hashCode()
    }

    private fun syntheticBatch(index: Int): TSRFrameCandidateBatch {
        val time = 10_000.0 + index * 200
        val candidates = List(24) { candidate -> TSRApplicabilityCandidate("candidate-$candidate", "maxspeed:70",
            TSRApplicabilityBox(.03 + (candidate % 6) * .15, .08 + (candidate / 6) * .15, .04, .04),
            .95, true, null) }
        val road = TrafficSignMapContextSnapshot("road-$index", time, scope, "way", 1.0, 1.0, 0.0,
            0.0, true, "primary", emptyList(), emptyList(), emptyList(), 60.0, 0.0, 70)
        return TSRFrameCandidateBatch(1, "frame-$index", time, scope, "analyzed", candidates, false,
            candidates.size, "synthetic-existing-detections", "upright", road, "DE")
    }

    private fun generated(name: String, width: Int, height: Int, clutter: Boolean = false,
        pixelStride: Int = 1, rotation: Int = 0): Fixture {
        val rowStride = width * pixelStride + 16
        val plane = ByteBuffer.allocate(rowStride * height + 1).apply { position(1) }
        for (y in 0 until height) for (x in 0 until width) {
            val u = x.toDouble() / (width - 1)
            val v = y.toDouble() / (height - 1)
            val stripe = v in .50.. .94 && (abs(u - (.42 - (v - .52) * .55)) < .007 ||
                abs(u - (.58 + (v - .52) * .55)) < .007)
            val distractor = clutter && ((x / 13 + y / 19) % 7 == 0 || x % 71 < 3)
            plane.put(1 + y * rowStride + x * pixelStride, (if (stripe || distractor) 230 else 55).toByte())
        }
        return Fixture(name, plane, rowStride, pixelStride, width, height, rotation, clutter = clutter)
    }

    private fun imageFixture(asset: String): Fixture {
        val bitmap = requireNotNull(InstrumentationRegistry.getInstrumentation().context.assets.open(asset)
            .use(BitmapFactory::decodeStream))
        try {
            val pixels = IntArray(bitmap.width * bitmap.height)
            bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
            val plane = ByteBuffer.allocate(pixels.size)
            pixels.forEachIndexed { index, value ->
                val red = (value ushr 16) and 255; val green = (value ushr 8) and 255; val blue = value and 255
                plane.put(index, ((77 * red + 150 * green + 29 * blue) ushr 8).toByte())
            }
            return Fixture(asset, plane, bitmap.width, 1, bitmap.width, bitmap.height, source = "existing_unlabelled_still")
        } finally { bitmap.recycle() }
    }

    private fun stats(values: List<Double>): JSONObject {
        val sorted = values.sorted()
        fun percentile(q: Double) = sorted[(ceil(q * sorted.size).toInt() - 1).coerceAtLeast(0)]
        return JSONObject().put("samples", values.size).put("p50", percentile(.5)).put("p95", percentile(.95))
            .put("p99", percentile(.99)).put("max", sorted.last()).put("deadlineMisses", values.count { it > 200.0 })
    }
}

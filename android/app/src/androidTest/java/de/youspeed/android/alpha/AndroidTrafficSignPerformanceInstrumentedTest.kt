package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Matrix
import android.graphics.Paint
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs
import kotlin.math.max

@LargeTest
@RunWith(AndroidJUnit4::class)
class AndroidTrafficSignPerformanceInstrumentedTest {
    @Test
    fun reducedPrecisionGpuPreservesFullPrecisionSceneResultsAndReportsStageTimings() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        // The second real 70 scene is also an iPhone fixture, SHA-256
        // 1d2c8a66c8eedf68c3028d8749c5916c597ba2b7feeb4e1ddb71a4bf219b3f76.
        val fixtures = listOf("reference70", "earlier70", "cityEntry", "dimmed70", "blank")
        val results = linkedMapOf<String, Map<String, List<AndroidTrafficSignInferenceResult>>>()
        val startupReports = JSONObject()
        for (allowPrecisionLoss in listOf(false, true)) {
            val mode = if (allowPrecisionLoss) "reducedPrecision" else "fullPrecision"
            AndroidLiteRtTrafficSignInferenceEngine(pack, gpuPrecisionLossAllowed = allowPrecisionLoss).use { engine ->
                val startup = AndroidTrafficSignStartupProbe.run(instrumentation.targetContext, engine, pack.modelPack)
                assertEquals("This benchmark requires actual GPU execution", "gpu", startup.executionBackend)
                startupReports.put(mode, JSONObject()
                    .put("warmInferenceTimesMs", JSONArray(startup.warmInferenceTimesMs))
                    .put("confirmationWindowMs", startup.timingProfile.confirmationWindowMs))
                results[mode] = fixtures.associateWith { fixture ->
                    val bitmap = loadFixture(fixture)
                    try { List(3) { engine.recognizeAllWithDiagnostics(bitmap) } }
                    finally { bitmap.recycle() }
                }
            }
        }
        // Save all timing and prediction evidence before assertions, including any parity failure.
        val report = JSONObject()
            .put("detectorSha256", pack.detectorArtifact.sha256)
            .put("classifierSha256", pack.classifierArtifact.sha256)
            .put("startup", startupReports)
            .put("modes", JSONObject().apply {
                results.forEach { (mode, scenes) -> put(mode, JSONObject().apply {
                    scenes.forEach { (scene, samples) -> put(scene, JSONArray(samples.map(::sampleJson))) }
                }) }
            })
        File(instrumentation.targetContext.cacheDir, "tsr-gpu-precision-benchmark.json").writeText(report.toString())
        Log.i("YouSpeedTSR", "GPU precision benchmark: $report")

        val fullPrecision = results.getValue("fullPrecision")
        val reducedPrecision = results.getValue("reducedPrecision")
        fixtures.forEach { fixture ->
            val baseline = fullPrecision.getValue(fixture).last()
            (fullPrecision.getValue(fixture) + reducedPrecision.getValue(fixture)).forEach { sample ->
                assertEquals("$fixture must actually use GPU", "gpu", sample.executionBackend)
                assertTrue("$fixture must not use CPU fallback", sample.accelerationFallbackReason == null)
                assertEquals("$fixture proposal admission", baseline.detectorProposalCount, sample.detectorProposalCount)
                assertEquals("$fixture classifier calls", baseline.classifierInvocationCount, sample.classifierInvocationCount)
                assertEquals("$fixture primary class", primaryDetection(baseline.detections)?.candidate?.rawClassId,
                    primaryDetection(sample.detections)?.candidate?.rawClassId)
                assertEquals("$fixture displayed sign", TrafficSignDisplayPolicy.accepted(baseline.detections)?.rawClassId,
                    TrafficSignDisplayPolicy.accepted(sample.detections)?.rawClassId)
                assertEquals("$fixture detection count", baseline.detections.size, sample.detections.size)
                val unmatched = sample.detections.toMutableList()
                baseline.detections.forEach { expected ->
                    val candidate = expected.candidate
                    val actual = requireNotNull(unmatched
                        .filter { it.candidate.rawClassId == candidate.rawClassId }
                        .maxByOrNull { it.candidate.boundingBox.intersectionOverUnion(candidate.boundingBox) }) {
                        "$fixture lost class ${candidate.rawClassId}"
                    }
                    unmatched.remove(actual)
                    // FP16 coordinates quantize subpixel box edges. A fixed
                    // 95% IoU rejects a <1-input-pixel shift on a distant sign;
                    // bound the actual detector-space error as well as overlap.
                    val expectedBox = candidate.boundingBox
                    val actualBox = actual.candidate.boundingBox
                    val sourceWidth = requireNotNull(baseline.sourceWidthPixels).toDouble()
                    val sourceHeight = requireNotNull(baseline.sourceHeightPixels).toDouble()
                    val scale = 1280.0 / max(sourceWidth, sourceHeight)
                    val edgeErrors = listOf(
                        abs(expectedBox.x - actualBox.x) * sourceWidth * scale,
                        abs(expectedBox.x + expectedBox.width - actualBox.x - actualBox.width) * sourceWidth * scale,
                        abs(expectedBox.y - actualBox.y) * sourceHeight * scale,
                        abs(expectedBox.y + expectedBox.height - actualBox.y - actualBox.height) * sourceHeight * scale,
                    )
                    assertTrue("$fixture ${candidate.rawClassId} detector pixel error $edgeErrors",
                        edgeErrors.all { it <= 1.0 })
                    assertTrue("$fixture ${candidate.rawClassId} bounding box overlap",
                        actualBox.intersectionOverUnion(expectedBox) >= 0.90)
                    assertEquals("$fixture ${candidate.rawClassId} semantic", candidate.semantic, actual.candidate.semantic)
                    assertEquals("$fixture ${candidate.rawClassId} detector score", requireNotNull(candidate.proposalRawScore),
                        requireNotNull(actual.candidate.proposalRawScore), 0.05)
                    assertEquals("$fixture ${candidate.rawClassId} classifier score", requireNotNull(candidate.classifierRawScore),
                        requireNotNull(actual.candidate.classifierRawScore), 0.02)
                    val classThreshold = pack.modelPack.classMapping.firstOrNull { it.classId == candidate.rawClassId }?.threshold ?: 0.0
                    listOf(pack.modelPack.thresholds.unknown, pack.modelPack.thresholds.provisional,
                        pack.modelPack.thresholds.confirmed, classThreshold).forEach { threshold ->
                        assertEquals("$fixture ${candidate.rawClassId} threshold $threshold",
                            candidate.rawScore >= threshold, actual.candidate.rawScore >= threshold)
                    }
                    assertEquals("$fixture ${candidate.rawClassId} display eligibility",
                        TrafficSignDisplayPolicy.accepted(listOf(expected)) != null,
                        TrafficSignDisplayPolicy.accepted(listOf(actual)) != null)
                }
            }
        }
        assertEquals("maxspeed:70", primaryDetection(fullPrecision.getValue("reference70").last().detections)?.candidate?.rawClassId)
        assertTrue(fullPrecision.getValue("blank").all { it.detections.isEmpty() })
        assertTrue(reducedPrecision.getValue("blank").all { it.detections.isEmpty() })
    }

    @Test
    fun reusedRotationMatchesThePreviousFullFrameTransformAtEveryCameraOrientation() {
        AndroidTrafficSignBitmapRotation().use { rotation ->
            for ((width, height) in listOf(37 to 53, 48 to 32)) {
                val source = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                val pixels = IntArray(width * height) { index ->
                    Color.argb(255, index * 17 % 256, index * 31 % 256, index * 47 % 256)
                }
                source.setPixels(pixels, 0, width, 0, 0, width, height)
                try {
                    for (degrees in listOf(0, 90, 180, 270)) {
                        val expected = Bitmap.createBitmap(source, 0, 0, width, height,
                            Matrix().apply { postRotate(degrees.toFloat()) }, true)
                        try {
                            val actual = rotation.orient(source, degrees)
                            assertTrue("$width x $height at $degrees degrees must preserve every source pixel", expected.sameAs(actual))
                            assertSame("A second same-size frame must reuse rotation storage", actual, rotation.orient(source, degrees))
                            if (degrees == 0) assertSame(source, actual)
                        } finally {
                            if (expected !== source) expected.recycle()
                        }
                    }
                } finally { source.recycle() }
            }
        }
    }

    private fun loadFixture(name: String): Bitmap {
        if (name == "blank") return Bitmap.createBitmap(1200, 1600, Bitmap.Config.ARGB_8888).apply {
            eraseColor(Color.rgb(114, 114, 114))
        }
        val asset = when (name) {
            "earlier70" -> "tsr-panoramax-49e25e66.jpg"
            "cityEntry" -> "tsr-city310-bernbach.jpg"
            else -> "tsr-panoramax-0906fc23.jpg"
        }
        val source = requireNotNull(InstrumentationRegistry.getInstrumentation().context.assets
            .open(asset).use(BitmapFactory::decodeStream))
        if (name != "dimmed70") return source
        try {
            return Bitmap.createBitmap(source.width, source.height, Bitmap.Config.ARGB_8888).apply {
                val paint = Paint().apply {
                    colorFilter = ColorMatrixColorFilter(ColorMatrix().apply { setScale(0.6f, 0.6f, 0.6f, 1f) })
                }
                Canvas(this).drawBitmap(source, 0f, 0f, paint)
            }
        } finally { source.recycle() }
    }

    private fun sampleJson(sample: AndroidTrafficSignInferenceResult) = JSONObject()
        .put("executionBackend", sample.executionBackend)
        .put("accelerationFallbackReason", sample.accelerationFallbackReason)
        .put("inferenceMs", sample.inferenceMs)
        .put("detectorPreprocessingMs", sample.detectorPreprocessingMs)
        .put("detectorInferenceMs", sample.detectorInferenceMs)
        .put("classifierInferenceMs", sample.classifierInferenceMs)
        .put("detectorProposalCount", sample.detectorProposalCount)
        .put("classifierInvocationCount", sample.classifierInvocationCount)
        .put("sourceWidthPixels", sample.sourceWidthPixels)
        .put("sourceHeightPixels", sample.sourceHeightPixels)
        .put("detections", JSONArray(sample.detections.map { detection ->
            val candidate = detection.candidate
            JSONObject().put("classId", candidate.rawClassId)
                .put("proposalScore", candidate.proposalRawScore)
                .put("classifierScore", candidate.classifierRawScore)
                .put("boundingBox", JSONArray(listOf(candidate.boundingBox.x, candidate.boundingBox.y,
                    candidate.boundingBox.width, candidate.boundingBox.height)))
        }))
}

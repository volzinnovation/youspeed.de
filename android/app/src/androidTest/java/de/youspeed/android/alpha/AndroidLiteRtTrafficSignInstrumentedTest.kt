package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.concurrent.TimeUnit
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@LargeTest
@RunWith(AndroidJUnit4::class)
class AndroidLiteRtTrafficSignInstrumentedTest {
    @Test
    fun panoramaxTownFaces() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val fixtures = instrumentation.context.assets
        val rows = JSONArray(fixtures.open("tsr-town-face/panoramax-crops.json").bufferedReader().use { it.readText() })
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        val box = NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, 1.0)
        AndroidLiteRtTrafficSignInferenceEngine(pack).use { engine ->
            for (i in 0 until rows.length()) {
                val sample = rows.getJSONObject(i)
                val name = sample.getString("file")
                val source = requireNotNull(fixtures.open("tsr-town-face/$name").use(BitmapFactory::decodeStream))
                try {
                    for (code in listOf(310, 311)) {
                        assertEquals("$name, DE:$code", sample.getInt("code") == code,
                            engine.matchesTownFace(source, box, townExit = code == 311))
                    }
                } finally {
                    source.recycle()
                }
            }
        }
    }

    @Test
    fun germanTownFacesRejectPhotographedDirectionSigns() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val baseline = AndroidTrafficSignModelPackLoader.load(context)
        val pack = AndroidTrafficSignModelPackLoader.townTrial(context, baseline) ?: baseline
        val fixtures = instrumentation.context.assets
        val rows = JSONArray(fixtures.open("tsr-town-face/cases.json").bufferedReader().use { it.readText() })
        AndroidLiteRtTrafficSignInferenceEngine(pack).use { engine ->
            for (i in 0 until rows.length()) {
                val row = rows.getJSONObject(i)
                val name = row.getString("file")
                val source = requireNotNull(fixtures.open("tsr-town-face/$name").use(BitmapFactory::decodeStream))
                try {
                    val box = NormalizedTrafficSignBoundingBox(row.getDouble("x"), row.getDouble("y"),
                        row.getDouble("width"), row.getDouble("height"))
                    assertFalse("$name accepted as DE:310", engine.matchesTownFace(source, box, townExit = false))
                    assertFalse("$name accepted as DE:311", engine.matchesTownFace(source, box, townExit = true))
                    val result = engine.recognizeAllWithDiagnostics(source)
                    assertFalse(name, result.detections.any { it.candidate.rawClassId in setOf("city:start", "city:end") })
                    Log.i("YouSpeedTownTest", "$name: ${result.detectorProposalCount} proposals, no town detections")
                } finally {
                    source.recycle()
                }
            }
            for (code in listOf(310, 311)) {
                val source = requireNotNull(context.assets.open("tsr/sign-pictograms/png/de-$code.png")
                    .use(BitmapFactory::decodeStream))
                try {
                    val face = NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, 1.0)
                    assertTrue("DE:$code rejected", engine.matchesTownFace(source, face, townExit = code == 311))
                    assertFalse("DE:$code accepted as other town class", engine.matchesTownFace(source, face, townExit = code != 311))
                } finally {
                    source.recycle()
                }
            }
        }
    }

    @Test
    fun townTwoWindowLatencyUsesGpuAndOriginalCoordinates() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val baseline = AndroidTrafficSignModelPackLoader.load(context)
        val pack = requireNotNull(AndroidTrafficSignModelPackLoader.townTrial(context, baseline))
        val reference = requireNotNull(instrumentation.context.assets
            .open("tsr-panoramax-0906fc23.jpg").use(BitmapFactory::decodeStream))
        val source = Bitmap.createBitmap(1920, 1080, Bitmap.Config.ARGB_8888)
        val scale = minOf(source.width.toFloat() / reference.width, source.height.toFloat() / reference.height)
        val width = reference.width * scale
        val height = reference.height * scale
        val left = (source.width - width) / 2
        val top = (source.height - height) / 2
        android.graphics.Canvas(source).apply {
            drawColor(Color.rgb(114, 114, 114))
            drawBitmap(reference, null, android.graphics.RectF(left, top, left + width, top + height),
                android.graphics.Paint(android.graphics.Paint.FILTER_BITMAP_FLAG))
        }
        reference.recycle()
        val results = JSONObject()
        try {
            for (dual in listOf(false, true)) {
                val samples = JSONArray()
                AndroidLiteRtTrafficSignInferenceEngine(pack, useTwoDetectorWindows = dual).use { engine ->
                    repeat(8) { iteration ->
                        val result = engine.recognizeAllWithDiagnostics(source)
                        assertEquals("gpu", result.executionBackend)
                        assertEquals(null, result.accelerationFallbackReason)
                        assertTrue(result.detections.all { detection ->
                            val box = detection.candidate.boundingBox
                            box.x >= 0 && box.y >= 0 && box.x + box.width <= 1.000001 && box.y + box.height <= 1.000001
                        })
                        assertEquals(result.detectorProposalCount, result.classifierInvocationCount)
                        if (iteration >= 3) samples.put(JSONObject()
                            .put("total_ms", result.inferenceMs)
                            .put("detector_ms", result.detectorInferenceMs)
                            .put("classifier_ms", result.classifierInferenceMs)
                            .put("proposals", result.detectorProposalCount))
                    }
                }
                results.put(if (dual) "dual" else "single", samples)
            }
            File(context.filesDir, "reviewed142-dual-window-latency.json").writeText(JSONObject()
                .put("source_width", source.width).put("source_height", source.height)
                .put("measurements", results).toString(2))
        } finally { source.recycle() }
    }

    @Test
    fun measuredCameraCadenceCarriesRealModelResultsThroughTheFinalizedPassageForwarder() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        val sign = requireNotNull(instrumentation.context.assets
            .open("tsr-panoramax-0906fc23.jpg").use(BitmapFactory::decodeStream))
        val blank = Bitmap.createBitmap(sign.width, sign.height, Bitmap.Config.ARGB_8888).apply {
            eraseColor(Color.rgb(114, 114, 114))
        }
        val passages = mutableListOf<TrafficSignPassageEvent>()
        val displays = mutableListOf<TrafficSignDisplayObservation>()
        val outputs = mutableListOf<TrafficSignOrchestrationOutput>()
        val frames = mutableListOf<BitmapFrame>()
        val forwarder = TrafficSignFinalizedPassageForwarder(
            submitDisplayObservation = { displays += it },
            onInferenceDiagnostics = { outputs += it },
            submitFinalizedPassage = { passages += it; true },
        )
        try {
            AndroidLiteRtTrafficSignInferenceEngine(pack).use { engine ->
                val startup = AndroidTrafficSignStartupProbe.run(instrumentation.targetContext, engine, pack.modelPack)
                assertTrue("Startup reference predictions must not publish live passages", passages.isEmpty())
                assertTrue("Startup reference predictions must not publish pictograms", displays.isEmpty())
                assertTrue(outputs.isEmpty())
                val conditions = TrafficSignAnalysisConditions(speedMetersPerSecond = 10.0)
                val context = TrafficSignDetectionContext(
                    wayId = "100",
                    latitude = 0.0,
                    longitude = 0.0,
                    headingDegrees = 90.0,
                    travelDirection = TrafficSignTravelDirection.FORWARD,
                    sourceSignature = TrafficSignRuntimeSourceSignature("bundle:model-passage-fixture", null),
                    bundleSha256 = "a".repeat(64),
                    countryCode = "DE",
                    matchedWayStable = true,
                    speedMetersPerSecond = 10.0,
                )
                val orchestrator = TrafficSignRecognitionOrchestrator(
                    modelPack = pack.modelPack,
                    runtimeArtifact = pack.detectorArtifact,
                    backend = TrafficSignRecognitionBackend<BitmapFrame> { frame, completion ->
                        val result = engine.recognizeAllWithDiagnostics(frame.bitmap)
                        val detection = primaryDetection(result.detections)
                        if (frame.expectsSign) assertEquals("maxspeed:70", detection?.candidate?.rawClassId)
                        else assertTrue("Missing evidence must come from an analyzed blank image", result.detections.isEmpty())
                        completion(TrafficSignBackendResult.Recognition(
                            detection = detection,
                            displayDetections = result.detections,
                            diagnostics = TrafficSignInferenceDiagnostics(
                                inferenceMs = result.inferenceMs,
                                detectorProposalCount = result.detectorProposalCount,
                                detectorTopScore = result.detectorTopScore,
                                classifierInvocationCount = result.classifierInvocationCount,
                                classifiedDetectionCount = result.classifiedDetectionCount,
                                classifierTopScore = result.classifierTopScore,
                                primaryClassId = detection?.candidate?.rawClassId,
                                primaryScore = detection?.candidate?.rawScore,
                                executionBackend = result.executionBackend,
                                accelerationFallbackReason = result.accelerationFallbackReason,
                                detectorPreprocessingMs = result.detectorPreprocessingMs,
                                detectorInferenceMs = result.detectorInferenceMs,
                                classifierInferenceMs = result.classifierInferenceMs,
                            ),
                        ))
                    },
                    contextSnapshot = TrafficSignDetectionContextSnapshot {
                        TrafficSignDetectionContextSnapshotValue(context, 1L, true, "model-passage-fixture")
                    },
                    conditionsSnapshot = { conditions },
                    monotonicClockNanos = System::nanoTime,
                    observer = forwarder,
                    confirmationWindowMsOverride = startup.timingProfile.confirmationWindowMs,
                )
                try {
                    val interval = requireNotNull(TrafficSignAdaptiveFramePolicy.decide(conditions).minimumIntervalNanos)
                    fun analyze(bitmap: Bitmap, expectsSign: Boolean) {
                        // Use real elapsed time, including model execution; never manufacture a faster cadence.
                        // Wait after completion: capture precedes dispatch by a small amount,
                        // so sleeping to capture+interval alone can still hit the cadence gate.
                        if (frames.isNotEmpty()) TimeUnit.NANOSECONDS.sleep(interval)
                        val frame = BitmapFrame("model-frame-${frames.size}", bitmap, expectsSign)
                        frames += frame
                        val previousOutputs = outputs.size
                        assertTrue(orchestrator.submit(frame))
                        assertEquals("Every supplied evidence frame must actually be analyzed", previousOutputs + 1, outputs.size)
                        assertEquals(1, frame.releases)
                    }
                    analyze(sign, true)
                    assertTrue(passages.isEmpty())
                    analyze(sign, true)
                    assertEquals(TrafficSignRecognitionState.CONFIRMED, outputs.last().event.state)
                    assertEquals(2, outputs.last().event.candidate?.evidenceFrames)
                    assertEquals(2, displays.size)
                    assertTrue("Seeing a sign alone must not finalize its passage", passages.isEmpty())
                    analyze(blank, false)
                    assertTrue(passages.isEmpty())
                    analyze(blank, false)
                    val passage = passages.single()
                    assertEquals(70, passage.resolution.speedKmh)
                    assertEquals(2, passage.framesSeen)
                    assertEquals(2, passage.negativeFramesToCommit)
                    assertEquals(2, passage.lossEvidence.size)
                    assertEquals(70, orchestrator.effectiveSpeedKmh(null, 50))
                    assertTrue(outputs.all { it.contextIsCurrent && it.backendFailureReason == null })
                    analyze(blank, false)
                    assertEquals("Additional missing frames must not duplicate the passage", 1, passages.size)
                    val report = JSONObject()
                        .put("startupBackend", startup.executionBackend)
                        .put("confirmationWindowMs", startup.timingProfile.confirmationWindowMs)
                        .put("finalizedSpeedKmh", passage.resolution.speedKmh)
                        .put("frames", JSONArray(outputs.mapIndexed { index, output -> JSONObject()
                            .put("expectsSign", frames[index].expectsSign)
                            .put("capturedAtMonotonicNanos", frames[index].capturedAtMonotonicNanos)
                            .put("inferenceMs", output.inferenceDiagnostics?.inferenceMs)
                            .put("executionBackend", output.inferenceDiagnostics?.executionBackend)
                            .put("state", output.event.state.toString())
                            .put("passageFinalized", output.passageEvent != null)
                        }))
                    File(instrumentation.targetContext.cacheDir, "tsr-model-passage.json").writeText(report.toString())
                    Log.i("YouSpeedTSR", "Measured model-to-passage evidence: $report")
                } finally {
                    orchestrator.close()
                    assertTrue(frames.all { it.releases == 1 })
                }
            }
        } finally {
            sign.recycle()
            blank.recycle()
        }
    }

    private class BitmapFrame(
        override val frameId: String,
        val bitmap: Bitmap,
        val expectsSign: Boolean,
    ) : TrafficSignNormalizedFrameHandle {
        override val source = TrafficSignInputSource.LIVE_FRAME
        override val capturedAtUtc: Instant = Instant.now()
        override val capturedAtMonotonicNanos = System.nanoTime()
        override val widthPixels = bitmap.width
        override val heightPixels = bitmap.height
        var releases = 0
        override fun release() { releases += 1 }
    }

    @Test
    fun acceleratedRuntimePreservesCpuPredictionAndReportsMeasuredStageTiming() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        val bitmap = requireNotNull(instrumentation.context.assets
            .open("tsr-panoramax-0906fc23.jpg").use(BitmapFactory::decodeStream))
        try {
            val (cpu, cpuProbe) = AndroidLiteRtTrafficSignInferenceEngine(pack, allowGpu = false).use { engine ->
                val probe = AndroidTrafficSignStartupProbe.run(instrumentation.targetContext, engine, pack.modelPack)
                engine.recognizeAllWithDiagnostics(bitmap) to probe
            }
            assertEquals("cpu", cpu.executionBackend)
            assertEquals("cpu", cpuProbe.executionBackend)
            assertTrue(cpuProbe.warmInferenceTimesMs.all { it < cpuProbe.timingProfile.confirmationWindowMs })
            val cpuDetection = requireNotNull(primaryDetection(cpu.detections))
            assertEquals("maxspeed:70", cpuDetection.candidate.rawClassId)
            AndroidLiteRtTrafficSignInferenceEngine(pack).use { engine ->
                val probe = AndroidTrafficSignStartupProbe.run(instrumentation.targetContext, engine, pack.modelPack)
                val samples = List(3) { engine.recognizeAllWithDiagnostics(bitmap) }
                samples.forEach { sample ->
                    val detection = requireNotNull(primaryDetection(sample.detections))
                    assertEquals(cpuDetection.candidate.rawClassId, detection.candidate.rawClassId)
                    assertEquals(cpuDetection.candidate.semantic, detection.candidate.semantic)
                    assertEquals(requireNotNull(cpuDetection.candidate.proposalRawScore),
                        requireNotNull(detection.candidate.proposalRawScore), 0.05)
                    assertEquals(requireNotNull(cpuDetection.candidate.classifierRawScore),
                        requireNotNull(detection.candidate.classifierRawScore), 0.02)
                    assertTrue(sample.detectorPreprocessingMs > 0)
                    assertTrue(sample.detectorInferenceMs > 0)
                    assertTrue(sample.classifierInferenceMs > 0)
                    assertTrue("Measured runtime must fit its startup-derived confirmation allowance",
                        sample.inferenceMs < probe.timingProfile.confirmationWindowMs)
                    assertTrue(sample.inferenceMs >= sample.detectorPreprocessingMs +
                        sample.detectorInferenceMs + sample.classifierInferenceMs)
                    if (sample.executionBackend != "gpu") {
                        assertTrue(!sample.accelerationFallbackReason.isNullOrBlank())
                    }
                }
                val report = JSONObject()
                    .put("cpuInferenceMs", cpu.inferenceMs)
                    .put("cpuConfirmationWindowMs", cpuProbe.timingProfile.confirmationWindowMs)
                    .put("startupExecutionBackend", probe.executionBackend)
                    .put("startupWarmInferenceTimesMs", JSONArray(probe.warmInferenceTimesMs))
                    .put("confirmationWindowMs", probe.timingProfile.confirmationWindowMs)
                    .put("warmSamples", JSONArray(samples.map { sample -> JSONObject()
                        .put("executionBackend", sample.executionBackend)
                        .put("accelerationFallbackReason", sample.accelerationFallbackReason)
                        .put("inferenceMs", sample.inferenceMs)
                        .put("detectorPreprocessingMs", sample.detectorPreprocessingMs)
                        .put("detectorInferenceMs", sample.detectorInferenceMs)
                        .put("classifierInferenceMs", sample.classifierInferenceMs)
                    }))
                Log.i("YouSpeedTSR", "Acceleration parity and timing: $report")
                File(instrumentation.targetContext.cacheDir, "tsr-acceleration-parity.json").writeText(report.toString())
            }
        } finally {
            bitmap.recycle()
        }
    }

    @Test
    fun cityEntryReferenceReportsActualFullFrameAndCropPredictions() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        val bitmap = instrumentation.context.assets.open("tsr-city310-bernbach.jpg").use(BitmapFactory::decodeStream)
        requireNotNull(bitmap)
        val crop = Bitmap.createBitmap(bitmap, 1827, 2244, 2039 - 1827, 2392 - 2244)
        val prolixCrop = Bitmap.createBitmap(bitmap, 1795, 2221, 2071 - 1795, 2415 - 2221)
        val engine = AndroidLiteRtTrafficSignInferenceEngine(pack)
        fun detectionJson(detection: TrafficSignDetection) = JSONObject().apply {
            val candidate = detection.candidate
            put("class_id", candidate.rawClassId)
            put("class_index", pack.displayCatalog.classLabels.indexOf(candidate.rawClassId))
            put("bounding_box_xywh", JSONArray(listOf(candidate.boundingBox.x, candidate.boundingBox.y, candidate.boundingBox.width, candidate.boundingBox.height)))
            put("semantic", candidate.semantic.kind.wireValue)
            put("proposal_score", candidate.proposalRawScore)
            put("classifier_score", candidate.classifierRawScore)
            put("display_accepted", TrafficSignDisplayPolicy.accepted(listOf(detection)) != null)
        }
        try {
            val fullResult = engine.recognizeAllWithDiagnostics(bitmap)
            val full = fullResult.detections
            val classifiedCrop = engine.classifyCropForDiagnostic(crop)
            val classifiedProlixCrop = engine.classifyCropForDiagnostic(prolixCrop)
            assertEquals(142, pack.displayCatalog.classLabels.size)
            assertTrue("Current classifier supports city entry", "city:start" in pack.displayCatalog.classLabels)
            assertTrue("Current classifier supports city exit", "city:end" in pack.displayCatalog.classLabels)
            if (InstrumentationRegistry.getArguments().getString("requireGpu") == "true") {
                assertEquals("gpu", fullResult.executionBackend)
                assertEquals(null, fullResult.accelerationFallbackReason)
            }
            val evidence = JSONObject().apply {
                put("ground_truth", "User-identified DE:310 Bernbach city entry; source annotation provides generic sign bounds")
                put("fixture_sha256", "11c4eb3729167234ec35474192e301b0e74b9f4fd68582d4ccc959e80b43e9ae")
                put("model_has_city_entry_class", "city:start" in pack.displayCatalog.classLabels)
                put("class_count", pack.displayCatalog.classLabels.size)
                put("execution_backend", fullResult.executionBackend)
                put("detector_inference_ms", fullResult.detectorInferenceMs)
                put("classifier_inference_ms", fullResult.classifierInferenceMs)
                put("evaluation_scope", "Historical diagnostic fixture, not fresh held-out accuracy or warmed latency benchmark")
                put("classifier_artifact_sha256", pack.classifierArtifact.sha256)
                put("detector_artifact_sha256", pack.detectorArtifact.sha256)
                put("crop_probe_note", "Crop probes call the classifier directly; proposal_score=1 is synthetic admission, not a detector result.")
                put("full_frame", JSONArray(full.map(::detectionJson)))
                put("annotation_crop_classifier", classifiedCrop?.let(::detectionJson) ?: JSONObject.NULL)
                put("prolix_15_percent_crop_classifier", classifiedProlixCrop?.let(::detectionJson) ?: JSONObject.NULL)
                put("prolix_crop_xyxy", JSONArray(listOf(1795, 2221, 2071, 2415)))
                put("crop_xyxy", JSONArray(listOf(1827, 2244, 2039, 2392)))
            }
            File(instrumentation.targetContext.getExternalFilesDir(null), "tsr-city310-probe.json").writeText(evidence.toString(2))
            Log.i("YouSpeedTSRProbe", evidence.toString())
        } finally {
            engine.close()
            crop.recycle()
            prolixCrop.recycle()
            bitmap.recycle()
        }
    }

    @Test
    fun verifiedLiteRtPackRecognizesPinnedPanoramaxFixture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        assertEquals("de-youspeed-reviewed142-v1", pack.modelPack.packId)
        assertEquals(142, pack.modelPack.classMapping.size)
        assertEquals("bus:stop", pack.modelPack.classMapping[136].classId)
        assertEquals("supplementary:plate", pack.modelPack.classMapping[137].classId)
        val bitmap = instrumentation.context.assets
            .open("tsr-panoramax-0906fc23.jpg")
            .use(BitmapFactory::decodeStream)
        assertNotNull(bitmap)
        val engine = AndroidLiteRtTrafficSignInferenceEngine(pack)

        try {
            val result = engine.recognizeAllWithDiagnostics(bitmap)
            if (InstrumentationRegistry.getArguments().getString("requireGpu") == "true") {
                assertEquals("gpu", result.executionBackend)
                assertEquals(null, result.accelerationFallbackReason)
            }
            val detection = requireNotNull(primaryDetection(result.detections))
            Log.i("YouSpeedTSR", "DE142 packaged model verified: backend=${result.executionBackend}, " +
                "classifierMs=${result.classifierInferenceMs}, class=${detection.candidate.rawClassId}")
            assertEquals("maxspeed:70", detection.candidate.rawClassId)
            assertEquals(TrafficSignSemanticKind.MAXIMUM_SPEED, detection.candidate.semantic.kind)
            assertEquals(70, detection.candidate.semantic.value)
            assertTrue(requireNotNull(detection.candidate.proposalRawScore) > 0.80)
            assertTrue(requireNotNull(detection.candidate.classifierRawScore) > 0.95)
            assertTrue(detection.candidate.restrictions.isEmpty())
            assertEquals(TrafficSignConditionState.NONE, detection.candidate.conditionState)
        } finally {
            engine.close()
            bitmap.recycle()
        }
    }
}

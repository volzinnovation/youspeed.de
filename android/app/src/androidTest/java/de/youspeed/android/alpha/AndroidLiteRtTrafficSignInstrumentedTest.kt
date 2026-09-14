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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@LargeTest
@RunWith(AndroidJUnit4::class)
class AndroidLiteRtTrafficSignInstrumentedTest {
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
            val full = engine.recognizeAll(bitmap)
            val classifiedCrop = engine.classifyCropForDiagnostic(crop)
            val classifiedProlixCrop = engine.classifyCropForDiagnostic(prolixCrop)
            assertTrue("Pinned classifier has no city-entry class", pack.displayCatalog.classLabels.none { it.contains("310") || it.contains("city") })
            assertTrue(full.none { it.candidate.semantic.kind == TrafficSignSemanticKind.CITY_ENTRY })
            assertTrue(classifiedCrop?.candidate?.semantic?.kind != TrafficSignSemanticKind.CITY_ENTRY)
            val evidence = JSONObject().apply {
                put("ground_truth", "User-identified DE:310 Bernbach city entry; source annotation provides generic sign bounds")
                put("fixture_sha256", "11c4eb3729167234ec35474192e301b0e74b9f4fd68582d4ccc959e80b43e9ae")
                put("model_has_city_entry_class", false)
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
        val bitmap = instrumentation.context.assets
            .open("tsr-panoramax-0906fc23.jpg")
            .use(BitmapFactory::decodeStream)
        assertNotNull(bitmap)
        val engine = AndroidLiteRtTrafficSignInferenceEngine(pack)

        try {
            val detection = requireNotNull(engine.recognize(bitmap))
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

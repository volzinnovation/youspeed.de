package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.PowerManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.Locale
import java.util.zip.ZipFile
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in drive replay of the installed debug APK's actual German detector and classifier. */
@RunWith(AndroidJUnit4::class)
class FinalTownDriveReplayInstrumentedTest {
    @Test fun installedPolicyOnRecordedDrive() {
        val args = InstrumentationRegistry.getArguments()
        val name = args.getString("replayCache")
        assumeTrue("Provide the staged drive cache", name != null)
        require(name != null && name.matches(Regex("town-drive-[a-zA-Z0-9_-]+")))
        val frames = requireNotNull(args.getString("frames")).toInt()
        require(frames > 0)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cache = File(context.cacheDir, name)
        val output = File(cache, "result.jsonl")
        check(output.createNewFile()) { "Replay result already exists in this cache" }
        val baseline = AndroidTrafficSignModelPackLoader.load(context)
        val pack = requireNotNull(AndroidTrafficSignModelPackLoader.townTrial(context, baseline))
        require(pack.trialDetectorThreshold == GermanTownTrialOperatingPoint.DETECTOR_FLOOR)
        val thermal = requireNotNull(context.getSystemService(PowerManager::class.java))
        fun newFusion() = TrafficSignFusionEngine(pack.modelPack.thresholds, pack.modelPack.calibration.runtimeOutput,
            pack.modelPack.classMapping.associate { it.classId to it.threshold })
        val fusion = newFusion()
        val strictFusion = newFusion()

        ZipFile(File(cache, "frames.zip")).use { archive ->
            fun load(i: Int): Bitmap {
                val entry = requireNotNull(archive.getEntry("%04d.jpg".format(Locale.US, i)))
                return archive.getInputStream(entry).use { checkNotNull(BitmapFactory.decodeStream(it)) }
                    .also { require(it.width == 1920 && it.height == 1080) }
            }
            AndroidLiteRtTrafficSignInferenceEngine(pack).use { engine ->
                val warmup = load(0)
                try {
                    repeat(6) {
                        val s = engine.recognizeAllWithDiagnostics(warmup)
                        check(s.executionBackend == "gpu" && s.accelerationFallbackReason == null)
                    }
                } finally { warmup.recycle() }
                output.bufferedWriter().use { writer ->
                    for (i in 0 until frames) {
                        val image = load(i)
                        try {
                            val s = engine.recognizeAllWithDiagnostics(image)
                            check(s.executionBackend == "gpu" && s.accelerationFallbackReason == null)
                            val fused = fusion.observe(primaryDetection(s.detections), i * 500L)
                            val display = TrafficSignDisplayPolicy.accepted(s.detections)
                            val strict = s.detections.filter { (it.candidate.proposalRawScore ?: 0.0) >=
                                GermanTownTrialOperatingPoint.PREVIOUS_DETECTOR_FLOOR }
                            val strictFused = strictFusion.observe(primaryDetection(strict), i * 500L)
                            val strictDisplay = TrafficSignDisplayPolicy.accepted(strict)
                            val towns = JSONArray()
                            val detections = JSONArray()
                            for (d in s.detections) {
                                val c = d.candidate
                                val b = c.boundingBox
                                val row = JSONObject().put("label", c.rawClassId).put("score", c.rawScore)
                                    .put("detector", c.proposalRawScore).put("classifier", c.classifierRawScore)
                                    .put("xyxy", JSONArray(listOf(b.x * image.width, b.y * image.height,
                                        (b.x + b.width) * image.width, (b.y + b.height) * image.height)))
                                detections.put(row)
                                if (c.rawClassId == "city:start" || c.rawClassId == "city:end") towns.put(row)
                            }
                            val data = JSONObject().put("frame", i).put("threshold", pack.trialDetectorThreshold)
                                .put("order", 0).put("displayLabel", display?.rawClassId ?: JSONObject.NULL)
                                .put("fusionLabel", fused.candidate?.rawClassId ?: JSONObject.NULL)
                                .put("fusionState", fused.state.wireValue)
                                .put("strictDisplayLabel", strictDisplay?.rawClassId ?: JSONObject.NULL)
                                .put("strictFusionLabel", strictFused.candidate?.rawClassId ?: JSONObject.NULL)
                                .put("strictFusionState", strictFused.state.wireValue)
                                .put("lowBandExitChecks", s.lowBandExitChecks).put("lowBandExitRejects", s.lowBandExitRejects)
                                .put("elapsedMs", s.inferenceMs).put("detectorMs", s.detectorInferenceMs)
                                .put("preprocessingMs", s.detectorPreprocessingMs).put("classifierMs", s.classifierInferenceMs)
                                .put("calls", s.classifierInvocationCount).put("thermal", thermal.currentThermalStatus)
                                .put("towns", towns).put("detections", detections).put("nativeRejectedExits", JSONArray())
                            writer.write(data.toString())
                            writer.newLine()
                            writer.flush()
                        } finally { image.recycle() }
                    }
                }
            }
        }
    }

    @Test fun sameVerifierPairedTiming() {
        val args = InstrumentationRegistry.getArguments()
        val name = args.getString("replayCache")
        assumeTrue("Provide the staged drive cache", name != null)
        require(name != null && name.matches(Regex("town-drive-[a-zA-Z0-9_-]+")))
        val frames = requireNotNull(args.getString("frames")).toInt()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cache = File(context.cacheDir, name)
        val output = File(cache, "same-verifier-timing.jsonl")
        check(output.createNewFile())
        val baseline = AndroidTrafficSignModelPackLoader.load(context)
        val final = requireNotNull(AndroidTrafficSignModelPackLoader.townTrial(context, baseline))
        val strict = final.copy(trialDetectorThreshold = GermanTownTrialOperatingPoint.PREVIOUS_DETECTOR_FLOOR)
        val thermal = requireNotNull(context.getSystemService(PowerManager::class.java))
        ZipFile(File(cache, "frames.zip")).use { archive ->
            fun load(i: Int): Bitmap = archive.getInputStream(archive.getEntry("%04d.jpg".format(Locale.US, i))).use {
                requireNotNull(BitmapFactory.decodeStream(it))
            }.also { require(it.width == 1920 && it.height == 1080) }
            AndroidLiteRtTrafficSignInferenceEngine(strict).use { strictEngine ->
                AndroidLiteRtTrafficSignInferenceEngine(final).use { finalEngine ->
                    fun pass(image: Bitmap, arm: Int) = (if (arm == 0) strictEngine else finalEngine)
                        .recognizeAllWithDiagnostics(image).also {
                            check(it.executionBackend == "gpu" && it.accelerationFallbackReason == null)
                        }
                    val warmup = load(5)
                    try { repeat(12) { pass(warmup, it % 2) } } finally { warmup.recycle() }
                    output.bufferedWriter().use { writer ->
                        for ((pair, i) in (5 until frames step 12).withIndex()) {
                            val image = load(i)
                            try {
                                for (order in 0..1) {
                                    val arm = (pair + order) % 2
                                    val s = pass(image, arm)
                                    val floor = if (arm == 0) strict.trialDetectorThreshold else final.trialDetectorThreshold
                                    val row = JSONObject().put("frame", i).put("threshold", floor).put("order", order)
                                        .put("elapsedMs", s.inferenceMs).put("calls", s.classifierInvocationCount)
                                        .put("preprocessingMs", s.detectorPreprocessingMs).put("detectorMs", s.detectorInferenceMs)
                                        .put("classifierMs", s.classifierInferenceMs).put("thermal", thermal.currentThermalStatus)
                                        .put("lowBandExitChecks", s.lowBandExitChecks).put("lowBandExitRejects", s.lowBandExitRejects)
                                        .put("displayLabel", TrafficSignDisplayPolicy.accepted(s.detections)?.rawClassId ?: JSONObject.NULL)
                                    writer.write(row.toString())
                                    writer.newLine()
                                }
                                writer.flush()
                            } finally { image.recycle() }
                        }
                    }
                }
            }
        }
    }
}

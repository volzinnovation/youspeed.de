package de.youspeed.android.alpha

import android.graphics.BitmapFactory
import android.os.PowerManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.gpu.GpuDelegate
import org.tensorflow.lite.gpu.GpuDelegateFactory
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Device-only paired inference. Model input, frame order and decode are shared with the iPhone replay. */
@RunWith(AndroidJUnit4::class)
class TownDetectorTrialInstrumentedTest {
    @Test
    fun replayOnGpu() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val replay = File(context.filesDir, "town-trial-replay")
        val manifest = JSONArray(File(replay, "frames.json").readText())
        require(manifest.length() > 0)
        val frames = (0 until manifest.length()).map(manifest::getJSONObject)
        val baseline = AndroidTrafficSignModelPackLoader.load(context)
        val candidate = checkNotNull(AndroidTrafficSignModelPackLoader.townTrial(context, baseline))
        val thermal = checkNotNull(context.getSystemService(PowerManager::class.java))
        val results = JSONObject()
        val size = 1024
        val pixels = IntArray(size * size)
        val input = ByteBuffer.allocateDirect(size * size * 3 * 4).order(ByteOrder.nativeOrder())
        val scores = FloatArray(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
        val output = ByteBuffer.allocateDirect(scores.size * 4).order(ByteOrder.nativeOrder())

        for ((name, pack, threshold) in listOf(Triple("sgblur", baseline, 0.25), Triple("town", candidate, 0.840783))) {
            val thermalStart = thermal.currentThermalStatus
            val rows = JSONArray()
            val delegate = GpuDelegate(GpuDelegateFactory.Options().setPrecisionLossAllowed(true))
            try {
                Interpreter(pack.detectorModel.duplicate(), Interpreter.Options().addDelegate(delegate)).use { model ->
                    for ((index, frame) in (frames.take(5) + frames).withIndex()) {
                        val image = checkNotNull(BitmapFactory.decodeFile(File(replay, frame.getString("file")).path))
                        require(image.width == size && image.height == size)
                        image.getPixels(pixels, 0, size, 0, 0, size, size)
                        image.recycle()
                        input.clear()
                        for (value in pixels) {
                            input.putFloat((value shr 16 and 255) / 255f)
                            input.putFloat((value shr 8 and 255) / 255f)
                            input.putFloat((value and 255) / 255f)
                        }
                        input.rewind()
                        output.clear()
                        val start = System.nanoTime()
                        model.run(input, output)
                        val milliseconds = (System.nanoTime() - start) / 1_000_000.0
                        if (index < minOf(frames.size, 5)) continue
                        output.rewind()
                        output.asFloatBuffer().get(scores)
                        val proposals = AndroidYoloSignDecoder.decode(scores, size, size, size, threshold)
                        val boxes = JSONArray()
                        for (proposal in proposals) {
                            val box = proposal.box
                            boxes.put(JSONArray(listOf(proposal.score.toDouble(), box.x, box.y, box.x + box.width, box.y + box.height)))
                        }
                        rows.put(JSONObject().put("id", frame.getString("id")).put("ms", milliseconds).put("boxes", boxes))
                    }
                }
            } finally {
                delegate.close()
            }
            results.put(name, JSONObject().put("threshold", threshold).put("computeUnits", "LiteRT GPU delegate")
                .put("thermalStart", thermalStart).put("thermalEnd", thermal.currentThermalStatus).put("frames", rows))
        }
        File(context.filesDir, "town-trial-results.json").writeText(results.toString())
    }
}

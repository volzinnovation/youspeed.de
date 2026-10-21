package de.youspeed.android.alpha

import android.graphics.BitmapFactory
import android.graphics.Bitmap
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TrafficSignPlateRegressionTest {
    @Test fun same32NativeCropsWithBundledMLKit() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        assertTrue(context.packageName.endsWith(".testhost"))
        val assets = instrumentation.context.assets
        val rows = JSONArray(assets.open("tsr-ocr-32/manifest.json").bufferedReader().use { it.readText() })
        assertEquals(32, rows.length())
        val warm = CountDownLatch(1)
        AndroidTrafficSignSupplementaryOCR.warmUp(context) { warm.countDown() }
        assertTrue(warm.await(30, TimeUnit.SECONDS))
        val baselineClient = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        val results = JSONArray()
        var failure: String? = null
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i); val id = row.getString("crop_id"); val expected = row.getJSONObject("expected")
            val bitmap = assets.open("tsr-ocr-32/$id.png").use { requireNotNull(BitmapFactory.decodeStream(it)) }
            val sourceWidth = bitmap.width; val sourceHeight = bitmap.height
            val baselineStart = System.nanoTime()
            val lower = Bitmap.createBitmap(bitmap,0,bitmap.height/2,bitmap.width,bitmap.height-bitmap.height/2)
            val baseline = try { Tasks.await(baselineClient.process(InputImage.fromBitmap(lower,0))).text } finally { lower.recycle() }
            val baselineMs = (System.nanoTime()-baselineStart)/1e6
            val done = CountDownLatch(1); var read: TrafficSignSupplementaryTextAnnotation? = null
            val candidate = TrafficSignCandidate("maxspeed:30", "30", TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED,30,"km/h"),
                .99,null,NormalizedTrafficSignBoundingBox(0.0,0.0,1.0,.5),evidenceFrames=2)
            val now = java.time.Instant.now()
            val request = TrafficSignSupplementaryOCRRequest(candidate,"regression-$id","frame-$id",now,now,TrafficSignSupplementaryScope(1,"regression"))
            val started = System.nanoTime()
            AndroidTrafficSignSupplementaryOCR.fromBitmap(bitmap).recognize(request) { read = it; done.countDown() }
            bitmap.recycle() // The production camera releases the source immediately.
            assertTrue(done.await(30, TimeUnit.SECONDS))
            val annotation = requireNotNull(read)
            val result = AndroidTrafficSignSupplementaryOCR.Read(annotation.rawText,
                annotation.ocrBoundingBox?.let { TrafficSignPlateRect(kotlin.math.round(it.x*sourceWidth).toInt(),kotlin.math.round(it.y*sourceHeight).toInt(),kotlin.math.round(it.width*sourceWidth).toInt(),kotlin.math.round(it.height*sourceHeight).toInt()) },
                annotation.qualityDecision,annotation.ocrPasses,annotation.status == TrafficSignSupplementaryOCRStatus.FAILED)
            val negative = expected.getString("kind") != "text" || expected.optBoolean("small_ambiguous")
            if (result.decision == "accepted" && TrafficSignOCRQuality.comparison(result.raw.orEmpty()) !=
                TrafficSignOCRQuality.comparison(expected.optString("expected_text"))) failure = "Incorrect accepted read: $id ${result.raw}"
            if (negative && result.decision == "accepted") failure = "False positive: $id ${result.raw}"
            if (id in setOf("de47d0de-884f-5638-a31d-ea0dede1b643", "fabf2a14-f2c3-539f-9bd4-3385c40f0c0d") &&
                (result.decision != "accepted" || TrafficSignSupplementaryTimeWindow.parse(result.raw.orEmpty())?.displayText != "22–6 h")) failure = "Missed known plate: $id ${result.raw} ${result.decision}"
            if (id == "7444ffc9-d750-5b2b-bf8e-a39951ad9f6a" && result.decision == "accepted") failure = "Clipped clause must not be presented"
            results.put(JSONObject().put("crop_id",id).put("baseline_text",baseline).put("baseline_ms",baselineMs).put("raw_text",result.raw ?: JSONObject.NULL)
                .put("status",if(result.failed) "failed" else if(result.decision == "accepted") "read" else "no_text")
                .put("decision",result.decision).put("plate",result.rect?.let { JSONArray(listOf(it.x,it.y,it.width,it.height)) } ?: JSONObject.NULL)
                .put("passes",JSONArray(result.passes.map { JSONObject().put("text",it.text).put("confidence",it.confidence).put("scale",it.scale).put("uncovered_ink",it.uncoveredInk) }))
                .put("milliseconds",(System.nanoTime()-started)/1e6))
        }
        File(context.filesDir,"ocr-32-results.json").writeText(results.toString(2))
        if ((0 until results.length()).count { results.getJSONObject(it).getString("status") == "read" } < 18) failure = "Readable coverage regressed below 18/28"
        baselineClient.close()
        assertNull(failure, failure)
    }
}

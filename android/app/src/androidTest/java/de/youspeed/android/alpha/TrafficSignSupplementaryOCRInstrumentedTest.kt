package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Bundle
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Fixture is injected into the isolated test host, never committed or read from the user's app. */
@RunWith(AndroidJUnit4::class)
class TrafficSignSupplementaryOCRInstrumentedTest {
    @Test fun primaryZoneProofRejectsInformationPanelsAndMismatchedLimits() {
        val candidate = TrafficSignCandidate("zone:30", "30 ZONE",
            TrafficSignSemantic(TrafficSignSemanticKind.ZONE_START, 30, "km/h"), .99, null,
            NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, 1.0), evidenceFrames = 2)
        fun panel(number: String, label: String): Bitmap = Bitmap.createBitmap(400, 400, Bitmap.Config.ARGB_8888).apply {
            eraseColor(android.graphics.Color.WHITE)
            val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
                color = android.graphics.Color.BLACK; textSize = 70f; textAlign = android.graphics.Paint.Align.CENTER
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            }
            android.graphics.Canvas(this).apply { drawText(number, 200f, 150f, paint); drawText(label, 200f, 280f, paint) }
        }
        // Warm the separate bounded primary-panel reader, then verify actual OCR output.
        panel("30", "ZONE").let { image ->
            try {
                val deadline = android.os.SystemClock.uptimeMillis() + 10_000
                var verified = false
                while (!verified && android.os.SystemClock.uptimeMillis() < deadline) {
                    verified = AndroidTrafficSignSupplementaryOCR.verifiesZone(image, candidate)
                    if (!verified) android.os.SystemClock.sleep(100)
                }
                assertTrue("Bundled zone proof must initialize and read the primary panel", verified)
            } finally { image.recycle() }
        }
        for ((number, label) in listOf("30" to "ZONE", "20" to "ZONE", "40" to "Kurort", "70" to "GEFAHR")) {
            val image = panel(number, label)
            try { assertEquals("$number $label", number == "30" && label == "ZONE",
                AndroidTrafficSignSupplementaryOCR.verifiesZone(image, candidate)) }
            finally { image.recycle() }
        }
    }
    private fun report(fixture: String, annotation: TrafficSignSupplementaryTextAnnotation, started: Long) {
        InstrumentationRegistry.getInstrumentation().sendStatus(0, Bundle().apply {
            putString("ocr_fixture", fixture)
            putString("ocr_raw_text", annotation.rawText)
            putString("ocr_display_text", annotation.text)
            putString("ocr_status", annotation.status.name)
            putString("ocr_engine", annotation.engine)
            putString("ocr_model_version", annotation.modelVersion)
            putDouble("ocr_completion_ms", (System.nanoTime() - started) / 1e6)
        })
    }
    @Test fun warmedBundledRecognizerReadsNativeBottomHalfOfInjectedFixture() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertTrue("Run only with -PyouspeedIsolatedTests=true", context.packageName.endsWith(".testhost"))
        val fixture = File(context.filesDir, "supplementary-ocr-fixture.png")
        assertTrue("Inject the private source into this isolated test host's files directory", fixture.isFile)
        val source = requireNotNull(BitmapFactory.decodeFile(fixture.absolutePath))
        try {
            assertEquals(136, source.width)
            assertEquals(230, source.height)
            val warm = CountDownLatch(1)
            var warmed = false
            AndroidTrafficSignSupplementaryOCR.warmUp(context) { warmed = it; warm.countDown() }
            assertTrue("Bundled OCR must initialize without downloading a model", warm.await(30, TimeUnit.SECONDS))
            assertTrue(warmed)
            val rect = requireNotNull(supplementaryTextPixelRect(
                NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, .5), source.width, source.height))
            assertEquals(TrafficSignSupplementaryPixelRect(0, 115, 136, 115), rect)
            val complete = CountDownLatch(1)
            var annotation: TrafficSignSupplementaryTextAnnotation? = null
            val candidate = TrafficSignCandidate("maxspeed:30", "30",
                TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h"), .99, null,
                NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, .5), evidenceFrames = 2)
            val now = java.time.Instant.now()
            val request = TrafficSignSupplementaryOCRRequest(candidate, "confirmed-physical", "confirmed-second-frame",
                now, now.minusMillis(201), TrafficSignSupplementaryScope(1, "isolated-fixture"))
            val started = System.nanoTime()
            AndroidTrafficSignSupplementaryOCR.fromBitmap(source).recognize(request) { annotation = it; complete.countDown() }
            // Production releases the source after this callback returns. The admitted OCR crop
            // must remain valid independently and no second OCR read is needed for confirmation.
            source.recycle()
            assertTrue(complete.await(10, TimeUnit.SECONDS))
            val result = requireNotNull(annotation)
            report("private-native-136x115", result, started)
            assertEquals(TrafficSignSupplementaryOCRStatus.READ, result.status)
            assertEquals("22-6h", result.rawText?.replace(" ", "")?.trim())
            assertEquals("22–6 h", result.text)
            assertEquals("confirmed-second-frame", result.frameId)
            val plateBox = requireNotNull(result.ocrBoundingBox)
            assertTrue(plateBox.y >= .5 && plateBox.x >= 0)
            assertTrue(plateBox.x + plateBox.width <= 1.000001 && plateBox.y + plateBox.height <= 1.000001)
            assertTrue(plateBox.width * 136 >= 48 && plateBox.height * 230 >= 32)
            Log.i("SupplementaryOCRTest", "source-independent=true input=136x115 native=true raw=${result.rawText} completionMs=${(System.nanoTime() - started) / 1e6}")
        } finally { if (!source.isRecycled) source.recycle() }
    }

    @Test fun bundledRecognizerReadsPublicWeekdayPlateAndPreparesFrenchAndItalianLocally() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertTrue(context.packageName.endsWith(".testhost"))
        val source = requireNotNull(BitmapFactory.decodeFile(File(context.filesDir, "supplementary-ocr-public-fixture.png").absolutePath))
        assertEquals(384, source.width); assertEquals(754, source.height)
        val done = CountDownLatch(1)
        val now = java.time.Instant.now()
        val candidate = TrafficSignCandidate("hazard:school", "School", TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN),
            .99, null, NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, .5), evidenceFrames = 2)
        val request = TrafficSignSupplementaryOCRRequest(candidate, "public-physical", "later-clearer-view", now,
            now.minusMillis(600), TrafficSignSupplementaryScope(1, "public-fixture"), attemptNumber = 2)
        var result: TrafficSignSupplementaryTextAnnotation? = null
        val started = System.nanoTime()
        AndroidTrafficSignSupplementaryOCR.fromBitmap(source).recognize(request) { result = it; done.countDown() }
        source.recycle()
        assertTrue(done.await(20, TimeUnit.SECONDS))
        val annotation = requireNotNull(result)
        report("public-native-384x377", annotation, started)
        Log.i("SupplementaryOCRTest", "public-weekday input=384x377 native=true raw=${annotation.rawText} display=${annotation.text} completionMs=${(System.nanoTime() - started) / 1e6}")
        assertEquals(TrafficSignSupplementaryOCRStatus.READ, annotation.status)
        assertTrue(annotation.rawText.orEmpty().contains("Mo", true))
        assertTrue(annotation.rawText.orEmpty().contains("Fr", true))
        assertNull(annotation.primarySpeedKmh)
        TrafficSignOCRLanguageContext.configure("CH")
        try {
            TrafficSignOCRLanguageContext.prepare("sauf riverains")
            assertEquals("fr", TrafficSignOCRLanguageContext.speechLocale("sauf riverains")?.language)
            TrafficSignOCRLanguageContext.prepare("eccetto scuola")
            assertEquals("it", TrafficSignOCRLanguageContext.speechLocale("eccetto scuola")?.language)
        } finally { TrafficSignOCRLanguageContext.configure("DE") }
    }
}

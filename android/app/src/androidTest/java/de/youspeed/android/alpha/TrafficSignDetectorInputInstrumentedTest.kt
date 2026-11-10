package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TrafficSignDetectorInputInstrumentedTest {
    @Test fun collectionCropUsesFullResolutionCoordinates() {
        val source = Bitmap.createBitmap(3840, 2160, Bitmap.Config.ARGB_8888)
        source.eraseColor(Color.GREEN)
        source.setHasAlpha(false)
        try {
            val crop = SignCollectionCrop.generate(source,
                mapOf("x" to 0.0, "y" to 0.25, "width" to 0.25, "height" to 0.125), hashSource = false)
            assertEquals(3840, crop.sourceWidth)
            assertEquals(2160, crop.sourceHeight)
            assertEquals(0, crop.geometry.actual[0])
            assertEquals(960, crop.geometry.actual[2])
            assertEquals(540, crop.geometry.actual[3] - crop.geometry.actual[1])
        } finally { source.recycle() }
    }

    @Test fun fullFrameRecognizesTheBundledReferenceSign() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val pack = AndroidTrafficSignModelPackLoader.load(context, "DE")
        val source = requireNotNull(context.assets.open(AndroidTrafficSignStartupProbe.REFERENCE_ASSET)
            .use(BitmapFactory::decodeStream))
        try {
            AndroidLiteRtTrafficSignInferenceEngine(pack, allowGpu = false).use { engine ->
                val result = engine.recognizeAllWithDiagnostics(source)
                assertEquals(source.width, result.sourceWidthPixels)
                assertEquals(source.height, result.sourceHeightPixels)
                assertTrue("Expected 70 km/h classification from the full frame", result.detections.any {
                    it.candidate.rawClassId == "maxspeed:70" && it.candidate.rawScore >= pack.modelPack.thresholds.confirmed
                })
            }
        } finally { source.recycle() }
    }

    @Test fun fullFrameFitsAndReusesItsBuffer() {
        val source = Bitmap.createBitmap(3840, 2160, Bitmap.Config.ARGB_8888)
        Canvas(source).apply {
            drawColor(Color.RED)
            drawRect(1680f, 0f, 2760f, 2160f, Paint().apply { color = Color.GREEN })
            drawRect(2760f, 0f, 3840f, 2160f, Paint().apply { color = Color.BLUE })
            drawRect(0f, 0f, 3840f, 216f, Paint().apply { color = Color.YELLOW })
        }
        try {
            AndroidTrafficSignDetectorInput().use { input ->
                input.prepare(source)
                val window = input.bitmap
                assertEquals(1024, window.width)
                assertEquals(1024, window.height)
                assertEquals(Color.RED, window.getPixel(100, 500))
                assertEquals(Color.GREEN, window.getPixel(550, 500))
                assertEquals(Color.BLUE, window.getPixel(900, 500))
                assertEquals(Color.YELLOW, window.getPixel(100, 240))
                assertEquals(Color.RED, window.getPixel(100, 780))
                assertEquals(Color.rgb(114, 114, 114), window.getPixel(100, 0))
                assertEquals(Color.rgb(114, 114, 114), window.getPixel(100, 1023))
                input.prepare(source)
                assertSame(window, input.bitmap)
                assertEquals(3840, source.width)
            }
        } finally { source.recycle() }
    }

    @Test fun portraitPaddingClearsThePreviousFrame() {
        val source = Bitmap.createBitmap(640, 1280, Bitmap.Config.ARGB_8888)
        source.eraseColor(Color.GREEN)
        try {
            AndroidTrafficSignDetectorInput().use { input ->
                input.bitmap.eraseColor(Color.RED)
                input.prepare(source)
                assertEquals(Color.rgb(114, 114, 114), input.bitmap.getPixel(100, 500))
                assertEquals(Color.GREEN, input.bitmap.getPixel(600, 500))
                assertEquals(Color.rgb(114, 114, 114), input.bitmap.getPixel(900, 500))
            }
        } finally { source.recycle() }
    }
}

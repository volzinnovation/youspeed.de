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
    @Test fun uploadWindowKeepsNativePixelsWithoutScaling() {
        val source = Bitmap.createBitmap(3840, 2160, Bitmap.Config.ARGB_8888)
        source.eraseColor(Color.GREEN)
        for (y in 0 until source.height) source.setPixel(3839, y, Color.RED)
        val native = AndroidTrafficSignDetectorInput.nativeWindow(source)
        try {
            assertEquals(2160, native.width)
            assertEquals(2160, native.height)
            assertEquals(Color.GREEN, native.getPixel(2158, 500))
            assertEquals(Color.RED, native.getPixel(2159, 500))
            source.eraseColor(Color.BLUE)
            assertEquals(Color.RED, native.getPixel(2159, 500))
            val crop = SignCollectionCrop.generate(native,
                mapOf("x" to 0.5, "y" to 0.25, "width" to 0.25, "height" to 0.125), hashSource = false)
            assertEquals(540, crop.geometry.actual[2] - crop.geometry.actual[0])
            assertEquals(540, crop.geometry.actual[3] - crop.geometry.actual[1])
        } finally { native.recycle(); source.recycle() }
    }

    @Test fun croppedWindowStillRecognizesTheBundledReferenceSign() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val pack = AndroidTrafficSignModelPackLoader.load(context, "DE")
        val source = requireNotNull(context.assets.open(AndroidTrafficSignStartupProbe.REFERENCE_ASSET)
            .use(BitmapFactory::decodeStream))
        try {
            AndroidLiteRtTrafficSignInferenceEngine(pack, allowGpu = false).use { engine ->
                val result = engine.recognizeAllWithDiagnostics(source)
                assertEquals(1024, result.sourceWidthPixels)
                assertEquals(1024, result.sourceHeightPixels)
                assertTrue("Expected 70 km/h classification from the fixed rightmost window", result.detections.any {
                    it.candidate.rawClassId == "maxspeed:70" && it.candidate.rawScore >= pack.modelPack.thresholds.confirmed
                })
            }
        } finally { source.recycle() }
    }

    @Test fun rightmostWindowPreservesHeightAndReusesItsBuffer() {
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
                assertEquals(Color.GREEN, window.getPixel(100, 500))
                assertEquals(Color.BLUE, window.getPixel(900, 500))
                assertEquals(Color.YELLOW, window.getPixel(100, 0))
                assertEquals(Color.GREEN, window.getPixel(100, 1023))
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
            }
        } finally { source.recycle() }
    }
}

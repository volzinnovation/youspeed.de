package de.youspeed.android.alpha

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import com.sun.jna.NativeMappedConverter
import java.io.File
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.vosk.Model
import org.vosk.Recognizer

@LargeTest
@RunWith(AndroidJUnit4::class)
class VoskNativeRuntimeInstrumentedTest {
    @Test
    fun bundledModelInitializesJnaAndRecognizesSyntheticSilence() {
        // JNA creates NativeMapped values reflectively. R8 must retain Model().
        val emptyModel = NativeMappedConverter.getInstance(Model::class.java).defaultValue()
        assertTrue(emptyModel is Model)
        assertNull((emptyModel as Model).pointer)

        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val rootDir = File(context.cacheDir, "vosk-native-smoke-${UUID.randomUUID()}")
        assertTrue(rootDir.mkdirs())
        try {
            val handle = BundledVoskModelStore(context, rootDir).prepareModel()
            handle.model.use { model ->
                assertNotNull(model.pointer)
                assertTrue(handle.assetVersion.isNotBlank())

                // Cover both the NativeMapped Model argument and the app's grammar path.
                Recognizer(model, SAMPLE_RATE).use(::assertSilenceResult)
                Recognizer(model, SAMPLE_RATE, SpeedCaptureSpeech.voskGrammarJson)
                    .use(::assertSilenceResult)
            }
        } finally {
            rootDir.deleteRecursively()
        }
    }

    private fun assertSilenceResult(recognizer: Recognizer) {
        // One second of PCM avoids microphone permission, hardware, and recorded speech.
        val silence = ShortArray(SAMPLE_RATE.toInt())
        recognizer.acceptWaveForm(silence, silence.size)
        val result = JSONObject(recognizer.finalResult)
        assertTrue("Vosk must return a final transcript object", result.has("text"))
        assertEquals("", result.getString("text").trim())
    }

    private companion object {
        const val SAMPLE_RATE = 16_000f
    }
}

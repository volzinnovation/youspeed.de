package de.youspeed.android.alpha

import android.graphics.BitmapFactory
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

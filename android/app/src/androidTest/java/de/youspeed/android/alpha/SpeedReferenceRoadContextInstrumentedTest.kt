package de.youspeed.android.alpha

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SpeedReferenceRoadContextInstrumentedTest {
    private fun model(): SpeedLimitReferenceModel {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertTrue("Requires the isolated test host", context.packageName.endsWith(".testhost"))
        return SpeedLimitReferenceModel.load { context.assets.open("speed-limit-reference/$it").use { stream -> stream.readBytes() } }
    }

    @Test fun recordedWayOrientationChangesKeepTheFrozenEightSecondConfirmation() {
        for (relationOnly in listOf(false, true)) {
            var now = 0.0
            val runtime = SpeedReferenceRuntime(model()) { now }
            assertEquals("1.1.0:497e157de2d04ed067897ecc9abde29ecf304a4147c9897b26e71d5c5fc0fcd9", runtime.policyIdentity)
            runtime.context("old", "ref:old", emptySet(), "forward", true)
            runtime.bundle("old-map", SpeedReferenceValue("numeric", 70))
            val road = if (relationOnly) null else "ref:L562"
            val relations = if (relationOnly) setOf("562") else emptySet()
            for ((at, way, direction) in listOf(Triple(1.0, "242667444", "forward"), Triple(3.0, "242667445", "reverse"),
                Triple(4.0, "242667443", "forward"), Triple(7.0, "31266734", "reverse"), Triple(8.999, "733915457", "forward"))) {
                now = at
                runtime.context(way, road, relations, direction, true)
                runtime.bundle("current-map", SpeedReferenceValue("numeric", 50))
                assertEquals("LAST_KNOWN", runtime.output()?.state)
                assertEquals(0, runtime.output()?.generation)
                assertNull(runtime.output()?.baselineKmh)
            }
            val withheld = requireNotNull(runtime.camera("pending-sign", SpeedReferenceValue("numeric", 30)))
            assertTrue(withheld.pendingContextAfter)
            now = 9.0
            runtime.context("733915457", road, relations, "forward", true)
            assertEquals(1, runtime.output()?.generation)
            runtime.bundle("fresh-map", SpeedReferenceValue("numeric", 50))
            assertEquals("BUNDLE", runtime.output()?.state)
            assertEquals(50, runtime.output()?.baselineKmh)
        }
    }

    @Test fun realReversalsAndUnrelatedRoadsStillRequireEightSeconds() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("old", "ref:old", emptySet(), "forward", true)
        runtime.bundle("old-map", SpeedReferenceValue("numeric", 70))
        now = 1.0
        runtime.context("road", "ref:B", emptySet(), "forward", true)
        now = 3.0
        runtime.context("road", "ref:B", emptySet(), "unknown", true)
        now = 4.0
        runtime.context("road", "ref:B", emptySet(), "reverse", true)
        now = 9.0
        runtime.context("road", "ref:B", emptySet(), "unknown", true)
        assertEquals(0, runtime.output()?.generation)
        now = 12.0
        runtime.context("road", "ref:B", emptySet(), "unknown", true)
        assertEquals(1, runtime.output()?.generation)
        runtime.bundle("new-map", SpeedReferenceValue("numeric", 50))
        now = 13.0
        runtime.context("road", "ref:B", emptySet(), "forward", true)
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        now = 20.999
        runtime.context("road", "ref:B", emptySet(), "unknown", true)
        assertEquals(1, runtime.output()?.generation)
        now = 21.0
        runtime.context("road", "ref:B", emptySet(), "forward", true)
        assertEquals(2, runtime.output()?.generation)
    }
}

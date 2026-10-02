package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.abs

class RoadPathPreparationTests {
    private val scope = TSRApplicabilityScope("drive", "bundle", "camera", 1, 1, 1)
    private fun diagnostic(id: String = "exposure", selectedScope: TSRApplicabilityScope = scope) =
        TSRApplicabilityDiagnostic(1, TSRFrameCandidateBatch(1, id, 10_000.0, selectedScope,
            "analyzed", emptyList(), false, 0, "model", "preprocessing", null), emptyList(), emptyList())
    private fun paintedFrame(): RoadPathCameraFrame {
        val width = 384; val height = 216
        val pixels = ByteArray(width * height) { 55 }
        for (y in 0 until height) {
            val ny = y.toDouble() / (height - 1)
            if (ny !in .49.. .96) continue
            val t = (ny - .50) / .44
            for (x in 0 until width) {
                val nx = x.toDouble() / (width - 1)
                if (abs(nx - (.42 - .28 * t)) < .0065 || abs(nx - (.58 + .28 * t)) < .0065)
                    pixels[y * width + x] = 230.toByte()
            }
        }
        return RoadPathCameraFrame(pixels, width, height, 10.0, "geometry", null, true, 0.0, 0,
            sourceTimestampSeconds = 123.0)
    }

    @Test fun productionKernelMatchesIndependentUnsignedBorderRoundingAndSaturationGoldens() {
        val cases = listOf(
            listOf(10,10,11,10,10) to listOf(10,10,12,10,10),
            listOf(101,10,10,10,10) to listOf(237,10,10,10,10),
            listOf(10,10,10,10,101) to listOf(10,10,10,10,237),
            listOf(10,10,255,10,10) to listOf(10,10,255,10,10),
            listOf(128,128,128,128,128) to listOf(128,128,128,128,128),
        )
        for ((input, expected) in cases) {
            val original = input.map(Int::toByte).toByteArray()
            val result = requireNotNull(RoadPathLaneFilter.apply(original, 5, 1))
            assertEquals(expected, result.map { it.toInt() and 255 })
            assertEquals(input, original.map { it.toInt() and 255 })
        }
        assertArrayEquals(byteArrayOf(200.toByte(), 20), RoadPathLaneFilter.apply(byteArrayOf(200.toByte(),20), 1, 2))
    }

    @Test fun cancellationInEitherMorphologyPassReturnsNoPartialPixels() {
        val input = ByteArray(64 * 2) { (it * 13).toByte() }
        // Each row checks once, then at pixels 0 and 32: checks 1..6 erode, 7..12 dilate.
        for (stopAt in listOf(1, 4, 8, 12)) {
            var calls = 0
            assertNull(RoadPathLaneFilter.apply(input, 64, 2) { ++calls < stopAt })
        }
        assertNull(RoadPathLaneFilter.apply(input, 384, 216))
    }

    @Test fun sparseFilterMatchesFullFilterAndDetectorAcrossCalibratedRows() {
        for ((w,h) in listOf(64 to 64,288 to 216,384 to 216,161 to 91)) {
            val input=ByteArray(w*h) { ((it*37+it/7)%256).toByte() }
            val full=requireNotNull(RoadPathLaneFilter.apply(input,w,h))
            for (horizon in listOf(null,Double.NaN,-1.0,0.05,0.37,0.8,2.0)) {
                val sparse=requireNotNull(RoadPathLaneFilter.applyForDetector(input,w,h,horizon))
                val rows=RoadBoundarySamplingRows.support(h,horizon).toSet()
                assertTrue(rows.size<=72)
                for (y in 0 until h) for (x in 0 until w)
                    assertEquals(if(y in rows) full[y*w+x] else 0.toByte(),sparse[y*w+x])
                val guidance=RoadBoundarySearchGuidance(horizon)
                assertEquals(RoadBoundaryDetector().detect(full,w,h,1.0,guidance=guidance),
                    RoadBoundaryDetector().detect(sparse,w,h,1.0,guidance=guidance))
            }
        }
        assertNull(RoadPathLaneFilter.applyForDetector(ByteArray(64*64),64,64) { false })
    }

    @Test fun preparePublishesBeforeTsrAndReusesGeometryWithoutPixelsOrTsrTime() {
        var clock = 1_000_000L
        val session = RoadPathSession { clock }
        val input = paintedFrame()
        val prepared = session.prepare(input, "exposure", scope)
        assertEquals(2, prepared.geometry.boundaries.size)
        val published = session.overlay()
        assertNotNull(published)
        assertTrue(published!!.boundaries.isEmpty()) // Raw evidence exists; display awaits a second exposure.
        assertEquals(2,prepared.presentation.tentativeCount)
        assertEquals(10.0, published.capturedAtSeconds, 0.0)
        // The producer may release/overwrite its pixels while TSR uses its own conversion.
        input.grayscale.fill(0)
        assertTrue(prepared.frame.grayscale.isEmpty())
        clock += 500_000_000 // A slow model must not consume the separate path-work budget.
        val result = Json.parseToJsonElement(session.evaluate(prepared, diagnostic())).jsonObject
        assertEquals(2, result.getValue("boundaries").jsonArray.size)
        assertFalse(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
        assertEquals(1.0, result.getValue("totalAddedProcessingMs").jsonPrimitive.double, 0.0)
        assertTrue(result.getValue("preparedGeometryReused").jsonPrimitive.boolean)
        assertSame(published, session.overlay()) // No after-TSR publication or freshness reset.
        assertEquals("prepared_frame_already_consumed_or_superseded",
            Json.parseToJsonElement(session.evaluate(prepared, diagnostic())).jsonObject.getValue("reason").jsonPrimitive.content)
        val second = session.prepare(paintedFrame().copy(capturedAtSeconds=10.45,sourceTimestampSeconds=123.45,
            startedAtNanos=clock-1_000_000),"second",scope)
        assertEquals(2,second.geometry.boundaries.size)
        assertEquals(second.geometry.boundaries,session.overlay()!!.boundaries)
        assertEquals(2,second.presentation.confirmedCount)
        session.invalidateOverlay()
        val afterReset=session.prepare(paintedFrame().copy(capturedAtSeconds=10.7,sourceTimestampSeconds=123.7,
            startedAtNanos=clock-1_000_000),"after-reset",scope)
        assertEquals(2,afterReset.geometry.boundaries.size)
        assertTrue(session.overlay()!!.boundaries.isEmpty())
    }

    @Test fun exactFrameAndScopeAreRequiredAndNewPreparationSupersedesOldToken() {
        val session = RoadPathSession { 1_000_000L }
        val prepared = session.prepare(paintedFrame(), "exposure", scope)
        for (wrong in listOf(diagnostic("other"), diagnostic(selectedScope = scope.copy(generation = 2)))) {
            assertEquals("prepared_frame_mismatch", Json.parseToJsonElement(session.evaluate(prepared, wrong))
                .jsonObject.getValue("reason").jsonPrimitive.content)
        }
        session.prepare(paintedFrame().copy(capturedAtSeconds = 11.0, sourceTimestampSeconds = 124.0), "next", scope)
        assertEquals("prepared_frame_already_consumed_or_superseded", Json.parseToJsonElement(session.evaluate(prepared, diagnostic()))
            .jsonObject.getValue("reason").jsonPrimitive.content)
    }

    @Test fun invalidationBetweenPreparationAndTsrCompletionRejectsAssociation() {
        for (reset in listOf(false, true)) {
            val session = RoadPathSession { 1_000_000L }
            val prepared = session.prepare(paintedFrame(), "exposure", scope)
            if (reset) session.resetTrajectory() else session.invalidateOverlay()
            val result = Json.parseToJsonElement(session.evaluate(prepared, diagnostic())).jsonObject
            assertEquals(if (reset) "trajectory_reset" else "overlay_invalidated", result.getValue("reason").jsonPrimitive.content)
            assertTrue(result.getValue("associations").jsonArray.isEmpty())
            assertNull(session.overlay())
        }
    }

    @Test fun rejectedContextAndOperationExhaustionNeverPublishPartialGeometry() {
        val session = RoadPathSession { 1_000_000L }
        val prepared = session.prepare(paintedFrame(), "exposure", scope) { false }
        assertNull(session.overlay())
        assertEquals("context_invalidated", Json.parseToJsonElement(session.evaluate(prepared, diagnostic()))
            .jsonObject.getValue("reason").jsonPrimitive.content)
        val exhaustedSession = RoadPathSession(maximumGeometryOperations = 100) { 60_000_000L }
        val exhausted = exhaustedSession.prepare(paintedFrame(), "exposure", scope)
        assertTrue(exhausted.geometry.budgetExceeded)
        assertTrue(exhausted.geometry.boundaries.isEmpty())
        assertTrue(exhausted.presentation.visibleBoundaryIndices.isEmpty())
        assertFalse(exhausted.presentation.accepted)
        assertNull(exhaustedSession.overlay())
    }

    @Test fun associationStillHasCumulativeTwoHundredMillisecondDeadline() {
        var clock = 1_000_000L
        var runningAssociation = false
        val session = RoadPathSession { if (runningAssociation) clock += 100_000_000; clock }
        val prepared = session.prepare(paintedFrame(), "exposure", scope)
        runningAssociation = true
        val result = Json.parseToJsonElement(session.evaluate(prepared, diagnostic())).jsonObject
        assertTrue(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
        assertEquals("added_processing_deadline", result.getValue("reason").jsonPrimitive.content)
        assertTrue(result.getValue("associations").jsonArray.isEmpty())
        assertNull(session.overlay())
    }
}

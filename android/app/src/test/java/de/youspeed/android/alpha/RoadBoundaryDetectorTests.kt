package de.youspeed.android.alpha

import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RoadBoundaryDetectorTests {
    private val detector = RoadBoundaryDetector()

    // Same deterministic fixtures and assertions as RoadBoundaryDetectorTests.swift.
    private fun scene(kind: String, width: Int = 384, height: Int = 216): ByteArray {
        val image = ByteArray(width * height) { 55 }
        for (y in 0 until height) {
            val ny = y.toDouble() / (height - 1)
            if (ny < 0.49 || ny > 0.96) continue
            val t = (ny - 0.50) / 0.44
            val bend = if (kind == "curve") 0.18 * (1 - t) * (1 - t) else if (kind == "wave") 0.04*kotlin.math.sin(2*Math.PI*t) else 0.0
            val targets = when (kind) {
                "fork" -> listOf(0.38 - 0.24 * t, 0.50, 0.62 + 0.24 * t)
                "facade" -> (1..10).map { it / 11.0 }
                else -> listOf(0.42 - 0.28 * t + bend, 0.58 + 0.28 * t + bend)
            }
            for (x in 0 until width) {
                val nx = x.toDouble() / (width - 1)
                val value = when (kind) {
                    "edge" -> if (nx > 0.42 - 0.28 * t && nx < 0.58 + 0.28 * t) 190 else 55
                    "clutter" -> (x * 37 + y * 17 + x * y * 13) % 256
                    else -> if (targets.any { abs(nx - it) < 0.0065 }) 230 else 55
                }
                image[y * width + x] = value.toByte()
            }
        }
        return image
    }

    @Test fun straightPaintProducesUnassignedObservedCorridor() {
        val frame = detector.detect(scene("straight"), 384, 216, 1.0)
        assertFalse(frame.budgetExceeded)
        assertEquals(2, frame.boundaries.size)
        assertEquals(1, frame.corridors.size)
        frame.boundaries.forEachIndexed { index, boundary ->
            assertEquals(RoadBoundaryCue.PAINT, boundary.cue)
            assertEquals(24, boundary.supportRows)
            assertTrue(boundary.confidence >= 0.90)
            boundary.points.forEach { point ->
                val t = (point.y - 0.50) / 0.44
                assertEquals(if (index == 0) 0.42 - 0.28 * t else 0.58 + 0.28 * t, point.x, 0.008)
                assertTrue(point.y in 0.50..0.95)
            }
        }
        // Identical fixture also catches Swift/Kotlin rounding and budget arithmetic drift.
        assertEquals(127904, frame.operationCount)
        assertEquals(0.4177545691906005, frame.boundaries[0].points.first().x, 1e-12)
    }

    @Test fun curvedMarkingsPreserveLocalShapeInsteadOfStraightFit() {
        val frame = detector.detect(scene("curve"), 384, 216, 2.0)
        assertEquals(2, frame.boundaries.size)
        assertEquals(1, frame.corridors.size)
        frame.boundaries.forEachIndexed { index, boundary ->
            boundary.points.forEach { point ->
                val t = (point.y - 0.50) / 0.44
                val expected = (if (index == 0) 0.42 - 0.28 * t else 0.58 + 0.28 * t) + 0.18 * (1 - t) * (1 - t)
                assertEquals(expected, point.x, 0.009)
            }
        }
    }

    @Test fun darkNoiseAndBroadShadowTransitionsCannotBecomePaint() {
        val width = 384; val height = 216
        val paint = scene("straight", width, height)
        val scenes = listOf(
            ByteArray(width * height) { index -> if ((paint[index].toInt() and 255) > 100) 47 else 32 },
            ByteArray(width * height) { index -> if ((paint[index].toInt() and 255) > 100) 30 else 0 },
            ByteArray(width * height) { index -> (40 + ((index % width) * 13 + (index / width) * 7) % 15).toByte() },
            ByteArray(width * height) { index -> (25 + 50 * (index % width) / width).toByte() },
            ByteArray(width * height) { index ->
                val y = (index / width).toDouble() / (height - 1)
                val x = (index % width).toDouble() / (width - 1)
                if (x > 0.42 - 0.28 * ((y - 0.50) / 0.44) &&
                    x < 0.58 + 0.28 * ((y - 0.50) / 0.44)) 75 else 20
            },
        )
        for (image in scenes) {
            val frame = detector.detect(image, width, height, 2.2)
            assertFalse(frame.budgetExceeded)
            assertTrue(frame.boundaries.all { it.cue == RoadBoundaryCue.EDGE && it.confidence <= 0.40 })
            assertTrue(frame.corridors.isEmpty())
        }
    }

    @Test fun competingCorridorsRemainSeparateWithoutChoosingEgo() {
        val frame = detector.detect(scene("fork"), 384, 216, 3.0)
        assertEquals(3, frame.boundaries.size)
        assertEquals(listOf(0 to 1, 1 to 2), frame.corridors.map { it.leftBoundaryIndex to it.rightBoundaryIndex })
    }

    @Test fun staleCurvedGuideCannotJoinTwoSeparatelyObservedStripes() {
        // A continuous stripe has two current observations before the old guide bends toward
        // a nearby stripe appearing farther away. The old unbounded guide joined those stripes.
        for (width in listOf(192, 384)) {
            val height = 216
            val image = ByteArray(width * height) { 55 }
            for (y in 0 until height) {
                val ny = y.toDouble() / (height - 1)
                if (ny !in 0.49..0.96) continue
                for (x in 0 until width) {
                    val nx = x.toDouble() / (width - 1)
                    if (abs(nx - 0.35) < 0.0065 || (ny < 0.91 && abs(nx - 0.40) < 0.0065)) image[y * width + x] = 230.toByte()
                }
            }
            val guide = RoadBoundarySearchGuidance(polylines = listOf(listOf(
                LanePoint(0.45, 0.50), LanePoint(0.45, 0.903), LanePoint(0.35, 0.920), LanePoint(0.35, 0.94),
            )))
            val frame = detector.detect(image, width, height, 3.1, guidance = guide)
            assertFalse(frame.budgetExceeded)
            assertEquals(2, frame.boundaries.size)
            val continuous = frame.boundaries.single { it.supportRows == 24 }
            assertTrue(continuous.points.all { abs(it.x - 0.35) <= 1.0 / (width - 1) })
            val distant = frame.boundaries.single { it.supportRows == 22 }
            assertTrue(distant.points.all { abs(it.x - 0.40) <= 1.0 / (width - 1) })
        }
    }

    @Test fun noPaintAndFacadeEdgesCannotInventDrivableCorridor() {
        val blank = detector.detect(ByteArray(384 * 216) { 55 }, 384, 216, 4.0)
        assertTrue(blank.boundaries.isEmpty())
        assertTrue(blank.corridors.isEmpty())
        val edges = detector.detect(scene("edge"), 384, 216, 4.1)
        assertEquals(2, edges.boundaries.size)
        assertTrue(edges.boundaries.all { it.cue == RoadBoundaryCue.EDGE && it.confidence <= 0.40 })
        assertTrue(edges.corridors.isEmpty())
        assertTrue(detector.detect(scene("facade"), 384, 216, 4.2).corridors.isEmpty())
    }

    @Test fun portraitAndClutterRemainBounded() {
        val portrait = detector.detect(scene("straight", 122, 216), 122, 216, 5.0)
        assertFalse(portrait.budgetExceeded)
        assertEquals(2, portrait.boundaries.size)
        val clutter = detector.detect(scene("clutter"), 384, 216, 5.1)
        assertFalse(clutter.budgetExceeded)
        assertTrue(clutter.boundaries.size <= 6)
        assertTrue(clutter.corridors.size <= 2)
        assertTrue(clutter.operationCount <= 250_000)
    }

    @Test fun invalidDimensionsBufferAndTimestampReturnEmpty() {
        for ((width, height) in listOf(0 to 216, 385 to 216, 384 to 217, Int.MAX_VALUE to Int.MAX_VALUE)) {
            val result = detector.detect(byteArrayOf(), width, height, 1.0)
            assertTrue(result.boundaries.isEmpty())
            assertFalse(result.budgetExceeded)
        }
        assertTrue(detector.detect(byteArrayOf(55), 384, 216, 1.0).boundaries.isEmpty())
        assertTrue(detector.detect(scene("straight"), 384, 216, Double.NaN).boundaries.isEmpty())
    }

    @Test fun deadlinesAndOperationBudgetDiscardAllPartialGeometry() {
        val pixels = scene("straight")
        var checks = 0
        val cancelled = detector.detect(pixels, 384, 216, 6.0) { ++checks < 75 }
        assertTrue(cancelled.budgetExceeded)
        assertTrue(cancelled.boundaries.isEmpty())
        assertTrue(cancelled.corridors.isEmpty())
        assertEquals(75, checks)
        val exhausted = detector.detect(pixels, 384, 216, 6.1, maximumOperations = 100)
        assertTrue(exhausted.budgetExceeded)
        assertTrue(exhausted.boundaries.isEmpty())
        val fresh = detector.detect(pixels, 384, 216, 6.2)
        assertEquals(2, fresh.boundaries.size)
        assertFalse(fresh.budgetExceeded)
    }
    private fun fragmentScene(kind:String):ByteArray {
        val width=384; val height=216
        val image=ByteArray(width*height) { 55 }
        for (y in 0 until height) {
            val ny=y.toDouble()/(height-1); val t=(ny-0.50)/0.44
            for (x in 0 until width) {
                val nx=x.toDouble()/(width-1)
                val painted=when(kind) {
                    "dashed", "curved_dashed" -> {
                        val bend=if (kind=="curved_dashed") 0.18*(1-t)*(1-t) else 0.0
                        (ny in 0.56..0.63 || ny in 0.76..0.83) &&
                            listOf(0.42-0.28*t+bend,0.58+0.28*t+bend).any { abs(nx-it)<0.0065 }
                    }
                    "arrow" -> (ny in 0.81..0.93 && abs(nx-0.5)<0.0065) ||
                        (ny in 0.70..0.81 && abs(abs(nx-0.5)-(0.81-ny)*1.4)<0.0065)
                    "merge" -> (ny in 0.76..0.83 && abs(nx-(0.42-0.28*t))<0.0065) ||
                        (ny in 0.56..0.63 && abs(nx-(0.42-0.28*t+0.10))<0.0065)
                    "guardrail" -> nx>0.1 && nx<0.9 && (abs(ny-0.62)<0.006 || abs(ny-0.78)<0.006)
                    else -> false
                }
                if (painted) image[y*width+x]=230.toByte()
            }
        }
        return image
    }

    @Test fun fragmentRecoveryPreservesAcceptedContinuousGeometryAndConfidence() {
        // This coherent wave is not one quadratic; a global gate previously erased it.
        for (kind in listOf("straight","curve","wave","fork","edge","facade")) {
            val pixels=scene(kind)
            val baseline=detector.detect(pixels,384,216,6.3)
            assertFalse(baseline.boundaries.isEmpty())
            for (bands in listOf(false,true)) {
                val recovered=detector.detect(pixels,384,216,6.3,
                    options=RoadBoundaryDetectionOptions(useSearchBands=bands,groupFragments=true))
                assertFalse(recovered.budgetExceeded)
                assertEquals("Lost raw support for $kind",baseline.boundaries.size,recovered.boundaries.size)
                baseline.boundaries.zip(recovered.boundaries).forEach { (original,preserved) ->
                    assertEquals(original.points,preserved.points)
                    assertEquals(original.confidence,preserved.confidence,0.0)
                    assertEquals(original.cue,preserved.cue)
                    assertEquals(original.supportRows,preserved.supportRows)
                    assertEquals(null,preserved.geometryConfidence)
                    if (preserved.cue==RoadBoundaryCue.PAINT) {
                        assertEquals(listOf(original.points),preserved.observedSegments)
                        assertEquals(1.0,preserved.paintOccupancy!!,0.0)
                    }
                }
                assertEquals(baseline.corridors,recovered.corridors)
                assertEquals(null,recovered.rejectionCounts["fragments_joined"])
                assertFalse(recovered.rejectionCounts.keys.any { it.startsWith("fragment_fit_") })
            }
        }
    }

    @Test fun recoveredDashesCannotDisplaceSixAcceptedRawBorders() {
        val w=384; val h=216; val pixels=ByteArray(w*h) { 55 }
        for (y in 0 until h) {
            val ny=y.toDouble()/(h-1)
            if (ny !in 0.49..0.96) continue
            val centers=mutableListOf(0.10,0.25,0.40,0.55,0.70,0.85)
            if (ny in 0.56..0.63 || ny in 0.76..0.83) centers.add(0.475)
            for (x in 0 until w) if (centers.any { abs(x.toDouble()/(w-1)-it)<0.0065 }) pixels[y*w+x]=230.toByte()
        }
        val baseline=detector.detect(pixels,w,h,6.4)
        val recovered=detector.detect(pixels,w,h,6.4,options=RoadBoundaryDetectionOptions(groupFragments=true))
        assertFalse(recovered.budgetExceeded)
        assertEquals(6,baseline.boundaries.size)
        assertEquals(baseline.boundaries.map { it.points },recovered.boundaries.map { it.points })
        assertEquals(baseline.boundaries.map { it.confidence },recovered.boundaries.map { it.confidence })
        assertEquals(1,recovered.rejectionCounts["fragment_output_capacity"])
    }

    @Test fun fragmentGroupingJoinsConsistentDashesWithoutInventingPaintOrRequiringBottomRow() {
        for (kind in listOf("dashed","curved_dashed")) {
            val pixels=fragmentScene(kind)
            val baseline=detector.detect(pixels,384,216,7.0)
            assertTrue(baseline.boundaries.isEmpty())
            val grouped=detector.detect(pixels,384,216,7.0,options=RoadBoundaryDetectionOptions(groupFragments=true))
            assertFalse(grouped.budgetExceeded)
            assertEquals(2,grouped.boundaries.size)
            assertEquals(2,grouped.rejectionCounts["fragments_joined"])
            for (boundary in grouped.boundaries) {
                assertEquals(RoadBoundaryCue.PAINT,boundary.cue)
                assertEquals(2,boundary.observedSegments.size)
                assertTrue(boundary.confidence>0.40)
                assertTrue((boundary.paintOccupancy ?: 1.0)<0.65)
                assertTrue(boundary.points.last().y<0.85)
                for (segment in boundary.observedSegments) {
                    assertTrue(segment.size>=2)
                    assertTrue(segment.all { it.y in 0.55..0.64 || it.y in 0.75..0.84 })
                    assertTrue(segment.last().y-segment.first().y<0.10)
                }
            }
        }
    }

    @Test fun searchBandsAreSoftAndDoNotChangeSolidPaintWithoutCapacityPressure() {
        val pixels=scene("straight")
        val baseline=detector.detect(pixels,384,216,8.0)
        val wrong=RoadBoundarySearchGuidance(polylines=listOf(
            listOf(LanePoint(0.05,0.5),LanePoint(0.05,0.94)),listOf(LanePoint(0.1,0.5),LanePoint(0.1,0.94))))
        val bands=detector.detect(pixels,384,216,8.0,guidance=wrong,options=RoadBoundaryDetectionOptions(useSearchBands=true))
        assertEquals(baseline.boundaries,bands.boundaries)
        assertTrue((bands.rejectionCounts["outside_bands_retained"] ?: 0)>0)
        assertEquals("bands",bands.detectionVariant)
    }

    @Test fun fragmentNegativesDoNotJoinArrowMergeOrHorizontalGuardrail() {
        for (kind in listOf("arrow","merge","guardrail","unmarked")) for (bands in listOf(false,true)) {
            val result=detector.detect(fragmentScene(kind),384,216,9.0,
                options=RoadBoundaryDetectionOptions(useSearchBands=bands,groupFragments=true))
            assertFalse(result.budgetExceeded)
            assertTrue("Unexpected boundary for $kind",result.boundaries.isEmpty())
            assertTrue(result.corridors.isEmpty())
            assertEquals(null,result.rejectionCounts["fragments_joined"])
        }
    }

    @Test fun fragmentVariantKeepsOperationCapAndCancellationAtomic() {
        for (options in listOf(RoadBoundaryDetectionOptions(useSearchBands=true),RoadBoundaryDetectionOptions(groupFragments=true),
            RoadBoundaryDetectionOptions(useSearchBands=true,groupFragments=true))) {
            val exhausted=detector.detect(fragmentScene("dashed"),384,216,10.0,maximumOperations=100,options=options)
            assertTrue(exhausted.budgetExceeded)
            assertTrue(exhausted.boundaries.isEmpty())
            assertTrue(exhausted.operationCount<=100)
            val clutter=detector.detect(scene("clutter"),384,216,10.0,options=options)
            assertTrue(clutter.operationCount<=250_000)
            assertTrue(clutter.boundaries.size<=6)
        }
    }

}

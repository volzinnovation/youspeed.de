package de.youspeed.android.alpha

import java.nio.ByteBuffer
import java.util.concurrent.AbstractExecutorService
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import org.junit.Assert.*
import org.junit.Test

class LaneDetectionRuntimeTests {
    private val identity = listOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

    @Test fun cadenceSeparatesCameraDeliveryAdmissionAndPublicationWithBoundedHistory() {
        val cadence=LaneCadenceWindow()
        for (index in 0..200) {
            cadence.record("delivery",index*30_000_000L)
            if (index%4==0) {
                cadence.record("admitted",index*30_000_000L)
                cadence.record("published",index*30_000_000L+15_000_000L)
            }
        }
        val fields=cadence.diagnostics()
        val delivered=fields["delivery"] as Map<*,*>
        val admitted=fields["admitted"] as Map<*,*>
        assertEquals(201L,delivered["count"])
        assertEquals(128,delivered["intervalSamples"])
        assertEquals(30.0,delivered["intervalP95Ms"])
        assertEquals(51L,admitted["count"])
        assertEquals(120.0,admitted["intervalP95Ms"])
        cadence.resetIntervals()
        cadence.record("delivery",100_000_000_000L)
        val resumed=cadence.diagnostics()["delivery"] as Map<*,*>
        assertEquals(202L,resumed["count"])
        assertEquals(0,resumed["intervalSamples"])
    }

    @Test fun samplesPaddedPixelStridedPlaneInEveryRotationWithoutChangingOwnership() {
        val buffer = ByteBuffer.allocate(20)
        buffer.position(1)
        for (y in 0..1) for (x in 0..2) buffer.put(1 + y * 8 + x * 2, (y * 3 + x).toByte())
        val expected = mapOf(0 to listOf(0, 1, 2, 3, 4, 5), 90 to listOf(3, 0, 4, 1, 5, 2),
            180 to listOf(5, 4, 3, 2, 1, 0), 270 to listOf(2, 5, 1, 4, 0, 3))
        for ((rotation, pixels) in expected) {
            val geometry = LaneImageGeometry(3, 2, rotation, identity)
            val output = ByteArray(6)
            LaneLumaSampler.copyUpright(buffer, 8, 2, geometry, output, geometry.uprightWidth, geometry.uprightHeight)
            assertEquals(pixels, output.map(Byte::toInt))
            assertEquals(1, buffer.position())
        }
    }

    @Test fun cachedSamplerMatchesOriginalPixelCentersAcrossGeometryStrideAndBufferChanges() {
        for ((rawW,rawH) in listOf(1279 to 721,1920 to 1440,65 to 67)) {
            for (rotation in listOf(0,90,180,270)) for (pixelStride in listOf(1,2)) {
                val rowStride=rawW*pixelStride+13
                val bytes=ByteArray(rowStride*rawH+20) { ((it*31+it/19)%256).toByte() }
                val buffer=ByteBuffer.wrap(bytes).asReadOnlyBuffer()
                val geometry=LaneImageGeometry(rawW,rawH,rotation,identity)
                val scale=minOf(384.0/geometry.uprightWidth,216.0/geometry.uprightHeight,1.0)
                val w=(geometry.uprightWidth*scale).toInt(); val h=(geometry.uprightHeight*scale).toInt()
                for (base in listOf(0,7,0)) {
                    buffer.position(base)
                    val expected=ByteArray(w*h)
                    for (y in 0 until h) for (x in 0 until w) {
                        val u=(x+0.5)/w; val v=(y+0.5)/h
                        val rx=when(rotation) { 0 -> u; 90 -> v; 180 -> 1-u; else -> 1-v }
                        val ry=when(rotation) { 0 -> v; 90 -> 1-u; 180 -> 1-v; else -> u }
                        val ix=(rx*rawW).toInt().coerceIn(0,rawW-1)
                        val iy=(ry*rawH).toInt().coerceIn(0,rawH-1)
                        expected[y*w+x]=buffer.get(base+iy*rowStride+ix*pixelStride)
                    }
                    val actual=ByteArray(w*h)
                    LaneLumaSampler.copyUpright(buffer,rowStride,pixelStride,geometry,actual,w,h)
                    assertArrayEquals(expected,actual)
                    assertEquals(base,buffer.position())
                }
            }
        }
    }

    @Test fun mapsAnalysisThroughSensorAndDifferentPreviewCropWithRotationAndMirroring() {
        val analysis = LaneImageGeometry(1920, 1080, 0, listOf(.5, 0.0, 0.0, 0.0, .5, 0.0, 0.0, 0.0, 1.0))
        val preview = LanePreviewGeometry(1440, 1080, 0, 0, 1440, 1080, 0, false,
            listOf(.5, 0.0, -240.0, 0.0, .5, 0.0, 0.0, 0.0, 1.0), 400, 300)
        assertPoint(200.0, 150.0, LaneOverlayGeometry.project(LanePoint(.5, .5), analysis, preview))
        assertPoint(300.0, 150.0, LaneOverlayGeometry.project(LanePoint(.6875, .5), analysis, preview))
        assertPoint(100.0, 150.0, LaneOverlayGeometry.project(LanePoint(.6875, .5), analysis, preview.copy(mirrored = true)))
        val portrait = preview.copy(rotationDegrees = 90, viewWidth = 300, viewHeight = 400)
        assertPoint(150.0, 300.0, LaneOverlayGeometry.project(LanePoint(.6875, .5), analysis, portrait))
        // Both streams rotated: converting upright analysis coordinates back to
        // raw sensor pixels cancels before the preview's portrait rotation.
        assertPoint(150.0, 300.0, LaneOverlayGeometry.project(LanePoint(.5, .6875), analysis.copy(rotationDegrees = 90), portrait))
        assertNull(LaneOverlayGeometry.project(LanePoint(.5, .5), analysis.copy(sensorToBuffer = List(9) { 0.0 }), preview))
    }

    @Test fun previewViewTransformIsNotRotatedOrCroppedTwice() {
        val image = LaneImageGeometry(1920, 1080, 90,
            listOf(.5, 0.0, 0.0, 0.0, .5, 0.0, 0.0, 0.0, 1.0))
        // CameraX's sensor-to-view matrix includes portrait rotation and a
        // crop from a 3840x2160 sensor into a 300x400 view.
        val preview = LanePreviewGeometry(300, 400, 0, 0, 300, 400, 0, false,
            listOf(0.0, -1.0 / 9.0, 270.0, 1.0 / 9.0, 0.0, -40.0, 0.0, 0.0, 1.0), 300, 400)
        assertPoint(150.0, 173.33333333333334,
            LaneOverlayGeometry.project(LanePoint(.5, .5), image, preview))
        assertPoint(90.0, 280.0,
            LaneOverlayGeometry.project(LanePoint(.25, .75), image, preview))
        assertPoint(210.0, 280.0, LaneOverlayGeometry.project(LanePoint(.25, .75), image,
            preview.copy(sensorToBuffer = listOf(0.0, 1.0 / 9.0, 30.0, 1.0 / 9.0, 0.0, -40.0, 0.0, 0.0, 1.0))))
    }

    @Test fun centreFillClipsTheSameWayAsTextureView() {
        val image = LaneImageGeometry(1920, 1080, 0, identity)
        val preview = LanePreviewGeometry(1920, 1080, 0, 0, 1920, 1080, 0, false, identity, 400, 400)
        assertPoint(200.0, 200.0, LaneOverlayGeometry.project(LanePoint(.5, .5), image, preview))
        assertTrue(requireNotNull(LaneOverlayGeometry.project(LanePoint(0.0, .5), image, preview)).x < 0)
    }

    @Test fun resultsFadeAndExpireUsingCaptureAgeIncludingFutureTimestamps() {
        val start = 10_000_000_000L
        assertEquals(1f, LaneOverlayGeometry.opacity(start, start + 300_000_000L))
        assertEquals(.5f, LaneOverlayGeometry.opacity(start, start + 525_000_000L), .00001f)
        assertEquals(0f, LaneOverlayGeometry.opacity(start, start + 750_000_000L))
        assertEquals(0f, LaneOverlayGeometry.opacity(start, start - 1))
        assertEquals(0f, LaneOverlayGeometry.opacity(0, start))
    }

    @Test fun realtimeClockRetainsCameraQueueAgeAndUnknownOriginReportsEstimation() {
        val clock = LaneCaptureClock()
        val realtime = clock.map(1_000_000_000L, 1_500_000_000L, realtime = true)
        assertEquals(1_000_000_000L, realtime.nanos)
        assertFalse(realtime.estimated)
        clock.reset()
        val unknown = clock.map(5_000L, 1_500_000_000L)
        assertEquals(1_500_000_000L, unknown.nanos)
        assertTrue(unknown.estimated)
        assertEquals(1_600_000_000L, clock.map(100_005_000L, 1_800_000_000L).nanos)
        val delayed = clock.map(200_005_000L, 7_500_000_000L)
        assertEquals(1_700_000_000L, delayed.nanos)
        assertFalse(delayed.discontinuity)
        assertTrue(clock.map(1L, 2_000_000_000L).discontinuity)
        assertTrue(clock.map(2_000_000_001L, 2_000_000_001L, realtime = true).discontinuity)
    }

    @Test fun gatingSkipsPlaneReadsForDisabledHiddenThermalAndCadenceStates() {
        val fixture = RuntimeFixture()
        fixture.condition = LaneAdmission(false, 1, false)
        fixture.submit()
        assertEquals(0, fixture.reads)
        fixture.condition = LaneAdmission(true, 2, true)
        fixture.submit()
        assertEquals(0, fixture.reads)
        fixture.condition = LaneAdmission(true, 3, false)
        fixture.submit()
        fixture.worker.drain()
        fixture.main.drain()
        fixture.now += 50_000_000L
        fixture.submit()
        assertEquals(1, fixture.reads)
        fixture.close()
    }

    @Test fun latestFrameReplacesPendingWorkWithoutGrowingExecutorQueue() {
        val fixture = RuntimeFixture()
        repeat(3) { fixture.submit(); fixture.now += 200_000_000L }
        assertEquals(1, fixture.worker.pendingCount)
        fixture.worker.drain()
        fixture.main.drain()
        val result = fixture.results.last()
        assertEquals(3L, result.frameId)
        assertEquals(2L, result.replacedFrames)
        assertEquals(1L, result.processedFrames)
        fixture.close()
    }

    @Test fun scopeChangeAndCloseRejectQueuedCallbacksFromOldPreview() {
        val fixture = RuntimeFixture()
        fixture.submit()
        fixture.worker.drain()
        fixture.condition = fixture.condition.copy(scope = 2)
        fixture.main.drain()
        assertTrue(fixture.results.isEmpty())
        fixture.now += 200_000_000L
        fixture.submit()
        fixture.worker.drain()
        fixture.runtime.close()
        fixture.main.drain()
        assertTrue(fixture.results.isEmpty())
    }

    @Test fun trackerConfirmsAcrossWorkerIdleAndResetsAfterThermalPause() {
        val fixture = RuntimeFixture()
        fixture.submit(); fixture.worker.drain(); fixture.main.drain()
        assertFalse(requireNotNull(fixture.results.last().estimate).hasReliablePair)
        fixture.now += 200_000_000L
        fixture.submit(); fixture.worker.drain(); fixture.main.drain()
        assertTrue(requireNotNull(fixture.results.last().estimate).hasReliablePair)
        fixture.condition = fixture.condition.copy(thermallyPaused = true)
        fixture.submit(); fixture.main.drain()
        assertEquals(LanePresentationState.PAUSED, fixture.results.last().state)
        fixture.condition = fixture.condition.copy(thermallyPaused = false)
        fixture.now += 200_000_000L
        fixture.submit(); fixture.worker.drain(); fixture.main.drain()
        assertFalse(requireNotNull(fixture.results.last().estimate).hasReliablePair)
        fixture.close()
    }

    @Test fun staleRealtimeFramesAreRejectedBeforeCopyingOrDetection() {
        val fixture = RuntimeFixture()
        fixture.cameraAge = 800_000_000L
        fixture.submit()
        assertEquals(0, fixture.worker.pendingCount)
        fixture.main.drain()
        assertNull(fixture.results.last().estimate)
        fixture.close()
    }

    @Test fun pendingFrameThatAgesOutOrLosesScopeIsNotAnalysed() {
        val fixture = RuntimeFixture()
        fixture.submit()
        fixture.now += 800_000_000L
        fixture.worker.drain(); fixture.main.drain()
        assertTrue(fixture.results.none { it.estimate != null })
        fixture.results.clear()
        fixture.submit()
        fixture.condition = fixture.condition.copy(scope = 2)
        fixture.worker.drain(); fixture.main.drain()
        assertTrue(fixture.results.isEmpty())
        fixture.close()
    }

    @Test fun performanceWindowKeepsSlowTailAndHasBoundedMemory() {
        val window = LanePerformanceWindow(20)
        repeat(25) { index -> window.record(index * 200_000_000L, 1.0, if (index == 24) 80.0 else 5.0, 20.0) }
        val summary = window.summary()
        assertEquals(20, summary.sampleCount)
        assertEquals(5.0, summary.completedFramesPerSecond, 1e-9)
        assertEquals(5.0, summary.detection.p50, 1e-9)
        assertEquals(80.0, summary.detection.p95, 1e-9)
        assertEquals(80.0, summary.detection.maximum, 1e-9)
    }

    @Test fun previewWorkerUsesTenHzLatestFrameAndPublishesWithoutTsrContext() {
        val f=RuntimeFixture(preview=true)
        repeat(6) { f.submit(); f.worker.drain(); f.main.drain(); f.now+=100_000_000L }
        assertEquals(6,f.roadResults.size)
        assertTrue(f.roadResults.any { it.presentation.visibleBoundaryIndices.isNotEmpty() })
        assertTrue(f.roadResults.all { it.presentation.visibleBoundaryIndices.size<=2 })
        f.submit(); f.now+=100_000_000L; f.submit(); f.now+=100_000_000L; f.submit()
        assertEquals(1,f.worker.pendingCount)
        f.worker.drain(); f.main.drain()
        assertEquals(7,f.roadResults.size)
        assertEquals(f.now/1e9,f.roadResults.last().frame.sourceTimestampSeconds!!,1e-9)
        f.close()
    }
    @Test fun previewPendingWorkCannotSurviveThermalPauseOrScopeChange() {
        val f=RuntimeFixture(preview=true)
        f.submit(); f.condition=f.condition.copy(thermallyPaused=true)
        f.worker.drain(); f.main.drain(); assertTrue(f.roadResults.isEmpty())
        f.now+=200_000_000L; f.condition=f.condition.copy(thermallyPaused=false)
        f.submit(); f.condition=f.condition.copy(scope=2)
        f.worker.drain(); f.main.drain(); assertTrue(f.roadResults.isEmpty())
        f.close()
    }

    private fun assertPoint(x: Double, y: Double, point: LanePoint?) {
        assertNotNull(point)
        assertEquals(x, point!!.x, 1e-6)
        assertEquals(y, point.y, 1e-6)
    }

    private inner class RuntimeFixture(preview: Boolean = false) {
        var now = 10_000_000_000L
        var condition = LaneAdmission(true, 1, false)
        var cameraAge = 0L
        var reads = 0
        val main = QueuedExecutor()
        val worker = QueuedExecutor()
        val results = mutableListOf<LaneRuntimeSnapshot>()
        private val pixels = ByteArray(384 * 216) { 55 }.also { bytes ->
            for (y in 0 until 216) {
                val v = y / 215.0
                if (v !in .52.. .96) continue
                val offset = (v - .52) * .30 / .44
                for (x in 0 until 384) if (abs(x / 383.0 - (.42 - offset)) < .0065 ||
                    abs(x / 383.0 - (.58 + offset)) < .0065) bytes[y * 384 + x] = 230.toByte()
            }
        }
        val roadResults=mutableListOf<RoadPathPreparedFrame>()
        val previewSession=RoadPathSession(previewMode=true, nowNanos={now})
        private val previewEnabled=preview
        val runtime = AndroidLaneDetectionRuntime(main, { condition }, { true }, results::add, {}, { now }, worker,
            previewSession=if(preview) previewSession else null,onRoadResult=roadResults::add)
        fun submit() = runtime.submit {
            reads++
            LaneLumaSource(ByteBuffer.wrap(pixels), 384, 1, LaneImageGeometry(384, 216, 0, identity), now - cameraAge,
                if(previewEnabled) RoadPathCameraFrame(pixels.copyOf(),384,216,(now-cameraAge)/1e9,"camera",null,true,0.0,now,
                    sourceTimestampSeconds=(now-cameraAge)/1e9) else null)
        }
        fun close() = runtime.close()
    }

    private class QueuedExecutor : AbstractExecutorService() {
        private val tasks = ArrayDeque<Runnable>()
        private var stopped = false
        val pendingCount: Int get() = tasks.size
        fun drain() { while (tasks.isNotEmpty()) tasks.removeFirst().run() }
        override fun execute(command: Runnable) { check(!stopped); tasks.addLast(command) }
        override fun shutdown() { stopped = true }
        override fun shutdownNow(): MutableList<Runnable> { stopped = true; return tasks.toMutableList().also { tasks.clear() } }
        override fun isShutdown() = stopped
        override fun isTerminated() = stopped && tasks.isEmpty()
        override fun awaitTermination(timeout: Long, unit: TimeUnit) = isTerminated
    }
}

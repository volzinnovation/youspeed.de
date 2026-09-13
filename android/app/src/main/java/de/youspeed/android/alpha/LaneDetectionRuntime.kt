package de.youspeed.android.alpha

import android.os.SystemClock
import android.os.Process
import androidx.camera.core.ImageProxy
import java.nio.ByteBuffer
import java.util.concurrent.Executor
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.max
import kotlin.math.roundToInt

/** Lanes are an optional preview annotation, never speed-limit evidence. */
internal enum class LanePresentationState { RELIABLE, UNCERTAIN, UNAVAILABLE, PAUSED }

internal data class LaneImageGeometry(
    val width: Int,
    val height: Int,
    val rotationDegrees: Int,
    val sensorToBuffer: List<Double>,
) {
    val uprightWidth: Int get() = if (rotationDegrees % 180 == 0) width else height
    val uprightHeight: Int get() = if (rotationDegrees % 180 == 0) height else width
}

internal data class LanePreviewGeometry(
    val width: Int,
    val height: Int,
    val cropLeft: Int,
    val cropTop: Int,
    val cropRight: Int,
    val cropBottom: Int,
    val rotationDegrees: Int,
    val mirrored: Boolean,
    val sensorToBuffer: List<Double>,
    val viewWidth: Int,
    val viewHeight: Int,
)

internal data class LaneRuntimeSnapshot(
    val state: LanePresentationState = LanePresentationState.PAUSED,
    val estimate: LaneDetectionEstimate? = null,
    val geometry: LaneImageGeometry? = null,
    val scope: Long = -1,
    val capturedAtNanos: Long = 0,
    val frameId: Long = 0,
    val preprocessingMs: Double = 0.0,
    val detectionMs: Double = 0.0,
    val captureToResultMs: Double = 0.0,
    val captureAgeEstimated: Boolean = true,
    val processedFrames: Long = 0,
    val replacedFrames: Long = 0,
    val throttledFrames: Long = 0,
    val timestampRejectedFrames: Long = 0,
    val performance: LanePerformanceSummary? = null,
) {
    fun opacity(nowNanos: Long): Float = LaneOverlayGeometry.opacity(capturedAtNanos, nowNanos)
}

internal data class LaneStageTiming(val p50: Double, val p95: Double, val maximum: Double)
internal data class LanePerformanceSummary(val sampleCount: Int, val completedFramesPerSecond: Double,
    val preprocessing: LaneStageTiming, val detection: LaneStageTiming, val captureToResult: LaneStageTiming)

/** A bounded window includes every completed frame, so periodic logs retain slow tails. */
internal class LanePerformanceWindow(private val capacity: Int = 128) {
    private data class Sample(val at: Long, val preprocess: Double, val detection: Double, val age: Double)
    private val samples = ArrayDeque<Sample>()
    fun record(at: Long, preprocessing: Double, detection: Double, age: Double) {
        if (samples.size == capacity) samples.removeFirst()
        samples.addLast(Sample(at, preprocessing, detection, age))
    }
    fun clear() = samples.clear()
    fun summary(): LanePerformanceSummary {
        fun timing(values: List<Double>): LaneStageTiming {
            val sorted = values.sorted()
            fun quantile(p: Double) = sorted[kotlin.math.ceil((sorted.size - 1) * p).toInt()]
            return LaneStageTiming(quantile(0.50), quantile(0.95), sorted.last())
        }
        require(samples.isNotEmpty())
        val elapsed = (samples.last().at - samples.first().at) / 1e9
        return LanePerformanceSummary(samples.size, if (elapsed > 0) (samples.size - 1) / elapsed else 0.0,
            timing(samples.map { it.preprocess }), timing(samples.map { it.detection }), timing(samples.map { it.age }))
    }
}

/** Pure geometry also used by replay tests; no assumption that preview and analysis share a crop. */
internal object LaneOverlayGeometry {
    fun opacity(capturedAtNanos: Long, nowNanos: Long): Float {
        val age = (nowNanos - capturedAtNanos) / 1e9
        return when {
            capturedAtNanos <= 0 || age < 0 || age >= 0.75 -> 0f
            age <= 0.30 -> 1f
            else -> ((0.75 - age) / 0.45).toFloat()
        }
    }

    fun rawPoint(point: LanePoint, image: LaneImageGeometry): LanePoint = when (image.rotationDegrees) {
        0 -> LanePoint(point.x * image.width, point.y * image.height)
        90 -> LanePoint(point.y * image.width, (1.0 - point.x) * image.height)
        180 -> LanePoint((1.0 - point.x) * image.width, (1.0 - point.y) * image.height)
        270 -> LanePoint((1.0 - point.y) * image.width, point.x * image.height)
        else -> error("Unsupported camera rotation")
    }

    fun project(point: LanePoint, image: LaneImageGeometry, preview: LanePreviewGeometry): LanePoint? {
        if (preview.viewWidth <= 0 || preview.viewHeight <= 0 || preview.cropRight <= preview.cropLeft ||
            preview.cropBottom <= preview.cropTop) return null
        val raw = rawPoint(point, image)
        val sensor = inverseAffine(image.sensorToBuffer, raw) ?: return null
        val buffer = affine(preview.sensorToBuffer, sensor) ?: return null
        val x = buffer.x - (preview.cropLeft + preview.cropRight) / 2.0
        val y = buffer.y - (preview.cropTop + preview.cropBottom) / 2.0
        val rotated = when (preview.rotationDegrees) {
            0 -> LanePoint(x, y)
            90 -> LanePoint(-y, x)
            180 -> LanePoint(-x, -y)
            270 -> LanePoint(y, -x)
            else -> return null
        }
        val width = (preview.cropRight - preview.cropLeft).toDouble()
        val height = (preview.cropBottom - preview.cropTop).toDouble()
        val scale = if (preview.rotationDegrees % 180 == 0)
            max(preview.viewWidth / width, preview.viewHeight / height)
        else max(preview.viewWidth / height, preview.viewHeight / width)
        return LanePoint(preview.viewWidth / 2.0 + rotated.x * scale * (if (preview.mirrored) -1 else 1),
            preview.viewHeight / 2.0 + rotated.y * scale)
    }

    private fun affine(matrix: List<Double>, point: LanePoint): LanePoint? {
        if (matrix.size != 9 || matrix.any { !it.isFinite() }) return null
        val w = matrix[6] * point.x + matrix[7] * point.y + matrix[8]
        if (kotlin.math.abs(w) < 1e-9) return null
        return LanePoint((matrix[0] * point.x + matrix[1] * point.y + matrix[2]) / w,
            (matrix[3] * point.x + matrix[4] * point.y + matrix[5]) / w)
    }

    private fun inverseAffine(matrix: List<Double>, point: LanePoint): LanePoint? {
        if (matrix.size != 9 || matrix.any { !it.isFinite() } ||
            matrix[6] != 0.0 || matrix[7] != 0.0 || matrix[8] != 1.0) return null
        val determinant = matrix[0] * matrix[4] - matrix[1] * matrix[3]
        if (kotlin.math.abs(determinant) < 1e-9) return null
        val x = point.x - matrix[2]
        val y = point.y - matrix[5]
        return LanePoint((matrix[4] * x - matrix[1] * y) / determinant,
            (-matrix[3] * x + matrix[0] * y) / determinant)
    }
}

internal object LaneLumaSampler {
    fun copyUpright(source: ByteBuffer, rowStride: Int, pixelStride: Int,
        geometry: LaneImageGeometry, destination: ByteArray, width: Int, height: Int) {
        require(rowStride > 0 && pixelStride > 0 && width > 0 && height > 0)
        require(destination.size >= width * height)
        val base = source.position()
        // Absolute reads preserve the camera plane's position for TSR. Pixel centres
        // keep all four rotations inside the padded Y plane, including odd dimensions.
        for (y in 0 until height) for (x in 0 until width) {
            val u = (x + 0.5) / width
            val v = (y + 0.5) / height
            val rawX = when (geometry.rotationDegrees) { 0 -> u; 90 -> v; 180 -> 1 - u; 270 -> 1 - v; else -> error("Invalid rotation") }
            val rawY = when (geometry.rotationDegrees) { 0 -> v; 90 -> 1 - u; 180 -> 1 - v; 270 -> u; else -> error("Invalid rotation") }
            val ix = (rawX * geometry.width).toInt().coerceIn(0, geometry.width - 1)
            val iy = (rawY * geometry.height).toInt().coerceIn(0, geometry.height - 1)
            destination[y * width + x] = source.get(base + iy * rowStride + ix * pixelStride)
        }
    }
}

/** REALTIME timestamps retain capture age. UNKNOWN-origin timestamps are aligned
 * once per scope; their age is an estimate that omits the first frame's upstream
 * delay. Subsequent backlog remains visible and must never be retimed as fresh. */
internal data class LaneCaptureTime(val nanos: Long, val estimated: Boolean, val discontinuity: Boolean)

internal class LaneCaptureClock {
    private var offset: Long? = null
    private var previousCamera = Long.MIN_VALUE
    private var previousRealtime: Boolean? = null
    fun reset() { offset = null; previousCamera = Long.MIN_VALUE; previousRealtime = null }
    fun map(cameraNanos: Long, arrivalNanos: Long, realtime: Boolean = false): LaneCaptureTime {
        val changedSource = previousRealtime != null && previousRealtime != realtime
        val regressed = previousCamera != Long.MIN_VALUE && cameraNanos <= previousCamera
        val calibrated = offset?.let { cameraNanos + it }
        val jumped = !realtime && calibrated != null && calibrated > arrivalNanos + 50_000_000L
        if (offset == null || changedSource || regressed || jumped) {
            offset = arrivalNanos - cameraNanos
        }
        previousCamera = cameraNanos
        previousRealtime = realtime
        return LaneCaptureTime(if (realtime) cameraNanos else
            (cameraNanos + requireNotNull(offset)).coerceAtMost(arrivalNanos),
            estimated = !realtime, discontinuity = changedSource || regressed || jumped)
    }
}

internal data class LaneAdmission(val enabled: Boolean, val scope: Long, val thermallyPaused: Boolean)
internal data class LaneLumaSource(val plane: ByteBuffer, val rowStride: Int, val pixelStride: Int,
    val geometry: LaneImageGeometry, val capturedAtNanos: Long)

/** Single worker, at most one pending downsampled image, and no retained ImageProxy. */
internal class AndroidLaneDetectionRuntime(
    private val mainExecutor: Executor,
    private val admission: () -> LaneAdmission,
    private val clockIsRealtime: () -> Boolean,
    private val onResult: (LaneRuntimeSnapshot) -> Unit,
    private val onDiagnostics: (LaneRuntimeSnapshot) -> Unit,
    private val nowNanos: () -> Long = SystemClock::elapsedRealtimeNanos,
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { task ->
        Thread({ Process.setThreadPriority(Process.THREAD_PRIORITY_BACKGROUND); task.run() }, "YouSpeedLanes")
    },
) : AutoCloseable {
    private data class Frame(val bytes: ByteArray, val width: Int, val height: Int,
        val geometry: LaneImageGeometry, val scope: Long, val epoch: Long, val captureNanos: Long,
        val frameId: Long, val preprocessingMs: Double, val captureAgeEstimated: Boolean)
    private val lock = Any()
    private val detector = LaneDetector()
    private val tracker = LaneTracker()
    // Owned by the serial worker across idle periods, so consecutive 5 Hz
    // frames actually confirm each other instead of restarting the tracker.
    private var trackerEpoch = Long.MIN_VALUE
    private val clock = LaneCaptureClock()
    private val performance = LanePerformanceWindow()
    private val buffers = ArrayDeque<ByteArray>()
    private var pending: Frame? = null
    private var working = false
    private var closed = false
    private var scope = Long.MIN_VALUE
    private var epoch = 0L
    private var geometry: LaneImageGeometry? = null
    private var paused = true
    private var lastAdmissionNanos = Long.MIN_VALUE
    private var frameId = 0L
    private var processed = 0L
    private var replaced = 0L
    private var throttled = 0L
    private var timestampRejected = 0L
    private var lastDiagnosticsNanos = 0L

    /** Called before TSR takes ownership; only admitted frames are copied. */
    fun submit(image: ImageProxy) = submit {
        val values = FloatArray(9).also(image.imageInfo.sensorToBufferTransformMatrix::getValues)
        val plane = image.planes.first()
        LaneLumaSource(plane.buffer, plane.rowStride, plane.pixelStride,
            LaneImageGeometry(image.width, image.height, image.imageInfo.rotationDegrees, values.map(Float::toDouble)),
            image.imageInfo.timestamp)
    }

    /** Lazy source access makes off/thermal/rate gates run before camera-plane reads. */
    internal fun submit(source: () -> LaneLumaSource) {
        val now = nowNanos()
        val condition = admission()
        synchronized(lock) {
            if (closed) return
            val shouldPause = !condition.enabled || condition.thermallyPaused
            if (scope != condition.scope || paused != shouldPause) {
                invalidateLocked()
                scope = condition.scope
                paused = shouldPause
                publish(LaneRuntimeSnapshot(if (paused) LanePresentationState.PAUSED else LanePresentationState.UNAVAILABLE,
                    scope = scope), epoch)
            }
            if (paused) return
            if (lastAdmissionNanos != Long.MIN_VALUE && now - lastAdmissionNanos < 200_000_000L) {
                throttled++
                return
            }
            lastAdmissionNanos = now
            val preprocessStart = nowNanos()
            runCatching {
                val input = source()
                val incoming = input.geometry
                if (geometry != incoming) {
                    invalidateLocked()
                    geometry = incoming
                    publish(LaneRuntimeSnapshot(LanePresentationState.UNAVAILABLE, scope = scope), epoch)
                }
                lastAdmissionNanos = now
                val capture = clock.map(input.capturedAtNanos, now, clockIsRealtime())
                if (capture.discontinuity) {
                    epoch++
                    pending?.let { recycleLocked(it.bytes) }
                    pending = null
                    publish(LaneRuntimeSnapshot(LanePresentationState.UNAVAILABLE, scope = scope), epoch)
                }
                // A backed-up camera image cannot become a fresh overlay merely
                // because inference is quick. UNKNOWN-origin clocks are marked
                // estimated explicitly in diagnostics.
                if (capture.nanos <= 0 || capture.nanos > now || now - capture.nanos >= 750_000_000L) {
                    timestampRejected++
                    return
                }
                val scale = minOf(384.0 / incoming.uprightWidth, 768.0 / incoming.uprightHeight, 1.0)
                val width = max(1, (incoming.uprightWidth * scale).roundToInt())
                val height = max(1, (incoming.uprightHeight * scale).roundToInt())
                val bytes = buffers.firstOrNull { it.size == width * height }?.also(buffers::remove)
                    ?: ByteArray(width * height)
                LaneLumaSampler.copyUpright(input.plane, input.rowStride, input.pixelStride, incoming, bytes, width, height)
                val frame = Frame(bytes, width, height, incoming, scope, epoch,
                    capture.nanos, ++frameId,
                    (nowNanos() - preprocessStart) / 1e6, capture.estimated)
                pending?.let { recycleLocked(it.bytes); replaced++ }
                pending = frame
                if (!working) {
                    working = true
                    executor.execute(::drain)
                }
            }.onFailure {
                invalidateLocked()
                publish(LaneRuntimeSnapshot(LanePresentationState.UNAVAILABLE, scope = scope), epoch)
            }
        }
    }

    private fun drain() {
        while (true) {
            val frame = synchronized(lock) {
                val next = pending
                pending = null
                if (next == null) working = false
                next
            } ?: return
            val condition = admission()
            val valid = synchronized(lock) {
                val stale = nowNanos() - frame.captureNanos >= 750_000_000L
                val allowed = !closed && frame.epoch == epoch && frame.scope == condition.scope &&
                    condition.enabled && !condition.thermallyPaused && !stale
                if (!allowed) {
                    recycleLocked(frame.bytes)
                    if (stale) timestampRejected++
                }
                allowed
            }
            if (!valid) continue
            if (frame.epoch != trackerEpoch) { tracker.reset(); trackerEpoch = frame.epoch }
            val started = nowNanos()
            val result = runCatching { tracker.update(detector.detect(frame.bytes, frame.width, frame.height,
                frame.captureNanos / 1e9)) }
            val finished = nowNanos()
            synchronized(lock) {
                recycleLocked(frame.bytes)
                if (closed || frame.epoch != epoch) return@synchronized
                processed++
                val estimate = result.getOrNull()
                val snapshot = LaneRuntimeSnapshot(
                    state = when (estimate?.state) {
                        LaneDetectionState.RELIABLE -> LanePresentationState.RELIABLE
                        LaneDetectionState.UNCERTAIN -> LanePresentationState.UNCERTAIN
                        else -> LanePresentationState.UNAVAILABLE
                    },
                    estimate = estimate, geometry = frame.geometry, scope = frame.scope,
                    capturedAtNanos = frame.captureNanos, frameId = frame.frameId,
                    preprocessingMs = frame.preprocessingMs, detectionMs = (finished - started) / 1e6,
                    captureToResultMs = (finished - frame.captureNanos) / 1e6,
                    captureAgeEstimated = frame.captureAgeEstimated,
                    processedFrames = processed, replacedFrames = replaced, throttledFrames = throttled,
                    timestampRejectedFrames = timestampRejected,
                )
                publish(snapshot, frame.epoch)
                performance.record(finished, snapshot.preprocessingMs, snapshot.detectionMs, snapshot.captureToResultMs)
                if (finished - lastDiagnosticsNanos >= 5_000_000_000L) {
                    lastDiagnosticsNanos = finished
                    val diagnostic = snapshot.copy(performance = performance.summary())
                    mainExecutor.execute { if (isCurrent(frame.epoch, frame.scope)) onDiagnostics(diagnostic) }
                }
            }
        }
    }

    private fun isCurrent(candidateEpoch: Long, candidateScope: Long): Boolean {
        val condition = admission()
        return synchronized(lock) { !closed && epoch == candidateEpoch && scope == candidateScope &&
            condition.scope == candidateScope }
    }

    private fun publish(snapshot: LaneRuntimeSnapshot, candidateEpoch: Long) {
        mainExecutor.execute {
            if (isCurrent(candidateEpoch, snapshot.scope)) {
                val condition = admission()
                onResult(if (!condition.enabled || condition.thermallyPaused)
                    LaneRuntimeSnapshot(LanePresentationState.PAUSED, scope = snapshot.scope) else snapshot)
            }
        }
    }

    private fun recycleLocked(bytes: ByteArray) { if (buffers.size < 2) buffers.addLast(bytes) }
    private fun invalidateLocked() {
        epoch++
        pending?.let { recycleLocked(it.bytes) }
        pending = null
        geometry = null
        clock.reset()
        performance.clear()
        lastAdmissionNanos = Long.MIN_VALUE
    }

    override fun close() {
        synchronized(lock) { closed = true; invalidateLocked(); buffers.clear() }
        executor.shutdown()
    }
}

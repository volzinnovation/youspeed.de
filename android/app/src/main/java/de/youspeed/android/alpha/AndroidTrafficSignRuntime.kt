package de.youspeed.android.alpha

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CameraCharacteristics
import android.os.PowerManager
import android.os.Handler
import android.os.Looper
import android.util.Size
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.core.ExtendableBuilder
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.FileInputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.security.MessageDigest
import java.time.Instant
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.max
import kotlin.math.min
import org.tensorflow.lite.DataType
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.gpu.CompatibilityList
import org.tensorflow.lite.gpu.GpuDelegate
import org.tensorflow.lite.gpu.GpuDelegateFactory

enum class TrafficSignCameraRuntimeState {
    DISABLED,
    REQUESTING_PERMISSION,
    STARTING,
    ACTIVE,
    DENIED,
    UNAVAILABLE,
    FAILED,
}

internal data class AndroidTrafficSignVerifiedPack(
    val modelPack: TrafficSignModelPack,
    val detectorArtifact: TrafficSignArtifact,
    val classifierArtifact: TrafficSignArtifact,
    val detectorModel: MappedByteBuffer,
    val classifierModel: MappedByteBuffer,
    val displayCatalog: TrafficSignDisplayCatalog,
    val manifestSHA256: String = "",
)

internal object AndroidTrafficSignModelPackLoader {
    const val PACK_ASSET_ROOT = "tsr/DE.panoramax-bootstrap.tsrmodelpack"
    const val MANIFEST_ASSET_PATH = "$PACK_ASSET_ROOT/manifest.json"

    fun load(context: Context, countryCode: String = "DE"): AndroidTrafficSignVerifiedPack {
        val normalizedCountry = AndroidTrafficSignModelPackSelection.availableCountryCode(countryCode)
            ?: error("No bundled Android TSR pack for country $countryCode")
        val packAssetRoot = AndroidTrafficSignModelPackSelection.assetRoot(normalizedCountry)
        val manifestAssetPath = "$packAssetRoot/manifest.json"
        val assets = context.assets
        val manifestBytes = assets.open(manifestAssetPath).use { it.readBytes() }
        val modelPack = TrafficSignModelPackJson.decode(manifestBytes.toString(Charsets.UTF_8))
        TrafficSignModelPackValidator.requireValid(modelPack)
        require(modelPack.countries.any { PenaltyCountryCodes.alpha2(it) == normalizedCountry }) {
            "The bundled Android TSR pack does not support $normalizedCountry"
        }
        require(modelPack.pipeline == TrafficSignPipeline.PROPOSAL_CLASSIFICATION) {
            "The bundled Android TSR pack must use proposal classification"
        }
        val detectorArtifact = requireNotNull(modelPack.androidArtifact(modelPack.detector)) {
            "The bundled TSR pack has no Android detector"
        }
        val classifierComponent = requireNotNull(modelPack.classifier) {
            "The bundled TSR pack has no classifier component"
        }
        val classifierArtifact = requireNotNull(modelPack.androidArtifact(classifierComponent)) {
            "The bundled TSR pack has no Android classifier"
        }
        require(detectorArtifact.format == TrafficSignArtifactFormat.TFLITE)
        require(classifierArtifact.format == TrafficSignArtifactFormat.TFLITE)
        require(detectorArtifact.inputShape == listOf(1, DETECTOR_SIZE, DETECTOR_SIZE, 3))
        require(classifierArtifact.inputShape == listOf(1, CLASSIFIER_SIZE, CLASSIFIER_SIZE, 3))
        require(detectorArtifact.outputSchema == "yolo_raw_xywh_class_scores_v1")
        require(classifierArtifact.outputSchema == "classification_probabilities_v1")

        val displayCatalog = assets.open(TrafficSignDisplayCatalog.assetPath(normalizedCountry)).bufferedReader().use {
            TrafficSignDisplayCatalog.decode(it.readText(), expectedCountryCode = normalizedCountry)
        }
        require(displayCatalog.checkpointSha256 == classifierComponent.sourceCheckpoint.sha256) {
            "TSR class catalog does not match the classifier checkpoint"
        }
        val detectorModel = mapAndVerify(context, packAssetRoot, detectorArtifact)
        val classifierModel = mapAndVerify(context, packAssetRoot, classifierArtifact)
        return AndroidTrafficSignVerifiedPack(
            modelPack = modelPack,
            detectorArtifact = detectorArtifact,
            classifierArtifact = classifierArtifact,
            detectorModel = detectorModel,
            classifierModel = classifierModel,
            displayCatalog = displayCatalog,
            manifestSHA256 = MessageDigest.getInstance("SHA-256").digest(manifestBytes).joinToString("") { "%02x".format(it) },
        )
    }

    private fun mapAndVerify(context: Context, packAssetRoot: String, artifact: TrafficSignArtifact): MappedByteBuffer {
        val assetPath = "$packAssetRoot/${artifact.path}"
        val mapped = context.assets.openFd(assetPath).use { descriptor ->
            FileInputStream(descriptor.fileDescriptor).channel.use { channel ->
                channel.map(
                    java.nio.channels.FileChannel.MapMode.READ_ONLY,
                    descriptor.startOffset,
                    descriptor.declaredLength,
                )
            }
        }
        val digestBuffer = mapped.duplicate().apply { position(0) }
        val digest = MessageDigest.getInstance("SHA-256").apply { update(digestBuffer) }
        val actualHash = digest.digest()
            .joinToString("") { byte -> "%02x".format(Locale.US, byte.toInt() and 0xff) }
        require(actualHash == artifact.sha256) {
            "TSR artifact hash mismatch for ${artifact.path}"
        }
        mapped.position(0)
        return mapped
    }

    private const val DETECTOR_SIZE = 1280
    private const val CLASSIFIER_SIZE = 224
}

/** Release the camera buffer once the independent bitmap exists, before model work.
 * Kept separate from the frame lifetime: metadata/prepared geometry remain valid until fusion.
 */
internal class CameraXImageLease(private val closeImage: () -> Unit, private val onClosed: (String) -> Unit = {}) {
    private val closed = AtomicBoolean(false)
    val isClosed: Boolean get() = closed.get()
    fun close(reason: String) {
        if (closed.compareAndSet(false, true)) {
            try { closeImage() } finally { onClosed(reason) }
        }
    }
    fun <T> copyAndClose(copy: () -> T): T {
        check(!closed.get()) { "Camera image was already closed" }
        var copied = false
        try { return copy().also { copied = true } }
        finally { close(if (copied) "bitmap_copied" else "bitmap_copy_failed") }
    }
}

/** Fixed-size timing windows and cumulative counters; no images or per-frame log writes. */
internal class CameraAnalysisCadenceWindow {
    private val intervals = ArrayDeque<Double>()
    private val holds = ArrayDeque<Double>()
    private val bitmapHolds = ArrayDeque<Double>()
    private val counts = linkedMapOf<String, Long>()
    private var lastDelivery: Long? = null
    private var lastReport: Long? = null
    private fun append(window: ArrayDeque<Double>, value: Double) {
        if (window.size == 128) window.removeFirst()
        window.addLast(value.coerceAtLeast(0.0))
    }
    @Synchronized fun delivered(now: Long) {
        lastDelivery?.let { previous -> if (now >= previous) append(intervals, (now-previous)/1e6) }
        lastDelivery = now
        counts["delivered"] = (counts["delivered"] ?: 0)+1
        if (lastReport == null) lastReport = now
    }
    @Synchronized fun event(reason: String) { counts[reason] = (counts[reason] ?: 0)+1 }
    @Synchronized fun closed(reason: String, heldMs: Double) {
        event(reason); append(holds,heldMs)
        if (reason == "bitmap_copied") append(bitmapHolds,heldMs)
    }
    @Synchronized fun reportIfDue(now: Long): Map<String,Any>? {
        if (lastReport == null || now-(lastReport ?: now)<5_000_000_000L) return null
        lastReport = now
        fun timing(values: Collection<Double>): Map<String,Any> {
            if (values.isEmpty()) return mapOf("samples" to 0)
            val sorted = values.sorted()
            fun quantile(p: Double) = sorted[kotlin.math.ceil((sorted.size-1)*p).toInt()]
            return mapOf("samples" to sorted.size,"p50Ms" to quantile(0.5),"p95Ms" to quantile(0.95),"maxMs" to sorted.last())
        }
        return mapOf("counts" to counts.toMap(),"deliveryInterval" to timing(intervals),
            "cameraHold" to timing(holds),"copiedInputCameraHold" to timing(bitmapHolds),
            "pendingCameraInputsAllowed" to false,"timingWindowCapacity" to 128)
    }
}

/** Owns camera pixels only through preparation/copy; frame metadata lives through inference. */
internal class CameraXTrafficSignFrame(
    private val image: ImageProxy,
    private val pathIntrinsics: RoadPathCameraIntrinsics? = null,
    private val pathClockKnown: Boolean = false,
    private val pathCameraGeneration: Long = 0,
    savedVisualCalibration: VisualRoadCalibration? = null,
    onCameraReleased: (String, Double) -> Unit = { _, _ -> },
) : TrafficSignNormalizedFrameHandle {
    val receivedAtNanos: Long = System.nanoTime()
    private val released = AtomicBoolean(false)
    private val imageLease = CameraXImageLease(image::close) { reason ->
        onCameraReleased(reason, (System.nanoTime()-receivedAtNanos)/1e6)
    }
    private val rotationDegrees = image.imageInfo.rotationDegrees

    override val frameId: String = UUID.randomUUID().toString().lowercase(Locale.US)
    override val source: TrafficSignInputSource = TrafficSignInputSource.LIVE_FRAME
    override val capturedAtUtc: Instant = Instant.now()
    override val capturedAtMonotonicNanos: Long = image.imageInfo.timestamp.coerceAtLeast(0L)
    override val widthPixels: Int = if (rotationDegrees == 90 || rotationDegrees == 270) image.height else image.width
    override val heightPixels: Int = if (rotationDegrees == 90 || rotationDegrees == 270) image.width else image.height
    val orientationKey = "rear:rotation:$rotationDegrees"
    val visualCalibration = savedVisualCalibration?.takeIf { it.compatible(widthPixels, heightPixels, orientationKey) }

    private val pathCaptureSeconds = capturedAtUtc.toEpochMilli() / 1000.0 -
        if (pathClockKnown) (android.os.SystemClock.elapsedRealtimeNanos() - image.imageInfo.timestamp) / 1e9 else 0.0

    var preparedRoadPath: RoadPathPreparedFrame? = null
    var roadPathPreparationFailure: String? = null
    var roadPathInferenceStartedNanos: Long? = null

    fun roadPathFrame(): RoadPathCameraFrame? {
        check(!imageLease.isClosed) { "Road geometry must be copied before closing camera pixels" }
        val start = System.nanoTime()
        if (!pathCaptureSeconds.isFinite()) return null
        val values = FloatArray(9).also(image.imageInfo.sensorToBufferTransformMatrix::getValues)
        val geometry = LaneImageGeometry(image.width, image.height, rotationDegrees, values.map(Float::toDouble))
        val scale = minOf(384.0 / geometry.uprightWidth, 216.0 / geometry.uprightHeight, 1.0)
        val width = (geometry.uprightWidth * scale).toInt().coerceAtLeast(1)
        val height = (geometry.uprightHeight * scale).toInt().coerceAtLeast(1)
        val bytes = ByteArray(width * height)
        val plane = image.planes.firstOrNull() ?: return null
        LaneLumaSampler.copyUpright(plane.buffer, plane.rowStride, plane.pixelStride, geometry, bytes, width, height)
        return RoadPathCameraFrame(bytes, width, height, pathCaptureSeconds,
            "$pathCameraGeneration:${image.width}x${image.height}:$rotationDegrees:${values.joinToString()}",
            pathIntrinsics?.calibration(image), pathClockKnown, (System.nanoTime() - start) / 1e6, start,
            image.width, image.height, rotationDegrees, values.map(Float::toDouble),
            sourceTimestampSeconds = image.imageInfo.timestamp / 1e9,
            visualCalibration = visualCalibration, orientationKey = orientationKey)
    }

    fun <T> withOrientedBitmap(rotationBuffer: AndroidTrafficSignBitmapRotation, consume: (Bitmap) -> T): T {
        check(!released.get()) { "Camera frame was already released" }
        // toBitmap makes independent ARGB pixels. CameraX KEEP_ONLY_LATEST cannot
        // deliver another lane exposure until this proxy closes; inference needs only bitmap.
        val sourceBitmap = imageLease.copyAndClose { image.toBitmap() }
        try {
            return consume(rotationBuffer.orient(sourceBitmap, rotationDegrees))
        } finally {
            sourceBitmap.recycle()
        }
    }

    override fun release() {
        if (released.compareAndSet(false, true)) imageLease.close("frame_released")
    }
}

internal data class AndroidYoloProposal(
    val score: Float,
    val box: NormalizedTrafficSignBoundingBox,
)

/** Decodes normalized LiteRT xywh boxes for channel 0 (`sign`); `plate` and `face` are out of scope. */
internal object AndroidYoloSignDecoder {
    const val OUTPUT_CHANNELS = 7
    const val OUTPUT_ELEMENTS = 33_600
    const val SIGN_SCORE_CHANNEL = 4

    fun decode(
        output: FloatArray,
        sourceWidth: Int,
        sourceHeight: Int,
        inputSize: Int,
        minimumScore: Double,
        maximumProposals: Int = 12,
        nmsIou: Double = 0.45,
    ): List<AndroidYoloProposal> {
        require(output.size == OUTPUT_CHANNELS * OUTPUT_ELEMENTS)
        require(sourceWidth > 0 && sourceHeight > 0 && inputSize > 0)
        val scale = min(inputSize.toDouble() / sourceWidth, inputSize.toDouble() / sourceHeight)
        val scaledWidth = sourceWidth * scale
        val scaledHeight = sourceHeight * scale
        val padX = (inputSize - scaledWidth) / 2.0
        val padY = (inputSize - scaledHeight) / 2.0
        val proposals = buildList {
            for (index in 0 until OUTPUT_ELEMENTS) {
                val score = output[SIGN_SCORE_CHANNEL * OUTPUT_ELEMENTS + index]
                if (!score.isFinite() || score < minimumScore) continue
                // The pinned Ultralytics LiteRT export normalizes xywh by its input dimensions.
                // Restore input pixels before removing letterbox padding and scaling to the source.
                val centerX = output[index].toDouble() * inputSize
                val centerY = output[OUTPUT_ELEMENTS + index].toDouble() * inputSize
                val width = output[2 * OUTPUT_ELEMENTS + index].toDouble() * inputSize
                val height = output[3 * OUTPUT_ELEMENTS + index].toDouble() * inputSize
                if (!centerX.isFinite() || !centerY.isFinite() || !width.isFinite() || !height.isFinite() ||
                    width <= 0.0 || height <= 0.0
                ) continue
                val left = ((centerX - width / 2.0 - padX) / scale).coerceIn(0.0, sourceWidth.toDouble())
                val top = ((centerY - height / 2.0 - padY) / scale).coerceIn(0.0, sourceHeight.toDouble())
                val right = ((centerX + width / 2.0 - padX) / scale).coerceIn(0.0, sourceWidth.toDouble())
                val bottom = ((centerY + height / 2.0 - padY) / scale).coerceIn(0.0, sourceHeight.toDouble())
                if (right <= left || bottom <= top) continue
                add(
                    AndroidYoloProposal(
                        score = score,
                        box = NormalizedTrafficSignBoundingBox(
                            x = left / sourceWidth,
                            y = top / sourceHeight,
                            width = (right - left) / sourceWidth,
                            height = (bottom - top) / sourceHeight,
                        ),
                    ),
                )
            }
        }.sortedByDescending(AndroidYoloProposal::score)

        val retained = mutableListOf<AndroidYoloProposal>()
        for (proposal in proposals) {
            if (retained.none { it.box.intersectionOverUnion(proposal.box) > nmsIou }) {
                retained += proposal
                if (retained.size == maximumProposals) break
            }
        }
        return retained
    }
}

internal fun primaryDetection(detections: List<TrafficSignDetection>): TrafficSignDetection? = detections
    .filter { it.candidate.normalizedPrimarySemantic().kind !in setOf(TrafficSignSemanticKind.UNKNOWN, TrafficSignSemanticKind.NON_SPEED_RESTRICTION_END) }
    .maxByOrNull { it.candidate.rawScore }
    ?: detections.maxByOrNull { it.candidate.rawScore }

internal data class AndroidTrafficSignInferenceResult(
    val detections: List<TrafficSignDetection>,
    val detectorProposalCount: Int,
    val detectorTopScore: Double?,
    val classifierInvocationCount: Int,
    val classifiedDetectionCount: Int,
    val classifierTopScore: Double?,
    val inferenceMs: Double,
    val detectorRawSignTopScore: Double?,
    val detectorRawGlobalTopScore: Double?,
    val detectorRawSignScoresAboveThreshold: Int,
    val sourceWidthPixels: Int,
    val sourceHeightPixels: Int,
    val sourceLumaMean: Double?,
    val executionBackend: String,
    val accelerationFallbackReason: String?,
    val detectorPreprocessingMs: Double,
    val detectorInferenceMs: Double,
    val classifierInferenceMs: Double,
)

internal class AndroidLiteRtTrafficSignInferenceEngine(
    private val verifiedPack: AndroidTrafficSignVerifiedPack,
    // CPU mode is a fixture-parity test control, not a user setting.
    allowGpu: Boolean = true,
    // Keep the production precision until device fixture and preview benchmarks approve a change.
    val gpuPrecisionLossAllowed: Boolean = true,
) : AutoCloseable {
    private class InterpreterResources(val interpreter: Interpreter, private val delegate: GpuDelegate?) : AutoCloseable {
        override fun close() {
            try {
                interpreter.close()
            } finally {
                delegate?.close()
            }
        }
    }

    private data class GpuConfiguration(val options: GpuDelegateFactory.Options?, val unavailableReason: String?)

    private val gpuConfiguration = if (!allowGpu) GpuConfiguration(null, null) else {
        try {
            CompatibilityList().use { compatibility ->
                if (compatibility.isDelegateSupportedOnThisDevice) {
                    GpuConfiguration(
                        compatibility.bestOptionsForThisDevice
                            .setPrecisionLossAllowed(gpuPrecisionLossAllowed)
                            // Exhaustive OpenCL tuning can block in the Mali driver's
                            // profiling queue. Fast tuning avoids that startup path.
                            .setInferencePreference(GpuDelegateFactory.Options.INFERENCE_PREFERENCE_FAST_SINGLE_ANSWER),
                        null,
                    )
                } else GpuConfiguration(null, "GPU delegate is unsupported on this device")
            }
        } catch (failure: RuntimeException) {
            GpuConfiguration(null, "GPU compatibility check failed: ${failure.message ?: failure.javaClass.simpleName}")
        } catch (failure: LinkageError) {
            GpuConfiguration(null, "GPU runtime unavailable: ${failure.message ?: failure.javaClass.simpleName}")
        }
    }
    private val detector = createInterpreter(verifiedPack.detectorModel, "detector")
    private val classifier = try {
        createInterpreter(verifiedPack.classifierModel, "classifier")
    } catch (failure: Throwable) {
        detector.close()
        throw failure
    }
    private val detectorInput = directFloatBuffer(DETECTOR_SIZE * DETECTOR_SIZE * RGB_CHANNELS)
    private val detectorOutput = directFloatBuffer(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
    private val detectorOutputFloats = FloatArray(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
    private val classifierInput = directFloatBuffer(CLASSIFIER_SIZE * CLASSIFIER_SIZE * RGB_CHANNELS)
    private val classifierClassCount = verifiedPack.displayCatalog.classLabels.size
    private val classifierOutput = directFloatBuffer(classifierClassCount)
    private val detectorBitmap = Bitmap.createBitmap(DETECTOR_SIZE, DETECTOR_SIZE, Bitmap.Config.ARGB_8888)
    private val classifierBitmap = Bitmap.createBitmap(CLASSIFIER_SIZE, CLASSIFIER_SIZE, Bitmap.Config.ARGB_8888)
    private val detectorPixels = IntArray(DETECTOR_SIZE * DETECTOR_SIZE)
    private val classifierPixels = IntArray(CLASSIFIER_SIZE * CLASSIFIER_SIZE)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    private val rgbTensorEncoder = TrafficSignRgbTensorEncoder()
    private val mappingsByClassId = verifiedPack.modelPack.classMapping.associateBy(TrafficSignClassMapping::classId)

    private fun createInterpreter(model: ByteBuffer, role: String): TrafficSignInferenceFallback<InterpreterResources> {
        fun options() = Interpreter.Options().apply {
            setNumThreads(4)
            setUseXNNPACK(true)
        }
        return TrafficSignInferenceFallback(
            createCpu = { InterpreterResources(Interpreter(model.duplicate(), options()), null) },
            createAccelerated = gpuConfiguration.options?.let { gpuOptions ->
                {
                    val delegate = GpuDelegate(gpuOptions)
                    try {
                        InterpreterResources(Interpreter(model.duplicate(), options().addDelegate(delegate)), delegate)
                    } catch (failure: Throwable) {
                        delegate.close()
                        throw failure
                    }
                }
            },
            unavailableReason = gpuConfiguration.unavailableReason,
            onCpuFallback = { reason -> Log.w("YouSpeedTSR", "$role uses CPU fallback: $reason") },
        )
    }

    init {
        try {
            detector.run { resource ->
                val interpreter = resource.interpreter
                require(interpreter.getInputTensor(0).shape().contentEquals(intArrayOf(1, DETECTOR_SIZE, DETECTOR_SIZE, RGB_CHANNELS)))
                require(interpreter.getInputTensor(0).dataType() == DataType.FLOAT32)
                require(interpreter.getOutputTensor(0).shape().contentEquals(intArrayOf(1, 7, 33_600)))
                require(interpreter.getOutputTensor(0).dataType() == DataType.FLOAT32)
            }
            classifier.run { resource ->
                val interpreter = resource.interpreter
                require(interpreter.getInputTensor(0).shape().contentEquals(intArrayOf(1, CLASSIFIER_SIZE, CLASSIFIER_SIZE, RGB_CHANNELS)))
                require(interpreter.getInputTensor(0).dataType() == DataType.FLOAT32)
                require(interpreter.getOutputTensor(0).shape().contentEquals(intArrayOf(1, classifierClassCount)))
                require(interpreter.getOutputTensor(0).dataType() == DataType.FLOAT32)
            }
        } catch (failure: Throwable) {
            close()
            throw failure
        }
    }

    fun recognize(source: Bitmap): TrafficSignDetection? = primaryDetection(recognizeAll(source))

    fun recognizeAll(source: Bitmap): List<TrafficSignDetection> {
        return recognizeAllWithDiagnostics(source).detections
    }

    fun recognizeAllWithDiagnostics(source: Bitmap): AndroidTrafficSignInferenceResult {
        val startedAtNanos = System.nanoTime()
        prepareDetectorInput(source)
        val detectorPreprocessingMs = elapsedMs(startedAtNanos)
        val detectorStartedAtNanos = System.nanoTime()
        detector.run { resource ->
            detectorInput.rewind()
            detectorOutput.clear()
            resource.interpreter.run(detectorInput, detectorOutput)
        }
        val detectorInferenceMs = elapsedMs(detectorStartedAtNanos)
        detectorOutput.rewind()
        detectorOutput.asFloatBuffer().get(detectorOutputFloats)
        val proposals = AndroidYoloSignDecoder.decode(
            output = detectorOutputFloats,
            sourceWidth = source.width,
            sourceHeight = source.height,
            inputSize = DETECTOR_SIZE,
            minimumScore = verifiedPack.modelPack.thresholds.unknown,
        )
        val rawOutput = TrafficSignTensorDiagnostics.summarize(
            detectorOutputFloats,
            signOffset = AndroidYoloSignDecoder.SIGN_SCORE_CHANNEL * AndroidYoloSignDecoder.OUTPUT_ELEMENTS,
            signCount = AndroidYoloSignDecoder.OUTPUT_ELEMENTS,
            minimumScore = verifiedPack.modelPack.thresholds.unknown,
        )
        val lumaMean = sourceLumaMean(source)

        val classified = proposals.map { proposal -> classify(source, proposal) }
        val detections = classified.mapNotNull(ClassificationResult::detection)
        return AndroidTrafficSignInferenceResult(
            detections = detections,
            detectorProposalCount = proposals.size,
            detectorTopScore = proposals.maxOfOrNull { it.score.toDouble() },
            classifierInvocationCount = classified.count { it.classifierScore != null },
            classifiedDetectionCount = detections.size,
            classifierTopScore = classified.mapNotNull { it.classifierScore }.maxOrNull(),
            inferenceMs = (System.nanoTime() - startedAtNanos).coerceAtLeast(0L) / 1_000_000.0,
            detectorRawSignTopScore = rawOutput.signTopScore,
            detectorRawGlobalTopScore = rawOutput.globalTopScore,
            detectorRawSignScoresAboveThreshold = rawOutput.signScoresAboveThreshold,
            sourceWidthPixels = source.width,
            sourceHeightPixels = source.height,
            sourceLumaMean = lumaMean,
            executionBackend = if (detector.executionBackend == classifier.executionBackend) detector.executionBackend else "mixed",
            accelerationFallbackReason = listOfNotNull(
                detector.accelerationFallbackReason?.let { "detector: $it" },
                classifier.accelerationFallbackReason?.let { "classifier: $it" },
            ).takeIf { it.isNotEmpty() }?.joinToString("; "),
            detectorPreprocessingMs = detectorPreprocessingMs,
            detectorInferenceMs = detectorInferenceMs,
            classifierInferenceMs = classified.sumOf(ClassificationResult::inferenceMs),
        )
    }

    private fun sourceLumaMean(source: Bitmap): Double? {
        val sampleStep = 32
        var sum = 0.0
        var count = 0
        var y = 0
        while (y < source.height) {
            var x = 0
            while (x < source.width) {
                val color = source.getPixel(x, y)
                sum += 0.299 * Color.red(color) + 0.587 * Color.green(color) + 0.114 * Color.blue(color)
                count += 1
                x += sampleStep
            }
            y += sampleStep
        }
        return count.takeIf { it > 0 }?.let { sum / it.toDouble() }
    }

    private fun prepareDetectorInput(source: Bitmap) {
        val scale = min(DETECTOR_SIZE.toFloat() / source.width, DETECTOR_SIZE.toFloat() / source.height)
        val drawWidth = source.width * scale
        val drawHeight = source.height * scale
        val left = (DETECTOR_SIZE - drawWidth) / 2f
        val top = (DETECTOR_SIZE - drawHeight) / 2f
        Canvas(detectorBitmap).apply {
            drawColor(Color.rgb(114, 114, 114))
            drawBitmap(source, null, RectF(left, top, left + drawWidth, top + drawHeight), paint)
        }
        detectorBitmap.getPixels(detectorPixels, 0, DETECTOR_SIZE, 0, 0, DETECTOR_SIZE, DETECTOR_SIZE)
        writeRgbFloats(detectorInput, detectorPixels)
    }

    /** Runs the pinned classifier on an explicitly supplied crop; used for reproducible capability probes. */
    internal fun classifyCropForDiagnostic(source: Bitmap): TrafficSignDetection? = classify(
        source, AndroidYoloProposal(1f, NormalizedTrafficSignBoundingBox(0.0, 0.0, 1.0, 1.0)), minimumScore = 0.0,
    ).detection

    private data class ClassificationResult(
        val detection: TrafficSignDetection?,
        val classifierScore: Double?,
        val inferenceMs: Double = 0.0,
    )

    private fun classify(source: Bitmap, proposal: AndroidYoloProposal, minimumScore: Double = verifiedPack.modelPack.thresholds.unknown): ClassificationResult {
        val box = proposal.box
        val left = ((box.x - box.width * HORIZONTAL_CROP_PADDING) * source.width).coerceAtLeast(0.0)
        val top = ((box.y - box.height * TOP_CROP_PADDING) * source.height).coerceAtLeast(0.0)
        val right = ((box.x + box.width * (1.0 + HORIZONTAL_CROP_PADDING)) * source.width)
            .coerceAtMost(source.width.toDouble())
        val bottom = ((box.y + box.height * (1.0 + BOTTOM_CROP_EXTENSION)) * source.height)
            .coerceAtMost(source.height.toDouble())
        if (right <= left || bottom <= top) return ClassificationResult(null, null)

        Canvas(classifierBitmap).apply {
            drawColor(Color.BLACK)
            drawBitmap(
                source,
                Rect(
                    left.toInt(),
                    top.toInt(),
                    right.toInt().coerceAtLeast(left.toInt() + 1),
                    bottom.toInt().coerceAtLeast(top.toInt() + 1),
                ),
                RectF(0f, 0f, CLASSIFIER_SIZE.toFloat(), CLASSIFIER_SIZE.toFloat()),
                paint,
            )
        }
        classifierBitmap.getPixels(
            classifierPixels,
            0,
            CLASSIFIER_SIZE,
            0,
            0,
            CLASSIFIER_SIZE,
            CLASSIFIER_SIZE,
        )
        writeRgbFloats(classifierInput, classifierPixels)
        val classifierStartedAtNanos = System.nanoTime()
        classifier.run { resource ->
            classifierInput.rewind()
            classifierOutput.clear()
            resource.interpreter.run(classifierInput, classifierOutput)
        }
        val classifierInferenceMs = elapsedMs(classifierStartedAtNanos)
        classifierOutput.rewind()
        val scores = classifierOutput.asFloatBuffer()
        var bestIndex = -1
        var bestScore = Float.NEGATIVE_INFINITY
        for (index in 0 until classifierClassCount) {
            val score = scores.get(index)
            if (score.isFinite() && score > bestScore) {
                bestIndex = index
                bestScore = score
            }
        }
        if (bestIndex < 0) return ClassificationResult(null, null, classifierInferenceMs)
        val classId = verifiedPack.displayCatalog.classId(bestIndex)
        val mapping = mappingsByClassId[classId]
        val combinedScore = min(proposal.score.toDouble(), bestScore.toDouble())
        val detection = TrafficSignDetection(
            candidate = TrafficSignCandidate(
                rawClassId = classId,
                rawLabel = mapping?.label ?: classId,
                semantic = mapping?.semantic ?: TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN),
                rawScore = combinedScore,
                calibratedConfidence = null,
                boundingBox = box,
                proposalRawScore = proposal.score.toDouble(),
                proposalCalibratedConfidence = null,
                classifierRawScore = bestScore.toDouble(),
                classifierCalibratedConfidence = null,
                conditionState = TrafficSignConditionState.NONE,
                restrictions = emptyList(),
            ),
            cropQuality = box.area,
        )
        return ClassificationResult(
            detection = detection.takeIf { bestScore >= minimumScore },
            classifierScore = bestScore.toDouble(),
            inferenceMs = classifierInferenceMs,
        )
    }

    override fun close() {
        detector.close()
        classifier.close()
        detectorBitmap.recycle()
        classifierBitmap.recycle()
    }

    private fun writeRgbFloats(buffer: ByteBuffer, pixels: IntArray) {
        rgbTensorEncoder.write(buffer, pixels)
    }

    private fun directFloatBuffer(elementCount: Int): ByteBuffer =
        ByteBuffer.allocateDirect(elementCount * Float.SIZE_BYTES).order(ByteOrder.nativeOrder())

    private fun elapsedMs(startedAtNanos: Long): Double =
        (System.nanoTime() - startedAtNanos).coerceAtLeast(0L) / 1_000_000.0

    private companion object {
        const val DETECTOR_SIZE = 1280
        const val CLASSIFIER_SIZE = 224
        const val RGB_CHANNELS = 3
        const val HORIZONTAL_CROP_PADDING = 0.10
        const val TOP_CROP_PADDING = 0.05
        const val BOTTOM_CROP_EXTENSION = 0.35
    }
}

internal class AndroidLiteRtTrafficSignBackend(
    verifiedPack: AndroidTrafficSignVerifiedPack,
    private val thermalState: () -> String?,
    context: Context,
    private val cropRequested: () -> Boolean = { false },
) : TrafficSignRecognitionBackend<CameraXTrafficSignFrame>, AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val cropFrameOutstanding = AtomicBoolean(false)
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    // GPU delegates require initialization, every invocation and disposal on one thread.
    // Construction already runs on the camera's startup executor, so waiting here cannot
    // block camera delivery or the UI thread.
    private val initialized = try {
        executor.submit<Pair<AndroidLiteRtTrafficSignInferenceEngine, AndroidTrafficSignStartupResult>> {
            fun initialize(reducedPrecision: Boolean): Pair<AndroidLiteRtTrafficSignInferenceEngine, AndroidTrafficSignStartupResult> {
                val engine = AndroidLiteRtTrafficSignInferenceEngine(verifiedPack, gpuPrecisionLossAllowed = reducedPrecision)
                try {
                    return engine to AndroidTrafficSignStartupProbe.run(context, engine, verifiedPack.modelPack)
                } catch (failure: Throwable) {
                    engine.close()
                    throw failure
                }
            }
            try {
                initialize(true)
            } catch (reducedPrecisionFailure: RuntimeException) {
                // Android GPUs vary. A reduced-precision startup must pass the
                // known-sign check; otherwise verify the previous precision mode.
                // Both modes retain the existing GPU-to-CPU runtime fallback.
                try {
                    val (engine, measured) = initialize(false)
                    engine to measured.copy(accelerationFallbackReason = listOfNotNull(
                        "Reduced-precision startup failed: ${reducedPrecisionFailure.message}",
                        measured.accelerationFallbackReason,
                    ).joinToString("; "))
                } catch (fullPrecisionFailure: RuntimeException) {
                    fullPrecisionFailure.addSuppressed(reducedPrecisionFailure)
                    throw fullPrecisionFailure
                }
            }
        }.get()
    } catch (failure: Exception) {
        executor.shutdown()
        throw (failure.cause ?: failure)
    }
    private val engine = initialized.first
    private val rotationBuffer = AndroidTrafficSignBitmapRotation()
    val startupResult: AndroidTrafficSignStartupResult = initialized.second

    override fun recognize(
        frame: CameraXTrafficSignFrame,
        completion: (TrafficSignBackendResult) -> Unit,
    ) = recognize(frame, {}, completion)

    override fun recognize(
        frame: CameraXTrafficSignFrame,
        beforeInference: () -> Unit,
        completion: (TrafficSignBackendResult) -> Unit,
    ) {
        val queuedAtNanos = System.nanoTime()
        if (closed.get()) {
            completion(TrafficSignBackendResult.Unavailable("Android LiteRT TSR backend is closed", thermalState()))
            return
        }
        executor.execute {
            val workerStartedAtNanos = System.nanoTime()
            beforeInference()
            frame.roadPathInferenceStartedNanos = System.nanoTime()
            val conversionStartedAtNanos = System.nanoTime()
            val result = runCatching {
                frame.withOrientedBitmap(rotationBuffer) { bitmap ->
                    val conversionMs = (System.nanoTime() - conversionStartedAtNanos) / 1_000_000.0
                    val calibration = frame.visualCalibration
                    val cropLeft = calibration?.cropLeftPixels(bitmap.width) ?: 0
                    val modelInput = if (cropLeft > 0) Bitmap.createBitmap(bitmap, cropLeft, 0,
                        bitmap.width - cropLeft, bitmap.height) else bitmap
                    val croppedInference = try { engine.recognizeAllWithDiagnostics(modelInput) }
                        finally { if (modelInput !== bitmap) modelInput.recycle() }
                    val inference = if (calibration != null && cropLeft > 0) croppedInference.copy(
                        detections = croppedInference.detections.map { detection ->
                            val box = calibration.fullFrameBox(detection.candidate.boundingBox, bitmap.width)
                            detection.copy(candidate = detection.candidate.copy(boundingBox = box), cropQuality = box.area)
                        }, sourceWidthPixels = bitmap.width, sourceHeightPixels = bitmap.height) else croppedInference
                    val detections = inference.detections
                    val primary = primaryDetection(detections)
                    TrafficSignBackendResult.Recognition(
                        detection = primary,
                        collectionFrame = if (detections.isNotEmpty() && cropRequested() && cropFrameOutstanding.compareAndSet(false, true)) {
                            try {
                                val owned = bitmap.copy(Bitmap.Config.ARGB_8888, false); owned.setHasAlpha(false)
                                SignCollectionFrame(frame.frameId, owned) { cropFrameOutstanding.set(false) }
                            } catch (_: Exception) { cropFrameOutstanding.set(false); null }
                        } else null,
                        displayDetections = detections,
                        thermalState = thermalState(),
                        strongPassGeometry = false,
                        diagnostics = TrafficSignInferenceDiagnostics(
                            inferenceMs = inference.inferenceMs,
                            detectorProposalCount = inference.detectorProposalCount,
                            detectorTopScore = inference.detectorTopScore,
                            classifierInvocationCount = inference.classifierInvocationCount,
                            classifiedDetectionCount = inference.classifiedDetectionCount,
                            classifierTopScore = inference.classifierTopScore,
                            primaryClassId = primary?.candidate?.rawClassId,
                            primaryScore = primary?.candidate?.rawScore,
                            detectorRawSignTopScore = inference.detectorRawSignTopScore,
                            detectorRawGlobalTopScore = inference.detectorRawGlobalTopScore,
                            detectorRawSignScoresAboveThreshold = inference.detectorRawSignScoresAboveThreshold,
                            sourceWidthPixels = inference.sourceWidthPixels,
                            sourceHeightPixels = inference.sourceHeightPixels,
                            sourceLumaMean = inference.sourceLumaMean,
                            executionBackend = inference.executionBackend,
                            accelerationFallbackReason = inference.accelerationFallbackReason,
                            detectorPreprocessingMs = inference.detectorPreprocessingMs,
                            detectorInferenceMs = inference.detectorInferenceMs,
                            classifierInferenceMs = inference.classifierInferenceMs,
                            backendQueueWaitMs = (workerStartedAtNanos - queuedAtNanos) / 1_000_000.0,
                            frameConversionMs = conversionMs,
                            cameraReceiptToResultMs = (System.nanoTime() - frame.receivedAtNanos) / 1_000_000.0,
                        ),
                    )
                }
            }.getOrElse { failure ->
                TrafficSignBackendResult.Unavailable(
                    reason = failure.message?.takeIf(String::isNotBlank) ?: failure.javaClass.simpleName,
                    thermalState = thermalState(),
                )
            }
            completion(result)
        }
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        executor.execute {
            try { engine.close() } finally { rotationBuffer.close() }
        }
        executor.shutdown()
    }
}

/** Binds the rear CameraX stream to the verified LiteRT pack and the existing M7 controller lane. */
internal class AndroidTrafficSignCameraRuntime(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val controller: ConsumerSessionController,
    private val onStateChanged: (TrafficSignCameraRuntimeState, String) -> Unit,
    private val onModelPackLoaded: (AndroidTrafficSignVerifiedPack) -> Unit = {},
) : AutoCloseable {
    private val mainExecutor = ContextCompat.getMainExecutor(context)
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val startupExecutor = Executors.newSingleThreadExecutor()
    private val generation = AtomicLong(0L)
    private val closed = AtomicBoolean(false)
    private val cameraResourcesReleased = AtomicBoolean(false)
    private val cameraReleaseCallbacks = mutableListOf<() -> Unit>()
    private var cameraProvider: ProcessCameraProvider? = null
    private var boundCamera: androidx.camera.core.Camera? = null
    @Volatile private var expectedAnalysisRotation: Int? = null
    @Volatile private var analysisOrientationEpoch = 0L
    private var imageAnalysis: ImageAnalysis? = null
    private var analyzerAttached = false
    private var lastCalibrationPreviewNanos = 0L
    private var lastLaneGeometryNanos = 0L
    @Volatile private var firstAnalysisFramePending = true
    private val calibrationRotation = AndroidTrafficSignBitmapRotation()
    private val analysisCadence = CameraAnalysisCadenceWindow()
    private var imageCapture: ImageCapture? = null
    private var manualPhotoOutputUnavailable = false
    private var videoCapture: VideoCapture<Recorder>? = null
    private var preview: Preview? = null
    private var previewSurfaceProvider: Preview.SurfaceProvider? = null
    private var modelLoading = false
    private var recognitionRuntimeSerial = 0L
    private var recognitionUnavailable = false
    private var cameraBound = false
    private var cameraBindingInProgress = false
    private var boundGraphPlan: DriveCameraGraphPlan? = null
    private var videoRequested = false
    private var recordingStopRequested = false
    private var videoTerminallyStopped = false
    private var activeRecording: Recording? = null
    private var activeRecordingFile: File? = null
    private var backend: AndroidLiteRtTrafficSignBackend? = null
    @Volatile private var bridge: TrafficSignLiveRuntimeBridge<CameraXTrafficSignFrame>? = null
    @Volatile private var requestedModelCountryCode: String = controller.trafficSignModelCountryCode()
    @Volatile private var loadedModelCountryCode: String? = null
    @Volatile private var laneClockIsRealtime = false
    @Volatile private var pathIntrinsics: RoadPathCameraIntrinsics? = null
    private val laneRuntime = AndroidLaneDetectionRuntime(
        mainExecutor = mainExecutor,
        admission = {
            val thermal = context.getSystemService(PowerManager::class.java)?.currentThermalStatus
                ?: PowerManager.THERMAL_STATUS_NONE
            controller.laneAdmission(thermal >= PowerManager.THERMAL_STATUS_SEVERE)
        },
        clockIsRealtime = { laneClockIsRealtime },
        onResult = controller::onLaneDetectionResult,
        onDiagnostics = controller::onLaneDetectionDiagnostics,
        previewSession = controller.lanePreviewSession,
        roadFrameFactory = { image -> CameraXTrafficSignFrame(image, pathIntrinsics,
            laneClockIsRealtime, generation.get(), controller.visualRoadCalibration).roadPathFrame() },
        onRoadResult = controller::onLanePreviewPrepared,
    )

    // A hidden preview still supplies a surface. Removing the UI must never
    // suspend analysis or movie recording while CameraX waits for its surface.
    private val offscreenPreviewProvider = DrainingCameraPreviewProvider(mainExecutor) { failure ->
        onStateChanged(TrafficSignCameraRuntimeState.UNAVAILABLE,
            failure.message ?: ConsumerRuntimeText.REAR_CAMERA_UNAVAILABLE.text())
    }

    fun start() {
        if (closed.get()) return
        generation.incrementAndGet()
        onStateChanged(TrafficSignCameraRuntimeState.STARTING, ConsumerRuntimeText.CAMERA_MODEL_LOADING.text())
        refreshConfiguration()
    }

    fun setPreviewSurfaceProvider(provider: Preview.SurfaceProvider?) {
        previewSurfaceProvider = provider
        preview?.setSurfaceProvider(mainExecutor, provider ?: offscreenPreviewProvider)
    }

    /** Update the selected mount without unbinding the photo/recognition graph. */
    fun updateTargetRotation(rotation: Int) {
        if (closed.get()) return
        analysisOrientationEpoch++
        expectedAnalysisRotation = boundCamera?.cameraInfo?.getSensorRotationDegrees(rotation)
        // Discard buffered frames; the analyzer also checks each frame's actual
        // rotation before it can acquire the new recognition generation.
        imageAnalysis?.clearAnalyzer()
        analyzerAttached = false
        preview?.targetRotation = rotation
        imageAnalysis?.targetRotation = rotation
        imageCapture?.targetRotation = rotation
        // Button actions finalize an existing movie before changing this value.
        videoCapture?.targetRotation = rotation
        refreshAnalysisConsumer()
    }

    /** Module changes preserve the camera and any independently running movie. */
    fun refreshConfiguration() {
        if (closed.get()) return
        videoRequested = controller.isDashcamRecordingEnabled()
        if (!controller.isTrafficSignRecognitionRuntimeEnabled()) {
            bridge?.close()
            bridge = null
            backend?.close()
            backend = null
            recognitionUnavailable = false
        } else if (bridge == null && !modelLoading && !recognitionUnavailable) {
            loadRecognitionRuntime()
        }
        refreshAnalysisConsumer()
        bindCamera(generation.get())
        setDashcamRecordingEnabled(videoRequested)
    }

    /** Select the bundled model for the current route without rebinding CameraX. */
    fun selectModelPack(countryCode: String?, reason: String = "bundle_selection") {
        val selected = AndroidTrafficSignModelPackSelection.availableCountryCode(countryCode) ?: return
        mainExecutor.execute {
            if (closed.get()) return@execute
            if (requestedModelCountryCode == selected &&
                (modelLoading || (loadedModelCountryCode == selected && bridge != null))
            ) return@execute
            requestedModelCountryCode = selected
            recognitionRuntimeSerial++
            modelLoading = false
            bridge?.close()
            bridge = null
            backend?.close()
            backend = null
            loadedModelCountryCode = null
            recognitionUnavailable = false
            refreshAnalysisConsumer()
            appendModelSwitchDiagnostic(selected, reason)
            if (controller.isTrafficSignRecognitionRuntimeEnabled()) loadRecognitionRuntime()
        }
    }

    private fun appendModelSwitchDiagnostic(countryCode: String, reason: String) {
        controller.onTrafficSignModelPackSwitchRequested(countryCode, reason)
    }

    /** Suspend delivery while recognition is disabled/loading without interrupting a movie. */
    private fun refreshAnalysisConsumer() {
        val analysis = imageAnalysis ?: return
        val needed = bridge != null || controller.isVisualCalibrationActive() || (controller.uiState.showDetectedLanes && controller.isDriveRecorderSessionActive())
        if (needed == analyzerAttached) return
        analyzerAttached = needed
        controller.onTrafficSignCameraAnalysisDiagnostic("consumer_changed", mapOf(
            "attached" to needed, "recognitionReady" to (bridge != null)))
        if (needed) {
            firstAnalysisFramePending = true
            val orientationEpoch = analysisOrientationEpoch
            analysis.setAnalyzer(cameraExecutor) { image ->
                val deliveredAt = System.nanoTime()
                analysisCadence.delivered(deliveredAt)
                controller.withCameraOrientation {
                    val current = bridge
                    if (firstAnalysisFramePending) {
                        firstAnalysisFramePending = false
                        controller.onTrafficSignCameraAnalysisDiagnostic("first_frame", mapOf(
                            "width" to image.width, "height" to image.height,
                            "rotation" to image.imageInfo.rotationDegrees, "expectedRotation" to expectedAnalysisRotation,
                            "orientationCurrent" to (orientationEpoch == analysisOrientationEpoch),
                            "recognitionReady" to (current != null)))
                    }
                    if (orientationEpoch != analysisOrientationEpoch ||
                        image.imageInfo.rotationDegrees != expectedAnalysisRotation) {
                        image.close(); analysisCadence.closed("orientation_discarded", (System.nanoTime()-deliveredAt)/1e6)
                    }
                    else {
                        val receivedAt = android.os.SystemClock.elapsedRealtimeNanos()
                        val previewScope = controller.lanePreviewSourceScope()
                        if (previewScope != null && receivedAt - lastLaneGeometryNanos >= 200_000_000L) {
                            lastLaneGeometryNanos = receivedAt
                            val matrix = FloatArray(9).also { image.imageInfo.sensorToBufferTransformMatrix.getValues(it) }
                            val thermal = context.getSystemService(PowerManager::class.java)?.currentThermalStatus
                                ?: PowerManager.THERMAL_STATUS_NONE
                            controller.onLanePreviewSource(LanePreviewSourceGeometry(previewScope,
                                LaneImageGeometry(image.width, image.height, image.imageInfo.rotationDegrees, matrix.map { it.toDouble() }),
                                receivedAt, thermal >= PowerManager.THERMAL_STATUS_SEVERE))
                        }
                        if (controller.isVisualCalibrationActive() && System.nanoTime() - lastCalibrationPreviewNanos >= 200_000_000L) {
                            lastCalibrationPreviewNanos = System.nanoTime()
                            runCatching {
                                val raw = image.toBitmap()
                                try {
                                    val upright = calibrationRotation.orient(raw, image.imageInfo.rotationDegrees)
                                    val scale = minOf(960.0 / upright.width, 540.0 / upright.height, 1.0)
                                    val display = Bitmap.createScaledBitmap(upright, maxOf(1, (upright.width * scale).toInt()),
                                        maxOf(1, (upright.height * scale).toInt()), true).let {
                                            if (it === raw || it === upright) it.copy(Bitmap.Config.ARGB_8888, false) else it
                                        }
                                    controller.onVisualCalibrationPreview(VisualRoadCalibrationPreview(display,
                                        upright.width, upright.height, "rear:rotation:${image.imageInfo.rotationDegrees}",
                                        android.os.SystemClock.elapsedRealtime()))
                                } finally { raw.recycle() }
                            }
                        }
                        // Copy admitted lane luminance before TSR takes ownership.
                        laneRuntime.submit(image)
                        if (current == null) {
                            image.close(); analysisCadence.closed("no_tsr_consumer", (System.nanoTime()-deliveredAt)/1e6)
                        } else {
                            analysisCadence.event("tsr_submitted")
                            val frame = CameraXTrafficSignFrame(image, pathIntrinsics, laneClockIsRealtime,
                                generation.get(), controller.visualRoadCalibration) { reason, _ ->
                                analysisCadence.closed(reason, (System.nanoTime()-deliveredAt)/1e6)
                            }
                            try { current.submitCameraFrame(frame) { reason -> analysisCadence.event("source_drop_$reason") } }
                            catch (failure: RuntimeException) { frame.release(); throw failure }
                        }
                    }
                }
                analysisCadence.reportIfDue(System.nanoTime())?.let { report ->
                    controller.onTrafficSignCameraAnalysisDiagnostic("cadence", report + ("lanes" to laneRuntime.cadenceDiagnostics()))
                }
            }
        } else analysis.clearAnalyzer()
    }

    private fun loadRecognitionRuntime() {
        val startGeneration = generation.get()
        val recognitionGeneration = controller.uiState.trafficSignGeneration
        val runtimeSerial = ++recognitionRuntimeSerial
        val countryCode = requestedModelCountryCode
        modelLoading = true
        startupExecutor.execute {
            val loaded = runCatching {
                    val pack = AndroidTrafficSignModelPackLoader.load(context, countryCode)
                    val runtimeBackend = AndroidLiteRtTrafficSignBackend(pack, ::currentThermalState, context, { controller.signCollection.wantsCropFrame })
                    val runtimeBridge = try { TrafficSignLiveRuntimeBridge(
                        pathPreparer = { frame: CameraXTrafficSignFrame, preparation ->
                            val thermal = context.getSystemService(PowerManager::class.java)?.currentThermalStatus ?: PowerManager.THERMAL_STATUS_NONE
                            if (thermal >= PowerManager.THERMAL_STATUS_SEVERE) {
                                frame.roadPathPreparationFailure = "thermal_paused"
                                controller.roadPathSession.invalidateOverlay()
                            } else runCatching {
                                val input = frame.roadPathFrame()
                                if (input == null) {
                                    frame.roadPathPreparationFailure = "frame_input_unavailable"
                                    controller.roadPathSession.invalidateOverlay()
                                } else frame.preparedRoadPath = controller.roadPathSession.prepare(input, frame.frameId,
                                    preparation.scope, preparation.publishIfCurrent)
                            }.onFailure {
                                frame.roadPathPreparationFailure = "path_processing_failed"
                                controller.roadPathSession.invalidateOverlay()
                            }
                        },
                        pathInvalidated = controller.roadPathSession::invalidateOverlay,
                        pathEvaluator = { frame: CameraXTrafficSignFrame, diagnostic ->
                            val prepared = frame.preparedRoadPath
                            val result = if (prepared != null) controller.roadPathSession.evaluate(prepared, diagnostic) else
                                org.json.JSONObject().apply {
                                    put("schemaVersion", 1); put("mode", "shadow"); put("frameId", frame.frameId)
                                    put("reason", frame.roadPathPreparationFailure ?: "frame_not_prepared")
                                    put("capturedAtSeconds", frame.capturedAtUtc.toEpochMilli() / 1000.0)
                                    put("captureClockKnown", false); put("geometryId", "unavailable:${frame.widthPixels}x${frame.heightPixels}")
                                    put("boundaries", org.json.JSONArray()); put("associations", org.json.JSONArray())
                                }.toString()
                            // Same worker's monotonic values demonstrate ordering; this is not UI render telemetry.
                            org.json.JSONObject(result).apply {
                                frame.roadPathInferenceStartedNanos?.let { put("inferenceStartedNanos", it) }
                                frame.visualCalibration?.let {
                                    put("visualCalibration", org.json.JSONObject(it.encode()))
                                    put("tsrInputRegion", org.json.JSONObject().put("leftPixels", it.cropLeftPixels(frame.widthPixels))
                                        .put("topPixels", 0).put("rightPixels", frame.widthPixels).put("bottomPixels", frame.heightPixels))
                                }
                            }.toString()
                        },
                        controller = controller,
                        modelPack = pack.modelPack,
                        runtimeArtifact = pack.detectorArtifact,
                        backend = runtimeBackend,
                        conditionsSnapshot = ::analysisConditions,
                        confirmationWindowMsOverride = runtimeBackend.startupResult.timingProfile.confirmationWindowMs,
                        onRuntimeUnavailable = { detail, failedGeneration -> mainExecutor.execute {
                            if (!closed.get() && generation.get() == startGeneration && recognitionRuntimeSerial == runtimeSerial) {
                                stopRecognitionAfterFailure(
                                    "Speed-sign recognition stopped after three camera-processing errors in a row. " +
                                        "Turn recognition off and on to retry. $detail",
                                    failedGeneration,
                                )
                            }
                        } },
                    ) } catch (failure: Throwable) {
                        runtimeBackend.close()
                        throw failure
                    }
                    LoadedRuntime(pack, runtimeBackend, runtimeBridge)
            }
            mainExecutor.execute main@{
                if (closed.get() || generation.get() != startGeneration || recognitionRuntimeSerial != runtimeSerial) {
                    loaded.getOrNull()?.close()
                    return@main
                }
                modelLoading = false
                if (!controller.isTrafficSignRecognitionRuntimeEnabled()) {
                    loaded.getOrNull()?.close()
                    return@main
                }
                loaded.onFailure { failure ->
                    if (controller.uiState.trafficSignGeneration != recognitionGeneration) loadRecognitionRuntime()
                    else stopRecognitionAfterFailure(failure.message?.takeIf(String::isNotBlank) ?: failure.javaClass.simpleName,
                        recognitionGeneration)
                }.onSuccess { runtime ->
                    runtime.backend?.startupResult?.let(controller::onTrafficSignStartupMeasured)
                    runtime.pack?.let {
                        loadedModelCountryCode = AndroidTrafficSignModelPackSelection.availableCountryCode(
                            it.modelPack.countries.firstOrNull()
                        )
                        onModelPackLoaded(it)
                    }
                    backend = runtime.backend
                    bridge = runtime.bridge
                    refreshAnalysisConsumer()
                    bindCamera(startGeneration)
                }
            }
        }
    }

    private fun stopRecognitionAfterFailure(detail: String, recognitionGeneration: Long) {
        if (controller.uiState.trafficSignGeneration != recognitionGeneration) {
            // The controller may reset its generation before another frame
            // reaches the orchestrator. Its terminal old scope must not make
            // the newly authorized scope permanently reject every frame.
            bridge?.close()
            bridge = null
            backend?.close()
            backend = null
            refreshAnalysisConsumer()
            recognitionUnavailable = false
            if (controller.isTrafficSignRecognitionRuntimeEnabled() && !modelLoading) loadRecognitionRuntime()
            return
        }
        recognitionUnavailable = true
        bridge?.close()
        bridge = null
        backend?.close()
        backend = null
        refreshAnalysisConsumer()
        controller.onTrafficSignRecognitionUnavailable(detail, recognitionGeneration)
    }

    @androidx.annotation.OptIn(ExperimentalCamera2Interop::class)
    private fun bindCamera(startGeneration: Long) {
        var graphPlan = DriveCameraGraphPlan.resolve(controller.isDriveRecorderSessionActive(),
            controller.isPhotoOutputRequested() || controller.isPanoramaxCaptureEnabled(), boundGraphPlan)
        if (manualPhotoOutputUnavailable && !controller.isPanoramaxCaptureEnabled())
            graphPlan = graphPlan.copy(photoOutput = false)
        if (cameraBindingInProgress || (cameraBound && graphPlan == boundGraphPlan)) return
        cameraBindingInProgress = true
        val providerFuture = ProcessCameraProvider.getInstance(context)
        providerFuture.addListener({
            if (closed.get() || generation.get() != startGeneration) {
                cameraBindingInProgress = false
                return@addListener
            }
            runCatching {
                val provider = providerFuture.get()
                val rotation = controller.uiState.manualOrientation.targetRotation
                val analysis = imageAnalysis ?: run {
                    val builder = ImageAnalysis.Builder()
                    configureInfinityFocus(builder)
                    builder
                        .setTargetRotation(rotation)
                        .setResolutionSelector(
                            ResolutionSelector.Builder()
                                .setResolutionStrategy(
                                    ResolutionStrategy(
                                        // iPhone keeps the high-resolution video output for
                                        // TSR. Keep the same camera detail on Android and let
                                        // the pinned 1280px model perform its declared
                                        // scale-fit preprocessing.
                                        Size(1920, 1080),
                                        ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                                    ),
                                )
                                .build(),
                        )
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                }
                // Keep still/movie outputs optional, and retain them once bound
                // so consumer toggles do not interrupt independent analysis.
                var capture = if (graphPlan.photoOutput) imageCapture ?: run {
                    val builder = ImageCapture.Builder()
                    configureInfinityFocus(builder)
                    builder
                        .setTargetRotation(rotation)
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .build()
                } else null
                val video = if (graphPlan.movieOutput) videoCapture ?: run {
                    val builder = VideoCapture.Builder(Recorder.Builder().build())
                    configureInfinityFocus(builder)
                    builder.setTargetRotation(rotation).build()
                } else null
                // A repeating preview surface must exist even while the model
                // loads and no analyzer is attached yet. On the Moto G86 the
                // startup graph produced no recognition until recording added
                // a preview. The offscreen consumer starts the same stream
                // without requiring a displayed preview or a saved movie.
                val currentPreview = run {
                    val builder = Preview.Builder()
                    configureInfinityFocus(builder)
                    preview ?: builder.setTargetRotation(rotation).build().also {
                        it.setSurfaceProvider(mainExecutor, previewSurfaceProvider ?: offscreenPreviewProvider)
                    }
                }
                currentPreview.targetRotation = rotation
                analysis.targetRotation = rotation
                capture?.targetRotation = rotation
                video?.targetRotation = rotation
                val oldUseCases = listOfNotNull(preview, imageAnalysis, imageCapture, videoCapture)
                if (cameraBound) provider.unbind(*oldUseCases.toTypedArray())
                // Keep the still and movie consumers ahead of analysis in the
                // binding order so constrained devices reserve recorder outputs
                // before the optional recognition stream.
                val useCases = graphPlan.bindOrder<androidx.camera.core.UseCase>(currentPreview, analysis, capture, video)
                boundCamera = try {
                    provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, *useCases.toTypedArray())
                } catch (failure: Exception) {
                    // A dormant manual shutter is optional. A constrained camera must
                    // retain its movie/recognition streams if the extra still output
                    // is unsupported. Never change the graph in response to a tap.
                    val fallbackPlan = graphPlan.withoutOptionalManualPhoto(controller.isPanoramaxCaptureEnabled())
                        ?: throw failure
                    provider.unbind(*useCases.toTypedArray())
                    graphPlan = fallbackPlan
                    capture = null
                    manualPhotoOutputUnavailable = true
                    val fallback = graphPlan.bindOrder<androidx.camera.core.UseCase>(currentPreview, analysis, null, video)
                    provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, *fallback.toTypedArray())
                }
                expectedAnalysisRotation = boundCamera?.cameraInfo?.getSensorRotationDegrees(rotation)
                pathIntrinsics = runCatching {
                    val info = Camera2CameraInfo.from(boundCamera!!.cameraInfo)
                    RoadPathCameraIntrinsics.from { key -> info.getCameraCharacteristic(key) }
                }.getOrNull()
                laneClockIsRealtime = runCatching {
                    Camera2CameraInfo.from(boundCamera!!.cameraInfo).getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ==
                        CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
                }.getOrDefault(false)
                cameraProvider = provider
                imageAnalysis = analysis
                imageCapture = capture
                videoCapture = video
                preview = currentPreview
                boundGraphPlan = graphPlan
                controller.onPanoramaxPhotoOutputReadyChanged(capture != null)
                controller.onTrafficSignCameraAnalysisDiagnostic("graph_bound", mapOf(
                    "preview" to true, "analysis" to true, "photoOutput" to graphPlan.photoOutput,
                    "movieOutput" to graphPlan.movieOutput, "expectedRotation" to expectedAnalysisRotation))
                refreshAnalysisConsumer()
            }.onFailure { failure ->
                controller.onPanoramaxPhotoOutputReadyChanged(false)
                cameraBindingInProgress = false
                onStateChanged(
                    TrafficSignCameraRuntimeState.UNAVAILABLE,
                    failure.message?.takeIf(String::isNotBlank) ?: ConsumerRuntimeText.REAR_CAMERA_UNAVAILABLE.text(),
                )
            }.onSuccess {
                cameraBindingInProgress = false
                if (!cameraBound) {
                    cameraBound = true
                    onStateChanged(TrafficSignCameraRuntimeState.ACTIVE, ConsumerRuntimeText.CAMERA_ACTIVE.text())
                }
                setDashcamRecordingEnabled(controller.isDashcamRecordingEnabled())
            }
        }, mainExecutor)
    }

    /**
     * The camera is mounted behind the windscreen, where autofocus can settle
     * on dirt or reflections close to the lens instead of the road ahead.
     * Camera2 expresses infinity as a zero-diopter focus distance.
     */
    @androidx.annotation.OptIn(ExperimentalCamera2Interop::class)
    private fun <T> configureInfinityFocus(builder: ExtendableBuilder<T>) {
        Camera2Interop.Extender(builder)
            .setCaptureRequestOption(
                CaptureRequest.CONTROL_AF_MODE,
                CaptureRequest.CONTROL_AF_MODE_OFF,
            )
            .setCaptureRequestOption(CaptureRequest.LENS_FOCUS_DISTANCE, 0.0f)
    }

    fun setDashcamRecordingEnabled(enabled: Boolean) {
        videoRequested = enabled
        if (!enabled) {
            videoTerminallyStopped = false
            activeRecording?.let {
                recordingStopRequested = true
                activeRecordingFile?.absolutePath?.let { path ->
                    controller.onDashcamRecordingStateChanged(active = true, transitioning = true, path = path)
                }
                it.stop()
            }
        } else if (cameraBound) {
            videoCapture?.let(::startDashcamRecording)
        }
    }

    private var lastPathRecordingAnchorNanos = 0L
    private fun startDashcamRecording(video: VideoCapture<Recorder>) {
        if (closed.get() || activeRecording != null || videoTerminallyStopped || !videoRequested ||
            !controller.isDashcamRecordingEnabled()) return
        val file = controller.nextDashcamRecordingFile()
        val output = FileOutputOptions.Builder(file).setFileSizeLimit(MAXIMUM_DASHCAM_FILE_BYTES).build()
        activeRecordingFile = file
        recordingStopRequested = false
        controller.onDashcamRecordingStateChanged(active = false, transitioning = true, path = file.absolutePath)
        runCatching { video.output
            .prepareRecording(context, output)
            .start(mainExecutor) { event ->
                when (event) {
                    is VideoRecordEvent.Start -> if (!closed.get()) {
                        controller.onDashcamRecordingStateChanged(active = true, path = file.absolutePath)
                        controller.onRoadPathRecording("start", file.absolutePath, event.recordingStats.recordedDurationNanos / 1e9)
                    }
                    is VideoRecordEvent.Status -> {
                        val now = System.nanoTime()
                        if (now-lastPathRecordingAnchorNanos >= 5_000_000_000L) {
                            lastPathRecordingAnchorNanos = now
                            controller.onRoadPathRecording("progress", file.absolutePath, event.recordingStats.recordedDurationNanos / 1e9)
                        }
                    }
                    is VideoRecordEvent.Finalize -> {
                        controller.onRoadPathRecording("stop", file.absolutePath, event.recordingStats.recordedDurationNanos / 1e9)
                        val resumeAfterStop = recordingStopRequested && videoRequested
                        val stoppedByUser = recordingStopRequested
                        recordingStopRequested = false
                        activeRecording = null
                        activeRecordingFile = null
                        controller.onDashcamRecordingStateChanged(active = false, path = file.absolutePath)
                        val reachedLimit = event.error == VideoRecordEvent.Finalize.ERROR_FILE_SIZE_LIMIT_REACHED
                        val succeeded = event.error == VideoRecordEvent.Finalize.ERROR_NONE || reachedLimit
                        videoTerminallyStopped = !stoppedByUser || reachedLimit
                        if (!succeeded) file.delete()
                        controller.onDashcamRecordingFinalized(
                            path = file.absolutePath,
                            success = succeeded,
                            detail = event.cause?.message ?: "Video recording failed (${event.error})",
                        )
                        // A user stop leaves the other camera modules running.
                        // A 5 GB cap is a completed movie, never an upload trigger.
                        if (resumeAfterStop && !reachedLimit && controller.isDashcamRecordingEnabled() && !closed.get()) {
                            startDashcamRecording(video)
                        }
                        if (closed.get()) releaseCameraResources()
                    }
                }
            }
        }.onSuccess { activeRecording = it }.onFailure { failure ->
            file.delete()
            activeRecordingFile = null
            videoTerminallyStopped = true
            controller.onDashcamRecordingStateChanged(active = false, path = file.absolutePath)
            controller.onDashcamRecordingFinalized(file.absolutePath, false,
                failure.message ?: "Video recording could not start")
        }
    }

    private fun analysisConditions(): TrafficSignAnalysisConditions {
        val powerManager = context.getSystemService(PowerManager::class.java)
        val pressure = when (powerManager?.currentThermalStatus) {
            PowerManager.THERMAL_STATUS_CRITICAL,
            PowerManager.THERMAL_STATUS_EMERGENCY,
            PowerManager.THERMAL_STATUS_SHUTDOWN,
            -> TrafficSignThermalPressure.CRITICAL
            PowerManager.THERMAL_STATUS_SEVERE -> TrafficSignThermalPressure.SERIOUS
            PowerManager.THERMAL_STATUS_MODERATE -> TrafficSignThermalPressure.FAIR
            else -> TrafficSignThermalPressure.NOMINAL
        }
        return TrafficSignAnalysisConditions(
            speedMetersPerSecond = controller.currentSpeedMetersPerSecondForTrafficSignAnalysis(),
            hasActiveTrack = false,
            powerSaveMode = powerManager?.isPowerSaveMode == true,
            thermalPressure = pressure,
        )
    }

    private fun currentThermalState(): String? =
        context.getSystemService(PowerManager::class.java)?.currentThermalStatus?.toString()

    fun capturePanoramaxPhoto(requestId: String) {
        val captureGeneration = generation.get()
        fun fail(detail: String) = controller.onPanoramaxPhotoCaptureFailed(detail, requestId)
        if (closed.get() || !cameraBound) return fail("Camera session has stopped")
        val capture = imageCapture ?: return fail("Still camera is unavailable")
        val sample = controller.currentPanoramaxLocationSample() ?: return fail("No current GPS fix for photo")
        val file = runCatching { File.createTempFile("panoramax-", ".jpg", context.cacheDir) }
            .getOrElse { return fail(it.message ?: "Could not create photo file") }
        val options = ImageCapture.OutputFileOptions.Builder(file).build()
        runCatching { capture.takePicture(
            options,
            cameraExecutor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                    if (closed.get() || generation.get() != captureGeneration) {
                        file.delete()
                        fail("Camera session changed before photo completed")
                    } else controller.onPanoramaxPhotoCaptured(file.absolutePath, sample, requestId)
                }

                override fun onError(exception: ImageCaptureException) {
                    file.delete()
                    fail(exception.message ?: "Still capture failed")
                }
            },
        ) }.onFailure { file.delete(); fail(it.message ?: "Still capture failed") }
    }

    /** Main-thread completion barrier before a replacement runtime binds this camera. */
    fun closeAfterFinalization(onReleased: () -> Unit) {
        if (cameraResourcesReleased.get()) onReleased() else {
            cameraReleaseCallbacks += onReleased
            close()
        }
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        generation.incrementAndGet()
        videoRequested = false
        laneRuntime.close()
        bridge?.close()
        bridge = null
        backend?.close()
        backend = null
        imageAnalysis?.clearAnalyzer()
        startupExecutor.shutdown()
        // Keep the movie's surface alive until CameraX finalizes the local
        // file, with the same bounded five-second stop recovery as iPhone.
        val wasRecording = activeRecording != null
        activeRecording?.stop()
        if (wasRecording) {
            Handler(Looper.getMainLooper()).postDelayed(::releaseCameraResources, 5_000L)
        } else releaseCameraResources()
    }

    private fun releaseCameraResources() {
        if (!cameraResourcesReleased.compareAndSet(false, true)) return
        activeRecording = null
        activeRecordingFile = null
        cameraProvider?.unbind(*listOfNotNull(imageAnalysis, imageCapture, videoCapture, preview).toTypedArray())
        imageAnalysis = null
        imageCapture = null
        controller.onPanoramaxPhotoOutputReadyChanged(false)
        videoCapture = null
        preview = null
        cameraProvider = null
        boundCamera = null
        expectedAnalysisRotation = null
        cameraExecutor.execute { calibrationRotation.close() }
        cameraExecutor.shutdown()
        controller.onDashcamCameraReleased()
        val completions = cameraReleaseCallbacks.toList()
        cameraReleaseCallbacks.clear()
        completions.forEach { it() }
    }

    private companion object { const val MAXIMUM_DASHCAM_FILE_BYTES = 5_000_000_000L }

    private data class LoadedRuntime(
        val pack: AndroidTrafficSignVerifiedPack?,
        val backend: AndroidLiteRtTrafficSignBackend?,
        val bridge: TrafficSignLiveRuntimeBridge<CameraXTrafficSignFrame>?,
    ) : AutoCloseable {
        override fun close() {
            bridge?.close()
            backend?.close()
        }
    }
}

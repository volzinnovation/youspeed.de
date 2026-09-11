package de.youspeed.android.alpha

import android.content.Context
import android.app.Activity
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.ImageFormat
import android.hardware.HardwareBuffer
import android.media.ImageReader
import android.os.PowerManager
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.util.Size
import android.view.Surface
import androidx.camera.core.CameraSelector
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
)

internal object AndroidTrafficSignModelPackLoader {
    const val PACK_ASSET_ROOT = "tsr/DE.panoramax-bootstrap.tsrmodelpack"
    const val MANIFEST_ASSET_PATH = "$PACK_ASSET_ROOT/manifest.json"

    fun load(context: Context): AndroidTrafficSignVerifiedPack {
        val assets = context.assets
        val modelPack = assets.open(MANIFEST_ASSET_PATH).bufferedReader().use { reader ->
            TrafficSignModelPackJson.decode(reader.readText())
        }
        TrafficSignModelPackValidator.requireValid(modelPack)
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

        val displayCatalog = assets.open(TrafficSignDisplayCatalog.ASSET_PATH).bufferedReader().use {
            TrafficSignDisplayCatalog.decode(it.readText())
        }
        require(displayCatalog.checkpointSha256 == classifierComponent.sourceCheckpoint.sha256) {
            "TSR class catalog does not match the classifier checkpoint"
        }
        val detectorModel = mapAndVerify(context, detectorArtifact)
        val classifierModel = mapAndVerify(context, classifierArtifact)
        return AndroidTrafficSignVerifiedPack(
            modelPack = modelPack,
            detectorArtifact = detectorArtifact,
            classifierArtifact = classifierArtifact,
            detectorModel = detectorModel,
            classifierModel = classifierModel,
            displayCatalog = displayCatalog,
        )
    }

    private fun mapAndVerify(context: Context, artifact: TrafficSignArtifact): MappedByteBuffer {
        val assetPath = "$PACK_ASSET_ROOT/${artifact.path}"
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

/** Owns one CameraX image until the orchestrator releases it. */
internal class CameraXTrafficSignFrame(
    private val image: ImageProxy,
) : TrafficSignNormalizedFrameHandle {
    private val released = AtomicBoolean(false)
    private val rotationDegrees = image.imageInfo.rotationDegrees

    override val frameId: String = UUID.randomUUID().toString().lowercase(Locale.US)
    override val source: TrafficSignInputSource = TrafficSignInputSource.LIVE_FRAME
    override val capturedAtUtc: Instant = Instant.now()
    override val capturedAtMonotonicNanos: Long = image.imageInfo.timestamp.coerceAtLeast(0L)
    override val widthPixels: Int = if (rotationDegrees == 90 || rotationDegrees == 270) image.height else image.width
    override val heightPixels: Int = if (rotationDegrees == 90 || rotationDegrees == 270) image.width else image.height

    fun orientedBitmap(): Bitmap {
        check(!released.get()) { "Camera frame was already released" }
        val sourceBitmap = image.toBitmap()
        if (rotationDegrees == 0) return sourceBitmap
        val matrix = Matrix().apply { postRotate(rotationDegrees.toFloat()) }
        return Bitmap.createBitmap(
            sourceBitmap,
            0,
            0,
            sourceBitmap.width,
            sourceBitmap.height,
            matrix,
            true,
        ).also { rotated ->
            if (rotated !== sourceBitmap) sourceBitmap.recycle()
        }
    }

    override fun release() {
        if (released.compareAndSet(false, true)) image.close()
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

internal class AndroidLiteRtTrafficSignInferenceEngine(
    private val verifiedPack: AndroidTrafficSignVerifiedPack,
) : AutoCloseable {
    private val interpreterOptions = Interpreter.Options().apply {
        setNumThreads(4)
        setUseXNNPACK(true)
    }
    private val detector = Interpreter(verifiedPack.detectorModel, interpreterOptions)
    private val classifier = Interpreter(verifiedPack.classifierModel, interpreterOptions)
    private val detectorInput = directFloatBuffer(DETECTOR_SIZE * DETECTOR_SIZE * RGB_CHANNELS)
    private val detectorOutput = directFloatBuffer(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
    private val detectorOutputFloats = FloatArray(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
    private val classifierInput = directFloatBuffer(CLASSIFIER_SIZE * CLASSIFIER_SIZE * RGB_CHANNELS)
    private val classifierOutput = directFloatBuffer(CLASSIFIER_CLASS_COUNT)
    private val detectorBitmap = Bitmap.createBitmap(DETECTOR_SIZE, DETECTOR_SIZE, Bitmap.Config.ARGB_8888)
    private val classifierBitmap = Bitmap.createBitmap(CLASSIFIER_SIZE, CLASSIFIER_SIZE, Bitmap.Config.ARGB_8888)
    private val detectorPixels = IntArray(DETECTOR_SIZE * DETECTOR_SIZE)
    private val classifierPixels = IntArray(CLASSIFIER_SIZE * CLASSIFIER_SIZE)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    private val mappingsByClassId = verifiedPack.modelPack.classMapping.associateBy(TrafficSignClassMapping::classId)

    init {
        require(detector.getInputTensor(0).shape().contentEquals(intArrayOf(1, DETECTOR_SIZE, DETECTOR_SIZE, RGB_CHANNELS)))
        require(detector.getInputTensor(0).dataType() == DataType.FLOAT32)
        require(detector.getOutputTensor(0).shape().contentEquals(intArrayOf(1, 7, 33_600)))
        require(detector.getOutputTensor(0).dataType() == DataType.FLOAT32)
        require(classifier.getInputTensor(0).shape().contentEquals(intArrayOf(1, CLASSIFIER_SIZE, CLASSIFIER_SIZE, RGB_CHANNELS)))
        require(classifier.getInputTensor(0).dataType() == DataType.FLOAT32)
        require(classifier.getOutputTensor(0).shape().contentEquals(intArrayOf(1, CLASSIFIER_CLASS_COUNT)))
        require(classifier.getOutputTensor(0).dataType() == DataType.FLOAT32)
    }

    fun recognize(source: Bitmap): TrafficSignDetection? = primaryDetection(recognizeAll(source))

    fun recognizeAll(source: Bitmap): List<TrafficSignDetection> {
        prepareDetectorInput(source)
        detectorOutput.clear()
        detector.run(detectorInput, detectorOutput)
        detectorOutput.rewind()
        detectorOutput.asFloatBuffer().get(detectorOutputFloats)
        val proposals = AndroidYoloSignDecoder.decode(
            output = detectorOutputFloats,
            sourceWidth = source.width,
            sourceHeight = source.height,
            inputSize = DETECTOR_SIZE,
            minimumScore = verifiedPack.modelPack.thresholds.unknown,
        )

        return proposals.mapNotNull { proposal -> classify(source, proposal) }
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
    )

    private fun classify(source: Bitmap, proposal: AndroidYoloProposal, minimumScore: Double = verifiedPack.modelPack.thresholds.unknown): TrafficSignDetection? {
        val box = proposal.box
        val left = ((box.x - box.width * HORIZONTAL_CROP_PADDING) * source.width).coerceAtLeast(0.0)
        val top = ((box.y - box.height * TOP_CROP_PADDING) * source.height).coerceAtLeast(0.0)
        val right = ((box.x + box.width * (1.0 + HORIZONTAL_CROP_PADDING)) * source.width)
            .coerceAtMost(source.width.toDouble())
        val bottom = ((box.y + box.height * (1.0 + BOTTOM_CROP_EXTENSION)) * source.height)
            .coerceAtMost(source.height.toDouble())
        if (right <= left || bottom <= top) return null

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
        classifierOutput.clear()
        classifier.run(classifierInput, classifierOutput)
        classifierOutput.rewind()
        val scores = classifierOutput.asFloatBuffer()
        var bestIndex = -1
        var bestScore = Float.NEGATIVE_INFINITY
        for (index in 0 until CLASSIFIER_CLASS_COUNT) {
            val score = scores.get(index)
            if (score.isFinite() && score > bestScore) {
                bestIndex = index
                bestScore = score
            }
        }
        if (bestIndex < 0 || bestScore < minimumScore) return null
        val classId = verifiedPack.displayCatalog.classId(bestIndex)
        val mapping = mappingsByClassId[classId]
        val combinedScore = min(proposal.score.toDouble(), bestScore.toDouble())
        return TrafficSignDetection(
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
    }

    override fun close() {
        detector.close()
        classifier.close()
        detectorBitmap.recycle()
        classifierBitmap.recycle()
    }

    private fun writeRgbFloats(buffer: ByteBuffer, pixels: IntArray) {
        buffer.clear()
        pixels.forEach { color ->
            buffer.putFloat(Color.red(color) / 255f)
            buffer.putFloat(Color.green(color) / 255f)
            buffer.putFloat(Color.blue(color) / 255f)
        }
        buffer.rewind()
    }

    private fun directFloatBuffer(elementCount: Int): ByteBuffer =
        ByteBuffer.allocateDirect(elementCount * Float.SIZE_BYTES).order(ByteOrder.nativeOrder())

    private companion object {
        const val DETECTOR_SIZE = 1280
        const val CLASSIFIER_SIZE = 224
        const val CLASSIFIER_CLASS_COUNT = 134
        const val RGB_CHANNELS = 3
        const val HORIZONTAL_CROP_PADDING = 0.10
        const val TOP_CROP_PADDING = 0.05
        const val BOTTOM_CROP_EXTENSION = 0.35
    }
}

internal class AndroidLiteRtTrafficSignBackend(
    verifiedPack: AndroidTrafficSignVerifiedPack,
    private val thermalState: () -> String?,
) : TrafficSignRecognitionBackend<CameraXTrafficSignFrame>, AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val engine = AndroidLiteRtTrafficSignInferenceEngine(verifiedPack)

    override fun recognize(
        frame: CameraXTrafficSignFrame,
        completion: (TrafficSignBackendResult) -> Unit,
    ) {
        if (closed.get()) {
            completion(TrafficSignBackendResult.Unavailable("Android LiteRT TSR backend is closed", thermalState()))
            return
        }
        executor.execute {
            val result = runCatching {
                val bitmap = frame.orientedBitmap()
                try {
                    val detections = engine.recognizeAll(bitmap)
                    TrafficSignBackendResult.Recognition(
                        detection = primaryDetection(detections),
                        displayDetections = detections,
                        thermalState = thermalState(),
                        strongPassGeometry = false,
                    )
                } finally {
                    bitmap.recycle()
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
        executor.execute(engine::close)
        executor.shutdown()
    }
}

/** Binds the rear CameraX stream to the verified LiteRT pack and the existing M7 controller lane. */
internal class AndroidTrafficSignCameraRuntime(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val controller: ConsumerSessionController,
    private val onStateChanged: (TrafficSignCameraRuntimeState, String) -> Unit,
) : AutoCloseable {
    private val mainExecutor = ContextCompat.getMainExecutor(context)
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val startupExecutor = Executors.newSingleThreadExecutor()
    private val generation = AtomicLong(0L)
    private val closed = AtomicBoolean(false)
    private val cameraResourcesReleased = AtomicBoolean(false)
    private val cameraReleaseCallbacks = mutableListOf<() -> Unit>()
    private var cameraProvider: ProcessCameraProvider? = null
    private var imageAnalysis: ImageAnalysis? = null
    private var imageCapture: ImageCapture? = null
    private var videoCapture: VideoCapture<Recorder>? = null
    private var preview: Preview? = null
    private var previewSurfaceProvider: Preview.SurfaceProvider? = null
    private var modelLoading = false
    private var recognitionRuntimeSerial = 0L
    private var recognitionUnavailable = false
    private var cameraBound = false
    private var videoRequested = false
    private var recordingStopRequested = false
    private var videoTerminallyStopped = false
    private var activeRecording: Recording? = null
    private var activeRecordingFile: File? = null
    private var backend: AndroidLiteRtTrafficSignBackend? = null
    @Volatile private var bridge: TrafficSignLiveRuntimeBridge<CameraXTrafficSignFrame>? = null

    // A hidden preview still supplies a surface. Removing the UI must never
    // suspend analysis or movie recording while CameraX waits for its surface.
    private val offscreenPreviewProvider = Preview.SurfaceProvider { request ->
        val drainThread = HandlerThread("YouSpeedPreviewDrain").apply { start() }
        val reader = try {
            ImageReader.newInstance(request.resolution.width, request.resolution.height,
                ImageFormat.PRIVATE, 3, HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE)
        } catch (failure: Exception) {
            drainThread.quitSafely()
            request.willNotProvideSurface()
            onStateChanged(TrafficSignCameraRuntimeState.UNAVAILABLE,
                failure.message ?: ConsumerRuntimeText.REAR_CAMERA_UNAVAILABLE.text())
            return@SurfaceProvider
        }
        reader.setOnImageAvailableListener({ source ->
            // PRIVATE frames are never mapped or retained. Draining the
            // consumer keeps a hidden preview from blocking the camera graph.
            runCatching { source.acquireLatestImage()?.close() }
        }, Handler(drainThread.looper))
        request.provideSurface(reader.surface, mainExecutor) {
            reader.close()
            drainThread.quitSafely()
        }
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
        bindCamera(generation.get())
        setDashcamRecordingEnabled(videoRequested)
    }

    private fun loadRecognitionRuntime() {
        val startGeneration = generation.get()
        val recognitionGeneration = controller.uiState.trafficSignGeneration
        val runtimeSerial = ++recognitionRuntimeSerial
        modelLoading = true
        startupExecutor.execute {
            val loaded = runCatching {
                    val pack = AndroidTrafficSignModelPackLoader.load(context)
                    val runtimeBackend = AndroidLiteRtTrafficSignBackend(pack, ::currentThermalState)
                    val runtimeBridge = try { TrafficSignLiveRuntimeBridge(
                        controller = controller,
                        modelPack = pack.modelPack,
                        runtimeArtifact = pack.detectorArtifact,
                        backend = runtimeBackend,
                        conditionsSnapshot = ::analysisConditions,
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
                modelLoading = false
                if (closed.get() || generation.get() != startGeneration) {
                    loaded.getOrNull()?.close()
                    return@main
                }
                if (!controller.isTrafficSignRecognitionRuntimeEnabled()) {
                    loaded.getOrNull()?.close()
                    return@main
                }
                loaded.onFailure { failure ->
                    if (controller.uiState.trafficSignGeneration != recognitionGeneration) loadRecognitionRuntime()
                    else stopRecognitionAfterFailure(failure.message?.takeIf(String::isNotBlank) ?: failure.javaClass.simpleName,
                        recognitionGeneration)
                }.onSuccess { runtime ->
                    backend = runtime.backend
                    bridge = runtime.bridge
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
            recognitionUnavailable = false
            if (controller.isTrafficSignRecognitionRuntimeEnabled() && !modelLoading) loadRecognitionRuntime()
            return
        }
        recognitionUnavailable = true
        bridge?.close()
        bridge = null
        backend?.close()
        backend = null
        controller.onTrafficSignRecognitionUnavailable(detail, recognitionGeneration)
    }

    private fun bindCamera(startGeneration: Long) {
        if (cameraBound) return
        val providerFuture = ProcessCameraProvider.getInstance(context)
        providerFuture.addListener({
            if (closed.get() || generation.get() != startGeneration || cameraBound) return@addListener
            runCatching {
                val provider = providerFuture.get()
                val rotation = (lifecycleOwner as? Activity)?.display?.rotation ?: Surface.ROTATION_0
                // Reserve the complete shared graph before any movie starts.
                // Adding analysis later rebuilds CameraX's StreamSharing edges
                // and can invalidate the rotated surface of an active movie.
                // Module switches control consumers, never output bindings.
                val analysis = imageAnalysis ?: run {
                    ImageAnalysis.Builder()
                        .setTargetRotation(rotation)
                        .setResolutionSelector(
                            ResolutionSelector.Builder()
                                .setResolutionStrategy(
                                    ResolutionStrategy(
                                        Size(1280, 720),
                                        ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                                    ),
                                )
                                .build(),
                        )
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                        .also { imageAnalysis ->
                            imageAnalysis.setAnalyzer(cameraExecutor) { image ->
                                val current = bridge
                                if (current == null) image.close() else current.submit(CameraXTrafficSignFrame(image))
                            }
                        }
                }
                val capture = imageCapture ?: run {
                    ImageCapture.Builder()
                        .setTargetRotation(rotation)
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .build()
                }
                val video = videoCapture ?: run {
                    VideoCapture.withOutput(Recorder.Builder().build()).apply { targetRotation = rotation }
                }
                val currentPreview = preview ?: Preview.Builder().setTargetRotation(rotation).build().also {
                    it.setSurfaceProvider(mainExecutor, previewSurfaceProvider ?: offscreenPreviewProvider)
                }
                currentPreview.targetRotation = rotation
                analysis.targetRotation = rotation
                capture.targetRotation = rotation
                video.targetRotation = rotation
                val useCases = listOf(currentPreview, analysis, capture, video)
                provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, *useCases.toTypedArray())
                cameraProvider = provider
                imageAnalysis = analysis
                imageCapture = capture
                videoCapture = video
                preview = currentPreview
            }.onFailure { failure ->
                onStateChanged(
                    TrafficSignCameraRuntimeState.UNAVAILABLE,
                    failure.message?.takeIf(String::isNotBlank) ?: ConsumerRuntimeText.REAR_CAMERA_UNAVAILABLE.text(),
                )
            }.onSuccess {
                if (!cameraBound) {
                    cameraBound = true
                    onStateChanged(TrafficSignCameraRuntimeState.ACTIVE, ConsumerRuntimeText.CAMERA_ACTIVE.text())
                }
                setDashcamRecordingEnabled(controller.isDashcamRecordingEnabled())
            }
        }, mainExecutor)
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
                    is VideoRecordEvent.Start -> if (!closed.get()) controller.onDashcamRecordingStateChanged(active = true, path = file.absolutePath)
                    is VideoRecordEvent.Status -> Unit
                    is VideoRecordEvent.Finalize -> {
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
        if (closed.get()) return fail("Camera session has stopped")
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
        videoCapture = null
        preview = null
        cameraProvider = null
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

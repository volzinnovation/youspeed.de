package de.youspeed.android.alpha

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.os.PowerManager
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
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
    private var cameraProvider: ProcessCameraProvider? = null
    private var imageAnalysis: ImageAnalysis? = null
    private var imageCapture: ImageCapture? = null
    private var videoCapture: VideoCapture<Recorder>? = null
    private var activeRecording: Recording? = null
    private var activeRecordingFile: File? = null
    private var backend: AndroidLiteRtTrafficSignBackend? = null
    private var bridge: TrafficSignLiveRuntimeBridge<CameraXTrafficSignFrame>? = null

    fun start() {
        if (closed.get()) return
        val startGeneration = generation.incrementAndGet()
        onStateChanged(TrafficSignCameraRuntimeState.STARTING, ConsumerRuntimeText.CAMERA_MODEL_LOADING.text())
        startupExecutor.execute {
            val loaded = runCatching {
                if (!controller.isTrafficSignRecognitionRuntimeEnabled()) {
                    LoadedRuntime(null, null, null)
                } else {
                    val pack = AndroidTrafficSignModelPackLoader.load(context)
                    val runtimeBackend = AndroidLiteRtTrafficSignBackend(pack, ::currentThermalState)
                    val runtimeBridge = TrafficSignLiveRuntimeBridge(
                        controller = controller,
                        modelPack = pack.modelPack,
                        runtimeArtifact = pack.detectorArtifact,
                        backend = runtimeBackend,
                        conditionsSnapshot = ::analysisConditions,
                    )
                    LoadedRuntime(pack, runtimeBackend, runtimeBridge)
                }
            }
            mainExecutor.execute main@{
                if (closed.get() || generation.get() != startGeneration) {
                    loaded.getOrNull()?.close()
                    return@main
                }
                loaded.onFailure { failure ->
                    onStateChanged(
                        TrafficSignCameraRuntimeState.FAILED,
                        failure.message?.takeIf(String::isNotBlank) ?: failure.javaClass.simpleName,
                    )
                }.onSuccess { runtime ->
                    backend = runtime.backend
                    bridge = runtime.bridge
                    bindCamera(runtime, startGeneration)
                }
            }
        }
    }

    private fun bindCamera(runtime: LoadedRuntime, startGeneration: Long) {
        val providerFuture = ProcessCameraProvider.getInstance(context)
        providerFuture.addListener({
            if (closed.get() || generation.get() != startGeneration) return@addListener
            runCatching {
                val provider = providerFuture.get()
                val analysis = runtime.bridge?.let { bridge ->
                    ImageAnalysis.Builder()
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
                                val frame = CameraXTrafficSignFrame(image)
                                bridge.submit(frame)
                            }
                        }
                }
                val capture = if (controller.isDashcamRecordingEnabled()) {
                    ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .build()
                } else null
                val video = if (controller.isDashcamRecordingEnabled()) {
                    VideoCapture.withOutput(Recorder.Builder().build())
                } else null
                provider.unbindAll()
                val useCases = listOfNotNull(analysis, capture, video)
                check(useCases.isNotEmpty()) { "No camera use case enabled" }
                provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, *useCases.toTypedArray())
                cameraProvider = provider
                imageAnalysis = analysis
                imageCapture = capture
                videoCapture = video
            }.onFailure { failure ->
                runtime.close()
                backend = null
                bridge = null
                onStateChanged(
                    TrafficSignCameraRuntimeState.UNAVAILABLE,
                    failure.message?.takeIf(String::isNotBlank) ?: ConsumerRuntimeText.REAR_CAMERA_UNAVAILABLE.text(),
                )
            }.onSuccess {
                onStateChanged(
                    TrafficSignCameraRuntimeState.ACTIVE,
                    ConsumerRuntimeText.CAMERA_ACTIVE.text(),
                )
                videoCapture?.let(::startDashcamRecording)
            }
        }, mainExecutor)
    }

    private fun startDashcamRecording(video: VideoCapture<Recorder>) {
        if (activeRecording != null || !controller.isDashcamRecordingEnabled()) return
        val file = controller.nextDashcamRecordingFile()
        val output = FileOutputOptions.Builder(file).build()
        activeRecordingFile = file
        activeRecording = video.output
            .prepareRecording(context, output)
            .start(mainExecutor) { event ->
                when (event) {
                    is VideoRecordEvent.Start,
                    is VideoRecordEvent.Status,
                    -> Unit
                    is VideoRecordEvent.Finalize -> {
                        activeRecording = null
                        activeRecordingFile = null
                        controller.onDashcamRecordingFinalized(
                            path = file.absolutePath,
                            success = event.error == VideoRecordEvent.Finalize.ERROR_NONE,
                            detail = event.cause?.message ?: "Video recording failed (${event.error})",
                        )
                    }
                }
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

    fun capturePanoramaxPhoto() {
        val capture = imageCapture ?: return
        val sample = controller.currentPanoramaxLocationSample() ?: return
        val file = File.createTempFile("panoramax-", ".jpg", context.cacheDir)
        val options = ImageCapture.OutputFileOptions.Builder(file).build()
        capture.takePicture(
            options,
            cameraExecutor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                    controller.onPanoramaxPhotoCaptured(file.absolutePath, sample)
                }

                override fun onError(exception: ImageCaptureException) {
                    file.delete()
                }
            },
        )
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        generation.incrementAndGet()
        activeRecording?.stop()
        activeRecording = null
        activeRecordingFile = null
        imageAnalysis?.clearAnalyzer()
        imageAnalysis?.let { cameraProvider?.unbind(it) }
        imageCapture?.let { cameraProvider?.unbind(it) }
        imageAnalysis = null
        imageCapture = null
        videoCapture = null
        cameraProvider = null
        bridge?.close()
        bridge = null
        backend?.close()
        backend = null
        startupExecutor.shutdown()
        cameraExecutor.shutdown()
    }

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

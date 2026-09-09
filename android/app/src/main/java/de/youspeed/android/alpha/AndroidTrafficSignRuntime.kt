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
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.FileInputStream
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

        val detectorModel = mapAndVerify(context, detectorArtifact)
        val classifierModel = mapAndVerify(context, classifierArtifact)
        return AndroidTrafficSignVerifiedPack(
            modelPack = modelPack,
            detectorArtifact = detectorArtifact,
            classifierArtifact = classifierArtifact,
            detectorModel = detectorModel,
            classifierModel = classifierModel,
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

/** Decodes only detector channel 0 (`sign`); channels 1 (`plate`) and 2 (`face`) are out of scope. */
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
                val centerX = output[index].toDouble()
                val centerY = output[OUTPUT_ELEMENTS + index].toDouble()
                val width = output[2 * OUTPUT_ELEMENTS + index].toDouble()
                val height = output[3 * OUTPUT_ELEMENTS + index].toDouble()
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

internal object PanoramaxGermanRoadSignClasses {
    private val classIdByIndex = mapOf(
        59 to "maxspeed:10",
        60 to "maxspeed:100",
        61 to "maxspeed:120",
        62 to "maxspeed:130",
        63 to "maxspeed:20",
        64 to "maxspeed:25",
        65 to "maxspeed:30",
        66 to "maxspeed:40",
        67 to "maxspeed:5",
        68 to "maxspeed:50",
        69 to "maxspeed:60",
        70 to "maxspeed:70",
        71 to "maxspeed:80",
        72 to "maxspeed:end",
        128 to "zone:20",
        129 to "zone:30",
        130 to "zone:30:end",
        131 to "zone:end",
        133 to "zone:pedestrian",
    )

    fun classId(index: Int): String = classIdByIndex[index] ?: "classifier:$index"
}

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

    fun recognize(source: Bitmap): TrafficSignDetection? {
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

        val detections = proposals.mapNotNull { proposal -> classify(source, proposal) }
        return detections
            .filter { it.candidate.semantic.kind != TrafficSignSemanticKind.UNKNOWN }
            .maxByOrNull { it.candidate.rawScore }
            ?: detections.maxByOrNull { it.candidate.rawScore }
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

    private fun classify(source: Bitmap, proposal: AndroidYoloProposal): TrafficSignDetection? {
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
        if (bestIndex < 0 || bestScore < verifiedPack.modelPack.thresholds.unknown) return null
        val classId = PanoramaxGermanRoadSignClasses.classId(bestIndex)
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
                    TrafficSignBackendResult.Recognition(
                        detection = engine.recognize(bitmap),
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
    private var backend: AndroidLiteRtTrafficSignBackend? = null
    private var bridge: TrafficSignLiveRuntimeBridge<CameraXTrafficSignFrame>? = null

    fun start() {
        if (closed.get()) return
        val startGeneration = generation.incrementAndGet()
        onStateChanged(TrafficSignCameraRuntimeState.STARTING, "Android-TSR-Modell wird geprüft und geladen.")
        startupExecutor.execute {
            val loaded = runCatching {
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
                val analysis = ImageAnalysis.Builder()
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
                analysis.setAnalyzer(cameraExecutor) { image ->
                    val frame = CameraXTrafficSignFrame(image)
                    runtime.bridge.submit(frame)
                }
                provider.unbindAll()
                provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, analysis)
                cameraProvider = provider
                imageAnalysis = analysis
            }.onFailure { failure ->
                runtime.close()
                backend = null
                bridge = null
                onStateChanged(
                    TrafficSignCameraRuntimeState.UNAVAILABLE,
                    failure.message?.takeIf(String::isNotBlank) ?: "Rückkamera ist nicht verfügbar.",
                )
            }.onSuccess {
                onStateChanged(
                    TrafficSignCameraRuntimeState.ACTIVE,
                    "CameraX und der verifizierte Android-LiteRT-Modellpack sind aktiv.",
                )
            }
        }, mainExecutor)
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

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        generation.incrementAndGet()
        imageAnalysis?.clearAnalyzer()
        imageAnalysis?.let { cameraProvider?.unbind(it) }
        imageAnalysis = null
        cameraProvider = null
        bridge?.close()
        bridge = null
        backend?.close()
        backend = null
        startupExecutor.shutdown()
        cameraExecutor.shutdown()
    }

    private data class LoadedRuntime(
        val pack: AndroidTrafficSignVerifiedPack,
        val backend: AndroidLiteRtTrafficSignBackend,
        val bridge: TrafficSignLiveRuntimeBridge<CameraXTrafficSignFrame>,
    ) : AutoCloseable {
        override fun close() {
            bridge.close()
            backend.close()
        }
    }
}

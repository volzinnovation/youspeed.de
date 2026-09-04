package de.youspeed.android.alpha

import java.time.Instant

/**
 * Opaque, backend-specific access to one already-normalized camera frame.
 *
 * The orchestrator owns an accepted handle until it is either superseded or
 * inference completes. It never reads or copies pixels and always calls
 * [release] when ownership ends. A backend must not retain the handle after
 * invoking its completion callback.
 */
interface TrafficSignNormalizedFrameHandle {
    val frameId: String
    val source: TrafficSignInputSource
    val capturedAtUtc: Instant
    val capturedAtMonotonicNanos: Long
    val widthPixels: Int
    val heightPixels: Int

    fun release()
}

data class TrafficSignDetectionContextSnapshotValue(
    val context: TrafficSignDetectionContext,
    val generation: Long,
) {
    init {
        require(generation >= 0L) { "Traffic-sign context generation must not be negative" }
    }
}

/** Must return one internally consistent snapshot of all road-context fields and its monotonic generation. */
fun interface TrafficSignDetectionContextSnapshot {
    fun snapshot(): TrafficSignDetectionContextSnapshotValue
}

/** Backend result before temporal fusion and normalized-event construction. */
sealed interface TrafficSignBackendResult {
    data class Recognition(
        val detection: TrafficSignDetection?,
        val thermalState: String? = null,
    ) : TrafficSignBackendResult

    data class Unavailable(
        val reason: String,
        val thermalState: String? = null,
    ) : TrafficSignBackendResult {
        init {
            require(reason.isNotBlank()) { "Unavailable reason must not be blank" }
        }
    }
}

/**
 * Backend-neutral asynchronous recognizer. The callback must be invoked once;
 * duplicate callbacks are ignored defensively by the orchestrator.
 */
fun interface TrafficSignRecognitionBackend<F : TrafficSignNormalizedFrameHandle> {
    fun recognize(frame: F, completion: (TrafficSignBackendResult) -> Unit)
}

data class TrafficSignOrchestrationOutput(
    val event: TrafficSignRecognitionEvent,
    val speedOverride: TrafficSignSpeedOverride?,
    val backendFailureReason: String? = null,
)

interface TrafficSignRecognitionObserver {
    fun onRecognition(output: TrafficSignOrchestrationOutput)

    fun onSpeedOverrideChanged(current: TrafficSignSpeedOverride?) = Unit
}

/**
 * Owns frame scheduling, temporal fusion, normalized event creation, and the
 * transient speed-source override. CameraX and concrete ML runtimes remain
 * outside this pure-Kotlin type.
 *
 * A road-context snapshot is captured exactly once inside [submit], before the
 * frame can enter the asynchronous backend. The snapshot travels with the
 * frame through latest-frame replacement and inference, so its way ID,
 * coordinate, heading, direction, and source signature cannot be replaced by
 * a later navigation update.
 */
class TrafficSignRecognitionOrchestrator<F : TrafficSignNormalizedFrameHandle>(
    private val modelPack: TrafficSignModelPack,
    private val runtimeArtifact: TrafficSignArtifact,
    private val backend: TrafficSignRecognitionBackend<F>,
    private val contextSnapshot: TrafficSignDetectionContextSnapshot,
    private val conditionsSnapshot: () -> TrafficSignAnalysisConditions,
    private val monotonicClockNanos: () -> Long,
    private val observer: TrafficSignRecognitionObserver,
) {
    private val lock = Any()
    private val fusionEngine: TrafficSignFusionEngine
    private val frameSlot = TrafficSignLatestFrameSlot<AcceptedFrame<F>> { accepted ->
        accepted.frame.releaseSafely()
    }

    private var nextInferenceId = 1L
    private var activeInference: ActiveInference<F>? = null
    private var lastAcceptedTimestampNanos: Long? = null
    private var currentSourceSignature: TrafficSignRuntimeSourceSignature? = null
    private var currentRoadContextKey: RoadContextKey? = null
    private var currentContextGeneration: Long? = null
    private var currentOverride: TrafficSignSpeedOverride? = null
    private var closed = false

    init {
        TrafficSignModelPackValidator.requireValid(modelPack)
        require(runtimeArtifact.platform == TrafficSignPlatform.ANDROID) {
            "Traffic-sign runtime artifact must target Android"
        }
        require(
            modelPack.detector.artifacts.contains(runtimeArtifact) ||
                modelPack.classifier?.artifacts?.contains(runtimeArtifact) == true,
        ) { "Traffic-sign runtime artifact does not belong to the model pack" }

        fusionEngine = TrafficSignFusionEngine(
            thresholds = modelPack.thresholds,
            scoreSource = modelPack.calibration.runtimeOutput,
            classThresholds = modelPack.classMapping.associate { it.classId to it.threshold },
        )
    }

    /**
     * Accepts live-camera and explicit camera-still frames. Returns false when
     * a closed orchestrator or an out-of-order frame rejects ownership.
     */
    fun submit(frame: F): Boolean {
        validateFrame(frame)
        var dispatch: Dispatch? = null
        var overrideNotification: OverrideNotification? = null
        var accepted = false

        synchronized(lock) {
            if (!closed) {
                val previousTimestamp = lastAcceptedTimestampNanos
                if (previousTimestamp == null || frame.capturedAtMonotonicNanos >= previousTimestamp) {
                    // This single call is deliberately inside the acceptance
                    // critical section: no later frame can interleave its context.
                    val snapshot = contextSnapshot.snapshot().immutableCopy()
                    val currentGeneration = currentContextGeneration
                    if (currentGeneration != null && snapshot.generation < currentGeneration) {
                        return@synchronized
                    }
                    overrideNotification = updateRoadContextLocked(
                        context = snapshot.context,
                        contextGeneration = snapshot.generation,
                    )
                    lastAcceptedTimestampNanos = frame.capturedAtMonotonicNanos
                    frameSlot.offer(
                        value = AcceptedFrame(
                            frame = frame,
                            metadata = FrameMetadata(
                                source = frame.source,
                                capturedAtUtc = frame.capturedAtUtc,
                                capturedAtMonotonicNanos = frame.capturedAtMonotonicNanos,
                            ),
                            context = snapshot.context,
                            contextGeneration = snapshot.generation,
                        ),
                        capturedAtNanos = frame.capturedAtMonotonicNanos,
                    )
                    dispatch = takeDispatchLocked()
                    accepted = true
                }
            }
        }

        if (!accepted) frame.releaseSafely()
        overrideNotification?.deliver(observer)
        dispatch?.start()
        return accepted
    }

    /** Gives a throttled pending frame another chance to dispatch. */
    fun tick() {
        val dispatch = synchronized(lock) {
            if (closed) null else takeDispatchLocked()
        }
        dispatch?.start()
    }

    /**
     * Announces genuinely new bundled-map/local-correction information.
     * Repeating an equal signature retains the current vision override.
     */
    fun reconcileSource(
        sourceSignature: TrafficSignRuntimeSourceSignature,
        contextGeneration: Long,
    ) {
        require(contextGeneration >= 0L) { "Traffic-sign context generation must not be negative" }
        val notification = synchronized(lock) {
            if (closed) null else updateSourceLocked(sourceSignature, contextGeneration)
        }
        notification?.deliver(observer)
    }

    /**
     * Announces the current matched way and travel direction even when the
     * effective OSM/local values happen to be identical. Coordinate and
     * heading updates on the same way/direction retain the camera override;
     * a new way or U-turn clears it and invalidates delayed inference.
     */
    fun reconcileContext(
        context: TrafficSignDetectionContext,
        contextGeneration: Long,
    ) {
        require(contextGeneration >= 0L) { "Traffic-sign context generation must not be negative" }
        val immutableContext = context.immutableCopy()
        val notification = synchronized(lock) {
            if (closed) null else updateRoadContextLocked(immutableContext, contextGeneration)
        }
        notification?.deliver(observer)
    }

    fun speedOverride(): TrafficSignSpeedOverride? = synchronized(lock) { currentOverride }

    fun effectiveSpeedKmh(localCorrectionKmh: Int?, bundledMapKmh: Int?): Int? = synchronized(lock) {
        TrafficSignSpeedOverridePolicy.effectiveSpeedKmh(
            current = currentOverride,
            localCorrectionKmh = localCorrectionKmh,
            bundledMapKmh = bundledMapKmh,
        )
    }

    /** Drops a pending frame. An active backend call is allowed to return and is then released silently. */
    fun close() {
        val clearedOverride = synchronized(lock) {
            if (closed) return@synchronized false
            closed = true
            frameSlot.clear()
            val hadOverride = currentOverride != null
            currentOverride = null
            currentSourceSignature = null
            currentRoadContextKey = null
            currentContextGeneration = null
            fusionEngine.reset()
            hadOverride
        }
        if (clearedOverride) observer.onSpeedOverrideChanged(null)
    }

    private fun validateFrame(frame: F) {
        require(frame.frameId.isNotBlank()) { "Traffic-sign frame ID must not be blank" }
        require(frame.source == TrafficSignInputSource.LIVE_FRAME || frame.source == TrafficSignInputSource.CAMERA_STILL) {
            "Traffic-sign orchestration accepts live frames and camera stills"
        }
        require(frame.capturedAtMonotonicNanos >= 0L) { "Frame timestamp must not be negative" }
        require(frame.widthPixels > 0 && frame.heightPixels > 0) { "Normalized frame dimensions must be positive" }
    }

    private fun updateSourceLocked(
        sourceSignature: TrafficSignRuntimeSourceSignature,
        contextGeneration: Long,
    ): OverrideNotification? {
        val previousGeneration = currentContextGeneration
        if (previousGeneration != null && contextGeneration < previousGeneration) return null
        val previousSignature = currentSourceSignature
        if (previousGeneration == contextGeneration && previousSignature == sourceSignature) return null

        currentContextGeneration = contextGeneration
        currentSourceSignature = sourceSignature
        currentRoadContextKey = currentRoadContextKey?.copy(sourceSignature = sourceSignature)
        fusionEngine.reset()
        val previousOverride = currentOverride
        currentOverride = if (previousGeneration != null && previousGeneration != contextGeneration) {
            null
        } else {
            TrafficSignSpeedOverridePolicy.reconcileSource(previousOverride, sourceSignature)
        }
        return if (previousOverride != currentOverride) OverrideNotification(currentOverride) else null
    }

    private fun updateRoadContextLocked(
        context: TrafficSignDetectionContext,
        contextGeneration: Long,
    ): OverrideNotification? {
        val previousGeneration = currentContextGeneration
        if (previousGeneration != null && contextGeneration < previousGeneration) return null
        val nextKey = RoadContextKey(context)
        if (previousGeneration == contextGeneration && currentRoadContextKey == nextKey) return null

        currentContextGeneration = contextGeneration
        currentRoadContextKey = nextKey
        currentSourceSignature = context.sourceSignature
        fusionEngine.reset()
        val previousOverride = currentOverride
        currentOverride = previousOverride?.takeIf {
            previousGeneration == contextGeneration && RoadContextKey(it.context) == nextKey
        }
        return if (previousOverride != currentOverride) OverrideNotification(currentOverride) else null
    }

    private fun takeDispatchLocked(): Dispatch? {
        val accepted = frameSlot.takeIfDue(
            nowNanos = monotonicClockNanos(),
            conditions = conditionsSnapshot(),
        ) ?: return null
        val inferenceId = nextInferenceId++
        val active = ActiveInference(
            inferenceId = inferenceId,
            accepted = accepted.value,
            dispatchedAtNanos = monotonicClockNanos(),
        )
        activeInference = active
        return Dispatch(active) { result -> complete(inferenceId, result) }
    }

    private fun complete(inferenceId: Long, backendResult: TrafficSignBackendResult) {
        var output: TrafficSignOrchestrationOutput? = null
        var dispatch: Dispatch? = null
        var overrideNotification: OverrideNotification? = null

        synchronized(lock) {
            val active = activeInference?.takeIf { it.inferenceId == inferenceId } ?: return
            activeInference = null
            frameSlot.markAnalysisComplete()
            active.accepted.frame.releaseSafely()

            if (!closed) {
                val event = createEventLocked(active, backendResult)
                val previousOverride = currentOverride
                val signature = requireNotNull(currentSourceSignature)
                currentOverride = TrafficSignSpeedOverridePolicy.applyRecognition(
                    current = previousOverride,
                    event = event,
                    currentSourceSignature = signature,
                )
                if (previousOverride != currentOverride) {
                    overrideNotification = OverrideNotification(currentOverride)
                }
                output = TrafficSignOrchestrationOutput(
                    event = event,
                    speedOverride = currentOverride,
                    backendFailureReason = (backendResult as? TrafficSignBackendResult.Unavailable)?.reason,
                )
                dispatch = takeDispatchLocked()
            }
        }

        overrideNotification?.deliver(observer)
        output?.let(observer::onRecognition)
        dispatch?.start()
    }

    private fun createEventLocked(
        active: ActiveInference<F>,
        backendResult: TrafficSignBackendResult,
    ): TrafficSignRecognitionEvent {
        val latencyNanos = (monotonicClockNanos() - active.dispatchedAtNanos).coerceAtLeast(0L)
        val sourceIsCurrent = active.accepted.contextGeneration == currentContextGeneration &&
            RoadContextKey(active.accepted.context) == currentRoadContextKey &&
            active.accepted.context.sourceSignature == currentSourceSignature
        val fusion = when (backendResult) {
            is TrafficSignBackendResult.Recognition -> if (sourceIsCurrent) {
                fusionEngine.observe(
                    detection = backendResult.detection,
                    observedAtMs = active.accepted.metadata.capturedAtMonotonicNanos / NANOS_PER_MILLISECOND,
                )
            } else {
                null
            }
            is TrafficSignBackendResult.Unavailable -> null
        }

        return TrafficSignRecognitionEvent(
            schemaVersion = modelPack.schemaVersion,
            packId = modelPack.packId,
            artifactSha256 = runtimeArtifact.sha256,
            preprocessingVersion = modelPack.preprocessing.version,
            source = active.accepted.metadata.source,
            frameTimestampUtc = active.accepted.metadata.capturedAtUtc,
            state = when {
                backendResult is TrafficSignBackendResult.Unavailable -> TrafficSignRecognitionState.UNAVAILABLE
                !sourceIsCurrent -> TrafficSignRecognitionState.NO_RECOGNITION
                else -> requireNotNull(fusion).state
            },
            candidate = fusion?.candidate,
            roadContext = active.accepted.context,
            latencyMs = latencyNanos.toDouble() / NANOS_PER_MILLISECOND,
            thermalState = when (backendResult) {
                is TrafficSignBackendResult.Recognition -> backendResult.thermalState
                is TrafficSignBackendResult.Unavailable -> backendResult.thermalState
            },
        )
    }

    private inner class Dispatch(
        private val active: ActiveInference<F>,
        private val completion: (TrafficSignBackendResult) -> Unit,
    ) {
        fun start() {
            try {
                backend.recognize(active.accepted.frame, completion)
            } catch (failure: Throwable) {
                completion(
                    TrafficSignBackendResult.Unavailable(
                        reason = failure.message?.takeIf(String::isNotBlank) ?: failure::class.java.simpleName,
                    ),
                )
            }
        }
    }

    private data class AcceptedFrame<T : TrafficSignNormalizedFrameHandle>(
        val frame: T,
        val metadata: FrameMetadata,
        val context: TrafficSignDetectionContext,
        val contextGeneration: Long,
    )

    private data class FrameMetadata(
        val source: TrafficSignInputSource,
        val capturedAtUtc: Instant,
        val capturedAtMonotonicNanos: Long,
    )

    private data class RoadContextKey(
        val wayId: String,
        val travelDirection: TrafficSignTravelDirection,
        val sourceSignature: TrafficSignRuntimeSourceSignature,
    ) {
        constructor(context: TrafficSignDetectionContext) : this(
            wayId = context.wayId,
            travelDirection = context.travelDirection,
            sourceSignature = context.sourceSignature,
        )
    }

    private data class ActiveInference<T : TrafficSignNormalizedFrameHandle>(
        val inferenceId: Long,
        val accepted: AcceptedFrame<T>,
        val dispatchedAtNanos: Long,
    )

    private data class OverrideNotification(val current: TrafficSignSpeedOverride?) {
        fun deliver(observer: TrafficSignRecognitionObserver) = observer.onSpeedOverrideChanged(current)
    }

    private companion object {
        const val NANOS_PER_MILLISECOND = 1_000_000L
    }
}

private fun TrafficSignDetectionContext.immutableCopy() = copy(
    sourceSignature = sourceSignature.copy(),
)

private fun TrafficSignDetectionContextSnapshotValue.immutableCopy() = copy(
    context = context.immutableCopy(),
)

private fun TrafficSignNormalizedFrameHandle.releaseSafely() {
    runCatching(::release)
}

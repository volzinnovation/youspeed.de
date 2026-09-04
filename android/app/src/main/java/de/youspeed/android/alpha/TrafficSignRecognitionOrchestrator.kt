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
    val runtimeActivationEligible: Boolean = false,
    val driveSessionId: String? = null,
) {
    init {
        require(generation >= 0L) { "Traffic-sign context generation must not be negative" }
    }
}

/** Must return one internally consistent snapshot of all road-context fields and its monotonic generation. */
fun interface TrafficSignDetectionContextSnapshot {
    fun snapshot(): TrafficSignDetectionContextSnapshotValue?
}

/** Backend result before temporal fusion and normalized-event construction. */
sealed interface TrafficSignBackendResult {
    data class Recognition(
        val detection: TrafficSignDetection?,
        val thermalState: String? = null,
        val strongPassGeometry: Boolean = false,
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
    val passageEvent: TrafficSignPassageEvent? = null,
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
    private val passageFinalizer = TrafficSignPassageFinalizer()
    private val frameSlot = TrafficSignLatestFrameSlot<AcceptedFrame<F>> { accepted ->
        accepted.frame.releaseSafely()
    }

    private var nextInferenceId = 1L
    private var activeInference: ActiveInference<F>? = null
    private var lastAcceptedTimestampNanos: Long? = null
    private var currentSourceSignature: TrafficSignRuntimeSourceSignature? = null
    private var currentRoadContextKey: RoadContextKey? = null
    private var currentRoadContext: TrafficSignDetectionContext? = null
    /** Scope of the physical sign currently being assembled/finalized. */
    private var currentEligibleRouteRelationGroupIds: Set<Long> = emptySet()
    /** Independent scope of the already-published legacy passage projection. */
    private var currentOverrideEligibleRouteRelationGroupIds: Set<Long> = emptySet()
    /** Invalidates any inference accepted before an incompatible route/source reset. */
    private var currentScopeEpoch = 0L
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
                    val snapshot = contextSnapshot.snapshot()?.immutableCopy() ?: return@synchronized
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
                                frameId = frame.frameId,
                                source = frame.source,
                                capturedAtUtc = frame.capturedAtUtc,
                                capturedAtMonotonicNanos = frame.capturedAtMonotonicNanos,
                            ),
                            context = snapshot.context,
                            contextGeneration = snapshot.generation,
                            scopeEpoch = currentScopeEpoch,
                            eligibleRouteRelationGroupIds = currentEligibleRouteRelationGroupIds.toSet(),
                            runtimeActivationEligible = snapshot.runtimeActivationEligible,
                            driveSessionId = snapshot.driveSessionId,
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
            currentRoadContext = null
            currentEligibleRouteRelationGroupIds = emptySet()
            currentOverrideEligibleRouteRelationGroupIds = emptySet()
            currentContextGeneration = null
            fusionEngine.reset()
            passageFinalizer.reset()
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

        val generationChanged = previousGeneration != null && previousGeneration != contextGeneration
        val osmChanged = previousSignature != null && previousSignature.bundleRevision != sourceSignature.bundleRevision
        currentContextGeneration = contextGeneration
        currentSourceSignature = sourceSignature
        currentRoadContextKey = currentRoadContextKey?.copy(sourceSignature = sourceSignature)
        val previousOverride = currentOverride
        currentOverride = if (generationChanged || osmChanged) {
            null
        } else {
            previousOverride
        }
        if (generationChanged || osmChanged) {
            currentScopeEpoch += 1L
            currentOverrideEligibleRouteRelationGroupIds = emptySet()
            fusionEngine.reset()
            passageFinalizer.reset(contextGeneration)
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

        val previousContext = currentRoadContext
        val generationChanged = previousGeneration != null && previousGeneration != contextGeneration
        val hadActiveTrack = passageFinalizer.hasActiveTrack()
        val trackReconciliation = if (!generationChanged && hadActiveTrack) {
            passageFinalizer.reconcileRoadContext(context)
        } else {
            null
        }
        val compatibleScope = !generationChanged && previousContext != null && (
            trackReconciliation?.activeScope != null ||
                (!hadActiveTrack && contextsShareScope(
                    previous = previousContext,
                    next = context,
                    eligibleRouteRelationGroupIds = currentEligibleRouteRelationGroupIds,
                ))
            )
        currentContextGeneration = contextGeneration
        currentRoadContextKey = nextKey
        currentRoadContext = context
        currentSourceSignature = context.sourceSignature
        val previousOverride = currentOverride
        currentOverride = previousOverride?.takeIf {
            !generationChanged && contextsShareScope(
                previous = it.context,
                next = context,
                eligibleRouteRelationGroupIds = currentOverrideEligibleRouteRelationGroupIds,
            )
        }
        if (currentOverride == null) currentOverrideEligibleRouteRelationGroupIds = emptySet()
        if (generationChanged) {
            currentScopeEpoch += 1L
            currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
            fusionEngine.reset()
            passageFinalizer.reset(contextGeneration)
        } else if (hadActiveTrack) {
            val reconciliation = requireNotNull(trackReconciliation)
            if (reconciliation.trackSetChanged) currentScopeEpoch += 1L
            val survivingScope = reconciliation.activeScope
            if (survivingScope == null) {
                currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
                fusionEngine.reset()
            } else {
                currentEligibleRouteRelationGroupIds = survivingScope.eligibleRouteRelationGroupIds
            }
        } else if (previousContext != null && !compatibleScope) {
            currentScopeEpoch += 1L
            currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
            fusionEngine.reset()
            passageFinalizer.reset(contextGeneration)
        } else if (previousContext == null) {
            currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
        } else if (
            previousContext.wayId == null &&
            context.wayId != null &&
            passageFinalizer.activeTrackAwaitsMatchedRecognitionOrigin()
        ) {
            // Keep the orchestrator's compatibility scope aligned with the
            // finalizer when acquisition began during a transient no-match.
            // A known-way track never enters this branch, so a later rematch
            // cannot acquire an unrelated relation transitively.
            currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
        } else if (previousContext.wayId != null && context.wayId != null && previousContext.wayId != context.wayId) {
            currentEligibleRouteRelationGroupIds = currentEligibleRouteRelationGroupIds.intersect(
                context.routeRelationGroupIds,
            )
            if (currentOverride != null) {
                currentOverrideEligibleRouteRelationGroupIds = currentOverrideEligibleRouteRelationGroupIds.intersect(
                    context.routeRelationGroupIds,
                )
            }
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
                val created = createEventLocked(active, backendResult)
                val event = created.event
                if (!passageFinalizer.hasActiveTrack() && event.candidate != null) {
                    currentEligibleRouteRelationGroupIds = active.accepted.context.routeRelationGroupIds
                }
                val passage = passageFinalizer.observe(
                    event = event,
                    fusedScore = created.fusedScore,
                    contextGeneration = active.accepted.contextGeneration,
                    qualifiedAnalyzedFrame = created.qualifiedAnalyzedFrame,
                    overrideEligible = modelPack.calibration.calibrated &&
                        modelPack.calibration.runtimeOutput == TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE &&
                        active.accepted.runtimeActivationEligible,
                    strongPassGeometry = (backendResult as? TrafficSignBackendResult.Recognition)?.strongPassGeometry == true,
                )
                val previousOverride = currentOverride
                currentOverride = passage?.let {
                    TrafficSignSpeedOverridePolicy.applyPassage(previousOverride, it)
                } ?: previousOverride
                if (currentOverride != previousOverride) {
                    currentOverrideEligibleRouteRelationGroupIds = if (currentOverride == null) {
                        emptySet()
                    } else {
                        passage?.eligibleRouteRelationGroupIds.orEmpty()
                    }
                }
                // observe() may replace an unarmed incompatible track or may
                // promote an independently scoped queued track after the old
                // passage commits. Adopt that sign's frozen intersection;
                // never derive it from the preceding track's narrowed scope.
                passageFinalizer.activeTrackRouteScope()?.let { activeScope ->
                    currentEligibleRouteRelationGroupIds = activeScope.eligibleRouteRelationGroupIds
                }
                if (previousOverride != currentOverride) {
                    overrideNotification = OverrideNotification(currentOverride)
                }
                output = TrafficSignOrchestrationOutput(
                    event = event,
                    speedOverride = currentOverride,
                    passageEvent = passage,
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
    ): CreatedEvent {
        val latencyNanos = (monotonicClockNanos() - active.dispatchedAtNanos).coerceAtLeast(0L)
        val currentContext = currentRoadContext
        val sourceIsCurrent = active.accepted.contextGeneration == currentContextGeneration &&
            active.accepted.scopeEpoch == currentScopeEpoch &&
            currentContext != null &&
            active.accepted.context.hasVerifiedBundle &&
            contextsShareScope(
                previous = active.accepted.context,
                next = currentContext,
                eligibleRouteRelationGroupIds = active.accepted.eligibleRouteRelationGroupIds,
            ) &&
            active.accepted.context.sourceSignature.bundleRevision == currentSourceSignature?.bundleRevision
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

        val event = TrafficSignRecognitionEvent(
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
            frameId = active.accepted.metadata.frameId,
            driveSessionId = active.accepted.driveSessionId,
            calibrationId = modelPack.calibration.revision,
            componentRole = if (modelPack.pipeline == TrafficSignPipeline.DIRECT_DETECTION) {
                "direct_detector"
            } else {
                "proposal_detector"
            },
            modelComponents = buildList {
                modelPack.androidArtifact(modelPack.detector)?.let { artifact ->
                    add(
                        TrafficSignModelComponentLineage(
                            role = if (modelPack.pipeline == TrafficSignPipeline.DIRECT_DETECTION) {
                                "direct_detector"
                            } else {
                                "proposal_detector"
                            },
                            artifactSha256 = artifact.sha256,
                            preprocessingVersion = modelPack.preprocessing.version,
                            calibrationId = modelPack.calibration.revision,
                        ),
                    )
                }
                modelPack.classifier?.let { classifier ->
                    modelPack.androidArtifact(classifier)?.let { artifact ->
                        add(
                            TrafficSignModelComponentLineage(
                                role = "semantic_classifier",
                                artifactSha256 = artifact.sha256,
                                preprocessingVersion = modelPack.preprocessing.version,
                                calibrationId = modelPack.calibration.revision,
                            ),
                        )
                    }
                }
            },
        )
        return CreatedEvent(
            event = event,
            fusedScore = fusion?.fusedScore,
            qualifiedAnalyzedFrame = backendResult is TrafficSignBackendResult.Recognition &&
                sourceIsCurrent &&
                active.accepted.metadata.source == TrafficSignInputSource.LIVE_FRAME,
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
        val scopeEpoch: Long,
        val eligibleRouteRelationGroupIds: Set<Long>,
        val runtimeActivationEligible: Boolean,
        val driveSessionId: String?,
    )

    private data class FrameMetadata(
        val frameId: String,
        val source: TrafficSignInputSource,
        val capturedAtUtc: Instant,
        val capturedAtMonotonicNanos: Long,
    )

    private data class RoadContextKey(
        val wayId: String?,
        val travelDirection: TrafficSignTravelDirection,
        val sourceSignature: TrafficSignRuntimeSourceSignature,
        val bundleSha256: String?,
        val traversalEpoch: Long,
        val routeRelationGroupIds: Set<Long>,
    ) {
        constructor(context: TrafficSignDetectionContext) : this(
            wayId = context.wayId,
            travelDirection = context.travelDirection,
            sourceSignature = context.sourceSignature,
            bundleSha256 = context.bundleSha256,
            traversalEpoch = context.traversalEpoch,
            routeRelationGroupIds = context.routeRelationGroupIds,
        )
    }

    private data class CreatedEvent(
        val event: TrafficSignRecognitionEvent,
        val fusedScore: Double?,
        val qualifiedAnalyzedFrame: Boolean,
    )

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

private fun contextsShareScope(
    previous: TrafficSignDetectionContext,
    next: TrafficSignDetectionContext,
    eligibleRouteRelationGroupIds: Set<Long>,
): Boolean {
    if (previous.sourceSignature.bundleRevision != next.sourceSignature.bundleRevision) return false
    if (previous.bundleSha256 != next.bundleSha256) return false
    if (previous.traversalEpoch != next.traversalEpoch) return false
    // A brief no-match is neutral. The passage resolver owns its time/distance
    // bound and validates the first stabilized rematch against the frozen scope.
    if (previous.wayId == null || next.wayId == null) return true
    if (previous.wayId == next.wayId) {
        return previous.travelDirection == TrafficSignTravelDirection.UNKNOWN ||
            next.travelDirection == TrafficSignTravelDirection.UNKNOWN ||
            previous.travelDirection == next.travelDirection
    }
    if (!previous.continuityCapable || !next.continuityCapable) return false
    return eligibleRouteRelationGroupIds.intersect(next.routeRelationGroupIds).isNotEmpty()
}

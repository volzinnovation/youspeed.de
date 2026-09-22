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
    /** Runtime/source admission for authoritative live-frame passage evaluation; independent of vehicle speed. */
    val runtimeActivationEligible: Boolean = false,
    val driveSessionId: String? = null,
    val applicabilityMapFix: TSRMapFix? = null,
) {
    init {
        require(generation >= 0L) { "Traffic-sign context generation must not be negative" }
    }
}

/**
 * Compact per-frame evidence from the concrete camera backend. Keeping this
 * separate from the public recognition event makes failures at detector,
 * classifier, fusion, and context stages distinguishable in field logs.
 */
data class TrafficSignInferenceDiagnostics(
    val inferenceMs: Double,
    val detectorProposalCount: Int,
    val detectorTopScore: Double?,
    val classifierInvocationCount: Int,
    val classifiedDetectionCount: Int,
    val classifierTopScore: Double?,
    val primaryClassId: String?,
    val primaryScore: Double?,
    val detectorRawSignTopScore: Double? = null,
    val detectorRawGlobalTopScore: Double? = null,
    val detectorRawSignScoresAboveThreshold: Int = 0,
    val sourceWidthPixels: Int = 0,
    val sourceHeightPixels: Int = 0,
    val sourceLumaMean: Double? = null,
    val executionBackend: String? = null,
    val accelerationFallbackReason: String? = null,
    val detectorPreprocessingMs: Double? = null,
    val detectorInferenceMs: Double? = null,
    val classifierInferenceMs: Double? = null,
    val backendQueueWaitMs: Double? = null,
    val frameConversionMs: Double? = null,
    val cameraReceiptToResultMs: Double? = null,
) {
    init {
        require(inferenceMs.isFinite() && inferenceMs >= 0.0)
        require(detectorProposalCount >= 0)
        require(classifierInvocationCount >= 0)
        require(classifiedDetectionCount >= 0)
        require(detectorTopScore == null || detectorTopScore.isFinite())
        require(classifierTopScore == null || classifierTopScore.isFinite())
        require(primaryScore == null || primaryScore.isFinite())
        require(detectorRawSignTopScore == null || detectorRawSignTopScore.isFinite())
        require(detectorRawGlobalTopScore == null || detectorRawGlobalTopScore.isFinite())
        require(detectorRawSignScoresAboveThreshold >= 0)
        require(sourceWidthPixels >= 0)
        require(sourceHeightPixels >= 0)
        require(sourceLumaMean == null || sourceLumaMean.isFinite())
        require(listOf(detectorPreprocessingMs, detectorInferenceMs, classifierInferenceMs,
            backendQueueWaitMs, frameConversionMs, cameraReceiptToResultMs)
            .all { it == null || (it.isFinite() && it >= 0.0) })
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
        val displayDetections: List<TrafficSignDetection> = listOfNotNull(detection),
        val diagnostics: TrafficSignInferenceDiagnostics? = null,
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
    val terminalBackendFailure: Boolean = false,
    val contextGeneration: Long = 0L,
    val contextIsCurrent: Boolean = true,
    val displayObservation: TrafficSignDisplayObservation? = null,
    val inferenceDiagnostics: TrafficSignInferenceDiagnostics? = null,
    val effectiveConfirmationWindowMs: Long? = null,
    val applicabilityDiagnostic: TSRApplicabilityDiagnostic? = null,
    val annotationEvent: TrafficSignRecognitionEvent? = null,
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
    confirmationWindowMsOverride: Long? = null,
) {
    private val lock = Any()
    private val fusionEngine: TrafficSignFusionEngine
    private val annotationFusion: TrafficSignFusionEngine
    private val startupTimingVerified = confirmationWindowMsOverride != null
    private val passageFinalizer = TrafficSignPassageFinalizer()
    private val applicabilitySession = TSRApplicabilitySession()
    private var applicabilityScope: TSRApplicabilityScope? = null
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
    private var consecutiveBackendFailures = 0
    private var terminalBackendFailure = false
    private var candidateBurstUntilNanos = Long.MIN_VALUE

    init {
        TrafficSignModelPackValidator.requireValid(modelPack)
        require(runtimeArtifact.platform == TrafficSignPlatform.ANDROID) {
            "Traffic-sign runtime artifact must target Android"
        }
        require(
            modelPack.detector.artifacts.contains(runtimeArtifact) ||
                modelPack.classifier?.artifacts?.contains(runtimeArtifact) == true,
        ) { "Traffic-sign runtime artifact does not belong to the model pack" }

        val confirmationWindowMs = confirmationWindowMsOverride ?: modelPack.thresholds.confirmationWindowMs
        require(confirmationWindowMs in modelPack.thresholds.confirmationWindowMs..maxOf(
            modelPack.thresholds.confirmationWindowMs,
            TrafficSignInferenceTimingPolicy.MAXIMUM_CONFIRMATION_WINDOW_MS,
        )) { "Device timing must preserve the manifest window and stay within the bounded allowance" }
        fusionEngine = TrafficSignFusionEngine(
            thresholds = modelPack.thresholds.copy(confirmationWindowMs = confirmationWindowMs),
            scoreSource = modelPack.calibration.runtimeOutput,
            classThresholds = modelPack.classMapping.associate { it.classId to it.threshold },
        )
        annotationFusion = TrafficSignFusionEngine(
            thresholds = modelPack.thresholds.copy(confirmationWindowMs = confirmationWindowMs),
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
            if (!closed && !terminalBackendFailure) {
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
                            applicabilityMapFix = snapshot.applicabilityMapFix,
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
            fusionEngine.reset(); annotationFusion.reset()
            passageFinalizer.reset()
            applicabilitySession.reset()
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
            fusionEngine.reset(); annotationFusion.reset()
            passageFinalizer.reset(contextGeneration)
            applicabilitySession.reset()
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
            fusionEngine.reset(); annotationFusion.reset()
            passageFinalizer.reset(contextGeneration)
            applicabilitySession.reset()
        } else if (hadActiveTrack) {
            val reconciliation = requireNotNull(trackReconciliation)
            if (reconciliation.trackSetChanged) currentScopeEpoch += 1L
            val survivingScope = reconciliation.activeScope
            if (survivingScope == null) {
                currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
                fusionEngine.reset(); annotationFusion.reset()
            } else {
                currentEligibleRouteRelationGroupIds = survivingScope.eligibleRouteRelationGroupIds
            }
        } else if (previousContext != null && !compatibleScope) {
            currentScopeEpoch += 1L
            currentEligibleRouteRelationGroupIds = context.routeRelationGroupIds
            fusionEngine.reset(); annotationFusion.reset()
            passageFinalizer.reset(contextGeneration)
            applicabilitySession.reset()
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
        if (terminalBackendFailure) return null
        val now = monotonicClockNanos()
        val supplied = conditionsSnapshot()
        val accepted = frameSlot.takeIfDue(
            nowNanos = now,
            conditions = supplied.copy(hasActiveTrack = supplied.hasActiveTrack || now < candidateBurstUntilNanos),
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
            val active = activeInference
            if (active == null || active.inferenceId != inferenceId) {
                return
            }
            activeInference = null
            frameSlot.markAnalysisComplete()
            active.accepted.frame.releaseSafely()

            if (!closed) {
                val created = createEventLocked(active, backendResult)
                val event = created.event
                if (created.contextIsCurrent && backendResult is TrafficSignBackendResult.Unavailable) {
                    consecutiveBackendFailures += 1
                    if (consecutiveBackendFailures >= MAXIMUM_CONSECUTIVE_BACKEND_FAILURES) {
                        terminalBackendFailure = true
                        frameSlot.clear()
                    }
                } else if (created.contextIsCurrent) {
                    consecutiveBackendFailures = 0
                    val candidateSeen = event.state in setOf(
                        TrafficSignRecognitionState.PROVISIONAL,
                        TrafficSignRecognitionState.CONFIRMED,
                        TrafficSignRecognitionState.UNKNOWN,
                    )
                    if (candidateSeen) {
                        candidateBurstUntilNanos = monotonicClockNanos() + CANDIDATE_BURST_NANOS
                    }
                }
                if (!passageFinalizer.hasActiveTrack() && event.candidate != null) {
                    currentEligibleRouteRelationGroupIds = active.accepted.context.routeRelationGroupIds
                }
                // Fusion reaches CONFIRMED after the required consecutive
                // evidence frames. Apply numeric camera limits at that point;
                // passage finalization remains the durable persistence and
                // long-lived scope-validation path.
                if (created.contextIsCurrent &&
                    active.accepted.runtimeActivationEligible &&
                    event.source == TrafficSignInputSource.LIVE_FRAME && event.permitsApplicability("immediate") &&
                    event.roadContext?.wayId?.isNotBlank() == true &&
                    event.roadContext.matchedWayStable &&
                    event.roadContext.hasVerifiedBundle
                ) {
                    currentSourceSignature?.let { sourceSignature ->
                        currentOverride = TrafficSignSpeedOverridePolicy.applyRecognition(
                            current = currentOverride,
                            event = event,
                            currentSourceSignature = sourceSignature,
                        )
                    }
                }
                val passage = passageFinalizer.observe(
                    event = event,
                    fusedScore = created.fusedScore,
                    contextGeneration = active.accepted.contextGeneration,
                    qualifiedAnalyzedFrame = created.qualifiedAnalyzedFrame && applicabilitySession.canConsumePassage(
                        passageFinalizer.activePhysicalTrackId(), created.selectedTrackId, TSRApplicabilityConfiguration.defaultMode),
                    // Calibration remains provenance. During field testing a
                    // raw-score pack uses its declared raw thresholds and is
                    // just as eligible for passage evaluation.
                    overrideEligible = active.accepted.runtimeActivationEligible,
                    strongPassGeometry = (backendResult as? TrafficSignBackendResult.Recognition)?.strongPassGeometry == true,
                )?.let { it.copy(applicabilityDecision = applicabilitySession.passageDecision(it.physicalTrackId)) }?.takeIf { it.permitsApplicability() }
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
                    // Presentation is independent from speed-limit activation.
                    // Eligible confirmed frames preserve iPhone immediate-preview
                    // timing; durable authority still waits for passage.
                    displayObservation = if (created.qualifiedAnalyzedFrame &&
                        !active.accepted.driveSessionId.isNullOrBlank() && backendResult is TrafficSignBackendResult.Recognition
                    ) {
                        TrafficSignDisplayPolicy.accepted(created.displayDetections)?.let {
                            TrafficSignDisplayObservation(it, active.accepted.contextGeneration, requireNotNull(active.accepted.driveSessionId), applicabilityDecision = created.event.applicabilityDecision)
                        }
                    } else null,
                    backendFailureReason = (backendResult as? TrafficSignBackendResult.Unavailable)?.reason,
                    terminalBackendFailure = terminalBackendFailure,
                    contextGeneration = active.accepted.contextGeneration,
                    contextIsCurrent = created.contextIsCurrent,
                    inferenceDiagnostics = (backendResult as? TrafficSignBackendResult.Recognition)?.diagnostics,
                    effectiveConfirmationWindowMs = fusionEngine.confirmationWindowMs,
                    applicabilityDiagnostic = created.applicabilityDiagnostic,
                    annotationEvent = created.annotationEvent,
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
        if (sourceIsCurrent && startupTimingVerified &&
            active.accepted.metadata.source == TrafficSignInputSource.LIVE_FRAME &&
            backendResult is TrafficSignBackendResult.Recognition
        ) {
            val diagnostics = backendResult.diagnostics
            if (diagnostics?.executionBackend in setOf("cpu", "mixed") &&
                !diagnostics?.accelerationFallbackReason.isNullOrBlank()
            ) {
                val measured = TrafficSignInferenceTimingPolicy.profile(
                    manifestConfirmationWindowMs = modelPack.thresholds.confirmationWindowMs,
                    referenceVerified = true,
                    warmInferenceTimesMs = listOf(requireNotNull(diagnostics).inferenceMs),
                )
                if (measured != null && measured.confirmationWindowMs > fusionEngine.confirmationWindowMs) {
                    // A runtime GPU failure can make the startup GPU timing
                    // obsolete. Keep the same scores and evidence, allowing
                    // only the bounded time needed by successful CPU frames.
                    fusionEngine.extendConfirmationWindowTo(measured.confirmationWindowMs)
                    annotationFusion.extendConfirmationWindowTo(measured.confirmationWindowMs)
                }
            }
        }
        val rawDetections = (backendResult as? TrafficSignBackendResult.Recognition)?.displayDetections.orEmpty()
        val scope = TSRApplicabilityScope(active.accepted.driveSessionId ?: "no-session",
            active.accepted.context.bundleSha256 ?: "unverified",
            "normalized:${active.accepted.frame.widthPixels}x${active.accepted.frame.heightPixels}",
            active.accepted.contextGeneration, active.accepted.contextGeneration, active.accepted.context.traversalEpoch)
        val batch = TSRFrameCandidateBatch(1, active.accepted.metadata.frameId,
            active.accepted.metadata.capturedAtUtc.toEpochMilli().toDouble(), scope,
            if (backendResult is TrafficSignBackendResult.Recognition && sourceIsCurrent) "analyzed" else "failed",
            rawDetections.take(TSRApplicabilityConfiguration.maxCandidates).mapIndexed { index, detection ->
                val c = detection.candidate; val b = c.boundingBox
                val score = if (modelPack.calibration.runtimeOutput == TrafficSignCalibrationOutput.RAW_SCORE) c.rawScore else c.calibratedConfidence ?: Double.NEGATIVE_INFINITY
                TSRApplicabilityCandidate("${active.accepted.metadata.frameId}:$index", "${c.semantic.kind.wireValue}:${c.semantic.value}:${c.semantic.unit}",
                    TSRApplicabilityBox(b.x, b.y, b.width, b.height), c.rawScore,
                    score >= maxOf(modelPack.thresholds.unknown, modelPack.classMapping.firstOrNull { it.classId == c.rawClassId }?.threshold ?: 0.0), c.assemblyId, score.takeIf { it.isFinite() }, c.calibratedConfidence)
            }, rawDetections.size > TSRApplicabilityConfiguration.maxCandidates ||
                ((backendResult as? TrafficSignBackendResult.Recognition)?.diagnostics?.detectorProposalCount ?: 0) >= 12,
            rawDetections.size, runtimeArtifact.sha256, modelPack.preprocessing.version,
            active.accepted.applicabilityMapFix?.snapshot(scope))
        if (sourceIsCurrent && TSRApplicabilityConfiguration.defaultMode != "shadow" && applicabilityScope != scope) {
            fusionEngine.reset(); annotationFusion.reset(); passageFinalizer.reset(active.accepted.contextGeneration)
        }
        if (sourceIsCurrent) applicabilityScope = scope
        val applicability = if (sourceIsCurrent) applicabilitySession.evaluate(batch) else null
        val exitWithheld = if (sourceIsCurrent) TSRMotorwayExitPolicy.withheldCandidates(batch) else emptySet()
        val exitEligibleDetections = rawDetections.filterIndexed { index, _ ->
            "${batch.frameId}:$index" !in exitWithheld
        }
        if (exitWithheld.isNotEmpty()) {
            fusionEngine.reset(); passageFinalizer.reset(active.accepted.contextGeneration)
        }
        val enforcing = TSRApplicabilityConfiguration.defaultMode != "shadow"
        if (enforcing && applicability != null && passageFinalizer.activePhysicalTrackId()?.let { id -> applicability.tracks.none { it.trackId == id } } == true) {
            passageFinalizer.reset(active.accepted.contextGeneration) // Expiry is cancellation, never passage.
        }
        val selectedTrack = applicability?.tracks?.filter { track -> applicability.decisions.any { it.trackId == track.trackId && it.immediateEligible } }
            ?.sortedWith(compareByDescending<TSRPhysicalTrackSnapshot> { it.trackId == passageFinalizer.activePhysicalTrackId() }
                .thenByDescending { it.samples.lastOrNull()?.candidate?.rawScore ?: 0.0 }.thenBy { it.trackId })?.firstOrNull()
        val selectedIndex = selectedTrack?.samples?.lastOrNull()?.candidate?.candidateId?.substringAfterLast(':')?.toIntOrNull()
        val selectedDetection = if (enforcing) selectedIndex?.let { rawDetections[it] } else
            (backendResult as? TrafficSignBackendResult.Recognition)?.detection?.takeIf {
                exitWithheld.isEmpty() || exitEligibleDetections.any { eligible ->
                    eligible.candidate.rawClassId == it.candidate.rawClassId && eligible.candidate.boundingBox == it.candidate.boundingBox
                }
            }
        val physicalSamples = selectedTrack?.samples?.filter { it.candidate.recognitionEligible && batch.capturedAtMs - it.capturedAtMs <= fusionEngine.confirmationWindowMs }.orEmpty()
        val fusion = when (backendResult) {
            is TrafficSignBackendResult.Recognition -> if (sourceIsCurrent) {
                fusionEngine.observe(
                    detection = selectedDetection,
                    physicalTrackId = if (enforcing) selectedTrack?.trackId else null,
                    physicalEvidenceFrames = if (enforcing) physicalSamples.size else null,
                    physicalHasConfirmedEvidence = if (enforcing) physicalSamples.any { (it.candidate.recognitionScore ?: Double.NEGATIVE_INFINITY) >= modelPack.thresholds.confirmed } else null,
                    observedAtMs = active.accepted.metadata.capturedAtMonotonicNanos / NANOS_PER_MILLISECOND,
                )
            } else {
                null
            }
            is TrafficSignBackendResult.Unavailable -> null
        }

        val eventTrackId = if (enforcing) selectedTrack?.trackId else selectedDetection?.let { detection ->
            val index = rawDetections.indexOf(detection)
            applicability?.tracks?.firstOrNull { it.samples.lastOrNull()?.candidate?.candidateId == "${active.accepted.metadata.frameId}:$index" }?.trackId
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
            applicabilityDecision = applicability?.decisions?.firstOrNull { it.trackId == eventTrackId },
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
        // Independent raw confirmation feeds only the existing annotation sink.
        val annotationEvent = if ((enforcing || exitWithheld.isNotEmpty()) && sourceIsCurrent && backendResult is TrafficSignBackendResult.Recognition) {
            val raw = annotationFusion.observe(backendResult.detection,
                observedAtMs = active.accepted.metadata.capturedAtMonotonicNanos / NANOS_PER_MILLISECOND)
            val index = rawDetections.indexOf(backendResult.detection)
            val track = applicability?.tracks?.firstOrNull {
                it.samples.lastOrNull()?.candidate?.candidateId == "${active.accepted.metadata.frameId}:$index"
            }
            event.copy(state = raw.state, candidate = raw.candidate,
                applicabilityDecision = applicability?.decisions?.firstOrNull { it.trackId == track?.trackId })
        } else null
        return CreatedEvent(
            event = event,
            fusedScore = fusion?.fusedScore,
            applicabilityDiagnostic = applicability,
            annotationEvent = annotationEvent,
            selectedTrackId = selectedTrack?.trackId,
            displayDetections = if (enforcing) listOfNotNull(selectedDetection) else exitEligibleDetections,
            contextIsCurrent = sourceIsCurrent,
            qualifiedAnalyzedFrame = backendResult is TrafficSignBackendResult.Recognition &&
                exitWithheld.isEmpty() &&
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
        val applicabilityMapFix: TSRMapFix?,
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
        val matchedWayStable: Boolean,
    ) {
        constructor(context: TrafficSignDetectionContext) : this(
            wayId = context.wayId,
            travelDirection = context.travelDirection,
            sourceSignature = context.sourceSignature,
            bundleSha256 = context.bundleSha256,
            traversalEpoch = context.traversalEpoch,
            routeRelationGroupIds = context.routeRelationGroupIds,
            matchedWayStable = context.matchedWayStable,
        )
    }

    private data class CreatedEvent(
        val event: TrafficSignRecognitionEvent,
        val fusedScore: Double?,
        val contextIsCurrent: Boolean,
        val qualifiedAnalyzedFrame: Boolean,
        val applicabilityDiagnostic: TSRApplicabilityDiagnostic?,
        val selectedTrackId: String?,
        val displayDetections: List<TrafficSignDetection>,
        val annotationEvent: TrafficSignRecognitionEvent?,
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
        const val CANDIDATE_BURST_NANOS = 1_500_000_000L
        const val MAXIMUM_CONSECUTIVE_BACKEND_FAILURES = 3
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

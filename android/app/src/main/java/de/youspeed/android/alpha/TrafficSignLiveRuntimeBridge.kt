package de.youspeed.android.alpha

/**
 * Production seam between an Android live-frame backend and
 * the driving controller. Only finalized passages can mutate the speed state.
 * Accepted raw detections use a separate pictogram callback and cannot reach the speed resolver.
 */
class TrafficSignLiveRuntimeBridge<F : TrafficSignNormalizedFrameHandle>(
    controller: ConsumerSessionController,
    modelPack: TrafficSignModelPack,
    runtimeArtifact: TrafficSignArtifact,
    backend: TrafficSignRecognitionBackend<F>,
    conditionsSnapshot: () -> TrafficSignAnalysisConditions,
    monotonicClockNanos: () -> Long = System::nanoTime,
    onRuntimeUnavailable: (String, Long) -> Unit = controller::onTrafficSignRecognitionUnavailable,
    onContextMismatch: (Long) -> Unit = controller::onTrafficSignRecognitionContextMismatch,
    onInferenceDiagnostics: (TrafficSignOrchestrationOutput) -> Unit = controller::onTrafficSignInferenceDiagnostics,
    confirmationWindowMsOverride: Long? = null,
) : AutoCloseable {
    private val forwarder = TrafficSignFinalizedPassageForwarder(
        submitFinalizedPassage = controller::submitFinalizedTrafficSignPassage,
        submitDisplayObservation = controller::submitTrafficSignDisplayObservation,
        submitRecognitionEvent = controller::onTrafficSignRecognitionEvent,
        onRuntimeUnavailable = onRuntimeUnavailable,
        onContextMismatch = onContextMismatch,
        onInferenceDiagnostics = onInferenceDiagnostics,
    )
    private val orchestrator: TrafficSignRecognitionOrchestrator<F>

    init {
        val detectorArtifact = modelPack.androidArtifact(modelPack.detector)
        require(detectorArtifact != null) {
            "The live TSR bridge requires Android detector lineage"
        }
        require(runtimeArtifact.sha256 == detectorArtifact.sha256) {
            "The live TSR bridge runtime artifact must be the pack's Android detector"
        }
        if (modelPack.pipeline == TrafficSignPipeline.PROPOSAL_CLASSIFICATION) {
            require(modelPack.classifier?.let { modelPack.androidArtifact(it) } != null) {
                "A two-stage live TSR bridge requires Android classifier lineage"
            }
        }
        orchestrator = TrafficSignRecognitionOrchestrator(
            modelPack = modelPack,
            runtimeArtifact = runtimeArtifact,
            backend = backend,
            contextSnapshot = TrafficSignDetectionContextSnapshot(controller::currentTrafficSignDetectionContext),
            conditionsSnapshot = conditionsSnapshot,
            monotonicClockNanos = monotonicClockNanos,
            observer = forwarder,
            confirmationWindowMsOverride = confirmationWindowMsOverride,
        )
    }

    fun submit(frame: F): Boolean = orchestrator.submit(frame)

    override fun close() = orchestrator.close()
}

internal class TrafficSignFinalizedPassageForwarder(
    private val submitDisplayObservation: (TrafficSignDisplayObservation) -> Unit = {},
    private val submitRecognitionEvent: (TrafficSignRecognitionEvent, Long) -> Unit = { _, _ -> },
    private val onRuntimeUnavailable: (String, Long) -> Unit = { _, _ -> },
    private val onContextMismatch: (Long) -> Unit = {},
    private val onInferenceDiagnostics: (TrafficSignOrchestrationOutput) -> Unit = {},
    private val submitFinalizedPassage: (TrafficSignPassageEvent) -> Boolean,
) : TrafficSignRecognitionObserver {
    override fun onRecognition(output: TrafficSignOrchestrationOutput) {
        if (!output.contextIsCurrent) {
            onContextMismatch(output.contextGeneration)
        }
        if (output.terminalBackendFailure) {
            onRuntimeUnavailable(requireNotNull(output.backendFailureReason), output.contextGeneration)
        }
        // Primary speed delivery precedes annotations, secondary pictograms and
        // diagnostics. Only the finalized passage can change the speed limit.
        output.passageEvent?.let(submitFinalizedPassage)
        if (!output.terminalBackendFailure && output.backendFailureReason == null) {
            submitRecognitionEvent(output.event, output.contextGeneration)
        }
        output.displayObservation?.let(submitDisplayObservation)
        onInferenceDiagnostics(output)
    }

    override fun onSpeedOverrideChanged(current: TrafficSignSpeedOverride?) {
        // The resolver/controller is the sole authoritative speed source.
    }
}

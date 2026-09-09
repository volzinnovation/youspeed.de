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
) : AutoCloseable {
    private val forwarder = TrafficSignFinalizedPassageForwarder(
        submitFinalizedPassage = controller::submitFinalizedTrafficSignPassage,
        submitDisplayObservation = controller::submitTrafficSignDisplayObservation,
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
        )
    }

    fun submit(frame: F): Boolean = orchestrator.submit(frame)

    override fun close() = orchestrator.close()
}

internal class TrafficSignFinalizedPassageForwarder(
    private val submitDisplayObservation: (TrafficSignDisplayObservation) -> Unit = {},
    private val submitFinalizedPassage: (TrafficSignPassageEvent) -> Boolean,
) : TrafficSignRecognitionObserver {
    override fun onRecognition(output: TrafficSignOrchestrationOutput) {
        output.passageEvent?.let(submitFinalizedPassage)
        output.displayObservation?.let(submitDisplayObservation)
    }

    override fun onSpeedOverrideChanged(current: TrafficSignSpeedOverride?) {
        // The resolver/controller is the sole authoritative speed source.
    }
}

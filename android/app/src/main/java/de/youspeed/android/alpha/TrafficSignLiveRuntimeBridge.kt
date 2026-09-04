package de.youspeed.android.alpha

/**
 * Production seam between a future calibrated Android live-frame backend and
 * the driving controller. It deliberately forwards only finalized passage
 * events; provisional/raw outputs and the orchestrator's legacy numeric
 * projection cannot mutate driver-facing state through this adapter.
 */
class TrafficSignLiveRuntimeBridge<F : TrafficSignNormalizedFrameHandle>(
    controller: ConsumerSessionController,
    modelPack: TrafficSignModelPack,
    runtimeArtifact: TrafficSignArtifact,
    backend: TrafficSignRecognitionBackend<F>,
    conditionsSnapshot: () -> TrafficSignAnalysisConditions,
    monotonicClockNanos: () -> Long = System::nanoTime,
) : AutoCloseable {
    private val forwarder = TrafficSignFinalizedPassageForwarder(controller::submitFinalizedTrafficSignPassage)
    private val orchestrator: TrafficSignRecognitionOrchestrator<F>

    init {
        require(modelPack.calibration.calibrated &&
            modelPack.calibration.runtimeOutput == TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE
        ) { "The live TSR bridge requires a calibrated runtime-authoritative model pack" }
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
    private val submitFinalizedPassage: (TrafficSignPassageEvent) -> Boolean,
) : TrafficSignRecognitionObserver {
    override fun onRecognition(output: TrafficSignOrchestrationOutput) {
        output.passageEvent?.let(submitFinalizedPassage)
    }

    override fun onSpeedOverrideChanged(current: TrafficSignSpeedOverride?) {
        // The resolver/controller is the sole authoritative speed source.
    }
}

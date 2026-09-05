package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import java.util.Locale
import java.util.UUID

/**
 * Runtime-only view of the pack-v2 execution policy.
 *
 * M0 deliberately supports one value. A later production rollout must add a
 * separately reviewed policy implementation instead of reinterpreting a
 * shadow pack as actionable.
 */
enum class TrafficSignExecutionModeV2(val wireValue: String) {
    SHADOW("shadow"),
}

enum class TrafficSignEvidenceOriginV2(val wireValue: String) {
    RUNTIME_INFERENCE("runtime_inference"),
    REVIEWED_EXPECTATION("reviewed_expectation"),
}

enum class TrafficSignOverrideDispositionV2(val wireValue: String) {
    SHADOW_EVIDENCE_ONLY("shadow_evidence_only"),
}

enum class TrafficSignQADispositionV2(val wireValue: String) {
    EMIT("emit"),
}

enum class TrafficSignInputSourceV2(val wireValue: String) {
    LIVE_FRAME("live_frame"),
    CAMERA_STILL("camera_still"),
    DIAGNOSTIC_IMPORT("diagnostic_import"),
    PANORAMAX_REPLAY("panoramax_replay"),
}

enum class TrafficSignRuntimeArtifactFormatV2(val wireValue: String) {
    ONNX("onnx"),
    CORE_ML("coreml"),
    LITERT("litert"),
}

enum class TrafficSignAssociationPolicyV2(val wireValue: String) {
    STABLE_OBSERVATION_HINT_THEN_UNIQUE_SEMANTIC_ROAD_DIRECTION(
        "stable_observation_hint_then_unique_semantic_road_direction",
    ),
}

enum class TrafficSignPlateReadabilityV2(val wireValue: String) {
    READABLE("readable"),
    UNREADABLE("unreadable"),
}

enum class TrafficSignRestrictionTransitionV2(val wireValue: String) {
    NONE("none"),
    PRESERVED_UNREADABLE("preserved_unreadable"),
    UPGRADED_FROM_LATER_READABLE_EVIDENCE("upgraded_from_later_readable_evidence"),
}

enum class TrafficSignDiagnosticCaptureStatusV2(val wireValue: String) {
    NOT_REQUESTED("not_requested"),
    REQUESTED("requested"),
    PERSISTED("persisted"),
    FAILED("failed"),
}

enum class TrafficSignDiagnosticReasonV2(val wireValue: String) {
    SHADOW_CANDIDATE("shadow_candidate"),
    UNCERTAIN_PRIMARY("uncertain_primary"),
    UNREADABLE_SUPPLEMENTARY_PLATE("unreadable_supplementary_plate"),
    TEMPORAL_UPGRADE("temporal_upgrade"),
    MANUAL_QA("manual_qa"),
}

enum class TrafficSignPrimarySemanticKindV2(val wireValue: String) {
    MAXIMUM_SPEED("maximum_speed"),
    MAXIMUM_SPEED_END("maximum_speed_end"),
    ZONE_START("zone_start"),
    ZONE_END("zone_end"),
    RESTRICTION_END("restriction_end"),
    UNKNOWN("unknown"),
}

data class TrafficSignPrimarySemanticV2(
    val kind: TrafficSignPrimarySemanticKindV2,
    val value: Int?,
    val unit: String?,
) {
    init {
        require(value == null || value > 0) { "TSR semantic value must be positive" }
        require(unit == null || unit == "km/h" || unit == "mph") { "TSR semantic unit is invalid" }
        require(kind == TrafficSignPrimarySemanticKindV2.UNKNOWN || (value != null && unit != null)) {
            "A recognized TSR speed semantic requires value and unit"
        }
    }
}

data class TrafficSignRestrictionV2(
    val kind: TrafficSignRestrictionKind,
    val normalizedValue: String,
    val distanceM: Int? = null,
    val extentM: Int? = null,
    val rawText: String? = null,
    val countrySignCode: String? = null,
) {
    init {
        require(normalizedValue.isNotBlank()) { "TSR restriction value is required" }
        require(kind != TrafficSignRestrictionKind.DISTANCE || (distanceM != null && distanceM > 0)) {
            "A distance restriction requires a positive distance_m"
        }
        require(kind != TrafficSignRestrictionKind.EXTENT || (extentM != null && extentM > 0)) {
            "An extent restriction requires a positive extent_m"
        }
        require(kind == TrafficSignRestrictionKind.DISTANCE || distanceM == null) {
            "Only a distance restriction may carry distance_m"
        }
        require(kind == TrafficSignRestrictionKind.EXTENT || extentM == null) {
            "Only an extent restriction may carry extent_m"
        }
        require(rawText == null || rawText.isNotBlank()) { "TSR restriction text must not be blank" }
        require(countrySignCode == null || countrySignCode.isNotBlank()) {
            "TSR country sign code must not be blank"
        }
    }
}

data class TrafficSignShadowStageIdentityV2(
    val componentId: String,
    val artifactId: String,
    val artifactSha256: String,
    val artifactFormat: TrafficSignRuntimeArtifactFormatV2,
    val preprocessingVersion: String,
    val calibrationId: String,
    val calibrationPassed: Boolean,
) {
    init {
        require(componentId.isNotBlank()) { "TSR component ID is required" }
        require(artifactId.isNotBlank()) { "TSR artifact ID is required" }
        require(artifactSha256.matches(SHA256)) { "TSR artifact SHA-256 is invalid" }
        require(preprocessingVersion.isNotBlank()) { "TSR preprocessing identity is required" }
        require(calibrationId.isNotBlank()) { "TSR calibration identity is required" }
    }

    private companion object {
        val SHA256 = Regex("^[a-f0-9]{64}$")
    }
}

/** A validated, platform-selected projection of model-pack v2. */
data class TrafficSignShadowRuntimeConfigurationV2(
    val packId: String,
    val taxonomyVersion: String,
    val initialMode: TrafficSignExecutionModeV2,
    val overrideEligible: Boolean,
    val detector: TrafficSignShadowStageIdentityV2,
    val classifier: TrafficSignShadowStageIdentityV2,
    val classifierConfirmedThreshold: Double,
    val confirmationFrames: Int,
    val minimumTrackIou: Double,
    val temporalWindowMs: Long,
    val associationPolicy: TrafficSignAssociationPolicyV2,
    val stableObservationHintCanOverrideIou: Boolean,
    val fallbackRequiresUniqueCandidate: Boolean,
) {
    init {
        require(packId.isNotBlank()) { "TSR pack ID is required" }
        require(taxonomyVersion == "tsr-semantic-v2") { "Unsupported TSR v2 taxonomy" }
        require(initialMode == TrafficSignExecutionModeV2.SHADOW) { "M0 accepts shadow packs only" }
        require(!overrideEligible) { "M0 shadow packs cannot be override eligible" }
        require(detector.componentId != classifier.componentId) { "TSR stage component IDs must be distinct" }
        require(detector.artifactId != classifier.artifactId) { "TSR stage artifact IDs must be distinct" }
        require(detector.artifactSha256 != classifier.artifactSha256) { "TSR stage artifact hashes must be distinct" }
        require(detector.artifactFormat == classifier.artifactFormat) { "TSR mobile stage formats must match" }
        require(detector.artifactFormat != TrafficSignRuntimeArtifactFormatV2.ONNX) {
            "The on-device shadow runtime cannot execute ONNX artifacts"
        }
        require(classifierConfirmedThreshold.isFinite() && classifierConfirmedThreshold in 0.0..1.0) {
            "TSR classifier confirmation threshold is invalid"
        }
        require(confirmationFrames >= 2) { "TSR confirmation frame count is invalid" }
        require(minimumTrackIou.isFinite() && minimumTrackIou in 0.0..1.0) {
            "TSR temporal IoU threshold is invalid"
        }
        require(temporalWindowMs > 0L) { "TSR temporal window must be positive" }
        require(
            associationPolicy ==
                TrafficSignAssociationPolicyV2.STABLE_OBSERVATION_HINT_THEN_UNIQUE_SEMANTIC_ROAD_DIRECTION &&
                stableObservationHintCanOverrideIou &&
                fallbackRequiresUniqueCandidate,
        ) { "Unsupported TSR temporal association policy" }
    }
}

data class TrafficSignFrameV2(
    val frameId: String,
    val timestampUtc: Instant,
    val width: Int,
    val height: Int,
) {
    init {
        require(frameId.isNotBlank()) { "TSR frame ID is required" }
        require(width > 0 && height > 0) { "TSR frame dimensions must be positive" }
    }
}

data class TrafficSignStageScoreV2(
    val rawScore: Double,
    val calibratedConfidence: Double?,
) {
    init {
        require(rawScore.isFinite()) { "TSR raw stage score must be finite" }
        require(
            calibratedConfidence == null ||
                (calibratedConfidence.isFinite() && calibratedConfidence in 0.0..1.0),
        ) { "TSR calibrated stage confidence is invalid" }
    }
}

data class TrafficSignStageRunV2(
    val componentId: String,
    val artifactId: String,
    val artifactSha256: String,
    val artifactFormat: TrafficSignRuntimeArtifactFormatV2,
    val preprocessingVersion: String,
    val calibrationId: String,
    val invoked: Boolean,
    val latencyMs: Double,
) {
    init {
        require(latencyMs.isFinite() && latencyMs >= 0.0) { "TSR stage latency is invalid" }
        require(invoked || latencyMs == 0.0) { "A skipped TSR stage cannot report latency" }
    }
}

data class TrafficSignStageRunsV2(
    val detector: TrafficSignStageRunV2,
    val classifier: TrafficSignStageRunV2,
)

data class TrafficSignPrimaryEvidenceV2(
    val objectId: String,
    val boundingBox: NormalizedTrafficSignBoundingBox,
    val detectorScore: TrafficSignStageScoreV2,
    val classifierScore: TrafficSignStageScoreV2,
    val classId: String,
    val semantic: TrafficSignPrimarySemanticV2,
)

data class TrafficSignSupplementaryPlateEvidenceV2(
    val objectId: String,
    val boundingBox: NormalizedTrafficSignBoundingBox,
    val detectorScore: TrafficSignStageScoreV2,
    val classifierScore: TrafficSignStageScoreV2?,
    val classId: String?,
    val readability: TrafficSignPlateReadabilityV2,
    val restriction: TrafficSignRestrictionV2?,
) {
    init {
        if (readability == TrafficSignPlateReadabilityV2.UNREADABLE) {
            require((classifierScore == null || classifierScore.rawScore.isFinite()) && classId == null && restriction == null) {
                "An unreadable supplementary plate cannot carry classifier semantics"
            }
        } else {
            require(classifierScore != null && !classId.isNullOrBlank() && restriction != null) {
                "A readable supplementary plate requires calibrated classifier semantics"
            }
        }
    }
}

data class TrafficSignTemporalEvidenceV2(
    val evidenceFrameCount: Int,
    val priorEventId: String?,
    val restrictionTransition: TrafficSignRestrictionTransitionV2,
) {
    init {
        require(evidenceFrameCount > 0) { "TSR temporal evidence count must be positive" }
        require(priorEventId == null || priorEventId.isNotBlank()) {
            "TSR prior event ID must not be blank"
        }
        require(
            restrictionTransition == TrafficSignRestrictionTransitionV2.NONE || priorEventId != null,
        ) { "A TSR restriction transition requires prior temporal evidence" }
    }
}

data class TrafficSignAssemblyV2(
    val assemblyId: String,
    val physicalSignTrackId: String,
    val primary: TrafficSignPrimaryEvidenceV2,
    val supplementaryPlates: List<TrafficSignSupplementaryPlateEvidenceV2>,
    val conditionState: TrafficSignConditionState,
    val temporalEvidence: TrafficSignTemporalEvidenceV2,
)

data class TrafficSignDiagnosticCaptureV2(
    val status: TrafficSignDiagnosticCaptureStatusV2,
    val reasons: List<TrafficSignDiagnosticReasonV2>,
    val captureId: String?,
) {
    init {
        require(reasons.distinct().size == reasons.size) { "TSR diagnostic reasons must be unique" }
        require(captureId == null || captureId.isNotBlank()) { "TSR diagnostic capture ID must not be blank" }
        require(status == TrafficSignDiagnosticCaptureStatusV2.PERSISTED || captureId == null) {
            "Only a persisted diagnostic capture may expose a capture ID"
        }
        require(status != TrafficSignDiagnosticCaptureStatusV2.PERSISTED || captureId != null) {
            "A persisted diagnostic capture requires a capture ID"
        }
    }
}

data class TrafficSignRecognitionEventV2(
    val schemaVersion: Int,
    val eventId: String,
    val packId: String,
    val taxonomyVersion: String,
    val evidenceOrigin: TrafficSignEvidenceOriginV2,
    val executionMode: TrafficSignExecutionModeV2,
    val overrideEligible: Boolean,
    val overrideDisposition: TrafficSignOverrideDispositionV2,
    val qaDisposition: TrafficSignQADispositionV2,
    val source: TrafficSignInputSourceV2,
    val frame: TrafficSignFrameV2,
    val stageRuns: TrafficSignStageRunsV2,
    val state: TrafficSignRecognitionState,
    val assemblies: List<TrafficSignAssemblyV2>,
    val roadContext: TrafficSignDetectionContext?,
    val diagnosticCapture: TrafficSignDiagnosticCaptureV2,
    val thermalState: String? = null,
) {
    init {
        require(schemaVersion == 2) { "Unsupported TSR event schema" }
        require(eventId.isNotBlank()) { "TSR event ID is required" }
        require(evidenceOrigin == TrafficSignEvidenceOriginV2.RUNTIME_INFERENCE) {
            "The on-device TSR runtime emits runtime inference evidence only"
        }
        require(executionMode == TrafficSignExecutionModeV2.SHADOW) { "M0 emits shadow events only" }
        require(!overrideEligible) { "M0 events cannot be override eligible" }
        require(overrideDisposition == TrafficSignOverrideDispositionV2.SHADOW_EVIDENCE_ONLY) {
            "M0 events must remain shadow evidence"
        }
    }
}

data class TrafficSignTwoStagePrimaryObservationV2(
    val objectId: String,
    val classId: String,
    val semantic: TrafficSignPrimarySemanticV2,
    val boundingBox: NormalizedTrafficSignBoundingBox,
    val detectorScore: Double,
    val detectorCalibratedConfidence: Double?,
    val classifierRawScore: Double?,
    val classifierCalibratedConfidence: Double?,
    val classifierThreshold: Double,
) {
    init {
        require(objectId.isNotBlank() && classId.isNotBlank()) { "TSR primary classification is required" }
        require(detectorScore.isFinite() && detectorScore in 0.0..1.0) { "TSR detector score is invalid" }
        require(
            detectorCalibratedConfidence == null ||
                (detectorCalibratedConfidence.isFinite() && detectorCalibratedConfidence in 0.0..1.0),
        ) { "TSR calibrated detector confidence is invalid" }
        require(classifierRawScore != null && classifierRawScore.isFinite()) {
            "TSR primary classifier score is required"
        }
        require(
            classifierCalibratedConfidence == null ||
                (classifierCalibratedConfidence.isFinite() && classifierCalibratedConfidence in 0.0..1.0),
        ) { "TSR calibrated classifier confidence is invalid" }
        require(classifierThreshold.isFinite() && classifierThreshold in 0.0..1.0) {
            "TSR classifier threshold is invalid"
        }
    }
}

data class TrafficSignTwoStagePlateObservationV2(
    val objectId: String,
    val classId: String?,
    val boundingBox: NormalizedTrafficSignBoundingBox,
    val detectorScore: Double,
    val detectorCalibratedConfidence: Double?,
    val classifierRawScore: Double?,
    val classifierCalibratedConfidence: Double?,
    val classifierThreshold: Double,
    val readability: TrafficSignPlateReadabilityV2,
    val restriction: TrafficSignRestrictionV2?,
) {
    init {
        require(objectId.isNotBlank()) { "TSR supplementary object ID is required" }
        require(detectorScore.isFinite() && detectorScore in 0.0..1.0) { "TSR detector score is invalid" }
        require(
            detectorCalibratedConfidence == null ||
                (detectorCalibratedConfidence.isFinite() && detectorCalibratedConfidence in 0.0..1.0),
        ) { "TSR calibrated detector confidence is invalid" }
        require(classifierThreshold.isFinite() && classifierThreshold in 0.0..1.0) {
            "TSR classifier threshold is invalid"
        }
        require(readability == TrafficSignPlateReadabilityV2.READABLE || restriction == null) {
            "An unreadable supplementary observation cannot carry a restriction"
        }
    }
}

data class TrafficSignTwoStageAssemblyObservationV2(
    val assemblyId: String,
    val stableObservationHint: String? = null,
    val primary: TrafficSignTwoStagePrimaryObservationV2,
    val supplementaryPlates: List<TrafficSignTwoStagePlateObservationV2>,
) {
    init {
        require(assemblyId.isNotBlank()) { "TSR assembly ID is required" }
        require(stableObservationHint == null || stableObservationHint.isNotBlank()) {
            "TSR stable observation hint must not be blank"
        }
    }
}

data class TrafficSignShadowFrameInputV2(
    val eventId: String,
    val source: TrafficSignInputSourceV2,
    val frame: TrafficSignFrameV2,
    val roadContext: TrafficSignDetectionContext,
    val requestedState: TrafficSignRecognitionState,
    val detectorLatencyMs: Double,
    val classifierInvoked: Boolean,
    val classifierLatencyMs: Double,
    val assemblies: List<TrafficSignTwoStageAssemblyObservationV2>,
    val diagnosticReasons: List<TrafficSignDiagnosticReasonV2> = emptyList(),
) {
    init {
        require(eventId.isNotBlank()) { "TSR event ID is required" }
        require(source != TrafficSignInputSourceV2.DIAGNOSTIC_IMPORT || !roadContext.wayId.isNullOrBlank()) {
            "Imported TSR evidence still requires its captured road context"
        }
        require(detectorLatencyMs.isFinite() && detectorLatencyMs >= 0.0) { "TSR detector latency is invalid" }
        require(classifierLatencyMs.isFinite() && classifierLatencyMs >= 0.0) { "TSR classifier latency is invalid" }
        require(classifierInvoked || classifierLatencyMs == 0.0) { "A skipped classifier cannot report latency" }
        require(assemblies.isEmpty() || classifierInvoked) { "Two-stage assemblies require classifier execution" }
        require(diagnosticReasons.distinct().size == diagnosticReasons.size) {
            "TSR diagnostic reasons must be unique"
        }
    }
}

data class TrafficSignDiagnosticCaptureRequestV2(
    val eventId: String,
    val frame: TrafficSignFrameV2,
    val roadContext: TrafficSignDetectionContext,
    val reasons: List<TrafficSignDiagnosticReasonV2>,
)

data class TrafficSignDiagnosticCaptureOutcomeV2(
    val status: TrafficSignDiagnosticCaptureStatusV2,
    val captureId: String? = null,
) {
    init {
        require(status != TrafficSignDiagnosticCaptureStatusV2.NOT_REQUESTED) {
            "An invoked diagnostic sink cannot return not_requested"
        }
        require(status == TrafficSignDiagnosticCaptureStatusV2.PERSISTED || captureId == null) {
            "Only a persisted diagnostic capture may expose a capture ID"
        }
        require(status != TrafficSignDiagnosticCaptureStatusV2.PERSISTED || !captureId.isNullOrBlank()) {
            "A persisted diagnostic capture requires a capture ID"
        }
    }
}

fun interface TrafficSignDiagnosticCaptureSinkV2 {
    fun requestCapture(request: TrafficSignDiagnosticCaptureRequestV2): TrafficSignDiagnosticCaptureOutcomeV2
}

fun interface TrafficSignQAEventSinkV2 {
    fun emit(event: TrafficSignRecognitionEventV2)
}

/**
 * Pure M0 coordinator around a future detector/classifier backend.
 *
 * It binds stage identities from the validated pack, retains primary-sign QA,
 * emits events, and optionally asks a separate consent-aware sink for a
 * diagnostic capture. Supplementary signs are intentionally excluded from
 * the on-device lane. It has no speed-source mutation API.
 */
class TrafficSignShadowRuntimeV2(
    private val configuration: TrafficSignShadowRuntimeConfigurationV2,
    private val diagnosticCaptureSink: TrafficSignDiagnosticCaptureSinkV2? = null,
    private val qaEventSink: TrafficSignQAEventSinkV2? = null,
) {
    private val tracks = mutableListOf<Track>()
    private var lastFrameTimestamp: Instant? = null

    @Synchronized
    fun process(input: TrafficSignShadowFrameInputV2): TrafficSignRecognitionEventV2 {
        val priorTimestamp = lastFrameTimestamp
        require(priorTimestamp == null || !input.frame.timestampUtc.isBefore(priorTimestamp)) {
            "TSR shadow frames must be chronological"
        }
        lastFrameTimestamp = input.frame.timestampUtc
        expireTracks(input.frame.timestampUtc)

        val usedTrackIds = mutableSetOf<String>()
        val assemblies = input.assemblies.map { observation ->
            normalizeAssembly(
                observation = observation,
                eventId = input.eventId,
                observedAt = input.frame.timestampUtc,
                roadContext = input.roadContext,
                usedTrackIds = usedTrackIds,
            )
        }
        val state = recognitionState(input, assemblies)
        val stageRuns = TrafficSignStageRunsV2(
            detector = configuration.detector.run(invoked = true, latencyMs = input.detectorLatencyMs),
            classifier = configuration.classifier.run(
                invoked = input.classifierInvoked,
                latencyMs = input.classifierLatencyMs,
            ),
        )
        val reasons = diagnosticReasons(input, state)
        val capture = requestDiagnosticCapture(input, reasons)
        val event = TrafficSignRecognitionEventV2(
            schemaVersion = 2,
            eventId = input.eventId,
            packId = configuration.packId,
            taxonomyVersion = configuration.taxonomyVersion,
            evidenceOrigin = TrafficSignEvidenceOriginV2.RUNTIME_INFERENCE,
            executionMode = TrafficSignExecutionModeV2.SHADOW,
            overrideEligible = false,
            overrideDisposition = TrafficSignOverrideDispositionV2.SHADOW_EVIDENCE_ONLY,
            qaDisposition = TrafficSignQADispositionV2.EMIT,
            source = input.source,
            frame = input.frame,
            stageRuns = stageRuns,
            state = state,
            assemblies = assemblies,
            roadContext = input.roadContext,
            diagnosticCapture = capture,
        )
        runCatching { qaEventSink?.emit(event) }
        return event
    }

    @Synchronized
    fun reset() {
        tracks.clear()
        lastFrameTimestamp = null
    }

    private fun normalizeAssembly(
        observation: TrafficSignTwoStageAssemblyObservationV2,
        eventId: String,
        observedAt: Instant,
        roadContext: TrafficSignDetectionContext,
        usedTrackIds: MutableSet<String>,
    ): TrafficSignAssemblyV2 {
        val primary = observation.primary.toEvidence()
        val conditionState = TrafficSignConditionState.NONE
        val roadKey = RoadKey(roadContext)
        val candidates = tracks
            .asSequence()
            .filter { it.id !in usedTrackIds }
            .filter { it.roadKey == roadKey && it.semantic == primary.semantic }
            .toList()
        val track = candidates.maxByOrNull { it.lastObservedAt }
            ?: Track(
                id = UUID.randomUUID().toString().lowercase(Locale.US),
                roadKey = roadKey,
                semantic = primary.semantic,
                lastObservedAt = observedAt,
                evidenceFrameCount = 0,
                lastEventId = null,
            ).also(tracks::add)
        usedTrackIds += track.id

        val temporalEvidence = TrafficSignTemporalEvidenceV2(
            evidenceFrameCount = track.evidenceFrameCount + 1,
            priorEventId = track.lastEventId,
            restrictionTransition = TrafficSignRestrictionTransitionV2.NONE,
        )
        track.lastObservedAt = observedAt
        track.evidenceFrameCount = temporalEvidence.evidenceFrameCount
        track.lastEventId = eventId

        return TrafficSignAssemblyV2(
            assemblyId = observation.assemblyId,
            physicalSignTrackId = track.id,
            primary = primary,
            supplementaryPlates = emptyList(),
            conditionState = conditionState,
            temporalEvidence = temporalEvidence,
        )
    }

    private fun diagnosticReasons(
        input: TrafficSignShadowFrameInputV2,
        state: TrafficSignRecognitionState,
    ): List<TrafficSignDiagnosticReasonV2> = buildList {
        addAll(input.diagnosticReasons)
        if (state == TrafficSignRecognitionState.CONFIRMED) {
            add(TrafficSignDiagnosticReasonV2.SHADOW_CANDIDATE)
        }
    }.distinct()

    private fun recognitionState(
        input: TrafficSignShadowFrameInputV2,
        assemblies: List<TrafficSignAssemblyV2>,
    ): TrafficSignRecognitionState {
        if (assemblies.isEmpty()) {
            return if (input.requestedState == TrafficSignRecognitionState.UNAVAILABLE) {
                TrafficSignRecognitionState.UNAVAILABLE
            } else {
                TrafficSignRecognitionState.NO_RECOGNITION
            }
        }
        if (
            input.requestedState == TrafficSignRecognitionState.UNKNOWN
        ) {
            return TrafficSignRecognitionState.UNKNOWN
        }
        val hasQualifiedPrimary = assemblies.any {
            (it.primary.classifierScore.calibratedConfidence ?: it.primary.classifierScore.rawScore) >=
                configuration.classifierConfirmedThreshold
        }
        if (!hasQualifiedPrimary) return TrafficSignRecognitionState.UNKNOWN
        val evidenceCount = assemblies.maxOf { it.temporalEvidence.evidenceFrameCount }
        return if (evidenceCount >= configuration.confirmationFrames) {
            TrafficSignRecognitionState.CONFIRMED
        } else {
            TrafficSignRecognitionState.PROVISIONAL
        }
    }

    private fun requestDiagnosticCapture(
        input: TrafficSignShadowFrameInputV2,
        reasons: List<TrafficSignDiagnosticReasonV2>,
    ): TrafficSignDiagnosticCaptureV2 {
        if (reasons.isEmpty()) {
            return TrafficSignDiagnosticCaptureV2(
                status = TrafficSignDiagnosticCaptureStatusV2.NOT_REQUESTED,
                reasons = emptyList(),
                captureId = null,
            )
        }
        val sink = diagnosticCaptureSink
            ?: return TrafficSignDiagnosticCaptureV2(
                status = TrafficSignDiagnosticCaptureStatusV2.NOT_REQUESTED,
                reasons = reasons,
                captureId = null,
            )
        val outcome = runCatching {
            sink.requestCapture(
                TrafficSignDiagnosticCaptureRequestV2(
                    eventId = input.eventId,
                    frame = input.frame,
                    roadContext = input.roadContext,
                    reasons = reasons,
                ),
            )
        }.getOrElse {
            TrafficSignDiagnosticCaptureOutcomeV2(
                status = TrafficSignDiagnosticCaptureStatusV2.FAILED,
            )
        }
        return TrafficSignDiagnosticCaptureV2(
            status = outcome.status,
            reasons = reasons,
            captureId = outcome.captureId,
        )
    }

    private fun expireTracks(now: Instant) {
        tracks.removeAll {
            Duration.between(it.lastObservedAt, now).toMillis() > configuration.temporalWindowMs
        }
    }

    private data class RoadKey(
        val wayId: String?,
        val direction: TrafficSignTravelDirection,
        val sourceSignature: TrafficSignRuntimeSourceSignature,
    ) {
        constructor(context: TrafficSignDetectionContext) : this(
            wayId = context.wayId,
            direction = context.travelDirection,
            sourceSignature = context.sourceSignature,
        )
    }

    private data class Track(
        val id: String,
        val roadKey: RoadKey,
        val semantic: TrafficSignPrimarySemanticV2,
        var lastObservedAt: Instant,
        var evidenceFrameCount: Int,
        var lastEventId: String?,
    )

}

private fun TrafficSignShadowStageIdentityV2.run(
    invoked: Boolean,
    latencyMs: Double,
) = TrafficSignStageRunV2(
    componentId = componentId,
    artifactId = artifactId,
    artifactSha256 = artifactSha256,
    artifactFormat = artifactFormat,
    preprocessingVersion = preprocessingVersion,
    calibrationId = calibrationId,
    invoked = invoked,
    latencyMs = latencyMs,
)

private fun TrafficSignTwoStagePrimaryObservationV2.toEvidence() = TrafficSignPrimaryEvidenceV2(
    objectId = objectId,
    boundingBox = boundingBox,
    detectorScore = TrafficSignStageScoreV2(
        rawScore = detectorScore,
        calibratedConfidence = detectorCalibratedConfidence,
    ),
    classifierScore = TrafficSignStageScoreV2(
        rawScore = requireNotNull(classifierRawScore),
        calibratedConfidence = classifierCalibratedConfidence,
    ),
    classId = classId,
    semantic = semantic,
)

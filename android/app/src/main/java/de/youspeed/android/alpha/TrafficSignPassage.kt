package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt

/** Linearizes generation invalidation with durable CV observation writes. */
internal class TrafficSignWriteGate(initialGeneration: Long = 0L) {
    private val lock = Any()
    private var generation = initialGeneration
    private var writesPermitted = false

    fun get(): Long = synchronized(lock) { generation }

    fun snapshot(): Pair<Long, Boolean> = synchronized(lock) { generation to writesPermitted }

    fun incrementAndGet(permitWrites: Boolean): Long = synchronized(lock) {
        generation += 1L
        writesPermitted = permitWrites
        generation
    }

    fun <T> withPermit(expectedGeneration: Long, block: () -> T): T? = synchronized(lock) {
        if (!writesPermitted || expectedGeneration != generation) null else block()
    }
}

internal object TrafficSignBundleContextPolicy {
    fun enteredCity(previousInsideCity: Boolean?, currentInsideCity: Boolean?): Boolean =
        previousInsideCity == false && currentInsideCity == true
}

/** A structural sign operation. Display values are deliberately kept separate. */
enum class TrafficSignActionKind(val wireValue: String) {
    POSTED_MAXIMUM("posted_maximum"),
    MAXIMUM_SPEED_END("maximum_speed_end"),
    ALL_RESTRICTIONS_END("all_restrictions_end"),
    ZONE_START("zone_start"),
    ZONE_END("zone_end"),
    CITY_ENTRY("city_entry"),
    CITY_EXIT("city_exit"),
    PEDESTRIAN_ZONE_START("pedestrian_zone_start"),
    PEDESTRIAN_ZONE_END("pedestrian_zone_end"),
    MOTORWAY_EXIT("motorway_exit"),
    MOTORROAD_EXIT("motorroad_exit"),
    TEMPORARY_MAXIMUM("temporary_maximum"),
    NON_SPEED_RESTRICTION_END("non_speed_restriction_end"),
    UNKNOWN("unknown"),
}

private val SPEED_END_ACTION_KINDS = setOf(
    TrafficSignActionKind.MAXIMUM_SPEED_END,
    TrafficSignActionKind.ALL_RESTRICTIONS_END,
    TrafficSignActionKind.ZONE_END,
    TrafficSignActionKind.CITY_EXIT,
    TrafficSignActionKind.PEDESTRIAN_ZONE_END,
    TrafficSignActionKind.MOTORWAY_EXIT,
    TrafficSignActionKind.MOTORROAD_EXIT,
)

data class TrafficSignAction(
    val kind: TrafficSignActionKind,
    val valueKmh: Int? = null,
    val countryCode: String? = null,
    val conditionState: TrafficSignConditionState = TrafficSignConditionState.NONE,
    val restrictions: List<TrafficSignRestriction> = emptyList(),
) {
    init {
        require(valueKmh == null || isSharedTrafficSignSpeedKmh(valueKmh)) {
            "Traffic-sign action speed must be in $MIN_SHARED_TRAFFIC_SIGN_SPEED_KMH..$MAX_SHARED_TRAFFIC_SIGN_SPEED_KMH km/h"
        }
    }

    val isConditional: Boolean
        get() = conditionState != TrafficSignConditionState.NONE || restrictions.isNotEmpty()

    val isPermanentRuntimeAction: Boolean
        get() = !isConditional && kind != TrafficSignActionKind.TEMPORARY_MAXIMUM
}

enum class TrafficSignResolvedLimitKind(val wireValue: String) {
    NUMERIC("numeric"),
    WALK("walk"),
    UNLIMITED("unlimited"),
    UNKNOWN("unknown"),
}

data class TrafficSignResolvedLimit(
    val kind: TrafficSignResolvedLimitKind,
    val speedKmh: Int? = null,
) {
    init {
        require(kind == TrafficSignResolvedLimitKind.NUMERIC || speedKmh == null) {
            "Only numeric traffic-sign resolutions may carry speed_kmh"
        }
        require(kind != TrafficSignResolvedLimitKind.NUMERIC || (speedKmh != null && speedKmh > 0)) {
            "A numeric traffic-sign resolution requires a positive speed"
        }
    }

    val maxspeedValue: String?
        get() = when (kind) {
            TrafficSignResolvedLimitKind.NUMERIC -> speedKmh?.toString()
            TrafficSignResolvedLimitKind.WALK -> "walk"
            TrafficSignResolvedLimitKind.UNLIMITED -> "none"
            TrafficSignResolvedLimitKind.UNKNOWN -> null
        }
}

data class TrafficSignPassageFrameEvidence(
    val frameId: String,
    val timestampUtc: Instant,
    val rawScore: Double,
    val calibratedConfidence: Double?,
    val accumulatedSupport: Double,
    val boundingBox: NormalizedTrafficSignBoundingBox,
    val proposalRawScore: Double? = null,
    val proposalCalibratedConfidence: Double? = null,
    val classifierRawScore: Double? = null,
    val classifierCalibratedConfidence: Double? = null,
    val assemblyConfidence: Double? = null,
    val outcome: String = "seen",
    val analysisEligible: Boolean = true,
)

data class TrafficSignPassageLossEvidence(
    val frameId: String,
    val timestampUtc: Instant,
    val strongPassGeometry: Boolean,
    val outcome: String = "analyzed_missing",
    val analysisEligible: Boolean = true,
)

data class TrafficSignModelComponentLineage(
    val role: String,
    val artifactSha256: String,
    val preprocessingVersion: String,
    val calibrationId: String,
) {
    init {
        require(role in setOf("proposal_detector", "semantic_classifier", "direct_detector"))
        require(Regex("^[a-f0-9]{64}$").matches(artifactSha256))
        require(preprocessingVersion.isNotBlank())
        require(calibrationId.isNotBlank())
    }
}

data class TrafficSignPassageBoundary(
    val timestampUtc: Instant,
    val context: TrafficSignDetectionContext?,
    val strongPassGeometry: Boolean = false,
)

data class TrafficSignPassageEvent(
    val schemaVersion: Int = 1,
    val finalizedEventId: String,
    val driveSessionId: String,
    val generation: Long,
    val packId: String,
    val artifactSha256: String,
    val preprocessingVersion: String,
    val calibrationId: String,
    val componentRole: String,
    val modelComponents: List<TrafficSignModelComponentLineage>,
    val physicalTrackId: String,
    val assemblyId: String?,
    val assemblyIds: List<String>,
    val action: TrafficSignAction,
    val resolution: TrafficSignResolvedLimit,
    val firstSeenAtUtc: Instant,
    val lastSeenAtUtc: Instant,
    val firstSeenContext: TrafficSignDetectionContext?,
    val lastSeenContext: TrafficSignDetectionContext?,
    val passageBoundary: TrafficSignPassageBoundary,
    val activationContext: TrafficSignDetectionContext?,
    val activationAtUtc: Instant = passageBoundary.timestampUtc,
    val pendingRematchDistanceM: Double = 0.0,
    val initialRouteRelationGroupIds: Set<Long>,
    val eligibleRouteRelationGroupIds: Set<Long>,
    val sourceRelationIds: Set<Long>,
    val evidence: List<TrafficSignPassageFrameEvidence>,
    val lossEvidence: List<TrafficSignPassageLossEvidence>,
    val framesSeen: Int,
    val finalConfidence: Double,
    val finalAccumulatedSupport: Double,
    val peakConsecutiveFramesSeen: Int,
    val lossReason: String,
    val negativeFramesToCommit: Int,
    val overrideEligible: Boolean,
) {
    init {
        require(schemaVersion == 1) { "Unsupported traffic-sign passage schema" }
        require(finalizedEventId.isNotBlank()) { "Finalized event ID is required" }
        require(driveSessionId.isNotBlank()) { "Drive session ID is required" }
        require(generation >= 0L) { "TSR generation must not be negative" }
        require(physicalTrackId.isNotBlank()) { "Physical track ID is required" }
        require(calibrationId.isNotBlank()) { "Calibration ID is required" }
        require(componentRole in setOf("proposal_detector", "semantic_classifier", "direct_detector")) {
            "Unsupported model component role"
        }
        require(modelComponents.isNotEmpty()) { "At least one model component lineage is required" }
        require(modelComponents.map { it.role }.distinct().size == modelComponents.size) {
            "Model component roles must be unique"
        }
        require(assemblyIds.isNotEmpty() && assemblyIds.none(String::isBlank))
        require(assemblyIds.distinct().size == assemblyIds.size)
        require(evidence.isNotEmpty()) { "A passage requires positive-frame evidence" }
        require(lossEvidence.isNotEmpty() && lossEvidence.all { it.analysisEligible && it.outcome == "analyzed_missing" }) {
            "A passage requires qualified missing-frame evidence"
        }
        require(eligibleRouteRelationGroupIds.none { it <= 0L })
        require(initialRouteRelationGroupIds.none { it <= 0L })
        require(sourceRelationIds.none { it <= 0L })
        require(pendingRematchDistanceM.isFinite() && pendingRematchDistanceM >= 0.0)
        require(finalConfidence.isFinite() && finalConfidence in 0.0..1.0) {
            "Final passage confidence is invalid"
        }
        require(finalAccumulatedSupport.isFinite() && finalAccumulatedSupport in 0.0..1.0) {
            "Final passage accumulated support is invalid"
        }
        require(negativeFramesToCommit > 0) { "Loss debounce must be positive" }
        require(framesSeen >= evidence.size && framesSeen > 0)
        require(peakConsecutiveFramesSeen in 1..framesSeen)
    }
}

data class TrafficSignPassageFinalizerConfiguration(
    val repeatedTrackNegativeFrames: Int = 2,
    val strongPassGeometryNegativeFrames: Int = 1,
    val singleFrameNegativeFrames: Int = 3,
    val singleFrameArmThreshold: Double = 0.94,
    val maximumEvidenceFrames: Int = 16,
    val physicalTrackSuppressionWindow: Duration = Duration.ofSeconds(12),
    val physicalTrackSuppressionDistanceM: Double = 45.0,
) {
    init {
        require(repeatedTrackNegativeFrames > 0)
        require(strongPassGeometryNegativeFrames > 0)
        require(singleFrameNegativeFrames > repeatedTrackNegativeFrames)
        require(singleFrameArmThreshold in 0.0..1.0)
        require(maximumEvidenceFrames > 0)
        require(!physicalTrackSuppressionWindow.isNegative && !physicalTrackSuppressionWindow.isZero)
        require(physicalTrackSuppressionDistanceM.isFinite() && physicalTrackSuppressionDistanceM > 0.0)
    }
}

/**
 * Turns provisional per-frame recognition into one passage event. Only a
 * successfully analyzed frame can provide negative evidence; lifecycle gaps,
 * throttling and backend failures must call this with [qualifiedAnalyzedFrame]
 * set to false.
 */
class TrafficSignPassageFinalizer(
    private val configuration: TrafficSignPassageFinalizerConfiguration = TrafficSignPassageFinalizerConfiguration(),
) {
    private var generation: Long? = null
    private var track: Track? = null
    private var queuedTrack: Track? = null
    private var lastCommittedPhysicalSign: CommittedPhysicalSign? = null

    fun observe(
        event: TrafficSignRecognitionEvent,
        fusedScore: Double?,
        contextGeneration: Long,
        qualifiedAnalyzedFrame: Boolean,
        overrideEligible: Boolean,
        strongPassGeometry: Boolean = false,
    ): TrafficSignPassageEvent? {
        require(contextGeneration >= 0L)
        if (generation != contextGeneration) {
            reset(contextGeneration)
        }
        expireSuppression(event.frameTimestampUtc)

        if (event.candidate?.semantic?.value?.let(::isSharedTrafficSignSpeedKmh) == false) return null
        val hardNegativeCandidate = event.candidate?.toAction(event.roadContext?.countryCode)?.kind in setOf(
            TrafficSignActionKind.NON_SPEED_RESTRICTION_END,
            TrafficSignActionKind.UNKNOWN,
        )
        val candidate = event.candidate?.takeUnless { hardNegativeCandidate }
        if (hardNegativeCandidate) return null
        if (overrideEligible && qualifiedAnalyzedFrame && event.source == TrafficSignInputSource.LIVE_FRAME &&
            !event.frameId.isNullOrBlank() && !event.driveSessionId.isNullOrBlank() &&
            candidate != null && event.state in setOf(
                TrafficSignRecognitionState.PROVISIONAL,
                TrafficSignRecognitionState.CONFIRMED,
            )
        ) {
            val current = track
            if (qualifiedAnalyzedFrame && current != null && !current.isCompatibleWith(event, candidate) && current.armed) {
                queuedTrack = updateVisibleTrack(queuedTrack, event, candidate, fusedScore, overrideEligible)
                val committed = observeMissing(event, current, strongPassGeometry)
                if (committed != null) {
                    track = queuedTrack
                    queuedTrack = null
                    return committed
                }
                return null
            }
            return observeVisible(event, candidate, fusedScore, overrideEligible)
        }
        if (!overrideEligible || !qualifiedAnalyzedFrame || event.state != TrafficSignRecognitionState.NO_RECOGNITION) {
            return null
        }
        return observeMissing(event, track ?: return null, strongPassGeometry)
    }

    fun reset(nextGeneration: Long? = null) {
        generation = nextGeneration
        track = null
        queuedTrack = null
        lastCommittedPhysicalSign = null
    }

    fun hasActiveTrack(): Boolean = track != null

    /** Immutable route scope owned by the currently active physical sign. */
    internal fun activeTrackRouteScope(): TrafficSignActiveTrackRouteScope? = track?.let { current ->
        TrafficSignActiveTrackRouteScope(
            physicalTrackId = current.id,
            initialRouteRelationGroupIds = current.initialRouteRelationGroupIds.toSet(),
            eligibleRouteRelationGroupIds = current.eligibleRouteRelationGroupIds.toSet(),
            sourceRelationIds = current.sourceRelationIds.toSet(),
        )
    }

    /**
     * Reconciles active and queued signs independently against a stabilized
     * navigation context. A transient no-match/unstable match is neutral; the
     * first later stable match must still belong to each sign's frozen scope.
     */
    internal fun reconcileRoadContext(context: TrafficSignDetectionContext): TrafficSignTrackScopeReconciliation {
        if (context.wayId.isNullOrBlank() || !context.matchedWayStable) {
            return TrafficSignTrackScopeReconciliation(activeTrackRouteScope(), trackSetChanged = false)
        }
        val activeBefore = track
        val queuedBefore = queuedTrack
        val retainedActive = activeBefore?.takeIf { it.reconcileRouteContext(context) }
        val retainedQueued = queuedBefore?.takeIf { it.reconcileRouteContext(context) }
        track = retainedActive ?: retainedQueued
        queuedTrack = if (retainedActive != null) retainedQueued else null
        val changed = track !== activeBefore || queuedTrack !== queuedBefore
        return TrafficSignTrackScopeReconciliation(activeTrackRouteScope(), trackSetChanged = changed)
    }

    /** True until a track acquired during a map-matching gap sees its first real way. */
    fun activeTrackAwaitsMatchedRecognitionOrigin(): Boolean =
        track?.let { it.firstSeenContext?.wayId.isNullOrBlank() } == true

    private fun observeVisible(
        event: TrafficSignRecognitionEvent,
        candidate: TrafficSignCandidate,
        fusedScore: Double?,
        overrideEligible: Boolean,
    ): TrafficSignPassageEvent? {
        if (candidate.trackId == null) return null
        if (isRecentlyCommittedPhysicalSign(candidate, event.roadContext, event.frameTimestampUtc)) return null
        val existing = track
        val compatible = existing?.isCompatibleWith(event, candidate) == true
        val current = updateVisibleTrack(existing.takeIf { compatible }, event, candidate, fusedScore, overrideEligible)
            ?: return null
        track = current
        queuedTrack = null
        return null
    }

    private fun updateVisibleTrack(
        existing: Track?,
        event: TrafficSignRecognitionEvent,
        candidate: TrafficSignCandidate,
        fusedScore: Double?,
        overrideEligible: Boolean,
    ): Track? {
        val trackId = candidate.trackId ?: return null
        val calibrationId = event.calibrationId?.takeIf(String::isNotBlank) ?: return null
        val componentRole = event.componentRole?.takeIf {
            it in setOf("proposal_detector", "semantic_classifier", "direct_detector")
        } ?: return null
        val modelComponents = event.modelComponents.takeIf { components ->
            components.isNotEmpty() &&
                components.map(TrafficSignModelComponentLineage::role).distinct().size == components.size &&
                components.any { component ->
                    component.role == componentRole &&
                        component.artifactSha256 == event.artifactSha256 &&
                        component.preprocessingVersion == event.preprocessingVersion &&
                        component.calibrationId == calibrationId
                }
        } ?: return null
        val confidence = candidate.calibratedConfidence ?: fusedScore ?: candidate.rawScore
        if (!confidence.isFinite() || confidence !in 0.0..1.0) return null
        val current = existing?.takeIf { it.id == trackId && it.candidate.semantic == candidate.semantic } ?: Track(
            id = trackId,
            candidate = candidate,
            packId = event.packId,
            artifactSha256 = event.artifactSha256,
            preprocessingVersion = event.preprocessingVersion,
            calibrationId = calibrationId,
            componentRole = componentRole,
            modelComponents = modelComponents,
            driveSessionId = requireNotNull(event.driveSessionId),
            initialRouteRelationGroupIds = event.roadContext?.routeRelationGroupIds.orEmpty(),
            eligibleRouteRelationGroupIds = event.roadContext?.routeRelationGroupIds.orEmpty(),
            sourceRelationIds = event.roadContext?.sourceRelationIds.orEmpty(),
            firstSeenAtUtc = event.frameTimestampUtc,
            firstSeenContext = event.roadContext,
            lastSeenAtUtc = event.frameTimestampUtc,
            lastSeenContext = event.roadContext,
            routeContext = event.roadContext,
            accumulatedSupport = 0.0,
            overrideEligible = overrideEligible,
        )
        val resumingAfterLoss = current.boundary != null || current.negativeFrames > 0
        if (resumingAfterLoss) current.currentConsecutiveFramesSeen = 0
        current.candidate = candidate
        current.lastSeenAtUtc = event.frameTimestampUtc
        val priorContext = current.lastSeenContext
        val nextContext = event.roadContext
        val firstValidNextContext = nextContext?.takeIf { !it.wayId.isNullOrBlank() }
        if (current.firstSeenContext?.wayId.isNullOrBlank() && firstValidNextContext != null) {
            // Acquisition may begin during a transient map-matching gap. The first
            // later visible frame with a real match becomes the immutable route
            // origin; relations from a no-match frame must never seed or widen it.
            current.firstSeenContext = firstValidNextContext
            current.initialRouteRelationGroupIds = firstValidNextContext.routeRelationGroupIds
            current.eligibleRouteRelationGroupIds = firstValidNextContext.routeRelationGroupIds
            current.sourceRelationIds = firstValidNextContext.sourceRelationIds
        } else if (priorContext?.wayId != null && nextContext?.wayId != null && priorContext.wayId != nextContext.wayId) {
            current.eligibleRouteRelationGroupIds = current.eligibleRouteRelationGroupIds.intersect(
                nextContext.routeRelationGroupIds,
            )
            current.sourceRelationIds = current.sourceRelationIds.intersect(nextContext.sourceRelationIds)
        }
        current.lastSeenContext = nextContext
        if (nextContext != null && !nextContext.wayId.isNullOrBlank() && nextContext.matchedWayStable) {
            current.routeContext = nextContext
        }
        current.boundary = null
        current.negativeFrames = 0
        current.lossEvidence.clear()
        current.overrideEligible = current.overrideEligible && overrideEligible
        current.framesSeen += 1
        current.currentConsecutiveFramesSeen += 1
        current.peakConsecutiveFramesSeen = max(
            current.peakConsecutiveFramesSeen,
            current.currentConsecutiveFramesSeen,
        )
        current.assemblyIds += candidate.assemblyId?.takeIf(String::isNotBlank)
            ?: requireNotNull(event.frameId)
        val observedSupport = (fusedScore ?: confidence).coerceIn(0.0, 1.0)
        current.accumulatedSupport = if (current.evidence.isEmpty()) {
            observedSupport
        } else {
            val independentContribution = observedSupport * SUPPORT_CONTRIBUTION
            max(
                current.accumulatedSupport,
                1.0 - ((1.0 - current.accumulatedSupport) * (1.0 - independentContribution)),
            ).coerceAtMost(1.0)
        }
        current.evidence += TrafficSignPassageFrameEvidence(
            frameId = requireNotNull(event.frameId),
            timestampUtc = event.frameTimestampUtc,
            rawScore = candidate.rawScore,
            calibratedConfidence = candidate.calibratedConfidence,
            accumulatedSupport = current.accumulatedSupport,
            boundingBox = candidate.boundingBox,
            proposalRawScore = candidate.proposalRawScore ?: candidate.rawScore,
            proposalCalibratedConfidence = candidate.proposalCalibratedConfidence ?: candidate.calibratedConfidence,
            classifierRawScore = candidate.classifierRawScore ?: candidate.rawScore,
            classifierCalibratedConfidence = candidate.classifierCalibratedConfidence ?: candidate.calibratedConfidence,
            assemblyConfidence = candidate.assemblyConfidence ?: candidate.calibratedConfidence,
        )
        while (current.evidence.size > configuration.maximumEvidenceFrames) current.evidence.removeFirst()
        current.armed = when {
            current.framesSeen == 1 -> confidence >= configuration.singleFrameArmThreshold
            event.state == TrafficSignRecognitionState.CONFIRMED -> true
            else -> current.armed
        }
        return current
    }

    private fun observeMissing(
        event: TrafficSignRecognitionEvent,
        current: Track,
        strongPassGeometry: Boolean,
    ): TrafficSignPassageEvent? {
        if (!current.armed) return null
        val frameId = event.frameId?.takeIf(String::isNotBlank) ?: return null
        if (current.boundary == null) {
            current.boundary = TrafficSignPassageBoundary(event.frameTimestampUtc, event.roadContext, strongPassGeometry)
        }
        current.lossEvidence += TrafficSignPassageLossEvidence(
            frameId = frameId,
            timestampUtc = event.frameTimestampUtc,
            strongPassGeometry = strongPassGeometry,
        )
        current.negativeFrames += 1
        val requiredNegatives = when {
            current.framesSeen == 1 -> configuration.singleFrameNegativeFrames
            current.boundary?.strongPassGeometry == true -> configuration.strongPassGeometryNegativeFrames
            else -> configuration.repeatedTrackNegativeFrames
        }
        if (current.negativeFrames < requiredNegatives) return null
        val finalConfidence = current.evidence.maxOfOrNull {
            it.calibratedConfidence ?: it.rawScore
        } ?: return null
        val boundary = requireNotNull(current.boundary)
        val action = current.candidate.toAction(current.lastSeenContext?.countryCode ?: event.roadContext?.countryCode)
        val finalizedId = listOf(
            current.packId,
            current.id,
            boundary.timestampUtc.toEpochMilli().toString(),
            action.kind.wireValue,
        ).joinToString(":")
        if (isRecentlyCommittedPhysicalSign(current.candidate, current.lastSeenContext, boundary.timestampUtc)) {
            track = null
            return null
        }
        lastCommittedPhysicalSign = CommittedPhysicalSign(
            trackId = current.id,
            actionKey = current.candidate.normalizedActionKey(current.lastSeenContext?.countryCode),
            committedAtUtc = boundary.timestampUtc,
            latitude = current.lastSeenContext?.latitude,
            longitude = current.lastSeenContext?.longitude,
        )
        track = null
        return TrafficSignPassageEvent(
            finalizedEventId = finalizedId,
            driveSessionId = current.driveSessionId,
            generation = requireNotNull(generation),
            packId = current.packId,
            artifactSha256 = current.artifactSha256,
            preprocessingVersion = current.preprocessingVersion,
            calibrationId = current.calibrationId,
            componentRole = current.componentRole,
            modelComponents = current.modelComponents,
            physicalTrackId = current.id,
            assemblyId = current.candidate.assemblyId,
            assemblyIds = current.assemblyIds.toList(),
            action = action,
            resolution = resolveDirectAction(action),
            firstSeenAtUtc = current.firstSeenAtUtc,
            lastSeenAtUtc = current.lastSeenAtUtc,
            firstSeenContext = current.firstSeenContext,
            lastSeenContext = current.lastSeenContext,
            passageBoundary = boundary,
            activationContext = boundary.context?.takeIf { !it.wayId.isNullOrBlank() && it.matchedWayStable },
            initialRouteRelationGroupIds = current.initialRouteRelationGroupIds,
            eligibleRouteRelationGroupIds = current.eligibleRouteRelationGroupIds,
            sourceRelationIds = current.sourceRelationIds,
            evidence = current.evidence.toList(),
            lossEvidence = current.lossEvidence.toList(),
            framesSeen = current.framesSeen,
            finalConfidence = finalConfidence,
            finalAccumulatedSupport = current.accumulatedSupport,
            peakConsecutiveFramesSeen = current.peakConsecutiveFramesSeen,
            lossReason = if (boundary.strongPassGeometry) "strong_pass_geometry" else "negative_debounce",
            negativeFramesToCommit = requiredNegatives,
            overrideEligible = current.overrideEligible,
        )
    }

    private fun expireSuppression(now: Instant) {
        lastCommittedPhysicalSign = lastCommittedPhysicalSign?.takeUnless { committed ->
            Duration.between(committed.committedAtUtc, now) > configuration.physicalTrackSuppressionWindow
        }
    }

    private fun isRecentlyCommittedPhysicalSign(
        candidate: TrafficSignCandidate,
        context: TrafficSignDetectionContext?,
        observedAtUtc: Instant,
    ): Boolean {
        val committed = lastCommittedPhysicalSign ?: return false
        val elapsed = Duration.between(committed.committedAtUtc, observedAtUtc)
        if (elapsed.isNegative || elapsed > configuration.physicalTrackSuppressionWindow) return false
        if (committed.actionKey != candidate.normalizedActionKey(context?.countryCode)) return false
        if (committed.trackId == candidate.trackId) return true
        val latitude = context?.latitude ?: return false
        val longitude = context.longitude
        val committedLatitude = committed.latitude ?: return false
        val committedLongitude = committed.longitude ?: return false
        return distanceMeters(
            committedLatitude,
            committedLongitude,
            latitude,
            longitude,
        ) <= configuration.physicalTrackSuppressionDistanceM
    }

    private data class CommittedPhysicalSign(
        val trackId: String,
        val actionKey: String,
        val committedAtUtc: Instant,
        val latitude: Double?,
        val longitude: Double?,
    )

    private data class Track(
        val id: String,
        var candidate: TrafficSignCandidate,
        val packId: String,
        val artifactSha256: String,
        val preprocessingVersion: String,
        val calibrationId: String,
        val componentRole: String,
        val modelComponents: List<TrafficSignModelComponentLineage>,
        val driveSessionId: String,
        var initialRouteRelationGroupIds: Set<Long>,
        var eligibleRouteRelationGroupIds: Set<Long>,
        var sourceRelationIds: Set<Long>,
        val firstSeenAtUtc: Instant,
        var firstSeenContext: TrafficSignDetectionContext?,
        var lastSeenAtUtc: Instant,
        var lastSeenContext: TrafficSignDetectionContext?,
        var routeContext: TrafficSignDetectionContext?,
        var accumulatedSupport: Double,
        var overrideEligible: Boolean,
        val assemblyIds: LinkedHashSet<String> = linkedSetOf(),
        val evidence: ArrayDeque<TrafficSignPassageFrameEvidence> = ArrayDeque(),
        val lossEvidence: ArrayDeque<TrafficSignPassageLossEvidence> = ArrayDeque(),
        var framesSeen: Int = 0,
        var currentConsecutiveFramesSeen: Int = 0,
        var peakConsecutiveFramesSeen: Int = 0,
        var armed: Boolean = false,
        var boundary: TrafficSignPassageBoundary? = null,
        var negativeFrames: Int = 0,
    ) {
        fun reconcileRouteContext(next: TrafficSignDetectionContext): Boolean {
            val previous = routeContext ?: firstSeenContext ?: return true
            if (previous.sourceSignature.bundleRevision != next.sourceSignature.bundleRevision) return false
            if (previous.bundleSha256 != next.bundleSha256) return false
            if (previous.traversalEpoch != next.traversalEpoch) return false
            val previousWayId = previous.wayId
            val nextWayId = next.wayId
            if (previousWayId.isNullOrBlank() || nextWayId.isNullOrBlank() || !next.matchedWayStable) return true
            if (previousWayId == nextWayId) {
                if (previous.travelDirection != TrafficSignTravelDirection.UNKNOWN &&
                    next.travelDirection != TrafficSignTravelDirection.UNKNOWN &&
                    previous.travelDirection != next.travelDirection
                ) return false
                // Heading can briefly be indeterminate without constituting a
                // reversal. Do not let that gap erase the last known direction,
                // otherwise FORWARD -> UNKNOWN -> REVERSE would be accepted.
                routeContext = if (
                    next.travelDirection == TrafficSignTravelDirection.UNKNOWN &&
                    previous.travelDirection != TrafficSignTravelDirection.UNKNOWN
                ) {
                    next.copy(travelDirection = previous.travelDirection)
                } else {
                    next
                }
                return true
            }
            if (!previous.continuityCapable || !next.continuityCapable) return false
            val narrowedRelations = eligibleRouteRelationGroupIds.intersect(next.routeRelationGroupIds)
            if (narrowedRelations.isEmpty()) return false
            eligibleRouteRelationGroupIds = narrowedRelations
            sourceRelationIds = sourceRelationIds.intersect(next.sourceRelationIds)
            routeContext = next
            return true
        }

        fun isCompatibleWith(event: TrafficSignRecognitionEvent, candidate: TrafficSignCandidate): Boolean =
            id == candidate.trackId &&
                this.candidate.semantic == candidate.semantic &&
                packId == event.packId &&
                artifactSha256 == event.artifactSha256 &&
                preprocessingVersion == event.preprocessingVersion &&
                calibrationId == event.calibrationId &&
                componentRole == event.componentRole &&
                modelComponents == event.modelComponents
    }

    private companion object {
        // Closely correlated video frames must not be treated as independent
        // probabilities. This capped contribution still accumulates evidence.
        const val SUPPORT_CONTRIBUTION = 0.35
    }
}

internal data class TrafficSignActiveTrackRouteScope(
    val physicalTrackId: String,
    val initialRouteRelationGroupIds: Set<Long>,
    val eligibleRouteRelationGroupIds: Set<Long>,
    val sourceRelationIds: Set<Long>,
)

internal data class TrafficSignTrackScopeReconciliation(
    val activeScope: TrafficSignActiveTrackRouteScope?,
    val trackSetChanged: Boolean,
)

private fun TrafficSignCandidate.normalizedActionKey(countryCode: String?): String {
    val action = toAction(countryCode)
    return listOf(
        action.kind.wireValue,
        action.valueKmh?.toString().orEmpty(),
        action.countryCode?.trim()?.uppercase().orEmpty(),
        action.conditionState.wireValue,
        action.restrictions
            .map { "${it.kind.wireValue}:${it.normalizedValue.trim()}" }
            .sorted()
            .joinToString(","),
    ).joinToString("|")
}

private fun TrafficSignCandidate.toAction(countryCode: String?): TrafficSignAction {
    val kind = when (semantic.kind) {
        TrafficSignSemanticKind.MAXIMUM_SPEED -> TrafficSignActionKind.POSTED_MAXIMUM
        TrafficSignSemanticKind.MAXIMUM_SPEED_END -> TrafficSignActionKind.MAXIMUM_SPEED_END
        TrafficSignSemanticKind.ZONE_START -> TrafficSignActionKind.ZONE_START
        TrafficSignSemanticKind.ZONE_END -> TrafficSignActionKind.ZONE_END
        TrafficSignSemanticKind.RESTRICTION_END -> legacyRestrictionEndActionKind()
        TrafficSignSemanticKind.ALL_RESTRICTIONS_END -> TrafficSignActionKind.ALL_RESTRICTIONS_END
        TrafficSignSemanticKind.CITY_ENTRY -> TrafficSignActionKind.CITY_ENTRY
        TrafficSignSemanticKind.CITY_EXIT -> TrafficSignActionKind.CITY_EXIT
        TrafficSignSemanticKind.PEDESTRIAN_ZONE_START -> TrafficSignActionKind.PEDESTRIAN_ZONE_START
        TrafficSignSemanticKind.PEDESTRIAN_ZONE_END -> TrafficSignActionKind.PEDESTRIAN_ZONE_END
        TrafficSignSemanticKind.MOTORWAY_EXIT -> TrafficSignActionKind.MOTORWAY_EXIT
        TrafficSignSemanticKind.MOTORROAD_EXIT -> TrafficSignActionKind.MOTORROAD_EXIT
        TrafficSignSemanticKind.NON_SPEED_RESTRICTION_END -> TrafficSignActionKind.NON_SPEED_RESTRICTION_END
        TrafficSignSemanticKind.TEMPORARY -> TrafficSignActionKind.TEMPORARY_MAXIMUM
        TrafficSignSemanticKind.UNKNOWN -> TrafficSignActionKind.UNKNOWN
    }
    return TrafficSignAction(
        kind = kind,
        valueKmh = semantic.value,
        countryCode = countryCode,
        conditionState = conditionState,
        restrictions = restrictions,
    )
}

private fun TrafficSignCandidate.legacyRestrictionEndActionKind(): TrafficSignActionKind {
    val token = "$rawClassId $rawLabel".trim().lowercase()
    return when {
        token.contains("maxspeed:end") || token.contains("de:278") ||
            Regex("(^|[^0-9])278([^0-9]|$)").containsMatchIn(token) -> TrafficSignActionKind.MAXIMUM_SPEED_END
        token.contains("no:end") || token.contains("all_restrictions") || token.contains("de:282") ||
            Regex("(^|[^0-9])282([^0-9]|$)").containsMatchIn(token) -> TrafficSignActionKind.ALL_RESTRICTIONS_END
        else -> TrafficSignActionKind.NON_SPEED_RESTRICTION_END
    }
}

fun resolveDirectAction(action: TrafficSignAction): TrafficSignResolvedLimit = when (action.kind) {
    TrafficSignActionKind.POSTED_MAXIMUM,
    TrafficSignActionKind.ZONE_START -> action.valueKmh?.let {
        TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, it)
    } ?: TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN)
    TrafficSignActionKind.CITY_ENTRY -> if (action.countryCode.equals("DE", true) || action.countryCode.equals("DEU", true)) {
        TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50)
    } else {
        TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN)
    }
    TrafficSignActionKind.PEDESTRIAN_ZONE_START -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.WALK)
    else -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN)
}

enum class EffectiveSpeedLimitSource(val wireValue: String) {
    CAMERA("camera"),
    LOCAL_CORRECTION("local_correction"),
    BUNDLE("bundle"),
    NONE("none"),
}

data class EffectiveSpeedLimit(
    val resolution: TrafficSignResolvedLimit?,
    val source: EffectiveSpeedLimitSource,
    val presentationReason: String,
    val cameraEvidence: Boolean = source == EffectiveSpeedLimitSource.CAMERA,
)

data class TrafficSignBaseLimit(
    val resolution: TrafficSignResolvedLimit?,
    val source: EffectiveSpeedLimitSource,
    val reason: String,
    val structurallyVerifiedForEnd: Boolean = false,
) {
    init {
        require(source != EffectiveSpeedLimitSource.CAMERA)
    }

    fun effective() = EffectiveSpeedLimit(resolution, source, reason)
}

data class TrafficSignApplicabilityScope(
    val originWayId: String,
    val currentWayId: String,
    val travelDirection: TrafficSignTravelDirection,
    val traversalEpoch: Long,
    val bundleRevision: String,
    val bundleSha256: String,
    val eligibleRouteRelationGroupIds: Set<Long>,
    val sourceRelationIds: Set<Long>,
    val continuityCapable: Boolean,
    val lastMatchedAtUtc: Instant,
    val gapStartedAtUtc: Instant? = null,
    val gapDistanceM: Double = 0.0,
)

data class TrafficSignRuleLayer(
    val kind: TrafficSignActionKind,
    val resolution: TrafficSignResolvedLimit,
    val eventId: String,
)

data class TrafficSignCameraAssertion(
    val event: TrafficSignPassageEvent,
    val scope: TrafficSignApplicabilityScope,
    val layers: List<TrafficSignRuleLayer>,
    val resolution: TrafficSignResolvedLimit,
    val presentationReason: String,
)

data class TrafficSignRoadMatch(
    val context: TrafficSignDetectionContext?,
    val matchedAtUtc: Instant,
    val distanceFromPreviousM: Double = 0.0,
    val stabilized: Boolean = true,
    val traversalReversed: Boolean = false,
)

data class TrafficSignSourceResolverConfiguration(
    val maximumNoMatchDuration: Duration = Duration.ofSeconds(5),
    val maximumNoMatchDistanceM: Double = 120.0,
)

/** Stateful camera layer above the ordinary local-correction/bundle base. */
class TrafficSignRuntimeSourceResolver(
    private val configuration: TrafficSignSourceResolverConfiguration = TrafficSignSourceResolverConfiguration(),
) {
    private var active: TrafficSignCameraAssertion? = null
    private var pending: PendingPassage? = null
    private var newlyActivatedEvent: TrafficSignPassageEvent? = null
    private var newlyPersistableEvent: TrafficSignPassageEvent? = null

    fun activeAssertion(): TrafficSignCameraAssertion? = active

    fun clear() {
        active = null
        pending = null
        newlyActivatedEvent = null
        newlyPersistableEvent = null
    }

    fun takeNewlyActivatedEvent(): TrafficSignPassageEvent? = newlyActivatedEvent.also {
        newlyActivatedEvent = null
    }

    fun takeNewlyPersistableEvent(): TrafficSignPassageEvent? = newlyPersistableEvent.also {
        newlyPersistableEvent = null
    }

    fun commit(event: TrafficSignPassageEvent, base: TrafficSignBaseLimit): EffectiveSpeedLimit {
        if (!event.overrideEligible) return effective(base)
        val context = event.activationContext
        if (context == null || context.wayId.isNullOrBlank()) {
            val lastSeen = event.lastSeenContext
            if (lastSeen != null && !lastSeen.wayId.isNullOrBlank()) {
                pending = PendingPassage(event, lastSeen, event.passageBoundary.timestampUtc, 0.0)
            }
            return effective(base)
        }
        val wayId = context.wayId?.trim().orEmpty()
        if (wayId.isNotEmpty() && context.matchedWayStable) {
            newlyPersistableEvent = event
        }
        if ((event.action.isConditional || !event.action.isPermanentRuntimeAction) &&
            event.action.kind !in SPEED_END_ACTION_KINDS
        ) {
            return effective(base)
        }
        if (wayId.isEmpty() || !context.matchedWayStable || !context.hasVerifiedBundle
        ) {
            return if (event.action.kind in SPEED_END_ACTION_KINDS) {
                maskOrPreserveUnsafeEnd(event, base, "camera_end_unsafe_context")
            } else {
                effective(base)
            }
        }
        val firstSeenWayId = event.firstSeenContext?.wayId?.trim().orEmpty()
        if (firstSeenWayId.isEmpty()) {
            return if (event.action.kind in SPEED_END_ACTION_KINDS) {
                maskOrPreserveUnsafeEnd(event, base, "camera_end_recognition_scope_missing")
            } else {
                effective(base)
            }
        }
        val activationRelationGroups = event.eligibleRouteRelationGroupIds.intersect(context.routeRelationGroupIds)
        if (wayId != firstSeenWayId && activationRelationGroups.isEmpty()) {
            return if (event.action.kind in SPEED_END_ACTION_KINDS) {
                maskOrPreserveUnsafeEnd(event, base, "camera_end_recognition_scope_lost")
            } else {
                effective(base)
            }
        }
        val previousLayers = active
            ?.takeIf { it.scope.traversalEpoch == context.traversalEpoch }
            ?.layers
            .orEmpty()
        val reduced = reduceLayers(previousLayers, event.action, event.finalizedEventId, base)
        if (reduced.noMutation) return effective(base)
        val resolution = reduced.layers.lastOrNull()?.resolution ?: reduced.fallback
        val scope = TrafficSignApplicabilityScope(
            originWayId = firstSeenWayId,
            currentWayId = wayId,
            travelDirection = context.travelDirection,
            traversalEpoch = context.traversalEpoch,
            bundleRevision = context.sourceSignature.bundleRevision,
            bundleSha256 = requireNotNull(context.bundleSha256),
            eligibleRouteRelationGroupIds = activationRelationGroups,
            sourceRelationIds = event.sourceRelationIds.intersect(context.sourceRelationIds),
            continuityCapable = context.continuityCapable,
            lastMatchedAtUtc = event.passageBoundary.timestampUtc,
        )
        active = TrafficSignCameraAssertion(
            event = event,
            scope = scope,
            layers = reduced.layers,
            resolution = resolution,
            presentationReason = reduced.reason,
        )
        newlyActivatedEvent = event
        return effective(base)
    }

    /**
     * An unsafe end cannot establish a new route scope, but it also cannot
     * leave a matching stale camera restriction displayed. Mutate only the
     * previously safe assertion's typed layers; an explicit crossed-value
     * mismatch is the sole no-mutation case and therefore preserves it.
     */
    private fun maskOrPreserveUnsafeEnd(
        event: TrafficSignPassageEvent,
        base: TrafficSignBaseLimit,
        reason: String,
    ): EffectiveSpeedLimit {
        val previous = active ?: return base.effective()
        val reduced = reduceLayers(previous.layers, event.action, event.finalizedEventId, base)
        if (reduced.noMutation) return effective(base)
        val survivingResolution = reduced.layers.lastOrNull()?.resolution
        val resolution = survivingResolution
            ?: base.resolution?.takeIf { base.structurallyVerifiedForEnd }
            ?: TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN)
        active = previous.copy(
            event = event,
            layers = reduced.layers,
            resolution = resolution,
            presentationReason = if (resolution.kind == TrafficSignResolvedLimitKind.UNKNOWN) {
                "${reason}_masked"
            } else {
                "${reason}_restored_enclosing"
            },
        )
        newlyActivatedEvent = event
        return effective(base)
    }

    fun reconcile(match: TrafficSignRoadMatch, base: TrafficSignBaseLimit): EffectiveSpeedLimit {
        reconcilePending(match, base)?.let { return it }
        val assertion = active ?: return base.effective()
        if (match.traversalReversed) {
            active = null
            return base.effective()
        }
        val context = match.context
        if (context == null || context.wayId.isNullOrBlank()) {
            val startedAt = assertion.scope.gapStartedAtUtc ?: match.matchedAtUtc
            val distance = assertion.scope.gapDistanceM + match.distanceFromPreviousM.coerceAtLeast(0.0)
            if (Duration.between(startedAt, match.matchedAtUtc) > configuration.maximumNoMatchDuration ||
                distance > configuration.maximumNoMatchDistanceM
            ) {
                active = null
                return base.effective()
            }
            active = assertion.copy(scope = assertion.scope.copy(gapStartedAtUtc = startedAt, gapDistanceM = distance))
            return effective(base)
        }
        if (!match.stabilized) return effective(base)
        val wayId = context.wayId
        if (context.traversalEpoch != assertion.scope.traversalEpoch) {
            active = null
            return base.effective()
        }
        if (context.sourceSignature.bundleRevision != assertion.scope.bundleRevision) {
            active = null
            return base.effective()
        }
        if (context.bundleSha256 != assertion.scope.bundleSha256) {
            active = null
            return base.effective()
        }
        if (wayId == assertion.scope.currentWayId) {
            if (context.travelDirection != TrafficSignTravelDirection.UNKNOWN &&
                assertion.scope.travelDirection != TrafficSignTravelDirection.UNKNOWN &&
                context.travelDirection != assertion.scope.travelDirection
            ) {
                active = null
                return base.effective()
            }
            active = assertion.copy(
                scope = assertion.scope.copy(
                    lastMatchedAtUtc = match.matchedAtUtc,
                    gapStartedAtUtc = null,
                    gapDistanceM = 0.0,
                ),
            )
            return effective(base)
        }
        val sharedGroups = assertion.scope.eligibleRouteRelationGroupIds.intersect(context.routeRelationGroupIds)
        if (!context.continuityCapable || sharedGroups.isEmpty()) {
            active = null
            return base.effective()
        }
        active = assertion.copy(
            scope = assertion.scope.copy(
                currentWayId = wayId,
                travelDirection = context.travelDirection,
                eligibleRouteRelationGroupIds = sharedGroups,
                sourceRelationIds = assertion.scope.sourceRelationIds.intersect(context.sourceRelationIds),
                lastMatchedAtUtc = match.matchedAtUtc,
                gapStartedAtUtc = null,
                gapDistanceM = 0.0,
            ),
        )
        return effective(base)
    }

    private fun reconcilePending(match: TrafficSignRoadMatch, base: TrafficSignBaseLimit): EffectiveSpeedLimit? {
        val waiting = pending ?: return null
        if (match.traversalReversed) {
            pending = null
            return null
        }
        val elapsed = Duration.between(waiting.startedAtUtc, match.matchedAtUtc)
        val distance = waiting.distanceM + match.distanceFromPreviousM.coerceAtLeast(0.0)
        if (elapsed > configuration.maximumNoMatchDuration || distance > configuration.maximumNoMatchDistanceM) {
            pending = null
            return null
        }
        val context = match.context
        if (context == null || context.wayId.isNullOrBlank() || !match.stabilized) {
            pending = waiting.copy(distanceM = distance)
            return null
        }
        val lastSeen = waiting.lastSeenContext
        val sameWay = context.wayId == lastSeen.wayId && (
            context.travelDirection == TrafficSignTravelDirection.UNKNOWN ||
                lastSeen.travelDirection == TrafficSignTravelDirection.UNKNOWN ||
                context.travelDirection == lastSeen.travelDirection
            )
        val sharedGroups = waiting.event.eligibleRouteRelationGroupIds.intersect(context.routeRelationGroupIds)
        val sameScope = context.traversalEpoch == lastSeen.traversalEpoch &&
            context.sourceSignature.bundleRevision == lastSeen.sourceSignature.bundleRevision &&
            context.bundleSha256 == lastSeen.bundleSha256 &&
            (sameWay || (context.continuityCapable && sharedGroups.isNotEmpty()))
        pending = null
        if (!sameScope) {
            return null
        }
        val activated = waiting.event.copy(
            activationContext = context,
            activationAtUtc = match.matchedAtUtc,
            pendingRematchDistanceM = distance,
        )
        return commit(activated, base)
    }

    fun effective(base: TrafficSignBaseLimit): EffectiveSpeedLimit {
        val assertion = active ?: return base.effective()
        return if (assertion.resolution.kind == TrafficSignResolvedLimitKind.UNKNOWN) {
            EffectiveSpeedLimit(
                resolution = assertion.resolution,
                source = EffectiveSpeedLimitSource.NONE,
                presentationReason = assertion.presentationReason,
                cameraEvidence = true,
            )
        } else {
            EffectiveSpeedLimit(
                resolution = assertion.resolution,
                source = EffectiveSpeedLimitSource.CAMERA,
                presentationReason = assertion.presentationReason,
                cameraEvidence = true,
            )
        }
    }

    private fun reduceLayers(
        current: List<TrafficSignRuleLayer>,
        action: TrafficSignAction,
        eventId: String,
        base: TrafficSignBaseLimit,
    ): ReducedLayers {
        val layers = current.toMutableList()
        fun add(kind: TrafficSignActionKind, resolution: TrafficSignResolvedLimit, remove: Set<TrafficSignActionKind>) {
            layers.removeAll { it.kind in remove }
            layers += TrafficSignRuleLayer(kind, resolution, eventId)
        }
        when (action.kind) {
            TrafficSignActionKind.POSTED_MAXIMUM -> {
                val resolved = resolveDirectAction(action)
                if (resolved.kind == TrafficSignResolvedLimitKind.UNKNOWN) return unresolved(layers, "camera_posted_maximum_unresolved")
                add(action.kind, resolved, setOf(TrafficSignActionKind.POSTED_MAXIMUM, TrafficSignActionKind.TEMPORARY_MAXIMUM))
                return ReducedLayers(layers, resolved, "camera_posted_maximum")
            }
            TrafficSignActionKind.ZONE_START -> {
                val resolved = resolveDirectAction(action)
                if (resolved.kind == TrafficSignResolvedLimitKind.UNKNOWN) return unresolved(layers, "camera_zone_start_unresolved")
                add(action.kind, resolved, setOf(TrafficSignActionKind.ZONE_START, TrafficSignActionKind.POSTED_MAXIMUM))
                return ReducedLayers(layers, resolved, "camera_zone_start")
            }
            TrafficSignActionKind.CITY_ENTRY -> {
                val resolved = resolveDirectAction(action)
                if (resolved.kind == TrafficSignResolvedLimitKind.UNKNOWN) return unresolved(layers, "camera_city_entry_unresolved")
                add(action.kind, resolved, setOf(TrafficSignActionKind.CITY_ENTRY, TrafficSignActionKind.POSTED_MAXIMUM))
                return ReducedLayers(layers, resolved, "camera_city_entry")
            }
            TrafficSignActionKind.PEDESTRIAN_ZONE_START -> {
                val resolved = resolveDirectAction(action)
                add(action.kind, resolved, setOf(TrafficSignActionKind.PEDESTRIAN_ZONE_START, TrafficSignActionKind.POSTED_MAXIMUM))
                return ReducedLayers(layers, resolved, "camera_pedestrian_zone_start")
            }
            TrafficSignActionKind.MAXIMUM_SPEED_END -> {
                val index = layers.indexOfLast { it.kind == TrafficSignActionKind.POSTED_MAXIMUM }
                if (index < 0) {
                    val enclosing = layers.lastOrNull()?.resolution
                    return if (enclosing != null) {
                        ReducedLayers(layers, enclosing, "camera_maximum_speed_end_enclosing_rule")
                    } else {
                        unresolved(emptyList(), "camera_maximum_speed_end_unresolved")
                    }
                }
                if (action.valueKmh != null && layers[index].resolution.speedKmh != action.valueKmh) {
                    return ReducedLayers(
                        layers = layers,
                        fallback = layers.last().resolution,
                        reason = "camera_maximum_speed_end_mismatch_review",
                        noMutation = true,
                    )
                }
                layers.removeAt(index)
                return restored(layers, base, "camera_maximum_speed_end")
            }
            TrafficSignActionKind.ALL_RESTRICTIONS_END -> {
                layers.removeAll { it.kind in setOf(TrafficSignActionKind.POSTED_MAXIMUM, TrafficSignActionKind.TEMPORARY_MAXIMUM) }
                return restored(layers, base, "camera_all_restrictions_end")
            }
            TrafficSignActionKind.ZONE_END -> {
                val zoneIndex = layers.indexOfLast { it.kind == TrafficSignActionKind.ZONE_START }
                if (zoneIndex < 0) {
                    val enclosing = layers.lastOrNull()?.resolution
                    return if (enclosing != null) {
                        ReducedLayers(layers, enclosing, "camera_zone_end_enclosing_rule")
                    } else {
                        unresolved(emptyList(), "camera_zone_end_unresolved")
                    }
                }
                if (action.valueKmh != null && layers[zoneIndex].resolution.speedKmh != action.valueKmh) {
                    return ReducedLayers(
                        layers = layers,
                        fallback = layers.last().resolution,
                        reason = "camera_zone_end_mismatch_review",
                        noMutation = true,
                    )
                }
                layers.removeAll { it.kind in setOf(TrafficSignActionKind.ZONE_START, TrafficSignActionKind.POSTED_MAXIMUM) }
                return restored(layers, base, "camera_zone_end")
            }
            TrafficSignActionKind.CITY_EXIT -> {
                layers.removeAll { it.kind in setOf(TrafficSignActionKind.CITY_ENTRY, TrafficSignActionKind.POSTED_MAXIMUM) }
                return restored(layers, base, "camera_city_exit")
            }
            TrafficSignActionKind.PEDESTRIAN_ZONE_END -> {
                layers.removeAll {
                    it.kind in setOf(
                        TrafficSignActionKind.PEDESTRIAN_ZONE_START,
                        TrafficSignActionKind.POSTED_MAXIMUM,
                        TrafficSignActionKind.TEMPORARY_MAXIMUM,
                    )
                }
                return restored(layers, base, "camera_pedestrian_zone_end")
            }
            TrafficSignActionKind.MOTORWAY_EXIT,
            TrafficSignActionKind.MOTORROAD_EXIT -> {
                // Leaving the classified road terminates its posted/temporary
                // camera rule. Never carry that stale number onto the new road.
                layers.removeAll {
                    it.kind in setOf(
                        TrafficSignActionKind.POSTED_MAXIMUM,
                        TrafficSignActionKind.TEMPORARY_MAXIMUM,
                    )
                }
                return restored(layers, base, "camera_road_class_exit")
            }
            TrafficSignActionKind.NON_SPEED_RESTRICTION_END -> return ReducedLayers(layers, active?.resolution ?: TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN), "camera_non_speed_end", noMutation = true)
            TrafficSignActionKind.TEMPORARY_MAXIMUM,
            TrafficSignActionKind.UNKNOWN -> return unresolved(layers, "camera_action_review_only")
        }
    }

    private fun restored(
        layers: List<TrafficSignRuleLayer>,
        base: TrafficSignBaseLimit,
        reason: String,
    ): ReducedLayers {
        val restored = layers.lastOrNull()?.resolution
            ?: base.resolution?.takeIf { base.structurallyVerifiedForEnd }
            ?: TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN)
        return ReducedLayers(layers, restored, if (restored.kind == TrafficSignResolvedLimitKind.UNKNOWN) "${reason}_unresolved" else reason)
    }

    private fun unresolved(layers: List<TrafficSignRuleLayer>, reason: String) = ReducedLayers(
        layers = layers,
        fallback = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNKNOWN),
        reason = reason,
    )

    private data class ReducedLayers(
        val layers: List<TrafficSignRuleLayer>,
        val fallback: TrafficSignResolvedLimit,
        val reason: String,
        val noMutation: Boolean = false,
    )

    private data class PendingPassage(
        val event: TrafficSignPassageEvent,
        val lastSeenContext: TrafficSignDetectionContext,
        val startedAtUtc: Instant,
        val distanceM: Double,
    )
}

internal fun distanceMeters(
    firstLatitude: Double,
    firstLongitude: Double,
    secondLatitude: Double,
    secondLongitude: Double,
): Double {
    val lat1 = Math.toRadians(firstLatitude)
    val lat2 = Math.toRadians(secondLatitude)
    val dLat = lat2 - lat1
    val dLon = Math.toRadians(secondLongitude - firstLongitude)
    val a = sin(dLat / 2.0) * sin(dLat / 2.0) + cos(lat1) * cos(lat2) * sin(dLon / 2.0) * sin(dLon / 2.0)
    return 2.0 * 6_371_000.0 * asin(sqrt(a.coerceIn(0.0, 1.0)))
}

/** Admission guard for a delayed finalized result before it may mutate/persist. */
internal fun trafficSignPassageContextIsCurrent(
    event: TrafficSignPassageEvent,
    current: TrafficSignDetectionContext?,
): Boolean {
    val currentContext = current ?: return false
    // A no-match boundary deliberately has no activation context. It may enter
    // the resolver's bounded pending state only while the controller is still
    // on the frozen recognition scope (or still has no match); an unrelated
    // stabilized result must reject the delayed callback before any mutation.
    val anchor = event.activationContext ?: event.lastSeenContext ?: return false
    if (anchor.sourceSignature.bundleRevision != currentContext.sourceSignature.bundleRevision) return false
    if (anchor.bundleSha256 != currentContext.bundleSha256) return false
    if (anchor.traversalEpoch != currentContext.traversalEpoch) return false
    if (currentContext.wayId.isNullOrBlank()) return true
    if (!currentContext.matchedWayStable) return false
    if (anchor.wayId == currentContext.wayId) {
        return anchor.travelDirection == TrafficSignTravelDirection.UNKNOWN ||
            currentContext.travelDirection == TrafficSignTravelDirection.UNKNOWN ||
            anchor.travelDirection == currentContext.travelDirection
    }
    return anchor.continuityCapable && currentContext.continuityCapable &&
        event.eligibleRouteRelationGroupIds.intersect(currentContext.routeRelationGroupIds).isNotEmpty()
}

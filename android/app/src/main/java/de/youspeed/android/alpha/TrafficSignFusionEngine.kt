package de.youspeed.android.alpha

import kotlin.math.max

data class TrafficSignDetection(
    val candidate: TrafficSignCandidate,
    /** Higher values identify a sharper, better exposed, or otherwise stronger crop. */
    val cropQuality: Double = candidate.boundingBox.area,
) {
    init {
        require(cropQuality.isFinite() && cropQuality >= 0.0) { "Crop quality must be finite and non-negative" }
    }
}

data class TrafficSignFusionResult(
    val state: TrafficSignRecognitionState,
    val candidate: TrafficSignCandidate?,
    val fusedScore: Double?,
    val bestCropBoundingBox: NormalizedTrafficSignBoundingBox?,
)

/**
 * Bounded temporal fusion for one stream. Repeated spatially overlapping
 * observations of the same normalized class progress from provisional to
 * confirmed. Low-confidence candidates remain unknown and never form tracks.
 */
class TrafficSignFusionEngine(
    private val thresholds: TrafficSignThresholds,
    private val scoreSource: TrafficSignCalibrationOutput,
    classThresholds: Map<String, Double> = emptyMap(),
) {
    private val classThresholds = classThresholds.toMap()
    private val tracks = mutableListOf<Track>()
    private var nextTrackNumber = 1L
    private var lastObservedAtMs: Long? = null

    init {
        require(thresholds.confirmationFrames >= 2)
        require(thresholds.confirmationWindowMs > 0)
        require(thresholds.unknown in 0.0..1.0)
        require(thresholds.provisional in 0.0..1.0)
        require(thresholds.confirmed in 0.0..1.0)
        require(thresholds.unknown <= thresholds.provisional)
        require(thresholds.provisional <= thresholds.confirmed)
        require(thresholds.minimumTrackIou in 0.0..1.0)
        require(classThresholds.values.all { it.isFinite() && it in 0.0..1.0 })
    }

    fun observe(
        detection: TrafficSignDetection?,
        observedAtMs: Long,
    ): TrafficSignFusionResult {
        require(observedAtMs >= 0L) { "Observation timestamp must not be negative" }
        val previousTimestamp = lastObservedAtMs
        require(previousTimestamp == null || observedAtMs >= previousTimestamp) {
            "Traffic-sign observations must be chronological"
        }
        lastObservedAtMs = observedAtMs
        expireTracks(observedAtMs)
        if (detection == null) return noRecognition()

        val score = effectiveScore(detection.candidate)
        val classThreshold = classThresholds[detection.candidate.rawClassId] ?: 0.0
        if (!score.isFinite() || score < max(thresholds.unknown, classThreshold)) return noRecognition()
        if (detection.candidate.semantic.kind == TrafficSignSemanticKind.UNKNOWN) {
            return TrafficSignFusionResult(
                state = TrafficSignRecognitionState.UNKNOWN,
                candidate = detection.candidate.copy(trackId = null, evidenceFrames = 1),
                fusedScore = score,
                bestCropBoundingBox = detection.candidate.boundingBox,
            )
        }

        val matchingTrack = tracks
            .filter { it.matches(detection.candidate, thresholds.minimumTrackIou) }
            .maxByOrNull { it.latest.candidate.boundingBox.intersectionOverUnion(detection.candidate.boundingBox) }
            ?: Track(
                id = "tsr-track-${nextTrackNumber++}",
                observations = mutableListOf(),
            ).also(tracks::add)

        matchingTrack.observations += TimedDetection(observedAtMs, detection)
        matchingTrack.observations.removeAll { observedAtMs - it.observedAtMs > thresholds.confirmationWindowMs }

        val fusedScore = matchingTrack.weightedScore(::effectiveScore)
        val hasConfirmedEvidence = matchingTrack.observations.any {
            effectiveScore(it.detection.candidate) >= thresholds.confirmed
        }
        val state = if (
            matchingTrack.observations.size >= thresholds.confirmationFrames &&
            hasConfirmedEvidence &&
            score >= thresholds.provisional
        ) {
            TrafficSignRecognitionState.CONFIRMED
        } else {
            TrafficSignRecognitionState.PROVISIONAL
        }

        val best = matchingTrack.bestCrop.detection.candidate
        val restrictions = matchingTrack.observations
            .flatMap { it.detection.candidate.restrictions }
            .distinct()
        val conditionState = matchingTrack.observations
            .asReversed()
            .firstOrNull { it.detection.candidate.conditionState != TrafficSignConditionState.NONE }
            ?.detection
            ?.candidate
            ?.conditionState
            ?: TrafficSignConditionState.NONE
        val assemblyId = matchingTrack.observations
            .asReversed()
            .firstNotNullOfOrNull { it.detection.candidate.assemblyId }

        return TrafficSignFusionResult(
            state = state,
            candidate = best.copy(
                trackId = matchingTrack.id,
                evidenceFrames = matchingTrack.observations.size,
                assemblyId = assemblyId,
                conditionState = conditionState,
                restrictions = restrictions,
            ),
            fusedScore = fusedScore,
            bestCropBoundingBox = best.boundingBox,
        )
    }

    fun reset() {
        tracks.clear()
        nextTrackNumber = 1L
        lastObservedAtMs = null
    }

    private fun expireTracks(observedAtMs: Long) {
        tracks.removeAll { observedAtMs - it.observations.last().observedAtMs > thresholds.confirmationWindowMs }
    }

    private fun effectiveScore(candidate: TrafficSignCandidate): Double = when (scoreSource) {
        TrafficSignCalibrationOutput.RAW_SCORE -> candidate.rawScore
        TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE -> candidate.calibratedConfidence ?: Double.NaN
    }

    private fun noRecognition() = TrafficSignFusionResult(
        state = TrafficSignRecognitionState.NO_RECOGNITION,
        candidate = null,
        fusedScore = null,
        bestCropBoundingBox = null,
    )

    private data class TimedDetection(
        val observedAtMs: Long,
        val detection: TrafficSignDetection,
    )

    private data class Track(
        val id: String,
        val observations: MutableList<TimedDetection>,
    ) {
        val latest: TrafficSignDetection
            get() = observations.last().detection

        val bestCrop: TimedDetection
            get() = observations.maxWith(
                compareBy<TimedDetection> { it.detection.cropQuality }
                    .thenBy { it.detection.candidate.boundingBox.area },
            )

        fun matches(candidate: TrafficSignCandidate, minimumIou: Double): Boolean {
            val current = latest.candidate
            if (current.semantic != candidate.semantic) return false
            // Assembly IDs link objects within one frame; they are intentionally
            // frame-scoped and therefore cannot be used as temporal track IDs.
            return current.boundingBox.intersectionOverUnion(candidate.boundingBox) >= minimumIou
        }

        fun weightedScore(scoreOf: (TrafficSignCandidate) -> Double): Double {
            val weighted = observations.sumOf { observation ->
                effectiveWeight(observation.detection) * scoreOf(observation.detection.candidate)
            }
            val totalWeight = observations.sumOf { effectiveWeight(it.detection) }
            return weighted / totalWeight
        }

        private fun effectiveWeight(detection: TrafficSignDetection): Double =
            max(MINIMUM_WEIGHT, detection.cropQuality) * max(MINIMUM_WEIGHT, detection.candidate.boundingBox.area)

        private companion object {
            const val MINIMUM_WEIGHT = 1e-6
        }
    }
}

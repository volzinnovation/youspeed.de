package de.youspeed.android.alpha

import kotlin.math.*

/** Additive v1 sidecar; frozen recognition events are unchanged. All times use one capture clock. */
data class TSRApplicabilityScope(val sessionId: String, val bundleId: String, val cameraGeometryId: String,
    val generation: Long, val contextGeneration: Long, val traversalEpoch: Long)
data class TSRApplicabilityBox(val x: Double, val y: Double, val width: Double, val height: Double) {
    val centerX get() = x + width / 2
    val centerY get() = y + height / 2
    val scale get() = sqrt(width * height)
    val valid get() = listOf(x, y, width, height).all { it.isFinite() } && x >= 0 && y >= 0 &&
        width > 0 && height > 0 && x + width <= 1.000001 && y + height <= 1.000001
}
data class TSRApplicabilityCandidate(val candidateId: String, val semanticKey: String, val box: TSRApplicabilityBox,
    val rawScore: Double, val recognitionEligible: Boolean, val assemblyId: String?,
    val recognitionScore: Double? = null, val calibratedConfidence: Double? = null)
data class TSRApplicabilityCorridor(val wayId: String, val headingDeg: Double?, val distanceM: Double?,
    val roadClass: String?, val endpointLinked: Boolean, val turnAngleDeg: Double?)
data class TrafficSignMapContextSnapshot(val snapshotId: String, val capturedAtMs: Double, val scope: TSRApplicabilityScope,
    val wayId: String?, val horizontalAccuracyM: Double?, val courseAccuracyDeg: Double?, val courseDeg: Double?,
    val localTangentDeg: Double?, val matchedStable: Boolean, val roadClass: String?,
    val hypotheses: List<TSRApplicabilityCorridor>, val branches: List<TSRApplicabilityCorridor>, val capabilities: List<String>,
    val cameraHorizontalFovDeg: Double?, val cameraYawDeg: Double?)
data class TSRFrameCandidateBatch(val schemaVersion: Int, val frameId: String, val capturedAtMs: Double,
    val scope: TSRApplicabilityScope, val status: String, val candidates: List<TSRApplicabilityCandidate>,
    val truncated: Boolean, val rawCandidateCount: Int, val modelId: String, val preprocessingId: String,
    val road: TrafficSignMapContextSnapshot?)
data class TSRTrackSample(val frameId: String, val capturedAtMs: Double, val candidate: TSRApplicabilityCandidate)
data class TSRPhysicalTrackSnapshot(val trackId: String, val scope: TSRApplicabilityScope, val samples: List<TSRTrackSample>,
    val visibility: String, val associationAmbiguous: Boolean)
data class TSRApplicabilityDecision(val schemaVersion: Int, val policyVersion: String, val configHash: String,
    val frameId: String, val trackId: String, val scope: TSRApplicabilityScope, val roadSnapshotId: String?,
    val classification: String, val reasons: List<String>, val evidence: List<String>, val imageSupport: Double,
    val displayEligible: Boolean, val immediateEligible: Boolean, val passageEligible: Boolean)
data class TSRApplicabilityDiagnostic(val schemaVersion: Int, val batch: TSRFrameCandidateBatch,
    val tracks: List<TSRPhysicalTrackSnapshot>, val decisions: List<TSRApplicabilityDecision>)

object TSRApplicabilityConfiguration {
    const val policyVersion = "applicability-heuristic-v1"
    const val configHash = "ff87a27c0a2dc643225fad1f34cfd3f131bf00b2e2e5a2b647ab5ed3e81738e3"
    const val defaultMode = "shadow"
    const val maxCandidates = 32
    const val maxTracks = 24
    const val maxHistory = 12
    const val maxTrackAgeMs = 2500.0
    const val maxContextAgeMs = 1500.0
    const val maxGpsAccuracyM = 20.0
    const val maxCourseAccuracyDeg = 25.0
    const val minObservations = 2
    const val associationDistance = 0.18
    const val associationGrowth = 0.35
    const val ambiguityMargin = 0.04
    const val maxScaleRatio = 3.0
    const val minApproachRatio = 1.08
    const val maxLateralSpeed = 0.9
    const val corridorHalfAngleDeg = 35.0
    const val branchMarginDeg = 12.0
    const val maxBranches = 8
    const val maxHypotheses = 8
    const val maxJunctionDistanceM = 100.0
}

/** Deterministic one-to-one association. Uncertain or skipped work never synthesizes loss. */
class TSRPhysicalSignTracker {
    var tracks: List<TSRPhysicalTrackSnapshot> = emptyList(); private set
    private var scope: TSRApplicabilityScope? = null
    private var lastTimestamp = Double.NEGATIVE_INFINITY
    private var recentFrames = listOf<String>()
    private var nextID = 1
    fun reset() { tracks = emptyList(); scope = null; lastTimestamp = Double.NEGATIVE_INFINITY; recentFrames = emptyList(); nextID = 1 }
    fun ingest(batch: TSRFrameCandidateBatch): List<TSRPhysicalTrackSnapshot> {
        if (scope != batch.scope) { reset(); scope = batch.scope }
        if (!batch.capturedAtMs.isFinite() || batch.capturedAtMs <= lastTimestamp || batch.frameId in recentFrames) return tracks
        lastTimestamp = batch.capturedAtMs
        recentFrames = (recentFrames + batch.frameId).takeLast(64)
        tracks = tracks.filter { batch.capturedAtMs - (it.samples.lastOrNull()?.capturedAtMs ?: 0.0) <= TSRApplicabilityConfiguration.maxTrackAgeMs }
        if (batch.status != "analyzed") { tracks = tracks.map { it.copy(visibility = "uncertain") }; return tracks }
        val candidates = batch.candidates.filter { it.box.valid && it.rawScore.isFinite() }.sortedBy { it.candidateId }.take(TSRApplicabilityConfiguration.maxCandidates)
        data class Edge(val cost: Double, val track: Int, val candidate: Int)
        val edges = mutableListOf<Edge>()
        for ((ti, track) in tracks.withIndex()) {
            val last = track.samples.lastOrNull() ?: continue
            val dt = (batch.capturedAtMs - last.capturedAtMs) / 1000
            if (dt <= 0) continue
            var vx = 0.0; var vy = 0.0
            if (track.samples.size >= 2) {
                val previous = track.samples[track.samples.size - 2]
                val elapsed = (last.capturedAtMs - previous.capturedAtMs) / 1000
                if (elapsed > 0) {
                    vx = ((last.candidate.box.centerX - previous.candidate.box.centerX) / elapsed).coerceIn(-0.9, 0.9)
                    vy = ((last.candidate.box.centerY - previous.candidate.box.centerY) / elapsed).coerceIn(-0.9, 0.9)
                }
            }
            for ((ci, candidate) in candidates.withIndex()) {
                val ratio = candidate.box.scale / last.candidate.box.scale
                if (ratio < 1 / TSRApplicabilityConfiguration.maxScaleRatio || ratio > TSRApplicabilityConfiguration.maxScaleRatio) continue
                val distance = hypot(candidate.box.centerX - last.candidate.box.centerX - vx * dt, candidate.box.centerY - last.candidate.box.centerY - vy * dt)
                if (distance > min(0.55, TSRApplicabilityConfiguration.associationDistance + TSRApplicabilityConfiguration.associationGrowth * dt)) continue
                val semanticPenalty = if (candidate.semanticKey == last.candidate.semanticKey) 0.0 else 0.08
                edges += Edge(distance + 0.05 * abs(ln(ratio)) + semanticPenalty, ti, ci)
            }
        }
        edges.sortWith(compareBy<Edge> { it.cost }.thenBy { it.track }.thenBy { it.candidate })
        val usedTracks = mutableSetOf<Int>(); val usedCandidates = mutableSetOf<Int>(); val ambiguousCandidates = mutableSetOf<Int>()
        val updated = tracks.map { it.copy(visibility = if (batch.truncated) "uncertain" else "absent", associationAmbiguous = false) }.toMutableList()
        for (edge in edges) {
            if (edge.track in usedTracks || edge.candidate in usedCandidates) continue
            val ambiguous = edges.any { (it.track == edge.track && it.candidate != edge.candidate || it.candidate == edge.candidate && it.track != edge.track) && abs(it.cost - edge.cost) < TSRApplicabilityConfiguration.ambiguityMargin }
            if (ambiguous) {
                ambiguousCandidates += edge.candidate
                updated[edge.track] = updated[edge.track].copy(visibility = "uncertain", associationAmbiguous = true)
                continue
            }
            usedTracks += edge.track; usedCandidates += edge.candidate
            val track = updated[edge.track]
            updated[edge.track] = track.copy(samples = (track.samples + TSRTrackSample(batch.frameId, batch.capturedAtMs, candidates[edge.candidate])).filter { batch.capturedAtMs - it.capturedAtMs <= TSRApplicabilityConfiguration.maxTrackAgeMs }.takeLast(TSRApplicabilityConfiguration.maxHistory), visibility = "observed")
        }
        for ((ci, candidate) in candidates.withIndex()) {
            if (ci in usedCandidates || ci in ambiguousCandidates) continue
            if (updated.size >= TSRApplicabilityConfiguration.maxTracks) break
            updated += TSRPhysicalTrackSnapshot("track-${nextID++}", batch.scope, listOf(TSRTrackSample(batch.frameId, batch.capturedAtMs, candidate)), "observed", false)
        }
        tracks = updated.toList(); return tracks
    }
}

object TSRApplicabilityPolicy {
    fun signedAngle(angle: Double): Double {
        var a = angle % 360
        if (a >= 180) a -= 360
        if (a < -180) a += 360
        return a
    }
    fun evaluate(track: TSRPhysicalTrackSnapshot, batch: TSRFrameCandidateBatch): TSRApplicabilityDecision {
        val reasons = mutableListOf<String>(); val evidence = mutableListOf<String>()
        var classification = "UNKNOWN"; var support = 0.0
        val road = batch.road
        fun result(): TSRApplicabilityDecision {
            val eligible = classification == "LIKELY_EGO_CORRIDOR"
            return TSRApplicabilityDecision(1, TSRApplicabilityConfiguration.policyVersion, TSRApplicabilityConfiguration.configHash,
                batch.frameId, track.trackId, batch.scope, road?.snapshotId, classification, reasons.toList(), evidence.toList(), support, eligible, eligible, eligible)
        }
        val last = track.samples.lastOrNull()
        if (track.scope != batch.scope || batch.status != "analyzed" || batch.truncated || track.visibility != "observed" || track.associationAmbiguous ||
            last == null || last.frameId != batch.frameId || !last.candidate.box.valid || !last.candidate.recognitionEligible) {
            reasons += "unqualified_observation"; return result()
        }
        if (road == null || road.scope != batch.scope || road.wayId == null) { reasons += "missing_road_context"; return result() }
        val age = batch.capturedAtMs - road.capturedAtMs
        if (!(age >= 0 && age <= TSRApplicabilityConfiguration.maxContextAgeMs)) { reasons += "stale_road_context"; return result() }
        val accuracy = road.horizontalAccuracyM; val courseAccuracy = road.courseAccuracyDeg; val course = road.courseDeg; val tangent = road.localTangentDeg
        if (!road.matchedStable || accuracy == null || !accuracy.isFinite() || accuracy < 0 || accuracy > TSRApplicabilityConfiguration.maxGpsAccuracyM || courseAccuracy == null ||
            !courseAccuracy.isFinite() || courseAccuracy < 0 || courseAccuracy > TSRApplicabilityConfiguration.maxCourseAccuracyDeg || course == null || !course.isFinite() || tangent == null || !tangent.isFinite()) {
            reasons += "unreliable_road_context"; return result()
        }
        evidence += "local_road_geometry"
        val fov = road.cameraHorizontalFovDeg; val yaw = road.cameraYawDeg
        if (fov == null || !fov.isFinite() || fov <= 10 || fov >= 170 || yaw == null || !yaw.isFinite()) { reasons += "camera_calibration_unavailable"; return result() }
        evidence += "calibrated_image_bearing"
        val bearing = atan((last.candidate.box.centerX * 2 - 1) * tan(fov * PI / 360)) * 180 / PI + yaw
        var egoAngle = signedAngle(tangent - course)
        if (abs(egoAngle) > 90) egoAngle = signedAngle(egoAngle + 180)
        val residual = abs(signedAngle(bearing - egoAngle))
        support = max(0.0, 1 - residual / 70)
        val nearbyBranches = road.branches.filter { (it.distanceM ?: Double.POSITIVE_INFINITY) <= TSRApplicabilityConfiguration.maxJunctionDistanceM }
        if ("endpoint_links" !in road.capabilities || "local_tangent" !in road.capabilities || "context_truncated" in road.capabilities) { reasons += "missing_topology_capability"; return result() }
        val branchIds = nearbyBranches.map { it.wayId }.toSet()
        for (alternative in nearbyBranches + road.hypotheses.filter { it.wayId != road.wayId && it.wayId !in branchIds }) {
            val heading = alternative.headingDeg
            if (heading == null || !heading.isFinite()) { reasons += "unknown_competing_corridor"; return result() }
            var angle = signedAngle(heading - course)
            if (!alternative.endpointLinked && abs(angle) > 90) angle = signedAngle(angle + 180)
            val alternativeResidual = abs(signedAngle(bearing - angle))
            if (alternativeResidual + TSRApplicabilityConfiguration.branchMarginDeg < residual && alternative.endpointLinked) { classification = "LIKELY_BRANCH"; reasons += "branch_bearing_better_supported"; return result() }
            if (alternativeResidual <= TSRApplicabilityConfiguration.corridorHalfAngleDeg || abs(alternativeResidual - residual) < TSRApplicabilityConfiguration.branchMarginDeg) { reasons += "competing_corridors"; return result() }
        }
        evidence += "bounded_corridor_comparison"
        if (track.samples.size < TSRApplicabilityConfiguration.minObservations) { reasons += "insufficient_independent_observations"; return result() }
        if (track.samples.any { it.candidate.semanticKey != last.candidate.semanticKey }) { reasons += "semantic_disagreement"; return result() }
        val first = track.samples.first(); val elapsed = (last.capturedAtMs - first.capturedAtMs) / 1000
        if (!(elapsed > 0 && last.candidate.box.scale / first.candidate.box.scale >= TSRApplicabilityConfiguration.minApproachRatio && abs(last.candidate.box.centerX - first.candidate.box.centerX) / elapsed <= TSRApplicabilityConfiguration.maxLateralSpeed)) {
            reasons += "insufficient_coherent_approach"; return result()
        }
        evidence += "independent_approach"
        if (residual > TSRApplicabilityConfiguration.corridorHalfAngleDeg) { reasons += "outside_supported_corridor"; return result() }
        classification = "LIKELY_EGO_CORRIDOR"; reasons += "coherent_approach_unique_corridor"; return result()
    }
}

object TSRApplicabilityAuthority {
    fun allows(decision: TSRApplicabilityDecision?, scope: TSRApplicabilityScope, frameId: String, trackId: String,
        sink: String, mode: String = TSRApplicabilityConfiguration.defaultMode): Boolean {
        if (mode == "shadow") return true
        if (mode != "enforce" || decision == null || decision.schemaVersion != 1 || decision.scope != scope || decision.frameId != frameId || decision.trackId != trackId ||
            decision.policyVersion != TSRApplicabilityConfiguration.policyVersion || decision.configHash != TSRApplicabilityConfiguration.configHash || decision.classification != "LIKELY_EGO_CORRIDOR") return false
        return when (sink) { "display" -> decision.displayEligible; "immediate" -> decision.immediateEligible; "passage" -> decision.passageEligible; else -> false }
    }
}

data class TSRMapGeometry(val wayId: String?, val localTangentDeg: Double?, val roadClass: String?,
    val hypotheses: List<TSRApplicabilityCorridor>, val branches: List<TSRApplicabilityCorridor>, val capabilities: List<String>) {
    fun snapshot(scope: TSRApplicabilityScope, fixTimeMs: Double, accuracyM: Double?, courseDeg: Double?, courseAccuracyDeg: Double?, stable: Boolean) =
        TrafficSignMapContextSnapshot("${scope.bundleId}:${scope.traversalEpoch}:$fixTimeMs", fixTimeMs, scope,
            wayId, accuracyM, courseAccuracyDeg, courseDeg, localTangentDeg, stable, roadClass, hypotheses.toList(), branches.toList(), capabilities.toList(), null, null)
}

data class TSRMapFix(val geometry: TSRMapGeometry, val timestampMs: Double, val accuracyM: Double?,
    val courseDeg: Double?, val courseAccuracyDeg: Double?, val stable: Boolean) {
    fun snapshot(scope: TSRApplicabilityScope) = geometry.snapshot(scope, timestampMs, accuracyM, courseDeg, courseAccuracyDeg, stable)
}

class TSRApplicabilitySession {
    private val tracker = TSRPhysicalSignTracker()
    private val decisionsByTrack = mutableMapOf<String, TSRApplicabilityDecision>()
    var diagnostic: TSRApplicabilityDiagnostic? = null; private set
    fun reset() { tracker.reset(); decisionsByTrack.clear(); diagnostic = null }
    fun evaluate(batch: TSRFrameCandidateBatch): TSRApplicabilityDiagnostic {
        val tracks = tracker.ingest(batch)
        val decisions = tracks.map { TSRApplicabilityPolicy.evaluate(it, batch) }
        decisionsByTrack.entries.removeAll { (key, value) -> tracks.none { it.trackId == key && it.scope == value.scope } }
        tracks.zip(decisions).filter { it.first.visibility == "observed" }.forEach { (track, decision) -> decisionsByTrack[track.trackId] = decision }
        return TSRApplicabilityDiagnostic(1, batch, tracks, decisions).also { diagnostic = it }
    }
    fun passageDecision(trackId: String): TSRApplicabilityDecision? = decisionsByTrack[trackId]
    fun canConsumePassage(activeTrackId: String?, selectedTrackId: String?, mode: String): Boolean {
        if (mode == "shadow") return true
        val current = diagnostic ?: return false
        if (mode != "enforce" || current.batch.status != "analyzed" || current.batch.truncated) return false
        if (activeTrackId == null) return selectedTrackId != null
        val track = current.tracks.firstOrNull { it.trackId == activeTrackId } ?: return false
        if (track.visibility == "observed") return selectedTrackId == activeTrackId && decisionsByTrack[activeTrackId]?.passageEligible == true
        return track.visibility == "absent" && decisionsByTrack[activeTrackId]?.passageEligible == true
    }
}

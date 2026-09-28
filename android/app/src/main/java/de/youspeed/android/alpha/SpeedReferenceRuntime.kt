package de.youspeed.android.alpha

import java.util.UUID

/** Thread-safe adapter for already interpreted pipeline/bundle inputs. No image or lane inference. */
internal class SpeedReferenceRuntime(model: SpeedLimitReferenceModel?, private val now: () -> Double = { System.nanoTime() / 1e9 }) {
    private val machine = model?.let(::SpeedReferenceMachine)
    private var session = UUID.randomUUID().toString()
    private var sequence = 0
    private var origin = now()
    private var meters = 0.0
    private val withdrawnCameraEvidence = mutableSetOf<String>()
    private val cameraOrigins = mutableMapOf<String, Pair<Double, Double>>()
    private var way: String? = null
    private var road: String? = null
    private var relations = emptySet<String>()
    private var direction = "unknown"
    private var departure: Pair<String, Double>? = null
    var lastEventReason = ""; private set
    val elapsedSeconds: Double get() = synchronized(this) { machine?.time ?: 0.0 }
    val traveledMeters: Double get() = synchronized(this) { machine?.distance ?: 0.0 }
    var onTransition: ((SpeedReferenceOutput) -> Unit)? = null
    init { reset() }
    @Synchronized fun reset() {
        session = UUID.randomUUID().toString(); sequence = 0; origin = now(); meters = 0.0
        withdrawnCameraEvidence.clear()
        cameraOrigins.clear(); way = null; road = null; relations = emptySet(); departure = null; direction = "unknown"
        send("reset")
    }
    @Synchronized fun output() = machine?.project()
    @Synchronized fun voice() = machine?.claims?.get("voice")?.value
    val policyIdentity: String get() = machine?.let { "${it.model.version}:${it.model.sha256}" } ?: "invalid_policy"
    private fun send(kind: String, fields: Map<String, Any?> = emptyMap()): SpeedReferenceOutput? {
        val m = machine ?: return null
        sequence++
        val event = mutableMapOf<String, Any?>("kind" to kind, "session_id" to session, "sequence" to sequence,
            "elapsed_s" to if (kind == "reset") 0.0 else maxOf(m.time, now() - origin), "distance_m" to meters, "generation" to m.generation)
        event.putAll(fields)
        lastEventReason = fields["reason"] as? String ?: kind
        val before = m.project()
        val result = m.step(event)
        if (before.state != result.state || before.value != result.value || before.evidenceId != result.evidenceId || result.expiryReasons.isNotEmpty() || result.transition == "T08") onTransition?.invoke(result)
        return result
    }
    @Synchronized fun tick(distance: Double = 0.0) { if (distance.isFinite() && distance >= 0) meters += distance; send("tick") }
    private fun applicability() = mapOf("status" to "applicable", "context_revision" to (machine?.applicabilityRevision ?: 0), "conditions" to emptyList<Any>())
    @Synchronized fun voice(id: String, value: SpeedReferenceValue) { tick(); send("voice", mapOf("id" to id, "value" to value.json, "verified" to true)) }
    @Synchronized fun bundle(id: String, value: SpeedReferenceValue?, evaluatedApplicability: Map<String, Any?>? = null) {
        if (value == null) send("bundle_missing") else send("bundle", mapOf("id" to id, "value" to value.json, "verified" to true, "applicability" to (evaluatedApplicability ?: applicability())))
    }
    @Synchronized fun camera(id: String, value: SpeedReferenceValue, enclosing: Boolean = false, evaluatedApplicability: Map<String, Any?>? = null) {
        tick()
        val first = cameraOrigins.getOrPut(id) { (machine?.time ?: 0.0) to meters }
        send(if (enclosing) "camera_context" else "camera", mapOf("id" to id, "value" to value.json, "verified" to true,
            "applicability" to (evaluatedApplicability ?: applicability()), "observed_elapsed_s" to first.first, "observed_distance_m" to first.second,
            "area_verified" to enclosing, "scope_kind" to "zone"))
    }
    @Synchronized fun applicabilityContextChanged(revision: Int) { send("applicability_context_changed", mapOf("next_revision" to revision)) }
    @Synchronized fun pipelineAuthorityWithdrawn(evidenceId: String) {
        if (withdrawnCameraEvidence.add(evidenceId)) send("camera_scope_invalidated")
    }
    @Synchronized fun dismissCamera() { send("camera_dismissed") }
    @Synchronized fun boundary(reason: String) { tick(); send("context_confirmed", mapOf("id" to UUID.randomUUID().toString(), "confirmed" to true, "reason" to reason)); departure = null }
    @Synchronized fun context(nextWay: String?, nextRoad: String?, nextRelations: Set<String>, nextDirection: String, stable: Boolean) {
        tick()
        if (nextWay.isNullOrBlank()) { send("context_missing"); return }
        val reversed = way == nextWay && direction != "unknown" && nextDirection != "unknown" && direction != nextDirection
        val continues = !reversed && (way == null || way == nextWay || (road != null && road == nextRoad) || relations.intersect(nextRelations).isNotEmpty())
        if (continues) { send("context_restored", mapOf("verified" to true)); departure = null }
        else {
            val candidate = "${nextRoad ?: nextWay}|$nextDirection"
            if (departure?.first != candidate) departure = candidate to (machine?.time ?: 0.0)
            send("context_pending")
            val m = machine ?: return
            if (!stable || m.time - departure!!.second < m.limit("road_departure_confirmation_s")) return
            boundary(if (reversed) "direction_reversal" else "road_relation_exit")
        }
        way = nextWay; road = nextRoad; relations = nextRelations; direction = nextDirection
    }
}

internal fun TrafficSignResolvedLimit.referenceValue(): SpeedReferenceValue? = when(kind) {
    TrafficSignResolvedLimitKind.NUMERIC -> speedKmh?.let { SpeedReferenceValue("numeric", it) }
    TrafficSignResolvedLimitKind.WALK -> SpeedReferenceValue("walk")
    TrafficSignResolvedLimitKind.UNLIMITED -> SpeedReferenceValue("unlimited")
    else -> null
}
internal fun SpeedReferenceOutput.effective(): EffectiveSpeedLimit {
    val source = when(state) { "VOICE" -> EffectiveSpeedLimitSource.LOCAL_CORRECTION; "CAMERA" -> EffectiveSpeedLimitSource.CAMERA; "BUNDLE" -> EffectiveSpeedLimitSource.BUNDLE; "LAST_KNOWN" -> EffectiveSpeedLimitSource.LAST_KNOWN; else -> EffectiveSpeedLimitSource.NONE }
    val resolution = when(value?.kind) { "numeric" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, value.kmh); "walk" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.WALK); "unlimited" -> TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNLIMITED); else -> null }
    return EffectiveSpeedLimit(resolution, source, "reference_${state.lowercase()}_$transition", cameraEvidence = state == "CAMERA", isUserCorrection = state == "VOICE")
}

/** Caller holds trafficSignStateLock. Dismissal never disables recognition of new signs. */
internal class VisionDismissalGate {
    private var cutoff: java.time.Instant? = null
    private val tracks = mutableSetOf<String>()
    fun dismiss(at: java.time.Instant, ids: List<String>) {
        cutoff = at
        tracks.addAll(ids)
    }
    fun permits(track: String?, observedAt: java.time.Instant): Boolean {
        if (cutoff?.let { observedAt <= it } == true) {
            track?.let { tracks.add(it) }
            return false
        }
        return track == null || track !in tracks
    }
}

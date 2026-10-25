package de.youspeed.android.alpha

import java.util.UUID

internal data class SpeedReferenceBundleFix(val sourceTime:Double,val ageSeconds:Double,val accuracyMetres:Double,val matchDistanceMetres:Double,val applicable:Boolean)

/** Observation of one offer; never grants authority or retries withheld evidence. */
internal data class SpeedReferenceCameraReceipt(
    val offeredId: String,
    val offeredValue: SpeedReferenceValue,
    val offeredKind: String,
    val before: SpeedReferenceOutput,
    val after: SpeedReferenceOutput,
    val pendingContextBefore: Boolean,
    val pendingContextAfter: Boolean,
) {
    val diagnosticFields: Map<String, Any?> get() = mapOf(
        "offeredId" to offeredId, "offeredValue" to offeredValue.json, "offeredKind" to offeredKind,
        "before" to before.diagnosticFields(), "after" to after.diagnosticFields(),
        "pendingContextBefore" to pendingContextBefore, "pendingContextAfter" to pendingContextAfter,
        "gapBefore" to null, "seenBefore" to null, "gateDiagnosticAvailability" to "pending_context_only",
    )
    private fun SpeedReferenceOutput.diagnosticFields(): Map<String, Any?> = mapOf(
        "state" to state, "value" to value?.json, "source" to source, "evidenceId" to evidenceId,
        "current" to current, "generation" to generation, "applicabilityRevision" to applicabilityRevision,
        "transition" to transition, "expiryReasons" to expiryReasons, "rejection" to rejection,
    )
}

/** Thread-safe adapter for already interpreted pipeline/bundle inputs. No image or lane inference. */
internal class SpeedReferenceRuntime(model: SpeedLimitReferenceModel?, private val now: () -> Double = { System.nanoTime() / 1e9 }) {
    private val machine = model?.let(::SpeedReferenceMachine)
    private var session = UUID.randomUUID().toString()
    private var sequence = 0
    private var origin = now()
    private var meters = 0.0
    private val withdrawnCameraEvidence = mutableSetOf<String>()
    private val cameraOrigins = mutableMapOf<String, Pair<Double, Double>>()
    private var bundleEnvelope:Pair<String,Map<String,Any?>>?=null
    private val cameraEnvelopes=mutableMapOf<String,Map<String,Any?>>()
    private var way: String? = null
    private var road: String? = null
    private var relations = emptySet<String>()
    private var direction = "unknown"
    private val acceptedDirections = linkedMapOf<String, String>()
    private data class Departure(
        val way: String,
        val road: String?,
        val relations: Set<String>,
        val direction: String,
        val startedAt: Double,
        val reason: String,
        val verifiedFixCount: Int = 0,
        val lastVerifiedFixTime: Double? = null,
    ) {
        fun continues(nextWay: String, nextRoad: String?, nextRelations: Set<String>, nextDirection: String): Boolean {
            // Forward/reverse are relative to an OSM way's digitization. They
            // cannot be compared across adjacent ways on the same road.
            val reversed = way == nextWay && direction != "unknown" && nextDirection != "unknown" && direction != nextDirection
            return !reversed && (way == nextWay || (road != null && road == nextRoad) || relations.intersect(nextRelations).isNotEmpty())
        }
        fun observed(nextWay: String, nextRoad: String?, nextRelations: Set<String>, nextDirection: String) =
            copy(way = nextWay, road = nextRoad, relations = nextRelations,
                direction = if (way == nextWay && nextDirection == "unknown") direction else nextDirection)
    }
    private var departure: Departure? = null
    var lastEventReason = ""; private set
    val elapsedSeconds: Double get() = synchronized(this) { machine?.time ?: 0.0 }
    val traveledMeters: Double get() = synchronized(this) { machine?.distance ?: 0.0 }
    var onTransition: ((SpeedReferenceOutput) -> Unit)? = null
    init { reset() }
    @Synchronized fun reset() {
        session = UUID.randomUUID().toString(); sequence = 0; origin = now(); meters = 0.0
        withdrawnCameraEvidence.clear()
        cameraOrigins.clear();cameraEnvelopes.clear();bundleEnvelope=null; way = null; road = null; relations = emptySet(); departure = null; direction = "unknown"; acceptedDirections.clear()
        send("reset")
    }
    @Synchronized fun output() = machine?.project()
    @Synchronized fun cameraEvidenceIds(): List<String> = listOf("camera", "camera_context").mapNotNull { machine?.claims?.get(it)?.id }
    @Synchronized fun ordinaryCameraEvidenceId():String? = machine?.claims?.get("camera")?.id
    @Synchronized fun ordinaryCameraOrigin():Pair<Double,Double>? = machine?.claims?.get("camera")?.let {it.time to it.distance}
    @Synchronized fun contextPending(): Boolean = machine?.pendingContext == true
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
    private fun rebased(envelope:Map<String,Any?>)=envelope+mapOf("context_revision" to (machine?.applicabilityRevision ?: 0))
    @Synchronized internal fun bundleApplicability():Map<String,Any?>?=bundleEnvelope?.second?.let(::rebased)
    @Synchronized fun voice(id: String, value: SpeedReferenceValue) { tick(); send("voice", mapOf("id" to id, "value" to value.json, "verified" to true)) }
    @Synchronized fun bundle(id: String, value: SpeedReferenceValue?, evaluatedApplicability: Map<String, Any?>? = null) {
        if (value == null) {bundleEnvelope=null;send("bundle_missing")} else {
            val envelope=rebased(evaluatedApplicability ?: bundleEnvelope?.takeIf {it.first==id}?.second ?: applicability())
            bundleEnvelope=id to envelope
            send("bundle", mapOf("id" to id, "value" to value.json, "verified" to true, "applicability" to envelope))
        }
    }
    @Synchronized fun camera(id: String, value: SpeedReferenceValue, enclosing: Boolean = false, evaluatedApplicability: Map<String, Any?>? = null,
        originalElapsedSeconds:Double?=null,originalDistanceMeters:Double?=null): SpeedReferenceCameraReceipt? {
        tick()
        if((originalElapsedSeconds==null)!=(originalDistanceMeters==null)) return null
        if(originalElapsedSeconds!=null && (!originalElapsedSeconds.isFinite() || originalElapsedSeconds<0 || originalElapsedSeconds>(machine?.time ?: 0.0) ||
                originalDistanceMeters?.isFinite()!=true || originalDistanceMeters<0 || originalDistanceMeters>meters)) return null
        val first = cameraOrigins.getOrPut(id) { (originalElapsedSeconds ?: (machine?.time ?: 0.0)) to (originalDistanceMeters ?: meters) }
        // Capture after the existing tick, immediately before the unchanged offer.
        val before = machine?.project()
        val pendingBefore = machine?.pendingContext
        val kind = if (enclosing) "camera_context" else "camera"
        val envelope=rebased(evaluatedApplicability ?: cameraEnvelopes[id] ?: applicability())
        val after = send(kind, mapOf("id" to id, "value" to value.json, "verified" to true,
            "applicability" to envelope, "observed_elapsed_s" to first.first, "observed_distance_m" to first.second,
            "area_verified" to enclosing, "scope_kind" to "zone"))
        if(machine?.claims?.get(kind)?.id==id) cameraEnvelopes[id]=envelope
        return if (before != null && after != null && pendingBefore != null)
            SpeedReferenceCameraReceipt(id, value, kind, before, after, pendingBefore, machine!!.pendingContext)
        else null
    }
    /** Reevaluate one producer's condition using existing applicability events.
     * Other currently valid registers retain their evidence IDs and origins.
     * Voice-suppressed historical camera evidence is never cached or restored. */
    @Synchronized fun reevaluateCamera(id:String,value:SpeedReferenceValue?,originalElapsedSeconds:Double,originalDistanceMeters:Double,conditionEvidence:Map<String,Any?> = emptyMap()):SpeedReferenceCameraReceipt? {
        tick();val current=machine ?: return null
        if(current.claims["voice"]!=null) return null
        if(value==null && current.claims["camera"]?.id!=id && current.claims["camera_context"]?.id!=id) return null
        val retained=current.claims.filterKeys {it in setOf("camera","camera_context","bundle")}.filterValues {it.id!=id}.toMap()
        send("applicability_context_changed",mapOf("next_revision" to current.applicabilityRevision+1))
        retained["bundle"]?.let {bundle(it.id,it.value)}
        retained["camera_context"]?.let {camera(it.id,it.value,enclosing=true)}
        retained["camera"]?.let {camera(it.id,it.value,originalElapsedSeconds=it.time,originalDistanceMeters=it.distance)}
        return value?.let {camera(id,it,evaluatedApplicability=applicability()+mapOf("conditions" to conditionEvidence),
            originalElapsedSeconds=originalElapsedSeconds,originalDistanceMeters=originalDistanceMeters)}
    }
    @Synchronized fun applicabilityContextChanged(revision: Int) { send("applicability_context_changed", mapOf("next_revision" to revision)) }
    @Synchronized fun pipelineAuthorityWithdrawn(evidenceId: String) {
        if (withdrawnCameraEvidence.add(evidenceId)) send("camera_scope_invalidated")
    }
    @Synchronized fun dismissCamera() { send("camera_dismissed") }
    @Synchronized fun boundary(reason: String) { tick(); send("context_confirmed", mapOf("id" to UUID.randomUUID().toString(), "confirmed" to true, "reason" to reason)); departure = null; acceptedDirections.clear() }
    @Synchronized fun context(nextWay: String?, nextRoad: String?, nextRelations: Set<String>, nextDirection: String, stable: Boolean, bundleFix:SpeedReferenceBundleFix?=null) {
        tick()
        if (nextWay.isNullOrBlank()) {
            departure=departure?.copy(verifiedFixCount=0,lastVerifiedFixTime=null)
            send("context_missing"); return
        }
        var acceptedDirection = nextDirection
        val comparisonDirection = if (nextDirection == "unknown" && departure?.way == nextWay) departure!!.direction else nextDirection
        val originalDirection = acceptedDirections[nextWay] ?: if (way == nextWay) direction else "unknown"
        val reversed = originalDirection != "unknown" && comparisonDirection != "unknown" && originalDirection != comparisonDirection
        val returningOriginalDirection = originalDirection != "unknown" && nextDirection == originalDirection
        val pendingReversal = departure?.reason == "direction_reversal" && !returningOriginalDirection
        val continues = !reversed && !pendingReversal && (way == null || way == nextWay || (road != null && road == nextRoad) || relations.intersect(nextRelations).isNotEmpty())
        if (continues) { send("context_restored", mapOf("verified" to true)); departure = null }
        else {
            val candidate = departure
            departure = if (candidate?.continues(nextWay, nextRoad, nextRelations, nextDirection) == true)
                candidate.observed(nextWay, nextRoad, nextRelations, nextDirection)
            else Departure(nextWay, nextRoad, nextRelations, nextDirection, machine?.time ?: 0.0,
                if (reversed) "direction_reversal" else "road_relation_exit")
            send("context_pending")
            val m = machine ?: return
            val fix=bundleFix
            if(stable && fix!=null && fix.applicable && fix.sourceTime.isFinite() && fix.sourceTime>=0 &&
                fix.ageSeconds.isFinite() && fix.ageSeconds in 0.0..m.limit("verified_bundle_max_fix_age_s") &&
                fix.accuracyMetres.isFinite() && fix.accuracyMetres in 0.0..m.limit("verified_bundle_max_accuracy_m") &&
                fix.matchDistanceMetres.isFinite() && fix.matchDistanceMetres in 0.0..m.limit("verified_bundle_max_match_distance_m")) {
                val last=departure!!.lastVerifiedFixTime
                if(last==null || fix.sourceTime>last) departure=departure!!.copy(
                    verifiedFixCount=if(last!=null && fix.sourceTime-last<=m.limit("verified_bundle_max_fix_gap_s")) departure!!.verifiedFixCount+1 else 1,
                    lastVerifiedFixTime=fix.sourceTime)
            } else departure=departure!!.copy(verifiedFixCount=0,lastVerifiedFixTime=null)
            val verifiedBundle=departure!!.reason=="road_relation_exit" && departure!!.verifiedFixCount>=m.limit("verified_bundle_confirmation_fixes")
            if (!stable || (!verifiedBundle && m.time - departure!!.startedAt < m.limit("road_departure_confirmation_s"))) return
            if (departure!!.reason == "direction_reversal" && nextDirection == "unknown") return
            acceptedDirection = departure!!.direction
            boundary(departure!!.reason)
        }
        if (way != nextWay || acceptedDirection != "unknown") direction = acceptedDirection
        way = nextWay; road = nextRoad; relations = nextRelations
        if (stable && acceptedDirection != "unknown") {
            acceptedDirections[nextWay] = acceptedDirection
            if (acceptedDirections.size > 128) acceptedDirections.remove(acceptedDirections.keys.first())
        }
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

package de.youspeed.android.alpha

internal data class SpeedReferenceValue(val kind: String, val kmh: Int? = null) {
    val json: Map<String, Any?> get() = if (kind == "numeric") mapOf("kind" to kind, "kmh" to kmh) else mapOf("kind" to kind)
}
internal data class SpeedReferenceOutput(
    val state: String, val value: SpeedReferenceValue?, val source: String?, val evidenceId: String?,
    val current: Boolean, val generation: Int, val applicabilityRevision: Int, val transition: String,
    val expiryReasons: List<String>, val rejection: String? = null,
) { val baselineKmh: Int? get() = if (current && value?.kind == "numeric") value.kmh else null }

/** Deterministic interpreter of the shared guard/action vocabulary and transition table. */
internal class SpeedReferenceMachine(val model: SpeedLimitReferenceModel) {
    data class Claim(val id: String, val value: SpeedReferenceValue, val source: String, val time: Double, val distance: Double)
    val claims = mutableMapOf<String, Claim>()
    private var lastKnown: Claim? = null
    var generation = 0; private set
    var applicabilityRevision = 0; private set
    var pendingContext = false; private set
    private var gap: Pair<Double, Double>? = null
    private val seen = mutableSetOf<Triple<String, String?, Int?>>()
    private val origins = mutableMapOf<String, Pair<Double, Double>>()
    private var session: String? = null
    private var sequence = -1
    var time = 0.0; private set
    var distance = 0.0; private set
    fun limit(name: String) = ((model.policy["limits"] as Map<*, *>)[name] as Number).toDouble()
    private fun number(x: Any?): Double? = (x as? Number)?.toDouble()?.takeIf { it.isFinite() && it >= 0 }
    private fun integer(x: Any?): Int? = number(x)?.takeIf { it % 1.0 == 0.0 && it < Int.MAX_VALUE }?.toInt()
    private fun value(e: Map<String, Any?>): SpeedReferenceValue? {
        val v = e["value"] as? Map<*, *> ?: return null
        val kind = v["kind"] as? String ?: return null
        if (kind in setOf("walk", "unlimited") && v.size == 1) return SpeedReferenceValue(kind)
        val domain = model.policy["value_domain"] as Map<*, *>
        val n = integer(v["kmh"])
        return if (kind == "numeric" && v.size == 2 && n != null && n >= (domain["numeric_min_kmh"] as Number).toInt() && n <= (domain["numeric_max_kmh"] as Number).toInt()) SpeedReferenceValue(kind, n) else null
    }
    private fun key(e: Map<String, Any?>): Triple<String, String?, Int?> {
        val kind = e["kind"] as String
        val revision = if (kind in setOf("camera", "camera_context")) integer((e["applicability"] as? Map<*, *>)?.get("context_revision")) else null
        return Triple(kind, e["id"] as? String, revision)
    }
    private fun applicable(e: Map<String, Any?>): Boolean {
        val a = e["applicability"] as? Map<*, *> ?: return false
        return a["status"] == "applicable" && integer(a["context_revision"]) == applicabilityRevision
    }
    private fun validate(e: Map<String, Any?>): String? {
        val kind = e["kind"] as? String ?: return "unknown_event"
        if (!(model.policy["events"] as Map<*, *>).containsKey(kind)) return "unknown_event"
        val s = (e["session_id"] as? String)?.takeIf { it.isNotEmpty() } ?: return "invalid_session"
        val seq = integer(e["sequence"]) ?: return "invalid_sequence"
        val t = number(e["elapsed_s"]) ?: return "invalid_progress"
        val d = number(e["distance_m"]) ?: return "invalid_progress"
        if (kind == "reset") return when { s == session -> "duplicate_session"; t != 0.0 || d != 0.0 -> "invalid_session_origin"; else -> null }
        if (s != session) return "wrong_session"
        if (seq <= sequence) return "out_of_order"
        if (t < time || d < distance) return "non_monotonic_progress"
        if (kind != "tick" && integer(e["generation"]) == null) return "invalid_generation"
        if (kind in setOf("voice", "camera", "camera_context", "bundle", "context_confirmed") && (e["id"] as? String).isNullOrEmpty()) return "missing_evidence_id"
        if (kind in setOf("voice", "camera", "camera_context", "bundle") && value(e) == null) return "invalid_value"
        if (kind in setOf("camera", "camera_context", "bundle")) {
            val a = e["applicability"] as? Map<*, *> ?: return "invalid_applicability_envelope"
            if (a["status"] !in setOf("applicable", "inapplicable", "unresolved") || integer(a["context_revision"]) == null || (a["conditions"] !is List<*> && a["conditions"] !is Map<*, *>)) return "invalid_applicability_envelope"
        }
        if (kind == "camera") {
            val t0 = number(e["observed_elapsed_s"]) ?: return "invalid_evidence_origin"
            val d0 = number(e["observed_distance_m"]) ?: return "invalid_evidence_origin"
            if (t0 > t || d0 > d) return "invalid_evidence_origin"
            val previous = origins[e["id"] as String]
            if (previous != null && previous != (t0 to d0)) return "changed_evidence_origin"
        }
        return null
    }
    private fun guard(name: String, e: Map<String, Any?>): Boolean {
        val scoped = integer(e["generation"]) == generation
        val fresh = scoped && key(e) !in seen
        return when(name) {
            "always", "new_session" -> true
            "current_generation" -> scoped
            "verified_current_generation" -> scoped && e["verified"] == true
            "fresh_scoped_evidence" -> fresh && e["verified"] == true
            "fresh_applicable_pipeline_output" -> {
                val alive = e["kind"] != "camera" || (time - number(e["observed_elapsed_s"])!! < limit("ordinary_max_age_s") && distance - number(e["observed_distance_m"])!! < limit("ordinary_max_distance_m"))
                fresh && e["verified"] == true && claims["voice"] == null && !pendingContext && gap == null && applicable(e) && alive
            }
            "verified_enclosing_camera" -> guard("fresh_applicable_pipeline_output", e) && e["area_verified"] == true && e["scope_kind"] in setOf("zone", "city")
            "current_verified_bundle" -> scoped && e["verified"] == true && !pendingContext && gap == null && applicable(e)
            "fresh_confirmed_boundary" -> fresh && e["confirmed"] == true && e["reason"] in model.policy["boundary_reasons"] as List<*>
            "new_applicability_revision" -> scoped && (integer(e["next_revision"]) ?: -1) > applicabilityRevision
            else -> error("Unsupported policy guard $name")
        }
    }
    private fun action(name: String, e: Map<String, Any?>) {
        if (name.startsWith("accept_")) {
            val source = name.removePrefix("accept_")
            claims[source] = Claim(e["id"] as String, value(e)!!, if (source == "camera_context") "camera" else source,
                if (source == "camera") number(e["observed_elapsed_s"])!! else time,
                if (source == "camera") number(e["observed_distance_m"])!! else distance)
            return
        }
        if (name in setOf("clear_voice", "clear_camera", "clear_camera_context", "clear_bundle")) { claims.remove(name.removePrefix("clear_")); return }
        when(name) {
            "reset_session" -> { claims.clear(); lastKnown = null; generation = 0; applicabilityRevision = 0; pendingContext = false; gap = null; seen.clear(); origins.clear(); time = 0.0; distance = 0.0; session = e["session_id"] as String; sequence = integer(e["sequence"])!! }
            "advance_generation" -> generation++
            "advance_applicability_revision" -> applicabilityRevision = integer(e["next_revision"])!!
            "mark_pending" -> pendingContext = true
            "clear_pending" -> pendingContext = false
            "start_gap_once" -> if (gap == null) gap = time to distance
            "clear_gap" -> gap = null
            else -> error("Unsupported policy action $name")
        }
    }
    fun project(transition: String = "T10", expiry: List<String> = emptyList(), rejection: String? = null): SpeedReferenceOutput {
        for (row in model.policy["selection"] as List<Map<String, Any?>>) {
            val name = row["register"] as? String
            val claim = if (name == "last_known") lastKnown else claims[name]
            if (name != null && claim == null) continue
            val current = row["current"] as Boolean
            if (current) lastKnown = claim
            return SpeedReferenceOutput(row["state"] as String, claim?.value, claim?.source, claim?.id, current, generation, applicabilityRevision, transition, expiry, rejection)
        }
        error("Missing policy selection fallback")
    }
    fun step(e: Map<String, Any?>): SpeedReferenceOutput {
        validate(e)?.let { return project("REJECT", rejection = it) }
        val kind = e["kind"] as String
        val reasons = mutableListOf<String>()
        if (kind != "reset") {
            time = number(e["elapsed_s"])!!; distance = number(e["distance_m"])!!; sequence = integer(e["sequence"])!!
            for (rule in model.policy["expiry"] as List<Map<String, Any?>>) {
                for (source in rule["sources"] as List<String>) {
                    val claim = claims[source] ?: continue
                    val delta = if (rule["metric"] == "elapsed_s") time - claim.time else distance - claim.distance
                    if (delta >= limit(rule["limit"] as String)) { claims.remove(source); reasons.add("$source:${rule["id"]}") }
                }
            }
            gap?.let { g -> if (time - g.first >= limit("context_gap_max_age_s") || distance - g.second >= limit("context_gap_max_distance_m")) {
                for (source in listOf("voice", "camera", "bundle", "camera_context")) if (claims.remove(source) != null) reasons.add("$source:context_gap")
            } }
        }
        for (row in model.policy["transitions"] as List<Map<String, Any?>>) {
            if (row["on"] !in setOf(kind, "*") || !guard(row["guard"] as String, e)) continue
            for (name in row["actions"] as List<String>) action(name, e)
            if (kind in setOf("voice", "camera", "camera_context", "context_confirmed")) seen.add(key(e))
            if (kind == "camera") origins[e["id"] as String] = number(e["observed_elapsed_s"])!! to number(e["observed_distance_m"])!!
            return project(row["id"] as String, reasons)
        }
        error("Incomplete policy transition table")
    }
}

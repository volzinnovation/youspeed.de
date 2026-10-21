package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import java.io.File
import java.time.Instant

/** One app process; resume and camera/model restarts do not cause requests. */
internal class SignCollectionInterestActivation {
    var enabled = false; private set
    fun update(value: Boolean): Boolean {
        val request = value && !enabled
        enabled = value
        return request
    }
}

/** HTTPS image selection; neither plan availability nor sampling gates sighting delivery. */
internal class SignCollectionInterestPlan(data: ByteArray, schema: JsonObject) {
    data class Identity(val country: String, val pack: String, val classifier: String, val label: String)
    data class Rule(val key: String, val numerator: Long, val denominator: Long)
    companion object {
        const val MAXIMUM_BYTES = 2 * 1024 * 1024
        fun isAlways(label: String) = label == "bad" || label.startsWith("bad:")
        fun sample(revision: Long, key: String, observation: String, numerator: Long, denominator: Long): Boolean {
            require(revision in 1..9007199254740991L && '\n' !in key && '\r' !in key && SignCollectionJson.isUuid(observation))
            require(denominator in 1..1000000L && numerator in 0..denominator)
            val draw = observation.takeLast(8).toLong(16)
            return draw * denominator < numerator * 4294967296L
        }
        fun date(text: String): Instant {
            require(text.endsWith("Z") || text.endsWith("+00:00"))
            return java.time.OffsetDateTime.parse(text).toInstant()
        }
    }
    val document: JsonObject
    val revision: Long
    val generated: Instant
    val validFrom: Instant
    val expires: Instant
    val packs: Set<String>
    val rules: Map<Identity, Rule>
    init {
        require(data.size <= MAXIMUM_BYTES)
        val text = Charsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
            .decode(java.nio.ByteBuffer.wrap(data)).toString()
        val d = SignCollectionJson.parse(text, maximumCollectionCount = 10000).jsonObject
        SignCollectionSchema.validate(d, schema, schema)
        fun string(o: JsonObject, key: String) = o.getValue(key).jsonPrimitive.content
        fun integer(o: JsonObject, key: String) = o.getValue(key).jsonPrimitive.long
        revision = integer(d, "revision")
        generated = date(string(d, "generated_at")); validFrom = date(string(d, "valid_from")); expires = date(string(d, "valid_until"))
        require(generated <= validFrom && validFrom < expires && java.time.Duration.between(generated, expires) <= java.time.Duration.ofHours(48))
        val compatible = d.getValue("compatible_packs").jsonArray.map { it.jsonPrimitive.content }
        packs = compatible.toSet(); require(packs.size == compatible.size)
        val limits = d.getValue("limits").jsonObject
        val algorithm = string(d, "algorithm_version")
        if (algorithm == "daily-maximum-v1") {
            require(d.getValue("bootstrap").jsonPrimitive.boolean == (integer(d, "daily_maximum") == 0L))
            require(limits["normal_images"] in listOf(null, JsonNull) && limits["normal_bytes"] in listOf(null, JsonNull))
        }
        val found = mutableMapOf<Identity, Rule>(); val keys = mutableSetOf<String>(); val selectors = mutableSetOf<List<String>>()
        var allocation = 0L
        d.getValue("interests").jsonArray.forEach { value ->
            val item = value.jsonObject; val key = string(item, "collection_key"); val country = string(item, "country")
            val fraction = item.getValue("selection").jsonObject; val n = integer(fraction, "numerator"); val den = integer(fraction, "denominator")
            require(n > 0 && n <= den && !isAlways(string(item, "class_id")) && keys.add(key) && integer(item, "target_deficit") > 0)
            if (algorithm == "waterfill-v1") {
                val allocated = integer(item, "allocated_images"); require(allocated <= integer(item, "target_deficit")); allocation += allocated
            } else require(n == den && integer(item, "target_deficit") <= maxOf(1, integer(d,"daily_maximum")) && item["allocated_images"] in listOf(null, JsonNull))
            item.getValue("selectors").jsonArray.forEach { selector ->
                val s = selector.jsonObject
                val identity = Identity(string(s, "country"), string(s, "pack_sha256"), string(s, "classifier_sha256"), string(s, "raw_label"))
                require(identity.country == country && identity.pack in packs && !isAlways(identity.label)
                    && selectors.add(listOf(identity.country, identity.pack, identity.label)))
                found[identity] = Rule(key, n, den)
            }
        }
        if (algorithm == "waterfill-v1") require(allocation <= integer(limits, "normal_images") && allocation * integer(limits, "max_image_bytes") <= integer(limits, "normal_bytes"))
        rules = found.toMap(); document = d
    }
    fun current(now: Instant) = generated <= now && validFrom <= now && now < expires
}

internal data class SignCollectionInterestSelection(val revision: Long?, val key: String?, val decision: String,
    val numerator: Long? = null, val denominator: Long? = null, val expires: Instant? = null) {
    val collects get() = decision == "always" || decision == "selected"
    fun permits(at: Instant) = decision == "always" || (collects && expires?.let { at < it } == true)
    val wire get() = buildJsonObject {
        put("plan_revision", revision?.let(::JsonPrimitive) ?: JsonNull); put("collection_key", key?.let(::JsonPrimitive) ?: JsonNull)
        put("decision", decision)
        put("sampling_fraction", if (numerator != null && denominator != null) buildJsonObject { put("numerator",numerator); put("denominator",denominator) } else JsonNull)
    }
}

internal class SignCollectionInterestStore(private val path: File, private val schema: JsonObject,
    private val now: () -> Instant = Instant::now,
    private val uptime: () -> Long = System::nanoTime) {
    private var plan: SignCollectionInterestPlan? = runCatching { if (path.length() <= SignCollectionInterestPlan.MAXIMUM_BYTES) SignCollectionInterestPlan(path.readBytes(),schema) else null }.getOrNull()
    private var loadedWall = now()
    private var loadedUptime = uptime()
    private fun usable() = plan?.takeIf { it.current(now()) && kotlin.math.abs(java.time.Duration.between(loadedWall,now()).toMillis() - (uptime()-loadedUptime)/1000000) < 300000 }
    @Synchronized fun etag() = usable()?.let { "\"crop-interest-${it.revision}\"" }
    @Synchronized fun install(data: ByteArray) {
        val candidate = SignCollectionInterestPlan(data,schema); require(candidate.current(now()))
        plan?.let { require(candidate.revision >= it.revision && (candidate.revision != it.revision || SignCollectionJson.canonical(candidate.document, maximumCollectionCount = 10000) == SignCollectionJson.canonical(it.document, maximumCollectionCount = 10000))) }
        path.parentFile!!.mkdirs()
        val temporary = File.createTempFile("interest-", ".json", path.parentFile)
        try {
            java.io.FileOutputStream(temporary).use { it.write(data); it.fd.sync() }
            java.nio.file.Files.move(temporary.toPath(),path.toPath(),java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        } finally { temporary.delete() }
        plan=candidate; loadedWall=now(); loadedUptime=uptime()
    }
    @Synchronized fun interested(identity: SignCollectionInterestPlan.Identity) = SignCollectionInterestPlan.isAlways(identity.label) || usable()?.rules?.containsKey(identity) == true
    @Synchronized fun select(identity: SignCollectionInterestPlan.Identity, observation: String): SignCollectionInterestSelection {
        val current=usable()
        if(SignCollectionInterestPlan.isAlways(identity.label)) return SignCollectionInterestSelection(current?.revision,null,"always",1,1)
        if(current == null || identity.pack !in current.packs) return SignCollectionInterestSelection(null,null,"no_valid_plan")
        val rule=current.rules[identity] ?: return SignCollectionInterestSelection(current.revision,null,"not_interested",expires=current.expires)
        val selected=SignCollectionInterestPlan.sample(current.revision,rule.key,observation,rule.numerator,rule.denominator)
        return SignCollectionInterestSelection(current.revision,rule.key,if(selected) "selected" else "sampled_out",rule.numerator,rule.denominator,current.expires)
    }
}

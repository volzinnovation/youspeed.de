package de.youspeed.android.alpha

import java.security.MessageDigest
import java.time.Instant
import kotlinx.serialization.json.*
import kotlin.math.*

/** A separate opt-in advisory path. It cannot produce a speed offer or sign sighting. */
internal object RoadworksAdvisory {
    enum class Freshness { FRESH, DELAYED, UNKNOWN, UNAVAILABLE }
    data class Interval(val start: Instant, val end: Instant) { fun contains(at: Instant) = at >= start && at < end }
    data class Point(val latitude: Double, val longitude: Double)
    private val supportedSources = setOf("bemas", "incidents-bw", "autobahn-short-term", "autobahn-long-term")
    data class Feature(val id: String, val revision: String, val kind: String, val description: String,
        val roadLabel: String, val direction: String, val operatorStatus: String, val scheduleStatus: String,
        val outer: Interval, val intervals: List<Interval>, val points: List<Point>, val advisorySource: String = "bemas",
        val publisherRecordId: String = "", val sourceVersionTime: Instant? = null,
        val validityBasis: String = "scheduled", val sourceValidityStatus: String? = null,
        val sourceValidityStart: Instant? = null, val sourceValidityEnd: Instant? = null) {
        val supportedValidity: Boolean get() = when (validityBasis) {
            "scheduled" -> advisorySource != "incidents-bw" || sourceValidityStatus == "definedByValidityTimeSpec"
            "reported_active" -> advisorySource == "incidents-bw" && sourceValidityStatus == "active" && scheduleStatus == "resolved" &&
                outer.end > outer.start && outer.end <= outer.start.plusSeconds(900)
            else -> false
        }
        fun eligible(at: Instant): Boolean {
            val kinds = if (advisorySource == "bemas") setOf("roadworks", "closure") else setOf("roadworks", "closure", "incident", "hazard", "congestion")
            val statuses = if (advisorySource == "bemas") setOf("requested", "approved", "implemented") else setOf("requested", "approved", "implemented", "reported")
            return advisorySource in supportedSources && supportedValidity && kind in kinds && operatorStatus in statuses &&
                scheduleStatus == "resolved" && outer.contains(at) && intervals.any { it.contains(at) }
        }
    }
    data class Snapshot(val id: String, val window: Interval, val features: List<Feature>, val attributions: List<Map<String, String>>,
        val schemaVersion: Int = 1, val sourceIds: Set<String> = setOf("bemas"))
    data class Source(val id: String, val enabled: Boolean, val sourcePublication: Instant?, val sourceModified: Instant?,
        val lastChecked: Instant?, val advertisedStatus: Freshness, val attribution: Map<String, String> = emptyMap())
    data class Manifest(val enabled: Boolean, val snapshotId: String?, val snapshotBytes: Int?, val snapshotPath: String?,
        val serverTime: Instant, val sourcePublication: Instant?, val sourceModified: Instant?, val lastChecked: Instant?,
        val advertisedStatus: Freshness, val schemaVersion: Int = 1, val sources: List<Source> = emptyList()) {
        /** Source validity uses the server anchor, independently of handset GPS wall timestamps. */
        fun trustedNow(receivedUptime: Double, nowUptime: Double): Instant? {
            val elapsed = nowUptime - receivedUptime
            if (!elapsed.isFinite() || elapsed < 0 || elapsed >= Long.MAX_VALUE.toDouble()) return null
            val seconds = elapsed.toLong()
            val nanos = ((elapsed - seconds.toDouble()) * 1e9).toLong()
            return runCatching { serverTime.plusSeconds(seconds).plusNanos(nanos) }.getOrNull()
        }
        fun sourceList(): List<Source> = if (schemaVersion == 1) listOf(Source("bemas", enabled, sourcePublication, sourceModified, lastChecked, advertisedStatus)) else sources
        fun sourceAgeMinutes(sourceId: String, receivedUptime: Double, nowUptime: Double): Long? {
            val source = sourceList().firstOrNull { it.id == sourceId } ?: return null
            val publication = source.sourcePublication ?: return null
            val modified = source.sourceModified ?: return null
            val oldest = minOf(publication, modified)
            val elapsed = nowUptime - receivedUptime
            if (!elapsed.isFinite() || elapsed < 0) return null
            val now = serverTime.toEpochMilli() / 1000.0 + elapsed
            if (now < publication.toEpochMilli() / 1000.0 || now < modified.toEpochMilli() / 1000.0) return null
            val age = (serverTime.toEpochMilli() - oldest.toEpochMilli()) / 1000.0 + elapsed
            return age.takeIf { it.isFinite() && it >= 0 }?.let { (it / 60).toLong() }
        }
        fun sourceFreshness(receivedUptime: Double, nowUptime: Double): Map<String, Freshness> = sourceList().associate { source ->
            source.id to sourceFreshness(source, receivedUptime, nowUptime)
        }
        private fun sourceFreshness(source: Source, receivedUptime: Double, nowUptime: Double): Freshness {
            if (!enabled || !source.enabled) return Freshness.UNAVAILABLE
            val elapsed = nowUptime - receivedUptime
            if (!elapsed.isFinite() || elapsed < 0) return Freshness.UNKNOWN
            val incident = source.id == "incidents-bw"
            val maximumAge = if (incident) 900 else 86400
            if (elapsed > 86400) return Freshness.UNAVAILABLE
            if (snapshotId == null || source.advertisedStatus == Freshness.UNAVAILABLE) return Freshness.UNAVAILABLE
            if (source.advertisedStatus == Freshness.UNKNOWN || source.sourcePublication == null || source.sourceModified == null || source.lastChecked == null) return Freshness.UNKNOWN
            val now = serverTime.epochSecond + serverTime.nano / 1e9 + elapsed
            fun age(clock: Instant) = now - clock.epochSecond - clock.nano / 1e9
            val publicationAge = age(source.sourcePublication); val modifiedAge = age(source.sourceModified); val checkAge = age(source.lastChecked)
            if (publicationAge < 0 || modifiedAge < 0 || checkAge < 0) return Freshness.UNKNOWN
            val sourceAge = maxOf(publicationAge, modifiedAge)
            if (sourceAge > maximumAge || incident && checkAge > maximumAge) return Freshness.UNAVAILABLE
            return if (source.advertisedStatus == Freshness.DELAYED || sourceAge > (if (incident) 600 else 1800) || checkAge > (if (incident) 600 else 900)) Freshness.DELAYED else Freshness.FRESH
        }
        fun freshness(receivedUptime: Double, nowUptime: Double): Freshness {
            if (!enabled) return Freshness.UNAVAILABLE
            return sourceFreshness(receivedUptime, nowUptime).values.minByOrNull { it.ordinal } ?: Freshness.UNAVAILABLE
        }
        fun validatedHttpClock(date: Instant, age: Double): Manifest {
            require(age.isFinite() && age in 0.0..86400.0 && abs(serverTime.epochSecond - date.epochSecond) <= 300)
            return copy(serverTime = date.plusNanos((age * 1e9).toLong()))
        }
    }
    private fun date(raw: JsonElement?): Instant {
        val value = requireNotNull(raw).jsonPrimitive.content
        require(Regex("(Z|[+-][0-9]{2}:[0-9]{2})$").containsMatchIn(value))
        return java.time.OffsetDateTime.parse(value).toInstant()
    }
    private fun interval(raw: JsonElement?): Interval {
        val value = requireNotNull(raw).jsonObject
        return Interval(date(value["start"]), date(value["end"])).also { require(it.end > it.start) }
    }
    private fun hashId(raw: JsonElement?): String? = raw?.takeUnless { it == JsonNull }?.jsonPrimitive?.content?.takeIf { it.matches(Regex("[a-f0-9]{64}")) }
    private fun string(value: JsonObject, key: String) = requireNotNull(value[key]).jsonPrimitive.content
    private fun attributions(raw: JsonElement?): List<Map<String, String>> = requireNotNull(raw).jsonArray.map { row -> row.jsonObject.mapValues { it.value.jsonPrimitive.content } }.also { require(it.isNotEmpty()) }
    fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun sourceIds(raw: JsonElement?): Set<String> {
        val values = requireNotNull(raw).jsonArray.map { it.jsonPrimitive.content }
        require(values.isNotEmpty() && values.size == values.toSet().size && values.all { it in supportedSources })
        return values.toSet()
    }
    private fun sourceAttribution(raw: JsonElement?): Map<String, String> = requireNotNull(raw).jsonObject.mapValues { it.value.jsonPrimitive.content }.also { values ->
        require(listOf("provider", "dataset_url", "license_id", "license_url", "changes").all { values[it]?.isNotBlank() == true })
    }
    fun parseManifest(bytes: ByteArray): Manifest {
        require(bytes.size <= 262144)
        val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        val version = root["schema_version"]?.jsonPrimitive?.int
        require(version in setOf(1, 2)) { "unsupported_roadworks_version" }
        require(string(root, "region") == "DE-BW")
        val enabled = root.getValue("feature_enabled").jsonPrimitive.boolean
        val coverage = root.getValue("coverage").jsonObject
        require(string(coverage, "region") == "DE-BW" && !coverage.getValue("complete_road_coverage").jsonPrimitive.boolean)
        attributions(root["attributions"])
        val sources = if (version == 2) root.getValue("sources").jsonArray.map { row ->
            val value = row.jsonObject; val clocks = value.getValue("freshness").jsonObject
            fun optionalDate(key: String) = requireNotNull(clocks[key]).takeUnless { it == JsonNull }?.let(::date)
            Source(string(value, "source_id"), value.getValue("enabled").jsonPrimitive.boolean, optionalDate("source_publication_at"),
                optionalDate("source_modified_at"), optionalDate("last_checked_at"), Freshness.valueOf(string(clocks, "status").uppercase()), sourceAttribution(value["attribution"]))
        }.also { values ->
            require(values.isNotEmpty() && values.map { it.id }.toSet().size == values.size && values.all { it.id in supportedSources })
            require(sourceIds(coverage["source_ids"]) == values.map { it.id }.toSet())
        } else emptyList()
        val expectedAutobahn = sources.any { it.enabled && it.id.startsWith("autobahn-") }
        require(coverage.getValue("autobahn_included").jsonPrimitive.boolean == expectedAutobahn)
        val id = hashId(root["snapshot_id"])
        val size = root["snapshot_bytes"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.int
        val path = root["snapshot_path"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content
        if (id != null) require(size != null && size in 0..8388608 && path == "/youspeed/live/v$version/regions/DE-BW/snapshots/$id")
        else require(root["snapshot_id"] == JsonNull && root["snapshot_bytes"] == JsonNull && root["snapshot_path"] == JsonNull)
        val clocks = root.getValue("freshness").jsonObject
        fun optionalDate(key: String) = clocks[key]?.takeUnless { it == JsonNull }?.let(::date)
        val status = Freshness.valueOf(string(clocks, "status").uppercase())
        if (version == 2) require(status == (sources.filter { it.enabled }.minByOrNull { it.advertisedStatus.ordinal }?.advertisedStatus ?: Freshness.UNAVAILABLE))
        return Manifest(enabled, id, size, path, date(clocks["server_time"]), optionalDate("source_publication_at"),
            optionalDate("source_modified_at"), optionalDate("last_checked_at"), status, requireNotNull(version), sources)
    }
    fun parseSnapshot(bytes: ByteArray, expectedId: String): Snapshot {
        require(bytes.size <= 8388608)
        require(sha256(bytes) == expectedId) { "roadworks_checksum_mismatch" }
        val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        val version = root["schema_version"]?.jsonPrimitive?.int
        require(version in setOf(1, 2)) { "unsupported_roadworks_version" }
        val sources = if (version == 2) sourceIds(root["source_ids"]) else setOf("bemas")
        require(string(root, "type") == "FeatureCollection")
        require(string(root, "normalization_version").isNotEmpty())
        date(root["generated_at"])
        val window = interval(root["evaluation_window"])
        val credits = attributions(root["attributions"])
        val rows = root.getValue("features").jsonArray
        require(rows.size <= 10000)
        var vertices = 0
        val identities = mutableSetOf<String>()
        val features = rows.map { raw ->
            val row = raw.jsonObject
            val id = string(row, "id")
            val properties = row.getValue("properties").jsonObject
            val advisorySource = if (version == 2) string(properties, "advisory_source") else "bemas"
            require(advisorySource in sources && string(row, "type") == "Feature" && id.startsWith("mobidata-bw:$advisorySource:") && id.length <= 300 && identities.add(id))
            val publisherRecordId = properties["source_id"]?.jsonPrimitive?.content ?: ""
            if (version == 2) require(publisherRecordId.isNotBlank() && publisherRecordId.length <= 256)
            val sourceVersionTime = if (version == 2) requireNotNull(properties["source_version_time"]).takeUnless { it == JsonNull }?.let(::date) else null
            val revision = requireNotNull(hashId(properties["revision"]))
            val text = string(properties, "description"); require(text.length <= 2048)
            val road = string(properties, "road_label"); require(road.length <= 512)
            val outer = Interval(date(properties["outer_start"]), date(properties["outer_end"])); require(outer.end > outer.start)
            val intervals = properties.getValue("active_intervals").jsonArray.map(::interval); require(intervals.size <= 1024)
            val schedule = string(properties, "schedule_status")
            require(intervals.all { it.start >= maxOf(window.start, outer.start) && it.end <= minOf(window.end, outer.end) })
            require(schedule == "resolved" || intervals.isEmpty())
            var validityBasis = "scheduled"
            var sourceValidityStatus: String? = null
            var sourceValidityStart: Instant? = null
            var sourceValidityEnd: Instant? = null
            if (version == 2 && advisorySource == "incidents-bw") {
                validityBasis = string(properties, "validity_basis")
                sourceValidityStatus = string(properties, "source_validity_status")
                sourceValidityStart = requireNotNull(properties["source_validity_start"]).takeUnless { it == JsonNull }?.let(::date)
                sourceValidityEnd = requireNotNull(properties["source_validity_end"]).takeUnless { it == JsonNull }?.let(::date)
                require(validityBasis == "scheduled" && sourceValidityStatus == "definedByValidityTimeSpec" ||
                    validityBasis == "reported_active" && sourceValidityStatus == "active" && schedule == "resolved" && outer.end <= outer.start.plusSeconds(900))
            } else if (version == 2 && properties["validity_basis"] != null) {
                require(string(properties, "validity_basis") == "scheduled")
            }
            val geometry = row.getValue("geometry").jsonObject
            val coordinates = when (string(geometry, "type")) {
                "Point" -> listOf(geometry.getValue("coordinates").jsonArray)
                "LineString" -> geometry.getValue("coordinates").jsonArray.map { it.jsonArray }.also { require(it.size >= 2) }
                else -> error("unsupported_roadworks_geometry")
            }
            vertices += coordinates.size; require(vertices <= 200000)
            val points = coordinates.map { pair ->
                require(pair.size == 2)
                val longitude = pair[0].jsonPrimitive.double; val latitude = pair[1].jsonPrimitive.double
                require(longitude.isFinite() && latitude.isFinite() && longitude in 7.0..11.0 && latitude in 47.0..50.0)
                Point(latitude, longitude)
            }
            Feature(id, revision, string(properties, "kind"), text, road,
                if (points.size == 1) "unknown" else string(properties, "direction"), string(properties, "operator_status"), schedule, outer, intervals, points, advisorySource, publisherRecordId, sourceVersionTime,
                validityBasis, sourceValidityStatus, sourceValidityStart, sourceValidityEnd)
        }
        return Snapshot(expectedId, window, features, credits, requireNotNull(version), sources)
    }
    fun distance(point: Point, feature: Feature): Double {
        val sy = Math.PI / 180 * 6371008.8; val sx = sy * cos(Math.toRadians(point.latitude))
        val projected = feature.points.map { (it.longitude - point.longitude) * sx to (it.latitude - point.latitude) * sy }
        if (projected.size == 1) return hypot(projected[0].first, projected[0].second)
        return projected.zipWithNext().minOfOrNull { (a, b) ->
            val dx = b.first - a.first; val dy = b.second - a.second; val length = dx * dx + dy * dy
            val fraction = if (length > 0) (-(a.first * dx + a.second * dy) / length).coerceIn(0.0, 1.0) else 0.0
            hypot(a.first + fraction * dx, a.second + fraction * dy)
        } ?: Double.POSITIVE_INFINITY
    }
}

internal class RoadworksSnapshotCache(private val directory: java.io.File? = null) {
    var snapshot: RoadworksAdvisory.Snapshot? = null; private set
    var bytes: ByteArray? = null; private set
    var previousSnapshot: RoadworksAdvisory.Snapshot? = null; private set
    var restoreError: String? = null; private set
    init {
        if (directory != null) runCatching {
            val pointer = java.io.File(directory,"current.json")
            if (pointer.exists()) {
                val raw = Json.parseToJsonElement(pointer.readText()).jsonObject
                fun load(id: String?): Pair<ByteArray,RoadworksAdvisory.Snapshot>? {
                    if (id == null || !id.matches(Regex("[a-f0-9]{64}"))) return null
                    val data=java.io.File(directory,"snapshot-$id.json").readBytes()
                    return data to RoadworksAdvisory.parseSnapshot(data,id)
                }
                val previous=runCatching { load(raw["previous"]?.jsonPrimitive?.content) }.getOrNull()
                previousSnapshot=previous?.second
                val current=runCatching { load(raw["current"]?.jsonPrimitive?.content) }.getOrNull()
                if(current!=null) { bytes=current.first;snapshot=current.second }
                else if(previous!=null) { bytes=previous.first;snapshot=previous.second;previousSnapshot=null;restoreError="current_snapshot_invalid_using_previous" }
                else restoreError="no_valid_cached_snapshot"
            }
        }.onFailure { restoreError=it.message }
    }
    private fun writeAtomic(file:java.io.File,data:ByteArray) {
        val staging=java.io.File(file.parentFile,file.name+".tmp")
        java.io.FileOutputStream(staging).use { output -> output.write(data);output.fd.sync() }
        java.nio.file.Files.move(staging.toPath(),file.toPath(),java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING)
    }
    fun install(data: ByteArray, manifest: RoadworksAdvisory.Manifest) {
        require(data.size == manifest.snapshotBytes)
        val parsed = RoadworksAdvisory.parseSnapshot(data, requireNotNull(manifest.snapshotId))
        require(parsed.schemaVersion == manifest.schemaVersion && parsed.sourceIds == manifest.sourceList().map { it.id }.toSet()) { "roadworks_source_manifest_mismatch" }
        parsed.features.filter { it.validityBasis == "reported_active" }.forEach { feature ->
            val publication = requireNotNull(manifest.sourceList().firstOrNull { it.id == feature.advisorySource }?.sourcePublication)
            require(feature.outer.start == publication && feature.outer.end <= publication.plusSeconds(900)) { "roadworks_active_lease_manifest_mismatch" }
        }
        directory?.let { root ->
            check(root.isDirectory || root.mkdirs())
            writeAtomic(java.io.File(root,"snapshot-${parsed.id}.json"),data)
            val previous=snapshot?.id?.takeIf { it!=parsed.id } ?: previousSnapshot?.id
            val pointer=buildJsonObject { put("current",parsed.id);previous?.let { put("previous",it) } }
            writeAtomic(java.io.File(root,"current.json"),pointer.toString().toByteArray())
        }
        if (snapshot?.id != parsed.id) previousSnapshot=snapshot
        bytes = data.copyOf(); snapshot = parsed
    }
}

internal class RoadworksRelevance {
    data class Fix(val point: RoadworksAdvisory.Point, val at: Instant, val accuracyM: Double)
    data class Card(val feature: RoadworksAdvisory.Feature, val distanceM: Double, val freshness: RoadworksAdvisory.Freshness)
    private var snapshotId: String? = null
    private var selectedId: String? = null
    private var pendingId: String? = null
    private var previousFix: Instant? = null
    fun reset() { snapshotId = null; selectedId = null; pendingId = null; previousFix = null }
    fun update(snapshot: RoadworksAdvisory.Snapshot?, freshness: RoadworksAdvisory.Freshness, fix: Fix?, now: Instant,
               enabled: Boolean, driving: Boolean, foreground: Boolean, sourceFreshness: Map<String, RoadworksAdvisory.Freshness>? = null,
               eligibilityNow: Instant? = null): Card? {
        val validityTime = eligibilityNow ?: if (snapshot?.schemaVersion == 1) now else null
        val available = setOf(RoadworksAdvisory.Freshness.FRESH, RoadworksAdvisory.Freshness.DELAYED)
        fun status(feature: RoadworksAdvisory.Feature) = sourceFreshness?.get(feature.advisorySource) ?: if (sourceFreshness == null && snapshot?.schemaVersion == 1) freshness else RoadworksAdvisory.Freshness.UNAVAILABLE
        if (!enabled || !driving || !foreground || sourceFreshness == null && freshness !in available ||
            snapshot == null || validityTime == null || !snapshot.window.contains(validityTime) || fix == null || !fix.point.latitude.isFinite() || !fix.point.longitude.isFinite() ||
            fix.point.latitude !in -90.0..90.0 || fix.point.longitude !in -180.0..180.0 || !fix.accuracyM.isFinite() || fix.accuracyM !in 0.0..50.0 ||
            now < fix.at || java.time.Duration.between(fix.at, now).toMillis() > 3000) { reset(); return null }
        if (previousFix?.let { fix.at < it } == true) { reset(); return null }
        if (snapshotId != snapshot.id) { reset(); snapshotId = snapshot.id }
        val eligible = snapshot.features.filter { it.eligible(validityTime) && status(it) in available }.map { it to RoadworksAdvisory.distance(fix.point, it) }
        eligible.firstOrNull { it.first.id == selectedId && it.second <= 750 }?.let {
            previousFix = fix.at; return Card(it.first, it.second, status(it.first))
        }
        selectedId = null
        val candidate = eligible.filter { it.second <= 500 }.sortedWith(compareBy<Pair<RoadworksAdvisory.Feature, Double>> { if (it.first.kind == "closure") 0 else 1 }.thenBy { it.second }.thenBy { it.first.id }).firstOrNull()
        if (candidate == null) { pendingId = null; previousFix = fix.at; return null }
        val confirmed = pendingId == candidate.first.id && previousFix?.let { fix.at > it && java.time.Duration.between(it, fix.at).toMillis() <= 3000 } == true
        pendingId = candidate.first.id; previousFix = fix.at
        if (!confirmed) return null
        selectedId = candidate.first.id
        return Card(candidate.first, candidate.second, status(candidate.first))
    }
}

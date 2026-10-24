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
    data class Feature(val id: String, val revision: String, val kind: String, val description: String,
        val roadLabel: String, val direction: String, val operatorStatus: String, val scheduleStatus: String,
        val outer: Interval, val intervals: List<Interval>, val points: List<Point>) {
        fun eligible(at: Instant) = kind in setOf("roadworks", "closure") && operatorStatus in setOf("requested", "approved", "implemented") &&
            scheduleStatus == "resolved" && outer.contains(at) && intervals.any { it.contains(at) }
    }
    data class Snapshot(val id: String, val window: Interval, val features: List<Feature>, val attributions: List<Map<String, String>>)
    data class Manifest(val enabled: Boolean, val snapshotId: String?, val snapshotBytes: Int?, val snapshotPath: String?,
        val serverTime: Instant, val sourcePublication: Instant?, val sourceModified: Instant?, val lastChecked: Instant?,
        val advertisedStatus: Freshness) {
        fun freshness(receivedUptime: Double, nowUptime: Double): Freshness {
            if (!enabled) return Freshness.UNAVAILABLE
            val elapsed = nowUptime - receivedUptime
            if (!elapsed.isFinite() || elapsed < 0) return Freshness.UNKNOWN
            if (elapsed > 86400) return Freshness.UNAVAILABLE
            if (advertisedStatus == Freshness.UNAVAILABLE || snapshotId == null) return Freshness.UNAVAILABLE
            if (advertisedStatus == Freshness.UNKNOWN || sourcePublication == null || sourceModified == null || lastChecked == null) return Freshness.UNKNOWN
            val now = serverTime.epochSecond + serverTime.nano / 1e9 + elapsed
            val oldest = minOf(sourcePublication, sourceModified)
            val sourceAge = now - oldest.epochSecond - oldest.nano / 1e9
            val checkAge = now - lastChecked.epochSecond - lastChecked.nano / 1e9
            if (sourceAge < 0 || checkAge < 0) return Freshness.UNKNOWN
            if (sourceAge > 86400) return Freshness.UNAVAILABLE
            return if (advertisedStatus == Freshness.DELAYED || sourceAge > 1800 || checkAge > 900) Freshness.DELAYED else Freshness.FRESH
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

    fun parseManifest(bytes: ByteArray): Manifest {
        require(bytes.size <= 262144)
        val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        require(root["schema_version"]?.jsonPrimitive?.int == 1) { "unsupported_roadworks_version" }
        require(string(root, "region") == "DE-BW")
        val enabled = root.getValue("feature_enabled").jsonPrimitive.boolean
        val coverage = root.getValue("coverage").jsonObject
        require(string(coverage, "region") == "DE-BW" && !coverage.getValue("complete_road_coverage").jsonPrimitive.boolean && !coverage.getValue("autobahn_included").jsonPrimitive.boolean)
        attributions(root["attributions"])
        val id = hashId(root["snapshot_id"])
        val size = root["snapshot_bytes"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.int
        val path = root["snapshot_path"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content
        if (id != null) require(size != null && size in 0..8388608 && path == "/youspeed/live/v1/regions/DE-BW/snapshots/$id")
        else require(root["snapshot_id"] == JsonNull && root["snapshot_bytes"] == JsonNull && root["snapshot_path"] == JsonNull)
        val clocks = root.getValue("freshness").jsonObject
        fun optionalDate(key: String) = clocks[key]?.takeUnless { it == JsonNull }?.let(::date)
        return Manifest(enabled, id, size, path, date(clocks["server_time"]), optionalDate("source_publication_at"),
            optionalDate("source_modified_at"), optionalDate("last_checked_at"), Freshness.valueOf(string(clocks, "status").uppercase()))
    }
    fun parseSnapshot(bytes: ByteArray, expectedId: String): Snapshot {
        require(bytes.size <= 8388608)
        require(sha256(bytes) == expectedId) { "roadworks_checksum_mismatch" }
        val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        require(root["schema_version"]?.jsonPrimitive?.int == 1) { "unsupported_roadworks_version" }
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
            require(string(row, "type") == "Feature" && id.startsWith("mobidata-bw:bemas:") && id.length <= 300 && identities.add(id))
            val properties = row.getValue("properties").jsonObject
            val revision = requireNotNull(hashId(properties["revision"]))
            val text = string(properties, "description"); require(text.length <= 2048)
            val road = string(properties, "road_label"); require(road.length <= 512)
            val outer = Interval(date(properties["outer_start"]), date(properties["outer_end"])); require(outer.end > outer.start)
            val intervals = properties.getValue("active_intervals").jsonArray.map(::interval); require(intervals.size <= 1024)
            val schedule = string(properties, "schedule_status")
            require(intervals.all { it.start >= maxOf(window.start, outer.start) && it.end <= minOf(window.end, outer.end) })
            require(schedule == "resolved" || intervals.isEmpty())
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
                if (points.size == 1) "unknown" else string(properties, "direction"), string(properties, "operator_status"), schedule, outer, intervals, points)
        }
        return Snapshot(expectedId, window, features, credits)
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
               enabled: Boolean, driving: Boolean, foreground: Boolean): Card? {
        if (!enabled || !driving || !foreground || freshness !in setOf(RoadworksAdvisory.Freshness.FRESH, RoadworksAdvisory.Freshness.DELAYED) ||
            snapshot == null || !snapshot.window.contains(now) || fix == null || !fix.point.latitude.isFinite() || !fix.point.longitude.isFinite() ||
            fix.point.latitude !in -90.0..90.0 || fix.point.longitude !in -180.0..180.0 || !fix.accuracyM.isFinite() || fix.accuracyM !in 0.0..50.0 ||
            now < fix.at || java.time.Duration.between(fix.at, now).toMillis() > 3000) { reset(); return null }
        if (previousFix?.let { fix.at < it } == true) { reset(); return null }
        if (snapshotId != snapshot.id) { reset(); snapshotId = snapshot.id }
        val eligible = snapshot.features.filter { it.eligible(now) }.map { it to RoadworksAdvisory.distance(fix.point, it) }
        eligible.firstOrNull { it.first.id == selectedId && it.second <= 750 }?.let {
            previousFix = fix.at; return Card(it.first, it.second, freshness)
        }
        selectedId = null
        val candidate = eligible.filter { it.second <= 500 }.sortedWith(compareBy<Pair<RoadworksAdvisory.Feature, Double>> { if (it.first.kind == "closure") 0 else 1 }.thenBy { it.second }.thenBy { it.first.id }).firstOrNull()
        if (candidate == null) { pendingId = null; previousFix = fix.at; return null }
        val confirmed = pendingId == candidate.first.id && previousFix?.let { fix.at > it && java.time.Duration.between(it, fix.at).toMillis() <= 3000 } == true
        pendingId = candidate.first.id; previousFix = fix.at
        if (!confirmed) return null
        selectedId = candidate.first.id
        return Card(candidate.first, candidate.second, freshness)
    }
}

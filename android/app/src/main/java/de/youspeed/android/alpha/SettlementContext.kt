package de.youspeed.android.alpha

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot

internal data class SettlementContext(val insideCity: Boolean?, val source: String, val confidence: String) {
    val citySource: String get() = "settlement:$source:$confidence"
    val isHighConfidence: Boolean get() = confidence == "high" && insideCity != null

    companion object {
        fun unknown(source: String = "missing") = SettlementContext(null, source, "unknown")
    }
}

internal data class SettlementPoint(val lat: Double, val lon: Double)
internal data class SettlementSegment(
    val direction: Int,
    val context: SettlementContext,
    val points: List<SettlementPoint>,
)

/** Settlement direction is taken from the local directed edge, never an undirected road axis. */
internal object SettlementContextPolicy {
    private data class Projection(val distanceM: Double, val heading: Double)

    fun reliableHeading(heading: Double?, speed: Double?, accuracy: Double?): Double? = heading?.takeIf {
        it.isFinite() && it >= 0.0 && it < 360.0 &&
            speed != null && speed.isFinite() && speed >= 8.0 &&
            accuracy != null && accuracy.isFinite() && accuracy >= 0.0 && accuracy <= 45.0
    }

    private fun projection(point: SettlementPoint, points: List<SettlementPoint>): Projection? {
        val longitudeScale = 111320.0 * maxOf(0.01, cos(Math.toRadians(point.lat)))
        return points.zipWithNext().mapNotNull { (a, b) ->
            val ax = (a.lon - point.lon) * longitudeScale
            val ay = (a.lat - point.lat) * 111132.0
            val dx = (b.lon - a.lon) * longitudeScale
            val dy = (b.lat - a.lat) * 111132.0
            val lengthSquared = dx * dx + dy * dy
            if (!lengthSquared.isFinite() || lengthSquared <= 0.0) return@mapNotNull null
            val fraction = (-(ax * dx + ay * dy) / lengthSquared).coerceIn(0.0, 1.0)
            Projection(hypot(ax + fraction * dx, ay + fraction * dy),
                (Math.toDegrees(atan2(dx, dy)) + 360.0) % 360.0)
        }.minByOrNull { it.distanceM }
    }

    fun resolve(segments: List<SettlementSegment>, point: SettlementPoint, heading: Double?): SettlementContext {
        if (!point.lat.isFinite() || !point.lon.isFinite()) return SettlementContext.unknown()
        val projected = segments.filter { it.direction in -1..1 && it.points.all { point -> point.lat.isFinite() && point.lon.isFinite() } }
            .mapNotNull { segment -> projection(point, segment.points)?.let { segment to it } }
        val nearestDistance = projected.minOfOrNull { it.second.distanceM } ?: return SettlementContext.unknown()
        val nearest = projected.filter { it.second.distanceM <= nearestDistance + 0.05 }
        val applicable = nearest.filter { (segment, projection) ->
            if (segment.direction == 0 || heading == null) true else {
                val target = (projection.heading + if (segment.direction == -1) 180.0 else 0.0) % 360.0
                val delta = abs(heading - target)
                minOf(delta, 360.0 - delta) <= 45.0
            }
        }.map { it.first }
        if (heading == null) {
            val directions = applicable.map { it.direction }.toSet()
            if (0 !in directions && !directions.containsAll(setOf(-1, 1))) return SettlementContext.unknown()
        }
        val contexts = applicable.map { it.context }
        if (applicable.isEmpty()) return SettlementContext.unknown()
        val sources = setOf("zone_traffic", "maxspeed_type", "source_maxspeed", "traffic_sign", "urban_polygon", "landuse", "conflict", "missing")
        if (contexts.any { it.source !in sources }) return SettlementContext.unknown()
        if (contexts.map { it.insideCity }.distinct().size != 1) return SettlementContext.unknown("conflict")
        if (contexts.first().insideCity == null || contexts.any { it.confidence !in setOf("high", "low") }) {
            return SettlementContext.unknown(if (contexts.any { it.source == "conflict" }) "conflict" else "missing")
        }
        return SettlementContext(contexts.first().insideCity, contexts.minBy { it.source }.source,
            if (contexts.all { it.confidence == "high" }) "high" else "low")
    }

    fun legacy(fields: List<Pair<String, String?>>): SettlementContext? {
        val evidence = fields.flatMap { (source, value) ->
            value.orEmpty().split(Regex("[;\\s]+")).mapNotNull { token ->
                val normalized = token.trim().lowercase()
                when {
                    normalized == "urban" || normalized.endsWith(":urban") -> SettlementContext(true, source, "high")
                    normalized == "rural" || normalized.endsWith(":rural") -> SettlementContext(false, source, "high")
                    else -> null
                }
            }
        }
        if (evidence.isEmpty()) return null
        if (evidence.map { it.insideCity }.distinct().size > 1) return SettlementContext.unknown("conflict")
        return evidence.first()
    }
}

/** Queries only the selected way; no bundle-wide scans occur while driving. */
internal class SettlementContextResolver(private val db: SQLiteDatabase) {
    private fun tableExists(name: String): Boolean = db.rawQuery(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", arrayOf(name),
    ).use { it.moveToFirst() }
    private val version: String? = if (tableExists("metadata")) db.rawQuery(
        "SELECT value FROM metadata WHERE key='settlement_context_version'", null,
    ).use { if (it.moveToFirst()) it.getString(0) ?: "" else null } else null
    private val hasSegments = tableExists("settlement_segment")
    private val wayColumns = if (tableExists("ways")) db.rawQuery("PRAGMA table_info(ways)", null).use { cursor ->
        buildSet { while (cursor.moveToNext()) add(cursor.getString(1)) }
    } else emptySet()

    fun resolve(wayId: String?, lat: Double, lon: Double, heading: Double?, residentialInside: Boolean?): SettlementContext {
        if (wayId == null) return SettlementContext.unknown()
        if (version != null) {
            if (version != "1" || !hasSegments) return SettlementContext.unknown()
            val segments = runCatching {
                db.rawQuery(
                    "SELECT direction,inside_city,source,confidence,points_json FROM settlement_segment WHERE way_id=? ORDER BY segment_index,direction,segment_id",
                    arrayOf(wayId),
                ).use { cursor -> buildList {
                    while (cursor.moveToNext()) {
                        val insideCity = if (cursor.isNull(1) || cursor.getType(1) != Cursor.FIELD_TYPE_INTEGER) null
                            else when (cursor.getLong(1)) { 1L -> true; 0L -> false; else -> null }
                        val source = cursor.getString(2) ?: "missing"
                        val confidence = cursor.getString(3) ?: "unknown"
                        val points = parsePoints(cursor.getString(4))
                        val direction = cursor.getLong(0).takeIf { it in -1L..1L }?.toInt() ?: 2
                        add(SettlementSegment(direction, SettlementContext(insideCity, source, confidence), points))
                    }
                } }
            }.getOrElse { return SettlementContext.unknown() }
            return SettlementContextPolicy.resolve(segments, SettlementPoint(lat, lon), heading)
        }
        val fields = listOf("zone_traffic", "maxspeed_type", "source_maxspeed", "maxspeed").filter { it in wayColumns }
        if (fields.isNotEmpty()) {
            val explicit = db.rawQuery("SELECT ${fields.joinToString(",")} FROM ways WHERE way_id=?", arrayOf(wayId)).use { cursor ->
                if (!cursor.moveToFirst()) null else SettlementContextPolicy.legacy(fields.mapIndexed { index, field ->
                    // The wire contract has no separate source for symbolic maxspeed.
                    (if (field == "maxspeed") "maxspeed_type" else field) to cursor.getString(index)
                })
            }
            if (explicit != null) return explicit
        }
        return if (residentialInside == true) SettlementContext(true, "landuse", "low") else SettlementContext.unknown()
    }
}

private fun parsePoints(raw: String?): List<SettlementPoint> = runCatching {
    val points = JSONArray(raw ?: return emptyList())
    if (points.length() < 2) return emptyList()
    (0 until points.length()).map { index ->
        val pair = points.getJSONArray(index)
        require(pair.length() == 2 && pair.get(0) is Number && pair.get(1) is Number)
        val lat = pair.getDouble(0)
        val lon = pair.getDouble(1)
        require(lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0)
        SettlementPoint(lat, lon)
    }
}.getOrDefault(emptyList())

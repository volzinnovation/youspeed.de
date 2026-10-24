package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import kotlin.math.*

/** Bounded indexed reads. Never substitutes nearby artwork or way-speed boundaries for signs. */
internal class UpcomingSpeedLimitReader(private val db: SQLiteDatabase, private val allowMobiData: Boolean = true) {
    private data class Segment(val id: String?, val way: String, val direction: Int, val start: Double, val end: Double, val length: Double, val startNode: String? = null, val endNode: String? = null)
    private data class Event(val sign: String, val source: String, val snapshot: String, val kind: String,
        val status: String, val parameter: String, val station: Double, val speed: Double?, val direction: Int?, val unit: String?, val code: String) {
        val townEntry: Boolean get() = kind == "settlement_boundary" && code == "DE:310"
    }
    private val geometryCache = object : LinkedHashMap<String,List<Pair<Double,Double>>>(32,0.75f,true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String,List<Pair<Double,Double>>>?) = size > 64
    }
    private val relationCache = object : LinkedHashMap<String,Set<Long>>(32,0.75f,true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String,Set<Long>>?) = size > 128
    }
    private var deadlineNs = Long.MAX_VALUE
    private fun budget() { check(System.nanoTime() <= deadlineNs) { "upcoming_preview_budget" } }
    private val hasCityRule: Boolean by lazy { db.rawQuery("PRAGMA table_info(traffic_sign_way_rule)", null).use { c ->
        var found = false; while (c.moveToNext()) if (c.getString(1) == "inside_city") found = true; found
    } }
    private val capability: Boolean by lazy { runCatching { values("traffic_sign_capability")["version"] == "1" }.getOrDefault(false) }
    private val topology: Boolean by lazy { runCatching {
        val v = values("upcoming_path_capability")
        v["version"] == "1" && v["completeness"] == "complete" &&
            v["geometry_convention"] == "source_vertices_spherical_6371000m_v1" &&
            v["source_node_incidence"] == "complete_pbf_highway_v1" &&
            v["restrictions"] == "all_involved_ways_stop_v1" &&
            v["motorcar_profile"] == "existing_runtime_direction_v1" &&
            v["road_snapshot_sha256"]?.matches(Regex("[0-9a-fA-F]{64}")) == true && v["road_snapshot_sha256"] == values("traffic_sign_capability")["road_snapshot_sha256"]
    }.getOrDefault(false) }
    val hasTopology: Boolean get() = topology
    private fun values(table: String): Map<String, String> = db.rawQuery("SELECT key,value FROM $table", null).use { c -> buildMap { while (c.moveToNext()) put(c.getString(0), c.getString(1)) } }

    fun read(lat: Double, lon: Double, way: String?, direction: Int, stable: Boolean,
             accuracy: Double?, heading: Double?, headingAccuracy: Double?, groups: Set<Long>, speedKmh: Double? = null): UpcomingSpeedLimitSnapshot? = runCatching {
        if (!capability || way == null || !stable || direction !in setOf(-1, 1) || accuracy == null || !accuracy.isFinite() || accuracy !in 0.0..25.0 ||
            heading == null || !heading.isFinite() || (heading < 0 || heading >= 360) || headingAccuracy == null || !headingAccuracy.isFinite() || headingAccuracy !in 0.0..35.0) return null
        val lookaheadDistanceM = UpcomingSpeedLimitHorizon.distanceM(speedKmh)
        val began = System.nanoTime()
        deadlineNs = began + 25_000_000
        if (lat !in -85.0..85.0 || lon !in -180.0..180.0) return null
        val points = geometry(way) ?: return null
        val projection = projection(lat, lon, points) ?: return null
        val expected = (projection.second + if (direction < 0) 180 else 0) % 360
        if (abs((heading - expected + 540) % 360 - 180) > 35) return null
        val chainage = projection.first
        val length = points.zipWithNext().sumOf { distance(it.first, it.second) }
        var segment = if (topology) currentSegment(way, direction, chainage) ?: return null else Segment(null, way, direction, 0.0, length, length)
        var entryDistance = -direction * (chainage - if (direction > 0) segment.start else segment.end)
        var common = groups
        val paths = mutableListOf<UpcomingSpeedLimitPath>()
        val candidates = mutableListOf<UpcomingSpeedLimitCandidate>()
        val visited = mutableSetOf<String>()
        var reason = "distance_budget"
        var eventCount = 0
        for (index in 0 until UpcomingSpeedLimitHorizon.maxPathSegments) {
            budget()
            val segmentPoints = geometry(segment.way) ?: return null
            if (segment.end > segmentPoints.zipWithNext().sumOf { distance(it.first,it.second) } + 0.5) return null
            if (!visited.add(segment.id ?: "${segment.way}:${segment.direction}")) { reason = "cycle"; break }
            val memberships = if (segment.way == way) groups else relations(segment.way)
            if (segment.way != way) {
                common = common.intersect(memberships)
                if (common.isEmpty()) { reason = "relation_exit"; break }
            }
            val path = UpcomingSpeedLimitPath(segment.id, segment.way, segment.direction, segment.start, segment.end, entryDistance, memberships)
            paths += path
            // SQL already bounds stations to the horizon. Clamp cancellation at a reverse boundary
            // so subtraction cannot turn an exactly included station into a just-outside event.
            val events = events(segment, entryDistance, lookaheadDistanceM).map { it to min(lookaheadDistanceM, entryDistance + segment.direction * (it.station - if (segment.direction > 0) segment.start else segment.end)) }
                .filter { it.second > 0 && it.second <= lookaheadDistanceM }
                .sortedWith(compareBy<Pair<Event, Double>> { it.second }.thenBy { it.first.sign })
            eventCount += events.size
            check(eventCount <= 256) { "upcoming_preview_event_cap" }
            var offset = 0
            var blocked = false
            while (offset < events.size) {
                val cluster = events.drop(offset).takeWhile { abs(it.second - events[offset].second) <= 1.0 }
                offset += cluster.size
                val numeric = cluster.filter { it.first.kind == "speed_limit" }
                val targets = if (numeric.isNotEmpty()) numeric else cluster.filter { it.first.townEntry }
                val eligible = targets.mapNotNull { (event, remaining) -> candidate(event, segment, remaining, memberships, index < UpcomingSpeedLimitHorizon.maxPathSegments - 1) }
                // Read every actionable event. A rejected association or unsupported rule blocks targets beyond it.
                if (cluster.any { it.first.status != "accepted" || it.first.direction != segment.direction } ||
                    targets.size != eligible.size || eligible.map { it.speedKmh }.distinct().size > 1 ||
                    (numeric.isEmpty() && cluster.any { !it.first.townEntry }) || eligible.isEmpty()) {
                    reason = "unresolved_event"; blocked = true; break
                }
                candidates += eligible.distinctBy { it.identity }
            }
            if (blocked) break
            val exitDistance = entryDistance + segment.length
            if (exitDistance >= lookaheadDistanceM && candidates.none { it.originWayID == segment.way && abs(it.distanceM-exitDistance) < 1e-6 }) break
            if (!topology || common.isEmpty()) { reason = if (!topology) "same_way_only" else "no_relation"; break }
            val next = successor(segment)
            if (next == null) { reason = "topology_stop"; break }
            if (geometry(next.way) == null) { reason = "missing_geometry"; break }
            entryDistance = exitDistance
            segment = next
            if (index == UpcomingSpeedLimitHorizon.maxPathSegments - 1) reason = "work_cap"
        }
        budget()
        UpcomingSpeedLimitSnapshot(way, direction, chainage, groups, paths, candidates, reason,
            (System.nanoTime() - began) / 1e6, topology, lookaheadDistanceM)
    }.getOrNull()

    private fun relations(way: String): Set<Long> = relationCache.getOrPut(way) { db.rawQuery("SELECT m.continuity_group_id FROM way_continuity_membership m JOIN way_continuity_group g USING(continuity_group_id) WHERE m.way_id=? AND m.continuity_kind='route_relation_connected' AND g.continuity_kind='route_relation_connected'", arrayOf(way)).use { c -> buildSet { while (c.moveToNext()) add(c.getLong(0)) } } }
    private fun number(c: android.database.Cursor, index: Int): Boolean = c.getType(index) in setOf(android.database.Cursor.FIELD_TYPE_INTEGER,android.database.Cursor.FIELD_TYPE_FLOAT) && c.getDouble(index).isFinite()
    private fun decodeSegment(c: android.database.Cursor): Segment? {
        if(listOf(0,1,6,7).any { c.getType(it)!=android.database.Cursor.FIELD_TYPE_INTEGER || c.getLong(it)<=0 } ||
            c.getType(2)!=android.database.Cursor.FIELD_TYPE_INTEGER || listOf(3,4,5).any { !number(c,it) }) return null
        val value = Segment(c.getString(0),c.getString(1),c.getInt(2),c.getDouble(3),c.getDouble(4),c.getDouble(5),c.getString(6),c.getString(7))
        return value.takeIf { it.direction in setOf(-1,1) && it.start.isFinite() && it.end.isFinite() && it.length.isFinite() && it.start >= 0 && it.end > it.start && it.length > 0 && abs(it.end-it.start-it.length) < 0.5 && !it.startNode.isNullOrBlank() && !it.endNode.isNullOrBlank() }
    }
    private fun currentSegment(way: String, direction: Int, station: Double): Segment? = db.rawQuery("SELECT segment_id,way_id,direction,start_chainage_m,end_chainage_m,length_m,start_node_id,end_node_id FROM upcoming_path_segment WHERE way_id=? AND direction=? AND permission_status='allowed' AND start_chainage_m<=? AND end_chainage_m>=? ORDER BY start_chainage_m LIMIT 3", arrayOf(way, "$direction", "$station", "$station")).use { c ->
        val found = mutableListOf<Segment>(); while(c.moveToNext()) found += decodeSegment(c) ?: return null
        val owners = found.filter { if(direction>0) station < it.end-1e-6 else station > it.start+1e-6 }
        owners.singleOrNull() ?: if(owners.isEmpty()) found.singleOrNull() else null
    }
    private fun successor(segment: Segment): Segment? = db.rawQuery("SELECT s.segment_id,s.way_id,s.direction,s.start_chainage_m,s.end_chainage_m,s.length_m,s.start_node_id,s.end_node_id,n.via_node_id FROM upcoming_path_successor n JOIN upcoming_path_segment s ON s.segment_id=n.to_segment_id WHERE n.from_segment_id=? AND n.status='certified' AND n.proof='source_node_unbranched_unmerged_v1' AND s.permission_status='allowed'", arrayOf(segment.id)).use { c ->
        if(!c.moveToFirst() || c.getType(8)!=android.database.Cursor.FIELD_TYPE_INTEGER || c.getLong(8)<=0) null else decodeSegment(c)?.takeIf { segment.endNode == c.getString(8) && it.startNode == c.getString(8) }
    }
    private fun events(segment: Segment, entryDistance: Double, lookaheadDistanceM: Double): List<Event> {
        val entry = if(segment.direction>0) segment.start else segment.end
        val first = entry + segment.direction * max(0.0,-entryDistance)
        val last = entry + segment.direction * min(segment.length,lookaheadDistanceM-entryDistance)
        val result = db.rawQuery("SELECT s.sign_id,s.source_id,s.snapshot_sha256,s.kind,a.status,s.parameter_status,a.station_chainage_m,s.numeric_value,a.direction,s.unit,s.sign_code FROM traffic_sign_association a JOIN traffic_sign_runtime s USING(sign_id) WHERE a.way_id=? AND a.direction=? AND a.station_chainage_m>=? AND a.station_chainage_m<=? AND (s.kind IN ('speed_limit','settlement_boundary','speed_limit_end') OR s.sign_code='DE:282') ${if (allowMobiData) "" else " AND s.source_id <> 'mobidata-bw-vzk'"} ORDER BY a.station_chainage_m LIMIT 257", arrayOf(segment.way,"${segment.direction}","${min(first,last)}","${max(first,last)}")).use { c -> buildList {
            while(c.moveToNext()) { budget(); check(number(c,6) && c.getType(8)==android.database.Cursor.FIELD_TYPE_INTEGER); add(Event(c.getString(0),c.getString(1),c.getString(2),c.getString(3),c.getString(4),c.getString(5),c.getDouble(6),if(!number(c,7)) null else c.getDouble(7),c.getInt(8),if(c.isNull(9)) null else c.getString(9),c.getString(10))) }
        } }
        check(result.size <= 256) { "upcoming_preview_event_cap" }
        return result
    }
    private fun candidate(event: Event, segment: Segment, remaining: Double, groups: Set<Long>, mayContinue: Boolean): UpcomingSpeedLimitCandidate? {
        val townEntry = event.townEntry
        // The town rule supplies locality, while a separate posted limit at this station wins.
        // Unresolved/conditional OSM evidence cannot promise an unconditional implied 50.
        if (townEntry && event.source == "osm-settlement" && ConditionalSpeedRules.resolve(db, segment.way,
                segment.direction, 50, false, countryCode = "DE") != null) return null
        val speed = (if (townEntry) 50.0 else event.speed)?.takeIf { it.isFinite() && it in 1.0..300.0 && it == floor(it) }?.toInt() ?: return null
        if (event.status != "accepted" || (if (townEntry) event.parameter != "not_applicable" else event.parameter != "parsed_source_value" || event.unit != "km/h") || event.direction != segment.direction || event.source.isBlank() || event.snapshot.isBlank()) return null
        // The unique physical origin must own the post-station interval. Child-entry propagation is excluded.
        val wayLength=geometry(segment.way)?.zipWithNext()?.sumOf { distance(it.first,it.second) } ?: return null
        val normal = db.rawQuery("SELECT rule_id,sign_id,speed_kmh,station_chainage_m,association_status,lane_scope,start_chainage_m,end_chainage_m,${if (hasCityRule) "inside_city" else "NULL"} FROM traffic_sign_way_rule WHERE way_id=? AND direction=? AND ((direction=1 AND start_chainage_m<=? AND end_chainage_m>?) OR (direction=-1 AND start_chainage_m<? AND end_chainage_m>=?)) LIMIT 3", arrayOf(segment.way, "${segment.direction}", "${event.station}", "${event.station}", "${event.station}", "${event.station}")).use { c ->
            if (c.count != 1 || !c.moveToFirst() || listOf(3,6,7).any { !number(c,it) } || c.getString(1) != event.sign ||
                (if (townEntry) !c.isNull(2) || !number(c,8) || c.getInt(8) != 1 else !number(c,2) || c.getDouble(2) != speed.toDouble()) || abs(c.getDouble(3) - event.station) > 1e-6 || c.getString(4) != "accepted" || c.getString(5) != "all" || c.getDouble(6)<0 || c.getDouble(7)>wayLength+0.01 || c.getDouble(7)<=c.getDouble(6) || event.station<c.getDouble(6) || event.station>c.getDouble(7)) null
            else UpcomingSpeedLimitCandidate(event.sign, event.source, event.snapshot, c.getString(0), segment.way, segment.direction, event.station, speed, remaining)
        }
        if(normal != null) return normal
        if(!topology || !mayContinue || groups.isEmpty() || abs(event.station-(if(segment.direction>0) segment.end else segment.start)) > 1e-6) return null
        val next = successor(segment) ?: return null
        if(next.way == segment.way || groups.intersect(relations(next.way)).isEmpty()) return null
        val entry = if(next.direction>0) next.start else next.end
        val origin = db.rawQuery("SELECT rule_id,start_chainage_m,end_chainage_m,speed_kmh,association_status,lane_scope,${if (hasCityRule) "inside_city" else "NULL"} FROM traffic_sign_way_rule WHERE sign_id=? AND way_id=? AND direction=? AND abs(station_chainage_m-?)<0.000001 LIMIT 3", arrayOf(event.sign,segment.way,"${segment.direction}","${event.station}")).use { c ->
            if(c.count!=1 || !c.moveToFirst() || listOf(1,2).any { !number(c,it) } || c.getDouble(1)!=event.station || c.getDouble(2)!=event.station ||
                (if (townEntry) !c.isNull(3) || !number(c,6) || c.getInt(6) != 1 else !number(c,3) || c.getDouble(3)!=speed.toDouble()) || c.getString(4)!="accepted" || c.getString(5)!="all") null else c.getString(0)
        } ?: return null
        val nextLength=geometry(next.way)?.zipWithNext()?.sumOf { distance(it.first,it.second) } ?: return null
        val post = db.rawQuery("SELECT sign_id,speed_kmh,association_status,lane_scope,start_chainage_m,end_chainage_m,station_chainage_m,${if (hasCityRule) "inside_city" else "NULL"} FROM traffic_sign_way_rule WHERE way_id=? AND direction=? AND ((direction=1 AND start_chainage_m<=? AND end_chainage_m>?) OR (direction=-1 AND start_chainage_m<? AND end_chainage_m>=?)) LIMIT 3", arrayOf(next.way,"${next.direction}","$entry","$entry","$entry","$entry")).use { c -> c.count==1 && c.moveToFirst() && listOf(4,5,6).all { number(c,it) } && c.getString(0)==event.sign &&
            (if (townEntry) c.isNull(1) && number(c,7) && c.getInt(7)==1 else number(c,1) && c.getDouble(1)==speed.toDouble()) && c.getString(2)=="accepted" && c.getString(3)=="all" && c.getDouble(4)>=0 && c.getDouble(5)>c.getDouble(4) && c.getDouble(5)<=nextLength+0.01 && abs(c.getDouble(6)-entry)<1e-6 }
        return if(post) UpcomingSpeedLimitCandidate(event.sign,event.source,event.snapshot,origin,segment.way,segment.direction,event.station,speed,remaining) else null
    }
    private fun geometry(way: String): List<Pair<Double,Double>>? {
        geometryCache[way]?.let { return it }
        budget()
        val result = db.rawQuery("SELECT points_json FROM way_geom WHERE way_id=?", arrayOf(way)).use { c ->
        if (!c.moveToFirst()) null else JSONArray(c.getString(0)).let { a -> check(a.length() <= 32768); (0 until a.length()).map { a.getJSONArray(it).let { p -> p.getDouble(0) to p.getDouble(1) } }.takeIf { it.size >= 2 && it.all { p -> p.first.isFinite() && p.second.isFinite() } } }
    }
        budget()
        if(result != null && result.size <= 8192) {
            while(geometryCache.isNotEmpty() && geometryCache.values.sumOf { it.size } + result.size > 8192) geometryCache.remove(geometryCache.keys.first())
            geometryCache[way] = result
        }
        return result
    }
    private fun distance(a: Pair<Double,Double>, b: Pair<Double,Double>): Double {
        val x = sin(Math.toRadians(b.first - a.first) / 2).pow(2) + cos(Math.toRadians(a.first)) * cos(Math.toRadians(b.first)) * sin(Math.toRadians(b.second - a.second) / 2).pow(2)
        return 2 * 6371000.0 * asin(sqrt(x.coerceIn(0.0, 1.0)))
    }
    private fun projection(lat: Double, lon: Double, points: List<Pair<Double,Double>>): Pair<Double,Double>? {
        if (!lat.isFinite() || !lon.isFinite()) return null
        var chain = 0.0; var best = Double.POSITIVE_INFINITY; var result: Pair<Double,Double>? = null
        val scale = Math.PI / 180 * 6371008.8; val sx = scale * cos(Math.toRadians(lat))
        for ((a,b) in points.zipWithNext()) {
            budget()
            val ax = (a.second-lon)*sx; val ay = (a.first-lat)*scale; val dx=(b.second-a.second)*sx; val dy=(b.first-a.first)*scale
            val square=dx*dx+dy*dy; val len=distance(a,b)
            if (square > 0) { val f=(-(ax*dx+ay*dy)/square).coerceIn(0.0,1.0); val d=hypot(ax+f*dx,ay+f*dy)
                if(d<best){ best=d; result=(chain+f*len) to ((Math.toDegrees(atan2(dx,dy))+360)%360) } }
            chain += len
        }
        return result.takeIf { best <= 25 }
    }
}

package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StratifiedSQLiteBenchmarkInstrumentedTest {
    private data class Probe(
        val probeId: String,
        val stratum: String,
        val region: String,
        val lat: Double,
        val lon: Double,
        val heading: Double?,
    )

    private data class Schema(
        val waysKey: String,
        val rtreeKey: String,
        val geomKey: String,
        val tileKey: String?,
        val hasWayTile: Boolean,
        val hasRTree: Boolean,
    )

    private data class Candidate(
        val key: Long,
        val wayId: String,
        val highway: String?,
        val approxHeadingDeg: Double?,
        val minLon: Double,
        val minLat: Double,
        val maxLon: Double,
        val maxLat: Double,
        val pointsJson: String?,
    )

    @Test
    fun stratifiedLatencyBenchmarkFromInstrumentationArgs() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val args = InstrumentationRegistry.getArguments()
        val dbPath = args.getString("benchmark_db_path")
            ?: File(context.filesDir, "benchmark/speeds.sqlite").absolutePath
        val probePath = args.getString("benchmark_probe_csv_path")
            ?: File(context.filesDir, "benchmark/stratified_probe_points.csv").absolutePath
        val dbFile = File(dbPath)
        val probeFile = File(probePath)
        assumeTrue("Benchmark DB missing at $dbPath", dbFile.exists())
        assumeTrue("Probe CSV missing at $probePath", probeFile.exists())

        val regionFilter = args.getString("benchmark_region_filter")
            ?.split(",")
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            ?.toSet()
            ?: setOf("karlsruhe-regbez", "baden-wuerttemberg-bench")
        val repeats = max(1, args.getString("benchmark_repeats")?.toIntOrNull() ?: 5)
        val probes = loadProbes(probeFile).filter { regionFilter.isEmpty() || regionFilter.contains(it.region) }
        assumeTrue("No probes remain after region filter", probes.isNotEmpty())

        SQLiteDatabase.openDatabase(dbFile.absolutePath, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            val schema = querySchema(db)
            val hasWayTile = schema.hasWayTile
            val hasRTree = schema.hasRTree
            val tileSizeM = queryTileSize(db)
            val rows = JSONArray()

            for (probe in probes) {
                for (variant in listOf("v1", "v2", "v3", "v4")) {
                    val effectiveVariant = when (variant) {
                        "v2" -> if (hasWayTile) "v2" else "v1"
                        "v3" -> if (hasRTree) "v3" else "v1"
                        "v4" -> if (hasWayTile && hasRTree) "v4" else if (hasRTree) "v3" else if (hasWayTile) "v2" else "v1"
                        else -> "v1"
                    }
                    for (mode in listOf("bbox", "hybrid", "polyline")) {
                        runProbe(db, schema, probe, effectiveVariant, mode, tileSizeM)
                        val timings = ArrayList<Double>(repeats)
                        repeat(repeats) {
                            val started = System.nanoTime()
                            runProbe(db, schema, probe, effectiveVariant, mode, tileSizeM)
                            timings += (System.nanoTime() - started) / 1_000_000.0
                        }
                        rows.put(
                            JSONObject()
                                .put("probe_id", probe.probeId)
                                .put("stratum", probe.stratum)
                                .put("region", probe.region)
                                .put("variant", variant)
                                .put("effective_variant", effectiveVariant)
                                .put("distance_mode", mode)
                                .put("avg_ms", timings.average())
                                .put("p50_ms", percentile(timings, 0.50))
                                .put("min_ms", timings.minOrNull() ?: 0.0)
                                .put("max_ms", timings.maxOrNull() ?: 0.0)
                        )
                    }
                }
            }

            val payload = JSONObject()
                .put("dataset_kind", args.getString("benchmark_dataset_kind") ?: "external_sqlite")
                .put("db_path", dbFile.absolutePath)
                .put("db_size_bytes", dbFile.length())
                .put("has_way_tile_table", hasWayTile)
                .put("has_ways_rtree_table", hasRTree)
                .put("probe_count", probes.size)
                .put("rows", rows)
            File(context.filesDir, "benchmark/stratified_latency_result.json").apply {
                parentFile?.mkdirs()
                writeText(payload.toString())
            }
            val line = "ANDROID_STRATIFIED_BENCHMARK_JSON=$payload"
            println(line)
            Log.i("StratifiedSQLiteBench", line)
            assertTrue(rows.length() > 0)
        }
    }

    private fun runProbe(
        db: SQLiteDatabase,
        schema: Schema,
        probe: Probe,
        variant: String,
        mode: String,
        tileSizeM: Double,
    ): Long {
        val candidates = loadCandidates(db, schema, probe, variant, tileSizeM)
        val scored = candidates.map { candidate ->
            val headingPenalty = probe.heading?.let { heading ->
                candidate.approxHeadingDeg?.let { headingMismatchDeg(heading, it) * 2.0 } ?: 0.0
            } ?: 0.0
            val baseDistance = distanceToBBoxM(probe.lat, probe.lon, candidate)
            Scored(candidate, baseDistance, baseDistance + headingPenalty + if (candidate.highway == null) 30.0 else 0.0, headingPenalty)
        }.toMutableList()
        if (mode != "bbox") {
            val ordered = scored.indices.sortedBy { scored[it].score }
            val refine = if (mode == "hybrid") ordered.take(250) else ordered
            for (idx in refine) {
                val points = parsePoints(scored[idx].candidate.pointsJson) ?: continue
                val polyDistance = polylineDistanceM(probe.lat, probe.lon, points)
                val candidate = scored[idx]
                scored[idx] = candidate.copy(distanceM = polyDistance, score = polyDistance + candidate.headingPenalty)
            }
        }
        scored.sortWith(compareBy<Scored> { it.score }.thenBy { it.distanceM }.thenBy { it.candidate.wayId })
        return scored.take(5).fold(0L) { acc, item -> acc + item.candidate.key }
    }

    private data class Scored(
        val candidate: Candidate,
        val distanceM: Double,
        val score: Double,
        val headingPenalty: Double,
    )

    private fun loadCandidates(
        db: SQLiteDatabase,
        schema: Schema,
        probe: Probe,
        variant: String,
        tileSizeM: Double,
    ): List<Candidate> {
        val bounds = queryBounds(probe.lat, probe.lon, 1200.0)
        val rowIdExpr = "w.${schema.waysKey}"
        val wayIdExpr = "CAST(w.${schema.waysKey} AS TEXT)"
        val args = ArrayList<String>()
        val sql = when (variant) {
            "v2" -> {
                val tileKey = schema.tileKey ?: return loadCandidates(db, schema, probe, "v1", tileSizeM)
                val tile = tileForLonLat(probe.lon, probe.lat, tileSizeM)
                args += listOf("${tile.first - 1}", "${tile.first + 1}", "${tile.second - 1}", "${tile.second + 1}")
                args += listOf("${bounds.maxLon}", "${bounds.minLon}", "${bounds.maxLat}", "${bounds.minLat}", "5000")
                """
                WITH tile_rows AS (
                  SELECT DISTINCT $tileKey AS key_id FROM way_tile
                  WHERE tile_x BETWEEN ? AND ? AND tile_y BETWEEN ? AND ?
                )
                SELECT $rowIdExpr, $wayIdExpr, w.highway, w.approx_heading_deg,
                       w.min_lon, w.min_lat, w.max_lon, w.max_lat, g.points_json
                FROM tile_rows t
                JOIN ways w ON w.${schema.waysKey}=t.key_id
                LEFT JOIN way_geom g ON g.${schema.geomKey}=t.key_id
                WHERE w.min_lon <= ? AND w.max_lon >= ? AND w.min_lat <= ? AND w.max_lat >= ?
                LIMIT ?
                """.trimIndent()
            }
            "v3" -> {
                args += listOf("${bounds.maxLon}", "${bounds.minLon}", "${bounds.maxLat}", "${bounds.minLat}", "5000")
                """
                SELECT $rowIdExpr, $wayIdExpr, w.highway, w.approx_heading_deg,
                       w.min_lon, w.min_lat, w.max_lon, w.max_lat, g.points_json
                FROM ways_rtree r
                JOIN ways w ON w.${schema.waysKey}=r.${schema.rtreeKey}
                LEFT JOIN way_geom g ON g.${schema.geomKey}=w.${schema.waysKey}
                WHERE r.min_lon <= ? AND r.max_lon >= ? AND r.min_lat <= ? AND r.max_lat >= ?
                LIMIT ?
                """.trimIndent()
            }
            "v4" -> {
                val tileKey = schema.tileKey ?: return loadCandidates(db, schema, probe, "v3", tileSizeM)
                val tile = tileForLonLat(probe.lon, probe.lat, tileSizeM)
                args += listOf("${tile.first - 1}", "${tile.first + 1}", "${tile.second - 1}", "${tile.second + 1}")
                args += listOf("${bounds.maxLon}", "${bounds.minLon}", "${bounds.maxLat}", "${bounds.minLat}", "5000")
                """
                WITH tile_rows AS (
                  SELECT DISTINCT $tileKey AS key_id FROM way_tile
                  WHERE tile_x BETWEEN ? AND ? AND tile_y BETWEEN ? AND ?
                )
                SELECT $rowIdExpr, $wayIdExpr, w.highway, w.approx_heading_deg,
                       w.min_lon, w.min_lat, w.max_lon, w.max_lat, g.points_json
                FROM tile_rows t
                JOIN ways_rtree r ON r.${schema.rtreeKey}=t.key_id
                JOIN ways w ON w.${schema.waysKey}=t.key_id
                LEFT JOIN way_geom g ON g.${schema.geomKey}=t.key_id
                WHERE r.min_lon <= ? AND r.max_lon >= ? AND r.min_lat <= ? AND r.max_lat >= ?
                LIMIT ?
                """.trimIndent()
            }
            else -> {
                args += listOf("${bounds.maxLon}", "${bounds.minLon}", "${bounds.maxLat}", "${bounds.minLat}", "5000")
                """
                SELECT $rowIdExpr, $wayIdExpr, w.highway, w.approx_heading_deg,
                       w.min_lon, w.min_lat, w.max_lon, w.max_lat, g.points_json
                FROM ways w
                LEFT JOIN way_geom g ON g.${schema.geomKey}=w.${schema.waysKey}
                WHERE w.min_lon <= ? AND w.max_lon >= ? AND w.min_lat <= ? AND w.max_lat >= ?
                LIMIT ?
                """.trimIndent()
            }
        }

        db.rawQuery(sql, args.toTypedArray()).use { cursor ->
            val out = ArrayList<Candidate>()
            while (cursor.moveToNext()) {
                out += Candidate(
                    key = cursor.getLong(0),
                    wayId = cursor.getString(1),
                    highway = if (cursor.isNull(2)) null else cursor.getString(2),
                    approxHeadingDeg = if (cursor.isNull(3)) null else cursor.getDouble(3),
                    minLon = cursor.getDouble(4),
                    minLat = cursor.getDouble(5),
                    maxLon = cursor.getDouble(6),
                    maxLat = cursor.getDouble(7),
                    pointsJson = if (cursor.isNull(8)) null else cursor.getString(8),
                )
            }
            return out
        }
    }

    private fun querySchema(db: SQLiteDatabase): Schema {
        val waysKey = if (columnExists(db, "ways", "row_id")) "row_id" else "way_id"
        val hasWayTile = usableTableExists(db, "way_tile")
        val hasRTree = usableTableExists(db, "ways_rtree")
        fun keyFor(table: String): String {
            return when {
                columnExists(db, table, waysKey) -> waysKey
                columnExists(db, table, "row_id") -> "row_id"
                else -> "way_id"
            }
        }
        val tileKey = if (hasWayTile) keyFor("way_tile") else null
        return Schema(
            waysKey = waysKey,
            rtreeKey = if (hasRTree) keyFor("ways_rtree") else waysKey,
            geomKey = keyFor("way_geom"),
            tileKey = tileKey,
            hasWayTile = hasWayTile,
            hasRTree = hasRTree,
        )
    }

    private fun tableExists(db: SQLiteDatabase, table: String): Boolean {
        try {
            db.rawQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", arrayOf(table)).use {
                return it.moveToFirst()
            }
        } catch (_: SQLiteException) {
            return false
        }
    }

    private fun usableTableExists(db: SQLiteDatabase, table: String): Boolean {
        if (!tableExists(db, table)) return false
        try {
            db.rawQuery("SELECT * FROM $table LIMIT 0", emptyArray<String>()).use {
                return true
            }
        } catch (_: SQLiteException) {
            return false
        }
    }

    private fun columnExists(db: SQLiteDatabase, table: String, column: String): Boolean {
        try {
            db.rawQuery("PRAGMA table_info($table)", emptyArray<String>()).use { cursor ->
                while (cursor.moveToNext()) {
                    if (cursor.getString(1) == column) return true
                }
            }
        } catch (_: SQLiteException) {
            return false
        }
        return false
    }

    private fun queryTileSize(db: SQLiteDatabase): Double {
        return try {
            db.rawQuery("SELECT value FROM metadata WHERE key='tile_size_m' LIMIT 1", emptyArray<String>()).use {
                if (it.moveToFirst()) it.getString(0).toDoubleOrNull() ?: 4096.0 else 4096.0
            }
        } catch (_: Exception) {
            4096.0
        }
    }

    private fun loadProbes(file: File): List<Probe> {
        val lines = file.readLines().filter { it.isNotBlank() }
        if (lines.isEmpty()) return emptyList()
        val headers = lines.first().split(",")
        return lines.drop(1).mapNotNull { line ->
            val values = line.split(",", limit = headers.size)
            val row = headers.mapIndexedNotNull { idx, key -> values.getOrNull(idx)?.let { key to it } }.toMap()
            Probe(
                probeId = row["probe_id"] ?: return@mapNotNull null,
                stratum = row["stratum"] ?: return@mapNotNull null,
                region = row["region"] ?: return@mapNotNull null,
                lat = row["lat"]?.toDoubleOrNull() ?: return@mapNotNull null,
                lon = row["lon"]?.toDoubleOrNull() ?: return@mapNotNull null,
                heading = row["heading"]?.toDoubleOrNull() ?: row["heading_deg"]?.toDoubleOrNull(),
            )
        }
    }

    private fun queryBounds(lat: Double, lon: Double, radiusM: Double): Bounds {
        val degLat = radiusM / 111_132.0
        val cosLat = max(0.173648, abs(cos(Math.toRadians(lat))))
        val degLon = radiusM / (111_320.0 * cosLat)
        return Bounds(lon - degLon, lat - degLat, lon + degLon, lat + degLat)
    }

    private data class Bounds(val minLon: Double, val minLat: Double, val maxLon: Double, val maxLat: Double)

    private fun tileForLonLat(lon: Double, lat: Double, tileSizeM: Double): Pair<Int, Int> {
        val clampedLat = min(max(lat, -85.05112878), 85.05112878)
        val x = 6_378_137.0 * Math.toRadians(lon)
        val y = 6_378_137.0 * ln(tan(Math.PI / 4.0 + Math.toRadians(clampedLat) / 2.0))
        return Pair(floor(x / tileSizeM).toInt(), floor(y / tileSizeM).toInt())
    }

    private fun distanceToBBoxM(lat: Double, lon: Double, row: Candidate): Double {
        val clampedLon = min(max(lon, row.minLon), row.maxLon)
        val clampedLat = min(max(lat, row.minLat), row.maxLat)
        return haversineM(lat, lon, clampedLat, clampedLon)
    }

    private fun headingMismatchDeg(heading: Double, approxHeading: Double): Double {
        val raw = min(abs((heading - approxHeading) % 360.0), 360.0 - abs((heading - approxHeading) % 360.0))
        return min(raw, abs(180.0 - raw))
    }

    private fun parsePoints(raw: String?): List<Pair<Double, Double>>? {
        if (raw.isNullOrBlank()) return null
        val arr = JSONArray(raw)
        val points = ArrayList<Pair<Double, Double>>(arr.length())
        for (i in 0 until arr.length()) {
            val pair = arr.getJSONArray(i)
            if (pair.length() >= 2) {
                points += Pair(pair.getDouble(0), pair.getDouble(1))
            }
        }
        return points
    }

    private fun polylineDistanceM(lat: Double, lon: Double, points: List<Pair<Double, Double>>): Double {
        if (points.isEmpty()) return Double.POSITIVE_INFINITY
        if (points.size == 1) return haversineM(lat, lon, points[0].first, points[0].second)
        var best = Double.POSITIVE_INFINITY
        for (i in 0 until points.size - 1) {
            val d = pointToSegmentDistanceM(lat, lon, points[i].first, points[i].second, points[i + 1].first, points[i + 1].second)
            if (d < best) best = d
        }
        return best
    }

    private fun pointToSegmentDistanceM(lat: Double, lon: Double, lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val x1 = (lon1 - lon) * 111_320.0 * cos(Math.toRadians(lat))
        val y1 = (lat1 - lat) * 111_132.0
        val x2 = (lon2 - lon) * 111_320.0 * cos(Math.toRadians(lat))
        val y2 = (lat2 - lat) * 111_132.0
        val dx = x2 - x1
        val dy = y2 - y1
        if (dx == 0.0 && dy == 0.0) return hypot(x1, y1)
        val t = min(max((-(x1 * dx + y1 * dy)) / (dx * dx + dy * dy), 0.0), 1.0)
        return hypot(x1 + t * dx, y1 + t * dy)
    }

    private fun haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6_371_008.8
        val p1 = Math.toRadians(lat1)
        val p2 = Math.toRadians(lat2)
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2) * sin(dLat / 2) + cos(p1) * cos(p2) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * asin(sqrt(a))
    }

    private fun percentile(values: List<Double>, q: Double): Double {
        val sorted = values.sorted()
        val idx = min(max(floor(q * sorted.size).toInt(), 0), sorted.size - 1)
        return sorted[idx]
    }
}

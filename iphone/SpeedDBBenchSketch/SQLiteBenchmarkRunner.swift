import Foundation
import SQLite3

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

private struct CandidateRow {
    let rowID: Int64
    let wayID: String
    let highway: String?
    let approxHeadingDeg: Double?
    let minLon: Double
    let minLat: Double
    let maxLon: Double
    let maxLat: Double
    let pointsJSON: String?
}

private struct ScoredRow {
    let rowID: Int64
    let wayID: String
    let highway: String?
    var distanceM: Double
    var score: Double
    let headingPenalty: Double
    let unknownHighwayPenalty: Double
    let pointsJSON: String?
}

final class SQLiteBenchmarkRunner {
    private let dbPath: String

    init(dbPath: String) {
        self.dbPath = dbPath
    }

    func run(input: ProbeInput) throws -> BenchmarkReport {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: dbPath),
              let dbSize = attrs[.size] as? NSNumber else {
            throw BenchmarkError.ioError("Unable to read DB file attributes at \(dbPath)")
        }

        let encodedPath = dbPath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbPath
        let dbURI = "file:\(encodedPath)?mode=ro&immutable=1"
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbURI, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw BenchmarkError.sqliteError("sqlite3_open_v2 failed for \(dbPath)")
        }
        defer { sqlite3_close(db) }

        let hasWays = try tableExists(db: db, tableName: "ways")
        let hasWaysRTree = try tableExists(db: db, tableName: "ways_rtree")
        let hasWayTile = try tableExists(db: db, tableName: "way_tile")
        guard hasWays else {
            throw BenchmarkError.invalidDB("DB does not contain required table: ways")
        }

        let hasRTree = try queryCompileOption(db: db, option: "ENABLE_RTREE")
        let tileSizeM = try queryTileSize(db: db)

        var benchmarkMs: [String: [String: ProbeTiming]] = [:]
        for variant in BenchmarkVariant.allCases {
            var perMode: [String: ProbeTiming] = [:]
            let effectiveVariant = mapVariantForSchema(variant: variant, hasWaysRTree: hasWaysRTree, hasWayTile: hasWayTile)
            for mode in DistanceMode.allCases {
                let timings = try runRepeats(repeats: input.repeats) {
                    try self.runProbe(
                        db: db,
                        input: input,
                        variant: effectiveVariant,
                        mode: mode,
                        tileSizeM: tileSizeM
                    )
                }
                perMode[mode.rawValue] = summarize(timings)
            }
            benchmarkMs[variant.rawValue] = perMode
        }

        let formatter = ISO8601DateFormatter()
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return BenchmarkReport(
            generatedAtUTC: formatter.string(from: Date()),
            dbPath: dbPath,
            dbSizeBytes: dbSize.int64Value,
            hasRTreeSupport: hasRTree,
            hasWayTileTable: hasWayTile,
            input: input,
            benchmarkMs: benchmarkMs
        )
    }

    private func runProbe(
        db: OpaquePointer,
        input: ProbeInput,
        variant: BenchmarkVariant,
        mode: DistanceMode,
        tileSizeM: Double
    ) throws {
        let candidates = try loadCandidates(db: db, input: input, variant: variant, tileSizeM: tileSizeM)
        _ = rankCandidates(candidates: candidates, input: input, mode: mode)
    }

    private func mapVariantForSchema(
        variant: BenchmarkVariant,
        hasWaysRTree: Bool,
        hasWayTile: Bool
    ) -> BenchmarkVariant {
        switch variant {
        case .v1:
            return .v1
        case .v2:
            return hasWayTile ? .v2 : .v1
        case .v3:
            return hasWaysRTree ? .v3 : .v1
        case .v4:
            if hasWaysRTree && hasWayTile {
                return .v4
            }
            if hasWaysRTree {
                return .v3
            }
            if hasWayTile {
                return .v2
            }
            return .v1
        }
    }

    private func loadCandidates(
        db: OpaquePointer,
        input: ProbeInput,
        variant: BenchmarkVariant,
        tileSizeM: Double
    ) throws -> [CandidateRow] {
        let bounds = queryBounds(lat: input.lat, lon: input.lon, radiusM: input.searchRadiusM)

        switch variant {
        case .v1:
            let sql = """
            SELECT w.row_id, w.way_id, w.highway, w.approx_heading_deg,
                   w.min_lon, w.min_lat, w.max_lon, w.max_lat,
                   g.points_json
            FROM ways w
            LEFT JOIN way_geom g ON g.row_id = w.row_id
            WHERE w.min_lon <= ?1 AND w.max_lon >= ?2
              AND w.min_lat <= ?3 AND w.max_lat >= ?4
            LIMIT ?5
            """
            return try queryCandidates(
                db: db,
                sql: sql,
                bind: { stmt in
                    sqlite3_bind_double(stmt, 1, bounds.maxLon)
                    sqlite3_bind_double(stmt, 2, bounds.minLon)
                    sqlite3_bind_double(stmt, 3, bounds.maxLat)
                    sqlite3_bind_double(stmt, 4, bounds.minLat)
                    sqlite3_bind_int64(stmt, 5, Int64(input.maxCandidates))
                }
            )

        case .v2:
            let (tileX, tileY) = tileForLonLat(lon: input.lon, lat: input.lat, tileSizeM: tileSizeM)
            let tileXMin = tileX - input.tileRadius
            let tileXMax = tileX + input.tileRadius
            let tileYMin = tileY - input.tileRadius
            let tileYMax = tileY + input.tileRadius
            let sql = """
            WITH tile_rows AS (
              SELECT DISTINCT row_id
              FROM way_tile
              WHERE tile_x BETWEEN ?1 AND ?2
                AND tile_y BETWEEN ?3 AND ?4
            )
            SELECT w.row_id, w.way_id, w.highway, w.approx_heading_deg,
                   w.min_lon, w.min_lat, w.max_lon, w.max_lat,
                   g.points_json
            FROM tile_rows t
            JOIN ways w ON w.row_id = t.row_id
            LEFT JOIN way_geom g ON g.row_id = t.row_id
            WHERE w.min_lon <= ?5 AND w.max_lon >= ?6
              AND w.min_lat <= ?7 AND w.max_lat >= ?8
            LIMIT ?9
            """
            return try queryCandidates(
                db: db,
                sql: sql,
                bind: { stmt in
                    sqlite3_bind_int64(stmt, 1, Int64(tileXMin))
                    sqlite3_bind_int64(stmt, 2, Int64(tileXMax))
                    sqlite3_bind_int64(stmt, 3, Int64(tileYMin))
                    sqlite3_bind_int64(stmt, 4, Int64(tileYMax))
                    sqlite3_bind_double(stmt, 5, bounds.maxLon)
                    sqlite3_bind_double(stmt, 6, bounds.minLon)
                    sqlite3_bind_double(stmt, 7, bounds.maxLat)
                    sqlite3_bind_double(stmt, 8, bounds.minLat)
                    sqlite3_bind_int64(stmt, 9, Int64(input.maxCandidates))
                }
            )

        case .v3:
            let sql = """
            SELECT w.row_id, w.way_id, w.highway, w.approx_heading_deg,
                   w.min_lon, w.min_lat, w.max_lon, w.max_lat,
                   g.points_json
            FROM ways_rtree r
            JOIN ways w ON w.row_id = r.row_id
            LEFT JOIN way_geom g ON g.row_id = w.row_id
            WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
              AND r.min_lat <= ?3 AND r.max_lat >= ?4
            LIMIT ?5
            """
            return try queryCandidates(
                db: db,
                sql: sql,
                bind: { stmt in
                    sqlite3_bind_double(stmt, 1, bounds.maxLon)
                    sqlite3_bind_double(stmt, 2, bounds.minLon)
                    sqlite3_bind_double(stmt, 3, bounds.maxLat)
                    sqlite3_bind_double(stmt, 4, bounds.minLat)
                    sqlite3_bind_int64(stmt, 5, Int64(input.maxCandidates))
                }
            )

        case .v4:
            let (tileX, tileY) = tileForLonLat(lon: input.lon, lat: input.lat, tileSizeM: tileSizeM)
            let tileXMin = tileX - input.tileRadius
            let tileXMax = tileX + input.tileRadius
            let tileYMin = tileY - input.tileRadius
            let tileYMax = tileY + input.tileRadius
            let sql = """
            WITH tile_rows AS (
              SELECT DISTINCT row_id
              FROM way_tile
              WHERE tile_x BETWEEN ?1 AND ?2
                AND tile_y BETWEEN ?3 AND ?4
            )
            SELECT w.row_id, w.way_id, w.highway, w.approx_heading_deg,
                   w.min_lon, w.min_lat, w.max_lon, w.max_lat,
                   g.points_json
            FROM tile_rows t
            JOIN ways_rtree r ON r.row_id = t.row_id
            JOIN ways w ON w.row_id = t.row_id
            LEFT JOIN way_geom g ON g.row_id = t.row_id
            WHERE r.min_lon <= ?5 AND r.max_lon >= ?6
              AND r.min_lat <= ?7 AND r.max_lat >= ?8
            LIMIT ?9
            """
            return try queryCandidates(
                db: db,
                sql: sql,
                bind: { stmt in
                    sqlite3_bind_int64(stmt, 1, Int64(tileXMin))
                    sqlite3_bind_int64(stmt, 2, Int64(tileXMax))
                    sqlite3_bind_int64(stmt, 3, Int64(tileYMin))
                    sqlite3_bind_int64(stmt, 4, Int64(tileYMax))
                    sqlite3_bind_double(stmt, 5, bounds.maxLon)
                    sqlite3_bind_double(stmt, 6, bounds.minLon)
                    sqlite3_bind_double(stmt, 7, bounds.maxLat)
                    sqlite3_bind_double(stmt, 8, bounds.minLat)
                    sqlite3_bind_int64(stmt, 9, Int64(input.maxCandidates))
                }
            )
        }
    }

    private func queryCandidates(
        db: OpaquePointer,
        sql: String,
        bind: (OpaquePointer) -> Void
    ) throws -> [CandidateRow] {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw BenchmarkError.sqliteError("prepare failed (candidate query)")
        }
        defer { sqlite3_finalize(stmt) }
        bind(stmt)

        var out: [CandidateRow] = []
        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_ROW {
                out.append(
                    CandidateRow(
                        rowID: sqlite3_column_int64(stmt, 0),
                        wayID: cStringOrEmpty(sqlite3_column_text(stmt, 1)),
                        highway: cStringOptional(sqlite3_column_text(stmt, 2)),
                        approxHeadingDeg: sqlite3_column_type(stmt, 3) == SQLITE_NULL ? nil : sqlite3_column_double(stmt, 3),
                        minLon: sqlite3_column_double(stmt, 4),
                        minLat: sqlite3_column_double(stmt, 5),
                        maxLon: sqlite3_column_double(stmt, 6),
                        maxLat: sqlite3_column_double(stmt, 7),
                        pointsJSON: cStringOptional(sqlite3_column_text(stmt, 8))
                    )
                )
            } else if rc == SQLITE_DONE {
                break
            } else {
                throw BenchmarkError.sqliteError("step failed (candidate query)")
            }
        }
        return out
    }

    private func rankCandidates(
        candidates: [CandidateRow],
        input: ProbeInput,
        mode: DistanceMode
    ) -> Int64 {
        var scored: [ScoredRow] = []
        scored.reserveCapacity(candidates.count)

        for row in candidates {
            let distance = distanceToBBoxM(lat: input.lat, lon: input.lon, row: row)
            let headingDiff = headingMismatchDeg(heading: input.heading, approxHeading: row.approxHeadingDeg)
            let headingPenalty = headingDiff.map { $0 * input.headingWeight } ?? 0.0
            let unknownHighwayPenalty = row.highway == nil ? 30.0 : 0.0
            let score = distance + headingPenalty + unknownHighwayPenalty
            scored.append(
                ScoredRow(
                    rowID: row.rowID,
                    wayID: row.wayID,
                    highway: row.highway,
                    distanceM: distance,
                    score: score,
                    headingPenalty: headingPenalty,
                    unknownHighwayPenalty: unknownHighwayPenalty,
                    pointsJSON: row.pointsJSON
                )
            )
        }

        if mode != .bbox {
            let orderedIndices = scored.indices.sorted {
                scored[$0].score == scored[$1].score
                    ? (scored[$0].distanceM == scored[$1].distanceM ? scored[$0].wayID < scored[$1].wayID : scored[$0].distanceM < scored[$1].distanceM)
                    : scored[$0].score < scored[$1].score
            }
            let refineCount = mode == .hybrid ? min(input.polylineTopN, orderedIndices.count) : orderedIndices.count
            for idx in orderedIndices.prefix(refineCount) {
                guard let points = parsePointsJSON(scored[idx].pointsJSON), !points.isEmpty else {
                    continue
                }
                let poly = polylineDistanceM(lat: input.lat, lon: input.lon, points: points)
                scored[idx].distanceM = poly
                scored[idx].score = poly + scored[idx].headingPenalty + scored[idx].unknownHighwayPenalty
            }
        }

        scored.sort {
            if $0.score != $1.score { return $0.score < $1.score }
            if $0.distanceM != $1.distanceM { return $0.distanceM < $1.distanceM }
            return $0.wayID < $1.wayID
        }

        var checksum: Int64 = 0
        for row in scored.prefix(input.topK) {
            checksum = checksum &+ row.rowID
        }
        return checksum
    }

    private func queryCompileOption(db: OpaquePointer, option: String) throws -> Bool {
        let sql = "SELECT sqlite_compileoption_used(?1)"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw BenchmarkError.sqliteError("prepare failed (compile option)")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, option, -1, SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_ROW else {
            throw BenchmarkError.sqliteError("step failed (compile option)")
        }
        return sqlite3_column_int(stmt, 0) == 1
    }

    private func tableExists(db: OpaquePointer, tableName: String) throws -> Bool {
        let sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1 LIMIT 1"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw BenchmarkError.sqliteError("prepare failed (table exists)")
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, tableName, -1, SQLITE_TRANSIENT)
        return sqlite3_step(stmt) == SQLITE_ROW
    }

    private func queryTileSize(db: OpaquePointer) throws -> Double {
        let sql = "SELECT value FROM metadata WHERE key='tile_size_m' LIMIT 1"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return 4096.0
        }
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_step(stmt) == SQLITE_ROW else {
            return 4096.0
        }
        guard let cstr = sqlite3_column_text(stmt, 0), let value = Double(String(cString: cstr)), value > 0 else {
            return 4096.0
        }
        return value
    }

    private func runRepeats(repeats: Int, block: () throws -> Void) throws -> [Double] {
        var timings: [Double] = []
        for _ in 0..<repeats {
            let t0 = DispatchTime.now().uptimeNanoseconds
            try block()
            let t1 = DispatchTime.now().uptimeNanoseconds
            timings.append(Double(t1 - t0) / 1_000_000.0)
        }
        return timings
    }

    private func summarize(_ values: [Double]) -> ProbeTiming {
        let sorted = values.sorted()
        let avg = values.reduce(0.0, +) / Double(values.count)
        let p50 = sorted[sorted.count / 2]
        return ProbeTiming(
            avgMs: round(avg * 100.0) / 100.0,
            p50Ms: round(p50 * 100.0) / 100.0,
            minMs: round((sorted.first ?? 0.0) * 100.0) / 100.0,
            maxMs: round((sorted.last ?? 0.0) * 100.0) / 100.0
        )
    }

    private func queryBounds(lat: Double, lon: Double, radiusM: Double) -> (minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) {
        let degLat = radiusM / 111_132.0
        let cosLat = max(0.173648, abs(cos(lat * .pi / 180.0)))
        let degLon = radiusM / (111_320.0 * cosLat)
        return (lon - degLon, lat - degLat, lon + degLon, lat + degLat)
    }

    private func tileForLonLat(lon: Double, lat: Double, tileSizeM: Double) -> (Int, Int) {
        let clampedLat = min(max(lat, -85.05112878), 85.05112878)
        let x = 6_378_137.0 * lon * .pi / 180.0
        let y = 6_378_137.0 * log(tan(.pi / 4.0 + clampedLat * .pi / 360.0))
        return (Int(floor(x / tileSizeM)), Int(floor(y / tileSizeM)))
    }

    private func parsePointsJSON(_ raw: String?) -> [[Double]]? {
        guard let raw, !raw.isEmpty else {
            return nil
        }
        guard let data = raw.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [[Double]] else {
            return nil
        }
        return value
    }

    private func distanceToBBoxM(lat: Double, lon: Double, row: CandidateRow) -> Double {
        let clampedLon = min(max(lon, row.minLon), row.maxLon)
        let clampedLat = min(max(lat, row.minLat), row.maxLat)
        return haversineM(lat1: lat, lon1: lon, lat2: clampedLat, lon2: clampedLon)
    }

    private func haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double) -> Double {
        let r = 6_371_008.8
        let p1 = lat1 * .pi / 180.0
        let p2 = lat2 * .pi / 180.0
        let dLat = (lat2 - lat1) * .pi / 180.0
        let dLon = (lon2 - lon1) * .pi / 180.0
        let a = sin(dLat / 2) * sin(dLat / 2) + cos(p1) * cos(p2) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * asin(sqrt(a))
    }

    private func headingMismatchDeg(heading: Double, approxHeading: Double?) -> Double? {
        guard let approxHeading else {
            return nil
        }
        var raw = abs((heading - approxHeading).truncatingRemainder(dividingBy: 360.0))
        raw = min(raw, 360.0 - raw)
        return min(raw, abs(180.0 - raw))
    }

    private func polylineDistanceM(lat: Double, lon: Double, points: [[Double]]) -> Double {
        if points.isEmpty {
            return .infinity
        }
        if points.count == 1 {
            let p = points[0]
            if p.count < 2 {
                return .infinity
            }
            return haversineM(lat1: lat, lon1: lon, lat2: p[0], lon2: p[1])
        }

        var best = Double.infinity
        for i in 0..<(points.count - 1) {
            let p1 = points[i]
            let p2 = points[i + 1]
            if p1.count < 2 || p2.count < 2 {
                continue
            }
            let d = pointToSegmentDistanceM(
                lat: lat,
                lon: lon,
                lat1: p1[0],
                lon1: p1[1],
                lat2: p2[0],
                lon2: p2[1]
            )
            if d < best {
                best = d
            }
        }
        return best
    }

    private func pointToSegmentDistanceM(
        lat: Double,
        lon: Double,
        lat1: Double,
        lon1: Double,
        lat2: Double,
        lon2: Double
    ) -> Double {
        let (px, py) = xyMeters(lat: lat, lon: lon, lat0: lat, lon0: lon)
        let (x1, y1) = xyMeters(lat: lat1, lon: lon1, lat0: lat, lon0: lon)
        let (x2, y2) = xyMeters(lat: lat2, lon: lon2, lat0: lat, lon0: lon)
        let dx = x2 - x1
        let dy = y2 - y1
        if dx == 0.0 && dy == 0.0 {
            return hypot(px - x1, py - y1)
        }
        let tRaw = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        let t = min(max(tRaw, 0.0), 1.0)
        let projX = x1 + t * dx
        let projY = y1 + t * dy
        return hypot(px - projX, py - projY)
    }

    private func xyMeters(lat: Double, lon: Double, lat0: Double, lon0: Double) -> (Double, Double) {
        let metersPerDegLat = 111_132.0
        let metersPerDegLon = 111_320.0 * cos(lat0 * .pi / 180.0)
        let x = (lon - lon0) * metersPerDegLon
        let y = (lat - lat0) * metersPerDegLat
        return (x, y)
    }

    private func cStringOptional(_ ptr: UnsafePointer<UInt8>?) -> String? {
        guard let ptr else { return nil }
        return String(cString: ptr)
    }

    private func cStringOrEmpty(_ ptr: UnsafePointer<UInt8>?) -> String {
        guard let ptr else { return "" }
        return String(cString: ptr)
    }
}

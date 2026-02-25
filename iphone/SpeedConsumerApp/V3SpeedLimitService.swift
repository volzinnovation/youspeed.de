import Foundation
import SQLite3

final class V3SpeedLimitService {
    private let dbPath: String

    init(dbPath: String) {
        self.dbPath = dbPath
    }

    func lookupSpeedLimit(lat: Double, lon: Double, radiusM: Double = 120.0, maxCandidates: Int = 256) throws -> SpeedLimitResult {
        let t0 = DispatchTime.now().uptimeNanoseconds

        var db: OpaquePointer?
        let encodedPath = dbPath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbPath
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for \(dbPath)")
        }
        defer { sqlite3_close(db) }

        let bounds = queryBounds(lat: lat, lon: lon, radiusM: radiusM)
        let sql = """
        SELECT w.way_id, w.highway, w.maxspeed, w.maxspeed_type, w.source_maxspeed,
               w.min_lon, w.min_lat, w.max_lon, w.max_lat
        FROM ways_rtree r
        JOIN ways w ON w.row_id = r.row_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
        LIMIT ?5
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw ConsumerAppError.sqlite("prepare failed in lookup query")
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, bounds.maxLon)
        sqlite3_bind_double(stmt, 2, bounds.minLon)
        sqlite3_bind_double(stmt, 3, bounds.maxLat)
        sqlite3_bind_double(stmt, 4, bounds.minLat)
        sqlite3_bind_int64(stmt, 5, Int64(maxCandidates))

        // Bounding-box prefiltering can yield multiple nearby/overlapping ways for one point.
        // We intentionally resolve by nearest bbox distance and speed parsing, not by fixed way_id.
        var bestDistance = Double.infinity
        var bestSpeed: Int?
        var bestWayID: String?
        var candidateCount = 0
        var speedCandidateCount = 0
        var nearestCandidateDistance = Double.infinity
        var nearestSpeedCandidateDistance = Double.infinity

        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_DONE {
                break
            }
            if rc != SQLITE_ROW {
                throw ConsumerAppError.sqlite("step failed in lookup query")
            }

            let wayID = cStringOptional(sqlite3_column_text(stmt, 0))
            let highway = cStringOptional(sqlite3_column_text(stmt, 1))
            let maxspeedRaw = cStringOptional(sqlite3_column_text(stmt, 2))
            let maxspeedType = cStringOptional(sqlite3_column_text(stmt, 3))
            let sourceMaxspeed = cStringOptional(sqlite3_column_text(stmt, 4))
            let minLon = sqlite3_column_double(stmt, 5)
            let minLat = sqlite3_column_double(stmt, 6)
            let maxLon = sqlite3_column_double(stmt, 7)
            let maxLat = sqlite3_column_double(stmt, 8)

            candidateCount += 1
            let distance = distanceToBBoxM(lat: lat, lon: lon, minLon: minLon, minLat: minLat, maxLon: maxLon, maxLat: maxLat)
            if distance < nearestCandidateDistance {
                nearestCandidateDistance = distance
            }
            if distance > bestDistance {
                continue
            }

            let parsed = Self.deriveSpeedLimitKmh(maxspeed: maxspeedRaw, maxspeedType: maxspeedType, sourceMaxspeed: sourceMaxspeed, highway: highway)
            guard let speed = parsed else {
                continue
            }
            speedCandidateCount += 1
            if distance < nearestSpeedCandidateDistance {
                nearestSpeedCandidateDistance = distance
            }
            bestDistance = distance
            bestSpeed = speed
            bestWayID = wayID
        }

        let t1 = DispatchTime.now().uptimeNanoseconds
        let elapsedMs = Double(t1 - t0) / 1_000_000.0
        return SpeedLimitResult(
            speedLimitKmh: bestSpeed,
            wayID: bestWayID,
            queryTimeMs: elapsedMs,
            candidateCount: candidateCount,
            speedCandidateCount: speedCandidateCount,
            nearestCandidateDistanceM: nearestCandidateDistance.isFinite ? nearestCandidateDistance : nil,
            nearestSpeedCandidateDistanceM: nearestSpeedCandidateDistance.isFinite ? nearestSpeedCandidateDistance : nil
        )
    }

    static func deriveSpeedLimitKmh(maxspeed: String?, maxspeedType: String?, sourceMaxspeed: String?, highway: String?) -> Int? {
        if let maxspeed, let explicit = parseExplicitSpeed(maxspeed) {
            return explicit
        }

        let inherited = [maxspeedType, sourceMaxspeed].compactMap { $0 }.joined(separator: " ").lowercased()
        if inherited.contains("urban") {
            return 50
        }
        if inherited.contains("rural") {
            return 100
        }
        if inherited.contains("motorway") {
            return 130
        }

        switch highway?.lowercased() {
        case "motorway", "motorway_link":
            return 130
        case "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link":
            return 100
        case "living_street":
            return 10
        case "residential", "service", "unclassified", "road":
            return 50
        default:
            return nil
        }
    }

    static func parseExplicitSpeed(_ raw: String) -> Int? {
        let digits = raw.filter(\.isNumber)
        guard !digits.isEmpty, let value = Int(digits), value > 0 else {
            return nil
        }
        return value
    }

    private func queryBounds(lat: Double, lon: Double, radiusM: Double) -> (minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) {
        let degLat = radiusM / 111_132.0
        let cosLat = max(0.173648, abs(cos(lat * .pi / 180.0)))
        let degLon = radiusM / (111_320.0 * cosLat)
        return (lon - degLon, lat - degLat, lon + degLon, lat + degLat)
    }

    private func distanceToBBoxM(lat: Double, lon: Double, minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) -> Double {
        let clampedLon = min(max(lon, minLon), maxLon)
        let clampedLat = min(max(lat, minLat), maxLat)
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

    private func cStringOptional(_ cString: UnsafePointer<UInt8>?) -> String? {
        guard let cString else {
            return nil
        }
        return String(cString: cString)
    }
}

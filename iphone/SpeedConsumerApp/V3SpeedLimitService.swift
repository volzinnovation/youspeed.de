import Foundation
import SQLite3

final class V3SpeedLimitService {
    private let dbPath: String

    private struct WayCandidate {
        let wayID: String?
        let highway: String?
        let service: String?
        let tunnel: String?
        let streetName: String?
        let streetBaseName: String?
        let streetRef: String?
        let speedKmh: Int?
        let speedSource: DerivedSpeedSource
        let distanceM: Double
        let score: Double
    }

    private enum DerivedSpeedSource {
        case explicitTag
        case inheritedTag
        case highwayClass
        case none
    }

    private struct CityBoundaryCandidate {
        let rowID: Int64
        let adminLevel: Int
        let name: String?
        let minLon: Double
        let minLat: Double
        let maxLon: Double
        let maxLat: Double
    }

    private struct AreaCandidate {
        let name: String?
        let place: String?
        let boundary: String?
        let adminLevel: Int?
        let minLon: Double
        let minLat: Double
        let maxLon: Double
        let maxLat: Double
    }

    private struct CityContext {
        let insideCity: Bool?
        let cityName: String?
        let citySource: String?
        let candidateBoundaries: Int
        let containingBoundaries: Int
        let placeCandidates: Int
        let resolveMs: Double
    }

    private struct ResidentialContext {
        let insideCity: Bool?
        let candidatePolygons: Int
        let containingPolygons: Int
        let resolveMs: Double
    }

    private static let placeRank: [String: Int] = [
        "city": 0,
        "town": 1,
        "village": 2,
        "hamlet": 3,
    ]
    private static let nearestPlaceFallbackMaxDistanceM: Double = 5_000
    private static let headingWeightMPerDeg: Double = 1.8
    private static let headingMinSpeedKmh: Double = 8.0
    private static let headingMaxAccuracyDeg: Double = 45.0
    private static let preferredWayScoreSlackM: Double = 12.0
    private static let preferredWayDistanceMultiplier: Double = 1.6
    private static let preferredWayDistanceFloorM: Double = 70.0
    private static let inCityHighwayClasses: Set<String> = [
        "residential",
        "service",
        "crossing",
        "living_street",
    ]

    init(dbPath: String) {
        self.dbPath = dbPath
    }

    func lookupSpeedLimit(
        lat: Double,
        lon: Double,
        radiusM: Double = 50.0,
        maxCandidates: Int = 256,
        preferredWayID: String? = nil,
        headingDeg: Double? = nil,
        headingAccuracyDeg: Double? = nil,
        speedKmh: Double? = nil,
        horizontalAccuracyM: Double? = nil
    ) throws -> SpeedLimitResult {
        let t0 = DispatchTime.now().uptimeNanoseconds

        var db: OpaquePointer?
        let encodedPath = dbPath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbPath
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for \(dbPath)")
        }
        defer { sqlite3_close(db) }

        let wayGeomJoin = "LEFT JOIN way_geom g ON g.way_id = w.way_id"
        let bounds = queryBounds(lat: lat, lon: lon, radiusM: radiusM)
        let sql = """
        SELECT w.way_id, w.highway, w.street_name, w.ref, w.maxspeed, w.maxspeed_type, w.source_maxspeed,
               w.approx_heading_deg, w.service, w.tunnel,
               w.min_lon, w.min_lat, w.max_lon, w.max_lat, g.points_json
        FROM ways_rtree r
        JOIN ways w ON w.way_id = r.way_id
        \(wayGeomJoin)
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

        let resolvedHeading = normalizedHeadingDegrees(headingDeg)
        let headingForScoring = shouldUseHeading(
            headingDeg: resolvedHeading,
            headingAccuracyDeg: headingAccuracyDeg,
            speedKmh: speedKmh
        ) ? resolvedHeading : nil

        var bestCandidate: WayCandidate?
        var preferredCandidate: WayCandidate?
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
            let rawStreetName = cStringOptional(sqlite3_column_text(stmt, 2))
            let streetRef = cStringOptional(sqlite3_column_text(stmt, 3))
            let streetName = Self.formattedStreetDisplay(streetName: rawStreetName, ref: streetRef)
            let maxspeedRaw = cStringOptional(sqlite3_column_text(stmt, 4))
            let maxspeedType = cStringOptional(sqlite3_column_text(stmt, 5))
            let sourceMaxspeed = cStringOptional(sqlite3_column_text(stmt, 6))
            let approxHeadingDeg = sqlite3_column_type(stmt, 7) == SQLITE_NULL ? nil : sqlite3_column_double(stmt, 7)
            let service = cStringOptional(sqlite3_column_text(stmt, 8))
            let tunnel = cStringOptional(sqlite3_column_text(stmt, 9))
            let minLon = sqlite3_column_double(stmt, 10)
            let minLat = sqlite3_column_double(stmt, 11)
            let maxLon = sqlite3_column_double(stmt, 12)
            let maxLat = sqlite3_column_double(stmt, 13)
            let points = parseWayPoints(cStringOptional(sqlite3_column_text(stmt, 14)))

            candidateCount += 1
            let bboxDistance = distanceToBBoxM(
                lat: lat,
                lon: lon,
                minLon: minLon,
                minLat: minLat,
                maxLon: maxLon,
                maxLat: maxLat
            )
            let polylineDistance = polylineDistanceM(lat: lat, lon: lon, points: points)
            let distance = polylineDistance ?? bboxDistance
            if distance < nearestCandidateDistance {
                nearestCandidateDistance = distance
            }
            let parsedResult = Self.deriveSpeedLimitWithSource(
                maxspeed: maxspeedRaw,
                maxspeedType: maxspeedType,
                sourceMaxspeed: sourceMaxspeed,
                highway: highway
            )
            let parsed = parsedResult.speed
            if parsed != nil {
                speedCandidateCount += 1
                if distance < nearestSpeedCandidateDistance {
                    nearestSpeedCandidateDistance = distance
                }
            }

            // TODO(v5): Replace coarse per-way heading with segment-level heading + topology transitions.
            let headingPenalty: Double
            if let headingForScoring, let approxHeadingDeg {
                headingPenalty = headingMismatchDeg(headingDeg: headingForScoring, approxHeadingDeg: approxHeadingDeg) * Self.headingWeightMPerDeg
            } else {
                headingPenalty = 0.0
            }
            let score = distance + headingPenalty

            let candidate = WayCandidate(
                wayID: wayID,
                highway: highway,
                service: service,
                tunnel: tunnel,
                streetName: streetName,
                streetBaseName: rawStreetName,
                streetRef: streetRef,
                speedKmh: parsed,
                speedSource: parsedResult.source,
                distanceM: distance,
                score: score
            )
            if let currentBest = bestCandidate {
                if isBetterCandidate(candidate, than: currentBest) {
                    bestCandidate = candidate
                }
            } else {
                bestCandidate = candidate
            }
            if let preferredWayID, wayID == preferredWayID {
                if let existingPreferred = preferredCandidate {
                    if isBetterCandidate(candidate, than: existingPreferred) {
                        preferredCandidate = candidate
                    }
                } else {
                    preferredCandidate = candidate
                }
            }
        }

        let selected: WayCandidate?
        if let bestCandidate, let preferredCandidate {
            let accuracyBuffer = max(horizontalAccuracyM ?? 0.0, 0.0)
            let maxPreferredDistance = max(
                radiusM * Self.preferredWayDistanceMultiplier,
                Self.preferredWayDistanceFloorM
            ) + accuracyBuffer
            let keepPreferred = preferredCandidate.distanceM <= maxPreferredDistance &&
                preferredCandidate.score <= bestCandidate.score + Self.preferredWayScoreSlackM
            if keepPreferred {
                selected = preferredCandidate
            } else {
                selected = bestCandidate
            }
        } else {
            selected = preferredCandidate ?? bestCandidate
        }

        let cityContext = resolveCityContext(db: db, lat: lat, lon: lon)
        let insideCityDecision: (insideCity: Bool?, source: String?)
        let residentialContext: ResidentialContext
        if highwayImpliesInsideCity(selected?.highway) {
            insideCityDecision = (true, "highway_class_in_city")
            residentialContext = ResidentialContext(
                insideCity: nil,
                candidatePolygons: 0,
                containingPolygons: 0,
                resolveMs: 0.0
            )
        } else {
            residentialContext = resolveResidentialContext(db: db, lat: lat, lon: lon)
            if let insideCity = residentialContext.insideCity {
                insideCityDecision = (insideCity, "residential_polygon")
            } else {
                insideCityDecision = (nil, nil)
            }
        }

        let t1 = DispatchTime.now().uptimeNanoseconds
        let elapsedMs = Double(t1 - t0) / 1_000_000.0

        let effectiveSpeed: Int?
        if let selected, let matchedSpeed = selected.speedKmh {
            if selected.speedSource == .highwayClass, let insideCity = insideCityDecision.insideCity {
                // Highway class alone is weaker than explicit city/rural context.
                effectiveSpeed = insideCity ? 50 : 100
            } else {
                effectiveSpeed = matchedSpeed
            }
        } else if selected != nil, let insideCity = insideCityDecision.insideCity {
            // Keep inherited defaults only when a way match exists.
            effectiveSpeed = insideCity ? 50 : 100
        } else if insideCityDecision.insideCity == true {
            // Residential polygon containment can still provide a safe inner-city fallback.
            effectiveSpeed = 50
        } else {
            effectiveSpeed = nil
        }

        let selectedTunnelLike = isTruthyOSMTag(selected?.tunnel)

        return SpeedLimitResult(
            speedLimitKmh: effectiveSpeed,
            wayID: selected?.wayID,
            highway: selected?.highway,
            service: selected?.service,
            tunnel: selected?.tunnel,
            bridge: nil,
            covered: nil,
            location: nil,
            layer: nil,
            level: nil,
            isTunnelSegment: selectedTunnelLike,
            streetName: selected?.streetName,
            streetBaseName: selected?.streetBaseName,
            streetRef: selected?.streetRef,
            cityName: cityContext.cityName,
            insideCity: insideCityDecision.insideCity,
            citySource: insideCityDecision.source ?? cityContext.citySource,
            cityResolveMs: cityContext.resolveMs + residentialContext.resolveMs,
            cityCandidateBoundaries: cityContext.candidateBoundaries,
            cityContainingBoundaries: cityContext.containingBoundaries,
            cityPlaceCandidates: cityContext.placeCandidates,
            queryTimeMs: elapsedMs,
            candidateCount: candidateCount,
            speedCandidateCount: speedCandidateCount,
            nearestCandidateDistanceM: nearestCandidateDistance.isFinite ? nearestCandidateDistance : nil,
            nearestSpeedCandidateDistanceM: nearestSpeedCandidateDistance.isFinite ? nearestSpeedCandidateDistance : nil
        )
    }

    func lookupStreetNames(forWayIDs wayIDs: [String]) throws -> [String: String] {
        let uniqueWayIDs = Array(
            Set(
                wayIDs
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }
            )
        ).sorted()
        guard !uniqueWayIDs.isEmpty else {
            return [:]
        }

        var db: OpaquePointer?
        let encodedPath = dbPath.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbPath
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for \(dbPath)")
        }
        defer { sqlite3_close(db) }

        guard tableExists(db: db, name: "ways"), columnExists(db: db, table: "ways", column: "way_id") else {
            return [:]
        }

        let hasStreetName = columnExists(db: db, table: "ways", column: "street_name")
        let hasStreetRef = columnExists(db: db, table: "ways", column: "ref")
        guard hasStreetName || hasStreetRef else {
            return [:]
        }

        let streetSelect = hasStreetName ? "street_name" : "NULL"
        let refSelect = hasStreetRef ? "ref" : "NULL"
        var resolved: [String: String] = [:]

        let chunkSize = 200
        var cursor = 0
        while cursor < uniqueWayIDs.count {
            let end = min(cursor + chunkSize, uniqueWayIDs.count)
            let chunk = Array(uniqueWayIDs[cursor..<end])
            let placeholders = chunk.enumerated().map { "?\($0.offset + 1)" }.joined(separator: ",")
            let sql = """
            SELECT way_id, \(streetSelect) AS street_name, \(refSelect) AS ref
            FROM ways
            WHERE way_id IN (\(placeholders))
            """

            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw ConsumerAppError.sqlite("prepare failed in street lookup query")
            }
            defer { sqlite3_finalize(stmt) }

            for (index, wayID) in chunk.enumerated() {
                sqlite3_bind_text(stmt, Int32(index + 1), wayID, -1, SQLITE_TRANSIENT)
            }

            while true {
                let rc = sqlite3_step(stmt)
                if rc == SQLITE_DONE {
                    break
                }
                if rc != SQLITE_ROW {
                    throw ConsumerAppError.sqlite("step failed in street lookup query")
                }
                guard let wayID = cStringOptional(sqlite3_column_text(stmt, 0)) else {
                    continue
                }
                let streetName = cStringOptional(sqlite3_column_text(stmt, 1))
                let ref = cStringOptional(sqlite3_column_text(stmt, 2))
                if let display = Self.formattedStreetDisplay(streetName: streetName, ref: ref) {
                    resolved[wayID] = display
                }
            }

            cursor = end
        }

        return resolved
    }

    static func deriveSpeedLimitKmh(maxspeed: String?, maxspeedType: String?, sourceMaxspeed: String?, highway: String?) -> Int? {
        deriveSpeedLimitWithSource(
            maxspeed: maxspeed,
            maxspeedType: maxspeedType,
            sourceMaxspeed: sourceMaxspeed,
            highway: highway
        ).speed
    }

    private static func deriveSpeedLimitWithSource(
        maxspeed: String?,
        maxspeedType: String?,
        sourceMaxspeed: String?,
        highway: String?
    ) -> (speed: Int?, source: DerivedSpeedSource) {
        if let maxspeed, let explicit = parseExplicitSpeed(maxspeed) {
            return (explicit, .explicitTag)
        }

        let inherited = [maxspeedType, sourceMaxspeed].compactMap { $0 }.joined(separator: " ").lowercased()
        if inherited.contains("urban") {
            return (50, .inheritedTag)
        }
        if inherited.contains("rural") {
            return (100, .inheritedTag)
        }
        if inherited.contains("motorway") {
            return (130, .inheritedTag)
        }

        switch highway?.lowercased() {
        case "motorway", "motorway_link":
            return (130, .highwayClass)
        case "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link":
            return (100, .highwayClass)
        case "living_street":
            return (10, .highwayClass)
        case "residential", "service", "unclassified", "road":
            return (50, .highwayClass)
        default:
            return (nil, .none)
        }
    }

    static func parseExplicitSpeed(_ raw: String) -> Int? {
        let digits = raw.filter(\.isNumber)
        guard !digits.isEmpty, let value = Int(digits), value > 0 else {
            return nil
        }
        return value
    }

    static func formattedStreetDisplay(streetName: String?, ref: String?) -> String? {
        let normalizedStreet = streetName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedRef = ref?.trimmingCharacters(in: .whitespacesAndNewlines)
        let hasStreet = (normalizedStreet?.isEmpty == false)
        let hasRef = (normalizedRef?.isEmpty == false)

        if hasStreet, hasRef {
            return "\(normalizedStreet!) (\(normalizedRef!))"
        }
        if hasStreet {
            return normalizedStreet
        }
        if hasRef {
            return normalizedRef
        }
        return nil
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

    private func normalizedHeadingDegrees(_ headingDeg: Double?) -> Double? {
        guard var headingDeg, headingDeg.isFinite else {
            return nil
        }
        headingDeg.formTruncatingRemainder(dividingBy: 360.0)
        if headingDeg < 0.0 {
            headingDeg += 360.0
        }
        return headingDeg
    }

    private func shouldUseHeading(
        headingDeg: Double?,
        headingAccuracyDeg: Double?,
        speedKmh: Double?
    ) -> Bool {
        guard headingDeg != nil else {
            return false
        }
        if let speedKmh, speedKmh.isFinite, speedKmh < Self.headingMinSpeedKmh {
            return false
        }
        if let headingAccuracyDeg, headingAccuracyDeg.isFinite,
           headingAccuracyDeg >= 0.0, headingAccuracyDeg > Self.headingMaxAccuracyDeg {
            return false
        }
        return true
    }

    private func headingMismatchDeg(headingDeg: Double, approxHeadingDeg: Double) -> Double {
        var raw = abs((headingDeg - approxHeadingDeg).truncatingRemainder(dividingBy: 360.0))
        raw = min(raw, 360.0 - raw)
        return min(raw, abs(180.0 - raw))
    }

    private func parseWayPoints(_ raw: String?) -> [(Double, Double)] {
        guard let raw, let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let arr = json as? [Any] else {
            return []
        }

        var out: [(Double, Double)] = []
        out.reserveCapacity(arr.count)
        for element in arr {
            guard let pair = element as? [Any], pair.count >= 2 else {
                continue
            }
            guard let lat = pair[0] as? Double,
                  let lon = pair[1] as? Double else {
                continue
            }
            out.append((lat, lon))
        }
        return out
    }

    private func polylineDistanceM(lat: Double, lon: Double, points: [(Double, Double)]) -> Double? {
        if points.isEmpty {
            return nil
        }
        if points.count == 1 {
            let point = points[0]
            return haversineM(lat1: lat, lon1: lon, lat2: point.0, lon2: point.1)
        }
        var best = Double.infinity
        for i in 0..<(points.count - 1) {
            let p1 = points[i]
            let p2 = points[i + 1]
            let distance = pointToSegmentDistanceM(
                lat: lat,
                lon: lon,
                lat1: p1.0,
                lon1: p1.1,
                lat2: p2.0,
                lon2: p2.1
            )
            if distance < best {
                best = distance
            }
        }
        return best.isFinite ? best : nil
    }

    private func pointToSegmentDistanceM(
        lat: Double,
        lon: Double,
        lat1: Double,
        lon1: Double,
        lat2: Double,
        lon2: Double
    ) -> Double {
        let origin = toXYMeters(lat: lat, lon: lon, originLat: lat, originLon: lon)
        let start = toXYMeters(lat: lat1, lon: lon1, originLat: lat, originLon: lon)
        let end = toXYMeters(lat: lat2, lon: lon2, originLat: lat, originLon: lon)
        let dx = end.x - start.x
        let dy = end.y - start.y

        if dx == 0.0 && dy == 0.0 {
            return hypot(origin.x - start.x, origin.y - start.y)
        }
        let tNumerator = (origin.x - start.x) * dx + (origin.y - start.y) * dy
        let tDenominator = (dx * dx) + (dy * dy)
        let t = min(max(tNumerator / tDenominator, 0.0), 1.0)
        let projectionX = start.x + (t * dx)
        let projectionY = start.y + (t * dy)
        return hypot(origin.x - projectionX, origin.y - projectionY)
    }

    private func toXYMeters(lat: Double, lon: Double, originLat: Double, originLon: Double) -> (x: Double, y: Double) {
        let metersPerDegLat = 111_132.0
        let metersPerDegLon = 111_320.0 * cos(originLat * .pi / 180.0)
        let x = (lon - originLon) * metersPerDegLon
        let y = (lat - originLat) * metersPerDegLat
        return (x, y)
    }

    private func isBetterCandidate(_ lhs: WayCandidate, than rhs: WayCandidate) -> Bool {
        if lhs.score != rhs.score {
            return lhs.score < rhs.score
        }
        if lhs.distanceM != rhs.distanceM {
            return lhs.distanceM < rhs.distanceM
        }
        return (lhs.wayID ?? "~") < (rhs.wayID ?? "~")
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

    private func isTruthyOSMTag(_ raw: String?) -> Bool {
        guard let raw else {
            return false
        }
        let normalized = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.isEmpty {
            return false
        }
        return !["0", "false", "no", "off", "none"].contains(normalized)
    }

    private func tableExists(db: OpaquePointer, name: String) -> Bool {
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1 LIMIT 1"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return false
        }
        sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT)
        return sqlite3_step(stmt) == SQLITE_ROW
    }

    private func columnExists(db: OpaquePointer, table: String, column: String) -> Bool {
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "PRAGMA table_info(\(table));"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return false
        }
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let name = cStringOptional(sqlite3_column_text(stmt, 1)), name == column {
                return true
            }
        }
        return false
    }

    private func resolveCityContext(db: OpaquePointer, lat: Double, lon: Double) -> CityContext {
        let startNs = DispatchTime.now().uptimeNanoseconds

        let hasAreasTables = tableExists(db: db, name: "areas") && tableExists(db: db, name: "areas_rtree")
        if hasAreasTables {
            let areaResult = resolveCityContextFromAreas(db: db, lat: lat, lon: lon)
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
            return CityContext(
                insideCity: areaResult.insideCity,
                cityName: areaResult.cityName,
                citySource: areaResult.citySource,
                candidateBoundaries: areaResult.candidateBoundaries,
                containingBoundaries: areaResult.containingBoundaries,
                placeCandidates: areaResult.placeCandidates,
                resolveMs: elapsed
            )
        }

        // Compatibility fallback for older datasets that still expose dedicated
        // city boundary polygons instead of the consolidated areas table.
        let hasBoundaryTables = tableExists(db: db, name: "city_boundary") &&
            tableExists(db: db, name: "city_boundary_rtree") &&
            tableExists(db: db, name: "city_ring")
        if hasBoundaryTables {
            let hasPlaceTables = tableExists(db: db, name: "city_place") &&
                tableExists(db: db, name: "city_place_rtree")
            if let polygonResult = resolveCityContextWithPolygons(
                db: db,
                lat: lat,
                lon: lon,
                hasPlaceTables: hasPlaceTables
            ) {
                let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
                return CityContext(
                    insideCity: polygonResult.insideCity,
                    cityName: polygonResult.cityName,
                    citySource: polygonResult.citySource,
                    candidateBoundaries: polygonResult.candidateBoundaries,
                    containingBoundaries: polygonResult.containingBoundaries,
                    placeCandidates: polygonResult.placeCandidates,
                    resolveMs: elapsed
                )
            }
        }

        let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
        return CityContext(
            insideCity: nil,
            cityName: nil,
            citySource: "unavailable",
            candidateBoundaries: 0,
            containingBoundaries: 0,
            placeCandidates: 0,
            resolveMs: elapsed
        )
    }

    private func resolveResidentialContext(db: OpaquePointer, lat: Double, lon: Double, limitRows: Int = 1024) -> ResidentialContext {
        let startNs = DispatchTime.now().uptimeNanoseconds

        let hasAreasTables = tableExists(db: db, name: "areas") && tableExists(db: db, name: "areas_rtree")
        let hasResidentialColumn = columnExists(db: db, table: "areas", column: "residential")
        let hasPointsColumn = columnExists(db: db, table: "areas", column: "points_json")
        guard hasAreasTables, hasResidentialColumn, hasPointsColumn else {
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
            return ResidentialContext(insideCity: nil, candidatePolygons: 0, containingPolygons: 0, resolveMs: elapsed)
        }

        let sql = """
        SELECT a.residential, a.points_json
        FROM areas_rtree r
        JOIN areas a ON a.row_id = r.row_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
          AND a.residential IS NOT NULL
          AND trim(a.residential) <> ''
        LIMIT ?5
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
            return ResidentialContext(insideCity: nil, candidatePolygons: 0, containingPolygons: 0, resolveMs: elapsed)
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, lon)
        sqlite3_bind_double(stmt, 2, lon)
        sqlite3_bind_double(stmt, 3, lat)
        sqlite3_bind_double(stmt, 4, lat)
        sqlite3_bind_int64(stmt, 5, Int64(limitRows))

        var candidates = 0
        var containing = 0
        while sqlite3_step(stmt) == SQLITE_ROW {
            guard let pointsRaw = cStringOptional(sqlite3_column_text(stmt, 1)),
                  let ring = parseRingPoints(pointsRaw) else {
                continue
            }
            candidates += 1
            if pointInRing(lon: lon, lat: lat, ring: ring) {
                containing += 1
            }
        }

        let elapsed = Double(DispatchTime.now().uptimeNanoseconds - startNs) / 1_000_000.0
        let insideCity: Bool? = candidates > 0 ? (containing > 0) : nil
        return ResidentialContext(
            insideCity: insideCity,
            candidatePolygons: candidates,
            containingPolygons: containing,
            resolveMs: elapsed
        )
    }

    private func highwayImpliesInsideCity(_ highway: String?) -> Bool {
        guard let highway else {
            return false
        }
        return Self.inCityHighwayClasses.contains(
            highway.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        )
    }

    private func resolveCityContextWithPolygons(
        db: OpaquePointer,
        lat: Double,
        lon: Double,
        hasPlaceTables: Bool,
        limitRows: Int = 2048
    ) -> (insideCity: Bool, cityName: String?, citySource: String, candidateBoundaries: Int, containingBoundaries: Int, placeCandidates: Int)? {
        let boundarySQL = """
        SELECT b.row_id, b.admin_level, b.name, b.min_lon, b.min_lat, b.max_lon, b.max_lat
        FROM city_boundary_rtree r
        JOIN city_boundary b ON b.row_id = r.row_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
        LIMIT ?5
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, boundarySQL, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return nil
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, lon)
        sqlite3_bind_double(stmt, 2, lon)
        sqlite3_bind_double(stmt, 3, lat)
        sqlite3_bind_double(stmt, 4, lat)
        sqlite3_bind_int64(stmt, 5, Int64(limitRows))

        var boundaries: [CityBoundaryCandidate] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            boundaries.append(
                CityBoundaryCandidate(
                    rowID: sqlite3_column_int64(stmt, 0),
                    adminLevel: Int(sqlite3_column_int64(stmt, 1)),
                    name: cStringOptional(sqlite3_column_text(stmt, 2)),
                    minLon: sqlite3_column_double(stmt, 3),
                    minLat: sqlite3_column_double(stmt, 4),
                    maxLon: sqlite3_column_double(stmt, 5),
                    maxLat: sqlite3_column_double(stmt, 6)
                )
            )
        }

        var containing: [(adminLevel: Int, name: String?, bboxArea: Double)] = []
        for boundary in boundaries {
            if boundaryContainsPoint(db: db, boundaryRowID: boundary.rowID, lon: lon, lat: lat) {
                let bboxArea = max(boundary.maxLon - boundary.minLon, 0) * max(boundary.maxLat - boundary.minLat, 0)
                containing.append((adminLevel: boundary.adminLevel, name: boundary.name, bboxArea: bboxArea))
            }
        }

        if let best = containing.sorted(by: {
            if $0.adminLevel != $1.adminLevel { return $0.adminLevel < $1.adminLevel }
            if $0.bboxArea != $1.bboxArea { return $0.bboxArea < $1.bboxArea }
            return ($0.name ?? "~") < ($1.name ?? "~")
        }).first {
            return (
                insideCity: best.adminLevel == 8 || best.adminLevel == 9,
                cityName: best.name,
                citySource: "admin_polygon",
                candidateBoundaries: boundaries.count,
                containingBoundaries: containing.count,
                placeCandidates: 0
            )
        }

        if hasPlaceTables {
            let placeSQL = """
            SELECT p.name
            FROM city_place_rtree r
            JOIN city_place p ON p.row_id = r.row_id
            WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
              AND r.min_lat <= ?3 AND r.max_lat >= ?4
            ORDER BY ((p.lon - ?5) * (p.lon - ?6) + (p.lat - ?7) * (p.lat - ?8)) ASC
            LIMIT 16
            """
            var placeStmt: OpaquePointer?
            if sqlite3_prepare_v2(db, placeSQL, -1, &placeStmt, nil) == SQLITE_OK, let placeStmt {
                defer { sqlite3_finalize(placeStmt) }
                sqlite3_bind_double(placeStmt, 1, lon + 0.3)
                sqlite3_bind_double(placeStmt, 2, lon - 0.3)
                sqlite3_bind_double(placeStmt, 3, lat + 0.3)
                sqlite3_bind_double(placeStmt, 4, lat - 0.3)
                sqlite3_bind_double(placeStmt, 5, lon)
                sqlite3_bind_double(placeStmt, 6, lon)
                sqlite3_bind_double(placeStmt, 7, lat)
                sqlite3_bind_double(placeStmt, 8, lat)

                var names: [String] = []
                while sqlite3_step(placeStmt) == SQLITE_ROW {
                    if let name = cStringOptional(sqlite3_column_text(placeStmt, 0)), !name.isEmpty {
                        names.append(name)
                    }
                }
                if let cityName = names.first {
                    return (
                        insideCity: false,
                        cityName: cityName,
                        citySource: "place_fallback",
                        candidateBoundaries: boundaries.count,
                        containingBoundaries: 0,
                        placeCandidates: names.count
                    )
                }
            }
        }

        return (
            insideCity: false,
            cityName: nil,
            citySource: hasPlaceTables ? "admin_polygons_plus_places" : "admin_polygons",
            candidateBoundaries: boundaries.count,
            containingBoundaries: 0,
            placeCandidates: 0
        )
    }

    private func resolveCityContextFromAreas(
        db: OpaquePointer,
        lat: Double,
        lon: Double,
        limitRows: Int = 512
    ) -> (insideCity: Bool?, cityName: String?, citySource: String, candidateBoundaries: Int, containingBoundaries: Int, placeCandidates: Int) {
        let sql = """
        SELECT a.name, a.place, a.boundary, a.admin_level, a.min_lon, a.min_lat, a.max_lon, a.max_lat
        FROM areas_rtree r
        JOIN areas a ON a.row_id = r.row_id
        WHERE (
            r.min_lon <= ?1 AND r.max_lon >= ?2
            AND r.min_lat <= ?3 AND r.max_lat >= ?4
        ) OR (
            a.place IN ('city','town','village','hamlet')
            AND r.min_lon <= ?5 AND r.max_lon >= ?6
            AND r.min_lat <= ?7 AND r.max_lat >= ?8
        )
        LIMIT ?9
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return (nil, nil, "bbox_unavailable", 0, 0, 0)
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, lon)
        sqlite3_bind_double(stmt, 2, lon)
        sqlite3_bind_double(stmt, 3, lat)
        sqlite3_bind_double(stmt, 4, lat)
        sqlite3_bind_double(stmt, 5, lon + 0.3)
        sqlite3_bind_double(stmt, 6, lon - 0.3)
        sqlite3_bind_double(stmt, 7, lat + 0.3)
        sqlite3_bind_double(stmt, 8, lat - 0.3)
        sqlite3_bind_int64(stmt, 9, Int64(limitRows))

        var areas: [AreaCandidate] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let adminLevelRaw = cStringOptional(sqlite3_column_text(stmt, 3))
            let adminLevel = adminLevelRaw.flatMap(Int.init)
            areas.append(
                AreaCandidate(
                    name: cStringOptional(sqlite3_column_text(stmt, 0)),
                    place: cStringOptional(sqlite3_column_text(stmt, 1)),
                    boundary: cStringOptional(sqlite3_column_text(stmt, 2)),
                    adminLevel: adminLevel,
                    minLon: sqlite3_column_double(stmt, 4),
                    minLat: sqlite3_column_double(stmt, 5),
                    maxLon: sqlite3_column_double(stmt, 6),
                    maxLat: sqlite3_column_double(stmt, 7)
                )
            )
        }

        var containingAdmin: [(adminLevel: Int, bboxArea: Double, name: String)] = []
        var containingPlaces: [(rank: Int, distanceM: Double, name: String)] = []
        var nearbyPlaces: [(rank: Int, distanceM: Double, name: String)] = []

        for area in areas {
            guard let name = area.name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty else {
                continue
            }
            let inside = pointInBBox(lat: lat, lon: lon, minLon: area.minLon, minLat: area.minLat, maxLon: area.maxLon, maxLat: area.maxLat)
            let areaSize = max(area.maxLon - area.minLon, 0) * max(area.maxLat - area.minLat, 0)

            if area.boundary == "administrative", let level = area.adminLevel, (level == 8 || level == 9), inside {
                containingAdmin.append((adminLevel: level, bboxArea: areaSize, name: name))
            }

            if let place = area.place,
               let rank = Self.placeRank[place] {
                let centerLat = (area.minLat + area.maxLat) / 2
                let centerLon = (area.minLon + area.maxLon) / 2
                let distance = haversineM(lat1: lat, lon1: lon, lat2: centerLat, lon2: centerLon)
                nearbyPlaces.append((rank: rank, distanceM: distance, name: name))
                if inside {
                    containingPlaces.append((rank: rank, distanceM: distance, name: name))
                }
            }
        }

        if let best = containingAdmin.sorted(by: {
            if $0.adminLevel != $1.adminLevel { return $0.adminLevel < $1.adminLevel }
            if $0.bboxArea != $1.bboxArea { return $0.bboxArea < $1.bboxArea }
            return $0.name < $1.name
        }).first {
            return (
                true,
                best.name,
                "admin_bbox",
                containingAdmin.count,
                containingAdmin.count,
                nearbyPlaces.count
            )
        }

        if let best = containingPlaces.sorted(by: {
            if $0.rank != $1.rank { return $0.rank < $1.rank }
            if $0.distanceM != $1.distanceM { return $0.distanceM < $1.distanceM }
            return $0.name < $1.name
        }).first {
            return (
                true,
                best.name,
                "place_bbox",
                0,
                0,
                nearbyPlaces.count
            )
        }

        if let best = nearbyPlaces.sorted(by: {
            if $0.distanceM != $1.distanceM { return $0.distanceM < $1.distanceM }
            if $0.rank != $1.rank { return $0.rank < $1.rank }
            return $0.name < $1.name
        }).first, best.distanceM <= Self.nearestPlaceFallbackMaxDistanceM {
            return (
                false,
                best.name,
                "place_nearest",
                0,
                0,
                nearbyPlaces.count
            )
        }

        return (
            false,
            nil,
            "bbox_no_match",
            0,
            0,
            0
        )
    }

    private func boundaryContainsPoint(db: OpaquePointer, boundaryRowID: Int64, lon: Double, lat: Double) -> Bool {
        let sql = """
        SELECT outer_index, is_hole, points_json
        FROM city_ring
        WHERE boundary_row_id = ?1
        ORDER BY outer_index, is_hole, ring_index
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            return false
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_int64(stmt, 1, boundaryRowID)

        struct RingGroup {
            var outer: [(Double, Double)]?
            var holes: [[(Double, Double)]]
        }

        var groups: [Int: RingGroup] = [:]

        while sqlite3_step(stmt) == SQLITE_ROW {
            let outerIndex = Int(sqlite3_column_int64(stmt, 0))
            let isHole = Int(sqlite3_column_int64(stmt, 1))
            guard let pointsRaw = cStringOptional(sqlite3_column_text(stmt, 2)),
                  let ring = parseRingPoints(pointsRaw) else {
                continue
            }

            var group = groups[outerIndex] ?? RingGroup(outer: nil, holes: [])
            if isHole == 0 {
                group.outer = ring
            } else {
                group.holes.append(ring)
            }
            groups[outerIndex] = group
        }

        for group in groups.values {
            guard let outer = group.outer else {
                continue
            }
            if !pointInRing(lon: lon, lat: lat, ring: outer) {
                continue
            }
            let inHole = group.holes.contains { hole in
                pointInRing(lon: lon, lat: lat, ring: hole)
            }
            if !inHole {
                return true
            }
        }

        return false
    }

    private func parseRingPoints(_ raw: String) -> [(Double, Double)]? {
        guard let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let arr = json as? [Any] else {
            return nil
        }
        var out: [(Double, Double)] = []
        out.reserveCapacity(arr.count)
        for element in arr {
            guard let pair = element as? [Any], pair.count >= 2 else {
                continue
            }
            guard let lon = pair[0] as? Double,
                  let lat = pair[1] as? Double else {
                continue
            }
            out.append((lon, lat))
        }
        return out.count >= 4 ? out : nil
    }

    private func pointInRing(lon: Double, lat: Double, ring: [(Double, Double)]) -> Bool {
        if ring.count < 4 {
            return false
        }
        var inside = false
        for i in 0..<(ring.count - 1) {
            let (x1, y1) = ring[i]
            let (x2, y2) = ring[i + 1]
            if pointOnSegment(px: lon, py: lat, x1: x1, y1: y1, x2: x2, y2: y2) {
                return true
            }
            let crossesLatitude = ((y1 > lat) != (y2 > lat))
            let denom = (y2 - y1) == 0 ? 1e-30 : (y2 - y1)
            let xAtLat = (x2 - x1) * (lat - y1) / denom + x1
            if crossesLatitude && lon < xAtLat {
                inside.toggle()
            }
        }
        return inside
    }

    private func pointOnSegment(px: Double, py: Double, x1: Double, y1: Double, x2: Double, y2: Double) -> Bool {
        let eps = 1e-12
        let cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
        if abs(cross) > eps {
            return false
        }
        let dot = (px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)
        if dot < -eps {
            return false
        }
        let sqLen = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1)
        if dot - sqLen > eps {
            return false
        }
        return true
    }

    private func pointInBBox(lat: Double, lon: Double, minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) -> Bool {
        return minLat <= lat && lat <= maxLat && minLon <= lon && lon <= maxLon
    }
}

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

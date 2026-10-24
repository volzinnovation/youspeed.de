import Foundation
import SQLite3

/// Thirty seconds of approach at the measured driving speed, with the legacy 300 m floor.
/// This only bounds preview evidence; it does not change the current speed-limit authority.
enum UpcomingSpeedLimitHorizon {
    static func distanceM(speedKmh: Double?) -> Double {
        guard let speedKmh, speedKmh.isFinite, speedKmh >= 0 else { return 300 }
        let distance = speedKmh / 3.6 * 30
        return distance.isFinite ? max(300, distance) : 300
    }
}

/// Preview evidence only. It is never offered to the protected speed-reference policy.
struct UpcomingSpeedLimitCandidate: Codable, Equatable, Sendable {
    let signID: String
    let sourceID: String
    let snapshotSHA256: String
    let ruleID: String
    let originWayID: String
    let direction: Int
    let stationM: Double
    let speedKmh: Int
    let distanceM: Double
    var identity: String { sourceID + "|" + snapshotSHA256 + "|" + signID + "|" + String(direction) }
}

struct UpcomingSpeedLimitPath: Codable, Equatable, Sendable {
    let segmentID: String?
    let wayID: String
    let direction: Int
    let startM: Double
    let endM: Double
    /// Distance from this fix to the directed entry of the inspected interval.
    let entryDistanceM: Double
    let relationGroupIDs: [Int]
}

struct UpcomingSpeedLimitSnapshot: Codable, Equatable, Sendable {
    let wayID: String
    let direction: Int
    let chainageM: Double
    let relationGroupIDs: [Int]
    let path: [UpcomingSpeedLimitPath]
    let candidates: [UpcomingSpeedLimitCandidate]
    let reason: String
    let queryTimeMs: Double
    let topologyAvailable: Bool
    let lookaheadDistanceM: Double

    init(wayID: String, direction: Int, chainageM: Double, relationGroupIDs: [Int],
         path: [UpcomingSpeedLimitPath], candidates: [UpcomingSpeedLimitCandidate], reason: String,
         queryTimeMs: Double, topologyAvailable: Bool, lookaheadDistanceM: Double = 300) {
        self.wayID = wayID; self.direction = direction; self.chainageM = chainageM
        self.relationGroupIDs = relationGroupIDs; self.path = path; self.candidates = candidates
        self.reason = reason; self.queryTimeMs = queryTimeMs; self.topologyAvailable = topologyAvailable
        self.lookaheadDistanceM = lookaheadDistanceM
    }

    private enum CodingKeys: String, CodingKey {
        case wayID, direction, chainageM, relationGroupIDs, path, candidates, reason, queryTimeMs, topologyAvailable, lookaheadDistanceM
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.init(wayID: try values.decode(String.self, forKey: .wayID),
            direction: try values.decode(Int.self, forKey: .direction),
            chainageM: try values.decode(Double.self, forKey: .chainageM),
            relationGroupIDs: try values.decode([Int].self, forKey: .relationGroupIDs),
            path: try values.decode([UpcomingSpeedLimitPath].self, forKey: .path),
            candidates: try values.decode([UpcomingSpeedLimitCandidate].self, forKey: .candidates),
            reason: try values.decode(String.self, forKey: .reason),
            queryTimeMs: try values.decode(Double.self, forKey: .queryTimeMs),
            topologyAvailable: try values.decode(Bool.self, forKey: .topologyAvailable),
            lookaheadDistanceM: try values.decodeIfPresent(Double.self, forKey: .lookaheadDistanceM) ?? 300)
    }
}

/// Preserves passage memory independently of UI visibility, fix gaps and cancellation generations.
struct UpcomingSpeedLimitTracker {
    private struct Encounter {
        var candidate: UpcomingSpeedLimitCandidate
        var path: [UpcomingSpeedLimitPath]
    }
    private var bundle: String?
    private var lastTimestamp: Date?
    private var previous: UpcomingSpeedLimitSnapshot?
    private var frozenGroups = Set<Int>()
    private var scopeWayID: String?
    private var scopeLost = false
    private var encounters: [String: Encounter] = [:]
    private var consumed = Set<String>()
    private(set) var snapshot: UpcomingSpeedLimitSnapshot?
    private(set) var fixTimestamp: Date?
    private(set) var reason = "unsupported_bundle"

    mutating func reset() { self = Self() }
    mutating func invalidate(reason: String) {
        snapshot = nil; fixTimestamp = nil; self.reason = reason
    }

    func certifiesContinuation(_ next: UpcomingSpeedLimitSnapshot?, bundle expectedBundle: String? = nil) -> Bool {
        if let expectedBundle, bundle != expectedBundle { return false }
        guard let next, let previous, previous.topologyAvailable, next.topologyAvailable, !scopeLost,
              !frozenGroups.isEmpty, !frozenGroups.isDisjoint(with: next.relationGroupIDs) else { return false }
        return previous.path.contains {
            $0.wayID == next.wayID && $0.direction == next.direction
                && next.chainageM >= $0.startM - 0.01 && next.chainageM <= $0.endM + 0.01
                && !frozenGroups.isDisjoint(with: $0.relationGroupIDs)
        }
    }

    mutating func consume(_ next: UpcomingSpeedLimitSnapshot?, bundle: String, at: Date, now: Date = Date()) {
        guard at.timeIntervalSince1970.isFinite, now.timeIntervalSince(at).isFinite,
              now >= at, now.timeIntervalSince(at) <= 3 else { invalidate(reason: "stale_fix"); return }
        if self.bundle != bundle {
            // A temporary bundle switch must not erase an already consumed station.
            previous = nil; snapshot = nil; fixTimestamp = nil; lastTimestamp = nil
            encounters.removeAll(); frozenGroups = []; scopeWayID = nil; scopeLost = false
            self.bundle = bundle
        }
        guard lastTimestamp.map({ at >= $0 }) ?? true else { return }
        lastTimestamp = at
        guard let next, next.chainageM.isFinite, [-1, 1].contains(next.direction),
              next.lookaheadDistanceM.isFinite, next.lookaheadDistanceM >= 300 else {
            invalidate(reason: "unsupported_bundle"); return
        }
        let rawGroups = Set(next.relationGroupIDs)
        if let old = previous {
            let sameDirectedWay = old.wayID == next.wayID && old.direction == next.direction
            let onPath = old.topologyAvailable && next.topologyAvailable && old.path.contains {
                $0.wayID == next.wayID && $0.direction == next.direction
            }
            let shared = frozenGroups.intersection(rawGroups)
            let compatible = sameDirectedWay || (onPath && !shared.isEmpty)
            if !compatible {
                // A proved reversal/departure rearms; a jump farther along the same relation does not.
                let reversed = old.wayID == next.wayID && old.direction != next.direction
                if reversed || shared.isEmpty {
                    encounters.removeAll(); consumed.removeAll()
                    frozenGroups = rawGroups; scopeWayID = next.wayID; scopeLost = false
                } else {
                    // We cannot establish that a target from the old bounded proof is still ahead.
                    for identity in encounters.keys { consumed.insert(bundle + "|" + identity) }
                    encounters.removeAll(); frozenGroups = shared
                }
            } else if !frozenGroups.isEmpty {
                frozenGroups = shared
                if shared.isEmpty {
                    scopeLost = true; previous = next; invalidate(reason: "left_scope"); return
                }
            }
        } else { frozenGroups = rawGroups; scopeWayID = next.wayID }

        // Check cached targets before replacing them with the forward-only DB result.
        for (identity, encounter) in encounters {
            let target = encounter.candidate
            if target.originWayID == next.wayID && target.direction == next.direction {
                if Double(next.direction) * (next.chainageM - target.stationM) >= 0 { consumed.insert(bundle + "|" + identity) }
            } else if let targetIndex = encounter.path.firstIndex(where: {
                $0.wayID == target.originWayID && $0.direction == target.direction
                    && target.stationM >= $0.startM - 0.01 && target.stationM <= $0.endM + 0.01
            }), let currentIndex = encounter.path.firstIndex(where: {
                $0.wayID == next.wayID && $0.direction == next.direction
            }), currentIndex > targetIndex { consumed.insert(bundle + "|" + identity) }
        }
        encounters = encounters.filter { !consumed.contains(bundle + "|" + $0.key) }
        previous = next
        let scoped: [UpcomingSpeedLimitCandidate]
        if scopeLost || (frozenGroups.isEmpty && scopeWayID != next.wayID) { scoped = [] }
        else {
            scoped = next.candidates.filter { candidate in
                guard candidate.distanceM.isFinite, candidate.distanceM > 0, candidate.distanceM <= next.lookaheadDistanceM,
                      (1...300).contains(candidate.speedKmh), !consumed.contains(bundle + "|" + candidate.identity) else { return false }
                let prefix = next.path.prefix { path in
                    !(path.wayID == candidate.originWayID && path.direction == candidate.direction
                      && candidate.stationM >= path.startM - 0.01 && candidate.stationM <= path.endM + 0.01)
                }
                let onCurrentWay = candidate.originWayID == next.wayID && candidate.direction == next.direction
                    && Double(next.direction) * (candidate.stationM - next.chainageM) > 0
                    && next.path.contains { $0.wayID == candidate.originWayID && $0.direction == candidate.direction
                        && candidate.stationM >= $0.startM && candidate.stationM <= $0.endM }
                return onCurrentWay || (next.topologyAvailable && !frozenGroups.isEmpty && prefix.allSatisfy {
                    !frozenGroups.isDisjoint(with: $0.relationGroupIDs)
                } && next.path.contains { $0.wayID == candidate.originWayID && !frozenGroups.isDisjoint(with: $0.relationGroupIDs) })
            }
        }
        for candidate in scoped { encounters[candidate.identity] = .init(candidate: candidate, path: next.path) }
        // A bounded cache cannot forget a passage and then resurrect it: suspend further admission.
        guard encounters.count <= 64, consumed.count <= 1024 else { invalidate(reason: "budget_exceeded"); return }
        snapshot = .init(wayID: next.wayID, direction: next.direction, chainageM: next.chainageM,
            relationGroupIDs: frozenGroups.sorted(), path: next.path, candidates: scoped.sorted { ($0.distanceM, $0.signID) < ($1.distanceM, $1.signID) },
            reason: next.reason, queryTimeMs: next.queryTimeMs, topologyAvailable: next.topologyAvailable,
            lookaheadDistanceM: next.lookaheadDistanceM)
        fixTimestamp = at; reason = next.reason
    }

    mutating func selection(currentKmh: Int?, unlimited: Bool, currentIsStale: Bool,
                            obscured: Bool = false, now: Date = Date()) -> UpcomingSpeedLimitCandidate? {
        guard let at = fixTimestamp, now >= at, now.timeIntervalSince(at) < 3 else {
            invalidate(reason: "stale_fix"); return nil
        }
        guard !obscured, !currentIsStale, unlimited || currentKmh != nil else { reason = "current_unusable"; return nil }
        let selected = snapshot?.candidates.first { unlimited || $0.speedKmh < (currentKmh ?? 0) }
        reason = selected == nil ? (snapshot?.candidates.isEmpty == false ? "not_lower" : snapshot?.reason ?? "no_target") : "visible"
        return selected
    }
}

/// Indexed, bounded read of physical origins. Continued child rule stations are never signs.
enum UpcomingSpeedLimitBundle {
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    private struct Segment {
        let id: Int64?
        let way: String
        let direction: Int
        let start: Double
        let end: Double
        let length: Double
        let startNode: Int64?
        let endNode: Int64?
    }
    private struct Event {
        let id: String
        let status: String
        let station: Double
        let kind: String
        let code: String
        let value: Double?
        let unit: String?
        let parameter: String
        let source: String
        let sha: String
        var primary: Bool { ["speed_limit", "speed_limit_end", "settlement_boundary"].contains(kind) || code == "DE:282" }
        var townEntry: Bool { kind == "settlement_boundary" && code == "DE:310" }
    }
    private struct Rule {
        let id: String
        let sign: String
        let station: Double
        let start: Double
        let end: Double
        let speed: Double?
        let status: String
        let lane: String
        let insideCity: Double?
    }
    private static func string(_ s: OpaquePointer, _ i: Int32) -> String? { sqlite3_column_text(s, i).map { String(cString: $0) } }
    private static func number(_ s: OpaquePointer, _ i: Int32) -> Double? { sqlite3_column_type(s, i) == SQLITE_NULL ? nil : sqlite3_column_double(s, i) }
    private static func text(_ s: OpaquePointer, _ index: Int32, _ value: String) { sqlite3_bind_text(s, index, value, -1, transient) }
    private static func rows(_ db: OpaquePointer, _ resources: V3LookupResources, _ sql: String,
                             bind: (OpaquePointer) -> Void = { _ in }, body: (OpaquePointer) -> Void) -> Bool {
        var statement: OpaquePointer?
        guard resources.prepare(db, sql, -1, &statement, nil) == SQLITE_OK, let q = statement else { return false }
        defer { resources.release(q) }; bind(q)
        var status = sqlite3_step(q)
        while status == SQLITE_ROW { body(q); status = sqlite3_step(q) }
        return status == SQLITE_DONE
    }
    private static func capability(_ db: OpaquePointer, _ resources: V3LookupResources) -> Bool {
        resources.capability("upcoming_path:validated_v1") {
            var values: [String: String] = [:], source: String?
            guard rows(db, resources, "SELECT key,value FROM upcoming_path_capability", body: { q in
                if let k = string(q, 0), let v = string(q, 1) { values[k] = v }
            }), rows(db, resources, "SELECT value FROM traffic_sign_capability WHERE key='road_snapshot_sha256'", body: { source = string($0, 0) }) else { return false }
            return values["version"] == "1" && values["completeness"] == "complete"
                && values["geometry_convention"] == "source_vertices_spherical_6371000m_v1"
                && values["source_node_incidence"] == "complete_pbf_highway_v1"
                && values["restrictions"] == "all_involved_ways_stop_v1"
                && values["motorcar_profile"] == "existing_runtime_direction_v1"
                && source?.count == 64 && values["road_snapshot_sha256"] == source
        }
    }
    private static func groups(_ db: OpaquePointer, _ resources: V3LookupResources, _ way: String) -> Set<Int> {
        var result = Set<Int>()
        _ = rows(db, resources, """
            SELECT m.continuity_group_id FROM way_continuity_membership m JOIN way_continuity_group g USING(continuity_group_id)
            WHERE m.way_id=? AND g.continuity_kind='route_relation_connected'
            """, bind: { text($0, 1, way) }, body: { q in
                let value = Int(sqlite3_column_int64(q, 0)); if value > 0 { result.insert(value) }
            })
        return result
    }
    private static func decodeSegment(_ q: OpaquePointer) -> Segment? {
        let start = sqlite3_column_double(q, 3), end = sqlite3_column_double(q, 4), length = sqlite3_column_double(q, 7)
        let direction = Int(sqlite3_column_int(q, 2))
        guard [Int32(0), 1, 2, 5, 6].allSatisfy({ sqlite3_column_type(q, $0) == SQLITE_INTEGER }),
              sqlite3_column_int64(q, 0) > 0, sqlite3_column_int64(q, 1) > 0,
              sqlite3_column_int64(q, 5) > 0, sqlite3_column_int64(q, 6) > 0,
              sqlite3_column_type(q, 3) != SQLITE_NULL, sqlite3_column_type(q, 4) != SQLITE_NULL,
              sqlite3_column_type(q, 7) != SQLITE_NULL, length > 0,
              [start, end, length].allSatisfy(\.isFinite), start >= 0, end > start,
              abs(end - start - length) <= 0.5, [-1, 1].contains(direction), string(q, 8) == "allowed" else { return nil }
        return Segment(id: sqlite3_column_int64(q, 0), way: String(sqlite3_column_int64(q, 1)), direction: direction,
            start: start, end: end, length: length, startNode: sqlite3_column_int64(q, 5), endNode: sqlite3_column_int64(q, 6))
    }
    private static let segmentColumns = "segment_id,way_id,direction,start_chainage_m,end_chainage_m,start_node_id,end_node_id,length_m,permission_status"
    private static func initialSegment(_ db: OpaquePointer, _ resources: V3LookupResources, way: String, direction: Int, chainage: Double) -> Segment? {
        var found: [Segment] = []
        let boundary = direction == 1 ? "start_chainage_m<=? AND end_chainage_m>?" : "start_chainage_m<? AND end_chainage_m>=?"
        guard rows(db, resources, "SELECT " + segmentColumns + " FROM upcoming_path_segment WHERE way_id=? AND direction=? AND " + boundary + " LIMIT 2", bind: { q in
            text(q, 1, way); sqlite3_bind_int(q, 2, Int32(direction)); sqlite3_bind_double(q, 3, chainage); sqlite3_bind_double(q, 4, chainage)
        }, body: { if let value = decodeSegment($0) { found.append(value) } }), found.count == 1 else { return nil }
        return found[0]
    }
    private static func successor(_ db: OpaquePointer, _ resources: V3LookupResources, _ current: Segment) -> Segment? {
        guard let id = current.id else { return nil }
        var next: Int64?, via: Int64?
        guard rows(db, resources, "SELECT status,to_segment_id,via_node_id,proof FROM upcoming_path_successor WHERE from_segment_id=?", bind: { sqlite3_bind_int64($0, 1, id) }, body: { q in
            if string(q, 0) == "certified", string(q, 3) == "source_node_unbranched_unmerged_v1", sqlite3_column_type(q, 1) != SQLITE_NULL {
                next = sqlite3_column_int64(q, 1); via = sqlite3_column_int64(q, 2)
            }
        }), let next, via == current.endNode else { return nil }
        var result: Segment?
        _ = rows(db, resources, "SELECT " + segmentColumns + " FROM upcoming_path_segment WHERE segment_id=?", bind: { sqlite3_bind_int64($0, 1, next) }, body: { result = decodeSegment($0) })
        guard result?.startNode == via else { return nil }; return result
    }

    /// Produces provisional split geometry; the controller must verify the retained path certificate.
    /// Primary inventory admission stays unchanged.
    static func previewContext(db: OpaquePointer, resources: V3LookupResources, inventory: InventorySignLookup?,
        points: [(Double, Double)], latitude: Double, longitude: Double, heading: Double?, headingAccuracy: Double?,
        accuracy: Double?, fixUsable: Bool, preferredWayID: String?, matchedFixCount: Int,
        relationGroupIDs: [Int]) -> InventorySignLookup? {
        guard let inventory else { return nil }
        if inventory.direction != nil { return inventory }
        guard matchedFixCount >= 1, fixUsable, let way = inventory.wayID, let preferredWayID,
              preferredWayID != way, capability(db, resources), !Set(relationGroupIDs).isEmpty,
              !Set(relationGroupIDs).isDisjoint(with: groups(db, resources, preferredWayID)),
              let accuracy, accuracy.isFinite, (0...25).contains(accuracy),
              let heading, heading.isFinite, (0..<360).contains(heading),
              let headingAccuracy, headingAccuracy.isFinite, (0...35).contains(headingAccuracy),
              let projection = InventorySignBundle.projection(lat: latitude, lon: longitude, points: points), projection.distance <= 25 else { return nil }
        let direction = InventorySignBundle.angle(heading, projection.heading) <= 35 ? 1
            : InventorySignBundle.angle(heading, projection.heading + 180) <= 35 ? -1 : 0
        guard direction != 0 else { return nil }
        return .init(signs: [], activeRule: nil, wayID: way, direction: direction, chainageM: projection.chainage)
    }

    static func lookup(db: OpaquePointer, resources: V3LookupResources, inventory: InventorySignLookup?,
                       points: [(Double, Double)], relationGroupIDs: [Int], speedKmh: Double? = nil,
                       allowMobiData: Bool = true) -> UpcomingSpeedLimitSnapshot? {
        guard let inventory, let way = inventory.wayID, let direction = inventory.direction,
              let chainage = inventory.chainageM, chainage.isFinite, [-1, 1].contains(direction), points.count >= 2 else { return nil }
        let lookaheadDistance = UpcomingSpeedLimitHorizon.distanceM(speedKmh: speedKmh)
        let maximumSegments = 32
        let started = DispatchTime.now().uptimeNanoseconds
        let deadline = started + 25_000_000
        let topology = capability(db, resources)
        let length = zip(points, points.dropFirst()).reduce(0.0) { $0 + InventorySignBundle.distance($1.0.0, $1.0.1, $1.1.0, $1.1.1) * (6_371_000.0 / 6_371_008.8) }
        guard length.isFinite, length > 0, chainage >= 0, chainage <= length + 0.5 else { return nil }
        // A declared valid topology with no admitted current segment is an explicit stop.
        let initial = topology ? initialSegment(db, resources, way: way, direction: direction, chainage: chainage) : nil
        if topology && initial == nil {
            return .init(wayID: way, direction: direction, chainageM: chainage, relationGroupIDs: relationGroupIDs,
                path: [], candidates: [], reason: "ambiguous_path", queryTimeMs: Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000, topologyAvailable: true,
                lookaheadDistanceM: lookaheadDistance)
        }
        var current = initial ?? Segment(id: nil, way: way, direction: direction, start: 0, end: length, length: length, startNode: nil, endNode: nil)
        var origin = chainage, travelled = 0.0, visited = Set<String>(), candidates: [UpcomingSpeedLimitCandidate] = [], path: [UpcomingSpeedLimitPath] = []
        var common = Set(relationGroupIDs), reason = "no_target", includeEntry = false
        let canTraverse = topology && initial != nil
        let hasCityRule = resources.capability("upcoming:inside_city") {
            var found = false
            _ = rows(db, resources, "PRAGMA table_info(traffic_sign_way_rule)", body: { found = found || string($0, 1) == "inside_city" })
            return found
        }
        for segmentIndex in 0..<maximumSegments {
            guard DispatchTime.now().uptimeNanoseconds <= deadline else { reason = "budget_exceeded"; candidates = []; break }
            let key = current.id.map(String.init) ?? current.way + ":" + String(current.direction)
            guard visited.insert(key).inserted else { reason = "ambiguous_path"; break }
            if current.way != way {
                common.formIntersection(groups(db, resources, current.way))
                guard !common.isEmpty else { reason = "left_scope"; break }
            }
            let exit = current.direction == 1 ? current.end : current.start
            let available = max(0, Double(current.direction) * (exit - origin))
            let span = min(lookaheadDistance - travelled, available)
            let stop = origin + Double(current.direction) * span
            path.append(.init(segmentID: current.id.map(String.init), wayID: current.way, direction: current.direction,
                startM: min(origin, stop), endM: max(origin, stop), entryDistanceM: travelled, relationGroupIDs: common.sorted()))
            var events: [Event] = []
            let comparison = current.direction == 1 ? (includeEntry ? ">=" : ">") : (includeEntry ? "<=" : "<")
            let upper = current.direction == 1 ? "<=" : ">="
            let order = current.direction == 1 ? "ASC" : "DESC"
            let sql = """
                SELECT a.sign_id,a.status,a.station_chainage_m,s.kind,s.sign_code,s.numeric_value,s.unit,s.parameter_status,s.source_id,s.snapshot_sha256
                FROM traffic_sign_association a JOIN traffic_sign_runtime s ON s.sign_id=a.sign_id
                WHERE a.way_id=? AND a.direction=? AND a.station_chainage_m \(comparison) ? AND a.station_chainage_m \(upper) ?
                  \(allowMobiData ? "" : "AND s.source_id <> 'mobidata-bw-vzk'")
                ORDER BY a.station_chainage_m \(order),a.sign_id LIMIT 257
                """
            guard rows(db, resources, sql, bind: { q in
                text(q, 1, current.way); sqlite3_bind_int(q, 2, Int32(current.direction)); sqlite3_bind_double(q, 3, origin); sqlite3_bind_double(q, 4, stop)
            }, body: { q in
                let station = sqlite3_column_double(q, 2)
                if station.isFinite { events.append(.init(id: string(q, 0) ?? "", status: string(q, 1) ?? "unknown", station: station,
                    kind: string(q, 3) ?? "", code: string(q, 4) ?? "", value: number(q, 5), unit: string(q, 6), parameter: string(q, 7) ?? "", source: string(q, 8) ?? "", sha: string(q, 9) ?? "")) }
            }) else { reason = "unsupported_bundle"; break }
            if events.count > 256 { reason = "budget_exceeded"; break }
            var rules: [Rule] = []
            guard rows(db, resources, "SELECT rule_id,sign_id,station_chainage_m,start_chainage_m,end_chainage_m,speed_kmh,association_status,lane_scope,\(hasCityRule ? "inside_city" : "NULL") FROM traffic_sign_way_rule WHERE way_id=? AND direction=? LIMIT 1025", bind: { q in text(q, 1, current.way); sqlite3_bind_int(q, 2, Int32(current.direction)) }, body: { q in
                rules.append(.init(id: string(q, 0) ?? "", sign: string(q, 1) ?? "", station: sqlite3_column_double(q, 2), start: sqlite3_column_double(q, 3), end: sqlite3_column_double(q, 4), speed: number(q, 5), status: string(q, 6) ?? "", lane: string(q, 7) ?? "", insideCity: number(q, 8)))
            }), rules.count <= 1024 else { reason = "budget_exceeded"; break }
            var clusters: [[Event]] = []
            for event in events where event.primary {
                if let first = clusters.last?.first, abs(first.station - event.station) <= 1 { clusters[clusters.count - 1].append(event) }
                else { clusters.append([event]) }
            }
            var blocked = false
            for cluster in clusters {
                guard cluster.allSatisfy({ $0.status == "accepted" }) else { reason = "conflict"; blocked = true; break }
                let speeds = cluster.filter { $0.kind == "speed_limit" }
                let values = Set(speeds.compactMap(\.value))
                guard values.count <= 1 else { reason = "conflict"; blocked = true; break }
                // A town entry is a physical source-backed default, not an invented numeric sign.
                // A fresh posted limit at the same station owns the post-boundary interval.
                let targets = speeds.isEmpty ? cluster.filter(\.townEntry) : speeds
                if targets.isEmpty || (speeds.isEmpty && cluster.contains(where: { !$0.townEntry })) {
                    reason = "unresolved_applicability"; blocked = true; break
                }
                var clusterCandidates: [UpcomingSpeedLimitCandidate] = []
                for event in targets {
                    let townEntry = event.townEntry
                    // Conditional OSM context cannot become an unconditional implied 50.
                    // An independently accepted government boundary keeps its higher source priority.
                    if townEntry && event.source == "osm-settlement",
                       ConditionalSpeedRules.resolve(db: db, wayID: current.way, direction: current.direction,
                           baseKmh: 50, baseUnlimited: false, countryCode: "DE") != nil { blocked = true; break }
                    guard let value = townEntry ? 50.0 : event.value, value.isFinite, value.rounded() == value, (1...300).contains(value),
                          (townEntry ? event.parameter == "not_applicable" : event.parameter == "parsed_source_value" && event.unit == "km/h"), !event.id.isEmpty,
                          !event.source.isEmpty, !event.sha.isEmpty else { blocked = true; break }
                    let origins = rules.filter { $0.sign == event.id && $0.status == "accepted" && $0.lane == "all"
                        && abs($0.station - event.station) <= 0.01
                        && (townEntry ? $0.speed == nil && $0.insideCity == 1 : $0.speed == value)
                        && [$0.start, $0.end, $0.station].allSatisfy(\.isFinite) && $0.start >= 0 && $0.end >= $0.start }
                    guard origins.count == 1, let rule = origins.first else { blocked = true; break }
                    // Check the actual immediately-after station offer, including overlapping rules.
                    let probe = event.station + Double(current.direction) * 0.001
                    let offers = rules.filter {
                        current.direction == 1 ? $0.start <= probe && $0.end > probe : $0.start < probe && $0.end >= probe
                    }
                    var continuing = offers.count == 1 && offers.first?.id == rule.id
                    if !continuing, abs(event.station - exit) <= 0.01, canTraverse,
                       !common.isEmpty, let next = successor(db, resources, current),
                       !common.isDisjoint(with: groups(db, resources, next.way)) {
                        let entry = next.direction == 1 ? next.start : next.end
                        let nextProbe = entry + Double(next.direction) * 0.001
                        var childOffers: [(String, Double?, String, String, Double?)] = []
                        let childSQL = "SELECT sign_id,speed_kmh,association_status,lane_scope,\(hasCityRule ? "inside_city" : "NULL") FROM traffic_sign_way_rule WHERE way_id=? AND direction=? AND start_chainage_m<=? AND end_chainage_m>=? LIMIT 257"
                        let ok = rows(db, resources, childSQL, bind: { q in
                            text(q, 1, next.way); sqlite3_bind_int(q, 2, Int32(next.direction))
                            sqlite3_bind_double(q, 3, nextProbe); sqlite3_bind_double(q, 4, nextProbe)
                        }, body: { q in childOffers.append((string(q, 0) ?? "", number(q, 1), string(q, 2) ?? "", string(q, 3) ?? "", number(q, 4))) })
                        continuing = ok && childOffers.count == 1 && childOffers.first?.0 == event.id
                            && (townEntry ? childOffers.first?.1 == nil && childOffers.first?.4 == 1 : childOffers.first?.1 == value)
                            && childOffers.first?.2 == "accepted" && childOffers.first?.3 == "all"
                    }
                    guard continuing else { blocked = true; break }
                    // The SQL range already proves the horizon. Clamp cancellation at the
                    // exact reverse boundary, where subtraction can add a fraction of an ulp.
                    let distance = min(lookaheadDistance, travelled + Double(current.direction) * (event.station - origin))
                    if distance > 0 && distance <= lookaheadDistance { clusterCandidates.append(.init(signID: event.id, sourceID: event.source,
                        snapshotSHA256: event.sha, ruleID: rule.id, originWayID: current.way, direction: current.direction,
                        stationM: event.station, speedKmh: Int(value), distanceM: distance)) }
                }
                if blocked { reason = "unresolved_applicability"; break }
                candidates.append(contentsOf: clusterCandidates)
            }
            if blocked { break }
            travelled += span
            if travelled >= lookaheadDistance, abs(stop - exit) <= 0.01, canTraverse, path.count < maximumSegments, !common.isEmpty,
               candidates.contains(where: { $0.originWayID == current.way && $0.direction == current.direction && abs($0.stationM - exit) <= 0.01 }),
               let next = successor(db, resources, current), !visited.contains(next.id.map(String.init) ?? "") {
                let nextGroups = common.intersection(groups(db, resources, next.way))
                if !nextGroups.isEmpty {
                    // No events beyond the horizon are read. This certified entry records passage when
                    // the next accepted fix is already on the far side of an endpoint station.
                    path.append(.init(segmentID: next.id.map(String.init), wayID: next.way, direction: next.direction,
                        startM: next.start, endM: next.end, entryDistanceM: travelled, relationGroupIDs: nextGroups.sorted()))
                }
            }
            guard travelled < lookaheadDistance, span >= available - 0.001, canTraverse, !common.isEmpty,
                  let next = successor(db, resources, current) else { break }
            guard segmentIndex + 1 < maximumSegments else { reason = "work_cap"; break }
            current = next; origin = next.direction == 1 ? next.start : next.end; includeEntry = true
        }
        if DispatchTime.now().uptimeNanoseconds > deadline { candidates = []; reason = "budget_exceeded" }
        var seen = Set<String>()
        candidates = candidates.sorted { ($0.distanceM, $0.signID) < ($1.distanceM, $1.signID) }.filter { seen.insert($0.identity).inserted }
        return .init(wayID: way, direction: direction, chainageM: chainage, relationGroupIDs: relationGroupIDs,
            path: path, candidates: candidates, reason: candidates.isEmpty ? reason : "candidate", queryTimeMs: Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000, topologyAvailable: canTraverse,
            lookaheadDistanceM: lookaheadDistance)
    }
}

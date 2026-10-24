import Foundation
import CryptoKit

/// A separate, opt-in advisory data path. It never creates a speed offer or sign observation.
enum RoadworksAdvisory {
    enum Failure: Error { case invalidManifest, invalidSnapshot, unsupportedVersion, checksumMismatch }
    enum Freshness: String { case fresh, delayed, unknown, unavailable }
    struct Interval: Equatable {
        let start: Date
        let end: Date
        func contains(_ date: Date) -> Bool { date >= start && date < end }
    }
    struct Point: Equatable { let latitude: Double; let longitude: Double }
    struct Feature {
        let id: String
        let revision: String
        let kind: String
        let description: String
        let roadLabel: String
        let direction: String
        let operatorStatus: String
        let scheduleStatus: String
        let outer: Interval
        let intervals: [Interval]
        let points: [Point]
        var isLine: Bool { points.count >= 2 }
        func eligible(at: Date) -> Bool {
            ["roadworks", "closure"].contains(kind) && ["requested", "approved", "implemented"].contains(operatorStatus)
                && scheduleStatus == "resolved" && outer.contains(at) && intervals.contains { $0.contains(at) }
        }
    }
    struct Snapshot {
        let id: String
        let window: Interval
        let features: [Feature]
        let attributions: [[String: String]]
    }
    struct Manifest {
        let enabled: Bool
        let snapshotID: String?
        let snapshotBytes: Int?
        let snapshotPath: String?
        let serverTime: Date
        let sourcePublication: Date?
        let sourceModified: Date?
        let lastChecked: Date?
        let advertisedStatus: Freshness

        func freshness(receivedUptime: TimeInterval, nowUptime: TimeInterval) -> Freshness {
            guard enabled else { return .unavailable }
            let elapsed = nowUptime - receivedUptime
            guard elapsed.isFinite, elapsed >= 0 else { return .unknown }
            guard elapsed <= 86_400 else { return .unavailable }
            guard advertisedStatus != .unavailable, snapshotID != nil else { return .unavailable }
            guard advertisedStatus != .unknown, let publication = sourcePublication,
                  let modified = sourceModified, let checked = lastChecked else { return .unknown }
            let now = serverTime.addingTimeInterval(elapsed)
            let sourceAge = now.timeIntervalSince(min(publication, modified))
            let checkAge = now.timeIntervalSince(checked)
            guard sourceAge >= 0, checkAge >= 0 else { return .unknown }
            guard sourceAge <= 86_400 else { return .unavailable }
            return advertisedStatus == .delayed || sourceAge > 1800 || checkAge > 900 ? .delayed : .fresh
        }
        /// HTTP Date and Age bound a cached manifest; they never freshen publisher clocks.
        func validatedHTTPClock(date: Date, age: TimeInterval) throws -> Manifest {
            guard age.isFinite, age >= 0, age <= 86_400,
                  abs(serverTime.timeIntervalSince(date)) <= 300 else { throw Failure.invalidManifest }
            return Manifest(enabled: enabled, snapshotID: snapshotID, snapshotBytes: snapshotBytes,
                snapshotPath: snapshotPath, serverTime: date.addingTimeInterval(age), sourcePublication: sourcePublication,
                sourceModified: sourceModified, lastChecked: lastChecked, advertisedStatus: advertisedStatus)
        }
    }

    private static func date(_ raw: Any?) throws -> Date {
        guard let string = raw as? String,
              string.range(of: #"(Z|[+-][0-9]{2}:[0-9]{2})$"#, options: .regularExpression) != nil else { throw Failure.invalidSnapshot }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = parser.date(from: string) { return parsed }
        parser.formatOptions = [.withInternetDateTime]
        guard let parsed = parser.date(from: string) else { throw Failure.invalidSnapshot }
        return parsed
    }
    private static func interval(_ raw: Any?) throws -> Interval {
        guard let values = raw as? [String: Any] else { throw Failure.invalidSnapshot }
        let value = try Interval(start: date(values["start"]), end: date(values["end"]))
        guard value.end > value.start else { throw Failure.invalidSnapshot }
        return value
    }
    private static func hashID(_ raw: Any?) -> String? {
        guard let value = raw as? String, value.range(of: #"^[a-f0-9]{64}$"#, options: .regularExpression) != nil else { return nil }
        return value
    }
    static func parseManifest(_ bytes: Data) throws -> Manifest {
        guard bytes.count <= 262_144, let root = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { throw Failure.invalidManifest }
        guard root["schema_version"] as? Int == 1 else { throw Failure.unsupportedVersion }
        guard root["region"] as? String == "DE-BW", let enabled = root["feature_enabled"] as? Bool,
              let clocks = root["freshness"] as? [String: Any], let status = Freshness(rawValue: clocks["status"] as? String ?? ""),
              let coverage = root["coverage"] as? [String: Any], coverage["region"] as? String == "DE-BW",
              coverage["complete_road_coverage"] as? Bool == false, coverage["autobahn_included"] as? Bool == false,
              let attribution = root["attributions"] as? [[String: String]], !attribution.isEmpty else { throw Failure.invalidManifest }
        let id = hashID(root["snapshot_id"])
        let size = root["snapshot_bytes"] as? Int
        let path = root["snapshot_path"] as? String
        if let id {
            guard let size, (0...8_388_608).contains(size), path == "/youspeed/live/v1/regions/DE-BW/snapshots/" + id else { throw Failure.invalidManifest }
        } else if !(root["snapshot_id"] is NSNull && root["snapshot_bytes"] is NSNull && root["snapshot_path"] is NSNull) { throw Failure.invalidManifest }
        return try Manifest(enabled: enabled, snapshotID: id, snapshotBytes: size, snapshotPath: path,
            serverTime: date(clocks["server_time"]),
            sourcePublication: clocks["source_publication_at"] is NSNull ? nil : date(clocks["source_publication_at"]),
            sourceModified: clocks["source_modified_at"] is NSNull ? nil : date(clocks["source_modified_at"]),
            lastChecked: clocks["last_checked_at"] is NSNull ? nil : date(clocks["last_checked_at"]), advertisedStatus: status)
    }
    static func parseSnapshot(_ bytes: Data, expectedID: String) throws -> Snapshot {
        guard bytes.count <= 8_388_608 else { throw Failure.invalidSnapshot }
        guard SHA256.hash(data: bytes).map({ String(format: "%02x", $0) }).joined() == expectedID else { throw Failure.checksumMismatch }
        guard let root = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { throw Failure.invalidSnapshot }
        guard root["schema_version"] as? Int == 1 else { throw Failure.unsupportedVersion }
        guard root["type"] as? String == "FeatureCollection", let rows = root["features"] as? [[String: Any]], rows.count <= 10_000,
              let normalization = root["normalization_version"] as? String, !normalization.isEmpty,
              let credits = root["attributions"] as? [[String: String]], !credits.isEmpty else { throw Failure.invalidSnapshot }
        _ = try date(root["generated_at"])
        let window = try interval(root["evaluation_window"])
        var identities = Set<String>(), vertices = 0
        let features = try rows.map { row -> Feature in
            guard row["type"] as? String == "Feature", let id = row["id"] as? String,
                  id.hasPrefix("mobidata-bw:bemas:"), id.count <= 300, identities.insert(id).inserted,
                  let properties = row["properties"] as? [String: Any], let revision = hashID(properties["revision"]),
                  let kind = properties["kind"] as? String, let text = properties["description"] as? String, text.count <= 2048,
                  let road = properties["road_label"] as? String, road.count <= 512,
                  let direction = properties["direction"] as? String, let operatorStatus = properties["operator_status"] as? String,
                  let scheduleStatus = properties["schedule_status"] as? String,
                  let rawIntervals = properties["active_intervals"] as? [[String: Any]], rawIntervals.count <= 1024,
                  let geometry = row["geometry"] as? [String: Any] else { throw Failure.invalidSnapshot }
            let outer = try Interval(start: date(properties["outer_start"]), end: date(properties["outer_end"]))
            guard outer.end > outer.start else { throw Failure.invalidSnapshot }
            let intervals = try rawIntervals.map { try interval($0) }
            guard intervals.allSatisfy({ $0.start >= max(window.start, outer.start) && $0.end <= min(window.end, outer.end) }),
                  scheduleStatus == "resolved" || intervals.isEmpty else { throw Failure.invalidSnapshot }
            let coordinates: [[Double]]
            if geometry["type"] as? String == "Point", let pair = geometry["coordinates"] as? [Double] { coordinates = [pair] }
            else if geometry["type"] as? String == "LineString", let line = geometry["coordinates"] as? [[Double]], line.count >= 2 { coordinates = line }
            else { throw Failure.invalidSnapshot }
            vertices += coordinates.count
            guard vertices <= 200_000 else { throw Failure.invalidSnapshot }
            let points = try coordinates.map { pair -> Point in
                // Broad BW sanity envelope rejects the known reversed Point defect.
                // Repair is exclusively a source-backed server adapter operation.
                guard pair.count == 2, pair[0].isFinite, pair[1].isFinite,
                      (7...11).contains(pair[0]), (47...50).contains(pair[1]) else { throw Failure.invalidSnapshot }
                return Point(latitude: pair[1], longitude: pair[0])
            }
            return Feature(id: id, revision: revision, kind: kind, description: text, roadLabel: road,
                direction: points.count == 1 ? "unknown" : direction, operatorStatus: operatorStatus,
                scheduleStatus: scheduleStatus, outer: outer, intervals: intervals, points: points)
        }
        return Snapshot(id: expectedID, window: window, features: features, attributions: credits)
    }
    static func distance(from point: Point, to feature: Feature) -> Double {
        let sy = Double.pi / 180 * 6_371_008.8, sx = sy * cos(point.latitude * .pi / 180)
        let projected = feature.points.map { (($0.longitude - point.longitude) * sx, ($0.latitude - point.latitude) * sy) }
        if projected.count == 1 { return hypot(projected[0].0, projected[0].1) }
        return zip(projected, projected.dropFirst()).map { a, b in
            let dx = b.0 - a.0, dy = b.1 - a.1, length = dx * dx + dy * dy
            let fraction = length > 0 ? max(0, min(1, -(a.0 * dx + a.1 * dy) / length)) : 0
            return hypot(a.0 + fraction * dx, a.1 + fraction * dy)
        }.min() ?? .infinity
    }
}

/// Atomic cache promotion preserves the previous generation on malformed/unsupported replies.
final class RoadworksSnapshotCache {
    private(set) var snapshot: RoadworksAdvisory.Snapshot?
    private(set) var bytes: Data?
    private(set) var previousSnapshot: RoadworksAdvisory.Snapshot?
    private(set) var restoreError: String?
    private let directory: URL?
    init(directory: URL? = nil) {
        self.directory = directory
        guard let directory else { return }
        do {
            let pointer = directory.appendingPathComponent("current.json")
            guard FileManager.default.fileExists(atPath: pointer.path) else { return }
            let raw = try JSONSerialization.jsonObject(with: Data(contentsOf: pointer)) as? [String: String] ?? [:]
            func load(_ id: String?) throws -> (Data, RoadworksAdvisory.Snapshot)? {
                guard let id, id.range(of: #"^[a-f0-9]{64}$"#, options: .regularExpression) != nil else { return nil }
                let data = try Data(contentsOf: directory.appendingPathComponent("snapshot-" + id + ".json"))
                return (data, try RoadworksAdvisory.parseSnapshot(data, expectedID: id))
            }
            let previous = try? load(raw["previous"])
            previousSnapshot = previous?.1
            if let current = try? load(raw["current"]) { bytes = current.0; snapshot = current.1 }
            else if let previous { bytes = previous.0; snapshot = previous.1; previousSnapshot = nil; restoreError = "current_snapshot_invalid_using_previous" }
            else { restoreError = "no_valid_cached_snapshot" }
        } catch { restoreError = error.localizedDescription }
    }
    func install(_ data: Data, manifest: RoadworksAdvisory.Manifest) throws {
        guard let id = manifest.snapshotID, data.count == manifest.snapshotBytes else { throw RoadworksAdvisory.Failure.invalidSnapshot }
        let parsed = try RoadworksAdvisory.parseSnapshot(data, expectedID: id)
        if let directory {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try data.write(to: directory.appendingPathComponent("snapshot-" + id + ".json"), options: .atomic)
            var pointer = ["current": id]
            if let previous = snapshot?.id, previous != id { pointer["previous"] = previous }
            else if let previous = previousSnapshot?.id { pointer["previous"] = previous }
            try JSONSerialization.data(withJSONObject: pointer, options: .sortedKeys)
                .write(to: directory.appendingPathComponent("current.json"), options: .atomic)
        }
        if snapshot?.id != id { previousSnapshot = snapshot }
        bytes = data; snapshot = parsed
    }
}

struct RoadworksRelevance {
    struct Fix { let point: RoadworksAdvisory.Point; let at: Date; let accuracyM: Double }
    struct Card { let feature: RoadworksAdvisory.Feature; let distanceM: Double; let freshness: RoadworksAdvisory.Freshness }
    private var snapshotID: String?
    private var selectedID: String?
    private var pendingID: String?
    private var previousFix: Date?
    mutating func reset() { self = Self() }
    mutating func update(snapshot: RoadworksAdvisory.Snapshot?, freshness: RoadworksAdvisory.Freshness,
                         fix: Fix?, now: Date, enabled: Bool, driving: Bool, foreground: Bool) -> Card? {
        guard enabled, driving, foreground, freshness == .fresh || freshness == .delayed, let snapshot,
              snapshot.window.contains(now), let fix, fix.point.latitude.isFinite, fix.point.longitude.isFinite,
              (-90...90).contains(fix.point.latitude), (-180...180).contains(fix.point.longitude),
              fix.accuracyM.isFinite, (0...50).contains(fix.accuracyM), now >= fix.at, now.timeIntervalSince(fix.at) <= 3 else { reset(); return nil }
        guard previousFix.map({ fix.at >= $0 }) ?? true else { reset(); return nil }
        if snapshotID != snapshot.id { reset(); snapshotID = snapshot.id }
        let eligible = snapshot.features.filter { $0.eligible(at: now) }.map { ($0, RoadworksAdvisory.distance(from: fix.point, to: $0)) }
        if let selectedID, let retained = eligible.first(where: { $0.0.id == selectedID && $0.1 <= 750 }) {
            previousFix = fix.at
            return Card(feature: retained.0, distanceM: retained.1, freshness: freshness)
        }
        selectedID = nil
        let candidate = eligible.filter { $0.1 <= 500 }.sorted {
            if ($0.0.kind == "closure") != ($1.0.kind == "closure") { return $0.0.kind == "closure" }
            return ($0.1, $0.0.id) < ($1.1, $1.0.id)
        }.first
        guard let candidate else { pendingID = nil; previousFix = fix.at; return nil }
        let confirmed = pendingID == candidate.0.id && previousFix.map { fix.at > $0 && fix.at.timeIntervalSince($0) <= 3 } == true
        pendingID = candidate.0.id; previousFix = fix.at
        guard confirmed else { return nil }
        selectedID = candidate.0.id
        return Card(feature: candidate.0, distanceM: candidate.1, freshness: freshness)
    }
}

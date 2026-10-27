import Foundation
import SQLite3
import CryptoKit
import CoreFoundation

/// A data correction to an immutable bundle, separate from voice/camera offers.
/// Rules use the existing bundle conditional grammar, including unsupported AST
/// leaves and all original tags. Reference-policy priority/expiry stays unchanged.
struct MapDataAmendment: Codable, Sendable {
    var schemaVersion = 1
    let id: String
    var revision: Int64 = 0
    var operation = "upsert"
    let sourceNamespace: String
    let entity: String
    let sourceID: String
    var direction: Int = 0
    var basisBundle: String
    let originalBundle: String
    var sourceRevision: String
    var rulesJSON: String
    var rawSourceTags: [String: String]
    var validFromUTC: Double?
    var validUntilUTC: Double?
    var reviewState = "confirmed"
    var author: String
    var evidenceID: String
    var nodeJSON: String?
    var boundWayID: String?
    var bindingVerified = false
    var passageEvidenceID: String?
    var stationChainageM: Double?
    var scopeStartM: Double?
    var scopeEndM: Double?
    var displayRadiusM: Double?

    enum CodingKeys: String, CodingKey {
        case id, revision, operation, entity, direction, author
        case schemaVersion = "schema_version"
        case sourceNamespace = "source_namespace"
        case sourceID = "source_id"
        case basisBundle = "basis_bundle"
        case originalBundle = "original_bundle"
        case sourceRevision = "source_revision"
        case rulesJSON = "rules_json"
        case rawSourceTags = "raw_source_tags"
        case validFromUTC = "valid_from_utc"
        case validUntilUTC = "valid_until_utc"
        case reviewState = "review_state"
        case evidenceID = "evidence_id"
        case nodeJSON = "node_json"
        case boundWayID = "bound_way_id"
        case bindingVerified = "binding_verified"
        case passageEvidenceID = "passage_evidence_id"
        case stationChainageM = "station_chainage_m"
        case scopeStartM = "scope_start_m"
        case scopeEndM = "scope_end_m"
        case displayRadiusM = "display_radius_m"
    }
}

/// Correction snapshots can identify an OSM node or a newly surveyed local
/// node. Local identities never impersonate an OSM identifier.
private struct MapDataAmendmentNode: Decodable {
    let osmNodeID: Int64?
    let sourceID: String
    let latitude: Double
    let longitude: Double
    let tags: [String: String]
    let memberships: [GenericSpeedSignNode.Membership]
    let bindingStatus: String
    enum CodingKeys: String, CodingKey {
        case latitude, longitude, tags, memberships
        case osmNodeID = "osm_node_id", sourceID = "source_id", bindingStatus = "binding_status"
    }
    func matches(_ record: MapDataAmendment) -> Bool {
        if record.sourceNamespace == "local" {
            return osmNodeID == nil && sourceID == record.sourceID && memberships.isEmpty && bindingStatus == "local_reviewed"
        }
        return record.sourceNamespace == "osm" && osmNodeID.map(String.init) == record.sourceID
    }
}

/// Adapts explicitly reviewed node records to the existing inventory passage
/// predicate. A temporary fix gap ends interpolation, not an admitted scope.
struct MapDataNodePassageRuntime {
    private struct Scope: Equatable { let bundle: String; let way: String; let direction: Int }
    private struct Association: Equatable {
        let id: String, sourceID: String, basis: String, sourceRevision: String, reviewState: String, operation: String
        let direction: Int
        let verified: Bool
        let boundWay: String?, passageEvidence: String?, nodeJSON: String?
        let station: Double?, start: Double?, end: Double?, radius: Double?
        init(_ record: MapDataAmendment) {
            id = record.id; sourceID = record.sourceID; basis = record.basisBundle; sourceRevision = record.sourceRevision
            reviewState = record.reviewState; operation = record.operation; verified = record.bindingVerified
            direction = record.direction; boundWay = record.boundWayID; passageEvidence = record.passageEvidenceID; nodeJSON = record.nodeJSON
            station = record.stationChainageM; start = record.scopeStartM; end = record.scopeEndM; radius = record.displayRadiusM
        }
    }
    private var scope: Scope?
    private var tracker = InventoryBoundaryPassageTracker()
    private var admitted = Set<String>()
    private var activatedScopes = Set<String>()
    private var associationSignature: [Association] = []
    private(set) var observations: [InventoryTrafficSign] = []
    private(set) var observationLookup: InventorySignLookup?
    mutating func reset() { scope = nil; tracker.reset(); admitted = []; activatedScopes = []; associationSignature = []; observations = []; observationLookup = nil }

    mutating func consume(records: [MapDataAmendment], bundle: String, wayID: String?, points: [(Double, Double)],
                          wayLengthM: Double?, lat: Double, lon: Double, heading: Double?, headingAccuracy: Double?,
                          accuracy: Double, matchStable: Bool, at: Date?, now: Date = Date()) -> Set<String> {
        if scope?.bundle != nil && scope?.bundle != bundle { reset() }
        if records.isEmpty {
            if scope?.way == wayID || matchStable { reset() }
            return []
        }
        let currentAssociations = records.map(Association.init).sorted { $0.id < $1.id }
        // Review changes revoke physical proof even when the current fix is
        // unusable. Numeric rule edits leave the directed association intact.
        if associationSignature != currentAssociations {
            tracker.reset(); admitted = []; activatedScopes = []; associationSignature = currentAssociations
        }
        let fresh = at.map { $0 <= now.addingTimeInterval(1) && now.timeIntervalSince($0) <= 3 } == true
        let usable = accuracy.isFinite && (0...25).contains(accuracy)
        let projection = usable ? InventorySignBundle.projection(lat: lat, lon: lon, points: points) : nil
        guard fresh, matchStable, let wayID, let projection,
              let direction = InventorySignBundle.travelDirection(projection: projection, heading: heading, headingAccuracy: headingAccuracy) else {
            _ = tracker.consume(nil, bundle: bundle, at: at)
            observations = []
            observationLookup = nil
            return scope?.way == wayID ? activatedScopes : []
        }
        let current = Scope(bundle: bundle, way: wayID, direction: direction)
        if scope != current { reset(); scope = current; associationSignature = currentAssociations }
        let length = wayLengthM ?? zip(points,points.dropFirst()).reduce(0) {
            $0 + InventorySignBundle.distance($1.0.0,$1.0.1,$1.1.0,$1.1.1) * (6_371_000.0/6_371_008.8)
        }
        var rules: [InventoryTrafficRule] = []
        var signs: [InventoryTrafficSign] = []
        for record in records {
            guard record.operation == "upsert", record.reviewState == "confirmed", record.basisBundle == bundle,
                  record.entity == "node", record.boundWayID == wayID, record.direction == direction,
                  record.bindingVerified, record.passageEvidenceID?.isEmpty == false,
                  let raw = record.nodeJSON?.data(using: .utf8),
                  let node = try? JSONDecoder().decode(MapDataAmendmentNode.self, from: raw), node.matches(record),
                  node.latitude.isFinite, node.longitude.isFinite,
                  (-85..<85).contains(node.latitude), (-180...180).contains(node.longitude) else { continue }
            let stations = Set(node.memberships.filter { String($0.wayID) == wayID }.map(\.chainageM))
            guard let station = record.stationChainageM ?? (stations.count == 1 ? stations.first : nil),
                  station.isFinite, station >= 0, length.isFinite, length > 0, station <= length else { continue }
            let start = record.scopeStartM ?? (direction == 1 ? station : 0)
            let end = record.scopeEndM ?? (direction == 1 ? length : station)
            if record.sourceNamespace == "local",
               record.stationChainageM == nil || record.scopeStartM == nil || record.scopeEndM == nil { continue }
            guard start.isFinite, end.isFinite, start >= 0, start < end, end <= length else { continue }
            let radius = record.displayRadiusM ?? 30
            guard radius == 10 || radius == 30 else { continue }
            let distance = InventorySignBundle.distance(lat,lon,node.latitude,node.longitude)
            let code = node.tags["traffic_sign"] ?? "maxspeed"
            rules.append(InventoryTrafficRule(ruleID: record.id, signID: record.sourceID, code: code,
                direction: direction, stationM: station, startM: start, endM: end, speedKmh: nil, insideCity: nil,
                distanceM: distance, radiusM: radius, sourceLatitude: node.latitude, sourceLongitude: node.longitude,
                sourceID: "local-map-amendment", snapshotSHA256: record.sourceRevision))
            if distance <= radius {
                signs.append(InventoryTrafficSign(signID: record.sourceID, sourceID: "local-map-amendment", recordKey: record.id,
                    snapshotSHA256: record.sourceRevision, code: code, kind: "speed_limit",
                    numericValue: MapDataAmendmentStore.observationBaseKmh(rulesJSON: record.rulesJSON, rawMaxspeed: node.tags["maxspeed"]),
                    unit: "km/h", parameterStatus: "parsed_source_value",
                    latitude: node.latitude, longitude: node.longitude, radiusM: radius, pictogramCode: nil, pictogramPath: nil,
                    modelClasses: [], distanceM: distance, associatedWayID: wayID, associatedDirection: direction,
                    associationStatus: "accepted", associatedHeadingDeg: projection.heading))
            }
        }
        let lookup = InventorySignLookup(signs: signs, activeRule: nil, wayID: wayID, direction: direction,
            chainageM: projection.chainage, boundaries: rules)
        let crossed = tracker.consume(lookup, bundle: bundle, at: at, latitude: lat, longitude: lon)
        admitted.formUnion(crossed.map(\.signID))
        let stillApplicable = Set(rules.filter {
            direction == 1 ? projection.chainage >= $0.startM && projection.chainage < $0.endM
                : projection.chainage > $0.startM && projection.chainage <= $0.endM
        }.map(\.signID))
        // Proof is retained between its station and an explicitly later scope
        // start, but a known end of scope removes authority immediately.
        let notEnded = Set(rules.filter { direction == 1 ? projection.chainage < $0.endM : projection.chainage > $0.startM }.map(\.signID))
        admitted.formIntersection(notEnded)
        activatedScopes.formUnion(admitted.intersection(stillApplicable))
        activatedScopes.formIntersection(notEnded)
        observations = signs
        observationLookup = InventorySignLookup(signs: signs, activeRule: nil, wayID: wayID, direction: direction, chainageM: projection.chainage)
        return activatedScopes
    }
}

final class MapDataAmendmentStore: @unchecked Sendable {
    enum StoreError: Error { case invalid(String), conflict(actualRevision: Int64), missing, storage(String) }
    private let url: URL
    private let lock = NSLock()
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(directory: URL) {
        url = directory.appendingPathComponent("map_data_amendments.sqlite")
        if FileManager.default.fileExists(atPath: url.path) { try? database(write: true) { _ in () } }
    }

    private static let defaultStore: MapDataAmendmentStore? = {
        guard let base = try? FileManager.default.url(for: .applicationSupportDirectory,
            in: .userDomainMask, appropriateFor: nil, create: false) else { return nil }
        return MapDataAmendmentStore(directory: base.appendingPathComponent("SpeedConsumer", isDirectory: true))
    }()
    static func applicationStore() -> MapDataAmendmentStore? { defaultStore }

    static func isCanonicalBaseIdentity(_ value: String) -> Bool {
        value.range(of: "^ysp-base-v1:[0-9a-f]{64}:[0-9a-f]{64}:([0-9a-f]{64}|absent)$", options: .regularExpression) != nil
    }

    static func nodeSourceRevision(json: String) -> String { "node-json-sha256:" + sourceHash(json) }
    static func waySourceRevision(rulesJSON: String) -> String { "way-rule-set-sha256:" + sourceHash(rulesJSON) }
    private static func sourceHash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func matchesNodeSourceRevision(_ revision: String, json: String?) -> Bool {
        guard revision.hasPrefix("node-json-sha256:") else { return true }
        return json.map { nodeSourceRevision(json: $0) == revision } ?? false
    }

    /// Physical circle for inventory/camera matching, independent of the
    /// conditional effective limit. The observation pipeline uses km/h here;
    /// a raw mph/symbolic source must not receive a normalized-km/h circle.
    static func observationBaseKmh(rulesJSON: String, rawMaxspeed: String?) -> Double? {
        var rawValue: Double?
        if let raw = rawMaxspeed?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty {
            guard let number = Double(raw), number.isFinite, number > 0, number <= 400 else { return nil }
            rawValue = number
        }
        guard let data = rulesJSON.data(using: .utf8), data.count <= 262_144,
              let rules = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = rules["version"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(), version.doubleValue == 1,
              rules["grammar"] as? String == "youspeed-osm-speed-1",
              let tags = rules["tags"] as? [[String: Any]], !tags.isEmpty, tags.count <= 128 else { return nil }
        func boolean(_ value: Any?) -> Bool? {
            guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
            return number.boolValue
        }
        if tags.contains(where: { $0["role"] as? String == "variable" && ($0["raw"] as? String ?? "").lowercased() != "no" }) { return nil }
        let universal = tags.filter { $0["role"] as? String == "speed" && $0["vehicle"] as? String == "all" && boolean($0["conditional"]) != true }
        if universal.contains(where: { ($0["key"] as? String ?? "").hasPrefix("maxspeed:") }) { return nil }
        let bases = universal.filter { $0["key"] as? String == "maxspeed" }
        guard !bases.isEmpty else { return rawValue }
        guard bases.count == 1 else { return nil }
        let base = bases[0]
        guard boolean(base["conditional"]) == false,
              let direction = base["direction"] as? NSNumber, CFGetTypeID(direction) != CFBooleanGetTypeID(), direction.doubleValue == 0,
              base["lane"] == nil || boolean(base["lane"]) == false,
              base["status"] as? String == "supported",
              let clauses = base["clauses"] as? [[String: Any]], clauses.count == 1,
              (clauses[0]["condition"] as? [String: Any])?["kind"] as? String == "true",
              let limit = clauses[0]["limit"] as? [String: Any], limit["kind"] as? String == "numeric",
              let number = limit["kmh"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue > 0, number.doubleValue <= 400 else { return nil }
        return number.doubleValue
    }

    /// Persists a new, initially unbound survey record. Applying it requires a
    /// separate reviewed directed association and the ordinary drive passage.
    @discardableResult
    func createLocalNode(latitude: Double, longitude: Double, tags: [String: String], rulesJSON: String,
                         bundle: String, author: String, evidenceID: String) throws -> MapDataAmendment {
        let sourceID = "local-node:" + UUID().uuidString.lowercased()
        let object: [String: Any] = ["source_id": sourceID, "latitude": latitude, "longitude": longitude,
            "tags": tags, "memberships": [], "binding_status": "local_reviewed"]
        let json = String(data: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]), encoding: .utf8)!
        let record = MapDataAmendment(id: sourceID, sourceNamespace: "local", entity: "node", sourceID: sourceID,
            basisBundle: bundle, originalBundle: bundle, sourceRevision: "local-survey:" + sourceID,
            rulesJSON: rulesJSON, rawSourceTags: tags, author: author, evidenceID: evidenceID, nodeJSON: json)
        return try put(record, expectedRevision: 0)
    }

    private func database<T>(write: Bool, _ body: (OpaquePointer) throws -> T) throws -> T {
        lock.lock(); defer { lock.unlock() }
        if write { try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true) }
        var connection: OpaquePointer?
        let flags = write ? SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX : SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(url.path, &connection, flags, nil) == SQLITE_OK, let connection else {
            if let connection { sqlite3_close(connection) }
            throw StoreError.storage("Cannot open map amendment store")
        }
        defer { sqlite3_close(connection) }
        sqlite3_busy_timeout(connection, 2000)
        if write {
            guard sqlite3_exec(connection, """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS revisions(
                  id TEXT NOT NULL,revision INTEGER NOT NULL,source_namespace TEXT NOT NULL,
                  entity TEXT NOT NULL,source_id TEXT NOT NULL,bound_way_id TEXT,body_json TEXT NOT NULL,
                  PRIMARY KEY(id,revision));
                CREATE INDEX IF NOT EXISTS revisions_target ON revisions(source_namespace,entity,source_id);
                """, nil, nil, nil) == SQLITE_OK else { throw StoreError.storage("Cannot initialize map amendment store") }
            // This store is independent of the base pack. Older local draft
            // stores gain a bound-way index without rewriting revision JSON.
            var columns: OpaquePointer?
            var hasBoundWay = false
            if sqlite3_prepare_v2(connection, "PRAGMA table_info(revisions)", -1, &columns, nil) == SQLITE_OK {
                while sqlite3_step(columns) == SQLITE_ROW {
                    if let name = sqlite3_column_text(columns, 1), String(cString: name) == "bound_way_id" { hasBoundWay = true }
                }
            }
            sqlite3_finalize(columns)
            if !hasBoundWay {
                guard sqlite3_exec(connection, "ALTER TABLE revisions ADD COLUMN bound_way_id TEXT; UPDATE revisions SET bound_way_id=json_extract(body_json,'$.bound_way_id')", nil, nil, nil) == SQLITE_OK else {
                    throw StoreError.storage("Cannot migrate map amendment target index")
                }
            }
            guard sqlite3_exec(connection, "CREATE INDEX IF NOT EXISTS revisions_bound_way ON revisions(bound_way_id)", nil, nil, nil) == SQLITE_OK else {
                throw StoreError.storage("Cannot index node amendment targets")
            }
        }
        return try body(connection)
    }

    private func decode(_ text: UnsafePointer<UInt8>?) throws -> MapDataAmendment {
        guard let text, let data = String(cString: text).data(using: .utf8), data.count <= 512 * 1024 else {
            throw StoreError.invalid("Oversized or missing amendment revision")
        }
        let record = try JSONDecoder().decode(MapDataAmendment.self, from: data)
        try validate(record)
        return record
    }

    private func latest(_ id: String, database: OpaquePointer) throws -> MapDataAmendment? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, "SELECT revision,body_json FROM revisions WHERE id=?1 ORDER BY revision DESC LIMIT 1", -1, &statement, nil) == SQLITE_OK, let statement else {
            throw StoreError.storage("Cannot inspect amendment revision")
        }
        defer { sqlite3_finalize(statement) }
        _ = id.withCString { sqlite3_bind_text(statement, 1, $0, -1, transient) }
        let code = sqlite3_step(statement)
        if code == SQLITE_DONE { return nil }
        guard code == SQLITE_ROW else { throw StoreError.storage("Cannot read amendment revision") }
        let record = try decode(sqlite3_column_text(statement, 1))
        guard record.id == id, record.revision == sqlite3_column_int64(statement, 0) else {
            throw StoreError.invalid("Amendment body does not match its revision identity")
        }
        return record
    }

    func latest(_ id: String) throws -> MapDataAmendment? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try database(write: false) { try latest(id, database: $0) }
    }

    @discardableResult
    func put(_ incoming: MapDataAmendment, expectedRevision: Int64) throws -> MapDataAmendment {
        try validate(incoming)
        return try database(write: true) { db in
            guard sqlite3_exec(db, "BEGIN IMMEDIATE", nil, nil, nil) == SQLITE_OK else { throw StoreError.storage("Cannot begin amendment transaction") }
            var committed = false
            defer { if !committed { sqlite3_exec(db, "ROLLBACK", nil, nil, nil) } }
            let old = try latest(incoming.id, database: db)
            let current = old?.revision ?? 0
            guard current == expectedRevision else { throw StoreError.conflict(actualRevision: current) }
            guard current < Int64.max else { throw StoreError.invalid("Revision capacity reached") }
            if let old {
                guard old.originalBundle == incoming.originalBundle, old.sourceNamespace == incoming.sourceNamespace,
                      old.entity == incoming.entity, old.sourceID == incoming.sourceID else {
                    throw StoreError.invalid("Retargeting an amendment requires a separate reviewed source record")
                }
            }
            var saved = incoming; saved.revision = current + 1
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
            let data = try encoder.encode(saved)
            guard data.count <= 512 * 1024, let json = String(data: data, encoding: .utf8) else { throw StoreError.invalid("Amendment exceeds size limit") }
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(db, "INSERT INTO revisions(id,revision,source_namespace,entity,source_id,bound_way_id,body_json) VALUES(?1,?2,?3,?4,?5,?6,?7)", -1, &statement, nil) == SQLITE_OK, let statement else {
                throw StoreError.storage("Cannot prepare amendment revision")
            }
            defer { sqlite3_finalize(statement) }
            for (index, text) in [(1, saved.id), (3, saved.sourceNamespace), (4, saved.entity), (5, saved.sourceID), (7, json)] {
                _ = text.withCString { sqlite3_bind_text(statement, Int32(index), $0, -1, transient) }
            }
            sqlite3_bind_int64(statement, 2, saved.revision)
            if let bound = saved.boundWayID { _ = bound.withCString { sqlite3_bind_text(statement, 6, $0, -1, transient) } }
            else { sqlite3_bind_null(statement, 6) }
            guard sqlite3_step(statement) == SQLITE_DONE, sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK else {
                throw StoreError.storage("Cannot commit amendment revision")
            }
            committed = true
            return saved
        }
    }

    @discardableResult
    func tombstone(_ id: String, expectedRevision: Int64) throws -> MapDataAmendment {
        guard var record = try latest(id) else { throw StoreError.missing }
        record.operation = "tombstone"
        return try put(record, expectedRevision: expectedRevision)
    }

    /// Edits one typed limit without discarding the tag's condition, raw source
    /// text, direction, vehicle specificity or neighboring clauses.
    @discardableResult
    func amendNumericLimit(_ id: String, expectedRevision: Int64, tagKey: String,
                           clauseIndex: Int, kmh: Int) throws -> MapDataAmendment {
        guard var record = try latest(id), record.operation == "upsert", (1...400).contains(kmh), clauseIndex >= 0,
              let data = record.rulesJSON.data(using: .utf8),
              var rules = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              var tags = rules["tags"] as? [[String: Any]],
              let index = tags.firstIndex(where: { $0["key"] as? String == tagKey }),
              var clauses = tags[index]["clauses"] as? [[String: Any]], clauses.indices.contains(clauseIndex) else {
            throw StoreError.invalid("Missing typed speed clause")
        }
        clauses[clauseIndex]["limit"] = ["kind": "numeric", "kmh": kmh]
        tags[index]["clauses"] = clauses; rules["tags"] = tags
        record.rulesJSON = String(data: try JSONSerialization.data(withJSONObject: rules, options: [.sortedKeys]), encoding: .utf8)!
        return try put(record, expectedRevision: expectedRevision)
    }

    func history(_ id: String) throws -> [MapDataAmendment] {
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        return try database(write: false) { db in
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(db, "SELECT revision,body_json FROM revisions WHERE id=?1 ORDER BY revision", -1, &statement, nil) == SQLITE_OK, let statement else {
                throw StoreError.storage("Cannot read amendment history")
            }
            defer { sqlite3_finalize(statement) }
            _ = id.withCString { sqlite3_bind_text(statement, 1, $0, -1, transient) }
            var rows: [MapDataAmendment] = []
            while true {
                let code = sqlite3_step(statement); if code == SQLITE_DONE { return rows }
                guard code == SQLITE_ROW else { throw StoreError.storage("Cannot read amendment history") }
                let record = try decode(sqlite3_column_text(statement, 1))
                guard record.id == id, record.revision == sqlite3_column_int64(statement, 0) else {
                    throw StoreError.invalid("Amendment history identity mismatch")
                }
                rows.append(record)
            }
        }
    }

    private func validate(_ record: MapDataAmendment) throws {
        guard record.schemaVersion == 1, !record.id.isEmpty, record.id.utf8.count <= 1024, record.revision >= 0,
              ["upsert", "tombstone"].contains(record.operation), ["way", "node", "inventory_sign"].contains(record.entity),
              !record.sourceNamespace.isEmpty, !record.basisBundle.isEmpty, !record.originalBundle.isEmpty,
              !record.sourceRevision.isEmpty, !record.author.isEmpty,
              [-1, 0, 1, 2].contains(record.direction),
              ["confirmed", "needs_review", "rebase_required"].contains(record.reviewState),
              record.rulesJSON.utf8.count <= 262_144, record.rawSourceTags.count <= 128,
              record.rawSourceTags.reduce(0, { $0 + $1.key.utf8.count + $1.value.utf8.count }) <= 131_072,
              record.nodeJSON?.utf8.count ?? 0 <= 262_144,
              let rulesData = record.rulesJSON.data(using: .utf8),
              let rules = try JSONSerialization.jsonObject(with: rulesData) as? [String: Any],
              rules["version"] as? Int == 1, rules["grammar"] as? String == "youspeed-osm-speed-1",
              let tags = rules["tags"] as? [[String: Any]], !tags.isEmpty, tags.count <= 128 else {
            throw StoreError.invalid("Invalid map amendment record or conditional grammar")
        }
        if record.sourceNamespace == "local" {
            let prefix = "local-node:"
            guard record.entity == "node", record.sourceID.hasPrefix(prefix),
                  let uuid = UUID(uuidString: String(record.sourceID.dropFirst(prefix.count))),
                  prefix + uuid.uuidString.lowercased() == record.sourceID,
                  let data = record.nodeJSON?.data(using: .utf8),
                  let node = try? JSONDecoder().decode(MapDataAmendmentNode.self, from: data), node.matches(record),
                  node.latitude.isFinite, node.longitude.isFinite, (-85..<85).contains(node.latitude),
                  (-180...180).contains(node.longitude), node.tags == record.rawSourceTags else {
                throw StoreError.invalid("Invalid local node identity or source snapshot")
            }
            if record.bindingVerified {
                guard record.stationChainageM != nil, record.scopeStartM != nil, record.scopeEndM != nil else {
                    throw StoreError.invalid("Reviewed local node needs an explicit station and scope")
                }
            }
        } else {
            guard let sourceID = Int64(record.sourceID), sourceID > 0 else { throw StoreError.invalid("Invalid source identifier") }
        }
        for (prefix, entity) in [("node-json-sha256:", "node"), ("way-rule-set-sha256:", "way")] where record.sourceRevision.hasPrefix(prefix) {
            guard record.entity == entity,
                  String(record.sourceRevision.dropFirst(prefix.count)).range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
                throw StoreError.invalid("Invalid typed source revision")
            }
        }
        if record.entity == "node", !Self.matchesNodeSourceRevision(record.sourceRevision, json: record.nodeJSON) {
            throw StoreError.invalid("Node source snapshot differs from its typed revision")
        }
        for instant in [record.validFromUTC, record.validUntilUTC].compactMap({ $0 }) {
            guard instant.isFinite, instant >= 0 else { throw StoreError.invalid("Invalid amendment validity") }
        }
        if let start = record.validFromUTC, let end = record.validUntilUTC, start >= end { throw StoreError.invalid("Empty amendment validity") }
        for distance in [record.stationChainageM, record.scopeStartM, record.scopeEndM].compactMap({ $0 }) {
            guard distance.isFinite, distance >= 0 else { throw StoreError.invalid("Invalid amendment chainage") }
        }
        if let start = record.scopeStartM, let end = record.scopeEndM, start >= end { throw StoreError.invalid("Empty node applicability interval") }
        if let radius = record.displayRadiusM, radius != 10 && radius != 30 { throw StoreError.invalid("Unsupported sign display radius") }
        if record.entity != "way", record.bindingVerified {
            guard let way = record.boundWayID.flatMap(Int64.init), way > 0,
                  [-1, 1].contains(record.direction), record.passageEvidenceID?.isEmpty == false else {
                throw StoreError.invalid("Node amendment lacks verified directed passage evidence")
            }
        }
    }

    func nodePassageCandidates(wayID: String, bundle: String, at: Date) throws -> [MapDataAmendment] {
        guard Self.isCanonicalBaseIdentity(bundle) else { return [] }
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        return try database(write: false) { db in
            var statement: OpaquePointer?
            let sql = """
              SELECT r.body_json,r.id,r.revision FROM revisions r
              WHERE r.entity='node' AND r.bound_way_id=?1
                AND r.revision=(SELECT MAX(n.revision) FROM revisions n WHERE n.id=r.id)
              ORDER BY r.id
              """
            guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let statement else { throw StoreError.storage("Cannot read bound node amendments") }
            defer { sqlite3_finalize(statement) }
            _ = wayID.withCString { sqlite3_bind_text(statement, 1, $0, -1, transient) }
            var result: [MapDataAmendment] = []
            while true {
                let code = sqlite3_step(statement); if code == SQLITE_DONE { return result }
                guard code == SQLITE_ROW else { throw StoreError.storage("Cannot read bound node amendments") }
                let record = try decode(sqlite3_column_text(statement, 0))
                guard record.id == sqlite3_column_text(statement, 1).map({ String(cString: $0) }),
                      record.revision == sqlite3_column_int64(statement, 2), record.entity == "node", record.boundWayID == wayID else {
                    throw StoreError.invalid("Node amendment indexed identity mismatch")
                }
                let instant = at.timeIntervalSince1970
                guard record.operation == "upsert", record.reviewState == "confirmed", record.basisBundle == bundle,
                      record.bindingVerified, record.passageEvidenceID?.isEmpty == false,
                      record.validFromUTC.map({ instant >= $0 }) ?? true,
                      record.validUntilUTC.map({ instant < $0 }) ?? true else { continue }
                result.append(record)
            }
        }
    }

    /// A data-layer offer; callers retain the existing inventory/camera/voice
    /// admission and reference policy. Pending/changed source bindings cannot
    /// be promoted by nearest-road matching.
    func resolve(wayID: String, bundle: String, direction: Int?, context: ConditionalSpeedRules.Context,
                 baseKmh: Int?, baseUnlimited: Bool, passedNodeIDs: Set<String> = [],
                 baselineResult: ConditionalSpeedRules.Result? = nil,
                 sourceWayRulesJSON: String? = nil) throws -> ConditionalSpeedRules.Result? {
        guard Self.isCanonicalBaseIdentity(bundle) else { return nil }
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try database(write: false) { db in
            var statement: OpaquePointer?
            let sql = """
              SELECT r.body_json,r.id,r.revision,r.source_namespace,r.entity,r.source_id FROM revisions r
              WHERE r.revision=(SELECT MAX(n.revision) FROM revisions n WHERE n.id=r.id)
                AND (r.entity='way' AND r.source_id=?1 OR r.entity IN ('node','inventory_sign') AND r.bound_way_id=?1)
              ORDER BY r.id
              """
            guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let statement else { throw StoreError.storage("Cannot query amendments") }
            defer { sqlite3_finalize(statement) }
            _ = wayID.withCString { sqlite3_bind_text(statement, 1, $0, -1, transient) }
            var selected: ConditionalSpeedRules.Result?
            while true {
                let code = sqlite3_step(statement); if code == SQLITE_DONE { return selected }
                guard code == SQLITE_ROW else { throw StoreError.storage("Cannot query amendments") }
                let record = try decode(sqlite3_column_text(statement, 0))
                func indexedText(_ column: Int32) -> String? {
                    sqlite3_column_text(statement, column).map { String(cString: $0) }
                }
                guard record.id == indexedText(1), record.revision == sqlite3_column_int64(statement, 2),
                      record.sourceNamespace == indexedText(3), record.entity == indexedText(4), record.sourceID == indexedText(5),
                      record.entity != "way" || record.sourceID == wayID else {
                    throw StoreError.invalid("Amendment body does not match its indexed typed target")
                }
                guard record.operation == "upsert", record.sourceNamespace == "osm" || record.sourceNamespace == "local" && record.entity == "node" else { continue }
                if record.entity != "way" {
                    guard record.boundWayID == wayID else { continue }
                    // A saved historical passage is provenance, not proof that
                    // this drive has passed the node. The caller supplies the
                    // current drive's admitted passage IDs explicitly.
                    guard record.bindingVerified, record.passageEvidenceID?.isEmpty == false,
                          passedNodeIDs.contains(record.sourceID) else { continue }
                }
                guard record.reviewState == "confirmed", record.basisBundle == bundle else { continue }
                if record.entity == "way", record.sourceRevision.hasPrefix("way-rule-set-sha256:") {
                    guard sourceWayRulesJSON.map({ Self.waySourceRevision(rulesJSON: $0) == record.sourceRevision }) == true else { continue }
                }
                if record.entity == "node", !Self.matchesNodeSourceRevision(record.sourceRevision, json: record.nodeJSON) { continue }
                if record.direction != 0 {
                    guard let direction, record.direction != 2 else {
                        return ConditionalSpeedRules.Result(kmh: nil, unlimited: false, unresolved: true, reason: "map_amendment_direction_unresolved")
                    }
                    guard record.direction == direction else { continue }
                }
                if (record.validFromUTC != nil || record.validUntilUTC != nil), !context.clockTrusted {
                    return ConditionalSpeedRules.Result(kmh: nil, unlimited: false, unresolved: true, reason: "map_amendment_validity_unresolved")
                }
                let now = context.at.timeIntervalSince1970
                if let start = record.validFromUTC, now < start { continue }
                if let end = record.validUntilUTC, now >= end { continue }
                guard let data = record.rulesJSON.data(using: .utf8), let rules = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw StoreError.invalid("Invalid stored amendment rules") }
                let inheritsBaseline = record.entity != "way"
                let inherited = inheritsBaseline ? baselineResult : nil
                let effectiveBase = inherited.map { $0.unresolved ? nil : $0.kmh } ?? baseKmh
                let effectiveUnlimited = inherited.map { !$0.unresolved && $0.unlimited } ?? baseUnlimited
                var result = ConditionalSpeedRules.evaluate(rules, context: context, baseKmh: effectiveBase, baseUnlimited: effectiveUnlimited)
                result.reevaluation = ConditionalSpeedRules.Reevaluation(rulesJSON: record.rulesJSON,
                    baseKmh: effectiveBase, baseUnlimited: effectiveUnlimited, direction: direction,
                    countryCode: context.countryCode, timeZoneID: context.timeZoneID)
                result.reevaluation?.validFromUTC = record.validFromUTC
                result.reevaluation?.validUntilUTC = record.validUntilUTC
                result.reevaluation?.fallbackReevaluations = baselineResult?.reevaluation.map { [$0] }
                result.reevaluation?.fallbackUnresolved = baselineResult?.unresolved
                result.reevaluation?.fallbackReason = baselineResult?.reason
                if inheritsBaseline {
                    result.reevaluation?.baselineReevaluations = inherited?.reevaluation.map { [$0] }
                }
                if selected != nil {
                    return ConditionalSpeedRules.Result(kmh: nil, unlimited: false, unresolved: true, reason: "map_amendment_conflict")
                }
                selected = result
            }
        }
    }
}

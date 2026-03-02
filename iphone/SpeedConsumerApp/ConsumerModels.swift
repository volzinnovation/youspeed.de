import Foundation
import CryptoKit
import SQLite3

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

struct BundleArtifact: Codable, Sendable {
    let file: String
    let bytes: Int64
    let sha256: String
    let url: String?
}

struct BundleCoverageBBox: Codable, Sendable {
    let minLon: Double
    let minLat: Double
    let maxLon: Double
    let maxLat: Double

    enum CodingKeys: String, CodingKey {
        case minLon = "min_lon"
        case minLat = "min_lat"
        case maxLon = "max_lon"
        case maxLat = "max_lat"
    }
}

struct BundleCoverage: Codable, Sendable {
    let bbox: BundleCoverageBBox
    let poly: BundleArtifact?
}

struct V3BundleManifest: Codable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let region: String
    let countryCode: String?
    let bundleVersion: String
    let createdAtUTC: String
    let minAppVersion: String
    let db: BundleArtifact
    let dbParts: [BundleArtifact]?
    let deltaIndex: BundleArtifact?
    let penaltyRules: BundleArtifact?
    let coverage: BundleCoverage?

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case region
        case countryCode = "country_code"
        case bundleVersion = "bundle_version"
        case createdAtUTC = "created_at_utc"
        case minAppVersion = "min_app_version"
        case db
        case dbParts = "db_parts"
        case deltaIndex = "delta_index"
        case penaltyRules = "penalty_rules"
        case coverage
    }

    init(
        format: String,
        schemaVersion: Int,
        variant: String,
        region: String,
        countryCode: String? = nil,
        bundleVersion: String,
        createdAtUTC: String,
        minAppVersion: String,
        db: BundleArtifact,
        dbParts: [BundleArtifact]?,
        deltaIndex: BundleArtifact?,
        penaltyRules: BundleArtifact? = nil,
        coverage: BundleCoverage? = nil
    ) {
        self.format = format
        self.schemaVersion = schemaVersion
        self.variant = variant
        self.region = region
        self.countryCode = countryCode
        self.bundleVersion = bundleVersion
        self.createdAtUTC = createdAtUTC
        self.minAppVersion = minAppVersion
        self.db = db
        self.dbParts = dbParts
        self.deltaIndex = deltaIndex
        self.penaltyRules = penaltyRules
        self.coverage = coverage
    }
}

struct V3CountryBundleCatalogRegion: Codable, Sendable {
    let region: String
    let name: String
    let bundleVersion: String
    let manifest: BundleArtifact
    let coverage: BundleCoverage?

    enum CodingKeys: String, CodingKey {
        case region
        case name
        case bundleVersion = "bundle_version"
        case manifest
        case coverage
    }
}

struct V3CountryBundleCatalog: Codable, Sendable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let country: String
    let bundleVersion: String
    let createdAtUTC: String
    let maxCountryPBFBytes: Int64
    let regions: [V3CountryBundleCatalogRegion]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case country
        case bundleVersion = "bundle_version"
        case createdAtUTC = "created_at_utc"
        case maxCountryPBFBytes = "max_country_pbf_bytes"
        case regions
    }
}

struct V3BundleTargetRegionConfig: Codable, Sendable {
    let regionID: String

    enum CodingKeys: String, CodingKey {
        case regionID = "region_id"
    }
}

struct V3BundleTargetCountryConfig: Codable, Sendable {
    let rank: Int
    let countryID: String
    let countryCode: String
    let iso2: String?
    let mode: String
    let regions: [V3BundleTargetRegionConfig]

    enum CodingKeys: String, CodingKey {
        case rank
        case countryID = "country_id"
        case countryCode = "country_code"
        case iso2
        case mode
        case regions
    }
}

struct V3BundleTargetsConfig: Codable, Sendable {
    let format: String
    let schemaVersion: Int
    let variant: String
    let maxCountryPBFBytes: Int64
    let countries: [V3BundleTargetCountryConfig]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case variant
        case maxCountryPBFBytes = "max_country_pbf_bytes"
        case countries
    }

    func country(countryID: String) -> V3BundleTargetCountryConfig? {
        let key = countryID.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !key.isEmpty else {
            return nil
        }
        return countries.first { $0.countryID.lowercased() == key }
    }

    func country(countryCode: String) -> V3BundleTargetCountryConfig? {
        let key = countryCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !key.isEmpty else {
            return nil
        }
        return countries.first { $0.countryCode.uppercased() == key }
    }

    static func loadBundled(
        named resourceName: String = "BundleTargets.top10",
        bundle: Bundle = .main
    ) throws -> V3BundleTargetsConfig {
        guard let url = bundle.url(forResource: resourceName, withExtension: "json") else {
            throw ConsumerAppError.io("Missing bundled \(resourceName).json")
        }
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(V3BundleTargetsConfig.self, from: data)
    }
}

struct LocalBundleRoute: Sendable {
    let region: String
    let bundleVersion: String
    let countryCode: String?
    let dbPath: String
}

struct PenaltyRuleContext: Sendable {
    let countryCode: String?
    let rulesPath: String?
    let rulesFileName: String?
}

struct V3DeltaIndex: Codable {
    struct Entry: Codable {
        let fromBundleVersion: String
        let toBundleVersion: String
        let region: String?
        let deltaManifestFile: String

        enum CodingKeys: String, CodingKey {
            case fromBundleVersion = "from_bundle_version"
            case toBundleVersion = "to_bundle_version"
            case region
            case deltaManifestFile = "delta_manifest_file"
        }
    }

    let format: String
    let schemaVersion: Int
    let count: Int
    let entries: [Entry]

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case count
        case entries
    }
}

struct V3DeltaManifest: Codable {
    let format: String
    let schemaVersion: Int
    let region: String
    let fromBundleVersion: String
    let toBundleVersion: String
    let patch: BundleArtifact

    enum CodingKeys: String, CodingKey {
        case format
        case schemaVersion = "schema_version"
        case region
        case fromBundleVersion = "from_bundle_version"
        case toBundleVersion = "to_bundle_version"
        case patch
    }
}

struct ActiveBundleState: Codable {
    let region: String
    let bundleVersion: String
    let dbFileName: String
    let dbPath: String?
    let activatedAtUTC: String

    init(
        region: String,
        bundleVersion: String,
        dbFileName: String,
        activatedAtUTC: String,
        dbPath: String? = nil
    ) {
        self.region = region
        self.bundleVersion = bundleVersion
        self.dbFileName = dbFileName
        self.dbPath = dbPath
        self.activatedAtUTC = activatedAtUTC
    }

    enum CodingKeys: String, CodingKey {
        case region
        case bundleVersion = "bundle_version"
        case dbFileName = "db_file_name"
        case dbPath = "db_path"
        case activatedAtUTC = "activated_at_utc"
    }
}

struct BundleSyncResult: Codable {
    enum Mode: String, Codable {
        case bootstrap
        case upToDate
        case fullDownload
        case deltaPatch
    }

    let mode: Mode
    let bundleVersion: String
    let dbPath: String
    let details: String
}

struct BundleSyncProgress: Sendable {
    enum Stage: String, Sendable {
        case preparing
        case downloading
        case assembling
        case validating
        case applyingDelta
        case completed
    }

    let stage: Stage
    let detail: String
    let completedBytes: Int64
    let totalBytes: Int64
    let partDownloads: [PartDownloadProgress]
}

struct PartDownloadProgress: Sendable, Identifiable {
    let id: String
    let detail: String
    let completedBytes: Int64
    let totalBytes: Int64
}

struct SpeedLimitResult {
    let speedLimitKmh: Int?
    let wayID: String?
    let highway: String?
    let service: String?
    let tunnel: String?
    let bridge: String?
    let covered: String?
    let location: String?
    let layer: Int?
    let level: Int?
    let isTunnelSegment: Bool
    let streetName: String?
    let cityName: String?
    let insideCity: Bool?
    let citySource: String?
    let cityResolveMs: Double
    let cityCandidateBoundaries: Int
    let cityContainingBoundaries: Int
    let cityPlaceCandidates: Int
    let queryTimeMs: Double
    let candidateCount: Int
    let speedCandidateCount: Int
    let nearestCandidateDistanceM: Double?
    let nearestSpeedCandidateDistanceM: Double?
}

enum ConsumerAppError: Error, LocalizedError {
    case invalidManifest(String)
    case io(String)
    case network(String)
    case checksum(String)
    case sqlite(String)

    var errorDescription: String? {
        switch self {
        case .invalidManifest(let message): return message
        case .io(let message): return message
        case .network(let message): return message
        case .checksum(let message): return message
        case .sqlite(let message): return message
        }
    }
}

enum LocalObservationModality: String, Codable, Sendable {
    case voice_command
    case lock_current_speed
    case computer_vision
}

enum LocalObservationIntentType: String, Codable, Sendable {
    case set_maxspeed
    case temporary_restriction
    case map_inconsistency
    case lock_speed_snapshot
}

enum LocalObservationState: String, Codable, Sendable, CaseIterable {
    case localOnly = "local_only"
    case needsReview = "needs_review"
    case approvedForExport = "approved_for_export"
    case exportedOsc = "exported_osc"
    case editorImported = "editor_imported"
    case uploadedToOsm = "uploaded_to_osm"
    case discarded = "discarded"
}

struct LocalObservation: Codable, Sendable, Identifiable {
    let id: String
    let modality: LocalObservationModality
    let intentType: LocalObservationIntentType
    let value: String?
    let lat: Double?
    let lon: Double?
    let headingDeg: Double?
    let roadCandidateIDs: [String]
    let cityContext: String?
    let streetContext: String?
    let capturedAtUTC: String
    let confidenceCalibrated: Double?
    let sourceVersion: String
    let state: LocalObservationState
    let devicePseudoID: String
    let updatedAtUTC: String
    let exportID: String?
    let oldSpeedKmh: Int?
    let newSpeedKmh: Int?
}

struct LocalObservationCaptureContext: Sendable {
    let lat: Double?
    let lon: Double?
    let headingDeg: Double?
    let roadCandidateIDs: [String]
    let cityContext: String?
    let streetContext: String?
    let confidenceCalibrated: Double?
    let sourceVersion: String
}

struct LocalObservationProposal: Sendable {
    struct TargetObject: Sendable {
        let type: String
        let id: String
    }

    let observationID: String
    let targetObjects: [TargetObject]
    let oscXML: String
    let confidenceSummary: String
}

struct LocalObservationExportResult: Sendable {
    let exportID: String
    let packageDirectory: URL
    let changesFile: URL
    let reviewFile: URL
    let readmeFile: URL
}

struct LocalObservationBulkExportResult: Sendable {
    let exportID: String
    let packageDirectory: URL
    let changesFile: URL
    let includedCount: Int
}

actor LocalObservationStore {
    private let fileManager: FileManager
    private let userDefaults: UserDefaults
    private let bundle: Bundle
    private let rootDirectoryOverride: URL?
    private let nowProvider: @Sendable () -> Date
    private static let devicePseudoIDDefaultsKey = "youspeed.local_observation.device_pseudo_id"
    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    init(
        fileManager: FileManager = .default,
        userDefaults: UserDefaults = .standard,
        bundle: Bundle = .main,
        rootDirectoryOverride: URL? = nil,
        nowProvider: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.fileManager = fileManager
        self.userDefaults = userDefaults
        self.bundle = bundle
        self.rootDirectoryOverride = rootDirectoryOverride
        self.nowProvider = nowProvider
    }

    func captureVoiceCommand(command: String, context: LocalObservationCaptureContext) throws -> LocalObservation {
        let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw ConsumerAppError.io("Voice command must not be empty")
        }
        let parsedSpeed = Self.extractFirstSpeedKmh(from: trimmed)
        let intent: LocalObservationIntentType = parsedSpeed == nil ? .map_inconsistency : .set_maxspeed
        let value = parsedSpeed.map(String.init) ?? trimmed
        return try insertObservation(
            modality: .voice_command,
            intent: intent,
            value: value,
            context: context,
            initialState: .needsReview
        )
    }

    func lockCurrentSpeed(speedKmh: Int, context: LocalObservationCaptureContext) throws -> LocalObservation {
        guard speedKmh > 0 else {
            throw ConsumerAppError.io("Current speed must be > 0 to create lock observation")
        }
        return try insertObservation(
            modality: .lock_current_speed,
            intent: .lock_speed_snapshot,
            value: String(speedKmh),
            context: context,
            initialState: .needsReview,
            oldSpeedKmh: nil,
            newSpeedKmh: speedKmh
        )
    }

    func recordSpeedLimitChange(
        oldSpeedKmh: Int?,
        newSpeedKmh: Int,
        context: LocalObservationCaptureContext
    ) throws -> LocalObservation {
        guard newSpeedKmh > 0 else {
            throw ConsumerAppError.io("Recorded speed must be > 0 km/h")
        }
        return try insertObservation(
            modality: .lock_current_speed,
            intent: .set_maxspeed,
            value: String(newSpeedKmh),
            context: context,
            initialState: .localOnly,
            oldSpeedKmh: oldSpeedKmh,
            newSpeedKmh: newSpeedKmh
        )
    }

    func fetchObservations(states: [LocalObservationState]? = nil, limit: Int = 50) throws -> [LocalObservation] {
        try withDatabase { db in
            var sql = """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
            FROM observations
            """
            if let states, !states.isEmpty {
                let placeholders = Array(repeating: "?", count: states.count).joined(separator: ",")
                sql += " WHERE state IN (\(placeholders))"
            }
            sql += " ORDER BY captured_at_utc DESC LIMIT ?"

            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation fetch")
            }
            defer { sqlite3_finalize(stmt) }

            var bindIndex: Int32 = 1
            if let states, !states.isEmpty {
                for state in states {
                    sqlite3_bind_text(stmt, bindIndex, state.rawValue, -1, SQLITE_TRANSIENT)
                    bindIndex += 1
                }
            }
            sqlite3_bind_int64(stmt, bindIndex, Int64(max(1, limit)))

            var out: [LocalObservation] = []
            while sqlite3_step(stmt) == SQLITE_ROW {
                out.append(try decodeObservationRow(stmt))
            }
            return out
        }
    }

    func deleteObservation(observationID: String) throws {
        try withDatabase { db in
            let sql = "DELETE FROM observations WHERE observation_id = ?1"
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation delete")
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(stmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "execute observation delete")
            }
        }
    }

    func deleteAllObservations() throws -> Int {
        try withDatabase { db in
            var countStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM observations", -1, &countStmt, nil) == SQLITE_OK,
                  let countStmt else {
                throw sqliteError(db: db, context: "prepare observation count")
            }
            defer { sqlite3_finalize(countStmt) }
            let existingCount: Int
            if sqlite3_step(countStmt) == SQLITE_ROW {
                existingCount = Int(sqlite3_column_int64(countStmt, 0))
            } else {
                existingCount = 0
            }

            guard sqlite3_exec(db, "DELETE FROM observations", nil, nil, nil) == SQLITE_OK else {
                throw sqliteError(db: db, context: "delete all observations")
            }
            return existingCount
        }
    }

    func reviewAndApproveProposal(observationID: String) throws -> LocalObservation {
        try updateObservationState(observationID: observationID, newState: .approvedForExport)
    }

    func discardObservation(observationID: String) throws -> LocalObservation {
        try updateObservationState(observationID: observationID, newState: .discarded)
    }

    func buildOsmProposal(observationID: String) throws -> LocalObservationProposal {
        let observation = try fetchObservation(observationID: observationID)
        guard observation.state == .approvedForExport || observation.state == .needsReview else {
            throw ConsumerAppError.io("Observation \(observationID) is not exportable in current state \(observation.state.rawValue)")
        }
        guard let wayID = observation.roadCandidateIDs.first, !wayID.isEmpty else {
            throw ConsumerAppError.io("Observation \(observationID) has no road candidate id")
        }
        guard let rawValue = observation.value,
              let maxspeed = Int(rawValue.trimmingCharacters(in: .whitespacesAndNewlines)),
              maxspeed > 0 else {
            throw ConsumerAppError.io("Observation \(observationID) does not contain a numeric speed value")
        }

        let xml = Self.makeOsmChangeXML(wayID: wayID, maxspeed: maxspeed)
        let summary = observation.confidenceCalibrated.map { String(format: "confidence=%.2f", $0) } ?? "confidence=n/a"
        return LocalObservationProposal(
            observationID: observationID,
            targetObjects: [.init(type: "way", id: wayID)],
            oscXML: xml,
            confidenceSummary: summary
        )
    }

    func exportProposalAsOscPackage(observationID: String) throws -> LocalObservationExportResult {
        let proposal = try buildOsmProposal(observationID: observationID)
        let observation = try fetchObservation(observationID: observationID)
        guard observation.state == .approvedForExport else {
            throw ConsumerAppError.io("Observation must be approved_for_export before export")
        }

        let createdAt = nowProvider()
        let createdAtUTC = Self.isoFormatter.string(from: createdAt)
        let exportID = UUID().uuidString.lowercased()
        let packageDirectory = try exportsDirectory()
            .appendingPathComponent("osm-export-\(Self.safeTimestamp(createdAtUTC))-\(String(exportID.prefix(8)))", isDirectory: true)
        try createDirectoryIfNeeded(at: packageDirectory)

        let changesFile = packageDirectory.appendingPathComponent("changes.osc")
        let reviewFile = packageDirectory.appendingPathComponent("review.json")
        let readmeFile = packageDirectory.appendingPathComponent("README.txt")

        let oscData = Data(proposal.oscXML.utf8)
        try oscData.write(to: changesFile, options: .atomic)
        let reviewJSON = try makeReviewJSON(
            exportID: exportID,
            createdAtUTC: createdAtUTC,
            observation: observation,
            proposal: proposal
        )
        try reviewJSON.write(to: reviewFile, options: .atomic)
        try Data(Self.readmeTemplate.utf8).write(to: readmeFile, options: .atomic)

        let oscSHA = SHA256.hash(data: oscData).compactMap { String(format: "%02x", $0) }.joined()
        try withDatabase { db in
            let insertExportSQL = """
            INSERT OR REPLACE INTO exports (
              export_id, created_at_utc, package_path, package_sha256, observation_ids, returned_changeset_id
            ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)
            """
            var exportStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, insertExportSQL, -1, &exportStmt, nil) == SQLITE_OK, let exportStmt else {
                throw sqliteError(db: db, context: "prepare export insert")
            }
            defer { sqlite3_finalize(exportStmt) }
            sqlite3_bind_text(exportStmt, 1, exportID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 3, packageDirectory.path, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 4, oscSHA, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 5, "[\"\(observation.id)\"]", -1, SQLITE_TRANSIENT)
            guard sqlite3_step(exportStmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "insert export row")
            }

            let updateObsSQL = """
            UPDATE observations
               SET state = ?1, updated_at_utc = ?2, export_id = ?3
             WHERE observation_id = ?4
            """
            var updateStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, updateObsSQL, -1, &updateStmt, nil) == SQLITE_OK, let updateStmt else {
                throw sqliteError(db: db, context: "prepare observation update after export")
            }
            defer { sqlite3_finalize(updateStmt) }
            sqlite3_bind_text(updateStmt, 1, LocalObservationState.exportedOsc.rawValue, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(updateStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(updateStmt, 3, exportID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(updateStmt, 4, observation.id, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(updateStmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "update exported observation state")
            }
        }

        return LocalObservationExportResult(
            exportID: exportID,
            packageDirectory: packageDirectory,
            changesFile: changesFile,
            reviewFile: reviewFile,
            readmeFile: readmeFile
        )
    }

    func exportAllLocalObservationsAsOsc() throws -> LocalObservationBulkExportResult {
        let observations = try fetchObservations(limit: 1_000)
            .filter { $0.state != .discarded }
            .sorted { $0.capturedAtUTC < $1.capturedAtUTC }
        let reduced = observations.reduce(into: [String: LocalObservation]()) { partial, observation in
            guard let wayID = observation.roadCandidateIDs.first,
                  !wayID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  let newSpeed = observation.newSpeedKmh,
                  newSpeed > 0 else {
                return
            }
            partial[wayID] = observation
        }
        let payload = reduced.values.sorted { lhs, rhs in
            lhs.capturedAtUTC < rhs.capturedAtUTC
        }
        guard !payload.isEmpty else {
            throw ConsumerAppError.io("Keine lokalen Erfassungen mit Way-ID und neuer Geschwindigkeit vorhanden.")
        }

        let createdAt = nowProvider()
        let createdAtUTC = Self.isoFormatter.string(from: createdAt)
        let exportID = UUID().uuidString.lowercased()
        let packageDirectory = try exportsDirectory()
            .appendingPathComponent("osm-export-all-\(Self.safeTimestamp(createdAtUTC))-\(String(exportID.prefix(8)))", isDirectory: true)
        try createDirectoryIfNeeded(at: packageDirectory)

        let changesFile = packageDirectory.appendingPathComponent("changes.osc")
        let xml = Self.makeBulkOsmChangeXML(observations: payload)
        let oscData = Data(xml.utf8)
        try oscData.write(to: changesFile, options: .atomic)
        let oscSHA = SHA256.hash(data: oscData).compactMap { String(format: "%02x", $0) }.joined()

        let observationIDsJSONData = try JSONEncoder().encode(payload.map(\.id))
        let observationIDsJSON = String(data: observationIDsJSONData, encoding: .utf8) ?? "[]"

        try withDatabase { db in
            let insertExportSQL = """
            INSERT OR REPLACE INTO exports (
              export_id, created_at_utc, package_path, package_sha256, observation_ids, returned_changeset_id
            ) VALUES (?1, ?2, ?3, ?4, ?5, NULL)
            """
            var exportStmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, insertExportSQL, -1, &exportStmt, nil) == SQLITE_OK, let exportStmt else {
                throw sqliteError(db: db, context: "prepare bulk export insert")
            }
            defer { sqlite3_finalize(exportStmt) }
            sqlite3_bind_text(exportStmt, 1, exportID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 2, createdAtUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 3, packageDirectory.path, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 4, oscSHA, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(exportStmt, 5, observationIDsJSON, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(exportStmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "insert bulk export row")
            }
        }

        return LocalObservationBulkExportResult(
            exportID: exportID,
            packageDirectory: packageDirectory,
            changesFile: changesFile,
            includedCount: payload.count
        )
    }

    private func updateObservationState(observationID: String, newState: LocalObservationState) throws -> LocalObservation {
        let nowUTC = Self.isoFormatter.string(from: nowProvider())
        try withDatabase { db in
            let sql = """
            UPDATE observations
               SET state = ?1, updated_at_utc = ?2
             WHERE observation_id = ?3
            """
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation state update")
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, newState.rawValue, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 2, nowUTC, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 3, observationID, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(stmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "execute observation state update")
            }
        }
        return try fetchObservation(observationID: observationID)
    }

    private func insertObservation(
        modality: LocalObservationModality,
        intent: LocalObservationIntentType,
        value: String?,
        context: LocalObservationCaptureContext,
        initialState: LocalObservationState,
        oldSpeedKmh: Int? = nil,
        newSpeedKmh: Int? = nil
    ) throws -> LocalObservation {
        let id = UUID().uuidString.lowercased()
        let nowUTC = Self.isoFormatter.string(from: nowProvider())
        let devicePseudoID = ensureDevicePseudoID()
        let roadIDsData = try JSONEncoder().encode(context.roadCandidateIDs)
        let roadIDsJSON = String(data: roadIDsData, encoding: .utf8) ?? "[]"

        try withDatabase { db in
            let sql = """
            INSERT INTO observations (
              observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
              city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
              device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, NULL, ?17, ?18)
            """
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare observation insert")
            }
            defer { sqlite3_finalize(stmt) }

            sqlite3_bind_text(stmt, 1, id, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 2, modality.rawValue, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 3, intent.rawValue, -1, SQLITE_TRANSIENT)
            if let value {
                sqlite3_bind_text(stmt, 4, value, -1, SQLITE_TRANSIENT)
            } else {
                sqlite3_bind_null(stmt, 4)
            }
            bindOptionalDouble(context.lat, stmt: stmt, index: 5)
            bindOptionalDouble(context.lon, stmt: stmt, index: 6)
            bindOptionalDouble(context.headingDeg, stmt: stmt, index: 7)
            sqlite3_bind_text(stmt, 8, roadIDsJSON, -1, SQLITE_TRANSIENT)
            bindOptionalText(context.cityContext, stmt: stmt, index: 9)
            bindOptionalText(context.streetContext, stmt: stmt, index: 10)
            sqlite3_bind_text(stmt, 11, nowUTC, -1, SQLITE_TRANSIENT)
            bindOptionalDouble(context.confidenceCalibrated, stmt: stmt, index: 12)
            sqlite3_bind_text(stmt, 13, context.sourceVersion, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 14, initialState.rawValue, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 15, devicePseudoID, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, 16, nowUTC, -1, SQLITE_TRANSIENT)
            bindOptionalInt(oldSpeedKmh, stmt: stmt, index: 17)
            bindOptionalInt(newSpeedKmh, stmt: stmt, index: 18)

            guard sqlite3_step(stmt) == SQLITE_DONE else {
                throw sqliteError(db: db, context: "execute observation insert")
            }
        }
        return try fetchObservation(observationID: id)
    }

    private func fetchObservation(observationID: String) throws -> LocalObservation {
        try withDatabase { db in
            let sql = """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
            FROM observations
            WHERE observation_id = ?1
            LIMIT 1
            """
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                throw sqliteError(db: db, context: "prepare single observation fetch")
            }
            defer { sqlite3_finalize(stmt) }
            sqlite3_bind_text(stmt, 1, observationID, -1, SQLITE_TRANSIENT)
            guard sqlite3_step(stmt) == SQLITE_ROW else {
                throw ConsumerAppError.io("Observation not found: \(observationID)")
            }
            return try decodeObservationRow(stmt)
        }
    }

    private func decodeObservationRow(_ stmt: OpaquePointer) throws -> LocalObservation {
        guard let id = cString(sqlite3_column_text(stmt, 0)),
              let modalityRaw = cString(sqlite3_column_text(stmt, 1)),
              let modality = LocalObservationModality(rawValue: modalityRaw),
              let intentRaw = cString(sqlite3_column_text(stmt, 2)),
              let intent = LocalObservationIntentType(rawValue: intentRaw),
              let capturedAt = cString(sqlite3_column_text(stmt, 10)),
              let sourceVersion = cString(sqlite3_column_text(stmt, 12)),
              let stateRaw = cString(sqlite3_column_text(stmt, 13)),
              let state = LocalObservationState(rawValue: stateRaw),
              let devicePseudoID = cString(sqlite3_column_text(stmt, 14)),
              let updatedAt = cString(sqlite3_column_text(stmt, 15)) else {
            throw ConsumerAppError.sqlite("Invalid observation row")
        }

        let roadJSON = cString(sqlite3_column_text(stmt, 7)) ?? "[]"
        let roadIDs: [String]
        if let jsonData = roadJSON.data(using: .utf8),
           let decoded = try? JSONDecoder().decode([String].self, from: jsonData) {
            roadIDs = decoded
        } else {
            roadIDs = []
        }

        return LocalObservation(
            id: id,
            modality: modality,
            intentType: intent,
            value: cStringOptional(sqlite3_column_text(stmt, 3)),
            lat: sqliteOptionalDouble(stmt, index: 4),
            lon: sqliteOptionalDouble(stmt, index: 5),
            headingDeg: sqliteOptionalDouble(stmt, index: 6),
            roadCandidateIDs: roadIDs,
            cityContext: cStringOptional(sqlite3_column_text(stmt, 8)),
            streetContext: cStringOptional(sqlite3_column_text(stmt, 9)),
            capturedAtUTC: capturedAt,
            confidenceCalibrated: sqliteOptionalDouble(stmt, index: 11),
            sourceVersion: sourceVersion,
            state: state,
            devicePseudoID: devicePseudoID,
            updatedAtUTC: updatedAt,
            exportID: cStringOptional(sqlite3_column_text(stmt, 16)),
            oldSpeedKmh: sqliteOptionalInt(stmt, index: 17),
            newSpeedKmh: sqliteOptionalInt(stmt, index: 18)
        )
    }

    private func makeReviewJSON(
        exportID: String,
        createdAtUTC: String,
        observation: LocalObservation,
        proposal: LocalObservationProposal
    ) throws -> Data {
        let targetObjects = proposal.targetObjects.map { ["type": $0.type, "id": $0.id] }
        let payload: [String: Any] = [
            "export_id": exportID,
            "created_at_utc": createdAtUTC,
            "app_version": appVersion(),
            "data_bundle_version": observation.sourceVersion,
            "observation_ids": [observation.id],
            "target_objects": targetObjects,
            "street_context": observation.streetContext ?? "",
            "city_context": observation.cityContext ?? "",
            "suggested_changeset_comment": "Update maxspeed based on YouSpeed local observation",
            "suggested_changeset_source": "YouSpeed local observation",
            "confidence_summary": proposal.confidenceSummary,
        ]
        guard JSONSerialization.isValidJSONObject(payload) else {
            throw ConsumerAppError.io("Invalid review.json payload")
        }
        return try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
    }

    private static let readmeTemplate = """
    YouSpeed editor export package

    Files:
    - changes.osc
    - review.json
    - README.txt

    JOSM import:
    1. Open JOSM.
    2. File -> Open... and select changes.osc.
    3. Review all tag changes carefully.
    4. Upload using your own OSM account.

    Merkaartor import:
    1. Open Merkaartor.
    2. Import changes.osc.
    3. Review all edited objects and tags.
    4. Upload using your own OSM account.

    Important:
    - Final upload is always user-controlled in the editor.
    - You are responsible for reviewing correctness before upload.
    """

    private static func makeOsmChangeXML(wayID: String, maxspeed: Int) -> String {
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
            <way id="\(xmlEscape(wayID))">
              <tag k="maxspeed" v="\(maxspeed)"/>
            </way>
          </modify>
        </osmChange>
        """
    }

    private static func makeBulkOsmChangeXML(observations: [LocalObservation]) -> String {
        let body = observations.compactMap { observation -> String? in
            guard let wayID = observation.roadCandidateIDs.first,
                  let maxspeed = observation.newSpeedKmh else {
                return nil
            }
            return """
                <way id="\(xmlEscape(wayID))">
                  <tag k="maxspeed" v="\(maxspeed)"/>
                </way>
            """
        }.joined(separator: "\n")
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
        \(body)
          </modify>
        </osmChange>
        """
    }

    private static func xmlEscape(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func safeTimestamp(_ iso: String) -> String {
        iso.replacingOccurrences(of: ":", with: "").replacingOccurrences(of: "-", with: "")
    }

    private func appVersion() -> String {
        let short = (bundle.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "0.0.0"
        let build = (bundle.infoDictionary?["CFBundleVersion"] as? String) ?? "0"
        return "\(short) (\(build))"
    }

    private func ensureDevicePseudoID() -> String {
        if let existing = userDefaults.string(forKey: Self.devicePseudoIDDefaultsKey),
           !existing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return existing
        }
        let generated = UUID().uuidString.lowercased()
        userDefaults.set(generated, forKey: Self.devicePseudoIDDefaultsKey)
        return generated
    }

    private static func extractFirstSpeedKmh(from text: String) -> Int? {
        let pattern = #"\b([1-9][0-9]{0,2})\b"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..<text.endIndex, in: text)),
              let range = Range(match.range(at: 1), in: text),
              let value = Int(text[range]),
              (5...160).contains(value) else {
            return nil
        }
        return value
    }

    private func rootDir() throws -> URL {
        if let rootDirectoryOverride {
            try createDirectoryIfNeeded(at: rootDirectoryOverride)
            return rootDirectoryOverride
        }
        return try V3BundleManager.applicationSupportDirectory(fileManager: fileManager)
    }

    private func databaseURL() throws -> URL {
        try rootDir().appendingPathComponent("local_observation_store.sqlite")
    }

    private func exportsDirectory() throws -> URL {
        let url = try rootDir().appendingPathComponent("osm-editor-packages", isDirectory: true)
        try createDirectoryIfNeeded(at: url)
        return url
    }

    private func withDatabase<T>(_ block: (OpaquePointer) throws -> T) throws -> T {
        let dbURL = try databaseURL()
        let root = dbURL.deletingLastPathComponent()
        try createDirectoryIfNeeded(at: root)

        var db: OpaquePointer?
        let flags = SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(dbURL.path, &db, flags, nil) == SQLITE_OK, let db else {
            let msg = db.flatMap { sqlite3_errmsg($0).flatMap { String(cString: $0) } } ?? "unknown sqlite error"
            if let db {
                sqlite3_close(db)
            }
            throw ConsumerAppError.sqlite("open local observation store failed: \(msg)")
        }
        defer { sqlite3_close(db) }

        try ensureSchema(db: db)
        return try block(db)
    }

    private func ensureSchema(db: OpaquePointer) throws {
        let sql = """
        CREATE TABLE IF NOT EXISTS observations (
          observation_id TEXT PRIMARY KEY,
          modality TEXT NOT NULL,
          intent_type TEXT NOT NULL,
          value TEXT,
          lat REAL,
          lon REAL,
          heading_deg REAL,
          road_candidate_ids TEXT NOT NULL,
          city_context TEXT,
          street_context TEXT,
          captured_at_utc TEXT NOT NULL,
          confidence_calibrated REAL,
          source_version TEXT NOT NULL,
          state TEXT NOT NULL,
          device_pseudo_id TEXT NOT NULL,
          updated_at_utc TEXT NOT NULL,
          export_id TEXT,
          old_speed_kmh INTEGER,
          new_speed_kmh INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_observations_state ON observations(state);
        CREATE INDEX IF NOT EXISTS idx_observations_captured ON observations(captured_at_utc DESC);
        CREATE TABLE IF NOT EXISTS exports (
          export_id TEXT PRIMARY KEY,
          created_at_utc TEXT NOT NULL,
          package_path TEXT NOT NULL,
          package_sha256 TEXT NOT NULL,
          observation_ids TEXT NOT NULL,
          returned_changeset_id TEXT
        );
        """
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: "ensure local observation schema")
        }
        try ensureObservationColumn(db: db, columnName: "old_speed_kmh", typeDeclaration: "INTEGER")
        try ensureObservationColumn(db: db, columnName: "new_speed_kmh", typeDeclaration: "INTEGER")
    }

    private func ensureObservationColumn(
        db: OpaquePointer,
        columnName: String,
        typeDeclaration: String
    ) throws {
        let pragma = "PRAGMA table_info(observations)"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, pragma, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw sqliteError(db: db, context: "prepare schema table_info")
        }
        defer { sqlite3_finalize(stmt) }

        var exists = false
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let namePtr = sqlite3_column_text(stmt, 1),
               String(cString: namePtr) == columnName {
                exists = true
                break
            }
        }
        guard !exists else {
            return
        }
        let alterSQL = "ALTER TABLE observations ADD COLUMN \(columnName) \(typeDeclaration)"
        guard sqlite3_exec(db, alterSQL, nil, nil, nil) == SQLITE_OK else {
            throw sqliteError(db: db, context: "alter observations add \(columnName)")
        }
    }

    private func createDirectoryIfNeeded(at url: URL) throws {
        if !fileManager.fileExists(atPath: url.path) {
            try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
        }
    }

    private func sqliteError(db: OpaquePointer, context: String) -> ConsumerAppError {
        let message = sqlite3_errmsg(db).flatMap { String(cString: $0) } ?? "unknown sqlite error"
        return .sqlite("\(context): \(message)")
    }

    private func bindOptionalDouble(_ value: Double?, stmt: OpaquePointer, index: Int32) {
        if let value {
            sqlite3_bind_double(stmt, index, value)
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func bindOptionalText(_ value: String?, stmt: OpaquePointer, index: Int32) {
        if let value {
            sqlite3_bind_text(stmt, index, value, -1, SQLITE_TRANSIENT)
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func bindOptionalInt(_ value: Int?, stmt: OpaquePointer, index: Int32) {
        if let value {
            sqlite3_bind_int64(stmt, index, Int64(value))
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func sqliteOptionalDouble(_ stmt: OpaquePointer, index: Int32) -> Double? {
        if sqlite3_column_type(stmt, index) == SQLITE_NULL {
            return nil
        }
        return sqlite3_column_double(stmt, index)
    }

    private func sqliteOptionalInt(_ stmt: OpaquePointer, index: Int32) -> Int? {
        if sqlite3_column_type(stmt, index) == SQLITE_NULL {
            return nil
        }
        return Int(sqlite3_column_int64(stmt, index))
    }

    private func cString(_ ptr: UnsafePointer<UInt8>?) -> String? {
        guard let ptr else {
            return nil
        }
        return String(cString: ptr)
    }

    private func cStringOptional(_ ptr: UnsafePointer<UInt8>?) -> String? {
        guard let value = cString(ptr)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }
}

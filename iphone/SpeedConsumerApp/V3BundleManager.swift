import CryptoKit
import Foundation
import SQLite3

actor V3BundleManager {
    private let fileManager: FileManager
    private let session: URLSession
    private let decoder: JSONDecoder

    init(fileManager: FileManager = .default, session: URLSession = .shared) {
        self.fileManager = fileManager
        self.session = session
        self.decoder = JSONDecoder()
    }

    static func applicationSupportDirectory(fileManager: FileManager = .default) throws -> URL {
        let base = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appendingPathComponent("SpeedConsumer", isDirectory: true)
    }

    private func rootDir() throws -> URL {
        let dir = try Self.applicationSupportDirectory(fileManager: fileManager)
        if !fileManager.fileExists(atPath: dir.path) {
            try fileManager.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        return dir
    }

    private func bundlesDir() throws -> URL {
        let dir = try rootDir().appendingPathComponent("bundles", isDirectory: true)
        if !fileManager.fileExists(atPath: dir.path) {
            try fileManager.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        return dir
    }

    private func stateFileURL() throws -> URL {
        try rootDir().appendingPathComponent("active_bundle.json")
    }

    func activeState() throws -> ActiveBundleState? {
        let stateURL = try stateFileURL()
        guard fileManager.fileExists(atPath: stateURL.path) else {
            return nil
        }
        let data = try Data(contentsOf: stateURL)
        return try decoder.decode(ActiveBundleState.self, from: data)
    }

    func activeDatabaseURL() throws -> URL? {
        guard let state = try activeState() else {
            return nil
        }
        return try bundlesDir()
            .appendingPathComponent(state.bundleVersion, isDirectory: true)
            .appendingPathComponent(state.dbFileName)
    }

    func bootstrapSeedIfNeeded(resourceName: String = "speeds_v3", bundle: Bundle = .main) throws -> BundleSyncResult {
        if let state = try activeState() {
            let dbURL = try bundlesDir()
                .appendingPathComponent(state.bundleVersion, isDirectory: true)
                .appendingPathComponent(state.dbFileName)
            if fileManager.fileExists(atPath: dbURL.path) {
                return BundleSyncResult(mode: .upToDate, bundleVersion: state.bundleVersion, dbPath: dbURL.path, details: "existing active bundle")
            }
        }

        guard let source = bundle.url(forResource: resourceName, withExtension: "sqlite") else {
            throw ConsumerAppError.io("Missing bundled seed DB resource: \(resourceName).sqlite")
        }

        let version = "seed"
        let bundleDir = try bundlesDir().appendingPathComponent(version, isDirectory: true)
        if !fileManager.fileExists(atPath: bundleDir.path) {
            try fileManager.createDirectory(at: bundleDir, withIntermediateDirectories: true)
        }

        let dbFileName = "speeds_v3.sqlite"
        let dst = bundleDir.appendingPathComponent(dbFileName)
        if !fileManager.fileExists(atPath: dst.path) {
            let tmp = bundleDir.appendingPathComponent("\(dbFileName).tmp")
            if fileManager.fileExists(atPath: tmp.path) {
                try fileManager.removeItem(at: tmp)
            }
            try fileManager.copyItem(at: source, to: tmp)
            try fileManager.moveItem(at: tmp, to: dst)
        }

        try writeActiveState(
            ActiveBundleState(
                region: "unknown",
                bundleVersion: version,
                dbFileName: dbFileName,
                activatedAtUTC: nowUTC()
            )
        )

        return BundleSyncResult(mode: .bootstrap, bundleVersion: version, dbPath: dst.path, details: "seed bundle activated")
    }

    func syncFromManifestURL(_ manifestURL: URL) async throws -> BundleSyncResult {
        let manifestData = try await downloadData(from: manifestURL)
        let manifest = try decoder.decode(V3BundleManifest.self, from: manifestData)
        guard manifest.format == "youspeed.v3.bundle.manifest", manifest.variant == "v3" else {
            throw ConsumerAppError.invalidManifest("Unexpected manifest format or variant")
        }

        let current = try activeState()
        if current?.bundleVersion == manifest.bundleVersion,
           let currentDB = try activeDatabaseURL(),
           fileManager.fileExists(atPath: currentDB.path) {
            return BundleSyncResult(mode: .upToDate, bundleVersion: manifest.bundleVersion, dbPath: currentDB.path, details: "already active")
        }

        let forceFullReload = shouldForceFullReload(currentVersion: current?.bundleVersion, targetVersion: manifest.bundleVersion, maxAgeDays: 30)

        if !forceFullReload,
           let current,
           let deltaRef = manifest.deltaIndex,
           let result = try await tryApplyDelta(
               current: current,
               manifest: manifest,
               manifestURL: manifestURL,
               deltaIndexRef: deltaRef
           ) {
            return result
        }

        return try await fullDownloadActivate(manifest: manifest, manifestURL: manifestURL)
    }

    private func tryApplyDelta(
        current: ActiveBundleState,
        manifest: V3BundleManifest,
        manifestURL: URL,
        deltaIndexRef: BundleArtifact
    ) async throws -> BundleSyncResult? {
        let deltaIndexURL = try resolveArtifactURL(deltaIndexRef, relativeTo: manifestURL)
        let deltaIndexData = try await downloadData(from: deltaIndexURL)
        let deltaIndex = try decoder.decode(V3DeltaIndex.self, from: deltaIndexData)
        guard deltaIndex.format == "youspeed.v3.delta.index" else {
            throw ConsumerAppError.invalidManifest("Unexpected delta index format")
        }

        guard let entry = deltaIndex.entries.first(where: {
            $0.fromBundleVersion == current.bundleVersion && $0.toBundleVersion == manifest.bundleVersion
                && ($0.region == nil || $0.region == manifest.region)
        }) else {
            return nil
        }

        let deltaManifestURL = URL(string: entry.deltaManifestFile, relativeTo: deltaIndexURL)?.absoluteURL
        guard let deltaManifestURL else {
            throw ConsumerAppError.invalidManifest("Unable to resolve delta manifest URL")
        }

        let deltaManifestData = try await downloadData(from: deltaManifestURL)
        let deltaManifest = try decoder.decode(V3DeltaManifest.self, from: deltaManifestData)
        guard deltaManifest.fromBundleVersion == current.bundleVersion,
              deltaManifest.toBundleVersion == manifest.bundleVersion else {
            throw ConsumerAppError.invalidManifest("Delta manifest version mismatch")
        }

        let patchURL = try resolveArtifactURL(deltaManifest.patch, relativeTo: deltaManifestURL)
        let patchData = try await downloadData(from: patchURL)
        try validateSHA256(data: patchData, expectedHex: deltaManifest.patch.sha256, label: "delta patch")

        guard let activeDB = try activeDatabaseURL(), fileManager.fileExists(atPath: activeDB.path) else {
            return nil
        }

        let stagingDB = try stageCopyOfActiveDB(forVersion: manifest.bundleVersion)
        let patchSQL = String(decoding: patchData, as: UTF8.self)
        try applyPatchSQL(patchSQL, toDBPath: stagingDB.path)
        try activatePreparedDB(
            preparedDB: stagingDB,
            manifest: manifest,
            mode: .deltaPatch,
            details: "applied delta from \(current.bundleVersion)"
        )

        return BundleSyncResult(
            mode: .deltaPatch,
            bundleVersion: manifest.bundleVersion,
            dbPath: try activeDatabaseURL()?.path ?? stagingDB.path,
            details: "delta applied"
        )
    }

    private func fullDownloadActivate(manifest: V3BundleManifest, manifestURL: URL) async throws -> BundleSyncResult {
        let dbURL = try resolveArtifactURL(manifest.db, relativeTo: manifestURL)
        let dbData = try await downloadData(from: dbURL)
        try validateSHA256(data: dbData, expectedHex: manifest.db.sha256, label: "bundle db")

        let stagingDB = try writeStagingDB(data: dbData, version: manifest.bundleVersion)
        try quickValidateDB(at: stagingDB)
        try activatePreparedDB(
            preparedDB: stagingDB,
            manifest: manifest,
            mode: .fullDownload,
            details: "full bundle download"
        )

        return BundleSyncResult(
            mode: .fullDownload,
            bundleVersion: manifest.bundleVersion,
            dbPath: try activeDatabaseURL()?.path ?? stagingDB.path,
            details: "full bundle activated"
        )
    }

    private func activatePreparedDB(
        preparedDB: URL,
        manifest: V3BundleManifest,
        mode: BundleSyncResult.Mode,
        details: String
    ) throws {
        let bundleDir = try bundlesDir().appendingPathComponent(manifest.bundleVersion, isDirectory: true)
        if !fileManager.fileExists(atPath: bundleDir.path) {
            try fileManager.createDirectory(at: bundleDir, withIntermediateDirectories: true)
        }

        let finalDB = bundleDir.appendingPathComponent(manifest.db.file)
        let finalTmp = bundleDir.appendingPathComponent("\(manifest.db.file).tmp")
        if fileManager.fileExists(atPath: finalTmp.path) {
            try fileManager.removeItem(at: finalTmp)
        }
        if fileManager.fileExists(atPath: finalDB.path) {
            try fileManager.removeItem(at: finalDB)
        }
        try fileManager.moveItem(at: preparedDB, to: finalTmp)
        try fileManager.moveItem(at: finalTmp, to: finalDB)

        let manifestURL = bundleDir.appendingPathComponent("bundle-manifest.v3.json")
        let encodedManifest = try JSONEncoder().encode(manifest)
        try encodedManifest.write(to: manifestURL, options: .atomic)

        try writeActiveState(
            ActiveBundleState(
                region: manifest.region,
                bundleVersion: manifest.bundleVersion,
                dbFileName: manifest.db.file,
                activatedAtUTC: nowUTC()
            )
        )

        _ = mode
        _ = details
    }

    private func writeActiveState(_ state: ActiveBundleState) throws {
        let stateURL = try stateFileURL()
        let data = try JSONEncoder().encode(state)
        let tmp = stateURL.appendingPathExtension("tmp")
        if fileManager.fileExists(atPath: tmp.path) {
            try fileManager.removeItem(at: tmp)
        }
        try data.write(to: tmp, options: .atomic)
        if fileManager.fileExists(atPath: stateURL.path) {
            try fileManager.removeItem(at: stateURL)
        }
        try fileManager.moveItem(at: tmp, to: stateURL)
    }

    private func writeStagingDB(data: Data, version: String) throws -> URL {
        let stageDir = try rootDir().appendingPathComponent("staging", isDirectory: true)
        if !fileManager.fileExists(atPath: stageDir.path) {
            try fileManager.createDirectory(at: stageDir, withIntermediateDirectories: true)
        }
        let fileURL = stageDir.appendingPathComponent("\(version)-\(UUID().uuidString).sqlite")
        try data.write(to: fileURL, options: .atomic)
        return fileURL
    }

    private func stageCopyOfActiveDB(forVersion version: String) throws -> URL {
        guard let current = try activeDatabaseURL(), fileManager.fileExists(atPath: current.path) else {
            throw ConsumerAppError.io("No active DB for delta patch")
        }
        let stageDir = try rootDir().appendingPathComponent("staging", isDirectory: true)
        if !fileManager.fileExists(atPath: stageDir.path) {
            try fileManager.createDirectory(at: stageDir, withIntermediateDirectories: true)
        }
        let out = stageDir.appendingPathComponent("\(version)-delta-\(UUID().uuidString).sqlite")
        try fileManager.copyItem(at: current, to: out)
        return out
    }

    private func resolveArtifactURL(_ artifact: BundleArtifact, relativeTo baseURL: URL) throws -> URL {
        if let raw = artifact.url, let absolute = URL(string: raw), absolute.scheme != nil {
            return absolute
        }
        guard !artifact.file.isEmpty,
              let relative = URL(string: artifact.file, relativeTo: baseURL)?.absoluteURL else {
            throw ConsumerAppError.invalidManifest("Cannot resolve artifact URL for \(artifact.file)")
        }
        return relative
    }

    private func downloadData(from url: URL) async throws -> Data {
        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse,
              (200...299).contains(http.statusCode) else {
            throw ConsumerAppError.network("Unexpected HTTP response for \(url.absoluteString)")
        }
        return data
    }

    private func validateSHA256(data: Data, expectedHex: String, label: String) throws {
        let digest = SHA256.hash(data: data)
        let actual = digest.map { String(format: "%02x", $0) }.joined()
        if actual != expectedHex.lowercased() {
            throw ConsumerAppError.checksum("Checksum mismatch for \(label)")
        }
    }

    private func quickValidateDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open_v2(url.path, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for \(url.path)")
        }
        defer { sqlite3_close(db) }

        let required = ["ways", "ways_rtree", "way_geom"]
        for table in required {
            let escaped = table.replacingOccurrences(of: "'", with: "''")
            let sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='\(escaped)' LIMIT 1"
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK,
                  let stmt else {
                throw ConsumerAppError.sqlite("prepare failed for schema check")
            }
            defer { sqlite3_finalize(stmt) }
            if sqlite3_step(stmt) != SQLITE_ROW {
                throw ConsumerAppError.sqlite("missing table in v3 db: \(table)")
            }
        }

        if sqlite3_exec(db, "PRAGMA quick_check", nil, nil, nil) != SQLITE_OK {
            let msg = String(cString: sqlite3_errmsg(db))
            throw ConsumerAppError.sqlite("quick_check failed: \(msg)")
        }
    }

    private func applyPatchSQL(_ patchSQL: String, toDBPath path: String) throws {
        var db: OpaquePointer?
        guard sqlite3_open_v2(path, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK, let db else {
            throw ConsumerAppError.sqlite("sqlite open failed for patch application")
        }
        defer { sqlite3_close(db) }

        if sqlite3_exec(db, patchSQL, nil, nil, nil) != SQLITE_OK {
            let msg = String(cString: sqlite3_errmsg(db))
            throw ConsumerAppError.sqlite("delta patch failed: \(msg)")
        }
        if sqlite3_exec(db, "PRAGMA quick_check", nil, nil, nil) != SQLITE_OK {
            let msg = String(cString: sqlite3_errmsg(db))
            throw ConsumerAppError.sqlite("quick_check after patch failed: \(msg)")
        }
    }

    private func nowUTC() -> String {
        ISO8601DateFormatter().string(from: Date())
    }

    private func shouldForceFullReload(currentVersion: String?, targetVersion: String, maxAgeDays: Int) -> Bool {
        guard let currentVersion else {
            return false
        }
        if currentVersion == targetVersion {
            return false
        }
        guard let currentDay = parseDayVersion(currentVersion),
              let targetDay = parseDayVersion(targetVersion) else {
            return true
        }
        let deltaDays = Int(targetDay.timeIntervalSince(currentDay) / 86400.0)
        return deltaDays > maxAgeDays
    }

    private func parseDayVersion(_ value: String) -> Date? {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: value)
    }
}

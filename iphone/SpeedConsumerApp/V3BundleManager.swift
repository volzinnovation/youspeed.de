import CryptoKit
import Foundation
import OSLog
import SQLite3

actor V3BundleManager {
    private nonisolated static let logger = Logger(subsystem: "de.youspeed.SpeedConsumer", category: "bundle-manager")
    private struct CoverageRing {
        let isHole: Bool
        let points: [(lon: Double, lat: Double)]
    }

    private struct CoverageEntry {
        let region: String
        let bundleVersion: String
        let countryCode: String?
        let dbPath: String
        let bbox: BundleCoverageBBox
        let rings: [CoverageRing]
    }

    private let fileManager: FileManager
    private let session: URLSession
    private let decoder: JSONDecoder
    private let minimumFreeDiskReserveBytes: Int64 = 256 * 1024 * 1024
    private let coverageCacheTTLSeconds: TimeInterval = 60
    private var githubToken: String?
    private var githubAssetURLByReleaseURL: [String: URL] = [:]
    private var githubReleaseAssetsByTagKey: [String: [String: Int64]] = [:]
    private var coverageCacheUpdatedAt: Date?
    private var cachedCoverageEntries: [CoverageEntry] = []

    func configuredShardRegions(forCountryCode countryCode: String) -> [String] {
        guard let config = try? V3BundleTargetsConfig.loadBundled(),
              let country = config.country(countryCode: countryCode) else {
            return []
        }
        return country.regions.map(\.regionID)
    }

    init(fileManager: FileManager = .default, session: URLSession = .shared) {
        self.fileManager = fileManager
        self.session = session
        self.decoder = JSONDecoder()
    }

    func setGitHubToken(_ token: String?) {
        let trimmed = token?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let normalized = trimmed.isEmpty ? nil : trimmed
        if githubToken != normalized {
            githubAssetURLByReleaseURL = [:]
            githubReleaseAssetsByTagKey = [:]
        }
        githubToken = normalized
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
        return try resolveDatabaseURL(for: state)
    }

    func resolveLocalBundleRoute(lat: Double, lon: Double, fallbackDBPath: String?) throws -> LocalBundleRoute? {
        let entries = try loadCoverageEntriesIfNeeded()
        guard !entries.isEmpty else {
            if let fallback = fallbackDBPath?.trimmingCharacters(in: .whitespacesAndNewlines), !fallback.isEmpty {
                return LocalBundleRoute(region: "unknown", bundleVersion: "unknown", countryCode: nil, dbPath: fallback)
            }
            return nil
        }

        if let fallback = fallbackDBPath?.trimmingCharacters(in: .whitespacesAndNewlines), !fallback.isEmpty,
           let current = entries.first(where: { $0.dbPath == fallback }),
           pointIsInsideCoverage(lon: lon, lat: lat, entry: current) {
            return LocalBundleRoute(
                region: current.region,
                bundleVersion: current.bundleVersion,
                countryCode: current.countryCode,
                dbPath: current.dbPath
            )
        }

        let matches = entries.filter { pointIsInsideCoverage(lon: lon, lat: lat, entry: $0) }
        if matches.isEmpty {
            if let fallback = fallbackDBPath?.trimmingCharacters(in: .whitespacesAndNewlines), !fallback.isEmpty {
                return LocalBundleRoute(region: "unknown", bundleVersion: "unknown", countryCode: nil, dbPath: fallback)
            }
            return nil
        }

        let best = matches.sorted { lhs, rhs in
            let lhsArea = bboxArea(lhs.bbox)
            let rhsArea = bboxArea(rhs.bbox)
            if lhsArea != rhsArea {
                return lhsArea < rhsArea
            }
            if lhs.bundleVersion != rhs.bundleVersion {
                return lhs.bundleVersion > rhs.bundleVersion
            }
            return lhs.region < rhs.region
        }.first!

        return LocalBundleRoute(
            region: best.region,
            bundleVersion: best.bundleVersion,
            countryCode: best.countryCode,
            dbPath: best.dbPath
        )
    }

    func resolvePenaltyRuleContext(forDBPath dbPath: String?) throws -> PenaltyRuleContext? {
        guard let dbPath, !dbPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        let normalizedDBPath = URL(fileURLWithPath: dbPath).standardizedFileURL.path
        let bundlesRoot = try bundlesDir()
        let bundleDirs = try fileManager.contentsOfDirectory(
            at: bundlesRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ).filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }

        for bundleDir in bundleDirs {
            let manifestURL = bundleDir.appendingPathComponent("bundle-manifest.v3.json")
            guard let manifest = decodeManifestIfPresent(at: manifestURL) else {
                continue
            }
            let manifestDBPath = bundleDir.appendingPathComponent(manifest.db.file).standardizedFileURL.path
            guard manifestDBPath == normalizedDBPath else {
                continue
            }
            var rulesPath: String?
            var rulesFileName: String?
            if let penaltyRules = manifest.penaltyRules {
                let candidate = bundleDir.appendingPathComponent(penaltyRules.file)
                rulesFileName = penaltyRules.file
                if fileManager.fileExists(atPath: candidate.path) {
                    rulesPath = candidate.path
                }
            }
            return PenaltyRuleContext(
                countryCode: manifest.countryCode,
                rulesPath: rulesPath,
                rulesFileName: rulesFileName
            )
        }
        return nil
    }

    /// Removes writable local correction artifacts so the app can rely on
    /// upstream OSM-derived daily diffs after user-side editor uploads.
    /// Does not remove active runtime bundles or active bundle state.
    func flushLocalContributionState() throws -> Int {
        let root = try rootDir()
        let sqliteBaseNames = [
            "local_corrections.sqlite",
            "local_overrides.sqlite",
            "local_observation_store.sqlite",
            "local_overlay_cache.sqlite",
            "osm-editor-export-outbox.sqlite",
        ]
        let sqliteCompanionSuffixes = ["", "-shm", "-wal"]
        let removableFiles = sqliteBaseNames.flatMap { baseName in
            sqliteCompanionSuffixes.map { suffix in
                root.appendingPathComponent(baseName + suffix)
            }
        }
        let removableDirectories = [
            root.appendingPathComponent("osm-editor-export-outbox", isDirectory: true),
            root.appendingPathComponent("osm-editor-packages", isDirectory: true),
            root.appendingPathComponent("local-corrections-export", isDirectory: true),
            root.appendingPathComponent("local_observation_store", isDirectory: true),
            root.appendingPathComponent("local_overlay_cache", isDirectory: true),
        ]

        var removedCount = 0
        for fileURL in removableFiles {
            if fileManager.fileExists(atPath: fileURL.path) {
                try removeItemIfExists(at: fileURL)
                removedCount += 1
            }
        }
        for directoryURL in removableDirectories {
            if fileManager.fileExists(atPath: directoryURL.path) {
                try removeItemIfExists(at: directoryURL)
                removedCount += 1
            }
        }
        Self.logger.notice("maintenance flush_local_contribution_state removed=\(removedCount, privacy: .public)")
        return removedCount
    }

    private func resolveDatabaseURL(for state: ActiveBundleState) throws -> URL {
        if let explicitPath = state.dbPath?.trimmingCharacters(in: .whitespacesAndNewlines),
           !explicitPath.isEmpty {
            return URL(fileURLWithPath: explicitPath, isDirectory: false)
        }
        let root = try bundlesDir()
        let preferred = root
            .appendingPathComponent(bundleDirectoryName(region: state.region, bundleVersion: state.bundleVersion), isDirectory: true)
            .appendingPathComponent(state.dbFileName)
        if fileManager.fileExists(atPath: preferred.path) {
            return preferred
        }
        return root
            .appendingPathComponent(state.bundleVersion, isDirectory: true)
            .appendingPathComponent(state.dbFileName)
    }

    private func bundleDirectoryName(region: String, bundleVersion: String) -> String {
        let regionKey = region
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .replacingOccurrences(of: "_", with: "-")
        let versionKey = normalizeBundleVersion(bundleVersion)
        if regionKey.isEmpty || regionKey == "unknown" {
            return versionKey
        }
        return "\(regionKey)-\(versionKey)"
    }

    func recoverLocalDataAtStartup(
        onProgress: (@Sendable (_ detail: String, _ fraction: Double) -> Void)? = nil
    ) throws -> BundleSyncResult? {
        Self.logger.notice("startup_recovery begin")
        var seedFallback: BundleSyncResult?

        emitStartupProgress(onProgress, detail: "Pruefe aktives Bundle", fraction: 0.05)
        if let active = try recoverFromActiveState(onProgress: onProgress) {
            if active.bundleVersion == "seed" {
                seedFallback = active
                Self.logger.notice("startup_recovery active_state seed_kept_as_fallback")
            } else {
                Self.logger.notice("startup_recovery active_state recovered version=\(active.bundleVersion, privacy: .public)")
                try? cleanupStagingArtifacts()
                try? cleanupMultipartCacheArtifacts(removeAll: false)
                return active
            }
        }

        let hasRecoveryArtifacts = (try? hasAnyLocalRecoveryArtifacts()) ?? false
        if !hasRecoveryArtifacts {
            emitStartupProgress(onProgress, detail: "Keine lokalen Download-Daten gefunden", fraction: 0.9)
            if let seedFallback {
                try? cleanupStagingArtifacts()
                try? cleanupMultipartCacheArtifacts(removeAll: true)
                Self.logger.notice("startup_recovery fast_path using_existing_seed")
                return seedFallback
            }
            emitStartupProgress(onProgress, detail: "Keine wiederverwendbaren lokalen Daten gefunden", fraction: 1.0)
            Self.logger.notice("startup_recovery fast_path no_recovery_artifacts")
            return nil
        }

        emitStartupProgress(onProgress, detail: "Suche heruntergeladene Bundles", fraction: 0.18)
        if let bundle = try recoverFromBundleDirectories(onProgress: onProgress, includeSeed: false) {
            Self.logger.notice("startup_recovery bundles recovered version=\(bundle.bundleVersion, privacy: .public)")
            try? cleanupStagingArtifacts()
            try? cleanupMultipartCacheArtifacts(removeAll: false)
            return bundle
        }

        emitStartupProgress(onProgress, detail: "Pruefe teilweise heruntergeladene Daten", fraction: 0.62)
        if let staging = try recoverFromStagingArtifacts(onProgress: onProgress) {
            Self.logger.notice("startup_recovery staging recovered version=\(staging.bundleVersion, privacy: .public)")
            try? cleanupStagingArtifacts()
            try? cleanupMultipartCacheArtifacts(removeAll: false)
            return staging
        }

        emitStartupProgress(onProgress, detail: "Pruefe zusammengesetzte Download-Dateien", fraction: 0.78)
        if let cache = try recoverFromMultipartAssembledCache(onProgress: onProgress) {
            Self.logger.notice("startup_recovery multipart_cache recovered version=\(cache.bundleVersion, privacy: .public)")
            try? cleanupStagingArtifacts()
            try? cleanupMultipartCacheArtifacts(removeAll: false)
            return cache
        }

        emitStartupProgress(onProgress, detail: "Pruefe Seed-Bundle als Rueckfall", fraction: 0.9)
        if seedFallback == nil {
            seedFallback = try recoverFromBundleDirectories(onProgress: onProgress, includeSeed: true, onlySeed: true)
            if seedFallback != nil {
                Self.logger.notice("startup_recovery seed_fallback recovered_from_bundles")
            }
        }
        if let seedFallback {
            try? cleanupStagingArtifacts()
            // Download artifacts were not recoverable; remove stale remnants to free space.
            try? cleanupMultipartCacheArtifacts(removeAll: true)
            Self.logger.notice("startup_recovery fallback_using_seed")
            return seedFallback
        }

        emitStartupProgress(onProgress, detail: "Entferne unbrauchbare Download-Reste", fraction: 0.9)
        try? cleanupStagingArtifacts()
        try? cleanupMultipartCacheArtifacts(removeAll: true)
        emitStartupProgress(onProgress, detail: "Keine wiederverwendbaren lokalen Daten gefunden", fraction: 1.0)
        Self.logger.notice("startup_recovery no_recoverable_local_data")
        return nil
    }

    func bootstrapSeedIfNeeded(resourceName: String = "speeds_v3", bundle: Bundle = .main) throws -> BundleSyncResult {
        let bundledSeed = bundle.url(forResource: resourceName, withExtension: "sqlite")

        if let state = try activeState() {
            let dbURL = try resolveDatabaseURL(for: state)
            if fileManager.fileExists(atPath: dbURL.path) {
                if state.bundleVersion == "seed", let bundledSeed {
                    let bundledPath = bundledSeed.path
                    if dbURL.path != bundledPath {
                        let migrated = ActiveBundleState(
                            region: state.region,
                            bundleVersion: state.bundleVersion,
                            dbFileName: state.dbFileName,
                            activatedAtUTC: nowUTC(),
                            dbPath: bundledPath
                        )
                        try writeActiveState(migrated)
                        let seedDir = try bundlesDir().appendingPathComponent("seed", isDirectory: true)
                        try? removeItemIfExists(at: seedDir)
                        Self.logger.notice("seed bootstrap migrated_to_bundled_resource")
                        return BundleSyncResult(
                            mode: .bootstrap,
                            bundleVersion: state.bundleVersion,
                            dbPath: bundledPath,
                            details: "seed bundle referenced"
                        )
                    }
                }
                return BundleSyncResult(mode: .upToDate, bundleVersion: state.bundleVersion, dbPath: dbURL.path, details: "existing active bundle")
            }
            try? clearActiveState()
        }

        guard let source = bundledSeed else {
            // Bundled seed is optional; app can continue with manifest/release download flow.
            return BundleSyncResult(
                mode: .upToDate,
                bundleVersion: "none",
                dbPath: "",
                details: "no bundled seed resource"
            )
        }
        try quickValidateDB(at: source, runQuickCheck: false)

        try writeActiveState(
            ActiveBundleState(
                region: "DEU",
                bundleVersion: "seed",
                dbFileName: "speeds_v3.sqlite",
                activatedAtUTC: nowUTC(),
                dbPath: source.path
            )
        )
        let seedDir = try bundlesDir().appendingPathComponent("seed", isDirectory: true)
        try? removeItemIfExists(at: seedDir)

        return BundleSyncResult(
            mode: .bootstrap,
            bundleVersion: "seed",
            dbPath: source.path,
            details: "seed bundle referenced"
        )
    }

    func syncFromManifestURL(
        _ manifestURL: URL,
        onProgress: (@Sendable (BundleSyncProgress) -> Void)? = nil
    ) async throws -> BundleSyncResult {
        Self.logger.notice("sync manifest begin url=\(manifestURL.absoluteString, privacy: .public)")
        try? cleanupStagingArtifacts()
        emitProgress(
            onProgress,
            stage: .preparing,
            detail: "Loading bundle manifest",
            completedBytes: 0,
            totalBytes: 0
        )
        let manifestData = try await downloadData(from: manifestURL)
        let manifest = try decoder.decode(V3BundleManifest.self, from: manifestData)
        guard manifest.format == "youspeed.v3.bundle.manifest", manifest.variant == "v3" else {
            throw ConsumerAppError.invalidManifest("Unexpected manifest format or variant")
        }
        Self.logger.notice(
            "sync manifest loaded version=\(manifest.bundleVersion, privacy: .public) region=\(manifest.region, privacy: .public) has_parts=\((manifest.dbParts?.isEmpty == false), privacy: .public)"
        )

        do {
            let current = try activeState()
            if current?.bundleVersion == manifest.bundleVersion,
               let currentDB = try activeDatabaseURL(),
               fileManager.fileExists(atPath: currentDB.path) {
                emitProgress(
                    onProgress,
                    stage: .completed,
                    detail: "Bundle already up to date",
                    completedBytes: manifest.db.bytes,
                    totalBytes: manifest.db.bytes
                )
                try? cleanupStagingArtifacts()
                Self.logger.notice("sync manifest up_to_date version=\(manifest.bundleVersion, privacy: .public)")
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
                   deltaIndexRef: deltaRef,
                   onProgress: onProgress
               ) {
                emitProgress(
                    onProgress,
                    stage: .completed,
                    detail: "Delta update applied",
                    completedBytes: manifest.db.bytes,
                    totalBytes: manifest.db.bytes
                )
                try? cleanupStagingArtifacts()
                Self.logger.notice("sync manifest delta_applied version=\(manifest.bundleVersion, privacy: .public)")
                return result
            }

            let fullDownload = try await fullDownloadActivate(
                manifest: manifest,
                manifestURL: manifestURL,
                onProgress: onProgress
            )
            emitProgress(
                onProgress,
                stage: .completed,
                detail: "Download completed",
                completedBytes: manifest.db.bytes,
                totalBytes: manifest.db.bytes
            )
            try? cleanupStagingArtifacts()
            Self.logger.notice("sync manifest full_download_completed version=\(manifest.bundleVersion, privacy: .public)")
            return fullDownload
        } catch {
            try? cleanupStagingArtifacts()
            Self.logger.error("sync manifest failed error=\(String(describing: error), privacy: .public)")
            throw error
        }
    }

    private func tryApplyDelta(
        current: ActiveBundleState,
        manifest: V3BundleManifest,
        manifestURL: URL,
        deltaIndexRef: BundleArtifact,
        onProgress: (@Sendable (BundleSyncProgress) -> Void)?
    ) async throws -> BundleSyncResult? {
        emitProgress(
            onProgress,
            stage: .preparing,
            detail: "Loading delta index",
            completedBytes: 0,
            totalBytes: 0
        )
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

        guard let activeDB = try activeDatabaseURL(), fileManager.fileExists(atPath: activeDB.path) else {
            return nil
        }
        let activeDBBytes = try fileSize(activeDB)
        try ensureSufficientDiskSpace(
            requiredBytes: activeDBBytes + deltaManifest.patch.bytes,
            reason: "delta update staging"
        )

        let patchURL = try resolveArtifactURL(deltaManifest.patch, relativeTo: deltaManifestURL)
        emitProgress(
            onProgress,
            stage: .downloading,
            detail: "Downloading delta patch",
            completedBytes: 0,
            totalBytes: deltaManifest.patch.bytes
        )
        let patchData = try await downloadData(from: patchURL)
        try validateSHA256(data: patchData, expectedHex: deltaManifest.patch.sha256, label: "delta patch")

        let stagingDB = try stageCopyOfActiveDB(forVersion: manifest.bundleVersion)
        let patchSQL = String(decoding: patchData, as: UTF8.self)
        do {
            emitProgress(
                onProgress,
                stage: .applyingDelta,
                detail: "Applying delta patch",
                completedBytes: deltaManifest.patch.bytes,
                totalBytes: deltaManifest.patch.bytes
            )
            try applyPatchSQL(patchSQL, toDBPath: stagingDB.path)
            try activatePreparedDB(
                preparedDB: stagingDB,
                manifest: manifest,
                mode: .deltaPatch,
                details: "applied delta from \(current.bundleVersion)"
            )
        } catch {
            try? removeItemIfExists(at: stagingDB)
            throw error
        }

        return BundleSyncResult(
            mode: .deltaPatch,
            bundleVersion: manifest.bundleVersion,
            dbPath: try activeDatabaseURL()?.path ?? stagingDB.path,
            details: "delta applied"
        )
    }

    private func fullDownloadActivate(
        manifest: V3BundleManifest,
        manifestURL: URL,
        onProgress: (@Sendable (BundleSyncProgress) -> Void)?
    ) async throws -> BundleSyncResult {
        emitProgress(
            onProgress,
            stage: .preparing,
            detail: "Checking free disk space",
            completedBytes: 0,
            totalBytes: 0
        )
        let requiredBytes = manifest.db.bytes
        try ensureSufficientDiskSpace(requiredBytes: requiredBytes, reason: "bundle download")

        let stagingDB: URL
        if let dbParts = manifest.dbParts, !dbParts.isEmpty {
            stagingDB = try await writeMultipartStagingDB(
                parts: dbParts,
                manifest: manifest,
                manifestURL: manifestURL,
                onProgress: onProgress
            )
        } else {
            let dbURL = try resolveArtifactURL(manifest.db, relativeTo: manifestURL)
            let declaredBytes = manifest.db.bytes
            let detail = "Downloading \(manifest.db.file)"
            emitProgress(
                onProgress,
                stage: .downloading,
                detail: detail,
                completedBytes: 0,
                totalBytes: declaredBytes
            )
            let downloaded = try await downloadFile(from: dbURL) { completedBytes, totalBytes in
                let expected = totalBytes ?? declaredBytes
                onProgress?(
                    BundleSyncProgress(
                        stage: .downloading,
                        detail: detail,
                        completedBytes: max(0, min(completedBytes, expected)),
                        totalBytes: max(0, expected),
                        partDownloads: []
                    )
                )
            }
            defer {
                try? removeItemIfExists(at: downloaded)
            }
            try validateSHA256(fileAt: downloaded, expectedHex: manifest.db.sha256, label: "bundle db")
            stagingDB = try writeStagingDB(downloadedFile: downloaded, version: manifest.bundleVersion)
        }

        do {
            emitProgress(
                onProgress,
                stage: .validating,
                detail: "Checking downloaded database schema",
                completedBytes: manifest.db.bytes,
                totalBytes: manifest.db.bytes
            )
            // Full-file SHA256 was already validated during download/assembly.
            // Keep startup responsive by skipping heavy PRAGMA quick_check here.
            try quickValidateDB(at: stagingDB, runQuickCheck: false)
            try activatePreparedDB(
                preparedDB: stagingDB,
                manifest: manifest,
                mode: .fullDownload,
                details: "full bundle download"
            )
        } catch {
            try? removeItemIfExists(at: stagingDB)
            throw error
        }

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
        let bundleDir = try bundlesDir().appendingPathComponent(
            bundleDirectoryName(region: manifest.region, bundleVersion: manifest.bundleVersion),
            isDirectory: true
        )
        if !fileManager.fileExists(atPath: bundleDir.path) {
            try fileManager.createDirectory(at: bundleDir, withIntermediateDirectories: true)
        }

        let finalDB = bundleDir.appendingPathComponent(manifest.db.file)
        let finalTmp = bundleDir.appendingPathComponent("\(manifest.db.file).tmp")
        let sqliteCompanionSuffixes = ["-wal", "-shm"]
        do {
            try? removeItemIfExists(at: finalTmp)
            for suffix in sqliteCompanionSuffixes {
                let preparedCompanion = sqliteCompanionURL(for: preparedDB, suffix: suffix)
                let finalTmpCompanion = sqliteCompanionURL(for: finalTmp, suffix: suffix)
                try? removeItemIfExists(at: finalTmpCompanion)
                if fileManager.fileExists(atPath: preparedCompanion.path) {
                    try fileManager.moveItem(at: preparedCompanion, to: finalTmpCompanion)
                }
            }
            try fileManager.moveItem(at: preparedDB, to: finalTmp)
            if fileManager.fileExists(atPath: finalDB.path) {
                _ = try fileManager.replaceItemAt(finalDB, withItemAt: finalTmp)
            } else {
                try fileManager.moveItem(at: finalTmp, to: finalDB)
            }
            for suffix in sqliteCompanionSuffixes {
                let finalCompanion = sqliteCompanionURL(for: finalDB, suffix: suffix)
                let finalTmpCompanion = sqliteCompanionURL(for: finalTmp, suffix: suffix)
                try? removeItemIfExists(at: finalCompanion)
                if fileManager.fileExists(atPath: finalTmpCompanion.path) {
                    try fileManager.moveItem(at: finalTmpCompanion, to: finalCompanion)
                }
            }
        } catch {
            try? removeItemIfExists(at: finalTmp)
            try? removeItemIfExists(at: preparedDB)
            for suffix in sqliteCompanionSuffixes {
                let preparedCompanion = sqliteCompanionURL(for: preparedDB, suffix: suffix)
                let finalTmpCompanion = sqliteCompanionURL(for: finalTmp, suffix: suffix)
                try? removeItemIfExists(at: preparedCompanion)
                try? removeItemIfExists(at: finalTmpCompanion)
            }
            throw error
        }

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
        try? pruneInactiveBundles(keepingVersions: [manifest.bundleVersion])

        _ = mode
        _ = details
    }

    private func recoverFromActiveState(
        onProgress: (@Sendable (_ detail: String, _ fraction: Double) -> Void)?
    ) throws -> BundleSyncResult? {
        guard let state = try activeState() else {
            Self.logger.notice("startup_recovery active_state missing")
            return nil
        }
        let dbURL = try resolveDatabaseURL(for: state)
        Self.logger.notice(
            "startup_recovery active_state candidate version=\(state.bundleVersion, privacy: .public) db=\(dbURL.lastPathComponent, privacy: .public)"
        )
        guard fileManager.fileExists(atPath: dbURL.path) else {
            Self.logger.error("startup_recovery active_state file_missing path=\(dbURL.path, privacy: .public)")
            if state.dbPath == nil {
                let preferredDir = try bundlesDir().appendingPathComponent(
                    bundleDirectoryName(region: state.region, bundleVersion: state.bundleVersion),
                    isDirectory: true
                )
                let legacyDir = try bundlesDir().appendingPathComponent(state.bundleVersion, isDirectory: true)
                try? removeItemIfExists(at: preferredDir)
                try? removeItemIfExists(at: legacyDir)
            }
            try? clearActiveState()
            return nil
        }
        emitStartupProgress(onProgress, detail: "Validiere aktives Bundle \(state.bundleVersion)", fraction: 0.12)
        do {
            try quickValidateDB(at: dbURL, runQuickCheck: false)
            Self.logger.notice("startup_recovery active_state validated version=\(state.bundleVersion, privacy: .public)")
            return BundleSyncResult(
                mode: .upToDate,
                bundleVersion: state.bundleVersion,
                dbPath: dbURL.path,
                details: "recovered active bundle"
            )
        } catch {
            Self.logger.error(
                "startup_recovery active_state invalid version=\(state.bundleVersion, privacy: .public) error=\(String(describing: error), privacy: .public)"
            )
            if state.dbPath == nil {
                let preferredDir = try bundlesDir().appendingPathComponent(
                    bundleDirectoryName(region: state.region, bundleVersion: state.bundleVersion),
                    isDirectory: true
                )
                let legacyDir = try bundlesDir().appendingPathComponent(state.bundleVersion, isDirectory: true)
                try? removeItemIfExists(at: preferredDir)
                try? removeItemIfExists(at: legacyDir)
            }
            try? clearActiveState()
            return nil
        }
    }

    private func recoverFromBundleDirectories(
        onProgress: (@Sendable (_ detail: String, _ fraction: Double) -> Void)?,
        includeSeed: Bool,
        onlySeed: Bool = false
    ) throws -> BundleSyncResult? {
        let bundlesRoot = try bundlesDir()
        let entries = try fileManager.contentsOfDirectory(
            at: bundlesRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        var directories = entries.filter { entry in
            (try? entry.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        }
        if onlySeed {
            directories = directories.filter { $0.lastPathComponent == "seed" }
        } else if !includeSeed {
            directories = directories.filter { $0.lastPathComponent != "seed" }
        }
        directories.sort { $0.lastPathComponent > $1.lastPathComponent }
        if includeSeed, let seedIndex = directories.firstIndex(where: { $0.lastPathComponent == "seed" }) {
            let seed = directories.remove(at: seedIndex)
            directories.append(seed)
        }
        Self.logger.notice("startup_recovery bundles scan_count=\(directories.count, privacy: .public)")

        let count = max(1, directories.count)
        for (index, bundleDir) in directories.enumerated() {
            let fraction = 0.2 + (0.38 * (Double(index) / Double(count)))
            let versionName = bundleDir.lastPathComponent
            emitStartupProgress(onProgress, detail: "Pruefe Bundle \(versionName)", fraction: fraction)
            Self.logger.notice("startup_recovery bundles candidate version=\(versionName, privacy: .public)")

            let manifestURL = bundleDir.appendingPathComponent("bundle-manifest.v3.json")
            let manifest = decodeManifestIfPresent(at: manifestURL)
            let dbFileName = manifest?.db.file ?? firstSQLiteFileName(in: bundleDir)
            guard let dbFileName else {
                Self.logger.error("startup_recovery bundles no_sqlite version=\(versionName, privacy: .public) removing_dir")
                try? removeItemIfExists(at: bundleDir)
                continue
            }
            let dbURL = bundleDir.appendingPathComponent(dbFileName)
            guard fileManager.fileExists(atPath: dbURL.path) else {
                Self.logger.error("startup_recovery bundles db_missing version=\(versionName, privacy: .public) db=\(dbFileName, privacy: .public)")
                try? removeItemIfExists(at: bundleDir)
                continue
            }

            do {
                try quickValidateDB(at: dbURL, runQuickCheck: false)
            } catch {
                Self.logger.error(
                    "startup_recovery bundles validation_failed version=\(versionName, privacy: .public) db=\(dbFileName, privacy: .public) error=\(String(describing: error), privacy: .public)"
                )
                try? removeItemIfExists(at: bundleDir)
                continue
            }
            Self.logger.notice("startup_recovery bundles validation_ok version=\(versionName, privacy: .public) db=\(dbFileName, privacy: .public)")

            let state = ActiveBundleState(
                region: manifest?.region ?? "DEU",
                bundleVersion: manifest?.bundleVersion ?? versionName,
                dbFileName: dbFileName,
                activatedAtUTC: nowUTC()
            )
            try writeActiveState(state)
            try? pruneInactiveBundles(keepingVersions: [state.bundleVersion, "seed"])
            Self.logger.notice("startup_recovery bundles activated version=\(state.bundleVersion, privacy: .public)")
            return BundleSyncResult(
                mode: .upToDate,
                bundleVersion: state.bundleVersion,
                dbPath: dbURL.path,
                details: "recovered local bundle"
            )
        }
        return nil
    }

    private func recoverFromStagingArtifacts(
        onProgress: (@Sendable (_ detail: String, _ fraction: Double) -> Void)?
    ) throws -> BundleSyncResult? {
        let stageDir = try stagingDirectory()
        let entries = try fileManager.contentsOfDirectory(
            at: stageDir,
            includingPropertiesForKeys: [.isRegularFileKey, .contentModificationDateKey],
            options: [.skipsHiddenFiles]
        )
        var sqliteCandidates = entries.filter { $0.pathExtension.lowercased() == "sqlite" }
        sqliteCandidates.sort {
            let lhsDate = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let rhsDate = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return lhsDate > rhsDate
        }
        Self.logger.notice("startup_recovery staging scan_count=\(sqliteCandidates.count, privacy: .public)")
        let count = max(1, sqliteCandidates.count)
        for (index, candidate) in sqliteCandidates.enumerated() {
            let fraction = 0.64 + (0.12 * (Double(index) / Double(count)))
            emitStartupProgress(onProgress, detail: "Validiere lokale Daten aus Staging", fraction: fraction)
            Self.logger.notice("startup_recovery staging candidate=\(candidate.lastPathComponent, privacy: .public)")
            do {
                try quickValidateDB(at: candidate, runQuickCheck: false)
                let recoveredVersion = parseVersionPrefix(fromStagingFileName: candidate.lastPathComponent)
                    ?? "recovered-\(startupRecoveryTimestamp())"
                Self.logger.notice(
                    "startup_recovery staging validation_ok candidate=\(candidate.lastPathComponent, privacy: .public) version=\(recoveredVersion, privacy: .public)"
                )
                return try activateRecoveredDatabase(
                    sourceDB: candidate,
                    bundleVersion: recoveredVersion,
                    region: "DEU",
                    dbFileName: "DEU-latest.speeds_v3.sqlite",
                    details: "activated recovered staging bundle"
                )
            } catch {
                Self.logger.error(
                    "startup_recovery staging validation_failed candidate=\(candidate.lastPathComponent, privacy: .public) error=\(String(describing: error), privacy: .public)"
                )
                try? removeSQLiteWithCompanions(at: candidate)
            }
        }
        return nil
    }

    private func recoverFromMultipartAssembledCache(
        onProgress: (@Sendable (_ detail: String, _ fraction: Double) -> Void)?
    ) throws -> BundleSyncResult? {
        let cacheDir = try multipartPartsCacheDirectory()
        let entries = try fileManager.contentsOfDirectory(
            at: cacheDir,
            includingPropertiesForKeys: [.isRegularFileKey, .contentModificationDateKey],
            options: [.skipsHiddenFiles]
        )
        var assembledCandidates = entries.filter { $0.lastPathComponent.hasSuffix(".assembled.sqlite") }
        assembledCandidates.sort {
            let lhsDate = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let rhsDate = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return lhsDate > rhsDate
        }
        Self.logger.notice("startup_recovery multipart_cache scan_count=\(assembledCandidates.count, privacy: .public)")
        let count = max(1, assembledCandidates.count)
        for (index, candidate) in assembledCandidates.enumerated() {
            let fraction = 0.8 + (0.1 * (Double(index) / Double(count)))
            emitStartupProgress(onProgress, detail: "Validiere zusammengesetzte Download-Datei", fraction: fraction)
            Self.logger.notice("startup_recovery multipart_cache candidate=\(candidate.lastPathComponent, privacy: .public)")
            do {
                try quickValidateDB(at: candidate, runQuickCheck: false)
                Self.logger.notice("startup_recovery multipart_cache validation_ok candidate=\(candidate.lastPathComponent, privacy: .public)")
                let result = try activateRecoveredDatabase(
                    sourceDB: candidate,
                    bundleVersion: "recovered-\(startupRecoveryTimestamp())",
                    region: "DEU",
                    dbFileName: "DEU-latest.speeds_v3.sqlite",
                    details: "activated recovered multipart cache"
                )
                let prefix = candidate.deletingPathExtension().deletingPathExtension().lastPathComponent
                let checkpoint = cacheDir.appendingPathComponent("\(prefix).checkpoint.json")
                try? removeItemIfExists(at: checkpoint)
                return result
            } catch {
                Self.logger.error(
                    "startup_recovery multipart_cache validation_failed candidate=\(candidate.lastPathComponent, privacy: .public) error=\(String(describing: error), privacy: .public)"
                )
                try? removeSQLiteWithCompanions(at: candidate)
                let prefix = candidate.deletingPathExtension().deletingPathExtension().lastPathComponent
                let checkpoint = cacheDir.appendingPathComponent("\(prefix).checkpoint.json")
                try? removeItemIfExists(at: checkpoint)
            }
        }
        return nil
    }

    private func activateRecoveredDatabase(
        sourceDB: URL,
        bundleVersion: String,
        region: String,
        dbFileName: String,
        details: String
    ) throws -> BundleSyncResult {
        let normalizedVersion = normalizeBundleVersion(bundleVersion)
        Self.logger.notice(
            "startup_recovery activate begin source=\(sourceDB.lastPathComponent, privacy: .public) version=\(normalizedVersion, privacy: .public)"
        )
        let bundleDir = try bundlesDir().appendingPathComponent(
            bundleDirectoryName(region: region, bundleVersion: normalizedVersion),
            isDirectory: true
        )
        if !fileManager.fileExists(atPath: bundleDir.path) {
            try fileManager.createDirectory(at: bundleDir, withIntermediateDirectories: true)
        }

        let finalDB = bundleDir.appendingPathComponent(dbFileName)
        if sourceDB.standardizedFileURL != finalDB.standardizedFileURL {
            let finalTmp = bundleDir.appendingPathComponent("\(dbFileName).recover.tmp")
            try? removeItemIfExists(at: finalTmp)
            for suffix in ["-wal", "-shm"] {
                let sourceCompanion = sqliteCompanionURL(for: sourceDB, suffix: suffix)
                let tmpCompanion = sqliteCompanionURL(for: finalTmp, suffix: suffix)
                try? removeItemIfExists(at: tmpCompanion)
                if fileManager.fileExists(atPath: sourceCompanion.path) {
                    try fileManager.moveItem(at: sourceCompanion, to: tmpCompanion)
                }
            }
            try fileManager.moveItem(at: sourceDB, to: finalTmp)
            if fileManager.fileExists(atPath: finalDB.path) {
                _ = try fileManager.replaceItemAt(finalDB, withItemAt: finalTmp)
            } else {
                try fileManager.moveItem(at: finalTmp, to: finalDB)
            }
            for suffix in ["-wal", "-shm"] {
                let finalCompanion = sqliteCompanionURL(for: finalDB, suffix: suffix)
                let tmpCompanion = sqliteCompanionURL(for: finalTmp, suffix: suffix)
                try? removeItemIfExists(at: finalCompanion)
                if fileManager.fileExists(atPath: tmpCompanion.path) {
                    try fileManager.moveItem(at: tmpCompanion, to: finalCompanion)
                }
            }
        }

        try writeActiveState(
            ActiveBundleState(
                region: region,
                bundleVersion: normalizedVersion,
                dbFileName: dbFileName,
                activatedAtUTC: nowUTC()
            )
        )
        try? pruneInactiveBundles(keepingVersions: [normalizedVersion, "seed"])
        Self.logger.notice(
            "startup_recovery activate success version=\(normalizedVersion, privacy: .public) db=\(finalDB.lastPathComponent, privacy: .public)"
        )

        return BundleSyncResult(
            mode: .bootstrap,
            bundleVersion: normalizedVersion,
            dbPath: finalDB.path,
            details: details
        )
    }

    private func emitStartupProgress(
        _ onProgress: (@Sendable (_ detail: String, _ fraction: Double) -> Void)?,
        detail: String,
        fraction: Double
    ) {
        guard let onProgress else {
            return
        }
        onProgress(detail, min(1, max(0, fraction)))
    }

    private func clearActiveState() throws {
        let stateURL = try stateFileURL()
        try? removeItemIfExists(at: stateURL)
    }

    private func decodeManifestIfPresent(at manifestURL: URL) -> V3BundleManifest? {
        guard fileManager.fileExists(atPath: manifestURL.path),
              let data = try? Data(contentsOf: manifestURL) else {
            return nil
        }
        return try? decoder.decode(V3BundleManifest.self, from: data)
    }

    private func firstSQLiteFileName(in directory: URL) -> String? {
        guard let entries = try? fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            return nil
        }
        let sqliteNames = entries
            .filter { $0.pathExtension.lowercased() == "sqlite" }
            .map(\.lastPathComponent)
            .sorted()
        return sqliteNames.first
    }

    private func loadCoverageEntriesIfNeeded(forceReload: Bool = false) throws -> [CoverageEntry] {
        let now = Date()
        if !forceReload,
           let updatedAt = coverageCacheUpdatedAt,
           now.timeIntervalSince(updatedAt) < coverageCacheTTLSeconds {
            return cachedCoverageEntries
        }

        let bundlesRoot = try bundlesDir()
        let bundleDirs = try fileManager.contentsOfDirectory(
            at: bundlesRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ).filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }

        var loaded: [CoverageEntry] = []
        for bundleDir in bundleDirs {
            let manifestURL = bundleDir.appendingPathComponent("bundle-manifest.v3.json")
            guard let manifest = decodeManifestIfPresent(at: manifestURL),
                  let coverage = manifest.coverage else {
                continue
            }
            let dbURL = bundleDir.appendingPathComponent(manifest.db.file)
            guard fileManager.fileExists(atPath: dbURL.path) else {
                continue
            }

            let rings: [CoverageRing]
            if let poly = coverage.poly {
                let polyURL = bundleDir.appendingPathComponent(poly.file)
                guard fileManager.fileExists(atPath: polyURL.path) else {
                    continue
                }
                rings = try parsePolyRings(at: polyURL)
            } else {
                rings = []
            }

            loaded.append(
                CoverageEntry(
                    region: manifest.region,
                    bundleVersion: manifest.bundleVersion,
                    countryCode: manifest.countryCode,
                    dbPath: dbURL.path,
                    bbox: coverage.bbox,
                    rings: rings
                )
            )
        }

        cachedCoverageEntries = loaded
        coverageCacheUpdatedAt = now
        return loaded
    }

    private func bboxArea(_ bbox: BundleCoverageBBox) -> Double {
        let width = max(0, bbox.maxLon - bbox.minLon)
        let height = max(0, bbox.maxLat - bbox.minLat)
        return width * height
    }

    private func pointIsInsideCoverage(lon: Double, lat: Double, entry: CoverageEntry) -> Bool {
        if lon < entry.bbox.minLon || lon > entry.bbox.maxLon || lat < entry.bbox.minLat || lat > entry.bbox.maxLat {
            return false
        }

        guard !entry.rings.isEmpty else {
            return true
        }

        var insideOuter = false
        for ring in entry.rings where !ring.isHole {
            if pointInRing(lon: lon, lat: lat, ring: ring.points) {
                insideOuter = true
                break
            }
        }
        guard insideOuter else {
            return false
        }
        for ring in entry.rings where ring.isHole {
            if pointInRing(lon: lon, lat: lat, ring: ring.points) {
                return false
            }
        }
        return true
    }

    private func parsePolyRings(at polyURL: URL) throws -> [CoverageRing] {
        let content = try String(contentsOf: polyURL, encoding: .utf8)
        let lines = content.split(whereSeparator: \.isNewline).map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
        guard !lines.isEmpty else {
            return []
        }

        var rings: [CoverageRing] = []
        var index = 1 // first line is polygon label
        while index < lines.count {
            let token = lines[index]
            index += 1
            if token.isEmpty {
                continue
            }
            if token.uppercased() == "END" {
                break
            }

            let isHole = token.hasPrefix("!")
            var points: [(lon: Double, lat: Double)] = []
            while index < lines.count {
                let pointLine = lines[index]
                index += 1
                if pointLine.isEmpty {
                    continue
                }
                if pointLine.uppercased() == "END" {
                    break
                }
                let comps = pointLine.split(whereSeparator: \.isWhitespace)
                if comps.count < 2 {
                    continue
                }
                guard let lon = Double(comps[0]), let lat = Double(comps[1]) else {
                    continue
                }
                points.append((lon: lon, lat: lat))
            }
            if points.count >= 3 {
                if points.first?.lon != points.last?.lon || points.first?.lat != points.last?.lat {
                    points.append(points[0])
                }
                if points.count >= 4 {
                    rings.append(CoverageRing(isHole: isHole, points: points))
                }
            }
        }
        return rings
    }

    private func pointInRing(lon: Double, lat: Double, ring: [(lon: Double, lat: Double)]) -> Bool {
        guard ring.count >= 4 else {
            return false
        }
        var inside = false
        for idx in 0..<(ring.count - 1) {
            let a = ring[idx]
            let b = ring[idx + 1]
            if pointOnSegment(lon: lon, lat: lat, a: a, b: b) {
                return true
            }
            let intersects = ((a.lat > lat) != (b.lat > lat)) &&
                (lon < (b.lon - a.lon) * (lat - a.lat) / ((b.lat - a.lat) != 0 ? (b.lat - a.lat) : 1e-30) + a.lon)
            if intersects {
                inside.toggle()
            }
        }
        return inside
    }

    private func pointOnSegment(
        lon: Double,
        lat: Double,
        a: (lon: Double, lat: Double),
        b: (lon: Double, lat: Double),
        eps: Double = 1e-12
    ) -> Bool {
        let cross = (lon - a.lon) * (b.lat - a.lat) - (lat - a.lat) * (b.lon - a.lon)
        if abs(cross) > eps {
            return false
        }
        let dot = (lon - a.lon) * (b.lon - a.lon) + (lat - a.lat) * (b.lat - a.lat)
        if dot < -eps {
            return false
        }
        let sqLen = (b.lon - a.lon) * (b.lon - a.lon) + (b.lat - a.lat) * (b.lat - a.lat)
        return dot - sqLen <= eps
    }

    private func hasAnyLocalRecoveryArtifacts() throws -> Bool {
        let bundlesRoot = try bundlesDir()
        let bundleEntries = try fileManager.contentsOfDirectory(
            at: bundlesRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        let hasDownloadedBundle = bundleEntries.contains { entry in
            guard entry.lastPathComponent != "seed" else {
                return false
            }
            return (try? entry.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        }
        if hasDownloadedBundle {
            return true
        }

        let stageDir = try stagingDirectory()
        let stageEntries = try fileManager.contentsOfDirectory(
            at: stageDir,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        )
        if !stageEntries.isEmpty {
            return true
        }

        let cacheDir = try multipartPartsCacheDirectory()
        let cacheEntries = try fileManager.contentsOfDirectory(
            at: cacheDir,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        )
        return !cacheEntries.isEmpty
    }

    private func parseVersionPrefix(fromStagingFileName fileName: String) -> String? {
        let parts = fileName.split(separator: "-")
        guard parts.count >= 3 else {
            return nil
        }
        let candidate = "\(parts[0])-\(parts[1])-\(parts[2])"
        return parseDayVersion(candidate) != nil ? candidate : nil
    }

    private func startupRecoveryTimestamp() -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMddHHmmss"
        return formatter.string(from: Date())
    }

    private func normalizeBundleVersion(_ value: String) -> String {
        let cleaned = value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
        let allowed = Set("abcdefghijklmnopqrstuvwxyz0123456789-_.")
        let filtered = cleaned.map { allowed.contains($0) ? $0 : "-" }
        let joined = String(filtered).trimmingCharacters(in: CharacterSet(charactersIn: "-_."))
        return joined.isEmpty ? "recovered-\(startupRecoveryTimestamp())" : joined
    }

    private func removeSQLiteWithCompanions(at dbURL: URL) throws {
        try? removeItemIfExists(at: dbURL)
        for suffix in ["-wal", "-shm"] {
            try? removeItemIfExists(at: sqliteCompanionURL(for: dbURL, suffix: suffix))
        }
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
        coverageCacheUpdatedAt = nil
        cachedCoverageEntries = []
    }

    private func stagingDirectory() throws -> URL {
        let stageDir = try rootDir().appendingPathComponent("staging", isDirectory: true)
        if !fileManager.fileExists(atPath: stageDir.path) {
            try fileManager.createDirectory(at: stageDir, withIntermediateDirectories: true)
        }
        return stageDir
    }

    private func multipartPartsCacheDirectory() throws -> URL {
        let cacheDir = try rootDir().appendingPathComponent("multipart-cache", isDirectory: true)
        if !fileManager.fileExists(atPath: cacheDir.path) {
            try fileManager.createDirectory(at: cacheDir, withIntermediateDirectories: true)
        }
        return cacheDir
    }

    private func multipartAssembledCacheIdentity(manifest: V3BundleManifest, sortedParts: [BundleArtifact]) -> String {
        var identity = "\(manifest.bundleVersion)|\(manifest.db.file)|\(manifest.db.sha256)|\(manifest.db.bytes)"
        for part in sortedParts {
            identity.append("|\(part.file)|\(part.sha256)|\(part.bytes)")
        }
        return identity
    }

    private func multipartAssembledCacheFileURL(manifest: V3BundleManifest, sortedParts: [BundleArtifact]) throws -> URL {
        let identity = multipartAssembledCacheIdentity(manifest: manifest, sortedParts: sortedParts)
        let digest = SHA256.hash(data: Data(identity.utf8))
        let key = digest.map { String(format: "%02x", $0) }.joined()
        return try multipartPartsCacheDirectory().appendingPathComponent("\(key).assembled.sqlite")
    }

    private func multipartAssembleCheckpointFileURL(manifest: V3BundleManifest, sortedParts: [BundleArtifact]) throws -> URL {
        let identity = multipartAssembledCacheIdentity(manifest: manifest, sortedParts: sortedParts)
        let digest = SHA256.hash(data: Data(identity.utf8))
        let key = digest.map { String(format: "%02x", $0) }.joined()
        return try multipartPartsCacheDirectory().appendingPathComponent("\(key).checkpoint.json")
    }

    private func isReusableCachedArtifact(
        _ url: URL,
        expectedBytes: Int64,
        expectedSHA256: String,
        preserveOnMismatch: Bool = false
    ) throws -> Bool {
        guard fileManager.fileExists(atPath: url.path) else {
            return false
        }
        guard try fileSize(url) == expectedBytes else {
            if !preserveOnMismatch {
                try? removeItemIfExists(at: url)
            }
            return false
        }
        do {
            try validateSHA256(fileAt: url, expectedHex: expectedSHA256, label: "bundle db cached artifact")
            return true
        } catch {
            if !preserveOnMismatch {
                try? removeItemIfExists(at: url)
            }
            return false
        }
    }

    private func writeStagingDB(downloadedFile: URL, version: String) throws -> URL {
        let stageDir = try stagingDirectory()
        let fileURL = stageDir.appendingPathComponent("\(version)-\(UUID().uuidString).sqlite")
        try fileManager.moveItem(at: downloadedFile, to: fileURL)
        return fileURL
    }

    private func stageCopyOfActiveDB(forVersion version: String) throws -> URL {
        guard let current = try activeDatabaseURL(), fileManager.fileExists(atPath: current.path) else {
            throw ConsumerAppError.io("No active DB for delta patch")
        }
        let stageDir = try stagingDirectory()
        let out = stageDir.appendingPathComponent("\(version)-delta-\(UUID().uuidString).sqlite")
        try fileManager.copyItem(at: current, to: out)
        return out
    }

    private func writeMultipartStagingDB(
        parts: [BundleArtifact],
        manifest: V3BundleManifest,
        manifestURL: URL,
        onProgress: (@Sendable (BundleSyncProgress) -> Void)?
    ) async throws -> URL {
        let sortedParts = parts.sorted { $0.file < $1.file }
        if sortedParts.isEmpty {
            throw ConsumerAppError.invalidManifest("db_parts is empty")
        }

        let declaredTotalBytes = manifest.db.bytes
        let assembledOut = try multipartAssembledCacheFileURL(manifest: manifest, sortedParts: sortedParts)
        let checkpointURL = try multipartAssembleCheckpointFileURL(manifest: manifest, sortedParts: sortedParts)
        if try isReusableCachedArtifact(
            assembledOut,
            expectedBytes: declaredTotalBytes,
            expectedSHA256: manifest.db.sha256,
            preserveOnMismatch: true
        ) {
            try? removeItemIfExists(at: checkpointURL)
            emitProgress(
                onProgress,
                stage: .assembling,
                detail: "Reusing cached assembled database",
                completedBytes: declaredTotalBytes,
                totalBytes: declaredTotalBytes
            )
            return assembledOut
        }

        if !fileManager.fileExists(atPath: assembledOut.path) {
            fileManager.createFile(atPath: assembledOut.path, contents: nil)
        }

        var totalBytes: Int64 = 0
        var nextPartIndex = 0
        if let checkpoint = try? loadMultipartAssembleCheckpoint(at: checkpointURL) {
            let expectedPrefixBytes = expectedMultipartPrefixBytes(parts: sortedParts, upToPartIndex: checkpoint.nextPartIndex)
            let existingBytes = (try? fileSize(assembledOut)) ?? 0
            if checkpoint.nextPartIndex >= 0,
               checkpoint.nextPartIndex <= sortedParts.count,
               checkpoint.assembledBytes == expectedPrefixBytes,
               existingBytes >= expectedPrefixBytes {
                nextPartIndex = checkpoint.nextPartIndex
                totalBytes = expectedPrefixBytes
            } else {
                try resetMultipartAssemblyState(assembledOut: assembledOut, checkpointURL: checkpointURL)
            }
        } else if ((try? fileSize(assembledOut)) ?? 0) > 0 {
            // Partial file without checkpoint is ambiguous; reset to keep recovery deterministic.
            try resetMultipartAssemblyState(assembledOut: assembledOut, checkpointURL: checkpointURL)
        }

        let outHandle = try FileHandle(forWritingTo: assembledOut)
        defer {
            try? outHandle.close()
        }
        try outHandle.truncate(atOffset: UInt64(max(0, totalBytes)))
        try outHandle.seekToEnd()

        if nextPartIndex > 0 {
            emitMultipartSequentialProgress(
                onProgress: onProgress,
                detail: "Resuming multipart assembly at part \(nextPartIndex + 1)/\(sortedParts.count)",
                parts: sortedParts,
                completedPartCount: nextPartIndex,
                activePartIndex: nil,
                activePartCompletedBytes: 0,
                completedBytes: totalBytes,
                totalBytes: declaredTotalBytes,
                stage: .assembling
            )
        }

        for index in nextPartIndex..<sortedParts.count {
            let part = sortedParts[index]
            let partURL = try resolveArtifactURL(part, relativeTo: manifestURL)
            let partLabel = "Part \(index + 1)/\(sortedParts.count): \(part.file)"
            let partStart = totalBytes

            emitMultipartSequentialProgress(
                onProgress: onProgress,
                detail: "Downloading \(partLabel)",
                parts: sortedParts,
                completedPartCount: index,
                activePartIndex: index,
                activePartCompletedBytes: 0,
                completedBytes: partStart,
                totalBytes: declaredTotalBytes,
                stage: .downloading
            )

            do {
                let partBytes = try await downloadAndAppendMultipartPart(
                    part: part,
                    partURL: partURL,
                    outHandle: outHandle
                ) { completedBytesInPart in
                    let overallCompleted = min(declaredTotalBytes, partStart + completedBytesInPart)
                    self.emitMultipartSequentialProgress(
                        onProgress: onProgress,
                        detail: "Downloading \(partLabel)",
                        parts: sortedParts,
                        completedPartCount: index,
                        activePartIndex: index,
                        activePartCompletedBytes: completedBytesInPart,
                        completedBytes: overallCompleted,
                        totalBytes: declaredTotalBytes,
                        stage: .downloading
                    )
                }
                totalBytes = partStart + partBytes
            } catch {
                // Roll back the partial part so restart can continue from last fully completed part.
                try outHandle.truncate(atOffset: UInt64(max(0, partStart)))
                try outHandle.seekToEnd()
                totalBytes = partStart
                throw error
            }

            try saveMultipartAssembleCheckpoint(
                MultipartAssembleCheckpoint(nextPartIndex: index + 1, assembledBytes: totalBytes),
                to: checkpointURL
            )
            emitMultipartSequentialProgress(
                onProgress: onProgress,
                detail: "Assembled \(index + 1)/\(sortedParts.count) parts",
                parts: sortedParts,
                completedPartCount: index + 1,
                activePartIndex: nil,
                activePartCompletedBytes: 0,
                completedBytes: totalBytes,
                totalBytes: declaredTotalBytes,
                stage: .assembling
            )
        }

        if totalBytes != declaredTotalBytes {
            throw ConsumerAppError.invalidManifest(
                "db_parts size mismatch: expected \(declaredTotalBytes), got \(totalBytes)"
            )
        }
        do {
            try validateSHA256(fileAt: assembledOut, expectedHex: manifest.db.sha256, label: "bundle db (assembled)")
            try? removeItemIfExists(at: checkpointURL)
            return assembledOut
        } catch {
            try? removeItemIfExists(at: assembledOut)
            try? removeItemIfExists(at: checkpointURL)
            throw error
        }
    }

    private func loadMultipartAssembleCheckpoint(at url: URL) throws -> MultipartAssembleCheckpoint? {
        guard fileManager.fileExists(atPath: url.path) else {
            return nil
        }
        let data = try Data(contentsOf: url)
        return try decoder.decode(MultipartAssembleCheckpoint.self, from: data)
    }

    private func saveMultipartAssembleCheckpoint(_ checkpoint: MultipartAssembleCheckpoint, to url: URL) throws {
        let data = try JSONEncoder().encode(checkpoint)
        try data.write(to: url, options: .atomic)
    }

    private func expectedMultipartPrefixBytes(parts: [BundleArtifact], upToPartIndex: Int) -> Int64 {
        guard upToPartIndex > 0 else {
            return 0
        }
        let upperBound = min(upToPartIndex, parts.count)
        var sum: Int64 = 0
        for index in 0..<upperBound {
            let next = max(0, parts[index].bytes)
            if sum > Int64.max - next {
                return Int64.max
            }
            sum += next
        }
        return sum
    }

    private func resetMultipartAssemblyState(assembledOut: URL, checkpointURL: URL) throws {
        try? removeItemIfExists(at: checkpointURL)
        try? removeItemIfExists(at: assembledOut)
        fileManager.createFile(atPath: assembledOut.path, contents: nil)
    }

    private nonisolated func emitMultipartSequentialProgress(
        onProgress: (@Sendable (BundleSyncProgress) -> Void)?,
        detail: String,
        parts: [BundleArtifact],
        completedPartCount: Int,
        activePartIndex: Int?,
        activePartCompletedBytes: Int64,
        completedBytes: Int64,
        totalBytes: Int64,
        stage: BundleSyncProgress.Stage
    ) {
        guard let onProgress else {
            return
        }
        let partDownloads = parts.enumerated().map { index, part in
            let label = "Part \(index + 1)/\(parts.count): \(part.file)"
            let total = max(0, part.bytes)
            if index < completedPartCount {
                return PartDownloadProgress(
                    id: part.file,
                    detail: "\(label) [completed]",
                    completedBytes: total,
                    totalBytes: total
                )
            }
            if activePartIndex == index {
                return PartDownloadProgress(
                    id: part.file,
                    detail: "\(label) [downloading]",
                    completedBytes: min(max(0, activePartCompletedBytes), total),
                    totalBytes: total
                )
            }
            return PartDownloadProgress(
                id: part.file,
                detail: "\(label) [waiting]",
                completedBytes: 0,
                totalBytes: total
            )
        }
        onProgress(
            BundleSyncProgress(
                stage: stage,
                detail: detail,
                completedBytes: max(0, min(completedBytes, totalBytes)),
                totalBytes: max(0, totalBytes),
                partDownloads: partDownloads
            )
        )
    }

    private func downloadAndAppendMultipartPart(
        part: BundleArtifact,
        partURL: URL,
        outHandle: FileHandle,
        onProgress: @escaping @Sendable (_ completedBytesInPart: Int64) -> Void
    ) async throws -> Int64 {
        let resolvedURL = try await resolveGitHubReleaseAssetAPIURLIfNeeded(partURL)
        let request = makeRequest(url: resolvedURL)
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw ConsumerAppError.network("Unexpected non-HTTP response for \(partURL.absoluteString)")
        }
        guard (200...299).contains(http.statusCode) else {
            throw ConsumerAppError.network("Unexpected HTTP response status=\(http.statusCode) url=\(response.url?.absoluteString ?? partURL.absoluteString)")
        }

        var hasher = SHA256()
        var downloadedBytes: Int64 = 0
        var buffer = Data()
        buffer.reserveCapacity(256 * 1024)
        var lastProgressAt = Date.distantPast
        var lastProgressBytes: Int64 = -1

        func emitProgress(force: Bool) {
            let now = Date()
            if !force {
                let elapsed = now.timeIntervalSince(lastProgressAt)
                let byteDelta = downloadedBytes - lastProgressBytes
                if elapsed < 0.25 && byteDelta < (2 * 1024 * 1024) {
                    return
                }
            }
            lastProgressAt = now
            lastProgressBytes = downloadedBytes
            onProgress(downloadedBytes)
        }

        for try await byte in bytes {
            buffer.append(byte)
            if buffer.count >= 256 * 1024 {
                try outHandle.write(contentsOf: buffer)
                hasher.update(data: buffer)
                downloadedBytes += Int64(buffer.count)
                buffer.removeAll(keepingCapacity: true)
                emitProgress(force: false)
            }
        }
        if !buffer.isEmpty {
            try outHandle.write(contentsOf: buffer)
            hasher.update(data: buffer)
            downloadedBytes += Int64(buffer.count)
            buffer.removeAll(keepingCapacity: true)
        }
        emitProgress(force: true)

        if downloadedBytes != part.bytes {
            throw ConsumerAppError.invalidManifest(
                "db part size mismatch for \(part.file): expected \(part.bytes), got \(downloadedBytes)"
            )
        }

        let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        if digest != part.sha256.lowercased() {
            throw ConsumerAppError.checksum("Checksum mismatch for bundle db part \(part.file)")
        }
        return downloadedBytes
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
        let resolvedURL = try await resolveGitHubReleaseAssetAPIURLIfNeeded(url)
        let request = makeRequest(url: resolvedURL)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw ConsumerAppError.network("Unexpected non-HTTP response for \(url.absoluteString)")
        }
        guard (200...299).contains(http.statusCode) else {
            throw ConsumerAppError.network(httpErrorMessage(requestURL: url, response: http, bodyPreviewData: data))
        }
        return data
    }

    private func downloadFile(
        from url: URL,
        onProgress: (@Sendable (_ completedBytes: Int64, _ totalBytes: Int64?) -> Void)? = nil
    ) async throws -> URL {
        let resolvedURL = try await resolveGitHubReleaseAssetAPIURLIfNeeded(url)
        let request = makeRequest(url: resolvedURL)
        let (tmpURL, response): (URL, URLResponse)
        if shouldUseBackgroundDownloadTransport() {
            (tmpURL, response) = try await BackgroundDownloadCenter.shared.download(
                request: request,
                requestURL: url,
                onProgress: onProgress
            )
        } else {
            (tmpURL, response) = try await downloadFileViaCurrentSession(
                request: request,
                requestURL: url,
                onProgress: onProgress
            )
        }
        guard let http = response as? HTTPURLResponse else {
            try? removeItemIfExists(at: tmpURL)
            throw ConsumerAppError.network("Unexpected non-HTTP response for \(url.absoluteString)")
        }
        guard (200...299).contains(http.statusCode) else {
            let previewData = try? Data(contentsOf: tmpURL)
            try? removeItemIfExists(at: tmpURL)
            throw ConsumerAppError.network(
                httpErrorMessage(
                    requestURL: url,
                    response: http,
                    bodyPreviewData: previewData
                )
            )
        }
        if let onProgress {
            let finalSize = (try? fileSize(tmpURL)) ?? 0
            let total = http.expectedContentLength > 0 ? http.expectedContentLength : nil
            onProgress(finalSize, total)
        }
        return tmpURL
    }

    private func shouldUseBackgroundDownloadTransport() -> Bool {
        let protocolClasses = session.configuration.protocolClasses ?? []
        return protocolClasses.isEmpty
    }

    private func downloadFileViaCurrentSession(
        request: URLRequest,
        requestURL: URL,
        onProgress: (@Sendable (_ completedBytes: Int64, _ totalBytes: Int64?) -> Void)? = nil
    ) async throws -> (URL, URLResponse) {
        let tempRoot = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
        var observation: NSKeyValueObservation?
        var progressPoller: Task<Void, Never>?
        defer {
            observation?.invalidate()
            progressPoller?.cancel()
        }

        return try await withCheckedThrowingContinuation { continuation in
            let task = session.downloadTask(with: request) { tmpURL, response, error in
                progressPoller?.cancel()
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let tmpURL, let response else {
                    continuation.resume(throwing: ConsumerAppError.network("Empty download response for \(requestURL.absoluteString)"))
                    return
                }
                let retainedURL = tempRoot.appendingPathComponent("download-\(UUID().uuidString).tmp")
                do {
                    if FileManager.default.fileExists(atPath: retainedURL.path) {
                        try FileManager.default.removeItem(at: retainedURL)
                    }
                    try FileManager.default.moveItem(at: tmpURL, to: retainedURL)
                    continuation.resume(returning: (retainedURL, response))
                } catch {
                    continuation.resume(throwing: error)
                }
            }

            if let onProgress {
                observation = task.progress.observe(\.completedUnitCount, options: [.initial, .new]) { progress, _ in
                    let totalUnitCount = progress.totalUnitCount
                    let totalBytes: Int64? = totalUnitCount > 0 ? totalUnitCount : nil
                    onProgress(progress.completedUnitCount, totalBytes)
                }
                progressPoller = Task.detached(priority: .utility) { [weak task] in
                    guard let task else {
                        return
                    }
                    while !Task.isCancelled {
                        let expected = task.countOfBytesExpectedToReceive
                        let totalBytes: Int64? = expected > 0 ? expected : nil
                        let completed = max(0, task.countOfBytesReceived)
                        onProgress(completed, totalBytes)
                        if task.state == .completed || task.state == .canceling {
                            break
                        }
                        try? await Task.sleep(nanoseconds: 250_000_000)
                    }
                }
            }
            task.resume()
        }
    }

    private func emitProgress(
        _ onProgress: (@Sendable (BundleSyncProgress) -> Void)?,
        stage: BundleSyncProgress.Stage,
        detail: String,
        completedBytes: Int64,
        totalBytes: Int64,
        partDownloads: [PartDownloadProgress] = []
    ) {
        guard let onProgress else {
            return
        }
        onProgress(
            BundleSyncProgress(
                stage: stage,
                detail: detail,
                completedBytes: max(0, completedBytes),
                totalBytes: max(0, totalBytes),
                partDownloads: partDownloads
            )
        )
    }

    private func resolveGitHubReleaseAssetAPIURLIfNeeded(_ url: URL) async throws -> URL {
        guard githubToken != nil,
              let releaseAsset = parseGitHubReleaseAssetURL(url) else {
            return url
        }

        let originalKey = url.absoluteString
        if let cached = githubAssetURLByReleaseURL[originalKey] {
            return cached
        }

        let tagAssets: [String: Int64]
        do {
            tagAssets = try await fetchGitHubReleaseAssets(
                owner: releaseAsset.owner,
                repo: releaseAsset.repo,
                tag: releaseAsset.tag
            )
        } catch {
            return url
        }
        guard let assetID = tagAssets[releaseAsset.assetName] else {
            return url
        }
        guard let apiURL = URL(
            string: "https://api.github.com/repos/\(releaseAsset.owner)/\(releaseAsset.repo)/releases/assets/\(assetID)"
        ) else {
            return url
        }
        githubAssetURLByReleaseURL[originalKey] = apiURL
        return apiURL
    }

    private func fetchGitHubReleaseAssets(owner: String, repo: String, tag: String) async throws -> [String: Int64] {
        let key = "\(owner)/\(repo)/\(tag)"
        if let cached = githubReleaseAssetsByTagKey[key] {
            return cached
        }
        guard let token = githubToken else {
            throw ConsumerAppError.network("Missing GitHub token for private release download")
        }
        guard let url = URL(string: "https://api.github.com/repos/\(owner)/\(repo)/releases/tags/\(tag)") else {
            throw ConsumerAppError.invalidManifest("Unable to build GitHub release tag API URL")
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 120
        request.setValue("YouSpeedConsumer/1.0", forHTTPHeaderField: "User-Agent")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw ConsumerAppError.network("Unexpected non-HTTP response for \(url.absoluteString)")
        }
        guard (200...299).contains(http.statusCode) else {
            throw ConsumerAppError.network(httpErrorMessage(requestURL: url, response: http, bodyPreviewData: data))
        }

        let release: GitHubReleaseTagResponse
        do {
            release = try decoder.decode(GitHubReleaseTagResponse.self, from: data)
        } catch {
            throw ConsumerAppError.invalidManifest("Unable to decode GitHub release metadata for tag \(tag)")
        }
        let mapping = Dictionary(uniqueKeysWithValues: release.assets.map { ($0.name, $0.id) })
        githubReleaseAssetsByTagKey[key] = mapping
        return mapping
    }

    private func parseGitHubReleaseAssetURL(_ url: URL) -> GitHubReleaseAssetPath? {
        guard let host = url.host?.lowercased(),
              host == "github.com" || host == "www.github.com" else {
            return nil
        }
        let parts = url.path.split(separator: "/", omittingEmptySubsequences: true)
        guard parts.count >= 6,
              parts[2] == "releases",
              parts[3] == "download" else {
            return nil
        }

        let owner = String(parts[0])
        let repo = String(parts[1])
        let tag = String(parts[4])
        let assetName = parts[5...].joined(separator: "/")
        guard !owner.isEmpty, !repo.isEmpty, !tag.isEmpty, !assetName.isEmpty else {
            return nil
        }
        return GitHubReleaseAssetPath(owner: owner, repo: repo, tag: tag, assetName: assetName)
    }

    private func makeRequest(url: URL) -> URLRequest {
        var request = URLRequest(url: url)
        request.timeoutInterval = 120
        request.setValue("YouSpeedConsumer/1.0", forHTTPHeaderField: "User-Agent")
        if let token = githubToken,
           let host = url.host?.lowercased(),
           host == "api.github.com" || host.contains("github.com") || host.contains("githubusercontent.com") {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            request.setValue("application/octet-stream", forHTTPHeaderField: "Accept")
        }
        return request
    }

    private func httpErrorMessage(
        requestURL: URL,
        response: HTTPURLResponse,
        bodyPreviewData: Data?
    ) -> String {
        let finalURL = response.url?.absoluteString ?? requestURL.absoluteString
        let status = response.statusCode
        let contentType = response.value(forHTTPHeaderField: "Content-Type") ?? "unknown"

        var bodyPreview = ""
        if let bodyPreviewData, !bodyPreviewData.isEmpty {
            let head = bodyPreviewData.prefix(384)
            if var text = String(data: head, encoding: .utf8) {
                text = text.replacingOccurrences(of: "\n", with: " ")
                text = text.replacingOccurrences(of: "\r", with: " ")
                bodyPreview = " body_preview=\"\(text)\""
            } else {
                bodyPreview = " body_preview=<non-utf8 \(head.count)b>"
            }
        }

        let host = response.url?.host?.lowercased() ?? requestURL.host?.lowercased() ?? ""
        let githubPrivateHint: String
        if (status == 403 || status == 404), (host.contains("github.com") || host.contains("githubusercontent.com")) {
            githubPrivateHint = " hint=\"GitHub asset may be private or inaccessible without auth\""
        } else {
            githubPrivateHint = ""
        }

        return "Unexpected HTTP response status=\(status) url=\(finalURL) content_type=\(contentType)\(bodyPreview)\(githubPrivateHint)"
    }

    private func validateSHA256(data: Data, expectedHex: String, label: String) throws {
        let digest = SHA256.hash(data: data)
        let actual = digest.map { String(format: "%02x", $0) }.joined()
        if actual != expectedHex.lowercased() {
            throw ConsumerAppError.checksum("Checksum mismatch for \(label)")
        }
    }

    private func validateSHA256(fileAt url: URL, expectedHex: String, label: String) throws {
        let inHandle = try FileHandle(forReadingFrom: url)
        defer {
            try? inHandle.close()
        }

        var hasher = SHA256()
        while true {
            let chunk = inHandle.readData(ofLength: 8 * 1024 * 1024)
            if chunk.isEmpty {
                break
            }
            hasher.update(data: chunk)
        }
        let digest = hasher.finalize()
        let actual = digest.map { String(format: "%02x", $0) }.joined()
        if actual != expectedHex.lowercased() {
            throw ConsumerAppError.checksum("Checksum mismatch for \(label)")
        }
    }

    private func fileSize(_ url: URL) throws -> Int64 {
        let attrs = try fileManager.attributesOfItem(atPath: url.path)
        let sizeNum = attrs[.size] as? NSNumber
        return sizeNum?.int64Value ?? 0
    }

    private func removeItemIfExists(at url: URL) throws {
        if fileManager.fileExists(atPath: url.path) {
            try fileManager.removeItem(at: url)
        }
    }

    private func sqliteCompanionURL(for dbURL: URL, suffix: String) -> URL {
        URL(fileURLWithPath: dbURL.path + suffix)
    }

    private func cleanupStagingArtifacts() throws {
        let stageDir = try stagingDirectory()
        let entries = try fileManager.contentsOfDirectory(
            at: stageDir,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )
        if !entries.isEmpty {
            Self.logger.notice("startup_recovery cleanup staging count=\(entries.count, privacy: .public)")
        }
        for entry in entries {
            try? removeItemIfExists(at: entry)
        }
    }

    private func cleanupMultipartCacheArtifacts(removeAll: Bool) throws {
        let cacheDir = try multipartPartsCacheDirectory()
        let entries = try fileManager.contentsOfDirectory(
            at: cacheDir,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )
        if !entries.isEmpty {
            Self.logger.notice(
                "startup_recovery cleanup multipart_cache count=\(entries.count, privacy: .public) remove_all=\(removeAll, privacy: .public)"
            )
        }
        for entry in entries {
            if removeAll || entry.pathExtension.lowercased() == "json" {
                try? removeItemIfExists(at: entry)
            }
        }
    }

    private func pruneInactiveBundles(keepingVersions: Set<String>) throws {
        _ = keepingVersions
        let bundlesRoot = try bundlesDir()
        let entries = try fileManager.contentsOfDirectory(
            at: bundlesRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        for entry in entries {
            let values = try? entry.resourceValues(forKeys: [.isDirectoryKey])
            guard values?.isDirectory == true else {
                continue
            }
            if entry.lastPathComponent == "seed" {
                continue
            }
            let manifestURL = entry.appendingPathComponent("bundle-manifest.v3.json")
            if fileManager.fileExists(atPath: manifestURL.path) {
                continue
            }
            if firstSQLiteFileName(in: entry) != nil {
                continue
            }
            try? removeItemIfExists(at: entry)
        }
    }

    private func ensureSufficientDiskSpace(requiredBytes: Int64, reason: String) throws {
        guard requiredBytes > 0 else {
            return
        }
        guard let availableBytes = availableDiskSpaceBytes() else {
            return
        }
        let minimumRequired = requiredBytes > Int64.max - minimumFreeDiskReserveBytes
            ? Int64.max
            : requiredBytes + minimumFreeDiskReserveBytes
        guard availableBytes >= minimumRequired else {
            throw ConsumerAppError.io(
                "Insufficient free disk space for \(reason). Required at least \(byteCountString(minimumRequired)), available \(byteCountString(availableBytes))."
            )
        }
    }

    private func availableDiskSpaceBytes() -> Int64? {
        do {
            let root = try rootDir()
            let values = try root.resourceValues(forKeys: [
                .volumeAvailableCapacityForImportantUsageKey,
                .volumeAvailableCapacityForOpportunisticUsageKey,
                .volumeAvailableCapacityKey,
            ])
            if let important = values.volumeAvailableCapacityForImportantUsage {
                return important
            }
            if let opportunistic = values.volumeAvailableCapacityForOpportunisticUsage {
                return opportunistic
            }
            if let available = values.volumeAvailableCapacity {
                return Int64(available)
            }
            return nil
        } catch {
            return nil
        }
    }

    private func byteCountString(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }

    private func quickValidateDB(at url: URL, runQuickCheck: Bool = true) throws {
        var db: OpaquePointer?
        let encodedPath = url.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? url.path
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
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
                let msg = String(cString: sqlite3_errmsg(db))
                throw ConsumerAppError.sqlite("prepare failed for schema check: \(msg)")
            }
            defer { sqlite3_finalize(stmt) }
            if sqlite3_step(stmt) != SQLITE_ROW {
                throw ConsumerAppError.sqlite("missing table in v3 db: \(table)")
            }
        }

        guard runQuickCheck else {
            return
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

private struct GitHubReleaseAssetPath {
    let owner: String
    let repo: String
    let tag: String
    let assetName: String
}

private struct GitHubReleaseTagResponse: Decodable {
    let assets: [GitHubReleaseAssetEntry]
}

private struct GitHubReleaseAssetEntry: Decodable {
    let id: Int64
    let name: String
}

private struct MultipartAssembleCheckpoint: Codable, Sendable {
    let nextPartIndex: Int
    let assembledBytes: Int64
}

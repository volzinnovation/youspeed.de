import CryptoKit
import Foundation
import SQLite3

actor V3BundleManager {
    private let fileManager: FileManager
    private let session: URLSession
    private let decoder: JSONDecoder
    private let minimumFreeDiskReserveBytes: Int64 = 256 * 1024 * 1024
    private var githubToken: String?
    private var githubAssetURLByReleaseURL: [String: URL] = [:]
    private var githubReleaseAssetsByTagKey: [String: [String: Int64]] = [:]

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
                if state.bundleVersion == "seed",
                   let bundledSeed = bundle.url(forResource: resourceName, withExtension: "sqlite"),
                   let existingBytes = try? fileSize(dbURL),
                   let bundledBytes = try? fileSize(bundledSeed),
                   existingBytes != bundledBytes {
                    if bundledBytes > 0 {
                        try ensureSufficientDiskSpace(requiredBytes: bundledBytes, reason: "seed database refresh")
                    }
                    let tmp = dbURL.deletingLastPathComponent().appendingPathComponent("\(state.dbFileName).refresh.tmp")
                    try? removeItemIfExists(at: tmp)
                    try fileManager.copyItem(at: bundledSeed, to: tmp)
                    if fileManager.fileExists(atPath: dbURL.path) {
                        _ = try fileManager.replaceItemAt(dbURL, withItemAt: tmp)
                    } else {
                        try fileManager.moveItem(at: tmp, to: dbURL)
                    }
                    return BundleSyncResult(mode: .bootstrap, bundleVersion: state.bundleVersion, dbPath: dbURL.path, details: "seed bundle refreshed")
                }
                return BundleSyncResult(mode: .upToDate, bundleVersion: state.bundleVersion, dbPath: dbURL.path, details: "existing active bundle")
            }
        }

        guard let source = bundle.url(forResource: resourceName, withExtension: "sqlite") else {
            throw ConsumerAppError.io("Missing bundled seed DB resource: \(resourceName).sqlite")
        }
        let seedBytes = (try? fileSize(source)) ?? 0
        if seedBytes > 0 {
            try ensureSufficientDiskSpace(requiredBytes: seedBytes, reason: "seed database")
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

    func syncFromManifestURL(
        _ manifestURL: URL,
        onProgress: (@Sendable (BundleSyncProgress) -> Void)? = nil
    ) async throws -> BundleSyncResult {
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
            return fullDownload
        } catch {
            try? cleanupStagingArtifacts()
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
                detail: "Validating downloaded database",
                completedBytes: manifest.db.bytes,
                totalBytes: manifest.db.bytes
            )
            try quickValidateDB(at: stagingDB)
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
        let bundleDir = try bundlesDir().appendingPathComponent(manifest.bundleVersion, isDirectory: true)
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
        for entry in entries {
            try? removeItemIfExists(at: entry)
        }
    }

    private func pruneInactiveBundles(keepingVersions: Set<String>) throws {
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
            guard !keepingVersions.contains(entry.lastPathComponent) else {
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

    private func quickValidateDB(at url: URL) throws {
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

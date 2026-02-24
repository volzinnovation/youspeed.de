import CryptoKit
import Foundation
import SQLite3

actor V3BundleManager {
    private let fileManager: FileManager
    private let session: URLSession
    private let decoder: JSONDecoder
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

    func syncFromManifestURL(
        _ manifestURL: URL,
        onProgress: (@Sendable (BundleSyncProgress) -> Void)? = nil
    ) async throws -> BundleSyncResult {
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
        return fullDownload
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

        guard let activeDB = try activeDatabaseURL(), fileManager.fileExists(atPath: activeDB.path) else {
            return nil
        }

        let stagingDB = try stageCopyOfActiveDB(forVersion: manifest.bundleVersion)
        let patchSQL = String(decoding: patchData, as: UTF8.self)
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
                        totalBytes: max(0, expected)
                    )
                )
            }
            try validateSHA256(fileAt: downloaded, expectedHex: manifest.db.sha256, label: "bundle db")
            stagingDB = try writeStagingDB(downloadedFile: downloaded, version: manifest.bundleVersion)
        }

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

    private func stagingDirectory() throws -> URL {
        let stageDir = try rootDir().appendingPathComponent("staging", isDirectory: true)
        if !fileManager.fileExists(atPath: stageDir.path) {
            try fileManager.createDirectory(at: stageDir, withIntermediateDirectories: true)
        }
        return stageDir
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

        let stageDir = try stagingDirectory()
        let out = stageDir.appendingPathComponent("\(manifest.bundleVersion)-\(UUID().uuidString).sqlite")
        fileManager.createFile(atPath: out.path, contents: nil)
        let outHandle = try FileHandle(forWritingTo: out)
        defer {
            try? outHandle.close()
        }

        let declaredTotalBytes = manifest.db.bytes
        var totalBytes: Int64 = 0
        for (index, part) in sortedParts.enumerated() {
            let partURL = try resolveArtifactURL(part, relativeTo: manifestURL)
            let partLabel = "Downloading part \(index + 1)/\(sortedParts.count): \(part.file)"
            let bytesBeforePart = totalBytes
            emitProgress(
                onProgress,
                stage: .downloading,
                detail: partLabel,
                completedBytes: bytesBeforePart,
                totalBytes: declaredTotalBytes
            )
            let downloadedPart = try await downloadFile(from: partURL) { completedBytes, totalBytesInPart in
                let partExpected = totalBytesInPart ?? part.bytes
                let boundedPartBytes = min(completedBytes, max(partExpected, 0))
                onProgress?(
                    BundleSyncProgress(
                        stage: .downloading,
                        detail: partLabel,
                        completedBytes: max(0, bytesBeforePart + boundedPartBytes),
                        totalBytes: max(0, declaredTotalBytes)
                    )
                )
            }
            try validateSHA256(fileAt: downloadedPart, expectedHex: part.sha256, label: "bundle db part \(part.file)")
            totalBytes += try fileSize(downloadedPart)

            let inHandle = try FileHandle(forReadingFrom: downloadedPart)
            while true {
                let chunk = inHandle.readData(ofLength: 8 * 1024 * 1024)
                if chunk.isEmpty {
                    break
                }
                outHandle.write(chunk)
            }
            try inHandle.close()
            try? fileManager.removeItem(at: downloadedPart)
            emitProgress(
                onProgress,
                stage: .assembling,
                detail: "Assembled \(index + 1)/\(sortedParts.count) parts",
                completedBytes: min(totalBytes, declaredTotalBytes),
                totalBytes: declaredTotalBytes
            )
        }

        if totalBytes != manifest.db.bytes {
            throw ConsumerAppError.invalidManifest(
                "db_parts size mismatch: expected \(manifest.db.bytes), got \(totalBytes)"
            )
        }
        try validateSHA256(fileAt: out, expectedHex: manifest.db.sha256, label: "bundle db (assembled)")
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
            throw ConsumerAppError.network("Unexpected non-HTTP response for \(url.absoluteString)")
        }
        guard (200...299).contains(http.statusCode) else {
            let previewData = try? Data(contentsOf: tmpURL)
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
        totalBytes: Int64
    ) {
        guard let onProgress else {
            return
        }
        onProgress(
            BundleSyncProgress(
                stage: stage,
                detail: detail,
                completedBytes: max(0, completedBytes),
                totalBytes: max(0, totalBytes)
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

        let tagAssets = try await fetchGitHubReleaseAssets(
            owner: releaseAsset.owner,
            repo: releaseAsset.repo,
            tag: releaseAsset.tag
        )
        guard let assetID = tagAssets[releaseAsset.assetName] else {
            throw ConsumerAppError.invalidManifest(
                "GitHub release asset not found: \(releaseAsset.assetName) in \(releaseAsset.owner)/\(releaseAsset.repo) tag \(releaseAsset.tag)"
            )
        }
        guard let apiURL = URL(
            string: "https://api.github.com/repos/\(releaseAsset.owner)/\(releaseAsset.repo)/releases/assets/\(assetID)"
        ) else {
            throw ConsumerAppError.invalidManifest("Unable to build GitHub asset API URL")
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

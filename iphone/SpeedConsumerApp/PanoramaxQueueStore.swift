import Foundation
import CryptoKit

struct PanoramaxBatchRecord: Codable, Equatable {
    let batchID: String
    let captureSessionID: String
    let createdAt: Date
    var state: PanoramaxBatchState
    var items: [PanoramaxItemRecord]
    var remoteUploadSetID: String? = nil
    var instanceOrigin: String? = nil
}

struct PanoramaxItemRecord: Codable, Equatable {
    let itemID: String
    let originalPath: String
    let thumbnailPath: String
    let metadata: PanoramaxCaptureMetadata
    var state: PanoramaxItemState
    var remoteID: String?
    var isFavorite: Bool = false

    private enum CodingKeys: String, CodingKey { case itemID, originalPath, thumbnailPath, metadata, state, remoteID, isFavorite }

    init(itemID: String, originalPath: String, thumbnailPath: String, metadata: PanoramaxCaptureMetadata, state: PanoramaxItemState, remoteID: String?, isFavorite: Bool = false) {
        self.itemID = itemID
        self.originalPath = originalPath
        self.thumbnailPath = thumbnailPath
        self.metadata = metadata
        self.state = state
        self.remoteID = remoteID
        self.isFavorite = isFavorite
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        itemID = try container.decode(String.self, forKey: .itemID)
        originalPath = try container.decode(String.self, forKey: .originalPath)
        thumbnailPath = try container.decode(String.self, forKey: .thumbnailPath)
        metadata = try container.decode(PanoramaxCaptureMetadata.self, forKey: .metadata)
        state = try container.decode(PanoramaxItemState.self, forKey: .state)
        remoteID = try container.decodeIfPresent(String.self, forKey: .remoteID)
        isFavorite = try container.decodeIfPresent(Bool.self, forKey: .isFavorite) ?? false
    }
}

struct PanoramaxQueueCleanupReport: Equatable, Sendable {
    var recoveredBatchIDs: [String] = []
    var removedOrphanFileCount = 0
    var removedOrphanByteCount: Int64 = 0
    var removedEmptyBatchCount = 0
    var failedRelativePaths: [String] = []

    var hasFailures: Bool { !failedRelativePaths.isEmpty }
}

struct PanoramaxDeletionReport: Equatable, Sendable {
    var deletedItemIDs: [String] = []
    var failedRelativePaths: [String] = []

    var hasFailures: Bool { !failedRelativePaths.isEmpty }
}

/// Transactional, app-private queue. The root is excluded from iCloud/device backup.
final class PanoramaxQueueStore: @unchecked Sendable {
    private let root: URL
    private let batchesDirectory: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let lock = NSRecursiveLock()
    private(set) var startupCleanupReport = PanoramaxQueueCleanupReport()

    init(root: URL? = nil, performStartupMaintenance: Bool = true) throws {
        let base = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("YouSpeed", isDirectory: true)
        let configuredRoot = base.appendingPathComponent("Panoramax", isDirectory: true)
        self.root = configuredRoot
        self.batchesDirectory = configuredRoot.appendingPathComponent("batches", isDirectory: true)
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
        self.encoder.dateEncodingStrategy = .iso8601
        self.decoder.dateDecodingStrategy = .iso8601
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try FileManager.default.createDirectory(at: batchesDirectory, withIntermediateDirectories: true)
        var excludedRoot = configuredRoot
        try? excludedRoot.setResourceValues(values)
        var excludedBatches = batchesDirectory
        try? excludedBatches.setResourceValues(values)
        protect(configuredRoot)
        protect(batchesDirectory)
        if performStartupMaintenance {
            startupCleanupReport = performStartupMaintenanceNow()
        }
    }

    /// Executes startup repair on the caller's executor. The app routes this
    /// through `PanoramaxQueueMaintenanceExecutor`; synchronous tests may keep
    /// the default initializer behavior for deterministic fixtures.
    @discardableResult
    func performStartupMaintenanceNow() -> PanoramaxQueueCleanupReport {
        let report: PanoramaxQueueCleanupReport
        do {
            report = try repairInterruptedStateAndOrphans()
        } catch {
            // Queue reads remain available even when best-effort maintenance
            // cannot finish. The view model surfaces this synthetic path.
            report = PanoramaxQueueCleanupReport(failedRelativePaths: ["batches"])
        }
        lock.withLock { startupCleanupReport = report }
        return report
    }

    func createBatch(captureSessionID: String, createdAt: Date = Date()) throws -> PanoramaxBatchRecord {
        precondition(!captureSessionID.isEmpty)
        let batch = PanoramaxBatchRecord(batchID: UUID().uuidString, captureSessionID: captureSessionID, createdAt: createdAt, state: .capturing, items: [])
        try commit(batch)
        return batch
    }

    func listBatches() throws -> [PanoramaxBatchRecord] {
        try lock.withLock {
            let files = try FileManager.default.contentsOfDirectory(at: batchesDirectory, includingPropertiesForKeys: nil)
                .filter { $0.pathExtension == "json" }
            return files.compactMap { file in
                let fileBatchID = file.deletingPathExtension().lastPathComponent
                guard Self.isValidBatchID(fileBatchID),
                      let batch = try? decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: file)),
                      batch.batchID == fileBatchID else { return nil }
                return batch
            }
                .sorted { $0.createdAt > $1.createdAt }
        }
    }

    func getBatch(_ batchID: String) throws -> PanoramaxBatchRecord? {
        try lock.withLock { try read(batchID) }
    }

    func fileURL(forRelativePath path: String) -> URL? {
        safeFileURL(forRelativePath: path)
    }

    func thumbnailURL(for item: PanoramaxItemRecord) -> URL? {
        fileURL(forRelativePath: item.thumbnailPath)
    }

    func originalURL(for item: PanoramaxItemRecord) -> URL? {
        fileURL(forRelativePath: item.originalPath)
    }

    @discardableResult
    func addJPEG(batchID: String, jpeg: Data, thumbnail: Data, metadata: PanoramaxCaptureMetadata) throws -> PanoramaxItemRecord {
        guard Self.isJPEG(jpeg), !thumbnail.isEmpty else { throw QueueError.invalidImage }
        guard metadata.validate(now: Date()).isEmpty, metadata.byteSize == Int64(jpeg.count), metadata.sha256.lowercased() == Self.sha256(jpeg) else { throw QueueError.invalidMetadata }
        return try lock.withLock {
            guard var batch = try read(batchID), batch.captureSessionID == metadata.captureSessionID else { throw QueueError.unknownBatch }
            guard batch.state == .capturing else { throw QueueError.invalidBatchState }
            guard !batch.items.contains(where: { $0.itemID == metadata.captureID }) else { throw QueueError.duplicateItem }
            let itemDirectory = batchesDirectory.appendingPathComponent(batchID, isDirectory: true).appendingPathComponent(metadata.captureID, isDirectory: true)
            try FileManager.default.createDirectory(at: itemDirectory, withIntermediateDirectories: true)
            let original = itemDirectory.appendingPathComponent("\(metadata.captureID).jpg")
            let thumb = itemDirectory.appendingPathComponent("\(metadata.captureID).thumb.jpg")
            try jpeg.write(to: original, options: .atomic)
            try thumbnail.write(to: thumb, options: .atomic)
            protect(itemDirectory)
            protect(original)
            protect(thumb)
            let item = PanoramaxItemRecord(itemID: metadata.captureID, originalPath: relativePath(original), thumbnailPath: relativePath(thumb), metadata: metadata, state: .captured, remoteID: nil, isFavorite: false)
            batch.items.append(item)
            try commit(batch)
            return item
        }
    }

    func updateBatch(_ batch: PanoramaxBatchRecord) throws { try commit(batch) }

    /// Changes only lifecycle state on the latest durable batch snapshot.
    /// Capture callbacks append items directly in the store, so sealing with an
    /// older in-memory snapshot would otherwise discard those item records.
    @discardableResult
    func transitionBatch(_ batchID: String, to state: PanoramaxBatchState) throws -> PanoramaxBatchRecord {
        try lock.withLock {
            guard var batch = try read(batchID) else { throw QueueError.unknownBatch }
            batch.state = state
            try commit(batch)
            return batch
        }
    }

    @discardableResult
    func updateItem(batchID: String, itemID: String, state: PanoramaxItemState, remoteID: String? = nil) throws -> PanoramaxBatchRecord {
        try lock.withLock {
            guard var batch = try read(batchID), let index = batch.items.firstIndex(where: { $0.itemID == itemID }) else { throw QueueError.unknownItem }
            batch.items[index].state = state
            if let remoteID { batch.items[index].remoteID = remoteID }
            try commit(batch)
            return batch
        }
    }

    @discardableResult
    func updateItemFavorite(batchID: String, itemID: String, isFavorite: Bool) throws -> PanoramaxBatchRecord {
        try lock.withLock {
            guard var batch = try read(batchID), let index = batch.items.firstIndex(where: { $0.itemID == itemID }) else { throw QueueError.unknownItem }
            batch.items[index].isFavorite = isFavorite
            try commit(batch)
            return batch
        }
    }

    /// Restores a safely resumable snapshot after an upload task is stopped.
    /// A request that was in flight is deliberately abandoned: its remote
    /// outcome is unknowable, so retrying it could duplicate an accepted image.
    @discardableResult
    func abandonInFlightItems(batchID: String) throws -> PanoramaxBatchRecord {
        try lock.withLock {
            guard var batch = try read(batchID) else { throw QueueError.unknownBatch }
            for index in batch.items.indices where batch.items[index].state == .uploading {
                batch.items[index].state = .abandoned
            }
            if batch.state == .creatingUploadSet {
                batch.state = batch.remoteUploadSetID == nil ? .approved : .partial
            } else if batch.state == .uploading {
                batch.state = .partial
            }
            try commit(batch)
            return batch
        }
    }

    /// Removes the oldest non-favorite originals and thumbnails until the configured byte budget fits.
    @discardableResult
    func enforceStorageLimit(maxBytes: Int64) throws -> [String] {
        try enforceStorageLimitWithReport(maxBytes: maxBytes).deletedItemIDs
    }

    /// Report-producing variant used by gallery maintenance so a failed asset
    /// removal is visible instead of looking like successful quota eviction.
    @discardableResult
    func enforceStorageLimitWithReport(maxBytes: Int64) throws -> PanoramaxDeletionReport {
        guard maxBytes > 0 else { return PanoramaxDeletionReport() }
        return try lock.withLock {
            let files = try FileManager.default.contentsOfDirectory(at: batchesDirectory, includingPropertiesForKeys: nil)
                .filter { $0.pathExtension == "json" }
            let batches = files.compactMap { try? decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: $0)) }
            struct Candidate { let batchID: String; let id: String; let bytes: Int64; let capturedAt: Date }
            var candidates: [Candidate] = []
            var total: Int64 = 0
            for batch in batches {
                for item in batch.items {
                    let originalBytes = fileSize(forRelativePath: item.originalPath)
                    let thumbnailBytes = fileSize(forRelativePath: item.thumbnailPath)
                    let bytes = originalBytes + thumbnailBytes
                    total += bytes
                    if !item.isFavorite,
                       DriveRecorderPolicy.canEvictPanoramaxItem(
                           batchState: batch.state,
                           itemState: item.state
                       ) {
                        candidates.append(Candidate(batchID: batch.batchID, id: item.itemID, bytes: bytes, capturedAt: item.metadata.capturedAt))
                    }
                }
            }
            guard total > maxBytes else { return PanoramaxDeletionReport() }
            candidates.sort { $0.capturedAt < $1.capturedAt }
            var report = PanoramaxDeletionReport()
            for candidate in candidates where total > maxBytes {
                guard !Task.isCancelled else { break }
                let deletion = try deleteItems(batchID: candidate.batchID, itemIDs: [candidate.id])
                report.deletedItemIDs.append(contentsOf: deletion.deletedItemIDs)
                report.failedRelativePaths.append(contentsOf: deletion.failedRelativePaths)
                // Avoid cascading through more gallery records when local
                // cleanup is already failing; surface the issue and retry on
                // the next explicit/startup maintenance pass.
                guard !deletion.hasFailures else { break }
                total -= candidate.bytes
            }
            return report
        }
    }

    @discardableResult
    func deleteItem(batchID: String, itemID: String) throws -> PanoramaxDeletionReport {
        let report = try deleteItems(batchID: batchID, itemIDs: [itemID])
        guard !report.deletedItemIDs.isEmpty else { throw QueueError.unknownItem }
        return report
    }

    /// Removes the durable gallery records first, then their local assets. A
    /// missing asset is already a successful deletion; other cleanup failures
    /// are returned to the caller and retried by the startup orphan scavenger.
    @discardableResult
    func deleteItems(batchID: String, itemIDs: Set<String>) throws -> PanoramaxDeletionReport {
        guard !itemIDs.isEmpty else { return PanoramaxDeletionReport() }
        return try lock.withLock {
            guard var batch = try read(batchID) else { throw QueueError.unknownBatch }
            let removedItems = batch.items.filter { itemIDs.contains($0.itemID) }
            guard !removedItems.isEmpty else { return PanoramaxDeletionReport() }
            guard removedItems.allSatisfy({ item in
                DriveRecorderPolicy.canDeletePanoramaxItem(
                    batchState: batch.state,
                    itemState: item.state
                )
            }) else { throw QueueError.invalidBatchState }

            batch.items.removeAll { itemIDs.contains($0.itemID) }
            try commit(batch)

            var report = PanoramaxDeletionReport(deletedItemIDs: removedItems.map(\.itemID))
            for item in removedItems {
                removeLocalAsset(relativePath: item.originalPath, failures: &report.failedRelativePaths)
                removeLocalAsset(relativePath: item.thumbnailPath, failures: &report.failedRelativePaths)
                removeEmptyItemDirectory(for: item)
            }
            _ = pruneEmptyBatchIfSafe(batch, failures: &report.failedRelativePaths)
            return report
        }
    }

    /// Applies the optional post-upload retention policy without touching
    /// queued, failed, excluded, or abandoned items.
    @discardableResult
    func deleteUploadedItems(batchID: String) throws -> PanoramaxDeletionReport {
        try lock.withLock {
            guard let batch = try read(batchID) else { throw QueueError.unknownBatch }
            guard batch.state == .complete else { throw QueueError.invalidBatchState }
            let terminalIDs = Set(batch.items.compactMap { item -> String? in
                switch item.state {
                case .uploaded, .accepted, .duplicate:
                    return item.itemID
                default:
                    return nil
                }
            })
            return try deleteItems(batchID: batchID, itemIDs: terminalIDs)
        }
    }

    /// Retries the opt-in local-retention cleanup for remote-complete batches.
    /// Individual failures are reported without preventing other batches from
    /// being swept; their complete records remain available for the next launch.
    @discardableResult
    func deleteUploadedItemsInCompletedBatches() throws -> PanoramaxDeletionReport {
        try lock.withLock {
            let completed = try listBatches().filter { $0.state == .complete }
            var aggregate = PanoramaxDeletionReport()
            for batch in completed {
                do {
                    let report = try deleteUploadedItems(batchID: batch.batchID)
                    aggregate.deletedItemIDs.append(contentsOf: report.deletedItemIDs)
                    aggregate.failedRelativePaths.append(contentsOf: report.failedRelativePaths)
                } catch {
                    aggregate.failedRelativePaths.append("batches/\(batch.batchID).json")
                }
            }
            aggregate.deletedItemIDs.sort()
            aggregate.failedRelativePaths.sort()
            return aggregate
        }
    }

    static func sha256(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    private static func isJPEG(_ data: Data) -> Bool {
        data.count >= 4 && data.prefix(2) == Data([0xff, 0xd8]) && data.suffix(2) == Data([0xff, 0xd9])
    }

    enum QueueError: Error {
        case unknownBatch, unknownItem, duplicateItem, invalidImage, invalidMetadata, invalidBatchState, invalidBatchID
    }

    /// Repairs only states that cannot still be active during store startup and
    /// removes unreferenced legacy image files for successfully decoded batches.
    @discardableResult
    private func repairInterruptedStateAndOrphans() throws -> PanoramaxQueueCleanupReport {
        try lock.withLock {
            let files = try FileManager.default.contentsOfDirectory(at: batchesDirectory, includingPropertiesForKeys: nil)
                .filter { $0.pathExtension == "json" }
            var decodedBatches: [PanoramaxBatchRecord] = []
            var report = PanoramaxQueueCleanupReport()

            for file in files {
                let fileBatchID = file.deletingPathExtension().lastPathComponent
                guard Self.isValidBatchID(fileBatchID),
                      var batch = try? decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: file)),
                      batch.batchID == fileBatchID else {
                    report.failedRelativePaths.append(relativePath(file))
                    continue
                }
                var changed = false
                if batch.state == .capturing {
                    batch.state = .awaitingReview
                    changed = true
                } else if batch.state == .creatingUploadSet {
                    batch.state = batch.remoteUploadSetID == nil ? .approved : .partial
                    changed = true
                } else if batch.state == .uploading {
                    batch.state = .partial
                    changed = true
                }
                for index in batch.items.indices where batch.items[index].state == .uploading {
                    batch.items[index].state = .abandoned
                    changed = true
                }
                if changed {
                    try commit(batch)
                    report.recoveredBatchIDs.append(batch.batchID)
                }
                decodedBatches.append(batch)
            }

            let referencedPaths = Set(decodedBatches.flatMap { batch in
                batch.items.flatMap { [$0.originalPath, $0.thumbnailPath] }
            })
            for batch in decodedBatches {
                let batchDirectory = batchesDirectory.appendingPathComponent(batch.batchID, isDirectory: true)
                let batchValues = try? batchDirectory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
                guard batchValues?.isDirectory == true, batchValues?.isSymbolicLink != true else { continue }
                var legacyItemDirectories: Set<URL> = []
                guard let enumerator = FileManager.default.enumerator(
                    at: batchDirectory,
                    includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey],
                    options: [.skipsHiddenFiles]
                ) else { continue }
                for case let candidate as URL in enumerator {
                    let values = try? candidate.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
                    guard values?.isRegularFile == true,
                          values?.isSymbolicLink != true,
                          isLegacyItemJPEG(candidate, directlyUnder: batchDirectory) else { continue }
                    legacyItemDirectories.insert(candidate.deletingLastPathComponent())
                    let relative = relativePath(candidate)
                    guard !referencedPaths.contains(relative) else { continue }
                    do {
                        try FileManager.default.removeItem(at: candidate)
                        report.removedOrphanFileCount += 1
                        report.removedOrphanByteCount += Int64(values?.fileSize ?? 0)
                    } catch {
                        report.failedRelativePaths.append(relative)
                    }
                }
                for directory in legacyItemDirectories {
                    do {
                        guard try FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty else { continue }
                        try FileManager.default.removeItem(at: directory)
                    } catch {
                        report.failedRelativePaths.append(relativePath(directory))
                    }
                }
            }
            for batch in decodedBatches where pruneEmptyBatchIfSafe(
                batch,
                failures: &report.failedRelativePaths
            ) {
                report.removedEmptyBatchCount += 1
            }
            report.recoveredBatchIDs.sort()
            report.failedRelativePaths.sort()
            return report
        }
    }

    /// Legacy capture leakage is narrowly recognizable as the two JPEG names
    /// written by `addJPEG`, one directory below a decoded batch. Do not treat
    /// batch-root files or future sidecars as disposable merely because the
    /// current record does not reference them.
    private func isLegacyItemJPEG(_ candidate: URL, directlyUnder batchDirectory: URL) -> Bool {
        guard candidate.pathExtension.lowercased() == "jpg" else { return false }
        let itemDirectory = candidate.deletingLastPathComponent().standardizedFileURL
        guard itemDirectory.deletingLastPathComponent().standardizedFileURL == batchDirectory.standardizedFileURL else {
            return false
        }
        let directoryValues = try? itemDirectory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard directoryValues?.isDirectory == true, directoryValues?.isSymbolicLink != true else { return false }
        let itemID = itemDirectory.lastPathComponent
        return candidate.lastPathComponent == "\(itemID).jpg"
            || candidate.lastPathComponent == "\(itemID).thumb.jpg"
    }

    private func read(_ batchID: String) throws -> PanoramaxBatchRecord? {
        let file = try batchRecordURL(for: batchID)
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        let batch = try decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: file))
        guard batch.batchID == batchID else { throw QueueError.invalidBatchID }
        return batch
    }

    private static func isValidBatchID(_ batchID: String) -> Bool {
        UUID(uuidString: batchID) != nil
            && !batchID.contains("/")
            && batchID != "."
            && batchID != ".."
    }

    private func batchRecordURL(for batchID: String) throws -> URL {
        guard Self.isValidBatchID(batchID) else { throw QueueError.invalidBatchID }
        return batchesDirectory.appendingPathComponent("\(batchID).json")
    }

    private func safeFileURL(forRelativePath path: String) -> URL? {
        guard !path.isEmpty, !path.hasPrefix("/") else { return nil }
        let standardizedRoot = root.standardizedFileURL
        let candidate = standardizedRoot.appendingPathComponent(path).standardizedFileURL
        guard candidate.path.hasPrefix(standardizedRoot.path + "/") else { return nil }
        return candidate
    }

    private func fileSize(forRelativePath path: String) -> Int64 {
        guard let url = safeFileURL(forRelativePath: path) else { return 0 }
        return (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize).flatMap(Int64.init) ?? 0
    }

    private func removeLocalAsset(relativePath path: String, failures: inout [String]) {
        guard let url = safeFileURL(forRelativePath: path) else {
            failures.append(path)
            return
        }
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        do {
            try FileManager.default.removeItem(at: url)
        } catch {
            failures.append(path)
        }
    }

    private func removeEmptyItemDirectory(for item: PanoramaxItemRecord) {
        guard let original = safeFileURL(forRelativePath: item.originalPath) else { return }
        let directory = original.deletingLastPathComponent()
        guard (try? FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty) == true else { return }
        try? FileManager.default.removeItem(at: directory)
    }

    @discardableResult
    private func pruneEmptyBatchIfSafe(
        _ batch: PanoramaxBatchRecord,
        failures: inout [String]
    ) -> Bool {
        guard Self.isValidBatchID(batch.batchID) else {
            failures.append(batch.batchID)
            return false
        }
        guard batch.items.isEmpty,
              batch.state == .awaitingReview || batch.state == .complete else {
            return false
        }
        let directory = batchesDirectory.appendingPathComponent(batch.batchID, isDirectory: true)
        if FileManager.default.fileExists(atPath: directory.path) {
            do {
                guard try FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty else {
                    // Keep the empty record so startup maintenance retains the
                    // authority to retry removal of residual local assets.
                    return false
                }
            } catch {
                failures.append(relativePath(directory))
                return false
            }
        }
        let record = batchesDirectory.appendingPathComponent("\(batch.batchID).json")
        if FileManager.default.fileExists(atPath: record.path) {
            do {
                try FileManager.default.removeItem(at: record)
            } catch {
                failures.append(relativePath(record))
                return false
            }
        }
        if (try? FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty) == true {
            do {
                try FileManager.default.removeItem(at: directory)
            } catch {
                failures.append(relativePath(directory))
            }
        }
        return true
    }

    private func commit(_ batch: PanoramaxBatchRecord) throws {
        try lock.withLock {
            let destination = try batchRecordURL(for: batch.batchID)
            let temporary = destination.appendingPathExtension("tmp")
            try encoder.encode(batch).write(to: temporary, options: .atomic)
            if FileManager.default.fileExists(atPath: destination.path) {
                _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary)
            } else {
                try FileManager.default.moveItem(at: temporary, to: destination)
            }
        }
    }

    private func relativePath(_ url: URL) -> String { url.path.replacingOccurrences(of: root.path + "/", with: "") }

    private func protect(_ url: URL) {
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var excludedURL = url
        try? excludedURL.setResourceValues(values)
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
    }
}

struct PanoramaxQueueMaintenanceResult: @unchecked Sendable {
    let startupCleanup: PanoramaxQueueCleanupReport?
    let deletion: PanoramaxDeletionReport
    let batches: [PanoramaxBatchRecord]
    let batchLoadSucceeded: Bool
}

/// Serializes gallery scans and retention deletion away from the main actor.
/// QueueStore's lock still protects capture/upload mutations, while this actor
/// prevents multiple maintenance sweeps from competing for disk bandwidth.
actor PanoramaxQueueMaintenanceExecutor {
    static let shared = PanoramaxQueueMaintenanceExecutor()

    func loadBatches(store: PanoramaxQueueStore) -> PanoramaxQueueMaintenanceResult {
        result(store: store, startup: nil, deletion: PanoramaxDeletionReport())
    }

    func runStartup(
        store: PanoramaxQueueStore,
        deleteCompletedUploads: Bool
    ) -> PanoramaxQueueMaintenanceResult {
        let startup = store.performStartupMaintenanceNow()
        let deletion = deleteCompletedUploads
            ? completedRetentionReport(store: store)
            : PanoramaxDeletionReport()
        return result(store: store, startup: startup, deletion: deletion)
    }

    func retryCompletedRetention(store: PanoramaxQueueStore) -> PanoramaxQueueMaintenanceResult {
        result(
            store: store,
            startup: nil,
            deletion: completedRetentionReport(store: store)
        )
    }

    func enforceStorageLimit(
        store: PanoramaxQueueStore,
        maxBytes: Int64
    ) -> PanoramaxQueueMaintenanceResult {
        guard !Task.isCancelled else {
            return PanoramaxQueueMaintenanceResult(
                startupCleanup: nil,
                deletion: PanoramaxDeletionReport(),
                batches: [],
                batchLoadSucceeded: false
            )
        }
        var deletion = PanoramaxDeletionReport()
        do {
            deletion = try store.enforceStorageLimitWithReport(maxBytes: maxBytes)
        } catch {
            deletion.failedRelativePaths = ["batches"]
        }
        return result(store: store, startup: nil, deletion: deletion)
    }

    func deleteItems(
        store: PanoramaxQueueStore,
        itemIDsByBatch: [String: Set<String>]
    ) -> PanoramaxQueueMaintenanceResult {
        var deletion = PanoramaxDeletionReport()
        for batchID in itemIDsByBatch.keys.sorted() {
            guard let itemIDs = itemIDsByBatch[batchID], !itemIDs.isEmpty else { continue }
            do {
                let report = try store.deleteItems(batchID: batchID, itemIDs: itemIDs)
                deletion.deletedItemIDs.append(contentsOf: report.deletedItemIDs)
                deletion.failedRelativePaths.append(contentsOf: report.failedRelativePaths)
            } catch {
                deletion.failedRelativePaths.append("batches/\(batchID).json")
            }
        }
        deletion.deletedItemIDs.sort()
        deletion.failedRelativePaths.sort()
        return result(store: store, startup: nil, deletion: deletion)
    }

    func finalizeRemoteCompletion(
        store: PanoramaxQueueStore,
        batchID: String,
        deleteUploadedImages: Bool
    ) throws -> PanoramaxQueueMaintenanceResult {
        guard var ready = try store.getBatch(batchID) else {
            return result(store: store, startup: nil, deletion: PanoramaxDeletionReport())
        }
        ready.state = .complete
        try store.updateBatch(ready)

        var deletion = PanoramaxDeletionReport()
        if deleteUploadedImages {
            do {
                deletion = try store.deleteUploadedItems(batchID: batchID)
            } catch {
                deletion.failedRelativePaths = ["batches/\(batchID).json"]
            }
        }
        return result(store: store, startup: nil, deletion: deletion)
    }

    private func completedRetentionReport(store: PanoramaxQueueStore) -> PanoramaxDeletionReport {
        do {
            return try store.deleteUploadedItemsInCompletedBatches()
        } catch {
            return PanoramaxDeletionReport(failedRelativePaths: ["batches"])
        }
    }

    private func result(
        store: PanoramaxQueueStore,
        startup: PanoramaxQueueCleanupReport?,
        deletion: PanoramaxDeletionReport
    ) -> PanoramaxQueueMaintenanceResult {
        do {
            return PanoramaxQueueMaintenanceResult(
                startupCleanup: startup,
                deletion: deletion,
                batches: try store.listBatches(),
                batchLoadSucceeded: true
            )
        } catch {
            var failedDeletion = deletion
            failedDeletion.failedRelativePaths.append("batches")
            return PanoramaxQueueMaintenanceResult(
                startupCleanup: startup,
                deletion: failedDeletion,
                batches: [],
                batchLoadSucceeded: false
            )
        }
    }
}

private extension NSRecursiveLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T { lock(); defer { unlock() }; return try body() }
}

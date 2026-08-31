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

/// Transactional, app-private queue. The root is excluded from iCloud/device backup.
final class PanoramaxQueueStore {
    private let root: URL
    private let batchesDirectory: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let lock = NSRecursiveLock()

    init(root: URL? = nil) throws {
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
            return files.compactMap { try? decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: $0)) }
                .sorted { $0.createdAt > $1.createdAt }
        }
    }

    func getBatch(_ batchID: String) throws -> PanoramaxBatchRecord? {
        try lock.withLock { try read(batchID) }
    }

    func fileURL(forRelativePath path: String) -> URL {
        root.appendingPathComponent(path)
    }

    func thumbnailURL(for item: PanoramaxItemRecord) -> URL {
        fileURL(forRelativePath: item.thumbnailPath)
    }

    func originalURL(for item: PanoramaxItemRecord) -> URL {
        fileURL(forRelativePath: item.originalPath)
    }

    @discardableResult
    func addJPEG(batchID: String, jpeg: Data, thumbnail: Data, metadata: PanoramaxCaptureMetadata) throws -> PanoramaxItemRecord {
        guard Self.isJPEG(jpeg), !thumbnail.isEmpty else { throw QueueError.invalidImage }
        guard metadata.validate(now: Date()).isEmpty, metadata.byteSize == Int64(jpeg.count), metadata.sha256.lowercased() == Self.sha256(jpeg) else { throw QueueError.invalidMetadata }
        return try lock.withLock {
            guard var batch = try read(batchID), batch.captureSessionID == metadata.captureSessionID else { throw QueueError.unknownBatch }
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

    /// Removes the oldest non-favorite originals and thumbnails until the configured byte budget fits.
    @discardableResult
    func enforceStorageLimit(maxBytes: Int64) throws -> [String] {
        guard maxBytes > 0 else { return [] }
        return try lock.withLock {
            let files = try FileManager.default.contentsOfDirectory(at: batchesDirectory, includingPropertiesForKeys: nil)
                .filter { $0.pathExtension == "json" }
            var batches = files.compactMap { try? decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: $0)) }
            struct Candidate { let batchIndex: Int; let itemIndex: Int; let id: String; let bytes: Int64; let capturedAt: Date }
            var candidates: [Candidate] = []
            var total: Int64 = 0
            for (batchIndex, batch) in batches.enumerated() {
                for (itemIndex, item) in batch.items.enumerated() {
                    let originalURL = root.appendingPathComponent(item.originalPath)
                    let thumbnailURL = root.appendingPathComponent(item.thumbnailPath)
                    let originalBytes = (try? originalURL.resourceValues(forKeys: [.fileSizeKey]).fileSize).flatMap(Int64.init) ?? 0
                    let thumbnailBytes = (try? thumbnailURL.resourceValues(forKeys: [.fileSizeKey]).fileSize).flatMap(Int64.init) ?? 0
                    let bytes = originalBytes + thumbnailBytes
                    total += bytes
                    if !item.isFavorite { candidates.append(Candidate(batchIndex: batchIndex, itemIndex: itemIndex, id: item.itemID, bytes: bytes, capturedAt: item.metadata.capturedAt)) }
                }
            }
            guard total > maxBytes else { return [] }
            candidates.sort { $0.capturedAt < $1.capturedAt }
            var removed: [String] = []
            for candidate in candidates where total > maxBytes {
                guard let item = batches[candidate.batchIndex].items.first(where: { $0.itemID == candidate.id }) else { continue }
                try? FileManager.default.removeItem(at: root.appendingPathComponent(item.originalPath))
                try? FileManager.default.removeItem(at: root.appendingPathComponent(item.thumbnailPath))
                total -= candidate.bytes
                removed.append(candidate.id)
                batches[candidate.batchIndex].items.removeAll { $0.itemID == candidate.id }
            }
            for batch in batches { try commit(batch) }
            return removed
        }
    }

    func deleteItem(batchID: String, itemID: String) throws {
        try lock.withLock {
            guard var batch = try read(batchID), let item = batch.items.first(where: { $0.itemID == itemID }) else { throw QueueError.unknownItem }
            try? FileManager.default.removeItem(at: root.appendingPathComponent(item.originalPath))
            try? FileManager.default.removeItem(at: root.appendingPathComponent(item.thumbnailPath))
            batch.items.removeAll { $0.itemID == itemID }
            try commit(batch)
        }
    }

    static func sha256(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    private static func isJPEG(_ data: Data) -> Bool {
        data.count >= 4 && data.prefix(2) == Data([0xff, 0xd8]) && data.suffix(2) == Data([0xff, 0xd9])
    }

    enum QueueError: Error { case unknownBatch, unknownItem, duplicateItem, invalidImage, invalidMetadata }

    private func read(_ batchID: String) throws -> PanoramaxBatchRecord? {
        let file = batchesDirectory.appendingPathComponent("\(batchID).json")
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        return try decoder.decode(PanoramaxBatchRecord.self, from: Data(contentsOf: file))
    }

    private func commit(_ batch: PanoramaxBatchRecord) throws {
        try lock.withLock {
            let destination = batchesDirectory.appendingPathComponent("\(batch.batchID).json")
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

private extension NSRecursiveLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T { lock(); defer { unlock() }; return try body() }
}

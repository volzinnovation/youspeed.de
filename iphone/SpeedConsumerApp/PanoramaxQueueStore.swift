import Foundation
import CryptoKit

struct PanoramaxBatchRecord: Codable, Equatable {
    let batchID: String
    let captureSessionID: String
    let createdAt: Date
    var state: PanoramaxBatchState
    var items: [PanoramaxItemRecord]
}

struct PanoramaxItemRecord: Codable, Equatable {
    let itemID: String
    let originalPath: String
    let thumbnailPath: String
    let metadata: PanoramaxCaptureMetadata
    var state: PanoramaxItemState
    var remoteID: String?
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
            let item = PanoramaxItemRecord(itemID: metadata.captureID, originalPath: relativePath(original), thumbnailPath: relativePath(thumb), metadata: metadata, state: .captured, remoteID: nil)
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

    func deleteItem(batchID: String, itemID: String) throws {
        try lock.withLock {
            guard var batch = try read(batchID), let item = batch.items.first(where: { $0.itemID == itemID }) else { throw QueueError.unknownItem }
            try? FileManager.default.removeItem(at: root.appendingPathComponent(item.originalPath))
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

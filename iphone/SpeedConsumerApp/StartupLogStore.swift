import Foundation

enum StartupLogReviewState {
    case checking, choice, clearing, failed, complete
}

/// Only app-owned logs, including retained sessions, belong to this cleanup.
/// Maps, observations, photos, videos and other support files are excluded.
enum StartupLogStore {
    static let thresholdBytes: Int64 = 100_000_000

    static func requiresReview(bytes: Int64) -> Bool { bytes > thresholdBytes }

    static func files(in directory: URL) throws -> [URL] {
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }
        return try FileManager.default.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
        ).filter { url in
            let name = url.lastPathComponent
            guard name == "gps_fix_log.csv" || name == "drive_match_log.ndjson" ||
                    name == "tsr_log.ndjson" || name.hasSuffix("_drive_match_log.ndjson") ||
                    name.hasSuffix("_tsr_log.ndjson") else { return false }
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            return values.isRegularFile == true && values.isSymbolicLink != true
        }
    }

    static func totalBytes(in directory: URL) throws -> Int64 {
        try files(in: directory).reduce(0) { total, url in
            total + Int64(try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0)
        }
    }

    static func clear(in directory: URL) throws {
        for url in try files(in: directory) {
            try FileManager.default.removeItem(at: url)
        }
    }
}

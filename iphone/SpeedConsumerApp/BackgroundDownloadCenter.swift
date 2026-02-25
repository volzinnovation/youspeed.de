import CryptoKit
import Foundation

final class BackgroundDownloadCenter: NSObject, URLSessionDownloadDelegate, URLSessionTaskDelegate {
    static let sessionIdentifier = "de.youspeed.SpeedConsumer.background-downloads.v1"
    static let shared = BackgroundDownloadCenter()

    private struct ActiveDownload {
        let requestURL: URL
        let resumeKey: String
        let onProgress: (@Sendable (_ completedBytes: Int64, _ totalBytes: Int64?) -> Void)?
        let continuation: CheckedContinuation<(URL, URLResponse), Error>
    }

    private let lock = NSLock()
    private let resumeDataMaxAge: TimeInterval = 3 * 24 * 60 * 60
    private var activeDownloads: [Int: ActiveDownload] = [:]
    private var finishedFiles: [Int: URL] = [:]
    private var backgroundCompletionHandler: (() -> Void)?

    private override init() {
        super.init()
        pruneStaleResumeDataFiles()
    }

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: Self.sessionIdentifier)
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.waitsForConnectivity = true
        config.timeoutIntervalForRequest = 120
        config.timeoutIntervalForResource = 86_400
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    func download(
        request: URLRequest,
        requestURL: URL,
        onProgress: (@Sendable (_ completedBytes: Int64, _ totalBytes: Int64?) -> Void)? = nil
    ) async throws -> (URL, URLResponse) {
        try await withCheckedThrowingContinuation { continuation in
            let resumeKey = resumeDataKey(for: requestURL)
            let task: URLSessionDownloadTask
            if let resumeData = loadResumeData(forKey: resumeKey) {
                task = session.downloadTask(withResumeData: resumeData)
            } else {
                task = session.downloadTask(with: request)
            }
            lock.lock()
            activeDownloads[task.taskIdentifier] = ActiveDownload(
                requestURL: requestURL,
                resumeKey: resumeKey,
                onProgress: onProgress,
                continuation: continuation
            )
            lock.unlock()
            onProgress?(0, nil)
            task.resume()
        }
    }

    func handleEventsForBackgroundURLSession(identifier: String, completionHandler: @escaping () -> Void) {
        guard identifier == Self.sessionIdentifier else {
            completionHandler()
            return
        }
        lock.lock()
        backgroundCompletionHandler = completionHandler
        lock.unlock()
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        let callback: (@Sendable (_ completedBytes: Int64, _ totalBytes: Int64?) -> Void)?
        lock.lock()
        callback = activeDownloads[downloadTask.taskIdentifier]?.onProgress
        lock.unlock()
        let expected = totalBytesExpectedToWrite > 0 ? totalBytesExpectedToWrite : nil
        callback?(max(0, totalBytesWritten), expected)
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        let retainedURL = FileManager.default.temporaryDirectory.appendingPathComponent("bgdownload-\(UUID().uuidString).tmp")
        do {
            if FileManager.default.fileExists(atPath: retainedURL.path) {
                try FileManager.default.removeItem(at: retainedURL)
            }
            try FileManager.default.moveItem(at: location, to: retainedURL)
            lock.lock()
            finishedFiles[downloadTask.taskIdentifier] = retainedURL
            lock.unlock()
        } catch {
            lock.lock()
            finishedFiles.removeValue(forKey: downloadTask.taskIdentifier)
            lock.unlock()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let active: ActiveDownload?
        let downloadedFile: URL?
        lock.lock()
        active = activeDownloads.removeValue(forKey: task.taskIdentifier)
        downloadedFile = finishedFiles.removeValue(forKey: task.taskIdentifier)
        lock.unlock()

        guard let active else {
            if let downloadedFile {
                try? FileManager.default.removeItem(at: downloadedFile)
            }
            return
        }

        if let error {
            persistResumeDataIfAvailable(error: error, resumeKey: active.resumeKey)
            if let downloadedFile {
                try? FileManager.default.removeItem(at: downloadedFile)
            }
            active.continuation.resume(throwing: error)
            return
        }

        guard let response = task.response else {
            if let downloadedFile {
                try? FileManager.default.removeItem(at: downloadedFile)
            }
            active.continuation.resume(
                throwing: URLError(
                    .badServerResponse,
                    userInfo: [NSLocalizedDescriptionKey: "Missing response for \(active.requestURL.absoluteString)"]
                )
            )
            return
        }

        guard let downloadedFile else {
            active.continuation.resume(
                throwing: URLError(
                    .cannotOpenFile,
                    userInfo: [NSLocalizedDescriptionKey: "Missing temporary file for \(active.requestURL.absoluteString)"]
                )
            )
            return
        }

        removeResumeData(forKey: active.resumeKey)
        active.onProgress?(max(0, task.countOfBytesReceived), task.countOfBytesExpectedToReceive > 0 ? task.countOfBytesExpectedToReceive : nil)
        active.continuation.resume(returning: (downloadedFile, response))
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        let handler: (() -> Void)?
        lock.lock()
        handler = backgroundCompletionHandler
        backgroundCompletionHandler = nil
        lock.unlock()
        guard let handler else {
            return
        }
        DispatchQueue.main.async {
            handler()
        }
    }

    private func resumeDataDirectoryURL() -> URL? {
        do {
            let root = try V3BundleManager.applicationSupportDirectory(fileManager: .default)
            let dir = root.appendingPathComponent("download-resume", isDirectory: true)
            if !FileManager.default.fileExists(atPath: dir.path) {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            }
            return dir
        } catch {
            return nil
        }
    }

    private func resumeDataFileURL(forKey key: String) -> URL? {
        resumeDataDirectoryURL()?.appendingPathComponent("\(key).resume")
    }

    private func resumeDataKey(for requestURL: URL) -> String {
        let digest = SHA256.hash(data: Data(requestURL.absoluteString.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    private func loadResumeData(forKey key: String) -> Data? {
        guard let url = resumeDataFileURL(forKey: key),
              FileManager.default.fileExists(atPath: url.path) else {
            return nil
        }
        return try? Data(contentsOf: url)
    }

    private func removeResumeData(forKey key: String) {
        guard let url = resumeDataFileURL(forKey: key),
              FileManager.default.fileExists(atPath: url.path) else {
            return
        }
        try? FileManager.default.removeItem(at: url)
    }

    private func persistResumeDataIfAvailable(error: Error, resumeKey: String) {
        let nsError = error as NSError
        guard let resumeData = nsError.userInfo[NSURLSessionDownloadTaskResumeData] as? Data,
              !resumeData.isEmpty,
              let resumeURL = resumeDataFileURL(forKey: resumeKey) else {
            if nsError.domain == NSURLErrorDomain {
                removeResumeData(forKey: resumeKey)
            }
            return
        }
        do {
            try resumeData.write(to: resumeURL, options: .atomic)
        } catch {
            try? FileManager.default.removeItem(at: resumeURL)
        }
    }

    private func pruneStaleResumeDataFiles() {
        guard let dir = resumeDataDirectoryURL() else {
            return
        }
        let threshold = Date().addingTimeInterval(-resumeDataMaxAge)
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.contentModificationDateKey, .isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            return
        }

        for file in files {
            let values = try? file.resourceValues(forKeys: [.contentModificationDateKey, .isRegularFileKey])
            guard values?.isRegularFile == true else {
                continue
            }
            let modifiedAt = values?.contentModificationDate ?? .distantPast
            if modifiedAt < threshold {
                try? FileManager.default.removeItem(at: file)
            }
        }
    }
}

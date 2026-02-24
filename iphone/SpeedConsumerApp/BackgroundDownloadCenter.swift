import Foundation

final class BackgroundDownloadCenter: NSObject, URLSessionDownloadDelegate, URLSessionTaskDelegate {
    static let sessionIdentifier = "de.youspeed.SpeedConsumer.background-downloads.v1"
    static let shared = BackgroundDownloadCenter()

    private struct ActiveDownload {
        let requestURL: URL
        let onProgress: (@Sendable (_ completedBytes: Int64, _ totalBytes: Int64?) -> Void)?
        let continuation: CheckedContinuation<(URL, URLResponse), Error>
    }

    private let lock = NSLock()
    private var activeDownloads: [Int: ActiveDownload] = [:]
    private var finishedFiles: [Int: URL] = [:]
    private var backgroundCompletionHandler: (() -> Void)?

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
            let task = session.downloadTask(with: request)
            lock.lock()
            activeDownloads[task.taskIdentifier] = ActiveDownload(
                requestURL: requestURL,
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
}

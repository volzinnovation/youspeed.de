import Foundation

/// Independent anonymous startup fetch; never shares an upload retry queue or camera executor.
final class SignCollectionInterestHTTP: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    struct Response { let status: Int; let data: Data; let retryAfter: String? }
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil; config.httpCookieStorage = nil; config.httpShouldSetCookies = false
        config.timeoutIntervalForRequest = 15; config.timeoutIntervalForResource = 30
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()
    func fetch(etag: String?) async throws -> Response {
        var request = URLRequest(url: URL(string: SignCollectionHTTPClient.defaultBaseURL + "/crop-interest")!)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        if let etag { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        let (bytes, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.expectedContentLength <= Int64(SignCollectionInterestPlan.maximumBytes) else { throw SignCollectionError.invalidContract }
        var data = Data()
        if response.statusCode == 200 {
            guard response.mimeType == "application/json" else { throw SignCollectionError.invalidContract }
            for try await byte in bytes {
                try Task.checkCancellation()
                guard data.count < SignCollectionInterestPlan.maximumBytes else { throw SignCollectionError.capacity }
                data.append(byte)
            }
        }
        return Response(status: response.statusCode, data: data, retryAfter: response.value(forHTTPHeaderField: "Retry-After"))
    }
    func close() { session.invalidateAndCancel() }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

import Foundation

protocol PanoramaxUploadTransport: Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
    func upload(for request: URLRequest, fromFile fileURL: URL) async throws -> (Data, URLResponse)
}

struct URLSessionPanoramaxUploadTransport: PanoramaxUploadTransport, @unchecked Sendable {
    static let shared = URLSessionPanoramaxUploadTransport(session: .shared)

    let session: URLSession

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await session.data(for: request)
    }

    func upload(for request: URLRequest, fromFile fileURL: URL) async throws -> (Data, URLResponse) {
        try await session.upload(for: request, fromFile: fileURL)
    }
}

/// Bounds simultaneous file uploads across every active batch. A waiter owns
/// no remote outcome until it receives a permit, and cancellation removes it
/// from the FIFO without consuming a slot.
actor PanoramaxUploadLimiter {
    static let shared = PanoramaxUploadLimiter(limit: 2)

    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<UUID, Error>
    }

    private let limit: Int
    private var activePermitIDs: Set<UUID> = []
    private var waiters: [Waiter] = []

    var waitingRequestCount: Int { waiters.count }

    init(limit: Int) {
        precondition(limit > 0)
        self.limit = limit
    }

    func acquire() async throws -> UUID {
        try Task.checkCancellation()
        let id = UUID()
        if activePermitIDs.count < limit {
            activePermitIDs.insert(id)
            return id
        }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                if Task.isCancelled {
                    continuation.resume(throwing: CancellationError())
                } else {
                    waiters.append(Waiter(id: id, continuation: continuation))
                }
            }
        } onCancel: {
            Task { await self.cancelWaiter(id: id) }
        }
    }

    func release(_ id: UUID) {
        guard activePermitIDs.remove(id) != nil else { return }
        guard !waiters.isEmpty else { return }
        let next = waiters.removeFirst()
        activePermitIDs.insert(next.id)
        next.continuation.resume(returning: next.id)
    }

    private func cancelWaiter(id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else { return }
        let waiter = waiters.remove(at: index)
        waiter.continuation.resume(throwing: CancellationError())
    }
}

struct PanoramaxUploadProgress: Equatable, Sendable {
    enum Phase: Equatable, Sendable {
        case preparing
        case uploading
        case processing
        case stopping
    }

    let completedItems: Int
    let totalItems: Int
    let phase: Phase

    var fractionCompleted: Double {
        guard totalItems > 0 else { return 0 }
        return min(max(Double(completedItems) / Double(totalItems), 0), 1)
    }
}

struct PanoramaxUploadSetStatus: Decodable {
    let id: String
    let status: String?
    let state: String?
    let ready: Bool?

    var isReady: Bool {
        if ready == true { return true }
        let value = (status ?? state ?? "").lowercased()
        return ["ready", "complete", "completed", "finished"].contains(value)
    }

    private enum CodingKeys: String, CodingKey { case id, status, state, ready }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        if let string = try? container.decode(String.self, forKey: .id) {
            id = string
        } else if let number = try? container.decode(Int.self, forKey: .id) {
            id = String(number)
        } else {
            throw DecodingError.dataCorruptedError(forKey: .id, in: container, debugDescription: "Missing upload-set id")
        }
        status = try container.decodeIfPresent(String.self, forKey: .status)
        state = try container.decodeIfPresent(String.self, forKey: .state)
        ready = try container.decodeIfPresent(Bool.self, forKey: .ready)
    }
}

/// Small, explicit client for the Panoramax upload-set API. It deliberately
/// accepts a token as an argument so credentials never get persisted in queue
/// records or request logs.
struct PanoramaxUploadClient {
    enum UploadError: LocalizedError {
        case invalidResponse
        case httpStatus(Int)
        case missingUploadSetID
        case timedOut

        var errorDescription: String? {
            switch self {
            case .invalidResponse: return "Ungueltige Antwort der Panoramax-Instanz"
            case .httpStatus(let status): return "HTTP \(status)"
            case .missingUploadSetID: return "Panoramax hat keine Upload-ID geliefert"
            case .timedOut: return "Panoramax verarbeitet den Upload noch"
            }
        }
    }

    let origin: URL
    let token: String
    private let transport: any PanoramaxUploadTransport
    private let uploadLimiter: PanoramaxUploadLimiter

    init(
        origin: URL,
        token: String,
        transport: any PanoramaxUploadTransport = URLSessionPanoramaxUploadTransport.shared,
        uploadLimiter: PanoramaxUploadLimiter = .shared
    ) {
        self.origin = origin
        self.token = token
        self.transport = transport
        self.uploadLimiter = uploadLimiter
    }

    /// A cancelled or transport-lost request may have reached the server even
    /// when the client never received its response. Keep that item out of
    /// automatic retries; only failures with a definitive HTTP response (or a
    /// local preparation failure) are retryable without duplicate risk.
    static func durableItemStateAfterUploadFailure(
        _ error: Error,
        taskIsCancelled: Bool
    ) -> PanoramaxItemState {
        if taskIsCancelled || error is CancellationError || error is URLError {
            return .abandoned
        }
        if let uploadError = error as? UploadError {
            switch uploadError {
            case .invalidResponse, .timedOut:
                return .abandoned
            case .httpStatus, .missingUploadSetID:
                return .retryableError
            }
        }
        return .retryableError
    }

    func createUploadSet(title: String, estimatedFileCount: Int) async throws -> PanoramaxUploadSetStatus {
        var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets"))
        request.httpMethod = "POST"
        applyAuth(to: &request)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let payload: [String: Any] = [
            "title": title,
            "estimated_nb_files": max(estimatedFileCount, 1)
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await transport.data(for: request)
        try validate(response)
        return try JSONDecoder().decode(PanoramaxUploadSetStatus.self, from: data)
    }

    func upload(
        file: URL,
        uploadSetID: String,
        fileName: String,
        beforeRequest: @escaping @Sendable () async throws -> Void = {}
    ) async throws {
        let permitID = try await uploadLimiter.acquire()
        do {
            try Task.checkCancellation()
            try await uploadWithPermit(
                file: file,
                uploadSetID: uploadSetID,
                fileName: fileName,
                beforeRequest: beforeRequest
            )
            await uploadLimiter.release(permitID)
        } catch {
            await uploadLimiter.release(permitID)
            throw error
        }
    }

    private func uploadWithPermit(
        file: URL,
        uploadSetID: String,
        fileName: String,
        beforeRequest: @escaping @Sendable () async throws -> Void
    ) async throws {
        let boundary = "YouSpeed-\(UUID().uuidString)"
        var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets/\(uploadSetID)/files"))
        request.httpMethod = "POST"
        applyAuth(to: &request)
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        // Keep memory bounded even when multiple batches are active: assemble
        // the multipart envelope into a temporary file in chunks, then let
        // URLSession stream that file. The helper removes it on success,
        // failure, and cancellation.
        try await Self.withMultipartBodyFile(file: file, fileName: fileName, boundary: boundary) { bodyFile in
            try Task.checkCancellation()
            // The caller persists `.uploading` here, after local preparation
            // and permit waiting but immediately before the transport boundary.
            // A cancelled pre-send attempt therefore remains safely queued.
            try await beforeRequest()
            let (_, response) = try await transport.upload(for: request, fromFile: bodyFile)
            try validate(response)
        }
    }

    func complete(uploadSetID: String) async throws -> PanoramaxUploadSetStatus {
        var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets/\(uploadSetID)/complete"))
        request.httpMethod = "POST"
        applyAuth(to: &request)
        let (data, response) = try await transport.data(for: request)
        try validate(response)
        if data.isEmpty { return PanoramaxUploadSetStatus(id: uploadSetID, status: "processing", state: nil, ready: false) }
        return try JSONDecoder().decode(PanoramaxUploadSetStatus.self, from: data)
    }

    func pollUntilReady(uploadSetID: String, attempts: Int = 12) async throws -> PanoramaxUploadSetStatus {
        var latest: PanoramaxUploadSetStatus?
        for attempt in 0..<max(attempts, 1) {
            var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets/\(uploadSetID)"))
            applyAuth(to: &request)
            let (data, response) = try await transport.data(for: request)
            try validate(response)
            let status = try JSONDecoder().decode(PanoramaxUploadSetStatus.self, from: data)
            latest = status
            if status.isReady { return status }
            if attempt + 1 < attempts { try await Task.sleep(for: .seconds(2)) }
        }
        _ = latest
        throw UploadError.timedOut
    }

    private func applyAuth(to request: inout URLRequest) {
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
    }

    private func validate(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { throw UploadError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else { throw UploadError.httpStatus(http.statusCode) }
    }

    static func withMultipartBodyFile<T>(
        file: URL,
        fileName: String,
        boundary: String,
        operation: (URL) async throws -> T
    ) async throws -> T {
        let preparation = Task.detached(priority: .utility) {
            try makeMultipartBodyFile(file: file, fileName: fileName, boundary: boundary)
        }
        let bodyFile = try await withTaskCancellationHandler {
            try await preparation.value
        } onCancel: {
            preparation.cancel()
        }
        defer { try? FileManager.default.removeItem(at: bodyFile) }
        try Task.checkCancellation()
        return try await operation(bodyFile)
    }

    private static func makeMultipartBodyFile(file: URL, fileName: String, boundary: String) throws -> URL {
        try Task.checkCancellation()
        let safeFileName = fileName
            .replacingOccurrences(of: "\r", with: "_")
            .replacingOccurrences(of: "\n", with: "_")
            .replacingOccurrences(of: "\"", with: "_")
        let temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("YouSpeedPanoramaxMultipart", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
        let bodyFile = temporaryDirectory.appendingPathComponent("\(UUID().uuidString).multipart")
        guard FileManager.default.createFile(atPath: bodyFile.path, contents: nil) else {
            throw CocoaError(.fileWriteUnknown)
        }

        do {
            let input = try FileHandle(forReadingFrom: file)
            let output = try FileHandle(forWritingTo: bodyFile)
            defer {
                try? input.close()
                try? output.close()
            }
            try output.write(contentsOf: Data("--\(boundary)\r\n".utf8))
            try output.write(contentsOf: Data(
                "Content-Disposition: form-data; name=\"file\"; filename=\"\(safeFileName)\"\r\n".utf8
            ))
            try output.write(contentsOf: Data("Content-Type: image/jpeg\r\n\r\n".utf8))
            while let chunk = try input.read(upToCount: 1_048_576), !chunk.isEmpty {
                try Task.checkCancellation()
                try output.write(contentsOf: chunk)
            }
            try Task.checkCancellation()
            try output.write(contentsOf: Data("\r\n--\(boundary)--\r\n".utf8))
            try output.synchronize()
            return bodyFile
        } catch {
            try? FileManager.default.removeItem(at: bodyFile)
            throw error
        }
    }
}

private extension PanoramaxUploadSetStatus {
    init(id: String, status: String?, state: String?, ready: Bool?) {
        self.id = id
        self.status = status
        self.state = state
        self.ready = ready
    }
}

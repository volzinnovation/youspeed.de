import Foundation

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
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        return try JSONDecoder().decode(PanoramaxUploadSetStatus.self, from: data)
    }

    func upload(file: URL, uploadSetID: String, fileName: String) async throws {
        let boundary = "YouSpeed-\(UUID().uuidString)"
        var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets/\(uploadSetID)/files"))
        request.httpMethod = "POST"
        applyAuth(to: &request)
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let bytes = try Data(contentsOf: file, options: .mappedIfSafe)
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".utf8))
        body.append(Data("Content-Type: image/jpeg\r\n\r\n".utf8))
        body.append(bytes)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        request.httpBody = body
        let (_, response) = try await URLSession.shared.data(for: request)
        try validate(response)
    }

    func complete(uploadSetID: String) async throws -> PanoramaxUploadSetStatus {
        var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets/\(uploadSetID)/complete"))
        request.httpMethod = "POST"
        applyAuth(to: &request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        if data.isEmpty { return PanoramaxUploadSetStatus(id: uploadSetID, status: "processing", state: nil, ready: false) }
        return try JSONDecoder().decode(PanoramaxUploadSetStatus.self, from: data)
    }

    func pollUntilReady(uploadSetID: String, attempts: Int = 12) async throws -> PanoramaxUploadSetStatus {
        var latest: PanoramaxUploadSetStatus?
        for attempt in 0..<max(attempts, 1) {
            var request = URLRequest(url: origin.appendingPathComponent("api/upload_sets/\(uploadSetID)"))
            applyAuth(to: &request)
            let (data, response) = try await URLSession.shared.data(for: request)
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
}

private extension PanoramaxUploadSetStatus {
    init(id: String, status: String?, state: String?, ready: Bool?) {
        self.id = id
        self.status = status
        self.state = state
        self.ready = ready
    }
}

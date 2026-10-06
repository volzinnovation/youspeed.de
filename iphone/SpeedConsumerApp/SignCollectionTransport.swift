import Foundation

struct SignCollectionCapabilities {
    static let metadataDisclosure = "youspeed-camera-use-pilot-1"
    static let cropDisclosure = "youspeed-crop-storage-pilot-1"
    let metadataBytes: Int
    let eventBytes: Int
    let mediaBytes: Int
    let disclosures: [String: [String]]

    init(_ value: [String: Any]) throws {
        guard let limits = value["limits"] as? [String: Any],
              let metadata = SignCollectionJSON.integer(limits["metadata_bytes"]), metadata > 0, metadata <= 512 * 1024,
              let event = SignCollectionJSON.integer(limits["event_bytes"]), event > 0, event <= SignCollectionStore.maximumEventBytes,
              let versions = value["disclosure_versions"] as? [String: [String]],
              versions["sign_metadata"]?.contains(Self.metadataDisclosure) == true else { throw SignCollectionError.invalidContract }
        metadataBytes = metadata; eventBytes = event; disclosures = versions
        mediaBytes = min(5 * 1024 * 1024, max(0, SignCollectionJSON.integer(limits["media_bytes"]) ?? 0))
    }

    func accepts(_ claim: Any?) -> Bool {
        guard let claim = claim as? [String: Any], let scope = claim["scope"] as? String,
              let version = claim["disclosure_version"] as? String else { return false }
        return disclosures[scope]?.contains(version) == true
    }
}

struct SignCollectionHTTPResponse {
    let status: Int
    let body: [String: Any]
    let retryAfter: String?
}

protocol SignCollectionRequesting {
    func request(path: String, body: String?) async throws -> SignCollectionHTTPResponse
    func captureCrop(metadata: String, bytes: Data) async throws -> SignCollectionHTTPResponse
}
extension SignCollectionRequesting {
    func captureCrop(metadata: String, bytes: Data) async throws -> SignCollectionHTTPResponse { throw SignCollectionError.invalidContract }
}

/// Ephemeral, anonymous HTTP. No cookies, authentication or redirects carrying receipts.
final class SignCollectionHTTPClient: NSObject, SignCollectionRequesting, URLSessionTaskDelegate, @unchecked Sendable {
    static let defaultBaseURL = "https://live-eu.woladen.de/youspeed/v1"
    private let base: URL
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil; configuration.httpShouldSetCookies = false
        configuration.timeoutIntervalForRequest = 30; configuration.timeoutIntervalForResource = 45
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()
    init(baseURL: String = defaultBaseURL) throws {
        guard let url = URL(string: baseURL), url.scheme == "https", url.host != nil,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil else { throw SignCollectionError.invalidContract }
        base = url; super.init()
    }
    func request(path: String, body: String?) async throws -> SignCollectionHTTPResponse {
        guard !path.contains("/"), !path.contains("?"), !path.isEmpty else { throw SignCollectionError.invalidContract }
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = body == nil ? "GET" : "POST"
        request.httpBody = body.map { Data($0.utf8) }
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("identity", forHTTPHeaderField: "Content-Encoding")
        request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        return try await send(request)
    }
    func captureCrop(metadata: String, bytes: Data) async throws -> SignCollectionHTTPResponse {
        let json = Data(metadata.utf8), length = json.count
        guard length > 0, length <= 16384, bytes.count <= 5 * 1024 * 1024 else { throw SignCollectionError.capacity }
        var body = Data([UInt8((length >> 24) & 255), UInt8((length >> 16) & 255), UInt8((length >> 8) & 255), UInt8(length & 255)])
        body.append(json); body.append(bytes)
        var request = URLRequest(url: base.appendingPathComponent("capture-crops"))
        request.httpMethod = "POST"; request.httpBody = body
        request.setValue("application/vnd.youspeed.crop", forHTTPHeaderField: "Content-Type")
        return try await send(request)
    }
    private func send(_ request: URLRequest) async throws -> SignCollectionHTTPResponse {
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard data.count <= 512 * 1024, let response = response as? HTTPURLResponse else { throw SignCollectionError.invalidReceipt }
        let value = (try? SignCollectionJSON.parse(String(decoding: data, as: UTF8.self))) as? [String: Any]
        guard request.url?.lastPathComponent.hasPrefix("capture-") == true || response.statusCode == 204 || !(200..<300).contains(response.statusCode) || value != nil else { throw SignCollectionError.invalidReceipt }
        return SignCollectionHTTPResponse(status: response.statusCode, body: value ?? [:], retryAfter: response.value(forHTTPHeaderField: "Retry-After"))
    }
    func close() { session.invalidateAndCancel() }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

/// One-way metadata/control uploads with explicit captured authorization.
/// Camera processing is independent of delivery and server feature flags.
actor SignCollectionUploadWorker {
    private let store: SignCollectionStore
    private let client: SignCollectionRequesting
    private let now: () -> Date
    private let jitter: () -> Double
    private var running = false
    private var pollOffset = 0
    private var failures = 0
    private var mediaFailures = 0
    private var cachedCapabilities: SignCollectionCapabilities?
    private var capabilitiesUntil = Date.distantPast
    init(store: SignCollectionStore, client: SignCollectionRequesting, now: @escaping () -> Date = Date.init, jitter: @escaping () -> Double = { Double.random(in: 0...1) }) {
        self.store = store; self.client = client; self.now = now; self.jitter = jitter
    }
    func capabilities() async throws -> SignCollectionCapabilities {
        if let cachedCapabilities, capabilitiesUntil > now() { return cachedCapabilities }
        let response = try await client.request(path: "capabilities", body: nil)
        guard response.status == 200 else { throw SignCollectionError.invalidContract }
        let value = try SignCollectionCapabilities(response.body)
        cachedCapabilities = value; capabilitiesUntil = now().addingTimeInterval(300)
        return value
    }

    func retryDelay() throws -> TimeInterval {
        max(1, max(try store.transportRetryDate(), try store.cropRetryDate()).timeIntervalSince(now()))
    }

    /// Call on foreground/resume and a bounded timer. Never sleep a camera thread.
    func runOnce(networkAvailable: Bool, ordinaryDeliveryAllowed: Bool) async throws -> String {
        guard !running else { return "busy" }
        guard networkAvailable else { return "offline" }
        if try store.pendingControls().isEmpty {
            guard ordinaryDeliveryAllowed else { return "contribution_paused" }
        }
        guard try store.transportRetryDate() <= now() else { return "backoff" }
        running = true; defer { running = false }
        var attemptedBatch: String?
        do {
            let capabilities = try await capabilities()
            // Unsent local controls first; the active deletion always leads.
            for _ in 0..<2 {
                let pending = try store.pendingControls()
                let selected = try store.deletionIsPending ? pending.first : pending.first(where: { $0.receipt == nil && $0.response?["client_error"] == nil })
                guard let control = selected, control.receipt == nil, control.response?["client_error"] == nil else { break }
                if control.kind == "consent" {
                    let body = try SignCollectionJSON.parse(control.body) as! [String: Any]
                    if !capabilities.accepts(body["collection_authorization"]) { try store.quarantineControl(id: control.id, code: "disclosure_version_unrecognized"); continue }
                }
                let response = try await client.request(path: control.kind == "deletion" ? "observation-deletions" : "consent-events", body: control.body)
                if !(200..<300).contains(response.status) { return try handle(response, control: control.id) }
                try store.applyControlReceipt(id: control.id, response: response.body)
            }
            var polls = try store.pendingControls().filter { $0.receipt != nil && $0.response?["client_error"] == nil }
            if try store.deletionIsPending, let barrier = polls.first {
                let body = try SignCollectionJSON.canonical(["operation_receipt": barrier.receipt!])
                let response = try await client.request(path: "operation-status", body: body)
                if !(200..<300).contains(response.status) { return try handle(response, control: barrier.id) }
                try store.applyControlReceipt(id: barrier.id, response: response.body); polls.removeFirst()
            }
            if !polls.isEmpty {
                for index in 0..<min(4, polls.count) {
                    let control = polls[(pollOffset + index) % polls.count]
                    let body = try SignCollectionJSON.canonical(["operation_receipt": control.receipt!])
                    let response = try await client.request(path: "operation-status", body: body)
                    if !(200..<300).contains(response.status) { return try handle(response, control: control.id) }
                    try store.applyControlReceipt(id: control.id, response: response.body)
                }
                pollOffset = (pollOffset + min(4, polls.count)) % polls.count
            }
            guard try !store.deletionIsPending else { return "deletion_pending" }
            guard ordinaryDeliveryAllowed else { return "contribution_paused" }
            guard try store.ordinaryRetryDate() <= now() else { return "deletion_pending" }
            try store.expireCrops()
            var result = "idle"
            if let batch = try store.prepareBatch(maxEvents: 100, maxBytes: capabilities.metadataBytes) {
            let envelope = try SignCollectionJSON.parse(batch.body) as! [String: Any]
            guard capabilities.accepts(envelope["collection_authorization"]) else { return "disclosure_update_required" }
            let events = envelope["events"] as! [[String: Any]]
            if batch.body.utf8.count > capabilities.metadataBytes || events.count > 100 { try store.splitBatch(id: batch.id); return "batch_split" }
            let path = ["sighting":"capture-sightings", "correction":"capture-corrections", "media_status":"capture-media-status"][batch.kind]!
            attemptedBatch = batch.id
            let response = try await client.request(path: path, body: batch.body)
            attemptedBatch = nil
            if !(200..<300).contains(response.status) {
                if try (response.status < 500 && ![408,429].contains(response.status)) || (store.recordBestEffortFailure(id: batch.id) >= 3) {
                    try store.finishBestEffortBatch(id: batch.id, dropped: true); return "metadata_dropped"
                }
                return try handle(response, batch: batch.id)
            }
            try store.finishBestEffortBatch(id: batch.id)
            failures = 0
                result = "metadata_sent"
            }
            // Drain a bounded group independently of the camera.
            do {
                for _ in 0..<8 {
                    try Task.checkCancellation()
                    guard let cropResult = try await sendCrop(capabilities) else { break }
                    result = cropResult
                    if cropResult != "crop_sent" { break }
                }
                return result
            }
            catch is CancellationError { throw CancellationError() }
            catch {
                mediaFailures += 1
                try store.deferCrop(until: now().addingTimeInterval(min(300, pow(2, Double(min(mediaFailures, 8)))) + jitter()))
                return "crop_delivery_unavailable"
            }
        } catch is CancellationError { throw CancellationError() }
        catch {
            if let attemptedBatch, try store.recordBestEffortFailure(id: attemptedBatch) >= 3 {
                try store.finishBestEffortBatch(id: attemptedBatch, dropped: true); return "metadata_dropped"
            }
            failures += 1
            try store.deferTransport(until: now().addingTimeInterval(min(300, pow(2, Double(min(failures, 8)))) + jitter()))
            throw error
        }
    }

    private func sendCrop(_ capabilities: SignCollectionCapabilities) async throws -> String? {
        guard try store.cropRetryDate() <= now() else { return "backoff" }
        guard let crop = try store.nextCrop() else { return nil }
        guard crop.bytes.count <= capabilities.mediaBytes else { try store.finishBestEffortCrop(id: crop.id, dropped: true); return "crop_dropped" }
        do {
            let response = try await client.captureCrop(metadata: crop.metadata, bytes: crop.bytes)
            if (200..<300).contains(response.status) {
                try store.finishBestEffortCrop(id: crop.id); mediaFailures = 0; return "crop_sent"
            }
            if try (response.status < 500 && ![408,429].contains(response.status)) || (store.recordBestEffortFailure(id: crop.id) >= 3) {
                try store.finishBestEffortCrop(id: crop.id, dropped: true); return "crop_dropped"
            }
            return try handle(response, crop: crop.id)
        } catch is CancellationError { throw CancellationError() }
        catch {
            if try store.recordBestEffortFailure(id: crop.id) >= 3 {
                try store.finishBestEffortCrop(id: crop.id, dropped: true); return "crop_dropped"
            }
            throw error
        }
    }

    private func handle(_ response: SignCollectionHTTPResponse, batch: String? = nil, control: String? = nil, crop: String? = nil) throws -> String {
        let raw = response.body["code"] as? String ?? response.body["error"] as? String ?? "server_rejected"
        let code = raw.range(of: "^[a-z][a-z0-9_]{0,79}$", options: .regularExpression) == nil ? "server_rejected" : raw
        if response.status == 413, let batch { try store.splitBatch(id: batch); return "batch_split" }
        if response.status == 409 && code == "deletion_pending" {
            try store.deferOrdinary(until: now().addingTimeInterval(60)); return "deletion_pending"
        }
        if response.status == 429 || response.status >= 500 || response.status == 408 {
            if crop != nil { mediaFailures += 1 } else { failures += 1 }
            var delay = min(300, pow(2, Double(min(crop != nil ? mediaFailures : failures, 8))))
            if let header = response.retryAfter {
                if let seconds = Double(header), seconds.isFinite { delay = max(delay, seconds) }
                else {
                    let parser = DateFormatter(); parser.locale = Locale(identifier: "en_US_POSIX"); parser.timeZone = TimeZone(secondsFromGMT: 0); parser.dateFormat = "EEE, dd MMM yyyy HH:mm:ss z"
                    if let date = parser.date(from: header) { delay = max(delay, date.timeIntervalSince(now())) }
                }
            }
            if crop != nil { try store.deferCrop(until: now().addingTimeInterval(delay + jitter())) }
            else { try store.deferTransport(until: now().addingTimeInterval(delay + jitter())) }
            return "backoff"
        }
        if let crop { try store.discardCrop(id: crop, status: code == "media_expired" ? "expired" : "missing") }
        if let batch { try store.quarantineBatch(id: batch, code: code) }
        if let control { try store.quarantineControl(id: control, code: code) }
        return "quarantined"
    }
}

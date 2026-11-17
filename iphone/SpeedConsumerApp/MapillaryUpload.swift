import Foundation
import CryptoKit
import ImageIO
import Security

enum MapillaryUploadError: LocalizedError {
    case account, image, response, http(Int), paused, alreadyUploaded
    var errorDescription: String? {
        switch self {
        case .account: return mly("account_required")
        case .image: return mly("image_error")
        case .response: return mly("response_error")
        case .http(let code): return code == 401 || code == 403 ? mly("account_required") : "\(mly("http_error")) (\(code))"
        case .paused: return mly("paused")
        case .alreadyUploaded: return mly("already_uploaded")
        }
    }
}

func mly(_ key: String) -> String { NSLocalizedString("mapillary.\(key)", comment: "") }

protocol MapillaryHTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

private final class MapillaryNoRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest) async -> URLRequest? { nil }
}

struct MapillaryURLTransport: MapillaryHTTPTransport {
    private let session: URLSession
    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 300
        session = URLSession(configuration: config, delegate: MapillaryNoRedirects(), delegateQueue: nil)
    }
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw MapillaryUploadError.response }
        return (data, response)
    }
}

struct MapillaryUploadClient: Sendable {
    let transport: any MapillaryHTTPTransport
    init(transport: any MapillaryHTTPTransport = MapillaryURLTransport()) { self.transport = transport }

    func profile(token: String) async throws -> (id: String, username: String) {
        let data = try await request("https://graph.mapillary.com/me?fields=id,username", token: token)
        guard let id = data["id"] as? String, !id.isEmpty,
              let username = data["username"] as? String, !username.isEmpty else { throw MapillaryUploadError.account }
        return (id, username)
    }

    func upload(_ bytes: Data, sessionKey: String, token: String,
                allowed: @Sendable () async -> Bool = { true }) async throws -> String {
        guard sessionKey.range(of: "^[a-zA-Z0-9_.-]+$", options: .regularExpression) != nil else {
            throw MapillaryUploadError.image
        }
        let url = "https://rupload.facebook.com/mapillary_public_uploads/\(sessionKey)"
        var lastError: Error = MapillaryUploadError.response
        for attempt in 0..<3 {
            try Task.checkCancellation()
            guard await allowed() else { throw MapillaryUploadError.paused }
            do {
                let status = try await request(url, token: token)
                guard let value = status["offset"] as? NSNumber,
                      CFGetTypeID(value) != CFBooleanGetTypeID(),
                      value.doubleValue.rounded() == value.doubleValue,
                      value.intValue >= 0, value.intValue <= bytes.count else { throw MapillaryUploadError.response }
                guard await allowed() else { throw MapillaryUploadError.paused }
                let response = try await request(url, method: "POST", token: token,
                    body: bytes.subdata(in: value.intValue..<bytes.count), contentType: "application/octet-stream",
                    headers: ["Offset": String(value.intValue), "X-Entity-Name": sessionKey])
                guard let handle = response["h"] as? String, !handle.isEmpty else { throw MapillaryUploadError.response }
                return handle
            } catch let error as MapillaryUploadError {
                if case .http(let code) = error, code == 429 || code >= 500 { lastError = error }
                else { throw error }
            } catch let error as URLError {
                if error.code == .cancelled { throw error }
                lastError = error
            }
            if attempt < 2 { try await Task.sleep(for: .seconds(attempt + 1)) }
        }
        throw lastError
    }

    func finish(handle: String, token: String) async throws -> String {
        let body = try JSONSerialization.data(withJSONObject: ["file_handle": handle, "file_type": "mly_bundle_manifest"])
        let data = try await request("https://graph.mapillary.com/finish_upload", method: "POST", token: token,
                                     body: body, contentType: "application/json")
        if let id = data["cluster_id"] as? String, !id.isEmpty { return id }
        if let id = data["cluster_id"] as? NSNumber, CFGetTypeID(id) != CFBooleanGetTypeID(),
           id.doubleValue.isFinite, id.doubleValue > 0, id.doubleValue.rounded() == id.doubleValue { return id.stringValue }
        throw MapillaryUploadError.response
    }

    private func request(_ url: String, method: String = "GET", token: String, body: Data? = nil,
                         contentType: String? = nil, headers: [String: String] = [:]) async throws -> [String: Any] {
        guard !token.isEmpty, !token.contains("\r"), !token.contains("\n"), let url = URL(string: url),
              url.scheme == "https", ["graph.mapillary.com", "rupload.facebook.com"].contains(url.host) else {
            throw MapillaryUploadError.account
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("OAuth \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        for (key, value) in headers { request.setValue(value, forHTTPHeaderField: key) }
        let (bytes, response) = try await transport.send(request)
        guard (200..<300).contains(response.statusCode) else { throw MapillaryUploadError.http(response.statusCode) }
        guard bytes.count <= 4 * 1024 * 1024,
              let result = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else {
            throw MapillaryUploadError.response
        }
        return result
    }
}

struct MapillaryPhoto: @unchecked Sendable {
    let itemID: String
    let url: URL
    let metadata: PanoramaxCaptureMetadata
}

enum MapillaryImageMetadata {
    static func description(_ metadata: PanoramaxCaptureMetadata) throws -> [String: Any] {
        guard metadata.validate().isEmpty else { throw MapillaryUploadError.image }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy_MM_dd_HH_mm_ss_SSS"
        var value: [String: Any] = [
            "MAPLatitude": metadata.location.latitude, "MAPLongitude": metadata.location.longitude,
            "MAPCaptureTime": formatter.string(from: metadata.capturedAt),
            "MAPSequenceUUID": MapillaryUploadStore.hash(Data(metadata.captureSessionID.utf8)),
            "MAPGPSAccuracyMeters": metadata.location.accuracyMeters,
        ]
        if let altitude = metadata.location.altitudeMeters, altitude.isFinite { value["MAPAltitude"] = altitude }
        if let heading = metadata.location.headingDegrees, heading.isFinite, (0...360).contains(heading) {
            value["MAPCompassHeading"] = ["TrueHeading": heading.truncatingRemainder(dividingBy: 360),
                                          "MagneticHeading": heading.truncatingRemainder(dividingBy: 360)]
        }
        return value
    }

    static func prepared(_ photo: MapillaryPhoto) throws -> Data {
        let original = try Data(contentsOf: photo.url, options: .mappedIfSafe)
        guard original.count <= 32 * 1024 * 1024, Int64(original.count) == photo.metadata.byteSize,
              MapillaryUploadStore.hash(original) == photo.metadata.sha256.lowercased(),
              let source = CGImageSourceCreateWithData(original as CFData, nil),
              CGImageSourceGetType(source) as String? == "public.jpeg",
              var properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any] else {
            throw MapillaryUploadError.image
        }
        let json = try JSONSerialization.data(withJSONObject: description(photo.metadata), options: [.sortedKeys])
        var tiff = properties[kCGImagePropertyTIFFDictionary as String] as? [String: Any] ?? [:]
        tiff[kCGImagePropertyTIFFImageDescription as String] = String(decoding: json, as: UTF8.self)
        properties[kCGImagePropertyTIFFDictionary as String] = tiff
        var exif = properties[kCGImagePropertyExifDictionary as String] as? [String: Any] ?? [:]
        exif.removeValue(forKey: kCGImagePropertyExifUserComment as String)
        properties[kCGImagePropertyExifDictionary as String] = exif
        let bytes = NSMutableData()
        guard let output = CGImageDestinationCreateWithData(bytes, "public.jpeg" as CFString, 1, nil) else {
            throw MapillaryUploadError.image
        }
        CGImageDestinationAddImageFromSource(output, source, 0, properties as CFDictionary)
        guard CGImageDestinationFinalize(output) else { throw MapillaryUploadError.image }
        return bytes as Data
    }
}

struct MapillaryUploadJob: Codable, Identifiable, Sendable {
    struct Image: Codable, Sendable {
        let itemID: String
        let name: String
        var handle: String?
    }
    let id: String
    let userID: String
    var images: [Image]
    var manifestHandle: String?
    var clusterID: String?
}

actor MapillaryUploadStore {
    let root: URL
    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("YouSpeed/Mapillary", isDirectory: true)
    }
    nonisolated static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private func directory(_ jobID: String) -> URL { root.appendingPathComponent(jobID, isDirectory: true) }
    func pending(userID: String) -> [MapillaryUploadJob] {
        jobs(userID: userID).filter { $0.clusterID == nil }
    }
    func uploadedItemIDs(userID: String) -> Set<String> {
        Set(jobs(userID: userID).filter { $0.clusterID != nil }.flatMap { $0.images.map(\.itemID) })
    }
    private func jobs(userID: String) -> [MapillaryUploadJob] {
        let entries = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        return entries.compactMap { entry in
            guard let data = try? Data(contentsOf: entry.appendingPathComponent("job.json")),
                  let job = try? JSONDecoder().decode(MapillaryUploadJob.self, from: data),
                  job.userID == userID else { return nil }
            return job
        }.sorted { $0.id < $1.id }
    }
    func prepare(photos: [MapillaryPhoto], userID: String) throws -> MapillaryUploadJob {
        guard !photos.isEmpty else { throw MapillaryUploadError.image }
        let photos = photos.sorted { $0.metadata.capturedAt < $1.metadata.capturedAt }
        let keys = photos.map { $0.itemID + ":" + $0.metadata.sha256 }.sorted().joined(separator: "\n")
        let id = Self.hash(Data((userID + "\n" + keys).utf8))
        let folder = directory(id)
        if let data = try? Data(contentsOf: folder.appendingPathComponent("job.json")) {
            let job = try JSONDecoder().decode(MapillaryUploadJob.self, from: data)
            guard job.userID == userID else { throw MapillaryUploadError.account }
            return job
        }
        let uploaded = uploadedItemIDs(userID: userID)
        let remaining = photos.filter { !uploaded.contains($0.itemID) }
        guard !remaining.isEmpty else { throw MapillaryUploadError.alreadyUploaded }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        var excludedRoot = root
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try excludedRoot.setResourceValues(values)
        var images: [MapillaryUploadJob.Image] = []
        for photo in remaining {
            try Task.checkCancellation()
            let data = try MapillaryImageMetadata.prepared(photo)
            let name = Self.hash(data) + ".jpg"
            try data.write(to: folder.appendingPathComponent(name), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            images.append(.init(itemID: photo.itemID, name: name))
        }
        let job = MapillaryUploadJob(id: id, userID: userID, images: images)
        try save(job)
        return job
    }
    func save(_ job: MapillaryUploadJob) throws {
        try JSONEncoder().encode(job).write(to: directory(job.id).appendingPathComponent("job.json"),
                                          options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
    func bytes(jobID: String, name: String) throws -> Data {
        guard jobID.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              name.range(of: "^[a-f0-9]{64}\\.jpg$", options: .regularExpression) != nil else { throw MapillaryUploadError.image }
        let data = try Data(contentsOf: directory(jobID).appendingPathComponent(name))
        guard !data.isEmpty, data.count <= 33 * 1024 * 1024, Self.hash(data) + ".jpg" == name else {
            throw MapillaryUploadError.image
        }
        return data
    }
    func releaseImages(_ job: MapillaryUploadJob) {
        guard job.clusterID != nil else { return }
        for image in job.images { try? FileManager.default.removeItem(at: directory(job.id).appendingPathComponent(image.name)) }
    }
}

private enum MapillaryCredentials {
    static func query() -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "de.youspeed.mapillary",
         kSecAttrAccount as String: "upload"]
    }
    static func read() -> String? {
        var query = query(); query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &value) == errSecSuccess, let bytes = value as? Data else { return nil }
        return String(data: bytes, encoding: .utf8)
    }
    static func save(_ token: String) throws {
        var query = query()
        query[kSecValueData as String] = Data(token.utf8)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemDelete(self.query() as CFDictionary)
        guard SecItemAdd(query as CFDictionary, nil) == errSecSuccess else { throw MapillaryUploadError.account }
    }
    static func delete() { SecItemDelete(query() as CFDictionary) }
}

struct MapillaryUploadWorker: Sendable {
    let client: MapillaryUploadClient
    let store: MapillaryUploadStore
    func submit(_ original: MapillaryUploadJob, userID: String, token: String,
                allowed: @escaping @Sendable () async -> Bool = { true },
                progress: @escaping @Sendable (Int, Int, String) async -> Void = { _, _, _ in }) async throws {
        var job = original
        guard job.userID == userID else { throw MapillaryUploadError.account }
        if job.clusterID == nil {
            for index in job.images.indices {
                try Task.checkCancellation()
                guard await allowed() else { throw MapillaryUploadError.paused }
                if job.images[index].handle == nil {
                    await progress(index, job.images.count, "uploading")
                    let bytes = try await store.bytes(jobID: job.id, name: job.images[index].name)
                    job.images[index].handle = try await client.upload(bytes,
                        sessionKey: "youspeed_\(userID)_\(job.images[index].name)", token: token, allowed: allowed)
                    try await store.save(job)
                }
                await progress(index + 1, job.images.count, "uploading")
            }
            guard await allowed() else { throw MapillaryUploadError.paused }
            let bytes = try JSONSerialization.data(withJSONObject: ["version": "1", "upload_type": "images",
                "image_handles": job.images.compactMap(\.handle)], options: [.sortedKeys])
            if job.manifestHandle == nil {
                job.manifestHandle = try await client.upload(bytes,
                    sessionKey: "youspeed_\(userID)_\(MapillaryUploadStore.hash(bytes)).json", token: token, allowed: allowed)
                try await store.save(job)
            }
            guard await allowed() else { throw MapillaryUploadError.paused }
            try Task.checkCancellation()
            await progress(job.images.count, job.images.count, "submitting")
            job.clusterID = try await client.finish(handle: job.manifestHandle!, token: token)
            try await store.save(job)
            await store.releaseImages(job)
        }
        await progress(job.images.count, job.images.count, "submitted")
    }
}

@MainActor
final class MapillaryUploadModel: ObservableObject {
    @Published private(set) var username: String?
    @Published private(set) var isBusy = false
    @Published private(set) var isUploading = false
    @Published private(set) var completed = 0
    @Published private(set) var total = 0
    @Published private(set) var status = ""
    @Published private(set) var pending: [MapillaryUploadJob] = []
    @Published private(set) var uploadedItemIDs: Set<String> = []
    private let client: MapillaryUploadClient
    private let store: MapillaryUploadStore
    private var task: Task<Void, Never>?
    private var userID: String?
    var isConnected: Bool { username != nil && userID != nil && MapillaryCredentials.read() != nil }

    init(client: MapillaryUploadClient = .init(), store: MapillaryUploadStore = .init()) {
        self.client = client; self.store = store
        userID = UserDefaults.standard.string(forKey: "mapillary.user_id")
        username = UserDefaults.standard.string(forKey: "mapillary.username")
        Task { await refresh() }
    }
    func connect(token raw: String) {
        guard !isBusy, !isUploading else { return }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        isBusy = true
        Task {
            defer { isBusy = false }
            do {
                let profile = try await client.profile(token: token)
                try MapillaryCredentials.save(token)
                userID = profile.id; username = profile.username
                UserDefaults.standard.set(profile.id, forKey: "mapillary.user_id")
                UserDefaults.standard.set(profile.username, forKey: "mapillary.username")
                status = mly("connected"); await refresh()
            } catch { status = message(error) }
        }
    }
    func disconnect() {
        guard !isBusy, !isUploading else { return }
        MapillaryCredentials.delete(); userID = nil; username = nil; pending = []; uploadedItemIDs = []
        UserDefaults.standard.removeObject(forKey: "mapillary.user_id")
        UserDefaults.standard.removeObject(forKey: "mapillary.username")
        status = mly("disconnected")
    }
    func stop() { task?.cancel() }
    func start(photos: [MapillaryPhoto] = [], resume: MapillaryUploadJob? = nil,
               allowed: @escaping @MainActor @Sendable () -> Bool) {
        guard !isUploading, !isBusy, allowed() else { return }
        guard let userID, let token = MapillaryCredentials.read(), isConnected else { status = mly("account_required"); return }
        isUploading = true; completed = 0; total = photos.count; status = mly("preparing")
        task = Task {
            defer { isUploading = false; task = nil }
            do {
                let profile = try await client.profile(token: token)
                guard profile.id == userID else { throw MapillaryUploadError.account }
                let job: MapillaryUploadJob
                if let resume { job = resume }
                else { job = try await store.prepare(photos: photos, userID: userID) }
                guard job.userID == userID else { throw MapillaryUploadError.account }
                let worker = MapillaryUploadWorker(client: client, store: store)
                try await worker.submit(job, userID: userID, token: token,
                    allowed: { await allowed() }, progress: { done, count, key in
                        await self.updateProgress(completed: done, total: count, key: key)
                    })
            } catch { status = message(error) }
            await refresh()
        }
    }
    private func updateProgress(completed: Int, total: Int, key: String) {
        self.completed = completed; self.total = total; status = mly(key)
    }
    func refresh() async {
        guard let userID else { pending = []; uploadedItemIDs = []; return }
        pending = await store.pending(userID: userID)
        uploadedItemIDs = await store.uploadedItemIDs(userID: userID)
    }
    private func message(_ error: Error) -> String {
        if error is CancellationError || (error as? URLError)?.code == .cancelled { return mly("paused") }
        return (error as? MapillaryUploadError)?.errorDescription ?? mly("failed")
    }
}

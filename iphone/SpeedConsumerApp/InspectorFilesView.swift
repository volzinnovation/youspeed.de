import SwiftUI
import UniformTypeIdentifiers
import WebKit

private struct InspectorFile: Decodable, Identifiable {
    let id: String
    let name: String
    let kind: String
    let title: String?
}

private struct InspectorLibrary: Decodable {
    let files: [InspectorFile]
    let examples: [InspectorFile]
    let storage: Bool
    let comparison: Bool
    let trip_upload: Bool?
}

private struct InspectorPreview: Decodable {
    let html: String?
    let text: String?
    let truncated: Bool?
}

private struct InspectorFileError: LocalizedError {
    let code: String
    var errorDescription: String? { NSLocalizedString(code, comment: "") }
}

private final class InspectorNoRedirects: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest) async -> URLRequest? { nil }
}

private enum InspectorFilesClient {
    private static let endpoint = URL(string: "https://inspector.youspeed.de/inspector/api/files")!
    private static let session = URLSession(configuration: .ephemeral, delegate: InspectorNoRedirects(), delegateQueue: nil)

    static func request<Value: Decodable>(_ type: Value.Type, token: String, path: String = "",
                                           upload: (URL, String)? = nil) async throws -> Value {
        if let (url, name) = upload {
            let extensionName = (name as NSString).pathExtension.lowercased()
            guard ["gpx", "log", "txt", "csv", "json", "jsonl", "ndjson"].contains(extensionName) else {
                throw InspectorFileError(code: "inspector.files.type")
            }
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let bytes = try read(url, limit: (extensionName == "gpx" ? 2 : 16) * 1024 * 1024)
            return try await send(type, token: token, path: path, body: (name, bytes))
        }
        return try await send(type, token: token, path: path)
    }

    private static func read(_ url: URL, limit: Int) throws -> Data {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let bytes = try handle.read(upToCount: limit + 1) ?? Data()
        guard (1...limit).contains(bytes.count) else { throw InspectorFileError(code: "inspector.files.size") }
        return bytes
    }

    static func uploadTrack(_ id: String, journal: TripJournal, token: String) async throws {
        let bytes = try await Task.detached(priority: .userInitiated) {
            let root = try journal.export(id)
            defer { try? FileManager.default.removeItem(at: root) }
            return try read(root.appendingPathComponent("track.gpx"), limit: 2 * 1024 * 1024)
        }.value
        try Task.checkCancellation()
        _ = try await send(InspectorFile.self, token: token, path: "", body: ("YouSpeed-\(id).gpx", bytes))
    }

    static func uploadTrip(_ id: String, journal: TripJournal, token: String) async throws -> InspectorFile {
        let body = try await Task.detached(priority: .userInitiated) {
            let root = try journal.export(id)
            defer { try? FileManager.default.removeItem(at: root) }
            let gpx = try read(root.appendingPathComponent("track.gpx"), limit: 2 * 1024 * 1024)
            let raw = try read(root.appendingPathComponent("journal.json"), limit: 16 * 1024 * 1024)
            guard let payload = try JSONSerialization.jsonObject(with: raw) as? [String: Any],
                  let events = payload["events"] as? [[String: Any]] else {
                throw InspectorFileError(code: "inspector.files.failed")
            }
            let logs = events.filter { ["gps", "tsr", "sign", "gap"].contains($0["kind"] as? String ?? "") }
            let encoded = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "events": logs])
            guard encoded.count <= 16 * 1024 * 1024 else { throw InspectorFileError(code: "inspector.files.size") }
            var length = UInt32(gpx.count).bigEndian
            var body = withUnsafeBytes(of: &length) { Data($0) }
            body.append(gpx)
            body.append(encoded)
            return body
        }.value
        try Task.checkCancellation()
        return try await send(InspectorFile.self, token: token, path: "trip", body: ("YouSpeed-\(id).gpx", body))
    }

    private static func send<Value: Decodable>(_ type: Value.Type, token: String, path: String,
                                               body: (String, Data)? = nil) async throws -> Value {
        var request = URLRequest(url: path.isEmpty ? endpoint : endpoint.appending(path: path))
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 60
        let data: Data
        let response: URLResponse
        if let (name, bytes) = body {
            request.httpMethod = "POST"
            request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            request.setValue(name.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")), forHTTPHeaderField: "X-File-Name")
            (data, response) = try await session.upload(for: request, from: bytes)
        } else {
            (data, response) = try await session.data(for: request)
        }
        guard let status = (response as? HTTPURLResponse)?.statusCode, (200...299).contains(status) else {
            let status = (response as? HTTPURLResponse)?.statusCode
            let code = status == 401 || status == 403 ? "inspector.files.account" :
                status == 413 ? "inspector.files.size" :
                status == 503 ? "inspector.files.unavailable" : "inspector.files.failed"
            throw InspectorFileError(code: code)
        }
        return try JSONDecoder().decode(type, from: data)
    }
}

struct InspectorTrackShareView: View {
    let id: String
    let journal: TripJournal
    @ObservedObject var account: PanoramaxAccountModel
    @ObservedObject var viewModel: DriveSessionViewModel
    let shareArchive: () -> Void

    var body: some View {
        InspectorTrackShareOptions(id: id, journal: journal, account: account,
                                   recording: viewModel.isDriveRecorderActive, shareArchive: shareArchive)
    }
}

struct InspectorTrackShareOptions: View {
    let id: String
    let journal: TripJournal
    var account: PanoramaxAccountModel?
    var recording = false
    let shareArchive: () -> Void

    @State private var operation: Task<Void, Never>?
    @State private var error: String?
    @State private var saved = false

    private var token: String? {
        guard let account, account.normalizedOrigin == PanoramaxServiceConfiguration.origin else { return nil }
        return account.tokenForUpload()
    }

    var body: some View {
        List {
            Section {
                if saved {
                    Label("inspector.track.saved", systemImage: "checkmark.circle")
                    Link("inspector.files.open_web", destination: URL(string: "https://inspector.youspeed.de/inspector/tracks.html")!)
                } else {
                    Text("inspector.track.scope").font(.footnote)
                    Button("inspector.track.save", systemImage: "arrow.up.circle", action: upload)
                        .buttonStyle(.borderedProminent)
                        .disabled(token == nil || operation != nil || recording)
                        .accessibilityIdentifier("journal.share.inspector")
                    if token == nil {
                        Text("inspector.files.account").foregroundStyle(.secondary)
                    } else if recording {
                        Text("inspector.track.recording").foregroundStyle(.secondary)
                    }
                    if operation != nil { ProgressView() }
                    if let error { Text(error).foregroundStyle(.secondary) }
                }
            }
            Button(journalText("share_archive"), systemImage: "square.and.arrow.up", action: shareArchive)
                .disabled(operation != nil)
                .accessibilityIdentifier("journal.share.archive")
        }
        .navigationTitle("inspector.track.share")
        .navigationBarTitleDisplayMode(.inline)
        .onDisappear { operation?.cancel() }
        .onChange(of: account?.tokenID) { _, _ in reset() }
        .onChange(of: account?.instanceOrigin) { _, _ in reset() }
    }

    private func upload() {
        guard let token, operation == nil, !recording else { return }
        error = nil
        operation = Task { @MainActor in
            defer { if !Task.isCancelled { operation = nil } }
            do {
                try await InspectorFilesClient.uploadTrack(id, journal: journal, token: token)
                try Task.checkCancellation()
                saved = true
            } catch {
                if !Task.isCancelled {
                    self.error = error is InspectorFileError ? error.localizedDescription :
                        NSLocalizedString("inspector.files.failed", comment: "")
                }
            }
        }
    }

    private func reset() {
        operation?.cancel()
        operation = nil
        error = nil
        saved = false
    }
}

struct InspectorFilesView: View {
    @ObservedObject var account: PanoramaxAccountModel
    @ObservedObject var viewModel: DriveSessionViewModel
    @ObservedObject private var journal = TripJournal.shared
    @State private var trip: TripChoice?
    @State private var library: InspectorLibrary?
    @State private var selected: URL?
    @State private var picker = false
    @State private var error: String?
    @State private var operation: Task<Void, Never>?
    @State private var preview: PreviewItem?

    private struct PreviewItem: Identifiable {
        let id = UUID()
        let file: InspectorFile
        let payload: InspectorPreview
    }

    private struct TripChoice: Identifiable {
        let id: String
        let started: Date
        let destination: String?

        var label: String {
            [started.formatted(date: .abbreviated, time: .shortened), destination]
                .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        }
    }

    private var savedTrips: [TripChoice] {
        journal.historyTrips.compactMap { row in
            guard let id = row["id"] as? String, let start = row["start"] as? Double,
                  let state = row["state"] as? String,
                  ["ended", "interrupted", "disabled"].contains(state) else { return nil }
            return TripChoice(id: id, started: Date(timeIntervalSince1970: start),
                              destination: row["end_place"] as? String)
        }
    }

    private var token: String? {
        account.normalizedOrigin == PanoramaxServiceConfiguration.origin ? account.tokenForUpload() : nil
    }

    private var localLogs: [URL] {
        let paths = [viewModel.gpsLogPath, viewModel.matchLogPath, viewModel.tsrLogPath]
            .filter { !$0.isEmpty }.map { URL(fileURLWithPath: $0) }
        return (paths + [viewModel.inventorySignLogURL].compactMap { $0 })
            .filter { FileManager.default.fileExists(atPath: $0.path) }
    }

    var body: some View {
        List {
            if token == nil {
                Text("inspector.files.account").foregroundStyle(.secondary)
            } else {
                Section("inspector.files.upload") {
                    Button("inspector.files.choose") { picker = true }
                    if library?.trip_upload == true && !savedTrips.isEmpty {
                        Menu("inspector.files.choose_trip") {
                            ForEach(savedTrips) { choice in
                                Button(choice.label) { trip = choice; selected = nil }
                            }
                        }
                        .disabled(operation != nil)
                    }
                    if let trip {
                        Text(trip.label)
                        Button("inspector.files.save_trip") { uploadTrip(trip.id) }
                            .disabled(operation != nil || viewModel.isDriveRecorderActive)
                    }
                    if !localLogs.isEmpty {
                        Menu("inspector.files.choose_log") {
                            ForEach(localLogs, id: \.self) { url in
                                Button(url.lastPathComponent) { selected = url; trip = nil }
                            }
                        }
                    }
                    if let selected {
                        Text(selected.lastPathComponent)
                        Button("inspector.files.save") { upload(selected) }
                            .disabled(operation != nil || library?.storage != true || viewModel.isDriveRecorderActive)
                    }
                }
                Section("inspector.files.saved") {
                    ForEach(library?.files ?? []) { file in fileButton(file) }
                    if library?.storage == true && library?.files.isEmpty == true {
                        Text("inspector.files.empty").foregroundStyle(.secondary)
                    }
                    if library?.storage == false { Text("inspector.files.unavailable").foregroundStyle(.secondary) }
                }
                if let examples = library?.examples, !examples.isEmpty {
                    Section("inspector.files.examples") {
                        ForEach(examples) { file in fileButton(file) }
                    }
                }
                Button("inspector.files.refresh") { refresh() }.disabled(operation != nil)
            }
            if operation != nil { ProgressView() }
            if let error { Text(error).foregroundStyle(.secondary) }
            Link("inspector.files.open_web", destination: URL(string: "https://inspector.youspeed.de/inspector/tracks.html")!)
        }
        .navigationTitle("inspector.files.title")
        .navigationBarTitleDisplayMode(.inline)
        .fileImporter(isPresented: $picker, allowedContentTypes: [.item]) { result in
            switch result {
            case .success(let url): selected = url; trip = nil
            case .failure(let failure): error = failure.localizedDescription
            }
        }
        .sheet(item: $preview) { item in
            NavigationStack {
                Group {
                    if let html = item.payload.html {
                        InspectorChartView(html: html)
                    } else {
                        ScrollView {
                            Text(item.payload.text ?? "").font(.system(.footnote, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading).padding()
                            if item.payload.truncated == true { Text("inspector.files.truncated") }
                        }
                    }
                }
                .navigationTitle(item.file.title ?? item.file.name)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("inspector.files.close") { preview = nil } } }
            }
        }
        .onAppear { refresh() }
        .onDisappear { cancel() }
        .onChange(of: account.tokenID) { _, _ in reset() }
        .onChange(of: account.instanceOrigin) { _, _ in reset() }
    }

    private func fileButton(_ file: InspectorFile) -> some View {
        Button(file.title ?? file.name) {
            run { token in
                let action = file.kind == "track" ? "comparison" : "preview"
                let payload = try await InspectorFilesClient.request(InspectorPreview.self, token: token,
                                                                      path: file.id + "/" + action)
                try Task.checkCancellation()
                preview = PreviewItem(file: file, payload: payload)
            }
        }
        .disabled(operation != nil || (file.kind == "track" && library?.comparison != true))
    }

    private func upload(_ url: URL) {
        guard !viewModel.isDriveRecorderActive else { return }
        run { token in
            let file = try await InspectorFilesClient.request(InspectorFile.self, token: token,
                                                              upload: (url, url.lastPathComponent))
            try Task.checkCancellation()
            if library?.files.contains(where: { $0.id == file.id }) == false {
                library = library.map { InspectorLibrary(files: [file] + $0.files, examples: $0.examples,
                                                           storage: $0.storage, comparison: $0.comparison, trip_upload: $0.trip_upload) }
            }
            selected = nil
        }
    }

    private func uploadTrip(_ id: String) {
        guard !viewModel.isDriveRecorderActive else { return }
        run { token in
            _ = try await InspectorFilesClient.uploadTrip(id, journal: journal, token: token)
            let result = try await InspectorFilesClient.request(InspectorLibrary.self, token: token)
            try Task.checkCancellation()
            library = result
            trip = nil
        }
    }

    private func refresh() {
        run { token in
            let result = try await InspectorFilesClient.request(InspectorLibrary.self, token: token)
            try Task.checkCancellation()
            library = result
        }
    }

    private func run(_ action: @escaping @MainActor (String) async throws -> Void) {
        guard operation == nil, let token else { return }
        error = nil
        operation = Task { @MainActor in
            defer { if !Task.isCancelled { operation = nil } }
            do { try await action(token) } catch {
                if !Task.isCancelled { self.error = error.localizedDescription }
            }
        }
    }

    private func cancel() {
        operation?.cancel()
        operation = nil
    }

    private func reset() {
        cancel()
        library = nil
        preview = nil
        selected = nil
        trip = nil
        refresh()
    }
}

private struct InspectorChartView: UIViewRepresentable {
    let html: String

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(navigationAction.request.url?.absoluteString == "about:blank" ? .allow : .cancel)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.loadHTMLString(html, baseURL: nil)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}
}

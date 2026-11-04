import XCTest
import CryptoKit
import CoreLocation
import SwiftUI
import UIKit
import Darwin
import Vision
@testable import SpeedConsumer

@MainActor final class RoadworksServiceTests: XCTestCase {
    private func cachedPair(at root: URL) throws {
        let bytes = try RoadworksTestFixtures.data("snapshot-v1.json")
        let id = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let now = ISO8601DateFormatter().string(from: Date())
        let manifest: [String: Any] = ["schema_version": 1, "region": "DE-BW", "feature_enabled": true, "snapshot_id": id, "snapshot_bytes": bytes.count, "snapshot_path": "/youspeed/live/v1/regions/DE-BW/snapshots/" + id, "freshness": ["status": "fresh", "server_time": now, "source_publication_at": now, "source_modified_at": now, "last_checked_at": now], "coverage": ["region": "DE-BW", "complete_road_coverage": false, "autobahn_included": false], "attributions": [["provider": "fixture"]]]
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try bytes.write(to: root.appendingPathComponent(id + ".json"))
        try JSONSerialization.data(withJSONObject: manifest).write(to: root.appendingPathComponent("previous-manifest.json"))
        try Data("broken-current".utf8).write(to: root.appendingPathComponent("manifest.json"))
    }
    func testProductionCacheRestoresPreviousAndCompatibilityErrorSurvivesEvaluation() async throws {
        let name = "roadworks-previous-\(UUID())", root = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name)); defaults.set(true, forKey: "youspeed.roadworks.enabled")
        defer { defaults.removePersistentDomain(forName: name); try? FileManager.default.removeItem(at: root) }
        try cachedPair(at: root)
        let service = RoadworksService(directory: root, defaults: defaults) { url, _, _ in
            XCTAssertEqual(url.path, "/youspeed/live/v2/regions/DE-BW")
            return (Data("{\"schema_version\":3}".utf8), HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        }
        service.update(location: CLLocation(coordinate: .init(latitude: 48, longitude: 8), altitude: 0, horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: Date()))
        XCTAssertFalse(service.nearby.isEmpty)
        XCTAssertEqual(service.status, "unknown")
        service.refresh(explicit: true)
        for _ in 0..<100 { if service.status != "loading" { break }; await Task.yield() }
        XCTAssertEqual(service.status, "update_required")
        service.session(driving: false, foreground: true)
        XCTAssertEqual(service.status, "update_required")
        service.setEnabled(false)
    }
    func testClearEpochRejectsEarlierDiskPromotion() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("roadworks-disk-\(UUID())")
        defer { try? FileManager.default.removeItem(at: root) }
        let disk = RoadworksDiskStore(directory: root)
        let manifest = RoadworksAdvisory.Manifest(enabled: false, snapshotID: nil, snapshotBytes: nil, snapshotPath: nil, serverTime: Date(), sourcePublication: nil, sourceModified: nil, lastChecked: nil, advertisedStatus: .unavailable)
        await disk.clear(epoch: 1)
        let stale = try await disk.promote(epoch: 0, bytes: nil, candidate: manifest, manifestBytes: Data("{}".utf8), previousID: nil)
        XCTAssertFalse(stale)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
        let fresh = try await disk.promote(epoch: 2, bytes: nil, candidate: manifest, manifestBytes: Data("{}".utf8), previousID: nil)
        XCTAssertTrue(fresh)
        await disk.clear(epoch: 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("manifest.json").path))
        await disk.clear(epoch: 3)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
    }
    func testV2DownloadKeepsSourceHealthAndValidatedCacheAcrossRestart() async throws {
        let manifest = try RoadworksTestFixtures.data("manifest-v2.json")
        let snapshot = try RoadworksTestFixtures.data("snapshot-v2.json")
        let name = "road-advisories-v2-\(UUID())", root = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name); try? FileManager.default.removeItem(at: root) }
        let service = RoadworksService(directory: root, defaults: defaults) { url, _, _ in
            XCTAssertTrue(url.path.hasPrefix("/youspeed/live/v2/regions/DE-BW"))
            return (url.path.contains("/snapshots/") ? snapshot : manifest,
                HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        }
        service.setEnabled(true)
        for _ in 0..<100 { if service.status != "loading" { break }; try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(service.sources.count, 4)
        XCTAssertEqual(service.sourceStatus(for: "bemas"), .fresh)
        XCTAssertEqual(service.sourceStatus(for: "incidents-bw"), .fresh)
        XCTAssertEqual(service.sourceStatus(for: "autobahn-long-term"), .unavailable)
        XCTAssertEqual(service.sourceAttribution(for: "incidents-bw")["license_id"], "fixture-only")
        let restored = RoadworksService(directory: root, defaults: defaults) { _, _, _ in throw URLError(.notConnectedToInternet) }
        XCTAssertEqual(restored.sources.count, 4)
        XCTAssertEqual(restored.sourceStatus(for: "incidents-bw"), .unknown)
        service.setEnabled(false)
        restored.setEnabled(false)
    }
    func testV2EndpointCannotRevalidateLegacyCacheWithV1ManifestOr304() async throws {
        for code in [200, 304] {
            let name = "road-advisories-legacy-\(UUID())", root = FileManager.default.temporaryDirectory.appendingPathComponent(name)
            let defaults = try XCTUnwrap(UserDefaults(suiteName: name)); defaults.set(true, forKey: "youspeed.roadworks.enabled")
            defer { defaults.removePersistentDomain(forName: name); try? FileManager.default.removeItem(at: root) }
            try cachedPair(at: root)
            let legacyManifest = try Data(contentsOf: root.appendingPathComponent("previous-manifest.json"))
            let service = RoadworksService(directory: root, defaults: defaults) { url, _, _ in
                XCTAssertEqual(url.path, "/youspeed/live/v2/regions/DE-BW")
                return (code == 200 ? legacyManifest : Data(), HTTPURLResponse(url: url, statusCode: code, httpVersion: nil, headerFields: nil)!)
            }
            service.update(location: CLLocation(coordinate: .init(latitude: 48, longitude: 8), altitude: 0, horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: Date()))
            service.refresh(explicit: true)
            for _ in 0..<100 { if service.status != "loading" { break }; try await Task.sleep(nanoseconds: 10_000_000) }
            XCTAssertEqual(service.status, "update_required")
            XCTAssertEqual(service.sourceStatus(for: "bemas"), .unknown)
            XCTAssertFalse(service.nearby.isEmpty)
            service.setEnabled(false)
        }
    }
    actor Calls {
        var count = 0
        func increment() { count += 1 }
    }
    func testOffByDefaultSingleRequestAndDisableCancelsWithoutLatePublication() async throws {
        let name = "roadworks-test-\(UUID())", calls = Calls()
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        let service = RoadworksService(directory: FileManager.default.temporaryDirectory.appendingPathComponent(name), defaults: defaults) { _, _, _ in
            await calls.increment()
            try await Task.sleep(nanoseconds: 10_000_000_000)
            throw URLError(.timedOut)
        }
        XCTAssertFalse(service.enabled)
        service.session(driving: true, foreground: true)
        service.refresh(explicit: true)
        await Task.yield()
        let before = await calls.count
        XCTAssertEqual(before, 0)
        service.setEnabled(true)
        service.refresh(explicit: true)
        for _ in 0..<20 { if await calls.count == 1 { break }; await Task.yield() }
        let during = await calls.count
        XCTAssertEqual(during, 1)
        service.setEnabled(false)
        for _ in 0..<5 { await Task.yield() }
        XCTAssertEqual(service.status, "off")
        XCTAssertNil(service.card)
        XCTAssertTrue(service.nearby.isEmpty)
    }
}

private actor CapturedIncidentTransport {
    enum Mode: Equatable { case publication, notModified, offline, disabled }
    private var mode = Mode.publication
    private let manifest: Data
    private let snapshot: Data
    private var validators: [String?] = []

    init(manifest: Data, snapshot: Data) { self.manifest = manifest; self.snapshot = snapshot }
    func setMode(_ value: Mode) { mode = value }
    func receivedConditionalValidator() -> Bool { validators.contains { $0 == "\"captured-qualification\"" } }
    func reply(_ url: URL, validator: String?, limit: Int) throws -> (bytes: Data, response: HTTPURLResponse) {
        if mode == .offline { throw URLError(.notConnectedToInternet) }
        if url.path.contains("/snapshots/") {
            guard snapshot.count <= limit else { throw URLError(.dataLengthExceedsMaximum) }
            return (snapshot, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        }
        validators.append(validator)
        if mode == .notModified {
            return (Data(), HTTPURLResponse(url: url, statusCode: 304, httpVersion: nil,
                headerFields: ["ETag": "\"captured-qualification\""])!)
        }
        var data = manifest
        if mode == .disabled {
            var root = try JSONSerialization.jsonObject(with: manifest) as! [String: Any]
            root["feature_enabled"] = false
            var sources = root["sources"] as! [[String: Any]]
            for index in sources.indices { sources[index]["enabled"] = false }
            root["sources"] = sources
            var freshness = root["freshness"] as! [String: Any]
            freshness["status"] = "unavailable"
            root["freshness"] = freshness
            data = try JSONSerialization.data(withJSONObject: root, options: .sortedKeys)
        }
        guard data.count <= limit else { throw URLError(.dataLengthExceedsMaximum) }
        return (data, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil,
            headerFields: ["ETag": "\"captured-qualification\""])!)
    }
}

extension RoadworksServiceTests {
    private func awaitAcceptanceRefresh(_ service: RoadworksService) async throws {
        let deadline = Date().addingTimeInterval(5)
        while service.status == "loading", Date() < deadline {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertNotEqual(service.status, "loading", "An isolated incident acceptance refresh did not finish")
    }

    func testCapturedIncidentServiceTwoFixesReentryConditionalOfflineAndSourceDisable() async throws {
        let fixture = try RoadworksTestFixtures.qualificationDirectory()
        let manifestBytes = try Data(contentsOf: fixture.appendingPathComponent("manifest.json"))
        let snapshotBytes = try Data(contentsOf: fixture.appendingPathComponent("snapshot.json"))
        let manifest = try RoadworksAdvisory.parseManifest(manifestBytes)
        let snapshot = try RoadworksAdvisory.parseSnapshot(snapshotBytes, expectedID: try XCTUnwrap(manifest.snapshotID))
        let feature = try XCTUnwrap(snapshot.features.first { $0.validityBasis == "reported_active" && $0.eligible(at: manifest.serverTime) })
        let point = try XCTUnwrap(feature.points.first)
        let transport = CapturedIncidentTransport(manifest: manifestBytes, snapshot: snapshotBytes)
        let name = "captured-incident-device-\(UUID())"
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        let service = RoadworksService(directory: root, defaults: defaults) { url, validator, limit in
            try await transport.reply(url, validator: validator, limit: limit)
        }
        defer {
            service.setEnabled(false)
            defaults.removePersistentDomain(forName: name)
            try? FileManager.default.removeItem(at: root)
        }
        XCTAssertFalse(service.enabled)
        service.setEnabled(true)
        try await awaitAcceptanceRefresh(service)
        XCTAssertEqual(Set(service.sources.filter(\.enabled).map(\.id)), ["incidents-bw"])
        for source in ["bemas", "autobahn-short-term", "autobahn-long-term"] {
            XCTAssertEqual(service.sourceStatus(for: source), .unavailable)
        }
        service.session(driving: true, foreground: true)
        func location(_ at: Date) -> CLLocation {
            CLLocation(coordinate: .init(latitude: point.latitude, longitude: point.longitude), altitude: 0,
                horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: at)
        }
        let first = Date().addingTimeInterval(-1)
        service.update(location: location(first)); XCTAssertNil(service.card)
        service.update(location: location(first.addingTimeInterval(0.1)))
        XCTAssertEqual(service.card?.feature.advisorySource, "incidents-bw")
        let leaseEnd = try XCTUnwrap(service.card?.feature.outer.end)
        let sourcePublication = try XCTUnwrap(service.sources.first { $0.id == "incidents-bw" }?.publication)
        let age = try XCTUnwrap(service.sourceAgeMinutes(for: "incidents-bw"))
        func offerFreshPairAfterStorage() async throws {
            // Storage latency may legitimately age the previous GPS fix. Supply
            // fresh fixes without changing the original publisher/lease clocks.
            service.update(location: location(Date()))
            try await Task.sleep(nanoseconds: 1_000_000) // Distinct captured fixes.
            service.update(location: location(Date()))
        }

        await transport.setMode(.notModified)
        service.refresh(explicit: true); try await awaitAcceptanceRefresh(service)
        try await offerFreshPairAfterStorage()
        let conditionalValidatorReceived = await transport.receivedConditionalValidator()
        XCTAssertTrue(conditionalValidatorReceived)
        XCTAssertEqual(service.card?.feature.outer.end, leaseEnd, "304 must not extend a publisher observation")
        XCTAssertEqual(service.sources.first { $0.id == "incidents-bw" }?.publication, sourcePublication)
        XCTAssertGreaterThanOrEqual(try XCTUnwrap(service.sourceAgeMinutes(for: "incidents-bw")), age)

        await transport.setMode(.offline)
        service.refresh(explicit: true); try await awaitAcceptanceRefresh(service)
        XCTAssertEqual(service.status, "offline")
        try await offerFreshPairAfterStorage()
        XCTAssertEqual(service.card?.feature.outer.end, leaseEnd, "A failed refresh retains the original expiry")
        XCTAssertEqual(service.sources.first { $0.id == "incidents-bw" }?.publication, sourcePublication)
        service.update(location: location(Date().addingTimeInterval(-10)))
        XCTAssertNil(service.card, "Stale GPS cannot retain a cached incident card")

        service.session(driving: false, foreground: false)
        XCTAssertNil(service.card)
        service.session(driving: true, foreground: true)
        try await awaitAcceptanceRefresh(service)
        let resumed = Date().addingTimeInterval(-0.5)
        service.update(location: location(resumed)); XCTAssertNil(service.card)
        service.update(location: location(resumed.addingTimeInterval(0.1)))
        XCTAssertNotNil(service.card, "Reentry requires fresh distinct fixes and preserves still-valid data")

        await transport.setMode(.disabled)
        service.refresh(explicit: true); try await awaitAcceptanceRefresh(service)
        XCTAssertEqual(service.sourceStatus(for: "incidents-bw"), .unavailable)
        XCTAssertNil(service.card, "Disabling the source invalidates an already displayed positive report")
        XCTAssertTrue(service.nearby.isEmpty)
        service.setEnabled(false)
        XCTAssertEqual(service.status, "off")
        XCTAssertNil(service.card)
    }
}

@MainActor
private final class IncidentComponentScrollTarget: ObservableObject {
    @Published var id: String?
    var didRequestScroll: (() -> Void)?
}

/// This watermark belongs to the test stage, not to production product UI.
private struct CapturedIncidentComponentStage<Content: View>: View {
    let title: String
    let capturedAt: String
    let content: Content
    var body: some View {
        VStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text("CAPTURED TEST DATA · COMPONENT VIEW").font(.caption2.bold()).foregroundStyle(.orange)
                Text(title).font(.headline)
                Text("Source capture: " + capturedAt + " · No live feed or dashboard simulation")
                    .font(.caption2).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.top, 12)
            content
        }.background(Color.black).foregroundStyle(.white).preferredColorScheme(.dark)
    }
}

private struct CapturedIncidentParkedComponent: View {
    let service: RoadworksService
    @ObservedObject var target: IncidentComponentScrollTarget
    var body: some View {
        ScrollViewReader { proxy in
            Form { RoadworksSettingsSection(service: service) }
                .onChange(of: target.id) { value in
                    if let value {
                        proxy.scrollTo(value, anchor: .top)
                        target.didRequestScroll?()
                    }
                }
        }
    }
}

@MainActor
final class RoadworksComponentVisualAcceptanceTests: XCTestCase {
    private func host<Content: View>(_ view: Content, title: String, capturedAt: String) async throws -> UIWindow {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive })
        let appeared = expectation(description: title + " component appeared")
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.windowLevel = .alert + 1
        window.rootViewController = UIHostingController(rootView: CapturedIncidentComponentStage(
            title: title, capturedAt: capturedAt, content: view.onAppear { appeared.fulfill() }))
        window.makeKeyAndVisible()
        await fulfillment(of: [appeared], timeout: 5)
        window.rootViewController?.view.setNeedsLayout()
        window.rootViewController?.view.layoutIfNeeded()
        await Task.yield()
        return window
    }

    @discardableResult
    private func attach(_ window: UIWindow, name: String) throws -> UIImage {
        window.layoutIfNeeded()
        let renderer = UIGraphicsImageRenderer(bounds: window.bounds)
        var drew = false
        let image = renderer.image { _ in drew = window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        XCTAssertTrue(drew, "UIKit must render the hosted production component")
        XCTAssertGreaterThan(try XCTUnwrap(image.pngData()).count, 1_024)
        let attachment = XCTAttachment(image: image)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        return image
    }

    func testCapturedIncidentActualDrivingAndParkedComponents() async throws {
        guard ConsumerTestHost.isIsolated else {
            throw ConsumerAppError.io("Component evidence must run in the separate unit-test app")
        }
        let fixture = try RoadworksTestFixtures.qualificationDirectory()
        let manifestBytes = try Data(contentsOf: fixture.appendingPathComponent("manifest.json"))
        let snapshotBytes = try Data(contentsOf: fixture.appendingPathComponent("snapshot.json"))
        let receipt = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: fixture.appendingPathComponent("receipt.json"))) as? [String: Any])
        let capturedAt = try XCTUnwrap(receipt["checked_at_utc"] as? String)
        let manifest = try RoadworksAdvisory.parseManifest(manifestBytes)
        let snapshot = try RoadworksAdvisory.parseSnapshot(snapshotBytes, expectedID: try XCTUnwrap(manifest.snapshotID))
        let candidate = try XCTUnwrap(snapshot.features.first { $0.validityBasis == "reported_active" && $0.eligible(at: manifest.serverTime) })
        let point = try XCTUnwrap(candidate.points.first)
        let transport = CapturedIncidentTransport(manifest: manifestBytes, snapshot: snapshotBytes)
        let name = "incident-component-evidence-\(UUID())"
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        let service = RoadworksService(directory: directory, defaults: defaults) { url, validator, limit in
            try await transport.reply(url, validator: validator, limit: limit)
        }
        let previousKey = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows).first(where: \.isKeyWindow)
        var windows: [UIWindow] = []
        defer {
            windows.forEach { $0.isHidden = true; $0.rootViewController = nil }
            previousKey?.makeKeyAndVisible()
            service.setEnabled(false)
            defaults.removePersistentDomain(forName: name)
            try? FileManager.default.removeItem(at: directory)
        }
        service.setEnabled(true)
        let deadline = Date().addingTimeInterval(5)
        while service.status == "loading", Date() < deadline { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertNotEqual(service.status, "loading")
        XCTAssertEqual(Set(service.sources.filter(\.enabled).map(\.id)), ["incidents-bw"])
        await transport.setMode(.notModified)
        service.session(driving: true, foreground: true)
        func offerFix() {
            service.update(location: CLLocation(coordinate: .init(latitude: point.latitude, longitude: point.longitude),
                altitude: 0, horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: Date()))
        }
        offerFix(); try await Task.sleep(nanoseconds: 1_000_000); offerFix()
        let card = try XCTUnwrap(service.card)
        XCTAssertEqual(card.feature.advisorySource, "incidents-bw")
        let simulatedFixes = Task { @MainActor in
            while !Task.isCancelled {
                offerFix()
                do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
            }
        }
        defer { simulatedFixes.cancel() }
        // These are component palette checks, not full-dashboard evidence.
        // MainView's call site uses its existing primaryForegroundColor policy.
        let palettes: [(name: String, background: Color, foreground: Color)] = [
            ("black", .black, .white),
            ("yellow", Color(red: 0.98, green: 0.87, blue: 0.20), .black),
            ("red", Color(red: 0.78, green: 0.10, blue: 0.13), .white)
        ]
        for palette in palettes {
            let driving = try await host(RoadworksDrivingAdvisoryView(service: service)
                .foregroundStyle(palette.foreground)
                .frame(maxWidth: .infinity, maxHeight: .infinity).padding(.horizontal, 16)
                .background(palette.background),
                title: "Actual driving caption · " + palette.name + " palette", capturedAt: capturedAt)
            windows.append(driving)
            XCTAssertNotNil(service.card, "The captured driving component requires a current simulated GPS fix")
            let suffix = palette.name == "black" ? "" : "-" + palette.name
            try attach(driving, name: "captured-incidents-driving-caption-component" + suffix)
            driving.isHidden = true
        }
        simulatedFixes.cancel()

        service.session(driving: false, foreground: true)
        XCTAssertNil(service.card)
        XCTAssertTrue(service.nearby.contains { $0.0.id == candidate.id })
        let scroll = IncidentComponentScrollTarget()
        let parked = try await host(CapturedIncidentParkedComponent(service: service, target: scroll),
            title: "Actual parked advisory settings", capturedAt: capturedAt)
        windows.append(parked)
        try attach(parked, name: "captured-incidents-parked-settings-top-component")
        let scrolled = expectation(description: "Captured source-active report details selected")
        scroll.didRequestScroll = { scrolled.fulfill() }
        scroll.id = candidate.id
        await fulfillment(of: [scrolled], timeout: 5)
        parked.rootViewController?.view.layoutIfNeeded()
        await Task.yield()
        try attach(parked, name: "captured-incidents-parked-report-details-component")
        let facts = XCTAttachment(string: "Evidence scope: actual production caption and Settings section in a watermarked test-only host; not a full-dashboard screenshot.\nCapture: \(capturedAt)\nDriving card: \(card.feature.id)\nRequested parked detail: \(candidate.id)\nEnabled test source: incidents-bw only. A test-only fix stream keeps the ordinary 3-second GPS gate satisfied while driving components render. Palette attachments are component checks, not full-dashboard contrast acceptance. No runtime feed or normal preference was changed.")
        facts.name = "captured-incident-component-evidence-scope"
        facts.lifetime = .keepAlways
        add(facts)
    }
}

extension RoadworksComponentVisualAcceptanceTests {
    /// Reads the rendered image, not the SwiftUI text/accessibility payload.
    /// This caught the former caption whose long road name hid source/age.
    private func visibleMetadata(_ image: UIImage, distance: String, age: Int?, roadLabel: String,
                                 controlsTopY: CGFloat, name: String) throws -> [String: Any] {
        let cgImage = try XCTUnwrap(image.cgImage)
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["de-DE", "en-US", "fr-FR", "nl-NL"]
        request.minimumTextHeight = 0.008
        try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
        let rows = (request.results ?? []).compactMap { observation -> (text: String, box: CGRect, confidence: Float)? in
            guard let text = observation.topCandidates(1).first else { return nil }
            let box = observation.boundingBox
            return (text.string, CGRect(x: box.minX * CGFloat(cgImage.width), y: (1 - box.maxY) * CGFloat(cgImage.height),
                                        width: box.width * CGFloat(cgImage.width), height: box.height * CGFloat(cgImage.height)), text.confidence)
        }.sorted { abs($0.box.minY - $1.box.minY) > 4 ? $0.box.minY < $1.box.minY : $0.box.minX < $1.box.minX }
        func normalized(_ value: String) -> String {
            value.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
                .components(separatedBy: CharacterSet.alphanumerics.inverted).joined()
        }
        let sourceNames = ["BW traffic incidents", "BW-Verkehrsmeldungen", "Incidents routiers BW", "BW-verkeersmeldingen"].map(normalized)
        let ageTitles = ["Source age", "Alter der Quelldaten", "Âge des données source", "Leeftijd brongegevens"].map(normalized)
        let combined = normalized(rows.map(\.text).joined(separator: " "))
        XCTAssertTrue(sourceNames.contains(where: combined.contains), "Source attribution must be readable in actual dashboard pixels")
        let ageValue = age.map { "\($0) min" } ?? ""
        XCTAssertTrue(ageTitles.contains { combined.contains($0 + normalized(ageValue)) }, "Complete source-age label/value must be readable, without tail truncation")
        let distancePattern = "(?<![0-9])" + NSRegularExpression.escapedPattern(for: distance.replacingOccurrences(of: " ", with: ""))
            .replacingOccurrences(of: "m", with: "\\s*m") + "(?![A-Za-z])"
        let summaryRows = rows.filter { $0.text.range(of: distancePattern, options: .regularExpression) != nil }
        XCTAssertFalse(summaryRows.isEmpty, "Distance including its metre unit must remain visible in rendered pixels")
        let metadataRows = rows.filter { row in
            let text = normalized(row.text)
            return sourceNames.contains(where: text.contains) || ageTitles.contains(where: text.contains)
        }
        XCTAssertFalse(metadataRows.isEmpty, "Metadata needs an actual rendered image area")
        let metadataBounds = metadataRows.reduce(CGRect.null) { $0.union($1.box) }
        let roadPrefix = String(normalized(roadLabel).prefix(12))
        guard !roadPrefix.isEmpty else { throw ConsumerAppError.io("Captured full-dashboard regression requires a nonempty road label") }
        let roadRows = rows.filter { normalized($0.text).contains(roadPrefix) }
        XCTAssertFalse(roadRows.isEmpty, "The road line must occupy readable dashboard pixels")
        let roadBounds = roadRows.reduce(CGRect.null) { $0.union($1.box) }
        let captionBounds = (summaryRows + metadataRows + roadRows).reduce(CGRect.null) { $0.union($1.box) }
        if !captionBounds.isNull {
            XCTAssertLessThan(captionBounds.maxY, controlsTopY,
                              "The complete incident caption, including the road line, must end above the action controls")
        }
        if !metadataBounds.isNull {
            XCTAssertGreaterThan(metadataBounds.width * metadataBounds.height, 128)
            XCTAssertGreaterThan(metadataBounds.height, 8)
            XCTAssertTrue(CGRect(x: 0, y: 0, width: CGFloat(cgImage.width), height: CGFloat(cgImage.height)).contains(metadataBounds), "Metadata pixels must fit the dashboard image")
            for summary in summaryRows {
                XCTAssertLessThanOrEqual(summary.box.maxY, metadataBounds.minY + 4, "Summary/distance pixels must appear above source-age pixels")
            }
            let cropBounds = metadataBounds.insetBy(dx: -6, dy: -6)
                .intersection(CGRect(x: 0, y: 0, width: CGFloat(cgImage.width), height: CGFloat(cgImage.height))).integral
            if let crop = cgImage.cropping(to: cropBounds) {
                let attachment = XCTAttachment(image: UIImage(cgImage: crop))
                attachment.name = name + "-metadata-pixels"; attachment.lifetime = .keepAlways; add(attachment)
            }
        }
        return ["method": "Vision OCR of actual rendered dashboard image; no semantic/accessibility-only success",
                "expected_distance": distance, "expected_age_minutes": age.map { $0 as Any } ?? NSNull(),
                "metadata_pixel_bounds": metadataBounds.isNull ? [] : [Double(metadataBounds.minX), Double(metadataBounds.minY), Double(metadataBounds.width), Double(metadataBounds.height)],
                "expected_road_prefix": roadPrefix, "controls_top_pixel_y": Double(controlsTopY),
                "road_pixel_bounds": roadBounds.isNull ? [] : [Double(roadBounds.minX), Double(roadBounds.minY), Double(roadBounds.width), Double(roadBounds.height)],
                "caption_pixel_bounds": captionBounds.isNull ? [] : [Double(captionBounds.minX), Double(captionBounds.minY), Double(captionBounds.width), Double(captionBounds.height)],
                "recognized_rows": rows.map { row -> [String: Any] in ["text": row.text, "confidence": Double(row.confidence), "pixel_bounds": [Double(row.box.minX), Double(row.box.minY), Double(row.box.width), Double(row.box.height)]] }]
    }

    private func dashboardFrames(_ window: UIWindow) -> [String: CGRect] {
        var seen = Set<ObjectIdentifier>(), frames: [String: CGRect] = [:]
        func visit(_ value: Any, depth: Int = 0) {
            guard depth < 40, seen.count < 5_000, let object = value as? NSObject,
                  seen.insert(ObjectIdentifier(object)).inserted else { return }
            if let view = object as? UIView {
                if !view.isHidden, view.alpha > 0.01, let id = view.accessibilityIdentifier {
                    frames[id] = view.convert(view.bounds, to: window)
                }
                for child in view.subviews { visit(child, depth: depth + 1) }
            } else if let element = object as? UIAccessibilityElement,
                      let id = element.accessibilityIdentifier {
                frames[id] = window.convert(element.accessibilityFrame, from: nil)
            }
            for child in object.automationElements ?? [] { visit(child, depth: depth + 1) }
            for child in object.accessibilityElements ?? [] { visit(child, depth: depth + 1) }
            let count = object.accessibilityElementCount()
            if count > 0, count < 1_000 {
                for index in 0..<count {
                    if let child = object.accessibilityElement(at: index) { visit(child, depth: depth + 1) }
                }
            }
        }
        visit(window)
        return frames
    }

    private func requestEvidenceMount(_ mount: ScreenOrientation, scene: UIWindowScene) async -> String? {
        UserDefaults.standard.set(mount.rawValue, forKey: ScreenOrientation.defaultsKey)
        ManualScreenOrientationController.shared.selection = mount
        var failure: String?
        ManualScreenOrientationController.shared.apply(to: scene) { failure = $0.localizedDescription }
        let deadline = Date().addingTimeInterval(4)
        while scene.interfaceOrientation != mount.interfaceOrientation, failure == nil, Date() < deadline {
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        if scene.interfaceOrientation != mount.interfaceOrientation {
            return failure ?? "The requested interface orientation did not become active"
        }
        return nil
    }

    func testCapturedIncidentFullDashboardEvidence() async throws {
        guard ConsumerTestHost.isIsolated else {
            throw ConsumerAppError.io("Full dashboard evidence requires the separate unit-test app")
        }
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive })
        let previousKey = scene.windows.first(where: \.isKeyWindow)
        let previousMount = ManualScreenOrientationController.shared.selection
        let preferences = UserDefaults.standard
        let preferenceKeys = [ScreenOrientation.defaultsKey, "youspeed.drive_recorder.dashcam_enabled",
                              "youspeed.drive_recorder.tsr_enabled", "youspeed.drive_recorder.panoramax_enabled",
                              "youspeed.audio_alerts_enabled", "youspeed.journal.enabled"]
        let savedPreferences = Dictionary(uniqueKeysWithValues: preferenceKeys.map { ($0, preferences.object(forKey: $0)) })
        let environmentKeys = ["YOUSPEED_SCREENSHOT_STATE", "YOUSPEED_SCREENSHOT_DASHCAM",
                               "YOUSPEED_SCREENSHOT_SPEED_KMH", "YOUSPEED_SCREENSHOT_MISSING_COVERAGE"]
        let savedEnvironment = Dictionary(uniqueKeysWithValues: environmentKeys.map { key in
            (key, getenv(key).map { String(cString: $0) })
        })
        defer {
            for (key, value) in savedPreferences {
                if let value { preferences.set(value, forKey: key) } else { preferences.removeObject(forKey: key) }
            }
            for (key, value) in savedEnvironment {
                if let value { setenv(key, value, 1) } else { unsetenv(key) }
            }
            ManualScreenOrientationController.shared.selection = previousMount
            ManualScreenOrientationController.shared.apply(to: scene) { _ in }
            previousKey?.makeKeyAndVisible()
        }
        for key in preferenceKeys where key != ScreenOrientation.defaultsKey { preferences.set(false, forKey: key) }
        for key in environmentKeys { unsetenv(key) }
        let fixture = try RoadworksTestFixtures.qualificationDirectory()
        let manifestBytes = try Data(contentsOf: fixture.appendingPathComponent("manifest.json"))
        let snapshotBytes = try Data(contentsOf: fixture.appendingPathComponent("snapshot.json"))
        let receipt = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: fixture.appendingPathComponent("receipt.json"))) as? [String: Any])
        let capturedAt = try XCTUnwrap(receipt["checked_at_utc"] as? String)
        let manifest = try RoadworksAdvisory.parseManifest(manifestBytes)
        let snapshot = try RoadworksAdvisory.parseSnapshot(snapshotBytes, expectedID: try XCTUnwrap(manifest.snapshotID))
        let candidate = try XCTUnwrap(snapshot.features.first { $0.validityBasis == "reported_active" && $0.eligible(at: manifest.serverTime) })
        let point = try XCTUnwrap(candidate.points.first)
        let transport = CapturedIncidentTransport(manifest: manifestBytes, snapshot: snapshotBytes)
        let name = "incident-dashboard-evidence-\(UUID())"
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        let service = RoadworksService(directory: directory.appendingPathComponent("advisories"), defaults: defaults) { url, validator, limit in
            try await transport.reply(url, validator: validator, limit: limit)
        }
        let journal = TripJournal(directory: directory.appendingPathComponent("journal"), preferences: defaults, heartbeat: false)
        _ = await journal.mediaSnapshot("nonexistent-visual-fixture")
        var windows: [UIWindow] = []
        defer {
            windows.forEach { $0.isHidden = true; $0.rootViewController = nil }
            service.setEnabled(false)
            journal.close()
            defaults.removePersistentDomain(forName: name)
            try? FileManager.default.removeItem(at: directory)
        }
        service.setEnabled(true)
        let loadedDeadline = Date().addingTimeInterval(5)
        while service.status == "loading", Date() < loadedDeadline { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertNotEqual(service.status, "loading")
        XCTAssertEqual(Set(service.sources.filter(\.enabled).map(\.id)), ["incidents-bw"])
        await transport.setMode(.notModified)
        service.session(driving: true, foreground: true)
        func offerFix() {
            service.update(location: CLLocation(coordinate: .init(latitude: point.latitude, longitude: point.longitude),
                altitude: 0, horizontalAccuracy: 5, verticalAccuracy: 5, timestamp: Date()))
        }
        offerFix(); try await Task.sleep(nanoseconds: 1_000_000); offerFix()
        XCTAssertNotNil(service.card)
        let simulatedFixes = Task { @MainActor in
            while !Task.isCancelled {
                offerFix()
                do { try await Task.sleep(nanoseconds: 250_000_000) } catch { return }
            }
        }
        defer { simulatedFixes.cancel() }
        for mount in [ScreenOrientation.portrait, .landscapeCameraLowerRight] {
            if let failure = await requestEvidenceMount(mount, scene: scene) {
                let note = XCTAttachment(string: "Requested mount: \(mount.rawValue)\nNot captured: \(failure)\nNo resized image is represented as an orientation acceptance.")
                note.name = "dashboard-orientation-unavailable-" + mount.rawValue; note.lifetime = .keepAlways; add(note)
                if mount == .portrait { XCTFail(failure) }
                continue
            }
            for state in [AppScreenshotState.warnLevel0, .warnLevel1, .warnLevel3] {
                XCTAssertEqual(setenv("YOUSPEED_SCREENSHOT_STATE", state.rawValue, 1), 0)
                guard AppScreenshotState.current() == state else {
                    throw ConsumerAppError.io("In-process screenshot environment did not update; do not mount a normal dashboard as a fixture")
                }
                let model = DriveSessionViewModel()
                guard model.appScreenshotState == state else {
                    throw ConsumerAppError.io("The dashboard did not enter the requested screenshot fixture")
                }
                XCTAssertEqual(model.screenOrientation, mount)
                XCTAssertFalse(model.trafficSignRecognitionEnabled)
                XCTAssertFalse(model.panoramaxCaptureEnabled)
                let appeared = expectation(description: "Actual dashboard " + state.rawValue + " appeared")
                let window = UIWindow(windowScene: scene)
                window.frame = scene.coordinateSpace.bounds
                window.windowLevel = .alert + 1
                window.rootViewController = UIHostingController(rootView: MainView(
                    viewModel: model, tripJournal: journal, roadworksService: service)
                    .environment(\.scenePhase, .active)
                    .overlay(alignment: .topLeading) {
                        Text("TEST TELEMETRY + CAPTURED INCIDENT\n" + capturedAt + " · " + state.rawValue)
                            .font(.system(size: 7, weight: .bold)).padding(4)
                            .foregroundStyle(.white).background(.black.opacity(0.8))
                            .allowsHitTesting(false).accessibilityIdentifier("test.incidentCaptureWatermark")
                    }
                    .onAppear { appeared.fulfill() })
                windows.append(window)
                window.makeKeyAndVisible()
                await fulfillment(of: [appeared], timeout: 5)
                // First pass measures the intrinsic caption; the second lets
                // MainView reserve that height in its sign/metric budgets.
                for _ in 0..<2 {
                    window.rootViewController?.view.setNeedsLayout()
                    window.rootViewController?.view.layoutIfNeeded()
                    await Task.yield()
                    try await Task.sleep(nanoseconds: 20_000_000)
                }
                let evidenceCard = try XCTUnwrap(service.card, "The full dashboard screenshot must contain an admitted captured incident")
                let expectedAge = service.sourceAgeMinutes(for: evidenceCard.feature.advisorySource)
                let imageName = "captured-incidents-full-dashboard-" + state.rawValue + "-" + mount.rawValue
                let image = try attach(window, name: imageName)
                // Reproduce the actual MainView control-row geometry from
                // this window's safe area, not an unavailable AX frame map.
                let safeArea = window.safeAreaInsets
                let viewport = window.bounds.inset(by: safeArea)
                let screenInset = max(8, min(viewport.width, viewport.height) * 0.02)
                let diameter: CGFloat = mount.isLandscape ? 40 : 44
                let bottomPadding = max(screenInset, safeArea.bottom * 0.45)
                let controlsTop = window.bounds.maxY - safeArea.bottom - bottomPadding - diameter
                let pixelScale = CGFloat(try XCTUnwrap(image.cgImage).height) / window.bounds.height
                let renderedMetadata = try visibleMetadata(image, distance: "\(Int((evidenceCard.distanceM / 10).rounded(.up)) * 10) m",
                    age: expectedAge, roadLabel: evidenceCard.feature.roadLabel, controlsTopY: controlsTop * pixelScale, name: imageName)
                let frames = dashboardFrames(window)
                let caption = frames["dashboard.roadworks"]
                if let caption {
                    XCTAssertGreaterThan(caption.width * caption.height, 1)
                    XCTAssertTrue(window.bounds.insetBy(dx: -1, dy: -1).contains(caption), "Advisory text escapes the actual dashboard viewport")
                    for id in ["primary-metric", "secondary-metric", "dashboard.recorderButton", "dashboard.panoramaxCaptureButton",
                               "dashboard.galleryButton", "dashboard.calibrationButton", "dashboard.infoButton", "dashboard.tripsButton", "dashboard.settingsButton"] {
                        if let other = frames[id] {
                            let intersection = caption.intersection(other)
                            XCTAssertTrue(intersection.isNull || intersection.width * intersection.height <= 1, "Advisory overlaps " + id)
                        }
                    }
                }
                let geometry: [String: Any] = ["capture_scope": "Actual MainView layout; telemetry is an existing screenshot fixture; incident is captured source data, not a live feed",
                    "state": state.rawValue, "mount": mount.rawValue, "actual_interface_orientation": scene.interfaceOrientation.rawValue,
                    "viewport": [Double(window.bounds.width), Double(window.bounds.height)],
                    "safe_area_insets": [Double(safeArea.top), Double(safeArea.left), Double(safeArea.bottom), Double(safeArea.right)],
                    "controls_top_point_y": Double(controlsTop),
                    "caption_accessibility_frame_exposed": caption != nil,
                    "frames": frames.mapValues { [Double($0.minX), Double($0.minY), Double($0.width), Double($0.height)] },
                    "manual_image_review_required": true, "rendered_metadata": renderedMetadata]
                let json = try JSONSerialization.data(withJSONObject: geometry, options: [.prettyPrinted, .sortedKeys])
                let note = XCTAttachment(data: json, uniformTypeIdentifier: "public.json")
                note.name = imageName + "-geometry"; note.lifetime = .keepAlways; add(note)
                window.isHidden = true; window.rootViewController = nil
                model.stopDriving()
            }
        }
    }
}

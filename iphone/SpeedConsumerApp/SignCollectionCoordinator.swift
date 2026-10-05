import Foundation
import Combine
import CoreLocation
import Network
import CoreGraphics

/// Ordinary camera collection. The camera does not wait for this controller.
@MainActor final class SignCollectionCoordinator: ObservableObject {
    @Published private(set) var enabled: Bool
    @Published private(set) var authorized = false
    @Published private(set) var cropsAuthorized = false
    private var framePending = false
    @Published private(set) var consentPresented = false
    @Published private(set) var status = "idle"
    @Published private(set) var deletions: [[String: Bool]] = []
    private let foundation: SignCollectionFoundation
    private let storage = DispatchQueue(label: "de.youspeed.sign-collection.storage", qos: .utility)
    private final class CaptureState {
        let observer = SignCollectionObserver()
        var packHashes: [String: String] = [:]
    }
    private nonisolated let capture = CaptureState()
    private let monitor = NWPathMonitor()
    private var timer: Timer?
    private var upload: Task<Void, Never>?
    private var client: SignCollectionHTTPClient?
    private var worker: SignCollectionUploadWorker?
    private var networkAvailable = false
    private var cameraActive = false
    private var session: String?
    private var generation = 0
    private var privacyChangePending = false
    private var currentEpoch: Int?
    init(foundation: SignCollectionFoundation) {
        self.foundation = foundation
        enabled = UserDefaults.standard.object(forKey: "youspeed.collection.enabled") as? Bool ?? true
        if case .success(let store) = foundation.store, let http = try? SignCollectionHTTPClient() {
            client = http; worker = SignCollectionUploadWorker(store: store, client: http)
        } else { status = "storage_unavailable" }
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.networkAvailable = path.status == .satisfied
                self?.deliver()
            }
        }
        monitor.start(queue: DispatchQueue(label: "de.youspeed.sign-collection.network"))
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.deliver() }
        }
        perform { try $0.migrateAutomaticCrops() }
    }
    deinit { timer?.invalidate(); monitor.cancel(); upload?.cancel(); client?.close() }
    func cameraChanged(active: Bool) {
        let becameActive = active && !cameraActive
        cameraActive = active
        if becameActive {
            if session == nil { session = SignCollectionJSON.uuid() }
            let id = session!
            perform { store in try store.beginSession(id) }
            requestConsent()
        }
        if !active { deliver() }
    }
    func endSession() {
        session = nil; consentPresented = false; authorized = false; cropsAuthorized = false; cameraActive = false
        perform { [capture] store in capture.observer.reset(); store.endSession() }
        deliver()
    }
    private func requestConsent() {
        guard enabled, cameraActive, !consentPresented else { return }
        let token = generation, expectedSession = session
        perform { store in
            let prompt = try store.shouldPrompt(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure)
            Task { @MainActor [weak self] in if self?.generation == token && self?.session == expectedSession && self?.cameraActive == true && self?.enabled == true { self?.consentPresented = prompt } }
        }
    }
    func decide(granted: Bool, dontAskAgain: Bool) {
        consentPresented = false
        privacy { store in _ = try store.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: granted, dontAskAgain: dontAskAgain) }
    }
    func dismissConsent() { consentPresented = false }
    func setEnabled(_ value: Bool) {
        guard value != enabled else { return }
        enabled = value; UserDefaults.standard.set(value, forKey: "youspeed.collection.enabled")
        invalidateUpload(); authorized = false; cropsAuthorized = false; consentPresented = false
        privacy { [capture] store in
            capture.observer.reset()
            if value { try store.allowPromptAgain(scope: "sign_metadata") }
            else { try store.withdraw(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure) }
        }
        if value { requestConsent() }
    }
    func deleteObservations() {
        invalidateUpload(); authorized = false; cropsAuthorized = false; consentPresented = false; session = nil
        privacy { [capture] store in capture.observer.reset(); _ = try store.requestDeletion() }
    }
    func clearPendingForDeveloper() {
        invalidateUpload()
        perform { [capture] store in capture.observer.reset(); try store.clearPendingForDeveloper() }
    }
    private func invalidateUpload() { generation += 1; upload?.cancel(); upload = nil }
    private func privacy(_ action: @escaping (SignCollectionStore) throws -> Void) {
        invalidateUpload(); privacyChangePending = true; authorized = false; cropsAuthorized = false
        let token = generation
        perform { store in
            try action(store)
            Task { @MainActor [weak self] in
                guard self?.generation == token else { return }
                self?.privacyChangePending = false; self?.deliver()
            }
        }
    }
    private func perform(refreshAfter: Bool = true, _ action: @escaping (SignCollectionStore) throws -> Void) {
        guard case .success(let store) = foundation.store else { return }
        storage.async { [weak self] in
            do { try action(store); if refreshAfter { Task { @MainActor in self?.refresh() } } }
            catch { Task { @MainActor in self?.status = "local_operation_failed"; self?.refresh() } }
        }
    }
    private func refresh() {
        guard case .success(let store) = foundation.store else { return }
        let token = generation
        storage.async { [weak self] in
            let authorized = store.isAuthorized(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure)
            if authorized { try? store.authorizeAutomaticCrops() }
            let crops = store.isAuthorized(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure)
            try? store.expireCrops()
            let epoch = try? store.collectionEpoch, barrier = (try? store.deletionIsPending) ?? true
            let phases = (try? store.controlHistory())?.filter { $0.kind == "deletion" }.suffix(3).map { control in
                Dictionary(uniqueKeysWithValues: ["active_data_removed", "archives_purged", "backup_expiry_complete"].map { ($0, SignCollectionJSON.boolean(control.response?[$0]) == true) })
            } ?? []
            Task { @MainActor in
                guard let self, self.generation == token else { return }
                if let previous = self.currentEpoch, let epoch, previous != epoch {
                    self.session = nil; self.perform { [capture = self.capture] _ in capture.observer.reset() }
                }
                self.currentEpoch = epoch
                self.authorized = authorized && self.enabled && !self.privacyChangePending; self.deletions = phases
                self.cropsAuthorized = crops && self.authorized
                // Active removal invalidates the old session. A new grant is required.
                if self.cameraActive, self.session == nil, !self.privacyChangePending, !barrier {
                    self.session = SignCollectionJSON.uuid()
                    if let id = self.session { self.perform { try $0.beginSession(id) }; self.requestConsent() }
                }
            }
        }
    }
    func deliver() {
        guard upload == nil, let worker else { return }
        let available = networkAvailable, allowed = enabled && !privacyChangePending, token = generation
        upload = Task { [weak self] in
            let result: String
            do { result = try await worker.runOnce(networkAvailable: available, ordinaryDeliveryAllowed: allowed) }
            catch is CancellationError { return }
            catch { result = "delivery_unavailable" }
            guard let self, token == self.generation else { return }
            if !self.privacyChangePending { self.status = result }
            self.upload = nil; self.refresh()
            if ["crop_committed", "metadata_committed", "batch_split"].contains(result) {
                Timer.scheduledTimer(withTimeInterval: 1, repeats: false) { [weak self] _ in
                    Task { @MainActor in self?.deliver() }
                }
            }
        }
    }
    func observe(_ emission: TrafficSignRuntimeEmission, pack: TrafficSignVerifiedModelPack?, location: CLLocation?) {
        guard enabled, authorized, cameraActive, let session, let pack, emission.event.source == .liveFrame, !framePending else { return }
        framePending = true
        let cropRequested = cropsAuthorized, token = generation
        let app = ["platform": "ios", "version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.4",
                   "build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown"]
        perform(refreshAfter: false) { [capture, weak self] store in
            defer { Task { @MainActor in self?.framePending = false } }
            guard store.isAuthorized(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure) else { return }
            let path = pack.directoryURL.appendingPathComponent("manifest.json").path
            let hash: String
            if let verified = pack.manifestSHA256 { hash = verified }
            else if let saved = capture.packHashes[path] { hash = saved }
            else { hash = SignCollectionJSON.sha256(try Data(contentsOf: URL(fileURLWithPath: path))); capture.packHashes[path] = hash }
            let event = emission.event, at = event.frameTimestampUtc
            let country = pack.manifest.countries.first(where: { $0.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil }) ?? "unknown"
            let components: [[String: Any]] = event.modelComponents.map {
                ["role": $0.role, "artifact_sha256": $0.artifactSHA256.lowercased(), "preprocessing_version": $0.preprocessingVersion,
                 "calibration_id": $0.calibrationID.isEmpty ? NSNull() : $0.calibrationID as Any, "calibration_sha256": NSNull()]
            }
            guard !components.isEmpty else { return }
            let model: [String: Any] = ["pack_id": event.packId, "pack_version": "manifest-schema-\(pack.manifest.schemaVersion)", "pack_sha256": hash, "components": components]
            let position = Self.position(location, at: at)
            let eligible = Array(emission.collectionDetections.filter { $0.boundingBox.isValid && $0.rawScore.isFinite && $0.rawScore >= $0.classThreshold }.prefix(64))
            let presentationMatches = event.candidate.map { candidate in eligible.filter { $0.rawLabel == candidate.rawLabel && $0.boundingBox.intersectionOverUnion(with: candidate.boundingBox) >= 0.5 }.count } ?? 0
            let detections = eligible.map { detection -> SignCollectionObserver.Detection in
                let box = detection.boundingBox
                let mapping = pack.manifest.classMapping.first { $0.classId == detection.rawClassId }
                let classification: [String: Any] = ["country": country, "model_label": detection.rawLabel, "canonical_code": NSNull(),
                    "family": detection.semantic.kind.rawValue, "value": detection.semantic.value as Any? ?? NSNull(), "unit": detection.semantic.unit as Any? ?? NSNull(),
                    "role": mapping.map { $0.signRole == .supplementaryPlate ? "supplementary" : "primary" } ?? "unknown", "mapping_revision": NSNull(), "mapping_sha256": NSNull(), "alternatives": []]
                let scores: [String: Any] = ["detector_raw": detection.detectorRawScore as Any? ?? (pack.manifest.pipeline == .directDetection ? detection.rawScore as Any : NSNull()),
                    "classifier_raw": detection.classifierRawScore as Any? ?? NSNull(), "raw_domain": "model_declared_score_0_1", "calibrated_confidence": NSNull(), "track_support": 0]
                let evidence: [String: Any] = ["track_id": NSNull(), "assembly_id": detection.assemblyId as Any? ?? NSNull(), "analyzed_frames": 0,
                    "finalization_reason": "qualified_track", "quality_flags": position is NSNull ? ["gps_missing", "manifest_schema_version"] : ["manifest_schema_version"],
                    "normalized_box": ["x": box.x, "y": box.y, "width": box.width, "height": box.height]]
                let payload: [String: Any] = ["schema_version": 1, "collection_session_id": session, "observer_version": "sighting-observer-1",
                    "source_kind": "detector", "app": app, "clock_quality": "device_unverified", "vehicle_position": position,
                    "sign_position": NSNull(), "classification": classification, "scores": scores, "model": model, "evidence": evidence, "road_context": NSNull(), "media_refs": []]
                let presentation = event.candidate.flatMap { presentationMatches == 1 && $0.rawLabel == detection.rawLabel && $0.boundingBox.intersectionOverUnion(with: box) >= 0.5 ? $0.trackId : nil }
                return .init(key: hash + ":" + detection.rawLabel, box: [box.x,box.y,box.width,box.height], payload: payload, presentationTrack: presentation)
            }
            var cropCount = 0, upright: CGImage?
            try capture.observer.observe(at: at, detections: detections) { observation in
                try store.enqueue(kind: "sighting", event: observation, disclosure: SignCollectionCapabilities.metadataDisclosure)
                guard cropRequested, cropCount < 4, let frame = emission.collectionFrame,
                      let box = (observation["evidence"] as? [String: Any])?["normalized_box"] as? [String: Double] else { return }
                do {
                    let claim = try store.claim(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure)
                    cropCount += 1
                    if upright == nil { upright = try frame.image() }
                    let crop = try SignCollectionCrop.generate(upright: upright!, box: box, hashSource: false)
                    let metadata = crop.metadata(cropID: SignCollectionJSON.uuid(), observationID: observation["event_id"] as! String,
                        installationID: try store.installationID, epoch: try store.collectionEpoch, sourceKind: "detector", frameAt: at,
                        localFrameToken: frame.token, privacyPreflight: "passed", redactionVersion: "metadata-strip-1", collectionClaim: claim)
                    try store.enqueueAutomaticCrop(metadata: metadata, bytes: crop.bytes)
                } catch { Task { @MainActor [weak self] in if self?.generation == token { self?.status = "crop_capture_unavailable" } } }
            }
        }
    }
    func freezeCorrection(attempt: String, presentation: String?) { perform { [capture] _ in capture.observer.freeze(attempt: attempt, presentation: presentation) } }
    func correct(attempt: String, modality: String) {
        perform { [capture] store in if let correction = capture.observer.correction(attempt: attempt, modality: modality, at: Date()) {
            try store.enqueue(kind: "correction", event: correction, disclosure: SignCollectionCapabilities.metadataDisclosure)
        } }
    }
    nonisolated private static func position(_ fix: CLLocation?, at: Date) -> Any {
        guard let fix, CLLocationCoordinate2DIsValid(fix.coordinate), fix.horizontalAccuracy.isFinite, fix.horizontalAccuracy >= 0,
              fix.horizontalAccuracy <= 100_000, abs(at.timeIntervalSince(fix.timestamp)) <= 30 else { return NSNull() }
        return ["latitude": fix.coordinate.latitude, "longitude": fix.coordinate.longitude, "horizontal_accuracy_m": fix.horizontalAccuracy,
                "fix_at": SignCollectionJSON.utc(fix.timestamp), "frame_fix_delta_ms": at.timeIntervalSince(fix.timestamp)*1000,
                "source": "core_location", "alignment": "nearest_fix", "course_degrees": (0..<360).contains(fix.course) ? fix.course as Any : NSNull(),
                "course_accuracy_degrees": (0...180).contains(fix.courseAccuracy) ? fix.courseAccuracy as Any : NSNull()]
    }
}

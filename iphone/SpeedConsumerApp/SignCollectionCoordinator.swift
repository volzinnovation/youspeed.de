import Foundation
import Combine
import CoreLocation
import Network
import CoreGraphics
import CoreMotion

/// Ordinary camera collection. The camera does not wait for this controller.
@MainActor final class SignCollectionCoordinator: ObservableObject {
    @Published private(set) var enabled: Bool
    @Published private(set) var authorized = false
    @Published private(set) var cropsAuthorized = false
    private var locations: [CLLocation] = []
    private var framePending = false
    @Published private(set) var consentPresented = false
    @Published private(set) var status = "idle"
    @Published private(set) var deletions: [[String: Bool]] = []
    private let cameraDirection = SignCollectionCameraDirection()
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
    private var interestTask: Task<Void, Never>?
    private let interestHTTP = SignCollectionInterestHTTP()
    private var interestGeneration = 0
    private var interestActivation = SignCollectionInterestActivation()
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
    deinit { timer?.invalidate(); monitor.cancel(); upload?.cancel(); interestTask?.cancel(); interestHTTP.close(); client?.close() }
    /// App launch with TSR enabled, or the setting's false-to-true transition.
    /// Foreground, model reload, network changes and timers do not refetch.
    func visualTSRChanged(enabled: Bool) {
        let activate = interestActivation.update(enabled)
        if !enabled { interestGeneration += 1; interestTask?.cancel(); interestTask = nil }
        guard activate, interestTask == nil, let interests = foundation.interests else { return }
        interestGeneration += 1
        let requestGeneration = interestGeneration
        interestTask = Task { [weak self, interestHTTP] in
            defer { if self?.interestGeneration == requestGeneration { self?.interestTask = nil } }
            do {
                let response = try await interestHTTP.fetch(etag: interests.etag)
                try Task.checkCancellation()
                if response.status == 200 { try interests.install(response.data) }
                else if response.status != 304 || interests.etag == nil { throw SignCollectionError.invalidContract }
            } catch { /* Keep a usable cached plan; otherwise only bad crops remain eligible. */ }
        }
    }
    func cameraChanged(active: Bool) {
        let becameActive = active && !cameraActive
        cameraActive = active
        cameraDirection.setActive(active && authorized && enabled)
        if becameActive {
            if session == nil { session = SignCollectionJSON.uuid() }
            let id = session!
            perform { store in try store.beginSession(id) }
            requestConsent()
        }
        if !active { locations.removeAll(); deliver() }
    }
    func endSession() {
        cameraDirection.setActive(false); locations.removeAll()
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
        cameraDirection.setActive(false); locations.removeAll()
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
                self.cameraDirection.setActive(self.cameraActive && self.authorized && self.enabled)
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
            let delay: TimeInterval?
            if ["crop_sent", "metadata_sent", "crop_dropped", "metadata_dropped", "batch_split"].contains(result) { delay = 1 }
            else if ["backoff", "crop_delivery_unavailable", "delivery_unavailable"].contains(result) {
                delay = (try? await worker.retryDelay()) ?? 60
            } else { delay = nil }
            guard let self, token == self.generation else { return }
            if !self.privacyChangePending { self.status = result }
            self.upload = nil; self.refresh()
            if let delay {
                Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
                    Task { @MainActor in if self?.generation == token { self?.deliver() } }
                }
            }
        }
    }
    func recordLocation(_ location: CLLocation) {
        guard enabled, authorized, cameraActive else { return }
        if locations.last?.timestamp != location.timestamp { locations.append(location) }
        if locations.count > 120 { locations.removeFirst(locations.count - 120) }
    }
    func observe(_ emission: TrafficSignRuntimeEmission, pack: TrafficSignVerifiedModelPack?, location: CLLocation?) {
        guard enabled, authorized, cameraActive, emission.event.source == .liveFrame else { return }
        defer { if let actual = emission.ocrAttemptAnnotation ?? emission.ocrAnnotation { updateSupplementaryOCR(actual) } }
        guard let session, let pack, !framePending else { return }
        // Freeze both measurements before inference/storage can advance to another frame.
        if let location { recordLocation(location) }
        guard let frameAt = emission.collectionCaptureAt else {
            perform(refreshAfter: false) { [capture] _ in capture.observer.reset() }
            return
        }
        let nearestFix = locations.min { abs($0.timestamp.timeIntervalSince(frameAt)) < abs($1.timestamp.timeIntervalSince(frameAt)) }
        let framePosition = Self.position(nearestFix, at: frameAt)
        guard let position = framePosition as? [String: Any],
              let delta = position["frame_fix_delta_ms"] as? Double, abs(delta) <= 5000,
              let frameDirection = cameraDirection.history.direction(at: frameAt) else {
            perform(refreshAfter: false) { [capture] _ in capture.observer.reset() }
            return
        }
        framePending = true
        let cropRequested = cropsAuthorized, token = generation
        let supplementaryOCR = (emission.ocrAttemptAnnotation ?? emission.ocrAnnotation).flatMap(Self.collectionOCRAnnotation)
        let interests = foundation.interests
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
            let event = emission.event, at = frameAt
            let country = pack.manifest.countries.first(where: { $0.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil }) ?? "unknown"
            let components: [[String: Any]] = event.modelComponents.map {
                ["role": $0.role, "artifact_sha256": $0.artifactSHA256.lowercased(), "preprocessing_version": $0.preprocessingVersion,
                 "calibration_id": $0.calibrationID.isEmpty ? NSNull() : $0.calibrationID as Any, "calibration_sha256": NSNull()]
            }
            guard !components.isEmpty else { return }
            let model: [String: Any] = ["pack_id": event.packId, "pack_version": "manifest-schema-\(pack.manifest.schemaVersion)", "pack_sha256": hash, "components": components]
            let position = framePosition
            let deviceID = try store.installationID
            let eligible = Array(emission.collectionDetections.filter { $0.boundingBox.isValid && $0.rawScore.isFinite && $0.rawScore >= $0.classThreshold }.prefix(64))
            let annotationMatches = eligible.filter { detection in
                let box = detection.boundingBox
                return supplementaryOCR?.matches(modelLabel: detection.rawClassId, speedKmh: detection.semantic.value,
                    box: [box.x, box.y, box.width, box.height]) == true
            }.count
            let presentationMatches = event.candidate.map { candidate in eligible.filter { $0.rawLabel == candidate.rawLabel && $0.boundingBox.intersectionOverUnion(with: candidate.boundingBox) >= 0.5 }.count } ?? 0
            let detections = eligible.map { detection -> SignCollectionObserver.Detection in
                let box = detection.boundingBox
                let mapping = pack.manifest.classMapping.first { $0.classId == detection.rawClassId }
                let classification: [String: Any] = ["country": country, "model_label": detection.rawClassId, "canonical_code": NSNull(),
                    "family": detection.semantic.kind.rawValue, "value": detection.semantic.value as Any? ?? NSNull(), "unit": detection.semantic.unit as Any? ?? NSNull(),
                    "role": mapping.map { $0.signRole == .supplementaryPlate ? "supplementary" : "primary" } ?? "unknown", "mapping_revision": NSNull(), "mapping_sha256": NSNull(), "alternatives": []]
                let scores: [String: Any] = ["detector_raw": detection.detectorRawScore as Any? ?? (pack.manifest.pipeline == .directDetection ? detection.rawScore as Any : NSNull()),
                    "classifier_raw": detection.classifierRawScore as Any? ?? NSNull(), "raw_domain": "model_declared_score_0_1", "calibrated_confidence": NSNull(), "track_support": 0]
                let evidence: [String: Any] = ["track_id": NSNull(), "assembly_id": detection.assemblyId as Any? ?? NSNull(), "analyzed_frames": 0,
                    "finalization_reason": "qualified_track", "quality_flags": position is NSNull ? ["gps_missing", "manifest_schema_version"] : ["manifest_schema_version"],
                    "normalized_box": ["x": box.x, "y": box.y, "width": box.width, "height": box.height]]
                let payload: [String: Any] = ["schema_version": 1, "collection_session_id": session, "observer_version": "sighting-observer-2",
                    "capture_metadata_version": 1, "device_id": deviceID, "camera_viewing_direction": frameDirection,
                    "source_kind": "detector", "app": app, "clock_quality": "device_unverified", "vehicle_position": position,
                    "sign_position": NSNull(), "classification": classification, "scores": scores, "model": model, "evidence": evidence, "road_context": NSNull(), "media_refs": []]
                let presentation = event.candidate.flatMap { presentationMatches == 1 && $0.rawLabel == detection.rawLabel && $0.boundingBox.intersectionOverUnion(with: box) >= 0.5 ? $0.trackId : nil }
                let annotation = annotationMatches == 1 && supplementaryOCR?.matches(modelLabel: detection.rawClassId,
                    speedKmh: detection.semantic.value, box: [box.x,box.y,box.width,box.height]) == true ? supplementaryOCR : nil
                return .init(key: hash + ":" + detection.rawLabel, box: [box.x,box.y,box.width,box.height],
                    payload: payload, presentationTrack: presentation, supplementaryOCR: annotation)
            }
            var cropCount = 0
            try capture.observer.observe(at: at, detections: detections, frameID: event.frameId, captureCrop: { candidate in
                guard cropRequested, cropCount < 4, let frame = emission.collectionFrame,
                      candidate.box.count == 4, candidate.selection?.permits(at: Date()) != false else { return .skipped }
                let box = Dictionary(uniqueKeysWithValues: zip(["x", "y", "width", "height"], candidate.box))
                do {
                    cropCount += 1
                    let claim = try store.claim(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure)
                    let crop = try frame.crop(box: box)
                    var metadata = crop.metadata(cropID: SignCollectionJSON.uuid(), observationID: candidate.observationID,
                        installationID: try store.installationID, epoch: try store.collectionEpoch, sourceKind: "detector", frameAt: candidate.frameAt,
                        localFrameToken: frame.token, privacyPreflight: "passed", redactionVersion: "metadata-strip-1", collectionClaim: claim,
                        vehiclePosition: framePosition, cameraViewingDirection: frameDirection)
                    if let selection = candidate.selection { metadata["collection_selection"] = selection.wire }
                    if let annotation = candidate.supplementaryOCR { metadata["supplementary_ocr"] = annotation.wire }
                    try store.enqueueAutomaticCrop(metadata: metadata, bytes: crop.bytes)
                    return .stored
                } catch {
                    Task { @MainActor [weak self] in if self?.generation == token { self?.status = "crop_capture_unavailable" } }
                    return .failed
                }
            }, selectCrop: { payload, observationID in
                let c = payload["classification"] as! [String: Any]
                let identity = SignCollectionInterestPlan.Identity(country: country, pack: hash,
                    classifier: event.modelComponents.first { $0.role == "semantic_classifier" }?.artifactSHA256.lowercased() ?? "",
                    label: c["model_label"] as? String ?? "")
                return interests?.select(identity, observation: observationID)
                    ?? .init(revision: nil, key: nil, decision: SignCollectionInterestPlan.isAlways(identity.label) ? "always" : "no_valid_plan",
                             fraction: SignCollectionInterestPlan.isAlways(identity.label) ? ["numerator": 1, "denominator": 1] : nil, expires: nil)
            }) { observation in
                try store.enqueue(kind: "sighting", event: observation, disclosure: SignCollectionCapabilities.metadataDisclosure)
            }
        }
    }
    /// This lane accepts completion after the primary frame was already stored.
    func updateSupplementaryOCR(_ source: TrafficSignSupplementaryOCRAnnotation) {
        guard enabled, authorized, cameraActive, session != nil,
              let annotation = Self.collectionOCRAnnotation(source) else { return }
        perform { [capture] store in
            guard store.isAuthorized(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure) else { return }
            try capture.observer.recordSupplementaryOCR(annotation, at: Date()) { event in
                try store.enqueue(kind: "media_status", event: event, disclosure: SignCollectionCapabilities.metadataDisclosure)
            }
        }
    }
    func freezeCorrection(attempt: String, presentation: String?) { perform { [capture] _ in capture.observer.freeze(attempt: attempt, presentation: presentation) } }
    nonisolated private static func collectionOCRAnnotation(_ source: TrafficSignSupplementaryOCRAnnotation) -> SupplementaryOCRAnnotation? {
        let box = source.primaryBoundingBox
        let ocrBox = source.ocrBoundingBox.map { SupplementaryOCRAnnotation.Box(x: $0.x, y: $0.y, width: $0.width, height: $0.height) }
        guard let status = SupplementaryOCRAnnotation.Status(rawValue: source.readStatus.rawValue) else { return nil }
        return SupplementaryOCRAnnotation(primaryClassID: source.primaryClassID, primarySpeedKmh: source.primarySpeedKmh,
            physicalSignID: source.physicalSignID, frameID: source.frameID, observedAt: source.sourceObservedAt,
            firstSeenAt: source.firstSeenAt, rawText: source.rawText, status: status,
            primaryBox: .init(x: box.x, y: box.y, width: box.width, height: box.height), ocrBox: ocrBox,
            engine: source.engine, modelVersion: source.modelVersion,
            parsedTimeWindow: source.window.map { .init(startMinutes: $0.startMinutes, endMinutes: $0.endMinutes) })
    }
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


/// Core Motion's matrix maps true-north/West/up into device coordinates.
/// Transpose it to transform the rear camera's fixed device axis (0,0,-1).
private final class SignCollectionCameraDirection {
    private(set) var history = SignCollectionCameraHistory()
    private let motion = CMMotionManager()
    private let queue: OperationQueue = { let q = OperationQueue(); q.maxConcurrentOperationCount = 1; return q }()
    private var active = false
    func setActive(_ value: Bool) {
        guard value != active else { return }
        active = value
        motion.stopDeviceMotionUpdates(); queue.cancelAllOperations(); history = SignCollectionCameraHistory()
        guard value, motion.isDeviceMotionAvailable,
              CMMotionManager.availableAttitudeReferenceFrames().contains(.xTrueNorthZVertical) else { return }
        motion.deviceMotionUpdateInterval = 0.05
        motion.showsDeviceMovementDisplay = false
        let bootUTC = Date().timeIntervalSince1970 - ProcessInfo.processInfo.systemUptime
        let history = self.history
        motion.startDeviceMotionUpdates(using: .xTrueNorthZVertical, to: queue) { data, _ in
            guard let data, data.heading.isFinite, data.heading >= 0 else { history.clear(); return }
            let accuracy: String
            switch data.magneticField.accuracy {
            case .high: accuracy = "high"
            case .medium: accuracy = "medium"
            default: history.clear(); return
            }
            let r = data.attitude.rotationMatrix, g = data.gravity
            // Fail closed if the reference/matrix convention is not as expected.
            guard abs(r.m13 + g.x) < 0.05, abs(r.m23 + g.y) < 0.05, abs(r.m33 + g.z) < 0.05,
                  let sample = SignCollectionCameraSample.coreMotionMatrix([r.m11,r.m12,r.m13,r.m21,r.m22,r.m23,r.m31,r.m32,r.m33],
                    at: Date(timeIntervalSince1970: bootUTC + data.timestamp), accuracy: accuracy) else { history.clear(); return }
            history.append(sample)
        }
    }
    deinit { motion.stopDeviceMotionUpdates(); queue.cancelAllOperations() }
}

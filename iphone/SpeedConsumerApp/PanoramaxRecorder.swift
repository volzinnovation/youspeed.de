import AVFoundation
import CoreLocation
import Foundation
import ImageIO
import SwiftUI
import UIKit

enum PanoramaxRecorderState: Equatable {
    case disabled
    case preparing
    case recording
    case denied
    case unavailable
    case failed
}

/// Owns the rear-camera photo session used by Panoramax. The speed-limit UI and
/// this recorder only share location samples; neither feature triggers the other.
@MainActor
final class PanoramaxRecorder: NSObject, ObservableObject {
    let session = AVCaptureSession()

    @Published private(set) var state: PanoramaxRecorderState = .disabled
    @Published private(set) var capturedImageCount = 0
    @Published private(set) var lastCaptureAt: Date?
    @Published private(set) var lastCaptureDetail = "Noch keine Aufnahme"
    @Published private(set) var lastAccuracyMeters: Double?

    var onChange: (() -> Void)?

    private let queueStore: PanoramaxQueueStore?
    private let sessionQueue = DispatchQueue(label: "de.youspeed.panoramax.camera")
    private let cadenceConfiguration = PanoramaxCadenceConfiguration()
    private var batch: PanoramaxBatchRecord?
    private var lastCaptureSample: PanoramaxLocationSample?
    private var pendingSample: PanoramaxLocationSample?
    private var photoInFlight = false
    private var configured = false

    init(queueStore: PanoramaxQueueStore?) {
        self.queueStore = queueStore
        super.init()
    }

    func startRecording() {
        guard state != .recording, state != .preparing else {
            return
        }
        guard let queueStore else {
            state = .failed
            lastCaptureDetail = "Panoramax-Speicher nicht verfuegbar"
            notifyChange()
            return
        }

        state = .preparing
        lastCaptureDetail = "Kamera wird vorbereitet"
        notifyChange()
        Task { @MainActor [weak self] in
            guard let self else { return }
            guard await AVCaptureDevice.requestAccess(for: .video) else {
                state = .denied
                lastCaptureDetail = "Kamerazugriff verweigert"
                notifyChange()
                return
            }
            do {
                try configureSessionIfNeeded()
                batch = try queueStore.createBatch(captureSessionID: UUID().uuidString)
            } catch {
                state = .failed
                lastCaptureDetail = "Kamera konnte nicht gestartet werden"
                notifyChange()
                return
            }
            sessionQueue.async { [weak self] in
                guard let self else { return }
                self.session.startRunning()
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    state = .recording
                    lastCaptureDetail = "Drive Recorder aktiv"
                    notifyChange()
                }
            }
        }
    }

    func stopRecording() {
        guard state == .recording || state == .preparing else {
            return
        }
        sessionQueue.async { [weak self] in
            self?.session.stopRunning()
        }
        if var batch {
            batch.state = .awaitingReview
            try? queueStore?.updateBatch(batch)
        }
        batch = nil
        pendingSample = nil
        lastCaptureSample = nil
        photoInFlight = false
        state = .disabled
        lastCaptureDetail = capturedImageCount > 0
            ? "\(capturedImageCount) Bilder fuer die Nachbearbeitung gespeichert"
            : "Keine Bilder gespeichert"
        notifyChange()
    }

    func ingest(location: CLLocation) {
        guard state == .recording, !photoInFlight, let batch else {
            return
        }
        let accuracy = location.horizontalAccuracy
        guard accuracy >= 0, accuracy.isFinite else {
            return
        }
        let heading: Double?
        if location.course >= 0, location.course <= 360, location.courseAccuracy >= 0 {
            heading = location.course
        } else {
            heading = nil
        }
        let sample = PanoramaxLocationSample(
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            capturedAt: location.timestamp,
            accuracyMeters: accuracy,
            altitudeMeters: location.altitude.isFinite ? location.altitude : nil,
            headingDegrees: heading
        )
        lastAccuracyMeters = accuracy
        guard PanoramaxCapturePolicy.shouldCapture(
            lastCapture: lastCaptureSample,
            current: sample,
            configuration: cadenceConfiguration
        ) else {
            notifyChange()
            return
        }

        pendingSample = sample
        photoInFlight = true
        let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
        settings.isHighResolutionPhotoEnabled = true
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
    }

    private let photoOutput = AVCapturePhotoOutput()

    private func configureSessionIfNeeded() throws {
        guard !configured else { return }
        session.beginConfiguration()
        defer { session.commitConfiguration() }
        session.sessionPreset = .photo
        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            state = .unavailable
            lastCaptureDetail = "Keine Rueckkamera verfuegbar"
            throw RecorderError.cameraUnavailable
        }
        let input = try AVCaptureDeviceInput(device: camera)
        guard session.canAddInput(input), session.canAddOutput(photoOutput) else {
            state = .unavailable
            lastCaptureDetail = "Kamera-Session nicht verfuegbar"
            throw RecorderError.sessionUnavailable
        }
        session.addInput(input)
        session.addOutput(photoOutput)
        photoOutput.isHighResolutionCaptureEnabled = true
        configured = true
    }

    private func finishPhoto(data: Data?, error: Error?) {
        defer {
            photoInFlight = false
            pendingSample = nil
            notifyChange()
        }
        guard let data, let sample = pendingSample, let batch, let queueStore else {
            lastCaptureDetail = error == nil ? "Aufnahme verworfen" : "Aufnahme fehlgeschlagen"
            return
        }
        let panoramaxJPEG = Self.addLocationMetadata(to: data, sample: sample) ?? data
        guard let thumbnail = Self.makeThumbnail(from: panoramaxJPEG) else {
            lastCaptureDetail = "Vorschaubild konnte nicht erstellt werden"
            return
        }
        let metadata = PanoramaxCaptureMetadata(
            captureID: UUID().uuidString,
            captureSessionID: batch.captureSessionID,
            capturedAt: sample.capturedAt,
            location: sample,
            sha256: PanoramaxQueueStore.sha256(panoramaxJPEG),
            byteSize: Int64(panoramaxJPEG.count),
            software: "YouSpeed/1.0.1"
        )
        do {
            _ = try queueStore.addJPEG(batchID: batch.batchID, jpeg: panoramaxJPEG, thumbnail: thumbnail, metadata: metadata)
            lastCaptureSample = sample
            capturedImageCount += 1
            lastCaptureAt = sample.capturedAt
            lastCaptureDetail = "Aufnahme \(capturedImageCount) gespeichert"
        } catch {
            lastCaptureDetail = "Aufnahme konnte nicht gespeichert werden"
        }
    }

    private static func makeThumbnail(from data: Data) -> Data? {
        guard let image = UIImage(data: data),
              let thumbnail = image.preparingThumbnail(of: CGSize(width: 640, height: 360)) else {
            return nil
        }
        return thumbnail.jpegData(compressionQuality: 0.72)
    }

    /// Panoramax extracts position and capture time from standard JPEG metadata.
    /// Keep the original camera bytes when ImageIO cannot rewrite the image.
    private static func addLocationMetadata(to data: Data, sample: PanoramaxLocationSample) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let type = CGImageSourceGetType(source) else { return nil }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, type, 1, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any] else { return nil }
        var merged = properties
        var gps = (merged[kCGImagePropertyGPSDictionary as String] as? [String: Any]) ?? [:]
        let latitude = abs(sample.latitude)
        let longitude = abs(sample.longitude)
        gps[kCGImagePropertyGPSLatitude as String] = latitude
        gps[kCGImagePropertyGPSLatitudeRef as String] = sample.latitude >= 0 ? "N" : "S"
        gps[kCGImagePropertyGPSLongitude as String] = longitude
        gps[kCGImagePropertyGPSLongitudeRef as String] = sample.longitude >= 0 ? "E" : "W"
        if let altitude = sample.altitudeMeters, altitude.isFinite {
            gps[kCGImagePropertyGPSAltitude as String] = abs(altitude)
            gps[kCGImagePropertyGPSAltitudeRef as String] = altitude >= 0 ? 0 : 1
        }
        let timeFormatter = DateFormatter()
        timeFormatter.locale = Locale(identifier: "en_US_POSIX")
        timeFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        timeFormatter.dateFormat = "HH:mm:ss"
        let dateFormatter = DateFormatter()
        dateFormatter.locale = Locale(identifier: "en_US_POSIX")
        dateFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        dateFormatter.dateFormat = "yyyy:MM:dd"
        gps[kCGImagePropertyGPSTimeStamp as String] = timeFormatter.string(from: sample.capturedAt)
        gps[kCGImagePropertyGPSDateStamp as String] = dateFormatter.string(from: sample.capturedAt)
        if let heading = sample.headingDegrees, heading.isFinite, (0...360).contains(heading) {
            gps[kCGImagePropertyGPSImgDirection as String] = heading
            gps[kCGImagePropertyGPSImgDirectionRef as String] = "T"
        }
        merged[kCGImagePropertyGPSDictionary as String] = gps
        CGImageDestinationAddImageFromSource(destination, source, 0, merged as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }

    private func notifyChange() {
        onChange?()
    }

    enum RecorderError: Error {
        case cameraUnavailable
        case sessionUnavailable
    }
}

extension PanoramaxRecorder: AVCapturePhotoCaptureDelegate {
    nonisolated func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        let data = photo.fileDataRepresentation()
        Task { @MainActor [weak self] in
            self?.finishPhoto(data: data, error: error)
        }
    }
}

struct PanoramaxCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.videoPreviewLayer.session = session
        view.videoPreviewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        if uiView.videoPreviewLayer.session !== session {
            uiView.videoPreviewLayer.session = session
        }
    }

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var videoPreviewLayer: AVCaptureVideoPreviewLayer {
            guard let layer = layer as? AVCaptureVideoPreviewLayer else {
                fatalError("Expected AVCaptureVideoPreviewLayer")
            }
            return layer
        }
    }
}

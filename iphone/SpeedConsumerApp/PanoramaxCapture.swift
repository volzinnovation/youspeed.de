import Foundation
import CoreLocation

enum PanoramaxBatchState: String, Codable {
    case capturing
    case awaitingReview = "awaiting_review"
    case approved
    case creatingUploadSet = "creating_upload_set"
    case uploading
    case processing
    case complete
    case partial
    case blocked
}

enum PanoramaxItemState: String, Codable {
    case captured
    case included
    case excluded
    case queued
    case uploading
    case uploaded
    case accepted
    case duplicate
    case rejected
    case retryableError = "retryable_error"
    case permanentError = "permanent_error"
    /// The request was cancelled while its server outcome was unknown. It is
    /// intentionally not retried automatically because the server may already
    /// have accepted the bytes.
    case abandoned
}

struct PanoramaxLocationSample: Codable, Equatable {
    let latitude: Double
    let longitude: Double
    let capturedAt: Date
    let accuracyMeters: Double
    let altitudeMeters: Double?
    let headingDegrees: Double?
}

struct PanoramaxCaptureMetadata: Codable, Equatable {
    let captureID: String
    let captureSessionID: String
    let capturedAt: Date
    let location: PanoramaxLocationSample
    let sha256: String
    let byteSize: Int64
    let software: String

    func validate(now: Date? = nil) -> [String] {
        let reference = now ?? capturedAt
        var errors: [String] = []
        if captureID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors.append("captureID is missing") }
        if captureSessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors.append("captureSessionID is missing") }
        if capturedAt > reference.addingTimeInterval(60) { errors.append("capture time is in the future") }
        if !location.latitude.isFinite || !(-90...90).contains(location.latitude) { errors.append("latitude is invalid") }
        if !location.longitude.isFinite || !(-180...180).contains(location.longitude) { errors.append("longitude is invalid") }
        if !location.accuracyMeters.isFinite || location.accuracyMeters < 0 { errors.append("location accuracy is invalid") }
        if location.capturedAt > reference.addingTimeInterval(60) { errors.append("location time is in the future") }
        if abs(location.capturedAt.timeIntervalSince(capturedAt)) > 120 { errors.append("location is not associated with shutter time") }
        if let heading = location.headingDegrees, (!heading.isFinite || !(0...360).contains(heading)) { errors.append("heading is invalid") }
        if byteSize <= 0 { errors.append("image is empty") }
        if sha256.range(of: "^[0-9a-fA-F]{64}$", options: .regularExpression) == nil { errors.append("sha256 is invalid") }
        if software.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors.append("software provenance is missing") }
        return errors
    }
}

struct PanoramaxCadenceConfiguration: Equatable {
    var distanceMeters: Double = 25
    var fallbackInterval: TimeInterval = 5
    var maxLocationAge: TimeInterval = 10
    var maxAccuracyMeters: Double = 50
    var triggerMode: PanoramaxCaptureTriggerMode = .distance
}

enum PanoramaxCaptureTriggerMode: String, CaseIterable, Codable {
    case distance
    case time

    var label: String {
        switch self {
        case .distance: return NSLocalizedString("panoramax.settings.trigger_distance", comment: "")
        case .time: return NSLocalizedString("panoramax.settings.trigger_time", comment: "")
        }
    }
}

enum PanoramaxCapturePolicy {
    static func shouldCapture(
        lastCapture: PanoramaxLocationSample?,
        current: PanoramaxLocationSample,
        now: Date? = nil,
        configuration: PanoramaxCadenceConfiguration = .init()
    ) -> Bool {
        let reference = now ?? current.capturedAt
        guard current.capturedAt <= reference.addingTimeInterval(60),
              reference.timeIntervalSince(current.capturedAt) <= configuration.maxLocationAge,
              current.accuracyMeters.isFinite,
              current.accuracyMeters >= 0,
              current.accuracyMeters <= configuration.maxAccuracyMeters else { return false }
        guard let previous = lastCapture else { return true }
        guard current.capturedAt > previous.capturedAt else { return false }
        let precisionMovement = 2 * max(current.accuracyMeters, previous.accuracyMeters)
        let distance = distanceMeters(from: previous, to: current)
        guard distance >= precisionMovement else { return false }
        switch configuration.triggerMode {
        case .distance:
            return distance >= max(configuration.distanceMeters, precisionMovement)
        case .time:
            return current.capturedAt.timeIntervalSince(previous.capturedAt) >= configuration.fallbackInterval
        }
    }

    static func distanceMeters(from first: PanoramaxLocationSample, to second: PanoramaxLocationSample) -> Double {
        CLLocation(latitude: first.latitude, longitude: first.longitude)
            .distance(from: CLLocation(latitude: second.latitude, longitude: second.longitude))
    }
}

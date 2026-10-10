import Foundation

struct DrivingControlAvailability {
    static let controlsSpeedThresholdKmh = 4.0
    let controlsAllowed: Bool
    let stationaryObservedAt: Date?

    static func updated(previouslyAllowed: Bool, rawSpeedMetersPerSecond: Double,
                        displayedSpeedKmh: Double, horizontalAccuracyMeters: Double,
                        observedAt: Date, now: Date) -> Self {
        let validSpeed = rawSpeedMetersPerSecond.isFinite && rawSpeedMetersPerSecond >= 0
        if displayedSpeedKmh >= controlsSpeedThresholdKmh ||
            (validSpeed && rawSpeedMetersPerSecond >= controlsSpeedThresholdKmh / 3.6) {
            return Self(controlsAllowed: false, stationaryObservedAt: nil)
        }
        let age = now.timeIntervalSince(observedAt)
        let fresh = age >= 0 && age <= 3
        guard validSpeed, horizontalAccuracyMeters.isFinite, horizontalAccuracyMeters >= 0,
              displayedSpeedKmh.isFinite, displayedSpeedKmh >= 0, fresh else {
            return Self(controlsAllowed: previouslyAllowed, stationaryObservedAt: nil)
        }
        let stopped = rawSpeedMetersPerSecond == 0 && displayedSpeedKmh == 0
        // Low-speed controls do not establish standstill for permission dialogs.
        return Self(controlsAllowed: true, stationaryObservedAt: stopped ? observedAt : nil)
    }
}

/// Independent of the four-km/h lock for navigation/settings. Manual capture
/// never changes that lock or opens a permission/settings sheet.
enum DrivingPhotoPolicy {
    static let speedThresholdKmh = 1.0
    static let minimumTapInterval: TimeInterval = 0.5

    static func showsButton(speedKmh: Double) -> Bool {
        speedKmh.isFinite && speedKmh > speedThresholdKmh
    }

    static func locationIsUsable(latitude: Double, longitude: Double, accuracy: Double,
                                 timestamp: Date, now: Date,
                                 maxAge: TimeInterval = 10, maxAccuracy: Double = 50) -> Bool {
        let age = now.timeIntervalSince(timestamp)
        return latitude.isFinite && (-90...90).contains(latitude)
            && longitude.isFinite && (-180...180).contains(longitude)
            && accuracy.isFinite && accuracy >= 0 && accuracy <= maxAccuracy
            && age >= -60 && age <= maxAge
    }

    static func canCapture(recording: Bool, cameraAuthorized: Bool, photoOutputAvailable: Bool,
                           storageReady: Bool, photoInFlight: Bool, locationUsable: Bool,
                           lastRequestAt: Date?, now: Date) -> Bool {
        recording && cameraAuthorized && photoOutputAvailable && storageReady
            && !photoInFlight && locationUsable
            && (lastRequestAt.map { now.timeIntervalSince($0) >= minimumTapInterval } ?? true)
    }
}

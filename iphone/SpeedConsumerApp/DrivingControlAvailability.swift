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

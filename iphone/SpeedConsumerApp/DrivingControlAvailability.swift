import Foundation

struct DrivingControlAvailability {
    let controlsAllowed: Bool
    let stationaryObservedAt: Date?

    static func updated(previouslyAllowed: Bool, rawSpeedMetersPerSecond: Double,
                        displayedSpeedKmh: Double, horizontalAccuracyMeters: Double,
                        observedAt: Date, now: Date) -> Self {
        let validSpeed = rawSpeedMetersPerSecond.isFinite && rawSpeedMetersPerSecond >= 0
        if displayedSpeedKmh > 0 || (validSpeed && rawSpeedMetersPerSecond > 0) {
            return Self(controlsAllowed: false, stationaryObservedAt: nil)
        }
        let age = now.timeIntervalSince(observedAt)
        let fresh = age >= 0 && age <= 3
        guard validSpeed, horizontalAccuracyMeters.isFinite, horizontalAccuracyMeters >= 0,
              displayedSpeedKmh.isFinite, fresh else {
            return Self(controlsAllowed: previouslyAllowed, stationaryObservedAt: nil)
        }
        let stopped = rawSpeedMetersPerSecond == 0 && displayedSpeedKmh == 0
        return Self(controlsAllowed: stopped, stationaryObservedAt: stopped ? observedAt : nil)
    }
}

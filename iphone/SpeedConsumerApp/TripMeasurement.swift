import Foundation

/// Version 1: use the same accuracy/movement gates on both platforms.
enum TripMeasurement {
    static func acceptedDistance(seconds: Double, metres: Double, accuracy: Double, previousAccuracy: Double, speed: Double) -> Double {
        guard [seconds,metres,accuracy,previousAccuracy,speed].allSatisfy({$0.isFinite}),
              seconds > 0, seconds <= 15, metres >= max(3,max(accuracy,previousAccuracy)),
              metres/seconds <= 70, speed > 0.5 else { return 0 }
        return (metres * 1000).rounded() / 1000
    }
}

import Foundation

/// Causal GNSS search hint only. It neither projects pixels nor supplies observed lane points.
struct RoadBoundaryMotionSample {
    let timeSeconds, speedMetersPerSecond, courseDegrees, horizontalAccuracyMeters, courseAccuracyDegrees: Double
}
struct RoadBoundaryMotionHint {
    let used: Bool
    let reason: String
    var sourceAgeSeconds: Double? = nil
    var speedMetersPerSecond: Double? = nil
    var courseAccuracyDegrees: Double? = nil
    var pairIntervalSeconds: Double? = nil
    var headingDeltaDegrees: Double? = nil
    var headingRateDegreesPerSecond: Double? = nil
    var horizontalSearchRadiusFloor = 0
    var diagnosticFields: [String:Any] {
        ["used":used,"reason":reason,"sourceAgeSeconds":sourceAgeSeconds as Any? ?? NSNull(),
         "speedMetersPerSecond":speedMetersPerSecond as Any? ?? NSNull(),"courseAccuracyDegrees":courseAccuracyDegrees as Any? ?? NSNull(),
         "pairIntervalSeconds":pairIntervalSeconds as Any? ?? NSNull(),"headingDeltaDegrees":headingDeltaDegrees as Any? ?? NSNull(),
         "headingRateDegreesPerSecond":headingRateDegreesPerSecond as Any? ?? NSNull(),
         "horizontalSearchRadiusFloor":horizontalSearchRadiusFloor]
    }
    static func from(samples: [RoadBoundaryMotionSample], capturedAtSeconds: Double, clockKnown: Bool) -> Self {
        guard clockKnown,capturedAtSeconds.isFinite else { return Self(used:false,reason:"capture_clock_unknown") }
        let causal=samples.suffix(32).filter { $0.timeSeconds.isFinite && $0.timeSeconds<=capturedAtSeconds }
        guard let latest=causal.last else { return Self(used:false,reason:"no_causal_fix") }
        let age=capturedAtSeconds-latest.timeSeconds
        func reject(_ reason: String) -> Self { Self(used:false,reason:reason,sourceAgeSeconds:age,
            speedMetersPerSecond:latest.speedMetersPerSecond,courseAccuracyDegrees:latest.courseAccuracyDegrees) }
        // Session ingestion already owns GPS validity. Do not introduce a second health policy.
        func valid(_ s: RoadBoundaryMotionSample) -> Bool {
            [s.speedMetersPerSecond,s.courseDegrees,s.horizontalAccuracyMeters,s.courseAccuracyDegrees].allSatisfy(\.isFinite) &&
            s.speedMetersPerSecond>=0 && (0..<360).contains(s.courseDegrees)
        }
        guard valid(latest) else { return reject("invalid_fix") }
        guard let before=causal.dropLast().last(where:{ $0.timeSeconds<latest.timeSeconds }) else { return reject("insufficient_history") }
        guard valid(before) else { return reject("invalid_fix") }
        let interval=latest.timeSeconds-before.timeSeconds
        let delta=(latest.courseDegrees-before.courseDegrees+540).truncatingRemainder(dividingBy:360)-180
        let rate=delta/interval
        guard rate.isFinite else { return reject("invalid_fix_interval") }
        let turning=latest.speedMetersPerSecond>0 && abs(rate)>6
        return Self(used:turning,reason:turning ? "turn_search_hint" : "no_moving_turn",sourceAgeSeconds:age,
            speedMetersPerSecond:latest.speedMetersPerSecond,courseAccuracyDegrees:latest.courseAccuracyDegrees,
            pairIntervalSeconds:interval,headingDeltaDegrees:delta,headingRateDegreesPerSecond:rate,
            horizontalSearchRadiusFloor:turning ? 12 : 0)
    }
}

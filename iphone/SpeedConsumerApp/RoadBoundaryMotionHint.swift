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

/// Approximate road-plane motion is a search prior only; patches independently confirm it.
struct RoadBoundaryMotionProjection {
    private let c: RoadPathCalibration
    private let pitch, speed, yawRate, sourceAge: Double
    func project(_ point: LanePoint, dt: Double) -> LanePoint? {
        guard dt.isFinite, dt > 0, dt <= 0.75, speed*dt <= 8 else { return nil }
        let r=c.rollDegrees * .pi/180, yaw=c.yawDegrees * .pi/180
        let u=(point.x-c.cx)/c.fx, v=(point.y-c.cy)/c.fy
        let rx=cos(r)*u-sin(r)*v, ry=sin(r)*u+cos(r)*v
        let down=cos(pitch)*ry+sin(pitch), forward = -sin(pitch)*ry+cos(pitch)
        guard down > 0.02, let offset=c.lateralOffsetMeters else { return nil }
        let z=(-sin(yaw)*rx+cos(yaw)*forward)*c.heightMeters/down
        let x=(cos(yaw)*rx+sin(yaw)*forward)*c.heightMeters/down+offset
        guard (2...80).contains(z) else { return nil }
        let turn=yawRate*dt * .pi/180
        let omega=yawRate * .pi/180
        let travelX=abs(omega)<1e-6 ? 0 : speed/omega*(1-cos(turn))
        let travelZ=abs(omega)<1e-6 ? speed*dt : speed/omega*sin(turn)
        let movedX=cos(turn)*(x-travelX)-sin(turn)*(z-travelZ)-offset
        let movedZ=sin(turn)*(x-travelX)+cos(turn)*(z-travelZ)
        guard movedZ > 1 else { return nil }
        let cameraX=cos(yaw)*movedX-sin(yaw)*movedZ, cameraZ=sin(yaw)*movedX+cos(yaw)*movedZ
        let cameraY=cos(pitch)*c.heightMeters-sin(pitch)*cameraZ
        let depth=sin(pitch)*c.heightMeters+cos(pitch)*cameraZ
        guard depth > 1 else { return nil }
        let nx=c.cx+c.fx*(cos(r)*cameraX+sin(r)*cameraY)/depth
        let ny=c.cy+c.fy*(-sin(r)*cameraX+cos(r)*cameraY)/depth
        guard nx.isFinite, ny.isFinite, (0...1).contains(nx), (0...1).contains(ny) else { return nil }
        return LanePoint(x:nx,y:ny)
    }
    /// Bounded engineering envelope, not a statistical covariance: ±10% speed
    /// (at least 1 m/s), increasing with fix age, plus ±0.5° road-plane pitch.
    /// The intrinsic tolerance contributes one pixel; patches must still match.
    func searchUncertaintyPixels(_ point: LanePoint, dt: Double, width: Int, height: Int) -> (horizontal:Int,vertical:Int)? {
        guard width>1, height>1, let nominal=project(point,dt:dt) else { return nil }
        let speedError=max(1,speed*0.10)+sourceAge*0.5
        let pitchError=0.5 * Double.pi/180
        let alternatives=[
            Self(c:c,pitch:pitch,speed:max(0,speed-speedError),yawRate:yawRate,sourceAge:sourceAge),
            Self(c:c,pitch:pitch,speed:speed+speedError,yawRate:yawRate,sourceAge:sourceAge),
            Self(c:c,pitch:pitch-pitchError,speed:speed,yawRate:yawRate,sourceAge:sourceAge),
            Self(c:c,pitch:pitch+pitchError,speed:speed,yawRate:yawRate,sourceAge:sourceAge)]
        let projected=alternatives.compactMap { $0.project(point,dt:dt) }
        let dx=projected.map { abs($0.x-nominal.x)*Double(width-1) }.max() ?? 0
        let dy=projected.map { abs($0.y-nominal.y)*Double(height-1) }.max() ?? 0
        return (min(8,max(2,Int(ceil(dx))+1)),min(6,max(2,Int(ceil(dy))+1)))
    }
    static func from(_ c: RoadPathCalibration?, visual: VisualRoadCalibration?, hint: RoadBoundaryMotionHint) -> Self? {
        guard let c, let speed=hint.speedMetersPerSecond, let age=hint.sourceAgeSeconds,
              let accuracy=hint.courseAccuracyDegrees, let rate=hint.headingRateDegreesPerSecond,
              c.verified, [c.fx,c.fy,c.cx,c.cy,c.pitchDegrees,c.rollDegrees,c.yawDegrees,c.heightMeters,speed,age,accuracy,rate].allSatisfy(\.isFinite),
              (0.1...10).contains(c.fx), (0.1...10).contains(c.fy), (0...1).contains(c.cx), (0...1).contains(c.cy), (0.3...4).contains(c.heightMeters),
              c.lateralOffsetMeters?.isFinite == true, abs(c.lateralOffsetMeters!)<=2,
              hint.pairIntervalSeconds.map { (0.1...2.5).contains($0) } == true, (1...60).contains(speed), (0...1.1).contains(age),
              (0...15).contains(accuracy), abs(rate)<=35 else { return nil }
        let pitch=visual.flatMap { $0.isValid ? atan((c.cy-$0.horizonY)/c.fy) : nil } ?? c.pitchDegrees * .pi/180
        guard abs(pitch)<=15 * .pi/180, abs(c.rollDegrees)<=15, abs(c.yawDegrees)<=15 else { return nil }
        return Self(c:c,pitch:pitch,speed:speed,yawRate:rate,sourceAge:age)
    }
}

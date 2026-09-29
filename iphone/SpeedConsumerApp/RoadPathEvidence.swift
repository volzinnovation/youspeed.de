import Foundation

/// Local metric east/north coordinates. Poses refer to the vehicle centre on the road plane.
struct RoadPathPoint: Codable, Equatable, Sendable { let x: Double; let y: Double }
struct RoadPathPose: Codable, Equatable, Sendable {
    let scope: String; let timeSeconds: Double; let eastMeters: Double; let northMeters: Double
    let courseDegrees: Double; let speedMetersPerSecond: Double
    let horizontalAccuracyMeters: Double; let courseAccuracyDegrees: Double
}
struct RoadPathObservation: Codable, Equatable, Sendable {
    let trackId: String; let scope: String; let calibrationRevision: String
    let timeSeconds: Double; let imageX: Double; let imageY: Double
}
/// Intrinsics refer to the complete upright image. Camera axes are right/down/forward.
/// Mount rotation order is roll, pitch, yaw: positive pitch points down, positive yaw right.
/// Verification includes the actual lens/crop/rotation. A missing offset is unavailable.
struct RoadPathCalibration: Codable, Equatable, Sendable {
    let revision: String; let verified: Bool
    let fx: Double; let fy: Double; let cx: Double; let cy: Double
    let yawDegrees: Double; let pitchDegrees: Double; let rollDegrees: Double
    let heightMeters: Double; let lateralOffsetMeters: Double?
}
struct RoadPathCorridor: Codable, Equatable, Sendable {
    let id: String; let role: String; let polygon: [RoadPathPoint]
    let confidence: Double; let independentlySupported: Bool; let roadsideMarginMeters: Double
    func withRole(_ value: String) -> RoadPathCorridor {
        RoadPathCorridor(id: id, role: value, polygon: polygon, confidence: confidence,
            independentlySupported: independentlySupported, roadsideMarginMeters: roadsideMarginMeters)
    }
}
struct RoadPathResult: Codable, Equatable, Sendable {
    var classification = "unknown"
    let reason: String
    var trackId: String? = nil
    var eastMeters: Double? = nil; var northMeters: Double? = nil; var heightMeters: Double? = nil
    var rangeMeters: Double? = nil; var residualMeters: Double? = nil
    var baselineMeters: Double? = nil; var parallaxDegrees: Double? = nil
    var supportingObservations = 0
    var uncertaintyEastMeters: Double? = nil; var uncertaintyNorthMeters: Double? = nil
    var shadowOnly = true
    var oldestPoseTimeSeconds: Double? = nil; var newestPoseTimeSeconds: Double? = nil
    var maximumPoseAgeSeconds: Double? = nil
}

/// Bounded experimental evidence. No output grants display, passage, or speed authority.
enum RoadPathEvidence {
    static let maxObservations = 12, maxPoses = 32, maxCorridors = 8, maxVertices = 32
    static let maxHistorySeconds = 3.0, maxResultAgeSeconds = 0.75, maxPoseAgeSeconds = 0.35
    static let minBaselineMeters = 3.0, minParallaxDegrees = 1.0
    private static let radians = Double.pi / 180
    private struct Vec {
        let x: Double; let y: Double; let z: Double
        static func +(a: Vec, b: Vec) -> Vec { Vec(x: a.x+b.x, y: a.y+b.y, z: a.z+b.z) }
        static func -(a: Vec, b: Vec) -> Vec { Vec(x: a.x-b.x, y: a.y-b.y, z: a.z-b.z) }
        static func *(a: Vec, k: Double) -> Vec { Vec(x: a.x*k, y: a.y*k, z: a.z*k) }
        func dot(_ b: Vec) -> Double { x*b.x+y*b.y+z*b.z }
        func norm() -> Double { sqrt(dot(self)) }
        var values: [Double] { [x,y,z] }
    }
    private struct Ray { let origin: Vec; let direction: Vec; let pose: RoadPathPose; let age: Double }
    private static func calibrationValid(_ c: RoadPathCalibration) -> Bool {
        c.verified && !c.revision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        [c.fx,c.fy,c.cx,c.cy,c.yawDegrees,c.pitchDegrees,c.rollDegrees,c.heightMeters].allSatisfy(\.isFinite) &&
        (0.1...10).contains(c.fx) && (0.1...10).contains(c.fy) && (0...1).contains(c.cx) && (0...1).contains(c.cy) &&
        abs(c.yawDegrees)<=90 && abs(c.pitchDegrees)<=60 && abs(c.rollDegrees)<=90 && (0.3...4).contains(c.heightMeters) &&
        c.lateralOffsetMeters.map { $0.isFinite && abs($0)<=2 } == true
    }
    private static func poseValid(_ p: RoadPathPose) -> Bool {
        [p.timeSeconds,p.eastMeters,p.northMeters,p.courseDegrees,p.speedMetersPerSecond,
         p.horizontalAccuracyMeters,p.courseAccuracyDegrees].allSatisfy(\.isFinite) &&
        (0..<360).contains(p.courseDegrees) && (0...80).contains(p.speedMetersPerSecond) &&
        (0...5).contains(p.horizontalAccuracyMeters) && (0...5).contains(p.courseAccuracyDegrees)
    }
    private static func corridorValid(_ c: RoadPathCorridor) -> Bool {
        guard !c.id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            ["current_path","other_path","unknown"].contains(c.role), (3...maxVertices).contains(c.polygon.count),
            c.polygon.allSatisfy({ $0.x.isFinite && $0.y.isFinite }), c.confidence.isFinite,
            (0...1).contains(c.confidence), c.roadsideMarginMeters.isFinite, (0...5).contains(c.roadsideMarginMeters) else { return false }
        var area = 0.0
        for i in c.polygon.indices { let a=c.polygon[i], b=c.polygon[(i+1)%c.polygon.count]; area += a.x*b.y-b.x*a.y }
        return abs(area)>0.01
    }
    private static func ray(_ x: Double, _ y: Double, _ p: RoadPathPose, _ c: RoadPathCalibration, age: Double = 0) -> Ray {
        let roll=c.rollDegrees*radians, pitch=c.pitchDegrees*radians, yaw=c.yawDegrees*radians
        let u=(x-c.cx)/c.fx, v=(y-c.cy)/c.fy
        let rx=cos(roll)*u-sin(roll)*v, ry=sin(roll)*u+cos(roll)*v
        let py=cos(pitch)*ry+sin(pitch), pz = -sin(pitch)*ry+cos(pitch)
        let vx=cos(yaw)*rx+sin(yaw)*pz, vz = -sin(yaw)*rx+cos(yaw)*pz
        let h=p.courseDegrees*radians
        let direction=Vec(x: cos(h)*vx+sin(h)*vz,y: -sin(h)*vx+cos(h)*vz,z: -py)
        let offset=c.lateralOffsetMeters!
        return Ray(origin: Vec(x: p.eastMeters+cos(h)*offset,y: p.northMeters-sin(h)*offset,z: c.heightMeters),
            direction: direction*(1/direction.norm()),pose: p,age: age)
    }
    /// Only actual road-boundary pixels may use this projection, never a sign centre.
    static func projectGround(imageX: Double, imageY: Double, pose: RoadPathPose, calibration: RoadPathCalibration) -> RoadPathPoint? {
        guard calibrationValid(calibration), poseValid(pose), imageX.isFinite, imageY.isFinite,
            (0...1).contains(imageX), (0...1).contains(imageY) else { return nil }
        let r=ray(imageX,imageY,pose,calibration)
        guard r.direction.z < -0.02 else { return nil }
        let distance = -r.origin.z/r.direction.z
        guard (0.5...120).contains(distance) else { return nil }
        let p=r.origin+r.direction*distance
        return RoadPathPoint(x: p.x,y: p.y)
    }
    /// Latest past fix only, with bounded constant-course exposure alignment and growing error.
    /// The result must never be stored as a new GNSS observation.
    static func causalPoseAt(scope: String,timeSeconds: Double,poses: [RoadPathPose]) -> RoadPathPose? {
        guard timeSeconds.isFinite, !scope.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, poses.count<=maxPoses else { return nil }
        let causal=poses.filter { $0.timeSeconds<=timeSeconds }
        guard !causal.contains(where: { $0.scope != scope || !poseValid($0) }),
            !zip(causal,causal.dropFirst()).contains(where: { $1.timeSeconds <= $0.timeSeconds }),
            let last=causal.last else { return nil }
        let age=timeSeconds-last.timeSeconds
        guard age<=maxPoseAgeSeconds else { return nil }
        let heading=last.courseDegrees*radians, distance=last.speedMetersPerSecond*age
        return RoadPathPose(scope: last.scope,timeSeconds: timeSeconds,eastMeters: last.eastMeters+sin(heading)*distance,
            northMeters: last.northMeters+cos(heading)*distance,courseDegrees: last.courseDegrees,
            speedMetersPerSecond: last.speedMetersPerSecond,
            horizontalAccuracyMeters: last.horizontalAccuracyMeters+distance*sin(last.courseAccuracyDegrees*radians)+age*max(0.5,last.speedMetersPerSecond*0.1),
            courseAccuracyDegrees: last.courseAccuracyDegrees)
    }
    static func evaluate(scope: String,nowSeconds: Double,observations: [RoadPathObservation],poses: [RoadPathPose],
        calibration: RoadPathCalibration?,corridors: [RoadPathCorridor]) -> RoadPathResult {
        func unknown(_ reason: String) -> RoadPathResult { RoadPathResult(reason: reason,trackId: observations.first?.trackId) }
        guard observations.count<=maxObservations, poses.count<=maxPoses, corridors.count<=maxCorridors,
            !corridors.contains(where: { $0.polygon.count>maxVertices }) else { return unknown("input_limit") }
        guard !scope.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, nowSeconds.isFinite else { return unknown("invalid_scope_or_time") }
        guard let calibration, calibrationValid(calibration) else { return unknown("calibration_unavailable") }
        guard observations.count>=3 else { return unknown("insufficient_observations") }
        guard !observations.contains(where: { $0.scope != scope || $0.trackId != observations[0].trackId ||
            $0.trackId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || $0.calibrationRevision != calibration.revision }) else { return unknown("scope_or_calibration_mismatch") }
        guard !observations.contains(where: { !$0.timeSeconds.isFinite || !$0.imageX.isFinite || !$0.imageY.isFinite ||
            !(0...1).contains($0.imageX) || !(0...1).contains($0.imageY) }),
            !zip(observations,observations.dropFirst()).contains(where: { $1.timeSeconds<=$0.timeSeconds }) else { return unknown("invalid_observation_history") }
        guard observations.last!.timeSeconds<=nowSeconds else { return unknown("future_observation") }
        guard nowSeconds-observations.last!.timeSeconds<=maxResultAgeSeconds,
            nowSeconds-observations[0].timeSeconds<=maxHistorySeconds else { return unknown("stale_observations") }
        let causal=poses.filter { $0.timeSeconds<=observations.last!.timeSeconds }
        guard !causal.isEmpty else { return unknown("trajectory_unavailable") }
        guard !causal.contains(where: { $0.scope != scope || !poseValid($0) }),
            !zip(causal,causal.dropFirst()).contains(where: { $1.timeSeconds<=$0.timeSeconds }) else { return unknown("invalid_trajectory") }
        var rays=[Ray](), sourcePoseTimes=[Double](), maximumPoseAge=0.0
        for observation in observations {
            guard causal.contains(where: { $0.timeSeconds<=observation.timeSeconds }) else { return unknown("trajectory_unavailable") }
            let sourceTime=causal.last(where: { $0.timeSeconds<=observation.timeSeconds })!.timeSeconds
            sourcePoseTimes.append(sourceTime); maximumPoseAge=max(maximumPoseAge,observation.timeSeconds-sourceTime)
            guard let p=causalPoseAt(scope: scope,timeSeconds: observation.timeSeconds,poses: causal) else { return unknown("stale_trajectory") }
            guard p.speedMetersPerSecond>=1 else { return unknown("stationary_trajectory") }
            rays.append(ray(observation.imageX,observation.imageY,p,calibration))
        }
        var baseline=0.0, parallax=0.0
        for i in rays.indices { for j in 0..<i {
            baseline=max(baseline,(rays[i].origin-rays[j].origin).norm())
            parallax=max(parallax,acos(max(-1,min(1,rays[i].direction.dot(rays[j].direction))))/radians)
        } }
        let positionError=rays.map { $0.pose.horizontalAccuracyMeters+$0.age*$0.pose.speedMetersPerSecond }.max()!
        guard baseline>=max(minBaselineMeters,2*positionError) else { return unknown("insufficient_baseline") }
        guard parallax>=minParallaxDegrees else { return unknown("insufficient_parallax") }
        var a=[Double](repeating: 0,count: 9), b=[Double](repeating: 0,count: 3)
        for r in rays { let d=r.direction.values, o=r.origin.values
            for i in 0...2 { for j in 0...2 { let q=(i==j ? 1.0 : 0.0)-d[i]*d[j]; a[i*3+j]+=q; b[i]+=q*o[j] } }
        }
        guard let inverse=invert(a) else { return unknown("ill_conditioned_bearings") }
        let point=Vec(x: (0...2).reduce(0) { $0+inverse[$1]*b[$1] },
            y: (0...2).reduce(0) { $0+inverse[3+$1]*b[$1] },z: (0...2).reduce(0) { $0+inverse[6+$1]*b[$1] })
        guard point.values.allSatisfy(\.isFinite) else { return unknown("ill_conditioned_bearings") }
        var residual=0.0, largestRange=0.0
        for r in rays {
            let delta=point-r.origin, range=delta.dot(r.direction)
            guard (1...150).contains(range) else { return unknown("invalid_range") }
            largestRange=max(largestRange,range); residual=max(residual,(delta-r.direction*range).norm())
        }
        guard (-0.5...12).contains(point.z) else { return unknown("implausible_sign_height") }
        guard residual<=max(0.75,positionError) else { return unknown("inconsistent_bearings") }
        let angularError=rays.map { $0.pose.courseAccuracyDegrees }.max()!*radians
        let sigma=max(0.05,positionError+largestRange*tan(angularError)+residual)
        let eastError=max(0.15,2*sigma*sqrt(max(0,inverse[0]))), northError=max(0.15,2*sigma*sqrt(max(0,inverse[4])))
        func result(_ classification: String,_ reason: String) -> RoadPathResult {
            RoadPathResult(classification: classification,reason: reason,trackId: observations[0].trackId,
                eastMeters: point.x,northMeters: point.y,heightMeters: point.z,rangeMeters: (point-rays.last!.origin).norm(),
                residualMeters: residual,baselineMeters: baseline,parallaxDegrees: parallax,supportingObservations: rays.count,
                uncertaintyEastMeters: eastError,uncertaintyNorthMeters: northError,
                oldestPoseTimeSeconds: sourcePoseTimes.first,newestPoseTimeSeconds: sourcePoseTimes.last,maximumPoseAgeSeconds: maximumPoseAge)
        }
        guard eastError.isFinite, northError.isFinite, max(eastError,northError)<=30 else { return result("unknown","uncertain_position") }
        guard !corridors.contains(where: { !corridorValid($0) }), Set(corridors.map(\.id)).count==corridors.count else { return result("unknown","invalid_corridors") }
        let supported=inferCorridorRoles(scope: scope,nowSeconds: observations.last!.timeSeconds,poses: causal,corridors: corridors)
            .filter { $0.independentlySupported && $0.confidence>=0.7 }
        guard supported.contains(where: { $0.role=="current_path" }) else { return result("unknown","current_path_unavailable") }
        let envelope=[RoadPathPoint(x: point.x-eastError,y: point.y-northError),RoadPathPoint(x: point.x+eastError,y: point.y-northError),
            RoadPathPoint(x: point.x+eastError,y: point.y+northError),RoadPathPoint(x: point.x-eastError,y: point.y+northError)]
        let possible=supported.filter { polygonGap(envelope,$0.polygon)<=$0.roadsideMarginMeters }
        let definite=possible.filter { c in [-1.0,0,1].allSatisfy { dx in [-1.0,0,1].allSatisfy { dy in
            distance(RoadPathPoint(x: point.x+dx*eastError,y: point.y+dy*northError),c.polygon)<=c.roadsideMarginMeters } } }
        guard !definite.isEmpty else { return result("unknown",possible.isEmpty ? "outside_supported_corridors" : "uncertain_corridor_boundary") }
        let roles=Set(possible.map(\.role))
        guard roles.count==1, let role=roles.first, role != "unknown" else { return result("unknown","ambiguous_corridors") }
        return result(role,"triangulated_unique_corridor")
    }
    /// Observed local heading identifies only a uniquely supported short corridor, not a future turn.
    /// Touching neighbouring lanes remain unknown alternatives.
    static func inferCorridorRoles(scope: String,nowSeconds: Double,poses: [RoadPathPose],corridors: [RoadPathCorridor]) -> [RoadPathCorridor] {
        guard nowSeconds.isFinite, poses.count<=maxPoses, corridors.count<=maxCorridors,
            !corridors.contains(where: { !corridorValid($0) }), !corridors.contains(where: { $0.role=="current_path" }) else { return corridors }
        let causal=poses.filter { $0.timeSeconds<=nowSeconds }
        guard let last=causalPoseAt(scope: scope,timeSeconds: nowSeconds,poses: causal),
            let previous=causal.last(where: { last.timeSeconds-$0.timeSeconds>=0.2 }) else { return corridors }
        guard !causal.contains(where: { $0.scope != scope || !poseValid($0) }),
            !zip(causal,causal.dropFirst()).contains(where: { $1.timeSeconds<=$0.timeSeconds }),
            nowSeconds-last.timeSeconds<=maxPoseAgeSeconds, last.speedMetersPerSecond>=1,
            hypot(last.eastMeters-previous.eastMeters,last.northMeters-previous.northMeters)>=3 else { return corridors }
        func difference(_ a: Double,_ b: Double) -> Double { abs((a-b+540).truncatingRemainder(dividingBy: 360)-180) }
        let observed=(atan2(last.eastMeters-previous.eastMeters,last.northMeters-previous.northMeters)/radians+360).truncatingRemainder(dividingBy: 360)
        guard difference(last.courseDegrees,previous.courseDegrees)<=5, difference(last.courseDegrees,observed)<=10 else { return corridors }
        let h=last.courseDegrees*radians
        let candidates=corridors.filter { c in c.independentlySupported && c.confidence>=0.7 && [3.0,5,8].allSatisfy { d in
            let spread=last.horizontalAccuracyMeters+d*tan(last.courseAccuracyDegrees*radians)
            return [-spread,0,spread].allSatisfy { lateral in distance(RoadPathPoint(x: last.eastMeters+sin(h)*d+cos(h)*lateral,
                y: last.northMeters+cos(h)*d-sin(h)*lateral),c.polygon)<1e-6 } } }
        guard candidates.count==1 else { return corridors }
        let current=candidates[0]
        return corridors.map { c in
            if c.id==current.id { return c.withRole("current_path") }
            if c.independentlySupported && c.confidence>=0.7 && polygonGap(c.polygon,current.polygon)>1 { return c.withRole("other_path") }
            return c.withRole("unknown")
        }
    }
    private static func invert(_ m: [Double]) -> [Double]? {
        let c=[m[4]*m[8]-m[5]*m[7],m[2]*m[7]-m[1]*m[8],m[1]*m[5]-m[2]*m[4],
            m[5]*m[6]-m[3]*m[8],m[0]*m[8]-m[2]*m[6],m[2]*m[3]-m[0]*m[5],
            m[3]*m[7]-m[4]*m[6],m[1]*m[6]-m[0]*m[7],m[0]*m[4]-m[1]*m[3]]
        let determinant=m[0]*c[0]+m[1]*c[3]+m[2]*c[6]
        guard determinant.isFinite, determinant>1e-8 else { return nil }
        return c.map { $0/determinant }
    }
    private static func segmentDistance(_ p: RoadPathPoint,_ a: RoadPathPoint,_ b: RoadPathPoint) -> Double {
        let dx=b.x-a.x, dy=b.y-a.y, length=dx*dx+dy*dy
        let t=length>0 ? max(0,min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/length)) : 0
        return hypot(p.x-a.x-t*dx,p.y-a.y-t*dy)
    }
    private static func distance(_ p: RoadPathPoint,_ polygon: [RoadPathPoint]) -> Double {
        var inside=false, nearest=Double.infinity
        for i in polygon.indices { let a=polygon[i], b=polygon[(i+1)%polygon.count]
            nearest=min(nearest,segmentDistance(p,a,b))
            if (a.y>p.y) != (b.y>p.y) && p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x { inside.toggle() }
        }
        return inside ? 0 : nearest
    }
    private static func polygonGap(_ a: [RoadPathPoint],_ b: [RoadPathPoint]) -> Double {
        func cross(_ p: RoadPathPoint,_ q: RoadPathPoint,_ r: RoadPathPoint) -> Double { (q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x) }
        for i in a.indices { for j in b.indices { let p=a[i], q=a[(i+1)%a.count], r=b[j], s=b[(j+1)%b.count]
            if cross(p,q,r)*cross(p,q,s)<=0 && cross(r,s,p)*cross(r,s,q)<=0 &&
                max(min(p.x,q.x),min(r.x,s.x))<=min(max(p.x,q.x),max(r.x,s.x)) &&
                max(min(p.y,q.y),min(r.y,s.y))<=min(max(p.y,q.y),max(r.y,s.y)) { return 0 }
        } }
        return min(a.map { distance($0,b) }.min()!,b.map { distance($0,a) }.min()!)
    }
}

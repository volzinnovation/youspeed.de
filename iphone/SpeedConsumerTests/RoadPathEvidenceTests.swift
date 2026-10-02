import XCTest
@testable import SpeedConsumer

final class RoadPathEvidenceTests: XCTestCase {
    private let scope="drive:camera:mount-1"
    private var calibration: RoadPathCalibration { camera() }
    private func camera(verified: Bool=true,offset: Double? = -0.08,fx: Double=0.8) -> RoadPathCalibration {
        RoadPathCalibration(revision: "mount-1",verified: verified,fx: fx,fy: 0.8,cx: 0.5,cy: 0.5,
            yawDegrees: 0,pitchDegrees: 0,rollDegrees: 0,heightMeters: 1.6,lateralOffsetMeters: offset)
    }
    private func pose(_ t: Double,east: Double=0,north: Double?=nil,heading: Double=0,speed: Double=10,courseAccuracy: Double=0.02) -> RoadPathPose {
        RoadPathPose(scope: scope,timeSeconds: t,eastMeters: east,northMeters: north ?? t*10,courseDegrees: heading,
            speedMetersPerSecond: speed,horizontalAccuracyMeters: 0.02,courseAccuracyDegrees: courseAccuracy)
    }
    private var poses: [RoadPathPose] { [pose(0),pose(0.4),pose(0.8)] }
    private func corridor(id: String="ego",role: String="current_path",left: Double = -2,right: Double=2,margin: Double=2,supported: Bool=true) -> RoadPathCorridor {
        RoadPathCorridor(id: id,role: role,polygon: [RoadPathPoint(x: left,y: 0),RoadPathPoint(x: right,y: 0),RoadPathPoint(x: right,y: 50),RoadPathPoint(x: left,y: 50)],
            confidence: 1,independentlySupported: supported,roadsideMarginMeters: margin)
    }
    private func observations(x: Double=3,y: Double=20,z: Double=2,trajectory: [RoadPathPose]?=nil) -> [RoadPathObservation] {
        (trajectory ?? poses).map { p in
            let h=p.courseDegrees*Double.pi/180, offset=calibration.lateralOffsetMeters!
            let east=x-p.eastMeters-cos(h)*offset, north=y-p.northMeters+sin(h)*offset
            let right=cos(h)*east-sin(h)*north, forward=sin(h)*east+cos(h)*north
            return RoadPathObservation(trackId: "physical-1",scope: scope,calibrationRevision: calibration.revision,timeSeconds: p.timeSeconds,
                imageX: calibration.cx+calibration.fx*right/forward,imageY: calibration.cy+calibration.fy*(calibration.heightMeters-z)/forward)
        }
    }
    private func evaluate(_ obs: [RoadPathObservation]?=nil,trajectory: [RoadPathPose]?=nil,camera: RoadPathCalibration?=nil,
        corridors: [RoadPathCorridor]?=nil,now: Double=0.8) -> RoadPathResult {
        RoadPathEvidence.evaluate(scope: scope,nowSeconds: now,observations: obs ?? observations(),poses: trajectory ?? poses,
            calibration: camera ?? calibration,corridors: corridors ?? [corridor()])
    }
    func testCalibratedTriangulationPreservesRoadsideLeftAndOverheadSigns() {
        for (x,z) in [(3.0,2.0),(-3,2),(0,6)] {
            let r=evaluate(observations(x: x,z: z))
            XCTAssertEqual("current_path",r.classification); XCTAssertTrue(r.shadowOnly)
            XCTAssertEqual(x,r.eastMeters!,accuracy: 1e-8); XCTAssertEqual(20,r.northMeters!,accuracy: 1e-8); XCTAssertEqual(z,r.heightMeters!,accuracy: 1e-8)
            XCTAssertEqual(3,r.supportingObservations); XCTAssertEqual(0,r.maximumPoseAgeSeconds!)
        }
    }
    func testSeparatedRoadIsOtherButOverlappingCorridorsStayUnknown() {
        let other=corridor(id: "branch",role: "other_path",left: 6,right: 10,margin: 1)
        XCTAssertEqual("other_path",evaluate(observations(x: 8,y: 30),corridors: [corridor(),other]).classification)
        let overlap=corridor(id: "branch",role: "other_path",left: 0,right: 6)
        XCTAssertEqual("ambiguous_corridors",evaluate(corridors: [corridor(),overlap]).reason)
        XCTAssertEqual("current_path_unavailable",evaluate(corridors: [other]).reason)
        XCTAssertEqual("current_path_unavailable",evaluate(corridors: [corridor(supported: false)]).reason)
    }
    func testActualTurningPosesTriangulateWithoutFutureTurnInformation() {
        let turning=[pose(0),pose(0.4,east: 0.4,heading: 8),pose(0.8,east: 1.5,north: 7.8,heading: 16)]
        let r=evaluate(observations(trajectory: turning),trajectory: turning)
        XCTAssertEqual("current_path",r.classification); XCTAssertEqual(3,r.eastMeters!,accuracy: 1e-8); XCTAssertEqual(20,r.northMeters!,accuracy: 1e-8)
    }
    func testExplicitOffsetCorrectsCameraOriginAndMissingCalibrationAbstains() {
        XCTAssertEqual(3,evaluate().eastMeters!,accuracy: 1e-8)
        XCTAssertEqual(3.08,evaluate(camera: camera(offset: 0)).eastMeters!,accuracy: 1e-8)
        for c in [nil,camera(verified: false),camera(offset: nil),camera(fx: .nan)] {
            let r=RoadPathEvidence.evaluate(scope: scope,nowSeconds: 0.8,observations: observations(),poses: poses,calibration: c,corridors: [corridor()])
            XCTAssertEqual("calibration_unavailable",r.reason)
        }
        let changed=observations().map { RoadPathObservation(trackId: $0.trackId,scope: $0.scope,calibrationRevision: "different",timeSeconds: $0.timeSeconds,imageX: $0.imageX,imageY: $0.imageY) }
        XCTAssertEqual("scope_or_calibration_mismatch",evaluate(changed).reason)
    }
    func testCausalityRejectsStaleAndRepeatedTimesAndNeverUsesFutureFixes() {
        XCTAssertEqual("future_observation",evaluate(now: 0.7).reason)
        XCTAssertEqual("stale_observations",evaluate(now: 1.6).reason)
        XCTAssertEqual("trajectory_unavailable",evaluate(trajectory: [pose(2),pose(2.4),pose(2.8)]).reason)
        XCTAssertEqual("stale_trajectory",evaluate(trajectory: [poses[0]]).reason)
        XCTAssertEqual("invalid_trajectory",evaluate(trajectory: [poses[0],poses[1],poses[1],poses[2]]).reason)
        let o=observations()
        XCTAssertEqual("invalid_observation_history",evaluate([o[0],o[1],o[1]]).reason)
        XCTAssertEqual(evaluate(),evaluate(trajectory: poses+[pose(1,east: 999)]))
    }
    func testShortExposurePredictionIsCausalBoundedAndGrowsError() {
        let p=RoadPathEvidence.causalPoseAt(scope: scope,timeSeconds: 1,poses: poses+[pose(1.1,north: 999)])!
        XCTAssertEqual(10,p.northMeters,accuracy: 1e-9); XCTAssertGreaterThan(p.horizontalAccuracyMeters,poses.last!.horizontalAccuracyMeters)
        XCTAssertNil(RoadPathEvidence.causalPoseAt(scope: scope,timeSeconds: 1.16,poses: poses))
        XCTAssertNil(RoadPathEvidence.causalPoseAt(scope: scope,timeSeconds: -0.1,poses: poses))
        XCTAssertNil(RoadPathEvidence.causalPoseAt(scope: "wrong",timeSeconds: 0.8,poses: poses))
        let aligned=poses.map { RoadPathEvidence.causalPoseAt(scope: scope,timeSeconds: $0.timeSeconds+0.1,poses: poses)! }
        let r=evaluate(observations(trajectory: aligned),now: 0.9)
        XCTAssertEqual(0.1,r.maximumPoseAgeSeconds!,accuracy: 1e-9); XCTAssertEqual(0.8,r.newestPoseTimeSeconds!,accuracy: 1e-9)
        XCTAssertEqual(20,r.northMeters!,accuracy: 1e-8)
    }
    func testPoorBaselineParallelRaysAndBadFixesAbstain() {
        XCTAssertEqual("insufficient_baseline",evaluate(trajectory: [pose(0),pose(0.4,north: 0.4),pose(0.8,north: 0.8)]).reason)
        let parallel=observations().map { RoadPathObservation(trackId: $0.trackId,scope: $0.scope,calibrationRevision: $0.calibrationRevision,timeSeconds: $0.timeSeconds,imageX: 0.6,imageY: 0.5) }
        XCTAssertEqual("insufficient_parallax",evaluate(parallel).reason)
        XCTAssertEqual("stationary_trajectory",evaluate(trajectory: [pose(0,speed: 0),pose(0.4,speed: 0),pose(0.8,speed: 0)]).reason)
        XCTAssertEqual("invalid_trajectory",evaluate(trajectory: [pose(0,courseAccuracy: 25),pose(0.4,courseAccuracy: 25),pose(0.8,courseAccuracy: 25)]).reason)
        XCTAssertEqual("input_limit",evaluate(Array(repeating: observations()[0],count: 13)).reason)
    }
    func testProjectionUsesRealMountAndRejectsHorizon() {
        let p=RoadPathEvidence.projectGround(imageX: 0.5,imageY: 0.7,pose: poses[0],calibration: calibration)!
        XCTAssertEqual(-0.08,p.x,accuracy: 1e-9); XCTAssertEqual(6.4,p.y,accuracy: 1e-9)
        XCTAssertNil(RoadPathEvidence.projectGround(imageX: 0.5,imageY: 0.5,pose: poses[0],calibration: calibration))
        XCTAssertNil(RoadPathEvidence.projectGround(imageX: 0.5,imageY: 0.4,pose: poses[0],calibration: calibration))
    }
    func testAutomaticRolesRequireUniqueTrajectoryCorridorAndPhysicalSeparation() {
        let inputs=[corridor(role: "unknown",margin: 0),corridor(id: "adjacent",role: "unknown",left: 2,right: 6,margin: 0),corridor(id: "separated",role: "unknown",left: 8,right: 12,margin: 0)]
        XCTAssertEqual(["current_path","unknown","other_path"],RoadPathEvidence.inferCorridorRoles(scope: scope,nowSeconds: 0.8,poses: poses,corridors: inputs).map(\.role))
        XCTAssertEqual(inputs,RoadPathEvidence.inferCorridorRoles(scope: scope,nowSeconds: 1.2,poses: poses,corridors: inputs))
        let duplicate=[inputs[0],corridor(id: "duplicate",role: "unknown",margin: 0)]
        XCTAssertEqual(duplicate,RoadPathEvidence.inferCorridorRoles(scope: scope,nowSeconds: 0.8,poses: poses,corridors: duplicate))
    }
}

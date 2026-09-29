package de.youspeed.android.alpha

import kotlin.math.*
import org.junit.Assert.*
import org.junit.Test

class RoadPathEvidenceTests {
    private val scope="drive:camera:mount-1"
    private val calibration=RoadPathCalibration("mount-1",true,0.8,0.8,0.5,0.5,0.0,0.0,0.0,1.6,-0.08)
    private val poses=listOf(0.0,0.4,0.8).map { RoadPathPose(scope,it,0.0,it*10,0.0,10.0,0.02,0.02) }
    private fun corridor(id: String="ego",role: String="current_path",left: Double = -2.0,right: Double=2.0,margin: Double=2.0)=
        RoadPathCorridor(id,role,listOf(RoadPathPoint(left,0.0),RoadPathPoint(right,0.0),RoadPathPoint(right,50.0),RoadPathPoint(left,50.0)),1.0,true,margin)
    private fun observations(x: Double=3.0,y: Double=20.0,z: Double=2.0,trajectory: List<RoadPathPose> = poses): List<RoadPathObservation> = trajectory.map { p ->
        val h=p.courseDegrees*PI/180; val offset=calibration.lateralOffsetMeters!!
        val east=x-p.eastMeters-cos(h)*offset; val north=y-p.northMeters+sin(h)*offset
        val right=cos(h)*east-sin(h)*north; val forward=sin(h)*east+cos(h)*north
        RoadPathObservation("physical-1",scope,calibration.revision,p.timeSeconds,
            calibration.cx+calibration.fx*right/forward,calibration.cy+calibration.fy*(calibration.heightMeters-z)/forward)
    }
    private fun evaluate(obs: List<RoadPathObservation> = observations(),trajectory: List<RoadPathPose> = poses,
        camera: RoadPathCalibration? = calibration,corridors: List<RoadPathCorridor> = listOf(corridor()),now: Double=0.8)=
        RoadPathEvidence.evaluate(scope,now,obs,trajectory,camera,corridors)

    @Test fun calibratedTriangulationPreservesRoadsideLeftAndOverheadSigns() {
        for ((x,z) in listOf(3.0 to 2.0,-3.0 to 2.0,0.0 to 6.0)) {
            val r=evaluate(observations(x=x,z=z))
            assertEquals("current_path",r.classification); assertTrue(r.shadowOnly)
            assertEquals(x,r.eastMeters!!,1e-8); assertEquals(20.0,r.northMeters!!,1e-8); assertEquals(z,r.heightMeters!!,1e-8)
            assertEquals(3,r.supportingObservations); assertEquals(0.0,r.maximumPoseAgeSeconds!!,0.0)
        }
    }
    @Test fun separatedRoadIsOtherButOverlappingCorridorsStayUnknown() {
        val other=corridor("branch","other_path",6.0,10.0,1.0)
        assertEquals("other_path",evaluate(observations(x=8.0,y=30.0),corridors=listOf(corridor(),other)).classification)
        val overlap=corridor("branch","other_path",0.0,6.0,2.0)
        assertEquals("ambiguous_corridors",evaluate(corridors=listOf(corridor(),overlap)).reason)
        assertEquals("current_path_unavailable",evaluate(corridors=listOf(other)).reason)
        assertEquals("current_path_unavailable",evaluate(corridors=listOf(corridor().copy(independentlySupported=false))).reason)
    }
    @Test fun actualTurningPosesTriangulateWithoutFutureTurnInformation() {
        val turning=listOf(poses[0],poses[1].copy(eastMeters=0.4,courseDegrees=8.0),
            poses[2].copy(eastMeters=1.5,northMeters=7.8,courseDegrees=16.0))
        val r=evaluate(observations(trajectory=turning),turning)
        assertEquals("current_path",r.classification); assertEquals(3.0,r.eastMeters!!,1e-8); assertEquals(20.0,r.northMeters!!,1e-8)
    }
    @Test fun explicitOffsetCorrectsCameraOriginAndMissingCalibrationAbstains() {
        assertEquals(3.0,evaluate().eastMeters!!,1e-8)
        assertEquals(3.08,evaluate(camera=calibration.copy(lateralOffsetMeters=0.0)).eastMeters!!,1e-8)
        for (c in listOf(null,calibration.copy(verified=false),calibration.copy(lateralOffsetMeters=null),calibration.copy(fx=Double.NaN)))
            assertEquals("calibration_unavailable",evaluate(camera=c).reason)
        assertEquals("scope_or_calibration_mismatch",evaluate(observations().map { it.copy(calibrationRevision="different") }).reason)
    }
    @Test fun causalityRejectsStaleAndRepeatedTimesAndNeverUsesFutureFixes() {
        assertEquals("future_observation",evaluate(now=0.7).reason)
        assertEquals("stale_observations",evaluate(now=1.6).reason)
        assertEquals("trajectory_unavailable",evaluate(trajectory=poses.map { it.copy(timeSeconds=it.timeSeconds+2) }).reason)
        assertEquals("stale_trajectory",evaluate(trajectory=listOf(poses.first())).reason)
        assertEquals("invalid_trajectory",evaluate(trajectory=listOf(poses[0],poses[1],poses[1],poses[2])).reason)
        assertEquals("invalid_observation_history",evaluate(listOf(observations()[0],observations()[1],observations()[1])).reason)
        assertEquals(evaluate(),evaluate(trajectory=poses+poses.last().copy(timeSeconds=1.0,eastMeters=999.0)))
    }
    @Test fun shortExposurePredictionIsCausalBoundedAndGrowsError() {
        val p=RoadPathEvidence.causalPoseAt(scope,1.0,poses+poses.last().copy(timeSeconds=1.1,northMeters=999.0))!!
        assertEquals(10.0,p.northMeters,1e-9); assertTrue(p.horizontalAccuracyMeters>poses.last().horizontalAccuracyMeters)
        assertNull(RoadPathEvidence.causalPoseAt(scope,1.16,poses))
        assertNull(RoadPathEvidence.causalPoseAt(scope,-0.1,poses))
        assertNull(RoadPathEvidence.causalPoseAt("wrong",0.8,poses))
        val aligned=poses.map { RoadPathEvidence.causalPoseAt(scope,it.timeSeconds+0.1,poses)!! }
        val r=evaluate(observations(trajectory=aligned),poses,now=0.9)
        assertEquals(0.1,r.maximumPoseAgeSeconds!!,1e-9); assertEquals(0.8,r.newestPoseTimeSeconds!!,1e-9)
        assertEquals(20.0,r.northMeters!!,1e-8)
    }
    @Test fun poorBaselineParallelRaysAndBadFixesAbstain() {
        assertEquals("insufficient_baseline",evaluate(trajectory=poses.map { it.copy(northMeters=it.northMeters/10) }).reason)
        assertEquals("insufficient_parallax",evaluate(observations().map { it.copy(imageX=0.6,imageY=0.5) }).reason)
        assertEquals("stationary_trajectory",evaluate(trajectory=poses.map { it.copy(speedMetersPerSecond=0.0) }).reason)
        assertEquals("invalid_trajectory",evaluate(trajectory=poses.map { it.copy(courseAccuracyDegrees=25.0) }).reason)
        assertEquals("input_limit",evaluate(List(13) { observations()[0] }).reason)
    }
    @Test fun projectionUsesRealMountAndRejectsHorizon() {
        val p=RoadPathEvidence.projectGround(0.5,0.7,poses[0],calibration)!!
        assertEquals(-0.08,p.x,1e-9); assertEquals(6.4,p.y,1e-9)
        assertNull(RoadPathEvidence.projectGround(0.5,0.5,poses[0],calibration))
        assertNull(RoadPathEvidence.projectGround(0.5,0.4,poses[0],calibration))
    }
    @Test fun automaticRolesRequireUniqueTrajectoryCorridorAndPhysicalSeparation() {
        val inputs=listOf(corridor(role="unknown",margin=0.0),corridor("adjacent","unknown",2.0,6.0,0.0),
            corridor("separated","unknown",8.0,12.0,0.0))
        assertEquals(listOf("current_path","unknown","other_path"),RoadPathEvidence.inferCorridorRoles(scope,0.8,poses,inputs).map { it.role })
        assertEquals(inputs,RoadPathEvidence.inferCorridorRoles(scope,1.2,poses,inputs))
        val duplicate=listOf(inputs[0],inputs[0].copy(id="duplicate"))
        assertEquals(duplicate,RoadPathEvidence.inferCorridorRoles(scope,0.8,poses,duplicate))
    }
}

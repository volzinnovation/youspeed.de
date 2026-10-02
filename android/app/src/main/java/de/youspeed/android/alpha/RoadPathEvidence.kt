package de.youspeed.android.alpha

import kotlin.math.*

/** Local metric east/north coordinates. Poses refer to the vehicle centre on the road plane. */
data class RoadPathPoint(val x: Double, val y: Double)
data class RoadPathPose(val scope: String, val timeSeconds: Double, val eastMeters: Double,
    val northMeters: Double, val courseDegrees: Double, val speedMetersPerSecond: Double,
    val horizontalAccuracyMeters: Double, val courseAccuracyDegrees: Double)
data class RoadPathObservation(val trackId: String, val scope: String, val calibrationRevision: String,
    val timeSeconds: Double, val imageX: Double, val imageY: Double)

/** Intrinsics are normalized to the complete upright image. Camera axes: right/down/forward.
 * Euler mounting angles are applied roll, pitch, yaw; positive pitch points down and positive
 * yaw points right. A verified calibration includes the actual lens/crop/rotation mapping.
 * An unspecified lateral offset is unavailable, never an implicit centred installation. */
data class RoadPathCalibration(val revision: String, val verified: Boolean,
    val fx: Double, val fy: Double, val cx: Double, val cy: Double,
    val yawDegrees: Double, val pitchDegrees: Double, val rollDegrees: Double,
    val heightMeters: Double, val lateralOffsetMeters: Double?)
data class RoadPathCorridor(val id: String, val role: String, val polygon: List<RoadPathPoint>,
    val confidence: Double, val independentlySupported: Boolean, val roadsideMarginMeters: Double)
data class RoadPathResult(val classification: String = "unknown", val reason: String,
    val trackId: String? = null, val eastMeters: Double? = null, val northMeters: Double? = null,
    val heightMeters: Double? = null, val rangeMeters: Double? = null, val residualMeters: Double? = null,
    val baselineMeters: Double? = null, val parallaxDegrees: Double? = null,
    val supportingObservations: Int = 0, val uncertaintyEastMeters: Double? = null,
    val uncertaintyNorthMeters: Double? = null, val shadowOnly: Boolean = true,
    val oldestPoseTimeSeconds: Double? = null, val newestPoseTimeSeconds: Double? = null,
    val maximumPoseAgeSeconds: Double? = null)

/** Experimental evidence only. No method grants display, passage, or speed-reference authority.
 * Work is bounded by the public caps; callers retain raw observations even on abstention. */
object RoadPathEvidence {
    const val maxObservations = 12
    const val maxPoses = 32
    const val maxCorridors = 8
    const val maxVertices = 32
    const val maxHistorySeconds = 3.0
    const val maxResultAgeSeconds = 0.75
    const val maxPoseAgeSeconds = 0.35
    const val minBaselineMeters = 3.0
    const val minParallaxDegrees = 1.0
    private const val radians = PI / 180.0
    private data class Vec(val x: Double, val y: Double, val z: Double) {
        operator fun plus(b: Vec) = Vec(x+b.x,y+b.y,z+b.z)
        operator fun minus(b: Vec) = Vec(x-b.x,y-b.y,z-b.z)
        operator fun times(k: Double) = Vec(x*k,y*k,z*k)
        fun dot(b: Vec) = x*b.x+y*b.y+z*b.z
        fun norm() = sqrt(dot(this))
        fun values() = doubleArrayOf(x,y,z)
    }
    private data class Ray(val origin: Vec, val direction: Vec, val pose: RoadPathPose, val age: Double)

    private fun calibrationValid(c: RoadPathCalibration): Boolean = c.verified && c.revision.isNotBlank() &&
        listOf(c.fx,c.fy,c.cx,c.cy,c.yawDegrees,c.pitchDegrees,c.rollDegrees,c.heightMeters).all { it.isFinite() } &&
        c.fx in 0.1..10.0 && c.fy in 0.1..10.0 && c.cx in 0.0..1.0 && c.cy in 0.0..1.0 &&
        abs(c.yawDegrees) <= 90 && abs(c.pitchDegrees) <= 60 && abs(c.rollDegrees) <= 90 &&
        c.heightMeters in 0.3..4.0 && c.lateralOffsetMeters?.let { it.isFinite() && abs(it) <= 2 } == true
    private fun poseValid(p: RoadPathPose) = listOf(p.timeSeconds,p.eastMeters,p.northMeters,p.courseDegrees,
        p.speedMetersPerSecond,p.horizontalAccuracyMeters,p.courseAccuracyDegrees).all { it.isFinite() } &&
        p.courseDegrees in 0.0..<360.0 && p.speedMetersPerSecond in 0.0..80.0 &&
        p.horizontalAccuracyMeters in 0.0..5.0 && p.courseAccuracyDegrees in 0.0..5.0
    private fun corridorValid(c: RoadPathCorridor): Boolean = c.id.isNotBlank() &&
        c.role in listOf("current_path","other_path","unknown") && c.polygon.size in 3..maxVertices &&
        c.polygon.all { it.x.isFinite() && it.y.isFinite() } && c.confidence.isFinite() &&
        c.confidence in 0.0..1.0 && c.roadsideMarginMeters.isFinite() && c.roadsideMarginMeters in 0.0..5.0 &&
        abs(c.polygon.indices.sumOf { i -> val a=c.polygon[i]; val b=c.polygon[(i+1)%c.polygon.size]; a.x*b.y-b.x*a.y }) > 0.01

    private fun ray(x: Double,y: Double,p: RoadPathPose,c: RoadPathCalibration,age: Double = 0.0): Ray {
        val roll=c.rollDegrees*radians; val pitch=c.pitchDegrees*radians; val yaw=c.yawDegrees*radians
        val u=(x-c.cx)/c.fx; val v=(y-c.cy)/c.fy
        val rx=cos(roll)*u-sin(roll)*v; val ry=sin(roll)*u+cos(roll)*v
        val py=cos(pitch)*ry+sin(pitch); val pz=-sin(pitch)*ry+cos(pitch)
        val vx=cos(yaw)*rx+sin(yaw)*pz; val vz=-sin(yaw)*rx+cos(yaw)*pz
        val h=p.courseDegrees*radians
        val direction=Vec(cos(h)*vx+sin(h)*vz,-sin(h)*vx+cos(h)*vz,-py)
        val offset=requireNotNull(c.lateralOffsetMeters)
        return Ray(Vec(p.eastMeters+cos(h)*offset,p.northMeters-sin(h)*offset,c.heightMeters),
            direction*(1.0/direction.norm()),p,age)
    }

    /** Only actual road-boundary pixels may use ground projection. Never pass a sign centre. */
    fun projectGround(imageX: Double,imageY: Double,pose: RoadPathPose,calibration: RoadPathCalibration): RoadPathPoint? {
        if (!calibrationValid(calibration) || !poseValid(pose) || !imageX.isFinite() || !imageY.isFinite() ||
            imageX !in 0.0..1.0 || imageY !in 0.0..1.0) return null
        val r=ray(imageX,imageY,pose,calibration)
        if (r.direction.z >= -0.02) return null
        val distance=-r.origin.z/r.direction.z
        if (distance !in 0.5..120.0) return null
        val p=r.origin+r.direction*distance
        return RoadPathPoint(p.x,p.y)
    }

    /** Exposure alignment from the latest *past* fix only. This short constant-course prediction
     * grows position uncertainty; callers must not store it as a new GNSS observation. */
    fun causalPoseAt(scope: String,timeSeconds: Double,poses: List<RoadPathPose>): RoadPathPose? {
        if (!timeSeconds.isFinite() || scope.isBlank() || poses.size>maxPoses) return null
        val causal=poses.filter { it.timeSeconds<=timeSeconds }
        if (causal.any { it.scope!=scope || !poseValid(it) } ||
            causal.zipWithNext().any { (a,b) -> b.timeSeconds<=a.timeSeconds }) return null
        val last=causal.lastOrNull() ?: return null
        val age=timeSeconds-last.timeSeconds
        if (age>maxPoseAgeSeconds) return null
        val heading=last.courseDegrees*radians
        val distance=last.speedMetersPerSecond*age
        return last.copy(timeSeconds=timeSeconds,eastMeters=last.eastMeters+sin(heading)*distance,
            northMeters=last.northMeters+cos(heading)*distance,
            horizontalAccuracyMeters=last.horizontalAccuracyMeters+distance*sin(last.courseAccuracyDegrees*radians)+
                age*max(0.5,last.speedMetersPerSecond*0.1))
    }

    fun evaluate(scope: String,nowSeconds: Double,observations: List<RoadPathObservation>,poses: List<RoadPathPose>,
        calibration: RoadPathCalibration?,corridors: List<RoadPathCorridor>): RoadPathResult {
        fun unknown(reason: String) = RoadPathResult(reason=reason,trackId=observations.firstOrNull()?.trackId)
        if (observations.size>maxObservations || poses.size>maxPoses || corridors.size>maxCorridors ||
            corridors.any { it.polygon.size>maxVertices }) return unknown("input_limit")
        if (scope.isBlank() || !nowSeconds.isFinite()) return unknown("invalid_scope_or_time")
        if (calibration==null || !calibrationValid(calibration)) return unknown("calibration_unavailable")
        if (observations.size<3) return unknown("insufficient_observations")
        if (observations.any { it.scope!=scope || it.trackId!=observations.first().trackId || it.trackId.isBlank() ||
                it.calibrationRevision!=calibration.revision }) return unknown("scope_or_calibration_mismatch")
        if (observations.any { !it.timeSeconds.isFinite() || !it.imageX.isFinite() || !it.imageY.isFinite() ||
                it.imageX !in 0.0..1.0 || it.imageY !in 0.0..1.0 } ||
            observations.zipWithNext().any { (a,b) -> b.timeSeconds<=a.timeSeconds }) return unknown("invalid_observation_history")
        if (observations.last().timeSeconds>nowSeconds) return unknown("future_observation")
        if (nowSeconds-observations.last().timeSeconds>maxResultAgeSeconds ||
            nowSeconds-observations.first().timeSeconds>maxHistorySeconds) return unknown("stale_observations")
        // Later fixes are never used, even when available by the time recognition completes.
        val causal=poses.filter { it.timeSeconds<=observations.last().timeSeconds }
        if (causal.isEmpty()) return unknown("trajectory_unavailable")
        if (causal.any { it.scope!=scope || !poseValid(it) } ||
            causal.zipWithNext().any { (a,b) -> b.timeSeconds<=a.timeSeconds }) return unknown("invalid_trajectory")
        val rays=ArrayList<Ray>()
        val sourcePoseTimes=ArrayList<Double>()
        var maximumPoseAge=0.0
        for (observation in observations) {
            if (causal.none { it.timeSeconds<=observation.timeSeconds }) return unknown("trajectory_unavailable")
            val sourceTime=causal.last { it.timeSeconds<=observation.timeSeconds }.timeSeconds
            sourcePoseTimes.add(sourceTime)
            maximumPoseAge=max(maximumPoseAge,observation.timeSeconds-sourceTime)
            val p=causalPoseAt(scope,observation.timeSeconds,causal) ?: return unknown("stale_trajectory")
            if (p.speedMetersPerSecond<1.0) return unknown("stationary_trajectory")
            rays.add(ray(observation.imageX,observation.imageY,p,calibration))
        }
        var baseline=0.0; var parallax=0.0
        for (i in rays.indices) for (j in 0 until i) {
            baseline=max(baseline,(rays[i].origin-rays[j].origin).norm())
            parallax=max(parallax,acos(rays[i].direction.dot(rays[j].direction).coerceIn(-1.0,1.0))/radians)
        }
        val positionError=rays.maxOf { it.pose.horizontalAccuracyMeters+it.age*it.pose.speedMetersPerSecond }
        if (baseline<max(minBaselineMeters,2*positionError)) return unknown("insufficient_baseline")
        if (parallax<minParallaxDegrees) return unknown("insufficient_parallax")
        val a=DoubleArray(9); val b=DoubleArray(3)
        for (r in rays) {
            val d=r.direction.values(); val o=r.origin.values()
            for (i in 0..2) for (j in 0..2) { val q=(if (i==j) 1.0 else 0.0)-d[i]*d[j]; a[i*3+j]+=q; b[i]+=q*o[j] }
        }
        val inverse=invert(a) ?: return unknown("ill_conditioned_bearings")
        val point=Vec((0..2).sumOf { inverse[it]*b[it] },(0..2).sumOf { inverse[3+it]*b[it] },(0..2).sumOf { inverse[6+it]*b[it] })
        if (!point.values().all { it.isFinite() }) return unknown("ill_conditioned_bearings")
        var residual=0.0; var largestRange=0.0
        for (r in rays) {
            val delta=point-r.origin; val range=delta.dot(r.direction)
            if (range !in 1.0..150.0) return unknown("invalid_range")
            largestRange=max(largestRange,range)
            residual=max(residual,(delta-r.direction*range).norm())
        }
        if (point.z !in -0.5..12.0) return unknown("implausible_sign_height")
        if (residual>max(0.75,positionError)) return unknown("inconsistent_bearings")
        val angularError=rays.maxOf { it.pose.courseAccuracyDegrees }*radians
        val sigma=max(0.05,positionError+largestRange*tan(angularError)+residual)
        val eastError=max(0.15,2*sigma*sqrt(max(0.0,inverse[0])))
        val northError=max(0.15,2*sigma*sqrt(max(0.0,inverse[4])))
        fun result(classification: String,reason: String)=RoadPathResult(classification,reason,observations.first().trackId,
            point.x,point.y,point.z,(point-rays.last().origin).norm(),residual,baseline,parallax,rays.size,eastError,northError,
            oldestPoseTimeSeconds=sourcePoseTimes.first(),newestPoseTimeSeconds=sourcePoseTimes.last(),maximumPoseAgeSeconds=maximumPoseAge)
        if (!eastError.isFinite() || !northError.isFinite() || max(eastError,northError)>30) return result("unknown","uncertain_position")
        if (corridors.any { !corridorValid(it) } || corridors.map { it.id }.distinct().size!=corridors.size) return result("unknown","invalid_corridors")
        val supported=inferCorridorRoles(scope,observations.last().timeSeconds,causal,corridors)
            .filter { it.independentlySupported && it.confidence>=0.7 }
        if (supported.none { it.role=="current_path" }) return result("unknown","current_path_unavailable")
        val envelope=listOf(RoadPathPoint(point.x-eastError,point.y-northError),RoadPathPoint(point.x+eastError,point.y-northError),
            RoadPathPoint(point.x+eastError,point.y+northError),RoadPathPoint(point.x-eastError,point.y+northError))
        val possible=supported.filter { polygonGap(envelope,it.polygon)<=it.roadsideMarginMeters }
        val definite=possible.filter { c -> listOf(-1.0,0.0,1.0).all { dx -> listOf(-1.0,0.0,1.0).all { dy ->
            distance(RoadPathPoint(point.x+dx*eastError,point.y+dy*northError),c.polygon)<=c.roadsideMarginMeters } } }
        if (definite.isEmpty()) return result("unknown",if (possible.isEmpty()) "outside_supported_corridors" else "uncertain_corridor_boundary")
        val roles=possible.map { it.role }.distinct()
        if (roles.size!=1 || roles.first()=="unknown") return result("unknown","ambiguous_corridors")
        return result(roles.first(),"triangulated_unique_corridor")
    }

    /** Short current-heading continuation identifies only a uniquely supported local corridor.
     * It does not predict an intended turn. Touching adjacent lanes remain unknown alternatives. */
    fun inferCorridorRoles(scope: String,nowSeconds: Double,poses: List<RoadPathPose>,corridors: List<RoadPathCorridor>): List<RoadPathCorridor> {
        if (!nowSeconds.isFinite() || poses.size>maxPoses || corridors.size>maxCorridors ||
            corridors.any { !corridorValid(it) } || corridors.any { it.role=="current_path" }) return corridors
        val causal=poses.filter { it.timeSeconds<=nowSeconds }
        val last=causalPoseAt(scope,nowSeconds,causal) ?: return corridors
        val previous=causal.lastOrNull { last.timeSeconds-it.timeSeconds>=0.2 } ?: return corridors
        if (causal.any { it.scope!=scope || !poseValid(it) } || causal.zipWithNext().any { (a,b) -> b.timeSeconds<=a.timeSeconds } ||
            nowSeconds-last.timeSeconds>maxPoseAgeSeconds || last.speedMetersPerSecond<1 ||
            hypot(last.eastMeters-previous.eastMeters,last.northMeters-previous.northMeters)<3) return corridors
        fun difference(a: Double,b: Double)=abs(((a-b+540)%360)-180)
        val observed=(atan2(last.eastMeters-previous.eastMeters,last.northMeters-previous.northMeters)/radians+360)%360
        if (difference(last.courseDegrees,previous.courseDegrees)>5 || difference(last.courseDegrees,observed)>10) return corridors
        val h=last.courseDegrees*radians
        val candidates=corridors.filter { c -> c.independentlySupported && c.confidence>=0.7 && listOf(3.0,5.0,8.0).all { d ->
            val spread=last.horizontalAccuracyMeters+d*tan(last.courseAccuracyDegrees*radians)
            listOf(-spread,0.0,spread).all { lateral -> distance(RoadPathPoint(last.eastMeters+sin(h)*d+cos(h)*lateral,
                last.northMeters+cos(h)*d-sin(h)*lateral),c.polygon)<1e-6 } } }
        if (candidates.size!=1) return corridors
        val current=candidates.first()
        return corridors.map { c -> when {
            c.id==current.id -> c.copy(role="current_path")
            c.independentlySupported && c.confidence>=0.7 && polygonGap(c.polygon,current.polygon)>1.0 -> c.copy(role="other_path")
            else -> c.copy(role="unknown")
        } }
    }

    private fun invert(m: DoubleArray): DoubleArray? {
        val c=doubleArrayOf(m[4]*m[8]-m[5]*m[7],m[2]*m[7]-m[1]*m[8],m[1]*m[5]-m[2]*m[4],
            m[5]*m[6]-m[3]*m[8],m[0]*m[8]-m[2]*m[6],m[2]*m[3]-m[0]*m[5],
            m[3]*m[7]-m[4]*m[6],m[1]*m[6]-m[0]*m[7],m[0]*m[4]-m[1]*m[3])
        val determinant=m[0]*c[0]+m[1]*c[3]+m[2]*c[6]
        if (!determinant.isFinite() || determinant<=1e-8) return null
        return c.map { it/determinant }.toDoubleArray()
    }
    private fun segmentDistance(p: RoadPathPoint,a: RoadPathPoint,b: RoadPathPoint): Double {
        val dx=b.x-a.x; val dy=b.y-a.y; val length=dx*dx+dy*dy
        val t=if (length>0) (((p.x-a.x)*dx+(p.y-a.y)*dy)/length).coerceIn(0.0,1.0) else 0.0
        return hypot(p.x-a.x-t*dx,p.y-a.y-t*dy)
    }
    private fun distance(p: RoadPathPoint,polygon: List<RoadPathPoint>): Double {
        var inside=false; var nearest=Double.POSITIVE_INFINITY
        for (i in polygon.indices) {
            val a=polygon[i]; val b=polygon[(i+1)%polygon.size]
            nearest=min(nearest,segmentDistance(p,a,b))
            if ((a.y>p.y)!=(b.y>p.y) && p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x) inside=!inside
        }
        return if (inside) 0.0 else nearest
    }
    private fun polygonGap(a: List<RoadPathPoint>,b: List<RoadPathPoint>): Double {
        // Vertex distances alone miss crossing edges. Detect segment intersections first.
        fun cross(p: RoadPathPoint,q: RoadPathPoint,r: RoadPathPoint)=(q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x)
        for (i in a.indices) for (j in b.indices) {
            val p=a[i]; val q=a[(i+1)%a.size]; val r=b[j]; val s=b[(j+1)%b.size]
            if (cross(p,q,r)*cross(p,q,s)<=0 && cross(r,s,p)*cross(r,s,q)<=0 &&
                max(min(p.x,q.x),min(r.x,s.x))<=min(max(p.x,q.x),max(r.x,s.x)) &&
                max(min(p.y,q.y),min(r.y,s.y))<=min(max(p.y,q.y),max(r.y,s.y))) return 0.0
        }
        return min(a.minOf { distance(it,b) },b.minOf { distance(it,a) })
    }
}

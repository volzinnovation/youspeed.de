package de.youspeed.android.alpha

import kotlin.math.abs

/** Causal GNSS search hint only. It neither projects pixels nor supplies observed lane points. */
data class RoadBoundaryMotionSample(val timeSeconds: Double, val speedMetersPerSecond: Double,
    val courseDegrees: Double, val horizontalAccuracyMeters: Double, val courseAccuracyDegrees: Double)
data class RoadBoundaryMotionHint(val used: Boolean, val reason: String, val sourceAgeSeconds: Double? = null,
    val speedMetersPerSecond: Double? = null, val courseAccuracyDegrees: Double? = null,
    val pairIntervalSeconds: Double? = null, val headingDeltaDegrees: Double? = null,
    val headingRateDegreesPerSecond: Double? = null,
    val horizontalSearchRadiusFloor: Int = 0) {
    companion object {
        fun from(samples: List<RoadBoundaryMotionSample>, capturedAtSeconds: Double, clockKnown: Boolean): RoadBoundaryMotionHint {
            if (!clockKnown || !capturedAtSeconds.isFinite()) return RoadBoundaryMotionHint(false,"capture_clock_unknown")
            val causal = samples.takeLast(32).filter { it.timeSeconds.isFinite() && it.timeSeconds <= capturedAtSeconds }
            val latest = causal.lastOrNull() ?: return RoadBoundaryMotionHint(false,"no_causal_fix")
            val age = capturedAtSeconds-latest.timeSeconds
            fun reject(reason: String) = RoadBoundaryMotionHint(false,reason,age,latest.speedMetersPerSecond,latest.courseAccuracyDegrees)
            // Session ingestion already owns GPS validity. Do not introduce a second health policy.
            fun valid(s: RoadBoundaryMotionSample) = listOf(s.speedMetersPerSecond,s.courseDegrees,s.horizontalAccuracyMeters,s.courseAccuracyDegrees).all { it.isFinite() } &&
                s.speedMetersPerSecond >= 0 && s.courseDegrees in 0.0..<360.0
            if (!valid(latest)) return reject("invalid_fix")
            val before = causal.dropLast(1).lastOrNull { it.timeSeconds < latest.timeSeconds } ?: return reject("insufficient_history")
            if (!valid(before)) return reject("invalid_fix")
            val interval = latest.timeSeconds-before.timeSeconds
            val delta = ((latest.courseDegrees-before.courseDegrees+540)%360)-180
            val rate = delta/interval
            if (!rate.isFinite()) return reject("invalid_fix_interval")
            val turning = latest.speedMetersPerSecond>0 && abs(rate)>6
            return RoadBoundaryMotionHint(turning,if(turning) "turn_search_hint" else "no_moving_turn",age,
                latest.speedMetersPerSecond,latest.courseAccuracyDegrees,interval,delta,rate,if(turning)12 else 0)
        }
    }
}

/** Approximate road-plane motion is a search prior only; patches must independently confirm it. */
class RoadBoundaryMotionProjection private constructor(private val c: RoadPathCalibration,
    private val pitch: Double, private val speed: Double, private val yawRate: Double, private val sourceAge: Double) {
    fun project(point: LanePoint, dt: Double): LanePoint? {
        if (!dt.isFinite() || dt <= 0 || dt > .75 || speed*dt > 8) return null
        val r=Math.toRadians(c.rollDegrees); val yaw=Math.toRadians(c.yawDegrees)
        val u=(point.x-c.cx)/c.fx; val v=(point.y-c.cy)/c.fy
        val rx=kotlin.math.cos(r)*u-kotlin.math.sin(r)*v
        val ry=kotlin.math.sin(r)*u+kotlin.math.cos(r)*v
        val down=kotlin.math.cos(pitch)*ry+kotlin.math.sin(pitch)
        val forward=-kotlin.math.sin(pitch)*ry+kotlin.math.cos(pitch)
        if (down <= .02) return null
        val z=(-kotlin.math.sin(yaw)*rx+kotlin.math.cos(yaw)*forward)*c.heightMeters/down
        val offset=c.lateralOffsetMeters ?: return null
        val x=(kotlin.math.cos(yaw)*rx+kotlin.math.sin(yaw)*forward)*c.heightMeters/down+offset
        if (z !in 2.0..80.0) return null
        val turn=Math.toRadians(yawRate*dt)
        val omega=Math.toRadians(yawRate)
        val travelX=if(abs(omega)<1e-6) 0.0 else speed/omega*(1-kotlin.math.cos(turn))
        val travelZ=if(abs(omega)<1e-6) speed*dt else speed/omega*kotlin.math.sin(turn)
        val movedX=kotlin.math.cos(turn)*(x-travelX)-kotlin.math.sin(turn)*(z-travelZ)-offset
        val movedZ=kotlin.math.sin(turn)*(x-travelX)+kotlin.math.cos(turn)*(z-travelZ)
        if (movedZ <= 1) return null
        val cameraX=kotlin.math.cos(yaw)*movedX-kotlin.math.sin(yaw)*movedZ
        val cameraZ=kotlin.math.sin(yaw)*movedX+kotlin.math.cos(yaw)*movedZ
        val cameraY=kotlin.math.cos(pitch)*c.heightMeters-kotlin.math.sin(pitch)*cameraZ
        val depth=kotlin.math.sin(pitch)*c.heightMeters+kotlin.math.cos(pitch)*cameraZ
        if (depth <= 1) return null
        val nx=c.cx+c.fx*(kotlin.math.cos(r)*cameraX+kotlin.math.sin(r)*cameraY)/depth
        val ny=c.cy+c.fy*(-kotlin.math.sin(r)*cameraX+kotlin.math.cos(r)*cameraY)/depth
        return LanePoint(nx,ny).takeIf { nx.isFinite() && ny.isFinite() && nx in 0.0..1.0 && ny in 0.0..1.0 }
    }
    /** Bounded engineering envelope (not covariance): speed/fix-age and ±0.5° pitch uncertainty. */
    fun searchUncertaintyPixels(point: LanePoint, dt: Double, width: Int, height: Int): Pair<Int,Int>? {
        if(width<=1 || height<=1) return null
        val nominal=project(point,dt) ?: return null
        val speedError=maxOf(1.0,speed*.10)+sourceAge*.5
        val pitchError=Math.toRadians(.5)
        val alternatives=listOf(
            RoadBoundaryMotionProjection(c,pitch,maxOf(0.0,speed-speedError),yawRate,sourceAge),
            RoadBoundaryMotionProjection(c,pitch,speed+speedError,yawRate,sourceAge),
            RoadBoundaryMotionProjection(c,pitch-pitchError,speed,yawRate,sourceAge),
            RoadBoundaryMotionProjection(c,pitch+pitchError,speed,yawRate,sourceAge))
        val projected=alternatives.mapNotNull { it.project(point,dt) }
        val dx=projected.maxOfOrNull { abs(it.x-nominal.x)*(width-1) } ?: 0.0
        val dy=projected.maxOfOrNull { abs(it.y-nominal.y)*(height-1) } ?: 0.0
        return (kotlin.math.ceil(dx).toInt()+1).coerceIn(2,8) to (kotlin.math.ceil(dy).toInt()+1).coerceIn(2,6)
    }
    companion object {
        fun from(c: RoadPathCalibration?, visual: VisualRoadCalibration?, hint: RoadBoundaryMotionHint): RoadBoundaryMotionProjection? {
            c ?: return null
            val speed=hint.speedMetersPerSecond ?: return null
            val age=hint.sourceAgeSeconds ?: return null
            val accuracy=hint.courseAccuracyDegrees ?: return null
            val rate=hint.headingRateDegreesPerSecond ?: return null
            if (!c.verified || !listOf(c.fx,c.fy,c.cx,c.cy,c.pitchDegrees,c.rollDegrees,c.yawDegrees,c.heightMeters,speed,age,accuracy,rate).all(Double::isFinite) ||
                c.fx !in .1..10.0 || c.fy !in .1..10.0 || c.cx !in 0.0..1.0 || c.cy !in 0.0..1.0 || c.heightMeters !in .3..4.0 ||
                c.lateralOffsetMeters?.isFinite()!=true || abs(c.lateralOffsetMeters)>2 || hint.pairIntervalSeconds?.let { it in .1..2.5 } != true || speed !in 1.0..60.0 || age !in 0.0..1.1 || accuracy !in 0.0..15.0 || kotlin.math.abs(rate)>35) return null
            // A saved visual horizon adjusts the approximate road plane, never camera intrinsics.
            val pitch=visual?.takeIf { it.isValid }?.let { kotlin.math.atan((c.cy-it.horizonY)/c.fy) } ?: Math.toRadians(c.pitchDegrees)
            if (kotlin.math.abs(pitch)>Math.toRadians(15.0) || kotlin.math.abs(c.rollDegrees)>15 || kotlin.math.abs(c.yawDegrees)>15) return null
            return RoadBoundaryMotionProjection(c,pitch,speed,rate,age)
        }
    }
}

package de.youspeed.android.alpha

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/** Display geometry only; the original evidence remains authoritative. */
data class LaneBezierSegment(val start: LanePoint, val control1: LanePoint, val control2: LanePoint, val end: LanePoint) {
    fun point(t: Double): LanePoint {
        val u = 1-t
        return LanePoint(u*u*u*start.x+3*u*u*t*control1.x+3*u*t*t*control2.x+t*t*t*end.x,
            start.y+(end.y-start.y)*t)
    }
}

/** Same bounded least-squares fitting and exact polyline deviation check as iPhone. */
object LaneBoundaryBezier {
    const val MAXIMUM_DEVIATION = 2.0/383.0
    const val MAXIMUM_GAP = 0.16

    fun fit(points: List<LanePoint>): List<LaneBezierSegment> {
        if (points.size !in 2..64) return emptyList()
        val output = ArrayList<LaneBezierSegment>()
        val run = ArrayList<LanePoint>()
        fun finish() {
            if (run.size >= 2) approximate(run, 0, run.lastIndex, output)
            run.clear()
        }
        for (p in points) {
            if (!p.x.isFinite() || !p.y.isFinite() || p.x !in 0.0..1.0 || p.y !in 0.0..1.0) {
                finish(); continue
            }
            val previous = run.lastOrNull()
            if (previous != null && (p.y <= previous.y || p.y-previous.y > MAXIMUM_GAP)) finish()
            run += p
        }
        finish()
        return output
    }

    private fun approximate(points: List<LanePoint>, first: Int, last: Int, output: MutableList<LaneBezierSegment>) {
        val curve = fitted(points, first, last)
        val error = deviation(curve, points, first, last)
        if (last-first == 1 || error.first <= MAXIMUM_DEVIATION+1e-12) output += curve
        else {
            val split = error.second.coerceIn(first+1,last-1)
            approximate(points,first,split,output)
            approximate(points,split,last,output)
        }
    }

    private fun fitted(points: List<LanePoint>, first: Int, last: Int): LaneBezierSegment {
        val a = points[first]; val b = points[last]; val span = b.y-a.y
        var c1 = a.x+(b.x-a.x)/3; var c2 = a.x+2*(b.x-a.x)/3
        var aa = 0.0; var ab = 0.0; var bb = 0.0; var ar = 0.0; var br = 0.0; var qq = 0.0; var qr = 0.0
        var low = min(a.x,b.x); var high = max(a.x,b.x)
        if (last-first > 1) {
            for (i in first+1 until last) {
                val p = points[i]; val t = (p.y-a.y)/span; val u = 1-t
                val v1 = 3*u*u*t; val v2 = 3*u*t*t; val residual = p.x-u*u*u*a.x-t*t*t*b.x
                aa += v1*v1; ab += v1*v2; bb += v2*v2; ar += v1*residual; br += v2*residual
                val q = 2*u*t
                qq += q*q; qr += q*(p.x-u*u*a.x-t*t*b.x)
                low = min(low,p.x); high = max(high,p.x)
            }
            val determinant = aa*bb-ab*ab
            if (determinant > 1e-12) {
                c1 = (ar*bb-br*ab)/determinant; c2 = (br*aa-ar*ab)/determinant
            } else if (qq > 1e-12) {
                val q = qr/qq
                c1 = a.x+2*(q-a.x)/3; c2 = b.x+2*(q-b.x)/3
            }
        }
        return LaneBezierSegment(a,LanePoint(c1.coerceIn(low,high),a.y+span/3),
            LanePoint(c2.coerceIn(low,high),a.y+2*span/3),b)
    }

    private fun deviation(curve: LaneBezierSegment, points: List<LanePoint>, first: Int, last: Int): Pair<Double,Int> {
        val span = curve.end.y-curve.start.y
        val a = -curve.start.x+3*curve.control1.x-3*curve.control2.x+curve.end.x
        val b = 3*curve.start.x-6*curve.control1.x+3*curve.control2.x
        val c = -3*curve.start.x+3*curve.control1.x
        var maximum = 0.0; var split = (first+last)/2
        for (i in first until last) {
            val p = points[i]; val q = points[i+1]
            val t0 = (p.y-curve.start.y)/span; val t1 = (q.y-curve.start.y)/span
            val slope = (q.x-p.x)/(t1-t0)
            val candidates = arrayListOf(t0,t1)
            if (abs(3*a) < 1e-12) {
                if (abs(2*b) > 1e-12) candidates += -(c-slope)/(2*b)
            } else {
                val discriminant = 4*b*b-12*a*(c-slope)
                if (discriminant >= 0) {
                    val root = sqrt(discriminant)
                    candidates += (-2*b-root)/(6*a); candidates += (-2*b+root)/(6*a)
                }
            }
            for (t in candidates) if (t >= t0 && t <= t1) {
                val error = abs(curve.point(t).x-(p.x+slope*(t-t0)))
                if (error > maximum) { maximum = error; split = i+1 }
            }
        }
        return maximum to split
    }
}

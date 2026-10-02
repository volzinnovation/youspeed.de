package de.youspeed.android.alpha

import kotlin.math.abs
import kotlin.math.sin
import org.junit.Assert.*
import org.junit.Test

class LaneBoundaryBezierTests {
    private fun checkBound(points: List<LanePoint>, curves: List<LaneBezierSegment>) {
        for (curve in curves) {
            assertTrue(curve.start in points); assertTrue(curve.end in points)
            val covered = points.filter { it.y >= curve.start.y && it.y <= curve.end.y }
            val lo = covered.minOf { it.x }; val hi = covered.maxOf { it.x }
            for (p in listOf(curve.control1,curve.control2)) {
                assertTrue(p.x in lo..hi); assertTrue(p.y in curve.start.y..curve.end.y)
            }
            for (step in 0..200) {
                val p = curve.point(step/200.0)
                val index = points.indexOfFirst { it.y >= p.y }.let { if (it<0) points.lastIndex else it }.coerceAtLeast(1)
                val a = points[index-1]; val b = points[index]
                val raw = a.x+(b.x-a.x)*(p.y-a.y)/(b.y-a.y)
                assertTrue("deviation=${abs(p.x-raw)}",abs(p.x-raw)<=LaneBoundaryBezier.MAXIMUM_DEVIATION+1e-10)
            }
        }
    }

    @Test fun noisyStraightBoundarySimplifiesToOneCurveWithoutMovingEndpoints() {
        val points = (0..11).map { i ->
            val t = i/11.0
            LanePoint(0.3+0.18*t+(if (i==0 || i==11) 0.0 else if (i%2==0) 0.002 else -0.002),0.45+0.5*t)
        }
        val before = points.toList(); val curves = LaneBoundaryBezier.fit(points)
        assertEquals(1,curves.size); assertEquals(points.first(),curves.first().start); assertEquals(points.last(),curves.last().end)
        assertEquals(before,points)
        assertTrue(abs(curves[0].point(5.0/11).x-points[5].x)>0.001)
        checkBound(points,curves)
    }

    @Test fun bendAndInflectionKeepCurvatureWithinTheObservedExtent() {
        val points = (0..12).map { i ->
            val t = i/12.0
            LanePoint(0.22+0.34*t-0.25*t*t+0.2*t*t*t,0.4+0.55*t)
        }
        val curves = LaneBoundaryBezier.fit(points)
        assertEquals(1,curves.size); checkBound(points,curves)
        assertEquals(0.3525,curves[0].point(0.5).x,1e-10)
    }

    @Test fun sharpGeometrySplitsInsteadOfOvershootingOrErasingIt() {
        val points = (0..10).map { i -> LanePoint(if (i<5) 0.25+0.025*i else 0.55-0.025*i,0.4+0.05*i) }
        val curves = LaneBoundaryBezier.fit(points)
        assertTrue(curves.size>1); assertTrue(curves.size<=points.size-1)
        assertEquals(points.first(),curves.first().start); assertEquals(points.last(),curves.last().end); checkBound(points,curves)
    }

    @Test fun missingIntervalsAndInvalidPointsNeverBecomeConnectingCurves() {
        val points = listOf(LanePoint(0.3,0.4),LanePoint(0.31,0.45),LanePoint(0.32,0.5),
            LanePoint(0.4,0.75),LanePoint(0.41,0.8),LanePoint(0.42,0.85))
        val curves = LaneBoundaryBezier.fit(points)
        assertEquals(2,curves.size); assertEquals(points[2],curves[0].end); assertEquals(points[3],curves[1].start)
        val invalid = points.take(3)+LanePoint(Double.NaN,0.6)+points.takeLast(3)
        assertEquals(curves,LaneBoundaryBezier.fit(invalid))
        assertTrue(LaneBoundaryBezier.fit(emptyList()).isEmpty())
        assertTrue(LaneBoundaryBezier.fit(List(65) { points[0] }).isEmpty())
    }

    @Test fun manyIrregularInputsKeepTheWholePolylineErrorBound() {
        for (phase in 0 until 20) {
            val points = (0..15).map { i -> LanePoint(0.2+i*0.025+sin((i*7+phase).toDouble())*0.018,0.35+i*0.04) }
            val curves = LaneBoundaryBezier.fit(points)
            assertFalse(curves.isEmpty()); checkBound(points,curves)
        }
    }
}

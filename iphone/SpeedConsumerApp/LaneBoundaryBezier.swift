import Foundation

/// Display geometry only. Detection, confidence, timestamps and applicability keep the original points.
struct LaneBezierSegment: Equatable {
    let start, control1, control2, end: LanePoint

    func point(at t: Double) -> LanePoint {
        let u = 1 - t
        return LanePoint(x: u*u*u*start.x + 3*u*u*t*control1.x + 3*u*t*t*control2.x + t*t*t*end.x,
                         y: start.y + (end.y-start.y)*t)
    }
}

/// Fits a few cubics instead of bending the stroke through every noisy sample.
/// The deviation bound covers the complete input polyline, including between samples.
enum LaneBoundaryBezier {
    static let maximumDeviation = 2.0 / 383.0
    static let maximumGap = 0.16

    static func fit(_ points: [LanePoint]) -> [LaneBezierSegment] {
        guard points.count >= 2, points.count <= 64 else { return [] }
        var output: [LaneBezierSegment] = [], run: [LanePoint] = []
        func finish() {
            if run.count >= 2 { approximate(run, 0, run.count-1, &output) }
            run.removeAll(keepingCapacity: true)
        }
        for p in points {
            guard p.x.isFinite, p.y.isFinite, (0...1).contains(p.x), (0...1).contains(p.y) else {
                finish(); continue
            }
            if let previous = run.last, p.y <= previous.y || p.y-previous.y > maximumGap { finish() }
            run.append(p)
        }
        finish()
        return output
    }

    private static func approximate(_ points: [LanePoint], _ first: Int, _ last: Int,
                                    _ output: inout [LaneBezierSegment]) {
        let curve = fitted(points, first, last)
        let error = deviation(curve, points, first, last)
        if last-first == 1 || error.value <= maximumDeviation + 1e-12 {
            output.append(curve)
        } else {
            let split = max(first+1, min(last-1, error.split))
            approximate(points, first, split, &output)
            approximate(points, split, last, &output)
        }
    }

    private static func fitted(_ points: [LanePoint], _ first: Int, _ last: Int) -> LaneBezierSegment {
        let a = points[first], b = points[last], span = b.y-a.y
        var c1 = a.x+(b.x-a.x)/3, c2 = a.x+2*(b.x-a.x)/3
        var aa = 0.0, ab = 0.0, bb = 0.0, ar = 0.0, br = 0.0, qq = 0.0, qr = 0.0
        var low = min(a.x,b.x), high = max(a.x,b.x)
        if last-first > 1 {
            for i in (first+1)..<last {
                let p = points[i], t = (p.y-a.y)/span, u = 1-t
                let v1 = 3*u*u*t, v2 = 3*u*t*t, residual = p.x-u*u*u*a.x-t*t*t*b.x
                aa += v1*v1; ab += v1*v2; bb += v2*v2; ar += v1*residual; br += v2*residual
                let q = 2*u*t
                qq += q*q; qr += q*(p.x-u*u*a.x-t*t*b.x)
                low = min(low,p.x); high = max(high,p.x)
            }
            let determinant = aa*bb-ab*ab
            if determinant > 1e-12 {
                c1 = (ar*bb-br*ab)/determinant; c2 = (br*aa-ar*ab)/determinant
            } else if qq > 1e-12 {
                let q = qr/qq
                c1 = a.x+2*(q-a.x)/3; c2 = b.x+2*(q-b.x)/3
            }
        }
        // A Bézier stays inside its control hull: no extrapolation past observed extents.
        return LaneBezierSegment(start:a, control1:LanePoint(x:max(low,min(high,c1)),y:a.y+span/3),
            control2:LanePoint(x:max(low,min(high,c2)),y:a.y+2*span/3),end:b)
    }

    private static func deviation(_ curve: LaneBezierSegment, _ points: [LanePoint], _ first: Int,
                                  _ last: Int) -> (value: Double, split: Int) {
        let span = curve.end.y-curve.start.y
        let a = -curve.start.x+3*curve.control1.x-3*curve.control2.x+curve.end.x
        let b = 3*curve.start.x-6*curve.control1.x+3*curve.control2.x
        let c = -3*curve.start.x+3*curve.control1.x
        var maximum = 0.0, split = (first+last)/2
        for i in first..<last {
            let p = points[i], q = points[i+1]
            let t0 = (p.y-curve.start.y)/span, t1 = (q.y-curve.start.y)/span
            let slope = (q.x-p.x)/(t1-t0)
            var candidates = [t0,t1]
            if abs(3*a) < 1e-12 {
                if abs(2*b) > 1e-12 { candidates.append(-(c-slope)/(2*b)) }
            } else {
                let discriminant = 4*b*b-12*a*(c-slope)
                if discriminant >= 0 {
                    let root = sqrt(discriminant)
                    candidates.append((-2*b-root)/(6*a)); candidates.append((-2*b+root)/(6*a))
                }
            }
            for t in candidates where t >= t0 && t <= t1 {
                let error = abs(curve.point(at:t).x-(p.x+slope*(t-t0)))
                if error > maximum { maximum = error; split = i+1 }
            }
        }
        return (maximum,split)
    }
}

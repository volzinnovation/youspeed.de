import Foundation

/// Coordinates in the complete, upright analysis image (origin at top left).
struct LanePoint: Equatable, Sendable {
    let x: Double
    let y: Double
}

struct LaneBoundary: Equatable, Sendable {
    let points: [LanePoint]
    let confidence: Double
}

enum LaneDetectionState: String, Sendable {
    case reliable, uncertain, unavailable
}

/// Capture time in monotonic seconds. Runtime geometry/generation and timings travel separately.
struct LaneDetectionEstimate: Equatable, Sendable {
    let left: LaneBoundary?
    let right: LaneBoundary?
    let timestampSeconds: Double
    let state: LaneDetectionState

    var hasReliablePair: Bool { state == .reliable && left != nil && right != nil }

    /// Fill only the common observed interval; longer single-side evidence remains a stroke.
    var corridorPoints: [LanePoint] {
        guard hasReliablePair, let left, let right, left.points.count >= 2, right.points.count >= 2 else { return [] }
        let top = max(left.points[0].y, right.points[0].y)
        let bottom = min(left.points[left.points.count - 1].y, right.points[right.points.count - 1].y)
        guard bottom > top else { return [] }
        func clip(_ points: [LanePoint]) -> [LanePoint] {
            func at(_ y: Double) -> LanePoint {
                let index = max(1, points.firstIndex { $0.y >= y } ?? points.count - 1)
                let a = points[index - 1], b = points[index]
                let t = b.y > a.y ? (y - a.y) / (b.y - a.y) : 0
                return LanePoint(x: a.x + (b.x - a.x) * t, y: y)
            }
            return [at(top)] + points.filter { $0.y > top && $0.y < bottom } + [at(bottom)]
        }
        return clip(left.points) + clip(right.points).reversed()
    }
}

/// Bounded classical baseline shared with Android. Narrow bright ridges feed row-wise consensus
/// fits of converging boundaries. Missing sides are never invented; curved-road coverage is not
/// claimed. This is visual evidence, not a driving or speed-limit decision.
struct LaneDetector {
    private struct Stripe {
        let x: Double
        let y: Double
        let contrast: Double
    }

    private struct Fit {
        let slope: Double
        let intercept: Double
        let samples: [Stripe]
        func x(_ y: Double) -> Double { slope * y + intercept }
    }

    func detect(grayscale: [UInt8], width: Int, height: Int, timestampSeconds: Double) -> LaneDetectionEstimate {
        func unavailable() -> LaneDetectionEstimate {
            LaneDetectionEstimate(left: nil, right: nil, timestampSeconds: timestampSeconds, state: .unavailable)
        }
        // Bounds also prevent accidental full-resolution work on the camera thread.
        guard (64...640).contains(width), (64...960).contains(height),
              grayscale.count == width * height, timestampSeconds.isFinite else { return unavailable() }

        let aspectScale = min(1.0, Double(width) * 9.0 / (Double(height) * 16.0))
        let minimumSpan = max(0.07, 0.18 * aspectScale)
        let rowCount = min(48, Int((24 / aspectScale).rounded()))
        let rowStep = 0.46 / Double(rowCount - 1)
        let rows: [[Stripe]] = (0..<rowCount).map { index in
            let y = Int(((0.48 + Double(index) * rowStep) * Double(height - 1)).rounded())
            var radii: [Int] = []
            for radius in 1...4 {
                let value = max(1, Int((Double(radius * width) / 384).rounded()))
                if !radii.contains(value) { radii.append(value) }
            }
            let margin = 4 * (radii.max() ?? 1) + 2
            var candidates: [Stripe] = []
            var strengths = [Double](repeating: 0, count: width)
            func mean(_ center: Int, _ radius: Int) -> Double {
                var sum = 0
                for dy in -1...1 {
                    for dx in -radius...radius {
                        sum += Int(grayscale[(y + dy) * width + center + dx])
                    }
                }
                return Double(sum) / Double(3 * (2 * radius + 1))
            }
            let start = max(margin, Int((Double(width) * 0.04).rounded()))
            let end = min(width - margin, Int((Double(width) * 0.96).rounded()))
            for x in start..<end {
                var contrast = 0.0
                for radius in radii {
                    let center = mean(x, radius)
                    if center < 80 { continue }
                    let offset = 3 * radius + 1
                    let ridge = min(center - mean(x - offset, radius), center - mean(x + offset, radius))
                    contrast = max(contrast, ridge)
                }
                if contrast >= 24 { strengths[x] = contrast }
            }
            // Collapse each stripe to one local maximum before limiting candidates per side.
            let suppression = max(3, Int((Double(width) * 0.015).rounded()))
            for x in margin..<(width - margin) {
                let strength = strengths[x]
                if strength == 0 { continue }
                var winner = true
                for other in max(margin, x - suppression)...min(width - margin - 1, x + suppression) {
                    if strengths[other] > strength || (strengths[other] == strength && other < x) {
                        winner = false
                        break
                    }
                }
                if winner {
                    candidates.append(Stripe(x: Double(x) / Double(width - 1), y: Double(y) / Double(height - 1), contrast: strength))
                }
            }
            return candidates
        }
        // Stable ties explicitly match Kotlin's stable sort and left-to-right extraction order.
        func strongest(_ row: [Stripe], left: Bool) -> [Stripe] {
            Array(row.filter { left ? $0.x <= 0.56 : $0.x >= 0.44 }.sorted {
                $0.contrast == $1.contrast ? $0.x < $1.x : $0.contrast > $1.contrast
            }.prefix(4))
        }
        var left = boundary(rows.map { strongest($0, left: true) }, isLeft: true, minimumSpan: minimumSpan, rowStep: rowStep)
        var right = boundary(rows.map { strongest($0, left: false) }, isLeft: false, minimumSpan: minimumSpan, rowStep: rowStep)
        if let l = left, let r = right, !plausiblePair(l, r, minimumSpan: minimumSpan) {
            // Conflicting fits do not identify an ego lane. Keep only a substantially better side.
            if l.confidence > r.confidence + 0.20 { right = nil }
            else if r.confidence > l.confidence + 0.20 { left = nil }
            else { left = nil; right = nil }
        }
        let state: LaneDetectionState
        if left == nil && right == nil { state = .unavailable }
        else if let l = left, let r = right, min(l.confidence, r.confidence) >= 0.62 { state = .reliable }
        else { state = .uncertain }
        return LaneDetectionEstimate(left: left, right: right, timestampSeconds: timestampSeconds, state: state)
    }

    private func boundary(_ rows: [[Stripe]], isLeft: Bool, minimumSpan: Double, rowStep: Double) -> LaneBoundary? {
        var best: Fit?
        var bestScore = 0.0
        var alternative: Fit?
        var alternativeScore = 0.0
        func valid(_ slope: Double, _ intercept: Double, _ topY: Double, _ bottomY: Double) -> Bool {
            guard (isLeft ? (-3.0 ... -0.15).contains(slope) : (0.15...3.0).contains(slope)) else { return false }
            let top = slope * topY + intercept
            let bottom = slope * bottomY + intercept
            return (0.22...0.78).contains(top) && (isLeft ? (0.02...0.49).contains(bottom) : (0.51...0.98).contains(bottom))
        }
        func distinct(_ a: Fit, _ b: Fit) -> Bool { abs(a.x(min(a.samples.last!.y, b.samples.last!.y)) - b.x(min(a.samples.last!.y, b.samples.last!.y))) > 0.075 }
        let separation = Int(ceil(minimumSpan / rowStep))
        for topRow in 0..<(rows.count - separation) {
            for bottomRow in (topRow + separation)..<rows.count {
                for top in rows[topRow] {
                    for bottom in rows[bottomRow] {
                        let slope = (bottom.x - top.x) / (bottom.y - top.y)
                        let intercept = top.x - slope * top.y
                        if !valid(slope, intercept, top.y, bottom.y) { continue }
                        let samples: [Stripe] = rows.compactMap { row in
                            guard let point = row.min(by: { abs($0.x - (slope * $0.y + intercept)) < abs($1.x - (slope * $1.y + intercept)) }),
                                  abs(point.x - (slope * point.y + intercept)) <= 0.018 else { return nil }
                            return point
                        }
                        guard samples.count >= 8, let first = samples.first, let last = samples.last,
                              last.y - first.y >= minimumSpan else { continue }
                        let score = samples.reduce(0) { $0 + min(1.0, $1.contrast / 70.0) }
                        let fit = Fit(slope: slope, intercept: intercept, samples: samples)
                        if score > bestScore {
                            if let oldBest = best, distinct(fit, oldBest) {
                                alternative = oldBest; alternativeScore = bestScore
                            }
                            best = fit; bestScore = score
                        } else if let oldBest = best, distinct(fit, oldBest), score > alternativeScore {
                            alternative = fit; alternativeScore = score
                        }
                    }
                }
            }
        }
        guard let seed = best, let first = seed.samples.first, let last = seed.samples.last else { return nil }
        let samples = seed.samples
        let count = Double(samples.count)
        let meanY = samples.reduce(0) { $0 + $1.y } / count
        let meanX = samples.reduce(0) { $0 + $1.x } / count
        let variance = samples.reduce(0) { $0 + ($1.y - meanY) * ($1.y - meanY) }
        guard variance > 0 else { return nil }
        let slope = samples.reduce(0) { $0 + ($1.y - meanY) * ($1.x - meanX) } / variance
        let intercept = meanX - slope * meanY
        guard valid(slope, intercept, first.y, last.y) else { return nil }
        let residual = samples.reduce(0) { $0 + abs($1.x - (slope * $1.y + intercept)) } / count
        let span = last.y - first.y
        let expectedRows = 1.0 + span / rowStep
        var confidence = min(1.0, count / expectedRows) * min(1.0, span / (minimumSpan * (0.28 / 0.18)))
            * min(1.0, samples.reduce(0) { $0 + $1.contrast } / count / 55.0) * max(0.0, 1.0 - residual / 0.04)
        if let other = alternative, alternativeScore >= bestScore * 0.88, distinct(seed, other) { confidence = min(confidence, 0.49) }
        guard confidence >= 0.38 else { return nil }
        // Render only the observed extent; there is no extrapolated/inferred geometry.
        let points = (0..<5).map { index -> LanePoint in
            let y = first.y + span * Double(index) / 4
            return LanePoint(x: min(1, max(0, slope * y + intercept)), y: y)
        }
        return LaneBoundary(points: points, confidence: min(1, max(0, confidence)))
    }

    private func plausiblePair(_ left: LaneBoundary, _ right: LaneBoundary, minimumSpan: Double) -> Bool {
        func x(_ boundary: LaneBoundary, _ y: Double) -> Double {
            let a = boundary.points[0], b = boundary.points[boundary.points.count - 1]
            return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
        }
        let topY = max(left.points[0].y, right.points[0].y)
        let bottomY = min(left.points[left.points.count - 1].y, right.points[right.points.count - 1].y)
        guard bottomY - topY >= minimumSpan else { return false }
        let topWidth = x(right, topY) - x(left, topY)
        let bottomWidth = x(right, bottomY) - x(left, bottomY)
        let center = (x(right, bottomY) + x(left, bottomY)) / 2
        return (0.015...0.55).contains(topWidth) && (0.24...0.94).contains(bottomWidth)
            && bottomWidth > topWidth + 0.10 && (0.32...0.68).contains(center)
    }
}

/// Single-worker state. Missing sides disappear immediately; geometry is never predicted forward.
struct LaneTracker {
    private var previous: LaneDetectionEstimate?
    private var consecutivePairs = 0

    mutating func reset() { previous = nil; consecutivePairs = 0 }

    mutating func update(_ estimate: LaneDetectionEstimate) -> LaneDetectionEstimate {
        var prior = previous
        guard estimate.timestampSeconds.isFinite else {
            reset()
            return LaneDetectionEstimate(left: nil, right: nil, timestampSeconds: estimate.timestampSeconds, state: .unavailable)
        }
        if let p = prior, estimate.timestampSeconds <= p.timestampSeconds || estimate.timestampSeconds - p.timestampSeconds > 0.6 {
            reset(); prior = nil
        }
        func compatible(_ old: LaneBoundary?, _ current: LaneBoundary?) -> Bool {
            guard let old, let current, old.points.count == current.points.count else { return false }
            return zip(old.points, current.points).allSatisfy { abs($0.x - $1.x) <= 0.065 && abs($0.y - $1.y) <= 0.06 }
        }
        func smooth(_ old: LaneBoundary?, _ current: LaneBoundary?) -> LaneBoundary? {
            guard let old, let current, compatible(old, current) else { return current }
            return LaneBoundary(points: zip(old.points, current.points).map { LanePoint(x: $0.x * 0.30 + $1.x * 0.70, y: $1.y) }, confidence: current.confidence)
        }
        let pairMatches = prior != nil && compatible(prior?.left, estimate.left) && compatible(prior?.right, estimate.right)
        consecutivePairs = estimate.hasReliablePair ? (pairMatches ? consecutivePairs + 1 : 1) : 0
        let result = LaneDetectionEstimate(left: smooth(prior?.left, estimate.left), right: smooth(prior?.right, estimate.right),
            timestampSeconds: estimate.timestampSeconds, state: estimate.hasReliablePair && consecutivePairs < 2 ? .uncertain : estimate.state)
        previous = result
        return result
    }
}

import Foundation

/// Shared Android/iPhone kernel: horizontal five-pixel opening, then saturated 1.5× top-hat.
/// Borders repeat the nearest pixel (equivalent to clipped min/max windows). Integer division
/// rounds down; the original image for TSR is never modified. Cancellation returns no partial image.
enum RoadBoundaryPreprocessor {
    static let identifier = "horizontal_top_hat5_gain_1_5_v1"
    static func topHat5(grayscale: [UInt8], width: Int, height: Int,
                        shouldContinue: () -> Bool = { true }) -> [UInt8]? {
        guard (1...384).contains(width), (1...216).contains(height), grayscale.count == width*height,
              shouldContinue() else { return nil }
        var eroded = [UInt8](repeating: 0, count: grayscale.count)
        var output = eroded
        for y in 0..<height {
            guard shouldContinue() else { return nil }
            for x in 0..<width {
                if x % 32 == 0 && !shouldContinue() { return nil }
                var value: UInt8 = 255
                for column in max(0,x-2)...min(width-1,x+2) { value = min(value,grayscale[y*width+column]) }
                eroded[y*width+x] = value
            }
        }
        for y in 0..<height {
            guard shouldContinue() else { return nil }
            for x in 0..<width {
                if x % 32 == 0 && !shouldContinue() { return nil }
                var opened: UInt8 = 0
                for column in max(0,x-2)...min(width-1,x+2) { opened = max(opened,eroded[y*width+column]) }
                let value = Int(grayscale[y*width+x])
                output[y*width+x] = UInt8(min(255,value+(value-Int(opened))*3/2))
            }
        }
        return shouldContinue() ? output : nil
    }
}

/// Image evidence only: even a paint cue is not a semantic road/lane classification.
enum RoadBoundaryCue: String, Equatable, Sendable { case paint, edge }
enum RoadBoundaryProvenance: String, Equatable, Sendable { case fresh, tracked, fused }
struct RoadBoundaryEvidence: Equatable, Sendable {
    let points: [LanePoint]
    let confidence: Double
    let cue: RoadBoundaryCue
    let supportRows: Int
    var provenance: RoadBoundaryProvenance = .fresh
    var lastFreshTimestampSeconds: Double? = nil
    var evidenceAgeSeconds: Double = 0
    var trackedAnchorCount: Int = 0
}
/// Unassigned hypotheses: a calibrated trajectory must identify the ego path.
struct RoadCorridorHypothesis: Equatable, Sendable {
    let leftBoundaryIndex: Int
    let rightBoundaryIndex: Int
    let confidence: Double
}
struct RoadBoundaryFrame: Equatable, Sendable {
    let boundaries: [RoadBoundaryEvidence]
    let corridors: [RoadCorridorHypothesis]
    let timestampSeconds: Double
    var budgetExceeded = false
    var operationCount = 0
    var temporalOperationCount = 0
    var temporalResetReason: String? = nil
}
struct RoadBoundarySearchGuidance {
    var horizonY: Double? = nil
    var polylines: [[LanePoint]] = []
}
func roadBoundaryXAt(_ points: [LanePoint], _ y: Double) -> Double {
    if y <= points[0].y { return points[0].x }
    if y >= points[points.count-1].y { return points[points.count-1].x }
    let index = max(1,points.firstIndex { $0.y >= y } ?? points.count-1)
    let a = points[index-1], b = points[index]
    return a.x+(b.x-a.x)*(y-a.y)/(b.y-a.y)
}

/// Bounded CPU image front end, shared arithmetically with Android. The caller provides upright
/// luma reduced with one aspect-preserving scale to at most 384 x 216. Twenty-four prefix-summed
/// rows feed capped piecewise tracks: curves and multiple boundaries retain their observed shape.
/// Edge-only structures never create corridors. Buildings/shadows can still resemble markings;
/// these visual hypotheses cannot establish drivable space or sign applicability. A cancelled or
/// expired call publishes no partial geometry and retains no state from earlier frames.
struct RoadBoundaryDetector {
    private struct Sample {
        let point: LanePoint
        let strength: Double
        let cue: RoadBoundaryCue
        let row: Int
    }
    private final class Track {
        var samples: [Sample]
        let guide: [LanePoint]?
        let guideCorrectionLimit: Double
        init(_ sample: Sample, guide: [LanePoint]? = nil, guideCorrectionLimit: Double) {
            samples = [sample]; self.guide = guide; self.guideCorrectionLimit = guideCorrectionLimit
        }
        func predictedX(_ y: Double) -> Double {
            let last = samples[samples.count - 1]
            let guided = guide.map { last.point.x + roadBoundaryXAt($0,y)-roadBoundaryXAt($0,last.point.y) }
            guard samples.count > 1 else { return guided ?? last.point.x }
            let before = samples[max(0, samples.count - 3)]
            let slope = max(-2, min(2, (last.point.x - before.point.x) / (last.point.y - before.point.y)))
            let local = last.point.x + slope * (y - last.point.y)
            // Two current observations outrank an older curve. A prior may only nudge the
            // next association by one analysis pixel, never bend it onto adjacent paint.
            return guided.map { local + max(-guideCorrectionLimit,min(guideCorrectionLimit,0.4*($0-local))) } ?? local
        }
    }

    func detect(grayscale: [UInt8], width: Int, height: Int, timestampSeconds: Double,
                maximumOperations: Int = 250_000, guidance: RoadBoundarySearchGuidance? = nil,
                shouldContinue: () -> Bool = { true }) -> RoadBoundaryFrame {
        let maximum = max(0, maximumOperations)
        var used = 0
        func check(_ cost: Int = 1) -> Bool {
            guard cost <= maximum - used else { return false }
            used += cost
            return shouldContinue()
        }
        func empty(_ exceeded: Bool = false) -> RoadBoundaryFrame {
            RoadBoundaryFrame(boundaries: [], corridors: [], timestampSeconds: timestampSeconds,
                              budgetExceeded: exceeded, operationCount: used)
        }
        guard (64...384).contains(width), (64...216).contains(height),
              grayscale.count == width * height, timestampSeconds.isFinite else { return empty() }
        guard check() else { return empty(true) }
        var active: [Track] = []
        var completed: [Track] = []
        var prefix = [Int](repeating: 0, count: width + 1)
        var strengths = [Double](repeating: 0, count: width)
        var paints = [Bool](repeating: false, count: width)
        var radii: [Int] = []
        for radius in 1...3 {
            let value = max(1, Int((Double(radius * width) / 384).rounded()))
            if !radii.contains(value) { radii.append(value) }
        }
        let margin = 4 * radii[radii.count - 1] + 2
        let suppression = max(3, Int((Double(width) * 0.012).rounded()))
        let guides = Array((guidance?.polylines ?? []).prefix(8)).filter { points in
            (2...12).contains(points.count) && points.allSatisfy { $0.x.isFinite && $0.y.isFinite && (0...1).contains($0.x) && (0...1).contains($0.y) } &&
            zip(points,points.dropFirst()).allSatisfy { $1.y > $0.y }
        }
        let topY = guidance?.horizonY.flatMap { $0.isFinite ? min(0.83,max(0.08,$0+0.03)) : nil } ?? 0.50
        let rowCount = max(8,min(24,Int(((0.94-topY)*Double(height-1)).rounded())+1))
        for row in 0..<rowCount {
            guard check() else { return empty(true) }
            let y = Int(((0.94 - Double(row) * (0.94-topY) / Double(rowCount - 1)) * Double(height - 1)).rounded())
            let normalizedY = Double(y) / Double(height - 1)
            prefix[0] = 0
            for x in 0..<width {
                if x % 32 == 0 && !check(32) { return empty(true) }
                strengths[x] = 0
                paints[x] = false
                prefix[x + 1] = prefix[x] + Int(grayscale[(y - 1) * width + x]) +
                    Int(grayscale[y * width + x]) + Int(grayscale[(y + 1) * width + x])
            }
            func mean(_ center: Int, _ radius: Int) -> Double {
                Double(prefix[center + radius + 1] - prefix[center - radius]) / Double(3 * (2 * radius + 1))
            }
            for x in margin..<(width - margin) {
                if x % 32 == 0 && !check(32 * radii.count) { return empty(true) }
                var ridge = 0.0
                for radius in radii {
                    let middle = mean(x, radius)
                    if middle >= 95 {
                        let offset = 3 * radius + 1
                        ridge = max(ridge, min(middle - mean(x - offset, radius), middle - mean(x + offset, radius)))
                    }
                }
                let edge = abs(mean(x - 3, 1) - mean(x + 3, 1))
                if ridge >= 26 { strengths[x] = ridge; paints[x] = true }
                else if edge >= 45 { strengths[x] = edge * 0.45 }
            }
            var candidates: [Sample] = []
            for x in margin..<(width - margin) {
                if x % 32 == 0 && !check(32 * (2 * suppression + 1)) { return empty(true) }
                if strengths[x] == 0 { continue }
                var winner = true
                for other in max(margin, x - suppression)...min(width - margin - 1, x + suppression) {
                    if strengths[other] > strengths[x] || (strengths[other] == strengths[x] && other < x) {
                        winner = false; break
                    }
                }
                if winner {
                    candidates.append(Sample(point: LanePoint(x: Double(x) / Double(width - 1), y: normalizedY),
                                             strength: strengths[x], cue: paints[x] ? .paint : .edge, row: row))
                }
            }
            func rank(_ sample: Sample) -> Double {
                let distance = guides.map { abs(sample.point.x-roadBoundaryXAt($0,sample.point.y)) }.min() ?? 1
                return sample.strength*(1+0.15*max(0,min(1,1-distance/0.08)))
            }
            let rowCandidates = Array(candidates.sorted {
                let a = rank($0), b = rank($1)
                return a == b ? $0.point.x < $1.point.x : a > b
            }.prefix(12))
            completed.append(contentsOf: active.filter { row - $0.samples[$0.samples.count - 1].row > 4 })
            active.removeAll { row - $0.samples[$0.samples.count - 1].row > 4 }
            var usedTracks = [Bool](repeating: false, count: active.count)
            var usedCandidates = [Bool](repeating: false, count: rowCandidates.count)
            // At most 12 x 12 comparisons per assignment, at most 12 assignments per row.
            for _ in 0..<min(active.count, rowCandidates.count) {
                var bestTrack = -1, bestCandidate = -1
                var bestDistance = Double.infinity
                for trackIndex in active.indices {
                    guard check(rowCandidates.count + 1) else { return empty(true) }
                    if usedTracks[trackIndex] { continue }
                    let track = active[trackIndex]
                    let gap = row - track.samples[track.samples.count - 1].row
                    let tolerance = track.samples.count == 1 ? 0.065 : 0.028 + 0.012 * Double(gap - 1)
                    for candidateIndex in rowCandidates.indices {
                        if usedCandidates[candidateIndex] { continue }
                        let distance = abs(rowCandidates[candidateIndex].point.x - track.predictedX(normalizedY))
                        if distance <= tolerance && distance < bestDistance {
                            bestDistance = distance; bestTrack = trackIndex; bestCandidate = candidateIndex
                        }
                    }
                }
                if bestTrack >= 0 {
                    active[bestTrack].samples.append(rowCandidates[bestCandidate])
                    usedTracks[bestTrack] = true; usedCandidates[bestCandidate] = true
                }
            }
            for index in rowCandidates.indices {
                if !usedCandidates[index] && active.count < 12 {
                    let sample = rowCandidates[index]
                    let closest = guides.min { abs(sample.point.x-roadBoundaryXAt($0,sample.point.y)) < abs(sample.point.x-roadBoundaryXAt($1,sample.point.y)) }
                    let guide = closest.flatMap { abs(sample.point.x-roadBoundaryXAt($0,sample.point.y)) <= 0.05 ? $0 : nil }
                    active.append(Track(sample,guide:guide,guideCorrectionLimit:1/Double(width-1)))
                }
            }
        }
        completed.append(contentsOf: active)
        var evidence: [RoadBoundaryEvidence] = []
        for track in completed {
            guard check(track.samples.count + 1) else { return empty(true) }
            let samples = track.samples
            let span = samples[0].point.y - samples[samples.count - 1].point.y
            if samples.count < 8 || span < min(0.16,(0.94-topY)*0.6) { continue }
            let paintCount = samples.filter { $0.cue == .paint }.count
            let cue: RoadBoundaryCue = paintCount >= 6 && paintCount * 5 >= samples.count * 3 ? .paint : .edge
            let density = Double(samples.count) / Double(samples[samples.count - 1].row - samples[0].row + 1)
            var confidence = min(1, span / 0.32) * density * min(1, samples.reduce(0) { $0 + $1.strength } / Double(samples.count) / 90)
            if cue == .edge { confidence = min(0.40, confidence) }
            if confidence < 0.22 { continue }
            evidence.append(RoadBoundaryEvidence(points: samples.reversed().map { $0.point }, confidence: confidence,
                                                 cue: cue, supportRows: samples.count))
        }
        let boundaries = Array(evidence.sorted {
            if $0.confidence != $1.confidence { return $0.confidence > $1.confidence }
            if $0.supportRows != $1.supportRows { return $0.supportRows > $1.supportRows }
            return $0.points[$0.points.count - 1].x < $1.points[$1.points.count - 1].x
        }.prefix(6)).sorted { $0.points[$0.points.count - 1].x < $1.points[$1.points.count - 1].x }
        var corridors: [RoadCorridorHypothesis] = []
        for leftIndex in boundaries.indices {
            guard check(32) else { return empty(true) }
            // Adjacent observed boundaries only; do not skip a marking to invent a lane.
            let rightIndex = leftIndex + 1
            if rightIndex >= boundaries.count { continue }
            let left = boundaries[leftIndex], right = boundaries[rightIndex]
            if left.cue != .paint || right.cue != .paint || min(left.supportRows, right.supportRows) < 10 { continue }
            let top = max(left.points[0].y, right.points[0].y)
            let bottom = min(left.points[left.points.count - 1].y, right.points[right.points.count - 1].y)
            if bottom - top < 0.24 { continue }
            let topWidth = xAt(right.points, top) - xAt(left.points, top)
            let bottomWidth = xAt(right.points, bottom) - xAt(left.points, bottom)
            if !(0.015...0.60).contains(topWidth) || !(0.09...0.85).contains(bottomWidth) || bottomWidth < topWidth + 0.04 { continue }
            let overlapRows = (left.points + right.points).filter { $0.y >= top && $0.y <= bottom }
            if overlapRows.contains(where: { xAt(right.points, $0.y) - xAt(left.points, $0.y) < 0.012 }) { continue }
            corridors.append(RoadCorridorHypothesis(leftBoundaryIndex: leftIndex, rightBoundaryIndex: rightIndex,
                                                   confidence: min(left.confidence, right.confidence)))
        }
        guard check() else { return empty(true) }
        return RoadBoundaryFrame(boundaries: boundaries, corridors: Array(corridors.sorted {
            $0.confidence == $1.confidence ? $0.leftBoundaryIndex < $1.leftBoundaryIndex : $0.confidence > $1.confidence
        }.prefix(2)), timestampSeconds: timestampSeconds, budgetExceeded: false, operationCount: used)
    }

    private func xAt(_ points: [LanePoint], _ y: Double) -> Double {
        let index = max(1, points.firstIndex { $0.y >= y } ?? points.count - 1)
        let a = points[index - 1], b = points[index]
        return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
    }
}

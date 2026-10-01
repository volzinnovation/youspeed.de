import Foundation

/// Shared Android/iPhone kernel: horizontal five-pixel opening, then saturated 1.5× top-hat.
/// Borders repeat the nearest pixel (equivalent to clipped min/max windows). Integer division
/// rounds down; the original image for TSR is never modified. Cancellation returns no partial image.
enum RoadBoundaryPreprocessor {
    static let identifier = "horizontal_top_hat5_gain_1_5_v1"
    static func topHat5(grayscale: [UInt8], width: Int, height: Int,
                        shouldContinue: () -> Bool = { true }) -> [UInt8]? {
        topHatRows(grayscale:grayscale,width:width,height:height,rows:Array(0..<max(0,min(216,height))),shouldContinue:shouldContinue)
    }
    /// Non-support rows are zero; this output is only valid for the detector with the same horizon.
    static func topHat5ForDetector(grayscale: [UInt8], width: Int, height: Int, horizonY: Double? = nil,
                                  shouldContinue: () -> Bool = { true }) -> [UInt8]? {
        guard (64...384).contains(width), (64...216).contains(height), grayscale.count == width*height else { return nil }
        return topHatRows(grayscale:grayscale,width:width,height:height,
            rows:RoadBoundarySamplingRows.support(height:height,horizonY:horizonY),shouldContinue:shouldContinue)
    }
    private static func topHatRows(grayscale: [UInt8], width: Int, height: Int, rows: [Int],
                                   shouldContinue: () -> Bool) -> [UInt8]? {
        guard (1...384).contains(width), (1...216).contains(height), grayscale.count == width*height,
              shouldContinue() else { return nil }
        var eroded = [UInt8](repeating: 0, count: grayscale.count)
        var output = eroded
        for y in rows {
            guard shouldContinue() else { return nil }
            for x in 0..<width {
                if x % 32 == 0 && !shouldContinue() { return nil }
                var value: UInt8 = 255
                for column in max(0,x-2)...min(width-1,x+2) { value = min(value,grayscale[y*width+column]) }
                eroded[y*width+x] = value
            }
        }
        for y in rows {
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
    /// Current exposure's contiguous paint support. Empty retains the legacy full-points contract.
    var observedSegments: [[LanePoint]] = []
    var geometryConfidence: Double? = nil
    var paintOccupancy: Double? = nil
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
    var rejectionCounts: [String: Int] = [:]
    var detectionVariant: String = "baseline"
}
struct RoadBoundaryDetectionOptions: Equatable, Sendable {
    var useSearchBands = false
    var groupFragments = false
    var identifier: String { useSearchBands ? (groupFragments ? "bands_fragments" : "bands") : (groupFragments ? "fragments" : "baseline") }
}
struct RoadBoundarySearchGuidance {
    var horizonY: Double? = nil
    var polylines: [[LanePoint]] = []
}
/// Exact rows shared by detection and sparse horizontal preprocessing.
enum RoadBoundarySamplingRows {
    static func top(_ horizonY: Double?) -> Double {
        horizonY.flatMap { $0.isFinite ? min(0.83,max(0.08,$0+0.03)) : nil } ?? 0.50
    }
    static func centers(height: Int, horizonY: Double?) -> [Int] {
        let topY = top(horizonY)
        let count = max(8,min(24,Int(((0.94-topY)*Double(height-1)).rounded())+1))
        return (0..<count).map { row in Int(((0.94-Double(row)*(0.94-topY)/Double(count-1))*Double(height-1)).rounded()) }
    }
    static func support(height: Int, horizonY: Double?) -> [Int] {
        Array(Set(centers(height:height,horizonY:horizonY).flatMap { [$0-1,$0,$0+1] })).sorted()
    }
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
        let stripeWidth: Int
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
                options: RoadBoundaryDetectionOptions = RoadBoundaryDetectionOptions(),
                shouldContinue: () -> Bool = { true }) -> RoadBoundaryFrame {
        let maximum = max(0, maximumOperations)
        var used = 0
        var rejections: [String: Int] = [:]
        func reject(_ reason: String, _ count: Int = 1) { if count > 0 { rejections[reason, default: 0] += count } }
        func check(_ cost: Int = 1) -> Bool {
            guard cost <= maximum - used else { return false }
            used += cost
            return shouldContinue()
        }
        func empty(_ exceeded: Bool = false) -> RoadBoundaryFrame {
            RoadBoundaryFrame(boundaries: [], corridors: [], timestampSeconds: timestampSeconds,
                              budgetExceeded: exceeded, operationCount: used, rejectionCounts: rejections, detectionVariant: options.identifier)
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
        let topY = RoadBoundarySamplingRows.top(guidance?.horizonY)
        let rows = RoadBoundarySamplingRows.centers(height:height,horizonY:guidance?.horizonY)
        for row in rows.indices {
            guard check() else { return empty(true) }
            let y = rows[row]
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
                    var stripeWidth = 1
                    if options.groupFragments && paints[x] {
                        guard check(26) else { return empty(true) }
                        var left = x, right = x
                        while left > margin && paints[left-1] && x-left < 12 { left -= 1 }
                        while right < width-margin-1 && paints[right+1] && right-x < 12 { right += 1 }
                        stripeWidth = right-left+1
                    }
                    candidates.append(Sample(point: LanePoint(x: Double(x) / Double(width - 1), y: normalizedY),
                                             strength: strengths[x], cue: paints[x] ? .paint : .edge, row: row, stripeWidth: stripeWidth))
                }
            }
            func rank(_ sample: Sample) -> Double {
                let distance = guides.map { abs(sample.point.x-roadBoundaryXAt($0,sample.point.y)) }.min() ?? 1
                return sample.strength*(1+0.15*max(0,min(1,1-distance/0.08)))
            }
            let ranked = candidates.sorted {
                let a = rank($0), b = rank($1)
                return a == b ? $0.point.x < $1.point.x : a > b
            }
            var rowCandidates = Array(ranked.prefix(12))
            if options.useSearchBands {
                guard check(candidates.count*3+24) else { return empty(true) }
                // Reserve equal capacity around two curved hypotheses, then fill from the full
                // image. This never crops a stripe away or manufactures paint from calibration.
                let t = max(0,min(1,(normalizedY-topY)/max(0.01,0.94-topY)))
                let ordered = guides.sorted { roadBoundaryXAt($0,0.94) < roadBoundaryXAt($1,0.94) }
                let centers = ordered.count >= 2 ? [roadBoundaryXAt(ordered[0],normalizedY),roadBoundaryXAt(ordered[ordered.count-1],normalizedY)] : [0.5-0.07-0.29*t,0.5+0.07+0.29*t]
                let halfWidth = 0.045+0.105*t
                var selected = Set<Int>()
                var indices: [Int] = []
                for center in centers {
                    var reserved = 0
                    for index in ranked.indices where reserved < 4 {
                        if abs(ranked[index].point.x-center) <= halfWidth && !selected.contains(index) {
                            selected.insert(index); indices.append(index); reserved += 1
                        }
                    }
                }
                for index in ranked.indices where indices.count < 12 {
                    if selected.insert(index).inserted { indices.append(index) }
                }
                rowCandidates = indices.sorted().map { ranked[$0] }
                reject("outside_bands_retained",rowCandidates.filter { sample in centers.allSatisfy { abs(sample.point.x-$0)>halfWidth } }.count)
            }
            reject("candidate_capacity",candidates.count-rowCandidates.count)
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
        // Accept the original measured tracks first. Gap fitting is an additive recovery
        // path: a failed global model must never erase a supported continuous border.
        var evidence: [RoadBoundaryEvidence] = []
        var fragments: [[Sample]] = []
        for track in completed {
            guard check(track.samples.count + 1) else { return empty(true) }
            let samples = track.samples
            let span = samples[0].point.y - samples[samples.count - 1].point.y
            if samples.count < 8 {
                reject("track_support")
                if options.groupFragments { fragments.append(samples) }
                continue
            }
            if span < min(0.16,(0.94-topY)*0.6) {
                reject("track_span")
                if options.groupFragments { fragments.append(samples) }
                continue
            }
            let paintCount = samples.filter { $0.cue == .paint }.count
            let cue: RoadBoundaryCue = paintCount >= 6 && paintCount * 5 >= samples.count * 3 ? .paint : .edge
            let density = Double(samples.count) / Double(samples[samples.count - 1].row - samples[0].row + 1)
            var confidence = min(1, span / 0.32) * density * min(1, samples.reduce(0) { $0 + $1.strength } / Double(samples.count) / 90)
            if cue == .edge { confidence = min(0.40, confidence) }
            if confidence < 0.22 {
                reject("confidence")
                if options.groupFragments { fragments.append(samples) }
                continue
            }
            evidence.append(RoadBoundaryEvidence(points:samples.reversed().map { $0.point },confidence:confidence,cue:cue,
                supportRows:samples.count,observedSegments:options.groupFragments && cue == .paint ? paintedSegments(samples) : [],
                paintOccupancy:options.groupFragments && cue == .paint ? density : nil))
            if options.groupFragments { reject("supported_track_preserved") }
        }
        func ranked(_ values:[RoadBoundaryEvidence]) -> [RoadBoundaryEvidence] {
            values.sorted {
                if $0.confidence != $1.confidence { return $0.confidence > $1.confidence }
                if $0.supportRows != $1.supportRows { return $0.supportRows > $1.supportRows }
                return $0.points[$0.points.count-1].x < $1.points[$1.points.count-1].x
            }
        }
        let protected = Array(ranked(evidence).prefix(6))
        var additions: [RoadBoundaryEvidence] = []
        if options.groupFragments {
            // Only rejected short/sparse fragments are eligible; accepted raw tracks cannot
            // be consumed by a speculative join or displaced by it at the output cap.
            fragments.sort { $0.count == $1.count ? $0[0].point.x < $1[0].point.x : $0.count > $1.count }
            reject("fragment_capacity",max(0,fragments.count-32))
            fragments = Array(fragments.prefix(32))
            var consumed = Set<Int>()
            for i in fragments.indices {
                if consumed.contains(i) { continue }
                var changed = true
                while changed {
                    changed = false
                    for j in fragments.indices where j != i && !consumed.contains(j) {
                        let first = fragments[i], second = fragments[j]
                        guard check((first.count+second.count)*8+30) else { return empty(true) }
                        if let joined = joinFragments(first,second,width:width,reject:{ reject($0) }) {
                            fragments[i] = joined; consumed.insert(j); changed = true
                            reject("fragments_joined")
                        }
                    }
                }
            }
            for (index,samples) in fragments.enumerated() where !consumed.contains(index) {
                guard check(samples.count*8+30) else { return empty(true) }
                let span = samples[0].point.y-samples[samples.count-1].point.y
                if samples.count < 6 { reject("fragment_track_support"); continue }
                if span < min(0.16,(0.94-topY)*0.6) { reject("fragment_track_span"); continue }
                let paintCount = samples.filter { $0.cue == .paint }.count
                if paintCount < 6 || paintCount*5 < samples.count*3 { reject("fragment_paint_support"); continue }
                let segments = paintedSegments(samples)
                // A fit has a purpose only when there is an actual gap between observed
                // paint intervals. Continuous measured shape never needs this global test.
                if segments.filter({ $0.count >= 2 }).count < 2 { reject("fragment_no_supported_gap"); continue }
                guard let model = validatedModel(samples,residualLimit:max(0.014,2/Double(width-1)),
                    reject:{ reject($0) }) else { continue }
                let density = Double(samples.count)/Double(samples[samples.count-1].row-samples[0].row+1)
                let geometric = max(0,1-model.maximumResidual/max(0.028,4/Double(width-1)))
                let confidence = min(1,span/0.32)*min(1,Double(paintCount)/10)*geometric *
                    min(1,samples.reduce(0) { $0+$1.strength }/Double(samples.count)/90)
                if confidence < 0.22 { reject("fragment_confidence"); continue }
                additions.append(RoadBoundaryEvidence(points:model.points,confidence:confidence,cue:.paint,supportRows:samples.count,
                    observedSegments:segments,geometryConfidence:geometric,paintOccupancy:density))
            }
        }
        reject("fragment_output_capacity",max(0,additions.count-(6-protected.count)))
        let boundaries = (protected+ranked(additions).prefix(6-protected.count)).sorted {
            $0.points[$0.points.count-1].x < $1.points[$1.points.count-1].x
        }
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
        }.prefix(2)), timestampSeconds: timestampSeconds, budgetExceeded: false, operationCount: used, rejectionCounts: rejections, detectionVariant: options.identifier)
    }

    private struct Model {
        let points: [LanePoint]
        let maximumResidual: Double
        let maximumSlope: Double
        let curvature: Double
    }
    /// Fit in a centered, scaled row coordinate to keep the 3x3 system conditioned.
    /// All observations must agree; a bright outlier cannot be silently fitted away.
    private func fitModel(_ samples: [Sample]) -> Model? {
        guard samples.count >= 3 else { return nil }
        let low = samples.map { $0.point.y }.min()!, high = samples.map { $0.point.y }.max()!
        let scale = high-low, center = (high+low)/2
        guard scale >= 0.035 else { return nil }
        var matrix = Array(repeating:Array(repeating:0.0,count:4),count:3)
        for sample in samples {
            let t = (sample.point.y-center)/scale, v = [1.0,t,t*t]
            for r in 0..<3 { for c in 0..<3 { matrix[r][c] += v[r]*v[c] }; matrix[r][3] += v[r]*sample.point.x }
        }
        for column in 0..<3 {
            let pivot = (column..<3).max { abs(matrix[$0][column]) < abs(matrix[$1][column]) }!
            if abs(matrix[pivot][column]) < 1e-9 { return nil }
            if pivot != column { matrix.swapAt(pivot,column) }
            let divisor = matrix[column][column]
            for c in column..<4 { matrix[column][c] /= divisor }
            for r in 0..<3 where r != column {
                let factor = matrix[r][column]
                for c in column..<4 { matrix[r][c] -= factor*matrix[column][c] }
            }
        }
        let a = matrix[0][3], b = matrix[1][3], c = matrix[2][3]
        func value(_ y:Double) -> Double { let t=(y-center)/scale; return a+b*t+c*t*t }
        let residual = samples.map { abs(value($0.point.y)-$0.point.x) }.max() ?? 1
        let points = (0..<12).map { index -> LanePoint in let y=low+scale*Double(index)/11; return LanePoint(x:value(y),y:y) }
        guard points.allSatisfy({ $0.x.isFinite && (0...1).contains($0.x) }) else { return nil }
        return Model(points:points,maximumResidual:residual,maximumSlope:max(abs(b-c),abs(b+c))/scale,curvature:abs(2*c)/(scale*scale))
    }
    private func paintedSegments(_ samples: [Sample]) -> [[LanePoint]] {
        var segments: [[LanePoint]] = [], current: [LanePoint] = []
        var previousRow: Int? = nil
        for sample in samples {
            if sample.cue != .paint || previousRow.map({ sample.row-$0>1 }) == true {
                if !current.isEmpty { segments.append(current.reversed()); current=[] }
            }
            if sample.cue == .paint { current.append(sample.point) }
            previousRow=sample.row
        }
        if !current.isEmpty { segments.append(current.reversed()) }
        return segments.reversed()
    }
    private func joinFragments(_ lhs:[Sample], _ rhs:[Sample], width:Int, reject:(String)->Void) -> [Sample]? {
        guard lhs.count >= 3, rhs.count >= 3,
              lhs.filter({ $0.cue == .paint }).count*5 >= lhs.count*4,
              rhs.filter({ $0.cue == .paint }).count*5 >= rhs.count*4 else { return nil }
        let near:[Sample], far:[Sample]
        if lhs.last!.row < rhs.first!.row { near=lhs; far=rhs }
        else if rhs.last!.row < lhs.first!.row { near=rhs; far=lhs }
        else { return nil }
        let gap=far.first!.row-near.last!.row
        guard gap > 1 && gap <= 9 else { return nil }
        let a=near[max(0,near.count-3)], b=near.last!, c=far.first!, d=far[min(2,far.count-1)]
        let slopeNear=(b.point.x-a.point.x)/(b.point.y-a.point.y)
        let slopeFar=(d.point.x-c.point.x)/(d.point.y-c.point.y)
        let expected=b.point.x+slopeNear*(c.point.y-b.point.y)
        let widthNear=Double(near.reduce(0) { $0+$1.stripeWidth })/Double(near.count)
        let widthFar=Double(far.reduce(0) { $0+$1.stripeWidth })/Double(far.count)
        guard abs(slopeNear-slopeFar)<=0.65 else { reject("fragment_tangent"); return nil }
        guard abs(expected-c.point.x)<=0.035 else { reject("fragment_endpoint"); return nil }
        guard max(widthNear,widthFar)<=min(widthNear,widthFar)*2.5 else { reject("fragment_width"); return nil }
        let joined=near+far
        guard validatedModel(joined,residualLimit:max(0.012,2/Double(width-1)),reject:reject) != nil else { return nil }
        return joined
    }

    private func validatedModel(_ samples:[Sample], residualLimit:Double, reject:(String)->Void) -> Model? {
        guard let model=fitModel(samples) else { reject("fragment_fit_invalid"); return nil }
        var accepted=true
        if model.maximumResidual>residualLimit { reject("fragment_fit_residual"); accepted=false }
        if model.maximumSlope>1.8 { reject("fragment_fit_slope"); accepted=false }
        if model.curvature>7 { reject("fragment_fit_curvature"); accepted=false }
        return accepted ? model : nil
    }

    private func xAt(_ points: [LanePoint], _ y: Double) -> Double {
        let index = max(1, points.firstIndex { $0.y >= y } ?? points.count - 1)
        let a = points[index - 1], b = points[index]
        return a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y)
    }
}

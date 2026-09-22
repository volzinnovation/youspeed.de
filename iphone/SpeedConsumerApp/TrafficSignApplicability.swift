import Foundation

// Additive v1 evidence. Never serialize these fields into frozen recognition v1/v2.
struct TSRApplicabilityScope: Codable, Equatable, Sendable {
    let sessionId: String
    let bundleId: String
    let cameraGeometryId: String
    let generation: UInt64
    let contextGeneration: UInt64
    let traversalEpoch: UInt64
}

struct TSRApplicabilityBox: Codable, Equatable, Sendable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    var centerX: Double { x + width / 2 }
    var centerY: Double { y + height / 2 }
    var scale: Double { sqrt(width * height) }
    var valid: Bool {
        [x, y, width, height].allSatisfy(\.isFinite) && x >= 0 && y >= 0
            && width > 0 && height > 0 && x + width <= 1.000001 && y + height <= 1.000001
    }
}

struct TSRApplicabilityCandidate: Codable, Equatable, Sendable {
    let candidateId: String
    let semanticKey: String
    let box: TSRApplicabilityBox
    let rawScore: Double
    let recognitionEligible: Bool
    let assemblyId: String?
    var recognitionScore: Double? = nil
    var calibratedConfidence: Double? = nil
}

struct TSRApplicabilityCorridor: Codable, Equatable, Sendable {
    let wayId: String
    let headingDeg: Double?
    let distanceM: Double?
    let roadClass: String?
    let endpointLinked: Bool
    let turnAngleDeg: Double?
}

struct TrafficSignMapContextSnapshot: Codable, Equatable, Sendable {
    let snapshotId: String
    let capturedAtMs: Double
    let scope: TSRApplicabilityScope
    let wayId: String?
    let horizontalAccuracyM: Double?
    let courseAccuracyDeg: Double?
    let courseDeg: Double?
    let localTangentDeg: Double?
    let matchedStable: Bool
    let roadClass: String?
    let hypotheses: [TSRApplicabilityCorridor]
    let branches: [TSRApplicabilityCorridor]
    let capabilities: [String]
    let cameraHorizontalFovDeg: Double?
    let cameraYawDeg: Double?
    var postedSpeedKmh: Int? = nil
}

struct TSRFrameCandidateBatch: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let frameId: String
    let capturedAtMs: Double
    let scope: TSRApplicabilityScope
    let status: String
    let candidates: [TSRApplicabilityCandidate]
    let truncated: Bool
    let rawCandidateCount: Int
    let modelId: String
    let preprocessingId: String
    let road: TrafficSignMapContextSnapshot?
}

struct TSRTrackSample: Codable, Equatable, Sendable {
    let frameId: String
    let capturedAtMs: Double
    let candidate: TSRApplicabilityCandidate
}

struct TSRPhysicalTrackSnapshot: Codable, Equatable, Sendable {
    let trackId: String
    let scope: TSRApplicabilityScope
    var samples: [TSRTrackSample]
    var visibility: String
    var associationAmbiguous: Bool
}

struct TSRApplicabilityDecision: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let policyVersion: String
    let configHash: String
    let frameId: String
    let trackId: String
    let scope: TSRApplicabilityScope
    let roadSnapshotId: String?
    let classification: String
    let reasons: [String]
    let evidence: [String]
    let imageSupport: Double // Soft support, NOT probability or recognition confidence.
    let displayEligible: Bool
    let immediateEligible: Bool
    let passageEligible: Bool
}

struct TSRApplicabilityDiagnostic: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let batch: TSRFrameCandidateBatch
    let tracks: [TSRPhysicalTrackSnapshot]
    let decisions: [TSRApplicabilityDecision]
}

// Generated contract values are checked against shared/tsr/applicability/policy-v1.json.
struct TSRApplicabilityConfiguration: Sendable {
    static let policyVersion = "applicability-heuristic-v1"
    static let configHash = "6278259f59578238acabe7df1abe53f8cd580115b20c6036ef3f89657e97ca11"
    static let defaultMode = "shadow"
    static let maxCandidates = 32
    static let maxTracks = 24
    static let maxHistory = 12
    static let maxTrackAgeMs = 2500.0
    static let maxContextAgeMs = 1500.0
    static let maxGpsAccuracyM = 20.0
    static let maxCourseAccuracyDeg = 25.0
    static let minObservations = 2
    static let associationDistance = 0.18
    static let associationGrowth = 0.35
    static let ambiguityMargin = 0.04
    static let maxScaleRatio = 3.0
    static let minApproachRatio = 1.08
    static let maxLateralSpeed = 0.9
    static let corridorHalfAngleDeg = 35.0
    static let branchMarginDeg = 12.0
    static let maxBranches = 8
    static let maxHypotheses = 8
    static let maxJunctionDistanceM = 100.0
    static let motorwayExitPolicyVersion = "motorway-exit-guard-v1"
    static let motorwayExitMinPostedSpeed = 100
    static let motorwayExitMinCandidateSpeed = 30
    static let motorwayExitMaxCandidateSpeed = 90
    static let motorwayExitMaxJunctionDistanceM = 350.0
    static let motorwayExitMaxHeadingDeltaDeg = 60.0
    static let motorwayExitMinSignCenterX = 0.6
    static let motorwayExitPairedRepeatMaxCenterX = 0.5
}

/// Bounded, deterministic one-to-one physical association before semantic fusion.
/// A failed/skipped/withheld frame never becomes an analyzed absence.
struct TSRPhysicalSignTracker: Sendable {
    private(set) var tracks: [TSRPhysicalTrackSnapshot] = []
    private var scope: TSRApplicabilityScope?
    private var lastTimestamp = -Double.infinity
    private var recentFrames: [String] = []
    private var nextID = 1

    mutating func reset() {
        tracks = []; scope = nil; lastTimestamp = -.infinity; recentFrames = []; nextID = 1
    }

    mutating func ingest(_ batch: TSRFrameCandidateBatch) -> [TSRPhysicalTrackSnapshot] {
        if scope != batch.scope { reset(); scope = batch.scope }
        guard batch.capturedAtMs.isFinite, batch.capturedAtMs > lastTimestamp,
              !recentFrames.contains(batch.frameId) else { return tracks }
        lastTimestamp = batch.capturedAtMs
        recentFrames.append(batch.frameId)
        recentFrames = Array(recentFrames.suffix(64))
        tracks.removeAll { batch.capturedAtMs - ($0.samples.last?.capturedAtMs ?? 0) > TSRApplicabilityConfiguration.maxTrackAgeMs }
        guard batch.status == "analyzed" else {
            for i in tracks.indices { tracks[i].visibility = "uncertain" }
            return tracks
        }
        let candidates = Array(batch.candidates.filter { $0.box.valid && $0.rawScore.isFinite }
            .sorted { $0.candidateId < $1.candidateId }.prefix(TSRApplicabilityConfiguration.maxCandidates))
        struct Edge { let cost: Double; let track: Int; let candidate: Int }
        var edges: [Edge] = []
        for (ti, track) in tracks.enumerated() {
            guard let last = track.samples.last else { continue }
            let dt = (batch.capturedAtMs - last.capturedAtMs) / 1000
            guard dt > 0 else { continue }
            var vx = 0.0, vy = 0.0
            if track.samples.count >= 2 {
                let previous = track.samples[track.samples.count - 2]
                let elapsed = (last.capturedAtMs - previous.capturedAtMs) / 1000
                if elapsed > 0 {
                    vx = max(-0.9, min(0.9, (last.candidate.box.centerX - previous.candidate.box.centerX) / elapsed))
                    vy = max(-0.9, min(0.9, (last.candidate.box.centerY - previous.candidate.box.centerY) / elapsed))
                }
            }
            for (ci, candidate) in candidates.enumerated() {
                let ratio = candidate.box.scale / last.candidate.box.scale
                guard ratio >= 1 / TSRApplicabilityConfiguration.maxScaleRatio && ratio <= TSRApplicabilityConfiguration.maxScaleRatio else { continue }
                let distance = hypot(candidate.box.centerX - last.candidate.box.centerX - vx * dt,
                                     candidate.box.centerY - last.candidate.box.centerY - vy * dt)
                let bound = min(0.55, TSRApplicabilityConfiguration.associationDistance + TSRApplicabilityConfiguration.associationGrowth * dt)
                guard distance <= bound else { continue }
                let semanticPenalty = candidate.semanticKey == last.candidate.semanticKey ? 0.0 : 0.08
                edges.append(Edge(cost: distance + 0.05 * abs(log(ratio)) + semanticPenalty, track: ti, candidate: ci))
            }
        }
        edges.sort {
            if $0.cost != $1.cost { return $0.cost < $1.cost }
            if $0.track != $1.track { return $0.track < $1.track }
            return $0.candidate < $1.candidate
        }
        var usedTracks = Set<Int>(), usedCandidates = Set<Int>(), ambiguousCandidates = Set<Int>()
        for i in tracks.indices {
            tracks[i].visibility = batch.truncated ? "uncertain" : "absent"
            tracks[i].associationAmbiguous = false
        }
        for edge in edges {
            guard !usedTracks.contains(edge.track), !usedCandidates.contains(edge.candidate) else { continue }
            // Near-equal assignment alternatives are withheld; deterministic tie ordering is not evidence.
            let ambiguous = edges.contains {
                ($0.track == edge.track && $0.candidate != edge.candidate
                    || $0.candidate == edge.candidate && $0.track != edge.track)
                    && abs($0.cost - edge.cost) < TSRApplicabilityConfiguration.ambiguityMargin
            }
            if ambiguous {
                ambiguousCandidates.insert(edge.candidate)
                tracks[edge.track].visibility = "uncertain"
                tracks[edge.track].associationAmbiguous = true
                continue
            }
            usedTracks.insert(edge.track); usedCandidates.insert(edge.candidate)
            tracks[edge.track].samples.append(TSRTrackSample(frameId: batch.frameId, capturedAtMs: batch.capturedAtMs, candidate: candidates[edge.candidate]))
            tracks[edge.track].samples = Array(tracks[edge.track].samples.filter { batch.capturedAtMs - $0.capturedAtMs <= TSRApplicabilityConfiguration.maxTrackAgeMs }.suffix(TSRApplicabilityConfiguration.maxHistory))
            tracks[edge.track].visibility = "observed"
        }
        for (ci, candidate) in candidates.enumerated() where !usedCandidates.contains(ci) && !ambiguousCandidates.contains(ci) {
            guard tracks.count < TSRApplicabilityConfiguration.maxTracks else { break }
            tracks.append(TSRPhysicalTrackSnapshot(trackId: "track-\(nextID)", scope: batch.scope,
                samples: [TSRTrackSample(frameId: batch.frameId, capturedAtMs: batch.capturedAtMs, candidate: candidate)],
                visibility: "observed", associationAmbiguous: false))
            nextID += 1
        }
        return tracks
    }
}

enum TSRApplicabilityPolicy {
    static func signedAngle(_ angle: Double) -> Double {
        var a = angle.truncatingRemainder(dividingBy: 360)
        if a >= 180 { a -= 360 }; if a < -180 { a += 360 }; return a
    }

    static func evaluate(_ track: TSRPhysicalTrackSnapshot, batch: TSRFrameCandidateBatch) -> TSRApplicabilityDecision {
        var reasons: [String] = [], evidence: [String] = []
        var classification = "UNKNOWN", support = 0.0
        let road = batch.road
        func result() -> TSRApplicabilityDecision {
            let eligible = classification == "LIKELY_EGO_CORRIDOR"
            return TSRApplicabilityDecision(schemaVersion: 1, policyVersion: TSRApplicabilityConfiguration.policyVersion,
                configHash: TSRApplicabilityConfiguration.configHash, frameId: batch.frameId, trackId: track.trackId,
                scope: batch.scope, roadSnapshotId: road?.snapshotId, classification: classification,
                reasons: reasons, evidence: evidence, imageSupport: support,
                displayEligible: eligible, immediateEligible: eligible, passageEligible: eligible)
        }
        guard track.scope == batch.scope, batch.status == "analyzed", !batch.truncated,
              track.visibility == "observed", !track.associationAmbiguous,
              let last = track.samples.last, last.frameId == batch.frameId,
              last.candidate.box.valid, last.candidate.recognitionEligible else {
            reasons.append("unqualified_observation"); return result()
        }
        guard let road, road.scope == batch.scope, road.wayId != nil else {
            reasons.append("missing_road_context"); return result()
        }
        let age = batch.capturedAtMs - road.capturedAtMs
        guard age >= 0 && age <= TSRApplicabilityConfiguration.maxContextAgeMs else {
            reasons.append("stale_road_context"); return result()
        }
        guard road.matchedStable, let accuracy = road.horizontalAccuracyM, accuracy.isFinite, accuracy >= 0, accuracy <= TSRApplicabilityConfiguration.maxGpsAccuracyM,
              let courseAccuracy = road.courseAccuracyDeg, courseAccuracy.isFinite, courseAccuracy >= 0, courseAccuracy <= TSRApplicabilityConfiguration.maxCourseAccuracyDeg,
              let course = road.courseDeg, course.isFinite, let tangent = road.localTangentDeg, tangent.isFinite else {
            reasons.append("unreliable_road_context"); return result()
        }
        evidence.append("local_road_geometry")
        guard let fov = road.cameraHorizontalFovDeg, fov.isFinite, fov > 10 && fov < 170,
              let yaw = road.cameraYawDeg, yaw.isFinite else {
            reasons.append("camera_calibration_unavailable"); return result()
        }
        evidence.append("calibrated_image_bearing")
        let bearing = atan((last.candidate.box.centerX * 2 - 1) * tan(fov * .pi / 360)) * 180 / .pi + yaw
        var egoAngle = signedAngle(tangent - course)
        // Geometry is undirected. Orient its tangent to observed motion, never infer legal oneway.
        if abs(egoAngle) > 90 { egoAngle = signedAngle(egoAngle + 180) }
        let residual = abs(signedAngle(bearing - egoAngle))
        support = max(0, 1 - residual / 70)
        let nearbyBranches = road.branches.filter { ($0.distanceM ?? .infinity) <= TSRApplicabilityConfiguration.maxJunctionDistanceM }
        guard road.capabilities.contains("endpoint_links"), road.capabilities.contains("local_tangent"),
              !road.capabilities.contains("context_truncated") else {
            reasons.append("missing_topology_capability"); return result()
        }
        let branchIDs = Set(nearbyBranches.map(\.wayId))
        let alternatives = nearbyBranches + road.hypotheses.filter { $0.wayId != road.wayId && !branchIDs.contains($0.wayId) }
        for alternative in alternatives {
            guard let heading = alternative.headingDeg, heading.isFinite else {
                reasons.append("unknown_competing_corridor"); return result()
            }
            var angle = signedAngle(heading - course)
            if !alternative.endpointLinked && abs(angle) > 90 { angle = signedAngle(angle + 180) }
            let alternativeResidual = abs(signedAngle(bearing - angle))
            if alternativeResidual + TSRApplicabilityConfiguration.branchMarginDeg < residual && alternative.endpointLinked {
                classification = "LIKELY_BRANCH"; reasons.append("branch_bearing_better_supported"); return result()
            }
            if alternativeResidual <= TSRApplicabilityConfiguration.corridorHalfAngleDeg || abs(alternativeResidual - residual) < TSRApplicabilityConfiguration.branchMarginDeg {
                reasons.append("competing_corridors"); return result()
            }
        }
        evidence.append("bounded_corridor_comparison")
        guard track.samples.count >= TSRApplicabilityConfiguration.minObservations, let first = track.samples.first else {
            reasons.append("insufficient_independent_observations"); return result()
        }
        guard track.samples.allSatisfy({ $0.candidate.semanticKey == last.candidate.semanticKey }) else {
            reasons.append("semantic_disagreement"); return result()
        }
        let elapsed = (last.capturedAtMs - first.capturedAtMs) / 1000
        guard elapsed > 0, last.candidate.box.scale / first.candidate.box.scale >= TSRApplicabilityConfiguration.minApproachRatio,
              abs(last.candidate.box.centerX - first.candidate.box.centerX) / elapsed <= TSRApplicabilityConfiguration.maxLateralSpeed else {
            reasons.append("insufficient_coherent_approach"); return result()
        }
        evidence.append("independent_approach")
        guard residual <= TSRApplicabilityConfiguration.corridorHalfAngleDeg else { reasons.append("outside_supported_corridor"); return result() }
        classification = "LIKELY_EGO_CORRIDOR"
        reasons.append("coherent_approach_unique_corridor")
        return result()
    }
}

/// Rechecked at serialized authority boundaries. Missing legacy evidence fails closed in enforcement.
enum TSRApplicabilityAuthority {
    static func allows(_ decision: TSRApplicabilityDecision?, scope: TSRApplicabilityScope, frameId: String,
                       trackId: String, sink: String, mode: String = TSRApplicabilityConfiguration.defaultMode) -> Bool {
        if decision?.reasons.contains(TSRMotorwayExitPolicy.reason) == true { return false }
        if mode == "shadow" { return true }
        guard mode == "enforce", let decision, decision.schemaVersion == 1, decision.scope == scope, decision.frameId == frameId,
              decision.trackId == trackId, decision.policyVersion == TSRApplicabilityConfiguration.policyVersion,
              decision.configHash == TSRApplicabilityConfiguration.configHash,
              decision.classification == "LIKELY_EGO_CORRIDOR" else { return false }
        switch sink {
        case "display": return decision.displayEligible
        case "immediate": return decision.immediateEligible
        case "passage": return decision.passageEligible
        default: return false
        }
    }
}

/// A bounded projection of data already loaded by the location matcher. No per-frame SQL.
struct TSRMapGeometry: Codable, Equatable, Sendable {
    let wayId: String?
    let localTangentDeg: Double?
    let roadClass: String?
    let hypotheses: [TSRApplicabilityCorridor]
    let branches: [TSRApplicabilityCorridor]
    let capabilities: [String]
    var postedSpeedKmh: Int? = nil

    func snapshot(scope: TSRApplicabilityScope, fixTimeMs: Double, accuracyM: Double?, courseDeg: Double?, courseAccuracyDeg: Double?, stable: Bool) -> TrafficSignMapContextSnapshot {
        TrafficSignMapContextSnapshot(snapshotId: "\(scope.bundleId):\(scope.traversalEpoch):\(fixTimeMs)",
            capturedAtMs: fixTimeMs, scope: scope, wayId: wayId, horizontalAccuracyM: accuracyM,
            courseAccuracyDeg: courseAccuracyDeg, courseDeg: courseDeg, localTangentDeg: localTangentDeg,
            matchedStable: stable, roadClass: roadClass, hypotheses: hypotheses, branches: branches,
            capabilities: capabilities, cameraHorizontalFovDeg: nil, cameraYawDeg: nil, postedSpeedKmh: postedSpeedKmh)
    }
}

struct TSRMapFix: Equatable, Sendable {
    let geometry: TSRMapGeometry
    let timestampMs: Double
    let accuracyM: Double?
    let courseDeg: Double?
    let courseAccuracyDeg: Double?
    let stable: Bool
    func snapshot(scope: TSRApplicabilityScope) -> TrafficSignMapContextSnapshot {
        geometry.snapshot(scope: scope, fixTimeMs: timestampMs, accuracyM: accuracyM,
            courseDeg: courseDeg, courseAccuracyDeg: courseAccuracyDeg, stable: stable)
    }
}

/// A narrow, active ambiguity guard for deceleration signs beside a mapped exit.
/// It does not claim to read an arrow plate or establish legal lane applicability.
/// Mainline repeats and signs after a stable ramp match remain eligible.
enum TSRMotorwayExitPolicy {
    static let reason = "motorway_exit_ambiguous_speed"
    static func withheldCandidates(_ batch: TSRFrameCandidateBatch) -> Set<String> {
        guard batch.status == "analyzed", let road = batch.road, road.scope == batch.scope,
              road.roadClass == "motorway", road.matchedStable,
              let posted = road.postedSpeedKmh, posted >= TSRApplicabilityConfiguration.motorwayExitMinPostedSpeed,
              (0...1500).contains(batch.capturedAtMs - road.capturedAtMs),
              let accuracy = road.horizontalAccuracyM, (0...20).contains(accuracy),
              let course = road.courseDeg, (0..<360).contains(course),
              let courseAccuracy = road.courseAccuracyDeg, (0...25).contains(courseAccuracy),
              road.branches.contains(where: { branch in
                  branch.endpointLinked && branch.roadClass == "motorway_link"
                      && branch.distanceM.map { (0...TSRApplicabilityConfiguration.motorwayExitMaxJunctionDistanceM).contains($0) } == true
                      && branch.headingDeg.map { abs(TSRApplicabilityPolicy.signedAngle($0 - course)) <= TSRApplicabilityConfiguration.motorwayExitMaxHeadingDeltaDeg } == true
              }) else { return [] }
        return Set(batch.candidates.filter { candidate in
            let components = candidate.semanticKey.split(separator: ":")
            guard components.first == "maximum_speed", components.count >= 2,
                  let speed = Int(components[1]), (TSRApplicabilityConfiguration.motorwayExitMinCandidateSpeed...TSRApplicabilityConfiguration.motorwayExitMaxCandidateSpeed).contains(speed), speed < posted,
                  candidate.recognitionEligible, candidate.box.valid, candidate.box.centerX >= TSRApplicabilityConfiguration.motorwayExitMinSignCenterX else { return false }
            // A matching left/central repeat is positive evidence of a mainline
            // restriction (including roadworks), despite a nearby exit.
            return !batch.candidates.contains { other in
                other.candidateId != candidate.candidateId && other.recognitionEligible && other.box.valid
                    && other.semanticKey == candidate.semanticKey && other.box.centerX < TSRApplicabilityConfiguration.motorwayExitPairedRepeatMaxCenterX
            }
        }.map(\.candidateId))
    }
}

struct TSRApplicabilitySession: Sendable {
    private var tracker = TSRPhysicalSignTracker()
    private var decisionsByTrack: [String: TSRApplicabilityDecision] = [:]
    private(set) var diagnostic: TSRApplicabilityDiagnostic?
    mutating func reset() { tracker.reset(); decisionsByTrack = [:]; diagnostic = nil }
    mutating func evaluate(_ batch: TSRFrameCandidateBatch) -> TSRApplicabilityDiagnostic {
        let tracks = tracker.ingest(batch)
        let withheld = TSRMotorwayExitPolicy.withheldCandidates(batch)
        let decisions = tracks.map { track in
            let decision = TSRApplicabilityPolicy.evaluate(track, batch: batch)
            guard let sample = track.samples.last, sample.frameId == batch.frameId,
                  withheld.contains(sample.candidate.candidateId) else { return decision }
            return TSRApplicabilityDecision(schemaVersion: decision.schemaVersion, policyVersion: decision.policyVersion,
                configHash: decision.configHash, frameId: decision.frameId, trackId: decision.trackId,
                scope: decision.scope, roadSnapshotId: decision.roadSnapshotId, classification: "UNKNOWN",
                reasons: [TSRMotorwayExitPolicy.reason], evidence: ["connected_motorway_link", "mainline_match", "right_side_lower_speed"],
                imageSupport: decision.imageSupport, displayEligible: false, immediateEligible: false, passageEligible: false)
        }
        decisionsByTrack = decisionsByTrack.filter { key, value in tracks.contains { $0.trackId == key && $0.scope == value.scope } }
        for (track, decision) in zip(tracks, decisions) where track.visibility == "observed" {
            decisionsByTrack[track.trackId] = decision
        }
        let result = TSRApplicabilityDiagnostic(schemaVersion: 1, batch: batch, tracks: tracks, decisions: decisions)
        diagnostic = result
        return result
    }
    func passageDecision(trackId: String) -> TSRApplicabilityDecision? { decisionsByTrack[trackId] }
    func canConsumePassage(activeTrackId: String?, selectedTrackId: String?, mode: String) -> Bool {
        if diagnostic?.decisions.contains(where: { $0.reasons.contains(TSRMotorwayExitPolicy.reason) }) == true { return false }
        if mode == "shadow" { return true }
        guard mode == "enforce", let diagnostic, diagnostic.batch.status == "analyzed", !diagnostic.batch.truncated else { return false }
        guard let activeTrackId else { return selectedTrackId != nil }
        guard let track = diagnostic.tracks.first(where: { $0.trackId == activeTrackId }) else { return false }
        if track.visibility == "observed" { return selectedTrackId == activeTrackId && decisionsByTrack[activeTrackId]?.passageEligible == true }
        return track.visibility == "absent" && decisionsByTrack[activeTrackId]?.passageEligible == true
    }
}

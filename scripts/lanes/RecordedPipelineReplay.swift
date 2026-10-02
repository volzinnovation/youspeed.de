import Foundation
import CryptoKit

// Offline only: links the production RoadPathSession, including its filter,
// detector, temporal tracker, presentation gate and operation/evidence-age guards.
private struct ReplayFrame: Decodable {
    let id, sequenceId, grayPath, graySha256: String
    let width, height, decodedWidth, decodedHeight: Int
    let time: Double
    let source: String?
    let sourceFrameId: String?
    let calibration: RoadPathCalibration?
    let visualCalibration: VisualRoadCalibration?
    let orientationKey: String?
    let locationFixes: [ReplayLocation]?
}
private struct ReplayLocation: Decodable {
    let time, latitude, longitude, course, speed, accuracy, courseAccuracy: Double
}
private struct ReplayManifest: Decodable {
    let schemaVersion: Int
    let variant: String
    let previewMode: Bool?
    let useSearchBands, groupFragments, fragmentTracking, retainTentativeIdentity, jointSelection: Bool?
    let frames: [ReplayFrame]
}
private struct ReplayFailure: Error, CustomStringConvertible { let description: String }

@main struct RecordedPipelineReplay {
    static func main() throws {
        guard CommandLine.arguments.count == 3 else {
            throw ReplayFailure(description: "usage: pipeline-replay normalized-manifest.json output.ndjson")
        }
        let manifestURL = URL(fileURLWithPath: CommandLine.arguments[1])
        let manifest = try JSONDecoder().decode(ReplayManifest.self, from: Data(contentsOf: manifestURL))
        guard manifest.schemaVersion == 1 else { throw ReplayFailure(description: "unsupported schema") }
        let destination = URL(fileURLWithPath: CommandLine.arguments[2])
        guard !FileManager.default.fileExists(atPath: destination.path),
              FileManager.default.createFile(atPath: destination.path, contents: nil) else {
            throw ReplayFailure(description: "output already exists or cannot be created")
        }
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        func makeSession() -> RoadPathSession {
#if LANE_SELECTION_OPTIONS
            return RoadPathSession(previewMode: manifest.previewMode ?? false,
                detectionOptions: RoadBoundaryDetectionOptions(useSearchBands: manifest.useSearchBands ?? false,
                    groupFragments: manifest.groupFragments ?? false), fragmentTracking: manifest.fragmentTracking ?? false,
                retainTentativeIdentity: manifest.retainTentativeIdentity ?? false,
                jointSelection: manifest.jointSelection ?? false)
#elseif LANE_FRAGMENT_OPTIONS
            return RoadPathSession(previewMode: manifest.previewMode ?? false,
                detectionOptions: RoadBoundaryDetectionOptions(useSearchBands: manifest.useSearchBands ?? false,
                    groupFragments: manifest.groupFragments ?? false), fragmentTracking: manifest.fragmentTracking ?? false)
#else
            return RoadPathSession(previewMode: manifest.previewMode ?? false)
#endif
        }
        var session = makeSession(), sequence: String?
        var previousTime = -Double.infinity
        var seen = Set<String>()
        for input in manifest.frames {
            guard seen.insert(input.id).inserted, !input.id.isEmpty, !input.sequenceId.isEmpty,
                  (64...384).contains(input.width), (64...216).contains(input.height), input.time.isFinite else {
                throw ReplayFailure(description: "invalid or duplicate frame: \(input.id)")
            }
            if sequence != input.sequenceId {
                session = makeSession()
                sequence = input.sequenceId
                previousTime = -Double.infinity
            }
            guard input.time > previousTime else {
                throw ReplayFailure(description: "timestamps must increase within a sequence: \(input.id)")
            }
            previousTime = input.time
            let bytes = try Data(contentsOf: URL(fileURLWithPath: input.grayPath))
            guard bytes.count == input.width * input.height else {
                throw ReplayFailure(description: "gray byte count differs from width*height: \(input.id)")
            }
            let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
            guard digest == input.graySha256 else {
                throw ReplayFailure(description: "gray hash changed after manifest validation: \(input.id)")
            }
            let gray = [UInt8](bytes)
            let start = ProcessInfo.processInfo.systemUptime
            // Encoded PTS is a valid relative ordering clock, not a UTC mapping.
            // Optional metadata is explicit and causal; no sign observations or road context are invented.
            for fix in input.locationFixes ?? [] {
                guard fix.time <= input.time else { throw ReplayFailure(description: "noncausal location: \(input.id)") }
                session.recordLocation(time: fix.time, latitude: fix.latitude, longitude: fix.longitude,
                    course: fix.course, speed: fix.speed, accuracy: fix.accuracy, courseAccuracy: fix.courseAccuracy)
            }
            let geometryId = "encoded:\(input.sequenceId):\(input.decodedWidth)x\(input.decodedHeight)"
            let frame = RoadPathCameraFrame(grayscale: gray, width: input.width, height: input.height,
                capturedAtSeconds: input.time, geometryId: geometryId, calibration: input.calibration, clockKnown: true,
                preprocessingMs: 0, startedAt: start, rawWidth: input.decodedWidth, rawHeight: input.decodedHeight,
                sourceTimestampSeconds: input.time, visualCalibration: input.visualCalibration, orientationKey: input.orientationKey ?? "")
            let scope = TSRApplicabilityScope(sessionId: input.sequenceId, bundleId: "offline-video",
                cameraGeometryId: geometryId, generation: 1, contextGeneration: 1, traversalEpoch: 1)
            let prepared = session.prepare(frame: frame, frameId: input.id, scope: scope)
            let diagnostic = TSRApplicabilityDiagnostic(schemaVersion: 1,
                batch: TSRFrameCandidateBatch(schemaVersion: 1, frameId: input.id, capturedAtMs: input.time * 1000,
                    scope: scope, status: "analyzed", candidates: [], truncated: false, rawCandidateCount: 0,
                    modelId: "none", preprocessingId: "none", road: nil), tracks: [], decisions: [])
            guard let diagnosticText = session.evaluate(prepared: prepared, diagnostic: diagnostic),
                  let diagnosticData = diagnosticText.data(using: .utf8),
                  let evaluated = try JSONSerialization.jsonObject(with: diagnosticData) as? [String: Any] else {
                throw ReplayFailure(description: "session evaluation failed: \(input.id)")
            }
            let componentMs = (ProcessInfo.processInfo.systemUptime - start) * 1000
            let overlay = session.overlay()
            let visibleIndices = Set(prepared.presentation.visibleBoundaryIndices)
            let visibleItems = prepared.presentation.items.filter {
                $0.boundaryIndex.map { visibleIndices.contains($0) } == true
            }
            let published = evaluated["overlayPublished"] as? Bool == true
            // Overlay geometry follows selected indices (left/right), which need
            // not match presentation.items order. Keep identity/geometry paired.
            let idsByIndex = Dictionary(uniqueKeysWithValues: visibleItems.compactMap { item in
                item.boundaryIndex.map { ($0, item.trackId) }
            })
            let visibleIDs = published ? prepared.presentation.visibleBoundaryIndices.compactMap { idsByIndex[$0] } : []
            func boundaries(_ values: [RoadBoundaryEvidence]) -> [[String: Any]] {
                values.map { boundary in
                    var result: [String: Any] = [
                    "points": boundary.points.map { [$0.x, $0.y] }, "cue": boundary.cue.rawValue,
                    "confidence": boundary.confidence, "provenance": boundary.provenance.rawValue,
                    "supportRows": boundary.supportRows, "trackedAnchorCount": boundary.trackedAnchorCount,
                    "lastFreshTimestampSeconds": boundary.lastFreshTimestampSeconds as Any? ?? NSNull(),
                    "evidenceAgeSeconds": boundary.evidenceAgeSeconds,
                ]
#if LANE_FRAGMENT_OPTIONS
                    result["observedSegments"] = boundary.observedSegments.map { $0.map { [$0.x, $0.y] } }
                    result["geometryConfidence"] = boundary.geometryConfidence as Any? ?? NSNull()
                    result["paintOccupancy"] = boundary.paintOccupancy as Any? ?? NSNull()
#endif
                    return result
                }
            }
            let raw = boundaries(prepared.geometry.boundaries)
            let visible = boundaries(overlay?.boundaries ?? [])
            let corridors: [[String: Any]] = prepared.geometry.corridors.map {
                ["leftBoundaryIndex": $0.leftBoundaryIndex, "rightBoundaryIndex": $0.rightBoundaryIndex,
                 "confidence": $0.confidence]
            }
            var row: [String: Any] = [
                "schemaVersion": 1, "id": input.id, "sourceFrameId": input.sourceFrameId as Any? ?? NSNull(),
                "sequenceId": input.sequenceId, "variant": manifest.variant,
                "source": input.source as Any? ?? NSNull(), "sourcePtsSeconds": input.time, "time": input.time,
                "width": input.width, "height": input.height, "decodedWidth": input.decodedWidth,
                "decodedHeight": input.decodedHeight, "inputSha256": digest, "rawSha256": digest,
                "rawBoundaries": raw, "confirmedBoundaries": visible, "visibleIDs": visibleIDs,
                "visibleBoundaryIndices": published ? prepared.presentation.visibleBoundaryIndices : [],
                "road": ["boundaries": raw, "corridors": corridors, "budgetExceeded": prepared.geometry.budgetExceeded,
                         "operationCount": prepared.geometry.operationCount],
                "visibleRoad": ["boundaries": visible],
                "lanePresentation": prepared.presentation.diagnosticFields,
                "laneMotionHint": prepared.motionHint.diagnosticFields,
                "geometryBudgetExceeded": prepared.geometry.budgetExceeded,
                "temporalOperationCount": prepared.geometry.temporalOperationCount,
                "temporalResetReason": prepared.geometry.temporalResetReason as Any? ?? NSNull(),
                "overlayPublished": published,
                "overlaySuppressionReason": evaluated["overlayPublicationSuppressionReason"] ?? NSNull(),
                "deadlineExceeded": evaluated["deadlineExceeded"] ?? false,
                "filterIdentifier": RoadBoundaryPreprocessor.identifier,
                "experimentDiagnostics": evaluated["lightingExperiment"] ?? NSNull(),
                "filterMs": prepared.filterMs, "geometryMs": prepared.geometryMs,
                "preparationMs": prepared.preparationMs, "componentMs": componentMs,
                "totalAddedProcessingMs": evaluated["totalAddedProcessingMs"] ?? NSNull(),
                "sourceClock": "encoded relative PTS; no verified UTC mapping",
                "gpsSupplied": !(input.locationFixes ?? []).isEmpty, "metricCalibrationSupplied": input.calibration != nil, "visualCalibrationSupplied": input.visualCalibration != nil,
                "executionHost": "macOS native Swift; not device performance acceptance",
                "timingScope": "production prepare/evaluate plus diagnostic parsing; excludes decode, luma sampling, file IO, hashing and output serialization",
            ]
#if LANE_FRAGMENT_OPTIONS
            row["rejectionCounts"] = prepared.geometry.rejectionCounts
            row["detectionVariant"] = prepared.geometry.detectionVariant
#endif
            row["calibrationDiagnostics"] = evaluated["lanePreparationDiagnostics"] ?? NSNull()
            var encoded = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            encoded.append(10)
            try handle.write(contentsOf: encoded)
        }
        print("Replayed \(manifest.frames.count) frames through the production native pipeline.")
    }
}

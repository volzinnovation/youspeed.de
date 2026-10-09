import Foundation
import CryptoKit

// Host adapter only. Every still gets one fresh production session. The injected
// processing clock removes wall-clock nondeterminism, not operation budgets.
private struct StillFrame: Decodable {
    let id, sequenceId, grayPath, graySha256: String
    let width, height, decodedWidth, decodedHeight: Int
    let time: Double
    let semanticScoreAdjustments: [Double]?
    let semanticSourceInputSha256: String?
}
private struct StillManifest: Decodable {
    let schemaVersion: Int
    let sessionMode: String
    let detectorTrace: Bool
    let frames: [StillFrame]
}
private struct StillError: Error { let description: String }

@main struct StillLaneReplay {
    static func main() throws {
        guard CommandLine.arguments.count == 3 else { throw StillError(description: "manifest.json output.ndjson") }
        let manifest = try JSONDecoder().decode(StillManifest.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        guard manifest.schemaVersion == 1, ["preview", "tsr"].contains(manifest.sessionMode), (1...2048).contains(manifest.frames.count) else {
            throw StillError(description: "Invalid bounded still contract")
        }
        let output = CommandLine.arguments[2]
        guard !FileManager.default.fileExists(atPath: output), FileManager.default.createFile(atPath: output, contents: nil) else { throw StillError(description: "Refuse existing output") }
        let handle = try FileHandle(forWritingTo: URL(fileURLWithPath: output)); defer { try? handle.close() }
        var seen = Set<String>()
        func boundaries(_ values: [RoadBoundaryEvidence]) -> [[String: Any]] {
            values.map { b in ["points": b.points.map { [$0.x, $0.y] }, "observedSegments": b.observedSegments.map { $0.map { [$0.x, $0.y] } },
                "confidence": b.confidence, "cue": b.cue.rawValue, "supportRows": b.supportRows, "provenance": b.provenance.rawValue,
                "lastFreshTimestampSeconds": b.lastFreshTimestampSeconds as Any? ?? NSNull(), "evidenceAgeSeconds": b.evidenceAgeSeconds,
                "trackedAnchorCount": b.trackedAnchorCount, "geometryConfidence": b.geometryConfidence as Any? ?? NSNull(),
                "paintOccupancy": b.paintOccupancy as Any? ?? NSNull()] }
        }
        for input in manifest.frames {
            guard !input.id.isEmpty, input.id.utf8.allSatisfy({ $0 < 128 }), seen.insert(input.id).inserted,
                  input.sequenceId == input.id, input.time == 0, (64...384).contains(input.width), (64...216).contains(input.height),
                  input.decodedWidth > 0, input.decodedHeight > 0 else { throw StillError(description: "Still must be one unique exposure with fresh state") }
            let data = try Data(contentsOf: URL(fileURLWithPath: input.grayPath))
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard data.count == input.width * input.height, digest == input.graySha256 else { throw StillError(description: "Input pixels/hash differ") }
            if let adjustments = input.semanticScoreAdjustments {
                guard manifest.sessionMode == "preview", input.semanticSourceInputSha256 == digest,
                      adjustments.count <= 6, adjustments.allSatisfy({ $0.isFinite && (0...0.1).contains($0) }) else {
                    throw StillError(description: "Invalid source-bound semantic adjustments")
                }
            }
            // Exactly the options used by DriveSessionViewModel app callsites.
            let session = RoadPathSession(previewMode: manifest.sessionMode == "preview", nowUptime: { 0 })
            let geometryId = "still:\(input.id):\(input.decodedWidth)x\(input.decodedHeight)"
            let frame = RoadPathCameraFrame(grayscale: [UInt8](data), width: input.width, height: input.height,
                capturedAtSeconds: 0, geometryId: geometryId, calibration: nil, clockKnown: true, preprocessingMs: 0, startedAt: 0,
                rawWidth: input.decodedWidth, rawHeight: input.decodedHeight, sourceTimestampSeconds: 0)
            let scope = TSRApplicabilityScope(sessionId: input.id, bundleId: "offline-still", cameraGeometryId: geometryId,
                generation: 1, contextGeneration: 1, traversalEpoch: 1)
            var trace: [[String: Any]] = []
            let observer: RoadBoundaryTraceObserver? = manifest.detectorTrace ? { trace.append($0) } : nil
            let prepared = session.prepare(frame: frame, frameId: input.id, scope: scope, detectorTrace: observer, semanticScoreAdjustments: input.semanticScoreAdjustments)
            guard prepared.presentation.items.allSatisfy({ $0.observationCount <= 1 }) else { throw StillError(description: "Still gained artificial temporal confirmation") }
            let diagnostic = TSRApplicabilityDiagnostic(schemaVersion: 1,
                batch: TSRFrameCandidateBatch(schemaVersion: 1, frameId: input.id, capturedAtMs: 0, scope: scope, status: "analyzed",
                    candidates: [], truncated: false, rawCandidateCount: 0, modelId: "none", preprocessingId: "none", road: nil), tracks: [], decisions: [])
            guard let text = session.evaluate(prepared: prepared, diagnostic: diagnostic), let bytes = text.data(using: .utf8),
                  let evaluated = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { throw StillError(description: "Evaluation failed") }
            let published = evaluated["overlayPublished"] as? Bool == true
            let indices = published ? prepared.presentation.visibleBoundaryIndices : []
            let visibleIDs = indices.compactMap { index in prepared.presentation.items.first { $0.boundaryIndex == index }?.trackId }
            var output: [String: Any] = ["schemaVersion": 1, "id": input.id, "sequenceId": input.id, "time": 0,
                "inputSha256": digest, "width": input.width, "height": input.height, "decodedWidth": input.decodedWidth, "decodedHeight": input.decodedHeight,
                "sessionMode": manifest.sessionMode, "freshInputObservations": 1, "rawBoundaries": boundaries(prepared.geometry.boundaries),
                "confirmedBoundaries": boundaries(session.overlay()?.boundaries ?? []), "visibleBoundaryIndices": indices, "visibleIDs": visibleIDs,
                "corridors": prepared.geometry.corridors.map { ["leftBoundaryIndex": $0.leftBoundaryIndex, "rightBoundaryIndex": $0.rightBoundaryIndex, "confidence": $0.confidence] },
                "lanePresentation": prepared.presentation.diagnosticFields,
                "calibrationDiagnostics": prepared.diagnostics.diagnosticFields.filter { $0.key != "stageMs" },
                "geometryBudgetExceeded": prepared.geometry.budgetExceeded, "operationCount": prepared.geometry.operationCount,
                "temporalOperationCount": prepared.geometry.temporalOperationCount, "temporalResetReason": prepared.geometry.temporalResetReason as Any? ?? NSNull(),
                "rejectionCounts": prepared.geometry.rejectionCounts, "overlayPublished": published,
                "overlaySuppressionReason": evaluated["overlayPublicationSuppressionReason"] ?? NSNull(), "deadlineExceeded": evaluated["deadlineExceeded"] ?? false]
            if manifest.detectorTrace { output["detectorTrace"] = trace }
            var encoded = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]); encoded.append(10); try handle.write(contentsOf: encoded)
        }
    }
}

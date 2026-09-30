import Foundation

/// Metadata from the current camera-data callback, independent of TSR/map admission.
/// No pixel storage or inferred road evidence is retained here.
struct LanePreviewSourceGeometry: Equatable, Sendable {
    let captureSessionID: String
    let rawWidth: Int
    let rawHeight: Int
    let rotationDegrees: Int
    let orientationKey: String
    let observedAtUptimeSeconds: Double
    var imageWidth: Int { rotationDegrees % 180 == 0 ? rawWidth : rawHeight }
    var imageHeight: Int { rotationDegrees % 180 == 0 ? rawHeight : rawWidth }
    var geometryKey: String { "\(captureSessionID):\(rawWidth)x\(rawHeight):\(orientationKey)" }
}

enum LanePreviewPresentationMode: String, Sendable { case observed, calibrationReference = "calibration_reference", hidden }

struct LanePreviewPresentationDecision {
    let mode: LanePreviewPresentationMode
    let reason: String
    let referenceLines: [[LanePoint]]
    var referenceOpacity: Double { mode == .calibrationReference ? 0.28 : 0 }
}

struct LanePreviewPresentationDiagnostic {
    let decision: LanePreviewPresentationDecision
    let source: LanePreviewSourceGeometry?
    let calibration: VisualRoadCalibration?
    let matureBoundaryCount: Int
}

/// Presentation only. Reference lines are never inserted into a detector,
/// corridor, tracker, applicability result or speed-limit policy input.
enum LanePreviewPresentationPolicy {
    /// A stale or paused legacy result must not mask the calibration reference.
    /// This mirrors the legacy overlay TTL without depending on its UIKit runtime.
    static func legacyFrameIsCurrent(capturedAtSeconds: Double, nowSeconds: Double,
                                     state: String, legacyAllowed: Bool) -> Bool {
        let age = nowSeconds - capturedAtSeconds
        return legacyAllowed && state != "paused" && age.isFinite && age >= 0 && age < 0.75
    }

    static func decide(enabled: Bool, visible: Bool, active: Bool, thermalPaused: Bool,
                       previewRotation: Int, source: LanePreviewSourceGeometry?,
                       calibration: VisualRoadCalibration?, matureBoundaryCount: Int,
                       contextAvailable: Bool, staleObservedBoundary: Bool, nowUptime: Double) -> LanePreviewPresentationDecision {
        func hidden(_ reason: String) -> LanePreviewPresentationDecision {
            LanePreviewPresentationDecision(mode: .hidden, reason: reason, referenceLines: [])
        }
        guard enabled else { return hidden("lanes_disabled") }
        guard visible else { return hidden("preview_hidden") }
        guard active else { return hidden("activity_paused") }
        guard !thermalPaused else { return hidden("thermal_paused") }
        guard let source, source.rawWidth > 0, source.rawHeight > 0,
              !source.captureSessionID.isEmpty, source.rotationDegrees == previewRotation else {
            return hidden("source_geometry_unavailable")
        }
        let age = nowUptime - source.observedAtUptimeSeconds
        guard age.isFinite, age >= 0, age <= 0.75 else { return hidden("source_geometry_stale") }
        if matureBoundaryCount > 0 {
            return LanePreviewPresentationDecision(mode: .observed, reason: "mature_boundaries", referenceLines: [])
        }
        guard let calibration else { return hidden("calibration_unavailable") }
        guard calibration.compatible(width: source.imageWidth, height: source.imageHeight,
                                     orientationKey: source.orientationKey) else { return hidden("calibration_geometry_incompatible") }
        let reason = !contextAvailable || staleObservedBoundary ? "stale_context" : "no_confirmed_boundaries"
        return LanePreviewPresentationDecision(mode: .calibrationReference, reason: reason,
            referenceLines: [[calibration.leftBottom, LanePoint(x: calibration.leftTopX, y: calibration.horizonY)],
                             [calibration.rightBottom, LanePoint(x: calibration.rightTopX, y: calibration.horizonY)]])
    }
}

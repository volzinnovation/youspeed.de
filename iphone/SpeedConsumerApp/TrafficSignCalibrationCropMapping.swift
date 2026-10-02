import Foundation

/// Pure coordinate conversion for an actual pixel-aligned crop. Scores,
/// semantics and thresholds are copied unchanged; y always spans full height.
struct TrafficSignCalibrationCropMapping: Equatable {
    let sourceWidth: Int
    let leftPixels: Int
    func remap(_ box: TrafficSignNormalizedRect) -> TrafficSignNormalizedRect {
        guard sourceWidth > 0, leftPixels > 0 else { return box }
        let left = Double(leftPixels) / Double(sourceWidth)
        return TrafficSignNormalizedRect(x: left + box.x * (1 - left), y: box.y,
                                         width: box.width * (1 - left), height: box.height)
    }
    func remap(_ detection: TrafficSignDetection) -> TrafficSignDetection {
        guard leftPixels > 0 else { return detection }
        return TrafficSignDetection(rawClassId: detection.rawClassId, rawLabel: detection.rawLabel,
            semantic: detection.semantic, rawScore: detection.rawScore, calibratedConfidence: detection.calibratedConfidence,
            detectorRawScore: detection.detectorRawScore, detectorCalibratedConfidence: detection.detectorCalibratedConfidence,
            classifierRawScore: detection.classifierRawScore, classifierCalibratedConfidence: detection.classifierCalibratedConfidence,
            boundingBox: remap(detection.boundingBox), classThreshold: detection.classThreshold,
            assemblyId: detection.assemblyId, conditionState: detection.conditionState, restrictions: detection.restrictions)
    }
    func remap(_ result: TrafficSignTwoStageInferenceResultV2) -> TrafficSignTwoStageInferenceResultV2 {
        guard leftPixels > 0 else { return result }
        return TrafficSignTwoStageInferenceResultV2(legacyDetections: result.legacyDetections.map(remap),
            assemblies: result.assemblies.map { assembly in
                let primary = assembly.primary
                return TrafficSignTwoStageAssemblyObservationV2(assemblyId: assembly.assemblyId,
                    stableObservationHint: assembly.stableObservationHint,
                    primary: TrafficSignTwoStagePrimaryObservationV2(objectId: primary.objectId, classId: primary.classId,
                        semantic: primary.semantic, boundingBox: remap(primary.boundingBox), detectorScore: primary.detectorScore,
                        detectorCalibratedConfidence: primary.detectorCalibratedConfidence, classifierRawScore: primary.classifierRawScore,
                        classifierCalibratedConfidence: primary.classifierCalibratedConfidence, classifierThreshold: primary.classifierThreshold),
                    supplementaryPlates: assembly.supplementaryPlates.map { plate in
                        TrafficSignTwoStagePlateObservationV2(objectId: plate.objectId, classId: plate.classId,
                            boundingBox: remap(plate.boundingBox), detectorScore: plate.detectorScore,
                            detectorCalibratedConfidence: plate.detectorCalibratedConfidence, classifierRawScore: plate.classifierRawScore,
                            classifierCalibratedConfidence: plate.classifierCalibratedConfidence,
                            auxiliaryEvidence: plate.auxiliaryEvidence, classifierThreshold: plate.classifierThreshold,
                            readability: plate.readability, restriction: plate.restriction)
                    })
            }, detectorLatencyMs: result.detectorLatencyMs, classifierInvoked: result.classifierInvoked,
            classifierLatencyMs: result.classifierLatencyMs, proposalsTruncated: result.proposalsTruncated)
    }
}

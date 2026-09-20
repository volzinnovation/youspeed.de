import Foundation

extension TrafficSignRecognitionEvent {
    func permitsApplicability(_ sink: String, mode: String = TSRApplicabilityConfiguration.defaultMode) -> Bool {
        if mode == "shadow" { return true }
        guard let decision = applicabilityDecision, let context = roadContext,
              decision.scope.sessionId == driveSessionId,
              decision.scope.bundleId == context.sourceSignature.bundleSHA256,
              decision.scope.traversalEpoch == context.traversalEpoch,
              let frameId, let trackID = candidate?.trackId else { return false }
        return TSRApplicabilityAuthority.allows(decision, scope: decision.scope, frameId: frameId, trackId: trackID, sink: sink, mode: mode)
    }
}

extension TrafficSignPassageEvent {
    func permitsApplicability(mode: String = TSRApplicabilityConfiguration.defaultMode) -> Bool {
        if mode == "shadow" { return true }
        guard let decision = applicabilityDecision,
              decision.scope.sessionId == driveSessionID,
              decision.scope.generation == sessionGeneration,
              decision.scope.contextGeneration == contextGeneration,
              decision.scope.bundleId == activationContext.sourceSignature.bundleSHA256,
              decision.scope.traversalEpoch == activationContext.traversalEpoch,
              frameEvidence.contains(where: { $0.frameID == decision.frameId }) else { return false }
        return TSRApplicabilityAuthority.allows(decision, scope: decision.scope, frameId: decision.frameId,
            trackId: physicalTrackID, sink: "passage", mode: mode)
    }
}

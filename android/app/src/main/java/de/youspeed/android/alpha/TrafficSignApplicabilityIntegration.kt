package de.youspeed.android.alpha

fun TrafficSignRecognitionEvent.permitsApplicability(sink: String, mode: String = TSRApplicabilityConfiguration.defaultMode): Boolean {
    if (mode == "shadow") return true
    val decision = applicabilityDecision ?: return false
    val context = roadContext ?: return false
    if (decision.scope.sessionId != driveSessionId || decision.scope.bundleId != context.bundleSha256 || decision.scope.traversalEpoch != context.traversalEpoch) return false
    return TSRApplicabilityAuthority.allows(decision, decision.scope, frameId ?: return false, candidate?.trackId ?: return false, sink, mode)
}
fun TrafficSignPassageEvent.permitsApplicability(mode: String = TSRApplicabilityConfiguration.defaultMode): Boolean {
    if (mode == "shadow") return true
    val decision = applicabilityDecision ?: return false
    val context = activationContext ?: return false
    if (decision.scope.sessionId != driveSessionId || decision.scope.contextGeneration != generation ||
        decision.scope.bundleId != context.bundleSha256 || decision.scope.traversalEpoch != context.traversalEpoch ||
        evidence.none { it.frameId == decision.frameId }) return false
    return TSRApplicabilityAuthority.allows(decision, decision.scope, decision.frameId, physicalTrackId, "passage", mode)
}

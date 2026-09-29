import Foundation

/// Keeps a selected camera value attached to the evidence that produced it.
struct TrafficSignCameraReferenceOffer: Equatable {
    let trackID: String
    let enclosing: Bool
    let provenance: String
    var evidenceID: String { trackID + (enclosing ? ":enclosing" : "") }

    /// Only the current changed-recognition event selects its numeric preview over an older resolver value.
    /// GPS/timer reconciliation continues to use the ordinary resolver selection.
    static func presentationForChangedOverride(_ resolved: EffectiveSpeedLimitState, overrideChanged: Bool,
                                               speedKmh: Int?, trackID: String?) -> EffectiveSpeedLimitState {
        guard overrideChanged, !resolved.isUserCorrection, let speedKmh, speedKmh > 0,
              let trackID, !trackID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return resolved }
        return EffectiveSpeedLimitState(value: .numeric(speedKmh), source: .camera,
            presentationReason: "camera_confirmed_frames", hasCameraEvidenceMarker: true)
    }

    static func select(presentationReason: String, presentedSpeedKmh: Int?, immediateTrackID: String?,
                       immediateSpeedKmh: Int?, passageTrackID: String?, resolverTrackID: String?,
                       resolverEnclosing: Bool) -> Self? {
        if presentationReason == "camera_confirmed_frames" {
            // A concurrent/newer resolver assertion must not lend this override its ID or type.
            // This is the existing numeric-preview stage, also for a recognized zone sign.
            // Only its finalized passage supplies the resolver's enclosing-area assertion.
            guard let speed = presentedSpeedKmh, speed == immediateSpeedKmh,
                  let id = immediateTrackID, !id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return Self(trackID: id, enclosing: false, provenance: "immediate")
        }
        let id: String, source: String
        if let passageTrackID { id = passageTrackID; source = "passage" }
        else if let resolverTrackID { id = resolverTrackID; source = "resolver" }
        else if let immediateTrackID { id = immediateTrackID; source = "immediate_fallback" }
        else { return nil }
        return Self(trackID: id, enclosing: resolverEnclosing, provenance: source)
    }
}

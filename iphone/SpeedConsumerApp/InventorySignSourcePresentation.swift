import Foundation

/// Display decoration only: a retained map origin never overrides camera authority.
enum MobiDataSignSourcePresentation {
    static func isMobiData(sourceID: String?) -> Bool { sourceID == "mobidata-bw-vzk" }

    static func showsLimitContour(state: EffectiveSpeedLimitState, provenance: BundleSpeedProvenance?,
                                  isInSpeedCaptureMode: Bool, hasPendingCameraLimit: Bool,
                                  showsCameraEndSign: Bool) -> Bool {
        guard !isInSpeedCaptureMode, !hasPendingCameraLimit, !showsCameraEndSign,
              state.source == .bundle, state.value != .unknown,
              let provenance, isMobiData(sourceID: provenance.sourceID) else { return false }
        switch provenance.kind {
        case .inventorySign, .inventoryTownContext, .inventoryResetContext: return true
        case .osmTag, .roadDefault: return false
        }
    }
}

enum SpeedLimitSourcePresentation {
    static func localizationKey(state: EffectiveSpeedLimitState, provenance: BundleSpeedProvenance?) -> String {
        guard state.value != .unknown else { return "speed.source.unknown" }
        switch state.source {
        case .camera: return "speed.source.camera"
        case .localCorrection: return state.isUserCorrection ? "speed.source.user_correction" : "speed.source.local_correction"
        case .staleBundle, .lastKnown: return "speed.source.last_known"
        case .none: return "speed.source.unknown"
        case .bundle:
            switch provenance?.kind {
            case .osmTag: return "speed.source.osm_tag"
            case .roadDefault: return "speed.source.road_default"
            case .inventorySign: return "speed.source.inventory_sign"
            case .inventoryTownContext: return "speed.source.inventory_town_context"
            case .inventoryResetContext: return "speed.source.inventory_reset_context"
            case nil: return "speed.source.bundle"
            }
        }
    }
}

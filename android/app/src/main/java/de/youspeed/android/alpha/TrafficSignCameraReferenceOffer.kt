package de.youspeed.android.alpha

/** Keeps a selected camera value attached to the evidence that produced it. */
internal data class TrafficSignCameraReferenceOffer(val trackId: String, val enclosing: Boolean, val provenance: String) {
    val evidenceId: String get() = trackId + if (enclosing) ":enclosing" else ""

    companion object {
        fun select(presentationReason: String, presentedSpeedKmh: Int?, immediateTrackId: String?,
            immediateSpeedKmh: Int?, passageTrackId: String?, resolverTrackId: String?, resolverEnclosing: Boolean): TrafficSignCameraReferenceOffer? {
            if (presentationReason == "camera_confirmed_frames") {
                // A concurrent/newer resolver assertion must not lend this override its ID or type.
                // This is the existing numeric-preview stage, also for a recognized zone sign.
                // Only its finalized passage supplies the resolver's enclosing-area assertion.
                if (presentedSpeedKmh == null || presentedSpeedKmh != immediateSpeedKmh || immediateTrackId.isNullOrBlank()) return null
                return TrafficSignCameraReferenceOffer(immediateTrackId, false, "immediate")
            }
            val (id, source) = when {
                passageTrackId != null -> passageTrackId to "passage"
                resolverTrackId != null -> resolverTrackId to "resolver"
                immediateTrackId != null -> immediateTrackId to "immediate_fallback"
                else -> return null
            }
            return TrafficSignCameraReferenceOffer(id, resolverEnclosing, source)
        }
    }
}

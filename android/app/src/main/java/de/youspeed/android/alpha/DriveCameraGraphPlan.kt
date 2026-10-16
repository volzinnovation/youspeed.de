package de.youspeed.android.alpha

/** The repeating camera stream exists before an optional model worker or movie starts. */
internal data class DriveCameraGraphPlan(
    val photoOutput: Boolean,
    val movieOutput: Boolean,
) {
    /** Preview is drained offscreen when no dashboard preview is attached. */
    fun <T : Any> bindOrder(preview: T, analysis: T, photo: T? = null, movie: T? = null): List<T> =
        buildList {
            add(preview)
            if (photoOutput) add(requireNotNull(photo))
            if (movieOutput) add(requireNotNull(movie))
            add(analysis)
        }

    /** Only the dormant manual output may be sacrificed; preserve every other consumer. */
    fun withoutOptionalManualPhoto(automaticPhotosEnabled: Boolean): DriveCameraGraphPlan? =
        takeIf { photoOutput && !automaticPhotosEnabled }?.copy(photoOutput = false)

    companion object {
        fun resolve(recorderRequested: Boolean, photosRequested: Boolean, previous: DriveCameraGraphPlan? = null) =
            DriveCameraGraphPlan(
                photoOutput = recorderRequested || photosRequested || previous?.photoOutput == true,
                movieOutput = recorderRequested || previous?.movieOutput == true,
            )
    }
}

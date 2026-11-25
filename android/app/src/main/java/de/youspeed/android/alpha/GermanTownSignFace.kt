package de.youspeed.android.alpha

internal object GermanTownSignFace {
    const val WIDTH = 80
    const val HEIGHT = 64

    const val RESCUE_WIDTH = 96
    const val RESCUE_HEIGHT = 72

    init { System.loadLibrary("youspeed_packed_runtime") }

    external fun recoverExit(argb: IntArray): Boolean

    external fun accepts(argb: IntArray, sourceWidth: Double, sourceHeight: Double, townExit: Boolean): Boolean
}

internal object GermanTownTrialOperatingPoint {
    const val DETECTOR_FLOOR = 0.70
    const val PREVIOUS_DETECTOR_FLOOR = 0.840783
    const val EXIT_CLASSIFIER_FLOOR = 0.45

    fun readable(box: NormalizedTrafficSignBoundingBox, width: Int, height: Int) =
        box.width * width >= 32.0 && box.height * height >= 32.0

    fun requiresExitFaceFirst(detectorScore: Double) =
        detectorScore >= DETECTOR_FLOOR && detectorScore < PREVIOUS_DETECTOR_FLOOR

    fun admit(detectorScore: Double, classId: String, classifierScore: Double) =
        detectorScore >= PREVIOUS_DETECTOR_FLOOR || (detectorScore >= DETECTOR_FLOOR &&
            classId == "city:end" && classifierScore >= EXIT_CLASSIFIER_FLOOR)
}

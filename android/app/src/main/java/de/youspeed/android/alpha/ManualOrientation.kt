package de.youspeed.android.alpha

import android.content.pm.ActivityInfo
import android.view.Surface

/** The selected mount position, viewed from the front of the phone. */
enum class ManualOrientation(
    val storageValue: String,
    val requestedOrientation: Int,
    val targetRotation: Int,
) {
    PORTRAIT(
        "portrait",
        ActivityInfo.SCREEN_ORIENTATION_PORTRAIT,
        Surface.ROTATION_0,
    ),
    // The rear camera starts at the top right when projected onto the front.
    // At the lower right, the phone's charging connector points left.
    LANDSCAPE_CAMERA_LOWER_RIGHT(
        "landscape_camera_lower_right",
        ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE,
        Surface.ROTATION_270,
    ),
    // At the upper left, the phone's charging connector points right.
    LANDSCAPE_CAMERA_UPPER_LEFT(
        "landscape_camera_upper_left",
        ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE,
        Surface.ROTATION_90,
    );

    val isLandscape: Boolean
        get() = this != PORTRAIT

    companion object {
        fun fromStorageValue(value: String?): ManualOrientation =
            entries.firstOrNull { it.storageValue == value } ?: PORTRAIT
    }
}

package de.youspeed.android.alpha

interface ConsumerHost {
    fun requestLocationPermission()

    fun openApplicationSettings() {}

    fun requestMicrophonePermission()

    fun requestCameraPermission()

    fun startTrafficSignCamera()

    fun selectTrafficSignModel(countryCode: String?, reason: String = "bundle_selection") {}

    fun stopTrafficSignCamera()

    fun applyManualOrientation(orientation: ManualOrientation) {}

    fun setDriveRecorderPreviewSurfaceProvider(provider: androidx.camera.core.Preview.SurfaceProvider?) {}

    fun capturePanoramaxPhoto(requestId: String)

    fun showTransientMessage(message: String)

    fun openExternalUrl(url: String)

    fun shareFile(path: String, mimeType: String)
}

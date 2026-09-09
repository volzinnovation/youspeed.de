package de.youspeed.android.alpha

interface ConsumerHost {
    fun requestLocationPermission()

    fun requestMicrophonePermission()

    fun requestCameraPermission()

    fun startTrafficSignCamera()

    fun stopTrafficSignCamera()

    fun showTransientMessage(message: String)

    fun openExternalUrl(url: String)

    fun shareFile(path: String, mimeType: String)
}

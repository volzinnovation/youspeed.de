package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import java.io.File
import java.time.Clock

class MainActivity : ComponentActivity(), ConsumerHost {
    private var trafficSignCameraRuntime: AndroidTrafficSignCameraRuntime? = null
    private var cameraReleasePending = false
    private var cameraRequested = false
    private var previewSurfaceProvider: androidx.camera.core.Preview.SurfaceProvider? = null
    internal val sessionController by lazy {
        ConsumerSessionController(
            context = this,
            rootDir = File(filesDir, "bundle"),
            preferences = getSharedPreferences("youspeed", Context.MODE_PRIVATE),
            clock = Clock.systemUTC(),
            countryScreenshotScenario = if (BuildConfig.DEBUG && intent?.hasExtra("screenshot_country") == true) runCatching {
                CountryPenaltyScreenshotScenario(
                    PenaltyCountryCodes.normalize(intent.getStringExtra("screenshot_country")) ?: error("Unsupported screenshot country"),
                    intent.getIntExtra("screenshot_delta", 0), intent.getIntExtra("screenshot_limit", 50),
                )
            }.getOrNull() else null,
            launchScreenshotState = AppScreenshotState.fromRaw(intent?.getStringExtra("screenshot_state") ?: System.getenv("YOUSPEED_SCREENSHOT_STATE")),
        )
    }
    private val locationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { result ->
        sessionController.onLocationPermissionResult(result.values.any { it })
    }
    private val microphonePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        sessionController.onMicrophonePermissionResult(granted)
    }
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        sessionController.onCameraPermissionResult(granted)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        enableEdgeToEdge()
        sessionController.bindHost(this)
        setContent {
            ConsumerApp(sessionController)
        }
    }

    override fun onStart() {
        super.onStart()
        sessionController.setApplicationActive(true)
    }

    override fun onStop() {
        sessionController.setApplicationActive(false)
        super.onStop()
    }

    override fun onDestroy() {
        sessionController.dispose()
        super.onDestroy()
    }

    override fun requestLocationPermission() {
        locationPermissionLauncher.launch(
            arrayOf(
                android.Manifest.permission.ACCESS_FINE_LOCATION,
                android.Manifest.permission.ACCESS_COARSE_LOCATION,
            ),
        )
    }

    override fun onResume() {
        super.onResume()
        sessionController.refreshOnboardingPermissions()
    }

    override fun openApplicationSettings() {
        startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.parse("package:$packageName")))
    }

    override fun requestMicrophonePermission() {
        microphonePermissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
    }

    override fun requestCameraPermission() {
        cameraPermissionLauncher.launch(android.Manifest.permission.CAMERA)
    }

    override fun startTrafficSignCamera() {
        if (isFinishing || isDestroyed) return
        cameraRequested = true
        if (cameraReleasePending) return
        trafficSignCameraRuntime?.let { it.refreshConfiguration(); return }
        trafficSignCameraRuntime = AndroidTrafficSignCameraRuntime(
            context = applicationContext,
            lifecycleOwner = this,
            controller = sessionController,
            onStateChanged = sessionController::onTrafficSignCameraRuntimeStateChanged,
        ).also {
            it.setPreviewSurfaceProvider(previewSurfaceProvider)
            it.start()
        }
    }

    override fun stopTrafficSignCamera() {
        cameraRequested = false
        val previous = trafficSignCameraRuntime ?: return
        trafficSignCameraRuntime = null
        cameraReleasePending = true
        previous.closeAfterFinalization {
            // Drain already posted finalization updates before starting a new
            // camera graph; a rapid foreground transition may request it.
            window.decorView.post {
                cameraReleasePending = false
                if (cameraRequested && !isFinishing && !isDestroyed) startTrafficSignCamera()
            }
        }
    }

    override fun setDriveRecorderPreviewSurfaceProvider(provider: androidx.camera.core.Preview.SurfaceProvider?) {
        previewSurfaceProvider = provider
        trafficSignCameraRuntime?.setPreviewSurfaceProvider(provider)
    }

    override fun capturePanoramaxPhoto(requestId: String) {
        val runtime = trafficSignCameraRuntime
        if (runtime != null) runtime.capturePanoramaxPhoto(requestId)
        else sessionController.onPanoramaxPhotoCaptureFailed("Camera unavailable", requestId)
    }

    override fun showTransientMessage(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    override fun openExternalUrl(url: String) {
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }
    }

    override fun shareFile(path: String, mimeType: String) {
        val file = File(path)
        if (!file.exists()) {
            return
        }
        runCatching {
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = mimeType
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(intent, null))
        }
    }
}

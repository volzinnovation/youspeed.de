package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.content.FileProvider
import java.io.File
import java.time.Clock

class MainActivity : ComponentActivity(), ConsumerHost {
    private val sessionController by lazy {
        ConsumerSessionController(
            context = this,
            rootDir = File(filesDir, "bundle-alpha"),
            preferences = getSharedPreferences("youspeed-alpha", Context.MODE_PRIVATE),
            clock = Clock.systemUTC(),
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        sessionController.bindHost(this)
        setContent {
            ConsumerApp(sessionController)
        }
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

    override fun requestMicrophonePermission() {
        microphonePermissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
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

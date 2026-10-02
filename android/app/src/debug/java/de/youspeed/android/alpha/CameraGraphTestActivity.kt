package de.youspeed.android.alpha

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity

/** Foreground camera permission for isolated graph tests; no controller, settings or owner media. */
class CameraGraphTestActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
}

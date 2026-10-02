package de.youspeed.android.alpha

import android.graphics.ImageFormat
import android.hardware.HardwareBuffer
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import androidx.camera.core.Preview
import androidx.camera.core.SurfaceRequest
import java.util.concurrent.Executor

/** Supplies a repeating surface without displaying, mapping or retaining camera pixels. */
internal class DrainingCameraPreviewProvider(
    private val mainExecutor: Executor,
    private val onFailure: (Exception) -> Unit,
) : Preview.SurfaceProvider {
    override fun onSurfaceRequested(request: SurfaceRequest) {
        val drainThread = HandlerThread("YouSpeedPreviewDrain").apply { start() }
        val reader = try {
            ImageReader.newInstance(request.resolution.width, request.resolution.height,
                ImageFormat.PRIVATE, 3, HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE)
        } catch (failure: Exception) {
            drainThread.quitSafely()
            request.willNotProvideSurface()
            onFailure(failure)
            return
        }
        reader.setOnImageAvailableListener({ source ->
            runCatching { source.acquireLatestImage()?.close() }
        }, Handler(drainThread.looper))
        request.provideSurface(reader.surface, mainExecutor) {
            reader.close()
            drainThread.quitSafely()
        }
    }
}

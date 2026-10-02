package de.youspeed.android.alpha

import android.graphics.Matrix
import android.hardware.camera2.CameraCharacteristics
import androidx.camera.core.ImageProxy
import kotlin.math.*

/** Owner-supplied bus installation, only used by the experimental shadow pipeline. */
internal data class RoadPathCameraIntrinsics(val fx: Double, val fy: Double, val cx: Double,
    val cy: Double, val source: String) {
    fun calibration(image: ImageProxy): RoadPathCalibration? {
        val matrix = image.imageInfo.sensorToBufferTransformMatrix
        val points = floatArrayOf(cx.toFloat(), cy.toFloat(), (cx + fx).toFloat(), cy.toFloat(), cx.toFloat(), (cy + fy).toFloat())
        matrix.mapPoints(points)
        val angle = image.imageInfo.rotationDegrees
        val w = image.width.toDouble(); val h = image.height.toDouble()
        fun upright(x: Double, y: Double): Pair<Double, Double> = when (angle) {
            0 -> x to y; 90 -> (h - y) to x; 180 -> (w - x) to (h - y); 270 -> y to (w - x)
            else -> Double.NaN to Double.NaN
        }
        val center = upright(points[0].toDouble(), points[1].toDouble())
        val ax = upright(points[2].toDouble(), points[3].toDouble())
        val ay = upright(points[4].toDouble(), points[5].toDouble())
        val width = if (angle % 180 == 0) w else h; val height = if (angle % 180 == 0) h else w
        val focalX = max(abs(ax.first - center.first), abs(ay.first - center.first)) / width
        val focalY = max(abs(ax.second - center.second), abs(ay.second - center.second)) / height
        if (!listOf(focalX, focalY, center.first, center.second).all(Double::isFinite) || focalX <= 0 || focalY <= 0) return null
        return RoadPathCalibration("test-bus-2026-09-29:$source:$angle:${image.width}x${image.height}", true,
            focalX, focalY, center.first / width, center.second / height,
            0.0, 0.0, 0.0, 1.60, -0.08)
    }
    companion object {
        fun from(characteristics: (android.hardware.camera2.CameraCharacteristics.Key<*>) -> Any?): RoadPathCameraIntrinsics? {
            val intrinsic = characteristics(CameraCharacteristics.LENS_INTRINSIC_CALIBRATION) as? FloatArray
            if (intrinsic != null && intrinsic.size >= 5 && abs(intrinsic[4]) < 0.01f) {
                return RoadPathCameraIntrinsics(intrinsic[0].toDouble(), intrinsic[1].toDouble(),
                    intrinsic[2].toDouble(), intrinsic[3].toDouble(), "camera2-intrinsics")
            }
            // Public physical camera metadata provides a pinhole approximation;
            // this is recorded as such, not a measured distortion calibration.
            val physical = characteristics(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE) as? android.util.SizeF ?: return null
            val pixels = characteristics(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE) as? android.util.Size ?: return null
            val focals = characteristics(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS) as? FloatArray ?: return null
            if (focals.size != 1 || physical.width <= 0 || physical.height <= 0) return null
            return RoadPathCameraIntrinsics(focals[0] * pixels.width / physical.width.toDouble(),
                focals[0] * pixels.height / physical.height.toDouble(), pixels.width / 2.0, pixels.height / 2.0,
                "camera2-physical-approximation")
        }
    }
}

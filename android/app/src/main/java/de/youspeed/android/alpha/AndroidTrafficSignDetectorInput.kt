package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF

/** Reuses a 1024-square window; scaling/cropping is rendered without a full-size intermediate. */
internal class AndroidTrafficSignDetectorInput : AutoCloseable {
    val bitmap: Bitmap = Bitmap.createBitmap(TrafficSignDetectorGeometry.SIZE, TrafficSignDetectorGeometry.SIZE, Bitmap.Config.ARGB_8888)
    private val canvas = Canvas(bitmap)
    private val paint = Paint(Paint.FILTER_BITMAP_FLAG)
    private val sourceBounds = Rect()
    private val destinationBounds = RectF()

    fun prepare(source: Bitmap): TrafficSignDetectorGeometry {
        val geometry = TrafficSignDetectorGeometry(source.width, source.height)
        canvas.drawColor(Color.rgb(114, 114, 114))
        sourceBounds.set(0, 0, source.width, source.height)
        destinationBounds.set((-geometry.left).toFloat(), 0f,
            TrafficSignDetectorGeometry.SIZE.toFloat(), TrafficSignDetectorGeometry.SIZE.toFloat())
        canvas.drawBitmap(source, sourceBounds, destinationBounds, paint)
        return geometry
    }

    override fun close() { bitmap.recycle() }

    companion object {
        /** Owned native-resolution window for selected upload evidence; no image scaling. */
        fun nativeWindow(source: Bitmap): Bitmap {
            val size = source.height
            val result = if (source.width >= size) {
                val crop = Bitmap.createBitmap(source, source.width - size, 0, size, size)
                if (crop === source) source.copy(Bitmap.Config.ARGB_8888, false) else crop
            } else {
                Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888).apply {
                    eraseColor(Color.rgb(114, 114, 114))
                    Canvas(this).drawBitmap(source, Rect(0, 0, source.width, source.height),
                        Rect(size - source.width, 0, size, size), null)
                }
            }
            result.setHasAlpha(false)
            return result
        }
    }
}

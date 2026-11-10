package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF

/** Reuses a square detector bitmap and fits the entire upright source inside it. */
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
        destinationBounds.set(geometry.left.toFloat(), geometry.top.toFloat(),
            (geometry.left + geometry.scaledWidth).toFloat(),
            (geometry.top + geometry.scaledHeight).toFloat())
        canvas.drawBitmap(source, sourceBounds, destinationBounds, paint)
        return geometry
    }

    fun prepare(source: Bitmap, window: TrafficSignDetectorWindow) {
        require(window.left + window.width <= source.width && window.height == source.height)
        val scale = TrafficSignDetectorGeometry.SIZE.toDouble() / maxOf(window.width, window.height)
        val width = window.width * scale
        val height = window.height * scale
        val left = (TrafficSignDetectorGeometry.SIZE - width) / 2
        val top = (TrafficSignDetectorGeometry.SIZE - height) / 2
        canvas.drawColor(Color.rgb(114, 114, 114))
        sourceBounds.set(window.left, 0, window.left + window.width, window.height)
        destinationBounds.set(left.toFloat(), top.toFloat(), (left + width).toFloat(), (top + height).toFloat())
        canvas.drawBitmap(source, sourceBounds, destinationBounds, paint)
    }

    override fun close() { bitmap.recycle() }
}

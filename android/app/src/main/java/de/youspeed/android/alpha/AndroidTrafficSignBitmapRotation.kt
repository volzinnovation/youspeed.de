package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import kotlin.math.roundToInt

/** Worker-owned full-frame rotation storage; callers borrow the result until the next frame. */
internal class AndroidTrafficSignBitmapRotation : AutoCloseable {
    private var bitmap: Bitmap? = null
    private var canvas: Canvas? = null
    private val matrix = Matrix()
    private val bounds = RectF()
    private val sourceBounds = Rect()
    private val destinationBounds = RectF()
    private val paint = Paint(Paint.FILTER_BITMAP_FLAG)

    fun orient(source: Bitmap, rotationDegrees: Int): Bitmap {
        require(rotationDegrees in listOf(0, 90, 180, 270))
        if (rotationDegrees == 0) return source
        matrix.reset()
        matrix.postRotate(rotationDegrees.toFloat())
        bounds.set(0f, 0f, source.width.toFloat(), source.height.toFloat())
        matrix.mapRect(bounds)
        val width = bounds.width().roundToInt()
        val height = bounds.height().roundToInt()
        var target = bitmap
        if (target == null || target.width != width || target.height != height) {
            target?.recycle()
            target = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            bitmap = target
            canvas = Canvas(target)
        }
        target.density = source.density
        target.eraseColor(Color.TRANSPARENT)
        sourceBounds.set(0, 0, source.width, source.height)
        destinationBounds.set(0f, 0f, source.width.toFloat(), source.height.toFloat())
        requireNotNull(canvas).apply {
            save()
            translate(-bounds.left, -bounds.top)
            concat(this@AndroidTrafficSignBitmapRotation.matrix)
            // Explicit bounds avoid implicit density scaling. This is the same
            // full-frame 90-degree transform as Bitmap.createBitmap, reusing storage.
            drawBitmap(source, sourceBounds, destinationBounds, paint)
            restore()
        }
        return target
    }

    override fun close() {
        bitmap?.recycle()
        bitmap = null
        canvas = null
    }
}

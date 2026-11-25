package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RectF
import kotlin.math.abs

internal object GermanCargoPlate {
    private const val SIZE = 96
    private val codes = setOf("DE:1052-30", "DE:1052-31")

    fun codeIn(restrictions: List<TrafficSignRestriction>): String? = restrictions.firstOrNull {
        it.kind == TrafficSignRestrictionKind.VEHICLE && it.countrySignCode in codes
    }?.countrySignCode

    private external fun match(argb: IntArray, primaryWidth: Double, bounds: IntArray): Int

    class Reader : AutoCloseable {
        init { System.loadLibrary("youspeed_packed_runtime") }

        private val bitmap = Bitmap.createBitmap(SIZE, SIZE, Bitmap.Config.ARGB_8888)
        private val canvas = Canvas(bitmap)
        private val pixels = IntArray(SIZE * SIZE)
        private val bounds = IntArray(4)
        private val paint = Paint(Paint.FILTER_BITMAP_FLAG)
        private val matrix = Matrix()

        data class Result(val code: Int, val box: NormalizedTrafficSignBoundingBox)

        fun classify(source: Bitmap, primary: NormalizedTrafficSignBoundingBox): Result? {
            val width = primary.width * source.width
            if (width < 24) return null
            val side = 1.5 * width
            val left = primary.x * source.width - 0.25 * width
            val top = (primary.y + primary.height) * source.height - 0.25 * width
            if (left < 0 || top < 0 || left + side > source.width || top + side > source.height) return null
            matrix.setRectToRect(RectF(left.toFloat(), top.toFloat(), (left + side).toFloat(), (top + side).toFloat()),
                RectF(0f, 0f, SIZE.toFloat(), SIZE.toFloat()), Matrix.ScaleToFit.FILL)
            canvas.drawColor(Color.BLACK)
            canvas.drawBitmap(source, matrix, paint)
            bitmap.getPixels(pixels, 0, SIZE, 0, 0, SIZE, SIZE)
            val code = match(pixels, width, bounds)
            if (code != 30 && code != 31) return null
            val step = side / SIZE
            return Result(code, NormalizedTrafficSignBoundingBox((left + bounds[0] * step) / source.width,
                (top + bounds[1] * step) / source.height, bounds[2] * step / source.width, bounds[3] * step / source.height))
        }

        fun attach(source: Bitmap, detections: List<TrafficSignDetection>): List<TrafficSignDetection> =
            detections.mapIndexed { index, detection ->
                val primary = detection.candidate
                if (primary.semantic.kind != TrafficSignSemanticKind.MAXIMUM_SPEED || codeIn(primary.restrictions) != null)
                    return@mapIndexed detection
                val result = classify(source, primary.boundingBox) ?: return@mapIndexed detection
                val middle = result.box.x + result.box.width / 2
                val competing = detections.withIndex().any { (otherIndex, other) ->
                    val box = other.candidate.boundingBox
                    val gap = result.box.y - box.y - box.height
                    otherIndex != index && other.candidate.semantic.kind != TrafficSignSemanticKind.UNKNOWN &&
                        abs(box.x + box.width / 2 - middle) <= box.width * 0.25 && gap / box.height in -0.25..0.35
                }
                if (competing) return@mapIndexed detection
                val restriction = TrafficSignRestriction(TrafficSignRestrictionKind.VEHICLE,
                    normalizedValue = if (result.code == 31) "hazmat:water" else "hazmat", countrySignCode = "DE:1052-${result.code}")
                detection.copy(candidate = primary.copy(
                    conditionState = if (primary.conditionState == TrafficSignConditionState.NONE) TrafficSignConditionState.RESOLVED else primary.conditionState,
                    restrictions = primary.restrictions + restriction,
                ))
            }

        override fun close() { bitmap.recycle() }
    }
}

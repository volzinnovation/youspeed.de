package de.youspeed.android.alpha

internal object GermanTownSignFace {
    const val WIDTH = 80
    const val HEIGHT = 64

    init { System.loadLibrary("youspeed_packed_runtime") }

    external fun accepts(argb: IntArray, sourceWidth: Double, sourceHeight: Double, townExit: Boolean): Boolean
}

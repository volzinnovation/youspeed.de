package de.youspeed.android.alpha

import java.io.InputStream

interface AppAssetReader {
    fun readText(name: String): String

    fun readTextOrNull(name: String): String?

    fun openOrNull(name: String): InputStream?

    fun listOrNull(path: String): List<String>?
}

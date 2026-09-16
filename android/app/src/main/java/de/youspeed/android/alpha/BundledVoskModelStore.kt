package de.youspeed.android.alpha

import android.content.Context
import android.content.res.AssetManager
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import org.vosk.Model

private const val VOSK_MODEL_STORAGE_DIR = "speech-models"

data class BundledVoskModelHandle(
    val model: Model,
    val modelPath: String,
    val assetVersion: String,
)

class BundledVoskModelStore(
    context: Context,
    private val rootDir: File,
) {
    private val appContext = context.applicationContext
    private val assets: AssetManager = appContext.assets

    @Throws(IOException::class)
    fun prepareModel(assetPath: String = SpeedCaptureLanguage.GERMAN.modelAssetPath): BundledVoskModelHandle {
        require(assetPath.matches(Regex("[A-Za-z0-9._-]+"))) { "Invalid Vosk model asset path" }
        val assetVersion = readAssetVersion(assetPath)
        val storageRoot = File(rootDir, VOSK_MODEL_STORAGE_DIR)
        val targetDir = File(storageRoot, assetPath)
        val targetVersionFile = File(targetDir, "uuid")
        val targetVersion = targetVersionFile.takeIf(File::exists)?.readText()?.trim().orEmpty()
        if (targetVersion != assetVersion) {
            targetDir.deleteRecursively()
            copyAssetTree(assetPath, storageRoot)
        }
        if (!targetDir.isDirectory) {
            throw IOException("Vosk-Modellverzeichnis fehlt: ${targetDir.absolutePath}")
        }
        return BundledVoskModelHandle(
            model = Model(targetDir.absolutePath),
            modelPath = targetDir.absolutePath,
            assetVersion = assetVersion,
        )
    }

    @Throws(IOException::class)
    private fun readAssetVersion(assetPath: String): String {
        return assets.open("$assetPath/uuid").bufferedReader().use { reader ->
            reader.readLine()?.trim().orEmpty()
        }.ifEmpty {
            throw IOException("Bundled Vosk-Modell hat keine uuid-Datei.")
        }
    }

    @Throws(IOException::class)
    private fun copyAssetTree(assetPath: String, targetParent: File) {
        val children = assets.list(assetPath).orEmpty()
        if (children.isEmpty()) {
            copyAssetFile(assetPath, targetParent)
            return
        }
        val targetDir = File(targetParent, assetPath)
        if (!targetDir.exists() && !targetDir.mkdirs()) {
            throw IOException("Konnte Modellverzeichnis nicht anlegen: ${targetDir.absolutePath}")
        }
        children.forEach { child ->
            copyAssetTree("$assetPath/$child", targetParent)
        }
    }

    @Throws(IOException::class)
    private fun copyAssetFile(assetPath: String, targetParent: File) {
        val targetFile = File(targetParent, assetPath)
        targetFile.parentFile?.mkdirs()
        assets.open(assetPath).use { input ->
            FileOutputStream(targetFile).use { output ->
                input.copyTo(output)
            }
        }
    }
}

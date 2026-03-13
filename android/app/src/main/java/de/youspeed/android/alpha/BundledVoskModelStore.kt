package de.youspeed.android.alpha

import android.content.Context
import android.content.res.AssetManager
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import org.vosk.Model

private const val VOSK_MODEL_ASSET_PATH = "vosk-model-small-de-0.15"
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
    fun prepareModel(): BundledVoskModelHandle {
        val assetVersion = readAssetVersion()
        val storageRoot = File(rootDir, VOSK_MODEL_STORAGE_DIR)
        val targetDir = File(storageRoot, VOSK_MODEL_ASSET_PATH)
        val targetVersionFile = File(targetDir, "uuid")
        val targetVersion = targetVersionFile.takeIf(File::exists)?.readText()?.trim().orEmpty()
        if (targetVersion != assetVersion) {
            targetDir.deleteRecursively()
            copyAssetTree(VOSK_MODEL_ASSET_PATH, storageRoot)
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
    private fun readAssetVersion(): String {
        return assets.open("$VOSK_MODEL_ASSET_PATH/uuid").bufferedReader().use { reader ->
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

package de.youspeed.android.alpha

import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class GitHubReleaseAssetPath(
    val owner: String,
    val repo: String,
    val tag: String,
    val assetName: String,
)

class HttpUrlFetcher(
    private val githubToken: String = "",
) : HttpFetcher {
    private val json = Json { ignoreUnknownKeys = true }
    private val releaseAssetApiUrlByOriginalUrl = linkedMapOf<String, String>()

    override fun fetch(url: String): ByteArray {
        val requestUrl = resolveEffectiveUrl(url)
        val connection = openConnection(requestUrl)
        return try {
            requireSuccess(connection, requestUrl)
            connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    override fun fetchToFile(
        url: String,
        destination: File,
        onProgress: ((completedBytes: Long, totalBytes: Long?) -> Unit)?,
    ) {
        val requestUrl = resolveEffectiveUrl(url)
        val connection = openConnection(requestUrl)
        try {
            requireSuccess(connection, requestUrl)
            val totalBytes = connection.contentLengthLong.takeIf { it > 0L }
            destination.outputStream().use { output ->
                connection.inputStream.use { input ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    var completedBytes = 0L
                    while (true) {
                        val read = input.read(buffer)
                        if (read <= 0) {
                            break
                        }
                        output.write(buffer, 0, read)
                        completedBytes += read.toLong()
                        onProgress?.invoke(completedBytes, totalBytes)
                    }
                }
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun resolveEffectiveUrl(originalUrl: String): String {
        val cached = releaseAssetApiUrlByOriginalUrl[originalUrl]
        if (cached != null) {
            return cached
        }
        val githubAsset = parseGitHubReleaseAssetUrl(originalUrl) ?: return originalUrl
        if (githubToken.isBlank()) {
            return originalUrl
        }
        val apiUrl = resolveGitHubReleaseAssetApiUrl(githubAsset)
        if (apiUrl == null) {
            throw IOException(
                "GitHub release asset not found for ${githubAsset.owner}/${githubAsset.repo} tag=${githubAsset.tag} asset=${githubAsset.assetName}"
            )
        }
        releaseAssetApiUrlByOriginalUrl[originalUrl] = apiUrl
        return apiUrl
    }

    private fun resolveGitHubReleaseAssetApiUrl(asset: GitHubReleaseAssetPath): String? {
        val metadataUrl = "https://api.github.com/repos/${asset.owner}/${asset.repo}/releases/tags/${asset.tag}"
        val metadataBytes = fetchViaConnection(
            url = metadataUrl,
            accept = "application/vnd.github+json",
            useGitHubHeaders = true,
        )
        val release = json.parseToJsonElement(metadataBytes.toString(Charsets.UTF_8)).jsonObject
        val assets = release["assets"]?.jsonArray ?: return null
        val assetId = assets.firstOrNull { item ->
            item.jsonObject["name"]?.jsonPrimitive?.content == asset.assetName
        }?.jsonObject?.get("id")?.jsonPrimitive?.content?.toLongOrNull()
        return assetId?.let { "https://api.github.com/repos/${asset.owner}/${asset.repo}/releases/assets/$it" }
    }

    private fun fetchViaConnection(
        url: String,
        accept: String,
        useGitHubHeaders: Boolean,
    ): ByteArray {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects = true
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("User-Agent", "YouSpeedAndroidAlpha/0.1")
        connection.setRequestProperty("Accept", accept)
        if (useGitHubHeaders) {
            connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
        }
        if (githubToken.isNotBlank() &&
            (url.contains("api.github.com") || url.contains("github.com") || url.contains("githubusercontent.com"))
        ) {
            connection.setRequestProperty("Authorization", "Bearer $githubToken")
        }
        return try {
            val status = connection.responseCode
            val body = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.use { it.readBytes() }
                ?: ByteArray(0)
            if (status !in 200..299) {
                val detail = body.toString(Charsets.UTF_8).take(160)
                throw IOException("HTTP $status for $url: $detail")
            }
            body
        } finally {
            connection.disconnect()
        }
    }

    private fun openConnection(requestUrl: String): HttpURLConnection {
        val connection = URL(requestUrl).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects = true
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("User-Agent", "YouSpeedAndroidAlpha/0.1")
        if (isGitHubReleaseAssetApiUrl(requestUrl)) {
            connection.setRequestProperty("Accept", "application/octet-stream")
        } else if (requestUrl.contains("api.github.com/")) {
            connection.setRequestProperty("Accept", "application/vnd.github+json")
        } else {
            connection.setRequestProperty("Accept", "application/json,application/octet-stream")
        }
        if (requestUrl.contains("api.github.com/")) {
            connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
        }
        if (githubToken.isNotBlank() &&
            (requestUrl.contains("api.github.com") || requestUrl.contains("github.com") || requestUrl.contains("githubusercontent.com"))
        ) {
            connection.setRequestProperty("Authorization", "Bearer $githubToken")
        }
        return connection
    }

    private fun requireSuccess(
        connection: HttpURLConnection,
        url: String,
    ) {
        val status = connection.responseCode
        if (status in 200..299) {
            return
        }
        val detail = connection.errorStream?.use { it.readBytes().toString(Charsets.UTF_8).take(160) }.orEmpty()
        throw IOException("HTTP $status for $url: $detail")
    }

    companion object {
        private fun isGitHubReleaseAssetApiUrl(rawUrl: String): Boolean {
            return rawUrl.contains("api.github.com/") && rawUrl.contains("/releases/assets/")
        }

        fun parseGitHubReleaseAssetUrl(rawUrl: String): GitHubReleaseAssetPath? {
            val url = runCatching { URL(rawUrl) }.getOrNull() ?: return null
            val host = url.host?.lowercase() ?: return null
            if (host != "github.com" && host != "www.github.com") {
                return null
            }
            val parts = url.path.trim('/').split("/")
            if (parts.size < 6 || parts[2] != "releases" || parts[3] != "download") {
                return null
            }
            val owner = parts[0]
            val repo = parts[1]
            val tag = parts[4]
            val assetName = parts.subList(5, parts.size).joinToString("/")
            if (owner.isBlank() || repo.isBlank() || tag.isBlank() || assetName.isBlank()) {
                return null
            }
            return GitHubReleaseAssetPath(owner, repo, tag, assetName)
        }
    }
}

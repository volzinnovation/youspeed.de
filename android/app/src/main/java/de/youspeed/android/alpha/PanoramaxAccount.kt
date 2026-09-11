package de.youspeed.android.alpha

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

object PanoramaxServiceConfiguration {
    const val instanceName = "panoramax.youspeed.de"
    const val origin = "https://panoramax.youspeed.de"
}

data class PanoramaxAccountState(
    val status: String = "Not connected",
    val isConnected: Boolean = false,
    val tokenId: String? = null,
    val hasToken: Boolean = false,
    val isBusy: Boolean = false,
)

interface PanoramaxAccountAccess {
    fun validateConnection(): Boolean
    fun tokenForUpload(): String?
}

data class PanoramaxCredentials(val token: String, val tokenId: String) {
    override fun toString(): String = "PanoramaxCredentials(redacted)"
}

interface PanoramaxCredentialStorage {
    fun read(): PanoramaxCredentials?
    fun save(credentials: PanoramaxCredentials)
    fun delete()
}

/** AES-GCM key stays in Android Keystore; ciphertext is excluded from backup. */
class PanoramaxCredentialStore(context: Context) : PanoramaxCredentialStorage {
    private val file = File(context.noBackupFilesDir, "panoramax-credentials.json")
    private val alias = "de.youspeed.panoramax"

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build())
        }.generateKey()
    }

    @Synchronized override fun read(): PanoramaxCredentials? {
        if (!file.isFile) return null
        val envelope = Json.parseToJsonElement(file.readText()).jsonObject
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.getDecoder().decode(envelope.getValue("iv").jsonPrimitive.content)))
        cipher.updateAAD(PanoramaxServiceConfiguration.origin.toByteArray(Charsets.UTF_8))
        val decoded = cipher.doFinal(Base64.getDecoder().decode(envelope.getValue("ciphertext").jsonPrimitive.content))
        val payload = Json.parseToJsonElement(decoded.toString(Charsets.UTF_8)).jsonObject
        return PanoramaxCredentials(payload.getValue("token").jsonPrimitive.content, payload.getValue("id").jsonPrimitive.content)
    }

    @Synchronized override fun save(credentials: PanoramaxCredentials) {
        require(credentials.token.isNotBlank() && credentials.tokenId.isNotBlank())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(PanoramaxServiceConfiguration.origin.toByteArray(Charsets.UTF_8))
        val payload = buildJsonObject { put("token", credentials.token); put("id", credentials.tokenId) }.toString()
        val encrypted = cipher.doFinal(payload.toByteArray(Charsets.UTF_8))
        val envelope = buildJsonObject {
            put("iv", Base64.getEncoder().encodeToString(cipher.iv))
            put("ciphertext", Base64.getEncoder().encodeToString(encrypted))
        }
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, ".${file.name}.tmp")
        temporary.writeText(envelope.toString())
        try { Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING) }
        finally { temporary.delete() }
    }

    @Synchronized override fun delete() { check(!file.exists() || file.delete()) { "Could not remove Panoramax credentials" } }
}

/** Calls are synchronous: run them on the controller's background executor. No call starts capture or uploads. */
class PanoramaxAccount(
    private val credentials: PanoramaxCredentialStorage,
    private val transport: PanoramaxUploadTransport = HttpPanoramaxUploadTransport(),
) : PanoramaxAccountAccess {
    constructor(context: Context) : this(PanoramaxCredentialStore(context))

    @Volatile var onChange: () -> Unit = {}
    @Volatile var state: PanoramaxAccountState = initialState()
        private set

    private fun initialState(): PanoramaxAccountState = runCatching {
        credentials.read()?.let { PanoramaxAccountState("Token saved — validate connection", tokenId = it.tokenId, hasToken = true) }
            ?: PanoramaxAccountState()
    }.getOrElse { PanoramaxAccountState("Saved credentials are unavailable — connect again") }

    private fun publish(value: PanoramaxAccountState) { state = value; onChange() }

    /** Returns the claim URL that the host should open after the token has been securely saved. */
    @Synchronized fun connect(): String? {
        publish(state.copy(status = "Preparing connection", isBusy = true))
        try {
            val response = transport.execute(PanoramaxHttpRequest("POST", "/api/auth/tokens/generate"))
            response.requireSuccess()
            val root = Json.parseToJsonElement(response.body.toString(Charsets.UTF_8)).jsonObject
            val saved = PanoramaxCredentials(root.getValue("jwt_token").jsonPrimitive.content, root.getValue("id").jsonPrimitive.content)
            credentials.save(saved)
            publish(PanoramaxAccountState("Confirm the claim link in your browser", tokenId = saved.tokenId, hasToken = true))
            return root["links"]?.jsonArray?.map { it.jsonObject }?.firstOrNull { it["rel"]?.jsonPrimitive?.content == "claim" }
                ?.get("href")?.jsonPrimitive?.content?.takeIf { runCatching { URI(it).scheme == "https" }.getOrDefault(false) }
        } catch (error: Exception) {
            publish(state.copy(status = "Connection failed: ${PanoramaxUploadClient.userMessage(error)}", isBusy = false))
            return null
        }
    }

    @Synchronized override fun validateConnection(): Boolean {
        val saved = runCatching { credentials.read() }.getOrNull()
        if (saved == null) { publish(PanoramaxAccountState()); return false }
        publish(state.copy(status = "Checking connection", isBusy = true))
        return try {
            transport.execute(PanoramaxHttpRequest("GET", "/api/users/me", token = saved.token)).requireSuccess()
            publish(PanoramaxAccountState("Connected", isConnected = true, tokenId = saved.tokenId, hasToken = true))
            true
        } catch (_: Exception) {
            publish(PanoramaxAccountState("Not confirmed yet, unavailable, or expired", tokenId = saved.tokenId, hasToken = true))
            false
        }
    }

    @Synchronized fun disconnect() {
        val saved = runCatching { credentials.read() }.getOrNull()
        credentials.delete()
        publish(PanoramaxAccountState("Disconnected"))
        if (saved != null) runCatching {
            transport.execute(PanoramaxHttpRequest("DELETE", "/api/users/me/tokens/${PanoramaxUploadClient.pathSegment(saved.tokenId)}", token = saved.token)).requireSuccess()
        }
    }

    override fun tokenForUpload(): String? = runCatching { credentials.read()?.token }.getOrNull()
}

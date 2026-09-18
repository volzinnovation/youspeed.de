package de.youspeed.android.alpha

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
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
    const val openStreetMapInstanceName = "panoramax.openstreetmap.fr"
    const val openStreetMapOrigin = "https://panoramax.openstreetmap.fr"
}

data class PanoramaxServerPreset(
    val id: String,
    val name: String,
    val origin: String,
)

object PanoramaxServerCatalog {
    val presets = listOf(
        PanoramaxServerPreset("youspeed", "YouSpeed (${PanoramaxServiceConfiguration.instanceName})", PanoramaxServiceConfiguration.origin),
        PanoramaxServerPreset("openstreetmap-france", "OpenStreetMap France (${PanoramaxServiceConfiguration.openStreetMapInstanceName})", PanoramaxServiceConfiguration.openStreetMapOrigin),
    )

    val default: PanoramaxServerPreset get() = presets.first()
    fun find(id: String?): PanoramaxServerPreset = presets.firstOrNull { it.id == id } ?: default
}

data class PanoramaxAccountState(
    val status: String = "Not connected",
    val isConnected: Boolean = false,
    val tokenId: String? = null,
    val hasToken: Boolean = false,
    val isBusy: Boolean = false,
    val instanceName: String = PanoramaxServerCatalog.default.name,
)

interface PanoramaxAccountAccess {
    val origin: String get() = PanoramaxServiceConfiguration.origin
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

interface PanoramaxOriginCredentialStorage : PanoramaxCredentialStorage {
    fun read(origin: String): PanoramaxCredentials?
    fun save(origin: String, credentials: PanoramaxCredentials)
    fun delete(origin: String)
}

/** AES-GCM key stays in Android Keystore; ciphertext is excluded from backup. */
class PanoramaxCredentialStore(context: Context) : PanoramaxOriginCredentialStorage {
    private val root = context.noBackupFilesDir
    private val alias = "de.youspeed.panoramax"

    private fun file(origin: String): File {
        if (origin == PanoramaxServerCatalog.default.origin) return File(root, "panoramax-credentials.json")
        return File(root, "panoramax-credentials-${sha256(origin).take(24)}.json")
    }

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
        return read(PanoramaxServerCatalog.default.origin)
    }

    @Synchronized override fun read(origin: String): PanoramaxCredentials? {
        val file = file(origin)
        if (!file.isFile) return null
        val envelope = Json.parseToJsonElement(file.readText()).jsonObject
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.getDecoder().decode(envelope.getValue("iv").jsonPrimitive.content)))
        cipher.updateAAD(origin.toByteArray(Charsets.UTF_8))
        val decoded = cipher.doFinal(Base64.getDecoder().decode(envelope.getValue("ciphertext").jsonPrimitive.content))
        val payload = Json.parseToJsonElement(decoded.toString(Charsets.UTF_8)).jsonObject
        return PanoramaxCredentials(payload.getValue("token").jsonPrimitive.content, payload.getValue("id").jsonPrimitive.content)
    }

    @Synchronized override fun save(credentials: PanoramaxCredentials) {
        save(PanoramaxServerCatalog.default.origin, credentials)
    }

    @Synchronized override fun save(origin: String, credentials: PanoramaxCredentials) {
        require(credentials.token.isNotBlank() && credentials.tokenId.isNotBlank())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(origin.toByteArray(Charsets.UTF_8))
        val payload = buildJsonObject { put("token", credentials.token); put("id", credentials.tokenId) }.toString()
        val encrypted = cipher.doFinal(payload.toByteArray(Charsets.UTF_8))
        val envelope = buildJsonObject {
            put("iv", Base64.getEncoder().encodeToString(cipher.iv))
            put("ciphertext", Base64.getEncoder().encodeToString(encrypted))
        }
        val file = file(origin)
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, ".${file.name}.tmp")
        temporary.writeText(envelope.toString())
        try { Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING) }
        finally { temporary.delete() }
    }

    @Synchronized override fun delete() { delete(PanoramaxServerCatalog.default.origin) }

    @Synchronized override fun delete(origin: String) {
        val file = file(origin)
        check(!file.exists() || file.delete()) { "Could not remove Panoramax credentials" }
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}

/** Calls are synchronous: run them on the controller's background executor. No call starts capture or uploads. */
class PanoramaxAccount(
    private val credentials: PanoramaxCredentialStorage,
    private val transport: PanoramaxUploadTransport = HttpPanoramaxUploadTransport(),
    private val preferences: SharedPreferences? = null,
) : PanoramaxAccountAccess {
    constructor(context: Context) : this(
        credentials = PanoramaxCredentialStore(context),
        preferences = context.getSharedPreferences("panoramax", Context.MODE_PRIVATE),
    )

    @Volatile var onChange: () -> Unit = {}
    @Volatile private var selectedServerID = preferences?.getString(KEY_SERVER_ID, null) ?: PanoramaxServerCatalog.default.id
    @Volatile var state: PanoramaxAccountState = initialState()
        private set

    override val origin: String get() = selectedServer.origin
    val selectedServer: PanoramaxServerPreset
        get() = PanoramaxServerCatalog.find(selectedServerID)

    @Synchronized fun selectServer(id: String) {
        val server = PanoramaxServerCatalog.find(id)
        if (server.id == selectedServer.id) return
        selectedServerID = server.id
        preferences?.edit()?.putString(KEY_SERVER_ID, server.id)?.apply()
        publish(initialState())
    }

    private fun readCredentials(): PanoramaxCredentials? {
        val originStorage = credentials as? PanoramaxOriginCredentialStorage
        return originStorage?.read(origin) ?: credentials.read().takeIf { origin == PanoramaxServerCatalog.default.origin }
    }

    private fun saveCredentials(value: PanoramaxCredentials) {
        val originStorage = credentials as? PanoramaxOriginCredentialStorage
        if (originStorage != null) originStorage.save(origin, value) else {
            require(origin == PanoramaxServerCatalog.default.origin) { "Credential storage does not support multiple Panoramax instances" }
            credentials.save(value)
        }
    }

    private fun deleteCredentials() {
        val originStorage = credentials as? PanoramaxOriginCredentialStorage
        if (originStorage != null) originStorage.delete(origin) else credentials.delete()
    }

    private fun initialState(): PanoramaxAccountState = runCatching {
        readCredentials()?.let { PanoramaxAccountState("Token saved — validate connection", tokenId = it.tokenId, hasToken = true, instanceName = selectedServer.name) }
            ?: PanoramaxAccountState(instanceName = selectedServer.name)
    }.getOrElse { PanoramaxAccountState("Saved credentials are unavailable — connect again", instanceName = selectedServer.name) }

    private fun publish(value: PanoramaxAccountState) { state = value; onChange() }

    /** Returns the claim URL that the host should open after the token has been securely saved. */
    @Synchronized fun connect(): String? {
        publish(state.copy(status = "Preparing connection", isBusy = true))
        try {
            val response = transport.execute(PanoramaxHttpRequest("POST", "/api/auth/tokens/generate", origin = origin))
            response.requireSuccess()
            val root = Json.parseToJsonElement(response.body.toString(Charsets.UTF_8)).jsonObject
            val saved = PanoramaxCredentials(root.getValue("jwt_token").jsonPrimitive.content, root.getValue("id").jsonPrimitive.content)
            saveCredentials(saved)
            publish(PanoramaxAccountState("Confirm the claim link in your browser", tokenId = saved.tokenId, hasToken = true, instanceName = selectedServer.name))
            return root["links"]?.jsonArray?.map { it.jsonObject }?.firstOrNull { it["rel"]?.jsonPrimitive?.content == "claim" }
                ?.get("href")?.jsonPrimitive?.content?.takeIf { runCatching { URI(it).scheme == "https" }.getOrDefault(false) }
        } catch (error: Exception) {
            publish(state.copy(status = "Connection failed: ${PanoramaxUploadClient.userMessage(error)}", isBusy = false))
            return null
        }
    }

    @Synchronized override fun validateConnection(): Boolean {
        val saved = runCatching { readCredentials() }.getOrNull()
        if (saved == null) { publish(PanoramaxAccountState(instanceName = selectedServer.name)); return false }
        publish(state.copy(status = "Checking connection", isBusy = true))
        return try {
            transport.execute(PanoramaxHttpRequest("GET", "/api/users/me", token = saved.token, origin = origin)).requireSuccess()
            publish(PanoramaxAccountState("Connected", isConnected = true, tokenId = saved.tokenId, hasToken = true, instanceName = selectedServer.name))
            true
        } catch (_: Exception) {
            publish(PanoramaxAccountState("Not confirmed yet, unavailable, or expired", tokenId = saved.tokenId, hasToken = true, instanceName = selectedServer.name))
            false
        }
    }

    @Synchronized fun disconnect() {
        val saved = runCatching { readCredentials() }.getOrNull()
        deleteCredentials()
        publish(PanoramaxAccountState("Disconnected", instanceName = selectedServer.name))
        if (saved != null) runCatching {
            transport.execute(PanoramaxHttpRequest("DELETE", "/api/users/me/tokens/${PanoramaxUploadClient.pathSegment(saved.tokenId)}", token = saved.token, origin = origin)).requireSuccess()
        }
    }

    override fun tokenForUpload(): String? = runCatching { readCredentials()?.token }.getOrNull()

    private companion object {
        const val KEY_SERVER_ID = "server_id"
    }
}

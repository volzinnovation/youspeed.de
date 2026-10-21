package de.youspeed.android.alpha

import android.content.Context
import java.io.File
import kotlinx.serialization.json.*

/** First launch identity creation is independent of camera/collection consent. */
internal class SignCollectionFoundation(context: Context) {
    val contract: Result<SignCollectionContractGate> = runCatching {
        SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
    }
    val interests: SignCollectionInterestStore? = runCatching {
        check(contract.isSuccess)
        val schema = context.assets.open("tsr/collection-contract-v1/crop-interest-v1.schema.json").use {
            SignCollectionJson.parse(it.readBytes().toString(Charsets.UTF_8)).jsonObject
        }
        SignCollectionInterestStore(File(context.noBackupFilesDir,"SignCollection/crop-interest.json"),schema)
    }.getOrNull()
    val store: Result<SignCollectionStore> = runCatching {
        SignCollectionStore(File(context.noBackupFilesDir, "SignCollection"), contract.getOrElse { SignCollectionContractGate.blocked })
    }
}

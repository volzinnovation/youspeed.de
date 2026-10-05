package de.youspeed.android.alpha

import android.content.Context
import java.io.File

/** First launch identity creation is independent of camera/collection consent. */
internal class SignCollectionFoundation(context: Context) {
    val contract: Result<SignCollectionContractGate> = runCatching {
        SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
    }
    val store: Result<SignCollectionStore> = runCatching {
        SignCollectionStore(File(context.noBackupFilesDir, "SignCollection"), contract.getOrElse { SignCollectionContractGate.blocked })
    }
}

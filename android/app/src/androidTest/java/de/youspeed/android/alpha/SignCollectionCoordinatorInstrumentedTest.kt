package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertTrue
import org.junit.Test

class SignCollectionCoordinatorInstrumentedTest {
    @Test fun lateModelCallbackAfterCloseDoesNotRestartStorage() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = instrumentation.targetContext
        val id = "collection-close-${SignCollectionJson.uuid()}"
        val root = File(base.cacheDir, id).apply { mkdirs() }
        val context = object : ContextWrapper(base) {
            override fun getNoBackupFilesDir() = root
            override fun getSharedPreferences(name: String, mode: Int) = base.getSharedPreferences("$id-$name", mode)
        }
        val pack = AndroidTrafficSignModelPackLoader.load(base)
        val foundation = SignCollectionFoundation(context)
        lateinit var coordinator: SignCollectionCoordinator
        instrumentation.runOnMainSync {
            coordinator = SignCollectionCoordinator(context, foundation)
            coordinator.close()
            coordinator.modelLoaded(pack)
            coordinator.clearPendingForDeveloper()
            coordinator.close()
        }
        val worker = SignCollectionCoordinator::class.java.getDeclaredField("storage")
            .apply { isAccessible = true }.get(coordinator) as ExecutorService
        try {
            assertTrue("Closed collection storage drains existing work", worker.awaitTermination(10, TimeUnit.SECONDS))
        } finally {
            foundation.store.getOrNull()?.close()
            base.deleteSharedPreferences("$id-youspeed.sign_collection")
            root.deleteRecursively()
        }
    }
}

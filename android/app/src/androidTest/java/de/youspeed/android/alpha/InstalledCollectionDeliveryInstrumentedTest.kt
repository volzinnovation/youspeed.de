package de.youspeed.android.alpha

import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Explicit device acceptance sends only the installation's existing real queue. */
class InstalledCollectionDeliveryInstrumentedTest {
    @Test fun existingRealCropsAreSent() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("send_real_queue") == "true")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = SignCollectionFoundation(context).store.getOrThrow()
        try {
            store.migrateAutomaticCrops()
            val client = SignCollectionHTTPClient()
            val measured = object : SignCollectionRequesting {
                override fun request(path: String,body: String?): SignCollectionHTTPResponse = client.request(path,body).also {
                    Log.i("YouSpeedCollectionAcceptance","$path status=${it.status}")
                }
                override fun captureCrop(metadata: String,bytes: ByteArray) = client.captureCrop(metadata,bytes).also {
                    Log.i("YouSpeedCollectionAcceptance","capture-crops status=${it.status}")
                }
            }
            val worker = SignCollectionUploadWorker(store,measured)
            var cycles = 0
            while (store.nextCrop() != null && cycles++ < 30) {
                val result = worker.runOnce(true,true)
                Log.i("YouSpeedCollectionAcceptance","cycle=$cycles result=$result")
                assertTrue("Automatic delivery result: $result",result in listOf("crop_sent","metadata_sent"))
                // Respect the server request budget while exercising the real worker.
                Thread.sleep(7000)
            }
            assertNull(store.nextCrop()); assertEquals(0,store.cropReviewCount())
        } finally { store.close() }
    }
}

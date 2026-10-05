package de.youspeed.android.alpha

import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Explicit device acceptance sends only the installation's existing real queue. */
class InstalledCollectionDeliveryInstrumentedTest {
    @Test fun existingRealCropsReceiveDurableReceipts() {
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
                override fun upload(handle: String,bytes: ByteArray) = client.upload(handle,bytes).also {
                    Log.i("YouSpeedCollectionAcceptance","crop_content status=${it.status}")
                }
            }
            val worker = SignCollectionUploadWorker(store,measured)
            var cycles = 0
            while (store.nextCrop() != null && cycles++ < 30) {
                val result = worker.runOnce(true,true)
                Log.i("YouSpeedCollectionAcceptance","cycle=$cycles result=$result")
                assertTrue("Automatic delivery result: $result",result in listOf("crop_committed","metadata_committed"))
                // Respect the server request budget while exercising the real worker.
                Thread.sleep(7000)
            }
            assertNull(store.nextCrop()); assertEquals(0,store.cropReviewCount())
            worker.runOnce(true,true) // append the final crop's linked status
        } finally { store.close() }
    }
}

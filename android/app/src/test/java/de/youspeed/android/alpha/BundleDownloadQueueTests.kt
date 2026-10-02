package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class BundleDownloadQueueTests {
    @Test fun multipleSelectionsWaitInOrderWithoutDuplicates() {
        val queue = BundleDownloadQueue<String> { it }
        listOf("active", "belgium", "provence-alpes-cote-d-azur", "belgium").forEach {
            queue.enqueue(it, "active")
        }
        assertNull(queue.next(isBusy = true))
        assertEquals(listOf("belgium", "provence-alpes-cote-d-azur"), queue.ids)
        assertEquals("belgium", queue.next(isBusy = false))
        // The worker can continue with the next request after success or failure.
        assertEquals("provence-alpes-cote-d-azur", queue.next(isBusy = false))
        assertNull(queue.next(isBusy = false))
    }

    @Test fun cancellingOneSelectionKeepsTheRemainingOrder() {
        val queue = BundleDownloadQueue<String> { it }
        listOf("belgium", "netherlands", "switzerland").forEach { queue.enqueue(it, null) }
        queue.remove("netherlands")
        queue.remove("not-queued")
        assertEquals(listOf("belgium", "switzerland"), queue.ids)
        assertEquals("belgium", queue.next(isBusy = false))
        assertEquals("switzerland", queue.next(isBusy = false))
    }
}

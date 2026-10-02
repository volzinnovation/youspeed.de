package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.graphics.Bitmap
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Bounded gallery content fixtures; no app preferences, device rotation, or user photos are changed. */
@RunWith(AndroidJUnit4::class)
class PanoramaxGalleryLayoutInstrumentedTest {
    @get:Rule val compose = createComposeRule()
    private data class Viewport(val width: Int, val height: Int, val fontScale: Float)

    @Test fun shortLandscapeAndLargeTextKeepWholePhotosAndAllControlsReachable() = withController { controller ->
        val viewport = mutableStateOf(Viewport(840, 276, 1f))
        compose.setContent {
            // Density 1 lets the same content bounds fit both portrait and
            // landscape test devices without overriding system display settings.
            CompositionLocalProvider(LocalDensity provides Density(1f, viewport.value.fontScale)) {
                MaterialTheme {
                    Box(Modifier.fillMaxSize()) {
                        key(viewport.value) {
                            Box(Modifier.requiredSize(viewport.value.width.dp, viewport.value.height.dp)
                                .clipToBounds().testTag("gallery-test-viewport")) {
                                PanoramaxGalleryPane(controller)
                            }
                        }
                    }
                }
            }
        }
        for (size in listOf(Viewport(840, 276, 1f), Viewport(840, 276, 1.5f),
            Viewport(640, 276, 2f), Viewport(320, 640, 1.5f))) {
            compose.runOnIdle { viewport.value = size }
            val list = compose.onNodeWithTag("panoramax-photo-list")
            val context = InstrumentationRegistry.getInstrumentation().targetContext
            val layout = buildString {
                appendLine("$size list=${list.fetchSemanticsNode().boundsInRoot}")
                compose.onAllNodesWithTag("gallery-action").fetchSemanticsNodes().forEach {
                    appendLine("action=${it.boundsInRoot}")
                }
                appendLine("tabs=${compose.onNodeWithTag("gallery-tab-pictures").fetchSemanticsNode().boundsInRoot}")
            }
            File(context.cacheDir, "gallery-layout-${size.width}-${size.height}-${size.fontScale}.txt").writeText(layout)
            File(context.cacheDir, "gallery-layout-${size.width}-${size.height}-${size.fontScale}-before-scroll.png").outputStream().use {
                assertTrue(compose.onNodeWithTag("gallery-test-viewport").captureToImage().asAndroidBitmap()
                    .compress(Bitmap.CompressFormat.PNG, 100, it))
            }
            assertTrue("A complete 92dp thumbnail fits the scroll viewport: $layout",
                list.fetchSemanticsNode().size.height >= 92)
            list.performScrollToNode(hasTestTag("panoramax-thumbnail-gallery-photo-0"))
            val thumbnail = compose.onNodeWithTag("panoramax-thumbnail-gallery-photo-0")
            thumbnail.performScrollTo().assertIsDisplayed()
            val photo = thumbnail.fetchSemanticsNode()
            assertEquals("The photo is not vertically clipped at $size", 92f, photo.boundsInRoot.height, 1f)
            assertEquals(92f, photo.boundsInRoot.width, 1f)

            val actions = compose.onAllNodesWithTag("gallery-action").fetchSemanticsNodes()
            assertEquals(4, actions.size)
            if (size.height < 360) {
                assertEquals("Compact actions stay in one row at $size", 1,
                    actions.map { it.boundsInRoot.top }.distinct().size)
            }
            actions.forEach {
                assertFalse("Every action keeps its localized label and count at $size",
                    it.config.getOrNull(SemanticsProperties.Text).isNullOrEmpty())
            }
            val bounds = compose.onNodeWithTag("gallery-test-viewport").fetchSemanticsNode().boundsInRoot
            val controls = actions + listOf("gallery-tab-pictures", "gallery-tab-videos").map {
                compose.onNodeWithTag(it).assertIsDisplayed().fetchSemanticsNode()
            }
            controls.forEach { control ->
                assertTrue("Touch targets retain at least 48dp at $size", control.size.height >= 48)
                assertEquals("Controls are not vertically clipped at $size", control.size.height.toFloat(), control.boundsInRoot.height, 1f)
                assertTrue("Controls stay inside the available content at $size",
                    control.boundsInRoot.top >= bounds.top && control.boundsInRoot.bottom <= bounds.bottom)
            }
            File(context.cacheDir, "gallery-layout-${size.width}-${size.height}-${size.fontScale}.png").outputStream().use {
                assertTrue(compose.onNodeWithTag("gallery-test-viewport").captureToImage().asAndroidBitmap()
                    .compress(Bitmap.CompressFormat.PNG, 100, it))
            }
            compose.onNodeWithTag("gallery-tab-videos").performClick()
            compose.onNodeWithTag("gallery-tab-pictures").performClick()
            compose.onNodeWithTag("panoramax-photo-list").assertIsDisplayed()
        }
    }

    private fun withController(block: (ConsumerSessionController) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = instrumentation.targetContext
        val id = "gallery-layout-${UUID.randomUUID()}"
        val directory = File(base.cacheDir, id).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = File(directory, "files").apply { mkdirs() }
            override fun getCacheDir(): File = File(directory, "cache").apply { mkdirs() }
            override fun getNoBackupFilesDir(): File = File(directory, "no-backup").apply { mkdirs() }
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences =
                base.getSharedPreferences("$id-$name", mode)
        }
        val oldLocale = Locale.getDefault()
        var controller: ConsumerSessionController? = null
        try {
            Locale.setDefault(Locale.GERMANY)
            val store = PanoramaxQueueStore(isolated)
            val now = Instant.now().minusSeconds(10)
            val batch = store.createBatch("gallery-layout-session", now)
            val original = File(directory, "photo.jpg")
            Bitmap.createBitmap(160, 100, Bitmap.Config.ARGB_8888).apply {
                eraseColor(android.graphics.Color.BLUE)
                original.outputStream().use { assertTrue(compress(Bitmap.CompressFormat.JPEG, 90, it)) }
                recycle()
            }
            repeat(3) { index ->
                val timestamp = now.plusSeconds(index.toLong())
                store.addJpeg(batch.batchId, original, original, PanoramaxCaptureMetadata(
                    "gallery-photo-$index", batch.captureSessionId, timestamp,
                    PanoramaxLocationSample(49.0, 8.0, timestamp, 2.0), PanoramaxQueueStore.sha256(original), original.length(), "test"))
            }
            store.transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW)
            instrumentation.runOnMainSync {
                controller = ConsumerSessionController(isolated, File(isolated.filesDir, "bundle"),
                    isolated.getSharedPreferences("youspeed", Context.MODE_PRIVATE), Clock.systemUTC(),
                    AppScreenshotState.OTHER_SIGN_GIVE_WAY)
            }
            val subject = requireNotNull(controller)
            compose.waitUntil(10_000) { !subject.uiState.panoramaxMaintenanceInProgress && subject.uiState.panoramaxCaptureCount == 3 }
            block(subject)
        } finally {
            controller?.let { subject ->
                instrumentation.runOnMainSync { subject.dispose() }
                val field = ConsumerSessionController::class.java.getDeclaredField("executor").apply { isAccessible = true }
                assertTrue((field.get(subject) as ExecutorService).awaitTermination(10, TimeUnit.SECONDS))
            }
            base.deleteSharedPreferences("$id-youspeed")
            directory.deleteRecursively()
            Locale.setDefault(oldLocale)
        }
    }
}

package de.youspeed.android.alpha

import android.Manifest
import android.content.Intent
import android.os.SystemClock
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.Preview
import androidx.camera.core.UseCase
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Explicit opt-in: uses the rear camera and creates one temporary, silent test movie. */
@RunWith(AndroidJUnit4::class)
class DriveCameraGraphInstrumentedTest {
    @get:Rule val permissions: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.CAMERA)

    private fun newAnalysis() = ImageAnalysis.Builder()
        .setResolutionSelector(ResolutionSelector.Builder().setResolutionStrategy(
            ResolutionStrategy(Size(1920, 1080), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)
        ).build())
        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()

    @Test fun coldStandaloneAnalysisAndMovieStopBothDeliverFramesWithoutLaneDetection() {
        assumeTrue("Requires explicit camera_graph_test=true and an available foreground camera",
            InstrumentationRegistry.getArguments().getString("camera_graph_test") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val mainExecutor = ContextCompat.getMainExecutor(context)
        val provider = ProcessCameraProvider.getInstance(context).get(30, TimeUnit.SECONDS)
        val frames = AtomicReference(CountDownLatch(5))
        val failure = AtomicReference<Exception?>()
        val frameExecutor = Executors.newSingleThreadExecutor()
        var preview = Preview.Builder().build()
        var analysis = newAnalysis()
        var attached = emptyList<UseCase>()
        var recording: Recording? = null
        val movie = File(context.cacheDir, "camera-graph-test-${UUID.randomUUID()}.mp4")
        val started = CountDownLatch(1)
        val encoded = CountDownLatch(1)
        val finalized = CountDownLatch(1)
        val result = AtomicReference<VideoRecordEvent.Finalize?>()
        fun expectFrames(stage: String) {
            assertTrue("$stage must deliver frames with no lane consumer; surface failure=${failure.get()}",
                frames.get().await(15, TimeUnit.SECONDS))
            assertNull(failure.get())
        }
        fun attachDelayedAnalyzer() {
            // Reproduce model loading: the graph is bound with no analyzer.
            SystemClock.sleep(1_000)
            instrumentation.runOnMainSync {
                analysis.setAnalyzer(frameExecutor) { image ->
                    try { frames.get().countDown() } finally { image.close() }
                }
            }
        }
        val scenario = ActivityScenario.launch<CameraGraphTestActivity>(Intent(context, CameraGraphTestActivity::class.java))
        try {
            val standalone = DriveCameraGraphPlan.resolve(false, false)
            scenario.onActivity { activity ->
                preview.setSurfaceProvider(mainExecutor, DrainingCameraPreviewProvider(mainExecutor) { failure.set(it) })
                attached = standalone.bindOrder<UseCase>(preview, analysis)
                provider.bindToLifecycle(activity, CameraSelector.DEFAULT_BACK_CAMERA, *attached.toTypedArray())
            }
            attachDelayedAnalyzer()
            expectFrames("Cold standalone TSR")
            assertFalse("Standalone recognition must not create a movie", movie.exists())

            scenario.moveToState(Lifecycle.State.CREATED)
            frames.set(CountDownLatch(5))
            scenario.moveToState(Lifecycle.State.RESUMED)
            expectFrames("Foreground standalone TSR")

            // The field failure followed disposal/recreation inside one process.
            // A new graph must start without inheriting a former movie consumer.
            instrumentation.runOnMainSync {
                analysis.clearAnalyzer()
                provider.unbind(*attached.toTypedArray())
            }
            scenario.recreate()
            scenario.onActivity { activity ->
                preview = Preview.Builder().build()
                analysis = newAnalysis()
                frames.set(CountDownLatch(5))
                preview.setSurfaceProvider(mainExecutor, DrainingCameraPreviewProvider(mainExecutor) { failure.set(it) })
                attached = standalone.bindOrder<UseCase>(preview, analysis)
                provider.bindToLifecycle(activity, CameraSelector.DEFAULT_BACK_CAMERA, *attached.toTypedArray())
            }
            attachDelayedAnalyzer()
            expectFrames("Recreated standalone TSR")
            assertFalse("Recreation must not create a movie", movie.exists())

            val withRecorder = DriveCameraGraphPlan.resolve(true, false, standalone)
            val video = VideoCapture.Builder(Recorder.Builder().build()).build()
            val photo = ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build()
            frames.set(CountDownLatch(5))
            scenario.onActivity { activity ->
                provider.unbind(*attached.toTypedArray())
                attached = withRecorder.bindOrder<UseCase>(preview, analysis, photo, video)
                provider.bindToLifecycle(activity, CameraSelector.DEFAULT_BACK_CAMERA, *attached.toTypedArray())
                recording = video.output.prepareRecording(context, FileOutputOptions.Builder(movie).build())
                    .start(mainExecutor) { event ->
                        when (event) {
                            is VideoRecordEvent.Start -> started.countDown()
                            is VideoRecordEvent.Status -> if (event.recordingStats.recordedDurationNanos >= 1_000_000_000 &&
                                event.recordingStats.numBytesRecorded > 1_024) encoded.countDown()
                            is VideoRecordEvent.Finalize -> { result.set(event); finalized.countDown() }
                        }
                    }
            }
            assertTrue("Test movie starts", started.await(15, TimeUnit.SECONDS))
            assertTrue("Test movie contains encoded frames before stopping", encoded.await(15, TimeUnit.SECONDS))
            frames.set(CountDownLatch(5))
            expectFrames("Recording TSR")
            instrumentation.runOnMainSync { recording?.stop() }
            assertTrue("Test movie finalizes", finalized.await(15, TimeUnit.SECONDS))
            assertFalse("Movie finalization error=${result.get()?.error}", requireNotNull(result.get()).hasError())
            recording = null
            assertTrue(movie.length() > 0)
            assertEquals("Stopping video preserves the graph", withRecorder,
                DriveCameraGraphPlan.resolve(false, false, withRecorder))
            frames.set(CountDownLatch(5))
            expectFrames("TSR after movie finalization")
        } finally {
            instrumentation.runOnMainSync {
                recording?.stop()
                analysis.clearAnalyzer()
                provider.unbind(*attached.toTypedArray())
            }
            if (recording != null) finalized.await(5, TimeUnit.SECONDS)
            scenario.close()
            frameExecutor.shutdownNow()
            movie.delete()
        }
    }
}

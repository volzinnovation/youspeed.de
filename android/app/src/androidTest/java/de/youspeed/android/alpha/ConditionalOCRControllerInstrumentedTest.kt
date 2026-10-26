package de.youspeed.android.alpha

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class ConditionalOCRControllerInstrumentedTest {
    @Test fun positivePlateWithdrawsOnlyItsParentWhilePendingAndFailedOcrKeepPrimary() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        val name = "ocr-controller-${UUID.randomUUID()}"
        val root = File(context.cacheDir, name).apply { mkdirs() }
        lateinit var controller: ConsumerSessionController
        instrumentation.runOnMainSync {
            controller = ConsumerSessionController(context, root, context.getSharedPreferences(name, Context.MODE_PRIVATE),
                Clock.systemUTC(), launchScreenshotState = AppScreenshotState.CAMERA_LIMIT_ACTIVE)
            field("isDriving").setBoolean(controller, true)
            field("trafficSignDriveSessionId").set(controller, name)
        }
        try {
            instrumentation.runOnMainSync {
                val generation = (field("trafficSignGeneration").get(controller) as TrafficSignWriteGate).get()
                val at = Instant.now()
                val box = NormalizedTrafficSignBoundingBox(.2, .2, .1, .1)
                val candidate = TrafficSignCandidate("maxspeed:30", "30", TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h"),
                    .99, null, box, trackId = "conditional-parent", evidenceFrames = 2)
                val event = TrafficSignRecognitionEvent(1, "test", "a".repeat(64), "test", TrafficSignInputSource.LIVE_FRAME,
                    at, TrafficSignRecognitionState.CONFIRMED, candidate, latencyMs = 0.0, thermalState = "nominal", frameId = "ocr", driveSessionId = name)
                val annotation = TrafficSignSupplementaryTextAnnotation("maxspeed:30", 30, "conditional-parent", "ocr", at, at,
                    "bei Nässe", null, TrafficSignSupplementaryOCRStatus.READ, box, generation = generation, driveSessionId = name)
                val runtime = field("speedReference").get(controller) as SpeedReferenceRuntime
                val bundle = ConsumerSessionController::class.java.getDeclaredMethod("updateBundledSpeedReference", String::class.java, SpeedReferenceValue::class.java).apply { isAccessible = true }
                fun seed(cameraId: String, voice: Boolean = false) {
                    runtime.reset(); runtime.context("101", "road", emptySet(), "forward", true)
                    bundle.invoke(controller, "independent-map", SpeedReferenceValue("numeric", 80))
                    runtime.camera(cameraId, SpeedReferenceValue("numeric", 30))
                    if (voice) runtime.voice("own-correction", SpeedReferenceValue("numeric", 70))
                }
                seed("conditional-parent")
                controller.onTrafficSignSupplementaryAuthority(event, annotation)
                assertEquals(80, runtime.output()?.value?.kmh)
                assertEquals("bundle", runtime.output()?.source)
                for (status in listOf(TrafficSignSupplementaryOCRStatus.NO_TEXT, TrafficSignSupplementaryOCRStatus.FAILED)) {
                    val unreadId = "unread-$status"
                    seed(unreadId)
                    controller.onTrafficSignSupplementaryAuthority(event.copy(candidate = candidate.copy(trackId = unreadId)),
                        annotation.copy(physicalSignId = unreadId, rawText = null, status = status))
                    assertEquals("A failed/empty actual read must not suppress its qualified primary", 30, runtime.output()?.value?.kmh)
                }
                seed("conditional-parent", voice = true)
                controller.onTrafficSignSupplementaryAuthority(event, annotation)
                assertEquals(70, runtime.output()?.value?.kmh)
                assertEquals("voice", runtime.output()?.source)
                assertFalse(runtime.cameraEvidenceIds().contains("conditional-parent"))
                seed("independent-camera")
                controller.onTrafficSignSupplementaryAuthority(event, annotation)
                assertEquals("independent-camera", runtime.output()?.evidenceId)
                seed("deferred-parent")
                val deferred = event.copy(candidate = candidate.copy(trackId = "deferred-parent", conditionState = TrafficSignConditionState.UNRESOLVED))
                controller.onTrafficSignUnverifiedAssembly(deferred, generation)
                assertEquals(80, runtime.output()?.value?.kmh)
                controller.onTrafficSignUnverifiedAssembly(deferred.copy(candidate = deferred.candidate!!.copy(conditionState = TrafficSignConditionState.NONE)), generation)
                assertEquals("A deferred plate cannot expire into an unconditional parent", 80, runtime.output()?.value?.kmh)
                seed("unrelated-bare")
                controller.onTrafficSignUnverifiedAssembly(event.copy(candidate = candidate.copy(trackId = "unrelated-bare")), generation)
                assertEquals("A bare primary never waits for lower-context inspection",30,runtime.output()?.value?.kmh)
            }
        } finally {
            instrumentation.runOnMainSync { controller.dispose() }
            context.deleteSharedPreferences(name)
            root.deleteRecursively()
        }
    }
    private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }
}

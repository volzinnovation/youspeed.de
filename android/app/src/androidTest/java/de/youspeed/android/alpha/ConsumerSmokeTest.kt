package de.youspeed.android.alpha

import android.content.Intent
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ConsumerSmokeTest {
    private val device: UiDevice = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())

    @Before
    fun prepareDevice() {
        dismissKeyguardAndSystemPanels()
    }

    @Test
    fun screenshotWarnState_coversSheetsAndLocalCaptureFlow() {
        launchApp(screenshotState = "warn-level-3")
        waitByRes("main-root", 20_000)
        waitByRes("primary-metric", 10_000)

        clickByRes("settings-button")
        waitByRes("settings-sheet", 10_000)
        device.pressBack()
        waitByRes("main-root", 10_000)

        clickByRes("city-badge")
        waitByRes("debug-sheet", 10_000)
        device.pressBack()
        waitByRes("main-root", 10_000)

        clickByRes("legal-button")
        waitByRes("legal-sheet", 10_000)
        device.pressBack()
        waitByRes("main-root", 10_000)

        // Reset into the deterministic screenshot fixture before local-capture coverage,
        // because sheet dismissal timing can leave the UIAutomator tree in a stale state.
        launchApp(screenshotState = "warn-level-3")
        waitByRes("main-root", 20_000)
        waitByRes("primary-metric", 10_000)

        doubleTapByRes("speed-sign")
        waitByRes("speed-capture-dialog", 10_000)
        if (device.hasObject(By.res(PACKAGE_NAME, "speed-capture-manual-button")) || device.hasObject(By.res("speed-capture-manual-button"))) {
            clickByRes("speed-capture-manual-button")
            waitByRes("speed-capture-input", 10_000)
        }
        setTextByRes("speed-capture-input", "80")
        clickByRes("speed-capture-save-button")
        waitUntilGoneByRes("speed-capture-dialog", 10_000)
    }

    @Test
    fun screenshotUnlimitedState_rendersAndSettingsRemainReachable() {
        launchApp(screenshotState = "autobahn-unlimited-above-130")
        waitByRes("main-root", 20_000)
        waitByRes("speed-sign", 10_000)
        clickByRes("settings-button")
        waitByRes("settings-sheet", 10_000)
    }

    @Test
    fun defaultLaunch_reachesKnownRootWithoutCrash() {
        launchApp(screenshotState = null)
        waitAnyByRes(listOf("startup-root", "welcome-root", "main-root"), 120_000)
    }

    private fun launchApp(screenshotState: String?) {
        val targetContext = InstrumentationRegistry.getInstrumentation().targetContext
        device.pressHome()
        val intent = Intent(Intent.ACTION_MAIN).apply {
            setClassName(PACKAGE_NAME, "$PACKAGE_NAME.MainActivity")
            addCategory(Intent.CATEGORY_LAUNCHER)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            screenshotState?.let { putExtra("screenshot_state", it) }
        }
        targetContext.startActivity(intent)
        val deadline = SystemClock.uptimeMillis() + 20_000
        while (SystemClock.uptimeMillis() < deadline) {
            if (device.hasObject(By.pkg(PACKAGE_NAME))) {
                device.waitForIdle()
                return
            }
            if (device.hasObject(By.pkg(PERMISSION_PACKAGE))) {
                allowRuntimePermissionIfPrompted()
                if (device.wait(Until.hasObject(By.pkg(PACKAGE_NAME)), 10_000)) {
                    device.waitForIdle()
                    return
                }
            }
            SystemClock.sleep(250)
        }
        throw AssertionError("App did not reach foreground package=$PACKAGE_NAME")
    }

    private fun clickByRes(tag: String) {
        waitByRes(tag, 10_000).click()
        device.waitForIdle()
    }

    private fun doubleTapByRes(tag: String) {
        val target = waitByRes(tag, 10_000)
        val bounds = target.visibleBounds
        val x = bounds.centerX()
        val y = bounds.centerY()
        device.click(x, y)
        SystemClock.sleep(90)
        device.click(x, y)
        device.waitForIdle()
    }

    private fun setTextByRes(tag: String, value: String) {
        val target = waitByRes(tag, 10_000)
        target.click()
        target.text = value
        device.waitForIdle()
    }

    private fun waitByRes(tag: String, timeoutMs: Long): UiObject2 {
        return waitObject(selectorsForTag(tag), timeoutMs)
    }

    private fun waitAnyByRes(tags: List<String>, timeoutMs: Long): UiObject2 {
        return waitObject(tags.flatMap(::selectorsForTag), timeoutMs)
    }

    private fun waitObject(selectors: List<BySelector>, timeoutMs: Long): UiObject2 {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            if (device.hasObject(By.pkg(PERMISSION_PACKAGE))) {
                allowRuntimePermissionIfPrompted()
            }
            for (selector in selectors) {
                val match = device.findObject(selector)
                if (match != null) {
                    return match
                }
            }
            SystemClock.sleep(250)
        }
        throw AssertionError("UI element not found for selectors: $selectors")
    }

    private fun waitUntilGoneByRes(tag: String, timeoutMs: Long) {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            if (selectorsForTag(tag).none(device::hasObject)) {
                return
            }
            SystemClock.sleep(250)
        }
        throw AssertionError("UI element still present for tag=$tag")
    }

    private fun selectorsForTag(tag: String): List<BySelector> {
        val selectors = mutableListOf(
            By.res(PACKAGE_NAME, tag),
            By.res(tag),
        )
        fallbackTextForTag(tag)?.let { selectors += By.text(it) }
        fallbackDescForTag(tag)?.let { selectors += By.desc(it) }
        return selectors
    }

    private fun fallbackTextForTag(tag: String): String? {
        return when (tag) {
            "settings-button" -> "Einstellungen"
            "legal-button" -> "Rechtliche Hinweise"
            "open-debug-button" -> "Debug-Informationen oeffnen"
            "speed-capture-save-button" -> "Speichern"
            else -> null
        }
    }

    private fun fallbackDescForTag(tag: String): String? {
        return when (tag) {
            "settings-button" -> "Einstellungen"
            "legal-button" -> "Rechtliche Hinweise"
            "local-recordings-button" -> "Lokale Erfassungen"
            else -> null
        }
    }

    private fun dismissKeyguardAndSystemPanels() {
        runCatching { device.wakeUp() }
        runCatching { device.pressMenu() }
        runCatching { device.pressHome() }
        device.waitForIdle()
    }

    private fun allowRuntimePermissionIfPrompted() {
        val selectors = listOf(
            By.res(PERMISSION_PACKAGE, "permission_allow_foreground_only_button"),
            By.res(PERMISSION_PACKAGE, "permission_allow_one_time_button"),
            By.res(PERMISSION_PACKAGE, "permission_allow_button"),
            By.res(PERMISSION_PACKAGE, "permission_allow_audio_only_button"),
            By.text("While using the app"),
            By.text("Allow only while using the app"),
            By.text("Allow"),
        )
        selectors.firstNotNullOfOrNull(device::findObject)?.click()
        device.waitForIdle()
    }

    companion object {
        private const val PACKAGE_NAME = "de.youspeed.android.alpha"
        private const val PERMISSION_PACKAGE = "com.google.android.permissioncontroller"
    }
}

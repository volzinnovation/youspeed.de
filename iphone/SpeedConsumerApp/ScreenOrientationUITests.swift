import XCTest

/// Opt in with --installed-app-ui-tests and this class's test identifier.
/// Uses real GPS/camera and preserves the driver's maps, queue, and preferences.
final class LiveDeviceRecordingUITests: XCTestCase {
    func testLocationAndRepeatedDashcamRecordingOnInstalledApp() throws {
#if targetEnvironment(simulator)
        throw XCTSkip("This smoke test requires the attached iPhone's camera and GPS.")
#else
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        func cancelExchangePrompt(_ alert: XCUIElement) -> Bool {
            let exchange = alert.staticTexts.matching(
                NSPredicate(format: "label CONTAINS[cd] 'Exchange'"))
            guard alert.label.localizedCaseInsensitiveContains("Exchange") || exchange.count > 0 else { return false }
            let cancel = alert.buttons["Abbrechen"].exists
                ? alert.buttons["Abbrechen"] : alert.buttons["Cancel"]
            guard cancel.exists else { return false }
            cancel.tap()
            return true
        }
        addUIInterruptionMonitor(withDescription: "Cancel unrelated Exchange reauthentication") { alert in
            cancelExchangePrompt(alert)
        }
        func openDashboard() {
            // iOS can fail to construct the automatic interruption query for
            // an existing account alert; address SpringBoard directly as well.
            let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
            for alert in springboard.alerts.allElementsBoundByIndex {
                _ = cancelExchangePrompt(alert)
            }
            let keep = app.buttons["startup.logs.keep"]
            let start = app.buttons["Start drive recording"]
            let ready = NSPredicate { _, _ in keep.exists || start.exists }
            expectation(for: ready, evaluatedWith: nil)
            waitForExpectations(timeout: 90)
            if keep.exists {
                keep.tap()
                // A system interruption may consume the first tap.
                if keep.exists { keep.tap() }
            }
            expectation(for: NSPredicate(format: "exists == true AND enabled == true"), evaluatedWith: start)
            waitForExpectations(timeout: 90)
        }
        app.launch()
        openDashboard()
        defer {
            let stop = app.buttons["Stop drive recording"]
            if app.state == .runningForeground && stop.exists && stop.isEnabled { stop.tap() }
        }
        for cycle in 1...3 {
            app.buttons["Start drive recording"].tap()
            let stop = app.buttons["Stop drive recording"]
            let contribution = app.navigationBars["Share detected signs"]
            expectation(for: NSPredicate { _, _ in stop.exists || contribution.exists }, evaluatedWith: nil)
            waitForExpectations(timeout: 30)
            if contribution.exists {
                // Recording does not require opting in to sign uploads.
                contribution.buttons["Close"].tap()
                // The asynchronously presented sheet may have intercepted the
                // start tap before it reached the dashboard.
                let start = app.buttons["Start drive recording"]
                if !stop.exists && start.exists && start.isHittable { start.tap() }
            }
            XCTAssertTrue(stop.waitForExistence(timeout: 30))
            // The combined SwiftUI module button does not consistently expose
            // accessibilityValue. Verify the actual recording-state indicator.
            let recording = app.descendants(matching: .any)
                .matching(NSPredicate(format: "label BEGINSWITH 'REC'")).firstMatch
            XCTAssertTrue(recording.waitForExistence(timeout: 30))
            Thread.sleep(forTimeInterval: 10)
            XCTAssertEqual(app.state, .runningForeground, "Recording must not crash the app")
            XCTAssertTrue(stop.isEnabled)
            XCTAssertTrue(recording.exists)
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = "physical-dashcam-recording-\(cycle)"
            attachment.lifetime = .keepAlways
            add(attachment)
            stop.tap()
            let start = app.buttons["Start drive recording"]
            expectation(for: NSPredicate(format: "exists == true AND enabled == true"), evaluatedWith: start)
            waitForExpectations(timeout: 45)
            if cycle == 1 {
                // Exercise the startup path again against the retained map/logs.
                app.terminate()
                app.launch()
                openDashboard()
            } else if cycle == 2 {
                XCUIDevice.shared.press(.home)
                app.activate()
                openDashboard()
            }
        }
#endif
    }
}

final class ScreenOrientationUITests: XCTestCase {
    func testPanoramaxCaptureButtonTogglesInEveryMountAndMatchesSettings() {
        continueAfterFailure = false
        for orientation in ["portrait", "landscape_camera_lower_right", "landscape_camera_upper_left"] {
            let app = XCUIApplication()
            app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
            app.launchArguments = ["-youspeed.screen_orientation", orientation,
                "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
            app.launch()
            let capture = app.buttons["dashboard.panoramaxCaptureButton"]
            XCTAssertTrue(capture.waitForExistence(timeout: 15))
            XCTAssertTrue(capture.isHittable)
            if (capture.value as? String) == "on" { capture.tap() }
            XCTAssertEqual(capture.label, "Start photo capture")
            XCTAssertEqual(capture.value as? String, "off")
            for state in ["off", "on", "off"] {
                if (capture.value as? String) != state { capture.tap() }
                XCTAssertEqual(capture.value as? String, state)
                let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                screenshot.name = "panoramax-capture-\(state)-\(orientation)"
                screenshot.lifetime = .keepAlways
                add(screenshot)
            }
            capture.tap()
            XCTAssertEqual(capture.label, "Stop photo capture")
            if orientation == "portrait" {
                app.buttons["dashboard.settingsButton"].tap()
                let preference = app.switches["Capture pictures"]
                for _ in 0..<24 where !preference.isHittable { app.swipeUp() }
                XCTAssertTrue(preference.waitForExistence(timeout: 5))
                XCTAssertEqual(preference.value as? String, "1")
                preference.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
                expectation(for: NSPredicate(format: "value == '0'"), evaluatedWith: preference)
                waitForExpectations(timeout: 5)
                app.buttons["subscreen.close"].tap()
                XCTAssertTrue(capture.waitForExistence(timeout: 5))
                XCTAssertEqual(capture.value as? String, "off")
            }
            app.terminate()
        }
    }

    func testSupplementaryOCRPlateDoesNotResizeOrMoveSpeedCircleAndTelemetry() {
        continueAfterFailure = false
        for orientation in ["portrait", "landscape_camera_lower_right"] {
            var baselineSign = CGRect.zero
            var baselineMetric = CGRect.zero
            for hasText in [false, true] {
                let app = XCUIApplication()
                app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
                if hasText {
                    app.launchEnvironment["YOUSPEED_SCREENSHOT_SUPPLEMENTARY_TEXT"] = "Mo-Fr\n6³⁰–17³⁰ h"
                }
                app.launchArguments = ["-youspeed.screen_orientation", orientation,
                                       "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
                app.launch()
                let sign = app.descendants(matching: .any)["dashboard.speedSignGeometry"]
                let metric = app.staticTexts["primary-metric"]
                XCTAssertTrue(sign.waitForExistence(timeout: 20))
                XCTAssertTrue(metric.exists)
                let plate = app.staticTexts["dashboard.speedSignSupplementaryText"]
                if hasText {
                    XCTAssertTrue(plate.exists)
                    XCTAssertEqual(plate.label, "Mo-Fr 6:30–17:30 h")
                    for (actual, expected) in [(sign.frame, baselineSign), (metric.frame, baselineMetric)] {
                        XCTAssertEqual(actual.minX, expected.minX, accuracy: 0.5)
                        XCTAssertEqual(actual.minY, expected.minY, accuracy: 0.5)
                        XCTAssertEqual(actual.width, expected.width, accuracy: 0.5)
                        XCTAssertEqual(actual.height, expected.height, accuracy: 0.5)
                    }
                    XCTAssertGreaterThanOrEqual(plate.frame.minY, sign.frame.maxY)
                    let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                    screenshot.name = "supplementary-plate-stable-\(orientation)"
                    screenshot.lifetime = .keepAlways
                    add(screenshot)
                } else {
                    XCTAssertFalse(plate.exists)
                    baselineSign = sign.frame
                    baselineMetric = metric.frame
                }
                app.terminate()
            }
        }
    }

    func testSwissPenaltyUsesTwoLargeLocalizedLines() {
        continueAfterFailure = false
        let labels: [(String, String, String, String)] = [
            ("de", "Monat Fahrverbot", "Monate Fahrverbot", "Prüfen"),
            ("fr", "mois d'interdiction", "mois d'interdiction", "À vérifier"),
            ("en", "month driving ban", "months driving ban", "Review"),
            ("nl", "maand rijverbod", "maanden rijverbod", "Controleren")
        ]
        for (language, singular, plural, review) in labels {
            let cases = [(50, 5, "residential", "40", "CHF"),
                         (120, 32, "motorway", "≥1", singular),
                         (30, 40, "residential", "24", plural),
                         (120, 32, "trunk", "!", review)]
            for (index, input) in cases.enumerated() {
                let app = XCUIApplication()
                app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "country-penalty"
                app.launchEnvironment["YOUSPEED_SCREENSHOT_COUNTRY"] = "CH"
                app.launchEnvironment["YOUSPEED_SCREENSHOT_LIMIT"] = String(input.0)
                app.launchEnvironment["YOUSPEED_SCREENSHOT_DELTA"] = String(input.1)
                app.launchEnvironment["YOUSPEED_SCREENSHOT_HIGHWAY"] = input.2
                app.launchEnvironment["YOUSPEED_SCREENSHOT_INSIDE_CITY"] = input.0 == 120 ? "0" : "1"
                app.launchArguments = ["-youspeed.screen_orientation", "portrait",
                                       "-AppleLanguages", "(\(language))", "-AppleLocale", "\(language)_CH"]
                app.launch()
                let primary = app.staticTexts["primary-metric"]
                let secondary = app.staticTexts["secondary-metric"]
                XCTAssertTrue(primary.waitForExistence(timeout: 20))
                XCTAssertEqual(primary.label, input.3)
                XCTAssertEqual(secondary.label, input.4)
                XCTAssertFalse(app.staticTexts["penalty-advisory-caption"].exists)
                let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                screenshot.name = "swiss-two-line-\(language)-\(index)"
                screenshot.lifetime = .keepAlways
                add(screenshot)
                app.terminate()
            }
        }
    }

    func testLaneOptionIsOffAtBottomOfDiagnostics() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "country-penalty"
        app.launchEnvironment["YOUSPEED_SCREENSHOT_COUNTRY"] = "CH"
        app.launchEnvironment["YOUSPEED_SCREENSHOT_LIMIT"] = "1"
        app.launchEnvironment["YOUSPEED_SCREENSHOT_DELTA"] = "0"
        app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        defer { app.terminate() }
        let settings = app.buttons["dashboard.settingsButton"]
        XCTAssertTrue(settings.waitForExistence(timeout: 20))
        settings.tap()
        let lanes = app.switches["show-detected-lanes-toggle"]
        let debug = app.buttons["Open debug information"]
        for _ in 0..<80 {
            XCTAssertFalse(lanes.exists, "Lane detection must not be in General Settings")
            if debug.exists && debug.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(debug.isHittable)
        debug.tap()
        for _ in 0..<40 {
            if lanes.exists && lanes.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(lanes.isHittable)
        XCTAssertEqual(lanes.value as? String, "0")
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "diagnostics-lanes-off"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    func testGravityOverlayRemainsVisibleAtDisplayedZeroWithoutNewGpsFix() {
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
        app.launchArguments = ["-youspeed.screen_orientation", "landscape_camera_lower_right"]
        app.launch()
        let overlay = app.descendants(matching: .any)["dashboard.gravityAlignment"]
        XCTAssertTrue(overlay.waitForExistence(timeout: 15))
        // The fixture never supplies another GPS fix. The mounting tool must
        // outlive the three-second freshness gate used by permission dialogs.
        Thread.sleep(forTimeInterval: 4)
        XCTAssertTrue(overlay.exists)
        XCTAssertLessThan(overlay.frame.width, app.windows.firstMatch.frame.width * 0.12)
        XCTAssertLessThan(overlay.frame.height, app.windows.firstMatch.frame.height * 0.12)
        app.terminate()
    }

    func testMovingDashboardHasNoButtonsOrGravityOverlay() {
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "warn-level-0"
        for mount in ["portrait", "landscape_camera_lower_right"] {
            app.launchArguments = ["-youspeed.screen_orientation", mount]
            app.launch()
            XCTAssertTrue(app.otherElements["dashboard.limitPane"].waitForExistence(timeout: 15))
            XCTAssertFalse(app.buttons["dashboard.settingsButton"].exists)
            XCTAssertFalse(app.buttons["dashboard.disregardVision"].exists)
            let photo = app.buttons["dashboard.photoButton"]
            XCTAssertTrue(photo.exists)
            XCTAssertFalse(photo.isEnabled, "Ordinary screenshot fixtures never start a camera")
            XCTAssertTrue(app.buttons.allElementsBoundByIndex.filter { $0.isHittable && $0.identifier != "dashboard.photoButton" }.isEmpty)
            XCTAssertFalse(app.descendants(matching: .any)["dashboard.gravityAlignment"].exists)
            app.terminate()
        }
    }

    func testLiveSettingsDismissalReopenAndNestedDebugNavigation() throws {
#if targetEnvironment(simulator)
        throw XCTSkip("The live Settings smoke test requires an installed map on a physical iPhone.")
#else
        continueAfterFailure = false
        let app = XCUIApplication()
        // Exercise the installed bundle and normal runtime. Do not enable the
        // screenshot fixture or seed/delete maps. Restore the driver's mount
        // after exercising all three orientation choices.
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        defer { app.terminate() }

        let settings = app.buttons["dashboard.settingsButton"]
        let keepLogs = app.buttons["startup.logs.keep"]
        let startupReady = NSPredicate { _, _ in settings.exists || keepLogs.exists }
        expectation(for: startupReady, evaluatedWith: nil)
        waitForExpectations(timeout: 60)
        if keepLogs.exists { keepLogs.tap() }
        XCTAssertTrue(settings.waitForExistence(timeout: 60),
                      "The live dashboard requires an installed map and completed onboarding.")
        let close = app.buttons["subscreen.close"]
        let settingsTitle = app.navigationBars["Settings"]
        let waitForDashboard = {
            let dismissed = NSPredicate { _, _ in settings.isHittable && !close.exists }
            self.expectation(for: dismissed, evaluatedWith: nil)
            self.waitForExpectations(timeout: 10)
        }

        // Repeated presentation must recover a usable dashboard each time.
        for pass in 0..<2 {
            settings.tap()
            XCTAssertTrue(settingsTitle.waitForExistence(timeout: 10))
            XCTAssertTrue(close.isHittable)
            if pass == 0 {
                let mounts = ["Portrait", "Landscape · camera lower right", "Landscape · camera upper left"]
                // Landscape has less vertical space, so later mount options
                // may need scrolling after the preceding orientation change.
                let revealMount: (String) -> XCUIElement = { name in
                    // Short drags avoid a full-screen flick skipping past the
                    // orientation section in the shallow landscape viewport.
                    let middle = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.55))
                    let lower = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.70))
                    for _ in 0..<12 where !app.buttons["Portrait"].isHittable {
                        middle.press(forDuration: 0.1, thenDragTo: lower)
                    }
                    let option = app.buttons[name]
                    for _ in 0..<12 where !option.isHittable {
                        lower.press(forDuration: 0.1, thenDragTo: middle)
                    }
                    return option
                }
                guard let originalMount = mounts.first(where: {
                    let button = revealMount($0)
                    return button.isSelected || (button.value as? String) == "1"
                }) else {
                    XCTFail("Cannot preserve the original mount: \(app.debugDescription)")
                    return
                }
                defer {
                    let original = revealMount(originalMount)
                    if original.isHittable { original.tap() }
                }
                for mount in mounts {
                    let option = revealMount(mount)
                    XCTAssertTrue(option.isHittable)
                    option.tap()
                    let settled = NSPredicate { _, _ in
                        let window = app.windows.firstMatch.frame
                        return mount == "Portrait"
                            ? window.height > window.width
                            : window.width > window.height
                    }
                    expectation(for: settled, evaluatedWith: nil)
                    waitForExpectations(timeout: 10)
                    XCTAssertTrue(close.isHittable)
                }
            }
            if pass == 1 {
                XCUIDevice.shared.press(.home)
                app.activate()
                XCTAssertTrue(settingsTitle.waitForExistence(timeout: 10))
                XCTAssertTrue(close.isHittable)
            }
            close.tap()
            waitForDashboard()
        }

        // Debug is pushed inside the Settings sheet. Its close control must
        // dismiss the entire sheet and permit another Settings presentation.
        settings.tap()
        XCTAssertTrue(settingsTitle.waitForExistence(timeout: 10))
        let debug = app.buttons["Open debug information"]
        for _ in 0..<24 {
            if debug.exists && debug.isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(debug.isHittable, "The Debug navigation entry must remain reachable.")
        debug.tap()
        XCTAssertTrue(app.navigationBars["Debug"].waitForExistence(timeout: 10))
        XCTAssertTrue(close.isHittable)
        let debugScreen = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        debugScreen.name = "live-settings-nested-debug"
        debugScreen.lifetime = .keepAlways
        add(debugScreen)
        close.tap()
        waitForDashboard()

        settings.tap()
        XCTAssertTrue(settingsTitle.waitForExistence(timeout: 10))
        XCTAssertFalse(app.navigationBars["Debug"].exists)
        close.tap()
        waitForDashboard()
#endif
    }

    func testDataManagerNavigationSelectionAndBackPreserveSelectedRegion() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
        app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let settings = app.buttons["dashboard.settingsButton"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["dashboard.calibrationButton"].exists)
        settings.tap()
        let managerLink = app.descendants(matching: .any).matching(identifier: "settings.dataManager").firstMatch
        XCTAssertTrue(managerLink.isHittable, "Data Manager is at the top of Settings without scrolling")
        managerLink.tap()
        let tabs = app.segmentedControls.firstMatch
        XCTAssertTrue(tabs.waitForExistence(timeout: 5))
        XCTAssertTrue(tabs.buttons["Map"].isSelected)
        tabs.buttons["List"].tap()
        let search = app.textFields["dataManager.search"]
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("Berlin")
        let berlin = app.buttons["dataManager.region.germany|berlin"]
        XCTAssertTrue(berlin.waitForExistence(timeout: 5))
        XCTAssertFalse(berlin.label.contains("Unknown"), "Missing metadata does not show placeholders")
        XCTAssertFalse(berlin.label.contains("Size:"), "Missing size is omitted")
        XCTAssertFalse(berlin.label.contains("Package date:"), "Missing date is omitted")
        berlin.tap()
        let download = app.buttons["dataManager.download"]
        for _ in 0..<5 where !download.isHittable { app.swipeUp() }
        XCTAssertTrue(download.isHittable)
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "Not installed")).firstMatch.exists)
        XCTAssertFalse(app.buttons["dataManager.delete"].exists)
        tabs.buttons["Map"].tap()
        XCTAssertTrue(app.staticTexts["Berlin"].waitForExistence(timeout: 5))
        tabs.buttons["List"].tap()
        XCTAssertTrue(app.buttons["dataManager.region.germany|berlin"].waitForExistence(timeout: 5))
        // Selecting never starts a download. Back returns to Settings and
        // reopening retains the selected ID on the long-lived view model.
        let backToSettings = app.navigationBars["Data Manager"].buttons["Settings"]
        XCTAssertTrue(backToSettings.isHittable)
        backToSettings.tap()
        XCTAssertTrue(managerLink.waitForExistence(timeout: 5))
        managerLink.tap()
        XCTAssertTrue(tabs.buttons["Map"].isSelected)
        XCTAssertTrue(app.staticTexts["Berlin"].waitForExistence(timeout: 5))
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "data-manager-berlin-selected"
        attachment.lifetime = .keepAlways
        add(attachment)
        app.buttons["subscreen.close"].tap()
        XCTAssertTrue(settings.waitForExistence(timeout: 5))
        settings.tap()
        let debug = app.buttons["Open debug information"]
        for _ in 0..<24 where !debug.isHittable { app.swipeUp() }
        XCTAssertTrue(debug.isHittable)
        debug.tap()
        let lanes = app.switches["show-detected-lanes-toggle"]
        for _ in 0..<24 where !lanes.isHittable { app.swipeUp() }
        XCTAssertTrue(lanes.isHittable, "Lane recognition settings remain available with Data Manager")
        app.terminate()
    }

    func testSecondarySignSpeechModeIsAvailableInSettings() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
        app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let settings = app.buttons["dashboard.settingsButton"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()
        let recognition = app.switches["Recognize speed signs"]
        for _ in 0..<24 where !recognition.isHittable { app.swipeUp() }
        XCTAssertTrue(recognition.isHittable)
        let initiallyEnabled = recognition.value as? String == "1"
        if !initiallyEnabled { recognition.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap() }
        let feedback = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Recognized traffic signs")).firstMatch
        for _ in 0..<24 where !feedback.isHittable { app.swipeUp() }
        XCTAssertTrue(feedback.isHittable)
        XCTAssertTrue(feedback.isEnabled)
        feedback.tap()
        XCTAssertTrue(app.buttons["Speed and other signs"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Notification sound"].exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "secondary-sign-speech-settings"
        attachment.lifetime = .keepAlways
        add(attachment)
        app.terminate()
        if !initiallyEnabled {
            app.launch()
            XCTAssertTrue(settings.waitForExistence(timeout: 15))
            settings.tap()
            for _ in 0..<24 where !recognition.isHittable { app.swipeUp() }
            recognition.coordinate(withNormalizedOffset: CGVector(dx: 0.92, dy: 0.5)).tap()
        }
        app.terminate()
    }

    func testSettingsCanChangeManualMountWithSheetOpen() {
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
        app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let settings = app.buttons["Settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        settings.tap()
        let lowerRight = app.buttons["Landscape · camera lower right"]
        XCTAssertTrue(lowerRight.waitForExistence(timeout: 5))
        lowerRight.tap()
        let wideWindow = NSPredicate { _, _ in app.windows.firstMatch.frame.width > app.windows.firstMatch.frame.height }
        expectation(for: wideWindow, evaluatedWith: nil)
        waitForExpectations(timeout: 10)
        let upperLeft = app.buttons["Landscape · camera upper left"]
        XCTAssertTrue(upperLeft.isHittable)
        upperLeft.tap()
        // A 180-degree scene rotation passes through transitional window bounds.
        expectation(for: wideWindow, evaluatedWith: nil)
        waitForExpectations(timeout: 10)
        let settingsScreenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        settingsScreenshot.name = "settings-landscape-camera-upper-left"
        settingsScreenshot.lifetime = .keepAlways
        add(settingsScreenshot)
        XCTAssertTrue(app.buttons["subscreen.close"].isHittable)
        let portrait = app.buttons["Portrait"]
        XCTAssertTrue(portrait.isHittable)
        portrait.tap()
        let tallWindow = NSPredicate { _, _ in app.windows.firstMatch.frame.height > app.windows.firstMatch.frame.width }
        expectation(for: tallWindow, evaluatedWith: nil)
        waitForExpectations(timeout: 10)
        let close = app.buttons["subscreen.close"]
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(settings.waitForExistence(timeout: 5))
        XCTAssertFalse(close.exists)
        app.terminate()
    }

    func testManualMountsKeepReadableDashboardPaneOrder() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
        for mount in ["portrait", "landscape_camera_lower_right", "landscape_camera_upper_left"] {
            for dashcam in [false, true] {
                app.launchEnvironment["YOUSPEED_SCREENSHOT_DASHCAM"] = dashcam ? "1" : nil
                app.launchArguments = ["-youspeed.screen_orientation", mount, "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
                app.launch()
                let caseName = "\(mount)-\(dashcam ? "dashcam" : "telemetry")"
                let sign = app.otherElements["dashboard.limitPane"]
                let workspace = app.otherElements["dashboard.workspacePane"]
                let settings = app.buttons["dashboard.settingsButton"]
                XCTAssertTrue(sign.waitForExistence(timeout: 15))
                XCTAssertTrue(workspace.waitForExistence(timeout: 5))
                XCTAssertTrue(settings.waitForExistence(timeout: 5))
                let landscape = mount != "portrait"
                let settled = NSPredicate { _, _ in
                    if landscape {
                        return sign.frame.maxX <= workspace.frame.minX
                            && abs(sign.frame.midY - workspace.frame.midY) < 2
                    }
                    // Accessibility exposes the workspace's content bounds,
                    // which exclude the full-width pane's horizontal padding.
                    return sign.frame.maxY <= workspace.frame.minY
                        && abs(sign.frame.midX - workspace.frame.midX) < 2
                        && workspace.frame.width >= app.windows.firstMatch.frame.width * 0.8
                }
                expectation(for: settled, evaluatedWith: nil)
                waitForExpectations(timeout: 10)
                let screen = app.windows.firstMatch.frame
                XCTAssertGreaterThan(sign.frame.width, 100)
                XCTAssertGreaterThan(workspace.frame.height, 100)
                XCTAssertGreaterThanOrEqual(sign.frame.minX, screen.minX)
                XCTAssertGreaterThanOrEqual(sign.frame.minY, screen.minY)
                XCTAssertLessThanOrEqual(workspace.frame.maxX, screen.maxX + 1)
                XCTAssertLessThanOrEqual(workspace.frame.maxY, screen.maxY + 1)
                let buttons = app.buttons.allElementsBoundByIndex.filter { $0.isHittable }
                XCTAssertGreaterThanOrEqual(buttons.count, 4)
                for (index, button) in buttons.enumerated() {
                    XCTAssertGreaterThanOrEqual(button.frame.minX, screen.minX - 1)
                    XCTAssertLessThanOrEqual(button.frame.maxX, screen.maxX + 1)
                    XCTAssertLessThanOrEqual(button.frame.maxY, screen.maxY + 1)
                    for other in buttons.dropFirst(index + 1) {
                        XCTAssertFalse(button.frame.intersects(other.frame), "Dashboard buttons overlap: \(caseName)")
                    }
                }
                // Portrait's upper controls precede the workspace, so only the
                // bottom row limits the space available for its content.
                let bottomControls = buttons.filter { abs($0.frame.midY - settings.frame.midY) < 2 }
                XCTAssertGreaterThanOrEqual(bottomControls.count, 4)
                let bottomControlsTop = bottomControls.map { $0.frame.minY }.min() ?? settings.frame.minY
                let assertLabelClearance = {
                    for label in workspace.staticTexts.allElementsBoundByIndex where label.isHittable {
                        XCTAssertLessThanOrEqual(label.frame.maxY, bottomControlsTop + 1,
                                                 "Workspace label overlaps bottom controls: \(caseName), \(label.label)")
                    }
                }
                let attachDashboard = { (name: String) in
                    let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                    screenshot.name = "manual-\(name)"
                    screenshot.lifetime = .keepAlways
                    self.add(screenshot)
                    let hierarchy = XCTAttachment(string: app.debugDescription)
                    hierarchy.name = "hierarchy-\(name)"
                    hierarchy.lifetime = .keepAlways
                    self.add(hierarchy)
                }
                attachDashboard(caseName)
                let city = workspace.staticTexts["Bad Herrenalb"]
                assertLabelClearance()
                if !dashcam {
                    XCTAssertTrue(city.waitForExistence(timeout: 5))
                    XCTAssertTrue(city.isHittable)
                    XCTAssertLessThanOrEqual(city.frame.maxY, bottomControlsTop + 1)
                }
                // Moving the simulator must not change the driver's saved mount.
                XCUIDevice.shared.orientation = landscape ? .portrait : .landscapeLeft
                XCTAssertTrue(settled.evaluate(with: nil))
                if dashcam {
                    let preview = app.descendants(matching: .any).matching(identifier: "dashboard.dashcamPreview").firstMatch
                    let recorderStatus = app.descendants(matching: .any).matching(identifier: "dashboard.recorderStatus").firstMatch
                    XCTAssertTrue(preview.waitForExistence(timeout: 5))
                    XCTAssertTrue(recorderStatus.waitForExistence(timeout: 5))
                    XCTAssertTrue(preview.isHittable)
                    XCTAssertGreaterThan(preview.frame.height, 100)
                    XCTAssertLessThanOrEqual(preview.frame.maxY, bottomControlsTop + 1)
                    if landscape {
                        XCTAssertGreaterThanOrEqual(preview.frame.minY, recorderStatus.frame.maxY - 1)
                    } else {
                        XCTAssertLessThanOrEqual(preview.frame.maxY, recorderStatus.frame.minY + 1)
                    }
                    attachDashboard(caseName)
                    preview.tap()
                    XCTAssertTrue(city.waitForExistence(timeout: 5))
                    XCTAssertTrue(city.isHittable)
                    XCTAssertLessThanOrEqual(city.frame.maxY, bottomControlsTop + 1)
                    XCTAssertTrue(recorderStatus.exists)
                    assertLabelClearance()
                    attachDashboard("\(caseName)-telemetry")
                } else {
                    attachDashboard(caseName)
                }
                app.terminate()
            }
        }
        XCUIDevice.shared.orientation = .portrait
    }

    func testSecondaryTrafficSignAlignsWithSpeedSignAndEyeInEveryManualOrientation() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "traffic-sign-pictogram"
        app.launchEnvironment["YOUSPEED_SCREENSHOT_SIGNS"] = "give_way"

        for mount in ["portrait", "landscape_camera_lower_right", "landscape_camera_upper_left"] {
            app.launchArguments = ["-youspeed.screen_orientation", mount, "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
            app.launch()

            let pane = app.otherElements["dashboard.limitPane"]
            let speedSign = app.descendants(matching: .any)
                .matching(identifier: "dashboard.speedSignGeometry").firstMatch
            let pictogram = app.descendants(matching: .any)
                .matching(identifier: "dashboard.trafficSignPictogram").firstMatch
            XCTAssertTrue(pane.waitForExistence(timeout: 15))
            XCTAssertTrue(speedSign.waitForExistence(timeout: 15))
            XCTAssertTrue(pictogram.waitForExistence(timeout: 15))

            let settled = NSPredicate { _, _ in
                return abs(pictogram.frame.minY - speedSign.frame.minY) < 2
            }
            expectation(for: settled, evaluatedWith: nil)
            waitForExpectations(timeout: 10)

            let landscape = mount != "portrait"
            // In landscape the eye canvas is expanded through the horizontal
            // safe area, placing its tip at the pane's leading edge. Portrait
            // keeps the control-radius inset used by the eye renderer.
            let expectedEyeLeft = landscape ? pane.frame.minX : pane.frame.minX + 22
            XCTAssertEqual(pictogram.frame.minX, expectedEyeLeft, accuracy: 2)
            XCTAssertEqual(pictogram.frame.minY, speedSign.frame.minY, accuracy: 2)
            app.terminate()
        }
        XCUIDevice.shared.orientation = .portrait
    }
}


extension ScreenOrientationUITests {
    @objc func testPenaltyLookupBehindInfoInEveryIphoneLanguage() {
        continueAfterFailure = false
        for (language, disclaimer) in [
            ("en", "For information only. This is not legal advice."),
            ("de", "Nur zur Information. Dies ist keine Rechtsberatung."),
            ("fr", "À titre informatif uniquement. Ceci ne constitue pas un conseil juridique."),
            ("nl", "Alleen ter informatie. Dit is geen juridisch advies.")
        ] {
            let app = XCUIApplication()
            app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "country-penalty"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_COUNTRY"] = "NL"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_LIMIT"] = "1"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_DELTA"] = "0"
            app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(\(language))", "-AppleLocale", "\(language)_NL"]
            app.launch()
            let info = app.buttons["dashboard.infoButton"]
            XCTAssertTrue(info.waitForExistence(timeout: 20))
            info.tap()
            let lookup = app.buttons["penalty-documentation-button"]
            XCTAssertTrue(lookup.waitForExistence(timeout: 10))
            lookup.tap()
            let webView = app.webViews.firstMatch
            XCTAssertTrue(webView.waitForExistence(timeout: 15))
            XCTAssertTrue(webView.staticTexts[disclaimer].waitForExistence(timeout: 15))
            XCTAssertTrue(webView.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "37")).firstMatch.waitForExistence(timeout: 10), "The Dutch table must load from its JSON")
            let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            image.name = "penalty-documentation-\(language)"; image.lifetime = .keepAlways; add(image)
            app.terminate()
        }
    }
}

extension ScreenOrientationUITests {
    @objc func testTrafficSignReferenceBehindInfoInAllFourLanguages() {
        continueAfterFailure = false
        for language in ["en", "fr", "de", "nl"] {
            let app = XCUIApplication()
            app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "country-penalty"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_COUNTRY"] = "NL"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_LIMIT"] = "1"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_DELTA"] = "0"
            app.launchArguments = ["-AppleLanguages", "(\(language))", "-AppleLocale", "\(language)_NL"]
            app.launch()
            let info = app.buttons["dashboard.infoButton"]
            XCTAssertTrue(info.waitForExistence(timeout: 20)); info.tap()
            let reference = app.buttons["traffic-sign-documentation-button"]
            XCTAssertTrue(reference.waitForExistence(timeout: 10)); reference.tap()
            let webView = app.webViews.firstMatch
            let search = webView.searchFields.firstMatch
            XCTAssertTrue(search.waitForExistence(timeout: 20)); search.tap(); search.typeText("B07\n"); webView.swipeUp()
            XCTAssertTrue(webView.staticTexts["B07"].waitForExistence(timeout: 10))
            XCTAssertTrue(webView.images.firstMatch.exists)
            var previousY: CGFloat = -1
            for label in ["English", "Français", "Deutsch", "Nederlands"] {
                let entry = webView.staticTexts[label].firstMatch
                XCTAssertTrue(entry.exists)
                XCTAssertGreaterThan(entry.frame.minY, previousY)
                previousY = entry.frame.minY
            }
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = "traffic-sign-reference-\(language)"; attachment.lifetime = .keepAlways; add(attachment)
            app.terminate()
        }
    }
}


extension ScreenOrientationUITests {
    @objc func testCaptureCountryReferenceScreenshots() {
        continueAfterFailure = false
        let fineCountries = ["DEU", "FRA", "CHE", "BEL", "NLD", "GBR", "LUX", "LIE", "MCO", "ROU", "SWE", "ISL"]
        for (language, storeLocale) in [("en", "en-US"), ("fr", "fr-FR"), ("de", "de-DE"), ("nl", "nl-NL")] {
            for (kind, countries) in [("signs", ["DE", "FR", "NL", "BE", "CH"]), ("penalties", fineCountries)] {
                for country in countries {
                    let app = XCUIApplication()
                    app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "country-penalty"
                    app.launchEnvironment["YOUSPEED_SCREENSHOT_COUNTRY"] = "NL"
                    app.launchEnvironment["YOUSPEED_SCREENSHOT_LIMIT"] = "1"
                    app.launchEnvironment["YOUSPEED_SCREENSHOT_DELTA"] = "0"
                    app.launchEnvironment["YOUSPEED_SCREENSHOT_REFERENCE_COUNTRY"] = country
                    app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(\(language))", "-AppleLocale", "\(language)_NL"]
                    app.launch()
                    let info = app.buttons["dashboard.infoButton"]
                    XCTAssertTrue(info.waitForExistence(timeout: 20)); info.tap()
                    let button = app.buttons[kind == "signs" ? "traffic-sign-documentation-button" : "penalty-documentation-button"]
                    XCTAssertTrue(button.waitForExistence(timeout: 10)); button.tap()
                    let view = app.webViews.firstMatch
                    XCTAssertTrue(view.waitForExistence(timeout: 20))
                    if kind == "signs" { XCTAssertTrue(view.images.firstMatch.waitForExistence(timeout: 20)) }
                    else {
                        let disclaimers = ["en": "For information only. This is not legal advice.", "fr": "À titre informatif uniquement. Ceci ne constitue pas un conseil juridique.", "de": "Nur zur Information. Dies ist keine Rechtsberatung.", "nl": "Alleen ter informatie. Dit is geen juridisch advies."]
                        XCTAssertTrue(view.staticTexts[disclaimers[language]!].waitForExistence(timeout: 20))
                    }
                    view.swipeUp()
                    let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                    image.name = "reference-\(storeLocale)-\(kind)-\(country)"; image.lifetime = .keepAlways; add(image)
                    app.terminate()
                }
            }
        }
    }
    @objc func testCapturePenaltyStoreScreenshots() {
        continueAfterFailure = false
        for (language, storeLocale) in [("en", "en-US"), ("fr", "fr-FR"), ("de", "de-DE"), ("nl", "nl-NL")] {
            let app = XCUIApplication()
            app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "country-penalty"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_COUNTRY"] = "NL"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_LIMIT"] = "1"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_DELTA"] = "0"
            app.launchEnvironment["YOUSPEED_SCREENSHOT_REFERENCE_COUNTRY"] = "NLD"
            app.launchArguments = ["-youspeed.screen_orientation", "portrait", "-AppleLanguages", "(\(language))", "-AppleLocale", "\(language)_NL"]
            app.launch()
            let info = app.buttons["dashboard.infoButton"]
            XCTAssertTrue(info.waitForExistence(timeout: 20)); info.tap()
            let button = app.buttons["penalty-documentation-button"]
            XCTAssertTrue(button.waitForExistence(timeout: 10)); button.tap()
            let view = app.webViews.firstMatch
            XCTAssertTrue(view.waitForExistence(timeout: 20))
            let disclaimers = ["en": "For information only. This is not legal advice.", "fr": "À titre informatif uniquement. Ceci ne constitue pas un conseil juridique.", "de": "Nur zur Information. Dies ist keine Rechtsberatung.", "nl": "Alleen ter informatie. Dit is geen juridisch advies."]
            XCTAssertTrue(view.staticTexts[disclaimers[language]!].waitForExistence(timeout: 20))
            let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            image.name = "reference-store-\(storeLocale)-penalties-NLD"
            image.lifetime = .keepAlways; add(image)
            app.terminate()
        }
    }

}


extension ScreenOrientationUITests {
    func testDrivingPhotoButtonLayoutAndManualCapture() throws {
#if !targetEnvironment(simulator)
        throw XCTSkip("Manual photo UI fixtures are simulator-only and never access a physical camera.")
#else
        continueAfterFailure = false
        for orientation in ["portrait", "landscape_camera_lower_right", "landscape_camera_upper_left"] {
            let app = drivingPhotoApp(speed: "30", orientation: orientation, camera: "ready")
            app.launch()
            let photo = app.buttons["dashboard.photoButton"]
            XCTAssertTrue(photo.waitForExistence(timeout: 20))
            expectation(for: NSPredicate(format: "enabled == true AND hittable == true"), evaluatedWith: photo)
            waitForExpectations(timeout: 10)
            assertDrivingPhotoLowerRight(photo, in: app)
            XCTAssertFalse(app.buttons["dashboard.settingsButton"].exists)
            XCTAssertEqual(app.buttons.allElementsBoundByIndex.filter { $0.isHittable && $0.isEnabled }.count, 1)
            XCTAssertEqual(photo.value as? String, "0")
            photo.doubleTap()
            expectation(for: NSPredicate(format: "value == '1'"), evaluatedWith: photo)
            waitForExpectations(timeout: 10)
            XCTAssertEqual(photo.value as? String, "1", "Repeated taps during capture save only one JPEG")
            XCTAssertFalse(app.alerts.firstMatch.exists)
            expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: photo)
            waitForExpectations(timeout: 5)
            photo.tap()
            expectation(for: NSPredicate(format: "value == '2'"), evaluatedWith: photo)
            waitForExpectations(timeout: 10)
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = "driving-photo-\(orientation)"
            attachment.lifetime = .keepAlways
            add(attachment)
            app.terminate()
        }
#endif
    }

    func testDrivingPhotoThresholdAndDisabledCamera() throws {
#if !targetEnvironment(simulator)
        throw XCTSkip("Manual photo UI fixtures are simulator-only.")
#else
        continueAfterFailure = false
        for orientation in ["portrait", "landscape_camera_lower_right", "landscape_camera_upper_left"] {
            var settingsSlot: CGRect?
            for speed in ["1", "1.01", "3.99", "4", "20", "20.01"] {
                let app = drivingPhotoApp(speed: speed, orientation: orientation, camera: "unavailable")
                if orientation == "landscape_camera_upper_left" {
                    app.launchArguments += ["-AppleLanguages", "(ar)", "-AppleLocale", "ar_SA", "-AppleTextDirection", "YES", "-NSForceRightToLeftWritingDirection", "YES"]
                }
                app.launch()
                XCTAssertTrue(app.otherElements["dashboard.limitPane"].waitForExistence(timeout: 20))
                let photo = app.buttons["dashboard.photoButton"]
                let moving = (Double(speed) ?? 0) >= 4
                XCTAssertEqual(photo.exists, moving)
                let settings = app.buttons["dashboard.settingsButton"]
                XCTAssertEqual(settings.exists, !moving)
                if settings.exists { settingsSlot = settings.frame }
                if moving {
                    XCTAssertFalse(photo.isEnabled)
                    assertDrivingPhotoLowerRight(photo, in: app)
                    let info = app.buttons["dashboard.infoButton"]
                    XCTAssertEqual(info.exists, (Double(speed) ?? 0) <= 20)
                    let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
                    screenshot.name = "photo-slot-\(orientation)-\(speed)"
                    screenshot.lifetime = .keepAlways
                    add(screenshot)
                    if info.exists {
                        // Wrapped buttons expose their icon glyph bounds; the shutter
                        // exposes its full 44pt target. Compare centers, not glyph edges.
                        XCTAssertEqual(photo.frame.midY, info.frame.midY, accuracy: 2.5,
                            "Shutter shares the current action-row center")
                    }
                    if let slot = settingsSlot {
                        XCTAssertEqual(photo.frame.midX, slot.midX, accuracy: 2.5, "Shutter uses the Settings slot")
                    }
                    photo.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
                    XCTAssertFalse(app.alerts.firstMatch.exists)
                    XCTAssertEqual(photo.value as? String, "0")
                }
                app.terminate()
            }
        }
#endif
    }

    private func drivingPhotoApp(speed: String, orientation: String, camera: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "warn-level-0"
        app.launchEnvironment["YOUSPEED_MANUAL_PHOTO_TEST"] = camera
        app.launchEnvironment["YOUSPEED_MANUAL_PHOTO_SPEED"] = speed
        app.launchArguments = ["-youspeed.screen_orientation", orientation,
                               "-youspeed.drive_recorder.panoramax_enabled", "NO",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        return app
    }

    private func assertDrivingPhotoLowerRight(_ photo: XCUIElement, in app: XCUIApplication,
                                              file: StaticString = #filePath, line: UInt = #line) {
        let safeArea = app.descendants(matching: .any)["dashboard.safeAreaGeometry"]
        XCTAssertTrue(safeArea.exists, file: file, line: line)
        let safeFrame = safeArea.frame
        let frame = photo.frame
        XCTAssertGreaterThanOrEqual(frame.width, 44, file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.height, 44, file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.minX, safeFrame.minX, file: file, line: line)
        XCTAssertGreaterThanOrEqual(frame.minY, safeFrame.minY, file: file, line: line)
        XCTAssertLessThanOrEqual(frame.maxX, safeFrame.maxX, file: file, line: line)
        XCTAssertLessThanOrEqual(frame.maxY, safeFrame.maxY, file: file, line: line)
        XCTAssertLessThan(safeFrame.maxX - frame.maxX, 40, file: file, line: line)
        XCTAssertLessThan(safeFrame.maxY - frame.maxY, 40, file: file, line: line)
    }
}

/// TestFlight feedback regressions run in the isolated .TestHost container.
final class TestFlightFeedbackUITests: XCTestCase {
    func testDashcamOnboardingLocalizesBackAndShowsTheRecordingControl() {
        continueAfterFailure = false
        for (language, backLabel) in [("de", "Zurück"), ("en", "Back"), ("fr", "Retour"), ("nl", "Terug")] {
            let app = XCUIApplication()
            app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "warn-level-0"
            app.launchEnvironment["YOUSPEED_ONBOARDING_SCREENSHOT_STEP"] = "2"
            app.launchArguments = ["-AppleLanguages", "(\(language))", "-AppleLocale", language,
                                   "-youspeed.screen_orientation", "portrait"]
            app.launch()
            let back = app.buttons["onboarding.back"]
            XCTAssertTrue(back.waitForExistence(timeout: 15))
            XCTAssertEqual(back.label, backLabel)
            XCTAssertTrue(back.isHittable)
            let reference = app.buttons["onboarding.screenshot.onboarding-record-control"]
            for _ in 0..<5 where !reference.isHittable { app.swipeUp() }
            XCTAssertTrue(reference.isHittable, "The guide must show how to start recording")
            reference.tap()
            XCTAssertTrue(app.buttons["subscreen.close"].waitForExistence(timeout: 5))
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = "onboarding-record-control-\(language)"
            attachment.lifetime = .keepAlways
            add(attachment)
            app.buttons["subscreen.close"].tap()
            back.tap()
            XCTAssertTrue(app.buttons["onboarding.next"].exists)
            XCTAssertEqual(back.label, backLabel)
            app.terminate()
        }
    }
}

import XCTest

final class ScreenOrientationUITests: XCTestCase {
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
            XCTAssertTrue(app.buttons.allElementsBoundByIndex.filter { $0.isHittable }.isEmpty)
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
                guard let originalMount = mounts.first(where: {
                    let button = app.buttons[$0]
                    return button.isSelected || (button.value as? String) == "1"
                }) else {
                    XCTFail("Cannot preserve the original mount: \(app.debugDescription)")
                    return
                }
                defer {
                    let original = app.buttons[originalMount]
                    if original.isHittable { original.tap() }
                }
                for mount in mounts {
                    let option = app.buttons[mount]
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
        app.navigationBars.buttons.firstMatch.tap()
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

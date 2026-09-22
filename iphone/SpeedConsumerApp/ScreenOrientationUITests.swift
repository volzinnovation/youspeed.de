import XCTest

final class ScreenOrientationUITests: XCTestCase {
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

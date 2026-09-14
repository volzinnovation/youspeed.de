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
        let portrait = app.buttons["Portrait"]
        XCTAssertTrue(portrait.isHittable)
        portrait.tap()
        let tallWindow = NSPredicate { _, _ in app.windows.firstMatch.frame.height > app.windows.firstMatch.frame.width }
        expectation(for: tallWindow, evaluatedWith: nil)
        waitForExpectations(timeout: 10)
        app.terminate()
    }

    func testManualMountsKeepReadableDashboardPaneOrder() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["YOUSPEED_SCREENSHOT_STATE"] = "camera-limit-active"
        for mount in ["portrait", "landscape_camera_lower_right", "landscape_camera_upper_left"] {
            app.launchArguments = ["-youspeed.screen_orientation", mount, "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
            app.launch()
            let sign = app.otherElements["dashboard.limitPane"]
            let workspace = app.otherElements["dashboard.workspacePane"]
            XCTAssertTrue(sign.waitForExistence(timeout: 15))
            XCTAssertTrue(workspace.waitForExistence(timeout: 5))
            let landscape = mount != "portrait"
            let settled = NSPredicate { _, _ in
                landscape ? sign.frame.maxX <= workspace.frame.minX : sign.frame.maxY <= workspace.frame.minY
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
            let buttons = workspace.buttons.allElementsBoundByIndex.filter { $0.isHittable }
            XCTAssertGreaterThanOrEqual(buttons.count, 4)
            for (index, button) in buttons.enumerated() {
                XCTAssertGreaterThanOrEqual(button.frame.minX, workspace.frame.minX - 1)
                XCTAssertLessThanOrEqual(button.frame.maxX, workspace.frame.maxX + 1)
                XCTAssertLessThanOrEqual(button.frame.maxY, workspace.frame.maxY + 1)
                for other in buttons.dropFirst(index + 1) {
                    XCTAssertFalse(button.frame.intersects(other.frame), "Dashboard buttons overlap")
                }
            }
            for label in workspace.staticTexts.allElementsBoundByIndex where label.isHittable {
                XCTAssertLessThanOrEqual(label.frame.maxY, buttons.map { $0.frame.minY }.min() ?? workspace.frame.maxY)
            }
            // Moving the simulator must not change the driver's saved mount.
            XCUIDevice.shared.orientation = landscape ? .portrait : .landscapeLeft
            XCTAssertTrue(settled.evaluate(with: nil))
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = "manual-\(mount)"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "hierarchy-\(mount)"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            app.terminate()
        }
        XCUIDevice.shared.orientation = .portrait
    }
}

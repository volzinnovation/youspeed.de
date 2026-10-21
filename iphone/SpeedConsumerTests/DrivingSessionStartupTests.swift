import SwiftUI
import XCTest
@testable import SpeedConsumer

@MainActor
final class DrivingSessionStartupTests: XCTestCase {
    func testMountedDashboardStartsGPSWhenDelayedStartupBecomesReady() async throws {
        let model = DriveSessionViewModel()
        model.trafficSignRecognitionEnabled = false
        model.panoramaxCaptureEnabled = false
        await model.testPrepareDrivingStartup(ready: false)
        let started = expectation(description: "GPS starts after map and onboarding readiness")
        var startCount = 0
        model.testStartLocationUpdates = {
            startCount += 1
            started.fulfill()
        }
        let mounted = expectation(description: "dashboard mounted before readiness")
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
        window.rootViewController = UIHostingController(rootView: MainView(viewModel: model).environment(\.scenePhase, .active).onAppear { mounted.fulfill() })
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            model.testStartLocationUpdates = nil
            model.stopDriving()
        }
        // The dashboard appears before startup completes, as it can in the
        // mounted/safety branch of SpeedConsumerRootView. No GPS request yet.
        await fulfillment(of: [mounted], timeout: 5)
        XCTAssertEqual(startCount, 0)
        XCTAssertFalse(model.canStartDrivingFromDashboard)
        await model.testPrepareDrivingStartup(ready: true)
        await fulfillment(of: [started], timeout: 5)
        XCTAssertEqual(startCount, 1)
        XCTAssertEqual(model.driveStatus, "running")
        XCTAssertFalse(model.canStartDrivingFromDashboard)
        // Subsequent ready notifications must not restart a running drive.
        await model.testPrepareDrivingStartup(ready: true)
        await Task.yield()
        XCTAssertEqual(startCount, 1)
    }

    private final class Lifecycle: ObservableObject {
        @Published var phase = ScenePhase.background
    }

    private struct Dashboard: View {
        let model: DriveSessionViewModel
        @ObservedObject var lifecycle: Lifecycle
        var mounted: () -> Void
        var body: some View {
            MainView(viewModel: model)
                .environment(\.scenePhase, lifecycle.phase)
                .onAppear(perform: mounted)
        }
    }

    func testReadyDashboardWaitsForForegroundBeforeStartingGPS() async throws {
        let model = DriveSessionViewModel()
        model.trafficSignRecognitionEnabled = false
        model.panoramaxCaptureEnabled = false
        await model.testPrepareDrivingStartup(ready: true)
        let started = expectation(description: "GPS starts on foreground")
        let mounted = expectation(description: "dashboard mounted in background")
        var startCount = 0
        model.testStartLocationUpdates = { startCount += 1; started.fulfill() }
        let lifecycle = Lifecycle()
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
        window.rootViewController = UIHostingController(rootView: Dashboard(
            model: model, lifecycle: lifecycle, mounted: { mounted.fulfill() }))
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            model.testStartLocationUpdates = nil
            model.stopDriving()
        }
        await fulfillment(of: [mounted], timeout: 5)
        XCTAssertEqual(startCount, 0)
        lifecycle.phase = .active
        await fulfillment(of: [started], timeout: 5)
        XCTAssertEqual(startCount, 1)
    }

    func testStartupCannotBeginWithoutMapOrCompletedOnboarding() async {
        let model = DriveSessionViewModel()
        await model.testPrepareDrivingStartup(ready: false)
        XCTAssertFalse(model.canStartDrivingFromDashboard)
        await model.testPrepareDrivingStartup(ready: true, hasMap: false)
        XCTAssertFalse(model.canStartDrivingFromDashboard)
        await model.testPrepareDrivingStartup(ready: true, completed: false)
        XCTAssertFalse(model.canStartDrivingFromDashboard)
        await model.testPrepareDrivingStartup(ready: true)
        XCTAssertTrue(model.canStartDrivingFromDashboard)
    }
}

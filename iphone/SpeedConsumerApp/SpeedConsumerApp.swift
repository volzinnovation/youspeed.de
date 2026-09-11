import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

@main
struct SpeedConsumerApp: App {
    @UIApplicationDelegateAdaptor(SpeedConsumerAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var viewModel = DriveSessionViewModel()

    var body: some Scene {
        WindowGroup {
            Group {
                if viewModel.isScreenshotMode {
                    MainView(viewModel: viewModel)
                } else if viewModel.startupDataState != .ready || !viewModel.onboardingStateLoaded {
                    StartupView(viewModel: viewModel)
                } else if viewModel.shouldPresentOnboarding {
                    FirstUserWelcomeView(viewModel: viewModel)
                } else {
                    MainView(viewModel: viewModel)
                }
            }
            .onAppear { updateLifecycle(for: scenePhase) }
            .onChange(of: viewModel.hasOnboardingMap) { _, _ in
                viewModel.normalizeOnboardingState()
            }
        }
        .onChange(of: scenePhase) { _, newPhase in
            updateLifecycle(for: newPhase)
        }
    }

    private func updateLifecycle(for phase: ScenePhase) {
        if phase == .active { viewModel.refreshOnboardingLocationPermission() }
        viewModel.setTrafficSignApplicationActive(phase == .active)
        #if canImport(UIKit)
        UIApplication.shared.isIdleTimerDisabled = (phase == .active)
        #endif
    }
}

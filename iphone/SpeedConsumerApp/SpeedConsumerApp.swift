import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

@main
struct SpeedConsumerApp: App {
    @UIApplicationDelegateAdaptor(SpeedConsumerAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var viewModel = DriveSessionViewModel()
    @State private var dismissedWelcomeThisSession = false
    @State private var shouldOpenSettingsOnMainAppear = false

    var body: some Scene {
        WindowGroup {
            Group {
                if viewModel.isScreenshotMode {
                    MainView(viewModel: viewModel)
                } else if shouldPresentWelcome && !dismissedWelcomeThisSession {
                    FirstUserWelcomeView(viewModel: viewModel) {
                        openSettings in
                        dismissedWelcomeThisSession = true
                        shouldOpenSettingsOnMainAppear = openSettings
                    }
                } else if viewModel.startupDataState == .ready {
                    MainView(
                        viewModel: viewModel,
                        openSettingsOnAppear: shouldOpenSettingsOnMainAppear,
                        onOpenSettingsConsumed: {
                            shouldOpenSettingsOnMainAppear = false
                        }
                    )
                } else {
                    StartupView(viewModel: viewModel)
                }
            }
            .onAppear { updateIdleTimer(for: scenePhase) }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                dismissedWelcomeThisSession = false
            }
            updateIdleTimer(for: newPhase)
        }
    }

    private var shouldPresentWelcome: Bool {
        guard viewModel.startupDataState == .ready else {
            return false
        }
        if viewModel.hideWelcomeScreen {
            return false
        }
        return Self.requiresWelcome(bundleVersion: viewModel.activeBundleVersion, now: Date())
    }

    private func updateIdleTimer(for phase: ScenePhase) {
        #if canImport(UIKit)
        UIApplication.shared.isIdleTimerDisabled = (phase == .active)
        #endif
    }

    private static func requiresWelcome(bundleVersion: String, now: Date) -> Bool {
        let normalized = bundleVersion.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.isEmpty || normalized == "none" || normalized == "seed" {
            return true
        }
        guard let bundleDate = parseBundleDate(from: normalized) else {
            // If date cannot be parsed, force welcome so users can trigger an update.
            return true
        }
        let ageSeconds = now.timeIntervalSince(bundleDate)
        return ageSeconds > (30 * 24 * 60 * 60)
    }

    private static func parseBundleDate(from version: String) -> Date? {
        let dayFormatter = DateFormatter()
        dayFormatter.calendar = Calendar(identifier: .gregorian)
        dayFormatter.locale = Locale(identifier: "en_US_POSIX")
        dayFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        dayFormatter.dateFormat = "yyyy-MM-dd"

        if let range = version.range(of: #"\d{4}-\d{2}-\d{2}"#, options: .regularExpression),
           let date = dayFormatter.date(from: String(version[range])) {
            return date
        }

        let compactFormatter = DateFormatter()
        compactFormatter.calendar = Calendar(identifier: .gregorian)
        compactFormatter.locale = Locale(identifier: "en_US_POSIX")
        compactFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        compactFormatter.dateFormat = "yyyyMMdd"

        if let range = version.range(of: #"\d{8}"#, options: .regularExpression),
           let date = compactFormatter.date(from: String(version[range])) {
            return date
        }
        return nil
    }
}

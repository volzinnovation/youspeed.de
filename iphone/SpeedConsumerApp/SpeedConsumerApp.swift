import SwiftUI

@main
struct SpeedConsumerApp: App {
    @UIApplicationDelegateAdaptor(SpeedConsumerAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var viewModel = DriveSessionViewModel()
    @State private var dismissedWelcomeThisSession = false

    var body: some Scene {
        WindowGroup {
            if shouldPresentWelcome && !dismissedWelcomeThisSession {
                FirstUserWelcomeView(viewModel: viewModel) {
                    dismissedWelcomeThisSession = true
                }
            } else if viewModel.isDatabaseReadyForQueries {
                MainView(viewModel: viewModel)
            } else {
                StartupView(viewModel: viewModel)
            }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                dismissedWelcomeThisSession = false
            }
        }
    }

    private var shouldPresentWelcome: Bool {
        guard viewModel.startupDataState == .ready else {
            return false
        }
        return Self.requiresWelcome(bundleVersion: viewModel.activeBundleVersion, now: Date())
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

import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

@main
struct SpeedConsumerApp: App {
    @UIApplicationDelegateAdaptor(SpeedConsumerAppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            if isHostedUnitTest {
                Color.clear
                    .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
            } else {
#if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--trip-journal-preview") || ProcessInfo.processInfo.arguments.contains("--trip-journal-detail-preview") {
                    TripJournalPreviewRoot()
                } else { SpeedConsumerRootView() }
#else
                SpeedConsumerRootView()
#endif
            }
        }
    }

    private var isHostedUnitTest: Bool {
#if DEBUG
        return NSClassFromString("XCTestCase") != nil
#else
        return false
#endif
    }
}

private struct SpeedConsumerRootView: View {
    @Environment(\.scenePhase) private var scenePhase
    private let reviewPrompt = AppReviewPrompt.shared
    @StateObject private var viewModel = DriveSessionViewModel()
    @State private var showingStartupJournal = false
    @State private var startupJournalSettingsAfterDismiss = false
    @State private var showingStartupSettings = false

    var body: some View {
        Group {
            if viewModel.onboardingScreenshotStep != nil {
                FirstUserWelcomeView(viewModel: viewModel)
            } else if viewModel.startupLogReviewState != .complete {
                StartupLogReviewView(viewModel: viewModel)
            } else if viewModel.isScreenshotMode || !viewModel.drivingControlsAllowed ||
                (viewModel.startupDataState == .ready && viewModel.onboardingStateLoaded && !viewModel.shouldPresentOnboarding) {
                MainView(viewModel: viewModel)
            } else if viewModel.startupDataState != .ready || !viewModel.onboardingStateLoaded {
                StartupView(viewModel: viewModel)
            } else {
                FirstUserWelcomeView(viewModel: viewModel)
            }
        }
        .safeAreaInset(edge: .bottom) {
            if viewModel.startupLogReviewState == .complete, viewModel.startupDataState != .ready,
               TripJournal.shared.configured, viewModel.drivingControlsAllowed {
                Button { showingStartupJournal = true } label: {
                    Label(journalText("navigation"), systemImage: "point.topleft.down.to.point.bottomright.curvepath")
                        .frame(minHeight: 44)
                }.buttonStyle(.bordered).padding(.horizontal)
            }
        }
        .sheet(isPresented:$showingStartupJournal,onDismiss:{
            if startupJournalSettingsAfterDismiss {
                startupJournalSettingsAfterDismiss = false
                viewModel.setSettingsPresented(true); showingStartupSettings = true
            }
        }) {
            DismissibleNavigationSheet {
                TripJournalView(openSettings:{startupJournalSettingsAfterDismiss = true; showingStartupJournal = false})
            }
        }
        .sheet(isPresented:$showingStartupSettings,onDismiss:{viewModel.setSettingsPresented(false)}) {
            DismissibleNavigationSheet { SettingsView(viewModel:viewModel,account:viewModel.panoramaxAccount) }
        }
        .environment(\.driveInteraction, DriveInteraction(perform: viewModel.performDriveInteraction))
        .background(ManualOrientationSceneBridge(selection: viewModel.screenOrientation) { error in
            viewModel.screenOrientationError = error.localizedDescription
        })
        .disabled(viewModel.driveInteractionPending)
        .overlay(alignment: .top) {
            if viewModel.driveInteractionPending {
                Text(NSLocalizedString("drive_recorder.action.saving", comment: ""))
                    .font(.callout.weight(.semibold))
                    .padding(12)
                    .background(.regularMaterial, in: Capsule())
                    .accessibilityAddTraits(.updatesFrequently)
            }
        }
        .alert(NSLocalizedString("drive_recorder.action.failed_title", comment: ""), isPresented: Binding(
            get: { viewModel.driveInteractionError != nil && viewModel.drivingControlsAllowed },
            set: { if !$0 { viewModel.driveInteractionError = nil } }
        )) {
            Button(NSLocalizedString("common.done", comment: ""), role: .cancel) {}
        } message: {
            Text(viewModel.driveInteractionError ?? "")
        }
        .onAppear { updateLifecycle(for: scenePhase) }
        .onChange(of: viewModel.startupLogReviewState) { _, state in
            if state == .complete && scenePhase == .active { viewModel.startJournalDrivingUseIfAuthorized() }
        }
        .onChange(of: viewModel.hasOnboardingMap) { _, _ in
            viewModel.normalizeOnboardingState()
        }
        .onChange(of: scenePhase) { _, newPhase in
            updateLifecycle(for: newPhase)
        }
    }

    private func updateLifecycle(for phase: ScenePhase) {
        if phase != .active { viewModel.cancelPendingDriveInteraction() }
        if phase == .active { viewModel.refreshOnboardingLocationPermission() }
        // OS permission sheets use .inactive without suspending foreground recording.
        if phase == .background { TripJournal.shared.lifecycle(false) }
        if phase == .active { TripJournal.shared.lifecycle(true); viewModel.startJournalDrivingUseIfAuthorized() }
        viewModel.setTrafficSignApplicationActive(phase == .active)
        #if canImport(UIKit)
        UIApplication.shared.isIdleTimerDisabled = (phase == .active)
        #endif
    }
}

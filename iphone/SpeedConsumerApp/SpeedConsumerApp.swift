import SwiftUI

@main
struct SpeedConsumerApp: App {
    @UIApplicationDelegateAdaptor(SpeedConsumerAppDelegate.self) private var appDelegate
    @StateObject private var viewModel = DriveSessionViewModel()

    var body: some Scene {
        WindowGroup {
            if viewModel.isDatabaseReadyForQueries {
                MainView(viewModel: viewModel)
            } else {
                StartupView(viewModel: viewModel)
            }
        }
    }
}

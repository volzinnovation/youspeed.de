import SwiftUI

@main
struct SpeedConsumerApp: App {
    @UIApplicationDelegateAdaptor(SpeedConsumerAppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            MainView()
        }
    }
}

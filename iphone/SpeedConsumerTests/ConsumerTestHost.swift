import Foundation

/// Test fixtures may replace maps and journals. Never admit the historical
/// TestHost identifier on a phone: it is also used by an installed driver app.
enum ConsumerTestHost {
    static var isIsolated: Bool {
        let identifier = Bundle.main.bundleIdentifier
        if ["de.youspeed.SpeedConsumer.UnitTests", "de.youspeed.SpeedConsumer.CityLookupTests"].contains(identifier) {
            return true
        }
        #if targetEnvironment(simulator)
        return identifier == "de.youspeed.SpeedConsumer.TestHost"
        #else
        return false
        #endif
    }
}

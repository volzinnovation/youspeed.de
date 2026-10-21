import Foundation

/// Offline solar elevation using NOAA's general solar-position equations.
/// https://gml.noaa.gov/grad/solcalc/solareqns.PDF
/// An absolute UTC instant avoids local timezone and daylight-saving ambiguities.
enum SolarDaylight {
    static func elevationDegrees(latitude: Double, longitude: Double, at date: Date) -> Double? {
        guard latitude.isFinite, (-90...90).contains(latitude), longitude.isFinite,
              (-180...180).contains(longitude), date.timeIntervalSince1970.isFinite else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        guard let day = calendar.ordinality(of: .day, in: .year, for: date),
              let days = calendar.range(of: .day, in: .year, for: date)?.count else { return nil }
        let c = calendar.dateComponents([.hour, .minute, .second], from: date)
        let hours = Double(c.hour!) + Double(c.minute!) / 60 + Double(c.second!) / 3600
        let gamma = 2 * Double.pi / Double(days) * (Double(day - 1) + (hours - 12) / 24)
        let equation = 229.18 * (0.000075 + 0.001868 * cos(gamma) - 0.032077 * sin(gamma)
            - 0.014615 * cos(2 * gamma) - 0.040849 * sin(2 * gamma))
        let declination = 0.006918 - 0.399912 * cos(gamma) + 0.070257 * sin(gamma)
            - 0.006758 * cos(2 * gamma) + 0.000907 * sin(2 * gamma)
            - 0.002697 * cos(3 * gamma) + 0.00148 * sin(3 * gamma)
        let hourAngle = (hours * 60 + equation + 4 * longitude) / 4 - 180
        let lat = latitude * .pi / 180
        let sine = sin(lat) * sin(declination) + cos(lat) * cos(declination) * cos(hourAngle * .pi / 180)
        return asin(max(-1, min(1, sine))) * 180 / .pi
    }

    /// Standard sunrise/sunset horizon (solar disk and atmospheric refraction).
    /// Missing location evidence keeps camera TSR paused; road bundles still work.
    static func permitsCameraTSR(latitude: Double?, longitude: Double?, at date: Date) -> Bool {
        guard let latitude, let longitude,
              let elevation = elevationDegrees(latitude: latitude, longitude: longitude, at: date) else { return false }
        return elevation >= -0.833
    }
}

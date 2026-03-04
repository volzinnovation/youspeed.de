import SafariServices
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

private let speedLimitNumberScale: CGFloat = 0.5
private let secondaryTextRatio: CGFloat = 9.0 / 16.0
private let drivingBanPulseCycleSeconds: Double = 2.2

enum LegalDisclaimerText {
    static let short = "Hinweis: Angezeigte Bußgelder, Punkte und Fahrverbote sind unverbindliche Orientierung und keine Rechtsberatung. Maßgeblich sind amtliche Bescheide und die jeweils gültige Rechtslage."

    static let long = "Die in YouSpeed angezeigten Werte zu Bußgeld, Punkten und Fahrverbot dienen nur der unverbindlichen Orientierung. Sie stellen keine Rechtsberatung und keine verbindliche Rechtsauskunft dar. Maßgeblich sind ausschließlich amtliche Bescheide sowie die zum Tatzeitpunkt geltende Rechtslage; zusätzliche Gebühren und Auslagen können anfallen."
}

struct MainView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    var openSettingsOnAppear: Bool = false
    var onOpenSettingsConsumed: (() -> Void)?
    @State private var hasAutoTriggeredSyncForTests = false
    @State private var showingSettings = false
    @State private var showingLegalInfo = false
    @State private var showingDebug = false
    @State private var showingLocalRecordings = false

    var body: some View {
        GeometryReader { proxy in
            let minDimension = min(proxy.size.width, proxy.size.height)
            let screenInset = minDimension * 0.02
            let signSize = min(proxy.size.width * 0.74, proxy.size.width - (screenInset * 2))
            let primaryMetricFontSize = signSize * speedLimitNumberScale
            let topPadding = proxy.safeAreaInsets.top + screenInset
            let bottomPadding = proxy.safeAreaInsets.bottom + screenInset
            ZStack(alignment: .bottom) {
                screenBackgroundView
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    topCornerButtons
                        .padding(.horizontal, screenInset)
                        .padding(.top, topPadding)

                    SpeedLimitSignView(
                        limitText: limitText,
                        numberFontSize: primaryMetricFontSize,
                        showsTunnelIcon: shouldShowTunnelSignIcon
                    )
                        .frame(width: signSize, height: signSize)
                        .frame(maxWidth: .infinity)
                        .padding(.top, screenInset)
                        .padding(.horizontal, screenInset)
                        .contentShape(Rectangle())
                        .highPriorityGesture(
                            TapGesture(count: 2).onEnded {
                                viewModel.beginSpeedLimitCapture()
                            }
                        )

                    Spacer(minLength: 0)
                }

                mainStatusInfo(
                    signSize: signSize,
                    primaryFont: primaryMetricFontSize,
                    screenSize: proxy.size,
                    bottomPadding: bottomPadding
                )

                bugButton(bottomPadding: bottomPadding, horizontalPadding: screenInset)
            }
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack {
                SettingsView(viewModel: viewModel)
            }
        }
        .sheet(isPresented: $showingLegalInfo) {
            NavigationStack {
                LegalInformationView()
            }
        }
        .sheet(isPresented: $showingDebug) {
            NavigationStack {
                DebugInformationView(viewModel: viewModel)
            }
        }
        .sheet(isPresented: $showingLocalRecordings) {
            NavigationStack {
                LocalRecordingsView(viewModel: viewModel)
            }
        }
        .onAppear {
            if viewModel.driveStatus == "stopped" {
                viewModel.startDriving()
            }
            if openSettingsOnAppear && !showingSettings {
                showingSettings = true
                onOpenSettingsConsumed?()
            }
            guard shouldAutoTapSyncForTests, !hasAutoTriggeredSyncForTests else {
                return
            }
            hasAutoTriggeredSyncForTests = true
            print("SPEEDCONSUMER_TEST_AUTOTAP_SYNC triggered")
            viewModel.bootstrapAndSync()
        }
    }

    private func bugButton(bottomPadding: CGFloat, horizontalPadding: CGFloat) -> some View {
        VStack {
            Spacer()
            HStack {
                Button {
                    showingLegalInfo = true
                } label: {
                    Image(systemName: "info.circle.fill")
                        .font(.title3.weight(.semibold))
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .background(buttonBackgroundColor, in: Circle())
                .foregroundStyle(primaryForegroundColor)

                Spacer()
            }
            .padding(.leading, horizontalPadding)
            .padding(.bottom, bottomPadding + 4)
        }
    }

    private var topCornerButtons: some View {
        HStack {
            Button {
                showingLocalRecordings = true
            } label: {
                Image(systemName: "ladybug.fill")
                    .font(.title3.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(buttonBackgroundColor, in: Circle())

            Spacer()

            Button {
                showingSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.title3.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(buttonBackgroundColor, in: Circle())
        }
        .foregroundStyle(primaryForegroundColor)
    }

    @ViewBuilder
    private func mainStatusInfo(signSize: CGFloat, primaryFont: CGFloat, screenSize: CGSize, bottomPadding: CGFloat) -> some View {
        let minDimension = min(screenSize.width, screenSize.height)
        let horizontalPadding = max(12, screenSize.width * 0.04)
        let baseSecondaryFont = primaryFont * secondaryTextRatio
        let secondaryScale = sharedSecondaryScale(
            baseSecondaryFont: baseSecondaryFont,
            availableWidth: screenSize.width - (horizontalPadding * 2)
        )
        let secondaryFont = baseSecondaryFont * secondaryScale
        let valueUnitSpacing: CGFloat = 0
        let metricDebugGap = max(12, minDimension * 0.024)
        let debugFont = secondaryFont*0.6
        let debugSpacing = max(2, minDimension * 0.004)
        let metricBlockHeight = primaryFont + (secondaryFont * 0.9)
        let debugBlockHeight = (secondaryFont * 2.1) + debugSpacing
        let statusAreaHeight = max(220, metricBlockHeight + metricDebugGap + debugBlockHeight + bottomPadding)

        VStack(spacing: 0) {
            VStack(spacing: valueUnitSpacing) {
                if shouldShowTunnelCurrentSpeedIcon {
                    Image(systemName: "tunnel.fill")
                        .font(.system(size: primaryFont * 0.72, weight: .bold, design: .rounded))
                    Text("Tunnel")
                        .font(.system(size: secondaryFont, weight: .bold, design: .default))
                } else {
                    Text(primaryMetricText)
                        .font(primaryMetricFont(size: primaryFont))
                        .multilineTextAlignment(.center)
                        .minimumScaleFactor(0.45)
                        .lineLimit(viewModel.isInSpeedCaptureMode ? 2 : 1)
                    Text(secondaryMetricText)
                        .font(.system(size: secondaryFont, weight: .bold, design: .default))
                        .minimumScaleFactor(0.45)
                        .padding(.top, -primaryFont * 0.06)
                        .opacity(secondaryMetricText.isEmpty ? 0 : 1)
                }
            }
            .frame(height: metricBlockHeight, alignment: .center)

            Spacer(minLength: metricDebugGap)

            if viewModel.isInSpeedCaptureMode {
                Color.clear
                    .frame(height: debugBlockHeight)
            } else if shouldShowCityBadge {
                CityLimitBadgeView(
                    streetName: cityBadgeStreetText ?? "",
                    cityName: cityBadgeCityText ?? ""
                )
                .frame(maxWidth: signSize * 0.86)
                .frame(height: debugBlockHeight)
                .contentShape(Rectangle())
                .onTapGesture(count: 2) {
                    showingDebug = true
                }
            } else {
                VStack(spacing: debugSpacing) {
                    Text(debugCoordinateText)
                        .font(.system(size: debugFont, weight: .bold, design: .rounded))
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                        .monospacedDigit()
                    Text(debugWayIDText)
                        .font(.system(size: debugFont, weight: .bold, design: .rounded))
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
                .contentShape(Rectangle())
                .onTapGesture(count: 2) {
                    showingDebug = true
                }
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: statusAreaHeight, alignment: .bottom)
        .multilineTextAlignment(.center)
        .foregroundStyle(primaryForegroundColor)
        .padding(.horizontal, horizontalPadding)
        .padding(.bottom, bottomPadding)
    }

    private var primaryMetricText: String {
        if viewModel.isInSpeedCaptureMode {
            return viewModel.speedCapturePrimaryMetricText ?? "Jetzt"
        }
        if let drivingBanMonths = finePresentation?.drivingBanMonths, drivingBanMonths > 0 {
            return "\(drivingBanMonths)"
        }
        switch finePresentation?.severity {
        case .moneyOnly:
            guard let fineEUR = finePresentation?.moneyFineEUR else {
                return "?"
            }
            return "\(fineEUR)"
        case .pointsAndFine:
            guard let points = finePresentation?.penaltyPoints else {
                return "?"
            }
            return "\(points)"
        case .none:
            guard !isSearchingSignal else {
                return "Suche Signal"
            }
            return "\(Int(round(viewModel.currentSpeedKmh)))"
        }
    }

    private var secondaryMetricText: String {
        if viewModel.isInSpeedCaptureMode {
            return viewModel.speedCaptureSecondaryMetricText ?? "sprechen"
        }
        if let drivingBanMonths = finePresentation?.drivingBanMonths, drivingBanMonths > 0 {
            return drivingBanMonths == 1 ? "Monat Fahrverbot" : "Monate Fahrverbot"
        }
        switch finePresentation?.severity {
        case .moneyOnly:
            return viewModel.activePenaltyRules.currencyCode
        case .pointsAndFine:
            if let points = finePresentation?.penaltyPoints {
                return points == 1 ? "Punkt" : "Punkte"
            }
            return "Punkte"
        case .none:
            guard !isSearchingSignal else {
                return ""
            }
            return "km/h"
        }
    }

    private var debugCoordinateText: String {
        if viewModel.isInSpeedCaptureMode {
            return ""
        }
        if let street = normalizedPlaceText(viewModel.limitStreetName), viewModel.limitWayID != nil {
            return street
        }
        guard let latitude = viewModel.currentLatitude, let longitude = viewModel.currentLongitude else {
            return "Suche..."
        }
        return "\(iso6709Coordinate(latitude: latitude, longitude: longitude, fractionalDigits: 3))"
    }

    private var debugWayIDText: String {
        if viewModel.isInSpeedCaptureMode {
            return ""
        }
        if let city = normalizedPlaceText(viewModel.limitCityName) {
            return city
        }
        return hasUsableGPSFix ? "Stadt unbekannt" : "Suche..."
    }

    private var limitText: String {
        if let capture = viewModel.speedCaptureSignText {
            return capture
        }
        guard let speedLimit = viewModel.speedLimitKmh else {
            return hasUsableGPSFix ? "–" : "?"
        }
        return "\(speedLimit)"
    }

    private var shouldShowTunnelSignIcon: Bool {
        false
    }

    private var shouldShowTunnelCurrentSpeedIcon: Bool {
        viewModel.isTunnelModeActive && !viewModel.isInSpeedCaptureMode
    }

    private var cityBadgeStreetText: String? {
        normalizedPlaceText(viewModel.limitStreetName)
    }

    private var cityBadgeCityText: String? {
        normalizedPlaceText(viewModel.limitCityName)
    }

    private var shouldShowCityBadge: Bool {
        guard viewModel.lastLookupInsideCity == true else {
            return false
        }
        return cityBadgeStreetText != nil || cityBadgeCityText != nil
    }

    private var finePresentation: SpeedPenaltyNotice? {
        viewModel.currentPenaltyNotice
    }

    private var screenBackgroundColor: Color {
        guard let progress = overspeedBackgroundProgress else {
            return .black
        }
        return backgroundColor(for: progress)
    }

    @ViewBuilder
    private var screenBackgroundView: some View {
        if viewModel.isInSpeedCaptureMode {
            Color.white
        } else if isDrivingBanWarningActive {
            TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { timeline in
                drivingBanPulseBackgroundColor(at: timeline.date)
            }
        } else {
            screenBackgroundColor
        }
    }

    private var primaryForegroundColor: Color {
        if viewModel.isInSpeedCaptureMode {
            return .black
        }
        if usesDarkForeground {
            return .black
        }
        return .white
    }

    private var buttonBackgroundColor: Color {
        if viewModel.isInSpeedCaptureMode {
            return Color.black.opacity(0.08)
        }
        if usesDarkForeground {
            return Color.black.opacity(0.08)
        }
        return Color.white.opacity(0.14)
    }

    private var isSearchingSignal: Bool {
        !hasUsableGPSFix
    }

    private var isDrivingBanWarningActive: Bool {
        (finePresentation?.drivingBanMonths ?? 0) > 0
    }

    private var hasUsableGPSFix: Bool {
        viewModel.gpsFixCount > 0 && viewModel.currentLatitude != nil && viewModel.currentLongitude != nil
    }

    private var overspeedBackgroundProgress: Double? {
        guard hasUsableGPSFix else {
            return nil
        }
        let overspeed = viewModel.currentOverspeedKmh
        guard overspeed > 0 else {
            return nil
        }
        if isDrivingBanWarningActive {
            return 1
        }
        let pointsThreshold = Double(max(minOverspeedForPoints, 1))
        let drivingBanThreshold = Double(max(minOverspeedForDrivingBan, minOverspeedForPoints + 1))
        if finePresentation?.severity == .pointsAndFine {
            let normalized = min(
                1,
                max(0, (Double(overspeed) - pointsThreshold) / max(1, drivingBanThreshold - pointsThreshold))
            )
            return 0.68 + (normalized * 0.27)
        }
        let normalized = min(1, max(0, Double(overspeed) / pointsThreshold))
        return normalized * 0.62
    }

    private var minOverspeedForPoints: Int {
        viewModel.activePenaltyRules.bands
            .filter { $0.severity == .pointsAndFine }
            .map(\.minDeltaKmh)
            .min() ?? 21
    }

    private var minOverspeedForDrivingBan: Int {
        let thresholds = viewModel.activePenaltyRules.bands
            .filter { ($0.drivingBanMonths ?? 0) > 0 || ($0.conditionalDrivingBanMonths ?? 0) > 0 }
            .map(\.minDeltaKmh)
        return thresholds.min() ?? (minOverspeedForPoints + 10)
    }

    private var usesDarkForeground: Bool {
        guard let progress = overspeedBackgroundProgress else {
            return false
        }
        return progress < 0.45
    }

    private func backgroundColor(for progress: Double) -> Color {
        let t = min(1, max(0, progress))
        let yellow = (r: 0.98, g: 0.87, b: 0.20)
        let orange = (r: 0.95, g: 0.48, b: 0.12)
        let red = (r: 0.78, g: 0.10, b: 0.13)
        let mixed: (r: Double, g: Double, b: Double)
        if t < 0.6 {
            let a = t / 0.6
            mixed = (
                r: yellow.r + (orange.r - yellow.r) * a,
                g: yellow.g + (orange.g - yellow.g) * a,
                b: yellow.b + (orange.b - yellow.b) * a
            )
        } else {
            let a = (t - 0.6) / 0.4
            mixed = (
                r: orange.r + (red.r - orange.r) * a,
                g: orange.g + (red.g - orange.g) * a,
                b: orange.b + (red.b - orange.b) * a
            )
        }
        return Color(red: mixed.r, green: mixed.g, blue: mixed.b)
    }

    private func drivingBanPulseBackgroundColor(at date: Date) -> Color {
        let phase = (date.timeIntervalSinceReferenceDate / drivingBanPulseCycleSeconds) * (2 * Double.pi)
        let wave = (sin(phase) + 1) / 2
        let darkRed = (r: 0.42, g: 0.04, b: 0.06)
        let darkerRed = (r: 0.29, g: 0.01, b: 0.03)
        let blend = 0.25 + (wave * 0.75)
        return Color(
            red: darkRed.r + (darkerRed.r - darkRed.r) * blend,
            green: darkRed.g + (darkerRed.g - darkRed.g) * blend,
            blue: darkRed.b + (darkerRed.b - darkRed.b) * blend
        )
    }

    private func normalizedPlaceText(_ raw: String?) -> String? {
        guard let trimmed = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return nil
        }
        return trimmed
    }

    private func iso6709Coordinate(latitude: Double, longitude: Double, fractionalDigits: Int) -> String {
        let posix = Locale(identifier: "en_US_POSIX")
        let latSign = latitude >= 0 ? "N" : "S"
        let lonSign = longitude >= 0 ? "O" : "W"
        let latBody = String(
            format: "%0*.*f",
            locale: posix,
            3 + 1 + fractionalDigits,
            fractionalDigits,
            abs(latitude)
        )
        let lonBody = String(
            format: "%0*.*f",
            locale: posix,
            3 + 1 + fractionalDigits,
            fractionalDigits,
            abs(longitude)
        )
        return "\(latSign)\(latBody) \(lonSign)\(lonBody)"
    }

    private func primaryMetricFont(size: CGFloat) -> Font {
        if viewModel.isInSpeedCaptureMode {
            return .system(size: size * 0.42, weight: .bold, design: .rounded)
        }
        if isSearchingSignal {
            return .system(size: size, weight: .bold, design: .rounded)
        }
        return trafficSignNumberFont(size: size)
    }

    private func sharedSecondaryScale(baseSecondaryFont: CGFloat, availableWidth: CGFloat) -> CGFloat {
        // Keep the status area visually stable between "no fix" and "fix" states.
        let stableReference = "N00.0000 O000.0000"
        let estimatedWidth = estimateTextWidth(stableReference, fontSize: baseSecondaryFont)
        guard estimatedWidth > 0 else {
            return 0.45
        }
        let adaptive = availableWidth / estimatedWidth
        return min(0.5, max(0.35, adaptive))
    }

    private func estimateTextWidth(_ text: String, fontSize: CGFloat) -> CGFloat {
        CGFloat(text.count) * fontSize * 0.58
    }

    private var shouldAutoTapSyncForTests: Bool {
        let env = ProcessInfo.processInfo.environment
        let envEnabled = env["SPEEDCONSUMER_TEST_AUTOTAP_SYNC"] == "1"
        let infoEnabled = (Bundle.main.infoDictionary?["YouSpeedTestAutoTapSync"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) == "1"
        guard envEnabled || infoEnabled else {
            return false
        }
        return env["XCTestConfigurationFilePath"] != nil
    }
}

private struct SpeedLimitSignView: View {
    let limitText: String
    let numberFontSize: CGFloat
    let showsTunnelIcon: Bool

    var body: some View {
        GeometryReader { proxy in
            let size = min(proxy.size.width, proxy.size.height)
            // Based on Zeichen 274 geometry: black border 7.875 / 450, red band 60.301 / 450.
            let blackBorderWidth = max(1, size * 0.0175)
            let redBandWidth = max(2, size * 0.134)
            let innerDiameter = max(1, size - (2 * (blackBorderWidth + redBandWidth)))
            ZStack {
                Circle()
                    .fill(Color.white)

                Circle()
                    .strokeBorder(Color.black.opacity(0.75), lineWidth: blackBorderWidth)

                Circle()
                    .inset(by: blackBorderWidth)
                    .strokeBorder(Color(red: 0.76, green: 0.07, blue: 0.11), lineWidth: redBandWidth)

                if showsTunnelIcon {
                    Image(systemName: "tunnel.fill")
                        .font(.system(size: innerDiameter * 0.42, weight: .bold))
                        .foregroundStyle(.black)
                } else {
                    Text(limitText)
                        .font(trafficSignNumberFont(size: numberFontSize))
                        .frame(width: innerDiameter * 0.86, height: innerDiameter * 0.66, alignment: .center)
                        .minimumScaleFactor(0.28)
                        .allowsTightening(true)
                        .foregroundStyle(.black)
                        .lineLimit(1)
                }
            }
            .frame(width: size, height: size)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

private func trafficSignNumberFont(size: CGFloat) -> Font {
    #if canImport(UIKit)
    if UIFont(name: "DINAlternate-Bold", size: size) != nil {
        return .custom("DINAlternate-Bold", size: size)
    }
    if UIFont(name: "DINCondensed-Bold", size: size) != nil {
        return .custom("DINCondensed-Bold", size: size)
    }
    #endif
    return .system(size: size, weight: .black, design: .default)
}

private struct LegalInformationView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var legalText: String = LegalTextLoader.load()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Rechtlicher Hinweis")
                        .font(.system(size: 16, weight: .bold, design: .default))
                    Text(LegalDisclaimerText.long)
                        .font(.system(size: 14, weight: .regular, design: .default))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.yellow.opacity(0.16), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

                Text(legalText)
                    .font(.system(size: 15, weight: .regular, design: .default))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .padding(16)
        }
        .navigationTitle("Rechtliche Hinweise")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Fertig") {
                    dismiss()
                }
            }
        }
        .background(Color(.systemBackground))
    }
}

private enum LegalTextLoader {
    static func load(bundle: Bundle = .main) -> String {
        guard let url = bundle.url(forResource: "legal", withExtension: "txt"),
              let text = try? String(contentsOf: url, encoding: .utf8) else {
            return "Rechtliche Hinweise konnten nicht geladen werden."
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private struct CityLimitBadgeView: View {
    let streetName: String
    let cityName: String

    var body: some View {
        VStack(spacing: 2) {
            if !streetName.isEmpty {
                Text(streetName)
                    .font(.system(size: 18, weight: .bold, design: .default))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
            if !cityName.isEmpty {
                Text(cityName)
                    .font(.system(size: 18, weight: .bold, design: .default))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
        }
        .foregroundStyle(.black)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(red: 0.97, green: 0.86, blue: 0.30))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.black.opacity(0.9), lineWidth: 2)
        )
    }
}

private struct LocalRecordingsView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var shareItem: ShareItem?

    private struct ShareItem: Identifiable {
        let id = UUID()
        let url: URL
    }

    var body: some View {
        VStack(spacing: 0) {
            Text("Zur Erfassung von Korrekturen Schild doppelklicken anschliessend die korrekte Geschwindigkeit als Zahl einsprechen")
                .font(.footnote)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 6)

            List {
                if viewModel.localObservations.isEmpty {
                    Text("Keine lokalen Erfassungen vorhanden.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(viewModel.localObservations) { observation in
                        HStack(alignment: .center, spacing: 12) {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(formattedTimestamp(observation.capturedAtUTC))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Text(streetName(for: observation))
                                    .font(.subheadline.weight(.semibold))
                                Text("way id \(observation.roadCandidateIDs.first ?? "n/a")")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                HStack(spacing: 10) {
                                    Text("alt \(observation.oldSpeedKmh.map(String.init) ?? "n/a")")
                                    Text("neu \(observation.newSpeedKmh.map(String.init) ?? observation.value ?? "n/a")")
                                }
                                .font(.subheadline.monospacedDigit())
                            }
                            Spacer(minLength: 0)
                            Button(role: .destructive) {
                                viewModel.deleteLocalObservation(observation.id)
                            } label: {
                                Image(systemName: "trash")
                                    .font(.body.weight(.semibold))
                                    .frame(width: 32, height: 32)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Eintrag löschen")
                        }
                        .padding(.vertical, 2)
                    }
                }
            }

            VStack(spacing: 8) {
                if !viewModel.localObservationStatus.isEmpty {
                    Text(viewModel.localObservationStatus)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                Button {
                    viewModel.exportAllLocalObservations()
                } label: {
                    Text("changes.osc exportieren")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)

                Button(role: .destructive) {
                    viewModel.deleteAllLocalObservations()
                } label: {
                    Label("Alle lokalen Erfassungen löschen", systemImage: "trash")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 12)
        }
        .navigationTitle("Lokale Erfassungen")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Fertig") {
                    dismiss()
                }
            }
        }
        .task {
            await viewModel.refreshLocalObservations()
        }
        .onChange(of: viewModel.localObservationShareURL) { _, newValue in
            guard let newValue else {
                return
            }
            shareItem = ShareItem(url: newValue)
            viewModel.clearLocalObservationShareURL()
        }
        .sheet(item: $shareItem) { item in
            ShareSheet(activityItems: [item.url])
        }
    }

    private func formattedTimestamp(_ value: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fallbackFormatter = ISO8601DateFormatter()
        fallbackFormatter.formatOptions = [.withInternetDateTime]
        let parsed = formatter.date(from: value) ?? fallbackFormatter.date(from: value)
        guard let parsed else {
            return value
        }
        return parsed.formatted(date: .abbreviated, time: .standard)
    }

    private func streetName(for observation: LocalObservation) -> String {
        if let wayID = observation.roadCandidateIDs.first?.trimmingCharacters(in: .whitespacesAndNewlines),
           !wayID.isEmpty,
           let lookedUp = viewModel.localObservationStreetNames[wayID],
           !lookedUp.isEmpty {
            return lookedUp
        }
        if let fallback = observation.streetContext?.trimmingCharacters(in: .whitespacesAndNewlines),
           !fallback.isEmpty {
            return fallback
        }
        return "Straßenname n/a"
    }
}

private struct ShareSheet: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

private struct SettingsView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var showingDeleteDownloadedBundlesConfirm = false

    var body: some View {
        Form {
            Section("Akustische Hinweise") {
                Toggle("Sprachausgabe", isOn: $viewModel.audioAlertsEnabled)

                HStack {
                    Text("Warnung ab")
                    Spacer()
                    TextField("km/h", value: $viewModel.audioAlertThresholdKmh, format: .number)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 64)
                    Text("km/h")
                        .foregroundStyle(.secondary)
                }
                .disabled(!viewModel.audioAlertsEnabled)

                HStack {
                    Text("Warnschwelle anpassen")
                    Spacer()
                    Stepper("", value: $viewModel.audioAlertThresholdKmh, in: 0...80, step: 1)
                        .labelsHidden()
                }
                .disabled(!viewModel.audioAlertsEnabled)

                Text(!viewModel.audioAlertsEnabled
                     ? "Sprachausgabe ist deaktiviert."
                     : viewModel.audioAlertThresholdKmh == 0
                     ? "Akustische Hinweise sind deaktiviert."
                     : "Sprachwarnung startet bei \(viewModel.audioAlertThresholdKmh) km/h ueber dem erkannten Tempolimit.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section("Kartendaten-Download") {
                LabeledContent("Status", value: syncStatusLabel)
                LabeledContent("Bundle", value: viewModel.activeBundleVersion)
                LabeledContent("GH Token", value: viewModel.hasGitHubReleaseToken ? "vorhanden" : "fehlt")

                if !viewModel.hasGitHubReleaseToken {
                    Text("GitHub Release Token fehlt. Downloads aus Releases schlagen fehl (YOUSPEED_RELEASE_READ_TOKEN).")
                        .font(.footnote)
                        .foregroundStyle(.red)
                }

                if let syncMessage = syncMessageLine {
                    Text(syncMessage.text)
                        .font(.footnote)
                        .foregroundStyle(syncMessage.color)
                }

                Text("Top-10 Laender (A-Z). Bundles koennen einzeln geladen oder geloescht werden.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                if viewModel.bundleDownloadSections.isEmpty {
                    Text("Keine Downloadliste verfuegbar.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(viewModel.bundleDownloadSections) { country in
                        if country.options.count == 1, let option = country.options.first {
                            bundleOptionRow(option, title: country.countryName)
                        } else {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(country.countryName)
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(.primary)

                                ForEach(country.options) { option in
                                    bundleOptionRow(option, title: option.displayName)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }

                Button(role: .destructive) {
                    showingDeleteDownloadedBundlesConfirm = true
                } label: {
                    Text("Heruntergeladene Datenbanken loeschen (Seed behalten)")
                }
                .disabled(viewModel.isSyncingNow)

                if !viewModel.maintenanceMessage.isEmpty {
                    Text(viewModel.maintenanceMessage)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if !viewModel.lastError.isEmpty {
                    Text(viewModel.lastError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }

                if (viewModel.syncStatus == "syncing" || viewModel.syncStatus == "bootstrapping"),
                   viewModel.activeDownloadOptionID == nil {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(viewModel.syncProgressDetail)
                            .font(.caption)

                        if let progressValue = syncProgressValue {
                            ProgressView(value: progressValue)
                            Text(syncProgressBytesText)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            if !syncProgressMetaText.isEmpty {
                                Text(syncProgressMetaText)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        } else {
                            ProgressView()
                            if !syncProgressBytesText.isEmpty {
                                Text(syncProgressBytesText)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        ForEach(viewModel.syncPartDownloads) { part in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(part.detail)
                                    .font(.caption2)
                                ProgressView(
                                    value: part.totalBytes > 0
                                    ? Double(min(max(part.completedBytes, 0), part.totalBytes)) / Double(part.totalBytes)
                                    : 0
                                )
                                Text(partProgressBytesText(part))
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }
            }

            Section("Bussgeldregeln") {
                LabeledContent("Aktive Datei", value: viewModel.activePenaltyRulesFile)
                LabeledContent("Land", value: "\(viewModel.activePenaltyRules.countryName) (\(viewModel.activePenaltyRules.countryCode))")
                LabeledContent("Stufen", value: "\(viewModel.activePenaltyRules.bands.count)")
            }

            Section("Startbildschirm") {
                Toggle("Nicht mehr anzeigen", isOn: $viewModel.hideWelcomeScreen)

                Text(viewModel.hideWelcomeScreen
                     ? "Der Startbildschirm wird nicht mehr automatisch angezeigt."
                     : "Der Startbildschirm wird bei Seed-Daten oder veralteten Deutschland-Daten angezeigt.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section("Debug") {
                NavigationLink("Debug-Informationen oeffnen") {
                    DebugInformationView(viewModel: viewModel)
                }
            }
        }
        .navigationTitle("Einstellungen")
        .navigationBarTitleDisplayMode(.inline)
        .alert("Heruntergeladene Datenbanken loeschen?", isPresented: $showingDeleteDownloadedBundlesConfirm) {
            Button("Abbrechen", role: .cancel) {}
            Button("Loeschen", role: .destructive) {
                viewModel.deleteDownloadedBundlesKeepingSeed()
            }
        } message: {
            Text("Alle heruntergeladenen Bundle-Daten werden entfernt. Der Seed-Datensatz bleibt erhalten.")
        }
    }

    private var syncStatusLabel: String {
        switch viewModel.syncStatus {
        case "not_synced":
            return "Nicht synchronisiert"
        case "syncing":
            return "Synchronisiert..."
        case "sync_failed":
            return "Synchronisierung fehlgeschlagen"
        default:
            return viewModel.syncStatus.replacingOccurrences(of: "_", with: " ")
        }
    }

    private var syncMessageLine: (text: String, color: Color)? {
        switch viewModel.syncStatus {
        case "ready_upToDate":
            return ("Daten sind verfuegbar und aktuell.", .green)
        case "ready_fullDownload", "ready_deltaPatch":
            return ("Datensynchronisierung abgeschlossen. Lokale Daten sind aktuell.", .green)
        case "ready_bootstrap":
            return ("Seed-Daten sind lokal verfuegbar.", .orange)
        case "sync_failed" where !viewModel.activeDBPath.isEmpty:
            return ("Synchronisierung fehlgeschlagen, lokale Daten sind aber weiterhin verfuegbar.", .orange)
        case "sync_failed":
            return ("Synchronisierung fehlgeschlagen. Kein aktives Daten-Bundle verfuegbar.", .red)
        default:
            return nil
        }
    }

    private var syncProgressValue: Double? {
        let total = viewModel.syncProgressTotalBytes
        guard total > 0 else {
            return nil
        }
        let completed = min(max(viewModel.syncProgressCompletedBytes, 0), total)
        return Double(completed) / Double(total)
    }

    private var syncProgressBytesText: String {
        let completed = max(viewModel.syncProgressCompletedBytes, 0)
        let total = max(viewModel.syncProgressTotalBytes, 0)
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        if total > 0 {
            return "\(formatter.string(fromByteCount: completed)) / \(formatter.string(fromByteCount: total))"
        }
        if completed > 0 {
            return formatter.string(fromByteCount: completed)
        }
        return ""
    }

    private var syncProgressMetaText: String {
        let rate = max(0, viewModel.syncProgressBytesPerSecond)
        let eta = viewModel.syncProgressETASeconds
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file

        var parts: [String] = []
        if rate > 1 {
            parts.append("\(formatter.string(fromByteCount: Int64(rate)))/s")
        }
        if let eta, eta >= 0 {
            let duration = DateComponentsFormatter()
            duration.allowedUnits = eta >= 3600 ? [.hour, .minute] : [.minute, .second]
            duration.unitsStyle = .abbreviated
            if let etaText = duration.string(from: eta) {
                parts.append("Restzeit \(etaText)")
            }
        }
        return parts.joined(separator: " • ")
    }

    private func partProgressBytesText(_ part: PartDownloadProgress) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        let completed = max(0, part.completedBytes)
        let total = max(0, part.totalBytes)
        if total > 0 {
            return "\(formatter.string(fromByteCount: completed)) / \(formatter.string(fromByteCount: total))"
        }
        if completed > 0 {
            return formatter.string(fromByteCount: completed)
        }
        return ""
    }

    @ViewBuilder
    private func bundleOptionRow(
        _ option: DriveSessionViewModel.BundleDownloadOption,
        title: String
    ) -> some View {
        let downloaded = viewModel.isBundleDownloaded(option)
        let statusText = viewModel.downloadedBundleStatusText(option)
        let isActiveDownload = viewModel.isActiveBundleDownload(option)
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)

                if !statusText.isEmpty {
                    Text(statusText)
                        .font(.caption2)
                        .foregroundStyle(downloaded ? .green : .secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }

                if isActiveDownload {
                    if let progress = viewModel.activeBundleDownloadProgress(option) {
                        ProgressView(value: progress)
                    } else {
                        ProgressView()
                    }
                    let progressText = viewModel.activeBundleDownloadBytesText(option)
                    if !progressText.isEmpty {
                        Text(progressText)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
                }
            }

            Spacer(minLength: 8)

            if downloaded {
                Button(role: .destructive) {
                    viewModel.deleteSelectedBundle(option)
                } label: {
                    Image(systemName: "trash")
                        .font(.title3.weight(.semibold))
                        .frame(width: 30, height: 30)
                }
                .buttonStyle(.plain)
                .disabled(viewModel.isSyncingNow)
            } else {
                if isActiveDownload {
                    Image(systemName: "arrow.down.circle")
                        .font(.title3.weight(.semibold))
                        .frame(width: 30, height: 30)
                        .foregroundStyle(.secondary)
                } else {
                    Button {
                        viewModel.downloadSelectedBundle(option)
                    } label: {
                        Image(systemName: "arrow.down.circle")
                            .font(.title3.weight(.semibold))
                            .frame(width: 30, height: 30)
                    }
                    .buttonStyle(.plain)
                    .disabled(viewModel.isSyncingNow || viewModel.hasActiveBundleDownload)
                }
            }
        }
        .frame(minHeight: 42, alignment: .center)
        .padding(.vertical, 1)
    }
}

private struct DebugInformationView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var showingOSMBrowser = false

    var body: some View {
        List {
            Section("Letzter Fix") {
                if hasUsableFix {
                    DebugKeyValueTable(rows: fixRows)
                } else {
                    Text("Noch kein verwertbarer GPS-Fix vorhanden.")
                        .foregroundStyle(.secondary)
                }
            }

            if let target = osmTarget {
                Section("OSM") {
                    HStack {
                        Text("Way")
                        Spacer()
                        Text(target.wayID)
                            .font(.body.monospaced())
                            .textSelection(.enabled)
                    }

                    HStack(spacing: 12) {
                        Link("Im Browser öffnen", destination: target.url)
                            .buttonStyle(.bordered)

                        Button("In App-Browser") {
                            showingOSMBrowser = true
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            }

            if !viewModel.lastError.isEmpty {
                Section("Fehler") {
                    Text(viewModel.lastError)
                        .foregroundStyle(.red)
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Debug")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showingOSMBrowser) {
            if let target = osmTarget {
                OSMBrowserView(url: target.url)
                    .ignoresSafeArea()
            } else {
                Text("No OSM URL available")
                    .font(.footnote)
                    .padding()
            }
        }
    }

    private var hasUsableFix: Bool {
        viewModel.gpsFixCount > 0 &&
        viewModel.currentLatitude != nil &&
        viewModel.currentLongitude != nil
    }

    private var fixRows: [(key: String, value: String)] {
        let speed = String(format: "%.1f km/h", viewModel.currentSpeedKmh)
        let limitText = viewModel.speedLimitKmh.map { "\($0) km/h" } ?? "n/a"
        let delta: String = {
            guard let limit = viewModel.speedLimitKmh else { return "n/a" }
            let value = Int(round(viewModel.currentSpeedKmh)) - limit
            return "\(value >= 0 ? "+" : "")\(value) km/h"
        }()
        let latLon = "\(latText), \(lonText)"
        return [
            ("Koordinate", latLon),
            ("Geschwindigkeit", speed),
            ("Tempolimit", limitText),
            ("Delta", delta),
            ("Aktives Bundle", viewModel.activeBundleVersion),
            ("Aktive DB", viewModel.activeDatabaseFileName),
            ("DB-Quelle", viewModel.activeDatabaseOriginLabel),
            ("DB-Pfad", viewModel.activeDBPath.isEmpty ? "n/a" : viewModel.activeDBPath),
            ("Way-ID", viewModel.limitWayID ?? "n/a"),
            ("Straße", normalizedOrNA(viewModel.limitStreetName)),
            ("Stadt", normalizedOrNA(viewModel.limitCityName)),
            ("Innerorts", viewModel.lastLookupInsideCity.map { $0 ? "ja" : "nein" } ?? "n/a"),
            ("Lookup", viewModel.lastLookupStatus),
            ("Query", String(format: "%.3f ms", viewModel.lastLookupQueryMs)),
            ("Kandidaten", "\(viewModel.lastLookupCandidateCount)"),
            ("Mit Limit", "\(viewModel.lastLookupSpeedCandidateCount)"),
            ("Distanz Weg", viewModel.lastLookupNearestCandidateM.map { String(format: "%.1f m", $0) } ?? "n/a"),
            ("Distanz Limit-Weg", viewModel.lastLookupNearestSpeedCandidateM.map { String(format: "%.1f m", $0) } ?? "n/a"),
            ("Stadtquelle", viewModel.lastLookupCitySource),
            ("Stadt-Resolve", String(format: "%.3f ms", viewModel.lastLookupCityResolveMs)),
            ("Manifest-Endpunkte", "\(viewModel.configuredManifestEndpointCount)"),
            ("Manifest-Länder", viewModel.configuredManifestCountryCodes),
        ]
    }

    private var latText: String {
        guard let lat = viewModel.currentLatitude else { return "n/a" }
        return String(format: "%.6f", lat)
    }

    private var lonText: String {
        guard let lon = viewModel.currentLongitude else { return "n/a" }
        return String(format: "%.6f", lon)
    }

    private func normalizedOrNA(_ raw: String?) -> String {
        guard let trimmed = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return "n/a"
        }
        return trimmed
    }

    private var osmTarget: (wayID: String, latText: String, lonText: String, url: URL)? {
        guard let wayID = viewModel.limitWayID,
              let lat = viewModel.currentLatitude,
              let lon = viewModel.currentLongitude else {
            return nil
        }
        let latText = String(format: "%.6f", lat)
        let lonText = String(format: "%.6f", lon)
        guard let url = URL(string: "https://www.openstreetmap.org/way/\(wayID)#map=18/\(latText)/\(lonText)") else {
            return nil
        }
        return (wayID, latText, lonText, url)
    }
}

private struct DebugKeyValueTable: View {
    let rows: [(key: String, value: String)]

    var body: some View {
        Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 12, verticalSpacing: 8) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                GridRow {
                    Text(row.key)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(row.value)
                        .font(.body.monospacedDigit())
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct OSMBrowserView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let browser = SFSafariViewController(url: url)
        browser.preferredControlTintColor = .systemBlue
        return browser
    }

    func updateUIViewController(_ uiViewController: SFSafariViewController, context: Context) {
        // SFSafariViewController does not support updating URL after creation.
    }
}

import SafariServices
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

private let speedLimitNumberScale: CGFloat = 0.5
private let secondaryTextRatio: CGFloat = 9.0 / 16.0
private let drivingBanPulseCycleSeconds: Double = 2.2

struct MainView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
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
                    showingLocalRecordings = true
                } label: {
                    Image(systemName: "ladybug.fill")
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
                showingLegalInfo = true
            } label: {
                Image(systemName: "info.circle.fill")
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
            return "Erfasse"
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
            return "Geschwindigkeit"
        }
        if let drivingBanMonths = finePresentation?.drivingBanMonths, drivingBanMonths > 0 {
            return drivingBanMonths == 1 ? "Monat Fahrverbot" : "Monate Fahrverbot"
        }
        switch finePresentation?.severity {
        case .moneyOnly:
            return "Euro"
        case .pointsAndFine:
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
        if shouldShowTunnelSignIcon {
            return ""
        }
        guard let speedLimit = viewModel.speedLimitKmh else {
            return hasUsableGPSFix ? "–" : "?"
        }
        return "\(speedLimit)"
    }

    private var shouldShowTunnelSignIcon: Bool {
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
        if isDrivingBanWarningActive {
            TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { timeline in
                drivingBanPulseBackgroundColor(at: timeline.date)
            }
        } else {
            screenBackgroundColor
        }
    }

    private var primaryForegroundColor: Color {
        if usesDarkForeground {
            return .black
        }
        return .white
    }

    private var buttonBackgroundColor: Color {
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
            Text(legalText)
                .font(.system(size: 15, weight: .regular, design: .default))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .textSelection(.enabled)
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
    @State private var showingFlushLocalContributionsConfirm = false

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

                if let syncMessage = syncMessageLine {
                    Text(syncMessage.text)
                        .font(.footnote)
                        .foregroundStyle(syncMessage.color)
                }

                Button("Neueste Daten herunterladen/synchronisieren") {
                    viewModel.bootstrapAndSync()
                }
                .disabled(viewModel.isSyncingNow)

                Button(role: .destructive) {
                    showingFlushLocalContributionsConfirm = true
                } label: {
                    Text("Lokale Korrekturen loeschen und neu synchronisieren")
                }
                .disabled(viewModel.isSyncingNow)

                if !viewModel.maintenanceMessage.isEmpty {
                    Text(viewModel.maintenanceMessage)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if viewModel.syncStatus == "syncing" || viewModel.syncStatus == "bootstrapping" {
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
                LabeledContent("Aktive Datei", value: "DEU-rules.json")
                LabeledContent("Land", value: "\(viewModel.activePenaltyRules.countryName) (\(viewModel.activePenaltyRules.countryCode))")
                LabeledContent("Stufen", value: "\(viewModel.activePenaltyRules.bands.count)")
            }

            Section("Debug") {
                NavigationLink("Debug-Informationen oeffnen") {
                    DebugInformationView(viewModel: viewModel)
                }
            }
        }
        .navigationTitle("Einstellungen")
        .navigationBarTitleDisplayMode(.inline)
        .alert("Lokale Korrekturen loeschen?", isPresented: $showingFlushLocalContributionsConfirm) {
            Button("Abbrechen", role: .cancel) {}
            Button("Loeschen und synchronisieren", role: .destructive) {
                viewModel.flushLocalContributionsAndResync()
            }
        } message: {
            Text("Diese Aktion entfernt lokale Korrektur- und Exportdaten. Anschliessend wird eine neue Datensynchronisierung gestartet.")
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
}

private struct DebugInformationView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var showingOSMBrowser = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("YouSpeed Consumer (Debug)")
                    .font(.title3)
                    .bold()

                Group {
                    Text("sync=\(viewModel.syncStatus)")
                    Text("drive=\(viewModel.driveStatus)")
                    Text("bundle=\(viewModel.activeBundleVersion)")
                }
                .font(.footnote)

                HStack {
                    Button("Sync Data") {
                        viewModel.bootstrapAndSync()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(viewModel.isSyncingNow)

                    Button("Start Driving") {
                        viewModel.startDriving()
                    }
                    .buttonStyle(.bordered)

                    Button("Stop") {
                        viewModel.stopDriving()
                    }
                    .buttonStyle(.bordered)
                }

                Group {
                    Text(String(format: "Current speed: %.1f km/h", viewModel.currentSpeedKmh))
                        .font(.title3)
                        .bold()
                    if let limit = viewModel.speedLimitKmh {
                        Text("Speed limit: \(limit) km/h")
                            .font(.title3)
                            .bold()
                        let delta = Int(round(viewModel.currentSpeedKmh)) - limit
                        Text("Delta: \(delta >= 0 ? "+" : "")\(delta) km/h")
                            .foregroundStyle(delta > 0 ? .red : .green)
                    } else {
                        Text("Speed limit: n/a")
                            .font(.title3)
                    }
                    if let wayID = viewModel.limitWayID {
                        Text("Matched way: \(wayID)")
                            .font(.caption)
                    }
                    if let street = viewModel.limitStreetName, !street.isEmpty {
                        Text("Street: \(street)")
                            .font(.caption)
                    }
                    if let city = viewModel.limitCityName, !city.isEmpty {
                        Text("City: \(city)")
                            .font(.caption)
                    }
                }

                GroupBox("Lookup Diagnostics") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("strategy=closest_way + prefer_previous_way")
                        Text("radius=50m (fixed)")

                        Stepper("max candidates \(viewModel.lookupMaxCandidates)", value: $viewModel.lookupMaxCandidates, in: 64...1024, step: 64)

                        Text(
                            "gps=\(viewModel.currentLatitude.map { String(format: "%.6f", $0) } ?? "nil"),\(viewModel.currentLongitude.map { String(format: "%.6f", $0) } ?? "nil")"
                        )
                        Text(
                            "lookup=\(viewModel.lastLookupStatus) q_ms=\(String(format: "%.3f", viewModel.lastLookupQueryMs)) rows=\(viewModel.lastLookupCandidateCount) speed_rows=\(viewModel.lastLookupSpeedCandidateCount)"
                        )
                        Text(
                            "nearest_m=\(viewModel.lastLookupNearestCandidateM.map { String(format: "%.1f", $0) } ?? "nil") nearest_speed_m=\(viewModel.lastLookupNearestSpeedCandidateM.map { String(format: "%.1f", $0) } ?? "nil")"
                        )
                        Text(
                            "city=\(viewModel.limitCityName ?? "nil") inside_city=\(viewModel.lastLookupInsideCity.map { $0 ? "1" : "0" } ?? "nil") city_src=\(viewModel.lastLookupCitySource)"
                        )
                        Text(
                            "street=\(viewModel.limitStreetName ?? "nil") city_ms=\(String(format: "%.3f", viewModel.lastLookupCityResolveMs)) city_bounds=\(viewModel.lastLookupCityCandidateBoundaries) city_contains=\(viewModel.lastLookupCityContainingBoundaries) city_places=\(viewModel.lastLookupCityPlaceCandidates)"
                        )
                        Text("fix_count=\(viewModel.gpsFixCount)")
                        if !viewModel.gpsLogPath.isEmpty {
                            Text("gps_log=\(viewModel.gpsLogPath)")
                                .lineLimit(2)
                        }

                        Button("Reset Diagnostics") {
                            viewModel.resetDiagnostics()
                        }
                        .buttonStyle(.bordered)

                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 4) {
                                ForEach(Array(viewModel.lookupEventLog.enumerated()), id: \.offset) { _, line in
                                    Text(line)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                }
                            }
                        }
                        .frame(maxHeight: 140)
                    }
                    .font(.caption2.monospaced())
                }

                GroupBox("Local Corrections (Draft)") {
                    VStack(alignment: .leading, spacing: 8) {
                        TextField("Voice command (z. B. Tempo 30)", text: $viewModel.observationDraftVoiceCommand)
                            .textFieldStyle(.roundedBorder)
                            .textInputAutocapitalization(.never)
                            .disableAutocorrection(true)

                        HStack {
                            Button("Capture Voice") {
                                viewModel.captureVoiceObservationDraft()
                            }
                            .buttonStyle(.borderedProminent)

                            Button("Lock Current Speed") {
                                viewModel.lockCurrentSpeedAsObservation()
                            }
                            .buttonStyle(.bordered)
                        }

                        HStack {
                            Button("Export First Approved") {
                                viewModel.exportFirstApprovedObservation()
                            }
                            .buttonStyle(.bordered)

                            Button("Reload") {
                                Task { @MainActor in
                                    await viewModel.refreshLocalObservations()
                                }
                            }
                            .buttonStyle(.bordered)
                        }

                        if !viewModel.localObservationStatus.isEmpty {
                            Text(viewModel.localObservationStatus)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        if !viewModel.lastExportDirectoryPath.isEmpty {
                            Text("export_dir=\(viewModel.lastExportDirectoryPath)")
                                .font(.caption2.monospaced())
                                .lineLimit(2)
                                .textSelection(.enabled)
                        }

                        Divider()

                        if viewModel.localObservations.isEmpty {
                            Text("No local observations yet.")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(viewModel.localObservations) { observation in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("#\(observation.id.prefix(8)) \(observation.modality.rawValue) \(observation.intentType.rawValue)")
                                    Text("state=\(observation.state.rawValue) value=\(observation.value ?? "n/a")")
                                    Text("road=\(observation.roadCandidateIDs.first ?? "n/a") city=\(observation.cityContext ?? "n/a") street=\(observation.streetContext ?? "n/a")")
                                    Text("captured=\(observation.capturedAtUTC)")
                                    if observation.state == .needsReview {
                                        HStack {
                                            Button("Approve") {
                                                viewModel.approveObservation(observation.id)
                                            }
                                            .buttonStyle(.bordered)

                                            Button("Discard") {
                                                viewModel.discardObservation(observation.id)
                                            }
                                            .buttonStyle(.bordered)
                                        }
                                    }
                                }
                                .font(.caption2.monospaced())
                                .padding(.vertical, 4)
                            }
                        }
                    }
                }

                GroupBox("OSM Link") {
                    VStack(alignment: .leading, spacing: 8) {
                        if let target = osmTarget {
                            Text("way_id=\(target.wayID) lat=\(target.latText) lon=\(target.lonText)")
                                .font(.caption2.monospaced())

                            let url = target.url
                            Text(url.absoluteString)
                                .font(.caption2.monospaced())
                                .textSelection(.enabled)
                                .lineLimit(3)

                            HStack {
                                Link("Open in Browser", destination: url)
                                    .buttonStyle(.bordered)

                                Button("Open in Browser View") {
                                    showingOSMBrowser = true
                                }
                                .buttonStyle(.borderedProminent)
                            }
                        } else {
                            Text("OSM link unavailable (need matched way + current location)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if !viewModel.activeDBPath.isEmpty {
                    Text("db=\(viewModel.activeDBPath)")
                        .font(.caption2)
                        .lineLimit(3)
                        .foregroundStyle(.secondary)
                }

                if !viewModel.lastError.isEmpty {
                    Text("error=\(viewModel.lastError)")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            .padding()
        }
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

import SafariServices
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

private let speedLimitNumberScale: CGFloat = 0.5
private let secondaryTextRatio: CGFloat = 9.0 / 16.0
private let drivingBanPulseCycleSeconds: Double = 2.2
private let gpsBadgeSlotMinHeight: CGFloat = 58
private let cityBadgeSlotMinHeight: CGFloat = 84

enum LegalDisclaimerText {
    static var short: String {
        NSLocalizedString("legal.disclaimer.short", comment: "")
    }

    static var long: String {
        NSLocalizedString("legal.disclaimer.long", comment: "")
    }
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
            let horizontalPadding = max(12, proxy.size.width * 0.04)
            let controlDiameter: CGFloat = 44
            let bottomButtonGapWidth = max(0, proxy.size.width - (screenInset * 2) - (controlDiameter * 2))
            let topPadding = max(screenInset, proxy.safeAreaInsets.top * 0.28)
            let bottomPadding = max(screenInset, proxy.safeAreaInsets.bottom * 0.45)
            let sectionGap = max(14, minDimension * 0.04)
            let topControlBottom = topPadding + controlDiameter
            let bottomControlTopInset = bottomPadding + controlDiameter
            let contentTopInset = topControlBottom + max(10, minDimension * 0.028)
            let contentBottomInset = bottomControlTopInset + max(10, minDimension * 0.03)
            let locationReserve = viewModel.isInSpeedCaptureMode
                ? CGFloat(0)
                : max(cityBadgeSlotMinHeight, minDimension * 0.225)
            let signWidthBudget = min(proxy.size.width * 0.82, proxy.size.width - (horizontalPadding * 2))
            let signHeightBudget = (
                proxy.size.height -
                contentTopInset -
                contentBottomInset -
                locationReserve -
                (sectionGap * 2)
            ) / 1.78
            let signSize = min(signWidthBudget, max(minDimension * 0.58, signHeightBudget))
            let primaryMetricFontSize = signSize * speedLimitNumberScale
            let baseSecondaryFont = primaryMetricFontSize * secondaryTextRatio
            let secondaryScale = sharedSecondaryScale(
                baseSecondaryFont: baseSecondaryFont,
                availableWidth: proxy.size.width - (horizontalPadding * 2)
            )
            let secondaryFont = baseSecondaryFont * secondaryScale
            let debugFont = secondaryFont * 0.6
            let debugSpacing = max(2, minDimension * 0.004)
            ZStack {
                screenBackgroundView
                    .ignoresSafeArea()

                VStack(spacing: sectionGap) {
                    SpeedLimitSignView(
                        limitText: limitText,
                        numberFontSize: primaryMetricFontSize,
                        showsTunnelIcon: shouldShowTunnelSignIcon,
                        showsUnlimitedIcon: !showsPedestrianZoneSign && showsUnlimitedAutobahnSign,
                        showsPedestrianZoneIcon: showsPedestrianZoneSign
                    )
                    .frame(width: signSize, height: signSize)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, screenInset)
                    .contentShape(Rectangle())
                    .highPriorityGesture(
                        TapGesture(count: 2).onEnded {
                            viewModel.beginSpeedLimitCapture()
                        }
                    )

                    if viewModel.panoramaxCaptureEnabled {
                        panoramaxDriveRecorderBlock
                            .padding(.horizontal, horizontalPadding)
                    } else {
                        metricStatusBlock(
                            primaryFont: primaryMetricFontSize,
                            secondaryFont: secondaryFont
                        )
                        .padding(.horizontal, horizontalPadding)

                        locationStatusBlock(
                            badgeWidth: bottomButtonGapWidth,
                            debugFont: debugFont,
                            debugSpacing: debugSpacing,
                            reservedHeight: locationReserve
                        )
                        .padding(.horizontal, horizontalPadding)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .padding(.top, contentTopInset)
                .padding(.bottom, contentBottomInset)

                topCornerButtons
                    .padding(.horizontal, screenInset)
                    .padding(.top, topPadding)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)

                bottomCornerButtons(horizontalPadding: screenInset)
                    .padding(.bottom, bottomPadding)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
            }
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack {
                SettingsView(viewModel: viewModel, account: viewModel.panoramaxAccount)
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

    private var showsPedestrianZoneSign: Bool {
        !viewModel.isInSpeedCaptureMode && viewModel.speedLimitDisplayText == "Schritt"
    }

    private var panoramaxDriveRecorderBlock: some View {
        VStack(spacing: 8) {
            ZStack(alignment: .topLeading) {
                if let session = viewModel.panoramaxPreviewSession,
                   viewModel.panoramaxCaptureState == .recording || viewModel.panoramaxCaptureState == .preparing {
                    PanoramaxCameraPreview(session: session)
                } else {
                    Color.white.opacity(0.08)
                    VStack(spacing: 6) {
                        Image(systemName: "camera.viewfinder")
                            .font(.system(size: 30, weight: .semibold))
                        Text(panoramaxRecorderStateText)
                            .font(.subheadline.weight(.semibold))
                    }
                    .foregroundStyle(.white.opacity(0.78))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }

                HStack(spacing: 6) {
                    Circle()
                        .fill(viewModel.panoramaxCaptureState == .recording ? .red : .orange)
                        .frame(width: 9, height: 9)
                    Text(viewModel.panoramaxCaptureState == .recording ? "REC" : "VORBEREITUNG")
                        .font(.caption.weight(.bold))
                    Spacer()
                    Text("\(viewModel.panoramaxCaptureCount) Bilder")
                        .font(.caption.weight(.semibold))
                }
                .foregroundStyle(.white)
                .padding(10)
                .background(.black.opacity(0.46), in: Capsule())
                .padding(10)
            }
            .aspectRatio(16.0 / 9.0, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(.white.opacity(0.18), lineWidth: 1)
            }

            HStack(spacing: 8) {
                Image(systemName: "location.fill")
                    .font(.caption.weight(.bold))
                Text(viewModel.panoramaxLastCaptureDetail)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                Spacer()
                if let accuracy = viewModel.panoramaxLastAccuracyMeters {
                    Text("GPS ±\(Int(accuracy.rounded())) m")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.white.opacity(0.72))
                }
            }
            .foregroundStyle(.white.opacity(0.86))
        }
        .padding(10)
        .background(.black.opacity(0.24), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var panoramaxRecorderStateText: String {
        switch viewModel.panoramaxCaptureState {
        case .disabled:
            return "Drive Recorder pausiert"
        case .denied:
            return "Kamerazugriff erlauben"
        case .unavailable, .failed:
            return "Kamera nicht verfuegbar"
        case .preparing:
            return "Kamera wird vorbereitet"
        case .recording:
            return "Drive Recorder aktiv"
        }
    }

    private var topCornerButtons: some View {
        HStack {
            localRecordingsButton

            Spacer()

            gpsSignalBadge
        }
        .foregroundStyle(primaryForegroundColor)
    }

    private var localRecordingsButton: some View {
        Button {
            showingLocalRecordings = true
        } label: {
            Image(systemName: viewModel.isLowSpeedMatchingRuleActive ? "tortoise.fill" : "ladybug.fill")
                .font(.title3.weight(.semibold))
                .frame(width: 44, height: 44)
        }
        .buttonStyle(.plain)
        .background(actionButtonBackgroundColor, in: Circle())
        .overlay {
            Circle()
                .strokeBorder(actionButtonBorderColor, lineWidth: 1.5)
        }
    }

    private var gpsSignalBadge: some View {
        GPSSignalBadge(
            bars: viewModel.gpsSignalBars,
            accuracyText: viewModel.gpsHorizontalAccuracyM.map { String(format: "%.0f m", $0) } ?? nil,
            foregroundColor: primaryForegroundColor
        )
    }

    private func bottomCornerButtons(horizontalPadding: CGFloat) -> some View {
        HStack {
            Button {
                showingLegalInfo = true
            } label: {
                Image(systemName: "info.circle.fill")
                    .font(.title3.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(actionButtonBackgroundColor, in: Circle())
            .overlay {
                Circle()
                    .strokeBorder(actionButtonBorderColor, lineWidth: 1.5)
            }

            Spacer()

            Button {
                showingSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.title3.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(actionButtonBackgroundColor, in: Circle())
            .overlay {
                Circle()
                    .strokeBorder(actionButtonBorderColor, lineWidth: 1.5)
            }
        }
        .padding(.horizontal, horizontalPadding)
        .foregroundStyle(primaryForegroundColor)
    }

    @ViewBuilder
    private func metricStatusBlock(
        primaryFont: CGFloat,
        secondaryFont: CGFloat
    ) -> some View {
        let valueUnitSpacing: CGFloat = 0
        let metricSlotMinHeight = (primaryFont * 1.05) + (secondaryFont * 1.2)

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
                    Text(secondaryMetricText.isEmpty ? " " : secondaryMetricText)
                        .font(.system(size: secondaryFont, weight: .bold, design: .default))
                        .minimumScaleFactor(0.45)
                        .padding(.top, -primaryFont * 0.06)
                        .opacity(secondaryMetricText.isEmpty ? 0 : 1)
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: metricSlotMinHeight, alignment: .center)
        .multilineTextAlignment(.center)
        .foregroundStyle(primaryForegroundColor)
    }

    @ViewBuilder
    private func locationStatusBlock(
        badgeWidth: CGFloat,
        debugFont: CGFloat,
        debugSpacing: CGFloat,
        reservedHeight: CGFloat
    ) -> some View {
        Group {
            if viewModel.isInSpeedCaptureMode {
                Color.clear
            } else if showsLocationBadge {
                CityLimitBadgeView(
                    streetName: cityBadgeStreetText ?? "",
                    placeName: cityBadgePlaceText ?? "",
                    districtName: cityBadgeDistrictText ?? "",
                    highlighted: highlightsCityBadge,
                    foregroundColor: highlightsCityBadge ? .black : primaryForegroundColor,
                    badgeWidth: badgeWidth
                )
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
                .foregroundStyle(primaryForegroundColor)
                .multilineTextAlignment(.center)
                .contentShape(Rectangle())
                .onTapGesture(count: 2) {
                    showingDebug = true
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: reservedHeight, alignment: .center)
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
                return " "
            }
            return "\(Int(round(viewModel.currentSpeedKmh)))"
        }
    }

    private var secondaryMetricText: String {
        if viewModel.isInSpeedCaptureMode {
            return viewModel.speedCaptureSecondaryMetricText ?? "sprechen"
        }
        if let drivingBanMonths = finePresentation?.drivingBanMonths, drivingBanMonths > 0 {
            return NSLocalizedString(drivingBanMonths == 1 ? "penalty.driving_ban.month.one" : "penalty.driving_ban.month.many", comment: "")
        }
        switch finePresentation?.severity {
        case .moneyOnly:
            return viewModel.activePenaltyRules.currencyCode
        case .pointsAndFine:
            if let points = finePresentation?.penaltyPoints {
                return NSLocalizedString(points == 1 ? "penalty.points.one" : "penalty.points.many", comment: "")
            }
            return NSLocalizedString("penalty.points.many", comment: "")
        case .none:
            guard !isSearchingSignal else {
                return NSLocalizedString("metric.searching_signal", comment: "")
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
        if let city = normalizedPlaceText(viewModel.limitCityName ?? viewModel.limitCityPlaceName) {
            return city
        }
        return hasUsableGPSFix ? "Stadt unbekannt" : "Suche..."
    }

    private var limitText: String {
        if let capture = viewModel.speedCaptureSignText {
            return capture
        }
        if let displayText = viewModel.speedLimitDisplayText {
            return displayText
        }
        guard let speedLimit = viewModel.speedLimitKmh else {
            return hasUsableGPSFix ? "–" : "?"
        }
        return "\(speedLimit)"
    }

    private var shouldShowTunnelSignIcon: Bool {
        false
    }

    private var showsUnlimitedAutobahnSign: Bool {
        viewModel.isUnlimitedSpeedLimitActive && !viewModel.isInSpeedCaptureMode
    }

    private var shouldShowTunnelCurrentSpeedIcon: Bool {
        viewModel.isTunnelModeActive && !viewModel.isInSpeedCaptureMode
    }

    private var cityBadgeStreetText: String? {
        normalizedPlaceText(viewModel.limitStreetName)
    }

    private var cityBadgePlaceText: String? {
        normalizedPlaceText(viewModel.limitCityPlaceName)
            ?? normalizedPlaceText(viewModel.limitCityName)
    }

    private var cityBadgeDistrictText: String? {
        normalizedPlaceText(viewModel.limitCityDistrictName)
    }

    private var showsLocationBadge: Bool {
        guard !viewModel.isInSpeedCaptureMode else {
            return false
        }
        return cityBadgeStreetText != nil || cityBadgePlaceText != nil || cityBadgeDistrictText != nil
    }

    private var highlightsCityBadge: Bool {
        viewModel.lastLookupInsideCity == true
    }

    private var finePresentation: SpeedPenaltyNotice? {
        viewModel.currentPenaltyNotice
    }

    private var screenBackgroundColor: Color {
        if showsUnlimitedAutobahnSign {
            return Color(red: 0.03, green: 0.33, blue: 0.78)
        }
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
            if viewModel.isScreenshotMode {
                drivingBanPulseBackgroundColor(at: Date(timeIntervalSinceReferenceDate: 0))
            } else {
                TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { timeline in
                    drivingBanPulseBackgroundColor(at: timeline.date)
                }
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

    private var actionButtonBackgroundColor: Color {
        if viewModel.isInSpeedCaptureMode {
            return Color.black.opacity(0.08)
        }
        if usesDarkForeground {
            return Color.black.opacity(0.08)
        }
        return Color.white.opacity(0.14)
    }

    private var actionButtonBorderColor: Color {
        primaryForegroundColor.opacity(0.95)
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
        if showsUnlimitedAutobahnSign {
            return true
        }
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
    let showsUnlimitedIcon: Bool
    let showsPedestrianZoneIcon: Bool

    var body: some View {
        GeometryReader { proxy in
            let size = min(proxy.size.width, proxy.size.height)
            let unlimitedBorderWidth = max(2, size * 0.028)
            let unlimitedFaceDiameter = max(1, size - (2 * unlimitedBorderWidth))
            let standardBlackBorderWidth = max(1, size * 0.0175)
            let standardRedBandWidth = max(2, size * 0.134)
            let standardInnerDiameter = max(1, size - (2 * (standardBlackBorderWidth + standardRedBandWidth)))
            ZStack {
                if showsUnlimitedIcon {
                    Circle()
                        .fill(Color.white)

                    Circle()
                        .strokeBorder(Color.black.opacity(0.82), lineWidth: unlimitedBorderWidth)

                    ZStack {
                        ForEach(0..<5, id: \.self) { index in
                            Rectangle()
                                .fill(Color.black.opacity(0.34))
                                .frame(width: max(3, size * 0.028), height: unlimitedFaceDiameter * 1.65)
                                .rotationEffect(.degrees(51))
                                .offset(x: (CGFloat(index) - 2) * unlimitedFaceDiameter * 0.07)
                        }
                    }
                    .frame(width: unlimitedFaceDiameter, height: unlimitedFaceDiameter)
                    .clipShape(
                        Circle().inset(by: unlimitedBorderWidth * 0.22)
                    )
                } else if showsPedestrianZoneIcon {
                    Image("PedestrianZoneSign")
                        .resizable()
                        .interpolation(.high)
                        .antialiased(true)
                        .accessibilityLabel("Fussgaengerzone")
                } else {
                    // Based on Zeichen 274 geometry: black border 7.875 / 450, red band 60.301 / 450.
                    Circle()
                        .fill(Color.white)

                    Circle()
                        .strokeBorder(Color.black.opacity(0.75), lineWidth: standardBlackBorderWidth)

                    Circle()
                        .inset(by: standardBlackBorderWidth)
                        .strokeBorder(Color(red: 0.76, green: 0.07, blue: 0.11), lineWidth: standardRedBandWidth)

                    if showsTunnelIcon {
                        Image(systemName: "tunnel.fill")
                            .font(.system(size: standardInnerDiameter * 0.42, weight: .bold))
                            .foregroundStyle(.black)
                    } else {
                        Text(limitText)
                            .font(trafficSignNumberFont(size: numberFontSize))
                            .frame(width: standardInnerDiameter * 0.86, height: standardInnerDiameter * 0.66, alignment: .center)
                            .minimumScaleFactor(0.28)
                            .allowsTightening(true)
                            .foregroundStyle(.black)
                            .lineLimit(1)
                    }
                }
            }
            .frame(width: size, height: size)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

private struct GPSSignalBadge: View {
    let bars: Int
    let accuracyText: String?
    let foregroundColor: Color

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            Image(systemName: signalSymbolName)
                .font(.title3.weight(.semibold))
                .frame(width: 44, height: 44)
            Text(accuracyText ?? " ")
                .font(.caption2.monospacedDigit())
                .opacity(accuracyText == nil ? 0 : 1)
        }
        .frame(minHeight: gpsBadgeSlotMinHeight, alignment: .topTrailing)
        .foregroundStyle(foregroundColor)
    }

    private var signalSymbolName: String {
        switch bars {
        case 4:
            return "wifi"
        case 3:
            return "wifi"
        case 2:
            return "wifi.exclamationmark"
        case 1:
            return "wifi.slash"
        default:
            return "wifi.slash"
        }
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
        let bundles = [bundle, Bundle(for: SpeedConsumerAppDelegate.self)]
        for candidateBundle in bundles {
            guard let url = candidateBundle.url(forResource: "legal", withExtension: "txt"),
                  let text = try? String(contentsOf: url, encoding: .utf8) else {
                continue
            }
            return text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return "Rechtliche Hinweise konnten nicht geladen werden."
    }
}

private struct CityLimitBadgeView: View {
    let streetName: String
    let placeName: String
    let districtName: String
    let highlighted: Bool
    let foregroundColor: Color
    let badgeWidth: CGFloat

    var body: some View {
        VStack(spacing: 2) {
            badgeLine(streetName, size: 18, weight: .bold)
            badgeLine(placeName, size: 17, weight: .bold)
            badgeLine(districtName, size: 16, weight: .semibold)
        }
        .foregroundStyle(foregroundColor)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(width: badgeWidth)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(highlighted ? Color(red: 0.97, green: 0.86, blue: 0.30) : .clear)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(highlighted ? Color.black.opacity(0.9) : .clear, lineWidth: 2)
        )
    }

    private func badgeLine(_ text: String, size: CGFloat, weight: Font.Weight) -> some View {
        Text(text.isEmpty ? " " : text)
            .font(.system(size: size, weight: weight, design: .default))
            .lineLimit(1)
            .truncationMode(.tail)
            .opacity(text.isEmpty ? 0 : 1)
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
            Text(NSLocalizedString("recordings.instructions", comment: ""))
                .font(.footnote)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 6)

            NavigationLink {
                PanoramaxReviewView(viewModel: viewModel)
            } label: {
                HStack {
                    Image(systemName: "camera.aperture")
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Panoramax-Bilder")
                            .font(.subheadline.weight(.semibold))
                        Text("\(viewModel.panoramaxBatches.reduce(0) { $0 + $1.items.count }) lokale Bilder pruefen")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .padding(.horizontal, 16)
            }
            .buttonStyle(.plain)

            List {
                if viewModel.localObservations.isEmpty {
                    Text(NSLocalizedString("recordings.empty", comment: ""))
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
                                Text(String(
                                    format: NSLocalizedString("recordings.way_id", comment: ""),
                                    observation.roadCandidateIDs.first ?? "n/a"
                                ))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                HStack(spacing: 10) {
                                    Text(String(
                                        format: NSLocalizedString("recordings.old_value", comment: ""),
                                        observation.oldSpeedKmh.map(String.init) ?? "n/a"
                                    ))
                                    Text(String(
                                        format: NSLocalizedString("recordings.new_value", comment: ""),
                                        observation.newSpeedKmh.map(String.init) ?? observation.value ?? "n/a"
                                    ))
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
                            .accessibilityLabel(NSLocalizedString("recordings.delete_entry", comment: ""))
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
                    Text(NSLocalizedString("recordings.export_osc", comment: ""))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)

                Button(role: .destructive) {
                    viewModel.deleteAllLocalObservations()
                } label: {
                    Label(NSLocalizedString("recordings.delete_all", comment: ""), systemImage: "trash")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 12)
        }
        .navigationTitle(NSLocalizedString("recordings.title", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(NSLocalizedString("common.done", comment: "")) {
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

private struct PanoramaxReviewView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var uploadConfirmationBatchID: String?

    var body: some View {
        List {
            if viewModel.panoramaxBatches.isEmpty {
                ContentUnavailableView(
                    "Keine Panoramax-Bilder",
                    systemImage: "camera.aperture",
                    description: Text("Aktiviere den Drive Recorder waehrend einer Fahrt.")
                )
            } else {
                ForEach(viewModel.panoramaxBatches, id: \.batchID) { batch in
                    Section {
                        ForEach(batch.items, id: \.itemID) { item in
                            PanoramaxReviewItemRow(batch: batch, item: item, viewModel: viewModel)
                        }
                    } header: {
                        HStack {
                            Text(batch.createdAt.formatted(date: .abbreviated, time: .shortened))
                            Spacer()
                            Text(batch.state.rawValue.replacingOccurrences(of: "_", with: " "))
                        }
                    } footer: {
                        let included = batch.items.filter { $0.state != .excluded }.count
                        if batch.state == .awaitingReview, included > 0 {
                            Button("Batch fuer Upload freigeben") {
                                viewModel.approvePanoramaxBatch(batchID: batch.batchID)
                            }
                        } else if (batch.state == .approved || batch.state == .partial), included > 0 {
                            Button("Jetzt zu Panoramax hochladen") {
                                uploadConfirmationBatchID = batch.batchID
                            }
                            if let status = viewModel.panoramaxUploadStatus(for: batch.batchID) {
                                Text(status)
                            } else {
                                Text("Bereit fuer den ausdruecklichen Upload")
                            }
                        } else {
                            Text("\(included) Bilder ausgewaehlt")
                        }
                    }
                }
            }
        }
        .navigationTitle("Panoramax-Bilder")
        .navigationBarTitleDisplayMode(.inline)
        .task { viewModel.refreshPanoramaxBatches() }
        .alert("Bilder zu Panoramax hochladen?", isPresented: Binding(
            get: { uploadConfirmationBatchID != nil },
            set: { if !$0 { uploadConfirmationBatchID = nil } }
        )) {
            Button("Upload starten") {
                if let batchID = uploadConfirmationBatchID {
                    viewModel.uploadPanoramaxBatch(batchID: batchID)
                }
                uploadConfirmationBatchID = nil
            }
            Button("Abbrechen", role: .cancel) { uploadConfirmationBatchID = nil }
        } message: {
            Text("Die ausgewaehlten Originalbilder und ihre GPS-Metadaten werden an die konfigurierte Panoramax-Instanz uebertragen.")
        }
    }
}

private struct PanoramaxReviewItemRow: View {
    let batch: PanoramaxBatchRecord
    let item: PanoramaxItemRecord
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var showingOriginal = false

    private var included: Bool { item.state != .excluded }

    var body: some View {
        HStack(spacing: 12) {
            Button { showingOriginal = true } label: {
                thumbnail
                    .frame(width: 112, height: 64)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 4) {
                Text(item.metadata.capturedAt.formatted(date: .omitted, time: .standard))
                    .font(.caption.weight(.semibold))
                Text(String(format: "%.5f, %.5f", item.metadata.location.latitude, item.metadata.location.longitude))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                if let heading = item.metadata.location.headingDegrees {
                    Text(String(format: "Blickrichtung %.0f°", heading))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                Text(included ? "Eingeschlossen" : "Ausgeschlossen")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(included ? .green : .secondary)
            }
            Spacer(minLength: 0)
            Button {
                viewModel.setPanoramaxItemIncluded(batchID: batch.batchID, itemID: item.itemID, included: !included)
            } label: {
                Image(systemName: included ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(included ? .green : .secondary)
            }
            .buttonStyle(.plain)
            Button(role: .destructive) {
                viewModel.deletePanoramaxItem(batchID: batch.batchID, itemID: item.itemID)
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.plain)
        }
        .sheet(isPresented: $showingOriginal) {
            NavigationStack {
                if let url = viewModel.panoramaxOriginalURL(for: item),
                   let image = UIImage(contentsOfFile: url.path) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .padding()
                        .navigationTitle("Panoramax-Bild")
                        .navigationBarTitleDisplayMode(.inline)
                } else {
                    ContentUnavailableView("Bild nicht verfuegbar", systemImage: "photo")
                }
            }
        }
    }

    @ViewBuilder
    private var thumbnail: some View {
        if let url = viewModel.panoramaxThumbnailURL(for: item),
           let image = UIImage(contentsOfFile: url.path) {
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
        } else {
            Color.secondary.opacity(0.2)
                .overlay { Image(systemName: "photo").foregroundStyle(.secondary) }
        }
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
    @ObservedObject var account: PanoramaxAccountModel
    @State private var showingDeleteDownloadedBundlesConfirm = false

    var body: some View {
        Form {
            Section(NSLocalizedString("settings.audio.section", comment: "")) {
                Toggle(NSLocalizedString("settings.audio.voice_output", comment: ""), isOn: $viewModel.audioAlertsEnabled)

                HStack {
                    Text(NSLocalizedString("settings.audio.warning_from", comment: ""))
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
                    Text(NSLocalizedString("settings.audio.adjust_threshold", comment: ""))
                    Spacer()
                    Stepper("", value: $viewModel.audioAlertThresholdKmh, in: 0...80, step: 1)
                        .labelsHidden()
                }
                .disabled(!viewModel.audioAlertsEnabled)

                Text(audioHintText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section("Panoramax Drive Recorder") {
                Toggle("Strassenbilder beitragen", isOn: $viewModel.panoramaxCaptureEnabled)

                Text("Nimmt waehrend der Fahrt vollstaendige Bilder der Rueckkamera auf und speichert sie zuerst nur auf diesem iPhone.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                LabeledContent("Status", value: panoramaxStatusText)
                LabeledContent("Gespeicherte Bilder", value: "\(viewModel.panoramaxCaptureCount)")

                if let accuracy = viewModel.panoramaxLastAccuracyMeters {
                    Text("Neue Bilder werden erst nach mindestens 2 × GPS-Genauigkeit (aktuell ±\(Int(accuracy.rounded())) m) aufgenommen.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Neue Bilder werden nur bei ausreichender GPS-Genauigkeit und mindestens 2 × GPS-Genauigkeit Bewegung aufgenommen.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Panoramax-Konto") {
                TextField("Instanz (https://...)", text: $account.instanceOrigin)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)

                Text("Es gibt keinen YouSpeed-API-Key. Die Anmeldung ist pro Panoramax-Instanz und wird als geschuetztes JWT im iOS-Schluesselbund gespeichert.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                LabeledContent("Status", value: account.status)

                if account.isConnected {
                    Button("Konto trennen", role: .destructive) {
                        account.disconnect()
                    }
                } else {
                    Button("Instanz verbinden") {
                        account.connect()
                    }
                    Button("Verbindung pruefen") {
                        account.validateConnection()
                    }
                }
            }

            Section(NSLocalizedString("settings.maps.section", comment: "")) {
                LabeledContent(NSLocalizedString("settings.maps.status", comment: ""), value: syncStatusLabel)
                LabeledContent(NSLocalizedString("settings.maps.bundle", comment: ""), value: viewModel.activeBundleVersion)

                if let syncMessage = syncMessageLine {
                    Text(syncMessage.text)
                        .font(.footnote)
                        .foregroundStyle(syncMessage.color)
                }

                Text(NSLocalizedString("settings.maps.description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                if viewModel.bundleDownloadSections.isEmpty {
                    Text(NSLocalizedString("settings.maps.no_downloads", comment: ""))
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
                    Text(NSLocalizedString("settings.maps.delete_downloads", comment: ""))
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
        .navigationTitle(NSLocalizedString("settings.title", comment: ""))
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

    private var audioHintText: String {
        if !viewModel.audioAlertsEnabled {
            return NSLocalizedString("settings.audio.voice_disabled", comment: "")
        }
        if viewModel.audioAlertThresholdKmh == 0 {
            return NSLocalizedString("settings.audio.alerts_disabled", comment: "")
        }
        return String(
            format: NSLocalizedString("settings.audio.threshold_description", comment: ""),
            viewModel.audioAlertThresholdKmh
        )
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

    private var panoramaxStatusText: String {
        switch viewModel.panoramaxCaptureState {
        case .disabled:
            return viewModel.panoramaxCaptureEnabled ? "Bereit fuer die naechste Fahrt" : "Aus"
        case .preparing:
            return "Kamera wird vorbereitet"
        case .recording:
            return "Aufnahme aktiv"
        case .denied:
            return "Kamerazugriff verweigert"
        case .unavailable:
            return "Kamera nicht verfuegbar"
        case .failed:
            return "Fehler"
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
    @State private var shareItem: LocalDebugShareItem?
    @State private var showingClearDrivingLogConfirm = false

    private struct LocalDebugShareItem: Identifiable {
        let id = UUID()
        let url: URL
    }

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

            Section("Logs") {
                if let gpsLogURL {
                    Button("GPS-CSV teilen") {
                        shareItem = LocalDebugShareItem(url: gpsLogURL)
                    }
                }
                if let matchLogURL {
                    Button("Matcher-Log teilen") {
                        shareItem = LocalDebugShareItem(url: matchLogURL)
                    }
                }
                if gpsLogURL != nil || matchLogURL != nil {
                    Button("Fahrlog leeren", role: .destructive) {
                        showingClearDrivingLogConfirm = true
                    }
                }
                if gpsLogURL == nil && matchLogURL == nil {
                    Text("Noch keine Logdateien vorhanden.")
                        .foregroundStyle(.secondary)
                }
            }

            Section("Matcher") {
                Picker("Profil", selection: $viewModel.matcherDebugProfile) {
                    ForEach(MatcherDebugProfile.allCases) { profile in
                        Text(profile.debugLabel).tag(profile)
                    }
                }
                Text("Aktiv: \(viewModel.matcherDebugProfile.debugLabel)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !viewModel.lastCandidateTraces.isEmpty {
                Section("Matcher-Kandidaten") {
                    ForEach(Array(viewModel.lastCandidateTraces.enumerated()), id: \.offset) { _, trace in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("#\(trace.rank) \(trace.streetName ?? trace.wayID ?? "n/a")")
                                .font(.subheadline.weight(.semibold))
                            Text(
                                trace.geometryScore.map { geometryScore in
                                    "way \(trace.wayID ?? "n/a") score \(String(format: "%.1f", trace.score)) geom \(String(format: "%.1f", geometryScore)) dist \(String(format: "%.1f m", trace.distanceM))"
                                } ?? "way \(trace.wayID ?? "n/a") score \(String(format: "%.1f", trace.score)) dist \(String(format: "%.1f m", trace.distanceM))"
                            )
                                .font(.caption.monospacedDigit())
                            Text(
                                "continuity \(trace.continuityClass) corridor \((trace.corridorSelectable ?? true) ? "ok" : "blocked") tunnel \(trace.tunnelSelectable ? "ok" : "blocked")\(trace.isSelected ? " selected" : "")"
                            )
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(trace.isSelected ? .green : .secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }
            }

            if !viewModel.lastSelectionTrace.isEmpty {
                Section("Inference Chain") {
                    ForEach(Array(viewModel.lastSelectionTrace.enumerated()), id: \.offset) { _, item in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.step)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                            Text(item.detail)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                        }
                        .padding(.vertical, 2)
                    }
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
        .alert("Fahrlog leeren?", isPresented: $showingClearDrivingLogConfirm) {
            Button("Abbrechen", role: .cancel) {}
            Button("Leeren", role: .destructive) {
                viewModel.clearDrivingLogs()
            }
        } message: {
            Text("GPS-CSV und Matcher-Log werden geleert. Neue Fahrdaten werden anschliessend wieder normal aufgezeichnet.")
        }
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
        .sheet(item: $shareItem) { item in
            ShareSheet(activityItems: [item.url])
        }
    }

    private var hasUsableFix: Bool {
        viewModel.gpsFixCount > 0 &&
        viewModel.currentLatitude != nil &&
        viewModel.currentLongitude != nil
    }

    private var fixRows: [(key: String, value: String)] {
        let speed = String(format: "%.1f km/h", viewModel.currentSpeedKmh)
        let limitText = viewModel.speedLimitDisplayText ?? viewModel.speedLimitKmh.map { "\($0) km/h" } ?? "n/a"
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
            ("GPS-Signal", "\(viewModel.gpsSignalBars)/4"),
            ("Horizontal", viewModel.gpsHorizontalAccuracyM.map { String(format: "%.1f m", $0) } ?? "n/a"),
            ("Matcher", viewModel.matcherDebugProfile.debugLabel),
            ("Tunnel-Modus", viewModel.tunnelModeState.rawValue),
            ("Innerorts", viewModel.lastLookupInsideCity.map { $0 ? "ja" : "nein" } ?? "n/a"),
            ("Lookup", viewModel.lastLookupStatus),
            ("Query", String(format: "%.3f ms", viewModel.lastLookupQueryMs)),
            ("Kandidaten", "\(viewModel.lastLookupCandidateCount)"),
            ("Mit Limit", "\(viewModel.lastLookupSpeedCandidateCount)"),
            ("Trace-Kandidaten", "\(viewModel.lastCandidateTraces.count)"),
            ("Distanz Weg", viewModel.lastLookupNearestCandidateM.map { String(format: "%.1f m", $0) } ?? "n/a"),
            ("Distanz Limit-Weg", viewModel.lastLookupNearestSpeedCandidateM.map { String(format: "%.1f m", $0) } ?? "n/a"),
            ("Stadtquelle", viewModel.lastLookupCitySource),
            ("Stadt-Resolve", String(format: "%.3f ms", viewModel.lastLookupCityResolveMs)),
            ("GPS-Log", viewModel.gpsLogPath.isEmpty ? "n/a" : viewModel.gpsLogPath),
            ("Matcher-Log", viewModel.matchLogPath.isEmpty ? "n/a" : viewModel.matchLogPath),
            ("Manifest-Endpunkte", "\(viewModel.configuredManifestEndpointCount)"),
            ("Manifest-Länder", viewModel.configuredManifestCountryCodes),
        ]
    }

    private var gpsLogURL: URL? {
        guard !viewModel.gpsLogPath.isEmpty else {
            return nil
        }
        return URL(fileURLWithPath: viewModel.gpsLogPath)
    }

    private var matchLogURL: URL? {
        guard !viewModel.matchLogPath.isEmpty else {
            return nil
        }
        return URL(fileURLWithPath: viewModel.matchLogPath)
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

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

enum DriveRecorderWorkspaceSelection: Equatable {
    case preview
    case telemetry

    func showsPreview(whenAvailable previewAvailable: Bool) -> Bool {
        self == .preview && previewAvailable
    }
}

struct DriveRecorderPreviewPresentation: Equatable {
    let isAttached: Bool
    let isVisible: Bool

    static func resolve(
        sessionAvailable: Bool,
        selection: DriveRecorderWorkspaceSelection,
        previewAvailable: Bool
    ) -> Self {
        Self(
            // The preview layer is a permanent fourth camera consumer. It must
            // be attached before movie recording begins because attaching it
            // afterward reconfigures the active AVFoundation capture graph.
            isAttached: sessionAvailable,
            isVisible: sessionAvailable && selection.showsPreview(whenAvailable: previewAvailable)
        )
    }
}

enum DriveRecorderPreviewInteractionPolicy {
    static let activationTapGuardInterval: TimeInterval = 0.6

    static func canDismissPreview(at date: Date, notBefore: Date) -> Bool {
        date >= notBefore
    }
}

struct DriveRecorderMainControlPresentation: Equatable {
    enum Action: Equatable {
        case start
        case stop
    }

    let action: Action
    let isEnabled: Bool

    static func resolve(for state: DriveRecorderState) -> Self {
        switch state {
        case .disabled, .denied, .unavailable, .failed:
            return Self(action: .start, isEnabled: true)
        case .preparing, .recording:
            return Self(action: .stop, isEnabled: true)
        case .stopping:
            return Self(action: .stop, isEnabled: false)
        }
    }

    var systemImageName: String {
        action == .start ? "circle.fill" : "stop.fill"
    }

    var usesRedIcon: Bool {
        action == .stop
    }

    var accessibilityLocalizationKey: String {
        action == .start ? "drive_recorder.start" : "drive_recorder.stop"
    }
}

struct DriveRecorderGalleryControlPresentation: Equatable {
    let isEnabled: Bool

    static func resolve(for state: DriveRecorderState) -> Self {
        switch state {
        case .preparing, .recording, .stopping:
            return Self(isEnabled: false)
        case .disabled, .denied, .unavailable, .failed:
            return Self(isEnabled: true)
        }
    }

    var opacity: Double {
        isEnabled ? 1 : 0.38
    }
}

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
    @Environment(\.accessibilityReduceMotion) private var accessibilityReduceMotion
    var openSettingsOnAppear: Bool = false
    var onOpenSettingsConsumed: (() -> Void)?
    @State private var hasAutoTriggeredSyncForTests = false
    @State private var showingSettings = false
    @State private var showingLegalInfo = false
    @State private var showingDebug = false
    @State private var showingLocalRecordings = false
    @State private var showingPanoramaxGallery = false
    @State private var showingTrafficSignDetails = false
    // Keep the user's selection independent from transient recorder
    // availability. Published recorder fields arrive one after another; if a
    // short unavailable state overwrites this preference, the preview flashes
    // once and then incorrectly stays hidden.
    @State private var driveRecorderWorkspaceSelection: DriveRecorderWorkspaceSelection = .preview
    @State private var driveRecorderPreviewDismissalAllowedAt = Date.distantPast

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
            let topControlBottom = topPadding + 62
            let bottomControlTopInset = bottomPadding + controlDiameter
            let contentTopInset = topControlBottom + max(10, minDimension * 0.028)
            let recorderStatusReserve: CGFloat = showsDriveRecorderStatusStrip ? 68 : 0
            let contentBottomInset = bottomControlTopInset + recorderStatusReserve + max(10, minDimension * 0.03)
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

                    driveStatusWorkspace(
                        primaryFont: primaryMetricFontSize,
                        secondaryFont: secondaryFont,
                        badgeWidth: bottomButtonGapWidth,
                        debugFont: debugFont,
                        debugSpacing: debugSpacing,
                        reservedHeight: locationReserve,
                        sectionGap: sectionGap
                    )
                    .padding(.horizontal, horizontalPadding)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .padding(.top, contentTopInset)
                .padding(.bottom, contentBottomInset)

                topCornerButtons
                    .padding(.horizontal, screenInset)
                    .padding(.top, topPadding)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)

                if showsDriveRecorderStatusStrip {
                    driveRecorderStatusStrip
                        .padding(.horizontal, max(12, horizontalPadding * 0.72))
                        .padding(.bottom, bottomPadding + controlDiameter + 8)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                }

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
        .sheet(isPresented: $showingPanoramaxGallery) {
            NavigationStack {
                PanoramaxGalleryView(viewModel: viewModel)
            }
        }
        .sheet(isPresented: $showingTrafficSignDetails) {
            NavigationStack {
                TrafficSignRecognitionDetailsView(viewModel: viewModel)
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
        .onChange(of: viewModel.driveRecorderDashcamActive) { previousValue, active in
            if active != previousValue {
                // Each new Dashcam selection defaults to the confidence view.
                // When Dashcam stops, keep the same default ready for the next
                // segment without forcing a visible transition now.
                setDriveRecorderPreviewVisible(true)
            }
        }
        .onChange(of: viewModel.driveRecorderState) { previousState, state in
            if state == .recording, previousState != .recording {
                setDriveRecorderPreviewVisible(true)
            }
        }
    }

    private var showsPedestrianZoneSign: Bool {
        !viewModel.isInSpeedCaptureMode && viewModel.speedLimitDisplayText == "Schritt"
    }

    private var topCornerButtons: some View {
        HStack(alignment: .top) {
            localRecordingsButton

            Spacer()

            trafficSignRecognitionBadge
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

    private func bottomCornerButtons(horizontalPadding: CGFloat) -> some View {
        let recorderControl = DriveRecorderMainControlPresentation.resolve(
            for: viewModel.driveRecorderState
        )
        let galleryControl = DriveRecorderGalleryControlPresentation.resolve(
            for: viewModel.driveRecorderState
        )

        return HStack {
            Button {
                viewModel.toggleDriveRecorder()
            } label: {
                Image(systemName: recorderControl.systemImageName)
                    .font(.title3.weight(.bold))
                    .foregroundStyle(recorderControl.usesRedIcon ? Color.red : Color.white)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(Color.black, in: Circle())
            .overlay {
                Circle()
                    .strokeBorder(Color.white, lineWidth: 1.5)
            }
            .contentShape(Circle())
            .accessibilityLabel(NSLocalizedString(recorderControl.accessibilityLocalizationKey, comment: ""))
            .disabled(!recorderControl.isEnabled)

            Spacer()

            Button {
                guard galleryControl.isEnabled else { return }
                showingPanoramaxGallery = true
            } label: {
                Image(systemName: "photo.on.rectangle")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(galleryControl.isEnabled ? primaryForegroundColor : Color.gray)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(
                galleryControl.isEnabled ? actionButtonBackgroundColor : Color.gray.opacity(0.16),
                in: Circle()
            )
            .overlay {
                Circle().strokeBorder(
                    galleryControl.isEnabled ? actionButtonBorderColor : Color.gray.opacity(0.6),
                    lineWidth: 1.5
                )
            }
            .contentShape(Circle())
            .opacity(galleryControl.opacity)
            .accessibilityLabel(NSLocalizedString("panoramax.gallery.open", comment: ""))
            .disabled(!galleryControl.isEnabled)

            Spacer()

            Button { showingLegalInfo = true } label: {
                Image(systemName: "info.circle.fill")
                    .font(.title3.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(actionButtonBackgroundColor, in: Circle())
            .overlay { Circle().strokeBorder(actionButtonBorderColor, lineWidth: 1.5) }

            Spacer()

            Button { showingSettings = true } label: {
                Image(systemName: "gearshape.fill")
                    .font(.title3.weight(.semibold))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .background(actionButtonBackgroundColor, in: Circle())
            .overlay { Circle().strokeBorder(actionButtonBorderColor, lineWidth: 1.5) }
        }
        .padding(.horizontal, horizontalPadding)
        .foregroundStyle(primaryForegroundColor)
    }

    private var trafficSignRecognitionBadge: some View {
        Button {
            showingTrafficSignDetails = true
        } label: {
            VStack(spacing: 1) {
                HStack(spacing: 4) {
                    Image(systemName: "camera.viewfinder")
                        .font(.caption2.weight(.bold))
                    Text(NSLocalizedString("tsr.badge.title", comment: ""))
                        .font(.caption2.weight(.bold))
                        .lineLimit(1)
                }

                Text(trafficSignRecognitionValueText)
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .lineLimit(1)

                Text(trafficSignRecognitionStatusText)
                    .font(.system(size: 9, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
            .foregroundStyle(primaryForegroundColor)
            .frame(width: 96, height: 58)
            .background(actionButtonBackgroundColor, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(trafficSignRecognitionAccentColor, lineWidth: 2)
            }
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(trafficSignRecognitionAccessibilityLabel)
        .accessibilityHint(NSLocalizedString("tsr.details.open", comment: ""))
    }

    private var driveRecorderStatusStrip: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: 7) {
                HStack(spacing: 6) {
                    Circle()
                        .fill(viewModel.driveRecorderState == .recording ? Color.red : Color.orange)
                        .frame(width: 9, height: 9)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(driveRecorderStateText.uppercased())
                            .font(.caption2.weight(.bold))
                        Text(driveRecorderElapsedText(at: context.date))
                            .font(.caption.monospacedDigit().weight(.semibold))
                    }
                }
                .accessibilityElement(children: .combine)

                Spacer(minLength: 0)

                driveRecorderModuleButton(
                    symbol: "video.fill",
                    label: NSLocalizedString("drive_recorder.status.dashcam", comment: ""),
                    selected: viewModel.driveRecorderDashcamActive || viewModel.driveRecorderDashcamTransitioning,
                    active: viewModel.driveRecorderDashcamActive,
                    available: viewModel.driveRecorderDashcamAvailable,
                    transitioning: viewModel.driveRecorderDashcamTransitioning
                ) {
                    _ = viewModel.toggleDriveRecorderDashcam()
                }

                driveRecorderModuleButton(
                    symbol: trafficSignRecognitionModuleSymbol,
                    label: NSLocalizedString("drive_recorder.status.tsr", comment: ""),
                    selected: viewModel.trafficSignRecognitionEnabled,
                    active: viewModel.driveRecorderTrafficSignRecognitionActive,
                    available: viewModel.driveRecorderTrafficSignRecognitionAvailable,
                    transitioning: false
                ) {
                    if !viewModel.toggleDriveRecorderTrafficSignRecognition() {
                        showingTrafficSignDetails = true
                    }
                }

                driveRecorderModuleIndicator(
                    symbol: "photo.stack.fill",
                    label: NSLocalizedString("drive_recorder.status.panoramax", comment: ""),
                    enabled: viewModel.driveRecorderPanoramaxActive,
                    detail: viewModel.driveRecorderPanoramaxActive ? "\(viewModel.panoramaxCaptureCount)" : nil
                )
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .foregroundStyle(primaryForegroundColor)
            .background(actionButtonBackgroundColor, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(actionButtonBorderColor.opacity(0.85), lineWidth: 1.5)
            }
            .accessibilityElement(children: .contain)
        }
    }

    private var showsDriveRecorderStatusStrip: Bool {
        viewModel.driveRecorderState != .disabled
    }

    private func driveRecorderModuleIndicator(
        symbol: String,
        label: String,
        enabled: Bool,
        detail: String? = nil
    ) -> some View {
        VStack(spacing: 1) {
            HStack(spacing: 3) {
                Image(systemName: enabled ? symbol : "circle.slash")
                    .font(.caption.weight(.semibold))
                if let detail {
                    Text(detail)
                        .font(.caption2.monospacedDigit().weight(.bold))
                }
            }
            Text(label)
                .font(.system(size: 9, weight: .semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .frame(minWidth: 48, minHeight: 44)
        .opacity(enabled ? 1 : 0.55)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label), \(NSLocalizedString(enabled ? "drive_recorder.status.on" : "drive_recorder.status.off", comment: ""))")
    }

    private func driveRecorderModuleButton(
        symbol: String,
        label: String,
        selected: Bool,
        active: Bool,
        available: Bool,
        transitioning: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 1) {
                if transitioning {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(primaryForegroundColor)
                } else {
                    Image(systemName: active ? symbol : (available ? "circle.slash" : "exclamationmark.triangle.fill"))
                        .font(.caption.weight(.semibold))
                }
                Text(label)
                    .font(.system(size: 9, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            .frame(minWidth: 50, minHeight: 44)
            .contentShape(Rectangle())
            .background(
                active ? Color.red.opacity(0.16) : (selected ? Color.orange.opacity(0.16) : Color.clear),
                in: RoundedRectangle(cornerRadius: 9, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .strokeBorder(
                        active ? Color.red.opacity(0.9) : (selected ? Color.orange.opacity(0.9) : Color.clear),
                        lineWidth: 1.5
                    )
            }
            .opacity(active || selected || transitioning ? 1 : 0.62)
        }
        .buttonStyle(.plain)
        .disabled(!viewModel.canToggleDriveRecorderModules || transitioning)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityValue(driveRecorderModuleAccessibilityValue(
            active: active,
            selected: selected,
            available: available,
            transitioning: transitioning
        ))
        .accessibilityHint(NSLocalizedString("drive_recorder.status.toggle_hint", comment: ""))
    }

    private func driveRecorderModuleAccessibilityValue(
        active: Bool,
        selected: Bool,
        available: Bool,
        transitioning: Bool
    ) -> String {
        if transitioning {
            return NSLocalizedString("drive_recorder.status.changing", comment: "")
        }
        if !available {
            return NSLocalizedString(
                selected ? "drive_recorder.status.selected_unavailable" : "drive_recorder.status.unavailable",
                comment: ""
            )
        }
        return NSLocalizedString(active ? "drive_recorder.status.on" : "drive_recorder.status.off", comment: "")
    }

    private var driveRecorderStateText: String {
        switch viewModel.driveRecorderState {
        case .disabled:
            return NSLocalizedString("drive_recorder.state.ready", comment: "")
        case .preparing:
            return NSLocalizedString("drive_recorder.state.preparing", comment: "")
        case .recording:
            return NSLocalizedString("drive_recorder.state.recording", comment: "")
        case .stopping:
            return NSLocalizedString("drive_recorder.state.stopping", comment: "")
        case .denied:
            return NSLocalizedString("drive_recorder.state.denied", comment: "")
        case .unavailable:
            return NSLocalizedString("drive_recorder.state.unavailable", comment: "")
        case .failed:
            return NSLocalizedString("drive_recorder.state.failed", comment: "")
        }
    }

    private func driveRecorderElapsedText(at date: Date) -> String {
        guard let startedAt = viewModel.driveRecorderStartedAt else {
            return "00:00"
        }
        let elapsed = max(0, Int(date.timeIntervalSince(startedAt)))
        let hours = elapsed / 3_600
        let minutes = (elapsed % 3_600) / 60
        let seconds = elapsed % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%02d:%02d", minutes, seconds)
    }

    private var trafficSignRecognitionValueText: String {
        switch viewModel.trafficSignRecognitionState {
        case .disabled, .noRecognition:
            return "—"
        case .unavailable:
            return "×"
        case .provisional(let value), .confirmed(let value):
            return "\(value)"
        case .unknown:
            return "?"
        }
    }

    private var trafficSignRecognitionStatusText: String {
        switch viewModel.trafficSignRecognitionState {
        case .disabled:
            return NSLocalizedString("tsr.state.disabled", comment: "")
        case .unavailable:
            return NSLocalizedString("tsr.state.unavailable", comment: "")
        case .noRecognition:
            return NSLocalizedString("tsr.state.no_recognition", comment: "")
        case .provisional:
            return NSLocalizedString("tsr.state.provisional", comment: "")
        case .confirmed:
            return NSLocalizedString("tsr.state.confirmed", comment: "")
        case .unknown:
            return NSLocalizedString("tsr.state.unknown", comment: "")
        }
    }

    private var trafficSignRecognitionAccentColor: Color {
        switch viewModel.trafficSignRecognitionState {
        case .confirmed:
            return .green
        case .provisional, .unknown:
            return .orange
        case .unavailable:
            return .red
        case .disabled, .noRecognition:
            return actionButtonBorderColor.opacity(0.75)
        }
    }

    private var trafficSignRecognitionAccessibilityLabel: String {
        String(
            format: NSLocalizedString("tsr.badge.accessibility", comment: ""),
            trafficSignRecognitionValueText,
            trafficSignRecognitionStatusText
        )
    }

    private var trafficSignRecognitionModuleSymbol: String {
        switch viewModel.trafficSignRecognitionState {
        case .confirmed:
            return "checkmark.circle.fill"
        case .provisional:
            return "ellipsis.circle.fill"
        case .unknown:
            return "questionmark.circle.fill"
        case .unavailable:
            return "exclamationmark.triangle.fill"
        case .disabled, .noRecognition:
            return "camera.viewfinder"
        }
    }

    private var canShowDriveRecorderPreview: Bool {
        DriveRecorderPolicy.canShowDashcamPreview(
            for: viewModel.driveRecorderState,
            dashcamActive: viewModel.driveRecorderDashcamActive,
            speedCaptureActive: viewModel.isInSpeedCaptureMode
        ) && viewModel.driveRecorderPreviewSession != nil
    }

    private func setDriveRecorderPreviewVisible(_ visible: Bool) {
        if visible {
            // The Dashcam chip can overlap the workspace on compact layouts.
            // SwiftUI may finish dispatching that same tap after inserting the
            // preview, causing its tap-to-hide gesture to fire immediately.
            driveRecorderPreviewDismissalAllowedAt = Date().addingTimeInterval(
                DriveRecorderPreviewInteractionPolicy.activationTapGuardInterval
            )
        }
        let selection: DriveRecorderWorkspaceSelection = visible ? .preview : .telemetry
        guard driveRecorderWorkspaceSelection != selection else { return }
        if accessibilityReduceMotion {
            driveRecorderWorkspaceSelection = selection
        } else {
            withAnimation(.easeInOut(duration: 0.2)) {
                driveRecorderWorkspaceSelection = selection
            }
        }
    }

    @ViewBuilder
    private func driveStatusWorkspace(
        primaryFont: CGFloat,
        secondaryFont: CGFloat,
        badgeWidth: CGFloat,
        debugFont: CGFloat,
        debugSpacing: CGFloat,
        reservedHeight: CGFloat,
        sectionGap: CGFloat
    ) -> some View {
        let metricSlotMinHeight = (primaryFont * 1.05) + (secondaryFont * 1.2)
        let workspaceHeight = metricSlotMinHeight + reservedHeight + sectionGap
        let previewSession = viewModel.driveRecorderPreviewSession
        let previewPresentation = DriveRecorderPreviewPresentation.resolve(
            sessionAvailable: previewSession != nil,
            selection: driveRecorderWorkspaceSelection,
            previewAvailable: canShowDriveRecorderPreview
        )
        let showingPreview = previewPresentation.isVisible

        ZStack {
            VStack(spacing: sectionGap) {
                metricStatusBlock(
                    primaryFont: primaryFont,
                    secondaryFont: secondaryFont
                )
                locationStatusBlock(
                    badgeWidth: badgeWidth,
                    debugFont: debugFont,
                    debugSpacing: debugSpacing,
                    reservedHeight: reservedHeight
                )
            }
            .frame(maxWidth: .infinity, minHeight: workspaceHeight)
            .contentShape(Rectangle())
            .opacity(showingPreview ? 0 : 1)
            .allowsHitTesting(!showingPreview)
            .accessibilityHidden(showingPreview)
            .onTapGesture {
                guard canShowDriveRecorderPreview else { return }
                setDriveRecorderPreviewVisible(true)
            }

            // Keep this representable mounted even while telemetry is visible.
            // Removing/reinserting it assigns AVCaptureVideoPreviewLayer.session
            // during movie recording, which rebuilds the graph and terminates
            // the Dashcam file on physical devices.
            if previewPresentation.isAttached, let session = previewSession {
                DriveCameraPreview(session: session)
                    .frame(maxWidth: .infinity)
                    .frame(height: workspaceHeight)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .strokeBorder(Color.white.opacity(0.32), lineWidth: 1)
                    }
                    .overlay {
                        VStack {
                            HStack {
                                Label(
                                    "\(NSLocalizedString("drive_recorder.preview.live", comment: "")) · \(NSLocalizedString("drive_recorder.status.dashcam", comment: ""))",
                                    systemImage: "video.fill"
                                )
                                .font(.caption.weight(.bold))
                                .padding(.horizontal, 9)
                                .padding(.vertical, 6)
                                .background(.black.opacity(0.62), in: Capsule())
                                Spacer()
                            }
                            Spacer()
                            Text(NSLocalizedString("drive_recorder.preview.hide", comment: ""))
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(.black.opacity(0.62), in: Capsule())
                        }
                        .foregroundStyle(.white)
                        .padding(12)
                    }
                    .contentShape(Rectangle())
                    .opacity(showingPreview ? 1 : 0)
                    .allowsHitTesting(showingPreview)
                    .accessibilityHidden(!showingPreview)
                    .accessibilityLabel(NSLocalizedString("drive_recorder.preview.live", comment: ""))
                    .accessibilityHint(NSLocalizedString("drive_recorder.preview.hide", comment: ""))
                    .onTapGesture {
                        guard DriveRecorderPreviewInteractionPolicy.canDismissPreview(
                            at: Date(),
                            notBefore: driveRecorderPreviewDismissalAllowedAt
                        ) else { return }
                        setDriveRecorderPreviewVisible(false)
                    }
            }
        }
        .frame(maxWidth: .infinity, minHeight: workspaceHeight)
        .accessibilityAction(named: NSLocalizedString("drive_recorder.preview.show", comment: "")) {
            guard canShowDriveRecorderPreview, !showingPreview else { return }
            setDriveRecorderPreviewVisible(true)
        }
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
                .onLongPressGesture {
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
                .onLongPressGesture {
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

private struct TrafficSignRecognitionDetailsView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        List {
            Section {
                LabeledContent(NSLocalizedString("tsr.details.source", comment: "")) {
                    Label(NSLocalizedString("tsr.details.source_camera", comment: ""), systemImage: "camera.viewfinder")
                }

                LabeledContent(NSLocalizedString("tsr.details.result", comment: "")) {
                    HStack(spacing: 8) {
                        Text(valueText)
                            .font(.headline.monospacedDigit())
                        Text(statusText)
                            .foregroundStyle(.secondary)
                    }
                }

                Text(stateDescription)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section {
                Label(NSLocalizedString("tsr.details.notice", comment: ""), systemImage: "exclamationmark.triangle")
                    .font(.subheadline.weight(.semibold))
                Text(NSLocalizedString("tsr.details.privacy", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if let event = viewModel.trafficSignRecognitionLastEvent,
               let context = event.roadContext {
                Section(NSLocalizedString("tsr.details.context", comment: "")) {
                    LabeledContent(NSLocalizedString("tsr.details.model_pack", comment: ""), value: event.packId)
                    LabeledContent(NSLocalizedString("tsr.details.way_id", comment: ""), value: context.wayId)
                    LabeledContent(
                        NSLocalizedString("tsr.details.coordinate", comment: ""),
                        value: String(format: "%.5f, %.5f", context.latitude, context.longitude)
                    )
                    LabeledContent(
                        NSLocalizedString("tsr.details.direction", comment: ""),
                        value: String(
                            format: "%@ · %.0f°",
                            localizedDirection(context.travelDirection),
                            context.headingDegrees
                        )
                    )
                    if let candidate = event.candidate {
                        LabeledContent(
                            NSLocalizedString("tsr.details.confidence", comment: ""),
                            value: confidenceText(candidate)
                        )
                        if !candidate.restrictions.isEmpty {
                            LabeledContent(
                                NSLocalizedString("tsr.details.restrictions", comment: ""),
                                value: candidate.restrictions
                                    .map { "\($0.kind.rawValue)=\($0.normalizedValue)" }
                                    .joined(separator: ", ")
                            )
                        }
                    }
                    LabeledContent(
                        NSLocalizedString("tsr.details.precedence", comment: ""),
                        value: viewModel.trafficSignRecognitionActiveOverride == nil
                            ? NSLocalizedString("tsr.details.precedence_base", comment: "")
                            : NSLocalizedString("tsr.details.precedence_camera", comment: "")
                    )
                }
            } else if let packID = viewModel.trafficSignRecognitionModelPackID {
                Section(NSLocalizedString("tsr.details.context", comment: "")) {
                    LabeledContent(NSLocalizedString("tsr.details.model_pack", comment: ""), value: packID)
                }
            } else if !viewModel.trafficSignRecognitionUnavailableDetail.isEmpty {
                Section(NSLocalizedString("tsr.details.context", comment: "")) {
                    Text(viewModel.trafficSignRecognitionUnavailableDetail)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle(NSLocalizedString("tsr.details.title", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(NSLocalizedString("common.done", comment: "")) {
                    dismiss()
                }
            }
        }
    }

    private var valueText: String {
        switch viewModel.trafficSignRecognitionState {
        case .disabled, .noRecognition:
            return "—"
        case .unavailable:
            return "×"
        case .provisional(let value), .confirmed(let value):
            return "\(value) km/h"
        case .unknown:
            return "?"
        }
    }

    private var statusText: String {
        switch viewModel.trafficSignRecognitionState {
        case .disabled:
            return NSLocalizedString("tsr.state.disabled", comment: "")
        case .unavailable:
            return NSLocalizedString("tsr.state.unavailable", comment: "")
        case .noRecognition:
            return NSLocalizedString("tsr.state.no_recognition", comment: "")
        case .provisional:
            return NSLocalizedString("tsr.state.provisional", comment: "")
        case .confirmed:
            return NSLocalizedString("tsr.state.confirmed", comment: "")
        case .unknown:
            return NSLocalizedString("tsr.state.unknown", comment: "")
        }
    }

    private var stateDescription: String {
        switch viewModel.trafficSignRecognitionState {
        case .disabled:
            return NSLocalizedString("tsr.details.disabled", comment: "")
        case .unavailable:
            return NSLocalizedString("tsr.details.unavailable", comment: "")
        case .noRecognition:
            return NSLocalizedString("tsr.details.no_recognition", comment: "")
        case .provisional:
            return NSLocalizedString("tsr.details.provisional", comment: "")
        case .confirmed:
            return NSLocalizedString("tsr.details.confirmed", comment: "")
        case .unknown:
            return NSLocalizedString("tsr.details.unknown", comment: "")
        }
    }

    private func confidenceText(_ candidate: TrafficSignRecognitionCandidate) -> String {
        if let confidence = candidate.calibratedConfidence {
            return String(format: "%.1f%%", confidence * 100)
        }
        return String(format: "raw %.3f", candidate.rawScore)
    }

    private func localizedDirection(_ direction: TrafficSignTravelDirection) -> String {
        switch direction {
        case .forward:
            return NSLocalizedString("tsr.direction.forward", comment: "")
        case .reverse:
            return NSLocalizedString("tsr.direction.reverse", comment: "")
        case .unknown:
            return NSLocalizedString("tsr.direction.unknown", comment: "")
        }
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
    @State private var trafficSignNoticesText: String = TrafficSignThirdPartyNoticesLoader.load()

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

                VStack(alignment: .leading, spacing: 8) {
                    Text(NSLocalizedString("about.tsr_attribution.title", comment: ""))
                        .font(.system(size: 16, weight: .bold, design: .default))
                    Text(NSLocalizedString("about.tsr_attribution.intro", comment: ""))
                        .font(.system(size: 14, weight: .regular, design: .default))
                    Link(
                        NSLocalizedString("about.tsr_attribution.detector", comment: ""),
                        destination: TrafficSignModelAttributionLinks.detector
                    )
                    Link(
                        NSLocalizedString("about.tsr_attribution.classifier", comment: ""),
                        destination: TrafficSignModelAttributionLinks.classifier
                    )
                    Link(
                        NSLocalizedString("about.tsr_attribution.training_data", comment: ""),
                        destination: TrafficSignModelAttributionLinks.trainingData
                    )
                    Link(
                        NSLocalizedString("about.tsr_attribution.exporter", comment: ""),
                        destination: TrafficSignModelAttributionLinks.exporter
                    )
                    Link(
                        NSLocalizedString("about.tsr_attribution.coremltools", comment: ""),
                        destination: TrafficSignModelAttributionLinks.coreMLTools
                    )
                    Link(
                        NSLocalizedString("about.tsr_attribution.pytorch", comment: ""),
                        destination: TrafficSignModelAttributionLinks.pyTorch
                    )
                    Divider()
                    NavigationLink {
                        TrafficSignThirdPartyNoticesView(text: trafficSignNoticesText)
                    } label: {
                        Label(
                            NSLocalizedString("about.tsr_attribution.licenses", comment: ""),
                            systemImage: "doc.text"
                        )
                    }
                }
                .font(.system(size: 14, weight: .regular, design: .default))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

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

private struct TrafficSignThirdPartyNoticesView: View {
    let text: String

    var body: some View {
        ScrollView {
            Text(text)
                .font(.system(size: 13, weight: .regular, design: .monospaced))
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .padding(16)
        }
        .navigationTitle(NSLocalizedString("about.tsr_attribution.licenses", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
    }
}

private enum TrafficSignModelAttributionLinks {
    static let detector = URL(
        string: "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt"
    )!
    static let classifier = URL(
        string: "https://huggingface.co/Panoramax/classify_de_road_signs/blob/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790/README.md"
    )!
    static let trainingData = URL(
        string: "https://huggingface.co/datasets/Panoramax/classified_de_road_signs/tree/b4856947ed7cb6312587258acc90e8cf88a4aa13"
    )!
    static let exporter = URL(
        string: "https://github.com/ultralytics/ultralytics/tree/v8.4.56"
    )!
    static let coreMLTools = URL(
        string: "https://github.com/apple/coremltools/tree/9.0"
    )!
    static let pyTorch = URL(
        string: "https://github.com/pytorch/pytorch/tree/v2.13.0"
    )!
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

enum TrafficSignThirdPartyNoticesLoader {
    private static let packSubdirectory =
        "TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack"

    static func load(bundle: Bundle = .main) -> String {
        let bundles = [bundle, Bundle(for: SpeedConsumerAppDelegate.self)]
        for candidateBundle in bundles {
            guard let url = candidateBundle.url(
                forResource: "THIRD_PARTY_NOTICES",
                withExtension: "txt",
                subdirectory: packSubdirectory
            ), let text = try? String(contentsOf: url, encoding: .utf8) else {
                continue
            }
            return text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return NSLocalizedString("about.tsr_attribution.licenses_unavailable", comment: "")
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
                DashcamRecordingsView(viewModel: viewModel)
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "video.fill")
                    VStack(alignment: .leading, spacing: 2) {
                        Text(NSLocalizedString("drive_recorder.library.title", comment: ""))
                            .font(.subheadline.weight(.semibold))
                        Text(String(
                            format: NSLocalizedString("drive_recorder.library.count", comment: ""),
                            viewModel.dashcamRecordings.count
                        ))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .foregroundStyle(.secondary)
                }
                .padding(12)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 16)
            .padding(.top, 4)

            VStack(alignment: .leading, spacing: 10) {
                Label(NSLocalizedString("panoramax.post_drive.title", comment: ""), systemImage: "clock.arrow.circlepath")
                    .font(.headline)

                Text(NSLocalizedString("panoramax.post_drive.description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Text(String(
                    format: NSLocalizedString("panoramax.review.local_count", comment: ""),
                    viewModel.panoramaxBatches.reduce(0) { $0 + $1.items.count }
                ))
                .font(.caption.weight(.semibold))

                if !viewModel.canProcessPanoramaxUploads {
                    Label(NSLocalizedString("panoramax.post_drive.capture_active", comment: ""), systemImage: "record.circle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }

                HStack(spacing: 8) {
                    NavigationLink {
                        PanoramaxReviewView(viewModel: viewModel)
                    } label: {
                        Label(NSLocalizedString("panoramax.review.open", comment: ""), systemImage: "checkmark.circle")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(!viewModel.canProcessPanoramaxUploads)

                    NavigationLink {
                        PanoramaxGalleryView(viewModel: viewModel)
                    } label: {
                        Label(NSLocalizedString("panoramax.gallery.open_post_drive", comment: ""), systemImage: "square.grid.2x2")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(!viewModel.canProcessPanoramaxUploads)
                }
            }
            .padding(12)
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .padding(.horizontal, 16)
            .padding(.top, 4)

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

private struct DashcamRecordingsView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var sharedRecording: DashcamRecording?
    @State private var selectedRecordingIDs: Set<String> = []
    @State private var showingDeleteConfirmation = false

    var body: some View {
        VStack(spacing: 0) {
            Group {
                if viewModel.dashcamRecordings.isEmpty {
                    ContentUnavailableView(
                        NSLocalizedString("drive_recorder.library.empty", comment: ""),
                        systemImage: "video.slash"
                    )
                } else {
                    List {
                        Section {
                            ForEach(viewModel.dashcamRecordings) { recording in
                                HStack(spacing: 12) {
                                    Button {
                                        if selectedRecordingIDs.contains(recording.id) {
                                            selectedRecordingIDs.remove(recording.id)
                                        } else {
                                            selectedRecordingIDs.insert(recording.id)
                                        }
                                    } label: {
                                        Image(systemName: selectedRecordingIDs.contains(recording.id) ? "checkmark.square.fill" : "square")
                                            .font(.title3.weight(.semibold))
                                            .foregroundStyle(selectedRecordingIDs.contains(recording.id) ? Color.accentColor : .secondary)
                                    }
                                    .buttonStyle(.plain)
                                    .accessibilityLabel(selectedRecordingIDs.contains(recording.id)
                                        ? NSLocalizedString("drive_recorder.library.deselect", comment: "")
                                        : NSLocalizedString("drive_recorder.library.select", comment: ""))
                            Image(systemName: "video.fill")
                                .foregroundStyle(.secondary)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(recording.createdAt.formatted(date: .abbreviated, time: .shortened))
                                    .font(.subheadline.weight(.semibold))
                                Text(ByteCountFormatter.string(fromByteCount: recording.byteSize, countStyle: .file))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button {
                                sharedRecording = recording
                            } label: {
                                Image(systemName: "square.and.arrow.up")
                            }
                            .buttonStyle(.plain)
                            .disabled(viewModel.isDriveRecorderActive)
                                }
                            }
                        } footer: {
                            Text(NSLocalizedString("drive_recorder.library.retention", comment: ""))
                        }
                    }
                }
            }
            .frame(maxHeight: .infinity)

            if !viewModel.dashcamRecordings.isEmpty {
                HStack(spacing: 8) {
                    Button {
                        selectedRecordingIDs = Set(viewModel.dashcamRecordings.map(\.id))
                    } label: {
                        Image(systemName: "checkmark.square.fill").frame(width: 24, height: 24)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityLabel(NSLocalizedString("drive_recorder.library.select_all", comment: ""))
                    Button {
                        selectedRecordingIDs.removeAll()
                    } label: {
                        Image(systemName: "square.dashed").frame(width: 24, height: 24)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityLabel(NSLocalizedString("drive_recorder.library.select_none", comment: ""))
                    .disabled(selectedRecordingIDs.isEmpty)
                    Button(role: .destructive) {
                        showingDeleteConfirmation = true
                    } label: {
                        Image(systemName: "trash").frame(width: 24, height: 24)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityLabel(NSLocalizedString("drive_recorder.library.delete_selected", comment: ""))
                    .disabled(selectedRecordingIDs.isEmpty || viewModel.isDriveRecorderActive)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(.bar)
            }
        }
        .task { viewModel.refreshDashcamRecordings() }
        .onChange(of: Set(viewModel.dashcamRecordings.map(\.id))) { _, availableIDs in
            selectedRecordingIDs.formIntersection(availableIDs)
        }
        .sheet(item: $sharedRecording) { recording in
            ShareSheet(activityItems: [recording.url])
        }
        .alert(NSLocalizedString("drive_recorder.library.delete_title", comment: ""), isPresented: $showingDeleteConfirmation) {
            Button(NSLocalizedString("common.cancel", comment: ""), role: .cancel) {}
            Button(NSLocalizedString("panoramax.gallery.delete_confirm", comment: ""), role: .destructive) {
                viewModel.deleteDashcamRecordings(ids: selectedRecordingIDs)
                selectedRecordingIDs.removeAll()
            }
        } message: {
            Text(String(format: NSLocalizedString("drive_recorder.library.delete_message", comment: ""), selectedRecordingIDs.count))
        }
    }
}

private struct PanoramaxReviewView: View {
    @ObservedObject var viewModel: DriveSessionViewModel

    var body: some View {
        List {
            if viewModel.panoramaxBatches.isEmpty {
                ContentUnavailableView(
                    NSLocalizedString("panoramax.review.empty_title", comment: ""),
                    systemImage: "camera.aperture",
                    description: Text(NSLocalizedString("panoramax.review.empty_description", comment: ""))
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
                        let included = batch.items.filter {
                            $0.state == .captured || $0.state == .included || $0.state == .retryableError
                        }.count
                        if batch.state == .awaitingReview, included > 0 {
                            Button(NSLocalizedString("panoramax.review.approve", comment: "")) {
                                viewModel.approvePanoramaxBatch(batchID: batch.batchID)
                            }
                            .disabled(!viewModel.canProcessPanoramaxUploads)
                        } else if DriveRecorderPolicy.canStartPanoramaxUpload(for: batch.state) {
                            Button(NSLocalizedString("panoramax.gallery.upload", comment: "")) {
                                viewModel.uploadPanoramaxBatch(batchID: batch.batchID)
                            }
                            .disabled(
                                !viewModel.canProcessPanoramaxUploads
                                || !viewModel.panoramaxUploadIsReady
                                || viewModel.isPanoramaxUploadActive(batchID: batch.batchID)
                            )
                            if let status = viewModel.panoramaxUploadStatus(for: batch.batchID) { Text(status) }
                        } else {
                            Text(String(format: NSLocalizedString("panoramax.review.selected_count", comment: ""), included))
                        }
                    }
                }
            }
        }
        .navigationTitle(NSLocalizedString("panoramax.review.title", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
        .task { viewModel.refreshPanoramaxBatches() }
    }
}

private struct PanoramaxReviewItemRow: View {
    let batch: PanoramaxBatchRecord
    let item: PanoramaxItemRecord
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var showingOriginal = false

    private var included: Bool {
        item.state == .captured || item.state == .included || item.state == .retryableError
    }

    private var canEdit: Bool {
        viewModel.canProcessPanoramaxUploads
            && !viewModel.isPanoramaxUploadActive(batchID: batch.batchID)
            && DriveRecorderPolicy.canEditPanoramaxSelection(in: batch.state)
            && DriveRecorderPolicy.canSelectPanoramaxItem(in: item.state)
    }

    private var canDeleteLocally: Bool {
        viewModel.canProcessPanoramaxUploads
            && DriveRecorderPolicy.canDeletePanoramaxItem(
                batchState: batch.state,
                itemState: item.state
            )
    }

    var body: some View {
        HStack(spacing: 12) {
            Button { showingOriginal = true } label: {
                thumbnail.frame(width: 112, height: 64)
            }
            .buttonStyle(.plain)
            .overlay(alignment: .topTrailing) {
                Button {
                    viewModel.togglePanoramaxFavorite(batchID: batch.batchID, itemID: item.itemID)
                } label: {
                    Image(systemName: item.isFavorite ? "star.fill" : "star")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(item.isFavorite ? .yellow : .white)
                        .padding(6)
                        .background(.black.opacity(0.55), in: Circle())
                }
                .buttonStyle(.plain)
                .disabled(!canEdit)
                .accessibilityLabel(item.isFavorite
                    ? NSLocalizedString("panoramax.gallery.favorite_remove", comment: "")
                    : NSLocalizedString("panoramax.gallery.favorite_add", comment: ""))
                .padding(4)
            }
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
            .disabled(!canEdit)
            Button(role: .destructive) {
                viewModel.deletePanoramaxItem(batchID: batch.batchID, itemID: item.itemID)
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.plain)
            .disabled(!canDeleteLocally)
        }
        .sheet(isPresented: $showingOriginal) {
            NavigationStack {
                if let url = viewModel.panoramaxOriginalURL(for: item),
                   let image = UIImage(contentsOfFile: url.path) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .padding()
                        .navigationTitle(NSLocalizedString("panoramax.gallery.image_title", comment: ""))
                        .navigationBarTitleDisplayMode(.inline)
                } else {
                    ContentUnavailableView(NSLocalizedString("panoramax.gallery.image_missing", comment: ""), systemImage: "photo")
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

private struct PanoramaxGalleryView: View {
    @ObservedObject var viewModel: DriveSessionViewModel

    var body: some View {
        TabView {
            PictureGalleryView(viewModel: viewModel)
                .tabItem {
                    Label(NSLocalizedString("gallery.tab.pictures", comment: ""), systemImage: "photo.on.rectangle")
                }
            DashcamRecordingsView(viewModel: viewModel)
                .tabItem {
                    Label(NSLocalizedString("gallery.tab.videos", comment: ""), systemImage: "video.fill")
                }
        }
        .navigationTitle(NSLocalizedString("panoramax.gallery.title", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct PictureGalleryView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @State private var selectedItem: GalleryItem?
    @State private var selectedItemIDs: Set<String> = []
    @State private var showingDeleteConfirmation = false
    @State private var showingAccountRequired = false

    private struct GalleryItem: Identifiable {
        let id: String
        let batchID: String
        let item: PanoramaxItemRecord
    }

    private var entries: [(batch: PanoramaxBatchRecord, item: PanoramaxItemRecord)] { viewModel.panoramaxGalleryItems }
    private var locallySelectableEntries: [(batch: PanoramaxBatchRecord, item: PanoramaxItemRecord)] {
        entries.filter { canSelectLocally(batch: $0.batch) }
    }
    private var selectedEntries: [(batch: PanoramaxBatchRecord, item: PanoramaxItemRecord)] {
        entries.filter { selectedItemIDs.contains($0.item.itemID) }
    }
    private var uploadableSelectedEntries: [(batch: PanoramaxBatchRecord, item: PanoramaxItemRecord)] {
        selectedEntries.filter { isUploadEligible(batch: $0.batch, item: $0.item) }
    }
    private var resumableBatchIDs: Set<String> {
        Set(viewModel.panoramaxBatches.compactMap { batch in
            DriveRecorderPolicy.canResumePanoramaxRemoteSet(
                batchState: batch.state,
                remoteUploadSetID: batch.remoteUploadSetID,
                itemStates: batch.items.map(\.state)
            ) ? batch.batchID : nil
        })
    }
    var body: some View {
        VStack(spacing: 0) {
            Group {
                if entries.isEmpty {
                    ContentUnavailableView(NSLocalizedString("panoramax.gallery.empty", comment: ""), systemImage: "photo.on.rectangle")
                } else {
                    ScrollView {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 12)], spacing: 12) {
                            ForEach(entries, id: \.item.itemID) { entry in
                            let galleryItem = GalleryItem(id: entry.item.itemID, batchID: entry.batch.batchID, item: entry.item)
                            Button { selectedItem = galleryItem } label: {
                                thumbnail(for: entry.item)
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 110)
                                    .clipped()
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            .overlay(alignment: .topLeading) {
                                Button {
                                    if selectedItemIDs.contains(entry.item.itemID) {
                                        selectedItemIDs.remove(entry.item.itemID)
                                    } else if canSelectLocally(batch: entry.batch) {
                                        selectedItemIDs.insert(entry.item.itemID)
                                    }
                                } label: {
                                    Image(systemName: selectedItemIDs.contains(entry.item.itemID) ? "checkmark.square.fill" : "square")
                                        .font(.title2.weight(.semibold))
                                        .foregroundStyle(selectedItemIDs.contains(entry.item.itemID) ? Color.accentColor : .white)
                                        .padding(6)
                                        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                                }
                                .buttonStyle(.plain)
                                .disabled(!canSelectLocally(batch: entry.batch))
                                .accessibilityLabel(selectedItemIDs.contains(entry.item.itemID)
                                    ? NSLocalizedString("panoramax.gallery.deselect", comment: "")
                                    : NSLocalizedString("panoramax.gallery.select", comment: ""))
                                .padding(6)
                            }
                            .overlay(alignment: .topTrailing) {
                                Button {
                                    viewModel.togglePanoramaxFavorite(batchID: galleryItem.batchID, itemID: galleryItem.item.itemID)
                                } label: {
                                    Image(systemName: entry.item.isFavorite ? "star.fill" : "star")
                                        .foregroundStyle(entry.item.isFavorite ? .yellow : .white)
                                        .padding(7)
                                        .background(.black.opacity(0.55), in: Circle())
                                }
                                .buttonStyle(.plain)
                                .disabled(
                                    !viewModel.canProcessPanoramaxUploads
                                    || viewModel.isPanoramaxUploadActive(batchID: entry.batch.batchID)
                                )
                                .accessibilityLabel(entry.item.isFavorite
                                    ? NSLocalizedString("panoramax.gallery.favorite_remove", comment: "")
                                    : NSLocalizedString("panoramax.gallery.favorite_add", comment: ""))
                                .padding(6)
                            }
                            .overlay(alignment: .bottomLeading) {
                                Text(entry.item.metadata.capturedAt.formatted(date: .omitted, time: .shortened))
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.white)
                                    .padding(5)
                                    .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 5))
                                    .padding(6)
                                    .allowsHitTesting(false)
                            }
                            .overlay(alignment: .bottomTrailing) {
                                if let status = statusPresentation(for: entry.item) {
                                    Image(systemName: status.systemImage)
                                        .font(.caption.weight(.bold))
                                        .foregroundStyle(status.color)
                                        .padding(6)
                                        .background(.black.opacity(0.65), in: Circle())
                                        .padding(6)
                                        .allowsHitTesting(false)
                                        .accessibilityLabel(status.accessibilityLabel)
                                }
                            }
                            .overlay {
                                if let annotation = primaryTrafficSignAnnotation(for: entry.item) {
                                    GallerySpeedLimitOverlay(speedLimitKmh: annotation.speedLimitKmh)
                                        .allowsHitTesting(false)
                                }
                            }
                            .accessibilityElement(children: .contain)
                        }
                        }
                        .padding(12)
                    }
                }
            }
            .frame(maxHeight: .infinity)

            if !entries.isEmpty
                || !viewModel.activePanoramaxUploadBatchIDs.isEmpty
                || viewModel.panoramaxMaintenanceIssue != nil {
                VStack(spacing: 6) {
                    if !viewModel.canProcessPanoramaxUploads {
                        Label(NSLocalizedString("panoramax.gallery.upload_capture_active", comment: ""), systemImage: "record.circle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .multilineTextAlignment(.center)
                    }
                    if let issue = viewModel.panoramaxMaintenanceIssue {
                        Label(issue, systemImage: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .multilineTextAlignment(.center)
                    }
                    if let progress = viewModel.panoramaxAggregateUploadProgress {
                        VStack(spacing: 3) {
                            if progress.totalItems > 0 {
                                ProgressView(value: progress.fractionCompleted)
                            } else {
                                ProgressView()
                            }
                            Text(progressText(progress))
                                .font(.caption2.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 12)
                    }
                    HStack(spacing: 8) {
                        if !entries.isEmpty {
                            Button {
                                selectedItemIDs = Set(locallySelectableEntries.map { $0.item.itemID })
                            } label: {
                                Image(systemName: "checkmark.square.fill")
                                    .frame(width: 24, height: 24)
                            }
                            .buttonStyle(.bordered)
                            .accessibilityLabel(NSLocalizedString("panoramax.gallery.select_all", comment: ""))
                            .disabled(locallySelectableEntries.isEmpty)
                            Button {
                                selectedItemIDs.removeAll()
                            } label: {
                                Image(systemName: "square.dashed")
                                    .frame(width: 24, height: 24)
                            }
                            .buttonStyle(.bordered)
                            .accessibilityLabel(NSLocalizedString("panoramax.gallery.select_none", comment: ""))
                            .disabled(selectedItemIDs.isEmpty)
                            Button(role: .destructive) { showingDeleteConfirmation = true } label: {
                                Image(systemName: "trash")
                                    .frame(width: 24, height: 24)
                            }
                            .buttonStyle(.bordered)
                            .accessibilityLabel(NSLocalizedString("panoramax.gallery.delete", comment: ""))
                            .disabled(
                                selectedItemIDs.isEmpty
                                || !viewModel.canProcessPanoramaxUploads
                            )
                        }
                        Spacer(minLength: 0)
                        if viewModel.activePanoramaxUploadBatchIDs.isEmpty, !entries.isEmpty {
                            Button {
                                guard viewModel.canProcessPanoramaxUploads else { return }
                                guard viewModel.panoramaxUploadIsReady else {
                                    showingAccountRequired = true
                                    return
                                }
                                viewModel.uploadPanoramaxSelections(
                                    uploadableSelectedEntries.map {
                                        (batchID: $0.batch.batchID, itemID: $0.item.itemID)
                                    }
                                )
                                let newlyStartedBatchIDs = Set(uploadableSelectedEntries.map { $0.batch.batchID })
                                for batchID in resumableBatchIDs.subtracting(newlyStartedBatchIDs) {
                                    viewModel.uploadPanoramaxBatch(batchID: batchID)
                                }
                            } label: {
                                Image(systemName: "arrow.up.circle.fill")
                                    .frame(width: 24, height: 24)
                            }
                            .buttonStyle(.borderedProminent)
                            .accessibilityLabel(NSLocalizedString("panoramax.gallery.upload", comment: ""))
                            .disabled(
                                (uploadableSelectedEntries.isEmpty && resumableBatchIDs.isEmpty)
                                || !viewModel.canProcessPanoramaxUploads
                            )
                        } else {
                            Button(role: .destructive) {
                                viewModel.stopPanoramaxUploads()
                            } label: {
                                Image(systemName: "stop.circle.fill")
                                    .frame(width: 24, height: 24)
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(.red)
                            .accessibilityLabel(NSLocalizedString("panoramax.gallery.stop_upload", comment: ""))
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.bottom, 10)
                }
                .background(.bar)
            }
        }
        .navigationTitle(NSLocalizedString("panoramax.gallery.title", comment: ""))
        .navigationBarTitleDisplayMode(.inline)
        .task { viewModel.refreshPanoramaxBatches() }
        .onChange(of: Set(entries.map { $0.item.itemID })) { _, availableIDs in
            selectedItemIDs.formIntersection(availableIDs)
        }
        .sheet(item: $selectedItem) { selection in
            NavigationStack {
                if let url = viewModel.panoramaxOriginalURL(for: selection.item), let image = UIImage(contentsOfFile: url.path) {
                    ZStack {
                        Image(uiImage: image).resizable().scaledToFit()
                        if let annotation = primaryTrafficSignAnnotation(for: selection.item) {
                            GallerySpeedLimitOverlay(speedLimitKmh: annotation.speedLimitKmh, diameter: 92)
                        }
                    }
                    .padding()
                    .navigationTitle(NSLocalizedString("panoramax.gallery.image_title", comment: ""))
                    .navigationBarTitleDisplayMode(.inline)
                } else {
                    ContentUnavailableView(NSLocalizedString("panoramax.gallery.image_missing", comment: ""), systemImage: "photo")
                }
            }
        }
        .alert(NSLocalizedString("panoramax.gallery.delete_title", comment: ""), isPresented: $showingDeleteConfirmation) {
            Button(NSLocalizedString("common.cancel", comment: ""), role: .cancel) {}
            Button(NSLocalizedString("panoramax.gallery.delete_confirm", comment: ""), role: .destructive) {
                viewModel.deletePanoramaxSelections(selectedEntries.map { (batchID: $0.batch.batchID, itemID: $0.item.itemID) })
                selectedItemIDs.removeAll()
            }
        } message: {
            Text(String(format: NSLocalizedString("panoramax.gallery.delete_message", comment: ""), selectedItemIDs.count))
        }
        .alert(NSLocalizedString("panoramax.gallery.account_required_title", comment: ""), isPresented: $showingAccountRequired) {
            Button(NSLocalizedString("common.done", comment: ""), role: .cancel) {}
        } message: {
            Text(NSLocalizedString("panoramax.gallery.upload_requires_account", comment: ""))
        }
    }

    private func canSelectLocally(batch _: PanoramaxBatchRecord) -> Bool {
        viewModel.canProcessPanoramaxUploads
    }

    private func isUploadEligible(batch: PanoramaxBatchRecord, item: PanoramaxItemRecord) -> Bool {
        canSelectLocally(batch: batch)
            && DriveRecorderPolicy.canEditPanoramaxSelection(in: batch.state)
            && DriveRecorderPolicy.canSelectPanoramaxItem(in: item.state)
    }

    private func progressText(_ progress: PanoramaxUploadProgress) -> String {
        let key: String
        switch progress.phase {
        case .preparing: key = "panoramax.gallery.progress_preparing"
        case .uploading: key = "panoramax.gallery.progress_uploading"
        case .processing: key = "panoramax.gallery.progress_processing"
        case .stopping: key = "panoramax.gallery.progress_stopping"
        }
        return String(
            format: NSLocalizedString(key, comment: ""),
            progress.completedItems,
            progress.totalItems
        )
    }

    private func statusPresentation(for item: PanoramaxItemRecord) -> (
        systemImage: String,
        color: Color,
        accessibilityLabel: String
    )? {
        switch item.state {
        case .captured, .queued, .included:
            return ("clock.fill", .orange, NSLocalizedString("panoramax.gallery.status_waiting", comment: ""))
        case .uploading:
            return ("arrow.up.circle.fill", .blue, NSLocalizedString("panoramax.gallery.status_uploading", comment: ""))
        case .uploaded, .accepted, .duplicate:
            return ("pano.fill", .green, NSLocalizedString("panoramax.gallery.status_uploaded", comment: ""))
        case .retryableError:
            return ("clock.fill", .orange, NSLocalizedString("panoramax.gallery.status_retry", comment: ""))
        case .abandoned:
            return ("exclamationmark.triangle.fill", .orange, NSLocalizedString("panoramax.gallery.status_abandoned", comment: ""))
        case .rejected, .permanentError:
            return ("exclamationmark.triangle.fill", .red, NSLocalizedString("panoramax.gallery.status_failed", comment: ""))
        case .excluded:
            return nil
        }
    }

    private func primaryTrafficSignAnnotation(
        for item: PanoramaxItemRecord
    ) -> PanoramaxTrafficSignAnnotation? {
        item.metadata.trafficSignAnnotations?.max {
            $0.classificationConfidence < $1.classificationConfidence
        }
    }

    @ViewBuilder
    private func thumbnail(for item: PanoramaxItemRecord) -> some View {
        if let url = viewModel.panoramaxThumbnailURL(for: item), let image = UIImage(contentsOfFile: url.path) {
            Image(uiImage: image).resizable().scaledToFill()
        } else {
            Color.secondary.opacity(0.2).overlay { Image(systemName: "photo").foregroundStyle(.secondary) }
        }
    }
}

private struct GallerySpeedLimitOverlay: View {
    let speedLimitKmh: Int
    var diameter: CGFloat = 62

    var body: some View {
        Text("\(speedLimitKmh)")
            .font(.system(size: diameter * 0.39, weight: .bold, design: .rounded))
            .monospacedDigit()
            .foregroundStyle(.black)
            .frame(width: diameter, height: diameter)
            .background(.white, in: Circle())
            .overlay {
                Circle().stroke(.red, lineWidth: max(5, diameter * 0.09))
            }
            .shadow(color: .black.opacity(0.7), radius: 4, y: 2)
            .accessibilityLabel(String(
                format: NSLocalizedString("gallery.recognized_speed", comment: ""),
                speedLimitKmh
            ))
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

            Section(NSLocalizedString("drive_recorder.settings.section", comment: "")) {
                Text(NSLocalizedString("drive_recorder.settings.description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                LabeledContent(NSLocalizedString("drive_recorder.settings.status", comment: ""), value: driveRecorderStatusText)

                Toggle(NSLocalizedString("drive_recorder.settings.tsr", comment: ""), isOn: $viewModel.trafficSignRecognitionEnabled)
                    .disabled(viewModel.isDriveRecorderActive)
                Text(NSLocalizedString("drive_recorder.settings.tsr_description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Picker(
                    NSLocalizedString("drive_recorder.settings.tsr_feedback", comment: ""),
                    selection: $viewModel.trafficSignFeedbackMode
                ) {
                    ForEach(TrafficSignFeedbackMode.allCases) { mode in
                        Text(mode.label).tag(mode)
                    }
                }
                .pickerStyle(.menu)
                .disabled(!viewModel.trafficSignRecognitionEnabled)
                Text(NSLocalizedString("drive_recorder.settings.tsr_feedback_description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Toggle(NSLocalizedString("drive_recorder.settings.panoramax", comment: ""), isOn: $viewModel.panoramaxCaptureEnabled)
                    .disabled(viewModel.isDriveRecorderActive)
                Text(NSLocalizedString("drive_recorder.settings.panoramax_description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Label(NSLocalizedString("drive_recorder.settings.shared_camera", comment: ""), systemImage: "camera.viewfinder")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Label(NSLocalizedString("drive_recorder.settings.upload_later", comment: ""), systemImage: "clock.arrow.circlepath")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                if viewModel.panoramaxCaptureEnabled {
                    LabeledContent(NSLocalizedString("panoramax.settings.saved_images", comment: ""), value: "\(viewModel.panoramaxCaptureCount)")

                    Picker(NSLocalizedString("panoramax.settings.trigger", comment: ""), selection: $viewModel.panoramaxTriggerMode) {
                        ForEach(PanoramaxCaptureTriggerMode.allCases, id: \.self) { mode in
                            Text(mode.label).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)

                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(NSLocalizedString("panoramax.settings.minimum_distance", comment: ""))
                            Spacer()
                            Text("\(Int(viewModel.panoramaxMinimumDistanceMeters.rounded())) m")
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $viewModel.panoramaxMinimumDistanceMeters, in: 3...100, step: 1)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(NSLocalizedString("panoramax.settings.minimum_time", comment: ""))
                            Spacer()
                            Text("\(Int(viewModel.panoramaxMinimumIntervalSeconds.rounded())) s")
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $viewModel.panoramaxMinimumIntervalSeconds, in: 1...60, step: 1)
                    }

                    if let accuracy = viewModel.panoramaxLastAccuracyMeters {
                        Text(String(format: NSLocalizedString("panoramax.settings.gps_distance_explanation", comment: ""), Int(accuracy.rounded())))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        Text(NSLocalizedString("panoramax.settings.gps_accuracy_explanation", comment: ""))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    Toggle(NSLocalizedString("panoramax.settings.unlimited_storage", comment: ""), isOn: $viewModel.panoramaxUnlimitedStorage)
                    if !viewModel.panoramaxUnlimitedStorage {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(NSLocalizedString("panoramax.settings.storage_limit", comment: ""))
                                Spacer()
                                Text("\(Int(viewModel.panoramaxStorageLimitMB.rounded())) MB")
                                    .monospacedDigit()
                                    .foregroundStyle(.secondary)
                            }
                            Slider(value: $viewModel.panoramaxStorageLimitMB, in: 100...10_000, step: 100)
                        }
                        Text(NSLocalizedString("panoramax.settings.retention_description", comment: ""))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                }

                Toggle(
                    NSLocalizedString("panoramax.settings.delete_uploaded", comment: ""),
                    isOn: $viewModel.panoramaxDeleteUploadedImages
                )
                Text(NSLocalizedString("panoramax.settings.delete_uploaded_description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section(NSLocalizedString("panoramax.account.section", comment: "")) {
                Picker(NSLocalizedString("panoramax.account.instance", comment: ""), selection: Binding(
                    get: { PanoramaxServerCatalog.presets.first(where: { $0.origin == account.instanceOrigin })?.id ?? "custom" },
                    set: { id in
                        if let preset = PanoramaxServerCatalog.presets.first(where: { $0.id == id }) { account.instanceOrigin = preset.origin }
                    }
                )) {
                    ForEach(PanoramaxServerCatalog.presets) { preset in
                        Text(preset.name).tag(preset.id)
                    }
                    Text(NSLocalizedString("panoramax.account.other_instance", comment: "")).tag("custom")
                }
                .pickerStyle(.menu)

                TextField(NSLocalizedString("panoramax.account.instance_placeholder", comment: ""), text: $account.instanceOrigin)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)

                Text(NSLocalizedString("panoramax.account.security_description", comment: ""))
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                LabeledContent(NSLocalizedString("panoramax.account.status", comment: ""), value: account.status)

                if account.isConnected {
                    Button(NSLocalizedString("panoramax.account.disconnect", comment: ""), role: .destructive) {
                        account.disconnect()
                    }
                } else {
                    Button(NSLocalizedString("panoramax.account.connect", comment: "")) {
                        account.connect()
                    }
                    Button(NSLocalizedString("panoramax.account.validate", comment: "")) {
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

    private var driveRecorderStatusText: String {
        switch viewModel.driveRecorderState {
        case .disabled:
            return NSLocalizedString("drive_recorder.state.ready", comment: "")
        case .preparing:
            return NSLocalizedString("drive_recorder.state.preparing", comment: "")
        case .recording:
            return NSLocalizedString("drive_recorder.state.recording", comment: "")
        case .stopping:
            return NSLocalizedString("drive_recorder.state.stopping", comment: "")
        case .denied:
            return NSLocalizedString("drive_recorder.state.denied", comment: "")
        case .unavailable:
            return NSLocalizedString("drive_recorder.state.unavailable", comment: "")
        case .failed:
            return NSLocalizedString("drive_recorder.state.failed", comment: "")
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
                if let tsrLogURL {
                    Button("TSR-Log teilen") {
                        shareItem = LocalDebugShareItem(url: tsrLogURL)
                    }
                }
                if gpsLogURL != nil || matchLogURL != nil || tsrLogURL != nil {
                    Button("Fahrlog leeren", role: .destructive) {
                        showingClearDrivingLogConfirm = true
                    }
                }
                if gpsLogURL == nil && matchLogURL == nil && tsrLogURL == nil {
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
            Text("GPS-CSV, Matcher-Log und TSR-Log werden geleert. Neue Fahrdaten werden anschliessend wieder normal aufgezeichnet.")
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
            ("TSR-Log", viewModel.tsrLogPath.isEmpty ? "n/a" : viewModel.tsrLogPath),
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

    private var tsrLogURL: URL? {
        guard !viewModel.tsrLogPath.isEmpty else { return nil }
        return URL(fileURLWithPath: viewModel.tsrLogPath)
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

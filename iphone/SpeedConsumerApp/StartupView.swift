import SwiftUI
import UIKit

struct StartupView: View {
    @ObservedObject var viewModel: DriveSessionViewModel

    var body: some View {
        ZStack {
            Color.black
                .ignoresSafeArea()

            VStack(spacing: 18) {
                Text("YouSpeed")
                    .font(.system(size: 42, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)

                Text("startup.loading_map_data")
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)

                ProgressView(value: clampedProgress, total: 1)
                    .tint(.red)
                    .padding(.top, 10)

                Text("\(Int(clampedProgress * 100))%")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.92))
                    .monospacedDigit()

                Text(viewModel.startupDetail)
                    .font(.system(size: 16, weight: .medium, design: .rounded))
                    .foregroundStyle(.white.opacity(0.85))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 16)

                if viewModel.startupDataState == .failed {
                    if !viewModel.lastError.isEmpty {
                        Text(viewModel.lastError)
                            .font(.system(size: 14, weight: .regular, design: .rounded))
                            .foregroundStyle(.white.opacity(0.75))
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 16)
                    }

                    RecordingSafeButton("startup.retry") {
                        viewModel.retryStartupDataPreparation()
                    }
                    .font(.system(size: 17, weight: .bold, design: .rounded))
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                }
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: 420)
        }
    }

    private var clampedProgress: Double {
        min(1, max(0, viewModel.startupProgress))
    }
}

/// Shared first-run rules: a seed cannot unlock driving, and a download made
/// during an unfinished walkthrough must not accidentally complete migration.
enum FirstRunOnboardingPolicy {
    static let lastStep = 4

    static func hasUsableMap(databaseReady: Bool, bundleVersion: String) -> Bool {
        let version = bundleVersion.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return databaseReady && !version.isEmpty && version != "none" && version != "seed"
    }

    static func resolveCompletion(storedCompletion: Bool?, hasMap: Bool) -> Bool {
        hasMap && (storedCompletion ?? true)
    }

    static func resolvedStep(storedStep: Int, hasMap: Bool) -> Int {
        hasMap ? min(lastStep, max(0, storedStep)) : 0
    }

    static func canAdvance(step: Int, hasMap: Bool, hasPreciseLocation: Bool) -> Bool {
        guard hasMap else { return false }
        return step != 1 && step != lastStep || hasPreciseLocation
    }

    static func canFinish(hasMap: Bool, hasPreciseLocation: Bool) -> Bool {
        hasMap && hasPreciseLocation
    }
}

struct FirstUserWelcomeView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @Environment(\.openURL) private var openURL
    @AppStorage("youspeed.onboarding.selected_map") private var selectedOptionID = ""
    @State private var enlargedScreenshot: OnboardingScreenshotSelection?

    private var step: Int { viewModel.onboardingStep }
    private var selectedOption: DriveSessionViewModel.BundleDownloadOption? {
        viewModel.bundleDownloadSections.flatMap(\.options).first { $0.id == selectedOptionID }
    }
    private var locationNeedsSettings: Bool {
        switch viewModel.onboardingLocationAuthorization {
        case .denied, .restricted: return true
        case .authorizedAlways, .authorizedWhenInUse: return !viewModel.onboardingHasPreciseLocation
        default: return false
        }
    }
    private let stepNames = ["map", "driving", "dashcam", "sources", "panoramax"]
    private let stepIcons = ["map", "location", "video", "signpost.right", "photo.on.rectangle"]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("YouSpeed").font(.headline)
                Spacer()
                Text(String(format: NSLocalizedString("onboarding.progress", comment: ""), step + 1, 5))
                    .font(.subheadline).foregroundStyle(.secondary)
                    .accessibilityIdentifier("onboarding.progress")
            }
            .padding(.horizontal, 24).padding(.vertical, 18)

            ProgressView(value: Double(step + 1), total: 5)
                .tint(.red).padding(.horizontal, 24)
                .accessibilityHidden(true)

            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Image(systemName: stepIcons[step])
                        .font(.system(size: 40, weight: .medium)).foregroundStyle(.red)
                        .accessibilityHidden(true)
                    Text(NSLocalizedString("onboarding.\(stepNames[step]).title", comment: ""))
                        .font(.largeTitle.bold()).fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                    Text(NSLocalizedString("onboarding.\(stepNames[step]).body", comment: ""))
                        .font(.body).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    switch step {
                    case 0: mapStep
                    case 1: drivingStep
                    case 2: dashcamStep
                    case 3: sourcesStep
                    default: panoramaxStep
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
            }
            .id(step)

            HStack(spacing: 16) {
                if step > 0 {
                    RecordingSafeButton("onboarding.back") { viewModel.goBackInOnboarding() }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("onboarding.back")
                }
                RecordingSafeButton(LocalizedStringKey(step == 4 ? "onboarding.finish" : "onboarding.next")) {
                    viewModel.advanceOnboarding()
                }
                .frame(maxWidth: .infinity)
                .buttonStyle(.borderedProminent).tint(.red)
                .disabled(!viewModel.canAdvanceOnboarding)
                .accessibilityIdentifier("onboarding.next")
            }
            .controlSize(.large)
            .padding(24)
        }
        .frame(maxWidth: 620)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .onAppear {
            if viewModel.driveStatus != "stopped" { viewModel.stopDriving() }
            viewModel.normalizeOnboardingState()
            viewModel.refreshOnboardingLocationPermission()
            if selectedOptionID.isEmpty { selectedOptionID = viewModel.recommendedBundleOptionID ?? "" }
        }
        .onChange(of: viewModel.recommendedBundleOptionID) { _, optionID in
            if selectedOptionID.isEmpty { selectedOptionID = optionID ?? "" }
        }
        .sheet(item: $enlargedScreenshot) { selection in
            OnboardingScreenshotViewer(selection: selection)
        }
    }

    private var mapStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            RecordingSafeButton("onboarding.map.locate", systemImage: "location") {
                if locationNeedsSettings { openSystemSettings() }
                else {
                    selectedOptionID = ""
                    viewModel.retryFirstLocationSetup()
                }
            }
            .buttonStyle(.bordered).controlSize(.large)
            .accessibilityIdentifier("onboarding.location")
            Text(viewModel.firstLocationPackStatus).font(.footnote).foregroundStyle(.secondary)

            if let recommendedID = viewModel.recommendedBundleOptionID,
               let option = viewModel.bundleDownloadSections.flatMap(\.options).first(where: { $0.id == recommendedID }) {
                RecordingSafeButton {
                    selectedOptionID = option.id
                    viewModel.selectOnboardingMap(option.id)
                } label: {
                    Label(String(format: NSLocalizedString("onboarding.map.suggested", comment: ""), option.displayName), systemImage: "location.fill")
                }
                .accessibilityIdentifier("onboarding.recommendation")
            }

            Picker("onboarding.map.region", selection: Binding(
                get: { selectedOptionID },
                set: {
                    selectedOptionID = $0
                    viewModel.selectOnboardingMap($0)
                }
            )) {
                Text("onboarding.map.choose").tag("")
                ForEach(viewModel.bundleDownloadSections) { country in
                    Section(country.countryName) {
                        ForEach(country.options) { option in
                            Text(option.displayName).tag(option.id)
                        }
                    }
                }
            }
            .pickerStyle(.menu)
            .disabled(viewModel.isSyncingNow)
            .accessibilityIdentifier("onboarding.map.region")

            if let option = selectedOption {
                let size = viewModel.bundleSizeText(for: option)
                if !size.isEmpty {
                    Text(size).font(.subheadline).foregroundStyle(.secondary)
                }
                if viewModel.isActiveBundleDownload(option) {
                    ProgressView(value: viewModel.activeBundleDownloadProgress(option))
                    Text(viewModel.activeBundleDownloadBytesText(option)).font(.caption)
                    Text(viewModel.syncProgressDetail).font(.caption).foregroundStyle(.secondary)
                } else {
                    RecordingSafeButton(LocalizedStringKey(viewModel.syncStatus == "sync_failed" ? "onboarding.map.retry" : "onboarding.map.download"), systemImage: "arrow.down.circle") {
                        viewModel.downloadSelectedBundle(option, firstLocationSetup: true)
                    }
                    .buttonStyle(.borderedProminent).tint(.red).controlSize(.large)
                    .disabled(viewModel.isSyncingNow)
                    .accessibilityIdentifier("onboarding.map.download")
                }
            }
            if viewModel.syncStatus == "sync_failed", !viewModel.lastError.isEmpty {
                Text(viewModel.lastError).font(.footnote).foregroundStyle(.red)
                    .accessibilityIdentifier("onboarding.map.error")
            }
            if viewModel.hasOnboardingMap {
                Label("onboarding.map.ready", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    .accessibilityIdentifier("onboarding.map.ready")
            }
            Text("onboarding.map.network").font(.footnote).foregroundStyle(.secondary)
            Text("welcome.osm_credit").font(.caption).foregroundStyle(.secondary)
        }
    }

    private var drivingStep: some View {
        VStack(alignment: .leading, spacing: 18) {
            if viewModel.onboardingHasPreciseLocation {
                Label("onboarding.driving.ready", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            } else {
                Text("onboarding.driving.permission").font(.callout)
                RecordingSafeButton(LocalizedStringKey(locationNeedsSettings ? "onboarding.driving.settings" : "onboarding.driving.allow")) {
                    if locationNeedsSettings { openSystemSettings() }
                    else { viewModel.requestOnboardingLocation() }
                }
                .buttonStyle(.borderedProminent).tint(.red)
            }
            Divider()
            Toggle("settings.audio.voice_output", isOn: $viewModel.audioAlertsEnabled)
            Stepper(value: $viewModel.audioAlertThresholdKmh, in: 0...80) {
                Text(String(format: NSLocalizedString("onboarding.driving.threshold", comment: ""), viewModel.audioAlertThresholdKmh))
            }
            .disabled(!viewModel.audioAlertsEnabled)
            Text("onboarding.driving.safety").font(.footnote).foregroundStyle(.secondary)
        }
    }

    private var dashcamStep: some View {
        VStack(alignment: .leading, spacing: 18) {
            screenshot("onboarding-dashcam", caption: "onboarding.dashcam.screenshot")
            information("onboarding.dashcam.controls", icon: "record.circle")
            information("onboarding.dashcam.library", icon: "play.rectangle.on.rectangle")
            information("onboarding.dashcam.share", icon: "square.and.arrow.up")
            information("onboarding.dashcam.permission", icon: "camera")
        }
    }

    private var sourcesStep: some View {
        VStack(alignment: .leading, spacing: 18) {
            Toggle("drive_recorder.settings.tsr", isOn: $viewModel.trafficSignRecognitionEnabled)
            Toggle("drive_recorder.settings.tsr_independent", isOn: $viewModel.trafficSignRecognitionIndependentEnabled)
                .disabled(!viewModel.trafficSignRecognitionEnabled)
            HStack(alignment: .top, spacing: 16) {
                screenshot("onboarding-map-limit", caption: "onboarding.sources.map_screenshot")
                screenshot("onboarding-camera-limit", caption: "onboarding.sources.camera_screenshot")
            }
            information("onboarding.sources.eye", icon: "eye")
            information("onboarding.sources.map", icon: "map")
            information("onboarding.sources.voice", icon: "mic")
            information("onboarding.sources.camera", icon: "camera.viewfinder")
            Text("onboarding.sources.independent").font(.footnote).foregroundStyle(.secondary)
        }
    }

    private var panoramaxStep: some View {
        VStack(alignment: .leading, spacing: 18) {
            screenshot("onboarding-photo-review", caption: "onboarding.panoramax.screenshot")
            Toggle("drive_recorder.settings.panoramax", isOn: $viewModel.panoramaxCaptureEnabled)
            information("onboarding.panoramax.capture", icon: "camera")
            information("onboarding.panoramax.review", icon: "photo.on.rectangle")
            information("onboarding.panoramax.selection", icon: "checkmark.circle")
            information("onboarding.panoramax.upload", icon: "arrow.up.circle")
            screenshot("onboarding-photo-upload", caption: "onboarding.panoramax.account_screenshot")
            information("onboarding.panoramax.progress", icon: "arrow.clockwise")
            if !viewModel.onboardingHasPreciseLocation {
                Text("onboarding.driving.permission").font(.footnote)
                RecordingSafeButton(LocalizedStringKey(locationNeedsSettings ? "onboarding.driving.settings" : "onboarding.driving.allow")) {
                    if locationNeedsSettings { openSystemSettings() }
                    else { viewModel.requestOnboardingLocation() }
                }
                .buttonStyle(.bordered)
            }
            Text("onboarding.panoramax.later").font(.footnote).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func screenshot(_ name: String, caption: String) -> some View {
        if let image = UIImage(named: name) {
            VStack(alignment: .leading, spacing: 10) {
                RecordingSafeButton {
                    enlargedScreenshot = OnboardingScreenshotSelection(name: name, caption: caption)
                } label: {
                    Image(uiImage: image)
                        .resizable().scaledToFit()
                        .frame(maxHeight: 400)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .overlay { RoundedRectangle(cornerRadius: 16).stroke(.white.opacity(0.18), lineWidth: 1) }
                        .overlay(alignment: .bottomTrailing) {
                            Image(systemName: "arrow.up.left.and.arrow.down.right")
                                .font(.callout.weight(.semibold))
                                .padding(10).background(.black.opacity(0.8), in: Circle())
                                .padding(10)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text(LocalizedStringKey(caption)))
                .accessibilityHint(Text("onboarding.screenshot.enlarge"))
                Text(LocalizedStringKey(caption)).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func information(_ key: String, icon: String) -> some View {
        Label { Text(LocalizedStringKey(key)).fixedSize(horizontal: false, vertical: true) }
        icon: { Image(systemName: icon).foregroundStyle(.secondary).frame(width: 22) }
    }

    private func openSystemSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        openURL(url)
    }
}

private struct OnboardingScreenshotSelection: Identifiable {
    let name: String
    let caption: String
    var id: String { name }
}

private struct OnboardingScreenshotViewer: View {
    let selection: OnboardingScreenshotSelection
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                if let image = UIImage(named: selection.name) {
                    OnboardingZoomableScreenshot(image: image, accessibilityCaption: NSLocalizedString(selection.caption, comment: ""))
                }
                Text(LocalizedStringKey(selection.caption)).font(.footnote)
                    .padding(.horizontal)
                Text("onboarding.screenshot.zoom").font(.caption).foregroundStyle(.secondary)
                    .padding(.bottom)
            }
            .background(.black)
            .navigationTitle("onboarding.screenshot.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    RecordingSafeButton("onboarding.screenshot.close") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

/// Native scroll-view zoom keeps full-resolution screenshots readable and
/// supports panning with the same gestures as the system photo viewer.
private struct OnboardingZoomableScreenshot: UIViewRepresentable {
    let image: UIImage
    let accessibilityCaption: String

    func makeUIView(context: Context) -> OnboardingImageScrollView {
        let view = OnboardingImageScrollView(image: image)
        view.imageView.accessibilityLabel = accessibilityCaption
        return view
    }

    func updateUIView(_ view: OnboardingImageScrollView, context: Context) {
        view.imageView.accessibilityLabel = accessibilityCaption
    }
}

private final class OnboardingImageScrollView: UIScrollView, UIScrollViewDelegate {
    let imageView: UIImageView
    private var lastViewportSize = CGSize.zero

    init(image: UIImage) {
        imageView = UIImageView(image: image)
        super.init(frame: .zero)
        delegate = self
        minimumZoomScale = 1
        maximumZoomScale = 6
        bouncesZoom = true
        showsVerticalScrollIndicator = false
        showsHorizontalScrollIndicator = false
        imageView.isAccessibilityElement = true
        addSubview(imageView)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        guard bounds.size != lastViewportSize,
              bounds.width > 0, bounds.height > 0,
              let image = imageView.image else { return }
        lastViewportSize = bounds.size
        setZoomScale(1, animated: false)
        let scale = min(bounds.width / image.size.width, bounds.height / image.size.height)
        imageView.frame = CGRect(origin: .zero, size: CGSize(width: image.size.width * scale, height: image.size.height * scale))
        contentSize = imageView.frame.size
        centerImage()
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }

    func scrollViewDidZoom(_ scrollView: UIScrollView) { centerImage() }

    private func centerImage() {
        let horizontal = max(0, (bounds.width - contentSize.width) / 2)
        let vertical = max(0, (bounds.height - contentSize.height) / 2)
        contentInset = UIEdgeInsets(top: vertical, left: horizontal, bottom: vertical, right: horizontal)
    }
}

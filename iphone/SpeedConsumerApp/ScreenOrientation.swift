import SwiftUI
import UIKit
import ImageIO

/// The mount is chosen by the driver, never inferred from motion sensors.
enum ScreenOrientation: String, CaseIterable, Identifiable {
    case portrait
    case landscapeCameraLowerRight = "landscape_camera_lower_right"
    case landscapeCameraUpperLeft = "landscape_camera_upper_left"

    static let defaultsKey = "youspeed.screen_orientation"
    var id: String { rawValue }
    var isLandscape: Bool { self != .portrait }
    var localizationKey: String { "settings.orientation.\(rawValue)" }
    static func load(from defaults: UserDefaults = .standard) -> Self {
        defaults.string(forKey: defaultsKey).flatMap(Self.init(rawValue:)) ?? .portrait
    }
    var interfaceOrientation: UIInterfaceOrientation {
        switch self {
        case .portrait: .portrait
        case .landscapeCameraLowerRight: .landscapeLeft
        case .landscapeCameraUpperLeft: .landscapeRight
        }
    }
    var interfaceMask: UIInterfaceOrientationMask {
        switch self {
        case .portrait: .portrait
        case .landscapeCameraLowerRight: .landscapeLeft
        case .landscapeCameraUpperLeft: .landscapeRight
        }
    }
    var captureRotationAngle: CGFloat {
        switch self {
        case .portrait: 90
        case .landscapeCameraLowerRight: 180
        case .landscapeCameraUpperLeft: 0
        }
    }
    /// Video-data buffers retain the rear sensor's native orientation.
    var frameOrientation: CGImagePropertyOrientation {
        switch self {
        case .portrait: .right
        case .landscapeCameraLowerRight: .down
        case .landscapeCameraUpperLeft: .up
        }
    }
}

@MainActor
final class ManualScreenOrientationController {
    static let shared = ManualScreenOrientationController()
    var selection = ScreenOrientation.load()

    func apply(to scene: UIWindowScene, failed: @escaping (Error) -> Void) {
        for window in scene.windows {
            var controller = window.rootViewController
            while let current = controller {
                current.setNeedsUpdateOfSupportedInterfaceOrientations()
                controller = current.presentedViewController
            }
        }
        scene.requestGeometryUpdate(.iOS(interfaceOrientations: selection.interfaceMask)) { error in
            failed(error)
        }
    }
}

struct ManualOrientationSceneBridge: UIViewControllerRepresentable {
    let selection: ScreenOrientation
    var failed: (Error) -> Void = { _ in }
    func makeUIViewController(context: Context) -> Controller { Controller() }
    func updateUIViewController(_ controller: Controller, context: Context) {
        controller.selection = selection
        controller.failed = failed
        controller.applySelection()
    }
    final class Controller: UIViewController {
        var selection = ScreenOrientation.load()
        private var appliedSelection: ScreenOrientation?
        private var failedSelection: ScreenOrientation?
        var failed: (Error) -> Void = { _ in }
        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            failedSelection = nil
            applySelection()
        }
        func applySelection() {
            ManualScreenOrientationController.shared.selection = selection
            guard let scene = view.window?.windowScene,
                  appliedSelection != selection, failedSelection != selection else { return }
            appliedSelection = selection
            let requested = selection
            ManualScreenOrientationController.shared.apply(to: scene) { [weak self] error in
                Task { @MainActor [weak self] in
                    guard let self, appliedSelection == requested else { return }
                    appliedSelection = nil
                    failedSelection = requested
                    failed(error)
                }
            }
        }
    }
}

/// One accepted action waits for the movie delegate's finalization result.
/// Repeated taps while waiting are ignored; failure never executes the action.
@MainActor
final class DriveInteractionGate {
    private(set) var isFinalizing = false
    private(set) var didFinalizeForCurrentAction = false
    private var pendingToken: UUID?

    func cancel() {
        pendingToken = nil
        isFinalizing = false
    }

    func perform(
        needsFinalization: Bool,
        finalize: (@escaping (Result<Void, Error>) -> Void) -> Void,
        changed: @escaping (Bool) -> Void,
        failed: @escaping (Error) -> Void,
        action: @escaping () -> Void
    ) {
        guard !isFinalizing else { return }
        guard needsFinalization else { action(); return }
        let token = UUID()
        pendingToken = token
        isFinalizing = true
        changed(true)
        finalize { [weak self] result in
            guard let self, pendingToken == token else { return }
            pendingToken = nil
            isFinalizing = false
            changed(false)
            switch result {
            case .success:
                didFinalizeForCurrentAction = true
                defer { didFinalizeForCurrentAction = false }
                action()
            case .failure(let error):
                failed(error)
            }
        }
    }
}

enum DriveInteractionError: LocalizedError {
    case finalizationFailed
    var errorDescription: String? {
        NSLocalizedString("drive_recorder.action.failed", comment: "")
    }
}

struct DriveInteraction {
    var perform: (@escaping () -> Void) -> Void = { $0() }
}
private struct DriveInteractionKey: EnvironmentKey {
    static let defaultValue = DriveInteraction()
}
extension EnvironmentValues {
    var driveInteraction: DriveInteraction {
        get { self[DriveInteractionKey.self] }
        set { self[DriveInteractionKey.self] = newValue }
    }
}

/// Preserves native button roles, styling, keyboard and accessibility behavior.
struct RecordingSafeButton<Label: View>: View {
    @Environment(\.driveInteraction) private var interaction
    private let role: ButtonRole?
    private let action: () -> Void
    private let label: Label
    init(role: ButtonRole? = nil, action: @escaping () -> Void, @ViewBuilder label: () -> Label) {
        self.role = role
        self.action = action
        self.label = label()
    }
    var body: some View {
        Button(role: role) { interaction.perform(action) } label: { label }
    }
}
extension RecordingSafeButton where Label == Text {
    init(_ title: LocalizedStringKey, role: ButtonRole? = nil, action: @escaping () -> Void) {
        self.init(role: role, action: action) { Text(title) }
    }
    init<S: StringProtocol>(_ title: S, role: ButtonRole? = nil, action: @escaping () -> Void) {
        self.init(role: role, action: action) { Text(title) }
    }
}
extension RecordingSafeButton where Label == SwiftUI.Label<Text, Image> {
    init(_ title: LocalizedStringKey, systemImage: String, action: @escaping () -> Void) {
        self.init(action: action) { SwiftUI.Label(title, systemImage: systemImage) }
    }
}

/// Keep the sheet dismissal separate from a pushed page's Back action.
private struct SubscreenDismissKey: EnvironmentKey {
    static let defaultValue: (() -> Void)? = nil
}

extension EnvironmentValues {
    var dismissSubscreen: (() -> Void)? {
        get { self[SubscreenDismissKey.self] }
        set { self[SubscreenDismissKey.self] = newValue }
    }
}

struct DismissibleNavigationSheet<Content: View>: View {
    @Environment(\.dismiss) private var dismiss
    private let content: Content

    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        NavigationStack { content }
            .environment(\.dismissSubscreen, { dismiss() })
    }
}

private struct SubscreenCloseButton: ViewModifier {
    @Environment(\.dismissSubscreen) private var close

    func body(content: Content) -> some View {
        content.toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if let close {
                    RecordingSafeButton(action: close) {
                        Image(systemName: "xmark")
                            .font(.body.weight(.semibold))
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(Text("common.close"))
                    .accessibilityIdentifier("subscreen.close")
                }
            }
        }
    }
}

extension View {
    func subscreenCloseButton() -> some View { modifier(SubscreenCloseButton()) }
}

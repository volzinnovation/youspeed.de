import CoreMotion
import SwiftUI

/// Gravity can establish roll and tilt, but cannot establish the vehicle's heading.
struct GravityAlignmentReading: Equatable {
    let rollDegrees: Double
    let tiltDegrees: Double

    var isLevel: Bool { abs(rollDegrees) <= 3 && abs(tiltDegrees) <= 3 }
}

enum GravityAlignmentGeometry {
    /// Core Motion's gravity vector points down in the phone's portrait axes.
    static func reading(x: Double, y: Double, z: Double,
                        orientation: ScreenOrientation) -> GravityAlignmentReading? {
        guard x.isFinite, y.isFinite, z.isFinite else { return nil }
        let length = sqrt(x * x + y * y + z * z)
        guard (0.5...1.5).contains(length) else { return nil }
        let screenX: Double
        let screenY: Double
        switch orientation {
        case .portrait: (screenX, screenY) = (x, y)
        case .landscapeCameraLowerRight: (screenX, screenY) = (y, -x)
        case .landscapeCameraUpperLeft: (screenX, screenY) = (-y, x)
        }
        let inPlane = hypot(screenX, screenY)
        // A phone lying flat has no stable horizon. Do not show a false level.
        guard inPlane / length >= 0.1 else { return nil }
        return GravityAlignmentReading(
            rollDegrees: atan2(screenX, -screenY) * 180 / .pi,
            tiltDegrees: atan2(z, inPlane) * 180 / .pi
        )
    }
}

enum GravityAlignmentVisibility {
    static func isFreshStationary(speedKmh: Double?, stationaryObservedAt: Date?, now: Date,
                                  inTunnel: Bool) -> Bool {
        guard !inTunnel, let speedKmh, speedKmh.isFinite, speedKmh == 0,
              let stationaryObservedAt else { return false }
        let age = now.timeIntervalSince(stationaryObservedAt)
        return age.isFinite && (0...3).contains(age)
    }

    static func isVisible(landscape: Bool, controlsAllowed: Bool, speedKmh: Double?,
                          stationaryObservedAt: Date?, now: Date, inTunnel: Bool) -> Bool {
        landscape && controlsAllowed && isFreshStationary(
            speedKmh: speedKmh, stationaryObservedAt: stationaryObservedAt, now: now, inTunnel: inTunnel
        )
    }
}

@MainActor
private final class GravityAlignmentMotion: ObservableObject {
    @Published private(set) var reading: GravityAlignmentReading?
    private let manager = CMMotionManager()
    private var generation: UUID?
    private var filtered: (x: Double, y: Double, z: Double)?

    func start(orientation: ScreenOrientation) {
        stop()
        guard manager.isDeviceMotionAvailable else { return }
        let token = UUID()
        generation = token
        manager.deviceMotionUpdateInterval = 0.1
        manager.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: .main) { [weak self] motion, error in
            Task { @MainActor [weak self] in
                guard let self, self.generation == token else { return }
                guard let gravity = motion?.gravity, error == nil else {
                    self.reading = nil
                    return
                }
                let previous = self.filtered
                let alpha = 0.25
                let vector = (
                    x: previous.map { $0.x + alpha * (gravity.x - $0.x) } ?? gravity.x,
                    y: previous.map { $0.y + alpha * (gravity.y - $0.y) } ?? gravity.y,
                    z: previous.map { $0.z + alpha * (gravity.z - $0.z) } ?? gravity.z
                )
                self.filtered = vector
                self.reading = GravityAlignmentGeometry.reading(
                    x: vector.x, y: vector.y, z: vector.z, orientation: orientation
                )
            }
        }
    }

    func stop() {
        generation = nil
        manager.stopDeviceMotionUpdates()
        filtered = nil
        reading = nil
    }
}

/// The dashboard owns visibility and the 10%-by-10% frame. This view is never a control.
struct GravityAlignmentOverlay: View {
    let orientation: ScreenOrientation
    var foregroundColor: Color = .white
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var motion = GravityAlignmentMotion()

    private var accessibilityValue: String {
        guard let reading = motion.reading else {
            return NSLocalizedString("gravity_alignment.unavailable", comment: "")
        }
        return String(format: NSLocalizedString("gravity_alignment.angles", comment: ""),
                      reading.rollDegrees, reading.tiltDegrees)
    }

    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let radius = min(size.width, size.height) * 0.12
            let stroke = max(1, min(size.width, size.height) * 0.045)
            let neutral = foregroundColor.opacity(0.45)
            var target = Path()
            target.move(to: CGPoint(x: size.width * 0.12, y: center.y))
            target.addLine(to: CGPoint(x: size.width * 0.35, y: center.y))
            target.move(to: CGPoint(x: size.width * 0.65, y: center.y))
            target.addLine(to: CGPoint(x: size.width * 0.88, y: center.y))
            target.addEllipse(in: CGRect(x: center.x - radius, y: center.y - radius,
                                        width: radius * 2, height: radius * 2))
            context.stroke(target, with: .color(neutral), lineWidth: stroke)
            guard let reading = motion.reading else { return }
            var horizonContext = context
            horizonContext.translateBy(x: center.x, y: center.y)
            horizonContext.rotate(by: .degrees(-reading.rollDegrees))
            let offset = max(-1, min(1, reading.tiltDegrees / 20)) * size.height * 0.32
            let color = reading.isLevel ? Color.green : foregroundColor
            var horizon = Path()
            horizon.move(to: CGPoint(x: -size.width * 0.40, y: offset))
            horizon.addLine(to: CGPoint(x: size.width * 0.40, y: offset))
            horizonContext.stroke(horizon, with: .color(color), lineWidth: stroke)
            horizonContext.fill(Path(ellipseIn: CGRect(
                x: -radius * 0.55, y: offset - radius * 0.55,
                width: radius * 1.1, height: radius * 1.1
            )), with: .color(color))
        }
        .clipped()
        .allowsHitTesting(false)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(NSLocalizedString("gravity_alignment.title", comment: "")))
        .accessibilityValue(Text(accessibilityValue))
        .accessibilityIdentifier("dashboard.gravityAlignment")
        .onAppear { if scenePhase == .active { motion.start(orientation: orientation) } }
        .onDisappear { motion.stop() }
        .onChange(of: orientation) { _, value in
            if scenePhase == .active { motion.start(orientation: value) }
        }
        .onChange(of: scenePhase) { _, value in
            if value == .active { motion.start(orientation: orientation) }
            else { motion.stop() }
        }
    }
}

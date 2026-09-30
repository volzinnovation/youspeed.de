import SwiftUI
import AVFoundation
import CoreImage
import ImageIO

struct VisualRoadCalibrationPreview: @unchecked Sendable {
    let image: UIImage
    let width: Int
    let height: Int
    let orientationKey: String
    let capturedAt: Date
    let generation: Int
    var geometryKey: String { "\(width)x\(height):\(orientationKey)" }
}

/// A bounded display-only tap on the same video-data output used by TSR. No
/// still capture, alternate preview crop, photo queue or upload is involved.
final class VisualRoadCalibrationPreviewConsumer: DriveVideoFrameConsumer, @unchecked Sendable {
    private let lock = NSLock()
    private let queue = DispatchQueue(label: "de.youspeed.calibration-preview", qos: .userInitiated)
    private let context = CIContext(options: [.cacheIntermediates: false])
    private var epoch = 0
    private var enabled = false
    private var busy = false
    private var lastAdmission = -Double.infinity
    var onPreview: (@Sendable (VisualRoadCalibrationPreview) -> Void)?

    func setEnabled(_ enabled: Bool) { lock.lock(); self.enabled = enabled; epoch += 1; lock.unlock() }
    func isCurrent(_ preview: VisualRoadCalibrationPreview) -> Bool { lock.lock(); defer { lock.unlock() }; return enabled && preview.generation == epoch }
    func consumeVideoFrame(_ sampleBuffer: CMSampleBuffer, orientation: CGImagePropertyOrientation) {
        let now = ProcessInfo.processInfo.systemUptime
        lock.lock()
        guard enabled, !busy, now - lastAdmission >= 0.2,
              let pixel = CMSampleBufferGetImageBuffer(sampleBuffer) else { lock.unlock(); return }
        busy = true; lastAdmission = now; let admittedEpoch = epoch; lock.unlock()
        let capturedAt = Date()
        queue.async { [weak self] in
            guard let self else { return }
            defer { self.lock.lock(); self.busy = false; self.lock.unlock() }
            let upright = CIImage(cvPixelBuffer: pixel).oriented(forExifOrientation: Int32(orientation.rawValue))
            let width = Int(upright.extent.width), height = Int(upright.extent.height)
            let scale = min(1, min(960 / Double(width), 540 / Double(height)))
            let scaled = upright.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            guard let image = self.context.createCGImage(scaled, from: scaled.extent) else { return }
            self.lock.lock(); let current = self.enabled && admittedEpoch == self.epoch; self.lock.unlock()
            guard current else { return }
            self.onPreview?(VisualRoadCalibrationPreview(image: UIImage(cgImage: image), width: width, height: height,
                orientationKey: "rear:exif:\(orientation.rawValue)", capturedAt: capturedAt, generation: admittedEpoch))
        }
    }
}

struct VisualRoadCalibrationView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var draft: VisualRoadCalibration?
    @State private var step = 0
    private let stepKeys = ["horizon", "left_bottom", "left_top", "right_bottom", "right_top"]

    var body: some View {
        GeometryReader { geometry in
            let wide = geometry.size.width > geometry.size.height
            Group {
                if wide { HStack(spacing: 12) { preview; ScrollView { controls }.frame(width: min(300, geometry.size.width * 0.34)) } }
                else { VStack(spacing: 12) { preview; ScrollView { controls }.frame(maxHeight: min(380, geometry.size.height * 0.52)) } }
            }.padding(12)
        }
        .background(Color.black).foregroundStyle(.white)
        .navigationTitle(Text("calibration.title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("calibration.cancel") { dismiss() } } }
        .onAppear { viewModel.beginVisualRoadCalibration(); resetDraftForSource() }
        .onDisappear { viewModel.endVisualRoadCalibration() }
        .onChange(of: viewModel.visualCalibrationPreview?.geometryKey) { _, _ in resetDraftForSource() }
        .onChange(of: viewModel.drivingControlsAllowed) { _, allowed in if !allowed { dismiss() } }
        .onChange(of: viewModel.visualCalibrationActive) { _, active in if !active { dismiss() } }
    }

    private var preview: some View {
        GeometryReader { geometry in
            if let frame = viewModel.visualCalibrationPreview {
                let scale = min(geometry.size.width / CGFloat(frame.width), geometry.size.height / CGFloat(frame.height))
                let size = CGSize(width: CGFloat(frame.width) * scale, height: CGFloat(frame.height) * scale)
                ZStack {
                    Image(uiImage: frame.image).resizable().frame(width: size.width, height: size.height)
                    if let draft {
                        Canvas { context, canvas in
                            let guide = Color(red: 57.0 / 255, green: 1, blue: 20.0 / 255)
                            func point(_ p: LanePoint) -> CGPoint { CGPoint(x: p.x * canvas.width, y: p.y * canvas.height) }
                            func line(_ a: LanePoint, _ b: LanePoint, color: Color, active: Bool) {
                                var path = Path(); path.move(to: point(a)); path.addLine(to: point(b))
                                context.stroke(path, with: .color(.black), lineWidth: active ? 6 : 4)
                                context.stroke(path, with: .color(color), lineWidth: active ? 3 : 2)
                            }
                            line(LanePoint(x: 0, y: draft.horizonY), LanePoint(x: 1, y: draft.horizonY), color: step == 0 ? .yellow : .white, active: step == 0)
                            let leftTop = LanePoint(x: draft.leftTopX, y: draft.horizonY)
                            let rightTop = LanePoint(x: draft.rightTopX, y: draft.horizonY)
                            line(draft.leftBottom, leftTop, color: guide, active: step == 1 || step == 2)
                            line(draft.rightBottom, rightTop, color: guide, active: step == 3 || step == 4)
                            let markers = [(draft.leftBottom, 1), (leftTop, 2), (draft.rightBottom, 3), (rightTop, 4)]
                            for (p, index) in markers {
                                let c = point(p), radius: CGFloat = step == index ? 8 : 5
                                let circle = Path(ellipseIn: CGRect(x: c.x - radius, y: c.y - radius, width: radius * 2, height: radius * 2))
                                context.fill(circle, with: .color(step == index ? .yellow : guide))
                                context.stroke(circle, with: .color(.black), lineWidth: 2)
                            }
                            var crop = Path(); crop.move(to: CGPoint(x: draft.leftTopX * canvas.width, y: 0)); crop.addLine(to: CGPoint(x: draft.leftTopX * canvas.width, y: canvas.height))
                            context.stroke(crop, with: .color(.white.opacity(0.8)), style: StrokeStyle(lineWidth: 1, dash: [5, 5]))
                        }.frame(width: size.width, height: size.height)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 12) { ProgressView(); Text("calibration.waiting").multilineTextAlignment(.center)
                    Text(viewModel.visualCalibrationStatus).font(.caption).multilineTextAlignment(.center) }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }.accessibilityIdentifier("calibration.analysisPreview")
    }

    private var controls: some View {
        VStack(spacing: 10) {
            Text(String(format: NSLocalizedString("calibration.step", comment: ""), step + 1)).font(.caption)
            Text(LocalizedStringKey("calibration.\(stepKeys[step])")).font(.headline).multilineTextAlignment(.center)
            Text("calibration.crop_note").font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            VStack(spacing: 5) {
                if step == 0 || step == 1 || step == 3 { arrow("arrow.up", dx: 0, dy: -0.005, label: "calibration.up") }
                if step != 0 { HStack(spacing: 30) {
                    arrow("arrow.left", dx: -0.005, dy: 0, label: "calibration.left")
                    arrow("arrow.right", dx: 0.005, dy: 0, label: "calibration.right")
                } }
                if step == 0 || step == 1 || step == 3 { arrow("arrow.down", dx: 0, dy: 0.005, label: "calibration.down") }
            }.disabled(draft == nil || !viewModel.drivingControlsAllowed)
            if draft?.isValid == false { Text("calibration.invalid").font(.caption).foregroundStyle(.orange) }
            HStack {
                Button("calibration.previous") { step -= 1 }.disabled(step == 0)
                Spacer()
                if step == 4 {
                    Button("calibration.save") {
                        guard let draft, viewModel.saveVisualRoadCalibration(draft) else { return }; dismiss()
                    }.disabled(draft?.isValid != true || !viewModel.drivingControlsAllowed)
                    .accessibilityIdentifier("calibration.save")
                } else { Button("calibration.next") { step += 1 }.disabled(draft == nil) }
            }.buttonStyle(.borderedProminent)
            Button("calibration.defaults") {
                guard let frame = viewModel.visualCalibrationPreview else { return }
                draft = .defaults(width: frame.width, height: frame.height, orientationKey: frame.orientationKey)
                step = 0
            }.font(.caption)
        }
    }

    private func arrow(_ image: String, dx: Double, dy: Double, label: String) -> some View {
        Button { draft?.move(step: step, dx: dx, dy: dy) } label: {
            Image(systemName: image).font(.title2.weight(.bold)).frame(width: 46, height: 40)
        }.buttonStyle(.bordered).accessibilityLabel(Text(LocalizedStringKey(label)))
    }
    private func resetDraftForSource() {
        guard let frame = viewModel.visualCalibrationPreview else { return }
        if draft?.compatible(width: frame.width, height: frame.height, orientationKey: frame.orientationKey) == true { return }
        let stored = viewModel.visualRoadCalibration
        draft = stored?.compatible(width: frame.width, height: frame.height, orientationKey: frame.orientationKey) == true
            ? stored : .defaults(width: frame.width, height: frame.height, orientationKey: frame.orientationKey)
        step = 0
    }
}

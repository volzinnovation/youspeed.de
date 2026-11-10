import CoreML
import Foundation
import UIKit
import Vision

@main
final class Bench: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let view = UIViewController()
        view.view.backgroundColor = .systemBackground
        let status = UILabel()
        status.text = "Running paired detector replay"
        status.textAlignment = .center
        status.numberOfLines = 0
        view.view = status
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = view
        window.makeKeyAndVisible()
        self.window = window
        application.isIdleTimerDisabled = true
        Task.detached {
            let directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            do {
                let result = try await Self.run(directory)
                try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
                    .write(to: directory.appendingPathComponent("results.json"), options: .atomic)
                await MainActor.run { status.text = "Paired detector replay completed"; application.isIdleTimerDisabled = false }
            } catch {
                try? error.localizedDescription.write(to: directory.appendingPathComponent("failure.txt"), atomically: true, encoding: .utf8)
                await MainActor.run { status.text = error.localizedDescription; application.isIdleTimerDisabled = false }
            }
        }
        return true
    }

    private struct Frame: Decodable {
        let id: String
        let file: String
    }

    private static func run(_ directory: URL) async throws -> [String: Any] {
        let input = directory.appendingPathComponent("replay")
        let frames = try JSONDecoder().decode([Frame].self, from: Data(contentsOf: input.appendingPathComponent("frames.json")))
        var results = [String: Any]()
        for (name, modelName, threshold) in [("sgblur","sgblur.mlmodelc",0.25),("town","town.mlmodelc",0.840783)] {
            let modelURL = directory.appendingPathComponent(modelName)
            let configuration = MLModelConfiguration()
            configuration.computeUnits = name == "town" ? .cpuAndNeuralEngine : .all
            let model = try VNCoreMLModel(for: MLModel(contentsOf: modelURL, configuration: configuration))
            let thermalStart = ProcessInfo.processInfo.thermalState.rawValue
            let request = VNCoreMLRequest(model: model)
            request.imageCropAndScaleOption = .scaleFit
            var outputs = [[String: Any]]()
            for frame in Array(frames.prefix(5)) + frames {
                let url = input.appendingPathComponent(frame.file)
                guard let image = UIImage(contentsOfFile: url.path)?.cgImage else { throw CocoaError(.fileReadCorruptFile) }
                let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
                let start = DispatchTime.now().uptimeNanoseconds
                try handler.perform([request])
                let ms = Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000
                guard let objects = request.results as? [VNRecognizedObjectObservation] else { throw CocoaError(.fileReadCorruptFile) }
                let signs = objects.filter { $0.labels.first?.identifier == "sign" && Double($0.confidence) >= threshold }
                    .sorted { $0.confidence > $1.confidence }.prefix(12)
                let boxes = signs.map { object -> [Double] in
                    let b = object.boundingBox
                    return [Double(object.confidence), b.minX, 1 - b.maxY, b.maxX, 1 - b.minY]
                }
                outputs.append(["id":frame.id,"ms":ms,"boxes":boxes])
            }
            var placement = [String: Int]()
            if #available(iOS 17.4, *) {
                if let plan = try? await MLComputePlan.load(contentsOf: modelURL, configuration: configuration) {
                    placement = deviceCounts(plan)
                }
            }
            results[name] = ["threshold":threshold,"thermalStart":thermalStart,
                             "thermalEnd":ProcessInfo.processInfo.thermalState.rawValue,
                             "computeUnits":name == "town" ? "cpuAndNeuralEngine" : "all",
                             "preferredDevices":placement,"frames":Array(outputs.dropFirst(min(frames.count,5)))]
        }
        return results
    }

    @available(iOS 17.4, *)
    private static func deviceCounts(_ plan: MLComputePlan) -> [String: Int] {
        var counts = [String: Int]()
        func count(_ use: MLComputePlan.DeviceUsage?) {
            guard let device = use?.preferred else { return }
            let kind: String
            switch device {
            case .neuralEngine: kind = "neuralEngine"
            case .gpu: kind = "gpu"
            case .cpu: kind = "cpu"
            @unknown default: kind = "other"
            }
            counts[kind,default:0] += 1
        }
        func block(_ value: MLModelStructure.Program.Block) {
            for op in value.operations {
                count(plan.deviceUsage(for: op))
                for inner in op.blocks { block(inner) }
            }
        }
        func visit(_ structure: MLModelStructure) {
            switch structure {
            case .program(let program):
                for function in program.functions.values { block(function.block) }
            case .pipeline(let pipeline):
                for child in pipeline.subModels { visit(child) }
            case .neuralNetwork(let network):
                for layer in network.layers { count(plan.deviceUsage(for: layer)) }
            default: break
            }
        }
        visit(plan.modelStructure)
        return counts
    }
}

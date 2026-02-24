import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DriveSessionViewModel()
    @State private var manifestURL: String = "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.bundle-manifest.v3.json"

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Text("YouSpeed Consumer (v3)")
                    .font(.title2)
                    .bold()

                Group {
                    Text("sync=\(viewModel.syncStatus)")
                    Text("drive=\(viewModel.driveStatus)")
                    Text("bundle=\(viewModel.activeBundleVersion)")
                }
                .font(.footnote)

                TextField("Manifest URL", text: $manifestURL)
                    .textInputAutocapitalization(.never)
                    .disableAutocorrection(true)
                    .font(.caption)
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Button("Sync Data") {
                        viewModel.bootstrapAndSync(manifestURLString: manifestURL)
                    }
                    .buttonStyle(.borderedProminent)

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

                Spacer()
            }
            .padding()
            .navigationTitle("Speed Assist")
        }
    }
}

import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DriveSessionViewModel()

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

                if let syncMessage = syncMessageLine {
                    Text(syncMessage.text)
                        .font(.footnote)
                        .foregroundStyle(syncMessage.color)
                }

                if viewModel.syncStatus == "syncing" || viewModel.syncStatus == "bootstrapping" {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Sync progress: \(viewModel.syncProgressDetail)")
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
                            if !syncProgressMetaText.isEmpty {
                                Text(syncProgressMetaText)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                HStack {
                    Button("Sync Data") {
                        viewModel.bootstrapAndSync()
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

                GroupBox("Lookup Diagnostics") {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 8) {
                            Text("radius \(Int(viewModel.lookupRadiusM)) m")
                            Slider(value: $viewModel.lookupRadiusM, in: 50...500, step: 10)
                        }

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

    private var syncMessageLine: (text: String, color: Color)? {
        switch viewModel.syncStatus {
        case "ready_upToDate":
            return ("Data is available and up to date.", .green)
        case "ready_fullDownload", "ready_deltaPatch":
            return ("Data sync completed. Local data is up to date.", .green)
        case "ready_bootstrap":
            return ("Seed data is available locally.", .orange)
        case "sync_failed" where !viewModel.activeDBPath.isEmpty:
            return ("Sync failed, but local data is still available.", .orange)
        case "sync_failed":
            return ("Sync failed. No active data bundle available.", .red)
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
            let completedText = formatter.string(fromByteCount: completed)
            let totalText = formatter.string(fromByteCount: total)
            return "\(completedText) / \(totalText)"
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
                parts.append("ETA \(etaText)")
            }
        }
        return parts.joined(separator: " • ")
    }
}

import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = DriveSessionViewModel()
    @State private var hasAutoTriggeredSyncForTests = false
    @State private var showingSettings = false
    @State private var showingDebug = false

    var body: some View {
        GeometryReader { proxy in
            let screenInset = min(proxy.size.width, proxy.size.height) * 0.02
            let signSize = min(proxy.size.width * 0.78, proxy.size.width - (screenInset * 2))
            ZStack {
                screenBackgroundColor
                    .ignoresSafeArea()

                VStack(spacing: 18) {
                    topCornerButtons

                    SpeedLimitSignView(limitText: limitText)
                        .frame(width: signSize, height: signSize)
                        .frame(maxWidth: .infinity)
                        .padding(.top, screenInset)
                        .padding(.horizontal, screenInset)

                    if let fine = finePresentation {
                        FineNoticeView(fine: fine)
                    } else {
                        normalSpeedInfo
                    }

                    Spacer(minLength: 8)

                    driveToggleButton
                }
                .padding(.horizontal, 14)
                .padding(.top, 8)
                .padding(.bottom, 16)
            }
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack {
                SettingsView(viewModel: viewModel)
            }
        }
        .sheet(isPresented: $showingDebug) {
            NavigationStack {
                DebugInformationView(viewModel: viewModel)
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

    private var topCornerButtons: some View {
        HStack {
            Button {
                showingDebug = true
            } label: {
                Image(systemName: "ladybug.fill")
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

    private var normalSpeedInfo: some View {
        VStack(spacing: 6) {
            Text("Current Speed")
                .font(.headline)
                .foregroundStyle(primaryForegroundColor.opacity(0.85))
            Text("\(Int(round(viewModel.currentSpeedKmh))) km/h")
                .font(.system(size: 56, weight: .black, design: .rounded))
                .foregroundStyle(primaryForegroundColor)
            Text(limitInfoText)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(primaryForegroundColor.opacity(0.85))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }

    private var driveToggleButton: some View {
        Button {
            if viewModel.driveStatus == "running" || viewModel.driveStatus == "requesting_location" {
                viewModel.stopDriving()
            } else {
                viewModel.startDriving()
            }
        } label: {
            Text(viewModel.driveStatus == "running" ? "Stop GPS" : "Start GPS")
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(buttonTextColor)
        .background(buttonFillColor, in: Capsule())
    }

    private var limitText: String {
        guard let speedLimit = viewModel.speedLimitKmh else {
            return "?"
        }
        return "\(speedLimit)"
    }

    private var limitInfoText: String {
        if let speedLimit = viewModel.speedLimitKmh {
            return "Limit \(speedLimit) km/h"
        }
        return "Limit not available yet"
    }

    private var finePresentation: SpeedPenaltyNotice? {
        viewModel.currentPenaltyNotice
    }

    private var screenBackgroundColor: Color {
        switch finePresentation?.severity {
        case .moneyOnly:
            return Color(red: 0.98, green: 0.87, blue: 0.20)
        case .pointsAndFine:
            return Color(red: 0.77, green: 0.09, blue: 0.13)
        case .none:
            return .black
        }
    }

    private var primaryForegroundColor: Color {
        switch finePresentation?.severity {
        case .moneyOnly:
            return .black
        case .pointsAndFine, .none:
            return .white
        }
    }

    private var buttonBackgroundColor: Color {
        switch finePresentation?.severity {
        case .moneyOnly:
            return Color.black.opacity(0.08)
        case .pointsAndFine, .none:
            return Color.white.opacity(0.14)
        }
    }

    private var buttonFillColor: Color {
        switch finePresentation?.severity {
        case .moneyOnly:
            return Color.black.opacity(0.15)
        case .pointsAndFine, .none:
            return Color.white.opacity(0.22)
        }
    }

    private var buttonTextColor: Color {
        switch finePresentation?.severity {
        case .moneyOnly:
            return .black
        case .pointsAndFine, .none:
            return .white
        }
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

private struct FineNoticeView: View {
    let fine: SpeedPenaltyNotice

    var body: some View {
        VStack(spacing: 8) {
            Text(fine.title)
                .font(.title2.bold())
            Text(fine.details)
                .font(.headline)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .foregroundStyle(fine.severity == .moneyOnly ? Color.black : Color.white)
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }
}

private struct SpeedLimitSignView: View {
    let limitText: String

    var body: some View {
        GeometryReader { proxy in
            let size = min(proxy.size.width, proxy.size.height)
            // Based on Zeichen 274 geometry: black border 7.875 / 450, red band 60.301 / 450.
            let blackBorderWidth = max(1, size * 0.0175)
            let redBandWidth = max(2, size * 0.134)
            ZStack {
                Circle()
                    .fill(Color.white)

                Circle()
                    .strokeBorder(Color.black.opacity(0.75), lineWidth: blackBorderWidth)

                Circle()
                    .inset(by: blackBorderWidth)
                    .strokeBorder(Color(red: 0.76, green: 0.07, blue: 0.11), lineWidth: redBandWidth)

                Text(limitText)
                    .font(.system(size: size * (limitText == "?" ? 0.5 : 0.38), weight: .black, design: .rounded))
                    .minimumScaleFactor(0.45)
                    .foregroundStyle(.black)
            }
            .frame(width: size, height: size)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

private struct SettingsView: View {
    @ObservedObject var viewModel: DriveSessionViewModel

    var body: some View {
        Form {
            Section("Auditory Feedback") {
                HStack {
                    Text("Start warning at")
                    Spacer()
                    TextField("km/h", value: $viewModel.audioAlertThresholdKmh, format: .number)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 64)
                    Text("km/h")
                        .foregroundStyle(.secondary)
                }

                Stepper(
                    "Threshold \(viewModel.audioAlertThresholdKmh) km/h above limit",
                    value: $viewModel.audioAlertThresholdKmh,
                    in: 0...80,
                    step: 1
                )

                Text(viewModel.audioAlertThresholdKmh == 0
                     ? "Auditory feedback is disabled."
                     : "Spoken warning starts at \(viewModel.audioAlertThresholdKmh) km/h above the detected speed limit.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section("Map Data Download") {
                LabeledContent("Status", value: syncStatusLabel)
                LabeledContent("Bundle", value: viewModel.activeBundleVersion)

                if let syncMessage = syncMessageLine {
                    Text(syncMessage.text)
                        .font(.footnote)
                        .foregroundStyle(syncMessage.color)
                }

                Button("Download/Sync Latest Data") {
                    viewModel.bootstrapAndSync()
                }
                .disabled(viewModel.isSyncingNow)

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

            Section("Penalty Rules") {
                LabeledContent("Active file", value: "DEU-rules.json")
                LabeledContent("Country", value: "\(viewModel.activePenaltyRules.countryName) (\(viewModel.activePenaltyRules.countryCode))")
                LabeledContent("Bands", value: "\(viewModel.activePenaltyRules.bands.count)")
            }

            Section("Debug") {
                NavigationLink("Open Debug Information") {
                    DebugInformationView(viewModel: viewModel)
                }
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var syncStatusLabel: String {
        switch viewModel.syncStatus {
        case "not_synced":
            return "Not synced"
        case "syncing":
            return "Syncing"
        case "sync_failed":
            return "Sync failed"
        default:
            return viewModel.syncStatus.replacingOccurrences(of: "_", with: " ")
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
                parts.append("ETA \(etaText)")
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
            }
            .padding()
        }
        .navigationTitle("Debug")
        .navigationBarTitleDisplayMode(.inline)
    }
}

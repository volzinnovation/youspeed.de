import SwiftUI

@MainActor
final class BenchmarkViewModel: ObservableObject {
    @Published var status: String = "idle"
    @Published var reportText: String = ""
    @Published var dbPath: String = ""

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }()

    func prepareBundledDB() {
        do {
            let stagedCountry = URL(fileURLWithPath: NSTemporaryDirectory())
                .appendingPathComponent("speeds_v4_germany.sqlite")
            if FileManager.default.fileExists(atPath: stagedCountry.path) {
                dbPath = stagedCountry.path
                status = "country_db_ready"
                return
            }

            let url = try AssetStore.prepareBundledDatabase(
                resourceName: "speeds_v4",
                extension: "sqlite",
                targetFileName: "speeds_v4.sqlite"
            )
            dbPath = url.path
            status = "bundled_db_ready"
        } catch {
            status = "error_prepare_db"
            reportText = String(describing: error)
        }
    }

    func runBenchmark() {
        Task {
            do {
                if dbPath.isEmpty {
                    prepareBundledDB()
                }
                let attrs = try FileManager.default.attributesOfItem(atPath: dbPath)
                let dbSize = (attrs[.size] as? NSNumber)?.int64Value ?? 0
                let repeats = dbSize > 1_000_000_000 ? 1 : 20
                let input = ProbeInput(
                    lat: 52.5200,
                    lon: 13.4050,
                    heading: 90.0,
                    repeats: repeats,
                    searchRadiusM: 1200.0,
                    tileRadius: 1,
                    maxCandidates: 5000,
                    topK: 5,
                    headingWeight: 2.0,
                    polylineTopN: 250
                )
                status = "running_benchmark"
                let runner = SQLiteBenchmarkRunner(dbPath: dbPath)
                let report = try runner.run(input: input)
                let data = try encoder.encode(report)
                reportText = String(decoding: data, as: UTF8.self)
                let reportURL = try writeReportToDocuments(data)
                status = "benchmark_finished"
                reportText += "\n\nsaved_report=\(reportURL.path)"
            } catch {
                status = "error_benchmark"
                reportText = String(describing: error)
            }
        }
    }

    private func writeReportToDocuments(_ data: Data) throws -> URL {
        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else {
            throw BenchmarkError.ioError("Unable to resolve Documents directory")
        }
        let ts = Int(Date().timeIntervalSince1970)
        let url = docs.appendingPathComponent("benchmark_report_\(ts).json")
        try data.write(to: url, options: .atomic)
        return url
    }
}

struct ContentView: View {
    @StateObject private var viewModel = BenchmarkViewModel()

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Text("Speed DB Benchmark")
                    .font(.title2)
                    .bold()
                Text("status=\(viewModel.status)")
                    .font(.footnote)
                    .accessibilityIdentifier("benchmarkStatus")

                HStack {
                    Button("Prepare DB") { viewModel.prepareBundledDB() }
                        .buttonStyle(.bordered)
                    Button("Run Benchmark") { viewModel.runBenchmark() }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("runBenchmarkButton")
                }

                if !viewModel.dbPath.isEmpty {
                    Text("db=\(viewModel.dbPath)")
                        .font(.caption)
                        .lineLimit(2)
                }

                ScrollView {
                    Text(viewModel.reportText)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: .infinity)
            }
            .padding()
            .navigationTitle("SQLite Probe")
        }
    }
}

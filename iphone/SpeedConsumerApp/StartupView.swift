import SwiftUI

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

                Text("Lade lokale Kartendaten")
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

                    Button("Erneut versuchen") {
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

struct FirstUserWelcomeView: View {
    @ObservedObject var viewModel: DriveSessionViewModel
    let onContinue: () -> Void

    var body: some View {
        ZStack {
            Color.black
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 18) {
                    Text("Willkommen bei YouSpeed")
                        .font(.system(size: 34, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.center)

                    Text("Geld sparen. Fahrverbot vermeiden. Sicher ankommen. YouSpeed zeigt dir live, was Dich Dein zu schnelles Fahren kostet. Achtung: Auch YouSpeed kann Fehler machen – Augen auf die Straße!")
                        .font(.system(size: 18, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white.opacity(0.92))
                        .multilineTextAlignment(.center)

                    DataCoverageMapView(activeBundleVersion: viewModel.activeBundleVersion)
                        .frame(height: 200)

                    Text(scopeDescriptionText)
                        .font(.system(size: 15, weight: .medium, design: .rounded))
                        .foregroundStyle(.white.opacity(0.88))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 8)

                    Text("Daten (c) OpenStreetMap - Open Database License 1.0.")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(.white.opacity(0.76))
                        .multilineTextAlignment(.leading)
                        .padding(12)
                        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

                    VStack(spacing: 10) {
                        Button {
                            viewModel.bootstrapAndSync()
                        } label: {
                            Text(downloadButtonTitle)
                                .frame(maxWidth: .infinity)
                        }
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                        .disabled(viewModel.isSyncingNow)

                        Button {
                            onContinue()
                        } label: {
                            Text("Mit vorhandenen Daten fortfahren")
                                .frame(maxWidth: .infinity)
                        }
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                        .buttonStyle(.bordered)
                        .tint(.white)
                    }

                    if shouldShowSyncProgress {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(viewModel.syncProgressDetail.isEmpty ? "Synchronisierung läuft..." : viewModel.syncProgressDetail)
                                .font(.system(size: 13, weight: .semibold, design: .rounded))
                                .foregroundStyle(.white.opacity(0.88))
                            if let progressValue = syncProgressValue {
                                ProgressView(value: progressValue, total: 1)
                                    .tint(.red)
                                Text(syncProgressBytesText)
                                    .font(.system(size: 12, weight: .regular, design: .rounded))
                                    .foregroundStyle(.white.opacity(0.72))
                            } else {
                                ProgressView()
                                    .tint(.red)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }

                    if viewModel.syncStatus == "sync_failed", !viewModel.lastError.isEmpty {
                        Text(viewModel.lastError)
                            .font(.system(size: 12, weight: .regular, design: .rounded))
                            .foregroundStyle(.red.opacity(0.95))
                            .multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                            .background(Color.red.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 24)
                .padding(.bottom, 28)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
            }
        }
    }

    private var scopeDescriptionText: String {
        if viewModel.activeBundleVersion == "seed" || viewModel.activeBundleVersion == "none" {
            return "Ohne Deutschland-Download ist nur der Regierungsbezirk Karlsruhe verfügbar."
        }
        return "Deutschland-Datensatz aktiv: \(viewModel.activeBundleVersion)"
    }

    private var downloadButtonTitle: String {
        if viewModel.activeBundleVersion == "seed" {
            return "Deutschland-Datensatz herunterladen"
        }
        if viewModel.syncStatus == "ready_fullDownload" || viewModel.syncStatus == "ready_upToDate" {
            return "Deutschland-Datensatz aktualisieren"
        }
        return "Deutschland-Datensatz herunterladen"
    }

    private var shouldShowSyncProgress: Bool {
        viewModel.syncStatus == "syncing" || viewModel.syncStatus == "bootstrapping"
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
        return formatter.string(fromByteCount: completed)
    }
}

private struct DataCoverageMapView: View {
    let activeBundleVersion: String

    private var hasGermanyDataset: Bool {
        activeBundleVersion != "seed" && activeBundleVersion != "none"
    }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.white.opacity(0.08))

            CoverageMercatorMap(hasGermanyDataset: hasGermanyDataset)
                .padding(8)

            VStack(alignment: .leading, spacing: 2) {
                Text("Deutschland")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.84))
                Text(hasGermanyDataset ? "Daten für Deutschland" : "Nur Karlsruhe Regierungsbezirk")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(hasGermanyDataset ? .blue.opacity(0.96) : .white.opacity(0.72))
            }
            .padding(.horizontal, 10)
            .padding(.bottom, 8)
        }
    }
}

private struct CoverageMercatorMap: View {
    let hasGermanyDataset: Bool

    var body: some View {
        Canvas { context, size in
            let rect = CGRect(origin: .zero, size: size).insetBy(dx: 8, dy: 8)
            let projector = MercatorProjector(referencePolygons: CoveragePolygons.germanyLandOSMAdminLevel2, in: rect)

            let germanyPath = mercatorPath(polygons: CoveragePolygons.germanyLandOSMAdminLevel2, projector: projector)
            let germanyFill = hasGermanyDataset ? Color.blue.opacity(0.80) : Color.white.opacity(0.92)
            context.fill(germanyPath, with: .color(germanyFill))
            context.stroke(
                germanyPath,
                with: .color(Color.black.opacity(hasGermanyDataset ? 0.30 : 0.40)),
                lineWidth: hasGermanyDataset ? 0.8 : 1.0
            )

            let karlsruhePath = mercatorPath(polygons: [CoveragePolygons.karlsruheRegbez], projector: projector)
            if hasGermanyDataset {
                context.stroke(
                    karlsruhePath,
                    with: .color(Color.white.opacity(0.98)),
                    style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round, dash: [6, 4])
                )
            } else {
                context.fill(karlsruhePath, with: .color(Color.blue.opacity(0.78)))
                context.stroke(
                    karlsruhePath,
                    with: .color(Color.white.opacity(0.95)),
                    lineWidth: 1.2
                )
            }
        }
    }
}

private struct MercatorProjector {
    private let minX: Double
    private let minY: Double
    private let xSpan: Double
    private let ySpan: Double
    private let drawRect: CGRect

    init(referencePolygons: [[GeoLonLat]], in rect: CGRect) {
        var minX = Double.greatestFiniteMagnitude
        var maxX = -Double.greatestFiniteMagnitude
        var minY = Double.greatestFiniteMagnitude
        var maxY = -Double.greatestFiniteMagnitude

        for polygon in referencePolygons {
            for point in polygon {
                let x = Self.mercatorX(point.lon)
                let y = Self.mercatorY(point.lat)
                minX = min(minX, x)
                maxX = max(maxX, x)
                minY = min(minY, y)
                maxY = max(maxY, y)
            }
        }

        let xSpan = max(maxX - minX, 0.000001)
        let ySpan = max(maxY - minY, 0.000001)
        let scale = min(rect.width / xSpan, rect.height / ySpan)
        let drawWidth = xSpan * scale
        let drawHeight = ySpan * scale

        self.drawRect = CGRect(
            x: rect.minX + (rect.width - drawWidth) / 2,
            y: rect.minY + (rect.height - drawHeight) / 2,
            width: drawWidth,
            height: drawHeight
        )
        self.minX = minX
        self.minY = minY
        self.xSpan = xSpan
        self.ySpan = ySpan
    }

    func project(_ point: GeoLonLat) -> CGPoint {
        let xMercator = Self.mercatorX(point.lon)
        let x = drawRect.minX + ((xMercator - minX) / xSpan) * drawRect.width
        let yMercator = Self.mercatorY(point.lat)
        let y = drawRect.maxY - ((yMercator - minY) / ySpan) * drawRect.height
        return CGPoint(x: x, y: y)
    }

    private static func mercatorX(_ longitude: Double) -> Double {
        let clamped = min(max(longitude, -180), 180)
        return clamped * .pi / 180
    }

    private static func mercatorY(_ latitude: Double) -> Double {
        let clamped = min(max(latitude, -85), 85)
        let radians = clamped * .pi / 180
        return log(tan(.pi / 4 + radians / 2))
    }
}

private func mercatorPath(polygons: [[GeoLonLat]], projector: MercatorProjector) -> Path {
    var path = Path()
    for polygon in polygons where polygon.count > 2 {
        path.move(to: projector.project(polygon[0]))
        for point in polygon.dropFirst() {
            path.addLine(to: projector.project(point))
        }
        path.closeSubpath()
    }
    return path
}

struct GeoLonLat {
    let lon: Double
    let lat: Double
}

enum CoveragePolygons {
    // Source: OSM administrative boundary for Germany (admin_level=2, relation 51477),
    // fetched via Nominatim polygon_geojson and simplified for on-device rendering.
    static let germanyLandOSMAdminLevel2: [[GeoLonLat]] = [
        [
            .init(lon: 10.454440, lat: 47.555796),
            .init(lon: 10.488912, lat: 47.540403),
            .init(lon: 10.571106, lat: 47.533472),
            .init(lon: 10.597948, lat: 47.569741),
            .init(lon: 10.691003, lat: 47.558770),
            .init(lon: 10.694596, lat: 47.544781),
            .init(lon: 10.751048, lat: 47.537277),
            .init(lon: 10.777508, lat: 47.513921),
            .init(lon: 10.890311, lat: 47.537314),
            .init(lon: 10.918007, lat: 47.513631),
            .init(lon: 10.871989, lat: 47.500363),
            .init(lon: 10.870040, lat: 47.483255),
            .init(lon: 10.937174, lat: 47.481137),
            .init(lon: 10.929539, lat: 47.470232),
            .init(lon: 10.983612, lat: 47.430018),
            .init(lon: 10.968792, lat: 47.411867),
            .init(lon: 10.971896, lat: 47.399558),
            .init(lon: 11.114824, lat: 47.395456),
            .init(lon: 11.128071, lat: 47.412196),
            .init(lon: 11.206990, lat: 47.433940),
            .init(lon: 11.253416, lat: 47.428238),
            .init(lon: 11.224959, lat: 47.395252),
            .init(lon: 11.269885, lat: 47.397565),
            .init(lon: 11.290057, lat: 47.407264),
            .init(lon: 11.291030, lat: 47.427080),
            .init(lon: 11.338613, lat: 47.449923),
            .init(lon: 11.421194, lat: 47.444592),
            .init(lon: 11.409438, lat: 47.466736),
            .init(lon: 11.383843, lat: 47.472375),
            .init(lon: 11.442090, lat: 47.517917),
            .init(lon: 11.449332, lat: 47.507243),
            .init(lon: 11.505664, lat: 47.504727),
            .init(lon: 11.572417, lat: 47.514506),
            .init(lon: 11.588109, lat: 47.525451),
            .init(lon: 11.586881, lat: 47.554720),
            .init(lon: 11.605763, lat: 47.581079),
            .init(lon: 11.633489, lat: 47.580589),
            .init(lon: 11.636180, lat: 47.594555),
            .init(lon: 11.660308, lat: 47.583804),
            .init(lon: 11.781048, lat: 47.591197),
            .init(lon: 11.844041, lat: 47.581212),
            .init(lon: 11.854955, lat: 47.602358),
            .init(lon: 11.976229, lat: 47.612978),
            .init(lon: 12.008533, lat: 47.625178),
            .init(lon: 12.021909, lat: 47.611083),
            .init(lon: 12.060719, lat: 47.618829),
            .init(lon: 12.129022, lat: 47.605649),
            .init(lon: 12.179004, lat: 47.614390),
            .init(lon: 12.178149, lat: 47.600890),
            .init(lon: 12.203961, lat: 47.606765),
            .init(lon: 12.199087, lat: 47.640851),
            .init(lon: 12.162425, lat: 47.701167),
            .init(lon: 12.203636, lat: 47.707433),
            .init(lon: 12.257029, lat: 47.743035),
            .init(lon: 12.264981, lat: 47.732517),
            .init(lon: 12.241261, lat: 47.694377),
            .init(lon: 12.255250, lat: 47.679451),
            .init(lon: 12.338035, lat: 47.697055),
            .init(lon: 12.363618, lat: 47.683842),
            .init(lon: 12.440071, lat: 47.695231),
            .init(lon: 12.440743, lat: 47.673905),
            .init(lon: 12.499170, lat: 47.625101),
            .init(lon: 12.536374, lat: 47.636473),
            .init(lon: 12.575027, lat: 47.632315),
            .init(lon: 12.607344, lat: 47.673727),
            .init(lon: 12.732117, lat: 47.679671),
            .init(lon: 12.757207, lat: 47.663036),
            .init(lon: 12.781165, lat: 47.673818),
            .init(lon: 12.778455, lat: 47.660917),
            .init(lon: 12.758575, lat: 47.651550),
            .init(lon: 12.824484, lat: 47.612107),
            .init(lon: 12.792884, lat: 47.600573),
            .init(lon: 12.779150, lat: 47.579142),
            .init(lon: 12.803935, lat: 47.550125),
            .init(lon: 12.847692, lat: 47.545978),
            .init(lon: 12.851711, lat: 47.530786),
            .init(lon: 12.882842, lat: 47.520615),
            .init(lon: 12.908726, lat: 47.496943),
            .init(lon: 12.968151, lat: 47.474451),
            .init(lon: 12.978008, lat: 47.484689),
            .init(lon: 13.001047, lat: 47.464012),
            .init(lon: 13.047647, lat: 47.492163),
            .init(lon: 13.047293, lat: 47.521496),
            .init(lon: 13.030936, lat: 47.532562),
            .init(lon: 13.057499, lat: 47.562148),
            .init(lon: 13.043652, lat: 47.583364),
            .init(lon: 13.070642, lat: 47.586978),
            .init(lon: 13.062619, lat: 47.601462),
            .init(lon: 13.098936, lat: 47.635172),
            .init(lon: 13.078081, lat: 47.666875),
            .init(lon: 13.080748, lat: 47.687034),
            .init(lon: 13.018338, lat: 47.722875),
            .init(lon: 12.973805, lat: 47.707153),
            .init(lon: 12.924907, lat: 47.710294),
            .init(lon: 12.905259, lat: 47.723435),
            .init(lon: 12.944816, lat: 47.764409),
            .init(lon: 12.929602, lat: 47.772984),
            .init(lon: 13.003361, lat: 47.850022),
            .init(lon: 12.938171, lat: 47.943283),
            .init(lon: 12.922610, lat: 47.939355),
            .init(lon: 12.917326, lat: 47.954997),
            .init(lon: 12.873910, lat: 47.963923),
            .init(lon: 12.850205, lat: 48.016211),
            .init(lon: 12.759481, lat: 48.075167),
            .init(lon: 12.749244, lat: 48.108513),
            .init(lon: 12.758126, lat: 48.126069),
            .init(lon: 12.786919, lat: 48.123711),
            .init(lon: 12.799402, lat: 48.146776),
            .init(lon: 12.847710, lat: 48.167375),
            .init(lon: 12.870051, lat: 48.201310),
            .init(lon: 12.956133, lat: 48.209281),
            .init(lon: 13.021680, lat: 48.257818),
            .init(lon: 13.180842, lat: 48.294992),
            .init(lon: 13.256216, lat: 48.293560),
            .init(lon: 13.329798, lat: 48.323514),
            .init(lon: 13.411357, lat: 48.374710),
            .init(lon: 13.439313, lat: 48.430840),
            .init(lon: 13.426998, lat: 48.456641),
            .init(lon: 13.458177, lat: 48.511909),
            .init(lon: 13.437839, lat: 48.557442),
            .init(lon: 13.475373, lat: 48.556061),
            .init(lon: 13.504034, lat: 48.572514),
            .init(lon: 13.508963, lat: 48.590600),
            .init(lon: 13.570904, lat: 48.560976),
            .init(lon: 13.599771, lat: 48.569388),
            .init(lon: 13.653746, lat: 48.548885),
            .init(lon: 13.664101, lat: 48.534169),
            .init(lon: 13.730522, lat: 48.514768),
            .init(lon: 13.747784, lat: 48.529390),
            .init(lon: 13.754071, lat: 48.563569),
            .init(lon: 13.770100, lat: 48.553588),
            .init(lon: 13.800936, lat: 48.573598),
            .init(lon: 13.801279, lat: 48.597394),
            .init(lon: 13.825798, lat: 48.618577),
            .init(lon: 13.813505, lat: 48.691841),
            .init(lon: 13.837433, lat: 48.700548),
            .init(lon: 13.814088, lat: 48.700906),
            .init(lon: 13.794892, lat: 48.715082),
            .init(lon: 13.819082, lat: 48.731827),
            .init(lon: 13.820988, lat: 48.754391),
            .init(lon: 13.839552, lat: 48.771618),
            .init(lon: 13.803388, lat: 48.780822),
            .init(lon: 13.815229, lat: 48.797088),
            .init(lon: 13.792937, lat: 48.830113),
            .init(lon: 13.764419, lat: 48.834476),
            .init(lon: 13.737928, lat: 48.886015),
            .init(lon: 13.675938, lat: 48.878734),
            .init(lon: 13.655475, lat: 48.893572),
            .init(lon: 13.622489, lat: 48.938805),
            .init(lon: 13.628603, lat: 48.949243),
            .init(lon: 13.610246, lat: 48.938622),
            .init(lon: 13.583902, lat: 48.969208),
            .init(lon: 13.529274, lat: 48.974049),
            .init(lon: 13.507063, lat: 48.969117),
            .init(lon: 13.508274, lat: 48.942137),
            .init(lon: 13.495772, lat: 48.941488),
            .init(lon: 13.402724, lat: 48.987223),
            .init(lon: 13.409413, lat: 49.003220),
            .init(lon: 13.391673, lat: 49.042147),
            .init(lon: 13.397371, lat: 49.050660),
            .init(lon: 13.289183, lat: 49.118635),
            .init(lon: 13.236059, lat: 49.113716),
            .init(lon: 13.182776, lat: 49.134485),
            .init(lon: 13.170294, lat: 49.144005),
            .init(lon: 13.170897, lat: 49.173623),
            .init(lon: 13.109887, lat: 49.203129),
            .init(lon: 13.114177, lat: 49.218257),
            .init(lon: 13.086211, lat: 49.229120),
            .init(lon: 13.080814, lat: 49.247409),
            .init(lon: 13.060405, lat: 49.250206),
            .init(lon: 13.055319, lat: 49.263925),
            .init(lon: 13.033982, lat: 49.263930),
            .init(lon: 13.029112, lat: 49.304329),
            .init(lon: 13.007400, lat: 49.305923),
            .init(lon: 12.945286, lat: 49.343796),
            .init(lon: 12.880021, lat: 49.350396),
            .init(lon: 12.886846, lat: 49.332350),
            .init(lon: 12.843490, lat: 49.345090),
            .init(lon: 12.785782, lat: 49.345464),
            .init(lon: 12.758074, lat: 49.375240),
            .init(lon: 12.757668, lat: 49.394802),
            .init(lon: 12.708704, lat: 49.424760),
            .init(lon: 12.655552, lat: 49.434799),
            .init(lon: 12.652998, lat: 49.460267),
            .init(lon: 12.633648, lat: 49.476153),
            .init(lon: 12.644214, lat: 49.484919),
            .init(lon: 12.644196, lat: 49.522966),
            .init(lon: 12.588541, lat: 49.538477),
            .init(lon: 12.594916, lat: 49.541724),
            .init(lon: 12.574348, lat: 49.559136),
            .init(lon: 12.576679, lat: 49.586345),
            .init(lon: 12.560743, lat: 49.619609),
            .init(lon: 12.528104, lat: 49.618102),
            .init(lon: 12.534285, lat: 49.626085),
            .init(lon: 12.517247, lat: 49.645405),
            .init(lon: 12.529974, lat: 49.666086),
            .init(lon: 12.521987, lat: 49.686444),
            .init(lon: 12.442452, lat: 49.703820),
            .init(lon: 12.400555, lat: 49.753805),
            .init(lon: 12.472651, lat: 49.786110),
            .init(lon: 12.464007, lat: 49.810051),
            .init(lon: 12.473057, lat: 49.833671),
            .init(lon: 12.497980, lat: 49.837528),
            .init(lon: 12.497864, lat: 49.856937),
            .init(lon: 12.512079, lat: 49.859403),
            .init(lon: 12.521608, lat: 49.881692),
            .init(lon: 12.550030, lat: 49.901538),
            .init(lon: 12.547676, lat: 49.920496),
            .init(lon: 12.474931, lat: 49.938522),
            .init(lon: 12.469991, lat: 49.948324),
            .init(lon: 12.499559, lat: 49.972049),
            .init(lon: 12.489959, lat: 49.981603),
            .init(lon: 12.460738, lat: 49.994874),
            .init(lon: 12.431480, lat: 49.984392),
            .init(lon: 12.431650, lat: 50.002510),
            .init(lon: 12.367495, lat: 50.017427),
            .init(lon: 12.339657, lat: 50.039330),
            .init(lon: 12.325875, lat: 50.032833),
            .init(lon: 12.317282, lat: 50.053372),
            .init(lon: 12.261627, lat: 50.058123),
            .init(lon: 12.275414, lat: 50.076472),
            .init(lon: 12.246652, lat: 50.097532),
            .init(lon: 12.200805, lat: 50.108698),
            .init(lon: 12.195163, lat: 50.143169),
            .init(lon: 12.215972, lat: 50.168205),
            .init(lon: 12.188856, lat: 50.195541),
            .init(lon: 12.197084, lat: 50.199066),
            .init(lon: 12.159694, lat: 50.211232),
            .init(lon: 12.162023, lat: 50.223456),
            .init(lon: 12.145385, lat: 50.230395),
            .init(lon: 12.151078, lat: 50.235716),
            .init(lon: 12.127193, lat: 50.232363),
            .init(lon: 12.092431, lat: 50.249610),
            .init(lon: 12.097614, lat: 50.262309),
            .init(lon: 12.140062, lat: 50.277837),
            .init(lon: 12.122823, lat: 50.290970),
            .init(lon: 12.126033, lat: 50.307241),
            .init(lon: 12.100805, lat: 50.318031),
            .init(lon: 12.184606, lat: 50.322223),
            .init(lon: 12.200948, lat: 50.308950),
            .init(lon: 12.201325, lat: 50.272839),
            .init(lon: 12.253843, lat: 50.270978),
            .init(lon: 12.265940, lat: 50.250181),
            .init(lon: 12.246917, lat: 50.257247),
            .init(lon: 12.239476, lat: 50.246157),
            .init(lon: 12.293905, lat: 50.221037),
            .init(lon: 12.274653, lat: 50.196550),
            .init(lon: 12.289362, lat: 50.176893),
            .init(lon: 12.335356, lat: 50.171971),
            .init(lon: 12.323476, lat: 50.181998),
            .init(lon: 12.338314, lat: 50.192289),
            .init(lon: 12.323367, lat: 50.207117),
            .init(lon: 12.334695, lat: 50.217291),
            .init(lon: 12.331294, lat: 50.242450),
            .init(lon: 12.359229, lat: 50.242130),
            .init(lon: 12.352586, lat: 50.262657),
            .init(lon: 12.370675, lat: 50.285108),
            .init(lon: 12.399628, lat: 50.293664),
            .init(lon: 12.398353, lat: 50.321401),
            .init(lon: 12.430964, lat: 50.322721),
            .init(lon: 12.442368, lat: 50.341999),
            .init(lon: 12.468552, lat: 50.354608),
            .init(lon: 12.489548, lat: 50.349797),
            .init(lon: 12.486384, lat: 50.370787),
            .init(lon: 12.512032, lat: 50.397259),
            .init(lon: 12.673273, lat: 50.416804),
            .init(lon: 12.707118, lat: 50.397120),
            .init(lon: 12.734473, lat: 50.432340),
            .init(lon: 12.794856, lat: 50.449431),
            .init(lon: 12.810498, lat: 50.430898),
            .init(lon: 12.806653, lat: 50.443336),
            .init(lon: 12.819035, lat: 50.460292),
            .init(lon: 12.948093, lat: 50.404251),
            .init(lon: 12.942255, lat: 50.411713),
            .init(lon: 12.985219, lat: 50.420358),
            .init(lon: 13.019869, lat: 50.446557),
            .init(lon: 13.031648, lat: 50.509744),
            .init(lon: 13.085297, lat: 50.500221),
            .init(lon: 13.132568, lat: 50.518621),
            .init(lon: 13.136623, lat: 50.506406),
            .init(lon: 13.195292, lat: 50.503241),
            .init(lon: 13.195167, lat: 50.516117),
            .init(lon: 13.229430, lat: 50.550137),
            .init(lon: 13.223031, lat: 50.563435),
            .init(lon: 13.248353, lat: 50.592073),
            .init(lon: 13.278711, lat: 50.592967),
            .init(lon: 13.291095, lat: 50.574929),
            .init(lon: 13.323154, lat: 50.581089),
            .init(lon: 13.324791, lat: 50.608445),
            .init(lon: 13.377297, lat: 50.627253),
            .init(lon: 13.371052, lat: 50.650814),
            .init(lon: 13.391817, lat: 50.646625),
            .init(lon: 13.414966, lat: 50.616529),
            .init(lon: 13.464859, lat: 50.601779),
            .init(lon: 13.497619, lat: 50.631971),
            .init(lon: 13.524276, lat: 50.638984),
            .init(lon: 13.525944, lat: 50.649403),
            .init(lon: 13.512788, lat: 50.653767),
            .init(lon: 13.544374, lat: 50.677548),
            .init(lon: 13.525244, lat: 50.704386),
            .init(lon: 13.551919, lat: 50.713741),
            .init(lon: 13.602735, lat: 50.710153),
            .init(lon: 13.664673, lat: 50.732084),
            .init(lon: 13.706712, lat: 50.716687),
            .init(lon: 13.728132, lat: 50.733659),
            .init(lon: 13.740562, lat: 50.727274),
            .init(lon: 13.758308, lat: 50.735825),
            .init(lon: 13.854941, lat: 50.726953),
            .init(lon: 13.861993, lat: 50.742797),
            .init(lon: 13.898797, lat: 50.745135),
            .init(lon: 13.887341, lat: 50.770073),
            .init(lon: 13.900779, lat: 50.793379),
            .init(lon: 13.938986, lat: 50.789928),
            .init(lon: 13.954363, lat: 50.807568),
            .init(lon: 13.990738, lat: 50.820005),
            .init(lon: 14.029926, lat: 50.804256),
            .init(lon: 14.078458, lat: 50.812479),
            .init(lon: 14.089523, lat: 50.826080),
            .init(lon: 14.223500, lat: 50.859086),
            .init(lon: 14.233366, lat: 50.887599),
            .init(lon: 14.267434, lat: 50.895314),
            .init(lon: 14.304752, lat: 50.883927),
            .init(lon: 14.349148, lat: 50.892700),
            .init(lon: 14.349092, lat: 50.900757),
            .init(lon: 14.388001, lat: 50.899200),
            .init(lon: 14.385677, lat: 50.916586),
            .init(lon: 14.402173, lat: 50.923839),
            .init(lon: 14.396969, lat: 50.936340),
            .init(lon: 14.311442, lat: 50.954010),
            .init(lon: 14.316996, lat: 50.960620),
            .init(lon: 14.302571, lat: 50.965259),
            .init(lon: 14.328181, lat: 50.973098),
            .init(lon: 14.323474, lat: 50.985385),
            .init(lon: 14.285695, lat: 50.976921),
            .init(lon: 14.258678, lat: 50.987540),
            .init(lon: 14.268725, lat: 51.000046),
            .init(lon: 14.260534, lat: 51.008823),
            .init(lon: 14.280134, lat: 51.014095),
            .init(lon: 14.286375, lat: 51.027490),
            .init(lon: 14.273854, lat: 51.039799),
            .init(lon: 14.289034, lat: 51.039487),
            .init(lon: 14.302094, lat: 51.055091),
            .init(lon: 14.336933, lat: 51.038994),
            .init(lon: 14.382682, lat: 51.038537),
            .init(lon: 14.384775, lat: 51.026990),
            .init(lon: 14.408568, lat: 51.018784),
            .init(lon: 14.453830, lat: 51.035944),
            .init(lon: 14.492717, lat: 51.023413),
            .init(lon: 14.490765, lat: 51.043554),
            .init(lon: 14.508401, lat: 51.043310),
            .init(lon: 14.498598, lat: 51.022090),
            .init(lon: 14.532187, lat: 51.016581),
            .init(lon: 14.534755, lat: 51.003743),
            .init(lon: 14.564552, lat: 51.010167),
            .init(lon: 14.599074, lat: 50.987175),
            .init(lon: 14.596159, lat: 50.962727),
            .init(lon: 14.564360, lat: 50.918574),
            .init(lon: 14.581938, lat: 50.913548),
            .init(lon: 14.650203, lat: 50.931522),
            .init(lon: 14.652835, lat: 50.905422),
            .init(lon: 14.636675, lat: 50.897841),
            .init(lon: 14.618917, lat: 50.857759),
            .init(lon: 14.708603, lat: 50.840779),
            .init(lon: 14.722344, lat: 50.822062),
            .init(lon: 14.744711, lat: 50.829482),
            .init(lon: 14.794066, lat: 50.820125),
            .init(lon: 14.824987, lat: 50.867562),
            .init(lon: 14.819555, lat: 50.885063),
            .init(lon: 14.896556, lat: 50.940646),
            .init(lon: 14.903080, lat: 50.971719),
            .init(lon: 14.919430, lat: 50.975347),
            .init(lon: 14.917185, lat: 50.995193),
            .init(lon: 14.929040, lat: 50.997981),
            .init(lon: 14.948505, lat: 51.042624),
            .init(lon: 14.964656, lat: 51.050123),
            .init(lon: 14.967629, lat: 51.071112),
            .init(lon: 14.979315, lat: 51.077038),
            .init(lon: 14.980878, lat: 51.116109),
            .init(lon: 14.997758, lat: 51.122764),
            .init(lon: 14.993119, lat: 51.162435),
            .init(lon: 15.005045, lat: 51.167716),
            .init(lon: 15.009831, lat: 51.213568),
            .init(lon: 15.037852, lat: 51.243991),
            .init(lon: 15.023301, lat: 51.250585),
            .init(lon: 15.041931, lat: 51.272912),
            .init(lon: 15.033354, lat: 51.294089),
            .init(lon: 15.012325, lat: 51.300979),
            .init(lon: 15.009282, lat: 51.316683),
            .init(lon: 14.986078, lat: 51.329381),
            .init(lon: 14.976237, lat: 51.357119),
            .init(lon: 14.965137, lat: 51.361187),
            .init(lon: 14.983755, lat: 51.373658),
            .init(lon: 14.958257, lat: 51.395648),
            .init(lon: 14.969201, lat: 51.398255),
            .init(lon: 14.958703, lat: 51.431343),
            .init(lon: 14.974049, lat: 51.442118),
            .init(lon: 14.948817, lat: 51.471480),
            .init(lon: 14.921934, lat: 51.482440),
            .init(lon: 14.852118, lat: 51.489390),
            .init(lon: 14.796295, lat: 51.517802),
            .init(lon: 14.728981, lat: 51.531543),
            .init(lon: 14.729357, lat: 51.549948),
            .init(lon: 14.711334, lat: 51.562742),
            .init(lon: 14.765120, lat: 51.607470),
            .init(lon: 14.753340, lat: 51.627873),
            .init(lon: 14.757747, lat: 51.661346),
            .init(lon: 14.736252, lat: 51.688574),
            .init(lon: 14.668169, lat: 51.725857),
            .init(lon: 14.645475, lat: 51.795528),
            .init(lon: 14.607186, lat: 51.803793),
            .init(lon: 14.590180, lat: 51.821173),
            .init(lon: 14.590402, lat: 51.838457),
            .init(lon: 14.612482, lat: 51.845501),
            .init(lon: 14.611105, lat: 51.857131),
            .init(lon: 14.694184, lat: 51.901895),
            .init(lon: 14.721287, lat: 51.951315),
            .init(lon: 14.704855, lat: 51.976008),
            .init(lon: 14.721659, lat: 51.994475),
            .init(lon: 14.714029, lat: 52.003683),
            .init(lon: 14.748422, lat: 52.031928),
            .init(lon: 14.745449, lat: 52.054332),
            .init(lon: 14.759094, lat: 52.065383),
            .init(lon: 14.681812, lat: 52.115640),
            .init(lon: 14.680016, lat: 52.143383),
            .init(lon: 14.705567, lat: 52.168914),
            .init(lon: 14.685814, lat: 52.193906),
            .init(lon: 14.708392, lat: 52.211672),
            .init(lon: 14.715550, lat: 52.236128),
            .init(lon: 14.689475, lat: 52.256758),
            .init(lon: 14.598680, lat: 52.272326),
            .init(lon: 14.575288, lat: 52.289048),
            .init(lon: 14.584829, lat: 52.306347),
            .init(lon: 14.561440, lat: 52.327806),
            .init(lon: 14.551473, lat: 52.375667),
            .init(lon: 14.534376, lat: 52.395000),
            .init(lon: 14.548115, lat: 52.432337),
            .init(lon: 14.578825, lat: 52.441569),
            .init(lon: 14.633926, lat: 52.491484),
            .init(lon: 14.603838, lat: 52.531031),
            .init(lon: 14.639014, lat: 52.573317),
            .init(lon: 14.596211, lat: 52.610643),
            .init(lon: 14.465103, lat: 52.661322),
            .init(lon: 14.351042, lat: 52.751510),
            .init(lon: 14.278807, lat: 52.774459),
            .init(lon: 14.217490, lat: 52.816868),
            .init(lon: 14.140493, lat: 52.824424),
            .init(lon: 14.122944, lat: 52.837330),
            .init(lon: 14.161611, lat: 52.888124),
            .init(lon: 14.142642, lat: 52.933161),
            .init(lon: 14.143667, lat: 52.961357),
            .init(lon: 14.258960, lat: 53.002981),
            .init(lon: 14.348569, lat: 53.054717),
            .init(lon: 14.387275, lat: 53.142392),
            .init(lon: 14.366258, lat: 53.171988),
            .init(lon: 14.377268, lat: 53.201752),
            .init(lon: 14.405856, lat: 53.210729),
            .init(lon: 14.450565, lat: 53.262252),
            .init(lon: 14.445247, lat: 53.274435),
            .init(lon: 14.421204, lat: 53.276136),
            .init(lon: 14.406803, lat: 53.308715),
            .init(lon: 14.415448, lat: 53.324368),
            .init(lon: 14.405502, lat: 53.347080),
            .init(lon: 14.390290, lat: 53.353748),
            .init(lon: 14.394844, lat: 53.375720),
            .init(lon: 14.373328, lat: 53.408950),
            .init(lon: 14.371274, lat: 53.456440),
            .init(lon: 14.358053, lat: 53.457328),
            .init(lon: 14.350655, lat: 53.496004),
            .init(lon: 14.326937, lat: 53.503824),
            .init(lon: 14.305748, lat: 53.543567),
            .init(lon: 14.316945, lat: 53.618063),
            .init(lon: 14.283898, lat: 53.634446),
            .init(lon: 14.284792, lat: 53.658692),
            .init(lon: 14.270661, lat: 53.666677),
            .init(lon: 14.283700, lat: 53.682585),
            .init(lon: 14.266811, lat: 53.698700),
            .init(lon: 14.266956, lat: 53.753489),
            .init(lon: 14.283597, lat: 53.772297),
            .init(lon: 14.212419, lat: 53.867283),
            .init(lon: 14.205772, lat: 53.910552),
            .init(lon: 14.185331, lat: 53.911962),
            .init(lon: 14.226098, lat: 53.927731),
            .init(lon: 14.242208, lat: 53.987728),
            .init(lon: 14.168019, lat: 54.238800),
            .init(lon: 14.069639, lat: 54.277642),
            .init(lon: 14.078292, lat: 54.441131),
            .init(lon: 14.022697, lat: 54.607669),
            .init(lon: 13.997564, lat: 54.648962),
            .init(lon: 13.908579, lat: 54.719507),
            .init(lon: 13.649826, lat: 54.838962),
            .init(lon: 13.545612, lat: 54.873272),
            .init(lon: 13.427221, lat: 54.884966),
            .init(lon: 13.156631, lat: 54.858021),
            .init(lon: 12.971575, lat: 54.785777),
            .init(lon: 12.748816, lat: 54.744020),
            .init(lon: 12.322150, lat: 54.577905),
            .init(lon: 12.292150, lat: 54.518182),
            .init(lon: 12.300206, lat: 54.511793),
            .init(lon: 12.258539, lat: 54.451236),
            .init(lon: 12.165206, lat: 54.385401),
            .init(lon: 11.951596, lat: 54.333733),
            .init(lon: 11.644374, lat: 54.330761),
            .init(lon: 11.538263, lat: 54.407623),
            .init(lon: 11.321875, lat: 54.512903),
            .init(lon: 11.311042, lat: 54.529570),
            .init(lon: 11.141320, lat: 54.577071),
            .init(lon: 10.819932, lat: 54.547348),
            .init(lon: 10.754654, lat: 54.514292),
            .init(lon: 10.651667, lat: 54.510167),
            .init(lon: 10.338822, lat: 54.593182),
            .init(lon: 10.169379, lat: 54.738185),
            .init(lon: 10.051551, lat: 54.766084),
            .init(lon: 9.894307, lat: 54.841796),
            .init(lon: 9.739942, lat: 54.823310),
            .init(lon: 9.604632, lat: 54.854517),
            .init(lon: 9.628013, lat: 54.879789),
            .init(lon: 9.592715, lat: 54.886852),
            .init(lon: 9.497759, lat: 54.841226),
            .init(lon: 9.435137, lat: 54.827050),
            .init(lon: 9.411190, lat: 54.842160),
            .init(lon: 9.382835, lat: 54.839188),
            .init(lon: 9.343714, lat: 54.800247),
            .init(lon: 9.293453, lat: 54.808931),
            .init(lon: 9.294939, lat: 54.801675),
            .init(lon: 9.250081, lat: 54.809638),
            .init(lon: 9.235845, lat: 54.831106),
            .init(lon: 9.240340, lat: 54.849949),
            .init(lon: 9.142993, lat: 54.873025),
            .init(lon: 9.047808, lat: 54.872022),
            .init(lon: 8.948075, lat: 54.902538),
            .init(lon: 8.859834, lat: 54.896760),
            .init(lon: 8.823994, lat: 54.906817),
            .init(lon: 8.776991, lat: 54.892645),
            .init(lon: 8.727911, lat: 54.892750),
            .init(lon: 8.681044, lat: 54.910407),
            .init(lon: 8.555431, lat: 54.920839),
            .init(lon: 8.557248, lat: 54.992817),
            .init(lon: 8.501565, lat: 55.000013),
            .init(lon: 8.472164, lat: 55.025338),
            .init(lon: 8.472381, lat: 55.054718),
            .init(lon: 8.395479, lat: 55.069277),
            .init(lon: 8.346845, lat: 55.065290),
            .init(lon: 8.318650, lat: 55.085010),
            .init(lon: 8.290037, lat: 55.074733),
            .init(lon: 8.290037, lat: 55.064762),
            .init(lon: 8.044381, lat: 55.099161),
            .init(lon: 7.949798, lat: 54.930080),
            .init(lon: 7.932493, lat: 54.734937),
            .init(lon: 7.964576, lat: 54.601573),
            .init(lon: 8.161409, lat: 54.333317),
            .init(lon: 8.028992, lat: 54.381707),
            .init(lon: 7.845938, lat: 54.393735),
            .init(lon: 7.706216, lat: 54.372040),
            .init(lon: 7.584883, lat: 54.310900),
            .init(lon: 7.527606, lat: 54.233454),
            .init(lon: 7.521439, lat: 54.186453),
            .init(lon: 7.534245, lat: 54.139924),
            .init(lon: 7.565189, lat: 54.096423),
            .init(lon: 7.621133, lat: 54.048034),
            .init(lon: 7.728049, lat: 53.994143),
            .init(lon: 7.532967, lat: 53.960393),
            .init(lon: 7.380357, lat: 53.951115),
            .init(lon: 7.261413, lat: 53.926420),
            .init(lon: 7.112386, lat: 53.919392),
            .init(lon: 6.960164, lat: 53.884780),
            .init(lon: 6.726860, lat: 53.863391),
            .init(lon: 6.592027, lat: 53.816334),
            .init(lon: 6.458250, lat: 53.789806),
            .init(lon: 6.345914, lat: 53.724536),
            .init(lon: 6.412611, lat: 53.604278),
            .init(lon: 6.551329, lat: 53.582553),
            .init(lon: 6.614035, lat: 53.553683),
            .init(lon: 6.628601, lat: 53.530580),
            .init(lon: 6.656768, lat: 53.527829),
            .init(lon: 6.687828, lat: 53.503879),
            .init(lon: 6.683656, lat: 53.496665),
            .init(lon: 6.882486, lat: 53.447267),
            .init(lon: 6.893524, lat: 53.436332),
            .init(lon: 6.882858, lat: 53.418936),
            .init(lon: 6.898203, lat: 53.361648),
            .init(lon: 6.926819, lat: 53.338860),
            .init(lon: 7.052267, lat: 53.306748),
            .init(lon: 7.191711, lat: 53.315055),
            .init(lon: 7.217025, lat: 53.214767),
            .init(lon: 7.208043, lat: 53.188477),
            .init(lon: 7.227499, lat: 53.180279),
            .init(lon: 7.203655, lat: 53.176564),
            .init(lon: 7.178902, lat: 53.138286),
            .init(lon: 7.182899, lat: 53.121765),
            .init(lon: 7.202794, lat: 53.113411),
            .init(lon: 7.199219, lat: 53.081386),
            .init(lon: 7.217445, lat: 53.007037),
            .init(lon: 7.181516, lat: 52.941584),
            .init(lon: 7.087258, lat: 52.849887),
            .init(lon: 7.092740, lat: 52.838196),
            .init(lon: 7.071551, lat: 52.810421),
            .init(lon: 7.055729, lat: 52.643420),
            .init(lon: 7.039570, lat: 52.632706),
            .init(lon: 6.975985, lat: 52.646255),
            .init(lon: 6.919320, lat: 52.639837),
            .init(lon: 6.873078, lat: 52.653268),
            .init(lon: 6.752598, lat: 52.648111),
            .init(lon: 6.710033, lat: 52.627493),
            .init(lon: 6.727289, lat: 52.614928),
            .init(lon: 6.718772, lat: 52.588636),
            .init(lon: 6.766692, lat: 52.561637),
            .init(lon: 6.725973, lat: 52.563255),
            .init(lon: 6.716264, lat: 52.548525),
            .init(lon: 6.680880, lat: 52.553317),
            .init(lon: 6.705332, lat: 52.521008),
            .init(lon: 6.697524, lat: 52.486323),
            .init(lon: 6.752734, lat: 52.464111),
            .init(lon: 6.854298, lat: 52.459706),
            .init(lon: 6.852542, lat: 52.449914),
            .init(lon: 6.941658, lat: 52.435426),
            .init(lon: 6.987623, lat: 52.469767),
            .init(lon: 7.010782, lat: 52.429137),
            .init(lon: 7.036074, lat: 52.402663),
            .init(lon: 7.058728, lat: 52.399410),
            .init(lon: 7.072153, lat: 52.373611),
            .init(lon: 7.072255, lat: 52.351879),
            .init(lon: 7.026454, lat: 52.291968),
            .init(lon: 7.028584, lat: 52.273627),
            .init(lon: 7.065792, lat: 52.241233),
            .init(lon: 7.061284, lat: 52.234711),
            .init(lon: 6.985315, lat: 52.225347),
            .init(lon: 6.951245, lat: 52.181058),
            .init(lon: 6.908061, lat: 52.175959),
            .init(lon: 6.855474, lat: 52.120462),
            .init(lon: 6.760572, lat: 52.118780),
            .init(lon: 6.747612, lat: 52.081925),
            .init(lon: 6.694663, lat: 52.069800),
            .init(lon: 6.687854, lat: 52.039855),
            .init(lon: 6.752977, lat: 52.028406),
            .init(lon: 6.826607, lat: 51.993527),
            .init(lon: 6.828529, lat: 51.964105),
            .init(lon: 6.798873, lat: 51.958744),
            .init(lon: 6.788945, lat: 51.929657),
            .init(lon: 6.721970, lat: 51.896063),
            .init(lon: 6.683994, lat: 51.917577),
            .init(lon: 6.544151, lat: 51.884610),
            .init(lon: 6.472508, lat: 51.853823),
            .init(lon: 6.390566, lat: 51.873968),
            .init(lon: 6.387984, lat: 51.861910),
            .init(lon: 6.408953, lat: 51.853346),
            .init(lon: 6.407206, lat: 51.828020),
            .init(lon: 6.367960, lat: 51.833400),
            .init(lon: 6.347207, lat: 51.850681),
            .init(lon: 6.306203, lat: 51.849078),
            .init(lon: 6.299006, lat: 51.867826),
            .init(lon: 6.279730, lat: 51.874115),
            .init(lon: 6.210177, lat: 51.869021),
            .init(lon: 6.183549, lat: 51.882531),
            .init(lon: 6.191085, lat: 51.891657),
            .init(lon: 6.156225, lat: 51.905245),
            .init(lon: 6.103448, lat: 51.892474),
            .init(lon: 6.137127, lat: 51.885803),
            .init(lon: 6.144539, lat: 51.869745),
            .init(lon: 6.167000, lat: 51.861622),
            .init(lon: 6.166560, lat: 51.840722),
            .init(lon: 6.101098, lat: 51.849011),
            .init(lon: 6.063486, lat: 51.865451),
            .init(lon: 6.035671, lat: 51.842638),
            .init(lon: 5.994426, lat: 51.830915),
            .init(lon: 5.962978, lat: 51.836914),
            .init(lon: 5.945479, lat: 51.824266),
            .init(lon: 5.958151, lat: 51.816931),
            .init(lon: 5.947978, lat: 51.811371),
            .init(lon: 5.979065, lat: 51.797651),
            .init(lon: 5.974548, lat: 51.785062),
            .init(lon: 5.990227, lat: 51.783401),
            .init(lon: 5.982360, lat: 51.773697),
            .init(lon: 5.992067, lat: 51.770246),
            .init(lon: 5.951988, lat: 51.748949),
            .init(lon: 5.955155, lat: 51.738118),
            .init(lon: 5.994197, lat: 51.738309),
            .init(lon: 6.044939, lat: 51.716913),
            .init(lon: 6.026054, lat: 51.708688),
            .init(lon: 6.032349, lat: 51.674056),
            .init(lon: 6.118088, lat: 51.655973),
            .init(lon: 6.091424, lat: 51.605849),
            .init(lon: 6.157032, lat: 51.566575),
            .init(lon: 6.212024, lat: 51.513391),
            .init(lon: 6.223676, lat: 51.468715),
            .init(lon: 6.205257, lat: 51.399520),
            .init(lon: 6.226668, lat: 51.400268),
            .init(lon: 6.214425, lat: 51.389634),
            .init(lon: 6.226387, lat: 51.360336),
            .init(lon: 6.194235, lat: 51.334878),
            .init(lon: 6.168557, lat: 51.332989),
            .init(lon: 6.124499, lat: 51.274728),
            .init(lon: 6.072653, lat: 51.242556),
            .init(lon: 6.086022, lat: 51.222667),
            .init(lon: 6.067986, lat: 51.220548),
            .init(lon: 6.082190, lat: 51.171633),
            .init(lon: 6.165170, lat: 51.194414),
            .init(lon: 6.180724, lat: 51.186358),
            .init(lon: 6.138802, lat: 51.173339),
            .init(lon: 6.175422, lat: 51.158464),
            .init(lon: 6.091996, lat: 51.135048),
            .init(lon: 6.036692, lat: 51.096594),
            .init(lon: 5.997794, lat: 51.084246),
            .init(lon: 5.957778, lat: 51.034726),
            .init(lon: 5.938129, lat: 51.035117),
            .init(lon: 5.913208, lat: 51.066883),
            .init(lon: 5.867087, lat: 51.046676),
            .init(lon: 5.878914, lat: 51.017837),
            .init(lon: 5.905518, lat: 51.002172),
            .init(lon: 5.897086, lat: 50.974865),
            .init(lon: 5.955185, lat: 50.988417),
            .init(lon: 5.967576, lat: 50.979396),
            .init(lon: 6.026512, lat: 50.983272),
            .init(lon: 6.005198, lat: 50.956777),
            .init(lon: 6.016853, lat: 50.952643),
            .init(lon: 6.018202, lat: 50.934701),
            .init(lon: 6.093989, lat: 50.920946),
            .init(lon: 6.075182, lat: 50.892953),
            .init(lon: 6.088102, lat: 50.872427),
            .init(lon: 6.074171, lat: 50.846538),
            .init(lon: 6.055437, lat: 50.857245),
            .init(lon: 6.018946, lat: 50.846256),
            .init(lon: 6.025029, lat: 50.814132),
            .init(lon: 6.003629, lat: 50.801462),
            .init(lon: 5.984890, lat: 50.810426),
            .init(lon: 5.974873, lat: 50.798043),
            .init(lon: 6.027662, lat: 50.774165),
            .init(lon: 6.018361, lat: 50.763356),
            .init(lon: 6.040442, lat: 50.745503),
            .init(lon: 6.039437, lat: 50.718383),
            .init(lon: 6.044465, lat: 50.728433),
            .init(lon: 6.114696, lat: 50.722276),
            .init(lon: 6.165833, lat: 50.662137),
            .init(lon: 6.194751, lat: 50.663044),
            .init(lon: 6.186761, lat: 50.640606),
            .init(lon: 6.230376, lat: 50.649289),
            .init(lon: 6.266378, lat: 50.642076),
            .init(lon: 6.268733, lat: 50.618700),
            .init(lon: 6.247953, lat: 50.603918),
            .init(lon: 6.236013, lat: 50.566158),
            .init(lon: 6.210328, lat: 50.553931),
            .init(lon: 6.197512, lat: 50.529576),
            .init(lon: 6.226618, lat: 50.494350),
            .init(lon: 6.269664, lat: 50.504545),
            .init(lon: 6.351289, lat: 50.488288),
            .init(lon: 6.337464, lat: 50.474681),
            .init(lon: 6.340405, lat: 50.462265),
            .init(lon: 6.375137, lat: 50.450352),
            .init(lon: 6.369943, lat: 50.408871),
            .init(lon: 6.342940, lat: 50.380249),
            .init(lon: 6.399460, lat: 50.344949),
            .init(lon: 6.405530, lat: 50.323334),
            .init(lon: 6.361511, lat: 50.314884),
            .init(lon: 6.363375, lat: 50.305187),
            .init(lon: 6.333056, lat: 50.323578),
            .init(lon: 6.306470, lat: 50.320190),
            .init(lon: 6.278515, lat: 50.266452),
            .init(lon: 6.215805, lat: 50.256953),
            .init(lon: 6.197104, lat: 50.237856),
            .init(lon: 6.175596, lat: 50.235283),
            .init(lon: 6.166504, lat: 50.219757),
            .init(lon: 6.188852, lat: 50.205332),
            .init(lon: 6.192496, lat: 50.182068),
            .init(lon: 6.139677, lat: 50.169082),
            .init(lon: 6.147661, lat: 50.160545),
            .init(lon: 6.132017, lat: 50.153507),
            .init(lon: 6.154502, lat: 50.141639),
            .init(lon: 6.129351, lat: 50.121335),
            .init(lon: 6.132985, lat: 50.093360),
            .init(lon: 6.119991, lat: 50.092010),
            .init(lon: 6.115766, lat: 50.074591),
            .init(lon: 6.129215, lat: 50.073376),
            .init(lon: 6.112259, lat: 50.059747),
            .init(lon: 6.123985, lat: 50.059693),
            .init(lon: 6.129659, lat: 50.029799),
            .init(lon: 6.145893, lat: 50.022628),
            .init(lon: 6.129548, lat: 50.018490),
            .init(lon: 6.149582, lat: 50.008930),
            .init(lon: 6.137764, lat: 49.998302),
            .init(lon: 6.172470, lat: 49.984619),
            .init(lon: 6.164763, lat: 49.970515),
            .init(lon: 6.177676, lat: 49.953518),
            .init(lon: 6.190427, lat: 49.968859),
            .init(lon: 6.197658, lat: 49.948167),
            .init(lon: 6.223909, lat: 49.950081),
            .init(lon: 6.217785, lat: 49.923706),
            .init(lon: 6.231516, lat: 49.918602),
            .init(lon: 6.233593, lat: 49.900141),
            .init(lon: 6.296280, lat: 49.866445),
            .init(lon: 6.311735, lat: 49.869129),
            .init(lon: 6.321422, lat: 49.838453),
            .init(lon: 6.363943, lat: 49.850716),
            .init(lon: 6.429887, lat: 49.810479),
            .init(lon: 6.470986, lat: 49.822323),
            .init(lon: 6.510663, lat: 49.801480),
            .init(lon: 6.520870, lat: 49.813098),
            .init(lon: 6.530898, lat: 49.806007),
            .init(lon: 6.505610, lat: 49.789637),
            .init(lon: 6.516900, lat: 49.782577),
            .init(lon: 6.509574, lat: 49.773798),
            .init(lon: 6.518167, lat: 49.762352),
            .init(lon: 6.500320, lat: 49.752381),
            .init(lon: 6.501582, lat: 49.732982),
            .init(lon: 6.517149, lat: 49.723468),
            .init(lon: 6.495476, lat: 49.726083),
            .init(lon: 6.506263, lat: 49.713500),
            .init(lon: 6.427345, lat: 49.666981),
            .init(lon: 6.439869, lat: 49.656141),
            .init(lon: 6.421130, lat: 49.620841),
            .init(lon: 6.375277, lat: 49.592554),
            .init(lon: 6.381282, lat: 49.577286),
            .init(lon: 6.356949, lat: 49.573272),
            .init(lon: 6.381761, lat: 49.556546),
            .init(lon: 6.355831, lat: 49.530734),
            .init(lon: 6.366679, lat: 49.469599),
            .init(lon: 6.394181, lat: 49.464176),
            .init(lon: 6.428027, lat: 49.476948),
            .init(lon: 6.551979, lat: 49.424773),
            .init(lon: 6.557332, lat: 49.419394),
            .init(lon: 6.538695, lat: 49.412394),
            .init(lon: 6.540734, lat: 49.401102),
            .init(lon: 6.586700, lat: 49.385182),
            .init(lon: 6.583228, lat: 49.368516),
            .init(lon: 6.602300, lat: 49.367111),
            .init(lon: 6.588334, lat: 49.349602),
            .init(lon: 6.574053, lat: 49.358752),
            .init(lon: 6.565773, lat: 49.347831),
            .init(lon: 6.591339, lat: 49.335905),
            .init(lon: 6.589095, lat: 49.322126),
            .init(lon: 6.615379, lat: 49.301626),
            .init(lon: 6.670322, lat: 49.280265),
            .init(lon: 6.661583, lat: 49.258049),
            .init(lon: 6.690066, lat: 49.249654),
            .init(lon: 6.695772, lat: 49.215231),
            .init(lon: 6.723178, lat: 49.219011),
            .init(lon: 6.731513, lat: 49.205961),
            .init(lon: 6.711289, lat: 49.188365),
            .init(lon: 6.738557, lat: 49.163672),
            .init(lon: 6.782584, lat: 49.168204),
            .init(lon: 6.834175, lat: 49.151282),
            .init(lon: 6.847382, lat: 49.157171),
            .init(lon: 6.844514, lat: 49.173038),
            .init(lon: 6.861943, lat: 49.178924),
            .init(lon: 6.837988, lat: 49.213451),
            .init(lon: 6.859403, lat: 49.222753),
            .init(lon: 6.892611, lat: 49.208827),
            .init(lon: 6.938230, lat: 49.222448),
            .init(lon: 6.959595, lat: 49.203118),
            .init(lon: 6.975334, lat: 49.209379),
            .init(lon: 7.010913, lat: 49.187950),
            .init(lon: 7.035031, lat: 49.191436),
            .init(lon: 7.027756, lat: 49.170283),
            .init(lon: 7.052035, lat: 49.112946),
            .init(lon: 7.089543, lat: 49.130343),
            .init(lon: 7.080359, lat: 49.148962),
            .init(lon: 7.102006, lat: 49.155764),
            .init(lon: 7.113255, lat: 49.151938),
            .init(lon: 7.103810, lat: 49.138492),
            .init(lon: 7.126155, lat: 49.141957),
            .init(lon: 7.157451, lat: 49.120827),
            .init(lon: 7.184372, lat: 49.131460),
            .init(lon: 7.198322, lat: 49.115208),
            .init(lon: 7.245280, lat: 49.130055),
            .init(lon: 7.293556, lat: 49.114989),
            .init(lon: 7.325787, lat: 49.143324),
            .init(lon: 7.362681, lat: 49.143261),
            .init(lon: 7.365325, lat: 49.172041),
            .init(lon: 7.445769, lat: 49.184303),
            .init(lon: 7.434638, lat: 49.164733),
            .init(lon: 7.493976, lat: 49.169406),
            .init(lon: 7.505980, lat: 49.150973),
            .init(lon: 7.489447, lat: 49.136500),
            .init(lon: 7.515523, lat: 49.121177),
            .init(lon: 7.528757, lat: 49.097051),
            .init(lon: 7.563269, lat: 49.080279),
            .init(lon: 7.629522, lat: 49.073569),
            .init(lon: 7.631560, lat: 49.054915),
            .init(lon: 7.674826, lat: 49.044937),
            .init(lon: 7.697649, lat: 49.049753),
            .init(lon: 7.695953, lat: 49.057785),
            .init(lon: 7.731863, lat: 49.055618),
            .init(lon: 7.732357, lat: 49.044006),
            .init(lon: 7.757288, lat: 49.045315),
            .init(lon: 7.794434, lat: 49.065751),
            .init(lon: 7.867340, lat: 49.032962),
            .init(lon: 7.889361, lat: 49.049237),
            .init(lon: 7.916946, lat: 49.040881),
            .init(lon: 7.933976, lat: 49.057923),
            .init(lon: 7.966635, lat: 49.041874),
            .init(lon: 7.975036, lat: 49.026564),
            .init(lon: 8.049552, lat: 49.014457),
            .init(lon: 8.088006, lat: 48.989700),
            .init(lon: 8.193885, lat: 48.977226),
            .init(lon: 8.199409, lat: 48.966892),
            .init(lon: 8.222879, lat: 48.975883),
            .init(lon: 8.232578, lat: 48.966447),
            .init(lon: 8.197281, lat: 48.957243),
            .init(lon: 8.147716, lat: 48.903524),
            .init(lon: 8.091451, lat: 48.805665),
            .init(lon: 8.067881, lat: 48.790510),
            .init(lon: 8.030400, lat: 48.787254),
            .init(lon: 8.012666, lat: 48.760313),
            .init(lon: 7.972374, lat: 48.758173),
            .init(lon: 7.964360, lat: 48.722551),
            .init(lon: 7.890345, lat: 48.662857),
            .init(lon: 7.841739, lat: 48.643542),
            .init(lon: 7.802075, lat: 48.588581),
            .init(lon: 7.805626, lat: 48.514928),
            .init(lon: 7.767986, lat: 48.489241),
            .init(lon: 7.764302, lat: 48.454158),
            .init(lon: 7.732173, lat: 48.393687),
            .init(lon: 7.744167, lat: 48.326665),
            .init(lon: 7.693542, lat: 48.301636),
            .init(lon: 7.666537, lat: 48.221560),
            .init(lon: 7.601650, lat: 48.158952),
            .init(lon: 7.598650, lat: 48.135496),
            .init(lon: 7.577407, lat: 48.120199),
            .init(lon: 7.568901, lat: 48.034570),
            .init(lon: 7.610100, lat: 47.998893),
            .init(lon: 7.621897, lat: 47.972499),
            .init(lon: 7.583230, lat: 47.931193),
            .init(lon: 7.581181, lat: 47.897027),
            .init(lon: 7.556578, lat: 47.878036),
            .init(lon: 7.563058, lat: 47.842884),
            .init(lon: 7.529846, lat: 47.780101),
            .init(lon: 7.548412, lat: 47.731941),
            .init(lon: 7.511813, lat: 47.698538),
            .init(lon: 7.521800, lat: 47.663266),
            .init(lon: 7.565717, lat: 47.633385),
            .init(lon: 7.604882, lat: 47.577874),
            .init(lon: 7.645670, lat: 47.596955),
            .init(lon: 7.675171, lat: 47.591982),
            .init(lon: 7.693802, lat: 47.600775),
            .init(lon: 7.671750, lat: 47.587276),
            .init(lon: 7.685929, lat: 47.565615),
            .init(lon: 7.633953, lat: 47.561217),
            .init(lon: 7.679215, lat: 47.532792),
            .init(lon: 7.795663, lat: 47.557369),
            .init(lon: 7.823221, lat: 47.587995),
            .init(lon: 7.891998, lat: 47.587423),
            .init(lon: 7.910403, lat: 47.571781),
            .init(lon: 7.911605, lat: 47.551039),
            .init(lon: 7.944221, lat: 47.543878),
            .init(lon: 7.959837, lat: 47.558127),
            .init(lon: 8.020716, lat: 47.550405),
            .init(lon: 8.067203, lat: 47.564501),
            .init(lon: 8.090250, lat: 47.557829),
            .init(lon: 8.110141, lat: 47.582751),
            .init(lon: 8.164390, lat: 47.593980),
            .init(lon: 8.206310, lat: 47.621112),
            .init(lon: 8.226627, lat: 47.605026),
            .init(lon: 8.256912, lat: 47.615316),
            .init(lon: 8.291912, lat: 47.609158),
            .init(lon: 8.297588, lat: 47.589260),
            .init(lon: 8.329389, lat: 47.571017),
            .init(lon: 8.382783, lat: 47.565659),
            .init(lon: 8.397915, lat: 47.577216),
            .init(lon: 8.433564, lat: 47.566620),
            .init(lon: 8.494750, lat: 47.581033),
            .init(lon: 8.466869, lat: 47.584248),
            .init(lon: 8.456675, lat: 47.602327),
            .init(lon: 8.508285, lat: 47.617549),
            .init(lon: 8.517257, lat: 47.634250),
            .init(lon: 8.557884, lat: 47.624456),
            .init(lon: 8.574525, lat: 47.611966),
            .init(lon: 8.562208, lat: 47.600288),
            .init(lon: 8.582577, lat: 47.596138),
            .init(lon: 8.605005, lat: 47.613504),
            .init(lon: 8.596044, lat: 47.643279),
            .init(lon: 8.607705, lat: 47.652417),
            .init(lon: 8.614070, lat: 47.644705),
            .init(lon: 8.603451, lat: 47.638727),
            .init(lon: 8.617498, lat: 47.638120),
            .init(lon: 8.628930, lat: 47.651734),
            .init(lon: 8.606614, lat: 47.672147),
            .init(lon: 8.577673, lat: 47.661517),
            .init(lon: 8.559708, lat: 47.670236),
            .init(lon: 8.539932, lat: 47.665086),
            .init(lon: 8.541567, lat: 47.656881),
            .init(lon: 8.526898, lat: 47.660487),
            .init(lon: 8.531793, lat: 47.645748),
            .init(lon: 8.476423, lat: 47.650109),
            .init(lon: 8.472163, lat: 47.638593),
            .init(lon: 8.465955, lat: 47.657260),
            .init(lon: 8.412196, lat: 47.666342),
            .init(lon: 8.406338, lat: 47.676241),
            .init(lon: 8.420773, lat: 47.683882),
            .init(lon: 8.407960, lat: 47.701921),
            .init(lon: 8.454926, lat: 47.722462),
            .init(lon: 8.450760, lat: 47.740173),
            .init(lon: 8.484949, lat: 47.771385),
            .init(lon: 8.577318, lat: 47.781674),
            .init(lon: 8.561975, lat: 47.792606),
            .init(lon: 8.568028, lat: 47.808454),
            .init(lon: 8.575309, lat: 47.799592),
            .init(lon: 8.618602, lat: 47.798323),
            .init(lon: 8.619430, lat: 47.767668),
            .init(lon: 8.631653, lat: 47.758196),
            .init(lon: 8.652953, lat: 47.773403),
            .init(lon: 8.645749, lat: 47.790711),
            .init(lon: 8.656863, lat: 47.800441),
            .init(lon: 8.657393, lat: 47.791750),
            .init(lon: 8.681033, lat: 47.786603),
            .init(lon: 8.688708, lat: 47.758360),
            .init(lon: 8.714071, lat: 47.765400),
            .init(lon: 8.741136, lat: 47.751984),
            .init(lon: 8.711144, lat: 47.730148),
            .init(lon: 8.736292, lat: 47.716337),
            .init(lon: 8.728023, lat: 47.692764),
            .init(lon: 8.796034, lat: 47.675335),
            .init(lon: 8.797072, lat: 47.688443),
            .init(lon: 8.810095, lat: 47.693362),
            .init(lon: 8.769376, lat: 47.706854),
            .init(lon: 8.769753, lat: 47.718463),
            .init(lon: 8.806676, lat: 47.738293),
            .init(lon: 8.804797, lat: 47.724531),
            .init(lon: 8.826237, lat: 47.717873),
            .init(lon: 8.819036, lat: 47.712784),
            .init(lon: 8.872750, lat: 47.704071),
            .init(lon: 8.873386, lat: 47.693972),
            .init(lon: 8.851528, lat: 47.697636),
            .init(lon: 8.850531, lat: 47.681177),
            .init(lon: 8.894162, lat: 47.648255),
            .init(lon: 9.026502, lat: 47.686759),
            .init(lon: 9.150775, lat: 47.667647),
            .init(lon: 9.175971, lat: 47.653984),
            .init(lon: 9.256561, lat: 47.658708),
            .init(lon: 9.394714, lat: 47.620326),
            .init(lon: 9.495604, lat: 47.551455),
            .init(lon: 9.680360, lat: 47.523358),
            .init(lon: 9.736320, lat: 47.534568),
            .init(lon: 9.748065, lat: 47.570524),
            .init(lon: 9.777046, lat: 47.595449),
            .init(lon: 9.823814, lat: 47.587105),
            .init(lon: 9.825963, lat: 47.560421),
            .init(lon: 9.815755, lat: 47.547695),
            .init(lon: 9.874505, lat: 47.528537),
            .init(lon: 9.881247, lat: 47.548143),
            .init(lon: 9.921895, lat: 47.529636),
            .init(lon: 9.963700, lat: 47.534720),
            .init(lon: 9.958853, lat: 47.543171),
            .init(lon: 9.970711, lat: 47.545714),
            .init(lon: 9.965262, lat: 47.520893),
            .init(lon: 9.995695, lat: 47.502779),
            .init(lon: 9.987358, lat: 47.498465),
            .init(lon: 10.000764, lat: 47.482106),
            .init(lon: 10.044775, lat: 47.487622),
            .init(lon: 10.069991, lat: 47.455950),
            .init(lon: 10.091638, lat: 47.458928),
            .init(lon: 10.105586, lat: 47.428717),
            .init(lon: 10.069140, lat: 47.410176),
            .init(lon: 10.086240, lat: 47.399522),
            .init(lon: 10.099852, lat: 47.354762),
            .init(lon: 10.119335, lat: 47.375613),
            .init(lon: 10.165875, lat: 47.368875),
            .init(lon: 10.181849, lat: 47.392426),
            .init(lon: 10.236186, lat: 47.381921),
            .init(lon: 10.199509, lat: 47.326460),
            .init(lon: 10.215972, lat: 47.311064),
            .init(lon: 10.179611, lat: 47.296026),
            .init(lon: 10.174042, lat: 47.270248),
            .init(lon: 10.232366, lat: 47.270578),
            .init(lon: 10.330333, lat: 47.304815),
            .init(lon: 10.394730, lat: 47.375605),
            .init(lon: 10.436765, lat: 47.380363),
            .init(lon: 10.429215, lat: 47.391218),
            .init(lon: 10.437421, lat: 47.412688),
            .init(lon: 10.475946, lat: 47.432223),
            .init(lon: 10.467970, lat: 47.477110),
            .init(lon: 10.442596, lat: 47.484635),
            .init(lon: 10.431301, lat: 47.503763),
            .init(lon: 10.454440, lat: 47.555796),
        ],
        [
            .init(lon: 6.166035, lat: 50.661862),
            .init(lon: 6.183861, lat: 50.647942),
            .init(lon: 6.196162, lat: 50.658791),
            .init(lon: 6.166035, lat: 50.661862),
        ],
        [
            .init(lon: 6.166689, lat: 50.643620),
            .init(lon: 6.181800, lat: 50.623796),
            .init(lon: 6.194202, lat: 50.633896),
            .init(lon: 6.273811, lat: 50.629755),
            .init(lon: 6.264970, lat: 50.642391),
            .init(lon: 6.231604, lat: 50.648933),
            .init(lon: 6.220744, lat: 50.640281),
            .init(lon: 6.166689, lat: 50.643620),
        ],
        [
            .init(lon: 6.174068, lat: 50.556354),
            .init(lon: 6.178098, lat: 50.541520),
            .init(lon: 6.197437, lat: 50.536262),
            .init(lon: 6.235286, lat: 50.566103),
            .init(lon: 6.240574, lat: 50.587062),
            .init(lon: 6.225261, lat: 50.590459),
            .init(lon: 6.174068, lat: 50.556354),
        ],
        [
            .init(lon: 6.187164, lat: 50.526165),
            .init(lon: 6.187181, lat: 50.526093),
            .init(lon: 6.187397, lat: 50.525951),
            .init(lon: 6.187164, lat: 50.526165),
        ],
        [
            .init(lon: 6.246194, lat: 50.597369),
            .init(lon: 6.246510, lat: 50.597248),
            .init(lon: 6.246537, lat: 50.597275),
            .init(lon: 6.246194, lat: 50.597369),
        ],
        [
            .init(lon: 7.408664, lat: 54.006806),
            .init(lon: 7.549833, lat: 54.026800),
            .init(lon: 7.448465, lat: 54.137846),
            .init(lon: 7.408728, lat: 54.135700),
            .init(lon: 7.408664, lat: 54.006806),
        ],
        [
            .init(lon: 8.658591, lat: 47.691349),
            .init(lon: 8.717873, lat: 47.690690),
            .init(lon: 8.701270, lat: 47.715199),
            .init(lon: 8.664621, lat: 47.713382),
            .init(lon: 8.676299, lat: 47.697564),
            .init(lon: 8.658591, lat: 47.691349),
        ],
    ]

    static let karlsruheRegbez: [GeoLonLat] = [
        .init(lon: 7.949946, lat: 48.720910),
        .init(lon: 7.958799, lat: 48.728330),
        .init(lon: 7.958545, lat: 48.755250),
        .init(lon: 7.971347, lat: 48.763720),
        .init(lon: 8.007903, lat: 48.762990),
        .init(lon: 8.017443, lat: 48.770240),
        .init(lon: 8.020692, lat: 48.788790),
        .init(lon: 8.043024, lat: 48.795600),
        .init(lon: 8.064676, lat: 48.793790),
        .init(lon: 8.100241, lat: 48.823080),
        .init(lon: 8.130868, lat: 48.896900),
        .init(lon: 8.193647, lat: 48.960210),
        .init(lon: 8.226564, lat: 48.967070),
        .init(lon: 8.290483, lat: 49.004300),
        .init(lon: 8.308333, lat: 49.059070),
        .init(lon: 8.353387, lat: 49.102330),
        .init(lon: 8.362435, lat: 49.171750),
        .init(lon: 8.383821, lat: 49.213010),
        .init(lon: 8.381765, lat: 49.241210),
        .init(lon: 8.442378, lat: 49.281620),
        .init(lon: 8.479640, lat: 49.295040),
        .init(lon: 8.469629, lat: 49.307010),
        .init(lon: 8.444046, lat: 49.314260),
        .init(lon: 8.444046, lat: 49.331660),
        .init(lon: 8.489650, lat: 49.367160),
        .init(lon: 8.454613, lat: 49.376220),
        .init(lon: 8.462399, lat: 49.392870),
        .init(lon: 8.482977, lat: 49.402640),
        .init(lon: 8.500217, lat: 49.434300),
        .init(lon: 8.436817, lat: 49.446960),
        .init(lon: 8.435148, lat: 49.460690),
        .init(lon: 8.454613, lat: 49.469370),
        .init(lon: 8.405672, lat: 49.553510),
        .init(lon: 8.417351, lat: 49.589930),
        .init(lon: 8.473522, lat: 49.596780),
        .init(lon: 8.530805, lat: 49.556390),
        .init(lon: 8.546377, lat: 49.532940),
        .init(lon: 8.583083, lat: 49.526440),
        .init(lon: 8.608110, lat: 49.550980),
        .init(lon: 8.580302, lat: 49.611560),
        .init(lon: 8.618120, lat: 49.623090),
        .init(lon: 8.695425, lat: 49.631370),
        .init(lon: 8.708772, lat: 49.589930),
        .init(lon: 8.699318, lat: 49.571900),
        .init(lon: 8.732757, lat: 49.527880),
        .init(lon: 8.776359, lat: 49.524090),
        .init(lon: 8.825798, lat: 49.529890),
        .init(lon: 8.823738, lat: 49.511830),
        .init(lon: 8.902359, lat: 49.505590),
        .init(lon: 8.930511, lat: 49.479060),
        .init(lon: 8.948364, lat: 49.507380),
        .init(lon: 8.986129, lat: 49.512060),
        .init(lon: 9.031105, lat: 49.506480),
        .init(lon: 9.069934, lat: 49.538640),
        .init(lon: 9.069900, lat: 49.576440),
        .init(lon: 9.103889, lat: 49.582230),
        .init(lon: 9.236755, lat: 49.585120),
        .init(lon: 9.266624, lat: 49.636510),
        .init(lon: 9.300270, lat: 49.656960),
        .init(lon: 9.420376, lat: 49.666360),
        .init(lon: 9.477462, lat: 49.645710),
        .init(lon: 9.492172, lat: 49.647620),
        .init(lon: 9.501957, lat: 49.641190),
        .init(lon: 9.520480, lat: 49.646040),
        .init(lon: 9.528020, lat: 49.637750),
        .init(lon: 9.538627, lat: 49.642820),
        .init(lon: 9.552036, lat: 49.632420),
        .init(lon: 9.554613, lat: 49.621400),
        .init(lon: 9.540477, lat: 49.615160),
        .init(lon: 9.546415, lat: 49.599430),
        .init(lon: 9.511872, lat: 49.598480),
        .init(lon: 9.503965, lat: 49.586980),
        .init(lon: 9.525993, lat: 49.538870),
        .init(lon: 9.544080, lat: 49.535070),
        .init(lon: 9.548504, lat: 49.523830),
        .init(lon: 9.498351, lat: 49.497330),
        .init(lon: 9.495919, lat: 49.488570),
        .init(lon: 9.513965, lat: 49.482830),
        .init(lon: 9.519768, lat: 49.474310),
        .init(lon: 9.509110, lat: 49.454120),
        .init(lon: 9.517193, lat: 49.446540),
        .init(lon: 9.550281, lat: 49.452720),
        .init(lon: 9.590732, lat: 49.442690),
        .init(lon: 9.603346, lat: 49.432900),
        .init(lon: 9.605534, lat: 49.424090),
        .init(lon: 9.575791, lat: 49.414910),
        .init(lon: 9.581083, lat: 49.405720),
        .init(lon: 9.593202, lat: 49.403130),
        .init(lon: 9.597097, lat: 49.391580),
        .init(lon: 9.574543, lat: 49.374410),
        .init(lon: 9.531259, lat: 49.378950),
        .init(lon: 9.507554, lat: 49.372340),
        .init(lon: 9.473148, lat: 49.381960),
        .init(lon: 9.464501, lat: 49.392210),
        .init(lon: 9.448619, lat: 49.388570),
        .init(lon: 9.454313, lat: 49.374950),
        .init(lon: 9.445634, lat: 49.362290),
        .init(lon: 9.423507, lat: 49.355050),
        .init(lon: 9.399843, lat: 49.363030),
        .init(lon: 9.353843, lat: 49.363730),
        .init(lon: 9.329512, lat: 49.384660),
        .init(lon: 9.312317, lat: 49.374420),
        .init(lon: 9.317533, lat: 49.355420),
        .init(lon: 9.296609, lat: 49.345320),
        .init(lon: 9.289197, lat: 49.327520),
        .init(lon: 9.271646, lat: 49.327290),
        .init(lon: 9.264256, lat: 49.304630),
        .init(lon: 9.252735, lat: 49.295630),
        .init(lon: 9.240717, lat: 49.294800),
        .init(lon: 9.228954, lat: 49.307460),
        .init(lon: 9.219771, lat: 49.305010),
        .init(lon: 9.203658, lat: 49.321550),
        .init(lon: 9.164578, lat: 49.324430),
        .init(lon: 9.158322, lat: 49.296440),
        .init(lon: 9.147995, lat: 49.290050),
        .init(lon: 9.158261, lat: 49.283470),
        .init(lon: 9.151122, lat: 49.270940),
        .init(lon: 9.071258, lat: 49.275270),
        .init(lon: 9.029983, lat: 49.293310),
        .init(lon: 9.044179, lat: 49.284350),
        .init(lon: 9.044578, lat: 49.276230),
        .init(lon: 9.020668, lat: 49.262300),
        .init(lon: 9.022303, lat: 49.254200),
        .init(lon: 9.014282, lat: 49.252350),
        .init(lon: 9.005878, lat: 49.258980),
        .init(lon: 9.004115, lat: 49.253180),
        .init(lon: 9.013626, lat: 49.249580),
        .init(lon: 9.007981, lat: 49.240030),
        .init(lon: 8.966543, lat: 49.224370),
        .init(lon: 8.958534, lat: 49.210390),
        .init(lon: 8.891213, lat: 49.199440),
        .init(lon: 8.898643, lat: 49.180010),
        .init(lon: 8.873883, lat: 49.171930),
        .init(lon: 8.860036, lat: 49.172330),
        .init(lon: 8.828626, lat: 49.187170),
        .init(lon: 8.819316, lat: 49.161400),
        .init(lon: 8.832101, lat: 49.164720),
        .init(lon: 8.845157, lat: 49.150440),
        .init(lon: 8.840152, lat: 49.137810),
        .init(lon: 8.830334, lat: 49.133820),
        .init(lon: 8.857569, lat: 49.128880),
        .init(lon: 8.872371, lat: 49.134760),
        .init(lon: 8.893789, lat: 49.113660),
        .init(lon: 8.896010, lat: 49.083270),
        .init(lon: 8.877837, lat: 49.075960),
        .init(lon: 8.883510, lat: 49.055920),
        .init(lon: 8.875852, lat: 49.040000),
        .init(lon: 8.905534, lat: 49.024530),
        .init(lon: 8.935108, lat: 48.995070),
        .init(lon: 8.928605, lat: 48.978450),
        .init(lon: 8.952521, lat: 48.953070),
        .init(lon: 8.942971, lat: 48.935350),
        .init(lon: 8.906205, lat: 48.938450),
        .init(lon: 8.908931, lat: 48.924370),
        .init(lon: 8.929132, lat: 48.920640),
        .init(lon: 8.924478, lat: 48.911570),
        .init(lon: 8.913378, lat: 48.909050),
        .init(lon: 8.932030, lat: 48.865410),
        .init(lon: 8.904444, lat: 48.858380),
        .init(lon: 8.896825, lat: 48.844580),
        .init(lon: 8.879710, lat: 48.836950),
        .init(lon: 8.902238, lat: 48.820530),
        .init(lon: 8.902445, lat: 48.814070),
        .init(lon: 8.894393, lat: 48.810160),
        .init(lon: 8.902343, lat: 48.798260),
        .init(lon: 8.887139, lat: 48.799280),
        .init(lon: 8.868035, lat: 48.789210),
        .init(lon: 8.833691, lat: 48.794940),
        .init(lon: 8.803657, lat: 48.774080),
        .init(lon: 8.836843, lat: 48.756850),
        .init(lon: 8.833238, lat: 48.739300),
        .init(lon: 8.856062, lat: 48.737460),
        .init(lon: 8.880643, lat: 48.726380),
        .init(lon: 8.878652, lat: 48.719810),
        .init(lon: 8.868289, lat: 48.717490),
        .init(lon: 8.861791, lat: 48.706320),
        .init(lon: 8.865480, lat: 48.695500),
        .init(lon: 8.852812, lat: 48.681980),
        .init(lon: 8.838170, lat: 48.680000),
        .init(lon: 8.820495, lat: 48.661930),
        .init(lon: 8.802352, lat: 48.656840),
        .init(lon: 8.804470, lat: 48.642750),
        .init(lon: 8.794090, lat: 48.628820),
        .init(lon: 8.804178, lat: 48.611570),
        .init(lon: 8.797580, lat: 48.606550),
        .init(lon: 8.796975, lat: 48.591990),
        .init(lon: 8.750816, lat: 48.597380),
        .init(lon: 8.757661, lat: 48.586610),
        .init(lon: 8.760516, lat: 48.558780),
        .init(lon: 8.776181, lat: 48.550250),
        .init(lon: 8.773073, lat: 48.542730),
        .init(lon: 8.760697, lat: 48.541700),
        .init(lon: 8.766871, lat: 48.534400),
        .init(lon: 8.762716, lat: 48.528190),
        .init(lon: 8.774515, lat: 48.520220),
        .init(lon: 8.765267, lat: 48.506200),
        .init(lon: 8.777797, lat: 48.490120),
        .init(lon: 8.796862, lat: 48.487430),
        .init(lon: 8.832815, lat: 48.461990),
        .init(lon: 8.792269, lat: 48.448770),
        .init(lon: 8.773369, lat: 48.435260),
        .init(lon: 8.769089, lat: 48.428840),
        .init(lon: 8.781063, lat: 48.421500),
        .init(lon: 8.754780, lat: 48.389120),
        .init(lon: 8.760481, lat: 48.380650),
        .init(lon: 8.715672, lat: 48.376170),
        .init(lon: 8.688284, lat: 48.384210),
        .init(lon: 8.674785, lat: 48.397180),
        .init(lon: 8.654505, lat: 48.391530),
        .init(lon: 8.638658, lat: 48.398840),
        .init(lon: 8.605237, lat: 48.393300),
        .init(lon: 8.594693, lat: 48.405660),
        .init(lon: 8.561996, lat: 48.396450),
        .init(lon: 8.546948, lat: 48.401500),
        .init(lon: 8.525137, lat: 48.398240),
        .init(lon: 8.522172, lat: 48.384900),
        .init(lon: 8.490646, lat: 48.379160),
        .init(lon: 8.489484, lat: 48.369650),
        .init(lon: 8.503525, lat: 48.357100),
        .init(lon: 8.481430, lat: 48.345530),
        .init(lon: 8.487505, lat: 48.344500),
        .init(lon: 8.489803, lat: 48.335490),
        .init(lon: 8.505172, lat: 48.332240),
        .init(lon: 8.496397, lat: 48.312230),
        .init(lon: 8.461699, lat: 48.310470),
        .init(lon: 8.446183, lat: 48.297920),
        .init(lon: 8.431077, lat: 48.309640),
        .init(lon: 8.428417, lat: 48.320800),
        .init(lon: 8.395188, lat: 48.319900),
        .init(lon: 8.357714, lat: 48.336330),
        .init(lon: 8.356141, lat: 48.376480),
        .init(lon: 8.344485, lat: 48.381530),
        .init(lon: 8.330768, lat: 48.383950),
        .init(lon: 8.324358, lat: 48.378570),
        .init(lon: 8.318249, lat: 48.367640),
        .init(lon: 8.322834, lat: 48.358190),
        .init(lon: 8.303762, lat: 48.339740),
        .init(lon: 8.283386, lat: 48.357550),
        .init(lon: 8.253489, lat: 48.359280),
        .init(lon: 8.248700, lat: 48.370710),
        .init(lon: 8.256177, lat: 48.377140),
        .init(lon: 8.230022, lat: 48.402050),
        .init(lon: 8.255370, lat: 48.422670),
        .init(lon: 8.250964, lat: 48.434270),
        .init(lon: 8.261101, lat: 48.437230),
        .init(lon: 8.265329, lat: 48.448780),
        .init(lon: 8.261009, lat: 48.463500),
        .init(lon: 8.270368, lat: 48.482690),
        .init(lon: 8.257163, lat: 48.490620),
        .init(lon: 8.240554, lat: 48.488870),
        .init(lon: 8.216433, lat: 48.505800),
        .init(lon: 8.218299, lat: 48.516940),
        .init(lon: 8.208677, lat: 48.521650),
        .init(lon: 8.215457, lat: 48.538650),
        .init(lon: 8.209762, lat: 48.559180),
        .init(lon: 8.233734, lat: 48.577270),
        .init(lon: 8.226221, lat: 48.577750),
        .init(lon: 8.203471, lat: 48.601930),
        .init(lon: 8.209425, lat: 48.607630),
        .init(lon: 8.230710, lat: 48.609020),
        .init(lon: 8.238465, lat: 48.626390),
        .init(lon: 8.199337, lat: 48.625100),
        .init(lon: 8.180656, lat: 48.636590),
        .init(lon: 8.160690, lat: 48.637610),
        .init(lon: 8.145350, lat: 48.650470),
        .init(lon: 8.106940, lat: 48.648400),
        .init(lon: 8.072214, lat: 48.671020),
        .init(lon: 8.063003, lat: 48.667730),
        .init(lon: 8.059171, lat: 48.674090),
        .init(lon: 8.032122, lat: 48.674380),
        .init(lon: 8.030530, lat: 48.681070),
        .init(lon: 7.978792, lat: 48.684370),
        .init(lon: 7.970586, lat: 48.692400),
        .init(lon: 7.983905, lat: 48.704350),
        .init(lon: 7.949946, lat: 48.720910),
    ]
}

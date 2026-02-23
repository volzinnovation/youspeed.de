import CoreLocation
import Foundation

@MainActor
final class DriveSessionViewModel: NSObject, ObservableObject {
    @Published var syncStatus: String = "not_synced"
    @Published var driveStatus: String = "stopped"
    @Published var activeBundleVersion: String = "none"
    @Published var activeDBPath: String = ""
    @Published var currentSpeedKmh: Double = 0
    @Published var speedLimitKmh: Int?
    @Published var limitWayID: String?
    @Published var lastError: String = ""

    private let bundleManager = V3BundleManager()
    private let locationManager = CLLocationManager()
    private var speedLimitService: V3SpeedLimitService?
    private var isDriving = false

    override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.activityType = .automotiveNavigation
        locationManager.distanceFilter = 10
    }

    func bootstrapAndSync(manifestURLString: String) {
        Task {
            do {
                syncStatus = "bootstrapping"
                let bootstrap = try await bundleManager.bootstrapSeedIfNeeded()
                activeBundleVersion = bootstrap.bundleVersion
                activeDBPath = bootstrap.dbPath

                guard let manifestURL = URL(string: manifestURLString),
                      ["http", "https"].contains(manifestURL.scheme?.lowercased() ?? "") else {
                    syncStatus = "seed_only"
                    speedLimitService = V3SpeedLimitService(dbPath: activeDBPath)
                    return
                }

                syncStatus = "syncing"
                let sync = try await bundleManager.syncFromManifestURL(manifestURL)
                activeBundleVersion = sync.bundleVersion
                activeDBPath = sync.dbPath
                speedLimitService = V3SpeedLimitService(dbPath: sync.dbPath)
                syncStatus = "ready_\(sync.mode.rawValue)"
            } catch {
                syncStatus = "sync_failed"
                lastError = error.localizedDescription
                if !activeDBPath.isEmpty {
                    speedLimitService = V3SpeedLimitService(dbPath: activeDBPath)
                }
            }
        }
    }

    func startDriving() {
        if syncStatus == "not_synced" {
            lastError = "Run data sync before starting driving mode"
            return
        }

        isDriving = true
        driveStatus = "requesting_location"
        let auth = locationManager.authorizationStatus
        if auth == .notDetermined {
            locationManager.requestWhenInUseAuthorization()
        } else if auth == .authorizedWhenInUse || auth == .authorizedAlways {
            locationManager.startUpdatingLocation()
            driveStatus = "running"
        } else {
            driveStatus = "location_denied"
            lastError = "Location permission denied"
        }
    }

    func stopDriving() {
        isDriving = false
        locationManager.stopUpdatingLocation()
        driveStatus = "stopped"
    }

    private func updateSpeedLimit(for location: CLLocation) {
        guard let service = speedLimitService else {
            return
        }
        let lat = location.coordinate.latitude
        let lon = location.coordinate.longitude

        Task.detached(priority: .utility) {
            do {
                let result = try service.lookupSpeedLimit(lat: lat, lon: lon)
                await MainActor.run {
                    self.speedLimitKmh = result.speedLimitKmh
                    self.limitWayID = result.wayID
                }
            } catch {
                await MainActor.run {
                    self.lastError = error.localizedDescription
                }
            }
        }
    }
}

extension DriveSessionViewModel: @preconcurrency CLLocationManagerDelegate {
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard isDriving else {
            return
        }
        let auth = manager.authorizationStatus
        if auth == .authorizedWhenInUse || auth == .authorizedAlways {
            manager.startUpdatingLocation()
            driveStatus = "running"
        } else if auth == .denied || auth == .restricted {
            driveStatus = "location_denied"
            lastError = "Location permission denied"
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else {
            return
        }
        currentSpeedKmh = max(0, location.speed) * 3.6
        updateSpeedLimit(for: location)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        driveStatus = "location_error"
        lastError = error.localizedDescription
    }
}

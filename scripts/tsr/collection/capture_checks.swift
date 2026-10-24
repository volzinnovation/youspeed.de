import Foundation

func runCollectionCaptureChecks(gate: SignCollectionContractGate, root: URL, output: URL) throws {
    let vectors = try SignCollectionJSON.parse(String(contentsOf: root.appendingPathComponent("fixtures/camera-axis-v1.json"), encoding: .utf8)) as! [[String: Any]]
    let at = Date(timeIntervalSince1970: 1_770_000_000)
    for vector in vectors {
        let sample = SignCollectionCameraSample.coreMotionMatrix(vector["ios_nwu_to_device"] as! [Double], at: at, accuracy: "high")!
        let bearing = vector["bearing"] as! Double, elevation = vector["elevation"] as! Double
        let difference = abs(sample.azimuth - bearing)
        try check(min(difference,360-difference) < 0.0001 && abs(sample.elevation-elevation) < 0.0001,
                  "camera axis preserves compass/elevation across mounting rotations")
    }
    try check(SignCollectionCameraSample.opticalAxis(north: 0, east: 0, up: 1, at: at, accuracy: "high", source: "core_motion_true_north") == nil, "vertical camera has no invented azimuth")
    try check(SignCollectionCameraSample.opticalAxis(north: 1, east: 0, up: 0, at: at, accuracy: "low", source: "core_motion_true_north") == nil, "uncalibrated compass rejected")
    let history = SignCollectionCameraHistory()
    let original = SignCollectionCameraSample.opticalAxis(north: 1, east: 0, up: 0, at: at, accuracy: "high", source: "core_motion_true_north")!
    history.append(original)
    history.append(SignCollectionCameraSample.opticalAxis(north: 0, east: 1, up: 0, at: at.addingTimeInterval(1), accuracy: "high", source: "core_motion_true_north")!)
    try check(history.direction(at: at)?["azimuth_degrees"] as? Double == 0, "delayed frame retains its capture pose")
    try check(history.direction(at: at.addingTimeInterval(2)) == nil, "stale pose rejected")
    history.clear(); try check(history.direction(at: at) == nil, "session/privacy reset clears pose")
    var batch = try SignCollectionJSON.parse(String(contentsOf: root.appendingPathComponent("fixtures/capture-sighting-batch-v1.json"), encoding: .utf8)) as! [String: Any]
    let event = (batch["events"] as! [[String: Any]])[0]
    try gate.validate(batch, model: "batch"); try gate.validate(event, model: "sighting")
    for field in ["capture_metadata_version", "device_id", "vehicle_position", "camera_viewing_direction"] {
        var invalid = event; invalid.removeValue(forKey: field)
        rejects { try gate.validate(invalid, model: "sighting") }
    }
    var invalid = event; invalid["device_id"] = SignCollectionJSON.uuid(); batch["events"] = [invalid]
    rejects { try gate.validate(batch, model: "batch") }
    var direction = event["camera_viewing_direction"] as! [String: Any]
    direction["frame_measurement_delta_ms"] = 400; invalid = event; invalid["camera_viewing_direction"] = direction
    rejects { try gate.validate(invalid, model: "sighting") }
    let crop = try SignCollectionJSON.parse(String(contentsOf: root.appendingPathComponent("fixtures/capture-crop-v1.json"), encoding: .utf8)) as! [String: Any]
    try gate.validate(crop, model: "crop")
    invalid = crop; invalid["device_id"] = SignCollectionJSON.uuid()
    rejects { try gate.validate(invalid, model: "crop") }
    let store = try SignCollectionStore(root: output.appendingPathComponent("capture-device-" + SignCollectionJSON.uuid()), gate: gate)
    try store.beginSession(SignCollectionJSON.uuid())
    _ = try store.decide(scope: "sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure, granted: true, dontAskAgain: false)
    rejects { try store.enqueue(kind: "sighting", event: event, disclosure: SignCollectionCapabilities.metadataDisclosure) }
    invalid = event; invalid["device_id"] = try store.installationID
    try store.enqueue(kind: "sighting", event: invalid, disclosure: SignCollectionCapabilities.metadataDisclosure)
    try check(store.pendingCount() == 1, "store binds capture device to its installation")
    print("Swift capture metadata: 48 camera mounting vectors, capture history, freshness, complete records and device binding passed")
}

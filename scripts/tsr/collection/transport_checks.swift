import Foundation
import CoreGraphics

private final class CollectionFakeHTTP: SignCollectionRequesting {
    let handle: (String, String?) throws -> SignCollectionHTTPResponse
    var capture: ((String, Data) throws -> SignCollectionHTTPResponse)?
    init(_ handle: @escaping (String, String?) throws -> SignCollectionHTTPResponse) { self.handle = handle }
    func request(path: String, body: String?) async throws -> SignCollectionHTTPResponse { try handle(path, body) }
    func captureCrop(metadata: String, bytes: Data) async throws -> SignCollectionHTTPResponse { try capture!(metadata, bytes) }
}

func runCollectionTransportChecks(gate: SignCollectionContractGate, root: URL, fixture: [String: Any]) async throws {
    // Local fixtures only; no synthetic observations are sent to production.
    let disclosure = SignCollectionCapabilities.metadataDisclosure
    let caps: [String: Any] = ["limits": ["metadata_bytes":524288,"event_bytes":16384,"media_bytes":5242880],
        "disclosure_versions": ["sign_metadata":[disclosure],"crop_storage":[SignCollectionCapabilities.cropDisclosure]]]
    _ = try SignCollectionCapabilities(caps) // No manifest hash, receipt state or handshake.
    var time = Date(), metadataRequests = 0, capabilityRequests = 0, loseResponse = true, throttle = true
    let store = try SignCollectionStore(root:root.appendingPathComponent("transport-" + SignCollectionJSON.uuid()),gate:gate,now:{time})
    try store.beginSession(SignCollectionJSON.uuid())
    _ = try store.decide(scope:"sign_metadata",disclosure:disclosure,granted:true,dontAskAgain:false)
    func observation() -> [String:Any] {
        var event = fixture; event["event_id"] = SignCollectionJSON.uuid()
        return event
    }
    try store.enqueue(kind:"sighting",event:observation(),disclosure:disclosure)
    try store.enqueue(kind:"sighting",event:observation(),disclosure:disclosure)
    let http = CollectionFakeHTTP { path,body in
        if path == "capabilities" { capabilityRequests += 1; return .init(status:200,body:caps,retryAfter:nil) }
        let value = try SignCollectionJSON.parse(body!) as! [String:Any]
        if path == "consent-events" { return .init(status:200,body:["state":"recorded","operation_receipt":"grant-" + (value["event_id"] as! String)],retryAfter:nil) }
        try check(path == "capture-sightings", "sole metadata upload route")
        metadataRequests += 1
        if loseResponse { loseResponse = false; throw URLError(.networkConnectionLost) }
        if throttle { throttle = false; return .init(status:429,body:[:],retryAfter:"60") }
        return .init(status:204,body:[:],retryAfter:nil)
    }
    let worker = SignCollectionUploadWorker(store:store,client:http,now:{time},jitter:{0})
    let offline = try await worker.runOnce(networkAvailable:false,ordinaryDeliveryAllowed:true)
    try check(offline == "offline" && capabilityRequests == 0,"offline keeps buffered evidence")
    let paused = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:false)
    try check(paused == "contribution_paused" && metadataRequests == 0,"sharing control precedes ordinary delivery")
    do { _ = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true); fatalError("lost response expected") } catch is URLError {}
    try check(store.pendingCount() == 2,"temporary network failure retains the batch")
    time = time.addingTimeInterval(10)
    let limited = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
    let delay = try await worker.retryDelay()
    try check(limited == "backoff" && abs(delay - 60) < 0.001,"retry uses the server deadline")
    time = time.addingTimeInterval(59)
    _ = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
    try check(metadataRequests == 2,"no requests before Retry-After")
    time = time.addingTimeInterval(1.01)
    _ = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
    try check(store.pendingCount() == 0 && metadataRequests == 3 && capabilityRequests == 1,"one empty success clears the batch without receipt checks")
    print("Swift best-effort metadata: offline/paused delivery, cached capabilities, lost response and precise retry passed")

    try store.authorizeAutomaticCrops()
    let claim = try store.claim(scope:"crop_storage",disclosure:SignCollectionCapabilities.cropDisclosure)
    var pixel:[UInt8] = [0,170,187,255]
    let context = CGContext(data:&pixel,width:1,height:1,bitsPerComponent:8,bytesPerRow:4,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
    let crop = try SignCollectionCrop.generate(upright:context.makeImage()!,box:["x":0,"y":0,"width":1,"height":1],hashSource:false)
    let observationID = SignCollectionJSON.uuid()
    func enqueueCrop() throws {
        try store.enqueueAutomaticCrop(metadata:crop.metadata(cropID:SignCollectionJSON.uuid(),observationID:observationID,installationID:try store.installationID,epoch:0,sourceKind:"detector",frameAt:time,
            localFrameToken:"host-frame",privacyPreflight:"passed",redactionVersion:"metadata-strip-1",collectionClaim:claim),bytes:crop.bytes)
    }
    for _ in 0..<9 { try enqueueCrop() }
    var captures = 0, failCrop = false
    http.capture = { _,bytes in
        captures += 1; try check(bytes == crop.bytes,"transfer encoded crop directly")
        return .init(status:failCrop ? 503 : 204,body:[:],retryAfter:nil)
    }
    _ = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
    try check(captures == 8 && store.nextCrop() != nil && store.pendingCount() == 0,"bounded crop group needs no client status batch")
    _ = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
    try check(captures == 9 && store.nextCrop() == nil,"nine crops need nine requests without reservations or receipt checks")
    try enqueueCrop(); failCrop = true
    for _ in 0..<3 {
        _ = try await worker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
        time = time.addingTimeInterval(65)
    }
    try check(captures == 12 && store.nextCrop() == nil && store.pendingCount() == 0,"three temporary failures discard the optional crop and unblock the queue")
    print("Swift best-effort crops: one request per image, bounded groups, no linked-status request and three-attempt loss passed")

    var failMetadata = true
    let unavailable = CollectionFakeHTTP { path,body in
        if path == "capabilities" { return .init(status:200,body:caps,retryAfter:nil) }
        if path == "consent-events" {
            let value = try SignCollectionJSON.parse(body!) as! [String:Any]
            return .init(status:200,body:["state":"recorded","operation_receipt":"grant-" + (value["event_id"] as! String)],retryAfter:nil)
        }
        if failMetadata { throw URLError(.networkConnectionLost) }
        return .init(status:204,body:[:],retryAfter:nil)
    }
    let failing = SignCollectionUploadWorker(store:store,client:unavailable,now:{time},jitter:{0})
    try store.enqueue(kind:"sighting",event:observation(),disclosure:disclosure)
    for _ in 0..<3 {
        _ = try? await failing.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:true)
        time = time.addingTimeInterval(65)
    }
    try check(store.pendingCount() == 0,"three network failures discard the ordinary batch")
    failMetadata = false

    let privacy = try SignCollectionStore(root:root.appendingPathComponent("privacy-" + SignCollectionJSON.uuid()),gate:gate)
    try privacy.beginSession(SignCollectionJSON.uuid())
    _ = try privacy.decide(scope:"sign_metadata",disclosure:disclosure,granted:true,dontAskAgain:false)
    let deletion = try privacy.requestDeletion()
    var paths:[String] = [], removed = false
    let privacyHTTP = CollectionFakeHTTP { path,_ in
        paths.append(path)
        if path == "capabilities" { return .init(status:200,body:caps,retryAfter:nil) }
        try check(path != "consent-events","deletion takes priority over previous consent")
        return .init(status:200,body:["operation_receipt":"delete-receipt","state":removed ? "active_data_removed":"deletion_pending","next_collection_epoch":1,"active_data_removed":removed,"archives_purged":false,"backup_expiry_complete":false],retryAfter:nil)
    }
    let privacyWorker = SignCollectionUploadWorker(store:privacy,client:privacyHTTP)
    _ = try await privacyWorker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:false)
    try check(paths.contains("operation-status") && privacy.collectionEpoch == 0,"privacy completion remains explicit")
    removed = true
    _ = try await privacyWorker.runOnce(networkAvailable:true,ordinaryDeliveryAllowed:false)
    try check(privacy.collectionEpoch == 1 && !privacy.deletionIsPending && privacy.controlStatus(id:deletion)?.isComplete == false,"active removal releases the epoch independently of backup completion")
    print("Swift privacy controls: priority, withdrawal and separate deletion completion passed")

    let observer = SignCollectionObserver(); var sightings:[[String:Any]] = []
    let detection = SignCollectionObserver.Detection(key:"non-speed",box:[0.1,0.1,0.2,0.2],payload:fixture,presentationTrack:"presentation")
    for offset in [0.0,0.1,0.2] { try observer.observe(at:time.addingTimeInterval(offset),detections:[detection]) { sightings.append($0) } }
    try check(sightings.count == 1,"continuing encounter is not duplicated")
    observer.freeze(attempt:"speech",presentation:"presentation")
    try check(observer.correction(attempt:"speech",modality:"voice",at:time.addingTimeInterval(3))?["target_id"] as? String == sightings[0]["event_id"] as? String,"correction keeps its exact sighting")
}

func resumeCollectionHostCleanup(gate:SignCollectionContractGate,root:URL) async throws {
    let client = try SignCollectionHTTPClient(); defer { client.close() }
    for directory in try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil).filter({$0.lastPathComponent.hasPrefix("live-host-")}) {
        let store = try SignCollectionStore(root:directory,gate:gate)
        if try store.pendingControls().contains(where:{$0.kind == "deletion"}) {
            _ = try await SignCollectionUploadWorker(store:store,client:client).runOnce(networkAvailable:true,ordinaryDeliveryAllowed:false)
        }
    }
}

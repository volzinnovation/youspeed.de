#!/usr/bin/env python3
"""Prepare replay-only requests; upload only with an explicit --upload command.

Private pixels and request/acknowledgment records remain in the replay directory.
Uses a fresh simulated installation, no reconstructed GPS, and estimated UTC.
Requires jsonschema. Run prepare once, then upload the resulting upload-plan.json.
"""
import argparse
import copy
import hashlib
import json
import struct
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "shared/tsr/collection-contract-v1"
API = "https://live-eu.woladen.de/youspeed/v1"


def uid():
    return str(uuid.uuid4())


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def utc(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def artifact_hash(path):
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(child.relative_to(path).as_posix().encode() + b"\0")
        digest.update(child.read_bytes() + b"\0")
    return digest.hexdigest()


def prepare(report_path, pack, anchor):
    import jsonschema
    directory = report_path.parent
    plan_path = directory / "upload-plan.json"
    if plan_path.exists():
        raise ValueError("Plan already exists; reuse it to preserve retry identity")
    report = json.loads(report_path.read_text())
    source_evidence = report.get("source_evidence")
    manifest_bytes = (pack / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == report["manifest_sha256"]
    manifest = json.loads(manifest_bytes)
    schemas = {name: json.loads((CONTRACT / f"{name}-v1.schema.json").read_text())
               for name in ["batch", "sighting", "crop", "consent"]}
    def validate(value, kind):
        jsonschema.Draft202012Validator(schemas[kind], format_checker=jsonschema.FormatChecker()).validate(value)
    def stamp(seconds):
        return utc(anchor + timedelta(seconds=seconds))
    def elapsed(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    installation, session = uid(), uid()
    now = utc(datetime.now(timezone.utc))
    claims = {scope: dict(scope=scope, disclosure_version=disclosure, decided_at=now,
                          consent_generation=1, state="granted", origin="client_claim")
              for scope, disclosure in [("sign_metadata", "youspeed-camera-use-pilot-1"),
                                        ("crop_storage", "youspeed-crop-storage-pilot-1")]}
    components, artifact_provenance = [], []
    for role in ["detector", "classifier"]:
        artifact = next(a for a in manifest[role]["artifacts"] if a["platform"] == "ios")
        actual_hash = artifact_hash(pack / artifact["path"])
        artifact_provenance.append(dict(role=role, actual_sha256=actual_hash, declared_sha256=artifact["sha256"]))
        components.append(dict(role="proposal_detector" if role == "detector" else "semantic_classifier", artifact_sha256=actual_hash,
            preprocessing_version=manifest["preprocessing"]["version"] if role == "detector" else "vision-scale-fill-xpad10-lower35-upper5-v1",
            calibration_id=None, calibration_sha256=None))
    mapping = {m["class_id"]: m for m in manifest["class_mapping"]}
    model = dict(pack_id=report["pack_id"], pack_version="manifest-schema-1", pack_sha256=report["manifest_sha256"], components=components)
    requests = []
    request_directory = directory / "upload-requests"
    request_directory.mkdir(exist_ok=False)
    def add(endpoint, value, kind, image=None):
        validate(value, kind)
        body = encoded(value)
        if image is not None:
            body = struct.pack(">I", len(body)) + body + image
        path = request_directory / f"{len(requests):04d}.request"
        path.write_bytes(body)
        requests.append(dict(endpoint=endpoint, file=str(path.relative_to(directory)),
            sha256=hashlib.sha256(body).hexdigest(), byte_length=len(body),
            content_type="application/vnd.youspeed.crop" if image is not None else "application/json"))
    for claim in claims.values():
        add("consent-events", dict(schema_version=1, event_id=uid(), installation_id=installation,
            collection_epoch=0, collection_authorization=claim), "consent")
    template = json.loads((CONTRACT / "fixtures/sighting-batch-v1.json").read_text())["events"][0]
    events = []
    for sighting in report["sightings"]:
        event = copy.deepcopy(template)
        entry = mapping.get(sighting["raw_class_id"], {})
        semantic = entry.get("semantic", {})
        event.update(event_id=sighting["event_id"], collection_session_id=session,
            observer_version="dashcam-replay-crop-sequence-1", app=dict(platform="ios", version="1.4", build="dashcam-replay"),
            first_seen_at=stamp(elapsed(sighting["first_seen_at"])), last_seen_at=stamp(elapsed(sighting["last_seen_at"])),
            representative_frame_at=stamp(sighting["frame_seconds"]), duration_ms=sighting["duration_ms"],
            vehicle_position=None, sign_position=None, road_context=None, model=model)
        event["classification"] = dict(country=report["country"], model_label=sighting["label"], canonical_code=None,
            family=semantic.get("kind", "unknown"), value=semantic.get("value"), unit=semantic.get("unit"),
            role="primary" if entry else "unknown", mapping_revision=None, mapping_sha256=None, alternatives=[])
        event["scores"].update(sighting["scores"])
        event["evidence"] = dict(track_id=sighting["event_id"], assembly_id=None,
            analyzed_frames=sighting["evidence"]["analyzed_frames"], finalization_reason="qualified_track",
            quality_flags=["dashcam_replay", "simulated_installation", "recording_time_estimated", "gps_missing"],
            normalized_box=dict(zip(["x", "y", "width", "height"], sighting["evidence"]["replay_box"])))
        if source_evidence:
            event["evidence"]["quality_flags"].extend([
                "hf_archive_replay", "model_country_assumed",
                "recording_source_" + source_evidence["recording_platform"]])
        if any(p["actual_sha256"] != p["declared_sha256"] for p in artifact_provenance):
            event["evidence"]["quality_flags"].append("artifact_manifest_hash_mismatch")
        validate(event, "sighting")
        assert len(encoded(event)) <= 16384
        events.append(event)
    for offset in range(0, len(events), 100):
        batch = dict(schema_version=1, batch_id=uid(), installation_id=installation, collection_epoch=0,
            collection_authorization=claims["sign_metadata"], events=events[offset:offset + 100])
        assert len(encoded(batch)) <= 524288
        add("capture-sightings", batch, "batch")
    crop_ids = []
    for crop in report["crops"]:
        if crop["variant"] != "sequence":
            continue
        image = (directory / crop["file"]).read_bytes()
        assert image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) <= 5242880
        x0, y0, x1, y1 = crop["original_box"]
        actual, requested = crop["actual_box"], crop["requested_box"]
        width, height = actual[2] - actual[0], actual[3] - actual[1]
        assert struct.unpack(">II", image[16:24]) == (width, height)
        crop_id = uid(); crop_ids.append(crop_id)
        metadata = dict(schema_version=1, installation_id=installation, collection_epoch=0,
            crop_id=crop_id, observation_id=crop["observation_id"], source_kind="detector",
            source_frame_at=stamp(crop["frame_seconds"]), source_width=crop["source_width"], source_height=crop["source_height"],
            supplied_box=dict(zip(["x", "y", "width", "height"], crop["box"])),
            original_box=crop["original_box"], requested_box=requested, actual_box=actual,
            requested_extra_height=y1-y0, actual_extra_height=actual[3]-y1, bottom_clipped=actual != requested,
            source_upright_sha256=None, local_frame_token=(
                f"hf-replay:{source_evidence['sha256']}:{crop['frame_seconds']:.9f}" if source_evidence
                else f"dashcam-replay:{crop['frame_seconds']:.9f}"),
            encoded_sha256=hashlib.sha256(image).hexdigest(), byte_length=len(image), decoded_width=width, decoded_height=height,
            encoding="PNG", orientation_version="upright-1", crop_version="downward-1", redaction_version="metadata-strip-1",
            redaction_masks=[], privacy_preflight="passed", collection_authorization=claims["crop_storage"], processor_authorization=None)
        add("capture-crops", metadata, "crop", image)
    plan = dict(installation_id=installation, simulated=True, recorded_start_utc_estimated=utc(anchor), artifact_provenance=artifact_provenance,
        observation_count=len(events), crop_count=len(crop_ids), crop_ids=crop_ids, requests=requests,
        note="Private replay from compressed dashcam video; iPhone Core ML on Mac, no GPS. Baseline crops are local only.")
    if source_evidence:
        plan["source_evidence"] = source_evidence
    plan_path.write_bytes(encoded(plan))
    print(json.dumps({k: plan[k] for k in ["installation_id", "observation_count", "crop_count"]}))


def upload(plan_path):
    directory = plan_path.parent
    plan = json.loads(plan_path.read_text())
    with urllib.request.urlopen(API + "/capabilities", timeout=30) as response:
        capabilities = json.load(response)
    if capabilities.get("delivery_mode") != "best_effort_v2":
        raise RuntimeError("Matching best_effort_v2 backend is not active; no replay requests sent")
    acknowledgments = directory / "upload-acknowledgments.ndjson"
    done = {json.loads(line)["index"] for line in acknowledgments.read_text().splitlines()} if acknowledgments.exists() else set()
    for index, request in enumerate(plan["requests"]):
        if index in done:
            continue
        body = (directory / request["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == request["sha256"]
        for attempt in range(4):
            try:
                req = urllib.request.Request(API + "/" + request["endpoint"], data=body,
                    headers={"Content-Type": request["content_type"]}, method="POST")
                with urllib.request.urlopen(req, timeout=60) as response:
                    reply = dict(index=index, status=response.status, at=utc(datetime.now(timezone.utc)),
                        request_sha256=request["sha256"], response=response.read().decode())
                with acknowledgments.open("a") as stream:
                    stream.write(encoded(reply).decode() + "\n"); stream.flush()
                if index % 25 == 0:
                    print(f"Acknowledged {index + 1}/{len(plan['requests'])}", flush=True)
                break
            except urllib.error.HTTPError as error:
                if error.code not in [429, 500, 502, 503, 504] or attempt == 3:
                    raise RuntimeError(f"Request {index}: HTTP {error.code}: {error.read().decode()}") from error
                time.sleep(min(60, max(2, int(error.headers.get("Retry-After", "60")))))
        time.sleep(0.55)
    print(f"Uploaded {plan['crop_count']} crops and {plan['observation_count']} sightings as {plan['installation_id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--model-pack", type=Path)
    parser.add_argument("--recorded-start-utc", help="Explicit estimated recording UTC; not recovered GPS time")
    parser.add_argument("--upload", type=Path, help="Upload a prepared upload-plan.json to the live collection backend")
    args = parser.parse_args()
    if args.upload:
        upload(args.upload)
    elif args.report and args.model_pack and args.recorded_start_utc:
        prepare(args.report, args.model_pack, datetime.fromisoformat(args.recorded_start_utc.replace("Z", "+00:00")))
    else:
        parser.error("Specify --upload, or --report, --model-pack and --recorded-start-utc")

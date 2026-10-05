#!/usr/bin/env python3
"""Verify the shared byte lock, schema fixtures, native output and backend parity.

No network calls, writes to the sibling repo, or live-data release approval.
"""
import argparse
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PIN = ROOT / "shared/tsr/collection-contract-v1"
ALLOWED = {"$defs", "$ref", "additionalProperties", "anyOf", "const", "default", "description", "enum", "exclusiveMaximum", "exclusiveMinimum", "format", "items", "maxItems", "maxLength", "maximum", "minItems", "minLength", "minimum", "pattern", "properties", "required", "title", "type"}

def main():
    import jsonschema
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, help="optional sibling worktree; also validates Pydantic semantics")
    parser.add_argument("--native-output", type=Path, help="output of Swift checks and Kotlin unit tests")
    args = parser.parse_args()
    lock = json.loads((ROOT / "shared/tsr/collection-contract-source.json").read_text())
    manifest_bytes = (PIN / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == lock["manifest_sha256"]
    manifest = json.loads(manifest_bytes)
    assert manifest["cross_client_approved"] is False and lock["live_transport_enabled"] is True
    expected_files = {"manifest.json"} | {entry["path"] for entry in manifest["files"]}
    assert {str(path.relative_to(PIN)) for path in PIN.rglob("*") if path.is_file()} == expected_files
    for entry in manifest["files"]:
        path = PIN / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]
    for client in [ROOT / "iphone/SpeedConsumerApp/SignCollectionContract.swift", ROOT / "android/app/src/main/java/de/youspeed/android/alpha/SignCollectionContract.kt"]:
        assert lock["manifest_sha256"] in client.read_text(), client
    event_limits = []
    for client in [ROOT / "iphone/SpeedConsumerApp/SignCollectionStore.swift", ROOT / "android/app/src/main/java/de/youspeed/android/alpha/SignCollectionStore.kt"]:
        match = re.search(r"maximumEventBytes\s*=\s*(\d+)\s*\*\s*1024\b", client.read_text())
        assert match, f"native event limit missing: {client}"
        event_limits.append(int(match.group(1)) * 1024)
    assert event_limits[0] == event_limits[1], "native event size limit mismatch"
    project = (ROOT / "iphone/SpeedDBBench.xcodeproj/project.pbxproj").read_text()
    assert 'path = "../shared/tsr/collection-contract-v1"' in project
    assert 'collection-contract-v1 in Resources' in project
    assert '"../../shared"' in (ROOT / "android/app/build.gradle.kts").read_text()
    schemas = {name: json.loads((PIN / f"{name}-v1.schema.json").read_text()) for name in ["batch", "sighting", "correction", "crop", "consent", "deletion", "media-status", "extraction"]}
    def schema_keywords(node):
        assert not set(node) - ALLOWED, set(node) - ALLOWED
        for key in ["$defs", "properties"]:
            for child in node.get(key, {}).values(): schema_keywords(child)
        for child in node.get("anyOf", []): schema_keywords(child)
        if isinstance(node.get("items"), dict): schema_keywords(node["items"])
    for schema in schemas.values():
        jsonschema.Draft202012Validator.check_schema(schema)
        schema_keywords(schema)
    payloads = []
    for name in ["sighting", "manual"]:
        value = json.loads((PIN / f"fixtures/{name}-batch-v1.json").read_text())
        payloads.append(("batch", value))
        payloads.extend(("sighting", event) for event in value["events"])
    for name in ["correction", "crop", "consent", "deletion", "media-status", "extraction"]:
        payloads.append((name, json.loads((PIN / f"fixtures/{name}-v1.json").read_text())))
    for model, value in payloads: jsonschema.validate(value, schemas[model])
    backend = None
    if args.backend:
        source = args.backend / "commercial_backend/youspeed/contracts"
        for name in expected_files: assert (source / name).read_bytes() == (PIN / name).read_bytes(), f"backend drift: {name}"
        sys.path.insert(0, str(args.backend))
        backend = importlib.import_module("commercial_backend.youspeed.contracts")
        processing = importlib.import_module("commercial_backend.youspeed.processing")
        limits = importlib.import_module("commercial_backend.youspeed.spool").Limits()
        assert event_limits[0] == limits.event_bytes, f"backend event limit drift: clients={event_limits[0]}, backend={limits.event_bytes}"
        models = {"batch": backend.Batch, "sighting": backend.Sighting, "correction": backend.Correction, "crop": backend.Crop, "consent": backend.Consent, "deletion": backend.Deletion, "media-status": backend.MediaStatus, "extraction": processing.Extraction}
        for model, value in payloads: models[model].model_validate(value)
    if args.native_output:
        out = args.native_output
        swift = (out / "swift-numbers.json").read_bytes()
        kotlin = (out / "kotlin-numbers.json").read_bytes()
        assert swift == kotlin, "native numeric canonicalization mismatch"
        if backend: assert swift == backend.canonical(json.loads(swift)), "backend numeric mismatch"
        for suffix, expected in [("at-limit", event_limits[0]), ("over-limit", event_limits[0] + 1)]:
            path = out / f"swift-event-{suffix}.json"
            raw = path.read_bytes()
            value = json.loads(raw)
            jsonschema.validate(value, schemas["sighting"])
            assert len(raw) == expected, f"native event size boundary mismatch: {path}"
            if backend:
                models["sighting"].model_validate(value)
                assert backend.canonical(value) == raw, path
        for platform in ["swift", "kotlin"]:
            for model in ["batch", "consent", "deletion", "crop"]:
                path = out / f"{platform}-{model}.json"
                if not path.exists(): continue
                value = json.loads(path.read_text())
                jsonschema.validate(value, schemas[model])
                if backend:
                    models[model].model_validate(value)
                    assert backend.canonical(value) == path.read_bytes(), path
                    if model == "batch":
                        for event in value["events"]: backend.Sighting.model_validate(event)
            crop_path = out / f"{platform}-crop.png"
            if crop_path.exists():
                from PIL import Image
                with Image.open(crop_path) as image:
                    assert image.info == {} and image.getexif() == {} and image.n_frames == 1
                    assert image.size == (1, 1) and image.getpixel((0, 0)) == (0, 170, 187)
        row_path = out / "swift-rows.png"
        if row_path.exists():
            from PIL import Image
            with Image.open(row_path) as image:
                assert image.size == (2,2) and image.getpixel((0,0)) == (0,255,0) and image.getpixel((0,1)) == (0,0,255)
    print(f"Shared contract lock: {len(manifest['files'])} exact files; fixture schemas and native packaging paths passed; live transport requires explicit authorization and capabilities")
    if backend: print("Sibling schema bytes and backend Pydantic/canonicalization checks passed")
    print(f"Native event size limits match: {event_limits[0]} bytes" + ("; sibling backend default matched" if backend else ""))
    if args.native_output: print("Swift/Kotlin numeric parity, generated request schemas and metadata-free PNG passed")

if __name__ == "__main__":
    main()

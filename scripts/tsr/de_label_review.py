#!/usr/bin/env python3
"""Serve prediction-blind crop proposals and record explicit local human review.

Only frozen crop bytes, assistant visual proposals and the shared class catalog
are loaded. Model predictions and source-generated labels are never read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

EXCLUSIONS = {"unreadable", "out_of_catalog", "needs_context"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_review(evidence: Path, catalog: Path) -> dict:
    intake = evidence / "intake"
    manifest = intake / "benchmark-all120.json"
    images = json.loads(manifest.read_text())["images"]
    classes = json.loads((evidence / "class-index.json").read_text())["classes"]
    names = {s["class_id"]: s["label"].get("en", s["class_id"])
             for s in json.loads(catalog.read_text())["signs"]}
    proposals = {}
    for name in ("phone", "panoramax"):
        for row in json.loads((intake / "blind" / f"proposed-{name}-labels.json").read_text())["labels"]:
            if row["id"] in proposals:
                raise ValueError("Duplicate proposal ID")
            proposals[row["id"]] = row
    if set(proposals) != {r["id"] for r in images}:
        raise ValueError("Proposals must cover the exact frozen intake")
    records = []
    for image in images:
        item = proposals[image["id"]]
        for path_key, hash_key in (("path", "sha256"), ("canonicalPath", "canonicalSha256")):
            if digest(intake / image[path_key]) != image[hash_key]:
                raise ValueError(f"Crop digest mismatch: {image['id']}")
        label = item["proposed_class_id"]
        if label is not None and label not in classes:
            raise ValueError(f"Unknown proposed class: {label}")
        exclusion = item["confidence"] if item["confidence"] in EXCLUSIONS else "needs_context"
        records.append({"id": image["id"], "source": image["source"],
                        "native_sha256": image["sha256"], "canonical_sha256": image["canonicalSha256"],
                        "proposed_class_id": label, "confidence": item["confidence"],
                        "visual_reason": item["visual_reason"],
                        "decision": label if label else "@" + exclusion,
                        "reviewed": False, "note": ""})
    context_path = evidence / "review-context.json"
    context = json.loads(context_path.read_text()) if context_path.exists() else {}
    return {"schema": "youspeed-human-field-review-v1", "manifest_sha256": digest(manifest),
            "catalog_sha256": digest(catalog), "classes": [{"id": c, "name": names.get(c, c)} for c in classes],
            "records": records, "context": context}


def validate_submission(data: dict, frozen: dict, final: bool) -> list:
    if data.get("manifest_sha256") != frozen["manifest_sha256"]:
        raise ValueError("Review belongs to a different frozen intake")
    if data.get("catalog_sha256") != frozen["catalog_sha256"]:
        raise ValueError("Review belongs to a different class catalog")
    rows = data.get("records")
    if not isinstance(rows, list) or len(rows) != len(frozen["records"]):
        raise ValueError("Review must contain every crop exactly once")
    expected = {r["id"]: r for r in frozen["records"]}
    valid = {r["id"] for r in frozen["classes"]} | {"@" + x for x in EXCLUSIONS}
    seen, result = set(), []
    for row in rows:
        key = row.get("id")
        if key not in expected or key in seen:
            raise ValueError("Unknown or duplicate crop ID")
        seen.add(key)
        original = expected[key]
        if any(row.get(k) != original[k] for k in ("native_sha256", "canonical_sha256")):
            raise ValueError(f"Crop digest mismatch: {key}")
        if row.get("decision") not in valid or type(row.get("reviewed")) is not bool:
            raise ValueError(f"Invalid review decision: {key}")
        if final and not row["reviewed"]:
            raise ValueError("Every crop must be explicitly reviewed before approval")
        note = row.get("note", "")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError("Review notes must be text up to 2000 characters")
        result.append({**original, "decision": row["decision"], "reviewed": row["reviewed"], "note": note})
    return sorted(result, key=lambda r: r["id"])


def atomic_json(path: Path, data: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(temporary, path)


def make_handler(evidence: Path, frozen: dict, token: str):
    allowed_ids = {r["id"] for r in frozen["records"]}
    html = Path(__file__).with_name("de_label_review.html").read_bytes()
    output = evidence / "intake" / "blind"

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, content, kind="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def local_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.local_host():
                return self.reply(403, b'{"error":"Local host required"}')
            path = urlparse(self.path).path
            if path == "/":
                return self.reply(200, html, "text/html; charset=utf-8")
            if path == "/favicon.ico":
                return self.reply(204, b"", "image/x-icon")
            if path == "/api/review":
                data = {**frozen, "token": token, "approved": False}
                saved = output / "review-progress.json"
                approved = output / "review-approved.json"
                if approved.exists():
                    saved = approved
                if saved.exists():
                    previous = json.loads(saved.read_text())
                    data["records"] = validate_submission(previous, frozen, approved.exists())
                    data["approved"] = approved.exists()
                return self.reply(200, json.dumps(data).encode())
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "image" and parts[1] in ("blind", "native") and parts[2] in allowed_ids:
                crop = evidence / "intake" / parts[1] / (parts[2] + ".png")
                return self.reply(200, crop.read_bytes(), "image/png")
            return self.reply(404, b'{"error":"Not found"}')

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (not self.local_host() or self.headers.get("Origin") != origin
                    or self.headers.get("X-Review-Token") != token):
                return self.reply(403, b'{"error":"Local review session required"}')
            if self.path not in ("/api/save", "/api/approve"):
                return self.reply(404, b'{"error":"Not found"}')
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                final = self.path == "/api/approve"
                records = validate_submission(data, frozen, final)
                approved = output / "review-approved.json"
                if approved.exists():
                    raise ValueError("Review already approved; immutable approval is retained")
                payload = {"schema": frozen["schema"], "manifest_sha256": frozen["manifest_sha256"],
                           "catalog_sha256": frozen["catalog_sha256"], "records": records,
                           "status": "human_approved" if final else "in_progress",
                           "saved_at": datetime.now(timezone.utc).isoformat(),
                           "approval_method": "explicit_local_review_ui" if final else None}
                target = approved if final else output / "review-progress.json"
                atomic_json(target, payload)
                self.reply(200, json.dumps({"saved": target.name, "approved": final}).encode())
            except (ValueError, TypeError, KeyError) as exc:
                self.reply(400, json.dumps({"error": str(exc)}).encode())

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("shared/tsr/prolix-de-class-catalog-v1.json"))
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    frozen = load_review(args.evidence, args.catalog)
    atomic_json(args.evidence / "intake" / "blind" / "review-package.json", frozen)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.evidence, frozen, secrets.token_urlsafe(32)))
    print(f"Review ready: http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

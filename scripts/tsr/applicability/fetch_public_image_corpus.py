#!/usr/bin/env python3
"""Explicit opt-in download of hash-pinned public Panoramax corpus images.

This helper never downloads private originals, sends credentials, overwrites a
cache entry, or runs during image_geometry_replay.py. Redirects remain HTTPS on
the known public Panoramax services. Changed upstream bytes require re-review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_HOSTS = frozenset({"panoramax.openstreetmap.fr", "api.panoramax.xyz",
                          "panoramax.ign.fr", "data.geopf.fr", "api.panoramax.ign.fr",
                          "api.panoramax.openstreetmap.fr", "images.panoramax.fr",
                          "images.panoramax.basi.re", "panoramax.youspeed.de"})
MAX_BYTES = 100 * 1024 * 1024


def public_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname not in PUBLIC_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Image URL must be HTTPS on an allowed public Panoramax host without credentials")
    return value


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        public_url(new_url)
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def fetch(corpus_paths, *, image_root=ROOT, opener=None):
    opener = opener or urllib.request.build_opener(PublicRedirects())
    root = Path(image_root).resolve()
    results = []
    for corpus_path in corpus_paths:
        corpus = json.loads(Path(corpus_path).read_text())
        for frame in corpus["frames"]:
            path = (root / frame["image_path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Image cache path must remain within --image-root")
            expected = frame["image_sha256"]
            if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
                raise ValueError("Invalid expected image SHA-256")
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError(f"Existing image hash mismatch; refusing overwrite: {path}")
                results.append({"frame_id": frame["frame_id"], "status": "verified_cached"})
                continue
            source = frame["source"]
            if source.get("kind") != "public_panoramax":
                results.append({"frame_id": frame["frame_id"], "status": "private_original_unavailable"})
                continue
            url = public_url(source["image_url"])
            request = urllib.request.Request(url, headers={"User-Agent": "YouSpeed-offline-corpus-review/1"})
            with opener.open(request, timeout=60) as response:
                public_url(response.geturl())
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Public image exceeds download size limit")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Downloaded bytes changed; review required: {frame['frame_id']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation preserves any concurrently created user cache.
            with path.open("xb") as output:
                output.write(data)
            results.append({"frame_id": frame["frame_id"], "status": "downloaded_and_verified"})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpora", nargs="+", type=Path)
    parser.add_argument("--image-root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(fetch(args.corpora, image_root=args.image_root), indent=2))


if __name__ == "__main__":
    main()

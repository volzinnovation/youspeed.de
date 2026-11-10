"""Reuse private sign identities across batches with qualified evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hmac
import math
import re

from shapely.geometry import Point
from shapely.strtree import STRtree

from scripts.tsr.collection.estimate_sign_poses import (
    IDENTITY_DISTANCE_M,
    IDENTITY_VIEW_DIFFERENCE_DEG,
    SIGN_CODE,
    delta_angle,
    image_bearing_candidate,
    number,
)


def sign_token(secret, *parts):
    return hmac.digest(secret, "\0".join(parts).encode(), "sha256").hex()[:32]


def identity_entry(code, fit, secret):
    direction = image_bearing_candidate(fit.rays)
    first = min(
        fit.rays,
        key=lambda ray: (
            datetime.fromisoformat(ray.captured_at.replace("Z", "+00:00")),
            ray.key,
        ),
    )
    return {
        "id": sign_token(secret, "canonical-sign-v1", code, first.key),
        "code": code,
        "point": list(fit.point),
        "view_direction": direction.heading if direction is not None else None,
        "evidence": sorted(
            sign_token(secret, "canonical-sign-evidence-v1", ray.key)
            for ray in fit.rays
        ),
    }


def load_identities(document):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("expected a version 1 private sign identity ledger")
    entries = document.get("signs")
    if not isinstance(entries, list) or len(entries) > 50_000:
        raise ValueError("invalid number of private sign identities")
    seen = set()
    for entry in entries:
        if (
            not re.fullmatch(r"[0-9a-f]{32}", entry["id"])
            or entry["id"] in seen
            or not SIGN_CODE.fullmatch(entry["code"])
        ):
            raise ValueError("invalid or duplicate sign identity")
        seen.add(entry["id"])
        x, y = entry["point"]
        number(x, -1_000_000, 2_000_000)
        number(y, 4_000_000, 7_000_000)
        if entry["view_direction"] is not None:
            number(entry["view_direction"], 0, 360)
        if not entry["evidence"] or not all(
            re.fullmatch(r"[0-9a-f]{32}", value) for value in entry["evidence"]
        ):
            raise ValueError("invalid sign identity evidence")
    return entries


def match_identities(entries, previous):
    """Match one-to-one, preferring shared inliers to proximity alone."""
    if not previous:
        return
    by_code = defaultdict(list)
    for old in previous:
        by_code[old["code"]].append(old)
    indices = {
        code: STRtree([Point(row["point"]) for row in rows])
        for code, rows in by_code.items()
    }
    matches = {}
    for i, entry in enumerate(entries):
        code = entry["code"]
        if code not in indices:
            continue
        options = []
        for j in indices[code].query(
            Point(entry["point"]), predicate="dwithin", distance=IDENTITY_DISTANCE_M
        ):
            old = by_code[code][j]
            if math.dist(old["point"], entry["point"]) >= IDENTITY_DISTANCE_M:
                continue
            a, b = old["view_direction"], entry["view_direction"]
            if (
                a is not None
                and b is not None
                and delta_angle(a, b) > IDENTITY_VIEW_DIFFERENCE_DEG
            ):
                continue
            shared = len(set(entry["evidence"]).intersection(old["evidence"]))
            if shared or (a is not None and b is not None):
                options.append((shared, old["id"]))
        options.sort(reverse=True)
        if options and (len(options) == 1 or options[0][0] > options[1][0]):
            matches[i] = options[0][1]
    competing = Counter(matches.values())
    generated = {entry["id"]: i for i, entry in enumerate(entries)}
    for i, identifier in matches.items():
        if competing[identifier] == 1 and generated.get(identifier, i) == i:
            entries[i]["id"] = identifier

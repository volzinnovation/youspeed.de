"""Index a private drive comparison by existing Inspector sign-group IDs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile


PHONES = ("Android", "iPhone")
SIGN_CODE = re.compile(r"DE:\d+(?:[.-]\d+)*\Z")


def inspector_index(snapshots):
    groups = {}
    anchors = defaultdict(set)
    follow_ons = defaultdict(set)
    for city, snapshot in snapshots.items():
        for group in snapshot["groups"]:
            identifier = group["id"]
            if identifier in groups:
                raise ValueError(f"Duplicate Inspector group {identifier}")
            refinement = group.get("mobile_refinement") or {}
            pose = refinement.get("proposal") if refinement.get("status") == "refined" else None
            pose = pose or group.get("proposal")
            code = group["sign_code"]
            groups[identifier] = {
                "id": identifier,
                "inspectorId": identifier,
                "city": city,
                "place": snapshot["place"]["name"],
                "code": code,
                "title": code,
                "mode": "Inspector sign group",
                "positionBasis": (pose.get("position_method") or pose.get("position_status")) if pose else None,
                "positionRadius": pose.get("position_radius_m") if pose else None,
                "azimuth": pose.get("azimut_deg") if pose else None,
                "p": [pose["longitude"], pose["latitude"]] if pose else None,
                "refs": [],
                "history": [],
                "Android": [],
                "iPhone": [],
                "reviewCases": [],
                "passages": {},
                "verdicts": dict.fromkeys(PHONES, "Unverified"),
            }
            for field, index in (("observations", anchors), ("follow_on_observations", follow_ons)):
                for item in group.get(field, []):
                    index[item["annotation_id"], code].add(identifier)
    return groups, anchors, follow_ons


def direction_matches(first, second):
    return first is None or second is None or abs((first - second + 180) % 360 - 180) <= 45


def distance(first, second):
    if not first or not second:
        return math.inf
    latitude = math.radians((first[1] + second[1]) / 2)
    return math.hypot((first[0] - second[0]) * math.cos(latitude), first[1] - second[1]) * 111_200


def reviewed_route_group(row, source_refs, current):
    if not SIGN_CODE.fullmatch(row["code"]):
        return None
    if not source_refs and not any(row[phone] for phone in PHONES):
        return None
    evidence = sorted(source_refs) or sorted(
        current[observation]["key"] for phone in PHONES for observation in row[phone]
    )
    identity = hashlib.sha256(f'{row["code"]}:{evidence[0]}'.encode()).hexdigest()[:24]
    return {
        **row,
        "id": f"route-{identity}",
        "routeGroup": True,
        "mode": "Crop-reviewed route group",
        "p": None,
        "cameraPoint": row.get("p"),
        "reviewCases": [{
            "title": row["title"],
            "note": row["note"],
            "verdicts": row["verdicts"],
        }],
    }


def group_review(data, snapshots):
    groups, anchors, follow_ons = inspector_index(snapshots)
    sources = data["groups"]
    references = data["refs"]
    identity = {}
    for annotation_id, annotation in references.items():
        key = (annotation_id, annotation["code"])
        candidates = anchors.get(key) or follow_ons.get(key, set())
        if len(candidates) == 1:
            identity[annotation_id] = next(iter(candidates))

    old_to_group = {
        f"W-{identifier[:12]}": identifier for identifier in groups
    }
    unresolved = []
    route_groups = []
    for source in sources:
        row = dict(source)
        source_refs = source["refs"]
        row["refs"] = [ref for ref in source_refs if ref not in identity]
        targets = {identity[ref] for ref in source_refs if ref in identity}
        for ref in source_refs:
            if ref in identity:
                target = groups[identity[ref]]
                target["refs"].append(ref)
                target["title"] = source["title"] if source["mode"] != "Crop review" else target["title"]

        reviewed = source["mode"] == "Crop review"
        matched = old_to_group.get(source["id"])
        if reviewed and len(targets) == 1:
            same_approach = [
                ref for ref in source_refs
                if ref in identity
                and direction_matches(source.get("h"), references[ref].get("h"))
                and distance(source.get("p"), references[ref].get("p")) <= 75
            ]
            if same_approach and len(same_approach) == len(source_refs):
                matched = next(iter(targets))
        elif matched is None and len(targets) == 1 and not row["refs"]:
            matched = next(iter(targets))
        if matched and targets - {matched}:
            matched = None

        if matched:
            target = groups[matched]
            for field in ("history", *PHONES):
                target[field].extend(row[field])
                row[field] = []
            for phone in PHONES:
                if source[phone]:
                    target["verdicts"][phone] = "Candidate match"
                elif source["id"].startswith("W-") and source["passages"].get(phone):
                    target["passages"][phone] = source["passages"][phone]
                    if not target[phone]:
                        target["verdicts"][phone] = "No matched read"
            if reviewed:
                target["title"] = source["title"]
                target["reviewCases"].append({
                    "title": source["title"],
                    "note": source["note"],
                    "verdicts": source["verdicts"],
                })
        elif targets:
            row["possible"] = sorted(targets)

        if any(row[field] for field in ("refs", "history", *PHONES)) or (reviewed and not matched):
            for phone in PHONES:
                if not row[phone] and matched:
                    row["verdicts"] = {**row["verdicts"], phone: "Unverified"}
            if reviewed and not matched:
                row["contextRefs"] = [ref for ref in source_refs if ref in identity]
                group = reviewed_route_group(row, source_refs, data["current"])
                if group:
                    route_groups.append(group)
                    continue
            unresolved.append(row)

    for group in groups.values():
        for case in group["reviewCases"]:
            for phone, verdict in case["verdicts"].items():
                group["verdicts"][phone] = verdict
    included = [group for group in groups.values() if any(
        group[field] for field in ("refs", "history", *PHONES)
    )]
    result = {**data, "groups": included + route_groups + unresolved}
    result["defaultGroup"] = next(
        (group["id"] for group in route_groups if "No saved read" in group["verdicts"].values()),
        (included + route_groups + unresolved)[0]["id"] if result["groups"] else None,
    )
    for field in ("refs", "history", *PHONES):
        before = Counter(item for row in sources for item in row[field])
        after = Counter(item for row in result["groups"] for item in row[field])
        if before != after or any(count != 1 for count in after.values()):
            raise ValueError(f"Evidence membership changed for {field}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--place", action="append", nargs=2, metavar=("CITY", "SNAPSHOT"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(dict(args.place)) != len(args.place):
        parser.error("Each place must have a unique city key.")
    data = json.loads(args.comparison.read_text())
    snapshots = {city: json.loads(Path(path).read_text()) for city, path in args.place}
    result = group_review(data, snapshots)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=args.output.parent, encoding="utf-8", delete=False
    ) as output:
        json.dump(result, output, ensure_ascii=False, separators=(",", ":"))
    os.replace(output.name, args.output)


if __name__ == "__main__":
    main()

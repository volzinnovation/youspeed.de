"""Keep drive evidence from simultaneous, same-direction Android and iPhone passages."""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile

from scripts.inspector.group_route_review import PHONES, direction_matches, distance, group_review

FIX_TIME_S = 5
FIX_DISTANCE_M = 25
EVIDENCE_DISTANCE_M = 35
MIN_SPEED_MPS = 1.5
MAX_SEGMENT_GAP_S = 6
APPLE_EPOCH_OFFSET = 978307200
LOCAL_TIME = timezone(timedelta(hours=1))


def bearing(start, end):
    longitude, latitude = start
    return math.degrees(math.atan2(
        (end[0] - longitude) * math.cos(math.radians(latitude)), end[1] - latitude
    )) % 360


def track(rows):
    result = []
    for index, (time, point, speed, heading) in enumerate(rows):
        if speed is None or speed < MIN_SPEED_MPS:
            continue
        if heading is None or not 0 <= heading < 360:
            left = rows[max(index - 2, 0)]
            right = rows[min(index + 2, len(rows) - 1)]
            if right[0] - left[0] > 7 or distance(left[1], right[1]) < 5:
                continue
            heading = bearing(left[1], right[1])
        result.append((time, point, heading))
    return result


def android_track(path):
    with ZipFile(path) as archive:
        journal = json.loads(archive.read("journal.json"))
    rows = []
    for event in journal["events"]:
        fix = event["payload"]
        if event["kind"] != "gps" or not fix.get("track_eligible") or (fix.get("accuracy") or 200) > 50:
            continue
        rows.append((event["time"], (fix["longitude"], fix["latitude"]), fix.get("speed"), fix.get("course")))
    return track(sorted(rows))


def iphone_track(path):
    rows = []
    with path.open() as file:
        for line in file:
            event = json.loads(line)
            fix = event.get("fix")
            if fix and fix.get("accuracy", 200) <= 50:
                rows.append((event["time"] + APPLE_EPOCH_OFFSET, (fix["longitude"], fix["latitude"]), fix.get("speed"), None))
    return track(sorted(rows))


def matching_fixes(primary, peer):
    peer_times = [fix[0] for fix in peer]
    for fix in primary:
        time, point, heading = fix
        first = bisect_left(peer_times, time - FIX_TIME_S)
        last = bisect_right(peer_times, time + FIX_TIME_S)
        if any(distance(point, other[1]) <= FIX_DISTANCE_M and direction_matches(heading, other[2])
               for other in peer[first:last]):
            yield fix


def continuous(fixes):
    result = []
    segment = []
    for fix in fixes:
        if segment and (fix[0] - segment[-1][0] > MAX_SEGMENT_GAP_S or distance(fix[1], segment[-1][1]) > 110):
            if len(segment) >= 3:
                result.append(segment)
            segment = []
        segment.append(fix)
    if len(segment) >= 3:
        result.append(segment)
    return result


def overlap_tracks(tracks):
    result = dict.fromkeys(PHONES)
    for phone, other in (PHONES, tuple(reversed(PHONES))):
        peer = sorted(fix for trip in tracks[other] for fix in trip)
        result[phone] = [segment for trip in tracks[phone] for segment in continuous(matching_fixes(trip, peer))]
    return result


def nearby(point, heading, fixes, *, radius=EVIDENCE_DISTANCE_M):
    return bool(point) and any(
        direction_matches(heading, fix[2]) and distance(point, fix[1]) <= radius for fix in fixes
    )


def in_phone_overlap(observation, segments):
    time = observation["t"]
    return any(
        segment[0][0] - 1 <= time <= segment[-1][0] + 1
        and nearby(observation["p"], observation.get("h"), (
            fix for fix in segment if abs(fix[0] - time) <= 3
        )) for segment in segments
    )


def in_historical_overlap(observation, fixes):
    heading = observation.get("h")
    return heading is not None and nearby(observation["p"], heading, fixes)


def overlap_pass(references, fixes):
    eligible = [
        (distance(reference["p"], fix[1]), fix[0])
        for reference in references if reference["h"] is not None and reference["p"]
        for fix in fixes if direction_matches(reference["h"], fix[2])
        and distance(reference["p"], fix[1]) <= 22
    ]
    if not eligible:
        return None
    meters, time = min(eligible)
    return {"m": round(meters, 1), "time": datetime.fromtimestamp(time, LOCAL_TIME).strftime("%H:%M:%S")}


def filter_overlap(data, shared):
    fixes = {phone: [fix for segment in shared[phone] for fix in segment] for phone in PHONES}
    if any(not fixes[phone] for phone in PHONES):
        raise ValueError("No simultaneous same-direction driving overlap was found.")
    current = {
        key: row for key, row in data["current"].items()
        if all(in_phone_overlap(row, shared[phone]) for phone in PHONES)
    }
    historical = {
        field: {
            key: row for key, row in data[field].items()
            if all(in_historical_overlap(row, fixes[phone]) for phone in PHONES)
        } for field in ("refs", "history")
    }
    groups = []
    for source in data["groups"]:
        row = {
            **source,
            **{phone: [key for key in source[phone] if key in current] for phone in PHONES},
            **{field: [key for key in source[field] if key in records] for field, records in historical.items()},
            "passages": {},
            "verdicts": {},
        }
        if not any(row[field] for field in (*PHONES, *historical)):
            continue
        retained = [current[key] for phone in PHONES for key in row[phone]]
        retained.extend(historical[field][key] for field in ("refs", "history") for key in row[field])
        camera = next(item for item in retained if item["p"])
        row.update(p=camera["p"], h=camera["h"])
        keeps_review = source["mode"] == "Crop review" and all(row[phone] == source[phone] for phone in PHONES)
        if keeps_review:
            row["verdicts"] = source["verdicts"]
        else:
            if source["mode"] == "Crop review":
                row.update(mode="Phone journal", note=None)
            references = [historical["refs"][key] for key in row["refs"]]
            for phone in PHONES:
                if row[phone]:
                    row["verdicts"][phone] = "Candidate match" if references or row["history"] else "Saved read"
                else:
                    passage = overlap_pass([ref for ref in references if ref["code"] != "yes"], fixes[phone])
                    if passage:
                        row["passages"][phone] = passage
                        row["verdicts"][phone] = "No matched read"
                    else:
                        row["verdicts"][phone] = "Unverified"
        groups.append(row)
    clipped = {
        **data, **historical, "current": current, "groups": groups,
        "tracks": [{"phone": phone, "lines": [[fix[1] for fix in segment] for segment in shared[phone]]} for phone in PHONES],
        "totals": {
            "phone": len(current), "mobile": len(historical["history"]), "panoramax": len(historical["refs"]),
            "crops": sum(len(row["crops"]) for row in historical["history"].values()),
        },
        "overlap": {
            "distanceKm": round(sum(distance(a[1], b[1]) for segment in shared["Android"]
                                     for a, b in zip(segment, segment[1:])) / 1000, 1),
            "segments": len(shared["Android"]),
            "maxFixTimeS": FIX_TIME_S,
            "maxFixDistanceM": FIX_DISTANCE_M,
            "evidenceDistanceM": EVIDENCE_DISTANCE_M,
        },
    }
    clipped.pop("additionalPhotos", None)
    clipped.pop("photoNote", None)
    return clipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--android", type=Path, action="append", required=True)
    parser.add_argument("--iphone", type=Path, action="append", required=True)
    parser.add_argument("--place", action="append", nargs=2, metavar=("CITY", "SNAPSHOT"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.comparison.read_text())
    snapshots = {city: json.loads(Path(path).read_text()) for city, path in args.place}
    shared = overlap_tracks({
        "Android": [android_track(path) for path in args.android],
        "iPhone": [iphone_track(path) for path in args.iphone],
    })
    clipped = filter_overlap(data, shared)
    result = group_review(clipped, snapshots)
    for group in result["groups"]:
        if group.get("inspectorId") and group["p"]:
            group["mapInScope"] = all(nearby(group["p"], None, [
                fix for segment in shared[phone] for fix in segment
            ]) for phone in PHONES)
    with tempfile.NamedTemporaryFile(mode="w", dir=args.output.parent, encoding="utf-8", delete=False) as output:
        json.dump(result, output, ensure_ascii=False, separators=(",", ":"))
    os.replace(output.name, args.output)


if __name__ == "__main__":
    main()

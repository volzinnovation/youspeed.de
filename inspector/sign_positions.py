"""Serve private static fit geometry only after current source requalification.

No backend Python package or unapplied migration is needed. Source hashes use
shared semantic-json-v1 vectors; current DB checks match crop source lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from uuid import UUID

MAX_BYTES = 64 * 1024**2
SOURCE_POLICY = "live-crops-only-v1"
MEMBER_FIELDS = {
    "installation_id",
    "collection_epoch",
    "crop_id",
    "observation_id",
    "encoded_sha256",
    "manifest_sha256",
    "observation_sha256",
    "review_revision",
}
CASE_FIELDS = {
    "label",
    "category",
    "point",
    "region",
    "clipped",
    "bounded",
    "prediction",
    "country",
    "time",
    "source",
    "roadIds",
    "nearestRoad",
    "roadDistance",
    "portals",
    "captureStatus",
    "captures",
    "scenarios",
    "classification",
    "speedLimit",
}
_NONLIVE = re.compile(r"replay|archive|simulat", re.I)
_SESSION = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
)
HASH = re.compile(r"[a-f0-9]{64}")


class SignPositionsError(Exception):
    def __init__(self, message="Schildpositionen derzeit nicht verfügbar.", status=503):
        self.status = status
        super().__init__(message)


def canonical(value):
    """Backend semantic-json-v1; shared golden vectors are the parity contract."""

    def encode(item):
        if item is None or isinstance(item, (str, bool)):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, (int, float)):
            if isinstance(item, int) and abs(item) > 9007199254740991:
                raise ValueError("unsafe_integer")
            if not math.isfinite(item):
                raise ValueError("nonfinite")
            if item == 0:
                return "0"
            number = Decimal(str(item)).normalize()
            if Decimal("1e-6") <= abs(number) < Decimal("1e21"):
                return format(number, "f")
            mantissa, exponent = format(number, "e").split("e")
            return (
                mantissa
                + "e"
                + ("+" if int(exponent) >= 0 else "-")
                + str(abs(int(exponent)))
            )
        if isinstance(item, list):
            return "[" + ",".join(encode(x) for x in item) + "]"
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            return (
                "{"
                + ",".join(encode(k) + ":" + encode(item[k]) for k in sorted(item))
                + "}"
            )
        raise ValueError("invalid_json")

    return encode(value).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identity(member):
    for name in ("installation_id", "crop_id", "observation_id"):
        value = member[name]
        if (
            not isinstance(value, str)
            or str(UUID(value)) != value
            or UUID(value).version != 4
        ):
            raise ValueError("invalid_identity")
    epoch = member["collection_epoch"]
    if type(epoch) is not int or not 0 <= epoch <= 2147483647:
        raise ValueError("invalid_epoch")
    return member["installation_id"], epoch, member["crop_id"]


def live_source(manifest, observation):
    """Mirror backend live-crops-only-v1 where migration005 is unavailable."""
    if not isinstance(manifest, dict) or not isinstance(observation, dict):
        return False
    if not isinstance(manifest.get("observation_id"), str) or manifest[
        "observation_id"
    ] != observation.get("event_id"):
        return False
    if manifest.get("local_frame_token") is not None and not isinstance(
        manifest["local_frame_token"], str
    ):
        return False
    app, evidence = observation.get("app"), observation.get("evidence")
    if not isinstance(app, dict) or not isinstance(evidence, dict):
        return False
    flags = evidence.get("quality_flags")
    if not isinstance(flags, list) or not all(isinstance(x, str) for x in flags):
        return False
    markers = [
        manifest.get("local_frame_token"),
        observation.get("observer_version"),
        app.get("version"),
        app.get("build"),
        *flags,
    ]
    if any(isinstance(x, str) and _NONLIVE.search(x) for x in markers):
        return False
    return (
        manifest.get("source_kind") in ("detector", "manual_capture")
        and manifest["source_kind"] == observation.get("source_kind")
        and observation.get("observer_version") == "sighting-observer-1"
        and app.get("platform") in ("ios", "android")
        and all(isinstance(app.get(k), str) and app[k] for k in ("version", "build"))
        and isinstance(observation.get("collection_session_id"), str)
        and bool(_SESSION.fullmatch(observation["collection_session_id"]))
    )


def speed_limit(case):
    c = case.get("classification")
    return (
        isinstance(c, dict)
        and c.get("family") in ("maximum_speed", "zone_start")
        and type(c.get("value")) in (int, float)
        and math.isfinite(c["value"])
        and c["value"] > 0
        and c.get("unit") == "km/h"
    )


def bounded(value, depth=0):
    if depth > 24:
        raise ValueError("depth")
    if isinstance(value, dict):
        if len(value) > 256 or any(len(k) > 160 for k in value):
            raise ValueError("object")
        for v in value.values():
            bounded(v, depth + 1)
    elif isinstance(value, list):
        if len(value) > 200000:
            raise ValueError("array")
        for v in value:
            bounded(v, depth + 1)
    elif isinstance(value, str) and len(value) > 4096:
        raise ValueError("text")
    elif type(value) in (int, float) and (
        abs(value) > 1e100 or not math.isfinite(value)
    ):
        raise ValueError("number")


def references(case):
    refs = list(case["roadIds"])
    if case["nearestRoad"] is not None:
        refs.append(case["nearestRoad"])
    for portal in case["portals"]:
        refs.extend(portal["mainline"])
        refs.extend(portal[k] for k in ("incoming", "link") if portal[k] is not None)
    return refs


def load(path):
    if path is None:
        raise SignPositionsError("Datei für Schildpositionen ist nicht eingerichtet.")
    try:
        path = Path(path)
        # A private artifact must never fall under the Inspector static root.
        if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("file_must_be_external")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
                raise ValueError("file_size")
            raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("file_size")

        def pairs(items):
            result = {}
            for k, v in items:
                if k in result:
                    raise ValueError("duplicate_key")
                result[k] = v
            return result

        def invalid(_):
            raise ValueError("nonfinite")

        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        bounded(value)
        if (
            set(value)
            != {"schema_version", "source_policy", "display_data", "case_bindings"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["source_policy"] != SOURCE_POLICY
        ):
            raise ValueError("wrapper")
        display, bindings = value["display_data"], value["case_bindings"]
        if (
            set(display) != {"version", "cases", "roadClasses", "roads", "meta"}
            or type(display["version"]) is not int
            or display["version"] != 1
            or not isinstance(display["meta"], dict)
        ):
            raise ValueError("display")
        cases, roads = display["cases"], display["roads"]
        if (
            not isinstance(cases, list)
            or not 0 <= len(cases) <= 5000
            or not isinstance(roads, list)
            or len(roads) > 100000
            or not isinstance(bindings, list)
            or len(bindings) != len(cases)
        ):
            raise ValueError("population")
        labels = set()
        for case in cases:
            label = case["label"]
            if (
                not isinstance(label, str)
                or not 0 < len(label) <= 80
                or label in labels
                or set(case) - CASE_FIELDS
            ):
                raise ValueError("case_label_or_fields")
            labels.add(label)
            for i in references(case):
                if type(i) is not int or not 0 <= i < len(roads):
                    raise ValueError("road_reference")
        for road in roads:
            if (
                not isinstance(road, list)
                or len(road) != 5
                or type(road[1]) is not int
                or not 0 <= road[1] < len(display["roadClasses"])
            ):
                raise ValueError("road")
        sources, seen = {}, set()
        for binding in bindings:
            if (
                set(binding) != {"label", "source_members"}
                or binding["label"] not in labels
                or binding["label"] in seen
            ):
                raise ValueError("case_binding")
            seen.add(binding["label"])
            members = binding["source_members"]
            if not isinstance(members, list) or not 1 <= len(members) <= 256:
                raise ValueError("dependencies")
            local = set()
            for member in members:
                if set(member) != MEMBER_FIELDS:
                    raise ValueError("member_fields")
                key = identity(member)
                if key in local or key in sources and sources[key] != member:
                    raise ValueError("duplicate_or_conflicting_member")
                local.add(key)
                for field in (
                    "encoded_sha256",
                    "manifest_sha256",
                    "observation_sha256",
                ):
                    if not isinstance(member[field], str) or not HASH.fullmatch(
                        member[field]
                    ):
                        raise ValueError("member_hash")
                if (
                    type(member["review_revision"]) is not int
                    or not 0 <= member["review_revision"] < 2**53
                ):
                    raise ValueError("review_revision")
                sources[key] = member
        if len(sources) > 10000:
            raise ValueError("source_cap")
        return display, {b["label"]: b["source_members"] for b in bindings}
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        UnicodeError,
        OverflowError,
    ):
        raise SignPositionsError(
            "Datei für Schildpositionen fehlt oder ist ungültig."
        ) from None


def eligible(row, member):
    try:
        manifest, observation = row["manifest"], row["observation"]
        key = identity(member)
        if (row["installation"], row["epoch"], row["crop_id"]) != key:
            return False
        return (
            live_source(manifest, observation)
            and (
                manifest.get("installation_id"),
                manifest.get("collection_epoch"),
                manifest.get("crop_id"),
            )
            == key
            and manifest.get("observation_id") == member["observation_id"]
            and row["digest"]
            == manifest.get("encoded_sha256")
            == member["encoded_sha256"]
            and digest(manifest) == member["manifest_sha256"]
            and digest(observation) == member["observation_sha256"]
            and row["current_revision"] == member["review_revision"]
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def prune(display, labels, checked_at, available_until):
    result = deepcopy(display)
    result["cases"] = [
        c for c in result["cases"] if c["label"] in labels and speed_limit(c)
    ]
    used = sorted({i for c in result["cases"] for i in references(c)})
    remap = {old: new for new, old in enumerate(used)}
    result["roads"] = [result["roads"][i] for i in used]
    for case in result["cases"]:
        case["roadIds"] = [remap[i] for i in case["roadIds"]]
        if case["nearestRoad"] is not None:
            case["nearestRoad"] = remap[case["nearestRoad"]]
        for p in case["portals"]:
            p["mainline"] = [remap[i] for i in p["mainline"]]
            for name in ("incoming", "link"):
                if p[name] is not None:
                    p[name] = remap[p[name]]
        c = case["classification"]
        case["speedLimit"] = {k: c[k] for k in ("family", "value", "unit")}

    def utc(value):
        return (
            datetime.fromtimestamp(value, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if value is not None
            else None
        )

    result["meta"].update(
        {
            "scope": "maximum_speed_and_zone_start",
            "lifecycleCheckedAt": utc(checked_at),
            "availableUntil": utc(available_until),
            "totalEligibleFits": len(result["cases"]),
            "withheldFits": len(display["cases"]) - len(result["cases"]),
        }
    )
    return result


class SignPositionStore:
    def __init__(self, path, crop_store):
        self.path, self.crop_store = path, crop_store

    def get(self):
        display, bindings = load(self.path)  # Reread atomic external replacements.
        cases = [c for c in display["cases"] if speed_limit(c)]
        sources = {identity(m): m for c in cases for m in bindings[c["label"]]}
        with self.crop_store.connection() as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self.crop_store.require_live_controls(db)
            capability = db.execute(
                "SELECT to_regclass('youspeed.crop_reviews')::text AS reviews"
            ).fetchone()
            # If present but not readable, the query fails closed through connection().
            review_select = "COALESCE(r.revision,0)" if capability["reviews"] else "0"
            review_join = (
                """LEFT JOIN LATERAL (SELECT revision FROM youspeed.crop_reviews rr
              WHERE rr.installation=m.installation AND rr.epoch=m.epoch AND rr.crop_id=m.crop_id
              ORDER BY revision DESC LIMIT 1) r ON true"""
                if capability["reviews"]
                else ""
            )
            current = {}
            keys = sorted(sources)
            for start in range(0, len(keys), 500):
                chunk = keys[start : start + 500]
                markers = ",".join(["(%s::uuid,%s::int,%s::uuid)"] * len(chunk))
                sql = (
                    """SELECT m.installation::text AS installation,m.epoch,m.crop_id::text AS crop_id,
                  m.digest,m.manifest,m.expires,e.payload->'event' AS observation,"""
                    + review_select
                    + """ AS current_revision
                  FROM youspeed.media m JOIN (VALUES """
                    + markers
                    + """) k(installation,epoch,crop_id)
                  USING(installation,epoch,crop_id)
                  LEFT JOIN youspeed.events e ON e.installation=m.installation AND e.epoch=m.epoch
                  AND e.event_id::text=m.manifest->>'observation_id' AND e.kind='sighting'
                  """
                    + review_join
                    + """ WHERE m.expires>extract(epoch FROM now())
                  AND NOT EXISTS (SELECT 1 FROM youspeed.tombstones t WHERE t.installation=m.installation AND t.deleted_through>=m.epoch)
                  AND EXISTS (SELECT 1 FROM youspeed.authorizations a WHERE a.installation=m.installation AND a.epoch=m.epoch AND a.scope='sign_metadata' AND a.state='granted')
                  AND EXISTS (SELECT 1 FROM youspeed.authorizations a WHERE a.installation=m.installation AND a.epoch=m.epoch AND a.scope='crop_storage' AND a.state='granted')"""
                )
                rows = db.execute(sql, [v for k in chunk for v in k]).fetchall()
                current.update(
                    {(r["installation"], r["epoch"], r["crop_id"]): r for r in rows}
                )
            # Use wall-clock DB time also at completion, so expired-during-read data vanishes.
            clock = db.execute(
                "SELECT extract(epoch FROM clock_timestamp())::double precision AS checked_at, (SELECT refreshed_at FROM youspeed.control_state WHERE singleton) AS controls_refreshed_at"
            ).fetchone()
            now = clock["checked_at"]
            control_until = clock["controls_refreshed_at"] + 900
            if not math.isfinite(now) or not now < control_until:
                raise SignPositionsError(
                    "Schildpositionen warten auf aktuelle Freigabe- und Löschkontrollen."
                )
            valid = {
                k
                for k, r in current.items()
                if k in sources and r["expires"] > now and eligible(r, sources[k])
            }
            labels = {
                c["label"]
                for c in cases
                if all(identity(m) in valid for m in bindings[c["label"]])
            }
            retained = {identity(m) for label in labels for m in bindings[label]}
            until = min([control_until, *(current[k]["expires"] for k in retained)])
        return prune(display, labels, now, until)

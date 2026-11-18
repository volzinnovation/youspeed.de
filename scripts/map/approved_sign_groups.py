"""Import Inspector-approved sign groups into a region's source inventory."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from audit_city_context import point_in_ring
from traffic_sign_inventory import SCHEMA, canonical, number


SOURCE_ID = "streetshots-approved"
LIVE_BUNDLE = "baden-wuerttemberg"
ROOT = Path(__file__).resolve().parents[2]
LIVE_SSH_CONFIG = (ROOT / "mapdata/build"
                   / "baden-wuerttemberg-inspector-approvals/ssh_config")
RUNTIME_SCHEMA = ROOT / "mapdata/spec/traffic_sign_runtime_v1.sql"
ARTWORK_MANIFEST = ROOT / "shared/tsr/sign-pictograms/manifest.json"
SELECT_APPROVED = """SELECT group_id, revision, sign_code, longitude, latitude, front_azimuth_deg
                     FROM sign_group_approvals WHERE approved=1 AND bundle=? ORDER BY group_id"""
LIVE_EXPORT_COMMAND = ("docker exec youspeed-public-inspector-inspector-1 "
                       f"python -m inspector.export_sign_groups {LIVE_BUNDLE}")
# Keep the code forms aligned with the Streetshots Inspector approval editor.
SIGN_CODE = re.compile(
    r"(?:DE:[0-9]{3,4}(?:[.-][0-9]{1,3})*(?:,[0-9]{1,3})?"
    r"|(?:BE|CH|FR|NL):[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)(?:\[[0-9]{1,4}(?:[.,][0-9]{1,3})?\])?"
)


def read_approved(database, region):
    if database.suffix.lower() == ".json":
        return validate_export(json.loads(database.read_text()), region)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(SELECT_APPROVED, (region,))]
    return validate_rows(rows)


def read_live_approved():
    """Read one snapshot of the live Baden-Württemberg approvals on the build runner."""
    if not LIVE_SSH_CONFIG.is_file():
        raise ValueError(f"Missing Inspector approval SSH configuration: {LIVE_SSH_CONFIG}. "
                         "Configure the build runner or pass --approved-sign-groups with a pinned snapshot.")
    try:
        response = subprocess.run(
            ["ssh", "-F", str(LIVE_SSH_CONFIG), "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "-o", "StrictHostKeyChecking=yes", "streetshots-inspector-approvals", LIVE_EXPORT_COMMAND],
            stdout=subprocess.PIPE, text=True, timeout=25, check=True,
        )
        envelope = json.loads(response.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise ValueError(f"Could not fetch live Inspector approvals for {LIVE_BUNDLE}") from error
    return validate_export(envelope, LIVE_BUNDLE)


def validate_export(envelope, region):
    if (not isinstance(envelope, dict) or envelope.get("schema_version") != 1
            or envelope.get("region") != region or not isinstance(envelope.get("rows"), list)):
        raise ValueError("Unexpected Inspector approval export schema or region")
    return validate_rows(envelope["rows"])


def validate_rows(rows):
    for row in rows:
        if (not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", row["group_id"])
                or not re.fullmatch(r"[a-f0-9]{64}", row["revision"])
                or not SIGN_CODE.fullmatch(row["sign_code"])):
            raise ValueError("Invalid approved sign group")
        number(row["longitude"], "longitude", -180, 180)
        number(row["latitude"], "latitude", -90, 90)
        number(row["front_azimuth_deg"], "front azimuth", 0, 360, optional=True)
    return rows


def revision(rows):
    return hashlib.sha256(canonical(rows).encode()).hexdigest()


def coverage_rings(poly):
    lines = iter(poly.read_text().splitlines())
    next(lines, None)
    rings = []
    for label in (line.strip() for line in lines):
        if label == "END":
            break
        if not label:
            continue
        ring = []
        for line in lines:
            if line.strip() == "END":
                break
            lon, lat = map(float, line.split())
            ring.append((number(lon, "longitude", -180, 180), number(lat, "latitude", -90, 90)))
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError("Invalid release coverage ring")
        rings.append((label.startswith("!"), ring))
    return rings


def already_imported(db):
    if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='traffic_sign_source'").fetchone():
        return False
    return db.execute("SELECT 1 FROM traffic_sign_source WHERE source_id=?", (SOURCE_ID,)).fetchone() is not None


def published_index(db):
    """Record the exact approval revisions present in the final bundle inventory."""
    rows = []
    if already_imported(db):
        for group, code, lon, lat, raw in db.execute("""
            SELECT record_key, sign_code, longitude, latitude, raw_properties_json
            FROM traffic_sign_inventory WHERE source_id=? ORDER BY record_key
        """, (SOURCE_ID,)):
            properties = json.loads(raw)
            rows.append({"group_id": group, "revision": properties["review_revision"], "sign_code": code,
                         "longitude": lon, "latitude": lat, "front_azimuth_deg": properties["front_azimuth_deg"]})
    validate_rows(rows)
    return {"revision": revision(rows), "count": len(rows),
            "groups": {row["group_id"]: row["revision"] for row in rows}}


def refresh_display_inventory(db, rows, sha):
    """Materialize approved positions as secondary signs without a road rule."""
    tables = {name for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    if "traffic_sign_runtime" not in tables:
        directed = db.execute("SELECT 1 FROM traffic_sign_inventory WHERE source_id<>? LIMIT 1", (SOURCE_ID,)).fetchone()
        if not rows or directed:
            return
        for statement in RUNTIME_SCHEMA.read_text().split(";"):
            if statement.strip():
                db.execute(statement)
        db.executemany("INSERT INTO traffic_sign_capability VALUES (?, ?)",
                       [("version", "1"), ("inventory_scope", "display_only")])
    db.execute("""DELETE FROM traffic_sign_association WHERE sign_id IN
        (SELECT sign_id FROM traffic_sign_runtime WHERE source_id=?)""", (SOURCE_ID,))
    db.execute("DELETE FROM traffic_sign_runtime WHERE source_id=?", (SOURCE_ID,))
    if not rows:
        return
    artwork = {item["sign_code"]: "tsr/sign-pictograms/" + item["png_path"]
               for item in json.loads(ARTWORK_MANIFEST.read_text())["artworks"]}
    for row in rows:
        group, code = row["group_id"], row["sign_code"]
        sign_id = f"{SOURCE_ID}:{group}"
        front = row["front_azimuth_deg"]
        path = artwork.get(code)
        db.execute("""INSERT INTO traffic_sign_runtime VALUES
            (?,?,?,?,?,?,'secondary',NULL,NULL,'inspector_inventory_only',?,?,?,?,?,?,'[]')""",
            (sign_id, SOURCE_ID, group, sha, code, code, row["longitude"], row["latitude"],
             (front + 180) % 360 if front is not None else None, 30 if code in {"DE:310", "DE:311"} else 10,
             code if path else None, path))
        db.execute("""INSERT INTO traffic_sign_association VALUES
            (?, 'inventory_only', NULL, NULL, NULL, NULL, NULL, '{}')""", (sign_id,))


def import_approved(db, rows, coverage):
    """Replace this source with the current approval set, including revocations."""
    if rows:
        rings = coverage_rings(coverage)
        for row in rows:
            point = (row["longitude"], row["latitude"])
            depth = sum(-1 if hole else 1 for hole, ring in rings if point_in_ring(point, ring))
            if depth <= 0:
                raise ValueError(f"Approved sign group is outside this release: {row['group_id']}")
    if not rows and not already_imported(db):
        return 0
    db.execute("SAVEPOINT approved_inventory")
    try:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                db.execute(statement)
        db.execute("""DELETE FROM traffic_sign_inventory_rtree WHERE row_id IN
                      (SELECT row_id FROM traffic_sign_inventory WHERE source_id=?)""", (SOURCE_ID,))
        db.execute("DELETE FROM traffic_sign_inventory WHERE source_id=?", (SOURCE_ID,))
        db.execute("DELETE FROM traffic_sign_source WHERE source_id=?", (SOURCE_ID,))
        sha = revision(rows)
        if rows:
            xs, ys = [row["longitude"] for row in rows], [row["latitude"] for row in rows]
            db.execute("INSERT INTO traffic_sign_source VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (SOURCE_ID, "StreetShots", "", "", "", "", sha, None, len(rows),
                        min(xs), min(ys), max(xs), max(ys), "inventory_only",
                        "Admin-approved groups from the Inspector"))
            for row in rows:
                group = row["group_id"]
                x, y = row["longitude"], row["latitude"]
                front = row["front_azimuth_deg"]
                approach = (front + 180) % 360 if front is not None else None
                cursor = db.execute("""INSERT INTO traffic_sign_inventory
                    (source_id, record_key, group_id, location_id, sign_code, longitude, latitude,
                     orientation_deg, raw_properties_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (SOURCE_ID, group, group, group, row["sign_code"], x, y, approach,
                     canonical({"review_revision": row["revision"], "front_azimuth_deg": front})))
                db.execute("INSERT INTO traffic_sign_inventory_rtree VALUES (?, ?, ?, ?, ?)",
                           (cursor.lastrowid, x, x, y, y))
        refresh_display_inventory(db, rows, sha)
        db.execute("RELEASE approved_inventory")
        return len(rows)
    except BaseException:
        db.execute("ROLLBACK TO approved_inventory")
        db.execute("RELEASE approved_inventory")
        raise

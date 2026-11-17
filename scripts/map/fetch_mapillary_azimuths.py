#!/usr/bin/env python3
"""Cache missing Mapillary sign bearings for explicitly selected bundle feature IDs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from http.client import HTTPSConnection, HTTPException
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock, local
import time
from urllib.parse import urlencode

GRAPH_HOST = "graph.mapillary.com"
BATCH_SIZE = 50
CACHE_PATH = Path(__file__).resolve().parents[2] / "output/mapillary/azimuth-cache.sqlite"
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS mapillary_azimuth (
    feature_id TEXT NOT NULL,
    feature_class TEXT NOT NULL,
    aligned_direction REAL NOT NULL CHECK(aligned_direction >= 0 AND aligned_direction < 360),
    PRIMARY KEY (feature_id, feature_class)
)
"""
SIGN_SQL = """
SELECT orientation_deg, json_extract(raw_properties_json, '$.value')
FROM traffic_sign_inventory
WHERE source_id = 'mapillary-eval' AND record_key = ?
"""


def provider_azimuth(value):
    return value if type(value) in (int, float) and 0 <= value < 360 else None


def read_azimuth_cache(path):
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return {(key, feature_class): angle for key, feature_class, angle in db.execute(
            "SELECT feature_id, feature_class, aligned_direction FROM mapillary_azimuth"
        )}


class GraphLookup:
    def __init__(self, token, request_interval=0):
        self.token = token
        self.thread = local()
        self.connections = []
        self.request_interval = request_interval
        self.request_lock = Lock()
        self.next_request = 0

    def close(self):
        for connection in self.connections:
            connection.close()

    def __call__(self, ids):
        if not self.token:
            raise ValueError("Set MAPILLARY_ACCESS_TOKEN for the Graph lookup")
        if not hasattr(self.thread, "connection"):
            self.thread.connection = HTTPSConnection(GRAPH_HOST, timeout=30)
            self.connections.append(self.thread.connection)
        connection = self.thread.connection
        fields = urlencode({"ids": ",".join(ids), "fields": "id,object_type,object_value,aligned_direction"})
        for delay in (1, 3, None):
            try:
                with self.request_lock:
                    time.sleep(max(0, self.next_request - time.monotonic()))
                    self.next_request = time.monotonic() + self.request_interval
                connection.request("GET", "/?" + fields, headers={"Authorization": f"OAuth {self.token}"})
                with connection.getresponse() as response:
                    status = response.status
                    retry_after = response.getheader("Retry-After", "")
                    raw = response.read()
                if status == 429:
                    wait = f", retry after {retry_after} s" if retry_after.isdecimal() else ""
                    raise RuntimeError(f"Mapillary Graph rate limit (HTTP 429{wait})")
                if status >= 500 and delay is not None:
                    time.sleep(delay)
                    continue
                if status != 200:
                    code = None
                    try:
                        error = json.loads(raw).get("error")
                        code = error.get("code") if isinstance(error, dict) else None
                    except (AttributeError, ValueError):
                        pass
                    suffix = f", Graph error {code}" if type(code) is int else ""
                    raise RuntimeError(f"Mapillary Graph returned HTTP {status}{suffix}")
                payload = json.loads(raw)
            except (OSError, HTTPException) as error:
                connection.close()
                if delay is None:
                    raise RuntimeError(f"Mapillary Graph lookup failed ({type(error).__name__})") from None
                time.sleep(delay)
                continue
            if not isinstance(payload, dict) or "error" in payload:
                raise RuntimeError("Mapillary Graph returned an error response")
            return payload


def fetch_batches(pending, fetch, workers, batch_size):
    if workers == 1:
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            yield batch, fetch(batch)
        return
    window = workers * batch_size
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(pending), window):
            batches = [pending[offset:offset + batch_size]
                       for offset in range(start, min(start + window, len(pending)), batch_size)]
            inflight = {pool.submit(fetch, batch): batch for batch in batches}
            failure = None
            for future in as_completed(inflight):
                try:
                    response = future.result()
                except (OSError, RuntimeError, ValueError) as error:
                    failure = error
                    continue
                yield inflight[future], response
            if failure:
                raise failure


def enrich(db, cache, ids, fetch, workers=1, batch_size=BATCH_SIZE):
    target = {}
    for key in ids:
        row = db.execute(SIGN_SQL, (key,)).fetchone()
        if row is None:
            raise ValueError(f"Feature ID {key} is outside the bundle's Mapillary inventory")
        existing_angle, feature_class = row
        if not isinstance(feature_class, str) or not feature_class:
            raise ValueError(f"Feature ID {key} has no Mapillary source class")
        if existing_angle is None and cache.execute(
            "SELECT 1 FROM mapillary_azimuth WHERE feature_id=? AND feature_class=?", (key, feature_class)
        ).fetchone() is None:
            target[key] = feature_class

    pending = list(target)
    totals = {"selected": len(ids), "already_available": len(ids) - len(pending),
              "requested": 0, "cached": 0, "unresolved": 0}
    for batch, response in fetch_batches(pending, fetch, workers, batch_size):
        observations = []
        for key in batch:
            feature = response.get(key)
            if not isinstance(feature, dict) or str(feature.get("id")) != key:
                continue
            angle = provider_azimuth(feature.get("aligned_direction"))
            if (feature.get("object_type") == "trafficsign" and feature.get("object_value") == target[key]
                    and angle is not None):
                observations.append((key, target[key], angle))
        with cache:
            cache.executemany("INSERT OR IGNORE INTO mapillary_azimuth VALUES (?, ?, ?)", observations)
        totals["requested"] += len(batch)
        totals["cached"] += len(observations)
        totals["unresolved"] += len(batch) - len(observations)
        if totals["requested"] % 5000 < len(batch) or totals["requested"] == len(pending):
            print(f"Processed {totals['requested']}/{len(pending)} IDs; "
                  f"{totals['cached']} bearings available, {totals['unresolved']} unresolved", flush=True)
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Unpacked bundle source SQLite database")
    parser.add_argument("--ids-file", required=True, type=Path, help="Text file with one Mapillary feature ID per line")
    parser.add_argument("--cache", default=CACHE_PATH, type=Path, help="SQLite cache consumed by the local bundle builder")
    parser.add_argument("--workers", default=1, type=int, choices=range(1, 5), help="Concurrent Graph requests")
    parser.add_argument("--batch-size", default=BATCH_SIZE, type=int, metavar="N", help="Feature IDs per request (1–350)")
    parser.add_argument("--request-interval", default=0, type=float, metavar="SECONDS",
                        help="Minimum time between Graph request starts across workers")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 350:
        parser.error("--batch-size must be between 1 and 350")
    if not 0 <= args.request_interval <= 60:
        parser.error("--request-interval must be between 0 and 60 seconds")
    try:
        ids = list(dict.fromkeys(args.ids_file.read_text().split()))
        if not ids or any(re.fullmatch(r"[0-9]{1,24}", key) is None for key in ids):
            raise ValueError("Expected a nonempty list of decimal Mapillary feature IDs")
        token = os.environ.get("MAPILLARY_ACCESS_TOKEN", "").strip()
        if args.cache.exists() and args.cache.samefile(args.db):
            raise ValueError("Choose a cache separate from the bundle source database")
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        with (closing(GraphLookup(token, args.request_interval)) as graph,
              closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as db,
              closing(sqlite3.connect(args.cache, timeout=30)) as cache):
            cache.execute(CACHE_SCHEMA)
            print(json.dumps(enrich(db, cache, ids, graph, args.workers, args.batch_size)))
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()

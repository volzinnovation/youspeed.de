#!/usr/bin/env python3
"""Reversibly replace only Inspector code and its private static position input."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import stat
import sys
import tempfile
import time
from urllib.parse import quote
from urllib.request import urlopen

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
NAME = "youspeed-inspector"
CODE_TARGET = "/opt/youspeed-inspector"
DATA_TARGET = "/run/youspeed-inspector/sign-positions.json"
INSTALL_ROOT = Path("/srv/youspeed-inspector")
MAX_DATA = 64 * 1024**2


class UpdateError(Exception):
    """Contains only operator-safe messages, never Docker/env/HTTP bodies."""


class UpdateInterrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum


class Docker:
    def __init__(self, path="/var/run/docker.sock"):
        self.path = path

    def request(self, method, path, body=None, missing=False):
        connection = http.client.HTTPConnection("localhost", timeout=30)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(30)
        try:
            connection.sock.connect(self.path)
            raw = None if body is None else json.dumps(body).encode()
            connection.request(method, path, raw, {"Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(8 * 1024**2 + 1)
            if response.status == 404 and missing:
                return None
            if not 200 <= response.status < 300 or len(data) > 8 * 1024**2:
                raise UpdateError("Docker operation failed; no private response details printed.")
            return json.loads(data) if data else None
        except (OSError, ValueError, http.client.HTTPException):
            raise UpdateError("Docker unavailable or response invalid; administrator access is required.") from None
        finally:
            connection.close()

    def inspect(self, identity=NAME, missing=False):
        return self.request("GET", "/containers/" + quote(identity, safe="") + "/json", missing=missing)


def read_regular(path, maximum):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise UpdateError("Symlink input or parent rejected.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise UpdateError("Input is not a bounded regular file.")
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise UpdateError("Input exceeds the allowed size.")
    return data, info


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_package(root):
    raw, _ = read_regular(root / "inspector-deployment.json", 1024**2)
    manifest = json.loads(raw)
    if set(manifest) != {"release", "files"} or not isinstance(manifest["files"], dict):
        raise UpdateError("Invalid package manifest.")
    files = manifest["files"]
    if not 1 <= len(files) <= 1000 or manifest["release"] != sha(json.dumps(files, sort_keys=True).encode())[:16]:
        raise UpdateError("Invalid content-addressed release identity.")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if (not name or relative.is_absolute() or ".." in relative.parts or str(relative) != name
                or not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected)):
            raise UpdateError("Unsafe package path or hash.")
        data, _ = read_regular(root / name, 32 * 1024**2)
        if sha(data) != expected:
            raise UpdateError("Package file hash mismatch.")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise UpdateError("Nonregular package member rejected.")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(files) | {"inspector-deployment.json"}:
        raise UpdateError("Package contains unmanifested files.")
    for name in ("inspector/server.py", "inspector/sign_positions.py", "scripts/inspector/update-volz-db.py"):
        if name not in files:
            raise UpdateError("Package lacks a required update component.")
    return manifest


def private_input(path):
    raw, info = read_regular(path, MAX_DATA)
    if info.st_mode & 0o077:
        raise UpdateError("Private input must not be readable by group or others (use mode0600).")
    sys.path.insert(0, str(ROOT))
    from inspector.sign_positions import load, speed_limit
    display, _ = load(path)  # Offline validation only; no DB or server writes.
    if not display["cases"] or not all(speed_limit(case) for case in display["cases"]):
        raise UpdateError("Private input must contain only numeric maximum-speed/zone-start cases.")
    if read_regular(path, MAX_DATA)[0] != raw:
        raise UpdateError("Private input changed during validation.")
    return raw, {case["label"]: {k: case["classification"][k] for k in ("family", "value", "unit")} for case in display["cases"]}


def fingerprint(current):
    return sha(json.dumps({k: current[k] for k in ("Id", "Image", "Config", "HostConfig")}, sort_keys=True).encode()
                + json.dumps(current["NetworkSettings"]["Networks"], sort_keys=True).encode())


def make_plan(current, release, data_sha, operation):
    config, host = deepcopy(current["Config"]), deepcopy(current["HostConfig"])
    if (current["Name"] != "/" + NAME or config.get("Labels", {}).get("de.youspeed.component") != "inspector"
            or current["State"].get("Running") is not True or not re.fullmatch("sha256:[0-9a-f]{64}", current["Image"])):
        raise UpdateError("Expected the running, labelled Inspector with an exact local image ID.")
    if (not host.get("ReadonlyRootfs") or host.get("Privileged") or host.get("AutoRemove") or "ALL" not in host.get("CapDrop", [])
            or not any(x in ("no-new-privileges", "no-new-privileges:true") for x in host.get("SecurityOpt", []))
            or not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", config.get("User", ""))):
        raise UpdateError("Inspector security configuration is not the expected restricted configuration.")
    cmd = list(config.get("Cmd") or [])
    if cmd.count(CODE_TARGET + "/inspector/server.py") != 1 or cmd.count("--port") != 1:
        raise UpdateError("Inspector entry command/port is not recognizable.")
    try:
        port = int(cmd[cmd.index("--port") + 1])
    except (ValueError, IndexError):
        raise UpdateError("Invalid Inspector listening port.") from None
    bindings = host.get("PortBindings") or {}
    for entries in bindings.values():
        if not entries or any(e.get("HostIp") not in ("127.0.0.1", "::1") or not str(e.get("HostPort", "")).isdigit() for e in entries):
            raise UpdateError("Only explicit loopback published ports may be preserved.")
    ipv4 = [e for e in bindings.get(str(port) + "/tcp", []) if e["HostIp"] == "127.0.0.1"]
    if len(ipv4) != 1 or not 1024 <= int(ipv4[0]["HostPort"]) <= 65535 or host.get("PublishAllPorts"):
        raise UpdateError("Expected one explicit loopback HTTP port and no automatic port publishing.")
    # Preserve all mount options verbatim; only the known code/data bind sources change.
    if host.get("Binds") or host.get("VolumesFrom"):
        raise UpdateError("Legacy bind/volume inheritance needs administrator review; it cannot be silently reconstructed.")
    mounts = host.get("Mounts") or []
    represented = {m.get("Target") for m in mounts} | set(host.get("Tmpfs") or {})
    if any(m.get("Destination") not in represented for m in current.get("Mounts", [])):
        raise UpdateError("Unrepresented runtime mount needs administrator review; no anonymous replacement is allowed.")
    code = [m for m in mounts if m.get("Target") == CODE_TARGET]
    if len(code) != 1 or code[0].get("Type") != "bind" or code[0].get("ReadOnly") is not True:
        raise UpdateError("Expected one read-only Inspector code bind.")
    code[0]["Source"] = str(INSTALL_ROOT / "releases" / release)
    old_data = [m for m in mounts if m.get("Target") == DATA_TARGET]
    if len(old_data) > 1 or any(m.get("Type") != "bind" or not m.get("ReadOnly") for m in old_data):
        raise UpdateError("Unexpected existing private-data mount.")
    data_path = INSTALL_ROOT / "private" / ("sign-positions-" + data_sha + ".json")
    if old_data:
        old_data[0]["Source"] = str(data_path)
    else:
        mounts.append({"Type": "bind", "Source": str(data_path), "Target": DATA_TARGET, "ReadOnly": True})
    host["Mounts"] = mounts
    while "--sign-positions-file" in cmd:
        i = cmd.index("--sign-positions-file")
        if i + 1 == len(cmd):
            raise UpdateError("Malformed prior private-data argument.")
        del cmd[i:i + 2]
    cmd += ["--sign-positions-file", DATA_TARGET]
    config.update(Image=current["Image"], Cmd=cmd)
    config["Labels"].update({"de.youspeed.release": release, "de.youspeed.update-operation": operation})
    networks = deepcopy(current["NetworkSettings"]["Networks"])
    endpoints = {}
    for name, endpoint in networks.items():
        ipam = endpoint.get("IPAMConfig")
        if ipam and any(ipam.values()):
            raise UpdateError("Static network addressing needs a separate administrator cutover plan.")
        if endpoint.get("Links"):
            raise UpdateError("Legacy network links need a separate administrator cutover plan.")
        endpoints[name] = {key: deepcopy(endpoint[key]) for key in ("IPAMConfig", "Aliases", "DriverOpts", "GwPriority") if endpoint.get(key) is not None}
        # Docker-generated old container aliases are not configured service aliases.
        if "Aliases" in endpoints[name]:
            endpoints[name]["Aliases"] = [a for a in endpoints[name]["Aliases"] if a not in (current["Id"], current["Id"][:12])]
    primary = next((name for name, value in networks.items() if host.get("NetworkMode") in (name, value["NetworkID"])), None)
    if not networks or primary is None:
        raise UpdateError("Expected ordinary named Inspector networks.")
    body = {**config, "HostConfig": host, "NetworkingConfig": {"EndpointsConfig": {primary: endpoints[primary]}}}
    return {"old_id": current["Id"], "old_fingerprint": fingerprint(current), "backup_name": NAME + "-before-" + operation,
            "operation": operation, "release": release, "data_path": str(data_path), "data_sha256": data_sha,
            "gid": int(config["User"].split(":")[1]), "body": body,
            "extra_networks": [(networks[n]["NetworkID"], endpoints[n]) for n in sorted(networks) if n != primary],
            "network_names": sorted(networks), "base_url": "http://127.0.0.1:" + ipv4[0]["HostPort"]}


def stage_files(source, manifest, raw, plan):
    releases = INSTALL_ROOT / "releases"
    for directory in (INSTALL_ROOT, releases):
        if directory.is_symlink() or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o022:
            raise UpdateError("Release parent must be root-owned and not group/world writable.")
    destination = releases / manifest["release"]
    if destination.exists():
        if verify_package(destination) != manifest:
            raise UpdateError("Existing release differs from package.")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=".update-", dir=releases))
        try:
            for name in [*manifest["files"], "inspector-deployment.json"]:
                data = read_regular(source / name, 32 * 1024**2)[0]
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for path in [temporary, *temporary.rglob("*")]:
                os.chown(path, 0, 0)
                os.chmod(path, 0o755 if path.is_dir() else 0o644)
            if verify_package(temporary) != manifest:
                raise UpdateError("Copied release verification failed.")
            if destination.exists():
                raise UpdateError("Release appeared during staging.")
            os.rename(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    private = INSTALL_ROOT / "private"
    if not private.exists():
        private.mkdir(mode=0o700)
    if private.is_symlink() or private.stat().st_uid != 0 or private.stat().st_mode & 0o077:
        raise UpdateError("Private data directory must be root-owned mode0700.")
    path = Path(plan["data_path"])
    if path.exists():
        data, info = read_regular(path, MAX_DATA)
        if sha(data) != plan["data_sha256"] or info.st_uid != 0 or info.st_gid != plan["gid"] or info.st_mode & 0o777 != 0o440:
            raise UpdateError("Existing private data differs or has unsafe permissions.")
    else:
        fd, temporary = tempfile.mkstemp(prefix=".positions-", dir=private)
        temporary = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(temporary, 0, plan["gid"])
            os.chmod(temporary, 0o440)
            if sha(temporary.read_bytes()) != plan["data_sha256"] or path.exists():
                raise UpdateError("Private input changed during staging.")
            os.rename(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def verify_health(base, expected):
    def get(path):
        with urlopen(base + path, timeout=5) as response:
            if "no-store" not in {part.strip() for part in response.headers.get("Cache-Control", "").lower().split(",")}:
                raise UpdateError("Private health responses must prohibit caching.")
            data = response.read(MAX_DATA + 1)
            if len(data) > MAX_DATA:
                raise UpdateError("Health response too large.")
            return json.loads(data)
    status = get("/inspector/api/crops/status")
    if status.get("user") != "youspeed_report" or status.get("database") != "youspeed" or status.get("media_available") is not True:
        raise UpdateError("Report identity/media health check failed.")
    positions = get("/inspector/api/sign-positions")
    cases, meta = positions.get("cases"), positions.get("meta", {})
    if not isinstance(cases, list) or meta.get("scope") != "maximum_speed_and_zone_start" or meta.get("totalEligibleFits") != len(cases):
        raise UpdateError("Sign-position response contract failed.")
    try:
        expiry = datetime.fromisoformat(meta["availableUntil"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise UpdateError("Sign-position response has no future lifecycle deadline.") from None
    labels = [case.get("label") for case in cases]
    if len(set(labels)) != len(labels) or not set(labels) <= set(expected):
        raise UpdateError("Sign-position response population failed.")
    if any(case.get("speedLimit") != expected[case["label"]] for case in cases):
        raise UpdateError("Sign-position response is not the qualified speed-only population.")
    return {"eligible_speed_cases": len(cases), "source_speed_cases": len(expected)}


def perform_update(docker, plan, expected, health=verify_health, pause=time.sleep):
    old = docker.inspect()
    if fingerprint(old) != plan["old_fingerprint"] or old["State"].get("Running") is not True:
        raise UpdateError("Existing service changed since preflight; no switch performed.")
    if docker.inspect(plan["backup_name"], missing=True) is not None:
        raise UpdateError("Rollback name already exists; no switch performed.")
    managed_signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    handlers = {sig: signal.getsignal(sig) for sig in managed_signals}
    def interrupted(signum, _frame):
        raise UpdateInterrupted(signum)
    for sig in managed_signals:
        signal.signal(sig, interrupted)
    try:
        docker.request("POST", "/containers/" + plan["old_id"] + "/stop?t=20")
        docker.request("POST", "/containers/" + plan["old_id"] + "/rename?name=" + plan["backup_name"])
        created = docker.request("POST", "/containers/create?name=" + NAME, plan["body"])
        candidate = created["Id"]
        for network, endpoint in plan["extra_networks"]:
            docker.request("POST", "/networks/" + network + "/connect", {"Container": candidate, "EndpointConfig": endpoint})
        docker.request("POST", "/containers/" + candidate + "/start")
        for attempt in range(20):
            try:
                result = health(plan["base_url"], expected)
                return {"updated": True, "release": plan["release"], "old_container": plan["old_id"],
                        "rollback_container": plan["backup_name"], "new_container": candidate,
                        "data_sha256": plan["data_sha256"], "image": plan["body"]["Image"],
                        "networks": plan["network_names"], "health": result,
                        "database_grants_or_migrations_run": False}
            except Exception:
                if attempt == 19:
                    raise UpdateError("Candidate health check failed.") from None
                pause(1)
    except BaseException as failure:
        # A repeated terminal/disconnect signal must not interrupt restoration.
        for sig in managed_signals:
            signal.signal(sig, signal.SIG_IGN)
        try:
            current = docker.inspect(missing=True)
            if current is not None and current["Id"] != plan["old_id"]:
                if current["Config"].get("Labels", {}).get("de.youspeed.update-operation") != plan["operation"]:
                    raise UpdateError("Unexpected concurrent replacement; refusing to remove it.")
                docker.request("DELETE", "/containers/" + current["Id"] + "?force=true")
            preserved = docker.inspect(plan["old_id"])
            if preserved["Name"] == "/" + plan["backup_name"]:
                docker.request("POST", "/containers/" + plan["old_id"] + "/rename?name=" + NAME)
            elif preserved["Name"] != "/" + NAME:
                raise UpdateError("Preserved service was concurrently renamed.")
            if not docker.inspect(plan["old_id"])["State"].get("Running"):
                docker.request("POST", "/containers/" + plan["old_id"] + "/start")
        except BaseException:
            raise UpdateError("Update failed and automatic rollback is incomplete; administrator must restore the preserved Inspector container.") from None
        if isinstance(failure, (KeyboardInterrupt, UpdateInterrupted)):
            raise UpdateInterrupted(failure.signum if isinstance(failure, UpdateInterrupted) else signal.SIGINT) from None
        if isinstance(failure, SystemExit):
            raise failure
        raise UpdateError("Update failed; the original Inspector was restored. New immutable files were retained for diagnosis.") from None
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sign-positions-file", required=True, type=Path)
    parser.add_argument("--check-only", action="store_true", help="Inspect and validate only; make no filesystem/service/database changes")
    args = parser.parse_args()
    if os.geteuid() != 0 or not socket.gethostname().startswith("volz-db"):
        raise UpdateError("Run with administrator privileges on volz-db.")
    manifest = verify_package(ROOT)
    raw, expected = private_input(args.sign_positions_file)
    docker = Docker()
    operation = manifest["release"] + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    plan = make_plan(docker.inspect(), manifest["release"], sha(raw), operation)
    if args.check_only:
        print(json.dumps({"check_only": True, "passed": True, "release": manifest["release"],
                          "image": plan["body"]["Image"], "networks": plan["network_names"],
                          "loopback_url": plan["base_url"], "speed_cases_in_input": len(expected),
                          "private_data_sha256": plan["data_sha256"], "database_mutations": False}))
        return
    with open("/run/lock/youspeed-inspector-update.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage_files(ROOT, manifest, raw, plan)
        result = perform_update(docker, plan, expected)
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except UpdateInterrupted as error:
        print("Inspector update interrupted; the original service was restored.", file=sys.stderr)
        raise SystemExit(128 + error.signum)
    except KeyboardInterrupt:
        print("Inspector preparation interrupted before the service switch.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(str(error) if isinstance(error, UpdateError) else "Inspector update failed; private details suppressed.", file=sys.stderr)
        raise SystemExit(1)

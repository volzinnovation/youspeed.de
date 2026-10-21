#!/usr/bin/env python3
"""Install the private crop inspector using existing volz-db backend resources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen


def run(args, *, data=None):
    return subprocess.run(args, input=data, text=True, check=True, capture_output=True).stdout.strip()


def inspect(kind, name):
    return json.loads(run(["docker", kind, "inspect", name]))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--local-port", type=int, default=18080)
    args = parser.parse_args()
    if os.geteuid() != 0 or not socket.gethostname().startswith("volz-db"):
        raise RuntimeError("Run with sudo on volz-db")
    if not all(1024 <= port <= 65535 for port in (args.port, args.local_port)):
        raise RuntimeError("Invalid inspector port")
    source = Path(__file__).resolve().parents[2]
    manifest = json.loads((source / "inspector-deployment.json").read_text())
    for name, expected in manifest["files"].items():
        path = (source / name).resolve()
        if not path.is_relative_to(source) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Inspector package integrity failed")
    credential = Path("/srv/woladen/config/youspeed/database-report.txt")
    if not credential.is_file() or credential.stat().st_mode & 0o077:
        raise RuntimeError("Existing private report credential missing or not mode 0600")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    name = "youspeed-inspector"
    existing = run(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"])
    if existing:
        raise RuntimeError("youspeed-inspector already exists; refusing to replace an existing service")
    reports = run(["docker", "ps", "-q", "--filter", "label=com.docker.compose.service=youspeed-reports"]).splitlines()
    if len(reports) != 1:
        raise RuntimeError("Expected one running YouSpeed reports container")
    report = inspect("container", reports[0])
    image = report["Image"]
    networks = {name: inspect("network", name) for name in report["NetworkSettings"]["Networks"]}
    private = [name for name, network in networks.items() if network["Internal"]]
    bridges = [name for name, network in networks.items() if not network["Internal"] and network["Driver"] == "bridge"]
    if len(private) != 1 or len(bridges) != 1:
        raise RuntimeError("Expected the existing private database and report publication networks")
    database = inspect("container", "panoramax-backend-db-1")
    if private[0] not in database["NetworkSettings"]["Networks"]:
        raise RuntimeError("Database is not on the reports' private network")
    volumes = run(["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.volume=youspeed_management_media"]).splitlines()
    if len(volumes) != 1:
        raise RuntimeError("Expected one existing management-media volume")
    # Require the already accepted backend image; never pull a replacement image.
    run(["docker", "run", "--rm", "--network", "none", "--user", "10001:10001", "--entrypoint", "python", image,
         "-c", "import psycopg; print('Existing PostgreSQL driver verified')"])
    destination = Path("/srv/youspeed-inspector/releases") / manifest["release"]
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    os.chmod(destination.parent.parent, 0o755)
    os.chmod(destination.parent, 0o755)
    if destination.exists():
        raise RuntimeError("Inspector release directory already exists")
    shutil.copytree(source, destination)
    for path in [destination, *destination.rglob("*")]:
        os.chown(path, 0, 0)
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    environment = dict(item.split("=", 1) for item in database["Config"]["Env"] if "=" in item)
    admin = environment.get("POSTGRES_USER", "postgres")
    grants = (destination / "inspector/report-crops-grants.sql").read_text()
    run(["docker", "exec", "-i", database["Id"], "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", admin, "-d", "youspeed"], data=grants)
    command = ["docker", "create", "--name", name, "--restart", "unless-stopped", "--read-only",
               "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
               "--pids-limit", "128", "--memory", "512m", "--network", private[0],
               "--publish", f"127.0.0.1:{args.port}:{args.port}",
               "--mount", f"type=bind,src={destination},dst=/opt/youspeed-inspector,readonly",
               "--mount", f"type=bind,src={credential},dst=/run/secrets/youspeed/database.txt,readonly",
               "--mount", f"type=volume,src={volumes[0]},dst=/var/lib/youspeed/management-media,readonly,volume-nocopy",
               "--env", "YOUSPEED_DATABASE_URL_FILE=/run/secrets/youspeed/database.txt",
               "--env", "YOUSPEED_MANAGEMENT_MEDIA_ROOT=/var/lib/youspeed/management-media",
               "--env", "PYTHONDONTWRITEBYTECODE=1",
               "--label", "de.youspeed.component=inspector", "--label", f"de.youspeed.release={manifest['release']}",
               "--entrypoint", "python", image, "/opt/youspeed-inspector/inspector/server.py",
               "--bind", "0.0.0.0", "--port", str(args.port), "--allowed-host", f"127.0.0.1:{args.port}",
               "--allowed-host", f"localhost:{args.port}", "--allowed-host", f"127.0.0.1:{args.local_port}",
               "--allowed-host", f"localhost:{args.local_port}"]
    created = False
    try:
        run(command)
        created = True
        run(["docker", "network", "connect", bridges[0], name])
        run(["docker", "start", name])
        base = f"http://127.0.0.1:{args.port}/inspector/api/crops"
        for attempt in range(10):
            try:
                with urlopen(base + "/status", timeout=10) as response:
                    status = json.load(response)
                break
            except Exception:
                if attempt == 9:
                    raise RuntimeError("Inspector did not become ready; check database/media permissions") from None
                time.sleep(1)
        if status["user"] != "youspeed_report" or status["database"] != "youspeed" or not status["media_available"]:
            raise RuntimeError("Inspector report identity or media mount verification failed")
        with urlopen(base + "?limit=1", timeout=15) as response:
            gallery = json.load(response)
        if gallery["crops"]:
            crop = gallery["crops"][0]
            with urlopen(f"http://127.0.0.1:{args.port}" + crop["image_url"], timeout=15) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != crop["digest"]:
                raise RuntimeError("Stored crop preview verification failed")
            print("Report identity, gallery and a stored crop image verified")
        else:
            print("Report identity and gallery verified; no active stored crops yet")
        print(f"Inspector running on volz-db loopback port {args.port}; local tunnel port {args.local_port}")
    except Exception:
        if created:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not print subprocess stderr: backend errors may contain credentials.
        print(str(error) if not isinstance(error, subprocess.CalledProcessError) else "Installation command failed; no credential details printed")
        raise SystemExit(1)

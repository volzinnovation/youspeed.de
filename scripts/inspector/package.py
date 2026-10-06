#!/usr/bin/env python3
"""Package only Inspector code and shared display assets, without private evidence."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    files = []
    for extension in ("js", "css", "html"):
        files.extend((root / "inspector").glob("*." + extension))
    files.extend(root / "inspector" / name for name in ("server.py", "requirements.txt", "report-crops-grants.sql", "README.md"))
    files.append(root / "scripts/inspector/install-volz-db.py")
    files.extend(path for path in (root / "shared/tsr/fixtures").rglob("*")
                 if path.is_file() and path.suffix in {".json", ".ppm", ".png", ".jpg", ".jpeg"})
    files.extend((root / "shared/tsr/sign-pictograms/png").rglob("*.png"))
    files.append(root / "shared/tsr/sign-pictograms/THIRD_PARTY_NOTICES.txt")
    files.extend((root / "shared/tsr").glob("prolix-*-class-catalog-v1.json"))
    files.extend((root / "iphone/SpeedConsumerApp/TSRModelPacks").glob("*.tsrmodelpack/manifest.json"))
    if any(path.is_symlink() or not path.resolve().is_relative_to(root) for path in files):
        raise RuntimeError("Deployment sources must be repository-local regular files")
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(files))}
    release = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    manifest = json.dumps({"release": release, "files": hashes}, sort_keys=True, indent=2).encode()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    output = args.output_directory / f"youspeed-inspector-{release}.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        for name in hashes:
            archive.add(root / name, arcname=name, recursive=False)
        entry = tarfile.TarInfo("inspector-deployment.json")
        entry.size, entry.mode = len(manifest), 0o644
        archive.addfile(entry, io.BytesIO(manifest))
    print(output)
    print("Release:", release, "Files:", len(hashes))
    print("SHA-256:", hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

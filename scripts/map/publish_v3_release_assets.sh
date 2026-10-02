#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 --repo <owner/repo> --tag <release_tag> --bundle-dir <dir> [--title <name>] [--notes <text>] [--draft]

Updates a GitHub release without deleting its existing assets or tag.
Dependencies are uploaded before bundle manifests; new releases remain drafts until complete.
Relative paths are attached as display labels; release asset names are basenames.

Examples:
  $0 --repo volzinnovation/youspeed.de \
     --tag v3-data-2026-02-24 \
     --bundle-dir mapdata/bundles/v3
USAGE
}

repo=""
tag=""
bundle_dir=""
title=""
notes="Automated data bundle release"
draft="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      repo="$2"
      shift 2
      ;;
    --tag)
      tag="$2"
      shift 2
      ;;
    --bundle-dir)
      bundle_dir="$2"
      shift 2
      ;;
    --title)
      title="$2"
      shift 2
      ;;
    --notes)
      notes="$2"
      shift 2
      ;;
    --draft)
      draft="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$repo" || -z "$tag" || -z "$bundle_dir" ]]; then
  usage
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required" >&2
  exit 1
fi

if [[ ! -d "$bundle_dir" ]]; then
  echo "Missing bundle dir: $bundle_dir" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to validate the release asset plan" >&2
  exit 1
fi

# Preflight every asset before changing GitHub. A temporary plan also propagates
# Python errors, unlike a process substitution used directly by the upload loop.
upload_plan="$(mktemp)"
trap 'rm -f "$upload_plan"' EXIT
python3 - "$bundle_dir" > "$upload_plan" <<'PYTHON'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
dependencies = []
manifests = []
names = {}
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    relative = path.relative_to(root).as_posix()
    if "#" in str(path):
        raise SystemExit(f"Release asset paths cannot contain '#': {relative}")
    if path.name in names:
        raise SystemExit(
            f"Duplicate release asset basename {path.name!r}: {names[path.name]} and {relative}"
        )
    names[path.name] = relative
    is_manifest = False
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise SystemExit(f"Invalid JSON release asset {relative}: {exc}") from exc
        is_manifest = isinstance(payload, dict) and payload.get("format") == "youspeed.v3.bundle.manifest"
    (manifests if is_manifest else dependencies).append(str(path))
if not manifests:
    raise SystemExit("No youspeed.v3.bundle.manifest found in bundle directory")
for path in dependencies + manifests:
    sys.stdout.buffer.write(path.encode() + b"\0")
PYTHON

if gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
  : # Preserve the existing release and its tag, including unrelated assets.
else
  # Never expose an incomplete new release. A failed upload leaves a draft that
  # can be resumed by rerunning this command.
  create_args=("$tag" --repo "$repo" --notes "$notes" --draft)
  if [[ -n "$title" ]]; then
    create_args+=(--title "$title")
  fi
  gh release create "${create_args[@]}"
fi

while IFS= read -r -d '' file; do
  rel="${file#${bundle_dir%/}/}"
  gh release upload "$tag" "$file#$rel" --clobber --repo "$repo"
  echo "uploaded: $rel"
done < "$upload_plan"

# Metadata changes and draft publication happen only after every upload succeeds.
# --draft does not hide an already published release.
edit_args=("$tag" --repo "$repo" --notes "$notes")
if [[ -n "$title" ]]; then
  edit_args+=(--title "$title")
fi
if [[ "$draft" == "0" ]]; then
  edit_args+=(--draft=false)
fi
gh release edit "${edit_args[@]}"

echo "Published release assets to $repo tag=$tag from $bundle_dir"

#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 --repo <owner/repo> --tag <release_tag> --bundle-dir <dir> [--title <name>] [--notes <text>] [--draft]

Uploads v3 consumer bundle assets to a GitHub release.
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
notes="Automated v3 data bundle release"
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

if ! gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
  create_args=("$tag" --repo "$repo" --notes "$notes")
  if [[ -n "$title" ]]; then
    create_args+=(--title "$title")
  fi
  if [[ "$draft" == "1" ]]; then
    create_args+=(--draft)
  fi
  gh release create "${create_args[@]}"
fi

while IFS= read -r -d '' file; do
  rel="${file#${bundle_dir%/}/}"
  gh release upload "$tag" "$file#$rel" --clobber --repo "$repo"
  echo "uploaded: $rel"
done < <(find "$bundle_dir" -type f -print0 | sort -z)

echo "Published release assets to $repo tag=$tag from $bundle_dir"

#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
src="${repo_root}/Web"
dst="${repo_root}/sites"

if [[ ! -f "${src}/index.html" ]]; then
  echo "Missing ${src}/index.html" >&2
  exit 1
fi

rm -rf "${dst}"
mkdir -p "${dst}"

rsync -a --delete "${src}/" "${dst}/"
printf 'youspeed.de\n' > "${dst}/CNAME"
touch "${dst}/.nojekyll"

echo "Published Web -> sites"

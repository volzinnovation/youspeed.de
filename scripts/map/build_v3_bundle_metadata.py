#!/usr/bin/env python3
"""Build the small Data Manager index from published manifests, never database assets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

FORMAT = 'youspeed.v3.bundle.metadata'
ASSET = 'bundle-metadata.v3.json'
MAX_BYTES = 512 * 1024


def targets(config, repo):
    if config.get('format') != 'youspeed.v3.bundle.targets':
        raise ValueError('Unexpected target configuration')
    result = []
    for country in config['countries']:
        country_id = country['country_id']
        regions = country['regions'] if country['mode'] == 'regional_shards' else [{'region_id': country_id}]
        for region in regions:
            token = region['region_id'].split('/')[-1].strip().lower().replace('_', '-').replace(' ', '-')
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', token):
                raise ValueError(f'Invalid region: {token}')
            result.append((f'{country_id}|{token}', token,
                           f'https://github.com/{repo}/releases/download/{token}/{token}_manifest.json'))
    return result


def fetch_manifest(url):
    try:
        with urlopen(Request(url, headers={'User-Agent': 'YouSpeed-Bundle-Metadata', 'Accept': 'application/json'}), timeout=20) as response:
            data = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        if error.code in (404, 410):
            return None
        raise
    if len(data) > MAX_BYTES:
        raise ValueError(f'Oversized manifest: {url}')
    return json.loads(data)


def build(config, repo, fetch=fetch_manifest):
    bundles = []
    for bundle_id, region, url in targets(config, repo):
        manifest = fetch(url)
        if manifest is None:
            continue  # Absence from the index never proves unavailability to a client.
        if (manifest.get('format') != 'youspeed.v3.bundle.manifest' or manifest.get('variant') != 'v3'
                or manifest['region'].split('/')[-1] != region):
            raise ValueError(f'Manifest mismatch: {url}')
        date = manifest['created_at_utc']
        if datetime.fromisoformat(date.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError(f'Missing date timezone: {url}')
        artifacts = manifest.get('db_parts') or [manifest['db']]
        sizes = [artifact['bytes'] for artifact in artifacts]
        if any(type(size) is not int or size <= 0 for size in sizes) or sum(sizes) > 2**63 - 1:
            raise ValueError(f'Invalid transfer size: {url}')
        version = manifest['bundle_version']
        if not isinstance(version, str) or not version:
            raise ValueError(f'Missing bundle version: {url}')
        bundles.append({'id': bundle_id, 'manifest_url': url, 'bundle_version': version,
                        'created_at_utc': date, 'download_bytes': sum(sizes)})
    return {'format': FORMAT, 'schema_version': 1,
            'created_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'bundles': sorted(bundles, key=lambda item: item['id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('iphone/SpeedConsumerApp/BundleTargets.top10.json'))
    parser.add_argument('--repo', default='')
    parser.add_argument('--out-json', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    repo = args.repo or f"{config['github_owner']}/{config['github_repo']}"
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        parser.error('Repository must be owner/repo')
    payload = build(config, repo)
    if not payload['bundles']:
        raise ValueError('Refusing to replace release metadata with an empty index')
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out_json.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
    temporary.replace(args.out_json)
    print(f"Wrote {len(payload['bundles'])} bundle entries to {args.out_json}")


if __name__ == '__main__':
    main()

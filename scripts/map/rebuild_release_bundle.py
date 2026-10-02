#!/usr/bin/env python3
"""Rebuild, validate, and release one complete bundle from a pinned checkout.

Unlike incremental updates this deliberately fetches a fresh Geofabrik extract,
resets the delta chain, and records build provenance. Referenced asset names are
versioned so the existing manifest remains usable until the new one is uploaded.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlparse

from resolve_country_release_plan import resolve_country_release_plan
from validate_v3_testing_bundle import validate_bundle


def run(*args):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def package_artifacts(manifest):
    """Only downloadable bytes, rather than the materialized DB, are assets."""
    return [*(manifest.get('db_parts') or [manifest['db']]),
            manifest['coverage']['poly'], manifest['delta_index'],
            *([manifest['penalty_rules']] if manifest.get('penalty_rules') else [])]


def verify_package(directory, manifest):
    for artifact in package_artifacts(manifest):
        name = unquote(urlparse(artifact['url']).path.rsplit('/', 1)[-1])
        if not name or Path(name).name != name:
            raise ValueError(f'Invalid asset name: {name!r}')
        path = directory / name
        if not path.is_file() or path.stat().st_size != artifact['bytes']:
            raise ValueError(f'Missing or wrong-sized release asset: {name}')
        if digest(path) != artifact['sha256']:
            raise ValueError(f'Release asset hash mismatch: {name}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--bundle-version', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]*', args.bundle_version):
        parser.error('Bundle version must be a safe filename component')
    if not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
        parser.error('Source commit must be a full SHA')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', args.repo):
        parser.error('Repository must be owner/repo')
    root = Path(__file__).resolve().parents[2]
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if head != args.source_commit:
        raise ValueError(f'Checkout {head} differs from pinned source {args.source_commit}')
    # All helper paths and output locations below are relative to the checkout.
    import os
    os.chdir(root)
    plan = resolve_country_release_plan(
        repo_root=root, bundle_country=args.target,
        geofabrik_index=root / 'mapdata/build/geofabrik/index-v1.json',
        bundle_target_config=root / 'iphone/SpeedConsumerApp/BundleTargets.top10.json',
        geofabrik_index_url='https://download.geofabrik.de/index-v1.json')
    region, iso2 = plan['region_slug'], plan['iso2']
    reports = Path('mapdata/reports/full-refresh') / args.target
    reports.mkdir(parents=True, exist_ok=True)
    write_json(reports / 'plan.json', plan)
    pbf, poly = Path(plan['input_pbf_path']), Path(plan['input_poly_path'])
    for path, url in ((pbf, plan['pbf_url']), (poly, plan['poly_url'])):
        path.parent.mkdir(parents=True, exist_ok=True)
        run('curl', '--fail', '--location', '--retry', '5', '--retry-delay', '10',
            '--silent', '--show-error', url, '--output', path)
    import osmium
    with osmium.io.Reader(str(pbf)) as reader:
        source_timestamp = reader.header().get('osmosis_replication_timestamp')
    if not source_timestamp:
        raise ValueError('Source PBF has no replication timestamp')
    source_hash = digest(pbf)
    write_json(reports / 'source.json', {'timestamp': source_timestamp,
               'sha256': source_hash, 'url': plan['pbf_url'], 'commit': args.source_commit})
    run('bash', 'scripts/map/build_region_artifacts.sh', '--region', region,
        '--input', pbf, '--engine', 'pyosmium')
    db = Path('mapdata/dist-v3') / region / 'speeds_v3.sqlite'
    settlement = iso2 in {'DE', 'FR', 'CH'}
    build = [sys.executable, 'scripts/map/build_spatialite_v3.py', '--v1-dist',
             f'mapdata/dist/{region}', '--out-db', db, '--input-pbf', pbf,
             '--corridor-mode', 'none', '--country-code', iso2,
             '--build-way-links', '--way-links-schema', 'detailed']
    if settlement:
        build.append('--build-settlement-context')
    run(*build)
    package = Path('mapdata/bundles/v3') / region / args.bundle_version
    package.mkdir(parents=True, exist_ok=False)
    prefix = f'{region}_{args.bundle_version}'
    delta = package / f'{prefix}_delta_index.json'
    run(sys.executable, 'scripts/map/roll_v3_delta_index.py', '--output', delta)
    owner, repo = args.repo.split('/')
    publish = [sys.executable, 'scripts/map/publish_v3_bundle.py', '--region', region,
               '--country-code', plan['country_code'], '--db', db,
               '--bundle-version', args.bundle_version, '--db-file-name', f'{prefix}_speeds.sqlite',
               '--db-compression', 'gzip', '--manifest-name', plan['bundle_manifest_asset'],
               '--coverage-poly', poly, '--coverage-poly-file-name', f'{prefix}.poly',
               '--delta-index', delta, '--delta-index-file-name', delta.name,
               '--min-app-version', '1.1.1' if iso2 == 'FR' else '1.1' if settlement else '1.0.0',
               '--github-owner', owner, '--github-repo', repo,
               '--github-release-tag', plan['bundle_release_tag_default']]
    if plan['penalty_rules_source_path']:
        publish += ['--penalty-rules', plan['penalty_rules_source_path'],
                    '--penalty-rules-file-name', f'{prefix}_{plan["penalty_rules_file_name"]}']
    run(*publish)
    manifest_path = package / plan['bundle_manifest_asset']
    manifest = json.loads(manifest_path.read_text())
    manifest['source'] = {'commit': args.source_commit, 'pbf_timestamp': source_timestamp,
                          'pbf_sha256': source_hash, 'pbf_url': plan['pbf_url']}
    write_json(manifest_path, manifest)
    report = validate_bundle(db, manifest_path, require_settlement=settlement)
    write_json(package / f'{prefix}_validation.json', report)
    write_json(reports / 'validation.json', report)
    if not report['ready']:
        raise ValueError(f'Bundle failed structural validation: {report["errors"]}')
    verify_package(package, manifest)
    if manifest.get('db_parts'):
        # The publisher retains its unsplit staging gzip; GitHub accepts only
        # the referenced parts when that file exceeds the release size limit.
        (package / f'{prefix}_speeds.sqlite.gz').unlink(missing_ok=True)
    files = {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)}
             for p in sorted(package.iterdir()) if p.is_file()}
    provenance = {'format': 'youspeed.v3.build-provenance', 'region': region,
                  'bundle_version': args.bundle_version, 'source_commit': args.source_commit,
                  'workflow_run_url': f'https://github.com/{args.repo}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "")}',
                  'built_at': datetime.now(timezone.utc).isoformat(), 'source': manifest['source'],
                  'validation_ready': True, 'files': files}
    write_json(package / f'{prefix}_build-provenance.json', provenance)
    write_json(reports / 'build-provenance.json', provenance)
    shutil.copy2(manifest_path, reports / manifest_path.name)
    if args.build_only:
        return 0
    run('bash', 'scripts/map/publish_v3_release_assets.sh', '--repo', args.repo,
        '--tag', plan['bundle_release_tag_default'], '--bundle-dir', package,
        '--title', plan['bundle_release_title_default'], '--notes',
        f'Full rebuild {args.bundle_version} from {args.source_commit}. '
        f'Source map timestamp: {source_timestamp}. Structural checks passed; provenance attached.')
    # Confirm GitHub received every byte by its server-side digest and size.
    release = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{args.repo}/releases/tags/{plan["bundle_release_tag_default"]}'], text=True))
    assets = {asset['name']: asset for asset in release['assets']}
    for path in package.iterdir():
        if not path.is_file():
            continue
        asset = assets.get(path.name, {})
        if asset.get('size') != path.stat().st_size or asset.get('digest') != 'sha256:' + digest(path):
            raise ValueError(f'Published asset verification failed: {path.name}')
    if release['draft']:
        raise ValueError('Release is still a draft')
    write_json(reports / 'release-verified.json', {'url': release['html_url'],
               'source_commit': args.source_commit, 'bundle_version': args.bundle_version,
               'asset_count': len(list(package.iterdir())), 'verified': True})
    print(f'RELEASE VERIFIED: {release["html_url"]} source={args.source_commit}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pin every published v3 bundle and its public PBF assets for packed conversion."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlparse


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def download_asset(repo, asset, output):
    output = Path(output)
    require(Path(asset['name']).name == asset['name'], 'Unsafe source asset name')
    expected = asset.get('digest', '')
    require(expected.startswith('sha256:'), f"Missing server SHA-256: {asset['name']}")
    def valid(path):
        return path.is_file() and path.stat().st_size == asset['size'] and sha256(path) == expected[7:]
    if valid(output):
        return output
    require(not output.exists(), f'Refusing to replace mismatched source evidence: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + '.download')
    require(not partial.exists(), f'Incomplete download exists: {partial}')
    with partial.open('xb') as target:
        subprocess.run(['gh', 'api', f"repos/{repo}/releases/assets/{asset['id']}",
                        '-H', 'Accept: application/octet-stream'], stdout=target, check=True)
    require(valid(partial), f"Source asset failed size/SHA: {asset['name']}")
    partial.rename(output)
    return output


def pin_artifact(artifact, assets):
    name = unquote(urlparse(artifact.get('url', '')).path.rsplit('/', 1)[-1]) or artifact['file']
    require(Path(name).name == name and name in assets, f'Manifest dependency absent from release: {name}')
    asset = assets[name]
    require(asset['size'] == artifact['bytes'] and asset['digest'] == 'sha256:' + artifact['sha256'],
            f'Manifest and GitHub dependency differ: {name}')
    return asset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--version', default='2026-10-27')
    parser.add_argument('--repo', default='volzinnovation/youspeed.de')
    args = parser.parse_args()
    require(re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]*', args.version), 'Unsafe version')
    data = json.loads(args.inventory.read_text())
    releases = [item for page in data for item in page] if data and isinstance(data[0], list) else data
    by_tag = {item['tag_name']: item for item in releases}
    candidates = []
    for release in releases:
        if release['draft']:
            continue
        manifests = [a for a in release['assets'] if a['name'].endswith('_manifest.json')
                     or a['name'].endswith('.bundle-manifest.v3.json')]
        if manifests and '-pbf-' not in release['tag_name']:
            for asset in manifests:
                candidates.append((release, asset))
    args.workspace.mkdir(parents=True, exist_ok=True)
    def resolve(candidate):
        release, asset = candidate
        tag = release['tag_name']
        require(re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]*', tag), 'Unsafe release tag')
        manifest_path = args.workspace / 'manifests' / tag / asset['name']
        download_asset(args.repo, asset, manifest_path)
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('format') == 'youspeed.v4.bundle.manifest':
            return None
        require(manifest.get('format') == 'youspeed.v3.bundle.manifest', f'Unsupported source manifest: {tag}')
        assets = {a['name']: a for a in release['assets']}
        database = [pin_artifact(a, assets) for a in manifest.get('db_parts') or [manifest['db']]]
        region = manifest['region']
        require(re.fullmatch(r'[a-z0-9][a-z0-9._-]*', region), f'Unsafe region: {region}')
        code = manifest.get('country_code', '').upper()
        aliases = {'monaco':'mco','switzerland':'che','sweden':'swe','romania':'rou',
                   'netherlands':'nld','belgium':'bel','luxembourg':'lux','iceland':'isl',
                   'liechtenstein':'lie','united-kingdom':'gbr','germany':'deu'}
        pbf_tag = region + '-pbf-latest'
        if pbf_tag not in by_tag:
            pbf_tag = aliases.get(region, code.lower()) + '-pbf-latest'
        require(pbf_tag in by_tag, f'No pinned PBF release for {tag}/{region}')
        pbf_assets = [a for a in by_tag[pbf_tag]['assets'] if a['name'].endswith('.osm.pbf')]
        if not pbf_assets:
            pbf_assets = sorted((a for a in by_tag[pbf_tag]['assets'] if re.search(r'\.osm\.pbf\.part\d+$', a['name'])), key=lambda a:a['name'])
        require(pbf_assets, f'No PBF assets in {pbf_tag}')
        extras = {}
        for name, item in [('poly', manifest.get('coverage', {}).get('poly')),
                           ('penalty_rules', manifest.get('penalty_rules'))]:
            if item:
                extras[name] = pin_artifact(item, assets)
        return {'source_release_tag':tag, 'source_release_id':release['id'], 'source_release_url':release['html_url'],
                'source_manifest':str(manifest_path), 'source_manifest_asset':asset,
                'region':region, 'country_code':code, 'source_bundle_version':manifest.get('bundle_version'),
                'database_assets':database, 'extras':extras, 'pbf_release_tag':pbf_tag, 'pbf_assets':pbf_assets,
                'release_tag':f'{tag}-packed-v1-{args.version}', 'bundle_version':f'{args.version}-packed-v1',
                'manifest_file':region+'_manifest.json'}
    plans, failures = [], []
    with ThreadPoolExecutor(max_workers=6) as executor:
        tasks = {executor.submit(resolve, item):item for item in candidates}
        for task in as_completed(tasks):
            try:
                plan = task.result()
                if plan is None:
                    print('SKIPPED packed generation',tasks[task][0]['tag_name'],flush=True)
                    continue
                plans.append(plan)
                print('PINNED', plan['source_release_tag'], flush=True)
            except Exception as error:
                release, asset = tasks[task]
                failures.append({'tag':release['tag_name'], 'manifest':asset['name'], 'error':str(error)})
                print('FAILED', release['tag_name'], str(error), flush=True)
    document = {'format':'youspeed.v4.pinned-release-plan', 'schema_version':1, 'repo':args.repo,
                'version':args.version, 'bundles':sorted(plans, key=lambda x:x['source_release_tag']), 'failures':failures}
    (args.workspace / 'plan.json').write_text(json.dumps(document, indent=2)+'\n')
    require(not failures, f'{len(failures)} bundle sources need repair; see plan.json')
    print('COMPLETE',len(plans),'published bundle manifests pinned')


if __name__ == '__main__':
    main()

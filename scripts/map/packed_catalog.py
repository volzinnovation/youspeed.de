#!/usr/bin/env python3
"""Build an offline v4 catalog and byte comparisons from published-release receipts.

Usage: packed_catalog.py --results TARGET/result.json ... --output-dir OUTPUT
       --require-complete

Each result requires its sibling github-verified.json. The publisher receipt
must assert publication and server verification of every asset. This tool does
not contact GitHub, upload assets, edit releases or infer publication from a URL.
The pinned plan supplies country codes and the expected immutable identities.

catalog.json follows youspeed.v4.bundle.catalog, schema_version 1, variant v4:
bundles contain region, country_code, release_tag, bundle_version and manifest
{file,url,bytes,sha256}. A canonical source_release_tag equal to region wins the
Karlsruhe alias, while both releases retain separate size-comparison rows.

Comparisons count the source SQLite versus context+geometry+generic-node bytes,
and their database/runtime transport bytes. Coverage, penalty and report files
are excluded consistently. BW and the explicit canonical-region-alias refresh
retain their previous published sources as separate baselines. Percent changes
are (packed/source-1)*100.

--draft-comparison-only accepts server-verified drafts for size review, labels
their release status, and writes only comparison JSON/CSV. It never generates
a catalog and refuses an output directory already containing catalog.json.
"""

import argparse
import csv
from io import StringIO
import json
import os
from pathlib import Path
import re
import tempfile


DEFAULT_PLAN = Path(__file__).resolve().parents[2] / 'shared/packed-runtime/releases/source-plan-2026-10-27.json'
MAX_INTEGER = (1 << 63) - 1
SHA256 = re.compile(r'[0-9a-f]{64}')
IDENTITY = re.compile(r'[a-z0-9][a-z0-9._-]*')
CSV_FIELDS = [
    'region', 'country_code', 'source_release_tag', 'release_tag', 'bundle_version',
    'catalog_selected', 'release_status', 'local_source_upgrade', 'source_upgrade_kind', 'converted_source_release_tag', 'node_count',
    'source_installed_bytes', 'packed_installed_bytes', 'installed_delta_bytes', 'installed_change_percent',
    'source_download_bytes', 'packed_download_bytes', 'download_delta_bytes', 'download_change_percent',
    'previous_published_installed_bytes', 'previous_published_installed_delta_bytes', 'previous_published_installed_change_percent',
    'previous_published_download_bytes', 'previous_published_download_delta_bytes', 'previous_published_download_change_percent',
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, label, minimum=1):
    require(type(value) is int and minimum <= value <= MAX_INTEGER, 'Invalid ' + label)
    return value


def read_json(path):
    path = Path(path)
    require(path.stat().st_size <= 16 * 1024 * 1024, 'Oversized receipt/plan: ' + str(path))
    value = json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(value, dict), 'Expected a JSON document: ' + str(path))
    return value


def change(packed, source):
    if source is None:
        return None, None
    return packed - source, round((packed - source) * 100.0 / source, 6)


def plan_entries(plan):
    require(plan.get('format') == 'youspeed.v4.pinned-release-plan' and type(plan.get('schema_version')) is int and plan['schema_version'] == 1,
            'Unsupported source plan')
    require(plan.get('failures') == [], 'Source plan has unresolved failures')
    repo = plan.get('repo', '')
    require(isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'Invalid repository')
    entries = plan.get('bundles')
    require(isinstance(entries, list) and entries, 'Empty source plan')
    canonical_countries = {entry['region']: entry.get('country_code') for entry in entries
                           if isinstance(entry, dict) and entry.get('source_release_tag') == entry.get('region')}
    by_source = {}
    for entry in entries:
        require(isinstance(entry, dict), 'Invalid source entry')
        entry = dict(entry)
        for key in ['region', 'source_release_tag', 'release_tag', 'bundle_version']:
            require(isinstance(entry.get(key), str) and IDENTITY.fullmatch(entry[key]), 'Invalid source identity: ' + key)
        require(entry['source_release_tag'] not in by_source, 'Duplicate source release in plan')
        # The historical Karlsruhe alias omits this field. Its canonical
        # pinned region supplies the identity used by the catalog and report.
        canonical_country = canonical_countries.get(entry['region'])
        if not entry.get('country_code'):
            entry['country_code'] = canonical_country
        require(isinstance(entry.get('country_code'), str) and re.fullmatch(r'[A-Z]{2,3}', entry['country_code']), 'Invalid source country code')
        require(canonical_country is None or entry['country_code'] == canonical_country, 'Conflicting country codes for one region')
        require(entry.get('manifest_file') == entry['region'] + '_manifest.json', 'Unexpected source manifest filename')
        require(isinstance(entry.get('source_manifest_document'), dict), 'Embedded source manifest missing')
        assets = entry.get('database_assets')
        require(isinstance(assets, list) and assets, 'Pinned database assets missing')
        for asset in assets:
            require(isinstance(asset, dict), 'Invalid pinned database asset')
            integer(asset.get('size'), 'pinned database asset bytes')
        by_source[entry['source_release_tag']] = entry
    return repo, by_source


def validate_release(result_path, repo, entries, draft_comparison_only=False):
    result_path = Path(result_path)
    result = read_json(result_path)
    receipt = read_json(result_path.with_name('github-verified.json'))
    require(result.get('format') == 'youspeed.v4.release-comparison' and type(result.get('schema_version')) is int and result['schema_version'] == 1,
            'Unsupported packed build result')
    source = result.get('source_release_tag')
    require(source in entries, 'Result is absent from the pinned source plan: ' + str(source))
    entry = entries[source]
    for key in ['region', 'release_tag', 'bundle_version']:
        require(result.get(key) == entry[key], 'Result identity differs from pinned plan: ' + key)
    require(type(result.get('local_source_upgrade')) is bool, 'Source upgrade status missing')
    upgraded = result['local_source_upgrade']
    require(not upgraded or result['region'] == 'baden-wuerttemberg', 'Unplanned local source upgrade')
    converted_source = result.get('converted_source_release_tag')
    upgrade_kind = result.get('source_upgrade_kind')
    actual_entry = entry
    if converted_source is not None or upgrade_kind == 'canonical-region-alias':
        require(not upgraded and upgrade_kind == 'canonical-region-alias' and source != entry['region']
                and converted_source == entry['region'] and converted_source in entries,
                'Unplanned canonical alias substitution')
        actual_entry = entries[converted_source]
        require(actual_entry['source_release_tag'] == actual_entry['region'] == entry['region']
                and actual_entry['country_code'] == entry['country_code'], 'Alias replacement belongs to another region')
    else:
        require(upgrade_kind in [None, 'local-full-bw', 'unchanged'], 'Unknown source upgrade kind')
        require(upgrade_kind != 'local-full-bw' or upgraded, 'False local source upgrade label')
        require(not upgraded or upgrade_kind in [None, 'local-full-bw'], 'False unchanged source label')
    source_manifest = actual_entry['source_manifest_document']
    require(upgraded or result.get('source_bundle_version') == actual_entry.get('source_bundle_version'),
            'Source bundle version changed')
    source_hash = result.get('source_sqlite_sha256', '')
    require(isinstance(source_hash, str) and SHA256.fullmatch(source_hash), 'Invalid source SQLite hash')
    original = source_manifest.get('db', {})
    require(isinstance(original, dict), 'Invalid pinned source database')
    compressed = original.get('compression') not in [None, '', 'none', 'identity']
    pinned_source_hash = original.get('uncompressed_sha256') or (original.get('sha256') if not compressed else None)
    if not upgraded and pinned_source_hash is not None:
        require(source_hash == pinned_source_hash, 'Source SQLite hash differs from published manifest')
    verification = result.get('verification', {})
    require(isinstance(verification, dict), 'Invalid semantic verification')
    for flag in ['all_original_logical_table_counts_preserved', 'original_metadata_values_preserved', 'every_original_geometry_text_exact']:
        require(verification.get(flag) is True, 'Missing semantic verification: ' + flag)

    files = result.get('release_files')
    require(isinstance(files, list) and files, 'Release assets missing')
    assets = {}
    for asset in files:
        require(isinstance(asset, dict), 'Invalid release asset')
        name = asset.get('file')
        require(isinstance(name, str) and name not in ['', '.', '..'] and Path(name).name == name and '\\' not in name,
                'Unsafe release asset filename')
        require(name not in assets, 'Duplicate release asset: ' + name)
        integer(asset.get('bytes'), 'release asset bytes')
        require(isinstance(asset.get('sha256'), str) and SHA256.fullmatch(asset['sha256']), 'Invalid release asset SHA-256')
        assets[name] = asset
    manifest_name = entry['manifest_file']
    require(manifest_name in assets, 'Catalog manifest asset is missing')
    integer(assets[manifest_name]['bytes'], 'manifest bytes')
    require(assets[manifest_name]['bytes'] <= 1024 * 1024, 'Catalog manifest exceeds client size limit')
    require(receipt.get('release_tag') == result['release_tag'], 'Server receipt names another release')
    if draft_comparison_only:
        require(type(receipt.get('published')) is bool, 'Draft/publication status is unverified')
    else:
        require(receipt.get('published') is True, 'Release is still a draft or publication is unverified')
    require(receipt.get('all_asset_hashes_verified') is True, 'Not every release asset was server verified')
    require(type(receipt.get('asset_count')) is int and receipt['asset_count'] == len(assets), 'Server verified asset count differs')
    require(isinstance(receipt.get('source_commit'), str) and re.fullmatch(r'[0-9a-f]{40}', receipt['source_commit']),
            'Pinned publisher source commit missing')
    base_url = 'https://github.com/' + repo + '/releases/'
    public_url = base_url + 'tag/' + result['release_tag']
    draft_url = receipt.get('url', '')
    is_draft_url = isinstance(draft_url, str) and re.fullmatch(re.escape(base_url + 'tag/untagged-') + '[0-9a-f]+', draft_url)
    require(receipt.get('url') == public_url or draft_comparison_only and receipt['published'] is False and is_draft_url,
            'Unexpected published release URL')

    row = {key: result[key] for key in ['region', 'source_release_tag', 'release_tag', 'bundle_version', 'local_source_upgrade']}
    row['country_code'] = entry['country_code']
    row['catalog_selected'] = source == result['region']
    row['release_status'] = 'published' if receipt['published'] else 'draft'
    row['source_upgrade_kind'] = upgrade_kind or ('local-full-bw' if upgraded else 'unchanged')
    row['converted_source_release_tag'] = converted_source
    row['node_count'] = integer(result.get('node_count'), 'generic node count', minimum=0)
    for key in ['source_installed_bytes', 'packed_installed_bytes', 'source_download_bytes', 'packed_download_bytes', 'previous_published_download_bytes']:
        row[key] = integer(result.get(key), key)
    previous_download = sum(asset['size'] for asset in entry['database_assets'])
    require(row['previous_published_download_bytes'] == previous_download, 'Previous published download bytes differ from pinned assets')
    if not upgraded:
        require(row['source_download_bytes'] == original.get('bytes'), 'Source transport differs from published manifest')
    actual_installed = original.get('uncompressed_bytes')
    if actual_installed is None and not compressed:
        actual_installed = original.get('bytes')
    if not upgraded and actual_installed is not None:
        require(row['source_installed_bytes'] == actual_installed, 'Source installed bytes differ from published manifest')
    previous = entry['source_manifest_document'].get('db', {})
    previous_installed = previous.get('uncompressed_bytes')
    if previous_installed is None and previous.get('compression') in [None, '', 'none', 'identity']:
        previous_installed = previous.get('bytes')
    if previous_installed is not None:
        integer(previous_installed, 'previous published installed bytes')
    row['previous_published_installed_bytes'] = previous_installed
    for prefix, packed_key, source_key in [
        ('installed', 'packed_installed_bytes', 'source_installed_bytes'),
        ('download', 'packed_download_bytes', 'source_download_bytes'),
        ('previous_published_installed', 'packed_installed_bytes', 'previous_published_installed_bytes'),
        ('previous_published_download', 'packed_download_bytes', 'previous_published_download_bytes'),
    ]:
        row[prefix + '_delta_bytes'], row[prefix + '_change_percent'] = change(row[packed_key], row[source_key])
    manifest_asset = assets[manifest_name]
    catalog_entry = {key: row[key] for key in ['region', 'country_code', 'release_tag', 'bundle_version']}
    catalog_entry['manifest'] = {
        'file': manifest_name,
        'url': base_url + 'download/' + result['release_tag'] + '/' + manifest_name,
        'bytes': manifest_asset['bytes'], 'sha256': manifest_asset['sha256'],
    }
    return row, catalog_entry


def documents(plan, result_paths, require_complete=False, draft_comparison_only=False):
    repo, entries = plan_entries(plan)
    require(result_paths, 'No published build results supplied')
    rows, catalog_by_region, seen = [], {}, set()
    for path in result_paths:
        row, catalog_entry = validate_release(path, repo, entries, draft_comparison_only=draft_comparison_only)
        source = row['source_release_tag']
        require(source not in seen, 'Duplicate result for source release: ' + source)
        seen.add(source)
        rows.append(row)
        if row['catalog_selected']:
            require(row['region'] not in catalog_by_region, 'Duplicate canonical catalog region')
            catalog_by_region[row['region']] = catalog_entry
    if require_complete:
        require(seen == set(entries), 'Published source releases missing: ' + ','.join(sorted(set(entries) - seen)))
    for row in rows:
        require(row['region'] in catalog_by_region, 'Canonical source release is missing for region: ' + row['region'])
    rows.sort(key=lambda row: (row['region'], row['source_release_tag']))
    selected = [row for row in rows if row['catalog_selected']]
    totals = {}
    for key in ['source_installed_bytes', 'packed_installed_bytes', 'source_download_bytes', 'packed_download_bytes', 'previous_published_download_bytes']:
        totals[key] = sum(row[key] for row in selected)
    totals['previous_published_installed_bytes'] = (sum(row['previous_published_installed_bytes'] for row in selected)
        if all(row['previous_published_installed_bytes'] is not None for row in selected) else None)
    for prefix, packed_key, source_key in [
        ('installed', 'packed_installed_bytes', 'source_installed_bytes'),
        ('download', 'packed_download_bytes', 'source_download_bytes'),
        ('previous_published_installed', 'packed_installed_bytes', 'previous_published_installed_bytes'),
        ('previous_published_download', 'packed_download_bytes', 'previous_published_download_bytes'),
    ]:
        totals[prefix + '_delta_bytes'], totals[prefix + '_change_percent'] = change(totals[packed_key], totals[source_key])
    catalog = {'format': 'youspeed.v4.bundle.catalog', 'schema_version': 1, 'variant': 'v4',
               'bundles': [catalog_by_region[region] for region in sorted(catalog_by_region)]}
    comparison = {
        'format': 'youspeed.v4.size-comparison', 'schema_version': 1, 'units': 'bytes',
        'release_count': len(rows), 'catalog_region_count': len(selected),
        'comparison_mode': 'draft-comparison-only' if draft_comparison_only else 'published',
        'catalog_generated': not draft_comparison_only,
        'runtime_scope': 'context + exact geometry + generic speed-sign nodes; excludes coverage, penalty and report files',
        'source_scope': 'source SQLite and its transport; full-BW and canonical-region-alias upgrades retain their separate previous published baselines',
        'percent_formula': '(packed / source - 1) * 100; negative values indicate a reduction',
        'catalog_region_totals': totals, 'bundles': rows,
    }
    return None if draft_comparison_only else catalog, comparison


def csv_document(comparison):
    output = StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in comparison['bundles']:
        writer.writerow({key: str(value).lower() if isinstance(value, bool) else value for key, value in row.items()})
    return output.getvalue()


def write_atomic(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, prefix=path.name + '.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=DEFAULT_PLAN)
    parser.add_argument('--results', nargs='+', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--require-complete', action='store_true')
    parser.add_argument('--draft-comparison-only', action='store_true',
                        help='Review verified draft/published sizes without generating any catalog')
    args = parser.parse_args()
    require(not args.draft_comparison_only or not (args.output_dir / 'catalog.json').exists(),
            'Draft comparison requires an output directory without catalog.json')
    catalog, comparison = documents(read_json(args.plan), args.results, require_complete=args.require_complete,
                                    draft_comparison_only=args.draft_comparison_only)
    # Validate every receipt before touching any existing output.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [('size-comparison.json', comparison)]
    if catalog is not None:
        outputs.append(('catalog.json', catalog))
    for name, value in outputs:
        write_atomic(args.output_dir / name, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
    write_atomic(args.output_dir / 'size-comparison.csv', csv_document(comparison))
    print(json.dumps({'published_release_count': sum(row['release_status'] == 'published' for row in comparison['bundles']),
                      'draft_release_count': sum(row['release_status'] == 'draft' for row in comparison['bundles']),
                      'catalog_regions': comparison['catalog_region_count'], 'catalog_written': catalog is not None,
                      'output_directory': str(args.output_dir)}, sort_keys=True))


if __name__ == '__main__':
    main()

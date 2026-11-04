#!/usr/bin/env python3
"""Audit literal DE:278 values without assigning direction or runtime authority."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import zlib

from pack_sign_nodes import RECORD, fnv

ROOT = Path(__file__).resolve().parents[2]
SIGN_KEYS = {'traffic_sign', 'traffic_sign:forward', 'traffic_sign:backward'}
EXACT = re.compile(r'(?:DE:)?278(?:-([0-9]{1,3})|\[([0-9]{1,3})(?:\s*km/h)?\])')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inspect_osm(nodes, available):
    counts, keys, missing, spellings = Counter(), Counter(), Counter(), Counter()
    exact_nodes, reviewed_nodes, no_memberships = set(), set(), set()
    examples = []
    for node in nodes:
        for key, value in node['tags'].items():
            if key not in SIGN_KEYS:
                continue
            # This audit counts source tokens, not physical signs or accepted
            # driving observations. Additional plates/direction remain unresolved.
            for token in re.split(r'[;,]', value):
                match = EXACT.fullmatch(token.strip())
                if match is None:
                    continue
                speed = int(match.group(1) or match.group(2))
                code = f'DE:278-{speed}'
                counts[str(speed)] += 1
                keys[key] += 1
                spellings['bracket' if match.group(2) else 'suffix'] += 1
                exact_nodes.add(node['osm_node_id'])
                if code in available:
                    reviewed_nodes.add(node['osm_node_id'])
                else:
                    missing[code] += 1
                if not node['memberships']:
                    no_memberships.add(node['osm_node_id'])
                if len(examples) < 3:
                    examples.append({'osm_node_id': node['osm_node_id'], 'tag': key,
                                     'literal': token.strip(), 'memberships': node['memberships']})
    return {'numeric_token_occurrences': sum(counts.values()),
            'unique_nodes_with_numeric_tokens': len(exact_nodes),
            'unique_nodes_with_reviewed_artwork': len(reviewed_nodes),
            'numeric_token_counts_by_speed': dict(sorted(counts.items(), key=lambda item: int(item[0]))),
            'token_counts_by_tag': dict(sorted(keys.items())), 'token_counts_by_spelling': dict(spellings),
            'unreviewed_code_token_counts': dict(missing),
            'unique_numeric_nodes_without_admitted_way_membership': len(no_memberships),
            'contains_25_kmh': '25' in counts, 'examples': examples,
            'interpretation': 'Counts describe source tags, not legally applicable observations. '
                              'Unreviewed codes may be legacy numbering and are not silently reinterpreted.'}


def verify_packed(nodes, path):
    """Independently compare all source rows with the published pack encoding."""
    data = Path(path).read_bytes()
    assert data[:8] == b'YSPNODE1'
    count, record_offset, order_offset, blob_offset, total = struct.unpack_from('<QQQQQ', data, 16)
    assert count == len(nodes) and total == len(data)
    expected = {node['osm_node_id']: node for node in nodes}
    seen = set()
    for index in range(count):
        node_id, lat, lon, offset, size, raw_size, crc, checksum = RECORD.unpack_from(
            data, record_offset + index * RECORD.size)
        raw = zlib.decompress(data[blob_offset + offset:blob_offset + offset + size])
        node = expected[node_id]
        canonical = json.dumps(node, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        assert raw == canonical and len(raw) == raw_size
        assert zlib.crc32(raw) == crc and fnv(raw) == checksum
        assert (lat / 1e7, lon / 1e7) == (node['latitude'], node['longitude'])
        seen.add(node_id)
    assert seen == expected.keys()
    return {'path': str(path), 'sha256': digest(path), 'verified_node_count': count,
            'complete_source_records_identical': True}


def audit(database, source_json, packed):
    source = json.loads(source_json.read_text())
    manifest = json.loads((ROOT / 'shared/tsr/sign-pictograms/manifest.json').read_text())
    available = {art['sign_code'] for art in manifest['artworks']}
    db = sqlite3.connect('file:' + str(database.resolve()) + '?mode=ro&immutable=1', uri=True)
    inventory = db.execute("""SELECT source_id,sign_code,count(*) FROM traffic_sign_inventory
        WHERE sign_code='DE:278' OR sign_code LIKE 'DE:278-%' OR sign_code LIKE 'DE:278[%'
        GROUP BY source_id,sign_code ORDER BY source_id,sign_code""").fetchall()
    runtime = db.execute("""SELECT source_id,sign_code,numeric_value,pictogram_code,pictogram_path,count(*)
        FROM traffic_sign_runtime WHERE sign_code='DE:278' OR sign_code LIKE 'DE:278-%'
        OR sign_code LIKE 'DE:278[%' GROUP BY source_id,sign_code,numeric_value,pictogram_code,pictogram_path
        ORDER BY source_id,sign_code""").fetchall()
    properties = set()
    for row in db.execute("SELECT raw_properties_json FROM traffic_sign_inventory WHERE sign_code='DE:278'"):
        properties.update(json.loads(row[0]))
    snapshots = [dict(zip(('source_id', 'snapshot_sha256', 'snapshot_timestamp'), row)) for row in db.execute(
        "SELECT source_id,snapshot_sha256,snapshot_timestamp FROM traffic_sign_source WHERE source_id='mobidata-bw-vzk'")]
    db.close()
    sqlite_sha = digest(database)
    assert sqlite_sha == source['source_sqlite_sha256'], 'Node source/database mismatch'
    return {'schema_version': 1, 'scope': 'Local integrated BW snapshot; not a claim about newer source data.',
            'database': {'path': str(database), 'sha256': sqlite_sha},
            'osm_source': {'path': str(source_json), 'sha256': digest(source_json),
                           **{k: v for k, v in source.items() if k != 'nodes'}},
            'packed_nodes_verification': verify_packed(source['nodes'], packed),
            'mobidata': {'snapshots': snapshots,
                         'inventory_counts': [dict(zip(('source_id', 'sign_code', 'count'), row)) for row in inventory],
                         'runtime_counts': [dict(zip(('source_id', 'sign_code', 'numeric_value', 'pictogram_code', 'pictogram_path', 'count'), row)) for row in runtime],
                         'generic_end_source_property_keys': sorted(properties)},
            'osm': inspect_osm(source['nodes'], available)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--source-json', type=Path, required=True)
    parser.add_argument('--packed-nodes', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.database, args.source_json, args.packed_nodes)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'osm': result['osm'],
                      'mobidata': result['mobidata']['inventory_counts']}, ensure_ascii=False))

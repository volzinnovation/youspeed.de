"""Create a fixed MapServer view over one existing canonical GeoPackage.

No feature export, grouping, geometry calculation or database mutation occurs.
Run once per full/loop endpoint; both mapfiles reference the same canonical file.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

LAYER = 'verkehrszeichen'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def create_view(canonical_directory, output_directory, ids=None):
    canonical_directory = Path(canonical_directory).resolve(strict=True)
    output_directory = Path(output_directory).resolve()
    if canonical_directory == output_directory:
        raise ValueError('view directory must differ from canonical export directory')
    package = canonical_directory / (LAYER + '.gpkg')
    canonical_map = canonical_directory / (LAYER + '.map')
    if not package.is_file() or not canonical_map.is_file():
        raise ValueError('canonical GeoPackage and original exporter mapfile required')
    before = digest(package)
    with sqlite3.connect('file:' + quote(str(package), safe='/') + '?mode=ro', uri=True) as db:
        existing = [row[0] for row in db.execute('SELECT id FROM verkehrszeichen')]
    if len(existing) != len(set(existing)):
        raise ValueError('canonical feature IDs are not unique')
    if any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{32}', v) for v in existing):
        raise ValueError('invalid canonical feature ID')
    selected = None if ids is None else list(ids)
    if selected is not None:
        if any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{32}', v) for v in selected):
            raise ValueError('selected IDs must be 32 lowercase hexadecimal characters')
        if len(selected) != len(set(selected)):
            raise ValueError('duplicate selected ID')
        if set(selected) - set(existing):
            raise ValueError('selected ID missing from canonical GeoPackage')
        selected.sort()
    text = canonical_map.read_text()
    connection = '    CONNECTION "verkehrszeichen.gpkg"'
    data = '    DATA "verkehrszeichen"'
    if text.count(connection) != 1 or text.count(data) != 1:
        raise ValueError('unexpected canonical exporter mapfile; refusing broad replacement')
    text = text.replace(connection, '    CONNECTION ' + json.dumps(str(package)))
    layer_filter = None
    if selected is not None:
        # Quoted [id] bindings are required for string fields. A permanent layer
        # expression composes with the existing UI's incoming FES city filter;
        # a simple OGR SQL DATA query does not on the tested native MapServer build.
        # Keep the extra inner parentheses: otherwise the native FES merge applies
        # AND to only the first OR branch, returning incorrect filtered results.
        clauses = ['"[id]" = "' + value + '"' for value in selected]
        layer_filter = '((' + ' OR '.join(clauses) + '))' if clauses else '("[id]" = "")'
        text = text.replace(data, data + '\n    FILTER ' + layer_filter)
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_directory.stat().st_mode & 0o077:
        raise ValueError('view directory must be owner-only')
    mapfile = output_directory / (LAYER + '.map')
    config = output_directory / 'mapserver.conf'
    config_text = ('CONFIG\n  ENV\n    MS_MAPFILE ' + json.dumps(str(mapfile)) + '\n'
                   '    MS_MAP_NO_PATH "1"\n    MS_MODE "WFS"\n'
                   '    MS_ERRORFILE "stderr"\n    PROJ_NETWORK "OFF"\n  END\nEND\n')
    manifest = {'schema_version': 1, 'canonical_gpkg': str(package), 'canonical_gpkg_sha256': before,
                'canonical_mapfile': str(canonical_map), 'canonical_mapfile_sha256': digest(canonical_map),
                'mode': 'all_canonical_features' if selected is None else 'fixed_id_subset',
                'selected_ids': sorted(existing) if selected is None else selected,
                'feature_count': len(existing) if selected is None else len(selected),
                'mapserver_data': LAYER, 'mapserver_layer_filter': layer_filter,
                'no_feature_copy_or_recomputation': True}
    files = {mapfile: text, config: config_text,
             output_directory / 'view.json': json.dumps(manifest, indent=2) + '\n'}
    # Re-running an identical recipe is harmless; changing a view needs a new directory.
    for path, value in files.items():
        if path.exists() and path.read_text() != value:
            raise ValueError('view configuration is immutable: ' + str(path))
    for path, value in files.items():
        if not path.exists():
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                stream.write(value)
        elif path.stat().st_mode & 0o077:
            raise ValueError('existing view configuration is not owner-only')
    if digest(package) != before:
        raise ValueError('canonical GeoPackage changed during configuration generation')
    return config

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical-directory', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--ids-json', type=Path, help='JSON array of exact canonical feature IDs; omit for all features')
    args = parser.parse_args()
    ids = json.loads(args.ids_json.read_text()) if args.ids_json else None
    if ids is not None and not isinstance(ids, list):
        parser.error('--ids-json must contain a JSON array')
    print(create_view(args.canonical_directory, args.output_directory, ids))

if __name__ == '__main__':
    main()

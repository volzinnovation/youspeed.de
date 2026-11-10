#!/usr/bin/env python3
"""Bundle the audited expanded-class training intake without promoting its labels."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--repository', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError('Use a fresh immutable intake directory')
    proposals = a.evidence / 'new-sample-proposals.json'
    plates = a.evidence / 'upstream-audit/derived-plate-intake.json'
    classes = json.loads((a.evidence / 'class-index.json').read_text())['classes']
    catalog_path = a.repository / 'shared/tsr/prolix-de-class-catalog-v1.json'
    catalog = json.loads(catalog_path.read_text())
    rows = []
    for item in json.loads(proposals.read_text())['samples']:
        row = dict(item)
        if row['label_source'] != 'assistant_visual_silver' or row['human_approved']:
            raise ValueError('Unexpected proposal provenance')
        row.update(label=row['class_id'], label_origin='assistant_visual_silver', human_reviewed=False)
        row['group_identities'] = list(set(row.get('route_tokens', []) + [row['source_id']]))
        rows.append(row)
    for item in json.loads(plates.read_text())['samples']:
        row = dict(item)
        row['path'] = str((plates.parent / row['path']).resolve())
        rows.append(row)
    # Keep physical-sign and route connections together, including the three
    # historical plate crops known to show the same school/30 sign assembly.
    components = [{str(r.get('group_id', r['sample_id'])), *r.get('group_identities', []),
                   *r.get('route_tokens', []), str(r.get('source_id', r['sample_id']))} for r in rows]
    changed = True
    while changed:
        changed = False
        for i in range(len(components)):
            for j in range(i):
                if components[i] & components[j] and components[i] != components[j]:
                    union = components[i] | components[j]
                    components[i] = union
                    components[j] = union
                    changed = True
    for row, component in zip(rows, components):
        row['group_id'] = 'expanded-route-' + hashlib.sha256('\n'.join(sorted(component)).encode()).hexdigest()[:24]
        row['group_identities'] = sorted(component)
        row.update(training_only=True, evaluation_eligible=False)
    for label in classes[136:]:
        entry = next(s for s in catalog['signs'] if s['class_id'] == label)
        if not entry.get('image_path'):
            continue  # No fabricated generic supplementary artwork.
        source = a.repository / 'shared' / entry['image_path']
        rows.append({'sample_id': 'official-artwork-' + label.replace(':', '-'),
                     'group_id': 'official-artwork-' + label,
                     'label': label, 'label_origin': 'official_pictogram',
                     'human_reviewed': False, 'path': str(source.resolve()), 'sha256': sha(source),
                     'training_only': True, 'evaluation_eligible': False,
                     'source_catalog_sha256': sha(catalog_path),
                     'source_asset_manifest_sha256': sha(a.repository / 'shared/tsr/sign-pictograms/manifest.json'),
                     'source_sign_code': entry['sign_code'],
                     'note': 'Official artwork used only for training augmentation; not real-world reference truth.'})
    if len({r['sample_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate sample ID')
    for row in rows:
        if row['label'] not in classes[136:] or sha(row['path']) != row['sha256']:
            raise ValueError('Class or source hash mismatch')
    a.output.mkdir(parents=True)
    (a.output / 'images').mkdir()
    for i, row in enumerate(rows):
        source = Path(row['path'])
        name = 'images/' + f'{i:03d}-' + row['sha256'][:16] + source.suffix
        shutil.copyfile(source, a.output / name)
        row['original_local_path'] = str(source)
        row['path'] = name
        if sha(a.output / name) != row['sha256']:
            raise ValueError('Copied source differs')
    result = {'schema': 'youspeed-new-class-intake-v1', 'samples': rows,
              'class_index_sha256': sha(a.evidence / 'class-index.json'),
              'source_manifests': {str(path.relative_to(a.evidence)): sha(path) for path in (proposals, plates)},
              'counts_by_class': dict(Counter(r['label'] for r in rows)),
              'counts_by_origin': dict(Counter(r['label_origin'] for r in rows)),
              'all_training_only': True, 'human_approved': False,
              'holdout_exclusion_status': 'Required next: preparation enforces frozen identity/pixel/geographic exclusions.',
              'script_sha256': sha(__file__)}
    (a.output / 'new-intake.json').write_text(json.dumps(result, indent=2) + '\n')
    shutil.copyfile(__file__, a.output / 'executed-materializer.py')
    print(json.dumps({'samples': len(rows), 'counts': result['counts_by_class'],
                      'manifest_sha256': sha(a.output / 'new-intake.json')}))


if __name__ == '__main__':
    main()

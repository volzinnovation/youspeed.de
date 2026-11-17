#!/usr/bin/env python3
"""Reserve metadata-qualified geography before any expanded model training.

Mining proposals are not training exposure. This additive exclusion leaves the
original mining membership/policy intact and never reads pixels or label scores.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from full_source_eligibility import distance

ROOT = Path('/home/raphael/streetshots-d5-20261114/expanded-v1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    candidates = json.loads((ROOT/'known-exposure-clear-candidates.json').read_text())
    reserve = candidates['clear_frames']
    assert len(reserve) == 93
    ids = {r['picture_id'] for r in reserve}
    sequences = {s for r in reserve for s in r['sequence_ids']}
    excluded = []
    for line in gzip.open(ROOT/'source-membership.jsonl.gz', 'rt'):
        row = json.loads(line)
        if row['expanded_role'] != 'weak_training':
            continue
        reason = None
        if row['picture_id'] in ids:
            reason = 'qualified_geographic_holdout_identity'
        elif sequences.intersection(row['sequence_ids']):
            reason = 'qualified_geographic_holdout_sequence'
        elif any(distance(row['coordinates'], r['coordinates']) < 500 for r in reserve):
            reason = 'qualified_geographic_holdout_500m_buffer'
        if reason:
            excluded.append({'picture_id': row['picture_id'], 'reason': reason})
    out = {
        'schema': 'streetshots-final-geographic-reserve-v1',
        'selection': 'All metadata-qualified candidates clear of recovered d4 exposure and all previously opened pilot frames; no label, score or image-content selection.',
        'source_membership_sha256': sha(ROOT/'source-membership.jsonl.gz'),
        'candidate_audit_sha256': sha(ROOT/'known-exposure-clear-candidates.json'),
        'known_exposure_sha256': sha(ROOT.parent/'review-inputs/d4-known-exposure.json'),
        'opened_pilot_selection_sha256': sha(ROOT.parent/'inputs/provisional-selection-bw.json'),
        'buffer_m': 500, 'frames': reserve, 'training_exclusions': excluded,
        'counts': {'reserved_images': len(reserve), 'reserved_sequences': len(sequences),
                   'additional_training_exclusions': len(excluded),
                   'exclusion_reasons': dict(Counter(r['reason'] for r in excluded))},
        'label_status': 'Unreviewed; not a scored benchmark yet.',
        'limitation': 'Recovered baseline exposure is incomplete. Upstream pretraining and classifier exposure are unknown. Proposal mining may touch these bytes but expanded optimization may not.'}
    target = ROOT/'final-geographic-reserve.json'
    with target.open('x') as handle:
        handle.write(json.dumps(out, indent=2)+'\n')
    print(json.dumps({'counts': out['counts'], 'sha256': sha(target)}))


if __name__ == '__main__':
    main()

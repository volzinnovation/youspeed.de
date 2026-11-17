#!/usr/bin/env python3
"""Validate complete frozen mining coverage before mixed-dataset assembly."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from pseudo_admission import exclusion_reason

ROOT = Path('/home/raphael/streetshots-d5-20261114/expanded-v1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    policy_path = ROOT/'pseudo-policy.json'
    policy = json.loads(policy_path.read_text())
    assert sha(ROOT/'recipe/mine_full_pseudo_labels.py') == policy['script_sha256']
    assert sha(ROOT/'source-membership.jsonl.gz') == policy['source_membership_sha256']
    rows = {r['picture_id']: r for line in gzip.open(ROOT/'source-membership.jsonl.gz', 'rt')
            if (r := json.loads(line))['expanded_role'] == 'weak_training'}
    statuses = [json.loads((ROOT/f'mining-status-shard{i}.json').read_text()) for i in range(2)]
    if not all(r['complete'] for r in statuses):
        print(json.dumps({'complete':False, 'processed':sum(r['processed'] for r in statuses),
                          'total':len(rows), 'shards':statuses}))
        return
    assert sum(r['processed'] for r in statuses) == len(rows) == 10345
    assert {f.stem for f in (ROOT/'pseudo-labels').glob('*.json')} == set(rows)
    counts, admissions, classes, origins = Counter(), Counter(), Counter(), Counter()
    policy_sha = sha(policy_path)
    record_hashes = {}
    for uid, row in rows.items():
        file = ROOT/'pseudo-labels'/(uid+'.json')
        record = json.loads(file.read_text())
        assert record['picture_id'] == uid and record['image_sha256'] == row['image_sha256']
        assert record['policy_sha256'] == policy_sha
        assert record['annotation_complete'] is False and record['human_verified'] is False
        assert record['width'] > 0 and record['height'] > 0
        for box in record['accepted_boxes']:
            x1,y1,x2,y2 = box['box']
            assert 0 <= x1 < x2 <= record['width'] and 0 <= y1 < y2 <= record['height']
            assert box['scope'] == 'sign' and box['class_confidence'] >= .9
            classes[box['class_label']] += 1
            origins[box['origin']] += 1
        counts[record['status']] += 1
        admissions[exclusion_reason(record) or 'admissible_before_geographic_exclusions'] += 1
        record_hashes[uid] = sha(file)
    shard_counts = Counter()
    for status in statuses:
        shard_counts.update(status['counts'])
    assert shard_counts == counts
    result = {'schema':'streetshots-full-mining-verification-v1', 'complete':True,
              'processed':len(rows), 'total':len(rows), 'counts':dict(counts),
              'post_mining_admission_counts':dict(admissions), 'accepted_class_counts':dict(classes),
              'accepted_origin_counts':dict(origins), 'pseudo_policy_sha256':policy_sha,
              'admission_recipe_sha256':sha(ROOT/'recipe/pseudo_admission.py'),
              'record_hashes':record_hashes}
    target = ROOT/'mining-status.json'
    with target.open('x') as handle:
        handle.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'record_hashes'}))


if __name__ == '__main__':
    main()

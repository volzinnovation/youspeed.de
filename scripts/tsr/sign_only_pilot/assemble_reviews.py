#!/usr/bin/env python3
"""Validate reviewed evidence and export complete one-class scenes only.

This does not infer labels or promote incomplete frames. Source review records
are preserved verbatim; historical truth is provenance, never appended twice.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def box(value, dimensions):
    if not isinstance(value, list) or len(value) != 4 or any(
        isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value
    ):
        raise ValueError('Box must contain four finite numbers')
    x1, y1, x2, y2 = value
    width, height = dimensions
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f'Box outside registered raster: {value}')
    return value


def validate_historical_bindings(historical, originals, final, dimensions, uid):
    """Retained historical truth must resolve to an actual exported box.

    References are provenance only. This function never adds or changes labels.
    Exact unique geometry remains a backwards-compatible implicit reference.
    """
    for decision in historical:
        action = decision['decision']
        has_index = 'final_box_index' in decision
        has_ref = 'final_ref' in decision
        if action == 'reject':
            if has_index or has_ref:
                raise ValueError(f'{uid}: rejected historical box has a final reference')
            continue
        original = originals[decision['index']]['box_xyxy']
        declared = decision.get('box_xyxy', original if action == 'reuse' else None)
        if declared is None:
            raise ValueError(f'{uid}: historical replacement requires final geometry')
        box(declared, dimensions)
        if action == 'reuse' and declared != original:
            raise ValueError(f'{uid}: historical reuse changes geometry; use replace')
        matches = [i for i, item in enumerate(final) if item['box_xyxy'] == declared]
        if len(matches) != 1:
            raise ValueError(f'{uid}: retained historical box lacks a unique final-box counterpart')
        expected = matches[0]
        if has_index:
            index = decision['final_box_index']
            if type(index) is not int or not 0 <= index < len(final) or index != expected:
                raise ValueError(f'{uid}: historical final_box_index does not match geometry')
        if has_ref:
            ref = decision['final_ref']
            refs = []
            for i, item in enumerate(final):
                if item.get('origin') in ('accepted_proposal', 'corrected_proposal'):
                    candidate = 'proposal:' + str(item.get('proposal_id'))
                elif item.get('origin') == 'reviewer_addition' and item.get('id') is not None:
                    candidate = 'additional:' + str(item['id'])
                else:
                    candidate = None
                if candidate is not None and candidate == ref:
                    refs.append(i)
            if refs != [expected]:
                raise ValueError(f'{uid}: historical final_ref does not uniquely match geometry')

def validate_review(review, frame, selection_sha, prepared_versions, asset_hashes, policy_sha):
    uid = frame['picture_id']
    if review['picture_id'] != uid or review.get('reviewer_role') != 'model_assisted_assistant':
        raise ValueError('Wrong review identity or provenance')
    for key, expected in [('selection_sha256', selection_sha),
                          ('original_sha256', frame['original']['sha256']),
                          ('canonical_sha256', frame['canonical']['sha256'])]:
        if review.get(key) != expected:
            raise ValueError(f'{uid}: {key} mismatch')
    policy_bindings = [review[key] for key in ('policy_sha256', 'review_policy_sha256') if key in review]
    if not policy_bindings or any(value != policy_sha for value in policy_bindings):
        raise ValueError(f'{uid}: review must explicitly bind the current policy')
    prior = prepared_versions.get(review.get('prepared_sha256'), {}).get(uid)
    if prior is None:
        raise ValueError(f'{uid}: missing original prepared snapshot')
    # A later completed mining file may be bound only if the actually reviewed
    # per-frame evidence is unchanged. Global completion/timing is immaterial.
    for key in ('original', 'canonical', 'dimensions', 'proposals', 'review_pack', 'existing_truth_boxes'):
        if prior.get(key) != frame.get(key):
            raise ValueError(f'{uid}: prepared evidence changed: {key}')
    proposals = {p['proposal_id']: p for p in frame['proposals']}
    accepted = review['accepted_proposal_ids']
    rejected = review['rejected_proposal_ids']
    corrected = review['corrected_boxes']
    decisions = accepted + rejected + [p['proposal_id'] for p in corrected]
    if len(decisions) != len(set(decisions)) or set(decisions) != set(proposals):
        raise ValueError(f'{uid}: every proposal needs exactly one decision')
    if any(not review.get('rejection_reasons', {}).get(p) for p in rejected):
        raise ValueError(f'{uid}: rejected proposal missing reason')
    historical = review.get('existing_truth_decisions', [])
    indices = [p['index'] for p in historical]
    if any(type(i) is not int for i in indices) or sorted(indices) != list(range(len(frame.get('existing_truth_boxes') or []))):
        raise ValueError(f'{uid}: historical boxes lack explicit unique decisions')
    if any(p.get('decision') not in ('reuse', 'replace', 'reject') or not p.get('reason') for p in historical):
        raise ValueError(f'{uid}: invalid historical decision')
    assets = {}
    for a in review['reviewed_assets']:
        name = Path(a['path']).name
        if name in assets or not re.fullmatch('[a-f0-9]{64}', a.get('sha256', '')):
            raise ValueError(f'{uid}: duplicate or invalid evidence hash')
        assets[name] = a['sha256']
        expected = asset_hashes.get(f'{uid}/{name}')
        if expected is not None and expected != a['sha256']:
            raise ValueError(f'{uid}: evidence asset hash mismatch: {name}')
    pack = frame['review_pack']
    required = [Path(pack['clean']).name, Path(pack['overlay']).name]
    required += [Path(p).name for p in pack['contact_sheets']]
    required += [Path(p['path']).name for p in pack['clean_native_tiles']]
    if any(name not in assets or f'{uid}/{name}' not in asset_hashes for name in required):
        raise ValueError(f'{uid}: full overview, native tiles, overlay and crops must be reviewed')
    complete = review.get('annotation_complete', {}).get('sign')
    if type(complete) is not bool or review['frame_disposition'] != (
        'include' if complete else 'exclude_pending_adjudication'
    ):
        raise ValueError(f'{uid}: inconsistent completeness/disposition')
    if complete and review.get('uncertain_regions'):
        raise ValueError(f'{uid}: unresolved uncertainty in complete scene')
    final = [{'box_xyxy': proposals[p]['box_xyxy'], 'origin': 'accepted_proposal', 'proposal_id': p}
             for p in accepted]
    final += [{**p, 'origin': 'corrected_proposal'} for p in corrected]
    final += [{**p, 'origin': 'reviewer_addition'} for p in review.get('additional_boxes', [])]
    for p in final + review.get('uncertain_regions', []) + review.get('acceptable_extra_candidates', []):
        box(p['box_xyxy'], frame['dimensions'])
    if len({tuple(p['box_xyxy']) for p in final}) != len(final):
        raise ValueError(f'{uid}: duplicate final boxes')
    if any(p.get('kind') != 'traffic_light' for p in review.get('acceptable_extra_candidates', [])):
        raise ValueError(f'{uid}: unsupported acceptable extra class')
    validate_historical_bindings(historical, frame.get('existing_truth_boxes') or [],
                                 final, frame['dimensions'], uid)
    return final


def yolo_text(boxes, dimensions):
    width, height = dimensions
    return ''.join(f'0 {(x1+x2)/(2*width):.10f} {(y1+y2)/(2*height):.10f} '
                   f'{(x2-x1)/width:.10f} {(y2-y1)/height:.10f}\n'
                   for x1, y1, x2, y2 in (b['box_xyxy'] for b in boxes))


def assemble(args):
    selection, prepared, hints = read(args.selection), read(args.prepared), read(args.hints)
    selection_sha, prepared_sha, policy_sha = sha(args.selection), sha(args.prepared), sha(args.policy)
    if prepared.get('completed') is not True or prepared.get('mining_complete') is not True:
        raise ValueError('Mining must be complete')
    if prepared['selection_sha256'] != selection_sha or hints['selection_sha256'] != selection_sha:
        raise ValueError('Selection provenance mismatch')
    frames = {f['picture_id']: f for f in prepared['frames']}
    selected = {f['picture_id']: f for f in selection['frames']}
    if len(frames) != len(prepared['frames']) or frames.keys() != selected.keys():
        raise ValueError('Prepared and selected image sets differ')
    versions, version_paths = {}, {}
    for path in {Path(args.prepared), *Path(args.prepared).parent.glob('prepared*.json'), *Path(args.prepared).parent.glob('prepared*.json.gz')}:
        digest = hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest() if path.suffix == '.gz' else sha(path)
        versions[digest] = {f['picture_id']: f for f in read(path)['frames']}
        version_paths[digest] = path
    reviews, paths = {}, {}
    for directory in args.reviews:
        for path in Path(directory).rglob('*.json'):
            record = read(path)
            uid = record['picture_id']
            if uid not in frames or uid in reviews:
                raise ValueError(f'Unselected or duplicate review: {uid}')
            reviews[uid], paths[uid] = record, path
    missing = sorted(frames.keys() - reviews.keys())
    if missing and not args.audit_only:
        raise ValueError(f'Missing {len(missing)} reviews: {missing}')
    asset_hashes, hint_rows = read(args.asset_hashes), {h['picture_id']: h for h in hints['frames']}
    counts, exported, excluded, bindings = Counter(), [], [], []
    out = Path(args.output) if args.output else None
    if not args.audit_only and (out is None or out.exists()):
        raise ValueError('Choose a new output directory')
    for uid, review in reviews.items():
        frame, source = frames[uid], selected[uid]
        final = validate_review(review, frame, selection_sha, versions, asset_hashes, policy_sha)
        if (frame['split'], frame['group_id'], frame['original']['sha256']) != (
            source['split'], source['group_id'], source['sha256']
        ):
            raise ValueError(f'{uid}: selection identity changed')
        binding = {'picture_id': uid, 'review_sha256': sha(paths[uid]),
                   'reviewed_prepared_sha256': review['prepared_sha256'],
                   'final_prepared_sha256': prepared_sha, 'per_frame_evidence_unchanged': True,
                   'mapillary_hint_set_sha256': hashlib.sha256(json.dumps(hint_rows[uid], sort_keys=True).encode()).hexdigest()}
        bindings.append(binding)
        complete = review['annotation_complete']['sign']
        counts[f'{frame["split"]}_{"included" if complete else "excluded"}'] += 1
        if not complete:
            excluded.append({'picture_id': uid, 'split': frame['split'], 'recoverable_boxes': final,
                             'uncertain_regions': review['uncertain_regions'], 'review_sha256': binding['review_sha256']})
            continue
        label = yolo_text(final, frame['dimensions'])
        width, height = frame['dimensions']
        counts[f'{frame["split"]}_boxes'] += len(final)
        counts[f'{frame["split"]}_negative_scenes'] += not bool(final)
        record = {'image_id': source['image_id'], 'picture_id': uid, 'split': frame['split'],
                  'group_id': frame['group_id'], 'sequence_ids': frame['sequence_ids'],
                  'image_path': f'canonical/{uid}.png', 'image_sha256': frame['canonical']['sha256'],
                  'pixel_sha256': frame['canonical']['rgb_sha256'],
                  'source_image_sha256': frame['original']['sha256'], 'hf_path': frame['hf_path'],
                  'label_path': f'labels/{uid}.txt', 'label_sha256': hashlib.sha256(label.encode()).hexdigest(),
                  'width': width, 'height': height, 'coordinates': frame['coordinates'],
                  'annotation_complete': True, 'review_sha256': binding['review_sha256'],
                  'acceptable_extra_candidates': review.get('acceptable_extra_candidates', []),
                  'boxes': final}
        exported.append(record)
        if not args.audit_only:
            (out / 'labels').mkdir(parents=True, exist_ok=True)
            (out / record['label_path']).write_text(label)
    result = {'counts': dict(counts), 'reviewed': len(reviews), 'selected': len(frames), 'missing': missing}
    if args.audit_only:
        print(json.dumps(result, indent=2))
        return result
    manifest = {'schema': 'streetshots-sign-only-reviewed-v1', 'dataset_repo': selection['dataset_repo'],
                'dataset_revision': selection['dataset_revision'], 'review_provenance': 'model_assisted',
                'claim': 'Assistant visual review, not human-verified ground truth.',
                'selection_sha256': selection_sha, 'prepared_sha256': prepared_sha, 'policy_sha256': policy_sha,
                'mapillary_hints_sha256': sha(args.hints), 'frames': sorted(exported, key=lambda r: r['picture_id'])}
    from train_evaluate import partition_manifest
    partition_manifest(manifest)
    write(out / 'manifest.json', manifest)
    write(out / 'review-bindings.json', bindings)
    write(out / 'excluded-scenes.json', excluded)
    write(out / 'assembly-audit.json', {**result, 'manifest_sha256': sha(out / 'manifest.json')})
    # Preserve the original partial snapshots used during concurrent review,
    # so rebinding to final mining output is independently checkable.
    snapshot_dir = out / 'provenance' / 'prepared-snapshots'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for digest in {r['prepared_sha256'] for r in reviews.values()}:
        suffix = '.json.gz' if version_paths[digest].suffix == '.gz' else '.json'
        shutil.copyfile(version_paths[digest], snapshot_dir / (digest + suffix))
    for uid, path in paths.items():
        destination = out / 'reviews' / f'{uid}.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    for name, path in [('review-policy.json', args.policy), ('selection.json', args.selection),
                       ('mapillary-hints.json', args.hints), ('prepared.json', args.prepared),
                       ('review-asset-hashes.json', args.asset_hashes)]:
        shutil.copyfile(path, out / name)
    print(json.dumps(result, indent=2))
    return result


def stage(manifest_path, canonical_root, dataset_root):
    """On KI, hard-link verified PNGs inside the dataset root (no new encoding)."""
    root = Path(dataset_root).resolve()
    for frame in read(manifest_path)['frames']:
        source = Path(canonical_root) / (frame['picture_id'] + '.png')
        if sha(source) != frame['image_sha256']:
            raise ValueError(f'Canonical SHA mismatch: {source}')
        target = root / frame['image_path']
        if not target.resolve().is_relative_to(root):
            raise ValueError('Unsafe destination')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha(target) != frame['image_sha256']:
                raise ValueError('Existing canonical image differs')
        else:
            os.link(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    review = sub.add_parser('assemble')
    for name in ('selection', 'prepared', 'policy', 'hints', 'asset-hashes'):
        review.add_argument('--' + name, required=True)
    review.add_argument('--reviews', action='append', required=True)
    review.add_argument('--output')
    review.add_argument('--audit-only', action='store_true')
    staging = sub.add_parser('stage')
    for name in ('manifest', 'canonical-root', 'dataset-root'):
        staging.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if args.command == 'assemble':
        assemble(args)
    else:
        stage(args.manifest, args.canonical_root, args.dataset_root)


if __name__ == '__main__':
    main()

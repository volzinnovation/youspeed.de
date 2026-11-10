#!/usr/bin/env python3
"""Freeze route and crossing assignments for a prediction-blind town-sign intake."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from prepare_city_detector_dataset import Components, connect_groups, distance, position


CODES = {'DE:310': 'city:start', 'DE:311': 'city:end', 'city:start': 'city:start', 'city:end': 'city:end'}
CLASSES = ('city:start', 'city:end')
QUOTAS = {'test': dict(zip(CLASSES, (50, 50))), 'dev': dict(zip(CLASSES, (25, 25))),
          'train': dict(zip(CLASSES, (50, 60)))}
SMALL_TRAIN_QUOTAS = dict(zip(CLASSES, (50, 50)))
RADIUS_M = 250
CROSSING_ALIAS_M = 20
SCHEMA = 'youspeed-city-collection-route-plan-v1'
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    data = path.read_bytes()
    return json.loads(data), digest(data)


def fields(row, single, multiple):
    values = list(row.get(multiple) or [])
    if row.get(single) is not None:
        values.append(row[single])
    return sorted({str(value) for value in values if value})


def identity_row(row):
    """Bind crossing pairs and exact crop identities alongside full-frame identities."""
    item = dict(row)
    item['picture_id'] = row.get('picture_id') or row.get('image_id')
    item['sequence_ids'] = fields(row, 'sequence_id', 'sequence_ids')
    item['crossing_ids'] = fields(row, 'crossing_id', 'crossing_ids')
    route_tokens = set(row.get('route_tokens') or [])
    picture_ids = fields(row, 'picture_id', 'picture_alias_ids')
    if item['picture_id'] and str(item['picture_id']) not in picture_ids:
        picture_ids.append(str(item['picture_id']))
    route_tokens.update(f'city-picture:{value}' for value in picture_ids)
    route_tokens.update(f"city-crop-bytes:{value}" for value in fields(row, 'crop_sha256', 'crop_sha256s'))
    route_tokens.update(f"city-crop-rgb:{value}" for value in fields(row, 'crop_rgb_sha256', 'crop_rgb_sha256s'))
    item['route_tokens'] = sorted(route_tokens)
    physical = set(fields(row, 'physical_sign_id', 'physical_sign_ids'))
    physical.update(f'crossing:{value}' for value in item['crossing_ids'])
    item['physical_sign_ids'] = sorted(physical)
    return item


def with_crossing_anchors(rows):
    result = [identity_row(row) for row in rows]
    for row in rows:
        point = row.get('crossing_coordinates')
        crossings = fields(row, 'crossing_id', 'crossing_ids')
        if point is not None and crossings:
            result.append(identity_row({'crossing_ids': crossings, 'coordinates': point}))
    return result


def candidates(document):
    yield from document.get('frames', [])
    for site in document.get('sites', []):
        crossing = site.get('crossing_id')
        if not crossing or position(site) is None:
            raise ValueError('Site intake needs an explicit crossing identity and location')
        for frame in site.get('frames', []):
            if frame.get('crossing_id', crossing) != crossing:
                raise ValueError(f'Frame crossing differs from its parent site: {crossing}')
            yield {**frame, 'crossing_id': crossing, 'crossing_coordinates': site['coordinates']}


def observations(row):
    """Reference rectangles take priority over expected classes inferred from location."""
    for box in row.get('boxes', []):
        code = CODES.get(box.get('class_id') or box.get('source_code'))
        if not code:
            continue
        bounds = box.get('bbox_xyxy')
        height = row.get('height')
        width = row.get('width')
        edge = None
        if bounds and height and width:
            x1, y1, x2, y2 = bounds
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError(f"Town-sign rectangle outside registered raster: {row['picture_id']}")
            edge = min(x2-x1, y2-y1)*1024/height
        yield code, box.get('annotation_id') if edge is not None else None, edge
    if not row.get('boxes'):
        code = CODES.get(row.get('expected_class'))
        if code:
            yield code, None, None


def reference_rank(row, annotation, edge, split):
    # Small reference rectangles get priority in training. No detector output is read.
    if edge is None:
        edge = row.get('estimated_small_edge_px')
    small = edge is not None and edge < 32
    view_error = row.get('view_error_deg')
    if view_error is None and row.get('camera_heading') is not None and row.get('bearing_to_crossing') is not None:
        view_error = abs((row['camera_heading']-row['bearing_to_crossing']+180) % 360-180)
    return (annotation is None, split == 'train' and not small,
            view_error if view_error is not None else float('inf'), row['picture_id'], annotation or '')


def nearby_crossing_aliases(rows):
    """Use a conservative common quota identity for neighboring map anchors."""
    points = {}
    for row in rows:
        point = row.get('crossing_coordinates')
        if point is not None:
            for crossing in row['crossing_ids']:
                points.setdefault(crossing, position({'coordinates': point}))
    ordered = sorted(points)
    groups = Components(len(ordered))
    for i, first in enumerate(ordered):
        for j, second in enumerate(ordered[:i]):
            if distance(points[first], points[second]) <= CROSSING_ALIAS_M:
                groups.union(j, i)
    canonical = {}
    for i, crossing in enumerate(ordered):
        canonical.setdefault(groups.find(i), crossing)
    return {crossing: canonical[groups.find(i)] for i, crossing in enumerate(ordered)
            if canonical[groups.find(i)] != crossing}


def slots(group, split, aliases):
    """One target per crossing face, with same-split candidate views as alternatives."""
    by_face = defaultdict(dict)
    sites_by_picture = defaultdict(set)
    hints_by_picture = defaultdict(set)
    for row in group['rows']:
        sites_by_picture[row['picture_id']].update(aliases.get(site, site) for site in row['crossing_ids'])
        if row.get('expected_class') in CODES:
            hints_by_picture[row['picture_id']].add(CODES[row['expected_class']])
    for row in group['rows']:
        if row.get('projection') in {'spherical', 'equirectangular', 'projected_perspective'}:
            continue
        if not row['sequence_ids'] or position(row) is None:
            continue
        sites = sites_by_picture[row['picture_id']]
        if len(sites) > 1:
            # Source GPS alone cannot establish which of multiple proposed crossings is pictured.
            continue
        crossing = next(iter(sites), None)
        site = str(crossing) if crossing else f"unresolved:{group['id']}"
        for code, annotation, edge in observations(row):
            if annotation is None and len(hints_by_picture[row['picture_id']]) > 1:
                continue
            target = {'picture_id': row['picture_id'], 'annotation_id': annotation,
                      'nominal_mobile_short_edge_px': edge,
                      'geometry_size_proxy_px': row.get('estimated_small_edge_px'),
                      'source_crossing_ids': row['crossing_ids'],
                      'reference': 'registered_source_box_proposal' if annotation else 'site_class_hint'}
            rank = reference_rank(row, annotation, edge, split)
            # A duplicate reference to the same frame cannot supply another view of a face.
            previous = by_face[(site, code)].get(row['picture_id'])
            if previous is None or rank < previous[0]:
                by_face[(site, code)][row['picture_id']] = (rank, target)
    return [{'site': site, 'class_id': code, 'mapped_crossing_id': None if site.startswith('unresolved:') else site,
             'views': [target for _, target in sorted(views.values(), key=lambda pair: pair[0])]}
            for (site, code), views in sorted(by_face.items())]


def allocation_targets(groups):
    """Scale quota targets by available face slots, using whole components."""
    usable = [group for group in groups if group['slots']['test']]
    splits = ('test', 'dev', 'train') if len(usable) >= 3 else ('test', 'train')[:len(usable)]
    totals = Counter(slot['class_id'] for group in usable for slot in group['slots']['test'])
    targets = {split: {code: 0 for code in CLASSES} for split in QUOTAS}
    for code in CLASSES:
        total_target = sum(QUOTAS[split][code] for split in splits)
        count = min(totals[code], total_target)
        # Protect test and training coverage before development when fewer than
        # three face slots exist for a class. Allocate the rest proportionally.
        minimum_order = [split for split in ('test', 'train', 'dev') if split in splits]
        for split in minimum_order[:count]:
            targets[split][code] = 1
        ideal = {split: count*QUOTAS[split][code]/total_target for split in splits}
        for _ in range(max(0, count-len(minimum_order))):
            split = max((split for split in splits if targets[split][code] < QUOTAS[split][code]),
                        key=lambda split: ideal[split]-targets[split][code])
            targets[split][code] += 1
    # With very sparse class support the class-by-class minimums may leave an
    # otherwise feasible development partition empty. Shift one abundant lead.
    for split in splits:
        if not any(targets[split].values()):
            donor = max(splits, key=lambda name: sum(targets[name].values()))
            code = max((code for code in CLASSES if targets[donor][code]), key=lambda code: totals[code])
            targets[donor][code] -= 1
            targets[split][code] += 1
    return usable, targets, splits


def reserve(groups, split, targets, keep_free, prefer_test_breadth):
    """Allocate complete components with a deterministic, quota-capped reference queue."""
    quota = QUOTAS[split]
    requested = Counter(targets)
    small_requested = Counter(SMALL_TRAIN_QUOTAS if split == 'train' else {})
    assigned = []
    chosen = []
    while len(groups) > keep_free:
        def rank(group):
            support = Counter(slot['class_id'] for slot in group['slots'][split])
            small = Counter(slot['class_id'] for slot in group['slots'][split]
                            if is_small(slot, allow_proxy=True))
            gain = sum(min(requested[code], support[code]) for code in CLASSES)
            small_gain = sum(min(small_requested[code], small[code], requested[code]) for code in CLASSES)
            # In the breadth alternative, two useful faces beat a larger
            # cluster with excess near-duplicate support.
            ranked_gain = min(gain, 2) if split == 'test' and prefer_test_breadth else gain
            return -small_gain, -ranked_gain, sum(support.values())-ranked_gain, group['id']
        useful = [group for group in groups if rank(group)[1] < 0]
        if useful:
            group = min(useful, key=rank)
        elif assigned or not any(requested.values()):
            break
        else:
            # Cross-class components can make proportional class targets impossible.
            # Preserve a nonempty split using any remaining class within original quotas.
            group = min(groups, key=lambda g: (len(g['slots'][split]), g['id']))
            code = group['slots'][split][0]['class_id']
            requested[code] = 1
        groups.remove(group)
        assigned.append(group)
        group['split'] = split
        references = group['slots'][split]
        if split == 'train':
            references = sorted(references, key=lambda slot: not is_small(slot, allow_proxy=True))
        for slot in references:
            code = slot['class_id']
            if requested[code] <= 0:
                continue
            if is_small(slot) and small_requested[code] > 0:
                small_requested[code] -= 1
            chosen.append({**slot, 'component_id': group['id']})
            requested[code] -= 1
    count = Counter(slot['class_id'] for slot in chosen)
    shortage = {code: quota[code]-count[code] for code in CLASSES}
    return assigned, chosen, shortage, dict(small_requested)


def is_small(slot, allow_proxy=False):
    target = slot['views'][0]
    edge = target['nominal_mobile_short_edge_px']
    if edge is None and allow_proxy:
        edge = target['geometry_size_proxy_px']
    return edge is not None and edge < 32


def allocate_primary(groups, prefer_test_breadth):
    groups = [dict(group) for group in groups]
    available = [group for group in groups if not group['exclusion_reasons']]
    available, targets, active_splits = allocation_targets(available)
    queue = {}
    for index, split in enumerate(QUOTAS):
        keep_free = sum(any(targets[later].values()) for later in list(QUOTAS)[index+1:]
                        if later in active_splits)
        assigned, chosen, shortage, small_shortage = reserve(available, split, targets[split], keep_free,
                                                            prefer_test_breadth)
        queue[split] = summarize_queue(assigned, chosen, shortage, small_shortage, targets[split])
    return groups, queue, active_splits


def allocation_score(allocation):
    _, queue, _ = allocation
    counts = {split: len(value['target_slots']) for split, value in queue.items()}
    return (sum(counts.values()), counts['test'], counts['dev'], queue['test']['components'])


def reserve_backfill(groups, queue, active_splits):
    counts = Counter()
    for group in groups:
        if group['split'] in QUOTAS:
            counts[group['split']] += len(group['slots'][group['split']])
    unallocated = [group for group in groups if group['split'] == 'unallocated' and group['slots']['test']]
    unallocated.sort(key=lambda group: (-len(group['slots']['test']), group['id']))
    for group in unallocated:
        split = min(active_splits, key=lambda name: counts[name]/sum(QUOTAS[name].values()))
        group['split'] = split
        counts[split] += len(group['slots'][split])
    for split, stats in queue.items():
        primary = {(slot['site'], slot['class_id']) for slot in stats['target_slots']}
        assigned = [group for group in groups if group['split'] == split]
        backfill = [{**slot, 'component_id': group['id']} for group in assigned for slot in group['slots'][split]
                    if (slot['site'], slot['class_id']) not in primary]
        stats.update(reserve_target_slots=backfill,
                     reserve_slots_by_class=dict(Counter(slot['class_id'] for slot in backfill)),
                     assigned_components=len(assigned))


def apply_receipt(rows, receipt):
    known = {row['picture_id'] for row in rows}
    verified = {}
    for frame in receipt.get('frames', []):
        picture = frame.get('picture_id') or frame.get('image_id')
        if (picture not in known or picture in verified or frame.get('image_verification_complete') is not True
                or frame.get('exif_orientation') != 1):
            raise ValueError('Image receipt needs an exact unique candidate, verified upright full frame')
        hashes = {key: frame.get(key) for key in ('image_sha256', 'rgb_sha256')}
        if not all(isinstance(value, str) and SHA256.fullmatch(value) for value in hashes.values()):
            raise ValueError(f'Missing or invalid image digests: {picture}')
        dimensions = [frame.get('width'), frame.get('height')]
        if not all(type(value) is int and value > 0 for value in dimensions):
            raise ValueError(f'Missing verified raster dimensions: {picture}')
        verified[picture] = (hashes, dimensions)
    for row in rows:
        if row['picture_id'] not in verified:
            continue
        hashes, dimensions = verified[row['picture_id']]
        expected = row.get('frame_size') or [row.get('width'), row.get('height')]
        if all(expected) and list(expected) != dimensions:
            raise ValueError(f"Verified dimensions differ from source metadata: {row['picture_id']}")
        row.update(hashes)
    return set(verified)


def make_plan(documents, guard, frozen=None, receipt=None):
    rows = [identity_row(row) for doc in documents for row in candidates(doc)]
    if not all(row.get('picture_id') for row in rows):
        raise ValueError('Candidate source picture identity is required')
    verified = apply_receipt(rows, receipt) if receipt is not None else set()
    aliases = nearby_crossing_aliases(rows)
    nodes = with_crossing_anchors(rows)
    protected = with_crossing_anchors(guard['frames'])
    if not protected:
        raise ValueError('Historical exposure guard cannot be empty')
    _, components, blocked = connect_groups(nodes, protected, RADIUS_M)
    by_root = defaultdict(list)
    by_image_digest = defaultdict(set)
    for index, row in enumerate(rows):
        by_root[components.find(index)].append(row)
        for value in fields(row, 'image_sha256', 'image_sha256s') + fields(row, 'source_image_sha256', 'source_image_sha256s'):
            by_image_digest[('bytes', value)].add(row['picture_id'])
        if row.get('rgb_sha256'):
            by_image_digest[('rgb', row['rgb_sha256'])].add(row['picture_id'])
    duplicated_pictures = {picture for same in by_image_digest.values() if len(same) > 1 for picture in same}
    groups = []
    for root, members in by_root.items():
        pictures = sorted({row['picture_id'] for row in members})
        crossings = sorted({site for row in members for site in row['crossing_ids']})
        seqs = sorted({seq for row in members for seq in row['sequence_ids']})
        group_id = 'city-' + digest(json.dumps([pictures, crossings, seqs]).encode())[:20]
        reasons = ['historical_exposure_component'] if root in blocked else []
        if any(row.get('detector_guided_review') for row in members):
            reasons.append('detector_guided_component')
        if duplicated_pictures.intersection(pictures):
            reasons.append('duplicate_full_image_with_distinct_picture_ids')
        group = {'id': group_id, 'pictures': pictures, 'crossings': crossings, 'sequences': seqs,
                 'rows': members, 'exclusion_reasons': reasons,
                 'split': 'excluded' if reasons else 'unallocated'}
        group['slots'] = {split: slots(group, split, aliases) for split in QUOTAS}
        groups.append(group)
    groups.sort(key=lambda group: group['id'])
    queue = {}
    allocation_policy = None
    if frozen is None:
        breadth = allocate_primary(groups, prefer_test_breadth=True)
        coverage = allocate_primary(groups, prefer_test_breadth=False)
        prefer_breadth = allocation_score(breadth) >= allocation_score(coverage)
        groups, queue, active_splits = breadth if prefer_breadth else coverage
        allocation_policy = 'test_route_breadth' if prefer_breadth else 'quota_coverage'
        reserve_backfill(groups, queue, active_splits)
    else:
        allocation_policy = frozen['allocation_policy']
        old = {picture: group['split'] for group in frozen['components'] for picture in group['pictures']}
        if set(old) != {picture for group in groups for picture in group['pictures']}:
            raise ValueError('Hash re-audit needs exactly the frozen source picture set')
        for group in groups:
            prior_splits = sorted({old[picture] for picture in group['pictures']})
            group['frozen_splits'] = prior_splits
            if len(prior_splits) > 1:
                group['exclusion_reasons'].append('cross_split_identity_or_route_merge')
            group['split'] = 'excluded' if group['exclusion_reasons'] else prior_splits[0]
        allowed = {picture: group for group in groups if group['split'] in QUOTAS for picture in group['pictures']}
        for split in QUOTAS:
            assigned = [group for group in groups if group['split'] == split]
            # Keep the exact pre-scoring queue. An exposure collision shrinks it.
            def surviving(slots):
                return [{**slot, 'component_id': allowed[slot['views'][0]['picture_id']]['id']}
                        for slot in slots if all(view['picture_id'] in allowed for view in slot['views'])]
            chosen = surviving(frozen['queues'][split]['target_slots'])
            backfill = surviving(frozen['queues'][split].get('reserve_target_slots', []))
            counts = Counter(slot['class_id'] for slot in chosen)
            small = Counter(slot['class_id'] for slot in chosen if is_small(slot))
            shortage = {code: QUOTAS[split][code]-counts[code] for code in CLASSES}
            small_shortage = {code: max(0, SMALL_TRAIN_QUOTAS[code]-small[code]) for code in CLASSES} if split == 'train' else {}
            planned = frozen['queues'][split]['proportional_planning_targets']
            primary = {slot['component_id'] for slot in chosen}
            queue[split] = summarize_queue([g for g in assigned if g['id'] in primary], chosen, shortage, small_shortage, planned)
            queue[split].update(reserve_target_slots=backfill,
                                reserve_slots_by_class=dict(Counter(slot['class_id'] for slot in backfill)),
                                assigned_components=len(assigned))
    report = {'schema': SCHEMA, 'proximity_m': RADIUS_M, 'status': 'metadata_plan' if frozen is None else 'hash_reaudit',
              'nearby_map_anchor_alias_radius_m': CROSSING_ALIAS_M, 'map_anchor_aliases': aliases,
              'allocation_policy': allocation_policy,
              'candidate_picture_count': len({row['picture_id'] for row in rows}),
              'candidate_record_count': len(rows), 'components': [], 'queues': queue,
              'verified_receipt_pictures': len(verified),
              'training_launch_ready': False, 'independent_human_review': False,
              'limitations': [
                  'Quota slots are provisional source rectangles or site-class leads. Human review must verify labels and crossing identity.',
                  'An unresolved crossing contributes at most one target per class per connected component.',
                  'One view per site and class contributes to quotas. Additional views remain in the same split.',
                  'Mapped anchors within 20 m share a quota identity. Confirm physical crossing identity during review.',
                  'For shortfalls, scale each class proportionally to requested test/development/training targets. Reserve test first and retain whole components for later splits where feasible.',
                  'Prefer the quota-complete allocation with more test components. Reserve backfill stays within its frozen split.',
                  'Only metadata and supplied hashes are read. Image-byte verification and accepted labels are separate requirements.',
                  'Freeze test assignments before detector-guided annotation. Re-audit verified full-frame and crop hashes before use.',
              ]}
    for group in groups:
        report['components'].append({key: val for key, val in group.items() if key not in ('rows', 'slots')})
    for stats in queue.values():
        stats['slots_with_verified_receipt'] = sum(any(view['picture_id'] in verified for view in slot['views'])
                                                   for slot in stats['target_slots'])
    return report


def summarize_queue(assigned, chosen, shortage, small_shortage, planned):
    return {'components': len(assigned), 'target_slots': chosen, 'slots_by_class': dict(Counter(s['class_id'] for s in chosen)),
            'mapped_crossings': len({s['mapped_crossing_id'] for s in chosen if s['mapped_crossing_id']}),
            'registered_box_proposals': sum(s['views'][0]['reference'] == 'registered_source_box_proposal' for s in chosen),
            'small_size_proxy_by_class': dict(Counter(s['class_id'] for s in chosen
                if is_small(s, allow_proxy=True) and not is_small(s))),
            'proportional_planning_targets': planned,
            'shortage_by_class': shortage, 'small_training_shortage_by_class': small_shortage}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard', type=Path, required=True)
    parser.add_argument('--candidates', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frozen-plan', type=Path)
    parser.add_argument('--image-receipt', type=Path, help='Verified full-frame byte/RGB hashes for a frozen subset')
    args = parser.parse_args()
    guard, guard_sha = read(args.guard)
    docs = [read(path) for path in args.candidates]
    candidate_hashes = [sha for _, sha in docs]
    frozen, frozen_sha = read(args.frozen_plan) if args.frozen_plan else (None, None)
    receipt, receipt_sha = read(args.image_receipt) if args.image_receipt else (None, None)
    if receipt is not None and (frozen is None or receipt.get('plan_sha256') != frozen_sha):
        raise ValueError('Verify materialized images against the exact pre-review route freeze')
    if frozen is not None and (frozen.get('schema') != SCHEMA or frozen['guard_sha256'] != guard_sha
                               or frozen['candidates_sha256'] != candidate_hashes):
        raise ValueError('Hash re-audit requires the original frozen metadata and guard')
    plan = make_plan([data for data, _ in docs], guard, frozen, receipt)
    plan.update(guard_sha256=guard_sha, candidates_sha256=candidate_hashes, frozen_plan_sha256=frozen_sha,
                image_receipt_sha256=receipt_sha, planner_sha256=digest(Path(__file__).read_bytes()))
    with args.output.open('x') as stream:
        json.dump(plan, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(args.output), 'sha256': digest(args.output.read_bytes()),
                      'queues': {split: {key: value for key, value in stats.items() if key not in ('target_slots', 'reserve_target_slots')}
                                 for split, stats in plan['queues'].items()}}, indent=2))


if __name__ == '__main__':
    main()

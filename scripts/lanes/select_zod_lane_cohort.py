#!/usr/bin/env python3
"""Predeclare a ZOD cohort from ALL original metadata, before inspecting images.

No images or annotations are downloaded/read. Both modes include every original
source row, including unselected and blacklisted frames. Legacy components-v1
uses transitive vehicle/day and geographic components. Vehicle-day-direct-v2
keeps whole vehicle/day nodes and purges training nodes sharing a holdout day or
a direct 250 m adjacency edge. It excludes previously exposed whole days from
holdout, without claiming unseen geographic regions. Unused official validation
rows never train. Every cohort fixes its mode, seed, grouping proof and QA plan.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from prepare_zod_lane_corpus import assign_day_graph, assign_groups, read_records, sha256_file, write_json


def ranked(value, seed, purpose):
    return hashlib.sha256(f"{seed}:{purpose}:{value}".encode()).digest()


def interleave(groups, count, seed, purpose):
    buckets = [sorted(rows, key=lambda row: ranked(row['frame_id'], seed, purpose))
        for _, rows in sorted(groups.items(), key=lambda item: ranked(item[0], seed, purpose + '-groups'))]
    result, depth = [], 0
    while len(result) < count:
        added = [rows[depth] for rows in buckets if len(rows) > depth]
        if not added:
            raise ValueError("Insufficient predeclared cohort candidates")
        result.extend(added[:count - len(result)])
        depth += 1
    return result


def choose_cohort(records, exposure_ids, train_count=1024, test_count=128,
                  seed="zod-scale-20261009-v1", proximity_m=250., min_test_groups=8,
                  excluded_train_ids=(), target_test_groups=16):
    if any(type(v) is not int or v <= 0 for v in (train_count, test_count, min_test_groups, target_test_groups)) or not min_test_groups <= target_test_groups <= test_count:
        raise ValueError("Invalid cohort counts")
    if not isinstance(seed, str) or not seed:
        raise ValueError("Nonempty predeclared seed required")
    all_ids = {r['frame_id'] for r in records}
    exposure_ids, excluded_train_ids = set(exposure_ids), set(excluded_train_ids)
    if not exposure_ids <= all_ids or not excluded_train_ids <= all_ids:
        raise ValueError("Exposure/QA exclusion IDs absent from full source")
    groups = assign_groups(records, proximity_m)
    exposed_groups = {r['group_id'] for r in records if r['frame_id'] in exposure_ids}
    train_by_group, test_by_group = defaultdict(list), defaultdict(list)
    for row in records:
        if row['official_split'] == 'train' and row['frame_id'] not in excluded_train_ids:
            train_by_group[row['group_id']].append(row)
        if row['official_split'] == 'val' and row['group_id'] not in exposed_groups:
            test_by_group[row['group_id']].append(row)
    available_train = sum(map(len, train_by_group.values()))
    selected_test_groups, test_candidates, skipped = [], 0, []
    for identity in sorted(test_by_group, key=lambda value: ranked(value, seed, 'holdout-groups')):
        cost = len(train_by_group.get(identity, []))
        if available_train - cost < train_count:
            skipped.append(identity)
            continue
        selected_test_groups.append(identity)
        available_train -= cost
        test_candidates += len(test_by_group[identity])
        if (sum(min(len(test_by_group[k]), math.ceil(test_count / target_test_groups)) for k in selected_test_groups) >= test_count
                and len(selected_test_groups) >= target_test_groups):
            break
    if test_candidates < test_count or len(selected_test_groups) < min_test_groups or available_train < train_count:
        raise ValueError("Insufficient disjoint fresh cohort: " + json.dumps({
            'full_frames': len(records), 'full_groups': len(groups), 'exposed_groups': len(exposed_groups),
            'fresh_val_groups': len(test_by_group), 'fresh_val_frames': sum(map(len, test_by_group.values())),
            'reserved_test_groups': len(selected_test_groups), 'reserved_test_candidates': test_candidates,
            'remaining_train_candidates': available_train, 'requested_train': train_count,
            'requested_test': test_count, 'required_test_groups': min_test_groups}, sort_keys=True))
    held = set(selected_test_groups)
    test_group_cap = math.ceil(test_count / min(target_test_groups, len(held)))
    bounded_test_groups = {k:sorted(test_by_group[k], key=lambda row: ranked(row['frame_id'], seed, 'test-frames'))[:test_group_cap] for k in held}
    if sum(map(len,bounded_test_groups.values())) < test_count:
        raise ValueError('Insufficient fresh holdout after predeclared per-component cap: ' + str(test_group_cap))
    selected_train = interleave({k:v for k,v in train_by_group.items() if k not in held}, train_count, seed, 'train-frames')
    selected_test = interleave(bounded_test_groups, test_count, seed, 'test-frames')
    selected = {r['frame_id']: 'train' for r in selected_train}
    selected.update({r['frame_id']: 'test' for r in selected_test})
    return selected, {
        'method': 'all-source-vehicle-day-or-spherical-proximity-components-v2', 'proximity_m': proximity_m,
        'full_source_count': len(records), 'full_group_count': len(groups), 'exposed_group_count': len(exposed_groups),
        'exposure_policy': 'Exclude entire components containing exposed IDs from fresh holdout',
        'holdout_policy': 'Reserve selected official-val components; exclude their official-train rows; unused official-val never trains',
        'selection_policy': 'Seed-ranked groups with training-capacity guard; round-robin seed-ranked frames across groups; no metric-driven refill',
        'seed': seed, 'requested_train': train_count, 'requested_test': test_count, 'min_test_groups': min_test_groups, 'target_test_groups': target_test_groups, 'test_group_frame_cap': test_group_cap,
        'selected_test_group_ids': sorted(held), 'selected_train_group_count': len({r['group_id'] for r in selected_train}),
        'selected_test_group_count': len({r['group_id'] for r in selected_test}),
        'skipped_holdout_groups_for_train_capacity': skipped,
        'known_qa_excluded_train_ids': sorted(excluded_train_ids),
        'partition_counts': {'train':len(selected_train),'test':len(selected_test)},
        'selected_previously_exposed_train_count': sum(r['frame_id'] in exposure_ids for r in selected_train)}


def choose_day_cohort(records, exposure_ids, train_count=1024, test_count=128,
                      seed='zod-scale-20261009-v2', proximity_m=250., min_test_groups=8,
                      excluded_train_ids=(), target_test_groups=16):
    if any(type(v) is not int or v<=0 for v in (train_count,test_count,min_test_groups,target_test_groups)) or not min_test_groups<=target_test_groups<=test_count:
        raise ValueError('Invalid cohort counts')
    if not isinstance(seed,str) or not seed:
        raise ValueError('Nonempty predeclared seed required')
    all_ids={r['frame_id'] for r in records}
    exposure_ids,excluded_train_ids=set(exposure_ids),set(excluded_train_ids)
    if not exposure_ids<=all_ids or not excluded_train_ids<=all_ids:
        raise ValueError('Exposure/QA exclusion IDs absent from full source')
    graph=assign_day_graph(records,proximity_m)
    adjacent=defaultdict(set)
    for edge in graph['edges']:
        a,b=edge['nodes'];adjacent[a].add(b);adjacent[b].add(a)
    exposed={r['group_id'] for r in records if r['frame_id'] in exposure_ids}
    train,test=defaultdict(list),defaultdict(list)
    for row in records:
        if row['official_split']=='train' and row['frame_id'] not in excluded_train_ids:
            train[row['group_id']].append(row)
        if row['official_split']=='val' and row['group_id'] not in exposed:
            test[row['group_id']].append(row)
    held,blocked=set(),set()
    cap=math.ceil(test_count/target_test_groups)
    for identity in sorted(test,key=lambda value:ranked(value,seed,'holdout-groups')):
        proposed=blocked|{identity}|adjacent[identity]
        if sum(len(v) for k,v in train.items() if k not in proposed)<train_count:
            continue
        held.add(identity);blocked=proposed
        if len(held)>=target_test_groups and sum(min(cap,len(test[k])) for k in held)>=test_count:
            break
    if len(held)<min_test_groups or sum(min(cap,len(test[k])) for k in held)<test_count:
        raise ValueError('Insufficient direct-day cohort: '+json.dumps({'fresh_val_days':len(test),
            'fresh_val_frames':sum(map(len,test.values())),'reserved_days':len(held),'cap':cap,
            'capacity':sum(min(cap,len(test[k])) for k in held)}))
    bounded={k:sorted(test[k],key=lambda row:ranked(row['frame_id'],seed,'test-frames'))[:cap] for k in held}
    selected_train=interleave({k:v for k,v in train.items() if k not in blocked},train_count,seed,'train-frames')
    selected_test=interleave(bounded,test_count,seed,'test-frames')
    selected={r['frame_id']:'train' for r in selected_train}
    selected.update({r['frame_id']:'test' for r in selected_test})
    exposed_neighbors=exposed|{n for e in exposed for n in adjacent[e]}
    grouping={'method':graph['method'],'proximity_m':proximity_m,'full_source_count':len(records),
        'full_group_count':len(graph['nodes']),'direct_edge_count':len(graph['edges']),
        'exposure_policy':'Exclude whole previously exposed vehicle/day nodes E from holdout; neighboring unselected days may contain prior analyst exposure; no unseen-geographic-region claim',
        'holdout_policy':'Official-val only, whole vehicle/day identity; all train days in H union direct N(H) purged; unused official-val never trains',
        'selection_policy':'Seed-ranked day reservation with training-capacity guard; round-robin seed-ranked frames; cap per holdout day; no QA/metric-driven refill',
        'seed':seed,'requested_train':train_count,'requested_test':test_count,'min_test_groups':min_test_groups,
        'target_test_groups':target_test_groups,'test_group_frame_cap':cap,
        'selected_test_group_ids':sorted(held),'purged_train_group_ids':sorted(blocked),
        'selected_train_group_count':len({r['group_id'] for r in selected_train}),
        'selected_test_group_count':len({r['group_id'] for r in selected_test}),
        'exposed_group_count':len(exposed),'fresh_val_group_count':len(test),'fresh_val_frame_count':sum(map(len,test.values())),
        'remaining_train_candidate_count':sum(len(v) for k,v in train.items() if k not in blocked),
        'conservative_exposure_and_neighbors':{'excluded_days':len(exposed_neighbors),
            'fresh_val_days':sum(k not in exposed_neighbors for k in test),
            'fresh_val_frames':sum(len(v) for k,v in test.items() if k not in exposed_neighbors)},
        'known_qa_excluded_train_ids':sorted(excluded_train_ids),
        'partition_counts':{'train':len(selected_train),'test':len(selected_test)},
        'selected_previously_exposed_train_count':sum(r['frame_id'] in exposure_ids for r in selected_train)}
    return selected,grouping,graph


def select(dataset_root, trainval_path, exposure_path, output, train_count=1024, test_count=128,
           seed='zod-scale-20261009-v1', proximity_m=250., min_test_groups=8,
           expected_source_frames=100000, prior_receipt_path=None, target_test_groups=16, full_review_train_count=32, training_input_size=640, grouping_mode='components-v1'):
    output, dataset_root = Path(output).resolve(), Path(dataset_root).resolve()
    repository = Path(__file__).resolve().parents[2]
    if output.exists() or output == repository or repository in output.parents:
        raise ValueError('Choose a new output directory outside the repository')
    if type(full_review_train_count) is not int or not 0 <= full_review_train_count <= train_count:
        raise ValueError('Invalid predeclared training QA count')
    if type(training_input_size) is not int or not 32 <= training_input_size <= 1280 or training_input_size % 32:
        raise ValueError('Invalid predeclared training input size')
    exposure = json.loads(Path(exposure_path).read_text())
    ids = exposure.get('frame_ids')
    if (exposure.get('schemaVersion') != 1 or not isinstance(ids, list) or not ids
            or any(not isinstance(v,str) or not re.fullmatch(r'\d{6}',v) for v in ids) or len(ids) != len(set(ids))):
        raise ValueError('Expected explicit unique prior-exposure frame IDs')
    records = read_records(dataset_root, trainval_path, require_assets=False, include_blacklisted=True)
    if type(expected_source_frames) is not int or expected_source_frames <= 0 or len(records) != expected_source_frames:
        raise ValueError(f'Expected full source {expected_source_frames} records, found {len(records)}; never group a subset as full source')
    known_exclusions = []
    if prior_receipt_path is not None:
        prior = json.loads(Path(prior_receipt_path).read_text())
        known_exclusions = [r['frame_id'] for r in prior['frame_qa']['frames'] if r['decision'] == 'exclude']
    if grouping_mode not in ('components-v1','vehicle-day-direct-v2'):
        raise ValueError('Unknown grouping mode')
    failure,graph = None,None
    try:
        if grouping_mode=='components-v1':
            selected, grouping = choose_cohort(records, ids, train_count, test_count, seed, proximity_m, min_test_groups, known_exclusions, target_test_groups)
        else:
            selected,grouping,graph=choose_day_cohort(records,ids,train_count,test_count,seed,proximity_m,min_test_groups,known_exclusions,target_test_groups)
    except ValueError as error:
        if not str(error).startswith('Insufficient'):
            raise
        failure = error
    source_rows = []
    for row in sorted(records,key=lambda r:r['frame_id']):
        source_rows.append({key:row[key] for key in ('frame_id','official_split','group_id','metadata','collection_car','capture_date','latitude','longitude')})
        source_rows[-1]['metadata_sha256'] = row['metadata_sha256']
    output.mkdir(parents=True)
    graph_file='full-source-groups.json' if grouping_mode=='components-v1' else 'full-source-day-graph.json'
    if grouping_mode!='components-v1' and graph is None:
        graph=assign_day_graph(records,proximity_m)
    write_json(output/graph_file, {**(graph or {'schemaVersion':1}),'records':source_rows})
    if failure is not None:
        inventory = defaultdict(lambda:{'train':0,'val':0,'blacklisted':0,'exposed':0})
        for row in records:
            inventory[row['group_id']][row['official_split']] += 1
            inventory[row['group_id']]['exposed'] += row['frame_id'] in ids
        write_json(output/'infeasible.json', {'schemaVersion':1,'status':'infeasible_before_images_or_metrics',
            'reason':str(failure),'full_trainval_sha256':sha256_file(trainval_path),
            'full_source_grouping_sha256':sha256_file(output/graph_file),
            'exposure_file_sha256':sha256_file(exposure_path),'seed':seed,
            'requested_train':train_count,'requested_test':test_count,'minimum_test_groups':min_test_groups,
            'target_test_groups':target_test_groups,'groups':dict(inventory)})
        raise failure
    original = json.loads(Path(trainval_path).read_text())
    subset = {split:[row for row in original[split] if row['id'] in selected] for split in ('train','val')}
    write_json(output/'selected-trainval.json', subset)
    cohort = {'schemaVersion':1,'dataset':'ZOD','kind':'predeclared-full-source-cohort-v1',
        'full_trainval_sha256':sha256_file(trainval_path), 'full_trainval_path':str(Path(trainval_path).resolve()),
        'full_source_groups_sha256':sha256_file(output/graph_file),
        'full_source_groups_file':'full-source-groups.json',
        'selected_trainval_sha256':sha256_file(output/'selected-trainval.json'),
        'exposure_file_sha256':sha256_file(exposure_path),'exposure_ids':sorted(ids),
        'prior_qa_receipt_sha256':sha256_file(prior_receipt_path) if prior_receipt_path else None,
        'selector_sha256':sha256_file(__file__),'grouping_adapter_sha256':sha256_file(Path(__file__).with_name('prepare_zod_lane_corpus.py')),
        'grouping':grouping,'selected':[{ 'frame_id':identity,'split':split} for identity,split in sorted(selected.items())],
        'qa_plan':{'training_input_size':training_input_size, 'target_resampling':'rounded letterbox dimensions; INTER_NEAREST_EXACT; zero-valid padding', 'full_review_train_ids':sorted(sorted((identity for identity,split in selected.items() if split=='train'), key=lambda identity:ranked(identity,seed,'full-coverage-training-qa'))[:full_review_train_count]), 'full_review_test_ids':sorted(identity for identity,split in selected.items() if split=='test'), 'unreviewed_training':'positive_only', 'unreviewed_evaluation':'forbidden', 'refill':'forbidden'},
        'coverage':'unknown: source/geometry/coverage QA must follow selection before metrics; no refill after QA exclusions',
        'qualification':'Predeclared candidate cohort, not training clearance. All out-of-cohort source rows participate in global grouping. Prior exposure also excludes connected components from fresh holdout.'}
    if grouping_mode!='components-v1':
        cohort.update(kind='predeclared-full-source-day-cohort-v2',
            full_source_graph_file=graph_file,full_source_graph_sha256=sha256_file(output/graph_file),
            qualification='Predeclared candidate cohort, not training clearance. All source frames inform direct day adjacency; selected training days exclude H and direct N(H). Holdout whole days are unexposed, but neighboring unselected days may contain prior analyst exposure. No unseen-region claim.')
        cohort.pop('full_source_groups_sha256');cohort.pop('full_source_groups_file')
    write_json(output/'cohort.json',cohort)
    return cohort


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset-root',type=Path,required=True)
    p.add_argument('--trainval',type=Path,required=True)
    p.add_argument('--prior-exposure',type=Path,required=True)
    p.add_argument('--prior-source-receipt',type=Path)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--train-count',type=int,default=1024)
    p.add_argument('--test-count',type=int,default=128)
    p.add_argument('--seed',default='zod-scale-20261009-v1')
    p.add_argument('--proximity-m',type=float,default=250.)
    p.add_argument('--min-test-groups',type=int,default=8)
    p.add_argument('--target-test-groups',type=int,default=16)
    p.add_argument('--full-review-train-count',type=int,default=32)
    p.add_argument('--training-input-size',type=int,default=640)
    p.add_argument('--expected-source-frames',type=int,default=100000)
    p.add_argument('--grouping-mode',choices=('components-v1','vehicle-day-direct-v2'),default='components-v1')
    args=p.parse_args()
    try:
        result=select(args.dataset_root,args.trainval,args.prior_exposure,args.output_dir,args.train_count,args.test_count,args.seed,args.proximity_m,args.min_test_groups,args.expected_source_frames,args.prior_source_receipt,args.target_test_groups,args.full_review_train_count,args.training_input_size,args.grouping_mode)
    except (ValueError,KeyError,TypeError,OSError) as error:
        p.error(str(error))
    print(json.dumps(result['grouping'],indent=2))


if __name__=='__main__':
    main()

#!/usr/bin/env python3
"""Prepare a cumulative, unapproved lecture review from verified discovery assets."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[4]
LECTURE=ROOT/'lectures/tsr-sgblur-de-2026-10-26'
EVIDENCE=Path(__file__).resolve().parent
INITIAL=LECTURE/'source/mobidata-bw-review-2026-10-20'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def link_asset(source,root,name,expected=None):
    source=source.resolve();dest=root/name
    if not source.is_file() or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Invalid source asset '+str(source))
    if expected and sha(source)!=expected:raise ValueError('Source hash mismatch '+str(source))
    dest.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,dest)
    except OSError:shutil.copyfile(source,dest)


def distance(a,b):
    return math.hypot((a[0]-b[0])*111320*math.cos(math.radians((a[1]+b[1])/2)),(a[1]-b[1])*111320)


def prepare(discovery,initial_pack,output):
    original=json.loads((INITIAL/'manifest.json').read_text())
    new=json.loads((discovery/'new-enriched-proposals.json').read_text())
    assert len(new)==44 and all(r['distance_m']<=10 for r in new)
    old=original['records'];old_ids={r['picture_id'] for r in old};old_sequences={r['sequence_id'] for r in old}
    old_hashes={r[key] for r in old for key in ['hd_sha256','crop_sha256','rgb_sha256']}
    historic=json.loads((discovery.parent/'existing-inventory.json').read_text())
    historical_ids=set(historic['lecture_picture_ids'])|set(historic['prior_discovery_picture_ids'])
    historical_hashes=set(historic['hashes'])
    assert not old_ids & {r['picture_id'] for r in new}
    assert not old_sequences & {r['sequence_id'] for r in new}
    assert not historical_ids & {r['picture_id'] for r in new}
    assert not (old_hashes|historical_hashes) & {r[key] for r in new for key in ['hd_sha256','crop_sha256','rgb_sha256']}
    output.mkdir(parents=True,exist_ok=False)
    for rows,source in [(old,initial_pack),(new,discovery)]:
        for r in rows:
            assert not r['human_approved'] and not r['eligible_for_training'] and not r['approved_for_evaluation']
            for key,digest in [('image_path','hd_sha256'),('crop_path','crop_sha256'),('metadata_path','source_item_sha256')]:
                link_asset(source/r[key],output,r[key],r[digest])
            link_asset(source/r['overlay_path'],output,r['overlay_path'])
    for r in old:
        r['discovery_batch']='initial-144-views'
        r['sgblur_yolo11n_target_issue']='detected_sign' if r['sgblur_yolo11n_target_detected'] else 'missed_sign'
        r.setdefault('source_target_original_codes',[] if r['source_target_status']=='no_stored_target_box' else ['yes'])
    for r in new:
        if r['sgblur_yolo11n_target_detected'] and r['sgblur_yolo11n_target_iou']<.6:
            r['quality_notes'].append('baseline_match_near_threshold_IoU_'+str(round(r['sgblur_yolo11n_target_iou'],3)))
    records=old+new
    # Keep near sites and journeys together. This is a conservative grouping proposal,
    # not an approval of physical independence or a training/validation/test split.
    parent=list(range(len(records)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,a in enumerate(records):
        for j,b in enumerate(records[:i]):
            if a['sequence_id']==b['sequence_id'] or a['registry_location_id']==b['registry_location_id'] or distance(a['registry_coordinates'],b['registry_coordinates'])<=150:
                parent[find(i)]=find(j)
    groups=defaultdict(list)
    for i,r in enumerate(records):groups[find(i)].append(r['picture_id'])
    for i,r in enumerate(records):
        r['conservative_split_group_id']='bw-review:'+hashlib.sha256('|'.join(sorted(groups[find(i)])).encode()).hexdigest()[:16]
        r['physical_independence_approved']=False
    inference=json.loads((discovery/'inference-all-53.json').read_text());pred={r['picture_id']:r for r in inference['rows']}
    replay=json.loads((INITIAL/'sgblur-baseline-replay.json').read_text())
    for r in new:
        p=pred[r['picture_id']]
        replay['rows'].append(dict(candidate_index=r['candidate_index'],picture_id=r['picture_id'],visible_class_proposal=r['visible_class_proposal'],image_sha256=r['hd_sha256'],target_bbox_xyxy_proposal=r['target_bbox_xyxy_proposal'],detections_xyxy_score_class=p['detections_xyxy_score_class'],maximum_target_iou=r['sgblur_yolo11n_target_iou'],matched_at_iou_0_5=r['sgblur_yolo11n_target_detected'],cpu_ms=p['cpu_ms'],target_issue=r['sgblur_yolo11n_target_issue']))
    replay.update(known_targets=len(records),matched_known_targets=sum(r['sgblur_yolo11n_target_detected'] for r in records),missing_known_targets=sum(not r['sgblur_yolo11n_target_detected'] for r in records),discovery_full_images_replayed=53,one_new_match_near_iou_threshold=True)
    write(EVIDENCE/'sgblur-baseline-replay.json',replay)
    novelty={'scope':'Original 154-image lecture inventory, earlier 3745-picture/298-sequence discovery inventory, and initial 13 MobiData review records. Not all model pretraining data.',
             'initial_records_retained':len(old),'additional_records':len(new),'additional_exact_picture_id_overlaps':0,'additional_exact_hd_rgb_crop_hash_overlaps':0,'additional_sequences':len({r['sequence_id'] for r in new}),'additional_sequence_overlap_with_initial_review':0,
             'minimum_additional_camera_distance_to_scoped_prior_cameras_m':min(r['nearest_prior_camera_m'] for r in new),'minimum_additional_registry_distance_to_initial_review_sites_m':min(r['nearest_prior_mobidata_site_m'] for r in new),
             'conservative_split_group_method':'Connected components of shared sequence, shared registry location ID, or registry points at most 150m apart; proposals only, no split assigned.',
             'conservative_split_groups':len(groups),'physical_independence_approved':False,'rows':[dict(picture_id=r['picture_id'],sequence_id=r['sequence_id'],discovery_batch=r['discovery_batch'],conservative_split_group_id=r['conservative_split_group_id'],exact_hash_overlap_with_prior_inventory=r['exact_hash_overlap_with_prior_inventory']) for r in records]}
    write(EVIDENCE/'novelty-audit.json',novelty)
    summary=json.loads((discovery/'new-summary.json').read_text())
    summary.update(total_review_full_images=len(records),total_review_crops=len(records),total_visible_class_proposals=dict(Counter(r['visible_class_proposal'] for r in records)),total_sequences=len({r['sequence_id'] for r in records}),conservative_split_groups=len(groups),all_approvals=False,source_annotations_changed=False,source_detection_model='SGBlur-yolo11s/0.1.0 where recorded',source_wrong_target_classification_model='classify_fr_road_signs/0.13',source_wrong_target_code='FR:C50',source_wrong_target_classification_confidence=.92,baseline_checkpoint_sha256=inference['checkpoint_sha256'],one_baseline_match_near_threshold_IoU=.5123620550875272)
    supporting=[]
    files={'cohort-2730.json':'evidence/cohort-2730.json','catalogue-matches-10m.parquet':'evidence/catalogue-matches-10m.parquet','selection.sql':'evidence/selection.sql','selection-summary.json':'evidence/selection-summary.json','review-manifest.json':'evidence/screening-180.json','inference-all-53.json':'evidence/full-image-inference-53.json','choices.json':'evidence/visual-box-selections.json'}
    for filename,name in files.items():link_asset(discovery/filename,output,name);supporting.append(name)
    for n in [1,2,3]:
        name=f'evidence/retained-{n:02d}.jpg';link_asset(discovery/f'contacts/retained-{n:02d}.jpg',output,name);supporting.append(name)
    for filename in ['select_near10.py','fetch_near10.py']:
        name='reproduce/'+filename;link_asset(discovery.parent/filename,output,name);supporting.append(name)
    for filename in ['infer_full.py','roi.py','roi_strict.py','retain.py','enrich.py','export_matches.py']:
        name='reproduce/'+filename;link_asset(discovery/filename,output,name);supporting.append(name)
    for source,name in [(Path(__file__),'reproduce/prepare_review.py'),(ROOT/'scripts/tsr/mobidata_review.py','reproduce/mobidata_review.py'),(ROOT/'scripts/tsr/package_mobidata_bw_review.py','reproduce/package_mobidata_bw_review.py')]:
        link_asset(source,output,name);supporting.append(name)
    (output/'reproduce/README.txt').write_text('Die Skripte dokumentieren den tatsächlichen lokalen Suchlauf. Die Discovery-Skripte enthalten dessen Scratch-Pfade; passen Sie ROOT/O und Eingabepfade für einen erneuten Lauf an. Der ursprüngliche komplette GeoParquet-Snapshot ist nicht im Paket. evidence/catalogue-matches-10m.parquet friert alle 9014 passenden Zeilen (2730 Katastereinträge, 5972 Fotos) ein; die Auswahl und lokalen Modellvorhersagen sind separat gespeichert. Nur retained targets haben hier Original-JPEGs und PNG-Crops. prepare_review.py nimmt --discovery-root, --initial-pack-root und --output an. Das Paket weist keine Trainings-/Testfreigabe zu.\n',encoding='utf-8');supporting.append('reproduce/README.txt')
    summary['supporting_asset_hashes']={name:sha(output/name) for name in supporting}
    write(EVIDENCE/'search-summary.json',summary);write(output/'evidence/search-summary.json',summary);supporting.append('evidence/search-summary.json')
    original.update(schema_version='youspeed-mobidata-town-sign-review-v2',created_at=datetime.now(timezone.utc).isoformat(),previous_review_manifest_sha256=sha(INITIAL/'manifest.json'),records=records,review_sample=dict(total_retained_target_views=len(records),initial_target_views=len(old),additional_near10_target_views=len(new),visible_class_proposals=summary['total_visible_class_proposals'],source_target_status=dict(Counter(r['source_target_status'] for r in records))),baseline_replay={k:v for k,v in replay.items() if k!='rows'},additional_10m_search=summary,supporting_files=supporting,novelty_scope=novelty['scope'],physical_independence_approved=False)
    write(EVIDENCE/'manifest.json',original)
    print(json.dumps({k:v for k,v in summary.items() if k!='supporting_asset_hashes'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--discovery-root',type=Path,required=True);p.add_argument('--initial-pack-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.discovery_root,a.initial_pack_root,a.output)

#!/usr/bin/env python3
"""Freeze supplemental review proposals; never approve, split, train or evaluate."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[4]
LECTURE = ROOT / 'lectures/tsr-sgblur-de-2026-10-26'
EVIDENCE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/tsr'))
from mobidata_review import source_target_assessment


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def link(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try: os.link(source, destination)
    except OSError: shutil.copyfile(source, destination)


def distance(a, b):
    return math.hypot((a[0]-b[0])*111320*math.cos(math.radians((a[1]+b[1])/2)), (a[1]-b[1])*111320)


def prepare(discovery, output):
    old_manifest = LECTURE / 'source/mobidata-bw-review-2026-10-20-v2/manifest.json'
    old = json.loads(old_manifest.read_text())
    prior = json.loads((discovery.parent / 'existing-inventory.json').read_text())
    previous_screen = json.loads((discovery.parent / 'near10/review-manifest.json').read_text())['records']
    previous_ids = set(prior['lecture_picture_ids']) | set(prior['prior_discovery_picture_ids'])
    previous_sequences = set(prior['lecture_sequence_ids']) | set(prior['prior_discovery_sequence_ids'])
    previous_hashes = set(prior['hashes'])
    for r in old['records'] + previous_screen:
        previous_ids.add(r['picture_id']); previous_sequences.add(r['sequence_id'])
        previous_hashes.update(r[k] for k in ['hd_sha256','crop_sha256','rgb_sha256'] if r.get(k))
    screening = json.loads((discovery / 'review-manifest.json').read_text())['records']
    rows = {r['review_index']: r for r in json.loads((discovery / 'roi-strict.json').read_text())}
    decisions = json.loads((discovery / 'hd-review-decisions.json').read_text())
    assert not decisions['manual_pending']
    assert len(screening) == 360 and all(r['status'] == 'downloaded' for r in screening)
    assert set(rows) == set(map(int, decisions['choices'])) | set(map(int, decisions['excluded']))
    output.mkdir(parents=True, exist_ok=False)
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 16)
    records = []
    for key, choice in sorted(decisions['choices'].items(), key=lambda p: int(p[0])):
        r = dict(rows[int(key)]); r.pop('roi_proposals', None)
        assert r['picture_id'] not in previous_ids and r['sequence_id'] not in previous_sequences
        assert r['hd_sha256'] not in previous_hashes and r['rgb_sha256'] not in previous_hashes
        assert r['distance_m'] <= 10 and r['nearest_v2_site_m'] >= 150
        assert sha(discovery / r['hd_path']) == r['hd_sha256']
        assert sha(discovery / r['metadata_path']) == r['source_item_sha256']
        r.update(visible_class_proposal=choice['visible_class_proposal'],
                 target_bbox_xyxy_proposal=choice['final_bbox_xyxy'],
                 candidate_index=int(key), proposal_status='assistant_visual_proposal_pending_human_review',
                 human_approved=False, eligible_for_training=False, approved_for_evaluation=False,
                 physical_independence_approved=False, all_visible_object_annotation_complete=False,
                 sgblur_yolo11n_target_detected=None, sgblur_yolo11n_target_issue='not_replayed',
                 source_tags_changed=False, discovery_batch='near10-expanded-360-native-views',
                 exact_hash_overlap_with_prior_inventory=False,
                 registry_face_disagrees_with_visible_face=r['registry_class'] != choice['visible_class_proposal'],
                 registry_match_establishes_physical_sign_identity=False,
                 quality_notes=['Assistant proposal; inspect complete scene, box edges and class before approval.'])
        if int(key) in {7,149,159,263,302,315,348}:
            r['quality_notes'].append('Challenging blur, glare or low contrast; decide whether to retain after human review.')
        if int(key) == 78: r['quality_notes'].append('Vegetation partly occludes the sign border and lettering.')
        if int(key) == 202: r['quality_notes'].append('Registry municipality says Stuttgart; visible text says Wangen i.A.; registry association is only a search hint.')
        r.update(source_target_assessment(r['live_annotations'], r['target_bbox_xyxy_proposal'], r['visible_class_proposal']))
        r['image_path'] = r['hd_path']
        r['crop_path'] = 'crops/'+r['picture_id']+'.png'
        r['overlay_path'] = 'overlays/'+r['picture_id']+'.jpg'
        for field in ['image_path','metadata_path']: link(discovery/r[field], output/r[field])
        im = Image.open(output/r['image_path']).convert('RGB')
        assert list(im.size) == r['hd_dimensions']
        assert hashlib.sha256(im.tobytes()).hexdigest() == r['rgb_sha256']
        bb = r['target_bbox_xyxy_proposal']
        assert 0 <= bb[0] < bb[2] <= im.width and 0 <= bb[1] < bb[3] <= im.height
        crop = im.crop(bb); (output/'crops').mkdir(exist_ok=True)
        crop.save(output/r['crop_path']); r['crop_dimensions'] = list(crop.size)
        r['crop_sha256'] = sha(output/r['crop_path'])
        assert r['crop_sha256'] not in previous_hashes
        view = im.copy(); view.thumbnail((1000,750)); sx,sy=view.width/im.width,view.height/im.height
        canvas = Image.new('RGB',(max(1000,view.width),view.height+60),'white');canvas.paste(view,(0,0))
        d=ImageDraw.Draw(canvas);d.rectangle([bb[0]*sx,bb[1]*sy,bb[2]*sx,bb[3]*sy],outline='#ff315b',width=3)
        d.text((6,view.height+4),r['visible_class_proposal']+' | magenta: unapproved target proposal; other objects incomplete',fill='black',font=font)
        d.text((6,view.height+26),str(r['author'])+' | '+r['license']+' | Original image unchanged | no model replay',fill='black',font=font)
        (output/'overlays').mkdir(exist_ok=True);canvas.save(output/r['overlay_path'],quality=83)
        records.append(r)
    # Conservative location/sequence components, with author/day journey grouping.
    parent=list(range(len(records)))
    def find(i):
        while parent[i]!=i: parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,a in enumerate(records):
        for j,b in enumerate(records[:i]):
            same_journey = (bool(a.get('author')) and a['author']==b.get('author') and
                            a['live_capture_datetime'][:10]==b['live_capture_datetime'][:10])
            if same_journey or a['sequence_id']==b['sequence_id'] or a['registry_location_id']==b['registry_location_id'] or distance(a['registry_coordinates'],b['registry_coordinates'])<=150:
                parent[find(i)]=find(j)
    groups=defaultdict(list)
    for i,r in enumerate(records):groups[find(i)].append(r['picture_id'])
    for i,r in enumerate(records):
        r['conservative_split_group_id']='bw-additions:'+hashlib.sha256('|'.join(sorted(groups[find(i)])).encode()).hexdigest()[:16]
    preview_sequence_overlaps = sum(r['sequence_id'] in previous_sequences for r in screening)
    novelty=dict(scope='Prior lecture/discovery inventory, previous 180-view screen and retained v2; not a pretraining audit.',
                 screened_views_with_prior_sequence=preview_sequence_overlaps,
                 otherwise_usable_hd_views_excluded_for_prior_sequence=1,
                 prior_v2_manifest_sha256=sha(old_manifest), additional_picture_id_overlaps=0,
                 additional_sequence_overlaps=0, additional_exact_hd_rgb_crop_hash_overlaps=0,
                 minimum_registry_distance_to_v2_m=min(r['nearest_v2_site_m'] for r in records),
                 conservative_split_groups=len(groups), physical_independence_approved=False,
                 group_rule='Union of same sequence/location, registry separation <=150m, or same producer/capture day. Reconcile across all datasets manually; no split assigned.')
    write(EVIDENCE/'novelty-audit.json',novelty)
    write(EVIDENCE/'sgblur-baseline-replay.json',dict(status='not_run',training_performed=False,
          reason='Data collection only; model comparison and training remain student work. Stored source annotations are preserved separately.'))
    summary=dict(schema_version=1,near10_registry_records=2730,new_previews_screened=360,
                 screening_method='Color-ROI-assisted preview contact sheets; not exhaustive full-scene annotation.',
                 municipalities_screened=156,sequences_screened=360,
                 sequences_new_to_final_prior_inventory=360-preview_sequence_overlaps,hd_candidates_inspected=80,
                 retained_full_images=len(records),retained_crops=len(records),excluded_hd_candidates=len(decisions['excluded']),
                 visible_class_proposals=dict(Counter(r['visible_class_proposal'] for r in records)),
                 source_target_status=dict(Counter(r['source_target_status'] for r in records)),
                 registry_face_disagreements=sum(r['registry_face_disagrees_with_visible_face'] for r in records),
                 all_human_approvals=False,training_performed=False,model_replay_performed=False,
                 prior_v2_images=57,cumulative_review_images=57+len(records),
                 full_cohort_visually_reviewed=False,exact_image_novelty_checked=True)
    write(EVIDENCE/'search-summary.json',summary)
    supporting=[]
    for src,name in [(discovery/'selected.json','evidence/selected-360.json'),
                     (discovery/'selection-summary.json','evidence/selection-summary.json'),
                     (discovery/'review-manifest.json','evidence/screening-360.json'),
                     (discovery/'hd-review-decisions.json','evidence/visual-review-decisions-80.json'),
                     (discovery.parent/'near10/catalogue-matches-10m.parquet','evidence/catalogue-matches-10m.parquet'),
                     (EVIDENCE/'search-summary.json','evidence/search-summary.json')]:
        link(src,output/name);supporting.append(name)
    for filename in ['fetch_sd.py','fetch_hd.py','make_roi.py','hd-roi.py']:
        name='reproduce/'+filename;link(discovery/filename,output/name);supporting.append(name)
    for src,name in [(Path(__file__),'reproduce/prepare_review.py'),
                     (ROOT/'scripts/tsr/mobidata_review.py','reproduce/mobidata_review.py'),
                     (ROOT/'scripts/tsr/package_mobidata_bw_review.py','reproduce/package_mobidata_bw_review.py')]:
        link(src,output/name);supporting.append(name)
    manifest=dict(schema_version='youspeed-mobidata-town-sign-review-additions-v1',
                  created_at=datetime.now(timezone.utc).isoformat(),registry_source_url=old['registry_source_url'],
                  registry_source_sha256=old['registry_source_sha256'],
                  federation_export_http_last_modified=old['federation_export_http_last_modified'],
                  role='exploratory_lecture_review',human_approved=False,eligible_for_training=False,
                  approved_for_evaluation=False,normal_course_importer_compatible=False,
                  all_visible_object_annotation_complete=False,physical_independence_approved=False,
                  records=records,additional_10m_search=summary,supporting_files=supporting)
    write(EVIDENCE/'manifest.json',manifest)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--discovery-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();prepare(a.discovery_root,a.output)

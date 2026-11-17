#!/usr/bin/env python3
"""Assemble all eligible weak labels with immutable source-image references.

Image bytes already exist in the pinned HF monthly export / reviewed overlay.
The new dataset overlay publishes actual label bytes, membership and provenance.
"""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
from pseudo_admission import exclusion_reason

ROOT=Path('/job')
PREFIX='reviews/detector-expanded-2026-11-15'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from PIL import Image
    root=ROOT/'expanded-v1';status=json.loads((root/'mining-status.json').read_text())
    assert status['complete'] and status['processed']==status['total']==10345
    policy_sha=sha(root/'pseudo-policy.json')
    reserve=json.loads((root/'final-geographic-reserve.json').read_text())
    reserve_exclusions={r['picture_id']:r['reason'] for r in reserve['training_exclusions']}
    rows=[r for line in gzip.open(root/'source-membership.jsonl.gz','rt') if (r:=json.loads(line))['expanded_role']=='weak_training']
    reviewed=json.loads((ROOT/'dataset-reviewed-v1/manifest.json').read_text())
    review_train={r['picture_id']:r for r in reviewed['frames'] if r['split']=='train'}
    dataset=root/'dataset';dataset.mkdir(exist_ok=False)
    overlay=dataset/PREFIX;overlay.mkdir(parents=True)
    (overlay/'labels').mkdir();frames=[];exclusions=[];counts=Counter()
    def label(frame,boxes):
        path=overlay/'labels'/(frame['picture_id']+'.txt');w,h=frame['width'],frame['height']
        path.write_text(''.join('0 %.10f %.10f %.10f %.10f\n'%((b[0]+b[2])/2/w,(b[1]+b[3])/2/h,(b[2]-b[0])/w,(b[3]-b[1])/h) for b in boxes))
        frame['label_path']=path.relative_to(dataset).as_posix();frame['label_sha256']=sha(path)
    def link(source,target):
        target.parent.mkdir(parents=True,exist_ok=True);os.link(source,target)
    for row in rows:
        uid=row['picture_id'];pseudo=json.loads((root/'pseudo-labels'/(uid+'.json')).read_text())
        assert pseudo['policy_sha256']==policy_sha and pseudo['image_sha256']==row['image_sha256']
        if uid in reserve_exclusions:
            exclusions.append({'picture_id':uid,'reason':reserve_exclusions[uid]});continue
        if uid in review_train:
            r=review_train[uid];frame=dict(r);frame['supervision']='model_assisted_review'
            source=ROOT/'dataset-reviewed-v1'/r['image_path'];frame['image_path']='reviews/detector-pilot-2026-11-14/'+r['image_path']
            link(source,dataset/frame['image_path'])
            src_label=ROOT/'dataset-reviewed-v1'/r['label_path'];dst=overlay/'labels'/(uid+'.txt');shutil.copy2(src_label,dst)
            frame['label_path']=dst.relative_to(dataset).as_posix();frame['label_sha256']=sha(dst)
        else:
            reason=exclusion_reason(pseudo)
            if reason:
                exclusions.append({'picture_id':uid,'reason':reason});continue
            source=root/'source-images'/(row['image_sha256']+'.jpg')
            assert sha(source)==row['image_sha256']
            with Image.open(source) as image:
                if image.getexif().get(274,1)!=1:
                    exclusions.append({'picture_id':uid,'reason':'noncanonical_actual_exif_orientation'});continue
                assert image.size==(pseudo['width'],pseudo['height'])
            frame={'image_id':'panoramax-frame-'+uid,'picture_id':uid,'split':'train','group_id':'sequence:'+row['component'],
                   'sequence_ids':row['sequence_ids'],'coordinates':row['coordinates'],'image_path':row['image_path'],
                   'image_sha256':row['image_sha256'],'source_image_sha256':row['image_sha256'],
                   'width':pseudo['width'],'height':pseudo['height'],'annotation_complete':False,
                   'human_verified':False,'supervision':'teacher_pseudo','pseudo_label_status':pseudo['status'],
                   'pseudo_label_policy_sha256':policy_sha,'pseudo_record_sha256':sha(root/'pseudo-labels'/(uid+'.json')),
                   'acceptable_extra_candidates':[]}
            link(source,dataset/frame['image_path']);label(frame,[r['box'] for r in pseudo['accepted_boxes']])
        counts[frame['supervision']]+=1;frames.append(frame)
    for r in reviewed['frames']:
        if r['split']=='train':continue
        frame=dict(r);frame['supervision']='model_assisted_review'
        frame['image_path']='reviews/detector-pilot-2026-11-14/'+r['image_path']
        link(ROOT/'dataset-reviewed-v1'/r['image_path'],dataset/frame['image_path'])
        dst=overlay/'labels'/(r['picture_id']+'.txt');shutil.copy2(ROOT/'dataset-reviewed-v1'/r['label_path'],dst)
        frame['label_path']=dst.relative_to(dataset).as_posix();frame['label_sha256']=sha(dst);frames.append(frame)
    manifest={'schema':'streetshots-sign-only-mixed-v1','dataset_repo':'loffenauer/streetshots',
              'dataset_revision':'d2c5cc44716166e2604655d7fd8cad93a8dd9468',
              'reviewed_source_revision':'e428e4cff9b179934ffa5bb7609973178c8c18e8',
              'review_provenance':'mixed_reviewed_and_pseudo','pseudo_policy_sha256':policy_sha,
              'test_status':'consumed pilot diagnostic set; no new evaluation authorized by this recipe',
              'fresh_holdout_status':'93 metadata-qualified images in final-geographic-reserve.json; unreviewed, no benchmark metrics yet. Other original reserved groups are not all unseen by d4.',
              'final_geographic_reserve_sha256':sha(root/'final-geographic-reserve.json'),
              'post_mining_admission_sha256':sha(root/'recipe/pseudo_admission.py'),
              'frames':frames}
    (overlay/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (overlay/'exclusions.json').write_text(json.dumps(exclusions,indent=2)+'\n')
    for name in ['pseudo-policy.json','source-selection.json','mining-status.json','source-membership.jsonl.gz',
                 'source-image-verification.json','reserve-exposure-audit.json',
                 'known-exposure-clear-candidates.json','final-geographic-reserve.json']:
        shutil.copy2(root/name,overlay/name)
    # Preserve exact per-record JSON bytes in one indexed-by-picture_id stream.
    # This avoids thousands of tiny Hub commits without changing provenance.
    with (overlay/'pseudo-records.jsonl.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as archive:
            for record in sorted((root/'pseudo-labels').glob('*.json')):
                data=record.read_bytes();assert b'\n' not in data
                archive.write(data+b'\n')
    shutil.copytree(root/'early-quality-review',overlay/'early-quality-review')
    shutil.copytree(root/'recipe',overlay/'recipe')
    for name in ('final-scope-review','pre-admission-additions-review'):
        if (root/name).exists():shutil.copytree(root/name,overlay/name)
    counts.update(Counter(r['split'] for r in frames))
    summary={'counts':dict(counts),'source_candidates':len(rows),'excluded_training_candidates':len(exclusions),
             'manifest_sha256':sha(overlay/'manifest.json'),'annotation_provenance':'mixed; pseudo-labels explicitly not exhaustive ground truth',
             'pseudo_records_archive':{'path':'pseudo-records.jsonl.gz','sha256':sha(overlay/'pseudo-records.jsonl.gz'),
                                       'record_key':'picture_id','record_sha256':'Hash each JSON line without the terminating newline; matches per-frame pseudo_record_sha256'},
             'image_bytes':'Existing original HF monthly bytes and reviewed canonical bytes; all local image hashes verified. New overlay includes actual label bytes and complete source paths.'}
    (overlay/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (overlay/'README.md').write_text('# Expanded sign-only weak training dataset\n\nAll geographically eligible candidates were mined; no sample cap. Direction boards and supplementary plates are filtered. Traffic lights are not a positive class. Unknown classifier scope excludes a frame. Mapillary geometry hints block pseudo-negatives but never create boxes. Accepted pseudo-negatives are model judgements, not certified absence.\n\nActual image bytes are already present at the manifest image_path values in this same dataset repository, inherited from the pinned monthly source and reviewed overlay. No live database is required. New label bytes, complete membership, exclusion reasons, mining policy and recipe are included here. Panoramax source attribution and CC-BY-SA-4.0 provenance remain in the per-image monthly metadata.\n\nThe original 17-image development set is retained. The consumed 18-image pilot test is retained only for provenance, not new model selection. An additional 93 images clear of recovered d4 exposure and all opened pilot frames are reserved before expanded training, with sequence and 500 m training exclusions. Their labels remain unreviewed. Most original randomly reserved groups share historical d4 sequences; they must not be described as unseen-baseline geography. Upstream pretraining and classifier exposure remain unknown.\n')
    print(json.dumps(summary))


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Freeze one blinded reference image per reserved geographic component."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from full_source_eligibility import distance
from prepare_expanded_publication import inventory,sha,write

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'geographic-audit-v1';EXP=JOB/'expanded-v1'
PREFIX='reviews/detector-expanded-2026-11-15/geographic-audit-v1'


def main():
    reserve=EXP/'final-geographic-reserve.json'
    assert sha(reserve)=='00212c3e52c6d3d0f9d0ccae6445c1fbe4143fcd4b1be0d629d7f805536172cb'
    frames=json.loads(reserve.read_text())['frames']
    seen=set();uuid=re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
    audits=[EXP/'early-quality-review',EXP/'final-scope-review',EXP/'pre-admission-additions-review']
    audit_files=[p for d in audits for p in d.glob('*.json')]
    audit_files.append(JOB/'latest-ultralytics-v1/probe/report.json')
    for path in audit_files:seen.update(uuid.findall(path.read_text()))
    opened=[f['picture_id'] for f in frames if f['picture_id'] in seen]
    assert not opened, 'Previously inspected reserve frames need explicit exclusion: '+str(opened)
    parent=list(range(len(frames)))
    def root(i):
        while parent[i]!=i:i=parent[i]
        return i
    for i,a in enumerate(frames):
        for j,b in enumerate(frames[:i]):
            if set(a['sequence_ids'])&set(b['sequence_ids']) or distance(a['coordinates'],b['coordinates'])<500:
                parent[root(i)]=root(j)
    groups={}
    for i,frame in enumerate(frames):groups.setdefault(root(i),[]).append(frame)
    selected=[]
    for members in groups.values():
        key=hashlib.sha256('|'.join(sorted(r['picture_id'] for r in members)).encode()).hexdigest()
        choice=min(members,key=lambda r:hashlib.sha256(('streetshots-geographic-audit-v1|'+r['picture_id']).encode()).hexdigest())
        selected.append({**choice,'group_id':'reserved-geography:'+key,'group_source_images':len(members)})
    selected.sort(key=lambda r:hashlib.sha256(('streetshots-geographic-audit-order-v1|'+r['picture_id']).encode()).hexdigest())
    assert len(selected)==24 and len({r['picture_id'] for r in selected})==24
    train=json.loads((EXP/'dataset'/ 'reviews/detector-expanded-2026-11-15/manifest.json').read_text())['frames']
    train=[r for r in train if r['split']=='train']
    assert not {r['picture_id'] for r in selected}&{r['picture_id'] for r in train}
    assert not {s for r in selected for s in r['sequence_ids']}&{s for r in train for s in r['sequence_ids']}
    minimum=min(distance(a['coordinates'],b['coordinates']) for a in selected for b in train)
    assert minimum>=500
    selection={'schema':'streetshots-geographic-audit-selection-v1','dataset_repository':'loffenauer/streetshots',
        'dataset_revision':'5e51cd9333ec07a88d212de479d1d2139f007495','source_revision':'d2c5cc44716166e2604655d7fd8cad93a8dd9468',
        'reserve_sha256':sha(reserve),'selection':'One fixed-hash image from each connected component of shared sequences or source positions within500m, across the93 already reserved frames. No pixels, labels, model scores or outcomes used.',
        'selected_images':len(selected),'geographic_groups':len(groups),'minimum_distance_to_training_m':minimum,
        'previously_opened_visual_audit_intersection':opened,'visual_audit_metadata_hashes':{str(p.relative_to(JOB)):sha(p) for p in audit_files},
        'frames':selected}
    protocol={'schema':'streetshots-geographic-audit-protocol-v1','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'training_definition_revision':'144ddf04c6771cad25b1a6c8770e214ab35b0e1e','training_changes_allowed':False,
        'reviewer':'model-assisted assistant; not human-certified ground truth',
        'blindness':'No d4 or d8 predictions on these images may be inspected until reference labels and candidate/development thresholds are frozen. Existing source-model annotations are not presented to the reviewer.',
        'proposal_assistance':{'model':'Panoramax YOLO11l','sha256':'a3205e4a92b3acdaa883c02e09dba439c48f6c5bc8c89aff44da7c2e79f140e7','ultralytics':'8.4.213','full_imgsz':2048,'tile_imgsz':1536,'tile':True,'confidence':.1,'iou':.5,'max_det':1000,'quantize':16},
        'review':'Inspect the clean overview, every native clean tile, and all independent-teacher proposal crops/overlays; manually add missed primary sign faces and correct boxes. No proposal is preaccepted.',
        'scope':'One class: front-facing primary traffic-sign faces, including regulatory/warning/information signs and red-white hazard panels. Exclude direction/wayfinding/detour boards, separate supplementary plates, sign backs, faces, plates and non-sign objects. Traffic lights may be marked as acceptable extras, never positive sign labels.',
        'canonicalization':'Verified source SHA; EXIF transpose if needed, RGB conversion, PNG without EXIF/ICC; boxes in upright canonical pixels. Preserve original/canonical/pixel hashes and transform.',
        'admission':'A frame with unresolved sign-like regions is excluded before scoring rather than called negative. Record every exclusion and all teacher-proposal decisions. Include clear negatives. No exclusion based on candidate outputs.',
        'candidate_selection':'d8 maximum whole-image development AP50-95, earliest tie, epoch zero eligible, exactly as frozen training definition. No audit labels enter training or checkpoint selection.',
        'evaluation':'d4 versus sealed d8, once, on all admitted references; actual Swift/Core Image phone inputs on macOS, KI PyTorch FP32 Ultralytics8.4.213. Fixed phone threshold0.840783 plus each model development-only F2 threshold on0.25..0.99 grid, tie recall/precision/higher threshold. IoU0.5 one-to-one reference matching; per-pass cap12; source NMS0.45.',
        'reporting':'Raw TP/FP/FN, recall, precision, F2, proposal workload, reviewed traffic-light FP subset, geographic-group bootstrap and visual errors. No post-audit retuning or model selection.',
        'limitations':['Only24 geographic samples; sign counts may be small.','Assistant review is not independent human certification.','Known d4 exposure audit is incomplete; upstream teacher/student/classifier exposure is unknown.','Sample is from the HF detector export, not a random road-scene population.','Native renderer on macOS plus KI FP32 does not establish iOS/Core ML parity or latency.']}
    root=ROOT/'protocol-publication';out=root/PREFIX/'protocol';out.mkdir(parents=True,exist_ok=False)
    write(out/'selection.json',selection);protocol['selection_sha256']=sha(out/'selection.json');write(out/'definition.json',protocol)
    shutil.copy2(__file__,out/'freeze_geographic_audit.py')
    (out/'README.md').write_text('# Blinded geographic audit protocol\n\nBefore opening the images, select one fixed-hash frame from each of24 reserved geographic groups. The d8 training recipe is already frozen and running. Reference review uses clean imagery and an independent YOLO11l proposal teacher, never d4/d8 outputs. Freeze reviewed labels and the final candidate/development thresholds before one evaluation. These are assistant-reviewed references with explicit limitations, not human-certified ground truth.\n')
    inventory(root,out,'dataset',PREFIX+'/protocol/definition.json',ROOT/'protocol-inventory.json')

if __name__=='__main__':main()

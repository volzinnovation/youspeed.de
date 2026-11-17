#!/usr/bin/env python3
"""Freeze the corrected dataset and matched-budget d9 experiment before training."""
import json,shutil
from pathlib import Path
import sys
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1'
sys.path.insert(0,str(JOB/'expanded-v1/recipe'))
from prepare_expanded_publication import sha,write,inventory

def main():
    assert json.loads((ROOT/'smoke-complete.json').read_text())['complete']
    smoke={}
    for arm in ['phone','mixed']:
        path=ROOT/('smoke-'+arm);seal=json.loads((path/'seal.json').read_text());history=json.loads((path/'history.json').read_text())
        assert seal['complete'] and seal['completed_epochs']==1 and history[-1]['draws']==32 and history[-1]['batches']==2
        assert history[-1]['optimizer_step_calls_total']==2
        smoke[arm]={'seal_sha256':sha(path/'seal.json'),'optimizer_step_calls':2,'actual_updates':history[-1]['optimizer_actual_updates_total'],'finite_epoch':True}
    summary=json.loads((ROOT/'data/summary.json').read_text())
    sources=json.loads((ROOT/'data/corrected-sources.json').read_text())['frames']
    schedule=json.loads((ROOT/'data/schedules.json').read_text())
    used={r['picture_id'] for e in schedule for r in e}
    geometry_exclusions=[{'picture_id':f['picture_id'],'reason':'No admitted positive phone view: a known sign intersects a crop boundary'} for f in sources if f['picture_id'] not in used]
    summary['geometry_excluded_sources']=geometry_exclusions
    write(ROOT/'data/summary.json',summary)
    definition={'schema':'streetshots-balanced-view-experiment-v1','candidate':'d9','source_summary':summary,'source_parent_revision':'5e51cd9333ec07a88d212de479d1d2139f007495','source_parent_manifest_sha256':'818457fffae759e6366fbc4946a40bf1386f51c0a5e326143904247a1488c71e','scope':'Primary signs only; no direction/wayfinding boards, supplementary plates, backs or vehicle markings. Traffic lights acceptable extras, not positives.','arms':['phone','mixed'],'initialization':'d4 YOLO26n strict state transfer; no random restart','d4_sha256':'f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36','ultralytics':'8.4.213','epochs_per_arm':40,'draws_per_epoch':1024,'epoch_definition':'1024 scheduled draws, not a full source-data pass','batch':16,'nbs':16,'expected_optimizer_step_calls_per_arm':2560,'imgsz':1024,'optimizer':'AdamW','lr0':.0002,'seed':14,'balance':'25% phone-positive,25% pseudo-negative,50% small-sign parents: phone-positive control vs small-positive tile. Identical parent sequence and positive fraction.','geometry':'Native phone window geometry; small tiles512..1536px centered on known signs below24px at phone input scale; targets~48px subject to limits. Known clipped signs reject entire view.','rendering':'Pillow bilinear 1024 gray114 training approximation; actual SwiftMac-rendered PNG development replay. Not iPhone CoreML precision or latency parity.','tile_flag':False,'tile_flag_reason':'Explicit balanced views are frozen externally; native tile=True expands mostly empty tiles and cannot express this matched parent schedule.','augmentation':'HSV only; mosaic,mixup,flips,rotation,translation,scale disabled','selection':'Max development recall subject to mean proposals/image <=4; then precision,higher threshold,earlier epoch. Grid .25..99 step.01. Epoch0 eligible.','development_images':17,'development_sign_faces':33,'native_manifest_sha256':'3e924732f8f4bcbd676a7f46a0c2feed39d8c507994eb1103261b65c2d4a214a','current_phone_threshold':.840783,'holdout_usage':'None. Original test and consumed geographic audit not used for new inference, tuning or selection. No fresh generalization claim.','review_limitations':'145 classifier-rejected proposals reviewed;16 fixed-hash overviews screened,2 targeted native regions.13 sign regions corrected. Most content remains weak; no exhaustive negative certification or population miss-rate estimate.','smoke_tests':smoke,'scripts':{p.name:sha(p) for p in sorted((ROOT/'recipe').glob('*.py'))},'dataset_artifacts':{p.name:sha(p) for p in [ROOT/'data/corrected-sources.json',ROOT/'data/views.json',ROOT/'data/schedules.json']}}
    write(ROOT/'definition.json',definition)
    publication=ROOT/'publication';dataset=publication/'reviews/detector-balanced-2026-11-15';model=publication/'detector/d9/definition'
    dataset.mkdir(parents=True,exist_ok=False);model.mkdir(parents=True,exist_ok=False)
    for name in ['corrected-sources.json','views.json','schedules.json','summary.json']:shutil.copy2(ROOT/'data'/name,dataset/name)
    review=dataset/'negative-review';review.mkdir()
    for pattern in ['*decisions.json','selection.json','cases.json','proposals-*.jpg','corrected-*.jpg','empty-overview-*.jpg']:
        for p in (ROOT/'negative-review').glob(pattern):shutil.copy2(p,review/p.name)
    for identity in ['69daa5f5-530d-4613-8b55-2775939c3fd5','b79cba6b-4bd6-4e81-b395-59520e7a26d4']:
        source=ROOT/'negative-review/teacher-empty'/identity/'clean-native-005.jpg';shutil.copy2(source,review/(identity+'-native-005.jpg'))
    shutil.copytree(ROOT/'negative-review/crops',review/'crops')
    for target in [dataset,model]:
        shutil.copy2(ROOT/'definition.json',target/'definition.json');shutil.copytree(ROOT/'recipe',target/'recipe',ignore=shutil.ignore_patterns('__pycache__'))
    text='''# Balanced small-sign and phone-crop experiment (d9)

The scope classifier discarded real bus-stop signs. Targeted visual review recovered **13 sign regions**:10 bus-stop faces,1 yield,1 no-stopping and1 bend-hazard board. Twelve were proposed by the teacher and rejected by the classifier; the hazard board came from the fixed teacher-empty sample. These are image regions, not deduplicated physical assets. Ambiguous frames are withheld.

This is **weakly supervised training**, with assistant-reviewed corrections. All145 rejected proposals in137 pseudo-negative images were inspected. Sixteen teacher-empty overviews were screened and two native regions inspected; these are not exhaustively annotated scenes. We do not estimate a population miss rate from this targeted sample. No live database or new Mapillary download was used.

The phone-only control and mixed arm use the same scheduled source parents and75% positive /25% pseudo-negative draws. Half the mixed arm uses small-sign tiles. Each of40 epochs is1024 draws, not a full pass over the source pool. Cycling parent queues cover all5,263 usable parents from the5,264 corrected-source pool; one additional parent has no admitted positive phone view without clipping a known sign. Exact view and parent schedules are published. Both start from d4 and have2560 planned optimizer-step calls. This isolates the view change within the corrected, balanced recipe; it does not separately estimate the benefit of label corrections or balancing against d8.

Native `tile=True` is deliberately off in this experiment: the tiles are explicitly prepared and balanced. Known clipped sign boxes exclude an entire view. Other missing labels remain possible. Images come from the pinned existing private HF copy; derived PNG training views can be rebuilt from source hashes, source coordinates, recipe and frozen schedules. Training uses Pillow rendering; development uses actual SwiftMac-rendered inputs and KI FP32 inference. Neither establishes iPhone CoreML numerical parity or latency.

Checkpoint/threshold selection uses only17 development images (33 faces), maximizing recall with mean proposals/image<=4, then precision,threshold and earlier epoch. The already consumed geographic audit and original test are not used. These small, reused development results will be exploratory, not a new holdout result.

The follow-up Panoramax experiment will start after the d9 comparison is published. It will fine-tune pretrained YOLO11l's sign channel, preserving its learned box head; it will not start from scratch or retain face/plate output classes. It is an offline teacher experiment, not a phone deployment.
'''
    for target in [dataset,model]:(target/'README.md').write_text(text+'\n```json\n'+json.dumps(summary,indent=2)+'\n```\n')
    with (dataset/'README.md').open('a') as stream:
        stream.write('\n## Reviewed corrections\n\n![Corrected regions1](negative-review/corrected-0.jpg)\n\n![Corrected regions2](negative-review/corrected-1.jpg)\n\n[Review decisions](negative-review/proposal-decisions.json) · [Teacher-empty screening](negative-review/empty-decisions.json)\n')
    inventory(publication,dataset,'dataset','reviews/detector-balanced-2026-11-15/corrected-sources.json',ROOT/'dataset-inventory.json')
    inventory(publication,model,'model','detector/d9/definition/definition.json',ROOT/'definition-inventory.json')

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Freeze d8 full-data training after verified dataset and d7 evidence publication."""
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import shutil
from prepare_expanded_publication import inventory,sha,write

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'expanded-v1';LATEST=JOB/'latest-ultralytics-v1'
PREFIX='reviews/detector-expanded-2026-11-15'


def main():
    receipt=json.loads((JOB/'publication-receipts/expanded-dataset-v1.json').read_text())
    assert receipt['private'] and receipt['postverification'] and receipt['repo_type']=='dataset'
    overlay=ROOT/'dataset'/PREFIX
    assert receipt['manifest']['sha256']==sha(overlay/'manifest.json')
    manifest=json.loads((overlay/'manifest.json').read_text())
    closure=json.loads((ROOT/'image-reference-verification.json').read_text())
    assert closure['postverification'] and closure['revision']==receipt['revision']
    assert closure['verified_images']==len(manifest['frames'])
    assert closure['inventory_sha256']==sha(overlay/'image-reference-inventory.json')
    pilot_receipt=json.loads((JOB/'publication-receipts/d7-results-model-v1.json').read_text())
    assert pilot_receipt['private'] and pilot_receipt['postverification']
    pilot_path=LATEST/'pilot-results-publication/model/detector/d7/results/summary.json'
    assert pilot_receipt['paths']['detector/d7/results/summary.json']['sha256']==sha(pilot_path)
    pilot=json.loads(pilot_path.read_text())
    chosen=pilot['phone_recall_recommendation']['arm']
    assert chosen in ('whole','tile')
    training=[r for r in manifest['frames'] if r['split']=='train']
    # Exact8.4.213 tile_windows count, verified against the installed function
    # by the runtime budget check before launch.
    def axis_count(n):return len(range(0,max(n-1024,0),round(1024*.8)))+1
    tiles=sum(axis_count(r['width'])*axis_count(r['height']) for r in training)
    samples=tiles if chosen=='tile' else len(training)
    epochs=max(10,math.ceil(150*len(training)/samples)) if chosen=='tile' else 150
    smoke=json.loads((LATEST/'smoke-whole/configuration.json').read_text())
    assert smoke['script_sha256']==sha(ROOT/'recipe/train_latest.py') and smoke['amp_enabled']
    counts=json.loads((overlay/'training-counts.json').read_text())
    base=json.loads((LATEST/'pilot-definition-publication/detector/d7/definition.json').read_text())
    value={k:v for k,v in base.items() if k not in ['arms','arm_recommendation','training_boxes','development_boxes']}
    value.update(build='d8',status='frozen_before_training',definition_frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        experiment='Full eligible weak-data expansion using the latest Ultralytics runtime and the d7-recommended training mode',
        dataset_revision=receipt['revision'],manifest_path=PREFIX+'/manifest.json',manifest_sha256=sha(overlay/'manifest.json'),
        training_images=counts['train']['images'],development_images=counts['validation']['images'],training_counts=counts,
        review_provenance='mixed model-assisted reviewed and teacher pseudo-labels; weak labels are neither exhaustive nor human-certified',
        epochs=epochs,batch=16,tile=chosen=='tile',cache='disk',patience=0,
        expected_training_samples_per_epoch=samples,
        training_budget={'whole_image_reference_epochs':150,'native_tiles_per_epoch':tiles,
                         'chosen_complete_source_epochs':epochs,'sample_presentations':epochs*samples,
                         'whole_image_reference_sample_presentations':150*len(training),
                         'rule':'Whole:150epochs. Tile:max(10,ceil(150*source_images/tile_samples)). This matches or exceeds the reference sample-presentation budget, not equal sign exposures or identical optimization.'},
        recipe_choice={'pilot_results_revision':pilot_receipt['revision'],'pilot_summary_sha256':sha(pilot_path),
                       'recommendation':chosen,'nominal_prespecified_f2_winner':pilot['recommended_training_arm_from_reused_development'],'reason':pilot['phone_recall_recommendation']},
        script_sha256=sha(ROOT/'recipe/train_latest.py'),launcher_sha256=sha(ROOT/'recipe/launch_latest_full.py'),
        dataset_mount_readonly=True,
        teacher_runtime='8.4.56 frozen upstream mining; student training uses8.4.213',
        pseudo_policy_sha256=sha(ROOT/'pseudo-policy.json'),admission_recipe_sha256=sha(ROOT/'recipe/pseudo_admission.py'),
        geographic_reserve_sha256=sha(ROOT/'final-geographic-reserve.json'),
        source_image_closure_sha256=sha(ROOT/'image-reference-verification.json'),
        test_usage='Consumed pilot test retained as provenance only; no new inference.93 metadata-qualified geographic images remain reserved and unreviewed.',
        limitations=['Pseudo-labels and teacher negatives are not exhaustive ground truth.','Development has only17 model-assisted images and has been reused.','Mac Core Image plus KI FP32 does not establish iOS/Core ML parity or latency.','Recovered d4 exposure is incomplete; upstream/classifier exposure are unknown.','Whole-image development AP selects the checkpoint; phone comparison is post-selection.'])
    root=LATEST/'full-definition-publication';dest=root/'detector/d8';dest.mkdir(parents=True,exist_ok=False)
    write(dest/'definition.json',value);(dest/'recipe').mkdir();(dest/'provenance').mkdir()
    for name in ('train_latest.py','train_evaluate.py','mobile_replay.py','replay_latest.py','pseudo_admission.py','manual_scope_exclusions.json','prepare_latest_full.py','launch_latest_full.py','finish_latest_full.py','package_latest_full.py'):
        shutil.copy2(ROOT/'recipe'/name,dest/'recipe'/name)
    for path in [ROOT/'image-reference-verification.json',ROOT/'final-geographic-reserve.json',ROOT/'pseudo-policy.json',overlay/'manifest.json',overlay/'training-counts.json',pilot_path]:
        shutil.copy2(path,dest/'provenance'/path.name)
    shutil.copy2(LATEST/'pilot-definition-publication/detector/d7/provenance/runtime-wheels.json',dest/'provenance/runtime-wheels.json')
    (dest/'README.md').write_text(f'# d8: latest-runtime full eligible data run\n\nFrozen before training. Ultralytics 8.4.213, d4 initialization, sign only, all {len(training)} admitted geographic/label-quality eligible training examples. The completed d7 comparison recommends {chosen} training: {epochs} complete epochs, {samples} training samples per epoch. The frozen definition explains the sample-presentation budget relative to 150 whole-image epochs. Weak teacher labels are explicitly distinguished from reviewed labels. Results will be published separately after completion. No deployment.\n')
    inventory(root,dest,'model','detector/d8/definition.json',LATEST/'full-definition-inventory.json')

if __name__=='__main__':main()

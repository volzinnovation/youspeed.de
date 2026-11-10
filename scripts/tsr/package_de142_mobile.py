#!/usr/bin/env python3
"""Package the frozen DE142 v3 exports after measured native numerical parity.

This updates bundled model identities, not thresholds, detector bytes, or the
speed-limit policy. Private training images and review labels are not copied.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = 'c057107156d7bd4d535ece48f88b492e9c754ba59e951302ebdf77bfd75a2dda'
TFLITE = 'f179b03a59aff8ceb8c0127077c595d0f1629d9b30d0cf487cfa11bf24f4b15a'
COREML = 'c697dd469ba4aa4e15ce7ff73459b5fa02d5ced7ea95d1dbe56d970aae902e9b'
PACK_ID = 'de-youspeed-expanded142-v3'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def tree_sha(path):
    digest = hashlib.sha256()
    for child in sorted(p for p in Path(path).rglob('*') if p.is_file()):
        assert not child.is_symlink()
        digest.update(child.relative_to(path).as_posix().encode() + b'\0' + child.read_bytes() + b'\0')
    return digest.hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--android-parity',type=Path,required=True,help='Measured summary with checkpoint_sha256, passed, tolerance, measured_max_abs_difference')
    p.add_argument('--coreml-parity',type=Path,required=True)
    a=p.parse_args(); e=a.evidence
    catalog=read(e/'candidate-pack-v3/prolix-de-class-catalog-v1.json')
    mapping=read(e/'candidate-pack-v3/class-mapping.json')
    assert len(mapping)==142 and [m['class_id'] for m in mapping]==catalog['class_labels']
    assert catalog['classifier_checkpoint_sha256']==CHECKPOINT
    source_android=e/'native/tflite-v3/expanded-native_float16.tflite'
    source_ios=e/'iphone/benchmark-input-v3/models/primary142.mlmodelc'
    assert sha(source_android)==TFLITE and tree_sha(source_ios)==COREML
    assert read(source_ios/'metadata.json')[0]['classLabels']==catalog['class_labels']
    parity={}
    for platform,path in [('android',a.android_parity),('ios',a.coreml_parity)]:
        report=read(path)
        assert report['checkpoint_sha256']==CHECKPOINT and report['passed'] is True
        assert report['tolerance']==.02 and 0<=report['measured_max_abs_difference']<=.02
        parity[platform]={k:v for k,v in report.items() if k!='per_image'}
    training=read(e/'final-v3-receipts/training-v3/configuration.json')
    dataset_sha=training['manifest_sha256']
    evaluation=read(e/'final-v3-receipts/training-v3/ontology-compatible-report-metrics.json')
    evaluation={k:v for k,v in evaluation.items() if k not in ('per_class','confusion')}
    evaluation.update(scope='Historical ontology-compatible report; not fresh field F1.',fresh_field_f1=None,new_class_heldout_f1=None,predecessor_historical_macro_f1=.9817534896670391,limitations=['Historical labels include legacy catch-all conflicts.','Fresh route-separated labels await user review.','Six new classes have no independent held-out reference labels.'])
    training_summary={k:training[k] for k in ['epochs','seed','initialization_sha256','manifest_sha256','selection','unique_training_samples','normalization','gpu','torch','ultralytics']}
    training_summary.update(checkpoint_sha256=CHECKPOINT,selected_epoch=2,classes=catalog['class_labels'],human_field_f1=False)
    attribution=[]
    for row in read(e/'training-intake-v3/new-intake.json')['samples']:
        attribution.append({k:row[k] for k in ('sha256','class_id','source_url','source_dataset','source_dataset_revision','author','license','license_url') if k in row})
    # Preserve independent existing presentation edits while promoting only model identity/order.
    current=read(ROOT/'shared/tsr/prolix-de-class-catalog-v1.json')
    existing={s['class_id']:s for s in current['signs']}
    candidate_ids={s['class_id'] for s in catalog['signs']}
    catalog['signs'].extend(deepcopy(s) for s in current['signs'] if s['class_id'] not in candidate_ids)
    for sign in catalog['signs']:
        if sign['class_id'] in existing:
            for key in ('aliases',):
                if key in existing[sign['class_id']]: sign[key]=existing[sign['class_id']][key]
        if sign['class_id'] in catalog['class_labels'][134:]:
            sign['notes']='Bundled DE142 classifier output; raw score is uncalibrated and fresh field F1 awaits review.'
            if sign['class_id']=='supplementary:plate': sign['notes']+=' Generic plate content remains unresolved until OCR or review; no unique official family pictogram.'
    for platform,relative in [('android','android/app/src/main/assets/tsr'),('ios','iphone/SpeedConsumerApp/TSRModelPacks')]:
        dest=ROOT/relative/'DE.panoramax-bootstrap.tsrmodelpack'; manifest=read(dest/'manifest.json')
        old_detector=deepcopy(manifest['detector']); old_thresholds=deepcopy(manifest['thresholds'])
        prov=dest/'provenance'
        write(prov/'expanded142-training.json',training_summary)
        write(prov/'expanded142-evaluation.json',evaluation)
        write(prov/'expanded142-parity.json',parity)
        write(prov/'expanded142-intake-attribution.json',attribution)
        export=read(e/('native/tflite-v3/export-report.json' if platform=='android' else 'native/coreml-v3/export-report.json'))
        write(prov/'expanded142-export.json',export)
        artifact=manifest['classifier']['artifacts'][0]
        target=dest/artifact['path']
        if platform=='android': shutil.copy2(source_android,target)
        else:
            # Replace the entire compiled tree to avoid retaining obsolete model files.
            if target.exists(): shutil.rmtree(target)
            shutil.copytree(source_ios,target)
        artifact.update(sha256=TFLITE if platform=='android' else COREML,source_checkpoint_sha256=CHECKPOINT,calibration_dataset_sha256=dataset_sha,parity={k:parity[platform][k] for k in ('tolerance','measured_max_abs_difference','passed')})
        artifact['exporter']['configuration']='imgsz=224,batch=1,half=true,nms=false,dynamic=false; RGB/255; 142 frozen output classes'
        if platform=='android': artifact['exporter']['version']='8.4.56+1.17.0+1.28.8+2.19.0'
        manifest['classifier'].update(component_id='youspeed-de-expanded142-v3',source_checkpoint={'uri':'urn:sha256:'+CHECKPOINT,'revision':'de-expanded-2026-11-09-v3-epoch2','sha256':CHECKPOINT})
        manifest.update(pack_id=PACK_ID,class_mapping=mapping)
        manifest['calibration'].update(revision='uncalibrated-de-expanded142-v3',dataset_sha256=dataset_sha,calibrated=False,runtime_output='raw_score')
        manifest['lineage'].update(source_manifest_sha256=sha(ROOT/'shared/tsr/baselines/de134-expanded-reference-2026-11-09/model-pack.json'),dataset_inventory_sha256s=list(dict.fromkeys(manifest['lineage']['dataset_inventory_sha256s']+[dataset_sha])),training_run_id='de-expanded-2026-11-09-v3-epoch2',training_run_sha256=sha(prov/'expanded142-training.json'),evaluation_report_sha256=sha(prov/'expanded142-evaluation.json'),parity_report_sha256=sha(prov/'expanded142-parity.json'))
        assert manifest['detector']==old_detector and manifest['thresholds']==old_thresholds
        write(dest/'manifest.json',manifest)
        shadow=dest/'shadow-runtime-v2.json'
        if shadow.exists():
            d=read(shadow); d.update(source_pack_id=PACK_ID,pack_id='de-youspeed-expanded142-shadow-v2')
            d['classifier'].update(component_id=manifest['classifier']['component_id'],artifact_id='youspeed-de142-coreml-'+COREML[:8]+'-v2',artifact_sha256=COREML)
            d['classifier']['calibration'].update(id='youspeed-de142-uncalibrated-v3',dataset_sha256=dataset_sha)
            write(shadow,d)
        notice=dest/'THIRD_PARTY_NOTICES.txt'; text=notice.read_text()
        marker='\nDE142 expanded classifier, 2026-11-10\n'
        if marker not in text:
            notice.write_text(text+marker+'Fine-tuned from the Panoramax DE classifier and the preserved 136-class predecessor.\nAdditional public Panoramax imagery attribution and licenses are recorded in\nprovenance/expanded142-intake-attribution.json; official pictogram sources are\nin the shared sign-pictograms notices. Municipal/OSM anchors are search hints,\nnot reference labels. New intake uses assistant silver labels for TRAIN only.\nBootstrap provenance files retained here describe the predecessor/detector.\nexpanded142-* provenance files describe the current classifier.\nRaw scores remain uncalibrated. Fresh field F1 awaits human label review.\n')
    write(ROOT/'shared/tsr/prolix-de-class-catalog-v1.json',catalog)
    print(json.dumps({'pack_id':PACK_ID,'classes':142,'checkpoint_sha256':CHECKPOINT,'android_sha256':TFLITE,'coreml_runtime_tree_sha256':COREML}))

if __name__=='__main__': main()

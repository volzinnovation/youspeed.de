#!/usr/bin/env python3
"""Evaluate a separately frozen prospective example set without weakening training binding."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

from model_utils import (BASELINE_SHA256, PREPROCESSING, dataset, dependencies,
                         device_for, load_baseline, load_candidate, load_classes,
                         load_manifest, metrics_from_predictions, old_class_regression,
                         predict, sha256, write_json)


def require(value, reason):
    if not value: raise ValueError(reason)


def pixel_hash(Image, ImageOps, path):
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        return hashlib.sha256(str(image.size).encode()+b'\0'+image.tobytes()).hexdigest()


def load_reviewed_rows(path, overlay_path, train_manifest, classes, Image, ImageOps):
    require(sha256(path)==train_manifest['reserved_test_manifest_sha256'],
            'Reserved test differs from the pre-training manifest binding')
    document = json.loads(path.read_text())
    require(document['frozen_before_candidate_predictions'] is True, 'Test not frozen before predictions')
    require(document['human_approved'] is False, 'Review provenance changed unexpectedly')
    overlay = json.loads(overlay_path.read_text())
    require(overlay['parent_manifest_sha256']==sha256(path), 'Exclusion overlay refers to a different test')
    require(overlay['before_any_test_predictions_viewed'] is True, 'Exclusions not declared before predictions')
    excluded_list = [x['sample_id'] for x in overlay['exclusions']]
    require(all(x.get('reason') for x in overlay['exclusions']), 'Exclusion reason missing')
    excluded = set(excluded_list)
    require(len(excluded)==len(excluded_list), 'Duplicate exclusion ID')
    require(excluded <= {r['sample_id'] for r in document['rows']}, 'Unknown exclusion ID')
    # Deliberately retain the original training-manifest hash in the candidate loader.
    development = [r for r in train_manifest['samples'] if r['split'] in ['train','val']]
    dev_hashes = {r['sha256'] for r in development}
    dev_rgb = {r['rgb_sha256'] for r in development}
    dev_groups = {r['group_id'] for r in development}
    dev_sources = {r.get('source_id') for r in development}
    rows = []
    for r in document['rows']:
        if r['sample_id'] in excluded or not r.get('include_primary', True): continue
        require(r['label'] in classes and r['group_id'] not in dev_groups, 'Test label/group invalid')
        require(r.get('picture_id') not in dev_sources, 'Test source image was used in development')
        require(r['human_reviewed'] is False and r['review_type']=='assistant_visual', 'Review provenance invalid')
        crop = Path(r['crop_absolute_path']); source = Path(r['input_image_absolute_path'])
        require(sha256(crop)==r['crop_sha256'], 'Test crop changed')
        require(sha256(source)==r['input_sha256'], 'Test input image changed')
        require(r['crop_sha256'] not in dev_hashes and pixel_hash(Image, ImageOps, crop) not in dev_rgb,
                'Test crop overlaps train/val')
        with Image.open(source) as image, Image.open(crop) as crop_image:
            b = r['bbox_xyxy']
            require(len(b)==4 and all(float(x).is_integer() for x in b), 'Non-integral reviewed pixel box')
            b = [int(x) for x in b]
            require(0<=b[0]<b[2]<=image.width and 0<=b[1]<b[3]<=image.height, 'Reviewed box outside raster')
            actual = image.convert('RGB').crop(b)
            require(actual.size==crop_image.size and actual.tobytes()==crop_image.convert('RGB').tobytes(),
                    'Reviewed crop is not exactly the declared input-pixel box')
        rows.append(dict(r, resolved_path=str(crop), class_index=classes.index(r['label'])))
    require(rows, 'No primary rows remain')
    require(len({r['sample_id'] for r in rows})==len(rows), 'Duplicate primary test ID')
    # Normalized only in memory; original overlay file and SHA remain unchanged.
    return rows, document, dict(overlay, excluded_sample_ids=excluded_list)


def grouped_summary(rows, truth, predictions, key):
    groups = defaultdict(list)
    for row, target, predicted in zip(rows, truth, predictions):
        groups[row[key]].append(target==predicted)
    return {'units':len(groups),
            'mean_within_unit_accuracy':sum(sum(v)/len(v) for v in groups.values())/len(groups),
            'all_views_correct_units':sum(all(v) for v in groups.values()),
            'per_unit':{k:{'views':len(v),'correct':sum(v),'all_views_correct':all(v)} for k,v in groups.items()}}


def number(x):
    return 'nicht messbar' if x is None else f'{100*x:.1f} %'


def write_reports(output, report, rows, truth, old, new, classes):
    output.mkdir(parents=True)
    write_json(output/'metrics.json',report)
    write_json(output/'old-partial-regression-gate.json',report['old_partial_gate'])
    with (output/'predictions.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['sample_id','subset','site_id','group_id','true_label','baseline_label','candidate_label','candidate_correct','source_url'])
        writer.writerows([r['sample_id'],r['subset'],r['site_id'],r['group_id'],classes[t],classes[o],classes[n],t==n,r['source_url']]
                         for r,t,o,n in zip(rows,truth,old,new))
    with (output/'per-class.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['class','support','baseline_precision','baseline_recall','baseline_f1','candidate_precision','candidate_recall','candidate_f1'])
        for a,b in zip(report['baseline']['per_class'],report['candidate']['per_class']):
            writer.writerow([a['label'],a['support'],a['precision'],a['recall'],a['f1'],b['precision'],b['recall'],b['f1']])
    for name in ['baseline','candidate']:
        with (output/f'confusion-{name}.csv').open('w',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['true / predicted']+classes)
            for label,counts in zip(classes,report[name]['confusion']):writer.writerow([label]+counts)
    lines=['# Prospektiver TSR-Beispielvergleich', '',
           '**Sichtprüfung durch KI-Assistenten, keine menschliche Ground-Truth-Freigabe.**', '',
           'Gezielt gesammelte Beispiele; kein repräsentativer Blindtest und kein Nachweis einer allgemeinen Modellfreigabe.', '',
           f"{len(rows)} primäre Crops; {len({r['site_id'] for r in rows})} Standortkennungen und {len({r['group_id'] for r in rows})} konservative Gruppen.",
           'Die Standort-/Fahrtunabhängigkeit ist nicht abschließend menschlich bestätigt. Die zielzentrierten Panoramaprojektionen werden getrennt ausgewiesen.', '',
           f"Vor Vorhersagen ausgeschlossene zweifelhafte Labels: {len(report['excluded_sample_ids'])}. Originalmanifest und Trainingsbindung bleiben erhalten.", '',
           '| Primärer Cropvergleich | Baseline134 | Kandidat136 |','| --- | ---: | ---: |',
           f"| Accuracy | {number(report['baseline']['accuracy'])} | {number(report['candidate']['accuracy'])} |", '',
           '## Neue Ortstafelklassen','', '| Klasse | Support | Präzision | Recall | F1 |','| --- | ---: | ---: | ---: | ---: |']
    for row in report['candidate']['per_class'][-2:]:
        lines.append(f"| {row['label']} | {row['support']} | {number(row['precision'])} | {number(row['recall'])} | {number(row['f1'])} |")
    lines+=['','Die Baseline besitzt keine eigenen city:start/city:end-Ausgänge. Höhere Werte dort belegen zunächst die neue Ausgabefähigkeit auf diesen Beispielen.', '',
            '## Getrennte Bildarten','', '| Teilmenge | Bilder | Baseline Accuracy | Kandidat Accuracy |','| --- | ---: | ---: | ---: |']
    for subset,metrics in report['subsets'].items():
        lines.append(f"| {subset} | {metrics['views']} | {number(metrics['baseline']['accuracy'])} | {number(metrics['candidate']['accuracy'])} |")
    lines+=['','## Standorte und konservative Gruppen','',
            'Mehrere Ansichten einer Tafel zählen hier zusätzlich als ein Standort: zuerst der mittlere Anteil korrekter Ansichten innerhalb jedes Standorts, dann der ungewichtete Mittelwert dieser Standorte.', '',
            f"Standortgewichtete City-Accuracy des Kandidaten: {number(report['city_site_candidate']['mean_within_unit_accuracy'])}; alle Ansichten korrekt bei {report['city_site_candidate']['all_views_correct_units']}/{report['city_site_candidate']['units']} Standorten.", '',
            '## Bestehende Klassen','',
            f"Dieser externe Teilbestand deckt nur {sum(r['support']>0 for r in report['candidate']['per_class'][:134])} alte Klassen ab. Sein separates Altklassen-Gate lautet {report['old_partial_gate']['status']}; das ersetzt keinen Vergleich aller 134 Klassen.",
            'Der vollständig abgedeckte Altklassenvergleich steht im gesonderten retrospektiven Bericht. Dessen öffentlicher Ursprungskorpus kann bereits dem Baseline-Training bekannt gewesen sein und ist keine unabhängige absolute Qualitätsmessung.', '',
            '## Bindung und Grenzen','',
            f"Trainingsmanifest SHA256: `{report['training_manifest_sha256']}`",f"Originaltestmanifest SHA256: `{report['test_manifest_sha256']}`",f"Ausschluss-Overlay SHA256: `{report['exclusion_overlay_sha256']}`",f"Kandidat SHA256: `{report['candidate_sha256']}`", '',
            'Keine Detektor-Recall-Messung, kein Mobilplattformtest und keine Garantie für weitere Straßenbilder. Nach dieser Testeinsicht werden keine Hyperparameter anhand dieses Bestands geändert.']
    (output/'BERICHT.md').write_text('\n'.join(lines)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--test-manifest',type=Path,required=True)
    p.add_argument('--exclusion-overlay',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',default='cuda:0');p.add_argument('--batch-size',type=int,default=64)
    a=p.parse_args();require(not a.output.exists(),'Output exists; preserve earlier reports')
    classes=load_classes();training,training_sha=load_manifest(a.data,classes)
    torch,ultralytics,np,Image,ImageOps=dependencies()
    rows,source,overlay=load_reviewed_rows(a.test_manifest,a.exclusion_overlay,training,classes,Image,ImageOps)
    loader=torch.utils.data.DataLoader(dataset(torch,np,Image,ImageOps,rows),batch_size=a.batch_size,shuffle=False,num_workers=0)
    device=device_for(torch,a.device)
    baseline=load_baseline(torch,ultralytics,a.baseline,classes).to(device)
    truth,old=predict(torch,baseline,loader,device,'Prospektive Baseline')
    baseline.to('cpu')
    candidate,metadata=load_candidate(torch,baseline,a.candidate,classes,training_sha)
    candidate.to(device);candidate_truth,new=predict(torch,candidate,loader,device,'Prospektiver Kandidat')
    require(truth==candidate_truth,'Evaluation sample ordering changed')
    report={'schema_version':'real-city-reserved-evaluation-v1','execution_status':'completed','model_accepted':False,
            'review_type':'assistant_visual','human_reviewed':False,'preprocessing':PREPROCESSING,
            'baseline_sha256':BASELINE_SHA256,'candidate_sha256':sha256(a.candidate),
            'training_manifest_sha256':training_sha,'test_manifest_sha256':sha256(a.test_manifest),
            'exclusion_overlay_sha256':sha256(a.exclusion_overlay),'excluded_sample_ids':overlay['excluded_sample_ids'],
            'candidate_selected_epoch':metadata['epoch'],'baseline':metrics_from_predictions(truth,old,classes),
            'candidate':metrics_from_predictions(truth,new,classes),'old_partial_gate':old_class_regression(truth,old,new,classes),
            'subsets':{},'device':str(device),'torch':str(torch.__version__),'ultralytics':ultralytics.__version__}
    for subset in sorted({r['subset'] for r in rows}):
        indices=[i for i,r in enumerate(rows) if r['subset']==subset]
        report['subsets'][subset]={'views':len(indices),'baseline':metrics_from_predictions([truth[i] for i in indices],[old[i] for i in indices],classes),
                                  'candidate':metrics_from_predictions([truth[i] for i in indices],[new[i] for i in indices],classes)}
    city_indices=[i for i,t in enumerate(truth) if t>=134]
    city_rows=[rows[i] for i in city_indices];city_truth=[truth[i] for i in city_indices]
    require(city_rows,'No city test examples')
    for name,predictions in [('baseline',old),('candidate',new)]:
        pred=[predictions[i] for i in city_indices]
        report['city_site_'+name]=grouped_summary(city_rows,city_truth,pred,'site_id')
        report['city_group_'+name]=grouped_summary(city_rows,city_truth,pred,'group_id')
    write_reports(a.output,report,rows,truth,old,new,classes)
    print(json.dumps({'execution_status':'completed','primary_rows':len(rows),'candidate_accuracy':report['candidate']['accuracy'],
                      'city':report['candidate']['per_class'][-2:],'output':str(a.output)}),flush=True)


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,RuntimeError,KeyError) as error:
        print('ERROR: '+str(error),file=sys.stderr);raise SystemExit(2)

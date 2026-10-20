#!/usr/bin/env python3
"""Combine saved predictions for precision denominators, without model inference."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from model_utils import load_classes,metrics_from_predictions,old_class_regression,sha256,write_json


def percent(value): return 'nicht messbar' if value is None else f'{value*100:.1f} %'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--old-report',type=Path,required=True)
    p.add_argument('--prospective-report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): raise ValueError('Output already exists')
    classes=load_classes();records=[];seen=set();bindings={}
    for domain,folder in [('retrospective_old',a.old_report),('prospective_assistant_reviewed',a.prospective_report)]:
        metrics=json.loads((folder/'metrics.json').read_text())
        for key in ['baseline_sha256','candidate_sha256']:
            if key in bindings and bindings[key]!=metrics[key]: raise ValueError('Reports use different models')
            bindings[key]=metrics[key]
        with (folder/'predictions.csv').open() as stream:
            for row in csv.DictReader(stream):
                if row['sample_id'] in seen: raise ValueError('Duplicate sample across report domains')
                seen.add(row['sample_id']);row['domain']=domain;records.append(row)
    truth=[classes.index(r['true_label']) for r in records]
    old=[classes.index(r['baseline_label']) for r in records]
    new=[classes.index(r['candidate_label']) for r in records]
    result={'schema_version':'real-city-joint-predictions-v1','new_model_inference':False,
            'domain_warning':'Mixed retrospective public old corpus and prospective assistant-reviewed examples; retain separate domain tables.',
            'model_accepted':False,'human_reviewed':False,'views':len(records),'domain_counts':dict(Counter(r['domain'] for r in records)),
            'baseline':metrics_from_predictions(truth,old,classes),'candidate':metrics_from_predictions(truth,new,classes),
            'combined_old_gate_auxiliary':old_class_regression(truth,old,new,classes),**bindings,
            'inputs':{str(folder/'predictions.csv'):sha256(folder/'predictions.csv') for folder in [a.old_report,a.prospective_report]}}
    a.output.mkdir(parents=True);write_json(a.output/'metrics.json',result)
    fields=['sample_id','domain','group_id','true_label','baseline_label','candidate_label']
    with (a.output/'predictions.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(records)
    lines=['# Gemeinsame Nenner für neue Ortstafelklassen','',
           '**Keine zusätzliche Inferenz.** Diese Tabelle kombiniert ausschließlich gespeicherte Vorhersagen derselben beiden Modelle.', '',
           'Die Bestände haben unterschiedliche Aussagekraft: retrospektiver öffentlicher Altklassenkorpus und prospektive, durch Assistenten sichtgeprüfte Beispiele. Die getrennten Berichte bleiben maßgeblich.', '',
           f"{len(records)} Crops: {result['domain_counts']}", '',
           'Alle alten Zielbilder zählen als mögliche Falschpositive für city:start/city:end. So verschweigt die City-Präzision keine Ortstafelvorhersagen auf alten Zeichen.', '',
           '| Klasse | Support | Baseline P/R/F1 | Kandidat P/R/F1 |','| --- | ---: | --- | --- |']
    for oldrow,newrow in zip(result['baseline']['per_class'][-2:],result['candidate']['per_class'][-2:]):
        fmt=lambda r:' / '.join(percent(r[k]) for k in ['precision','recall','f1'])
        lines.append(f"| {newrow['label']} | {newrow['support']} | {fmt(oldrow)} | {fmt(newrow)} |")
    lines+=['','Die 134 Bestandsklassen werden zusätzlich einzeln im retrospektiven Gate verglichen. Diese gemeinsame Darstellung ist keine unabhängige repräsentative Qualitätsmessung und keine Modellfreigabe.', '',
            f"Kandidat SHA256: `{result['candidate_sha256']}`",f"Baseline SHA256: `{result['baseline_sha256']}`"]
    (a.output/'BERICHT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'views':len(records),'domain_counts':result['domain_counts'],'city_candidate':result['candidate']['per_class'][-2:],'output':str(a.output)}),flush=True)


if __name__=='__main__': main()

#!/usr/bin/env python3
"""Summarize the single completed scoring event; never loads a model."""
import csv
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    root = Path(__file__).resolve().parent
    experiment = root.parent.parent
    build = experiment.parent
    result_path = root/'output/results-01/pipeline-results.json'
    result = json.loads(result_path.read_text())
    receipt = json.loads((root/'completion-receipt.json').read_text())
    assert receipt['state']['ExitCode'] == 0 and not receipt['state']['Running']
    artifacts = json.loads((root/'output/results-01/artifact-sha256.json').read_text())
    for item in artifacts['files']:
        path = root/'output/results-01'/item['path']
        assert path.stat().st_size == item['bytes'] and sha(path) == item['sha256']
    component_consistency = {}
    for name, filename in [('baseline_pair', 'baseline-target-recall.json'), ('candidate_pair', 'candidate-target-recall.json')]:
        component_path = root.parent/'test-01'/filename
        component = json.loads(component_path.read_text())
        old = {r['sample_id']: r['matched'] for r in component['predictions'] if r['label'] in ['city:start', 'city:end']}
        current = {r['sample_id']: r['result'] != 'detector_miss' for r in result['arms'][name]['known_target_results']}
        assert old == current
        component_consistency[name] = {'component_report_sha256': sha(component_path),
                                       'all_15_match_flags_identical': True,
                                       'matched_targets': sum(current.values())}
    frozen_path = experiment/'review-test/reviewed-test.json'
    frozen = json.loads(frozen_path.read_text())
    assert sha(frozen_path) == result['frozen_target_manifest_sha256']
    targets = [r for r in frozen['rows'] if r['label'] in ['city:start', 'city:end']]
    external_path = build/'external-holdout-2026-10-20/final-audit/manifest.json'
    own_path = build/'holdout-2026-10-20/collection/manifest.json'
    external = json.loads(external_path.read_text())
    own = json.loads(own_path.read_text())
    ext_by_picture = {r['picture_id']: r for r in external['records']}
    own_by_picture = {r['picture_id']: r for r in own['items']}
    provenance = []
    for target in targets:
        source = ext_by_picture.get(target['picture_id'], own_by_picture.get(target['picture_id']))
        assert source is not None
        original_semantics = source.get('original_annotation_semantics')
        original_metadata_sha256 = source.get('assets', {}).get('source_metadata', {}).get('sha256')
        if original_semantics is None:
            metadata_path = build/'holdout-2026-10-20/collection'/source['bundle_path']/'metadata.json'
            metadata = json.loads(metadata_path.read_text())
            annotations = metadata['original_item']['properties']['annotations']
            original = [r for r in annotations if target['sample_id'].endswith('_a' + r['id'])]
            assert len(original) == 1
            original_semantics = original[0]['semantics']
            original_metadata_sha256 = sha(metadata_path)
        provenance.append({
            **{k: target[k] for k in ['sample_id', 'picture_id', 'sequence_id', 'label', 'site_id', 'group_id', 'subset', 'bbox_xyxy', 'input_sha256', 'source_url', 'review_type', 'human_reviewed', 'all_objects_complete']},
            'input_raster_transform': 'local spherical-to-pinhole perspective projection' if target['subset'] == 'projected' else 'native registered raster',
            'author': source.get('author'), 'license': source.get('license'),
            'original_annotation_semantics': original_semantics,
            'original_source_metadata_sha256': original_metadata_sha256,
            'source_tags_changed_by_this_experiment': False,
            'new_predicted_crops': 'All post-NMS sign crops of this source frame, including unmatched detections; these are model predictions, not complete GT.'})
    assert all(r['license'] == 'CC-BY-SA-4.0' and r['author'] for r in provenance)
    save(root/'city15-source-provenance.json', {
        'schema_version': 'pipeline-city15-source-provenance-v1',
        'frozen_manifest_sha256': sha(frozen_path),
        'provenance_manifest_sha256': {'external': sha(external_path), 'own': sha(own_path)},
        'derivative_image_license': 'CC-BY-SA-4.0',
        'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
        'image_changes': 'Previously registered native or pinhole-projected RGB rasters cropped at actual model-predicted boxes; floor/ceil/clamped. Clean lossless RGB PNG. No new source annotations or uploads.',
        'rows': provenance})
    csv_fields = ['sample_id', 'label', 'subset', 'site_id', 'group_id', 'baseline_result', 'candidate_result',
                  'baseline_predicted_label', 'candidate_predicted_label', 'baseline_matched_iou', 'candidate_matched_iou',
                  'baseline_crop_sha256', 'candidate_crop_sha256']
    arms = result['arms']
    maps = {name: {r['sample_id']: r for r in arm['known_target_results']} for name, arm in arms.items()}
    with (root/'known-city-pipeline-comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields)
        writer.writeheader()
        for sid, candidate in maps['candidate_pair'].items():
            baseline = maps['baseline_pair'][sid]
            writer.writerow({**{k: candidate[k] for k in ['sample_id', 'label', 'subset', 'site_id', 'group_id']},
                             **{f'{prefix}_{key}': row[source] for prefix, row in [('baseline', baseline), ('candidate', candidate)]
                                for key, source in [('result', 'result'), ('predicted_label', 'predicted_label_from_detected_crop'), ('matched_iou', 'matched_iou'), ('crop_sha256', 'detected_crop_sha256')]}})
    summary = {
        'schema_version': 'fixed-pipeline-city15-summary-v1',
        'analysis_only_no_new_inference': True,
        'source_result_sha256': sha(result_path),
        'execution_started_at': receipt['state']['StartedAt'], 'execution_finished_at': receipt['state']['FinishedAt'],
        'single_scoring_event_exit_code': 0,
        'component_detector_consistency': component_consistency,
        'arms': {name: {k: arm[k] for k in ['summary', 'by_label', 'by_subset', 'site_balanced', 'group_balanced']} for name, arm in arms.items()},
        'all_post_nms_predicted_sign_crops': {name: sum(d['detector_class_id'] == 0 for f in arm['full_frames_and_all_post_nms_detections'] for d in f['detections']) for name, arm in arms.items()},
        'limitations': result['limits'] + ['The independently measured old-134-class TSR regression gate remains REGRESSION; this city-only pipeline score does not override that failure.']}
    save(root/'summary.json', summary)
    report = '''# Fester Pipeline-Test: SGBlur → TSR, 20.10.2026

Die ausgewählte Modellkette erkennt und klassifiziert **9 von 15 bekannten Ortstafel-Zielen korrekt (60 %)**. Sechs Ziele verfehlt bereits SGBlur. TSR klassifiziert alle neun passenden, tatsächlich erkannten Ausschnitte richtig. Es wurden keine GT-Ausschnitte als TSR-Eingabe verwendet.

| Bekannte Ziele | Unterstützung | SGBlur trifft | Kette korrekt | Detektor verfehlt | TSR falsch nach Detektortreffer |
|---|---:|---:|---:|---:|---:|
| DE:310 / city:start | 3 | 2 | 2 (66,7 %) | 1 | 0 |
| DE:311 / city:end | 12 | 7 | 7 (58,3 %) | 5 | 0 |
| Insgesamt | 15 | 9 | 9 (60,0 %) | 6 | 0 |

Externe native Perspektivbilder: 7/11 korrekt; eigenes natives Perspektivbild: 1/1; lokal aus Kugelpanoramen projizierte Bilder: 1/3. Gleichgewichtung der 14 Standortkandidaten ergibt 64,29 %, der 13 konservativen Gruppen 65,38 %. Diese Gruppierung belegt keine physische Unabhängigkeit.

Die Baseline-Kette trifft vier Zielboxen und klassifiziert keine Ortstafel korrekt. Der ursprüngliche TSR-Klassifikator besitzt keine Ausgänge für city:start/end; sein Nullwert ist daher durch den Wortschatz vorgegeben. Der Kandidat nutzt den vorher auf Validierungsdaten ausgewählten SGBlur-Checkpoint aus Epoche 9 und TSR aus Epoche 4. Alle 20 Trainingsepochen waren vor diesem Lauf abgeschlossen. Kein Modell, Schwellenwert oder Verarbeitungsschritt wurde anhand dieser Pipeline-Ergebnisse ausgewählt oder angepasst.

Der einzige zusätzliche Auswertungslauf lief am 20.10.2026 von 11:03:46 bis 11:04:03 UTC auf GPU 2 (RTX A5000), isoliert im unveränderten Containerabbild. Quellen und Gewichte waren nur lesbar eingebunden. Fixe Schwellen: SGBlur 1280 px, Konfidenz 0,25, NMS-IoU 0,70; eindeutige Zielzuordnung bei IoU ≥ 0,50. Alle Post-NMS-Schilder wurden vor dem GT-Abgleich klassifiziert. Ausschnitte: tatsächliche native Modellbox, links/oben abrunden, rechts/unten aufrunden und auf das Bild begrenzen; RGB, bilinear 224×224, float32/255.

Die 15 Detektor-Trefferentscheidungen stimmen für beide Modellstände einzeln exakt mit den vorherigen SGBlur-Komponentenberichten überein (4 Baseline, 9 Kandidat). Aufbewahrt werden alle Post-NMS-Boxen einschließlich plate/face, 22 Baseline- und 37 Kandidaten-Schilderausschnitte, sämtliche TSR-Logits, Wahrscheinlichkeiten, Klassen, GT-Zuordnungen und Prüfsummen. Diese 59 Ausschnitte umfassen auch zusätzliche, nicht als Ziel annotierte Schilder. Ihre Anzahl erlaubt keine Präzisionsaussage.

Der separat gemessene TSR-Test der bisherigen 134 Klassen meldet **REGRESSION**. Der Ortstafel-Erfolg hebt diesen Befund nicht auf; es liegt keine allgemeine Modell- oder App-Freigabe vor. Die kleine, gezielt gewählte und durch den Assistenten geprüfte Stichprobe besitzt keine vollständige Szenenannotation und erlaubt weder AP/Präzision noch eine Aussage zur vollständigen face/plate-Regression. Native und projizierte Quellen bleiben getrennt auswertbar.

## Belege

- `output/results-01/pipeline-results.json`: vollständige unveränderte Modellvorhersagen und Zielzuordnungen.
- `known-city-pipeline-comparison.csv`: ein Datensatz je bekanntem Ziel.
- `summary.json`: Zusammenfassungen und exakter Abgleich mit den Komponentenberichten.
- `plan.json`, `pipeline_city15.py`, `launch-receipt.json`, `completion-receipt.json`: vorab fixierter Plan, ausgeführter Code und Laufbelege.
- `city15-source-provenance.json`: Urheber, Quelllinks, Lizenz, Originaltags und Bearbeitung der Bildquellen. Ausschnitte stehen unter CC BY-SA 4.0; sie sind Modellvorschläge und keine vollständige Ground Truth.
- `output/results-01/artifact-sha256.json`: originale Prüfsummen des Auswertungslaufs. Die separaten Komponentenberichte wurden unverändert belassen.
'''
    (root/'REPORT.md').write_text(report)
    print(json.dumps({'summary': str(root/'summary.json'), 'report': str(root/'REPORT.md'), 'all_artifacts_verified': True, 'component_match_flags_identical': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()

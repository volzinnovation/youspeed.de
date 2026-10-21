#!/usr/bin/env python3
"""Package the MobiData-guided lecture review inbox; never approve or split data."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
LECTURE = ROOT / 'lectures/tsr-sgblur-de-2026-10-26'
NAME = 'panoramax-mobidata-bw-review-2026-10-20'
EVIDENCE = LECTURE / 'source/mobidata-bw-review-2026-10-20'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def safe_source(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Missing or unsafe source asset: '+relative)
    return path


def package(source_root, collection, archive, evidence=EVIDENCE, link_assets=False, archive_root=NAME):
    if not archive_root or Path(archive_root).name != archive_root or archive_root in {'.','..'}:
        raise ValueError('Expected a simple archive root directory name')
    def asset(source, destination):
        # Only opt in for immutable, already checksummed local evidence.
        if link_assets:
            try:
                os.link(source, destination)
                return
            except OSError:
                pass
        shutil.copyfile(source, destination)
    manifest = json.loads((evidence / 'manifest.json').read_text())
    records = manifest['records']
    if not records or any(r['human_approved'] or r['eligible_for_training'] or r['approved_for_evaluation'] for r in records):
        raise ValueError('Expected unapproved review candidates')
    # Validate every asset before creating the review destination.
    for r in records:
        for key, digest in [('image_path', 'hd_sha256'), ('crop_path', 'crop_sha256'), ('metadata_path', 'source_item_sha256')]:
            path = safe_source(source_root, r[key])
            if sha(path) != r[digest]:
                raise ValueError('Source hash mismatch: '+r[key])
    collection.mkdir(parents=True, exist_ok=False)  # Protect any manual review on reruns.
    crop_rows, frame_rows, origins = [], [], []
    for r in records:
        cid = 'bw-'+r['picture_id']
        source_paths = {key: r[key] for key in ['image_path','crop_path','metadata_path']}
        image = 'inbox/detector/'+cid+'/image.jpg'
        crop = 'inbox/classifier/'+cid+'.png'
        meta = 'metadata/'+r['picture_id']+'.json'
        for key, relative in [('image_path',image),('crop_path',crop),('metadata_path',meta)]:
            dst = collection / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            asset(safe_source(source_root, source_paths[key]), dst)
            r[key] = relative
        if r.get('overlay_path'):
            dst = collection / r['overlay_path'];dst.parent.mkdir(parents=True,exist_ok=True)
            asset(safe_source(source_root,r['overlay_path']),dst)
        label = {'DE:310':'city:start','DE:311':'city:end'}[r['visible_class_proposal']]
        r.setdefault('conservative_split_group_id','sequence:'+r['sequence_id'])
        r.update(candidate_id=cid, role='exploratory_lecture_review', proposed_model_label=label,
                 site_candidate_id='registry-location:'+r['registry_location_id'],
                 all_visible_object_annotation_complete=False)
        proposal = dict(schema_version='youspeed-target-box-review-proposal-v1',
            candidate_id=cid, picture_id=r['picture_id'], sequence_id=r['sequence_id'],
            image_file='image.jpg', image_sha256=r['hd_sha256'],
            bbox_xyxy=r['target_bbox_xyxy_proposal'],
            bbox_coordinate_system='native_input_pixel_edges_right_bottom_exclusive',
            detector_class_proposal={'id':0,'name':'sign'},
            class_proposal={'osm|traffic_sign':r['visible_class_proposal'],'model_label':label},
            registry_sign_code=r['registry_class'], source_annotation_id=r['source_target_annotation_id'],
            source_target_status=r['source_target_status'], box_source='assistant_visual_proposal_pending_human_review',
            all_visible_object_annotation_complete=False, human_approved=False,
            eligible_for_training=False, approved_for_evaluation=False, role='exploratory_lecture_review',
            note='Prüfen Sie die Zielklasse und sämtliche Schild-, Gesichts- und Kennzeichenboxen vor einer Freigabe.')
        write(collection / Path(image).parent / 'box-proposals.json', proposal)
        common = dict(candidate_id=cid,picture_id=r['picture_id'],sequence_id=r['sequence_id'],
                      municipality=r['municipality'],registry_sign_code=r['registry_class'],
                      visible_class_proposal=r['visible_class_proposal'],proposed_model_label=label,
                      source_target_status=r['source_target_status'],
                      source_target_original_codes=';'.join(r.get('source_target_original_codes',[])),
                      baseline_target_issue=r.get('sgblur_yolo11n_target_issue','detected_sign' if r.get('sgblur_yolo11n_target_detected') is True else 'missed_sign' if r.get('sgblur_yolo11n_target_detected') is False else 'not_replayed'),
                      site_candidate_id=r['site_candidate_id'],conservative_split_group_id=r['conservative_split_group_id'])
        crop_rows.append(dict(**common,crop_path=crop,full_image_path=image,reviewed_class='',reviewer='',review_note='',approved='NEIN',crop_sha256=r['crop_sha256']))
        frame_rows.append(dict(**common,image_path=image,bbox_xyxy=json.dumps(r['target_bbox_xyxy_proposal']),
                               all_sign_plate_face_boxes_reviewed='NEIN',reviewer='',review_note='',image_sha256=r['hd_sha256']))
        origins.append(dict(**common,source_item_url=r['source_item_url'],viewer_url=r['viewer_url'],
                            hd_url=r['hd_url'],author=r['author'],license=r['license'],
                            license_url='https://creativecommons.org/licenses/by-sa/4.0/',
                            local_changes='Original-JPEG unverändert; Zielcrop und Box-/Klassenvorschlag; Überlagerungsdetails gemäß Bildlegende',
                            source_image_sha256=r['hd_sha256'],source_metadata_sha256=r['source_item_sha256']))
    for name, rows in [('SICHTUNG_CROPS.csv',crop_rows),('SICHTUNG_VOLLBILDER.csv',frame_rows),('HERKUNFT.csv',origins)]:
        with (collection / name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    classes=json.loads((LECTURE / 'praktikum/class-index.json').read_text())['classes']
    for label in classes:
        (collection / 'approved/classifier' / label.replace(':','__')).mkdir(parents=True)
    (collection / 'approved/detector').mkdir(parents=True)
    shutil.copyfile(LECTURE / 'praktikum/class-index.json',collection / 'class-index.json')
    for file in ['sgblur-baseline-replay.json','novelty-audit.json']:
        shutil.copyfile(evidence / file,collection / file)
    shutil.copyfile(evidence / 'BITTE_ZUERST_LESEN.txt',collection / 'BITTE_ZUERST_LESEN.txt')
    for file in manifest.get('supporting_files',[]):
        dst=collection / file;dst.parent.mkdir(parents=True,exist_ok=True)
        asset(safe_source(source_root,file),dst)
    write(collection / 'manifest.json',manifest)
    write(collection / 'EINGANGSORDNER.json',dict(schema_version=1,role='exploratory_lecture_review',
          normative_manifest='manifest.json',normal_course_importer_compatible=False,human_approved=False,
          eligible_for_training=False,approved_for_evaluation=False,
          note='Teilannotation als Sichtungseingang; kein Trainings-/Testexport und kein Blindtest.'))
    report=dict(schema_version='youspeed-mobidata-review-delivery-v1',role='exploratory_lecture_review',
        full_images=len(records),crops=len(records),sequences=len({r['sequence_id'] for r in records}),
        visible_class_proposals=dict(Counter(r['visible_class_proposal'] for r in records)),
        registry_face_disagreements=sum(r['registry_face_disagrees_with_visible_face'] for r in records),
        no_stored_target_box=sum(r['source_target_status']=='no_stored_target_box' for r in records),
        source_target_without_class=sum(r['source_target_status']=='detected_but_unclassified_yes' for r in records),
        source_target_wrong_code_proposals=sum(r['source_target_status']=='detected_but_wrong_code_proposal' for r in records),
        sgblur_yolo11n_target_matches=sum(r.get('sgblur_yolo11n_target_detected') is True for r in records),
        sgblur_yolo11n_target_misses=sum(r.get('sgblur_yolo11n_target_detected') is False for r in records),
        sgblur_yolo11n_not_replayed=sum(r.get('sgblur_yolo11n_target_detected') is None for r in records),
        all_visible_object_annotation_complete=False,human_approved=False,eligible_for_training=False,
        approved_for_evaluation=False,normal_course_importer_compatible=False,source_annotations_changed=False,
        collection_manifest_sha256=sha(collection / 'manifest.json'),
        limitations=['Ausgewählte Suchtreffer, keine populationsbezogene Detektor-Recall-Messung.',
                     'Novität gegen bisherige Lehrsammlung und dokumentierte Suchläufe; kein Audit sämtlicher Vortrainingsdaten.',
                     'Nach Bildauswahl exploratives Lehr-/Reviewmaterial; nicht als Blindtest verwenden.',
                     'Standort-/Fahrtgruppen müssen vor einem späteren Split menschlich geprüft werden.'])
    write(collection / 'bericht.json',report)
    # A self-contained index keeps the originals and proposals easy to inspect offline.
    cards=[]
    for r in records:
        escape=lambda value:html.escape(str(value),quote=True)
        issue=r.get('sgblur_yolo11n_target_issue','detected_sign' if r.get('sgblur_yolo11n_target_detected') is True else 'missed_sign' if r.get('sgblur_yolo11n_target_detected') is False else 'not_replayed')
        cards.append('<article><a href="'+escape(r['image_path'])+'"><img src="'+escape(r['crop_path'])+'" alt="Ungeprüfter Zielcrop '+escape(r['visible_class_proposal'])+'" loading="lazy"></a><h2>'+escape(r['visible_class_proposal'])+' · '+escape(r['municipality'])+'</h2><p>Quelle: '+escape(r['source_target_status'])+'<br>Lokales SGBlur: '+escape(issue)+'</p><p><a href="'+escape(r['image_path'])+'">Original-Vollbild</a> · <a href="'+escape(r['overlay_path'])+'">Prüfüberlagerung</a></p><p>'+escape(r['author'])+' · '+escape(r['license'])+'</p></article>')
    (collection / 'SICHTUNG.html').write_text('<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Ortstafel-Sichtung MobiData BW</title><style>body{font:16px system-ui;margin:2rem;background:#f6f5f0;color:#182c29}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}article{background:white;padding:1rem;border:1px solid #ccc}img{width:100%;height:190px;object-fit:contain}h2{font-size:1.1rem}a{color:#075a54}p{line-height:1.5}</style><h1>Ortstafel-Sichtung · '+str(len(records))+' Zielansichten</h1><p>Prüfen Sie Klassen und alle Vollbildboxen vor einer Freigabe. Die Originalbilder sind unverändert; die Zielboxen sind Teilannotation. Die Bildauswahl wurde bereits gesichtet und ist kein Blindtest.</p><p><a href="BITTE_ZUERST_LESEN.txt">Sichtungshinweise und Lizenzen</a> · <a href="SICHTUNG_CROPS.csv">Crop-Arbeitsliste</a> · <a href="SICHTUNG_VOLLBILDER.csv">Vollbild-Arbeitsliste</a> · <a href="HERKUNFT.csv">Herkunft</a></p><main>'+''.join(cards)+'</main></html>',encoding='utf-8')
    checksums={p.relative_to(collection).as_posix():sha(p) for p in sorted(collection.rglob('*')) if p.is_file()}
    write(collection / 'SHA256SUMS.json',checksums)
    archive.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(collection.rglob('*')):
            rel=archive_root+'/'+p.relative_to(collection).as_posix()
            if p.is_dir():z.writestr(rel+'/',b'')
            else:z.write(p,rel)
    report.update(archive_file=archive.name,archive_sha256=sha(archive),archive_bytes=archive.stat().st_size)
    write(evidence / 'delivery-report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True,help='Verified original review-pack directory')
    parser.add_argument('--evidence-dir',type=Path,default=EVIDENCE,help='Manifest, replay, novelty audit and review instructions')
    parser.add_argument('--collection',type=Path,default=LECTURE / '.build/mobidata-bw-review-2026-10-20/collection')
    parser.add_argument('--archive',type=Path,default=LECTURE / 'output' / (NAME+'.zip'))
    parser.add_argument('--link-assets',action='store_true',help='Hardlink immutable verified assets when possible')
    parser.add_argument('--archive-root',default=NAME,help='Distinct root directory for a supplemental package')
    args=parser.parse_args()
    print(json.dumps(package(args.source_root,args.collection,args.archive,args.evidence_dir,args.link_assets,args.archive_root),ensure_ascii=False,indent=2))


if __name__=='__main__':main()

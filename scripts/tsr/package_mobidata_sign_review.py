#!/usr/bin/env python3
"""Build the 85-candidate offline gallery; source codes never become approved labels.

Visual thesis: a quiet field-review workspace, neutral paper, clear photo planes.
Content: filters, full scene and crop inspector, source details, candidate queue.
Interaction: keyboard navigation, linked original images, restrained focus changes.
"""
from __future__ import annotations
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile
from datetime import datetime, timezone
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LECTURE = ROOT / 'lectures/tsr-sgblur-de-2026-10-26'
NAME = 'panoramax-mobidata-sign-review-2026-10-23'
WORK = LECTURE / '.build/mobidata-sign-review-2026-10-23'
EVIDENCE = LECTURE / 'source/mobidata-sign-review-2026-10-23'
COLLECTION = LECTURE / 'output' / NAME
ARCHIVE = LECTURE / 'output' / (NAME + '.zip')
NAMES = {'DE:274-90':'Höchstgeschwindigkeit 90 km/h','DE:156-10':'Bahnübergangs-Bake','DE:223.1-50':'Seitenstreifenfreigabe','DE:325.1':'Verkehrsberuhigter Bereich · Beginn','DE:325.2':'Verkehrsberuhigter Bereich · Ende','DE:101-15':'Steinschlag','DE:117-10':'Seitenwind','DE:142-10':'Wildwechsel','DE:278':'Ende einer Geschwindigkeitsbeschränkung','DE:350-10':'Fußgängerüberweg'}
FLAG_NAMES = {'variant_unverified':'Variante offen','value_unverified':'Wert offen','source_value_missing':'Wert fehlt im Kataster','target_not_confirmed':'Zielschild unbestätigt','context_region':'Nur Prüfbereich','panorama':'360°-Aufnahme','source_label_disagrees':'Abweichende Bildablesung','low_resolution':'Geringe Auflösung'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def link(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if sha(source)!=sha(destination):raise ValueError('Immutable source changed: '+str(source))
    else:shutil.copyfile(source,destination)

def csvfile(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def ground_distance(a,b):
    return math.hypot((a[0]-b[0])*111320*math.cos(math.radians((a[1]+b[1])/2)),(a[1]-b[1])*111320)

def build():
    downloaded=json.loads((WORK/'download-manifest.json').read_text())
    selections=json.loads((EVIDENCE/'visual-proposals.json').read_text())['selections']
    detections=json.loads((WORK/'crop-detections.json').read_text())
    images={r['picture_id']:r for r in downloaded['images']}
    detected={r['picture_id']:r['sign_boxes'] for r in detections['images']}
    assert len(downloaded['records'])==85 and len(images)==84 and len(selections)==85
    COLLECTION.mkdir(parents=True,exist_ok=True)
    for name in ['originals','metadata','previews','thumbnails','crops','proposals','evidence','reproduce','approved/classifier','approved/detector']:(COLLECTION/name).mkdir(parents=True,exist_ok=True)
    for image in images.values():
        assert image['status']=='ok' and sha(WORK/image['image_path'])==image['image_sha256']
        link(WORK/image['image_path'],COLLECTION/image['image_path'])
        link(WORK/image['metadata_path'],COLLECTION/image['metadata_path'])
        with Image.open(WORK/image['image_path']) as im:
            for folder,size in [('previews',(1600,1100)),('thumbnails',(340,240))]:
                view=im.convert('RGB');view.thumbnail(size)
                view.save(COLLECTION/folder/(image['picture_id']+'.jpg'),quality=88,optimize=True)
    records=[]
    for source in downloaded['records']:
        identifier=source['review_id'];selection=selections[identifier];image=images[source['picture_id']];w,h=image['dimensions']
        if 'bbox_normalized' in selection:
            box=[v*s for v,s in zip(selection['bbox_normalized'],[w,h,w,h])];box_source='assistant_visual_region_proposal'
        else:
            detection=next(d for d in detected[source['picture_id']] if d['box_id']==selection['detector_box'])
            box=list(detection['bbox_xyxy']);box_source='assistant_selected_detector_proposal'
            box[3]+=(box[3]-box[1])*selection.get('extend_down',0)
        # Keep contextual padding explicit; never enlarge stored crop pixels.
        dx=(box[2]-box[0])*.12;dy=(box[3]-box[1])*.12
        box=[max(0,math.floor(box[0]-dx)),max(0,math.floor(box[1]-dy)),min(w,math.ceil(box[2]+dx)),min(h,math.ceil(box[3]+dy))]
        assert 0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h
        crop_path='crops/'+identifier+'.png'
        with Image.open(WORK/image['image_path']) as im:im.convert('RGB').crop(box).save(COLLECTION/crop_path)
        flags=['variant_unverified']
        if selection['crop_role']!='sign_candidate':flags.append('target_not_confirmed')
        if selection['crop_role']=='context_region':flags.append('context_region')
        if source['fov']==360 or image.get('fov')==360:flags.append('panorama')
        if source['code'] in ['DE:274-90','DE:278']:flags.append('value_unverified')
        if source['code']=='DE:278':flags.append('source_value_missing')
        flags=list(dict.fromkeys(flags+selection.get('extra_flags',[])))
        val=selection.get('visible_value_proposal')
        value_note=('Kataster: 90 km/h; Bildablesung '+str(val)+' km/h, ungeprüft.' if val is not None else 'Kataster: 90 km/h; Bildwert nicht sicher abgelesen.') if source['code']=='DE:274-90' else (('Kein gedruckter Wert im Kataster; Bildablesung '+str(val)+' km/h, ungeprüft.' if val is not None else 'Kein gedruckter Wert im Kataster; Bildablesung offen.') if source['code']=='DE:278' else 'Kein numerischer Zielwert aus dem Suchcode abgeleitet.')
        record=dict(candidate_id=identifier,picture_id=source['picture_id'],sequence_id=source['sequence_id'],registry_sign_code=source['code'],sign_name=NAMES[source['code']],registry_group_id=source['group_id'],registry_location_id=source.get('location_id'),registry_coordinates=source['sign_coordinates'],camera_coordinates=source['camera_coordinates'],camera_distance_m=source['distance_m'],municipality=source['municipality'],image_path=image['image_path'],image_dimensions=image['dimensions'],image_sha256=image['image_sha256'],metadata_path=image['metadata_path'],metadata_sha256=image['metadata_sha256'],preview_path='previews/'+source['picture_id']+'.jpg',thumbnail_path='thumbnails/'+source['picture_id']+'.jpg',crop_path=crop_path,crop_sha256=sha(COLLECTION/crop_path),crop_bbox_xyxy=box,crop_dimensions=[box[2]-box[0],box[3]-box[1]],crop_role=selection['crop_role'],crop_box_source=box_source,visual_note_de=selection.get('visual_note_de','Schild und Variante benötigen Prüfung.'),uncertainty_flags=flags,source_code_role='inventory_search_hint_only',exact_code_verified=False,visible_value_proposal=val,visible_code_proposal=selection.get('visible_code_proposal'),value_note_de=value_note,viewer_url=source['viewer_url'],source_item_url=source['metadata_url'],hd_url=image['hd_url'],author=image['author'],license=image['license'],license_url=image['license_url'],capture_datetime=image['datetime'],human_approved=False,eligible_for_training=False,approved_for_evaluation=False,all_visible_object_annotation_complete=False,local_changes='Original-JPEG unverändert; Vorschaucodierung und nativer PNG-Ausschnitt; lokale Box-/Sichtungsvorschläge, keine Quellannotation geändert.')
        write(COLLECTION/'proposals'/(identifier+'.json'),record)
        records.append(record)
    # A deliberately conservative connected grouping avoids treating repeated views as independent.
    parent=list(range(len(records)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,a in enumerate(records):
        for j,b in enumerate(records[:i]):
            if a['picture_id']==b['picture_id'] or a['sequence_id']==b['sequence_id'] or ground_distance(a['registry_coordinates'],b['registry_coordinates'])<100:parent[find(i)]=find(j)
    group_members=collections.defaultdict(list)
    for i,r in enumerate(records):group_members[find(i)].append(r['candidate_id'])
    for i,r in enumerate(records):r['conservative_split_group_id']='review:'+min(group_members[find(i)])
    prior_pics=set();prior_sequences=set()
    def prior_walk(value):
        if isinstance(value,dict):
            if isinstance(value.get('picture_id'),str):prior_pics.add(value['picture_id'])
            if isinstance(value.get('sequence_id'),str):prior_sequences.add(value['sequence_id'])
            for child in value.values():prior_walk(child)
        elif isinstance(value,list):
            for child in value:prior_walk(child)
    for manifest in (LECTURE/'source').glob('*/manifest.json'):
        if manifest.parent==EVIDENCE:continue
        prior_walk(json.loads(manifest.read_text()))
    for r in records:
        r['prior_manifest_picture_overlap']=r['picture_id'] in prior_pics
        r['prior_manifest_sequence_overlap']=r['sequence_id'] in prior_sequences
        write(COLLECTION/'proposals'/(r['candidate_id']+'.json'),r)
    roles=dict(collections.Counter(r['crop_role'] for r in records))
    report=dict(format='youspeed-mobidata-sign-review-delivery-v1',created_at=datetime.now(timezone.utc).isoformat(),role='student_multiclass_review_supplement',candidate_views=len(records),unique_full_images=len(images),review_crop_files=len(records),crop_roles=roles,unique_sequences=len({r['sequence_id'] for r in records}),conservative_groups=len(group_members),registry_code_counts=dict(collections.Counter(r['registry_sign_code'] for r in records)),unconfirmed_target_views=sum('target_not_confirmed' in r['uncertainty_flags'] for r in records),prior_manifest_picture_overlaps=sorted({r['picture_id'] for r in records if r['prior_manifest_picture_overlap']}),prior_manifest_sequence_overlaps=sorted({r['sequence_id'] for r in records if r['prior_manifest_sequence_overlap']}),licenses=dict(collections.Counter(r['license'] for r in images.values())),human_approved=False,eligible_for_training=False,approved_for_evaluation=False,normal_course_importer_compatible=False,source_annotations_changed=False,training_performed=False,classifier_run=False,crop_localization_detector_used=True,limitations=['85 view-to-inventory associations contain only 84 unique photos. R19 and S22 reference the same original image.','A review crop may be an uncertain context region or another visible sign; crop_role distinguishes these from proposed target signs.','All variants and readings are unapproved proposals. Proximity does not establish physical identity or exact source code.','The eight DE:223.1-50 candidates do not confirm hard-shoulder use.','DE:278 supplies no printed speed in MobiData.','No candidate exists for DE:460-20 within the searched 100m radius.','Images and crops are not a blinded test or a course-import-ready training export.','Conservative groups and prior-manifest overlap hints do not replace physical sign/journey checks across every package.','Detector outputs only locate possible signs; no classifier was run and no model quality metrics are claimed.'])
    manifest=dict(format='youspeed-mobidata-sign-review-v1',package_id=NAME,**{k:v for k,v in report.items() if k!='format'},records=records)
    write(COLLECTION/'manifest.json',manifest);write(EVIDENCE/'manifest.json',manifest)
    write(COLLECTION/'bericht.json',report);write(EVIDENCE/'delivery-report.json',report)
    common=lambda r:dict(candidate_id=r['candidate_id'],picture_id=r['picture_id'],sequence_id=r['sequence_id'],registry_sign_code=r['registry_sign_code'],municipality=r['municipality'],crop_role=r['crop_role'],uncertainty_flags=';'.join(r['uncertainty_flags']),conservative_split_group_id=r['conservative_split_group_id'])
    crop_rows=[dict(**common(r),crop_path=r['crop_path'],full_image_path=r['image_path'],bbox_xyxy=json.dumps(r['crop_bbox_xyxy']),visible_value_proposal=r['visible_value_proposal'],visual_note=r['visual_note_de'],reviewed_class='',reviewed_value='',reviewer='',review_note='',approved='NEIN',crop_sha256=r['crop_sha256']) for r in records]
    frame_rows=[dict(**common(r),image_path=r['image_path'],source_item_url=r['source_item_url'],viewer_url=r['viewer_url'],all_sign_plate_face_boxes_reviewed='NEIN',image_sha256=r['image_sha256']) for r in records]
    origins=[dict(**common(r),image_path=r['image_path'],crop_path=r['crop_path'],author=r['author'],license=r['license'],license_url=r['license_url'],capture_datetime=r['capture_datetime'],viewer_url=r['viewer_url'],source_item_url=r['source_item_url'],hd_url=r['hd_url'],source_image_sha256=r['image_sha256'],source_metadata_sha256=r['metadata_sha256'],local_changes=r['local_changes']) for r in records]
    for name,rows in [('SICHTUNG_CROPS.csv',crop_rows),('SICHTUNG_VOLLBILDER.csv',frame_rows),('HERKUNFT.csv',origins)]:csvfile(COLLECTION/name,rows)
    notes=f'''# MobiData BW · 85 Schildkandidaten

**23. Oktober 2026 · ungeprüftes Sichtungsmaterial für Studierende**

Öffnen Sie nach dem Entpacken **[SICHTUNG.html](SICHTUNG.html)** für Filter, Vollbilder, Ausschnitte, Panoramax-Links und lokal speicherbare Sichtungsnotizen. Die unten stehende Galerie funktioniert auch direkt in Hugging Face. [Arbeitsliste](SICHTUNG_CROPS.csv) · [Herkunft](HERKUNFT.csv) · [Manifest](manifest.json).

Diese Sammlung enthält **85 Zuordnungen, 84 unveränderte Original-JPEGs und 85 native Prüfausschnitte**. Davon sind **{roles.get('sign_candidate',0)} vorgeschlagene Ziel-Schildcrops, {roles.get('other_sign',0)} Crops anderer sichtbarer Schilder und {roles.get('context_region',0)} Kontext-Prüfbereiche ohne bestätigtes Zielschild**. Kein Kontextbereich darf als bestätigtes Schild oder objektfreies Negativbeispiel importiert werden.

Der MobiData-Code ist ein **Suchhinweis**, kein bestätigtes Bildlabel. Prüfen Sie genaue Variante, Richtung, rote Diagonalstriche und Zahlen am Original. Die für `DE:274-90` gefundenen Ansichten S02/S04 zeigen einen **70-Ablesevorschlag**. Die acht `DE:223.1-50`-Ansichten bestätigen **keine Seitenstreifenfreigabe**. Für `DE:278` enthält der Kataster keinen gedruckten Wert. Für `DE:460-20` lag kein Bildkandidat im geprüften 100-m-Radius vor.

R19 und S22 verwenden **dasselbe Foto**, aber unterschiedliche Katasterzuordnungen. Mehrere weitere Ansichten zeigen denselben Standort oder stammen aus derselben Fahrt. Die {len(group_members)} konservativen Gruppen sind Vorschläge; gleichen Sie Tafeln und Fahrten vor jeder Aufteilung auch mit den anderen Paketen ab. Alle Freigaben bleiben ausstehend. Kein Training und keine Klassifikation wurden durchgeführt; ein unveränderter SGBlur-Detektor wurde nur zur Lokalisierung möglicher Crop-Boxen verwendet. Die Auswahl ist bereits gesichtetes Lern-/Reviewmaterial und kein Blindtest.

Die Original-JPEGs bleiben bytegleich. Vorschauen sind verkleinert; PNG-Crops enthalten native Pixel ohne Hochrechnung. 360°-Aufnahmen bleiben unverändert und sind gekennzeichnet; die Galerie erzeugt keine Perspektivprojektion. Boxen sind Teilannotation. Prüfen und ergänzen Sie sämtliche relevanten Schilder-, Gesichts- und Kennzeichenboxen vor einem Detektorexport.

## Herkunft und Rechte

MobiData BW / Verkehrsministerium Baden-Württemberg: [Katasterquelle](https://mobidata-bw.de/dataset/verkehrszeichen-baden-wurttemberg), [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0). Suchbasis: Repository-Snapshot vom 21.10.2026; Panoramax-Geoindex vom 11.10.2026 und getrennte Live-Prüfungen für die seltenen Codes.

**81 Originalfotos stehen unter CC BY-SA 4.0, drei unter Etalab Licence Ouverte 2.0.** Autor, Lizenz und Ursprungslink bleiben bei jedem Foto erhalten. Erhalten Sie diese Zuordnung auch für Crops und Vorschauen. Der jeweilige Lizenzlink ist maßgeblich. Öffentliche Bilder können bereits quellenanonymisiert sein. Projektcode bleibt AGPLv3; [Lizenztext](LICENSE-CODE-AGPL-3.0.txt).

## Galerie

'''
    for r in records:
        flags=' · '.join(FLAG_NAMES.get(f,f) for f in r['uncertainty_flags'])
        notes+=f"### {r['candidate_id']} · {r['registry_sign_code']} · {r['municipality']}\n\n**{flags}**\n\n| Vollbild | {('Kontext-Prüfbereich' if r['crop_role']=='context_region' else 'Schildcrop – ungeprüft')} |\n| --- | --- |\n| [![Vollbild {r['candidate_id']}]({r['preview_path']})]({r['image_path']}) | [![Ausschnitt {r['candidate_id']}]({r['crop_path']})]({r['crop_path']}) |\n\n{r['visual_note_de']} {r['value_note_de']}\n\n[Panoramax]({r['viewer_url']}) · [Original {r['image_dimensions'][0]} × {r['image_dimensions'][1]} px]({r['image_path']}) · [Quellmetadaten]({r['metadata_path']}) · © {r['author']} · [{r['license']}]({r['license_url']}) · {r['capture_datetime'][:10]}\n\n"
    (COLLECTION/'README.md').write_text(notes)
    (COLLECTION/'BITTE_ZUERST_LESEN.txt').write_text(notes.split('## Galerie')[0].replace('**',''))
    link(ROOT/'LICENSE',COLLECTION/'LICENSE-CODE-AGPL-3.0.txt')
    assets=Path(__file__).parent/'review-gallery'
    for filename in ['gallery.css','gallery.js']:shutil.copyfile(assets/filename,COLLECTION/filename)
    embedded=json.dumps(records,ensure_ascii=False).replace('<','\\u003c')
    (COLLECTION/'SICHTUNG.html').write_text((assets/'SICHTUNG.template.html').read_text().replace('__GALLERY_DATA__',embedded))
    for filename in ['visual-proposals.json']:shutil.copyfile(EVIDENCE/filename,COLLECTION/'evidence'/filename)
    shutil.copyfile(WORK/'crop-detections.json',COLLECTION/'evidence/crop-detections.json')
    shutil.copyfile(ROOT/'output/research/mobidata-panoramax-sign-coverage-2026-10-23/coverage.csv',COLLECTION/'evidence/coverage.csv')
    shutil.copyfile(Path(__file__),COLLECTION/'reproduce'/Path(__file__).name)
    for filename in ['SICHTUNG.template.html','gallery.css','gallery.js']:shutil.copyfile(assets/filename,COLLECTION/'reproduce'/filename)
    checks={p.relative_to(COLLECTION).as_posix():sha(p) for p in sorted(COLLECTION.rglob('*')) if p.is_file() and p.name!='SHA256SUMS.json'}
    write(COLLECTION/'SHA256SUMS.json',checks)
    return report

def archive():
    with zipfile.ZipFile(ARCHIVE,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(COLLECTION.rglob('*')):
            if p.is_file():z.write(p,NAME+'/'+p.relative_to(COLLECTION).as_posix())
    report=json.loads((EVIDENCE/'delivery-report.json').read_text())
    report.update(archive_file=ARCHIVE.name,archive_bytes=ARCHIVE.stat().st_size,archive_sha256=sha(ARCHIVE))
    write(EVIDENCE/'delivery-report.json',report)
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',action='store_true');args=parser.parse_args()
    print(json.dumps(archive() if args.archive else build(),ensure_ascii=False,indent=2))

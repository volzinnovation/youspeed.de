#!/usr/bin/env python3
"""Package visually selected Mapillary/MobiData review inputs without approval.

Input local_image paths are private build inputs and never enter the archive.
Only unchanged downloaded perspective JPEGs and exact native PNG crops are used.
This program does not fetch, train, evaluate, approve labels, or assign splits.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw, ImageFont


NAME = 'mapillary-mobidata-bw-review-2026-10-21'
LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/4.0/'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def table(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def page(title, content, prefix=''):
    return ('<!doctype html><html lang="de"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width"><title>'+html.escape(title)+'</title>'
            '<style>body{font:16px system-ui;line-height:1.5;margin:2rem auto;max-width:1300px;'
            'padding:0 1rem;background:#f5f4ef;color:#182c29}a{color:#075a54}'
            '.brand{width:180px;height:60px;object-fit:contain}main{display:grid;'
            'grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}'
            'article{padding:1rem;background:white;border:1px solid #c9cfcb}'
            '.crop{width:100%;height:210px;object-fit:contain;image-rendering:auto}'
            '.full{max-width:100%;height:auto}h2{font-size:1.15rem}</style>'
            '<header><a href="https://www.mapillary.com/"><img class="brand" src="'+prefix+
            'assets/mapillary-logo.png" alt="Mapillary"></a></header>'+content+'</html>')


def prepare(source, logo, prior_inventory, output, archive, evidence):
    manifest = json.loads(source.read_text())
    records = manifest['records']
    if not records or len({r['image_id'] for r in records}) != len(records):
        raise ValueError('Expected unique nonempty image records')
    previous = json.loads(prior_inventory.read_text())
    old_hashes = set(previous['hashes'])
    verified = []
    for r in records:
        if not r['image_id'].isdigit() or not r['author'] or r['license'] != 'CC-BY-SA-4.0':
            raise ValueError('Missing image identity, creator or licence')
        if r['projection'] != 'perspective':
            raise ValueError('This package only accepts native perspective images')
        if any(r[k] for k in ['human_approved', 'eligible_for_training', 'approved_for_evaluation',
                              'all_visible_object_annotation_complete', 'physical_independence_approved']):
            raise ValueError('Expected unapproved partial annotation')
        if r['visible_class_proposal'] not in {'DE:310', 'DE:311'}:
            raise ValueError('Unexpected class proposal')
        path = Path(r['local_image'])
        digest = sha(path)
        if digest in old_hashes:
            raise ValueError('Exact downloaded-image overlap with previous inventory')
        with Image.open(path) as im:
            im.load()
            x0, y0, x1, y1 = r['bbox_xyxy']
            if not all(isinstance(v, int) for v in r['bbox_xyxy']) or not (0 <= x0 < x1 <= im.width and 0 <= y0 < y1 <= im.height):
                raise ValueError('Invalid pixel-edge box')
            if im.getexif().get(274, 1) != 1:
                raise ValueError('EXIF rotation must be handled explicitly')
            rgb_hash = hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
            if rgb_hash in old_hashes:
                raise ValueError('Exact decoded-pixel overlap with previous inventory')
            verified.append((digest, rgb_hash, list(im.size)))
    output.mkdir(parents=True, exist_ok=False)
    (output/'assets').mkdir()
    shutil.copyfile(logo, output/'assets/mapillary-logo.png')
    crops, frames, origins, cards = [], [], [], []
    groups = defaultdict(list)
    font = None
    for font_name in ['DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf']:
        try:
            font = ImageFont.truetype(font_name, 18)
            break
        except OSError:
            pass
    if font is None:
        font = ImageFont.load_default()
    for r, (digest, rgb_hash, dimensions) in zip(records, verified):
        key = r['image_id']
        cid = 'mapillary-'+key
        original = Path(r.pop('local_image'))
        r.update(candidate_id=cid, image_path='inbox/detector/'+cid+'/image.jpg',
                 crop_path='inbox/classifier/'+cid+'.png', metadata_path='metadata/'+key+'.json',
                 overlay_path='overlays/'+key+'.jpg', full_image_page='ansichten/'+key+'.html',
                 source_image_sha256=digest, source_rgb_sha256=rgb_hash,
                 image_dimensions=dimensions, proposed_model_label={'DE:310':'city:start','DE:311':'city:end'}[r['visible_class_proposal']],
                 modification_notice='Downloaded JPEG bytes unchanged; exact rectangular PNG crop and a separate annotated preview. No upscaling, synthetic pixels or blur removal.',
                 conservative_split_group_id='mapillary-journey:'+r['author']+':'+r['captured_date_displayed'])
        groups[r['conservative_split_group_id']].append(key)
        for name in [r['image_path'], r['crop_path'], r['metadata_path'], r['overlay_path'], r['full_image_page']]:
            (output/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, output/r['image_path'])
        im = Image.open(output/r['image_path']).convert('RGB')
        crop = im.crop(r['bbox_xyxy'])
        crop.save(output/r['crop_path'])
        r.update(crop_dimensions=list(crop.size), crop_sha256=sha(output/r['crop_path']))
        if r['crop_sha256'] in old_hashes:
            raise ValueError('Exact crop overlap with previous inventory')
        view = im.copy()
        view.thumbnail((1000, 750))
        canvas = Image.new('RGB', (max(1000, view.width), view.height+68), 'white')
        canvas.paste(view, (0, 0))
        d = ImageDraw.Draw(canvas)
        x0, y0, x1, y1 = r['bbox_xyxy']
        d.rectangle((x0*view.width/im.width, y0*view.height/im.height,
                     x1*view.width/im.width, y1*view.height/im.height), outline='#ff315b', width=3)
        d.text((7, view.height+5), r['visible_class_proposal']+' | unapproved target box; other objects incomplete', font=font, fill='black')
        d.text((7, view.height+32), r['author']+' / Mapillary / CC BY-SA 4.0 / '+key, font=font, fill='black')
        canvas.save(output/r['overlay_path'], quality=87)
        write(output/r['metadata_path'], r)
        write(output/Path(r['image_path']).parent/'box-proposals.json', {
            'candidate_id':cid, 'bbox_xyxy':r['bbox_xyxy'], 'coordinate_system':r['bbox_coordinate_system'],
            'detector_class_proposal':{'id':0, 'name':'sign'}, 'class_proposal':r['visible_class_proposal'],
            'source_url':r['source_url'], 'human_approved':False, 'eligible_for_training':False,
            'approved_for_evaluation':False, 'all_visible_object_annotation_complete':False})
        common = dict(candidate_id=cid, image_id=key, sequence_id=r['sequence_id'],
            visible_class_proposal=r['visible_class_proposal'], registry_sign_code=r['registry_record']['sign_code'],
            municipality=r['registry_record']['municipality_name'], conservative_split_group_id=r['conservative_split_group_id'])
        crops.append(dict(**common, crop_path=r['crop_path'], full_image_path=r['image_path'],
                          reviewed_class='', reviewer='', review_note='', approved='NEIN', crop_sha256=r['crop_sha256']))
        frames.append(dict(**common, image_path=r['image_path'], bbox_xyxy=json.dumps(r['bbox_xyxy']),
                           all_sign_plate_face_boxes_reviewed='NEIN', reviewer='', review_note='', source_image_sha256=digest))
        origins.append(dict(**common, author=r['author'], source_url=r['source_url'], license=r['license'],
                            license_url=LICENSE_URL, captured_date=r['captured_date_displayed'],
                            modification_notice=r['modification_notice'], source_image_sha256=digest))
        e = lambda x: html.escape(str(x), quote=True)
        credit = ('<p>Bild <a href="'+e(r['source_url'])+'">'+key+'</a> von '+e(r['author'])+
                  ' auf <a href="https://www.mapillary.com/">Mapillary</a>, '+
                  '<a href="'+LICENSE_URL+'">CC BY-SA 4.0</a>. Aufgenommen: '+r['captured_date_displayed']+'.</p>')
        body = ('<h1>'+e(r['visible_class_proposal'])+' · '+e(r['registry_record']['municipality_name'])+'</h1>'+credit+
                '<p>Prüfen Sie die Klasse und alle relevanten Vollbildboxen. Das JPEG bleibt unverändert; '
                'der Crop und die magentafarbene Vorschau sind abgeleitet. Der Download ist eine auf 2048 Pixel Breite '
                'skalierte vollständige Mapillary-Ansicht, nicht die ursprüngliche Aufnahmeauflösung.</p>'+
                '<p><a href="../SICHTUNG.html">Zur Sichtung</a> · <a href="../'+e(r['image_path'])+'">JPEG herunterladen</a> · '+
                '<a href="../'+e(r['overlay_path'])+'">Boxvorschlag ansehen</a></p><img class="full" src="../'+e(r['image_path'])+'" alt="Vollbild mit Ortstafel">')
        (output/r['full_image_page']).write_text(page(key, body, '../'), encoding='utf-8')
        cards.append('<article><h2>'+e(r['visible_class_proposal'])+' · '+e(r['registry_record']['municipality_name'])+'</h2>'+
                     '<a href="'+e(r['full_image_page'])+'"><img class="crop" src="'+e(r['crop_path'])+'" alt="Ungeprüfter Ortstafel-Crop"></a>'+credit+
                     '<p><a href="'+e(r['full_image_page'])+'">Vollbild mit Herkunft</a> · <a href="'+e(r['overlay_path'])+'">Boxvorschlag</a></p>'+
                     '<p>Kataster: '+e(r['registry_record']['sign_code'])+'; sichtbarer Vorschlag: '+e(r['visible_class_proposal'])+'.</p></article>')
    for name, rows in [('SICHTUNG_CROPS.csv', crops), ('SICHTUNG_VOLLBILDER.csv', frames), ('HERKUNFT.csv', origins)]:
        table(output/name, rows)
    summary = dict(schema_version='youspeed-mapillary-mobidata-review-report-v1',
        full_images=len(records), crops=len(records), sequences=len({r['sequence_id'] for r in records}),
        municipalities=len({r['registry_record']['municipality_name'] for r in records}),
        visible_class_proposals=dict(Counter(r['visible_class_proposal'] for r in records)),
        conservative_split_groups=len(groups), all_examples_unapproved=True,
        normal_course_importer_compatible=False, training_performed=False, sgblur_replay_performed=False,
        api_queries_executed=manifest['api_queries_executed'],
        selected_from_public_ui_references=True, exhaustive_mapillary_coverage_measured=False,
        downloaded_image_representation='Complete perspective image resized by Mapillary to width 2048; JPEG unchanged locally.',
        exact_image_rgb_crop_overlap_with_prior_inventory=0,
        pretraining_overlap_audited=False, physical_independence_approved=False)
    manifest.update(records=records, registry_license={'id':'dl-de/by-2-0', 'url':'https://www.govdata.de/dl-de/by-2-0',
        'attribution':'Verkehrsministerium Baden-Württemberg / MobiData BW'},
        osm_license={'id':'ODbL-1.0', 'url':'https://www.openstreetmap.org/copyright', 'attribution':'© OpenStreetMap contributors'},
        logo_provenance={'source_url':'https://github.com/mapillary/mapillary_press/releases/download/v0.0.4/logos.zip',
            'member':'logos/mapillary/mapillary_logo_dark@2x.png', 'sha256':sha(logo),
            'notice':'Unmodified official attribution artwork. Mapillary trademark; not relicensed as CC BY-SA imagery.'},
        physical_independence_approved=False, human_approved=False, eligible_for_training=False, approved_for_evaluation=False)
    manifest.pop('metadata_source_note', None)
    write(output/'manifest.json', manifest)
    write(output/'bericht.json', summary)
    write(output/'EINGANGSORDNER.json', {'role':'learning_review_pending_human_approval',
        'normal_course_importer_compatible':False, 'human_approved':False, 'eligible_for_training':False})
    novelty = {'exact_image_rgb_crop_overlap_with_prior_inventory':0,
        'prior_inventory_sha256':sha(prior_inventory), 'conservative_split_groups':dict(groups),
        'physical_independence_approved':False, 'pretraining_overlap_audited':False,
        'rule':'Group by same creator and capture day. Reconcile locations and journeys across all course archives before splitting.'}
    write(output/'novelty-audit.json', novelty)
    instructions = ('MobiData-BW / Mapillary: Sichtungseingang\n\n'
        'Öffnen Sie SICHTUNG.html. Alle Klassen und Boxen sind Vorschläge. Prüfen Sie insbesondere die sichtbare Schildseite; '
        'die Katasterklasse ist keine Bildklassifikation. Die Vollbilder sind vollständige Mapillary-Downloads mit 2048 Pixel Breite; '
        'sie wurden lokal nicht verändert. Crops enthalten exakt die angegebenen Pixel, ohne Vergrößerung oder Entzerrung.\n\n'
        'Prüfen Sie Klassen und sämtliche Schild-, Gesichts- und Kennzeichenboxen vor einem Kurs-Export. '
        'Erhalten Sie vorhandene Unkenntlichmachungen. Der Standardimport übernimmt diese Teilannotation nicht direkt. '
        'Gruppieren Sie dieselben Tafeln und Fahrten über Mapillary und Panoramax hinweg vor jedem Split. '
        'Diese bereits gesichtete Auswahl ist kein Blindtest. Training und Modellevaluation sind Aufgaben der Studierenden.\n\n'
        'Bildlizenz: CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/. '
        'Für jedes JPEG und jeden abgeleiteten Crop sind Bild-ID, Urheber, Quelllink und Änderungshinweis in HERKUNFT.csv '
        'und manifest.json enthalten. Erhalten Sie diese Zuordnung bei jedem Export. source=Mapillary allein ersetzt sie nicht. '
        'Das unveränderte Mapillary-Logo dient der Quellenangabe und ist eine Marke von Mapillary.\n'
        'Kataster: Verkehrsministerium Baden-Württemberg / MobiData BW, Datenlizenz Deutschland Namensnennung 2.0, '
        'https://www.govdata.de/dl-de/by-2-0. Räumlicher Abgleich und Datenauswahl durch das Kursprojekt. '
        'OSM-Suchhinweise: © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright.\n')
    (output/'BITTE_ZUERST_LESEN.txt').write_text(instructions, encoding='utf-8')
    (output/'SICHTUNG.html').write_text(page('MobiData BW / Mapillary: Ortstafel-Sichtung',
        '<h1>'+str(len(records))+' Mapillary-Ansichten für die Ortstafel-Sichtung</h1>'+
        '<p>Prüfen Sie Klassen, Boxen und Herkunft. Diese Teilannotation ist kein fertiger Trainings- oder Testexport.</p>'+
        '<p><a href="BITTE_ZUERST_LESEN.txt">Hinweise und Lizenzen</a> · <a href="SICHTUNG_CROPS.csv">Crop-Arbeitsliste</a> · '+
        '<a href="SICHTUNG_VOLLBILDER.csv">Vollbild-Arbeitsliste</a> · <a href="HERKUNFT.csv">Herkunft</a></p><main>'+''.join(cards)+'</main>'), encoding='utf-8')
    (output/'reproduce').mkdir()
    shutil.copyfile(__file__, output/'reproduce/prepare_review.py')
    hashes = {p.relative_to(output).as_posix():sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    write(output/'SHA256SUMS.json', hashes)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise ValueError('Refusing to overwrite an existing archive')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(output.rglob('*')):
            if p.is_file():
                z.write(p, NAME+'/'+p.relative_to(output).as_posix())
    summary.update(archive_file=archive.name, archive_bytes=archive.stat().st_size, archive_sha256=sha(archive))
    evidence.mkdir(exist_ok=True, parents=True)
    for name, data in [('manifest.json', manifest), ('delivery-report.json', summary), ('novelty-audit.json', novelty)]:
        write(evidence/name, data)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['source', 'logo', 'prior-inventory', 'output', 'archive', 'evidence']:
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    prepare(a.source, a.logo, a.prior_inventory, a.output, a.archive, a.evidence)

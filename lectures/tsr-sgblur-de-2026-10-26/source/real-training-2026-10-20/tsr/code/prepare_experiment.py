#!/usr/bin/env python3
"""Freeze old replay data and assistant-reviewed city train/val before training."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import zipfile
from PIL import Image, ImageOps

SEED = '20261026'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
ARCHIVES = {'train.zip': '0a7cc5895afd76a4dc98e70efc9421ae82a6f580e6d60da3904911155e424853',
            'val.zip': '13ca882129a4e024fc865fc4a3187514a4554f8e323f612e338144fd1ff189ea'}


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def check(value, reason):
    if not value:
        raise ValueError(reason)


def rgb_hash(raw):
    with Image.open(io.BytesIO(raw)) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        return hashlib.sha256(str(image.size).encode()+b'\0'+image.tobytes()).hexdigest()


class Union:
    def __init__(self): self.parent = {}
    def find(self, key):
        self.parent.setdefault(key, key)
        if self.parent[key] != key: self.parent[key] = self.find(self.parent[key])
        return self.parent[key]
    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b: self.parent[max(a, b)] = min(a, b)


def grouped_stratification(groups, classes):
    """Predeclared deterministic coverage-first group split, never tuned on predictions."""
    available = {label: [g for g, rows in groups.items() if any(r['label']==label for r in rows)] for label in classes}
    order = sorted(classes, key=lambda label: (len(available[label]), label))
    assignment = {}
    counts = {s: Counter() for s in ['train','val','test']}
    def assign(g, split):
        assignment[g] = split
        counts[split].update(r['label'] for r in groups[g])
    for label in order:
        for split in ['train', 'val', 'test']:
            if counts[split][label]: continue
            candidates = [g for g in available[label] if g not in assignment]
            if not candidates: continue
            chosen = min(candidates, key=lambda g: hashlib.sha256(f'{SEED}\0coverage\0{label}\0{split}\0{g}'.encode()).hexdigest())
            assign(chosen, split)
    for g in sorted(groups):
        if g in assignment: continue
        n = int.from_bytes(hashlib.sha256(f'{SEED}\0{g}'.encode()).digest()[:8], 'big') / 2**64
        assign(g, 'train' if n < .70 else 'val' if n < .85 else 'test')
    check(all(counts['train'][label] for label in classes), 'Alte Trainingsklassen fehlen')
    return assignment, counts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--classes', type=Path, required=True)
    p.add_argument('--city-review', type=Path, required=True)
    p.add_argument('--reserved-test', type=Path, required=True)
    p.add_argument('--old-exclusions', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    check(not a.output.exists(), 'Ausgabe existiert; eingefrorenen Bestand nicht überschreiben')
    classes = json.loads(a.classes.read_text())['classes']
    check(len(classes)==136 and classes[-2:]==['city:start','city:end'], 'Falsche Klassen')
    city_document = json.loads(a.city_review.read_text())
    city = city_document['rows']
    reserved_document = json.loads(a.reserved_test.read_text())
    check(reserved_document['frozen_before_candidate_predictions'] is True, 'Reservierter Test nicht vorhersageblind eingefroren')
    reserved = reserved_document['rows']
    excluded = set()
    if a.old_exclusions:
        excluded = set(json.loads(a.old_exclusions.read_text())['excluded_sha256'])
    reserved_hashes, reserved_pixels, reserved_ids, reserved_groups = set(), set(), set(), set()
    for row in reserved:
        path = Path(row['crop_absolute_path'])
        check(sha(path)==row['crop_sha256'], 'Reservierter Crop verändert')
        check(sha(row['input_image_absolute_path'])==row['input_sha256'], 'Reserviertes Vollbild verändert')
        reserved_hashes.add(row['crop_sha256']); reserved_pixels.add(rgb_hash(path.read_bytes()))
        reserved_ids.add(row['picture_id']); reserved_groups.add(row['group_id'])
    union = Union()
    records = {}
    pixel_representative = {}
    input_count = 0
    for filename, expected in ARCHIVES.items():
        archive = a.sources / filename
        check(sha(archive)==expected, 'Archivhash falsch: '+filename)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if member.is_dir(): continue
                parts = Path(member.filename).parts
                check(len(parts)==3 and parts[1] in classes[:134], 'Unerwarteter Archivpfad')
                raw = z.read(member)
                h = hashlib.sha256(raw).hexdigest(); input_count += 1
                match = UUID.search(parts[2])
                source = match.group().lower() if match else 'unknown-'+h
                union.find(source)
                if h in records:
                    old = records[h]
                    check(old['label']==parts[1], 'Identisches Bild mit widersprechenden Labels')
                    union.join(old['source_id'], source)
                    old['origins'].append({'archive':filename, 'member':member.filename})
                    continue
                pixel = rgb_hash(raw)
                if pixel in pixel_representative:
                    old = records[pixel_representative[pixel]]
                    check(old['label']==parts[1], 'RGB-Duplikat mit widersprechenden Labels')
                    union.join(old['source_id'], source)
                else: pixel_representative[pixel] = h
                records[h] = {'sample_id':'old-'+h[:24], 'label':parts[1], 'sha256':h,
                              'rgb_sha256':pixel, 'source_id':source,
                              'origins':[{'archive':filename,'member':member.filename}]}
    banned_groups = {union.find(r['source_id']) for h,r in records.items()
                     if h in excluded or h in reserved_hashes or r['rgb_sha256'] in reserved_pixels
                     or r['source_id'] in reserved_ids}
    groups = defaultdict(list)
    dedup_pixels = set()
    for h,r in records.items():
        g = union.find(r['source_id'])
        if g in banned_groups or r['rgb_sha256'] in dedup_pixels: continue
        dedup_pixels.add(r['rgb_sha256'])
        r['group_id'] = 'old-source-image-'+g
        groups[r['group_id']].append(r)
    assignment, old_counts = grouped_stratification(groups, classes[:134])
    rows = []
    for g, members in groups.items():
        for row in members: rows.append(dict(row, split=assignment[g], origin='upstream_old_replay'))
    hashes = {r['sha256'] for r in rows}; pixels = {r['rgb_sha256'] for r in rows}
    city_groups = {}
    for c in city:
        check(c['label'] in classes[-2:] and c['subset'] in ['train','val'], 'Falsche City-Klasse/Rolle')
        check(c['group_id'] not in reserved_groups and c.get('picture_id') not in reserved_ids, 'Testgruppe in City-Training')
        path = Path(c['crop_absolute_path']);h = sha(path);pixel = rgb_hash(path.read_bytes())
        check(h==c['crop_sha256'], 'City-Crop verändert')
        check(h not in reserved_hashes and pixel not in reserved_pixels, 'Testcrop in City-Training')
        check(h not in hashes and pixel not in pixels, 'City-Crop dupliziert alten oder neuen Trainingscrop')
        check(c['group_id'] not in city_groups or city_groups[c['group_id']]==c['subset'], 'Citygruppe überschreitet Split')
        city_groups[c['group_id']] = c['subset'];hashes.add(h);pixels.add(pixel)
        rows.append({'sample_id':c['sample_id'], 'label':c['label'], 'sha256':h,
                     'rgb_sha256':pixel, 'group_id':c['group_id'], 'split':c['subset'],
                     'source_path':str(path), 'origin':'assistant_reviewed_city',
                     'human_reviewed':False})
    for split in ['train','val']:
        check(all(any(r['split']==split and r['label']==label for r in rows) for label in classes[-2:]),
              'Beide City-Klassen benötigen '+split+'-Beispiele')
    a.output.mkdir(parents=True)
    for split in ['train','val','test']:
        for label in classes: (a.output/split/label).mkdir(parents=True)
    opened = {n:zipfile.ZipFile(a.sources/n) for n in ARCHIVES}
    try:
        for row in rows:
            suffix = '.png' if row['origin']=='assistant_reviewed_city' else Path(row['origins'][0]['member']).suffix.lower()
            row['class_index'] = classes.index(row['label'])
            row['dataset_path'] = str(Path(row['split'])/row['label']/(row['sample_id']+suffix))
            target = a.output/row['dataset_path']
            if row['origin']=='assistant_reviewed_city': shutil.copyfile(row['source_path'],target)
            else:
                origin = row['origins'][0];target.write_bytes(opened[origin['archive']].read(origin['member']))
            check(sha(target)==row['sha256'], 'Exporthash falsch')
    finally:
        for z in opened.values(): z.close()
    shutil.copyfile(a.classes, a.output/'class-index.json')
    counts = {s:dict(Counter(r['label'] for r in rows if r['split']==s)) for s in ['train','val','test']}
    manifest = {'schema_version':1, 'dataset_id':'real-city-example-20261020-v1', 'seed':SEED,
                'classes':classes, 'class_index_sha256':sha(a.classes), 'samples':rows,
                'counts':counts, 'source_archive_rows':input_count, 'source_unique_bytes':len(records),
                'removed_old_groups_for_review_or_test_overlap':sorted(banned_groups),
                'city_review_sha256':sha(a.city_review), 'reserved_test_manifest_sha256':sha(a.reserved_test),
                'old_exclusions_sha256':sha(a.old_exclusions) if a.old_exclusions else None,
                'split_method':'predeclared coverage-first stratified source-image/duplicate groups; remaining70/15/15 hash seed20261026; city roles explicit review',
                'baseline_may_have_seen_old_corpus':True, 'old_evaluation_role':'retrospective regression, not independent absolute generalization',
                'physical_sequence_grouping_available_for_old_corpus':False,
                'review_type':'assistant_visual', 'human_reviewed':False,
                'limitations':['Upstream old labels retained, targeted yellow-object review only.','Source-image UUID and exact decoded duplicates grouped; old capture sequences/physical identities unavailable.','Independent reserved assistant-reviewed test manifest bound separately; no human-certified ground truth.']}
    manifest['lock_sha256'] = hashlib.sha256(canonical(manifest)).hexdigest()
    (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(a.output),'manifest_sha256':sha(a.output/'manifest.json'),
                      'split_counts':dict(Counter(r['split'] for r in rows)),
                      'class_coverage':{s:len(counts[s]) for s in counts},
                      'old_missing':{s:[c for c in classes[:134] if not counts[s].get(c)] for s in counts}}),flush=True)


if __name__=='__main__': main()

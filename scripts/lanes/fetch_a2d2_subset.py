#!/usr/bin/env python3
"""Plan then fetch a bounded, date-grouped A2D2 pilot from public S3.

Planning reads listings and small camera/configuration metadata, never image
objects. Fetching preserves original bytes outside the repository. No account,
upload, model training, or click-through license acceptance is implemented.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import heapq
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET


BASE = 'https://audi-autonomous-driving-dataset.s3.eu-central-1.amazonaws.com/'
PREFIX = 'camera_lidar_semantic/'
CAP = 1_000_000_000
NS = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}
METADATA = ['LICENSE', 'README.txt', 'cams_lidars.json', 'tutorial.ipynb',
            PREFIX+'LICENSE', PREFIX+'README-SemSeg.txt', PREFIX+'class_list.json']
DEFAULT_CONFIG = {
    'schemaVersion': 1,
    'split_dates': {'train': ['20180807', '20180810', '20181008'],
                    'validation': ['20181016'], 'test': ['20181108']},
    'counts': {'train': 128, 'validation': 32, 'test': 32},
    'minimum_spacing_seconds': 10.0,
    'maximum_bytes': CAP,
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def safe_key(key):
    path = PurePosixPath(key)
    if not key or path.is_absolute() or any(p in ('..', '.') for p in path.parts) or '\\' in key:
        raise ValueError('Unsafe source object key')
    return key


def curl(url, maximum, etag=None):
    args = ['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https',
            '--max-time', '90', '--max-filesize', str(maximum)]
    if etag:
        if not re.fullmatch(r'"[0-9a-fA-F-]+"', etag):
            raise ValueError('Unexpected S3 ETag format')
        args += ['--header', 'If-Match: '+etag]
    data = subprocess.check_output(args+[url])
    if len(data) > maximum:
        raise ValueError('Response exceeds planned size limit')
    return data


def listing(prefix='', delimiter=None):
    objects, directories, token = [], [], None
    while True:
        params = {'list-type': '2', 'max-keys': '1000', 'prefix': prefix}
        if delimiter:
            params['delimiter'] = delimiter
        if token:
            params['continuation-token'] = token
        root = ET.fromstring(curl(BASE+'?'+urllib.parse.urlencode(params), 4_000_000))
        directories.extend(n.text for n in root.findall('s:CommonPrefixes/s:Prefix', NS))
        for obj in root.findall('s:Contents', NS):
            objects.append(dict(key=safe_key(obj.findtext('s:Key', namespaces=NS)),
                size=int(obj.findtext('s:Size', namespaces=NS)), etag=obj.findtext('s:ETag', namespaces=NS),
                last_modified=obj.findtext('s:LastModified', namespaces=NS)))
        if root.findtext('s:IsTruncated', namespaces=NS) != 'true':
            return objects, directories
        new_token = root.findtext('s:NextContinuationToken', namespaces=NS)
        if not new_token or new_token == token:
            raise ValueError('Invalid S3 pagination')
        token = new_token


def object_bytes(row):
    data = curl(BASE+urllib.parse.quote(safe_key(row['key'])), row['size']+1, row['etag'])
    if len(data) != row['size']:
        raise ValueError('Source length changed: '+row['key'])
    etag = row['etag'].strip('"')
    if re.fullmatch('[0-9a-fA-F]{32}', etag) and hashlib.md5(data).hexdigest() != etag.lower():
        raise ValueError('Source ETag/MD5 mismatch: '+row['key'])
    if row.get('sha256') and digest(data) != row['sha256']:
        raise ValueError('Planned metadata SHA mismatch: '+row['key'])
    return data


def validate_config(config):
    if config.get('schemaVersion') != 1 or set(config['split_dates']) != {'train','validation','test'} or set(config['counts']) != {'train','validation','test'}:
        raise ValueError('Configuration requires train/validation/test date groups and counts')
    dates = []
    for split, groups in config['split_dates'].items():
        if not groups or any(not re.fullmatch(r'20\d{6}', d) for d in groups):
            raise ValueError('Invalid capture date group')
        if type(config['counts'][split]) is not int or not 1 <= config['counts'][split] <= 1000:
            raise ValueError('Invalid split count')
        dates.extend(groups)
    if len(dates) != len(set(dates)):
        raise ValueError('Capture date overlaps splits or is duplicated')
    if type(config['maximum_bytes']) is not int or not 1 <= config['maximum_bytes'] <= CAP:
        raise ValueError('Pilot limit must not exceed 1,000,000,000 bytes')
    spacing = config['minimum_spacing_seconds']
    if isinstance(spacing,bool) or not isinstance(spacing,(int,float)) or not math.isfinite(spacing) or spacing < 1:
        raise ValueError('Require at least one second between sampled exposures')


def dispersed_indices(n):
    """Deterministic endpoint/midpoint coverage before inspecting pixel contents."""
    if n <= 0:
        return
    yield 0
    if n == 1:
        return
    yield n-1
    heap = [(-(n-1), 0, n-1)]
    while heap:
        _, lo, hi = heapq.heappop(heap)
        if hi-lo <= 1:
            continue
        mid = (lo+hi)//2
        yield mid
        heapq.heappush(heap, (-(mid-lo),lo,mid))
        heapq.heappush(heap, (-(hi-mid),mid,hi))


def inventory(sequence):
    camera, _ = listing(f'{PREFIX}{sequence}/camera/cam_front_center/')
    labels, _ = listing(f'{PREFIX}{sequence}/label/cam_front_center/')
    items = {r['key']:r for r in camera+labels}
    candidates, unpaired = [], []
    for row in sorted(camera, key=lambda r:r['key']):
        key = row['key']
        if not key.endswith('.png'):
            continue
        expected = re.fullmatch(r'(\d{14})_camera_frontcenter_(\d+)\.png', PurePosixPath(key).name)
        if expected is None or expected[1] != sequence.replace('_',''):
            raise ValueError('Unexpected front-center frame filename')
        label = key.replace('/camera/','/label/').replace('_camera_','_label_')
        info = key[:-4]+'.json'
        if label not in items or info not in items:
            # Published folders may contain camera frames lacking a semantic
            # partner. Exclude them explicitly before sampling; never invent GT.
            unpaired.append(key)
            continue
        candidates.append(dict(rgb=key,label=label,camera_info=info))
    return sequence, items, candidates, dict(eligible_pairs=len(candidates), excluded_unpaired_rgb=unpaired)


def select_sequence(task):
    split, sequence, count, spacing, items, candidates = task
    chosen, metadata_requests = [], 0
    for index in dispersed_indices(len(candidates)):
        pair = candidates[index]
        info_row = items[pair['camera_info']]
        raw = object_bytes(info_row)
        info = json.loads(raw)
        metadata_requests += 1
        timestamp = info.get('cam_tstamp')
        if info.get('cam_name') != 'front_center' or type(timestamp) is not int or timestamp <= 0:
            raise ValueError('Invalid camera name/timestamp: '+pair['camera_info'])
        if any(abs(timestamp-p['camera_timestamp_us']) < spacing*1_000_000 for p in chosen):
            continue
        info_row['sha256'] = digest(raw)
        chosen.append(dict(**pair, split=split, sequence=sequence, capture_date=sequence[:8],
                           camera_timestamp_us=timestamp, selection_ordinal=index))
        if len(chosen) == count:
            break
        if metadata_requests >= max(count*20,100):
            raise ValueError('Insufficient sufficiently separated frames; increase capture groups or reduce count')
    if len(chosen) != count:
        raise ValueError('Capture cannot satisfy sparse quota: '+sequence)
    return sorted(chosen,key=lambda p:p['camera_timestamp_us'])


def plan(config, output):
    validate_config(config)
    if output.exists():
        raise ValueError('Plan file exists; use a new path')
    _, directories = listing(PREFIX, '/')
    sequences = sorted(p.rstrip('/').split('/')[-1] for p in directories if re.fullmatch(PREFIX+r'20\d{6}_\d{6}/',p))
    split_sequences = {split:[s for s in sequences if s[:8] in dates] for split,dates in config['split_dates'].items()}
    for split, chosen in split_sequences.items():
        if len(chosen) < (2 if split == 'train' else 1) or {s[:8] for s in chosen} != set(config['split_dates'][split]):
            raise ValueError('Configured dates absent or insufficient capture groups: '+split)
        if config['counts'][split] < len(chosen):
            raise ValueError('Sample count must cover every selected capture group')
    all_sequences = [s for split in ('train','validation','test') for s in split_sequences[split]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        inventories = {seq:(items,candidates,stats) for seq,items,candidates,stats in pool.map(inventory,all_sequences)}
    tasks, all_items = [], {}
    for split in ('train','validation','test'):
        # Some public capture folders contain only side-camera semantic labels.
        # Keep their date assignment/inventory but allocate no front-center quota.
        seqs = [s for s in split_sequences[split] if inventories[s][1]]
        if len(seqs) < (2 if split == 'train' else 1) or {s[:8] for s in seqs} != set(config['split_dates'][split]):
            raise ValueError('Configured date lacks eligible front-center semantic pairs: '+split)
        for i, sequence in enumerate(seqs):
            n = config['counts'][split]//len(seqs) + (i < config['counts'][split]%len(seqs))
            items,candidates,_ = inventories[sequence]
            all_items.update(items)
            tasks.append((split,sequence,n,config['minimum_spacing_seconds'],items,candidates))
    with ThreadPoolExecutor(max_workers=4) as pool:
        pairs = [p for group in pool.map(select_sequence,tasks) for p in group]
    # Cross-capture timestamps within a date are also checked, not assumed disjoint.
    for date in {p['capture_date'] for p in pairs}:
        times = sorted(p['camera_timestamp_us'] for p in pairs if p['capture_date']==date)
        if any(b-a < config['minimum_spacing_seconds']*1_000_000 for a,b in zip(times,times[1:])):
            raise ValueError('Selected captures contain adjacent/overlapping exposures within one date')
    root_items,_ = listing('', '/')
    semantic_items,_ = listing(PREFIX, '/')
    all_items.update({r['key']:r for r in root_items+semantic_items})
    metadata = {}
    for key in METADATA:
        data = object_bytes(all_items[key])
        all_items[key]['sha256'] = digest(data)
        metadata[key] = data
    class_map = json.loads(metadata[PREFIX+'class_list.json'])
    if class_map.get('#ffc125') != 'Solid line' or class_map.get('#8000ff') != 'Dashed line':
        raise ValueError('Unexpected marking class map')
    calibration = json.loads(metadata['cams_lidars.json'])['cameras']['front_center']
    selected_keys = METADATA + [p[k] for p in pairs for k in ('rgb','label','camera_info')]
    objects = [all_items[key] for key in sorted(set(selected_keys))]
    total = sum(r['size'] for r in objects)
    if total > config['maximum_bytes']:
        raise ValueError(f'Planned {total} bytes exceeds budget; change counts explicitly')
    result = dict(schemaVersion=1,dataset='A2D2',base_url=BASE,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        config=config,split_sequences=split_sequences,inventory={s:inventories[s][2] for s in all_sequences},pairs=pairs,objects=objects,planned_bytes=total,
        expected_resolution=calibration['Resolution'],class_map=class_map,
        source='https://a2d2-dataset.github.io/',registry='https://registry.opendata.aws/aev-a2d2/',
        license='CC BY-ND 4.0',license_url='https://creativecommons.org/licenses/by-nd/4.0/',
        grouping='All capture directories sharing YYYYMMDD are assigned to one split before frame selection; no route-disjoint guarantee.',
        qualification='Small supervised research pilot, not production validation. Existing eight smoke images belong to training dates. Annotated frames are non-sequential. Date isolation does not prove different roads or environments.',
        sampling='Balanced quotas across eligible front-center captures; captures without paired front-center labels retained in inventory with zero quota. Deterministic endpoint/midpoint traversal with actual camera timestamp spacing; no pixel or label-content curation.',
        limits='Original bytes only; local research use. No redistribution, Hub upload or determination of trained-model distribution rights. Global 193MB CHECKSUMS.txt omitted; conditional ETags, available MD5 checks and local SHA256 used.')
    output.parent.mkdir(parents=True,exist_ok=True)
    write_json(output,result)
    return result


def png_dimensions(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('Expected original PNG with IHDR')
    return list(struct.unpack('>II',data[16:24]))


def validate_plan(data):
    validate_config(data['config'])
    if data.get('schemaVersion') != 1 or data.get('base_url') != BASE:
        raise ValueError('Unsupported plan/source')
    objects = {r['key']:r for r in data['objects']}
    if len(objects) != len(data['objects']) or sum(r['size'] for r in objects.values()) != data['planned_bytes'] or data['planned_bytes'] > data['config']['maximum_bytes']:
        raise ValueError('Plan objects or byte accounting mismatch')
    expected = set(METADATA)
    for pair in data['pairs']:
        sequence,split = pair['sequence'],pair['split']
        if not re.fullmatch(r'20\d{6}_\d{6}',sequence) or sequence[:8] not in data['config']['split_dates'][split]:
            raise ValueError('Pair crosses planned capture-date split')
        rgb = pair['rgb']
        if not rgb.startswith(f'{PREFIX}{sequence}/camera/cam_front_center/') or not rgb.endswith('.png') or pair['label'] != rgb.replace('/camera/','/label/').replace('_camera_','_label_') or pair['camera_info'] != rgb[:-4]+'.json':
            raise ValueError('Invalid planned RGB/label pairing')
        expected.update(pair[k] for k in ('rgb','label','camera_info'))
    if expected != set(objects):
        raise ValueError('Plan contains unexpected or missing source objects')
    if len({p['rgb'] for p in data['pairs']}) != len(data['pairs']):
        raise ValueError('Duplicate selected source frame')
    for split,count in data['config']['counts'].items():
        if sum(p['split']==split for p in data['pairs']) != count:
            raise ValueError('Split count mismatch')
    for row in objects.values():
        safe_key(row['key'])
        if type(row['size']) is not int or row['size'] <= 0:
            raise ValueError('Invalid object size')
    return objects


def fetch(plan_path, output):
    raw_plan = plan_path.read_bytes()
    data = json.loads(raw_plan)
    objects = validate_plan(data)
    output = output.resolve()
    repo = Path(__file__).resolve().parents[2]
    if output == repo or repo in output.parents or output.exists():
        raise ValueError('Choose a new output directory outside the repository')
    output.mkdir(parents=True,exist_ok=False)
    (output/'source-plan.json').write_bytes(raw_plan)
    def get(row):
        raw = object_bytes(row)
        if row['key'].endswith('.png') and png_dimensions(raw) != data['expected_resolution']:
            raise ValueError('Original image dimensions disagree with front-center calibration')
        path = output / row['key']
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        return dict(row,sha256=digest(raw),local_path=str(path),url=BASE+urllib.parse.quote(row['key']),
                    etag_md5_verified=bool(re.fullmatch('[0-9a-fA-F]{32}',row['etag'].strip('"'))))
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(get,objects.values()))
        index = {r['key']:r for r in fetched}
        by_date = {}
        hashes = {}
        for pair in data['pairs']:
            info = json.loads((output/pair['camera_info']).read_text())
            if info.get('cam_name') != 'front_center' or info.get('cam_tstamp') != pair['camera_timestamp_us']:
                raise ValueError('Camera/timestamp changed after planning')
            by_date.setdefault(pair['capture_date'],[]).append(info['cam_tstamp'])
            h = index[pair['rgb']]['sha256']
            if h in hashes:
                raise ValueError('Duplicate RGB source bytes across selected frames')
            hashes[h] = pair['split']
        for values in by_date.values():
            times = sorted(values)
            if any(b-a < data['config']['minimum_spacing_seconds']*1_000_000 for a,b in zip(times,times[1:])):
                raise ValueError('Actual timestamp spacing failed')
        manifest = dict(data,objects=fetched,source_plan_sha256=digest(raw_plan),download_bytes=sum(r['size'] for r in fetched),
                        completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write_json(output/'manifest.json',manifest)
        (output/'ATTRIBUTION.txt').write_text('A2D2: Audi Autonomous Driving Dataset. Audi / Jakob Geyer et al. (2020), arXiv:2004.06320.\nSource: https://a2d2-dataset.github.io/ and https://registry.opendata.aws/aev-a2d2/\nDataset license: CC BY-ND 4.0, https://creativecommons.org/licenses/by-nd/4.0/\nOriginal bytes retained for local research. No publication or model distribution clearance inferred.\n')
        return manifest
    except Exception as error:
        write_json(output/'incomplete.json',dict(status='incomplete',reason=str(error),source_plan_sha256=digest(raw_plan)))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    p = commands.add_parser('plan'); p.add_argument('--config',type=Path); p.add_argument('--output',required=True,type=Path)
    f = commands.add_parser('fetch'); f.add_argument('--plan',required=True,type=Path); f.add_argument('--output-dir',required=True,type=Path)
    args = parser.parse_args()
    try:
        result = plan(json.loads(args.config.read_text()) if args.config else DEFAULT_CONFIG,args.output) if args.command=='plan' else fetch(args.plan,args.output_dir)
    except (ValueError,KeyError,OSError,subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(json.dumps({key:result[key] for key in ('split_sequences','planned_bytes','qualification')},indent=2))


if __name__ == '__main__':
    main()

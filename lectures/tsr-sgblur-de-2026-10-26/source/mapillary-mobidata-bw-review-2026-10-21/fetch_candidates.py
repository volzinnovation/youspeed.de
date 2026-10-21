#!/usr/bin/env python3
"""Bounded Mapillary API discovery from a frozen MobiData query plan.

Requires the user's own registered client token. Outputs are private build
inputs, not publishable metadata: CDN URLs expire. No labels are approved.
Uses the documented image radius search and throttles concurrent requests.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageDraw, ImageFont


FIELDS = ('id,geometry,computed_geometry,compass_angle,computed_compass_angle,'
          'captured_at,creator,sequence,is_pano,width,height,make,model,'
          'quality_score,thumb_1024_url,thumb_2048_url,thumb_original_url')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def distance(a, b):
    return math.hypot((a[0]-b[0])*111320*math.cos(math.radians((a[1]+b[1])/2)), (a[1]-b[1])*111320)


def bearing(a, b):
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    delta = math.radians(b[0]-a[0])
    return math.degrees(math.atan2(math.sin(delta)*math.cos(lat2),
        math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta))) % 360


class Client:
    def __init__(self, token_file):
        if token_file.is_symlink() or not token_file.is_file():
            raise ValueError('Expected the configured local token file')
        os.chmod(token_file, 0o600)
        self._token = token_file.read_text().strip()
        if not self._token or any(ch.isspace() for ch in self._token):
            raise ValueError('The local token file is empty or has internal whitespace')
        self.cert = '/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').is_file() else True

    def graph(self, entity, params):
        # Never put credentials into URLs, command arguments, cache keys or logs.
        for attempt in range(4):
            r = requests.get('https://graph.mapillary.com/'+entity,
                params=params, headers={'Authorization':'OAuth '+self._token},
                timeout=(15, 45), verify=self.cert)
            if r.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(min(20, 2**(attempt+1)))
                continue
            try:
                body = r.json()
            except ValueError:
                raise RuntimeError('Mapillary returned non-JSON, HTTP '+str(r.status_code)) from None
            if r.status_code != 200 or 'error' in body:
                error = body.get('error', {})
                raise RuntimeError('Mapillary HTTP '+str(r.status_code)+'; error code '+str(error.get('code'))+
                                   ', subcode '+str(error.get('error_subcode'))) from None
            # Graph paging URLs may repeat credentials even with header auth.
            # Radius sampling does not follow them; retain only a capped-result flag.
            paging = body.pop('paging', None)
            if paging:
                body['has_next_page'] = bool(paging.get('next'))
            return body
        raise RuntimeError('Mapillary retry limit reached')


def collect(args):
    client = Client(args.token_file)
    args.output.mkdir(parents=True, exist_ok=True)
    # Probe once before scheduling a batch; authentication errors stop here.
    probe = client.graph('1666865467913496', {'fields':FIELDS})
    write(args.output/'graph/1666865467913496.json', probe)
    if args.probe_only:
        print(json.dumps({'probe':'ok', 'image_id':probe['id'], 'is_pano':probe.get('is_pano'),
                          'dimensions':[probe.get('width'), probe.get('height')],
                          'original_url_available':bool(probe.get('thumb_original_url'))}))
        return
    points = json.loads(args.plan.read_text())[:args.max_points]
    def query(point):
        key = point['record_key']
        cache = args.output/'queries'/(key+'.json')
        if cache.exists():
            return point, json.loads(cache.read_text())
        body = client.graph('images', {'fields':FIELDS, 'lat':point['latitude'],
            'lng':point['longitude'], 'radius':50, 'limit':100})
        write(cache, body)
        return point, body
    candidates = {}
    covered10, covered50, capped = set(), set(), set()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(query, p) for p in points]
        for done, future in enumerate(as_completed(jobs), 1):
            point, body = future.result()
            target = [point['longitude'], point['latitude']]
            if len(body.get('data', [])) >= 100:
                capped.add(point['record_key'])
            choices = []
            for image in body.get('data', []):
                geo = image.get('computed_geometry') or image.get('geometry')
                if not geo or geo.get('type') != 'Point':
                    continue
                pos = geo['coordinates'][:2]
                dist = distance(target, pos)
                if dist > 50:
                    continue
                covered50.add(point['record_key'])
                if dist <= 10:
                    covered10.add(point['record_key'])
                angle = image.get('computed_compass_angle', image.get('compass_angle'))
                off_axis = abs((bearing(pos, target)-angle+180) % 360-180) if angle is not None else 0
                if not image.get('is_pano') and dist > 3 and off_axis > 75:
                    continue
                score = dist + (70 if image.get('is_pano') else off_axis/5) - 10*(image.get('quality_score') or 0)
                choices.append((score, image, dist, off_axis))
            for score, image, dist, off_axis in sorted(choices, key=lambda x:(x[0], x[1]['id']))[:3]:
                key = str(image['id'])
                r = {'image_id':key, 'registry_record':point, 'image_metadata':image,
                     'distance_camera_to_registry_m':round(dist, 2), 'off_axis_degrees':round(off_axis, 2),
                     'selection_score':round(score, 3), 'human_approved':False}
                if key not in candidates or score < candidates[key]['selection_score']:
                    candidates[key] = r
            if done % 50 == 0:
                print(json.dumps({'queried_points':done, 'unique_candidates':len(candidates)}), flush=True)
    rows = sorted(candidates.values(), key=lambda r:(bool(r['image_metadata'].get('is_pano')),
        r['selection_score'], hashlib.sha256(r['image_id'].encode()).hexdigest()))
    # Keep different registry sites and sequences first. No class is inferred from the inventory.
    selected, used_sites, used_sequences = [], set(), set()
    for r in rows:
        seq = str(r['image_metadata'].get('sequence') or r['image_id'])
        site = r['registry_record']['location_id']
        if site in used_sites or seq in used_sequences:
            continue
        selected.append(r)
        used_sites.add(site)
        used_sequences.add(seq)
        if len(selected) >= args.max_previews:
            break
    def download(r):
        key = r['image_id']
        path = args.output/'previews'/(key+'.jpg')
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            url = r['image_metadata'].get('thumb_2048_url') or r['image_metadata'].get('thumb_1024_url')
            host = urlsplit(url or '').hostname or ''
            if not host.endswith('.fbcdn.net'):
                raise ValueError('Unexpected image CDN host')
            res = requests.get(url, timeout=(15, 45), verify=client.cert)
            if res.status_code != 200:
                raise RuntimeError('Image download HTTP '+str(res.status_code))
            path.write_bytes(res.content)
        with Image.open(path) as im:
            im.verify()
        r['preview_path'] = str(path.resolve())
        r['preview_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return r
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        selected = list(pool.map(download, selected))
    write(args.output/'candidate-previews.json', selected)
    summary = {'queried_registry_records':len(points), 'queried_municipalities':len({p['municipality_ars'] for p in points}),
        'matched_within_10m':len(covered10), 'matched_within_50m':len(covered50),
        'queries_at_100_image_cap':len(capped), 'unique_candidate_images':len(candidates),
        'downloaded_previews':len(selected), 'full_bw_coverage_measured':False,
        'sampling':'Bounded frozen query plan; capped results and filtering prevent an exhaustive coverage claim.',
        'training_performed':False, 'human_approved':False}
    write(args.output/'search-summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--token-file', type=Path, default=Path(__file__).resolve().parents[4]/'secret/MAPILLARY-CLIENT-TOKEN.txt')
    p.add_argument('--plan', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-points', type=int, default=200)
    p.add_argument('--max-previews', type=int, default=120)
    p.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    p.add_argument('--probe-only', action='store_true')
    a = p.parse_args()
    if not a.probe_only and a.plan is None:
        p.error('--plan is required unless --probe-only is supplied')
    collect(a)

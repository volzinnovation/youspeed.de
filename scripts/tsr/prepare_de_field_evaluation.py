#!/usr/bin/env python3
"""Freeze route-separated, prediction-blind crop candidates; never invent truth."""
from __future__ import annotations
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'Woladen.de-analytics'))
sys.path.insert(1, str(ROOT.parent / 'streetshots-inspector'))
from inspector.server import CropStore, OBSERVATION_JOIN, LIVE_ACTIVE_MEDIA, PANORAMAX_JOIN, ACTIVE_PANORAMAX
from scripts.inspector.panoramax_annotation_statistics import arguments, load_catalogs, load_mapping
from scripts.tsr.source_annotation_labels import resolve_crop_labels

SEED = 'de-field-evaluation-20261109-v1'
CUTOFF = '2026-10-21T00:00:00+00:00'
BUFFER_M = 200
PAN_SQL = """SELECT f.crop_id::text,f.picture_id::text,f.annotation_id,f.fingerprint,
 i.fingerprint AS item_fingerprint,c.digest,c.geometry,o.width,o.height,o.bytes,
 i.metadata#>>'{picture,ts}' AS captured_at,i.metadata#>'{picture,geometry}' AS gps,
 i.metadata->'collections' AS collections,i.visibility,i.geographic_country,
 f.metadata->'semantics' AS semantics,
 COALESCE((SELECT jsonb_agg(l.label ORDER BY l.ordinal) FROM youspeed.panoramax_class_labels l
 WHERE l.crop_id=f.crop_id AND l.fingerprint=f.fingerprint AND l.mapping_sha256=%s),'[]'::jsonb) AS labels
 """ + PANORAMAX_JOIN + " WHERE " + ACTIVE_PANORAMAX + " ORDER BY f.crop_id"
MOBILE_SQL = """SELECT m.crop_id::text,m.digest,m.installation::text,m.epoch,m.manifest,
 e.event_id::text AS sighting_id,e.captured_at,e.payload->'event' AS event
 FROM youspeed.media m """ + OBSERVATION_JOIN + " WHERE " + LIVE_ACTIVE_MEDIA + """
 AND youspeed.live_crop_exclusion_reason(m.manifest,e.payload->'event') IS NULL
 AND e.payload#>>'{event,classification,country}'='DE'
 AND e.payload#>>'{event,app,platform}' IN('ios','android') ORDER BY m.crop_id"""
HISTORY_SQL = """SELECT picture_id::text,metadata#>'{picture,geometry}' AS gps,
 metadata->'collections' AS collections FROM youspeed.panoramax_items
 WHERE source_id='panoramax.woladen.de' AND picture_id=ANY(%s::uuid[]) ORDER BY picture_id"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, default=str, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def stable(*parts):
    return hashlib.sha256('|'.join([SEED, *map(str, parts)]).encode()).hexdigest()


def coord(value):
    if not isinstance(value, dict):
        return None
    if value.get('type') == 'Point':
        xy = value.get('coordinates')
        if isinstance(xy, list) and len(xy) >= 2:
            lon, lat = xy[:2]
        else:
            return None
    else:
        lat = value.get('latitude', value.get('lat'))
        lon = value.get('longitude', value.get('lon', value.get('lng')))
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return [float(lon), float(lat)]
    return None


def distance(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [*a, *b])
    q = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(q)))


def collections(values):
    return sorted({str(c[k]['id'] if k == 'sequence' else c[k])
                   for c in values or [] for k in ('id', 'sequence')
                   if c.get(k) and (k != 'sequence' or c[k].get('id'))})


def rgb_hash(image):
    return hashlib.sha256(str(image.size).encode()+b'\0'+image.tobytes()).hexdigest()


@contextmanager
def store_context():
    ports=[]
    for _ in range(2):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));ports.append(sock.getsockname()[1])
    db_port, image_port = ports
    proc = subprocess.Popen(['ssh','-N','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
        '-o','ConnectTimeout=12','-i',str(Path.home()/'.ssh/id_ed25519'),
        '-L',f'127.0.0.1:{db_port}:172.19.0.2:5432',
        '-L',f'127.0.0.1:{image_port}:127.0.0.1:8080','raphael@141.47.91.52'],
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(60):
            if proc.poll() is not None:raise RuntimeError('Read-only tunnel failed')
            try:
                with socket.create_connection(('127.0.0.1',db_port),timeout=.2):pass
                break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('Read-only tunnel timeout')
        args=arguments([])
        args.database_file=ROOT.parent/'Woladen.de-analytics/secret/youspeed/volz-db/database-report.txt'
        args.db_host,args.db_port='127.0.0.1',db_port
        args.mobile_image_proxy_url=f'http://127.0.0.1:{image_port}'
        args.panoramax_image_proxy_url=None
        args.panoramax_public_image_fallback=True
        store=CropStore(args)
        # Preserve the configured upstream Host through the ephemeral SSH port.
        # This is the existing private loopback Inspector; no service settings,
        # authentication, URL allowlist, or redirect behavior are changed.
        underlying=store.mobile_image_opener
        class UpstreamHostOpener:
            def open(self,request,**kwargs):
                request.add_header('Host','127.0.0.1:8080')
                return underlying.open(request,**kwargs)
        store.mobile_image_opener=UpstreamHostOpener()
        yield store,args
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        proc.stderr.close()


def snapshot(out, historical, supplement):
    assert not (out/'snapshot.json').exists(),'Freeze once; use a new run directory for a new inventory.'
    prior=json.loads(historical.read_text());extra=json.loads(supplement.read_text())
    prior_ids={str(r['source_id']) for r in prior['samples'] if r.get('source_id')}
    prior_ids.update(r['picture_id'] for r in extra['samples'])
    uuid_prior_ids=[];non_uuid_prior_ids=[]
    for value in sorted(prior_ids):
        try:uuid_prior_ids.append(str(UUID(value)))
        except ValueError:non_uuid_prior_ids.append(value)
    with store_context() as (store,args):
        mapping=load_mapping(args.mapping_file)
        with store.connection() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            db.execute("SET LOCAL statement_timeout='90000ms'")
            identity=db.execute("SELECT transaction_timestamp() AS as_of,current_user AS role,current_database() AS database,current_setting('transaction_read_only') AS read_only").fetchone()
            assert identity['role']=='youspeed_report' and identity['read_only']=='on'
            mobile=db.execute(MOBILE_SQL).fetchall();print('mobile snapshot',len(mobile),flush=True)
            pano=db.execute(PAN_SQL,(mapping['sha256'],)).fetchall();print('Panoramax snapshot',len(pano),flush=True)
            exposed=db.execute(HISTORY_SQL,(uuid_prior_ids,)).fetchall()
            reviews=db.execute("SELECT 'mobile' AS source,count(*) FROM youspeed.crop_reviews UNION ALL SELECT 'panoramax',count(*) FROM youspeed.panoramax_crop_reviews").fetchall()
    dump(out/'snapshot.json',{'identity':identity,'mapping_sha256':mapping['sha256'],
         'mobile':mobile,'panoramax':pano,'exposed_picture_metadata':exposed,'review_counts':reviews,
         'historical_manifest_sha256':sha(historical),'source_supplement_sha256':sha(supplement),
         'historical_source_ids_without_uuid':non_uuid_prior_ids,'script_sha256':sha(__file__)})
    (out/'source-queries.sql').write_text(PAN_SQL+';\n\n'+MOBILE_SQL+';\n\n'+HISTORY_SQL+';\n')


def select(out, historical, supplement):
    assert not (out/'selection-frozen.json').exists(),'Selection is immutable.'
    frozen=json.loads((out/'snapshot.json').read_text());prior=json.loads(historical.read_text());extra=json.loads(supplement.read_text())
    assert sha(historical)==frozen['historical_manifest_sha256'] and sha(supplement)==frozen['source_supplement_sha256']
    classes=prior['classes'];catalogs,models=load_catalogs()
    known_pictures={str(r['source_id']) for r in prior['samples'] if r.get('source_id')}
    known_pictures.update(r['picture_id'] for r in extra['samples'])
    known_crops={r['crop_id'] for r in extra['samples']}
    known_hashes={r['sha256'] for r in prior['samples']} | {r['sha256'] for r in extra['samples']}
    known_routes={x for r in extra['samples'] for x in r.get('collection_ids',[])+r.get('sequence_ids',[])}
    known_positions=[]
    for r in frozen['exposed_picture_metadata']:
        known_routes.update(collections(r['collections']))
        if coord(r['gps']):known_positions.append(coord(r['gps']))
    candidates=[];excluded=Counter();route_reasons=defaultdict(set);all_unqualified=0
    for r in frozen['panoramax']:
        q=resolve_crop_labels(r['labels'],catalogs,model_labels=models)
        if q['status']!='unique' or q.get('country')!='DE':
            excluded['panoramax:not_unique_DE']+=1;continue
        codes={x.get('raw_tag') for x in r['labels'] if x.get('raw_tag')}
        model_keys={x.get('key','') for x in r['semantics'] or [] if x.get('key','').startswith('classification_model')}
        unqualified=not model_keys
        all_unqualified+=int(unqualified)
        routes=collections(r['collections'])
        row={'source':'panoramax','crop_id':r['crop_id'],'picture_id':r['picture_id'],
             'digest':r['digest'],'captured_at':r['captured_at'],'coordinates':coord(r['gps']),
             'route_tokens':['collection:'+x for x in routes],
             'width':r['width'],'height':r['height'],'sign_box':r['geometry']['sign_in_crop'],
             'geometry':r['geometry'],'fingerprint':r['fingerprint'],'item_fingerprint':r['item_fingerprint'],
             'proposed_label':q['class_id'],'label_provenance':'source_annotation_without_model_qualifier' if unqualified else 'model_qualified_source_annotation',
             'truth_label':None,'truth_status':'unadjudicated','source_memberships':routes}
        reasons=[]
        if r['picture_id'] in known_pictures or r['crop_id'] in known_crops:reasons.append('known_picture_or_crop')
        if any(x in known_routes for x in routes):reasons.append('known_collection')
        if r['digest'] in known_hashes:reasons.append('known_encoded_hash')
        candidates.append((row,reasons))
    for r in frozen['mobile']:
        e=r['event'];m=r['manifest'];source=e['app']['platform'];o=m['original_box'];a=m['actual_box']
        width,height=m.get('decoded_width'),m.get('decoded_height')
        if not (len(o)==len(a)==4 and width==a[2]-a[0] and height==a[3]-a[1] and a[0]<=o[0]<o[2]<=a[2] and a[1]<=o[1]<o[3]<=a[3]):
            excluded[source+':invalid_geometry']+=1;continue
        session=e.get('collection_session_id')
        row={'source':source,'crop_id':r['crop_id'],'installation':r['installation'],'epoch':r['epoch'],
             'sighting_id':r['sighting_id'],'digest':r['digest'],'captured_at':r['captured_at'],
             'coordinates':coord(e.get('sign_position')) or coord(e.get('vehicle_position')),
             'coordinate_basis':'sign_position' if coord(e.get('sign_position')) else 'vehicle_position',
             'route_tokens':['collection:'+str(session)] if session else [],
             'width':width,'height':height,'sign_box':[o[0]-a[0],o[1]-a[1],o[2]-a[0],o[3]-a[1]],
             'geometry':{'original_box':o,'actual_box':a,'crop_version':m.get('crop_version')},
             'proposed_label':e.get('classification',{}).get('model_label'),
             'label_provenance':'mobile_model_prediction','truth_label':None,'truth_status':'unadjudicated'}
        reasons=['known_encoded_hash'] if r['digest'] in known_hashes else []
        if session and str(session) in known_routes:reasons.append('known_collection')
        candidates.append((row,reasons))
    # Whole route exclusion: one exposed image/nearby known sign rejects all its route members.
    for row,reasons in candidates:
        if not row['route_tokens']:reasons.append('missing_route')
        if not row['coordinates']:reasons.append('missing_position')
        if row['coordinates'] and any(distance(row['coordinates'],p)<=BUFFER_M for p in known_positions):
            reasons.append('within_200m_known_exposure')
        stamp=datetime.fromisoformat(str(row['captured_at']).replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('Capture timestamp lacks timezone')
        if stamp<datetime.fromisoformat(CUTOFF):reasons.append('before_fresh_capture_cutoff')
        for route in row['route_tokens']:
            route_reasons[route].update(reasons)
    # Connect overlapping collection memberships before selection.
    parent={route:route for row,_ in candidates for route in row['route_tokens']}
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(a,b):parent[find(b)]=find(a)
    for row,_ in candidates:
        for route in row['route_tokens'][1:]:union(row['route_tokens'][0],route)
    components=defaultdict(set);component_reasons=defaultdict(set)
    for route in parent:
        components[find(route)].add(route);component_reasons[find(route)].update(route_reasons[route])
    admitted=[];rejected=[]
    for row,reasons in candidates:
        if row['route_tokens']:
            root=find(row['route_tokens'][0]);reasons=sorted(set(reasons)|component_reasons[root])
            row['route_component']='route-'+stable(*sorted(components[root]))[:24]
            row['route_component_members']=sorted(components[root])
        if reasons:
            row['exclusion_reasons']=reasons;rejected.append(row)
            for reason in reasons:excluded[row['source']+':'+reason]+=1
        else:admitted.append(row)
    # One deterministic best-native-area image per phone sighting; no prediction scores consulted.
    representatives={}
    for row in admitted:
        key=(row['source'],row.get('installation'),row.get('epoch'),row.get('sighting_id')) if row['source']!='panoramax' else ('panoramax',row['crop_id'])
        box=row['sign_box'];quality=(-(box[2]-box[0])*(box[3]-box[1]),stable(row['crop_id']))
        if key not in representatives or quality<representatives[key][0]:representatives[key]=(quality,row)
    pool=[v[1] for v in representatives.values()];selected=[]
    for source in ('panoramax','ios','android'):
        groups=defaultdict(list)
        for row in pool:
            if row['source']==source:groups[row['route_component']].append(row)
        for group in groups:groups[group].sort(key=lambda r:stable('member',r['crop_id']))
        group_order=sorted(groups,key=lambda g:stable('route',source,g));count=0;depth=0
        while count<40:
            added=False
            for group in group_order:
                if depth<len(groups[group]) and count<40:
                    row=dict(groups[group][depth]);row['sample_id']='field-'+stable(source,row['crop_id'])[:20]
                    selected.append(row);count+=1;added=True
            if not added:break
            depth+=1
    selected.sort(key=lambda r:(r['source'],stable('display',r['sample_id'])))
    counters=Counter()
    for row in selected:
        counters[row['source']]+=1
        row['blind_id']={'panoramax':'P','ios':'I','android':'A'}[row['source']]+f"{counters[row['source']]:03d}"
    payload={'schema':'de-fresh-crop-selection-v1','seed':SEED,'snapshot_sha256':sha(out/'snapshot.json'),
        'historical_manifest_sha256':sha(historical),'supplement_manifest_sha256':sha(supplement),
        'fresh_capture_cutoff':CUTOFF,'known_exposure_buffer_m':BUFFER_M,'classes':classes,
        'known_pictures':len(known_pictures),'known_route_tokens':len(known_routes),'known_positions':len(known_positions),
        'matched_historical_picture_ids':len(frozen['exposed_picture_metadata']),
        'current_unqualified_panoramax_DE':all_unqualified,'review_counts':frozen['review_counts'],
        'eligible_counts':dict(Counter(r['source'] for r in pool)),
        'eligible_routes':{s:len({r['route_component'] for r in pool if r['source']==s}) for s in ('panoramax','ios','android')},
        'selected_counts':dict(Counter(r['source'] for r in selected)),
        'selected_routes':{s:len({r['route_component'] for r in selected if r['source']==s}) for s in ('panoramax','ios','android')},
        'exclusion_counts_nonexclusive':dict(excluded),'samples':selected,'script_sha256':sha(__file__),
        'selection_uses_predictions':False,'labels': 'All unadjudicated. Proposals are audit-only and not ground truth.',
        'limitations':['Known collection/session routes separated; full historical HF routes unavailable.',
            '200m buffer applies to known exposure camera/sign positions, not complete historical road geometry.',
            'Cross-provider physical-sign near duplicates still require visual review.',
            'Zero human review rows; all original unqualified DE source labels already in previous exposure pool.',
            'Source-conditioned crop samples cannot measure detector misses or unconditional road prevalence.']}
    dump(out/'selection-frozen.json',payload)
    dump(out/'excluded-candidates.json',rejected)
    dump(out/'eligible-candidates.json',pool)
    print(json.dumps({k:payload[k] for k in ['eligible_counts','eligible_routes','selected_counts','selected_routes','known_positions','current_unqualified_panoramax_DE','review_counts']},indent=2),flush=True)


def download(out,historical,supplement,allow_unavailable_source=False):
    from PIL import Image,ImageOps
    selection=json.loads((out/'selection-frozen.json').read_text())
    assert not (out/'download-complete.json').exists(),'Preserve completed pack'
    for sub in ('native','canonical','blind'): (out/sub).mkdir(exist_ok=True)
    old=json.loads(historical.read_text())['samples']+json.loads(supplement.read_text())['samples']
    old_hashes={r[k] for r in old for k in ('sha256','rgb_sha256','raw_rgb_sha256','sign_rgb_sha256','sign_raw_rgb_sha256') if r.get(k)}
    with store_context() as (store,args):
        def fetch(row):
            native=out/'native'/(row['blind_id']+'.png')
            if native.exists():data=native.read_bytes()
            elif row['source']=='panoramax':data,_=store.panoramax_image(row['crop_id'])
            else:data,_=store.image((row['installation'],row['epoch'],row['crop_id']))
            assert hashlib.sha256(data).hexdigest()==row['digest']
            with Image.open(io.BytesIO(data)) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.load()
            assert im.size==(row['width'],row['height'])
            box=row['sign_box'];assert 0<=box[0]<box[2]<=im.width and 0<=box[1]<box[3]<=im.height
            sign=im.crop(tuple(box));hashes=[row['digest'],rgb_hash(im),hashlib.sha256(im.tobytes()).hexdigest(),rgb_hash(sign),hashlib.sha256(sign.tobytes()).hexdigest()]
            assert not set(hashes)&old_hashes,'New decoded pixel overlap: invalidate whole route before inference'
            native.write_bytes(data)
            canonical=out/'canonical'/(row['blind_id']+'.png')
            sign.resize((224,224),Image.Resampling.BILINEAR).save(canonical,format='PNG')
            blind=out/'blind'/(row['blind_id']+'.png');sign.save(blind,format='PNG')
            return {**row,'path':'native/'+native.name,'canonicalPath':'canonical/'+canonical.name,
                    'sha256':hashes[0],'canonicalSha256':sha(canonical),'native_rgb_sha256':hashes[1],
                    'sign_rgb_sha256':hashes[3],'blind_path':'blind/'+blind.name}
        results=[];failures=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs={pool.submit(fetch,row):row for row in selection['samples']}
            for job in as_completed(jobs):
                try:results.append(job.result())
                except Exception as exc:failures.append({'blind_id':jobs[job]['blind_id'],'source':jobs[job]['source'],'error':str(exc),'type':type(exc).__name__})
                if (len(results)+len(failures))%10==0:print('Verified',len(results),'failed',len(failures),flush=True)
        permitted_unavailable=(allow_unavailable_source and all(
            r['source']=='panoramax' and r['type']=='InspectorError'
            and r['error']=='Öffentliches Panoramax-Bild: Panoramax-Aufnahme ist nicht mehr öffentlich verfügbar.'
            for r in failures))
        if not failures or permitted_unavailable:
            with store.connection() as db:
                db.execute("SET LOCAL statement_timeout='30000ms'")
                mobile_ids=[r['crop_id'] for r in results if r['source']!='panoramax']
                pan_ids=[r['crop_id'] for r in results if r['source']=='panoramax']
                mobile=db.execute('SELECT m.crop_id::text,m.digest,m.manifest FROM youspeed.media m WHERE '+LIVE_ACTIVE_MEDIA+' AND m.crop_id=ANY(%s::uuid[])',(mobile_ids,)).fetchall()
                pan=db.execute('SELECT f.crop_id::text,c.digest,f.fingerprint,i.fingerprint AS item_fingerprint '+PANORAMAX_JOIN+' WHERE '+ACTIVE_PANORAMAX+' AND f.crop_id=ANY(%s::uuid[])',(pan_ids,)).fetchall()
                checked_at=db.execute('SELECT transaction_timestamp() AS as_of').fetchone()['as_of']
            ml={r['crop_id']:r for r in mobile};pl={r['crop_id']:r for r in pan}
            assert set(ml)==set(mobile_ids) and set(pl)==set(pan_ids),'Lifecycle changed during retrieval'
            for row in results:
                current=pl[row['crop_id']] if row['source']=='panoramax' else ml[row['crop_id']]
                assert current['digest']==row['digest']
                if row['source']=='panoramax':
                    assert current['fingerprint']==row['fingerprint'] and current['item_fingerprint']==row['item_fingerprint']
                else:
                    assert current['manifest']['observation_id']==row['sighting_id']
                    assert current['manifest']['original_box']==row['geometry']['original_box']
                    assert current['manifest']['actual_box']==row['geometry']['actual_box']
            dump(out/'lifecycle-recheck.json',{'checked_at':checked_at,'status':'passed','mobile':len(mobile),'panoramax':len(pan),
                 'selection_sha256':sha(out/'selection-frozen.json'),'transport':'Private SSH tunnel; mobile upstream Host127.0.0.1:8080; Panoramax exact-byte public fallback'})
    dump(out/'download-progress.json',{'samples':results,'failures':failures})
    if failures and not permitted_unavailable:raise RuntimeError(f'{len(failures)} crop fetches failed')
    results.sort(key=lambda r:r['blind_id'])
    assert len(results)+len(failures)==len(selection['samples'])
    dump(out/'evaluation-manifest.json',{'schemaVersion':1,'selection_sha256':sha(out/'selection-frozen.json'),
         'classes':selection['classes'],'samples':results,'label_status':'unadjudicated',
         'preprocessing':'EXIF-corrected RGB native PNG; explicit sign box; Pillow bilinear224; no normalization in PNG.',
         'live_roi_limitation':'Stored mobile crops lack side/top pixels of deployed10%/5%/35% padded ROI. Native images are stored crops, not exact live ROI.'})
    images=[{'id':r['blind_id'],'path':r['path'],'canonicalPath':r['canonicalPath'],'sha256':r['sha256'],
             'canonicalSha256':r['canonicalSha256'],'source':r['source']} for r in results]
    all_name='benchmark-all120.json' if len(images)==120 else 'available-crops.json'
    dump(out/all_name,{'schemaVersion':1,'images':images})
    counts=Counter();bench=[]
    for r in images:
        if counts[r['source']]<32:bench.append(r);counts[r['source']]+=1
    benchmark_name='benchmark96.json' if len(bench)==96 else 'available-benchmark-subset.json'
    dump(out/benchmark_name,{'schemaVersion':1,'images':bench})
    dump(out/'blind/review-manifest.json',{'schemaVersion':1,'images':[{'id':r['blind_id'],'path':Path(r['blind_path']).name,'source':r['source'],'native_path':'../'+r['path']} for r in results],
         'labels':selection['classes'],'annotation_policy':'View pixels only; unknown/ambiguous allowed. Do not read proposal labels or model outputs. Human adjudication is required before release evaluation.'})
    from PIL import ImageDraw,ImageFont
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',18)
    sheets=[]
    for source in ('panoramax','ios','android'):
        subset=[r for r in results if r['source']==source]
        for offset in range(0,len(subset),12):
            chunk=subset[offset:offset+12];canvas=Image.new('RGB',(840,1120),'#e8e8e8');draw=ImageDraw.Draw(canvas)
            for index,row in enumerate(chunk):
                left=(index%3)*280;top=(index//3)*280
                with Image.open(out/row['blind_path']) as image:
                    image=image.convert('RGB');scale=min(256/image.width,236/image.height)
                    image=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.Resampling.NEAREST)
                    canvas.paste(image,(left+(280-image.width)//2,top+28+(242-image.height)//2))
                draw.text((left+12,top+5),row['blind_id'],fill='black',font=font)
            path=out/'blind'/f'contact-sheet-{source}-{offset//12+1:02d}.png';canvas.save(path)
            sheets.append({'path':path.name,'ids':[r['blind_id'] for r in chunk],'sha256':sha(path)})
    dump(out/'blind/contact-sheets.json',sheets)
    dump(out/'download-complete.json',{'samples':len(results),'selected_samples':len(selection['samples']),
         'unavailable_source_records':failures,'replacements_selected':False,'counts':dict(Counter(r['source'] for r in results)),
         'benchmark_samples':len(bench),'selection_sha256':sha(out/'selection-frozen.json'),
         'evaluation_manifest_sha256':sha(out/'evaluation-manifest.json'),'benchmark_manifest':benchmark_name,'benchmark_sha256':sha(out/benchmark_name),
         'encoded_and_decoded_overlap_checks':'passed','production_writes':False,'test_pixels_opened':False})
    print('Pack complete',len(results),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['snapshot','select','download'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--historical',type=Path,required=True)
    p.add_argument('--supplement',type=Path,required=True)
    p.add_argument('--allow-unavailable-source',action='store_true',help='Retain explicitly nonpublic Panoramax records as unavailable; no replacement or other failure bypass.')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if a.phase=='download':download(a.output,a.historical,a.supplement,a.allow_unavailable_source)
    else:{'snapshot':snapshot,'select':select}[a.phase](a.output,a.historical,a.supplement)


if __name__=='__main__':main()

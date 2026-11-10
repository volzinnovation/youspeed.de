#!/usr/bin/env python3
"""Bounded OSM-guided public imagery discovery; map anchors never assign labels."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import ssl
import shlex
import subprocess
import time
from urllib.parse import urlencode, urlparse, urljoin
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.error import HTTPError

AREAS = {'karlsruhe': [8.30, 48.95, 8.50, 49.05], 'pforzheim': [8.65, 48.85, 8.77, 48.93]}
PANORAMAX = {'youspeed': 'https://panoramax.youspeed.de/api/search',
             'federated': 'https://api.panoramax.xyz/api/search'}
MAP_FIELDS = 'id,geometry,computed_geometry,compass_angle,computed_compass_angle,captured_at,creator,sequence,is_pano,width,height,quality_score,thumb_2048_url,thumb_original_url'
CONTEXT = ssl.create_default_context(cafile='/etc/ssl/cert.pem')


def sha(data): return hashlib.sha256(data).hexdigest()
def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n'); tmp.replace(path)


def get(url, *, params=None, body=None, token=None, limit=8*1024**2, timeout=35):
    if urlparse(url).scheme != 'https': raise ValueError('HTTPS required')
    if params: url += '?' + urlencode(params)
    headers = {'User-Agent': 'YouSpeed-DE224-bounded-research/1.0', 'Accept-Encoding': 'identity'}
    if token: headers['Authorization'] = 'OAuth ' + token
    if body is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = Request(url, data=body, headers=headers)
    if token:
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args): return None
        response_context = build_opener(NoRedirect(), HTTPSHandler(context=CONTEXT)).open(request, timeout=timeout)
    else:
        response_context = urlopen(request, context=CONTEXT, timeout=timeout)
    with response_context as response:
        if token and urlparse(response.url).hostname != 'graph.mapillary.com':
            raise ValueError('Unexpected authenticated redirect')
        started=time.monotonic(); chunks=[]; size=0
        while True:
            if time.monotonic()-started > timeout: raise TimeoutError('Response total read deadline exceeded')
            chunk=response.read1(min(65536, limit+1-size))
            if not chunk: break
            chunks.append(chunk); size+=len(chunk)
            if size > limit: raise ValueError('Response byte limit exceeded')
        return b''.join(chunks)


def safe_error(exc):
    result={'type': type(exc).__name__, 'http_status': exc.code if isinstance(exc, HTTPError) else None}
    if isinstance(exc,HTTPError):
        try:
            error=json.loads(exc.read(32768)).get('error',{})
            result['provider_error']={k:error[k] for k in ['type','code','error_subcode','is_transient'] if k in error}
        except Exception:pass
    return result


def image_bytes(url, args):
    """Optional public-image-only transport through the explicitly authorized KI account."""
    if not args.download_via_ssh:
        return get(url, limit=25*1024**2)
    if args.download_via_ssh != 'raphael@141.47.5.55':
        raise ValueError('Only the authorized KI account is supported')
    if urlparse(url).scheme != 'https': raise ValueError('HTTPS required')
    code = ("import sys,urllib.request; "
            "r=urllib.request.urlopen(urllib.request.Request(sys.argv[1],headers={'User-Agent':'YouSpeed-DE224-bounded-research/1.0'}),timeout=35); "
            "b=r.read(25*1024**2+1); "
            "assert len(b)<=25*1024**2,'image byte limit'; sys.stdout.buffer.write(b)")
    command=' '.join(shlex.quote(v) for v in ['python3','-c',code,url])
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/id_ed25519'),'-o','BatchMode=yes',
                           '-o','ConnectTimeout=30',args.download_via_ssh,command],
                          capture_output=True,check=True,timeout=90)
    if len(result.stdout)>25*1024**2: raise ValueError('Image byte limit')
    return result.stdout


def distance(a, b):
    return math.hypot((a[0]-b[0])*111320*math.cos(math.radians((a[1]+b[1])/2)), (a[1]-b[1])*110540)


def bearing(a, b):
    lat1,lat2=math.radians(a[1]),math.radians(b[1]);delta=math.radians(b[0]-a[0])
    return math.degrees(math.atan2(math.sin(delta)*math.cos(lat2),math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta)))%360


def identities(row):
    values = {str(row[k]) for k in ['source_id','picture_id','crop_id','sample_id','group_id','route_component'] if row.get(k)}
    for key in ['route_tokens','route_component_members','collection_ids','sequence_ids','group_identities']:
        values.update(str(x) for x in row.get(key, []))
    return values | {x.split(':',1)[-1] for x in values}


def protection(paths):
    rows, receipts = [], []
    for path in paths:
        raw = path.read_bytes(); doc = json.loads(raw)
        rows.extend(doc['samples']); receipts.append({'path': str(path), 'sha256': sha(raw)})
    return {'ids': set().union(*(identities(r) for r in rows)),
            'coordinates': [r['coordinates'] for r in rows if r.get('coordinates')],
            'pixels': {str(r[k]) for r in rows for k in ['sha256','digest','rgb_sha256','sign_rgb_sha256','native_rgb_sha256'] if r.get(k)},
            'receipts': receipts, 'rows': len(rows)}


def excluded(row, protected):
    reasons = []
    if identities(row) & protected['ids']: reasons.append('protected_picture_or_route')
    if row.get('coordinates') and any(distance(row['coordinates'], p) <= 250 for p in protected['coordinates']):
        reasons.append('protected_250m_geography')
    return reasons


def pbf_anchors(path, protected):
    """Read a fixed local extract; filter bus-stop tags before Python processing."""
    import osmium
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):digest.update(block)
    rows=[]
    processor=osmium.FileProcessor(str(path)).with_locations('flex_mem').with_filter(
        osmium.filter.TagFilter(('highway','bus_stop'),('public_transport','platform')))
    for obj in processor:
        if not (obj.is_node() or obj.is_way()):continue
        tags=dict(obj.tags)
        if not (tags.get('highway')=='bus_stop' or (tags.get('public_transport')=='platform' and tags.get('bus')=='yes')):continue
        if tags.get('public_transport')=='stop_position':continue
        if obj.is_node():
            if not obj.location.valid():continue
            coords=[obj.location.lon,obj.location.lat];geometry=None;kind='node'
        else:
            points=[[n.lon,n.lat] for n in obj.nodes if n.location.valid()]
            if len(points)<2:continue
            coords=[(min(p[0] for p in points)+max(p[0] for p in points))/2,
                    (min(p[1] for p in points)+max(p[1] for p in points))/2]
            geometry=[{'lon':x,'lat':y} for x,y in points];kind='way'
        area=next((name for name,(w,s,e,n) in AREAS.items() if w<=coords[0]<=e and s<=coords[1]<=n),None)
        if not area:continue
        row={'osm_type':kind,'osm_id':obj.id,'coordinates':coords,'geometry':geometry,'tags':tags,
             'area':area,'anchor_role':'passenger_stop_location_not_visual_sign_truth',
             'source_url':f'https://www.openstreetmap.org/{kind}/{obj.id}','osm_version':obj.version,
             'osm_timestamp':str(obj.timestamp),'sign_label':None}
        row['exclusion_reasons']=excluded(row,protected);rows.append(row)
    return rows,[{'method':'local_pbf_tag_filter','path':str(path.resolve()),'sha256':digest.hexdigest(),
                  'bytes':path.stat().st_size,'areas':AREAS,'snapshot_note':'Pinned local September 2026 extract; not a claim of current OSM completeness.'}]


def anchors(args):
    protected = protection(args.holdouts); all_rows=[]; receipts=[]
    if args.osm_pbf:all_rows,receipts=pbf_anchors(args.osm_pbf,protected)
    for area, bbox in ([] if args.osm_pbf else AREAS.items()):
        west,south,east,north=bbox; bounds=f'{south},{west},{north},{east}'
        query=f'[out:json][timeout:25];(node["highway"="bus_stop"]({bounds});way["highway"="bus_stop"]({bounds});node["public_transport"="platform"]["bus"="yes"]({bounds});way["public_transport"="platform"]["bus"="yes"]({bounds}););out center geom;'
        path=args.output/'osm'/f'{area}.json'; url=args.overpass_endpoint
        try:
            raw=get(url,body=urlencode({'data':query}).encode(),limit=8*1024**2)
            doc=json.loads(raw)
            if 'remark' in doc: raise ValueError('Overpass returned a partial/error remark')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            receipts.append({'area':area,'bbox':bbox,'endpoint':url,'query':query,'response_sha256':sha(raw),'elements':len(doc['elements'])})
            for element in doc['elements']:
                tags=element.get('tags',{}); center=element if element['type']=='node' else element.get('center',{})
                if 'lon' not in center or tags.get('public_transport') == 'stop_position': continue
                row={'osm_type':element['type'],'osm_id':element['id'],'coordinates':[center['lon'],center['lat']],
                     'tags':tags,'area':area,'anchor_role':'passenger_stop_location_not_visual_sign_truth',
                     'source_url':f"https://www.openstreetmap.org/{element['type']}/{element['id']}",
                     'geometry':element.get('geometry'),'sign_label':None}
                row['exclusion_reasons']=excluded(row,protected);all_rows.append(row)
        except Exception as exc:
            receipts.append({'area':area,'bbox':bbox,'endpoint':url,'query':query,'error':safe_error(exc)})
    unique={(r['osm_type'],r['osm_id']):r for r in all_rows}
    rows=sorted(unique.values(),key=lambda r:(r['area'],r['osm_type'],r['osm_id']))
    selected=[]
    for area in AREAS:
        choices=sorted([r for r in rows if r['area']==area and not r['exclusion_reasons']],key=lambda r:sha(f"{r['osm_type']}/{r['osm_id']}".encode()))
        for row in choices:
            if any(distance(row['coordinates'],s['coordinates'])<150 for s in selected):continue
            selected.append(row)
            if sum(r['area']==area for r in selected)>=args.max_anchors_per_area:break
    result={'schema':'youspeed-osm-bus-stop-anchors-v1','created_at':datetime.now(timezone.utc).isoformat(),
            'anchors':rows,'query_anchors':selected,'requests':receipts,'holdout_receipts':protected['receipts'],
            'holdout_buffer_m':250,'protected_rows':protected['rows'],'osm_attribution':'© OpenStreetMap contributors',
            'osm_license':'ODbL-1.0','osm_license_url':'https://www.openstreetmap.org/copyright',
            'policy':'Nodes/ways locate passenger stops. OSM tags and nearby imagery never assign a DE:224 visual label.',
            'script_sha256':sha(Path(__file__).read_bytes())}
    write(args.output/'osm-anchors.json',result)
    print(json.dumps({'anchors':len(rows),'query_anchors':len(selected),'errors':[r for r in receipts if 'error' in r]}),flush=True)


def panoramax_is_pano(properties):
    return (properties.get('proj:type') == 'equirectangular'
            or properties.get('exif', {}).get('Xmp.GPano.ProjectionType') == 'equirectangular'
            or properties.get('pers:interior_orientation', {}).get('field_of_view') == 360)


def query_provider(provider, anchor, args, protected, token):
    key=f"{provider}-{anchor['osm_type']}-{anchor['osm_id']}";path=args.output/'queries'/(key+'.json')
    x,y=anchor['coordinates'];radius=args.radius
    if path.exists():doc=json.loads(path.read_text())
    else:
        if provider=='mapillary':
            raw=get('https://graph.mapillary.com/images',params={'fields':MAP_FIELDS,'lat':y,'lng':x,'radius':radius,'limit':40},token=token)
            doc=json.loads(raw);paging=doc.pop('paging',None);doc['has_next_page']=bool(paging and paging.get('next'))
            if 'error' in doc:raise ValueError('Mapillary API error')
        else:
            dy=radius/110540;dx=radius/(111320*math.cos(math.radians(y)))
            raw=get(PANORAMAX[provider],params={'bbox':f'{x-dx},{y-dy},{x+dx},{y+dy}','limit':40})
            doc=json.loads(raw)
        write(path,doc)
    candidates=[]
    features=doc.get('data' if provider=='mapillary' else 'features',[])
    for feature in features:
        if provider=='mapillary':
            geo=feature.get('computed_geometry') or feature.get('geometry');position=(geo or {}).get('coordinates')
            sequence=str(feature.get('sequence') or '')
            row={'source_id':str(feature['id']),'sequence_id':sequence,'route_tokens':['mapillary-sequence:'+sequence] if sequence else [],
                 'is_pano':feature.get('is_pano',False),'preview_url':feature.get('thumb_2048_url'),
                 'hd_url':feature.get('thumb_original_url'),'source_url':'https://www.mapillary.com/app/?pKey='+str(feature['id']),
                 'author':feature.get('creator'),'license':'CC-BY-SA-4.0','license_url':'https://www.mapillary.com/terms',
                 'heading':feature.get('computed_compass_angle',feature.get('compass_angle')),'captured_at':feature.get('captured_at'),
                 'source_instance':'mapillary','source_metadata':feature}
        else:
            position=(feature.get('geometry') or {}).get('coordinates');prop=feature.get('properties',{});links=feature.get('links',[])
            self_url=next((l['href'] for l in links if l.get('rel')=='self'),None)
            origin_url=next((l['href'] for l in links if l.get('rel')=='via'),self_url)
            sequence=str(feature.get('collection') or '');assets=feature.get('assets',{})
            def asset(name):return urljoin(self_url or PANORAMAX[provider],assets.get(name,{}).get('href','')) if assets.get(name,{}).get('href') else None
            row={'source_id':str(feature['id']),'picture_id':str(feature['id']),'sequence_id':sequence,
                 'route_tokens':['collection:'+sequence] if sequence else [],'is_pano':panoramax_is_pano(prop),
                 'preview_url':asset('sd') or asset('thumbnail') or asset('hd'),'hd_url':asset('hd'),
                 'source_url':urljoin(origin_url or self_url,'/api/pictures/'+str(feature['id'])),
                 'federated_item_url':self_url,'author':prop.get('geovisio:producer') or feature.get('providers'),
                 'license':prop.get('license'),'license_url':next((l['href'] for l in links if l.get('rel')=='license'),None),
                 'heading':prop.get('view:azimuth'),'captured_at':prop.get('datetime'),
                 'source_instance':urlparse(origin_url or '').hostname,'source_metadata':feature}
            if prop.get('geovisio:visibility') not in [None,'anyone'] or prop.get('geovisio:status') not in [None,'ready']:continue
        if not position or len(position)<2:continue
        row.update(provider=provider,coordinates=position[:2],osm_anchor=anchor,anchor_distance_m=distance(position[:2],anchor['coordinates']),query_receipt=str(path),query_sha256=sha(path.read_bytes()),human_approved=False,training_only=True,evaluation_eligible=False,label=None)
        if row['anchor_distance_m']>radius:continue
        off_axis=abs((bearing(position[:2],anchor['coordinates'])-row['heading']+180)%360-180) if row.get('heading') is not None else None
        row['off_axis_degrees']=off_axis
        if not row['is_pano'] and off_axis is not None and row['anchor_distance_m']>3 and off_axis>85:continue
        row['selection_score']=row['anchor_distance_m']+(off_axis or 0)/5+(25 if row['is_pano'] else 0)
        reasons=excluded(row,protected)
        if not row['route_tokens']:reasons.append('missing_route_identity')
        row['exclusion_reasons']=reasons
        candidates.append(row)
    return candidates,{'provider':provider,'anchor':key,'returned':len(features),'capped':len(features)>=40 or doc.get('has_next_page',False),'candidate_rows':len(candidates),'response_sha256':sha(path.read_bytes())}


def discover(args):
    protected=protection(args.holdouts);plan=json.loads((args.output/'osm-anchors.json').read_text())['query_anchors']
    token=None
    if 'mapillary' in args.providers and args.token_file.is_file() and not args.token_file.is_symlink():
        token=args.token_file.read_text().strip()
    rows=[];receipts=[];availability={}
    for provider in args.providers:
        if provider=='mapillary' and not token:
            availability[provider]={'status':'unavailable_no_configured_token'};continue
        failures=0
        for anchor in plan[:args.max_queries]:
            try:
                found,receipt=query_provider(provider,anchor,args,protected,token);rows.extend(found);receipts.append(receipt)
                availability[provider]={'status':'available','queries':sum(r['provider']==provider for r in receipts)}
            except Exception as exc:
                failures+=1;receipts.append({'provider':provider,'anchor':f"{anchor['osm_type']}/{anchor['osm_id']}",'error':safe_error(exc)})
                availability[provider]={'status':'partial_or_failed','errors':failures}
                if failures>=3:break
            write(args.output/'discovery-progress.json',{'candidates':rows,'requests':receipts,'provider_availability':availability})
            print(json.dumps({'provider':provider,'requests':sum(r['provider']==provider for r in receipts),'candidates':len(rows),'errors':failures}),flush=True)
            time.sleep(.15)
    unique={}
    for row in sorted(rows,key=lambda r:r['anchor_distance_m']):unique.setdefault((row['provider'],row['source_id']),row)
    result={'schema':'youspeed-osm-guided-image-candidates-v1','created_at':datetime.now(timezone.utc).isoformat(),
            'candidates':list(unique.values()),'requests':receipts,'provider_availability':availability,
            'anchors_sha256':sha((args.output/'osm-anchors.json').read_bytes()),'holdout_receipts':protected['receipts'],
            'protected_rows':protected['rows'],'policy':'No images opened in discovery. Exclude protected routes and 250m before download; map proximity is not class truth.',
            'script_sha256':sha(Path(__file__).read_bytes())}
    write(args.output/'candidates.json',result);print(json.dumps({'unique_candidates':len(unique),'provider_availability':availability}),flush=True)


def fetch(args):
    from PIL import Image,ImageOps
    protected=protection(args.holdouts);source=args.output/'candidates.json';doc=json.loads(source.read_text())
    selected=[];sites=set();routes=set();counts=Counter()
    rows=sorted(doc['candidates'],key=lambda r:(r.get('selection_score',r['anchor_distance_m']),sha(r['source_id'].encode())))
    for row in rows:
        if row['exclusion_reasons'] or excluded(row,protected):continue
        provider=row['provider'];site=(provider,row['osm_anchor']['osm_type'],row['osm_anchor']['osm_id'])
        if counts[provider]>=args.max_images_per_provider or site in sites or any(t in routes for t in row['route_tokens']):continue
        if not row.get('preview_url'):continue
        counts[provider]+=1;sites.add(site);routes.update(row['route_tokens']);selected.append(row)
    write(args.output/'download-selection-frozen.json',{'candidates':selected,'source_sha256':sha(source.read_bytes()),'holdout_receipts':protected['receipts'],'labels_assigned':False})
    results=[];failures=[];total=0
    for i,row in enumerate(selected,1):
        try:
            current_metadata=None
            if row['provider']!='mapillary':
                current_raw=get(row['source_url'],limit=4*1024**2);current_metadata=json.loads(current_raw)
                prop=current_metadata['properties']
                if (str(current_metadata['id'])!=row['source_id'] or prop.get('geovisio:visibility')!='anyone'
                    or prop.get('geovisio:status')!='ready' or str(current_metadata.get('collection'))!=row['sequence_id']):
                    raise ValueError('Current public source identity, route or lifecycle differs')
                row={**row,'coordinates':current_metadata['geometry']['coordinates'][:2],
                     'license':prop.get('license'),'author':prop.get('geovisio:producer'),
                     'is_pano':panoramax_is_pano(prop),
                     'current_source_metadata_sha256':sha(current_raw)}
                if excluded(row,protected):raise ValueError('Current source overlaps protected data')
                metadata_path=args.output/'source-metadata'/(row['source_id']+'.json')
                metadata_path.parent.mkdir(exist_ok=True);metadata_path.write_bytes(current_raw)
                row['current_source_metadata_path']=str(metadata_path.resolve())
            url=row['hd_url'] if args.hd and row.get('hd_url') else row['preview_url']
            if row['provider']=='mapillary' and not (urlparse(url).hostname or '').endswith('.fbcdn.net'):raise ValueError('Unexpected Mapillary CDN')
            raw=image_bytes(url,args);total+=len(raw)
            if total>args.max_total_mb*1024**2:raise ValueError('Total image byte budget exceeded')
            if sha(raw) in protected['pixels']:raise ValueError('Protected encoded pixels')
            if current_metadata:
                after=json.loads(get(row['source_url'],limit=4*1024**2))
                if (after['properties'].get('geovisio:visibility')!='anyone'
                    or after['properties'].get('updated')!=current_metadata['properties'].get('updated')
                    or after.get('assets')!=current_metadata.get('assets')):
                    raise ValueError('Public source changed during image retrieval')
            import io
            with Image.open(io.BytesIO(raw)) as im:
                if im.width*im.height>70_000_000:raise ValueError('Image pixel budget exceeded')
                im=ImageOps.exif_transpose(im).convert('RGB')
                rgb=sha(str(im.size).encode()+b'\0'+im.tobytes())
                if rgb in protected['pixels']:raise ValueError('Protected decoded pixels')
                display_id=f'B{i:03}';path=args.output/'images'/(display_id+'.jpg');path.parent.mkdir(exist_ok=True);path.write_bytes(raw)
                preview=im.copy();preview.thumbnail((1600,1000));preview_path=args.output/'previews'/(display_id+'.jpg');preview_path.parent.mkdir(exist_ok=True);preview.save(preview_path,quality=90)
                result={**row,'display_id':display_id,'path':str(path.resolve()),'sha256':sha(raw),'rgb_sha256':rgb,'dimensions':list(im.size),'preview_path':str(preview_path.resolve()),'source_asset_url':url,'download_transport':args.download_via_ssh or 'local_https','downloaded_at':datetime.now(timezone.utc).isoformat()};results.append(result)
        except Exception as exc:failures.append({'provider':row['provider'],'source_id':row['source_id'],'error':safe_error(exc)})
        write(args.output/'downloaded-candidates.json',{'samples':results,'failures':failures,'downloaded_bytes':total,'selection_sha256':sha((args.output/'download-selection-frozen.json').read_bytes()),'human_approved':False,'labels_assigned':False})
        print(json.dumps({'downloaded':len(results),'failures':len(failures),'bytes':total}),flush=True)
        if total>args.max_total_mb*1024**2:break


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['anchors','discover','fetch']);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--holdouts',type=Path,nargs='+',required=True);p.add_argument('--providers',nargs='+',choices=['youspeed','federated','mapillary'],default=['youspeed','federated','mapillary'])
    p.add_argument('--token-file',type=Path,default=Path('secret/MAPILLARY-CLIENT-TOKEN.txt'))
    p.add_argument('--overpass-endpoint',default='https://overpass.private.coffee/api/interpreter')
    p.add_argument('--osm-pbf',type=Path)
    p.add_argument('--max-anchors-per-area',type=int,default=16);p.add_argument('--max-queries',type=int,default=24);p.add_argument('--radius',type=float,default=45)
    p.add_argument('--max-images-per-provider',type=int,default=12);p.add_argument('--max-total-mb',type=int,default=250);p.add_argument('--hd',action='store_true')
    p.add_argument('--download-via-ssh',choices=['raphael@141.47.5.55'])
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);globals()[a.command](a)


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Metadata-first external automatic-reference benchmark sample; never training truth."""
import argparse,base64,hashlib,json,math,time
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import httpx
from PIL import Image
from shapely.geometry import shape,Point
import mapbox_vector_tile

ANCHORS=[('Heidelberg',8.694,49.407),('Heilbronn',9.217,49.143),('Aalen',10.094,48.837),('Ulm',9.987,48.400),('Reutlingen',9.213,48.491),('Freiburg',7.850,47.997),('Konstanz',9.173,47.674),('Ravensburg',9.611,47.783),('Offenburg',7.944,48.473),('Villingen',8.459,48.060),('Balingen',8.851,48.273),('Biberach',9.789,48.096),('Schwaebisch-Hall',9.739,49.112),('Ellwangen',10.131,48.962),('Loerrach',7.661,47.614),('Wertheim',9.518,49.759)]
FIELDS='id,geometry,computed_geometry,compass_angle,computed_compass_angle,captured_at,creator,sequence,is_pano,width,height,thumb_original_url,thumb_2048_url'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def distance(a,b):
    p1,p2=map(math.radians,[a[1],b[1]]);dlat=p2-p1;dlon=math.radians(b[0]-a[0]);return 12742000*math.asin(min(1,math.sqrt(math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2)))
def reference_scope(value):
    if value=='object--traffic-sign--front':return 'generic_front_scope_unknown'
    if value=='object--traffic-sign--back':return 'excluded_back'
    if value=='object--traffic-sign--direction-front':return 'excluded_direction'
    if value.startswith(('complementary--','supplementary--')):return 'excluded_supplementary'
    if any(w in value for w in ['direction','lane-layout','lane-assignment','route-marker','exit-number','distance-to','general-information']):return 'excluded_direction_or_panel'
    if value.startswith(('regulatory--','warning--','information--')):return 'classified_primary_candidate'
    return 'other'
def decode_boxes(encoded,width,height):
    tile=mapbox_vector_tile.decode(base64.b64decode(encoded),default_options={'y_coord_down':True});boxes=[]
    for layer in tile.values():
        extent=layer['extent'];assert extent>0
        for f in layer['features']:
            geometry=f['geometry'];assert geometry['type'] in ['Polygon','MultiPolygon']
            rings=geometry['coordinates'] if geometry['type']=='Polygon' else [r for polygon in geometry['coordinates'] for r in polygon]
            points=[(x/extent*width,y/extent*height) for ring in rings for x,y in ring]
            if not points:continue
            box=[max(0,min(x for x,y in points)),max(0,min(y for x,y in points)),min(width,max(x for x,y in points)),min(height,max(y for x,y in points))]
            if box[2]>box[0] and box[3]>box[1]:boxes.append(box)
    return boxes

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--token-file',type=Path,default=Path('secret/MAPILLARY-CLIENT-TOKEN.txt'));p.add_argument('--protection',type=Path,required=True);p.add_argument('--reviewed',type=Path,required=True);p.add_argument('--boundary',type=Path,default=Path('output/mapillary/baden-wuerttemberg/state-boundary.geojson'));args=p.parse_args()
    out=args.output;out.mkdir(exist_ok=False,parents=True);(out/'queries').mkdir();(out/'images').mkdir();(out/'detections').mkdir()
    protected=json.loads(args.protection.read_text())['frames']+json.loads(args.reviewed.read_text())['frames'];coordinates=[f['coordinates'] for f in protected if f.get('coordinates')]
    protected_hashes={f['image_sha256'] for f in protected};protected_sequences={s for f in protected for s in f.get('sequence_ids',[])}
    boundary=json.loads(args.boundary.read_text());boundary=shape(boundary['features'][0]['geometry'] if boundary.get('type')=='FeatureCollection' else boundary['geometry'] if boundary.get('type')=='Feature' else boundary)
    plan={'schema':'mapillary-automatic-reference-plan-v1','anchors':ANCHORS,'target_images':64,'per_anchor':4,'selection':'First100 requested API images within50m of each frozen anchor; metadata-only filters, fixed SHA256 order, at most1 per sequence and25m between selected images.4 per anchor. No selection on detections or model outputs; insufficient quota remains short.','protected_minimum_distance_m':500,'protection_sha256':sha(args.protection),'reviewed_sha256':sha(args.reviewed),'boundary_sha256':sha(args.boundary),'scope_policy':'classified regulatory/warning/information candidates excluding explicit direction/lane/route/supplementary labels. Separate generic-front agreement, not complete sign truth.','annotation_complete':False,'training_allowed':False,'threshold_tuning_allowed':False,'script_sha256':sha(__file__)};write(out/'plan.json',plan)
    token=args.token_file.read_text().strip();headers={'Authorization':'OAuth '+token};selected=[];sequences=set();receipts=[]
    with httpx.Client(timeout=httpx.Timeout(90,connect=30)) as client:
        def graph(endpoint,params):
            for attempt in range(4):
                r=client.get('https://graph.mapillary.com/'+endpoint,params=params,headers=headers)
                if r.status_code==200:return r.json()
                if r.status_code in [429,500,502,503,504] and attempt<3:time.sleep(2**attempt);continue
                raise RuntimeError('Mapillary request failed with HTTP '+str(r.status_code)+'; URL/body suppressed')
        for name,x,y in ANCHORS:
            result=graph('images',{'fields':FIELDS,'lat':y,'lng':x,'radius':50,'limit':100});rows=result.get('data',[]);candidates=[]
            for r in rows:
                coords=(r.get('computed_geometry') or r.get('geometry') or {}).get('coordinates');seq=r.get('sequence');seq=seq.get('id') if isinstance(seq,dict) else seq
                if not coords or not seq or r.get('is_pano') is not False or min(r.get('width',0),r.get('height',0))<768:continue
                if not boundary.covers(Point(coords[:2])) or seq in protected_sequences:continue
                nearest=min(distance(coords,c) for c in coordinates)
                if nearest<500:continue
                # Signed CDN URLs stay local transient metadata, never publication records.
                safe={k:v for k,v in r.items() if not k.endswith('_url')};safe.update(sequence_id=seq,coordinates=coords[:2],nearest_finetuning_or_dev_m=nearest,anchor=name)
                candidates.append((safe,r.get('thumb_original_url') or r.get('thumb_2048_url')))
            candidates.sort(key=lambda item:hashlib.sha256(('mapillary-auto-v1:'+item[0]['id']).encode()).hexdigest())
            chosen=[]
            for safe,url in candidates:
                if safe['sequence_id'] in sequences or not url:continue
                if any(distance(safe['coordinates'],other['metadata']['coordinates'])<25 for other in selected):continue
                chosen.append({'metadata':safe,'url':url});selected.append(chosen[-1]);sequences.add(safe['sequence_id'])
                if len(chosen)==4:break
            receipt={'anchor':name,'returned_images':len(rows),'has_more':bool(result.get('paging',{}).get('next')),'qualified_candidates':len(candidates),'selected_ids':[r['metadata']['id'] for r in chosen]};receipts.append(receipt);write(out/'queries'/(name+'.json'),{'receipt':receipt,'candidates':[r[0] for r in candidates]});print(json.dumps(receipt),flush=True)
        selection=[r['metadata'] for r in selected];write(out/'selection.json',{'plan_sha256':sha(out/'plan.json'),'images':selection,'queries':receipts,'selection_complete_before_detection_queries':True})
        frames=[];errors=[]
        for item in selected:
            meta=item['metadata'];identity=meta['id'];data=[];cursor=None;pages=0
            while True:
                params={'fields':'id,value,geometry,image','limit':1000}
                if cursor:params['after']=cursor
                result=graph(identity+'/detections',params);data.extend(result.get('data',[]));pages+=1
                if not result.get('paging',{}).get('next'):break
                cursor=result.get('paging',{}).get('cursors',{}).get('after') or parse_qs(urlparse(result['paging']['next']).query).get('after',[None])[0]
                if not cursor or pages>=100:raise RuntimeError('Incomplete detection pagination')
            write(out/'detections'/(identity+'.json'),{'data':data,'pages':pages,'pagination_complete':True})
            response=client.get(item['url'])
            if response.status_code!=200:errors.append({'id':identity,'reason':'Image HTTP'+str(response.status_code)});continue
            path=out/'images'/(identity+'.jpg');path.write_bytes(response.content)
            with Image.open(path) as image:
                if image.getexif().get(274,1)!=1:errors.append({'id':identity,'reason':'Unresolved EXIF orientation'});continue
                width,height=image.size
            image_hash=sha(path)
            if image_hash in protected_hashes:raise RuntimeError('Cross-split exact byte duplicate')
            proposals=[]
            for d in data:
                scope=reference_scope(d.get('value',''))
                if scope=='other':continue
                for box in decode_boxes(d['geometry'],width,height):proposals.append({'id':d['id'],'value':d['value'],'scope':scope,'box':box})
            frames.append({'image_id':'mapillary-'+identity,'picture_id':identity,'source_url':'https://www.mapillary.com/app/?pKey='+identity,'author':meta.get('creator'),'coordinates':meta['coordinates'],'sequence_id':meta['sequence_id'],'group_id':'mapillary-sequence:'+meta['sequence_id'],'anchor':meta['anchor'],'captured_at':meta.get('captured_at'),'heading':meta.get('computed_compass_angle',meta.get('compass_angle')),'width':width,'height':height,'source_dimensions':[meta.get('width'),meta.get('height')],'image_path':'images/'+identity+'.jpg','image_sha256':image_hash,'detection_path':'detections/'+identity+'.json','detection_sha256':sha(out/'detections'/(identity+'.json')),'nearest_finetuning_or_dev_m':meta['nearest_finetuning_or_dev_m'],'proposals':proposals,'annotation_complete':False,'human_verified':False,'supervision':'mapillary_automatic_reference','training_allowed':False,'threshold_tuning_allowed':False})
            print(json.dumps({'downloaded':len(frames),'selected':len(selected),'id':identity,'sign_related_proposals':len(proposals)}),flush=True)
    write(out/'manifest.json',{'schema':'mapillary-automatic-reference-sample-v1','plan_sha256':sha(out/'plan.json'),'selection_sha256':sha(out/'selection.json'),'frames':frames,'download_exclusions':errors,'reference_complete':False,'fresh_holdout_claim':False,'pretraining_overlap':'Unknown for upstream pretrained models; current fine-tuning byte/sequence/500m separation checked','limitations':'Metadata-first geographically distributed convenience sample. Automatic segmentation and classified detections can omit, duplicate or misclassify signs. Do not interpret unmatched predictions as verified false positives or agreement as all-visible-sign recall.'})
    write(out/'native-inputs.json',[{'image_id':f['image_id'],'local_path':str((out/f['image_path']).absolute()),'image_sha256':f['image_sha256']} for f in frames]);print(json.dumps({'complete':True,'images':len(frames),'manifest_sha256':sha(out/'manifest.json')}),flush=True)
if __name__=='__main__':main()

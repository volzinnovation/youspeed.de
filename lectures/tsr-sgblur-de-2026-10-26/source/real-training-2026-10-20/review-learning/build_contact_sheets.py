import json,math,hashlib
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
OUT=Path(__file__).resolve().parent
SRC=OUT.parents[1]/'student-collection-2026-10-19/collection'
d=json.loads((SRC/'manifest.json').read_text());rows=[]
for c in d['crops']:
 f=json.loads((SRC/'inbox/detector'/c['picture_id']/'metadata.json').read_text())['original_item'];tags=[t['value']for t in c['osm_tags']if t['key']=='osm|traffic_sign'];names=[t['value']for t in c['osm_tags']if t['key']=='osm|name'];rows.append(dict(c,source_tags=tags,source_names=names,sequence_id=f['collection'],capture_datetime=f['properties']['datetime'],camera_coordinates=f['geometry']['coordinates'],camera=f['properties'].get('pers:interior_orientation',{}),view_azimuth=f['properties'].get('view:azimuth')))
city=sorted([r for r in rows if any(t in['DE:310','DE:311']for t in r['source_tags'])],key=lambda r:(r['capture_datetime'],r['sample_id']));other=sorted([r for r in rows if r not in city],key=lambda r:(r['capture_datetime'],r['sample_id']))
font=lambda n:ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',n)
for kind,items in [('city',city),('other',other)]:
 for idx,r in enumerate(items,1):r['review_index']=f'{kind}-{idx:03d}'
 for start in range(0,len(items),16):
  batch=items[start:start+16];canvas=Image.new('RGB',(1920,math.ceil(len(batch)/4)*280+42),'white');draw=ImageDraw.Draw(canvas);draw.text((8,8),f'ASSISTANT REVIEW / {kind} / SOURCE TAGS ARE NOT TRUTH',fill='black',font=font(23))
  for n,r in enumerate(batch):
   x=n%4*480;y=42+n//4*280
   with Image.open(SRC/r['crop_path'])as im:
    w,h=im.size;r['crop_dimensions']=[w,h];im=im.convert('RGB');scale=min(470/w,210/h);im=im.resize((round(w*scale),round(h*scale)),Image.Resampling.NEAREST);canvas.paste(im,(x+5+(470-im.width)//2,y))
   draw.text((x+5,y+214),r['review_index']+' | '+','.join(r['source_tags']),fill='black',font=font(17));draw.text((x+5,y+235),r['picture_id'][:8]+' / '+r['annotation_id'][:8]+f' | {w}x{h}',fill='black',font=font(16));draw.text((x+5,y+255),r['capture_datetime'][:10]+' | '+','.join(r['source_names'])[:32],fill='black',font=font(16))
  path=OUT/f'{kind}-contact-{start//16+1:02d}.jpg';canvas.save(path,quality=93);print(path,flush=True)
(OUT/'source-inventory.json').write_text(json.dumps(dict(source_manifest=str(SRC/'manifest.json'),source_manifest_sha256=hashlib.sha256((SRC/'manifest.json').read_bytes()).hexdigest(),city=city,other=other),ensure_ascii=False,indent=2)+'\n');print('CITY',len(city),'OTHER',len(other),flush=True)

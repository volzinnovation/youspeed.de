#!/usr/bin/env python3
"""Colour-assisted ROI proposals for visual screening; never training labels."""
from __future__ import annotations

import argparse
import base64
from collections import deque
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def colour_regions(im):
    small = im.copy()
    small.thumbnail((640, 480))
    a = np.asarray(small.convert('RGB')).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = (r > 70) & (g > 55) & (b < np.minimum(r, g)*0.76) & (r > g*1.01) & (g > r*0.5)
    mask[:int(small.height*0.08)] = False
    mask[int(small.height*0.9):] = False
    mask = np.asarray(Image.fromarray((mask*255).astype('uint8')).filter(ImageFilter.MaxFilter(3))) > 0
    pixels = set(zip(*np.nonzero(mask)))
    regions = []
    while pixels:
        point = pixels.pop()
        todo = [point]
        n, ys, xs = 0, [], []
        while todo:
            y, x = todo.pop()
            n += 1
            ys.append(y)
            xs.append(x)
            for p in [(y-1,x),(y+1,x),(y,x-1),(y,x+1)]:
                if p in pixels:
                    pixels.remove(p)
                    todo.append(p)
        x0, y0, x1, y1 = min(xs), min(ys), max(xs)+1, max(ys)+1
        width, height = x1-x0, y1-y0
        if n < 8 or width < 4 or height < 3 or n > small.width*small.height*0.055:
            continue
        aspect, fill = width/height, n/(width*height)
        if not 0.65 < aspect < 4 or fill < 0.18:
            continue
        sx, sy = im.width/small.width, im.height/small.height
        box = [max(0, math.floor((x0-2)*sx)), max(0, math.floor((y0-2)*sy)),
               min(im.width, math.ceil((x1+2)*sx)), min(im.height, math.ceil((y1+2)*sy))]
        score = n*fill/(1+abs(aspect-1.5))
        regions.append({'bbox_xyxy':box, 'source':'colour_ROI_proposal', 'score':round(score, 2)})
    return sorted(regions, key=lambda r:-r['score'])[:5]


def detection_regions(path, width, height):
    if not path.is_file():
        return []
    import mapbox_vector_tile
    def points(v):
        if len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
            yield v
        else:
            for x in v:
                yield from points(x)
    regions = []
    for r in json.loads(path.read_text()).get('data', []):
        if not any(x in r['value'] for x in ['built-up-area','city-limit']):
            continue
        layers = mapbox_vector_tile.decode(base64.b64decode(r['geometry']), default_options={'y_coord_down':True})
        for layer in layers.values():
            pts = [p for f in layer['features'] for p in points(f['geometry']['coordinates'])]
            if not pts:
                continue
            extent = layer['extent']
            box = [max(0, math.floor(min(p[0] for p in pts)/extent*width)-3),
                   max(0, math.floor(min(p[1] for p in pts)/extent*height)-3),
                   min(width, math.ceil(max(p[0] for p in pts)/extent*width)+3),
                   min(height, math.ceil(max(p[1] for p in pts)/extent*height)+3)]
            regions.append({'bbox_xyxy':box, 'source':'Mapillary_detection_hint', 'source_detection_id':r['id'],
                            'source_detection_value':r['value'], 'score':1e6})
    return regions


def main(args):
    rows = json.loads(args.candidates.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    font = None
    for name in ['DejaVuSans.ttf','/System/Library/Fonts/Supplemental/Arial.ttf']:
        try:
            font = ImageFont.truetype(name, 16)
            break
        except OSError:
            pass
    if font is None:
        font = ImageFont.load_default()
    proposals = []
    for index, row in enumerate(rows):
        im = Image.open(row['preview_path']).convert('RGB')
        regions = detection_regions(args.detections/(row['image_id']+'.json'), *im.size)+colour_regions(im)
        unique = []
        for region in regions:
            box = region['bbox_xyxy']
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            if any(abs(sum(box[::2])-sum(r['bbox_xyxy'][::2])) < 16 and
                   abs(sum(box[1::2])-sum(r['bbox_xyxy'][1::2])) < 16 for r in unique):
                continue
            unique.append(region)
        row.update(review_index=index, preview_dimensions=list(im.size), roi_proposals=unique[:5])
        proposals.append(row)
    (args.output/'roi-proposals.json').write_text(json.dumps(proposals, indent=2, ensure_ascii=False)+'\n')
    for start in range(0, len(rows), 16):
        canvas = Image.new('RGB', (1600, 1200), '#eceeea')
        d = ImageDraw.Draw(canvas)
        for j, row in enumerate(proposals[start:start+16]):
            x, y = j%4*400, j//4*300
            im = Image.open(row['preview_path']).convert('RGB')
            v = im.copy()
            v.thumbnail((190, 160))
            canvas.paste(v, (x+5, y+50))
            d.text((x+5, y+3), str(row['review_index'])+' '+row['registry_record']['municipality_name'][:22], font=font, fill='black')
            d.text((x+5, y+24), row['image_id']+' '+row['registry_record']['sign_code'], font=font, fill='black')
            for k, region in enumerate(row['roi_proposals'][:4]):
                crop = im.crop(region['bbox_xyxy'])
                crop.thumbnail((94, 100))
                rx, ry = x+200+(k%2)*99, y+55+(k//2)*118
                canvas.paste(crop, (rx, ry))
                d.text((rx, ry-20), str(k)+' '+('MLY' if region['source'].startswith('Mapillary') else 'ROI'), font=font, fill='black')
            d.text((x+5,y+270), 'PANO' if row['image_metadata'].get('is_pano') else '2D',font=font,fill='black')
        canvas.save(args.output/('screen-'+str(start//16).zfill(2)+'.jpg'), quality=91)
    print(json.dumps({'preview_images':len(proposals),'review_sheets':math.ceil(len(rows)/16),
                      'images_with_ROI':sum(bool(r['roi_proposals']) for r in proposals)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidates', type=Path, required=True)
    p.add_argument('--detections', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    main(p.parse_args())

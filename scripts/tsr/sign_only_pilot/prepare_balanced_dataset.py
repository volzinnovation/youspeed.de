#!/usr/bin/env python3
"""Apply targeted corrections and freeze paired training views without held-out pixels."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from PIL import Image
import yaml
import train_latest as base
import mobile_replay as phone
from balanced_views import views_for,paired_schedules

ROOT=Path('/job/balanced-v1');OLD=Path('/job/expanded-v1/dataset')


def main():
    parent=OLD/'reviews/detector-expanded-2026-11-15/manifest.json'
    assert base.sha(parent)=='818457fffae759e6366fbc4946a40bf1386f51c0a5e326143904247a1488c71e'
    manifest=json.loads(parent.read_text());base.partition_manifest(manifest)
    decisions=json.loads((ROOT/'negative-review/proposal-decisions.json').read_text())['cases']+json.loads((ROOT/'negative-review/empty-decisions.json').read_text())['frames']
    excluded={r['picture_id'] for r in decisions if r['decision']=='exclude_frame_unresolved'}
    added={}
    for r in decisions:
        if r['decision']=='add_primary_sign':added.setdefault(r['picture_id'],[]).extend(r['corrected_boxes_xyxy'])
    assert not (set(added)&excluded)
    out=ROOT/'data';out.mkdir(exist_ok=False);(out/'labels/train').mkdir(parents=True);(out/'images/train').mkdir(parents=True)
    corrected=[];excluded_rows=[];train=[]
    for frame in manifest['frames']:
        if frame['split']!='train':continue
        if frame['picture_id'] in excluded:excluded_rows.append(frame);continue
        image=OLD/frame['image_path'];label=OLD/frame['label_path']
        assert base.sha(label)==frame['label_sha256']
        boxes=base.read_yolo_labels(label,frame['width'],frame['height'])
        if frame['picture_id'] in added:
            assert not boxes;boxes=added[frame['picture_id']]
        assert all(0<=b[0]<b[2]<=frame['width'] and 0<=b[1]<b[3]<=frame['height'] for b in boxes)
        row={**frame,'boxes_xyxy':boxes,'label_correction':'assistant_targeted_visual_review' if frame['picture_id'] in added else 'unchanged'}
        if frame['picture_id'] in added:row.update(annotation_complete=False,human_verified=False,pseudo_label_status='pseudo_positive')
        corrected.append(row);train.append((row,image))
    base.write(out/'corrected-sources.json',{'parent_manifest_sha256':base.sha(parent),'parent_dataset_revision':'5e51cd9333ec07a88d212de479d1d2139f007495','frames':corrected,'excluded_frames':excluded_rows,'review_claim':'Targeted corrections; unreviewed content remains weak. No exhaustive negative certification.'})
    views=[]
    def render_parent(item):
        frame,path=item;assert base.sha(path)==frame['image_sha256']
        with Image.open(path) as source:
            assert source.size==(frame['width'],frame['height']) and source.getexif().get(274,1)==1
            raster=source.convert('RGB')
        rows=views_for(*raster.size,frame['boxes_xyxy'])
        for j,v in enumerate(rows):
            stem=frame['picture_id']+'-'+str(j);target=out/'images/train'/f'{stem}.png';label=out/'labels/train'/f'{stem}.txt'
            phone.render(raster,v['window']).save(target,compress_level=1)
            label.write_text(''.join('0 %.9f %.9f %.9f %.9f\n'%((b[0]+b[2])/2048,(b[1]+b[3])/2048,(b[2]-b[0])/1024,(b[3]-b[1])/1024) for b in v['boxes']))
            v.update(view_id=stem,picture_id=frame['picture_id'],group_id=frame['group_id'],parent_positive=bool(frame['boxes_xyxy']),source_sha256=frame['image_sha256'],image_path=str(target),image_sha256=base.sha(target),label_sha256=base.sha(label))
        return rows
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,rows in enumerate(pool.map(render_parent,train)):
            views.extend(rows)
            if i%100==0:print(json.dumps({'rendered_sources':i+1,'views':len(views)}),flush=True)
    schedules,pools=paired_schedules(views)
    sampled={r[a] for epoch in schedules for r in epoch for a in ['phone','mixed']}
    views=[v for v in views if v['view_id'] in sampled]
    base.write(out/'views.json',views);base.write(out/'schedules.json',schedules)
    (out/'train.txt').write_text('\n'.join(v['image_path'] for v in views)+'\n')
    val=[]
    for f in manifest['frames']:
        if f['split']!='validation':continue
        for folder,suffix,key in [('images','.jpg','image_path'),('labels','.txt','label_path')]:
            dest=out/folder/'val'/(f['picture_id']+suffix);dest.parent.mkdir(exist_ok=True,parents=True);dest.symlink_to(OLD/f[key])
        val.append(str(out/'images/val'/(f['picture_id']+'.jpg')))
    (out/'val.txt').write_text('\n'.join(val)+'\n')
    (out/'data.yaml').write_text(yaml.safe_dump({'path':str(out),'train':'train.txt','val':'val.txt','names':{0:'sign'}}))
    # Source pool inherits the previously verified geographic exclusion. Verify no identity overlap again.
    valtest=[f for f in manifest['frames'] if f['split']!='train']
    for field in ['picture_id','image_sha256','group_id']:
        assert not ({f[field] for f in corrected}&{f[field] for f in valtest})
    counts={'eligible_sources':len(corrected),'excluded_sources':len(excluded_rows),'boxes':sum(len(f['boxes_xyxy']) for f in corrected),'corrected_sources':len(added),'added_boxes':sum(map(len,added.values())),'positive_sources':sum(bool(f['boxes_xyxy']) for f in corrected),'view_pool':len(views),'parent_pools':pools,'epochs':40,'draws_per_epoch':1024,'unique_sampled_parents':len({r['picture_id'] for e in schedules for r in e}),'positive_draw_fraction':.75,'small_tile_draw_fraction_mixed':.5,'renderer':'Phone crop geometry with Pillow bilinear approximation; not Swift pixel identity','native_tile_flag':False,'epoch_semantics':'1024 paired balanced draws, not one full-source pass'}
    for name in ['corrected-sources.json','views.json','schedules.json','data.yaml']:counts[name+'_sha256']=base.sha(out/name)
    base.write(out/'summary.json',counts);print(json.dumps(counts),flush=True)

if __name__=='__main__':main()

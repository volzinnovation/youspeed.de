"""Materialize the assistant's actual70-crop visual review. Source files stay untouched."""
import csv,hashlib,json
from pathlib import Path
from collections import Counter
OUT=Path(__file__).resolve().parent
D=json.loads((OUT/'source-inventory.json').read_text());SRC=Path(D['source_manifest']).parent
REMOTE=Path('/home/raphael/youspeed-lecture-download-test-20261020-f1a2266d/run-fixed/lectures/tsr-sgblur-de-2026-10-26/praktikum/data/collection')
GROUPS={
 '2026-09-05':('learning-marxzell-20260905-20260908','train'),
 '2026-09-08':('learning-marxzell-20260905-20260908','train'),
 '2026-09-09':('learning-murgtal-20260909-20261013','train'),
 '2026-10-13':('learning-murgtal-20260909-20261013','train'),
 '2026-10-14':('reserved-20261014-20261017-baden-overlap','reserved'),
 '2026-10-17':('reserved-20261014-20261017-baden-overlap','reserved'),
 '2026-10-15':('learning-gernsbach-loffenau-20261015','val'),
 '2026-10-19':('learning-herrenalb-dobel-20261019','train')}
REJECT={1:('reject_resolution','28x18pixels: class/absence of cancellation stripe not reliable.'),22:('duplicate_annotation','Same source picture and same Althof exit sign as city-021; keep larger complete city-021 only.'),45:('reject_resolution','34x25pixels with severe block blur; class cannot be assigned reliably from crop.'),66:('reject_incomplete_ambiguous','27x22crop contains incomplete town panel and partial red diagonal; sourceDE310 is not trustworthy, no reliable complete target.'),69:('reject_resolution','19x13pixels; no reliable town-exit label from visible detail.'),70:('reject_resolution','27x17pixels; class/box is too ambiguous for primary reviewed training.')}
rows=[]
for c in D['city']:
 i=int(c['review_index'].split('-')[1]);path=SRC/c['crop_path'];got=hashlib.sha256(path.read_bytes()).hexdigest()
 if got!=c['crop_sha256']:raise ValueError('source crop changed:'+str(path))
 label='city:end'if'DE:311'in c['source_tags']else'city:start'
 reason='Yellow town-entry rectangle without cancellation stripe is visibly identifiable.'if label=='city:start'else'Town-exit board has visible diagonal cancellation stripe.'
 box='usable_complete'if min(c['crop_dimensions'])>=48else'usable_small_or_tight_class_visible'
 if i==53:label='city:end';reason='Corrected sourceDE310: crop visibly contains a diagonal red cancellation stripe across the lower town name.'
 if i in[2,3]:reason+=' Source place-name Frankfurt am Main is wrong for city-002; visible name is Marxzell.'if i==2 else''
 group,subset=GROUPS[c['capture_datetime'][:10]];decision='accept'
 if i in REJECT:box,reason=REJECT[i];label=None;decision='reject';subset='reject'
 rows.append(dict(review_index=c['review_index'],sample_id=c['sample_id'],picture_id=c['picture_id'],annotation_id=c['annotation_id'],sequence_id=c['sequence_id'],label=label,decision=decision,reason=reason,box_quality=box,group_id=group,subset=subset,crop_absolute_path=str(REMOTE/c['crop_path']),crop_local_path=str(path.resolve()),crop_sha256=c['crop_sha256'],crop_dimensions=c['crop_dimensions'],source_osm_tags=c['osm_tags'],capture_datetime=c['capture_datetime'],camera_coordinates=c['camera_coordinates'],reviewer_type='assistant_visual_review',review_status='assistant_review_complete_not_human_ground_truth'))
base=dict(schema_version='youspeed-assistant-city-review-v1',source_manifest=str(SRC/'manifest.json'),source_manifest_sha256=D['source_manifest_sha256'],dataset_revision='6837ae4fae0d1d216612afa739c9dfefd6b277ab',source_files_changed=False,human_approval_fields_changed=False,review_method='All70sourceDE310/311crops viewed on5indexedcontact sheets before model metrics. Clearstripecorrectioncity053; ambiguous/small/duplicate exclusions recorded.',grouping_policy='WholecaptureUTCdays preserved; cross-day cityframes within300m merged conservatively, including MarxzellSep5/Sep8(168m), repeatedMurgtalSep9/Oct13(1.9m), BadenBadenOct14/Oct17(85.5m). These are conservative route/site groups, not proven independent journeys.',subset_assignment_policy='Root fixed BEFORE metrics: Oct15corridor validation;3other eligiblecorridor groups training; Oct14andlinkedOct17 reserved. Not a seed reroll. External/ownadditionaltest sources are absent.',group_definitions=[dict(group_id=g,subset=s,capture_days=sorted(d for d,p in GROUPS.items()if p==(g,s)))for g,s in sorted(set(GROUPS.values()))],counts=dict(source_crops=len(rows),accepted=sum(r['decision']=='accept'for r in rows),rejected=sum(r['decision']=='reject'for r in rows),by_subset={s:dict(Counter(r['label']for r in rows if r['subset']==s))for s in['train','val','reserved','reject']},route_groups_total=5,train_groups=3,val_groups=1,reserved_groups=1),rows=rows)
def write(name,d):
 d['lock_sha256']=hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
write('city-review.json',base)
trainval=[r for r in rows if r['subset']in['train','val']]
write('city-train-val.json',dict(schema_version='youspeed-assistant-city-trainval-v1',source_review_file='city-review.json',source_review_sha256=hashlib.sha256((OUT/'city-review.json').read_bytes()).hexdigest(),source_manifest_sha256=D['source_manifest_sha256'],reviewer_type='assistant_visual_review',counts=base['counts'],rows=trainval,note='Exploratory assistant-reviewed training/validation; no human approval or production ground truth claimed. No test sources included.'))
with(OUT/'city-review.csv').open('w',newline='')as f:
 cols=['review_index','sample_id','picture_id','annotation_id','sequence_id','label','decision','reason','box_quality','group_id','subset','crop_absolute_path','crop_sha256'];w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
# Entire100frame mapping uses the same whole-day/corridor decisions for both model tasks.
frame_rows=[]
for p in sorted((SRC/'inbox/detector').glob('*/metadata.json')):
 d=json.loads(p.read_text());f=d['original_item'];it=d['item'];day=f['properties']['datetime'][:10];group,subset=GROUPS.get(day,('reserved-unreviewed-day-'+day,'reserved'))
 approved=[r['sample_id']for r in rows if r['picture_id']==f['id']and r['decision']=='accept']
 frame_rows.append(dict(picture_id=f['id'],sequence_id=f['collection'],capture_datetime=f['properties']['datetime'],group_id=group,subset=subset,accepted_city_sample_ids=approved,image_absolute_path=str(REMOTE/it['bundle_path']/'image.png'),image_sha256=it['image_sha256'],all_visible_object_annotation_complete=False))
write('learning-frame-split.json',dict(schema_version='youspeed-shared-learning-frame-split-v1',source_review_file='city-review.json',source_review_sha256=hashlib.sha256((OUT/'city-review.json').read_bytes()).hexdigest(),rows=frame_rows,counts=dict(Counter(r['subset']for r in frame_rows)),note='Assignment only, not full detector ground truth. Frames require separate completeboxreview; rejected cropdoesnotautomaticallyrejectotherobjects.'))
sg=OUT.parent/'sgblur/review-candidates.json'
if sg.exists():
 ids={r['picture_id']for r in json.loads(sg.read_text())['frames']};selected=[r for r in frame_rows if r['picture_id']in ids];write('sgblur20-shared-split.json',dict(schema_version='youspeed-sgblur20-shared-split-v1',source_sgblur_review_file=str(sg),source_sgblur_review_sha256=hashlib.sha256(sg.read_bytes()).hexdigest(),source_city_review_sha256=hashlib.sha256((OUT/'city-review.json').read_bytes()).hexdigest(),rows=selected,counts=dict(Counter(r['subset']for r in selected)),all_visible_object_annotation_complete=False))
print(json.dumps(base['counts'],indent=2));print('SG20',Counter(r['subset']for r in selected))
for name in['city-review.json','city-train-val.json','learning-frame-split.json','sgblur20-shared-split.json']:print(name,hashlib.sha256((OUT/name).read_bytes()).hexdigest())

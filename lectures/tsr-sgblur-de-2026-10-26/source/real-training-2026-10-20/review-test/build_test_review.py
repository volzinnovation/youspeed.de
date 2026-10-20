"""Freeze assistant visual review before any candidate predictions are inspected."""
from pathlib import Path
from datetime import datetime, timezone
import json,hashlib
HERE=Path(__file__).resolve().parent
B=HERE.parents[1]
REMOTE=Path('/home/raphael/youspeed-lecture-download-test-20261020-f1a2266d/run-fixed/lectures/tsr-sgblur-de-2026-10-26/praktikum/data/teacher-reserved')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ext=B/'external-holdout-2026-10-20';em=json.loads((ext/'final-audit/manifest.json').read_text());rows=[];audit=[]
for i,r in enumerate(em['records']):
 label=r['local_class_proposal']['model_label'];cid=r['candidate_id'];a=r['assets'];crop=ext/a['crop']['package_path'];im=ext/a['input_image']['package_path']
 assert sha(crop)==a['crop']['sha256'] and sha(im)==a['input_image']['sha256']
 row=dict(sample_id=cid,label=label,group_id=r['conservative_split_group_id'],site_id=r['site_candidate_id'],subset='projected' if 'projection'in a else 'native',crop_absolute_path=str(REMOTE/'panoramax-externe-testkandidaten-2026-10-20/inbox/classifier'/f'{cid}.png'),crop_sha256=sha(crop),input_image_absolute_path=str(REMOTE/'panoramax-externe-testkandidaten-2026-10-20/inbox/detector'/cid/('image'+im.suffix)),input_sha256=sha(im),bbox_xyxy=r['input_bbox_xyxy'],picture_id=r['picture_id'],sequence_id=r['sequence_id'],source_url=r['source_url'],review_type='assistant_visual',human_reviewed=False,all_objects_complete=False)
 row['include_primary']=i!=1
 row['review_reason']='Two-part exit layout, but no reliably visible cancellation stripe; excluded from primary metrics' if i==1 else ('Yellow town name sign with black border; no arrow or cancellation stripe' if label=='city:start' else 'Town exit layout and visible cancellation stripe')
 audit.append(dict(index=i,**row))
 if row['include_primary']: rows.append(row)
own=B/'holdout-2026-10-20/collection';om=json.loads((own/'manifest.json').read_text())
labels={0:'hazard:rocks',1:'hazard:intersection',2:'give_way',3:'give_way',6:'city:start',9:'priority:start',12:'priority:start',13:'traffic_signal',14:'pedestrian_bicycle:start',15:'maxspeed:50',19:'arrow_right_down',20:'give_way',21:'no_parking',23:'no_parking',34:'parking',35:'parking',36:'bus:start',37:'give_way',40:'give_way',41:'give_way',43:'no_overtaking',45:'no_overtaking',48:'arrow_through',50:'no_overtaking',54:'hazard:gravel',55:'maxspeed:50',56:'give_way',57:'priority:start',60:'maxspeed:50',62:'maxspeed:30',65:'maxspeed:80',67:'maxspeed:50',75:'hazard:gravel'}
unsupported90={8,11,44,46,47,49,51,52}
for i,c in enumerate(om['crops']):
 item=next(x for x in om['items'] if x['picture_id']==c['picture_id']);crop=own/c['crop_path'];im=own/item['bundle_path']/'image.png'
 assert sha(crop)==c['crop_sha256'] and sha(im)==item['image_sha256']
 row=dict(sample_id=c['sample_id'],label=labels.get(i),group_id=c['group_id'],site_id=c['picture_id']+':'+c['annotation_id'],subset='own_native',crop_absolute_path=str(REMOTE/'panoramax-testkandidaten-2026-10-20/collection'/c['crop_path']),crop_sha256=sha(crop),input_image_absolute_path=str(REMOTE/'panoramax-testkandidaten-2026-10-20/collection'/item['bundle_path']/'image.png'),input_sha256=sha(im),bbox_xyxy=c['bbox_xyxy'],picture_id=c['picture_id'],sequence_id=item['sequence_id'],source_url=item['source_url'],review_type='assistant_visual',human_reviewed=False,all_objects_complete=False)
 row['include_primary']=i in labels
 row['review_reason']='Recognizable sign and complete enough primary shape/symbol' if i in labels else ('Speed90 class absent from fixed136 taxonomy' if i in unsupported90 else 'Ambiguous taxonomy, advertisement, tiny/unreadable or incomplete crop; excluded conservatively')
 if i==6:row.update(site_id='birkenfeld-entry-8.64536-48.87639',group_id='own-drive-2026-10-14-reserved',review_reason='Birkenfeld Enzkreis entry; keep all possibly common-drive learning sequences out of training')
 audit.append(dict(collection='own39',index=i,**row))
 if row['include_primary']:rows.append(row)
record=dict(schema='assistant-reviewed-prospective-test-v1',reviewed_at=datetime.now(timezone.utc).isoformat(),reviewer='Codex root visual inspection, not human approval',frozen_before_candidate_predictions=True,human_approved=False,role='test_only_no_training_or_selection',native_and_projection_report_separately=True,partial_annotation_note='Target boxes only. May evaluate target recall; cannot infer full-image detection precision or AP from these annotations.',source_manifests={str(ext/'final-audit/manifest.json'):sha(ext/'final-audit/manifest.json'),str(own/'manifest.json'):sha(own/'manifest.json')},rows=rows,review_audit=audit)
p=HERE/'reviewed-test.json';p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');print(p,sha(p));print('accepted',len(rows),'all reviewed',len(audit))

"""Verify recorded predictions and package compact experiment evidence, without inference."""
from pathlib import Path
from datetime import datetime,timezone
import csv,gzip,hashlib,json,re,shutil,zipfile
ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'.build/real-training-2026-10-20'
DEST=ROOT/'source/real-training-2026-10-20'
REPORT=ROOT/'TRAININGSERGEBNISSE-2026-10-20.md'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
# Sync completed compact records. Weights/full source images remain separate.
for kind in ['review-learning','review-test','sgblur']:
 for p in (BUILD/kind).rglob('*'):
  if not p.is_file():continue
  if p.suffix not in ['.json','.csv','.py','.md','.txt','.log'] and not('pipeline-fixed-city-v1' in p.parts and p.suffix=='.png'):continue
  q=DEST/kind/p.relative_to(BUILD/kind);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
for p in (BUILD/'tsr/results').rglob('*'):
 if p.is_file()and p.suffix in ['.json','.csv','.gz','.md','.log']:
  q=DEST/'tsr'/p.relative_to(BUILD/'tsr/results');q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
for p in (BUILD/'tsr').glob('*.py'):
 q=DEST/'tsr/code'/p.name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
for p in (BUILD/'tsr/code').iterdir():
 if p.is_file():shutil.copyfile(p,DEST/'tsr/code'/p.name)
for n in ['error-analysis.jpg','error-analysis.json','method-peer-audit.json','old-review-notes.json']:
 shutil.copyfile(BUILD/'tsr'/n,DEST/'tsr'/n)
raw=gzip.decompress((DEST/'tsr/records/dataset-manifest.json.gz').read_bytes())
assert hashlib.sha256(raw).hexdigest()=='e67c8699a705371b79d68ea534371e2ae0c5e74ce83be7fd62fce671a1cac9eb'
assert len(json.loads(raw)['samples'])==19755
summary=read(DEST/'tsr/results-summary.json');old=read(DEST/'tsr/reports/retrospective-old/metrics.json')
oldrows=list(csv.DictReader((DEST/'tsr/reports/retrospective-old/predictions.csv').open()))
assert len(oldrows)==3029
assert sum(r['true_label']==r['baseline_label']for r in oldrows)==3015
assert sum(r['true_label']==r['candidate_label']for r in oldrows)==3010
oldclasses=list(zip(old['baseline']['per_class'][:134],old['candidate']['per_class'][:134]))
assert all(a['support']>0 for a,b in oldclasses)
assert sum(b['f1']<a['f1']-1e-12 for a,b in oldclasses)==20
assert sum(b['recall']<a['recall']-1e-12 for a,b in oldclasses)==11
joint=list(csv.DictReader((DEST/'tsr/reports/joint-final/predictions.csv').open()))
assert len(joint)==3071 and len({r['sample_id']for r in joint})==3071
assert sum(not r['true_label'].startswith('city:')and r['candidate_label'].startswith('city:')for r in joint)==0
sg=read(DEST/'sgblur/results-analysis.json');assert(sg['overall']['baseline_matched'],sg['overall']['candidate_matched'],sg['overall']['lost'])==(27,35,0)
pipe_path=DEST/'sgblur/pipeline-fixed-city-v1/output/results-01/pipeline-results.json';pipe=read(pipe_path)
assert pipe['gt_crops_used_for_classification'] is False
for arm in pipe['arms'].values():
 for f in arm['full_frames_and_all_post_nms_detections']:
  for pred in f['detections']:
   if pred.get('crop_path'):assert sha(pipe_path.parent/pred['crop_path'])==pred['crop_sha256']
assert pipe['arms']['candidate_pair']['summary']['correct_city_known_targets']==9
assert pipe['arms']['candidate_pair']['summary']['detector_misses']==6
assert pipe['arms']['candidate_pair']['summary']['detected_but_wrong_tsr_class']==0
for local,expected in [(BUILD/'tsr/results/best.pt',summary['candidate_sha256']),(BUILD/'sgblur/run-01/best.pt','63cebe1bc4372ccdd9a4f3bdb525ed6a8094d8b05f0a27a39dfbb46fa0e1b5dd')]:assert sha(local)==expected
text=REPORT.read_text();assert not any(x in text for x in ['Noch einzutragen','Ergebnisse noch offen','TODO','TBD'])
for link in re.findall(r'\]\(([^)]+)\)',text):
 if not link.startswith(('https://','http://')):assert(ROOT/link).exists(),link
# Publish a compact read-only result summary inside the repository, not on the Hub.
write(DEST/'SUMMARY.json',dict(schema_version='tsr-sgblur-real-training-results-v1',recorded_at=datetime.now(timezone.utc).isoformat(),server='wingki01',login='raphael',gpu='Two NVIDIA RTX A5000, host indices0 and2',epochs_each=20,human_reviewed=False,tsr=summary,sgblur=dict(overall=sg['overall'],city=sg['city_all'],old_sign=sg['old_sign_all'],classes={k:sg['by_verified_subclass_label'][k]for k in ['city:start','city:end']},selected_epoch=9,full_scene_precision_ap_evaluable=False,unmasked_face_plate_evaluable=False),pipeline=dict(candidate=pipe['arms']['candidate_pair']['summary'],by_label=pipe['arms']['candidate_pair']['by_label'],baseline=pipe['arms']['baseline_pair']['summary'],actual_detected_crops=True),production_model_accepted=False,no_tuning_after_test=True))
write(DEST/'server-final-state.json',dict(recorded_date='2026-10-20',server='wingki01',all_four_checked_containers_exited_0=True,gpu_snapshot={'0':{'model':'RTX A5000','used_mib':419,'utilization_percent':0},'1':{'model':'RTX PRO6000 Blackwell','used_mib':1434,'utilization_percent':0},'2':{'model':'RTX A5000','used_mib':499,'utilization_percent':0}},production_tsr_baseline_sha256='f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7',production_tsr_baseline_unchanged=True,note='Read-only final SSH snapshot. Pipeline and component receipts include exact timestamps and container/image identities.'))
shutil.copyfile(Path(__file__),DEST/'finalize_evidence.py')
files=[dict(path=p.relative_to(DEST).as_posix(),bytes=p.stat().st_size,sha256=sha(p))for p in sorted(DEST.rglob('*'))if p.is_file()and p.name!='MANIFEST.json']
write(DEST/'MANIFEST.json',dict(schema_version='real-training-compact-evidence-v1',report_path='../../TRAININGSERGEBNISSE-2026-10-20.md',report_sha256=sha(REPORT),excludes='Original full HD images and model weights are not duplicated here. All59actual pipeline sign crops are included.',files=files))
archive=ROOT/'output/trainingsbelege-2026-10-20.zip'
entries={REPORT.name:REPORT,'LICENSE-CODE-AGPL-3.0.txt':ROOT.parents[1]/'LICENSE'}
assert entries['LICENSE-CODE-AGPL-3.0.txt'].exists()
for p in sorted(DEST.rglob('*')):
 if p.is_file():entries[p.relative_to(ROOT).as_posix()]=p
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
 for name,p in entries.items():
  info=zipfile.ZipInfo(name,date_time=(2026,10,20,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16;z.writestr(info,p.read_bytes())
with zipfile.ZipFile(archive)as z:
 assert z.testzip()is None
 for name,p in entries.items():assert hashlib.sha256(z.read(name)).hexdigest()==sha(p)
print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,sha256=sha(archive),files=len(entries),all_json=sum(1 for p in DEST.rglob('*.json')),report_links='PASS',prediction_totals='PASS',zip_crc_and_every_entry_sha256='PASS'),ensure_ascii=False))

#!/usr/bin/env python3
"""Explicit isolated native device run; production Proxy/VFS app tests are separate."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import uuid


def require(condition,detail):
    if not condition:raise RuntimeError(detail)


def main():
    p=argparse.ArgumentParser();p.add_argument('--device',required=True);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--mode',choices=['legacy-packed','legacy-sqlite','context-packed','pool-context-packed'],required=True);p.add_argument('--database',required=True);p.add_argument('--geometry',default='-');p.add_argument('--queries',required=True)
    p.add_argument('--pool-readers',type=int,default=8)
    p.add_argument('--binary',type=Path);p.add_argument('--stage',action='append',default=[],help='LOCAL_FILE=REMOTE_PATH');p.add_argument('--reference',type=Path);a=p.parse_args()
    results=a.workspace.resolve()/'results';results.mkdir(parents=True,exist_ok=True);nonce=str(uuid.uuid4());prefix=f'android-{a.mode}-{nonce[:8]}';adb=['adb','-s',a.device];root='/data/local/tmp/youspeed-packed-runtime'
    subprocess.run(adb+['shell','mkdir','-p',root],check=True,timeout=30)
    if a.binary:
        subprocess.run(adb+['push',str(a.binary.resolve()),root+'/packed-runtime-bench'],check=True,timeout=75);subprocess.run(adb+['shell','chmod','755',root+'/packed-runtime-bench'],check=True,timeout=30)
    for item in a.stage:
        local,remote=item.split('=',1);subprocess.run(adb+['push',str(Path(local).resolve()),remote],check=True,timeout=180)
    metadata={}
    for key,prop in [('model','ro.product.model'),('sdk','ro.build.version.sdk'),('abi','ro.product.cpu.abi')]:metadata[key]=subprocess.check_output(adb+['shell','getprop',prop],text=True,timeout=30).strip()
    command=[root+'/packed-runtime-bench',a.mode,a.database,a.geometry,a.queries,str(a.pool_readers if a.mode=='pool-context-packed' else 3)];received=subprocess.run(adb+['shell',shlex.join(command)],capture_output=True,text=True,timeout=300);report=json.loads(received.stdout);report['device']=metadata;report['run_id']=nonce
    path=results/(prefix+'-report.json');path.write_text(json.dumps(report,indent=2)+'\n')
    require(report.get('overall_success') is True,json.dumps(report))
    require(received.returncode==0,'Native benchmark process failed after producing a report')
    if a.reference:
        reference=json.loads(a.reference.read_text());require(report['query_results']==reference['query_results'],'Original source SQL result mismatch');require(report['result_fnv1a64']==reference['result_fnv1a64'],'Source result digest mismatch')
    print(json.dumps({'report':str(path),'mode':a.mode,'memory_gate_pass':report['memory_gate_pass'],'incremental_rss_bytes':report['incremental_rss_bytes']},indent=2))


if __name__=='__main__':main()

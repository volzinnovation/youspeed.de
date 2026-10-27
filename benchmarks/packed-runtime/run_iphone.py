#!/usr/bin/env python3
"""Explicitly stage/run the isolated benchmark after phone coordination."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

APP='de.youspeed.StoragePrototypeBenchmark'


def require(condition,detail):
    if not condition:raise RuntimeError(detail)


def main():
    p=argparse.ArgumentParser();p.add_argument('--device',required=True);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--mode',choices=['legacy-packed','legacy-sqlite','context-packed','pool-context-packed','nodes-packed'],required=True)
    p.add_argument('--pool-readers',type=int,default=8)
    p.add_argument('--database',required=True,help='Path inside Documents; old prototype normally data/runtime.pack or data/runtime.sqlite')
    p.add_argument('--geometry',default='-');p.add_argument('--queries',default='data/queries.csv')
    p.add_argument('--stage',action='append',default=[],help='LOCAL_FILE=REMOTE_DOCUMENTS_PATH; repeat only files needing staging')
    p.add_argument('--install-app',type=Path);p.add_argument('--reference',type=Path);a=p.parse_args()
    results=a.workspace.resolve()/'results';results.mkdir(parents=True,exist_ok=True);nonce=str(uuid.uuid4());prefix=f'iphone-{a.mode}-{nonce[:8]}'
    base=['xcrun','devicectl','--timeout','60','--quiet'];domain=['--device',a.device,'--domain-type','appDataContainer','--domain-identifier',APP]
    def command(args,receipt,timeout=75):
        # Keep tool options before the application's "--" argument delimiter.
        arguments=args[:3]+['--json-output',str(results/(prefix+'-'+receipt+'.json'))]+args[3:]
        return subprocess.run(base+arguments,check=True,timeout=timeout)
    if a.install_app:command(['device','install','app','--device',a.device,str(a.install_app.resolve())],'install')
    for index,spec in enumerate(a.stage):
        local,remote=spec.split('=',1);command(['device','copy','to',*domain,'--source',str(Path(local).resolve()),'--destination',remote],f'stage-{index}',timeout=75)
    config={'mode':a.mode,'database':a.database,'geometry':a.geometry,'queries':a.queries,'repetitions':a.pool_readers if a.mode=='pool-context-packed' else 3,'rss_gate_bytes':64*1024*1024,'run_id':nonce}
    config_path=results/(prefix+'-configuration.json');config_path.write_text(json.dumps(config,indent=2)+'\n')
    command(['device','copy','to',*domain,'--source',str(config_path),'--destination','Documents/data/packed-benchmark.json'],'config')
    command(['device','process','launch','--device',a.device,'--terminate-existing',APP,'--','--config','data/packed-benchmark.json'],'launch')
    report_path=results/(prefix+'-report.json');deadline=time.monotonic()+300;last=''
    while time.monotonic()<deadline:
        received=subprocess.run(base+['device','copy','from',*domain,'--source','Documents/packed-runtime-report.json','--destination',str(report_path)],capture_output=True,text=True,timeout=75)
        last=received.stderr[-1000:]
        if received.returncode==0:
            report=json.loads(report_path.read_text())
            if report.get('configuration',{}).get('run_id')==nonce:
                if not report.get('overall_success'):raise RuntimeError(json.dumps(report))
                if a.reference:
                    reference=json.loads(a.reference.read_text())
                    if a.mode=='nodes-packed':require(report['node_roundtrip']==reference,'Original source node metadata mismatch')
                    else:
                        require(report['query_results']==reference['query_results'],'Original source SQL result mismatch')
                        require(report['result_fnv1a64']==reference['result_fnv1a64'],'Source result digest mismatch')
                if a.mode=='nodes-packed':
                    print(json.dumps({'report':str(report_path),'mode':a.mode,'node_roundtrip':report['node_roundtrip']},indent=2));return
                print(json.dumps({'report':str(report_path),'mode':a.mode,'memory_gate_pass':report['memory_gate_pass'],'observed_incremental_rss_bytes':report['observed_snapshot_incremental_rss_bytes']},indent=2));return
        time.sleep(2)
    subprocess.run(base+['device','copy','from',*domain,'--source','Documents/packed-runtime-progress.json','--destination',str(results/(prefix+'-progress.json'))],timeout=75)
    raise TimeoutError('No fresh isolated benchmark report; progress receipt retained. '+last)


if __name__=='__main__':main()

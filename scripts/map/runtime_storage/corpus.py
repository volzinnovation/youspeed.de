#!/usr/bin/env python3
"""Deterministic full-region, conditional-rule and physical-event query samples."""
import argparse
import csv
import json
from pathlib import Path
import sqlite3


def create(source, output, base_count=256):
    d=sqlite3.connect('file:'+str(source.resolve())+'?mode=ro&immutable=1',uri=True)
    tables={r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    count=d.execute('SELECT count(*) FROM ways').fetchone()[0]
    step=max(1,count//base_count)
    selected={}
    for i,(way_id,) in enumerate(d.execute('SELECT way_id FROM ways ORDER BY way_id')):
        if i%step==0:selected.setdefault(way_id,set()).add('full_region_systematic')
    for table,label,limit in [('road_speed_rule_set','conditional_rule_set',128),
                              ('traffic_sign_way_rule','directional_physical_sign_event',128),
                              ('motorway_exit_approach','motorway_exit',32),
                              ('settlement_sign','town_sign',64)]:
        if table in tables:
            for way_id, in d.execute(f'SELECT DISTINCT way_id FROM "{table}" WHERE way_id IS NOT NULL ORDER BY way_id LIMIT ?', (limit,)):
                selected.setdefault(way_id,set()).add(label)
    for order in ('min_lon ASC','max_lon DESC','min_lat ASC','max_lat DESC'):
        way_id=d.execute('SELECT way_id FROM ways ORDER BY '+order+' LIMIT 1').fetchone()[0]
        selected.setdefault(way_id,set()).add('region_extreme')
    rows=[]
    for way_id,labels in sorted(selected.items()):
        value=d.execute('SELECT points_json FROM way_geom WHERE way_id=?',(way_id,)).fetchone()
        if value is None:continue
        points=json.loads(value[0])
        if not points:continue
        middle=len(points)//2
        lat,lon=points[middle]
        rows.append((lat,lon,80))
    rows.append((0,0,80))
    with output.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(('lat','lon','radius_m'));w.writerows(rows)
    report={'source':str(source.resolve()),'queries':len(rows),'systematic_interval':step,
            'seed_way_ids':[{'way_id':k,'labels':sorted(v)} for k,v in sorted(selected.items())],
            'notes':'Source vertex probes and one no-road control. Includes conditional records and directed sign associations; does not evaluate their runtime policy.'}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='seed_way_ids'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();create(a.source,a.output)

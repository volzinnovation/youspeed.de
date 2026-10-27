#!/usr/bin/env python3
"""Independent original-SQL spatial/projection reference for the native corpus."""
import argparse
import csv
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import time

EARTH=6371008.8
SCALE=EARTH*math.pi/180


def project(lat,lon,points):
    if len(points)==1:
        p=points[0]
        return math.hypot((p[1]-lon)*math.cos(math.radians(lat))*SCALE,(p[0]-lat)*SCALE),0,p[0],p[1]
    best=(math.inf,0,0,0)
    chain=0
    for a,b in zip(points,points[1:]):
        ax,ay=(a[1]-lon)*math.cos(math.radians(lat))*SCALE,(a[0]-lat)*SCALE
        bx,by=(b[1]-lon)*math.cos(math.radians(lat))*SCALE,(b[0]-lat)*SCALE
        dx,dy=bx-ax,by-ay
        den=dx*dx+dy*dy
        t=max(0,min(1,-(ax*dx+ay*dy)/den)) if den else 0
        distance=math.hypot(ax+t*dx,ay+t*dy)
        x,y=math.radians(b[0]-a[0]),math.radians(b[1]-a[1])
        h=math.sin(x/2)**2+math.cos(math.radians(a[0]))*math.cos(math.radians(b[0]))*math.sin(y/2)**2
        length=2*EARTH*math.asin(math.sqrt(min(1,h)))
        if distance<best[0]:best=distance,chain+t*length,a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])
        chain+=length
    return best


def verify(binary,source,output,corpus,result,geodesk=None):
    started=time.perf_counter()
    with corpus.open() as f:
        queries=[tuple(map(float,r)) for r in list(csv.reader(f))[1:] if r and not r[0].startswith('#')]
    d=sqlite3.connect('file:'+str(source.resolve())+'?mode=ro&immutable=1',uri=True)
    original=[]
    cache={}
    for lat,lon,radius in queries:
        dy=radius/SCALE;dx=dy/math.cos(math.radians(lat))
        minlon,minlat,maxlon,maxlat=(math.floor((lon-dx)*1e7)/1e7,math.floor((lat-dy)*1e7)/1e7,math.ceil((lon+dx)*1e7)/1e7,math.ceil((lat+dy)*1e7)/1e7)
        ids=d.execute('''SELECT w.way_id FROM ways_rtree r JOIN ways w USING(way_id)
            WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?
            AND w.min_lon<=? AND w.max_lon>=? AND w.min_lat<=? AND w.max_lat>=? ORDER BY w.way_id''',
            (maxlon,minlon,maxlat,minlat,maxlon,minlon,maxlat,minlat)).fetchall()
        rows=[]
        for way_id, in ids:
            if way_id not in cache:
                cache[way_id]=json.loads(d.execute('SELECT points_json FROM way_geom WHERE way_id=?',(way_id,)).fetchone()[0])
            projection=project(lat,lon,cache[way_id])
            if projection[0]<=radius:rows.append((way_id,projection))
        original.append(rows)
    backends={'packed':str(output/'runtime.pack'),'sqlite':str(output/'runtime.sqlite')}
    if geodesk:backends['geodesk']=str(geodesk)+'|'+str(output/'runtime.sqlite')
    decoded={}
    errors={}
    candidate_count=sum(map(len,original))
    for backend,path in backends.items():
        p=subprocess.run([str(binary),'dump',backend,path,str(corpus)],capture_output=True,text=True,check=True)
        data=json.loads(p.stdout)
        assert len(data)==len(original)
        maxerror=0
        for i,(expected,actual) in enumerate(zip(original,data)):
            assert [r[0] for r in expected]==[r['way_id'] for r in actual],(backend,'candidate mismatch',i,queries[i])
            for (way_id,projection),row in zip(expected,actual):
                native=(row['distance_m'],row['chainage_m'],row['lat'],row['lon'])
                error=max(abs(a-b) for a,b in zip(projection,native))
                maxerror=max(maxerror,error)
                assert error<1e-7,(backend,'projection mismatch',i,way_id,error)
        decoded[backend]=data
        errors[backend]=maxerror
    assert all(v==decoded['packed'] for v in decoded.values()),'Native backend results differ'
    report={'queries':len(queries),'candidate_results':candidate_count,'backends':list(backends),
            'original_sql_candidate_sets_identical':True,'native_backend_outputs_exactly_identical':True,
            'original_python_projection_max_abs_error':errors,'projection_absolute_tolerance':1e-7,
            'elapsed_seconds':time.perf_counter()-started,'corpus':str(corpus.resolve())}
    result.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('binary','source','output-dir','corpus','result'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--geodesk',type=Path)
    a=p.parse_args();verify(a.binary,a.source,a.output_dir,a.corpus,a.result,a.geodesk)

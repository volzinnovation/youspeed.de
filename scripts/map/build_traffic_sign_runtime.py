#!/usr/bin/env python3
"""Build the optional, directed traffic-sign runtime overlay in a v3 road DB.

Physical decoding uses pinned openlr 1.0.1; graph dereferencing below is local to
this bundle. No nearest-way fallback is allowed for speed or settlement actions.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import heapq
import json
import math
import re
from pathlib import Path
import sqlite3

from build_mobidata_v1_5_pilot import normalize_sign, project_polyline as project_local, EARTH_RADIUS_M

ROOT = Path(__file__).resolve().parents[2]
VERSION = '1'
MAX_DISTANCE_M = 30.0
MAX_BEARING_ERROR = 35.0


def geodesic_length(a,b):
    lat1,lat2=map(math.radians,(a[0],b[0]))
    dlat=lat2-lat1;dlon=math.radians(b[1]-a[1])
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*6_371_000.0*math.asin(min(1,math.sqrt(h)))


def project_polyline(lat,lon,points):
    """Local nearest projection, invariant geodesic chainage of source vertices.

    A query-dependent local scale must not change chainage as the car moves.
    This uses the same spherical segment lengths as v3 way_endpoints and both
    mobile adapters; the local plane is used only for the segment fraction.
    """
    result=project_local(lat,lon,points)
    if result is None:return None
    index=result['segment_index'];a,b=points[index:index+2]
    sx=math.cos(math.radians(lat))
    dx=(b[1]-a[1])*sx;dy=b[0]-a[0]
    px=(result['projection_lon']-a[1])*sx;py=result['projection_lat']-a[0]
    fraction=max(0,min(1,(px*dx+py*dy)/(dx*dx+dy*dy)))
    result['chainage_m']=sum(geodesic_length(x,y) for x,y in zip(points[:index],points[1:index+1]))+fraction*geodesic_length(a,b)
    return result


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def angle(a, b):
    return abs((a - b + 180) % 360 - 180)


def bounded_station(station,length):
    # Source geometry and stored lengths differ by sub-nanometre floating-point
    # accumulation at some endpoints. Do not turn a zero-length event into a
    # reversed interval overlapping the preceding offer.
    if station<1e-6:return 0.0
    if station>length-1e-6:return length
    return station


def integer(value):
    try:
        result = int(value)
        return result if 0 < result <= 32 else None
    except (ValueError, TypeError):
        return None


def way_direction(tags, highway=None):
    raw = str(next((tags[k] for k in ('oneway:motorcar','oneway:motor_vehicle','oneway:vehicle','oneway') if k in tags),'')).lower()
    one = -1 if raw == '-1' else 1 if raw in ('yes', '1', 'true') else 0
    if not raw and (highway in ('motorway','motorway_link') or tags.get('junction') == 'roundabout'):
        one = 1
    conditional = any('conditional' in k and (k.startswith(('oneway','access','vehicle','motor_vehicle','motorcar'))) for k in tags)
    if raw not in ('','-1','yes','1','true','no','0','false') or conditional:
        return one,0,0
    blocked = next((tags[k] for k in ('motorcar', 'motor_vehicle', 'vehicle', 'access') if k in tags), '') == 'no'
    def direction_access(suffix):
        return next((tags[k+suffix] for k in ('motorcar','motor_vehicle','vehicle','access') if k+suffix in tags),'') != 'no'
    forward = int(not blocked and one != -1 and direction_access(':forward'))
    backward = int(not blocked and one != 1 and direction_access(':backward'))
    return one, forward, backward


def lane_rows(way_id, tags, one):
    rows = []
    for direction, suffix in ((1, ':forward'), (-1, ':backward')):
        if one and one != direction:
            continue
        count = integer(tags.get('lanes' + suffix))
        if one == direction and count is None:
            count = integer(tags.get('lanes'))
        speed = tags.get('maxspeed:lanes' + suffix)
        turns = tags.get('turn:lanes' + suffix)
        access = tags.get('access:lanes' + suffix)
        if one == direction:
            speed = speed if speed is not None else tags.get('maxspeed:lanes')
            turns = turns if turns is not None else tags.get('turn:lanes')
            access = access if access is not None else tags.get('access:lanes')
        arrays = [str(v).split('|') if v is not None else [] for v in (speed, turns, access)]
        if count is None and arrays[0]:
            count = len(arrays[0])
        if count is None or any(a and len(a) != count for a in arrays):
            continue  # Do not invent a lane split from a total bidirectional count.
        for index in range(count):
            rows.append((way_id, direction, index + 1, *(a[index] if a else None for a in arrays), 'osm'))
    return rows


def import_directions(db, meta):
    db.execute('CREATE TEMP TABLE sign_direction_input(way_id INTEGER PRIMARY KEY,oneway INTEGER,forward_allowed INTEGER,backward_allowed INTEGER,lanes INTEGER,lanes_forward INTEGER,lanes_backward INTEGER,maxspeed_forward TEXT,maxspeed_backward TEXT,lane_tags_json TEXT)')
    batch, lanes = [], []
    def flush():
        db.executemany('INSERT INTO sign_direction_input VALUES(?,?,?,?,?,?,?,?,?,?)', batch)
        db.executemany('INSERT INTO traffic_sign_lane VALUES(?,?,?,?,?,?,?)', lanes)
        batch.clear(); lanes.clear()
    with Path(meta).open() as f:
        for line in f:
            row = json.loads(line)
            tags = row.get('raw_tags') or {}
            one, forward, backward = way_direction(tags, row.get('highway'))
            way_id = int(row['way_id'])
            lane_tags = {k: v for k, v in tags.items() if 'lanes' in k or k.startswith('oneway') or k.startswith('motorcar')
                         or ('conditional' in k and k.startswith(('maxspeed','access','vehicle','motor_vehicle')))}
            batch.append((way_id, one, forward, backward, integer(tags.get('lanes')), integer(tags.get('lanes:forward')),
                          integer(tags.get('lanes:backward')), tags.get('maxspeed:forward', tags.get('maxspeed')),
                          tags.get('maxspeed:backward', tags.get('maxspeed')), compact(lane_tags)))
            lanes.extend(lane_rows(way_id, tags, one))
            if len(batch) >= 10000:
                flush()
    flush()
    db.execute('''INSERT INTO traffic_sign_way_direction
        SELECT i.*,e.start_node_key,e.end_node_key,e.way_length_m,w.highway,w.ref,w.street_name
        FROM sign_direction_input i JOIN ways w USING(way_id) JOIN way_endpoints e USING(way_id)''')
    db.execute('DROP TABLE sign_direction_input')
    missing = db.execute('SELECT count(*) FROM ways w LEFT JOIN traffic_sign_way_direction d USING(way_id) WHERE d.way_id IS NULL').fetchone()[0]
    if missing:
        raise ValueError(f'{missing} admitted ways lack source direction metadata')


class Graph:
    def __init__(self, db):
        self.db = db

    @lru_cache(maxsize=30000)
    def way(self, way_id):
        row = self.db.execute('''SELECT d.way_id,d.forward_allowed,d.backward_allowed,d.start_node_key,d.end_node_key,
            d.way_length_m,d.highway,d.ref,d.street_name,g.points_json,d.maxspeed_forward,d.maxspeed_backward
            FROM traffic_sign_way_direction d JOIN way_geom g USING(way_id) WHERE way_id=?''', (way_id,)).fetchone()
        if row is None:
            return None
        result = dict(zip(('way_id','forward_allowed','backward_allowed','start','end','length','highway','ref','name','points','maxspeed_forward','maxspeed_backward'), row))
        result['points'] = json.loads(result['points'])
        return result

    @lru_cache(maxsize=30000)
    def edges(self, node):
        rows = self.db.execute('''SELECT way_id,1,end_node_key,way_length_m FROM traffic_sign_way_direction
            WHERE start_node_key=? AND forward_allowed=1
            UNION ALL SELECT way_id,-1,start_node_key,way_length_m FROM traffic_sign_way_direction
            WHERE end_node_key=? AND backward_allowed=1''', (node,node)).fetchall()
        return rows

    @lru_cache(maxsize=30000)
    def incoming(self,node):
        return self.db.execute('''SELECT way_id FROM traffic_sign_way_direction WHERE end_node_key=? AND forward_allowed=1
            UNION ALL SELECT way_id FROM traffic_sign_way_direction WHERE start_node_key=? AND backward_allowed=1''',(node,node)).fetchall()

    def candidates(self, lat, lon, bearing):
        dy = math.degrees(MAX_DISTANCE_M / EARTH_RADIUS_M)
        dx = dy / math.cos(math.radians(lat))
        result = []
        for (way_id,) in self.db.execute('''SELECT way_id FROM ways_rtree
                WHERE min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=?''', (lon+dx,lon-dx,lat+dy,lat-dy)):
            way = self.way(way_id)
            if way is None:
                continue
            projection = project_polyline(lat,lon,way['points'])
            if projection is None or projection['distance_m'] > MAX_DISTANCE_M:
                continue
            for direction, permitted in ((1,way['forward_allowed']),(-1,way['backward_allowed'])):
                error = angle(bearing,projection['local_heading_deg'] + (180 if direction == -1 else 0))
                if permitted and error <= MAX_BEARING_ERROR:
                    result.append(dict(way_id=way_id,direction=direction,error=error,**projection))
        return sorted(result,key=lambda r:(r['distance_m']+r['error']*.15,r['way_id'],r['direction']))[:4]

    @lru_cache(maxsize=20000)
    def shortest(self, start, end, excluded, limit):
        if start == end:
            return (0.0,())
        queue=[(0.0,start,())]; best={start:0.0}; expanded=0
        while queue and expanded < 3000:
            distance,node,path=heapq.heappop(queue)
            if node == end:
                return distance,path
            if distance > best.get(node,math.inf) or distance > limit:
                continue
            expanded+=1
            for way_id,direction,next_node,length in self.edges(node):
                if way_id in excluded:
                    continue
                new=distance+length
                if new <= limit and new < best.get(next_node,math.inf):
                    best[next_node]=new
                    heapq.heappush(queue,(new,next_node,path+((way_id,direction),)))
        return None

    @lru_cache(maxsize=20000)
    def reference_paths(self, raw):
        import openlr
        reference=openlr.binary_decode(raw)
        if type(reference).__name__ != 'PointAlongLineLocationReference' or len(reference.points)!=2:
            raise ValueError('unsupported_openlr_type')
        if int(reference.orientation) not in (1,2):
            raise ValueError('unknown_openlr_orientation')
        first,last=reference.points
        starts=self.candidates(first.lat,first.lon,first.bear)
        ends=self.candidates(last.lat,last.lon,(last.bear+180)%360)
        routes=[]
        for start in starts:
            for end in ends:
                sw,ew=self.way(start['way_id']),self.way(end['way_id'])
                ds,de=start['direction'],end['direction']
                if start['way_id']==end['way_id'] and ds==de and ds*(end['chainage_m']-start['chainage_m'])>0:
                    distance=abs(end['chainage_m']-start['chainage_m']); path=((sw['way_id'],ds),)
                else:
                    exit_node=sw['end'] if ds==1 else sw['start']
                    entry_node=ew['start'] if de==1 else ew['end']
                    route=self.shortest(exit_node,entry_node,tuple(sorted({sw['way_id'],ew['way_id']})),min(20000,first.dnp*1.5+100))
                    if route is None:
                        continue
                    middle,core=route
                    distance=(sw['length']-start['chainage_m'] if ds==1 else start['chainage_m'])+middle+(end['chainage_m'] if de==1 else ew['length']-end['chainage_m'])
                    path=((sw['way_id'],ds),)+core+((ew['way_id'],de),)
                length_error=abs(distance-first.dnp)
                if length_error>max(60,first.dnp*.30):
                    continue
                routes.append(dict(path=path,length=distance,offset=reference.poffs,
                                   start=start,end=end,orientation=int(reference.orientation),
                                   score=start['distance_m']+end['distance_m']+length_error*.15))
        return routes

    def associate(self, row):
        evidence={'decoder':'openlr-1.0.1','matcher':'directed-lrp-path-v1'}
        if not row['openlr_binary']:
            return None,'missing_openlr',evidence
        if row['openlr_confidence'] is None or row['openlr_confidence']<70:
            return None,'low_source_confidence',evidence
        try:
            routes=self.reference_paths(row['openlr_binary'])
        except (ValueError,TypeError,IndexError,NotImplementedError) as exc:
            evidence['detail']=str(exc)
            return None,'invalid_openlr',evidence
        candidates={}
        for route in routes:
            progress=0.0
            for index,(way_id,path_direction) in enumerate(route['path']):
                way=self.way(way_id)
                lo,hi=0.0,way['length']
                if index==0:
                    if path_direction==1:lo=route['start']['chainage_m']
                    else:hi=route['start']['chainage_m']
                if index==len(route['path'])-1:
                    if path_direction==1:hi=route['end']['chainage_m']
                    else:lo=route['end']['chainage_m']
                projection=project_polyline(row['latitude'],row['longitude'],way['points'])
                if projection and lo-2<=projection['chainage_m']<=hi+2 and projection['distance_m']<=MAX_DISTANCE_M:
                    station=bounded_station(projection['chainage_m'],way['length'])
                    offset_distance=abs(progress+(station-lo if path_direction==1 else hi-station)-route['offset']*route['length'])
                    direction=path_direction*(1 if route['orientation']==1 else -1)
                    permitted=way['forward_allowed'] if direction==1 else way['backward_allowed']
                    heading=(projection['local_heading_deg']+(180 if direction==-1 else 0))%360
                    orientation_error=angle(heading,row['orientation_deg']) if row['orientation_deg'] is not None else 0
                    if permitted and offset_distance<=max(35,route['length']*.03) and orientation_error<=55:
                        score=route['score']+projection['distance_m']+offset_distance*.25+orientation_error*.10
                        candidate=dict(way_id=way_id,direction=direction,station_chainage_m=station,
                                       local_heading_deg=projection['local_heading_deg'],score=score,
                                       distance_m=projection['distance_m'],offset_error_m=offset_distance,
                                       orientation_error_deg=orientation_error,path=[list(p) for p in route['path']])
                        key=(way_id,direction)
                        if key not in candidates or score<candidates[key]['score']:
                            candidates[key]=candidate
                progress+=hi-lo
        ranked=sorted(candidates.values(),key=lambda c:(c['score'],c['way_id'],c['direction']))
        evidence['candidates']=ranked[:4]
        if not ranked:
            return None,'no_verified_directed_path',evidence
        if len(ranked)>1 and ranked[1]['score']-ranked[0]['score']<8:
            return None,'ambiguous_directed_path',evidence
        return ranked[0],'accepted',evidence


def has_conflicting_lanes(db,way_id,direction):
    speeds={r[0] for r in db.execute('SELECT maxspeed FROM traffic_sign_lane WHERE way_id=? AND direction=? AND maxspeed IS NOT NULL AND maxspeed!=?',(way_id,direction,''))}
    return len(speeds)>1


def has_conditional_speed(db,way_id):
    row=db.execute('SELECT lane_tags_json FROM traffic_sign_way_direction WHERE way_id=?',(way_id,)).fetchone()
    return bool(row and any(k.startswith('maxspeed') and 'conditional' in k for k in json.loads(row[0])))


def materialize_osm_towns(db,graph,mapping,road_sha):
    """Preserve existing trusted OSM town stations where this inventory has gaps.

    These are additional, explicitly attributed source records, not fabricated
    MobiData observations. Unknown direction/location/association is excluded.
    """
    if not road_sha or not db.execute("SELECT 1 FROM sqlite_master WHERE name='settlement_sign'").fetchone():
        return 0
    country=db.execute("SELECT value FROM metadata WHERE key='country_code'").fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone() else None
    aliases={'city_limit:begin':'DE:310','city_limit:end':'DE:311'} if country and country[0]=='DE' else {}
    total=0;bounds=[]
    query='''SELECT sign_id,way_id,direction,lon,lat,sign_code,inside_city,association
        FROM settlement_sign WHERE direction IN(-1,1) AND way_id IS NOT NULL
        AND lon IS NOT NULL AND lat IS NOT NULL AND sign_code IN('DE:310','DE:311','city_limit:begin','city_limit:end')
        AND association IN('node_membership','collinear_way_split') ORDER BY sign_id'''
    physical=defaultdict(list);original_codes={}
    for row in db.execute(query):
        if row[5].startswith('city_limit:') and row[5] not in aliases:continue
        original_codes[row[0]]=row[5]
        row=list(row);row[5]=aliases.get(row[5],row[5])
        physical_key=':'.join(row[0].split(':')[:2]) if row[0].startswith('n:') else row[0].split(':w:')[0]
        physical[(physical_key,row[5])].append(row)
    stations=[];physical_evidence={};physical_alternatives={}
    for (physical_key,_),rows in physical.items():
        for row in rows:
            physical_evidence[row[0]]={'physical_source_key':physical_key,'source_station_ids':[r[0] for r in rows],
                                      'original_sign_code':original_codes[row[0]]}
            physical_alternatives[row[0]]=sorted({(r[1],r[2]) for r in rows})
        # Explicit and generic tags on the same node can describe the same
        # physical face. Prefer its exact source code, retain all raw keys.
        targets={}
        for row in sorted(rows,key=lambda r:(original_codes[r[0]]!=r[5],r[0])):
            targets.setdefault((row[1],row[2]),row)
        candidates=list(targets.values())
        if len(candidates)==1:
            stations.extend(candidates);continue
        downstream=[]
        for row in candidates:
            way=graph.way(row[1])
            projection=project_polyline(row[4],row[3],way['points']) if way else None
            if projection is None:continue
            before=projection['chainage_m'] if row[2]==1 else way['length']-projection['chainage_m']
            after=way['length']-before
            if before<=1 and after>1:downstream.append(row)
        # A node on a collinear OSM split is one physical boundary. Prefer its
        # unique downstream way, otherwise keep the ambiguity inactive.
        if len(downstream)==1:stations.extend(downstream)
    for original,way_id,direction,lon,lat,code,inside,association in stations:
        way=graph.way(way_id)
        if way is None or not (way['forward_allowed'] if direction==1 else way['backward_allowed']):continue
        projection=project_polyline(lat,lon,way['points'])
        if projection is None or projection['distance_m']>10:continue
        expected=1 if code=='DE:310' else 0
        if inside!=expected:continue
        targets=physical_alternatives[original]
        road_filter=' OR '.join('(a.way_id=? AND a.direction=?)' for _ in targets)
        near=db.execute('''SELECT s.sign_code,s.lat,s.lon FROM traffic_sign_runtime s
            JOIN traffic_sign_association a USING(sign_id) WHERE s.kind='settlement_boundary'
            AND s.source_id!='osm-settlement' AND a.status='accepted' AND ('''+road_filter+''')
            AND s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?''',
            (*[v for pair in targets for v in pair],lat-.0004,lat+.0004,lon-.0006,lon+.0006)).fetchall()
        if any(geodesic_length((lat,lon),(r[1],r[2])) <= (30 if r[0]==code else 3) for r in near):continue
        sign_id='osm-settlement:'+original
        art=mapping.get(code,{})
        path=art.get('pictogram_png_path')
        if path and path.startswith('shared/'):path=path[7:]
        heading=projection['local_heading_deg']
        db.execute('INSERT INTO traffic_sign_runtime VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (sign_id,'osm-settlement',original,road_sha,code,code,'settlement_boundary',None,None,'not_applicable',
                    lon,lat,(heading+(180 if direction==-1 else 0))%360,30,art.get('pictogram_key'),path,'[]'))
        db.execute('INSERT INTO traffic_sign_association VALUES(?,?,?,?,?,?,?,?)',
                   (sign_id,'accepted',way_id,direction,bounded_station(projection['chainage_m'],way['length']),heading,1.0,
                    compact({'method':'existing_osm_directed_town_station','settlement_sign_id':original,'association':association,'distance_m':projection['distance_m'],**physical_evidence[original]})))
        bounds.append((lon,lat));total+=1
    if total:
        db.execute('''INSERT INTO traffic_sign_source(source_id,publisher,dataset_url,source_url,license_id,license_url,
            snapshot_sha256,snapshot_timestamp,record_count,min_lon,min_lat,max_lon,max_lat,usage_role,modification_notice)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('osm-settlement','OpenStreetMap contributors','https://www.openstreetmap.org/copyright','https://download.geofabrik.de/europe/germany/baden-wuerttemberg.html',
             'ODbL-1.0','https://opendatacommons.org/licenses/odbl/1-0/',road_sha,None,total,
             min(r[0] for r in bounds),min(r[1] for r in bounds),max(r[0] for r in bounds),max(r[1] for r in bounds),'inventory_only',
             'Existing source-backed directed OSM town stations materialized as optional runtime boundaries; MobiData duplicates suppressed and original OSM tables retained.'))
    return total


def emit_intervals(db,graph):
    groups=defaultdict(list)
    for row in db.execute('''SELECT a.sign_id,a.way_id,a.direction,a.station_chainage_m,a.local_heading_deg,
            s.sign_code,s.kind,s.numeric_value,s.parameter_status FROM traffic_sign_association a
            JOIN traffic_sign_runtime s USING(sign_id) WHERE a.status='accepted'
            AND (s.kind IN ('speed_limit','settlement_boundary','speed_limit_end') OR s.sign_code='DE:282')'''):
        row=list(row)
        row[3]=bounded_station(row[3],graph.way(row[1])['length'])
        groups[(row[1],row[2])].append(row)
    inserted=0
    for (way_id,direction),events in sorted(groups.items()):
        events.sort(key=lambda r:(direction*r[3],0 if r[6]=='settlement_boundary' else 1,r[0]))
        conflicted=set()
        clusters=[]
        for event in events:
            if not clusters or abs(event[3]-clusters[-1][0][3])>1:
                clusters.append([])
            clusters[-1].append(event)
        for cluster in clusters:
            speeds={r[7] for r in cluster if r[6]=='speed_limit' and r[8]=='parsed_source_value'}
            cities={r[5] for r in cluster if r[6]=='settlement_boundary'}
            if len(speeds)>1 or len(cities)>1:
                conflicted.update(r[0] for r in cluster)
        for sign_id in sorted(conflicted):
            db.execute("UPDATE traffic_sign_association SET status='conflicting_source_values' WHERE sign_id=?",(sign_id,))
        city=None
        for index,row in enumerate(events):
            sign_id,_,_,station,heading,code,kind,value,status=row
            if sign_id in conflicted:
                city=None
                continue
            if kind=='settlement_boundary':
                city=1 if code=='DE:310' else 0
            end_event=kind=='speed_limit_end' or code=='DE:282'
            if kind not in ('settlement_boundary','speed_limit') and not end_event:
                continue
            if kind=='speed_limit' and status!='parsed_source_value':
                continue
            way=graph.way(way_id)
            finish=events[index+1][3] if index+1<len(events) else way['length'] if direction==1 else 0.0
            # Equal-station boundary/speed events are retained as zero-length
            # event rows; fresh explicit speed follows them deterministically.
            scope='unresolved' if has_conflicting_lanes(db,way_id,direction) else 'all'
            if kind=='speed_limit' and has_conditional_speed(db,way_id):scope='conditional'
            speed=value if kind=='speed_limit' else None
            rule_id=hashlib.sha256(f'{sign_id}:{way_id}:{direction}:{station}:{finish}'.encode()).hexdigest()
            db.execute('INSERT INTO traffic_sign_way_rule VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (rule_id,sign_id,way_id,direction,min(station,finish),max(station,finish),station,heading,speed,city,'accepted',scope))
            inserted+=1
    # Continue only across an ordinary unbranched split of the same road. A
    # merge/fork, new explicit OSM speed, lane conflict or new sign stops fill.
    # The source sign association/station is immutable; child paths are explicit.
    originals=db.execute('''SELECT r.*,s.kind FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s USING(sign_id)
        WHERE r.lane_scope='all' AND (s.kind IN('speed_limit','settlement_boundary','speed_limit_end') OR s.sign_code='DE:282')''').fetchall()
    for original in originals:
        rule_id,sign_id,way_id,direction,start,end,station,heading,speed,city,status,scope,kind=original
        origin=graph.way(way_id)
        if (direction==1 and abs(end-origin['length'])>.01) or (direction==-1 and abs(start)>.01):continue
        # At a shared exit station the town reset precedes a fresh posted
        # restriction. Only that final offer continues; the zero-length town
        # event remains physical evidence, not a second overlapping child rule.
        if groups[(way_id,direction)][-1][0]!=sign_id:continue
        original_raw=str(origin['maxspeed_forward' if direction==1 else 'maxspeed_backward'] or '').strip().lower()
        current=origin;current_direction=direction;path=[(way_id,direction)];distance=0
        for _ in range(32):
            node=current['end'] if current_direction==1 else current['start']
            outgoing=[e for e in graph.edges(node) if e[0] not in {p[0] for p in path}]
            if len(outgoing)!=1:break
            child_id,child_direction,_,length=outgoing[0]
            if any(r[0] not in (current['way_id'],child_id) for r in graph.incoming(node)):break
            child=graph.way(child_id)
            norm=lambda x:' '.join(str(x or '').lower().split())
            same_identity=(norm(current['ref']) and norm(current['ref'])==norm(child['ref'])) or (norm(current['name']) and norm(current['name'])==norm(child['name']))
            if not same_identity and not (not current['ref'] and not current['name'] and not child['ref'] and not child['name'] and current['highway']==child['highway']):break
            child_raw=str(child['maxspeed_forward' if child_direction==1 else 'maxspeed_backward'] or '').strip().lower()
            if child_raw and child_raw!=original_raw:break
            if has_conditional_speed(db,child_id):break
            if has_conflicting_lanes(db,child_id,child_direction):break
            child_events=groups.get((child_id,child_direction),[])
            entry=0.0 if child_direction==1 else child['length']
            finish=min(child_events,key=lambda e:child_direction*e[3])[3] if child_events else child['length'] if child_direction==1 else 0.0
            if abs(finish-entry)<.01:break
            if distance+abs(finish-entry)>5000:break
            point=child['points'][0 if child_direction==1 else -1]
            local=project_polyline(point[0],point[1],child['points'])
            if local is None:break
            path.append((child_id,child_direction))
            child_rule=hashlib.sha256(f'{rule_id}:continuation:{child_id}:{child_direction}'.encode()).hexdigest()
            db.execute('INSERT INTO traffic_sign_way_rule VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (child_rule,sign_id,child_id,child_direction,min(entry,finish),max(entry,finish),entry,local['local_heading_deg'],speed,city,'accepted','all'))
            db.execute('INSERT INTO traffic_sign_rule_path VALUES(?,?,?)',(child_rule,way_id,compact(path)))
            inserted+=1;distance+=abs(finish-entry)
            if child_events:break
            current=child;current_direction=child_direction
    return inserted


def build_runtime(db,meta,audit_path=ROOT/'docs/MOBIDATA_BW_PICTOGRAM_AUDIT_V1_5.json'):
    import openlr
    if not callable(openlr.binary_decode):
        raise ImportError('A pinned OpenLR decoder is required before replacing runtime data')
    audit=json.loads(Path(audit_path).read_text())
    mapping={r['source_code']:r for r in audit['entries']}
    road_sha=None
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone():
        road_path=dict(db.execute('SELECT key,value FROM metadata')).get('source_input_pbf')
        road_path=Path(road_path) if road_path else None
        if road_path and not road_path.is_absolute():road_path=ROOT/road_path
        if road_path and road_path.is_file():
            hasher=hashlib.sha256()
            with Path(road_path).open('rb') as source_file:
                while chunk:=source_file.read(1024*1024):hasher.update(chunk)
            road_sha=hasher.hexdigest()
    db.execute('SAVEPOINT traffic_sign_runtime_build')
    try:
        for statement in (ROOT/'mapdata/spec/traffic_sign_runtime_v1.sql').read_text().split(';'):
            if statement.strip():db.execute(statement)
        for table in ('traffic_sign_rule_path','traffic_sign_way_rule','traffic_sign_association','traffic_sign_lane','traffic_sign_way_direction','traffic_sign_runtime','traffic_sign_capability'):
            db.execute(f'DELETE FROM {table}')
        db.execute("DELETE FROM traffic_sign_source WHERE source_id='osm-settlement'")
        import_directions(db,meta)
        graph=Graph(db);counts=Counter(); signs=0
        db.row_factory=sqlite3.Row
        source=dict(db.execute('SELECT source_id,snapshot_sha256 FROM traffic_sign_source'))
        for row in db.execute('SELECT * FROM traffic_sign_inventory ORDER BY latitude,longitude,row_id'):
            sign_id=f"{row['source_id']}:{row['record_key']}"
            norm=normalize_sign(row['sign_code']);art=mapping.get(row['sign_code'],{})
            eligible=art.get('display_eligible',False)
            path=art.get('pictogram_png_path') if eligible else None
            if path and path.startswith('shared/'):path=path[len('shared/'):]
            # Family-only labels cannot attest the exact variant/value in this
            # source. Preserve that limitation rather than confirming an alias.
            classes=art.get('classifier_labels',[]) if art.get('classifier_capability')=='exact_label' else []
            db.execute('INSERT INTO traffic_sign_runtime VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (sign_id,row['source_id'],row['record_key'],source[row['source_id']],row['sign_code'],norm['normalized_code'],norm['kind'],norm['numeric_value'],norm['unit'],norm['parameter_status'],row['longitude'],row['latitude'],row['orientation_deg'],norm['display_radius_m'],art.get('pictogram_key') if eligible else None,path,compact(classes)))
            if norm['parameter_status'] in ('dynamic_unverified','annotation_unverified','malformed_code','invalid_value'):
                association,status,evidence=None,'unverified_source_annotation',{}
            else:
                association,status,evidence=graph.associate(row)
            counts[status]+=1;signs+=1
            db.execute('INSERT INTO traffic_sign_association VALUES(?,?,?,?,?,?,?,?)',
                       (sign_id,status,association['way_id'] if association else None,association['direction'] if association else None,
                        association['station_chainage_m'] if association else None,association['local_heading_deg'] if association else None,
                        min(1.0,row['openlr_confidence']/100) if association else None,compact(evidence)))
            if signs%10000==0:print(f'Processed {signs} inventory signs: {dict(counts)}',flush=True)
        db.row_factory=None
        osm_towns=materialize_osm_towns(db,graph,mapping,road_sha)
        source=dict(db.execute('SELECT source_id,snapshot_sha256 FROM traffic_sign_source'))
        rules=emit_intervals(db,graph)
        counts=dict(db.execute('SELECT status,count(*) FROM traffic_sign_association GROUP BY status'))
        report={'format':'youspeed.traffic-sign-runtime.v1','version':VERSION,'signs':signs+osm_towns,'mobidata_signs':signs,'osm_town_fallbacks':osm_towns,'rules':rules,
                'associations':dict(sorted(counts.items())),'road_directions':db.execute('SELECT count(*) FROM traffic_sign_way_direction').fetchone()[0],
                'known_lanes':db.execute('SELECT count(*) FROM traffic_sign_lane').fetchone()[0],
                'unresolved_lane_rules':db.execute("SELECT count(*) FROM traffic_sign_way_rule WHERE lane_scope!='all'").fetchone()[0],
                'continuation_rules':db.execute('SELECT count(*) FROM traffic_sign_rule_path').fetchone()[0],
                'matcher':'directed-lrp-path-v1','decoder':'openlr-1.0.1','source_snapshots':source}
        db.executemany('INSERT INTO traffic_sign_capability VALUES(?,?)',[('version',VERSION),('report_json',compact(report)),('interval_scope','directed_way_with_unbranched_continuation'),('lane_support','explicit_osm_directional'),('orientation_basis','openlr_point_orientation'),('osm_town_fallback','materialized' if road_sha else 'unavailable'),('road_snapshot_sha256',road_sha or '')])
        db.execute('RELEASE traffic_sign_runtime_build')
        return report
    except BaseException:
        db.row_factory=None
        db.execute('ROLLBACK TO traffic_sign_runtime_build');db.execute('RELEASE traffic_sign_runtime_build')
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--ways-meta',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if not args.db.is_file():parser.error('Database must exist')
    with sqlite3.connect(args.db) as db:report=build_runtime(db,args.ways_meta)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(compact(report))


if __name__=='__main__':main()

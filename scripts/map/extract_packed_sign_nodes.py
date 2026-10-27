#!/usr/bin/env python3
"""Retain country-independent OSM sign nodes without inventing applicability."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import osmium


def relevant(tags):
    # Keeping every traffic_sign variant also retains country codes such as
    # FR:B14 / CH:2.30 without pretending a partial classifier is exhaustive.
    return any(key.split(':', 1)[0] == 'maxspeed' or key == 'traffic_sign' or key.startswith('traffic_sign:') for key in tags)


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(value)))


class Nodes(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.nodes = {}

    def node(self, node):
        tags = {key:value for key,value in node.tags}
        if relevant(tags) and node.location.valid():
            self.nodes[int(node.id)] = {'source_id':f'osm-node:{node.id}', 'osm_node_id':int(node.id),
                'latitude':node.location.lat, 'longitude':node.location.lon, 'tags':tags,
                'memberships':[], 'source_way_memberships':[], 'binding_status':'no_admitted_source_way'}


class Memberships(osmium.SimpleHandler):
    def __init__(self, source, nodes):
        super().__init__()
        self.source, self.nodes = source, nodes
        self.incompatible_ways = 0

    def way(self, way):
        hits = [(ordinal,self.nodes[ref.ref]) for ordinal,ref in enumerate(way.nodes) if ref.ref in self.nodes]
        if not hits:
            return
        for ordinal, record in hits:
            record['source_way_memberships'].append({'way_id':int(way.id), 'source_vertex_ordinal':ordinal,
                                                     'proof':'explicit_source_way_node_membership'})
        row = self.source.execute('SELECT points_json FROM way_geom WHERE way_id=?', (int(way.id),)).fetchone()
        if not row:
            return
        points = json.loads(row[0])
        if len(points) != len(way.nodes):
            self.incompatible_ways += 1
            return
        stations = [0.0]
        for a,b in zip(points,points[1:]):
            stations.append(stations[-1] + distance(a,b))
        mismatch = False
        for ordinal, record in hits:
            latitude,longitude = points[ordinal]
            if (round(latitude*1e7),round(longitude*1e7)) != (round(record['latitude']*1e7),round(record['longitude']*1e7)):
                mismatch = True
                continue
            record['memberships'].append({'way_id':int(way.id), 'source_vertex_ordinal':ordinal,
                'chainage_m':stations[ordinal], 'direction':'unknown',
                'proof':'explicit_source_way_node_membership', 'coordinate_verified':True})
            record['binding_status'] = 'unresolved_direction'
        if mismatch:
            self.incompatible_ways += 1


def extract(pbf, database, output):
    started = time.monotonic()
    source_hash = hashlib.sha256()
    with Path(pbf).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            source_hash.update(block)
    with osmium.io.Reader(str(pbf)) as reader:
        timestamp = reader.header().get('osmosis_replication_timestamp')
    nodes = Nodes()
    nodes.apply_file(str(pbf),locations=False,filters=[osmium.filter.EmptyTagFilter()])
    source = sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro&immutable=1',uri=True)
    membership = Memberships(source,nodes.nodes)
    membership.apply_file(str(pbf),locations=False)
    source.close()
    for record in nodes.nodes.values():
        for name in ['memberships','source_way_memberships']:
            record[name].sort(key=lambda item:(item['way_id'],item['source_vertex_ordinal']))
    sql_hash=hashlib.sha256()
    with Path(database).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):sql_hash.update(block)
    summary = {'schema':'youspeed.generic-sign-nodes.v1', 'source_pbf_sha256':source_hash.hexdigest(),
        'source_sqlite_sha256':sql_hash.hexdigest(),
        'source_pbf_timestamp':timestamp or None, 'node_count':len(nodes.nodes),
        'membership_count':sum(len(item['memberships']) for item in nodes.nodes.values()),
        'unassociated_node_count':sum(not item['memberships'] for item in nodes.nodes.values()),
        'incompatible_source_ways':membership.incompatible_ways,
        'authority':'Source data only; all direction/legal bindings remain unverified. Incompatible older/newer way snapshots retain raw source memberships but no runtime chainage binding.'}
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    with Path(output).open('w') as target:
        prefix = json.dumps(summary,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        target.write(prefix[:-1]+',"nodes":[')
        for index,key in enumerate(sorted(nodes.nodes)):
            if index:target.write(',')
            json.dump(nodes.nodes[key],target,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        target.write(']}\n')
    summary['elapsed_seconds'] = time.monotonic()-started
    return summary


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pbf',type=Path,required=True)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(extract(args.pbf,args.db,args.output),indent=2))

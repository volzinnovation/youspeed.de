#!/usr/bin/env python3
"""Read-only contract gate for the optional directed traffic-sign overlay."""
import argparse
import json
from pathlib import Path
import sqlite3


def validate(db,require=False):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    report={'format':'youspeed.traffic-sign-runtime.validation.v1','supported':False,'ready':False,'errors':[],'counts':{}}
    if 'traffic_sign_capability' not in tables:
        report['ready']=not require
        if require:report['errors'].append('Missing required optional sign capability')
        return report
    capability=dict(db.execute('SELECT key,value FROM traffic_sign_capability'))
    if capability.get('version')!='1':
        report['errors'].append('Unknown traffic-sign capability version')
        return report
    report['supported']=True
    required={'traffic_sign_runtime','traffic_sign_way_rule','traffic_sign_association','traffic_sign_way_direction','traffic_sign_lane','traffic_sign_inventory','traffic_sign_source','traffic_sign_rule_path'}
    for table in sorted(required-tables):report['errors'].append('Missing table: '+table)
    if report['errors']:return report
    checks={
        'all_inventory_records_materialized':'''SELECT count(*) FROM traffic_sign_inventory i LEFT JOIN traffic_sign_runtime s ON s.source_id=i.source_id AND s.record_key=i.record_key WHERE s.sign_id IS NULL''',
        'all_runtime_signs_have_current_source':'''SELECT count(*) FROM traffic_sign_runtime s LEFT JOIN traffic_sign_source p USING(source_id) LEFT JOIN traffic_sign_inventory i ON i.source_id=s.source_id AND i.record_key=s.record_key WHERE p.source_id IS NULL OR p.snapshot_sha256!=s.snapshot_sha256 OR (s.source_id!='osm-settlement' AND i.row_id IS NULL)''',
        'directions_cover_admitted_ways':'''SELECT count(*) FROM ways w LEFT JOIN traffic_sign_way_direction d USING(way_id) WHERE d.way_id IS NULL''',
        'accepted_associations_permitted':'''SELECT count(*) FROM traffic_sign_association a LEFT JOIN traffic_sign_way_direction d USING(way_id) WHERE a.status='accepted' AND (d.way_id IS NULL OR a.direction IS NULL OR a.direction NOT IN(-1,1) OR (a.direction=1 AND d.forward_allowed!=1) OR (a.direction=-1 AND d.backward_allowed!=1) OR a.station_chainage_m<0 OR a.station_chainage_m>d.way_length_m+0.5)''',
        'radii_match_exact_classes':'''SELECT count(*) FROM traffic_sign_runtime WHERE display_radius_m!=CASE WHEN sign_code IN('DE:310','DE:311') THEN 30 ELSE 10 END''',
        'rules_have_accepted_association':'''SELECT count(*) FROM traffic_sign_way_rule r LEFT JOIN traffic_sign_association a USING(sign_id) LEFT JOIN traffic_sign_rule_path p USING(rule_id) WHERE a.status IS NULL OR a.status!='accepted' OR (p.rule_id IS NULL AND (r.way_id!=a.way_id OR r.direction!=a.direction))''',
        'rule_geometry_bounds':'''SELECT count(*) FROM traffic_sign_way_rule r JOIN traffic_sign_way_direction d USING(way_id) WHERE r.start_chainage_m<0 OR r.end_chainage_m<r.start_chainage_m OR r.end_chainage_m>d.way_length_m+0.5 OR r.station_chainage_m<0 OR r.station_chainage_m>d.way_length_m+0.5''',
        'unverified_parameters_never_active':'''SELECT count(*) FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s USING(sign_id) WHERE s.parameter_status IN('dynamic_unverified','annotation_unverified','invalid_value','malformed_code')''',
        'source_speed_value_matches_rule':'''SELECT count(*) FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s USING(sign_id) WHERE r.speed_kmh IS NOT NULL AND (s.kind!='speed_limit' OR s.parameter_status!='parsed_source_value' OR r.speed_kmh!=s.numeric_value OR r.speed_kmh<=0 OR r.speed_kmh>300 OR cast(r.speed_kmh AS INTEGER)!=r.speed_kmh)''',
        'boundary_context_correct':'''SELECT count(*) FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s USING(sign_id) WHERE (s.sign_code='DE:310' AND r.inside_city IS NOT 1) OR (s.sign_code='DE:311' AND r.inside_city IS NOT 0)''',
        'lane_conflicts_stay_unresolved':'''SELECT count(*) FROM traffic_sign_way_rule r WHERE r.lane_scope='all' AND (SELECT count(DISTINCT maxspeed) FROM traffic_sign_lane l WHERE l.way_id=r.way_id AND l.direction=r.direction AND l.maxspeed IS NOT NULL AND l.maxspeed!='')>1''',
        'no_overlapping_rule_interiors':'''SELECT count(*) FROM traffic_sign_way_rule a JOIN traffic_sign_way_rule b ON a.way_id=b.way_id AND a.direction=b.direction AND a.rule_id<b.rule_id WHERE a.start_chainage_m<b.end_chainage_m AND b.start_chainage_m<a.end_chainage_m''',
    }
    if 'settlement_sign' in tables:
        checks['osm_fallback_has_source_station']='''SELECT count(*) FROM traffic_sign_runtime s LEFT JOIN traffic_sign_association a USING(sign_id) WHERE s.source_id='osm-settlement' AND NOT EXISTS(SELECT 1 FROM settlement_sign o WHERE o.sign_id=s.record_key AND (o.sign_code=s.sign_code OR (o.sign_code='city_limit:begin' AND s.sign_code='DE:310') OR (o.sign_code='city_limit:end' AND s.sign_code='DE:311')) AND o.way_id=a.way_id AND o.direction=a.direction AND o.direction IN(-1,1) AND o.lon=s.lon AND o.lat=s.lat AND o.inside_city=CASE WHEN s.sign_code='DE:310' THEN 1 ELSE 0 END AND o.association IN('node_membership','collinear_way_split'))'''
        country=db.execute("SELECT value FROM metadata WHERE key='country_code'").fetchone() if 'metadata' in tables else None
        if not country or country[0]!='DE':
            checks['generic_town_aliases_only_in_germany']="SELECT count(*) FROM traffic_sign_runtime s JOIN settlement_sign o ON o.sign_id=s.record_key WHERE s.source_id='osm-settlement' AND o.sign_code IN('city_limit:begin','city_limit:end')"
    else:
        checks['osm_fallback_has_source_station']="SELECT count(*) FROM traffic_sign_runtime WHERE source_id='osm-settlement'"
    try:
        for table in sorted(required):report['counts'][table]=db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
        report['failed_rows']={key:db.execute(sql).fetchone()[0] for key,sql in checks.items()}
        report['errors'] += [f'{key}: {count} invalid rows' for key,count in report['failed_rows'].items() if count]
        for (raw,) in db.execute('SELECT model_classes_json FROM traffic_sign_runtime'):
            value=json.loads(raw)
            if not isinstance(value,list) or any(not isinstance(x,str) for x in value):
                report['errors'].append('Malformed camera model class list');break
        path_errors=0
        for rule_id,origin,raw in db.execute('SELECT rule_id,origin_way_id,way_directions_json FROM traffic_sign_rule_path'):
            try:
                path=json.loads(raw)
                rule=db.execute('SELECT r.way_id,r.direction,a.way_id,a.direction FROM traffic_sign_way_rule r JOIN traffic_sign_association a USING(sign_id) WHERE rule_id=?',(rule_id,)).fetchone()
                valid=isinstance(path,list) and 2<=len(path)<=33 and len({p[0] for p in path})==len(path)
                valid=valid and rule is not None and path[0]==[rule[2],rule[3]] and path[-1]==[rule[0],rule[1]] and origin==rule[2]
                previous=None
                for way_id,direction in path:
                    row=db.execute('SELECT start_node_key,end_node_key,forward_allowed,backward_allowed FROM traffic_sign_way_direction WHERE way_id=?',(way_id,)).fetchone()
                    if row is None or direction not in (-1,1) or row[2 if direction==1 else 3]!=1:
                        valid=False;break
                    entry,exit=(row[0],row[1]) if direction==1 else (row[1],row[0])
                    if previous is not None and previous!=entry:valid=False
                    previous=exit
                if not valid:path_errors+=1
            except (ValueError,TypeError,IndexError):path_errors+=1
        report['failed_rows']['invalid_continuation_paths']=path_errors
        if path_errors:report['errors'].append(f'invalid_continuation_paths: {path_errors}')
        report['associations']=dict(db.execute('SELECT status,count(*) FROM traffic_sign_association GROUP BY status'))
    except (sqlite3.Error,ValueError,TypeError) as exc:report['errors'].append(str(exc))
    report['ready']=not report['errors']
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--out-json',type=Path,required=True);p.add_argument('--require',action='store_true');a=p.parse_args()
    with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True) as db:report=validate(db,a.require)
    a.out_json.parent.mkdir(parents=True,exist_ok=True);a.out_json.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if report['ready'] else 1


if __name__=='__main__':raise SystemExit(main())

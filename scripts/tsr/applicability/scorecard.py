#!/usr/bin/env python3
"""Encounter/event scorecard. Predictions never supply truth; synthetic data cannot qualify rollout."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts/tsr'))
from group_splits_v2 import SplitSample, build_group_split

SCENARIOS=('motorway_exit','parallel_carriageway','side_road_yield','ego_yield','opposite_direction','valid_left','median','overhead','curve','lane_split','junction_approach','actual_turn','repeated_equal_signs','stationary','poor_gps','missing_map','camera_remount','low_cadence','occlusion','detector_dropout','negative_driving')

def wilson(successes,total):
    if total==0:return None
    z=1.959963984540054;p=successes/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den;spread=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [max(0,center-spread),min(1,center+spread)]

def percentile(values,fraction):
    if not values:return None
    values=sorted(values);index=(len(values)-1)*fraction;lo=int(index);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(index-lo)

def validate_corpus(corpus):
    if corpus.get('schemaVersion')!=1:raise ValueError('Unsupported corpus version')
    encounters=corpus['encounters'];ids=[e['encounterId'] for e in encounters]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate encounter ID')
    groups=defaultdict(set)
    samples=[]
    for e in encounters:
        if e['applicability'] not in ('ego','non_ego','unknown','no_sign'):raise ValueError('Invalid applicability truth')
        if e['origin']=='reviewed_real' and (not e.get('reviewer') or not e.get('provenance')):raise ValueError('Reviewed truth requires reviewer and provenance')
        for key,value in [('drive',e['driveId']),('sign',e.get('physicalSignId')),('route',e['routeGroup'])]+[('duplicate',g) for g in e['duplicateGroups']]:
            if value:groups[(key,value)].add(e['split'])
        for k in ['distanceKm','durationHours']:
            v=e.get(k)
            if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v) or v<0):raise ValueError('Invalid exposure')
        samples.append(SplitSample(e['encounterId'],e['driveId'],tuple(filter(None,[e.get('physicalSignId')])),tuple(sorted(set(e['duplicateGroups']+['route-'+e['routeGroup']])))))
    if any(len(splits)>1 for splits in groups.values()):raise ValueError('Drive/sign/route/duplicate leakage across partitions')
    # Reuse connected-component construction; route/geography is an additional grouping key.
    return build_group_split(samples,seed='applicability-v1',near_duplicate_analysis_status='pending') if samples else None

def summarize(encounters,predictions):
    known=[e for e in encounters if e['applicability']!='unknown']
    positive=[e for e in known if e['applicability']=='ego' and e.get('signClassCorrect') is True]
    immediate=passages=false_immediate=false_passages=detected=unknown=duplicates=wrong_direction=dangerous=premature=0
    latencies=[];distances=[];costs=[]
    for e in encounters:
        p=predictions[e['encounterId']]
        if not isinstance(p.get('unknown'),bool):raise ValueError('Missing explicit unknown prediction')
        unknown+=p['unknown']
        valid=e in positive
        immediate_events=p['immediateEvents'];passage_events=p['passageEvents']
        for events in (immediate_events,passage_events):
            if len({x['eventId'] for x in events})!=len(events):raise ValueError('Duplicate event identity')
        immediate+=len(immediate_events);passages+=len(passage_events)
        good=[v for v in immediate_events if valid and v['classCorrect'] and not v['wrongDirection']]
        detected+=bool(good)
        if e in known:
            false_immediate+=sum(not valid or not v['classCorrect'] or v['wrongDirection'] for v in immediate_events)
            false_passages+=sum(not valid or not v['classCorrect'] or v['wrongDirection'] for v in passage_events)
        duplicates+=max(0,len(immediate_events)-1)+max(0,len(passage_events)-1)
        wrong_direction+=sum(v['wrongDirection'] for v in immediate_events)
        dangerous+=sum(v['dangerousSubstitution'] for v in immediate_events)
        premature+=sum(v.get('premature',False) for v in immediate_events+passage_events)
        for field,target in [('decisionLatencyMs',latencies),('decisionDistanceM',distances)]:
            v=p.get(field)
            if v is not None:
                if not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Nonfinite latency/distance')
                target.append(v)
        costs.extend(p.get('incrementalProcessingMs',[]))
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in costs):raise ValueError('Invalid cost')
    # Unknown truth is excluded from precision, never relabeled as a negative.
    scored_immediate=sum(len(predictions[e['encounterId']]['immediateEvents']) for e in known)
    km=sum(e['distanceKm'] for e in known if e.get('distanceKm') is not None and e['distanceKm']>0)
    hours=sum(e['durationHours'] for e in known if e.get('durationHours',0)>0)
    # Only events in positive-exposure clips enter the matching rate numerator.
    def exposed_false(field,exposure):
        return sum(sum(e not in positive or not v['classCorrect'] or v['wrongDirection'] for v in predictions[e['encounterId']][field]) for e in known if (e.get(exposure) or 0)>0)
    return dict(encounters=len(encounters),knownTruthEncounters=len(known),egoEncounters=len(positive),independentDrives=len({e['driveId'] for e in encounters}),
        immediateEvents=immediate,finalizedPassages=passages,falseImmediate=false_immediate,falsePassages=false_passages,
        precision=(scored_immediate-false_immediate)/scored_immediate if scored_immediate else None,precisionWilson95=wilson(scored_immediate-false_immediate,scored_immediate),
        recall=detected/len(positive) if positive else None,recallWilson95=wilson(detected,len(positive)),missedValidSigns=len(positive)-detected,
        unknownRate=unknown/len(encounters) if encounters else None,duplicates=duplicates,wrongDirection=wrong_direction,dangerousSubstitutions=dangerous,prematureEvents=premature,
        exposureKm=km,exposureHours=hours,excludedZeroOrUnknownDistance=sum(not(e.get('distanceKm') or 0)>0 for e in known),
        falseImmediatePerKm=exposed_false('immediateEvents','distanceKm')/km if km else None,falsePassagesPerKm=exposed_false('passageEvents','distanceKm')/km if km else None,
        falseImmediatePerHour=exposed_false('immediateEvents','durationHours')/hours if hours else None,
        latencyP50Ms=percentile(latencies,.5),latencyP95Ms=percentile(latencies,.95),distanceP50M=percentile(distances,.5),distanceP95M=percentile(distances,.95),
        incrementalP50Ms=percentile(costs,.5),incrementalP95Ms=percentile(costs,.95))

def evaluate(corpus,prediction_file,gates):
    validate_corpus(corpus)
    if prediction_file.get('corpusSha256')!=hashlib.sha256(json.dumps(corpus,sort_keys=True,separators=(',',':')).encode()).hexdigest():raise ValueError('Predictions are not bound to this corpus')
    if prediction_file.get('lane') not in ('recorded_candidates','full_image'):raise ValueError('Explicit replay lane required')
    encounters=[e for e in corpus['encounters'] if e['split']=='holdout']
    rows=prediction_file['encounters'];predictions={p['encounterId']:p for p in rows}
    if len(rows)!=len(predictions) or set(predictions)!={e['encounterId'] for e in encounters}:raise ValueError('Predictions must cover exactly the same held-out encounters')
    metrics=summarize(encounters,predictions);blockers=[]
    numeric=summarize([e for e in encounters if e.get('numericSign') is True],predictions)
    metrics['numericPrecisionWilson95']=numeric['precisionWilson95']
    metrics['numericEncounters']=numeric['encounters']
    for name in ['wrongWayThreshold','duplicateThreshold','approvedHoldoutHash','approvedDeviceProfiles']:
        if gates.get(name) is None:blockers.append('Unresolved gate: '+name)
    if any(e['origin']!='reviewed_real' for e in encounters) or not encounters:blockers.append('Missing independent reviewed real holdout')
    for name,key in [('encounters','minimumReviewedEncounters'),('independentDrives','minimumIndependentDrives'),('exposureKm','minimumDistanceKm'),('exposureHours','minimumDurationHours')]:
        if metrics[name]<gates[key]:blockers.append('Underpowered '+name)
    by_scenario={name:summarize([e for e in encounters if e['scenario']==name],predictions) for name in SCENARIOS}
    for name,m in by_scenario.items():
        if m['encounters']<gates['minimumEncountersPerScenario']:blockers.append('Missing/underpowered scenario: '+name)
    for metric,limit in [('numericPrecisionWilson95','numericPrecisionWilsonLower95'),('recallWilson95','recallWilsonLower95')]:
        if metrics[metric] is None or metrics[metric][0]<gates[limit]:blockers.append('Failed/unknown '+metric)
    # Field approval also needs paired baseline CIs and independent device attestations, never a self-declared pass.
    blockers += ['Paired baseline improvement and recall non-inferiority review pending','Full-image and minimum-device qualification pending','Rate confidence bounds and approved inventory review pending']
    return dict(schemaVersion=1,lane=prediction_file['lane'],qualification='blocked',productionApproval=False,metrics=metrics,byScenario=by_scenario,
        byRoadClass={name:summarize([e for e in encounters if e['roadClass']==name],predictions) for name in sorted({e['roadClass'] for e in encounters})},blockers=blockers)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('corpus',type=Path);p.add_argument('predictions',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    report=evaluate(json.loads(args.corpus.read_text()),json.loads(args.predictions.read_text()),json.loads((ROOT/'shared/tsr/applicability/qualification-gates-v1.json').read_text()))
    args.output.write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()

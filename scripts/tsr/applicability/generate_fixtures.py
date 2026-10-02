#!/usr/bin/env python3
"""Regenerate synthetic contract vectors, never reviewed road truth or field evidence."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'shared/tsr/applicability'

def scope(name):
    return dict(sessionId=name, bundleId='b'*64, cameraGeometryId='fixture-calibrated', generation=1, contextGeneration=1, traversalEpoch=1)

def candidate(frame, i=0, x=.60, y=.35, size=.08, semantic='maximum_speed:50:km/h', score=.97):
    return dict(candidateId=f'{frame}:{i}', semanticKey=semantic, box=dict(x=x,y=y,width=size,height=size),rawScore=score,recognitionScore=score,calibratedConfidence=None,recognitionEligible=True,assemblyId=f'assembly-{i}')

def corridor(way='2',heading=65,linked=True):
    return dict(wayId=way, headingDeg=heading, distanceM=30, roadClass='motorway_link' if linked else 'primary', endpointLinked=linked,turnAngleDeg=heading if linked else None)

def sequence(name, x=.6, y=.35, semantic='maximum_speed:50:km/h'):
    batches=[]
    for i,size in enumerate([.08,.1,.13]):
        fid=f'{name}-{i}';stamp=1000+i*400;sc=scope(name)
        road=dict(snapshotId=f'fix-{i}',capturedAtMs=stamp-100,scope=sc,wayId='1',horizontalAccuracyM=5,courseAccuracyDeg=5,courseDeg=0,localTangentDeg=0,matchedStable=True,roadClass='primary',hypotheses=[],branches=[],capabilities=['local_tangent','endpoint_links','endpoint_topology_only','no_lane_metadata','no_legal_direction'],cameraHorizontalFovDeg=80,cameraYawDeg=0)
        batches.append(dict(schemaVersion=1,frameId=fid,capturedAtMs=stamp,scope=sc,status='analyzed',candidates=[candidate(fid,x=x,y=y,size=size,semantic=semantic)],truncated=False,rawCandidateCount=1,modelId='synthetic-model',preprocessingId='synthetic-normalized-v1',road=road))
    return batches

def build():
    vectors=[]
    def add(name, expected, edit=None, **kwargs):
        frames=sequence(name,**kwargs)
        if edit: edit(frames)
        vectors.append(dict(id=name,origin='synthetic',expectedFinalClass=expected,batches=frames))
    ego='LIKELY_EGO_CORRIDOR';unknown='UNKNOWN'
    for name,x,y in [('ego_right',.6,.35),('valid_left',.18,.35),('median',.42,.35),('overhead',.45,.05),('ego_yield',.55,.35),('curve',.25,.35),('actual_turn',.6,.35)]:
        add(name,ego,x=x,y=y,semantic='yield' if 'yield' in name else 'maximum_speed:50:km/h')
    add('exit_lane','LIKELY_BRANCH',lambda fs:[f['road'].update(branches=[corridor(heading=32)]) for f in fs],x=.82)
    add('side_road_yield','LIKELY_BRANCH',lambda fs:[f['road'].update(branches=[corridor(heading=32)]) for f in fs],x=.82,semantic='yield')
    add('parallel_road',unknown,lambda fs:[f['road'].update(hypotheses=[corridor(heading=2,linked=False)]) for f in fs])
    add('junction_future_turn',unknown,lambda fs:[f['road'].update(branches=[corridor(heading=15)]) for f in fs],x=.45)
    add('legitimate_lane_split',unknown,lambda fs:[f['road'].update(branches=[corridor(heading=6)]) for f in fs])
    add('opposite_direction_unavailable',unknown,lambda fs:[f['road'].update(cameraYawDeg=None) for f in fs])
    add('poor_gps',unknown,lambda fs:[f['road'].update(horizontalAccuracyM=80) for f in fs])
    add('missing_map',unknown,lambda fs:[f.update(road=None) for f in fs])
    add('stale_capture_context',unknown,lambda fs:[f['road'].update(capturedAtMs=f['capturedAtMs']-3000) for f in fs])
    add('missing_links',unknown,lambda fs:[f['road'].update(capabilities=['local_tangent']) for f in fs])
    add('unreviewed_mount',unknown,lambda fs:[f['road'].update(cameraYawDeg=None,cameraHorizontalFovDeg=None) for f in fs])
    add('stopped_traffic',unknown,lambda fs:[f['candidates'][0]['box'].update(width=.08,height=.08) for f in fs])
    add('semantic_flicker',unknown,lambda fs:fs[1]['candidates'][0].update(semanticKey='maximum_speed:70:km/h'))
    add('simultaneous_equal_signs',ego,lambda fs:[f.update(candidates=[candidate(f['frameId'],0,x=.2,size=.08+i*.02),candidate(f['frameId'],1,x=.7,size=.08+i*.02)],rawCandidateCount=2) for i,f in enumerate(fs)])
    add('weak_ego_strong_branch',ego,lambda fs:[f.update(candidates=[candidate(f['frameId'],0,x=.4,size=.08+i*.02,score=.91),candidate(f['frameId'],1,x=.82,size=.08+i*.02)],rawCandidateCount=2) or f['road'].update(branches=[corridor(heading=38)]) for i,f in enumerate(fs)])
    # Expected list order is deterministic track order; assert special cases in native tests.
    vectors[-1]['expectedFinalClass']=None
    add('camera_remount',unknown,lambda fs:fs[-1].update(scope=dict(fs[-1]['scope'],cameraGeometryId='rotated')))
    add('failed_frame',unknown,lambda fs:fs[-1].update(status='failed'))
    add('proposal_cap',unknown,lambda fs:fs[-1].update(truncated=True))
    add('detector_dropout',unknown,lambda fs:fs[-1].update(candidates=[],rawCandidateCount=0))
    add('negative_driving',None,lambda fs:[f.update(candidates=[],rawCandidateCount=0) for f in fs])
    add('sparse_samples',ego,lambda fs:[f.update(capturedAtMs=1000+i*900) or f['road'].update(capturedAtMs=900+i*900) for i,f in enumerate(fs)])
    add('duplicate_frame',ego,lambda fs:fs.append(copy.deepcopy(fs[-1])))
    add('occlusion_reappearance',ego,lambda fs:fs.insert(2,dict(copy.deepcopy(fs[1]),frameId='occlusion-miss',capturedAtMs=1600,candidates=[],rawCandidateCount=0)))
    add('sequential_same_value',unknown,lambda fs:fs[-1].update(capturedAtMs=6000,road=dict(fs[-1]['road'],capturedAtMs=5900)))
    def motorway(fs):
        for f in fs:
            f['road'].update(roadClass='motorway', postedSpeedKmh=130, branches=[corridor(heading=12)],
                cameraHorizontalFovDeg=None, cameraYawDeg=None)
    for speed in [90,70,50]:
        add(f'motorway_exit_{speed}',unknown,motorway,semantic=f'maximum_speed:{speed}:km/h')
        vectors[-1]['expectedWithheldCount']=1
    for name, edit in [
        ('exit_taken',lambda f:f['road'].update(roadClass='motorway_link')),
        ('mainline_limit_already_90',lambda f:f['road'].update(postedSpeedKmh=90)),
        ('unconnected_parallel',lambda f:f['road']['branches'][0].update(endpointLinked=False)),
        ('on_ramp_merge',lambda f:f['road']['branches'][0].update(headingDeg=180)),
        ('stale_motorway',lambda f:f['road'].update(capturedAtMs=f['capturedAtMs']-3000)),
        ('poor_gps_motorway',lambda f:f['road'].update(horizontalAccuracyM=80)),
        ('paired_mainline_repeat',lambda f:f.update(candidates=f['candidates']+[candidate(f['frameId'],1,x=.2)],rawCandidateCount=2)),
    ]:
        def prepare(fs, edit=edit):
            motorway(fs)
            for f in fs: edit(f)
        add(name,None,prepare)
        vectors[-1]['expectedWithheldCount']=0

    # A repeated main-road 90 followed by a small, right-hand access-road 30.
    # Includes the brief missing-map frame seen in the field, without private coordinates.
    for variant in ['conflict', 'missing_map', 'hold_expired', 'no_access', 'turned',
                    'paired', 'single_main', 'mixed_main', 'stale', 'poor_gps', 'new_camera',
                    'new_session', 'selected_access', 'truncated', 'duplicate']:
        name = 'access_' + variant
        fs = sequence(name, x=.3, semantic='maximum_speed:90:km/h')
        fs[2]['candidates'] = [candidate(fs[2]['frameId'], x=.70, size=.03, semantic='maximum_speed:30:km/h')]
        fs[2]['road']['hypotheses'] = [dict(corridor(heading=5, linked=False), roadClass='service', distanceM=5)]
        expected = [0, 0, 1]
        if variant in ['missing_map', 'hold_expired']:
            extra = copy.deepcopy(fs[2])
            extra.update(frameId=name+'-3', capturedAtMs=fs[2]['capturedAtMs']+(500 if variant=='missing_map' else 2000), road=None)
            extra['candidates'][0]['candidateId'] = name+'-3:0'
            extra['candidates'][0]['box']['x'] = .84
            fs.append(extra); expected.append(1 if variant=='missing_map' else 0)
        elif variant == 'no_access': fs[2]['road']['hypotheses'] = []; expected[-1] = 0
        elif variant == 'turned': fs[2]['road']['courseDeg'] = 70; expected[-1] = 0
        elif variant == 'paired':
            fs[2]['candidates'].append(candidate(fs[2]['frameId'], 1, x=.25, size=.03, semantic='maximum_speed:30:km/h'))
            fs[2]['rawCandidateCount'] = 2; expected[-1] = 0
        elif variant == 'single_main': fs[0]['candidates'] = []; fs[0]['rawCandidateCount'] = 0; expected[-1] = 0
        elif variant == 'mixed_main': fs[0]['candidates'][0]['semanticKey'] = 'maximum_speed:70:km/h'; expected[-1] = 0
        elif variant == 'stale': fs[2]['road']['capturedAtMs'] -= 3000; expected[-1] = 0
        elif variant == 'poor_gps': fs[2]['road']['horizontalAccuracyM'] = 50; expected[-1] = 0
        elif variant in ['new_camera','new_session']:
            fs[2]['scope'] = dict(fs[2]['scope'], **({'cameraGeometryId':'remounted'} if variant=='new_camera' else {'sessionId':'new'}))
            expected[-1] = 0
        elif variant == 'selected_access': fs[2]['road']['roadClass'] = 'service'; expected[-1] = 0
        elif variant == 'truncated': fs[2]['truncated'] = True; expected[-1] = 0
        elif variant == 'duplicate': fs[1] = copy.deepcopy(fs[0]); expected[-1] = 0
        vectors.append(dict(id=name, origin='synthetic', expectedFinalClass=None, expectedAccessWithheldCounts=expected, batches=fs))
    return dict(schemaVersion=1,description='Synthetic engineering fixtures; not field accuracy evidence. Expected policy outcomes are separate from raw proposals.',scenarios=vectors)

if __name__=='__main__':
    (OUT/'golden-vectors-v1.json').write_text(json.dumps(build(),indent=2)+'\n')

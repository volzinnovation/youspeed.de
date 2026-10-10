"""Focused alignment, binding, limited-GT and target-only evaluation checks."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from scripts.lanes import evaluate_auxiliary_video as evaluation


def test_inverse_letterbox_removes_padding_exactly_before_resampling():
    probability=np.ones((8,8),np.float32)
    content=np.arange(32,dtype=np.float32).reshape(4,8)/100
    probability[2:6,:]=content
    transform=dict(inputSize=8,padTop=2,padLeft=0,resizedWidth=8,resizedHeight=4)
    actual=evaluation.inverse_letterbox(probability,transform,4,2)
    assert np.array_equal(actual,cv2.resize(content,(4,2),interpolation=cv2.INTER_LINEAR))
    assert actual.max()<.32
    transform['padTop']=5
    with pytest.raises(ValueError,match='letterbox'):evaluation.inverse_letterbox(probability,transform,4,2)


def test_sparse_scores_only_actual_painted_spans_and_ignore_geometry():
    label=dict(evaluationYRange=[0,1],borders=[dict(geometry=[[.5,0],[.5,1]],paintedYIntervals=[[.2,.4]])],ignoreGeometry=[])
    probability=np.zeros((11,11),np.float32);probability[:,5]=.8;probability[:,4]=.9
    result=evaluation.sparse_positive_scores(probability,label,dict(paintToleranceX=.1))
    assert result['centerline']['count']==3
    assert result['centerline']['mean']==pytest.approx(.8)
    assert result['approximateBandMaximum']['mean']==pytest.approx(.9)
    label['ignoreGeometry']=[dict(points=[[.5,0],[.5,1]],tolerance=.01)]
    assert evaluation.sparse_positive_scores(probability,label,dict(paintToleranceX=.1))['centerline']['count']==0


def test_negative_roi_counts_only_reviewed_rows_and_caps_state_duration():
    probability=np.ones((11,10),np.float32)
    probability[3:6,:]=0
    binding=dict(evaluationYRange=[.3,.5],attributedDurationSeconds=.1)
    result=evaluation.negative_score(probability,binding)
    assert result['roiPixelCount']==30
    assert result['falsePositivePixels']==0
    assert result['sampledPositiveDurationSeconds']==0
    probability[4,2]=.5
    result=evaluation.negative_score(probability,binding)
    assert result['falsePositivePixels']==1
    assert result['sampledPositiveDurationSeconds']==.1


@pytest.fixture
def corpus(tmp_path):
    frames=[]
    for i in range(4):
        image=np.full((72,128,3),30+i,np.uint8)
        rgb=tmp_path/f'{i}.png';cv2.imwrite(str(rgb),image)
        gray=tmp_path/f'{i}.gray';gray.write_bytes(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).tobytes())
        source='a'*64
        frames.append(dict(id=f'frame-{i}',sequenceId='one',split='development',time=i*.1,actualPTS=i*.1,
            ptsValue=i,timeBase='1/10',sourceVideoSha256=source,sourceFrameId=f'{source}:{i}:1/10',
            grayPath=str(gray),graySha256=evaluation.sha(gray),rgbPath=str(rgb),rgbSha256=evaluation.sha(rgb),
            width=128,height=72,rgbWidth=128,rgbHeight=72,decodedWidth=128,decodedHeight=72,
            transform=dict(crop=None,analysisWidth=128,analysisHeight=72,uprightWidth=128,uprightHeight=72)))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(dict(frames=frames)))
    return manifest,frames


@pytest.mark.parametrize('mutation',['rgb','gray','pts','sourceFrameId','time','duplicate'])
def test_invalid_input_binding_fails(corpus,mutation):
    path,frames=corpus
    if mutation in ('rgb','gray'):frames[0][mutation+'Sha256']='0'*64
    elif mutation=='pts':frames[0]['actualPTS']=.05
    elif mutation=='sourceFrameId':frames[0]['sourceFrameId']='wrong'
    elif mutation=='time':frames[1]['time']=frames[0]['time']
    else:frames.append(copy.deepcopy(frames[0]))
    path.write_text(json.dumps(dict(frames=frames)))
    with pytest.raises(ValueError):evaluation.load_bound_manifest(path)


def test_negative_labels_require_correct_hash_and_sequence(corpus,tmp_path):
    path,frames=corpus
    labels=dict(qualification='synthetic',intervals=[dict(sequenceId='one',startSeconds=0,endSeconds=.4,
        evaluationYRange=[.5,1],frameIDs=[r['id'] for r in frames],inputSha256={r['id']:r['graySha256'] for r in frames})])
    negative=tmp_path/'negative.json';negative.write_text(json.dumps(labels))
    _,bound,_=evaluation.bind_reviews(frames,negative_path=negative)
    assert sum(r['attributedDurationSeconds'] for r in bound.values())==pytest.approx(.4)
    labels['intervals'][0]['inputSha256'][frames[0]['id']]='bad'
    negative.write_text(json.dumps(labels))
    with pytest.raises(ValueError,match='identity/hash'):evaluation.bind_reviews(frames,negative_path=negative)


def test_target_only_run_outputs_masks_and_prefix_verification(corpus,tmp_path):
    manifest,frames=corpus
    checkpoint=tmp_path/'weights.pt';checkpoint.write_bytes(b'synthetic weights')
    detector=tmp_path/'detector.pt';detector.write_bytes(b'synthetic detector')
    calls=[]
    class Predictor:
        def __init__(self,*args):
            self.config=dict(inputSize=128,trainingData='synthetic')
            self.config_sha256=evaluation.canonical_sha(self.config)
        def __call__(self,image,width,height):
            calls.append((image.shape,width,height))
            return np.full((height,width),image[0,0,0]/255,np.float32),dict(inputSize=128)
    args=SimpleNamespace(manifest=manifest,checkpoint=checkpoint,detector=detector,device='cpu',
        output_dir=tmp_path/'evaluation',labels=None,negative_labels=None)
    summary=evaluation.run(args,predictor_factory=Predictor)
    assert summary['frames']==4
    assert summary['prefixInvariance']['checkedFrames']==3
    assert summary['usesFutureFrames'] is False
    assert len(calls)==12
    result=json.loads((args.output_dir/'frames.json').read_text())
    assert len(result['frames'])==4
    for row in result['frames']:
        assert row['targetOnly'] is True
        assert evaluation.sha(row['maskPath'])==row['maskSha256']
        assert np.load(row['probabilityPath'],allow_pickle=False).shape==(72,128)
    assert (args.output_dir/'contact-sheet.png').exists()


def test_failed_prefix_invariance_does_not_publish_success(corpus,tmp_path):
    manifest,_=corpus
    checkpoint=tmp_path/'weights.pt';checkpoint.write_bytes(b'weights')
    detector=tmp_path/'detector.pt';detector.write_bytes(b'detector')
    generations=[]
    class Predictor:
        def __init__(self,*args):
            self.value=.1*len(generations);generations.append(self)
            self.config={};self.config_sha256=evaluation.canonical_sha(self.config)
        def __call__(self,image,width,height):
            return np.full((height,width),self.value,np.float32),{}
    args=SimpleNamespace(manifest=manifest,checkpoint=checkpoint,detector=detector,device='cpu',
        output_dir=tmp_path/'failed',labels=None,negative_labels=None)
    with pytest.raises(ValueError,match='prefix invariance'):
        evaluation.run(args,predictor_factory=Predictor)
    assert (args.output_dir/'failure.json').exists()
    assert not (args.output_dir/'summary.json').exists()

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/tsr/sign_only_pilot'))
import mobile_replay as replay


def test_reference_windows_and_ultrawide_fallback():
    assert replay.windows(1920,1080) == [(0,0,1080,1080),(840,0,1920,1080)]
    assert replay.windows(1080,1920) == [(0,0,1080,1920)]
    assert replay.windows(3000,1000) == [(0,0,1000,1000),(2000,0,3000,1000),(0,0,3000,1000)]
    assert len(replay.windows(2000,1000)) == 2


def test_source_overlap_maps_to_same_pixels():
    left, right = replay.windows(1920,1080)
    a = replay.source_box([900/1080*1024,200,950/1080*1024,300],left)
    b = replay.source_box([60/1080*1024,200,110/1080*1024,300],right)
    assert all(abs(x-y)<1e-9 for x,y in zip(a,b))


def test_portrait_padding_rejected_and_clipped():
    assert replay.source_box([0,0,200,100],(0,0,640,1280)) is None
    assert replay.source_box([200,0,300,100],(0,0,640,1280)) == [0,0,55,125]


def test_per_pass_cap_and_no_global_cap():
    passes = [[{'box':[i*10,j*20,i*10+5,j*20+5],'score':.99-i*.001} for i in range(15)] for j in range(2)]
    admitted, truncated = replay.admit(passes,.84)
    assert truncated and len(admitted)==24


def test_cross_pass_duplicates_and_threshold():
    box=[1,2,20,30]
    rows, truncated = replay.admit([[{'box':box,'score':.9}],[{'box':box,'score':.85},{'box':[100,100,110,110],'score':.8}]],.840783)
    assert len(rows)==1 and rows[0]['score']==.9 and not truncated


def test_error_matching_is_one_to_one():
    truth=[[0,0,10,10],[100,100,110,110]]
    preds=[{'box':[0,0,10,10],'score':.9},{'box':[0,0,10,10],'score':.8}]
    result=replay.errors(truth,preds)
    assert result['missed_truth_indices']==[1]
    assert len(result['false_positives'])==1

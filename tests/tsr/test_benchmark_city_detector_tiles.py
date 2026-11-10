"""Geometry, global deduplication and partial-label boundaries for tiling."""
import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('tile_benchmark',ROOT/'scripts/tsr/benchmark_city_detector_tiles.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)


def box(coords,annotation='a'):
    return {'annotation_id':annotation,'class_id':'city:end','detector_class_id':0,
            'bbox_source':'source_history_manual','bbox_xyxy':coords}


@pytest.mark.parametrize('mode',['mobile_right','whole_letterbox'])
@pytest.mark.parametrize('dimensions',[(3840,2160),(2376,4224)])
def test_single_input_arms_preserve_original_evaluator_pixels(mode,dimensions):
    image=Image.fromarray(np.random.default_rng(42).integers(0,256,(*dimensions[::-1],3),dtype=np.uint8))
    expected,_=subject.base.prepare_image(image,mode)
    actual=subject.render(image,subject.tile_transforms(*dimensions,mode)[0])
    assert actual.tobytes()==expected.tobytes()


def test_full_height_windows_add_left_coverage_without_changing_sign_size():
    refs=[box([100,800,180,860]),box([3600,800,3680,860],'right')]
    original=subject.coverage_targets(refs,subject.tile_transforms(3840,2160,'mobile_right'))
    assert [t['window_status'] for t in original]==['outside','inside']
    for mode,count in [('full_height_2',2),('full_height_3',3)]:
        tiles=subject.tile_transforms(3840,2160,mode)
        assert len(tiles)==count
        targets=subject.coverage_targets(refs,tiles)
        assert all(t['window_status']=='inside' and t['union_visible_fraction']==1 for t in targets)
        assert targets[0]['short_edge_pixels']==pytest.approx(original[0]['short_edge_pixels'])


def test_portrait_identical_full_height_windows_are_not_repeated():
    for mode in ['full_height_2','full_height_3']:
        tile=subject.tile_transforms(2376,4224,mode)
        current=subject.tile_transforms(2376,4224,'mobile_right')
        assert len(tile)==1
        assert tile[0]['source_window_xyxy']==pytest.approx(current[0]['source_window_xyxy'])


@pytest.mark.parametrize('dimensions',[(4224,2376),(2376,4224)])
def test_grid_has_six_overlapping_square_windows_and_full_source_coverage(dimensions):
    width,height=dimensions;tiles=subject.tile_transforms(width,height,'square_grid_6')
    assert len(tiles)==6
    side=tiles[0]['source_window_xyxy'][2]-tiles[0]['source_window_xyxy'][0]
    for axis in [0,1]:
        starts=sorted({t['source_window_xyxy'][axis] for t in tiles})
        assert all((side-(b-a))/side>=.2-1e-9 for a,b in zip(starts,starts[1:]))
    assert subject.union_area([t['source_window_xyxy'] for t in tiles])==pytest.approx(width*height)
    assert all(t['scale']>1024/height for t in tiles)


def test_source_mapping_global_nms_and_cap_preserve_confidence_order():
    left,right=subject.tile_transforms(3840,2160,'full_height_2')
    native=[1900,900,2000,1000]
    def prediction(t,score):
        s=t['scale'];x=t['offset_x'];y=t['offset_y']
        return {'bbox_xyxy':[native[0]*s+x,native[1]*s+y,native[2]*s+x,native[3]*s+y],
                'score':score,'anchor_index':1}
    proposals=subject.source_predictions([prediction(left,.8)],left)+subject.source_predictions([prediction(right,.9)],right)
    proposals.append({'bbox_xyxy':[100,100,200,200],'score':.7,'tile_index':0,'anchor_index':2})
    merged,stats=subject.merge_predictions(proposals,maximum=1)
    assert merged[0]['score']==.9 and merged[0]['bbox_xyxy']==pytest.approx(native)
    assert stats=={'source_proposals_before_merge':3,'duplicates_suppressed':1,
                   'deduplicated_before_global_cap':2,'global_cap_dropped':1}


def test_union_area_handles_disjoint_tiles_and_clipped_targets():
    assert subject.union_area([[0,0,1,1],[2,0,3,1]])==2
    t=subject.tile_transforms(3840,2160,'mobile_right')
    result=subject.coverage_targets([box([1600,500,1800,600])],t)[0]
    assert result['window_status']=='clipped'
    assert result['union_visible_fraction']==pytest.approx(.6)


def test_unlabelled_sources_are_workload_only_and_pixel_validation_is_required(tmp_path):
    path=tmp_path/'full.png';Image.new('RGB',(200,100)).save(path)
    m={'schema':'youspeed-city-detector-frames-v1','class_names':['sign','plate','face'],
       'image_verification_complete':True,'detector_checkpoint_sha256':subject.base.BASELINE_SHA,
       'frames':[{'image_id':'pending','image_path':'full.png','image_sha256':subject.base.sha(path),
                  'width':200,'height':100,'exif_orientation':1,'annotation_complete':False,
                  'split':'diagnostic','boxes':[],'reference_status':'pending_user_review'}]}
    frames=subject.validate_manifest(m,tmp_path,['diagnostic'])
    assert frames[0]['boxes']==[]
    m['image_verification_complete']=False
    with pytest.raises(ValueError,match='verification'):subject.validate_manifest(m,tmp_path,['diagnostic'])

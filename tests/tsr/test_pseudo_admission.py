import importlib.util
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[2]/'scripts/tsr/sign_only_pilot'
sys.path.insert(0, str(SCRIPTS))
from pseudo_admission import touches_internal_tile_boundary, exclusion_reason


def test_observed_partial_no_entry_box_is_excluded():
    assert touches_internal_tile_boundary([1500, 1292, 1536, 1388], 4000, 3000)


def test_outer_image_boundary_is_allowed():
    assert not touches_internal_tile_boundary([3950, 100, 4000, 180], 4000, 3000)
    assert not touches_internal_tile_boundary([0, 100, 50, 180], 4000, 3000)


def test_internal_start_and_bottom_are_guarded():
    assert touches_internal_tile_boundary([1152, 100, 1220, 180], 4000, 3000)
    assert touches_internal_tile_boundary([100, 1500, 180, 1535], 4000, 3000)
    assert not touches_internal_tile_boundary([100, 120, 180, 180], 4000, 3000)


def test_entire_frame_is_excluded_without_becoming_negative():
    record = dict(status='pseudo_positive', width=4000, height=3000,
                  accepted_boxes=[{'box':[1500,1292,1536,1388],'class_label':'no_entry'}])
    assert exclusion_reason(record) == 'possible_tile_truncated_sign_box'
    assert record['status'] == 'pseudo_positive'
    assert exclusion_reason(dict(status='pseudo_negative', width=4000, height=3000, accepted_boxes=[])) is None


def test_lane_layout_boards_do_not_enter_sign_training():
    assert exclusion_reason(dict(status='pseudo_positive', width=4000, height=3000,
        accepted_boxes=[{'box':[100,100,180,220],'class_label':'lanes'}])) == 'excluded_direction_or_lane_layout_board'


def test_visually_observed_supplementary_plate_excludes_entire_frame():
    record=dict(picture_id='e7d4cceb-bbca-48a9-b4fc-b2bb3210659b',status='pseudo_positive',width=4096,height=3072,
                accepted_boxes=[{'box':[2124,2314.5,2332,2460.25],'class_label':'city:start'}])
    assert exclusion_reason(record)=='visual_scope_or_localization_audit'
    assert record['status']=='pseudo_positive'

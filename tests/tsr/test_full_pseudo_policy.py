import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/tsr/sign_only_pilot'))
from mine_full_pseudo_labels import scope,positions

def test_scope_exclusions_and_tolerated_lights():
    for label in ['exit','supplementary:plate','traffic_signal','bad:back']:
        assert scope(label,.99)=='excluded'
    for label in ['city:start','city:end','arrow_right','lanes','maxspeed:30']:
        assert scope(label,.99)=='sign'

def test_uncertainty_is_not_a_negative():
    assert scope('maxspeed:30',.89)=='uncertain'
    assert scope('other',.99)=='uncertain'

def test_tiles_cover_last_edges():
    assert positions(1000)==[0]
    assert positions(1536)==[0]
    assert positions(4224)==[0,1152,2304,2688]

import importlib.util
from copy import deepcopy
from pathlib import Path
import sys
import pytest

SCRIPTS=Path(__file__).parents[2]/'scripts/tsr'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('intake_v2',SCRIPTS/'merge_de_expanded_intake_v2.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_new_same_physical_stop_views_share_group_without_mutating_v1():
    old=[{'sample_id':'v1','group_id':'frozen','source_id':'v1-picture'}]
    original=deepcopy(old)
    new=[{'sample_id':'new1','group_id':'site','group_identities':['osm:way:17','collection:a']},
         {'sample_id':'new2','group_id':'site','group_identities':['osm:way:17','collection:b']}]
    module.extend_groups(old,new)
    assert old==original
    assert new[0]['group_id']==new[1]['group_id']
    assert {'collection:a','collection:b','osm:way:17'}<=set(new[0]['group_identities'])


def test_new_view_inherits_existing_group_without_rewriting_frozen_row():
    old=[{'sample_id':'v1','group_id':'frozen','route_tokens':['collection:a']}]
    original=deepcopy(old)
    new=[{'sample_id':'new1','group_id':'temporary','route_tokens':['collection:a']}]
    module.extend_groups(old,new)
    assert new[0]['group_id']=='frozen' and old==original


def test_bridge_between_distinct_frozen_groups_fails_for_reconciliation():
    old=[{'sample_id':'v1a','group_id':'frozen-a','source_id':'a'},
         {'sample_id':'v1b','group_id':'frozen-b','source_id':'b'}]
    original=deepcopy(old)
    new=[{'sample_id':'bridge','group_id':'new','group_identities':['a','b']}]
    with pytest.raises(ValueError,match='two frozen v1 groups'):
        module.extend_groups(old,new)
    assert old==original

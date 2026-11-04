"""Annotation-inclusive inventory counts never depend on classifier support."""
from contextlib import contextmanager
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
from unittest.mock import patch

import pytest

from inspector.server import CropStore, InspectorError
from scripts.inspector import panoramax_annotation_statistics as statistics

AS_OF = '2026-11-03T19:59:43+00:00'
CATALOGS = {
    'DE': {'city:start', 'city:end', 'no_stop', 'hazard:incline', 'hazard:left_turn', 'hazard:right_turn'},
    'FR': {'B21a2'},
}
MODELS = {'DE': CATALOGS['DE'] - {'city:start', 'city:end'}, 'FR': CATALOGS['FR']}


def mobile(rows=None):
    rows = [] if rows is None else rows
    return {'as_of': AS_OF, 'total_crops': sum(row['count'] for row in rows), 'classes': rows}


def annotation(class_id='city:start', *, raw='DE:310', country='DE', catalog_class=None):
    return {
        'raw_tag': raw, 'parsed': {'raw': raw, 'code': raw.split(':')[-1]},
        'target_classifier_country': country, 'country_resolution_state': 'source_metadata',
        'semantic_mapping_status': 'unique', 'semantic_candidates': [{'label': class_id}],
        'yolo_mapping_status': 'unique' if catalog_class else 'catalog_mismatch',
        'selected_yolo': {'label': catalog_class, 'index': 3} if catalog_class else None,
    }


def detection():
    return {'raw_tag': 'yes', 'parsed': {'code': 'yes'}, 'target_classifier_country': None,
            'semantic_mapping_status': 'country_ambiguous', 'yolo_mapping_status': 'country_ambiguous'}


def report(groups, *, mobile_report=None, total=None, states=None):
    return statistics.build_report(mobile() if mobile_report is None else mobile_report,
                                   groups, CATALOGS, MODELS,
                                   total_panoramax_crops=sum(group['crops'] for group in groups) if total is None else total,
                                   annotations_by_state=states)


def test_manual_city_annotations_are_counted_even_when_classifier_cannot_emit_them():
    groups = [
        {'labels': [annotation(), detection()], 'crops': 63},
        {'labels': [annotation('city:end', raw='DE:311'), detection()], 'crops': 29},
    ]
    before = deepcopy(groups)
    result = report(groups, states=[{'state': 'ready', 'annotations': 92}, {'state': 'missing_geometry', 'annotations': 1}])
    assert [(row['class_id'], row['panoramax_crops']) for row in result['rows']] == [('city:start', 63), ('city:end', 29)]
    assert all(row['classifier_supported'] is False for row in result['rows'])
    assert all(row['source_annotations_crops'] == row['panoramax_crops'] for row in result['rows'])
    assert result['resolved_panoramax_crops'] == result['source_annotations_crops'] == result['all_crop_records'] == 92
    assert result['requires_review_panoramax_crops'] == 0
    assert result['identity_basis_counts'] == {'semantic_catalog': 92}
    assert groups == before


def test_existing_precise_catalogue_classes_survive_ambiguous_generic_semantic_aliases():
    examples = [
        ('DE', 'DE:108', 'hazard:incline', ['hazard:incline', 'hazard:incline:up'], 68),
        ('DE', 'DE:103-10', 'hazard:left_turn', ['hazard:left_turn', 'hazard:turn_left'], 36),
        ('DE', 'DE:103-20', 'hazard:right_turn', ['hazard:right_turn', 'hazard:turn_right'], 17),
        ('FR', 'FR:B21a2', 'B21a2', ['arrow_left_down', 'arrow_right_down'], 9),
    ]
    groups = []
    for country, raw, class_id, aliases, number in examples:
        label = annotation(country=country, raw=raw, catalog_class=class_id)
        label['semantic_mapping_status'] = 'ambiguous'
        label['semantic_candidates'] = [{'label': alias} for alias in aliases]
        groups.append({'labels': [label], 'crops': number})
    result = report(groups)
    assert result['resolved_panoramax_crops'] == 130
    assert result['requires_review_panoramax_crops'] == 0
    assert result['unresolved_panoramax'] == {}
    assert [row['class_id'] for row in result['rows']] == [item[2] for item in examples]
    assert all(row['classifier_supported'] for row in result['rows'])


def test_unresolved_and_compound_crops_remain_in_the_complete_inventory():
    conflict = annotation('no_stop', raw='DE:283', catalog_class='no_stop')
    conflict['country_resolution_state'] = 'country_conflict'
    groups = [
        {'labels': [annotation()], 'crops': 63},
        {'labels': [detection()], 'crops': 7},
        {'labels': [conflict], 'crops': 3},
        {'labels': [annotation(), annotation('city:end', raw='DE:311')], 'crops': 2},
    ]
    result = report(groups, mobile_report=mobile([{'country': 'DE', 'class_id': 'no_stop', 'count': 5}]))
    assert result['unresolved_panoramax'] == {'unresolved': 7, 'country_conflict': 3, 'compound': 2}
    assert result['panoramax_crops'] == 75
    assert result['ranked_crops'] == 68
    assert result['all_crop_records'] == 80
    assert result['ranked_crops'] + result['unresolved_panoramax_crops'] == result['all_crop_records']


def test_duplicate_annotation_tags_do_not_multiply_crops_and_equal_class_groups_merge():
    label = annotation()
    groups = [{'labels': [label, deepcopy(label)], 'crops': 7}, {'labels': [annotation()], 'crops': 3}]
    mobile_report = mobile([{'country': 'DE', 'class_id': 'no_stop', 'count': 10}])
    expected = report(groups, mobile_report=mobile_report)
    assert expected == report(list(reversed(groups)), mobile_report=mobile_report)
    assert len(expected['rows']) == 2
    assert [(row['class_id'], row['total_crops']) for row in expected['rows']] == [('city:start', 10), ('no_stop', 10)]
    assert expected['rows'][0]['source_annotations_crops'] == 10
    assert expected['all_crop_records'] == 20


def test_same_class_ids_in_different_countries_keep_separate_rows():
    result = report([], mobile_report=mobile([
        {'country': 'FR', 'class_id': 'same', 'count': 4}, {'country': 'DE', 'class_id': 'same', 'count': 4}]))
    assert [(row['country'], row['class_id']) for row in result['rows']] == [('DE', 'same'), ('FR', 'same')]


def test_denominator_mismatch_is_not_hidden_by_source_annotation_resolution():
    with pytest.raises(ValueError, match='independent ready-crop total'):
        report([{'labels': [annotation()], 'crops': 63}], total=64)
    bad_mobile = mobile([{'country': 'DE', 'class_id': 'no_stop', 'count': 5}])
    bad_mobile['total_crops'] = 6
    with pytest.raises(ValueError, match='stored-crop total'):
        report([], mobile_report=bad_mobile)


@pytest.mark.parametrize('number', [-1, True, 1.5])
def test_invalid_aggregate_counts_are_rejected(number):
    with pytest.raises(ValueError, match='nonnegative integer'):
        report([{'labels': [annotation()], 'crops': number}], total=1)


def test_annotation_states_cannot_claim_different_ready_crop_coverage():
    with pytest.raises(ValueError, match='Ready annotation-state count'):
        report([{'labels': [annotation()], 'crops': 63}], states=[{'state': 'ready', 'annotations': 64}])


def test_exports_are_inspectable_and_receipt_matches_all_output_bytes(tmp_path):
    result = report([{'labels': [annotation(), detection()], 'crops': 63}])
    receipt = statistics.export_report(result, tmp_path, source_sql='-- Frozen source query\nSELECT 1;\n')
    assert json.loads((tmp_path / 'annotation-class-statistics.json').read_text()) == result
    with (tmp_path / 'annotation-class-statistics.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['class_id'] == 'city:start'
    assert rows[0]['classifier_supported'] == 'False'
    assert rows[0]['panoramax_crops'] == rows[0]['source_annotations_crops'] == '63'
    text = (tmp_path / 'annotation-class-statistics.md').read_text()
    assert 'city:start' in text
    assert 'may be human or machine produced' in text
    assert receipt['all_assertions_passed'] is True
    assert 'source-query.sql' in receipt['files']
    for name, digest in receipt['files'].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest


def test_cli_reuses_report_role_and_private_connection_flags_without_connecting():
    args = statistics.arguments(['--db-host', '127.0.0.1', '--db-port', '15451', '--mapping-file', '/tmp/mapping.json'])
    assert args.db_user == 'youspeed_report'
    assert args.db_host == '127.0.0.1'
    assert args.db_port == 15451
    assert args.mapping_file.as_posix() == '/tmp/mapping.json'
    assert CropStore(args).media_root is None


class Database:
    def __init__(self, *, identity_role='youspeed_report', joined_rows=63, source_blocked_annotations=0,
                 states=None, label_groups=None):
        self.calls = []
        self.identity_role, self.joined_rows = identity_role, joined_rows
        self.source_blocked_annotations = source_blocked_annotations
        self.states = states
        self.label_groups = label_groups

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.sql = sql
        return self

    def fetchone(self):
        sql = self.sql
        if 'current_database' in sql:
            return {'database': 'youspeed', 'role': self.identity_role,
                    'as_of': datetime.fromisoformat(AS_OF), 'readonly': 'on', 'isolation': 'repeatable read'}
        if "report->>'mapping_sha256'" in sql:
            return {'mapping_sha256': 'pinned-digest'}
        if sql == statistics.DENOMINATOR_SQL:
            return {'ready_crops': 63, 'distinct_ready_crops': 63}
        if sql == statistics.JOIN_COUNT_SQL:
            return {'joined_rows': self.joined_rows, 'joined_crop_ids': 63}
        if 'discovery_snapshot' in sql:
            return {'discovery_snapshot': datetime.fromisoformat(AS_OF), 'crop_snapshot': datetime.fromisoformat(AS_OF)}
        if 'SELECT phase' in sql:
            return {'phase': 'complete', 'source_blocked_annotations': self.source_blocked_annotations}
        raise AssertionError(sql)

    def fetchall(self):
        if self.sql == statistics.GROUP_SQL:
            return self.label_groups if self.label_groups is not None else [{'labels': [annotation(), detection()], 'crops': 63}]
        if self.sql == statistics.ANNOTATION_SQL:
            return self.states if self.states is not None else [{'state': 'ready', 'annotations': 63, 'ignored_image_level_tags': 0}]
        raise AssertionError(self.sql)


class Store:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def connection(self):
        yield self.db


def test_snapshot_keeps_one_read_only_report_transaction_and_pinned_mapping():
    db = Database()
    with patch.object(statistics.mobile_statistics, 'snapshot', return_value=mobile()):
        result = statistics.snapshot(Store(db), {'sha256': 'pinned-digest'}, CATALOGS, MODELS)
    assert db.calls[0][0] == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'
    assert (statistics.GROUP_SQL, ('pinned-digest',)) in db.calls
    assert result['validation']['read_only'] and result['validation']['repeatable_read']
    assert result['panoramax_sync']['complete']
    assert result['rows'][0]['class_id'] == 'city:start'


@pytest.mark.parametrize('settings,expected', [({'identity_role': 'writer'}, 'Expected the youspeed_report'),
                                               ({'joined_rows': 64}, 'current crop/object joins disagree')])
def test_snapshot_rejects_wrong_role_or_crop_join_multiplication(settings, expected):
    db = Database(**settings)
    with patch.object(statistics.mobile_statistics, 'snapshot', return_value=mobile()):
        with pytest.raises(InspectorError, match=expected):
            statistics.snapshot(Store(db), {'sha256': 'pinned-digest'}, CATALOGS, MODELS)
    assert not any(sql == statistics.GROUP_SQL for sql, _ in db.calls)


def read_snapshot(db):
    with patch.object(statistics.mobile_statistics, 'snapshot', return_value=mobile()):
        return statistics.snapshot(Store(db), {'sha256': 'pinned-digest'}, CATALOGS, MODELS)


def test_source_blocked_annotations_are_separate_from_unresolved_classes_and_ready_crops():
    groups = [{'labels': [detection()], 'crops': 63}]
    unblocked = read_snapshot(Database(label_groups=groups))
    blocked = read_snapshot(Database(label_groups=groups, source_blocked_annotations=434))
    assert blocked['rows'] == unblocked['rows']
    assert blocked['all_crop_records'] == blocked['panoramax_crops'] == 63
    assert blocked['unresolved_panoramax'] == unblocked['unresolved_panoramax'] == {'unresolved': 63}
    sync = blocked['panoramax_sync']
    assert sync['source_blocked_annotations'] == 434
    assert sync['active_pending_crops'] == 0
    assert sync['eligible_active_crop_work_remaining'] is False
    assert sync['complete'] is False
    text = statistics.markdown(blocked)
    assert '434 source-blocked annotations' in text
    assert 'excluded from ready-crop totals and from unresolved class counts' in text
    assert 'No eligible active crop work remains' in text
    assert 'source-admission blocks remain' in text
    assert text.index('434 source-blocked annotations') < text.index('| Country | TSR class ID |')


def test_ignored_image_level_metadata_does_not_masquerade_as_pending_crop_work():
    result = read_snapshot(Database(states=[
        {'state': 'ready', 'annotations': 63, 'ignored_image_level_tags': 0},
        {'state': 'missing_geometry', 'annotations': 1, 'ignored_image_level_tags': 1},
    ]))
    assert result['active_pending_crops'] == 0
    assert result['ignored_image_level_tags'] == 1
    assert result['panoramax_sync']['complete'] is True
    assert result['panoramax_crops'] == 63


def test_real_missing_geometry_and_queued_annotations_count_as_pending_work():
    result = read_snapshot(Database(states=[
        {'state': 'ready', 'annotations': 63, 'ignored_image_level_tags': 0},
        {'state': 'queued', 'annotations': 2, 'ignored_image_level_tags': 0},
        {'state': 'rendering', 'annotations': 3, 'ignored_image_level_tags': 0},
        {'state': 'missing_geometry', 'annotations': 2, 'ignored_image_level_tags': 1},
    ]))
    assert result['active_pending_crops'] == 6
    assert result['ignored_image_level_tags'] == 1
    assert result['eligible_active_crop_work_remaining'] is True
    assert result['panoramax_sync']['source_blocked_annotations'] == 0
    assert result['panoramax_sync']['complete'] is False
    assert result['all_crop_records'] == 63
    text = statistics.markdown(result)
    assert '6 eligible active annotations still require crop processing' in text


def test_unknown_source_blocked_count_is_preserved_as_unknown_not_zero():
    result = read_snapshot(Database(source_blocked_annotations=None))
    assert result['panoramax_sync']['source_blocked_annotations'] is None
    assert result['panoramax_sync']['complete'] is False
    assert 'source-blocked annotation count; that coverage measure is unknown' in statistics.markdown(result)


def test_older_missing_geometry_counts_without_filter_evidence_remain_unknown():
    result = read_snapshot(Database(states=[
        {'state': 'ready', 'annotations': 63}, {'state': 'missing_geometry', 'annotations': 1},
    ]))
    assert result['active_pending_crops'] is None
    assert result['ignored_image_level_tags'] is None
    assert result['eligible_active_crop_work_remaining'] is None
    assert result['panoramax_sync']['complete'] is False


@pytest.mark.parametrize('blocked', [-1, True, '434', 0.5])
def test_source_blocked_annotation_count_requires_a_nonnegative_json_integer(blocked):
    with pytest.raises(ValueError, match='Source-blocked annotation count must be a nonnegative integer'):
        read_snapshot(Database(source_blocked_annotations=blocked))


@pytest.mark.parametrize('states', [
    [{'state': 'ready', 'annotations': 63, 'ignored_image_level_tags': 1}],
    [{'state': 'ready', 'annotations': 63}, {'state': 'missing_geometry', 'annotations': 1, 'ignored_image_level_tags': 2}],
])
def test_ignored_image_level_count_cannot_consume_ready_crops_or_exceed_its_state(states):
    with pytest.raises(ValueError, match='subset of missing-geometry annotations'):
        read_snapshot(Database(states=states))

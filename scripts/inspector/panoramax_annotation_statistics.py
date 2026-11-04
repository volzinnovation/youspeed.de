#!/usr/bin/env python3
"""Export crop counts including source annotations outside classifier inventories."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime
from io import StringIO
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inspector.server import CropStore, InspectorError
from scripts.inspector import sign_statistics as mobile_statistics
from scripts.tsr.source_annotation_labels import resolve_crop_labels

SOURCE = 'panoramax.woladen.de'
ROW_FIELDS = ['country', 'class_id', 'mobile_crops', 'panoramax_crops', 'total_crops',
              'classifier_supported', 'source_annotations_crops']
POOL_SQL = """
FROM youspeed.panoramax_features f
JOIN youspeed.panoramax_items i USING(source_id,picture_id)
JOIN youspeed.panoramax_sources s USING(source_id)
JOIN youspeed.panoramax_crops c ON c.crop_id=f.crop_id AND c.render_key=f.current_render
JOIN youspeed.panoramax_crop_objects o ON o.digest=c.digest
WHERE f.source_id='panoramax.woladen.de' AND f.active AND i.active AND f.state='ready'
"""
GROUP_SQL = """
WITH features AS MATERIALIZED (
 SELECT f.crop_id,f.picture_id,f.fingerprint
""" + POOL_SQL + """
), labels AS (
 SELECT f.crop_id,f.picture_id,
 COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
  'raw_tag',l.label->>'raw_tag','parsed',l.label->'parsed',
  'target_classifier_country',l.label->>'target_classifier_country',
  'country_resolution_state',l.label->>'country_resolution_state',
  'semantic_mapping_status',l.label->>'semantic_mapping_status',
  'semantic_candidates',l.label->'semantic_candidates',
  'yolo_mapping_status',l.label->>'yolo_mapping_status',
  'selected_yolo',l.label->'selected_yolo')) FILTER (WHERE l.crop_id IS NOT NULL),'[]'::jsonb) AS labels
 FROM features f
 LEFT JOIN youspeed.panoramax_class_labels l ON l.crop_id=f.crop_id
  AND l.fingerprint=f.fingerprint AND l.mapping_sha256=%s
 GROUP BY f.crop_id,f.picture_id
)
SELECT labels,count(*) AS crops FROM labels GROUP BY labels ORDER BY crops DESC,labels
"""
DENOMINATOR_SQL = """
SELECT count(*) AS ready_crops,count(DISTINCT f.crop_id) AS distinct_ready_crops
FROM youspeed.panoramax_features f
JOIN youspeed.panoramax_items i USING(source_id,picture_id)
WHERE f.source_id='panoramax.woladen.de' AND f.active AND i.active AND f.state='ready'
"""
JOIN_COUNT_SQL = 'SELECT count(*) AS joined_rows,count(DISTINCT f.crop_id) AS joined_crop_ids\n' + POOL_SQL
IGNORED_IMAGE_LEVEL_SQL = "(f.state='missing_geometry' AND f.annotation_id='image-level' AND f.metadata->>'shape' IS NULL)"
ANNOTATION_SQL = """
SELECT f.state,count(*) AS annotations,
 count(*) FILTER (WHERE """ + IGNORED_IMAGE_LEVEL_SQL + """) AS ignored_image_level_tags
FROM youspeed.panoramax_features f
JOIN youspeed.panoramax_items i USING(source_id,picture_id)
WHERE f.source_id='panoramax.woladen.de' AND f.active AND i.active
GROUP BY f.state ORDER BY annotations DESC,f.state
"""
SOURCE_CHECKPOINT_SQL = 'SELECT discovery_snapshot,crop_snapshot FROM youspeed.panoramax_sources WHERE source_id=%s'
LATEST_RUN_SQL = ("SELECT phase,report->'blocked_annotations' AS source_blocked_annotations "
                  'FROM youspeed.panoramax_sync_runs WHERE source_id=%s ORDER BY snapshot_at DESC LIMIT 1')


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer.')
    return value


def build_report(mobile_report, groups, catalogs, model_labels, *, total_panoramax_crops,
                 annotations_by_state=None):
    """Build an exclusive country/class ranking from one frozen source snapshot.

    Each grouped row describes distinct source crops, not an extra model
    inference. Classifier support is descriptive metadata and never filters a
    source annotation from the inventory. Duplicate tags within a crop resolve
    once; input groups with the same class merge into one output row.
    """
    total_panoramax_crops = _count(total_panoramax_crops, 'Panoramax crop total')
    expected_mobile = _count(mobile_report['total_crops'], 'Mobile crop total')
    if not isinstance(groups, list):
        raise ValueError('Panoramax label groups must be a list.')
    counts = defaultdict(lambda: {'mobile_crops': 0, 'panoramax_crops': 0})
    for row in mobile_report['classes']:
        if not isinstance(row.get('country'), str) or not isinstance(row.get('class_id'), str):
            raise ValueError('Mobile country and class ID must be strings.')
        counts[row['country'], row['class_id']]['mobile_crops'] += _count(row['count'], 'Mobile group count')
    if sum(row['mobile_crops'] for row in counts.values()) != expected_mobile:
        raise ValueError('Mobile country/class groups disagree with the stored-crop total.')

    statuses, bases = Counter(), Counter()
    grouped_total = 0
    requires_review = 0
    for group in groups:
        number = _count(group['crops'], 'Panoramax group count')
        grouped_total += number
        resolution = resolve_crop_labels(group['labels'], catalogs, model_labels=model_labels)
        statuses[resolution['status']] += number
        if resolution['status'] == 'unique' and resolution['class_id']:
            counts[resolution['country'], resolution['class_id']]['panoramax_crops'] += number
            bases[resolution['identity_basis']] += number
            if resolution['review_required']:
                requires_review += number
    if grouped_total != total_panoramax_crops:
        raise ValueError('Panoramax label groups disagree with the independent ready-crop total.')

    rows = sorted([
        dict(country=country, class_id=class_id, **values,
             total_crops=values['mobile_crops'] + values['panoramax_crops'],
             classifier_supported=class_id in model_labels.get(country, set()),
             source_annotations_crops=values['panoramax_crops'])
        for (country, class_id), values in counts.items()
        if values['mobile_crops'] + values['panoramax_crops'] > 0
    ], key=lambda row: (-row['total_crops'], row['country'], row['class_id']))
    unresolved = dict(sorted(((status, number) for status, number in statuses.items() if status != 'unique'),
                             key=lambda pair: (-pair[1], pair[0])))
    resolved_total = sum(row['panoramax_crops'] for row in rows)
    unresolved_total = sum(unresolved.values())
    if resolved_total != statuses.get('unique', 0) or resolved_total + unresolved_total != total_panoramax_crops:
        raise ValueError('Resolved and unresolved Panoramax crops do not partition the inventory.')
    ranked_total = sum(row['total_crops'] for row in rows)
    if ranked_total + unresolved_total != expected_mobile + total_panoramax_crops:
        raise ValueError('Class rows and unresolved crops do not reconcile with both source totals.')

    annotation_states = None
    active_pending_crops = ignored_image_level_tags = None
    if annotations_by_state is not None:
        annotation_states = []
        seen = set()
        for state in annotations_by_state:
            name = state['state']
            if not isinstance(name, str) or name in seen:
                raise ValueError('Annotation states must have unique string identities.')
            seen.add(name)
            number = _count(state['annotations'], 'Annotation count')
            # Older frozen inputs did not distinguish image-level metadata from
            # real missing-geometry annotations. Do not guess that distinction.
            ignored = state.get('ignored_image_level_tags', 0 if name != 'missing_geometry' else None)
            if ignored is not None:
                ignored = _count(ignored, 'Ignored image-level annotation count')
                if ignored > number or (ignored and name != 'missing_geometry'):
                    raise ValueError('Ignored image-level tags must be a subset of missing-geometry annotations.')
            annotation_states.append({'state': name, 'annotations': number, 'ignored_image_level_tags': ignored})
        annotation_states.sort(key=lambda row: (-row['annotations'], row['state']))
        if sum(row['annotations'] for row in annotation_states) < total_panoramax_crops:
            raise ValueError('Active annotations cannot be fewer than ready sign crops.')
        ready_annotations = next((row['annotations'] for row in annotation_states if row['state'] == 'ready'), 0)
        if ready_annotations != total_panoramax_crops:
            raise ValueError('Ready annotation-state count disagrees with the crop total.')
        if all(row['ignored_image_level_tags'] is not None for row in annotation_states):
            ignored_image_level_tags = sum(row['ignored_image_level_tags'] for row in annotation_states)
            active_pending_crops = sum(row['annotations'] - row['ignored_image_level_tags']
                                       for row in annotation_states if row['state'] != 'ready')

    return dict(
        schema='youspeed-annotation-class-statistics-v1', as_of=mobile_report.get('as_of'),
        source=SOURCE,
        sort_order='total_crops descending, country ascending, class_id ascending',
        grouping='Recorded model/annotation country and exact catalogue TSR class ID; countries remain separate.',
        mobile_definition='All retained stored mobile crops, including replay and inactive/expired records; labels are stored model predictions.',
        panoramax_definition='Active ready crops on active Panoramax source pictures with current crop/object metadata, all retained visibilities. Classes resolve from source annotations independently of current classifier support.',
        provenance_definition='Panoramax classifier-catalog and semantic mappings describe the same source annotations. Annotation authorship is not established; source annotations may be human or machine produced.',
        counting_policy='Each crop counts once in an exclusive country/class row or an unresolved bucket. Repeated tags and matching catalogue/semantic mappings do not add crops. Generic yes is detection-only. Classifier support is metadata, not an inclusion filter.',
        mobile_crops=expected_mobile, panoramax_crops=total_panoramax_crops,
        resolved_panoramax_crops=resolved_total, source_annotations_crops=resolved_total,
        unresolved_panoramax=unresolved, unresolved_panoramax_crops=unresolved_total,
        ranked_crops=ranked_total, all_crop_records=expected_mobile + total_panoramax_crops,
        row_count=len(rows), rows=rows, identity_basis_counts=dict(sorted(bases.items())),
        requires_review_panoramax_crops=requires_review, annotations_by_state=annotation_states,
        active_pending_crops=active_pending_crops, ignored_image_level_tags=ignored_image_level_tags,
        eligible_active_crop_work_remaining=None if active_pending_crops is None else active_pending_crops > 0,
        validation=dict(all_assertions_passed=True, mobile_group_sum=expected_mobile,
                        independent_ready_crops=total_panoramax_crops, grouped_panoramax_crops=grouped_total,
                        resolved_plus_unresolved=resolved_total + unresolved_total,
                        ranked_row_sum=ranked_total, country_class_keys_unique=True,
                        descending_count_order=True),
    )


def load_catalogs(directory=ROOT / 'shared/tsr'):
    catalogs, models = {}, {}
    for path in sorted(Path(directory).glob('prolix-*-class-catalog-v1.json')):
        catalog = json.loads(path.read_text())
        country = catalog['country']
        models[country] = set(catalog['class_labels'])
        catalogs[country] = models[country] | {sign['class_id'] for sign in catalog['signs']}
    if not catalogs:
        raise ValueError('No shared TSR catalogues are available.')
    return catalogs, models


def load_mapping(path):
    mapping = json.loads(Path(path).read_text())
    content = {key: value for key, value in mapping.items() if key != 'sha256'}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if mapping.get('sha256') != digest:
        raise ValueError('Panoramax reverse-mapping checksum does not match.')
    return mapping


class _SharedStore:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def connection(self):
        yield self.db


def snapshot(store, mapping, catalogs, model_labels):
    with store.connection() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        db.execute("SET LOCAL statement_timeout = '60000ms'")
        mobile = mobile_statistics.snapshot(_SharedStore(db))
        identity = db.execute("SELECT current_database() AS database,current_user AS role,"
                              "transaction_timestamp() AS as_of,current_setting('transaction_read_only') AS readonly,"
                              "current_setting('transaction_isolation') AS isolation").fetchone()
        if (identity['database'], identity['role'], identity['readonly'], identity['isolation']) != (
                'youspeed', 'youspeed_report', 'on', 'repeatable read'):
            raise InspectorError('Expected the youspeed_report read-only repeatable-read snapshot.')
        latest_mapping = db.execute("SELECT report->>'mapping_sha256' AS mapping_sha256 "
                                    "FROM youspeed.panoramax_sync_runs WHERE source_id=%s "
                                    "AND report ? 'mapping_sha256' ORDER BY snapshot_at DESC LIMIT 1", (SOURCE,)).fetchone()
        if not latest_mapping or latest_mapping['mapping_sha256'] != mapping['sha256']:
            raise InspectorError('The pinned reverse mapping differs from the latest imported mapping evidence.')
        independent = db.execute(DENOMINATOR_SQL).fetchone()
        joined = db.execute(JOIN_COUNT_SQL).fetchone()
        denominator = independent['ready_crops']
        if not (denominator == independent['distinct_ready_crops'] == joined['joined_rows'] == joined['joined_crop_ids']):
            raise InspectorError('Ready features and current crop/object joins disagree; report withheld.')
        groups = db.execute(GROUP_SQL, (mapping['sha256'],)).fetchall()
        states = db.execute(ANNOTATION_SQL).fetchall()
        source = db.execute(SOURCE_CHECKPOINT_SQL, (SOURCE,)).fetchone()
        run = db.execute(LATEST_RUN_SQL, (SOURCE,)).fetchone()
        blocked = run.get('source_blocked_annotations') if run else None
        if blocked is not None:
            blocked = _count(blocked, 'Source-blocked annotation count')
        report = build_report(mobile, groups, catalogs, model_labels, total_panoramax_crops=denominator,
                              annotations_by_state=states)
        if report['as_of'] != identity['as_of'].isoformat():
            raise InspectorError('Mobile and Panoramax sources did not share the same snapshot.')
    report.update(database=identity['database'], role=identity['role'], mapping_sha256=mapping['sha256'])
    report['panoramax_sync'] = dict(
        phase=run['phase'] if run else None,
        discovery_checkpoint=source['discovery_snapshot'].isoformat() if source and source['discovery_snapshot'] else None,
        crop_checkpoint=source['crop_snapshot'].isoformat() if source and source['crop_snapshot'] else None,
        source_blocked_annotations=blocked,
        active_pending_crops=report['active_pending_crops'],
        ignored_image_level_tags=report['ignored_image_level_tags'],
        eligible_active_crop_work_remaining=report['eligible_active_crop_work_remaining'],
        complete=bool(source and run and run['phase'] == 'complete'
                      and source['discovery_snapshot'] is not None and source['crop_snapshot'] is not None
                      and source['discovery_snapshot'] == source['crop_snapshot']
                      and blocked == 0 and report['active_pending_crops'] == 0),
    )
    report['validation'].update(read_only=True, repeatable_read=True, same_snapshot_for_all_sources=True,
                                independent_distinct_ready_crops=independent['distinct_ready_crops'],
                                joined_rows=joined['joined_rows'], joined_crop_ids=joined['joined_crop_ids'])
    return report


def markdown(report):
    def cell(value):
        return str(value).replace('&', '&amp;').replace('|', '&#124;').replace('`', '&#96;').replace('\r', ' ').replace('\n', ' ')
    as_of = report.get('as_of')
    timestamp = datetime.fromisoformat(as_of).astimezone(ZoneInfo('Europe/Berlin')).strftime('%d %B %Y, %H:%M %Z') if as_of else 'Not supplied'
    lines = ['# Annotation-inclusive TSR class crop counts', '', f'Snapshot: **{timestamp}**.', '',
             f"**{report['ranked_crops']:,} ranked crops**, including **{report['mobile_crops']:,} mobile crops** and **{report['resolved_panoramax_crops']:,} resolved Panoramax source-annotation crops**.", '',
             f"Another **{report['unresolved_panoramax_crops']:,} Panoramax ready crops** remain in unresolved class buckets. Complete retained crop inventory: **{report['all_crop_records']:,} crops**.", '',
             report['grouping'], report['counting_policy'], report['provenance_definition'], '',
             '| Country | TSR class ID | Mobile crops | Panoramax crops | Total crops | Classifier supports class |',
             '| --- | --- | ---: | ---: | ---: | --- |']
    for row in report['rows']:
        lines.append(f"| {cell(row['country'])} | `{cell(row['class_id'])}` | {row['mobile_crops']:,} | {row['panoramax_crops']:,} | {row['total_crops']:,} | {'yes' if row['classifier_supported'] else 'no'} |")
    lines += ['', '## Unresolved Panoramax crops', '', '| Status | Crops |', '| --- | ---: |']
    for status, number in report['unresolved_panoramax'].items():
        lines.append(f'| {cell(status)} | {number:,} |')
    lines += ['', report['mobile_definition'], report['panoramax_definition'], '',
              'Counts describe stored crops rather than reviewed ground truth, deduplicated physical signs, or training eligibility.', '']
    sync = report.get('panoramax_sync')
    if sync:
        blocked = sync.get('source_blocked_annotations')
        pending = sync.get('active_pending_crops')
        ignored = sync.get('ignored_image_level_tags')
        details = []
        if blocked is None:
            details += ['The latest source run did not record a source-blocked annotation count; that coverage measure is unknown.', '']
        else:
            details += [f"The latest source run reported **{blocked:,} source-blocked annotations**: annotations outside the configured source visibility or on deleted source pictures. These are excluded from ready-crop totals and from unresolved class counts.", '']
        if pending is None:
            details += ['Eligible active crop work remaining is unknown because the retained state counts do not distinguish image-level metadata without geometry.', '']
        elif pending:
            details += [f"**{pending:,} eligible active annotations still require crop processing or a geometry/source repair.** These are separate from ready crops whose class is unresolved.", '']
        else:
            details += ['**No eligible active crop work remains** in the imported corpus. Unresolved classes on ready crops do not represent pending crop extraction.', '']
        if ignored is not None:
            details += [f"**{ignored:,} image-level tags without crop geometry** are metadata-only and excluded from pending crop work.", '']
        causes = []
        if blocked is None:
            causes.append('source-blocked coverage is unknown')
        elif blocked:
            causes.append('source-admission blocks remain')
        if pending is None:
            causes.append('active crop-work coverage is unknown')
        elif pending:
            causes.append('eligible active crop work remains')
        if sync['phase'] != 'complete':
            causes.append(f"the latest source phase is {sync['phase']}")
        if (not sync['discovery_checkpoint'] or not sync['crop_checkpoint']
                or sync['discovery_checkpoint'] != sync['crop_checkpoint']):
            causes.append('discovery and completed crop checkpoints do not match')
        completion = ('The latest source sync is complete, checkpoints match, and no source blocks or eligible active crop work remain.'
                      if sync['complete'] else 'Full source completion is unconfirmed: '
                      + '; '.join(causes or ['the retained source run has not confirmed full completion']) + '.')
        coverage = [
            '## Source coverage and crop processing', '',
            f"Panoramax sync phase: `{sync['phase']}`. Discovery checkpoint: `{sync['discovery_checkpoint']}`. Crop checkpoint: `{sync['crop_checkpoint']}`.", '',
            completion, '',
        ] + details
        # Surface source exclusions beside the headline counts instead of only
        # after a long class table. The detailed explanations follow below.
        marker = lines.index('| Country | TSR class ID | Mobile crops | Panoramax crops | Total crops | Classifier supports class |')
        lines[marker:marker] = coverage
    return '\n'.join(lines)


def _atomic_write(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_report(report, output_dir, *, source_sql=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    buffer = StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=ROW_FIELDS)
    writer.writeheader()
    writer.writerows(report['rows'])
    files = {
        'annotation-class-statistics.json': json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        'annotation-class-statistics.csv': buffer.getvalue(),
        'annotation-class-statistics.md': markdown(report),
    }
    if source_sql is not None:
        files['source-query.sql'] = source_sql
    for name, content in files.items():
        _atomic_write(output_dir / name, content)
    with (output_dir / 'annotation-class-statistics.csv').open(newline='') as stream:
        actual = list(csv.DictReader(stream))
    if actual != [{key: str(row[key]) for key in ROW_FIELDS} for row in report['rows']]:
        raise ValueError('CSV and JSON class rows disagree.')
    receipt = dict(
        schema='youspeed-annotation-statistics-validation-v1', all_assertions_passed=True,
        as_of=report.get('as_of'), inventory_validation=report['validation'],
        csv_json_exact_match_files=['annotation-class-statistics.csv'],
        files={name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest() for name in sorted(files)},
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        resolver_sha256=hashlib.sha256((ROOT / 'scripts/tsr/source_annotation_labels.py').read_bytes()).hexdigest(),
        mobile_generator_sha256=hashlib.sha256((ROOT / 'scripts/inspector/sign_statistics.py').read_bytes()).hexdigest(),
    )
    _atomic_write(output_dir / 'validation.json', json.dumps(receipt, indent=2) + '\n')
    return receipt


def arguments(argv=None):
    defaults = mobile_statistics.arguments([])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-file', type=Path, default=defaults.database_file,
                        help='Existing private report DSN file; same defaults as Inspector')
    parser.add_argument('--db-host', help='Override the DSN host, e.g. an existing SSH tunnel')
    parser.add_argument('--db-port', type=int, help='Override the DSN port')
    parser.add_argument('--mapping-file', type=Path,
                        default=ROOT.parent / 'Woladen.de-analytics/commercial_backend/youspeed/panoramax-reverse-v1.json',
                        help='Existing pinned Panoramax reverse-mapping JSON')
    parser.add_argument('--output-dir', type=Path,
                        default=Path(tempfile.gettempdir()) / 'youspeed-annotation-class-statistics',
                        help='Local CSV/JSON/Markdown directory (default: %(default)s)')
    args = parser.parse_args(argv)
    args.db_user, args.media_root = defaults.db_user, defaults.media_root
    return args


def main(argv=None):
    args = arguments(argv)
    try:
        catalogs, model_labels = load_catalogs()
        mapping = load_mapping(args.mapping_file)
        report = snapshot(CropStore(args), mapping, catalogs, model_labels)
        source_sql = ('-- Run in the same REPEATABLE READ READ ONLY snapshot; bind mapping digest: '
                      + mapping['sha256'] + '\n\n-- Mobile crop grouping\n' + mobile_statistics.COUNTS_SQL
                      + ';\n\nSELECT count(*) AS count FROM youspeed.media;\n\n-- Panoramax source-label groups\n'
                      + GROUP_SQL + ';\n\n-- Independent ready and object-join counts\n' + DENOMINATOR_SQL
                      + ';\n' + JOIN_COUNT_SQL + ';\n\n-- Active annotation states\n' + ANNOTATION_SQL
                      + ';\n\n-- Contemporaneous source admission/checkpoints; bind source_id: ' + SOURCE + '\n'
                      + LATEST_RUN_SQL + ';\n' + SOURCE_CHECKPOINT_SQL + ';\n')
        export_report(report, args.output_dir, source_sql=source_sql)
    except (InspectorError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print('Cannot read the mapping/catalogues or write the local report files; check paths and permissions.', file=sys.stderr)
        return 1
    print(markdown(report), end='')
    print(f'Exported annotation-inclusive statistics to {args.output_dir.resolve()}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

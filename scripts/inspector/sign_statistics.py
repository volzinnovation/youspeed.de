#!/usr/bin/env python3
"""Print and export stored crop counts per country and class ID (descending)."""
from __future__ import annotations

import argparse
import csv
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inspector.server import CropStore, InspectorError, OBSERVATION_JOIN, default_connection_file


COUNTS_SQL = """
SELECT COALESCE(
    NULLIF(btrim(e.payload->'event'->'classification'->>'country'), ''),
    'unknown') AS country,
  COALESCE(
    NULLIF(btrim(e.payload->'event'->'classification'->>'model_label'), ''),
    '(unclassified)') AS class_id,
  count(*) AS count,
  count(DISTINCT (e.installation, e.epoch, e.event_id))
    FILTER (WHERE e.event_id IS NOT NULL) AS linked_sightings
FROM youspeed.media m
""" + OBSERVATION_JOIN + """
GROUP BY 1, 2
ORDER BY count DESC, country ASC, class_id ASC
"""


def snapshot(store):
    with store.connection() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        identity = db.execute(
            "SELECT current_database() AS database, current_user AS user, "
            "transaction_timestamp() AS as_of"
        ).fetchone()
        if identity['database'] != 'youspeed' or identity['user'] != 'youspeed_report':
            raise InspectorError('Expected database youspeed and read-only role youspeed_report.')
        invalid = db.execute("""
            SELECT count(*) AS count FROM youspeed.events e
            LEFT JOIN youspeed.class_ids c
              ON c.country=e.payload#>>'{event,classification,country}'
             AND c.class_id=e.payload#>>'{event,classification,model_label}'
            WHERE e.kind='sighting'
              AND e.payload#>>'{event,classification,model_label}' IS NOT NULL
              AND c.class_id IS NULL
        """).fetchone()['count']
        if invalid:
            raise InspectorError('Noncanonical class labels remain; apply class-ID migration 010 before reporting.')
        rows = db.execute(COUNTS_SQL).fetchall()
        total = db.execute("SELECT count(*) AS count FROM youspeed.media").fetchone()['count']
        if sum(row['count'] for row in rows) != total:
            raise InspectorError('Class counts do not match the stored crop total; report withheld.')
    return {
        'schema': 'youspeed-sign-statistics-v3',
        'as_of': identity['as_of'].isoformat(),
        'database': identity['database'],
        'user': identity['user'],
        'scope': 'All stored crops, including inactive or expired records and replay installations.',
        'country_definition': 'Recorded classification.country, or unknown when missing; model domain, not verified journey country.',
        'class_definition': 'Catalog class ID stored in classification.model_label; missing predictions use (unclassified). Display labels and national sign codes are not class IDs.',
        'count_definition': 'Stored crop records; multiple crops can belong to one sighting.',
        'total_crops': total,
        'class_count': len({row['class_id'] for row in rows}),
        'country_count': len({row['country'] for row in rows}),
        'group_count': len(rows),
        'classes': rows,
    }


def markdown(report):
    lines = [
        '# YouSpeed sign statistics', '',
        f"Snapshot (UTC): {report['as_of']}", '',
        report['scope'], report['country_definition'], report['class_definition'], report['count_definition'],
        'Recorded labels are not reviewed ground truth or deduplicated physical signs.', '',
        f"Total: **{report['total_crops']:,} crops** across **{report['group_count']} country/class groups** "
        f"(**{report['class_count']} classes**, **{report['country_count']} countries**, including unknown if present).", '',
        '| Country | Class ID | Count (crops) | Linked sightings |',
        '| --- | --- | ---: | ---: |',
    ]
    for row in report['classes']:
        label = (row['class_id'].replace('&', '&amp;').replace('<', '&lt;')
                 .replace('>', '&gt;').replace('\\', '&#92;').replace('|', '&#124;')
                 .replace('`', '&#96;').replace('*', '&#42;').replace('_', '&#95;')
                 .replace('[', '&#91;').replace(']', '&#93;')
                 .replace('\r', ' ').replace('\n', ' '))
        lines.append(f"| {row['country']} | {label} | {row['count']:,} | {row['linked_sightings']:,} |")
    return '\n'.join(lines) + '\n'


def export(report, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    buffer = StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=['country', 'class_id', 'count', 'linked_sightings'])
    writer.writeheader()
    writer.writerows(report['classes'])
    contents = {
        'sign-statistics.csv': buffer.getvalue(),
        'sign-statistics.json': json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        'sign-statistics.md': markdown(report),
    }
    # Replace each complete file atomically so readers never see truncated files.
    for name, content in contents.items():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                             dir=output_dir, delete=False) as file:
                temporary = Path(file.name)
                file.write(content)
            temporary.replace(output_dir / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-file', type=Path, default=default_connection_file(),
                        help='Existing private report DSN file (0600); same defaults as Inspector')
    parser.add_argument('--db-host', help='Override the DSN host, e.g. an existing SSH tunnel')
    parser.add_argument('--db-port', type=int, help='Override the DSN port')
    parser.add_argument('--output-dir', type=Path,
                        default=Path(tempfile.gettempdir()) / 'youspeed-sign-statistics',
                        help='Local CSV/JSON/Markdown directory (default: %(default)s)')
    args = parser.parse_args(argv)
    args.db_user = 'youspeed_report'
    args.media_root = None
    return args


def main(argv=None):
    args = arguments(argv)
    try:
        report = snapshot(CropStore(args))
        export(report, args.output_dir)
    except InspectorError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print('Cannot write the local report files; check output directory permissions.', file=sys.stderr)
        return 1
    print(markdown(report), end='')
    print(f"Exported CSV, JSON and Markdown to {args.output_dir.resolve()}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

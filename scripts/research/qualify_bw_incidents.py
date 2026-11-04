#!/usr/bin/env python3
"""One-shot, isolated BW incident qualification using the owning backend adapter.

No source registry, server, scheduler or device is changed. Repeat manually over
publication boundaries; raw sources and detailed record identities stay outside
Git in --evidence-root. This is a research receipt, not an activation command.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import resource
import sys
import time
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-root', type=Path, required=True)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--replay-receipt', type=Path, help='Re-evaluate a captured receipt with the current adapter, without network')
    args = parser.parse_args()
    backend = args.backend_root.resolve()
    evidence = args.evidence_root.resolve()
    client = Path(__file__).resolve().parents[2]
    if evidence in {backend, client} or backend in evidence.parents or client in evidence.parents:
        parser.error('Evidence must stay outside both repositories')
    sys.path.insert(0, str(backend))
    v2 = importlib.import_module('commercial_backend.youspeed.road_advisories')
    v1 = importlib.import_module('commercial_backend.youspeed.roadworks')
    config = next(c for c in v2.default_configs() if c.source_id == 'incidents-bw')
    assert not config.enabled and not config.active
    started = time.monotonic()
    if args.replay_receipt:
        captured = json.loads(args.replay_receipt.read_bytes())
        checked = v1.instant(captured['checked_at_utc'])
        body = (evidence / 'fetch/raw' / captured['raw_sha256']).read_bytes()
        if hashlib.sha256(body).hexdigest() != captured['raw_sha256']:
            raise ValueError('Captured raw checksum mismatch')
        raw = v1.Source('datex', body, captured['headers'], checked, captured['http_status'])
    else:
        checked = datetime.now(timezone.utc)
        raw = v2.Fetcher(evidence / 'fetch', 'incidents-bw').fetch(checked)
    fetched_seconds = time.monotonic() - started
    normalized = v2.normalize_datex(raw, config, checked)
    snapshot, data, receipt, lineage = normalized
    adapter_digest = hashlib.sha256((backend/'commercial_backend/youspeed/road_advisories.py').read_bytes()).hexdigest()
    # Keep parser revisions separate: unchanged raw input must still be replayed
    # after an adapter change, rather than reusing an earlier projection.
    store = v1.Store(evidence / 'projection' / adapter_digest)
    identity = store.promote(normalized, allow_anomaly=True)  # isolated acceptance replay only
    assert store.enabled is False
    ns = {'d': v2.NS}
    root = ET.fromstring(raw.body)
    records = root.findall('.//d:situationRecord', ns)
    features = snapshot['features']
    def eligible(feature):
        p = feature['properties']
        return (p['kind'] != 'unknown' and p['operator_status'] in {'requested', 'approved', 'implemented', 'reported'}
                and p['schedule_status'] == 'resolved' and v1.instant(p['outer_start']) <= checked < v1.instant(p['outer_end'])
                and any(v1.instant(i['start']) <= checked < v1.instant(i['end']) for i in p['active_intervals']))
    profile = Counter()
    record_state = {}
    for r in records:
        status = v1.text(v2._direct(r, 'validity'), 'validityStatus')
        spec = v2._direct(v2._direct(r, 'validity'), 'validityTimeSpecification')
        profile['overall_end_present' if v1.text(spec, 'overallEndTime') else 'overall_end_absent'] += 1
        profile['validity_status:' + str(status)] += 1
        profile['record_type:' + v2._type(r)] += 1
        for tag in ('validPeriod', 'exceptionPeriod', 'recurringTimePeriodOfDay', 'recurringDayWeekMonthPeriod'):
            profile[tag + '_present'] += bool(v1.descendants(r, tag))
        record_state[r.get('id')] = {'sha256': v1.sha(ET.tostring(r)), 'version': v1.text(r, 'situationRecordVersionTime')}
    previous_path = evidence / 'previous-records.json'
    previous = json.loads(previous_path.read_bytes()) if previous_path.exists() else None
    delta = None
    if previous is not None and not args.replay_receipt:

        old, new = set(previous), set(record_state)
        delta = {'added': len(new-old), 'disappeared': len(old-new),
                 'changed': sum(previous[k] != record_state[k] for k in old & new),
                 'unchanged': sum(previous[k] == record_state[k] for k in old & new)}
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.replay_receipt:
        previous_path.write_text(json.dumps(record_state, sort_keys=True))
    result = {'checked_at_utc': v1.utc(checked), 'method': 'Actual bounded HTTP fetch, archive, adapter and SQLite promotion in isolated disabled local store; no runtime activation.',
        'http_status': raw.status, 'headers': raw.headers, 'raw_sha256': raw.digest, 'decoded_bytes': len(raw.body),
        'normalized_sha256': hashlib.sha256(data).hexdigest(), 'normalized_bytes': len(data), 'projection_id': identity,
        'receipt': {k: v for k, v in receipt.items() if k != 'issues'},
        'quarantine_reasons': dict(Counter(i['code'] for i in receipt['issues'])),
        'profile': dict(sorted(profile.items())), 'kinds': dict(Counter(f['properties']['kind'] for f in features)),
        'schedule_status': dict(Counter(f['properties']['schedule_status'] for f in features)),
        'geometry_types': dict(Counter(f['geometry']['type'] for f in features)),
        'validity_basis': dict(Counter(f['properties'].get('validity_basis', 'legacy') for f in features)),
        'eligible_by_basis': dict(Counter(f['properties'].get('validity_basis', 'legacy') for f in features if eligible(f))),
        'eligible_by_kind': dict(Counter(f['properties']['kind'] for f in features if eligible(f))),
        'information_status': dict(Counter(e.text for e in root.findall('.//d:situation/d:headerInformation/d:informationStatus', ns))),
        'update_methods': [e.text for e in root.findall('d:exchange/d:subscription/d:updateMethod', ns)],
        'active_supported_features': sum(eligible(f) for f in features),
        'feature_flags': dict(Counter(flag for f in features for flag in f['properties']['quality_flags'])),
        'record_delta_from_previous_sample': delta,
        'freshness_evaluated_for_pilot_only': v2.freshness('incidents-bw', receipt, True, checked),
        'fetch_seconds': round(fetched_seconds, 3), 'total_seconds': round(time.monotonic()-started, 3),
        'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
        'runtime_enabled': False, 'backend_adapter_sha256': adapter_digest}
    name = 'replay-' + checked.strftime('%Y%m%dT%H%M%SZ') + '-' + adapter_digest[:12] if args.replay_receipt else 'sample-' + checked.strftime('%Y%m%dT%H%M%SZ')
    result['replay_of'] = str(args.replay_receipt) if args.replay_receipt else None
    path = evidence / (name + '.json')
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'receipt': str(path), 'publication': receipt['source_publication_at'], 'modified': receipt['source_modified_at'],
        'raw_sha256': raw.digest, 'http_status': raw.status, 'counts': {k: receipt[k] for k in ('membership_count','accepted_count','quarantined_count','cancelled_count')},
        'eligible_now': result['active_supported_features'], 'delta': delta, 'elapsed_seconds': result['total_seconds']}, ensure_ascii=False))


if __name__ == '__main__':
    main()

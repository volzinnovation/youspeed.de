#!/usr/bin/env python3
"""Capture immutable, explicitly incomplete d8 epoch metrics for publication."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from prepare_expanded_publication import ROOT, inventory, sha, write


def main():
    run = ROOT / 'latest-full'
    # The trainer atomically replaces history.json, so this byte snapshot is coherent.
    history_bytes = (run / 'history.json').read_bytes()
    history = json.loads(history_bytes)
    config = json.loads((run / 'configuration.json').read_text())
    assert [r['epoch'] for r in history] == list(range(history[-1]['epoch'] + 1))
    assert history[-1]['epoch'] < config['epochs'] == 150
    assert config['split_frames']['train'] == 5288
    assert all(r['training_samples_per_epoch'] == 5288 for r in history if r['epoch'] > 0)
    name = f"epoch-{history[-1]['epoch']:04d}"
    root = ROOT / 'progress-publication'
    prefix = 'detector/d8/progress/' + name
    out = root / prefix
    out.mkdir(parents=True, exist_ok=False)
    (out / 'history.json').write_bytes(history_bytes)
    write(out / 'configuration.json', config)
    fields = ('epoch', 'ap50_95', 'delta_previous_epoch', 'delta_epoch_zero',
              'best_ap50_95_so_far', 'ap50', 'precision', 'recall', 'duration_seconds',
              'training_samples_per_epoch', 'training_batches_per_epoch', 'optimizer_step_calls_total')
    best = -1
    previous = history[0]['ap50_95']
    with (out / 'epoch-improvements.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for row in history:
            best = max(best, row['ap50_95'])
            writer.writerow({**{k: row.get(k) for k in fields if k in row},
                'delta_previous_epoch': row['ap50_95'] - previous,
                'delta_epoch_zero': row['ap50_95'] - history[0]['ap50_95'],
                'best_ap50_95_so_far': best})
            previous = row['ap50_95']
    selected = max(history, key=lambda r: (r['ap50_95'], -r['epoch']))
    write(out / 'status.json', dict(schema='streetshots-d8-incomplete-progress-v1',
        captured_at_utc=datetime.now(timezone.utc).isoformat(), complete=False,
        completed_epochs=history[-1]['epoch'], planned_epochs=config['epochs'],
        best_epoch_so_far=selected['epoch'], best_development_ap50_95_so_far=selected['ap50_95'],
        history_sha256=sha(out / 'history.json'), final_checkpoint_selected=False,
        holdout_evaluated=False, script_sha256=sha(Path(__file__))))
    (out / 'README.md').write_text(f'''# d8 incomplete training snapshot

This immutable snapshot contains epochs 0 through {history[-1]['epoch']} of a planned 150-epoch run. Training is not complete and no final candidate or geographic result is reported here.

Training: 5,288 images, 4,410 sign boxes, predominantly teacher pseudo-labels; Ultralytics 8.4.213, whole-image 1024 input, batch 16, AMP, d4 initialization. Directions and supplementary plates are excluded. These are weak labels, not exhaustive human annotations.

Best development AP50–95 so far: {selected['ap50_95']:.2%} at epoch {selected['epoch']}. Latest completed epoch: {history[-1]['ap50_95']:.2%}. Epoch zero: {history[0]['ap50_95']:.2%}. Selection remains maximum development AP with earliest-epoch tie break, including epoch zero. Early changes do not establish an improvement.

[Per-epoch improvements](epoch-improvements.csv) · [Full metric and loss history](history.json) · [Configuration](configuration.json) · [Snapshot status](status.json)

The same 17-image development set has been reused. Final results, selected checkpoint, native phone comparison and the separately frozen geographic audit require completion and verification. This snapshot is not a deployment recommendation.
''')
    inventory(root, out, 'model', prefix + '/status.json', ROOT / (name + '-inventory.json'))


if __name__ == '__main__':
    main()

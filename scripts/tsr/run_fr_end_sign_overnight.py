#!/usr/bin/env python3
"""Detached, deadline-bounded KI experiment queue. Does not export or deploy models."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

IMAGE = 'youspeed-tsr-fr-end-training:20260924'
INITIAL = 'youspeed-fr-b31-b33-20260924'


def experiments():
    # Multiple seeds repeat the same comparisons; all runs start from original weights.
    for seed in (20260924, 20260925, 20260926):
        for scope, lr, augment in (
            ('linear', 1e-5, False), ('frozen-bn', 1e-5, False),
            ('frozen-bn', 3e-6, True), ('linear', 3e-5, True),
            ('full', 3e-6, False), ('frozen-bn', 1e-5, True),
        ):
            yield {'scope': scope, 'lr': lr, 'augment': augment, 'seed': seed}


def comparison(baseline, candidate):
    clean_b, clean_c = baseline['variants']['clean'], candidate['variants']['clean']
    return {'clean_top1_delta': clean_c['top1_accuracy'] - clean_b['top1_accuracy'],
            'clean_target_f1_delta': clean_c['target']['macro_f1'] - clean_b['target']['macro_f1'],
            'clean_non_regression': clean_c['top1_accuracy'] >= clean_b['top1_accuracy'] and
                                    clean_c['target']['macro_f1'] >= clean_b['target']['macro_f1'],
            'stress_target_f1_deltas': {key: candidate['variants'][key]['target']['macro_f1'] - value['target']['macro_f1']
                                       for key, value in baseline['variants'].items() if key != 'clean'},
            'deployment_approved': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--deadline', required=True, help='Absolute ISO UTC deadline, including initial-run wait')
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline).timestamp()
    output = args.root / 'overnight'
    output.mkdir(exist_ok=False)
    status = {'status': 'waiting_for_initial_run', 'deadline': args.deadline,
              'started_at': datetime.now(timezone.utc).isoformat(), 'runs': [], 'deployment_approved': False}

    def save():
        temp = output / 'status.tmp'
        temp.write_text(json.dumps(status, indent=2) + '\n')
        temp.replace(output / 'status.json')

    def remaining():
        return max(0, deadline - time.time())

    def run(name, command, seconds):
        status['active_container'] = name
        save()
        docker = ['docker', 'run', '--init', '--name', name, '--gpus', 'device=2', '--network', 'none',
                  '--user', '1003:1003', '--cpus', '8', '--memory', '16g', '--shm-size', '2g',
                  '-v', str(args.root) + ':/work', IMAGE, *command]
        with (output / (name + '.log')).open('w') as log:
            proc = subprocess.Popen(docker, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = proc.wait(timeout=max(1, min(seconds, remaining() - 55)))
            except subprocess.TimeoutExpired:
                subprocess.run(['docker', 'stop', '--time', '45', name], timeout=50, check=False)
                code = proc.wait(timeout=5)
        status['active_container'] = None
        save()
        return code

    def evaluate(name, model, folder):
        return run(name, ['/work/job/evaluate_fr_end_sign_robustness.py', '--model', model,
                         '--data', '/work/data-v2', '--output', folder], min(300, remaining()-55))

    save()
    while remaining() > 600:
        check = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', INITIAL],
                               capture_output=True, text=True, timeout=15, check=True)
        if check.stdout.strip() == 'false':
            break
        time.sleep(min(30, remaining()))
    if remaining() <= 600:
        status['status'] = 'deadline_before_additional_runs'
        save()
        return
    status['status'] = 'baseline_evaluation'
    if evaluate('youspeed-night-baseline', '/work/source/best.pt', '/work/overnight/baseline-eval') != 0:
        status['status'] = 'baseline_evaluation_failed'
        save()
        return
    baseline = json.loads((output / 'baseline-eval/summary.json').read_text())
    # Compare the initial pilot too, before launching lower-learning-rate experiments.
    if (args.root / 'training/weights/best.pt').exists():
        code = evaluate('youspeed-night-initial-eval', '/work/training/weights/best.pt', '/work/overnight/initial-eval')
        if code == 0:
            status['initial_comparison'] = comparison(baseline, json.loads((output / 'initial-eval/summary.json').read_text()))
    failures = 0
    for index, spec in enumerate(experiments(), 1):
        if remaining() < 600:
            break
        budget = min(2400, remaining() - 420)
        label = 'run-%02d' % index
        status['status'] = 'training'
        record = {'name': label, **spec, 'started_at': datetime.now(timezone.utc).isoformat()}
        status['runs'].append(record)
        command = ['/work/job/train_fr_end_sign_classifier.py', '--data', '/work/data-v2',
                   '--model', '/work/source/best.pt', '--output', '/work/overnight/' + label,
                   '--epochs', '30', '--batch', '32', '--workers', '4', '--lr', str(spec['lr']),
                   '--seed', str(spec['seed']), '--train-scope', spec['scope'],
                   '--max-hours', str((budget - 60) / 3600)]
        if spec['augment']:
            command.append('--augment')
        record['exit_code'] = run('youspeed-night-' + label, command, budget)
        checkpoint = output / label / 'weights/best.pt'
        if record['exit_code'] == 0 and checkpoint.exists() and remaining() > 180:
            status['status'] = 'candidate_evaluation'
            record['evaluation_exit_code'] = evaluate('youspeed-night-' + label + '-eval',
                '/work/overnight/' + label + '/weights/best.pt', '/work/overnight/' + label + '-eval')
            if record['evaluation_exit_code'] == 0:
                record['comparison'] = comparison(baseline, json.loads((output / (label + '-eval') / 'summary.json').read_text()))
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        failures = failures + 1 if record['exit_code'] != 0 else 0
        save()
        if failures >= 2:
            status['status'] = 'stopped_after_consecutive_failures'
            break
    else:
        status['status'] = 'experiments_completed'
    if status['status'] in ('training', 'candidate_evaluation'):
        status['status'] = 'budget_completed'
    status['finished_at'] = datetime.now(timezone.utc).isoformat()
    save()

if __name__ == '__main__':
    main()

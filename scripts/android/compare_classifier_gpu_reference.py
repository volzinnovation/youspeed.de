#!/usr/bin/env python3
"""Compare Android GPU vectors with hash-pinned CUDA vectors, without truth labels."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.tsr.de_field_gpu_reference import comparison


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def device_path_comparison(canonical, native, ids, classes):
    """Compare two FP16-runtime outputs without pretending either is FP32 truth."""
    assert canonical.shape == native.shape == (len(ids), len(classes))
    for scores in (canonical, native):
        assert np.isfinite(scores).all() and (scores >= 0).all()
        assert np.allclose(scores.sum(1), 1, atol=.02)
    delta = np.abs(canonical.astype(np.float64)-native.astype(np.float64))
    left, right = canonical.argmax(1), native.argmax(1)
    changed = np.flatnonzero(left != right)
    return {'images':len(ids),'classes':len(classes),'argmax_changes':len(changed),
            'max_probability_abs_error':float(delta.max()),
            'mean_probability_abs_error':float(delta.mean()),
            'p99_probability_abs_error':float(np.quantile(delta,.99)),
            'canonical_max_probability_sum_error':float(np.abs(canonical.sum(1)-1).max()),
            'native_max_probability_sum_error':float(np.abs(native.sum(1)-1).max()),
            'changes':[{'image_id':ids[i],'canonical_class':classes[int(left[i])],
                        'native_class':classes[int(right[i])]} for i in changed],
            'interpretation':'Raw device vectors; Android preprocessing/runtime comparison, not same-pixel CUDA parity or F1.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--reference-sha256', required=True)
    p.add_argument('--candidate-export', type=Path, required=True)
    a = p.parse_args()
    output = a.run / 'gpu-reference-parity.json'
    assert not output.exists(), 'Preserve immutable parity evidence'
    device_path = a.run / 'device-predictions.npz'
    reference_path = a.reference / 'gpu-reference-predictions.npz'
    provenance = json.loads((a.reference/'provenance.json').read_text())
    complete = json.loads((a.reference/'complete.json').read_text())
    assert sha(reference_path) == a.reference_sha256 == provenance['predictions_sha256'] == complete['predictions_sha256']
    assert sha(a.reference/'provenance.json') == complete['provenance_sha256']
    manifest = json.loads((a.inputs/'manifest.json').read_text())
    validation = json.loads((a.run/'independent-validation.json').read_text())
    assert validation['status']=='passed' and validation['manifestSha256']==sha(a.inputs/'manifest.json')
    assert validation['all_graphs_fully_gpu_delegated'], 'Actual GPU graph coverage is required'
    assert provenance['truth_labels_read'] is False and provenance['accuracy_or_f1_computed'] is False
    export = json.loads(a.candidate_export.read_text())
    device = dict(np.load(device_path, allow_pickle=False))
    reference = dict(np.load(reference_path, allow_pickle=False))
    ids = device['image_ids'].astype(str).tolist()
    reference_ids = reference['image_ids'].astype(str).tolist()
    assert len(ids)==len(set(ids))==96 and len(reference_ids)==len(set(reference_ids))
    assert ids==[r['id'] for r in manifest['images']]
    positions = [reference_ids.index(i) for i in ids]
    assert device['canonical_tensor_sha256'].astype(str).tolist()==reference['canonical_tensor_sha256'][positions].astype(str).tolist()
    models = {}
    for model in manifest['models']:
        name = model['id']; classes = model['classLabels']
        assert sha(a.inputs/model['path'])==model['sha256']
        assert classes==device[name+'_classes'].astype(str).tolist()==reference[name+'_classes'].astype(str).tolist()
        if name=='primary142':
            assert model['sha256']==export['artifact_sha256']
            assert provenance['models'][name]['checkpoint_sha256']==export['checkpoint_sha256']
        elif name=='primary136':
            assert provenance['models'][name]['checkpoint_sha256']=='2918071223bc115ae1341cd2ce363dad04b3ba3d377112e79340ed1a12964005'
        else:
            raise ValueError('Unreviewed model identity')
        expected = reference[name+'_canonical_scores'][positions]
        canonical, native = device[name+'_canonical_scores'], device[name+'_native_scores']
        same_pixels = comparison(expected, canonical, ids, classes)
        preprocessing = device_path_comparison(canonical, native, ids, classes)
        gates = {}
        for threshold in (.7,.9,.95):
            left = canonical.max(1)>=threshold; right=native.max(1)>=threshold
            gates[str(threshold)] = {'upward_crossings':[ids[i] for i in np.flatnonzero(~left & right)],
                                     'downward_crossings':[ids[i] for i in np.flatnonzero(left & ~right)]}
        models[name] = {'canonical_same_pixels':same_pixels,
                        'native_vs_canonical_device_preprocessing':preprocessing,
                        'native_vs_canonical_confidence_gate_crossings':gates}
    result = {'status':'compared','created_at':datetime.now(timezone.utc).isoformat(),
              'script_sha256':sha(__file__),'helper_sha256':sha(ROOT/'scripts/tsr/de_field_gpu_reference.py'),
              'device_predictions_sha256':sha(device_path),'reference_predictions_sha256':sha(reference_path),
              'reference_provenance_sha256':sha(a.reference/'provenance.json'),
              'manifest_sha256':sha(a.inputs/'manifest.json'),'candidate_export_sha256':sha(a.candidate_export),
              'image_count':96,'exact_canonical_tensor_hashes_verified':True,'fully_gpu_delegated':True,
              'models':models,'truth_labels_read':False,'accuracy_or_f1_computed':False,
              'limitations':['Numerical prediction agreement is not reference-label accuracy or F1.',
                             'Canonical parity compares identical RGB/255 tensors against CUDA FP32; export/FP16/runtime differences are combined.',
                             'Native-vs-canonical comparison combines Android resizing and runtime differences; no CUDA pass over the captured native tensors is claimed.']}
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':'compared','models':{k:{'canonical_argmax_changes':v['canonical_same_pixels']['argmax_changes'],
        'canonical_max_probability_error':v['canonical_same_pixels']['max_probability_abs_error'],
        'native_vs_canonical_argmax_changes':v['native_vs_canonical_device_preprocessing']['argmax_changes'],
        'confidence_gates':v['native_vs_canonical_confidence_gate_crossings']} for k,v in models.items()}}))


if __name__=='__main__': main()

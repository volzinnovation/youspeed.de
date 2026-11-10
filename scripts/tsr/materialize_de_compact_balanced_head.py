#!/usr/bin/env python3
"""Materialize the fixed development-selected uniform-control Small CE head.

This folds z/T + alpha*(log(uniform)-log(effective training prior)) into the
last affine layer. It is a class-balancing prototype, not evidence that observed
sign frequencies improve classification. All original source artifacts remain
immutable; native export, app deployment and device performance are out of scope.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

EXPECTED = {
    "checkpoint": "4e8574096e609eddc9d0ea4234d28ece1218508cc0d006f4fac78a7d8b18b447",
    "logits": "27d8661d3520c64c30a3a1434d9eb0b619b25949b2dca414cfec3e262f871d91",
    "selection": "716974da57f52b65c724ac0f2c213438c29755405181d2180c88c050340b32e8",
    "configuration": "e67897fec515784f0150dd5bd5448f83948354ec7bba0b6a0ab1a4e6a195c539",
    "metrics": "385f186a373d64ae4931574008111a455f47bef7afb888c191a37d9e72ca9e3b",
    "manifest": "e67c8699a705371b79d68ea534371e2ae0c5e74ce83be7fd62fce671a1cac9eb",
}
SELECTION = {"source": "uniform_control", "alpha": .1, "confidence_gate": None, "temperature": 1.5}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def fold_prior_head(weights, bias, training_prior, target_prior, selection):
    """Float64 coefficient calculation then FP32; conditional gates cannot fold."""
    if selection != SELECTION:
        raise ValueError("Only the exact frozen uniform-control selection is authorized")
    weights, bias, train, target = (np.asarray(x, dtype=np.float64) for x in
                                    (weights, bias, training_prior, target_prior))
    if (weights.ndim != 2 or weights.shape[0] != 136 or weights.shape[1] < 1
            or any(x.shape != (136,) for x in (bias, train, target))
            or not all(np.isfinite(x).all() for x in (weights, bias, train, target))
            or (train <= 0).any() or (target <= 0).any()
            or not np.isclose(train.sum(), 1.) or not np.isclose(target.sum(), 1.)
            or not np.allclose(target, np.full(136, 1 / 136), rtol=0, atol=1e-15)):
        raise ValueError("Finite DE136 affine weights and normalized positive priors with uniform target required")
    # Match the recorded prior experiment's normalization before logarithms.
    train, target = train / train.sum(), target / target.sum()
    offset = selection["alpha"] * (np.log(target) - np.log(train))
    folded_weights = (weights / selection["temperature"]).astype(np.float32)
    folded_bias = (bias / selection["temperature"] + offset).astype(np.float32)
    if not np.isfinite(folded_weights).all() or not np.isfinite(folded_bias).all():
        raise ValueError("Folded affine parameters overflow Float32")
    return folded_weights, folded_bias, offset


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--course-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError("Require a new candidate directory")
    sys.path.insert(0, str(args.course_root / "code"))
    import model_utils as mu
    import de_class_prior_experiment as prior
    import timm
    torch, _ultralytics, _np, Image, ImageOps = mu.dependencies()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    root = args.experiment_root / "phase2/results"
    neural = root / "neural-refinement/small_ce_cosine"
    control = root / "priors-refined-sightings/small_ce_cosine"
    inputs = {"checkpoint": neural / "best.pt", "logits": neural / "selected-val-logits.npz",
              "selection": control / "selected.json", "configuration": control / "configuration.json",
              "metrics": control / "metrics.json"}
    for name, path in inputs.items():
        if sha256(path) != EXPECTED[name]:
            raise ValueError(f"Frozen {name} bytes changed")
    selected = json.loads(inputs["selection"].read_text())
    config = json.loads(inputs["configuration"].read_text())
    original_metrics = json.loads(inputs["metrics"].read_text())
    classes = mu.load_classes(args.course_root / "data/dataset-v1/class-index.json")
    manifest, manifest_sha = mu.load_manifest(args.course_root / "data/dataset-v1", classes)
    if manifest_sha != EXPECTED["manifest"] or classes != config["class_names"] or classes != config["model_class_names"]:
        raise ValueError("Class index or manifest differs from fixed prior experiment")
    rows = mu.samples_for_split(args.course_root / "data/dataset-v1", manifest, "val", classes)
    with np.load(inputs["logits"], allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files}
    if (arrays["class_names"].tolist() != classes
            or arrays["val_sample_ids"].tolist() != [r["sample_id"] for r in rows]
            or arrays["val_groups"].tolist() != [r["group_id"] for r in rows]
            or arrays["val_labels"].tolist() != [r["class_index"] for r in rows]):
        raise ValueError("Exact frozen validation row/class order differs")
    prior.validate_partitions(arrays["dev_indices"], arrays["report_indices"], arrays["val_groups"], len(rows))
    checkpoint = torch.load(inputs["checkpoint"], map_location="cpu", weights_only=True)
    if (checkpoint["classes"] != classes or checkpoint["manifest_sha256"] != manifest_sha
            or checkpoint["normalization"] != "RGB/255 then ImageNet mean/std"
            or checkpoint["variant"] != "small_ce_cosine"):
        raise ValueError("Source checkpoint provenance or preprocessing differs")
    model = timm.create_model("mobilenetv3_small_100.lamb_in1k", pretrained=False, num_classes=136)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    weight, bias, offset = fold_prior_head(model.classifier.weight.detach().numpy(),
        model.classifier.bias.detach().numpy(), config["p_train"], config["target_priors"][selected["source"]], selected)
    adjusted_saved = prior.corrected_logits(arrays["val_logits"], config["p_train"],
        config["target_priors"][selected["source"]], selected["alpha"], selected["temperature"])
    saved_metrics = {}
    for split, key in (("dev", "dev_indices"), ("report", "report_indices")):
        indexes = arrays[key]
        result = prior.metrics(arrays["val_labels"][indexes], prior.softmax(adjusted_saved[indexes]), classes, np.arange(136))
        for metric in ("macro_f1_supported", "accuracy", "critical_micro_recall"):
            if abs(result[metric] - original_metrics[f"selected_{split}"][metric]) > 1e-14:
                raise ValueError("Fixed saved-logit correction did not reproduce recorded metrics")
        saved_metrics[split] = prior.compact(result)
    comparison_sources = {}
    for family in ("small136", "yolo136"):
        path = root / f"features/{family}.npz"
        metadata = json.loads(path.with_suffix(".json").read_text())
        if sha256(path) != metadata["npz_sha256"] or metadata["manifest_sha256"] != manifest_sha:
            raise ValueError("Comparison source hash differs")
        with np.load(path, allow_pickle=False) as data:
            for key in ("class_names", "val_sample_ids", "val_labels", "dev_indices", "report_indices"):
                if not np.array_equal(data[key], arrays[key]):
                    raise ValueError(f"Comparison {family} {key} is not aligned")
            comparison_sources[family] = {"logits": data["val_logits"], "metadata": metadata}
    args.output.mkdir(parents=True)
    folded_state = {key: value.clone() for key, value in checkpoint["state_dict"].items()}
    folded_state["classifier.weight"] = torch.from_numpy(weight)
    folded_state["classifier.bias"] = torch.from_numpy(bias)
    candidate = {**{key: value for key, value in checkpoint.items() if key != "state_dict"},
        "state_dict": folded_state, "format": "youspeed-uniform-prior-head-v1",
        "variant": "small_ce_cosine_uniform_control_head", "source_variant": checkpoint["variant"],
        "source_checkpoint_sha256": EXPECTED["checkpoint"], "prior_correction": {**selected,
            "training_prior": config["p_train"], "target_prior": config["target_priors"][selected["source"]],
            "configuration_sha256": EXPECTED["configuration"], "observation_prior": False},
        "architecture": "mobilenetv3_small_100.lamb_in1k", "resume_supported": False}
    artifact = args.output / "de136-small-balanced-head.pt"
    torch.save(candidate, artifact)
    # Forward the deserialized checkpoint, so parity also checks the actual artifact.
    restored = torch.load(artifact, map_location="cpu", weights_only=True)
    folded = deepcopy(model)
    folded.load_state_dict(restored["state_dict"], strict=True)
    for key, value in checkpoint["state_dict"].items():
        if key not in ("classifier.weight", "classifier.bias") and not torch.equal(value, restored["state_dict"][key]):
            raise ValueError("Folding modified a backbone tensor")
    model.float().eval().to(args.device); folded.float().eval().to(args.device)
    loader = torch.utils.data.DataLoader(mu.dataset(torch, np, Image, ImageOps, rows),
        batch_size=64, shuffle=False, num_workers=4, pin_memory=args.device.startswith("cuda"))
    original_logits, reference_logits, folded_logits = [], [], []
    with torch.inference_mode():
        for images, labels in loader:
            images = images.to(args.device)
            mean = images.new_tensor([.485, .456, .406])[None, :, None, None]
            std = images.new_tensor([.229, .224, .225])[None, :, None, None]
            normalized = (images - mean) / std
            raw = model(normalized)
            reference = raw / selected["temperature"] + raw.new_tensor(offset)[None, :]
            actual = folded(normalized)
            original_logits.append(raw.cpu().numpy()); reference_logits.append(reference.cpu().numpy())
            folded_logits.append(actual.cpu().numpy())
    raw, reference, actual = [np.concatenate(values) for values in (original_logits, reference_logits, folded_logits)]
    parity = {"rows": len(rows), "dtype": "float32", "autocast": False, "tf32": False,
        "max_absolute_logit_error": float(np.abs(reference - actual).max()),
        "max_absolute_probability_error": float(np.abs(prior.softmax(reference) - prior.softmax(actual)).max()),
        "folded_vs_explicit_correction_argmax_changes": int((reference.argmax(1) != actual.argmax(1)).sum()),
        "raw_fp32_vs_saved_amp_argmax_changes": int((raw.argmax(1) != arrays["val_logits"].argmax(1)).sum()),
        "balanced_fp32_vs_saved_amp_argmax_changes": int((actual.argmax(1) != adjusted_saved.argmax(1)).sum()),
        "checkpoint_reloaded_before_full_pixel_verification": True}
    dump(args.output / "pixel-parity.json", parity)
    reports = {}
    for split, key in (("development", "dev_indices"), ("report", "report_indices")):
        indexes = arrays[key]
        sources = {"raw_ce_fp32": raw, "balanced_ce_fp32": actual, "balanced_ce_saved_amp": adjusted_saved,
                   "frozen_small_kd_fp32": comparison_sources["small136"]["logits"],
                   "frozen_yolo136_fp32": comparison_sources["yolo136"]["logits"]}
        values = {name: prior.metrics(arrays["val_labels"][indexes], prior.softmax(logits[indexes]), classes, np.arange(136))
                  for name, logits in sources.items()}
        guards = {}
        for baseline in ("raw_ce_fp32", "frozen_small_kd_fp32", "frozen_yolo136_fp32"):
            violations = []
            for old, new in zip(values[baseline]["per_class"], values["balanced_ce_fp32"]["per_class"]):
                if old["critical"] and (new["fp"] > old["fp"] or new["fn"] > old["fn"]):
                    violations.append({"class_id": old["class_id"], "baseline_fp": old["fp"], "candidate_fp": new["fp"],
                                       "baseline_fn": old["fn"], "candidate_fn": new["fn"]})
            guards[baseline] = {"no_added_critical_errors": not violations, "violations": violations}
        dump(args.output / f"{split}-comparison.json", {"metrics": values, "critical_guards": guards})
        reports[split] = {"metrics": {name: prior.compact(value) for name, value in values.items()}, "critical_guards": guards,
            "raw_fp32_vs_saved_amp_argmax_changes": int((raw[indexes].argmax(1) != arrays["val_logits"][indexes].argmax(1)).sum()),
            "balanced_fp32_vs_saved_amp_argmax_changes": int((actual[indexes].argmax(1) != adjusted_saved[indexes].argmax(1)).sum())}
    np.savez_compressed(args.output / "pixel-results.npz", class_names=np.asarray(classes),
        val_sample_ids=arrays["val_sample_ids"], val_labels=arrays["val_labels"],
        val_groups=arrays["val_groups"], dev_indices=arrays["dev_indices"], report_indices=arrays["report_indices"],
        raw_ce_fp32_logits=raw, balanced_ce_fp32_logits=actual, explicit_corrected_fp32_logits=reference,
        balanced_saved_amp_logits=adjusted_saved)
    provenance = {"created_at": datetime.now(timezone.utc).isoformat(), "script_sha256": sha256(__file__),
        "prior_helper_sha256": sha256(prior.__file__), "course_helper_sha256": sha256(mu.__file__),
        "source_sha256": EXPECTED, "classes": classes, "selection": selected,
        "formula": "W'=W/T; b'=b/T+alpha*(log(uniform)-log(effective training prior))",
        "artifact_sha256": sha256(artifact), "artifact_bytes": artifact.stat().st_size,
        "parameters": sum(p.numel() for p in folded.parameters()), "head_and_backbone_compute_unchanged": True,
        "normalization": checkpoint["normalization"], "preprocessing": mu.PREPROCESSING,
        "torch": str(torch.__version__), "timm": timm.__version__, "numpy": np.__version__,
        "observation_frequency_benefit_claimed": False, "native_exported": False, "deployed": False,
        "test_pixels_opened": False, "pixel_parity": parity, "saved_logit_metrics_reproduced": saved_metrics,
        "diagnostic_comparisons": reports, "comparison_checkpoint_sha256": {
            name: source["metadata"]["checkpoint_sha256"] for name, source in comparison_sources.items()},
        "limitations": ["Prototype selected on reused historical validation; not independent field F1",
            "Uniform class balancing is not an observation-derived prior benefit",
            "Higher macro-F1 than old Small KD can coexist with worse critical-class recall and extra per-class FP/FN",
            "No native export, detector evaluation or real-device cost measured",
            "Source CE training/dev split has no city truth in dev and one city report group"]}
    dump(args.output / "provenance.json", provenance)
    if parity["folded_vs_explicit_correction_argmax_changes"] or parity["max_absolute_probability_error"] > 1e-4:
        raise ValueError("Folded artifact failed the full-pixel Float32 parity gate")
    dump(args.output / "complete.json", {"artifact_sha256": sha256(artifact), "parity_passed": True,
        "artifacts": {p.name: sha256(p) for p in sorted(args.output.iterdir()) if p.is_file()}})
    print(json.dumps({"artifact_sha256": sha256(artifact), "pixel_parity": parity,
                      "report": reports["report"]}), flush=True)


if __name__ == "__main__":
    main()

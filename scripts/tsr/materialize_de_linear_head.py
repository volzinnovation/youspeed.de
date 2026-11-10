#!/usr/bin/env python3
"""Materialize the frozen-YOLO134 development-selected logistic DE136 head.

Consumes only hash-verified artifacts owned by this experiment, folds the
standardizer into one Float32 Linear layer, and checks numerical equivalence.
No deployment, app modification, native conversion or test-pixel access occurs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


MODEL_SHA256 = "8e411fa032cf6f779d7b0fa69ce3e4a98dcdf24843461f40f61657f289aef988"
FEATURE_SHA256 = "ca553641a6cfdfb82e9ec4547230aa221a6c196c7324e386731ad40035b30ce6"
MANIFEST_SHA256 = "e67c8699a705371b79d68ea534371e2ae0c5e74ce83be7fd62fce671a1cac9eb"
SELECTED = "logistic_c1_balanced"


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--course-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--image-count", type=int, default=64)
    parser.add_argument("--maximum-probability-error", type=float, default=1e-4)
    args = parser.parse_args()
    if args.output.exists() or args.image_count < 8 or not 0 < args.maximum_probability_error <= 1e-3:
        raise ValueError("Require a new output directory, at least eight images and a bounded probability tolerance")
    sys.path.insert(0, str(args.course_root / "code"))
    import model_utils as mu
    from de_linear_head import fold_standardized_head, parity_report, stable_softmax
    import de_linear_head
    torch, ultralytics, np, Image, ImageOps = mu.dependencies()
    import joblib
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    phase = args.experiment_root / "phase2"
    run = phase / "results/classical/yolo134"
    selected_dir = run / SELECTED
    selection = json.loads((run / "selection.json").read_text())
    configuration = json.loads((run / "configuration.json").read_text())
    cost = json.loads((selected_dir / "cost.json").read_text())
    feature_path = phase / "results/features/yolo134.npz"
    feature_metadata = json.loads(feature_path.with_suffix(".json").read_text())
    model_path = selected_dir / "model.joblib"
    if selection["selected_candidate"] != SELECTED:
        raise ValueError("Development selection changed; refusing to substitute a candidate")
    if sha256(model_path) != MODEL_SHA256 or cost["model_sha256"] != MODEL_SHA256:
        raise ValueError("Selected fitted model bytes changed")
    if sha256(feature_path) != FEATURE_SHA256 or configuration["feature_npz_sha256"] != FEATURE_SHA256:
        raise ValueError("Frozen feature bytes changed")
    if feature_metadata["checkpoint_sha256"] != mu.BASELINE_SHA256 or feature_metadata["manifest_sha256"] != MANIFEST_SHA256:
        raise ValueError("Feature extractor or dataset provenance differs")
    if sklearn.__version__ != configuration["environment"]["sklearn"]:
        raise ValueError("Use the fitted model's recorded sklearn runtime")
    classes = mu.load_classes(args.course_root / "data/dataset-v1/class-index.json")
    if configuration["classes"] != classes:
        raise ValueError("Fitted model class order differs from the original class index")
    manifest, manifest_sha = mu.load_manifest(args.course_root / "data/dataset-v1", classes)
    if manifest_sha != MANIFEST_SHA256:
        raise ValueError("Frozen source manifest changed")
    validation = mu.samples_for_split(args.course_root / "data/dataset-v1", manifest, "val", classes)
    with np.load(feature_path, allow_pickle=False) as source:
        features = source["val_features"]
        feature_ids = source["val_sample_ids"]
        feature_labels = source["val_labels"]
        feature_classes = source["class_names"].tolist()
    if feature_ids.tolist() != [row["sample_id"] for row in validation] or feature_classes != classes:
        raise ValueError("Frozen features do not align with the validated source rows")
    if feature_labels.tolist() != [row["class_index"] for row in validation]:
        raise ValueError("Frozen validation labels differ")
    # This joblib was produced by our bounded experiment and is checked above
    # before its pickle-capable loader is invoked.
    estimator = joblib.load(model_path)
    if len(estimator.steps) != 2 or not isinstance(estimator.steps[0][1], StandardScaler) or not isinstance(estimator.steps[1][1], LogisticRegression):
        raise ValueError("Expected the fitted scaler plus multinomial logistic pipeline")
    scaler, classifier = estimator.steps[0][1], estimator.steps[1][1]
    if not scaler.with_mean or not scaler.with_std or classifier.solver != "lbfgs":
        raise ValueError("Scaler options or logistic probability link differ")
    parameters = {"mean": scaler.mean_, "scale": scaler.scale_, "coef": classifier.coef_,
                  "intercept": classifier.intercept_, "estimator_classes": classifier.classes_,
                  "class_names": np.asarray(classes)}
    weights, bias = fold_standardized_head(parameters["mean"], parameters["scale"], parameters["coef"],
            parameters["intercept"], parameters["estimator_classes"], classes, classes, dtype="float32")
    numeric_parity = parity_report(features, parameters["mean"], parameters["scale"], parameters["coef"],
                                    parameters["intercept"], weights, bias)
    with threadpool_limits(limits=1):
        reference = estimator.predict_proba(features)
        folded_logits = features @ weights.T + bias
    folded_probabilities = stable_softmax(folded_logits)
    with np.load(selected_dir / "validation-probabilities.npz", allow_pickle=False) as saved:
        if saved["val_sample_ids"].tolist() != feature_ids.tolist():
            raise ValueError("Saved classifier probabilities do not align")
        saved_probabilities = saved["probabilities"]
    numeric_parity["saved_probability_max_error"] = float(np.abs(reference - saved_probabilities).max())
    numeric_parity["folded_vs_sklearn_max_probability_error"] = float(np.abs(folded_probabilities - reference).max())
    numeric_parity["folded_vs_sklearn_argmax_disagreements"] = int((folded_probabilities.argmax(1) != reference.argmax(1)).sum())
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output / "fitted-logistic-parameters.npz", **parameters)
    np.savez_compressed(args.output / "folded-linear-head.npz", weights=weights, bias=bias, class_names=np.asarray(classes))
    dump(args.output / "feature-parity.json", numeric_parity)
    if (numeric_parity["folded_vs_sklearn_argmax_disagreements"] or
            numeric_parity["folded_vs_sklearn_max_probability_error"] > args.maximum_probability_error or
            numeric_parity["saved_probability_max_error"] > 1e-6):
        raise ValueError("Float32 head failed the predeclared frozen-feature parity gate")
    model = mu.extend_classifier(torch, mu.load_baseline(torch, ultralytics, args.course_root / "models/baseline.pt", classes), classes)
    head = model.model[-1].linear
    if weights.shape != tuple(head.weight.shape) or bias.shape != tuple(head.bias.shape):
        raise ValueError("Folded head dimensions differ from the neural head")
    with torch.no_grad():
        head.weight.copy_(torch.from_numpy(weights)); head.bias.copy_(torch.from_numpy(bias))
    if hasattr(model, "yaml"):
        model.yaml = {**model.yaml, "nc": len(classes)}
    if hasattr(model, "nc"):
        model.nc = len(classes)
    model.names = dict(enumerate(classes))
    model.eval().to(args.device)
    city = [index for index, row in enumerate(validation) if row["class_index"] >= 134]
    remaining = [index for index, row in enumerate(validation) if row["class_index"] < 134]
    remaining.sort(key=lambda index: hashlib.sha256(("fold-parity-20261109:" + validation[index]["sample_id"]).encode()).hexdigest())
    indices = sorted(city + remaining[:max(0, args.image_count - len(city))])
    selected_rows = [validation[index] for index in indices]
    loader = torch.utils.data.DataLoader(mu.dataset(torch, np, Image, ImageOps, selected_rows),
                                        batch_size=args.image_count, shuffle=False, num_workers=0)
    probabilities, image_logits = [], []
    with torch.inference_mode():
        for images, _labels in loader:
            logits = mu.logits_from_output(model(images.to(args.device)))
            image_logits.append(logits.cpu().numpy())
            probabilities.append(logits.softmax(1).cpu().numpy())
    image_logits = np.concatenate(image_logits)
    probabilities = np.concatenate(probabilities)
    expected = reference[indices]
    image_parity = {
        "rows": len(indices), "indices": indices,
        "sample_ids": [row["sample_id"] for row in selected_rows],
        "source_sha256": [row["sha256"] for row in selected_rows],
        "city_rows": len(city), "selection": "all eight city validation rows plus deterministic hash-ranked old-class rows; no prediction-dependent choice",
        "max_probability_error_vs_sklearn": float(np.abs(probabilities - expected).max()),
        "argmax_disagreements_vs_sklearn": int((probabilities.argmax(1) != expected.argmax(1)).sum()),
        "max_logit_error_vs_folded_saved_features": float(np.abs(image_logits - folded_logits[indices]).max()),
        "device": args.device, "torch": str(torch.__version__), "dtype": "float32",
        "probability_tolerance": args.maximum_probability_error,
        "preprocessing": mu.PREPROCESSING,
    }
    dump(args.output / "image-parity.json", image_parity)
    if image_parity["argmax_disagreements_vs_sklearn"] or image_parity["max_probability_error_vs_sklearn"] > args.maximum_probability_error:
        raise ValueError("Actual pixel-forward outputs failed the predeclared parity gate")
    provenance = {
        "created_at": datetime.now(timezone.utc).isoformat(), "script_sha256": sha256(__file__),
        "folding_script_sha256": sha256(de_linear_head.__file__), "course_helper_sha256": sha256(mu.__file__),
        "baseline_sha256": mu.BASELINE_SHA256, "fitted_model_sha256": MODEL_SHA256,
        "feature_npz_sha256": FEATURE_SHA256, "manifest_sha256": manifest_sha,
        "selected_candidate": SELECTED, "selection_sha256": sha256(run / "selection.json"),
        "class_index_sha256": sha256(args.course_root / "data/dataset-v1/class-index.json"),
        "classes": classes, "formula": "W'=coef/scale; b'=intercept-W'@mean",
        "head_dtype": "float32", "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "probability_link": "multinomial softmax", "observation_prior_applied": False,
        "preprocessing": mu.PREPROCESSING, "numpy": np.__version__, "sklearn": sklearn.__version__,
        "torch": str(torch.__version__), "ultralytics": ultralytics.__version__,
        "feature_parity_passed": True, "sampled_pixel_parity_passed": True,
        "test_pixels_opened": False, "native_exported": False, "deployed": False,
        "limitations": ["Original pretraining exposure and reused historical evaluation remain.",
                       "Pixel parity covers a deterministic64-image sample, not all field images.",
                       "No Core ML/LiteRT conversion or physical-device performance has been verified.",
                       "This is a useful concrete candidate, not a release approval or a claim of best overall F1."]}
    model.cpu().float()
    safe_checkpoint = {"format": "youspeed-folded-linear-head-state-v1", "state_dict": model.state_dict(),
                       "classes": classes, "baseline_sha256": mu.BASELINE_SHA256,
                       "manifest_sha256": manifest_sha, "preprocessing": mu.PREPROCESSING,
                       "provenance": provenance}
    safe_path = args.output / "de136-linear-head-state.pt"
    torch.save(safe_checkpoint, safe_path)
    checkpoint_path = args.output / "de136-linear-head-ultralytics.pt"
    torch.save({"model": deepcopy(model), "ema": None, "optimizer": None, "updates": 0, "epoch": -1,
                "date": provenance["created_at"], "version": ultralytics.__version__,
                "train_args": {"task": "classify", "imgsz": 224}, "youspeed_provenance": provenance}, checkpoint_path)
    reloaded = ultralytics.YOLO(str(checkpoint_path), task="classify").model.float().eval().to(args.device)
    names = [reloaded.names[index] for index in range(len(reloaded.names))]
    if names != classes:
        raise ValueError("Serialized Ultralytics checkpoint changed class names")
    restored = []
    with torch.inference_mode():
        for images, _labels in loader:
            logits = mu.logits_from_output(reloaded(images.to(args.device)))
            restored.append(logits.softmax(1).cpu().numpy())
    reload_error = float(np.abs(np.concatenate(restored) - probabilities).max())
    if reload_error > 1e-7:
        raise ValueError("Checkpoint serialization changed sampled predictions")
    provenance["ultralytics_reload_probability_error"] = reload_error
    provenance["artifact_sha256"] = {path.name: sha256(path) for path in args.output.iterdir() if path.is_file()}
    provenance["artifact_bytes"] = {path.name: path.stat().st_size for path in args.output.iterdir() if path.is_file()}
    dump(args.output / "provenance.json", provenance)
    dump(args.output / "complete.json", {"completed_at": datetime.now(timezone.utc).isoformat(),
         "state_checkpoint_sha256": sha256(safe_path), "ultralytics_checkpoint_sha256": sha256(checkpoint_path),
         "feature_argmax_disagreements": 0, "pixel_argmax_disagreements": 0,
         "checkpoint_reload_max_probability_error": reload_error, "deployed": False})
    print(json.dumps({"status": "complete", "feature_parity": numeric_parity,
                      "image_probability_error": image_parity["max_probability_error_vs_sklearn"],
                      "checkpoint": str(checkpoint_path), "checkpoint_sha256": sha256(checkpoint_path)}), flush=True)


if __name__ == "__main__":
    main()

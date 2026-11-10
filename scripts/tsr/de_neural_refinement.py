#!/usr/bin/env python3
"""Refine DE crop classifiers using train data and a bound dev/report partition.

The historical validation corpus was previously inspected and the upstream
teacher may have trained on some of its images. The report partition is a
diagnostic comparison, not an independent field test. Reserved test images
are never opened. No observation-derived pseudo labels enter supervised loss.
Requires the existing pinned course helper and isolated CUDA runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import sys
import time


STUDENT_WEIGHTS = {
    "small": ("mobilenetv3_small_100.lamb_in1k", "46d2c063b18125884c48937afa4c49e18128869e52e8db96df48bf0a4d7ff697"),
    "large": ("mobilenetv3_large_100.ra_in1k", "f425af34cc1cead2b5d6211f789a1f30b94835dc32f9c0fcc5a916e4fd2dde85"),
}
VARIANTS = {
    "yolo_ce_cosine": {"family": "yolo", "epochs": 10, "learning_rate": 3e-5, "head_learning_rate": 3e-4, "tau": 0.0},
    "yolo_balanced_cosine": {"family": "yolo", "epochs": 10, "learning_rate": 3e-5, "head_learning_rate": 3e-4, "tau": 0.25},
    "small_ce_cosine": {"family": "small", "epochs": 20, "learning_rate": 3e-4, "head_learning_rate": 1e-3, "tau": 0.0},
    "large_ce_cosine": {"family": "large", "epochs": 20, "learning_rate": 3e-4, "head_learning_rate": 1e-3, "tau": 0.0},
}


def dump(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def log_prior_offsets(counts, tau):
    """Training-only tempered Balanced Softmax offsets; raw logits at evaluation."""
    if not math.isfinite(tau) or tau < 0:
        raise ValueError("Nonnegative finite tau required")
    if not counts or any(not math.isfinite(c) or c <= 0 for c in counts):
        raise ValueError("Every training class requires positive finite support")
    total = sum(counts)
    return [tau * math.log(count / total) for count in counts]


def epoch_learning_rate(base, head, epoch, total):
    if not 1 <= epoch <= total or total < 2 or base <= 0 or head <= 0:
        raise ValueError("Invalid cosine schedule")
    if epoch == 1:
        return head
    progress = (epoch - 2) / max(1, total - 2)
    return base * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))


def validate_partition(partition, rows, manifest_sha, classes):
    if partition.get("manifest_sha256") != manifest_sha:
        raise ValueError("Partition belongs to another dataset manifest")
    if partition.get("val_sample_ids") != [row["sample_id"] for row in rows]:
        raise ValueError("Partition validation sample order does not match")
    if "classes" in partition and partition["classes"] != classes:
        raise ValueError("Partition class order does not match")
    if "val_group_ids" in partition and partition["val_group_ids"] != [row["group_id"] for row in rows]:
        raise ValueError("Partition group order does not match")
    dev, report = partition.get("dev_indices"), partition.get("report_indices")
    for name, indexes in (("dev", dev), ("report", report)):
        if not isinstance(indexes, list) or not indexes:
            raise ValueError(f"{name} partition is empty or invalid")
        if any(type(i) is not int or not 0 <= i < len(rows) for i in indexes):
            raise ValueError(f"Invalid {name} index")
        if len(set(indexes)) != len(indexes):
            raise ValueError(f"Repeated {name} index")
    if set(dev) & set(report) or set(dev) | set(report) != set(range(len(rows))):
        raise ValueError("Partitions must cover validation exactly once")
    for key in ("group_id", "sha256", "sample_id"):
        if {rows[i][key] for i in dev} & {rows[i][key] for i in report}:
            raise ValueError(f"Cross-partition {key} overlap")
    for key in ("rgb_sha256", "source_id"):
        left = {rows[i].get(key) for i in dev if rows[i].get(key)}
        right = {rows[i].get(key) for i in report if rows[i].get(key)}
        if left & right:
            raise ValueError(f"Cross-partition {key} overlap")
    return dev, report


def select_parameters(model, family, head_only):
    for name, parameter in model.named_parameters():
        head = ".linear." in name if family == "yolo" else name.startswith(("classifier.", "conv_head."))
        parameter.requires_grad_(not head_only or head)


def city_dev_repair(partition, train, val, classes):
    """Move the smallest viable whole city-training group set into development.

    Selection uses only group identities and label support, never predictions or
    report performance. Prefer one group, then minimum removed training rows,
    then lexical group identity. Every class must remain in training.
    """
    city = {"city:start", "city:end"}
    if any(val[i]["label"] in city for i in partition["dev_indices"]):
        raise ValueError("City development repair requires an originally city-empty dev set")
    groups = sorted({r["group_id"] for r in train if r["label"] in city})
    candidates = []
    for size in range(1, len(groups) + 1):
        for selected in itertools.combinations(groups, size):
            held = [r for r in train if r["group_id"] in selected]
            kept = [r for r in train if r["group_id"] not in selected]
            if city <= {r["label"] for r in held} and set(classes) <= {r["label"] for r in kept}:
                candidates.append((len(held), selected, kept, held))
        if candidates:
            break
    if not candidates:
        raise ValueError("No city group holdout preserves all training classes")
    _, selected, kept, held = min(candidates, key=lambda item: (item[0], item[1]))
    augmented = val + held
    repaired = dict(partition)
    repaired.update(val_sample_ids=[r["sample_id"] for r in augmented],
                    val_group_ids=[r["group_id"] for r in augmented],
                    dev_indices=partition["dev_indices"] + list(range(len(val), len(augmented))),
                    report_indices=list(partition["report_indices"]))
    for key in ("sample_id", "group_id", "sha256", "rgb_sha256", "source_id"):
        train_keys = {r[key] for r in kept if r.get(key)}
        evaluation_keys = {r[key] for r in augmented if r.get(key)}
        if train_keys & evaluation_keys:
            raise ValueError(f"Training/evaluation {key} overlap after city holdout")
    audit = {
        "protocol": "city-dev-repair-v1",
        "reason": "Original dev has no city support and cannot select city learning; followup after that protocol defect was observed",
        "selection_rule": "Fewest whole city-training groups, then fewest removed rows, then lexical group IDs; require both city labels held out and every class retained in training",
        "selected_groups": list(selected), "heldout_sample_ids": [r["sample_id"] for r in held],
        "candidate_group_counts": {g: dict(Counter(r["label"] for r in train if r["group_id"] == g)) for g in groups},
        "original_train_count": len(train), "repaired_train_count": len(kept),
        "original_val_count": len(val), "augmented_val_count": len(augmented),
        "original_train_class_counts": dict(Counter(r["label"] for r in train)),
        "repaired_train_class_counts": dict(Counter(r["label"] for r in kept)),
        "added_dev_class_counts": dict(Counter(r["label"] for r in held)),
        "report_sample_ids": [val[i]["sample_id"] for i in partition["report_indices"]],
        "report_unchanged": True, "selection_uses_report_predictions": False,
        "limitations": ["Followup motivated by inspected earlier diagnostic results", "Held-out city crops were training data in earlier completed runs but are excluded from these fresh baseline-initialized fits", "One added city dev group, four crops; weak development support", "Original report remains reused diagnostic evidence, not a blind test"],
    }
    repaired["city_dev_repair"] = {"selected_groups": list(selected), "original_val_count": len(val)}
    return kept, augmented, repaired, audit


def source_annotation_augmentation(path, train, val, reserved, classes, manifest_sha, Image, ImageOps):
    """Admit immutable source assertions after whole-group evaluation exclusions."""
    source = json.loads(path.read_text())
    if source.get("existing_manifest_sha256") != manifest_sha:
        raise ValueError("Source intake overlap audit is bound to another historical manifest")
    samples = source["samples"]
    if len({r["sample_id"] for r in samples}) != len(samples):
        raise ValueError("Duplicate source intake sample ID")
    evaluation = val + reserved
    eval_ids = {r["sample_id"] for r in evaluation}
    excluded_groups, checks = set(), []
    prepared = []
    for row in samples:
        if row.get("label_origin") != "source_annotation" or row["label"] not in classes:
            raise ValueError("Source augmentation requires a supported source annotation label")
        if row["class_index"] != classes.index(row["label"]):
            raise ValueError("Source class index mismatch")
        file = (path.parent / row["path"]).resolve()
        if not file.is_relative_to(path.parent.resolve()):
            raise ValueError("Source path escapes the frozen intake")
        if hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Source encoded hash mismatch")
        with Image.open(file) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            rectangle = row["geometry"]["sign_in_crop"]
            if (len(rectangle) != 4 or any(type(x) not in (int, float) or int(x) != x for x in rectangle)
                    or not 0 <= rectangle[0] < rectangle[2] <= image.width
                    or not 0 <= rectangle[1] < rectangle[3] <= image.height):
                raise ValueError("Invalid source sign rectangle")
            rectangle = [int(x) for x in rectangle]
            sign = image.crop(rectangle)
            def rgb_digest(value):
                return hashlib.sha256(str(value.size).encode() + b"\0" + value.tobytes()).hexdigest()
            if rgb_digest(image) != row["rgb_sha256"] or rgb_digest(sign) != row["sign_rgb_sha256"]:
                raise ValueError("Source native or sign RGB hash mismatch")
        reasons = []
        for key in ("sample_id", "source_id", "group_id", "sha256"):
            if row.get(key) and row[key] in {r[key] for r in evaluation if r.get(key)}:
                reasons.append("evaluation_" + key)
        eval_rgb = {r["rgb_sha256"] for r in evaluation if r.get("rgb_sha256")}
        if {row["rgb_sha256"], row["sign_rgb_sha256"]} & eval_rgb:
            reasons.append("evaluation_native_or_sign_rgb_sha256")
        if set(row.get("group_identities", [])) & {r["group_id"] for r in evaluation}:
            reasons.append("evaluation_group_identity")
        if any(match.get("sample_id") in eval_ids or match.get("group_id") in {r["group_id"] for r in evaluation}
               for match in row.get("existing_matches", [])):
            reasons.append("intake_existing_evaluation_match")
        if set(row.get("existing_split_memberships", [])) & {"val", "test"}:
            reasons.append("intake_existing_evaluation_split")
        if reasons:
            excluded_groups.add(row["group_id"])
        checks.append({"sample_id": row["sample_id"], "group_id": row["group_id"], "direct_exclusion_reasons": reasons})
        prepared.append({**row, "resolved_path": str(file), "training_crop_box": rectangle,
                         "origin": "panoramax_source_annotation", "source_supplement": True})
    train_file = {r["sha256"] for r in train}
    train_rgb = {r["rgb_sha256"] for r in train if r.get("rgb_sha256")}
    train_ids = {r["sample_id"] for r in train}
    accepted = []
    seen_pixels = set(train_rgb)
    for row, check in zip(prepared, checks):
        reasons = list(check["direct_exclusion_reasons"])
        if row["group_id"] in excluded_groups:
            reasons.append("connected_group_evaluation_overlap")
        if row["sample_id"] in train_ids or row["sha256"] in train_file or row["sign_rgb_sha256"] in seen_pixels:
            reasons.append("duplicate_training_sample_or_sign_pixels")
        check["exclusion_reasons"] = sorted(set(reasons))
        check["included_in_training"] = not reasons
        if not reasons:
            accepted.append(row)
            seen_pixels.add(row["sign_rgb_sha256"])
    if not accepted:
        raise ValueError("No source annotation remains after overlap and duplicate exclusion")
    audit = {
        "protocol": "source-annotation-augmentation-v1", "input_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "existing_manifest_sha256": manifest_sha, "source_intake_count": len(samples),
        "training_source_count": len(accepted), "source_intake_class_counts": dict(Counter(r["label"] for r in samples)),
        "training_source_class_counts": dict(Counter(r["label"] for r in accepted)),
        "historical_training_count": len(train), "augmented_training_count": len(train) + len(accepted),
        "source_fraction_per_epoch": len(accepted) / (len(train) + len(accepted)),
        "source_repetition_per_epoch": 1, "oversampling": False,
        "excluded_connected_groups": sorted(excluded_groups), "records": checks,
        "input_preprocessing": "Verify native PNG and dimensions-prefixed RGB SHA; crop explicit geometry.sign_in_crop; full sign resized bilinear224 with the same modest training photometric augmentation",
        "label_policy": "Source annotation assertions accepted for supervised training; no classifier-qualified pseudo-labels and no claim of certified human labels",
        "evaluation_policy": "No source samples enter dev/report; exclude whole connected source groups with known evaluation source/group/file/native-pixel/sign-pixel matches; original report unchanged",
        "limitations": ["Source metadata cannot exclude unrecorded near-duplicate views or unknown route overlap", "Historical evaluation remains reused diagnostic evidence, not source-distribution field F1"],
    }
    return train + accepted, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--course-code", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--student-models", type=Path, required=True)
    parser.add_argument("--partition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument("--city-dev-holdout", action="store_true", help="Repair missing city development support using whole training groups; preserves original report")
    parser.add_argument("--source-annotations", type=Path, help="Frozen source-labelled native-crop intake, training only")
    args = parser.parse_args()
    if args.batch_size < 1 or args.workers < 0 or args.output.exists():
        raise ValueError("Positive batch size, nonnegative workers and a new output directory required")
    if not args.device.startswith("cuda"):
        raise ValueError("This mixed-precision refinement requires an assigned CUDA device")
    if args.source_annotations and (not args.city_dev_holdout or args.variants != ["yolo_ce_cosine"]):
        raise ValueError("Source followup is predeclared as repaired-dev YOLO CE only")
    sys.path.insert(0, str(args.course_code))
    import model_utils as mu
    torch, ultralytics, np, Image, ImageOps = mu.dependencies()
    from PIL import ImageEnhance, ImageFilter
    import timm
    from safetensors.torch import load_file
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    device = mu.device_for(torch, args.device)
    classes = mu.load_classes(args.data / "class-index.json")
    manifest, manifest_sha = mu.load_manifest(args.data, classes)
    train = mu.samples_for_split(args.data, manifest, "train", classes, require_all=True)
    val = mu.samples_for_split(args.data, manifest, "val", classes)
    partition = json.loads(args.partition.read_text())
    dev_indices, report_indices = validate_partition(partition, val, manifest_sha, classes)
    original_partition = partition
    repair_audit = None
    if args.city_dev_holdout:
        train, val, partition, repair_audit = city_dev_repair(partition, train, val, classes)
        dev_indices, report_indices = validate_partition(partition, val, manifest_sha, classes)
    source_audit = None
    if args.source_annotations:
        reserved = [row for row in manifest["samples"] if row["split"] == "test"]
        train, source_audit = source_annotation_augmentation(args.source_annotations, train, val, reserved,
                                                            classes, manifest_sha, Image, ImageOps)
    dev = [val[i] for i in dev_indices]
    report = [val[i] for i in report_indices]
    counts_by_class = Counter(row["label"] for row in train)
    counts = [counts_by_class[name] for name in classes]
    args.output.mkdir(parents=True)
    (args.output / "executed-de_neural_refinement.py").write_bytes(Path(__file__).read_bytes())
    dump(args.output / "partition.json", partition)
    if repair_audit:
        dump(args.output / "original-partition.json", original_partition)
        dump(args.output / "city-dev-repair.json", repair_audit)
    if source_audit:
        dump(args.output / "source-augmentation.json", source_audit)
        dump(args.output / "source-intake-manifest.json", json.loads(args.source_annotations.read_text()))
    config = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "script_sha256": mu.sha256(Path(__file__)),
        "helper_sha256": mu.sha256(args.course_code / "model_utils.py"),
        "manifest_sha256": manifest_sha, "partition_sha256": mu.sha256(args.output / "partition.json") if repair_audit else mu.sha256(args.partition),
        "original_partition_sha256": mu.sha256(args.partition), "city_dev_repair": repair_audit is not None,
        "source_annotation_augmentation": source_audit is not None,
        "baseline_sha256": mu.BASELINE_SHA256,
        "classes": classes, "seed": args.seed, "variants": {k: VARIANTS[k] for k in args.variants},
        "train_count": len(train), "dev_count": len(dev), "report_count": len(report),
        "train_class_counts": dict(counts_by_class),
        "dev_class_counts": dict(Counter(row["label"] for row in dev)),
        "report_class_counts": dict(Counter(row["label"] for row in report)),
        "selection": "maximum dev macro-F1 over fixed dev-supported classes; earliest epoch wins ties",
        "report_use": "Scored only after epoch selection per predefined variant; not an independent or untouched field test",
        "loss": "cross_entropy(raw_logits + tau*log(training_class_prior), target); tau0 is CE; evaluate unadjusted raw logits",
        "prior_semantics": {
            "training_counts": "Use train_class_counts, never dev/report or observation counts for the loss offset",
            "raw_logit_prior_power_by_variant": {k: 1.0 - VARIANTS[k]["tau"] for k in args.variants},
            "status": "Analytical assumption under ideal fitted cross-entropy and label shift; not a measured or calibrated model prior",
            "posthoc_warning": "For tau=.25, raw logits have already undergone a training prior adjustment. Do not automatically divide by the full empirical training prior again; account for the training loss or exclude this model from plain label-shift correction.",
        },
        "warmup": "Epoch1 head-only with backbone BatchNorm eval; all parameters and BN train afterwards",
        "schedule": "Explicit head epoch followed by cosine learning rate from base to10%base",
        "optimizer": "AdamW, weight_decay1e-4; no distillation or observation-frequency prior",
        "preprocessing": "Full crop EXIF-transposed RGB; bilinear224 resize; /255; MobileNet adds ImageNet mean/std",
        "augmentation": "Training only: independent brightness/contrast factorsU(.9,1.1);10%Gaussianblur radiusU(.2,.6) after resize; no flips, crop, rotations or hue changes",
        "test_pixels_opened": False, "human_reviewed": manifest.get("human_reviewed"),
        "torch": str(torch.__version__), "ultralytics": ultralytics.__version__, "timm": timm.__version__,
        "gpu": torch.cuda.get_device_name(device),
        "limitations": ["Historical validation previously inspected", "Teacher pretrained exposure unresolved", "Only supported classes enter each partition macro-F1; class coverage differs between partitions", "One group of eight city validation crops; dev may have no city support", "Assistant city labels", "Single seed", "New recipes differ from earlier KD pilots beyond loss", "Historical crops are not exact current native runtime ROIs"],
    }
    dump(args.output / "configuration.json", config)
    dump(args.output / "partition.json", partition)
    dump(args.output / "training-identities.json", [
        {key: row.get(key) for key in ("sample_id", "sha256", "rgb_sha256", "group_id", "class_index", "label", "origin", "source_id", "sign_rgb_sha256", "training_crop_box", "source_supplement", "collection_ids", "sequence_ids")}
        for row in train
    ])
    dump(args.output / "validation-identities.json", [
        {key: row.get(key) for key in ("sample_id", "sha256", "rgb_sha256", "group_id", "class_index", "label", "origin", "source_id")}
        for row in val
    ])

    class TrainCrops(torch.utils.data.Dataset):
        def __len__(self):
            return len(train)

        def __getitem__(self, index):
            row = train[index]
            with Image.open(row["resolved_path"]) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                if row.get("training_crop_box"):
                    image = image.crop(row["training_crop_box"])
                image = image.resize((224, 224), Image.Resampling.BILINEAR)
                image = ImageEnhance.Brightness(image).enhance(random.uniform(0.9, 1.1))
                image = ImageEnhance.Contrast(image).enhance(random.uniform(0.9, 1.1))
                if random.random() < 0.1:
                    image = image.filter(ImageFilter.GaussianBlur(random.uniform(0.2, 0.6)))
                pixels = np.asarray(image, dtype=np.float32).copy() / 255.0
            return torch.from_numpy(pixels).permute(2, 0, 1), row["class_index"], bool(row.get("source_supplement"))

    def seed_worker(_worker_id):
        worker_seed = torch.initial_seed() % (2 ** 32)
        random.seed(worker_seed); np.random.seed(worker_seed)

    def make_eval_loader(rows):
        return torch.utils.data.DataLoader(mu.dataset(torch, np, Image, ImageOps, rows),
                    batch_size=args.batch_size, shuffle=False, num_workers=args.workers, pin_memory=True)

    dev_loader = make_eval_loader(dev)
    report_loader = make_eval_loader(report)
    mean = torch.tensor([.485, .456, .406], device=device)[None, :, None, None]
    std = torch.tensor([.229, .224, .225], device=device)[None, :, None, None]

    def forward(model, images, family):
        if family != "yolo":
            images = (images - mean) / std
        return mu.logits_from_output(model(images))

    def evaluate(model, family, loader):
        model.eval()
        targets, logits = [], []
        with torch.inference_mode():
            for images, labels in loader:
                with torch.autocast("cuda", dtype=torch.float16):
                    output = forward(model, images.to(device, non_blocking=True), family)
                targets.extend(labels.tolist())
                logits.append(output.float().cpu().numpy())
        values = np.concatenate(logits)
        predictions = values.argmax(axis=1).tolist()
        return mu.metrics_from_predictions(targets, predictions, classes), predictions, values

    def save_npz(path, values):
        np.savez_compressed(path, **values)

    results = []
    for variant in args.variants:
        recipe = VARIANTS[variant]
        family, epochs = recipe["family"], recipe["epochs"]
        random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        out = args.output / variant
        out.mkdir()
        if family == "yolo":
            model = mu.extend_classifier(torch, mu.load_baseline(torch, ultralytics, args.model, classes), classes)
            initialization_sha = mu.BASELINE_SHA256
        else:
            name, initialization_sha = STUDENT_WEIGHTS[family]
            path = args.student_models / f"mobilenetv3_{family}.safetensors"
            if mu.sha256(path) != initialization_sha:
                raise ValueError(f"Unexpected {family} initialization")
            model = timm.create_model(name, pretrained=False)
            model.load_state_dict(load_file(str(path)), strict=True)
            model.reset_classifier(len(classes))
        model.to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=recipe["learning_rate"], weight_decay=1e-4)
        scaler = torch.amp.GradScaler("cuda")
        adjustment = torch.tensor(log_prior_offsets(counts, recipe["tau"]), device=device)
        loader = torch.utils.data.DataLoader(TrainCrops(), batch_size=args.batch_size, shuffle=True,
                    num_workers=args.workers, pin_memory=True, worker_init_fn=seed_worker,
                    generator=torch.Generator().manual_seed(args.seed))
        history, best_score = [], -1.0
        started = time.monotonic()
        for epoch in range(1, epochs + 1):
            rate = epoch_learning_rate(recipe["learning_rate"], recipe["head_learning_rate"], epoch, epochs)
            for group in optimizer.param_groups:
                group["lr"] = rate
            warmup = epoch == 1
            select_parameters(model, family, warmup)
            model.eval() if warmup else model.train()
            seen, source_seen, loss_sum = 0, 0, 0.0
            epoch_started = time.monotonic()
            for batch, (images, labels, source_flags) in enumerate(loader):
                images, labels = images.to(device, non_blocking=True), labels.to(device, non_blocking=True)
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast("cuda", dtype=torch.float16):
                    output = forward(model, images, family)
                    loss = torch.nn.functional.cross_entropy(output.float() + adjustment, labels)
                scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update()
                seen += len(labels); loss_sum += loss.item() * len(labels)
                source_seen += int(source_flags.sum().item())
                if batch % 100 == 0:
                    print(json.dumps({"variant": variant, "epoch": epoch, "batch": batch, "loss": loss_sum / seen}), flush=True)
            metrics, predictions, logits = evaluate(model, family, dev_loader)
            record = {"epoch": epoch, "learning_rate": rate, "train_loss": loss_sum / seen,
                      "train_samples_seen": seen, "source_samples_seen": source_seen,
                      "seconds": time.monotonic() - epoch_started,
                      "dev_accuracy": metrics["accuracy"], "dev_macro_f1": metrics["macro_f1_supported"],
                      "dev_old_macro_f1": metrics["old_class_macro_f1_supported"],
                      "dev_city_macro_f1": metrics["city_macro_f1_supported"]}
            history.append(record)
            if seen != len(train) or source_seen != (source_audit["training_source_count"] if source_audit else 0):
                raise ValueError("Observed training exposure does not match the fixed single-pass corpus")
            dump(out / "history.json", history)
            if metrics["macro_f1_supported"] > best_score:
                best_score = metrics["macro_f1_supported"]
                dump(out / "selected-epoch.json", record)
                dump(out / "dev-metrics.json", metrics)
                dump(out / "dev-predictions.json", predictions)
                save_npz(out / "dev-logits.npz", {"logits": logits})
                torch.save({"state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                            "classes": classes, "variant": variant, "family": family, "epoch": epoch,
                            "initialization_sha256": initialization_sha, "manifest_sha256": manifest_sha,
                            "partition_sha256": config["partition_sha256"], "resume_supported": False,
                            "normalization": "RGB/255" if family == "yolo" else "RGB/255 then ImageNet mean/std"}, out / "best.pt")
            print(json.dumps({"variant": variant, **record}), flush=True)
        checkpoint = torch.load(out / "best.pt", map_location=device, weights_only=True)
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        dump(out / "selection-frozen.json", {
            "at": datetime.now(timezone.utc).isoformat(), "epoch": checkpoint["epoch"],
            "checkpoint_sha256": mu.sha256(out / "best.pt"), "report_scored_yet": False,
        })
        metrics, predictions, report_logits = evaluate(model, family, report_loader)
        dump(out / "report-metrics.json", metrics)
        dump(out / "report-predictions.json", predictions)
        values = np.empty((len(val), len(classes)), dtype=np.float32)
        with np.load(out / "dev-logits.npz", allow_pickle=False) as stored:
            values[dev_indices] = stored["logits"]
        values[report_indices] = report_logits
        save_npz(out / "selected-val-logits.npz", {
            "val_logits": values, "val_labels": np.asarray([r["class_index"] for r in val], dtype=np.int64),
            "class_names": np.asarray(classes), "dev_indices": np.asarray(dev_indices, dtype=np.int64),
            "report_indices": np.asarray(report_indices, dtype=np.int64),
            "val_sample_ids": np.asarray([r["sample_id"] for r in val]),
            "val_groups": np.asarray([r["group_id"] for r in val]),
            "train_labels": np.asarray([r["class_index"] for r in train], dtype=np.int64),
        })
        results.append({"variant": variant, "family": family, "epochs": epochs, "selected_epoch": checkpoint["epoch"],
                        "best_dev_macro_f1": best_score, "report_macro_f1": metrics["macro_f1_supported"],
                        "report_old_macro_f1": metrics["old_class_macro_f1_supported"],
                        "report_city_macro_f1": metrics["city_macro_f1_supported"],
                        "seconds": time.monotonic() - started,
                        "parameters": sum(p.numel() for p in model.parameters()),
                        "checkpoint_sha256": mu.sha256(out / "best.pt")})
        dump(args.output / "summary.json", results)
        del model, optimizer, scaler, checkpoint
        torch.cuda.empty_cache()

    # The baseline report is computed after all predefined training selection.
    baseline = mu.load_baseline(torch, ultralytics, args.model, classes).to(device).eval()
    for name, loader in (("dev", dev_loader), ("report", report_loader)):
        metrics, predictions, _ = evaluate(baseline, "yolo", loader)
        dump(args.output / f"baseline-{name}-metrics.json", metrics)
        dump(args.output / f"baseline-{name}-predictions.json", predictions)
    dump(args.output / "complete.json", {"at": datetime.now(timezone.utc).isoformat(),
          "variants": args.variants, "test_pixels_opened": False, "report_used_for_selection": False})


if __name__ == "__main__":
    main()

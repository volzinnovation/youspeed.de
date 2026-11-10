#!/usr/bin/env python3
"""Run bounded DE classifier pilots, without opening reserved test images.

The existing course train/validation split is a diagnostic replay, NOT an
independent test: the original teacher may have seen its upstream images.
Requires the pinned course model_utils.py, torch 2.6, Ultralytics 8.4.56,
timm 1.0.22 and safetensors 0.6.2. Run in an isolated, network-disabled runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import time


STUDENT_WEIGHTS = {
    "small": ("mobilenetv3_small_100.lamb_in1k", "46d2c063b18125884c48937afa4c49e18128869e52e8db96df48bf0a4d7ff697"),
    "large": ("mobilenetv3_large_100.ra_in1k", "f425af34cc1cead2b5d6211f789a1f30b94835dc32f9c0fcc5a916e4fd2dde85"),
}
VARIANTS = ("yolo_ce", "yolo_kd", "small_kd", "large_kd")


def dump(path, obj):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def distillation_loss(torch, student_logits, teacher_logits, labels, temperature=2.0):
    """The 134-class teacher has no authority over the two new city classes."""
    eligible = labels < 134
    if not eligible.any():
        return student_logits.sum() * 0.0
    return torch.nn.functional.kl_div(
        torch.nn.functional.log_softmax(student_logits[eligible, :134] / temperature, dim=1),
        torch.nn.functional.softmax(teacher_logits[eligible] / temperature, dim=1),
        reduction="batchmean",
    ) * temperature ** 2


def select_training_parameters(model, variant, head_only):
    for name, parameter in model.named_parameters():
        is_head = ".linear." in name if variant.startswith("yolo") else name.startswith(("classifier.", "conv_head."))
        parameter.requires_grad_(not head_only or is_head)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--course-code", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--student-models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=20261109)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1 or args.workers < 0 or args.output.exists():
        raise ValueError("Positive epochs/batch size, nonnegative workers and new output directory required")
    if not args.device.startswith("cuda"):
        raise ValueError("This mixed-precision pilot requires an assigned CUDA device")
    sys.path.insert(0, str(args.course_code))
    import model_utils as mu
    torch, ultralytics, np, Image, ImageOps = mu.dependencies()
    import timm
    from safetensors.torch import load_file
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    device = mu.device_for(torch, args.device)
    classes = mu.load_classes(args.data / "class-index.json")
    manifest, manifest_sha = mu.load_manifest(args.data, classes)
    # Manifest grouping metadata is checked for all splits. Only train/val
    # pixel bytes are opened, hashed, decoded or passed through a model.
    train = mu.samples_for_split(args.data, manifest, "train", classes, require_all=True)
    val = mu.samples_for_split(args.data, manifest, "val", classes)
    args.output.mkdir(parents=True)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "fixed-budget feasibility pilot; not independent acceptance F1",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helper_sha256": mu.sha256(args.course_code / "model_utils.py"),
        "manifest_sha256": manifest_sha, "baseline_sha256": mu.BASELINE_SHA256,
        "baseline_may_have_seen_old_corpus": True,
        "human_reviewed": manifest.get("human_reviewed"),
        "test_pixels_opened": False,
        "train_count": len(train), "validation_count": len(val),
        "train_class_counts": dict(Counter(row["label"] for row in train)),
        "validation_class_counts": dict(Counter(row["label"] for row in val)),
        "classes": classes, "epochs": args.epochs, "seed": args.seed,
        "torch": str(torch.__version__), "timm": timm.__version__,
        "ultralytics": ultralytics.__version__,
        "device": str(device), "gpu": torch.cuda.get_device_name(device),
        "preprocessing": "full crop RGB bilinear resize224; /255; timm additionally ImageNet mean/std",
        "augmentation": "none in this screening pilot",
        "selection": "highest supported-class validation macro-F1 within fixed epoch budget",
        "kd": {"temperature": 2.0, "weight": 0.5, "classes": "shared134", "mask": "exclude city labels134,135"},
        "warmup": "epoch1 head-only with backbone including BatchNorm held in eval; then all parameters",
        "limitations": ["upstream pretrained exposure", "assistant labels for city examples", "incomplete physical-site grouping", "single seed and short unequal-initialization convergence", "no current mobile crops or field test"],
    }
    dump(args.output / "configuration.json", metadata)
    train_ds = mu.dataset(torch, np, Image, ImageOps, train)
    val_ds = mu.dataset(torch, np, Image, ImageOps, val)
    val_loader = torch.utils.data.DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                                           num_workers=args.workers, pin_memory=True)
    teacher = mu.load_baseline(torch, ultralytics, args.model, classes).to(device).eval()
    for parameter in teacher.parameters():
        parameter.requires_grad_(False)

    def logits(model, images, variant):
        if not variant.startswith("yolo"):
            mean = images.new_tensor([0.485, 0.456, 0.406])[None, :, None, None]
            std = images.new_tensor([0.229, 0.224, 0.225])[None, :, None, None]
            images = (images - mean) / std
        return mu.logits_from_output(model(images))

    def evaluate(model, variant):
        model.eval()
        truth, predictions = [], []
        with torch.inference_mode():
            for images, labels in val_loader:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    result = logits(model, images.to(device, non_blocking=True), variant)
                truth.extend(labels.tolist())
                predictions.extend(result.argmax(1).cpu().tolist())
        return mu.metrics_from_predictions(truth, predictions, classes), predictions

    baseline_metrics, baseline_predictions = evaluate(teacher, "yolo_baseline")
    dump(args.output / "baseline-validation.json", baseline_metrics)
    dump(args.output / "validation-identities.json", [{"sample_id": r["sample_id"], "sha256": r["sha256"], "group_id": r["group_id"], "class_index": r["class_index"], "origin": r.get("origin"), "source_id": r.get("source_id"), "upstream_teacher_exposure_possible": r.get("origin") == "upstream_old_replay"} for r in val])
    dump(args.output / "baseline-predictions.json", baseline_predictions)
    summary = []
    for variant in args.variants:
        random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed); torch.backends.cudnn.benchmark = False
        variant_dir = args.output / variant
        variant_dir.mkdir()
        if variant.startswith("yolo"):
            model = mu.extend_classifier(torch, mu.load_baseline(torch, ultralytics, args.model, classes), classes)
            initialization_sha = mu.BASELINE_SHA256
            learning_rate = 1e-4
        else:
            size = variant.split("_")[0]
            name, initialization_sha = STUDENT_WEIGHTS[size]
            weight_path = args.student_models / f"mobilenetv3_{size}.safetensors"
            if mu.sha256(weight_path) != initialization_sha:
                raise ValueError(f"Unexpected {size} initialization bytes")
            model = timm.create_model(name, pretrained=False)
            model.load_state_dict(load_file(str(weight_path)), strict=True)
            model.reset_classifier(len(classes))
            learning_rate = 3e-4
        model.to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
        scaler = torch.amp.GradScaler("cuda")
        loader = torch.utils.data.DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                    num_workers=args.workers, pin_memory=True, generator=torch.Generator().manual_seed(args.seed))
        best, history = -1.0, []
        started = time.monotonic()
        for epoch in range(1, args.epochs + 1):
            warmup = epoch == 1
            select_training_parameters(model, variant, warmup)
            # eval keeps pretrained BatchNorm statistics frozen during head warmup.
            model.eval() if warmup else model.train()
            seen, loss_sum = 0, 0.0
            epoch_started = time.monotonic()
            for batch, (images, labels) in enumerate(loader):
                images, labels = images.to(device, non_blocking=True), labels.to(device, non_blocking=True)
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    output = logits(model, images, variant)
                    loss = torch.nn.functional.cross_entropy(output, labels)
                    if variant.endswith("_kd"):
                        with torch.no_grad():
                            target = mu.logits_from_output(teacher(images))
                        loss = loss + 0.5 * distillation_loss(torch, output.float(), target.float(), labels)
                scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update()
                seen += len(labels); loss_sum += loss.item() * len(labels)
                if batch % 100 == 0:
                    print(json.dumps({"variant": variant, "epoch": epoch, "batch": batch, "loss": loss_sum / seen}), flush=True)
            result, predictions = evaluate(model, variant)
            record = {"epoch": epoch, "train_loss": loss_sum / seen,
                      "seconds": time.monotonic() - epoch_started,
                      **{key: result[key] for key in ("accuracy", "macro_f1_supported", "old_class_macro_f1_supported", "city_macro_f1_supported")}}
            history.append(record)
            dump(variant_dir / "history.json", history)
            if result["macro_f1_supported"] > best:
                best = result["macro_f1_supported"]
                dump(variant_dir / "best-validation.json", result)
                dump(variant_dir / "best-predictions.json", predictions)
                dump(variant_dir / "best-epoch.json", record)
                torch.save({"state_dict": model.state_dict(), "classes": classes, "variant": variant,
                            "epoch": epoch, "initialization_sha256": initialization_sha,
                            "manifest_sha256": manifest_sha}, variant_dir / "best.pt")
            print(json.dumps({"variant": variant, **record}), flush=True)
        summary.append({"variant": variant, "best_validation_macro_f1": best,
                        "seconds": time.monotonic() - started,
                        "parameters": sum(p.numel() for p in model.parameters()),
                        "initialization_sha256": initialization_sha,
                        "checkpoint_sha256": mu.sha256(variant_dir / "best.pt"),
                        "learning_rate": learning_rate})
        dump(args.output / "summary.json", summary)
        del model, optimizer, scaler
        torch.cuda.empty_cache()
    dump(args.output / "complete.json", {"completed_at": datetime.now(timezone.utc).isoformat(), "variants": args.variants, "test_pixels_opened": False})


if __name__ == "__main__":
    main()

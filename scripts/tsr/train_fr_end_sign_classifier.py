#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#   "torch==2.6.0", "torchvision==0.21.0", "ultralytics==8.4.56",
#   "numpy==2.2.6", "pillow==11.1.0", "huggingface-hub==1.10.2",
# ]
# ///
"""Fine-tune the pinned FR crop classifier without replacing its 256-class head.

This is an evaluation experiment, not a detector or a mobile model release.
Input is an ImageFolder dataset made by prepare_fr_end_sign_training.py; target
oversampling happens only in that preparation step. Full-image RGB resize is
deliberate: the stock classification trainer's random crops, erasing and flips
can remove or reverse the end-sign stripe. No source images are uploaded here.

Run with ``uv run scripts/tsr/train_fr_end_sign_classifier.py --help``.
Optional Hub persistence requires an already-created private model repository.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import time
from typing import Any


SOURCE_MODEL_SHA256 = "5e70142feffd01ac15ce4f1fc2c3ce929a6dadb7c71ccf06ea20059ca5757641"
SOURCE_REVISION = "7f2bdd58f20b3dfc7161c5aea7c672ce02749c8f"
TARGET_CLASSES = ("B31", "B33-30", "B33-50", "B33-70", "B33-90")
CLASS_COUNT = 256
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
HUB_FILES = [
    "*-metrics.json", "training-summary.json", "configuration.json",
    "dataset-summary.json", "metrics.jsonl", "weights/best.pt", "weights/last.pt",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_model_names(names: dict | list) -> list[str]:
    if isinstance(names, dict):
        normalized = {int(index): str(name) for index, name in names.items()}
        if sorted(normalized) != list(range(len(normalized))):
            raise ValueError("Model class indices must be consecutive from zero")
        return [normalized[index] for index in range(len(normalized))]
    return [str(name) for name in names]


def validate_vocabulary(model_names: list[str], train_names: list[str], val_names: list[str],
                        declared_names: list[str], expected_count: int = CLASS_COUNT) -> None:
    if len(model_names) != expected_count or len(set(model_names)) != expected_count:
        raise ValueError(f"Expected the original {expected_count}-class head")
    if not set(TARGET_CLASSES).issubset(model_names):
        raise ValueError("Original B31/B33 model classes are missing")
    for label, names in (("train", train_names), ("val", val_names), ("manifest", declared_names)):
        if names != model_names:
            raise ValueError(f"{label} class order differs from the pretrained classifier; refusing head reset/remap")


def split_inventory(directory: Path) -> tuple[list[str], dict[str, int]]:
    names = sorted(path.name for path in directory.iterdir() if path.is_dir())
    counts = {name: sum(1 for path in (directory / name).rglob("*")
                        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS) for name in names}
    return names, counts


class ClassificationMetrics:
    """Full-vocabulary counts with exact-class and end-family summaries."""

    def __init__(self, names: list[str]):
        self.names = names
        self.matrix = [[0] * len(names) for _ in names]
        self.confident = [[0] * len(names) for _ in names]
        self.top5_correct = 0

    def add(self, truth: list[int], predictions: list[int], confidence: list[float],
            top5: list[list[int]]) -> None:
        if len({len(truth), len(predictions), len(confidence), len(top5)}) != 1:
            raise ValueError("Incomplete prediction batch")
        for actual, predicted, score, five in zip(truth, predictions, confidence, top5):
            if not 0 <= actual < len(self.names) or not 0 <= predicted < len(self.names):
                raise ValueError("Class index outside the retained vocabulary")
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("Invalid model score")
            self.matrix[actual][predicted] += 1
            self.confident[actual][predicted] += int(score >= 0.70)
            self.top5_correct += int(actual in five)

    def result(self) -> dict[str, Any]:
        support = [sum(row) for row in self.matrix]
        predicted = [sum(row[index] for row in self.matrix) for index in range(len(self.names))]
        confident_predicted = [sum(row[index] for row in self.confident) for index in range(len(self.names))]
        classes = {}
        for index, name in enumerate(self.names):
            correct = self.matrix[index][index]
            classes[name] = {
                "support": support[index], "predicted": predicted[index], "correct": correct,
                "precision": correct / predicted[index] if predicted[index] else None,
                "recall": correct / support[index] if support[index] else None,
                "f1": 2 * correct / (support[index] + predicted[index]) if support[index] + predicted[index] else None,
                "confident_predicted": confident_predicted[index],
                "precision_at_0_70": self.confident[index][index] / confident_predicted[index]
                if confident_predicted[index] else None,
                "recall_at_0_70": self.confident[index][index] / support[index] if support[index] else None,
                "confusions": {self.names[other]: count for other, count in enumerate(self.matrix[index])
                               if other != index and count},
            }
        total = sum(support)
        target_ids = [index for index, name in enumerate(self.names) if name in TARGET_CLASSES]
        target_support = sum(support[index] for index in target_ids)
        target_predictions = sum(predicted[index] for index in target_ids)
        exact_target_correct = sum(self.matrix[index][index] for index in target_ids)
        family_correct = sum(self.matrix[actual][pred] for actual in target_ids for pred in target_ids)
        target_f1 = [classes[self.names[index]]["f1"] or 0.0 for index in target_ids if support[index]]
        return {
            "sample_count": total, "top1_accuracy": sum(self.matrix[i][i] for i in range(len(self.names))) / total if total else None,
            "top5_accuracy": self.top5_correct / total if total else None,
            "target": {
                "classes": list(TARGET_CLASSES), "support": target_support,
                "predicted": target_predictions, "exact_class_correct": exact_target_correct,
                "macro_f1": sum(target_f1) / len(target_f1) if target_f1 else None,
                "exact_class_recall": exact_target_correct / target_support if target_support else None,
                "family_precision": family_correct / target_predictions if target_predictions else None,
                "family_recall": family_correct / target_support if target_support else None,
            },
            "per_class": classes,
            "limitation": "Crop development split; not independent route, detector recall, or mobile acceptance evidence.",
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="0", help="CUDA index, cuda:N, mps, or cpu")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--lr", type=float, default=0.0001)
    parser.add_argument("--train-scope", choices=["full", "frozen-bn", "linear"], default="full")
    parser.add_argument("--augment", action="store_true", help="Train-only blur, downsampling and brightness; no flips/crops")
    parser.add_argument("--max-hours", type=float, default=3.25)
    parser.add_argument("--hub-model-id", help="Persist checkpoints and metrics in an existing private model repo")
    args = parser.parse_args(argv)
    if min(args.epochs, args.batch, args.imgsz) <= 0 or args.workers < 0:
        parser.error("epochs, batch and imgsz must be positive; workers cannot be negative")
    if not math.isfinite(args.lr) or args.lr <= 0 or not math.isfinite(args.max_hours) or args.max_hours <= 0:
        parser.error("lr and max-hours must be positive and finite")
    if args.imgsz != 224:
        parser.error("The pinned mobile classifier preprocessing requires imgsz=224")
    return args


def seed_worker(worker_id: int) -> None:
    import numpy as np
    import torch
    worker_seed = torch.initial_seed() % (2**32)
    random.seed(worker_seed)
    np.random.seed(worker_seed)


class DrivingDegradation:
    """Seeded train-only image degradation; keeps the complete sign and stripe."""

    def __call__(self, image):
        from PIL import Image, ImageEnhance, ImageFilter
        if random.random() < 0.35:
            side = random.choice([32, 48, 64, 96])
            image = image.resize((side, side), Image.Resampling.BILINEAR)
        if random.random() < 0.25:
            image = image.filter(ImageFilter.GaussianBlur(random.uniform(0.2, 1.0)))
        if random.random() < 0.35:
            image = ImageEnhance.Brightness(image).enhance(random.uniform(0.65, 1.25))
        return image


def configure_training_scope(model, scope):
    for parameter in model.parameters():
        parameter.requires_grad_(scope != "linear")
    if scope == "linear":
        for parameter in model.model[-1].linear.parameters():
            parameter.requires_grad_(True)


def set_training_mode(model, scope):
    import torch
    if scope == "linear":
        model.eval()  # Keep backbone running statistics and dropout fixed too.
        model.model[-1].linear.train()
    else:
        model.train()
        if scope == "frozen-bn":
            for module in model.modules():
                if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
                    module.eval()


def train(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "configuration.json").exists():
        raise ValueError("Output already contains a run; use a new directory to preserve evidence")
    data = args.data.resolve()
    model_path = args.model.resolve()
    if sha256_file(model_path) != SOURCE_MODEL_SHA256:
        raise ValueError("Source model SHA-256 differs from the pinned original Panoramax FR classifier")
    dataset_summary = json.loads((data / "dataset-summary.json").read_text())
    train_names, train_counts = split_inventory(data / "train")
    val_names, val_counts = split_inventory(data / "val")
    if any(not train_counts.get(name) for name in train_names):
        raise ValueError("Every retained class must have a training example")
    if any(not val_counts.get(name) for name in TARGET_CLASSES):
        raise ValueError("B31 and every B33 variant need development validation examples")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import numpy as np
    import torch
    from torchvision import datasets, transforms
    import ultralytics
    from ultralytics import YOLO

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.backends.cudnn.benchmark = False
    device = torch.device(f"cuda:{args.device}" if args.device.isdigit() else args.device)
    original = YOLO(str(model_path), task="classify")
    names = ordered_model_names(original.names)
    validate_vocabulary(names, train_names, val_names, dataset_summary.get("class_names", []))
    model = original.model.float().to(device)
    head = model.model[-1]
    if not hasattr(head, "linear") or head.linear.out_features != CLASS_COUNT:
        raise ValueError("Unexpected classifier head; no replacement or shape adaptation is allowed")
    head.export = False
    configure_training_scope(model, args.train_scope)
    preprocessing = transforms.Compose([
        transforms.Resize((args.imgsz, args.imgsz), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.ToTensor(),
    ])
    train_transform = transforms.Compose([DrivingDegradation(), preprocessing]) if args.augment else preprocessing
    train_data = datasets.ImageFolder(str(data / "train"), transform=train_transform)
    val_data = datasets.ImageFolder(str(data / "val"), transform=preprocessing, allow_empty=True)
    validate_vocabulary(names, train_data.classes, val_data.classes, dataset_summary["class_names"])
    generator = torch.Generator().manual_seed(args.seed)
    common = dict(batch_size=args.batch, num_workers=args.workers, pin_memory=device.type == "cuda",
                  worker_init_fn=seed_worker, persistent_workers=args.workers > 0)
    train_loader = torch.utils.data.DataLoader(train_data, shuffle=True, generator=generator, **common)
    val_loader = torch.utils.data.DataLoader(val_data, shuffle=False, **common)
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    config.update({
        "status": "evaluation_only", "source_repository": "Panoramax/classify_fr_road_signs",
        "source_revision": SOURCE_REVISION, "source_model_sha256": SOURCE_MODEL_SHA256,
        "class_names": names, "train_counts": train_counts, "val_counts": val_counts,
        "head_preserved": True, "preprocessing": "RGB full image bilinear stretch to 224x224, float32 /255",
        "augmentation": "Train-only downsample/blur/brightness" if args.augment else "None",
        "optimizer": "AdamW", "weight_decay": 0.0001, "scheduler": "cosine to 0.1*initial_lr",
        "software": {"torch": torch.__version__, "ultralytics": ultralytics.__version__},
        "started_at": utc_now(), "dataset_summary_sha256": sha256_file(data / "dataset-summary.json"),
    })
    write_json(output / "configuration.json", config)
    write_json(output / "dataset-summary.json", dataset_summary)
    summary = {"status": "baseline_running", "evaluation_only": True, "output": str(output),
               "started_at": config["started_at"], "epochs_completed": 0, "source_model_sha256": SOURCE_MODEL_SHA256}
    write_json(output / "training-summary.json", summary)
    hub_api = None
    if args.hub_model_id:
        from huggingface_hub import HfApi
        if not os.environ.get("HF_TOKEN"):
            raise ValueError("Private checkpoint persistence requires HF_TOKEN")
        hub_api = HfApi(token=os.environ["HF_TOKEN"])
        if not hub_api.repo_info(args.hub_model_id, repo_type="model").private:
            raise ValueError("Training output repository must already exist and be private")

    def persist(phase: str) -> None:
        if hub_api:
            hub_api.upload_folder(repo_id=args.hub_model_id, repo_type="model", folder_path=str(output),
                                  allow_patterns=HUB_FILES, commit_message=f"FR end-sign experiment: {phase}")

    def emit(event: str, **details: Any) -> None:
        record = {"timestamp": utc_now(), "event": event, **details}
        print(json.dumps(record, allow_nan=False), flush=True)
        with (output / "metrics.jsonl").open("a") as handle:
            handle.write(json.dumps(record, allow_nan=False) + "\n")

    def logits_from(raw: Any) -> Any:
        # YOLOv8 Classify returns logits in train mode and (softmax, logits) in eval mode.
        logits = raw[1] if isinstance(raw, tuple) else raw
        if not isinstance(logits, torch.Tensor) or logits.ndim != 2 or logits.shape[1] != CLASS_COUNT:
            raise ValueError("Classifier returned an incompatible output tensor")
        return logits

    def evaluate(phase: str) -> dict[str, Any]:
        model.eval()
        counts = ClassificationMetrics(names)
        loss_sum = 0.0
        last_log = time.monotonic()
        with torch.inference_mode():
            for batch_index, (images, labels) in enumerate(val_loader):
                images, labels = images.to(device), labels.to(device)
                logits = logits_from(model(images))
                if not torch.isfinite(logits).all():
                    raise ValueError("Non-finite classifier output during evaluation")
                loss_sum += float(torch.nn.functional.cross_entropy(logits, labels, reduction="sum"))
                scores, predicted = logits.softmax(1).max(1)
                counts.add(labels.tolist(), predicted.tolist(), scores.tolist(), logits.topk(5, dim=1).indices.tolist())
                if batch_index == 0 or time.monotonic() - last_log >= 30:
                    emit("validation_progress", phase=phase, batch=batch_index + 1, batches=len(val_loader))
                    last_log = time.monotonic()
        metrics = counts.result()
        metrics["cross_entropy"] = loss_sum / len(val_data)
        metrics["phase"] = phase
        write_json(output / f"{phase}-metrics.json", metrics)
        emit("validation_complete", phase=phase, top1_accuracy=metrics["top1_accuracy"], target=metrics["target"])
        return metrics

    weights = output / "weights"
    weights.mkdir(exist_ok=True)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.lr, weight_decay=0.0001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.lr * 0.1)

    def checkpoint(epoch: int, best: bool = False, partial: bool = False) -> None:
        checkpoint_model = deepcopy(model).cpu().float()
        checkpoint_model.eval()
        checkpoint_model.transforms = preprocessing
        payload = {
            "model": checkpoint_model, "ema": None, "optimizer": None, "epoch": epoch,
            "date": utc_now(), "version": ultralytics.__version__,
            "license": "AGPL-3.0 License (https://ultralytics.com/license)",
            "train_args": {"task": "classify", "imgsz": args.imgsz, "data": str(data)},
            "experiment": {"evaluation_only": True, "source_sha256": SOURCE_MODEL_SHA256,
                           "partial_epoch": partial, "head_preserved": True},
        }
        targets = [weights / "last.pt", weights / f"epoch-{epoch:03d}{'-partial' if partial else ''}.pt"]
        if best:
            targets.append(weights / "best.pt")
        for path in targets:
            temporary = path.with_suffix(".tmp")
            torch.save(payload, temporary)
            temporary.replace(path)
        # Optimizer/RNG state is local only; Hub checkpoint files are model-only.
        resume = {"epoch": epoch, "partial_epoch": partial, "optimizer": optimizer.state_dict(),
                  "scheduler": scheduler.state_dict(), "torch_rng": torch.get_rng_state(),
                  "shuffle_rng": generator.get_state(), "python_rng": random.getstate(),
                  "numpy_rng": np.random.get_state()}
        if torch.cuda.is_available():
            resume["cuda_rng"] = torch.cuda.get_rng_state_all()
        temporary = weights / "training-state.tmp"
        torch.save(resume, temporary)
        temporary.replace(weights / "training-state.pt")

    stop = {"requested": False}
    old_handlers = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        old_handlers[sig] = signal.signal(sig, lambda *_: stop.update(requested=True))
    try:
        baseline = evaluate("baseline")
        summary.update(status="training", baseline=baseline["target"], baseline_top1=baseline["top1_accuracy"])
        write_json(output / "training-summary.json", summary)
        # Upload permission/connectivity failure must happen before the first optimizer update.
        persist("baseline")
        best_score = (-1.0, -1.0)
        last_metrics = baseline
        for epoch in range(1, args.epochs + 1):
            set_training_mode(model, args.train_scope)
            train_loss = 0.0
            samples = 0
            last_log = time.monotonic()
            interrupted = False
            for batch_index, (images, labels) in enumerate(train_loader):
                if stop["requested"] or time.monotonic() - started >= args.max_hours * 3600:
                    interrupted = True
                    break
                images, labels = images.to(device), labels.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = logits_from(model(images))
                loss = torch.nn.functional.cross_entropy(logits, labels)
                if not torch.isfinite(loss):
                    raise ValueError("Non-finite training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0, error_if_nonfinite=True)
                optimizer.step()
                samples += len(labels)
                train_loss += float(loss.detach()) * len(labels)
                if batch_index == 0 or time.monotonic() - last_log >= 30:
                    emit("training_progress", epoch=epoch, batch=batch_index + 1, batches=len(train_loader),
                         samples=samples, loss=train_loss / samples, learning_rate=optimizer.param_groups[0]["lr"])
                    last_log = time.monotonic()
            if interrupted:
                checkpoint(epoch, partial=True)
                summary.update(status="stopped" if stop["requested"] else "time_limit", partial_epoch=epoch)
                break
            scheduler.step()
            last_metrics = evaluate(f"epoch-{epoch:03d}")
            score = (last_metrics["target"]["macro_f1"], last_metrics["top1_accuracy"])
            is_best = score > best_score
            checkpoint(epoch, best=is_best)
            if is_best:
                best_score = score
                summary.update(best_epoch=epoch, best_target_macro_f1=score[0], best_top1=score[1])
                write_json(output / "best-metrics.json", last_metrics)
            summary.update(epochs_completed=epoch, latest_top1=last_metrics["top1_accuracy"],
                           latest_target=last_metrics["target"], elapsed_seconds=time.monotonic() - started)
            write_json(output / "training-summary.json", summary)
            emit("epoch_complete", epoch=epoch, train_loss=train_loss / samples, best=is_best,
                 top1_delta=last_metrics["top1_accuracy"] - baseline["top1_accuracy"])
            persist(f"epoch {epoch}")
        else:
            summary["status"] = "completed"
        summary.update(finished_at=utc_now(), elapsed_seconds=time.monotonic() - started,
                       checkpoint_selection="Maximum target macro F1, global top1 as tie-break; evaluation only",
                       mobile_release_approved=False,
                       scope="French crop classifier only; proposal detector unchanged")
        if summary.get("best_top1") is not None:
            summary["best_global_top1_delta"] = summary["best_top1"] - baseline["top1_accuracy"]
            summary["global_regression_gt_one_percentage_point"] = summary["best_global_top1_delta"] < -0.01
        write_json(output / "training-summary.json", summary)
        persist(summary["status"])
        emit("run_finished", **summary)
        return summary
    except BaseException as error:
        summary.update(status="failed", error_type=type(error).__name__, finished_at=utc_now(),
                       elapsed_seconds=time.monotonic() - started)
        write_json(output / "training-summary.json", summary)
        try:
            persist("failed")
        except Exception:
            pass  # Preserve the original failure and local evidence when persistence itself failed.
        raise
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main() -> int:
    result = train(parse_args())
    # A declared budget ending is an intentional, checkpointed terminal state.
    return 0 if result["status"] in {"completed", "time_limit"} else 130


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Den deutschen 134-Klassen-Checkpoint um zwei Ortstafelklassen erweitern."""
import argparse
import csv
from pathlib import Path
import random
import sys

from model_utils import (BASELINE_SHA256, CHECKPOINT_FORMAT, PREPROCESSING, dataset,
                         dependencies, device_for, extend_classifier, load_baseline,
                         load_classes, load_manifest, logits_from_output,
                         metrics_from_predictions, predict, samples_for_split,
                         sha256, write_json)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data", type=Path, default=Path("data/dataset"), help="Vorbereiteter Datensatz (Standard: data/dataset)")
    result.add_argument("--model", type=Path, default=Path("models/baseline.pt"), help="Gepinnte Original-Baseline")
    result.add_argument("--output", type=Path, default=Path("runs/versuch-01"), help="Neuer, noch nicht existierender Versuchsordner")
    result.add_argument("--epochs", type=int, default=20, help="Vollständige Trainingsdurchläufe (Standard: 20)")
    result.add_argument("--batch-size", type=int, default=16)
    result.add_argument("--learning-rate", type=float, default=0.0001)
    result.add_argument("--device", default="cuda:0", help="Zugewiesene GPU im Container; cpu für einen kleinen Probelauf")
    result.add_argument("--seed", type=int, default=20261026)
    return result


def run(args):
    if args.epochs < 1 or args.batch_size < 1 or args.learning_rate <= 0:
        raise ValueError("epochs, batch-size und learning-rate müssen positiv sein.")
    if args.output.exists():
        raise ValueError("Versuchsordner existiert bereits. --output runs/versuch-02 wählen; frühere Ergebnisse erhalten.")
    classes = load_classes()
    manifest, manifest_sha = load_manifest(args.data, classes)
    # Absichtlich nur train und val lesen: test wird weder optimiert noch zur Auswahl genutzt.
    train_rows = samples_for_split(args.data, manifest, "train", classes, require_all=True)
    val_rows = samples_for_split(args.data, manifest, "val", classes)
    missing_city = [label for label in classes[-2:] if not any(row["label"] == label for row in val_rows)]
    if missing_city:
        raise ValueError("Unabhängige Validierungsbilder fehlen für: " + ", ".join(missing_city)
                         + ". Weitere geprüfte Gruppen vor dem Experiment bereitstellen.")
    torch, ultralytics, np, Image, ImageOps = dependencies()
    device = device_for(torch, args.device)
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = False
    model = extend_classifier(torch, load_baseline(torch, ultralytics, args.model, classes), classes)
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    model.to(device)
    train_loader = torch.utils.data.DataLoader(dataset(torch, np, Image, ImageOps, train_rows),
                                               batch_size=args.batch_size, shuffle=True, num_workers=0,
                                               generator=torch.Generator().manual_seed(args.seed))
    val_loader = torch.utils.data.DataLoader(dataset(torch, np, Image, ImageOps, val_rows),
                                             batch_size=args.batch_size, shuffle=False, num_workers=0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.0001)
    criterion = torch.nn.CrossEntropyLoss()
    weights = args.output / "weights"; weights.mkdir(parents=True)
    config = {"epochs": args.epochs, "batch_size": args.batch_size, "learning_rate": args.learning_rate,
              "seed": args.seed, "device": str(device), "optimizer": "AdamW", "weight_decay": 0.0001,
              "torch": str(torch.__version__), "ultralytics": ultralytics.__version__,
              "preprocessing": PREPROCESSING, "train_samples": len(train_rows), "val_samples": len(val_rows),
              "dataset_manifest_sha256": manifest_sha, "baseline_sha256": BASELINE_SHA256,
              "selection": "highest validation macro-F1 among classes with support; test never read",
              "parameter_elements": sum(p.numel() for p in model.parameters()),
              "determinism_note": "Seed fixed; CUDA operations may still differ across hardware/runtime versions."}
    write_json(args.output / "config.json", config)
    write_json(args.output / "class-index.json", {"classes": classes})
    best_f1 = -1.0
    print(f"Training: {len(train_rows)} Bilder · Validierung: {len(val_rows)} · {len(classes)} Klassen · {device}", flush=True)
    print("Testdaten bleiben geschlossen. Auswahl nach Validierungs-Macro-F1.", flush=True)
    with (args.output / "progress.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["epoch", "train_loss", "val_accuracy", "val_macro_f1", "city_f1", "old_f1"])
        writer.writeheader()
        for epoch in range(1, args.epochs + 1):
            model.train(); total_loss = 0.0; samples_seen = 0
            for batch_index, (images, labels) in enumerate(train_loader, 1):
                images, labels = images.to(device), labels.to(device)
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(logits_from_output(model(images)), labels)
                loss.backward(); optimizer.step()
                total_loss += loss.item() * len(labels); samples_seen += len(labels)
                if batch_index == 1 or batch_index == len(train_loader) or batch_index % max(1, len(train_loader) // 10) == 0:
                    print(f"Epoche {epoch}/{args.epochs} · Batch {batch_index}/{len(train_loader)} · Loss {total_loss / samples_seen:.4f}", flush=True)
            truth, predicted = predict(torch, model, val_loader, device, f"Validierung Epoche {epoch}")
            result = metrics_from_predictions(truth, predicted, classes)
            f1 = result["macro_f1_supported"]
            writer.writerow({"epoch": epoch, "train_loss": total_loss / samples_seen,
                             "val_accuracy": result["accuracy"], "val_macro_f1": f1,
                             "city_f1": result["city_macro_f1_supported"], "old_f1": result["old_class_macro_f1_supported"]})
            stream.flush()
            record = {"format": CHECKPOINT_FORMAT, "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
                      "classes": classes, "epoch": epoch, "baseline_sha256": BASELINE_SHA256,
                      "dataset_manifest_sha256": manifest_sha, "preprocessing": PREPROCESSING,
                      "validation_macro_f1": f1, "config": config}
            torch.save(record, weights / "last.pt")
            if f1 > best_f1:
                best_f1 = f1; torch.save(record, weights / "best.pt")
            print(f"Epoche {epoch}: val-Accuracy {result['accuracy']:.3f} · val-Macro-F1 {f1:.3f} · bisher bestes F1 {best_f1:.3f}", flush=True)
    write_json(args.output / "checkpoint-hashes.json", {name: sha256(weights / name) for name in ["best.pt", "last.pt"]})
    print(f"Fertig. Bester Kandidat: {weights / 'best.pt'}\nNächster Schritt: python evaluate.py --candidate {weights / 'best.pt'}", flush=True)


def main():
    args = parser().parse_args()
    try:
        run(args)
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

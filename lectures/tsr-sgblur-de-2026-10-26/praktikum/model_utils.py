"""Gemeinsame, prüfbare Regeln. --help benötigt weder Torch noch eine GPU."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

BASELINE_SHA256 = "f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7"
ULTRALYTICS_VERSION = "8.4.56"
IMAGE_SIZE = 224
PREPROCESSING = "RGB-Pillow-bilinear-resize-224x224-float32-div255-v1"
CHECKPOINT_FORMAT = "youspeed-city-classifier-state-v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_classes(path=None):
    path = Path(path or Path(__file__).with_name("class-index.json"))
    value = json.loads(path.read_text())
    classes = value["classes"]
    if (len(classes) != 136 or len(set(classes)) != 136
            or value["baseline_class_count"] != 134
            or classes[-2:] != ["city:start", "city:end"]):
        raise ValueError("class-index.json muss 134 alte Klassen und city:start/city:end enthalten.")
    return classes


def load_manifest(data, classes):
    data = Path(data).resolve()
    path = data / "manifest.json"
    if not path.is_file():
        raise ValueError("Datensatz fehlt. Zuerst python prepare_dataset.py ausführen.")
    manifest = json.loads(path.read_text())
    unlocked = {key: value for key, value in manifest.items() if key != "lock_sha256"}
    lock = hashlib.sha256(json.dumps(unlocked, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if manifest.get("lock_sha256") != lock:
        raise ValueError("manifest.json wurde nach der Vorbereitung verändert (Lock stimmt nicht).")
    if manifest.get("classes") != classes:
        raise ValueError("Klassenreihenfolge im Datensatz stimmt nicht mit class-index.json überein.")
    if sha256(data / "class-index.json") != manifest.get("class_index_sha256"):
        raise ValueError("class-index.json im Datensatz wurde verändert. Datensatz neu vorbereiten.")
    if not isinstance(manifest.get("samples"), list):
        raise ValueError("manifest.json enthält keine Sample-Liste.")
    groups = {}
    hashes = {}
    for sample in manifest["samples"]:
        split = sample["split"]
        if split not in {"train", "val", "test"}:
            raise ValueError("Unbekannter Split im Manifest.")
        for mapping, key, label in [(groups, sample["group_id"], "Gruppe"),
                                    (hashes, sample["sha256"], "Bildhash")]:
            if key in mapping and mapping[key] != split:
                raise ValueError(f"{label} kommt in mehreren Splits vor: Datenleck.")
            mapping[key] = split
    return manifest, sha256(path)


def samples_for_split(data, manifest, split, classes, require_all=False):
    if split not in {"train", "val", "test"}:
        raise ValueError("Split muss train, val oder test sein.")
    data = Path(data).resolve()
    rows = []
    for row in manifest["samples"]:
        if row["split"] != split:
            continue
        index = row["class_index"]
        if not isinstance(index, int) or not 0 <= index < len(classes) or classes[index] != row["label"]:
            raise ValueError("Label und Klassenindex stimmen nicht überein.")
        path = (data / row["dataset_path"]).resolve()
        if not path.is_relative_to(data / split):
            raise ValueError("Bildpfad verlässt den erwarteten Split-Ordner.")
        if not path.is_file() or sha256(path) != row["sha256"]:
            raise ValueError(f"Bild fehlt oder wurde verändert: {row['dataset_path']}")
        rows.append(dict(row, resolved_path=str(path)))
    if not rows:
        raise ValueError(f"Split {split} ist leer. Weitere unabhängige Gruppen vorbereiten.")
    if require_all:
        counts = Counter(row["label"] for row in rows)
        missing = [label for label in classes if not counts[label]]
        if missing:
            raise ValueError("Trainingsbilder fehlen für Klassen: " + ", ".join(missing))
    return rows


def metrics_from_predictions(truth, predictions, classes):
    """One-vs-rest P/R/F1 + echte Klasse (Zeile) gegen Vorhersage (Spalte)."""
    if len(truth) != len(predictions) or not truth:
        raise ValueError("Vorhersagen und Zielklassen müssen gleich lang und nicht leer sein.")
    count = len(classes)
    confusion = [[0] * count for _ in classes]
    for target, predicted in zip(truth, predictions):
        if not (0 <= target < count and 0 <= predicted < count):
            raise ValueError("Vorhersage oder Ziel liegt außerhalb des Klasseninventars.")
        confusion[target][predicted] += 1
    per_class = []
    for index, label in enumerate(classes):
        tp = confusion[index][index]
        support = sum(confusion[index])
        predicted_count = sum(row[index] for row in confusion)
        fp, fn = predicted_count - tp, support - tp
        per_class.append({"index": index, "label": label, "support": support,
                          "predicted_count": predicted_count, "tp": tp, "fp": fp, "fn": fn,
                          "precision": tp / predicted_count if predicted_count else None,
                          "recall": tp / support if support else None,
                          "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None})
    supported = [row for row in per_class if row["support"]]
    def macro(rows):
        return sum((row["f1"] or 0) for row in rows) / len(rows) if rows else None
    old = [row for row in supported if row["index"] < 134]
    city = [row for row in supported if row["index"] >= 134]
    return {"samples": len(truth), "accuracy": sum(confusion[i][i] for i in range(count)) / len(truth),
            "macro_f1_supported": macro(supported), "old_class_macro_f1_supported": macro(old),
            "city_macro_f1_supported": macro(city), "supported_classes": len(supported),
            "per_class": per_class, "confusion": confusion}


def old_class_regression(truth, baseline_predictions, candidate_predictions, classes):
    """Verbindliche Null-Verschlechterung auf identischen ALTEN Zielbildern."""
    if not (len(truth) == len(baseline_predictions) == len(candidate_predictions)):
        raise ValueError("Für die Regressionsprüfung müssen beide Vorhersagelisten zum selben Bildsatz gehören.")
    selected = [(target, old, new) for target, old, new in zip(truth, baseline_predictions, candidate_predictions) if target < 134]
    if not selected:
        return {"status": "UNVOLLSTAENDIG", "passed": False, "tolerance": 0.0,
                "reasons": ["Keine unabhängigen Bilder alter Klassen vorhanden."],
                "missing_old_classes": classes[:134], "baseline": None, "candidate": None, "per_class": []}
    targets, old_predictions, new_predictions = map(list, zip(*selected))
    old = metrics_from_predictions(targets, old_predictions, classes)
    new = metrics_from_predictions(targets, new_predictions, classes)
    missing = [row["label"] for row in old["per_class"][:134] if row["support"] == 0]
    reasons, changes = [], []
    for old_row, new_row in zip(old["per_class"][:134], new["per_class"][:134]):
        change = {"label": old_row["label"], "support": old_row["support"],
                  "baseline_precision": old_row["precision"], "candidate_precision": new_row["precision"],
                  "baseline_recall": old_row["recall"], "candidate_recall": new_row["recall"],
                  "baseline_f1": old_row["f1"], "candidate_f1": new_row["f1"],
                  "delta_recall": None if not old_row["support"] else new_row["recall"] - old_row["recall"],
                  "delta_f1": None if not old_row["support"] else (new_row["f1"] or 0) - (old_row["f1"] or 0)}
        changes.append(change)
        if old_row["support"]:
            for metric in ["recall", "f1"]:
                if change[f"delta_{metric}"] < 0:
                    reasons.append(f"{old_row['label']}: {metric} auf alten Zielbildern gesunken ({change[f'delta_{metric}']:+.6f}).")
    for metric in ["accuracy", "old_class_macro_f1_supported"]:
        if new[metric] < old[metric]:
            reasons.append(f"{metric} auf alten Zielbildern gesunken ({new[metric] - old[metric]:+.6f}).")
    regression = bool(reasons)
    if missing:
        reasons.append(f"Für {len(missing)} alte Klassen fehlen unabhängige Beispiele: " + ", ".join(missing))
    status = "REGRESSION" if regression else "UNVOLLSTAENDIG" if missing else "BESTANDEN"
    return {"status": status, "passed": status == "BESTANDEN", "tolerance": 0.0,
            "scope": "Nur Bilder mit wahrer Klasse unter Index 134; beide Modelle auf identischen Bildern. Neue Ortstafel-Zielbilder ausgeschlossen.",
            "reasons": reasons, "missing_old_classes": missing, "baseline": old,
            "candidate": new, "per_class": changes}


def dependencies():
    try:
        import torch
        import ultralytics
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as error:
        raise ValueError("ML-Pakete fehlen. Die Lehrumgebung/requirements.txt installieren; Details im README.md.") from error
    if ultralytics.__version__ != ULTRALYTICS_VERSION:
        raise ValueError(f"Dieses Praktikum erwartet ultralytics=={ULTRALYTICS_VERSION}; gefunden: {ultralytics.__version__}.")
    return torch, ultralytics, np, Image, ImageOps


def device_for(torch, requested):
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise ValueError("Keine CUDA-GPU sichtbar. Zugewiesene Lehr-GPU prüfen; für einen kleinen Probelauf --device cpu verwenden.")
    return torch.device(requested)


def dataset(torch, np, Image, ImageOps, rows):
    class CropDataset(torch.utils.data.Dataset):
        def __len__(self):
            return len(rows)

        def __getitem__(self, index):
            row = rows[index]
            with Image.open(row["resolved_path"]) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image = image.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
                pixels = np.asarray(image, dtype=np.float32).copy() / 255.0
            return torch.from_numpy(pixels).permute(2, 0, 1), row["class_index"]
    return CropDataset()


def load_baseline(torch, ultralytics, path, classes):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Baseline fehlt: {path}. Der Dozent stellt models/baseline.pt bereit.")
    if sha256(path) != BASELINE_SHA256:
        raise ValueError("Baseline-SHA256 stimmt nicht mit dem gepinnten Panoramax-Checkpoint überein.")
    model = ultralytics.YOLO(str(path), task="classify").model.float()
    names = model.names
    names = [names[i] for i in range(len(names))] if isinstance(names, dict) else list(names)
    if names != classes[:134]:
        raise ValueError("Baseline hat nicht die erwarteten 134 Klassen in der Originalreihenfolge.")
    return model


def extend_classifier(torch, model, classes):
    head = model.model[-1]
    old = head.linear
    if old.out_features != 134:
        raise ValueError("Baseline-Klassifikationskopf hat nicht 134 Ausgänge.")
    new = torch.nn.Linear(old.in_features, len(classes), bias=old.bias is not None)
    with torch.no_grad():
        new.weight[:134].copy_(old.weight)
        if old.bias is not None:
            new.bias[:134].copy_(old.bias)
    head.linear = new
    model.names = dict(enumerate(classes))
    return model


def logits_from_output(output):
    # Ultralytics Classify: train -> logits; eval -> (softmax, logits).
    return output[1] if isinstance(output, tuple) else output


def predict(torch, model, loader, device, title):
    model.eval()
    truth, predicted = [], []
    with torch.inference_mode():
        for batch_index, (images, labels) in enumerate(loader, 1):
            logits = logits_from_output(model(images.to(device)))
            truth.extend(labels.tolist())
            predicted.extend(logits.argmax(1).cpu().tolist())
            if batch_index == 1 or batch_index == len(loader) or batch_index % max(1, len(loader) // 10) == 0:
                print(f"{title}: Batch {batch_index}/{len(loader)} · {len(truth)} Bilder", flush=True)
    return truth, predicted


def load_candidate(torch, baseline, path, classes, manifest_sha256):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Kandidat fehlt: {path}. Zuerst train.py ausführen.")
    record = torch.load(str(path), map_location="cpu", weights_only=True)
    if record.get("format") != CHECKPOINT_FORMAT or record.get("classes") != classes:
        raise ValueError("Kandidat hat nicht das erwartete Praktikumsformat mit 136 Klassen.")
    if record.get("baseline_sha256") != BASELINE_SHA256 or record.get("preprocessing") != PREPROCESSING:
        raise ValueError("Baseline oder Vorverarbeitung des Kandidaten weicht ab.")
    if record.get("dataset_manifest_sha256") != manifest_sha256:
        raise ValueError("Kandidat und Datensatzmanifest gehören nicht zum selben eingefrorenen Experiment.")
    model = extend_classifier(torch, baseline, classes)
    model.load_state_dict(record["state_dict"], strict=True)
    return model, record

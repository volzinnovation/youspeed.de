#!/usr/bin/env python3
"""Append DE classes without moving existing indices or consuming fresh holdouts.

Preparation retains the repaired historical development/report split and manual
source augmentation. New silver labels and official artwork are training inputs,
never certified human reference labels. The historical report is diagnostic.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

INITIAL_MODEL_SHA = "2918071223bc115ae1341cd2ce363dad04b3ba3d377112e79340ed1a12964005"
HELPER_SHA = "50e2c478161e13c8b1b67c0dcd8cfbbc7db9d1ce90398c9c5f9f915280b787f7"
LABEL_ORIGINS = {"human_reviewed", "manual_annotation", "source_annotation",
                 "assistant_visual_silver", "official_pictogram"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_classes(base, expanded):
    if len(base) != 136 or base[-2:] != ["city:start", "city:end"]:
        raise ValueError("The frozen 136-class prefix is required")
    if len(expanded) <= len(base) or expanded[:len(base)] != base or len(set(expanded)) != len(expanded):
        raise ValueError("Expanded classes must be unique and strictly append-only")
    if any(not isinstance(x, str) or not x for x in expanded):
        raise ValueError("Nonempty class identifiers are required")


def identity_values(row):
    values = set()
    for key in ("sample_id", "source_id", "group_id", "picture_id", "crop_id", "sighting_id", "route_component"):
        if row.get(key):
            values.add(str(row[key]))
    for key in ("group_identities", "route_tokens", "route_component_members", "collection_ids", "sequence_ids"):
        for value in row.get(key, []):
            values.add(str(value)); values.add(str(value).split(":", 1)[-1])
    return values


def pixel_values(row):
    return {row[key] for key in ("sha256", "digest", "rgb_sha256", "native_rgb_sha256",
                                 "sign_rgb_sha256", "canonicalSha256", "canonical_sha256") if row.get(key)}


def distance_m(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [*a, *b])
    x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(x)))


def exclude_groups(rows, protected, radius_m=250):
    """Any identity/pixel/geographic overlap excludes the whole new route group."""
    protected_ids = set().union(*(identity_values(r) for r in protected)) if protected else set()
    protected_pixels = set().union(*(pixel_values(r) for r in protected)) if protected else set()
    positions = [r["coordinates"] for r in protected if r.get("coordinates")]
    blocked, audit = set(), []
    for row in rows:
        reasons = []
        if identity_values(row) & protected_ids: reasons.append("protected_identity")
        if pixel_values(row) & protected_pixels: reasons.append("protected_pixels")
        if row.get("coordinates") and any(distance_m(row["coordinates"], p) <= radius_m for p in positions):
            reasons.append("protected_geography")
        if reasons: blocked.add(row["group_id"])
        audit.append({"sample_id": row["sample_id"], "group_id": row["group_id"], "direct_reasons": reasons})
    accepted = []
    for row, record in zip(rows, audit):
        record["excluded"] = row["group_id"] in blocked
        if record["excluded"] and not record["direct_reasons"]:
            record["direct_reasons"] = ["connected_route_overlap"]
        if not record["excluded"]: accepted.append(row)
    return accepted, audit


def split_new_rows(rows, classes):
    """Hold out real groups only with >=3 groups/class and retain training support.

    The labels remain silver where originally silver. Artwork never enters dev.
    Sorting a fixed hash makes selection reproducible without inspecting scores.
    """
    groups = {}
    for row in rows: groups.setdefault(row["group_id"], []).append(row)
    def can_hold_out(row):
        return row["label_origin"] != "official_pictogram" and not row.get("training_only") and row.get("evaluation_eligible") is not False
    eligible = {label for label in classes if len({r["group_id"] for r in rows
                if r["label"] == label and can_hold_out(r)}) >= 3}
    selected = set()
    for label in sorted(eligible):
        candidates = sorted({r["group_id"] for r in rows if r["label"] == label and can_hold_out(r)},
                            key=lambda x: hashlib.sha256(("expanded-dev-20261109:" + x).encode()).hexdigest())
        if any(r["label"] == label for g in selected for r in groups[g]): continue
        for group in candidates:
            candidate = selected | {group}
            kept_labels = {r["label"] for g, values in groups.items() if g not in candidate for r in values}
            if any(not can_hold_out(r) for r in groups[group]): continue
            if set(classes) <= kept_labels:
                selected = candidate
                break
    return ([r for r in rows if r["group_id"] not in selected],
            [r for r in rows if r["group_id"] in selected], sorted(selected))


def training_image_rgb(image, official_artwork=False):
    """Composite both indexed and RGBA artwork transparency consistently."""
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(image)
    if official_artwork and ("A" in image.getbands() or "transparency" in image.info):
        background = Image.new("RGBA", image.size, (238, 238, 238, 255))
        background.alpha_composite(image.convert("RGBA"))
        image = background
    return image.convert("RGB")


def verify_new_rows(intake, classes):
    from PIL import Image, ImageOps
    doc = read(intake)
    result, seen_ids, seen_pixels = [], set(), {}
    for item in doc["samples"]:
        row = dict(item)
        required = ("sample_id", "group_id", "label", "label_origin", "path", "sha256")
        if any(not row.get(k) for k in required): raise ValueError("New sample lacks provenance/identity")
        if row["sample_id"] in seen_ids: raise ValueError("Duplicate new sample ID")
        seen_ids.add(row["sample_id"])
        if row["label"] not in classes or row["label_origin"] not in LABEL_ORIGINS:
            raise ValueError("Unrecognized class or label provenance")
        if row.get("human_reviewed") and row["label_origin"] not in {"human_reviewed", "manual_annotation"}:
            raise ValueError("Silver/artwork/source assertions cannot become human reference labels")
        path = (intake.parent / row["path"]).resolve()
        if sha(path) != row["sha256"]: raise ValueError("New image encoded hash mismatch")
        with Image.open(path) as image:
            image = training_image_rgb(image, row["label_origin"] == "official_pictogram")
            box = row.get("training_crop_box", row.get("sign_box"))
            if box:
                if len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                    raise ValueError("Invalid new sample sign box")
                image = image.crop(box)
            pixel = hashlib.sha256(str(image.size).encode() + b"\0" + image.tobytes()).hexdigest()
        if pixel in seen_pixels:
            if seen_pixels[pixel] != row["label"]: raise ValueError("Identical new pixels have conflicting labels")
            continue
        seen_pixels[pixel] = row["label"]
        row.update(resolved_path=str(path), sign_rgb_sha256=pixel,
                   training_crop_box=box, class_index=classes.index(row["label"]),
                   is_new_intake=True, human_reviewed=bool(row.get("human_reviewed", False)))
        result.append(row)
    return result


def deduplicate_existing(rows, train):
    def training_pixels(row):
        # A derived supplementary subregion may share its encoded parent image
        # with a retained multi-sign assembly; only the cropped pixels coincide.
        return {row["sign_rgb_sha256"]} if row.get("training_crop_box") and row.get("sign_rgb_sha256") else pixel_values(row)
    existing = {}
    for row in train:
        for value in training_pixels(row): existing.setdefault(value, set()).add(row["label"])
    accepted, duplicates = [], []
    for row in rows:
        matching = set().union(*(existing.get(value, set()) for value in training_pixels(row)))
        if matching and matching != {row["label"]}:
            raise ValueError("New class conflicts with identical historical training pixels: " + row["sample_id"])
        if matching:
            duplicates.append(row["sample_id"])
        else:
            accepted.append(row)
            for value in training_pixels(row): existing.setdefault(value, set()).add(row["label"])
    return accepted, duplicates


def apply_training_relabels(train, evaluation, review, classes):
    by_id = {r["sample_id"]: r for r in train}
    evaluation_by_id = {r["sample_id"]: r for r in evaluation}
    changed, conflicts = {}, []
    for proposed in review.get("training_relabels", []):
        key = proposed["sample_id"]
        if key not in by_id or key in changed: raise ValueError("Relabel must identify a unique historical TRAIN row")
        original = by_id[key]
        if original["sha256"] != proposed["sha256"] or original["label"] != proposed["old_label"]:
            raise ValueError("Relabel original identity/target mismatch")
        if proposed["old_label"] not in {"other", "other:multi", "bad"} or proposed["proposed_label"] not in classes[136:]:
            raise ValueError("Only explicit catchall-to-new-class refinement is permitted")
        if proposed.get("label_origin") != "assistant_visual_silver" or proposed.get("human_reviewed") is not False:
            raise ValueError("Relabel provenance must remain unapproved silver")
        changed[key] = {**original, "original_label": original["label"], "label": proposed["proposed_label"],
                        "class_index": classes.index(proposed["proposed_label"]), "label_origin": "assistant_visual_silver",
                        "human_reviewed": False, "training_only_ontology_relabel": True}
    for proposed in review.get("evaluation_conflicts", []):
        original = evaluation_by_id.get(proposed["sample_id"])
        if original is None: continue  # Reserved test remains outside dev/report metrics.
        if original["sha256"] != proposed["sha256"] or original["label"] != proposed["old_label"]:
            raise ValueError("Evaluation conflict identity mismatch")
        conflicts.append(proposed["sample_id"])
    return [changed.get(r["sample_id"], r) for r in train], sorted(set(conflicts))


def bind_exposure_ledger(path, manifest):
    """Acknowledge earlier taxonomy inspection without opening any image."""
    ledger = read(path)
    if ledger.get("schema") != "youspeed-taxonomy-exposure-ledger-v1":
        raise ValueError("A frozen taxonomy exposure ledger is required")
    historical = {r["sample_id"]: r for r in manifest["samples"]}
    seen = set()
    for row in ledger["records"]:
        key = row["historical_sample_id"]
        if key in seen or key not in historical:
            raise ValueError("Unknown or duplicate exposure-ledger sample")
        seen.add(key)
        original = historical[key]
        if row["sha256"] != original["sha256"] or row["historical_split"] != original["split"]:
            raise ValueError("Exposure ledger historical identity or split mismatch")
    counts = dict(Counter(r["historical_split"] for r in ledger["records"]))
    if counts != ledger["counts_by_historical_split"]:
        raise ValueError("Exposure ledger counts mismatch")
    return {"sha256": sha(path), "records": len(seen), "counts_by_historical_split": counts,
            "earlier_test_pixels_exposed": bool(counts.get("test", 0)),
            "scope": "Prior semantic taxonomy inspection, not pixels opened by this preparation command."}


def historical_selection_rows(rows, conflicts):
    return [r for r in rows if r["sample_id"] not in conflicts and r["class_index"] < 136
            and not r.get("is_new_intake") and not r.get("training_only")
            and r.get("evaluation_eligible") is not False]


def normalize_expanded_metrics(metrics):
    """Keep unmeasured classes null without changing supported-class ranking."""
    for row in metrics["per_class"]:
        if not row["support"]:
            row["recall"] = None
            row["f1"] = None
    for name, rows in (("new_class_macro_f1_supported", metrics["per_class"][136:]),
                       ("city_macro_f1_supported", metrics["per_class"][134:136])):
        supported = [r["f1"] for r in rows if r["support"]]
        metrics[name] = sum(supported) / len(supported) if supported else None
    return metrics


def real_new_class_eligibility(rows, predictions, classes):
    """Require one correctly recognized real TRAIN crop per appended class.

    This is a minimal training-fit gate, never held-out performance evidence.
    Official artwork cannot satisfy it, even when correctly classified.
    """
    if len(rows) != len(predictions):
        raise ValueError("Training sanity predictions must match every supplied row")
    per_class = []
    for index, label in enumerate(classes[136:], 136):
        real = [(r, prediction) for r, prediction in zip(rows, predictions)
                if r["class_index"] == index and r.get("label_origin") != "official_pictogram"]
        if any(r.get("split") != "train" or r["label"] != label for r, _ in real):
            raise ValueError("Real-positive eligibility may use only matching TRAIN rows")
        correct = sum(int(prediction) == index for _, prediction in real)
        per_class.append({"class_id": label, "real_training_support": len(real),
                          "correct_real_training_predictions": correct, "eligible": correct >= 1})
    return {"eligible": bool(per_class) and all(r["eligible"] for r in per_class),
            "scope": "At least one correct real training crop per new class; training sanity only, not held-out F1.",
            "per_class": per_class,
            "classes_without_real_support": [r["class_id"] for r in per_class if not r["real_training_support"]],
            "classes_without_correct_real_prediction": [r["class_id"] for r in per_class if not r["eligible"]],
            "human_field_f1": False}


def require_eligible_checkpoint(output, eligible_epochs):
    if not eligible_epochs:
        write(output / "complete.json", {"status": "failed_no_eligible_epoch",
              "reason": "No epoch correctly predicted a real training crop in every appended class.",
              "native_export_created": False, "fresh_field_f1_computed": False, "deployed": False})
        raise RuntimeError("No eligible epoch; native checkpoint export is forbidden")
    if not (output / "best.pt").is_file():
        raise RuntimeError("Eligible checkpoint selection is missing")


def prepare(args):
    if args.output.exists(): raise ValueError("Use a new preparation directory")
    if sha(args.course_code / "model_utils.py") != HELPER_SHA: raise ValueError("Pinned helper changed")
    sys.path.insert(0, str(args.course_code))
    sys.path.insert(0, str(Path(__file__).parent))
    import model_utils as mu
    from de_neural_refinement import city_dev_repair, source_annotation_augmentation, validate_partition
    from PIL import Image, ImageOps
    base = mu.load_classes(args.data / "class-index.json")
    classes = read(args.classes)["classes"]; validate_classes(base, classes)
    manifest, manifest_sha = mu.load_manifest(args.data, base)
    exposure = bind_exposure_ledger(args.exposure_ledger, manifest)
    train = mu.samples_for_split(args.data, manifest, "train", base, require_all=True)
    val = mu.samples_for_split(args.data, manifest, "val", base)
    partition = read(args.historical_partition)
    validate_partition(partition, val, manifest_sha, base)
    train, val, partition, repair = city_dev_repair(partition, train, val, base)
    dev_idx, report_idx = validate_partition(partition, val, manifest_sha, base)
    reserved = [r for r in manifest["samples"] if r["split"] == "test"]
    train, manual = source_annotation_augmentation(args.source_annotations, train, val, reserved, base, manifest_sha, Image, ImageOps)
    dev, report = [val[i] for i in dev_idx], [val[i] for i in report_idx]
    ontology = read(args.ontology_review) if args.ontology_review else {}
    if ontology and ontology["historical_manifest_sha256"] != manifest_sha:
        raise ValueError("Ontology review belongs to another historical corpus")
    train, ontology_conflicts = apply_training_relabels(train, dev + report, ontology, classes)
    protected = val + reserved
    fresh = []
    for path in args.holdout_manifests:
        doc = read(path); fresh.extend(doc["samples"])
    # Verify retained historical/manual training remains outside the later frozen field intake.
    retained, base_exclusions = exclude_groups(train, fresh)
    if len(retained) != len(train):
        raise ValueError("Historical/manual training overlaps fresh holdout; resolve before training")
    new = verify_new_rows(args.new_intake, classes)
    new, exclusions = exclude_groups(new, protected + fresh)
    unique, duplicate_audit = deduplicate_existing(new, train)
    new_train, new_dev, selected_groups = split_new_rows(unique, classes[136:])
    train += new_train; dev += new_dev
    missing = set(classes) - {r["label"] for r in train}
    if missing: raise ValueError("No training support for appended classes: " + ", ".join(sorted(missing)))
    all_rows = []
    for split, values in (("train", train), ("dev", dev), ("report", report)):
        for row in values: all_rows.append({**row, "split": split})
    for key in ("sample_id", "group_id", "sha256", "sign_rgb_sha256", "rgb_sha256"):
        occupied = {}
        for row in all_rows:
            if not row.get(key): continue
            if row[key] in occupied and occupied[row[key]] != row["split"]: raise ValueError("Cross-split " + key)
            occupied[row[key]] = row["split"]
    if sha(args.exposure_ledger) != exposure["sha256"]:
        raise ValueError("Taxonomy exposure ledger changed during preparation")
    args.output.mkdir(parents=True)
    result = {"schema": "youspeed-expanded-training-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "classes": classes, "base_classes": base, "samples": all_rows,
              "provenance": {"base_manifest_sha256": manifest_sha, "classes_sha256": sha(args.classes),
                             "new_intake_sha256": sha(args.new_intake), "source_annotations_sha256": sha(args.source_annotations),
                             "exposure_ledger_sha256": exposure["sha256"],
                             "holdout_manifest_sha256": [sha(p) for p in args.holdout_manifests]},
              "split_counts": {split: dict(Counter(r["label"] for r in all_rows if r["split"] == split)) for split in ("train", "dev", "report")},
              "new_dev_groups": selected_groups, "new_source_label_quality": dict(Counter(r["label_origin"] for r in unique)),
              "ontology_review_sha256": sha(args.ontology_review) if args.ontology_review else None,
              "ontology_conflict_ids": ontology_conflicts,
              "training_only_ontology_relabel_count": sum(bool(r.get("training_only_ontology_relabel")) for r in train),
              "selection_policy": "Require one correct real non-artwork TRAIN crop per appended class, then maximize ontology-compatible historical development macro-F1. Exclude frozen conflicting IDs and all new-intake dev. The training-fit eligibility gate and silver metrics are diagnostic, not held-out evidence.",
              "new_classes_without_real_dev": [c for c in classes[136:] if not any(r["label"] == c for r in new_dev)],
              "limitations": ["Historical development/report are previously inspected diagnostic sets, not fresh final F1.",
                              "New silver development labels remain unapproved visual proposals, not certified human truth.",
                              "Artwork-only or singleton new classes have no independently supported real-world F1.",
                              "Source geographies unknown for some historical HF images; complete geographic independence cannot be certified."],
              "taxonomy_exposure": exposure,
              "test_pixels_opened_by_preparation": False, "fresh_field_training_samples": 0}
    write(args.output / "manifest.json", result)
    write(args.output / "class-index.json", {"classes": classes})
    (args.output / "exposure-ledger.json").write_bytes(args.exposure_ledger.read_bytes())
    if sha(args.output / "exposure-ledger.json") != exposure["sha256"]:
        raise ValueError("Copied taxonomy exposure ledger changed")
    write(args.output / "preparation-audit.json", {"manual_source_augmentation": manual, "city_dev_repair": repair,
          "new_holdout_exclusions": exclusions, "duplicate_existing_training": duplicate_audit,
          "historical_fresh_holdout_check": base_exclusions})
    (args.output / "executed-prepare.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"classes": len(classes), "counts": dict(Counter(r["split"] for r in all_rows)), "manifest_sha256": sha(args.output / "manifest.json")}))


def extend_head(torch, model, classes):
    old_names = [model.names[i] for i in range(len(model.names))] if isinstance(model.names, dict) else list(model.names)
    validate_classes(old_names, classes)
    old = model.model[-1].linear
    if old.out_features != len(old_names): raise ValueError("Old classifier head/name mismatch")
    new = torch.nn.Linear(old.in_features, len(classes), bias=old.bias is not None)
    with torch.no_grad():
        new.weight[:len(old_names)].copy_(old.weight)
        if old.bias is not None:
            new.bias[:len(old_names)].copy_(old.bias)
            new.bias[len(old_names):].fill_(-4)
    model.model[-1].linear = new
    model.names = dict(enumerate(classes)); model.yaml = {**model.yaml, "nc": len(classes)}
    if hasattr(model, "nc"): model.nc = len(classes)
    return model


def train(args):
    if args.output.exists() or args.epochs < 2: raise ValueError("New output directory and at least2epochs required")
    if sha(args.initial_model) != INITIAL_MODEL_SHA: raise ValueError("Frozen primary136 checkpoint differs")
    if sha(args.course_code / "model_utils.py") != HELPER_SHA: raise ValueError("Pinned helper changed")
    sys.path.insert(0, str(args.course_code)); import model_utils as mu
    torch, ultralytics, np, Image, ImageOps = mu.dependencies()
    from PIL import ImageEnhance, ImageFilter
    if not args.device.startswith("cuda") or not torch.cuda.is_available(): raise ValueError("Assigned CUDA GPU required")
    doc = read(args.manifest); classes = doc["classes"]; validate_classes(doc["base_classes"], classes)
    if sha(args.manifest.parent / "exposure-ledger.json") != doc["provenance"]["exposure_ledger_sha256"]:
        raise ValueError("Prepared taxonomy exposure ledger changed")
    rows = doc["samples"]
    for row in rows:
        if sha(row["resolved_path"]) != row["sha256"]: raise ValueError("Prepared image changed")
    train_rows = [r for r in rows if r["split"] == "train"]
    dev_rows = [r for r in rows if r["split"] == "dev"]
    report_rows = [r for r in rows if r["split"] == "report"]
    conflicts = set(doc.get("ontology_conflict_ids", []))
    selection_dev = historical_selection_rows(dev_rows, conflicts)
    silver_dev = [r for r in dev_rows if r["class_index"] >= 136]
    real_new_training = [r for r in train_rows if r["class_index"] >= 136
                         and r.get("label_origin") != "official_pictogram"]
    if not selection_dev: raise ValueError("No compatible historical development support")
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed); torch.cuda.manual_seed_all(args.seed)
    torch.set_num_threads(4); torch.set_num_interop_threads(1)
    torch.backends.cudnn.benchmark = False; torch.backends.cuda.matmul.allow_tf32 = False; torch.backends.cudnn.allow_tf32 = False
    device = torch.device(args.device)
    model = ultralytics.YOLO(str(args.initial_model), task="classify").model.float()
    model = extend_head(torch, model, classes).to(device)
    args.output.mkdir(parents=True)
    # Fixed repetition improves sparse new-class exposure without duplicating held-out groups.
    schedule = []
    new_counts = Counter(r["label"] for r in train_rows if r["class_index"] >=136)
    for i, row in enumerate(train_rows):
        repeats = min(64, max(1, math.ceil(128/new_counts[row["label"]]))) if row["class_index"] >=136 else 1
        schedule.extend([i] * repeats)
    class Crops(torch.utils.data.Dataset):
        def __init__(self, values, augment=False): self.values, self.augment = values, augment
        def __len__(self): return len(self.values)
        def __getitem__(self, index):
            row = self.values[index]
            with Image.open(row["resolved_path"]) as raw:
                im = training_image_rgb(raw, row.get("label_origin") == "official_pictogram")
                if row.get("training_crop_box"): im = im.crop(row["training_crop_box"])
                if self.augment and row.get("label_origin") == "official_pictogram":
                    # Artwork remains a synthetic training source, never held-out evidence.
                    size = random.randint(160,220); im.thumbnail((size,size))
                    canvas = Image.new("RGB", (224,224), tuple(random.randint(70,210) for _ in range(3)))
                    canvas.paste(im, ((224-im.width)//2,(224-im.height)//2)); im=canvas
                im = im.resize((224,224), Image.Resampling.BILINEAR)
                if self.augment:
                    im=ImageEnhance.Brightness(im).enhance(random.uniform(.9,1.1)); im=ImageEnhance.Contrast(im).enhance(random.uniform(.9,1.1))
                    if random.random()<.1: im=im.filter(ImageFilter.GaussianBlur(random.uniform(.2,.6)))
                value=np.asarray(im,dtype=np.float32).copy()/255
            return torch.from_numpy(value).permute(2,0,1),row["class_index"]
    def loader(values, augment=False):
        return torch.utils.data.DataLoader(Crops(values,augment),batch_size=args.batch_size,shuffle=augment,num_workers=args.workers,
            generator=torch.Generator().manual_seed(args.seed),pin_memory=True)
    train_loader=loader([train_rows[i] for i in schedule],True); dev_loader=loader(selection_dev); report_loader=loader(report_rows)
    real_new_loader = loader(real_new_training)
    def predict(target, batches):
        target.eval(); truth=[]; predictions=[]
        with torch.inference_mode():
            for images, labels in batches:
                with torch.autocast("cuda",dtype=torch.float16): scores=mu.logits_from_output(target(images.to(device)))
                truth.extend(labels.tolist()); predictions.extend(scores.argmax(1).cpu().tolist())
        return truth, predictions
    def evaluate(target, batches):
        truth, predictions = predict(target, batches)
        metrics=normalize_expanded_metrics(mu.metrics_from_predictions(truth,predictions,classes))
        return metrics, predictions
    config={"classes":classes,"epochs":args.epochs,"seed":args.seed,"initialization_sha256":INITIAL_MODEL_SHA,"manifest_sha256":sha(args.manifest),"script_sha256":sha(__file__),
        "selection":"Require at least one correct real non-artwork TRAIN crop per appended class, then highest ontology-compatible historical development supported-class macro-F1; earliest eligible epoch wins ties. New-intake dev and ontology-conflict IDs are excluded from selection. Full legacy dev/report evaluated only after selection.",
        "training_sanity_gate_is_not_heldout_evidence":True,"taxonomy_exposure":doc["taxonomy_exposure"],
        "selection_dev_count":len(selection_dev),"legacy_dev_count":len(dev_rows),"silver_dev_count":len(silver_dev),"ontology_conflict_ids":sorted(conflicts),
        "new_dev_label_status":"Preserved intake provenance; silver development is diagnostic, not human field F1.","new_classes_without_real_dev":doc["new_classes_without_real_dev"],
        "schedule":"Epoch1 head only, then low-rate whole-network AdamW cosine; raw logits, no observation priors.","samples_per_epoch":len(schedule),"unique_training_samples":len(train_rows),
        "new_class_repetition":"ceil(128 / class support), bounded1..64, fixed each epoch; old samples single pass","train_exposure_counts":dict(Counter(train_rows[i]["label"] for i in schedule)),
        "normalization":"RGB/255","gpu":torch.cuda.get_device_name(device),"torch":str(torch.__version__),"ultralytics":ultralytics.__version__,"deployed":False}
    write(args.output/"configuration.json",config); (args.output/"executed-train.py").write_bytes(Path(__file__).read_bytes())
    optimizer=torch.optim.AdamW(model.parameters(),lr=3e-5,weight_decay=1e-4);scaler=torch.amp.GradScaler("cuda")
    history=[];best=-1;eligible_epochs=[]
    for epoch in range(1,args.epochs+1):
        started=time.monotonic();head_only=epoch==1
        for name,param in model.named_parameters(): param.requires_grad_(not head_only or ".linear." in name)
        model.eval() if head_only else model.train()
        lr=3e-4 if head_only else 1e-5*(.1+.9*.5*(1+math.cos(math.pi*(epoch-2)/max(1,args.epochs-2))))
        for group in optimizer.param_groups: group["lr"]=lr
        total=0.; seen=0
        for images, labels in train_loader:
            images=images.to(device);labels=labels.to(device);optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda",dtype=torch.float16): loss=torch.nn.functional.cross_entropy(mu.logits_from_output(model(images)).float(),labels)
            scaler.scale(loss).backward();scaler.step(optimizer);scaler.update(); total+=float(loss)*len(labels);seen+=len(labels)
        metrics,predictions=evaluate(model,dev_loader)
        _, real_predictions = predict(model, real_new_loader)
        eligibility = real_new_class_eligibility(real_new_training, real_predictions, classes)
        if eligibility["eligible"]: eligible_epochs.append(epoch)
        record={"epoch":epoch,"train_loss":total/seen,"samples_seen":seen,"learning_rate":lr,"seconds":time.monotonic()-started,
                "dev_macro_f1_supported":metrics["macro_f1_supported"],"dev_new_class_macro_f1_supported":metrics["new_class_macro_f1_supported"],
                "real_training_eligibility":eligibility}
        history.append(record);write(args.output/"history.json",history)
        if eligibility["eligible"] and metrics["macro_f1_supported"]>best:
            best=metrics["macro_f1_supported"];write(args.output/"selected-epoch.json",record);write(args.output/"dev-metrics.json",metrics)
            torch.save({"state_dict":{k:v.detach().cpu() for k,v in model.state_dict().items()},"classes":classes,"family":"yolo","variant":"expanded_ce_cosine","epoch":epoch,
                        "initialization_sha256":INITIAL_MODEL_SHA,"manifest_sha256":sha(args.manifest),"normalization":"RGB/255",
                        "real_training_eligibility":eligibility},args.output/"best.pt")
        print(json.dumps(record),flush=True)
    require_eligible_checkpoint(args.output, eligible_epochs)
    checkpoint=torch.load(args.output/"best.pt",map_location=device,weights_only=True);model.load_state_dict(checkpoint["state_dict"],strict=True);model.eval()
    write(args.output/"selection-frozen.json",{"checkpoint_sha256":sha(args.output/"best.pt"),"epoch":checkpoint["epoch"],"report_scored_yet":False,
          "eligible_epochs":eligible_epochs,"real_training_eligibility":checkpoint["real_training_eligibility"]})
    metrics,predictions=evaluate(model,report_loader);write(args.output/"report-metrics.json",metrics)
    write(args.output/"report-predictions.json",predictions)
    legacy_dev_metrics,_=evaluate(model,loader([r for r in dev_rows if r["class_index"]<136]));write(args.output/"legacy-dev-metrics.json",legacy_dev_metrics)
    compatible_report=[r for r in report_rows if r["sample_id"] not in conflicts]
    if compatible_report:
        compatible_metrics,_=evaluate(model,loader(compatible_report));write(args.output/"ontology-compatible-report-metrics.json",compatible_metrics)
    if silver_dev:
        silver_metrics,_=evaluate(model,loader(silver_dev));write(args.output/"silver-new-class-dev-diagnostic.json",{"scope":"Unapproved silver labels; not human field F1 and not used for selection.","metrics":silver_metrics})
    new_training=[r for r in train_rows if r["class_index"]>=136]
    fit_metrics,fit_predictions=evaluate(model,loader(new_training))
    write(args.output/"new-class-training-fit-sanity.json",{
        "scope":"Selected checkpoint on its own unique new-class training samples; sanity only, not held-out accuracy or final F1.",
        "counts_by_provenance":dict(Counter(r["label_origin"] for r in new_training)),
        "new_classes_without_any_correct_training_prediction":[r["label"] for r in fit_metrics["per_class"][136:] if r["tp"]==0],
        "per_class":fit_metrics["per_class"][136:],"predictions":fit_predictions,"human_field_f1":False})
    model=model.float().cpu().eval()
    torch.save({"model":deepcopy(model),"ema":None,"optimizer":None,"updates":0,"epoch":checkpoint["epoch"],"version":ultralytics.__version__,"train_args":{"task":"classify","imgsz":224},"youspeed_provenance":config},args.output/"expanded-native.pt")
    restored=ultralytics.YOLO(str(args.output/"expanded-native.pt"),task="classify").model.float().eval()
    assert [restored.names[i] for i in range(len(classes))]==classes
    with torch.inference_mode():
        for probe in [torch.zeros(1,3,224,224),torch.ones(1,3,224,224),torch.rand(1,3,224,224)]:
            assert torch.equal(mu.logits_from_output(model(probe)),mu.logits_from_output(restored(probe)))
    write(args.output/"class-index.json",{"classes":classes})
    write(args.output/"complete.json",{"status":"complete","classes":len(classes),"selected_epoch":checkpoint["epoch"],"checkpoint_sha256":sha(args.output/"best.pt"),"native_checkpoint_sha256":sha(args.output/"expanded-native.pt"),"packaging_probes_exact":True,"real_training_eligibility":checkpoint["real_training_eligibility"],"fresh_field_f1_computed":False,"deployed":False})


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("prepare")
    for name in ("data","course-code","historical-partition","source-annotations","classes","new-intake","exposure-ledger","output"): p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--holdout-manifests",type=Path,nargs="+",required=True)
    p.add_argument("--ontology-review",type=Path)
    t=sub.add_parser("train")
    for name in ("manifest","course-code","initial-model","output"): t.add_argument("--"+name,type=Path,required=True)
    t.add_argument("--epochs",type=int,default=10);t.add_argument("--seed",type=int,default=20261109);t.add_argument("--batch-size",type=int,default=64);t.add_argument("--workers",type=int,default=4);t.add_argument("--device",default="cuda:0")
    args=parser.parse_args();prepare(args) if args.command=="prepare" else train(args)


if __name__=="__main__":main()

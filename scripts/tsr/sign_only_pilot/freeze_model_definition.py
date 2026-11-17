#!/usr/bin/env python3
"""Freeze a new d5 experiment definition after verified dataset publication.

This program never trains, evaluates, publishes, changes a prior build, or copies
scene-image bytes. Run only against the final assembled dataset and its verified
immutable publication receipt. The output directory must not already exist.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re

REPO = "loffenauer/streetshots"
SOURCE_REVISION = "d2c5cc44716166e2604655d7fd8cad93a8dd9468"
PARENT_REVISION = "32f7b519e91df05af24e3b1962aeefd864e033b7"
PARENT_DEFINITION_SHA = "ae6779c875746a8e89cf3941fe8882a56d944208f4b5b013d6dac1e67176cac9"
DATASET_PREFIX = "reviews/detector-pilot-2026-11-14/"
MODEL_PREFIX = "detector/d5/"
RECIPE_PINS = {
    "train_evaluate.py": "1924f97ed2d36afd3b281b4053dfd9e07d9e7e90dfd41ba36c6d881e2773b39e",
    "prepare_teacher.py": "f71c0c0bde76364511582e520498a8530d65f2424ba04f864470285433ba3282",
    "select_pilot.py": "51bbf0cc7a8047ac9332cae3a2898e40408582d13bced563fb455973d32e14bd",
    "assemble_reviews.py": "ef87a79d1b44152b361b0010c60fa4a665f9ed21d904b1f998ed11e88123044a",
}
CHECKPOINTS = {
    "d4": {"repository": REPO, "repo_type": "model", "revision": PARENT_REVISION,
           "path": "detector/d4/artifacts/d4.pt",
           "sha256": "f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36"},
    "coco": {"repository": "Ultralytics/YOLO26", "repo_type": "model",
             "revision": "070ac3c51435984d992ba92eb3f234daf4e4500d", "path": "yolo26n.pt",
             "sha256": "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"},
    "teacher": {"repository": "Panoramax/detect_face_plate_sign", "repo_type": "model",
                "revision": "de311725ddae469c200cce0f86126fd4c043f24b", "path": "yolo11l_panoramax.pt",
                "sha256": "a3205e4a92b3acdaa883c02e09dba439c48f6c5bc8c89aff44da7c2e79f140e7"},
    "sgblur": {"repository": "https://github.com/cquest/sgblur", "repo_type": "git",
               "revision": "169451970702aca0dde9ff3106dba0f67e0b88a8",
               "path": "models/yolo11n_panoramax.pt",
               "sha256": "698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a"},
}
TRAINING = {
    "arms": ["d4", "coco"], "epochs_per_arm": 40, "image_size": 1024, "batch_size": 4,
    "seed": 14, "optimizer": "AdamW", "learning_rate": 0.0002, "final_lr_fraction": 0.1,
    "weight_decay": 0.0005, "warmup_epochs": 2.0, "warmup_bias_lr": 0.0002,
    "warmup_momentum": 0.8, "early_stopping_patience": 0, "freeze_layers": None,
    "amp": False, "deterministic": True, "workers": 4, "device": 0, "rect": False,
    "augmentation": {"mosaic": 0.25, "close_mosaic": 5, "mixup": 0.0,
                     "fliplr": 0.0, "flipud": 0.0, "degrees": 2.0,
                     "translate": 0.05, "scale": 0.25, "hsv_h": 0.01,
                     "hsv_s": 0.3, "hsv_v": 0.3},
    "nms_iou": 0.45, "max_detections": 300,
    "trainer_pretrained_flag": False,
    "pretrained_flag_explanation": "Checkpoint transfer is applied explicitly before the trainer; false prevents automatic downloads and does not mean scratch initialization.",
    "epoch_zero_development_baseline": True,
    "logging": ["per-epoch precision", "per-epoch recall", "AP50", "AP50-95",
                "training losses", "learning rates", "epoch duration", "results CSV",
                "history JSON", "per-arm and comparative plots"],
}
SAFE_PARENT_FIELDS = {"schema_version", "task", "model_repository", "dataset_repository", "repository_type"}
DATASET_METADATA = ("manifest.json", "assembly-audit.json", "excluded-scenes.json",
                    "review-bindings.json", "review-policy.json", "selection.json")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".gif", ".tif", ".tiff"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value, "Invalid relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and "." not in path.parts,
            "Unsafe relative path")
    require(str(path) == value, "Path must use canonical POSIX spelling")
    return value


def within(root, value):
    path = (Path(root) / relative(value)).resolve()
    require(path.is_relative_to(Path(root).resolve()), "Path escapes dataset root")
    require(path.is_file(), "Missing file: " + str(path))
    return path


def hex_value(value, length, name):
    require(isinstance(value, str) and re.fullmatch("[a-f0-9]{" + str(length) + "}", value),
            name + " must be a full lowercase immutable hash")
    return value


def verify_publication(receipt, dataset_root, manifest):
    require(receipt.get("schema") == "streetshots-ki-publish-receipt-v1", "Unsupported publication receipt schema")
    require(receipt.get("repository") == REPO and receipt.get("repo_type") == "dataset", "Wrong dataset repository")
    require(receipt.get("private") is True and receipt.get("postverification") is True,
            "Dataset publication must be private and postverified")
    revision = hex_value(receipt.get("revision"), 40, "Dataset revision")
    require(revision != SOURCE_REVISION, "Reviewed overlay must have its own publication revision")
    require(receipt.get("prefix") == DATASET_PREFIX, "Unexpected dataset publication prefix")
    hex_value(receipt.get("inventory_sha256"), 64, "Inventory SHA")
    hex_value(receipt.get("publisher_sha256"), 64, "Publisher SHA")
    manifest_info = receipt.get("manifest", {})
    require(manifest_info.get("path") == DATASET_PREFIX + "manifest.json", "Wrong published manifest path")
    require(manifest_info.get("sha256") == sha(Path(dataset_root) / "manifest.json"), "Published manifest SHA mismatch")
    paths = receipt.get("paths")
    require(isinstance(paths, dict) and paths, "Verified publication file inventory required")
    required = {name: None for name in DATASET_METADATA}
    for frame in manifest["frames"]:
        for field, digest in (("image_path", "image_sha256"), ("label_path", "label_sha256")):
            name = relative(frame[field])
            require(name not in required, "Duplicate image or label filename")
            required[name] = hex_value(frame[digest], 64, digest)
    for name, expected in required.items():
        path = within(dataset_root, name)
        remote = paths.get(DATASET_PREFIX + name)
        require(isinstance(remote, dict), "Publication inventory omits " + name)
        require(type(remote.get("size")) is int and remote["size"] == path.stat().st_size,
                "Published size mismatch: " + name)
        observed = sha(path)
        require(remote.get("sha256") == observed and (expected is None or expected == observed),
                "Published SHA mismatch: " + name)
        hex_value(remote.get("git_blob_sha1"), 40, "Git blob SHA")
    return revision


def dataset_counts(manifest):
    counts = {}
    for split in ("train", "validation", "test"):
        frames = [f for f in manifest["frames"] if f["split"] == split]
        counts[split] = {"images": len(frames), "sign_boxes": sum(len(f["boxes"]) for f in frames),
                         "positive_images": sum(bool(f["boxes"]) for f in frames),
                         "negative_images": sum(not f["boxes"] for f in frames),
                         "groups": len({f["group_id"] for f in frames})}
    return counts


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata_bytes(path):
    path = Path(path)
    require(path.suffix.lower() not in IMAGE_SUFFIXES, "Scene image is forbidden in model staging")
    raw = path.read_bytes()
    raw.decode("utf8")
    return raw


def definition_from_parent(parent, replacement):
    definition = copy.deepcopy(parent)
    for key in list(definition):
        if key not in SAFE_PARENT_FIELDS:
            del definition[key]
    definition.update(replacement)
    return definition


def prepare(args):
    job = Path(args.job_root).resolve()
    data = Path(args.dataset_root).resolve()
    output = Path(args.output).resolve()
    require(not output.exists(), "Output already exists; definitions are immutable")
    require(output.is_relative_to(job) and output != job, "Output must be a new directory inside the KI job")
    require(data.is_dir(), "Dataset root does not exist")
    manifest_path = data / "manifest.json"
    manifest = read(manifest_path)
    require(manifest.get("dataset_repo") == REPO and manifest.get("dataset_revision") == SOURCE_REVISION,
            "Source dataset pin changed")
    require(manifest.get("review_provenance") == "model_assisted", "Review provenance must be explicit")
    require(manifest.get("schema") == "streetshots-sign-only-reviewed-v1", "Wrong reviewed manifest schema")
    require(all(f.get("annotation_complete") is True for f in manifest["frames"]),
            "Incomplete scene in final manifest")
    require(sha(job / "recipe/freeze_model_definition.py") == sha(Path(__file__)), "Builder path differs from staged recipe")
    for name, expected in RECIPE_PINS.items():
        require(sha(job / "recipe" / name) == expected, "Recipe changed: " + name)
    trainer = load_module(job / "recipe/train_evaluate.py", "frozen_d5_trainer")
    trainer.partition_manifest(manifest)
    assembler = load_module(job / "recipe/assemble_reviews.py", "frozen_d5_assembler")
    for frame in manifest["frames"]:
        expected = assembler.yolo_text(frame["boxes"], [frame["width"], frame["height"]]).encode()
        require(within(data, frame["label_path"]).read_bytes() == expected,
                "Manifest boxes and YOLO labels disagree: " + frame["picture_id"])
    publication_path = Path(args.dataset_publication_receipt).resolve()
    publication = read(publication_path)
    overlay_revision = verify_publication(publication, data, manifest)
    policy = read(data / "review-policy.json")
    require(policy.get("schema") == "streetshots.sign-only-pilot.review-policy.v2", "Sign scope changed")
    require(sha(data / "review-policy.json") == manifest["policy_sha256"], "Policy SHA mismatch")
    require(sha(data / "selection.json") == manifest["selection_sha256"], "Selection SHA mismatch")
    assembly = read(data / "assembly-audit.json")
    require(assembly.get("manifest_sha256") == sha(manifest_path) and not assembly.get("missing"),
            "Final assembly is incomplete or inconsistent")
    require(assembly.get("reviewed") == assembly.get("selected"), "Not every selected frame was reviewed")
    parent_path = job / "parent-definition-d4.json"
    require(sha(parent_path) == PARENT_DEFINITION_SHA, "Parent definition changed")
    parent = read(parent_path)
    require(parent.get("build") == "d4" and parent.get("checkpoint", {}).get("sha256") == CHECKPOINTS["d4"]["sha256"],
            "Wrong parent checkpoint")
    checkpoints = {"d4": job / "weights/d4.pt", "coco": job / "weights/yolo26n.pt",
                   "teacher": job / "weights/yolo11l_panoramax.pt", "sgblur": Path(args.sgblur_checkpoint)}
    for name, path in checkpoints.items():
        require(sha(path) == CHECKPOINTS[name]["sha256"], "Pretrained checkpoint changed: " + name)
    prepared = read(job / "teacher-prepared/prepared.json")
    require(prepared.get("completed") is True and prepared.get("mining_complete") is True, "Incomplete teacher mining")
    require(sha(job / "teacher-prepared/prepared.json") == manifest["prepared_sha256"], "Prepared source changed")
    limitations = read(job / "statistical-limitations.json")
    counts = dataset_counts(manifest)
    facts = limitations["test_facts"]
    require((counts["test"]["images"], counts["test"]["sign_boxes"], counts["test"]["groups"]) ==
            (facts["included_test_frames"], facts["sign_boxes"], facts["included_group_count"]),
            "Statistical limitations no longer match holdout")
    environment = read(job / "environment.json")
    require(environment.get("torch") == "2.6.0+cu126" and environment.get("ultralytics") == "8.4.56",
            "Recorded package environment differs from pinned runtime")
    require(environment.get("container_image_id") == "sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca",
            "Recorded container identity differs")
    test_receipt = read(job / "assembler-stdlib-test-receipt.json")
    require(test_receipt.get("exit_code") == 0 and test_receipt.get("assembler_sha256") == RECIPE_PINS["assemble_reviews.py"],
            "Assembler checks do not cover the frozen assembler")
    payload = {}
    def put(relative_path, raw):
        relative(relative_path)
        require(relative_path not in payload, "Duplicate staging file")
        require(Path(relative_path).suffix.lower() not in IMAGE_SUFFIXES, "Scene image forbidden")
        raw.decode("utf8")
        payload[relative_path] = raw
    def copy_file(source, destination):
        put(destination, metadata_bytes(source))
    for name in DATASET_METADATA:
        copy_file(data / name, "provenance/dataset/" + name)
    copy_file(parent_path, "provenance/parent-definition-d4.json")
    copy_file(publication_path, "provenance/dataset-publication-receipt.json")
    for name in ("environment.json", "statistical-limitations.json", "assembler-stdlib-test-receipt.json",
                 "historical-binding-validator-receipt.json", "historical-provenance-amendments.json"):
        copy_file(job / name, "provenance/" + name)
    copy_file(job / "review-extra-assets/receipt.json", "provenance/extra-review-assets-receipt.json")
    copy_file(job / "review-inputs/license-provenance.json", "licenses/license-provenance.json")
    copy_file(job / "review-inputs/sgblur-sign-surgery-smoke.json", "provenance/sgblur-sign-surgery-smoke.json")
    notices = read(job / "definition-inputs/source-receipt.json")
    for record in notices["records"]:
        source = within(job / "definition-inputs", record["name"])
        require(sha(source) == record["sha256"], "Archival notice changed")
        copy_file(source, "licenses/archival/" + record["name"])
    copy_file(job / "definition-inputs/source-receipt.json", "licenses/archival/source-receipt.json")
    recipe_names = set(RECIPE_PINS) | {p.name for p in (job / "recipe").glob("test_*.py")}
    recipe_names |= {"freeze_model_definition.py", "publish_from_ki.py", "create_training_smoke.py", "run_full_training_smoke_v3.py"}
    for name in sorted(recipe_names):
        copy_file(job / "recipe" / name, "recipe/" + name)
    put("provenance/teacher-mining.json", json_bytes({k: v for k, v in prepared.items() if k != "frames"}))
    membership = {}
    fields = ("picture_id", "image_id", "image_path", "image_sha256", "pixel_sha256",
              "label_path", "label_sha256", "source_image_sha256", "hf_path", "group_id", "sequence_ids")
    for split in ("train", "validation", "test"):
        membership[split] = [{key: f[key] for key in fields} for f in manifest["frames"] if f["split"] == split]
        put("splits/" + split + ".json", json_bytes(membership[split]))
    put("config/training.json", json_bytes(TRAINING))
    definition = definition_from_parent(parent, {
        "schema_version": 1, "build": "d5", "task": "detector", "status": "frozen_experiment_definition",
        "definition_frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model_repository": REPO, "dataset_repository": REPO, "repository_type": "model",
        "private": True,
        "parent": {"build": "d4", "repository": REPO, "revision": PARENT_REVISION,
                   "definition_path": "provenance/parent-definition-d4.json",
                   "definition_sha256": PARENT_DEFINITION_SHA},
        "data": {"source_repository": REPO, "source_revision": SOURCE_REVISION,
                 "reviewed_overlay_repository": REPO, "reviewed_overlay_revision": overlay_revision,
                 "reviewed_overlay_prefix": DATASET_PREFIX,
                 "manifest_path": DATASET_PREFIX + "manifest.json", "manifest_sha256": sha(manifest_path),
                 "policy_sha256": manifest["policy_sha256"], "selection_sha256": manifest["selection_sha256"],
                 "counts": counts, "membership_paths": {s: MODEL_PREFIX + "splits/" + s + ".json" for s in membership},
                 "review_provenance": "model_assisted",
                 "claim": "Assistant full-scene review aided by model proposals; not human-verified ground truth.",
                 "canonical_decode": "RGB stored raster, no EXIF transpose; lossless PNG, unchanged pixel coordinates.",
                 "machine_proposals_automatically_accepted": False},
        "architecture": {"family": "YOLO26n", "learned_classes": ["sign"], "class_count": 1,
                         "native_output_order": ["sign"], "end2end": False, "input_size": [1024, 1024],
                         "plate_face_outputs": "Absent from the one-class student; native mobile exports are a later separate step."},
        "initialization": {"arms": {n: CHECKPOINTS[n] for n in ("d4", "coco")},
                           "scratch_arm": False,
                           "rationale": "The reviewed corpus is small; compare task-specific d4 transfer with general COCO transfer while retaining pretrained visual features. Scratch training is outside this pilot.",
                           "parameter_transfer": "Explicit one-class model construction and checkpoint transfer in the pinned recipe."},
        "teacher": {**CHECKPOINTS["teacher"], "sign_channel": 0,
                    "role": "Full-frame and overlapping-tile proposals for review, not automatic ground truth.",
                    "mining_config": prepared["mining_config"]},
        "mapillary": {"role": "Class-blind geographic sampling and bearing/distance review cues where recorded.",
                      "not_pixel_ground_truth": True, "sign_classifications_used_as_labels": False,
                      "raw_points_in_model_repository": False},
        "training": {**TRAINING, "recipe": MODEL_PREFIX + "recipe/train_evaluate.py",
                     "recipe_sha256": RECIPE_PINS["train_evaluate.py"], "results_recorded_in_definition": False},
        "evaluation": {"checkpoint_selection": "Highest development AP50-95; earliest epoch wins ties; epoch zero eligible.",
                       "arm_selection": "Highest selected development AP50-95; exact cross-arm tie prefers d4.",
                       "threshold_selection": "Per-model development F2 (beta=2), then recall, precision, higher threshold; fixed before holdout.",
                       "holdout": "Single evaluation of the sealed winning student, current d4, and SGBlur.",
                       "baselines": {"d4": CHECKPOINTS["d4"], "sgblur": CHECKPOINTS["sgblur"]},
                       "preprocessing": "Matched single full-frame 1024-square letterbox; rect=False.",
                       "tp_fp_fn_match_iou": 0.5, "confidence_grid": {"start": 0.01, "stop": 0.99, "step": 0.01},
                       "traffic_lights": "Separate acceptable-extra counts when annotations permit; raw sign precision still counts unmatched detections.",
                       "metrics": None, "results_status": "No accuracy measurements are asserted by this frozen definition."},
        "checkpoint": {"status": "Not selected at definition freeze", "planned_path": MODEL_PREFIX + "artifacts/d5.pt"},
        "history": {"parent_build": "d4", "parent_revision": PARENT_REVISION,
                    "historical_parent_definition_preserved_unchanged": True,
                    "new_results_are_not_copied_from_parent": True},
        "recipe": {"path": MODEL_PREFIX + "recipe/train_evaluate.py",
                   "sha256": RECIPE_PINS["train_evaluate.py"], "status": "frozen_prospective_recipe",
                   "builder_sha256": sha(Path(__file__))},
        "runtime": {"container_image_id": "sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca",
                    "torch": "2.6.0+cu126", "cuda": "12.6", "ultralytics": "8.4.56",
                    "gpu": "NVIDIA RTX A5000", "network_during_training": "none",
                    "environment_path": MODEL_PREFIX + "provenance/environment.json",
                    "environment_sha256": sha(job / "environment.json")},
        "scope": policy["target_class"],
        "limitations": limitations["statistical_implications"],
        "statistical_limitations_path": MODEL_PREFIX + "provenance/statistical-limitations.json",
        "licensing": {"claim": "Mixed source provenance; no new blanket license or mobile deployment approval.",
                      "provenance_path": MODEL_PREFIX + "licenses/license-provenance.json",
                      "archival_notices": "licenses/archival/archived-third-party-notices.txt"},
        "execution_precondition": "Before training, bind the full immutable model-definition publication revision and this definition SHA in the launch receipt.",
        "deployment": {"authorized_by_this_definition": False, "native_exports": "Not produced by this builder"},
    })
    put("definition.json", json_bytes(definition))
    put("README.md", ("# d5 frozen detector experiment\n\n"
        "This private build freezes a two-arm, one-class YOLO26n experiment. "
        "At definition freeze, no newly measured accuracy or selected checkpoint existed. "
        "The frozen definition is immutable; training outcomes are in results/README.md "
        "and release.json when published.\n\n"
        "The source image snapshot and the published reviewed-label overlay are pinned separately "
        "in definition.json. Split files list exact images and labels. Labels are model-assisted "
        "assistant review, not human-verified ground truth. See the frozen scope and statistical limitations.\n\n"
        "Both initialization arms use 40 epochs, 1024-pixel full frames, batch 4, seed 14 and "
        "AdamW at 0.0002. Select the checkpoint and arm on development AP50-95, select the "
        "confidence threshold on development F2, then evaluate the winner and baselines once on holdout.\n\n"
        "Scene-image bytes remain in the separate private dataset repository. "
        "The unchanged archival notices retain historical scope and claims; current source-specific "
        "provenance is in licenses/license-provenance.json. No deployment or new blanket license is asserted.\n").encode())
    files = {MODEL_PREFIX + name: {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
             for name, raw in sorted(payload.items())}
    put("manifest.json", json_bytes({"schema": "streetshots-model-definition-manifest-v1",
        "build": "d5", "task": "detector", "status": "frozen_experiment_definition",
        "definition_sha256": files[MODEL_PREFIX + "definition.json"]["sha256"],
        "dataset_publication_receipt_sha256": sha(publication_path),
        "dataset_revision": overlay_revision, "source_dataset_revision": SOURCE_REVISION,
        "files": files, "contains_scene_images": False,
        "inventory_note": "This inventory excludes its own bytes to avoid a self-hash; publication inventory binds this manifest."}))
    return output, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--dataset-publication-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--job-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sgblur-checkpoint", type=Path,
        default=Path("/home/raphael/youspeed-training-20261020/sgblur/source/yolo11n_panoramax.pt"))
    args = parser.parse_args()
    output, payload = prepare(args)
    output.mkdir(parents=True, exist_ok=False)
    build = output / MODEL_PREFIX
    for name, raw in payload.items():
        path = build / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
    print(json.dumps({"output": str(output), "build": "d5", "files": len(payload),
                      "definition_sha256": sha(build / "definition.json"),
                      "manifest_sha256": sha(build / "manifest.json"),
                      "training_started": False, "publication_started": False}, indent=2))


if __name__ == "__main__":
    main()

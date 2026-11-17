"""Failure modes of reviewed full-scene training and frozen evaluation."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/tsr/sign_only_pilot/train_evaluate.py"
spec = importlib.util.spec_from_file_location("sign_only_train_evaluate", PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def manifest():
    return {"schema": subject.MANIFEST_SCHEMA, "dataset_revision": "a"*40,
        "review_provenance": "model_assisted", "frames": [
            {"image_id": split, "split": split, "group_id": split, "width": 100, "height": 50,
             "image_sha256": str(i)*64, "annotation_complete": True, "sequence_ids": [split]}
            for i, split in enumerate(subject.SPLITS, 1)]}


@pytest.mark.parametrize("field,value", [("group_id", "same"), ("image_sha256", "b"*64),
    ("pixel_sha256", "c"*64), ("source_image_sha256", "d"*64), ("sequence_ids", ["same"])])
def test_rejects_related_test_frame_even_with_different_filenames(field, value):
    data = manifest()
    data["frames"][0][field] = data["frames"][2][field] = value
    with pytest.raises(ValueError, match="Cross-split"):
        subject.partition_manifest(data)


def test_partial_empty_frame_cannot_become_a_background_negative():
    data = manifest()
    data["frames"][0]["annotation_complete"] = False
    with pytest.raises(ValueError, match="completeness"):
        subject.partition_manifest(data)


def test_model_assisted_review_cannot_be_relabelled_as_human_truth():
    data = manifest()
    data["review_provenance"] = "human"
    with pytest.raises(ValueError, match="model_assisted"):
        subject.partition_manifest(data)


def test_one_to_one_matching_penalizes_duplicate_detections():
    truth = [[10, 10, 20, 20]]
    proposals = [{"box": truth[0], "score": .8}, {"box": truth[0], "score": .7}]
    assert subject.frame_counts(truth, proposals, .5) == {"tp": 1, "fp": 1, "fn": 0}
    assert subject.frame_counts(truth, proposals, .75) == {"tp": 1, "fp": 0, "fn": 0}


def test_predictions_in_verified_empty_scene_are_false_positives():
    assert subject.frame_counts([], [{"box": [1, 1, 2, 2], "score": .9}], .5) == {"tp": 0, "fp": 1, "fn": 0}


def test_threshold_is_selected_from_development_counts_only():
    records = [{"image_id": "a", "group_id": "g", "truth": [[0, 0, 10, 10]],
                "predictions": [{"box": [0, 0, 10, 10], "score": .8}, {"box": [20, 20, 30, 30], "score": .5}]}]
    result = subject.threshold_sweep(records)
    assert result["threshold"] == .8  # Same F2 above .5; higher threshold breaks exact ties.
    assert max(p["f1"] for p in result["points"]) == 1


def test_f2_threshold_favors_recall_over_f1_optimum():
    truth = [[0, 0, 10, 10], [20, 0, 30, 10]]
    predictions = [{"box": truth[0], "score": .8}, {"box": truth[1], "score": .2},
        {"box": [40, 0, 50, 10], "score": .2}, {"box": [60, 0, 70, 10], "score": .2},
        {"box": [80, 0, 90, 10], "score": .2}]
    records = [{"image_id": "a", "group_id": "g", "truth": truth, "predictions": predictions}]
    sweep = subject.threshold_sweep(records)
    assert sweep["threshold"] == .2
    low, high = subject.score_frames(records, .2), subject.score_frames(records, .8)
    assert low["f1"] < high["f1"] and low["f2"] > high["f2"]
    assert low["recall"] == 1 and low["fp_per_image"] == 3


def test_traffic_light_extras_do_not_inflate_sign_precision_or_f2():
    records = [{"image_id": "a", "group_id": "g", "truth": [[0, 0, 10, 10]],
        "predictions": [{"box": [0, 0, 10, 10], "score": .8}, {"box": [20, 0, 30, 10], "score": .8}],
        "acceptable_extra_candidates": [{"kind": "traffic_light", "box_xyxy": [20, 0, 30, 10]}]}]
    result = subject.score_frames(records, .5)
    assert result["fp_on_reviewed_traffic_lights"] == 1
    assert result["fp"] == 1 and result["precision"] == .5
    assert result["f2"] == pytest.approx(5/6)


def test_yolo_label_geometry_and_class_validation(tmp_path):
    path = tmp_path/"labels.txt"
    path.write_text("0 0.5 0.5 0.2 0.4\n")
    assert subject.read_yolo_labels(path, 100, 50) == [[40., 15., 60., 35.]]
    path.write_text("1 0.5 0.5 0.2 0.4\n")
    with pytest.raises(ValueError, match="one-class"):
        subject.read_yolo_labels(path, 100, 50)
    path.write_text("0 0.05 0.5 0.2 0.4\n")
    with pytest.raises(ValueError, match="outside"):
        subject.read_yolo_labels(path, 100, 50)


def test_dataset_staging_does_not_decode_or_parse_test_inputs(tmp_path):
    from PIL import Image
    pytest.importorskip("yaml")
    source = tmp_path/"source"
    source.mkdir()
    data = manifest()
    for i, frame in enumerate(data["frames"]):
        image, label = source/f"{i}.png", source/f"{i}.txt"
        if frame["split"] == "test":
            image.write_bytes(b"held-out bytes never decoded during train preparation")
            label.write_text("held-out labels never parsed during train preparation")
        else:
            Image.new("RGB", (100, 50), (i, 0, 0)).save(image)
            label.write_text("0 0.5 0.5 0.2 0.4\n")
        frame.update(image_path=image.name, image_sha256=subject.sha(image), label_path=label.name,
                     label_sha256=subject.sha(label))
    yaml, parts = subject.stage_dataset(data, source, tmp_path/"staged")
    assert yaml.exists()
    assert len(parts["test"]) == 1
    assert len(list((tmp_path/"staged/labels/test").glob("*.txt"))) == 1


def test_geo_bootstrap_refuses_independence_claim_from_one_group():
    report = {"frames": [{"group_id": "one", "tp": 20, "fp": 0, "fn": 0}]}
    assert subject.bootstrap_groups(report)["intervals"] is None
    report["frames"].append({"group_id": "two", "tp": 10, "fp": 0, "fn": 0})
    result = subject.bootstrap_groups(report, iterations=100)
    assert result["intervals"]["f1"] == [1., 1.]


def test_input_path_cannot_escape_source_root(tmp_path):
    parent = tmp_path/"private"
    parent.write_text("value")
    root = tmp_path/"data"
    root.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        subject.checked_path(root, "../private", subject.sha(parent))


def sealed_run(root, arm, scores=(.2, .4, .3)):
    root.mkdir()
    subject.write(root/"manifest.json", manifest())
    config = {"epochs": len(scores)-1, "initialization": arm, "dataset_revision": "a"*40,
        "seed": 14, "imgsz": 1024, "batch": 4, "lr0": .0002, "script_sha256": "a"*64,
        "torch": "pinned", "ultralytics": subject.ULTRALYTICS_VERSION, "dataset_root": str(root),
        "optimizer": "AdamW", "warmup_epochs": 2., "warmup_bias_lr": .0002, "warmup_momentum": .8}
    subject.write(root/"configuration.json", config)
    history = [{"epoch": i, "ap50_95": score, "ap50": score, "precision": score,
                "recall": score, "duration_seconds": 1., "train_loss": {}}
               for i, score in enumerate(scores)]
    subject.write(root/"history.json", history)
    subject.write(root/"development-threshold-sweep.json", {"threshold": .5})
    (root/"selected.pt").write_bytes(b"synthetic checkpoint for pure verifier tests")
    chosen = max(history, key=lambda row: (row["ap50_95"], -row["epoch"]))
    seal = {"selected_epoch": chosen["epoch"], "development_ap50_95": chosen["ap50_95"], "threshold": .5}
    for filename, key in [("manifest.json", "manifest_sha256"), ("configuration.json", "configuration_sha256"),
                          ("history.json", "history_sha256"), ("selected.pt", "checkpoint_sha256"),
                          ("development-threshold-sweep.json", "threshold_sweep_sha256")]:
        seal[key] = subject.sha(root/filename)
    subject.write(root/"seal.json", seal)
    return root


def test_cross_arm_selection_ignores_test_scores_and_prefers_d4_only_on_ap_tie():
    candidates = {"d4": {"development_ap50_95": .4, "test_f1": 1.},
                  "coco": {"development_ap50_95": .5, "test_f1": 0.}}
    assert subject.choose_arm(candidates) == "coco"
    candidates["d4"]["development_ap50_95"] = .5
    assert subject.choose_arm(candidates) == "d4"
    with pytest.raises(ValueError, match="Both"):
        subject.choose_arm({"d4": candidates["d4"]})


def test_sealed_history_cannot_change_after_selection(tmp_path):
    run = sealed_run(tmp_path/"d4", "d4")
    subject.verified_run(run)
    subject.write(run/"history.json", [])
    with pytest.raises(ValueError, match="Sealed input changed"):
        subject.verified_run(run)


def test_both_arms_complete_before_real_holdout_and_loser_stays_protected(tmp_path, monkeypatch):
    d4 = sealed_run(tmp_path/"d4", "d4", (.3, .5, .4))
    coco = sealed_run(tmp_path/"coco", "coco", (.1, .4, .45))
    monkeypatch.setattr(subject, "plot_arm_comparison", lambda *args: None)
    output = tmp_path/"comparison-selection"
    subject.select(SimpleNamespace(d4_run=str(d4), coco_run=str(coco), output=str(output)))
    source = output/"arm-selection.json"
    result = subject.evaluation_inputs(SimpleNamespace(selection=str(source), run=None))
    assert result[0] == d4
    assert set(result[3]) == {"d4", "coco"}
    assert json.loads((output/"development-summary.json").read_text())["winner"] == "d4"
    (coco/"holdout-started.json").write_text("{}")
    with pytest.raises(ValueError, match="already entered"):
        subject.evaluation_inputs(SimpleNamespace(selection=str(source), run=None))


def test_single_arm_real_holdout_is_rejected(tmp_path):
    run = sealed_run(tmp_path/"d4", "d4")
    with pytest.raises(ValueError, match="both initialization arms"):
        subject.evaluation_inputs(SimpleNamespace(selection=None, run=str(run)))


def test_mismatched_recipe_cannot_win_a_comparable_two_arm_trial(tmp_path, monkeypatch):
    d4 = sealed_run(tmp_path/"d4", "d4")
    coco = sealed_run(tmp_path/"coco", "coco")
    config = json.loads((coco/"configuration.json").read_text())
    config["lr0"] = .1
    subject.write(coco/"configuration.json", config)
    seal = json.loads((coco/"seal.json").read_text())
    seal["configuration_sha256"] = subject.sha(coco/"configuration.json")
    subject.write(coco/"seal.json", seal)
    with pytest.raises(ValueError, match="share frozen data"):
        subject.select(SimpleNamespace(d4_run=str(d4), coco_run=str(coco), output=str(tmp_path/"output")))


def test_early_interrupted_arm_cannot_be_selected(tmp_path):
    run = sealed_run(tmp_path/"d4", "d4")
    config = json.loads((run/"configuration.json").read_text())
    config["epochs"] = 40
    subject.write(run/"configuration.json", config)
    seal = json.loads((run/"seal.json").read_text())
    seal["configuration_sha256"] = subject.sha(run/"configuration.json")
    subject.write(run/"seal.json", seal)
    with pytest.raises(ValueError, match="Every planned"):
        subject.verified_run(run)

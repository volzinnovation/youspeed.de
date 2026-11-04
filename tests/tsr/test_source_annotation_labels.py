from copy import deepcopy
from itertools import permutations

import pytest

from scripts.tsr.source_annotation_labels import resolve_crop_labels


CATALOGS = {
    "DE": {"city:start", "city:end", "no_stop", "give_way", "hazard:incline", "hazard:left_turn", "hazard:right_turn"},
    "FR": {"B14-30", "B21a2"},
}
MODEL_LABELS = {"DE": CATALOGS["DE"] - {"city:start", "city:end"}, "FR": CATALOGS["FR"]}


def source(class_id="city:start", *, raw="DE:310", country="DE", catalog_class=None):
    return {
        "raw_tag": raw, "parsed": {"code": raw.split(":")[-1], "raw": raw},
        "target_classifier_country": country,
        "country_resolution_state": "source_metadata",
        "semantic_mapping_status": "unique",
        "semantic_candidates": [{"label": class_id}],
        "yolo_mapping_status": "unique" if catalog_class else "catalog_mismatch",
        "selected_yolo": {"label": catalog_class, "index": 2} if catalog_class else None,
    }


def detection():
    return {
        "raw_tag": "yes", "parsed": {"code": "yes", "raw": "yes"},
        "target_classifier_country": None,
        "country_resolution_state": "country_ambiguous",
        "semantic_mapping_status": "country_ambiguous",
        "yolo_mapping_status": "country_ambiguous", "selected_yolo": None,
    }


@pytest.mark.parametrize("class_id,raw", [("city:start", "DE:310"), ("city:end", "DE:311")])
def test_manual_city_annotation_survives_absent_classifier_and_generic_detection(class_id, raw):
    labels = [source(class_id, raw=raw), detection()]
    before = deepcopy(labels)
    for order in permutations(labels):
        result = resolve_crop_labels(list(order), CATALOGS, model_labels=MODEL_LABELS)
        assert result["country"] == "DE"
        assert result["class_id"] == class_id
        assert result["status"] == "unique"
        assert result["label_origin"] == "source_annotation"
        assert result["identity_basis"] == "semantic_catalog"
        assert result["classifier_catalog_class_id"] is None
        assert result["current_model_class_id"] is None
        assert result["classifier_supported"] is False
        assert result["ignored_detection_tags"] == ["yes"]
        assert result["review_required"] is False
    assert labels == before


@pytest.mark.parametrize("country,raw,class_id,aliases", [
    ("DE", "DE:108", "hazard:incline", ["hazard:incline", "hazard:incline:up"]),
    ("DE", "DE:103-10", "hazard:left_turn", ["hazard:left_turn", "hazard:turn_left"]),
    ("DE", "DE:103-20", "hazard:right_turn", ["hazard:turn_right", "hazard:right_turn"]),
    ("FR", "FR:B21a2", "B21a2", ["arrow_left_down", "arrow_right_down"]),
])
def test_precise_catalog_identity_survives_generic_semantic_alias_ambiguity(country, raw, class_id, aliases):
    row = source(raw=raw, country=country, catalog_class=class_id)
    row["semantic_mapping_status"] = "ambiguous"
    row["semantic_candidates"] = [{"label": alias} for alias in aliases]
    result = resolve_crop_labels([row], CATALOGS, model_labels=MODEL_LABELS)
    assert result["status"] == "unique"
    assert result["class_id"] == class_id
    assert result["label_origin"] == "source_annotation"
    assert result["identity_basis"] == "classifier_catalog"
    assert result["classifier_catalog_class_id"] == class_id
    assert result["current_model_class_id"] == class_id
    assert result["classifier_supported"] is True
    assert result["review_required"] is False
    assert result["semantic_mappings"][0]["status"] == "ambiguous"
    assert result["semantic_mappings"][0]["candidate_class_ids"] == sorted(aliases)


def test_duplicate_tags_and_matching_catalog_mapping_count_as_one_exact_source_class():
    row = source("no_stop", raw="DE:283", catalog_class="no_stop")
    row["semantic_candidates"] += [{"label": "no_stop", "authority": "other-alias"}]
    result = resolve_crop_labels([row, deepcopy(row), detection(), detection()], CATALOGS)
    assert result["status"] == "unique"
    assert result["source_class_ids"] == ["no_stop"]
    assert result["model_class_ids"] == ["no_stop"]
    assert result["classifier_catalog_class_id"] == "no_stop"
    assert result["classifier_supported"] is True
    assert result["raw_tags"] == ["DE:283", "yes"]
    assert result["review_required"] is False
    assert len(result["semantic_mappings"]) == 1


def test_two_distinct_source_classes_remain_compound():
    result = resolve_crop_labels([source(), source("city:end", raw="DE:311")], CATALOGS)
    assert result["status"] == "compound"
    assert result["class_id"] is None
    assert result["source_class_ids"] == ["city:end", "city:start"]
    assert result["review_required"] is True


def test_distinct_source_labels_using_different_identity_routes_still_compete():
    rows = [source(), source("no_stop", raw="DE:283", catalog_class="no_stop")]
    result = resolve_crop_labels(rows, CATALOGS)
    assert result["status"] == "compound"
    assert result["identity_basis"] == "mixed"
    assert result["class_id"] is None
    assert result["review_required"] is True


@pytest.mark.parametrize("state", ["country_conflict", "country_ambiguous"])
def test_explicit_country_problem_cannot_be_erased_by_catalog_mapping(state):
    row = source("no_stop", raw="DE:283", catalog_class="no_stop")
    row["country_resolution_state"] = state
    result = resolve_crop_labels([row], CATALOGS)
    assert result["status"] == state
    assert result["class_id"] is None
    assert result["review_required"] is True


def test_multiple_source_countries_are_not_collapsed():
    result = resolve_crop_labels([source(), source("B14-30", raw="FR:B14[30]", country="FR")], CATALOGS)
    assert result["country"] == "multiple_or_mixed"
    assert result["status"] == "country_ambiguous"
    assert result["class_id"] is None


@pytest.mark.parametrize("declared_status", ["unique", "ambiguous"])
def test_genuine_semantic_ambiguity_without_precise_catalog_identity_remains_unresolved(declared_status):
    row = source("no_stop", raw="DE:283")
    row["semantic_mapping_status"] = declared_status
    row["semantic_candidates"].append({"label": "give_way"})
    result = resolve_crop_labels([row], CATALOGS)
    assert result["status"] == "ambiguous"
    assert result["class_id"] is None
    assert result["classifier_catalog_class_id"] is None


def test_unique_catalog_identity_resolves_even_without_a_semantic_alias():
    row = source("no_stop", raw="DE:283", catalog_class="no_stop")
    row["semantic_mapping_status"] = "unmapped"
    row["semantic_candidates"] = []
    result = resolve_crop_labels([row], CATALOGS)
    assert result["status"] == "unique"
    assert result["class_id"] == "no_stop"
    assert result["label_origin"] == "source_annotation"
    assert result["identity_basis"] == "classifier_catalog"
    assert result["classifier_supported"] is True
    assert result["review_required"] is False


def test_semantic_and_catalog_names_are_different_ontologies_of_the_same_annotation():
    row = source("generic-arrow-alias", raw="FR:B21a2", country="FR", catalog_class="B21a2")
    result = resolve_crop_labels([row], CATALOGS, model_labels=MODEL_LABELS)
    assert result["status"] == "unique"
    assert result["class_id"] == "B21a2"
    assert result["classifier_catalog_class_id"] == "B21a2"
    assert result["identity_basis"] == "classifier_catalog"
    assert result["review_required"] is False
    assert result["semantic_mappings"][0]["candidate_class_ids"] == ["generic-arrow-alias"]


def test_exact_catalog_validation_rejects_unknown_ids_without_string_heuristics():
    result = resolve_crop_labels([source("city_start")], CATALOGS)
    assert result["status"] == "unresolved"
    assert result["class_id"] is None
    assert result["classifier_supported"] is False
    assert "semantic_unique_without_exact_catalog_class" in result["reasons"]


def test_unknown_selected_catalog_id_is_retained_as_evidence_but_never_used_as_target():
    row = source("not-in-catalog", catalog_class="not-a-catalog-model-class")
    result = resolve_crop_labels([row], CATALOGS)
    assert result["class_id"] is None
    assert result["status"] == "unresolved"
    assert result["classifier_catalog_class_id"] is None
    assert result["current_model_class_id"] is None
    assert result["selected_catalog_class_ids"] == ["not-a-catalog-model-class"]
    assert result["classifier_supported"] is False
    assert "classifier_catalog_identity_invalid" in result["reasons"]


def test_selected_catalog_class_must_belong_to_explicit_current_inventory():
    row = source("no_stop", raw="DE:283", catalog_class="no_stop")
    result = resolve_crop_labels([row], CATALOGS, model_labels={"DE": set()})
    assert result["class_id"] == "no_stop"
    assert result["identity_basis"] == "semantic_catalog"
    assert result["classifier_catalog_class_id"] is None
    assert result["classifier_supported"] is False
    assert result["review_required"] is True
    assert "classifier_catalog_class_not_in_inventory" in result["reasons"]


def test_extra_unresolved_non_detection_tag_is_retained_for_review():
    unknown = {"raw_tag": "DE:made-up", "target_classifier_country": "DE",
               "semantic_mapping_status": "unmapped", "yolo_mapping_status": "unmapped"}
    result = resolve_crop_labels([source(), unknown], CATALOGS)
    assert result["class_id"] == "city:start"
    assert result["status"] == "unique"
    assert result["review_required"] is True
    assert "unresolved_source_tags" in result["reasons"]
    assert result["raw_tags"] == ["DE:310", "DE:made-up"]


def test_inventory_controls_capability_independently_of_source_mapping_route():
    result = resolve_crop_labels([source()], CATALOGS, model_labels={"DE": {"city:start"}})
    assert result["classifier_supported"] is True
    assert result["classifier_catalog_class_id"] is None
    without_inventory = resolve_crop_labels([source()], CATALOGS)
    assert without_inventory["classifier_supported"] is False


@pytest.mark.parametrize("labels", [[], [detection()]])
def test_no_class_evidence_remains_explicit(labels):
    result = resolve_crop_labels(labels, CATALOGS)
    assert result["status"] == "unresolved"
    assert result["class_id"] is None
    assert result["review_required"] is True

"""Guard the human-review boundary; draft labels must never qualify for F1."""
from copy import deepcopy

import pytest

from scripts.tsr.de_label_review import validate_submission


@pytest.fixture
def frozen():
    return {"manifest_sha256": "manifest", "catalog_sha256": "catalog",
            "classes": [{"id": "city:start"}],
            "records": [{"id": "P001", "native_sha256": "native",
                         "canonical_sha256": "canonical", "decision": "city:start",
                         "reviewed": False, "note": ""}]}


def test_draft_can_save_but_cannot_approve(frozen):
    assert not validate_submission(frozen, frozen, False)[0]["reviewed"]
    with pytest.raises(ValueError, match="explicitly reviewed"):
        validate_submission(frozen, frozen, True)


def test_explicit_review_and_exclusion_preserved(frozen):
    submitted = deepcopy(frozen)
    submitted["records"][0].update(reviewed=True, decision="@out_of_catalog")
    assert validate_submission(submitted, frozen, True)[0]["decision"] == "@out_of_catalog"


@pytest.mark.parametrize("field", ["native_sha256", "canonical_sha256"])
def test_wrong_crop_rejected(frozen, field):
    submitted = deepcopy(frozen)
    submitted["records"][0][field] = "wrong"
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_submission(submitted, frozen, False)


def test_unknown_class_rejected(frozen):
    submitted = deepcopy(frozen)
    submitted["records"][0]["decision"] = "bus:stop"
    with pytest.raises(ValueError, match="Invalid review decision"):
        validate_submission(submitted, frozen, False)


def test_truthy_string_cannot_approve(frozen):
    submitted = deepcopy(frozen)
    submitted["records"][0]["reviewed"] = "true"
    with pytest.raises(ValueError):
        validate_submission(submitted, frozen, True)


def test_duplicate_ids_rejected(frozen):
    frozen["records"].append({**frozen["records"][0], "id": "P002"})
    submitted = deepcopy(frozen)
    submitted["records"][1]["id"] = "P001"
    with pytest.raises(ValueError, match="duplicate"):
        validate_submission(submitted, frozen, False)

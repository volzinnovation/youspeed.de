"""Class-index integrity matters when extending existing device classifiers."""
import pytest

from scripts.tsr.export_de_expanded_mobile import validate_classes


def predecessor():
    return [f"original:{i}" for i in range(134)] + ["city:start", "city:end"]


def test_valid_expansion_retains_existing_indices():
    base = predecessor()
    validate_classes(base + ["bus:stop", "supplementary:plate"], base)


def test_permuted_existing_classes_rejected():
    base = predecessor()
    expanded = base + ["bus:stop"]
    expanded[0], expanded[1] = expanded[1], expanded[0]
    with pytest.raises(ValueError, match="preserve"):
        validate_classes(expanded, base)


def test_duplicate_new_class_rejected():
    base = predecessor()
    with pytest.raises(ValueError, match="Duplicate"):
        validate_classes(base + ["city:start"], base)


@pytest.mark.parametrize("bad", ["", " bus:stop", 224])
def test_invalid_new_identifier_rejected(bad):
    base = predecessor()
    with pytest.raises(ValueError, match="Class IDs"):
        validate_classes(base + [bad], base)


def test_unexpanded_model_rejected():
    with pytest.raises(ValueError, match="preserve"):
        validate_classes(predecessor(), predecessor())

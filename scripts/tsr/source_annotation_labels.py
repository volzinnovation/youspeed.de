"""Resolve source-annotation class identities independently of model inference.

``selected_yolo`` is the reverse mapping of the same source tag into the current
classifier-compatible catalogue. It is not a classifier prediction. A source
class absent from that inventory can still have an exact semantic catalogue ID.
"""
from __future__ import annotations


def resolve_crop_labels(
    labels: list[dict],
    catalogs: dict[str, set[str]],
    *,
    model_labels: dict[str, set[str]] | None = None,
) -> dict:
    """Return a single catalogue identity while retaining source uncertainty.

    Prefer a unique ``selected_yolo`` identity validated against ``catalogs``
    and, when provided, the separate current ``model_labels`` inventories. Fall
    back to an exact unique semantic catalogue identity if no such mapping
    exists. Generic semantic aliases do not erase a precise catalogue mapping
    of the same source tag. Effective classes from distinct non-detection tags
    still have to agree; conflicting classes are compound, not extra crops.

    Both identity routes have ``label_origin='source_annotation'``. The
    deprecated ``current_model_class_id`` field aliases
    ``classifier_catalog_class_id``; neither field establishes model inference.
    Detection-only ``parsed.code == 'yes'`` records do not compete with classes.
    Inputs are never mutated. This function does not establish human review or
    training eligibility, or create classifier indices.
    """
    if not isinstance(labels, list):
        raise ValueError("labels_must_be_list")

    reasons = set()
    raw_tags, ignored_tags = set(), set()
    effective_classes, classifier_classes = set(), set()
    selected_catalog_class_ids = set()
    semantic_mappings = []
    countries, bases = set(), set()
    needs_review = False
    explicit_ambiguity = False
    country_problem = None
    active_labels = 0
    unresolved_labels = 0

    for label in labels:
        if not isinstance(label, dict):
            reasons.add("invalid_label_metadata")
            unresolved_labels += 1
            continue
        raw_tag = label.get("raw_tag")
        if isinstance(raw_tag, str):
            raw_tags.add(raw_tag)
        parsed = label.get("parsed")
        parsed = parsed if isinstance(parsed, dict) else {}
        if parsed.get("code") == "yes":
            token = parsed.get("raw")
            ignored_tags.add(token if isinstance(token, str) else raw_tag if isinstance(raw_tag, str) else "yes")
            continue

        active_labels += 1
        country = label.get("target_classifier_country") or label.get("country")
        if isinstance(country, str) and country and country != "unknown":
            countries.add(country)
        statuses = {
            label.get("country_resolution_state"),
            label.get("semantic_mapping_status"),
            label.get("yolo_mapping_status"),
        }
        if "country_conflict" in statuses:
            country_problem = "country_conflict"
            reasons.add("country_conflict")
        elif "country_ambiguous" in statuses:
            if country_problem != "country_conflict":
                country_problem = "country_ambiguous"
            reasons.add("country_ambiguous")

        selected = label.get("selected_yolo")
        selected_id = selected.get("label") if isinstance(selected, dict) else None
        if label.get("yolo_mapping_status") == "unique" and isinstance(selected_id, str) and selected_id:
            selected_catalog_class_ids.add(selected_id)
        semantic_status = label.get("semantic_mapping_status")
        candidates = label.get("semantic_candidates", [])
        candidate_ids = {candidate["label"] for candidate in candidates
                         if isinstance(candidate, dict) and isinstance(candidate.get("label"), str)
                         and candidate["label"]} if isinstance(candidates, list) else set()
        semantic_mappings.append({
            "raw_tag": raw_tag if isinstance(raw_tag, str) else None,
            "country": country if isinstance(country, str) else None,
            "status": semantic_status if isinstance(semantic_status, str) else None,
            "candidate_class_ids": sorted(candidate_ids),
        })
        if not isinstance(country, str) or country not in catalogs:
            reasons.add("country_unknown" if not country or country == "unknown" else "country_not_in_catalog")
            unresolved_labels += 1
            continue

        classifier_id = None
        if label.get("yolo_mapping_status") == "unique":
            if not isinstance(selected_id, str) or selected_id not in catalogs[country]:
                reasons.add("classifier_catalog_identity_invalid")
                needs_review = True
            elif model_labels is not None and selected_id not in model_labels.get(country, set()):
                reasons.add("classifier_catalog_class_not_in_inventory")
                needs_review = True
            else:
                classifier_id = selected_id
                classifier_classes.add((country, classifier_id))

        if classifier_id is not None:
            # These semantic candidates are aliases/alternatives in a broader
            # ontology, not an independent annotation or competing prediction.
            effective_classes.add((country, classifier_id))
            bases.add("classifier_catalog")
            if semantic_status == "ambiguous" or len(candidate_ids) > 1:
                reasons.add("semantic_alias_ambiguity_preserved")
            if candidate_ids - catalogs[country]:
                reasons.add("semantic_aliases_outside_catalog")
            continue

        candidates_valid = isinstance(candidates, list) and all(
            isinstance(candidate, dict) and isinstance(candidate.get("label"), str)
            and candidate["label"] in catalogs[country] for candidate in candidates)
        if semantic_status == "unique" and candidates_valid and len(candidate_ids) == 1:
            effective_classes.add((country, next(iter(candidate_ids))))
            bases.add("semantic_catalog")
            continue
        if semantic_status == "ambiguous" or (semantic_status == "unique" and len(candidate_ids) > 1):
            explicit_ambiguity = True
            reasons.add("semantic_ambiguous")
        elif label.get("yolo_mapping_status") == "ambiguous":
            explicit_ambiguity = True
            reasons.add("classifier_catalog_ambiguous")
        if not candidates_valid or (semantic_status == "unique" and not candidate_ids):
            reasons.add("semantic_unique_without_exact_catalog_class" if semantic_status == "unique"
                        else "semantic_candidates_not_in_catalog")
        unresolved_labels += 1
        for name in ("semantic_mapping_status", "yolo_mapping_status"):
            value = label.get(name)
            if isinstance(value, str) and value:
                reasons.add(f"{name}:{value}")
        if not semantic_status and not label.get("yolo_mapping_status"):
            reasons.add("label_without_mapping")

    if ignored_tags:
        reasons.add("detection_only_tags_ignored")
    country = next(iter(countries)) if len(countries) == 1 else "multiple_or_mixed" if countries else "unknown"
    class_id, origin, basis = None, None, None
    status = "unresolved"
    if country_problem:
        status = country_problem
    elif len(countries) > 1:
        status = "country_ambiguous"
        reasons.add("multiple_annotation_countries")
    elif len(effective_classes) > 1:
        status = "compound"
        origin = "source_annotation"
        reasons.add("multiple_source_classes")
    elif explicit_ambiguity:
        status = "ambiguous"
    elif effective_classes:
        country, class_id = next(iter(effective_classes))
        status, origin = "unique", "source_annotation"
    elif active_labels == 0 and not unresolved_labels:
        reasons.add("detection_only_without_class" if ignored_tags else "no_source_labels")
    if origin is not None:
        basis = next(iter(bases)) if len(bases) == 1 else "mixed"
    if unresolved_labels:
        reasons.add("unresolved_source_tags")
        needs_review = True

    classifier_id = next(iter(classifier_classes))[1] if len(classifier_classes) == 1 else None
    supported = False
    if class_id is not None:
        supported = (class_id in model_labels.get(country, set()) if model_labels is not None
                     else classifier_classes == {(country, class_id)})
    semantic_mappings = sorted(
        {repr(sorted(mapping.items())): mapping for mapping in semantic_mappings}.values(),
        key=lambda mapping: (mapping["country"] or "", mapping["raw_tag"] or "", mapping["status"] or "",
                             mapping["candidate_class_ids"]),
    )
    return {
        "country": country,
        "class_id": class_id,
        "status": status,
        "label_origin": origin,
        "identity_basis": basis,
        "classifier_catalog_class_id": classifier_id,
        "current_model_class_id": classifier_id,
        "classifier_supported": supported,
        "ignored_detection_tags": sorted(ignored_tags),
        "raw_tags": sorted(raw_tags),
        "reasons": sorted(reasons),
        "review_required": needs_review or status != "unique",
        "source_class_ids": sorted(class_id for _, class_id in effective_classes),
        "model_class_ids": sorted(class_id for _, class_id in classifier_classes),
        "source_classes": [{"country": country, "class_id": class_id} for country, class_id in sorted(effective_classes)],
        "model_classes": [{"country": country, "class_id": class_id} for country, class_id in sorted(classifier_classes)],
        "selected_catalog_class_ids": sorted(selected_catalog_class_ids),
        "semantic_mappings": semantic_mappings,
    }

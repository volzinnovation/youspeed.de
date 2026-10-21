#!/usr/bin/env python3
"""Offline exact-exposure semantic-hint qualification prototype (#21/#23).

No detector, tracker, candidate ranking, phone scheduling, or speed policy is
changed. JSON schemas describe structure; this module also checks cross-field
geometry, clocks and model identity. All rejected hints have zero influence.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


MAX_CELLS = 262_144
MAX_SAFE_INTEGER = 2**53 - 1  # Exact in JSON consumers that use binary64.
SCOPE_KEYS = ("sessionId", "sessionGeneration", "cameraId", "cameraGeneration", "calibrationGeneration")
MODEL_KEYS = ("modelId", "revision", "outputKind")
OUTPUT_KIND = "lane-paint-probability-v1"


def _keys(value, required):
    return isinstance(value, dict) and set(value) == set(required)


def _integer(value, minimum=0, maximum=MAX_SAFE_INTEGER):
    return type(value) is int and minimum <= value <= maximum


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512


def _probability(value):
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def _scope(value):
    return (_keys(value, SCOPE_KEYS) and _text(value["sessionId"]) and _text(value["cameraId"])
            and all(_integer(value[k]) for k in SCOPE_KEYS if k.endswith("Generation")))


def _model(value):
    return _keys(value, MODEL_KEYS) and all(_text(value[k]) for k in MODEL_KEYS)


def _exposure(value):
    return (_keys(value, ("frameId", "sourceTimeNs", "sourceClockId", "capturedAtNs", "clockId", "clockKnown"))
            and all(_text(value[k]) for k in ("frameId", "sourceClockId", "clockId"))
            and all(_integer(value[k]) for k in ("sourceTimeNs", "capturedAtNs"))
            and type(value["clockKnown"]) is bool)


def _geometry(value):
    if not _keys(value, ("sourceWidth", "sourceHeight", "crop", "rotationDegrees", "mirrored", "analysisWidth",
                         "analysisHeight", "mappingId", "fullScene")):
        return False
    if not all(_integer(value[k], 1, 32_768) for k in ("sourceWidth", "sourceHeight", "analysisWidth", "analysisHeight")):
        return False
    if type(value["rotationDegrees"]) is not int or value["rotationDegrees"] not in (0, 90, 180, 270):
        return False
    if type(value["mirrored"]) is not bool or type(value["fullScene"]) is not bool or not _text(value["mappingId"]):
        return False
    crop = value["crop"]
    return (_keys(crop, ("x", "y", "width", "height"))
            and all(_integer(crop[k]) for k in ("x", "y"))
            and all(_integer(crop[k], 1, 32_768) for k in ("width", "height"))
            and crop["x"] + crop["width"] <= value["sourceWidth"]
            and crop["y"] + crop["height"] <= value["sourceHeight"])


def _full_scene(geometry):
    return geometry["fullScene"] and geometry["crop"] == {
        "x": 0, "y": 0, "width": geometry["sourceWidth"], "height": geometry["sourceHeight"]}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class QualificationPolicy:
    """Frozen experiment settings; max age is not an approved release threshold."""
    model_id: str
    revision: str
    mask_width: int
    mask_height: int
    max_capture_age_ns: int
    output_kind: str = OUTPUT_KIND

    def __post_init__(self):
        if not all(_text(x) for x in (self.model_id, self.revision)) or self.output_kind != OUTPUT_KIND:
            raise ValueError("Explicit model identity and lane-paint probability output required")
        if not all(_integer(x, 1, 512) for x in (self.mask_width, self.mask_height)) or self.mask_width * self.mask_height > MAX_CELLS:
            raise ValueError("Mask dimensions exceed prototype bounds")
        if not _integer(self.max_capture_age_ns, 1):
            raise ValueError("Positive integer experiment age budget required")

    @classmethod
    def from_mapping(cls, value):
        if not _keys(value, ("schemaVersion", "modelIdentity", "maskWidth", "maskHeight", "maxCaptureAgeNs")):
            raise ValueError("Invalid policy fields")
        if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or not _model(value["modelIdentity"]):
            raise ValueError("Invalid policy schema/model")
        model = value["modelIdentity"]
        return cls(model["modelId"], model["revision"], value["maskWidth"], value["maskHeight"],
                   value["maxCaptureAgeNs"], model["outputKind"])

    @property
    def model_identity(self):
        return {"modelId": self.model_id, "revision": self.revision, "outputKind": self.output_kind}


@dataclass(frozen=True)
class QualifiedHint:
    """Immutable valid-cell evidence only; never observed support or confirmation."""
    frame_id: str
    source_time_ns: int
    source_clock_id: str
    captured_at_ns: int
    clock_id: str
    arrived_at_ns: int
    scope_identity: str
    geometry_identity: str
    model_identity: str
    provenance_identity: str
    width: int
    height: int
    probabilities: tuple
    validity: tuple


@dataclass(frozen=True)
class Qualification:
    reason: str
    hint: QualifiedHint | None = None
    capture_age_ns: int | None = None

    @property
    def accepted(self):
        return self.hint is not None


def _context_reason(context):
    if not _keys(context, ("schemaVersion", "scope", "exposure", "geometry", "now")):
        return "invalid_context"
    if type(context["schemaVersion"]) is not int or context["schemaVersion"] != 1:
        return "invalid_context"
    if not _scope(context["scope"]) or not _exposure(context["exposure"]) or not _geometry(context["geometry"]):
        return "invalid_context"
    now = context["now"]
    if not _keys(now, ("atNs", "clockId", "clockKnown")) or not _integer(now["atNs"]) or not _text(now["clockId"]) or type(now["clockKnown"]) is not bool:
        return "invalid_context"
    if not now["clockKnown"] or not context["exposure"]["clockKnown"]:
        return "unknown_clock"
    if now["clockId"] != context["exposure"]["clockId"]:
        return "clock_mismatch"
    if now["atNs"] < context["exposure"]["capturedAtNs"]:
        return "future_capture"
    if not _full_scene(context["geometry"]):
        return "partial_scene_unsupported"
    return None


def qualify(hint, context, policy: QualificationPolicy) -> Qualification:
    """Fail closed. Caller supplies trusted current exposure and frozen policy.

    Exact identities establish declared alignment, not actual image calibration.
    Invalid mask cells are unknown; consumers must never treat them as zeros.
    """
    if not isinstance(policy, QualificationPolicy):
        raise TypeError("Use an immutable QualificationPolicy")
    context_reason = _context_reason(context)
    if context_reason:
        return Qualification(context_reason)
    if hint is None:
        return Qualification("missing_hint")
    if not _keys(hint, ("schemaVersion", "modelIdentity", "provenance", "scope", "exposure", "arrival", "geometry", "alignment", "mask")):
        return Qualification("invalid_hint")
    if type(hint["schemaVersion"]) is not int or hint["schemaVersion"] != 1:
        return Qualification("schema_mismatch")
    if not _model(hint["modelIdentity"]) or hint["modelIdentity"] != policy.model_identity:
        return Qualification("model_mismatch")
    provenance = hint["provenance"]
    if not _keys(provenance, ("kind", "sourceId")) or provenance["kind"] not in ("model_inference", "synthetic_fixture") or not _text(provenance["sourceId"]):
        return Qualification("invalid_provenance")
    if not _scope(hint["scope"]):
        return Qualification("invalid_scope")
    if hint["scope"] != context["scope"]:
        return Qualification("scope_mismatch")
    if not _exposure(hint["exposure"]):
        return Qualification("invalid_exposure")
    exposure = hint["exposure"]
    if not exposure["clockKnown"]:
        return Qualification("unknown_clock")
    if any(exposure[k] != context["exposure"][k] for k in ("clockId", "sourceClockId")):
        return Qualification("clock_mismatch")
    if exposure != context["exposure"]:
        return Qualification("exposure_mismatch")
    arrival = hint["arrival"]
    if not _keys(arrival, ("atNs", "clockId", "clockKnown")) or not _integer(arrival["atNs"]) or not _text(arrival["clockId"]) or type(arrival["clockKnown"]) is not bool:
        return Qualification("invalid_arrival")
    if not arrival["clockKnown"]:
        return Qualification("unknown_clock")
    if arrival["clockId"] != exposure["clockId"]:
        return Qualification("clock_mismatch")
    if arrival["atNs"] < exposure["capturedAtNs"]:
        return Qualification("arrival_before_capture")
    if arrival["atNs"] > context["now"]["atNs"]:
        return Qualification("future_arrival")
    age = context["now"]["atNs"] - exposure["capturedAtNs"]
    if age > policy.max_capture_age_ns:
        return Qualification("stale_hint", capture_age_ns=age)
    if not _geometry(hint["geometry"]):
        return Qualification("invalid_geometry", capture_age_ns=age)
    if hint["geometry"] != context["geometry"]:
        return Qualification("geometry_mismatch", capture_age_ns=age)
    if hint["alignment"] != {"mode": "exact_exposure"}:
        return Qualification("alignment_unsupported", capture_age_ns=age)
    mask = hint["mask"]
    if not _keys(mask, ("width", "height", "probabilities", "validity")):
        return Qualification("invalid_mask", capture_age_ns=age)
    if not _integer(mask["width"], 1, 512) or not _integer(mask["height"], 1, 512) or (mask["width"], mask["height"]) != (policy.mask_width, policy.mask_height):
        return Qualification("shape_mismatch", capture_age_ns=age)
    size = mask["width"] * mask["height"]
    if any(not isinstance(mask[k], list) or len(mask[k]) != size for k in ("probabilities", "validity")):
        return Qualification("shape_mismatch", capture_age_ns=age)
    if not all(_probability(value) for value in mask["probabilities"]):
        return Qualification("invalid_scores", capture_age_ns=age)
    if not all(type(value) is bool for value in mask["validity"]):
        return Qualification("invalid_validity", capture_age_ns=age)
    if not any(mask["validity"]):
        return Qualification("no_valid_pixels", capture_age_ns=age)
    qualified = QualifiedHint(exposure["frameId"], exposure["sourceTimeNs"], exposure["sourceClockId"],
        exposure["capturedAtNs"], exposure["clockId"], arrival["atNs"], _canonical(hint["scope"]),
        _canonical(hint["geometry"]), _canonical(hint["modelIdentity"]), _canonical(provenance),
        mask["width"], mask["height"], tuple(mask["probabilities"]), tuple(mask["validity"]))
    return Qualification("qualified", qualified, age)


@dataclass(frozen=True)
class OfflineGuidanceInput:
    baseline: Any
    qualification: Qualification


def prepare_guidance(baseline, hint, context, policy):
    """Return the baseline object unchanged next to optional qualified evidence.

    This does not mutate raw confidence, support, confirmations or identities.
    No downstream score adjustment or production-output parity is implied.
    """
    return OfflineGuidanceInput(baseline, qualify(hint, context, policy))


def _context_key(context):
    return (_canonical(context["scope"]), _canonical(context["geometry"]),
            context["exposure"]["sourceClockId"], context["exposure"]["clockId"])


def _snapshot(value):
    return json.loads(_canonical(value))


class HintCache:
    """Offline, single-owner cache; results cannot advance scope or exposure.

    advance() updates the authoritative current exposure in the same scope.
    reset_scope() is an explicit owner lifecycle operation, never triggered by
    an arriving hint. Previously cached maps cannot be used on another exposure.
    """
    def __init__(self, policy, context):
        if not isinstance(policy, QualificationPolicy):
            raise TypeError("Use an immutable QualificationPolicy")
        self.policy = policy
        self.reset_scope(context)

    def reset_scope(self, context):
        reason = _context_reason(context)
        if reason:
            raise ValueError(reason)
        self._context = _snapshot(context)
        self._key = _context_key(context)
        self._hint = None
        self._latest_source_time_ns = None

    @property
    def latest_source_time_ns(self):
        return self._latest_source_time_ns

    def advance(self, context):
        """Reject regressions without changing any cache state; return reason."""
        reason = _context_reason(context)
        if reason:
            return reason
        if _context_key(context) != self._key:
            return "context_scope_mismatch"
        old, new = self._context["exposure"], context["exposure"]
        if context["now"]["atNs"] < self._context["now"]["atNs"]:
            return "context_clock_regression"
        if new["sourceTimeNs"] < old["sourceTimeNs"] or new["capturedAtNs"] < old["capturedAtNs"]:
            return "context_exposure_regression"
        if new["sourceTimeNs"] == old["sourceTimeNs"] and new != old:
            return "context_exposure_conflict"
        if new["sourceTimeNs"] > old["sourceTimeNs"] and (new["frameId"] == old["frameId"] or new["capturedAtNs"] == old["capturedAtNs"]):
            return "context_exposure_conflict"
        self._context = _snapshot(context)
        return "advanced"

    def offer(self, hint):
        result = qualify(hint, self._context, self.policy)
        if not result.accepted:
            return result
        source_time = result.hint.source_time_ns
        if self._latest_source_time_ns is not None and source_time <= self._latest_source_time_ns:
            reason = "duplicate_exposure" if source_time == self._latest_source_time_ns else "out_of_order_exposure"
            return Qualification(reason, capture_age_ns=result.capture_age_ns)
        self._hint = _snapshot(hint)
        self._latest_source_time_ns = source_time
        return result

    def current(self):
        return qualify(self._hint, self._context, self.policy)

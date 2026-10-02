"""Executable semantics for the versioned speed-reference EFSM (no app I/O).

The JSON supplies transition order, priority, actions and limits. This interpreter
defines the deliberately small guard/action vocabulary documented in MODEL.md.
It is a reference oracle, not an assertion that either controller conforms yet.
"""
from copy import deepcopy
import math


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class Machine:
    def __init__(self, policy):
        self.policy = policy
        self.state = self.empty_state()

    @staticmethod
    def empty_state():
        return dict(voice=None, camera=None, camera_context=None, bundle=None, last_known=None,
                    generation=0, pending_context=False, gap_origin=None,
                    seen_ids=set(), evidence_origins={}, applicability_revision=0,
                    elapsed_s=0, distance_m=0,
                    session_id=None, sequence=-1)

    def valid_value(self, value):
        if not isinstance(value, dict):
            return False
        domain = self.policy["value_domain"]
        kind = value.get("kind")
        if kind not in domain["kinds"]:
            return False
        if kind != "numeric":
            return set(value) == {"kind"}
        speed = value.get("kmh")
        return (set(value) == {"kind", "kmh"} and type(speed) is int
                and domain["numeric_min_kmh"] <= speed <= domain["numeric_max_kmh"])

    def validate(self, e):
        s = self.state
        if e.get("kind") not in self.policy["events"]:
            return "unknown_event"
        if not isinstance(e.get("session_id"), str) or not e["session_id"]:
            return "invalid_session"
        if type(e.get("sequence")) is not int or e["sequence"] < 0:
            return "invalid_sequence"
        if not all(finite_number(e.get(key)) for key in ("elapsed_s", "distance_m")):
            return "invalid_progress"
        if e["kind"] == "reset":
            if e["session_id"] == s["session_id"]:
                return "duplicate_session"
            if e["elapsed_s"] != 0 or e["distance_m"] != 0:
                return "invalid_session_origin"
            return None
        if s["session_id"] is None or e["session_id"] != s["session_id"]:
            return "wrong_session"
        if e["sequence"] <= s["sequence"]:
            return "out_of_order"
        if any(e[key] < s[key] for key in ("elapsed_s", "distance_m")):
            return "non_monotonic_progress"
        if e["kind"] != "tick" and type(e.get("generation")) is not int:
            return "invalid_generation"
        if e["kind"] in ("voice", "camera", "camera_context", "bundle", "context_confirmed"):
            if not isinstance(e.get("id"), str) or not e["id"]:
                return "missing_evidence_id"
        if e["kind"] in ("voice", "camera", "camera_context", "bundle") and not self.valid_value(e.get("value")):
            return "invalid_value"
        if e["kind"] in self.policy["input_contracts"]["applicability"]["sources"]:
            a = e.get("applicability")
            if (not isinstance(a, dict) or a.get("status") not in self.policy["input_contracts"]["applicability"]["statuses"]
                    or type(a.get("context_revision")) is not int or not isinstance(a.get("conditions"), (list, dict))):
                return "invalid_applicability_envelope"
        if e["kind"] == "camera":
            for key, current in (("observed_elapsed_s", "elapsed_s"), ("observed_distance_m", "distance_m")):
                if not finite_number(e.get(key)) or e[key] > e[current]:
                    return "invalid_evidence_origin"
            origin = s["evidence_origins"].get(e["id"])
            if origin is not None and origin != (e["observed_elapsed_s"], e["observed_distance_m"]):
                return "changed_evidence_origin"
        return None

    def evidence_key(self, e):
        revision = e.get("applicability", {}).get("context_revision") if e["kind"] in ("camera", "camera_context") else None
        return e["kind"], e.get("id"), revision

    def applicable(self, e):
        a = e.get("applicability", {})
        return (a.get("status") == self.policy["input_contracts"]["applicability"]["selection_requires"]
                and a.get("context_revision") == self.state["applicability_revision"])

    def guard(self, name, e):
        s = self.state
        scoped = e.get("generation") == s["generation"]
        fresh = scoped and self.evidence_key(e) not in s["seen_ids"]
        if name in ("always", "new_session"):
            return True
        if name == "current_generation":
            return scoped
        if name == "verified_current_generation":
            return scoped and e.get("verified") is True
        if name == "fresh_scoped_evidence":
            return fresh and e.get("verified") is True
        if name == "fresh_applicable_pipeline_output":
            within_lifetime = e["kind"] != "camera" or (
                s["elapsed_s"] - e["observed_elapsed_s"] < self.policy["limits"]["ordinary_max_age_s"]
                and s["distance_m"] - e["observed_distance_m"] < self.policy["limits"]["ordinary_max_distance_m"])
            return (fresh and e.get("verified") is True and s["voice"] is None
                    and not s["pending_context"] and s["gap_origin"] is None
                    and self.applicable(e) and within_lifetime)
        if name == "verified_enclosing_camera":
            return (self.guard("fresh_applicable_pipeline_output", e)
                    and e.get("area_verified") is True
                    and e.get("scope_kind") in ("zone", "city"))
        if name == "current_verified_bundle":
            return (scoped and e.get("verified") is True
                    and not s["pending_context"] and s["gap_origin"] is None and self.applicable(e))
        if name == "new_applicability_revision":
            return (scoped and type(e.get("next_revision")) is int
                    and e["next_revision"] > s["applicability_revision"])
        if name == "fresh_confirmed_boundary":
            return (fresh and e.get("confirmed") is True
                    and e.get("reason") in self.policy["boundary_reasons"])
        raise ValueError(f"Unknown guard: {name}")

    def action(self, action, e):
        s = self.state
        if action == "reset_session":
            self.state = self.empty_state()
            self.state.update(session_id=e["session_id"], sequence=e["sequence"])
        elif action.startswith("accept_"):
            source = action.removeprefix("accept_")
            assert source in (*self.policy["priority"], "camera_context")
            s[source] = dict(id=e["id"], value=deepcopy(e["value"]),
                             generation=s["generation"], source="camera" if source == "camera_context" else source,
                             accepted_elapsed_s=e["observed_elapsed_s"] if source == "camera" else s["elapsed_s"],
                             accepted_distance_m=e["observed_distance_m"] if source == "camera" else s["distance_m"])
        elif action in ("clear_voice", "clear_camera", "clear_camera_context", "clear_bundle"):
            s[action.removeprefix("clear_")] = None
        elif action == "clear_camera_memory":
            if s["last_known"] and s["last_known"]["source"] == "camera":
                s["last_known"] = None
        elif action == "advance_generation":
            s["generation"] += 1
        elif action == "advance_applicability_revision":
            s["applicability_revision"] = e["next_revision"]
        elif action == "mark_pending":
            s["pending_context"] = True
        elif action == "clear_pending":
            s["pending_context"] = False
        elif action == "clear_gap":
            s["gap_origin"] = None
        elif action == "start_gap_once":
            if s["gap_origin"] is None:
                s["gap_origin"] = {k: s[k] for k in ("elapsed_s", "distance_m")}
        else:
            raise ValueError(f"Unknown action: {action}")

    def expire(self):
        s, reasons = self.state, []
        for rule in self.policy["expiry"]:
            assert rule["comparison"] == ">="
            for source in rule["sources"]:
                claim = s[source]
                if claim is not None and s[rule["metric"]] - claim[rule["origin"]] >= self.policy["limits"][rule["limit"]]:
                    s[source] = None
                    reasons.append(f"{source}:{rule['id']}")
        gap = s["gap_origin"]
        if gap is not None:
            limits = self.policy["limits"]
            exceeded = (s["elapsed_s"] - gap["elapsed_s"] >= limits["context_gap_max_age_s"]
                        or s["distance_m"] - gap["distance_m"] >= limits["context_gap_max_distance_m"])
            if exceeded:
                for source in (*self.policy["priority"], "camera_context"):
                    if s[source] is not None:
                        s[source] = None
                        reasons.append(f"{source}:context_gap")
        return reasons

    def project(self, transition, reasons, rejection=None):
        s = self.state
        for row in self.policy["selection"]:
            claim = s.get(row["register"])
            if row["register"] is None or claim is not None:
                break
        if row["current"]:
            s["last_known"] = deepcopy(claim)
        value = deepcopy(claim["value"]) if claim else None
        numeric = value["kmh"] if row["current"] and value["kind"] == "numeric" else None
        return dict(policy_version=self.policy["version"], state=row["state"], value=value,
                    source=claim["source"] if claim else None,
                    evidence_id=claim["id"] if claim else None, generation=s["generation"],
                    applicability_revision=s["applicability_revision"],
                    current=row["current"], display_stale=row["state"] == "LAST_KNOWN",
                    violation_reference_kmh=numeric, penalty_reference_kmh=numeric,
                    transition_id=transition, expiry_reasons=reasons, rejection=rejection)

    def step(self, event):
        e = deepcopy(event)
        invalid = self.validate(e)
        if invalid:
            return self.project("REJECT", [], invalid)
        if e["kind"] != "reset":
            self.state.update({k: e[k] for k in ("sequence", "elapsed_s", "distance_m")})
            expiry = self.expire()
        else:
            expiry = []
        for rule in self.policy["transitions"]:
            if rule["on"] in (e["kind"], "*") and self.guard(rule["guard"], e):
                for action in rule["actions"]:
                    self.action(action, e)
                break
        else:
            raise ValueError("Transition table is not total")
        if e["kind"] in ("voice", "camera", "camera_context", "context_confirmed"):
            self.state["seen_ids"].add(self.evidence_key(e))
        if e["kind"] == "camera":
            self.state["evidence_origins"].setdefault(e["id"], (e["observed_elapsed_s"], e["observed_distance_m"]))
        return self.project(rule["id"], expiry)

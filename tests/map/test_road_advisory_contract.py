"""Check the same versioned wire fixtures consumed by Swift, Kotlin and Python."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared/roadworks"


class RoadAdvisoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT / "docs/MOBIDATA_BW_ROAD_ADVISORIES_API_V2.openapi.json").read_text())
        cls.manifest = json.loads((SHARED / "manifest-v2.json").read_text())
        cls.snapshot_bytes = (SHARED / "snapshot-v2.json").read_bytes()
        cls.snapshot = json.loads(cls.snapshot_bytes)

    def validator(self, name):
        return Draft202012Validator(
            {"$ref": "#/components/schemas/" + name, "components": self.spec["components"]},
            format_checker=FormatChecker(),
        )

    def test_shared_v2_pair_validates_and_hashes_exact_downloaded_bytes(self):
        for name, value in [("Manifest", self.manifest), ("Snapshot", self.snapshot)]:
            with self.subTest(schema=name):
                self.validator(name).validate(value)
        self.assertEqual(self.manifest["snapshot_bytes"], len(self.snapshot_bytes))
        self.assertEqual(self.manifest["snapshot_id"], hashlib.sha256(self.snapshot_bytes).hexdigest())
        self.assertEqual(self.manifest["snapshot_path"],
                         "/youspeed/live/v2/regions/DE-BW/snapshots/" + self.manifest["snapshot_id"])

    def test_source_namespaces_coverage_and_feature_identifiers_agree(self):
        sources = {source["source_id"] for source in self.manifest["sources"]}
        self.assertEqual(sources, set(self.manifest["coverage"]["source_ids"]))
        self.assertEqual(sources, set(self.snapshot["source_ids"]))
        self.assertEqual(len(sources), len(self.manifest["sources"]))
        identities = set()
        for feature in self.snapshot["features"]:
            properties = feature["properties"]
            source = properties["advisory_source"]
            self.assertIn(source, sources)
            self.assertTrue(feature["id"].startswith("mobidata-bw:" + source + ":"))
            self.assertNotIn(feature["id"], identities)
            identities.add(feature["id"])
        self.assertEqual({row["properties"]["kind"] for row in self.snapshot["features"]},
                         {"roadworks", "closure", "incident", "hazard", "congestion"})
        self.assertTrue(all(credit["license_id"] == "fixture-only" for credit in self.snapshot["attributions"]))

    def test_incompatible_or_missing_source_meaning_is_not_a_valid_v2_payload(self):
        for kind in ["version", "missing_source", "unknown_source", "invalid_clock"]:
            value = copy.deepcopy(self.snapshot)
            if kind == "version":
                value["schema_version"] = 1
            elif kind == "missing_source":
                del value["features"][0]["properties"]["advisory_source"]
            elif kind == "unknown_source":
                value["source_ids"].append("unreviewed-provider")
            else:
                value["evaluation_window"]["start"] = "2026-10-28T10:00:00"
            with self.subTest(case=kind), self.assertRaises(ValidationError):
                self.validator("Snapshot").validate(value)

    def test_incident_validity_basis_is_explicit_and_status_cannot_be_relabelled(self):
        value = copy.deepcopy(self.snapshot)
        properties = next(f["properties"] for f in value["features"] if f["properties"]["advisory_source"] == "incidents-bw")
        for missing in ["validity_basis", "source_validity_status", "source_validity_start", "source_validity_end"]:
            changed = copy.deepcopy(value)
            incident = next(f["properties"] for f in changed["features"] if f["properties"]["advisory_source"] == "incidents-bw")
            incident.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValidationError):
                self.validator("Snapshot").validate(changed)
        properties.update(validity_basis="reported_active", source_validity_status="active", source_validity_end=None)
        self.validator("Snapshot").validate(value)
        properties["source_validity_status"] = "definedByValidityTimeSpec"
        with self.assertRaises(ValidationError):
            self.validator("Snapshot").validate(value)

    def test_component_schemas_and_local_references_are_well_formed(self):
        for name, schema in self.spec["components"]["schemas"].items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)
        def visit(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    prefix = "#/components/schemas/"
                    self.assertTrue(value["$ref"].startswith(prefix))
                    self.assertIn(value["$ref"][len(prefix):], self.spec["components"]["schemas"])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(self.spec)

    def test_v1_wire_fixture_still_uses_the_existing_contract(self):
        old = json.loads((ROOT / "docs/MOBIDATA_BW_ROADWORKS_API.openapi.json").read_text())
        validator = Draft202012Validator(
            {"$ref": "#/components/schemas/Snapshot", "components": old["components"]},
            format_checker=FormatChecker(),
        )
        validator.validate(json.loads((SHARED / "snapshot-v1.json").read_text()))
        self.assertEqual(old["components"]["schemas"]["Manifest"]["properties"]["schema_version"], {"const": 1})


if __name__ == "__main__":
    unittest.main()

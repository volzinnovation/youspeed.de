import importlib.util
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("plan_full_bundle_refresh", ROOT / "scripts/map/plan_full_bundle_refresh.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FullBundleRefreshPlanTests(unittest.TestCase):
    def test_default_includes_every_app_region_and_seed_once(self):
        config = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
        payload = json.loads(config.read_text())
        expected = {row["region_id"] for country in payload["countries"] for row in country["regions"]}
        actual = MODULE.resolve_targets(config)
        self.assertEqual(set(actual), expected | {"karlsruhe-regbez"})
        self.assertEqual(len(actual), 52)
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(actual[:6], list(MODULE.PRIORITY_TARGETS))
        self.assertNotIn("germany", actual)
        self.assertNotIn("france", actual)

    def test_explicit_canary_targets_preserve_order_and_dedupe(self):
        config = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
        self.assertEqual(MODULE.resolve_targets(config, "monaco, switzerland,MONACO"), ["monaco", "switzerland"])

    def test_country_override_expands_shards_without_root_bundle(self):
        config = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
        result = MODULE.resolve_targets(config, "rhone-alpes,france")
        self.assertEqual(len(result), 26)
        self.assertEqual(result[0], "rhone-alpes")
        self.assertNotIn("france", result)
        self.assertNotIn("karlsruhe-regbez", result)

    def test_unknown_empty_and_unsafe_overrides_are_rejected(self):
        config = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
        for value in ("rhones-alpes", "monaco,", "../monaco", "monaco;false"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.resolve_targets(config, value)

    def test_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "targets.json"
            for payload in ({"format": "wrong"}, {"format": "youspeed.v3.bundle.targets", "countries": []},
                            {"format": "youspeed.v3.bundle.targets", "countries": [{"country_id": "france", "regions": [{"region_id": "../bad"}]}]}):
                config.write_text(json.dumps(payload))
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    MODULE.resolve_targets(config)

    def test_unique_default_version_includes_utc_day_and_attempt(self):
        now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(MODULE.resolve_version("", "1234", "2", now=now), "2026-09-28-refresh-1234-2")
        self.assertEqual(MODULE.resolve_version("2026-09-28", "", "1"), "2026-09-28")

    def test_version_rejects_missing_identity_and_path_or_output_injection(self):
        for args in (("", "", "1"), ("", "123", "bad"), ("../version", "", "1"),
                     ("test\nforged=value", "", "1"), ("x" * 129, "", "1")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                MODULE.resolve_version(*args)


if __name__ == "__main__":
    unittest.main()

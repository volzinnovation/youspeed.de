"""Offline speech metadata guardrails; no models, artwork, SDK or pytest needed.

Run: python3 tests/tsr/test_sign_speech_catalog.py -v
Contract fingerprints pin all non-label/non-speech fields to reviewed baseline
366132efd566da0e46833738f13e8ddf255bf199, including Swiss review gates.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
TSR = ROOT / "shared/tsr"
LANGUAGES = {"de", "en", "fr", "nl"}

CONTRACT_FINGERPRINTS = {'DE': 'b16e9d410c37d88149f411271b5681850b215c051437a7882d3edfcd396389a4',
 'FR': 'af47677bc545972d8f6b0827a386b45eea1f8ae03479b8358179942bdd4d791b',
 'NL': '5d34aa7123089b08faaa5ed84ef76de202fbe9d1f515be60d9af0fa35f61903a',
 'BE': 'c85e61eb87d6c9c2eb6ad6c5214c7f07d93ee4584ceb12ae8e237f685ed0b4a8',
 'CH': 'bcbc1ba0e597bd6f52826a49494ccba91643b0093356953917003763256c4d32'}
SCOPE_FINGERPRINTS = {'DE': '5d9206043722f369a688b43185c56e2f6604a3fe02985925cfc993cbd969dd9f',
 'FR': '0e1f182068db5e15b59ae4192ba5d35043aa096eb101a1cebe2ffffb5fb9897f',
 'NL': '1126f52dbbac24d3667fc8afb1140ca34e3f6727b931942411032485950b5840',
 'BE': 'a8ff5807ee15ed1b0e8812388b78b585743049f51dd988cc8e63cda24d590e09',
 'CH': '075db6d19133608d37f10b0cae8657db2ed72b794fe73d217536813275b1efc0'}
COUNTS = {'DE': 76, 'FR': 77, 'NL': 76, 'BE': 67, 'CH': 92}


def load(country):
    return json.loads((TSR / f"prolix-{country.lower()}-class-catalog-v1.json").read_text(encoding="utf-8"))


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SignSpeechCatalogTests(unittest.TestCase):
    def test_model_artwork_policies_and_existing_provenance_are_unchanged(self):
        for country, expected in CONTRACT_FINGERPRINTS.items():
            with self.subTest(country=country):
                catalog = copy.deepcopy(load(country))
                for sign in catalog["signs"]:
                    sign.pop("label", None)
                    sign.pop("speech", None)
                catalog["provenance"].pop("speech_review", None)
                self.assertEqual(digest(catalog), expected)

    def test_only_exact_reviewed_real_display_classes_have_speech(self):
        for country in COUNTS:
            with self.subTest(country=country):
                catalog = load(country)
                spoken = [s for s in catalog["signs"] if "speech" in s]
                scope = sorted((s["class_id"], s["sign_code"]) for s in spoken)
                self.assertEqual(len(spoken), COUNTS[country])
                self.assertEqual(digest(scope), SCOPE_FINGERPRINTS[country])
                review = catalog["provenance"]["speech_review"]
                recorded = sorted((s["class_id"], s["sign_code"]) for s in review["reviewed_signs"])
                self.assertEqual(scope, recorded)
                self.assertEqual(review["reviewed_at"], "2026-10-02")
                self.assertEqual(review["baseline_revision"], "366132efd566da0e46833738f13e8ddf255bf199")
                self.assertTrue(review["source_urls"])
                self.assertTrue(all(url.startswith("https://") for url in review["source_urls"]))
                self.assertTrue(review["scope"])
                for sign in spoken:
                    self.assertIn(sign["class_id"], catalog["class_labels"])
                    self.assertIs(sign["display_eligible"], True)
                    self.assertTrue(sign["image_path"])
                    self.assertTrue(sign["sign_code"])

    def test_reviewed_phrases_and_names_cover_four_languages_without_identifiers(self):
        technical = re.compile(r"_|(?:DE|FR|NL|BE|CH):|\b(?:[A-Z]{1,3}[0-9]+[a-z]?)\b|classifier:|hazard:")
        for country in COUNTS:
            for sign in load(country)["signs"]:
                if "speech" not in sign:
                    continue
                with self.subTest(country=country, sign=sign["class_id"]):
                    for field in ("speech", "label"):
                        self.assertEqual(set(sign[field]), LANGUAGES)
                        for text in sign[field].values():
                            self.assertIsInstance(text, str)
                            self.assertTrue(text.strip())
                            self.assertEqual(text, text.strip())
                            self.assertNotRegex(text, technical)
                            self.assertNotIn("—", text)
                    self.assertTrue(all(len(text) <= 100 for text in sign["speech"].values()))

    def test_every_eligible_model_class_is_spoken_or_has_an_explicit_omission(self):
        for country in COUNTS:
            catalog = load(country)
            eligible = {s["class_id"] for s in catalog["signs"]
                        if s["display_eligible"] and s["class_id"] in catalog["class_labels"]}
            spoken = {s["class_id"] for s in catalog["signs"] if "speech" in s}
            omissions = catalog["provenance"]["speech_review"]["omitted_display_classes"]
            with self.subTest(country=country):
                self.assertEqual(eligible, spoken | set(omissions))
                self.assertFalse(spoken & set(omissions))
                self.assertTrue(all(reason.strip() for reason in omissions.values()))

    def test_speed_and_structural_classes_do_not_gain_secondary_speech(self):
        structural = {"motorway:start", "motorway:end", "trunk:start", "trunk:end",
                      "city:start", "city:end", "no:end", "zone:20", "zone:30", "zone:30:end",
                      "zone:pedestrian", "zone:pedestrian:end", "zone:calm", "zone:calm:end",
                      "min_speed", "min_speed:end", "speed", "EB10", "EB20", "C107", "C207", "B31"}
        for country in COUNTS:
            for sign in load(country)["signs"]:
                if sign["class_id"] in structural or sign["class_id"].startswith(("maxspeed:", "B14-")):
                    self.assertNotIn("speech", sign, (country, sign["class_id"]))

    def test_requested_german_examples_and_foreign_equivalents(self):
        examples = {"hazard:road_works": "Achtung, Baustelle", "parking": "Parkplatz",
                    "no_parking": "Eingeschränktes Haltverbot", "no_stop": "Absolutes Haltverbot",
                    "no_overtaking": "Überholverbot"}
        signs = {s["class_id"]: s for s in load("DE")["signs"]}
        for class_id, phrase in examples.items():
            self.assertEqual(signs[class_id]["speech"]["de"], phrase)
        for country, class_ids in {"FR": ("AK5", "C1a", "B6a1", "B6d", "B3"),
                                   "NL": ("hazard:road_works", "parking", "no_parking", "no_overtaking"),
                                   "BE": ("hazard:road_works", "parking", "no_parking", "no_stop", "no_overtaking"),
                                   "CH": ("hazard:road_works", "parking", "no_parking", "no_stop", "no_overtaking")}.items():
            signs = {s["class_id"]: s for s in load(country)["signs"]}
            for class_id in class_ids:
                self.assertEqual(set(signs[class_id]["speech"]), LANGUAGES)

    def test_upstream_display_blocks_are_preserved_and_never_spoken(self):
        # New main blocks parameterized artwork. Metadata must not reinstate it,
        # even when a generic phrase was safe on the older display contract.
        numeric = {
            "DE": ("maxheight", "maxwidth", "maxweight", "maxlength", "maxaxleweight", "min_distance"),
            "FR": ("B13a", "B12", "B13", "B11", "B17", "A2a", "A2b"),
            "NL": ("maxaxleweight", "maxheight", "maxlength", "maxweight", "maxwidth", "speed"),
            "BE": ("maxheight", "maxlength", "maxweight"),
            "CH": ("maxaxleweight", "maxheight", "maxlength", "maxweight", "maxwidth", "min_distance",
                   "hazard:include:down", "hazard:incline:up", "hazard:horse", "no_exit:car", "zone:no_parking:end"),
        }
        for country, ids in numeric.items():
            signs = {s["class_id"]: s for s in load(country)["signs"]}
            for class_id in ids:
                with self.subTest(country=country, sign=class_id):
                    self.assertFalse(signs[class_id]["display_eligible"])
                    self.assertIsNone(signs[class_id]["image_path"])
                    self.assertNotIn("speech", signs[class_id])
        be = {s["class_id"]: s for s in load("BE")["signs"]}
        self.assertEqual(be["maxheight"]["sign_code"], "C29")
        self.assertEqual(be["maxheight"]["label"]["en"], "Height restriction")

    def test_national_meanings_and_new_main_display_classes_follow_exact_codes(self):
        signs = {s["class_id"]: s for s in load("FR")["signs"]}
        self.assertEqual(signs["B21d1"]["speech"]["de"], "Geradeaus oder rechts")
        self.assertEqual(signs["B21d2"]["speech"]["de"], "Geradeaus oder links")
        self.assertEqual(signs["C107"]["label"]["de"], "Kraftfahrstraße")
        self.assertEqual(signs["C207"]["label"]["de"], "Autobahn")
        for country, additions in {
            "NL": {"bus:end": ("F14", "Ende der Busspur"),
                   "hazard:intersection_left": ("B04", "Vorfahrt vor Einmündung von links"),
                   "hazard:intersection_right": ("B05", "Vorfahrt vor Einmündung von rechts"),
                   "hazard:left_turn": ("J03", "Achtung, Kurve links"),
                   "hazard:right_turn": ("J02", "Achtung, Kurve rechts"),
                   "hazard:zigzag_left": ("J05", "Achtung, Doppelkurve, zuerst links"),
                   "no_overtaking:hgv:end": ("F04", "Ende des Überholverbots für Lastkraftwagen"),
                   "noexit": ("L08", "Sackgasse"),
                   "priority:start": ("B01", "Vorfahrtstraße")},
            "BE": {"hazard:left_turn": ("A1a", "Achtung, Kurve links"),
                   "hazard:right_turn": ("A1b", "Achtung, Kurve rechts")},
        }.items():
            signs = {s["class_id"]: s for s in load(country)["signs"]}
            for class_id, (code, phrase) in additions.items():
                with self.subTest(country=country, sign=class_id):
                    self.assertEqual(signs[class_id]["sign_code"], code)
                    self.assertEqual(signs[class_id]["speech"]["de"], phrase)
                    self.assertEqual(set(signs[class_id]["speech"]), LANGUAGES)

    def test_conflicting_or_unverified_classes_remain_silent(self):
        omissions = {"FR": ("A9", "B9i"), "NL": ("parking:car",),
                     "BE": ("arrow_left_down", "arrow_left", "arrow_right_down", "arrow_right", "arrow_turn_left",
                            "maxheight", "no_hgv", "pedestrian_bicycle:start", "pedestrian:start"),
                     "CH": ("hazard:horse", "no_exit:car", "zone:no_parking:end")}
        for country, class_ids in omissions.items():
            signs = {s["class_id"]: s for s in load(country)["signs"]}
            for class_id in class_ids:
                self.assertNotIn("speech", signs[class_id], (country, class_id))
        be = {s["class_id"]: s for s in load("BE")["signs"]}
        self.assertEqual(be["maxheight"]["label"]["en"], "Height restriction")
        self.assertEqual(be["no_hgv"]["label"]["en"], "No buses")
        self.assertEqual(be["hazard:zigzag"]["speech"], be["hazard:zigzag:left"]["speech"])
        self.assertNotIn("right", be["hazard:zigzag"]["speech"]["en"].lower())
        self.assertNotIn("left", be["hazard:zigzag"]["speech"]["en"].lower())


if __name__ == "__main__":
    unittest.main()

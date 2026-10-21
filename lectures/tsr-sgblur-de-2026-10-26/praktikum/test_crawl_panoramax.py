"""Lokale HTTP-/Rasterproben; keine Netzwerkzugriffe und kein Training."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from PIL import Image

import crawl_panoramax as crawler


BASE = "https://example.test"
SEQUENCE = "10000000-0000-4000-8000-000000000001"
PICTURE = "20000000-0000-4000-8000-000000000001"
SIGN = "30000000-0000-4000-8000-000000000001"
PLATE = "30000000-0000-4000-8000-000000000002"
FACE = "30000000-0000-4000-8000-000000000003"
ITEM_URL = f"{BASE}/api/collections/{SEQUENCE}/items/{PICTURE}"


def feature(picture=PICTURE, code="DE:310"):
    return {
        "type": "Feature", "id": picture, "collection": SEQUENCE,
        "properties": {"license": "CC-BY-SA-4.0", "geovisio:producer": "Kurs-Fixture",
                       "geovisio:status": "ready", "geovisio:visibility": "anyone",
                       "pers:interior_orientation": {"sensor_array_dimensions": [12, 8],
                                                      "field_of_view": 69},
                       "annotations": [
                           {"id": SIGN, "shape": [2, 1, 6, 5], "semantics": [
                               {"key": "osm|traffic_sign", "value": code},
                               {"key": "osm|name", "value": "Dobel"}]},
                           {"id": PLATE, "detector_class": "plate", "shape": [7, 1, 10, 3],
                            "semantics": []},
                           {"id": FACE, "class": "face", "shape": [1, 5, 3, 7],
                            "semantics": []}]},
        "assets": {"hd": {"href": f"/hd/{picture}.jpg"}},
        "links": [{"rel": "self", "href": f"/api/collections/{SEQUENCE}/items/{picture}"},
                  # A feature's next image is deliberately not an API page.
                  {"rel": "next", "href": "https://must-not-fetch.invalid/next-picture"}],
    }


def raster(size=(12, 8), orientation=6):
    image = Image.new("RGB", size)
    for y in range(size[1]):
        for x in range(size[0]):
            image.putpixel((x, y), (x * 11, y * 17, 30))
    exif = Image.Exif()
    exif[274] = orientation
    target = io.BytesIO()
    image.save(target, "PNG", exif=exif)
    return target.getvalue()


class FakeClient:
    def __init__(self, documents=None, images=None):
        self.documents, self.images = documents or {}, images or {}
        self.json_calls, self.image_calls = [], []

    def json(self, url):
        self.json_calls.append(url)
        value = self.documents[url]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def get(self, url, max_bytes):
        self.image_calls.append(url)
        value = self.images[url]
        if isinstance(value, Exception):
            raise value
        assert len(value) <= max_bytes
        return value


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.args = crawler.parser().parse_args([
            "--instance", BASE, "--item-url", ITEM_URL,
            "--output", str(self.root / "collection")])

    def tearDown(self):
        self.temporary.cleanup()

    def run_item(self, item=None, image=None):
        item = item or feature()
        client = FakeClient({ITEM_URL: item}, {BASE + item["assets"]["hd"]["href"]: image or raster()})
        return crawler.crawl(self.args, client), client

    def test_whole_bundle_three_classes_sign_only_crop_and_lock(self):
        manifest, client = self.run_item()
        self.assertEqual(len(manifest["items"]), 1)
        self.assertEqual(len(manifest["crops"]), 1)
        self.assertEqual(len(manifest["class_folders"]), 136)
        self.assertEqual(manifest["class_folders"]["city__start"], "city:start")
        item, crop = manifest["items"][0], manifest["crops"][0]
        self.assertEqual(item["group_id"], "sequence-" + SEQUENCE)
        self.assertEqual(crop["suggested_label"], "city:start")
        self.assertEqual(crop["sample_id"], f"p{PICTURE}_a{SIGN}")
        self.assertFalse(crop["eligible_for_training"])
        bundle = self.args.output / item["bundle_path"]
        self.assertEqual({p.name for p in bundle.iterdir()}, {"image.png", "labels.txt", "metadata.json"})
        self.assertEqual([line.split()[0] for line in (bundle / "labels.txt").read_text().splitlines()], ["0", "1", "2"])
        for filename, key in [("image.png", "image_sha256"), ("labels.txt", "labels_sha256"),
                              ("metadata.json", "metadata_sha256")]:
            self.assertEqual(crawler.digest((bundle / filename).read_bytes()), item[key])
        metadata = json.loads((bundle / "metadata.json").read_text())
        self.assertEqual(metadata["original_item"], feature())
        self.assertFalse(metadata["eligible_for_training"])
        with Image.open(bundle / "image.png") as image:
            self.assertEqual(image.size, (12, 8))
            self.assertEqual(image.mode, "RGB")
            self.assertFalse(image.getexif())
            self.assertEqual(image.getpixel((2, 1)), (22, 17, 30))
        with Image.open(self.args.output / crop["crop_path"]) as image:
            self.assertEqual(image.size, (4, 4))
            self.assertEqual(image.getpixel((0, 0)), (22, 17, 30))
        self.assertEqual(len(client.image_calls), 1)
        unlocked = {key: value for key, value in manifest.items() if key != "lock_sha256"}
        self.assertEqual(crawler.digest(crawler.canonical_bytes(unlocked)), manifest["lock_sha256"])
        self.assertTrue(manifest["crawl"]["explicit_selection"])
        self.assertFalse(manifest["crawl"]["complete_inventory"])
        self.assertTrue((self.args.output / "rejected/detector").is_dir())

    def test_city_end_and_other_classes_are_only_suggestions(self):
        for code, expected in [("DE:311", "city:end"), ("DE:101", None)]:
            with self.subTest(code=code):
                self.args.output = self.root / code.replace(":", "_")
                manifest, _ = self.run_item(feature(code=code))
                self.assertEqual(manifest["crops"][0]["suggested_label"], expected)

    def test_empty_and_unknown_only_annotations_do_not_download_or_use_image_budget(self):
        for annotation_list in [[], [{"id": SIGN, "shape": [2, 1, 6, 5], "semantics": [
                {"key": "unverified_object", "value": "car"}]}]]:
            with self.subTest(annotations=annotation_list):
                self.args.output = self.root / ("empty" if not annotation_list else "unknown")
                item = feature()
                item["properties"]["annotations"] = annotation_list
                manifest, client = self.run_item(item)
                self.assertEqual(client.image_calls, [])
                self.assertEqual(manifest["crawl"]["image_attempts"], 0)
                self.assertEqual(manifest["items"], [])
                self.assertIn("Keine verwendbaren", manifest["crawl"]["skipped"][0]["reason"])
                self.assertFalse(manifest["crawl"]["complete_inventory"])

    def test_unknown_annotation_is_preserved_but_not_guessed(self):
        item = feature()
        unknown = "30000000-0000-4000-8000-000000000004"
        item["properties"]["annotations"].append({"id": unknown, "shape": [1, 1, 2, 2], "semantics": []})
        manifest, _ = self.run_item(item)
        self.assertEqual(manifest["items"][0]["unknown_annotation_ids"], [unknown])
        self.assertEqual(len(manifest["items"][0]["annotations"]), 3)

    def test_bad_box_prevents_entire_bundle_and_download(self):
        item = feature()
        item["properties"]["annotations"][1]["shape"] = [0, 0, 99, 2]
        manifest, client = self.run_item(item)
        self.assertEqual(manifest["items"], [])
        self.assertEqual(client.image_calls, [])
        self.assertEqual(list((self.args.output / "inbox/detector").iterdir()), [])

    def test_decoded_dimension_mismatch_is_not_silently_scaled(self):
        manifest, client = self.run_item(image=raster((10, 8)))
        self.assertEqual(len(client.image_calls), 1)
        self.assertEqual(manifest["crawl"]["image_attempts"], 1)
        self.assertEqual(manifest["items"], [])
        self.assertIn("Abmessungen", manifest["crawl"]["skipped"][0]["reason"])

    def test_360_image_is_skipped_before_hd_download(self):
        item = feature()
        item["properties"]["pers:interior_orientation"]["field_of_view"] = 360
        manifest, client = self.run_item(item)
        self.assertFalse(client.image_calls)
        self.assertIn("360", manifest["crawl"]["skipped"][0]["reason"])

    def test_new_output_required(self):
        self.args.output.mkdir()
        with self.assertRaisesRegex(crawler.CrawlError, "existiert"):
            crawler.crawl(self.args, FakeClient())

    def test_top_level_pagination_only_and_inventory_completion(self):
        self.args.item_url = []
        collections = BASE + "/api/collections?limit=100"
        collections2 = BASE + "/api/collections?page=2"
        items = f"{BASE}/api/collections/{SEQUENCE}/items?limit=100"
        items2 = f"{BASE}/api/collections/{SEQUENCE}/items?page=2"
        second = "20000000-0000-4000-8000-000000000002"
        second_url = f"{BASE}/api/collections/{SEQUENCE}/items/{second}"
        client = FakeClient({collections: {"collections": [], "links": [{"rel": "next", "href": collections2}]},
                             collections2: {"collections": [{"id": SEQUENCE}]},
                             items: {"features": [feature()], "links": [{"rel": "next", "href": items2}]},
                             items2: {"features": [feature(second)]}, ITEM_URL: feature(), second_url: feature(second)},
                            {BASE + f"/hd/{p}.jpg": raster() for p in [PICTURE, second]})
        manifest = crawler.crawl(self.args, client)
        self.assertEqual(len(manifest["items"]), 2)
        self.assertEqual(manifest["crawl"]["pages_fetched"], 4)
        self.assertTrue(manifest["crawl"]["complete_inventory"])
        self.assertFalse(any("must-not-fetch" in url for url in client.json_calls))

    def test_image_limit_stops_before_next_detail_or_page(self):
        self.args.item_url = []
        self.args.collection = [SEQUENCE]
        self.args.max_images = 1
        items = f"{BASE}/api/collections/{SEQUENCE}/items?limit=100"
        client = FakeClient({items: {"features": [feature(), feature("20000000-0000-4000-8000-000000000002")],
                                    "links": [{"rel": "next", "href": "?page=2"}]}, ITEM_URL: feature()},
                            {BASE + f"/hd/{PICTURE}.jpg": raster()})
        manifest = crawler.crawl(self.args, client)
        self.assertEqual(client.json_calls, [items, ITEM_URL])
        self.assertEqual(manifest["crawl"]["image_attempts"], 1)
        self.assertIn("max_images", manifest["crawl"]["limits_reached"])

    def test_collections_are_consumed_lazily_before_next_inventory_page(self):
        self.args.item_url = []
        self.args.max_pages = 2
        collections = BASE + "/api/collections?limit=100"
        collections2 = BASE + "/api/collections?page=2"
        items = f"{BASE}/api/collections/{SEQUENCE}/items?limit=100"
        client = FakeClient({collections: {"collections": [{"id": SEQUENCE}],
                                          "links": [{"rel": "next", "href": collections2}]},
                             items: {"features": [feature()]}, ITEM_URL: feature()},
                            {BASE + f"/hd/{PICTURE}.jpg": raster()})
        manifest = crawler.crawl(self.args, client)
        self.assertEqual(client.json_calls, [collections, items, ITEM_URL])
        self.assertEqual(len(manifest["items"]), 1)
        self.assertIn("max_pages", manifest["crawl"]["limits_reached"])

    def test_unannotated_first_item_does_not_consume_budget_for_annotated_second(self):
        self.args.item_url = []
        self.args.collection = [SEQUENCE]
        self.args.max_images = 1
        items = f"{BASE}/api/collections/{SEQUENCE}/items?limit=100"
        empty = feature()
        empty["properties"]["annotations"] = []
        second = "20000000-0000-4000-8000-000000000002"
        second_url = f"{BASE}/api/collections/{SEQUENCE}/items/{second}"
        client = FakeClient({items: {"features": [empty, feature(second)]},
                             ITEM_URL: empty, second_url: feature(second)},
                            {BASE + f"/hd/{second}.jpg": raster()})
        manifest = crawler.crawl(self.args, client)
        self.assertEqual([item["picture_id"] for item in manifest["items"]], [second])
        self.assertEqual(manifest["crawl"]["image_attempts"], 1)
        self.assertEqual(len(client.image_calls), 1)

    def test_page_and_item_limits_are_reported(self):
        for bound in ["max_pages", "max_items"]:
            with self.subTest(bound=bound):
                self.args.output = self.root / bound
                self.args.item_url = []
                self.args.collection = [SEQUENCE]
                setattr(self.args, bound, 1)
                items = f"{BASE}/api/collections/{SEQUENCE}/items?limit=100"
                items2 = f"{BASE}/api/collections/{SEQUENCE}/items?page=2"
                second = "20000000-0000-4000-8000-000000000002"
                client = FakeClient({items: {"features": [feature()], "links": [{"rel": "next", "href": items2}]},
                                     items2: {"features": [feature(second)]}, ITEM_URL: feature()},
                                    {BASE + f"/hd/{PICTURE}.jpg": raster()})
                manifest = crawler.crawl(self.args, client)
                self.assertEqual(len(manifest["items"]), 1)
                self.assertIn(bound, manifest["crawl"]["limits_reached"])
                self.assertFalse(manifest["crawl"]["complete_inventory"])
                setattr(self.args, bound, 100)

    def test_failed_metadata_leaves_locked_incomplete_manifest(self):
        client = FakeClient({ITEM_URL: crawler.CrawlError("fixture metadata failure")})
        manifest = crawler.crawl(self.args, client)
        self.assertFalse(manifest["crawl"]["complete_inventory"])
        self.assertIn("fixture metadata failure", manifest["crawl"]["errors"][0]["reason"])
        self.assertEqual(json.loads((self.args.output / "manifest.json").read_text()), manifest)


class GeometryAndTransportTests(unittest.TestCase):
    def test_finite_bounded_list_and_polygon_boxes(self):
        self.assertEqual(crawler.box_xyxy({"type": "Polygon", "coordinates": [
            [[2, 1], [6, 1], [6, 5], [2, 5], [2, 1]]]}, 12, 8), [2, 1, 6, 5])
        for shape in [[0, 0, float("nan"), 2], [0, 0, float("inf"), 2],
                      [False, 0, 2, 2], [-1, 0, 2, 2], [0, 0, 0, 2], [0, 0, 13, 2]]:
            with self.subTest(shape=shape), self.assertRaises(crawler.CrawlError):
                crawler.box_xyxy(shape, 12, 8)

    def test_urls_are_https_same_origin_without_credentials(self):
        self.assertEqual(crawler.safe_url("/api/items", BASE), BASE + "/api/items")
        for url in ["http://example.test/x", "file:///tmp/private", "https://other.test/x",
                    "https://user:secret@example.test/x", "https://example.test:444/x", "/x#fragment"]:
            with self.subTest(url=url), self.assertRaises(crawler.CrawlError):
                crawler.safe_url(url, BASE)
        with self.assertRaises(crawler.CrawlError):
            crawler.SameOriginRedirect(BASE).redirect_request(Request(BASE), None, 302, "Found", {},
                                                            "https://other.test/secret")

    def test_duplicate_annotation_ids_and_conflicting_classes_fail(self):
        item = feature()
        item["properties"]["annotations"].append(copy.deepcopy(item["properties"]["annotations"][0]))
        with self.assertRaisesRegex(crawler.CrawlError, "Doppelte"):
            crawler.annotation_records(item, 12, 8)
        with self.assertRaisesRegex(crawler.CrawlError, "Widersprüchliche"):
            crawler.detector_class({"class": "face", "semantics": [{"key": "osm|traffic_sign", "value": "DE:310"}]})

    def test_get_retry_and_byte_limit(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):
                return BASE + "/probe"
        class Opener:
            def __init__(self):
                self.requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                if len(self.requests) == 1:
                    raise HTTPError(request.full_url, 429, "slow", {"Retry-After": "0"}, io.BytesIO())
                return Response(b"hello")
        opener, delays = Opener(), []
        client = crawler.HttpClient(BASE, retries=1, opener=opener, sleep=delays.append)
        self.assertEqual(client.get(BASE + "/probe", 5), b"hello")
        self.assertEqual(delays, [0])
        self.assertEqual([request.method for request in opener.requests], ["GET", "GET"])
        with self.assertRaisesRegex(crawler.CrawlError, "Byte-Grenze"):
            client.get(BASE + "/probe", 4)

    def test_transport_checks_final_response_origin(self):
        class Response(io.BytesIO):
            headers = {}
            def geturl(self):
                return "https://other.test/not-allowed"
        class Opener:
            def open(self, request, timeout):
                return Response(b"{}")
        with self.assertRaises(crawler.CrawlError):
            crawler.HttpClient(BASE, opener=Opener()).get(BASE, 100)

    def test_nonfinite_json_and_nonobject_documents_are_rejected(self):
        class Client(crawler.HttpClient):
            def get(self, url, max_bytes):
                return self.payload
        client = Client(BASE)
        for payload in [b'{"coordinates":NaN}', b'{"coordinates":Infinity}', b'[]']:
            with self.subTest(payload=payload), self.assertRaises(crawler.CrawlError):
                client.payload = payload
                client.json(BASE)


if __name__ == "__main__":
    unittest.main()

"""Private place review file validation and photo transport."""

from http.client import HTTPConnection
import io
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from inspector import place_sign_review as review
from inspector import server


class PlaceReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / "review.json"
        self.media = Path(directory.name) / "media"
        self.media.mkdir(mode=0o700)
        self.picture = str(uuid4())
        self.annotation = str(uuid4())
        self.observation = {
            "source_id": review.SOURCE_ID,
            "image_id": self.picture,
            "annotation_id": self.annotation,
            "image_width": 80,
            "image_height": 60,
            "box_xyxy": [11, 17, 32, 47],
            "item_visibility": "anyone",
            "picture_visibility": "anyone",
            "sequence_visibility": "anyone",
            "photo_url": "https://untrusted.invalid/photo",
        }
        self.document = {
            "schema_version": 1,
            "place": {},
            "summary": {},
            "default_group_id": "review-group",
            "groups": [
                {
                    "id": "review-group",
                    "sign_code": "DE:222",
                    "proposal": None,
                    "observations": [self.observation],
                }
            ],
        }
        self.save()
        self.store = review.PlaceSignReviewStore(self.file, opener=None)

    def save(self):
        self.file.write_text(json.dumps(self.document))
        self.file.chmod(0o600)

    def current_item(self, href=None):
        return {
            "type": "Feature",
            "id": self.picture,
            "properties": {
                "geovisio:visibility": "anyone",
                "geovisio:status": "ready",
                "pers:interior_orientation": {"sensor_array_dimensions": [80, 60]},
                "annotations": [
                    {
                        "id": self.annotation,
                        "shape": {
                            "type": "Polygon",
                            "coordinates": [
                                [[11, 17], [32, 17], [32, 47], [11, 47], [11, 17]]
                            ],
                        },
                        "semantics": [
                            {"key": "osm|traffic_sign", "value": "yes"},
                            {"key": "osm|traffic_sign", "value": "DE:222"},
                        ],
                    }
                ],
            },
            "assets": {
                "hd": {
                    "href": href or review.asset_path(self.picture),
                    "type": "image/jpeg",
                }
            },
        }

    def attach_follow_on(self):
        self.observation.update(
            sequence_id=str(uuid4()),
            sequence_rank=48,
            captured_at="2026-11-10T11:00:00Z",
        )
        next_observation = {
            **self.observation,
            "image_id": str(uuid4()),
            "annotation_id": str(uuid4()),
            "anchor_image_id": self.picture,
            "sequence_rank": 49,
            "frame_offset": 1,
            "captured_at": "2026-11-10T11:00:03Z",
        }
        self.document["groups"][0]["follow_on_observations"] = [next_observation]
        self.save()
        return next_observation

    def test_follow_on_photos_use_the_same_allowlisted_routes(self):
        follow_on = self.attach_follow_on()
        shown = self.store.get()["groups"][0]["follow_on_observations"][0]
        image_id = follow_on["annotation_id"]
        for variant in ("photo", "crop"):
            self.assertEqual(
                shown[f"{variant}_url"], f"{review.ROUTE}/images/{image_id}/{variant}"
            )
        with patch.object(self.store, "public_photo", return_value=b"source") as origin:
            with patch.object(review, "render", return_value=(b"crop", "image/png")):
                self.assertEqual(
                    self.store.image(image_id, "crop"), (b"crop", "image/png")
                )
            self.assertEqual(origin.call_args.args[0].picture, follow_on["image_id"])

    def test_follow_on_requires_a_same_group_ordered_sequence_rank(self):
        follow_on = self.attach_follow_on()
        original = dict(follow_on)
        for field, value in (
            ("anchor_image_id", str(uuid4())),
            ("image_id", self.picture),
            ("sequence_id", str(uuid4())),
            ("sequence_rank", 50),
            ("frame_offset", False),
            ("captured_at", "2026-11-10T10:59:59Z"),
        ):
            with self.subTest(field=field):
                follow_on.update(original)
                follow_on[field] = value
                self.save()
                with self.assertRaises(review.PlaceSignReviewError):
                    self.store.get()

    def test_snapshot_replaces_untrusted_links_and_fails_closed(self):
        shown = self.store.get()["groups"][0]["observations"][0]
        self.assertEqual(
            shown["photo_url"], f"{review.ROUTE}/images/{self.annotation}/photo"
        )
        self.assertEqual(
            shown["crop_url"], f"{review.ROUTE}/images/{self.annotation}/crop"
        )
        self.file.chmod(0o644)
        with self.assertRaises(review.PlaceSignReviewError):
            self.store.get()
        self.file.chmod(0o600)
        alias = self.file.with_name("alias.json")
        alias.symlink_to(self.file)
        with self.assertRaises(review.PlaceSignReviewError):
            review.load_snapshot(alias, False)

    def test_unknown_or_restricted_reference_never_requests_origin(self):
        self.observation["sequence_visibility"] = "owner-only"
        self.save()
        self.assertIsNone(self.store.get()["groups"][0]["observations"][0]["photo_url"])
        with patch.object(self.store, "upstream") as upstream:
            for annotation in (self.annotation, str(uuid4())):
                with self.assertRaises(review.PlaceSignReviewError) as error:
                    self.store.image(annotation, "photo")
                self.assertEqual(error.exception.status, 404)
            upstream.assert_not_called()

    def test_public_picture_binds_annotation_and_asset_before_fetch(self):
        item = review.reference(self.observation, "DE:222")
        current = self.current_item()
        with patch.object(
            self.store, "upstream", side_effect=[json.dumps(current).encode(), b"jpeg"]
        ) as upstream:
            self.assertEqual(self.store.public_photo(item), b"jpeg")
            self.assertEqual(
                upstream.call_args_list[0].args[0], f"/api/pictures/{self.picture}"
            )
            self.assertEqual(
                upstream.call_args_list[1].args[0], review.asset_path(self.picture)
            )
        altered = (
            self.current_item(
                "https://untrusted.invalid" + review.asset_path(self.picture)
            ),
            self.current_item(),
            self.current_item(),
        )
        altered[1]["properties"]["annotations"][0]["semantics"][1]["value"] = "DE:205"
        altered[2]["properties"]["geovisio:visibility"] = "owner-only"
        for payload in altered:
            with patch.object(
                self.store, "upstream", return_value=json.dumps(payload).encode()
            ) as upstream:
                with self.assertRaises(review.PlaceSignReviewError):
                    self.store.public_photo(item)
                self.assertEqual(upstream.call_count, 1)

    def test_local_media_preserves_photo_geometry_and_crops_native_pixels(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is optional for Inspector")
        photo = self.media / (self.picture + ".jpg")
        image = Image.new("RGB", (80, 60), "red")
        image.save(photo, "JPEG")
        photo.chmod(0o600)
        store = review.PlaceSignReviewStore(
            self.file, opener=None, media_dir=self.media
        )
        for variant, size, mime in (
            ("photo", (80, 60), "image/jpeg"),
            ("crop", (21, 30), "image/png"),
        ):
            data, actual_mime = store.image(self.annotation, variant)
            with Image.open(io.BytesIO(data)) as rendered:
                self.assertEqual(rendered.size, size)
                self.assertEqual(actual_mime, mime)
                self.assertFalse(rendered.getexif())
        photo.chmod(0o644)
        with self.assertRaises(review.PlaceSignReviewError):
            store.image(self.annotation, "photo")

    def test_route_is_opt_in_loopback_and_same_origin_without_cache(self):
        with self.assertRaises(SystemExit):
            server.arguments(
                ["--bind", "0.0.0.0", "--place-sign-review-file", str(self.file)]
            )
        http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.InspectorHandler)
        host = f"127.0.0.1:{http.server_port}"
        http.allowed_hosts = {host, f"volz-db:{http.server_port}"}
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)

        def request(path=review.ROUTE, *, method="GET", **headers):
            connection = HTTPConnection("127.0.0.1", http.server_port, timeout=3)
            try:
                connection.request(method, path, headers=headers)
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        self.assertEqual(request()[0], 404)
        http.place_sign_review = self.store
        status, headers, data = request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(json.loads(data)["default_group_id"], "review-group")
        self.assertEqual(request(Origin="https://untrusted.invalid")[0], 403)
        self.assertEqual(request(Host=f"volz-db:{http.server_port}")[0], 404)
        self.assertEqual(request(review.ROUTE + "?path=other")[0], 400)
        self.assertEqual(request(review.ROUTE + "/images/other/photo")[0], 404)
        self.assertEqual(request(method="HEAD")[2], b"")


if __name__ == "__main__":
    unittest.main()

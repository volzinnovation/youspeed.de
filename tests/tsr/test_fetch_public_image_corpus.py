"""Public corpus fetch safety/provenance tests; no external network requests."""
import hashlib
import io
import json

import pytest

from scripts.tsr.applicability.fetch_public_image_corpus import fetch, public_url


class Response(io.BytesIO):
    def geturl(self):
        return "https://panoramax.openstreetmap.fr/api/pictures/test/hd.jpg"


class Opener:
    def open(self, request, timeout):
        return Response(b"pinned-image-bytes")


def manifest(tmp_path, *, kind="public_panoramax", path="cache/image.jpg", sha=None):
    data = {"frames": [{"frame_id": "public-frame", "image_path": path,
                        "image_sha256": sha or hashlib.sha256(b"pinned-image-bytes").hexdigest(),
                        "source": {"kind": kind,
                                   "image_url": "https://panoramax.openstreetmap.fr/api/pictures/test/hd.jpg"}}]}
    target = tmp_path / "corpus.json"
    target.write_text(json.dumps(data))
    return target


def test_explicit_fetch_pins_bytes_and_existing_cache(tmp_path):
    corpus = manifest(tmp_path)
    assert fetch([corpus], image_root=tmp_path, opener=Opener())[0]["status"] == "downloaded_and_verified"
    assert fetch([corpus], image_root=tmp_path, opener=Opener())[0]["status"] == "verified_cached"


def test_private_original_is_reported_without_network(tmp_path):
    corpus = manifest(tmp_path, kind="authorized_local_panoramax_still")
    assert fetch([corpus], image_root=tmp_path, opener=object())[0]["status"] == "private_original_unavailable"


def test_user_supplied_youspeed_panoramax_host_is_supported_without_broadening_subdomains():
    url = "https://panoramax.youspeed.de/permanent/f8/ea/80/f9/c525-44fb-a6d8-7af479f7fdd8.jpg"
    assert public_url(url) == url
    for unapproved in ("https://youspeed.de/a", "https://other.panoramax.youspeed.de/a",
                       "https://panoramax.youspeed.de.example.com/a"):
        with pytest.raises(ValueError, match="HTTPS"):
            public_url(unapproved)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://panoramax.openstreetmap.fr/a",
                                "https://example.com/a", "https://user:pass@panoramax.openstreetmap.fr/a"])
def test_unapproved_urls_rejected(url):
    with pytest.raises(ValueError, match="HTTPS"):
        public_url(url)


def test_hash_change_and_path_escape_rejected(tmp_path):
    with pytest.raises(ValueError, match="bytes changed"):
        fetch([manifest(tmp_path, sha="a" * 64)], image_root=tmp_path, opener=Opener())
    assert not (tmp_path / "cache/image.jpg").exists()
    with pytest.raises(ValueError, match="within"):
        fetch([manifest(tmp_path, path="../image.jpg")], image_root=tmp_path, opener=Opener())


def test_corrupt_existing_cache_is_never_replaced(tmp_path):
    corpus = manifest(tmp_path)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/image.jpg").write_bytes(b"private-existing-data")
    with pytest.raises(ValueError, match="refusing overwrite"):
        fetch([corpus], image_root=tmp_path, opener=Opener())
    assert (tmp_path / "cache/image.jpg").read_bytes() == b"private-existing-data"

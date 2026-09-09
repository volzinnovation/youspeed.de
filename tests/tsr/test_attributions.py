"""Check that bundled attribution stays complete as sign assets change."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ATTR = ROOT / "shared/attributions"
SIGNS = ROOT / "shared/tsr/sign-pictograms"


def test_generated_mobile_attributions_are_current():
    subprocess.run([sys.executable, str(ROOT / "scripts/attributions/generate.py"), "--check"], check=True)


def test_every_sign_has_its_exact_author_source_and_modification_credit():
    catalog = json.loads((ATTR / "sources.json").read_text())
    entries = {entry["id"]: entry for entry in catalog["entries"]}
    assert len(entries) == len(catalog["entries"])
    artworks = json.loads((SIGNS / "manifest.json").read_text())["artworks"]
    assert {key for key in entries if key.startswith("sign-DE:")} == {"sign-" + art["sign_code"] for art in artworks}
    for art in artworks:
        entry = entries["sign-" + art["sign_code"]]
        assert entry["source_url"] == art["source_page_permanent_url"]
        assert art["artist"] in entry["attribution"]
        assert art["source_credit"] in entry["attribution"]
        assert entry["changes"] == art["changes"]
        assert entry["license_url"] == art["license_basis_url"]


def test_offline_notices_retain_original_licence_texts():
    notices = (ATTR / "THIRD_PARTY_NOTICES.txt").read_text()
    for path in [ROOT / "LICENSE", SIGNS / "THIRD_PARTY_NOTICES.txt", SIGNS / "sources/PROLIX_LICENSE.txt", *sorted((ATTR / "licenses").glob("*.txt"))]:
        assert path.read_text() in notices, path
    provenance = json.loads((SIGNS / "sources/prolix-de-class-map-provenance.json").read_text())
    assert hashlib.sha256((SIGNS / "sources/PROLIX_LICENSE.txt").read_bytes()).hexdigest() == provenance["prolix_license_sha256"]
    assert provenance["mapping_source"]["source_url"] in notices
    assert "Copyright (c) 2016 usr_share" in notices
    assert "Copyright (c) 2009-2016 Peter Wiegel" in notices


def test_reference_photographs_are_not_production_image_assets():
    photo = ROOT / "android/app/src/androidTest/assets/tsr-city310-bernbach.jpg"
    assert photo.is_file()
    assert not (ROOT / "android/app/src/main/assets" / photo.name).exists()
    sources = json.loads((ATTR / "sources.json").read_text())["entries"]
    credit = next(entry for entry in sources if entry["id"] == "photo-city310")
    assert "admin" in credit["attribution"]
    assert credit["license"] == "CC-BY-SA-4.0"
    assert "not in the production app" in credit["changes"]

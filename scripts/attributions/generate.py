#!/usr/bin/env python3
"""Generate the offline mobile attribution catalog from reviewed local inputs."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "shared/attributions"
SIGNS = ROOT / "shared/tsr/sign-pictograms"
APACHE = "https://www.apache.org/licenses/LICENSE-2.0"
REPO = "https://github.com/volzinnovation/youspeed.de"


def generate():
    entries = json.loads((OUT / "additional-sources.json").read_text())
    seen_components = set()
    for component in json.loads((OUT / "android-components.json").read_text())["components"]:
        coord = component["coordinate"]
        if coord in seen_components:
            continue
        seen_components.add(coord)
        group, artifact, version = coord.split(":")
        if group.startswith("androidx."):
            author, source = "The Android Open Source Project contributors", "https://android.googlesource.com/platform/frameworks/support/"
        elif group == "net.java.dev.jna":
            author, source = "Timothy Wall and JNA contributors", "https://github.com/java-native-access/jna/tree/5.18.1"
        elif group == "com.alphacephei":
            author, source = "Alpha Cephei Inc. and Vosk contributors", "https://github.com/alphacep/vosk-api"
        elif group == "com.google.ai.edge.litert":
            author, source = "Google and TensorFlow/LiteRT contributors", "https://github.com/google-ai-edge/LiteRT"
        elif group == "com.google.auto.value":
            author, source = "Google and AutoValue contributors", "https://github.com/google/auto/tree/auto-value-1.6.3"
        elif group == "com.google.guava":
            author, source = "Google and Guava contributors", "https://github.com/google/guava"
        elif group == "org.jetbrains.kotlin":
            author, source = "JetBrains s.r.o. and Kotlin contributors", "https://github.com/JetBrains/kotlin"
        elif group == "org.jetbrains.kotlinx":
            author = "JetBrains s.r.o. and respective contributors"
            source = "https://github.com/Kotlin/kotlinx." + ("coroutines" if "coroutines" in artifact else "serialization")
        elif group == "org.jetbrains":
            author, source = "JetBrains s.r.o. and Java annotations contributors", "https://github.com/JetBrains/java-annotations"
        else:
            raise ValueError(f"Unreviewed component: {coord}")
        entries.append(dict(id="android-" + coord, title="Android · " + coord,
                            category="software", attribution=author,
                            license="Apache-2.0" + (" (chosen from Apache-2.0 OR LGPL-2.1-or-later)" if group == "net.java.dev.jna" else ""),
                            source_url=source, license_url=APACHE,
                            changes="Bundled dependency; Android build processing and shrinking may apply. Upstream notices are retained in the offline licence text."))
    for path in sorted((ROOT / "iphone/SpeedConsumerApp/Rules").glob("*.json")):
        rules = json.loads(path.read_text())
        source = rules.get("source_url", rules.get("quelle_url"))
        entries.append(dict(id="rules-" + path.stem, title="Traffic-rule reference · " + rules.get("country_name", rules.get("land_name")),
                            category="reference", attribution=source.split("/")[2],
                            license="Reference citation; original website rights remain with its publisher",
                            source_url=source, license_url=source,
                            changes="Reference for the app's rule data and summaries. Source checked: " + rules.get("source_checked_at", rules.get("quelle_geprueft_am", "not recorded")) + ". The original website is not bundled."))
    manifest = json.loads((SIGNS / "manifest.json").read_text())
    for sign in manifest["artworks"]:
        entries.append(dict(id="sign-" + sign["sign_code"], title=sign["sign_code"] + " · " + sign["commons_title"].removeprefix("File:"),
                            category="sign", attribution=sign["artist"] + "; " + sign["source_credit"],
                            license=sign["license"] + " · " + sign["license_basis"],
                            source_url=sign["source_page_permanent_url"], license_url=sign["license_basis_url"], changes=sign["changes"]))
    assert len({e["id"] for e in entries}) == len(entries)
    required = {"id", "title", "category", "attribution", "license", "source_url", "license_url", "changes"}
    for entry in entries:
        assert entry.keys() == required and all(isinstance(v, str) and v.strip() for v in entry.values()), entry
        assert entry["source_url"].startswith("https://") and entry["license_url"].startswith("https://"), entry
    sources = json.dumps(dict(schema_version=1, reviewed_at="2026-09-16", entries=entries), ensure_ascii=False, indent=2) + "\n"
    parts = ["YOUSPEED — SOURCES AND THIRD-PARTY NOTICES\nReviewed 2026-09-16.\n\nThis document records sources, authors, changes and licence notices. Individual components retain their own licences; original licence texts retain their publication language. Android-only dependencies and test-only reference photographs are identified below. Complete model, dataset and conversion-tool licence texts are also available from Info's traffic-sign model notices.\n\nYouSpeed source: " + REPO + "\nMap database downloads: " + REPO + "/releases\n"]
    for entry in entries:
        parts.append("\n".join([entry["title"], entry["attribution"], entry["license"], "Source: " + entry["source_url"], "Licence / legal basis: " + entry["license_url"], "Changes: " + entry["changes"]]))
    for label, path in [
        ("German sign images and Prolix mapping", SIGNS / "THIRD_PARTY_NOTICES.txt"),
        ("Android font: original embedded copyright and SIL OFL 1.1", OUT / "licenses/U_DIN_OFL.txt"),
        ("Android dependency notices extracted from resolved release artifacts", OUT / "licenses/ANDROID_ARTIFACT_NOTICES.txt"),
        ("Vosk Android native dependencies", OUT / "licenses/VOSK_NATIVE_NOTICES.txt"),
        ("Android traffic-sign model conversion tools", OUT / "licenses/ANDROID_CONVERSION_NOTICES.txt"),
        ("Ultralytics source and redistribution record", OUT / "licenses/ULTRALYTICS_SOURCE_NOTICE.txt"),
        ("Vosk German speech model: Apache License 2.0", ROOT / "android/app/src/main/assets/vosk-model-small-de-0.15/COPYING"),
        ("YouSpeed source code: GNU AGPL v3", ROOT / "LICENSE"),
    ]:
        parts.append(label + "\n\n" + path.read_text())
    return {OUT / "sources.json": sources, OUT / "THIRD_PARTY_NOTICES.txt": "\n\n" + ("\n\n" + "=" * 80 + "\n\n").join(parts) + "\n"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, text in generate().items():
        if args.check:
            if not path.exists() or path.read_text() != text:
                raise SystemExit(f"Out of date: {path.relative_to(ROOT)}")
        else:
            path.write_text(text)
    print("Mobile attribution catalog and notices verified." if args.check else "Mobile attribution catalog and notices generated.")

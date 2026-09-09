# Country selection and localized penalty screenshots

The September 2026 review separates the country used for penalty warnings from
the country of the downloaded map. Device language controls the interface;
location controls the applicable country rules. Reviewed tariffs and primary
sources are in [the country rule review](COUNTRY_RULE_REVIEW_2026-09-09.md).

## Location and rule selection

- Both apps use the bundled offline regional coverage catalog. A first fresh,
  accurate fix in a uniquely covered country can select its rules immediately.
- Changing country requires at least three consistent fixes over fifteen seconds.
  Pending transitions, overlapping coverage, unsupported countries and invalid
  fixes suppress penalty estimates. There is no fallback to German fines.
- A fix must be at most thirty seconds old with accuracy at most 100 metres.
  Rule eligibility expires according to the fix timestamp. A GPS lapse or
  invalid fix clears pending transition evidence; future timestamps cannot block
  subsequent valid fixes.
- Download completion and map routing do not change penalty eligibility. The
  apps prefer the reviewed rules bundled with the current app over older rules
  stored beside downloaded maps. Map and camera context still follow their own
  map metadata.

The catalog contains **buffered extract coverage, not administrative borders**.
The policy is deliberately conservative in overlapping border areas; it does
not promise an exact switch at a border line. No online reverse geocoder or
location upload was introduced.

## Translation coverage

The reviewed main, settings, capture, download, permission, status and warning
flows support German, English, French and Dutch. French/Dutch/Belgian penalty
templates have all four translations. Country labels and spoken alerts follow
the device language. The offline correction recognizer still accepts German;
its prompt and explanation say so.

Android's static UI resource additions also cover Spanish, Italian, Polish,
Brazilian Portuguese and Swedish. Runtime messages and the newly reviewed
penalty templates fall back to English in those five languages; they are not
fully localized end to end. Existing technical diagnostic identifiers and
operating-system exception details may remain English. Other countries' tariff
templates were not translated or legally re-audited in this task.

## Native screenshot matrix

Each platform captures 33 original PNGs, for 66 total:

| Country / UI language | Excess over limit (km/h) | Posted limit |
| --- | --- | --- |
| France / French | 0, 2, 10, 25, 35, 45, 55 | 50 |
| France / French | 2, 10 | 70 |
| Netherlands / Dutch | 0, 2, 10, 35, 45, 55 | 50 |
| Belgium / Dutch | 0, 5, 15, 25, 35, 45 | 50 |
| Belgium / French | 0, 5, 15, 25, 35, 45 | 50 |
| Belgium / German | 0, 5, 15, 25, 35, 45 | 50 |

These are **simulations**, not road measurements. Paris, Amsterdam and Brussels
GPS positions, synthetic road labels and speed/limit inputs drive the actual
country selector, bundled-rule parser, penalty engine and native UI. The
harness does not supply precomputed fine text or generate/edit screenshot
pixels. JSON sidecars record each input and result; Android also records the
accessibility tree and checks displayed translations during capture.

The UI explicitly calls GPS excess indicative and says no enforcement tolerance
has been deducted. Missing exact fines display a localized review label, not a
made-up fine, point count or fixed driving ban. Warning text uses opaque black
or white selected for contrast against the actual background. The French
70-km/h cases verify the lower fine independently of an urban/rural flag.

## Reproduction

Install the Debug app on an Android emulator, then run from the repository root:

```sh
python3 scripts/capture_country_penalties_android.py \
  --adb /path/to/android-sdk/platform-tools/adb \
  --serial emulator-5580 \
  --output /path/to/YouSpeed-country-review
```

The iPhone equivalent is `scripts/iphone/capture_country_penalties.py`; use
`--help` for simulator/app selection. Both scripts write per-country/per-language
folders beneath the chosen output directory and leave store screenshots alone.

Generate the self-contained local gallery with original-image/evidence links:

```sh
python3 scripts/generate_country_screenshot_gallery.py \
  --root /path/to/YouSpeed-country-review --require-complete
```

The gallery checks expected scenarios, PNG headers, dimensions, evidence links
and hashes. It performs no upload or hosting. Captures and build artifacts are
kept outside version control.

## Final validation results

- Android Debug and Release builds passed. Each unit-test variant passed 173
  tests with no failures. The emulator suite passed 40 tests, including live
  GitHub download/install/hash verification, with five optional replay/benchmark
  cases skipped for missing inputs. The final UI smoke run passed all three
  cases. Lint reported zero errors and 53 warnings.
- iPhone Debug simulator and unsigned generic-device Release builds passed.
  The final complete suite executed 274 tests: 252 passed, 22 skipped, zero
  failures. Live download/assembly/lookup passed. Skips require 17 optional map
  fixtures, one benchmark fixture pair, or four physical-device checks.
- All 66 native screenshots passed scenario/translation checks and visual
  inspection. The local gallery validated all image hashes, expected dimensions,
  201 evidence links and its filters. No screenshot pixels were edited.
- Android/iPhone rule JSONs are byte-identical for FRA, NLD and BEL.
  `git diff --check` passed. Generated screenshots and validation logs are
  outside the repository.

# Offline map Data Manager

The map-package controls live in **Settings → Data Manager** on iPhone and
Android. The manager has **Map** (the initial tab) and **List** tabs. The
settings page starts with a single Data Manager entry at the very top rather
than the full list.

The initial and reset map focus is Germany, with nearby border context
(`west=5.5, south=47.0, east=15.8, north=55.6`). It does not fit every supported
region into one worldwide view. Europe overview and explicit region focus keep
all 51 packages accessible, including France's overseas regions.

## Interaction contract

- A tap on the map only selects a region. It never starts a download or deletes
  data, including on repeated taps.
- The full list and map share selection, metadata, installation state, and
  explicit actions. Switching tabs does not start or cancel an operation.
- Both tabs use compact rows and spacing while retaining accessible touch
  targets. The list is a complete management view, not only a search fallback.
- The selected-region card shows the package name and installation state.
  Installed data and available-download metadata have separate labels.
- Download/check-update and delete are explicit buttons. Deletion requires a
  confirmation naming the actual installed scope and retained versions.
- A legacy whole-country installation can cover a selected regional shard.
  Its broader scope must be visible in the detail card and deletion prompt.
- Pan, zoom, reset, and region focus use the same projected coordinates as hit
  testing. A named searchable selector reaches every configured option,
  including tiny regions and France's overseas regions.
- Green means installed, blue means available to download, and gray means a
  confirmed unavailable release. Unchecked metadata or a failed connection
  remains a distinct unknown state. An outline marks selection, and text/icon
  labels provide the same information without relying on color. Installed
  packages remain green when offline.
- Back returns to Settings. Leaving the manager does not cancel a download;
  reopening it exposes the controller's existing operation and progress.
- Main's download queue remains available: another package can be queued while
  one downloads, and a queued package exposes an explicit cancel action. Existing
  lookup pauses during Settings and bundle removal are retained.
- Selecting a search result dismisses the search keyboard so package details
  and actions remain reachable on phones and in landscape.
- Existing location-selection recovery, generic synchronization progress,
  errors, and confirmed delete-all operations remain available in the manager.

## Data boundaries

The offline display uses
[`official-regions-v1.json`](../shared/RegionalCoverage/official-regions-v1.json),
already packaged in both apps. The 51 geometry IDs join configured download
options by their exact `country_id|region_id` key. The required
`© EuroGeographics for the administrative boundaries` credit stays visible.

Administrative artwork is not precise downloaded-extract coverage. Automatic
location routing continues to use
[`catalog-v1.json`](../shared/RegionalCoverage/catalog-v1.json), including its
buffered extract boundaries. The new UI does not change routing, matching,
traffic-sign country eligibility, manifest trust, checksums, or activation.

The package date comes from manifest `created_at_utc`; it is a build date, not
an OSM observation timestamp. Download size uses validated transport metadata,
including multipart sizes. Installed size uses the installed inventory.
Missing, invalid, offline, or failed metadata remains explicitly unknown or
cached. Having a configured geometry does not guarantee a currently available
remote release. Selecting regions fetches only bounded metadata, never their
database artifacts.

## Verification

Portable geometry/asset contract checks:

```sh
python3 -m unittest discover -s tests/map -p test_region_data_manager_contract.py -v
```

Run the native test suites from the repository README in a supported Android
SDK/Xcode environment. New native tests cover map geometry/projection,
metadata interpretation, installed scope, and manager navigation. Check the
following flows on devices or simulators before release:

1. Settings → Data Manager → Map/List → region → Back, Close, reopen, and rotation
2. Germany-first view; tiny regions, polygon holes, overseas search/focus,
   Germany reset, Europe overview, pan and pinch/zoom
3. Download, repeated action taps, progress, failure/retry, and leaving/reopening
4. Delete confirmation Cancel and Confirm; region versus whole-country scope
5. Existing bootstrap/sync states, retry location selection, and bulk delete
6. Offline installed metadata; unavailable and stale remote metadata
7. VoiceOver/TalkBack, large text, long localized names, and both landscapes
8. Retained selection, details, and action state across both compact tabs;
   available versus installed versus unavailable versus unchecked colors

Use synthetic test fixtures for state transitions. Real bundle downloads and
model/database fixtures are unnecessary for these UI and geometry checks.

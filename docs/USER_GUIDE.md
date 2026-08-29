# YouSpeed iPhone user guide

This guide shows how to download offline map data, record a speed-limit correction, export it as an OpenStreetMap change file, and review it before uploading to OpenStreetMap (OSM).

The screenshots were made with YouSpeed in an iPhone 17 Simulator using the German interface. Microphone and speech-recognition permissions are assumed to be granted. Because no live speech was available, the correction example uses an assumed recognition result of **30**. The Durlacher Allee entry is demonstration data, not evidence that the real road should be changed.

> **Safety:** Set up the app before travelling. Only record a correction while stopped safely or as a passenger. YouSpeed is advisory; signs and traffic rules always take precedence.

## 1. Main driving screen

![YouSpeed driving screen in the iPhone Simulator](user-guide/ios-driving-screen.png)

The large sign is the speed limit currently matched from the local map. The number below it is the current GPS speed. Use the bug button at the upper left to open **Lokale Erfassungen** (local recordings), and the gear at the lower right to open settings.

## 2. Download regional maps

Open settings with the gear, then scroll to **Kartendaten-Download**. Countries are listed alphabetically. Countries with regional bundles, such as **Deutschland**, show each region separately.

![YouSpeed settings showing German regional map downloads](user-guide/ios-regional-map-downloads.png)

1. Connect to the internet, open **Einstellungen → Kartendaten-Download**, and find the country or region you need.
2. Tap the down-arrow button beside the region, for example **Baden-Württemberg** or **Bayern**.
3. Keep YouSpeed open until the progress indicator finishes. The downloaded bundle becomes available for offline matching.
4. Repeat for other regions you need. Each bundle can be managed independently.
5. To reclaim storage, use the delete control shown for a downloaded bundle, or **Heruntergeladene Datenbanken loeschen (Seed behalten)** to remove all downloaded bundles while retaining the built-in seed data.

The screenshot uses the simulator fixture, so its status values read `ready screenshot` and `screenshot`; a normal installation displays the active bundle and live download status instead.

## 3. Record a correction by voice

1. Wait until YouSpeed shows the relevant road and speed-limit sign, and make sure the phone has a good GPS fix.
2. **Double-tap the large speed-limit sign.**
3. On first use, allow microphone and speech-recognition access. This guide assumes both permissions are already granted.
4. When the sign changes to `?` and the app says **Jetzt sprechen**, say only the new number, for example **“30”**. You can also say **“Fussgaengerzone”** for walking speed.
5. YouSpeed stores the result locally. It does not change OpenStreetMap automatically.

![YouSpeed waiting for a spoken speed-limit correction](user-guide/ios-correction-listening.png)

## 4. Review and export the local recording

Open **Lokale Erfassungen** with the bug button. Check the timestamp, street, OSM way ID, old value (**alt**) and new value (**neu**). Delete an entry if the road match or recognized value is wrong.

![Local YouSpeed recording showing a correction from 50 to 30](user-guide/ios-local-recordings.png)

Tap **changes.osc exportieren**, then choose **In Dateien sichern** to save `changes.osc` in Files, or transfer it to the Mac with AirDrop or another share-sheet action.

![iOS share sheet for the exported changes.osc file](user-guide/ios-osc-export.png)

The export is a proposal containing OSM way IDs and intended `maxspeed` values. It is not a fully reviewed OSM data set.

## 5. Review the OSC proposal and upload to OSM

Use the dedicated OSM account:

- Sign-in email: `raphael.volz@pm.me`
- OSM username: `youspeed DOT de - mapping speed limits`

The username in the Safari account menu confirms which account is active. Never put the email address or password into the changeset comment.

![OpenStreetMap in Safari with the YouSpeed mapping account signed in](user-guide/osm-account.png)

### Safe JOSM workflow

The current YouSpeed `changes.osc` export contains only each way ID and the proposed `maxspeed` tag. It does not contain the complete current way geometry, version or other tags. **Do not upload the imported OSC layer directly.** Use it as a checklist and apply each verified change to freshly downloaded OSM data:

1. Install and open [JOSM](https://josm.openstreetmap.de/), then use **File → Open…** to inspect `changes.osc`.
2. For every listed way, use **File → Download object…** (`Ctrl+Shift+O`), select **way**, enter its ID, and download the current object from OSM. Download the surrounding area and referrers when they affect the road. See the [JOSM Download Object guide](https://josm.openstreetmap.de/wiki/Help/Action/DownloadObject).
3. Compare the proposed value with an actual on-site observation. Check that the way covers the correct road segment and that the limit applies to its whole length.
4. Edit the freshly downloaded way, preserving its geometry and all unrelated tags. Set `maxspeed=30` only when 30 applies in both directions. For a direction-specific or conditional sign, use the appropriate OSM tagging instead; consult the [OSM `maxspeed` documentation](https://wiki.openstreetmap.org/wiki/Key%3Amaxspeed).
5. In JOSM connection settings, start OAuth authorization. Safari should open the OSM authorization page. Confirm that it shows **youspeed DOT de - mapping speed limits**, then authorize JOSM.
6. Run JOSM validation and resolve errors or conflicts. Re-download/update the data if another mapper changed it while you were reviewing.
7. Choose **File → Upload data** (`Ctrl+Shift+↑`). Review the exact list of modified objects. Enter a concise changeset comment, for example `Update signed speed limits after on-site survey with YouSpeed`, and set the source to `survey` only when that is true. The [JOSM upload guide](https://josm.openstreetmap.de/wiki/Help/Action/Upload) explains the validator and upload dialog.
8. Click **Upload Changes** only after the final review. This publishes the edit to OSM under the selected account and cannot be treated as a private test.

The simulated 50 → 30 example in this guide was deliberately **not uploaded**.

## Troubleshooting

- **No “Jetzt sprechen” screen:** Check iOS **Settings → Privacy & Security → Microphone** and **Speech Recognition**, then enable YouSpeed. German on-device speech recognition must be available.
- **Wrong recognized number or road:** Delete the local entry and record it again only when the correct road is matched.
- **Export button produces no useful file:** Confirm that at least one valid local recording is listed.
- **JOSM reports incomplete or conflicting data:** Do not force the upload. Download the current way and its surroundings again, apply the verified tag to that complete object, and rerun validation.
- **Regional list or download is unavailable:** Check connectivity, reopen settings, and retry. Existing downloaded maps continue to work offline.

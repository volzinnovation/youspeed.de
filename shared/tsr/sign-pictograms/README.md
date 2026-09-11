# German sign pictograms

Reviewed on 2026-09-10 against the user-supplied [German sign plate since
2017](https://de.wikipedia.org/wiki/Bildtafel_der_Verkehrszeichen_in_der_Bundesrepublik_Deutschland_seit_2017)
and the German StVO. The plate identifies artwork; the law determines the
meaning. These are offline UI assets, not training samples or proof of model
recognition capability.

`../prolix-de-class-catalog-v1.json` preserves the 134 ordered labels in the
bundled Core ML classifier. Its checkpoint is
`f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7`
from Panoramax `classify_de_road_signs` revision
`5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`. The deployed Prolix DE mapping
was reviewed as a separate 142-entry reference. It does not define the mobile
model's actual output vocabulary.

## Files and verification

- `originals/`: original Commons SVG bytes, without artwork edits.
- `png/`: 8-bit PNG renditions fitted inside 256 × 256 pixels, preserving aspect
  ratio and transparency. Both mobile apps use these same bytes.
- `manifest.json`: original URLs and upload timestamps, Commons page revisions,
  authors, public-domain basis, original SHA-1/SHA-256, PNG SHA-256, dimensions,
  sizes, and the conversion command. All paths in this manifest are relative
  to this directory. Catalog image paths instead are relative to `shared/`.
- `selection.json`: explicit sign-code-to-Commons-title selection, derived from
  the plate. It is not a fuzzy filename search or automatic semantic mapping.
- `sources/`: the reviewed deployed DE mapping and its snapshot provenance.
- `THIRD_PARTY_NOTICES.txt`: offline credit and licensing notice for packaging
  with the PNG assets.

Verify all bytes and image dimensions offline:

```sh
python3 shared/tsr/sign-pictograms/fetch.py
```

To restore missing assets, use `fetch.py --fetch`. This requires `curl`, network
access and ImageMagick 7.1.2-3. It fetches pinned originals sequentially, verifies
their hashes, and recreates PNGs locally. Two renderer exceptions, signs 206
and 250, use separately pinned Commons PNG renditions: ImageMagick's SVG reader
loses their lettering or red ring. `png_source_kind`, source URL and source
hash record this distinction. Different bytes fail verification;
the script never updates the manifest or overwrites an existing mismatched
file. Review an intentional source/renderer update separately. Current PNGs
were produced on aarch64 with ImageMagick 7.1.2-3 Q16-HDRI; another platform may
render different bytes and correctly fail that reproducibility check.

## Display contract

Render the PNG alpha directly, without a white card or background outside the
physical sign outline. White sign faces, lettering and borders remain opaque.
All 105 assets already have transparent exteriors; do not turn white pixels
globally transparent, which would also erase required parts of the signs.

`display_eligible` means that a faithful pictogram exists for the entry. It does
not authorize a speed override or decide which signs belong in the secondary
sign card. Numeric speed signs may have artwork while the UI uses its main
speed display for them. Speed actions remain governed by the reviewed model
manifest and passage/state logic.

The first 134 `signs` entries correspond exactly to `class_labels`. Additional
exact `DE:278-x`, `DE:281`, `DE:282`, `DE:310`, `DE:311` and semantic aliases are
marked reference-only in their notes. A consumer must not infer that the pinned
model emits them. In particular, the checkpoint has no city-entry/city-exit
class and cannot gain that capability from an asset or alias.

Blocked entries have `display_eligible: false` and `image_path: null`. They cover
invalid/background/unknown classes, missing reviewed mappings, wildcard or
left/right variants, and numeric restrictions whose values are not model
outputs. For example, generic `maxheight` must not display a made-up 3 m limit;
generic `maxspeed:end` must not display a made-up crossed-out 30. The explicit
`maxspeed:25` model class is retained but currently has no matching asset from
the supplied plate. Generic `zone:end` does not identify a zone's number;
`zone:30:end` has a specific 30-zone-end pictogram.

## Reviewed mapping corrections

The catalog retains source-map provenance and documents its changes per entry:

- `arrow_turn_left` maps to DE:209-10; `arrow_turn_right` maps to DE:209. The
  deployed DE map interchanges these two pictograms.
- Model labels `hazard:left_turn` and `hazard:right_turn` map to DE:103-10 and
  DE:103-20. The deployed map uses different label spellings and maps its
  `hazard:turn_right` to DE:101-20, which depicts aircraft rather than a bend.
- The actual `zone:30:end` label maps to DE:274.2. It is absent from the deployed
  cross-country table.
- `exit` remains blocked: the deployed DE:460 is a numbered motorway detour,
  which does not establish an unambiguous exit pictogram.
- The deployed incline mappings also interchange ascent/descent. The actual
  classifier only emits generic `hazard:incline`, so no direction or percentage
  is fabricated.

These are display mappings; they do not change the deployed Prolix service or
the classifier weights. Existing model labels can themselves remain imperfect
predictions and must pass the app's recognition confidence/temporal gates.

## Speed-related legal distinctions

[StVO Anlage 2, items 55–60](https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html)
distinguishes the following signs:

- 278 ends the indicated maximum-speed restriction.
- 279 ends a prescribed minimum speed.
- 280 ends the general overtaking ban.
- 281 ends the overtaking ban for vehicles over 3.5 t. It does not end a speed
  restriction.
- 282 ends route-specific speed restrictions and overtaking bans. It does not
  cancel every traffic rule or universally establish unlimited speed.

An end sign integrated into a lane panel applies to the indicated lane.
General vehicle/road rules and any separately applicable enclosing zone must
still be resolved before assigning a new speed.

[Anlage 3, items 5–6](https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html)
defines 310 and 311 as the beginning and end of a built-up area. Under
[§3(3) StVO](https://www.gesetze-im-internet.de/stvo_2013/__3.html), the ordinary
urban maximum is 50 km/h for motor vehicles. A town exit requires vehicle and
road context; it is not an unconditional 100 km/h or unlimited-speed command.
Town names in the original pictograms are official illustrative artwork, not
recognized text or the user's location.

## Licensing

Each selected Commons file declares **Public domain**, with attribution not
required, based on the German official-work rule in
[§5(1) UrhG](https://www.gesetze-im-internet.de/urhg/__5.html). This status is
recorded per file. Credits are preserved voluntarily in the manifest and
offline notice. The website's general CC BY-SA text license is not the image
license; do not relabel these originals as CC BY-SA or CC0.

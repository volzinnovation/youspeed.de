"""Write the completed assistant visual review; never change the frozen City split."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
INVENTORY = json.loads((OUT / "source-inventory.json").read_text())
SOURCE = Path(INVENTORY["source_manifest"]).parent
FRAME_SPLIT = json.loads((OUT / "learning-frame-split.json").read_text())
FRAMES = {row["picture_id"]: row for row in FRAME_SPLIT["rows"]}
REMOTE = Path("/home/raphael/youspeed-lecture-download-test-20261020-f1a2266d/run-fixed/lectures/tsr-sgblur-de-2026-10-26/praktikum/data/collection")
CLASSES = set(json.loads((OUT.parents[2] / "praktikum/class-index.json").read_text())["classes"])

# One explicit observation per indexed crop, entered after viewing all nine sheets.
# '-' means no defensible canonical-class assignment for the primary crop audit.
OBSERVATIONS = """
001|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
002|-|Sehr schräger kleiner Parkverbotskreis; ein oder zwei rote Diagonalen nicht sicher unterscheidbar.
003|no_entry|Roter Kreis mit waagerechtem weißem Balken.
004|maxspeed:70|Roter Kreis mit lesbarer Zahl 70.
005|hazard|Warndreieck mit schwarzem Ausrufezeichen.
006|maxheight|Roter Kreis mit Höhenbegrenzung 4,0 m und Pfeilen.
007|priority:start|Gelbe Vorfahrtsraute; Rand unten/rechts knapp, Klasse erkennbar.
008|give_way|Weißes umgekehrtes Dreieck mit rotem Rand.
009|roundabout|Blauer Kreis mit drei weißen Kreispfeilen.
010|city:start|Gelbe Ortseingangstafel Michelbach; derselbe Bildinhalt wie city-016, zusätzliche überlappende Annotation.
011|city:start|Gelbe Ortseingangstafel Althof; derselbe Bildinhalt wie city-020, zusätzliche überlappende Annotation.
012|-|Kleines verschwommenes Warndreieck; Kinder-Symbol nicht zuverlässig genug für eine primäre Klassenfreigabe.
013|parking|Sichtbar ist ein blaues P mit linkem Richtungspfeil; Quelltag DE:1044-10 beschreibt nicht das sichtbare Hauptschild.
014|maxspeed:50|Roter Kreis mit lesbarer Zahl 50.
015|roundabout|Blauer Kreis mit drei weißen Kreispfeilen.
016|priority:start|Vollständige gelbe Vorfahrtsraute.
017|maxheight|Roter Kreis mit Höhenbegrenzung 4,0 m und Pfeilen.
018|give_way|Weißes umgekehrtes Dreieck mit rotem Rand.
019|no_overtaking|Roter Kreis mit rotem und schwarzem Pkw.
020|maxspeed:50|Roter Kreis mit lesbarer Zahl 50.
021|arrow:red|Kleine weiß-rote Rechtsleitbake; deutliches rotes Chevron.
022|arrow:red|Kleine weiß-rote Rechtsleitbake; deutliches rotes Chevron.
023|arrow:red|Kleine weiß-rote Rechtsleitbake; deutliches rotes Chevron.
024|maxspeed:70|Kleiner roter Kreis mit erkennbarer Zahl 70.
025|priority:start|Vollständige gelbe Vorfahrtsraute.
026|parking|Sichtbar ist ein blaues P mit linkem Richtungspfeil; Quelltag DE:1044-10 beschreibt nicht das sichtbare Hauptschild.
027|arrow:red|Weiß-rote Rechtsleitbake mit rotem Chevron.
028|arrow_turn_left_through|Blauer Kreis mit weißem Geradeauspfeil und linkem Abzweig.
029|pedestrian_bicycle:start|Blauer gemeinsamer Geh-/Radweg mit übereinander angeordneten Symbolen.
030|parking|Blaues quadratisches P-Schild.
031|hazard|Warndreieck mit schwarzem Ausrufezeichen.
032|arrow_turn_right_through|Blauer Kreis mit weißem Geradeauspfeil und rechtem Abzweig.
033|-|Weißer Parkplatz-Wegweiser mit Orts-/Straßentext und Pfeil; zusammengesetztes Schild außerhalb einer eindeutig zugeordneten Klasse.
034|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
035|no_parking|Blauer Kreis mit einem roten Diagonalstrich.
036|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
037|maxspeed:70|Roter Kreis mit lesbarer Zahl 70.
038|maxspeed:30|Kleiner roter Kreis; Zahl 30 noch erkennbar.
039|maxspeed:70|Roter Kreis mit lesbarer Zahl 70.
040|arrow_right_down|Blauer Kreis mit weißem Pfeil nach rechts unten.
041|hazard:road_works|Kleines Warndreieck mit erkennbarem arbeitendem Menschen/Schaufel.
042|no_way|Roter Ring mit weißer Mitte; Blätter verdecken einen Randbereich, Grundklasse klar.
043|hazard:intersection|Warndreieck mit schwarzem Vorfahrt-Kreuzungssymbol.
044|zone:30|Rechteckiges Schild mit Zahl 30 im roten Kreis und ZONE.
045|priority:start|Gelbe Vorfahrtsraute.
046|maxspeed:30|Kleiner roter Kreis mit erkennbarer Zahl 30.
047|hazard:intersection|Warndreieck mit schwarzem Vorfahrt-Kreuzungssymbol.
048|no_way|Schräg betrachteter roter Ring mit weißer Mitte.
049|no_way|Roter Ring mit weißer Mitte; Graffiti/Schrägansicht, Grundklasse erkennbar.
050|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
051|hazard:intersection|Warndreieck mit schwarzem Vorfahrt-Kreuzungssymbol.
052|-|Sichtbar ist eine Fußgänger-Warnfigur; DE:101-x1/Modellklasse hazard:pedestrian_crossing ist gegenüber dem sichtbaren DE:133-Motiv nicht eindeutig.
053|priority:start|Gelbe Vorfahrtsraute.
054|priority:start|Gelbe Vorfahrtsraute.
055|roundabout|Kleiner blauer Kreis mit erkennbaren weißen Kreispfeilen.
056|roundabout|Kleiner blauer Kreis mit erkennbaren weißen Kreispfeilen.
057|no_overtaking|Kleiner roter Kreis mit erkennbarem roten und dunklen Pkw; leicht unscharf.
058|no_overtaking|Kleiner roter Kreis mit erkennbarem roten und dunklen Pkw.
059|roundabout|Kleiner blauer Kreis mit erkennbaren weißen Kreispfeilen.
060|give_way|Weißes umgekehrtes Dreieck mit rotem Rand.
061|arrow_right_down|Blauer Kreis mit weißem Pfeil nach rechts unten.
062|arrow_right|Kleiner blauer Kreis mit waagerechtem weißem Rechtspfeil.
063|arrow_right_down|Blauer Kreis mit weißem Pfeil nach rechts unten.
064|roundabout|Kleiner blauer Kreis mit erkennbaren weißen Kreispfeilen.
065|stop|Kleines rotes Achteck mit lesbarem STOP.
066|hazard:slippery|Warndreieck mit schleuderndem Pkw und Spurlinien.
067|stop|Rotes Achteck mit lesbarem STOP.
068|hazard:traffic_signal|Warndreieck mit erkennbarem Ampelsymbol.
069|-|Weißer Stadtteil-/Parkplatz-Wegweiser mit mehreren Symbolen, Text und Richtungspfeil; keine Ortstafel, keine eindeutige Einzelklasse.
070|-|P mit Pkw-/Gehwegdarstellung; DE:315 wird im vorhandenen Klassenmapping doppelt als perpendicular/sidewalk geführt. Eindeutige alte Modellklasse nicht gesichert.
071|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
072|no_entry|Kleiner roter Kreis mit waagerechtem weißem Balken.
073|stop|Rotes Achteck mit lesbarem STOP.
074|pedestrian:start|Blauer Kreis mit Fußgänger- und Kindfigur.
075|stop|Rotes Achteck mit lesbarem STOP.
076|arrow_through|Blauer Kreis mit weißem Geradeauspfeil.
077|arrow_through|Blauer Kreis mit weißem Geradeauspfeil.
078|arrow_turn_left|Blauer Kreis mit nach links abbiegendem weißem Pfeil.
079|stop|Rotes Achteck mit lesbarem STOP.
080|no_entry|Schräger roter Kreis mit waagerechtem weißem Balken.
081|no_entry|Roter Kreis mit waagerechtem weißem Balken.
082|no_entry|Schräger roter Kreis mit waagerechtem weißem Balken.
083|arrow_through|Blauer Kreis mit weißem Geradeauspfeil.
084|stop|Rotes Achteck mit lesbarem STOP.
085|arrow_through|Blauer Kreis mit weißem Geradeauspfeil.
086|stop|Rotes Achteck mit lesbarem STOP.
087|no_entry|Schräger roter Kreis mit waagerechtem weißem Balken.
088|arrow_turn_left|Blauer Kreis mit nach links abbiegendem weißem Pfeil.
089|no_parking|Blauer Kreis mit einem roten Diagonalstrich.
090|priority:start|Gelbe Vorfahrtsraute; kleiner Randbereich verdeckt, Klasse erkennbar.
091|no_way|Stark schräge Ansicht eines roten Rings mit weißer Mitte.
092|no_stop|Blauer Kreis mit rotem Diagonalkreuz.
093|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
094|parking|Blaues P-Schild mit linkem Richtungspfeil.
095|-|Grün-gelbes H einer Bushaltestelle; bus:stop ist keine der 136 Klassen, bus:start bezeichnet eine andere Klasse.
096|maxspeed:50|Roter Kreis mit lesbarer Zahl 50.
097|priority:start|Gelbe Vorfahrtsraute.
098|no_way|Roter Ring mit weißer Mitte; leicht unscharf, Grundklasse erkennbar.
099|-|Kleine unscharfe graue Zusatztafel mit kaum erkennbaren Symbolen; keine sichere kanonische Klasse.
100|no_entry|Roter Kreis mit waagerechtem weißem Balken.
101|hazard:intersection|Warndreieck mit schwarzem Vorfahrt-Kreuzungssymbol, schräge Nachtaufnahme.
102|hazard:intersection|Warndreieck mit erkennbarem schwarzen Vorfahrt-Kreuzungssymbol.
103|-|Überstrahltes unscharfes Warndreieck ohne erkennbares inneres Symbol.
104|maxspeed:50|Roter Kreis mit lesbarer Zahl 50.
105|-|Unscharfer blauer Parkverbotskreis; Diagonalstriche sind nicht zuverlässig zu unterscheiden.
106|hazard:intersection|Warndreieck mit erkennbarem schwarzen Vorfahrt-Kreuzungssymbol.
107|parking|Blaues quadratisches P-Schild.
108|parking|Unscharfes blaues P-Schild, Buchstabe aber erkennbar.
109|hazard:intersection|Warndreieck mit erkennbarem schwarzen Vorfahrt-Kreuzungssymbol.
110|-|Stark überstrahlter Verbotskreis; mögliche Innenzeichnung durch Belichtung verloren, Quelltag alleine genügt nicht.
111|-|Stark überstrahlter Verbotskreis; mögliche Innenzeichnung durch Belichtung verloren, Quelltag alleine genügt nicht.
112|-|Unscharfes/überstrahltes Warndreieck ohne zuverlässig identifizierbares inneres Symbol.
113|maxspeed:40|Korrektur des Quelltags DE:274-60: die sichtbare Zahl ist 40.
114|no_parking|Blauer Kreis mit einem roten Diagonalstrich und weißem Richtungspfeil.
115|maxspeed:60|Roter Kreis mit lesbarer Zahl 60.
116|-|Grün-gelbes H einer Bushaltestelle; bus:stop ist keine der 136 Klassen.
117|hazard|Warndreieck mit schwarzem Ausrufezeichen.
118|hazard|Warndreieck mit schwarzem Ausrufezeichen.
119|arrow_right_down|Blauer Kreis mit weißem Pfeil nach rechts unten.
120|pedestrian_crossing|Blaues quadratisches Fußgängerüberweg-Schild mit Dreieck/Zebrastreifen.
121|priority:start|Kleine gelbe Vorfahrtsraute; knapp beschnittener Rand, Grundklasse erkennbar.
122|-|Parkverbotskreis mit breiten weißen Überdeckungen/Kreuz; kein sauberes unverdecktes kanonisches Hauptmotiv.
123|parking|Blaues rechteckiges P-Schild mit linkem Richtungspfeil.
124|parking|Blaues quadratisches P-Schild.
125|-|Parkverbotskreis mit breiten weißen Überdeckungen/Kreuz; kein sauberes unverdecktes kanonisches Hauptmotiv.
126|give_way|Weißes umgekehrtes Dreieck mit rotem Rand.
127|-|Texttafel zur Straßensanierung mit kleinem Durchfahrtsverbotssymbol; zusammengesetzte Darstellung, keine eindeutige Einzelklasse.
128|maxspeed:50|Roter Kreis mit lesbarer Zahl 50.
129|no_stop|Blauer Kreis mit rotem Diagonalkreuz und Richtungspfeilen.
130|maxspeed:30|Roter Kreis mit lesbarer Zahl 30.
131|no_stop|Blauer Kreis mit rotem Diagonalkreuz und Richtungspfeilen.
132|parking|Blaues P-Schild mit rechtem Richtungspfeil; oberer Rand knapp, Klasse erkennbar.
133|hazard:intersection|Warndreieck mit schwarzem Vorfahrt-Kreuzungssymbol.
134|pedestrian_crossing|Blaues quadratisches Fußgängerüberweg-Schild mit Dreieck/Zebrastreifen.
135|arrow_right_down|Blauer Kreis mit weißem Pfeil nach rechts unten.
136|pedestrian_crossing|Blaues quadratisches Fußgängerüberweg-Schild mit Dreieck/Zebrastreifen, anderes Schild im selben Foto als other-134/137.
137|pedestrian_crossing|Blaues quadratisches Fußgängerüberweg-Schild mit Dreieck/Zebrastreifen, anderes Schild im selben Foto als other-134/136.
138|hazard:intersection|Warndreieck mit schwarzem Vorfahrt-Kreuzungssymbol.
139|no_stop|Blauer Kreis mit rotem Diagonalkreuz und Richtungspfeilen.
140|-|Nur unterer roter Kreisbogen im extrem schmalen Bildausschnitt; Schildmotiv fehlt.
141|hazard|Großes Ausrufezeichen im Warndreieck; obere Spitze beschnitten, Motiv erkennbar.
142|arrow_right_down|Blauer Kreis mit weißem Pfeil nach rechts unten.
143|pedestrian:start|Blauer Kreis mit Fußgänger- und Kindfigur.
144|stop|Rotes Achteck mit lesbarem STOP.
""".strip().splitlines()

DUPLICATES = {10: "city-016", 11: "city-020"}
REJECT_QUALITY = {
    2: "reject_blur_oblique", 12: "reject_resolution", 33: "reject_composite",
    52: "reject_taxonomy_ambiguity", 69: "reject_composite", 70: "reject_taxonomy_ambiguity",
    95: "reject_unsupported_class", 99: "reject_unreadable", 103: "reject_overexposure",
    105: "reject_blur", 110: "reject_overexposure", 111: "reject_overexposure",
    112: "reject_blur_overexposure", 116: "reject_unsupported_class",
    122: "reject_covered_symbol", 125: "reject_covered_symbol", 127: "reject_composite",
    140: "reject_incomplete_box",
}
rows = []
for observation, crop in zip(OBSERVATIONS, INVENTORY["other"], strict=True):
    number, label, reason = observation.split("|", 2)
    index = int(number)
    assert crop["review_index"] == f"other-{index:03d}"
    path = SOURCE / crop["crop_path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == crop["crop_sha256"]
    frame = FRAMES[crop["picture_id"]]
    proposed_label = None if label == "-" else label
    assert proposed_label is None or proposed_label in CLASSES
    decision = "accept" if proposed_label is not None else "reject"
    quality = "usable_complete" if min(crop["crop_dimensions"]) >= 48 else "usable_small_or_tight_class_visible"
    if index in [7, 90, 121, 132, 141]:
        quality = "usable_tight_or_partial_edge_class_visible"
    if index in DUPLICATES:
        decision, quality = "reject", "duplicate_annotation"
    if index in REJECT_QUALITY:
        quality = REJECT_QUALITY[index]
    rows.append(dict(
        review_index=crop["review_index"], sample_id=crop["sample_id"], picture_id=crop["picture_id"],
        annotation_id=crop["annotation_id"], sequence_id=crop["sequence_id"],
        label=proposed_label if decision == "accept" else None, proposed_label=proposed_label,
        decision=decision, reason=reason, box_quality=quality,
        duplicate_of_review_index=DUPLICATES.get(index),
        is_visually_non_city=proposed_label not in ["city:start", "city:end"],
        group_id=frame["group_id"], frame_subset=frame["subset"],
        subset=frame["subset"] if decision == "accept" else "reject",
        selected_for_current_training=False,
        crop_absolute_path=str(REMOTE / crop["crop_path"]), crop_local_path=str(path.resolve()),
        crop_sha256=crop["crop_sha256"], crop_dimensions=crop["crop_dimensions"],
        source_osm_tags=crop["osm_tags"], capture_datetime=crop["capture_datetime"],
        camera_coordinates=crop["camera_coordinates"], reviewer_type="assistant_visual_review",
        review_status="assistant_review_complete_not_human_ground_truth",
    ))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(name, data):
    data["lock_sha256"] = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

base = dict(
    schema_version="youspeed-assistant-other-crop-review-v1",
    source_manifest=INVENTORY["source_manifest"], source_manifest_sha256=INVENTORY["source_manifest_sha256"],
    source_files_changed=False, human_approval_fields_changed=False,
    review_method="All144 remaining original crops viewed on nine indexed contact sheets; source tags are evidence, not ground truth. Each observation was entered explicitly.",
    use_limit="Audit only: no row in this file is selected for the already frozen City training. Accepted means visually plausible canonical class, not human-approved ground truth. This is not a complete detector annotation review.",
    grouping_policy="Inherit unchanged whole-day/corridor assignment from learning-frame-split.json; reserved days stay reserved. No split reroll and no addition of external test sources.",
    source_frame_split_file="learning-frame-split.json", source_frame_split_sha256=sha(OUT / "learning-frame-split.json"),
    frozen_city_trainval_sha256=sha(OUT / "city-train-val.json"),
    counts=dict(source_crops=len(rows), accepted=sum(r["decision"] == "accept" for r in rows),
                rejected=sum(r["decision"] == "reject" for r in rows),
                class_counts=dict(sorted(Counter(r["label"] for r in rows if r["decision"] == "accept").items())),
                by_subset={s: dict(sorted(Counter(r["label"] for r in rows if r["subset"] == s).items())) for s in ["train", "val", "reserved"]},
                duplicate_city_proposals=2, canonical_classes_observed=len({r["label"] for r in rows if r["decision"] == "accept"})),
    rows=rows,
)
write("other-review.json", base)

city = json.loads((OUT / "city-review.json").read_text())
all_rows = city["rows"] + rows
assert len(all_rows) == 214 and len({r["sample_id"] for r in all_rows}) == 214
write("assistant-review-all.json", dict(
    schema_version="youspeed-assistant-all-crop-review-v1", source_manifest=INVENTORY["source_manifest"],
    source_manifest_sha256=INVENTORY["source_manifest_sha256"], source_files_changed=False,
    human_approval_fields_changed=False, reviewer_type="assistant_visual_review",
    city_review_file="city-review.json", city_review_sha256=sha(OUT / "city-review.json"),
    other_review_file="other-review.json", other_review_sha256=sha(OUT / "other-review.json"),
    frozen_city_trainval_file="city-train-val.json", frozen_city_trainval_sha256=sha(OUT / "city-train-val.json"),
    counts=dict(total=214, accepted=sum(r["decision"] == "accept" for r in all_rows), rejected=sum(r["decision"] == "reject" for r in all_rows),
                training_selection_city_only=46, all136class_coverage=False),
    note="Complete crop audit, not full-frame detector ground truth; only the separate frozen City file supplies the46current training/validation rows. No human approval fields were changed.",
    rows=all_rows,
))
columns = ["review_index", "sample_id", "picture_id", "annotation_id", "sequence_id", "label", "proposed_label", "decision", "reason", "box_quality", "group_id", "subset", "frame_subset", "selected_for_current_training", "crop_absolute_path", "crop_sha256"]
for filename, selected_rows in [("other-review.csv", rows), ("assistant-review-all.csv", all_rows)]:
    with (OUT / filename).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected_rows)
print(json.dumps(base["counts"], ensure_ascii=False, indent=2))
for filename in ["other-review.json", "other-review.csv", "assistant-review-all.json", "assistant-review-all.csv", "city-train-val.json"]:
    print(filename, sha(OUT / filename))

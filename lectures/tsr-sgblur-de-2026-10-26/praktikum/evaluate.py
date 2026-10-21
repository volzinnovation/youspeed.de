#!/usr/bin/env python3
"""Baseline und Kandidat auf denselben unabhängigen Bildern vergleichen."""
import argparse
import csv
from pathlib import Path
import sys

from model_utils import (BASELINE_SHA256, PREPROCESSING, dataset, dependencies,
                         device_for, load_baseline, load_candidate, load_classes,
                         load_manifest, metrics_from_predictions, predict,
                         old_class_regression, samples_for_split, sha256, write_json)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data", type=Path, default=Path("data/dataset"))
    result.add_argument("--baseline", type=Path, default=Path("models/baseline.pt"))
    result.add_argument("--candidate", type=Path, required=True, help="weights/best.pt des Trainingsversuchs")
    result.add_argument("--output", type=Path, default=Path("reports/versuch-01"))
    result.add_argument("--split", choices=["val", "test"], default="val", help="val für Entwicklung; test einmal für Abschluss")
    result.add_argument("--batch-size", type=int, default=16)
    result.add_argument("--device", default="cuda:0")
    return result


def percent(value):
    return "nicht messbar" if value is None else f"{100 * value:.1f} %"


def write_reports(output, report, rows, truth, baseline_predictions, candidate_predictions, classes):
    output = Path(output)
    output.mkdir(parents=True)
    write_json(output / "metrics.json", report)
    gate = report["old_class_regression_gate"]
    write_json(output / "regression-gate.json", gate)
    with (output / "old-only-per-class.csv").open("w", newline="") as stream:
        fields = ["label", "support", "baseline_precision", "candidate_precision", "baseline_recall", "candidate_recall",
                  "baseline_f1", "candidate_f1", "delta_recall", "delta_f1"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(gate["per_class"])
    for name in ["baseline", "candidate"]:
        with (output / f"confusion-{name}.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Wahre Klasse / vorhergesagte Klasse"] + classes)
            for label, counts in zip(classes, report[name]["confusion"]):
                writer.writerow([label] + counts)
    old_regressions = []
    with (output / "per-class.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["label", "support", "baseline_precision", "candidate_precision",
                                                    "baseline_recall", "candidate_recall", "baseline_f1", "candidate_f1", "delta_f1"])
        writer.writeheader()
        for old, new in zip(report["baseline"]["per_class"], report["candidate"]["per_class"]):
            delta = None if old["f1"] is None or new["f1"] is None else new["f1"] - old["f1"]
            row = {"label": old["label"], "support": old["support"],
                   "baseline_precision": old["precision"], "candidate_precision": new["precision"],
                   "baseline_recall": old["recall"], "candidate_recall": new["recall"],
                   "baseline_f1": old["f1"], "candidate_f1": new["f1"], "delta_f1": delta}
            writer.writerow(row)
            if old["index"] < 134 and old["support"] and delta is not None and delta < 0:
                old_regressions.append(row)
    with (output / "predictions.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_id", "group_id", "true_label", "baseline_label", "candidate_label"])
        writer.writerows([row["sample_id"], row["group_id"], classes[target], classes[old], classes[new]]
                         for row, target, old, new in zip(rows, truth, baseline_predictions, candidate_predictions))
    old, new = report["baseline"], report["candidate"]
    old_only, new_only = gate["baseline"], gate["candidate"]
    lines = [f"# Modellvergleich auf {report['split']}", "",
             f"**Verbindliche Prüfung alter Klassen: {gate['status']}.** Toleranz: 0; keine Verschlechterung von Recall/F1 je alter Klasse oder altem Gesamtwert erlaubt.", "",
             "Dieser Vergleich nutzt ausschließlich Bilder, deren wahre Klasse zu den 134 alten Klassen gehört. Neue Ortstafelbilder beeinflussen diese Prüfung nicht.", ""]
    lines += ["- " + reason for reason in gate["reasons"]]
    if gate["passed"]:
        lines += ["Auf diesen geprüften Bildern sind alle 134 alten Klassen vertreten und keine der geprüften Kennzahlen sinkt. Das belegt keine Garantie für alle künftigen Bilder."]
    lines += ["", "| Alte Klassen, nur alte Zielbilder | Baseline | Kandidat |", "| --- | ---: | ---: |",
              f"| Accuracy / Top-1 | {percent(old_only['accuracy'] if old_only else None)} | {percent(new_only['accuracy'] if new_only else None)} |",
              f"| Macro-F1, alte Klassen mit Beispielen | {percent(old_only['old_class_macro_f1_supported'] if old_only else None)} | {percent(new_only['old_class_macro_f1_supported'] if new_only else None)} |", "",
              "Details je alter Klasse: old-only-per-class.csv. Ohne Beispiele für jede alte Klasse bleibt die Prüfung unvollständig.", "",
              "## Gesamter Bildsatz und neue Klassen", "",
             f"{len(rows)} Bilder aus {len(set(row['group_id'] for row in rows))} unabhängigen Gruppen; dieselben Bilder für beide Modelle.", "",
             "| Messwert | Baseline (134 Klassen) | Kandidat (136 Klassen) |",
             "| --- | ---: | ---: |",
             f"| Accuracy | {percent(old['accuracy'])} | {percent(new['accuracy'])} |",
             f"| Macro-F1, Klassen mit Testbeispielen | {percent(old['macro_f1_supported'])} | {percent(new['macro_f1_supported'])} |",
             f"| Macro-F1, Ortstafelklassen mit Beispielen | {percent(old['city_macro_f1_supported'])} | {percent(new['city_macro_f1_supported'])} |", "",
             "Die Baseline kann city:start und city:end nicht ausgeben. Sie wird trotzdem auf allen Bildern bewertet.", "",
             "## Die beiden neuen Klassen", "",
             "| Klasse | Beispiele | Präzision | Recall | F1 |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in new["per_class"][-2:]:
        lines.append(f"| {row['label']} | {row['support']} | {percent(row['precision'])} | {percent(row['recall'])} | {percent(row['f1'])} |")
    old_regressions = [row for row in gate["per_class"] if row["support"] and row["delta_f1"] < 0]
    lines += ["", f"Alte Klassen mit niedrigerem F1 im Vergleich nur alter Zielbilder: **{len(old_regressions)}**. Jede Klasse steht in old-only-per-class.csv; fehlende Beispiele sind keine bestandene Prüfung."]
    for row in sorted(old_regressions, key=lambda item: item["delta_f1"]):
        lines.append(f"- {row['label']}: F1 {percent(row['baseline_f1'])} → {percent(row['candidate_f1'])}; {row['support']} Beispiele.")
    missing = [row["label"] for row in new["per_class"] if not row["support"]]
    if missing:
        lines += ["", "Nicht bewertbare Klassen ohne Beispiele: " + ", ".join(missing) + "."]
    lines += ["", "## Interpretation", "",
              "Präzision: Wie viele als Klasse X gemeldete Bilder sind tatsächlich X? Recall: Wie viele echte X werden gefunden? F1 verbindet beide Werte.", "",
              "Die Confusion-CSV zeigt wahre Klassen in den Zeilen und Vorhersagen in den Spalten. per-class.csv beschreibt den gesamten Bildsatz; old-only-per-class.csv ausschließlich die alten Zielbilder für die Regressionsprüfung. Leere CSV-Felder und null in JSON bedeuten einen nicht definierten Wert.", "",
              "Dies misst Crop-Klassifikation. Detektor-Recall auf Vollbildern, Fehlalarme pro Fahrtstunde, mobile Laufzeit und bestätigte Passagen werden damit noch nicht gemessen.", "",
              "Ein niedrigerer Trainings-Loss reicht nicht für eine Verbesserung. Neue Klassen getrennt prüfen und Verschlechterungen alter Klassen begründen.", "",
              "Nach Einsicht in test keine Hyperparameter mehr anhand dieses Tests ändern. Weitere Änderungen brauchen einen neuen unberührten Testsatz." if report["split"] == "test" else "Dies ist Validierung für die Modellauswahl. Den test-Split erst nach Festlegung des Kandidaten einmal öffnen.", "",
              f"Baseline SHA256: `{report['baseline_sha256']}`", f"Kandidat SHA256: `{report['candidate_sha256']}`",
              f"Datensatzmanifest SHA256: `{report['dataset_manifest_sha256']}`", ""]
    (output / "BERICHT.md").write_text("\n".join(lines))


def run(args):
    if args.batch_size < 1:
        raise ValueError("batch-size muss positiv sein.")
    if args.output.exists():
        raise ValueError("Berichtsordner existiert bereits. Für den nächsten Vergleich einen neuen --output wählen.")
    classes = load_classes()
    manifest, manifest_sha = load_manifest(args.data, classes)
    rows = samples_for_split(args.data, manifest, args.split, classes)
    print(f"Vergleich auf {args.split}: {len(rows)} Bilder. {'Abschlusstest geöffnet.' if args.split == 'test' else 'Testdaten bleiben geschlossen.'}", flush=True)
    torch, ultralytics, np, Image, ImageOps = dependencies()
    device = device_for(torch, args.device)
    loader = torch.utils.data.DataLoader(dataset(torch, np, Image, ImageOps, rows), batch_size=args.batch_size, shuffle=False, num_workers=0)
    baseline = load_baseline(torch, ultralytics, args.baseline, classes).to(device)
    truth, baseline_predictions = predict(torch, baseline, loader, device, "Baseline")
    baseline_result = metrics_from_predictions(truth, baseline_predictions, classes)
    # Nach Baseline-Auswertung ihren unveränderten Backbone als Architektur nutzen.
    baseline.to("cpu")
    candidate, metadata = load_candidate(torch, baseline, args.candidate, classes, manifest_sha)
    candidate.to(device)
    candidate_truth, candidate_predictions = predict(torch, candidate, loader, device, "Kandidat")
    if truth != candidate_truth:
        raise ValueError("Bildreihenfolge zwischen Baseline und Kandidat stimmt nicht überein.")
    gate = old_class_regression(truth, baseline_predictions, candidate_predictions, classes)
    report = {"schema_version": 1, "split": args.split, "preprocessing": PREPROCESSING,
              "baseline_sha256": BASELINE_SHA256, "candidate_sha256": sha256(args.candidate),
              "dataset_manifest_sha256": manifest_sha, "candidate_selected_epoch": metadata["epoch"],
              "torch": str(torch.__version__), "ultralytics": ultralytics.__version__, "device": str(device),
              "baseline": baseline_result, "candidate": metrics_from_predictions(truth, candidate_predictions, classes),
              "old_class_regression_gate": gate}
    write_reports(args.output, report, rows, truth, baseline_predictions, candidate_predictions, classes)
    print(f"Fertig. Alte Klassen: {gate['status']}. Bericht: {args.output / 'BERICHT.md'}", flush=True)
    return 0 if gate["passed"] else 3


def main():
    args = parser().parse_args()
    try:
        return run(args)
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

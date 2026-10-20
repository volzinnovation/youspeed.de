#!/usr/bin/env python3
"""One held-out old-class evaluation, with explicit retrospective provenance."""
import sys
from pathlib import Path
import evaluate


if __name__=='__main__':
    args=evaluate.parser().parse_args()
    if args.split!='test':
        raise SystemExit('This wrapper is reserved for the single final old-class test.')
    code=evaluate.run(args)
    path=Path(args.output)/'BERICHT.md'
    content=path.read_text().replace('unabhängigen Gruppen','Quellbild-/Duplikatgruppen (physische Unabhängigkeit nicht bestätigt)')
    note=('# Retrospektive Prüfung der 134 Bestandsklassen\n\n'
          '**Die Baseline kann diesen öffentlichen Korpus bereits im eigenen Training gesehen haben.** '
          'Die Daten wurden für dieses Beispiel neu nach Quellbild-/Duplikatgruppen aufgeteilt. '
          'Erfasst wird die Änderung gegenüber der Baseline auf diesem endlichen Bestand; '
          'keine unabhängige absolute Generalisierungsleistung. Alte physische Standorte/Fahrten sind nicht vollständig bekannt.\n\n'
          'Beide Ortstafelklassen werden im separat eingefrorenen prospektiven Beispielbestand gemessen. '
          'Alle 134 Altklassen haben hier Support. Ein Rückgang wird unverändert als REGRESSION berichtet.\n\n')
    path.write_text(note+content)
    raise SystemExit(code)

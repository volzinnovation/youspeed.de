# KI für intelligente Mobilität

**Profilprojekt IMo WS27-28 HSPF**  
**Prof. Dr. Raphael Volz**  
19. Oktober 2026 · 42 Folien · 90 Minuten · Deutsch · Neufassung v6

- [PowerPoint mit bearbeitbaren Texten und Diagrammen](output/ki-intelligente-mobilitaet-2026-10-19-de.pptx)
- [PDF für Projektion und Weitergabe](output/ki-intelligente-mobilitaet-2026-10-19-de.pdf)
- [Dozentenleitfaden mit Ablauf und Demonstrationshinweisen](PRESENTER_GUIDE.md)
- [Sprechernotizen und Quellen je Folie](SPEAKER_NOTES_DE.md)
- [Studierendenleitfaden für Einrichtung und Projektarbeit](STUDENT_GUIDE.md)
- [Bildnachweise und Herkunft](ASSET_CREDITS.md)

Die Neufassung v6 zeigt das Projekt anhand seiner Website, eine OpenStreetMap-Karte von Pforzheim, Highway-Tags mit Renderingbeispielen, Tempo 50 mit Node-/Way-Tags aus dem OSM-Verkehrszeichenwerkzeug, echte Panoramax-Annotationen, Store-Ansichten beider Apps, reale Inspector-Crops und bereits vorhandene Spurauswertungen. Die Agenda besteht aus Abschnitten ohne Minutenangaben. Der Smartphone-Teil und die Serververarbeitung werden getrennt erklärt; der geprüfte Rückfluss nach OSM schließt den Datenkreislauf.

Die drei Orakel stehen in der gewünschten Prioritätsfolge **Nutzerkorrektur → Kamera/Vision → Datenbank**. Ein bestätigter Wechsel innerorts/außerorts setzt die alte visuelle Referenz zurück. Kurze unsichere Kontextzustände sind davon zu unterscheiden. Die Präsentation beschreibt die Laufzeitlogik; App-Code und geschützte Richtlinien wurden für diese Überarbeitung nicht verändert.

Die fünf KI-Aufgaben umfassen Bildsegmentierung, länderspezifische Verkehrszeichenklassifikation, Spurerkennung, OCR und Spracherkennung mit Apple Speech beziehungsweise Vosk. Der Fotoupload wird anhand vorhandener App-Galerien erklärt: lokal prüfen, auswählen und den Upload in der App bewusst starten; anschließend Bilder im Panoramax-Webviewer annotieren. Die Bildherkunft und die Grenzen der gezeigten UI-Zustände stehen in [APP_UPLOAD_ASSETS.md](assets/de/latest/APP_UPLOAD_ASSETS.md).

## Datenbestand und Statistik

Die Ländertabelle verwendet den [Quellsnapshot vom 18.10.2026, 11:44 MESZ](source/country-statistics.json). **Modellland** bezeichnet die gespeicherte Modell-/Klassifikatorzuordnung und kein verifiziertes geographisches Aufnahmeland. Die Panoramax-Spalte zählt **importierte fertige Crops**, keine Fotos der gesamten Instanz. App-Crops und App-Sightings umfassen gespeicherte Bestände einschließlich Replay und Altbestand. Crops und Sightings sind unterschiedliche Einheiten und nicht addierbar; auch Panoramax und App-Bestand bleiben getrennte Quellen. Der Snapshot beschreibt den importierten Verwaltungsbestand bei noch laufender Panoramax-Synchronisation.

## Semesterprojekte

**A1 und A2 – Verkehrszeichenerkennung:** eigene Bilder aufnehmen, in Panoramax `osm|traffic_sign=DE:310` beziehungsweise `DE:311` menschlich annotieren und die deutsche Erkennung verbessern. Präzise Segmentierung benötigt später zusätzliche geprüfte Masken/Polygone.

**B1 und B2 – Spurerkennung:** eigene Videos im Inspector annotieren, überwacht trainierte Modelle mit der bestehenden CV-Basis vergleichen und geeignete Server-/Gerätemodelle erproben.

Jedes Team arbeitet mit eigenen Forks beider Repositories. Zum Einstieg müssen die Studierenden die App installieren und benutzen; eine eigene native App-Buildumgebung ist nicht erforderlich. Die Terminfolie enthält Kick-Off, montägliche Statusbesprechung, Projektabschluss sowie interne und öffentliche Präsentation. Der Vortrag endet mit **„Nur Fragen?“**.

## Vor der Veranstaltung

Zugänge zum privaten Analytics-Repository und zulässige private Team-Forks vorbereiten. Für Panoramax eigene Kurskonten bereitstellen und die Sichtbarkeit jedes Uploads ausdrücklich prüfen. Der Admin-Zugang wurde nur für die angeforderten Screenshots genutzt; es wurden dafür keine neuen Aufnahmen, Annotationen oder OSM-Änderungen veröffentlicht.

Für einen Live-Videotest müssen `ffmpeg -version` und `ffprobe -version` funktionieren. Bei der Vorbereitung auf diesem Mac fehlte `libx265.216`. Das vorhandene [synthetische Lane-Dataset](assets/lane-demo.zip) öffnet gespeicherte Frames ohne neue Videodekodierung. Reale hervorgehobene Spurbilder sind ebenfalls enthalten; sie ersetzen bei Bedarf eine Live-Demo.

## Quelldateien

[Inhalt](source/slides-de.mjs) und [Layout/Export](source/build-de.mjs) erzeugen die deutsche Präsentation mit bearbeitbaren Texten, Diagrammen und Tabellen. [finalize-de.mjs](source/finalize-de.mjs) dient dem erneuten Import und Rendering; [render_pdf_de.py](source/render_pdf_de.py) erzeugt die PDF zur Weitergabe.

Zum Neubau werden der gebündelte Codex-Node-Laufzeitpfad und `@oai/artifact-tool` benötigt. `RUNTIME_NODE_MODULES` muss auf dessen Paketverzeichnis zeigen. Der Finalisierer überschreibt keine bestehende Finaldatei: für weitere Revisionen einen neuen Staging-Dateinamen im Builder und im Finalisierungsskript wählen. Zwischenstände, Prüfprotokolle und frühere Revisionen liegen in `.build/` und werden nicht versioniert.

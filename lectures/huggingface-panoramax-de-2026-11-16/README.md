# Hugging Face – Modelle und Datensätze am Beispiel Panoramax

**Montag, 16. November 2026 · Deutsch · 10 Folien · ca. 20 Minuten**

Prof. Dr. Raphael Volz · HSPF. Quellen und Screenshots geprüft am 12. November 2026.

[PDF mit Vortragsdatum als Dateipräfix](output/pdf/2026-11-16-huggingface-panoramax-de.pdf) · 10 Seiten, klickbare Repository-Links und Folienlesezeichen. Der PDF-Export verwendet hochauflösende Folienbilder; die Texte bleiben in der Spaces-Präsentation bearbeitbar.

Die Präsentation folgt dem Layout und der didaktischen Struktur der bestehenden Vorlesung „Bildklassifikation mit KI“: Titel, Lernziele, konkrete Beispiele, Anwendung und kurze Partnerübung. Format 1280 × 720, Arial und Courier New, bestehende Petrol-/Creme-/Gold-Palette. Die Layoutfunktionen wurden aus der vorhandenen Vorlesungsquelle übernommen und für den kurzen Einstieg angepasst.

Die Präsentation ist in Spaces bearbeitbar und lässt sich dort als PowerPoint exportieren.

## Inhalt

1. Hugging Face
2. Lernziele
3. Models, Datasets und Spaces
4. Panoramax Model Card
5. Modellgewichte und Versionen
6. Datensatz, Labels, Lizenz und Aufteilung
7. Dataset Viewer am Kursbestand
8. Download mit fester Revision
9. Panoramax-Daten und Nachtraining
10. Partneraufgabe und Fragen

[slides.mjs](source/slides.mjs) enthält Texte, Notizen und Quellen. [author.mjs](source/author.mjs) enthält den Callback `authorBatch({presentation,input})` für die verbundene Artifact Session. `input.start` ist inklusive, `input.end` exklusive; die Titelfolie wird zuerst, weitere Folien in kleinen Gruppen angelegt. Eine von Spaces automatisch angelegte leere Startfolie muss vorab entfernt werden. Der Callback hängt Folien an; beim erneuten Aufruf auf vorhandene Inhalte achten.

Die Screenshots in `assets/` stammen von den verlinkten öffentlichen Hugging-Face-Seiten. Sie werden als Originalbilder gespeichert und erst auf den Folien auf den relevanten Bereich zugeschnitten. Der Panoramax-Dataset-Viewer meldete beim Quellencheck einen Ladefehler. Der funktionierende Kursviewer ist eine Dateivorschau, keine geprüfte Trainingsaufteilung; die Folie und ihre Notizen erläutern diese Grenze.

## Quellen und Bildnachweise

- [Hugging Face Hub](https://huggingface.co/docs/hub/index)
- [Modellkarte und Modell-Screenshot](https://huggingface.co/Panoramax/classify_de_road_signs)
- [Modelldateien](https://huggingface.co/Panoramax/classify_de_road_signs/tree/5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790)
- [Datensatzkarte](https://huggingface.co/datasets/Panoramax/classified_de_road_signs)
- [Datensatzdateien](https://huggingface.co/datasets/Panoramax/classified_de_road_signs/tree/b4856947ed7cb6312587258acc90e8cf88a4aa13)
- [Kursdatensatz und Viewer](https://huggingface.co/datasets/loffenauer/ws26_hspf_imo)
- [Data Studio](https://huggingface.co/docs/hub/data-studio)
- [CLI-Download](https://huggingface.co/docs/huggingface_hub/guides/cli)

Screenshots: Hugging Face / jeweilige Repository-Autoren, 12.11.2026. Sichtbare Panoramax-Trainingsbilder gemäß Datensatzkarte CC BY-SA 4.0; Attribution und Lizenzen des Kursbestands werden bildbezogen in dessen Manifesten geführt. Logo und Weboberfläche bleiben unverändert. Modelllizenz und Datenlizenz werden getrennt erläutert. Weitere Belege stehen in den Notizen der jeweiligen Folie.

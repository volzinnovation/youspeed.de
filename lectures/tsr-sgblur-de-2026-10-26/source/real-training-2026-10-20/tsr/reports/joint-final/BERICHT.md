# Gemeinsame Nenner für neue Ortstafelklassen

**Keine zusätzliche Inferenz.** Diese Tabelle kombiniert ausschließlich gespeicherte Vorhersagen derselben beiden Modelle.

Die Bestände haben unterschiedliche Aussagekraft: retrospektiver öffentlicher Altklassenkorpus und prospektive, durch Assistenten sichtgeprüfte Beispiele. Die getrennten Berichte bleiben maßgeblich.

3071 Crops: {'retrospective_old': 3029, 'prospective_assistant_reviewed': 42}

Alle alten Zielbilder zählen als mögliche Falschpositive für city:start/city:end. So verschweigt die City-Präzision keine Ortstafelvorhersagen auf alten Zeichen.

| Klasse | Support | Baseline P/R/F1 | Kandidat P/R/F1 |
| --- | ---: | --- | --- |
| city:start | 3 | nicht messbar / 0.0 % / 0.0 % | 100.0 % / 66.7 % / 80.0 % |
| city:end | 12 | nicht messbar / 0.0 % / 0.0 % | 100.0 % / 100.0 % / 100.0 % |

Die 134 Bestandsklassen werden zusätzlich einzeln im retrospektiven Gate verglichen. Diese gemeinsame Darstellung ist keine unabhängige repräsentative Qualitätsmessung und keine Modellfreigabe.

Kandidat SHA256: `8991ee8127f50bfb88755b2bb8b293a08433c4787c6cf96d81539e087cd87a67`
Baseline SHA256: `f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7`

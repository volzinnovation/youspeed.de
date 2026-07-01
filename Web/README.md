# Web One-Page (Projektseite)

Quellordner fuer die Kunden-Website des Forschungsprojekts.

- Quelle: `Web/`
- Publish-Ziel: `sites/` (fuer GitHub Pages)

Lokaler Publish-Lauf:

```bash
./scripts/web/publish_web_to_sites.sh
```

Statischer Smoke-Test nach dem Publish:

```bash
node ./scripts/web/check_static_site.mjs sites
```

Der Test prueft lokale Links, referenzierte Assets und In-Page-Anker im GitHub-Pages-Artefakt.

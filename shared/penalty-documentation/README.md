# Penalty lookup presentation

Both native info sheets embed this same offline document. Native wrappers supply the actual country rule JSON files (the active country's effective rule document replaces the bundled copy), app locale and current country. There are no tariff amounts in the renderer or translations. All amounts, bands, currencies, points, conditions, fee and escalation thresholds come from the supplied rule JSON, including German aliases and Dutch per-km/h tables.

The localized lookup presents structured fields already used by the app; an absent amount stays unspecified. It does not calculate new legal penalties, translate or replace external authority pages, fetch network resources, or change the reference state machine. The source link and checked date come directly from each country document. All nine Android locales have complete table labels and the non-legal-advice note; iPhone uses its four supported app locales. The same renderer covers all twelve rule countries automatically.

Run `node tests/penalty-documentation.test.cjs` from the repository root. Preview locally using `scripts/release/preview_penalty_documentation.py`, which injects the real JSON documents without generating a separate tariff copy.

# Penalty lookup behind the info button

On both apps: **Info → Penalty tables**, then choose a country and its road / posted-limit context. The offline view covers every available country rule file automatically (currently twelve). It reads the same JSON documents as the penalty engines; the active country’s effective downloaded/packaged rule document takes precedence over the bundled catalog. There is no separately authored penalty dataset, new legal tariff or network lookup.

The shared renderer handles the German field aliases, urban/rural/motorway variants, French posted-limit variants, Dutch per-km/h tariffs and Swiss posted-limit escalation. Currencies come from each file rather than being assumed EUR. Unknown amounts stay “Not specified”; explicit zero stays zero. Conditional licence restrictions are distinguished from specified restrictions, and explicit minimum restrictions use ≥. Source URLs and reviewed dates are read directly from the JSON.

All table labels and the “not legal advice” note are provided in English, German, French, Dutch, Spanish, Italian, Polish, Brazilian Portuguese and Swedish. Country names use the device’s locale. iPhone exposes its four supported languages; Android exposes all nine. This view presents existing structured JSON fields. It does not add legal calculations or claim that a missing structured amount captures every condition described on an external authority page.

The content comes from `shared/penalty-documentation/`; Swift/WKWebView and Kotlin/Android WebView are thin wrappers. Rule text is serialized as data and escaped before embedding. The page has no external scripts, fonts, requests or native JavaScript bridge. A source link opens externally only after a user tap.

Run `node tests/penalty-documentation.test.cjs`. Swift tests verify all twelve packaged countries, the effective-source override and escaped JSON injection. Native iPhone UI tests exercise Info → lookup in all four languages. Android native UI checks exercise the same entry and JSON-generated table. Native tariff regression tests are documented in `DUTCH_PENALTY_REVIEW_2026-10-02.md`.

Preview the real data without the apps:

```sh
python3 scripts/release/preview_penalty_documentation.py --locale de --country NLD --output /tmp/youspeed-penalties.html
```

## Verification on 2026-10-02

The shared renderer passed all twelve countries and every road/limit context, including equivalent menus after reversing JSON key order, changed-source propagation, missing amounts and non-EUR currencies. Native iPhone UI tests passed in all four supported languages; the source-loading and Dutch tariff tests passed on the final build. Android native UI checks passed the translated disclaimer and generated German fine rows in all nine languages, and the final build’s country selector was exercised through Netherlands → urban +4 → 37 EUR. Android’s complete debug unit suite passed 619 tests with no failures. Both debug apps built successfully. Release binaries must be rebuilt to contain this view.

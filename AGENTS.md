# Repository guidance

## Cross-platform feature parity

- iPhone is the behavioral reference for the Android app. When a feature exists on iPhone, Android must provide the same user-visible behavior, controls, settings, defaults, capture outputs, and important runtime states unless a platform limitation is documented.
- Traffic-sign pictograms must use the shared `shared/tsr/sign-pictograms/` asset set. Every display-eligible sign has an official-source SVG in `originals/` and its transparent PNG rendition in `png/`; both apps consume those shared bytes. Do not draw or substitute sign artwork in platform UI code.
- Numeric speed-limit signs are the explicit exception: their platform UI is intentionally schematic, and the numeric value is interpreted against the penalty classes and displayed speed rather than sourced as a pictogram asset.
- Before changing Android behavior, inspect the corresponding iPhone implementation and keep both implementations aligned. New Android-only features, settings, or download behavior require explicit product approval.
- Validate parity on the attached Android device when device deployment is requested. Exercise the equivalent iPhone flow where practical, and use tests for state transitions and platform-specific fallbacks.
- Bundle schemas, matchers, camera recognition, speed-limit presentation, recording, Panoramax capture, and network gating are shared product behavior. A schema or platform implementation change must be checked against both clients.

## Attached iPhone screen inspection

- Use QuickTime Player to view the attached iPhone's screen on this Mac. The user's setup is in Germany, where iPhone Mirroring is unavailable; do not attempt to use or configure iPhone Mirroring.
- In QuickTime Player, select the attached iPhone as the camera source for a New Movie Recording preview. Viewing the preview does not require starting a recording. QuickTime provides screen viewing, not touch control; use device tests or interaction on the phone when controls must be exercised.

## Speed-limit reference policy changes

The shared runtime state-machine policy in `shared/speed-limit-reference/` and
its Swift/Kotlin interpreter semantics may change only on an explicit command
from the product owner. Follow that directory's `AGENTS.md`, versioning and
approval-lock process. Bundle/model updates must not change this policy.
Developer documentation and Mermaid/Graphviz diagrams are in
`docs/speed-limit-reference/`; do not add an in-app state-machine editor/viewer.

## Git workflow

- Do not assume the default branch is `master` or `main`; inspect repository configuration first.
- Never merge, deploy, publish, or delete a branch without explicit user approval.

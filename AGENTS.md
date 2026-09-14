# Repository guidance

## Cross-platform feature parity

- iPhone is the behavioral reference for the Android app. When a feature exists on iPhone, Android must provide the same user-visible behavior, controls, settings, defaults, capture outputs, and important runtime states unless a platform limitation is documented.
- Before changing Android behavior, inspect the corresponding iPhone implementation and keep both implementations aligned. New Android-only features, settings, or download behavior require explicit product approval.
- Validate parity on the attached Android device when device deployment is requested. Exercise the equivalent iPhone flow where practical, and use tests for state transitions and platform-specific fallbacks.
- Bundle schemas, matchers, camera recognition, speed-limit presentation, recording, Panoramax capture, and network gating are shared product behavior. A schema or platform implementation change must be checked against both clients.

## Attached iPhone screen inspection

- Use QuickTime Player to view the attached iPhone's screen on this Mac. The user's setup is in Germany, where iPhone Mirroring is unavailable; do not attempt to use or configure iPhone Mirroring.
- In QuickTime Player, select the attached iPhone as the camera source for a New Movie Recording preview. Viewing the preview does not require starting a recording. QuickTime provides screen viewing, not touch control; use device tests or interaction on the phone when controls must be exercised.

## Git workflow

- Do not assume the default branch is `master` or `main`; inspect repository configuration first.
- Never merge, deploy, publish, or delete a branch without explicit user approval.

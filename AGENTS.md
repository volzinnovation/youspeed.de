# Repository guidance

## Cross-platform feature parity

- iPhone is the behavioral reference for the Android app. When a feature exists on iPhone, Android must provide the same user-visible behavior, controls, settings, defaults, capture outputs, and important runtime states unless a platform limitation is documented.
- Before changing Android behavior, inspect the corresponding iPhone implementation and keep both implementations aligned. New Android-only features, settings, or download behavior require explicit product approval.
- Validate parity on the attached Android device when device deployment is requested. Exercise the equivalent iPhone flow where practical, and use tests for state transitions and platform-specific fallbacks.
- Bundle schemas, matchers, camera recognition, speed-limit presentation, recording, Panoramax capture, and network gating are shared product behavior. A schema or platform implementation change must be checked against both clients.

## Git workflow

- Do not assume the default branch is `master` or `main`; inspect repository configuration first.
- Never merge, deploy, publish, or delete a branch without explicit user approval.

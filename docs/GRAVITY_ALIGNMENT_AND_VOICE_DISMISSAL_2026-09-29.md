# Gravity feedback and spoken camera dismissal

Implemented on iPhone and Android, 2026-09-29.

The landscape dashboard displays a noninteractive gravity indicator at its top center, between the sign and speed panes. Its bounds are 10% of the usable dashboard width and height. It requires a measured zero speed no older than three seconds and disappears on movement, stale position, or tunnel mode. Both landscape mounting orientations are supported. Sensors run at 10 Hz while the indicator is visible and the app is foregrounded.

The indicator shows roll and pitch. It does not establish vehicle heading, demand a perfectly aligned camera, or gate recognition. Green indicates a small roll/pitch deviation; other angles remain usable. Image/model compensation is separate work: gravity can supply roll/pitch, while horizontal mounting offset requires road geometry or motion estimation. This change does not claim to implement that compensation.

Driving controls disappear on measured movement, including recorder toggles, settings, galleries, downloads and touch correction. Open dashboard sheets close; queued touch actions recheck motion before execution. The dashcam preview remains attached to preserve recordings. Missing speed or a stale zero cannot unlock controls after movement; a fresh measured zero can. Initial setup remains available before the first speed observation, since location permission and a usable speed measurement are prerequisites for detecting movement.

The eye-dismissal button is removed. Each newly accepted numeric camera limit offers one four-second local microphone window. Commands are German **Falsch**, English **Wrong**, French **Faux**, and Dutch **Fout**, matching the four bundled Android Vosk languages. A small text indicator appears while listening. Android uses Vosk; iPhone uses its existing Apple on-device recognizer with server fallback disabled. Permission preparation happens at a verified stop, never on sign detection.

Only a completed, exact command for the current visual evidence invokes the existing dismissal action. Partials, negated/longer phrases, callbacks for older signs, and expired windows cannot dismiss the current sign. Repeated frames and passage finalization do not reopen the same window. Sign speech/tone may delay listening for at most three seconds; microphone capture lasts four seconds, with up to 350 ms for final-result delivery. Manual speech capture, backgrounding and runtime invalidation cancel the window. The iPhone listener selects the built-in microphone and restores its prior audio configuration afterward.

No speed-limit-reference policy files are changed by this feature. Dismissal reuses the existing camera-clearing action and its road-reference fallback, preserving higher-priority explicit corrections.

## Validation

- Android debug APK builds; all 419 JVM unit tests pass, including geometry, stationary freshness, motion lock, language coverage, bounded windows and stale ownership.
- iPhone simulator build, 16 focused unit tests and 2 UI tests pass, covering geometry, motion lock, voice window behavior, road fallback, both moving dashboard orientations, and stationary settings/mount changes.
- Physical sensor accuracy, acoustic recognition with road noise, microphone routing with CarPlay, and recording coexistence still require a device trial. No attached device was installed, restarted or terminated; the Android Panoramax upload was left running.

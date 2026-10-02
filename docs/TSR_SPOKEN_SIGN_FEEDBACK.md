# Spoken secondary traffic signs

Android and iPhone provide four traffic-sign feedback choices:

- Speak speed only (the existing stored spoken-speed setting)
- Speed and other signs (new, opt-in)
- Notification sound (the unchanged default)
- Silent

The combined mode automatically announces reviewed **displayed** secondary
pictograms. It requires recognition and the existing “Show recognized sign”
setting. There is no tap action or explanation screen. Existing installations
retain their settings, and other-sign display remains off by default.

## Speech contract

The shared national class catalogs supply an optional `speech` dictionary with
German, English, French and Dutch phrases. `label` remains the human-readable
name. Speech never falls back to a classifier ID, an unreviewed label or another
language. An unavailable matching TTS voice leaves the secondary sign silent.
Catalog metadata does not expand the classifier vocabulary, change artwork,
change country rollout gates, or activate any road/speed rule. Ambiguous
class-to-pictogram mappings remain silent; catalog review metadata records why.

Only accepted, current-session live observations can speak. The car must be
moving at least 1 km/h. A fresh observation must be no more than two seconds old
and cannot be future-dated or out of order. Continuous observations of a class
never repeat its announcement: the same class rearms only after eight seconds
without an accepted observation. Different secondary announcements are at least
three seconds apart. Stationary, capture and busy-speech observations still
refresh visibility, preventing a false repeat when moving or listening resumes.

Secondary speech has no pending announcement queue. Busy observations can only
speak if a later, fresh frame still shows that sign. Confirmed speed feedback
has priority and replaces older traffic speech. User voice correction cancels
pending speech and blocks new secondary announcements. Pending and active
vision-dismissal voice windows also take priority over secondary speech. Lifecycle, model
and preference boundaries invalidate pending speech; ordinary road/city context
updates preserve repeat suppression while canceling the obsolete utterance.

## Validation

Native unit coverage is in `SpeedConsumerTests.swift` and
`SecondaryTrafficSignSpeechTests.kt`. It covers stored modes, reviewed-language
lookup, missing metadata, freshness, delivery ordering, repeated/alternating
classes, standstill, capture/busy speech, spacing and lifecycle reset.

Run the shared checks without native SDKs:

```sh
python3 -m unittest tests.tsr.test_sign_speech_catalog -v
python3 scripts/speed_limit_reference/check.py
python3 scripts/check_mobile_rules.py
```

Run the Android unit suite with the repository's pinned German JVM locale:

```sh
cd android
./gradlew :app:testDebugUnitTest -Duser.language=de -Duser.country=DE
```

Run the iOS simulator suite via the repository's normal consumer app build and
`xcodebuild test` workflow. Shared catalog tests check immutable classification
and artwork fields, speech language completeness, and explicit safe omissions.

Before release, exercise both physical apps with each language and mode:

1. Confirm an existing sound/silent/speed-only installation keeps its choice
2. Enable combined speech and sign display; drive a known warning/parking/
   prohibition sequence, checking the spoken phrase against the displayed icon
3. Keep one sign visible while stopped, then resume; it must not repeat
4. Alternate visible signs quickly; secondary audio must not accumulate
5. Confirm a speed sign while secondary audio is pending/playing; speed wins
6. Begin manual voice correction or an automatic vision-dismissal listening/
   recognition-drain window; secondary speech must not interrupt either. Change
   country, stop recognition, background the app or disable sign display;
   obsolete secondary speech must not continue
7. Inject stale and replay callbacks; they must not speak. Wrong-session and
   out-of-order callbacks must not speak or replace the current pictogram

A source-only review cannot verify pronunciation, audio routing, interruptions,
layout, native compilation or device timing. Those checks require the platform
SDKs and device/simulator runs; no new accuracy claim is implied by metadata.

# Launch Threads

Date: 2026-03-12

This board turns the aggressive Germany launch plan into active parallel workstreams.

## Active tracks

| Track | Window | Status | Current thread | Primary outputs |
|---|---|---|---|---|
| [Track A](./TRACK_A_PAPER.md) | `2026-03-12` to `2026-04-05` | active | refresh evidence and decide submit or defer | `youspeed.de-paper/itsc2026/`, `youspeed.de-paper/personalized_matching_arxiv/` |
| [Track B](./TRACK_B_SEED_AND_MATCHER.md) | `2026-03-12` to `2026-03-23` | active | freeze Karlsruhe seed baseline and close launch-critical matcher defects | `iphone/SpeedConsumerApp/`, bundle artifacts |
| [Track C](./TRACK_C_GERMANY_PIPELINE.md) | `2026-03-12` to `2026-04-20` | active | build and validate Germany shard full-bundle release set | `scripts/map/`, release manifests |
| [Track D](./TRACK_D_IPHONE_LAUNCH.md) | `2026-03-20` to `2026-05-01` | active | switch iPhone launch behavior to Germany-first discovery | `iphone/SpeedConsumerApp/` |
| [Track E](./TRACK_E_ANDROID_ALPHA.md) | `2026-03-12` to `2026-05-22` | active | stand up Android alpha foundation against the same manifest contract | `android/` or equivalent scaffold |
| [Track F](./TRACK_F_RELEASE_SURFACE.md) | `2026-04-21` to `2026-05-22` | active | align App Store, website, and public launch surface to real scope | `sites/`, App Store metadata |

## Operating rules

- Keep all six tracks live; do not collapse the plan back into a single serial queue.
- Protect the launch contract: Germany-only, iPhone-first, full bundles only at launch.
- Treat `delta_index` as optional for launch safety.
- If paper work and noncritical polish conflict, paper wins.
- Android work starts now, but Android release parity does not become a May 22 launch gate.

## Daily cadence

- Update each track with `now`, `next`, `blocked`, and `exit criteria`.
- Move evidence and outputs into the target path named in the track.
- If a track slips, cut scope in that track before stealing time from launch-critical tracks.

# YouSpeed Gantt Chart

Date: 2026-03-12

This chart visualizes the aggressive Germany launch plan defined in `PROJECT_PLAN_2026-03-12.md`.

```mermaid
gantt
    title YouSpeed aggressive Germany launch plan
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d

    section Milestones
    M0 Launch contract locked          :milestone, m0, 2026-03-14, 1d
    M1 Karlsruhe seed baseline frozen  :milestone, m1, 2026-03-23, 1d
    M2 Paper submit or defer           :milestone, m2, 2026-04-05, 1d
    M3 Full-bundle recovery validated  :milestone, m3, 2026-04-05, 1d
    M4 Germany shard set validated     :milestone, m4, 2026-04-20, 1d
    M5 iPhone launch candidate         :milestone, m5, 2026-05-01, 1d
    M6 App Store submission            :milestone, m6, 2026-05-08, 1d
    M7 Preferred go-live               :milestone, m7, 2026-05-15, 1d
    M7b Hard go-live deadline          :milestone, m7b, 2026-05-22, 1d
    M8 Android alpha checkpoint        :milestone, m8, 2026-05-22, 1d

    section Track A Paper-critical evidence
    Route evaluation and paper decision :crit, a1, 2026-03-12, 2026-04-05

    section Track B Karlsruhe seed and matcher hardening
    Seed rebuild and hardening          :active, b1, 2026-03-12, 2026-03-23

    section Track C Germany shard data pipeline
    Germany shard full-bundle pipeline  :c1, 2026-03-12, 2026-04-20

    section Track D iPhone Germany launch path
    Germany discovery and launch path   :d1, 2026-03-20, 2026-05-01

    section Track E Android internal alpha
    Android alpha foundation            :e1, 2026-03-12, 2026-05-22

    section Track F App Store and release surface
    Store package, website, FAQ         :f1, 2026-04-21, 2026-05-22
```

## Notes

- Launch is public, Germany-only, and iPhone-only on `2026-05-22`.
- Germany launch is nationwide via shards, but launch-day update policy is full bundles only.
- Android starts immediately as a parallel internal-alpha track, but Android release parity is not a May 22 gate.
- Paper work keeps priority over noncritical launch polish if time conflicts emerge.

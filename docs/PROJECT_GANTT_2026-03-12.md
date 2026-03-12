# YouSpeed Gantt Chart

Date: 2026-03-12

This chart visualizes the workstreams and milestone deadlines defined in `PROJECT_PLAN_2026-03-12.md`.

```mermaid
gantt
    title YouSpeed workstreams and milestone deadlines
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d
    excludes weekends

    section Milestones
    M0 Baseline lock                   :milestone, m0, 2026-03-16, 1d
    M1 Karlsruhe seed RC               :milestone, m1, 2026-03-23, 1d
    M2 Karlsruhe incremental validated :milestone, m2, 2026-04-05, 1d
    M3 Supported-region set live       :milestone, m3, 2026-04-26, 1d
    M4 Cross-region incrementals live  :milestone, m4, 2026-05-31, 1d
    M5 Android parity                  :milestone, m5, 2026-07-12, 1d
    M6 Release prep complete           :milestone, m6, 2026-08-16, 1d
    M7 Launch window closes            :milestone, m7, 2026-08-31, 1d

    section W1 Seed data and bundle generation
    Karlsruhe full-bundle regeneration :active, w1a, 2026-03-12, 2026-03-18
    Seed DB rebuild and baseline lock  :w1b, 2026-03-18, 2026-03-23
    Supported-region full bundles      :w1c, 2026-04-06, 2026-04-26

    section W2 iPhone runtime quality
    Device validation and drive tests  :active, w2a, 2026-03-12, 2026-03-23
    Seed-breaking fixes                :w2b, 2026-03-16, 2026-03-23
    Incremental-sync hardening         :w2c, 2026-03-24, 2026-04-05

    section W3 Incremental update system
    Karlsruhe delta-chain validation   :w3a, 2026-03-24, 2026-04-05
    Cross-region incremental rollout   :w3b, 2026-04-27, 2026-05-31

    section W4 Regional scale-out
    Supported-region expansion         :w4a, 2026-04-06, 2026-04-26
    Regional operations stabilization  :w4b, 2026-04-27, 2026-05-31

    section W7 Publications
    Matching paper submit or defer     :crit, w7a, 2026-03-12, 2026-04-05
    Architecture paper alignment       :w7b, 2026-03-12, 2026-05-31
    SotM application/system prep       :w7c, 2026-04-06, 2026-05-31

    section W6 Android
    Android architecture and seed port :w6a, 2026-06-01, 2026-06-21
    Android supported-region parity    :w6b, 2026-06-22, 2026-07-12

    section W5 Distribution and release
    Store, legal, and release QA       :w5a, 2026-07-13, 2026-08-16
    Website correction to real links   :w5b, 2026-07-27, 2026-08-16
    Public launch window               :w5c, 2026-08-17, 2026-08-31
```

## Notes

- `W5` starts after Android parity because the public website and store CTAs should only follow real store deliverables.
- `W7` starts early because the matching paper depends on the Karlsruhe seed phase, not on the later multi-region product rollout.
- `W3` and `W4` overlap intentionally after Karlsruhe validation; by then the work shifts from proving one region to operating a supported set.

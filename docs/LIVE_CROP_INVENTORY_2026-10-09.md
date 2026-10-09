# Live crop inventory and exit triage — 2026-10-09

The restored VPN allowed the first complete read-only inventory for #27/#28.
There are **1,801 provenance-qualified live crops**, including **201 near mapped exits**.
This provides a useful review population. It does not yet establish which signs
govern the driver's road or whether lane guidance improves that decision.

## Population and location

The source is the management database, captured at **17:49:26 UTC** in a single
repeatable-read, read-only transaction using the report role. Both consent scopes,
expiry and deletion barriers were checked. The contiguous control state was 263
seconds old, within the existing 900-second bound. This is a snapshot, not a claim
that consent remains current indefinitely.

| Population | Crops |
| --- | ---: |
| Retained media, active and consented at capture | 7,253 |
| Excluded archive/video replay | 5,452 |
| Excluded unknown provenance | 0 |
| Eligible live crops | 1,801 |
| Source identity/binding failures | 0 |

All source pages reconcile in the original read-only capture receipt. Live provenance
is classified from recorded metadata using `live-crops-only-v1`; camera origin is
not independently authenticated. Replay rows were classified
for exclusion counts but were not retained in the offline analysis inputs. The
7,253-row total and 5,452 exclusions are attested by the original capture receipt;
the excluded stream cannot be independently reconstructed from the retained files.
An independent check verified every retained source/context binding and reproduced
all 1,801 geographic results exactly, as well as the full selected queue membership.

Of the live crops, **1,535** have a location on the crop itself; **266** use the
legacy observation fallback because the crop field is absent. All 1,801 satisfy
the existing maximum 50 m uncertainty and 2-second frame/fix alignment checks.
These are metadata consistency checks, not independent GPS accuracy measurements.
Explicit null crop locations would remain unknown rather than using fallback.

The population is strongly unbalanced: **1,763 iPhone and 38 Android crops**, across
9 collection sessions, 2 installation epochs and capture dates October 5–8.
Repeated crops link to **1,112 observation identities**. These are source lineage
groups, not 1,112 independently reviewed physical signs or encounters.

## Offline geographic context

The frozen Baden-Württemberg extract is dated September 13. Its directed exit
index and the existing 500 m radius were used without tuning against these crops.
The complete search buffer includes bounded position uncertainty and projection
margin. Missing coverage and known topology gaps remain unknown.

| Context | Crops | Share of live crops |
| --- | ---: | ---: |
| Near a mapped directed exit | 201 | 11.2% |
| No mapped exit in a fully covered search buffer | 858 | 47.6% |
| Unknown | 742 | 41.2% |

Unknown comprises **738 coverage gaps** and **4 topology gaps**. Missing coverage
is not a negative example. Classification-country predictions are not evidence of
map coverage. The map is retrospective, may be incomplete or stale, and its source
association was checked by the assistant. Near-exit status describes proximity of
the vehicle location; it does not assign a sign to an exit, establish the driver's
carriageway, or identify a taken exit.

Both bounded pages were staged without database persistence. Every staged source,
configuration, index and result is hash-bound. Repeating the same analysis must
retain these identities; a larger map region requires a separately versioned run.

## What still prevents sign-relevance evaluation

Every retained crop has a valid manifest-to-observation link. None appears in the
linked observation's reciprocal `media_refs`, and the current published catalog
has **zero links to these eligible observations**. A missing reciprocal reference
does not invalidate later crops, but neither linkage route provides independently
reviewed physical-sign/site truth.

Surrounding live-capture frames/video, exposure-time mapping, driver trajectory,
governing road, class truth and repeated-site grouping have not been verified.
No crop pixels were reviewed in this inventory. Source frame hashes and opaque
frame tokens alone do not establish retrievable surrounding video. Tight crops
cannot answer missed-sign recall or reveal the road a sign governs.

The prepared review queue remains **development-only**, with
`training_ready=false`, `acceptance_eligible=false`, and unverified encounter
grouping. Near-exit, unknown and mapped non-exit strata are useful selection aids;
taken/untaken exit, simultaneous-sign and overhead/supplementary categories must
remain unfilled until surrounding evidence supports them. There is no measured
class accuracy or wrong-road rejection benefit yet.

The initial queue contains **40 observation-lineage groups / 57 crops**: 20 near
mapped exits, 12 mapped non-exit controls and 8 unknowns. It uses deterministic
source-key hash ordering with session round-robin selection, without classifier
confidence selection. All 9 available sessions are represented; 29 groups are
iPhone and 11 Android. All three proximity quotas are met, but none of the
governing-road/trajectory categories is verified. This deliberate review selection
does not estimate prevalence or platform accuracy. All crops belonging to a
selected observation are retained together; reviewed physical-site grouping is
still required before any evaluation split.

## Deployment and priorities

Read-only schema inspection confirms that `crop_reviews`, `crop_exit_contexts`
and the live-source SQL predicate are absent. The backend configuration records
revision `5421cb15073cc7abfc3ac01bdc9943207a1fe407`; this is not attestation of
running container/image identity. Docker inspection is denied to the SSH account,
and noninteractive sudo requires authentication.

An administrator rollout plan has been prepared, covering running-image attestation,
current grants, a YouSpeed-only backup and current deletion ledger, migrations
005/006, explicit role grants, separate review credentials, Inspector replacement,
private smoke checks and rollback. The configured revision to the target backend
`441be34` includes optional crop GPS and shared-runtime health/memory changes;
it cannot be treated as an isolated Inspector update. Reverting to the older strict
intake may reject crop GPS fields from newer clients. No rollout occurred.

Priority remains:

1. Qualify and approve the backend/Inspector rollout, then enable durable class
   review and persist contexts only after current lifecycle/source checks.
2. Start road-context triage from the recorded way, travel bearing and repeated
   crops; [the new phone-match extension](CROP_PHONE_ROAD_MATCH_2026-10-09.md)
   supplies direct way lookup for future captures. The current snapshot already
   has 266 multi-crop observation groups with crop-level course. Review the
   development queue, using surrounding live frames for unresolved cases. Report
   category shortfalls and resolve physical-sign/site groups before any future
   split. Expand regional map coverage only as a separate pinned run.
3. Qualify native exposure/context and whole-frame guard/display/passage behavior
   under #13/#15, using the reviewed simultaneous-sign cases.
4. Compare native, Hough, semantic-guided and reviewed geometry on identical
   qualified encounters. Keep further lane training conditional on measured
   sign-relevance benefit.

No production database writes, container changes, phone activation, additional
training or protected speed-reference policy changes occurred.

## Evidence identities

Private source records and coordinates stay outside Git. The executed capture and
analysis code, full population/page receipts and immutable staged result receipts
are retained privately; future use must recheck current consent, expiry and deletion.

- Backend source revision: `441be34ea151669b3caef7973210837f885d25b0`.
- Snapshot receipt SHA-256: `9880ca68b7ee28bc29eab3fd2dbddcf1b82c554936959369c18d1d10e4f71db5`.
- Map index SHA-256: `8288006df7775f9a7b96b315ea45d3d74cd47cf1622b85c7df1e94dd23c9e2a6`.
- Aggregate analysis SHA-256: `2717ae61fa2d75b29d7c8382f604840a06684b673ae05820e9c9b463a61e8929`.

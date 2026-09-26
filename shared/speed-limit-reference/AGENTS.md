# Speed-limit reference policy governance

The product owner explicitly requires that this model change only on their
explicit command. Do not change policy semantics, thresholds, priority, expiry,
outputs, or the active policy version as incidental maintenance, bundle work,
model retraining, automated tuning, or a release upgrade.

- A requested policy change must name the changed behavior in the changelog.
- Keep published versioned artifacts immutable. Add a new version and update
  the approval lock only for an explicitly requested policy change.
- Keep the implementation snapshot separate from the target model. Never label
  a target behavior as implemented without controller-level parity validation.
- Both apps must read the same packaged bytes. Downloaded road bundles and TSR
  packs must not supply or modify this policy.
- Run `python3 scripts/speed_limit_reference/check.py` after any change here.
- This instruction governs policy edits, not normal driving-state transitions.

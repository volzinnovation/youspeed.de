# Speed-limit reference runtime policy

- `policy-v1.1.0.json`: runtime EFSM shared by both apps; speech > applicable
  camera > applicable bundle; ordinary expiry at 5 km or 300 seconds.
- `current-v0.1.0.json`: descriptive implementation snapshot at `99d62f2`, before
  integrating the runtime policy, with the September 26 device findings.
- `scenarios-v1.1.0.json`: shared conformance corpus for Python, Swift and Kotlin.
- `approval-lock.json`: immutable-version hashes, pinned in both app loaders.
- [MODEL.md](../../docs/speed-limit-reference/MODEL.md): formal semantics,
  external pipeline boundary, future conditional restrictions, runtime mapping,
  standard Mermaid/Graphviz visualization and known remaining work.

There is no in-app model display/editor. Only the product owner's explicit
command authorizes policy changes; see AGENTS.md and CHANGELOG.md.

Run `python3 scripts/speed_limit_reference/check.py` from the repository root.
The checker never rewrites artifacts or updates hashes automatically.

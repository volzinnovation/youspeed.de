# Data Manager release metadata

Both clients read the fixed GitHub release asset
`releases/download/bundle-metadata/bundle-metadata.v3.json` in the repository
specified by their bundled target configuration. This small index gives all
configured regions their bundle creation dates, versions and download sizes
before their maps are downloaded. Sizes are compressed transport bytes,
summed across parts when a database is split.

The contract is `mapdata/spec/v3_bundle_metadata.schema.json`. Entries are keyed
by the same `country|region` IDs as the apps and matched against each configured
manifest URL. Missing entries do not prove that a bundle is unavailable.
Individual manifest checks and installation validation remain authoritative.
On opening Data Manager, both apps restore a validated snapshot from their
cache before requesting the release index. Snapshots are isolated by source URL,
survive app restarts, and remain useful offline. Fresh entries are marked
available for 15 minutes, avoiding separate manifest checks for every selection.
The apps preserve existing details when an index request fails and omit absent
size/date fields instead of displaying “Unknown”. Invalid refreshes cannot
replace the last valid snapshot, and metadata is accepted only for configured
bundle IDs with matching manifest URLs. Current manifest checks at download time
remain mandatory.

`Refresh Bundle Metadata` rebuilds the full index after successful bundle
build/release workflows. Its concurrency group serializes updates; each run
reads current published manifests for every configured region instead of
merging local partial results. Malformed manifests, network errors and an empty
result abort publication. Only confirmed HTTP 404/410 manifests are omitted.
The workflow also supports manual dispatch to bootstrap the asset or refresh
it after a manual release update. The workflow must be on the default branch
for automatic `workflow_run` triggers.

Generate a reviewable index without publishing anything:

```sh
python3 scripts/map/build_v3_bundle_metadata.py --out-json /tmp/bundle-metadata.v3.json
```

The generator follows manifest URLs only and never fetches database assets.
Deploying the workflow or publishing its initial release asset requires the
repository's explicit user approval. Existing installations continue to use
selected-region manifest checks until the metadata asset is available.

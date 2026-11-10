# Immutable 134-class expansion source

These JSON files preserve the contracts used to construct the 142-class German
classifier. `catalog.json` is the 134-output shared catalog with reviewed
reference metadata captured before the 142-class deployment. `model-pack.json`
is the corresponding iPhone manifest, including the original 134 semantic
mappings and checkpoint identity. Model weights are not duplicated here.

`scripts/tsr/build_de_expanded_catalog.py` pins and verifies both SHA-256 hashes
before generating a candidate. Updating deployed catalogs or manifests must not
change these files. A future baseline needs a new directory and explicit pins.

| File | SHA-256 |
| --- | --- |
| `catalog.json` | `caf88cdb00e3826867d5feb657c3065d66d8a48f1c289e165f6e717e46e953ad` |
| `model-pack.json` | `7d5d679d1ad7f9a5036b7837f92b875154d93c85cba772d13f73992fd87debbd` |

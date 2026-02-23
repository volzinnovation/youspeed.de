# Tile/Segment Asset Format (v2)

Date: 2026-02-23
Status: Proposed for implementation
Scope: On-device speed-limit map assets for iOS runtime, independently updatable from app binary.

Machine-readable contract files:
- `mapdata/spec/catalog.v2.schema.json`
- `mapdata/spec/tile_manifest.v2.schema.json`
- `mapdata/spec/examples/catalog.v2.example.json`
- `mapdata/spec/examples/tile_manifest.v2.example.json`
- validator: `scripts/map/check_tile_assets_v2.py`

## 1) Goals

- Reduce on-device query latency by loading only local data near current GPS location.
- Keep runtime memory stable by avoiding country-wide JSON parse/scan.
- Support independent data updates (daily/weekly) without shipping new app binary.
- Keep deterministic build and hash-verifiable artifacts.

## 2) Grid and Tiling

### 2.1 Tile grid

- Grid CRS: `EPSG:3857` (Web Mercator meters).
- Tile size: `1024m x 1024m`.
- Tile id format: `{tile_x}/{tile_y}`.

Rationale:
- At max driving speed (`250 km/h` ~= `69.4 m/s`), movement per second is ~70m.
- A 1km tile spans ~14s at max speed and enables stable prefetch windows.

### 2.2 Runtime window

- Active window default: `3x3` tiles centered around current tile.
- High-speed prefetch: extend to `5x3` in heading direction when speed > 120 km/h.

## 3) Delivery Model (Independent of App Binary)

### 3.1 Two-level metadata

1. `catalog.v2.json` (global/channel manifest)
- Contains app compatibility, region metadata, and list of available tile manifests.

2. `tile_manifest.v2.json` per tile
- Contains chunk table, tile bbox, counts, hashes, and packaging metadata.

### 3.2 Binary payload per tile

- Tile payload object: `tilepack` binary (single file), immutable and content-addressed.
- URL pattern (example):
  - `https://cdn.youspeed.de/map/v2/tiles/{tile_id}/{tile_content_sha256}.tilepack`

### 3.3 Update channels

- Channels: `stable`, `canary`.
- App points to one channel URL (remote config), independent of app bundle.
- App downloads only tiles whose `content_sha256` changed.

### 3.4 Signing and integrity

- `catalog.v2.json` and each `tile_manifest.v2.json` must be signed by backend key.
- App verifies signature before trusting metadata.
- App verifies `sha256` for each downloaded tilepack.

## 4) File Contract

## 4.1 `catalog.v2.json`

Required fields:
- `schema_version`: `2`
- `region`: string (e.g. `germany`)
- `generated_at_utc`: RFC3339 UTC
- `app_compat`: object
  - `min_data_runtime_version`: integer
  - `max_data_runtime_version`: integer
- `tile_grid`: object
  - `crs`: `EPSG:3857`
  - `tile_size_m`: integer >= 256
- `channels`: array of strings
- `tiles`: array of tile entries

Tile entry fields:
- `tile_id`: `x/y` (both integer strings, example: `164/1619`)
- `tile_manifest_url`
- `tile_manifest_sha256`
- `content_version` (monotonic per tile)
- `content_bytes`
- `content_sha256`
- `bbox_wgs84`

## 4.2 `tile_manifest.v2.json`

Required fields:
- `schema_version`: `2`
- `tile_id`: `x/y` (both integer strings)
- `content_version`
- `generated_at_utc`
- `tile_pack_url`
- `tile_pack_bytes`
- `tile_pack_sha256`
- `bbox_wgs84`
- `stats`
  - `segment_count`
  - `node_count`
  - `area_count`
- `chunks`: ordered list

Each chunk entry:
- `name`: one of
  - `segment_index`
  - `segment_geom`
  - `speed_rules`
  - `adjacency`
  - `area_index`
- `offset`: uint64
- `length`: uint64
- `codec`: one of `raw`, `zstd`

Chunk constraints:
- Offsets must be strictly increasing.
- Chunks must not overlap.
- Last chunk end (`offset + length`) must be <= `tile_pack_bytes`.

## 4.3 `tilepack` binary layout (v2)

Little-endian binary, chunked:

Header (fixed 64 bytes):
- magic[8]: `YSPDTPK2`
- version_u16
- flags_u16
- tile_x_i32
- tile_y_i32
- tile_size_m_u16
- reserved_u16
- chunk_count_u32
- segment_count_u32
- area_count_u32
- crc32_u32
- reserved[28]

Then chunk directory entries:
- `chunk_name_u16`
- `codec_u8`
- `reserved_u8`
- `offset_u64`
- `length_u64`

Then raw chunk payloads (possibly compressed by chunk codec).

## 5) Segment Data Model in tilepack

`segment_index` chunk (spatial buckets -> segment ids)
- Uniform local grid (e.g. 64x64 within tile).
- For each cell: varint count + delta-coded segment ids.

`segment_geom` chunk
- Segment id -> point list (delta-coded int32 microdegrees or local meter grid int32).
- Includes `approx_heading_deg` and bbox for quick reject.

`speed_rules` chunk
- Segment id -> speed attributes:
  - explicit maxspeed numeric
  - speed source/type tags
  - conditionals (optional compact encoding)

`adjacency` chunk
- Segment graph edges for incremental route continuity.

`area_index` chunk
- Built-up context candidates for default 50/100 fallback.

## 6) On-device Runtime Behavior

1. Resolve current tile from GPS.
2. Ensure active window tiles are available locally.
3. Query candidate segments from `segment_index` of active tiles.
4. Score with heading + distance; optional polyline refinement.
5. Keep previous match and adjacency continuity to avoid full search per fix.
6. Apply precedence: camera > map explicit > defaults.

## 7) Asset Storage in iOS App

- App bundle contains only bootstrap seed data (optional minimal region or no map).
- Downloaded tile data lives in app sandbox:
  - `Application Support/MapAssets/v2/<region>/<tile_id>/...`
- Keep app binary and map data lifecycle independent:
  - app updates do not force map redownload
  - map updates do not require app release

## 8) Update Workflow

1. App fetches `catalog.v2.json` for current channel.
2. Validate signature and compatibility.
3. Compare local tile state (`tile_id + content_sha256`).
4. Download changed `tile_manifest.v2.json` and `tilepack` only.
5. Verify hashes, atomically swap tile.
6. Garbage-collect orphaned tiles after successful swap.

## 9) Failure / Safety Policy

- If catalog signature fails: keep current local assets.
- If tile download/hash fails: keep previous tile.
- If no map tile available: fall back to camera + legal defaults.
- No hard dependency on network while driving.

## 10) Performance Targets

- Query p50 under 150ms (urban tile windows) on target iPhones.
- Query p95 under 300ms in dense city traffic.
- Tile update bandwidth proportional to changed local tiles, not country size.

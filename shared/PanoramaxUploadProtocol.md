# Panoramax client contract

The iPhone and Android clients share this protocol boundary instead of trying
to embed the Python CLI. The CLI is a useful reference implementation, but it
also contains terminal UX, filesystem reports, migration and download
commands that do not belong in a mobile app.

## Authentication

1. Normalize and require an HTTPS instance origin.
2. `POST /api/auth/tokens/generate` creates a token.
3. Open the returned claim link so the user can associate the token with their
   Panoramax account.
4. Store the token only in the platform secure store (iOS Keychain; Android
   Keystore-backed encrypted storage).
5. Validate with `GET /api/users/me` and send it as `Authorization: Bearer`.

There is no YouSpeed-wide API key. Credentials are instance-specific.

## Upload set

The platform adapters implement the same sequence:

```text
POST /api/upload_sets                         {title, estimated_nb_files}
POST /api/upload_sets/{id}/files              multipart field: file
POST /api/upload_sets/{id}/complete
GET  /api/upload_sets/{id}                     poll until ready/complete
```

Only user-included originals are sent. The local queue records the remote
upload-set ID and per-item state so a partial upload can be retried without
discarding captures.

## Image metadata

Every original must be a JPEG with EXIF GPS latitude/longitude, capture date,
and (when available) `GPSImgDirection`. The capture cadence is a separate
policy: a new image requires movement of at least `max(configured distance,
2 × max(previous accuracy, current accuracy))`.

## Platform split

`shared/` defines this wire/state contract. Swift and Kotlin own camera APIs,
secure credential storage, local queue persistence, and their platform upload
transport. This keeps the mobile apps small while remaining compatible with
the Panoramax CLI and API.

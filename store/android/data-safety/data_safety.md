# Google Play Data Safety Draft

Use this as the human-readable source for the Play Console Data safety form.

## Data Collection

- Location: precise location is used for app functionality while the app is active. Routine location processing is on device.
- Audio: microphone input is used for optional spoken speed-limit capture on device.
- User content: optional local speed-limit observations can be exported by the user.
- Diagnostics: optional exported logs can include precise coordinates, road candidates, and app diagnostics.

## Sharing

- No advertising or analytics sharing.
- User-initiated exports can be shared outside the app by the user.
- Public map bundle downloads contact GitHub/CDN hosts for app functionality.

## Security

- Data is stored locally in app-private storage.
- Android backup is disabled for the app.
- Production builds do not include a private GitHub release token.

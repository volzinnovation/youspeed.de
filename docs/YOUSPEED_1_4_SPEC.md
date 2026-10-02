# YouSpeed 1.4 traffic sign collection specification

Version 1.4 adds a central service for collecting traffic sign sightings from
the iPhone and Android apps and deriving a nationwide sign catalog and
geographic analytics. Submissions identify the contributing app installation
with a device ID; contributors do not need a user account.

The canonical product and technical specification belongs to the backend
repository:

- [YouSpeed 1.4 traffic sign backend specification](https://github.com/volzinnovation/Woladen.de-analytics/blob/main/docs/youspeed/YOUSPEED_1_4_TRAFFIC_SIGN_BACKEND_SPEC.md)
- Local checkout: [`../../Woladen.de-analytics/docs/youspeed/YOUSPEED_1_4_TRAFFIC_SIGN_BACKEND_SPEC.md`](../../Woladen.de-analytics/docs/youspeed/YOUSPEED_1_4_TRAFFIC_SIGN_BACKEND_SPEC.md)

The GitHub link becomes available when the specification is committed and
pushed. The local link supports review in adjacent repository checkouts.

## Requested scope

- Record sign class, GPS position, observation time, and model classification
  score, attributed to the submitting device ID.
- Buffer submissions durably on both platforms and retry after network outages
  or offline operation.
- Distinguish individual sightings from inferred physical signs so analytics
  can count signs within an area, sightings per sign, and signs of a given type.
- Host intake and API services on the infrastructure for
  `live-eu.woladen.de`, with the database and analytics workload on `volz-db`.
- Keep backend code, migrations, processing, analytics, and deployment
  configuration in `Woladen.de-analytics`.

## Mobile implementation constraints

iPhone remains the behavioral reference. Android must provide equivalent
collection settings, defaults, queue behavior, and visible synchronization
states. The specification records proposed defaults separately from the
requirements above.

Collection must cover recognized sign classes beyond actionable speed-limit
passages. A separate collection contract must observe recognition evidence
without modifying the governed
[`shared/speed-limit-reference/`](../shared/speed-limit-reference/README.md)
runtime policy. Existing recognition and passage contracts remain separate:
[`shared/tsr/`](../shared/tsr/README.md).

Sign metadata collection must remain separate from reviewed Panoramax media
uploads and their
[`shared/PanoramaxUploadProtocol.md`](../shared/PanoramaxUploadProtocol.md)
contract. Version 1.4 changes to collection disclosure and store privacy
information must accompany implementation; this specification does not enable
collection in existing app builds.
